"""The Day page's photos: where a photo's pixels are on this machine, and the photo review's passes.

A photo line points at pixels it does not hold (RFC 0002). Its thumbnail is shown only when the
record's own attachment store (SPEC §1.1) holds them: a reference under one of `REFERENCES` whose
`path` is `attachments/<sha256>`, a media type every browser draws (`SHOWN`), and a file that is there
and begins as that type says (`MAGIC`), sealed or not: a sealed file (RFC 0029 §7) is opened with
this machine's identity first, and is no thumbnail when it holds none or one that does not open it.
Anything else — a HEIC, a library's own path, an asset only Immich holds, a file missing — is no
thumbnail, and the page counts it instead of drawing a broken image. Nothing here
opens a socket or asks a library: the Immich adapter keeps the asset's id and the original's path,
never a URL, and the page never fetches one.

The photo review at the foot of a Day lists the day's photos with no star standing. *Star* is
`stars.star` (a `memory` keeper, RFC 0024); *Not a keeper* is no line: RFC 0024 rule 3 has a producer
never write "not a keeper" and RFC 0041 rule 4 has a star never say "not starred", so the owner's no
is the review's own bookkeeping, `state/photo-review.json` (`STATE_FILE`), as the places review kept
its rejections before 0.7: the photo ids passed over, so the review does not ask again. It is written
under the record's writer lock, never read by any reader but the review, and losing it only asks
again. Starring a photo passed over still stars it."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

from ..core import attachments, sealing
from ..core.chain import AGE_MAGIC, Line
from ..core.store import Logbook

REFERENCES = ("media", "attachments", "attachment", "file", "content")  # where a §1.1 reference may sit
SHOWN = ("image/jpeg", "image/png", "image/gif", "image/webp")  # what every browser draws
MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
STATE_FILE = PurePosixPath("state/photo-review.json")  # record-relative: the photos passed over
KIND = "photo"


class Stored(NamedTuple):
    """A photo's pixels in the attachment store: the file's name (its digest) and its media type."""

    sha256: str
    media_type: str


def stored(lb: Logbook, line: Line) -> Stored | None:
    """The pixels of a photo line in the record's own store, when a browser can draw them; else None.
    A plain file is judged by its first bytes; a sealed one is opened to judge it (`opened` serves it)."""
    for found in _references(line):
        head = _head(lb, found)
        if head is not None and _draws(head, found.media_type):
            return found
    return None


def opened(lb: Logbook, line: Line) -> tuple[Stored, bytes] | None:
    """`stored`, with the pixels read once: what `/photo/ID` sends; None when nothing here draws."""
    for found in _references(line):
        data = pixels(lb, found)
        if data is not None and _draws(data[:12], found.media_type):
            return found, data
    return None


def _references(line: Line) -> Iterator[Stored]:
    """The §1.1 references of a photo line to the store, in a type every browser draws."""
    if line.get("kind") != KIND:
        return
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    for holder in (payload, extra if isinstance(extra, dict) else {}):
        for key in REFERENCES:
            value = holder.get(key)
            for ref in value if isinstance(value, list) else [value]:
                if not isinstance(ref, dict):
                    continue
                sha, path, media = ref.get("sha256"), ref.get("path"), ref.get("media_type")
                if not isinstance(sha, str) or not attachments.is_digest(sha) or media not in SHOWN:
                    continue
                if isinstance(path, str) and PurePosixPath(path).parts == (attachments.DIR, sha):
                    yield Stored(sha, str(media))


def _head(lb: Logbook, found: Stored) -> bytes | None:
    """The first bytes of a stored photo's plaintext: a plain file's read as they are, a sealed one's
    opened with this machine's identity; None when it is not there or does not open here."""
    try:
        with (lb.root / attachments.DIR / found.sha256).open("rb") as fh:
            head = fh.read(len(AGE_MAGIC))  # long enough for the age marker and every type's magic
    except OSError:
        return None
    if not head.startswith(AGE_MAGIC):
        return head
    if not lb.identities:
        return None
    plain = pixels(lb, found)
    return plain[:12] if plain is not None else None


def _draws(head: bytes, media_type: str) -> bool:
    """Whether bytes beginning `head` are what `media_type` says, so a browser draws them."""
    if not any(head.startswith(magic) for magic in MAGIC[media_type]):
        return False
    return media_type != "image/webp" or head[8:12] == b"WEBP"


def pixels(lb: Logbook, found: Stored) -> bytes | None:
    """The plaintext of a stored photo, or None when the file is gone or cannot be opened here."""
    try:
        return attachments.read_bytes(lb.root, found.sha256, lb.identities)
    except (OSError, sealing.SealError):
        return None


def state_path(root: Path) -> Path:
    return Path(root).joinpath(*STATE_FILE.parts)


def passed(root: Path) -> frozenset[str]:
    """The photo line ids the owner passed over in the review (`Not a keeper`); none when the file is
    missing or not what it should be (the review then asks again: nothing is lost but a click)."""
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    found = data.get("passed") if isinstance(data, dict) else None
    return frozenset(i for i in found if isinstance(i, str)) if isinstance(found, list) else frozenset()


def pass_over(lb: Logbook, photo: str, at: str) -> bool:
    """Pass over the photo line `photo` (`Not a keeper`), at `at`: its id kept in `STATE_FILE`,
    under the record's writer lock, written to a temporary name and renamed into place. False when
    it was passed over already, and nothing written."""
    with lb.writer():
        path = state_path(lb.root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        rows = data.get("passed") if isinstance(data, dict) else None
        ids = [i for i in rows if isinstance(i, str)] if isinstance(rows, list) else []
        if photo in ids:
            return False
        state: dict[str, Any] = {"passed": [*ids, photo], "updated_at": at}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes((json.dumps(state, indent=2) + "\n").encode("utf-8"))
        os.replace(temporary, path)
    return True


def starred_first(ids: Iterable[str], starred: Mapping[str, object]) -> list[str]:
    """`ids` with the starred ones first (RFC 0041), each side in the order given."""
    ordered = list(ids)
    return [i for i in ordered if i in starred] + [i for i in ordered if i not in starred]
