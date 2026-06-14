"""
Models for the admin-boundary CSV-list feature.

Unlike the geo models (which are `managed = False` views over the PostGIS COD-AB
tables), these are real Django-managed tables — this is the first managed app in
the project, so it owns its own migrations.

A BoundaryCsvProject holds **no** boundary rows: the rows come from `cod_adm` at
serve time. It only pins a set of translation columns (BoundaryCsvLanguage) to
append to the public per-country CSVs, scoped to a user so each user's language
choices are isolated. See apps/boundary_csv/views.py for how they are served.
"""

from django.contrib.auth.models import User
from django.db import models


class BoundaryCsvProject(models.Model):
    """A user's named project pinning translation columns onto the boundary CSVs."""

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="boundary_csv_projects"
    )
    slug = models.SlugField(max_length=255)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    # auto_now bumps on every save; used as part of the public CSV's ETag so
    # adding/removing a language column invalidates cached client copies.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("owner", "slug")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner.username}/{self.slug})"


class BoundaryCsvLanguage(models.Model):
    """One translation column appended to every CSV served under a project.

    `header` is the full XLSForm column header (e.g. 'label::Spanish (es)'). The
    column's cell values are duplicates of the choice label — a ready-to-edit
    scaffold, not stored translations.
    """

    project = models.ForeignKey(
        BoundaryCsvProject, on_delete=models.CASCADE, related_name="languages"
    )
    header = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("project", "header")
        ordering = ["order", "id"]

    def __str__(self):
        return self.header
