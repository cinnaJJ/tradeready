"""
utils/data_processor.py — Data formatting + Trading Signal Engine
Uses real RSI from Binance where available, falls back to sparkline RSI.
"""

import logging
logger = logging.getLogger(__name__)


# ─── FORMATTING ──────────────────────────────────────────────────────────────
def format_currency(value, decimals: int = 2) -> str:
    if value is None: return "N/A"
    try:
        v = float(value)
        if abs(v) >= 1_000_000_000: return f"${v/1_000_000_000:.2f}B"
        if abs(v) >= 1_000_000:     return f"${v/1_000_000:.2f}M"
        if abs(v) >= 1_000:         return f"${v/1_000:.2f}K"
        if abs(v) < 0.01:           return f"${v:.6f}"
        return f"${v:,.{decimals}f}"
    except: return "N/A"


def format_percentage(value, decimals: int = 2) -> str:
    if value is None: return "N/A"
    try:
        v = float(value)
        return f"{'+' if v >= 0 else ''}{v:.{decimals}f}%"
    except: return "N/A"


# ─── RSI FROM SPARKLINE (fallback) ───────────────────────────────────────────
def calc_rsi_sparkline(prices: list, period: int = 14) -> float | None:
    if not prices or len(prices) < period + 1:
        return None
    try:
        gains, losses = 0.0, 0.0
        for i in range(1, period + 1):
            diff = prices[i] - prices[i - 1]
            if diff > 0: gains  += diff
            else:        losses -= diff
        avg_gain = gains  / period
        avg_loss = losses / period
        if avg_loss == 0: return 100.0
        for i in range(period + 1, len(prices)):
            diff = prices[i] - prices[i - 1]
            avg_gain = (avg_gain * (period-1) + max(diff, 0)) / period
            avg_loss = (avg_loss * (period-1) + max(-diff, 0)) / period
        if avg_loss == 0: return 100.0
        return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)
    except: return None


# ─── TREND DETECTION ─────────────────────────────────────────────────────────
def detect_trend(prices: list) -> str:
    if not prices or len(prices) < 6: return "unknown"
    try:
        third = len(prices) // 3
        early = sum(prices[:third]) / third
        late  = sum(prices[-third:]) / third
        change = (late - early) / early * 100
        if change > 5:  return "uptrend"
        if change < -5: return "downtrend"
        return "sideways"
    except: return "unknown"


def detect_pullback(prices: list) -> bool:
    if not prices or len(prices) < 10: return False
    try:
        peak   = max(prices[:-3])
        recent = prices[-1]
        pct    = (peak - recent) / peak * 100
        return detect_trend(prices) == "uptrend" and 3 <= pct <= 15
    except: return False


