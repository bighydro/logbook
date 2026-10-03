"""story/v1 (RFC 0028, draft): a *told* story, as distinct from an observed event.

A story is something one person told another about a time the record did not see: "in 1961 we
moved to the house by the lake". The line is on the day it was **told** (`at` is `told_at`, the
one instant anyone observed); what it is **about** is `refers_to`, a claim at the precision the
teller gave it (a year, a month, a day, a decade, or a phrase such as "before the war" that no
reader places on a calendar). `teller` and `listener` are RFC 0006 refs with the label known at
write time, so the line reads without any registry and resolves through the record's resolution
lines like any other ref. Tier 2 by default: it carries someone else's words.

`logbook add story <file> --teller <ref> --listener <ref> [--refers-to …] [--confidence …]` reads
a text or Markdown file (a leading `---` front-matter block may carry the same fields; a flag
wins over it) or a transcript/v1 JSON (the text is the transcript's, the transcript's bytes go to
the SPEC §1.1 store and the line points at them), one story per file. `raw_id` is `story:<sha256
of the file's bytes>`, so the same file added twice is one line.

Readers: `show` prints a story on its told day as `📖 refers to <when> — told by <name> to
<name>`; `day <date>` lists the standing stories whose `refers_to` covers the date under their own
heading, never in the timeline (`about`). Nothing here opens a socket; the only file read is the
one named at the command line."""

from __future__ import annotations

import calendar
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .attachments import digest, reference
from .chain import Line
from .export import parse_day
from .resolve import Identity, Ref
from .store import RETRACTION, now_utc, retractions

KIND = "story"
SCHEMA = "story/v1"
TIER = 2
SOURCE = "manual"  # the envelope's source: the owner typed the command
CONFIDENCES = ("sure", "fuzzy", "disputed")  # as the teller states it
PRECISIONS = ("day", "month", "year", "decade", "phrase")
MEDIA = ("conversation", "voice-memo", "interview", "letter", "written")  # payload `source`, open vocabulary
REF_KINDS = ("email", "phone", "handle", "provider_id", "device_id", "domain", "line")  # RFC 0006
TRANSCRIPT_SCHEMA = "transcript/v1"
TRANSCRIPT_MEDIUM = "voice-memo"  # a story read out of a transcript was spoken
NO_TIME = "an unsaid time"  # `refers to …` for a story that names no time
TEXT_CHARS = 72  # a story's first line as the Day lists it, cut like a note's
BOOK = "\U0001f4d6"  # 📖
EM_DASH = "—"
DOT = " · "

# the fields a front-matter block may carry, each with the spellings it is read under
FRONT_KEYS = {
    "title": ("title",),
    "teller": ("teller", "told_by", "told-by"),
    "listener": ("listener", "told_to", "told-to"),
    "refers_to": ("refers_to", "refers-to", "about", "when"),
    "told_at": ("told_at", "told-at", "at", "recorded_at"),
    "confidence": ("confidence",),
    "source": ("source", "medium"),
}
YEAR = re.compile(r"^\d{4}$")
MONTH = re.compile(r"^(\d{4})-(\d{2})$")
DECADE = re.compile(r"^(\d{3})0s$")
PHONE = re.compile(r"^\+[\d\s().-]{4,}$")
HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")


class StoryError(ValueError):
    """A file or a flag that does not make a story; the message is for the command line."""


# -- refers_to -----------------------------------------------------------------------------------------------


