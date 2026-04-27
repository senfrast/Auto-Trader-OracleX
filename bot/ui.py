from telegram import (InlineKeyboardButton as B, InlineKeyboardMarkup as K,
                      ReplyKeyboardMarkup, KeyboardButton)
from .config import settings

DIV = "━"*22
THIN = "┈"*22
HERO = ("╭"+"─"*22+"╮\n"
        "│   🔮  *ORACLE-X*         │\n"
        "│   _Trading Intelligence_   │\n"
        "╰"+"─"*22+"╯\n")

WELCOME_NEW = (HERO + DIV + "\nWelcome aboard, *{n}*. 🫡\n\n"
    "I'm your *AI trading operator*.\n"
    "I scan markets, verify setups, manage risk,\n"
    "and execute on your command — 24/7.\n\n"
    "🧠  Multi-LLM reasoning engine\n"
    "📡  Live market + news intelligence\n"
    "🛡  Built-in risk gates\n"
    "⚡  One-tap paper & live execution\n"
    "🚀  *AUTO-PILOT* — full hands-off mode\n\n" + THIN +
    "\n👇  *Tap below to enlist.*")