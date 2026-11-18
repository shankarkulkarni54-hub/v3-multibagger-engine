"""
V3 Multibagger Engine - Configuration & Parameters
Quant strategy focused on structural 300%+ winners in Indian Equities (NSE).
"""

from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_CACHE_DIR = BASE_DIR / "data_cache"
DB_PATH = BASE_DIR / "v3_multibagger_ledger.db"
NIFTY500_SYMBOLS_FILE = BASE_DIR / "nifty500_symbols.txt"

# Capital Configuration
STARTING_CAPITAL = 100_000.0  # ₹1,00,000 INR
INITIAL_ALLOCATION_PCT = 0.10  # 10% (₹10,000 initial allocation)
PYRAMID_ALLOCATION_PCT = 0.10  # 10% (₹10,000 pyramid allocation)
MAX_TICKER_ALLOCATION_PCT = 0.20  # 20% max allocation per ticker
PYRAMID_TRIGGER_GAIN_PCT = 0.20  # Trigger pyramid when stock is +20% above base buy price

# Liquidity & Penny Stock Filters
MIN_STOCK_PRICE = 50.0  # Filter out stocks below ₹50
MIN_10W_AVG_VOLUME = 500_000  # 10-week average volume must exceed 500,000 shares

# Setup Parameters (Stage 2 Breakout)
MA_PERIOD_WEEKS = 30  # 30-week Moving Average
MA_TREND_LOOKBACK_WEEKS = 4  # 30-week MA must be higher than 4 weeks ago
HIGH_52W_LOOKBACK_WEEKS = 52  # 52-week High breakout
VOL_MA_LOOKBACK_WEEKS = 10  # 10-week average volume
BREAKOUT_VOL_MULT = 1.5  # Breakout week volume > 1.5x 10-week average volume

# Fundamental Screen Parameters (Playwright / Screener.in)
MIN_ROCE_PCT = 15.0  # ROCE > 15%
MAX_DEBT_TO_EQUITY = 1.0  # Debt / Equity < 1.0
MAX_PLEDGED_PCT = 5.0  # Pledged promoter holding < 5%

# Exit Parameters (Wide Trailing Stop)
EXIT_MA_THRESHOLD_PCT = 0.15  # Sell ONLY if weekly close drops 15% below 30-week MA (Close < 0.85 * MA30)

# Market Regime Filter
REGIME_INDEX_TICKER = "^CRSLDX"  # Nifty 500 Index on Yahoo Finance
FALLBACK_REGIME_TICKER = "^NSEI"  # Fallback to Nifty 50 if ^CRSLDX is unavailable
REGIME_MA_PERIOD_WEEKS = 30  # Market index must be above its 30-week MA for new entries

# Execution / Trading Friction
TRANSACTION_COST_PCT = 0.0015  # 0.15% per trade (STT, brokerage, exchange charges, stamp duty)

# yfinance & Network Settings
YFINANCE_BATCH_SIZE = 30  # Batch download size for rate-limiting
YFINANCE_RATE_LIMIT_DELAY = 0.1  # Seconds delay between batches
CACHE_MAX_AGE_DAYS = 1  # Refresh cache if older than 1 day for live scans
