"""The granola live adapter and `logbook sync granola`: the public API shape (list notes with
created_after and cursor paging, get note with the transcript inline, the paged transcript endpoint
when the note answers 413), the mapping shared with the `transcript` file adapter, the summary as a
derived note/v1 line, the watermark and lookback, retry-once, and dedupe between a hand export and a
live pull. No network: `urlopen` is replaced by a fake Granola serving synthetic Oslo notes."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import granola, transcript
from logbook.core import attachments
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "transcript"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
KEY = "grn_synthetic0000000000000000"
ENV = {"LOGBOOK_GRANOLA_KEY": KEY}
URL = "https://public-api.granola.ai/v1"
CONFIG = granola.Config(url=URL, key=KEY, lookback_h=24.0, summaries=True)
NOTE_ID = "not_0synthetic0001"


def _segment(name: str | None, text: str, start: str, end: str, **more: Any) -> dict[str, Any]:
    speaker: dict[str, Any] = {"source": "microphone", "attribution": "me"}
    if name is not None:
        speaker["name"] = name
    speaker.update(more)
    return {"speaker": speaker, "text": text, "start_time": start, "end_time": end}


SEGMENTS = [
    _segment("Kari Nordmann", "Hei Ola, hører du meg?", "2026-03-01T13:00:00Z", "2026-03-01T13:00:04Z"),
    _segment(
        "Ola Nordmann",
        "Ja, klart.",
        "2026-03-01T13:00:04Z",
        "2026-03-01T13:00:09Z",
        source="speaker",
        attribution="them",
    ),
    _segment("Kari Nordmann", "Jeg tenker mai.", "2026-03-01T13:34:50Z", "2026-03-01T13:35:00Z"),
]


def _note(note_id: str = NOTE_ID, created: str = "2026-03-01T12:58:00Z", **fields: Any) -> dict[str, Any]:
    """One synthetic note as GET /v1/notes/{id} returns it."""
    note: dict[str, Any] = {
        "id": note_id,
        "object": "note",
        "title": "Tromsø-tur i mai",
        "owner": {"name": "Kari Nordmann", "email": "kari@example.org"},
        "created_at": created,
        "updated_at": "2026-03-01T13:40:00Z",
        "web_url": f"https://granola.example/notes/{note_id}",
        "calendar_event": None,
        "attendees": [
            {"name": "Kari Nordmann", "email": "kari@example.org"},
            {"name": "Ola Nordmann", "email": "ola@example.org"},
        ],
        "folder_membership": [
            {"id": "fol_0synthetic0001", "object": "folder", "name": "Reiser", "parent_folder_id": None}
        ],
        "summary_text": "Kari og Ola planlegger Tromsø i mai.",
        "summary_markdown": "**Kari og Ola** planlegger Tromsø i mai.",
        "transcript": SEGMENTS,
    }
    note.update(fields)
    return note


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeGranola:
    """Serves the three endpoints from `notes`: list filtered on created_after, paged by page_size
    and an opaque cursor; get note with the transcript inline unless `too_large`; the transcript
    endpoint paged by `segment_page`. Records every request. `fail_first` raises once."""

    def __init__(
        self,
        notes: list[dict[str, Any]],
        too_large: bool = False,
        segment_page: int = 50,
        fail_first: Exception | None = None,
        newest_first: bool = True,
    ):
        self.notes = notes
        self.too_large = too_large
        self.segment_page = segment_page
        self.fail_first = fail_first
        self.newest_first = newest_first
        self.requests: list[dict[str, Any]] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        url = urlsplit(req.full_url)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append({"path": url.path, "query": query, "headers": dict(req.header_items())})
        if self.fail_first is not None:
            error, self.fail_first = self.fail_first, None
            raise error
        parts = url.path.split("/")
        if parts[-1] == "notes":
            return self._list(query)
        if parts[-1] == "transcript":
            return self._transcript(parts[-2], query)
        return self._note(parts[-1], query)

    def _list(self, query: dict[str, str]) -> _Response:
        chosen = sorted(self.notes, key=lambda n: n["created_at"], reverse=self.newest_first)
        after = query.get("created_after")
        if after:
            chosen = [n for n in chosen if n["created_at"] > after]
        start = int(query.get("cursor") or 0)
        size = int(query.get("page_size", "10"))
        page = chosen[start : start + size]
        more = start + size < len(chosen)
        body = {
            "notes": [
                {k: n[k] for k in ("id", "object", "title", "owner", "created_at", "updated_at")}
                for n in page
            ],
            "hasMore": more,
            "cursor": str(start + size) if more else None,
        }
        return _Response(json.dumps(body).encode("utf-8"))

    def _note(self, note_id: str, query: dict[str, str]) -> _Response:
        note = next(n for n in self.notes if n["id"] == note_id)
        if query.get("include") == "transcript" and self.too_large:
            raise urllib.error.HTTPError(
                f"{URL}/notes/{note_id}",
                413,
                "Payload Too Large",
                None,
                None,  # type: ignore[arg-type]
            )
        body = dict(note)
        if query.get("include") != "transcript":
            body.pop("transcript", None)
        return _Response(json.dumps(body).encode("utf-8"))

    def _transcript(self, note_id: str, query: dict[str, str]) -> _Response:
        note = next(n for n in self.notes if n["id"] == note_id)
        start = int(query.get("cursor") or 0)
        segments = note.get("transcript") or []
        page = segments[start : start + self.segment_page]
        more = start + self.segment_page < len(segments)
        body = {
            "transcript": page,
            "hasMore": more,
            "cursor": str(start + self.segment_page) if more else None,
        }
        return _Response(json.dumps(body).encode("utf-8"))

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]


def _serve(monkeypatch: pytest.MonkeyPatch, notes: list[dict[str, Any]], **kw: Any) -> FakeGranola:
    fake = FakeGranola(notes, **kw)
    monkeypatch.setattr(granola, "urlopen", fake)
    return fake


def _content(segments: list[dict[str, Any]]) -> bytes:
    return json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# -- registry and configure ------------------------------------------------------------------------


def test_registry_has_granola_as_a_live_adapter_only():
    assert adapters.live("granola") is granola
    assert adapters.named("granola") is None
    assert granola.NAME == "granola" and granola.KIND == transcript.KIND == "transcript"
    assert granola.UNIT == "notes"


def test_configure_needs_only_the_key_and_defaults_the_url():
    assert granola.ENV == ("LOGBOOK_GRANOLA_KEY",)
    assert granola.configure(ENV) == CONFIG
    assert granola.DEFAULT_URL == URL


def test_configure_reads_the_url_override_without_its_trailing_slash():
    config = granola.configure({**ENV, "LOGBOOK_GRANOLA_URL": "https://granola.test/v1/"})
    assert config is not None and config.url == "https://granola.test/v1"


def test_configure_returns_none_without_a_key():
    assert granola.configure({}) is None
    assert granola.configure({"LOGBOOK_GRANOLA_KEY": "  "}) is None


def test_configure_reads_summaries_off_and_the_lookback():
    config = granola.configure({**ENV, "LOGBOOK_GRANOLA_SUMMARIES": "0", "LOGBOOK_GRANOLA_LOOKBACK_H": "72"})
    assert config is not None and config.summaries is False and config.lookback_h == 72.0


@pytest.mark.parametrize("bad", ["soon", "-1", "nan"])
def test_configure_refuses_a_bad_lookback(bad):
    with pytest.raises(ValueError, match="LOGBOOK_GRANOLA_LOOKBACK_H"):
        granola.configure({**ENV, "LOGBOOK_GRANOLA_LOOKBACK_H": bad})


def test_the_key_never_appears_in_the_configs_repr():
    assert KEY not in repr(CONFIG) and KEY not in str(CONFIG)


def test_resume_is_the_mark_less_the_lookback():
    assert granola.resume(CONFIG, "2026-03-02T13:35:00Z") == "2026-03-01T13:35:00Z"


def test_watermark_is_the_recording_end_else_its_start():
    assert (
        granola.watermark({"at": "2026-03-01T13:00:00Z", "end": "2026-03-01T13:35:00Z", "payload": {}})
        == "2026-03-01T13:35:00Z"
    )
    assert (
        granola.watermark({"at": "2026-03-01T13:00:00Z", "end": None, "payload": {}})
        == "2026-03-01T13:00:00Z"
    )


# -- the mapping -----------------------------------------------------------------------------------


def test_a_note_maps_to_the_transcript_line_the_file_adapter_would_give(monkeypatch):
    _serve(monkeypatch, [_note()])
    lines = list(granola.pull(CONFIG, "2026-03-01T00:00:00Z"))
    line = lines[0]
    given = json.loads((FIX / "exported.json").read_text(encoding="utf-8"))
    assert len(line.pop("id")) == 36
    assert {k: line[k] for k in ("at", "end", "source", "kind", "tier")} == {
        k: given[k] for k in ("at", "end", "source", "kind", "tier")
    }
    assert line["tz"] is None
    p, g = line["payload"], given["payload"]
    assert p["content"] == attachments.reference(_content(SEGMENTS), "application/json")
    assert p["content"] == g["content"]  # the fixture was written from the same bytes
    assert (p["schema"], p["provider"], p["raw_id"], p["title"], p["source_uri"]) == (
        g["schema"],
        g["provider"],
        g["raw_id"],
        g["title"],
        g["source_uri"],
    )
    assert p["participants"] == [
        {"name": "Kari Nordmann", "email": "kari@example.org"},
        {"name": "Ola Nordmann", "email": "ola@example.org"},
    ]
    assert p["extra"] == {"turns": 3, "speakers": 2, "duration_s": 2100.0, "folders": ["Reiser"]}
    assert "summary" not in p  # Granola's summary is a model's words: a derived note, never here


def test_the_live_puller_uses_the_file_adapters_mapping():
    assert granola.draft is transcript.draft


def test_a_live_line_and_the_same_transcript_from_a_json_export_share_one_raw_id(monkeypatch):
    _serve(monkeypatch, [_note()])
    live = next(granola.pull(CONFIG, "2026-03-01T00:00:00Z"))
    exported = next(transcript.run(FIX / "exported.json"))
    assert live["payload"]["raw_id"] == exported["payload"]["raw_id"] == f"granola:{NOTE_ID}"
    assert live["source"] == exported["source"] == "granola"


def test_speaker_labels_fall_back_to_diarization_then_attribution_then_unknown(monkeypatch):
    segments = [
        _segment(None, "Hei", "2026-03-01T13:00:00Z", "2026-03-01T13:00:01Z", diarization_label="Speaker A"),
        _segment(None, "Hei", "2026-03-01T13:00:01Z", "2026-03-01T13:00:02Z", attribution="them"),
        {
            "speaker": {},
            "text": "...",
            "start_time": "2026-03-01T13:00:02Z",
            "end_time": "2026-03-01T13:00:03Z",
        },
    ]
    line = granola.transcript_of(_note(transcript=segments, attendees=[]), segments)
    assert line["payload"]["participants"] == [{"name": "Speaker A"}, {"name": "them"}]
    assert line["payload"]["extra"] == {
        "turns": 3,
        "speakers": 2,
        "unattributed": 1,
        "duration_s": 3.0,
        "folders": ["Reiser"],
    }


def test_a_note_with_no_segments_is_timed_by_its_calendar_event_else_its_creation(monkeypatch):
    event = {
        "event_title": "Planlegging",
        "invitees": [],
        "organiser": None,
        "calendar_event_id": None,
        "scheduled_start_time": "2026-03-01T13:00:00Z",
        "scheduled_end_time": "2026-03-01T13:30:00Z",
    }
    line = granola.transcript_of(_note(transcript=[], calendar_event=event), [])
    assert (line["at"], line["end"]) == ("2026-03-01T13:00:00Z", "2026-03-01T13:30:00Z")
    line = granola.transcript_of(_note(transcript=[]), [])
    assert (line["at"], line["end"]) == ("2026-03-01T12:58:00Z", None)
    assert line["payload"]["extra"] == {"turns": 0, "speakers": 0, "folders": ["Reiser"]}


# -- the summary ----------------------------------------------------------------------------------


def test_the_summary_is_a_derived_note_pointing_at_the_transcript_line(monkeypatch):
    _serve(monkeypatch, [_note()])
    t, s = list(granola.pull(CONFIG, "2026-03-01T00:00:00Z"))
    assert len(t["id"]) == 36
    assert s == {
        "at": "2026-03-01T13:35:00Z",
        "end": None,
        "tz": None,
        "source": "granola",
        "kind": "note",
        "tier": 2,
        "payload": {
            "schema": "note/v1",
            "text": "Kari og Ola planlegger Tromsø i mai.",
            "title": "Tromsø-tur i mai",
            "raw_id": f"granola:{NOTE_ID}:summary",
            "modified_at": "2026-03-01T13:40:00Z",
            "extra": {"derived": True, "derived_from": t["id"], "derived_from_raw_id": f"granola:{NOTE_ID}"},
        },
    }


def test_the_summary_points_at_the_transcript_already_in_the_record_when_there_is_one(monkeypatch):
    _serve(monkeypatch, [_note()])
    existing = "01930000-0000-7000-8000-000000000001"
    calls: list[tuple[str, str]] = []

    def lookup(source: str, raw_id: str) -> str | None:
        calls.append((source, raw_id))
        return existing

    t, s = list(granola.pull(CONFIG, "2026-03-01T00:00:00Z", lookup=lookup))
    assert calls == [("granola", f"granola:{NOTE_ID}")]
    assert s["payload"]["extra"]["derived_from"] == existing
    assert t["id"] != existing  # the transcript draft dedupes on raw_id; its own id is never written


def test_summaries_off_yields_only_transcripts(monkeypatch):
    _serve(monkeypatch, [_note()])
    config = granola.Config(url=URL, key=KEY, lookback_h=24.0, summaries=False)
    lines = list(granola.pull(config, None))
    assert [line["kind"] for line in lines] == ["transcript"]


def test_a_note_without_a_summary_yields_no_note_and_is_counted(monkeypatch):
    _serve(monkeypatch, [_note(summary_text="")])
    counts: dict[str, int] = {}
    lines = list(granola.pull(CONFIG, None, counts=counts))
    assert [line["kind"] for line in lines] == ["transcript"]
    assert counts == {"no_summary": 1}


def test_a_note_with_no_recording_yields_only_its_summary(monkeypatch):
    """A note Granola made without recording (one empty turn, a zero span, `duration_s` 0) is
    not a transcript: only the summary is yielded, its raw_id as ever, nothing stored, and the
    skip is counted. Without a transcript line there is nothing for `derived_from` to name."""
    at = "2026-03-01T13:00:00Z"
    silent = [_segment(None, "", at, at)]
    _serve(monkeypatch, [_note(transcript=silent)])
    counts: dict[str, int] = {}
    stored: list[bytes] = []
    lines = list(granola.pull(CONFIG, None, counts=counts, store=stored.append))
    assert [line["kind"] for line in lines] == ["note"]
    (summary,) = lines
    assert summary["at"] == at
    assert summary["payload"]["raw_id"] == f"granola:{NOTE_ID}:summary"
    assert summary["payload"]["extra"] == {"derived": True, "derived_from_raw_id": f"granola:{NOTE_ID}"}
    assert stored == [] and counts == {"no_recording": 1}


def test_a_note_with_no_recording_still_points_at_a_transcript_already_in_the_record(monkeypatch):
    at = "2026-03-01T13:00:00Z"
    _serve(monkeypatch, [_note(transcript=[_segment(None, "", at, at)])])
    existing = "01930000-0000-7000-8000-000000000001"
    (summary,) = list(granola.pull(CONFIG, None, lookup=lambda _source, _raw_id: existing))
    assert summary["payload"]["extra"]["derived_from"] == existing


def test_a_note_with_neither_recording_nor_summary_yields_nothing_and_counts_both(monkeypatch):
    at = "2026-03-01T13:00:00Z"
    _serve(monkeypatch, [_note(transcript=[_segment(None, "", at, at)], summary_text="")])
    counts: dict[str, int] = {}
    assert list(granola.pull(CONFIG, None, counts=counts)) == []
    assert counts == {"no_recording": 1, "no_summary": 1}


# -- pull: requests, paging, the large transcript, order, store --------------------------------------


def test_pull_lists_notes_created_after_since_with_a_bearer_key(monkeypatch):
    fake = _serve(monkeypatch, [_note()])
    list(granola.pull(CONFIG, "2026-03-01T00:00:00Z"))
    first = fake.requests[0]
    assert first["path"] == "/v1/notes"
    assert {k.lower(): v for k, v in first["headers"].items()}["authorization"] == f"Bearer {KEY}"
    assert first["query"] == {"created_after": "2026-03-01T00:00:00Z", "page_size": str(granola.PAGE_SIZE)}
    assert KEY not in json.dumps([r["query"] for r in fake.requests])
    assert fake.paths() == ["/v1/notes", f"/v1/notes/{NOTE_ID}"]
    assert fake.requests[1]["query"] == {"include": "transcript"}


def test_pull_without_since_lists_everything(monkeypatch):
    fake = _serve(monkeypatch, [_note()])
    list(granola.pull(CONFIG, None))
    assert fake.requests[0]["query"] == {"page_size": str(granola.PAGE_SIZE)}


def test_pull_follows_the_cursor_until_has_more_is_false(monkeypatch):
    notes = [_note(f"not_0synthetic{i:04d}", created=f"2026-03-{1 + i:02d}T12:58:00Z") for i in range(1, 8)]
    for n in notes:
        n["transcript"] = []
    fake = _serve(monkeypatch, notes)
    monkeypatch.setattr(granola, "PAGE_SIZE", 3)
    lines = list(granola.pull(CONFIG, None))
    assert len([line for line in lines if line["kind"] == "transcript"]) == 7
    listed = [r for r in fake.requests if r["path"] == "/v1/notes"]
    assert [r["query"].get("cursor") for r in listed] == [None, "3", "6"]


def test_pull_falls_back_to_the_paged_transcript_endpoint_on_413(monkeypatch):
    fake = _serve(monkeypatch, [_note()], too_large=True, segment_page=2)
    line = next(granola.pull(CONFIG, None))
    assert line["payload"]["content"] == attachments.reference(_content(SEGMENTS), "application/json")
    assert fake.paths() == [
        "/v1/notes",
        f"/v1/notes/{NOTE_ID}",
        f"/v1/notes/{NOTE_ID}",
        f"/v1/notes/{NOTE_ID}/transcript",
        f"/v1/notes/{NOTE_ID}/transcript",
    ]
    assert fake.requests[2]["query"] == {}  # the note itself, without the transcript
    assert [r["query"].get("cursor") for r in fake.requests[3:]] == [None, "2"]


def test_pull_yields_oldest_first_with_each_summary_after_its_transcript(monkeypatch):
    notes = [
        _note("not_0synthetic0002", created="2026-03-05T09:00:00Z", transcript=[]),
        _note("not_0synthetic0001", created="2026-03-01T12:58:00Z"),
    ]
    _serve(monkeypatch, notes, newest_first=True)
    lines = list(granola.pull(CONFIG, None))
    assert [(line["kind"], line["payload"]["raw_id"]) for line in lines] == [
        ("transcript", "granola:not_0synthetic0001"),
        ("note", "granola:not_0synthetic0001:summary"),
        ("transcript", "granola:not_0synthetic0002"),
        ("note", "granola:not_0synthetic0002:summary"),
    ]


def test_pull_reports_the_note_count_after_each_page(monkeypatch):
    _serve(monkeypatch, [_note(), _note("not_0synthetic0002", created="2026-03-02T09:00:00Z")])
    seen: list[int] = []
    list(granola.pull(CONFIG, None, progress=lambda n, _elapsed: seen.append(n)))
    assert seen == [2]


def test_store_receives_the_transcript_bytes_when_the_line_is_yielded(monkeypatch):
    _serve(monkeypatch, [_note()])
    stored: list[bytes] = []
    lines = granola.pull(CONFIG, None, store=stored.append)
    next(lines)
    assert stored == [_content(SEGMENTS)]
    list(lines)
    assert stored == [_content(SEGMENTS)]  # the summary is inline text, nothing to store


# -- failure: retry once, then a clear error, nothing yielded -----------------------------------------


def test_a_connection_failure_is_retried_once(monkeypatch):
    fake = _serve(monkeypatch, [_note()], fail_first=urllib.error.URLError("connection refused"))
    lines = list(granola.pull(CONFIG, None))
    assert len(lines) == 2
    assert fake.paths()[:2] == ["/v1/notes", "/v1/notes"]


def test_two_failures_raise_a_clear_error_before_anything_is_yielded(monkeypatch):
    def down(req: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(granola, "urlopen", down)
    calls: list[str] = []
    monkeypatch.setattr(granola.time, "sleep", calls.append)
    with pytest.raises(OSError, match=r"GET /notes.*connection refused.*twice") as e:
        list(granola.pull(CONFIG, None))
    assert KEY not in str(e.value)
    assert len(calls) == 1


def test_an_unauthorized_answer_is_not_retried_and_names_the_variable(monkeypatch):
    def refused(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(granola, "urlopen", refused)
    monkeypatch.setattr(granola.time, "sleep", lambda s: None)
    calls = 0

    def counting(req: Any, timeout: float) -> Any:
        nonlocal calls
        calls += 1
        return refused(req, timeout)

    monkeypatch.setattr(granola, "urlopen", counting)
    with pytest.raises(OSError, match=r"401.*LOGBOOK_GRANOLA_KEY"):
        list(granola.pull(CONFIG, None))
    assert calls == 1


def test_a_response_that_is_not_json_is_an_error(monkeypatch):
    monkeypatch.setattr(granola, "urlopen", lambda req, timeout: _Response(b"<html>login</html>"))
    with pytest.raises(ValueError, match="not JSON"):
        list(granola.pull(CONFIG, None))


def test_a_failure_on_the_second_note_yields_nothing_at_all(monkeypatch):
    notes = [_note(), _note("not_0synthetic0002", created="2026-03-02T09:00:00Z")]
    fake = FakeGranola(notes)

    def flaky(req: Any, timeout: float) -> Any:
        if req.full_url.endswith("not_0synthetic0002?include=transcript"):
            raise urllib.error.HTTPError(req.full_url, 500, "Server Error", None, None)  # type: ignore[arg-type]
        return fake(req, timeout)

    monkeypatch.setattr(granola, "urlopen", flaky)
    monkeypatch.setattr(granola.time, "sleep", lambda s: None)
    stored: list[bytes] = []
    lines = granola.pull(CONFIG, None, store=stored.append)
    with pytest.raises(OSError, match="500"):
        next(lines)
    assert stored == []


# -- validity --------------------------------------------------------------------------------------


def test_pulled_lines_append_into_a_valid_record_and_match_the_schema(tmp_path, monkeypatch):
    _serve(monkeypatch, [_note(), _note("not_0synthetic0002", created="2026-03-02T09:00:00Z", transcript=[])])
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(granola.pull(CONFIG, None, store=lb.attach)) == 4
    assert lb.verify()[2] == []
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    ref = next(lb.lines())["payload"]["content"]
    assert hashlib.sha256((lb.root / ref["path"]).read_bytes()).hexdigest() == ref["sha256"]


# -- sync: the CLI ------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_GRANOLA_KEY", KEY)
    for name in ("LOGBOOK_GRANOLA_URL", "LOGBOOK_GRANOLA_LOOKBACK_H", "LOGBOOK_GRANOLA_SUMMARIES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(granola.time, "sleep", lambda s: None)
    return lb


def _sync(*args: str) -> None:
    cli.main(["sync", "granola", *args])


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "granola.json").read_text(encoding="utf-8"))
    return data


def test_sync_appends_the_transcript_and_its_summary_and_stores_the_text(lb, monkeypatch, capsys):
    _serve(monkeypatch, [_note()])
    _sync()
    out = capsys.readouterr().out
    assert "granola: 2 new lines of 2 seen from the beginning; watermark 2026-03-01T13:35:00Z" in out
    t, s = lb.lines()
    assert t["kind"] == "transcript" and s["kind"] == "note"
    assert s["payload"]["extra"]["derived_from"] == t["id"]
    ref = t["payload"]["content"]
    assert (lb.root / ref["path"]).read_bytes() == _content(SEGMENTS)
    assert _state(lb) == {"since": "2026-03-01T13:35:00Z"}


def test_sync_resumes_a_lookback_before_the_watermark(lb, monkeypatch, capsys):
    fake = _serve(monkeypatch, [_note()])
    (lb.root / "state").mkdir()
    (lb.root / "state" / "granola.json").write_text(
        json.dumps({"since": "2026-03-02T13:35:00Z"}), encoding="utf-8"
    )
    _sync()
    assert fake.requests[0]["query"]["created_after"] == "2026-03-01T13:35:00Z"
    assert "since 2026-03-01T13:35:00Z" in capsys.readouterr().out


def test_sync_since_is_used_as_given(lb, monkeypatch):
    fake = _serve(monkeypatch, [_note()])
    _sync("--since", "2026-02-01T00:00:00Z")
    assert fake.requests[0]["query"]["created_after"] == "2026-02-01T00:00:00Z"


def test_sync_first_run_continues_from_the_records_newest_granola_transcript(lb, monkeypatch, capsys):
    cli.main(["add", str(FIX / "exported.json")])
    fake = _serve(monkeypatch, [_note()])
    _sync()
    out = capsys.readouterr().out
    assert fake.requests[0]["query"]["created_after"] == "2026-02-28T13:00:00Z"
    assert "starting from the record's newest granola" in out


def test_a_hand_exported_transcript_and_the_live_pull_are_one_line(lb, monkeypatch, capsys):
    cli.main(["add", str(FIX / "exported.json")])
    (exported,) = lb.lines()
    _serve(monkeypatch, [_note()])
    _sync()
    out = capsys.readouterr().out
    assert "granola: 1 new lines of 2 seen" in out and "(1 already in the record)" in out
    lines = list(lb.lines())
    assert [line["kind"] for line in lines] == ["transcript", "note"]
    assert lines[1]["payload"]["extra"]["derived_from"] == exported["id"]


def test_sync_re_run_appends_nothing(lb, monkeypatch, capsys):
    _serve(monkeypatch, [_note()])
    _sync()
    _sync()
    assert "granola: 0 new lines of 2 seen" in capsys.readouterr().out.splitlines()[-1]
    assert len(list(lb.lines())) == 2


def test_sync_dry_run_writes_nothing_and_counts_per_kind(lb, monkeypatch, capsys):
    _serve(monkeypatch, [_note()])
    _sync("--dry-run")
    out = capsys.readouterr().out
    assert "granola: 2 lines from the beginning (dry run, nothing written)" in out
    assert "transcript: 1" in out and "note: 1" in out
    assert list(lb.lines()) == []
    assert not (lb.root / "state").exists() and not (lb.root / "attachments").exists()


def test_sync_summaries_can_be_switched_off(lb, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_GRANOLA_SUMMARIES", "0")
    _serve(monkeypatch, [_note()])
    _sync()
    assert "granola: 1 new lines of 1 seen" in capsys.readouterr().out
    assert [line["kind"] for line in lb.lines()] == ["transcript"]


def test_sync_progress_counts_notes(lb, monkeypatch, capsys):
    _serve(monkeypatch, [_note()])
    _sync()
    assert "  1 notes in 0s" in capsys.readouterr().err.splitlines()


def test_sync_refuses_to_run_without_the_key(lb, monkeypatch, capsys):
    monkeypatch.delenv("LOGBOOK_GRANOLA_KEY")
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 2
    assert capsys.readouterr().err.strip() == "sync: granola: set LOGBOOK_GRANOLA_KEY"


def test_sync_network_failure_exits_1_writes_nothing_and_never_prints_the_key(lb, monkeypatch, capsys):
    def down(req: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(granola, "urlopen", down)
    with pytest.raises(SystemExit) as e:
        _sync()
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "connection refused" in captured.err and KEY not in captured.err + captured.out
    assert list(lb.lines()) == []
    assert not (lb.root / "state").exists() and not (lb.root / "attachments").exists()
