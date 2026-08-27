"""FastAPI backend for the internal content delivery/management portal.

Implements the API surface described in the specification:
  * /api/health        - liveness + Blob connectivity
  * /api/me            - current user name + is_admin flag
  * /api/release-notes - public release note text, newest first
  * /api/admin/files   - list blobs (FileAdmin only)
  * /api/admin/upload  - mirror an upload to nginx and Blob (FileAdmin only)
  * /api/admin/delete  - delete from nginx and Blob (FileAdmin only)

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
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

try:  # Azure SDKs are optional for local import-only checks
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    _AZURE_AVAILABLE = True
except ImportError:  # pragma: no cover - allows py_compile without SDK
    DefaultAzureCredential = None
    BlobServiceClient = None
    _AZURE_AVAILABLE = False

ADMIN_ROLE = "FileAdmin"
RELEASE_NOTES_PREFIX = "release_notes/"
STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")
BLOB_CONTAINER_NAME = os.environ.get("BLOB_CONTAINER_NAME", "content")
DEFAULT_CONTENT_ROOT = "/var/www/html/content"

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


def is_dummy_storage() -> bool:
    """Return whether Azure calls should be replaced by local dummy handling."""
    return os.environ.get("STORAGE_MODE", "azure").lower() == "dummy"


def content_root() -> Path:
    return Path(os.environ.get("CONTENT_ROOT", DEFAULT_CONTENT_ROOT))


def validate_blob_name(name: str) -> tuple[str, ...]:
    """Validate a Blob-style relative path before using it on local disk."""
    if (
        not name
        or name.startswith("/")
        or name.endswith("/")
        or "\\" in name
        or "\x00" in name
    ):
        raise HTTPException(status_code=400, detail="Invalid file name")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise HTTPException(status_code=400, detail="Invalid file name")
    return PurePosixPath(name).parts


def local_file_path(name: str) -> Path:
    return content_root().joinpath(*validate_blob_name(name))


def list_local_files(prefix: str) -> list[dict]:
    root = content_root()
    if not root.exists():
        return []
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if not name.startswith(prefix):
            continue
        stat = path.stat()
        files.append({
            "name": name,
            "size": stat.st_size,
            "last_modified": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return sorted(files, key=lambda item: item["name"])


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
class DeleteRequest(BaseModel):
    name: str


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    """Liveness + Blob connectivity. 200 when healthy, 503 on Blob failure."""
    if is_dummy_storage():
        return {"status": "ok", "blob": "dummy"}
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


@app.get("/api/release-notes")
def release_notes():
    """Return release note text files in descending modification order."""
    if is_dummy_storage():
        files = list_local_files(RELEASE_NOTES_PREFIX)
        notes = [
            {
                **item,
                "content": local_file_path(item["name"]).read_text(
                    encoding="utf-8", errors="replace"
                ),
            }
            for item in files
            if item["name"].lower().endswith(".txt")
        ]
    else:
        client = get_blob_service_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Storage not configured")
        container = client.get_container_client(BLOB_CONTAINER_NAME)
        notes = []
        for blob in container.list_blobs(name_starts_with=RELEASE_NOTES_PREFIX):
            if not blob.name.lower().endswith(".txt"):
                continue
            content = (
                container.get_blob_client(blob.name)
                .download_blob()
                .readall()
                .decode("utf-8", errors="replace")
            )
            notes.append({
                "name": blob.name,
                "size": blob.size,
                "last_modified": (
                    blob.last_modified.isoformat() if blob.last_modified else None
                ),
                "content": content,
            })
    notes.sort(
        key=lambda item: (item["last_modified"] or "", item["name"]),
        reverse=True,
    )
    return {"release_notes": notes}


@app.get("/api/admin/files")
def list_files(request: Request, prefix: str = "", _: bool = Depends(require_admin)):
    if is_dummy_storage():
        return {"files": list_local_files(prefix)}
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


@app.post("/api/admin/upload")
async def upload_file(
    name: str, request: Request, _: bool = Depends(require_admin)
):
    """Stream a file to local disk, then mirror it to Blob when configured."""
    target = local_file_path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".upload-", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            async for chunk in request.stream():
                temporary.write(chunk)

        size = temporary_path.stat().st_size
        if not is_dummy_storage():
            client = get_blob_service_client()
            if client is None:
                raise HTTPException(status_code=503, detail="Storage not configured")
            blob = client.get_container_client(
                BLOB_CONTAINER_NAME
            ).get_blob_client(name)
            with temporary_path.open("rb") as data:
                await run_in_threadpool(
                    blob.upload_blob, data, overwrite=True, length=size
                )

        temporary_path.replace(target)
        return {"uploaded": name, "size": size}
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@app.post("/api/admin/delete")
def delete_file(req: DeleteRequest, request: Request, _: bool = Depends(require_admin)):
    target = local_file_path(req.name)
    if not is_dummy_storage():
        client = get_blob_service_client()
        if client is None:
            raise HTTPException(status_code=503, detail="Storage not configured")
        container = client.get_container_client(BLOB_CONTAINER_NAME)
        container.delete_blob(req.name, delete_snapshots="include")
    target.unlink(missing_ok=True)
    return {"deleted": req.name}


if __name__ == "__main__":
    import uvicorn

    # uvicorn is fixed to 127.0.0.1:8000 (internal only); do not honour $PORT.
    uvicorn.run(app, host="127.0.0.1", port=8000)
