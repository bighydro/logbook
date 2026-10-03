# Takeout: Tasks → `task/v1`

`Takeout/Tasks/Tasks.json` is every list in Google Tasks with every task in it, open or done:
`{"kind": "tasks#taskLists", "items": [<list>]}`, each list `{id, title, updated, items: [<task>]}`
and each task `{id, title, updated, status, due?, completed?, notes?, parent?, links?, hidden?,
deleted?}`, every time RFC 3339 in UTC. The adapter is `google-takeout-tasks` (`takeout-tasks`),
and `logbook add` recognises the file and the `Tasks/` folder on its own:

```bash
logbook add ~/Takeout/Tasks
logbook add takeout-tasks ~/Takeout/Tasks/Tasks.json --dry-run
```

## What a task becomes

One `task/v1` line per task (RFC 0016), subtasks lines of their own, tier 2, source `google-takeout`.

| Field | From |
|---|---|
| `at` | the task's `updated`: the export keeps no creation time, so the line is dated when the task last changed |
| `raw_id` | `<task id>@<updated>`: a task ticked off and exported again is a new line; an unchanged one appends nothing |
| `title` | the task's title, whitespace collapsed; a task with no title is skipped and counted |
| `status` | `done` for `completed`, else `open` |
| `due` | the day (`YYYY-MM-DD`): the export spells a due date as a midnight instant, and a day is what it means |
| `completed_at` | the completion instant, on a done task |
| `list` | the list's title, the task's context |
| `notes`, `parent` | the notes verbatim; the parent task's id for a subtask |
| `modified_at` | `updated` again, for readers that fold by it |
| `extra` | `hidden`, `deleted` (counted too) and `links` as `{type, description, url}` |

`--since` cuts on `at`. Nothing is written back and nothing is fetched. `logbook promises` reads
these lines when it closes a proposal (SPEC §3.2, *Promises*); a reader never changes a task.

The fixture is `tests/fixtures/takeout/Tasks/Tasks.json`, the Oslo persona's lists.