def parse_refers_to(text: str) -> dict[str, Any]:
    """`1961`, `1961-05`, `1961-05-04` or `1950s` as `{text, from, to, precision}` with the span's
    first and last day; any other words are a phrase (`before the war`), kept as told with no
    dates. Words that begin with a digit must be one of the four shapes: `1961-5` is a typo, not a
    phrase. `ValueError` for those and for nothing at all."""
    given = " ".join(text.split())
    if not given:
        raise ValueError("refers_to: nothing given")
    if YEAR.match(given):
        return {"text": given, "from": f"{given}-01-01", "to": f"{given}-12-31", "precision": "year"}
    if (m := MONTH.match(given)) is not None:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"refers_to: not a month (YYYY-MM): {given!r}")
        last = calendar.monthrange(year, month)[1]
        return {"text": given, "from": f"{given}-01", "to": f"{given}-{last:02d}", "precision": "month"}
    if (m := DECADE.match(given)) is not None:
        return {
            "text": given,
            "from": f"{m.group(1)}0-01-01",
            "to": f"{m.group(1)}9-12-31",
            "precision": "decade",
        }
    if given[0].isdigit():
        try:
            day = parse_day(given).isoformat()
        except ValueError as e:
            raise ValueError(
                "refers_to: not a year (1961), a month (1961-05), a day (1961-05-04) or a decade (1950s):"
                f" {given!r}"
            ) from e
        return {"text": given, "from": day, "to": day, "precision": "day"}
    return {"text": given, "from": None, "to": None, "precision": "phrase"}


def covers(refers_to: Mapping[str, Any] | None, day: str) -> bool:
    """Whether the span of `refers_to` holds the local day `day` (YYYY-MM-DD); a phrase, or no
    `refers_to`, covers no day."""
    if not isinstance(refers_to, Mapping):
        return False
    start, end = refers_to.get("from"), refers_to.get("to")
    return isinstance(start, str) and isinstance(end, str) and start <= day <= end


def when_text(payload: Mapping[str, Any]) -> str:
    """The time a story is about, as told: `1961`, `before the war`; `an unsaid time` for none."""
    refers_to = payload.get("refers_to")
    text = refers_to.get("text") if isinstance(refers_to, Mapping) else None
    return str(text) if isinstance(text, str) and text else NO_TIME


# -- people --------------------------------------------------------------------------------------------------

REF_ORDER = {kind: i for i, kind in enumerate(REF_KINDS)}  # an address before a number before a handle


def parse_person(text: str, identities: Mapping[Ref, Identity]) -> dict[str, Any]:
    """`--teller`/`--listener`, or a front-matter value, as `{ref: {kind, value}, name?}`:
    `kind:value` (an RFC 0006 kind), an address, a `+` number, or a name the record's resolution
    lines make one person, whose first ref (an address before a number) stands for them. `name`
    is the label the record knows, left out for a ref it does not. `StoryError` for nobody,
    several people, or nothing."""
    given = " ".join(text.split())
    if not given:
        raise StoryError("a person is needed: an address, a +number, kind:value or a name")
    kind, colon, value = given.partition(":")
    ref: Ref | None = None
    if colon and kind in REF_KINDS and value:
        ref = (kind, value.strip())
    elif "@" in given and " " not in given:
        ref = ("email", given)
    elif PHONE.match(given):
        ref = ("phone", "+" + re.sub(r"\D", "", given))
    if ref is None:
        entity, label, refs = _by_name(given, identities)
        if not refs:
            raise StoryError(f"{given!r} is a person with no ref to name them by; give kind:value")
        ref = min(refs, key=lambda r: (REF_ORDER.get(r[0], len(REF_ORDER)), r[1]))
        return {"ref": {"kind": ref[0], "value": ref[1]}, "name": label or entity}
    out: dict[str, Any] = {"ref": {"kind": ref[0], "value": ref[1]}}
    who = identities.get(ref)
    if who is not None and who.label:
        out["name"] = who.label
    return out


def _by_name(name: str, identities: Mapping[Ref, Identity]) -> tuple[str, str | None, list[Ref]]:
    """The one person `name` means: an entity id, a label (case aside), or a unique first or
    last name, as `people` and the pages read a name."""
    people: dict[str, tuple[str | None, list[Ref]]] = {}
    for ref, who in identities.items():
        if who.entity and who.type in (None, "person"):
            known = people.setdefault(who.entity, (who.label, []))
            if known[0] is None and who.label:
                people[who.entity] = (who.label, known[1])
            known[1].append(ref)
    if name in people:
        return name, *people[name]
    wanted = name.casefold()
    exact = [e for e, (label, _) in people.items() if label and " ".join(label.split()).casefold() == wanted]
    loose = [
        e for e, (label, _) in people.items() if label and wanted in (w.casefold() for w in label.split())
    ]
    found = exact or loose
    if len(found) > 1:
        names = sorted(str(people[e][0]) for e in found)
        raise StoryError(f"{name!r} names several people: {', '.join(names)}")
    if not found:
        raise StoryError(
            f"{name!r} is nobody the record's resolution lines name; give an address or kind:value"
        )
    return found[0], *people[found[0]]


