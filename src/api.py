"""FastAPI backend for the internal content delivery/management portal.

Implements the API surface described in the specification:
  * /api/health        - liveness + Blob connectivity
  * /api/me            - current user name + is_admin flag
  * /api/admin/files   - list blobs (FileAdmin only)
  * /api/admin/upload-url - issue write SAS for direct browser PUT (FileAdmin only)
  * /api/admin/delete  - delete a blob server-side (FileAdmin only)

Authentication is handled by App Service Easy Auth, which forwards the
X-MS-CLIENT-PRINCIPAL header (base64 JSON). Admin authorisation is decided by
the presence of the Entra app role "FileAdmin" in the roles claim.

Storage is accessed with a managed identity (DefaultAzureCredential) and
RBAC; no account keys or connection strings are kept. SAS tokens are
User Delegation SAS, signed via the user delegation key.
"""

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:  # Azure SDKs are optional for local import-only checks
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import (
        BlobSasPermissions,
        BlobServiceClient,
        generate_blob_sas,
    )
    _AZURE_AVAILABLE = True
except ImportError:  # pragma: no cover - allows py_compile without SDK
    DefaultAzureCredential = None
    BlobServiceClient = None
    generate_blob_sas = None
    BlobSasPermissions = None
    _AZURE_AVAILABLE = False

ADMIN_ROLE = "FileAdmin"
STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")
BLOB_CONTAINER_NAME = os.environ.get("BLOB_CONTAINER_NAME", "content")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("portal-api")

app = FastAPI(title="Internal Portal Content API", root_path="")


# --------------------------------------------------------------------------
# Storage helpers (managed identity + RBAC, no account keys)
# --------------------------------------------------------------------------
_blob_service_client = None


def get_blob_service_client():
    """Return a cached BlobServiceClient authenticated via managed identity."""
    global _blob_service_client
    if not _AZURE_AVAILABLE or not STORAGE_ACCOUNT_NAME:
        return None
    if _blob_service_client is None:
        account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
        _blob_service_client = BlobServiceClient(
            account_url=account_url, credential=DefaultAzureCredential()
        )
    return _blob_service_client


# --------------------------------------------------------------------------
# Authentication / authorisation (Easy Auth principal header)
# --------------------------------------------------------------------------
def parse_client_principal(request: Request) -> dict:
    """Decode the X-MS-CLIENT-PRINCIPAL header into name + roles."""
    header = request.headers.get("X-MS-CLIENT-PRINCIPAL")
    if not header:
        return {"name": None, "roles": []}
    try:
        decoded = base64.b64decode(header).decode("utf-8")
        principal = json.loads(decoded)
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return {"name": None, "roles": []}

    name = None
    roles = []
    for claim in principal.get("claims", []):
        typ = claim.get("typ", "")
        val = claim.get("val", "")
        if typ in ("roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"):
            roles.append(val)
        if typ in ("name", "preferred_username",
                   "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"):
            if name is None:
                name = val
    return {"name": name, "roles": roles}


def is_admin(request: Request) -> bool:
    return ADMIN_ROLE in parse_client_principal(request)["roles"]


def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="FileAdmin role required")
    return True


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------
class UploadUrlRequest(BaseModel):
    name: str


class DeleteRequest(BaseModel):
    name: str


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """Liveness + Blob connectivity. 200 when healthy, 503 on Blob failure."""
    client = get_blob_service_client()
    if client is None:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "blob": "unconfigured"},
        )
    try:
        container = client.get_container_client(BLOB_CONTAINER_NAME)
        container.get_container_properties()
        return {"status": "ok", "blob": "ok"}
    except Exception as exc:  # noqa: BLE001 - report any connectivity failure
        logger.warning("Blob connectivity check failed: %s", exc)
        return JSONResponse(
            status_code=503, content={"status": "degraded", "blob": "error"}
        )


@app.get("/api/me")
def me(request: Request):
    principal = parse_client_principal(request)
    return {
        "name": principal["name"],
        "is_admin": ADMIN_ROLE in principal["roles"],
    }


@app.get("/api/admin/files")
def list_files(request: Request, prefix: str = "", _: bool = Depends(require_admin)):
    client = get_blob_service_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Storage not configured")
    container = client.get_container_client(BLOB_CONTAINER_NAME)
    files = []
    for blob in container.list_blobs(name_starts_with=prefix):
        files.append({
            "name": blob.name,
            "size": blob.size,
            "last_modified": blob.last_modified.isoformat() if blob.last_modified else None,
        })
    return {"files": files}


@app.post("/api/admin/upload-url")
def upload_url(req: UploadUrlRequest, request: Request, _: bool = Depends(require_admin)):
    """Issue a short-lived write SAS so the browser can PUT directly to Blob."""
    client = get_blob_service_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Storage not configured")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    expiry = start + timedelta(minutes=35)
    delegation_key = client.get_user_delegation_key(start, expiry)
    sas = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=BLOB_CONTAINER_NAME,
        blob_name=req.name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(create=True, write=True),
        start=start,
        expiry=expiry,
    )
    url = (
        f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        f"{BLOB_CONTAINER_NAME}/{req.name}?{sas}"
    )
    return {"url": url, "expires": expiry.isoformat()}


@app.post("/api/admin/delete")
def delete_file(req: DeleteRequest, request: Request, _: bool = Depends(require_admin)):
    client = get_blob_service_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Storage not configured")
    container = client.get_container_client(BLOB_CONTAINER_NAME)
    container.delete_blob(req.name)
    return {"deleted": req.name}


if __name__ == "__main__":
    import uvicorn

    # uvicorn is fixed to 127.0.0.1:8000 (internal only); do not honour $PORT.
    uvicorn.run(app, host="127.0.0.1", port=8000)
