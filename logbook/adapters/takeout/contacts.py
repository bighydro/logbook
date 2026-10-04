"""Google Takeout Contacts/ → resolution/v1 (RFC 0006).

Takeout writes `Takeout/Contacts/All Contacts/All Contacts.vcf`, every contact as one vCard 3.0, and
one more folder per label (`My Contacts/`, `Sailing/`) whose `.vcf` repeats the contacts under it.
A card has `FN` and `N` (the name), `ORG`, `NICKNAME`, `EMAIL;TYPE=…` and `TEL;TYPE=…` lines, a
grouped property's label on an `item1.X-ABLabel` line, `CATEGORIES` (the labels), `REV`, and a
base64 `PHOTO` folded over many lines, which is not read. A folder that holds `All Contacts/` is
read from that file alone, so a label repeats nothing; any other folder is read whole.

This is how a record gets its people from Google rather than from the phone (ADR 0013.2), and the
rule is the one `ios-contacts` follows: each card mints one Logbook UUIDv7 — a `person`, or a
`company` when only `ORG` is set — and every email address and phone number becomes one resolution
line pointing at it, `raw_id` the normalised ref (`email:<address>`, `phone:<number>`), so the same
export again appends nothing. Emails are lower-cased; phones go through the shared `phone.normalise`
with `LOGBOOK_DIAL_PREFIX`, as every adapter that writes a phone ref does, so the address book, the
chats and the calls meet on one resolution.

**Merging.** `logbook add` hands `run` the refs the record already resolves (`resolved`, from the
resolution lines standing, through their aliases). A card whose email or phone the record already
knows takes that entity's id — nothing is minted for a person `ios-contacts` resolved — and only its
refs the record does not yet hold become lines; a ref already resolved is skipped and counted
(`skipped_already_resolved`), whoever resolved it standing. A card with no email and no phone is
skipped and counted; a ref an earlier card in the same file already carried is skipped and counted.
Pure: no network, never writes the source. `at` is the import time: a resolution is made when it is
read, not when the contact was saved; the card's `REV` lives under `extra`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...core.store import uuid7
from .. import phone
from ..ios_contacts import DIAL_PREFIX_ENV
from . import SOURCE

NAME = "google-takeout-contacts"
KIND = "resolution"
TIER = 2
SCHEMA = "resolution/v1"
METHOD = "owner"
FOLDER = "Contacts"
ALL_CONTACTS = "All Contacts"

SUFFIX = ".vcf"
SNIFF_BYTES = 4096
BEGIN = "BEGIN:VCARD"
END = "END:VCARD"
PROPERTIES = {"EMAIL": "email", "TEL": "phone"}
ALREADY = "skipped_already_resolved"
MERGED = "merged_into_known_people"
TYPE_LABEL_SKIP = frozenset({"internet", "pref", "voice", "x-mobile"})  # vCard noise, not a label

Ref = tuple[str, str]


def sniff(path: Path) -> bool:
    """A `.vcf` of vCards, or a folder holding one directly or one folder down — Takeout's
    `Contacts/`. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return bool(_files(path))
        return _is_vcf(path)
    except OSError:
        return False


