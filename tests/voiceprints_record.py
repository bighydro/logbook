"""A synthetic record with voices to embed (RFC 0038 §5), shared by the voiceprint tests.

Ines Nordmann of Oslo, who does not exist, records a dinner at home on Saturday 3 October 2026 (Kari
comes, a neighbour drops off a parcel) and a call with Ola on Tuesday 6 October, on two channels, as
`speakers_record` has them; here each recording has its own audio, and the audio is not sound: it is a
small JSON file saying who speaks when, which `FakeEmbedder` reads. No model is downloaded, loaded or
called: the fake "hears" the person whose second most of a clean piece is, and answers that person's
fixed vector, so a voice is embedded the same in every recording, as a real model would roughly do.

The vectors are distinctive on purpose (`VECTORS`): a test that must show no vector leaves the record
looks for their numbers, as the registry stores them (`stored`), in text and as packed floats."""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, dwell, utc
from speakers_record import (
    CALL,
    CALL_DAY,
    CALL_TEXT,
    DINNER,
    DINNER_DAY,
    DINNER_TEXT,
    KARI,
    OLA,
    ROOM,
    TWO_CHANNELS,
    call,
    event,
    message,
    people,
    transcript,
)

from logbook.core import attachments, sealing, speakers, voiceprints
from logbook.core.store import Logbook

RATE = 10  # the fake audio's samples per second
DIM = 4
# whose voice → the vector the fake model answers for it (raw: the registry makes it a unit vector)
VECTORS: dict[str, tuple[float, ...]] = {
    "ines": (0.918273, 0.112358, -0.271828, 0.141421),
    "kari": (-0.161803, 0.979797, 0.057721, -0.090909),
    "ola": (0.031415, -0.271801, 0.951413, 0.123987),
    "neighbour": (0.333331, 0.333332, 0.333333, -0.8125),
}
WHO = sorted(VECTORS)
DIGEST = "f" * 64  # the fake model's weights, as `model_sha256` names them

# who speaks in each segment of `speakers_record`'s texts (segment i is seconds 5i to 5i+4)
DINNER_VOICES = {"S1": "ines", "S2": "kari", "S3": "neighbour"}
CALL_VOICES = {"mic": "ines", "system": "ola"}


class FakeEmbedder:
    """`voiceprints.Embedder` without a model: `load` reads the fake audio (`audio_bytes`), `embed`
    answers the vector of whoever speaks most of the pieces' samples. Records every call."""

    def __init__(self, model: str = voiceprints.MODEL, digest: str = DIGEST, dim: int = DIM) -> None:
        self.model = model
        self.digest = digest
        self.dim = dim
        self.loaded: list[str] = []
        self.embedded: list[tuple[tuple[float, float], ...]] = []

    def load(self, path: Path) -> tuple[list[int], int]:
        data = json.loads(Path(path).read_bytes())
        self.loaded.append(Path(path).name)
        end = max((float(t) for _f, t, _w in data["who"]), default=0.0)
        samples = [0] * math.ceil(end * RATE)
        for start, stop, who in data["who"]:
            for i in range(int(start * RATE), min(len(samples), int(stop * RATE))):
                samples[i] = WHO.index(who) + 1
        return samples, RATE

    def embed(self, samples: Sequence[int], rate: int, pieces: Sequence[tuple[float, float]]) -> list[float]:
        self.embedded.append(tuple(pieces))
        counts: dict[int, int] = {}
        for start, end in pieces:
            for code in samples[int(start * rate) : int(end * rate)]:
                if code:
                    counts[code] = counts.get(code, 0) + 1
        if not counts:
            return [0.0] * self.dim
        who = WHO[max(sorted(counts), key=lambda c: counts[c]) - 1]
        return list(VECTORS[who][: self.dim])


def audio_bytes(said: Sequence[tuple[str, str]], voices: dict[str, str]) -> bytes:
    """The fake audio of a text `speakers_record` stores: segment i spoken by `voices[label]` from 5i
    to 5i+4 seconds."""
    who = [[float(i * 5), float(i * 5 + 4), voices[label]] for i, (label, _text) in enumerate(said)]
    return json.dumps({"fake-audio": 1, "who": who}, sort_keys=True).encode("utf-8")


def store_text(lb: Logbook, said: Sequence[tuple[str, str]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """As `speakers_record.stored_text`, through `Logbook.attach`, so a sealed record seals them."""
    data = "\n".join(text for _label, text in said).encode("utf-8") + b"\n"
    content = attachments.reference(data, "text/plain")
    lb.attach(data)
    segments = [
        {"from": float(i * 5), "to": float(i * 5 + 4), "speaker": label} for i, (label, _t) in enumerate(said)
    ]
    document = {
        "format": speakers.FORMAT,
        "content": content["sha256"],
        "segments": segments,
        "turns": segments,
    }
    raw = speakers.spans_bytes(document)
    lb.attach(raw)
    return content, attachments.reference(raw, speakers.MEDIA_TYPE)


def seal(lb: Logbook, monkeypatch: pytest.MonkeyPatch, folder: Path) -> Logbook:
    """Make `lb` a record that names two recipients, the first identity where
    `LOGBOOK_IDENTITY_FILE` points (as `logbook key init` would leave it); a fresh `Logbook`."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _secret, recipient in pairs]
    lb._save_meta(meta)
    path = folder / "keys" / "owner.txt"
    sealing.write_identity_file(path, pairs[0][0], "test identity")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    return Logbook(lb.root)


def voiced_record(lb: Logbook, *, audio: bool = True) -> dict[str, str]:
    """The dinner and the call of `speakers_record.dinner_record`, each with its own fake audio in
    the store; the people, Kari's calendar entry and message, the owner at home. Returns the audio
    digests by transcript id."""
    dinner_content, dinner_spans = store_text(lb, DINNER_TEXT)
    call_content, call_spans = store_text(lb, CALL_TEXT)
    sounds: dict[str, str] = {}
    if audio:
        for line_id, said, voices in ((DINNER, DINNER_TEXT, DINNER_VOICES), (CALL, CALL_TEXT, CALL_VOICES)):
            data = audio_bytes(said, voices)
            lb.attach(data)
            sounds[line_id] = attachments.digest(data)
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
                content=dinner_content,
                spans=dinner_spans,
                audio=sounds.get(DINNER),
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
                audio=sounds.get(CALL),
            ),
        ]
    )
    return sounds


def stored(who: str) -> tuple[float, ...]:
    """The vector the registry stores for `who`'s voice: the fake's, a unit vector, rounded."""
    return voiceprints.unit(VECTORS[who], DIM)


def as_text(vector: Sequence[float]) -> list[str]:
    """How the numbers of a vector read in JSON, from the point on (`.918273`): the leading `0` or
    `-0` dropped, so a match is not the accident of a short number, and the point kept, so it is not
    the accident of a run of digits in a hash, a salt or an id, none of which holds a point."""
    return ["." + json.dumps(v).lstrip("-").removeprefix("0.") for v in vector if len(json.dumps(v)) > 6]


def as_bytes(vector: Sequence[float]) -> list[bytes]:
    """The numbers of a vector packed as a model or numpy would hold them: float32 and float64."""
    return [struct.pack(f"<{fmt}", v) for v in vector for fmt in ("f", "d")]
