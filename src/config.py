"""Typed configuration loaded from environment / .env via pydantic-settings.

Single source of truth for every secret and tunable. Validation runs at startup
so we fail fast — a missing key surfaces immediately, not three async hops in.

Use ``get_settings()`` everywhere; it returns a process-wide cached instance.

v3 changes:
- ``NOTION_TASKS_DB_ID`` → ``NOTION_TASKS_DS_ID`` (and same for Projects, Jobs).
- New ``NOTION_BRAIN_DUMP_PAGE_ID``.
- Removed Contacts/Journal/Ideas/Bills/Health DB IDs (bills now live in the
  Tasks DB with Type=bill; the rest are out of scope).
- Backward-compat: the old ``..._DB_ID`` names still work for one release
  cycle. A deprecation warning prints at startup if any are detected.
"""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# Env vars we expect to source from .env — if any of these are present in the
# OS environment as EMPTY strings (a common Windows artefact when other tools
# blank out vars at the system level), they shadow our .env values because
# pydantic-settings prioritises os.environ over env_file. Drop them so .env
# wins. Non-empty OS values are still honoured.
_EXPECTED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "NOTION_API_KEY",
    # v3 names
    "NOTION_TASKS_DS_ID",
    "NOTION_PROJECTS_DS_ID",
    "NOTION_JOBS_DS_ID",
    "NOTION_BRAIN_DUMP_PAGE_ID",
    # legacy aliases (still accepted for one release cycle)
    "NOTION_TASKS_DB_ID",
    "NOTION_PROJECTS_DB_ID",
    "NOTION_JOBS_DB_ID",
    # webhook
    "WEBHOOK_SHARED_SECRET",
    # nag worker
    "NTFY_TOPIC",
    "NTFY_BASE_URL",
    "NAG_POLL_INTERVAL_SECONDS",
    "NAG_REPING_INTERVAL_SECONDS",
    # Web Push
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_SUBJECT",
)

# Legacy → v3 env var renames. Used both for AliasChoices (so pydantic loads
# from either name) and for the startup deprecation warning.
_LEGACY_RENAMES = {
    "NOTION_TASKS_DB_ID": "NOTION_TASKS_DS_ID",
    "NOTION_PROJECTS_DB_ID": "NOTION_PROJECTS_DS_ID",
    "NOTION_JOBS_DB_ID": "NOTION_JOBS_DS_ID",
}


def _drop_empty_shadow_env_vars() -> None:
    """Remove empty entries for our config keys from ``os.environ``.

    Idempotent. Called once at module import so any subsequent ``Settings()``
    construction sees a clean slate.
    """
    for name in _EXPECTED_ENV_VARS:
        if name in os.environ and os.environ[name] == "":
            del os.environ[name]


_drop_empty_shadow_env_vars()


