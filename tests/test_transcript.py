"""The `transcript` file adapter: JSON in transcript/v1 shape (the interchange format), WebVTT, SRT,
Markdown and plain text → one transcript/v1 line per file, the file's own bytes as the §1.1
attachment. Synthetic Oslo persona only."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, attachments, cli
from logbook.adapters import transcript
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "transcript"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
AT = "2026-03-01T13:00:00Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _one(path: Path, **kw: Any) -> dict[str, Any]:
    lines = list(transcript.run(path, **kw))
    assert len(lines) == 1, lines
    return lines[0]


# -- registry and sniff ------------------------------------------------------------------------


def test_registry_has_transcript_as_a_file_adapter():
    assert adapters.named("transcript") is transcript
    assert transcript.NAME == "transcript" and transcript.KIND == "transcript" and transcript.TIER == 3


@pytest.mark.parametrize("name", ["tromso.vtt", "tromso.srt", "exported.json", "inline.json"])
def test_sniff_recognises_vtt_srt_and_transcript_json_by_content(name):
    assert transcript.sniff(FIX / name)
    assert adapters.find(FIX / name) is transcript


@pytest.mark.parametrize("name", ["tromso.md", "tromso.txt"])
def test_sniff_leaves_markdown_and_plain_text_to_the_explicit_command(name):
    assert not transcript.sniff(FIX / name)


def test_sniff_rejects_other_json_and_directories(tmp_path):
    other = tmp_path / "x.json"
    other.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    assert not transcript.sniff(other)
    assert not transcript.sniff(tmp_path)
    assert not transcript.sniff(ROOT / "tests" / "fixtures" / "dawarich" / "export.json")


# -- WebVTT -----------------------------------------------------------------------------------


def test_vtt_cues_become_turns_with_the_voice_tag_or_leading_name_as_speaker():
    line = _one(FIX / "tromso.vtt", source="zoom", at=AT)
    assert line["at"] == AT and line["end"] == "2026-03-01T13:00:20Z"
    assert line["tz"] is None and line["source"] == "zoom" and line["kind"] == "transcript"
    assert line["tier"] == 3
    p = line["payload"]
    assert p["schema"] == "transcript/v1" and p["provider"] == "zoom"
    assert p["participants"] == [{"name": "Kari Nordmann"}, {"name": "Ola Nordmann"}]
    assert p["extra"] == {
        "format": "vtt",
        "file": "tromso.vtt",
        "turns": 4,
        "speakers": 2,
        "unattributed": 1,
        "duration_s": 20.0,
    }


def test_vtt_content_is_the_file_itself_and_raw_id_is_its_digest():
    line = _one(FIX / "tromso.vtt", source="zoom", at=AT)
    sha = _sha(FIX / "tromso.vtt")
    assert line["payload"]["raw_id"] == f"zoom:{sha}"
    assert line["payload"]["content"] == attachments.reference((FIX / "tromso.vtt").read_bytes(), "text/vtt")
    assert "title" not in line["payload"]


def test_vtt_turns_are_the_cues_text_without_tags():
    parsed = transcript.parse(FIX / "tromso.vtt")
    assert [(t.speaker, t.text) for t in parsed.turns] == [
        ("Kari Nordmann", "Hei Ola, hører du meg?"),
        ("Ola Nordmann", "Ja, klart. Skal vi snakke om Tromsø-turen?"),
        ("Kari Nordmann", "Ja. Jeg tenker mai, når nettene fortsatt er lyse."),
        (None, "Vi må bestille hotell tidlig."),
    ]


def test_vtt_without_a_start_is_skipped_and_counted():
    counts: dict[str, int] = {}
    assert list(transcript.run(FIX / "tromso.vtt", source="zoom", counts=counts)) == []
    assert counts == {"skipped_no_start": 1}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("2026-03-01T13-00-00Z tromso.vtt", "2026-03-01T13:00:00Z"),
        ("GMT20260301-130000_Recording.transcript.vtt", "2026-03-01T13:00:00Z"),
        ("2026-03-01 1300 tromso.vtt", "2026-03-01T12:00:00Z"),  # local Oslo time, CET
        ("tromso 2026-03-01.vtt", "2026-02-28T23:00:00Z"),  # local midnight
    ],
)
def test_a_start_in_the_file_name_is_read_in_the_records_zone_when_it_has_none(tmp_path, name, expected):
    copy = tmp_path / name
    shutil.copy(FIX / "tromso.vtt", copy)
    line = _one(copy, source="zoom", timezone="Europe/Oslo")
    assert line["at"] == expected
    assert line["payload"]["extra"]["file"] == name


def test_an_explicit_start_beats_the_file_name(tmp_path):
    copy = tmp_path / "2026-03-01T13-00-00Z tromso.vtt"
    shutil.copy(FIX / "tromso.vtt", copy)
    assert _one(copy, source="zoom", at="2026-04-01T08:00:00Z")["at"] == "2026-04-01T08:00:00Z"


# -- SRT ----------------------------------------------------------------------------------------


def test_srt_cues_become_turns_and_a_second_cue_line_continues_the_turn():
    line = _one(FIX / "tromso.srt", source="otter", at=AT)
    assert line["end"] == "2026-03-01T13:00:15.250Z"
    p = line["payload"]
    assert p["raw_id"] == f"otter:{_sha(FIX / 'tromso.srt')}"
    assert p["content"]["media_type"] == "text/plain"
    assert p["extra"] == {
        "format": "srt",
        "file": "tromso.srt",
        "turns": 3,
        "speakers": 2,
        "duration_s": 15.25,
    }
    parsed = transcript.parse(FIX / "tromso.srt")
    assert parsed.turns[1].text == "Ja, klart. Skal vi snakke om Tromsø-turen?"


# -- Markdown and plain text --------------------------------------------------------------------


def test_markdown_front_matter_gives_title_times_and_participants():
    line = _one(FIX / "tromso.md", source="manual")
    assert line["at"] == "2026-03-01T13:00:00Z" and line["end"] == "2026-03-01T13:35:00Z"
    p = line["payload"]
    assert p["title"] == "Tromsø-tur i mai"
    assert p["participants"] == [
        {"name": "Kari Nordmann", "email": "kari@example.org"},
        {"name": "Ola Nordmann"},
    ]
    assert p["content"]["media_type"] == "text/markdown"
    assert p["extra"] == {
        "format": "markdown",
        "file": "tromso.md",
        "turns": 3,
        "speakers": 2,
        "duration_s": 2100.0,
    }


def test_markdown_continuation_lines_join_the_turn_and_blank_lines_separate():
    parsed = transcript.parse(FIX / "tromso.md")
    assert [(t.speaker, t.text) for t in parsed.turns] == [
        ("Kari Nordmann", "Hei Ola, hører du meg?"),
        ("Ola Nordmann", "Ja, klart. Skal vi snakke om Tromsø-turen? Vi må bestille hotell tidlig."),
        ("Kari Nordmann", "Ja. Jeg tenker mai."),
    ]


def test_plain_text_takes_its_title_from_a_heading_and_its_start_from_the_option():
    line = _one(FIX / "tromso.txt", source="manual", at=AT)
    p = line["payload"]
    assert p["title"] == "Tromsø-tur i mai" and line["end"] is None
    assert p["content"]["media_type"] == "text/plain"
    assert p["extra"] == {"format": "text", "file": "tromso.txt", "turns": 3, "speakers": 2}


def test_a_text_file_with_no_speaker_lines_is_still_a_transcript_of_unknown_speakers(tmp_path):
    f = tmp_path / "notat.txt"
    f.write_text("Bare en tanke om båten.\n", encoding="utf-8")
    line = _one(f, source="manual", at=AT)
    assert line["payload"]["participants"] == []
    assert line["payload"]["extra"] == {
        "format": "text",
        "file": "notat.txt",
        "turns": 1,
        "speakers": 0,
        "unattributed": 1,
    }


# -- JSON: the interchange format -------------------------------------------------------------------


def test_json_in_transcript_v1_shape_round_trips_the_payload_untouched():
    given = json.loads((FIX / "exported.json").read_text(encoding="utf-8"))
    line = _one(FIX / "exported.json")
    assert line["payload"] == given["payload"]
    assert {k: line[k] for k in ("at", "end", "tz", "source", "kind", "tier")} == {
        k: given[k] for k in ("at", "end", "tz", "source", "kind", "tier")
    }


def test_json_keeps_its_own_source_unless_one_is_given():
    assert _one(FIX / "exported.json")["source"] == "granola"
    assert _one(FIX / "exported.json", source="fireflies")["source"] == "fireflies"


def test_json_with_a_content_reference_stores_nothing():
    stored: list[bytes] = []
    _one(FIX / "exported.json", store=stored.append)
    assert stored == []


def test_json_with_inline_text_stores_it_and_points_at_it():
    stored: list[bytes] = []
    line = _one(FIX / "inline.json", store=stored.append)
    text = "Kari Nordmann: Beholder båten en sesong til.\n".encode()
    assert stored == [text]
    p = line["payload"]
    assert p["content"] == attachments.reference(text, "text/markdown")
    assert p["raw_id"] == f"plaud:{_sha(FIX / 'inline.json')}"
    assert p["extra"] == {"format": "json", "turns": 1, "speakers": 1}
    assert p["participants"] == [{"name": "Kari Nordmann"}]
    assert line["source"] == "plaud" and line["tier"] == 3


def test_json_without_a_start_is_skipped_and_counted(tmp_path):
    f = tmp_path / "bare.json"
    f.write_text(json.dumps({"schema": "transcript/v1", "title": "x"}), encoding="utf-8")
    counts: dict[str, int] = {}
    assert list(transcript.run(f, counts=counts)) == []
    assert counts == {"skipped_no_start": 1}


def test_json_that_is_not_a_transcript_is_skipped_and_counted(tmp_path):
    f = tmp_path / "other.json"
    f.write_text(json.dumps({"at": AT, "payload": {"schema": "note/v1", "text": "x"}}), encoding="utf-8")
    counts: dict[str, int] = {}
    assert list(transcript.run(f, counts=counts)) == []
    assert counts == {"skipped_not_transcript": 1}


def test_since_filters_on_at():
    assert list(transcript.run(FIX / "exported.json", since="2026-03-02T00:00:00Z")) == []
    assert len(list(transcript.run(FIX / "exported.json", since="2026-03-01T00:00:00Z"))) == 1


# -- the common mapping -----------------------------------------------------------------------------


def test_tier_is_3_by_default_and_the_option_overrides_it():
    assert _one(FIX / "tromso.md")["tier"] == 3
    assert _one(FIX / "tromso.md", tier=2)["tier"] == 2


def test_raw_id_is_stable_across_runs_and_independent_of_the_file_name(tmp_path):
    a = _one(FIX / "tromso.md", source="manual")["payload"]["raw_id"]
    copy = tmp_path / "renamed.md"
    shutil.copy(FIX / "tromso.md", copy)
    b = _one(copy, source="manual")["payload"]["raw_id"]
    assert a == b == f"manual:{_sha(FIX / 'tromso.md')}"
    assert _one(FIX / "tromso.md", source="plaud")["payload"]["raw_id"] != a


def test_store_receives_the_file_bytes_once_per_line():
    stored: list[bytes] = []
    _one(FIX / "tromso.vtt", source="zoom", at=AT, store=stored.append)
    assert stored == [(FIX / "tromso.vtt").read_bytes()]


def test_speakers_are_the_sources_labels_never_resolved():
    parsed = transcript.parse(FIX / "tromso.srt")
    assert parsed.participants == [{"name": "Kari Nordmann"}, {"name": "Ola Nordmann"}]


def test_a_folder_yields_one_line_per_transcript_and_counts_the_rest(tmp_path):
    folder = tmp_path / "exports"
    folder.mkdir()
    for name in ("tromso.md", "exported.json", "tromso.txt"):
        shutil.copy(FIX / name, folder / name)
    (folder / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (folder / ".DS_Store").write_bytes(b"")
    counts: dict[str, int] = {}
    lines = list(transcript.run(folder, source="manual", counts=counts))
    assert [line["source"] for line in lines] == ["manual", "manual"]  # an explicit source wins
    assert counts == {"skipped_not_transcript": 1, "skipped_no_start": 1}  # png; txt has no start


def test_every_line_is_valid_against_the_schema_and_appends(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lines = [
        _one(FIX / name, source="manual", at=AT, store=lb.attach)
        for name in ("tromso.vtt", "tromso.srt", "tromso.md", "tromso.txt", "exported.json", "inline.json")
    ]
    assert lb.append_many(lines) == 6
    assert lb.verify()[2] == []
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        ref = line["payload"]["content"]
        if (
            ref["sha256"]
            != json.loads((FIX / "exported.json").read_text("utf-8"))["payload"]["content"]["sha256"]
        ):
            assert (lb.root / ref["path"]).stat().st_size == ref["bytes"]


# -- the CLI -----------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def test_add_transcript_with_source_and_tier(lb, capsys):
    cli.main(["add", "transcript", str(FIX / "tromso.md"), "--source", "plaud", "--tier", "2"])
    out = capsys.readouterr().out
    assert "added 1 lines from transcript" in out
    (line,) = lb.lines()
    assert line["source"] == "plaud" and line["tier"] == 2
    ref = line["payload"]["content"]
    assert (lb.root / ref["path"]).read_bytes() == (FIX / "tromso.md").read_bytes()


def test_add_transcript_folder_reports_what_it_skipped(lb, tmp_path, capsys):
    folder = tmp_path / "exports"
    folder.mkdir()
    shutil.copy(FIX / "tromso.md", folder / "a.md")
    shutil.copy(FIX / "tromso.vtt", folder / "b.vtt")
    cli.main(["add", "transcript", str(folder), "--source", "manual"])
    out = capsys.readouterr().out
    assert "added 1 lines from transcript" in out and "skipped 1 without a start" in out


def test_add_transcript_re_adding_appends_nothing(lb, capsys):
    cli.main(["add", "transcript", str(FIX / "tromso.md")])
    cli.main(["add", "transcript", str(FIX / "tromso.md")])
    assert capsys.readouterr().out.count("added 1 lines") == 1 and len(list(lb.lines())) == 1


def test_add_a_sniffed_vtt_uses_at_and_defaults_the_source_to_manual(lb):
    cli.main(["add", str(FIX / "tromso.vtt"), "--at", AT])
    (line,) = lb.lines()
    assert line["source"] == "manual" and line["at"] == AT and line["kind"] == "transcript"


def test_add_source_and_tier_are_refused_for_an_adapter_that_does_not_take_them(lb, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", str(ROOT / "tests" / "fixtures" / "dawarich" / "export.json"), "--source", "x"])
    assert e.value.code == 2 and "--source" in capsys.readouterr().err


def test_add_transcript_is_still_a_sentence_when_nothing_after_it_is_a_path(lb):
    cli.main(["add", "transcript", "of", "the", "call", "was", "boring"])
    (line,) = lb.lines()
    assert line["kind"] == "note" and line["payload"]["text"] == "transcript of the call was boring"
