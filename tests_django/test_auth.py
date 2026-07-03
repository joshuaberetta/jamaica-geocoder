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
from rest_framework.test import APIClient

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


def test_batch_geocode_tolerates_ungeocodable_row(auth_api, pcode_result):
    """Regression: a row that fails to geocode has a missing geometry, which
    surfaces as NaN (a float) — not None — under some geopandas versions. The
    batch must skip it for P-code resolution rather than crashing with
    "'float' object has no attribute 'y'".

    A plain DataFrame is returned so the NaN geometry survives verbatim (a
    GeoDataFrame would coerce it back to None on newer geopandas, hiding the
    exact production failure mode). The view only uses iterrows / row.geometry /
    drop(columns="geometry"), which all work on a plain DataFrame."""
    import pandas as pd
    from shapely.geometry import Point

    # Second row failed to geocode: NaN lat/lon and a NaN (float) geometry.
    result_gdf = pd.DataFrame(
        {"address": ["Good address", "Ungeocodable"],
         "latitude": [18.1, float("nan")],
         "longitude": [-76.5, float("nan")],
         "geocode_confidence": ["ROOFTOP", None],
         "geometry": [Point(-76.5, 18.1), float("nan")]},
    )
    stats = {"total": 2, "successful": 1, "failed": 1, "skipped": 0}

    csv = pd.DataFrame({"address": ["Good address", "Ungeocodable"]}).to_csv(index=False)
    with patch("apps.geocoding.views.geocode_dataframe", return_value=(result_gdf, stats)), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result) as mock_pcodes, \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.post(
            "/geocode",
            {"file": io.BytesIO(csv.encode()), "country": "JM"},
            format="multipart",
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    # Only the geocoded row triggers P-code resolution; the NaN row is skipped.
    assert mock_pcodes.call_count == 1


# ---------------------------------------------------------------------------
# GET /geocode, POST /geocode_single, POST /reverse_geocode — token gating
# ---------------------------------------------------------------------------

def test_geocode_get_requires_auth(api):
    r = api.get("/geocode", {"lat": "18.1", "lon": "-76.5"})
    assert r.status_code == 401


def test_geocode_single_requires_auth(api):
    """No token and no browser Origin → treated as an API client → rejected."""
    r = api.post("/geocode_single", {"address": "Kingston"}, format="json")
    assert r.status_code == 401


def test_reverse_geocode_requires_auth(api):
    """No token and no browser Origin → treated as an API client → rejected."""
    r = api.post("/reverse_geocode", {"latitude": 18.1, "longitude": -76.5}, format="json")
    assert r.status_code == 401


def test_geocode_single_cross_origin_rejected(api):
    """Anonymous request from a foreign Origin is rejected."""
    r = api.post(
        "/geocode_single", {"address": "Kingston"}, format="json",
        HTTP_ORIGIN="https://evil.example.com",
    )
    assert r.status_code == 401


def test_geocode_single_same_origin_ui_allowed(api, pcode_result):
    """Anonymous request from the web UI's own origin is allowed (no token)."""
    with patch("apps.geocoding.views.geocode_address", return_value=(18.1, -76.5, "ROOFTOP")), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = api.post(
            "/geocode_single", {"address": "Kingston"}, format="json",
            HTTP_ORIGIN="http://testserver",
        )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_reverse_geocode_same_origin_ui_allowed(api, pcode_result):
    """Anonymous reverse-geocode from the web UI's own origin is allowed."""
    with patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = api.post(
            "/reverse_geocode", {"latitude": 18.1, "longitude": -76.5}, format="json",
            HTTP_ORIGIN="http://testserver",
        )
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_geocode_get_authenticated(auth_api, pcode_result):
    with patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = auth_api.get("/geocode", {"lat": "18.1", "lon": "-76.5"})
    assert r.status_code == 200
    assert r.json()["success"] is True


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


# ---------------------------------------------------------------------------
# POST /api/login  +  POST /api/logout — session cookie auth (the web UI path)
# ---------------------------------------------------------------------------

def test_login_bad_credentials(api, admin_user):
    r = api.post("/api/login", {"username": "admin", "password": "wrong"}, format="json")
    assert r.status_code == 400


def test_login_starts_session_and_authenticates(api, admin_user):
    """A session login lets a subsequent protected POST through with no token."""
    r = api.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"

    # Same client (now carrying the session cookie) can reach a protected view.
    me = api.get("/api/me")
    assert me.status_code == 200
    assert me.json()["logged_in"] is True


def test_logout_ends_session(api, admin_user):
    api.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    assert api.get("/api/me").status_code == 200

    r = api.post("/api/logout")
    assert r.status_code == 200
    assert api.get("/api/me").status_code == 401


def test_me_plants_csrf_cookie(api, admin_user):
    """GET /api/me sets the CSRF cookie the SPA needs for unsafe requests."""
    api.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    r = api.get("/api/me")
    assert "csrftoken" in r.cookies


def test_session_post_requires_csrf(admin_user, pcode_result):
    """With CSRF enforcement on, a session POST without the token is rejected,
    and succeeds once the X-CSRFToken header is supplied."""
    client = APIClient(enforce_csrf_checks=True)
    client.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    csrf = client.get("/api/me").cookies["csrftoken"].value

    with patch("apps.geocoding.views.geocode_address", return_value=(18.1, -76.5, "ROOFTOP")), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        denied = client.post("/geocode_single", {"address": "Kingston"}, format="json")
        assert denied.status_code == 403

        allowed = client.post(
            "/geocode_single", {"address": "Kingston"}, format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
    assert allowed.status_code == 200


def test_token_client_not_subject_to_csrf(admin_user, pcode_result):
    """Regression guard: header-token clients (curl/Kobo) bypass CSRF even with
    enforcement on, since they carry no session."""
    token, _ = Token.objects.get_or_create(user=admin_user)
    client = APIClient(enforce_csrf_checks=True)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    with patch("apps.geocoding.views.geocode_address", return_value=(18.1, -76.5, "ROOFTOP")), \
         patch("apps.geocoding.views.resolve_pcodes", return_value=pcode_result), \
         patch("apps.geocoding.views.resolve_secondary_boundaries", return_value={}):
        r = client.post("/geocode_single", {"address": "Kingston"}, format="json")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET/POST /api/me/token — retrieve + rotate the API token
# ---------------------------------------------------------------------------

def test_me_token_requires_auth(api):
    assert api.get("/api/me/token").status_code == 401


def test_me_token_get_via_token_auth(auth_api, admin_user):
    """Token-authed client can read its token; it matches the stored one."""
    token, _ = Token.objects.get_or_create(user=admin_user)
    r = auth_api.get("/api/me/token")
    assert r.status_code == 200
    assert r.json()["token"] == token.key


def test_me_token_get_via_session_auth(api, admin_user):
    """Cookie-authed (session) client can read its token too."""
    api.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    r = api.get("/api/me/token")
    assert r.status_code == 200
    assert r.json()["token"]


def test_me_token_rotate_invalidates_old(api, admin_user):
    """POST issues a new token; the old key stops authenticating."""
    old, _ = Token.objects.get_or_create(user=admin_user)
    old_key = old.key

    api.post("/api/login", {"username": "admin", "password": "secret"}, format="json")
    r = api.post("/api/me/token")
    assert r.status_code == 201
    new_key = r.json()["token"]
    assert new_key != old_key

    # Old token no longer works; new one does.
    stale = APIClient()
    stale.credentials(HTTP_AUTHORIZATION=f"Token {old_key}")
    assert stale.get("/api/me").status_code == 401

    fresh = APIClient()
    fresh.credentials(HTTP_AUTHORIZATION=f"Token {new_key}")
    assert fresh.get("/api/me").status_code == 200


# ---------------------------------------------------------------------------
# OpenAPI schema — the new endpoints must be documented
# ---------------------------------------------------------------------------

def test_schema_includes_new_auth_paths(api):
    r = api.get("/api/schema/")
    assert r.status_code == 200
    body = r.content.decode()
    for path in ("/api/login", "/api/logout", "/api/me/token"):
        assert path in body
