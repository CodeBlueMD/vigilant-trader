"""Holdings drawdown protection — daily check for significant drops.

Trigger conditions (all three must be met):
  1. Drop from previous close exceeds multiplier × ATR(50)
  2. Volume ≥ 1.5× 20-day average (confirms institutional selling, not drift)
  3. Price is at or below SMA50 (breach of key support, not just a pullback)

Per-holding multipliers (from config.HOLDING_ATR_MULTIPLIERS):
  IBIT: 3.0×   QQQM: 2.0×   GLD: 1.5×
"""
from __future__ import annotations

from dataclasses import dataclass

from config import HOLDING_ATR_MULTIPLIERS, HOLDING_TICKERS, log
from data_fetcher import fetch_daily
from technical_analysis import compute_positional_signals

_VOLUME_CONFIRM_RATIO = 1.5


@dataclass
class DrawdownAlert:
    ticker: str
    price: float
    prev_close: float
    drop_pct: float
    threshold_pct: float
    multiplier: float
    sma_50: float | None
    sma_200: float | None
    rsi_21: float | None
    volume_ratio: float | None
    below_sma50: bool
    oversold: bool


def check_holdings_drawdown(tickers: list[str] | None = None) -> list[DrawdownAlert]:
    """Check each holding for a significant drawdown. Returns alerts to send."""
    targets = tickers if tickers is not None else HOLDING_TICKERS
    alerts = []

    for ticker in targets:
        try:
            df = fetch_daily(ticker, period="1y")
            if df is None or len(df) < 51:
                log.warning("Drawdown check: insufficient data for %s", ticker)
                continue

            sig = compute_positional_signals(df, None, None, ticker=ticker)

            if sig.price is None or sig.atr_50 is None:
                continue

            close = df["close"].astype(float)
            if len(close) < 2:
                continue

            prev_close = float(close.iloc[-2])
            price = sig.price
            drop_pct = (prev_close - price) / prev_close * 100

            if drop_pct <= 0:
                continue  # not a drop

            multiplier = HOLDING_ATR_MULTIPLIERS.get(ticker, 2.0)
            threshold_pct = multiplier * sig.atr_50 / price * 100

            if drop_pct < threshold_pct:
                log.info("Drawdown %s: %.1f%% drop below %.1f%% threshold — skipped", ticker, drop_pct, threshold_pct)
                continue

            # Volume confirmation — institutional selling leaves a fingerprint
            if sig.volume_ratio is not None and sig.volume_ratio < _VOLUME_CONFIRM_RATIO:
                log.info("Drawdown %s: %.1f%% drop but volume only %.1fx — skipped", ticker, drop_pct, sig.volume_ratio)
                continue

            # SMA50 filter — a drop while price is still above a rising SMA50 is a pullback
            below_sma50 = sig.sma_50 is not None and price <= sig.sma_50
            if not below_sma50 and sig.sma_50 is not None:
                log.info("Drawdown %s: %.1f%% drop but price still above SMA50 ($%.2f) — skipped", ticker, drop_pct, sig.sma_50)
                continue

            log.info("Drawdown alert firing: %s dropped %.1f%% (threshold %.1f%%)", ticker, drop_pct, threshold_pct)
            alerts.append(DrawdownAlert(
                ticker=ticker,
                price=price,
                prev_close=prev_close,
                drop_pct=round(drop_pct, 2),
                threshold_pct=round(threshold_pct, 2),
                multiplier=multiplier,
                sma_50=sig.sma_50,
                sma_200=sig.sma_200,
                rsi_21=sig.rsi_21,
                volume_ratio=sig.volume_ratio,
                below_sma50=below_sma50,
                oversold=sig.rsi_21 is not None and sig.rsi_21 < 30,
            ))

        except Exception as e:
            log.exception("Drawdown check failed for %s: %s", ticker, e)

    return alerts
