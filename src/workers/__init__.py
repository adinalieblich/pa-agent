"""Background workers — long-running async tasks that poll Notion and trigger
side-effects (push notifications, rollups, etc.).

Layer 1 of the v3 spec ends with the **nag worker** (``nag_worker``): polls the
Tasks DB for overdue / urgent items and pushes via ntfy.sh. Future workers
(job-hunt, bill-scanner, email-triage) live alongside it in this package.
"""
