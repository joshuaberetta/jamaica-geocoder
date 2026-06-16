"""Custom DRF permissions for the geocoding endpoints."""

from urllib.parse import urlparse

from django.conf import settings
from rest_framework.permissions import BasePermission


def _ui_origin_hosts(request):
    """Hosts allowed to call as the web UI without a token.

    In production the SPA is served same-origin, so the host the request came in
    on is always trusted. CORS_ALLOWED_ORIGINS adds the cross-origin dev case
    (the Vite dev server at localhost:5173).
    """
    hosts = {request.get_host()}
    for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []):
        netloc = urlparse(origin).netloc
        if netloc:
            hosts.add(netloc)
    return hosts


class IsAuthenticatedOrUIClient(BasePermission):
    """Allow token-authenticated API clients, or anonymous requests that come
    from our own web UI (validated via the Origin/Referer header).

    This lets the SPA call the endpoint without a login while still requiring a
    token for programmatic or cross-origin API access. It is not a hard security
    boundary — Origin/Referer can be forged by non-browser clients — but it
    blocks cross-origin abuse and casual scripting. Pair it with throttling.
    """

    message = (
        "Authentication credentials were not provided, and the request did not "
        "originate from the web UI."
    )

    def has_permission(self, request, view):
        # Token-authenticated API clients are always allowed.
        if request.user and request.user.is_authenticated:
            return True

        # If CORS is wide open, the origin gate is meaningless — don't pretend.
        if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
            return True

        # Anonymous: must look like a same-origin browser request. Browsers send
        # Origin on all POSTs; Referer is a fallback for the rare case it's absent.
        allowed = _ui_origin_hosts(request)
        for header in ("HTTP_ORIGIN", "HTTP_REFERER"):
            value = request.META.get(header)
            if value:
                return urlparse(value).netloc in allowed

        # No Origin and no Referer → not a browser → treat as an API client.
        return False
