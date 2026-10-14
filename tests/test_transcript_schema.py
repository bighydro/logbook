"""`transcript/v1` with RFC 0038's amendment (RFC 0004, amended 2026-10-14 under RFC 0031 rule 1):
two optional payload fields, `speakers` and `diarization`, the second required by the first. The
schema is `schema/transcript-v1.schema.json`. A transcript without them is a transcript as RFC 0004
defines it: it validates, and its canonical form and hash are what they were."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from logbook.core.chain import CONTENT_FIELDS, canonical_json, content_hash

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "transcript-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
PROFILE = ROOT / "conformance" / "profiles" / "transcript"
FIXTURES = ROOT / "tests" / "fixtures" / "transcript"

AUDIO = "c41d" + "0" * 60
SPANS = "a9e2" + "0" * 60
CONTENT = "5e0c" + "0" * 60


def _dinner() -> dict[str, Any]:
    """RFC 0038 §11's dinner, the hashes written out: three voices in one channel."""
    return {
        "at": "2026-10-03T17:40:12Z",
        "end": "2026-10-03T18:52:30Z",
        "tz": "Europe/Oslo",
        "source": "transcription",
        "kind": "transcript",
        "tier": 2,
        "payload": {
            "schema": "transcript/v1",
            "provider": "mlx-whisper",
            "raw_id": "7A1B2C3D-0000-4000-8000-000000000038",
            "title": "Middag",
            "participants": [],
            "language": "nb",
            "content": {
                "sha256": CONTENT,
                "path": f"attachments/{CONTENT}",
                "bytes": 38214,
                "media_type": "text/plain",
            },
            "provenance": {
                "source": "019cadd3-6bc0-7dcd-9133-0000000004a0",
                "engine": "mlx-whisper",
                "model": "small",
            },
            "speakers": [
                {"label": "S1", "seconds": 1862.4, "turns": 212},
                {"label": "S2", "seconds": 861.0, "turns": 97},
                {"label": "S3", "seconds": 41.5, "turns": 4},
            ],
            "diarization": {
                "engine": "pyannote",
                "model": "pyannote/speaker-diarization-3.1",
                "audio": AUDIO,
                "channels": 1,
                "overlap_s": 38.2,
                "spans": {
                    "sha256": SPANS,
                    "path": f"attachments/{SPANS}",
                    "bytes": 21877,
                    "media_type": "application/json",
                },
            },
            "extra": {"recording": "7A1B2C3D-0000-4000-8000-000000000038", "chunks": 8, "segments": 313},
        },
    }


def _errors(payload: dict[str, Any]) -> list[str]:
    return [e.message for e in VALIDATOR.iter_errors(payload)]


def test_the_schema_is_a_json_schema():
    Draft202012Validator.check_schema(SCHEMA)


def test_the_conformance_transcript_validates_and_its_hash_is_what_the_fixture_says():
    """The frozen profile's own line carries neither field; the amendment changes nothing of it."""
    expected = json.loads((PROFILE / "expected.json").read_text(encoding="utf-8"))
    [raw] = (PROFILE / "record" / "logbook" / "2026" / "03.jsonl").read_text(encoding="utf-8").splitlines()
    line = json.loads(raw)
    assert "speakers" not in line["payload"] and "diarization" not in line["payload"]
    assert _errors(line["payload"]) == []
    assert canonical_json({k: line.get(k) for k in CONTENT_FIELDS}) == expected["canonical"]
    assert content_hash(line) == expected["content_hash"]


@pytest.mark.parametrize("name", ["exported.json", "inline.json"])
def test_the_file_adapter_s_fixtures_validate(name: str):
    line = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    payload = line["payload"]
    if isinstance(payload.get("content"), dict) and "text" in payload["content"]:
        payload = {k: v for k, v in payload.items() if k != "content"}  # inline text: stored by `add`
    assert _errors(payload) == []


def test_a_line_with_speakers_validates_and_round_trips():
    line = _dinner()
    assert _errors(line["payload"]) == []
    text = canonical_json({k: line.get(k) for k in CONTENT_FIELDS})
    again = json.loads(text)
    assert again == {k: line.get(k) for k in CONTENT_FIELDS}
    assert canonical_json(again) == text  # the canonical form is a fixed point
    assert content_hash(again) == content_hash(line)


