"""Fixtures for the Django/DRF contract suite."""

from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_superuser(username="admin", password="secret")


@pytest.fixture
def auth_api(db, admin_user):
    """APIClient authenticated as an admin via token (the production auth path)."""
    token, _ = Token.objects.get_or_create(user=admin_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


@pytest.fixture
def pcode_result():
    """Sample resolve_pcodes return value (matches the Flask suite's fixture)."""
    return {
        "country": "Jamaica",
        "country_code": "JM",
        "adm0_pcode": "JM", "adm0_name": "Jamaica",
        "adm1_pcode": "JM01", "adm1_name": "Test Parish",
        "adm2_pcode": "JM0101", "adm2_name": "Test Community",
    }


def make_cursor(fetchall=None, fetchone=None, description=None):
    """Build a DB cursor mock usable as a context manager (connection.cursor())."""
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    if fetchall is not None:
        cur.fetchall.return_value = fetchall
    if fetchone is not None:
        cur.fetchone.return_value = fetchone
    if description is not None:
        cur.description = description
    return cur
