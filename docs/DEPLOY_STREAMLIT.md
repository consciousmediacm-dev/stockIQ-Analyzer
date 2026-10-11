# Deploying to Streamlit Community Cloud

Free hosting with a URL like `https://<name>.streamlit.app`. Takes about 10 minutes.

## What the repo already provides

| File | Purpose |
|---|---|
| `app.py` | Entry point (adds `src/` to the import path itself) |
| `requirements.txt` | Exact package versions CI tests against, which Cloud installs |
| `.streamlit/config.toml` | Theme; visitors see only the error type, not tracebacks |
| `.streamlit/secrets.toml.example` | The secret names to paste into Cloud |

Market data needs no server work. GitHub Actions builds the full-market snapshot nightly and publishes it as a Release asset. The app downloads that file on first use.

## Steps

1. **Sign in.** Go to [share.streamlit.io](https://share.streamlit.io) and sign in with the GitHub account that owns this repo. Authorize Streamlit when asked.
2. **Create the app.** Click **Create app**, then deploy from GitHub, and fill in:
   - Repository: `consciousmediacm-dev/stockIQ-Analyzer`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: pick a subdomain, e.g. `stockiq-yourcompany`
3. **Open Advanced settings.**
   - **Python version:** `3.12`. CI tests 3.11 and 3.12. Don't pick 3.13.
   - **Secrets:** paste the keys you have, in TOML format:
     ```toml
     ANTHROPIC_API_KEY     = "sk-ant-..."
     ALPHA_VANTAGE_API_KEY = "..."
     ```
     Leave out any provider you don't use. Every string secret is exported to the environment at startup, so the names match `.env.example`.
4. **Deploy.** The first build installs packages and takes a few minutes.
5. **Choose who can view.** Open the app's **Settings → Sharing**. While you're the only tester, restrict viewing to specific email addresses. Switch to public when you launch.

## What to expect

- **Updates:** a push to `main` updates the running app. The nightly data commits do this too, which is harmless.
- **Sleep:** an app with no visitors for a while goes to sleep. The next visitor clicks **Wake up** and waits about 30 seconds.
- **No persistent disk:** caches and the AI forecast track record (`forecasts.jsonl`) reset when the app restarts. The market snapshot is downloaded again automatically.
- **Memory is limited.** If the app is killed for memory, use **Manage app → Reboot**, and check the logs in the same panel.

## AI cost

- **Your key:** the SPY forecast is cached for one hour per provider. That limits your Anthropic key to about 24 forecast calls a day, plus at most one corrective retry each, however many people visit.
- **Visitors' keys:** a visitor who enters a personal key uses their own quota. Their key is never stored.
- **Hard cap:** set a monthly spend limit in the [Anthropic Console](https://console.anthropic.com/settings/limits) anyway.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "The app is temporarily unavailable" | **Manage app → logs**. Usually a missing package or a bad secret format. |
| Market Screener says the snapshot isn't built | Run **Actions → Market Snapshot → Run workflow**, or wait for the nightly run. |
| AI forecast says no key | Add `ANTHROPIC_API_KEY` under **Settings → Secrets**, then reboot. |
| Build fails on a package | Make sure Python is 3.12 (**Settings → General**). |
