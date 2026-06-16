"""
Geocoding endpoints ported from web_app.py:
    GET  /geocode            (token auth, throttled — hits the paid Google API)
    POST /geocode            (token auth — CSV/XLSX batch upload)
    POST /geocode_single     (token auth OR same-origin web UI, throttled)
    POST /reverse_geocode    (token auth OR same-origin web UI, throttled)

The two single-point lookups accept anonymous calls from our own web UI
(validated via Origin/Referer) so the SPA works without a login, while still
requiring a token for programmatic / cross-origin access. See permissions.py.

The Google-API + pandas helpers (geocode_address, geocode_dataframe) are reused
unchanged from the top-level geocode.py module.
"""

import base64
import io

import pandas as pd
from django.db import connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from scripts.geocode import geocode_address, geocode_dataframe
from apps.geo.services import resolve_pcodes, resolve_secondary_boundaries
from apps.geocoding.permissions import IsAuthenticatedOrUIClient


class GeocodeThrottle(ScopedRateThrottle):
    scope = "geocode"


class BatchThrottle(ScopedRateThrottle):
    scope = "batch"


def _country_hint(iso2, table="mv_countries"):
    """Look up a country name to bias Google geocoding. Best-effort."""
    if not iso2:
        return None
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT country_name FROM {table} WHERE iso2 = %s LIMIT 1", [iso2]
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:
        return None


@extend_schema(
    description="GET: resolve P-codes from lat/lon or address (token auth required). "
                "POST: CSV/XLSX batch upload (token auth required).",
    parameters=[
        OpenApiParameter("lat", OpenApiTypes.NUMBER, OpenApiParameter.QUERY),
        OpenApiParameter("lon", OpenApiTypes.NUMBER, OpenApiParameter.QUERY),
        OpenApiParameter("address", OpenApiTypes.STR, OpenApiParameter.QUERY),
        OpenApiParameter("country", OpenApiTypes.STR, OpenApiParameter.QUERY),
    ],
    responses=OpenApiTypes.OBJECT,
)
@api_view(["GET", "POST"])
def geocode(request):
    """Dispatch /geocode by method: GET = single lookup, POST = batch upload.
    Both require token auth. Django routes by path only, so both live on one view."""
    if request.method == "POST":
        return geocode_batch(request._request)
    return geocode_get(request._request)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([GeocodeThrottle])
def geocode_get(request):
    """Resolve P-codes from coordinates or a free-text address."""
    try:
        lat_raw = request.GET.get("lat") or request.GET.get("latitude")
        lon_raw = request.GET.get("lon") or request.GET.get("longitude")
        address_input = request.GET.get("address", "").strip()
        iso2 = request.GET.get("country", "").upper() or None

        confidence = None
        if lat_raw is not None and lon_raw is not None:
            try:
                lat = float(lat_raw)
                lon = float(lon_raw)
            except ValueError:
                return Response({"error": "Invalid latitude or longitude"}, status=400)
        elif address_input:
            result = geocode_address(address_input)
            if not result:
                return Response({"success": False, "error": "Could not geocode address"}, status=404)
            lat, lon, confidence = result
        else:
            return Response({"error": "Provide lat/lon or address parameters"}, status=400)

        pcodes = resolve_pcodes(lat, lon, iso2=iso2)
        if not pcodes:
            return Response({"success": False, "error": "Point outside known boundaries"}, status=404)

        response = {"success": True, "latitude": lat, "longitude": lon}
        if confidence:
            response["confidence"] = confidence
        response.update(pcodes)
        response.update(resolve_secondary_boundaries(lat, lon, iso2=iso2))
        return Response(response)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([BatchThrottle])
