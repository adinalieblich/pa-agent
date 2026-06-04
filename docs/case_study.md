# PA-Agent — Case Study

How I designed and built a personal AI assistant from scratch over two months, transitioning from product work into AI/tech engineering.

---

## Why I built it

I needed a way to capture every thought, task, and bill the moment it crossed my mind — without opening an app. Off-the-shelf task managers (TickTick, Todoist, Notion's native UI) all require the same friction: stop what you're doing, switch contexts, open the app, type. The friction of capture was the reason captures didn't happen.

I also wanted to deeply understand what it takes to build a real, useful, multi-component AI system end-to-end — not just prompt engineering, but data architecture, integration design, deployment, observability, and the harder UX problems around uncertainty and feedback loops.

PA-Agent does both. It's a tool I use daily, and it's the centrepiece of my portfolio while I transition into AI engineering roles.

---

## The constraint that shaped everything

**Capture has to be reflexive.** If you have to think about how to capture something, you won't. The system needs to be:

- Triggerable in under one second (one button press)
- Operable without looking at the phone (voice-first)
- Usable while walking, driving, mid-conversation, half-distracted
- Confident enough to not ask follow-up questions during capture

Every design decision had to bend to this constraint. Anything that broke the reflex was rejected, even if it improved accuracy.

---

## Architectural choices and trade-offs

### Notion as backend, not interface

The first instinct was to build everything in Notion. The problem: Notion's mobile UX is too slow for daily use. Marking a task done takes 4-5 taps. Reading a task title takes a scroll. Notion is wonderful as a database, awful as a daily driver.

Solution: keep Notion as the source of truth — exportable, owned, queryable — but build a custom PWA dashboard on top. The PWA reads/writes the same data via the Notion API, but presents it the way you actually use it (today's focus → quick wins → wins counter).

This split — database as one layer, interface as another — is something I'd seen done at scale (Slack, Linear, every modern SaaS) but never built myself.

### Two-model orchestration

I started with everything in Sonnet. It worked but cost ~$15/month at moderate usage. Splitting into Haiku-for-classification + Sonnet-for-extraction cut that to about $3/month with no quality drop. The classifier task is genuinely easier than the extractor task; matching model to task efficiency is just engineering discipline.

This taught me that "use one big model" is the lazy answer. Real systems route work to the cheapest model that can do it.

### Voice keyword classifiers

Pure AI classification is brittle and opaque. Pure keyword routing is rigid and breaks on natural speech. Hybrid is better: a small reliable vocabulary (`remind me`, `project:`, `pay`, `$`) guides the classifier, but the AI still has the final say.

The hardest part wasn't building this — it was *deciding* on it. The instinct of an AI engineer is to make everything more AI. Sometimes a regex catches it first and that's fine.

### Confidence-driven UX

Early on, I had the agent ask clarifying questions when it wasn't sure. "Did you mean to create a task or set a calendar event?" sounds reasonable. In practice it destroyed the capture reflex. Three captures in a row with follow-up questions and I'd stop using it.

The fix: the agent never asks during capture. If confidence drops below 0.7, the entry is still saved — just auto-tagged `review`. The user can batch-clean these later. This was the single biggest UX insight of the project.

### Calendar deliberately excluded

Early scope included calendar event creation. After two iterations of the spec, I cut it. Siri + iOS Calendar do this well already. Adding it to the agent meant duplicating that capability with worse UX (you'd have to remember to use my agent instead of just saying "Hey Siri").

Knowing when to *not* build something is harder than building it. This is a discipline I see often called "scope hygiene" — it shows up in mature engineering work and rarely in junior portfolios.

---

## The build journey

### Week 1 — Notion setup + voice → text → webhook

Got the basic plumbing working: iPhone Action Button triggers a Siri Shortcut that POSTs the transcribed text to an ngrok tunnel into a FastAPI handler running on my local machine. No AI yet, just text relay.

The "this is going to work" moment came when I spoke into my phone and saw the literal text appear in my Notion database with a 3-second round-trip.

### Week 2 — Adding Claude

Wired Sonnet in, then realised the cost would be uncomfortable at daily usage. Split into Haiku for classification, Sonnet for extraction. Wrote the prompts. Built a 10-example test suite for classifier accuracy. Hit 10/10.

This was where the project felt like AI engineering vs. plumbing. The prompts went through ~15 versions before I was happy. The classifier prompt looks simple now, but the structure (return JSON, include confidence, give worked examples per intent) took real work to find.

### Week 3 — Schema redesign

Original Notion structure had 8 databases (Tasks, Bills, Contacts, Journal, Ideas, Projects, Jobs, Health). Living with it for a week made clear this was over-engineered. Consolidated to one Tasks DB (Type field discriminates), one Projects DB, one Job Applications DB, plus a Brain Dump page.

The lesson: the right abstractions emerge from use, not from design sessions. I would have stayed with 8 databases if I hadn't been using the system.

### Week 4 — PWA design + build start

Mocked up 9 screens in HTML first (Today, All, Bills, Projects, Wins, Task Detail, Project Detail, Review Queue, Empty State). Picked a deliberate aesthetic — jewel tones on cream — to make the daily interface something I actually wanted to open.

Then started building in React + Vite. Built Today first, reviewed, then continued screen-by-screen. This was deliberate; building all nine before reviewing would have meant rework on every one.

### Week 5+ — Nag worker, AWS deploy, Layer 2 planning

Built the nag worker (polls Notion every 5 minutes for overdue items, pushes via ntfy.sh until ticked off, honours snooze). Started planning AWS Lambda deployment.

This is also when Layer 2 planning got serious: which background workers to build next (LinkedIn drafts first, then job application agent, then bill scanner), what order, what data structures they'd need.

---

## What broke and how I fixed it

### Mistake 1 — Creating a new database when I could edit the existing one

When I needed to add Type/Amount/Recurrence fields, I created a brand new database instead of editing the existing Tasks DB. Wasted ~30 minutes plus had to delete the redundant DB.

**Lesson:** Always check what the tool can actually do before working around it. Notion's API supports schema edits via SQL DDL; I just hadn't checked.

### Mistake 2 — Hardcoded data in dashboard

First version of the Today dashboard had hardcoded "3 done today" and a static date. Looked good in screenshots, useless in reality. Had to rebuild using linked database views with live filters.

**Lesson:** Mockups and built systems are different things. Anything dynamic needs to be wired to data from the start.

### Mistake 3 — Over-engineering confirmation

Initial design had a multi-step confirmation flow for ambiguous captures. The user would speak, the agent would ask back, the user would clarify. Tried it for two days, hated it. Replaced with the `review` tag pattern. The user's actual idea was simpler and better than mine.

**Lesson:** When the user offers a solution, take it seriously before pitching alternatives.

### Mistake 4 — Claiming work done without verifying

I once said "the dashboard is live and rendering correctly" before actually fetching the rendered output. It wasn't rendering correctly. Database view embed syntax had silently failed.

**Lesson:** "Done" requires verification. State "verified" or "couldn't verify" honestly.

I keep a running `ERRORS_AND_LESSONS.md` doc in the project root with all of these. Catalogue your failures and the same one stops repeating.

---

## What I learned about AI engineering

A few things I didn't expect:

**Prompt engineering is software engineering.** Versioning, testing, edge cases. The classifier prompt has 15 versions. Each one was a debugging session. The mature attitude isn't "what's the best prompt" — it's "what's the smallest reproducible test suite that proves this prompt works."

**Models change underneath you.** The Sonnet I started with is not the Sonnet that exists today. The classifier accuracy of 10/10 was on the version six months ago. Real systems need eval suites that run continuously, or you don't notice when accuracy drifts.

**The boring stuff is the hard stuff.** Webhook security. Structured logging. Error handling. Type-safe data models. The AI piece is shiny but takes maybe 20% of total build time. The other 80% is infrastructure, observability, and making sure the system survives real use.

**User research happens through use.** I am the user. Daily use revealed problems no design session would have caught. The friction of opening Notion to mark something done. The annoyance of clarifying questions interrupting flow. The need for a "wins this week" counter for dopamine. None of these were in my original spec.

---

## What's next

The system is approaching the end of Layer 1 (voice agent + PWA + nag worker + AWS deploy). Layer 2 (background workers) starts next:

- **LinkedIn drafts worker** — daily content draft generation from build progress and trend monitoring. ~1 week.
- **Job application agent** — daily scrape of LinkedIn / Seek / Indeed, AI-scored matches, tailored CV and cover letter drafting, approval queue. ~2 weeks.
- **Bill scanner** — Gmail integration to auto-extract bills. ~3-5 days.
- **Email triage** — inbox classification + draft replies. ~1 week.

Beyond that, Layer 3 is the proactive PA — pattern detection, daily check-ins, decision support, learning. That's a 3-6 month effort iteratively.

---

## What this proves about me as an engineer

I can:

- Take a fuzzy personal problem and design a system end-to-end
- Make architectural decisions and document the trade-offs
- Cut scope deliberately (Calendar wasn't built; it shouldn't have been)
- Build, ship, and live with the system long enough to learn what's actually broken
- Recover from mistakes by recording them rather than hiding them
- Choose tools by purpose, not by familiarity (Notion, Claude, ntfy.sh — none of these were tools I knew before this project)
- Stay honest about scope: this is a personal system used daily, not a polished commercial product

The system isn't done. Building it is the point.
