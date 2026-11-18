# V3 Multibagger Engine 🚀
**Institutional Quantitative Trend-Following & Pyramiding System for Indian Equities (NSE)**

Designed to capture **300%+ secular multibaggers** in the Indian stock market using weekly Stage 2 breakouts, regime-filtered capital allocation, and wide trailing stops.

---

## Architecture Overview

```
d:\v3_multibagger\
├── config.py                 # Central parameters (₹1L capital, thresholds, indicators, sizing)
├── data_loader.py            # yfinance fetcher, rate-limiting, W-FRI resampling, Parquet caching
├── strategy.py               # Quantitative Stage 2 rules, Nifty 500 regime filter, pyramiding & stop logic
├── playwright_fundamentals.py # Async Playwright browser engine extracting Screener.in ratios
├── telegram_notifier.py      # Telegram Bot API notification engine
├── v3_dashboard.py           # Streamlit local interactive quantitative dashboard
├── v3_backtest.py            # 10-Year Backtest Engine with compounding and year-by-year curve
├── v3_weekly_engine.py       # Autonomous Weekly Engine & SQLite Ledger Manager
├── test_engine.py            # Unit & integration verification test suite
├── v3_multibagger_ledger.db  # SQLite paper trading database
├── .env                      # Telegram bot token and chat ID config
├── nifty500_symbols.txt      # 501 NSE Nifty 500 constituents
├── v3_backtest_equity_curve.csv # Exported backtest weekly NAV history
└── v3_backtest_trades.csv    # Exported individual trade execution logs
```

---

## Strategy Rules & Quant Logic

### 1. Timeframe & Liquidity
- **Weekly Bars (`W-FRI`)**: All technicals and executions operate strictly on the weekly timeframe to eliminate intraday/daily market noise.
- **Penny Stock & Volume Filter**: Only evaluate stocks where `Close > ₹50` and `10-Week Average Volume > 500,000 shares`.

### 2. Market Regime Filter
- **Nifty 500 (`^CRSLDX`)**: New entries are **ONLY** permitted when Nifty 500 is trading above its 30-week moving average (`Close > MA30`).
- If Nifty 500 is below its 30-week MA, market regime is **BEARISH** and new purchases are halted to preserve capital.

### 3. Stage 2 Breakout Entry Setup
A stock triggers a virtual **BUY** when all 4 conditions align on the Friday close:
1. `Price > 30-Week MA`
2. `30-Week MA Trending Up`: `MA30[current] > MA30[4 weeks ago]`
3. `52-Week High Breakout`: Current week High exceeds the highest High of the prior 52 weeks
4. `Institutional Volume Confirmation`: Weekly Volume > `1.5x 10-Week Average Volume`

### 4. Autonomous Playwright Fundamental Filter (Screener.in)
Before executing any buy order, the engine automatically launches a headless Chromium browser instance to audit institutional fundamentals from Screener.in:
- **ROCE**: Must be strictly **> 15%**
- **Debt to Equity**: Must be strictly **< 1.0**
- **Pledged Promoter Holding**: Must be strictly **< 5.0%**
Stocks that break out technically but fail any of these fundamental hurdles are automatically rejected and logged.

### 5. Pyramiding & Position Sizing
- **Initial Allocation**: 10% (₹10,000 of ₹1,00,000 virtual capital).
- **Pyramid Addition**: If the stock advances **+20%** above the initial entry price, allocate an additional 10% (₹10,000).
- **Maximum Exposure**: Capped at 20% total allocation per ticker.

### 6. Wide Trailing Stop Exit
- Designed to survive normal 10–25% bull market shakeouts while locking in massive secular runs.
- **Exit Condition**: Sell **ONLY** if the weekly close drops **15% below the 30-week MA** (`Close < 0.85 * MA30`).

---

## Quickstart & CLI Commands

### 1. Run the 10-Year Backtest
```bash
# Run on 80 top Nifty 500 constituents
python v3_backtest.py --tickers 80

# Run on 150 constituents
python v3_backtest.py --tickers 150

# Run with fixed ₹10k size instead of compounding
python v3_backtest.py --tickers 80 --fixed-size
```

### 2. Launch Local Streamlit Dashboard
```bash
streamlit run v3_dashboard.py
```

### 3. Run the Live Weekly Paper Trading Engine (Friday EOD)
```bash
# Execute Friday EOD scan, manage open positions, and execute paper buys
python v3_weekly_engine.py --scan --tickers 150

# View current portfolio dashboard, cash, open positions, unrealized PnL & stop levels
python v3_weekly_engine.py --status

# View complete historical closed and open trades ledger
python v3_weekly_engine.py --history

# Dry-run scan without modifying the SQLite database
python v3_weekly_engine.py --dry-run --tickers 150

# Reset paper trading ledger to clean ₹100,000 starting cash
python v3_weekly_engine.py --reset
```

### 4. Automated Telegram Alerts Configuration
Add your bot credentials to `.env`:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
```
Test the connection & payload:
```bash
python telegram_notifier.py
```

### 5. Run Playwright Fundamental Engine Directly
```bash
# Test extraction and audit on specific tickers
python playwright_fundamentals.py DIVISLAB SUZLON IDEA
```

### 6. Run Verification Tests
```bash
python test_engine.py
```
