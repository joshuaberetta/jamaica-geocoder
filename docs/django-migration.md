# Backend migration: Flask → Django + DRF

This document records the migration of the backend from Flask to Django + Django
REST Framework (DRF), completed as a single cutover. The full design rationale
lives in [`plans/django-migration-plan.md`](../plans/django-migration-plan.md);
this is the operational summary of what changed.

## Why

- **Real user management** — a user table with hashed passwords and the Django
  admin UI, replacing the single hardcoded `LOGIN_USERNAME`/`LOGIN_PASSWORD`.
- **Token auth on API requests** — per-user API tokens so access can be granted
  and revoked per user.
- **Rate limiting** — per-user / per-IP / per-scope throttling, configurable per
  endpoint, to protect the paid Google Places API behind the geocoding routes.

## What changed

### New structure

```
manage.py              # Django entrypoint
config/                # project: settings, urls, wsgi
apps/
  geo/                 # boundary models + read/data endpoints + spatial resolvers
  geocoding/           # /geocode, /geocode_single, /reverse_geocode
  accounts/            # token auth (/api/token, /api/me), ensure_superuser command
  core/                # /health, /api/cache/clear, SPA serving
```

`web_app.py` (Flask) was removed. `geocode.py` (Google geocoding + pandas) and
`xlsforms.py` are unchanged and imported by the new apps.

### Database access

- The boundary tables (`cod_adm`, `secondary_boundaries`) and the `mv_countries`
  materialized view are mapped as GeoDjango **`managed = False`** models — Django
  reads them but never issues DDL. They remain owned by `db/schema.sql` +
  `scripts/ingest.py`.
- `resolve_pcodes` / `resolve_secondary_boundaries` were ported from raw psycopg2
  to GeoDjango `geom__contains` queries (same `ST_Contains` against the GIST index).
- The materialized-view refresh and the GeoJSON simplification queries
  (`ST_SimplifyPreserveTopology`) stay as **raw SQL** — they don't map cleanly to
  the ORM. See `apps/geo/services.py`.
- `python manage.py migrate` creates only Django's own auth/token/admin/session
  tables.

### Authentication

| Before (Flask) | After (Django/DRF) |
|----------------|--------------------|
| `POST /login` (form, sets session cookie) | `POST /api/token` → `{token}` |
| `GET /api/auth` (session check) | `GET /api/me` (token) |
| `GET /logout` | none — client discards the token |
| `@login_required` (session) | DRF `IsAuthenticated` (token) on batch geocode |
| — | `IsAdminUser` on `POST /api/cache/clear` |

Send the token as `Authorization: Token <token>`. All endpoints are rate-limited;
the geocoding routes use a tighter `geocode` scope and batch upload a `batch` scope.

### Caching

The per-process in-memory dicts were replaced by Django's cache framework
(`LocMemCache` by default). **Set `REDIS_URL` when running more than one gunicorn
worker** so cache-clear-on-ingest reaches every worker; otherwise keep
`--workers 1`.

### Frontend

- New `frontend/src/api/auth.ts`: token storage in `localStorage` + `login()`.
- API client injects the `Authorization: Token` header.
- `AuthContext` validates a stored token via `GET /api/me`; logout clears it.
- `LoginPage` posts to `/api/token`; the sign-out button clears the token
  client-side (no `/logout` request).

### Ops

- **Procfile / entrypoint / systemd:** run `gunicorn config.wsgi:application`.
  The entrypoint now also runs `migrate`, `ensure_superuser`, and `collectstatic`.
- **Superuser bootstrap:** `manage.py ensure_superuser` creates/updates an admin
  from `DJANGO_SUPERUSER_USERNAME`/`DJANGO_SUPERUSER_PASSWORD` and prints its API
  token. Replaces `LOGIN_USERNAME`/`LOGIN_PASSWORD`.
- **Ingest cache-clear** authenticates with `APP_API_TOKEN` (falls back to
  `APP_LOGIN_*` → `/api/token`).
- **Vite dev proxy** targets Django on `:8000`.
- `runtime.txt` aligned to `python-3.11.9` to match the Dockerfile base image.

### API docs

drf-spectacular serves interactive docs at `/api/docs/` (Swagger) and
`/api/redoc/`; raw schema at `/api/schema/`.

## Behaviour parity

Response shapes, status codes, validation, and ETag/304 behaviour are unchanged.
This is pinned by the DRF `APIClient` contract suite in `tests_django/`
(45 tests). The geocode-core unit tests (`tests/test_geocode*.py`,
`tests/test_bulk_geocode.py`) are retained unchanged.

One quirk was carried over deliberately and is pinned by a test: `GET /geocode`
and `POST /reverse_geocode` parse coordinates as `latitude or lat`, so a `0.0`
value (equator / prime meridian) is treated as missing and rejected with `400`.

## New dependencies

`django`, `djangorestframework`, `django-cors-headers`, `drf-spectacular`,
`whitenoise`, plus `pytest-django` / `pytest-cov` for tests. Flask, flask-cors,
and flask-compress were removed.
