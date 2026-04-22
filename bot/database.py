import sqlite3, json, time
from contextlib import contextmanager
from .config import settings
from .logger import get_logger

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id TEXT PRIMARY KEY,
    username TEXT,
    created_at INTEGER,
    risk_acknowledged INTEGER DEFAULT 0,
    paper_mode INTEGER DEFAULT 1,
    equity REAL DEFAULT 10000
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT, symbol TEXT, side TEXT,
    entry REAL, stop REAL, target REAL,
    confidence REAL, thesis TEXT, verification TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT, signal_id INTEGER, symbol TEXT, side TEXT,
    qty REAL, entry REAL, stop REAL, target REAL,
    status TEXT, pnl REAL DEFAULT 0,
    opened_at INTEGER, closed_at INTEGER
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT, ts INTEGER, kind TEXT, payload TEXT
);
"""

def _db_path():
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return "oraclex.db"

@contextmanager
def conn():
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
    log.info("DB initialized at %s", _db_path())

def upsert_user(tid, username):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(telegram_id, username, created_at) VALUES(?,?,?)",
                  (str(tid), username or "", int(time.time())))

def get_user(tid):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE telegram_id=?", (str(tid),)).fetchone()
        return dict(r) if r else None

def set_user_field(tid, field, value):
    with conn() as c:
        c.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, str(tid)))

def save_signal(user_id, sig: dict) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO signals(user_id,symbol,side,entry,stop,target,confidence,thesis,verification,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(user_id), sig["symbol"], sig["side"], sig["entry"], sig["stop"], sig["target"],
             sig["confidence"], sig["thesis"], json.dumps(sig.get("verification", {})), int(time.time())))
        return cur.lastrowid

def save_trade(user_id, signal_id, t: dict) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO trades(user_id,signal_id,symbol,side,qty,entry,stop,target,status,opened_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(user_id), signal_id, t["symbol"], t["side"], t["qty"], t["entry"],
             t["stop"], t["target"], t.get("status", "open"), int(time.time())))
        return cur.lastrowid

def close_trade(trade_id, pnl):
    with conn() as c:
        c.execute("UPDATE trades SET status='closed', pnl=?, closed_at=? WHERE id=?",
                  (pnl, int(time.time()), trade_id))

def list_open_trades(user_id):
    with conn() as c:
        rows = c.execute("SELECT * FROM trades WHERE user_id=? AND status='open' ORDER BY id DESC",
                         (str(user_id),)).fetchall()
        return [dict(r) for r in rows]

def journal(user_id, kind, payload):
    with conn() as c:
        c.execute("INSERT INTO journal(user_id,ts,kind,payload) VALUES(?,?,?,?)",
                  (str(user_id), int(time.time()), kind, json.dumps(payload)[:4000]))