class Settings(BaseSettings):
    """Strongly-typed application configuration.

    Required secrets raise on startup if missing; optional data-source IDs
    default to empty strings and can be filled in later.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Anthropic ---
    anthropic_api_key: SecretStr

    # --- Notion auth ---
    notion_api_key: SecretStr

    # --- Notion data-source IDs (v3 names; legacy *_DB_ID names accepted) ---
    notion_tasks_ds_id: str = Field(
        validation_alias=AliasChoices("notion_tasks_ds_id", "notion_tasks_db_id"),
    )
    notion_projects_ds_id: str = Field(
        default="",
        validation_alias=AliasChoices("notion_projects_ds_id", "notion_projects_db_id"),
    )
    notion_jobs_ds_id: str = Field(
        default="",
        validation_alias=AliasChoices("notion_jobs_ds_id", "notion_jobs_db_id"),
    )

    # --- Notion page IDs ---
    notion_brain_dump_page_id: str = ""

    # --- Webhook security ---
    webhook_shared_secret: SecretStr = SecretStr("")

    # --- App config ---
    log_level: str = "INFO"
    environment: str = "local"
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Model IDs (constants, but expose so we can swap without code edits) ---
    classifier_model: str = "claude-haiku-4-5-20251001"
    extractor_model: str = "claude-sonnet-4-6"

    # --- Behaviour tunables ---
    # Confidence below this triggers the orchestrator to add `review` to auto_tags.
    review_confidence_threshold: float = 0.7

    # --- Nag worker / push notifications ---
    # ntfy.sh is a free public push-notification relay. Topic acts as the
    # shared secret (anyone subscribed to the topic can read messages, so
    # the topic name must be hard to guess). Leave NTFY_TOPIC empty to
    # disable the worker (e.g. local dev without pushes).
    ntfy_topic: str = ""
    ntfy_base_url: str = "https://ntfy.sh"
    nag_poll_interval_seconds: int = 300        # query Notion every 5 minutes
    nag_reping_interval_seconds: int = 900      # don't ping the same row more than every 15 min

    # --- Web Push (Tier 3) ----------------------------------------------
    # VAPID keypair for the Web Push protocol. Public key is shipped to
    # the PWA so the browser can subscribe; private key signs outgoing
    # pushes server-side. Both are urlsafe base64 strings (no padding).
    # In Lambda these come from SSM via the bootstrap; locally from .env.
    vapid_public_key: str = ""
    vapid_private_key: SecretStr = SecretStr("")
    # mailto:you@example.com — required by the Push protocol's "subject"
    # field. Push services may contact you here if something's wrong.
    vapid_subject: str = "mailto:you@example.com"

    # --- Backward-compat read accessor ----------------------------------

    @property
    def notion_tasks_db_id(self) -> str:
        """Legacy accessor — alias for ``notion_tasks_ds_id``.

        Kept so any code still referring to the old name keeps working through
        the deprecation window. Remove once Phase 5 (live for 2 weeks) ends.
        """
        return self.notion_tasks_ds_id

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid LOG_LEVEL={v!r}")
        return v

    def ensure_webhook_secret(self) -> str:
        """Return the webhook secret, generating + persisting one if missing.

        Generated on first run so the user never has to think about it; written
        back to .env so the iOS Shortcut sees the same value next launch.
        """
        existing = self.webhook_shared_secret.get_secret_value()
        if existing:
            return existing
        new_secret = secrets.token_urlsafe(32)
        _persist_env_value("WEBHOOK_SHARED_SECRET", new_secret)
        self.webhook_shared_secret = SecretStr(new_secret)
        return new_secret


def _persist_env_value(key: str, value: str) -> None:
    """Append-or-replace a single key in the project ``.env`` file.

    Tiny helper used by ``ensure_webhook_secret`` so first-run secret generation
    survives restarts. Idempotent: replaces the line if the key already exists.
    """
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _warn_about_legacy_env_vars() -> None:
    """Log a deprecation warning if any legacy ``_DB_ID`` names are in use.

    Called once from ``get_settings()`` after the singleton is constructed.
    The aliases still work — this is a heads-up so the user knows to rename
    before the deprecation window ends.
    """
    found: list[tuple[str, str]] = []
    # Check both ``os.environ`` and the .env file contents — pydantic merges both.
    env_file_contents = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    for legacy, modern in _LEGACY_RENAMES.items():
        in_env_file = any(
            line.strip().startswith(f"{legacy}=") and not line.strip().startswith("#")
            for line in env_file_contents.splitlines()
        )
        in_os_env = legacy in os.environ and os.environ[legacy] != ""
        if in_env_file or in_os_env:
            found.append((legacy, modern))
    if found:
        logger = logging.getLogger(__name__)
        for legacy, modern in found:
            logger.warning(
                "config.deprecated_env_var",
                extra={"legacy": legacy, "replacement": modern},
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton ``Settings`` instance."""
    settings = Settings()  # type: ignore[call-arg]  # pydantic loads from env
    _warn_about_legacy_env_vars()
    return settings
