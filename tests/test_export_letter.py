"""`logbook export letter FROM TO`: a range of signed days read back as one HTML file and the same
content as Markdown, for print or for someone, and the month card (`--unit month --card`). A crossing
like every export: the `letter` entry of the policy, its ceiling on every line, tier 3 never by
default, a manifest of counts and one `crossing/v1` line. On the synthetic fortnight of
`tests/letter_record.py`: Ines Nordmann of Oslo, Kari and Ola Nordmann, who do not exist."""

from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import paper
import phone_width
import pytest
from dream_fortnight import JOURNEY, MODEL, NOTE_ZURICH, run_cli
from letter_record import (
    CAMERA,
    DINNER_NOTE,
    DOOR_REFLECTION,
    FOR,
    FROM,
    JOURNEY_STORY,
    LETTER_ENTRY,
    MONTH_SENTENCE,
    REFLECTIONS,
    STORY,
    TO,
    UNSIGNED,
    UNSIGNED_WORDS,
    WEEK_ONE_STORY,
    WEEK_STORY,
    WORKOUT_NOTE,
    record,
    set_policy,
)

from logbook.contrib import letter
from logbook.core import crossing, stars
from logbook.core.store import Logbook


def _export(lb: Logbook, out: Path, *flags: str) -> tuple[int, str, str]:
    return run_cli("export", "letter", FROM, TO, "--out", str(out), *flags)


def _files(out: Path) -> tuple[str, str, dict[str, object]]:
    html = (out / letter.HTML_FILE).read_text(encoding="utf-8")
    md = (out / letter.MARKDOWN_FILE).read_text(encoding="utf-8")
    manifest = json.loads((out / letter.MANIFEST_FILE).read_text(encoding="utf-8"))
    return html, md, manifest


class _Units(HTMLParser):
    """The units of a letter's HTML, in order: the text of each `h2` inside a `section.unit`."""

    def __init__(self) -> None:
        super().__init__()
        self.units: list[str] = []
        self._in: bool = False
        self._sections: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "section":
            self._sections.append(dict(attrs).get("class") or "")
        if tag == "h2" and self._sections and "unit" in self._sections[-1].split():
            self._in = True
            self.units.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._sections:
            self._sections.pop()
        if tag == "h2":
            self._in = False

    def handle_data(self, data: str) -> None:
        if self._in:
            self.units[-1] += data


def _html_units(html: str) -> list[str]:
    parser = _Units()
    parser.feed(html)
    return [" ".join(u.split()) for u in parser.units]


def _md_units(md: str) -> list[str]:
    return [" ".join(line[3:].split()) for line in md.splitlines() if line.startswith("## ")]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return record(tmp_path, monkeypatch)


def test_only_signed_days_go_in_unless_unsigned(lb: Logbook, tmp_path: Path) -> None:
    """Friday 12 June is not signed: its reflection, its draft and its photo stay home, and the
    manifest counts the day; `--unsigned` lets it in."""
    code, _, err = _export(lb, tmp_path / "out", "--to", FOR)
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "out")
    for text in (html, md):
        assert UNSIGNED_WORDS not in text
        assert f"{STORY} {UNSIGNED}." not in text
        assert "IMG_FRIDAY" not in text.replace("\\_", "_")
        assert "The dinner ran late" in text  # a signed day's reflection is there
    assert manifest["days"] == {"in": 13, "unsigned": 1}
    assert manifest["signed_only"] is True

    code, _, err = _export(lb, tmp_path / "all", "--to", FOR, "--unsigned")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "all")
    assert UNSIGNED_WORDS in html and UNSIGNED_WORDS in md
    assert manifest["days"] == {"in": 14, "unsigned": 0}
    assert manifest["signed_only"] is False


