"""
V3 Multibagger Engine - 10-Year Backtest Module
Executes institutional-grade backtesting of the V3 Multibagger strategy on weekly bars.
"""

import sys
import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from config import (
    STARTING_CAPITAL,
    INITIAL_ALLOCATION_PCT,
    PYRAMID_ALLOCATION_PCT,
    PYRAMID_TRIGGER_GAIN_PCT,
    MAX_TICKER_ALLOCATION_PCT,
    TRANSACTION_COST_PCT,
    EXIT_MA_THRESHOLD_PCT,
)
from data_loader import (
    fetch_nifty500_tickers,
    batch_fetch_weekly_universe,
    fetch_regime_index_weekly,
)
from strategy import (
    compute_weekly_indicators,
    compute_market_regime,
)

logger = logging.getLogger("V3Backtest")


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    initial_shares: int
    initial_invested: float

    # Pyramiding details
    is_pyramided: bool = False
    pyramid_date: Optional[pd.Timestamp] = None
    pyramid_price: float = 0.0
    pyramid_shares: int = 0
    pyramid_invested: float = 0.0

    # Blended position totals
    total_shares: int = 0
    total_invested: float = 0.0
    avg_price: float = 0.0

    # Tracking
    current_price: float = 0.0
    highest_price: float = 0.0
    exit_date: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    exit_reason: str = ""
    realized_pnl: float = 0.0
    realized_return_pct: float = 0.0
    holding_weeks: int = 0

    def __post_init__(self):
        self.total_shares = self.initial_shares
        self.total_invested = self.initial_invested
        self.avg_price = self.entry_price
        self.current_price = self.entry_price
        self.highest_price = self.entry_price

    def add_pyramid(self, date: pd.Timestamp, price: float, shares: int, invested: float):
        self.is_pyramided = True
        self.pyramid_date = date
        self.pyramid_price = price
        self.pyramid_shares = shares
        self.pyramid_invested = invested

        self.total_shares += shares
        self.total_invested += invested
        self.avg_price = self.total_invested / self.total_shares if self.total_shares > 0 else self.avg_price


