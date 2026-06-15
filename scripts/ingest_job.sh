#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Pre-deploy ingest job.
#
# Runs to completion BEFORE the web service starts (DO App Platform
# kind: PRE_DEPLOY). It has no HTTP health check, so the long one-time
# download + global ingest can take as long as it needs without tripping the
# web service's readiness probe.
#
# It is idempotent and resumable: once the global ingest completes it records a
# marker (ingest_meta.global_complete) and subsequent deploys check-and-skip in
# seconds; a run interrupted mid-ingest resumes from the last committed country
# rather than restarting. The web entrypoint no longer ingests;
# it only applies cheap, fast startup steps and then binds gunicorn.
# ---------------------------------------------------------------------------

DATA_FILE="/data/global_admin_boundaries_matched_latest.gdb.zip"

# Fast skip: if a previous run recorded a completed global ingest, exit
# immediately — no schema work, no 940MB download. The completion marker is
# written by ingest.py only after every layer finishes (set_ingest_complete),
# which is the only reliable "done" signal. (The old gate counted "admin levels
# 0-3 present", but this dataset has levels 1-4 and no level 0, so it could
# never reach 4 and every deploy re-ingested from scratch.)
echo "==> [ingest-job] Checking for completed-ingest marker..."
COMPLETE=$(python - <<'EOF'
import os, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL")
if not url:
    print("no"); sys.exit(0)
try:
    engine = create_engine(url)
    with engine.connect() as conn:
        v = conn.execute(text(
            "SELECT value FROM ingest_meta WHERE key = 'global_complete'"
        )).scalar()
        print("yes" if v else "no")
except Exception:
    # ingest_meta doesn't exist yet → not complete.
    print("no")
EOF
)

if [ "${COMPLETE}" = "yes" ]; then
    echo "==> [ingest-job] Global ingest already complete, skipping."
    exit 0
fi

# Ensure the boundary schema exists. On managed Postgres (e.g. DigitalOcean)
# there is no /docker-entrypoint-initdb.d hook, so db/schema.sql is never
# applied automatically the way it is under docker-compose. The schema is
# fully idempotent (CREATE ... IF NOT EXISTS), so running it here is safe and
# creates cod_adm/mv_countries/secondary_boundaries when absent.
echo "==> [ingest-job] Ensuring boundary schema (db/schema.sql)..."
python - <<'PYEOF'
import os, sys
from pathlib import Path
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("ERROR: DATABASE_URL not set; cannot apply schema.")

sql = Path("db/schema.sql").read_text()
engine = create_engine(url)
with engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    # Execute the schema as a single script; statements are idempotent.
    conn.exec_driver_sql(sql)
print("Boundary schema ensured.")
PYEOF

if [ ! -f "${DATA_FILE}" ]; then
    echo "==> [ingest-job] No local data file found. Downloading from HDX to /data (this may take a while)..."
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

echo "==> [ingest-job] Running ingest from ${DATA_FILE}..."
python scripts/ingest.py --file "${DATA_FILE}"
echo "==> [ingest-job] Ingest complete."

echo "==> [ingest-job] Refreshing materialized view..."
python - <<'PYEOF'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as conn:
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries"))
print("mv_countries refreshed.")
PYEOF

echo "==> [ingest-job] Done."
