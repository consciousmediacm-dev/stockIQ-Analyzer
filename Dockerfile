# StockIQ — production image
#   docker build -t stockiq .
#   docker run -p 8501:8501 --env-file .env -v stockiq-data:/data stockiq
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STOCKIQ_DATA_DIR=/data \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Dependencies first (cached layer), pinned to the versions CI tests against.
# The package itself isn't installed — PYTHONPATH points at src/ (app.py does the same).
COPY pyproject.toml constraints.txt ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -c constraints.txt -r /tmp/requirements.txt

ENV PYTHONPATH=/app/src
COPY . .

RUN useradd --create-home --uid 10001 stockiq \
    && mkdir -p /data && chown -R stockiq:stockiq /data /app
USER stockiq

VOLUME ["/data"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
