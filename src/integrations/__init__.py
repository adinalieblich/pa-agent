"""External-API clients. Each module owns one third-party surface:

- ``anthropic_client``: Claude Haiku (classification) + Sonnet (field extraction).
- ``notion_client``: writes to the unified Tasks DB (tasks + bills) and
  appends to the Brain Dump page.

v3 note: calendar integration was deliberately removed — Siri handles scheduled
items on the user's phone. The agent no longer routes calendar intents.
"""
