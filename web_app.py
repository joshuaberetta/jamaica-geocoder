#!/usr/bin/env python3
"""
Humanitarian Geocoder - Flask web application backed by PostGIS.
"""

import base64
import hashlib
import io
import json
import os
import tempfile
from functools import wraps
from threading import Lock

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
)
from flask_compress import Compress
from flask_cors import CORS
from werkzeug.utils import secure_filename

from geocode import geocode_address, geocode_dataframe, get_db_conn, resolve_pcodes

load_dotenv()

app = Flask(__name__)
CORS(app)
Compress(app)

# ---------------------------------------------------------------------------
# In-memory response caches (invalidated on ingest, not on restart)
# ---------------------------------------------------------------------------

_countries_cache: dict = {}        # {"data": [...], "json": "...", "etag": "..."}
_boundaries_cache: dict = {}       # {(iso2, level): {"json": "...", "etag": "..."}}
_cache_lock = Lock()
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
app.config["UPLOAD_FOLDER"] = tempfile.gettempdir()
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY", "dev-secret-key-change-in-production"
)

USERNAME = os.getenv("LOGIN_USERNAME", "admin")
PASSWORD = os.getenv("LOGIN_PASSWORD", "admin")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


def check_db():
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM cod_adm LIMIT 1")
        print("Database connection OK")
    except Exception as e:
        print(f"WARNING: Database not reachable at startup: {e}")


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    if username == USERNAME and password == PASSWORD:
        session["logged_in"] = True
        return redirect("/")
    return "Invalid username or password", 401


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/")


# ---------------------------------------------------------------------------
# Country list (DB-driven)
# ---------------------------------------------------------------------------


@app.route("/countries")
def countries():
    """All ingested countries with computed centroid for map centering."""
    global _countries_cache

    with _cache_lock:
        cached = _countries_cache.get("json")
        etag = _countries_cache.get("etag")

    if cached:
        if request.headers.get("If-None-Match") == etag:
            return "", 304
        from flask import Response
        resp = Response(cached, mimetype="application/json")
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp

    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT iso2, iso3, country_name,
                           max_adm_level, center_lon, center_lat
                    FROM mv_countries
                    ORDER BY country_name
                """)
                rows = cur.fetchall()

        result = []
        for row in rows:
            result.append({
                "code": row["iso2"],
                "iso3": row["iso3"],
                "name": row["country_name"],
                "key": row["iso2"].lower(),
                "max_adm_level": row["max_adm_level"],
                "map_center": {
                    "lat": round(row["center_lat"], 4) if row["center_lat"] else 0,
                    "lon": round(row["center_lon"], 4) if row["center_lon"] else 0,
                    "zoom": 6,
                },
            })

        body = json.dumps(result)
        etag = hashlib.md5(body.encode()).hexdigest()
        with _cache_lock:
            _countries_cache["json"] = body
            _countries_cache["etag"] = etag

        if request.headers.get("If-None-Match") == etag:
            return "", 304

        from flask import Response
        resp = Response(body, mimetype="application/json")
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Available admin levels for a country
# ---------------------------------------------------------------------------


@app.route("/api/available_levels")
def available_levels():
    """Return the distinct admin levels present in the DB for a country."""
    iso2 = request.args.get("country", "").upper()
    if not iso2:
        return jsonify({"error": "country parameter required"}), 400
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                # Only include a level if the level's own pcode column is
                # actually populated — filters out sparse/empty higher levels
                # written by the ingest even though the country lacks that data.
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
        return jsonify({"iso2": iso2, "levels": levels})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Admin-level name list (province filter)
# ---------------------------------------------------------------------------


@app.route("/api/admin_levels")
def get_admin_levels():
    """Distinct names at a given admin level for one country."""
    try:
        iso2 = request.args.get("country", "").upper()
        if not iso2:
            return jsonify({"error": "country parameter required"}), 400

        try:
            level = int(request.args.get("level", 1))
        except ValueError:
            return jsonify({"error": "level must be an integer"}), 400

        if level not in range(5):
            return jsonify({"error": "level must be 0-4"}), 400

        name_col = f"adm{level}_name"
        with get_db_conn() as conn:
            with conn.cursor() as cur:
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

        return jsonify({
            "iso2": iso2,
            "level": level,
            "label": f"ADM{level}",
            "values": names,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /boundaries.geojson  -- boundary polygons for a country/level (public)
# ---------------------------------------------------------------------------


@app.route("/boundaries.geojson")
def boundaries_geojson():
    """
    Boundary polygons for a given country and admin level as GeoJSON.
    Results are cached in memory after the first request per (country, level).

    Query params:
        country  ISO2 code (required)
        level    admin level integer, default 1
    """
    iso2 = request.args.get("country", "").upper()
    if not iso2:
        return jsonify({"error": "country parameter required"}), 400

    try:
        level = int(request.args.get("level", 1))
    except ValueError:
        return jsonify({"error": "level must be an integer"}), 400

    if level not in range(5):
        return jsonify({"error": "level must be 0-4"}), 400

    cache_key = (iso2, level)
    with _cache_lock:
        cached = _boundaries_cache.get(cache_key)

    if cached:
        etag = cached["etag"]
        if request.headers.get("If-None-Match") == etag:
            return "", 304
        from flask import Response
        resp = Response(cached["json"], mimetype="application/json")
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    name_col = f"adm{level}_name"
    pcode_col = f"adm{level}_pcode"
    # Include all parent level columns so the frontend can show the full hierarchy
    parent_cols = "".join(
        f"adm{n}_name, adm{n}_pcode, " for n in range(level)
    )

    try:
        with get_db_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        {pcode_col} AS pcode,
                        {name_col}  AS name,
                        {parent_cols}
                        ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.001))::json AS geometry
                    FROM cod_adm
                    WHERE iso2 = %s AND adm_level = %s
                    """,
                    [iso2, level],
                )
                rows = cur.fetchall()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    features = []
    for row in rows:
        geom = row.pop("geometry")
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": dict(row),
        })

    fc = json.dumps({"type": "FeatureCollection", "features": features})
    etag = hashlib.md5(fc.encode()).hexdigest()

    with _cache_lock:
        _boundaries_cache[cache_key] = {"json": fc, "etag": etag}

    if request.headers.get("If-None-Match") == etag:
        return "", 304

    from flask import Response
    resp = Response(fc, mimetype="application/json")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ---------------------------------------------------------------------------
