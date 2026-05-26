"""Positional Research Analyst — 7-gate signal engine.

All 7 gates must pass before an alert fires.
Quant gates are deterministic Python. AI adds narrative only.
"""
from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field

from config import (
    AVAILABLE_CAPITAL_USD,
    HOLDING_TICKERS,
    PORTFOLIO_HOLDINGS,
    TICKERS,
    log,
)
from data_fetcher import (
    fetch_daily,
    fetch_earnings_date,
    fetch_weekly,
    trading_days_until,
)
from database import record_positional_signal
from technical_analysis import PositionalSignals, compute_positional_signals

# SPY is the market regime reference regardless of watchlist
_SPY_TICKER = "SPY"
_EARNINGS_BLACKOUT_DAYS = 10
_POSITION_SIZE_PCT = 0.15  # 15% of available capital per signal


@dataclass
class GateResult:
    passed: bool
    name: str
    detail: str = ""


@dataclass
class AnalysisResult:
    ticker: str
    price: float | None
    currency: str
    signal_type: str | None         # "bullish" | "bearish" | None
    confidence: str | None          # "High" | "Medium" | None
    gates: list[GateResult] = field(default_factory=list)
    confluence_factors: list[str] = field(default_factory=list)
    atr_stop: float | None = None
    suggested_position_usd: float | None = None
    is_holding: bool = False
    earnings_date: datetime.date | None = None
    not_confirmed_reason: str = ""
    signals: PositionalSignals | None = None
    entry_high: float | None = None
    entry_low: float | None = None
    volatility_tier: str = ""


def _determine_signal_direction(sig: PositionalSignals) -> str | None:
    """Decide bullish or bearish based on MA stack and weekly trend."""
    if sig.weekly_trend == "up" and sig.ma_stack_bullish:
        return "bullish"
    if sig.weekly_trend == "down" and sig.ma_stack_bearish:
        return "bearish"
    # Reversal setups: strong divergence overrides
    if sig.rsi_divergence == "bullish" and sig.near_52w_low:
        return "bullish"
    if sig.rsi_divergence == "bearish" and sig.near_52w_high:
        return "bearish"
    return None


def _count_confluence(sig: PositionalSignals, direction: str) -> list[str]:
    """Return list of confluence factors that fired (mutually exclusive within category)."""
    factors = []

    if direction == "bullish":
        if sig.near_200sma or sig.near_52w_low:
            levels = []
            if sig.near_200sma:
                levels.append("200-SMA")
            if sig.near_52w_low:
                levels.append("52w low")
            factors.append(f"Price at key level ({', '.join(levels)})")

        # Breakout supersedes standalone volume spike — both require volume_spike, avoid double-count
        if sig.breakout_52w_high:
            factors.append("52-week high breakout on volume")
        elif sig.volume_spike:
            factors.append(f"Volume spike ({sig.volume_ratio:.1f}x 20d avg)")

        if sig.rsi_divergence == "bullish":
            factors.append(f"Bullish RSI(21) divergence (RSI={sig.rsi_21:.1f})")

    elif direction == "bearish":
        if sig.near_200sma or sig.near_52w_high:
            levels = []
            if sig.near_200sma:
                levels.append("200-SMA")
            if sig.near_52w_high:
                levels.append("52w high")
            factors.append(f"Price at key resistance ({', '.join(levels)})")

        # Distribution supersedes standalone volume spike — both require volume_spike, avoid double-count
        if sig.near_52w_high and sig.volume_spike:
            factors.append("Distribution at 52-week high")
        elif sig.volume_spike:
            factors.append(f"Volume spike ({sig.volume_ratio:.1f}x 20d avg)")

        if sig.rsi_divergence == "bearish":
            factors.append(f"Bearish RSI(21) divergence (RSI={sig.rsi_21:.1f})")

    return factors


def _persistence_gate(direction: str, sig: PositionalSignals) -> GateResult:
    """Require 2 consecutive daily closes in signal direction, computed from historical data."""
    streak = sig.consecutive_streak
    passed = streak >= 2 and sig.consecutive_direction == direction
    return GateResult(
        passed=passed,
        name="persistence",
        detail=f"{streak} consecutive {sig.consecutive_direction or '?'} close(s) (need 2 in {direction} direction)",
    )


