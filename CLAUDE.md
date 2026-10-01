# For agents working in this repository

You are one of several coding agents that build this project alongside a human captain. Read SPEC.md and ARCHITECTURE.md first.

Hard rules — a change that needs to break one is wrong; stop and say so:
- Never write to the log except through `Logbook.append`. Never UPDATE or DELETE a line, in code or by hand.
- Never add real personal data to the repository. Fixtures are synthetic; the sample person lives in Oslo and does not exist.
- Example phone numbers, emails and addresses come only from reserved fictional ranges (UK `07700 900xxx`, `example.org`, the Oslo persona); never a real number, even the maintainer's.
- Never add network calls to an adapter's default path.
- Never change the envelope (SPEC §2–3) without a spec version bump, a regenerated conformance fixture, and an ADR in `docs/adr/`.
- Test first: write the failing test, run it, implement, run it, commit with `-s`. One issue per task, closed by the commit.
- Tests never see `LOGBOOK_HOME` or the home directory (`HOME`, `USERPROFILE`) from the shell; `tests/conftest.py` pins them to a temp dir. Never remove that fixture.
- A test never sets `HOME` alone: `Path.home()` reads `USERPROFILE` on Windows, so a test that needs its own home directory monkeypatches `Path.home` (or sets both variables, as `tests/conftest.py` does).
- Every adapter that reads an app's own store (SQLite from a phone backup or this Mac) confirms the schema it needs with `PRAGMA table_info` before reading and tolerates drift: a column it does not need may be missing or renamed and the rows still read; a table it needs that is not there is a counted skip or one clear error naming the store, never a traceback.
- `import-backup` is never run bare against a real backup: always `--only <sources>`, so a run reads only the stores it was asked for. A disabled source in `policy/import.json` stays skipped either way.
- A long session commits after each step, signed, so a crash or a context reset loses one step at most.

Conventions: `uv` for everything (`uv sync --group dev`, `uv run pytest`, `uv run ruff check --fix .`, `uv run mypy logbook`). Conventional commits (`feat:`, `fix:`, `spec:`, `docs:`, `adapter:`). Plain English names inside the code: Logbook, Line, Day, Note — no metaphors.
- Paths: never match or split them as strings; use `pathlib` parts. Windows runs the tests too.

## Commit routine

- Commits are authored as `bighydro <122497530+bighydro@users.noreply.github.com>` only. A cloud or new checkout sets `user.name` and `user.email` before its first commit:
  `git config user.name bighydro && git config user.email 122497530+bighydro@users.noreply.github.com`
- Every commit is signed off and signed: `git commit -s -S`. After every commit run `git log -1 --format='%G?'` and expect `G`. Anything else (`N`, `E`, `B`) means the commit is unsigned or unverifiable: fix it before pushing. (A squash merge GitHub made shows `E` locally because its key is not in the keyring; that is GitHub's commit, not yours.)
- `pre-commit` runs on every commit (`uv run pre-commit install` once per checkout). Its last hook, `scripts/check_pii.py`, greps every added line of the staged diff for the owner's personal identifiers and fails the commit on a match, printing the file and line but never the text. The identifiers are never in the repository: the hook reads them from the file `LOGBOOK_PII_PATTERNS` names, default `~/.config/logbook/pii-patterns`, one case-insensitive regular expression per line (`#` comments and blank lines ignored). Without the file it prints one warning and passes, so CI and strangers are unaffected. Create it locally once, with your real identifiers in place of these synthetic ones:

  ```
  mkdir -p ~/.config/logbook && cat > ~/.config/logbook/pii-patterns <<'EOF'
  # one regex per line, matched case-insensitively against every added line
  07700 900123
  kari\.nordmann@example\.org
  Storgata 1
  EOF
  ```

## Release routine

- Bump `version` in `pyproject.toml` and `__version__` in `logbook/__init__.py` together; move the `Unreleased` block of `CHANGELOG.md` under the new version and date.
- Commit, then grep `__version__` on the tagged commit before `git tag -s`: `git grep __version__ HEAD -- logbook/__init__.py` must print the version you are about to tag. Only then `git tag -s vX.Y.Z -m vX.Y.Z` and push the tag.

## Cross-platform (the tests run on Windows too, and it has caught a bug in every PR that ignored this)

- Paths: never match, split or join them as strings; use `pathlib` (`.parts`, `/`). Windows returns backslashes.
- Timezones: `zoneinfo` needs the `tzdata` package on Windows (already a Windows-only dependency); never assume the OS has a zone database.
- Console output: the CLI reconfigures stdout/stderr to UTF-8 in `main()`; tests that read a subprocess must pass `encoding="utf-8"`, never `text=True`.
- Open files: Windows refuses to delete a file that any handle still holds. Close every SQLite connection (and any file) before an unlink; `Index.discard` enforces this on all platforms.
- Shell: `shutil.which("bash")` on Windows finds the WSL stub, not a shell. Tests that need a real shell skip on `win32`.
- Digests: text mode turns `\n` into CRLF on Windows. Encode once, write those bytes (`write_bytes`, `"wb"`), and hash the bytes you wrote, never the string you formatted.
- Filesystems: macOS is case-insensitive by default (`~/Logbook` and `~/logbook` are the same folder); Windows too. Never rely on case to tell files apart.
