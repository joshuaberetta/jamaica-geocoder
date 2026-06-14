"""
Geospatial resolution services, ported from geocode.py to the GeoDjango ORM.

resolve_pcodes / resolve_secondary_boundaries previously issued raw psycopg2
ST_Contains queries; they now use GeoDjango `geom__contains` (which emits the
same ST_Contains against the GIST index). Output dict shapes are kept identical
to the Flask app so the SPA and the test suite see no change.

The Google-API geocoding helpers (geocode_address, geocode_dataframe,
parse_coordinates) are not spatial — they are imported unchanged from geocode.py.
"""

from typing import Any, Dict, Optional

from django.contrib.gis.geos import Point
from django.db import connection

from .models import CodAdm, SecondaryBoundary

# Maps a secondary boundary_type to the response-key prefix for its fields.
# e.g. 'health' -> health_zone_name / health_zone_dhis2 / health_zone_id.
SECONDARY_KEY_PREFIX: Dict[str, str] = {
    "health": "health_zone",
}


def resolve_pcodes(
    lat: float, lon: float, iso2: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Return the deepest-available admin boundary P-codes for a WGS84 point.

    Mirrors geocode.resolve_pcodes: GIST-indexed contains query against cod_adm,
    deepest admin level wins, None-valued pcode/name fields are omitted.
    Returns None if the point falls outside all known boundaries.
    """
    point = Point(lon, lat, srid=4326)
    qs = CodAdm.objects.filter(geom__contains=point)
    if iso2:
        qs = qs.filter(iso2=iso2.upper())

    try:
        row = qs.order_by("-adm_level").first()
    except Exception as e:  # pragma: no cover - defensive, matches old behaviour
        print(f"Database error in resolve_pcodes({lat}, {lon}): {e}")
        return None

    if row is None:
        return None

    result: Dict[str, Any] = {
        "country": row.country_name,
        "country_code": row.iso2,
    }
    for n in range(row.adm_level + 1):
        pcode = getattr(row, f"adm{n}_pcode", None)
        name = getattr(row, f"adm{n}_name", None)
        if pcode:
            result[f"adm{n}_pcode"] = pcode
        if name:
            result[f"adm{n}_name"] = name

    return result


def resolve_secondary_boundaries(
    lat: float, lon: float, iso2: Optional[str] = None
) -> Dict[str, Any]:
    """
    Return non-administrative boundary attributes (e.g. health zone) containing
    a WGS84 point, keyed by a per-type prefix. Empty dict when the point is in no
    secondary boundary (the common case) so the caller can safely merge it.
    """
    point = Point(lon, lat, srid=4326)
    qs = SecondaryBoundary.objects.filter(geom__contains=point)
    if iso2:
        qs = qs.filter(iso2=iso2.upper())

    try:
        matches = list(qs.values("boundary_type", "name", "alt_name", "ref_dhis2", "source_id"))
    except Exception as e:
        # Missing table (data not loaded yet) or other DB error: degrade silently.
        print(f"resolve_secondary_boundaries({lat}, {lon}) skipped: {e}")
        return {}

    result: Dict[str, Any] = {}
    for row in matches:
        prefix = SECONDARY_KEY_PREFIX.get(row["boundary_type"])
        if not prefix:
            continue
        if row.get("name"):
            result[f"{prefix}_name"] = row["name"]
        if row.get("ref_dhis2"):
            result[f"{prefix}_dhis2"] = row["ref_dhis2"]
        if row.get("source_id"):
            result[f"{prefix}_id"] = row["source_id"]

    return result


def refresh_countries_view() -> None:
    """Rebuild the mv_countries materialized view (raw SQL — not ORM-modellable)."""
    with connection.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries")


def boundaries_geojson_sql(iso2: str, level: int) -> str:
    """
    Return a GeoJSON FeatureCollection (as a JSON string) of admin polygons for a
    country/level, simplified with ST_SimplifyPreserveTopology. Kept as raw SQL
    because the simplification + parent-column projection don't map cleanly to the
    ORM; this is the accepted raw-SQL exception from the plan.
    """
    import json

    name_col = f"adm{level}_name"
    pcode_col = f"adm{level}_pcode"
    parent_cols = "".join(f"adm{n}_name, adm{n}_pcode, " for n in range(level))

    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                {pcode_col} AS pcode,
                {name_col}  AS name,
                {parent_cols}
                ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.001)) AS geometry
            FROM cod_adm
            WHERE iso2 = %s AND adm_level = %s
            """,
            [iso2, level],
        )
        columns = [c[0] for c in cur.description]
        rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    features = []
    for row in rows:
        geom = row.pop("geometry")
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom) if geom else None,
            "properties": row,
        })
    return json.dumps({"type": "FeatureCollection", "features": features})


def secondary_boundaries_geojson_sql(iso2: str, btype: str) -> str:
    """GeoJSON FeatureCollection of secondary (e.g. health-zone) polygons. Raw SQL,
    mirroring boundaries_geojson_sql."""
    import json

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT
                name, ref_dhis2, source_id,
                ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.001)) AS geometry
            FROM secondary_boundaries
            WHERE iso2 = %s AND boundary_type = %s
            """,
            [iso2, btype],
        )
        columns = [c[0] for c in cur.description]
        rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    features = []
    for row in rows:
        geom = row.pop("geometry")
        features.append({
            "type": "Feature",
            "geometry": json.loads(geom) if geom else None,
            "properties": row,
        })
    return json.dumps({"type": "FeatureCollection", "features": features})
