# Stock Analyzer — Technical Analysis, Scanners & AI Market Outlook

[![CI](https://github.com/consciousmediacm-dev/stockIQ-Analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/consciousmediacm-dev/stockIQ-Analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-FF4B4B)](https://streamlit.io)

> A web app for technical analysis — moving averages, RSI, Fibonacci retracements, candlestick
> patterns, options intelligence, market scanners, signal backtesting and AI-powered outlooks.
>
> Built on [StockIQ](https://github.com/Mamun/stockIQ) by Mamun (MIT licensed). The product name
> and branding are configured in `config/brand.yml`.

---

## Features

### Market

| Page | What it does |
|------|-------------|
| **SPY Dashboard** | Real-time SPY price with data timestamp (Yahoo + CBOE parallel fetch, freshest wins), index strip (S&P 500 / Nasdaq / Dow / Russell / VIX), RSI summary card, candlestick chart with VWAP (intraday) and options levels (daily), Options Intelligence section (Put/Call ratio by scope, Max Pain, OI butterfly), SPY gap table, and VIX Fear Gauge |
| **SPY AI Outlook** | AI-powered 10-day SPY directional forecast — choose from **5 providers**: Groq (Llama 3.3 70B, free), Gemini 2.5 Flash (Google, free), DeepSeek-V3 (DeepSeek), GPT-4.1 Mini (OpenAI), or Claude (Anthropic). Context includes gaps, RSI, price action, key levels, and options flow (max pain, call/put wall) |
| **SPY Gap Table** | Every daily gap since 2022, live fill status, intraday High/Low, RSI, and next-day direction — shareable standalone URL |

### S&P 500 Tools

| Page | What it does |
|------|-------------|
| **Stock Analyzer** | Interactive candlestick chart with MA5/20/50/100/200, weekly MA200, RSI subplot, Fibonacci retracement, 7 reversal patterns, Golden/Death cross, neutral indicator readout (no buy/sell verdict — see Backtesting) |
| **Candle Screener** | Top 50 S&P 500 stocks ranked by candle pattern strength (Strong Buy → Sell), weekly and monthly views |

### Scanners

| Page | What it does |
|------|-------------|
| **Market Screener (all US)** | Every active US-listed stock and ETF (~10k), refreshed nightly: filter by type, exchange, price, liquidity, RSI, moving-average position, candle signal, MA200 distance, 52-week high; one click opens the Analyzer |
| **Pre-Market Scanner** | NASDAQ-100 pre-market movers with a 7-day daily close heatmap |
| **NASDAQ RSI Scanner** | NASDAQ-100 stocks filtered by RSI — quickly spot oversold / overbought conditions |
| **Short Squeeze Scanner** | High RSI + short interest = potential short squeeze candidates |
| **Analyst Buy Picks** | Highest-rated S&P 500 stocks by analyst consensus with ≥5% upside to price target |
| **Analyst Sell Picks** | Most-downgraded stocks with ≥5% downside to price target |
| **Munger Value Picks** | Quality companies (ROE, margins, growth, low debt) near their 200-week MA |
| **ETF Scanner** | Curated ETF categories — Retail Favorites, Semiconductors, Software — ranked by RSI and momentum |

---

## Screenshots

### SPY Dashboard
Full-page market hub: live SPY price with data timestamp, index strip, candlestick chart with VWAP, Options Intelligence (Max Pain, Put/Call ratio, OI butterfly), gap table, and VIX Fear Gauge.

![SPY Gap Table](docs/screenshots/spy_gaptable.png)

---

### AI-Powered SPY Outlook
Choose your AI provider — Groq, Gemini, DeepSeek, OpenAI, or Claude. The model analyses recent gaps, RSI, price action, and options flow (max pain, call/put wall) to generate a 10-day directional outlook with key levels and a plain-English rationale.

![SPY AI Forecast](docs/screenshots/spy_ai_claude_forecast.png)

---

### Stock Analyzer
Interactive candlestick chart with MA5/20/50/100/200, weekly MA200, RSI subplot, Fibonacci retracement, seven reversal patterns, and a neutral indicator readout.

![Stock Analyzer](docs/screenshots/analyzer.png)

---

### ETF Scanner
Curated ETF categories — Retail Favorites, Semiconductors, Software — ranked by RSI and momentum for quick sector rotation ideas.

![ETF Scanner](docs/screenshots/etf_scanner.png)

---

## Quick Start

### Prerequisites

- Python 3.11 or 3.12
- An API key for at least one AI provider (only required for the AI Outlook page — see Configuration below)

### Installation

```bash
git clone https://github.com/consciousmediacm-dev/stockIQ-Analyzer.git
cd stockIQ-Analyzer

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -e .            # installs the stockiq package + all dependencies
```

### Configuration

Create `.streamlit/secrets.toml` and add the API keys for the providers you want to use.
At least one AI provider key is needed for the SPY AI Outlook page — all free-tier providers work out of the box:

```toml
# AI providers — add whichever you want to use (all optional individually)
GROQ_API_KEY      = "gsk_..."        # free — console.groq.com/keys
GOOGLE_API_KEY    = "AIza..."        # free — aistudio.google.com/apikey
DEEPSEEK_API_KEY  = "sk-..."         # platform.deepseek.com/api_keys
OPENAI_API_KEY    = "sk-proj-..."    # platform.openai.com/api-keys
ANTHROPIC_API_KEY = "sk-ant-..."     # console.anthropic.com/settings/keys
```

Market data — Yahoo Finance is used by default (free, no key). Add Alpha Vantage as an
automatic fallback (and for the all-US universe) with:

```toml
ALPHA_VANTAGE_API_KEY = "..."        # alphavantage.co/support/#api-key
ALPHA_VANTAGE_PREMIUM = "true"       # paid plan: split-adjusted history + higher rate limits
```

The free Alpha Vantage tier is 25 requests/day and returns *unadjusted* prices, so it is only
a last-resort fallback; a premium key is needed for real use. Provider order lives in
`src/stockiq/backend/config/app.yml` (`history.providers`). Every response is validated
(duplicates, bad prices, High/Low repairs, split-like jumps) and tickers one provider can't
serve fall through to the next.

Or set keys as environment variables:

```bash
export GROQ_API_KEY="gsk_..."
```

### Run

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### Docker

```bash
cp .env.example .env          # add whichever keys you have
docker compose up --build     # → http://localhost:8501
```

The compose file mounts a volume at `/data` and uses the SQLite cache, so caches, the
AI forecast track record and backtest prices survive restarts.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ALPHA_VANTAGE_API_KEY` | — | Market-data failover + all-US ticker universe |
| `ALPHA_VANTAGE_PREMIUM` | `false` | `true` on a paid plan: adjusted history, higher rate limits |
| `GROQ_API_KEY`, `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | — | AI Outlook providers |
| `STOCKIQ_MODEL_<PROVIDER>` | see `llm/providers.py` | Override a provider's model ID |
| `STOCKIQ_DATA_DIR` | `~/.stockiq` | Caches, forecast log, backtest prices |
| `STOCKIQ_CACHE_BACKEND` | `memory` | `sqlite` to keep caches across restarts |
| `STOCKIQ_LOG_LEVEL` | `INFO` | Log verbosity |
| `SCREENER_TICKER_COUNT` | `300` | Scan fewer tickers while developing |

Templates: `.env.example` (local / Docker) and `.streamlit/secrets.toml.example` (Streamlit Cloud).
**Info → System Status** in the app shows which keys are set, provider health, cache ages and
recent warnings.

### Optional: limit screener scope

The weekly/monthly screener scans the top 50 S&P 500 tickers by default. To speed up development:

```bash
export SCREENER_TICKER_COUNT=10
streamlit run app.py
```

---

## Backtesting the signals

Every buy/sell label in the app can be replayed over history to see whether it actually worked.

```bash
python -m stockiq.backend.backtest --tickers 50 --years 10            # top 50 S&P names, 10 years
python -m stockiq.backend.backtest --symbols AAPL MSFT --step 20      # non-overlapping 20-day samples
python -m stockiq.backend.backtest --csv-dir ./vendor_prices          # TICKER.csv files from any vendor
```

The report (`reports/backtest/<date>/report.md` + CSVs) covers the retired buy/sell signal score
and each of its five components, RSI zones, the MA200 Bounce Radar and the Candle Screener, at
5/20/60-day horizons: hit rate, mean/median return, excess return vs SPY, worst drawdown while
holding (MAE) and a t-stat. A regression shows how much each score component really contributes.
The same results are available in the app under **Research → Signal Backtest**.

**Findings (Oct 2026, 10 years):** across 290 large S&P names and a random 999-stock sample
of the whole US market (≥ $5M/day traded at the time), the old composite buy/sell score showed
no edge — STRONG BUY never beat the market average at 5–120 days — and the MA200 Bounce Radar
underperformed. Both were removed from the app. Oversold RSI (≤ 30) was the one reading that
beat the market at 20–60 days in both samples, with deep interim drawdowns.

Entry is the next day's open (no look-ahead). Read the caveats at the top of every report —
survivorship bias, overlapping windows and zero trading costs all flatter the results.
Fundamentals-based scanners are not backtested because only a current snapshot is stored.

---

## Scheduled jobs (GitHub Actions)

| Workflow | When | What |
|----------|------|------|
| **CI** | every PR / push to main | tests on Python 3.11 + 3.12, lint, import check, Docker build + health check |
| **Refresh Screener Cache** | nightly 02:00 UTC (full on Sundays) | analyst, forward P/E, short interest, fundamentals, metadata, US universe → committed to `main` |
| **Market Snapshot** | Mon–Fri 22:30 UTC | indicators for every US stock + ETF → `market_snapshot.parquet` on the `market-data` release (not committed) |
| **Backtest** | manual (Actions → Backtest → Run workflow) | signal backtest on real data; report printed in the log and attached as an artifact |

Actions must be enabled on the repository (Actions tab) for any of these to run.

---

## Running Tests

```bash
pip install pytest pytest-cov
pytest                                    # all tests
pytest --cov=. --cov-report=term-missing  # with coverage
pytest tests/backend/models/test_indicators.py -v   # single file
```

Tests are network-free — data calls are mocked, and `tests/frontend/test_pages_smoke.py`
renders every page with sockets blocked to prove each one degrades gracefully when data
sources are down.

---

## Project Structure

```
.
├── app.py                          # Streamlit entry point — navigation wiring
├── cache/
│   ├── screener/                   # Pre-built screener JSON files (fundamentals, analyst, etc.)
│   └── scripts/                    # Offline scripts to rebuild the screener cache
├── config/
│   ├── indicators.yml              # MA periods, Fibonacci levels (shared frontend/backend)
│   └── screeners.yml               # Ticker universes, scan limits
└── src/stockiq/
    ├── backend/
    │   ├── config/                 # Backend-only config (app.yml, cache.yml, TTLs, provider order)
    │   ├── models/                 # Pure data models (indicators, signals, options, spy context)
    │   ├── backtest/               # Signal backtesting engine + CLI (python -m stockiq.backend.backtest)
    │   ├── data/
    │   │   ├── providers/          # Market-data providers (Yahoo, Alpha Vantage), failover, validation
    │   │   ├── universe.py         # Ticker universes (S&P, NASDAQ-100, all US stocks/ETFs)
    │   │   ├── spy.py              # SPY price, intraday bars, options chain, put/call ratio (Yahoo + CBOE)
    │   │   ├── market.py           # VIX/index snapshot helpers (TTL-cached)
    │   │   ├── yf_fetch.py         # yfinance OHLCV download & company search
    │   │   ├── screeners/          # Per-strategy screener modules (spx_*, nasdaq_*, etf_*)
    │   │   ├── cache/              # Pre-built screener cache loaders (metadata, fundamentals, analyst, short interest)
    │   │   ├── local_ohlc_cache.py # Local OHLC cache for gap detection
    │   │   └── local_gap_cache.py  # Local gap cache
    │   ├── services/
    │   │   ├── spy_service.py      # SPY quote (parallel Yahoo+CBOE fetch), chart, gap table, options analysis
    │   │   ├── market_service.py   # VIX, indices, put/call ratio
    │   │   ├── ai_forecast_service.py  # Multi-provider AI forecast composition
    │   │   ├── analyzer_service.py # Per-ticker technical analysis pipeline
    │   │   └── scanners/           # Scanner services (NASDAQ, SPX, ETF, pre-market)
    │   ├── llm/                    # LLM providers, forecast validation + retry, track record
    │   └── cache.py                # TTL cache (thread-safe memory / SQLite backends)
    └── frontend/
        └── views/                  # Streamlit page modules (one file per page)
            └── components/         # Reusable UI components (charts, gap table, summary card)
```

---

## Tech Stack

| Library | Purpose |
|---------|---------|
| [Streamlit](https://streamlit.io) | Web UI framework |
| [yfinance](https://github.com/ranaroussi/yfinance) | Market data (Yahoo Finance) |
| [Plotly](https://plotly.com/python/) | Interactive charts |
| [pandas](https://pandas.pydata.org) | Data manipulation |
| [NumPy](https://numpy.org) | Numerical computation |
| [Groq SDK](https://github.com/groq/groq-python) | Llama 3.3 70B AI forecast (free tier) |
| [Google GenAI SDK](https://github.com/googleapis/python-genai) | Gemini 2.5 Flash AI forecast (free tier) |
| [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) | Claude AI forecast |
| [requests](https://requests.readthedocs.io) | DeepSeek & OpenAI REST API calls |

---

## AI Provider Comparison

| Provider | Model | Free Tier | Sign Up |
|----------|-------|-----------|---------|
| **Groq** | Llama 3.3 70B | Yes | [console.groq.com/keys](https://console.groq.com/keys) |
| **Google** | Gemini 2.5 Flash | Yes | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **DeepSeek** | DeepSeek-V3 | Pay-as-you-go (very cheap) | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| **OpenAI** | GPT-4.1 Mini | Pay-as-you-go | [platform.openai.com](https://platform.openai.com/api-keys) |
| **Anthropic** | Claude Sonnet 5.5 | Pay-as-you-go | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

---

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes and add tests
4. Run `pytest` and `ruff check .`
5. Open a Pull Request

See [good first issues](https://github.com/consciousmediacm-dev/stockIQ-Analyzer/labels/good%20first%20issue) for a place to start.

---

## Roadmap

- [ ] Portfolio tracker — track a watchlist over time
- [ ] Alert system — email/webhook when a signal fires
- [ ] More tickers — extend beyond S&P 500
- [ ] MACD and Bollinger Bands indicators
- [ ] Mobile-responsive layout improvements
- [ ] Docker image for one-command deployment

---

## License

[MIT](LICENSE) © 2025 Mamun — original StockIQ project. Modifications in this fork are released under the same license.

---

## Disclaimer

This app is for **educational and informational purposes only**. Nothing on this site constitutes financial advice. Always do your own research before making investment decisions.
