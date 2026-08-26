---
description: aiwork doskasidagi ochiq vazifalarni ko'rsatish
---

Call `list_my_tasks` and show the result as a short numbered list:
number, title, column, priority, deadline if set.

If the response contains a `warning` field, show it — it means the project
was not resolved from headers.

Do not start any work. Do not call `claim_task`. Just show the list and
wait for the user to pick one.
