"""Central configuration for VigilantTrader — Positional Edition."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


# --- Watchlist ---
HOLDING_TICKERS: list[str] = _split_csv(
    os.getenv("HOLDING_TICKERS", "IBIT,QQQM,GLD")
)
WATCHLIST_TICKERS: list[str] = _split_csv(
    os.getenv("WATCHLIST_TICKERS", "VFV.TO,AAPL,TSLA,SPY,NVDA,TSM,CRWD,NFLX,AMZN,GOOGL")
)
TICKERS: list[str] = HOLDING_TICKERS + [
    t for t in WATCHLIST_TICKERS if t not in HOLDING_TICKERS
]

# --- Portfolio context ---
AVAILABLE_CAPITAL_USD: float = float(os.getenv("AVAILABLE_CAPITAL_USD", "0"))
try:
    PORTFOLIO_HOLDINGS: dict = json.loads(os.getenv("PORTFOLIO_HOLDINGS_JSON", "{}"))
except Exception:
    PORTFOLIO_HOLDINGS = {}

# --- Email (single recipient) ---
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENT: str = os.getenv("ALERT_RECIPIENT", "")

# --- AI backends ---
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL_PRIMARY: str = os.getenv("GROQ_MODEL_PRIMARY", "compound-beta")
GROQ_MODEL_FALLBACK: str = os.getenv("GROQ_MODEL_FALLBACK", "llama-3.3-70b-versatile")
AI_BACKEND: str = os.getenv("AI_BACKEND", "groq").lower()
AI_TIMEOUT_SECONDS: int = 30

# --- Holdings drawdown protection ---
HOLDING_ATR_MULTIPLIERS: dict = {
    "IBIT": 3.0,   # crypto — wider threshold to filter normal volatility
    "QQQM": 2.0,   # Nasdaq ETF — standard
    "GLD":  1.5,   # gold — tighter, large moves are significant
}

# --- Schedule (US/Eastern) ---
TIMEZONE: str = os.getenv("TIMEZONE", "America/Toronto")
ANALYSIS_HOUR: int = int(os.getenv("ANALYSIS_HOUR", "16"))
ANALYSIS_MINUTE: int = int(os.getenv("ANALYSIS_MINUTE", "15"))

# --- Storage ---
DB_PATH: str = os.getenv("DB_PATH", str(PROJECT_ROOT / "vigilant.db"))
LOG_FILE: str = os.getenv("LOG_FILE", str(PROJECT_ROOT / "vigilant.log"))

if not os.path.isabs(DB_PATH):
    DB_PATH = str(PROJECT_ROOT / DB_PATH)
if not os.path.isabs(LOG_FILE):
    LOG_FILE = str(PROJECT_ROOT / LOG_FILE)

AI_DISCLAIMER: str = (
    "AI analysis is advisory only and is NOT financial advice. "
    "Always do your own research before making any investment decision."
)


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("vigilant")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = setup_logging()


def email_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD and ALERT_RECIPIENT)
