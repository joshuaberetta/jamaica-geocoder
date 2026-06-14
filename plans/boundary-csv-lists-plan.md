# Plan: Per-country admin-boundary CSV lists (with per-project translation columns)

## Goal

Add a feature to the geocoder that serves the admin-boundary "choices" data —
the same rows we already put on the `choices` sheet of the per-country XLSForms —
as **CSV files** at URLs that end in `.csv` (required for KoboToolbox external
choice-list fetches).

Decisions locked in with the user:

| Question | Decision |
|----------|----------|
| Translation languages | **Persisted per user+project config** (token-authed CRUD; the CSV serve URL itself is public) |
| CSV granularity | **Per admin level** — one CSV per `(country, level)`, e.g. `.../JM/1.csv` → `name,label` |
| Auth on the `.csv` endpoint | **Public** (no auth) — so KoboToolbox can fetch it without credentials |
| Caching | **Yes** — cache the base level rows; bust on ingest and on project-config edits |

The translation columns are **label duplicates**: for each language a project
configures (e.g. `label::English (en)`, `label::Spanish (es)`), we append a
column whose header is that string and whose every cell is a copy of the `label`
value. No real per-row translated text is stored — the user fills it in
downstream, or it ships as a ready-to-translate scaffold. (This matches the
user's "can just be duplicates of the label column" requirement and keeps the
service stateless w.r.t. boundary data.)

---

## Reference: how the cloned `choices/` app does it

- `choices/backend/api/views.py` → `UserCustomCSVExportView` (lines ~1291–1335):
  public, unauthenticated, URL `/{user}/{project}/custom/{list}.csv`; writes
  `name,label,<orig cols>,<user cols>` with `csv.writer` into an `HttpResponse`
  (`content_type='text/csv'`, `Content-Disposition` attachment).
- `choices/backend/api/models.py` → `ChoiceList.label_column_name`
  ("e.g. `label::English (en)`") and the `UserChoiceListConfig` /
  `UserChoiceListColumn` models that hold a follower's per-project extra columns.

We mirror the **shape** (public per-project `.csv` URL, label-translation column
headers) but **not** the data model: the geocoder has no editable choices — the
rows come from `cod_adm`. So our persisted models only store *which language
columns* a project wants, never the boundary rows themselves.

## Reference: what already exists in the geocoder

- `scripts/xlsforms.py` — `_populated_levels(cur, iso2)`, `_level_choices(cur, iso2, level)`,
  `_health_zone_choices(cur, iso2)`. These already produce exactly the
  `(name, label)` pairs (admin pcode → admin name; health-zone value → name)
  we want to serve. They use psycopg2 (`get_db_conn`); we will add Django-ORM /
  `connection.cursor()` equivalents to match `apps/geo/services.py` style.
- `apps/geo/cache.py` — `cached_json_response(...)` + `clear_geo_caches()`
  (`cache.clear()` on ingest). We reuse the same `django.core.cache` backend.
- `apps/geo/views.py` → `download_xlsform` — the existing precedent for a
  file-download endpoint with ETag + `Cache-Control`.
- `config/urls.py` — explicit `path(...)` routes registered **before** the SPA
  catch-all `re_path`. The catch-all uses a negative-lookahead on known prefixes;
  our new prefix must be added to that lookahead so unknown CSV paths 404 as
  JSON / 404 rather than returning `index.html`.
- `config/settings.py` — DRF token auth is the default; `AllowAny` is the
  default permission. New **managed** models need a new app with migrations
  (today every model is `managed = False`).

---

## Design

### URL scheme

Public CSV serve (no auth), project-scoped so each user's language config is
isolated, ending in `.csv`:

```
GET /boundaries/{username}/{project_slug}/{ISO2}/{level}.csv
```

- `level` token is `1`–`4` (admin level) **or** `health_zone`. Internally this
  is the xlsforms `list_name` (`level_1`, …, `health_zone`); we accept the bare
  number for ergonomics and map it.
- Examples:
  - `/boundaries/josh/my-survey/JM/1.csv` → parishes (`name,label,<langs…>`)
  - `/boundaries/josh/my-survey/JM/2.csv` → districts
  - `/boundaries/josh/my-survey/CD/health_zone.csv` → DRC health zones (`name,label,adm1,<langs…>`)

Why a `/boundaries/` prefix: it gives the SPA catch-all a single clean prefix to
exclude, and avoids colliding with the choices-app-style bare `/{user}/...`
pattern.

Management API (token-authed, scoped to `owner=request.user`), DRF-style:

