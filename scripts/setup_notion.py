"""List every Notion database the PA-Agent integration can see.

Run after sharing your "Life OS" page with the integration to discover the
real database IDs and paste them into ``.env``.

Usage:
    python scripts/setup_notion.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.integrations.notion_client import NotionClient  # noqa: E402


async def _main() -> int:
    settings = get_settings()
    client = NotionClient(settings)

    # Notion 2025-09-03 API: search filter uses "data_source", not "database".
    res = await client._client.search(filter={"property": "object", "value": "data_source"})
    items = res.get("results", [])

    print(f"{len(items)} data source(s) visible to the PA-Agent integration:")
    for ds in items:
        title_parts = ds.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts) or "(untitled)"
        parent = ds.get("parent", {})
        parent_db = parent.get("database_id", "?") if parent.get("type") == "database_id" else "?"
        print(f"  - data_source_id={ds['id']}")
        print(f"      title : {title!r}")
        print(f"      parent_database_id : {parent_db}")

    if not items:
        print()
        print("None visible. Share your Life-OS page (or each DB) with the")
        print("integration via the page's ⋯ menu → Connections → PA-Agent.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