def _is_vcf(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return BEGIN.encode() in head


def _files(folder: Path) -> list[Path]:
    """The `.vcf` files to read for `folder`: `All Contacts/` alone when it has one (every contact
    is there and the label folders repeat them), else every `.vcf` in it and one level down."""
    everything = folder / ALL_CONTACTS
    if everything.is_dir():
        found = sorted(f for f in everything.iterdir() if _is_vcf(f))
        if found:
            return found
    found = [f for f in sorted(folder.iterdir()) if _is_vcf(f)]
    for sub in sorted(f for f in folder.iterdir() if f.is_dir()):
        found.extend(f for f in sorted(sub.iterdir()) if _is_vcf(f))
    return found


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    resolved: Mapping[Ref, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """One resolution/v1 line per email and phone of every card in `path` (a `.vcf`, or the folder),
    cards in file order. `since` is accepted for the adapter contract and ignored: every line's
    `at` is now, and the log dedupes on `raw_id`. `resolved` is `{(kind, value): entity id}` for
    the refs the record already resolves; a card that carries one reuses that id and writes no line
    for it."""
    counts = counts if counts is not None else {}
    resolved = resolved or {}
    path = Path(path)
    files = [path] if path.is_file() else _files(path)
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    seen: set[str] = set()
    for file in files:
        for card in _cards(file):
            yield from _lines(card, at, prefix, resolved, seen, counts)


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _lines(
    card: list[tuple[str, str, dict[str, str], str]],
    at: str,
    prefix: str,
    resolved: Mapping[Ref, str],
    seen: set[str],
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    refs: list[tuple[str, str, bool, str]] = []  # kind, value, unnormalised, label
    for group, name, params, value in card:
        kind = PROPERTIES.get(name)
        if kind is None or not value.strip():
            continue
        normalised, unnormalised = _normalise(kind, value, prefix)
        if normalised:
            refs.append((kind, normalised, unnormalised, _label(card, group, params)))
    if not refs:
        _count(counts, "skipped_no_ref")
        return
    entity_id = next((resolved[(k, v)] for k, v, _, _ in refs if (k, v) in resolved), None)
    known = entity_id is not None
    entity_type, label = _identity(card)
    extra_common = _extra(card)
    emitted = 0
    for kind, value, unnormalised, ref_label in refs:
        raw_id = f"{kind}:{value}"
        if (kind, value) in resolved:
            _count(counts, ALREADY)
            continue
        if raw_id in seen:
            _count(counts, "skipped_duplicate_ref")
            continue
        seen.add(raw_id)
        if entity_id is None:
            entity_id = uuid7()  # minted once per card, on the first ref that needs it
        emitted += 1
        extra: dict[str, Any] = {}
        if ref_label:
            extra["label"] = ref_label
        extra.update(extra_common)
        if unnormalised:
            extra["unnormalised"] = True
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ref": {"kind": kind, "value": value},
            "entity": {"type": entity_type, "id": entity_id, "registry": "logbook"},
        }
        if label:
            payload["label"] = label
        payload["method"] = METHOD
        payload["raw_id"] = raw_id
        if extra:
            payload["extra"] = extra
        yield {
            "at": at,
            "end": None,
            "tz": None,  # the logbook's own
            "source": SOURCE,
            "kind": KIND,
            "tier": TIER,
            "payload": payload,
        }
    if known and emitted:
        _count(counts, MERGED)


def _cards(file: Path) -> Iterator[list[tuple[str, str, dict[str, str], str]]]:
    """Every vCard in `file` as its content lines, each `(group, NAME, {param: value}, value)`,
    folded continuation lines joined, the `PHOTO` left out."""
    text = file.read_text(encoding="utf-8", errors="replace")
    unfolded = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    card: list[tuple[str, str, dict[str, str], str]] | None = None
    for raw in unfolded:
        line = raw.rstrip("\r")
        if line.upper() == BEGIN:
            card = []
            continue
        if line.upper() == END:
            if card is not None:
                yield card
            card = None
            continue
        if card is None or ":" not in line:
            continue
        head, _, value = line.partition(":")
        parts = head.split(";")
        group, _, name = parts[0].rpartition(".")
        name = name.upper()
        if name == "PHOTO":
            continue
        params: dict[str, str] = {}
        for param in parts[1:]:
            key, _, val = param.partition("=")
            key = key.upper()
            params[key] = f"{params[key]},{val}" if key in params else val
        card.append((group, name, params, value))


def _first(card: list[tuple[str, str, dict[str, str], str]], name: str) -> str:
    return next((value.strip() for _, n, _, value in card if n == name and value.strip()), "")


def _identity(card: list[tuple[str, str, dict[str, str], str]]) -> tuple[str, str]:
    """(entity type, display name): `FN`, else `N` joined, else `ORG` (a company), else `NICKNAME`.
    A card whose `FN` is its `ORG` and whose `N` is empty is a company too."""
    org = _unescape(_first(card, "ORG").split(";")[0])
    n_parts = [_unescape(part).strip() for part in _first(card, "N").split(";")]
    given = " ".join(part for part in (n_parts[1:2] + n_parts[:1]) if part) if any(n_parts) else ""
    fn = _unescape(_first(card, "FN"))
    if not given and org and (not fn or fn == org):
        return "company", org
    name = fn or given or _unescape(_first(card, "NICKNAME"))
    return "person", " ".join(name.split())


def _extra(card: list[tuple[str, str, dict[str, str], str]]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    entity_type, label = _identity(card)
    org = _unescape(_first(card, "ORG").split(";")[0])
    if entity_type == "person" and org:
        extra["organization"] = org
    nickname = _unescape(_first(card, "NICKNAME"))
    if nickname and nickname != label:
        extra["nickname"] = nickname
    categories = [c.strip() for c in _first(card, "CATEGORIES").split(",") if c.strip()]
    if categories:
        extra["categories"] = categories
    rev = _first(card, "REV")
    if rev:
        extra["rev"] = rev
    return extra


def _label(card: list[tuple[str, str, dict[str, str], str]], group: str, params: dict[str, str]) -> str:
    """The ref's label: the group's `X-ABLabel` (`item1.X-ABLabel:Boat`), else the first `TYPE`
    that names a kind of address (`home`, `work`, `cell`), lower-cased."""
    if group:
        custom = next((value for g, n, _, value in card if g == group and n == "X-ABLABEL"), "")
        if custom.strip():
            return _unescape(custom.strip())
    types = [t.strip().lower() for t in params.get("TYPE", "").split(",") if t.strip()]
    return next((t for t in types if t not in TYPE_LABEL_SKIP), "")


def _normalise(kind: str, entered: str, prefix: str) -> tuple[str, bool]:
    """(ref value, unnormalised): emails lower-cased and trimmed, phones through `phone.normalise`."""
    if kind == "email":
        return entered.strip().lower(), False
    return phone.normalise(entered.strip(), prefix)


def _unescape(value: str) -> str:
    return value.replace("\\,", ",").replace("\\;", ";").replace("\\n", "\n").replace("\\\\", "\\")
