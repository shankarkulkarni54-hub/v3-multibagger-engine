"""
V3 Multibagger Engine - Quantitative Strategy Module
Defines Stage 2 Breakout logic, Market Regime filter, Trailing Stop exit,
and Pyramiding conditions strictly on weekly timeframe bars.
"""

from typing import Dict, Any, Tuple
import pandas as pd
import numpy as np

from config import (
    MIN_STOCK_PRICE,
    MIN_10W_AVG_VOLUME,
    MA_PERIOD_WEEKS,
    MA_TREND_LOOKBACK_WEEKS,
    HIGH_52W_LOOKBACK_WEEKS,
    VOL_MA_LOOKBACK_WEEKS,
    BREAKOUT_VOL_MULT,
    EXIT_MA_THRESHOLD_PCT,
    EXIT_MA_BULL_THRESHOLD_PCT,
    EXIT_MA_BEAR_THRESHOLD_PCT,
    PYRAMID_TRIGGER_GAIN_PCT,
    MAX_STARTER_POSITIONS,
    PYRAMID_CASH_RESERVE_PCT,
)


def compute_weekly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all weekly technical indicators required for V3 Multibagger strategy.
    
    Inputs:
        df: DataFrame with DatetimeIndex and columns [Open, High, Low, Close, Volume]
    Returns:
        DataFrame augmented with:
            - MA30: 30-week SMA of Close
            - MA30_4w_ago: 30-week SMA from 4 weeks prior
            - MA30_trend_up: Boolean, MA30 > MA30_4w_ago
            - Vol_MA10: 10-week SMA of Volume
            - High_52w_prev: Highest High over the prior 52 weeks (excluding current week)
            - Close_52w_prev: Highest Close over the prior 52 weeks (excluding current week)
            - Is_Liquidity_OK: Close > 50 and Vol_MA10 > 500k
            - Breakout_Vol_OK: Volume > 1.5x Vol_MA10
            - Is_52w_Breakout: Current High >= High_52w_prev or Close >= Close_52w_prev
            - Stage2_Signal: All setup conditions met for entry
            - Exit_Signal: Close < 0.85 * MA30
    """
    if df is None or len(df) < (HIGH_52W_LOOKBACK_WEEKS + 4):
        return pd.DataFrame()

    res = df.copy()

    # 1. 30-week Moving Average
    res["MA30"] = res["Close"].rolling(window=MA_PERIOD_WEEKS, min_periods=MA_PERIOD_WEEKS).mean()

    # 2. 30-week MA Trend (trending up vs 4 weeks ago)
    res["MA30_4w_ago"] = res["MA30"].shift(MA_TREND_LOOKBACK_WEEKS)
    res["MA30_trend_up"] = res["MA30"] > res["MA30_4w_ago"]

    # 3. 10-week Average Volume
    res["Vol_MA10"] = res["Volume"].rolling(window=VOL_MA_LOOKBACK_WEEKS, min_periods=VOL_MA_LOOKBACK_WEEKS).mean()

    # 4. 52-week High of previous 52 weeks (shift 1 to avoid lookahead bias)
    res["High_52w_prev"] = res["High"].shift(1).rolling(
        window=HIGH_52W_LOOKBACK_WEEKS, min_periods=HIGH_52W_LOOKBACK_WEEKS
    ).max()
    res["Close_52w_prev"] = res["Close"].shift(1).rolling(
        window=HIGH_52W_LOOKBACK_WEEKS, min_periods=HIGH_52W_LOOKBACK_WEEKS
    ).max()

    # 5. Liquidity & Penny Stock Filter (Close > ₹50 and 10w avg vol > 500,000)
    res["Is_Liquidity_OK"] = (res["Close"] > MIN_STOCK_PRICE) & (res["Vol_MA10"] > MIN_10W_AVG_VOLUME)

    # 6. Breakout Volume Confirmation (Volume > 1.5x 10-week average volume)
    res["Breakout_Vol_OK"] = res["Volume"] > (BREAKOUT_VOL_MULT * res["Vol_MA10"])

    # 7. 52-Week High Breakout
    # True if weekly high breaks above the previous 52-week high, and close finishes strongly
    res["Is_52w_Breakout"] = (res["High"] >= res["High_52w_prev"]) | (res["Close"] >= res["Close_52w_prev"])

    # 8. Complete Stage 2 Breakout Entry Setup:
    # - Price > 30-week MA
    # - 30-week MA trending UP (MA30 > MA30 from 4 weeks ago)
    # - Price makes a 52-week high
    # - Breakout volume confirmation (Vol > 1.5x 10w avg)
    # - Liquidity filter satisfied
    res["Stage2_Signal"] = (
        (res["Close"] > res["MA30"]) &
        res["MA30_trend_up"] &
        res["Is_52w_Breakout"] &
        res["Breakout_Vol_OK"] &
        res["Is_Liquidity_OK"]
    )

    # 9. Dynamic Exit Conditions (Bull vs Bear Market Stop-Loss):
    # - Bull Regime: Trailing stop at 15% below 30-week MA (Close < 0.85 * MA30)
    # - Bear Regime: Dynamically tightened trailing stop at 8% below 30-week MA (Close < 0.92 * MA30)
    res["Exit_Stop_Price_Bull"] = res["MA30"] * (1.0 - EXIT_MA_BULL_THRESHOLD_PCT)
    res["Exit_Stop_Price_Bear"] = res["MA30"] * (1.0 - EXIT_MA_BEAR_THRESHOLD_PCT)
    res["Exit_Stop_Price"] = res["Exit_Stop_Price_Bull"]
    res["Exit_Signal"] = res["Close"] < res["Exit_Stop_Price"]

    return res


def compute_market_regime(nifty_weekly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes market regime for Nifty 500 index.
    The system is ONLY allowed to take new entries if Nifty 500 is trading above its 30-week MA.
    """
    regime_df = nifty_weekly_df.copy()
    regime_df["Nifty_MA30"] = regime_df["Close"].rolling(window=MA_PERIOD_WEEKS, min_periods=MA_PERIOD_WEEKS).mean()
    regime_df["Regime_Bullish"] = regime_df["Close"] > regime_df["Nifty_MA30"]
    return regime_df


