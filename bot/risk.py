from .config import settings
from .database import list_open_trades
from .logger import get_logger
log = get_logger(__name__)

def position_size(equity: float, entry: float, stop: float, risk_pct: float = None) -> float:
    risk_pct = risk_pct if risk_pct is not None else settings.MAX_RISK_PER_TRADE
    if entry <= 0 or stop <= 0: return 0.0
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0: return 0.0
    risk_dollars = equity * risk_pct
    return round(risk_dollars / risk_per_unit, 6)

def check_gates(user_id: str, signal: dict) -> (bool, str):
    if signal.get("side") == "flat":
        return False, "Signal is FLAT — no trade."
    if signal.get("confidence", 0) < settings.MIN_CONFIDENCE:
        return False, f"Confidence {signal.get('confidence'):.2f} < threshold {settings.MIN_CONFIDENCE}."
    entry = signal.get("entry"); stop = signal.get("stop"); target = signal.get("target")
    if not (entry and stop and target):
        return False, "Missing entry/stop/target."
    if signal["side"] == "long" and not (stop < entry < target):
        return False, "Long geometry invalid (need stop < entry < target)."
    if signal["side"] == "short" and not (target < entry < stop):
        return False, "Short geometry invalid (need target < entry < stop)."
    if len(list_open_trades(user_id)) >= 5:
        return False, "Max 5 concurrent open positions reached."
    return True, "OK"
