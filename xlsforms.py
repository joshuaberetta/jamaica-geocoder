#!/usr/bin/env python3
"""
Generate KoboCollect XLSForms with cascading admin-boundary select_one
questions from the geocoder's PostGIS database.

Each form has one `select_one level_n` question per admin level present for a
country (province -> district -> ...), with choices sourced from cod_adm and a
P-code-prefix cascade filter. Countries with secondary boundaries (e.g. DRC
health zones) get an extra `select_one health_zone` question cascaded under the
selected province (adm1), with each zone assigned to the province it overlaps
most. See data/ahMwxZhoASRpbmSmaTErim.xlsx for the reference shape.

Choice values match the keys the geocoder emits: admin levels store the P-code
(adm{n}_pcode); health zones store ref_dhis2 (fallback source_id).
"""

import io
import os
from datetime import datetime

import pandas as pd
import psycopg2
import psycopg2.extras

from geocode import get_db_conn

# Output directory for pre-generated forms. Defaults to /data/xlsforms so the
# files persist on the mounted data volume across container restarts.
XLSFORM_DIR = os.getenv("XLSFORM_DIR", "/data/xlsforms")


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def _country_name(cur, iso2: str) -> str:
    cur.execute(
        "SELECT country_name FROM mv_countries WHERE iso2 = %s LIMIT 1", [iso2]
    )
    row = cur.fetchone()
    return (row["country_name"] if row else None) or iso2


def _populated_levels(cur, iso2: str) -> list:
    """Admin levels whose own pcode column is actually populated for a country.

    Mirrors the filter in web_app.available_levels so we don't emit empty
    higher-level selects for countries that lack that data.
    """
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
    return [r["adm_level"] for r in cur.fetchall() if r["adm_level"] and r["adm_level"] >= 1]


def _level_choices(cur, iso2: str, level: int) -> list:
    """Distinct (pcode, name) pairs for one admin level."""
    pcode_col = f"adm{level}_pcode"
    name_col = f"adm{level}_name"
    cur.execute(
        f"""
        SELECT DISTINCT {pcode_col} AS pcode, {name_col} AS name
        FROM cod_adm
        WHERE iso2 = %s AND {pcode_col} IS NOT NULL
        ORDER BY name
        """,
        [iso2],
    )
    return cur.fetchall()


def _health_zone_choices(cur, iso2: str) -> list:
    """Health zones for a country, each assigned to the adm1 it overlaps most.

    Returns rows with (value, name, adm1_pcode). value = ref_dhis2 or source_id.
    Empty list when the country has no health-zone secondary boundaries (or the
    table doesn't exist yet).
    """
    try:
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
        return cur.fetchall()
    except Exception as e:
        print(f"  health-zone lookup skipped for {iso2}: {e}")
        return []


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _survey_sheet(levels: list, has_health: bool) -> pd.DataFrame:
    questions = []
    for i in levels:
        questions.append({
            "type": f"select_one level_{i}",
            "name": f"level_{i}",
            "label": f"Level {i}",
            "choice_filter": (
                "starts-with(name, ${" + f"level_{i - 1}" + "})"
                if i > min(levels) else ""
            ),
            "default": '"-"',
            "appearance": "minimal",
            "hxl": "#adm+code",
        })

    if has_health:
        questions.append({
            "type": "select_one health_zone",
            "name": "health_zone",
            "label": "Health Zone",
            "choice_filter": "adm1=${level_1}",
            "default": '"-"',
            "appearance": "minimal",
            "hxl": "#loc+health",
        })

    cols = ["type", "name", "label", "default", "appearance", "hxl", "choice_filter"]
    return pd.DataFrame(questions, columns=cols)


def _choices_sheet(cur, iso2: str, levels: list, health_rows: list) -> pd.DataFrame:
    choices = []
    for i in levels:
        for row in _level_choices(cur, iso2, i):
            choices.append({
                "list_name": f"level_{i}",
                "name": row["pcode"],
                "label": row["name"],
                "adm1": "",
            })

    for row in health_rows:
        if not row["value"]:
            continue
        choices.append({
            "list_name": "health_zone",
            "name": row["value"],
            "label": row["name"],
            "adm1": row["adm1_pcode"] or "",
        })

    cols = ["list_name", "name", "label", "adm1"]
    return pd.DataFrame(choices, columns=cols)


def _settings_sheet(form_title: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "form_title": form_title,
        "version": datetime.now().strftime("%Y%m%d%H%M%S"),
        "allow_choice_duplicates": "yes",
    }])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_xlsform(iso2: str):
    """Build an XLSForm workbook for one country.

    Returns (xlsx_bytes, country_name). Raises if the country has no admin
    levels in the DB.
    """
    iso2 = iso2.upper()
    with get_db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            country_name = _country_name(cur, iso2)
            levels = _populated_levels(cur, iso2)
            if not levels:
                raise ValueError(f"No admin levels found for country {iso2}")

            health_rows = _health_zone_choices(cur, iso2)
            has_health = len(health_rows) > 0

            form_title = f"{iso2} ({country_name})"
            survey = _survey_sheet(levels, has_health)
            choices = _choices_sheet(cur, iso2, levels, health_rows)
            settings = _settings_sheet(form_title)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        survey.to_excel(writer, sheet_name="survey", index=False)
        choices.to_excel(writer, sheet_name="choices", index=False)
        settings.to_excel(writer, sheet_name="settings", index=False)
    output.seek(0)
    return output.read(), country_name


def generate_one(iso2: str, out_dir: str = XLSFORM_DIR) -> str:
    """Build a country's form and write it to {out_dir}/{ISO2}.xlsx."""
    iso2 = iso2.upper()
    os.makedirs(out_dir, exist_ok=True)
    data, _ = build_xlsform(iso2)
    path = os.path.join(out_dir, f"{iso2}.xlsx")
    with open(path, "wb") as f:
        f.write(data)
    return path


def _all_country_codes() -> list:
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT iso2 FROM mv_countries ORDER BY iso2")
            return [r[0] for r in cur.fetchall()]


def generate_all(out_dir: str = XLSFORM_DIR) -> list:
    """Generate forms for every country in mv_countries.

    Continues past per-country failures so one bad country doesn't abort the
    batch. Returns the list of written file paths.
    """
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for iso2 in _all_country_codes():
        try:
            path = generate_one(iso2, out_dir)
            written.append(path)
            print(f"  wrote {path}")
        except Exception as e:
            print(f"  skipped {iso2}: {e}")
    return written