# ─── TRADING SIGNAL ENGINE ───────────────────────────────────────────────────
def calculate_trading_signal(coin: dict, rsi_cache: dict = None,
                               vol_cache: dict = None) -> dict:
    """
    Score a coin 0-10. Uses real Binance RSI/volume where available.
    rsi_cache: {SYMBOL: rsi_value} from Binance
    vol_cache: {SYMBOL: volume_profile} from Binance
    """
    score    = 0.0
    signals  = []
    warnings = []

    p24  = coin.get("price_change_percentage_24h") or 0
    p7d  = coin.get("price_change_percentage_7d_in_currency") or 0
    vol  = coin.get("total_volume") or 0
    mcap = coin.get("market_cap") or 0
    sym  = (coin.get("symbol") or "").upper()

    sparkline = coin.get("sparkline_in_7d", {})
    prices    = sparkline.get("price", []) if isinstance(sparkline, dict) else []

    # ── RSI — use Binance real RSI first, fallback to sparkline ──────────────
    rsi = None
    rsi_source = "estimated"

    if rsi_cache and sym in rsi_cache:
        rsi = rsi_cache[sym]
        rsi_source = "Binance (real)"
    elif prices:
        rsi = calc_rsi_sparkline(prices)
        rsi_source = "sparkline"

    # Final fallback — estimate from price changes
    if rsi is None:
        if p7d < -20:   rsi = 22
        elif p7d < -10: rsi = 33
        elif p7d > 20:  rsi = 78
        elif p7d > 10:  rsi = 65
        else:           rsi = 50
        rsi_source = "estimated"

    coin["rsi_value"]  = rsi
    coin["rsi_source"] = rsi_source

    if rsi <= 25:
        score += 3.0
        signals.append({"icon": "📉", "label": f"RSI Deeply Oversold ({rsi})", "type": "bullish",
                         "desc": f"RSI at {rsi} — extreme selling exhaustion ({rsi_source})"})
    elif rsi <= 30:
        score += 2.5
        signals.append({"icon": "📉", "label": f"RSI Oversold ({rsi})", "type": "bullish",
                         "desc": f"RSI at {rsi} — sellers exhausted, potential bounce ({rsi_source})"})
    elif rsi <= 40:
        score += 1.0
        signals.append({"icon": "📊", "label": f"RSI Low ({rsi})", "type": "neutral",
                         "desc": f"RSI recovering from oversold ({rsi_source})"})
    elif rsi >= 75:
        score -= 2.5
        warnings.append({"icon": "⚠️", "label": f"RSI Extremely Overbought ({rsi})", "type": "bearish",
                          "desc": f"RSI at {rsi} — very high reversal risk ({rsi_source})"})
    elif rsi >= 70:
        score -= 2.0
        warnings.append({"icon": "⚠️", "label": f"RSI Overbought ({rsi})", "type": "bearish",
                          "desc": f"RSI at {rsi} — buyers exhausted ({rsi_source})"})
    elif rsi >= 60:
        score -= 0.5
        warnings.append({"icon": "📊", "label": f"RSI Elevated ({rsi})", "type": "caution",
                          "desc": f"RSI getting high — be careful chasing ({rsi_source})"})

    # ── TREND ────────────────────────────────────────────────────────────────
    trend = detect_trend(prices) if prices else (
        "uptrend" if p7d > 5 else "downtrend" if p7d < -5 else "sideways"
    )
    coin["trend"] = trend

    if trend == "uptrend":
        score += 2.0
        signals.append({"icon": "📈", "label": "Uptrend Active", "type": "bullish",
                         "desc": "Higher Highs + Higher Lows — bullish structure intact"})
    elif trend == "downtrend":
        score -= 2.0
        warnings.append({"icon": "📉", "label": "Downtrend Active", "type": "bearish",
                          "desc": "Lower Highs + Lower Lows — avoid buying into this"})
    else:
        signals.append({"icon": "↔️", "label": "Sideways / Ranging", "type": "neutral",
                         "desc": "No clear trend — wait for breakout"})

    # ── PULLBACK TO SUPPORT ───────────────────────────────────────────────────
    pullback = detect_pullback(prices) if prices else (
        trend == "uptrend" and -15 <= p24 <= -3
    )
    coin["is_pullback"] = pullback

    if pullback:
        score += 2.0
        signals.append({"icon": "🎯", "label": "Pullback to Support", "type": "bullish",
                         "desc": "Healthy dip in uptrend — potential buy-the-dip setup"})

    # ── VOLUME — use Binance real data first ──────────────────────────────────
    vol_spike  = False
    vol_ratio  = 0
    vol_source = "estimated"

    if vol_cache and sym in vol_cache:
        vp         = vol_cache[sym]
        vol_spike  = vp.get("spike", False)
        vol_ratio  = vp.get("ratio", 0)
        vol_source = f"Binance (real) {vol_ratio}x avg"
    else:
        # Fallback — volume vs market cap ratio
        if vol and mcap and mcap > 0:
            vol_spike  = (vol / mcap) > 0.20
            vol_ratio  = round(vol / mcap, 2)
            vol_source = "estimated (vol/mcap)"

    coin["volume_spike"] = vol_spike

    if vol_spike:
        if p24 > 0:
            score += 1.5
            signals.append({"icon": "🔥", "label": f"Volume Spike Bullish ({vol_source})", "type": "bullish",
                             "desc": "High volume on up move — real buyers behind this"})
        else:
            score -= 1.0
            warnings.append({"icon": "🔥", "label": f"Volume Spike Bearish ({vol_source})", "type": "bearish",
                              "desc": "High volume on down move — real selling pressure"})

    # ── 24H MOMENTUM ─────────────────────────────────────────────────────────
    if p24 > 15:
        score -= 1.0
        warnings.append({"icon": "🚀", "label": f"Already pumped +{p24:.1f}% today", "type": "caution",
                          "desc": "Up too much — don't chase, wait for pullback"})
    elif p24 > 8:
        score -= 0.5
        warnings.append({"icon": "📈", "label": f"Strong day +{p24:.1f}%", "type": "caution",
                          "desc": "Good move but getting extended — be careful"})
    elif 3 <= p24 <= 8:
        score += 0.5
        signals.append({"icon": "✅", "label": f"Healthy gain +{p24:.1f}%", "type": "bullish",
                         "desc": "Steady gain — not overextended"})
    elif p24 < -20:
        warnings.append({"icon": "💥", "label": f"Big drop {p24:.1f}%", "type": "bearish",
                          "desc": "Steep drop — wait for stabilisation before considering"})

    # ── MARKET CAP SAFETY ────────────────────────────────────────────────────
    if mcap < 500_000_000:
        score -= 1.0
        warnings.append({"icon": "⚠️", "label": "Small Cap — Higher Risk", "type": "caution",
                          "desc": "Under $500M market cap — avoid as beginner"})
    elif mcap > 10_000_000_000:
        score += 0.5
        signals.append({"icon": "🏦", "label": "Large Cap (Safer)", "type": "bullish",
                         "desc": "Large cap — more liquid, cleaner patterns"})

    # ── FINAL SCORE ──────────────────────────────────────────────────────────
    score = round(max(0.0, min(10.0, score + 3.0)), 1)

    if score >= 7.5:
        verdict, color, icon = "STRONG BUY WATCH", "bullish", "🟢"
    elif score >= 6.0:
        verdict, color, icon = "BUY WATCH",         "bullish", "🟡"
    elif score >= 4.5:
        verdict, color, icon = "NEUTRAL — WAIT",    "neutral", "🔵"
    elif score >= 3.0:
        verdict, color, icon = "CAUTION",            "caution", "🟠"
    else:
        verdict, color, icon = "AVOID",              "bearish", "🔴"

    return {
        "score":         score,
        "verdict":       verdict,
        "verdict_color": color,
        "verdict_icon":  icon,
        "signals":       signals,
        "warnings":      warnings,
        "rsi":           rsi,
        "rsi_source":    rsi_source,
        "trend":         trend,
        "pullback":      pullback,
        "vol_spike":     vol_spike,
        "confluence":    len(signals),
    }


