"""
V3 Multibagger Engine - Live Weekly Paper Trading Module
Executes weekly Friday EOD scans, manages the local SQLite ledger (v3_multibagger_ledger.db),
handles 10% base allocation, 10% pyramiding at +20% gain, 15% sub-MA30 trailing stops,
and enforces the Nifty 500 market regime filter.
"""

import sys
import sqlite3
import argparse
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

# Ensure Windows terminal supports UTF-8 characters (e.g. Rupee symbol)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import (
    BASE_DIR,
    DB_PATH,
    STARTING_CAPITAL,
    INITIAL_ALLOCATION_PCT,
    PYRAMID_ALLOCATION_PCT,
    PYRAMID_TRIGGER_GAIN_PCT,
    MAX_TICKER_ALLOCATION_PCT,
    MAX_STARTER_POSITIONS,
    PYRAMID_CASH_RESERVE_PCT,
    EXIT_MA_BULL_THRESHOLD_PCT,
    EXIT_MA_BEAR_THRESHOLD_PCT,
    EXIT_MA_THRESHOLD_PCT,
    TRANSACTION_COST_PCT,
)
from data_loader import (
    fetch_nifty500_tickers,
    batch_fetch_weekly_universe,
    fetch_regime_index_weekly,
    fetch_ticker_weekly,
    fetch_single_ticker_daily,
)
from strategy import (
    compute_weekly_indicators,
    compute_market_regime,
    check_exit_condition,
    check_pyramid_condition,
)
from playwright_fundamentals import (
    fetch_screener_metrics,
    evaluate_fundamental_rules,
)
from telegram_notifier import send_weekly_scan_report

