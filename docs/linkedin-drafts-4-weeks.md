# LinkedIn drafts · 4 weeks · 10 posts

Pre-written. Copy-paste. Edit to taste. Each post obeys the playbook (hook < 140 chars, length 600–2000, link in first comment, 3–5 niche hashtags).

Times in **AWST (Perth)**. The first-comment URL goes in a separate reply you post immediately after the main post.

---

## 🟣 WEEK 1 · Launch week

### Mon · 8am · Template D — Architecture carousel
**First-comment URL**: `demo.adinalieblich.com`
**Asset**: existing animated arch SVG → 8-slide carousel
**Hashtags**: `#FastAPI #AWSLambda #Claude #BuildInPublic #AEC`

```
Tomorrow I launch Lilach. Today, the architecture.

Voice-first personal AI on AWS Lambda + Claude + Notion. Built solo in 8 weeks. In daily use since week 3. ~$5/month.

Five components total. No orchestration layer. The decision I keep getting asked about: why no Step Functions, no EventBridge, no queue?

Because the trade-off study fits on one slide. (It's slide 7 of the carousel.)

The whole architecture is below. The live demo (sample data, no signup) goes up tomorrow morning.

What would you change?

#FastAPI #AWSLambda #Claude #BuildInPublic #AEC
```

---

### Wed · 8am · Template A — Build log
**First-comment URL**: `github.com/adinalieblich/pa-agent`
**Asset**: 1 screenshot of Today screen
**Hashtags**: `#BuildInPublic #PWA #Claude #AEC`

```
Lilach went live Monday. Two days in, here are the three things I'd rebuild already.

1. The first-time experience.
The token gate is the first thing a friend sees when I send the link. It's also the most opaque. Three friends have asked me what the secret is. Nobody should have to ask. The fix is obvious — a public demo subdomain with sample data. Building it tonight.

2. The "done" gesture.
Tap-the-check-circle works. Swipe-the-row-right works. Both shipped. Both feel "fine." Neither feels great. The version that feels great is: tap anywhere on the row + a one-second undo banner at the top. Familiar from Gmail. Cheap to build. Already on the queue.

3. The recurring-task UX.
"Drink water daily" recurs correctly under the hood — leap years, month lengths, overdue floor, all tested. But the user can't TELL it's recurring from the row. There's no chip, no icon, no signal. Trust gap.

Real-talk: shipping a thing into your own life surfaces problems that 40 unit tests can't.

What's the thing YOU shipped where day-2 friction told you the most?

#BuildInPublic #PWA #Claude #AEC
```

---

### Fri · 7pm · Template B — One prompt
**First-comment URL**: `github.com/adinalieblich/engineering-team-minutes-system/raw/main/docs/What-AI-Wont-Tell-You.pdf`
**Asset**: before/after screenshot pair
**Hashtags**: `#VBA #Claude #ExcelTips #AEC`

```
This prompt changed how I work in Excel:

"Rewrite this VBA sub as a single Range.Find loop. Preserve every Data Validation rule by name. Output only the new Sub, no commentary."

What that gives me: 90 minutes of refactoring → 8 seconds. No hallucinated dropdowns. No "I'll explain my approach first" preamble. Zero loss of validation rules.

Why it works: the constraint ("no commentary") removes the AI's most wasteful pattern. The shape spec ("single Range.Find loop") gives it a target to match instead of an open invitation. Naming what to preserve prevents the model from deciding what's expendable.

I now use 9 variants of this. They're all in the field guide (40 pages, free PDF — link in comments).

What's a prompt YOU now reuse without thinking about it?

#VBA #Claude #ExcelTips #AEC
```

---

## 🟠 WEEK 2 · Depth

### Tue · 8am · Template C — Five corrections (CAROUSEL)
**First-comment URL**: `github.com/adinalieblich/prompt-engineering`
**Asset**: 8-slide carousel (use `/pwa-v2/carousel-template.html` then Save as PDF)
**Hashtags**: `#PromptEngineering #VBA #Claude #BuildInPublic`

```
Claude got this VBA refactor wrong five times in a row.

Here's what I corrected — and why each fix made the next one harder. Then I turned the corrections into a one-page skill the AI loads automatically next session.

Swipe through the carousel:
01 Cover
02 Correction 01 — no preamble
03 Correction 02 — name the shape
04 Correction 03 — preserve by name
05 Correction 04 — quote the escape
06 Correction 05 — verify by re-reading
07 The skill (5 rules, one file)
08 The repo

If you're driving AI to write corporate-grade VBA or anything where a wrong word breaks the audit — the skill file is in comments. MIT, free, one page.

What's the correction you keep having to give your AI?

#PromptEngineering #VBA #Claude #BuildInPublic
```