def test_the_tier_ceiling_holds_every_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Under `max_tier` 1 the owner's words, the model's draft and the names (tier 2) stay home and
    are counted; the dinner (tier 1) and its star go. Tier 3 never goes by default, not even under
    an entry of 3; `--tier 1,2,3` takes it under that entry and is refused under a lower one."""
    lb = record(tmp_path, monkeypatch, {"max_tier": 1})
    code, _, err = _export(lb, tmp_path / "one")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "one")
    for text in (html, md):
        assert "The dinner ran late" not in text
        assert STORY not in text
        assert NOTE_ZURICH not in text
        assert "Ola Nordmann" not in text and "Kari Nordmann" not in text
        assert "Dinner" in text and DINNER_NOTE in text  # a star is at its line's tier: tier 1 here
    assert manifest["tiers"] == [1]
    assert manifest["held_back"]["above_tier"] > 0

    set_policy(lb.root, {"max_tier": 3})
    code, _, err = _export(lb, tmp_path / "three")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "three")
    assert WORKOUT_NOTE not in html and WORKOUT_NOTE not in md
    assert manifest["tiers"] == [1, 2]

    code, _, err = _export(lb, tmp_path / "with-three", "--tier", "1,2,3")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "with-three")
    assert WORKOUT_NOTE in html and WORKOUT_NOTE in md
    assert manifest["tiers"] == [1, 2, 3]

    set_policy(lb.root, LETTER_ENTRY)
    code, _, err = _export(lb, tmp_path / "refused", "--tier", "1,2,3")
    assert code == 2
    assert "max_tier" in err and not (tmp_path / "refused").exists()


def test_without_the_entry_it_refuses_in_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = record(tmp_path, monkeypatch, None)
    seq = int(lb.meta["seq"])
    code, _, err = _export(lb, tmp_path / "out", "--to", FOR)
    assert code == 2
    message = err.strip()
    assert "\n" not in message and ". " not in message  # one sentence
    assert '"letter"' in message and "max_tier" in message
    assert not (tmp_path / "out").exists()
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_an_expired_entry_lets_nothing_leave(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = record(tmp_path, monkeypatch, {"max_tier": 2, "until": "2026-06-20"})
    code, _, err = _export(lb, tmp_path / "out")
    assert code == 2
    assert "expired on 2026-06-20" in err
    assert not (tmp_path / "out").exists()


def test_the_markdown_and_the_html_carry_the_same_units(lb: Logbook, tmp_path: Path) -> None:
    for unit, count in (("day", 13), ("week", 2), ("month", 1), ("journey", 1)):
        out = tmp_path / unit
        code, _, err = _export(lb, out, "--unit", unit)
        assert code == 0, err
        html, md, manifest = _files(out)
        units = _html_units(html)
        assert units == _md_units(md)
        assert len(units) == count, (unit, units)
        assert manifest["units"] == {"unit": unit, "count": count}
        assert html.count('class="unit') == count


def test_a_unit_s_parts_are_its_draft_its_words_its_stars_and_its_people(lb: Logbook, tmp_path: Path) -> None:
    """A day: the dream's story in pencil with its model's name, the reflection in ink, the starred
    lines and photos, the reviews of the day, the people by name, the places and the route."""
    front = tmp_path / "front.md"
    front.write_text(
        "Dear Kari,\n\nThese are our two weeks in June & what they held.\n\n— Ines\n", encoding="utf-8"
    )
    code, _, err = _export(
        lb, tmp_path / "out", "--to", FOR, "--title", "June, for Kari", "--front", str(front)
    )
    assert code == 0, err
    html, md, _ = _files(tmp_path / "out")
    assert "These are our two weeks in June &amp; what they held." in html
    assert "These are our two weeks in June & what they held." in md
    assert "<title>June, for Kari</title>" in html
    assert md.startswith("# June, for Kari\n")
    pencil = re.search(r'<div class="pencil"[^>]*>(.*?)</div>', html, re.S)
    assert pencil is not None and MODEL in pencil.group(1) and "model" in pencil.group(1)
    assert f"{STORY} 2026-06-16." in html and "The berth." not in html  # the story, not the threads
    assert 'class="ink"' in html
    assert REFLECTIONS["2026-06-16"] in md
    assert DINNER_NOTE in html and DINNER_NOTE in md
    assert NOTE_ZURICH in html
    assert "Ola Nordmann" in html and "Ola Nordmann" in md
    assert "advancing" in html and "Two days on the water." in md
    assert "Zurich" in html or "Zürich" in html
    assert "OSL → ZRH" in html and "OSL → ZRH" in md


def test_week_and_journey_units_carry_their_own_drafts(lb: Logbook, tmp_path: Path) -> None:
    code, _, err = _export(lb, tmp_path / "week", "--unit", "week")
    assert code == 0, err
    html, md, _ = _files(tmp_path / "week")
    assert WEEK_STORY in html and WEEK_STORY in md
    code, _, err = _export(lb, tmp_path / "journey", "--unit", "journey")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "journey")
    assert JOURNEY_STORY in html and JOURNEY_STORY in md
    assert manifest["units"] == {"unit": "journey", "count": 1}
    assert JOURNEY in json.dumps(manifest)


def test_photos_are_thumbnails_under_the_cap_never_the_originals(lb: Logbook, tmp_path: Path) -> None:
    code, _, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        [letter.HTML_FILE, letter.MARKDOWN_FILE, letter.MANIFEST_FILE]
    )
    images = re.findall(r'<img src="(data:image/[a-z]+;base64,[A-Za-z0-9+/=]+)"', html)
    assert len(images) == 2  # Saturday's PNG and the lake: the big one is named, the HEIC too
    assert all(len(src) < letter.PHOTO_MAX_BYTES * 2 for src in images)
    assert "IMG_BIG.JPG" in html and "IMG\\_BIG.JPG" in md
    for src in images:  # what the camera wrote beside the pixels stays home
        raw = base64.b64decode(src.split(",", 1)[1])
        assert CAMERA not in raw and raw.startswith((b"\xff\xd8", b"\x89PNG"))
    assert manifest["photos"] == {"embedded": 2, "named": 2}
    assert md.count("](data:image/") == 2


def test_the_month_card_is_one_page_and_nothing_else(lb: Logbook, tmp_path: Path) -> None:
    code, _, err = _export(lb, tmp_path / "card", "--unit", "month", "--card", "--to", FOR)
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "card")
    assert html.count('<section class="unit card"') == 1
    assert _html_units(html) == _md_units(md) == ["June 2026"]
    card = html[html.index('<section class="unit card"') :]
    assert card.count("<img ") == 2  # one photo per starred day the store holds
    assert "13 days signed" in re.sub(r"<[^>]*>", "", card) and "13 days signed" in md
    assert "Read one book a month." in card  # the goal kept: reviewed done in the month
    assert "Sail to Lofoten" not in card  # advancing is not kept
    assert "Ola Nordmann" in card and "Kari Nordmann" in card
    assert MONTH_SENTENCE in card and MONTH_SENTENCE in md
    assert "Ola laughed" not in card  # one sentence only
    for absent in (STORY, DINNER_NOTE, "advancing", "OSL → ZRH", "pencil"):
        assert absent not in card, absent
    assert manifest["card"] is True


def test_the_crossing_line_says_it_left_and_for_whom(lb: Logbook, tmp_path: Path) -> None:
    seq = int(lb.meta["seq"])
    code, out_text, err = _export(lb, tmp_path / "out", "--to", FOR)
    assert code == 0, err
    _, _, manifest = _files(tmp_path / "out")
    lines = list(Logbook(lb.root).lines())
    assert int(Logbook(lb.root).meta["seq"]) == seq + 1
    line = lines[-1]
    assert (line["kind"], line["source"]) == (crossing.KIND, crossing.SOURCE)
    payload = line["payload"]
    assert payload["schema"] == crossing.LINE_SCHEMA
    assert payload["destination"] == letter.DESTINATION
    assert payload["extra"]["letter"]["to"] == FOR
    assert payload["policy"]["max_tier"] == 2
    assert line["tier"] == 2  # it names the person it is for: a name is tier 2 (the owner's answer)
    assert manifest["to"] == FOR
    assert manifest["export_id"] == payload["bundle_id"]
    assert f"#{line['seq']}" in out_text
    for key in ("units", "days", "photos", "held_back"):
        assert key in manifest
    assert all(isinstance(v, int) for v in manifest["held_back"].values())


def test_a_letter_for_nobody_named_is_recorded_at_tier_1(lb: Logbook, tmp_path: Path) -> None:
    """Without `--to` the crossing line names no one and is tier 1, as every export's line."""
    code, _, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    line = list(Logbook(lb.root).lines())[-1]
    assert (line["kind"], line["payload"]["destination"]) == (crossing.KIND, letter.DESTINATION)
    assert line["payload"]["extra"]["letter"]["to"] is None
    assert line["tier"] == 1