def person_text(person: object, names: Mapping[Ref, str] | None) -> str:
    """How a teller or listener is named: the record's label for the ref (RFC 0006), else the
    name written at the time, else the ref's value; `names` None is `--raw`, the value as given."""
    ref = person.get("ref") if isinstance(person, Mapping) else None
    kind = ref.get("kind") if isinstance(ref, Mapping) else None
    value = ref.get("value") if isinstance(ref, Mapping) else None
    if names is not None:
        label = names.get((str(kind), str(value))) if kind is not None and value is not None else None
        written = person.get("name") if isinstance(person, Mapping) else None
        if label:
            return label
        if isinstance(written, str) and written:
            return written
    return str(value) if value is not None else "someone"


# -- the file ------------------------------------------------------------------------------------------------


@dataclass
class Parsed:
    """What one file says: the story's text, and every field the file itself carries."""

    text: str
    raw_id: str
    fields: dict[str, str] = field(default_factory=dict)  # front matter, by canonical key
    title: str | None = None
    told_at: str | None = None  # a transcript's own start
    source: str | None = None  # a medium the file implies (a transcript was spoken)
    transcript: dict[str, Any] | None = None  # the §1.1 reference of a transcript
    to_store: bytes | None = None  # the transcript's bytes, when the file held them inline
    transcript_key: tuple[str, str] | None = None  # (source, raw_id) of the transcript/v1 line


def read_file(path: Path, timezone: str | None = None) -> Parsed:
    """A text or Markdown file, or a transcript/v1 JSON; `StoryError` for anything else."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise StoryError(f"cannot read {path}: {e.strerror or e}") from e
    raw_id = f"story:{digest(data)}"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise StoryError(f"{path.name} is not UTF-8 text") from e
    if path.suffix.casefold() == ".json" or text.lstrip().startswith("{"):
        return _transcript(text, raw_id, timezone)
    return _prose(text, raw_id)


def _prose(text: str, raw_id: str) -> Parsed:
    parsed = Parsed(text="", raw_id=raw_id)
    body = _front_matter(text, parsed.fields)
    lines = body.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and (heading := HEADING.match(lines[0])) is not None:  # a leading heading is the title
        parsed.title = heading.group(1)
        lines.pop(0)
    parsed.text = "\n".join(line.rstrip() for line in lines).strip("\n")
    if not parsed.text.strip():
        raise StoryError("the file has no text after its front matter")
    if "title" in parsed.fields:
        parsed.title = parsed.fields.pop("title")
    return parsed


def _front_matter(text: str, fields: dict[str, str]) -> str:
    """Read a leading `---` block of `key: value` lines into `fields`; the rest of the text."""
    if not text.startswith("---\n"):
        return text
    close = text.find("\n---", 4)
    if close < 0:
        return text
    block, rest = text[4:close], text[close + 4 :]
    by_spelling = {spelling: key for key, spellings in FRONT_KEYS.items() for spelling in spellings}
    for raw in block.split("\n"):
        name, sep, value = raw.partition(":")
        key = by_spelling.get(name.strip().casefold())
        if sep and key is not None and value.strip():
            fields[key] = value.strip().strip("\"'")
    return rest.lstrip("\n")


def _transcript(text: str, raw_id: str, timezone: str | None) -> Parsed:
    """A transcript/v1 JSON as the transcript adapter reads one: a draft (`at`, `payload`) or a
    bare payload. The story's text is the transcript's text when it is inline, else its summary,
    else its title; the content is kept as the story's `transcript`."""
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise StoryError("not JSON; a story file is text, Markdown or a transcript/v1 JSON") from e
    payload = obj.get("payload") if isinstance(obj, dict) else None
    if isinstance(obj, dict) and obj.get("schema") == TRANSCRIPT_SCHEMA:
        payload, obj = obj, {}
    if not isinstance(payload, dict) or payload.get("schema") != TRANSCRIPT_SCHEMA:
        raise StoryError(
            f"not a {TRANSCRIPT_SCHEMA} JSON; a story file is text, Markdown or a transcript/v1 JSON"
        )
    parsed = Parsed(text="", raw_id=raw_id, source=TRANSCRIPT_MEDIUM)
    if isinstance(obj.get("at"), str):
        parsed.told_at = _stamp(obj["at"], timezone)
    title = payload.get("title")
    parsed.title = title if isinstance(title, str) and title.strip() else None
    content = payload.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        media_type = str(content.get("media_type") or "text/markdown")
        parsed.to_store = content["text"].encode("utf-8")
        parsed.transcript = reference(parsed.to_store, media_type)
        parsed.text = content["text"].strip()
    elif isinstance(content, dict) and isinstance(content.get("sha256"), str):
        parsed.transcript = {k: content[k] for k in ("sha256", "path", "bytes", "media_type") if k in content}
    if not parsed.text:
        for key in ("summary", "title"):
            if isinstance(payload.get(key), str) and payload[key].strip():
                parsed.text = payload[key].strip()
                break
    if not parsed.text:
        raise StoryError("the transcript has no text, summary or title to tell the story with")
    source = obj.get("source") if isinstance(obj.get("source"), str) else payload.get("provider")
    if isinstance(source, str) and isinstance(payload.get("raw_id"), str):
        parsed.transcript_key = (source, payload["raw_id"])
    return parsed


