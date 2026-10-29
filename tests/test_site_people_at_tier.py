"""The site's people pages through each gate, on a small synthetic record (fast, not slow-tier).

One evening at home with a timed dinner: three guests on a tier-1 calendar entry that gives their
addresses and no names. Kari Nordmann is named by a tier-1 resolution, Ola Nordmann by a tier-2 one
only, and Per Hemmelig by a tier-3 one only. A tier-1 site names a person only from the resolutions
at its tiers (the owner, 27 October: #422, #425): Kari has a page, Ola none. A tier-1,2 site names
both, and Per Hemmelig at neither. `test_names_held_to_their_tier.py` checks that a name above the
gate is nowhere; this checks the pages themselves, the people a gate does name included, on a
pull request, where the slow forty-year test does not run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from persona import HOME, KARI, KARI_ID, OLA, OLA_ID, TZ, attendee, dwell, event, resolution, utc

from logbook import cli
from logbook.core import reading
from logbook.core.store import Logbook

DAY, NEXT = "2026-06-12", "2026-06-13"
PER_EMAIL = "per.hemmelig@example.org"
PER_ID = "019cadd3-6bc0-7dcd-9133-000000000003"
NAMES = {"kari-nordmann": "Kari Nordmann", "ola-nordmann": "Ola Nordmann", "per-hemmelig": "Per Hemmelig"}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            {**resolution(("email", KARI["email"]), KARI_ID, NAMES["kari-nordmann"]), "tier": 1},
            resolution(("email", OLA["email"]), OLA_ID, NAMES["ola-nordmann"]),
            {**resolution(("email", PER_EMAIL), PER_ID, NAMES["per-hemmelig"]), "tier": 3},
            *dwell(DAY, "08:00", "24:00", HOME),
            *dwell(NEXT, "00:00", "12:00", HOME),
            event(
                utc(DAY, "18:00"),
                utc(DAY, "21:00"),
                "Dinner",
                [attendee(KARI["email"]), attendee(OLA["email"]), attendee(PER_EMAIL)],
            ),
        ]
    )
    places = {"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}
    (lb.root / "places.json").write_text(json.dumps(places), encoding="utf-8")
    return lb


def _export(lb: Logbook, folder: Path, tiers: str) -> dict[str, str]:
    if tiers != "1":
        policy = lb.root / "policy" / "crossing.json"
        policy.parent.mkdir(exist_ok=True)
        top = max(map(int, tiers.split(",")))
        policy.write_text(json.dumps({"site": {"max_tier": top}}), encoding="utf-8")
    cli.main(["export", "site", str(folder), "--tier", tiers])
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in folder.rglob("*.html")}


def test_with_no_gate_the_record_names_all_three(lb: Logbook) -> None:
    """The control: each guest is named by the record, so a page left out is the gate's doing."""
    names = reading.read(lb, DAY, NEXT).names
    assert {names.get(("email", e)) for e in (KARI["email"], OLA["email"], PER_EMAIL)} == set(NAMES.values())


@pytest.mark.parametrize(
    ("tiers", "named"),
    [("1", {"kari-nordmann"}), ("1,2", {"kari-nordmann", "ola-nordmann"})],
)
def test_the_people_pages_are_those_the_gate_names(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], tiers: str, named: set[str]
) -> None:
    pages = _export(lb, tmp_path / f"site-{tiers.replace(',', '-')}", tiers)
    capsys.readouterr()
    people = {Path(p).stem for p in pages if Path(p).parts[0] == "people"}
    assert people == named
    whole = "\n".join(pages.values())
    for slug, name in NAMES.items():
        assert (name in whole) == (slug in named), (tiers, name)
    assert "Hemmelig" not in whole and PER_ID not in whole
    if "ola-nordmann" not in named:
        assert OLA_ID not in whole
    index = pages["people.html"]
    for slug in named:
        assert f'href="people/{slug}.html"' in index, (tiers, slug)
