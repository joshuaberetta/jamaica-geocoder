"""
Core endpoints:
    GET  /health            -> DB health check
    POST /api/cache/clear   -> invalidate caches, refresh mv_countries, regen XLSForms (admin)
    GET  /  + /<path>       -> serve the compiled React SPA
"""

import os

from django.conf import settings
from django.db import connection
from django.http import FileResponse, Http404, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

import xlsforms

from apps.geo.cache import clear_geo_caches
from apps.geo.services import refresh_countries_view


@extend_schema(responses=OpenApiTypes.OBJECT, description="Database health check.")
@api_view(["GET"])
def health(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(DISTINCT iso2) FROM cod_adm")
            country_count = cur.fetchone()[0]
        return Response({"status": "ok", "countries_in_db": country_count})
    except Exception as e:
        return Response({"status": "degraded", "error": str(e)}, status=500)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               description="Invalidate caches + refresh views after ingest (admin token).")
@api_view(["POST"])
@permission_classes([IsAdminUser])
def clear_cache(request):
    """Invalidate caches after a data reload. Admin token required."""
    clear_geo_caches()

    try:
        refresh_countries_view()
    except Exception as e:
        return Response(
            {"status": "error", "message": f"Cache cleared but view refresh failed: {e}"},
            status=500,
        )

    country = (request.data.get("country", "") or "").upper() or None
    try:
        if country:
            xlsforms.generate_one(country)
        else:
            xlsforms.generate_all()
    except Exception as e:
        return Response({
            "status": "ok",
            "message": f"Cache cleared; XLSForm regeneration failed: {e}",
        })

    return Response({"status": "ok", "message": "Cache cleared"})


def serve_spa(request, path=""):
    """Serve the compiled React SPA for any route not matched by the API."""
    dist = settings.FRONTEND_DIST
    target = os.path.join(dist, path)
    if path and os.path.isfile(target):
        return FileResponse(open(target, "rb"))
    index = os.path.join(dist, "index.html")
    if os.path.isfile(index):
        return FileResponse(open(index, "rb"), content_type="text/html")
    raise Http404("SPA build not found")
