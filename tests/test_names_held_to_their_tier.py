"""A name is held to the tier of the line it is learned from (the review of 26 October, R1, and the
owner's ruling of 27 October). The people overlay is the record's resolution lines; an export at
`--tier 1` or `--tier 1,2` builds it from the resolution lines at its own tiers, so a name only a
tier-3 line gives is in no vault, no site and no trip bundle below tier 3, nor that line's id, nor a
count of the person it names; and a name only a tier-2 line gives is in none at tier 1. The Oslo
persona's fortnight (`persona.py`), whose people are named by tier-2 resolutions (Kari also by her
tier-1 calendar entry's own attendee name), with one more dinner in Zürich, on Wednesday 17 June,
whose tier-1 calendar entry lists per.hemmelig@example.org: only a tier-3 `resolution/v1` line names
that address "Per Hemmelig". Nobody here exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import OLA_ID, attendee, event, persona_record, resolution, utc

from logbook import cli
from logbook.core import reading
from logbook.core.store import Logbook

PER = "Per Hemmelig"
PER_EMAIL = "per.hemmelig@example.org"
PER_ID = "019cadd3-6bc0-7dcd-9133-0000000003e3"
DINNER_DAY = "2026-06-17"  # the hotel in Zürich, the second night of the trip
TRIP = "trip:2026-06-15:2026-06-17"
TIERS = ["1", "1,2"]


def _secret() -> dict[str, Any]:
    line = resolution(("email", PER_EMAIL), PER_ID, PER)
    line["tier"] = 3
    return line


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The fortnight, Per's tier-3 name and the tier-1 dinner that lists his address, and a crossing
    policy that lets tier 2 go to the vault, the site and `ines`."""
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [
            _secret(),
            event(utc(DINNER_DAY, "18:00"), utc(DINNER_DAY, "21:00"), "Dinner", [attendee(PER_EMAIL)]),
        ]
    )
    path = lb.root / "policy" / "crossing.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update({"vault": {"max_tier": 2}, "site": {"max_tier": 2}, "ines": {"max_tier": 2}})
    path.write_text(json.dumps(data), encoding="utf-8")
    return Logbook(lb.root)


def _secret_id(lb: Logbook) -> str:
    return next(str(line["id"]) for line in lb.lines() if line.get("tier") == 3)


def _texts(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): p.read_text(encoding="utf-8")
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.suffix in {".md", ".html", ".json"}
    }


def _nowhere(lb: Logbook, folder: Path, tiers: str) -> None:
    """Per is in no file; at tier 1 neither is Ola, whom only tier-2 lines name, nor his entity."""
    secret = _secret_id(lb)
    for name, text in _texts(folder).items():
        assert PER not in text, name
        assert PER_ID not in text, name
        assert secret not in text, name
        if tiers == "1":
            assert "Ola Nordmann" not in text, name
            assert OLA_ID not in text, name


def test_the_name_is_there_with_no_gate(lb: Logbook) -> None:
    """The record is as the test means it: read whole, the dinner names Per Hemmelig."""
    rd = reading.read(lb, DINNER_DAY, DINNER_DAY)
    assert rd.names[("email", PER_EMAIL)] == PER
    gated = reading.read(lb, DINNER_DAY, DINNER_DAY, tiers=(1, 2))
    assert ("email", PER_EMAIL) not in gated.names
    assert ("email", PER_EMAIL) not in gated.identities
    assert gated.names[("email", "ola@example.org")] == "Ola Nordmann", "a tier-2 name at tier 2"
    one = reading.read(lb, DINNER_DAY, DINNER_DAY, tiers=(1,))
    assert ("email", "ola@example.org") not in one.names, "and never at tier 1"


@pytest.mark.parametrize("tiers", TIERS)
def test_the_vault_never_names_a_person_only_a_tier_3_line_names(
    lb: Logbook, tmp_path: Path, tiers: str
) -> None:
    folder = tmp_path / "Vault"
    cli.main(["export", "vault", str(folder), "--tier", tiers])
    _nowhere(lb, folder, tiers)
    people = sorted(p.stem for p in (folder / "people").glob("*.md"))
    assert people == (["Kari Nordmann"] if tiers == "1" else ["Kari Nordmann", "Ola Nordmann"])


@pytest.mark.parametrize("tiers", TIERS)
def test_the_site_never_names_a_person_only_a_tier_3_line_names(
    lb: Logbook, tmp_path: Path, tiers: str
) -> None:
    folder = tmp_path / "Site"
    cli.main(["export", "site", str(folder), "--tier", tiers])
    _nowhere(lb, folder, tiers)
    assert not [p for p in (folder / "people").glob("*.html") if "hemmelig" in p.name.casefold()]


@pytest.mark.parametrize("tiers", TIERS)
def test_the_trip_bundle_never_names_counts_or_cites_a_person_only_a_tier_3_line_names(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], tiers: str
) -> None:
    folder = tmp_path / "bundle"
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", tiers, "--out", str(folder)])
    capsys.readouterr()
    _nowhere(lb, folder, tiers)
    share = json.loads((folder / "trip.json").read_text(encoding="utf-8"))
    assert PER_EMAIL not in json.dumps(share), "an address nobody below tier 3 names is left out"
    held = share["held_back"]["people"]
    if tiers == "1":
        assert held == 0, "Ola at Tuesday's dinner is named by tier-2 lines only: nobody at tier 1"
        assert share["people"] == []
    else:
        assert held == 0
        assert [p["name"] for p in share["people"]] == ["Ola Nordmann"]


def test_a_tier_3_line_that_repeats_a_tier_2_name_takes_nothing_away(lb: Logbook) -> None:
    """Ola's name is learned at tier 2; a tier-3 line that binds another of his refs to the same name
    adds nothing a gate below tier 3 may show, and takes nothing away either."""
    repeat = resolution(("phone", "+447700900123"), OLA_ID, "Ola Nordmann")
    repeat["tier"] = 3
    lb.append(**repeat)
    rd = reading.read(Logbook(lb.root), DINNER_DAY, DINNER_DAY, tiers=(1, 2))
    assert rd.names[("email", "ola@example.org")] == "Ola Nordmann"
    assert ("phone", "+447700900123") not in rd.names
