import json, time, os
from contextlib import contextmanager
from urllib.parse import urlparse, unquote
from .config import settings
from .logger import get_logger

log = get_logger(__name__)

IS_PG = settings.DATABASE_URL.startswith(("postgres://", "postgresql://"))

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (telegram_id TEXT PRIMARY KEY, username TEXT, created_at INTEGER,
    risk_acknowledged INTEGER DEFAULT 0, paper_mode INTEGER DEFAULT 1, equity REAL DEFAULT 10000);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, symbol TEXT, side TEXT,
    entry REAL, stop REAL, target REAL, confidence REAL, thesis TEXT, verification TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, signal_id INTEGER,
    symbol TEXT, side TEXT, qty REAL, entry REAL, stop REAL, target REAL, status TEXT, pnl REAL DEFAULT 0,
    opened_at INTEGER, closed_at INTEGER);
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, ts INTEGER, kind TEXT, payload TEXT);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (telegram_id TEXT PRIMARY KEY, username TEXT, created_at BIGINT,
    risk_acknowledged INTEGER DEFAULT 0, paper_mode INTEGER DEFAULT 1, equity DOUBLE PRECISION DEFAULT 10000);
CREATE TABLE IF NOT EXISTS signals (id SERIAL PRIMARY KEY, user_id TEXT, symbol TEXT, side TEXT,
    entry DOUBLE PRECISION, stop DOUBLE PRECISION, target DOUBLE PRECISION, confidence DOUBLE PRECISION,
    thesis TEXT, verification TEXT, created_at BIGINT);
CREATE TABLE IF NOT EXISTS trades (id SERIAL PRIMARY KEY, user_id TEXT, signal_id INTEGER,
    symbol TEXT, side TEXT, qty DOUBLE PRECISION, entry DOUBLE PRECISION, stop DOUBLE PRECISION,
    target DOUBLE PRECISION, status TEXT, pnl DOUBLE PRECISION DEFAULT 0, opened_at BIGINT, closed_at BIGINT);
CREATE TABLE IF NOT EXISTS journal (id SERIAL PRIMARY KEY, user_id TEXT, ts BIGINT, kind TEXT, payload TEXT);
"""

class PGConn:
    def __init__(self, conn):
        self._c = conn
        self._cur = conn.cursor()
    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("?", "%s"), params); return self
    def executescript(self, sql):
        self._cur.execute(sql); return self
    def fetchone(self):
        row = self._cur.fetchone()
        if not row: return None
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))
    def fetchall(self):
        rows = self._cur.fetchall() or []
        cols = [d[0] for d in self._cur.description]
        return [dict(zip(cols, r)) for r in rows]
    @property
    def lastrowid(self):
        self._cur.execute("SELECT LASTVAL()")
        return self._cur.fetchone()[0]

class PGWrap:
    def __init__(self, conn): self._c = conn
    def execute(self, sql, params=()):
        p = PGConn(self._c); p.execute(sql, params); return p
    def executescript(self, sql):
        PGConn(self._c).executescript(sql)
    def commit(self): self._c.commit()
    def close(self): self._c.close()

@contextmanager
def conn():
    if IS_PG:
        import psycopg2
        c = psycopg2.connect(settings.DATABASE_URL, sslmode="require")
        w = PGWrap(c)
        try: yield w; w.commit()
        finally: w.close()
    else:
        import sqlite3
        path = settings.DATABASE_URL.replace("sqlite:///", "", 1) if settings.DATABASE_URL.startswith("sqlite") else "oraclex.db"
        c = sqlite3.connect(path); c.row_factory = sqlite3.Row
        try: yield c; c.commit()
        finally: c.close()

def init_db():
    with conn() as c:
        c.executescript(SCHEMA_PG if IS_PG else SCHEMA_SQLITE)
    log.info("DB initialized (%s)", "postgres" if IS_PG else "sqlite")

def upsert_user(tid, username):
    with conn() as c:
        if IS_PG:
            c.execute("INSERT INTO users(telegram_id,username,created_at) VALUES(?,?,?) ON CONFLICT (telegram_id) DO NOTHING",
                      (str(tid), username or "", int(time.time())))
        else:
            c.execute("INSERT OR IGNORE INTO users(telegram_id,username,created_at) VALUES(?,?,?)",
                      (str(tid), username or "", int(time.time())))

def get_user(tid):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE telegram_id=?", (str(tid),)).fetchone()
        return dict(r) if r else None

def set_user_field(tid, field, value):
    with conn() as c:
        c.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, str(tid)))

def save_signal(user_id, sig):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO signals(user_id,symbol,side,entry,stop,target,confidence,thesis,verification,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(user_id), sig["symbol"], sig["side"], sig["entry"], sig["stop"], sig["target"],
             sig["confidence"], sig["thesis"], json.dumps(sig.get("verification", {})), int(time.time())))
        if IS_PG:
            r = c.execute("SELECT currval(pg_get_serial_sequence('signals','id')) AS id").fetchone()
            return r["id"]
        return cur.lastrowid

def save_trade(user_id, signal_id, t):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO trades(user_id,signal_id,symbol,side,qty,entry,stop,target,status,opened_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(user_id), signal_id, t["symbol"], t["side"], t["qty"], t["entry"],
             t["stop"], t["target"], t.get("status","open"), int(time.time())))
        if IS_PG:
            r = c.execute("SELECT currval(pg_get_serial_sequence('trades','id')) AS id").fetchone()
            return r["id"]
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
