"""
utils/quant_engine.py — Quantitative Analysis Engine
Implements:
1. Volatility Detector (Bollinger Band Width + ATR)
2. Mean Reversion Score (Z-Score from 30-day mean)
3. Pattern Recognition (Higher Lows, Double Bottom, Consolidation, Breakout)
4. Probability Score (historical similar setups win rate)
5. Correlation Tracker (altcoin vs BTC lead/lag)
"""

import requests
import time
import math
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

CC_URL = "https://min-api.cryptocompare.com/data/v2/histoday"


# ─── DATA FETCHING ────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, limit: int = 60) -> list:
    """
    Fetch daily OHLCV from CryptoCompare.
    Returns list of {time, open, high, low, close, volume}
    """
    params = {
        "fsym":      symbol.upper(),
        "tsym":      "USDT",
        "limit":     limit,
        "aggregate": 1,
    }
    try:
        r = requests.get(CC_URL, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get("Response") == "Success":
                candles = data.get("Data", {}).get("Data", [])
                return [c for c in candles if c.get("close", 0) > 0]
        return []
    except Exception as e:
        logger.debug(f"OHLCV fetch error {symbol}: {e}")
        return []


def fetch_btc_ohlcv(limit: int = 60) -> list:
    return fetch_ohlcv("BTC", limit)


# ─── STATISTICAL HELPERS ─────────────────────────────────────────────────────
def mean(values: list) -> float:
    return sum(values) / len(values) if values else 0

def std_dev(values: list) -> float:
    if len(values) < 2: return 0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)

def rolling_mean(values: list, window: int) -> list:
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            result.append(mean(values[i-window+1:i+1]))
    return result

def rolling_std(values: list, window: int) -> list:
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            result.append(std_dev(values[i-window+1:i+1]))
    return result


