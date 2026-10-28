"""Doctor's install hint in a clone run with uv is the short `uv sync --extra <name>` again (the owner's
desk's review of #429): no `--inexact`, no `--project`, no `--python`, the clone named before it. A bare
`uv sync` keeps only the extras it is given, so the line names, beside the one missing, every extra this
Logbook has, and following it removes nothing. #429's pipx and uv-tool lines are unchanged. No real
path: the clone is a temporary folder."""

from __future__ import annotations

from pathlib import Path

from logbook.contrib import doctor


def _clone(tmp_path: Path) -> doctor.Install:
    checkout = tmp_path / "src" / "logbook"
    checkout.mkdir(parents=True)
    return doctor.Install("checkout", folder=str(checkout), python=str(checkout / ".venv" / "bin" / "python"))


def _detail(install: doctor.Install, here: set[str], extra: str = "ais") -> str:
    checks = {c.name: c for c in doctor.extras_checks(lambda m: m in here, install)}
    return checks[f"extra:{extra}"].detail


def test_the_clone_hint_is_uv_sync_extra_name(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    assert doctor.install_line(clone, {"ais"}) == "uv sync --extra ais"
    detail = _detail(clone, set())
    assert detail.endswith(f"; in the clone, {clone.folder}: uv sync --extra ais"), detail
    for long in ("--inexact", "--project", "--python", "--no-default-groups"):
        assert long not in detail, long


def test_the_clone_hint_names_the_extras_already_there_so_it_removes_none(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    detail = _detail(clone, {"cryptography", "ijson"})
    assert detail.endswith(": uv sync --extra ais --extra crypto --extra stream"), detail
    assert "--inexact" not in detail
    said = doctor.how_to_add("ais", lambda m: m in {"cryptography", "ijson"}, clone)
    assert said.endswith(
        f"in the clone, {clone.folder}: uv sync --extra ais --extra crypto --extra stream"
    ), said
