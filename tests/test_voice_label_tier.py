"""A voice's name keeps the tier of the lines it was learned from (RFC 0038 §3.4, the review of the
11th sitting). An attribution binds a voice to a person; the name a reader shows for that voice is
the person's label, which a resolution line gives. When every line that gives it is above the
reading's tiers, the reader shows `a named voice` in its place: the voice is someone's, and who is
not for this reading. The highest tier of the lines that give the name decides, as the owner set it.
Synthetic Oslo persona: Per Hansen, whose name only a tier-3 line gives, speaks at dinner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cabin import SAT, TRIP, ola_record
from persona import HOME, TZ, dwell, utc
from speakers_record import DINNER, DINNER_DAY, ROOM, attribution, resolution, transcript

from logbook import cli
from logbook.contrib import serve
from logbook.core import attribution as voices_of
from logbook.core import day as day_reader
from logbook.core import resolve
from logbook.core.store import Logbook

PER_ID = "019cadd3-6bc0-7dcd-9133-000000000405"
PER_NAME = "Per Hansen"
PER_EMAIL = "per@example.org"


def _per(tier: int, ref: tuple[str, str] = ("email", PER_EMAIL)) -> dict[str, Any]:
    line = resolution(ref, PER_ID, PER_NAME)
    line["tier"] = tier
    return line


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The dinner of 3 October at home, its second voice bound to Per by a tier-2 attribution that
    carries no name; Per's name is given by one resolution line, at tier 3."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _per(3),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S2", PER_ID),
        ]
    )
    return lb


def _heard(lb: Logbook, tiers: tuple[int, ...] | None) -> voices_of.Heard:
    with lb.index() as idx:
        identities = resolve.identities_from([*idx.retractions(), *idx.resolutions()])
    owner = str(lb.meta["owner_id"])
    line = next(line for line in lb.lines() if line.get("id") == DINNER)
    found = {h.label: h for h in voices_of.Voices(identities, (owner,), owner, tiers).of(line)}
    return found["S2"]


def test_an_identity_carries_the_tier_of_the_line_that_gives_its_label(lb: Logbook) -> None:
    with lb.index() as idx:
        identities = resolve.identities_from(list(idx.resolutions()))
    assert identities[("email", PER_EMAIL)].tier == 3
    assert identities[("speaker", f"{DINNER}#S2")].tier == 2


def test_at_tier_2_the_voice_is_a_named_voice_and_its_name_is_nowhere(lb: Logbook) -> None:
    heard = _heard(lb, (1, 2))
    assert heard.state == voices_of.PERSON and heard.entity == PER_ID
    assert heard.name is None and heard.withheld
    assert heard.shown == voices_of.NAMED_VOICE == "a named voice"
    assert heard.to_json()["name"] == "a named voice"
    assert heard.to_json()["person"] == PER_ID  # the binding stands; only the name is held back


@pytest.mark.parametrize("tiers", [(1, 2, 3), None])
def test_at_tier_3_or_with_no_gate_the_voice_is_named(lb: Logbook, tiers: tuple[int, ...] | None) -> None:
    heard = _heard(lb, tiers)
    assert heard.name == PER_NAME and not heard.withheld
    assert heard.shown == PER_NAME and heard.to_json()["name"] == PER_NAME


def test_the_highest_tier_of_the_lines_that_give_the_name_decides(lb: Logbook) -> None:
    """A tier-2 line gives the same name too: one of the lines it was learned from is still tier 3,
    so a tier-2 reading still shows `a named voice` (the owner's rule: the highest tier decides)."""
    lb.append(**_per(2, ("phone", "+447700900105")))
    assert _heard(lb, (1, 2)).shown == voices_of.NAMED_VOICE
    assert _heard(lb, (1, 2, 3)).shown == PER_NAME


def test_a_name_learned_at_tier_2_shows_at_tier_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = Logbook.init(tmp_path / "lb2", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _per(2),
            transcript(DINNER, utc(DINNER_DAY, "19:40"), utc(DINNER_DAY, "20:52"), "Middag", ROOM),
            attribution(DINNER, "S2", PER_ID),
        ]
    )
    assert _heard(lb, (1, 2)).shown == PER_NAME
    assert _heard(lb, (1,)).shown == voices_of.NAMED_VOICE  # the name's line is tier 2


