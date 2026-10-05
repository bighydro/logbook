### Housekeeping
- A pull request that renames a command or changes a reader's output runs `LOGBOOK_SLOW=1 uv run pytest tests/test_fuzz_readers.py` once before it merges (CLAUDE.md, CONTRIBUTING.md and a box in the pull request template): the fuzz readers are slow-tier, which the pull-request CI tier skips, so #215 turned `main` red on 4 October and #217 fixed it forward.
