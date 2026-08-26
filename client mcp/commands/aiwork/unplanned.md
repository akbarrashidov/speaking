---
description: Doskada vazifasi yo'q ishni qayd qilish
argument-hint: [nima qilindi]
---

Record work that has no task on the board: $ARGUMENTS

Call `report_unplanned`. It creates a task in the "Rejadan tashqari"
column — this does not touch the task you are currently working on, and it
is a separate call.

Threshold — only record what a person would want on the record:
- yes: a bug that broke the build, a security issue, a config fix, a
  migration, a change that affects other tasks
- no: variable renames, import order, comments, formatting, a single typo

If it fits in the current task's summary, put it there instead.

Summary should also say why it was unplanned ("found while running the
migration", "the build was broken").

Group small work of the same kind into one call: "i18n keys fixed in three
routers" — one call, not three.
