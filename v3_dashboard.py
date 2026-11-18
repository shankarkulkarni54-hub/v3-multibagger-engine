"""
V3 Multibagger Engine - Live Streamlit Quantitative Dashboard
Interactive visual monitoring for portfolio NAV, active positions, trade ledger,
market regime status, and automated execution logs.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

from config import DB_PATH, STARTING_CAPITAL
from telegram_notifier import is_telegram_configured

# Page setup
st.set_page_config(
    page_title="V3 Multibagger Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .metric-card {
        background-color: #1e222d;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #2e3546;
    }
    .badge-bullish {
        background-color: #1b5e20;
        color: #a5d6a7;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.9rem;
    }
    .badge-bearish {
        background-color: #b71c1c;
        color: #ef9a9a;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=5)
def load_data():
    """Loads all tables from SQLite ledger."""
    if not DB_PATH.exists():
        return None, None, None, None

    conn = get_db_connection()
    try:
        portfolio_df = pd.read_sql("SELECT * FROM portfolio WHERE id = 1", conn)
        positions_df = pd.read_sql("SELECT * FROM positions", conn)
        trades_df = pd.read_sql("SELECT * FROM trades ORDER BY trade_id DESC", conn)
        snapshots_df = pd.read_sql("SELECT * FROM weekly_snapshots ORDER BY snapshot_id DESC", conn)
        return portfolio_df, positions_df, trades_df, snapshots_df
    finally:
        conn.close()


# Load database
portfolio_df, positions_df, trades_df, snapshots_df = load_data()

# Sidebar
with st.sidebar:
    st.title("🚀 V3 Multibagger")
    st.caption("Stage 2 Weekly Quantitative Engine")
    st.markdown("---")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("### ⚙️ System Status")
    db_status = "Connected ✅" if DB_PATH.exists() else "DB Not Found ❌"
    st.write(f"**Database:** `{DB_PATH.name}` ({db_status})")

    tg_status = "Active ✅" if is_telegram_configured() else "Unconfigured ⚠️"
    st.write(f"**Telegram Alerts:** {tg_status}")
    if not is_telegram_configured():
        st.caption("Add `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` in `.env` to enable alerts.")

    st.markdown("---")
    st.markdown("### 📐 Strategy Rules")
    st.markdown("""
    - **Timeframe:** Weekly bars (`W-FRI`)
    - **Regime Filter:** Nifty 500 > 30-week MA
    - **Setup:** 52w High + 30w MA Trend Up
    - **Volume:** Breakout Vol > 1.5x 10w Avg
    - **Fundamentals:** ROCE > 15%, D/E < 1.0, Pledge < 5%
    - **Sizing:** 10% Initial (₹10k base)
    - **Pyramid:** +10% on +20% gain (Max 20%)
    - **Trailing Stop:** Close < 15% sub-30w MA
    """)

    st.markdown("---")
    st.caption(f"Last sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# Main Content Header
st.title("📈 V3 Multibagger Quantitative Trading Ledger")
st.caption("Institutional Trend Following & Playwright Fundamental Filter for Indian Equities (NSE)")

if portfolio_df is None or portfolio_df.empty:
    st.error(f"Could not load ledger from `{DB_PATH}`. Please run `python v3_weekly_engine.py --scan` to initialize.")
    st.stop()

# Header Metrics Calculation
port = portfolio_df.iloc[0]
cash = float(port["cash_balance"])
invested = float(port["invested_value"])
total_equity = float(port["total_equity"])
peak_equity = float(port["peak_equity"])
overall_pnl = total_equity - STARTING_CAPITAL
overall_ret_pct = (total_equity / STARTING_CAPITAL - 1.0) * 100.0
drawdown_pct = (peak_equity - total_equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total NAV", f"₹{total_equity:,.2f}", f"{overall_ret_pct:+.2f}%")
with col2:
    st.metric("Cash Balance", f"₹{cash:,.2f}", f"{cash / total_equity * 100.0:.1f}% Cash")
with col3:
    st.metric("Invested Capital", f"₹{invested:,.2f}", f"{invested / total_equity * 100.0:.1f}% Exposure")
with col4:
    st.metric("Overall Return", f"{overall_ret_pct:+.2f}%", f"₹{overall_pnl:+,.2f}")
with col5:
    st.metric("Peak Drawdown", f"-{drawdown_pct:.2f}%", f"Peak: ₹{peak_equity:,.0f}")

st.markdown("---")

# Navigation Tabs
tab1, tab2, tab3 = st.tabs(["📊 Active Positions", "📜 Trade History", "🌐 Regime & Scan Logs"])


# ----------------------------------------------------------------------------------------
# TAB 1: ACTIVE POSITIONS
# ----------------------------------------------------------------------------------------
with tab1:
    open_positions = positions_df[positions_df["status"] == "OPEN"].copy() if not positions_df.empty else pd.DataFrame()

    st.subheader(f"Current Holdings ({len(open_positions)} Open Positions)")

    if open_positions.empty:
        st.info("No active positions currently held. Portfolio is 100% Cash.")
    else:
        # Calculate buffer to trailing stop
        open_positions["buffer_pct"] = (
            (open_positions["current_price"] / open_positions["current_stop_price"] - 1.0) * 100.0
        )
        open_positions["pyr_label"] = open_positions["is_pyramided"].apply(lambda x: "YES (+10%)" if x else "NO")

        # Format dataframe for display
        display_df = pd.DataFrame({
            "Ticker": open_positions["ticker"],
            "Shares": open_positions["total_shares"],
            "Avg Buy Price": open_positions["avg_price"].apply(lambda x: f"₹{x:,.2f}"),
            "Current Price": open_positions["current_price"].apply(lambda x: f"₹{x:,.2f}"),
            "Invested (₹)": open_positions["total_invested"].apply(lambda x: f"₹{x:,.0f}"),
            "Current Value (₹)": open_positions["current_value"].apply(lambda x: f"₹{x:,.0f}"),
            "Unrealized P&L (₹)": open_positions["unrealized_pnl"].apply(lambda x: f"₹{x:+,.0f}"),
            "Return %": open_positions["unrealized_pnl_pct"].apply(lambda x: f"{x:+.2f}%"),
            "30-Wk MA": open_positions["current_ma30"].apply(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "-"),
            "Trailing Stop (₹)": open_positions["current_stop_price"].apply(lambda x: f"₹{x:,.2f}" if pd.notna(x) else "-"),
            "Stop Buffer %": open_positions["buffer_pct"].apply(lambda x: f"+{x:.1f}%" if pd.notna(x) else "-"),
            "Pyramided?": open_positions["pyr_label"],
            "Entry Date": open_positions["initial_date"],
        })

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Asset Allocation Visual
        col_c1, col_c2 = st.columns([1, 1])
        with col_c1:
            st.markdown("#### 🥧 Portfolio Allocation")
            alloc_data = {"Asset": ["Cash"], "Value": [cash]}
            for _, r in open_positions.iterrows():
                alloc_data["Asset"].append(r["ticker"])
                alloc_data["Value"].append(r["current_value"])
            alloc_df = pd.DataFrame(alloc_data)
            st.bar_chart(alloc_df.set_index("Asset"), use_container_width=True)

        with col_c2:
            st.markdown("#### 🎯 Position Unrealized Returns")
            pnl_chart_df = pd.DataFrame({
                "Ticker": open_positions["ticker"],
                "Return %": open_positions["unrealized_pnl_pct"],
            }).set_index("Ticker")
            st.bar_chart(pnl_chart_df, use_container_width=True)


# ----------------------------------------------------------------------------------------
# TAB 2: TRADE HISTORY
# ----------------------------------------------------------------------------------------
with tab2:
    st.subheader("Historical Execution Ledger")

    if trades_df.empty:
        st.info("No trade transactions executed yet.")
    else:
        # Summary statistics on closed trades
        closed_trades = trades_df[trades_df["action"] == "EXIT_STOP"].copy()
        wins = closed_trades[closed_trades["realized_pnl"] > 0]
        losses = closed_trades[closed_trades["realized_pnl"] <= 0]

        win_rate = (len(wins) / len(closed_trades) * 100.0) if len(closed_trades) > 0 else 0.0
        total_pnl = closed_trades["realized_pnl"].sum() if not closed_trades.empty else 0.0

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Total Completed Trades", len(closed_trades))
        with m2:
            st.metric("Win Rate", f"{win_rate:.1f}%", f"{len(wins)}W / {len(losses)}L")
        with m3:
            st.metric("Realized P&L", f"₹{total_pnl:+,.2f}")
        with m4:
            avg_hold = closed_trades["holding_weeks"].mean() if not closed_trades.empty else 0.0
            st.metric("Avg Holding Period", f"{avg_hold:.1f} weeks")

        st.markdown("---")

        # Filter option
        filter_type = st.radio("Filter Trades:", ["All Executions", "Exits Only (Closed Trades)", "Buys Only"], horizontal=True)

        filtered_trades = trades_df
        if filter_type == "Exits Only (Closed Trades)":
            filtered_trades = trades_df[trades_df["action"] == "EXIT_STOP"]
        elif filter_type == "Buys Only":
            filtered_trades = trades_df[trades_df["action"].isin(["INITIAL_BUY", "PYRAMID_BUY"])]

        format_trades = pd.DataFrame({
            "Trade ID": filtered_trades["trade_id"],
            "Timestamp": filtered_trades["timestamp"].apply(lambda x: str(x)[:16]),
            "Ticker": filtered_trades["ticker"],
            "Action": filtered_trades["action"],
            "Shares": filtered_trades["shares"],
            "Price (₹)": filtered_trades["price"].apply(lambda x: f"₹{x:,.2f}"),
            "Gross Amount": filtered_trades["gross_amount"].apply(lambda x: f"₹{x:,.0f}"),
            "Realized P&L (₹)": filtered_trades["realized_pnl"].apply(lambda x: f"₹{x:+,.0f}" if x != 0 else "-"),
            "Return %": filtered_trades["return_pct"].apply(lambda x: f"{x:+.2f}%" if x != 0 else "-"),
            "Held (Weeks)": filtered_trades["holding_weeks"].apply(lambda x: f"{x} wks" if x > 0 else "-"),
            "Execution Reason": filtered_trades["reason"],
        })

        st.dataframe(format_trades, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------------------
# TAB 3: REGIME & LOGS
# ----------------------------------------------------------------------------------------
with tab3:
    st.subheader("Market Regime & Historical Snapshots")

    # Current Market Regime Card
    latest_snap = snapshots_df.iloc[0] if not snapshots_df.empty else None
    if latest_snap is not None:
        regime_bullish = bool(latest_snap["regime_bullish"])
        nifty_close = float(latest_snap["nifty500_close"]) if pd.notna(latest_snap["nifty500_close"]) else 0.0
        nifty_ma30 = float(latest_snap["nifty500_ma30"]) if pd.notna(latest_snap["nifty500_ma30"]) else 0.0
        nifty_diff_pct = (nifty_close / nifty_ma30 - 1.0) * 100.0 if nifty_ma30 > 0 else 0.0

        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.markdown("**Market Regime Filter**")
            if regime_bullish:
                st.markdown("<span class='badge-bullish'>🟢 BULLISH — ENTRIES ALLOWED</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='badge-bearish'>🔴 BEARISH — ENTRIES BLOCKED</span>", unsafe_allow_html=True)
        with r2:
            st.metric("Nifty 500 Close", f"{nifty_close:,.2f}", f"{nifty_diff_pct:+.2f}% vs 30w MA")
        with r3:
            st.metric("Nifty 500 30-Wk MA", f"{nifty_ma30:,.2f}")
        with r4:
            st.metric("As of Week", str(latest_snap["week_date"]))

    st.markdown("---")

    # Historical NAV progression chart
    if not snapshots_df.empty and len(snapshots_df) > 1:
        st.markdown("#### 📈 Weekly Portfolio Equity Progression")
        chart_data = snapshots_df.sort_values("snapshot_id").copy()
        chart_data["Date"] = pd.to_datetime(chart_data["week_date"])
        equity_chart = chart_data.set_index("Date")[["total_equity", "cash_balance", "invested_value"]]
        st.line_chart(equity_chart, use_container_width=True)

    # Snapshots Table
    st.markdown("#### 📋 Weekly Snapshots Log")
    if snapshots_df.empty:
        st.info("No weekly snapshots recorded yet.")
    else:
        disp_snap = pd.DataFrame({
            "Snapshot ID": snapshots_df["snapshot_id"],
            "Week Date": snapshots_df["week_date"],
            "Total NAV": snapshots_df["total_equity"].apply(lambda x: f"₹{x:,.2f}"),
            "Cash": snapshots_df["cash_balance"].apply(lambda x: f"₹{x:,.2f}"),
            "Invested": snapshots_df["invested_value"].apply(lambda x: f"₹{x:,.2f}"),
            "Holdings": snapshots_df["open_positions_count"],
            "Nifty 500": snapshots_df["nifty500_close"].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "-"),
            "Nifty 30w MA": snapshots_df["nifty500_ma30"].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "-"),
            "Regime": snapshots_df["regime_bullish"].apply(lambda x: "🟢 Bullish" if x else "🔴 Bearish"),
            "Notes": snapshots_df["notes"],
        })
        st.dataframe(disp_snap, use_container_width=True, hide_index=True)
