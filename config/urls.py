"""
URL routing. Paths are preserved exactly from the Flask app so the committed
React build (which calls relative URLs) keeps working unchanged.

Route order matters: the SPA catch-all is registered last via re_path and must
not shadow any API route above it.
"""

from django.contrib import admin
from django.urls import path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.accounts import views as accounts_views
from apps.core import views as core_views
from apps.geo import views as geo_views
from apps.geocoding import views as geocoding_views

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

    # --- Geocoding ---
    path("geocode", geocoding_views.geocode),                   # GET (single) + POST (batch)
    path("geocode_single", geocoding_views.geocode_single),
    path("reverse_geocode", geocoding_views.reverse_geocode),

    # --- Auth ---
    path("api/token", accounts_views.obtain_token),
    path("api/me", accounts_views.me),

    # --- Core / ops ---
    path("health", core_views.health),
    path("api/cache/clear", core_views.clear_cache),

    # --- API docs ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema")),
]

# SPA catch-all — must be last. Excludes the API/admin prefixes so unknown API
# paths 404 as JSON rather than returning index.html.
urlpatterns += [
    re_path(r"^(?!admin/|api/|countries|boundaries\.geojson|secondary_boundaries\.geojson|"
            r"xlsform|geocode|geocode_single|reverse_geocode|health|static/)(?P<path>.*)$",
            core_views.serve_spa),
]