def is_market_regime_bullish(regime_df: pd.DataFrame, as_of_date: pd.Timestamp) -> bool:
    """
    Checks whether the market regime was bullish on or immediately before as_of_date.
    """
    sub = regime_df.loc[:as_of_date]
    if sub.empty:
        return False
    latest_bar = sub.iloc[-1]
    return bool(latest_bar.get("Regime_Bullish", False))


def check_exit_condition(
    current_close: float,
    ma30: float,
    is_bearish_regime: bool = False,
) -> Tuple[bool, float]:
    """
    Evaluates whether an open position has triggered the sub-30-week MA trailing stop.
    - Bull Market Regime: 15% below 30-week MA (Close < 0.85 * MA30)
    - Bear Market Regime: Dynamically tightened to 8% below 30-week MA (Close < 0.92 * MA30)
    Returns: (exit_triggered: bool, stop_price: float)
    """
    threshold = EXIT_MA_BEAR_THRESHOLD_PCT if is_bearish_regime else EXIT_MA_BULL_THRESHOLD_PCT
    stop_price = ma30 * (1.0 - threshold)
    should_exit = current_close < stop_price
    return should_exit, stop_price


def check_pyramid_condition(current_close: float, initial_buy_price: float, is_pyramided: bool) -> bool:
    """
    Evaluates whether an open position is eligible for pyramiding:
    Triggered when current price advances >= 20% from initial buy point and hasn't pyramided yet.
    """
    if is_pyramided or initial_buy_price <= 0:
        return False
    return current_close >= (initial_buy_price * (1.0 + PYRAMID_TRIGGER_GAIN_PCT))
