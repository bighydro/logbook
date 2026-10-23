"""The orgs of the whole record, kept between readings (`entity_review._org_folds`, `orgs._touches`): each
kind's sightings and touches, in file order, read on from where they stopped, are the reading of every
line, row for row and touch for touch, after every day appended and through every gate; a line into an
earlier month, a correction, a retraction or a resolution reads every line again, and a newly named org
reads every touch again. On the synthetic record of `tests/orgs_record.py`: nobody and nothing in it
exists."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from orgs_record import (
    CODE_ORG,
    KARI,
    LIV,
    OLA,
    OWNER,
    PER,
    browse,
    evidence_record,
    group_message,
    mail,
    meeting,
    resolution,
    settle,
    wire,
)
from persona import utc

from logbook.contrib import entity_review, orgs
from logbook.contrib.entities import ORG
from logbook.core import index, kept
from logbook.core.store import Logbook

GATES = [orgs.gate(), orgs.gate((1, 2)), orgs.gate((1, 2, 3), money=True)]


@pytest.fixture(scope="module")
def settled(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("orgs-kept"))
        settle(lb)
        return lb.root


@pytest.fixture
def lb(settled: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Logbook]:
    root = tmp_path / "lb"
    shutil.copytree(settled, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    yield Logbook(root)


class Whole:
    """How many readings of the org kinds read every line."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = index.Index.of_kind

        def of_kind(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            if kind == "mail" and kwargs.get("after_seq") is None and not args:
                self.n += 1
            return real(idx, kind, *args, **kwargs)

        monkeypatch.setattr(index.Index, "of_kind", of_kind)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _observed(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return [o.row() | {"entity": o.entity} for o in entity_review.build(lb, idx, ORG)]


def _same(lb: Logbook, whole: Whole | None = None) -> int:
    """Kept and read on, as every line reads: the observed orgs, and each gate's touches; how many of
    the kept readings read every line, when `whole` counts."""
    if whole is not None:
        whole.take()
    found = _observed(lb)
    touches = [orgs.read(lb, g).touches for g in GATES]
    n = whole.take() if whole is not None else 0
    with mock.patch.object(kept, "load", return_value=None):
        assert found == _observed(lb)
        assert touches == [orgs.read(lb, g).touches for g in GATES]
    return n


def _days() -> list[list[dict[str, Any]]]:
    """Ten more days of the orgs' lines, after the sitting."""
    out = []
    for n in range(10):
        day = f"2026-10-{13 + n:02d}"
        out.append(
            [
                mail(utc(day, "08:00"), OLA, [OWNER], f"Board notes {n}"),
                mail(utc(day, "09:00"), KARI, [OWNER], f"Kiosk news {n}", cc=[PER]),
                meeting(utc(day, "13:00"), utc(day, "14:00"), f"Tidevann sync {n}", [LIV, PER]),
                group_message(utc(day, "18:00"), OLA, f"Evening {n}"),
                browse(utc(day, "21:00"), f"https://{CODE_ORG}/tide-clock/pull/{n}", "pull"),
                wire(utc(day, "11:00"), "NORDMANN HAVBRIS AS", -10.0 * (n + 1), f"wire-more-{n}"),
            ]
        )
    return out


def test_a_day_at_a_time_the_orgs_are_the_reading_of_every_line(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same(lb)
    whole = Whole(monkeypatch)
    for day in _days():
        lb.append_many(day)
        assert _same(lb, whole) == 0, "every kept reading read on from where it stopped"


def _earlier_month(lb: Logbook) -> None:
    lb.append(**mail(utc("2026-05-20", "10:00"), LIV, [OWNER], "A late one"))


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("mail")))
    lb.append(
        at=str(line["at"]),
        source=str(line["source"]),
        kind="mail",
        tier=int(line["tier"]),
        payload={**line["payload"], "subject": "corrected", "supersedes": line["id"]},
    )


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("mail")))
    lb.retract(int(line["seq"]), "not mine")


def _resolution(lb: Logbook) -> None:
    lb.append(**resolution(("email", "post@robaat.example.org"), str(KARI["id"]), "Kari at Robåt"))


@pytest.mark.parametrize("change", [_earlier_month, _correction, _retraction, _resolution])
def test_what_a_kept_reading_cannot_carry_reads_every_line(
    lb: Logbook, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same(lb)
    lb.append_many(_days()[0])
    change(lb)
    whole = Whole(monkeypatch)
    assert _same(lb, whole) == 1 + len(GATES), "the observed orgs and each gate's touches, every line"


def test_a_newly_named_org_reads_every_touch_again(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _same(lb)
    lb.append_many(_days()[0])
    report = entity_review.read(lb, "org")
    [p] = [p for p in report.proposals if p.new and p.observed.key == ("domain", "robaat.example.org")]
    entity_review.accept(lb, report, [(p, "Nordmann Robåt")])
    lb.append_many(_days()[1])
    whole = Whole(monkeypatch)
    assert _same(lb, whole) == len(GATES), "the observed orgs read on; every touch read again"
    record = orgs.read(lb, orgs.gate())
    [robaat] = [i for i, e in record.orgs.items() if e.label == "Nordmann Robåt"]
    assert record.touches_of(robaat), "its mail of August touches it"
