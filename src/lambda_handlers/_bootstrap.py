"""Cold-start bootstrap: pull secrets from SSM Parameter Store into ``os.environ``.

The rest of the app reads config via :func:`src.config.get_settings`, which
loads from ``os.environ``. This module bridges SSM → env vars so config.py
needs no Lambda-specific changes.

Invoked once per Lambda container at cold start. Subsequent invocations of
:func:`load_ssm_into_env` are no-ops thanks to the module-level guard.

Parameters fetched
------------------
Every SSM parameter under ``$SSM_PARAM_PREFIX`` (e.g. ``/pa-agent/prod/``).
The trailing path segment becomes the env var name with hyphens → underscores
and uppercased::

    /pa-agent/prod/anthropic-api-key  →  ANTHROPIC_API_KEY
    /pa-agent/prod/notion-tasks-ds-id →  NOTION_TASKS_DS_ID

SecureString parameters are auto-decrypted (``WithDecryption=True``).
"""

from __future__ import annotations

import os

_loaded = False


def load_ssm_into_env() -> None:
    """Idempotent SSM → ``os.environ`` loader.

    Safe to call multiple times — only the first call fetches.
    """
    global _loaded
    if _loaded:
        return

    prefix = os.environ.get("SSM_PARAM_PREFIX")
    if not prefix:
        # Not running in Lambda (or misconfigured). Skip silently so local
        # imports of this module don't fail; the caller will see whatever was
        # already in os.environ.
        _loaded = True
        return

    # boto3 is pre-installed in every Lambda Python runtime — no requirement
    # entry needed. Imported lazily so local dev installs don't need it.
    import boto3  # noqa: PLC0415

    ssm = boto3.client("ssm")
    paginator = ssm.get_paginator("get_parameters_by_path")

    # Parameters that are mutable state, not config. Skip these — they're
    # read directly via dedicated stores (e.g. SSMOverrideStore), and pinning
    # them into os.environ at cold start would mean stale values for the
    # life of the warm container.
    _SKIP_LEAVES = {"work-override"}

    for page in paginator.paginate(
        Path=prefix,
        Recursive=False,
        WithDecryption=True,
    ):
        for p in page["Parameters"]:
            # /pa-agent/prod/anthropic-api-key -> ANTHROPIC_API_KEY
            leaf = p["Name"].rsplit("/", 1)[-1]
            if leaf in _SKIP_LEAVES:
                continue
            env_name = leaf.upper().replace("-", "_")
            # Don't overwrite values explicitly set in Lambda env vars.
            os.environ.setdefault(env_name, p["Value"])

    _loaded = True
