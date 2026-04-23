from telegram import (InlineKeyboardButton as B, InlineKeyboardMarkup as K,
                      ReplyKeyboardMarkup, KeyboardButton)

DIV = "━"*22
THIN = "┈"*22
HERO = ("╭"+"─"*22+"╮\n"
        "│   🔮  *ORACLE-X*         │\n"
        "│   _Trading Intelligence_   │\n"
        "╰"+"─"*22+"╯\n")

WELCOME_NEW = (HERO + DIV + "\nWelcome aboard, *{n}*. 🪡\n\n"
    "I'm your *AI trading operator*.\n"
    "I scan markets, verify setups, manage risk,\n"
    "and execute on your command — 24/7.\n\n"
    "🧠  Multi-LLM reasoning engine\n"
    "📡  Live market + news intelligence\n"
    "🛡  Built-in risk gates\n"
    "⚡  One-tap paper & live execution\n\n" + THIN +
    "\n👇  *Tap below to enlist.*")

WELCOME_HOME = (HERO + DIV + "\nWelcome back, *{n}*.\n{s}\n" + THIN + "\nChoose your next move ↓")

RISK = ("⚠️  *RISK ACKNOWLEDGEMENT*\n" + DIV +
    "\n• Trading carries *substantial risk of loss*.\n"
    "• Signals are probabilistic research, *not advice*.\n"
    "• You are *solely responsible* for your capital.\n"
    "• Default mode is *PAPER* (simulated).\n\n" + THIN +
    "\nTap *✅ Accept & Join Duty* to activate.")

JOINED = ("✅  *ENLISTED — AGENT ACTIVATED*\n" + DIV +
    "\nYou're on duty, operator. 🪡\n\n"
    "🟢  Oracle engine:   *ONLINE*\n"
    "🟢  Risk gates:      *ARMED*\n"
    "🟢  Mode:            *PAPER*\n"
    "🟢  Agent:           *READY*\n\n" + THIN +
    "\nTap *🎯 Scan Market* or just send me a message.")

HELP = (HERO + DIV + "\n*Quick Guide*\n\n"
    "🎯  *Scan Market* — deep oracle analysis\n"
    "🤖  *Ask Agent*  — free-form AI reasoning\n"
    "🧠  *Trending*   — hot symbols\n"
    "📊  *Positions*  — open trades\n"
    "📈  *Status*     — operator dashboard\n"
    "⚙️  *Mode*       — paper/live (admin)\n\n" + THIN +
    "\n`/scan SYM` • `/agent ...` • `/positions`\n"
    "`/status` • `/mode` • `/ack` • `/help`\n\n"
    "💬 _Just message me anything — I'll reason as an agent._")

SYMS = [("₿ BTC","BTC-USD"),("Ξ ETH","ETH-USD"),("◎ SOL","SOL-USD"),
        ("🇺🇸 SPY","SPY"),("📊 QQQ","QQQ"),
        ("🟢 NVDA","NVDA"),("🚗 TSLA","TSLA"),("🍎 AAPL","AAPL")]

def join_kb():
    return K([[B("✅  ACCEPT  &  JOIN  DUTY  🪡", callback_data="ui:ack")],
              [B("📜  Risk Terms", callback_data="ui:risk"),
               B("❓  How it works", callback_data="ui:help")]])

def menu_kb(u):
    if not (u and u.get("risk_acknowledged")): return join_kb()
    m = "PAPER" if u.get("paper_mode", 1) else "LIVE"
    ic = "🧪" if m=="PAPER" else "🔴"
    return K([[B("🎯  Scan Market", callback_data="ui:scan_menu")],
              [B("🤖  Ask Agent", callback_data="ui:agent_help"),
               B("🧠  Trending", callback_data="ui:trending")],
              [B("📊  Positions", callback_data="ui:positions"),
               B("📈  Status", callback_data="ui:status")],
              [B(f"{ic}  Mode: {m}", callback_data="ui:mode"),
               B("❓  Help", callback_data="ui:help")]])

def persistent_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🎯 Scan"), KeyboardButton("🤖 Agent")],
         [KeyboardButton("📊 Positions"), KeyboardButton("📈 Status")],
         [KeyboardButton("🏠 Menu")]], resize_keyboard=True, is_persistent=True)

def scan_kb():
    rows, row = [], []
    for lbl, s in SYMS:
        row.append(B(lbl, callback_data=f"scan:{s}"))
        if len(row)==2: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([B("✏️  Custom symbol", callback_data="ui:scan_custom")])
    rows.append([B("⬅️  Back", callback_data="ui:home")])
    return K(rows)

def home_kb():
    return K([[B("🏠  Main Menu", callback_data="ui:home")]])

def post_kb(sym, sid=None, ok=False):
    r = []
    if ok and sid is not None:
        r.append([B("⚡  Execute Trade", callback_data=f"exec:{sid}")])
    r.append([B("🔁  Re-scan", callback_data=f"scan:{sym}"),
              B("🎯  New symbol", callback_data="ui:scan_menu")])
    r.append([B("🏠  Main Menu", callback_data="ui:home")])
    return K(r)

def sline(u):
    if not (u and u.get("risk_acknowledged")): return "⚪️ Standby — not enlisted"
    m = "PAPER" if u.get("paper_mode", 1) else "LIVE"
    return f"🟢 On duty  •  Mode *{m}*  •  Equity `${u.get('equity',10000)}`"
