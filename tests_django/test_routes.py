"""
HTTP-contract tests for the Django/DRF backend, mirroring the Flask suite in
tests/test_web_app_routes.py so response shapes, status codes, validation, auth
gating and ETag/304 are verified to be preserved by the port.

The DB and Google API are mocked at the same boundaries as the Flask tests:
    - apps.geo.services.resolve_pcodes / resolve_secondary_boundaries
    - geocode.geocode_address / geocode_dataframe
    - django.db.connection.cursor (for raw-SQL endpoints)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tests_django.conftest import make_cursor

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def patch_cursor(**kwargs):
    """Patch django.db.connection.cursor to return a mock cursor."""
    cur = make_cursor(**kwargs)
    return patch("django.db.connection.cursor", return_value=cur)


# ---------------------------------------------------------------------------
# /api/available_levels
# ---------------------------------------------------------------------------

def test_available_levels_requires_country(api):
    r = api.get("/api/available_levels")
    assert r.status_code == 400
    assert r.json()["error"] == "country parameter required"


def test_available_levels_returns_sorted_levels(api):
    with patch_cursor(fetchall=[(1,), (2,)]):
        r = api.get("/api/available_levels?country=jm")
    assert r.status_code == 200
    assert r.json() == {"iso2": "JM", "levels": [1, 2]}


# ---------------------------------------------------------------------------
# /api/admin_levels
# ---------------------------------------------------------------------------

def test_admin_levels_requires_country(api):
    assert api.get("/api/admin_levels").status_code == 400


def test_admin_levels_non_integer(api):
    r = api.get("/api/admin_levels?country=JM&level=abc")
    assert r.status_code == 400
    assert "integer" in r.json()["error"]


def test_admin_levels_out_of_range(api):
    r = api.get("/api/admin_levels?country=JM&level=9")
    assert r.status_code == 400
    assert "0-4" in r.json()["error"]


def test_admin_levels_returns_names(api):
    with patch_cursor(fetchall=[("Clarendon",), ("Kingston",)]):
        r = api.get("/api/admin_levels?country=JM&level=1")
    assert r.status_code == 200
    assert r.json() == {
        "iso2": "JM", "level": 1, "label": "ADM1",
        "values": ["Clarendon", "Kingston"],
    }


# ---------------------------------------------------------------------------
# /boundaries.geojson  (+ ETag / 304)
# ---------------------------------------------------------------------------

def test_boundaries_requires_country(api):
    assert api.get("/boundaries.geojson").status_code == 400


def test_boundaries_invalid_level(api):
    assert api.get("/boundaries.geojson?country=JM&level=x").status_code == 400


def test_boundaries_out_of_range(api):
    assert api.get("/boundaries.geojson?country=JM&level=7").status_code == 400


def test_boundaries_feature_collection_and_etag(api):
    fc = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []},
         "properties": {"pcode": "JM01", "name": "Kingston"}},
    ]})
    with patch("apps.geo.views.services.boundaries_geojson_sql", return_value=fc):
        r = api.get("/boundaries.geojson?country=JM&level=1")
    assert r.status_code == 200
    assert r["Content-Type"] == "application/json"
    etag = r["ETag"]
    body = json.loads(r.content)
    assert body["type"] == "FeatureCollection"
    assert body["features"][0]["properties"]["pcode"] == "JM01"

    # cached -> 304 on matching If-None-Match (no rebuild)
    r2 = api.get("/boundaries.geojson?country=JM&level=1", HTTP_IF_NONE_MATCH=etag)
    assert r2.status_code == 304


# ---------------------------------------------------------------------------
# /api/secondary_types
# ---------------------------------------------------------------------------

def test_secondary_types_requires_country(api):
    assert api.get("/api/secondary_types").status_code == 400


def test_secondary_types_returns_list(api):
    with patch_cursor(fetchall=[("health",)]):
        r = api.get("/api/secondary_types?country=CD")
    assert r.status_code == 200
    assert r.json() == {"iso2": "CD", "types": ["health"]}


def test_secondary_types_missing_table_empty(api):
    with patch("django.db.connection.cursor", side_effect=Exception("no table")):
        r = api.get("/api/secondary_types?country=JM")
    assert r.status_code == 200
    assert r.json() == {"iso2": "JM", "types": []}


# ---------------------------------------------------------------------------
# /secondary_boundaries.geojson
# ---------------------------------------------------------------------------

def test_secondary_boundaries_requires_country(api):
    assert api.get("/secondary_boundaries.geojson").status_code == 400


def test_secondary_boundaries_feature_collection(api):
    fc = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None,
         "properties": {"name": "Kasaji", "ref_dhis2": "kiFDojGFG3x", "source_id": "r1"}},
    ]})
    with patch("apps.geo.views.services.secondary_boundaries_geojson_sql", return_value=fc):
        r = api.get("/secondary_boundaries.geojson?country=CD&type=health")
    assert r.status_code == 200
    assert json.loads(r.content)["features"][0]["properties"]["ref_dhis2"] == "kiFDojGFG3x"


# ---------------------------------------------------------------------------
# /xlsform
# ---------------------------------------------------------------------------

def test_xlsform_requires_country(api):
    assert api.get("/xlsform").status_code == 400


def test_xlsform_builds_when_missing(api):
    with patch("apps.geo.views.os.path.exists", return_value=False), \
         patch("apps.geo.views.xlsforms.build_xlsform", return_value=(b"PK\x03\x04fake", "Jamaica")), \
         patch("apps.geo.views.os.makedirs"), \
         patch("builtins.open", MagicMock()):
        r = api.get("/xlsform?country=JM")
    assert r.status_code == 200
    assert r["Content-Type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "JM (Jamaica).xlsx" in r["Content-Disposition"]
    assert r.content == b"PK\x03\x04fake"


def test_xlsform_unknown_country_404(api):
    with patch("apps.geo.views.os.path.exists", return_value=False), \
         patch("apps.geo.views.xlsforms.build_xlsform", side_effect=ValueError("no data")):
        r = api.get("/xlsform?country=ZZ")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /geocode
# ---------------------------------------------------------------------------

def test_geocode_get_requires_params(auth_api):
    assert auth_api.get("/geocode").status_code == 400


def test_geocode_get_invalid_coords(auth_api):
    assert auth_api.get("/geocode?lat=abc&lon=def").status_code == 400


def test_geocode_get_by_coords(auth_api, pcode_result):
    with patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.get("/geocode?lat=18.0&lon=-76.7&country=JM")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["adm1_pcode"] == "JM01"


def test_geocode_get_outside_boundaries_404(auth_api):
    with patch("apps.geocoding.views.resolve_pcodes", return_value=None):
        r = auth_api.get("/geocode?lat=0.1&lon=0.1")
    assert r.status_code == 404
    assert r.json()["success"] is False


def test_geocode_get_by_address(auth_api, pcode_result):
    with patch("apps.geocoding.views.geocode_address", return_value=(18.0, -76.7, "SETTLEMENT")), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.get("/geocode?address=Kingston")
    assert r.status_code == 200
    assert r.json()["confidence"] == "SETTLEMENT"


def test_geocode_get_address_unresolvable_404(auth_api):
    with patch("apps.geocoding.views.geocode_address", return_value=None):
        r = auth_api.get("/geocode?address=Nowhere")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /geocode_single
# ---------------------------------------------------------------------------

def test_geocode_single_missing_address(auth_api):
    assert auth_api.post("/geocode_single", {}, format="json").status_code == 400
    assert auth_api.post("/geocode_single", {"address": ""}, format="json").status_code == 400


def test_geocode_single_success(auth_api, pcode_result):
    with patch("apps.geocoding.views.geocode_address", return_value=(18.123, -76.567, "ROOFTOP")), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.post("/geocode_single", {"address": "Test", "country": "JM"}, format="json")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["latitude"] == 18.123
    assert data["adm1_name"] == "Test Parish"


def test_geocode_single_geocoding_failure(auth_api):
    with patch("apps.geocoding.views.geocode_address", return_value=None):
        r = auth_api.post("/geocode_single", {"address": "Nowhere"}, format="json")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert data["error"] == "Could not geocode the address"


# ---------------------------------------------------------------------------
# POST /reverse_geocode
# ---------------------------------------------------------------------------

def test_reverse_geocode_requires_coords(auth_api):
    assert auth_api.post("/reverse_geocode", {}, format="json").status_code == 400


def test_reverse_geocode_invalid_coords(auth_api):
    r = auth_api.post("/reverse_geocode", {"latitude": "x", "longitude": "y"}, format="json")
    assert r.status_code == 400


def test_reverse_geocode_success(auth_api, pcode_result):
    with patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.post("/reverse_geocode", {"latitude": 18.0, "longitude": -76.7}, format="json")
    assert r.status_code == 200
    assert r.json()["adm1_name"] == "Test Parish"


def test_reverse_geocode_outside_boundaries(auth_api):
    with patch("apps.geocoding.views.resolve_pcodes", return_value=None):
        r = auth_api.post("/reverse_geocode", {"latitude": 5.0, "longitude": -1.0}, format="json")
    assert r.status_code == 200          # 200 with success=False (matches Flask)
    assert r.json()["success"] is False


def test_reverse_geocode_zero_coordinate_rejected(auth_api):
    """KNOWN BUG carried over from Flask: `latitude or lat` treats 0.0 as missing.
    Pinned so the port reproduces it deliberately. See plan Phase 6."""
    r = auth_api.post("/reverse_geocode", {"latitude": 0, "longitude": 0}, format="json")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health_ok(api):
    with patch_cursor(fetchone=(42,)):
        r = api.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "countries_in_db": 42}


def test_health_degraded(api):
    with patch("django.db.connection.cursor", side_effect=Exception("db down")):
        r = api.get("/health")
    assert r.status_code == 500
    assert r.json()["status"] == "degraded"
