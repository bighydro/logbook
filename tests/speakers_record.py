"""A synthetic record of voices and who they are (RFC 0038 §3, §4), shared by the attribution tests.

Ines Nordmann of Oslo, who does not exist, records a dinner at home on Saturday 3 October 2026 (Kari
comes, a neighbour drops off a parcel) and a call with Ola on Tuesday 6 October, on two channels.
Every id, address and number is invented: the addresses are at example.org and the numbers in the
UK's reserved fictional range, 07700 900xxx. The transcripts carry their ids (a draft may bring its
own), so a test names a voice as `<id>#<label>` the way a `speaker` ref does."""

from __future__ import annotations

import json
from typing import Any

from persona import HOME, TZ, dwell, utc

from logbook.core import attachments, speakers
from logbook.core.store import Logbook

DINNER_DAY, CALL_DAY = "2026-10-03", "2026-10-06"
OLA_ID = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
KARI_ID = "019cadd3-6bc0-7dcd-9133-000000000402"
OLA = {"email": "ola@example.org", "phone": "+447700900101", "name": "Ola Nordmann"}
KARI = {"email": "kari@example.org", "phone": "+447700900102", "name": "Kari Nordmann"}
DINNER = "019cadd3-6bc0-7dcd-9133-0000000004a1"
CALL = "019cadd3-6bc0-7dcd-9133-0000000004a2"
CALL_LINE = "019cadd3-6bc0-7dcd-9133-0000000004e3"
ROOM = [
    {"label": "S1", "seconds": 1862.4, "turns": 3},
    {"label": "S2", "seconds": 861.0, "turns": 2},
    {"label": "S3", "seconds": 41.5, "turns": 1},
]
TWO_CHANNELS = [
    {"label": "mic", "seconds": 201.7, "turns": 2, "channel": "mic", "from_me": True},
    {"label": "system", "seconds": 188.3, "turns": 2, "channel": "system"},
]
DINNER_TEXT = [
    ("S1", "Har du sett hvor høyt vannet står?"),
    ("S2", "Beklager, ferja var sen."),
    ("S1", "I'll send you the photos tomorrow."),
    ("S2", "I will bring the cake on Friday."),
    ("S3", "Hei, jeg skal bare levere en pakke."),
    ("S1", "Takk for maten."),
]
CALL_TEXT = [
    ("mic", "Hei Ola."),
    ("system", "I'll call the yard tomorrow."),
    ("mic", "I will book the ferry on Monday."),
    ("system", "Fint, vi snakkes."),
]


def resolution(ref: tuple[str, str], entity_id: str, label: str, at: str = "2026-09-01T08:00:00Z") -> dict:
    return {
        "at": at,
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": ref[0], "value": ref[1]},
            "entity": {"type": "person", "id": entity_id, "registry": "logbook"},
            "label": label,
            "method": "owner",
        },
    }


def people() -> list[dict[str, Any]]:
    """Ola and Kari, each resolved from their address and their number."""
    return [
        resolution(("email", OLA["email"]), OLA_ID, OLA["name"]),
        resolution(("phone", OLA["phone"]), OLA_ID, OLA["name"]),
        resolution(("email", KARI["email"]), KARI_ID, KARI["name"]),
        resolution(("phone", KARI["phone"]), KARI_ID, KARI["name"]),
    ]


def transcript(
    id_: str,
    at: str,
    end: str | None,
    title: str,
    voices: list[dict[str, Any]] | None,
    *,
    raw_id: str | None = None,
    participants: list[dict[str, Any]] | None = None,
    content: dict[str, Any] | None = None,
    spans: dict[str, Any] | None = None,
    audio: str | None = None,
    tier: int = 2,
    supersedes: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "transcript/v1",
        "provider": "mlx-whisper",
        "raw_id": raw_id or f"memo-{id_[-4:]}",
        "title": title,
        "participants": participants or [],
    }
    if content is not None:
        payload["content"] = content
    if voices is not None:
        payload["speakers"] = voices
        diarization: dict[str, Any] = {
            "engine": "pyannote",
            "channels": 2 if any(v.get("channel") for v in voices) else 1,
        }
        if audio is not None:
            diarization["audio"] = audio
        if spans is not None:
            diarization["spans"] = spans
        payload["diarization"] = diarization
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return {
        "id": id_,
        "at": at,
        "end": end,
        "tz": TZ,
        "source": "transcription",
        "kind": "transcript",
        "tier": tier,
        "payload": payload,
    }