# GET /geocode  -- coordinate or address lookup (public)
# ---------------------------------------------------------------------------


@app.route("/geocode", methods=["GET"])
def geocode_get():
    """
    Resolve P-codes from coordinates or a free-text address.

    Query parameters:
        lat / latitude  -- decimal latitude
        lon / longitude -- decimal longitude
        address         -- free-text address (geocoded via Google Places)
        country         -- ISO2 code to scope the lookup (optional)
    """
    try:
        lat_raw = request.args.get("lat") or request.args.get("latitude")
        lon_raw = request.args.get("lon") or request.args.get("longitude")
        address_input = request.args.get("address", "").strip()
        iso2 = request.args.get("country", "").upper() or None

        confidence = None

        if lat_raw is not None and lon_raw is not None:
            try:
                lat = float(lat_raw)
                lon = float(lon_raw)
            except ValueError:
                return jsonify({"error": "Invalid latitude or longitude"}), 400
        elif address_input:
            result = geocode_address(address_input)
            if not result:
                return jsonify({"success": False, "error": "Could not geocode address"}), 404
            lat, lon, confidence = result
        else:
            return jsonify({"error": "Provide lat/lon or address parameters"}), 400

        pcodes = resolve_pcodes(lat, lon, iso2=iso2)
        if not pcodes:
            return jsonify({"success": False, "error": "Point outside known boundaries"}), 404

        response = {"success": True, "latitude": lat, "longitude": lon}
        if confidence:
            response["confidence"] = confidence
        response.update(pcodes)
        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /geocode  -- CSV/XLSX batch upload (requires login)
# ---------------------------------------------------------------------------


