---
name: aiwork
description: |
  Track work on the aiwork board — claim a task before the first file change,
  finish it the moment the work is done, report work no task covers.
  Use in this repo before starting code work, when a task is finished, before
  moving to another task, and when given a dispatch code like AIW-7F3K.
---

# aiwork

Eleven MCP tools on the `aiwork` server. They read and write the team's board, so
everything you do here is visible to a person: what you report shows up in the
agent log next to the task.

Requires `AIWORK_TOKEN` in the environment. Project scope comes from the
`X-Aiwork-Project` header in `.mcp.json` at the repo root.

## Seven points where you call the board

These are triggers, not judgement calls: each one is an event you can **watch
happen**. When it happens, you make the call. "Later", "at a good moment",
"if it seems worth it", "if it is meaningful enough" are not on this list and
are not on any list in this file.

| Event | Call |
|---|---|
| 1. Before the first file change | `start_session()`, then `claim_task(session_id, task_id)` — or `get_dispatch(code)` if you were given one |
| 2. The work on the task is done — code written, tests passing, result in hand | `finish_task(session_id, task_id, summary, outcome)` |
| 3. Before moving to another task | `finish_task` on the current one, **then** `claim_task` on the next |
| 4. Work that no task on the board covers is done | `report_unplanned(session_id, summary)` |
| 5. You cannot go on without someone else | `report_progress(session_id, task_id, body, kind="blocked")` |
| 6. The user closes the work ("tugadi", "bo'ldi", "rahmat", "спасибо") while a task is still open | `finish_task` — `outcome="partial"` with `remaining` if it is not finished |
| 7. Tests ran and the result changed · a migration was applied · a build or type-check finished · an area of the work is done · a dependency or config changed · a command failed and the plan changed | `report_progress(..., kind="action")` — see **Reporting progress** for the exact list |

Point 2 is the one that gets skipped. `finish_task` is called when the work is
done, not when the conversation happens to end: the machine can be closed in
between, and then the work exists only in your context, which is gone.

Point 7 is the one that used to say "after every meaningful step". "Meaningful"
is a judgement, and a judgement postpones: the whole of sections 16 and 17 of
the project worklog was written with no session, no task and no report, and the
board has no trace of it. So the trigger is a list of events now, and the list
is closed.

## Language

Everything a person reads — every `summary`, every `body` — goes in **the language
that person uses with you**, not in English. The board is Uzbek and Russian; the
agent log is read by people, and an English wall of text in it is unusable to them.

- User writes Uzbek → report in Uzbek.
- User writes Russian → report in Russian.
- Unsure → match the language of the task title.

File names, identifiers, commands, branch names and error text stay exactly as
they are. Never translate those — they are addresses, not prose.

## Starting work — two entry points

**1. You were given a dispatch code** ("aiwork AIW-7F3K", "AIW-7F3K ni ol"):

```
get_dispatch("AIW-7F3K")
→ { session_id, task: {id, title, column, column_kind, checklist: {done, total}, ...},
    description,
    checklist: [{id, body, group, done}, ...],
    previous_reports: [{kind, summary, outcome, at}, ...] }
```

The dispatch **opens the session for you**. Do not call `start_session` and do
not call `claim_task` — the code already points at one task. Read
`previous_reports`: another session may have already done part of the work.
Codes are one-time use; a second `get_dispatch` with the same code fails.

**2. No code — you pick the work:**

```
start_session(agent_kind="claude_code", branch="feature/x")  → { session_id, reused }
next_assignment()                                            → { task, description }
claim_task(session_id, task.id)
→ { task, description, checklist: [...], previous_reports: [...] }
```

`claim_task` is also how you **come back** to a task: called on a task already in
an `active` column it moves nothing and simply hands you the state — the
checklist with its ticks, and what previous sessions reported. Start there after
a restart instead of reconstructing the work from memory. See **Continuing work
after a break**.

Use `list_my_tasks()` instead of `next_assignment()` when the user named a
specific task and you need to find it by title. `reused: true` is normal — it
means a live session already existed and you got it back.

## Working on several tasks in one session

