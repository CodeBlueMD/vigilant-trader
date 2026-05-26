"""SQLite-backed persistence for VigilantTrader.

Stores fired alerts, AI verdicts, divergence log, and arbitrary key/value state
that we want to survive restarts (e.g. last-seen news headlines, AI cache).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from config import DB_PATH, log


SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    ticker        TEXT,
    severity      TEXT,
    kind          TEXT,
    headline      TEXT,
    payload_json  TEXT
);

CREATE TABLE IF NOT EXISTS ai_verdicts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    ticker        TEXT,
    bias          TEXT,
    confidence    TEXT,
    urgency       TEXT,
    score         REAL,
    payload_json  TEXT
);

CREATE TABLE IF NOT EXISTS divergence_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    ticker        TEXT,
    quant_bias    TEXT,
    ai_bias       TEXT,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key       TEXT PRIMARY KEY,
    value     TEXT,
    updated   REAL
);

CREATE TABLE IF NOT EXISTS weekly_predictions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT    NOT NULL,
    monday_ts           REAL    NOT NULL,
    monday_price        REAL,
    target_low          REAL,
    target_high         REAL,
    expected_close      REAL,
    direction           TEXT,
    confidence          TEXT,
    key_catalyst        TEXT,
    bias                TEXT,
    friday_ts           REAL,
    friday_close        REAL,
    actual_move_pct     REAL,
    expected_error_pct  REAL,
    in_range            INTEGER,
    direction_correct   INTEGER
);

CREATE TABLE IF NOT EXISTS positional_signals (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_ts              REAL    NOT NULL,
    ticker                 TEXT    NOT NULL,
    signal_type            TEXT,
    confidence             TEXT,
    entry_price            REAL,
    gates_fired            TEXT,
    atr_stop               REAL,
    suggested_position_usd REAL,
    ai_narrative           TEXT,
    entry_range_high       REAL,
    entry_range_low        REAL,
    volatility_tier        TEXT,
    eval_30d_ts            REAL,
    eval_30d_price         REAL,
    eval_30d_return_pct    REAL,
    eval_30d_outcome       TEXT,
    eval_60d_ts            REAL,
    eval_60d_price         REAL,
    eval_60d_return_pct    REAL,
    eval_60d_outcome       TEXT
);

CREATE TABLE IF NOT EXISTS consecutive_closes (
    ticker      TEXT    PRIMARY KEY,
    direction   TEXT,
    count       INTEGER DEFAULT 0,
    last_close  REAL,
    last_date   TEXT,
    updated     REAL
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts          ON alerts(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker      ON alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_verdicts_ts        ON ai_verdicts(ts);
CREATE INDEX IF NOT EXISTS idx_predictions_ticker ON weekly_predictions(ticker, monday_ts);
CREATE INDEX IF NOT EXISTS idx_signals_ticker     ON positional_signals(ticker, signal_ts);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema deployment."""
    new_cols = [
        ("entry_range_high", "REAL"),
        ("entry_range_low",  "REAL"),
        ("volatility_tier",  "TEXT"),
    ]
    for col, typedef in new_cols:
        try:
            conn.execute(f"ALTER TABLE positional_signals ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # column already exists


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_db(conn)
    log.info("Database initialised at %s", DB_PATH)


# --- Alerts -------------------------------------------------------------

def record_alert(
    ticker: str | None,
    severity: str,
    kind: str,
    headline: str,
    payload: dict | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO alerts (ts, ticker, severity, kind, headline, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), ticker, severity, kind, headline, json.dumps(payload or {})),
        )
        return int(cur.lastrowid)


def recent_alerts(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- AI verdicts --------------------------------------------------------

def record_ai_verdict(ticker: str, verdict: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ai_verdicts (ts, ticker, bias, confidence, urgency, score, payload_json)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                time.time(),
                ticker,
                verdict.get("ai_bias") or verdict.get("bias"),
                verdict.get("ai_confidence") or verdict.get("confidence"),
                verdict.get("ai_urgency") or verdict.get("urgency"),
                float(verdict.get("score", 0.0) or 0.0),
                json.dumps(verdict),
            ),
        )


