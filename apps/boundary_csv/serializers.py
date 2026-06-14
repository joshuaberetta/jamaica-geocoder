"""Serializers for the boundary-CSV management API."""

from rest_framework import serializers

from . import services
from .models import BoundaryCsvLanguage, BoundaryCsvProject


class BoundaryCsvLanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoundaryCsvLanguage
        fields = ["id", "header", "order"]

    def validate_header(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("header cannot be blank.")
        # Uniqueness per project (the model enforces it too, but give a clean 400).
        project = self.context.get("project")
        if project is not None:
            qs = project.languages.filter(header=value)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "This project already has a column with that header."
                )
        return value


class BoundaryCsvProjectSerializer(serializers.ModelSerializer):
    languages = BoundaryCsvLanguageSerializer(many=True, read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    csv_urls = serializers.SerializerMethodField()

    class Meta:
        model = BoundaryCsvProject
        fields = [
            "id", "slug", "name", "owner_username",
            "languages", "csv_urls", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_csv_urls(self, obj):
        """Per-level public CSV URLs for ?country=ISO2 (omitted without it).

        Enumerates the country's populated admin levels plus health zones (if any)
        so the UI can show ready-to-copy KoboToolbox URLs.
        """
        request = self.context.get("request")
        iso2 = request.query_params.get("country", "").upper() if request else ""
        if not iso2:
            return None

        base = f"/boundaries/{obj.owner.username}/{obj.slug}/{iso2}"
        urls = []
        try:
            for level in services.populated_levels(iso2):
                urls.append({"level": str(level), "url": f"{base}/{level}.csv"})
            hz_header, hz_rows = services.health_zone_rows(iso2)
            if hz_rows:
                urls.append({
                    "level": services.HEALTH_ZONE,
                    "url": f"{base}/{services.HEALTH_ZONE}.csv",
                })
        except Exception:
            return urls
        return urls