@pytest.mark.parametrize("tiers", [(1, 2), (1, 2, 3)])
def test_the_day_shows_a_named_voice_below_the_names_tier_and_the_name_at_it(
    lb: Logbook, tiers: tuple[int, ...]
) -> None:
    """The Day (`--json`, its text rows, `serve`'s Day page, which a tier-1,2 site renders): below
    tier 3 the voice is `a named voice` and Per's name is on no part of it, his company included;
    at tier 3 it is his name."""
    data = day_reader.read(lb, DINNER_DAY, tiers=tiers)
    whole = json.dumps(data, ensure_ascii=False)
    text = "\n".join(day_reader.rows(data))
    page = serve.Site(lb, tiers=tiers, href=lambda _path: None).page_day(DINNER_DAY)  # static, as a site
    voices = [s for item in _transcripts(data) for s in item["speakers"] if s["label"] == "S2"]
    if 3 in tiers:
        assert [v["name"] for v in voices] == [PER_NAME]
        assert f"Middag · S1 · {PER_NAME} · S3" in text and "min" not in _row(text) and PER_NAME in page
    else:
        assert [v["name"] for v in voices] == [voices_of.NAMED_VOICE]
        assert f"Middag · S1 · {voices_of.NAMED_VOICE} · S3" in text and voices_of.NAMED_VOICE in page
        assert PER_NAME not in whole and PER_NAME not in text and PER_NAME not in page


def _row(text: str) -> str:
    """The Day's row of the dinner: its voices, never a time beside one (RFC 0043)."""
    return next(row for row in text.splitlines() if "Middag" in row)


def _transcripts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Every transcript entry of the Day, under a stay or unplaced."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("speakers"), list):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


# -- the exports that read the record whole and gate line by line, and the line's own participants ----


def _hits(folder: Path) -> list[str]:
    """The files under `folder` whose text carries Per's name."""
    found = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if PER_NAME in text:
                found.append(path.relative_to(folder).as_posix())
    return found


@pytest.mark.parametrize("target", ["vault", "site"])
def test_a_tier_1_2_vault_or_site_names_nobody_from_the_voice(
    lb: Logbook, tmp_path: Path, target: str
) -> None:
    """The vault reads the record whole and gates each line it shows; the site reads through the
    gate. Either way the tier-2 transcript crosses and Per's name, given only at tier 3, does not:
    not as the voice, not as company, not as a person's page."""
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"vault": {"max_tier": 2}, "site": {"max_tier": 2}}), encoding="utf-8")
    folder = tmp_path / target
    cli.main(["export", target, str(folder), "--tier", "1,2"])
    assert _hits(folder) == []


def test_a_tier_1_2_trip_bundle_names_nobody_from_the_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ola's weekend at the cabin (`cabin.py`), Per speaking at dinner on the Saturday: the bundle
    reads the trip whole and sends its lines through `--tier 1,2`, and its people rows leave him out."""
    ola = ola_record(tmp_path)
    monkeypatch.setenv("LOGBOOK_HOME", str(ola.root))
    ola.append_many(
        [
            _per(3),
            transcript(DINNER, utc(SAT, "18:00"), utc(SAT, "19:00"), "Middag", ROOM),
            attribution(DINNER, "S2", PER_ID),
        ]
    )
    out = tmp_path / "bundle"
    cli.main(["export", "trip-bundle", TRIP, "--to", "ines", "--tier", "1,2", "--out", str(out)])
    assert _hits(out) == []


def test_a_withheld_voice_is_not_named_again_by_its_lines_participants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript lists Per among its participants by his address, which the tier-3 line
    resolves: the voice is read first, and a voice held back keeps its line from naming him."""
    lb = Logbook.init(tmp_path / "lb3", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(
        [
            _per(3),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            transcript(
                DINNER,
                utc(DINNER_DAY, "19:40"),
                utc(DINNER_DAY, "20:52"),
                "Middag",
                ROOM,
                participants=[{"email": PER_EMAIL, "name": "Per"}],
            ),
            attribution(DINNER, "S2", PER_ID),
        ]
    )
    gated = day_reader.read(lb, DINNER_DAY, tiers=(1, 2))
    assert PER_NAME not in json.dumps(gated, ensure_ascii=False)
    assert PER_NAME not in "\n".join(day_reader.rows(gated))
    whole = day_reader.read(lb, DINNER_DAY, tiers=(1, 2, 3))
    assert f"{PER_NAME} (transcript)" in "\n".join(day_reader.rows(whole))