def analyze_ticker(
    ticker: str,
    spy_daily=None,
) -> AnalysisResult:
    """Run all 7 gates for one ticker. Returns AnalysisResult (no alert fired here)."""
    is_holding = ticker in HOLDING_TICKERS

    df_daily = fetch_daily(ticker, period="1y")
    df_weekly = fetch_weekly(ticker, period="2y")

    sig = compute_positional_signals(df_daily, df_weekly, spy_daily, ticker=ticker)

    result = AnalysisResult(
        ticker=ticker,
        price=sig.price,
        currency=sig.currency,
        signal_type=None,
        confidence=None,
        is_holding=is_holding,
        signals=sig,
    )

    if sig.errors or sig.price is None:
        result.not_confirmed_reason = f"Data error: {sig.errors}"
        return result

    gates = []

    # Gate 1 — Market regime (SPY above 200-SMA)
    if spy_daily is not None and not spy_daily.empty:
        spy_close = spy_daily["close"].astype(float)
        spy_sma200 = spy_close.rolling(200, min_periods=200).mean().dropna()
        if not spy_sma200.empty:
            spy_in_bull = float(spy_close.iloc[-1]) > float(spy_sma200.iloc[-1])
        else:
            spy_in_bull = True  # insufficient history, don't block
        gates.append(GateResult(
            passed=spy_in_bull,
            name="market_regime",
            detail="SPY above 200-SMA (bull regime)" if spy_in_bull else "SPY below 200-SMA (bear regime)",
        ))
    else:
        gates.append(GateResult(passed=True, name="market_regime", detail="SPY data unavailable — skipped"))

    regime_ok = gates[-1].passed

    # Determine direction before trend/stack gates — enables direction-aware evaluation
    direction = _determine_signal_direction(sig)

    if not direction:
        result.not_confirmed_reason = "No clear directional bias (weekly trend and MA stack not aligned)"
        result.gates = gates
        return result

    is_reversal = (
        (sig.rsi_divergence == "bullish" and sig.near_52w_low) or
        (sig.rsi_divergence == "bearish" and sig.near_52w_high)
    )

    # Gate 2 — Weekly trend (reversal requires opposite trend confirming the setup)
    if is_reversal:
        weekly_ok = sig.weekly_trend == ("down" if direction == "bullish" else "up")
        weekly_detail = (
            f"Counter-trend reversal — weekly trend {sig.weekly_trend} (30w SMA: {sig.sma_30w:.2f})"
            if sig.sma_30w else f"Counter-trend reversal — weekly trend {sig.weekly_trend}"
        )
    else:
        weekly_ok = sig.weekly_trend == ("up" if direction == "bullish" else "down")
        weekly_detail = (
            f"Weekly trend: {sig.weekly_trend} (30w SMA: {sig.sma_30w:.2f})"
            if sig.sma_30w else f"Weekly trend: {sig.weekly_trend}"
        )
    gates.append(GateResult(passed=weekly_ok, name="weekly_trend", detail=weekly_detail))

    # Gate 3 — MA stack (reversal requires opposite stack confirming oversold/overbought)
    if is_reversal:
        if direction == "bullish":
            ma_ok = sig.ma_stack_bearish
            ma_detail = (
                f"Counter-trend reversal — price({sig.price:.2f}) < SMA50({sig.sma_50:.2f}) < SMA200({sig.sma_200:.2f}) (oversold setup)"
                if sig.ma_stack_bearish else "MA stack not in expected bearish state for bullish reversal"
            )
        else:
            ma_ok = sig.ma_stack_bullish
            ma_detail = (
                f"Counter-trend reversal — price({sig.price:.2f}) > SMA50({sig.sma_50:.2f}) > SMA200({sig.sma_200:.2f}) (overbought setup)"
                if sig.ma_stack_bullish else "MA stack not in expected bullish state for bearish reversal"
            )
    else:
        if sig.ma_stack_bullish:
            ma_ok = True
            ma_detail = f"Bullish stack: price({sig.price:.2f}) > SMA50({sig.sma_50:.2f}) > SMA200({sig.sma_200:.2f})"
        elif sig.ma_stack_bearish:
            ma_ok = True
            ma_detail = f"Bearish stack: price({sig.price:.2f}) < SMA50({sig.sma_50:.2f}) < SMA200({sig.sma_200:.2f})"
        else:
            ma_ok = False
            ma_detail = "MA stack not aligned"
    gates.append(GateResult(passed=ma_ok, name="ma_stack", detail=ma_detail))

    # Bear regime suppresses bullish signals
    if not regime_ok and direction == "bullish":
        result.not_confirmed_reason = "Bear regime active — bullish signals suppressed"
        result.gates = gates
        return result

    # Gate 4 — Confluence (need ≥2 factors)
    confluence = _count_confluence(sig, direction)
    confluence_ok = len(confluence) >= 2
    gates.append(GateResult(
        passed=confluence_ok,
        name="confluence",
        detail=f"{len(confluence)}/4 factors: {'; '.join(confluence)}" if confluence else "No confluence factors",
    ))
    result.confluence_factors = confluence

    # Gate 5 — Persistence (streak computed from historical data — offline-safe)
    persistence_gate = _persistence_gate(direction, sig)
    gates.append(persistence_gate)

    # Gate 6 — Earnings blackout
    earnings_date = fetch_earnings_date(ticker)
    result.earnings_date = earnings_date
    earnings_ok = True
    earnings_detail = "No earnings within 10 trading days"
    if earnings_date:
        days_to_earnings = trading_days_until(earnings_date)
        if days_to_earnings <= _EARNINGS_BLACKOUT_DAYS:
            earnings_ok = False
            earnings_detail = f"EARNINGS RISK: {earnings_date} ({days_to_earnings} trading days)"
        else:
            earnings_detail = f"Earnings {earnings_date} ({days_to_earnings} trading days away)"
    gates.append(GateResult(passed=earnings_ok, name="earnings_blackout", detail=earnings_detail))

    # Gate 7 — Relative strength vs SPY
    rs_ok = sig.outperforming_spy if direction == "bullish" else not sig.outperforming_spy
    rs_detail = (
        f"63d return: {sig.return_63d:+.1f}% vs SPY {sig.spy_return_63d:+.1f}%"
        if sig.return_63d is not None and sig.spy_return_63d is not None
        else "Relative strength data unavailable"
    )
    gates.append(GateResult(passed=rs_ok, name="relative_strength", detail=rs_detail))

    result.gates = gates

    all_passed = all(g.passed for g in gates)
    gates_passed = sum(1 for g in gates if g.passed)

    if all_passed:
        result.signal_type = direction
        result.confidence = "High"
    elif gates_passed >= 5:
        result.signal_type = direction
        result.confidence = "Medium"
        result.not_confirmed_reason = f"Medium confidence: {7 - gates_passed} gate(s) failed"
    else:
        failed = [g.name for g in gates if not g.passed]
        result.not_confirmed_reason = f"Not Confirmed — failed gates: {', '.join(failed)}"
        return result

    # Position sizing
    if AVAILABLE_CAPITAL_USD > 0:
        result.suggested_position_usd = round(AVAILABLE_CAPITAL_USD * _POSITION_SIZE_PCT, 2)

    if sig.atr_14:
        result.atr_stop = round(sig.atr_14 * 2, 4)

    if sig.atr_14 and sig.price:
        p = sig.price
        a = sig.atr_14
        sma50 = sig.sma_50 or p
        if direction == "bullish":
            result.entry_high = round(p + 0.25 * a, 2) if sig.near_52w_high else round(p, 2)
            result.entry_low = round(max(p - a, min(sma50, p)), 2)
        else:
            result.entry_low = round(p - 0.25 * a, 2) if sig.near_52w_low else round(p, 2)
            result.entry_high = round(min(p + a, max(sma50, p)), 2)
        atr_pct = (a / p) * 100
        result.volatility_tier = "High" if atr_pct > 4.0 else "Medium" if atr_pct >= 1.5 else "Low"

    return result


def run_analysis_cycle() -> list[AnalysisResult]:
    """Analyze all tickers. Returns results — caller decides what to alert on."""
    log.info("Starting positional analysis cycle for %d tickers", len(TICKERS))

    # Fetch SPY once and reuse across all tickers
    spy_daily = fetch_daily(_SPY_TICKER, period="1y")
    if _SPY_TICKER not in TICKERS:
        pass  # SPY used only for regime check

    results = []
    for i, ticker in enumerate(TICKERS):
        try:
            if i > 0:
                time.sleep(0.5)
            log.info("Analyzing %s", ticker)
            r = analyze_ticker(ticker, spy_daily=spy_daily)
            results.append(r)
        except Exception as e:
            log.exception("Analysis failed for %s: %s", ticker, e)

    confirmed = [r for r in results if r.signal_type]
    log.info(
        "Analysis complete: %d/%d tickers with confirmed signals",
        len(confirmed), len(results),
    )
    return results
