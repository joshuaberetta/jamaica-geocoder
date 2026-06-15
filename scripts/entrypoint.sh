#!/bin/sh
set -e

# ---------------------------------------------------------------------------
# Web service entrypoint.
#
# The heavy one-time work (download + global boundary ingest) lives in the
# PRE_DEPLOY job (scripts/ingest_job.sh), which runs to completion before this
# service starts. This entrypoint only performs cheap, fast startup steps and
# then binds gunicorn, so the readiness probe passes promptly.
# ---------------------------------------------------------------------------

# Ensure the boundary schema exists. The pre-deploy job already does this, but
# it is cheap and idempotent (CREATE ... IF NOT EXISTS), so we keep it as a
# safety net in case the web service is ever started without the job (e.g.
# local docker run against a managed DB).
echo "==> Ensuring boundary schema (db/schema.sql)..."
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

echo "==> Ensuring materialized view is populated..."
python - <<'PYEOF'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as conn:
    count = conn.execute(text("SELECT COUNT(*) FROM mv_countries")).scalar()
    if count == 0:
        print("mv_countries is empty — refreshing...")
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries"))
        print("mv_countries refreshed.")
    else:
        print(f"mv_countries OK ({count} countries).")
PYEOF

echo "==> Pre-generating XLSForms..."
python scripts/generate_xlsforms.py || echo "WARNING: XLSForm pre-generation failed; forms will be built on demand."

echo "==> Applying Django migrations (auth + token tables)..."
# The managed=False boundary tables/view are owned by db/schema.sql + ingest.py;
# these migrations only create Django's own auth/token/admin/session tables.
python manage.py migrate --noinput

echo "==> Bootstrapping admin user from env (if DJANGO_SUPERUSER_PASSWORD set)..."
python manage.py ensure_superuser || echo "WARNING: superuser bootstrap skipped/failed."

echo "==> Collecting static assets..."
python manage.py collectstatic --noinput || echo "WARNING: collectstatic failed."

echo "==> Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --timeout 300 --workers 1 config.wsgi:application