def latest_ai_verdicts(limit_per_ticker: int = 1) -> list[dict]:
    """Return latest AI verdict per ticker (one row per ticker)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.* FROM ai_verdicts a "
            "JOIN (SELECT ticker, MAX(ts) AS mts FROM ai_verdicts GROUP BY ticker) b "
            "ON a.ticker=b.ticker AND a.ts=b.mts ORDER BY a.ticker"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- Divergence log -----------------------------------------------------

def record_divergence(ticker: str, quant_bias: str, ai_bias: str, note: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO divergence_log (ts, ticker, quant_bias, ai_bias, note) "
            "VALUES (?,?,?,?,?)",
            (time.time(), ticker, quant_bias, ai_bias, note),
        )


def recent_divergences(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM divergence_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- Generic key/value state -------------------------------------------

def state_set(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO state (key, value, updated) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            (key, json.dumps(value, default=str), time.time()),
        )


def state_get(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM state WHERE key=?", (key,)
        ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default


def state_age_seconds(key: str) -> float | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT updated FROM state WHERE key=?", (key,)
        ).fetchone()
    if not row:
        return None
    return time.time() - float(row["updated"])


# --- Helpers ------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "payload_json" in d and d["payload_json"]:
        try:
            d["payload"] = json.loads(d["payload_json"])
        except Exception:
            d["payload"] = {}
    return d


def alerts_in_window(seconds: int) -> Iterable[dict]:
    cutoff = time.time() - seconds
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE ts >= ? ORDER BY ts DESC", (cutoff,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- Positional signals ------------------------------------------------

def record_positional_signal(
    ticker: str,
    signal_type: str,
    confidence: str,
    entry_price: float,
    gates_fired: list[str],
    atr_stop: float | None,
    suggested_position_usd: float | None,
    ai_narrative: str,
    entry_range_high: float | None = None,
    entry_range_low: float | None = None,
    volatility_tier: str = "",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO positional_signals
               (signal_ts, ticker, signal_type, confidence, entry_price, gates_fired,
                atr_stop, suggested_position_usd, ai_narrative,
                entry_range_high, entry_range_low, volatility_tier)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(), ticker, signal_type, confidence, entry_price,
                json.dumps(gates_fired), atr_stop, suggested_position_usd, ai_narrative,
                entry_range_high, entry_range_low, volatility_tier or None,
            ),
        )
        return int(cur.lastrowid)


def open_positional_signals() -> list[dict]:
    """Signals where 30-day or 60-day evaluation is still pending."""
    cutoff_30 = time.time() - 30 * 86400
    cutoff_60 = time.time() - 60 * 86400
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM positional_signals
               WHERE (eval_30d_ts IS NULL AND signal_ts <= ?)
                  OR (eval_60d_ts IS NULL AND signal_ts <= ?)
               ORDER BY signal_ts ASC""",
            (cutoff_30, cutoff_60),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_signal_evaluation(
    signal_id: int,
    period: str,
    price: float,
    return_pct: float,
    outcome: str,
) -> None:
    col_ts = f"eval_{period}_ts"
    col_price = f"eval_{period}_price"
    col_ret = f"eval_{period}_return_pct"
    col_out = f"eval_{period}_outcome"
    with get_conn() as conn:
        conn.execute(
            f"UPDATE positional_signals SET {col_ts}=?, {col_price}=?, {col_ret}=?, {col_out}=? WHERE id=?",
            (time.time(), price, return_pct, outcome, signal_id),
        )


def recent_positional_signals(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positional_signals ORDER BY signal_ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


# --- Consecutive closes state ------------------------------------------

def get_consecutive_closes(ticker: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM consecutive_closes WHERE ticker=?", (ticker,)
        ).fetchone()
    return dict(row) if row else {"ticker": ticker, "direction": None, "count": 0}


def set_consecutive_closes(
    ticker: str, direction: str, count: int, last_close: float, last_date: str
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO consecutive_closes (ticker, direction, count, last_close, last_date, updated)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(ticker) DO UPDATE SET
                 direction=excluded.direction, count=excluded.count,
                 last_close=excluded.last_close, last_date=excluded.last_date,
                 updated=excluded.updated""",
            (ticker, direction, count, last_close, last_date, time.time()),
        )


# Initialise on import
init_db()
