"""
V3 Multibagger Engine - Data Loader Module
Handles downloading daily data from yfinance, resampling to weekly bars (W-FRI),
caching to Parquet files, robust rate-limiting, and error handling for Indian equities (.NS).
"""

import io
import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import requests
import pandas as pd
import yfinance as yf

from config import (
    DATA_CACHE_DIR,
    NIFTY500_SYMBOLS_FILE,
    REGIME_INDEX_TICKER,
    FALLBACK_REGIME_TICKER,
    YFINANCE_BATCH_SIZE,
    YFINANCE_RATE_LIMIT_DELAY,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("V3DataLoader")


def ensure_cache_dir() -> Path:
    """Ensures that the cache directory exists."""
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_CACHE_DIR


def fetch_nifty500_tickers() -> List[str]:
    """
    Retrieves the list of Nifty 500 constituents.
    First attempts live fetch from NSE official archives.
    Falls back to local file if network fails.
    Appends '.NS' suffix for yfinance compatibility.
    """
    tickers = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"

    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text))
            if "Symbol" in df.columns:
                symbols = df["Symbol"].dropna().unique().tolist()
                tickers = [f"{s.strip().upper()}.NS" for s in symbols if isinstance(s, str) and s.strip()]
                logger.info(f"Successfully fetched {len(tickers)} Nifty 500 constituents from NSE.")
                # Save to local file for offline fallback
                with open(NIFTY500_SYMBOLS_FILE, "w") as f:
                    for t in tickers:
                        f.write(f"{t}\n")
                return tickers
    except Exception as e:
        logger.warning(f"Live fetch of Nifty 500 list from NSE failed ({e}). Attempting local fallback.")

    # Fallback to local file if available
    if NIFTY500_SYMBOLS_FILE.exists():
        with open(NIFTY500_SYMBOLS_FILE, "r") as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
        logger.info(f"Loaded {len(tickers)} tickers from local fallback file.")
        return tickers

    # Hardcoded core universe if all else fails
    logger.warning("No constituent source found. Using top 50 core Indian multibagger universe.")
    fallback = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
        "INFY.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS", "TRENT.NS", "BEL.NS",
        "HAL.NS", "DIXON.NS", "POLYCAB.NS", "VBL.NS", "TITAN.NS", "SUNPHARMA.NS",
        "ADANIENT.NS", "TATAMOTORS.NS", "SIEMENS.NS", "CHOLAFIN.NS", "EICHERMOT.NS",
        "PIDILITIND.NS", "HINDALCO.NS", "ABB.NS", "KOTAKBANK.NS", "MARUTI.NS",
    ]
    return fallback


