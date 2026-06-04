# API reference

All endpoints live under the API Gateway base URL and require the `X-PA-Token` header for auth (except `/health` and `/api/push/vapid-public-key`).

**Base URL:** https://<your-api-gateway>.execute-api.<region>.amazonaws.com

Auto-generated OpenAPI / Swagger UI: `/docs` · ReDoc: `/redoc`.

---

## Capture

### `POST /capture`
Used by the iOS Shortcut + the PWA's Quick Capture FAB.

Request:
```json
{ "text": "remind me to call the dentist tomorrow afternoon" }
```

Response:
```json
{
  "status": "success",
  "captured": [
    { "type": "task", "title": "Call dentist", "url": "https://notion.so/..." }
  ],
  "summary": "Created normal task: Call dentist (due 2026-06-04)"
}
```

When the classifier tags `context=work`, `summary` includes the word "work":
> `"Created urgent work task: Email Alice (due 2026-06-04)"`

---

## PWA list endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/today` | Active rows due today or earlier, OR undated-urgent — Today's focus list |
| `GET /api/wins` | Rows marked Done at some point today |
| `GET /api/review` | Active rows tagged `review` (low-confidence captures) |
| `GET /api/quickwins` | Active rows tagged `quick-win` |
| `GET /api/tasks/all` | All Active Type=task rows (used by All / Browse → Work) |
| `GET /api/bills` | All Active Type=bill rows |
| `GET /api/projects` | Projects DB rows with subtask aggregation |
| `GET /api/wins/recent?days=N` | Rows Done in last N days (default 7) |
| `GET /api/parked` | Status=Parked rows, sorted oldest-first |
| `GET /api/needs-date` | Active rows with no due date AND not Someday priority |
| `GET /api/upcoming?days=N` | Active rows due in next N days, excluding today (default 7) |

All return `TaskList { items: TaskRow[], count: number }` with the full row projection including `context` field.

---

## Single-row reads + mutations

| Endpoint | What it does |
|---|---|
| `GET    /api/task/{id}` | Fetch a single TaskRow |
| `PATCH  /api/task/{id}` | Partial update — body is a `TaskPatch` (any of title/priority/due_date/first_step/notes/recurrence/auto_tags/amount/payee/context) |
| `DELETE /api/task/{id}` | Soft delete (Status=Cancelled) |
| `POST   /api/task/{id}/done` | Mark Done |
| `POST   /api/task/{id}/restore` | Done → Active (used by shake-to-undo) |
| `POST   /api/task/{id}/snooze?days=N` | Push due date forward by N days (default 1) |
| `POST   /api/task/{id}/confirm-review` | Strip the `review` auto-tag |
| `GET    /api/project/{id}` | Project header + full subtask list |

---

## Tile + nudge endpoints

| Endpoint | What it returns |
|---|---|
| `GET /api/dashboard` | `{ money_due_week, next_bill, streak_days, review_count, wins_today, urgent_count }` for the top-tiles strip |
| `GET /api/nudge` | `{ text }` — Claude's one-line take on today's state |

---

## Work mode

| Endpoint | What it does |
|---|---|
| `GET  /api/work-mode` | Returns `{ active, source: "schedule"\|"override", override, schedule: { days, start, end, tz }, quiet_hours }` |
| `POST /api/work-mode/override?action=...` | Apply one of `pause-today` / `start-now&hours=N` / `end-early` / `holiday&until=YYYY-MM-DD` / `clear` |

Driven by `src/work_mode.py`. State persisted to SSM Parameter Store at `/pa-agent/prod/work-override`.

---

## Web Push (Tier 3)

| Endpoint | What it does |
|---|---|
| `GET    /api/push/vapid-public-key` | Returns the VAPID public key (unauth — it's the public half) |
| `POST   /api/push/subscribe` | Body: `PushSubscription.toJSON() + { label? }`. Dedupes on endpoint. |
| `DELETE /api/push/subscribe?endpoint=...` | Drop a subscription |
| `POST   /api/push/test` | Broadcast a test push to every subscription — used by the PWA banner's auto-test on enable |

---

## Health
- `GET /health` — `{ status: "ok" }` for liveness probes.
