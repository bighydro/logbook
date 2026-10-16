"""Who a voice is (RFC 0038 §3): the `speaker` ref, and how a reader joins a transcript's voices to
the `resolution/v1` lines that bind them.

A transcript line carries anonymous labels (`speakers`, §2); who a voice belongs to is a judgement,
made later by the owner alone, in a line of its own: one `resolution/v1` per voice whose `ref` is
`{kind: speaker, value: "<the transcript line's id>#<label>"}` (§3.1). The transcript is never
touched. The label means something only inside its line, so a transcript heard again is a new line
with new labels and new refs: an attribution of the old line names nothing on the new one.

A reader joins through the identities it already reads (`resolve.identities_from`), which carry,
for a `speaker` ref, the fields of §3.2: the deciding line's `entity`, `label` and `unnamed`, and the
voice's own standing line's `basis`, `consent` and `confidence`. Each voice of a standing transcript
is then one of (§3.4):

- **the owner's**: bound to one of the owner's entities, or `from_me` with no attribution standing
  (§3.3 rule 4: the source's statement; a standing attribution wins over it and nothing else does);
- **a person's**: bound to a person, named by their label;
- **unnamed**: bound to a person the owner declined to name (`unnamed: true`); counted, never named;
- **not yet named**: no line, read as a guest's and shown as the source spoke it (its label, or the
  name the source displayed).

A voice of the `system` channel is the far end of a call: it speaks in the recording and was not
there (`far_end`). Readers ask; this module decides nothing about company or promises.

`voiced_turns` cuts a transcript's text into turns by voice, through the spans file (§2.3), for a
reader that must know whose each sentence is (`promises`). It reads two files of the attachment
store and gives None whenever they do not agree (a spans file that does not number the content's
segments, or labels another text): the reader then reads the text as it did before.

Nothing here writes a line. The one writer of an attribution is the review
(`logbook.contrib.speakers_review.answer`)."""

from __future__ import annotations

import json
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import sealing, speakers
from .chain import Line
from .transcripts import Turn

if TYPE_CHECKING:
    from .resolve import Identity, Ref
    from .store import Logbook

SPEAKER = "speaker"  # the ref kind (§3.1)
BASES = ("channel", "voice", "text")  # §1, §3.2
CONSENTS = ("yes", "no", "unknown")  # §7; absent reads as unknown
UNKNOWN = "unknown"
OWNER, PERSON, UNNAMED, NOT_YET_NAMED = "owner", "person", "unnamed", "not yet named"
PERSON_TYPES = (None, "person")
ASSERTED = 1.0  # RFC 0006: a confidence that is absent means asserted
SHOWN_UNNAMED = "unnamed"


def ref_value(line_id: str, label: str) -> str:
    """`<line id>#<label>`, the value of a `speaker` ref (§3.1)."""
    return f"{line_id}#{label}"


def ref_of(line_id: str, label: str) -> Ref:
    return (SPEAKER, ref_value(line_id, label))


def split(value: str) -> tuple[str, str] | None:
    """(the transcript line's id, the label) of a `speaker` ref's value, split at its first `#`
    (a label never holds one); None for a value that is not one."""
    line_id, sep, label = value.partition("#")
    if not sep or not line_id or not speakers.is_label(label):
        return None
    return line_id, label


def speaker_fields(own: Mapping[str, Any], deciding: Mapping[str, Any]) -> dict[str, Any]:
    """What `resolve.identities_from` adds to a `speaker` ref's identity: `unnamed` from the line the
    alias walk stops on (a voice said to be the same as an unnamed one is unnamed), `basis`,
    `consent` and `confidence` from the voice's own standing line (statements about this voice in
    this recording). A value that is not one the profile allows is left out (SPEC §5: a reader never
    fails on a payload it cannot read)."""
    basis = own.get("basis")
    consent = own.get("consent")
    confidence = own.get("confidence")
    return {
        "unnamed": deciding.get("unnamed") is True,
        "basis": basis if basis in BASES else None,
        "consent": consent if consent in CONSENTS else None,
        "confidence": float(confidence)
        if isinstance(confidence, int | float)
        and not isinstance(confidence, bool)
        and math.isfinite(confidence)
        and 0 <= confidence <= 1
        else None,
    }


@dataclass(frozen=True)
class Heard:
    """One voice of a transcript line, joined to who it is."""

    voice: speakers.Voice
    ref: str  # `<line id>#<label>`
    state: str  # OWNER, PERSON, UNNAMED or NOT_YET_NAMED
    entity: str | None  # the entity bound (the owner's, a person's, an unnamed person's); None not yet named
    name: str | None  # a person's label; None for the owner, the unnamed and a voice not yet named
    basis: str | None  # the line's; `channel` for a `from_me` voice no line binds; None not yet named
    consent: str | None  # the line's, absent read as `unknown`; None for the owner and not yet named
    confidence: float | None  # the line's; None when asserted or not yet named

    @property
    def label(self) -> str:
        return self.voice.label

    @property
    def bound(self) -> bool:
        """Whether the voice is someone's: bound by a line, or the owner's by `from_me`."""
        return self.state != NOT_YET_NAMED

    @property
    def far_end(self) -> bool:
        """The voice of the far end of a call (§3.4, `with`): on the `system` channel."""
        return far_end(self.voice)

    @property
    def shown(self) -> str:
        """`you`; a person's label; `unnamed`; else the voice as the source spoke it."""
        if self.state == OWNER:
            return speakers.OWNER
        if self.state == PERSON and self.name:
            return self.name
        if self.state == UNNAMED:
            return SHOWN_UNNAMED
        return self.voice.name or self.voice.label

    def reads_as(self) -> float:
        """The confidence a reader gives the voice's presence: the line's, else asserted."""
        return ASSERTED if self.confidence is None else self.confidence

    def to_json(self) -> dict[str, Any]:
        """`{label, person, name, seconds, basis, consent, owner}` (§3.4, `day --json`): `person` the
        entity bound (the owner's for the owner), null for an unnamed voice and one not yet named;
        `name` a person's label, the name the source displayed for a voice not yet named, else null."""
        return {
            "label": self.voice.label,
            "person": self.entity if self.state in (OWNER, PERSON) else None,
            "name": self.name if self.state == PERSON else self.voice.name if not self.bound else None,
            "seconds": self.voice.seconds,
            "basis": self.basis,
            "consent": self.consent,
            "owner": self.state == OWNER,
        }


