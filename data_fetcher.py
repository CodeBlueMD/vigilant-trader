"""Market data adapters for positional analysis.

All analysis uses D1 (daily) and W1 (weekly) timeframes only.
yfinance is the sole data source — always free.
"""
from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
import yfinance as yf

from config import log


def fetch_daily(ticker: str, period: str = "1y") -> pd.DataFrame:
    """1-year daily OHLCV — primary data source for all positional signals."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns=str.lower)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        log.warning("Daily fetch failed for %s: %s", ticker, e)
        return pd.DataFrame()


def fetch_weekly(ticker: str, period: str = "2y") -> pd.DataFrame:
    """2-year weekly OHLCV — used for W1 trend direction."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1wk", auto_adjust=True)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns=str.lower)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        log.warning("Weekly fetch failed for %s: %s", ticker, e)
        return pd.DataFrame()


def fetch_latest_price(ticker: str) -> float | None:
    """Last close price."""
    df = fetch_daily(ticker, period="5d")
    if df.empty or "close" not in df.columns:
        return None
    return float(df["close"].iloc[-1])


def fetch_earnings_date(ticker: str) -> datetime.date | None:
    """Next earnings date from yfinance calendar. Returns None if unavailable."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            future = [
                d for d in dates
                if hasattr(d, "date") and d.date() >= datetime.date.today()
            ]
            return future[0].date() if future else None
        if hasattr(cal, "loc"):
            try:
                dates = cal.loc["Earnings Date"]
                if hasattr(dates, "__iter__"):
                    future = [
                        d for d in dates
                        if hasattr(d, "date") and d.date() >= datetime.date.today()
                    ]
                    return future[0].date() if future else None
            except Exception:
                pass
        return None
    except Exception as e:
        log.debug("Earnings date fetch failed for %s: %s", ticker, e)
        return None


def trading_days_until(target: datetime.date) -> int:
    """Approximate trading days between today and target date."""
    today = datetime.date.today()
    if target <= today:
        return 0
    delta = (target - today).days
    return max(0, int(delta * 5 / 7))
