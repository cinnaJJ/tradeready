"""
utils/binance_rsi.py — Real RSI from CryptoCompare public API
Free, no API key, no geo-restrictions (works on Render US servers)
Falls back to Binance.US if CryptoCompare fails for a symbol.
"""

import requests
import logging
import time

logger = logging.getLogger(__name__)

# CryptoCompare — free, global, no restrictions
CC_URL   = "https://min-api.cryptocompare.com/data/v2/histoday"
# Binance US — works from US servers unlike binance.com
BUS_URL  = "https://api.binance.us/api/v3/klines"


def fetch_closes_cc(symbol: str, limit: int = 30) -> list:
    """Fetch daily closing prices from CryptoCompare."""
    params = {
        "fsym":  symbol.upper(),
        "tsym":  "USDT",
        "limit": limit,
        "aggregate": 1,
    }
    try:
        r = requests.get(CC_URL, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get("Response") == "Success":
                candles = data.get("Data", {}).get("Data", [])
                closes  = [c["close"] for c in candles if c.get("close")]
                volumes = [c["volumeto"] for c in candles if c.get("volumeto")]
                if closes:
                    return closes, volumes
        logger.debug(f"CryptoCompare: no data for {symbol}")
        return [], []
    except Exception as e:
        logger.warning(f"CryptoCompare error for {symbol}: {e}")
        return [], []


def fetch_closes_binance_us(symbol: str, limit: int = 30) -> list:
    """Fallback: Binance.US (works from US IPs)."""
    params = {
        "symbol":   symbol.upper() + "USDT",
        "interval": "1d",
        "limit":    limit,
    }
    try:
        r = requests.get(BUS_URL, params=params, timeout=8)
        if r.status_code == 200:
            candles = r.json()
            closes  = [float(c[4]) for c in candles]
            volumes = [float(c[5]) for c in candles]
            return closes, volumes
        return [], []
    except Exception as e:
        logger.debug(f"Binance.US error for {symbol}: {e}")
        return [], []


def calc_rsi(closes: list, period: int = 14) -> float | None:
    """Calculate RSI(14) from closing prices."""
    if not closes or len(closes) < period + 1:
        return None
    try:
        gains = losses = 0.0
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            if diff > 0: gains  += diff
            else:        losses -= diff
        avg_g = gains  / period
        avg_l = losses / period
        if avg_l == 0: return 100.0
        for i in range(period + 1, len(closes)):
            diff  = closes[i] - closes[i - 1]
            avg_g = (avg_g * (period - 1) + max(diff, 0))  / period
            avg_l = (avg_l * (period - 1) + max(-diff, 0)) / period
        if avg_l == 0: return 100.0
        return round(100 - (100 / (1 + avg_g / avg_l)), 1)
    except:
        return None


def get_rsi(symbol: str) -> float | None:
    """Get RSI for a symbol. Tries CryptoCompare first, then Binance.US."""
    closes, _ = fetch_closes_cc(symbol, limit=30)
    if not closes:
        closes, _ = fetch_closes_binance_us(symbol, limit=30)
    if not closes:
        return None
    return calc_rsi(closes)


def get_volume_profile(symbol: str) -> dict:
    """
    Compare today's volume vs 7-day average.
    Returns spike=True if today is 2x+ average.
    """
    closes, volumes = fetch_closes_cc(symbol, limit=8)
    if not volumes:
        closes, volumes = fetch_closes_binance_us(symbol, limit=8)
    if not volumes or len(volumes) < 2:
        return {"spike": False, "ratio": 0, "current": 0, "avg": 0}

    current = volumes[-1]
    avg     = sum(volumes[:-1]) / len(volumes[:-1])

    if avg == 0:
        return {"spike": False, "ratio": 0, "current": current, "avg": 0}

    ratio = current / avg
    return {
        "spike":   ratio >= 2.0,
        "ratio":   round(ratio, 2),
        "current": current,
        "avg":     avg,
    }


def fetch_rsi_batch(symbols: list, interval: str = "1d") -> dict:
    """Fetch RSI for a list of symbols. Returns {SYMBOL: rsi_value}."""
    results = {}
    for symbol in symbols:
        try:
            rsi = get_rsi(symbol)
            if rsi is not None:
                results[symbol.upper()] = rsi
        except Exception as e:
            logger.debug(f"RSI batch error {symbol}: {e}")
        time.sleep(0.1)  # 100ms between requests
    logger.info(f"RSI batch complete: {len(results)}/{len(symbols)} coins")
    return results


def fetch_volume_batch(symbols: list) -> dict:
    """Fetch volume profiles for a list of symbols."""
    results = {}
    for symbol in symbols:
        try:
            profile = get_volume_profile(symbol)
            results[symbol.upper()] = profile
        except Exception as e:
            logger.debug(f"Volume batch error {symbol}: {e}")
        time.sleep(0.1)
    logger.info(f"Volume batch complete: {len(results)}/{len(symbols)} coins")
    return results
