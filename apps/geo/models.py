"""
GeoDjango models mapping the existing PostGIS tables.

These tables and the mv_countries materialized view are created and populated by
db/schema.sql + scripts/ingest.py, so the models are `managed = False`: Django
reads them but never issues DDL for them. The materialized-view refresh and the
GeoJSON simplification queries remain raw SQL (see apps/geo/services.py).
"""

from django.contrib.gis.db import models


class CodAdm(models.Model):
    """One row per administrative boundary polygon at any admin level (0-4)."""

    iso2 = models.CharField(max_length=2)
    iso3 = models.CharField(max_length=3, null=True)
    country_name = models.TextField(null=True)
    adm_level = models.SmallIntegerField()

    adm0_pcode = models.TextField(null=True)
    adm0_name = models.TextField(null=True)
    adm1_pcode = models.TextField(null=True)
    adm1_name = models.TextField(null=True)
    adm2_pcode = models.TextField(null=True)
    adm2_name = models.TextField(null=True)
    adm3_pcode = models.TextField(null=True)
    adm3_name = models.TextField(null=True)
    adm4_pcode = models.TextField(null=True)
    adm4_name = models.TextField(null=True)

    geom = models.MultiPolygonField(srid=4326)

    class Meta:
        managed = False
        db_table = "cod_adm"


class SecondaryBoundary(models.Model):
    """Non-administrative boundary layer (e.g. health zones), keyed by an
    external id such as a DHIS2 org-unit id rather than a P-code."""

    iso2 = models.CharField(max_length=2)
    iso3 = models.CharField(max_length=3, null=True)
    boundary_type = models.TextField()
    level = models.TextField(null=True)
    name = models.TextField(null=True)
    alt_name = models.TextField(null=True)
    ref_dhis2 = models.TextField(null=True)
    source_id = models.TextField(null=True)
    attribution = models.TextField(null=True)

    geom = models.MultiPolygonField(srid=4326)

    class Meta:
        managed = False
        db_table = "secondary_boundaries"


class MvCountries(models.Model):
    """Materialized view: pre-aggregated country list with map-centring centroid.

    Refreshed via raw SQL (REFRESH MATERIALIZED VIEW) after ingest — see
    apps.geo.services.refresh_countries_view.
    """

    iso2 = models.CharField(max_length=2, primary_key=True)
    iso3 = models.CharField(max_length=3, null=True)
    country_name = models.TextField(null=True)
    max_adm_level = models.SmallIntegerField()
    center_lon = models.FloatField(null=True)
    center_lat = models.FloatField(null=True)

    class Meta:
        managed = False
        db_table = "mv_countries"
