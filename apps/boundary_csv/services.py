"""
Row builders for the admin-boundary CSV lists.

These are Django-`connection` equivalents of the choices-sheet queries in
scripts/xlsforms.py (`_populated_levels`, `_level_choices`, `_health_zone_choices`)
so the CSV endpoint doesn't depend on the psycopg2 path. Output shapes match the
xlsforms `choices` sheet: admin levels give (name=pcode, label=name); health
zones give (name=value, label=name, adm1=adm1_pcode).
"""

from django.db import connection

# The synthetic level token for the secondary health-zone list.
HEALTH_ZONE = "health_zone"


def populated_levels(iso2: str) -> list:
    """Admin levels (>=1) whose own pcode column is populated for a country.

    Mirrors scripts.xlsforms._populated_levels / geo.available_levels so we never
    serve an empty CSV for a level that country lacks.
    """
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
        return [r[0] for r in cur.fetchall() if r[0] and r[0] >= 1]


def level_rows(iso2: str, level: int):
    """(header, rows) for an admin level. header=['name','label']; rows=[(pcode, name)]."""
    pcode_col = f"adm{level}_pcode"
    name_col = f"adm{level}_name"
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT {pcode_col} AS pcode, {name_col} AS name
            FROM cod_adm
            WHERE iso2 = %s AND {pcode_col} IS NOT NULL
            ORDER BY name
            """,
            [iso2],
        )
        rows = [(r[0], r[1]) for r in cur.fetchall()]
    return ["name", "label"], rows


def health_zone_rows(iso2: str):
    """(header, rows) for health zones. header=['name','label','adm1'];
    rows=[(value, name, adm1_pcode)]. Empty rows if the country has none or the
    secondary table is absent."""
    header = ["name", "label", "adm1"]
    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(s.ref_dhis2, s.source_id) AS value,
                    s.name AS name,
                    (SELECT a.adm1_pcode FROM cod_adm a
                      WHERE a.iso2 = s.iso2 AND a.adm_level = 1
                        AND ST_Intersects(a.geom, s.geom)
                      ORDER BY ST_Area(ST_Intersection(a.geom, s.geom)) DESC
                      LIMIT 1) AS adm1_pcode
                FROM secondary_boundaries s
                WHERE s.iso2 = %s AND s.boundary_type = 'health'
                ORDER BY s.name
                """,
                [iso2],
            )
            rows = [(r[0], r[1], r[2] or "") for r in cur.fetchall() if r[0]]
    except Exception:
        # Missing table (data not loaded) or other DB error: degrade to empty.
        rows = []
    return header, rows


def build_rows(iso2: str, level_token: str):
    """Resolve a level token to (header, rows, label_index) for one country.

    level_token is '1'..'4' (admin level) or 'health_zone'. Returns None when the
    token/country has no rows so the caller can 404.
    """
    iso2 = iso2.upper()
    if level_token == HEALTH_ZONE:
        header, rows = health_zone_rows(iso2)
    else:
        try:
            level = int(level_token)
        except (TypeError, ValueError):
            return None
        if level not in (1, 2, 3, 4) or level not in populated_levels(iso2):
            return None
        header, rows = level_rows(iso2, level)

    if not rows:
        return None
    label_index = header.index("label")
    return header, rows, label_index
