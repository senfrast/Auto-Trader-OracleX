from telegram import (InlineKeyboardButton as B, InlineKeyboardMarkup as K,
                      ReplyKeyboardMarkup, KeyboardButton)
from .config import settings

DIV = "▁"*22
THIN = "┈"*22
HERO = ("╬"+"─"*22+"╮"+"\n"
        "│   🔮  *ORACLE-X*         │\n"
        "│   _Trading Intelligence_   │\n"
        "╰"+"─"*22+"╯"+"\n")

WELCOME_NEW = (HERO + DIV + "\nWelcome aboard, *{n}*. 🤻\n\n"
    "I'm your *AI trading operator*.\n"
    "I scan markets, verify setups, manage risk,\n"
    "and execute on your command — 24/7.\n\n"
    "🧏  Multi-LLM reasoning engine\n"
    "📡  Live market + news intelligence\n"
    "🖡  Built-in risk gates\n"
    "⚡  One-tap paper & live execution\n"
    "🚀  *AUTO-PILOT*  — full hands-off mode\n\n" + THIN +
    "\n👇  *Tap below to enlist.*")

WELCOME_HOME = (HERO + DIV + "\nWelcome back, *{n}*.\n{s}\n" + THIN + "\nChoose your next move ↓")

RISK = ("⚠️  *RISK ACKNOWLEDGEMENT*\n" + DIV +
    "\n• Trading carries *substantial risk of loss*.\n"
    "• Signals are probabilistic research, *not advice*.\n"
    "• You are *solely responsible* for your capital.\n"
    "• Default mode is *PAPER* (simulated).\n\n" + THIN +
    "\nTap *✅ Accept & Join Duty* to activate.")

JOINED = ("✅  *ENLISTED — AGENT ACTIVATED*\n" + DIV +
    "\nYou're on duty, operator. 🤻\n\n"
    "🟢  Oracle engine:   *ONLINE*\n"
    "🟢  Risk gates:      *ARMED*\n"
    "🟢  Mode:            *PAPER*\n"
    "🟢  Agent:           *READY*\n\n" + THIN +
    "\nTap *🚀 Auto-Pilot* for full automation,\nor *🎯 Scan Market* for a single symbol.")

HELP = (HERO + DIV + "\n*Quick Guide*\n\n"
    "🚀  *Auto-Pilot* — full automated research+trade\n"
    "🎯  *Scan Market* — deep oracle analysis\n"
    "🤞  *Ask Agent*  — free-form AI reasoning\n"
    "🧃  *Trending*   — hot symbols\n"
    "📊  *Positions*  — open trades\n"
    "📈  *Status*     — operator dashboard\n"
    "🔌  *APIs*       — connected services\n"
    "⚙️  *Mode*       — paper/live (admin)\n\n" + THIN +
    "\n`/auto` • `/scan SYM` • `/agent ...` • `/apis`\n"
    "`/positions` • `/status` • `/mode` • `/ack` • `/help`")

SYMS = [("₿ BTC","BTC-USD"),("Ξ ETH","ETH-USD"),("◎ SOL","SOL-USD"),
        ("🇺（ SPY","SPY"),("📊 QQQ","QQQ"),
        ("🟢 NVDA","NVDA"),("🚗 TSLA","TSLA"),("🍎 AAPL","AAPL")]

# Watchlist used by Auto-Pilot
AUTOPILOT_WATCHLIST = ["BTC-USD","ETH-USD","SOL-USD","SPY","QQQ","NVDA","TSLA","AAPL","MSFT","META"]

# (label, callback_key, settings_attr_name)  -> presence of attr means "configured"
APIS = [
    ("📨 Telegram",     "telegram",  "TELEGRAM_BOT_TOKEN"),
    ("🧠 OpenAI",       "openai",    "OPENAI_API_KEY"),
    ("🤖 Anthropic",    "anthropic", "ANTHROPIC_API_KEY"),
    ("⚡ Groq",         "groq",      "GROQ_API_KEY"),
    ("📈 Alpaca",       "alpaca",    "ALPACA_KEY"),
    ("🪙 Binance",      "binance",   "BINANCE_KEY"),
    ("📊 AlphaVantage", "alphav",    "ALPHA_VANTAGE_KEY"),
    ("💹 Finnub",      "finnub",    "FINNHUB_KEY"),
    ("🦎 CoinGecko",    "coingecko", "COINGECKO_KEY"),
    ("📰 NewsAPI",      "newsapi",   "NEWSAPI_KEY"),
    ("🐙 GitHub",       "github",    None),    # via integration
    ("☁️ Render",       "render",    None),
    ("🐡 UptimeRobot",  "uptime",    None),
    ("🗄 Database",     "db",        "DATABASE_URL"),
]

def join_kb():
    return K([[B("✅  ACCEPT  &  JOIN  DUTY  🤻", callback_data="ui:ack")],
              [B("📜  Risk Terms", callback_data="ui:risk"),
               B("❓  How it works", callback_data="ui:help")])

def menu_kb(u):
    if not (u and u.get("risk_acknowledged")): return join_kb()
    m = "PAPER" if u.get("paper_mode", 1) else "LIVE"
    ic = "🧴" if m=="PAPER" else "🔔"
    return K([
        [B("🚀  AUTO-PILOT  (full auto)", callback_data="ui:autopilot")],
        [B("🎯  Scan Market", callback_data="ui:scan_menu"),
         B("🧃  Trending", callback_data="ui:trending")],
        [B("🤞  Ask Agent", callback_data="ui:agent_help"),
         B("🔌  APIs", callback_data="ui:apis")],
        [B("📊  Positions", callback_data="ui:positions"),
         B("📈  Status", callback_data="ui:status")],
        [B(f"{ic}  Mode: {m}", callback_data="ui:mode"),
         B("❓  Help", callback_data="ui:help")]])