One session, many tasks — but **one task at a time**. Close the current task
before you claim the next one. Two pieces of work written into one task make
the board lie: the person reading it cannot tell what was actually delivered.

Three to five tasks in one session is normal. Every one of them gets its own
`finish_task`.

```
start_session(client_sid="<your own run id>")      → s
claim_task(s, A)
  ... work on A ...
  report_progress(s, A, "Migratsiya bajarildi, ustunlar jadvali paydo bo'ldi.", "action")
  report_progress(s, A, "Testlar o'tdi, 192 ta yashil.", "action")
finish_task(s, A, "Dinamik ustunlar qo'shildi. status ustuni column_id ga o'tdi.",
            "completed")                          ← A is closed here, not later

claim_task(s, B)                                   ← only after A was closed
  ... work on B ...
  report_progress(s, B, "Golden set fayli topilmadi.", "blocked")
finish_task(s, B, "Yarim qoldi.", "blocked",
            remaining="golden set qayerda ekanini aniqlash")

  ... fixed a broken build on the way; no task covers it ...
report_unplanned(s, "Build buzilayotgan edi: entrypoint.sh da CRLF. "
                    ".gitattributes qo'shildi.")    ← its own call, not folded into B

claim_task(s, C)
  ... work on C ...
finish_task(s, C, "...", "completed")
```

Two progress entries on A and one on B, because that is how many events
happened — not because a number was aimed at. Three to five tasks in one
session is normal.

Rules this example encodes:

- **One task open at a time.** Never `claim_task(B)` while A is still open, and
  never report B's work under A's `task_id`.
- **`report_unplanned` is never mixed into a task.** It is a separate call, made
  when that work is done — not a sentence inside the next `finish_task`.
- **Every task gets its own `finish_task`**, with its own outcome. `blocked` and
  `partial` are outcomes, not failures to report.

The server helps you here, but does not enforce it: `claim_task`, `finish_task`
and `report_unplanned` return **`open_tasks`** — the tasks this session claimed
and never closed — and name them in `note`. If you see that field in a response,
close what it lists before you go on.

## Reporting progress — when and which kind

`report_progress(session_id, task_id, body, kind)` — `body` is one or two
concrete sentences.

### `kind="action"` — an exact list of events

Call it **the moment** one of these happens. Not at a convenient point, not
before the next tool call, not at the end:

- **tests ran and the result changed** — red went green, or new failures appeared
- **a migration was applied** — `alembic upgrade`, `alembic downgrade`
- **a build or a type-check finished**
- **one area of the work is done** — a group of files, not a single file
- **a dependency was added, or configuration changed**
- **a command failed in a way that changed the plan**

Do **not** call it for: `ls`, `cd`, `cat`, `grep`, `git status`, reading a file,
a one-line edit, formatting.

**One event, one call.** Several events are never rolled into one call at the
end: the board exists to show work while it is happening, and a single entry
written at midnight says only that you were there, not what was going on.

### `kind="thought"` and `kind="blocked"`

| kind | When |
|---|---|
| `thought` | A decision was made, an approach chosen, a trade-off settled. One to three times in a session — this is the rare one. |
| `blocked` | You **cannot proceed**: missing information, missing access, waiting on a human decision. The moment it happens, always. |

`blocked` is not "this is hard" and not "this is taking long". It means the work
cannot move without someone else.

**`kind="blocked"` does not change anything about the task.** It writes a journal
entry that the person sees in the agent log; the card stays in its column. There
is no `blocked` column role, and adding a column named "Blocked" would not make
one — roles are fixed (see **Columns**), names are not.

### Reports are the only memory that survives

Your session lives in a process on someone's machine. The machine gets closed,
the process gets killed, the context ends — and everything you were holding in
your head is gone. What stays is in the database: the reports and the ticks on
the checklist.

So the trigger for writing is the work being **finished**, not the session being
over:

- A checklist item is done → `check_off` it with a note, right then.
- The task is done → `finish_task`, right then. Not after the next task, not
  when the user says goodbye.
- Work no task covers is done → `report_unplanned`, right then.

