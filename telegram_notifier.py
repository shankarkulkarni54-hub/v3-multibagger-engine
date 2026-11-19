"""
V3 Multibagger Engine - Telegram Notification Module
Sends structured weekly scan reports and execution alerts via Telegram Bot API.
"""

import os
import html
import logging
import requests
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

logger = logging.getLogger("TelegramNotifier")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def is_telegram_configured() -> bool:
    """Checks whether valid Telegram credentials are configured in .env."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return bool(token and chat_id and "your_telegram" not in token.lower())


def send_telegram_message(
    message: str,
    parse_mode: str = "HTML",
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    Sends a message to the configured Telegram chat via Telegram Bot API.
    """
    bot_token = (token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    target_chat = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()

    if not bot_token or not target_chat or "your_telegram" in bot_token.lower():
        logger.info("[Telegram] Notifications skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        if response.status_code == 200:
            logger.info("[Telegram] Alert sent successfully.")
            return True
        elif response.status_code == 400 and parse_mode == "HTML":
            # Fallback to plain text if HTML tags were rejected
            payload["parse_mode"] = None
            retry = requests.post(url, json=payload, timeout=timeout)
            if retry.status_code == 200:
                logger.info("[Telegram] Alert sent successfully (fallback plain text).")
                return True
            logger.error(f"[Telegram] Failed to send alert: {retry.status_code} - {retry.text}")
            return False
        else:
            logger.error(f"[Telegram] API error {response.status_code}: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logger.error(f"[Telegram] Network error connecting to Telegram Bot API: {e}")
        return False


def build_weekly_alert_payload(
    portfolio: Dict,
    week_date: str,
    nifty_close: float,
    nifty_ma30: float,
    regime_bullish: bool,
    new_buys: List[Dict],
    exits: List[Dict],
    pyramids: List[Dict],
    open_positions: List[Dict],
    starting_capital: float = 100_000.0,
) -> str:
    """
    Constructs a clean HTML-formatted weekly Telegram summary message.
    """
    cash = portfolio.get("cash_balance", 0.0)
    invested = sum(p.get("current_value") or (p.get("total_shares", 0) * p.get("current_price", 0.0)) for p in open_positions)
    nav = cash + invested
    total_gain_pct = (nav / starting_capital - 1.0) * 100.0 if starting_capital > 0 else 0.0
    cash_pct = (cash / nav * 100.0) if nav > 0 else 0.0

    regime_icon = "🟢" if regime_bullish else "🔴"
    regime_label = "BULLISH (Entries Allowed)" if regime_bullish else "BEARISH (Entries Blocked)"

    lines = []
    lines.append("🚀 <b>V3 MULTIBAGGER ENGINE — FRIDAY SCAN</b>")
    lines.append(f"📅 <i>Week Ending: {html.escape(week_date)}</i>")
    lines.append(
        f"📊 <b>Regime:</b> {regime_icon} <b>{regime_label}</b>\n"
        f"    Nifty 500: <code>{nifty_close:,.2f}</code> | 30w MA: <code>{nifty_ma30:,.2f}</code>"
    )
    lines.append("")

    # 1. Portfolio NAV & Cash
    lines.append("💰 <b>PORTFOLIO STATUS</b>")
    lines.append(f"• <b>NAV:</b> ₹{nav:,.2f} (<b>{total_gain_pct:+.2f}%</b>)")
    lines.append(f"• <b>Cash:</b> ₹{cash:,.2f} ({cash_pct:.1f}%)")
    lines.append(f"• <b>Invested:</b> ₹{invested:,.2f} ({100.0 - cash_pct:.1f}%)")
    lines.append(f"• <b>Open Holdings:</b> {len(open_positions)}")
    lines.append("")

    # 2. New Buys
    lines.append("🛒 <b>NEW BUYS EXECUTED</b>")
    if not new_buys:
        lines.append("<i>None executed this scan.</i>")
    else:
        for b in new_buys:
            t = html.escape(str(b.get("ticker", "")))
            sh = b.get("shares", 0)
            pr = b.get("price", 0.0)
            r = html.escape(str(b.get("reason", "Stage 2 Breakout + Fundamentals Passed")))
            lines.append(f"• <b>{t}</b>: {sh} shs @ ₹{pr:,.2f}")
            lines.append(f"  <i>↳ {r}</i>")
    lines.append("")

    # 3. Exits
    lines.append("🛑 <b>EXITS EXECUTED (Trailing Stop Hit)</b>")
    if not exits:
        lines.append("<i>None. All open positions holding above 15% sub-MA30 stop.</i>")
    else:
        for ex in exits:
            t = html.escape(str(ex.get("ticker", "")))
            sh = ex.get("shares", 0)
            pr = ex.get("price", 0.0)
            pnl = ex.get("pnl", 0.0)
            ret = ex.get("ret_pct", 0.0)
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"• {pnl_icon} <b>{t}</b>: Sold {sh} shs @ ₹{pr:,.2f} | PnL: ₹{pnl:+,.2f} ({ret:+.1f}%)")
    lines.append("")

    # 4. Pyramids
    if pyramids:
        lines.append("⚡ <b>PYRAMID ADDITIONS (+10%)</b>")
        for py in pyramids:
            t = html.escape(str(py.get("ticker", "")))
            sh = py.get("shares", 0)
            pr = py.get("price", 0.0)
            lines.append(f"• <b>{t}</b>: Added +{sh} shs @ ₹{pr:,.2f} (+20% gain trigger)")
        lines.append("")

    # 5. Current Holdings
    lines.append("📈 <b>CURRENT HOLDINGS</b>")
    if not open_positions:
        lines.append("<i>100% Cash. No open positions.</i>")
    else:
        for p in open_positions:
            t = html.escape(str(p.get("ticker", "")))
            sh = p.get("total_shares", 0)
            cur = p.get("current_price", 0.0)
            pnl = p.get("unrealized_pnl", 0.0)
            pnl_pct = p.get("unrealized_pnl_pct", 0.0)
            stop = p.get("current_stop_price", 0.0)
            pyr_badge = " [Pyr]" if p.get("is_pyramided") else ""
            status_badge = " ⚠️ [EXIT_PENDING: Circuit Locked]" if p.get("status") == "EXIT_PENDING" else ""
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"• <b>{t}</b>{pyr_badge}{status_badge}: {sh} shs @ ₹{cur:,.2f} | "
                f"{pnl_icon} PnL: ₹{pnl:+,.0f} (<b>{pnl_pct:+.1f}%</b>) | Stop: ₹{stop:,.2f}"
            )

    return "\n".join(lines)


def send_weekly_scan_report(
    portfolio: Dict,
    week_date: str,
    nifty_close: float,
    nifty_ma30: float,
    regime_bullish: bool,
    new_buys: List[Dict],
    exits: List[Dict],
    pyramids: List[Dict],
    open_positions: List[Dict],
    starting_capital: float = 100_000.0,
) -> bool:
    """Formats and dispatches the weekly Telegram scan report."""
    msg = build_weekly_alert_payload(
        portfolio=portfolio,
        week_date=week_date,
        nifty_close=nifty_close,
        nifty_ma30=nifty_ma30,
        regime_bullish=regime_bullish,
        new_buys=new_buys,
        exits=exits,
        pyramids=pyramids,
        open_positions=open_positions,
        starting_capital=starting_capital,
    )
    return send_telegram_message(msg, parse_mode="HTML")


if __name__ == "__main__":
    print("Testing Telegram payload generation:")
    mock_portfolio = {"cash_balance": 82465.0, "total_equity": 99974.0}
    mock_open = [
        {"ticker": "BEML.NS", "total_shares": 4, "current_price": 2098.2, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0, "current_stop_price": 1592.6, "is_pyramided": 0},
        {"ticker": "AUROPHARMA.NS", "total_shares": 5, "current_price": 1823.2, "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0, "current_stop_price": 1348.0, "is_pyramided": 0},
    ]
    sample_text = build_weekly_alert_payload(
        portfolio=mock_portfolio,
        week_date="2026-11-20",
        nifty_close=23855.15,
        nifty_ma30=22920.55,
        regime_bullish=True,
        new_buys=[{"ticker": "DIVISLAB.NS", "shares": 1, "price": 11442.0, "reason": "Stage 2 Breakout + ROCE 22%"}],
        exits=[],
        pyramids=[],
        open_positions=mock_open,
    )
    print("\n--- SAMPLE TELEGRAM ALERT MESSAGE ---\n")
    print(sample_text)
    print("\n-------------------------------------")
    if is_telegram_configured():
        print("Telegram configured! Sending test message...")
        send_telegram_message("🔔 <b>V3 Multibagger Bot Connection Test: OK</b>")
    else:
        print("[Notice] Telegram not configured yet. Put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
