"""Pluggable state persistence for the nag worker.

Two backends:

- :class:`FileStore` — JSON file on local disk. Used in dev and when running
  the FastAPI app on a long-lived machine.
- :class:`S3Store` — JSON object in an S3 bucket. Used in Lambda where local
  disk is ephemeral.

Backend selection is automatic via :func:`get_state_store`:

* If ``NAG_STATE_BUCKET`` is set in the environment, S3 is used (key defaults
  to ``nag_state.json`` and is overridable via ``NAG_STATE_KEY``).
* Otherwise the local file at ``<repo>/state/nag_state.json`` is used.

This means no source change is needed when switching between local and Lambda
— the environment dictates the backend.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class StateStore(Protocol):
    """Minimal interface every backend implements."""

    def load(self) -> dict[str, str]: ...
    def save(self, state: dict[str, str]) -> None: ...


class FileStore:
    """Local JSON file backend."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt file — start fresh rather than crash the worker.
            return {}

    def save(self, state: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")


class S3Store:
    """S3 object backend. Bucket + key are passed at construction time."""

    def __init__(self, bucket: str, key: str) -> None:
        # boto3 is pre-installed in every Lambda Python runtime. Importing it
        # at module load would force a dependency for every dev install, so
        # we lazy-import here.
        import boto3  # noqa: PLC0415 — intentional lazy import

        self.bucket = bucket
        self.key = key
        self._s3 = boto3.client("s3")

    def load(self) -> dict[str, str]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=self.key)
        except self._s3.exceptions.NoSuchKey:
            return {}
        except Exception:
            # Network blip / IAM hiccup — degrade to empty so the tick proceeds.
            # Persistence resumes on the next save.
            return {}
        try:
            return json.loads(resp["Body"].read())
        except Exception:
            return {}

    def save(self, state: dict[str, str]) -> None:
        body = json.dumps(state, indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=body,
            ContentType="application/json",
        )


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_state_store() -> StateStore:
    """Pick the backend based on the environment.

    S3 wins if ``NAG_STATE_BUCKET`` is set; otherwise fall back to local file.
    """
    bucket = os.environ.get("NAG_STATE_BUCKET")
    if bucket:
        key = os.environ.get("NAG_STATE_KEY", "nag_state.json")
        return S3Store(bucket=bucket, key=key)
    return FileStore(_PROJECT_ROOT / "state" / "nag_state.json")