A report you did not write is work nobody can prove you did — and after the
process dies, work nobody can even find.

### Continuing work after a break

Never restart a task from scratch and never guess what state it is in.

```
list_my_tasks()          → cards carry checklist: {done, total}
claim_task(session_id, task_id)
→ { checklist: [...], previous_reports: [...] }
```

Read `previous_reports` oldest to newest — that is the story of the task — and
look at which checklist items are already ticked. **Continue from there.** Work
that a previous session reported is done; doing it again wastes the person's time
and overwrites their review.

If the reports and the code disagree — a report says a migration was applied and
it is not there — say so in `report_progress`. Do not silently redo it and do not
silently skip it.

## Finishing a task

```
finish_task(session_id, task_id, summary, outcome, remaining=None)
```

- `summary` — what was done, for a person, in their language (see **Language**
  above).
- `outcome` — `completed` | `partial` | `blocked`.
- `remaining` — what is actually left, when something is. Leave it empty when
  nothing is left; never write `"hammasi tugadi"` into it, and never write it as
  a promise about work you have not started.

### What goes in a summary

The text is written for **a person looking at the board**, not for a log.
`report_progress` — one or two sentences. `finish_task` — two to five: what
changed and why. File names when they help the person find it; never a diff and
never a list of every touched file.

```
good (uz):  "Testlar o'tdi, 192 ta yashil. MCP doirasiga jamoa filtri qo'shildi."
good (ru):  "Тесты прошли, 192 зелёных. Добавлен фильтр по команде."
good (uz):  "create_session() da LIMIT 1 ORDER BY siz edi — birinchi duch kelgan
             a'zolik olinardi. Endi jamoa so'rovda ochiq keladi va a'zolik
             tekshiriladi. 5 test qo'shildi."
bad:        "pytest exit 0, 192 passed in 12.4s"      ← command output, not a report
bad:        "app/mcp/deps.py, app/projects/deps.py o'zgardi"   ← a file list
bad:        "Ish davom etmoqda."                      ← says nothing
bad:        "Bug tuzatildi."                          ← nobody can tell what changed
bad:        [50 lines of diff, or a list of 20 files] ← the board is not a patch
```

File and function names are fine when they carry meaning. As a list — no.

The same bar applies to `report_unplanned`, plus one thing more: say **why it
was unplanned** ("migratsiya paytida topildi", "build buzilgan edi").

**`completed` over an open checklist is not accepted as `completed`.** If items
are still unticked, the board records the outcome as `partial`, fills `remaining`
with those items and tells you so. There is no way around it: either the work is
finished and the items are ticked, or it is partial and you say so plainly.

**`completed` does not mean `done`.** The task is flagged `awaiting_review` and
**stays in the column it is in — `finish_task` never moves it.** A person moves
it and closes it on the board. This is deliberate, not a bug, and not something
to work around.

## Columns

Columns are per team and they change: a team may run `Navbatda → Kod ko'rikda →
Sinovda → Tayyor`, and another just three columns with different names. **Never
guess work state from a column name.** Every column carries a `kind`, and that is
what the product reads:

| kind | meaning |
|---|---|
| `backlog` | someday — not a commitment; never listed to you, never claimed |
| `open` | ready to be taken |
| `active` | work in progress |
| `done` | closed |
| `unplanned` | done outside any plan; never in any work list |

```
list_columns() → [{id, name, kind, position, wip_limit, task_count, next_column_id}]
```

Call it when you need to know where work goes next, or when a person asks about
the board. Two or three `active` columns is normal.

**You never move a task yourself.** `claim_task` moves it once — along the flow:
the column's `next_column_id`, or the first `active` column when the flow ends.
That is the only move an agent makes in its whole life. `finish_task` does not
move anything, and there is no tool that does. Everything after review is the
person's hand.

`claim_task` leaves a task alone and returns a note when it sits in a `backlog`,
`unplanned` or `done` column, and when it is already `active`. A note is not an
error: read it and move on.

## The activity trace — the journal on disk

