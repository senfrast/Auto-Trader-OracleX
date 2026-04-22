from .config import settings
from .database import save_trade, close_trade
from .logger import get_logger
log = get_logger(__name__)

class PaperBroker:
    name = "paper"
    def place(self, user_id, signal_id, sig, qty):
        return save_trade(user_id, signal_id, {
            "symbol": sig["symbol"], "side": sig["side"], "qty": qty,
            "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"],
            "status": "open"})
    def close(self, trade_id, pnl):
        close_trade(trade_id, pnl)

class AlpacaBroker:
    name = "alpaca"
    def __init__(self):
        try:
            from alpaca.trading.client import TradingClient
            self.client = TradingClient(settings.ALPACA_KEY, settings.ALPACA_SECRET,
                                        paper="paper" in settings.ALPACA_BASE_URL)
        except Exception as e:
            log.error("Alpaca init failed: %s", e); self.client = None
    def place(self, user_id, signal_id, sig, qty):
        if not self.client:
            log.warning("Alpaca unavailable — routing to paper."); return PaperBroker().place(user_id, signal_id, sig, qty)
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            side = OrderSide.BUY if sig["side"] == "long" else OrderSide.SELL
            self.client.submit_order(MarketOrderRequest(
                symbol=sig["symbol"], qty=qty, side=side, time_in_force=TimeInForce.DAY))
        except Exception as e:
            log.exception("Alpaca submit failed: %s", e)
        return save_trade(user_id, signal_id, {
            "symbol": sig["symbol"], "side": sig["side"], "qty": qty,
            "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"], "status": "open"})
    def close(self, trade_id, pnl):
        close_trade(trade_id, pnl)

def get_broker():
    if settings.PAPER_MODE or settings.BROKER == "paper":
        return PaperBroker()
    if settings.BROKER == "alpaca":
        return AlpacaBroker()
    return PaperBroker()
