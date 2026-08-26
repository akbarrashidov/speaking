
## Task tracking вЂ” aiwork

Work in this repo is tracked on the aiwork board over MCP, not in files.

- Before writing code: `start_session()`, then `claim_task(session_id, task_id)` вЂ”
  it hands you the task's checklist and what previous sessions reported.
- Work through the checklist top to bottom. The moment an item is finished,
  `check_off(session_id, task_id, item_ids=[...], note="what you actually did")`.
  Never tick an item you have not finished.
- When your part is done: `finish_task(session_id, task_id, summary, outcome)`.
  It does not close the task and does not move it вЂ” a person does that.
- Given a dispatch code (`aiwork AIW-7F3K`): call `get_dispatch("AIW-7F3K")` вЂ” it
  opens the session for you, so skip `start_session`.
- Read the `aiwork` skill (`.claude/skills/aiwork/SKILL.md`) before touching the
  board вЂ” it has the full procedure and the rules you will otherwise get wrong.
- Requires `AIWORK_TOKEN` in the environment. Without it every call returns 401:
  tell the user, do not retry.

