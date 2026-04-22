import json, re
from typing import Dict, Any
from .config import settings
from .logger import get_logger
from .prompts import ORACLE_SYSTEM_PROMPT, USER_TEMPLATE

log = get_logger(__name__)

def _heuristic_signal(ctx: Dict[str, Any]) -> Dict[str, Any]:
    price = float(ctx.get("price") or 0)
    chg = float(ctx.get("change_pct") or 0)
    side = "long" if chg > 1 else ("short" if chg < -1 else "flat")
    stop = price * (0.98 if side == "long" else 1.02) if price else 0
    target = price * (1.03 if side == "long" else 0.97) if price else 0
    conf = min(0.5 + abs(chg) / 20, 0.75) if price else 0.0
    return {
        "symbol": ctx["symbol"], "side": side, "entry": price, "stop": stop, "target": target,
        "confidence": conf, "r_multiple": 1.5 if side != "flat" else 0,
        "thesis": f"Heuristic fallback: {chg:.2f}% move, no LLM key configured.",
        "verification": {"price_confirms": True, "volume_confirms": False,
                         "news_risk": "medium", "contradictions": []},
        "notes": "No LLM — heuristic only. Lower confidence enforced."
    }

def analyze(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.OPENAI_API_KEY:
        log.warning("No OPENAI_API_KEY — using heuristic oracle.")
        return _heuristic_signal(ctx)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        headlines = "\n".join(f"- {h}" for h in ctx.get("headlines", [])[:8]) or "- (none)"
        user_msg = USER_TEMPLATE.format(
            symbol=ctx["symbol"], asset_class=ctx.get("asset_class", "equity"),
            price=ctx.get("price", "unknown"), change_pct=ctx.get("change_pct", "unknown"),
            volume_rel=ctx.get("volume_rel", "unknown"), levels=ctx.get("levels", "unknown"),
            headlines=headlines, max_risk_pct=settings.MAX_RISK_PER_TRADE * 100,
            min_conf=settings.MIN_CONFIDENCE)
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "system", "content": ORACLE_SYSTEM_PROMPT},
                      {"role": "user", "content": user_msg}],
            temperature=0.2, response_format={"type": "json_object"})
        raw = resp.choices[0].message.content
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0) if m else raw)
        data.setdefault("symbol", ctx["symbol"])
        return data
    except Exception as e:
        log.exception("Oracle LLM failed, falling back: %s", e)
        return _heuristic_signal(ctx)