```
GET    /api/boundary-projects/                     list my projects
POST   /api/boundary-projects/                     create {name, slug?}
GET    /api/boundary-projects/{slug}/              detail (incl. languages, csv_urls)
PATCH  /api/boundary-projects/{slug}/              rename
DELETE /api/boundary-projects/{slug}/
POST   /api/boundary-projects/{slug}/languages/    add    {header: "label::Spanish (es)"}
PATCH  /api/boundary-projects/{slug}/languages/{id}/  rename
DELETE /api/boundary-projects/{slug}/languages/{id}/
```

The detail response includes, for convenience, a `csv_urls` block listing the
public per-level CSV URLs for whatever countries the caller asks about (or a
helper `?country=JM` to enumerate that country's populated levels).

### Data model — new app `apps.boundary_csv`

This is the first **managed** app in the project, so it owns its own migrations
(geo models stay `managed = False`).

```python
# apps/boundary_csv/models.py
from django.contrib.auth.models import User
from django.db import models

class BoundaryCsvProject(models.Model):
    """A user's named project that pins a set of translation columns to append
    to the public admin-boundary CSVs. Holds NO boundary rows — those come from
    cod_adm at serve time."""
    owner       = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name="boundary_csv_projects")
    slug        = models.SlugField(max_length=255)
    name        = models.CharField(max_length=255)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)   # used as cache buster

    class Meta:
        unique_together = ("owner", "slug")

class BoundaryCsvLanguage(models.Model):
    """One translation column appended to every CSV served under a project.
    `header` is the full XLSForm column header, e.g. 'label::Spanish (es)'."""
    project = models.ForeignKey(BoundaryCsvProject, on_delete=models.CASCADE,
                                related_name="languages")
    header  = models.CharField(max_length=255)
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("project", "header")
        ordering = ["order", "id"]
```

> Alternative considered: a single `JSONField` list of headers on the project
> instead of a child model. Rejected for parity with the choices app's
> column-row pattern and to keep stable ids for PATCH/DELETE of individual
> languages. Either is fine; child model chosen.

### Serving logic

`apps/geo/services.py` (or a new `apps/boundary_csv/services.py`) gains a
Django-`connection` equivalent of the xlsforms queries so we don't import the
psycopg2 path:

```python
def level_choice_rows(iso2, level):
    """[(name, label), ...] for an admin level — name=adm{level}_pcode,
    label=adm{level}_name. Mirrors scripts.xlsforms._level_choices."""

def health_zone_rows(iso2):
    """[(value, label, adm1_pcode), ...] mirroring _health_zone_choices."""
```

The public view:

```python
# apps/boundary_csv/views.py
class BoundaryCsvExportView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, username, project_slug, iso2, level_token):
        project = get_object_or_404(BoundaryCsvProject,
                                    owner__username=username, slug=project_slug)
        langs = list(project.languages.all())          # ordered

        base = self._cached_base_rows(iso2.upper(), level_token)  # see caching
        if base is None:                                # unknown level/country
            raise Http404

        header, rows, label_idx = base   # header e.g. ['name','label'] or +['adm1']
        out = StringIO(); w = csv.writer(out)
        w.writerow(header + [l.header for l in langs])
        for r in rows:
            label = r[label_idx]
            w.writerow(list(r) + [label] * len(langs))  # langs = duplicated label

        resp = HttpResponse(out.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{iso2.upper()}_{level_token}.csv"'
        resp["Cache-Control"] = "public, max-age=3600"
        resp["ETag"] = <hash of base etag + project.updated_at + langs>
        # honour If-None-Match -> 304
        return resp
```

- Admin-level CSV columns: `name,label` (+ language columns).
- Health-zone CSV columns: `name,label,adm1` (+ language columns) so the
  KoboCollect cascade filter still works, matching the xlsforms choices sheet.

### Caching strategy

Two layers, both on the existing `django.core.cache` backend:

1. **Base rows per `(iso2, level)`** — static between ingests. Cache key
   `boundary_csv:base:{iso2}:{level_token}`, value = `{header, rows, etag}`,
   `timeout=None`. Built from `cod_adm` on miss. Invalidated by the existing
   `clear_geo_caches()` (`cache.clear()`) that already runs on ingest /
   `POST /api/cache/clear`, and on per-country regen. **No new invalidation
   wiring needed for ingest** — `cache.clear()` already covers our keys.
2. **Per-response ETag** combines the base etag + `project.updated_at` (config
   edits bump `updated_at` via `auto_now`) + the ordered language headers. So:
   - boundary data unchanged + config unchanged → `304 Not Modified` on
     `If-None-Match`.
   - a language added/removed → `updated_at` changes → new ETag → fresh CSV.

   The final CSV body is cheap to assemble from cached base rows on every
   request (duplicating a column is O(rows)), so we do **not** separately cache
   the per-project body — avoids a combinatorial `(project × country × level)`
   cache and keeps invalidation trivial. (If profiling later shows it matters,
   add a body cache keyed by the ETag.)

### URL wiring

`config/urls.py`:

```python
from apps.boundary_csv import views as bcsv_views
# ... before the SPA catch-all:
path("api/boundary-projects/...", include(bcsv_router.urls)),   # DRF router/viewset
re_path(r"^boundaries/(?P<username>[^/]+)/(?P<project_slug>[^/]+)/"
        r"(?P<iso2>[A-Za-z]{2})/(?P<level_token>level_\d|\d|health_zone)\.csv$",
        bcsv_views.BoundaryCsvExportView.as_view()),
```

Then **add `boundaries/` and `api/boundary-projects/`** to the SPA catch-all's
negative-lookahead in the final `re_path` so they aren't shadowed (the
`api/` exclusion already covers the management routes; add `boundaries/`).

