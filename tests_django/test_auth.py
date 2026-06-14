"""
Tests for the new token-auth surface that replaces the Flask session login:
    POST /api/token       obtain a token from credentials
    GET  /api/me          current user (replaces /api/auth)
    POST /geocode         batch upload — token required (was session login_required)
    POST /api/cache/clear admin token required
"""

import io
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# /api/token  +  /api/me
# ---------------------------------------------------------------------------

def test_token_obtain_success(api, admin_user):
    r = api.post("/api/token", {"username": "admin", "password": "secret"}, format="json")
    assert r.status_code == 200
    assert "token" in r.json()


def test_token_obtain_bad_credentials(api, admin_user):
    r = api.post("/api/token", {"username": "admin", "password": "wrong"}, format="json")
    assert r.status_code == 400


def test_me_requires_auth(api):
    assert api.get("/api/me").status_code == 401


def test_me_returns_user(auth_api):
    r = auth_api.get("/api/me")
    assert r.status_code == 200
    data = r.json()
    assert data["logged_in"] is True
    assert data["username"] == "admin"
    assert data["is_superuser"] is True


# ---------------------------------------------------------------------------
# POST /geocode (batch) — token gating
# ---------------------------------------------------------------------------

def test_batch_geocode_requires_auth(api):
    data = {"file": io.BytesIO(b"address\nTest")}
    r = api.post("/geocode", data, format="multipart")
    assert r.status_code == 401


def test_batch_geocode_authenticated_no_file(auth_api):
    r = auth_api.post("/geocode", {}, format="multipart")
    assert r.status_code == 400
    assert r.json()["error"] == "No file uploaded"


def test_batch_geocode_non_admin_user_allowed(api, db, pcode_result):
    """Batch only needs authentication (not admin). A regular user with a token
    can run it."""
    import geopandas as gpd
    from shapely.geometry import Point

    User = get_user_model()
    user = User.objects.create_user(username="bob", password="pw")
    token, _ = Token.objects.get_or_create(user=user)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    gdf = gpd.GeoDataFrame(
        {"address": ["Test 1"], "latitude": [18.1], "longitude": [-76.5],
         "geocode_confidence": ["ROOFTOP"], "geometry": [Point(-76.5, 18.1)]},
        crs="EPSG:4326",
    )
    stats = {"total": 1, "successful": 1, "failed": 0, "skipped": 0}

    import pandas as pd
    csv = pd.DataFrame({"address": ["Test 1"]}).to_csv(index=False)
    with patch("apps.geocoding.views.geocode_dataframe", return_value=(gdf, stats)), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = api.post(
            "/geocode",
            {"file": io.BytesIO(csv.encode()), "country": "JM"},
            format="multipart",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["filename"] == "geocoded_addresses.csv"


# ---------------------------------------------------------------------------
# POST /api/cache/clear — admin gating
# ---------------------------------------------------------------------------

def test_cache_clear_requires_auth(api):
    assert api.post("/api/cache/clear").status_code == 401


def test_cache_clear_non_admin_forbidden(api, db):
    User = get_user_model()
    user = User.objects.create_user(username="bob", password="pw")
    token, _ = Token.objects.get_or_create(user=user)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    assert api.post("/api/cache/clear").status_code == 403


def test_cache_clear_admin_refreshes_view(auth_api):
    with patch("apps.core.views.refresh_countries_view") as mock_refresh, \
         patch("apps.core.views.clear_geo_caches") as mock_clear, \
         patch("apps.core.views.xlsforms.generate_all") as mock_gen:
        r = auth_api.post("/api/cache/clear", {}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    mock_refresh.assert_called_once()
    mock_clear.assert_called_once()
    mock_gen.assert_called_once()


def test_cache_clear_single_country(auth_api):
    with patch("apps.core.views.refresh_countries_view"), \
         patch("apps.core.views.clear_geo_caches"), \
         patch("apps.core.views.xlsforms.generate_one") as mock_one, \
         patch("apps.core.views.xlsforms.generate_all") as mock_all:
        r = auth_api.post("/api/cache/clear", {"country": "jm"}, format="json")
    assert r.status_code == 200
    mock_one.assert_called_once_with("JM")
    mock_all.assert_not_called()
