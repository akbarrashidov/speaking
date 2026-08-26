---
description: Oraliq hisobot yozish
argument-hint: [nima bo'ldi]
---

Write a progress report on the current task: $ARGUMENTS

Call `report_progress`. Pick `kind` from what happened:
- `action` — tests ran, migration applied, build finished, an area is done
- `blocked` — cannot proceed: missing info, missing access, waiting on a human
- `thought` — a decision was made or an approach chosen

If $ARGUMENTS is empty, write the report yourself from what happened in
this session since the last report — one or two sentences.

Language: whatever the user is speaking. Written for a person reading the
board, not a log. No command output, no file lists.

Also send any unsent lines from `~/.aiwork/journal.ndjson` in the `pulses`
parameter, then advance `~/.aiwork/offset`.
