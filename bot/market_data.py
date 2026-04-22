from typing import Dict, Any
from .logger import get_logger
log = get_logger(__name__)

def _yf(symbol: str) -> Dict[str, Any]:
    import yfinance as yf
    t = yf.Ticker(symbol)
    hist = t.history(period="5d", interval="1h")
    if hist.empty:
        return {"symbol": symbol, "price": None, "change_pct": None, "volume_rel": None, "levels": "unknown"}
    last = hist.iloc[-1]
    prev_close = hist["Close"].iloc[-2] if len(hist) > 1 else last["Close"]
    chg = float((last["Close"] - prev_close) / prev_close * 100) if prev_close else 0.0
    avg_vol = float(hist["Volume"].mean()) or 1.0
    vol_rel = float(last["Volume"] / avg_vol)
    hi = float(hist["High"].max()); lo = float(hist["Low"].min())
    return {"symbol": symbol, "asset_class": "equity", "price": float(last["Close"]),
            "change_pct": round(chg, 3), "volume_rel": round(vol_rel, 2),
            "levels": f"recent_hi={hi:.2f}, recent_lo={lo:.2f}"}

def _coingecko(symbol: str) -> Dict[str, Any]:
    import requests
    s = symbol.lower().replace("-usd", "")
    mapping = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin",
               "xrp": "ripple", "ada": "cardano", "doge": "dogecoin"}
    cid = mapping.get(s, s)
    r = requests.get(f"https://api.coingecko.com/api/v3/coins/{cid}",
                     params={"localization": "false", "tickers": "false", "market_data": "true"}, timeout=15)
    if r.status_code != 200:
        return {"symbol": symbol, "price": None, "change_pct": None, "volume_rel": None, "levels": "unknown"}
    md = r.json().get("market_data", {})
    price = md.get("current_price", {}).get("usd")
    chg = md.get("price_change_percentage_24h", 0)
    hi = md.get("high_24h", {}).get("usd"); lo = md.get("low_24h", {}).get("usd")
    return {"symbol": symbol.upper(), "asset_class": "crypto", "price": price,
            "change_pct": round(chg or 0, 3), "volume_rel": 1.0,
            "levels": f"24h_hi={hi}, 24h_lo={lo}"}

def get_context(symbol: str) -> Dict[str, Any]:
    sym = symbol.strip().upper()
    crypto_tokens = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"}
    is_crypto = sym in crypto_tokens or sym.endswith("-USD") or sym.endswith("USDT")
    try:
        return _coingecko(sym) if is_crypto else _yf(sym)
    except Exception as e:
        log.exception("market_data failed for %s: %s", sym, e)
        return {"symbol": sym, "price": None, "change_pct": None, "volume_rel": None, "levels": "unknown"}
