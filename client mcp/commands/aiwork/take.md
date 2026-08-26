---
description: Talon kodi bilan vazifani olish
argument-hint: AIW-XXXX
---

Redeem the dispatch code: $ARGUMENTS

Call `get_dispatch` with that code. Do NOT call `start_session` or
`claim_task` — the dispatch opens the session and moves the task itself.

If it returns 404, the code is used, expired, or belongs to another team.
Say so and stop; do not try other codes.

Then show the task description, checklist and previous reports, and ask
what the user wants done first.
