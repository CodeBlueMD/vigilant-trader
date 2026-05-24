# VigilantTrader — Positional Edition

**Entry point:** `main.py`  
**Project root:** `~/Desktop/AI_CLI/ClaudeCode/vigilant-trader/`  
**Python:** 3.9 · **venv:** `./venv/` · **DB:** `vigilant.db` · **Logs:** `vigilant.log`

---

## Architecture

```
main.py          → starts scheduler, keeps process alive
scheduler.py     → APScheduler: analysis weekdays 4:15 PM ET, evals 5 AM, Sunday 8 AM
positional_analyst.py → 7-gate signal engine (core logic)
technical_analysis.py → D1/W1 indicators (SMA, RSI, ATR, divergence)
data_fetcher.py  → yfinance daily/weekly/earnings
ai_engine.py     → Groq compound-beta narrative (explains signals, never overrides gates)
accuracy_tracker.py → logs signals, evaluates 30d/60d outcomes
email_system.py  → SMTP send, positional alert + weekly summary + monthly report templates
database.py      → SQLite: positional_signals, consecutive_closes tables
config.py        → all env vars loaded here
```

---

## Hard Constraints

1. Zero AI API cost — Groq free tier + Ollama local only. Never add paid APIs.
2. AI is advisory only — every output must include `config.AI_DISCLAIMER`.
3. App keeps running on quant-only if AI is offline — never block on AI.
4. 30s AI timeout — never remove.
5. No trade execution — monitor + alert only.
6. Single email recipient — `ALERT_RECIPIENT` in .env (one address only).

---

## Style Rules

- Surgical edits only — touch only what the task requires.
- After multi-file changes: `python3 -m py_compile *.py` from project dir.
- No new heavy deps unless explicitly requested.
- All timeframe analysis: D1 and W1 only — no intraday data.

---

## Watchlist (configured in .env)

**Holdings (position management alerts):** IBIT, QQQM, GLD (proxy for physical gold)  
**Watchlist (entry opportunity alerts):** VFV.TO, AAPL, TSLA, SPY, NVDA, TSM, CRWD, NFLX, AMZN, GOOGL

---

## Key Files

| File | Role |
|---|---|
| `positional_analyst.py` | 7-gate signal engine — core logic |
| `technical_analysis.py` | SMA50/200, RSI(21), ATR, divergence, MA stack |
| `data_fetcher.py` | yfinance D1/W1, earnings date |
| `ai_engine.py` | Groq compound-beta + fallback, Positional Analyst system prompt |
| `accuracy_tracker.py` | Signal log + 30d/60d evaluation |
| `email_system.py` | Alert, weekly summary, monthly report templates |
| `scheduler.py` | APScheduler job wiring |
| `database.py` | positional_signals + consecutive_closes tables |
| `config.py` | All env vars — single source of truth |

---

## Runtime

- Start: `source venv/bin/activate && python main.py`
- Or: double-click `VigilantTrader.command`
- Logs: `tail -f vigilant.log`
- Trigger manual analysis: `python -c "from scheduler import _run_analysis; _run_analysis()"`