def resample_daily_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resamples daily OHLCV dataframe into weekly Friday bars (W-FRI).
    Handles edge cases like Thursday holiday closures gracefully.
    """
    if df.empty:
        return pd.DataFrame()

    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Convert to tz-naive for consistent operations
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Verify required columns exist
    req_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in req_cols:
        if col not in df.columns:
            return pd.DataFrame()

    weekly = df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])

    # Filter out empty volume or invalid close weeks
    weekly = weekly[(weekly["Close"] > 0) & (weekly["Volume"] >= 0)]
    return weekly


def fetch_single_ticker_daily(ticker: str, period: str = "10y", max_retries: int = 3) -> pd.DataFrame:
    """
    Downloads daily data for a single ticker with exponential backoff retry.
    """
    for attempt in range(max_retries):
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=period, auto_adjust=True)
            if df is not None and not df.empty and "Close" in df.columns:
                return df
        except Exception as e:
            wait_time = (2 ** attempt) * 0.5
            logger.debug(f"Attempt {attempt+1} failed for {ticker}: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
    return pd.DataFrame()


def get_cache_path(ticker: str) -> Path:
    """Returns the parquet cache file path for a given ticker."""
    ensure_cache_dir()
    clean_name = ticker.replace("^", "INDEX_").replace(".NS", "_NS")
    return DATA_CACHE_DIR / f"{clean_name}.parquet"


def save_to_cache(ticker: str, df: pd.DataFrame):
    """Saves weekly dataframe to Parquet cache."""
    if df is not None and not df.empty:
        path = get_cache_path(ticker)
        try:
            df.to_parquet(path)
        except Exception as e:
            logger.debug(f"Failed to save parquet cache for {ticker}: {e}")


def load_from_cache(ticker: str, max_age_days: Optional[int] = None) -> Optional[pd.DataFrame]:
    """Loads weekly dataframe from Parquet cache if it exists and is fresh."""
    path = get_cache_path(ticker)
    if not path.exists():
        return None

    if max_age_days is not None:
        mtime = path.stat().st_mtime
        age_days = (time.time() - mtime) / 86400.0
        if age_days > max_age_days:
            return None

    try:
        df = pd.read_parquet(path)
        if not df.empty:
            return df
    except Exception as e:
        logger.debug(f"Cache read error for {ticker}: {e}")
    return None


def fetch_ticker_weekly(
    ticker: str,
    period: str = "10y",
    force_refresh: bool = False,
    max_cache_age_days: Optional[int] = None,
) -> Optional[pd.DataFrame]:
    """
    Retrieves weekly data for a single ticker, utilizing Parquet cache when available.
    """
    min_required_bars = 400 if ("10y" in period or "12y" in period) else 35
    if not force_refresh:
        cached = load_from_cache(ticker, max_age_days=max_cache_age_days)
        if cached is not None and len(cached) >= min_required_bars:
            return cached

    # Fetch daily and resample to weekly
    daily = fetch_single_ticker_daily(ticker, period=period)
    if daily.empty:
        return None

    weekly = resample_daily_to_weekly(daily)
    if len(weekly) >= 30:
        save_to_cache(ticker, weekly)
        return weekly

    return None


def fetch_regime_index_weekly(
    period: str = "10y",
    force_refresh: bool = False,
) -> Tuple[pd.DataFrame, str]:
    """
    Fetches the Nifty 500 weekly data for market regime filtering.
    Falls back to Nifty 50 if Nifty 500 is unavailable.
    """
    min_required_bars = 400 if ("10y" in period or "12y" in period) else 35
    # Try primary: ^CRSLDX (Nifty 500)
    for ticker in [REGIME_INDEX_TICKER, FALLBACK_REGIME_TICKER]:
        logger.info(f"Fetching market regime index: {ticker}")
        df = fetch_ticker_weekly(ticker, period=period, force_refresh=force_refresh)
        if df is not None and len(df) >= min_required_bars:
            logger.info(f"Successfully loaded regime index {ticker} ({len(df)} weekly bars).")
            return df, ticker

    raise RuntimeError("Critical Error: Unable to fetch market regime index data for ^CRSLDX or ^NSEI.")


def batch_fetch_weekly_universe(
    tickers: List[str],
    period: str = "10y",
    force_refresh: bool = False,
    batch_size: int = YFINANCE_BATCH_SIZE,
    rate_limit_delay: float = YFINANCE_RATE_LIMIT_DELAY,
) -> Dict[str, pd.DataFrame]:
    """
    Downloads and resamples weekly data for a list of tickers in rate-limited batches.
    Utilizes local cache to prevent redundant downloads.
    """
    results: Dict[str, pd.DataFrame] = {}
    missing_tickers: List[str] = []

    # Required minimum bars based on requested period
    min_required_bars = 400 if ("10y" in period or "12y" in period) else 35

    # First check cache for all tickers
    for t in tickers:
        if not force_refresh:
            cached = load_from_cache(t)
            if cached is not None and len(cached) >= min_required_bars:
                results[t] = cached
                continue
        missing_tickers.append(t)

    logger.info(
        f"Universe size: {len(tickers)} | Cached: {len(results)} | To Download: {len(missing_tickers)}"
    )

    if not missing_tickers:
        return results

    # Download missing tickers in batches
    for i in range(0, len(missing_tickers), batch_size):
        chunk = missing_tickers[i : i + batch_size]
        logger.info(f"Downloading batch {i//batch_size + 1}/{(len(missing_tickers) + batch_size - 1)//batch_size} ({len(chunk)} tickers)...")

        try:
            # Batch download daily
            batch_df = yf.download(
                chunk,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
            )

            for t in chunk:
                try:
                    if len(chunk) == 1:
                        # Single ticker output format
                        stock_df = batch_df
                    else:
                        if t in batch_df.columns.levels[0]:
                            stock_df = batch_df[t].dropna(subset=["Close"])
                        else:
                            stock_df = pd.DataFrame()

                    if not stock_df.empty and len(stock_df) > 50:
                        weekly_df = resample_daily_to_weekly(stock_df)
                        if len(weekly_df) >= 35:
                            results[t] = weekly_df
                            save_to_cache(t, weekly_df)
                except Exception as ex:
                    logger.debug(f"Error parsing weekly data for {t}: {ex}")

        except Exception as e:
            logger.warning(f"Batch download failed for chunk starting at {i}: {e}. Retrying individually...")
            # Fallback to individual fetch
            for t in chunk:
                df = fetch_ticker_weekly(t, period=period, force_refresh=True)
                if df is not None and len(df) >= 35:
                    results[t] = df
                time.sleep(rate_limit_delay)

        time.sleep(rate_limit_delay)

    logger.info(f"Universe preparation complete. Successfully processed {len(results)}/{len(tickers)} valid tickers.")
    return results
