---
description: Vazifani tugatish va yakuniy hisobot
argument-hint: [qolgan ish bo'lsa]
---

Finish the current task.

Call `finish_task`:
- `summary` — 2 to 5 sentences: what changed and why. Written for a person,
  in the language the user is speaking. Not a diff, not a file list.
- `outcome` — `completed` if the work is done, `blocked` if something stopped it
- `remaining` — $ARGUMENTS if given, otherwise anything genuinely left undone.
  Leave it empty when nothing is left; never write "all done".

Also send unsent journal lines in `pulses` and advance the offset.

The task will NOT move to done — it gets an `awaiting_review` flag and a
human presses the button on the board. This is intended; do not treat it
as a failure and do not look for another tool.

If the response contains `open_tasks`, tell the user which tasks are still
open in this session.