---

### Thu · 7pm · Template E — Confession
**First-comment URL**: `demo.adinalieblich.com`
**Asset**: 1 photo of desk / DA stack / site notebook
**Hashtags**: `#AEC #LocalGov #AI #CivilEngineering`

```
I told my council AI couldn't handle compliance documents.

Six weeks later I'm walking that back. Here's why.

Original belief: regulatory language is too precise for an LLM. One wrong synonym and the audit fails. I'd already seen this happen twice in trial.

The thing that broke the belief: I asked Claude to extract obligations as a checklist with the source-document line number for each. It got 47 of 47 right on a 92-page DA. Source-traceable. Verifiable. Faster than the human pass — but more importantly, checkable.

New rule: the question isn't "can AI handle X?" It's "can I make the output checkable?"

That's it. That's the whole shift. Output you can verify line-by-line against a source document is fundamentally different from output you have to trust. And it turns out a lot of AEC work is the first kind, not the second.

What did YOU get wrong about AI at work recently?

#AEC #LocalGov #AI #CivilEngineering
```

---

## 🟢 WEEK 3 · Build cred

### Wed · 8am · Template D — Architecture carousel
**First-comment URL**: `github.com/adinalieblich/engineering-team-minutes-system`
**Asset**: NEW diagram (~2 hrs to build, in same style as Lilach arch)
**Hashtags**: `#VBA #Excel #SharePoint #AEC #LocalGov`

```
Architecture of the week: the Excel + VBA meeting-minutes system.

This is the one I built solo for a local government engineering team. Locked-down SharePoint environment, no plugins, no admin rights, no external tools. Built inside the constraints, not around them.

Five sheets. One column architecture decision that killed an entire class of bugs (Action Register is a filter view, not a separate sheet). 257 form-control checkboxes replaced with a single dropdown column. Conditional formatting that survives row insertion (the failure mode that wasted three weeks).

The interesting bit: the system is the artifact, but the field guide of what AI gets wrong building it is the deliverable. 23 confirmed errors, 10 strategies, 9 VBA patterns. 40-page PDF.

Repo + the field guide PDF — link in comments. v1.0 kit released.

If you've built anything serious in Excel + VBA, what's the architectural decision you wish you'd made earlier?

#VBA #Excel #SharePoint #AEC #LocalGov
```

---

### Fri · 8am · Template A — Build log
**First-comment URL**: `github.com/adinalieblich/pa-agent`
**Asset**: terminal GIF (~5 min screen recording)
**Hashtags**: `#AWSLambda #Notion #Webhooks #BuildInPublic`

```
Shipped a Notion → Lambda webhook in 90 minutes this morning.

Use case: any new task created in a Notion database fires a Lambda which classifies the task (Claude), assigns a priority bucket, and writes it back. Took the friction out of the "what should I work on next" question for me by 100%.

The thing that surprised me: Notion's webhook config doesn't include the page properties in the payload. You have to fetch them in a second call. Costs you a Notion API rate-limit slot per task. The default rate limit is 3 req/sec, which sounds like a lot until you're processing a backlog.

Fix: a 200ms in-memory queue in the Lambda handler. Drained sequentially. ~30 lines of code. Now handles ~150 tasks per minute steady-state.

Total cost: $0.04 in API calls + $0 in Lambda (under the always-free tier).

Worth ninety minutes? Absolutely. I'd been hand-classifying tasks for three weeks.

What did YOU automate this week that you should have automated months ago?

#AWSLambda #Notion #Webhooks #BuildInPublic
```

---

## 🟣 WEEK 4 · Reach

### Tue · 8am · Template B — One prompt
**First-comment URL**: `github.com/adinalieblich/engineering-team-minutes-system/raw/main/docs/What-AI-Wont-Tell-You.pdf`
**Asset**: screenshot pair (before = long doc, after = checklist)
**Hashtags**: `#PromptEngineering #AEC #Claude`

