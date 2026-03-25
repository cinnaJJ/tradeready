"""
TradeReady Crypto — Main Flask Application
Real RSI from Binance (free) + Market data from CMC/CoinGecko
"""

from flask import Flask, render_template, jsonify, request, abort
from config import Config
from utils.api_client import CryptoAPI
from utils.cache import Cache
from utils.data_processor import (
    format_currency, format_percentage, process_market_data,
    get_market_environment
)
from utils.binance_rsi import fetch_rsi_batch, fetch_volume_batch
from utils.quant_engine import run_quant_batch, fetch_btc_ohlcv
import threading
import time
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app   = Flask(__name__)
app.config.from_object(Config)
api   = CryptoAPI(api_key=Config.CMC_API_KEY)
cache = Cache()

print(f"[Config] CMC_API_KEY = {'SET ✅' if Config.CMC_API_KEY else 'NOT SET ❌'}")

# ─── CSP HEADERS ─────────────────────────────────────────────────────────────
@app.after_request
def set_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net "
                   "https://fonts.googleapis.com "
                   "https://fonts.gstatic.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com "
                  "https://cdn.jsdelivr.net data:; "
        "img-src 'self' https: data: blob:; "
        "connect-src 'self' https://api.alternative.me "
                     "https://api.coingecko.com "
                     "https://pro-api.coinmarketcap.com;"
    )
    return response

# ─── BACKGROUND REFRESH ───────────────────────────────────────────────────────
def refresh_all():
    logger.info("Fetch cycle starting...")

    # Fear & Greed
    try:
        fg = api.get_fear_greed()
        if fg: cache.set("fear_greed", fg)
        logger.info(f"F&G: {fg['value'] if fg else 'failed'}")
    except Exception as e:
        logger.warning(f"F&G failed: {e}")

    time.sleep(2)

    # Market data
    try:
        mk = api.get_coin_markets(per_page=100)
        if mk:
            cache.set("markets", mk)
            logger.info(f"Markets: {len(mk)} coins cached")
        else:
            logger.warning("Markets: empty response")
    except Exception as e:
        logger.warning(f"Markets failed: {e}")

    time.sleep(2)

    time.sleep(2)

    # Global metrics + BTC dominance
    try:
        gm = api.get_global_metrics()
        if gm: cache.set("global_metrics", gm)
        btc = api.get_btc_data()
        if btc: cache.set("btc_data", btc)
        logger.info(f"Global: BTC dom {gm.get('btc_dominance', '?')}% | BTC {btc.get('mood', '?')}")
    except Exception as e:
        logger.warning(f"Global metrics failed: {e}")

    time.sleep(2)

    # Binance RSI + Volume — runs after markets so we have symbols
    try:
        mk = cache.get("markets") or []
        if mk:
            symbols = [(c.get("symbol") or "").upper() for c in mk[:50]]
            symbols = [s for s in symbols if s]

            logger.info(f"Fetching Binance RSI for {len(symbols)} coins...")
            rsi_data = fetch_rsi_batch(symbols, interval="1d")
            if rsi_data:
                cache.set("rsi_cache", rsi_data)
                logger.info(f"Binance RSI: {len(rsi_data)} coins")

            time.sleep(2)

            logger.info(f"Fetching Binance volume for {len(symbols)} coins...")
            vol_data = fetch_volume_batch(symbols)
            if vol_data:
                cache.set("vol_cache", vol_data)
                logger.info(f"Binance volume: {len(vol_data)} coins")

    except Exception as e:
        logger.warning(f"Binance RSI/Volume failed: {e}")

    time.sleep(2)

    # Quant analysis — top 30 coins
    try:
        mk = cache.get("markets") or []
        if mk:
            symbols    = [(c.get("symbol") or "").upper() for c in mk[:30]]
            symbols    = [s for s in symbols if s]
            rsi_cache  = cache.get("rsi_cache") or {}
            btc_candles = fetch_btc_ohlcv(60)
            quant_data  = run_quant_batch(symbols, btc_candles, rsi_cache)
            if quant_data:
                cache.set("quant_cache", quant_data)
                logger.info(f"Quant analysis: {len(quant_data)} coins")
    except Exception as e:
        logger.warning(f"Quant failed: {e}")

    logger.info("Fetch cycle complete.")


