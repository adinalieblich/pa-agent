"""One-off: dump the Projects DB schema + a few sample rows."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.integrations.notion_client import NotionClient  # noqa: E402


async def main() -> None:
    s = get_settings()
    c = NotionClient(s)
    ds = await c._client.data_sources.retrieve(data_source_id=s.notion_projects_ds_id)
    print("PROJECTS DB properties:")
    for name, info in ds.get("properties", {}).items():
        t = info.get("type")
        extra = ""
        if t == "select":
            opts = [o["name"] for o in info.get("select", {}).get("options", [])]
            extra = f" opts={opts}"
        if t == "relation":
            db = info.get("relation", {}).get("database_id", "?")
            extra = f" rel_db={db}"
        print(f"  {name!r:25} type={t}{extra}")
    print()
    res = await c._client.data_sources.query(
        data_source_id=s.notion_projects_ds_id, page_size=10
    )
    rows = res.get("results", [])
    print(f"sample rows ({len(rows)}):")
    for row in rows[:10]:
        title_prop = next(
            (p for p in row["properties"].values() if p.get("type") == "title"),
            None,
        )
        title = (
            "".join(t.get("plain_text", "") for t in title_prop.get("title", []))
            if title_prop
            else "?"
        )
        status = (row["properties"].get("Status") or {}).get("select") or {}
        print(f"  - {row['id']}  {title!r}  status={status.get('name')}")


if __name__ == "__main__":
    asyncio.run(main())