class V3Backtester:
    """
    Simulates the V3 Multibagger strategy over a multi-year period.
    """

    def __init__(
        self,
        starting_capital: float = STARTING_CAPITAL,
        compounding: bool = True,
        transaction_cost_pct: float = TRANSACTION_COST_PCT,
    ):
        self.starting_capital = starting_capital
        self.compounding = compounding
        self.transaction_cost_pct = transaction_cost_pct

        # State
        self.cash: float = starting_capital
        self.open_positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.equity_history: List[Dict] = []

    def run(
        self,
        universe_data: Dict[str, pd.DataFrame],
        regime_df: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict:
        """
        Runs the chronological weekly backtest.
        """
        logger.info("Computing weekly indicators for all universe stocks...")
        indicators_map: Dict[str, pd.DataFrame] = {}
        for ticker, df in universe_data.items():
            ind = compute_weekly_indicators(df)
            if not ind.empty:
                indicators_map[ticker] = ind

        logger.info(f"Indicators calculated for {len(indicators_map)} tickers.")

        # Compute Nifty 500 Market Regime
        regime_clean = compute_market_regime(regime_df)

        # Collect all unique weekly dates
        all_dates = sorted(list(regime_clean.index))
        if start_date:
            all_dates = [d for d in all_dates if d >= pd.to_datetime(start_date)]
        if end_date:
            all_dates = [d for d in all_dates if d <= pd.to_datetime(end_date)]

        # Ensure we have at least 52 weeks before starting to allow indicator warm-up
        if len(all_dates) < 52:
            raise ValueError(f"Insufficient weekly bars ({len(all_dates)}) for 52-week lookback.")

        logger.info(f"Running backtest from {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')} ({len(all_dates)} weeks)...")

        peak_equity = self.starting_capital

        for date in all_dates:
            # 1. Update prices for all open positions
            for ticker, pos in list(self.open_positions.items()):
                ind_df = indicators_map.get(ticker)
                if ind_df is not None and date in ind_df.index:
                    current_close = ind_df.loc[date, "Close"]
                    pos.current_price = current_close
                    pos.highest_price = max(pos.highest_price, current_close)
                    pos.holding_weeks += 1

            # 2. Check Exits (Weekly Close < 0.85 * 30-week MA)
            exited_tickers = []
            for ticker, pos in self.open_positions.items():
                ind_df = indicators_map.get(ticker)
                if ind_df is None or date not in ind_df.index:
                    continue

                row = ind_df.loc[date]
                ma30 = row.get("MA30", np.nan)
                if pd.isna(ma30) or ma30 <= 0:
                    continue

                stop_price = ma30 * (1.0 - EXIT_MA_THRESHOLD_PCT)
                current_close = row["Close"]

                if current_close < stop_price:
                    # Execute EXIT
                    exit_proceeds = pos.total_shares * current_close * (1.0 - self.transaction_cost_pct)
                    pos.exit_date = date
                    pos.exit_price = current_close
                    pos.exit_reason = f"Close ({current_close:.2f}) < 85% of MA30 ({stop_price:.2f})"
                    pos.realized_pnl = exit_proceeds - pos.total_invested
                    pos.realized_return_pct = (exit_proceeds / pos.total_invested - 1.0) * 100.0 if pos.total_invested > 0 else 0.0

                    self.cash += exit_proceeds
                    self.closed_positions.append(pos)
                    exited_tickers.append(ticker)

            for t in exited_tickers:
                del self.open_positions[t]

            # 3. Check Pyramiding for remaining open positions
            # (+20% gain from initial buy price -> add another 10% allocation)
            current_portfolio_value = self.cash + sum(
                p.total_shares * p.current_price for p in self.open_positions.values()
            )

            for ticker, pos in self.open_positions.items():
                if pos.is_pyramided:
                    continue

                ind_df = indicators_map.get(ticker)
                if ind_df is None or date not in ind_df.index:
                    continue

                current_close = ind_df.loc[date, "Close"]
                if current_close >= pos.entry_price * (1.0 + PYRAMID_TRIGGER_GAIN_PCT):
                    # Eligible for pyramiding
                    pyramid_allocation = (
                        current_portfolio_value * PYRAMID_ALLOCATION_PCT
                        if self.compounding
                        else self.starting_capital * PYRAMID_ALLOCATION_PCT
                    )
                    # Cap allocation by available cash
                    pyramid_budget = min(self.cash * 0.95, pyramid_allocation)
                    shares_to_add = int(pyramid_budget / current_close) if current_close > 0 else 0

                    if shares_to_add > 0:
                        cost = shares_to_add * current_close * (1.0 + self.transaction_cost_pct)
                        if self.cash >= cost:
                            self.cash -= cost
                            pos.add_pyramid(date, current_close, shares_to_add, cost)

            # 4. Check Market Regime for New Entries
            is_bullish = False
            if date in regime_clean.index:
                is_bullish = bool(regime_clean.loc[date, "Regime_Bullish"])

            # 5. Check New Breakout Entries (ONLY if Market Regime is Bullish)
            if is_bullish:
                candidates: List[Tuple[str, float, float, float]] = []

                for ticker, ind_df in indicators_map.items():
                    if ticker in self.open_positions:
                        continue  # Already in position

                    if date not in ind_df.index:
                        continue

                    row = ind_df.loc[date]
                    if row.get("Stage2_Signal", False):
                        vol_ratio = row["Volume"] / row["Vol_MA10"] if row["Vol_MA10"] > 0 else 1.0
                        candidates.append((ticker, row["Close"], vol_ratio, row["MA30"]))

                # Sort candidates by Relative Volume ratio descending (strongest breakout volume first)
                candidates.sort(key=lambda x: x[2], reverse=True)

                # Enter trades up to available cash
                for ticker, close_price, vol_ratio, ma30 in candidates:
                    current_portfolio_value = self.cash + sum(
                        p.total_shares * p.current_price for p in self.open_positions.values()
                    )
                    trade_allocation = (
                        current_portfolio_value * INITIAL_ALLOCATION_PCT
                        if self.compounding
                        else self.starting_capital * INITIAL_ALLOCATION_PCT
                    )

                    # Ensure cash buffer
                    if self.cash < trade_allocation * 0.5:
                        break  # Out of sufficient cash

                    allocation_to_use = min(self.cash * 0.95, trade_allocation)
                    shares = int(allocation_to_use / close_price) if close_price > 0 else 0

                    if shares > 0:
                        cost = shares * close_price * (1.0 + self.transaction_cost_pct)
                        if self.cash >= cost:
                            self.cash -= cost
                            new_pos = Position(
                                ticker=ticker,
                                entry_date=date,
                                entry_price=close_price,
                                initial_shares=shares,
                                initial_invested=cost,
                            )
                            self.open_positions[ticker] = new_pos

            # 6. Record Weekly Portfolio Snapshot
            invested_val = sum(p.total_shares * p.current_price for p in self.open_positions.values())
            total_equity = self.cash + invested_val
            peak_equity = max(peak_equity, total_equity)
            drawdown_pct = (peak_equity - total_equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0

            nifty_close = regime_clean.loc[date, "Close"] if date in regime_clean.index else np.nan
            nifty_ma30 = regime_clean.loc[date, "Nifty_MA30"] if date in regime_clean.index else np.nan

            self.equity_history.append({
                "Date": date,
                "Cash": self.cash,
                "Invested_Value": invested_val,
                "Total_Equity": total_equity,
                "Peak_Equity": peak_equity,
                "Drawdown_Pct": drawdown_pct,
                "Regime_Bullish": is_bullish,
                "Open_Positions_Count": len(self.open_positions),
                "Nifty500_Close": nifty_close,
                "Nifty500_MA30": nifty_ma30,
            })

        # Final mark-to-market for open positions at backtest conclusion
        final_date = all_dates[-1]
        for ticker, pos in list(self.open_positions.items()):
            pos.exit_date = final_date
            pos.exit_price = pos.current_price
            pos.exit_reason = "Open at Backtest End (Mark-to-Market)"
            final_proceeds = pos.total_shares * pos.current_price * (1.0 - self.transaction_cost_pct)
            pos.realized_pnl = final_proceeds - pos.total_invested
            pos.realized_return_pct = (final_proceeds / pos.total_invested - 1.0) * 100.0 if pos.total_invested > 0 else 0.0

        return self.calculate_results()

    def calculate_results(self) -> Dict:
        """
        Calculates all quantitative performance metrics.
        """
        eq_df = pd.DataFrame(self.equity_history).set_index("Date")
        if eq_df.empty:
            return {}

        start_val = self.starting_capital
        end_val = eq_df["Total_Equity"].iloc[-1]
        total_return_pct = (end_val / start_val - 1.0) * 100.0

        # Time duration in years
        start_date = eq_df.index[0]
        end_date = eq_df.index[-1]
        years = max((end_date - start_date).days / 365.25, 0.1)

        # CAGR
        cagr_pct = ((end_val / start_val) ** (1.0 / years) - 1.0) * 100.0

        # Max Drawdown
        max_drawdown_pct = eq_df["Drawdown_Pct"].max()

        # All trades (closed + final marked-to-market)
        all_trades = self.closed_positions + list(self.open_positions.values())
        total_trades = len(all_trades)

        wins = [t for t in all_trades if t.realized_pnl > 0]
        losses = [t for t in all_trades if t.realized_pnl <= 0]

        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        total_gain = sum(t.realized_pnl for t in wins)
        total_loss = abs(sum(t.realized_pnl for t in losses))
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (999.0 if total_gain > 0 else 0.0)

        avg_win_pct = np.mean([t.realized_return_pct for t in wins]) if wins else 0.0
        avg_loss_pct = np.mean([t.realized_return_pct for t in losses]) if losses else 0.0

        # Multibaggers breakdown
        winners_100 = [t for t in all_trades if t.realized_return_pct >= 100.0]
        winners_200 = [t for t in all_trades if t.realized_return_pct >= 200.0]
        winners_300 = [t for t in all_trades if t.realized_return_pct >= 300.0]

        # Pyramiding stats
        pyramided_trades = [t for t in all_trades if t.is_pyramided]

        # Benchmark (Nifty 500) performance
        nifty_start = eq_df["Nifty500_Close"].dropna().iloc[0]
        nifty_end = eq_df["Nifty500_Close"].dropna().iloc[-1]
        nifty_cagr = ((nifty_end / nifty_start) ** (1.0 / years) - 1.0) * 100.0

        # Year-by-Year breakdown
        eq_df["Year"] = eq_df.index.year
        yearly_rows = []
        for year, group in eq_df.groupby("Year"):
            y_start = group["Total_Equity"].iloc[0]
            y_end = group["Total_Equity"].iloc[-1]
            y_ret = (y_end / y_start - 1.0) * 100.0
            y_max_dd = group["Drawdown_Pct"].max()

            # Benchmark year return
            b_start = group["Nifty500_Close"].dropna().iloc[0] if not group["Nifty500_Close"].dropna().empty else 1.0
            b_end = group["Nifty500_Close"].dropna().iloc[-1] if not group["Nifty500_Close"].dropna().empty else 1.0
            b_ret = (b_end / b_start - 1.0) * 100.0 if b_start > 0 else 0.0

            yearly_rows.append({
                "Year": year,
                "Start_Equity": y_start,
                "End_Equity": y_end,
                "Return_Pct": y_ret,
                "Benchmark_Return_Pct": b_ret,
                "Alpha_Pct": y_ret - b_ret,
                "Max_DD_Pct": y_max_dd,
            })

        yearly_df = pd.DataFrame(yearly_rows)

        results = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "years": round(years, 2),
            "starting_capital": start_val,
            "ending_equity": end_val,
            "total_return_pct": total_return_pct,
            "cagr_pct": cagr_pct,
            "benchmark_cagr_pct": nifty_cagr,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "win_loss_ratio": (avg_win_pct / abs(avg_loss_pct)) if avg_loss_pct != 0 else 0.0,
            "multibaggers_100_plus": len(winners_100),
            "multibaggers_200_plus": len(winners_200),
            "multibaggers_300_plus": len(winners_300),
            "pyramided_trades_count": len(pyramided_trades),
            "yearly_table": yearly_df,
            "equity_df": eq_df,
            "all_trades": all_trades,
        }
        return results

    def print_report(self, res: Dict):
        """
        Prints an executive quantitative performance report.
        """
        print("\n" + "=" * 80)
        print("          V3 MULTIBAGGER QUANTITATIVE ENGINE - 10-YEAR BACKTEST REPORT")
        print("=" * 80)
        print(f" Backtest Period       : {res['start_date']} to {res['end_date']} ({res['years']} Years)")
        print(f" Starting Capital      : ₹{res['starting_capital']:,.2f}")
        print(f" Ending Equity         : ₹{res['ending_equity']:,.2f}")
        print(f" Total Net Return      : {res['total_return_pct']:+.2f}%")
        print(f" Strategy CAGR         : {res['cagr_pct']:.2f}%")
        print(f" Nifty 500 CAGR (Bmk)  : {res['benchmark_cagr_pct']:.2f}%")
        print(f" Alpha over Benchmark  : {res['cagr_pct'] - res['benchmark_cagr_pct']:+.2f}%")
        print(f" Maximum Drawdown      : -{res['max_drawdown_pct']:.2f}%")
        print("-" * 80)
        print(" TRADE EXECUTION & WIN-RATE DYNAMICS")
        print(f" Total Trades Taken    : {res['total_trades']}")
        print(f" Winning Trades        : {res['winning_trades']} ({res['win_rate_pct']:.1f}% Win Rate)")
        print(f" Losing Trades         : {res['losing_trades']}")
        print(f" Profit Factor         : {res['profit_factor']:.2f}")
        print(f" Average Gain per Win  : +{res['avg_win_pct']:.1f}%")
        print(f" Average Cut per Loss  : {res['avg_loss_pct']:.1f}%")
        print(f" Win/Loss Ratio        : {res['win_loss_ratio']:.2f}x (Asymmetric Risk/Reward)")
        print(f" Pyramided Trades      : {res['pyramided_trades_count']} (+10% added on +20% gain)")
        print("-" * 80)
        print(" MULTIBAGGER DISTRIBUTION")
        print(f" 100%+ Gainers (2x)    : {res['multibaggers_100_plus']} stocks")
        print(f" 200%+ Gainers (3x)    : {res['multibaggers_200_plus']} stocks")
        print(f" 300%+ Winners (4x+)   : {res['multibaggers_300_plus']} STRUCTURAL MULTIBAGGERS 🚀")
        print("=" * 80)

        # Yearly Table
        print("\nYEAR-BY-YEAR EQUITY CURVE & PERFORMANCE")
        print("-" * 80)
        print(f"{'Year':<6} {'Start Equity':<15} {'End Equity':<15} {'Strategy':<10} {'Nifty 500':<12} {'Alpha':<10} {'Max DD':<8}")
        print("-" * 80)
        for _, row in res["yearly_table"].iterrows():
            print(
                f"{int(row['Year']):<6} "
                f"₹{row['Start_Equity']:>12,.0f}  "
                f"₹{row['End_Equity']:>12,.0f}  "
                f"{row['Return_Pct']:>+8.1f}%  "
                f"{row['Benchmark_Return_Pct']:>+9.1f}%   "
                f"{row['Alpha_Pct']:>+7.1f}%  "
                f"-{row['Max_DD_Pct']:>5.1f}%"
            )
        print("-" * 80)

        # Top 10 Multibaggers
        trades: List[Position] = res["all_trades"]
        sorted_trades = sorted(trades, key=lambda x: x.realized_return_pct, reverse=True)
        print("\nTOP 10 STRUCTURAL MULTIBAGGER WINNERS")
        print("-" * 90)
        print(f"{'Ticker':<14} {'Entry Date':<12} {'Exit Date':<12} {'Buy (₹)':<10} {'Exit (₹)':<10} {'Return %':<10} {'Held':<8} {'Pyramid?'}")
        print("-" * 90)
        for t in sorted_trades[:10]:
            exit_d = t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "OPEN"
            pyr_str = "YES (+10%)" if t.is_pyramided else "NO"
            print(
                f"{t.ticker:<14} "
                f"{t.entry_date.strftime('%Y-%m-%d'):<12} "
                f"{exit_d:<12} "
                f"{t.entry_price:>9.2f} "
                f"{t.exit_price:>9.2f} "
                f"{t.realized_return_pct:>+9.1f}% "
                f"{t.holding_weeks:>4} wks "
                f"{pyr_str}"
            )
        print("=" * 90 + "\n")


def main():
    parser = argparse.ArgumentParser(description="V3 Multibagger 10-Year Backtest Engine")
    parser.add_argument("--tickers", type=int, default=100, help="Number of universe tickers to test (default: 100)")
    parser.add_argument("--compounding", action="store_true", default=True, help="Reinvest equity profits")
    parser.add_argument("--fixed-size", action="store_true", help="Use fixed ₹10,000 sizing instead of 10% equity")
    parser.add_argument("--start", type=str, default="2014-01-01", help="Backtest start date")
    parser.add_argument("--end", type=str, default=None, help="Backtest end date")
    parser.add_argument("--export", action="store_true", default=True, help="Export trades and equity curve to CSV")
    args = parser.parse_args()

    print("\n[+] Initializing V3 Multibagger Backtester...")
    # 1. Fetch Universe
    all_tickers = fetch_nifty500_tickers()
    selected_tickers = all_tickers[: args.tickers]

    # 2. Fetch Regime Index (^CRSLDX)
    regime_df, regime_name = fetch_regime_index_weekly(period="12y")

    # 3. Fetch Universe Weekly Data
    universe_data = batch_fetch_weekly_universe(selected_tickers, period="12y")

    # 4. Run Backtest
    compounding_mode = not args.fixed_size
    backtester = V3Backtester(
        starting_capital=STARTING_CAPITAL,
        compounding=compounding_mode,
        transaction_cost_pct=TRANSACTION_COST_PCT,
    )

    results = backtester.run(
        universe_data=universe_data,
        regime_df=regime_df,
        start_date=args.start,
        end_date=args.end,
    )

    # 5. Print Executive Report
    backtester.print_report(results)

    # 6. Export CSVs if requested
    if args.export:
        eq_df = results["equity_df"]
        eq_df.to_csv("v3_backtest_equity_curve.csv")

        trade_rows = []
        for t in results["all_trades"]:
            trade_rows.append({
                "Ticker": t.ticker,
                "Entry_Date": t.entry_date.strftime("%Y-%m-%d"),
                "Entry_Price": t.entry_price,
                "Initial_Shares": t.initial_shares,
                "Is_Pyramided": t.is_pyramided,
                "Pyramid_Date": t.pyramid_date.strftime("%Y-%m-%d") if t.pyramid_date else "",
                "Pyramid_Price": t.pyramid_price,
                "Pyramid_Shares": t.pyramid_shares,
                "Total_Shares": t.total_shares,
                "Average_Price": t.avg_price,
                "Exit_Date": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "",
                "Exit_Price": t.exit_price,
                "Exit_Reason": t.exit_reason,
                "Total_Invested": t.total_invested,
                "Realized_PnL": t.realized_pnl,
                "Return_Pct": t.realized_return_pct,
                "Holding_Weeks": t.holding_weeks,
            })
        pd.DataFrame(trade_rows).to_csv("v3_backtest_trades.csv", index=False)
        print("[+] Backtest artifacts exported successfully:")
        print("    -> v3_backtest_equity_curve.csv")
        print("    -> v3_backtest_trades.csv")


if __name__ == "__main__":
    main()
