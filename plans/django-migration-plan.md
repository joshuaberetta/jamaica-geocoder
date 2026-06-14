# Plan: Migrate backend to Django + DRF (user management, token auth, rate limiting)

## Goal

Replace the Flask backend ([web_app.py](../web_app.py)) with a Django + Django REST
Framework (DRF) application that provides:

- **Real user management** — a user table, password hashing, admin UI — instead of the
  single hardcoded `LOGIN_USERNAME`/`LOGIN_PASSWORD` env pair.
- **Token auth on API requests** — per-user API tokens so access to the geocoding
  endpoints can be granted, revoked, and attributed per user.
- **Rate limiting** — per-user / per-IP request throttling, configurable per endpoint.

The React SPA ([frontend/](../frontend)) and its production build flow are kept. Only the
auth flow in the frontend changes (token instead of session cookie). The geospatial
query logic moves to **GeoDjango ORM** models.

### Decisions (locked in)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DB access layer | **GeoDjango ORM** | Model `cod_adm` / `secondary_boundaries` as `MultiPolygonField` models; rewrite the `ST_Contains` lookups as `.filter(geom__contains=point)`. Migrations + admin come for free. |
| Token mechanism | **DRF `TokenAuthentication` + throttling** | Per-user static tokens, plus DRF's built-in `UserRateThrottle` / `AnonRateThrottle` / `ScopedRateThrottle`. Simplest path that satisfies "limit access + rate limit". |
| Scope | **Backend swap, keep SPA** | Django/DRF serves the same routes; frontend keeps its API client with minimal auth changes. |

---

## Current state (what we're replacing)

- **Backend:** Flask app in [web_app.py](../web_app.py), 17 routes, raw `psycopg2` queries
  in [geocode.py](../geocode.py). Auth = `session["logged_in"]` cookie set by a hardcoded
  credential compare ([web_app.py:99-106](../web_app.py)); `login_required` decorator
  ([web_app.py:69-76](../web_app.py)) gates only `POST /geocode` and `POST /api/cache/clear`.
- **DB:** PostgreSQL + PostGIS (`postgis/postgis:16-3.4`). Two tables (`cod_adm`,
  `secondary_boundaries`) + one materialized view (`mv_countries`), all defined in
  [db/schema.sql](../db/schema.sql). No ORM, no migrations today.
- **Frontend:** React 19 + Vite, built into [static/](../static), served by Flask's
  catch-all. API client in [frontend/src/api/client.ts](../frontend/src/api/client.ts)
  uses relative same-origin URLs. Auth state via `GET /api/auth` poll in
  [frontend/src/context/AuthContext.tsx](../frontend/src/context/AuthContext.tsx).
- **In-memory caches:** `_countries_cache` / `_boundaries_cache` / `_secondary_cache`
  dicts ([web_app.py:50-53](../web_app.py)) — per-process, invalidated on ingest.
- **Ingest:** `scripts/ingest.py` (GeoPandas/GDAL) loads boundaries; calls the protected
  cache-clear endpoint when done. Independent of the web framework.

### Route inventory to port (paths must be preserved — the built SPA calls them)

| Method | Path | Auth | DRF home |
|--------|------|------|----------|
| GET | `/countries` | public | `geo` viewset/view |
| GET | `/api/available_levels` | public | `geo` |
| GET | `/api/admin_levels` | public | `geo` |
| GET | `/boundaries.geojson` | public | `geo` |
| GET | `/api/secondary_types` | public | `geo` |
| GET | `/secondary_boundaries.geojson` | public | `geo` |
| GET | `/xlsform` | public | `geo` |
| GET | `/geocode` | public | `geocoding` |
| POST | `/geocode` | **auth** | `geocoding` (batch) |
| POST | `/geocode_single` | public | `geocoding` |
| POST | `/reverse_geocode` | public | `geocoding` |
| GET | `/health` | public | `core` |
| POST | `/login` | — | replaced by token-obtain endpoint |
| GET | `/logout` | — | replaced (client drops token) |
| GET | `/api/auth` | public | replaced by `/api/me` |
| POST | `/api/cache/clear` | **auth** | `core` (admin-only) |
| GET `/` + `/<path>` | SPA catch-all | public | Django static serve |