An editor hook (`~/.aiwork/aiwork-pulse`, registered in `~/.claude/settings.json`)
appends one line to `~/.aiwork/journal.ndjson` after every `Edit`, `Write`,
`MultiEdit` and `Bash`. That file is a record of **facts**: which tool, which
path, when. It never leaves the machine on its own — no daemon, no network call
in the hook.

**It is not a report and never becomes one.** The hook cannot say what you did
or why; only you can. A pulse proves work happened, a report says what it was.
The board shows both, side by side, and a session with pulses and no reports is
displayed as exactly that: *work happened, no report*.

**Carrying it to the server is your job.** Four tools take an optional `pulses`
argument: `start_session`, `report_progress`, `finish_task`, `report_unplanned`.
Before you call any of them, read the lines you have not sent yet and pass them:

```bash
# how many lines already went (missing file = none)
sent=$(cat ~/.aiwork/offset 2>/dev/null || echo 0)
tail -n +$((sent + 1)) ~/.aiwork/journal.ndjson | head -200
```

Each line is already the right shape — `{ts, client_sid, tool, target, cwd}`;
pass `ts`, `client_sid`, `tool`, `target` (drop `cwd`, the server takes the
project from your session). Then move the marker:

```bash
wc -l < ~/.aiwork/journal.ndjson > ~/.aiwork/offset
```

Rules that make this safe to get wrong:

- **Up to 200 lines per call.** The rest stays on disk and goes with the next one.
- **Repeats are dropped server-side.** If you send the same lines twice, the
  answer is `accepted: 0` — not an error. So sending too much is harmless, and
  an offset you forgot to move costs nothing.
- **An empty array is not an error either.** No work since last time is a normal
  answer.
- **Pass `client_sid` to `start_session`** — your own run id, the same value the
  journal lines carry. With it the trace lands on your session exactly. Without
  it the server has to guess by time and project, and it only guesses for
  pulses that fall inside the session's own window.
- **Never edit the journal and never delete it.** Move the offset instead. The
  file is the only copy of that record.

If none of this happened — no hook installed, no pulses sent — nothing breaks.
The trace is a second, silent witness, not a dependency.

## Checklist

A checklist item is one step **a person wants to see ticked off separately**.

Roll same-shaped small work into ONE item:

```
good:  "i18n satrlari qo'shildi (5 fayl)"
bad:   one item per file
```

Three to twelve items on a task is normal. Past twenty, the split is too fine —
merge before you write it.

```
add_checklist_items(session_id, task_id,
                    items=[{"body": "migratsiya", "group": "Backend"}, ...])
check_off(session_id, task_id, item_ids=[...], note="...")
→ { checked, done, total, remaining: [{id, body, group}, ...] }
```

**Pass them all in one call.** Ten calls put ten lines in the work log and push
the actual work out of it. `group` is optional and free-form ("Backend",
"Frontend", "Testlar") — use it when the task really splits that way.

Most tasks arrive **with a list already on them**: a person wrote it, or the
model wrote it from the description when the card was created. Then the list is
your order of work. Take the first item that is not ticked, do it, tick it, take
the next. `check_off` returns `remaining`, so the next step never needs asking
for.

### Ticking off is a claim about reality

**Tick an item only when it is actually finished.** Not "the code is written and
probably works" — finished: it runs, the test passes, the file is saved. If you
are unsure whether it counts as done, **it does not**. An item you ticked is what
the person will not check again.

`note` is required and is not decoration: one or two concrete sentences about
what you actually did — the file, the migration id, the command that passed. It
goes into the work log under the item, and it is what the next session (or the
next person) reads. `"done"` is not a note.

Tick **at the moment the item is finished**, not in one batch at the end. A batch
at the end is exactly the work that disappears when the machine dies.

Ticking an already-ticked item is not new work: the tool answers `checked: 0` and
says it was already done. Do not present that as progress.

There is no tool to edit or delete an item, and that is deliberate: a person
writes the plan, you extend it and tick off what you finished. If an item is
wrong, say so in `report_progress` — do not work around it.

## Work outside any task

```
report_unplanned(session_id, summary, checklist_items=None)
```

