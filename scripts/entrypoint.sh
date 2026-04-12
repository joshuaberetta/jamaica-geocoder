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
        # Require admin levels 0, 1, 2, and 3 to all be present.
        # If any are missing the ingest was incomplete and must be re-run.
        result = conn.execute(text(
            "SELECT COUNT(*) FROM cod_adm WHERE adm_level IN (0,1,2,3) "
            "AND adm_level IN (SELECT DISTINCT adm_level FROM cod_adm)"
        ))
        level_count = conn.execute(text(
            "SELECT COUNT(DISTINCT adm_level) FROM cod_adm WHERE adm_level IN (0,1,2,3)"
        )).scalar()
        print(level_count)
except Exception as e:
    print(f"DB check failed: {e}", file=sys.stderr)
    print("0")
EOF
)

echo "==> Distinct admin levels (0-3) in cod_adm: ${ROW_COUNT}"

if [ "${ROW_COUNT}" != "4" ]; then
    if [ ! -f "${DATA_FILE}" ]; then
        echo "==> No local data file found. Downloading from HDX to /data (this may take a while)..."
        python - <<'PYEOF'
import sys
from pathlib import Path

DEST = Path("/data/global_admin_boundaries_matched_latest.gdb.zip")
DEST.parent.mkdir(parents=True, exist_ok=True)

try:
    from hdx.api.configuration import Configuration
    from hdx.data.dataset import Dataset
except ImportError:
    sys.exit("ERROR: hdx-python-api is not installed.")

Configuration.create(hdx_site="prod", user_agent="humanitarian-geocoder", hdx_read_only=True)
print("Searching HDX for 'global-admin-boundaries'...")
datasets = Dataset.search_in_hdx("global-admin-boundaries")
resources = Dataset.get_all_resources(datasets)

url = next((r["url"] for r in resources if r["name"] == DEST.name), None)
if not url:
    sys.exit(f"ERROR: Could not find {DEST.name} on HDX.")

import requests
print(f"Downloading {DEST.name} (~940 MB)...")
with requests.get(url, stream=True, timeout=600) as r:
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    with open(DEST, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"  {downloaded / total * 100:.1f}% ({downloaded // 1_000_000} MB)", end="\r", flush=True)
print(f"\nDownload complete: {DEST}")
PYEOF
    fi
    echo "==> Running ingest from ${DATA_FILE}..."
    python scripts/ingest.py --file "${DATA_FILE}"
    echo "==> Ingest complete."
else
    echo "==> All admin levels 0-3 present, skipping ingest."
fi

echo "==> Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --timeout 300 --workers 1 web_app:app