# ─── PROCESS MARKET DATA ─────────────────────────────────────────────────────
def process_market_data(raw_coins: list, rsi_cache: dict = None,
                         vol_cache: dict = None) -> list:
    processed = []
    for i, coin in enumerate(raw_coins):
        try:
            p24 = coin.get("price_change_percentage_24h")
            p7d = coin.get("price_change_percentage_7d_in_currency")
            vol = coin.get("total_volume")
            mc  = coin.get("market_cap")

            signal = calculate_trading_signal(coin, rsi_cache, vol_cache)

            sparkline = coin.get("sparkline_in_7d", {})

            processed.append({
                **coin,
                "rank":               coin.get("market_cap_rank") or (i + 1),
                "formatted_price":    format_currency(coin.get("current_price")),
                "formatted_mcap":     format_currency(mc),
                "formatted_volume":   format_currency(vol),
                "formatted_change":   format_percentage(p24),
                "formatted_change7d": format_percentage(p7d),
                "change_class":       "positive" if (p24 or 0) >= 0 else "negative",
                "sparkline_data":     sparkline.get("price", [])
                                      if isinstance(sparkline, dict) else [],
                "signal_score":       signal["score"],
                "signal_verdict":     signal["verdict"],
                "signal_color":       signal["verdict_color"],
                "signal_icon":        signal["verdict_icon"],
                "signal_details":     signal["signals"],
                "signal_warnings":    signal["warnings"],
                "signal_rsi":         signal["rsi"],
                "signal_rsi_source":  signal["rsi_source"],
                "signal_trend":       signal["trend"],
                "signal_pullback":    signal["pullback"],
                "signal_vol_spike":   signal["vol_spike"],
                "signal_confluence":  signal["confluence"],
                "trend_signal":       signal["verdict_color"],
            })
        except Exception as e:
            logger.warning(f"process error coin {i}: {e}")
            continue
    return processed


def filter_coins(coins: list, min_price=None, max_price=None,
                 min_change=None, max_change=None, sort_by: str = None) -> list:
    f = coins
    if min_price  is not None: f = [c for c in f if (c.get("current_price") or 0) >= min_price]
    if max_price  is not None: f = [c for c in f if (c.get("current_price") or 0) <= max_price]
    if min_change is not None: f = [c for c in f if (c.get("price_change_percentage_24h") or 0) >= min_change]
    if max_change is not None: f = [c for c in f if (c.get("price_change_percentage_24h") or 0) <= max_change]
    if sort_by:
        reverse = not sort_by.endswith("_asc")
        key_map = {"price": "current_price", "volume": "total_volume",
                   "market_cap": "market_cap", "change": "price_change_percentage_24h",
                   "score": "signal_score"}
        key = key_map.get(sort_by.replace("_asc","").replace("_desc",""), "market_cap")
        f   = sorted(f, key=lambda x: x.get(key) or 0, reverse=reverse)
    return f
