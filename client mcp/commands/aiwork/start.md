---
description: Vazifani olish va ishni boshlash
argument-hint: [vazifa raqami, nomi yoki id]
---

Take the task into work: $ARGUMENTS

Steps:
1. `start_session` — reuse an existing live session if one is returned
2. Find the task: if $ARGUMENTS is a number, use the last shown list; if it
   is text, call `list_my_tasks` and match by title; if it is a uuid, use it
3. `claim_task`

If nothing matches or several tasks match, ask instead of guessing.

Then show what came back in the response: description, checklist, and
reports from previous sessions. Do not start writing code until the user
says what to do — this command only picks up the task.
