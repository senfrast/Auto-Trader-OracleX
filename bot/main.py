import asyncio, os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
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

RISK_TEXT = (
    "[WARN] *ORACLE-X RISK ACKNOWLEDGEMENT*\n\n"
    "Trading involves substantial risk of loss. Signals are probabilistic research, not advice. "
    "You are solely responsible for your capital. Default mode is PAPER. "
    "Type /ack to acknowledge and enable signals."
)

async def start(update, ctx):
    u = update.effective_user
    upsert_user(u.id, u.username)
    await update.message.reply_text(
        f"ORACLE-X online.\nHello {u.first_name}.\n\n"
        "Commands:\n"
        "/ack - acknowledge risk\n"
        "/scan SYMBOL - quick oracle scan\n"
        "/agent <free-text> - autonomous agent (tool-use loop)\n"
        "/positions - open trades\n"
        "/mode paper|live - switch mode (admin)\n\n"
        "Or just DM me any question - I run as an agent by default.")

async def help_cmd(update, ctx):
    await update.message.reply_text(RISK_TEXT, parse_mode="Markdown")

async def ack(update, ctx):
    set_user_field(update.effective_user.id, "risk_acknowledged", 1)
    await update.message.reply_text("Risk acknowledged. Signals + agent enabled (paper mode).")

async def mode(update, ctx):
    if str(update.effective_user.id) != str(settings.ADMIN_TELEGRAM_ID):
        await update.message.reply_text("Admins only."); return
    if not ctx.args or ctx.args[0] not in ("paper", "live"):
        await update.message.reply_text("Usage: /mode paper|live"); return
    set_user_field(update.effective_user.id, "paper_mode", 1 if ctx.args[0] == "paper" else 0)
    await update.message.reply_text(f"Mode set: {ctx.args[0]}")

def _fmt_signal(sig):
    v = sig.get("verification", {}) or {}
    return (f"*{sig['symbol']}* - *{sig['side'].upper()}*\n"
            f"Entry: `{sig.get('entry')}`  Stop: `{sig.get('stop')}`  Target: `{sig.get('target')}`\n"
            f"Confidence: *{sig.get('confidence',0):.2f}*  R: {sig.get('r_multiple','?')}\n"
            f"Thesis: {sig.get('thesis','')[:400]}\n"
            f"Verify: price={v.get('price_confirms')} vol={v.get('volume_confirms')} news_risk={v.get('news_risk')}\n"
            f"Notes: {sig.get('notes','')[:200]}")

async def _require_ack(update):
    user = get_user(update.effective_user.id)
    if not user or not user.get("risk_acknowledged"):
        await update.message.reply_text(RISK_TEXT, parse_mode="Markdown"); return False
    return True

async def scan(update, ctx):
    u = update.effective_user
    if not await _require_ack(update): return
    if not ctx.args:
        await update.message.reply_text("Usage: /scan SYMBOL"); return
    symbol = ctx.args[0].upper()
    await update.message.reply_text(f"ORACLE-X scanning {symbol}...")
    md = await asyncio.to_thread(get_context, symbol)
    md["headlines"] = await asyncio.to_thread(fetch_headlines, symbol)
    sig = await asyncio.to_thread(analyze, md)
    ok, reason = check_gates(u.id, sig)
    sig_id = save_signal(u.id, {**sig, "thesis": sig.get("thesis", "")[:1000]})
    journal(u.id, "signal", {"symbol": symbol, "ok": ok, "reason": reason, "sig": sig})
    msg = _fmt_signal(sig) + f"\n\nGate: *{'PASS' if ok else 'BLOCK'}* - {reason}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Execute (paper)", callback_data=f"exec:{sig_id}")]]) if ok else None
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

async def agent_cmd(update, ctx):
    if not await _require_ack(update): return
    prompt = " ".join(ctx.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /agent <question or instruction>"); return
    await _run_agent_reply(update, prompt)

async def free_text(update, ctx):
    if update.message is None or not update.message.text: return
    if update.message.text.startswith("/"): return
    if not await _require_ack(update): return
    await _run_agent_reply(update, update.message.text.strip())

async def _run_agent_reply(update, prompt):
    u = update.effective_user
    await update.message.chat.send_action(action="typing")
    thinking = await update.message.reply_text("Agent thinking...")
    try:
        answer, trace = await run_agent(u.id, prompt)
    except Exception as e:
        log.exception("agent crashed: %s", e)
        await thinking.edit_text(f"Agent error: {e}"); return
    tool_log = " -> ".join(t.split("(")[0] for t in trace[-6:]) or "no tools"
    body = (answer[:3800] if answer else "(empty)") + f"\n\n_tools: {tool_log}_"
    try:
        await thinking.edit_text(body, parse_mode="Markdown")
    except Exception:
        await thinking.edit_text(body)

async def on_callback(update, ctx):
    q = update.callback_query; await q.answer()
    data = q.data or ""
    if data.startswith("exec:"):
        sig_id = int(data.split(":")[1])
        user = get_user(q.from_user.id) or {"equity": 10000}
        from .database import conn
        with conn() as c:
            r = c.execute("SELECT * FROM signals WHERE id=?", (sig_id,)).fetchone()
        if not r: await q.edit_message_text("Signal not found."); return
        sig = dict(r)
        qty = position_size(float(user.get("equity", 10000)), float(sig["entry"]), float(sig["stop"]))
        if qty <= 0: await q.edit_message_text("Invalid size - aborted."); return
        broker = get_broker()
        trade_id = broker.place(q.from_user.id, sig_id, sig, qty)
        await q.edit_message_text(f"Order sent via {broker.name}. qty={qty} trade_id={trade_id}")

async def positions(update, ctx):
    rows = list_open_trades(update.effective_user.id)
    if not rows: await update.message.reply_text("No open positions."); return
    lines = [f"#{r['id']} {r['symbol']} {r['side']} qty={r['qty']} @ {r['entry']}  stop={r['stop']} tgt={r['target']}" for r in rows]
    await update.message.reply_text("Open positions:\n" + "\n".join(lines))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"oracle-x"}')
    def log_message(self, *a, **k): pass

def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    srv = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info("Health server listening on :%s", port)
    srv.serve_forever()

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
    app.add_handler(CommandHandler("agent", agent_cmd))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    return app

def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    app = build_app()
    log.info("ORACLE-X starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