def test_nothing_is_fetched_and_no_script(lb: Logbook, tmp_path: Path, no_network: list[str]) -> None:
    code, _, err = _export(lb, tmp_path / "out", "--paper", "letter")
    assert code == 0, err
    assert no_network == []
    html, md, _ = _files(tmp_path / "out")
    assert "<script" not in html.lower()
    assert re.search(r"\bon[a-z]+\s*=", html) is None  # no handler attribute either
    assert re.search(r"(src|href)\s*=\s*\"(?!data:|#)", html) is None
    assert "@import" not in html and "url(" not in html
    assert "http://" not in html and "https://" not in html
    assert "http://" not in md and "https://" not in md
    assert "size: letter" in html
    paper.structure(re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "data:", html), images=True)
    code, _, err = _export(lb, tmp_path / "a5")
    assert code == 0, err
    assert "size: A5" in (tmp_path / "a5" / letter.HTML_FILE).read_text(encoding="utf-8")


def test_no_number_beside_a_person_s_name(lb: Logbook, tmp_path: Path) -> None:
    for flags in ((), ("--unit", "week"), ("--unit", "month", "--card")):
        out = tmp_path / "-".join(flags or ("day",))
        code, _, err = _export(lb, out, *flags)
        assert code == 0, err
        html, md, _ = _files(out)
        for text in (html, md):
            for name in ("Ola Nordmann", "Kari Nordmann"):
                for found in re.finditer(re.escape(name), text):
                    near = text[max(0, found.start() - 12) : found.end() + 12]
                    assert re.search(r"\d", re.sub(r"<[^>]*>", "", near)) is None, near