def far_end(voice: speakers.Voice) -> bool:
    """A voice of the `system` channel: its `channel`, else a label of it (`system`, `system.2`)."""
    channel = voice.channel or voice.label.split(".")[0]
    return channel == speakers.SYSTEM


class Voices:
    """The voices of transcript lines joined to the identities of one reading. `owner_entities` are
    the owner's entity ids (`present.Owner.entities`), `owner_id` the record's own (`logbook.json`),
    which a `from_me` voice is bound to without a line. The labels of the people are taken once, on
    the first line with voices."""

    def __init__(
        self,
        identities: Mapping[Ref, Identity],
        owner_entities: Collection[str] = (),
        owner_id: str | None = None,
    ) -> None:
        self.identities = identities
        self.owner_entities = frozenset(owner_entities) | ({owner_id} if owner_id else frozenset())
        self.owner_id = owner_id or next(iter(sorted(owner_entities)), None)
        self._labels: dict[str, str] | None = None

    def labels(self) -> dict[str, str]:
        """entity → the first label a resolution gives it (a person's name as readers show it), taken
        once per `Voices`, on the first voice bound to a person: a reader that asks for many lines
        keeps one `Voices`."""
        if self._labels is None:
            found: dict[str, str] = {}
            for who in self.identities.values():
                if who.entity and who.label and who.type in PERSON_TYPES:
                    found.setdefault(who.entity, who.label)
            self._labels = found
        return self._labels

    def of(self, line: Line) -> list[Heard]:
        """The voices of one transcript line, in the line's order; none for a line without
        `speakers`. The caller passes standing lines only (§3.3 rule 5)."""
        payload = line.get("payload") or {}
        found = speakers.voices(payload)
        if not found:
            return []
        line_id = str(line.get("id"))
        return [self.heard(line_id, voice) for voice in found]

    def heard(self, line_id: str, voice: speakers.Voice) -> Heard:
        ref = ref_value(line_id, voice.label)
        who = self.identities.get((SPEAKER, ref))
        if who is not None and who.entity and who.type in PERSON_TYPES:
            consent = who.consent or UNKNOWN
            if who.entity in self.owner_entities:
                return Heard(voice, ref, OWNER, who.entity, None, who.basis, who.consent, who.confidence)
            if who.unnamed:
                return Heard(voice, ref, UNNAMED, who.entity, None, who.basis, consent, who.confidence)
            name = self.labels().get(who.entity) or who.label
            return Heard(voice, ref, PERSON, who.entity, name, who.basis, consent, who.confidence)
        if voice.from_me:
            return Heard(voice, ref, OWNER, self.owner_id, None, "channel", None, None)
        return Heard(voice, ref, NOT_YET_NAMED, None, None, None, None, None)


# -- the text by voice ----------------------------------------------------------------------------------


def voiced_turns(lb: Logbook, line: Line) -> list[Turn] | None:
    """The text of a transcript with voices as turns by voice: each segment of the content (§2.3,
    `speakers.segment_texts`) with the label the spans file gives it, consecutive segments of one
    voice joined; a segment no voice spoke is a turn with no speaker. None when the line has no
    voices or no spans file, when either file is not in the store, or when the spans file labels
    another text or does not number the content's segments: the reader then reads the text as it
    did before (§2.3: a spans file that does not number them is wrong and says nothing of whose)."""
    payload = line.get("payload") or {}
    if not speakers.voices(payload):
        return None
    content = payload.get("content")
    diarization = payload.get("diarization")
    spans = diarization.get("spans") if isinstance(diarization, dict) else None
    if not isinstance(content, dict) or not isinstance(spans, dict):
        return None
    text = _stored(lb, content.get("sha256"))
    found = _stored(lb, spans.get("sha256"))
    if text is None or found is None:
        return None
    try:
        document = json.loads(found.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(document, dict) or document.get("content") != content.get("sha256"):
        return None
    segments = document.get("segments")
    texts = speakers.segment_texts(text, str(content.get("media_type") or ""))
    if not isinstance(segments, list) or texts is None or len(texts) != len(segments):
        return None
    labels = {v.label for v in speakers.voices(payload)}
    turns: list[Turn] = []
    for said, segment in zip(texts, segments, strict=True):
        who = segment.get("speaker") if isinstance(segment, dict) else None
        who = who if isinstance(who, str) and who in labels else None
        if not said.strip():
            continue
        if turns and turns[-1].speaker == who:
            turns[-1] = Turn(who, f"{turns[-1].text}\n{said}", turns[-1].start_s)
        else:
            turns.append(Turn(who, said))
    return turns


def _stored(lb: Logbook, sha256: object) -> bytes | None:
    if not isinstance(sha256, str) or not speakers.is_digest(sha256):
        return None
    if not (lb.root / "attachments" / sha256).is_file():
        return None
    try:
        return lb.attachment_bytes(sha256)
    except (OSError, sealing.SealError):
        return None
