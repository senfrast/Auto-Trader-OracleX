from typing import List
import requests
from .config import settings
from .logger import get_logger
log = get_logger(__name__)

def fetch_headlines(symbol: str, limit: int = 8) -> List[str]:
    headlines: List[str] = []
    try:
        if settings.FINNHUB_KEY:
            r = requests.get("https://finnhub.io/api/v1/company-news",
                             params={"symbol": symbol, "from": "2024-01-01", "to": "2030-01-01",
                                     "token": settings.FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                for n in r.json()[:limit]:
                    h = n.get("headline")
                    if h: headlines.append(h)
    except Exception as e:
        log.warning("finnhub news err: %s", e)
    try:
        if settings.NEWSAPI_KEY and len(headlines) < limit:
            r = requests.get("https://newsapi.org/v2/everything",
                             params={"q": symbol, "pageSize": limit, "sortBy": "publishedAt",
                                     "apiKey": settings.NEWSAPI_KEY, "language": "en"}, timeout=10)
            if r.status_code == 200:
                for a in r.json().get("articles", [])[:limit - len(headlines)]:
                    if a.get("title"): headlines.append(a["title"])
    except Exception as e:
        log.warning("newsapi err: %s", e)
    return headlines[:limit]
