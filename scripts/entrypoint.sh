#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Startup entrypoint: run ingest if the database is empty, then start the app
# ---------------------------------------------------------------------------

DATA_FILE="/data/global_admin_boundaries_matched_latest.gdb.zip"

echo "==> Checking database state..."
ROW_COUNT=$(python - <<'EOF'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL")
if not url:
    print("0")
    sys.exit(0)
try:
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM cod_adm"))
        print(result.scalar())
except Exception as e:
    print(f"DB check failed: {e}", file=sys.stderr)
    print("0")
EOF
)

echo "==> Rows in cod_adm: ${ROW_COUNT}"

if [ "${ROW_COUNT}" = "0" ]; then
    if [ -f "${DATA_FILE}" ]; then
        echo "==> Running ingest from ${DATA_FILE}..."
        python scripts/ingest.py --file "${DATA_FILE}"
    else
        echo "==> No local data file found. Downloading from HDX (this may take a while)..."
        python scripts/ingest.py
    fi
    echo "==> Ingest complete."
else
    echo "==> Database already populated, skipping ingest."
fi

echo "==> Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --timeout 300 --workers 1 web_app:app
