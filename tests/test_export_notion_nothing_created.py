"""The other side of `logbook export notion`: nothing is created, asked or matched on the Notion side,
and on this side nothing changes but the folder, one `crossing/v1` line and the index cache.

Every test snapshots every file under the test's folder (the record, the home directory with the
index cache, the output folder and whatever lands beside it) before and after a run and names what
changed. The record is `tests/test_export_notion.py`'s: Ines Nordmann of Oslo, who does not exist."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_export_notion import NOW, _entry, build

import logbook
from logbook import cli
from logbook.contrib import notion_export
from logbook.core import policy, store
from logbook.core.store import Logbook

Snapshot = dict[str, tuple[int, str]]  # path under tmp_path, posix -> (bytes, sha256); a folder: (0, "dir")
HTTP_CLIENTS = ("http.client", "urllib.request", "httpx", "requests", "websockets")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = build(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))
    _entry(record)
    return record


def _snapshot(base: Path) -> Snapshot:
    found: Snapshot = {}
    for p in base.rglob("*"):
        key = "/".join(p.relative_to(base).parts)
        if p.is_dir():
            found[key + "/"] = (0, "dir")
        elif p.is_file():
            raw = p.read_bytes()
            found[key] = (len(raw), hashlib.sha256(raw).hexdigest())
    return found


def _changed(before: Snapshot, after: Snapshot) -> set[str]:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _is_cache(lb: Logbook, base: Path, key: str) -> bool:
    """The index cache the readers already use: a file in `lb.index_path`'s folder (RFC 0029 §8)."""
    cache = "/".join(lb.index_path.parent.relative_to(base).parts) + "/"
    return key.startswith(cache)


def _run(out: Path, *args: str) -> None:
    cli.main(["export", "notion", str(out), *args])


