# Setup

Step-by-step guide to running PA-Agent locally.

> **Note:** This is a single-user personal system. Setup assumes you're the one running it. Not designed for multi-tenant deployment.

---

## Prerequisites

- Python 3.11 or higher
- Node.js 18+ (only if running the PWA)
- A free [Anthropic](https://console.anthropic.com) account (API key)
- A free [Notion](https://notion.so) account
- An iPhone (for voice capture via Action Button) — optional but recommended
- An [ngrok](https://ngrok.com) account (free tier sufficient) — for development tunnel

---

## 1. Clone and configure

```bash
git clone https://github.com/yourname/voice-assistant.git
cd pa-agent
cp .env.example .env
```

Edit `.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...
NOTION_API_KEY=secret_...
NOTION_TASKS_DS_ID=...
NOTION_PROJECTS_DS_ID=...
NOTION_JOBS_DS_ID=...
NOTION_BRAIN_DUMP_PAGE_ID=...
WEBHOOK_SHARED_SECRET=                # generated on first run
LOG_LEVEL=INFO

# Web Push (Tier 3 notifications) — generate via `python scripts/gen_vapid_keys.py`
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:you@example.com

# Wall-clock timezone for work-mode + scheduled pushes + extractor "today"
# Any valid IANA TZ id. Defaults to Australia/Perth if unset.
PA_LOCAL_TZ=Australia/Perth
```

To get your Notion data source IDs, run the setup script after creating a Notion integration:

```bash
python scripts/setup_notion.py
```

It lists every data source the integration can see, with IDs you can paste into `.env`.

---

## 2. Install dependencies

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate

# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 3. Set up the Notion workspace

You need a Notion workspace with the right structure. The schema in short:

- **Tasks DB** — properties: Task (title), Status, Priority, Due, First step, Notes, Project (relation), Type, Recurrence, Recurrence ends, Amount, Payee, Account ref, Parent task (self-relation), Depends on (self-relation), Auto tags, Captured, Done at, **Context** (Select: `personal` default + `work`).
- **Projects DB** — properties: Project (title), Status, Priority, Next action, Notes, Tasks (relation, auto from Tasks DB).
- **Job applications DB** — properties: Company, Role, Status, Date applied, CV version, Cover letter, Source, URL, Next follow-up, Notes.
- **Brain Dump page** — just a page, no special schema. The agent appends bulleted entries.

Then create a [Notion integration](https://www.notion.so/my-integrations) and grant it access to your workspace.

---

## 4. Run the backend

```bash
python -m src.main
```

The server starts on `http://localhost:8000`. Visit `/docs` to see the auto-generated FastAPI documentation.

---

## 5. Start the ngrok tunnel

In a separate terminal:

```bash
ngrok http 8000
```

Copy the public `https://...ngrok-free.app` URL. This is what your iPhone will POST to.

---

## 6. Set up the iOS Shortcut

Walkthrough:

1. On iPhone, open the Shortcuts app
2. Create a new shortcut
3. Add action: Dictate Text
4. Add action: Get Contents of URL
   - URL: your ngrok URL + `/capture`
   - Method: POST
   - Headers: `X-PA-Token: [your shared secret]`, `Content-Type: application/json`
   - Body: `{ "text": [Dictated Text] }`
5. Add action: Show Notification (uses the `summary` field from the response)
6. Assign the shortcut to your Action Button (Settings → Action Button → Shortcut → select)

---

## 7. Test it

Press your Action Button. Say *"Remind me to test the agent tomorrow."* Wait ~3 seconds. Check your Notion Tasks database. The entry should appear.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 401 Unauthorized | Shared secret mismatch | Re-check `X-PA-Token` in iOS Shortcut matches `.env` |
| 500 Internal Server Error | Missing env var | Check the server logs; usually a missing or malformed `.env` value |
| Task created but missing fields | Extractor confidence low | Check `auto_tags` field in Notion — should have `review` flag |
| ngrok URL keeps changing | Free tier behaviour | Acceptable in dev; production should use AWS API Gateway |
| Siri transcribes wrong | Background noise / accent | Re-capture; original transcript stored in `Notes` field |

---

## Running the PWA (optional)

```bash
cd pwa
npm install
npm run dev
```

Visit `http://localhost:5173` in mobile Safari, tap Share → Add to Home Screen. The PWA installs to your home screen.

---

## Running the nag worker

In a third terminal:

```bash
python -m src.workers.nag_worker
```

The worker polls Notion every 5 minutes and pushes notifications via ntfy.sh for overdue or urgent items. Polling cadence, escalation rules, and snooze handling are implemented in [`src/workers/nag_worker.py`](../src/workers/nag_worker.py).

---

## Deployment to AWS Lambda (planned)

Short version: the FastAPI app is wrapped with `Mangum` and deployed to Lambda. API Gateway routes the public URL. EventBridge fires the nag worker on a 5-minute schedule. CloudWatch captures logs.

This replaces ngrok and removes the dependency on a local machine running.
