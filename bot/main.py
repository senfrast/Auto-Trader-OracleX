import asyncio, os, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, KeyboardButton, BotCommand,
                      MenuButtonCommands)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          CallbackQueryHandler, MessageHandler, filters)
from .config import settings
from .database import (init_db, upsert_user, get_user, set_user_field,
                       save_signal, list_open_trades, journal)
from .logger import get_logger
from .market_data import get_context
from .news import fetch_headlines
from .oracle import analyze
from .risk import check_gates, position_size
from .execution import get_broker
from .agent import run_agent

log = get_logger(__name__)

BRAND     = "🔮 ORACLE-X"
TAGLINE   = "Autonomous Trading Intelligence"
DIV       = "━━━━━━━━━━━━━━━━━━━━━━"
THIN      = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
DOT_ON    = "🟢"
DOT_OFF   = "⚪️"
DOT_WARN  = "🟡"

HERO = (
    "╭──────────────────────╮\n"
    "│   🔮  *ORACLE-X*         │\n"
    "│   _Trading Intelligence_   │\n"
    "╰──────────────────────╯\n"
)

WELCOME_NEW = (
    f"{HERO}"
    f"{DIV}\n"
    "Welcome aboard, *{name}*. 🫡\n\n"
    "I'm your *AI trading operator*.\n"
    "I scan markets, verify setups, manage risk,\n"
    "and execute on your command — 24/7.\n\n"
    "🧠  Multi-LLM reasoning engine\n"
    "📡  Live market + news intelligence\n"
    "🛡  Built-in risk gates\n"
    "⚡  One-tap paper & live execution\n\n"
    f"{THIN}\n"
    "👇  *Tap below to enlist.*"
)

WELCOME_HOME = (
    f"{HERO}"
    f"{DIV}\n"
    "Welcome back, *{name}*.\n"
    "{status_line}\n"
    f"{THIN}\n"
    "Choose your next move ↓"
)

RISK_CARD = (
    "⚠️  *RISK ACKNOWLEDGEMENT*\n"
    f"{DIV}\n"
    "• Trading carries *substantial risk of loss*.\n"
    "• Signals are probabilistic research,\n"
    "  *not financial advice*.\n"
    "• You are *solely responsible* for your capital.\n"
    "• Default mode is *PAPER* (simulated).\n\n"
    f"{THIN}\n"
    "Tap *✅ Accept & Join Duty* to activate."
)

JOINED = (
    "✅  *ENLISTED — AGENT ACTIVATED*\n"
    f"{DIV}\n"
    "You're on duty, operator. 🫡\n\n"
    "🟢  Oracle engine:   *ONLINE*\n"
    "🟢  Risk gates:      *ARMED*\n"
    "🟢  Mode:            *PAPER*\n"
    "🟢  Agent:           *READY*\n\n"
    f"{THIN}\n"
    "Tap *🎯 Scan Market* or just send me a message."
)

def join_duty_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  ACCEPT  &  JOIN  DUTY  🫡", callback_data="ui:ack")],
        [InlineKeyboardButton("📜  Read Risk Terms",           callback_data="ui:risk"),
         InlineKeyboardButton("❓  How it works",              callback_data="ui:help")],
    ])

def main_menu_kb(user):
    acked = bool(user and user.get("risk_acknowledged"))
    if not acked:
        return join_duty_kb()
    mode = "PAPER" if (not user or user.get("paper_mode", 1)) else "LIVE"
    mode_icon = "🧪" if mode == "PAPER" else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯  Scan Market",        callback_data="ui:scan_menu")],
        [InlineKeyboardButton("🤖  Ask Agent",          callback_data="ui:agent_help"),
         InlineKeyboardButton("🧠  Trending",           callback_data="ui:trending")],
        [InlineKeyboardButton("📊  Positions",          callback_data="ui:positions"),
         InlineKeyboardButton("📈  Status",             callback_data="ui:status")],
        [InlineKeyboardButton(f"{mode_icon}  Mode: {mode}", callback_data="ui:mode"),
         InlineKeyboardButton("❓  Help",               callback_data="ui:help")],
    ])

def persistent_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🎯 Scan"), KeyboardButton("🤖 Agent")],
         [KeyboardButton("📊 Positions"), KeyboardButton("📈 Status")],
         [KeyboardButton("🏠 Menu")]],
        resize_keyboard=True, is_persistent=True,
    )

SCAN_UNIVERSE = [
    ("₿ BTC",  "BTC-USD"), ("Ξ ETH",  "ETH-USD"),
    ("◎ SOL",  "SOL-USD"), ("🇺🇸 SPY",  "SPY"),
    ("📊 QQQ", "QQQ"),     ("🟢 NVDA", "NVDA"),
    ("🚗 TSLA", "TSLA"),   ("🍎 AAPL", "AAPL"),
]

def scan_menu_kb():
    rows, row = [], []
    for label, sym in SCAN_UNIVERSE:
        row.append(InlineKeyboardButton(label, callback_data=f"scan:{sym}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("✏️  Custom symbol", callback_data="ui:scan_custom")])
    rows.append([InlineKeyboardButton("⬅️  Back",          callback_data="ui:home")])
    return InlineKeyboardMarkup(rows)

def back_home_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠  Main Menu", callback_data="ui:home")]])

def post_scan_kb(symbol, sig_id=None, ok=False):
    rows = []
    if ok and sig_id is not None:
        rows.append([InlineKeyboardButton("⚡  Execute Trade", callback_data=f"exec:{sig_id}")])
    rows.append([
        InlineKeyboardButton("🔁  Re-scan", callback_data=f"scan:{symbol}"),
        InlineKeyboardButton("🎯  New symbol", callback_data="ui:scan_menu"),
    ])
    rows.append([InlineKeyboardButton("🏠  Main Menu", callback_data="ui:home")])
    return InlineKeyboardMarkup(rows)
