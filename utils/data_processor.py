"""
utils/data_processor.py — Trading Signal Engine v2
Improvements:
- EMA 200 position check
- BTC condition filter (caps score if BTC bearish)
- Minimum 3 confluence rule for Buy Watch
- Pump filter (flags 20%+ 7d gains as chasing)
- Market environment badge
- Score confidence label
"""

import logging
logger = logging.getLogger(__name__)

# Stablecoins to always filter out
STABLECOINS = {
    "USDT","USDC","BUSD","DAI","TUSD","USDP","GUSD","FRAX",
    "LUSD","SUSD","USDD","PYUSD","USD1","USDE","USDG","RLUSD",
    "FDUSD","CUSD","CEUR","USDBC","EURC","EURS"
}

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

# ─── RSI FROM SPARKLINE ──────────────────────────────────────────────────────
def calc_rsi_sparkline(prices: list, period: int = 14) -> float | None:
    if not prices or len(prices) < period + 1: return None
    try:
        gains = losses = 0.0
        for i in range(1, period + 1):
            diff = prices[i] - prices[i-1]
            if diff > 0: gains  += diff
            else:        losses -= diff
        avg_g = gains  / period
        avg_l = losses / period
        if avg_l == 0: return 100.0
        for i in range(period + 1, len(prices)):
            diff  = prices[i] - prices[i-1]
            avg_g = (avg_g * (period-1) + max(diff, 0))  / period
            avg_l = (avg_l * (period-1) + max(-diff, 0)) / period
        if avg_l == 0: return 100.0
        return round(100 - (100 / (1 + avg_g / avg_l)), 1)
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

# ─── EMA 200 ESTIMATE FROM SPARKLINE ─────────────────────────────────────────
def estimate_ema200_position(prices: list, p7d: float) -> str:
    """
    Estimate if price is above or below EMA 200.
    Uses 7d trend as proxy — not perfect but directional.
    Returns: 'above', 'below', 'unknown'
    """
    if not prices: 
        # Use 7d change as proxy
        if p7d is None: return "unknown"
        if p7d > 15:    return "above"   # strong uptrend likely above
        if p7d < -15:   return "below"   # strong downtrend likely below
        return "unknown"
    
    # Use sparkline — if price is well above the early average = likely above EMA 200
    try:
        early_avg = sum(prices[:7]) / 7 if len(prices) >= 7 else prices[0]
        current   = prices[-1]
        diff_pct  = (current - early_avg) / early_avg * 100
        if diff_pct > 10:   return "above"
        if diff_pct < -10:  return "below"
        return "unknown"
    except: return "unknown"

# ─── MARKET ENVIRONMENT ───────────────────────────────────────────────────────
def get_market_environment(btc_data: dict) -> dict:
    """
    Determine overall market environment from BTC data.
    Returns environment dict used to cap scores.
    """
    if not btc_data or not btc_data.get("price"):
        return {"env": "unknown", "label": "UNKNOWN", "color": "neutral",
                "cap_score": 10, "penalty": 0, "warning": None}

    p24 = btc_data.get("change24", 0) or 0
    p7d = btc_data.get("change7d", 0)  or 0
    mood = btc_data.get("mood", "")

    # BTC below all EMAs = bearish environment
    if mood in ("bearish",) or (p7d < -10 and p24 < -2):
        return {
            "env":       "bear",
            "label":     "BEAR MARKET",
            "color":     "bearish",
            "cap_score": 5.0,   # max score capped at 5 in bear market
            "penalty":   1.5,   # additional penalty to scores
            "warning":   "BTC in downtrend — all longs carry higher risk. Score capped at 5."
        }
    elif mood in ("slightly_bearish",) or p7d < -5:
        return {
            "env":       "caution",
            "label":     "CAUTION",
            "color":     "caution",
            "cap_score": 7.0,
            "penalty":   0.5,
            "warning":   "BTC showing weakness — be selective, reduce position sizes."
        }
    elif mood in ("bullish",) or (p7d > 5 and p24 > 0):
        return {
            "env":       "bull",
            "label":     "BULL MARKET",
            "color":     "bullish",
            "cap_score": 10.0,
            "penalty":   0,
            "warning":   None
        }
    else:
        return {
            "env":       "neutral",
            "label":     "NEUTRAL",
            "color":     "neutral",
            "cap_score": 8.0,
            "penalty":   0,
            "warning":   None
        }

