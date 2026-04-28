from telegram import (InlineKeyboardButton as B, InlineKeyboardMarkup as K,
                      ReplyKeyboardMarkup, KeyboardButton)
from .config import settings

DIV = "━"*22
THIN = "┈"*22
HERO = ("╭"+"─"*22+"╮\n"
        "│   🔮  *ORACLE-X*         │\n"
        "│   _Trading Intelligence_   │\n"
        "╰"+"─"*22+"╯\n")

WELCOME_NEW = (HERO + DIV + "\nWelcome aboard, *{n