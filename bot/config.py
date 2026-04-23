import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

def _g(k, d=None):
    return os.getenv(k, d)

@dataclass
class Settings:
    TELEGRAM_BOT_TOKEN: str = _g("TELEGRAM_BOT_TOKEN", "")
    ADMIN_TELEGRAM_ID: str = _g("ADMIN_TELEGRAM_ID", "")
    LLM_PROVIDER: str = _g("LLM_PROVIDER", "groq")
    LLM_MODEL: str = _g("LLM_MODEL", "llama-3.3-70b-versatile")
    OPENAI_API_KEY: str = _g("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = _g("ANTHROPIC_API_KEY", "")
    GROQ_API_KEY: str = _g("GROQ_API_KEY", "")
    OPENAI_BASE_URL: str = _g("OPENAI_BASE_URL", "")
    DATABASE_URL: str = _g("DATABASE_URL", "sqlite:///oraclex.db")
    ALPHA_VANTAGE_KEY: str = _g("ALPHA_VANTAGE_KEY", "")
    FINNHUB_KEY: str = _g("FINNHUB_KEY", "")
    COINGECKO_KEY: str = _g("COINGECKO_KEY", "")
    NEWSAPI_KEY: str = _g("NEWSAPI_KEY", "")
    BROKER: str = _g("BROKER", "paper")
    ALPACA_KEY: str = _g("ALPACA_KEY", "")
    ALPACA_SECRET: str = _g("ALPACA_SECRET", "")
    ALPACA_BASE_URL: str = _g("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    BINANCE_KEY: str = _g("BINANCE_KEY", "")
    BINANCE_SECRET: str = _g("BINANCE_SECRET", "")
    MAX_RISK_PER_TRADE: float = float(_g("MAX_RISK_PER_TRADE", "0.01"))
    MAX_DAILY_LOSS: float = float(_g("MAX_DAILY_LOSS", "0.03"))
    MIN_CONFIDENCE: float = float(_g("MIN_CONFIDENCE", "0.65"))
    PAPER_MODE: bool = _g("PAPER_MODE", "true").lower() == "true"

settings = Settings()
