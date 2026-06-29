"""Test environment definitions and switching.

The test suite supports multiple environments selected via the ``TEST_ENV``
environment variable (default: ``local``). Switching environments changes the
storage configuration and the base URL that E2E tests target, so the same
tests can run against a local stack, a dev/staging deployment, or CI.

Usage::

    TEST_ENV=local pytest        # default, no external dependencies
    TEST_ENV=ci pytest
    TEST_ENV=staging pytest -m e2e

Each environment is a plain mapping so it is trivial to add new ones.
"""

import os

# Named environments. Add new ones here to make them selectable via TEST_ENV.
ENVIRONMENTS = {
    "local": {
        "name": "local",
        "storage_account_name": "localdevaccount",
        "blob_container_name": "content",
        "base_url": "http://127.0.0.1:8000",
    },
    "ci": {
        "name": "ci",
        "storage_account_name": "ciaccount",
        "blob_container_name": "content",
        "base_url": "http://127.0.0.1:8000",
    },
    "staging": {
        "name": "staging",
        "storage_account_name": "stagingaccount",
        "blob_container_name": "content",
        "base_url": "https://staging.example.com",
    },
}

DEFAULT_ENV = "local"


def current_env_name() -> str:
    """Return the active environment name from ``TEST_ENV`` (default local)."""
    return os.environ.get("TEST_ENV", DEFAULT_ENV)


def get_environment() -> dict:
    """Return config for the active environment, falling back to default."""
    name = current_env_name()
    if name not in ENVIRONMENTS:
        raise ValueError(
            f"Unknown TEST_ENV={name!r}; choose one of {sorted(ENVIRONMENTS)}"
        )
    return ENVIRONMENTS[name]
