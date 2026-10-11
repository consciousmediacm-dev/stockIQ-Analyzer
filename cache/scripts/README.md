# Screener Cache Build Scripts

These scripts pre-build slow-changing data into `cache/screener/*.json` so the
app never needs to call the Yahoo Finance `.info` API at runtime. The nightly
GitHub Action (`.github/workflows/refresh_cache.yml`) runs them automatically;
you can also run them by hand.

Every script writes through `_common.write_cache()`, which **refuses to overwrite**
a file when fewer than 90% of tickers came back or the file would shrink by more
than 10% (a rate-limited run can't wipe good data), writes atomically, and records
`generated_at` / count / coverage in `cache/screener/manifest.json` — shown on the
app's **System Status** page.

## Prerequisites

- `pip install -e .` from the project root
- Run from the project root: `python3 cache/scripts/<script>.py`

---

## Scripts

### `build_metadata_cache.py`
Company name + sector for every ticker in the S&P universe (300).

**When to run:** Once, then again only if the S&P 500 constituent list changes
(roughly quarterly).

```bash
python3 cache/scripts/build_metadata_cache.py
```

---

### `build_fundamentals_cache.py`
Uploads ROE, profit margins, revenue growth, debt/equity, and earnings growth
for all 300 tickers in the S&P universe. Used by the Munger Strategy Scanner.

**When to run:** Once per quarter, after earnings season.

```bash
python3 cache/scripts/build_fundamentals_cache.py
```

---

### `build_short_interest_cache.py`
Uploads short % of float, days-to-cover, shares short, and prior-month shares
short for all 300 tickers in the S&P universe. Used by the Squeeze Scanner.

**When to run:** Once per month — FINRA publishes short interest data bi-monthly,
so monthly refreshes are sufficient.

```bash
python3 cache/scripts/build_short_interest_cache.py
```

---

### `build_analyst_consensus_cache.py`
Uploads analyst recommendation mean, number of analysts, and price targets
(mean/high/low) for all 300 tickers in the S&P universe. Used by the Strong Buy/Sell scanners.

**When to run:** Once per week — analyst ratings change infrequently.

```bash
python3 cache/scripts/build_analyst_consensus_cache.py
```

---

### `build_universe_cache.py`
Builds the list of every active US-listed stock and ETF (~10k symbols) from the
free nasdaqtrader.com symbol directory, falling back to Alpha Vantage
`LISTING_STATUS`. Warrants, units, rights, preferreds and test issues are excluded.
Refuses to write if fewer than 3,000 symbols come back.

**When to run:** Weekly (new listings / delistings).

```bash
python3 cache/scripts/build_universe_cache.py
```

Use it in code with `stockiq.backend.data.universe.get_universe("us_equities")`
(also `us_etfs`, `us_all`, `sp500`, `nasdaq100`).

---

## Refresh Schedule Summary

| Script                          | Output file                       | Refresh cadence |
|---------------------------------|-----------------------------------|-----------------|
| `build_metadata_cache.py`       | `screener/ticker_metadata.json`   | Quarterly       |
| `build_fundamentals_cache.py`   | `screener/fundamentals.json`      | Quarterly       |
| `build_short_interest_cache.py` | `screener/short_interest.json`    | Monthly         |
| `build_analyst_consensus_cache.py` | `screener/analyst_consensus.json` | Weekly       |
| `build_universe_cache.py`       | `screener/universe.json`          | Weekly          |
