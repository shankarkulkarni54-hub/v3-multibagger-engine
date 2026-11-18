"""
V3 Multibagger Engine - Live Quantitative Dashboard
Institutional-grade Streamlit UI for monitoring portfolio NAV, active positions,
trade history, market regime status, and weekly execution logs.
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from config import DB_PATH, STARTING_CAPITAL
from telegram_notifier import is_telegram_configured

# -----------------------------------------------------------------------------
# 1. Page Configuration & Custom CSS (Strictly Wide-Screen & Anti-Truncation)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="V3 Multibagger Engine — Live Dashboard",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Metric Card Typography - Fix text ellipsis and truncation */
    div[data-testid="stMetricValue"] {
        font-size: 1.45rem !important;
        font-weight: 700 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.25 !important;
    }
    div[data-testid="stMetricValue"] > div {
        font-size: 1.45rem !important;
        font-weight: 700 !important;
        white-space: normal !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.6px !important;
        color: #8f9bb3 !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.85rem !important;
        font-weight: 600 !important;
    }

    /* Status Badges */
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.4px;
    }
    .badge-bullish {
        background-color: rgba(46, 125, 50, 0.2);
        color: #4caf50;
        border: 1px solid rgba(76, 175, 80, 0.4);
    }
    .badge-bearish {
        background-color: rgba(198, 40, 40, 0.2);
        color: #ef5350;
        border: 1px solid rgba(239, 83, 80, 0.4);
    }
    .badge-pyr {
        background-color: rgba(30, 136, 229, 0.2);
        color: #42a5f5;
        border: 1px solid rgba(66, 165, 245, 0.4);
    }

    /* Container card styling */
    .card-box {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. Currency Formatting Helper (Indian Numbering Format)
# -----------------------------------------------------------------------------
def format_inr(val: Any, decimals: int = 2) -> str:
    """Format numeric values into standard Indian currency with commas."""
    if val is None or pd.isna(val):
        return "₹0.00"
    try:
        val_f = float(val)
    except (ValueError, TypeError):
        return "₹0.00"

    sign = "-" if val_f < 0 else ""
    abs_v = abs(val_f)

    if decimals > 0:
        base_int = int(abs_v)
        dec_part = f"{abs_v - base_int:.{decimals}f}"[1:]  # includes dot
    else:
        base_int = int(round(abs_v))
        dec_part = ""

    s = str(base_int)
    if len(s) <= 3:
        return f"{sign}₹{s}{dec_part}"

    last3 = s[-3:]
    rest = s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)

    return f"{sign}₹{','.join(groups)},{last3}{dec_part}"


# -----------------------------------------------------------------------------
# 3. Read-Only Database Queries
# -----------------------------------------------------------------------------
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


# Load data
portfolio_df, positions_df, trades_df, snapshots_df = load_data()


# -----------------------------------------------------------------------------
# 4. Sidebar Controls & Quantitative Reference
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🚀 V3 Multibagger")
    st.caption("Weekly Stage 2 Trend + Playwright Fundamentals")
    st.markdown("---")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("### ⚙️ System Status")
    db_status = "Connected ✅" if DB_PATH.exists() else "DB Missing ❌"
    st.write(f"**Database:** `{DB_PATH.name}` ({db_status})")

    tg_status = "Active ✅" if is_telegram_configured() else "Unconfigured ⚠️"
    st.write(f"**Telegram Alerts:** {tg_status}")
    if not is_telegram_configured():
        st.caption("Add `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` to `.env` to enable alerts.")

    st.markdown("---")
    st.markdown("### 📐 Strategy Rules")
    st.markdown("""
    - **Timeframe:** Weekly Friday EOD (`W-FRI`)
    - **Regime Filter:** Nifty 500 > 30-week MA
    - **Setup:** 52w High + 30w MA Trend Up
    - **Volume:** Breakout Vol > 1.5x 10w Avg
    - **Fundamentals:** ROCE > 15%, D/E < 1.0, Pledge < 5%
    - **Sizing:** 10% Initial (₹10,000 base)
    - **Pyramid:** +10% on +20% gain (Max 20%)
    - **Trailing Stop:** Weekly Close < 15% sub-MA30
    """)

    st.markdown("---")
    st.caption(f"Last sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# -----------------------------------------------------------------------------
# 5. Top Header & 4-Column KPI Grid
# -----------------------------------------------------------------------------
st.title("📈 V3 Multibagger Portfolio Dashboard")
st.caption("Live Autonomous Paper Trading Engine | Indian Equities (NSE)")

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

open_positions = positions_df[positions_df["status"] == "OPEN"].copy() if (positions_df is not None and not positions_df.empty) else pd.DataFrame()
open_count = len(open_positions)
cash_pct = (cash / total_equity * 100.0) if total_equity > 0 else 100.0
invested_pct = (invested / total_equity * 100.0) if total_equity > 0 else 0.0

# 4-Column Clean Layout (Prevents truncation on any screen size)
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Total Portfolio NAV",
        value=format_inr(total_equity, decimals=2),
        delta=f"{overall_ret_pct:+.2f}% ({format_inr(overall_pnl, decimals=0)})",
    )
with col2:
    st.metric(
        label="Available Cash",
        value=format_inr(cash, decimals=2),
        delta=f"{cash_pct:.1f}% Capital Reserve",
        delta_color="off",
    )
with col3:
    st.metric(
        label="Invested Capital",
        value=format_inr(invested, decimals=2),
        delta=f"{invested_pct:.1f}% Exposure ({open_count} Position{'s' if open_count != 1 else ''})",
        delta_color="off",
    )
with col4:
    st.metric(
        label="Overall Performance",
        value=f"{overall_ret_pct:+.2f}%",
        delta=f"Peak: {format_inr(peak_equity, decimals=0)} | DD: -{drawdown_pct:.2f}%",
        delta_color="normal" if overall_ret_pct >= 0 else "inverse",
    )

st.markdown("---")


# -----------------------------------------------------------------------------
# 6. Navigation Tabs
# -----------------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📊 Active Positions", "📜 Trade History", "🌐 Regime & Scan Logs"])


# ----------------------------------------------------------------------------------------
# TAB 1: ACTIVE POSITIONS
# ----------------------------------------------------------------------------------------
with tab1:
    st.subheader(f"Current Holdings ({open_count} Open Positions)")

    if open_positions.empty:
        st.info("No active positions currently held. Portfolio is 100% Cash.")
    else:
        # Buffer to trailing stop
        open_positions["buffer_pct"] = (
            (open_positions["current_price"] / open_positions["current_stop_price"] - 1.0) * 100.0
        )
        open_positions["pyr_label"] = open_positions["is_pyramided"].apply(lambda x: "YES (+10%)" if x else "NO")

        # Color-coded PnL text
        open_positions["pnl_display"] = open_positions.apply(
            lambda r: f"{'+' if r['unrealized_pnl'] >= 0 else ''}{format_inr(r['unrealized_pnl'], decimals=0)} ({r['unrealized_pnl_pct']:+.2f}%)",
            axis=1,
        )

        # Formatted Display Table
        display_df = pd.DataFrame({
            "Ticker": open_positions["ticker"],
            "Shares": open_positions["total_shares"],
            "Avg Buy Price": open_positions["avg_price"].apply(lambda x: format_inr(x, decimals=2)),
            "Current LTP": open_positions["current_price"].apply(lambda x: format_inr(x, decimals=2)),
            "Market Value": open_positions["current_value"].apply(lambda x: format_inr(x, decimals=0)),
            "Unrealized P&L": open_positions["pnl_display"],
            "30-Wk MA": open_positions["current_ma30"].apply(lambda x: format_inr(x, decimals=2) if pd.notna(x) else "-"),
            "Trailing Stop (15% sub-MA)": open_positions["current_stop_price"].apply(lambda x: format_inr(x, decimals=2) if pd.notna(x) else "-"),
            "Stop Buffer %": open_positions["buffer_pct"].apply(lambda x: f"+{x:.1f}%" if pd.notna(x) else "-"),
            "Pyramided?": open_positions["pyr_label"],
            "Entry Date": open_positions["initial_date"],
        })

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        st.markdown("<br/>", unsafe_allow_html=True)

        # Side-by-Side Plotly Visualizations
        col_c1, col_c2 = st.columns(2)

        with col_c1:
            st.markdown("#### 🥧 Portfolio Allocation")
            alloc_labels = ["Cash"] + open_positions["ticker"].tolist()
            alloc_values = [cash] + open_positions["current_value"].tolist()
            colors = ["#26a69a", "#1e88e5", "#7e57c2", "#ffa726", "#42a5f5", "#ab47bc"]

            fig_donut = go.Figure(data=[go.Pie(
                labels=alloc_labels,
                values=alloc_values,
                hole=0.55,
                marker=dict(colors=colors[:len(alloc_labels)]),
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>Value: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
            )])
            fig_donut.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=30, b=20),
                height=340,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                annotations=[dict(
                    text=f"Total NAV<br><b>{format_inr(total_equity, decimals=0)}</b>",
                    x=0.5, y=0.5,
                    font_size=13,
                    showarrow=False,
                )]
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        with col_c2:
            st.markdown("#### 🎯 Position Unrealized Returns")
            tickers = open_positions["ticker"].tolist()
            pnl_pcts = open_positions["unrealized_pnl_pct"].tolist()
            bar_colors = ["#2e7d32" if v >= 0 else "#c62828" for v in pnl_pcts]
            bar_text = [f"{v:+.2f}%" for v in pnl_pcts]

            fig_bar = go.Figure(data=[go.Bar(
                x=tickers,
                y=pnl_pcts,
                marker=dict(color=bar_colors),
                text=bar_text,
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Unrealized Return: %{y:+.2f}%<extra></extra>",
            )])
            fig_bar.add_hline(y=0, line_dash="solid", line_color="rgba(255,255,255,0.25)", line_width=1)
            fig_bar.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=30, b=20),
                height=340,
                xaxis=dict(title="", tickfont=dict(size=12, weight="bold")),
                yaxis=dict(title="Return (%)", zeroline=False),
            )
            st.plotly_chart(fig_bar, use_container_width=True)


# ----------------------------------------------------------------------------------------
# TAB 2: TRADE HISTORY
# ----------------------------------------------------------------------------------------
with tab2:
    st.subheader("Historical Execution Ledger")

    if trades_df is None or trades_df.empty:
        st.info("No trade transactions executed yet.")
    else:
        # Closed trade metrics
        closed_trades = trades_df[trades_df["action"] == "EXIT_STOP"].copy()
        wins = closed_trades[closed_trades["realized_pnl"] > 0]
        losses = closed_trades[closed_trades["realized_pnl"] <= 0]

        win_rate = (len(wins) / len(closed_trades) * 100.0) if len(closed_trades) > 0 else 0.0
        total_realized_pnl = closed_trades["realized_pnl"].sum() if not closed_trades.empty else 0.0
        avg_hold = closed_trades["holding_weeks"].mean() if not closed_trades.empty else 0.0

        # Summary Row (4 Columns)
        th1, th2, th3, th4 = st.columns(4)
        with th1:
            st.metric("Total Closed Trades", len(closed_trades))
        with th2:
            st.metric("Win Rate", f"{win_rate:.1f}%", f"{len(wins)}W / {len(losses)}L")
        with th3:
            st.metric("Realized P&L", format_inr(total_realized_pnl, decimals=2))
        with th4:
            st.metric("Avg Holding Duration", f"{avg_hold:.1f} weeks")

        st.markdown("---")

        # Filter option
        filter_type = st.radio("Filter Trades:", ["All Executions", "Exits Only (Closed Trades)", "Buys Only"], horizontal=True)

        filtered_trades = trades_df
        if filter_type == "Exits Only (Closed Trades)":
            filtered_trades = trades_df[trades_df["action"] == "EXIT_STOP"]
        elif filter_type == "Buys Only":
            filtered_trades = trades_df[trades_df["action"].isin(["INITIAL_BUY", "PYRAMID_BUY"])]

        format_trades = pd.DataFrame({
            "Trade ID": filtered_trades["trade_id"].apply(lambda x: f"#{x}"),
            "Date": filtered_trades["timestamp"].apply(lambda x: str(x)[:16]),
            "Ticker": filtered_trades["ticker"],
            "Action": filtered_trades["action"],
            "Shares": filtered_trades["shares"],
            "Price": filtered_trades["price"].apply(lambda x: format_inr(x, decimals=2)),
            "Gross Amount": filtered_trades["gross_amount"].apply(lambda x: format_inr(x, decimals=0)),
            "Realized P&L": filtered_trades["realized_pnl"].apply(lambda x: format_inr(x, decimals=0) if x != 0 else "-"),
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
    latest_snap = snapshots_df.iloc[0] if (snapshots_df is not None and not snapshots_df.empty) else None
    if latest_snap is not None:
        regime_bullish = bool(latest_snap["regime_bullish"])
        nifty_close = float(latest_snap["nifty500_close"]) if pd.notna(latest_snap["nifty500_close"]) else 0.0
        nifty_ma30 = float(latest_snap["nifty500_ma30"]) if pd.notna(latest_snap["nifty500_ma30"]) else 0.0
        nifty_diff_pct = (nifty_close / nifty_ma30 - 1.0) * 100.0 if nifty_ma30 > 0 else 0.0

        r1, r2, r3, r4 = st.columns(4)
        with r1:
            st.markdown("**Market Regime Filter**")
            if regime_bullish:
                st.markdown("<span class='badge badge-bullish'>🟢 BULLISH — ENTRIES ALLOWED</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='badge badge-bearish'>🔴 BEARISH — ENTRIES BLOCKED</span>", unsafe_allow_html=True)
        with r2:
            st.metric("Nifty 500 Close", format_inr(nifty_close, decimals=2), f"{nifty_diff_pct:+.2f}% vs 30w MA")
        with r3:
            st.metric("Nifty 500 30-Wk MA", format_inr(nifty_ma30, decimals=2))
        with r4:
            st.metric("As of Week", str(latest_snap["week_date"]))

    st.markdown("---")

    # Historical NAV Progression Chart (Plotly Area)
    if snapshots_df is not None and not snapshots_df.empty and len(snapshots_df) > 1:
        st.markdown("#### 📈 Weekly Portfolio Equity Trajectory")
        chart_data = snapshots_df.sort_values("snapshot_id").copy()
        chart_data["Date"] = pd.to_datetime(chart_data["week_date"])

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=chart_data["Date"],
            y=chart_data["total_equity"],
            mode="lines+markers",
            name="Portfolio NAV",
            line=dict(color="#1e88e5", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(30, 136, 229, 0.12)",
            hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>NAV:</b> ₹%{y:,.2f}<extra></extra>",
        ))
        fig_eq.add_hline(
            y=STARTING_CAPITAL,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"Starting Capital ({format_inr(STARTING_CAPITAL, decimals=0)})",
        )
        fig_eq.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=30, b=20),
            height=360,
            xaxis_title="Week",
            yaxis_title="Portfolio NAV (₹)",
            hovermode="x unified",
        )
        st.plotly_chart(fig_eq, use_container_width=True)

    # Snapshots Log Table
    st.markdown("#### 📋 Weekly Snapshots Log")
    if snapshots_df is None or snapshots_df.empty:
        st.info("No weekly snapshots recorded yet.")
    else:
        disp_snap = pd.DataFrame({
            "Snapshot ID": snapshots_df["snapshot_id"].apply(lambda x: f"#{x}"),
            "Week Date": snapshots_df["week_date"],
            "Total NAV": snapshots_df["total_equity"].apply(lambda x: format_inr(x, decimals=2)),
            "Cash": snapshots_df["cash_balance"].apply(lambda x: format_inr(x, decimals=2)),
            "Invested": snapshots_df["invested_value"].apply(lambda x: format_inr(x, decimals=2)),
            "Holdings": snapshots_df["open_positions_count"],
            "Nifty 500": snapshots_df["nifty500_close"].apply(lambda x: format_inr(x, decimals=2) if pd.notna(x) else "-"),
            "Nifty 30w MA": snapshots_df["nifty500_ma30"].apply(lambda x: format_inr(x, decimals=2) if pd.notna(x) else "-"),
            "Regime": snapshots_df["regime_bullish"].apply(lambda x: "🟢 Bullish" if x else "🔴 Bearish"),
            "Notes": snapshots_df["notes"],
        })
        st.dataframe(disp_snap, use_container_width=True, hide_index=True)
