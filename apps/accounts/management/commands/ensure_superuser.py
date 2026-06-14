"""
Idempotently create/update a superuser from environment variables, plus mint an
API token for it. Used by the Docker entrypoint to bootstrap an admin without
committing credentials, replacing the old hardcoded LOGIN_USERNAME/PASSWORD.

Env vars:
    DJANGO_SUPERUSER_USERNAME   (default: admin)
    DJANGO_SUPERUSER_PASSWORD   (required; command is a no-op if unset)
    DJANGO_SUPERUSER_EMAIL      (optional)
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Create or update the bootstrap superuser and its API token from env."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "")

        if not password:
            self.stdout.write("DJANGO_SUPERUSER_PASSWORD not set — skipping superuser bootstrap.")
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        if email:
            user.email = email
        user.save()

        token, _ = Token.objects.get_or_create(user=user)

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} superuser '{username}'. API token: {token.key}"))
