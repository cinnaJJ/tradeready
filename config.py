"""config.py — App configuration"""
import os

if os.environ.get("FLASK_ENV") == "development":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

class Config:
    SECRET_KEY    = os.environ.get("SECRET_KEY", "tradeready-secret-2026")
    DEBUG         = os.environ.get("FLASK_ENV", "production") == "development"
    CACHE_TIMEOUT = int(os.environ.get("CACHE_TIMEOUT", 300))
    CMC_API_KEY   = os.environ.get("CMC_API_KEY", "")
    # Keep CoinGecko key in case needed
    COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")
    REQUEST_TIMEOUT   = 10

print(f"[Config] CMC_API_KEY = {'SET ✅ (' + Config.CMC_API_KEY[:8] + '...)' if Config.CMC_API_KEY else 'NOT SET ❌'}")