def test_a_refused_target_writes_nothing(lb: Logbook, tmp_path: Path) -> None:
    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "keep.txt").write_text("mine", encoding="utf-8")
    seq = int(lb.meta["seq"])
    code, _, err = _export(lb, taken)
    assert code == 2 and "--force" in err
    assert (taken / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_the_range_and_the_flags_are_checked(lb: Logbook, tmp_path: Path) -> None:
    code, _, err = run_cli("export", "letter", TO, FROM, "--out", str(tmp_path / "x"))
    assert code == 2 and "after" in err
    code, _, err = run_cli("export", "letter", FROM, "--out", str(tmp_path / "x"))
    assert code == 2 and "FROM TO" in err
    code, _, err = _export(lb, tmp_path / "x", "--card")
    assert code == 2 and "--unit month" in err
    code, _, err = _export(lb, tmp_path / "x", "--front", str(tmp_path / "missing.md"))
    assert code == 2 and "missing.md" in err
    assert not (tmp_path / "x").exists()


def test_it_reads_at_phone_width(lb: Logbook, tmp_path: Path) -> None:
    """Phone width first: no element of the letter or of the card needs more than a phone's column."""
    for flags in ((), ("--unit", "month", "--card")):
        out = tmp_path / "-".join(flags or ("day",))
        code, _, err = _export(lb, out, *flags)
        assert code == 0, err
        html = (out / letter.HTML_FILE).read_text(encoding="utf-8")
        screen = re.sub(r"@page \{[^}]*\}", "", html)  # the paper's rule: a phone never applies it
        assert phone_width.problems(screen) == []


def test_a_draft_of_a_week_with_an_unsigned_day_stays_home(lb: Logbook, tmp_path: Path) -> None:
    """W24's draft rests on the unsigned Friday: under signed-only its week goes without a story and
    the manifest counts it; with `--unsigned` every day of the week goes in, and so does its story."""
    code, _, err = _export(lb, tmp_path / "signed", "--unit", "week")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "signed")
    for text in (html, md):
        assert UNSIGNED_WORDS not in text and WEEK_ONE_STORY not in text
        assert WEEK_STORY in text
    assert manifest["held_back"]["stories_beyond_the_letter"] == 1
    code, _, err = _export(lb, tmp_path / "all", "--unit", "week", "--unsigned")
    assert code == 0, err
    html, _, _ = _files(tmp_path / "all")
    assert WEEK_ONE_STORY in html


