"""
Auth endpoints. The SPA authenticates via a Django session cookie (login/
logout below); headless API clients use a token (POST /api/token issues one).

    POST /api/login     -> start a session cookie from username/password
    POST /api/logout    -> end the session
    POST /api/token     -> obtain an API token from username/password (headless)
    GET  /api/me        -> current user info (also plants the CSRF cookie)
    GET  /api/me/token  -> the current user's API token (cookie or token auth)
    POST /api/me/token  -> rotate the API token (invalidates the old one)
"""

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.db import transaction
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


# DRF's built-in token-obtain view; POST {username, password} -> {token}.
# Kept for headless/API clients that authenticate via the Authorization header.
obtain_token = ObtainAuthToken.as_view()


def _user_payload(user):
    """The shape returned by /api/login and /api/me."""
    return {
        "logged_in": True,
        "username": user.username,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


@extend_schema(
    request=AuthTokenSerializer,
    responses={
        200: OpenApiResponse(OpenApiTypes.OBJECT, description="Session started."),
        400: OpenApiResponse(description="Invalid credentials."),
    },
    summary="Log in (session cookie)",
    description="Validate username/password and start a session. Sets the "
                "session cookie used by the web UI for subsequent requests.",
)
@api_view(["POST"])
def login(request):
    """Authenticate and open a session for the web UI."""
    serializer = AuthTokenSerializer(data=request.data,
                                     context={"request": request})
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data["user"]
    django_login(request, user)
    return Response(_user_payload(user))


@extend_schema(
    responses={200: OpenApiResponse(OpenApiTypes.OBJECT, description="Session ended.")},
    summary="Log out (session cookie)",
    description="End the current session and clear the session cookie.",
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    """End the current session."""
    django_logout(request)
    return Response({"logged_in": False})


@extend_schema(
    responses=OpenApiTypes.OBJECT,
    summary="Current user",
    description="Return the authenticated user. The SPA calls this on load to "
                "confirm its session and to receive the CSRF cookie.",
)
@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """Return the authenticated user. The SPA uses this to confirm its session."""
    return Response(_user_payload(request.user))


@extend_schema(
    methods=["GET"],
    responses=OpenApiTypes.OBJECT,
    summary="Get API token",
    description="Return the current user's API token, creating one if none "
                "exists. Use it as `Authorization: Token <token>` for headless "
                "API access. Works with either session or token auth.",
)
@extend_schema(
    methods=["POST"],
    request=None,
    responses=OpenApiTypes.OBJECT,
    summary="Rotate API token",
    description="Replace the current user's API token with a new one. The "
                "previous token is invalidated immediately.",
)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def me_token(request):
    """Retrieve (GET) or rotate (POST) the authenticated user's API token."""
    if request.method == "POST":
        with transaction.atomic():
            Token.objects.filter(user=request.user).delete()
            token = Token.objects.create(user=request.user)
        return Response({"token": token.key}, status=status.HTTP_201_CREATED)

    token, _ = Token.objects.get_or_create(user=request.user)
    return Response({"token": token.key})
