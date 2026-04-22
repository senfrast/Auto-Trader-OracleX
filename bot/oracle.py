import json, re
from typing import Dict, Any
from .config import settings
from .logger import get_logger
from .prompts import ORACLE_SYSTEM_PROMPT, USER_TEMPLATE

log = get_logger(__name__)

def _heuristic(ctx):
    price = float(ctx.get("price") or 0)
    chg = float(ctx.get("change_pct") or 0)
    side = "long" if chg > 1 else ("short" if chg < -1 else "flat")
    stop = price * (0.98 if side == "long" else 1.02) if price else 0
    target = price * (1.03 if side == "long" else 0.97) if price else 0
    conf = min(0.5 + abs(chg) / 20, 0.75) if price else 0.0
    return {"symbol": ctx["symbol"], "side": side, "entry": price, "stop": stop, "target": target,
            "confidence": conf, "r_multiple": 1.5 if side != "flat" else 0,
            "thesis": f"Heuristic fallback: {chg:.2f}% move, no LLM configured.",
            "verification": {"price_confirms": True, "volume_confirms": False,
                             "news_risk": "medium", "contradictions": []},
            "notes": "No LLM - heuristic only."}

def _build_user(ctx):
    headlines = "\n".join(f"- {h}" for h in ctx.get("headlines", [])[:8]) or "- (none)"
    return USER_TEMPLATE.format(
        symbol=ctx["symbol"], asset_class=ctx.get("asset_class", "equity"),
        price=ctx.get("price", "unknown"), change_pct=ctx.get("change_pct", "unknown"),
        volume_rel=ctx.get("volume_rel", "unknown"), levels=ctx.get("levels", "unknown"),
        headlines=headlines, max_risk_pct=settings.MAX_RISK_PER_TRADE * 100,
        min_conf=settings.MIN_CONFIDENCE)

def _parse(raw, symbol):
    m = re.search(r"\{[\s\S]*\}", raw)
    data = json.loads(m.group(0) if m else raw)
    data.setdefault("symbol", symbol)
    return data

def _anthropic(ctx):
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=settings.LLM_MODEL, max_tokens=1024, temperature=0.2,
        system=ORACLE_SYSTEM_PROMPT + "\nRespond with ONLY valid JSON, no prose.",
        messages=[{"role": "user", "content": _build_user(ctx)}])
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _parse(text, ctx["symbol"])

def _openai(ctx):
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=settings.LLM_MODEL, temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": ORACLE_SYSTEM_PROMPT},
                  {"role": "user", "content": _build_user(ctx)}])
    return _parse(resp.choices[0].message.content, ctx["symbol"])

def analyze(ctx):
    prov = (settings.LLM_PROVIDER or "").lower()
    try:
        if prov == "anthropic" and settings.ANTHROPIC_API_KEY:
            return _anthropic(ctx)
        if prov == "openai" and settings.OPENAI_API_KEY:
            return _openai(ctx)
        if settings.ANTHROPIC_API_KEY:
            return _anthropic(ctx)
        if settings.OPENAI_API_KEY:
            return _openai(ctx)
    except Exception as e:
        log.exception("Oracle LLM failed (%s): %s", prov, e)
    return _heuristic(ctx)
