# VigilantTrader — Positional Edition

A headless, 24/7 positional trading monitor that runs on your Mac and emails you when a high-conviction setup confirms across your watchlist.

**Philosophy:** No noise. Alerts fire only when 7 quantitative gates align. You might get 1-3 alerts per month — each one means something.

---

## How It Works

Every weekday at 4:15 PM ET (after market close), the system:

1. Fetches D1 and W1 price data for all tickers via yfinance
2. Runs every ticker through 7 gates — all must pass to fire an alert
3. If gates pass, Groq AI (compound-beta) writes a narrative explaining why
4. Sends you a mobile-friendly email with the full breakdown

**Every Sunday at 8 AM ET:** weekly trend table across your whole watchlist  
**First Sunday of each month:** accuracy report — win rates, avg returns by ticker and confidence level

---

## The 7 Gates

| Gate | Rule |
|---|---|
| Market Regime | SPY above 200-day SMA (bull market active) |
| Weekly Trend | Stock above 30-week SMA (directional bias confirmed) |
| MA Stack | Price > 50-SMA > 200-SMA (healthy trend structure) |
| Confluence | ≥2 of: S/R touch, Volume spike >150%, RSI(21) divergence, 52w high breakout |
| Persistence | 2 consecutive daily closes confirming the direction |
| Earnings Blackout | No earnings within 10 trading days |
| Relative Strength | Outperforming SPY on 63-day basis |

**High Confidence** = all 7 pass  
**Medium Confidence** = 5-6 pass (flagged as such)  
**Not Confirmed** = fewer than 5 (no email sent)

---

## Setup

### Requirements
- Python 3.9+
- macOS (or any Linux/Windows machine that runs continuously)
- Gmail account with an [App Password](https://support.google.com/accounts/answer/185833)
- [Groq free account](https://console.groq.com) (no credit card needed)

### Install

```bash
git clone https://github.com/CodeBlueMD/vigilant-trader.git
cd vigilant-trader
bash setup.sh
```

### Configure

Edit `.env`:

```env
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your_app_password
ALERT_RECIPIENT=your@gmail.com
GROQ_API_KEY=gsk_...

HOLDING_TICKERS=IBIT,QQQM,GLD
WATCHLIST_TICKERS=VFV.TO,AAPL,TSLA,SPY,NVDA,TSM,CRWD,NFLX,AMZN,GOOGL
AVAILABLE_CAPITAL_USD=5000
```

### Run

```bash
source venv/bin/activate
python main.py
```

On macOS, double-click `VigilantTrader.command` for a one-click start.

---

## AI Stack

- **Primary:** Groq `compound-beta` — live web search + Llama 4 reasoning (free)
- **Fallback:** Groq `llama-3.3-70b-versatile` (free)
- **Last resort:** Local Ollama (optional)

The AI explains confirmed signals only. It never overrides the quantitative gates.

---

## Key Constraints (Never Break)

- Zero AI API cost — Groq free tier + Ollama only
- AI is advisory only — every output includes a disclaimer
- App keeps running on quant-only signals if AI is offline
- 30-second AI timeout
- No trade execution — monitor and alert only

---

## Accuracy Tracking

Every alert is logged to `vigilant.db`. The system automatically evaluates outcomes at 30 and 60 days. The monthly report shows:

- Win rate by confidence level (High vs Medium)
- Average return per signal
- Best and worst performing tickers

This lets you tune the system over time based on real results.

---

## Run as a Background Daemon (macOS)

To run VigilantTrader automatically on login and keep it alive without a Terminal window:

```bash
bash install_daemon.sh
```

This installs a launchd agent that:
- Starts automatically when you log in
- Restarts within 30 seconds if it crashes
- Runs silently in the background — no Terminal needed

**Important:** Go to **System Settings → Energy → Power Adapter** and enable **"Prevent automatic sleeping when display is off"** so the daemon keeps running when your screen locks.

To manage the daemon:
```bash
# Check status
launchctl list | grep vigilant-trader

# Stop
launchctl unload ~/Library/LaunchAgents/com.codebluemd.vigilant-trader.plist

# Start
launchctl load ~/Library/LaunchAgents/com.codebluemd.vigilant-trader.plist

# Watch logs live
tail -f vigilant.log
```

---

## Disclaimer

This tool is for informational purposes only. It is NOT financial advice. Always do your own research before making any investment decision.