> **Throttling note:** today only batch geocode is gated. With the new system, *all*
> geocoding endpoints (`/geocode*`, `/reverse_geocode`) should be rate-limited even when
> public, since they hit the paid Google Places API. See Phase 5.

---

## Target architecture

```
manage.py
config/                      # Django project (was implicit Flask app)
  settings.py                # GeoDjango, DRF, token auth, throttling, CORS, static
  urls.py                    # route table -> preserves existing paths
  wsgi.py                    # gunicorn config.wsgi:application
apps/
  geo/                       # boundary data + read endpoints
    models.py                # CodAdm, SecondaryBoundary, MvCountries (managed=False where apt)
    views.py                 # countries, levels, boundaries.geojson, secondary, xlsform
    services.py              # resolve_pcodes / resolve_secondary (ported from geocode.py)
    cache.py                 # Django cache wrappers (replaces in-memory dicts)
  geocoding/                 # Google geocode + batch
    views.py                 # /geocode (GET+POST), /geocode_single, /reverse_geocode
    services.py              # geocode_address, geocode_dataframe (ported)
  accounts/                  # users + tokens
    models.py                # use Django auth User (+ optional profile)
    views.py                 # token obtain, /api/me
  core/                      # health, cache clear, SPA serving
    views.py
```

Keep [xlsforms.py](../xlsforms.py) and `scripts/ingest.py` as-is initially — import them
from the new app code. They're framework-agnostic. (A later cleanup can turn ingest into
a management command.)

---

## Phase 0 — Scaffolding & dependencies

1. Add to [requirements.txt](../requirements.txt):
   `django`, `djangorestframework`, `django-cors-headers`, `psycopg2-binary` (already
   present), `gunicorn` (already present). GeoDjango ships with Django (`django.contrib.gis`),
   relies on the GDAL/GEOS/PROJ libs already in the Docker image.