# ─── 1. VOLATILITY DETECTOR ──────────────────────────────────────────────────
def calculate_volatility(candles: list) -> dict:
    """
    Bollinger Band Width + ATR to detect:
    - Unusually low volatility (squeeze) → big move incoming
    - Unusually high volatility → trending/explosive move
    """
    if not candles or len(candles) < 20:
        return {"status": "insufficient_data", "score": 0, "signal": None}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    # Bollinger Band Width (last 20 days)
    recent_closes = closes[-20:]
    bb_mean = mean(recent_closes)
    bb_std  = std_dev(recent_closes)
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std
    bb_width = (bb_upper - bb_lower) / bb_mean * 100 if bb_mean > 0 else 0

    # Historical BB width (previous 20 days before that)
    if len(closes) >= 40:
        hist_closes = closes[-40:-20]
        hist_std    = std_dev(hist_closes)
        hist_mean   = mean(hist_closes)
        hist_width  = (hist_mean + 2*hist_std - (hist_mean - 2*hist_std)) / hist_mean * 100 if hist_mean > 0 else 0
        width_ratio = bb_width / hist_width if hist_width > 0 else 1
    else:
        width_ratio = 1
        hist_width  = bb_width

    # ATR (Average True Range) — last 14 days
    true_ranges = []
    for i in range(1, min(15, len(candles))):
        prev_close = candles[-i-1]["close"]
        high       = candles[-i]["high"]
        low        = candles[-i]["low"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    atr     = mean(true_ranges) if true_ranges else 0
    atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0

    # SQUEEZE DETECTION — width ratio < 0.5 means volatility compressed
    is_squeeze  = width_ratio < 0.5
    is_breakout = width_ratio > 2.0
    is_elevated = atr_pct > 5

    if is_squeeze:
        signal = "squeeze"
        desc   = f"Volatility compressed to {width_ratio:.1f}x normal — big move building, direction unknown. Watch for breakout."
        score  = 7  # high attention needed
    elif is_breakout:
        signal = "expansion"
        desc   = f"Volatility expanding at {width_ratio:.1f}x normal — trending move in progress. Momentum trading opportunity."
        score  = 6
    elif is_elevated:
        signal = "elevated"
        desc   = f"ATR {atr_pct:.1f}% — elevated daily range. Higher risk but also higher reward potential."
        score  = 5
    else:
        signal = "normal"
        desc   = f"Normal volatility. BB width {bb_width:.1f}%."
        score  = 3

    return {
        "status":      "ok",
        "signal":      signal,
        "score":       score,
        "desc":        desc,
        "bb_width":    round(bb_width, 2),
        "hist_width":  round(hist_width, 2),
        "width_ratio": round(width_ratio, 2),
        "atr_pct":     round(atr_pct, 2),
        "is_squeeze":  is_squeeze,
        "is_expansion": is_breakout,
    }


# ─── 2. MEAN REVERSION SCORE ─────────────────────────────────────────────────
def calculate_mean_reversion(candles: list) -> dict:
    """
    Z-Score: how many standard deviations is current price
    from the 30-day mean. Beyond ±2 = statistically extreme.
    """
    if not candles or len(candles) < 30:
        return {"status": "insufficient_data", "z_score": 0, "signal": None}

    closes      = [c["close"] for c in candles]
    recent_30   = closes[-30:]
    current     = closes[-1]
    mu          = mean(recent_30)
    sigma       = std_dev(recent_30)

    z_score = (current - mu) / sigma if sigma > 0 else 0
    z_score = round(z_score, 2)

    # Distance from mean
    pct_from_mean = (current - mu) / mu * 100 if mu > 0 else 0

    if z_score <= -2.5:
        signal = "strong_reversion_up"
        desc   = f"Price is {abs(z_score):.1f} standard deviations BELOW 30-day mean ({abs(pct_from_mean):.1f}% below average). Statistically extreme — high probability of mean reversion upward."
        score  = 8
    elif z_score <= -1.5:
        signal = "reversion_up"
        desc   = f"Price is {abs(z_score):.1f} std devs below mean ({abs(pct_from_mean):.1f}% below average). Likely to revert upward toward ${mu:.2f}."
        score  = 6
    elif z_score >= 2.5:
        signal = "strong_reversion_down"
        desc   = f"Price is {z_score:.1f} std devs ABOVE 30-day mean ({pct_from_mean:.1f}% above average). Statistically extended — high probability of mean reversion downward."
        score  = -6
    elif z_score >= 1.5:
        signal = "reversion_down"
        desc   = f"Price is {z_score:.1f} std devs above mean. Likely to revert downward toward ${mu:.2f}."
        score  = -4
    else:
        signal = "neutral"
        desc   = f"Price near 30-day average (z-score {z_score:.1f}). No statistical edge."
        score  = 0

    return {
        "status":         "ok",
        "signal":         signal,
        "score":          score,
        "z_score":        z_score,
        "desc":           desc,
        "mean_30d":       round(mu, 4),
        "pct_from_mean":  round(pct_from_mean, 2),
        "current_price":  current,
    }


# ─── 3. PATTERN RECOGNITION ──────────────────────────────────────────────────
def detect_patterns(candles: list) -> dict:
    """
    Detect:
    - Higher Lows (accumulation)
    - Lower Highs (distribution)
    - Double Bottom (reversal)
    - Consolidation (tight range)
    - Ascending Triangle
    - Breakout
    """
    if not candles or len(candles) < 14:
        return {"patterns": [], "primary": None, "score": 0}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    patterns = []

    # ── HIGHER LOWS (bullish accumulation) ───────────────────────────────────
    recent_lows = lows[-10:]
    hl_count = sum(1 for i in range(1, len(recent_lows)) if recent_lows[i] > recent_lows[i-1])
    if hl_count >= 6:
        patterns.append({
            "name":  "Higher Lows",
            "type":  "bullish",
            "icon":  "📈",
            "score": 3,
            "desc":  f"Price forming higher lows ({hl_count}/9 days) — buyers stepping in at higher prices. Accumulation pattern."
        })

    # ── LOWER HIGHS (bearish distribution) ───────────────────────────────────
    recent_highs = highs[-10:]
    lh_count = sum(1 for i in range(1, len(recent_highs)) if recent_highs[i] < recent_highs[i-1])
    if lh_count >= 6:
        patterns.append({
            "name":  "Lower Highs",
            "type":  "bearish",
            "icon":  "📉",
            "score": -3,
            "desc":  f"Price forming lower highs ({lh_count}/9 days) — sellers controlling rallies. Distribution pattern."
        })

    # ── DOUBLE BOTTOM (reversal) ──────────────────────────────────────────────
    if len(lows) >= 20:
        segment     = lows[-20:]
        bottom1_idx = segment.index(min(segment[:10]))
        bottom2_idx = 10 + segment[10:].index(min(segment[10:]))
        bottom1     = segment[bottom1_idx]
        bottom2     = segment[bottom2_idx]
        similarity  = abs(bottom1 - bottom2) / bottom1 * 100 if bottom1 > 0 else 100

        if similarity < 3 and bottom2_idx > bottom1_idx + 3:
            patterns.append({
                "name":  "Double Bottom",
                "type":  "bullish",
                "icon":  "⚡",
                "score": 4,
                "desc":  f"Two similar lows ({similarity:.1f}% apart) — classic reversal pattern. Buyers defended same level twice."
            })

    # ── CONSOLIDATION (tight range = energy building) ─────────────────────────
    recent_14    = closes[-14:]
    range_pct    = (max(recent_14) - min(recent_14)) / mean(recent_14) * 100 if mean(recent_14) > 0 else 100
    if range_pct < 8:
        patterns.append({
            "name":  "Consolidation",
            "type":  "neutral",
            "icon":  "🔲",
            "score": 2,
            "desc":  f"Price in tight {range_pct:.1f}% range for 14 days — energy compressing. Breakout likely soon."
        })

    # ── BREAKOUT (price exceeds recent resistance) ────────────────────────────
    if len(closes) >= 20:
        resistance   = max(closes[-20:-1])
        current      = closes[-1]
        breakout_pct = (current - resistance) / resistance * 100

        if breakout_pct > 3:
            patterns.append({
                "name":  "Resistance Breakout",
                "type":  "bullish",
                "icon":  "🚀",
                "score": 5,
                "desc":  f"Price broke above 20-day resistance by {breakout_pct:.1f}%. Continuation move possible."
            })
        elif breakout_pct < -3:
            patterns.append({
                "name":  "Support Breakdown",
                "type":  "bearish",
                "icon":  "💥",
                "score": -4,
                "desc":  f"Price broke below 20-day support by {abs(breakout_pct):.1f}%. Further downside possible."
            })

    # ── ASCENDING TRIANGLE ────────────────────────────────────────────────────
    if len(candles) >= 15:
        recent_h = highs[-15:]
        recent_l = lows[-15:]
        flat_top = max(recent_h) - min(recent_h[5:]) < max(recent_h) * 0.02
        hl_check = recent_l[-1] > recent_l[0] and recent_l[-1] > recent_l[len(recent_l)//2]
        if flat_top and hl_check:
            patterns.append({
                "name":  "Ascending Triangle",
                "type":  "bullish",
                "icon":  "△",
                "score": 4,
                "desc":  "Flat resistance with rising lows — classic bullish continuation. Breakout likely upward."
            })

    # Pick primary pattern (highest absolute score)
    primary = max(patterns, key=lambda x: abs(x["score"])) if patterns else None
    total_score = sum(p["score"] for p in patterns)

    return {
        "patterns": patterns,
        "primary":  primary,
        "score":    total_score,
        "count":    len(patterns),
    }


# ─── 4. PROBABILITY SCORE ────────────────────────────────────────────────────
def calculate_probability(candles: list, rsi: float = None) -> dict:
    """
    Looks at historical instances where similar conditions occurred
    (RSI level + trend direction + volume) and calculates:
    - What % of the time did price go UP in next 3 days?
    - What was the average return?
    - How many similar setups found?
    """
    if not candles or len(candles) < 40:
        return {"status": "insufficient_data", "prob_up": 50, "sample_size": 0}

    closes  = [c["close"] for c in candles]
    volumes = [c["volumeto"] for c in candles]

    # Current conditions
    current_close  = closes[-1]
    current_vol    = volumes[-1]
    avg_vol        = mean(volumes[-30:])
    vol_ratio      = current_vol / avg_vol if avg_vol > 0 else 1
    recent_change  = (closes[-1] - closes[-5]) / closes[-5] * 100

    outcomes_up    = 0
    outcomes_total = 0
    returns        = []

    # Look back through history for similar setups
    for i in range(10, len(closes) - 3):
        hist_close = closes[i]
        hist_vol   = volumes[i]
        hist_avg_v = mean(volumes[max(0,i-30):i]) if i > 5 else avg_vol
        hist_vr    = hist_vol / hist_avg_v if hist_avg_v > 0 else 1
        hist_chg   = (closes[i] - closes[i-5]) / closes[i-5] * 100

        # Similar conditions: volume ratio within 50%, momentum direction same
        vol_similar   = abs(hist_vr - vol_ratio) < 0.5
        trend_similar = (hist_chg > 0) == (recent_change > 0)

        if vol_similar and trend_similar:
            # What happened 3 days later?
            future_return = (closes[i+3] - hist_close) / hist_close * 100
            outcomes_total += 1
            if future_return > 0:
                outcomes_up += 1
            returns.append(future_return)

    if outcomes_total < 5:
        return {
            "status":      "insufficient_samples",
            "prob_up":     50,
            "sample_size": outcomes_total,
            "avg_return":  0,
        }

    prob_up    = round(outcomes_up / outcomes_total * 100, 1)
    avg_return = round(mean(returns), 2)
    best_case  = round(max(returns), 2) if returns else 0
    worst_case = round(min(returns), 2) if returns else 0

    if prob_up >= 65:
        signal = "high_probability_long"
        desc   = f"In {outcomes_total} similar historical setups, price went UP {prob_up}% of the time. Average return: +{avg_return:.1f}% over 3 days."
    elif prob_up <= 35:
        signal = "high_probability_short"
        desc   = f"In {outcomes_total} similar historical setups, price went DOWN {100-prob_up}% of the time. Average return: {avg_return:.1f}% over 3 days."
    else:
        signal = "neutral"
        desc   = f"Mixed historical results ({outcomes_total} setups, {prob_up}% up). No strong statistical edge in either direction."

    return {
        "status":      "ok",
        "signal":      signal,
        "prob_up":     prob_up,
        "prob_down":   round(100 - prob_up, 1),
        "sample_size": outcomes_total,
        "avg_return":  avg_return,
        "best_case":   best_case,
        "worst_case":  worst_case,
        "desc":        desc,
    }


# ─── 5. CORRELATION TRACKER ──────────────────────────────────────────────────
def calculate_btc_correlation(coin_candles: list, btc_candles: list) -> dict:
    """
    Pearson correlation between coin and BTC returns.
    Also checks lead/lag — does coin move before or after BTC?
    """
    if not coin_candles or not btc_candles or len(coin_candles) < 20:
        return {"status": "insufficient_data", "correlation": 0, "lead_lag": "unknown"}

    # Align to same dates
    n = min(len(coin_candles), len(btc_candles), 30)
    coin_closes = [c["close"] for c in coin_candles[-n:]]
    btc_closes  = [c["close"] for c in btc_candles[-n:]]

    # Daily returns
    coin_returns = [(coin_closes[i] - coin_closes[i-1]) / coin_closes[i-1]
                    for i in range(1, len(coin_closes))]
    btc_returns  = [(btc_closes[i] - btc_closes[i-1]) / btc_closes[i-1]
                    for i in range(1, len(btc_closes))]

    if len(coin_returns) < 5 or len(btc_returns) < 5:
        return {"status": "insufficient_data", "correlation": 0}

    # Pearson correlation
    n2       = min(len(coin_returns), len(btc_returns))
    cr       = coin_returns[-n2:]
    br       = btc_returns[-n2:]
    mc, mb   = mean(cr), mean(br)
    num      = sum((x - mc) * (y - mb) for x, y in zip(cr, br))
    den      = math.sqrt(sum((x-mc)**2 for x in cr) * sum((y-mb)**2 for y in br))
    corr     = round(num / den, 3) if den > 0 else 0

    # Lead/lag — check if coin leads BTC by 1 day
    if len(cr) > 5 and len(br) > 5:
        # Correlation with coin shifted 1 day ahead (coin leads BTC)
        lag1_num = sum((cr[i-1] - mc) * (br[i] - mb) for i in range(1, n2))
        lag1_den = math.sqrt(sum((x-mc)**2 for x in cr[:-1]) * sum((y-mb)**2 for y in br[1:]))
        lag1_corr = round(lag1_num / lag1_den, 3) if lag1_den > 0 else 0

        # Correlation with coin shifted 1 day behind (BTC leads coin)
        lag2_num = sum((cr[i] - mc) * (br[i-1] - mb) for i in range(1, n2))
        lag2_den = math.sqrt(sum((x-mc)**2 for x in cr[1:]) * sum((y-mb)**2 for y in br[:-1]))
        lag2_corr = round(lag2_num / lag2_den, 3) if lag2_den > 0 else 0

        if lag1_corr > corr + 0.05:
            lead_lag = "leads_btc"
            lead_lag_desc = "This coin tends to MOVE BEFORE BTC — can be used as early signal"
        elif lag2_corr > corr + 0.05:
            lead_lag = "follows_btc"
            lead_lag_desc = "This coin FOLLOWS BTC — check BTC direction first"
        else:
            lead_lag = "simultaneous"
            lead_lag_desc = "Moves simultaneously with BTC"
    else:
        lead_lag = "unknown"
        lead_lag_desc = "Insufficient data for lead/lag"
        lag1_corr = 0
        lag2_corr = 0

    # Interpretation
    if corr >= 0.8:
        corr_desc = f"Very high BTC correlation ({corr:.2f}) — moves almost identical to BTC"
        corr_type = "very_high"
    elif corr >= 0.6:
        corr_desc = f"High BTC correlation ({corr:.2f}) — strongly influenced by BTC"
        corr_type = "high"
    elif corr >= 0.3:
        corr_desc = f"Moderate BTC correlation ({corr:.2f}) — partially independent"
        corr_type = "moderate"
    elif corr >= 0:
        corr_desc = f"Low BTC correlation ({corr:.2f}) — moves somewhat independently"
        corr_type = "low"
    else:
        corr_desc = f"Negative BTC correlation ({corr:.2f}) — tends to move OPPOSITE to BTC"
        corr_type = "negative"

    return {
        "status":         "ok",
        "correlation":    corr,
        "correlation_type": corr_type,
        "corr_desc":      corr_desc,
        "lead_lag":       lead_lag,
        "lead_lag_desc":  lead_lag_desc,
        "lag1_corr":      lag1_corr,
        "lag2_corr":      lag2_corr,
    }


# ─── FULL QUANT ANALYSIS ─────────────────────────────────────────────────────
def run_quant_analysis(symbol: str, btc_candles: list = None,
                        rsi: float = None) -> dict:
    """Run all 5 quant analyses for a single coin."""
    candles = fetch_ohlcv(symbol, limit=60)

    if not candles:
        return {
            "symbol":      symbol,
            "status":      "no_data",
            "volatility":  None,
            "mean_rev":    None,
            "patterns":    None,
            "probability": None,
            "correlation": None,
            "quant_score": 0,
            "quant_signal": "No data",
        }

    vol_data  = calculate_volatility(candles)
    mean_data = calculate_mean_reversion(candles)
    pat_data  = detect_patterns(candles)
    prob_data = calculate_probability(candles, rsi)
    corr_data = calculate_btc_correlation(candles, btc_candles or [])

    # Combined quant score
    q_score = 0
    if mean_data.get("status") == "ok":
        q_score += mean_data.get("score", 0) * 0.3
    if pat_data:
        q_score += pat_data.get("score", 0) * 0.3
    if prob_data.get("status") == "ok":
        prob = prob_data.get("prob_up", 50)
        q_score += (prob - 50) / 10 * 0.2  # 60% = +1, 70% = +2
    if vol_data.get("is_squeeze"):
        q_score += 1.5  # squeeze adds score regardless direction

    q_score = round(max(-5, min(5, q_score)), 1)

    if q_score >= 2:
        quant_signal = "Quant Bullish"
        quant_color  = "bullish"
    elif q_score <= -2:
        quant_signal = "Quant Bearish"
        quant_color  = "bearish"
    elif vol_data.get("is_squeeze"):
        quant_signal = "Volatility Squeeze"
        quant_color  = "caution"
    else:
        quant_signal = "Quant Neutral"
        quant_color  = "neutral"

    return {
        "symbol":       symbol,
        "status":       "ok",
        "volatility":   vol_data,
        "mean_rev":     mean_data,
        "patterns":     pat_data,
        "probability":  prob_data,
        "correlation":  corr_data,
        "quant_score":  q_score,
        "quant_signal": quant_signal,
        "quant_color":  quant_color,
    }


# ─── BATCH QUANT ─────────────────────────────────────────────────────────────
def run_quant_batch(symbols: list, btc_candles: list = None,
                     rsi_cache: dict = None) -> dict:
    """
    Run quant analysis on top N coins.
    Returns {SYMBOL: quant_result}
    """
    results = {}
    # Fetch BTC candles once for correlation
    if not btc_candles:
        btc_candles = fetch_btc_ohlcv(60)
        time.sleep(0.1)

    for symbol in symbols:
        try:
            rsi = (rsi_cache or {}).get(symbol.upper())
            result = run_quant_analysis(symbol, btc_candles, rsi)
            results[symbol.upper()] = result
            logger.debug(f"Quant {symbol}: {result['quant_signal']} ({result['quant_score']})")
        except Exception as e:
            logger.warning(f"Quant error {symbol}: {e}")
        time.sleep(0.15)  # respect rate limits

    logger.info(f"Quant batch complete: {len(results)}/{len(symbols)} coins")
    return results
