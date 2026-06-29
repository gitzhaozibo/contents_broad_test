"""Integration tests for API endpoints via FastAPI TestClient (Blob mocked)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.integration


def test_me_anonymous(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"name": None, "is_admin": False}


def test_me_admin(client, admin_headers):
    r = client.get("/api/me", headers=admin_headers)
    body = r.json()
    assert body["is_admin"] is True
    assert body["name"] == "user@example.com"


def test_health_ok(client, mock_blob_client):
    mock_blob_client.get_container_client.return_value.get_container_properties.return_value = {}
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "blob": "ok"}


def test_health_blob_error(client, mock_blob_client):
    mock_blob_client.get_container_client.return_value.get_container_properties.side_effect = RuntimeError("boom")
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"


def test_admin_files_requires_admin(client):
    assert client.get("/api/admin/files").status_code == 403


def test_admin_files_lists_blobs(client, mock_blob_client, admin_headers):
    blob = MagicMock(name="manuals/a.pdf", size=123,
                     last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc))
    blob.name = "manuals/a.pdf"
    mock_blob_client.get_container_client.return_value.list_blobs.return_value = [blob]
    r = client.get("/api/admin/files", headers=admin_headers)
    assert r.status_code == 200
    files = r.json()["files"]
    assert files[0]["name"] == "manuals/a.pdf"
    assert files[0]["size"] == 123


def test_delete_requires_admin(client):
    assert client.post("/api/admin/delete", json={"name": "x"}).status_code == 403


def test_delete_admin(client, mock_blob_client, admin_headers):
    r = client.post("/api/admin/delete", json={"name": "manuals/a.pdf"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"deleted": "manuals/a.pdf"}
    mock_blob_client.get_container_client.return_value.delete_blob.assert_called_once_with("manuals/a.pdf")