2. `django-admin startproject config .` then create the apps under `apps/`.
3. `config/settings.py` essentials:
   - `INSTALLED_APPS`: `django.contrib.gis`, `rest_framework`, `rest_framework.authtoken`,
     `corsheaders`, the local apps, and `django.contrib.admin/auth/contenttypes/sessions`
     (admin needs sessions — that's fine; the *API* uses tokens, not sessions).
   - `DATABASES['default']['ENGINE'] = 'django.contrib.gis.db.backends.postgis'`, parsed
     from the existing `DATABASE_URL` env (keep the same var).
   - `SECRET_KEY` from env (reuse existing `SECRET_KEY`).
   - `ALLOWED_HOSTS`, `DEBUG` from env.
   - Static: `STATIC_ROOT`/serving so the built SPA in [static/](../static) is served
     (see Phase 6).

> **Decision needed at build time:** run Django and Flask side-by-side during migration,
> or cut over in one PR? Recommended: build Django in a branch, port + test all routes,
> then cut over in a single PR so paths never collide.

---

## Phase 1 — GeoDjango models

Map the existing schema to models. Since the tables already exist and are populated by
`scripts/ingest.py`, start with `managed = False` + `db_table` so Django reads the
current tables without trying to recreate them; switch ingest to the ORM later if desired.

```python
# apps/geo/models.py
from django.contrib.gis.db import models

class CodAdm(models.Model):
    iso2 = models.CharField(max_length=2)
    iso3 = models.CharField(max_length=3, null=True)
    country_name = models.TextField(null=True)
    adm_level = models.SmallIntegerField()
    adm0_pcode = models.TextField(null=True); adm0_name = models.TextField(null=True)
    # ... adm1..adm4 pcode/name ...
    geom = models.MultiPolygonField(srid=4326)
    class Meta:
        managed = False
        db_table = 'cod_adm'

class SecondaryBoundary(models.Model):
    iso2 = models.CharField(max_length=2)
    boundary_type = models.TextField()
    name = models.TextField(null=True)
    ref_dhis2 = models.TextField(null=True)
    source_id = models.TextField(null=True)
    # ... alt_name, level, attribution, iso3 ...
    geom = models.MultiPolygonField(srid=4326)
    class Meta:
        managed = False
        db_table = 'secondary_boundaries'

class MvCountries(models.Model):     # materialized view
    iso2 = models.CharField(max_length=2, primary_key=True)
    iso3 = models.CharField(max_length=3, null=True)
    country_name = models.TextField(null=True)
    max_adm_level = models.SmallIntegerField()
    center_lon = models.FloatField(null=True)
    center_lat = models.FloatField(null=True)
    class Meta:
        managed = False
        db_table = 'mv_countries'
```

- The materialized view `mv_countries` and its refresh stay as raw SQL (the ORM doesn't
  model `REFRESH MATERIALIZED VIEW`). Keep [db/schema.sql](../db/schema.sql) as the source
  of truth for the view + indexes; Django migrations only own the *auth/token* tables.
- Verify GIST index on `geom` is honored by `geom__contains` queries (it is — GeoDjango
  emits `ST_Contains`).

---

## Phase 2 — Port geocoding services to the ORM

Rewrite the two PostGIS resolvers from [geocode.py](../geocode.py) using GeoDjango:

```python
# apps/geo/services.py
from django.contrib.gis.geos import Point

def resolve_pcodes(lat, lon, iso2=None):
    pt = Point(lon, lat, srid=4326)
    qs = CodAdm.objects.filter(geom__contains=pt)
    if iso2:
        qs = qs.filter(iso2=iso2.upper())
    row = qs.order_by('-adm_level').first()   # deepest admin level
    if not row:
        return None
    # build the same {country, country_code, adm{n}_pcode/name} dict as today
```

- `resolve_pcodes` ([geocode.py:73-127](../geocode.py)) → `geom__contains` + `order_by('-adm_level').first()`.
- `resolve_secondary_boundaries` ([geocode.py:141-187](../geocode.py)) → `geom__contains`
  filter, keep the `SECONDARY_KEY_PREFIX` mapping and graceful-empty behavior.
- **Keep `geocode_address` and `geocode_dataframe` ([geocode.py:195-421](../geocode.py))
  unchanged** — they call Google's HTTP API and pandas; no ORM involved. Import them as-is.
- The output dict shapes must stay **byte-identical** to today so the SPA and the existing
  `tests/` continue to pass. The tests in [tests/](../tests) are the behavior spec — run
  them against the new endpoints (adapt the client fixture from Flask test client → DRF
  `APIClient`).

---

## Phase 3 — Port the read/data endpoints (`geo` app)

DRF `APIView`s (or function views with `@api_view`) for each, preserving exact paths and
response JSON:

- `GET /countries` — `MvCountries.objects.all().order_by('country_name')`, same dict shape
  ([web_app.py:120-179](../web_app.py)). Replace the in-memory ETag cache with Django's
  cache framework + `Last-Modified`/`ETag` (Phase 4).
- `GET /api/available_levels`, `GET /api/admin_levels`, `GET /api/secondary_types` —
  `.values_list(...).distinct()` queries.
- `GET /boundaries.geojson` & `GET /secondary_boundaries.geojson` — these use
  `ST_SimplifyPreserveTopology` + `ST_AsGeoJSON`. GeoDjango: annotate with
  `Simplify('geom', tolerance)` and serialize via `django.contrib.gis.serializers.geojson`
  **or** keep a small raw SQL query for these two if the simplification tuning matters
  (acceptable exception — they're read-only and performance-sensitive).
- `GET /xlsform` — calls `xlsforms.build_xlsform(iso2)` / streams the file. Import
  [xlsforms.py](../xlsforms.py) unchanged; use Django `FileResponse`.

---

## Phase 4 — Caching across workers

The Flask in-memory dicts ([web_app.py:50-53](../web_app.py)) don't survive multiple
gunicorn workers. Move to Django's cache framework:

- Configure `CACHES` — start with `LocMemCache` (per-process, matches today's behavior),
  but document that **Redis is the right backend** once running >1 worker, because
  cache-clear-on-ingest must reach all workers.
- The `POST /api/cache/clear` endpoint becomes `cache.clear()` (or targeted key deletion)
  + the raw-SQL `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries` + XLSForm regen.
- `scripts/ingest.py`'s `_notify_app` must now authenticate with a **token** for an admin
  user instead of session login (Phase 5).

> If a Redis dependency is unwanted now, an acceptable interim is keeping gunicorn at
> `--workers 1` (as today, [Procfile](../Procfile)) and `LocMemCache`. Flag this explicitly.

---

## Phase 5 — Auth, tokens & throttling (`accounts` app)

### Users
- Use Django's built-in `auth.User` + admin UI (`/admin/`) for user management — create,
  disable, set passwords (hashed). This replaces `LOGIN_USERNAME`/`LOGIN_PASSWORD`.
- Optional: seed an initial superuser from env on startup (entrypoint), to preserve a
  bootstrap admin without committing credentials.

### Tokens
- Enable `rest_framework.authtoken`; run its migration to create the token table.
- Expose `POST /api/token` (DRF's `obtain_auth_token`) → returns `{ "token": "..." }` for
  valid username/password. This replaces `POST /login`.
- `GET /api/me` (authenticated) returns the current user → replaces `GET /api/auth`.
- "Logout" = client discards the token (no server route needed); optionally add a
  token-revoke endpoint.

### DRF defaults (`settings.py`)
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',   # most routes are public
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',           # tune
        'user': '600/min',          # tune
        'geocode': '30/min',        # ScopedRateThrottle on Google-API endpoints
        'batch': '5/min',
    },
}
```

### Per-endpoint policy
- Public read endpoints (`/countries`, `*.geojson`, levels, `/xlsform`): `AllowAny`,
  `AnonRateThrottle`.
- Google-API endpoints (`/geocode`, `/geocode_single`, `/reverse_geocode`):
  `ScopedRateThrottle` with scope `geocode` — these cost money per call, so throttle even
  anonymous use. (Optionally require auth here later if you want to *limit access*, not
  just rate — easy switch to `IsAuthenticated`.)
- `POST /geocode` (batch) and `POST /api/cache/clear`: `IsAuthenticated`
  (+ `IsAdminUser` for cache clear). Scope `batch`.

---

## Phase 6 — API reference & documentation

Document every endpoint so consumers (and the SPA) have a single source of truth.
**Minimise new dependencies** — two options, recommendation first:

### Recommended: `drf-spectacular` (one dependency, auto-generated OpenAPI 3)
This is the current de-facto standard for DRF and the lowest-effort path to *accurate,
always-in-sync* docs. It's a single pure-Python dependency (no native libs), so it fits
the "minimal overhead" bar.

- Add `drf-spectacular` to [requirements.txt](../requirements.txt).
- `INSTALLED_APPS += ['drf_spectacular']`; set
  `REST_FRAMEWORK['DEFAULT_SCHEMA_CLASS'] = 'drf_spectacular.openapi.AutoSchema'`.
- URLs:
  - `GET /api/schema/` → `SpectacularAPIView` (the raw OpenAPI 3 YAML/JSON).
  - `GET /api/docs/` → `SpectacularSwaggerView` (interactive Swagger UI).
  - `GET /api/redoc/` (optional) → `SpectacularRedocView` (clean reference layout).
- The Swagger/ReDoc JS is served from a CDN by default → **no JS bundle added**. If you
  want zero external requests, `drf-spectacular-sidecar` vendors the assets (optional).
- Annotate non-obvious views with `@extend_schema(...)` for request/response examples
  (especially the file-upload `POST /geocode` and the GeoJSON responses, which the schema
  generator can't fully infer).

### Fallback: DRF's built-in OpenAPI generator (no third-party Django app)
DRF ships an OpenAPI schema generator. Deps are tiny and widely pre-installed:
`uritemplate` + `pyyaml`. Expose it via `rest_framework.schemas.get_schema_view(...)`.
Trade-off: the built-in generator produces a thinner schema (less control over
examples/auth docs) and has no bundled UI — you'd serve Swagger UI from a CDN `<script>`
in a one-off template. Choose this only if adding even one Django app is unwanted.

> Either way the endpoint paths and the `Authorization: Token <token>` scheme should be
> declared in the schema so API consumers can authenticate from the docs page.

### Static reference table (commit alongside the schema)

Regardless of the tool, keep a human-readable summary in the repo (e.g. `docs/api.md`),
since the OpenAPI schema is only live when the server runs. The table below is the
authoritative endpoint contract — derived from the current behaviour now pinned by
[tests/test_web_app_routes.py](../tests/test_web_app_routes.py) — and must hold after the port:

| Method & path | Auth | Query / body | Success | Error cases |
|---------------|------|--------------|---------|-------------|
| `GET /countries` | none | — | `200` array of `{code, iso3, name, key, max_adm_level, map_center}`; `ETag`, `304` on match | — |
| `GET /api/available_levels` | none | `country` (ISO2, req) | `200 {iso2, levels:[int]}` | `400` no country; `500` DB |
| `GET /api/admin_levels` | none | `country` (req), `level` (0–4, default 1) | `200 {iso2, level, label, values:[str]}` | `400` no country / non-int / out-of-range |
| `GET /boundaries.geojson` | none | `country` (req), `level` (0–4, default 1) | `200` GeoJSON `FeatureCollection`; `ETag`, `304` | `400` no country / bad level; `500` DB |
| `GET /api/secondary_types` | none | `country` (req) | `200 {iso2, types:[str]}` (empty if no table) | `400` no country |
| `GET /secondary_boundaries.geojson` | none | `country` (req), `type` (default `health`) | `200` GeoJSON FC; `ETag`, `304` | `400` no country; `500` DB |
| `GET /xlsform` | none | `country` (ISO2, req) | `200` XLSX attachment `"{ISO2} ({name}).xlsx"`; `ETag`, `304` | `400` no country; `404` unknown country; `500` |
| `GET /geocode` | none | `lat`+`lon` **or** `address`; `country` opt | `200 {success, latitude, longitude, [confidence], ...pcodes, ...secondary}` | `400` no params / bad coords; `404` unresolvable / outside |
| `POST /geocode` | **token** | multipart: `file` (CSV/XLSX, `address` col req), `country`, `limit`, `format`, `output_filename` | `200 {success, stats, file_data(base64), filename, mimetype}` | `401` no auth; `400` no file / no `address` col / read error |
| `POST /geocode_single` | none | JSON/form: `address` (req), `country` opt | `200 {success, address, latitude, longitude, confidence, ...pcodes}` (`success:false` if ungeocodable) | `400` no address |
| `POST /reverse_geocode` | none | JSON/form: `latitude`+`longitude` (req), `country` opt | `200 {success, latitude, longitude, ...pcodes, ...secondary}` (`success:false` if outside) | `400` missing / bad coords |
| `GET /health` | none | — | `200 {status:"ok", countries_in_db:int}` | `500 {status:"degraded", error}` |
| `POST /api/token` *(new)* | none | JSON: `username`, `password` | `200 {token}` | `400` bad creds |
| `GET /api/me` *(new, replaces `/api/auth`)* | token | — | `200 {username, ...}` | `401` |
| `POST /api/cache/clear` | **token (admin)** | JSON: `country` opt | `200 {status:"ok", message}` | `401`; `500` view-refresh fail |
| `GET /` + `/<path>` | none | — | `200` SPA `index.html` / static asset | — |

> **Behaviour note to carry over (or fix deliberately):** `GET /geocode` and
> `POST /reverse_geocode` parse coords as `latitude or lat`, so a `0.0` value (equator /
> prime meridian) is treated as *missing* and rejected `400`. This is pinned by
> `test_reverse_geocode_zero_coordinate_is_rejected`. Decide during the port whether to
> reproduce or fix it — don't change it by accident.

---

## Phase 7 — Serving the SPA + static

- `vite build` still outputs to [static/](../static)
  ([frontend/vite.config.ts](../frontend/vite.config.ts)). Have Django serve
  `static/index.html` for the SPA and `static/assets/*` for assets:
  - Production: serve assets via WhiteNoise (add to middleware) or the existing reverse
    proxy; a catch-all Django view returns `static/index.html` for non-API,
    non-asset paths (mirrors [web_app.py:880-887](../web_app.py)).
- Dev proxy in [frontend/vite.config.ts:7-39](../frontend/vite.config.ts): change the
  proxy target port from Flask's `5001` to Django's dev port (`8000`). All proxied paths
  stay the same.

---

## Phase 8 — Frontend auth changes (minimal)

Keep [frontend/src/api/client.ts](../frontend/src/api/client.ts)'s relative URLs. Changes:

1. **Token storage:** on login, `POST /api/token` → store token (in-memory + `localStorage`).
   Add an `Authorization: Token <token>` header in the shared `request()` helper
   ([client.ts:3-10](../frontend/src/api/client.ts)) when a token is present.
2. **AuthContext** ([AuthContext.tsx](../frontend/src/context/AuthContext.tsx)): replace
   the `GET /api/auth` poll with `GET /api/me` using the stored token; `loggedIn` =
   request succeeds. Clear token on 401.
3. **LoginPage** ([frontend/src/pages/LoginPage.tsx](../frontend/src/pages/LoginPage.tsx)):
   POST to `/api/token` (JSON), store the returned token, set `loggedIn`. Remove the
   form-redirect flow.
4. **Logout** ([MainPage.tsx:59](../frontend/src/pages/MainPage.tsx)): drop the token +
   `setLoggedIn(false)` client-side instead of hitting `/logout`.
5. Rebuild the SPA into `static/` and commit (as today).

---

## Phase 9 — Ingest & ops glue

- `scripts/ingest.py` `_notify_app` ([scripts/ingest.py:817-840]): authenticate the
  cache-clear call with an **admin token** (env `APP_API_TOKEN`) instead of
  `APP_LOGIN_USERNAME`/`APP_LOGIN_PASSWORD` form login.
- `scripts/entrypoint.sh`: after the boundary check, run `python manage.py migrate`
  (creates auth + token tables; the `managed=False` boundary tables/view stay owned by
  [db/schema.sql](../db/schema.sql)), optionally `createsuperuser --no-input` from env,
  then `exec gunicorn config.wsgi:application` (replacing `web_app:app` in
  [Procfile](../Procfile) and the entrypoint).
- [Dockerfile](../Dockerfile): no stage changes needed (GDAL already present); update the
  final command and copy `manage.py` + `config/` + `apps/`.
- `.do/app.yaml`: secrets `SECRET_KEY`/`GOOGLE_MAPS_API_KEY` stay; `LOGIN_PASSWORD` can be
  dropped once the superuser-seed env is in place.

---

## Phase 10 — Testing & cutover

The current behaviour is already pinned by the Flask-era suite — most importantly
[tests/test_web_app_routes.py](../tests/test_web_app_routes.py) (route contracts: status
codes, JSON shapes, validation, auth gating, ETag/304) and
[tests/test_geocode.py](../tests/test_geocode.py) (core resolvers). These are the
**regression spec** for the port; the Phase 6 reference table is derived from them.

1. Port [tests/](../tests) to DRF `APIClient`, reusing the same assertions, so the new
   endpoints must reproduce the pinned JSON shapes and status codes verbatim.
2. Add tests for the new auth surface: token obtain (`POST /api/token`), `401` without a
   token on protected routes (`POST /geocode`, `/api/cache/clear`), `403` for non-admin on
   cache-clear, and `429` once a throttle scope's rate is exceeded.
3. Decide the `0.0`-coordinate behaviour (see Phase 6 note) and either keep the pinned
   `400` or fix it and update the test — don't let it change silently.
4. Run the SPA against the Django dev server end-to-end (map, geocode, batch, xlsform,
   login).
5. Cut over in a single PR (paths are identical, so Flask and Django can't both bind them).
6. Delete [web_app.py](../web_app.py) and the Flask deps (`flask`, `flask-cors`,
   `flask-compress`) once green.

---

## Risks & open questions

- **Materialized view + raw simplification SQL** don't map cleanly to the ORM — keep them
  as raw SQL where tuning matters (`mv_countries` refresh, `*.geojson` simplification).
  This is an accepted, explicit exception, not ORM-everywhere.
- **GeoDjango GDAL/GEOS** must be discoverable by Django at runtime. The Docker image
  already has the GDAL stack; verify Django finds the libs (may need `GDAL_LIBRARY_PATH`).
- **Multi-worker cache** — cache-clear-on-ingest only works across workers with a shared
  backend (Redis). Decide: stay single-worker (status quo) or add Redis.
- **Token in `localStorage`** is XSS-exposed. Acceptable for an internal tool; note it. If
  this becomes public-facing, revisit (JWT in httpOnly cookie, or DRF session auth for the
  browser + tokens for programmatic clients).
- **Response parity** is the hard contract — the committed SPA build calls exact relative
  paths and field names. The existing test suite guards this; keep it green throughout.
```