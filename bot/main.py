import asyncio, os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, filters)
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
from .ui import (DIV, THIN, HERO, WELCOME_NEW, WELCOME_HOME, RISK, JOINED, HELP,
                 join_kb, menu_kb, persistent_kb, scan_kb, home_kb, post_kb, sline)

log = get_logger(__name__)
MD = ParseMode.MARKDOWN

async def _safe(q, t, **kw):
    try: await q.edit_message_text(t, **kw)
    except Exception: kw.pop("parse_mode",None); await q.edit_message_text(t, **kw)

async def start(update, ctx):
    u = update.effective_user
    upsert_user(u.id, u.username)
    usr = get_user(u.id); n = u.first_name or "Operator"
    t = WELCOME_HOME.format(n=n, s=sline(usr)) if (usr and usr.get("risk_acknowledged")) else WELCOME_NEW.format(n=n)
    await update.message.reply_text(t, parse_mode=MD, reply_markup=menu_kb(usr))
    await update.message.reply_text("⌨️  Quick actions ready below.", reply_markup=persistent_kb())

async def _help(send):
    await send(HELP, parse_mode=MD, reply_markup=home_kb())

async def help_cmd(update, ctx): await _help(update.message.reply_text)

async def ack(update, ctx):
    set_user_field(update.effective_user.id, "risk_acknowledged", 1)
    await update.message.reply_text(JOINED, parse_mode=MD, reply_markup=menu_kb(get_user(update.effective_user.id)))

async def mode(update, ctx):
    if str(update.effective_user.id) != str(settings.ADMIN_TELEGRAM_ID):
        await update.message.reply_text("⛔ Admins only."); return
    if not ctx.args or ctx.args[0] not in ("paper","live"):
        await update.message.reply_text("Usage: `/mode paper|live`", parse_mode=MD); return
    set_user_field(update.effective_user.id, "paper_mode", 1 if ctx.args[0]=="paper" else 0)
    await update.message.reply_text(f"⚙️ Mode: *{ctx.args[0].upper()}*", parse_mode=MD)

def _fmt(sig):
    v = sig.get("verification",{}) or {}
    side = sig.get("side","?").upper()
    arr = "🟢 ⬆️ LONG" if side=="LONG" else ("🔴 ⬇️ SHORT" if side=="SHORT" else "⚪️ FLAT")
    c = float(sig.get("confidence",0) or 0); f = int(round(c*10))
    bars = "▓"*f + "░"*(10-f)
    chk = lambda x: "✅" if x is True else ("❌" if x is False else "•")
    return (f"*{sig['symbol']}*   {arr}\n" + DIV +
            f"\n🎯  Entry   `{sig.get('entry')}`\n"
            f"🛡  Stop    `{sig.get('stop')}`\n"
            f"🏁  Target  `{sig.get('target')}`\n"
            f"📊  Conf    `{bars}` *{c:.0%}*\n"
            f"⚖️  R-mult  `{sig.get('r_multiple','?')}`\n" + THIN +
            f"\n💡  *Thesis*\n_{sig.get('thesis','')[:380]}_\n\n"
            f"🔎  *Verification*\n"
            f"  {chk(v.get('price_confirms'))} Price confirms\n"
            f"  {chk(v.get('volume_confirms'))} Volume confirms\n"
            f"  {chk(not v.get('news_risk'))} News risk clear")

async def _req_ack(x):
    uid = x.effective_user.id if hasattr(x,"effective_user") else x.from_user.id
    u = get_user(uid)
    if not u or not u.get("risk_acknowledged"):
        send = x.message.reply_text if hasattr(x,"message") and x.message else x.edit_message_text
        await send(RISK, parse_mode=MD, reply_markup=join_kb())
        return False
    return True

