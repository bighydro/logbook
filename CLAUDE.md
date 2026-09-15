# For agents working in this repository

You are one of several coding agents that build this project alongside a human captain. Read SPEC.md and ARCHITECTURE.md first.

Hard rules — a change that needs to break one is wrong; stop and say so:
- Never write to the log except through `Logbook.append`. Never UPDATE or DELETE a line, in code or by hand.
- Never add real personal data to the repository. Fixtures are synthetic; the sample person lives in Oslo and does not exist.
- Never add network calls to an adapter's default path.
- Never change the envelope (SPEC §2–3) without a spec version bump, a regenerated conformance fixture, and an ADR in `docs/adr/`.
- Test first: write the failing test, run it, implement, run it, commit with `-s`. One issue per task, closed by the commit.

Conventions: `uv` for everything (`uv sync --group dev`, `uv run pytest`, `uv run ruff check --fix .`, `uv run mypy logbook`). Conventional commits (`feat:`, `fix:`, `spec:`, `docs:`, `adapter:`). Plain English names inside the code: Logbook, Line, Day, Note — no metaphors.
- Paths: never match or split them as strings; use `pathlib` parts. Windows runs the tests too.

## Cross-platform (the tests run on Windows too, and it has caught a bug in every PR that ignored this)

- Paths: never match, split or join them as strings; use `pathlib` (`.parts`, `/`). Windows returns backslashes.
- Timezones: `zoneinfo` needs the `tzdata` package on Windows (already a Windows-only dependency); never assume the OS has a zone database.
- Console output: the CLI reconfigures stdout/stderr to UTF-8 in `main()`; tests that read a subprocess must pass `encoding="utf-8"`, never `text=True`.
- Open files: Windows refuses to delete a file that any handle still holds. Close every SQLite connection (and any file) before an unlink; `Index.discard` enforces this on all platforms.
- Shell: `shutil.which("bash")` on Windows finds the WSL stub, not a shell. Tests that need a real shell skip on `win32`.
- Filesystems: macOS is case-insensitive by default (`~/Logbook` and `~/logbook` are the same folder); Windows too. Never rely on case to tell files apart.
