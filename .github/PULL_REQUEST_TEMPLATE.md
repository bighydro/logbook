## What

## Why

## Checklist
- [ ] Tests added or updated; `uv run pytest` green
- [ ] If a command is renamed or a reader's output changes: `LOGBOOK_SLOW=1 uv run pytest tests/test_fuzz_readers.py` run and green (the pull-request CI tier skips it)
- [ ] No real personal data in fixtures (synthetic only)
- [ ] No write/update/delete path into the log except `Logbook.append`
- [ ] A changelog fragment, `changelog.d/<short-slug>.md`, never an edit to CHANGELOG.md (or the `no-changelog` label)
- [ ] If SPEC.md changed: version bumped, `conformance/` regenerated, an ADR
- [ ] Signed-off (`git commit -s`, DCO)
