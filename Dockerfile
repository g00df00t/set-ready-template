FROM python:3.11-slim

WORKDIR /app

# WeasyPrint renders the call-sheet PDF and needs pango/harfbuzz at runtime.
# fonts-liberation gives fontconfig a metric-compatible stand-in for the Arial
# the sheet asks for — without it the PDF falls back to whatever it can find and
# the spacing drifts from the on-screen sheet. fonts-dejavu-core is the
# fallback for symbols Liberation doesn't have: without it the talent hold
# sheet's ✓ marks printed blank (found on staging, 2026-10-02).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz-subset0 \
      fonts-liberation \
      fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
