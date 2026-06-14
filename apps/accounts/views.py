"""
Auth endpoints (token-based), replacing the Flask session login:
    POST /api/token   -> obtain an API token from username/password
    GET  /api/me      -> current user info (replaces GET /api/auth)
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


# DRF's built-in token-obtain view; POST {username, password} -> {token}.
obtain_token = ObtainAuthToken.as_view()


@extend_schema(responses=OpenApiTypes.OBJECT,
               description="Return the authenticated user (token required).")
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return the authenticated user. The SPA uses this to confirm its token."""
    u = request.user
    return Response({
        "logged_in": True,
        "username": u.username,
        "is_staff": u.is_staff,
        "is_superuser": u.is_superuser,
    })
