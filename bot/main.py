import asyncio, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from .config import settings
from .database import (init_db, upsert_user, get_user, set_user_field,
                       save_signal, list_open_trades, journal)
from .logger import get_logger
from .market_data import get_context
from .news import fetch_headlines
from .oracle import analyze
from .risk import check_gates, position_size
from .execution import get_broker

log = get_logger(__name__)

RISK_TEXT = (
    "⚠️ *ORACLE-X RISK ACKNOWLEDGEMENT*\n\n"
    "Trading involves substantial risk of loss. Signals are probabilistic research, not advice. "
    "You are solely responsible for your capital. Default mode is PAPER. "
    "Type /ack to acknowledge and enable signals."
)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username)
    await update.message.reply_text(
        f"🔮 ORACLE-X online.\nHello {u.first_name}.\n\n"
        "Commands:\n"
        "/ack — acknowledge risk\n"
        "/scan SYMBOL — run oracle on a ticker (e.g. /scan AAPL, /scan BTC)\n"
        "/positions — list open paper trades\n"
        "/mode paper|live — switch mode (admin)\n"
        "/help")

async def help_cmd(update: Update, ctx):
    await update.message.reply_text(RISK_TEXT, parse_mode="Markdown")

async def ack(update: Update, ctx):
    set_user_field(update.effective_user.id, "risk_acknowledged", 1)
    await update.message.reply_text("✅ Risk acknowledged. Signals enabled (paper mode).")

async def mode(update: Update, ctx):
    if str(update.effective_user.id) != str(settings.ADMIN_TELEGRAM_ID):
        await update.message.reply_text("Admins only."); return
    if not ctx.args or ctx.args[0] not in ("paper", "live"):
        await update.message.reply_text("Usage: /mode paper|live"); return
    set_user_field(update.effective_user.id, "paper_mode", 1 if ctx.args[0] == "paper" else 0)
    await update.message.reply_text(f"Mode set: {ctx.args[0]}")

def _fmt_signal(sig: dict) -> str:
    v = sig.get("verification", {})
    return (f"*{sig['symbol']}* — *{sig['side'].upper()}*\n"
            f"Entry: `{sig.get('entry')}`  Stop: `{sig.get('stop')}`  Target: `{sig.get('target')}`\n"
            f"Confidence: *{sig.get('confidence',0):.2f}*  R: {sig.get('r_multiple','?')}\n"
            f"Thesis: {sig.get('thesis','')[:400]}\n"
            f"Verify: price={v.get('price_confirms')} vol={v.get('volume_confirms')} "
            f"news_risk={v.get('news_risk')}\n"
            f"Notes: {sig.get('notes','')[:200]}")

async def scan(update: Update, ctx):
    u = update.effective_user
    user = get_user(u.id)
    if not user or not user.get("risk_acknowledged"):
        await update.message.reply_text(RISK_TEXT, parse_mode="Markdown"); return
    if not ctx.args:
        await update.message.reply_text("Usage: /scan SYMBOL"); return
    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"🔍 ORACLE-X scanning {symbol}...")
    md = await asyncio.to_thread(get_context, symbol)
    md["headlines"] = await asyncio.to_thread(fetch_headlines, symbol)
    sig = await asyncio.to_thread(analyze, md)
    ok, reason = check_gates(u.id, sig)
    sig_id = save_signal(u.id, {**sig, "thesis": sig.get("thesis", "")[:1000]})
    journal(u.id, "signal", {"symbol": symbol, "ok": ok, "reason": reason, "sig": sig})
    msg = _fmt_signal(sig) + f"\n\nGate: *{'PASS' if ok else 'BLOCK'}* — {reason}"
    kb = None
    if ok:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Execute (paper)", callback_data=f"exec:{sig_id}")]])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

async def on_callback(update: Update, ctx):
    q = update.callback_query; await q.answer()
    data = q.data or ""
    if data.startswith("exec:"):
        sig_id = int(data.split(":")[1])
        user = get_user(q.from_user.id) or {"equity": 10000}
        from .database import conn
        with conn() as c:
            r = c.execute("SELECT * FROM signals WHERE id=?", (sig_id,)).fetchone()
        if not r:
            await q.edit_message_text("Signal not found."); return
        sig = dict(r)
        qty = position_size(float(user.get("equity", 10000)), float(sig["entry"]), float(sig["stop"]))
        if qty <= 0:
            await q.edit_message_text("Invalid size — aborted."); return
        broker = get_broker()
        trade_id = broker.place(q.from_user.id, sig_id, sig, qty)
        await q.edit_message_text(f"✅ Order sent via {broker.name}. qty={qty} trade_id={trade_id}")

async def positions(update: Update, ctx):
    rows = list_open_trades(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No open positions."); return
    lines = [f"#{r['id']} {r['symbol']} {r['side']} qty={r['qty']} @ {r['entry']}  stop={r['stop']} tgt={r['target']}"
             for r in rows]
    await update.message.reply_text("Open positions:\n" + "\n".join(lines))

def build_app():
    init_db()
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN required")
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ack", ack))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app

def main():
    app = build_app()
    log.info("🔮 ORACLE-X starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
