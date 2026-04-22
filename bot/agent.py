"""Claude tool-use agent loop for ORACLE-X.
Gives the LLM a toolbox and lets it iterate like OpenHands / Agent Zero.
"""
import asyncio, json
from .config import settings
from .logger import get_logger
from .market_data import get_context
from .news import fetch_headlines
from .database import list_open_trades, get_user, save_signal, journal, conn
from .risk import check_gates, position_size
from .execution import get_broker

log = get_logger(__name__)

SYSTEM_PROMPT = """You are ORACLE-X, an autonomous trading agent under the Truth Oath.

TRUTH OATH
- Report calibrated confidence (0.0-1.0). No ego, no narrative inflation.
- Every thesis includes explicit invalidation (what proves it wrong).
- Prefer PASS over forcing a mediocre setup.
- Respect risk gates: <=1% risk/trade, >=1.8 R:R, confidence >=0.65, max 5 concurrent positions.
- You operate in PAPER mode unless the user has flipped to live.

OPERATING LOOP
You have tools. Use them. Do not guess prices or invent levels.
1. Gather: call get_market_data + get_news for the symbol. Check get_positions if relevant.
2. Reason: identify trend, volatility, nearest structural levels, catalyst, invalidation.
3. Decide: build entry/stop/target geometry. Compute R:R. Set confidence honestly.
4. Act: if conviction >= 0.65 and geometry passes, call place_trade. Otherwise produce PASS.
5. Respond to the user CONCISELY (<=8 lines), markdown-friendly:
   *SYMBOL* - VERDICT (LONG/SHORT/PASS)
   Entry / Stop / Target (if trade)
   Confidence: X.XX  R:R: X.X
   Thesis: 1-2 sentences.
   Invalidation: 1 line.

RULES
- Never fabricate data. If a tool fails, say so.
- Never place a trade without calling get_market_data first.
- If user asks a general question (not a symbol), answer plainly without tools.
"""

TOOLS = [
  {"name":"get_market_data","description":"Fetch live price, 24h change, relative volume, recent high/low for a stock or crypto symbol. Always call this before deciding on a trade.","input_schema":{"type":"object","properties":{"symbol":{"type":"string"}},"required":["symbol"]}},
  {"name":"get_news","description":"Fetch recent news headlines for a symbol.","input_schema":{"type":"object","properties":{"symbol":{"type":"string"},"limit":{"type":"integer"}},"required":["symbol"]}},
  {"name":"get_positions","description":"List the current user's open paper/live positions.","input_schema":{"type":"object","properties":{}}},
  {"name":"compute_position_size","description":"Compute qty from current equity + entry + stop using configured per-trade risk %.","input_schema":{"type":"object","properties":{"entry":{"type":"number"},"stop":{"type":"number"}},"required":["entry","stop"]}},
  {"name":"place_trade","description":"Submit a paper/live order AFTER calling get_market_data and building a full thesis. System applies risk gates (confidence>=0.65, valid geometry, max positions).","input_schema":{"type":"object","properties":{"symbol":{"type":"string"},"side":{"type":"string","enum":["long","short"]},"entry":{"type":"number"},"stop":{"type":"number"},"target":{"type":"number"},"confidence":{"type":"number"},"thesis":{"type":"string"}},"required":["symbol","side","entry","stop","target","confidence","thesis"]}},
  {"name":"close_position","description":"Close an open position by trade id at the given exit price.","input_schema":{"type":"object","properties":{"trade_id":{"type":"integer"},"exit_price":{"type":"number"}},"required":["trade_id","exit_price"]}}
]


def _dispatch(name, args, user_id):
    try:
        if name == "get_market_data":
            return get_context(args["symbol"])
        if name == "get_news":
            return {"symbol": args["symbol"], "headlines": fetch_headlines(args["symbol"], int(args.get("limit", 6)))}
        if name == "get_positions":
            return {"positions": list_open_trades(user_id)}
        if name == "compute_position_size":
            user = get_user(user_id) or {"equity": 10000}
            qty = position_size(float(user.get("equity", 10000)), float(args["entry"]), float(args["stop"]))
            return {"qty": qty, "equity": user.get("equity", 10000)}
        if name == "place_trade":
            sig = {"symbol": args["symbol"].upper(), "side": args["side"],
                   "entry": float(args["entry"]), "stop": float(args["stop"]),
                   "target": float(args["target"]), "confidence": float(args["confidence"]),
                   "thesis": args["thesis"][:1000], "verification": {"source": "agent"}}
            ok, reason = check_gates(user_id, sig)
            if not ok:
                journal(user_id, "agent_gate_block", {"sig": sig, "reason": reason})
                return {"rejected": True, "reason": reason}
            sig_id = save_signal(user_id, sig)
            user = get_user(user_id) or {"equity": 10000}
            qty = position_size(float(user.get("equity", 10000)), sig["entry"], sig["stop"])
            if qty <= 0:
                return {"rejected": True, "reason": "invalid size"}
            broker = get_broker()
            trade_id = broker.place(user_id, sig_id, sig, qty)
            journal(user_id, "agent_trade", {"sig": sig, "qty": qty, "trade_id": trade_id})
            return {"ok": True, "trade_id": trade_id, "qty": qty, "broker": broker.name, "signal_id": sig_id}
        if name == "close_position":
            trade_id = int(args["trade_id"]); exit_price = float(args["exit_price"])
            with conn() as c:
                r = c.execute("SELECT * FROM trades WHERE id=? AND user_id=?", (trade_id, str(user_id))).fetchone()
            if not r: return {"error": "trade not found"}
            t = dict(r)
            direction = 1 if t["side"] == "long" else -1
            pnl = round((exit_price - float(t["entry"])) * float(t["qty"]) * direction, 2)
            broker = get_broker(); broker.close(trade_id, pnl)
            journal(user_id, "agent_close", {"trade_id": trade_id, "pnl": pnl, "exit": exit_price})
            return {"ok": True, "trade_id": trade_id, "pnl": pnl}
        return {"error": f"unknown tool {name}"}
    except Exception as e:
        log.exception("tool %s failed: %s", name, e)
        return {"error": str(e)}


async def run_agent(user_id, user_message, max_iterations=8):
    try:
        from anthropic import Anthropic
    except Exception as e:
        return f"Agent unavailable: anthropic SDK missing ({e})", []
    if not settings.ANTHROPIC_API_KEY:
        return "Agent unavailable: ANTHROPIC_API_KEY not set.", []
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    model = settings.LLM_MODEL or "claude-opus-4-5"
    messages = [{"role": "user", "content": user_message}]
    trace = []
    for step in range(max_iterations):
        try:
            resp = await asyncio.to_thread(client.messages.create, model=model, max_tokens=1600,
                                           system=SYSTEM_PROMPT, tools=TOOLS, messages=messages)
        except Exception as e:
            log.exception("agent LLM call failed: %s", e)
            return f"Agent LLM error: {e}", trace
        if resp.stop_reason in ("end_turn", "stop_sequence"):
            final = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            trace.append(f"stop:{resp.stop_reason}")
            return final.strip() or "(no text)", trace
        tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            final = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            return final.strip() or "(empty response)", trace
        messages.append({"role": "assistant", "content": [b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content]})
        tool_results = []
        for tu in tool_uses:
            trace.append(f"{tu.name}({json.dumps(tu.input)[:120]})")
            result = await asyncio.to_thread(_dispatch, tu.name, tu.input, user_id)
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result)[:6000]})
        messages.append({"role": "user", "content": tool_results})
    return "Agent hit max iterations without a final verdict.", trace