### Settings

- Add `"apps.boundary_csv"` to `INSTALLED_APPS`.
- No new env vars. Reuses existing `CACHES` and DRF config.
- Throttle: the public CSV view stays under the default `AnonRateThrottle`
  (`120/min`). Optionally exempt it (set `throttle_classes = []`) since it's
  meant for automated Kobo fetches — flag for the user during implementation.

---

## Step-by-step implementation

1. **Scaffold the app**: `apps/boundary_csv/` with `__init__.py`, `apps.py`,
   `models.py`, `serializers.py`, `views.py`, `urls.py` (or fold routes into
   `config/urls.py`), `admin.py`, `migrations/`. Register in `INSTALLED_APPS`.
2. **Models** (`BoundaryCsvProject`, `BoundaryCsvLanguage`) + `makemigrations`
   + `migrate` (creates the first managed tables). Register both in `admin.py`.
3. **Service queries**: add `level_choice_rows` / `health_zone_rows` to
   `apps/geo/services.py` (Django `connection.cursor()` versions of the existing
   `scripts/xlsforms.py` helpers). Reuse `_populated_levels` logic for level
   validation.
4. **Public CSV view** `BoundaryCsvExportView` with the base-row cache + ETag /
   304 handling. Map `level` token (`1` ↔ `level_1`, `health_zone`).
5. **Management API**: DRF `ModelViewSet` for projects (owner-scoped) +
   nested actions or a second viewset for languages. Serializers expose
   `languages`, `csv_urls`, `role`-style fields. Token auth + `IsAuthenticated`.
6. **URL routing**: register management + public routes before the SPA
   catch-all and extend the catch-all lookahead with `boundaries/`.
7. **Tests** (`tests/` or `tests_django/`):
   - public CSV: correct headers incl. duplicated `label::*` columns; health-zone
     CSV includes `adm1`; unknown country/level → 404; URL ends in `.csv`.
   - caching: second request served from cache; `If-None-Match` → 304; adding a
     language busts the ETag; ingest `cache.clear()` rebuilds base rows.
   - management API: owner isolation (can't see/edit another user's project);
     slug uniqueness per owner; language add/rename/delete.
8. **Docs**: add an "Admin-boundary CSV lists" section to the root `README.md`
   API table, and (optionally) a frontend panel later to manage projects +
   show copyable CSV URLs (out of scope for this plan; backend-first).

---

## Open questions / flags for implementation time

- **Frontend**: this plan is backend-only. A Mantine UI panel to create a
  project, add language columns, and copy the per-country CSV URLs is a natural
  follow-up — confirm whether to include it now or ship the API first.
- **Throttling** the public CSV endpoint: keep the default anon throttle, or
  exempt it for Kobo automation? (Recommend exempt or a generous dedicated
  scope.)
- **`level` token format**: bare number (`/JM/1.csv`) vs xlsforms list_name
  (`/JM/level_1.csv`). Plan supports both; pick one canonical form for docs.
- **Default project**: do we want an implicit "no-translations" path that
  doesn't require creating a project first (e.g. a reserved `_/default` that
  serves `name,label` with zero language columns)? Useful for the simplest
  KoboToolbox case. Decide during step 5.
```