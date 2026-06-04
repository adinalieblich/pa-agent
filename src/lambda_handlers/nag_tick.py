"""One-shot nag worker handler — invoked by EventBridge every 5 minutes.

The original long-running worker (:class:`src.workers.nag_worker.NagWorker`)
is a forever-loop that ticks every ``nag_poll_interval_seconds``. In Lambda
we don't run forever — EventBridge is the scheduler. So we wire up a single
``_tick_safely()`` call per invocation and return.

State (``page_id → last_notified_at``) persists in S3 via the auto-selected
:mod:`src.state_backend` (the ``NAG_STATE_BUCKET`` env var on this Lambda
triggers the S3 backend).
"""

from __future__ import annotations

import asyncio
from typing import Any

from ._bootstrap import load_ssm_into_env

load_ssm_into_env()

# Imports below depend on env being populated.
from ..config import get_settings  # noqa: E402
from ..integrations.notion_client import NotionClient  # noqa: E402
from ..integrations.ntfy import Ntfy  # noqa: E402
from ..workers.nag_worker import NagWorker  # noqa: E402


async def _run_once() -> None:
    settings = get_settings()
    notion = NotionClient(settings)
    ntfy = Ntfy(settings)
    worker = NagWorker(settings=settings, notion=notion, ntfy=ntfy)
    try:
        await worker._tick_safely()
    finally:
        # Release the shared httpx clients so the runtime can exit cleanly.
        await ntfy.aclose()
        close = getattr(notion, "aclose", None)
        if close is not None:
            await close()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """EventBridge → one nag tick → return.

    Never raises: ``_tick_safely`` swallows internal errors and logs them.
    Any uncaught exception below would mark the Lambda invocation as failed,
    which EventBridge would retry — usually harmless but noisy.
    """
    try:
        asyncio.run(_run_once())
        return {"statusCode": 200, "body": "ok"}
    except Exception as e:  # belt-and-braces — never crash the schedule
        return {"statusCode": 500, "body": f"error: {e}"}
