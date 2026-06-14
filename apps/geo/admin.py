"""Read-only admin views for the (managed=False) boundary tables — handy for ops
inspection. The data is owned by the ingest pipeline, so editing is disabled."""

from django.contrib import admin

from .models import CodAdm, MvCountries, SecondaryBoundary


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CodAdm)
class CodAdmAdmin(_ReadOnlyAdmin):
    list_display = ("iso2", "country_name", "adm_level", "adm1_name", "adm2_name")
    list_filter = ("iso2", "adm_level")
    search_fields = ("iso2", "country_name", "adm1_name", "adm2_name")


@admin.register(SecondaryBoundary)
class SecondaryBoundaryAdmin(_ReadOnlyAdmin):
    list_display = ("iso2", "boundary_type", "name", "ref_dhis2")
    list_filter = ("iso2", "boundary_type")
    search_fields = ("name", "ref_dhis2")


@admin.register(MvCountries)
class MvCountriesAdmin(_ReadOnlyAdmin):
    list_display = ("iso2", "iso3", "country_name", "max_adm_level")
    search_fields = ("iso2", "country_name")
