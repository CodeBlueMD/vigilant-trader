"""AI narrative engine — compound-beta primary, llama-3.3-70b fallback.

The AI explains confirmed quant signals. It never overrides gate results.
Zero ongoing cost: Groq free tier + Ollama local only.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import requests

from config import (
    AI_DISCLAIMER,
    AI_TIMEOUT_SECONDS,
    GROQ_API_KEY,
    GROQ_MODEL_FALLBACK,
    GROQ_MODEL_PRIMARY,
    OLLAMA_MODEL,
    OLLAMA_URL,
    log,
)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

POSITIONAL_ANALYST_SYSTEM = """You are a Positional Research Analyst. Your role is to provide
objective, concise analytical narrative for trading setups that have already been confirmed by
a quantitative signal engine.

You receive pre-computed signal data (gates, indicators, confluence factors). Your job:
1. Write a brief narrative explaining WHY this signal matters in the current market context
2. Flag anything that increases or reduces conviction (macro, sector, news)
3. Identify the key risk to the trade

STRICT RULES:
- Never override or change the computed gate results — they are ground truth
- Never recommend a specific position size (that is computed separately)
- If you identify an upcoming earnings date or macro risk, flag it explicitly
- Be concise — this appears in a mobile email
- Always advisory only, never a trade recommendation
- Output plain text only, no markdown headers or bullet symbols"""


@dataclass
class AIStatus:
    backend: str = "offline"
    model: str = ""
    last_latency_ms: float | None = None
    last_error: str = ""
    last_success_ts: float | None = None


class AIEngine:
    def __init__(self) -> None:
        self.groq_key = GROQ_API_KEY
        self.timeout = AI_TIMEOUT_SECONDS
        self.status = AIStatus()

    def _call_groq(self, system: str, user: str, model: str, max_tokens: int) -> str:
        if not self.groq_key:
            raise ValueError("No Groq API key")
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        t0 = time.perf_counter()
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=self.timeout)
        self.status.last_latency_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()

    def _call_ollama(self, system: str, user: str, max_tokens: int) -> str:
        url = f"{OLLAMA_URL}/api/chat"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        t0 = time.perf_counter()
        r = requests.post(url, json=payload, timeout=self.timeout)
        self.status.last_latency_ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        return (r.json().get("message", {}).get("content") or "").strip()

    def ask(self, system: str, user: str, max_tokens: int = 400) -> str:
        """Try compound-beta -> llama-3.3-70b-versatile -> Ollama."""
        for backend, model in [
            ("groq", GROQ_MODEL_PRIMARY),
            ("groq", GROQ_MODEL_FALLBACK),
            ("ollama", None),
        ]:
            try:
                if backend == "groq":
                    text = self._call_groq(system, user, model, max_tokens)
                else:
                    text = self._call_ollama(system, user, max_tokens)
                if text:
                    self.status.backend = backend
                    self.status.model = model or OLLAMA_MODEL
                    self.status.last_success_ts = time.time()
                    self.status.last_error = ""
                    return text
            except Exception as e:
                self.status.last_error = f"{backend}/{model}: {e}"
                log.warning("AI backend %s/%s failed: %s", backend, model, e)

        self.status.backend = "offline"
        return ""

    def generate_positional_narrative(
        self,
        ticker: str,
        signal_type: str,
        confidence: str,
        confluence_factors: list,
        gates: list,
        price: float,
        currency: str,
        rsi: float | None,
        atr_stop_pct: float | None,
        is_holding: bool,
        suggested_position_usd: float | None,
        earnings_date=None,
    ) -> str:
        gates_summary = "\n".join(
            f"  {'PASS' if g.passed else 'FAIL'} {g.name}: {g.detail}"
            for g in gates
        )
        confluence_text = "\n".join(f"  - {f}" for f in confluence_factors)
        position_context = (
            "THIS IS AN EXISTING HOLDING — frame as monitor/add/trim opportunity."
            if is_holding
            else (
                f"Fresh entry opportunity. Suggested position: ${suggested_position_usd:,.0f} USD."
                if suggested_position_usd
                else "Fresh entry opportunity."
            )
        )
        earnings_note = f"Earnings date: {earnings_date}" if earnings_date else "No imminent earnings."

        user_prompt = (
            f"Ticker: {ticker} | Signal: {signal_type.upper()} | Confidence: {confidence}\n"
            f"Price: {currency} {price:,.2f}\n"
            f"RSI(21): {f'{rsi:.1f}' if rsi else 'N/A'}\n"
            f"ATR stop distance: {f'{atr_stop_pct:.1f}%' if atr_stop_pct else 'N/A'} below entry\n\n"
            f"Gates:\n{gates_summary}\n\n"
            f"Confluence factors:\n{confluence_text}\n\n"
            f"{position_context}\n{earnings_note}\n\n"
            "Write 3 concise sentences:\n"
            "1. Why this signal is significant right now\n"
            "2. Key risk or headwind to watch\n"
            "3. What to monitor for confirmation or invalidation\n\n"
            f"End with: '{AI_DISCLAIMER}'"
        )

        raw = self.ask(POSITIONAL_ANALYST_SYSTEM, user_prompt, max_tokens=350)
        if not raw:
            return (
                f"{ticker} {signal_type} signal confirmed with {confidence} confidence. "
                f"Confluence: {', '.join(confluence_factors[:2])}. {AI_DISCLAIMER}"
            )
        if AI_DISCLAIMER[:20].lower() not in raw.lower():
            raw = raw.rstrip() + " " + AI_DISCLAIMER
        return raw

    def generate_weekly_summary_narrative(self, all_results: list) -> str:
        ticker_lines = [
            f"{r['ticker']}: trend={r.get('weekly_trend','?')}, "
            f"signal={r.get('signal_type','none')}, confidence={r.get('confidence','N/A')}"
            for r in all_results[:12]
        ]
        user_prompt = (
            f"Weekly positional summary:\n" + "\n".join(ticker_lines) + "\n\n"
            "Write 2-3 plain-English sentences: overall market posture, "
            "strongest setups, and what to watch this week. "
            f"End with: '{AI_DISCLAIMER}'"
        )
        raw = self.ask(POSITIONAL_ANALYST_SYSTEM, user_prompt, max_tokens=250)
        return raw or f"Weekly summary unavailable — review signals below. {AI_DISCLAIMER}"


ai_engine = AIEngine()
