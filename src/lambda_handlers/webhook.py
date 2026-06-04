"""API Gateway → FastAPI bridge.

Mangum adapts the ASGI ``FastAPI`` app to the Lambda Proxy event shape that
API Gateway delivers. From the FastAPI side nothing changes — the same
routes (``/capture``, ``/api/*``, etc.) handle the requests.

Lifespan events are disabled because the nag worker — which the FastAPI
lifespan starts in long-lived mode — runs as its own scheduled Lambda
(``nag_tick.py``) in this deployment.
"""

from __future__ import annotations

# SSM → env vars MUST run before any module that reads config.
from ._bootstrap import load_ssm_into_env

load_ssm_into_env()

# Now safe to import the app — its config reads from os.environ.
from mangum import Mangum  # noqa: E402

from ..main import app  # noqa: E402

handler = Mangum(app, lifespan="off")
