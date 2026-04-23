"""Tool-use agent loop for ORACLE-X.
Supports OpenAI-compatible providers: Groq (default, free), OpenAI, or Anthropic.
Provider is chosen via LLM_PROVIDER env var: groq | openai | anthropic.
"""
import asyncio, json, os
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

_TOOL_DEFS = [
    ("get_market_data", "Fetch live price, 24h change, relative volume, recent high/low for a stock or crypto symbol. Always call this before deciding on a trade.",
     {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}),
    ("get_news", "Fetch recent news headlines for a symbol.",
     {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["symbol"]}),
    ("get_positions", "List the current user's open paper/live positions.",
     {"type": "object", "properties": {}}),
    ("compute_position_size", "Compute qty from current equity + entry + stop using configured per-trade risk %.",
     {"type": "object", "properties": {"entry": {"type": "number"}, "stop": {"type": "number"}}, "required": ["entry", "stop"]}),
    ("place_trade", "Submit a paper/live order AFTER calling get_market_data and building a full thesis. System applies risk gates (confidence>=0.65, valid geometry, max positions).",
     {"type": "object", "properties": {"symbol": {"type": "string"}, "side": {"type": "string", "enum": ["long", "short"]}, "entry": {"type": "number"}, "stop": {"type": "number"}, "target": {"type": "number"}, "confidence": {"type": "number"}, "thesis": {"type": "string"}}, "required": ["symbol", "side", "entry", "stop", "target", "confidence", "thesis"]}),
    ("close_position", "Close an open position by trade id at the given exit price.",
     {"type": "object", "properties": {"trade_id": {"type": "integer"}, "exit_price": {"type": "number"}}, "required": ["trade_id", "exit_price"]}),
]

OPENAI_TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}} for n, d, p in _TOOL_DEFS]
ANTHROPIC_TOOLS = [{"name": n, "description": d, "input_schema": p} for n, d, p in _TOOL_DEFS]


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
            if not r:
                return {"error": "trade not found"}
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


def _resolve_provider():
    prov = (settings.LLM_PROVIDER or "").lower().strip()
    if prov in ("groq", "openai", "anthropic"):
        return prov
    if settings.GROQ_API_KEY:
        return "groq"
    if settings.OPENAI_API_KEY:
        return "openai"
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    return "groq"


async def _run_openai_compat(user_id, user_message, max_iterations, base_url, api_key, model):
    try:
        from openai import OpenAI
    except Exception as e:
        return f"Agent unavailable: openai SDK missing ({e})", []
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}]
    trace = []
    for step in range(max_iterations):
        try:
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=model, messages=messages, tools=OPENAI_TOOLS,
                tool_choice="auto", max_tokens=1600, temperature=0.3,
            )
        except Exception as e:
            log.exception("agent LLM call failed: %s", e)
            return f"Agent LLM error: {e}", trace
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            final = (msg.content or "").strip()
            trace.append(f"stop:{resp.choices[0].finish_reason}")
            return final or "(no text)", trace
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in tool_calls],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            trace.append(f"{tc.function.name}({json.dumps(args)[:120]})")
            result = await asyncio.to_thread(_dispatch, tc.function.name, args, user_id)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)[:6000]})
    return "Agent hit max iterations without a final verdict.", trace


async def _run_anthropic(user_id, user_message, max_iterations, api_key, model):
    try:
        from anthropic import Anthropic
    except Exception as e:
        return f"Agent unavailable: anthropic SDK missing ({e})", []
    client = Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": user_message}]
    trace = []
    for step in range(max_iterations):
        try:
            resp = await asyncio.to_thread(client.messages.create, model=model, max_tokens=1600,
                                           system=SYSTEM_PROMPT, tools=ANTHROPIC_TOOLS, messages=messages)
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


async def run_agent(user_id, user_message, max_iterations=8):
    provider = _resolve_provider()
    model = settings.LLM_MODEL
    if provider == "groq":
        if not settings.GROQ_API_KEY:
            return "Agent unavailable: GROQ_API_KEY not set.", []
        return await _run_openai_compat(user_id, user_message, max_iterations,
                                        "https://api.groq.com/openai/v1",
                                        settings.GROQ_API_KEY,
                                        model or "llama-3.3-70b-versatile")
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            return "Agent unavailable: OPENAI_API_KEY not set.", []
        return await _run_openai_compat(user_id, user_message, max_iterations,
                                        settings.OPENAI_BASE_URL or None,
                                        settings.OPENAI_API_KEY,
                                        model or "gpt-4o-mini")
    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            return "Agent unavailable: ANTHROPIC_API_KEY not set.", []
        return await _run_anthropic(user_id, user_message, max_iterations,
                                    settings.ANTHROPIC_API_KEY,
                                    model or "claude-3-5-sonnet-latest")
    return f"Agent unavailable: unknown LLM_PROVIDER '{provider}'.", []