def background_loop():
    logger.info("Background thread started — first fetch in 5s")
    time.sleep(5)
    while True:
        refresh_all()
        interval = 60 if Config.CMC_API_KEY else 120
        logger.info(f"Next refresh in {interval}s")
        time.sleep(interval)


_started = False
def ensure_thread():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=background_loop, daemon=True).start()

ensure_thread()

# ─── CONTEXT PROCESSORS ──────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    fg = cache.get("fear_greed")
    if not fg:
        try:
            fg = api.get_fear_greed()
            if fg: cache.set("fear_greed", fg)
        except Exception:
            pass
    gm  = cache.get("global_metrics") or {}
    btc = cache.get("btc_data") or {}
    return dict(
        fear_greed=fg or {"value": 50, "class": "Neutral",
                          "yesterday": None, "last_week": None},
        global_metrics=gm,
        btc_data=btc,
        format_currency=format_currency,
        format_percentage=format_percentage,
    )

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def get_processed_coins():
    """Get market data with real RSI, volume, BTC condition and quant data injected."""
    markets    = cache.get("markets") or []
    rsi_cache  = cache.get("rsi_cache") or {}
    vol_cache  = cache.get("vol_cache") or {}
    btc_data   = cache.get("btc_data") or {}
    quant_cache = cache.get("quant_cache") or {}
    processed  = process_market_data(markets, rsi_cache, vol_cache, btc_data)

    # Inject quant data into each coin
    for coin in processed:
        sym  = (coin.get("symbol") or "").upper()
        quant = quant_cache.get(sym)
        if quant:
            coin["quant"] = quant
            coin["quant_score"]  = quant.get("quant_score", 0)
            coin["quant_signal"] = quant.get("quant_signal", "")
            coin["quant_color"]  = quant.get("quant_color", "neutral")
        else:
            coin["quant"] = None
            coin["quant_score"]  = 0
            coin["quant_signal"] = ""
            coin["quant_color"]  = "neutral"
    return processed

# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    markets = cache.get("markets") or []
    loading = not bool(markets)
    processed = get_processed_coins()

    strong_buys = [c for c in processed if c.get("signal_score", 0) >= 7.5][:6]
    buy_watches = [c for c in processed if 6 <= c.get("signal_score", 0) < 7.5][:6]
    pullbacks   = [c for c in processed
                   if c.get("signal_pullback") and c.get("signal_score", 0) >= 5][:6]
    vol_spikes  = [c for c in processed
                   if c.get("signal_vol_spike") and
                   c.get("price_change_percentage_24h", 0) > 0 and
                   c.get("signal_score", 0) >= 4][:6]
    oversold    = sorted(
        [c for c in processed if c.get("signal_rsi") and c["signal_rsi"] <= 30],
        key=lambda x: x.get("signal_rsi", 100)
    )[:6]
    overbought  = sorted(
        [c for c in processed if c.get("signal_rsi") and c["signal_rsi"] >= 70],
        key=lambda x: x.get("signal_rsi", 0), reverse=True
    )[:6]

    coins_summary = None
    if processed:
        coins_summary = {
            "strong_buy": len([c for c in processed if c.get("signal_score", 0) >= 7.5]),
            "buy_watch":  len([c for c in processed if 6 <= c.get("signal_score", 0) < 7.5]),
            "neutral":    len([c for c in processed if 4.5 <= c.get("signal_score", 0) < 6]),
            "avoid":      len([c for c in processed if c.get("signal_score", 0) < 3]),
            "uptrends":   len([c for c in processed if c.get("signal_trend") == "uptrend"]),
            "pullbacks":  len([c for c in processed if c.get("signal_pullback")]),
            "vol_spikes": len([c for c in processed if c.get("signal_vol_spike")]),
            "oversold":   len([c for c in processed if c.get("signal_rsi") and c["signal_rsi"] <= 30]),
            "overbought": len([c for c in processed if c.get("signal_rsi") and c["signal_rsi"] >= 70]),
        }

    btc_data   = cache.get("btc_data") or {}
    market_env = get_market_environment(btc_data)

    return render_template("index.html",
        loading=loading,
        last_updated=cache.get_timestamp("markets"),
        strong_buys=strong_buys,
        buy_watches=buy_watches,
        pullbacks=pullbacks,
        vol_spikes=vol_spikes,
        oversold=oversold,
        overbought=overbought,
        coins_summary=coins_summary,
        market_env=market_env,
    )


