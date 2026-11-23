"""
Standalone SQLite to Supabase Cloud Sync for V3 Multibagger Engine.
Does not modify v3_weekly_engine.py or core trading logic.
Executes at the end of .github/workflows/v3_cloud_engine.yml.
"""
import sqlite3
import os
import requests
from datetime import datetime

# Helper to load .env locally if not present in env
def load_env():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

load_env()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v3_multibagger_ledger.db")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[SYNC] SUPABASE_URL or SUPABASE_KEY missing. Skipping cloud sync.")
    exit(0)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def sync():
    if not os.path.exists(DB_PATH):
        print(f"[SYNC] {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Sync Portfolio State
    p_row = cur.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    if p_row:
        peak = float(p_row["peak_equity"])
        total = float(p_row["total_equity"])
        dd = round(((total - peak) / peak) * 100, 2) if peak > 0 else 0.0
        p_payload = [{
            "id": 1,
            "cash_balance": float(p_row["cash_balance"]),
            "invested_value": float(p_row["invested_value"]),
            "total_equity": total,
            "peak_equity": peak,
            "drawdown_pct": dd,
            "last_updated": datetime.utcnow().isoformat()
        }]
        r1 = requests.post(f"{SUPABASE_URL}/rest/v1/v3_portfolio", headers=headers, json=p_payload)
        print(f"[SYNC] V3 portfolio push response: {r1.status_code}")

    # 2. Sync Open & Active Positions
    pos_rows = [dict(r) for r in cur.execute("SELECT * FROM positions").fetchall()]
    pos_payload = []
    for r in pos_rows:
        curr = float(r["current_price"])
        stop = float(r.get("current_stop_price") or 0.0)
        dist = round(((curr - stop) / curr) * 100, 2) if curr > 0 and stop > 0 else 0.0

        pos_payload.append({
            "ticker": r["ticker"],
            "initial_date": r["initial_date"],
            "initial_price": float(r["initial_price"]),
            "initial_shares": int(r["initial_shares"]),
            "initial_invested": float(r["initial_invested"]),
            "is_pyramided": bool(r["is_pyramided"]),
            "pyramid_date": r.get("pyramid_date") or None,
            "pyramid_price": float(r.get("pyramid_price") or 0.0),
            "pyramid_shares": int(r.get("pyramid_shares") or 0),
            "pyramid_invested": float(r.get("pyramid_invested") or 0.0),
            "total_shares": int(r["total_shares"]),
            "total_invested": float(r["total_invested"]),
            "avg_price": float(r["avg_price"]),
            "current_price": curr,
            "current_ma30": float(r.get("current_ma30") or 0.0),
            "current_stop_price": stop,
            "stop_loss_pct_dist": dist,
            "current_value": float(r["current_value"]),
            "unrealized_pnl": float(r["unrealized_pnl"]),
            "unrealized_pnl_pct": float(r["unrealized_pnl_pct"]),
            "highest_price": float(r["highest_price"]),
            "status": r["status"],
            "last_updated": datetime.utcnow().isoformat()
        })
    if pos_payload:
        r2 = requests.post(f"{SUPABASE_URL}/rest/v1/v3_positions", headers=headers, json=pos_payload)
        print(f"[SYNC] V3 positions push response ({len(pos_payload)} records): {r2.status_code}")

    # 3. Sync Closed Trades
    trade_rows = [dict(r) for r in cur.execute("SELECT * FROM trades").fetchall()]
    trades_payload = []
    for r in trade_rows:
        trades_payload.append({
            "trade_id": int(r["trade_id"]),
            "timestamp": r["timestamp"],
            "ticker": r["ticker"],
            "action": r["action"],
            "shares": int(r["shares"]),
            "price": float(r["price"]),
            "gross_amount": float(r["gross_amount"]),
            "fees": float(r["fees"]),
            "net_amount": float(r["net_amount"]),
            "realized_pnl": float(r.get("realized_pnl") or 0.0),
            "return_pct": float(r.get("return_pct") or 0.0),
            "holding_weeks": int(r.get("holding_weeks") or 0),
            "reason": r.get("reason")
        })
    if trades_payload:
        r3 = requests.post(f"{SUPABASE_URL}/rest/v1/v3_trades", headers=headers, json=trades_payload)
        print(f"[SYNC] V3 trades push response ({len(trades_payload)} records): {r3.status_code}")

    conn.close()

if __name__ == "__main__":
    sync()
