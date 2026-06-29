"""Shared pytest fixtures and test-environment wiring.

The ``test_env`` fixture applies the selected environment (``TEST_ENV``) to the
process so that ``src.api`` reads matching ``STORAGE_ACCOUNT_NAME`` /
``BLOB_CONTAINER_NAME`` values. A helper builds Easy Auth principal headers and
unit/integration tests get a TestClient with the Blob service mocked.
"""

import base64
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make ``src`` importable regardless of where pytest is invoked from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.environments import get_environment  # noqa: E402


@pytest.fixture(scope="session")
def test_env():
    """Return the active environment config and export storage env vars."""
    env = get_environment()
    os.environ["STORAGE_ACCOUNT_NAME"] = env["storage_account_name"]
    os.environ["BLOB_CONTAINER_NAME"] = env["blob_container_name"]
    return env


def make_principal_header(name="user@example.com", roles=None):
    """Build a base64 X-MS-CLIENT-PRINCIPAL header like Easy Auth sends."""
    roles = roles or []
    claims = [{"typ": "name", "val": name}]
    claims += [{"typ": "roles", "val": r} for r in roles]
    payload = json.dumps({"claims": claims}).encode("utf-8")
    return base64.b64encode(payload).decode("utf-8")


@pytest.fixture
def admin_headers():
    return {"X-MS-CLIENT-PRINCIPAL": make_principal_header(roles=["FileAdmin"])}


@pytest.fixture
def user_headers():
    return {"X-MS-CLIENT-PRINCIPAL": make_principal_header(roles=[])}


@pytest.fixture
def mock_blob_client():
    """A MagicMock standing in for BlobServiceClient (no real Azure calls)."""
    return MagicMock()


@pytest.fixture
def client(test_env, mock_blob_client, monkeypatch):
    """FastAPI TestClient with the Blob service swapped for a mock."""
    from fastapi.testclient import TestClient

    from src import api

    monkeypatch.setattr(api, "get_blob_service_client", lambda: mock_blob_client)
    return TestClient(api.app)
