# PA-Agent — voice-first personal AI assistant

A voice-first capture system that turns spoken thoughts into structured action — classified by Claude, organised in Notion, and surfaced via a custom PWA with Web Push notifications.

Built end-to-end as a portfolio piece exploring AI orchestration, multi-channel push delivery, and ADHD-friendly UX. Deployed to AWS Lambda; fully serverless.

---

## What it does

You hold a button, speak — *"remind me to pay rent next Friday"* or *"PO 4521 for the ACME visit, due tomorrow"* — and within ~5 seconds the system has:

1. Transcribed your speech (iOS dictation)
2. Classified intent — task, bill, project, brain-dump, or a multi-intent breath (Claude Haiku)
3. Extracted structured fields — title, due date, priority, recurrence, project link, work-vs-personal context, "smallest first step" (Claude Sonnet)
4. Routed and written to the appropriate Notion table
5. Confirmed back to you with a one-line summary toast

A separate worker watches for overdue items and pings you via **Web Push** notifications with action buttons — `Done` and `+1 day` resolve straight from the lock screen. Scheduled triggers add a Monday morning work-roundup, a Sunday evening review nudge, monthly resurfacing of long-parked items, and milestone celebrations at 7/14/30-day streaks.

A custom PWA gives you a daily dashboard, manual capture, task editing, and a "commitment funnel" Review tab for triaging anything the AI flagged as low-confidence.

---

## Why it's interesting (architecturally)

A few things I'd flag if you're reading the code:

### 1. Two-model classification → extraction pipeline

The classifier runs Claude Haiku — cheap, fast, intent-only. The extractor runs Claude Sonnet — slower but structurally robust. Confidence below a threshold (0.7) auto-tags the row for human review, so the system is honest about its uncertainty. The split keeps p95 latency at ~5s while preserving extraction quality.

See `src/orchestrator.py` and `src/prompts/{classifier,extractor}.md`.

### 2. Work-mode as a first-class scheduling primitive

Work tasks are visually and audibly hidden outside Mon–Fri 9–5 local time. Override actions (`pause-today`, `start-now`, `end-early`, `holiday-until`) are persisted server-side in AWS SSM Parameter Store with TTLs, so a quick swipe on the phone changes behaviour for all devices and survives Lambda cold-starts.

Quiet hours (22:00–06:00) silence ALL pings — work or personal. Implemented in `src/work_mode.py`; tests in `tests/test_work_mode.py`.

### 3. Web Push primary, ntfy.sh fallback

Web Push (VAPID-signed) is the primary notification channel — action buttons, custom click URLs, app-like styling on iOS 16.4+. ntfy.sh is the fallback for devices that haven't completed the Web Push enrolment (one tap in the PWA). The nag worker only fires ntfy when Web Push delivered to 0 subscriptions, avoiding double-notifications.

See `src/integrations/push.py`, `src/workers/nag_worker.py`, and `pwa-v2/src/sw.js` (custom service worker with `push` + `notificationclick` handlers).

### 4. The "commitment funnel" Review tab

Most task apps surface uncertainty as a dumping ground. Review here is structured as a funnel:

- **📌 Needs a date** — active rows the user implicitly committed to but never time-boxed. Inline date chips (today / tomorrow / Sat / next wk / picker) commit a date with one tap.
- **✦ AI flagged** — low-confidence captures, with save / edit / delete actions.
- **📦 Parked** — collapsible at the bottom; opens a dedicated sub-screen with revive-with-date and delete-forever flows. Items older than 12 months get a "long parked" badge.

### 5. Configurable timezone via single source of truth

A small `src/_tz.py` reads `PA_LOCAL_TZ` from the environment (with a sane default) and exports a single `LOCAL_TZ` constant used by every other module. Rotating the user to a different city is a one-line SSM parameter update plus a redeploy — no code changes.

---

## Tech stack

**Backend** — Python 3.11 · FastAPI · Pydantic · Anthropic SDK · official `notion-client` · `pywebpush` · `boto3` · `structlog`

**PWA** — React 19 · Vite 5 · `vite-plugin-pwa` (injectManifest mode) · Workbox · React Router · custom Service Worker

**Infrastructure** — AWS Lambda (Python 3.11, arm64) · API Gateway HTTP API · EventBridge (5-min scheduled rule) · S3 (state) · SSM Parameter Store (secrets + config) · SAM template · GitHub Actions CI/CD

**Test surface** — 79 pytest tests covering work-mode schedule + override TTL, streak computation, milestone picker, scheduled-push time-of-day predicates, push subscription dedup, context field wiring, prompt content sanity.

---

## Repo layout

```
src/
├── _tz.py                    # configurable LOCAL_TZ singleton
├── main.py                   # FastAPI app + 25 routes
├── orchestrator.py           # classify → extract → Notion
├── work_mode.py              # schedule + override state machine
├── streak.py                 # consecutive-Done-days + milestone picker
├── models.py                 # Pydantic — TaskRow, TaskPatch, Context, …
├── state_backend.py          # FileStore (dev) / S3Store (Lambda)
├── prompts/                  # Markdown system prompts
├── integrations/
│   ├── anthropic_client.py
│   ├── notion_client.py
│   ├── ntfy.py               # fallback push channel
│   └── push.py               # Web Push — VAPID, subscription store, broadcast
├── workers/
│   ├── nag_worker.py         # 5-min overdue scan
│   └── scheduled_pushes.py   # Mon · Sun · monthly Parked · streak
└── lambda_handlers/          # Mangum + EventBridge wrappers + SSM bootstrap

pwa-v2/src/
├── App.jsx                   # 3-tab routing
├── sw.js                     # custom service worker (push + notificationclick)
├── components/, screens/, lib/, styles/

infra/sam/
├── template.yaml             # 2 Lambdas + HttpApi + S3 + IAM
├── seed_parameters.ps1       # .env → SSM
└── deploy.ps1                # local deploy alternative
```

---

## Running it

See `docs/setup.md` for the full setup walkthrough (Anthropic key, Notion integration, schema, env file, run the dev server, optional ngrok tunnel).

The 30-second version:

```bash
git clone <this-repo>
cd voice-assistant
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # then fill in your Anthropic + Notion keys
uvicorn src.main:app --reload
# in another terminal:
cd pwa-v2 && npm install && npm run dev
```

Deploy to AWS via `infra/sam/deploy.ps1` (or via the GitHub Actions workflow in `.github/workflows/deploy.yml` — add `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` as repo secrets).

---

## Further reading

- **`docs/architecture.md`** — system overview, module map, decision log
- **`docs/api.md`** — full endpoint reference
- **`docs/case_study.md`** — narrative writeup of design decisions and trade-offs
- **`docs/setup.md`** — step-by-step local setup

---

## License

MIT — see `LICENSE`.
