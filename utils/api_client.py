"""
utils/api_client.py — CoinMarketCap + Fear & Greed API wrapper
CMC Free tier: 10,000 credits/month
"""

import requests
import logging

logger = logging.getLogger(__name__)

CMC_BASE = "https://pro-api.coinmarketcap.com/v1"
FNG_URL  = "https://api.alternative.me/fng/?limit=7"
CMC_FNG  = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"


class CryptoAPI:
    def __init__(self, api_key: str = "", timeout: int = 10):
        self.api_key = api_key.strip() if api_key else ""
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Accept":       "application/json",
            "User-Agent":   "TradeReady/1.0",
        })
        if self.api_key:
            self.session.headers["X-CMC_PRO_API_KEY"] = self.api_key
            logger.info(f"CMC API key loaded: {self.api_key[:8]}...")
        else:
            logger.warning("No CMC API key set — add CMC_API_KEY to environment.")

    def _get(self, endpoint: str, params: dict = None):
        url = CMC_BASE + endpoint
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            logger.info(f"GET {endpoint} → {r.status_code}")
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                logger.error(f"401 Unauthorized — check CMC_API_KEY in Render env vars")
                return None
            if r.status_code == 429:
                logger.warning(f"Rate limited: {endpoint}")
                return None
            logger.warning(f"HTTP {r.status_code}: {endpoint} — {r.text[:200]}")
            return None
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout: {endpoint}")
            return None
        except Exception as e:
            logger.warning(f"Error: {endpoint} — {e}")
            return None

    def get_coin_markets(self, per_page: int = 100, page: int = 1,
                         order: str = "market_cap_desc") -> list:
        """Get top coins by market cap with price data."""
        params = {
            "start":   (page - 1) * per_page + 1,
            "limit":   per_page,
            "convert": "USD",
            "sort":    "market_cap",
            "sort_dir": "desc",
            "aux":     "cmc_rank,max_supply,circulating_supply,total_supply",
        }
        data = self._get("/cryptocurrency/listings/latest", params)
        if not data:
            return []

        coins = data.get("data", [])
        result = []
        for c in coins:
            quote = c.get("quote", {}).get("USD", {})
            result.append({
                "id":                               str(c.get("id")),
                "cmc_id":                           c.get("id"),
                "name":                             c.get("name"),
                "symbol":                           c.get("symbol", "").upper(),
                "slug":                             c.get("slug"),
                "image":                            self._logo_url(c.get("id")),
                "current_price":                    quote.get("price"),
                "market_cap":                       quote.get("market_cap"),
                "market_cap_rank":                  c.get("cmc_rank"),
                "total_volume":                     quote.get("volume_24h"),
                "price_change_percentage_1h_in_currency":  quote.get("percent_change_1h"),
                "price_change_percentage_24h":      quote.get("percent_change_24h"),
                "price_change_percentage_7d_in_currency":  quote.get("percent_change_7d"),
                "circulating_supply":               c.get("circulating_supply"),
                "sparkline_in_7d":                  {"price": []},  # CMC free tier no sparkline
            })
        logger.info(f"get_coin_markets: {len(result)} coins")
        return result

    def get_trending_coins(self) -> list:
        """Get trending/most visited coins from CMC."""
        params = {
            "start":   1,
            "limit":   10,
            "convert": "USD",
            "sort":    "percent_change_24h",
            "sort_dir": "desc",
        }
        data = self._get("/cryptocurrency/listings/latest", params)
        if not data:
            return []

        result = []
        for c in data.get("data", [])[:10]:
            quote  = c.get("quote", {}).get("USD", {})
            change = quote.get("percent_change_24h", 0)
            result.append({
                "id":     str(c.get("id")),
                "name":   c.get("name"),
                "symbol": c.get("symbol", "").upper(),
                "rank":   c.get("cmc_rank"),
                "thumb":  self._logo_url(c.get("id")),
                "small":  self._logo_url(c.get("id")),
                "data":   {
                    "price": quote.get("price"),
                    "price_change_percentage_24h": {"usd": change},
                },
            })
        return result

    def get_coin_details(self, coin_id: str) -> dict | None:
        """Get details for a single coin by CMC ID or slug."""
        # Try as numeric ID first, then slug
        params = {
            "convert": "USD",
            "aux": ("urls,logo,description,tags,platform,date_added,"
                    "notice,circulating_supply,total_supply,max_supply,"
                    "market_cap_by_total_supply,volume_24h_reported,"
                    "volume_7d,volume_7d_reported,volume_30d,volume_30d_reported"),
        }
        if coin_id.isdigit():
            params["id"] = coin_id
        else:
            params["slug"] = coin_id

        data = self._get("/cryptocurrency/info", params)
        if not data:
            return None

        coins = data.get("data", {})
        if not coins:
            return None

        # Get first result
        cmc_data = list(coins.values())[0]
        cmc_id   = cmc_data.get("id")

        # Get quote data separately
        quote_params = {"id": cmc_id, "convert": "USD"}
        quote_data = self._get("/cryptocurrency/quotes/latest", quote_params)
        quote = {}
        if quote_data:
            qd    = quote_data.get("data", {}).get(str(cmc_id), {})
            quote = qd.get("quote", {}).get("USD", {})

        # Build a response compatible with our templates
        urls  = cmc_data.get("urls", {})
        logo  = cmc_data.get("logo", "")
        price = quote.get("price", 0)
        c24   = quote.get("percent_change_24h", 0)
        c7d   = quote.get("percent_change_7d", 0)
        mcap  = quote.get("market_cap", 0)
        vol   = quote.get("volume_24h", 0)
        cs    = cmc_data.get("circulating_supply", 0)
        ath   = quote.get("ath", None)

        return {
            "id":     str(cmc_id),
            "name":   cmc_data.get("name"),
            "symbol": cmc_data.get("symbol", "").upper(),
            "image":  {"large": logo, "small": logo, "thumb": logo},
            "market_cap_rank": quote.get("market_cap_dominance"),
            "description": {"en": cmc_data.get("description", "")},
            "links": {
                "homepage":       urls.get("website", []),
                "blockchain_site": urls.get("explorer", []),
                "subreddit_url":  urls.get("reddit", [""])[0] if urls.get("reddit") else "",
                "twitter":        urls.get("twitter", []),
            },
            "market_data": {
                "current_price":               {"usd": price},
                "price_change_percentage_24h": c24,
                "price_change_percentage_7d":  c7d,
                "market_cap":                  {"usd": mcap},
                "total_volume":                {"usd": vol},
                "circulating_supply":          cs,
                "ath":                         {"usd": ath},
                "ath_date":                    {"usd": None},
                "high_24h":                    {"usd": quote.get("high_24h")},
                "low_24h":                     {"usd": quote.get("low_24h")},
                "sparkline_7d":                {"price": []},
            },
        }

    def get_simple_price(self, coin_ids: list) -> dict:
        params = {"id": ",".join(coin_ids), "convert": "USD"}
        data = self._get("/cryptocurrency/quotes/latest", params)
        if not data:
            return {}
        result = {}
        for cid, info in data.get("data", {}).items():
            q = info.get("quote", {}).get("USD", {})
            result[cid] = {
                "usd":            q.get("price"),
                "usd_24h_change": q.get("percent_change_24h"),
            }
        return result

    def get_fear_greed(self) -> dict:
        """
        Get Fear & Greed from CoinMarketCap (matches their website exactly).
        Tries both CMC endpoints, falls back to alternative.me.
        """
        if self.api_key:
            # Try CMC latest endpoint first (single current value)
            try:
                headers = {"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"}

                # Get latest value
                r_latest = requests.get(
                    "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest",
                    headers=headers, timeout=6
                )
                logger.info(f"CMC F&G latest → {r_latest.status_code}")

                if r_latest.status_code == 200:
                    latest = r_latest.json().get("data", {})
                    if latest:
                        current_val = int(float(latest.get("value", 50)))
                        current_cls = latest.get("value_classification", "Neutral")
                        logger.info(f"CMC F&G: {current_val} — {current_cls}")

                        # Get historical for yesterday/last week
                        r_hist = requests.get(
                            "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical",
                            params={"limit": 8},
                            headers=headers, timeout=6
                        )
                        yesterday = None
                        last_week = None
                        history = []

                        if r_hist.status_code == 200:
                            hist_data = r_hist.json().get("data", [])
                            if len(hist_data) > 1:
                                yesterday = int(float(hist_data[1].get("value", 50)))
                            if len(hist_data) > 7:
                                last_week = int(float(hist_data[7].get("value", 50)))
                            history = [{"value": int(float(d.get("value", 50))),
                                        "class": d.get("value_classification", "")}
                                       for d in hist_data]

                        return {
                            "value":     current_val,
                            "class":     current_cls,
                            "yesterday": yesterday,
                            "last_week": last_week,
                            "history":   history,
                        }

            except Exception as e:
                logger.warning(f"CMC F&G failed: {e} — falling back to alternative.me")

        # Fallback to alternative.me
        logger.info("Using alternative.me for F&G")
        return self._alt_fear_greed()

    def _alt_fear_greed(self) -> dict:
        try:
            r = requests.get(FNG_URL, timeout=6)
            if r.status_code != 200:
                return self._fg_fallback()
            data = r.json().get("data", [])
            if not data:
                return self._fg_fallback()
            c = data[0]
            return {
                "value":     int(c["value"]),
                "class":     c["value_classification"],
                "yesterday": int(data[1]["value"]) if len(data) > 1 else None,
                "last_week": int(data[6]["value"]) if len(data) > 6 else None,
                "history":   [{"value": int(d["value"]),
                               "class": d["value_classification"]} for d in data],
            }
        except Exception as e:
            logger.warning(f"alternative.me F&G failed: {e}")
            return self._fg_fallback()


    def get_global_metrics(self) -> dict:
        """
        Get global crypto market metrics:
        - BTC dominance %
        - Total market cap
        - BTC price + 24h change
        Uses CMC /v1/global-metrics/quotes/latest
        """
        try:
            data = self._get("/global-metrics/quotes/latest", {"convert": "USD"})
            if not data:
                return self._global_fallback()

            gd    = data.get("data", {})
            quote = gd.get("quote", {}).get("USD", {})

            btc_dom     = gd.get("btc_dominance", 0)
            btc_dom_24h = gd.get("btc_dominance_24h_percentage_change", 0)
            total_mcap  = quote.get("total_market_cap", 0)
            mcap_change = quote.get("total_market_cap_yesterday_percentage_change", 0)
            volume_24h  = quote.get("total_volume_24h", 0)

            # BTC market context
            if btc_dom > 55:
                btc_signal = "BTC Season"
                btc_signal_desc = "Bitcoin dominates — altcoins likely underperforming"
                btc_signal_color = "warning"
            elif btc_dom < 45:
                btc_signal = "Altcoin Season"
                btc_signal_desc = "Altcoins gaining — good time to look at alts"
                btc_signal_color = "success"
            else:
                btc_signal = "Neutral"
                btc_signal_desc = "Market balanced between BTC and alts"
                btc_signal_color = "info"

            # Dominance trend
            if btc_dom_24h > 0.5:
                dom_trend = "rising"
                dom_desc  = "BTC dominance rising — money flowing INTO Bitcoin, alts may drop"
            elif btc_dom_24h < -0.5:
                dom_trend = "falling"
                dom_desc  = "BTC dominance falling — money flowing INTO altcoins"
            else:
                dom_trend = "stable"
                dom_desc  = "BTC dominance stable — no major rotation happening"

            logger.info(f"Global metrics: BTC dom {btc_dom:.1f}% ({dom_trend})")

            return {
                "btc_dominance":       round(btc_dom, 2),
                "btc_dominance_24h":   round(btc_dom_24h, 2),
                "btc_signal":          btc_signal,
                "btc_signal_desc":     btc_signal_desc,
                "btc_signal_color":    btc_signal_color,
                "dom_trend":           dom_trend,
                "dom_desc":            dom_desc,
                "total_market_cap":    total_mcap,
                "market_cap_change":   round(mcap_change, 2),
                "total_volume_24h":    volume_24h,
            }
        except Exception as e:
            logger.warning(f"Global metrics failed: {e}")
            return self._global_fallback()

    def get_btc_data(self) -> dict:
        """Get BTC price + 24h change + 7d change for market context."""
        try:
            params = {"id": "1", "convert": "USD"}
            data   = self._get("/cryptocurrency/quotes/latest", params)
            if not data:
                return {}
            btc   = data.get("data", {}).get("1", {})
            quote = btc.get("quote", {}).get("USD", {})
            p24   = quote.get("percent_change_24h", 0)
            p7d   = quote.get("percent_change_7d", 0)
            price = quote.get("price", 0)

            # BTC trend interpretation
            if p24 > 3:
                btc_mood = "bullish"
                btc_mood_desc = f"BTC up {p24:.1f}% today — market likely bullish"
            elif p24 < -3:
                btc_mood = "bearish"
                btc_mood_desc = f"BTC down {p24:.1f}% today — avoid altcoins, wait"
            elif p24 > 0:
                btc_mood = "slightly_bullish"
                btc_mood_desc = f"BTC slightly up +{p24:.1f}% — cautious optimism"
            else:
                btc_mood = "slightly_bearish"
                btc_mood_desc = f"BTC slightly down {p24:.1f}% — be selective"

            return {
                "price":     price,
                "change24":  p24,
                "change7d":  p7d,
                "mood":      btc_mood,
                "mood_desc": btc_mood_desc,
            }
        except Exception as e:
            logger.warning(f"BTC data failed: {e}")
            return {}

    def _global_fallback(self) -> dict:
        return {
            "btc_dominance": 0, "btc_dominance_24h": 0,
            "btc_signal": "Unknown", "btc_signal_desc": "Data unavailable",
            "btc_signal_color": "secondary", "dom_trend": "unknown",
            "dom_desc": "", "total_market_cap": 0,
            "market_cap_change": 0, "total_volume_24h": 0,
        }

    def _logo_url(self, cmc_id) -> str:
        if not cmc_id:
            return ""
        return f"https://s2.coinmarketcap.com/static/img/coins/64x64/{cmc_id}.png"

    def _fg_fallback(self) -> dict:
        return {"value": 50, "class": "Neutral",
                "yesterday": None, "last_week": None, "history": []}
