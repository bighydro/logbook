"""The row `show` (and `search`) prints for one line: the clock, the kind, the source and the
profile's own summary of the payload. Nothing here is a command."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..contrib import trip_bundle
from ..core import apps, events, flights, keepers, signing, story
from ..core.chain import Line, is_sealed, number_text
from ..core.resolve import Ref
from .common import ARROW, EM_DASH, EN_DASH, _clock, _plural


def _day_rows(
    rows: list[Line],
    retracted: dict[str, Line],
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
    descriptions: Mapping[str, Line] | None = None,
) -> Iterator[str]:
    """One printed row per line, except that a run of location points from one source, unbroken
    by any other row, collapses into one summary, one calendar entry that several sources
    carry (`events.fold`) is one row, `×N sources`, and a photo's description (`descriptions`,
    photo line id → the derived note, `describe.by_photo`) prints under the first keeper row for
    that photo instead of as a row of its own; with no keeper row standing it is a row. `names` is
    the label map; None is the `--raw` path: refs exactly as the sources gave them, no label, no
    fallback."""
    from ..labs import describe

    run: list[Line] = []
    rows, folded = events.fold(rows, flights.Airlines.load(), retracted)
    described = descriptions or {}
    under: dict[str, str] = {}  # description line id → the keeper line id it prints under
    for line in rows:
        pid = (
            keepers.photo_id_of(line)
            if line["kind"] == keepers.KIND and line["id"] not in retracted
            else None
        )
        if pid is not None and pid in described and str(described[pid]["id"]) not in under:
            under[str(described[pid]["id"])] = str(line["id"])
    for line in rows:
        retraction = retracted.get(line["id"])
        point = line["kind"] == "location" and retraction is None
        if run and not (point and (line["source"], _subject(line)) == (run[0]["source"], _subject(run[0]))):
            yield _run_row(run, tz)
            run = []
        if point:
            run.append(line)
        elif str(line["id"]) in under:
            continue  # shown under its keeper
        else:
            stands_for = folded.get(str(line["id"]))
            sources = f"×{len(stands_for.sources)} sources" if stands_for else None
            yield _line_row(line, retraction, tz, names, superseded, sources)
            pid = keepers.photo_id_of(line) if line["kind"] == keepers.KIND else None
            if (
                pid is not None
                and pid in described
                and under.get(str(described[pid]["id"])) == str(line["id"])
            ):
                yield f"{' ' * DESCRIPTION_INDENT}{describe.under_keeper(described[pid])}"
    if run:
        yield _run_row(run, tz)


DESCRIPTION_INDENT = 2 + 5 + 2 + 10 + 1 + 14 + 1  # the text column of a row: margin, clock, kind, source


def _line_row(
    line: Line,
    retraction: Line | None,
    tz: ZoneInfo,
    names: Mapping[Ref, str] | None,
    superseded: Mapping[str, int] | None = None,
    sources: str | None = None,
) -> str:
    """`sources` stands in for the line's own source on a calendar entry several sources carry
    (`events.fold`): `×2 sources`."""
    clock = _clock(line["at"], tz)
    if retraction is not None:
        return f"  {clock}  retracted #{line['seq']}: {retraction['payload'].get('reason', '')}"
    by = (superseded or {}).get(str(line["id"]))
    if by is not None:
        return f"  {clock}  {line['kind']:<10} {line['source']:<14} superseded by #{by}"
    text = _line_text(line, tz, names)
    return f"  {clock}  {line['kind']:<10} {sources or line['source']:<14} {text}"


def _line_text(line: Line, tz: ZoneInfo, names: Mapping[Ref, str] | None) -> str:
    """The text part of a line's row: the profile's own summary where the kind has one, else the
    payload's text, title, name or url, else every field as `key=value`. A line still sealed at
    this point (no identity on this machine; RFC 0029) says so and nothing else."""
    from ..labs import describe

    p = line["payload"]
    if is_sealed(line):
        return f"[sealed {p.get('of')}; no identity to open it]"
    if line["kind"] == "flight":
        text = _flight_text(p, tz)
    elif line["kind"] == "message":
        text = _message_text(p, names)
    elif line["kind"] == "event":
        text = _event_text(p, names)
    elif line["kind"] == "transcript":
        text = _transcript_text(p, names)
    elif line["kind"] == "call":
        text = _call_text(p, names)
    elif line["kind"] == "mail":
        text = _mail_text(p, names)
    elif line["kind"] == "note" and describe.is_description(line):
        text = describe.row_text(line)  # a photo's description, when its keeper is not shown
    elif line["kind"] == "note":
        text = _note_text(p, raw=names is None)
    elif line["kind"] == keepers.KIND:
        text = keepers.text(line)
    elif line["kind"] == story.KIND and p.get("schema") == story.SCHEMA:
        text = story.text(p, names)
    elif line["kind"] == "highlight" and p.get("schema") == "highlight/v1":
        text = _highlight_text(p)
    elif line["kind"] == "voice-memo" and p.get("schema") == "voice-memo/v1":
        text = _voice_memo_text(p)
    elif line["kind"] in ("trip", "journey") and p.get("schema") in (
        "trip/v1",
        "journey/v1",
    ):  # RFC 0031: one profile, two spellings
        text = _trip_text(p)
    elif line["kind"] == "crossing" and p.get("schema") == "crossing/v1":
        text = _crossing_text(p)
    elif line["kind"] == signing.KIND and p.get("schema") == signing.SCHEMA:
        text = signing.row_text(p)
    elif line["kind"] == trip_bundle.RECEIVED:
        text = trip_bundle.text(line, lambda inner: _line_text(inner, tz, names))
    elif line["kind"] == apps.KIND and p.get("schema") == apps.SCHEMA:
        text = _app_use_text(p)
    else:
        text = (
            p.get("text")
            or p.get("title")
            or p.get("name")
            or p.get("url")
            or ", ".join(f"{k}={_value_text(v)}" for k, v in p.items() if k != "schema")
        )
    return str(text)


def _value_text(value: object) -> str:
    """A payload value in the generic row: a string as itself, anything else as `_value_repr`."""
    return value if isinstance(value, str) else _value_repr(value)


def _value_repr(value: object) -> str:
    """Python's repr of a JSON value, except that a number is spelled as RFC 8785 writes it
    (`chain.number_text`): `100000000000000000000`, not the stored `1e+20`; `0.000001`; `120`. The
    row then depends on the value alone, never on the text the writer chose, so another
    implementation can print the same row from the same record (SPEC §3.2)."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return number_text(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value_repr(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_value_repr(k)}: {_value_repr(v)}" for k, v in value.items()) + "}"
    return repr(value)


