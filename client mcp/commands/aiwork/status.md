---
description: Joriy seans va ulanish holati
---

Show the current aiwork state, without changing anything:

1. Whether the `aiwork` MCP server is reachable — if a call returns 401 or
   404, say what that means (token missing or revoked; project slug not
   found in the token's team)
2. `list_columns` — the team's columns and their roles
3. The current session: is one open, which task is claimed, is anything
   left unclosed
4. How many unsent lines are in `~/.aiwork/journal.ndjson`

Do not call `claim_task`, `finish_task` or `report_unplanned` here.
