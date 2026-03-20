# 📊 TradeReady — Crypto Trading Dashboard

A personal crypto trading dashboard built with Python Flask. Helps you identify the best coins to trade by showing trending coins, market data, Fear & Greed Index, and individual coin charts.

---

## Features

- **Home page** — Live Fear & Greed Index, trending coins, top gainers, highest volume
- **Markets page** — Top 100 coins with search, sort, filter, pagination and sparkline charts
- **Coin page** — Individual coin with 7-day price chart, market stats, description and links
- **Trend signals** — Each coin gets a Bullish / Bearish / Neutral signal based on price action and volume
- **Auto-refresh** — Background cache refresh every 5 minutes
- **Manual refresh** — Refresh button in navbar

---

## Setup

### 1. Clone or download the project

```bash
cd crypto-trading-site
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Edit the `.env` file:

```
SECRET_KEY=your-secret-key-here
FLASK_ENV=development
FLASK_APP=app.py
COINGECKO_API_KEY=        # Optional — leave blank for free tier
CACHE_TIMEOUT=300         # Cache duration in seconds
```

### 4. Run locally

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

---

## Deployment (Free — Render.com)

1. Push all files to a GitHub repository
2. Go to [render.com](https://render.com) and sign up free
3. Click **New → Web Service**
4. Connect your GitHub repo
5. Set the following:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
   - **Environment:** Python 3
6. Add your environment variables in the Render dashboard
7. Click **Deploy** — your site will be live in ~2 minutes

---

## Deployment (Free — Railway.app)

1. Push all files to GitHub
2. Go to [railway.app](https://railway.app) and sign up
3. New Project → Deploy from GitHub repo
4. Add environment variables
5. Railway auto-detects Flask and deploys

---

## API Rate Limits

This app uses the **CoinGecko free API** (no key required):
- 10–30 calls per minute on the free tier
- The built-in cache prevents excessive calls
- All data is cached for 5 minutes by default

To get a free CoinGecko API key (higher limits):
1. Go to [coingecko.com/en/api](https://www.coingecko.com/en/api)
2. Sign up for a free Demo account
3. Add your key to `.env` as `COINGECKO_API_KEY`

Fear & Greed Index from [alternative.me](https://alternative.me/crypto/fear-and-greed-index/) — free, no key needed.

---

## File Structure

```
crypto-trading-site/
├── app.py                    # Main Flask app, routes, background refresh
├── config.py                 # Configuration from .env
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (don't commit this)
├── utils/
│   ├── api_client.py         # CoinGecko + Fear & Greed API wrapper
│   ├── data_processor.py     # Formatting, trend signals, filtering
│   └── cache.py              # In-memory cache with TTL
├── static/
│   ├── css/style.css         # Dark theme CSS
│   └── js/main.js            # Sparklines, search, auto-refresh
└── templates/
    ├── base.html             # Base layout, Bootstrap 5, Chart.js
    ├── index.html            # Homepage
    ├── markets.html          # Full markets table
    ├── coin.html             # Individual coin detail
    ├── error.html            # Error pages
    └── partials/
        ├── navbar.html
        ├── fear_greed_widget.html
        ├── coin_card.html
        └── trending_row.html
```

---

## Credits

- Market data: [CoinGecko API](https://www.coingecko.com)
- Fear & Greed: [Alternative.me](https://alternative.me)
- Charts: [Chart.js](https://www.chartjs.org)
- UI: [Bootstrap 5](https://getbootstrap.com)

---

## Disclaimer

This tool is for **educational and personal use only**. Nothing here is financial advice. Always do your own research before trading. Paper trade first.