@app.route("/markets")
def markets():
    page     = request.args.get("page", 1, type=int)
    sort_by  = request.args.get("sort", "market_cap_desc")
    search   = request.args.get("q", "").strip().lower()
    per_page = 20

    processed = get_processed_coins()

    if search:
        processed = [c for c in processed if
            search in c.get("name","").lower() or
            search in c.get("symbol","").lower()]

    sort_map = {
        "market_cap_desc":  ("market_cap", True),
        "market_cap_asc":   ("market_cap", False),
        "price_desc":       ("current_price", True),
        "price_asc":        ("current_price", False),
        "change_desc":      ("price_change_percentage_24h", True),
        "change_asc":       ("price_change_percentage_24h", False),
        "change_7d_desc":   ("price_change_percentage_7d_in_currency", True),
        "change_7d_asc":    ("price_change_percentage_7d_in_currency", False),
        "change_1h_desc":   ("price_change_percentage_1h_in_currency", True),
        "change_1h_asc":    ("price_change_percentage_1h_in_currency", False),
        "volume_desc":      ("total_volume", True),
        "volume_asc":       ("total_volume", False),
        "score_desc":       ("signal_score", True),
        "score_asc":        ("signal_score", False),
        "rsi_asc":          ("signal_rsi", True),   # lowest RSI first = most oversold
        "rsi_desc":         ("signal_rsi", False),
    }

    if sort_by in sort_map:
        key, reverse = sort_map[sort_by]
        processed = sorted(processed, key=lambda x: x.get(key) or 0, reverse=reverse)

    total       = len(processed)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page        = max(1, min(page, total_pages))
    paginated   = processed[(page-1)*per_page : page*per_page]

    return render_template("markets.html",
        coins=paginated, page=page, total_pages=total_pages,
        total=total, sort_by=sort_by, search=search, per_page=per_page,
        loading=not bool(cache.get("markets")),
    )


@app.route("/coin/<coin_id>")
def coin(coin_id):
    detail = api.get_coin_details(coin_id)
    if not detail: abort(404)
    processed = get_processed_coins()
    similar   = [c for c in processed if c.get("id") != coin_id][:6]
    return render_template("coin.html", coin=detail, similar=similar)


# ─── API ENDPOINTS ────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    mk = cache.get("markets") or []
    return jsonify({
        "markets":       bool(mk),
        "markets_count": len(mk),
        "rsi_ready":     bool(cache.get("rsi_cache")),
        "vol_ready":     bool(cache.get("vol_cache")),
        "last_updated":  cache.get_timestamp("markets"),
    })

@app.route("/api/fear-greed")
def api_fear_greed():
    return jsonify(cache.get("fear_greed") or api.get_fear_greed() or {})

@app.route("/api/markets")
def api_markets():
    processed = get_processed_coins()
    result = [{
        "id":       c.get("id"),
        "name":     c.get("name"),
        "symbol":   (c.get("symbol") or "").upper(),
        "price":    c.get("current_price"),
        "change24": c.get("price_change_percentage_24h"),
        "score":    c.get("signal_score"),
        "verdict":  c.get("signal_verdict"),
    } for c in processed]
    return jsonify({"data": result, "last_updated": cache.get_timestamp("markets")})

@app.route("/api/trending")
def api_trending():
    return jsonify(cache.get("trending") or [])

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    threading.Thread(target=refresh_all, daemon=True).start()
    return jsonify({"status": "ok", "message": "Refresh started"})

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500: {e}")
    return render_template("error.html", code=500, message="Something went wrong."), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