def _stamp(value: str, timezone: str | None) -> str | None:
    """`value` as RFC3339 UTC; a zone-less time is read in `timezone` (UTC when none)."""
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(timezone) if timezone else UTC)
    when = when.astimezone(UTC)
    return (
        when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        if when.microsecond
        else when.strftime("%Y-%m-%dT%H:%M:%SZ")
    )


# -- the line ------------------------------------------------------------------------------------------------


def draft(
    parsed: Parsed,
    identities: Mapping[Ref, Identity],
    *,
    teller: str | None = None,
    listener: str | None = None,
    refers_to: str | None = None,
    confidence: str | None = None,
    at: str | None = None,
    tier: int | None = None,
    timezone: str | None = None,
    transcript_line: str | None = None,
) -> dict[str, Any]:
    """One story/v1 draft from a parsed file and the flags; a flag wins over the file's own field.
    `StoryError` when no teller or listener is given anywhere, when `refers_to` or `confidence`
    is not what it should be, or when the tier is 1."""
    fields = parsed.fields
    teller_text = teller or fields.get("teller")
    listener_text = listener or fields.get("listener")
    if not teller_text:
        raise StoryError("a story needs --teller <ref> (or `teller:` in the file's front matter)")
    if not listener_text:
        raise StoryError("a story needs --listener <ref> (or `listener:` in the file's front matter)")
    if tier is not None and tier not in (2, 3):
        raise StoryError("a story carries someone else's words: tier 2 (the default) or 3, never 1")
    when_text_ = refers_to or fields.get("refers_to")
    refers: dict[str, Any] | None = None
    if when_text_:
        try:
            refers = parse_refers_to(when_text_)
        except ValueError as e:
            raise StoryError(str(e)) from e
    sure = confidence or fields.get("confidence")
    if sure is not None:
        sure = sure.strip().casefold()
        if sure not in CONFIDENCES:
            raise StoryError(f"--confidence is one of {', '.join(CONFIDENCES)}, not {sure!r}")
    told_at = at or (_stamp(fields["told_at"], timezone) if fields.get("told_at") else None) or parsed.told_at
    if fields.get("told_at") and told_at is None:
        raise StoryError(f"told_at is not a time: {fields['told_at']!r}")
    told_at = told_at or now_utc()
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": parsed.raw_id}
    if parsed.title:
        payload["title"] = parsed.title
    payload["text"] = parsed.text
    payload["told_at"] = told_at
    if refers is not None:
        payload["refers_to"] = refers
    payload["teller"] = parse_person(teller_text, identities)
    payload["listener"] = parse_person(listener_text, identities)
    if sure is not None:
        payload["confidence"] = sure
    medium = fields.get("source") or parsed.source
    if medium:
        payload["source"] = medium
    if parsed.transcript is not None:
        payload["transcript"] = parsed.transcript
    if transcript_line is not None:
        payload["transcript_line"] = transcript_line
    return {
        "at": told_at,
        "end": None,
        "source": SOURCE,
        "kind": KIND,
        "tier": tier or TIER,
        "payload": payload,
    }