def _fails(out: Path, *args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(out, *args)
    return int(e.value.code or 0)


def _lock_is_free(lb: Logbook) -> None:
    assert not (lb.root / "state" / "writer.lock").exists(), "the writer lock is still there"
    assert store._held.get(lb._lock_path(), 0) == 0, "this process still counts itself a holder"


def _nothing_beside(out: Path) -> None:
    assert not list(out.parent.glob(f".{out.name}.*")), "a staging or old folder is left beside OUT"


# -- the Notion side ---------------------------------------------------------------------------------------


def test_the_command_reaches_no_http_client_and_not_the_notion_adapter() -> None:
    """In a fresh interpreter, importing the command loads neither the Notion adapter (the one module
    of the package that talks to api.notion.com) nor any HTTP client the `no_network` fixture guards."""
    code = (
        "import sys\n"
        "import logbook.contrib.notion_export\n"
        "import json\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('logbook'))))\n"
        f"print(json.dumps(sorted(m for m in {HTTP_CLIENTS!r} if m in sys.modules)))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(Path(logbook.__file__).resolve().parent.parent))
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, encoding="utf-8", env=env, check=True, timeout=120
    )
    loaded, clients = (json.loads(line) for line in done.stdout.strip().splitlines()[-2:])
    assert "logbook.contrib.adapters.notion" not in loaded
    assert not [m for m in loaded if m.startswith("logbook.contrib.adapters")], "no adapter at all"
    assert clients == []


def test_a_dry_run_asks_nothing_of_the_network(lb: Logbook, tmp_path: Path, no_network: list[str]) -> None:
    _run(tmp_path / "out", "--since", "2026-09-01", "--dry-run")
    assert no_network == []


# -- this side: what a run creates or changes --------------------------------------------------------------


def test_a_dry_run_changes_no_file_anywhere(lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "out"
    seq = lb.meta["seq"]
    before = _snapshot(tmp_path)
    _run(out, "--since", "2026-09-01", "--dry-run")
    assert _changed(before, _snapshot(tmp_path)) == set(), "a dry run writes nothing at all"
    assert not out.exists() and lb.meta["seq"] == seq
    assert not (lb.root / "state").exists(), "no lock, and no state folder for one"
    _nothing_beside(out)
    _lock_is_free(lb)
    assert "nothing written" in capsys.readouterr().out


def test_a_real_run_changes_only_the_folder_one_line_and_the_index_cache(lb: Logbook, tmp_path: Path):
    out = tmp_path / "out"
    seq = lb.meta["seq"]
    month = lb.root / "logbook" / "2026" / "10.jsonl"  # where a line at NOW (2026-10-15) lands
    lines_before = month.read_bytes().count(b"\n")
    before = _snapshot(tmp_path)
    _run(out, "--since", "2026-09-01")
    changed = _changed(before, _snapshot(tmp_path))
    in_out = {k for k in changed if k == "out/" or k.startswith("out/")}
    assert in_out == {"out/", "out/ideas.json", "out/manifest.json", "out/orgs.json", "out/persons.json"}
    cache = {k for k in changed if _is_cache(lb, tmp_path, k)}
    in_record = changed - in_out - cache
    assert in_record == {"lb/logbook.json", "lb/logbook/2026/10.jsonl"}, (
        "the only writes to the record are the appended line and the head that follows it: no policy"
        " file, no watermark, no state file"
    )
    assert month.read_bytes().count(b"\n") == lines_before + 1 and lb.meta["seq"] == seq + 1
    line = lb.line_by_seq(seq + 1)
    assert line is not None and line["kind"] == "crossing" and line["payload"]["destination"] == "notion"
    assert not (lb.root / "state").exists()
    _nothing_beside(out)
    _lock_is_free(lb)


@pytest.mark.parametrize("earlier_run", [False, True], ids=["fresh OUT", "OUT holds an earlier export"])
def test_a_failure_while_a_section_is_written_leaves_everything_as_it_was(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    earlier_run: bool,
) -> None:
    out = tmp_path / "out"
    if earlier_run:
        _run(out, "--since", "2026-09-01")
    seq = lb.meta["seq"]
    before = _snapshot(tmp_path)
    real_write_bytes = Path.write_bytes

    def refuse_ideas(self: Path, data: Any) -> int:
        if self.name == "ideas.json":
            raise OSError(28, "No space left on device (simulated)")
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", refuse_ideas)
    assert _fails(out, "--since", "2026-09-01") == 1
    monkeypatch.undo()
    assert "export notion:" in capsys.readouterr().err
    assert _changed(before, _snapshot(tmp_path)) == set(), "OUT as it was, no staging folder, no line"
    assert out.exists() is earlier_run and lb.meta["seq"] == seq
    _nothing_beside(out)
    _lock_is_free(lb)


def test_a_failure_while_reading_under_the_lock_releases_it(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build` runs under the writer lock; an error there (the entities settings file is not JSON)
    is one sentence, exit 2, nothing written, and the lock is released."""
    out = tmp_path / "out"
    (lb.root / "policy" / "entities.json").write_text("{not json", encoding="utf-8")
    seq = lb.meta["seq"]
    before = _snapshot(tmp_path)
    assert _fails(out, "--since", "2026-09-01") == 2
    assert _changed(before, _snapshot(tmp_path)) == set()
    assert not out.exists() and lb.meta["seq"] == seq
    _nothing_beside(out)
    _lock_is_free(lb)


def test_a_crash_between_the_folder_and_the_line_leaves_no_line_and_no_lock(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented residue (`notion_export.export`): the folder stands, no line names it, the next
    run replaces it. Nothing else: no staging or old folder beside OUT, no lock, nothing in the record."""
    out = tmp_path / "out"
    _run(out, "--since", "2026-09-01")
    first = json.loads((out / "manifest.json").read_bytes())["export_id"]
    seq = lb.meta["seq"]
    before = _snapshot(tmp_path)

    def crash(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated crash between the folder and the line")

    monkeypatch.setattr(notion_export, "record", crash)
    with pytest.raises(RuntimeError):
        _run(out, "--since", "2026-09-01")
    changed = _changed(before, _snapshot(tmp_path))
    assert changed and all(k.startswith("out/") for k in changed), changed
    assert json.loads((out / "manifest.json").read_bytes())["export_id"] != first, "the folder was replaced"
    assert lb.meta["seq"] == seq, "no line"
    _nothing_beside(out)
    _lock_is_free(lb)
