import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

def _get(key, default=None, required=False):
    v = os.getenv(key, default)
    if required and not v:
        raise RuntimeError(f"Missing env var: {key}")
    return v

@dataclass
class Settings:
    TELEGRAM_BOT_TOKEN: str = _get("TELEGRAM_BOT_TOKEN", "")
    ADMIN_TELEGRAM_ID: str = _get("ADMIN_TELEGRAM_ID", "")
    OPENAI_API_KEY: str = _get("OPENAI_API_KEY", "")
    LLM_MODEL: str = _get("LLM_MODEL", "gpt-4o-mini")
    DATABASE_URL: str = _get("DATABASE_URL", "sqlite:///oraclex.db")
    ALPHA_VANTAGE_KEY: str = _get("ALPHA_VANTAGE_KEY", "")
    FINNHUB_KEY: str = _get("FINNHUB_KEY", "")
    COINGECKO_KEY: str = _get("COINGECKO_KEY", "")
    NEWSAPI_KEY: str = _get("NEWSAPI_KEY", "")
    BROKER: str = _get("BROKER", "paper")
    ALPACA_KEY: str = _get("ALPACA_KEY", "")
    ALPACA_SECRET: str = _get("ALPACA_SECRET", "")
    ALPACA_BASE_URL: str = _get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    BINANCE_KEY: str = _get("BINANCE_KEY", "")
    BINANCE_SECRET: str = _get("BINANCE_SECRET", "")
    MAX_RISK_PER_TRADE: float = float(_get("MAX_RISK_PER_TRADE", "0.01"))
    MAX_DAILY_LOSS: float = float(_get("MAX_DAILY_LOSS", "0.03"))
    MIN_CONFIDENCE: float = float(_get("MIN_CONFIDENCE", "0.65"))
    PAPER_MODE: bool = _get("PAPER_MODE", "true").lower() == "true"

settings = Settings()
