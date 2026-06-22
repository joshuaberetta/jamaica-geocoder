"""
URL routing. Paths are preserved exactly from the Flask app so the committed
React build (which calls relative URLs) keeps working unchanged.

Route order matters: the SPA catch-all is registered last via re_path and must
not shadow any API route above it.
"""

from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from apps.accounts import views as accounts_views
from apps.boundary_csv import views as boundary_csv_views
from apps.core import views as core_views
from apps.geo import views as geo_views
from apps.geocoding import views as geocoding_views

# DRF router for the boundary-CSV management API (token-authed, owner-scoped).
boundary_csv_router = DefaultRouter()
boundary_csv_router.register(
    r"boundary-projects",
    boundary_csv_views.BoundaryCsvProjectViewSet,
    basename="boundary-project",
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # --- Geo / data ---
    path("countries", geo_views.countries),
    path("api/available_levels", geo_views.available_levels),
    path("api/admin_levels", geo_views.admin_levels),
    path("boundaries.geojson", geo_views.boundaries_geojson),
    path("api/secondary_types", geo_views.secondary_types),
    path("secondary_boundaries.geojson", geo_views.secondary_boundaries_geojson),
    path("xlsform", geo_views.download_xlsform),

    # --- Boundary CSV lists ---
    # Management API (token auth): /api/boundary-projects/...
    path("api/", include(boundary_csv_router.urls)),
    # Public CSV serve (no auth). `level` is 1-4 or `health_zone`; the path must
    # end in `.csv` for KoboToolbox external-choice fetches. The 4-segment
    # project-scoped form is matched before the 2-segment default form.
    re_path(
        r"^boundaries/(?P<username>[^/]+)/(?P<project_slug>[^/]+)/"
        r"(?P<iso2>[A-Za-z]{2})/(?P<level_token>[1-4]|health_zone)\.csv$",
        boundary_csv_views.BoundaryCsvProjectExportView.as_view(),
    ),
    re_path(
        r"^boundaries/(?P<iso2>[A-Za-z]{2})/(?P<level_token>[1-4]|health_zone)\.csv$",
        boundary_csv_views.BoundaryCsvDefaultExportView.as_view(),
    ),

    # --- Geocoding ---
    path("geocode", geocoding_views.geocode),                   # GET (single) + POST (batch)
    path("geocode_single", geocoding_views.geocode_single),
    path("reverse_geocode", geocoding_views.reverse_geocode),

    # --- Auth ---
    path("api/login", accounts_views.login),
    path("api/logout", accounts_views.logout),
    path("api/token", accounts_views.obtain_token),
    path("api/me", accounts_views.me),
    path("api/me/token", accounts_views.me_token),

    # --- Core / ops ---
    path("health", core_views.health),
    path("api/cache/clear", core_views.clear_cache),

    # --- API docs ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema")),
]

# SPA catch-all — must be last. Excludes the API/admin prefixes so unknown API
# paths 404 as JSON rather than returning index.html. `admin` is matched with
# an optional trailing slash so /admin (no slash) reaches Django's APPEND_SLASH
# redirect to /admin/ instead of being swallowed by the SPA.
urlpatterns += [
    re_path(r"^(?!admin(/|$)|api/|countries|boundaries\.geojson|secondary_boundaries\.geojson|"
            r"boundaries/|xlsform|geocode|geocode_single|reverse_geocode|health|static/)(?P<path>.*)$",
            core_views.serve_spa),
]
