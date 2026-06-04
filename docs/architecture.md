# Architecture

This document captures the system's design at a deeper level than the README, including the decision log behind major architectural choices and the trade-offs each one carries.

> **For current implementation state** (modules, endpoints, what's deployed, recent commits, known bugs) read **`docs/PROJECT_STATUS.md`** instead. This file is the design / decisions doc.

---

## Module map (as-built, V1 live on AWS)

```
src/
├── _tz.py                          # PA_LOCAL_TZ → ZoneInfo singleton (Australia/Perth)
├── config.py                       # pydantic Settings, env-loaded
├── main.py                         # FastAPI app, /capture + 22 PWA API routes
├── orchestrator.py                 # voice text → classify → extract → Notion
├── streak.py                       # consecutive-Done-days computation + milestone picker
├── work_mode.py                    # schedule + override store + canned helpers
├── models.py                       # Pydantic — TaskRow, TaskPatch, Context, etc.
├── state_backend.py                # FileStore (dev) / S3Store (Lambda) for nag dedup
├── prompts/
│   ├── classifier.md               # Haiku — intent + confidence
│   └── extractor.md                # Sonnet — structured fields incl. context (work-signal rules)
├── integrations/
│   ├── anthropic_client.py         # classify() + extract() + nudge()
│   ├── notion_client.py            # read + write Tasks/Projects DBs, brain dump
│   ├── ntfy.py                     # fallback push channel
│   └── push.py                     # Web Push: subscription store + broadcast + VAPID send
├── workers/
│   ├── nag_worker.py               # 5-min tick: overdue scan → Web Push (ntfy fallback)
│   └── scheduled_pushes.py         # Mon 9am · Sun 6pm · monthly Parked · streak milestones
└── lambda_handlers/
    ├── _bootstrap.py               # SSM Parameter Store → os.environ at cold start
    ├── webhook.py                  # Mangum wrapper for FastAPI
    └── nag_tick.py                 # EventBridge handler

pwa-v2/src/
├── App.jsx                         # 3-tab routing + TokenGate + AppShell
├── sw.js                           # Custom service worker (injectManifest) — push + notificationclick
├── lib/
│   ├── api.js, push.js, workMode.js, useSwipeDone.js, useShakeUndo.js,
│   │   format.js, weather.js, dashboard.js, tap.js
├── components/
│   ├── TabBar.jsx, TaskRow.jsx, NudgeCard.jsx, NotificationsBanner.jsx,
│   │   WorkModePill.jsx, TopTiles.jsx, ReviewBell.jsx, Toast.jsx,
│   │   QuickCaptureFab.jsx, TokenGate.jsx
└── screens/
    ├── Today.jsx (+ FocusCard)     # tiles · greeting · nudge · stats · focus · quick wins · coming up
    ├── Browse.jsx                  # 4 cards → Work · Bills · Upcoming · Projects
    ├── Review.jsx                  # Needs-a-date · AI flagged · Parked strip
    ├── Parked.jsx                  # Status=Parked, revive/delete-forever
    ├── All.jsx                     # parameterised — Browse/Work passes context filter
    ├── Bills.jsx, Projects.jsx
    ├── TaskDetail.jsx              # view/edit + tap-to-flip context chip
    └── ProjectDetail.jsx

infra/sam/
├── template.yaml                   # 2 Lambdas + HttpApi + S3 + IAM
├── seed_parameters.ps1             # .env → SSM
└── deploy.ps1                      # local deploy alternative to GitHub Actions
```

---

## System overview

PA-Agent is a voice-first capture and orchestration system. Voice spoken on iPhone is transcribed by Siri, sent as text to a webhook, classified and structured by Claude, written to Notion, and confirmed back to the user via an iOS notification. A separate worker watches for overdue items and pushes persistent reminders. A PWA dashboard provides the daily interface for ticking off, reviewing flagged items, and seeing wins.

### High-level data flow

```
       USER VOICE
            │
            ▼
   ┌────────────────────┐
   │  Capture layer     │   iPhone Action Button → Siri → iOS Shortcut
   └────────┬───────────┘
            │  HTTPS POST { text, captured_at, shared_secret }
            ▼
   ┌────────────────────┐
   │  Transport         │   ngrok (dev) / AWS API Gateway (prod)
   └────────┬───────────┘
            │
            ▼
   ┌────────────────────┐
   │  Webhook handler   │   FastAPI route, validates shared secret
   └────────┬───────────┘
            │
            ▼
   ┌────────────────────┐
   │  Orchestrator      │   Coordinates classifier + extractor + integrations
   └────────┬───────────┘
            │
   ┌────────┴──────────────────────────────┐
   │                                       │
   ▼                                       ▼
┌────────────┐                     ┌────────────┐
│ Classifier │  Haiku, returns     │ Extractor  │  Sonnet, returns
│            │  { intent,          │            │  structured fields
│            │    confidence }     │            │  per intent + confidence
└────────────┘                     └────────────┘
            │                                       │
            └────────┬──────────────────────────────┘
                     ▼
            ┌────────────────────┐
            │ Routing decision   │  If confidence < 0.7, add `review` tag
            └────────┬───────────┘
                     │
                     ▼
            ┌────────────────────┐
            │ Notion client      │  Per-intent: create_task / create_bill /
            │                    │  create_project_with_subtasks /
            │                    │  append_to_brain_dump
            └────────┬───────────┘
                     │
                     ▼
            ┌────────────────────┐
            │ Response           │  Returns summary string to iOS
            └────────────────────┘

            ┌────────────────────┐
            │ Nag worker (5-min) │  Polls Notion for overdue + work-context-aware
            │ EventBridge → λ    │  Web Push primary (VAPID), ntfy fallback only when
            │                    │  Web Push delivered to 0 subs. Quiet hours 22-06
            │                    │  Perth. Work-mode-aware: skips work rows when off.
            │                    │  Also drives scheduled pushes: Mon 9am · Sun 6pm
            │                    │  · monthly Parked · streak milestones 7/14/30.
            └────────────────────┘
```

---

## Decision log

### Decision 1 — Notion as backend, not as interface

**Considered:** SQLite (self-hosted), Supabase (Postgres-as-a-service), Airtable, Google Sheets, Notion.

**Chosen:** Notion.

**Reasoning:** Notion provides free hosting, automatic backups, a working mobile app for emergencies, search, and an exportable data model. The user already used Notion for other things, so the marginal cost of storage was zero. Building on SQLite would have required replicating all of those features.

**Trade-off:** Notion's API rate limits and occasional schema constraints mean some features (e.g. complex relational queries) need to happen in application code. This was an acceptable cost.

**Reversibility:** High. The Notion client is isolated behind a single Python module. Migrating to Postgres or SQLite later would require replacing one file.

---

### Decision 2 — Two-model AI orchestration (Haiku + Sonnet)

**Considered:** Sonnet-only, Haiku-only, two-model split, fine-tuning a custom model.

**Chosen:** Two-model split. Haiku for intent classification, Sonnet for structured field extraction.

**Reasoning:** Haiku is roughly 10× cheaper than Sonnet per request. Intent classification is a low-difficulty task that Haiku handles reliably with the right prompt. Structured extraction is harder and benefits from Sonnet's better adherence to JSON schemas. Routing through both lets each model do what it's best at.

**Trade-off:** Two API calls per capture instead of one. Roughly 1.5× the latency of a single Sonnet call. Acceptable because voice capture latency is dominated by Siri transcription, not the AI step.

**Cost estimate:** At ~30-50 captures per day, total monthly Claude API cost stays under $10.

---

### Decision 3 — Voice keyword classifiers as a first pass

**Considered:** Pure AI classification, keyword-only classification, hybrid keyword + AI.

**Chosen:** Hybrid. Voice keywords (`remind me`, `project:`, `pay`, `$`, `every [day/week/month]`) guide the classifier prompt. The AI still makes the final call.

**Reasoning:** Pure AI classification is opaque and harder to debug. Pure keyword routing is brittle and breaks on natural speech variation. Hybrid lets the user develop a small reliable vocabulary while the AI handles everything else.

**Trade-off:** Users need to learn a small set of trigger words for best results. The fallback (no keyword → default to task) means the system still works without them, just less precisely.

---

### Decision 4 — Confidence-driven UX with `review` tag

**Considered:** Ask clarifying questions, refuse low-confidence captures, accept everything silently, accept-with-flag.

**Chosen:** Accept-with-flag. When confidence < 0.7, the entry is saved with a `review` auto-tag. The user can clean these up in the PWA later.

**Reasoning:** Interrupting a voice capture flow to ask a clarifying question defeats the purpose of voice capture. The system must capture first and tidy later. The `review` tag makes the capture honest — the user knows the AI wasn't sure — without breaking flow.

**Trade-off:** Users have to periodically clear the review queue. Acceptable; batched review is faster than per-capture confirmation.

---

### Decision 5 — Calendar deliberately excluded

**Considered:** Building calendar event creation into the agent's intents.

**Chosen:** Don't. If the user says *"Dentist Tuesday 2pm"*, they're told to use Siri directly. Siri + iOS Calendar already do this well.

**Reasoning:** Reinventing what Siri does natively offers no user value and adds significant complexity (OAuth, calendar conflict resolution, recurring event handling, time zones). The discipline of saying no to features that don't add value was a deliberate scope decision.

**Trade-off:** Users have a slightly fragmented capture flow — two trigger phrases ("Hey Siri" for calendar, Action Button for everything else). Acceptable.

---

### Decision 6 — Flat Notion schema

**Considered:** Multiple databases per intent type (one for tasks, one for bills, one for ideas, etc.) vs single Tasks database with a Type field.

**Chosen:** Single Tasks database. The Type field discriminates between tasks and bills. Subtasks via self-relation. Brain Dump is a separate page (not a database) for non-actionable content.

**Reasoning:** Adding new intent types (e.g. "expenses", "research") becomes a Type-field option, not a schema migration. Filtering and views can do anything multi-database setups can do. The simpler model means less code to maintain.

**Trade-off:** The Tasks database is wider (more properties) than it would be if split. This is invisible to the user because the PWA renders only relevant properties per Type.

---

### Decision 7 — Custom PWA over Notion's native mobile UI

**Considered:** Use Notion's mobile app as the daily interface, build a PWA, build a native iOS app.

**Chosen:** Custom PWA (React + Vite), installed to iPhone home screen.

**Reasoning:** Notion's mobile UX, while functional, is too generic for daily speed. Marking a task done in Notion requires multiple taps; the PWA does it with a swipe. Native iOS would be even better but requires Apple Developer enrolment and App Store review for every change. PWA hits the sweet spot of mobile-feel-without-app-store overhead.

**Trade-off:** PWAs on iOS have known limitations (service worker quirks, less reliable background behaviour). Mitigated by aggressive caching, optimistic UI updates, and possibly wrapping in Capacitor later.

---

### Decision 8 — ntfy.sh for push notifications

**Considered:** Apple Push Notification Service (APNs), Firebase Cloud Messaging, Pushover, Pushcut, ntfy.sh.

**Chosen:** ntfy.sh.

**Reasoning:** APNs requires an Apple Developer account and a native app. Pushover requires a paid app and is closed-source. ntfy.sh is free, open source, has an iOS app, and uses a simple HTTP POST API. For a single-user system, it's the cleanest option.

**Trade-off:** Notifications go through a third-party server. For high-trust scenarios this would matter; for personal task reminders it doesn't.

---

### Decision 9 — Three-layer ambition (reactive → autonomous → proactive)

Rather than building everything at once, the system is staged in three layers:

- **Layer 1 — Voice agent.** User-triggered. Voice in, action out. This is the foundation. ~6-8 weeks to ship.
- **Layer 2 — Background workers.** Autonomous agents that run on schedule. LinkedIn drafts, job application agent, bill scanner, email triage. Each is ~1-2 weeks.
- **Layer 3 — Proactive PA.** Pattern detection, daily check-ins, decision support, learning. Months of iterative development on top of Layer 1 + 2.

**Reasoning:** Each layer creates immediate user value. Skipping ahead to Layer 3 without Layer 1 stable is a recipe for shipping nothing. Living with each layer for 2-4 weeks before starting the next surfaces what's actually needed vs. what sounded good in planning.

---

### Decision 10 — Deploy target: AWS Lambda

**Considered:** Railway, Render, Fly.io, AWS Lambda, AWS EC2, run-on-PC.

**Chosen:** AWS Lambda (with API Gateway + EventBridge for scheduling).

**Reasoning:** Free tier covers expected usage (a few thousand invocations per month). Aligns with the user's ongoing AWS certification study. Real production exposure to a serverless architecture is more transferable to future roles than a managed-PaaS like Railway. Lambda's stateless model also enforces good architectural discipline.

**Trade-off:** Slightly steeper setup than Railway. Cold start latency on Lambda is ~500ms-1s, acceptable for this use case.

---

## Sequence diagram — happy path

```
User           iPhone          ngrok         FastAPI       Claude         Notion         ntfy.sh
 │                │                │              │            │              │              │
 │─speak─────────▶│                │              │            │              │              │
 │                │─dictate (Siri)│              │            │              │              │
 │                │─POST /capture─▶│              │            │              │              │
 │                │                │─tunnel──────▶│            │              │              │
 │                │                │              │─classify──▶│              │              │
 │                │                │              │◀────intent─│              │              │
 │                │                │              │─extract───▶│              │              │
 │                │                │              │◀────fields─│              │              │
 │                │                │              │─create page─────────────▶│              │
 │                │                │              │◀──────────────────success │              │
 │                │                │              │─return summary           │              │
 │                │◀───{summary}──│              │            │              │              │
 │◀─notification─│                │              │            │              │              │
 │                │                │              │            │              │              │
 │                │                │              │   (later, every 5 min)   │              │
 │                │                │              │ Nag worker queries───────▶│              │
 │                │                │              │ ◀──overdue tasks──────────│              │
 │                │                │              │ ─push (priority X)──────────────────────▶│
 │                │◀─notification─────────────────────────────────────────────────────────────│
```

---

## Failure modes and mitigation

| Failure | Where | Mitigation |
|---|---|---|
| Siri mis-transcribes | iPhone | User sees the iOS confirmation and can re-capture; original transcript stored in Notion `Notes` |
| Classifier returns wrong intent | Claude Haiku | `confidence` field; if low, auto-tag `review`; user fixes later in PWA |
| Extractor produces invalid JSON | Claude Sonnet | Pydantic validation; on failure, store as brain-dump with `review` tag |
| Notion API down or rate-limited | Notion | Retry with backoff; if all retries fail, return error to iOS, user notified |
| ngrok tunnel drops | Network | Will move to AWS API Gateway in production to remove this dependency |
| Nag worker crashes | Worker | Lambda auto-restart on next EventBridge tick; no state loss because Notion is source of truth |
| User loses iPhone | User | Data is still in Notion; install PWA on new phone, re-link Shortcut, resume |

---

## Performance characteristics

| Stage | Typical latency |
|---|---|
| Siri dictation | 1-2s |
| Webhook to classifier response | 200-400ms |
| Classifier (Haiku) | 300-600ms |
| Extractor (Sonnet) | 800-1500ms |
| Notion write | 200-400ms |
| Total user-perceived | ~3-5s |

Voice latency dominates the experience, not the AI step. Optimisation efforts focus elsewhere.

---

## Security

| Concern | Mitigation |
|---|---|
| Anyone hitting the webhook URL | Shared-secret token (`X-PA-Token` header) required on every request |
| API keys in code | All secrets via environment variables; `.env` gitignored; `.env.example` shows structure only |
| Logged secrets | Structlog filters known secret fields; webhook payloads not logged at INFO level |
| Notion data exposure | Notion integration is single-purpose, scoped to user's Life OS page only |
| Push notification interception | ntfy.sh topic uses random GUID; not enumerable |

---

## What's intentionally out of scope

- Multi-user / multi-tenant. Single-user system by design.
- Authentication / authorisation beyond shared secret. Single-user.
- Calendar event creation. Siri does it.
- Email composition. Layer 2.
- Web search / browser automation. Layer 2 (Cowork).
- Sync between devices beyond Notion's native sync. Notion is the source of truth.
- Offline-first PWA. Online-first with cached reads; writes require connection.

---

## Open questions / known limitations

- **iOS PWA refresh behaviour** is inconsistent. Returning to the PWA tab sometimes shows stale data or requires manual reload. Investigating service worker tuning.
- **Notion API rate limits** could become an issue if multiple workers (Layer 2) hit the same API simultaneously. May need to introduce a job queue.
- **Nag worker is currently polling-based.** Notion has webhooks in beta which would be more efficient; will revisit when stable.
- **No analytics on AI accuracy over time.** Should add a periodic eval suite to detect prompt regression as models update.
