from django.contrib import admin

from .models import BoundaryCsvLanguage, BoundaryCsvProject


class BoundaryCsvLanguageInline(admin.TabularInline):
    model = BoundaryCsvLanguage
    extra = 0


@admin.register(BoundaryCsvProject)
class BoundaryCsvProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "updated_at")
    list_filter = ("owner",)
    search_fields = ("name", "slug", "owner__username")
    inlines = [BoundaryCsvLanguageInline]