# ─── SIGNAL ENGINE v2 ────────────────────────────────────────────────────────
def calculate_trading_signal(coin: dict, rsi_cache: dict = None,
                              vol_cache: dict = None,
                              market_env: dict = None) -> dict:
    """
    Score a coin 0-10 with 6 new improvements:
    1. EMA 200 position estimate
    2. BTC condition cap
    3. Min 3 confluences for Buy Watch
    4. Pump filter
    5. Market environment badge
    6. Score confidence label
    """
    score    = 0.0
    signals  = []
    warnings = []
    confidence_points = 0  # how many real data points we have

    p24  = coin.get("price_change_percentage_24h") or 0
    p7d  = coin.get("price_change_percentage_7d_in_currency") or 0
    p1h  = coin.get("price_change_percentage_1h_in_currency") or 0
    vol  = coin.get("total_volume") or 0
    mcap = coin.get("market_cap") or 0
    sym  = (coin.get("symbol") or "").upper()

    # Skip stablecoins entirely
    if sym in STABLECOINS:
        return {
            "score": 0, "verdict": "STABLECOIN", "verdict_color": "neutral",
            "verdict_icon": "⚪", "signals": [], "warnings": [],
            "rsi": None, "rsi_source": "n/a", "trend": "stable",
            "pullback": False, "vol_spike": False, "confluence": 0,
            "market_env": "neutral", "market_env_label": "N/A",
            "market_env_color": "neutral", "ema200_position": "unknown",
            "confidence": "N/A", "confidence_score": 0,
            "is_stablecoin": True,
        }

    sparkline = coin.get("sparkline_in_7d", {})
    prices    = sparkline.get("price", []) if isinstance(sparkline, dict) else []

    # ── RSI ──────────────────────────────────────────────────────────────────
    rsi = None
    rsi_source = "estimated"

    if rsi_cache and sym in rsi_cache:
        rsi = rsi_cache[sym]
        rsi_source = "real"
        confidence_points += 3  # real RSI = high confidence
    elif prices:
        rsi = calc_rsi_sparkline(prices)
        rsi_source = "sparkline"
        confidence_points += 1

    if rsi is None:
        if p7d < -20:   rsi = 22
        elif p7d < -10: rsi = 33
        elif p7d > 20:  rsi = 78
        elif p7d > 10:  rsi = 65
        else:           rsi = 50

    coin["rsi_value"]  = rsi
    coin["rsi_source"] = rsi_source

    if rsi <= 25:
        score += 3.0
        signals.append({"icon": "📉", "label": f"RSI Deeply Oversold ({rsi})", "type": "bullish",
                         "desc": f"Extreme selling exhaustion — potential bounce ({rsi_source})"})
    elif rsi <= 30:
        score += 2.5
        signals.append({"icon": "📉", "label": f"RSI Oversold ({rsi})", "type": "bullish",
                         "desc": f"Sellers exhausted — watch for reversal ({rsi_source})"})
    elif rsi <= 40:
        score += 1.0
        signals.append({"icon": "📊", "label": f"RSI Low ({rsi})", "type": "neutral",
                         "desc": f"RSI recovering from oversold ({rsi_source})"})
    elif rsi >= 75:
        score -= 2.5
        warnings.append({"icon": "⚠️", "label": f"RSI Extremely Overbought ({rsi})", "type": "bearish",
                          "desc": f"Very high reversal risk ({rsi_source})"})
    elif rsi >= 70:
        score -= 2.0
        warnings.append({"icon": "⚠️", "label": f"RSI Overbought ({rsi})", "type": "bearish",
                          "desc": f"Buyers exhausted ({rsi_source})"})
    elif rsi >= 60:
        score -= 0.5
        warnings.append({"icon": "📊", "label": f"RSI Elevated ({rsi})", "type": "caution",
                          "desc": "Getting high — careful chasing"})

    # ── TREND ────────────────────────────────────────────────────────────────
    trend = detect_trend(prices) if prices else (
        "uptrend" if p7d > 5 else "downtrend" if p7d < -5 else "sideways"
    )
    coin["trend"] = trend
    if prices: confidence_points += 1

    if trend == "uptrend":
        score += 2.0
        signals.append({"icon": "📈", "label": "Uptrend Active", "type": "bullish",
                         "desc": "Higher Highs + Higher Lows — bullish structure"})
    elif trend == "downtrend":
        score -= 2.0
        warnings.append({"icon": "📉", "label": "Downtrend Active", "type": "bearish",
                          "desc": "Lower Highs + Lower Lows — avoid buying"})
    else:
        signals.append({"icon": "↔️", "label": "Sideways / Ranging", "type": "neutral",
                         "desc": "No clear trend — wait for breakout"})

    # ── EMA 200 POSITION (NEW) ────────────────────────────────────────────────
    ema200_pos = estimate_ema200_position(prices, p7d)
    coin["ema200_position"] = ema200_pos

    if ema200_pos == "above":
        score += 2.0
        confidence_points += 1
        signals.append({"icon": "🏔️", "label": "Above EMA 200 (est.)", "type": "bullish",
                         "desc": "Price likely above the 200 EMA — long-term bullish"})
    elif ema200_pos == "below":
        score -= 2.0
        confidence_points += 1
        warnings.append({"icon": "⬇️", "label": "Below EMA 200 (est.)", "type": "bearish",
                          "desc": "Price likely below 200 EMA — long-term bearish, higher risk"})

    # ── PULLBACK ─────────────────────────────────────────────────────────────
    pullback = detect_pullback(prices) if prices else (
        trend == "uptrend" and -15 <= p24 <= -3
    )
    coin["is_pullback"] = pullback

    if pullback:
        score += 2.0
        signals.append({"icon": "🎯", "label": "Pullback to Support", "type": "bullish",
                         "desc": "Healthy dip in uptrend — buy-the-dip potential"})

    # ── PUMP FILTER (NEW) ─────────────────────────────────────────────────────
    if p7d > 30:
        score -= 2.0
        warnings.append({"icon": "🚨", "label": f"Pump Alert +{p7d:.0f}% in 7d", "type": "bearish",
                          "desc": "Already up 30%+ this week — high risk of reversal, do NOT chase"})
    elif p7d > 20:
        score -= 1.5
        warnings.append({"icon": "⚠️", "label": f"Extended +{p7d:.0f}% in 7d", "type": "caution",
                          "desc": "Up 20%+ this week — wait for pullback before entering"})
    elif p24 > 15:
        score -= 1.0
        warnings.append({"icon": "🚀", "label": f"Already up +{p24:.1f}% today", "type": "caution",
                          "desc": "Big move today — don't chase, wait for consolidation"})
    elif 3 <= p24 <= 15:
        score += 0.5
        signals.append({"icon": "✅", "label": f"Healthy gain +{p24:.1f}%", "type": "bullish",
                         "desc": "Steady move — not overextended"})
    elif p24 < -20:
        warnings.append({"icon": "💥", "label": f"Big drop {p24:.1f}%", "type": "bearish",
                          "desc": "Steep drop — wait for stabilisation"})

    confidence_points += 2  # price data always available

    # ── VOLUME ───────────────────────────────────────────────────────────────
    vol_spike  = False
    vol_source = "estimated"

    if vol_cache and sym in vol_cache:
        vp        = vol_cache[sym]
        vol_spike = vp.get("spike", False)
        ratio     = vp.get("ratio", 0)
        vol_source = f"real ({ratio}x avg)"
        confidence_points += 2
    else:
        if vol and mcap and mcap > 0:
            vol_spike  = (vol / mcap) > 0.20
            vol_source = "estimated"
            confidence_points += 1

    coin["volume_spike"] = vol_spike

    if vol_spike:
        if p24 > 0:
            score += 1.5
            signals.append({"icon": "🔥", "label": f"Volume Spike Bullish", "type": "bullish",
                             "desc": f"High volume on up move — real buyers ({vol_source})"})
        else:
            score -= 1.0
            warnings.append({"icon": "🔥", "label": f"Volume Spike Bearish", "type": "bearish",
                              "desc": f"High volume on down move — real selling ({vol_source})"})

    # ── MARKET CAP SAFETY ────────────────────────────────────────────────────
    if mcap < 500_000_000:
        score -= 1.0
        warnings.append({"icon": "⚠️", "label": "Small Cap — Higher Risk", "type": "caution",
                          "desc": "Under $500M — avoid as beginner"})
    elif mcap > 10_000_000_000:
        score += 0.5
        signals.append({"icon": "🏦", "label": "Large Cap (Safer)", "type": "bullish",
                         "desc": "Large cap — more liquid, cleaner patterns"})

    # ── BTC CONDITION CAP (NEW) ───────────────────────────────────────────────
    env = market_env or {"env": "unknown", "cap_score": 10, "penalty": 0, "warning": None,
                          "label": "UNKNOWN", "color": "neutral"}

    # Apply market environment penalty
    score -= env.get("penalty", 0)

    # Base score
    raw_score = round(max(0.0, score + 3.0), 1)

    # Cap score based on BTC condition
    cap = env.get("cap_score", 10)
    final_score = round(min(raw_score, cap), 1)

    if env.get("warning") and raw_score > cap:
        warnings.append({"icon": "₿", "label": f"Score capped — {env['label']}",
                          "type": "bearish", "desc": env["warning"]})

    # ── CONFLUENCE CHECK (NEW) ────────────────────────────────────────────────
    # Need minimum 3 bullish signals for Buy Watch
    bullish_count = len([s for s in signals if s["type"] == "bullish"])

    # ── VERDICT ──────────────────────────────────────────────────────────────
    if final_score >= 7.5 and bullish_count >= 3:
        verdict, color, icon = "STRONG BUY WATCH", "bullish", "🟢"
    elif final_score >= 6.0 and bullish_count >= 3:
        verdict, color, icon = "BUY WATCH",         "bullish", "🟡"
    elif final_score >= 6.0 and bullish_count < 3:
        # Has good score but not enough confluence
        verdict, color, icon = "WATCH — LOW CONFLUENCE", "caution", "🟠"
        warnings.append({"icon": "🔍", "label": "Low Confluence", "type": "caution",
                          "desc": f"Only {bullish_count}/3 required bullish signals — wait for more confirmation"})
    elif final_score >= 4.5:
        verdict, color, icon = "NEUTRAL — WAIT",    "neutral", "🔵"
    elif final_score >= 3.0:
        verdict, color, icon = "CAUTION",            "caution", "🟠"
    else:
        verdict, color, icon = "AVOID",              "bearish", "🔴"

    # ── CONFIDENCE LABEL (NEW) ───────────────────────────────────────────────
    max_points = 11
    conf_pct   = min(100, int(confidence_points / max_points * 100))
    if conf_pct >= 75:   conf_label = f"High ({conf_pct}%)"
    elif conf_pct >= 50: conf_label = f"Medium ({conf_pct}%)"
    else:                conf_label = f"Low ({conf_pct}%) — verify on chart"

    return {
        "score":             final_score,
        "raw_score":         raw_score,
        "verdict":           verdict,
        "verdict_color":     color,
        "verdict_icon":      icon,
        "signals":           signals,
        "warnings":          warnings,
        "rsi":               rsi,
        "rsi_source":        rsi_source,
        "trend":             trend,
        "pullback":          pullback,
        "vol_spike":         vol_spike,
        "confluence":        bullish_count,
        "ema200_position":   ema200_pos,
        "market_env":        env["env"],
        "market_env_label":  env["label"],
        "market_env_color":  env["color"],
        "confidence":        conf_label,
        "confidence_score":  conf_pct,
        "is_stablecoin":     False,
    }