def test_a_reflection_through_the_door_is_not_set_in_ink(lb: Logbook, tmp_path: Path) -> None:
    """A reflection an agent wrote through the door (`note_day`, source `mcp`) is shown as the Day shows
    it, with its source, and never in ink; the month card's sentence is chosen from her own hand only."""
    code, _, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    html, md, _ = _files(tmp_path / "out")
    inks = re.findall(r'<div class="ink">(.*?)</div>', html, re.S)
    assert inks and not any("An agent wrote this" in ink for ink in inks)
    assert "An agent wrote this through the door" in html and "through mcp" in html
    assert "*through mcp*" in md
    code, _, err = _export(lb, tmp_path / "card", "--unit", "month", "--card")
    assert code == 0, err
    html, md, _ = _files(tmp_path / "card")
    assert DOOR_REFLECTION.split(".")[0] not in html and MONTH_SENTENCE in html


def test_the_markdown_carries_no_markup_from_the_record(lb: Logbook, tmp_path: Path) -> None:
    """A star's note is the owner's text, a photo's name an adapter's, a model's name the runner's: the
    letter shows each as text, in the HTML escaped and in the Markdown neither a tag nor a heading."""
    dinner = next(
        line for line in lb.lines() if line["kind"] == "event" and line["payload"]["title"] == "Dinner"
    )
    stars.star(lb, str(dinner["id"]), "<img src=x onerror=alert(1)> ## not a heading")
    code, _, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    html, md, _ = _files(tmp_path / "out")
    assert "&lt;img src=x onerror=alert(1)&gt;" in html and "<img src=x" not in html
    assert re.search(r"(?<!\\)[<>]", md.replace("\n> ", "\n")) is None  # every < and > escaped: text
    assert _md_units(md) == _html_units(html)


def test_a_letter_with_no_page_is_refused_and_nothing_written(lb: Logbook, tmp_path: Path) -> None:
    seq = int(lb.meta["seq"])
    code, _, err = run_cli("export", "letter", UNSIGNED, UNSIGNED, "--out", str(tmp_path / "out"))
    assert code == 2 and "no signed day" in err
    assert not (tmp_path / "out").exists()
    assert int(Logbook(lb.root).meta["seq"]) == seq


def test_the_default_folder_is_the_range_and_the_shape(lb: Logbook) -> None:
    day = letter.request(lb, FROM, TO)
    card = letter.request(lb, FROM, TO, unit="month", card=True)
    assert letter.default_out(lb, day).parts[-3:] == ("export", "letter", f"{FROM}_{TO}_day")
    assert letter.default_out(lb, card).name == f"{FROM}_{TO}_month_card"


