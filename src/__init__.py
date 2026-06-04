"""PA-Agent: voice-first personal assistant pipeline.

Top-level package. Submodules:
- ``config``: typed environment loading.
- ``models``: shared Pydantic models for intents, extracted fields, responses.
- ``orchestrator``: the brain — classify, extract, route to integrations.
- ``integrations``: thin async wrappers around Anthropic, Notion, Google Calendar.
- ``utils``: structured logging and helpers.
- ``main``: FastAPI entry point that exposes the webhook.
"""

__version__ = "0.1.0"