# -- readers -------------------------------------------------------------------------------------------------


def text(payload: Mapping[str, Any], names: Mapping[Ref, str] | None) -> str:
    """A story as `show` prints it: `📖 refers to 1961 — told by Ola Nordmann to Kari Nordmann`."""
    teller = person_text(payload.get("teller"), names)
    listener = person_text(payload.get("listener"), names)
    return f"{BOOK} refers to {when_text(payload)} {EM_DASH} told by {teller} to {listener}"


def standing(lines: Iterable[Line], retracted: Mapping[str, Any] | None = None) -> list[Line]:
    """The story lines standing, in chain order: not retracted (the retractions among `lines`, or
    `retracted`, the ids a reading already knows) and not named by a later story's `supersedes`."""
    kept = sorted(lines, key=lambda line: int(line["seq"]))
    gone = set(retracted or ()) | set(retractions(line for line in kept if line.get("kind") == RETRACTION))
    stories = [line for line in kept if line.get("kind") == KIND]
    superseded = {
        str(p["supersedes"])
        for line in stories
        if isinstance(p := line.get("payload"), dict) and p.get("supersedes")
    }
    return [line for line in stories if str(line["id"]) not in gone and str(line["id"]) not in superseded]


def about(lines: Iterable[Line], day: str) -> list[Line]:
    """The standing stories whose `refers_to` covers the local day, the earliest-told first."""
    found = [line for line in lines if covers((line.get("payload") or {}).get("refers_to"), day)]
    return sorted(found, key=lambda line: (str(line["at"]), int(line["seq"])))


def summary(line: Line, names: Mapping[Ref, str]) -> dict[str, Any]:
    """One story as the Day's `stories` carries it: the line, when it was told, its title, first
    line of text, `refers_to`, the two people with the record's current label, confidence, source."""
    payload = line.get("payload") or {}
    return {
        "line": str(line["id"]),
        "told_at": str(line["at"]),
        "title": payload.get("title"),
        "text": first_line(str(payload.get("text") or "")),
        "refers_to": payload.get("refers_to"),
        "teller": _person_json(payload.get("teller"), names),
        "listener": _person_json(payload.get("listener"), names),
        "confidence": payload.get("confidence"),
        "source": payload.get("source"),
    }


def _person_json(person: object, names: Mapping[Ref, str]) -> dict[str, Any] | None:
    if not isinstance(person, Mapping):
        return None
    out: dict[str, Any] = {"ref": person.get("ref")}
    name = person_text(person, names)
    ref = person.get("ref")
    if name != (ref.get("value") if isinstance(ref, Mapping) else None):
        out["name"] = name
    return out


def first_line(text: str, chars: int = TEXT_CHARS) -> str:
    """The first non-blank line of a story, cut to `chars` with an ellipsis, as a note's is."""
    for line in text.splitlines():
        if line.strip():
            line = line.strip()
            return line if len(line) <= chars else line[: chars - 1] + "…"
    return ""


def rows(stories: Iterable[Mapping[str, Any]], tz: ZoneInfo) -> Iterator[str]:
    """The Day's `Stories about this day` section: the heading, then each story as `show` prints
    it with its confidence and told day, and its first line under it; nothing for no stories."""
    found = list(stories)
    if not found:
        return
    yield ""
    yield "  Stories about this day"
    for s in found:
        parts = [text(s, {})]
        if s.get("confidence"):
            parts.append(str(s["confidence"]))
        told = datetime.fromisoformat(str(s["told_at"]).replace("Z", "+00:00")).astimezone(tz)
        parts.append(f"told {told.date().isoformat()}")
        yield f"    {DOT.join(parts)}"
        if s.get("text"):
            yield f"       {s['text']}"
