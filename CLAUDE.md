# For agents working in this repository

You are one of several coding agents that build this project alongside a human captain. Read SPEC.md and ARCHITECTURE.md first.

Hard rules — a change that needs to break one is wrong; stop and say so:
- Never write to the log except through `Logbook.append`. Never UPDATE or DELETE a line, in code or by hand.
- Never add real personal data to the repository. Fixtures are synthetic; the sample person lives in Oslo and does not exist.
- Never add network calls to an adapter's default path.
- Never change the envelope (SPEC §2–3) without a spec version bump, a regenerated conformance fixture, and an ADR in `docs/adr/`.
- Test first: write the failing test, run it, implement, run it, commit with `-s`. One issue per task, closed by the commit.

Conventions: `uv` for everything (`uv sync --group dev`, `uv run pytest`, `uv run ruff check --fix .`, `uv run mypy logbook`). Conventional commits (`feat:`, `fix:`, `spec:`, `docs:`, `adapter:`). Plain English names inside the code: Logbook, Line, Day, Note — no metaphors.