async def _scan(send, uid, sym, chat=None):
    if chat:
        try: await chat.send_action(action=ChatAction.TYPING)
        except Exception: pass
    msg = await send(f"🔎  *Scanning {sym}*\n_pulling market data..._", parse_mode=MD)
    try:
        md = await asyncio.to_thread(get_context, sym)
        try: await msg.edit_text(f"🔎  *Scanning {sym}*\n_fetching headlines..._", parse_mode=MD)
        except Exception: pass
        md["headlines"] = await asyncio.to_thread(fetch_headlines, sym)
        try: await msg.edit_text(f"🧠  *Oracle reasoning on {sym}*", parse_mode=MD)
        except Exception: pass
        sig = await asyncio.to_thread(analyze, md)
        ok, reason = check_gates(uid, sig)
        sid = save_signal(uid, {**sig, "thesis": sig.get("thesis","")[:1000]})
        journal(uid, "signal", {"symbol":sym,"ok":ok,"reason":reason,"sig":sig})
        body = _fmt(sig) + f"\n{THIN}\n🚦  Gate:  *{'✅ PASS' if ok else '⛔ BLOCK'}*\n_{reason}_"
        try: await msg.edit_text(body, parse_mode=MD, reply_markup=post_kb(sym, sid, ok))
        except Exception: await msg.edit_text(body, reply_markup=post_kb(sym, sid, ok))
    except Exception as e:
        log.exception("scan"); await msg.edit_text(f"⚠️ Scan failed: `{e}`", parse_mode=MD, reply_markup=home_kb())

async def scan_cmd(update, ctx):
    if not await _req_ack(update): return
    if not ctx.args:
        await update.message.reply_text("🎯  *Select a market:*", parse_mode=MD, reply_markup=scan_kb()); return
    await _scan(update.message.reply_text, update.effective_user.id, ctx.args[0].upper(), update.message.chat)

async def agent_cmd(update, ctx):
    if not await _req_ack(update): return
    p = " ".join(ctx.args).strip()
    if not p:
        await update.message.reply_text("🤖  *Agent Ready*\n" + DIV +
            "\nSend any question:\n• `Analyze NVDA`\n• `Any SPY news risk?`",
            parse_mode=MD, reply_markup=home_kb()); return
    await _agent(update, p)

async def _agent(x, p):
    if hasattr(x,"message") and x.message:
        chat, reply, uid = x.message.chat, x.message.reply_text, x.effective_user.id
    else:
        chat, reply, uid = x.message.chat, x.message.reply_text, x.from_user.id
    try: await chat.send_action(action=ChatAction.TYPING)
    except Exception: pass
    th = await reply("🧠  _Agent reasoning..._", parse_mode=MD)
    try:
        ans, trace = await run_agent(uid, p)
    except Exception as e:
        log.exception("agent"); await th.edit_text(f"⚠️ Agent error: `{e}`", parse_mode=MD); return
    tl = " → ".join(t.split("(")[0] for t in trace[-6:]) or "no tools"
    body = (ans[:3800] if ans else "_(empty)_") + f"\n\n{THIN}\n🛠 _{tl}_"
    try: await th.edit_text(body, parse_mode=MD, reply_markup=home_kb())
    except Exception: await th.edit_text(body, reply_markup=home_kb())

SC = {"🎯 scan":"scan","🤖 agent":"agent","📊 positions":"pos",
      "📈 status":"stat","🏠 menu":"menu","❓ menu":"menu"}

async def free_text(update, ctx):
    if not update.message or not update.message.text: return
    t = update.message.text.strip()
    if t.startswith("/"): return
    low = t.lower()
    if low in SC:
        a = SC[low]; u = get_user(update.effective_user.id)
        if a == "scan":
            if not await _req_ack(update): return
            await update.message.reply_text("🎯  *Select a market:*", parse_mode=MD, reply_markup=scan_kb()); return
        if a == "pos": await positions(update, ctx); return
        if a == "stat": await status_cmd(update, ctx); return
        if a == "menu":
            n = update.effective_user.first_name or "Operator"
            msg = WELCOME_HOME.format(n=n, s=sline(u)) if (u and u.get("risk_acknowledged")) else WELCOME_NEW.format(n=n)
            await update.message.reply_text(msg, parse_mode=MD, reply_markup=menu_kb(u)); return
        if a == "agent":
            await update.message.reply_text("🤖  *Agent Ready* — send your question.", parse_mode=MD, reply_markup=home_kb()); return
    if not await _req_ack(update): return
    await _agent(update, t)

