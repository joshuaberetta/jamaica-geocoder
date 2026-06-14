"""
Tests for the admin-boundary CSV-list feature (apps.boundary_csv).

Boundary data comes from the managed=False cod_adm/secondary_boundaries tables,
which aren't created in the sqlite test DB — so we patch the row-builder service
(apps.boundary_csv.services.build_rows) the same way the route suite patches the
geo services. The project/language management models are real managed tables.
"""

import csv
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.cache import cache

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _parse(resp):
    return list(csv.reader(StringIO(resp.content.decode())))


# Base rows a country/level would yield: header, rows, label_index.
JM_LEVEL_1 = (["name", "label"], [("JM01", "Kingston"), ("JM02", "Saint Andrew")], 1)
CD_HEALTH = (["name", "label", "adm1"], [("hz1", "Clinic A", "CD01")], 1)


# ---------------------------------------------------------------------------
# Default (no-project) CSV
# ---------------------------------------------------------------------------

def test_default_csv_basic(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1):
        r = api.get("/boundaries/JM/1.csv")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/csv"
    assert "JM_1.csv" in r["Content-Disposition"]
    rows = _parse(r)
    assert rows[0] == ["name", "label"]
    assert rows[1] == ["JM01", "Kingston"]


def test_default_csv_lowercase_iso2_ok(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1):
        r = api.get("/boundaries/jm/1.csv")
    assert r.status_code == 200
    assert "JM_1.csv" in r["Content-Disposition"]


def test_default_csv_unknown_country_404(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=None):
        r = api.get("/boundaries/ZZ/1.csv")
    assert r.status_code == 404


def test_default_csv_health_zone(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=CD_HEALTH):
        r = api.get("/boundaries/CD/health_zone.csv")
    assert r.status_code == 200
    rows = _parse(r)
    assert rows[0] == ["name", "label", "adm1"]
    assert rows[1] == ["hz1", "Clinic A", "CD01"]


def test_invalid_level_token_not_routed(api):
    # level 5 / arbitrary tokens don't match the URL pattern -> SPA/404, never 200 CSV
    r = api.get("/boundaries/JM/5.csv")
    assert r.status_code != 200 or r["Content-Type"] != "text/csv"


# ---------------------------------------------------------------------------
# Caching / ETag
# ---------------------------------------------------------------------------

def test_default_csv_etag_304(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1) as m:
        r = api.get("/boundaries/JM/1.csv")
        etag = r["ETag"]
        # Second request with matching ETag -> 304, and base rows served from cache
        # (build_rows not called again).
        r2 = api.get("/boundaries/JM/1.csv", HTTP_IF_NONE_MATCH=etag)
    assert r2.status_code == 304
    assert m.call_count == 1


# ---------------------------------------------------------------------------
# Project-scoped CSV with translation columns
# ---------------------------------------------------------------------------

@pytest.fixture
def project(db, admin_user):
    from apps.boundary_csv.models import BoundaryCsvLanguage, BoundaryCsvProject
    p = BoundaryCsvProject.objects.create(owner=admin_user, slug="my-survey", name="My Survey")
    BoundaryCsvLanguage.objects.create(project=p, header="label::English (en)", order=0)
    BoundaryCsvLanguage.objects.create(project=p, header="label::Spanish (es)", order=1)
    return p


def test_project_csv_appends_label_duplicates(api, project):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1):
        r = api.get("/boundaries/admin/my-survey/JM/1.csv")
    assert r.status_code == 200
    rows = _parse(r)
    assert rows[0] == ["name", "label", "label::English (en)", "label::Spanish (es)"]
    # translation cells duplicate the label
    assert rows[1] == ["JM01", "Kingston", "Kingston", "Kingston"]
    assert rows[2] == ["JM02", "Saint Andrew", "Saint Andrew", "Saint Andrew"]


def test_project_csv_unknown_project_404(api):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1):
        r = api.get("/boundaries/admin/nope/JM/1.csv")
    assert r.status_code == 404


def test_project_csv_etag_changes_when_language_added(api, project):
    with patch("apps.boundary_csv.services.build_rows", return_value=JM_LEVEL_1):
        r1 = api.get("/boundaries/admin/my-survey/JM/1.csv")
        etag1 = r1["ETag"]
        # Add a language -> project.updated_at bumps -> ETag must change.
        from apps.boundary_csv.models import BoundaryCsvLanguage
        BoundaryCsvLanguage.objects.create(project=project, header="label::French (fr)", order=2)
        project.save(update_fields=["updated_at"])
        r2 = api.get("/boundaries/admin/my-survey/JM/1.csv", HTTP_IF_NONE_MATCH=etag1)
    assert r2.status_code == 200  # not 304 — config changed
    assert r2["ETag"] != etag1


# ---------------------------------------------------------------------------
# Management API
# ---------------------------------------------------------------------------

def test_create_project_requires_auth(api):
    assert api.post("/api/boundary-projects/", {"slug": "x", "name": "X"}, format="json").status_code == 401


def test_create_and_list_project(auth_api):
    r = auth_api.post("/api/boundary-projects/", {"slug": "survey", "name": "Survey"}, format="json")
    assert r.status_code == 201
    assert r.json()["owner_username"] == "admin"
    r2 = auth_api.get("/api/boundary-projects/")
    results = r2.json()["results"] if isinstance(r2.json(), dict) else r2.json()
    assert any(p["slug"] == "survey" for p in results)


def test_project_owner_isolation(auth_api, db):
    from django.contrib.auth import get_user_model
    from apps.boundary_csv.models import BoundaryCsvProject
    other = get_user_model().objects.create_user(username="other", password="pw")
    BoundaryCsvProject.objects.create(owner=other, slug="hidden", name="Hidden")
    r = auth_api.get("/api/boundary-projects/hidden/")
    assert r.status_code == 404  # not visible to admin


def test_add_rename_delete_language(auth_api):
    auth_api.post("/api/boundary-projects/", {"slug": "s", "name": "S"}, format="json")
    # add
    r = auth_api.post("/api/boundary-projects/s/languages/",
                      {"header": "label::Spanish (es)"}, format="json")
    assert r.status_code == 201
    lang_id = r.json()["id"]
    # duplicate header rejected
    dup = auth_api.post("/api/boundary-projects/s/languages/",
                        {"header": "label::Spanish (es)"}, format="json")
    assert dup.status_code == 400
    # rename
    r2 = auth_api.patch(f"/api/boundary-projects/s/languages/{lang_id}/",
                        {"header": "label::French (fr)"}, format="json")
    assert r2.status_code == 200
    assert r2.json()["header"] == "label::French (fr)"
    # delete
    r3 = auth_api.delete(f"/api/boundary-projects/s/languages/{lang_id}/")
    assert r3.status_code == 204


def test_csv_urls_for_country(auth_api):
    auth_api.post("/api/boundary-projects/", {"slug": "s", "name": "S"}, format="json")
    with patch("apps.boundary_csv.services.populated_levels", return_value=[1, 2]), \
         patch("apps.boundary_csv.services.health_zone_rows", return_value=(["name", "label", "adm1"], [])):
        r = auth_api.get("/api/boundary-projects/s/?country=JM")
    assert r.status_code == 200
    urls = r.json()["csv_urls"]
    assert {"level": "1", "url": "/boundaries/admin/s/JM/1.csv"} in urls
    assert {"level": "2", "url": "/boundaries/admin/s/JM/2.csv"} in urls