# ─── PROCESS MARKET DATA ─────────────────────────────────────────────────────
def process_market_data(raw_coins: list, rsi_cache: dict = None,
                         vol_cache: dict = None, btc_data: dict = None) -> list:
    market_env = get_market_environment(btc_data or {})
    processed  = []

    for i, coin in enumerate(raw_coins):
        try:
            sym = (coin.get("symbol") or "").upper()
            if sym in STABLECOINS:
                continue  # skip stablecoins entirely

            p24 = coin.get("price_change_percentage_24h")
            p7d = coin.get("price_change_percentage_7d_in_currency")
            vol = coin.get("total_volume")
            mc  = coin.get("market_cap")

            signal   = calculate_trading_signal(coin, rsi_cache, vol_cache, market_env)
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
                "signal_ema200":      signal["ema200_position"],
                "signal_market_env":  signal["market_env"],
                "signal_env_label":   signal["market_env_label"],
                "signal_env_color":   signal["market_env_color"],
                "signal_confidence":  signal["confidence"],
                "signal_conf_score":  signal["confidence_score"],
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
        key_map = {
            "price": "current_price", "volume": "total_volume",
            "market_cap": "market_cap", "change": "price_change_percentage_24h",
            "score": "signal_score"
        }
        key = key_map.get(sort_by.replace("_asc","").replace("_desc",""), "market_cap")
        f   = sorted(f, key=lambda x: x.get(key) or 0, reverse=reverse)
    return f
