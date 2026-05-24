"""Positional technical indicators — D1 and W1 only.

All indicators designed for swing/positional timeframes.
No pandas-ta dependency; all hand-rolled for Python 3.9 compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ---------------- core indicators ----------------

def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 21) -> pd.Series:
    """Wilder RSI — 21-period default for positional analysis."""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / length, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / length, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    prev_c = c.shift(1)
    tr = pd.concat(
        [h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _last(series: pd.Series) -> float | None:
    s = series.dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


# ---------------- divergence detection ----------------

def detect_rsi_divergence(close: pd.Series, rsi_series: pd.Series, window: int = 20) -> str:
    """
    Compare last two price peaks/troughs vs RSI peaks/troughs.
    Returns 'bullish', 'bearish', or 'none'.
    """
    if len(close) < window or len(rsi_series) < window:
        return "none"
    c = close.dropna().tail(window).values
    r = rsi_series.dropna().tail(window).values
    if len(c) < 6 or len(r) < 6:
        return "none"

    price_highs = [i for i in range(1, len(c) - 1) if c[i] > c[i-1] and c[i] > c[i+1]]
    price_lows  = [i for i in range(1, len(c) - 1) if c[i] < c[i-1] and c[i] < c[i+1]]

    if len(price_highs) >= 2:
        ph1, ph2 = price_highs[-2], price_highs[-1]
        if c[ph2] > c[ph1] and r[ph2] < r[ph1]:
            return "bearish"

    if len(price_lows) >= 2:
        pl1, pl2 = price_lows[-2], price_lows[-1]
        if c[pl2] < c[pl1] and r[pl2] > r[pl1]:
            return "bullish"

    return "none"


# ---------------- main signal computation ----------------

@dataclass
class PositionalSignals:
    ticker: str
    price: float | None = None
    currency: str = "USD"

    sma_50: float | None = None
    sma_200: float | None = None
    ma_stack_bullish: bool = False
    ma_stack_bearish: bool = False

    sma_30w: float | None = None
    weekly_trend: str = "flat"

    rsi_21: float | None = None
    rsi_divergence: str = "none"

    volume_20d_avg: float | None = None
    volume_latest: float | None = None
    volume_ratio: float | None = None
    volume_spike: bool = False

    high_52w: float | None = None
    low_52w: float | None = None
    near_200sma: bool = False
    near_52w_high: bool = False
    near_52w_low: bool = False
    breakout_52w_high: bool = False

    atr_14: float | None = None
    stop_distance_pct: float | None = None

    return_63d: float | None = None
    spy_return_63d: float | None = None
    outperforming_spy: bool = False

    consecutive_direction: str | None = None
    last_date: str = ""
    errors: list = field(default_factory=list)


def compute_positional_signals(
    df_daily: pd.DataFrame,
    df_weekly: pd.DataFrame,
    spy_daily: pd.DataFrame,
    ticker: str = "",
) -> PositionalSignals:
    sig = PositionalSignals(ticker=ticker)

    if df_daily is None or df_daily.empty:
        sig.errors.append("no_daily_data")
        return sig

    close = df_daily["close"].astype(float)
    sig.price = _last(close)
    if sig.price is None:
        sig.errors.append("no_price")
        return sig

    sig.last_date = str(df_daily.index[-1].date()) if not df_daily.empty else ""
    if ticker.endswith(".TO"):
        sig.currency = "CAD"

    if len(close) >= 50:
        sig.high_52w = float(close.tail(252).max())
        sig.low_52w = float(close.tail(252).min())
        sig.near_52w_high = sig.price >= sig.high_52w * 0.97
        sig.near_52w_low = sig.price <= sig.low_52w * 1.03
        sig.sma_50 = _last(sma(close, 50))

    if len(close) >= 200:
        sig.sma_200 = _last(sma(close, 200))

    if sig.sma_50 and sig.sma_200:
        sig.ma_stack_bullish = sig.price > sig.sma_50 > sig.sma_200
        sig.ma_stack_bearish = sig.price < sig.sma_50 < sig.sma_200

    if sig.sma_200:
        sig.near_200sma = abs(sig.price - sig.sma_200) / sig.sma_200 < 0.02

    if df_weekly is not None and not df_weekly.empty and len(df_weekly) >= 30:
        wclose = df_weekly["close"].astype(float)
        sig.sma_30w = _last(sma(wclose, 30))
        if sig.sma_30w:
            sig.weekly_trend = "up" if sig.price > sig.sma_30w else "down" if sig.price < sig.sma_30w else "flat"

    if len(close) >= 21:
        rsi_series = rsi(close, length=21)
        sig.rsi_21 = _last(rsi_series)
        sig.rsi_divergence = detect_rsi_divergence(close, rsi_series)

    if "volume" in df_daily.columns and len(df_daily) >= 20:
        vol = df_daily["volume"].astype(float)
        sig.volume_20d_avg = float(vol.tail(20).mean())
        sig.volume_latest = float(vol.iloc[-1])
        if sig.volume_20d_avg > 0:
            sig.volume_ratio = sig.volume_latest / sig.volume_20d_avg
            sig.volume_spike = sig.volume_ratio >= 1.5

    if sig.near_52w_high and sig.volume_spike and sig.high_52w:
        sig.breakout_52w_high = sig.price >= sig.high_52w * 0.99

    if len(df_daily) >= 14:
        atr_series = atr(df_daily, length=14)
        sig.atr_14 = _last(atr_series)
        if sig.atr_14 and sig.price:
            sig.stop_distance_pct = round(2 * sig.atr_14 / sig.price * 100, 2)

    if len(close) >= 64:
        ret_63 = (float(close.iloc[-1]) - float(close.iloc[-64])) / float(close.iloc[-64]) * 100
        sig.return_63d = round(ret_63, 2)

    if spy_daily is not None and not spy_daily.empty and len(spy_daily) >= 64:
        spy_close = spy_daily["close"].astype(float)
        spy_ret = (float(spy_close.iloc[-1]) - float(spy_close.iloc[-64])) / float(spy_close.iloc[-64]) * 100
        sig.spy_return_63d = round(spy_ret, 2)
        if sig.return_63d is not None:
            sig.outperforming_spy = sig.return_63d > sig.spy_return_63d

    if len(close) >= 2:
        delta = float(close.iloc[-1]) - float(close.iloc[-2])
        sig.consecutive_direction = "up" if delta > 0 else "down" if delta < 0 else "flat"

    return sig