```
The prompt that saved 4 hours yesterday:

"Rewrite this as a checklist. One row per requirement. Three columns: source line number, the obligation in plain English, the evidence I need to satisfy it. Don't paraphrase the obligation — quote it."

I gave it a 47-page compliance document. Got back a 134-row checklist. Every row source-traceable to the original. No interpretation, no judgment calls embedded — just structure.

Why it works:
- "One row per requirement" — forces atomicity
- "Three columns" — names the shape exactly
- "Don't paraphrase, quote" — removes the AI's worst failure mode (paraphrase-drift)
- "Source line number" — makes the output checkable

I've now used this prompt on five different document types. It works on compliance docs, RFP responses, lease agreements, even technical specs. The structure forces the model into stenography mode, which is what you want.

Four more prompts like it in the field guide — link in comments.

What's your favourite "make AI do structure, not opinion" prompt?

#PromptEngineering #AEC #Claude
```

---

### Thu · 7pm · Template C — Five corrections from readers (CAROUSEL)
**First-comment URL**: `[set up a guide-v2 waitlist URL — Notion form or Mailchimp]`
**Asset**: 8-slide carousel
**Hashtags**: `#FieldGuide #VBA #Claude #BuildInPublic`

```
Three weeks ago I published What AI Won't Tell You — a 40-page field guide on AI-assisted VBA development. Since then, readers have written in with corrections.

Here are the five most useful ones — the things I got wrong in v1 that v2 will fix.

Swipe through:
01 Cover
02 #1 — I missed the .Application.Volatile gotcha
03 #2 — My CF sqref advice was right but incomplete (Tables fix it cleanly, sometimes)
04 #3 — Wrong about WorksheetFunction inside UDFs being always safe
05 #4 — Triple-quote escape pattern has one edge case I didn't document
06 #5 — Strategy 6 needs a "when NOT to use root-cause demand" caveat
07 The pattern: every reader correction sharpened a specific claim
08 v2 waitlist (link in comments)

This is the bit I'm enjoying most about publishing this thing — the corrections. Each one is a free upgrade to the next reader's experience. v2 lands in about 6 weeks.

If you've used the guide and found something wrong — please write in. Best email is in the bio.

What's a correction you've received on something you published that genuinely improved it?

#FieldGuide #VBA #Claude #BuildInPublic
```

---

### Fri · 8am · Template E — Confession (closer)
**First-comment URL**: `demo.adinalieblich.com`
**Asset**: 1 site photo (culvert, drainage, real engineering work)
**Hashtags**: `#AEC #CivilEngineering #AI #LocalGov`

```
I thought AEC didn't need agents.

A culvert inspection changed my mind.

The job: 47 culverts across one council area. Standard procedure is a clipboard, a tape measure, and a photo per asset. Four engineers, two days, ~80 hours of field time. Reports written up the following week from notes and photos — usually another 40 hours of office work.

The agent I built does the office part. Photos go into a folder with GPS metadata. Claude reads each photo, extracts: structure type, visible defects (cracks, displacement, vegetation, scour), apparent severity. Cross-references the GPS against the asset register. Drafts a one-paragraph condition note per culvert in the council's standard format.

Forty hours of office work compressed to ~3.

Two important things this doesn't do: it doesn't sign off the inspection (engineer responsibility, always), and it doesn't replace the field measurement (a defect you can see from a photo isn't always a defect that matters for structural assessment).

But the drafting is mechanical. The compliance with the standard format is mechanical. The cross-reference is mechanical.

That's where AEC agents live. Not "replace the engineer." Replace the office-work tail that follows the engineer.

What's the office-work tail YOU'D hand to an agent if you could?

#AEC #CivilEngineering #AI #LocalGov
```

---

## How to use this file

**Monday morning (launch week)**:
1. Open the carousel template at `vote.adinalieblich.com/pwa-v2/carousel-template.html`
2. Edit slide content for Week 1 Monday's post (architecture carousel)
3. Cmd/Ctrl+P → Save as PDF → upload as document post to LinkedIn
4. Paste the Monday text from above as the post body
5. Hit publish at 8am AWST
6. Immediately post the first-comment URL in a reply
7. Pin your own reply
8. Stay near LinkedIn for 60-90 min — comments in that window get the algorithm boost

**Every other post**:
- 80% of the work is reading the draft, editing one or two lines so it feels like YOU on the day, and hitting publish at the right time
- The first comment URL is non-negotiable per the link-penalty data

**If a draft doesn't feel right**:
- Send me the post number and what's off — I'll rewrite that draft only
- The voice should match your real builds. If a story is wrong (e.g. "I never told my council that") swap to a real example