@app.route("/geocode", methods=["POST"])
@login_required
def geocode_post():
    try:
        iso2 = request.form.get("country", "").upper() or None
        output_filename = request.form.get("output_filename", "").strip()

        # Look up country name to use as geocoding hint
        country_hint = None
        if iso2:
            try:
                with get_db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT country_name FROM cod_adm WHERE iso2 = %s LIMIT 1",
                            [iso2],
                        )
                        row = cur.fetchone()
                if row:
                    country_hint = row[0]
            except Exception:
                pass

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        limit = request.form.get("limit", type=int)

        try:
            filename = secure_filename(file.filename)
            if filename.endswith((".xlsx", ".xls")):
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
                return jsonify({"error": 'File must have an "address" column'}), 400

        except Exception as e:
            return jsonify({"error": f"Failed to read file: {e}"}), 400

        # Geocode addresses to (lat, lon) points
        points_gdf, stats = geocode_dataframe(
            df, address_column="address", delay=0.05, country_hint=country_hint
        )

        # Resolve P-codes per row via PostGIS
        pcode_rows = []
        for _, row in points_gdf.iterrows():
            if row.geometry is None:
                pcode_rows.append({})
                continue
            lat, lon = row.geometry.y, row.geometry.x
            pcodes = resolve_pcodes(lat, lon, iso2=iso2) or {}
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
        output_format = request.form.get("format", "csv")
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

        return jsonify({
            "success": True,
            "stats": stats,
            "file_data": file_data,
            "filename": out_filename,
            "mimetype": mimetype,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /geocode_single  -- single address lookup (public)
# ---------------------------------------------------------------------------


@app.route("/geocode_single", methods=["POST"])
def geocode_single():
    """Geocode a single address or coordinate string."""
    try:
        data = request.get_json() if request.is_json else request.form
        address_input = data.get("address", "").strip()
        iso2 = data.get("country", "").upper() or None

        if not address_input:
            return jsonify({"error": "address is required"}), 400

        # Look up country name to use as a geocoding hint (improves disambiguation).
        country_hint = None
        if iso2:
            try:
                with get_db_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT country_name FROM mv_countries WHERE iso2 = %s LIMIT 1",
                            (iso2,),
                        )
                        row = cur.fetchone()
                        if row:
                            country_hint = row[0]
            except Exception:
                pass

        result = geocode_address(address_input, country_hint=country_hint)
        if not result:
            return jsonify({"success": False, "error": "Could not geocode the address"})

        lat, lon, confidence = result
        # Resolve pcodes from actual coordinates without country filter — the
        # geocoded location already determines the country.
        pcodes = resolve_pcodes(lat, lon) or {}

        return jsonify({
            "success": True,
            "address": address_input,
            "latitude": lat,
            "longitude": lon,
            "confidence": confidence,
            **pcodes,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /reverse_geocode  -- lat/lon to P-codes (public, used by map clicks)
# ---------------------------------------------------------------------------


@app.route("/reverse_geocode", methods=["POST"])
def reverse_geocode():
    """Resolve P-codes from a latitude/longitude coordinate."""
    try:
        data = request.get_json() if request.is_json else request.form
        lat_raw = data.get("latitude") or data.get("lat")
        lon_raw = data.get("longitude") or data.get("lon")
        iso2 = data.get("country", "").upper() or None

        if lat_raw is None or lon_raw is None:
            return jsonify({"error": "latitude and longitude are required"}), 400

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            return jsonify({"error": "Invalid latitude or longitude"}), 400

        pcodes = resolve_pcodes(lat, lon, iso2=iso2)
        if not pcodes:
            return jsonify({"success": False, "error": "Point outside known boundaries"})

        return jsonify({"success": True, "latitude": lat, "longitude": lon, **pcodes})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.route("/health")
def health():
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(DISTINCT iso2) FROM cod_adm")
                country_count = cur.fetchone()[0]
        return jsonify({"status": "ok", "countries_in_db": country_count})
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Auth state (used by SPA to check session)
# ---------------------------------------------------------------------------


@app.route("/api/auth")
def auth_state():
    return jsonify({"logged_in": bool(session.get("logged_in"))})


# ---------------------------------------------------------------------------
# Cache invalidation (called after ingest)
# ---------------------------------------------------------------------------


@app.route("/api/cache/clear", methods=["POST"])
@login_required
def clear_cache():
    """Invalidate the in-memory countries and boundaries caches after a data reload."""
    with _cache_lock:
        _countries_cache.clear()
        _boundaries_cache.clear()

    # Rebuild the materialized view so the next cold-cache hit is instant.
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_countries")
            conn.commit()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Cache cleared but view refresh failed: {e}"}), 500

    return jsonify({"status": "ok", "message": "Cache cleared"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SPA catch-all — serve the React build for any non-API route
# ---------------------------------------------------------------------------

_STATIC_FOLDER = os.path.join(os.path.dirname(__file__), "static")


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path: str):
    """Serve the compiled React SPA for any route not matched by the API."""
    target = os.path.join(_STATIC_FOLDER, path)
    if path and os.path.exists(target):
        return send_from_directory(_STATIC_FOLDER, path)
    return send_from_directory(_STATIC_FOLDER, "index.html")


if __name__ == "__main__":
    check_db()
    port = int(os.getenv("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