def attribution(
    transcript_id: str,
    label: str,
    entity_id: str,
    *,
    name: str | None = None,
    basis: str = "voice",
    consent: str | None = None,
    unnamed: bool = False,
    confidence: float | None = None,
    supersedes: str | None = None,
    alias_of: str | None = None,
    at: str = "2026-10-11T08:12:00Z",
    id_: str | None = None,
) -> dict[str, Any]:
    """A `speaker` resolution as RFC 0038 §11 writes one: a record already holding the owner's
    answer (a reader test's input; the review writes them through its own writer)."""
    payload: dict[str, Any] = {
        "schema": "resolution/v1",
        "ref": {"kind": "speaker", "value": f"{transcript_id}#{label}"},
    }
    if alias_of is not None:
        payload["alias_of"] = {"kind": "speaker", "value": alias_of}
    else:
        payload["entity"] = {"type": "person", "id": entity_id, "registry": "logbook"}
    if name is not None:
        payload["label"] = name
    payload.update({"method": "owner", "basis": basis})
    if unnamed:
        payload["unnamed"] = True
    if consent is not None:
        payload["consent"] = consent
    if confidence is not None:
        payload["confidence"] = confidence
    if supersedes is not None:
        payload["supersedes"] = supersedes
    payload["evidence"] = [transcript_id]
    draft = {"at": at, "source": "manual", "kind": "resolution", "tier": 2, "payload": payload}
    if id_ is not None:
        draft["id"] = id_
    return draft


def call(at: str, phone: str, seconds: int, id_: str = CALL_LINE) -> dict[str, Any]:
    return {
        "id": id_,
        "at": at,
        "source": "ios-calls",
        "kind": "call",
        "tier": 1,
        "payload": {
            "schema": "call/v1",
            "raw_id": f"c-{at}",
            "direction": "outgoing",
            "answered": seconds > 0,
            "duration_s": seconds,
            "counterparty": {"kind": "phone", "value": phone},
            "service": "cellular",
        },
    }


def message(at: str, phone: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"m-{at}",
            "sender": {"kind": "phone", "value": phone},
            "chat": {"id": phone, "type": "direct"},
            "text": text,
        },
    }


def event(at: str, end: str, title: str, attendees: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "at": at,
        "end": end,
        "source": "ios-calendar",
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"e-{at}",
            "title": title,
            "all_day": False,
            "attendees": attendees,
        },
    }


def stored_text(lb: Logbook, said: list[tuple[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The text of `said` (one segment a line, as `derive transcripts` writes it) and its spans file,
    both in the attachment store: (the content reference, the spans reference)."""
    data = "\n".join(text for _label, text in said).encode("utf-8") + b"\n"
    content = attachments.reference(data, "text/plain")
    attachments.write(lb.root, data)
    document = {
        "format": speakers.FORMAT,
        "content": content["sha256"],
        "segments": [
            {"from": float(i * 5), "to": float(i * 5 + 4), "speaker": label}
            for i, (label, _t) in enumerate(said)
        ],
        "turns": [
            {"from": float(i * 5), "to": float(i * 5 + 4), "speaker": label}
            for i, (label, _t) in enumerate(said)
        ],
    }
    raw = speakers.spans_bytes(document)
    attachments.write(lb.root, raw)
    return content, attachments.reference(raw, speakers.MEDIA_TYPE)


def audio_file(lb: Logbook, data: bytes = b"RIFF-not-really-audio") -> str:
    """Bytes standing in for a recording's audio in the store; its digest."""
    attachments.write(lb.root, data)
    return attachments.digest(data)


def dinner_record(lb: Logbook, *, with_text: bool = True, audio: bool = True) -> None:
    """The dinner and the call of the week, the people, Kari's calendar entry and her message that
    afternoon, the owner at home all evening and all Tuesday morning."""
    content = spans = None
    call_content = call_spans = None
    if with_text:
        content, spans = stored_text(lb, DINNER_TEXT)
        call_content, call_spans = stored_text(lb, CALL_TEXT)
    sound = audio_file(lb) if audio else None
    lb.append_many(
        [
            *people(),
            *dwell(DINNER_DAY, "16:00", "23:30", HOME),
            *dwell(CALL_DAY, "08:00", "10:30", HOME),
            message(utc(DINNER_DAY, "18:02"), KARI["phone"], "På vei!"),
            event(
                utc(DINNER_DAY, "19:30"),
                utc(DINNER_DAY, "22:00"),
                "Middag med Kari",
                [{"ref": {"kind": "email", "value": KARI["email"]}, "response": "accepted"}],
            ),
            transcript(
                DINNER,
                utc(DINNER_DAY, "19:40"),
                utc(DINNER_DAY, "20:52"),
                "Middag",
                ROOM,
                content=content,
                spans=spans,
                audio=sound,
            ),
            call(utc(CALL_DAY, "09:15"), OLA["phone"], 445),
            transcript(
                CALL,
                utc(CALL_DAY, "09:15"),
                utc(CALL_DAY, "09:22"),
                "Samtale",
                TWO_CHANNELS,
                content=call_content,
                spans=call_spans,
                audio=sound,
            ),
        ]
    )


def payload_json(line: dict[str, Any]) -> str:
    return json.dumps(line.get("payload"), sort_keys=True)
