"""
Read/data endpoints ported from web_app.py:
    GET /countries
    GET /api/available_levels
    GET /api/admin_levels
    GET /boundaries.geojson
    GET /api/secondary_types
    GET /secondary_boundaries.geojson
    GET /xlsform

Response shapes and status codes are kept identical to the Flask app (pinned by
tests/test_web_app_routes.py).
"""

import hashlib
import json
import os

from django.db import connection
from django.http import HttpResponse, HttpResponseNotModified, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from scripts import xlsforms

from . import services
from .cache import cached_json_response
from .models import MvCountries

# Shared OpenAPI param: most read endpoints take a ?country=ISO2.
_COUNTRY_PARAM = OpenApiParameter(
    "country", OpenApiTypes.STR, OpenApiParameter.QUERY,
    required=True, description="ISO 3166-1 alpha-2 country code, e.g. JM",
)


@extend_schema(responses=OpenApiTypes.OBJECT,
               description="All ingested countries with a map-centring centroid.")
@api_view(["GET"])
def countries(request):
    """All ingested countries with computed centroid for map centering."""
    def build():
        rows = MvCountries.objects.all().order_by("country_name")
        result = []
        for row in rows:
            result.append({
                "code": row.iso2,
                "iso3": row.iso3,
                "name": row.country_name,
                "key": row.iso2.lower(),
                "max_adm_level": row.max_adm_level,
                "map_center": {
                    "lat": round(row.center_lat, 4) if row.center_lat else 0,
                    "lon": round(row.center_lon, 4) if row.center_lon else 0,
                    "zoom": 6,
                },
            })
        return json.dumps(result)

    return cached_json_response(request, "geo:countries", build, max_age=300)


@extend_schema(parameters=[_COUNTRY_PARAM], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def available_levels(request):
    """Distinct admin levels present in the DB for a country."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)
    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT adm_level FROM cod_adm
                WHERE iso2 = %s
                  AND CASE adm_level
                        WHEN 1 THEN adm1_pcode
                        WHEN 2 THEN adm2_pcode
                        WHEN 3 THEN adm3_pcode
                        WHEN 4 THEN adm4_pcode
                      END IS NOT NULL
                ORDER BY adm_level
                """,
                [iso2],
            )
            levels = [r[0] for r in cur.fetchall()]
        return Response({"iso2": iso2, "levels": levels})
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(parameters=[
    _COUNTRY_PARAM,
    OpenApiParameter("level", OpenApiTypes.INT, OpenApiParameter.QUERY,
                     description="Admin level 0-4 (default 1)"),
], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def admin_levels(request):
    """Distinct names at a given admin level for one country."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)
    try:
        level = int(request.GET.get("level", 1))
    except ValueError:
        return Response({"error": "level must be an integer"}, status=400)
    if level not in range(5):
        return Response({"error": "level must be 0-4"}, status=400)

    name_col = f"adm{level}_name"
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT {name_col}
                FROM cod_adm
                WHERE iso2 = %s AND adm_level >= %s AND {name_col} IS NOT NULL
                ORDER BY {name_col}
                """,
                [iso2, level],
            )
            names = [r[0] for r in cur.fetchall()]
        return Response({
            "iso2": iso2,
            "level": level,
            "label": f"ADM{level}",
            "values": names,
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(parameters=[
    _COUNTRY_PARAM,
    OpenApiParameter("level", OpenApiTypes.INT, OpenApiParameter.QUERY,
                     description="Admin level 0-4 (default 1)"),
], responses=OpenApiTypes.OBJECT, description="GeoJSON FeatureCollection of admin polygons.")
@api_view(["GET"])
def boundaries_geojson(request):
    """Boundary polygons for a country/level as GeoJSON (cached + ETag)."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)
    try:
        level = int(request.GET.get("level", 1))
    except ValueError:
        return Response({"error": "level must be an integer"}, status=400)
    if level not in range(5):
        return Response({"error": "level must be 0-4"}, status=400)

    try:
        return cached_json_response(
            request,
            f"geo:boundaries:{iso2}:{level}",
            lambda: services.boundaries_geojson_sql(iso2, level),
            max_age=3600,
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(parameters=[_COUNTRY_PARAM], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def secondary_types(request):
    """Distinct secondary boundary types available for a country (empty if none)."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT boundary_type FROM secondary_boundaries "
                "WHERE iso2 = %s ORDER BY boundary_type",
                [iso2],
            )
            types = [r[0] for r in cur.fetchall()]
    except Exception:
        types = []
    return Response({"iso2": iso2, "types": types})


@extend_schema(parameters=[
    _COUNTRY_PARAM,
    OpenApiParameter("type", OpenApiTypes.STR, OpenApiParameter.QUERY,
                     description="Boundary type, e.g. 'health' (default)"),
], responses=OpenApiTypes.OBJECT, description="GeoJSON FeatureCollection of secondary polygons.")
@api_view(["GET"])
def secondary_boundaries_geojson(request):
    """Secondary (e.g. health-zone) polygons for a country as GeoJSON."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)
    btype = request.GET.get("type", "health").lower()

    try:
        return cached_json_response(
            request,
            f"geo:secondary:{iso2}:{btype}",
            lambda: services.secondary_boundaries_geojson_sql(iso2, btype),
            max_age=3600,
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(parameters=[_COUNTRY_PARAM], responses={200: OpenApiTypes.BINARY},
               description="Download a per-country KoboCollect XLSForm (.xlsx).")
@api_view(["GET"])
def download_xlsform(request):
    """Stream a per-country KoboCollect XLSForm, building it on demand if absent."""
    iso2 = request.GET.get("country", "").upper()
    if not iso2:
        return Response({"error": "country parameter required"}, status=400)

    path = os.path.join(xlsforms.XLSFORM_DIR, f"{iso2}.xlsx")
    country_name = iso2
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        "SELECT country_name FROM mv_countries WHERE iso2 = %s LIMIT 1",
                        [iso2],
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        country_name = row[0]
            except Exception:
                pass
        else:
            data, country_name = xlsforms.build_xlsform(iso2)
            try:
                os.makedirs(xlsforms.XLSFORM_DIR, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
            except OSError:
                pass  # Read-only dir: still serve the in-memory bytes.
    except ValueError as e:
        return Response({"error": str(e)}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    etag = hashlib.md5(data).hexdigest()
    if request.headers.get("If-None-Match") == etag:
        return HttpResponseNotModified()

    out_name = f"{iso2} ({country_name}).xlsx"
    resp = HttpResponse(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{out_name}"'
    resp["ETag"] = etag
    resp["Cache-Control"] = "public, max-age=3600"
    return resp