async def on_cb(update, ctx):
    q = update.callback_query; await q.answer()
    d = q.data or ""; uid = q.from_user.id; name = q.from_user.first_name or "Operator"
    if d == "ui:home":
        upsert_user(uid, q.from_user.username); u = get_user(uid)
        t = WELCOME_HOME.format(n=name, s=sline(u)) if (u and u.get("risk_acknowledged")) else WELCOME_NEW.format(n=name)
        await _safe(q, t, parse_mode=MD, reply_markup=menu_kb(u)); return
    if d == "ui:ack":
        await q.answer("✅ Enlisted. Agent activated.")
        set_user_field(uid, "risk_acknowledged", 1)
        await _safe(q, JOINED, parse_mode=MD, reply_markup=menu_kb(get_user(uid))); return
    if d == "ui:risk":
        await _safe(q, RISK, parse_mode=MD, reply_markup=menu_kb(get_user(uid))); return
    if d == "ui:help": await _help(q.edit_message_text); return
    if d == "ui:scan_menu":
        if not await _req_ack(q): return
        await _safe(q, "🎯  *Select a market:*", parse_mode=MD, reply_markup=scan_kb()); return
    if d == "ui:scan_custom":
        await _safe(q, "✏️  *Custom Symbol*\n" + DIV + "\nSend: `/scan SYMBOL`\nex: `/scan MSFT`",
                    parse_mode=MD, reply_markup=home_kb()); return
    if d == "ui:positions":
        rows = list_open_trades(uid)
        if not rows:
            t = f"📊  *Open Positions*\n{DIV}\n_No open positions yet._\n\nRun a 🎯 Scan."
        else:
            ls = [f"• `#{r['id']}`  *{r['symbol']}*  {r['side'].upper()}\n"
                  f"   qty `{r['qty']}` @ `{r['entry']}`\n"
                  f"   🛡 `{r['stop']}`   🏁 `{r['target']}`" for r in rows]
            t = f"📊  *Open Positions* ({len(rows)})\n{DIV}\n" + "\n\n".join(ls)
        await _safe(q, t, parse_mode=MD, reply_markup=home_kb()); return
    if d == "ui:status":
        u = get_user(uid) or {}
        a = "🟢" if u.get("risk_acknowledged") else "⚪️"
        m = "PAPER" if u.get("paper_mode",1) else "LIVE"
        md_ = "🟡" if m=="LIVE" else "🟢"
        t = (f"📈  *Operator Dashboard*  —  {name}\n{DIV}\n"
             f"{a}  Enlisted\n{md_}  Mode:  *{m}*\n"
             f"💰  Equity:  `${u.get('equity',10000)}`\n"
             f"📦  Open trades:  *{len(list_open_trades(uid))}*\n"
             f"🛡  Risk gates:  *ARMED*\n🧠  Oracle:  *ONLINE*")
        await _safe(q, t, parse_mode=MD, reply_markup=home_kb()); return
    if d == "ui:mode":
        if str(uid) != str(settings.ADMIN_TELEGRAM_ID):
            await _safe(q, "⛔ *Admins only.*", parse_mode=MD, reply_markup=home_kb()); return
        u = get_user(uid) or {}; new = 0 if u.get("paper_mode",1) else 1
        set_user_field(uid, "paper_mode", new)
        lbl = "PAPER" if new else "LIVE"; ic = "🧪" if new else "🔴"
        await _safe(q, f"{ic}  *Mode → {lbl}*\n{DIV}\n" +
                    ("_Simulated trades only._" if new else "*⚠️ LIVE trading enabled.*"),
                    parse_mode=MD, reply_markup=menu_kb(get_user(uid))); return
    if d == "ui:trending":
        t = (f"🧠  *Trending Watchlist*\n{DIV}\n"
             "🟢  BTC-USD   _strong momentum_\n"
             "🟢  ETH-USD   _breakout watch_\n"
             "🟡  NVDA      _consolidation_\n"
             "🟡  SPY       _range-bound_\n"
             "🔴  TSLA      _weakening_\n\n" + THIN +
             "\n_Tap 🎯 Scan Market to deep-analyze._")
        await _safe(q, t, parse_mode=MD, reply_markup=home_kb()); return
    if d == "ui:agent_help":
        await _safe(q, f"🤖  *Agent Mode*\n{DIV}\nJust *type your question*.\n\n"
                    "*Try:*\n• `Analyze NVDA swing long`\n• `News risk on SPY?`\n• `BTC vs ETH setup`",
                    parse_mode=MD, reply_markup=home_kb()); return
    if d.startswith("scan:"):
        if not await _req_ack(q): return
        s = d.split(":",1)[1]
        await _safe(q, f"🔎  *Scanning {s}*\n_initializing oracle..._", parse_mode=MD)
        await _scan(q.message.reply_text, uid, s, q.message.chat); return
    if d.startswith("exec:"):
        sid = int(d.split(":")[1])
        u = get_user(uid) or {"equity":10000}
        from .database import conn
        with conn() as c:
            r = c.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
        if not r: await _safe(q, "⚠️ Signal not found.", reply_markup=home_kb()); return
        sig = dict(r)
        qty = position_size(float(u.get("equity",10000)), float(sig["entry"]), float(sig["stop"]))
        if qty <= 0:
            await _safe(q, "⚠️ *Invalid size — aborted.*", parse_mode=MD, reply_markup=home_kb()); return
        br = get_broker(); tid = br.place(uid, sid, sig, qty)
        await _safe(q, f"⚡  *ORDER SENT*   via {br.name}\n{DIV}\n"
                    f"📈  Symbol:  *{sig['symbol']}*\n📊  Side:    *{sig['side'].upper()}*\n"
                    f"📦  Qty:     `{qty}`\n🖔  Trade:   `{tid}`\n\n{THIN}\n_Tracking in 📊 Positions._",
                    parse_mode=MD, reply_markup=home_kb()); return