def _app_use_text(p: dict[str, Any]) -> str:
    """An app-use line as `Safari · 25 min · mac`: the app (its name, else its bundle id), the span's
    length, the device (its name, else its identifier). Never a title or a URL: the line has none."""
    extra: dict[str, Any] = p["extra"] if isinstance(p.get("extra"), dict) else {}
    app = p.get("title") or extra.get("bundle_id") or "an app"
    parts = [str(app)]
    seconds = extra.get("duration_s")
    if isinstance(seconds, int | float) and not isinstance(seconds, bool):
        parts.append(duration_text(int(seconds)))
    device = extra.get("device_name") or extra.get("device")
    if device:
        parts.append(str(device))
    return " · ".join(parts)


def duration_text(seconds: int) -> str:
    """`40 s`, `25 min`, `2 h 30 min`, `3 h`: whole units, the smaller one left out when zero."""
    if seconds < 60:
        return f"{seconds} s"
    hours, minutes = divmod(round(seconds / 60), 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def _crossing_text(p: dict[str, Any]) -> str:
    """A crossing/v1 line as `crossed to <destination>: N lines (tier 1: a, tier 2: b)`."""
    counts = p["counts"]
    by_tier = counts["by_tier"]
    tiers = ", ".join(f"tier {tier}: {by_tier[tier]}" for tier in ("1", "2", "3") if by_tier.get(tier))
    text = f"crossed to {p['destination']}: {_plural(counts['crossed'], 'line')}"
    if tiers:
        text += f" ({tiers})"
    return text


def _note_text(p: dict[str, Any], raw: bool) -> str:
    """A note's first line, with `… (+N lines)` when there are more (RFC 0010); `--raw` prints the
    whole text as written."""
    text = str(p.get("text") or "")
    if raw:
        return text
    lines = text.rstrip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ""
    rest = len(lines) - 1
    return lines[0] if rest == 0 else f"{lines[0]} … (+{_plural(rest, 'line')})"


def _name(ref: object, names: Mapping[Ref, str] | None) -> str | None:
    """The label of a source-native ref `{kind, value}` (RFC 0006), else None."""
    if names is None or not isinstance(ref, dict):
        return None
    kind, value = ref.get("kind"), ref.get("value")
    if not isinstance(kind, str) or not isinstance(value, str):
        return None
    return names.get((kind, value))


def _ref_value(ref: object) -> str:
    return str(ref.get("value", "")) if isinstance(ref, dict) else ""


def _highlight_text(p: dict[str, Any]) -> str:
    """`“quote” — Title · note` for a highlight, `bookmark — Title @ location` for a bookmark
    (RFC 0022); the title is the library's, else the asset id."""
    book = p.get("title") or p.get("asset_id") or ""
    if p.get("type") == "bookmark":
        where = p.get("location")
        return f"bookmark — {book}" + (f" @ {where}" if where else "")
    text = f"\u201c{p.get('quote', '')}\u201d" + (f" — {book}" if book else "")
    if p.get("note"):
        text += f" · {p['note']}"
    return text


def _trip_text(p: dict[str, Any]) -> str:
    """`From → To, transit, sbb, 58.00 CHF, 1 change` (RFC 0020); a parking session names one place."""
    origin = _place_name(p.get("from"))
    destination = _place_name(p.get("to"))
    route = f"{origin} → {destination}" if destination and destination != origin else origin
    parts = [part for part in (route, str(p.get("mode") or ""), str(p.get("provider") or "")) if part]
    price = p.get("price")
    if isinstance(price, dict) and price.get("amount"):
        parts.append(f"{price['amount']} {price.get('currency', '')}".strip())
    if p.get("status") == "cancelled":
        parts.append("cancelled")
    extra = p.get("extra")
    if isinstance(extra, dict):
        transfers = extra.get("transfers")
        if isinstance(transfers, int) and not isinstance(transfers, bool) and transfers > 0:
            parts.append(_plural(transfers, "change"))
        if extra.get("observed") == "ticket":
            parts.append("ticket")
    return ", ".join(parts)


def _place_name(place: object) -> str:
    if isinstance(place, dict):
        return str(place.get("name") or place.get("address") or place.get("code") or "")
    return str(place) if isinstance(place, str) else ""


def _voice_memo_text(p: dict[str, Any]) -> str:
    """`Title (m:ss)`, then `audio missing` when the line has no media, `not stored` when it has
    the digest and no file (RFC 0023)."""
    text = str(p.get("title") or p.get("file_name") or "recording")
    duration = p.get("duration_s")
    if isinstance(duration, int | float) and not isinstance(duration, bool) and duration >= 0:
        minutes, seconds = divmod(round(duration), 60)
        text += f" ({minutes}:{seconds:02d})"
    media = p.get("media")
    if not isinstance(media, dict):
        text += ", audio missing"
    elif "path" not in media:
        text += ", not stored"
    return text


def _flight_text(p: dict[str, Any], tz: ZoneInfo | None = None) -> str:
    """`XY 561 OSL → ZRH, arrives 09:24, Airbus A320 LN-XYA, tracked, as pilot` (RFC 0013): the
    arrival clock in the owner's zone when `tz` is given; `cancelled` when it did not fly."""
    origin, destination = _airport_code(p.get("from")), _airport_code(p.get("to"))
    diverted = _airport_code(p.get("diverted_to"))
    route = f"{origin} → {destination}" + (f" (landed {diverted})" if diverted else "")
    parts = [f"{p.get('carrier', '')} {p.get('number', '')} {route}".strip()]
    if p.get("cancelled"):
        parts.append("cancelled")
    arrival = p.get("actual_arrival") or p.get("scheduled_arrival")
    if tz is not None and isinstance(arrival, str) and arrival:
        parts.append(f"arrives {_clock(arrival, tz)}")
    aircraft = p.get("aircraft")
    if isinstance(aircraft, dict):
        plane = " ".join(str(v) for v in (aircraft.get("type"), aircraft.get("registration")) if v)
        if plane:
            parts.append(plane)
    parts.append(str(p.get("evidence", "")))
    if p.get("role") == "pilot":
        parts.append("as pilot")
    return ", ".join(part for part in parts if part)


def _airport_code(ref: object) -> str:
    return str(ref.get("iata") or ref.get("icao") or "") if isinstance(ref, dict) else ""


def _call_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`← who, 7 min, cellular` for an answered incoming call, `→ who` outgoing, `missed` or `no
    answer` when it did not connect (RFC 0012). The counterparty is its label, else the ref as given;
    a withheld number is `withheld`. Raw (`names` None): the ref."""
    ref = p.get("counterparty")
    who = _name(ref, names) or _ref_value(ref) or "withheld"
    arrow = "→" if p.get("direction") == "outgoing" else "←"
    parts = [f"{arrow} {who}"]
    if not p.get("answered"):
        parts.append("no answer" if p.get("direction") == "outgoing" else "missed")
    else:
        seconds = p.get("duration_s")
        if isinstance(seconds, int) and seconds > 0:
            parts.append(f"{seconds // 60} min" if seconds >= 60 else f"{seconds} s")
    if isinstance(p.get("service"), str):
        parts.append(p["service"])
    return ", ".join(parts)


MAIL = "\u2709"  # ✉


BODY_INDENT = "    "


def _mail_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`✉ subject — from → to (n attachments)` (RFC 0015). A person is the label a resolution
    gives their address, else the name the header gave, else the address; the owner's own mail says
    `me`. Raw (`names` None): the addresses as given, and the body indented under the row — the
    only time `show` prints a body."""
    subject = str(p.get("subject") or "(no subject)")
    sender = p.get("from")
    own = p.get("direction") == "sent" and names is not None
    who = "me" if own else _mail_person(sender, names) or "?"
    recipients = [*(p.get("to") or []), *(p.get("cc") or [])]
    to = ", ".join(name for r in recipients if (name := _mail_person(r, names)))
    head = f"{MAIL} {subject} {EM_DASH} {who}"
    if to:
        head += f" {ARROW} {to}"
    attachments = p.get("attachments")
    if isinstance(attachments, list) and attachments:
        head += f" ({_plural(len(attachments), 'attachment')})"
    if names is None and isinstance(p.get("body"), str) and p["body"].strip():
        head += "\n" + "\n".join(BODY_INDENT + row for row in p["body"].rstrip("\n").split("\n"))
    return head


def _mail_person(person: object, names: Mapping[Ref, str] | None) -> str:
    """A mail/v1 `{email, name?}`: its resolution label, else its header name, else the address;
    raw is always the address."""
    if not isinstance(person, dict):
        return ""
    address = str(person.get("email") or "")
    if names is None:
        return address
    label = names.get(("email", address)) if address else None
    own = person.get("name")
    return label or (own if isinstance(own, str) and own else "") or address


def _message_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`who: text`, `who in group: text`, `me → other: text` (RFC 0008). The sender is its label,
    else the name the source showed for it (`sender.name`), else the direct chat's own name, else
    the ref as given. A group is its name, else its id: a chat is not an entity (RFC 0006), so its
    id is never looked up. Raw (`names` None): the ref."""
    chat = p.get("chat")
    if isinstance(chat, str):
        # SPEC §3.2: a string `chat` (the conformance sample's shape, before RFC 0008) is a direct chat's name
        chat = {"type": "direct", "name": chat}
    elif not isinstance(chat, dict):
        chat = {}
    chat_id = str(chat.get("id") or "")
    direct = chat.get("type") == "direct"
    chat_name = str(chat.get("name") or "")
    if p.get("from_me"):
        who = "me"
    elif names is None:
        who = _ref_value(p.get("sender"))
    else:
        sender = p.get("sender")
        own = sender.get("name") if isinstance(sender, dict) else None
        who = (
            _name(sender, names)
            or (own if isinstance(own, str) else "")
            or (chat_name if direct else "")
            or _ref_value(sender)
        )
    if direct:
        prefix = f"{who} → {chat_name or chat_id}" if who == "me" else who
    else:
        prefix = f"{who} in {chat_name or chat_id}"
    body = p.get("text") or f"[{p.get('media_kind') or 'media'}]"
    return f"{prefix}: {body}"


def _event_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`title · by organizer · with attendees` (RFC 0009). An attendee is its label, else the
    name the calendar gave it, else the ref; raw (`names` None) is always the ref."""
    parts = [str(p.get("title") or "")]
    organizer = p.get("organizer")
    if organizer:
        parts.append(f"by {_name(organizer, names) or _ref_value(organizer)}")
    attendees = p.get("attendees") or []
    if attendees:
        parts.append("with " + ", ".join(_attendee(a, names) for a in attendees))
    return " · ".join(part for part in parts if part)


def _transcript_text(p: dict[str, Any], names: Mapping[Ref, str] | None) -> str:
    """`<title> — <participants>; <turns>, <length>` (RFC 0004). A participant is named by a
    resolution of its email when one exists, else as the source names it; `--raw` uses the source's
    name. Never the text: that is an attachment."""
    who = [
        _name({"kind": "email", "value": q.get("email")}, names) or str(q.get("name") or q.get("email") or "")
        for q in p.get("participants") or []
        if isinstance(q, dict)
    ]
    head = str(p.get("title") or "transcript")
    if any(who):
        head += " — " + ", ".join(w for w in who if w)
    extra: dict[str, Any] = p["extra"] if isinstance(p.get("extra"), dict) else {}
    parts: list[str] = []
    turns = extra.get("turns")
    if isinstance(turns, int):
        parts.append(_plural(turns, "turn"))
    duration = extra.get("duration_s")
    if isinstance(duration, int | float) and duration >= 0:
        parts.append(f"{duration / 60:.0f} min" if duration >= 60 else f"{duration:.0f} s")
    return head + ("; " + ", ".join(parts) if parts else "")


def _attendee(attendee: object, names: Mapping[Ref, str] | None) -> str:
    """An attendee's name, else its ref. A string attendee is the shape before RFC 0009 (SPEC §3.2
    reads it as an `email` ref); anything else is printed as it is, never a failure (SPEC §5)."""
    if isinstance(attendee, str):
        return _name({"kind": "email", "value": attendee}, names) or attendee
    if not isinstance(attendee, dict):
        return str(attendee)
    ref = attendee.get("ref")
    label = _name(ref, names)
    if label:
        return label
    own = attendee.get("name")
    if names is not None and isinstance(own, str) and own:
        return own
    return _ref_value(ref) or str(own or "")


def _run_row(run: list[Line], tz: ZoneInfo) -> str:
    """Time span, count, and the first and last named place of a run of location points. The span
    ends at the last point's `end` when it has one, else at its `at` (SPEC §3.2); one point is a row
    of its own and prints its `at`, as every other row does."""
    until = run[-1].get("end") if len(run) > 1 else None
    first = _clock(run[0]["at"], tz)
    last = _clock(until, tz) if isinstance(until, str) else _clock(run[-1]["at"], tz)
    span = first if first == last else f"{first}{EN_DASH}{last}"
    n = len(run)
    text = f"{n:,} point{'s' if n != 1 else ''}"
    places = [place for place in map(_place, run) if place]
    if places:
        text += f" · {places[0]}" if places[0] == places[-1] else f" · {places[0]} → {places[-1]}"
    subject = _subject(run[0])
    if subject is not None:  # an asset's own track (RFC 0001 `subject`, ADR 0018), never the owner's
        text = f"{subject}: {text}"
    return f"  {span}  {'location':<10} {run[0]['source']:<14} {text}"


def _subject(line: Line) -> str | None:
    """The asset whose position a location line is, or None for the owner's own."""
    subject = (line.get("payload") or {}).get("subject")
    return str(subject) if subject else None


def _place(line: Line) -> str | None:
    """extra.place.district, else extra.place.city, else None (RFC 0001: `extra` is the source's)."""
    place = ((line.get("payload") or {}).get("extra") or {}).get("place") or {}
    value = place.get("district") or place.get("city")
    return str(value) if value else None