logger = logging.getLogger("V3WeeklyEngine")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class V3Ledger:
    """
    Manages SQLite database transactions for virtual paper trading.
    Tracks portfolio equity, cash, open positions, trade history, and snapshots.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Portfolio State Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cash_balance REAL NOT NULL,
                    invested_value REAL NOT NULL,
                    total_equity REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    last_updated TEXT NOT NULL
                )
            """)

            # 2. Open Positions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    initial_date TEXT NOT NULL,
                    initial_price REAL NOT NULL,
                    initial_shares INTEGER NOT NULL,
                    initial_invested REAL NOT NULL,
                    is_pyramided INTEGER NOT NULL DEFAULT 0,
                    pyramid_date TEXT,
                    pyramid_price REAL DEFAULT 0.0,
                    pyramid_shares INTEGER DEFAULT 0,
                    pyramid_invested REAL DEFAULT 0.0,
                    total_shares INTEGER NOT NULL,
                    total_invested REAL NOT NULL,
                    avg_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    current_ma30 REAL,
                    current_stop_price REAL,
                    current_value REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    unrealized_pnl_pct REAL NOT NULL,
                    highest_price REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    last_updated TEXT NOT NULL
                )
            """)

            # 3. Trade History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares INTEGER NOT NULL,
                    price REAL NOT NULL,
                    gross_amount REAL NOT NULL,
                    fees REAL NOT NULL,
                    net_amount REAL NOT NULL,
                    realized_pnl REAL DEFAULT 0.0,
                    return_pct REAL DEFAULT 0.0,
                    holding_weeks INTEGER DEFAULT 0,
                    reason TEXT
                )
            """)

            # 4. Weekly Equity Snapshots Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS weekly_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_date TEXT NOT NULL,
                    cash_balance REAL NOT NULL,
                    invested_value REAL NOT NULL,
                    total_equity REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    drawdown_pct REAL NOT NULL,
                    open_positions_count INTEGER NOT NULL,
                    nifty500_close REAL,
                    nifty500_ma30 REAL,
                    regime_bullish INTEGER NOT NULL,
                    notes TEXT
                )
            """)

            # Initialize portfolio if empty
            cursor.execute("SELECT COUNT(*) FROM portfolio WHERE id = 1")
            if cursor.fetchone()[0] == 0:
                now_str = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO portfolio (id, cash_balance, invested_value, total_equity, peak_equity, last_updated)
                    VALUES (1, ?, 0.0, ?, ?, ?)
                """, (STARTING_CAPITAL, STARTING_CAPITAL, STARTING_CAPITAL, now_str))

            conn.commit()

    def reset_ledger(self, initial_capital: float = STARTING_CAPITAL):
        """Resets the ledger back to clean starting state."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions")
            cursor.execute("DELETE FROM trades")
            cursor.execute("DELETE FROM weekly_snapshots")
            now_str = datetime.now().isoformat()
            cursor.execute("""
                UPDATE portfolio
                SET cash_balance = ?, invested_value = 0.0, total_equity = ?, peak_equity = ?, last_updated = ?
                WHERE id = 1
            """, (initial_capital, initial_capital, initial_capital, now_str))
            conn.commit()
        logger.info(f"Ledger reset successfully to ₹{initial_capital:,.2f}.")

    def get_portfolio(self) -> Dict:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
            return dict(row) if row else {}

    def get_open_positions(self) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM positions WHERE status IN ('OPEN', 'EXIT_PENDING')").fetchall()
            return [dict(r) for r in rows]

    def get_closed_trades(self) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM trades ORDER BY trade_id DESC").fetchall()
            return [dict(r) for r in rows]

    def mark_exit_pending(
        self,
        ticker: str,
        current_price: float,
        stop_price: float,
        reason: str = "Locked in Lower Circuit (High == Low)",
    ):
        """Marks a position as EXIT_PENDING when lower circuit freeze blocks immediate market execution."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            pos = cursor.execute(
                "SELECT * FROM positions WHERE ticker = ? AND status IN ('OPEN', 'EXIT_PENDING')",
                (ticker,),
            ).fetchone()
            if not pos:
                return

            shares = pos["total_shares"]
            invested = pos["total_invested"]
            cur_val = shares * current_price
            pnl = cur_val - invested
            pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0
            now_str = datetime.now().isoformat()

            cursor.execute("""
                UPDATE positions
                SET status = 'EXIT_PENDING', current_price = ?, current_stop_price = ?,
                    current_value = ?, unrealized_pnl = ?, unrealized_pnl_pct = ?, last_updated = ?
                WHERE ticker = ?
            """, (current_price, stop_price, cur_val, pnl, pnl_pct, now_str, ticker))
            conn.commit()
        logger.warning(f"[!] Position {ticker} queued as EXIT_PENDING @ ₹{current_price:.2f} ({reason})")

    def execute_initial_buy(
        self,
        ticker: str,
        price: float,
        shares: int,
        date_str: str,
        ma30: float,
        reason: str = "Stage 2 52w Breakout with Volume",
    ) -> bool:
        """Executes a virtual initial 10% buy and records in ledger."""
        if shares <= 0 or price <= 0:
            return False

        gross = shares * price
        fees = gross * TRANSACTION_COST_PCT
        net_cost = gross + fees

        portfolio = self.get_portfolio()
        cash = portfolio.get("cash_balance", 0.0)

        if cash < net_cost:
            logger.warning(f"Insufficient cash (₹{cash:,.2f}) for BUY {shares} of {ticker} (₹{net_cost:,.2f})")
            return False

        stop_price = ma30 * (1.0 - EXIT_MA_BULL_THRESHOLD_PCT)
        now_str = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Deduct cash
            new_cash = cash - net_cost
            cursor.execute("""
                UPDATE portfolio
                SET cash_balance = ?, last_updated = ?
                WHERE id = 1
            """, (new_cash, now_str))

            # Insert Position
            cursor.execute("""
                INSERT OR REPLACE INTO positions (
                    ticker, initial_date, initial_price, initial_shares, initial_invested,
                    is_pyramided, pyramid_date, pyramid_price, pyramid_shares, pyramid_invested,
                    total_shares, total_invested, avg_price, current_price, current_ma30,
                    current_stop_price, current_value, unrealized_pnl, unrealized_pnl_pct,
                    highest_price, status, last_updated
                ) VALUES (?, ?, ?, ?, ?, 0, NULL, 0.0, 0, 0.0, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, 'OPEN', ?)
            """, (
                ticker, date_str, price, shares, net_cost,
                shares, net_cost, price, price, ma30,
                stop_price, gross, price, now_str
            ))

            # Record Trade Log
            cursor.execute("""
                INSERT INTO trades (
                    timestamp, ticker, action, shares, price, gross_amount, fees, net_amount, reason
                ) VALUES (?, ?, 'INITIAL_BUY', ?, ?, ?, ?, ?, ?)
            """, (now_str, ticker, shares, price, gross, fees, net_cost, reason))

            conn.commit()

        logger.info(f"[+] EXECUTED BUY: {shares} shares of {ticker} @ ₹{price:.2f} (Total: ₹{net_cost:,.2f})")
        return True

    def execute_pyramid_buy(
        self,
        ticker: str,
        price: float,
        shares: int,
        date_str: str,
        reason: str = "Pyramiding (+20% Advance)",
    ) -> bool:
        """Executes a virtual 10% pyramid addition to an open position."""
        if shares <= 0 or price <= 0:
            return False

        gross = shares * price
        fees = gross * TRANSACTION_COST_PCT
        net_cost = gross + fees

        portfolio = self.get_portfolio()
        cash = portfolio.get("cash_balance", 0.0)

        if cash < net_cost:
            logger.warning(f"Insufficient cash for PYRAMID BUY on {ticker}")
            return False

        now_str = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            pos = cursor.execute("SELECT * FROM positions WHERE ticker = ? AND status = 'OPEN'", (ticker,)).fetchone()
            if not pos:
                return False

            old_shares = pos["total_shares"]
            old_invested = pos["total_invested"]
            new_shares = old_shares + shares
            new_invested = old_invested + net_cost
            new_avg_price = new_invested / new_shares if new_shares > 0 else price
            new_val = new_shares * price
            unrealized_pnl = new_val - new_invested
            unrealized_pct = (unrealized_pnl / new_invested * 100.0) if new_invested > 0 else 0.0

            # Deduct cash
            new_cash = cash - net_cost
            cursor.execute("UPDATE portfolio SET cash_balance = ?, last_updated = ? WHERE id = 1", (new_cash, now_str))

            # Update position
            cursor.execute("""
                UPDATE positions
                SET is_pyramided = 1, pyramid_date = ?, pyramid_price = ?, pyramid_shares = ?, pyramid_invested = ?,
                    total_shares = ?, total_invested = ?, avg_price = ?, current_price = ?, current_value = ?,
                    unrealized_pnl = ?, unrealized_pnl_pct = ?, highest_price = MAX(highest_price, ?), last_updated = ?
                WHERE ticker = ?
            """, (
                date_str, price, shares, net_cost,
                new_shares, new_invested, new_avg_price, price, new_val,
                unrealized_pnl, unrealized_pct, price, now_str, ticker
            ))

            # Trade log
            cursor.execute("""
                INSERT INTO trades (
                    timestamp, ticker, action, shares, price, gross_amount, fees, net_amount, reason
                ) VALUES (?, ?, 'PYRAMID_BUY', ?, ?, ?, ?, ?, ?)
            """, (now_str, ticker, shares, price, gross, fees, net_cost, reason))

            conn.commit()

        logger.info(f"[+] EXECUTED PYRAMID: +{shares} shares of {ticker} @ ₹{price:.2f} (Total: ₹{net_cost:,.2f})")
        return True

    def execute_exit(
        self,
        ticker: str,
        price: float,
        date_str: str,
        reason: str = "Weekly Close < Stop Level",
    ) -> bool:
        """Executes full position exit and credits cash back to portfolio."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            pos = cursor.execute("SELECT * FROM positions WHERE ticker = ? AND status IN ('OPEN', 'EXIT_PENDING')", (ticker,)).fetchone()
            if not pos:
                return False

            total_shares = pos["total_shares"]
            total_invested = pos["total_invested"]
            gross_proceeds = total_shares * price
            fees = gross_proceeds * TRANSACTION_COST_PCT
            net_proceeds = gross_proceeds - fees
            realized_pnl = net_proceeds - total_invested
            return_pct = (realized_pnl / total_invested * 100.0) if total_invested > 0 else 0.0

            # Calculate holding weeks
            try:
                init_dt = pd.to_datetime(pos["initial_date"])
                exit_dt = pd.to_datetime(date_str)
                holding_wks = max(1, int((exit_dt - init_dt).days // 7))
            except Exception:
                holding_wks = 0

            portfolio = self.get_portfolio()
            cash = portfolio.get("cash_balance", 0.0)
            new_cash = cash + net_proceeds
            now_str = datetime.now().isoformat()

            # Credit Cash
            cursor.execute("UPDATE portfolio SET cash_balance = ?, last_updated = ? WHERE id = 1", (new_cash, now_str))

            # Mark Position as CLOSED
            cursor.execute("""
                UPDATE positions
                SET status = 'CLOSED', current_price = ?, current_value = 0.0,
                    unrealized_pnl = 0.0, unrealized_pnl_pct = 0.0, last_updated = ?
                WHERE ticker = ?
            """, (price, now_str, ticker))

            # Record Trade Log
            cursor.execute("""
                INSERT INTO trades (
                    timestamp, ticker, action, shares, price, gross_amount, fees, net_amount,
                    realized_pnl, return_pct, holding_weeks, reason
                ) VALUES (?, ?, 'EXIT_STOP', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_str, ticker, total_shares, price, gross_proceeds, fees, net_proceeds,
                realized_pnl, return_pct, holding_wks, reason
            ))

            conn.commit()

        logger.info(
            f"[-] EXECUTED EXIT: {total_shares} shares of {ticker} @ ₹{price:.2f} | "
            f"PnL: ₹{realized_pnl:+,.2f} ({return_pct:+.1f}%) | Held: {holding_wks} wks"
        )
        return True

    def update_open_position_mtm(
        self,
        ticker: str,
        current_price: float,
        ma30: float,
        stop_price: float,
    ):
        """Updates current price and unrealized PnL for an open position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            pos = cursor.execute("SELECT * FROM positions WHERE ticker = ? AND status IN ('OPEN', 'EXIT_PENDING')", (ticker,)).fetchone()
            if not pos:
                return

            shares = pos["total_shares"]
            invested = pos["total_invested"]
            cur_val = shares * current_price
            pnl = cur_val - invested
            pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0
            now_str = datetime.now().isoformat()

            cursor.execute("""
                UPDATE positions
                SET current_price = ?, current_ma30 = ?, current_stop_price = ?,
                    current_value = ?, unrealized_pnl = ?, unrealized_pnl_pct = ?,
                    highest_price = MAX(highest_price, ?), last_updated = ?
                WHERE ticker = ?
            """, (current_price, ma30, stop_price, cur_val, pnl, pnl_pct, current_price, now_str, ticker))
            conn.commit()

    def record_weekly_snapshot(
        self,
        week_date: str,
        nifty_close: float,
        nifty_ma30: float,
        regime_bullish: bool,
    ):
        """Calculates total portfolio value and logs a weekly snapshot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            portfolio = self.get_portfolio()
            cash = portfolio.get("cash_balance", 0.0)

            # Sum of open positions (including EXIT_PENDING)
            open_positions = cursor.execute("SELECT current_value FROM positions WHERE status IN ('OPEN', 'EXIT_PENDING')").fetchall()
            invested_val = sum(r[0] for r in open_positions)
            total_equity = cash + invested_val

            old_peak = portfolio.get("peak_equity", STARTING_CAPITAL)
            new_peak = max(old_peak, total_equity)
            drawdown_pct = ((new_peak - total_equity) / new_peak * 100.0) if new_peak > 0 else 0.0
            now_str = datetime.now().isoformat()

            # Update portfolio header
            cursor.execute("""
                UPDATE portfolio
                SET invested_value = ?, total_equity = ?, peak_equity = ?, last_updated = ?
                WHERE id = 1
            """, (invested_val, total_equity, new_peak, now_str))

            # Insert snapshot
            cursor.execute("""
                INSERT INTO weekly_snapshots (
                    week_date, cash_balance, invested_value, total_equity, peak_equity,
                    drawdown_pct, open_positions_count, nifty500_close, nifty500_ma30,
                    regime_bullish, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                week_date, cash, invested_val, total_equity, new_peak,
                drawdown_pct, len(open_positions), nifty_close, nifty_ma30,
                1 if regime_bullish else 0, "Weekly EOD Engine Scan"
            ))

            conn.commit()


def run_engine(
    ledger: V3Ledger,
    mode: str = "full",
    max_universe_tickers: int = 150,
    dry_run: bool = False,
):
    """
    V3.1 Multibagger Engine - Live Execution Routine
    Modes:
      - 'full': Friday EOD scan (Market regime, dynamic trailing stops, lower circuit check,
                pyramiding additions (+20% gain), and Stage 2 + Playwright entry screening).
      - 'exits_only': Fast daily monitoring (Market regime, dynamic trailing stop evaluation,
                      and lower circuit detection (High == Low -> EXIT_PENDING)).
    """
    mode_title = "WEEKLY FRIDAY SCAN (FULL EXECUTION)" if mode == "full" else "DAILY TRAILING STOP MONITOR (EXITS ONLY)"
    print("\n" + "=" * 80)
    print(f"      V3.1 MULTIBAGGER ENGINE - {mode_title}")
    print("=" * 80)

    # Step 1: Market Regime Check
    print("\n[Step 1/5] Evaluating Nifty 500 Market Regime Filter...")
    regime_df, regime_name = fetch_regime_index_weekly(period="2y", force_refresh=True)
    regime_clean = compute_market_regime(regime_df)
    latest_nifty_bar = regime_clean.iloc[-1]
    latest_week_date = regime_clean.index[-1].strftime("%Y-%m-%d")

    nifty_close = float(latest_nifty_bar["Close"])
    nifty_ma30 = float(latest_nifty_bar["Nifty_MA30"])
    is_bullish = bool(latest_nifty_bar["Regime_Bullish"])

    if is_bullish:
        regime_status_str = "BULLISH (ENTRIES ALLOWED | TRAILING STOP: 15% sub-MA30)"
        active_stop_pct = EXIT_MA_BULL_THRESHOLD_PCT
        regime_tag = "BULL (15% sub-MA30)"
    else:
        regime_status_str = "BEARISH (ENTRIES & PYRAMIDS BLOCKED | STOP TIGHTENED: 8% sub-MA30)"
        active_stop_pct = EXIT_MA_BEAR_THRESHOLD_PCT
        regime_tag = "BEAR (8% sub-MA30)"

    print(f"  Benchmark Index     : {regime_name} (As of {latest_week_date})")
    print(f"  Nifty 500 Close     : {nifty_close:,.2f}")
    print(f"  Nifty 500 30-Wk MA  : {nifty_ma30:,.2f}")
    print(f"  Market Regime State : {regime_status_str}")

    # Step 2: Open Positions Review & Exit Checks (Dynamic Stop + Lower Circuit Check)
    print(f"\n[Step 2/5] Evaluating Open Positions & Trailing Stops [{regime_tag}]...")
    open_positions = ledger.get_open_positions()
    exited_tickers = set()
    new_buys_executed: List[Dict] = []
    exits_executed: List[Dict] = []
    pyramids_executed: List[Dict] = []

    eval_date_str = latest_week_date

    if not open_positions:
        print("  No active open positions currently held.")
    else:
        for pos in open_positions:
            ticker = pos["ticker"]

            # Fetch weekly data to calculate 30-week MA
            weekly_df = fetch_ticker_weekly(ticker, period="2y", force_refresh=True)
            if weekly_df is None or len(weekly_df) < 30:
                logger.warning(f"Unable to fetch weekly data for {ticker}. Skipping.")
                continue

            ind = compute_weekly_indicators(weekly_df)
            if ind.empty:
                continue

            cur_ma30 = float(ind.iloc[-1]["MA30"])

            # Fetch latest daily bar for intraday/daily price & lower circuit detection
            daily_df = fetch_single_ticker_daily(ticker, period="1mo")
            if daily_df is not None and not daily_df.empty:
                last_daily = daily_df.iloc[-1]
                cur_close = float(last_daily["Close"])
                cur_high = float(last_daily["High"])
                cur_low = float(last_daily["Low"])
                cur_date_str = daily_df.index[-1].strftime("%Y-%m-%d")
            else:
                last_weekly = ind.iloc[-1]
                cur_close = float(last_weekly["Close"])
                cur_high = float(last_weekly["High"])
                cur_low = float(last_weekly["Low"])
                cur_date_str = latest_week_date

            eval_date_str = cur_date_str

            # Dynamic stop condition (8% bear vs 15% bull)
            should_exit, stop_price = check_exit_condition(cur_close, cur_ma30, is_bearish_regime=(not is_bullish))

            # Mark to market
            if not dry_run:
                ledger.update_open_position_mtm(ticker, cur_close, cur_ma30, stop_price)

            if should_exit:
                # Check for lower circuit: High == Low freeze
                is_circuit_locked = (abs(cur_high - cur_low) < 1e-4) or (cur_high == cur_low)
                if is_circuit_locked:
                    print(f"  [!] LOWER CIRCUIT DETECTED: {ticker} locked at ₹{cur_close:.2f} (High == Low). Exit queued as EXIT_PENDING.")
                    logger.warning(f"LOWER CIRCUIT DETECTED: {ticker} locked at ₹{cur_close:.2f}. Queued as EXIT_PENDING.")
                    if not dry_run:
                        ledger.mark_exit_pending(
                            ticker,
                            cur_close,
                            stop_price,
                            reason=f"Lower circuit freeze (High=Low=₹{cur_close:.2f}). Stop breached at ₹{stop_price:.2f} ({regime_tag}).",
                        )
                else:
                    # Normal market exit
                    print(f"  [!] EXIT TRIGGERED for {ticker}: Close (₹{cur_close:.2f}) < Stop Level (₹{stop_price:.2f}) [{regime_tag}]")
                    gross = pos["total_shares"] * cur_close
                    net = gross * (1.0 - TRANSACTION_COST_PCT)
                    pnl = net - pos["total_invested"]
                    ret_pct = (net / pos["total_invested"] - 1.0) * 100.0 if pos["total_invested"] > 0 else 0.0

                    if not dry_run:
                        ledger.execute_exit(
                            ticker,
                            cur_close,
                            eval_date_str,
                            reason=f"Close (₹{cur_close:.2f}) < Stop (₹{stop_price:.2f}) [{regime_tag}]",
                        )

                    exits_executed.append({
                        "ticker": ticker,
                        "shares": pos["total_shares"],
                        "price": cur_close,
                        "pnl": pnl,
                        "ret_pct": ret_pct,
                    })
                    exited_tickers.add(ticker)
            else:
                # Position holds above stop
                if pos.get("status") == "EXIT_PENDING":
                    # Restored above stop level
                    with ledger._get_connection() as conn:
                        conn.execute("UPDATE positions SET status = 'OPEN' WHERE ticker = ?", (ticker,))
                        conn.commit()
                pct_above_stop = (cur_close / stop_price - 1.0) * 100.0
                status_tag = f" [{pos['status']}]" if pos.get("status") == "EXIT_PENDING" else ""
                print(
                    f"  [HOLD] {ticker:<12}{status_tag} | Price: ₹{cur_close:>8.2f} | MA30: ₹{cur_ma30:>8.2f} | "
                    f"Stop ({regime_tag}): ₹{stop_price:>8.2f} (+{pct_above_stop:.1f}% buffer)"
                )

    # Decouple Daily Mode from Friday Entries:
    if mode == "exits_only":
        print("\n[Daily Monitoring] Running in '--mode exits_only'. Pyramiding and Stage 2 entry screening skipped.")
    else:
        # Step 3: Pyramiding Checks
        print("\n[Step 3/5] Evaluating Pyramiding Eligibility (+20% gain from buy point)...")
        if not is_bullish:
            print("  [REGIME LOCK 🔒] Market Regime is BEARISH (Nifty 500 < 30w MA). All +10% pyramid additions strictly blocked to preserve cash.")
        else:
            remaining_open = [
                p for p in ledger.get_open_positions()
                if p["ticker"] not in exited_tickers and p.get("status") == "OPEN"
            ]

            for pos in remaining_open:
                ticker = pos["ticker"]
                is_pyr = bool(pos["is_pyramided"])
                if is_pyr:
                    continue

                init_price = float(pos["initial_price"])
                cur_price = float(pos["current_price"])

                if check_pyramid_condition(cur_price, init_price, is_pyr):
                    gain_pct = (cur_price / init_price - 1.0) * 100.0
                    print(f"  [PYRAMID CANDIDATE] {ticker} is up +{gain_pct:.1f}% from entry (₹{init_price:.2f} -> ₹{cur_price:.2f})")

                    portfolio = ledger.get_portfolio()
                    total_eq = portfolio.get("total_equity", STARTING_CAPITAL)
                    pyramid_alloc = max(total_eq * PYRAMID_ALLOCATION_PCT, STARTING_CAPITAL * PYRAMID_ALLOCATION_PCT)
                    available_cash = portfolio.get("cash_balance", 0.0)

                    budget = min(available_cash * 0.95, pyramid_alloc)
                    shares_to_add = int(budget / cur_price) if cur_price > 0 else 0

                    if shares_to_add > 0:
                        if not dry_run:
                            ledger.execute_pyramid_buy(ticker, cur_price, shares_to_add, eval_date_str)
                        else:
                            print(f"  [DRY-RUN] Would pyramid {shares_to_add} shares of {ticker} @ ₹{cur_price:.2f}")

                        pyramids_executed.append({
                            "ticker": ticker,
                            "shares": shares_to_add,
                            "price": cur_price,
                        })
                    else:
                        print(f"  [SKIP] Insufficient cash balance (₹{available_cash:,.2f}) to pyramid {ticker}.")

        # Step 4: Screening for New Stage 2 Breakouts
        print("\n[Step 4/5] Scanning Universe for Stage 2 52-Week Breakouts...")
        if not is_bullish:
            print("  [REGIME LOCK 🔒] Market Regime is BEARISH (Nifty 500 < 30w MA). Skipping new entry scans per V3.1 quantitative rules.")
        else:
            current_held = ledger.get_open_positions()
            if len(current_held) >= MAX_STARTER_POSITIONS:
                print(
                    f"  [CAPITAL LIMIT 🛡️] Max {MAX_STARTER_POSITIONS} starter positions reached ({MAX_STARTER_POSITIONS * 10}% allocation). "
                    f"Remaining 40% cash reserved exclusively for pyramiding tranches."
                )
            else:
                all_tickers = fetch_nifty500_tickers()
                universe_subset = all_tickers[:max_universe_tickers]
                already_held = {p["ticker"] for p in current_held}

                candidates_to_scan = [t for t in universe_subset if t not in already_held]
                print(f"  Scanning {len(candidates_to_scan)} candidate stocks (Open Starters: {len(current_held)}/{MAX_STARTER_POSITIONS})...")

                # Batch fetch weekly data
                scan_data = batch_fetch_weekly_universe(candidates_to_scan, period="2y")

                breakout_signals = []
                for ticker, df in scan_data.items():
                    ind = compute_weekly_indicators(df)
                    if ind.empty:
                        continue

                    last_bar = ind.iloc[-1]
                    if bool(last_bar.get("Stage2_Signal", False)):
                        close = float(last_bar["Close"])
                        vol_ratio = float(last_bar["Volume"] / last_bar["Vol_MA10"]) if last_bar["Vol_MA10"] > 0 else 1.0
                        ma30 = float(last_bar["MA30"])
                        breakout_signals.append({
                            "ticker": ticker,
                            "close": close,
                            "vol_ratio": vol_ratio,
                            "ma30": ma30,
                            "volume": float(last_bar["Volume"]),
                            "vol_ma10": float(last_bar["Vol_MA10"]),
                        })

                # Rank candidates by Relative Volume Confirmation
                breakout_signals.sort(key=lambda x: x["vol_ratio"], reverse=True)

                print(f"  Found {len(breakout_signals)} valid Stage 2 breakout setups:")
                for sig in breakout_signals:
                    print(
                        f"    -> {sig['ticker']:<12} | Close: ₹{sig['close']:>8.2f} | "
                        f"Vol Ratio: {sig['vol_ratio']:>5.2f}x (Vol: {int(sig['volume']):,} vs 10w Avg: {int(sig['vol_ma10']):,})"
                    )

                # Autonomous Playwright Fundamental Screening & Virtual Execution
                for sig in breakout_signals:
                    ticker = sig["ticker"]

                    # Check max starter positions limit (Cap at 6)
                    if len(ledger.get_open_positions()) >= MAX_STARTER_POSITIONS:
                        print(
                            f"  [CAPITAL LIMIT 🛡️] Max {MAX_STARTER_POSITIONS} starter positions reached ({MAX_STARTER_POSITIONS * 10}% allocation). "
                            f"Remaining 40% cash reserved exclusively for pyramiding tranches."
                        )
                        break

                    print(f"\n  [Auditing Fundamentals] Dispatching Playwright headless browser for '{ticker}'...")
                    fund_metrics = fetch_screener_metrics(ticker)
                    is_fund_ok, fund_reason = evaluate_fundamental_rules(fund_metrics)

                    if not is_fund_ok:
                        print(f"  [FUNDAMENTAL REJECT ❌] {ticker}: {fund_reason}")
                        logger.info(f"Skipping {ticker} due to fundamental filter failure: {fund_reason}")
                        continue

                    print(f"  [FUNDAMENTAL APPROVED ✅] {ticker}: {fund_reason}")

                    portfolio = ledger.get_portfolio()
                    cash = portfolio.get("cash_balance", 0.0)
                    total_eq = portfolio.get("total_equity", STARTING_CAPITAL)

                    alloc_target = max(total_eq * INITIAL_ALLOCATION_PCT, STARTING_CAPITAL * INITIAL_ALLOCATION_PCT)

                    if cash < alloc_target * 0.5:
                        print(f"  [CAPITAL LIMIT] Cash remaining (₹{cash:,.2f}) insufficient for new entry on {ticker}.")
                        break

                    alloc_to_use = min(cash * 0.95, alloc_target)
                    shares = int(alloc_to_use / sig["close"]) if sig["close"] > 0 else 0

                    if shares > 0:
                        trade_reason = (
                            f"Stage 2 52w Breakout (Vol: {sig['vol_ratio']:.1f}x) + "
                            f"Fundamentals Passed (ROCE: {fund_metrics.get('roce', 0.0):.1f}%, "
                            f"D/E: {fund_metrics.get('debt_to_equity', 0.0):.2f}, "
                            f"Pledge: {fund_metrics.get('pledged_pct', 0.0):.1f}%)"
                        )
                        if not dry_run:
                            ledger.execute_initial_buy(
                                sig["ticker"],
                                sig["close"],
                                shares,
                                eval_date_str,
                                sig["ma30"],
                                reason=trade_reason,
                            )
                        else:
                            print(f"  [DRY-RUN APPROVED] Would buy {shares} shares of {sig['ticker']} @ ₹{sig['close']:.2f} ({trade_reason})")

                        new_buys_executed.append({
                            "ticker": sig["ticker"],
                            "shares": shares,
                            "price": sig["close"],
                            "reason": trade_reason,
                        })

    # Step 5: Snapshot & Executive Summary & Telegram Alert & Cloud Sync
    if not dry_run:
        ledger.record_weekly_snapshot(eval_date_str, nifty_close, nifty_ma30, is_bullish)

        # Telegram report: sent on Friday or whenever exits / orders execute
        if mode == "full" or exits_executed:
            send_weekly_scan_report(
                portfolio=ledger.get_portfolio(),
                week_date=eval_date_str,
                nifty_close=nifty_close,
                nifty_ma30=nifty_ma30,
                regime_bullish=is_bullish,
                new_buys=new_buys_executed,
                exits=exits_executed,
                pyramids=pyramids_executed,
                open_positions=ledger.get_open_positions(),
                starting_capital=STARTING_CAPITAL,
            )

        # Automated Cloud Dashboard Sync to GitHub
        try:
            print("\n[Cloud Sync] Pushing updated ledger database to GitHub...")
            subprocess.run(["git", "add", "v3_multibagger_ledger.db"], check=True, cwd=BASE_DIR)
            status_res = subprocess.run(
                ["git", "status", "--porcelain", "v3_multibagger_ledger.db"],
                capture_output=True,
                text=True,
                cwd=BASE_DIR,
            )
            if status_res.stdout.strip():
                commit_msg = f"Automated ledger sync ({mode}) - {eval_date_str}"
                subprocess.run(["git", "commit", "-m", commit_msg], check=True, cwd=BASE_DIR)
                subprocess.run(["git", "push", "origin", "main"], check=True, cwd=BASE_DIR)
                print("[Cloud Sync] Successfully pushed updated ledger to GitHub ✅")
            else:
                print("[Cloud Sync] No changes detected in ledger to commit.")
        except Exception as e:
            logger.warning(f"[Cloud Sync] GitHub sync skipped/failed: {e}")

    print(f"\n[Step 5/5] Routine Complete ({mode}). Current Portfolio Dashboard:")
    display_portfolio_status(ledger)


def run_weekly_scan(ledger: V3Ledger, max_universe_tickers: int = 150, dry_run: bool = False, mode: str = "full"):
    """Backward compatibility entry point."""
    return run_engine(ledger=ledger, mode=mode, max_universe_tickers=max_universe_tickers, dry_run=dry_run)


def display_portfolio_status(ledger: V3Ledger):
    """Prints current portfolio dashboard."""
    portfolio = ledger.get_portfolio()
    positions = ledger.get_open_positions()

    cash = portfolio.get("cash_balance", 0.0)
    invested = sum(p["current_value"] for p in positions)
    total_equity = cash + invested
    peak = max(portfolio.get("peak_equity", STARTING_CAPITAL), total_equity)
    drawdown = (peak - total_equity) / peak * 100.0 if peak > 0 else 0.0
    total_gain_pct = (total_equity / STARTING_CAPITAL - 1.0) * 100.0

    print("\n" + "=" * 85)
    print("                        PORTFOLIO LEDGER DASHBOARD (V3.1)")
    print("=" * 85)
    print(f" Starting Capital   : ₹{STARTING_CAPITAL:,.2f}")
    print(f" Current Cash       : ₹{cash:,.2f} ({cash / total_equity * 100.0:.1f}%)")
    print(f" Invested Value     : ₹{invested:,.2f} ({invested / total_equity * 100.0:.1f}%)")
    print(f" Total NAV / Equity : ₹{total_equity:,.2f}")
    print(f" Overall Return     : {total_gain_pct:+.2f}%")
    print(f" Peak Equity        : ₹{peak:,.2f}")
    print(f" Current Drawdown   : -{drawdown:.2f}%")
    print(f" Open Positions     : {len(positions)} / {MAX_STARTER_POSITIONS} Max Starters")
    print("-" * 85)

    if not positions:
        print(" No active positions. 100% Cash.")
    else:
        print(f"{'Ticker':<12} {'Shares':<7} {'Buy (₹)':<10} {'Cur (₹)':<10} {'Value (₹)':<11} {'PnL (₹)':<11} {'PnL %':<9} {'Stop (₹)':<10} {'Pyr?':<5} {'Status'}")
        print("-" * 85)
        for p in positions:
            pyr = "YES" if p["is_pyramided"] else "NO"
            st_badge = p.get("status", "OPEN")
            print(
                f"{p['ticker']:<12} "
                f"{p['total_shares']:<7} "
                f"{p['avg_price']:>9.2f} "
                f"{p['current_price']:>9.2f} "
                f"₹{p['current_value']:>9,.0f} "
                f"₹{p['unrealized_pnl']:>+9,.0f} "
                f"{p['unrealized_pnl_pct']:>+7.1f}% "
                f"{p['current_stop_price']:>9.2f} "
                f"{pyr:<5} "
                f"{st_badge}"
            )
    print("=" * 85 + "\n")


def display_trade_history(ledger: V3Ledger):
    """Displays closed trade ledger."""
    trades = ledger.get_closed_trades()
    print("\n" + "=" * 85)
    print("                       V3 PAPER TRADING EXECUTION LEDGER")
    print("=" * 85)
    if not trades:
        print(" No recorded trades in database yet.")
    else:
        print(f"{'ID':<4} {'Date':<11} {'Ticker':<12} {'Action':<13} {'Qty':<6} {'Price':<10} {'Amount (₹)':<12} {'PnL (₹)':<12} {'Ret %'}")
        print("-" * 85)
        for t in trades:
            d_str = t["timestamp"][:10]
            pnl_str = f"₹{t['realized_pnl']:+,.0f}" if t["realized_pnl"] != 0 else "-"
            ret_str = f"{t['return_pct']:+.1f}%" if t["return_pct"] != 0 else "-"
            print(
                f"{t['trade_id']:<4} "
                f"{d_str:<11} "
                f"{t['ticker']:<12} "
                f"{t['action']:<13} "
                f"{t['shares']:<6} "
                f"{t['price']:>9.2f} "
                f"₹{t['gross_amount']:>10,.0f} "
                f"{pnl_str:>12} "
                f"{ret_str:>8}"
            )
    print("=" * 85 + "\n")


def main():
    parser = argparse.ArgumentParser(description="V3.1 Multibagger Live Paper Trading Engine")
    parser.add_argument("--scan", action="store_true", help="Run scan and paper trade execution")
    parser.add_argument(
        "--mode",
        choices=["full", "exits_only"],
        default="full",
        help="Execution mode: 'full' (Friday: exits, pyramids, and Stage 2 scans) or 'exits_only' (daily: monitor trailing stops and lower circuits)",
    )
    parser.add_argument("--status", action="store_true", help="Display current portfolio holdings and ledger state")
    parser.add_argument("--history", action="store_true", help="Display complete trade execution history")
    parser.add_argument("--reset", action="store_true", help="Reset database to clean ₹100,000 virtual capital")
    parser.add_argument("--dry-run", action="store_true", help="Run scan without modifying database ledger")
    parser.add_argument("--tickers", type=int, default=150, help="Number of universe tickers to scan (default: 150)")
    args = parser.parse_args()

    ledger = V3Ledger()

    if args.reset:
        confirm = input("Are you sure you want to reset the paper trading ledger to ₹100,000? (y/N): ").strip().lower()
        if confirm == "y":
            ledger.reset_ledger()
        else:
            print("Reset cancelled.")
        return

    if args.history:
        display_trade_history(ledger)
        return

    if args.status:
        display_portfolio_status(ledger)
        return

    # Run engine in specified mode
    run_engine(ledger, mode=args.mode, max_universe_tickers=args.tickers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
