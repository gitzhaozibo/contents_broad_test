"""Unit tests for auth/principal helpers in src.api (no FastAPI app needed)."""

import base64
import json

import pytest

from src import api
from tests.conftest import make_principal_header

pytestmark = pytest.mark.unit


class _Req:
    """Minimal stand-in for fastapi.Request exposing only headers."""

    def __init__(self, headers=None):
        self.headers = headers or {}


def test_no_header_returns_empty_principal():
    result = api.parse_client_principal(_Req())
    assert result == {"name": None, "roles": []}


def test_invalid_base64_returns_empty_principal():
    result = api.parse_client_principal(_Req({"X-MS-CLIENT-PRINCIPAL": "!!notbase64!!"}))
    assert result == {"name": None, "roles": []}


def test_invalid_json_returns_empty_principal():
    header = base64.b64encode(b"not-json").decode()
    result = api.parse_client_principal(_Req({"X-MS-CLIENT-PRINCIPAL": header}))
    assert result == {"name": None, "roles": []}


def test_parses_name_and_roles():
    header = make_principal_header(name="alice@example.com", roles=["FileAdmin"])
    result = api.parse_client_principal(_Req({"X-MS-CLIENT-PRINCIPAL": header}))
    assert result["name"] == "alice@example.com"
    assert "FileAdmin" in result["roles"]


def test_role_claim_uri_form_is_recognised():
    claims = [{"typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "val": "FileAdmin"}]
    header = base64.b64encode(json.dumps({"claims": claims}).encode()).decode()
    assert api.is_admin(_Req({"X-MS-CLIENT-PRINCIPAL": header})) is True


def test_is_admin_true_and_false():
    admin = {"X-MS-CLIENT-PRINCIPAL": make_principal_header(roles=["FileAdmin"])}
    user = {"X-MS-CLIENT-PRINCIPAL": make_principal_header(roles=[])}
    assert api.is_admin(_Req(admin)) is True
    assert api.is_admin(_Req(user)) is False


def test_require_admin_raises_for_non_admin():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        api.require_admin(_Req())
    assert exc.value.status_code == 403