def geocode_batch(request):
    """CSV/XLSX batch upload; geocode each row and return a base64-encoded file."""
    try:
        iso2 = (request.data.get("country", "") or "").upper() or None
        output_filename = (request.data.get("output_filename", "") or "").strip()
        country_hint = _country_hint(iso2, table="cod_adm") if iso2 else None

        if "file" not in request.FILES:
            return Response({"error": "No file uploaded"}, status=400)
        file = request.FILES["file"]
        if not file.name:
            return Response({"error": "No file selected"}, status=400)

        try:
            limit = int(request.data.get("limit")) if request.data.get("limit") else None
        except (ValueError, TypeError):
            limit = None

        try:
            if file.name.endswith((".xlsx", ".xls")):
                df = pd.read_excel(file, engine="openpyxl")
            else:
                df = pd.read_csv(file, encoding="utf-8-sig", sep=";")

            if "date" in df.columns:
                def convert_date(date_str):
                    if pd.isna(date_str):
                        return date_str
                    try:
                        parts = str(date_str).strip().split("/")
                        if len(parts) == 2:
                            month, day = parts
                            return f"2025-{int(month):02d}-{int(day):02d}"
                        return date_str
                    except Exception:
                        return date_str

                df["date"] = df["date"].apply(convert_date)

            if limit and limit > 0:
                df = df.head(limit)

            if "address" not in df.columns:
                return Response({"error": 'File must have an "address" column'}, status=400)
        except Exception as e:
            return Response({"error": f"Failed to read file: {e}"}, status=400)

        points_gdf, stats = geocode_dataframe(
            df, address_column="address", delay=0.05, country_hint=country_hint
        )

        pcode_rows = []
        for _, row in points_gdf.iterrows():
            if row.geometry is None:
                pcode_rows.append({})
                continue
            lat, lon = row.geometry.y, row.geometry.x
            pcodes = resolve_pcodes(lat, lon, iso2=iso2) or {}
            pcodes.update(resolve_secondary_boundaries(lat, lon, iso2=iso2))
            pcode_rows.append(pcodes)

        pcode_df = pd.DataFrame(pcode_rows)
        result_df = pd.concat(
            [
                pd.DataFrame(points_gdf.drop(columns="geometry")).reset_index(drop=True),
                pcode_df.reset_index(drop=True),
            ],
            axis=1,
        )

        output = io.BytesIO()
        output_format = request.data.get("format", "csv")
        base_filename = (
            output_filename.rsplit(".", 1)[0] if output_filename else "geocoded_addresses"
        )
        if output_format == "xlsx":
            result_df.to_excel(output, index=False, engine="openpyxl")
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            out_filename = f"{base_filename}.xlsx"
        else:
            result_df.to_csv(output, index=False)
            mimetype = "text/csv"
            out_filename = f"{base_filename}.csv"

        output.seek(0)
        file_data = base64.b64encode(output.read()).decode("utf-8")

        return Response({
            "success": True,
            "stats": stats,
            "file_data": file_data,
            "filename": out_filename,
            "mimetype": mimetype,
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               description="Geocode a single address; body: {address, country?}.")
@api_view(["POST"])
@permission_classes([IsAuthenticatedOrUIClient])
@throttle_classes([GeocodeThrottle])
def geocode_single(request):
    """Geocode a single address or coordinate string."""
    try:
        address_input = (request.data.get("address", "") or "").strip()
        iso2 = (request.data.get("country", "") or "").upper() or None

        if not address_input:
            return Response({"error": "address is required"}, status=400)

        country_hint = _country_hint(iso2)
        result = geocode_address(address_input, country_hint=country_hint)
        if not result:
            return Response({"success": False, "error": "Could not geocode the address"})

        lat, lon, confidence = result
        pcodes = resolve_pcodes(lat, lon) or {}
        secondary = resolve_secondary_boundaries(lat, lon)

        return Response({
            "success": True,
            "address": address_input,
            "latitude": lat,
            "longitude": lon,
            "confidence": confidence,
            **pcodes,
            **secondary,
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT,
               description="Resolve P-codes from a point; body: {latitude, longitude, country?}.")
@api_view(["POST"])
@permission_classes([IsAuthenticatedOrUIClient])
@throttle_classes([GeocodeThrottle])
def reverse_geocode(request):
    """Resolve P-codes from a latitude/longitude coordinate."""
    try:
        lat_raw = request.data.get("latitude") or request.data.get("lat")
        lon_raw = request.data.get("longitude") or request.data.get("lon")
        iso2 = (request.data.get("country", "") or "").upper() or None

        if lat_raw is None or lon_raw is None:
            return Response({"error": "latitude and longitude are required"}, status=400)

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            return Response({"error": "Invalid latitude or longitude"}, status=400)

        pcodes = resolve_pcodes(lat, lon, iso2=iso2)
        if not pcodes:
            return Response({"success": False, "error": "Point outside known boundaries"})

        secondary = resolve_secondary_boundaries(lat, lon, iso2=iso2)
        return Response({"success": True, "latitude": lat, "longitude": lon, **pcodes, **secondary})
    except Exception as e:
        return Response({"error": str(e)}, status=500)