async def positions(update, ctx):
    rows = list_open_trades(update.effective_user.id)
    if not rows:
        await update.message.reply_text(f"📊 *Open Positions*\n{DIV}\n_None yet._",
                                        parse_mode=MD, reply_markup=home_kb()); return
    ls = [f"• `#{r['id']}` *{r['symbol']}* {r['side'].upper()}  qty `{r['qty']}` @ `{r['entry']}`\n"
          f"  🛡 `{r['stop']}` 🏁 `{r['target']}`" for r in rows]
    await update.message.reply_text(f"📊 *Open Positions* ({len(rows)})\n{DIV}\n" + "\n\n".join(ls),
                                    parse_mode=MD, reply_markup=home_kb())

async def status_cmd(update, ctx):
    uid = update.effective_user.id; u = get_user(uid) or {}
    n = update.effective_user.first_name or "Operator"
    a = "🟢" if u.get("risk_acknowledged") else "⚪️"
    m = "PAPER" if u.get("paper_mode",1) else "LIVE"
    md_ = "🟡" if m=="LIVE" else "🟢"
    t = (f"📈  *Operator Dashboard*  —  {n}\n{DIV}\n"
         f"{a}  Enlisted\n{md_}  Mode:  *{m}*\n"
         f"💰  Equity:  `${u.get('equity',10000)}`\n"
         f"📦  Open trades:  *{len(list_open_trades(uid))}*\n"
         f"🛡  Risk gates:  *ARMED*\n🧠  Oracle:  *ONLINE*")
    await update.message.reply_text(t, parse_mode=MD, reply_markup=menu_kb(u))

class H(BaseHTTPRequestHandler):
    def do_GET(s):
        s.send_response(200); s.send_header("Content-Type","application/json"); s.end_headers()
        s.wfile.write(b'{"status":"ok","service":"oracle-x"}')
    def log_message(s,*a,**k): pass

def health():
    HTTPServer(("0.0.0.0", int(os.getenv("PORT","10000"))), H).serve_forever()

async def _post(app):
    try:
        await app.bot.set_my_commands([
            BotCommand("start","🏠 Open main menu"),
            BotCommand("scan","🎯 Scan a symbol"),
            BotCommand("agent","🤖 Ask the agent"),
            BotCommand("positions","📊 Open positions"),
            BotCommand("status","📈 Account status"),
            BotCommand("ack","✅ Accept risk & join duty"),
            BotCommand("mode","⚙️ Switch paper/live (admin)"),
            BotCommand("help","❓ Help")])
        try: await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        except Exception: pass
        try:
            await app.bot.set_my_short_description("🔮 Oracle-X — AI trading operator. One tap to join duty.")
            await app.bot.set_my_description("🔮 ORACLE-X — Autonomous Trading Intelligence.\n\n"
                "• AI oracle scans markets & news\n• Built-in risk gates\n"
                "• One-tap paper & live execution\n• Free-form agent: message anything.\n\nTap START to enlist.")
        except Exception: pass
    except Exception as e: log.warning("post_init: %s", e)

def build_app():
    init_db()
    if not settings.TELEGRAM_BOT_TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN required")
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(_post).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ack", ack))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("agent", agent_cmd))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    return app

def main():
    threading.Thread(target=health, daemon=True).start()
    app = build_app()
    log.info("ORACLE-X starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
