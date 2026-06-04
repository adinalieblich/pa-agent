"""AWS Lambda entry points.

Two handlers — both share the same deployment package:

- :mod:`webhook` — the FastAPI app fronted by API Gateway. iOS Shortcut posts here.
- :mod:`nag_tick` — single invocation of the nag worker's poll loop, called by
  EventBridge every 5 minutes.

Both run :func:`_bootstrap.load_ssm_into_env` at cold start so the existing
:mod:`src.config` machinery (which reads from ``os.environ``) keeps working
unchanged.
"""
