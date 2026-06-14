"""
Views for the admin-boundary CSV-list feature.

Public (no auth, throttle-exempt) CSV serve:
    GET /boundaries/{iso2}/{level}.csv                       -> default (no translation columns)
    GET /boundaries/{username}/{project}/{iso2}/{level}.csv  -> project's translation columns appended

Management API (token auth, owner-scoped):
    /api/boundary-projects/                       CRUD on projects
    /api/boundary-projects/{slug}/languages/      add a translation column
    /api/boundary-projects/{slug}/languages/{id}/ rename / delete a column

`level` is 1-4 (admin level) or `health_zone`. Translation columns are duplicates
of the label value under each configured XLSForm header (e.g. 'label::Spanish (es)').
"""

import csv
import hashlib
from io import StringIO

from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import BoundaryCsvLanguage, BoundaryCsvProject
from .serializers import (
    BoundaryCsvLanguageSerializer,
    BoundaryCsvProjectSerializer,
)


# ---------------------------------------------------------------------------
# Public CSV serve
# ---------------------------------------------------------------------------

def _cached_base(iso2: str, level_token: str):
    """Base (header, rows, label_index, etag) for a (country, level), cached.

    The base rows are static between data ingests; invalidated by the existing
    clear_geo_caches() (cache.clear()) on ingest / cache-clear. Returns None when
    the country/level has no rows.
    """
    key = f"boundary_csv:base:{iso2}:{level_token}"
    entry = cache.get(key)
    if entry is None:
        built = services.build_rows(iso2, level_token)
        if built is None:
            return None
        header, rows, label_index = built
        etag = hashlib.md5(repr((header, rows)).encode()).hexdigest()
        entry = {"header": header, "rows": rows,
                 "label_index": label_index, "etag": etag}
        cache.set(key, entry, timeout=None)
    return entry


def _serve_csv(request, iso2, level_token, languages, version_token):
    """Assemble and return the CSV response, honouring If-None-Match/304.

    languages: ordered list of header strings to append (label duplicates).
    version_token: per-config string folded into the ETag (e.g. project.updated_at)
    so config edits bust client caches even when the base rows are unchanged.
    """
    iso2 = iso2.upper()
    base = _cached_base(iso2, level_token)
    if base is None:
        raise Http404("No boundary data for this country/level")

    etag = hashlib.md5(
        f"{base['etag']}:{version_token}:{'|'.join(languages)}".encode()
    ).hexdigest()
    if request.headers.get("If-None-Match") == etag:
        return HttpResponseNotModified()

    label_index = base["label_index"]
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(list(base["header"]) + list(languages))
    for row in base["rows"]:
        label = row[label_index]
        writer.writerow(list(row) + [label] * len(languages))

    resp = HttpResponse(out.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{iso2}_{level_token}.csv"'
    resp["Cache-Control"] = "public, max-age=3600"
    resp["ETag"] = etag
    return resp


class BoundaryCsvDefaultExportView(APIView):
    """Public CSV with no translation columns: /boundaries/{iso2}/{level}.csv."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # automated KoboToolbox fetches — exempt from throttling

    @extend_schema(responses={200: OpenApiTypes.BINARY},
                   description="Admin-boundary choices as CSV (no translation columns).")
    def get(self, request, iso2, level_token):
        return _serve_csv(request, iso2, level_token, languages=[], version_token="default")


class BoundaryCsvProjectExportView(APIView):
    """Public CSV with a project's translation columns appended:
    /boundaries/{username}/{project_slug}/{iso2}/{level}.csv."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # automated KoboToolbox fetches — exempt from throttling

    @extend_schema(responses={200: OpenApiTypes.BINARY},
                   description="Admin-boundary choices as CSV with a project's translation columns.")
    def get(self, request, username, project_slug, iso2, level_token):
        project = get_object_or_404(
            BoundaryCsvProject, owner__username=username, slug=project_slug
        )
        languages = [lang.header for lang in project.languages.all()]
        version_token = project.updated_at.isoformat()
        return _serve_csv(request, iso2, level_token, languages, version_token)


# ---------------------------------------------------------------------------
# Management API
# ---------------------------------------------------------------------------

class BoundaryCsvProjectViewSet(viewsets.ModelViewSet):
    """CRUD on the current user's boundary-CSV projects + their language columns."""

    serializer_class = BoundaryCsvProjectSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"

    def get_queryset(self):
        return (
            BoundaryCsvProject.objects
            .filter(owner=self.request.user)
            .prefetch_related("languages")
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def languages(self, request, slug=None):
        """Add a translation column: {header, order?}."""
        project = self.get_object()
        serializer = BoundaryCsvLanguageSerializer(
            data=request.data, context={"project": project}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(project=project)
        project.save(update_fields=["updated_at"])  # bust the CSV ETag
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"languages/(?P<language_id>\d+)",
    )
    def language(self, request, slug=None, language_id=None):
        """Rename ({header}) or delete a single translation column."""
        project = self.get_object()
        lang = get_object_or_404(
            BoundaryCsvLanguage, project=project, pk=language_id
        )
        if request.method == "DELETE":
            lang.delete()
            project.save(update_fields=["updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = BoundaryCsvLanguageSerializer(
            lang, data=request.data, partial=True, context={"project": project}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        project.save(update_fields=["updated_at"])
        return Response(serializer.data)