def test_strip_keeps_the_pixels_and_refuses_what_it_cannot_read() -> None:
    from letter_record import jpeg, png

    stripped = letter.strip(jpeg(b"\x10\x20"), "image/jpeg")
    assert stripped is not None and CAMERA not in stripped and stripped.endswith(b"\x10\x20\xff\xd9")
    stripped = letter.strip(png(), "image/png")
    assert stripped is not None and CAMERA not in stripped and stripped.endswith(b"IEND\xaeB`\x82")
    assert letter.strip(b"\xff\xd8\xff\xe1\x00", "image/jpeg") is None  # a segment cut short
    assert letter.strip(b"GIF89a" + b"\x00" * 20, "image/gif") is None  # a type it does not strip


DRAFTED_SIGNED_DAYS = 9  # the day drafts of 8 to 17 June, the unsigned Friday aside


def test_drafts_above_the_letter_s_tier_are_counted_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a `letter` entry of 1 the day drafts (tier 2) stay home by the letter's own ceiling: the
    manifest and the console say `drafts_above_tier`, and nothing of them is in the letter."""
    lb = record(tmp_path, monkeypatch, {"max_tier": 1})
    code, out_text, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "out")
    held = manifest["held_back"]
    assert held["drafts_above_tier"] == DRAFTED_SIGNED_DAYS
    assert held.get("drafts_held_by_the_dream_entry", 0) == 0
    assert f"{DRAFTED_SIGNED_DAYS} drafts above tier 1" in out_text
    assert "the dream entry holds" not in out_text
    assert STORY not in html and STORY not in md


def test_drafts_the_dream_entry_holds_are_counted_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under a `letter` entry of 2 and a `dream` entry lowered to 1, the day drafts (tier 2) pass the
    letter's ceiling and stay home by the entry they were written under: the manifest and the console
    say `drafts_held_by_the_dream_entry`, and nothing of them is in the letter."""
    lb = record(tmp_path, monkeypatch)
    set_policy(lb.root, LETTER_ENTRY, dream={"max_tier": 1, "until": "2026-12-31"})
    code, out_text, err = _export(lb, tmp_path / "out")
    assert code == 0, err
    html, md, manifest = _files(tmp_path / "out")
    held = manifest["held_back"]
    assert held["drafts_held_by_the_dream_entry"] == DRAFTED_SIGNED_DAYS
    assert held.get("drafts_above_tier", 0) == 0
    assert f"{DRAFTED_SIGNED_DAYS} drafts the dream entry holds" in out_text
    assert "drafts above tier" not in out_text
    assert STORY not in html and STORY not in md


@pytest.mark.parametrize(
    "flag",
    [("--unit", "week"), ("--title", "June"), ("--front", "front.md"), ("--paper", "letter"), ("--card",)],
    ids=lambda flag: flag[0],
)
@pytest.mark.parametrize(
    "export",
    [
        ("crossing", "--to", "hermes", "--since", "2026-06-01T00:00:00Z", "--dry-run"),
        ("vault", "VAULT"),
        ("--days", "2026-06-08", "2026-06-09"),
        ("share", "day", "2026-06-08", "--to", "ola"),
    ],
    ids=lambda export: export[0],
)
def test_the_letter_s_flags_are_refused_on_any_other_export(
    lb: Logbook, tmp_path: Path, flag: tuple[str, ...], export: tuple[str, ...]
) -> None:
    """`--unit`, `--title`, `--front`, `--paper` and `--card` are the letter's: any other export refuses
    each in one sentence that names it and the letter, and writes nothing."""
    seq = int(lb.meta["seq"])
    argv = [str(tmp_path / "vault") if arg == "VAULT" else arg for arg in export]
    code, out_text, err = run_cli("export", *argv, "--out", str(tmp_path / "out"), *flag)
    assert code == 2, (out_text, err)
    message = err.strip()
    assert "\n" not in message and ". " not in message  # one sentence
    assert flag[0] in message and "export letter" in message
    assert out_text == ""
    assert not (tmp_path / "out").exists() and not (tmp_path / "vault").exists()
    assert int(Logbook(lb.root).meta["seq"]) == seq
