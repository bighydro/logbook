"""Google Takeout Keep/ → note/v1 (RFC 0010): one line per note; labels, flags, attachments by digest."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters.takeout import keep
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Keep"
PNG = FIX / "17a2b3c4d5e6f708.png"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"


def _lines(**kw):
    return list(keep.run(FIX, timezone=TZ, **kw))


def _by_title(lines):
    return {line["payload"].get("title", ""): line for line in lines}


# -- registry and sniff ---------------------------------------------------------------------------


def test_registry_has_keep_as_a_file_adapter():
    assert adapters.named("google-takeout-keep") is keep
    assert isinstance(keep, adapters.Adapter)
    assert adapters.find(FIX) is keep
    assert adapters.find(FIX / "Boat list.json") is keep


def test_sniff_recognises_a_keep_note_and_the_keep_folder_but_not_its_twins(tmp_path):
    assert keep.sniff(FIX / "Boat list.json")
    assert keep.sniff(FIX)
    assert not keep.sniff(FIX / "Boat list.html")
    assert not keep.sniff(FIX / "Labels.txt")
    assert not keep.sniff(FIX / PNG.name)
    assert not keep.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Records.json")
    assert not keep.sniff(ROOT / "tests" / "fixtures" / "dawarich" / "export.json")
    assert not keep.sniff(tmp_path)
    assert not keep.sniff(tmp_path / "missing.json")
    (tmp_path / "other.json").write_text('{"title": "x", "textContent": "y"}', encoding="utf-8")
    assert not keep.sniff(tmp_path / "other.json")  # no timestamps: not Keep's shape


# -- the mapping ----------------------------------------------------------------------------------


def test_every_note_with_text_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(keep.run(FIX, timezone=TZ, counts=counts))
    assert len(lines) == 4  # the empty note is skipped; the trashed one is kept and marked
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "note" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "note/v1"
    assert counts == {
        "skipped_no_text": 1,
        "trashed": 1,
        "attachments_referenced": 1,
        "attachments_missing": 1,
    }
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_text_note_maps_times_labels_flags_and_links():
    p = _by_title(_lines())[""]["payload"]
    line = _by_title(_lines())[""]
    assert line["at"] == "2026-02-11T07:55:00Z"
    assert p["raw_id"] == "keep:1770796500000000@2026-02-12T07:40:00Z"
    assert p["modified_at"] == "2026-02-12T07:40:00Z"
    assert p["text"] == "Boxes: 14. Van booked for the 20th.\nCall Ola about the keys."
    assert "title" not in p and "labels" not in p
    assert p["extra"]["archived"] is True and "pinned" not in p["extra"] and "trashed" not in p["extra"]
    assert "color" not in p["extra"]  # DEFAULT says nothing
    assert p["extra"]["links"] == [
        {"title": "Van hire", "url": "https://vans.example.org/booking/42", "description": "Storgata 1, Oslo"}
    ]


def test_a_list_note_becomes_checklist_lines_with_labels_pinned_and_colour():
    line = _by_title(_lines())["Boat list"]
    p = line["payload"]
    assert line["at"] == "2026-03-04T09:00:00Z"
    assert p["raw_id"] == "keep:1772614800000000@2026-03-08T09:00:00Z"
    assert p["title"] == "Boat list"
    assert p["text"] == "[x] long rope\n[ ] fenders\n[ ] fuel can"
    assert p["labels"] == ["Boat", "Weekend"]
    assert p["extra"] == {"pinned": True, "color": "BLUE"}


def test_a_trashed_note_is_a_line_marked_trashed():
    p = _by_title(_lines())["Old shopping"]["payload"]
    assert p["extra"]["trashed"] is True
    assert p["text"] == "milk, bread"


def test_attachments_are_referenced_by_digest_and_stored_only_when_asked(tmp_path):
    digest = hashlib.sha256(PNG.read_bytes()).hexdigest()
    p = _by_title(_lines())[""]["payload"]
    assert p["attachments"] == [
        {"filename": PNG.name, "media_type": "image/png", "sha256": digest, "bytes": PNG.stat().st_size}
    ]
    stored: list[bytes] = []
    p = _by_title(_lines(attachments=True, store=stored.append))[""]["payload"]
    assert p["attachments"][0]["path"] == f"attachments/{digest}"
    assert stored == [PNG.read_bytes()]
    missing = _by_title(_lines())["Missing photo"]["payload"]
    assert missing["attachments"] == [{"filename": "nowhere.jpg", "media_type": "image/jpeg"}]


def test_since_cuts_on_at_and_a_single_file_is_one_note():
    assert [line["payload"]["title"] for line in _lines(since="2026-03-01T00:00:00Z")] == ["Boat list"]
    (line,) = keep.run(FIX / "Boat list.json", timezone=TZ)
    assert line["payload"]["title"] == "Boat list"


def test_the_same_note_edited_is_a_new_line_and_a_re_import_appends_nothing(tmp_path):
    lb = Logbook.init(tmp_path / "lb", timezone_name=TZ)
    folder = tmp_path / "Keep"
    shutil.copytree(FIX, folder)
    assert lb.append_many(keep.run(folder, timezone=TZ)) == 4
    assert lb.append_many(keep.run(folder, timezone=TZ)) == 0  # a re-import appends nothing
    note = json.loads((folder / "Boat list.json").read_text(encoding="utf-8"))
    note["listContent"].append({"text": "chart", "isChecked": False})
    note["userEditedTimestampUsec"] += 60_000_000
    (folder / "Boat list.json").write_text(json.dumps(note), encoding="utf-8")
    assert lb.append_many(keep.run(folder, timezone=TZ)) == 1  # RFC 0010 rule 2: a snapshot per edit
    new = next(line for line in lb.lines() if line["payload"]["raw_id"].endswith("@2026-03-08T09:01:00Z"))
    assert new["payload"]["text"].endswith("\n[ ] chart")
    seq, _head, errors = lb.verify()
    assert seq == 5 and not errors


def test_cli_add_sniffs_the_keep_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert "added 4 lines from google-takeout-keep" in out
    assert "skipped 1 without any text" in out
    assert "1 marked trashed" in out and "1 attachments referenced, not stored" in out
    assert "1 attachments missing from the export" in out