def test_the_two_fields_leave_the_rest_of_the_line_byte_identical():
    """Take them out and what is left is the transcript RFC 0004 would have written, byte for byte."""
    line = _dinner()
    bare = copy.deepcopy(line)
    del bare["payload"]["speakers"], bare["payload"]["diarization"]
    assert content_hash(line) != content_hash(bare)  # the fields are content: the hash covers them
    text = canonical_json({k: bare.get(k) for k in CONTENT_FIELDS})
    assert '"speakers"' not in text and '"diarization"' not in text
    assert _errors(bare["payload"]) == []


def test_two_channels_from_me_and_a_provider_s_labels_validate():
    call = _dinner()["payload"]
    call["speakers"] = [
        {"label": "mic", "seconds": 201.7, "turns": 38, "channel": "mic", "from_me": True},
        {"label": "system", "seconds": 188.3, "turns": 35, "channel": "system", "name": "Ola Nordmann"},
    ]
    call["diarization"]["channels"] = 2
    assert _errors(call) == []
    provider = _dinner()["payload"]
    provider["speakers"] = [
        {"label": "mic", "turns": 3, "channel": "mic", "from_me": True},
        {"label": "Speaker 2", "turns": 1},
    ]
    provider["diarization"] = {"engine": "granola", "channels": 2}  # no audio: the provider kept it
    assert _errors(provider) == []


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda p: p.pop("diarization"), "dependency"),
        (lambda p: p.update(speakers=[]), "should be non-empty"),
        (lambda p: p["speakers"][0].update(label="S#1"), "does not match"),
        (lambda p: p["speakers"][0].update(label=""), "does not match"),
        (lambda p: p["speakers"][0].pop("turns"), "'turns' is a required property"),
        (lambda p: p["speakers"][0].update(turns=-1), "less than the minimum"),
        (lambda p: p["speakers"][0].update(seconds=-0.5), "less than the minimum"),
        (lambda p: p["speakers"][0].update(from_me="yes"), "is not of type 'boolean'"),
        (
            lambda p: p["speakers"][0].update(person="019cadd3-6bc0-7dcd-9133-000000000402"),
            "Additional properties",
        ),
        (lambda p: p["diarization"].pop("engine"), "'engine' is a required property"),
        (lambda p: p["diarization"].pop("channels"), "'channels' is a required property"),
        (lambda p: p["diarization"].update(channels=0), "less than the minimum"),
        (lambda p: p["diarization"].update(audio="C41D"), "does not match"),
        (lambda p: p["diarization"]["spans"].update(media_type="text/plain"), "was expected"),
        (lambda p: p["diarization"].update(spans={"sha256": SPANS}), "is a required property"),
    ],
)
def test_what_the_amendment_does_not_allow(change: Any, says: str):
    payload = _dinner()["payload"]
    change(payload)
    errors = _errors(payload)
    assert errors and any(says in e for e in errors), errors


def test_diarization_alone_is_allowed():
    """`diarization` is required by `speakers`, not the reverse (RFC 0038 §2.2)."""
    payload = _dinner()["payload"]
    del payload["speakers"]
    assert _errors(payload) == []


def test_the_schema_file_says_what_rfc_0038_says():
    """The two fields in `schema/transcript-v1.schema.json` are the JSON Schema of RFC 0038 §2.2."""
    rfc = (ROOT / "rfcs" / "0038-speakers.md").read_text(encoding="utf-8")
    block = next(
        json.loads(m.group(1))
        for m in re.finditer(r"```json\n(\{.*?\})\n```", rfc, re.S)
        if "the fields RFC 0038 adds" in m.group(1) and "transcript/v1" in m.group(1)
    )
    for key in ("speakers", "diarization"):
        assert SCHEMA["properties"][key] == block["properties"][key]
    assert SCHEMA["dependentRequired"] == block["dependentRequired"]


def test_rfc_0004_carries_the_dated_amendment():
    text = (ROOT / "rfcs" / "0004-transcript-v1.md").read_text(encoding="utf-8")
    assert "Amendment 2026-10-14" in text
    assert "schema/transcript-v1.schema.json" in text and "RFC 0038" in text