For work you actually did that no task covers. It lands in the column with role
`unplanned`, outside the main flow, so it never pretends to be planned work.
**Call it when that work is done**, as its own call — never folded into the
`finish_task` summary of whatever task you happen to be on, and never saved up
for the end of the session.

### The threshold

```
yes:  a bug that was breaking the build, a security hole, a config fix,
      a migration you had to add, a change that affects another task
no:   a renamed variable, reordered imports, a comment, formatting,
      a single typo
```

Below the line, nothing goes on the board at all — not a card, not a sentence in
someone else's summary. **When in doubt, do not write it.**

### How many

Zero to three `report_unplanned` calls in a session is normal. Past five, the
split is too fine: merge.

Small work of the same shape goes into **one** call:

```
good:  "uchta routerda i18n kalitlari tuzatildi"   ← one call
bad:   three calls, one per router
```

If the team has no `unplanned` column, the tool refuses and tells you why. It
does not fall back to another column: that would mix unplanned work into the
team's flow, which is the one thing the separate column exists to prevent.

## Do not

- Do not close a task yourself, and do not look for a `done` / `complete` /
  `approve` tool. There is none, by design.
- Do not create a task when you cannot find one — there is no tool for it. Ask
  the user.
- Do not claim `backlog` tasks. Backlog is "someday", not a commitment; taking
  one out is a person's decision. `claim_task` on a backlog task returns a note
  and leaves it alone.
- Do not guess a column by its name, and do not ask for a task to be moved to a
  column you picked. Read `list_columns()` and let `claim_task` do the one move.
- Do not add checklist items one call at a time, and do not fold unplanned work
  into a task's summary — it is its own `report_unplanned` call or nothing.
- Do not tick a checklist item you have not finished, and do not tick a batch of
  them at the end of the work "to tidy up". Both turn the list into a story.
- Do not leave a finished task open. `finish_task` is called when the work is
  done, not when the user says goodbye and not at the end of the session — the
  machine can die in between, and then it never happened.
- Do not claim a second task while the first is open, and do not finish the
  session with `open_tasks` still coming back in the responses.
- Do not start a task over because you do not remember it. Read
  `previous_reports` and the ticks first.
- Do not call `report_progress` before `claim_task` (or before `get_dispatch`).
- Do not write a `report_progress` entry for a file read, a `grep`, a `git
  status` or a one-line edit — the list of events in **Reporting progress** is
  the whole list.
- Do not save several events up for one call at the end of the work. The board
  has to show the work while it is happening.
- Do not roll several pieces of work into one `finish_task`.

## Errors

- **401** — `AIWORK_TOKEN` is missing, wrong, or revoked. Tell the user and stop;
  retrying will not help. The token is issued at
  `https://work.ai-energy.team/settings`.
- **404** — the resource does not exist **or** you have no access to it. The two
  are deliberately not distinguished. Do not probe other task or project ids to
  find out which — ask the user.
- **`warning` field in a response** — the project scope did not arrive: the
  `X-Aiwork-Project` header did not reach the server. You are seeing every
  visible project at once. Pass `project="umumiy"` explicitly to the tools until
  it is fixed.

Tool failures come back as normal error responses, not HTTP codes: 401 and 404
are the transport refusing you before the tool runs.

## Project scope

Scope comes from the `X-Aiwork-Project` header in `.mcp.json`. The value is a
**project slug scoped to your token's team** — not a team slug.

`list_my_tasks` and `next_assignment` are already limited to that project; do
not filter the results again. Every tool also takes an optional `project`
parameter as a fallback for clients that cannot send custom headers — the header
wins when both are present.

## Task fields

`{ id, title, column_id, column, column_kind, checklist, priority, due_date,
   awaiting_review, assignee, project }`

`checklist` is `{done, total}` — or `null` when the task has no list. It is the
fastest way to see that a task is already half-finished before you touch it.

`column` is the team's own name for it and is written by a person — show it to
them as is. `column_kind` is what you decide by: `backlog`, `open`, `active`,
`done`, `unplanned`.

`priority` is a number: `0` low, `1` normal, `2` high, `3` urgent.
`awaiting_review: true` means an agent already finished its part and a person
has not confirmed it yet.
