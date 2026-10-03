"""`logbook describe keepers`: a local vision model looks at each keeper's photo and writes down what
is in it — one factual sentence and a short list of the visible things — as a derived note.

For every `keeper/v1` line standing (RFC 0024) whose photo file is reachable, one `note/v1` line
(RFC 0010) with `source` `description`, tier 2, `at` the photo's capture time, so it sits on the
photo's day beside the keeper:

- `raw_id` is the photo line's `id`, so a photo is described once however many lanes it is in and
  however often the command runs (the `(source, raw_id)` dedupe of `append_many`, checked here first
  so no image is looked at twice);
- `text` is the sentence, then `Visible: a, b, c` on a second line, so `search` finds the things;
- `extra` is `{derived: true, engine, model, photo: {line, asset_id, library, file_name?}, keeper,
  things}` — the line is a model's reading, never the owner's words, and it says so.

**The model never names a person and never guesses a place.** The prompt forbids both; faces are the
photo library's job (`extra.faces`, read by `keepers --people`), and an answer that carries any name
the library gave a face on that photo is refused and counted, never written. Nothing but the pixels
and the fixed prompt reaches the model: no file name, no date, no location, no face.

**Where the file is.** A photo line points at pixels it does not hold (RFC 0002). The file is reachable
when the line carries a §1.1 reference (`media`, `attachments`, `file`) to a file in the record's own
store, or when a folder given with `--photos` holds it: an Apple Photos library (`.photoslibrary`) by
the asset's UUID under `originals/<first character>/`, any other folder by the original file name,
case aside, walked once per run. A keeper whose file is nowhere is a counted skip.

**Nothing leaves the machine.** The engine is `mlx-vlm` on Apple silicon, an optional extra
(`openlogbook[describe]`) imported only when the command runs, with a small 4-bit vision model
(`DEFAULT_MODEL`; `--model` names another), sampled at temperature 0. While it runs the Hugging Face
hub is told it is offline (`transcribe.offline`), so no socket is opened for any reason; a model not
on the machine stops the command with the one flag that fetches it, `--fetch-model`, as `transcribe`
and `promises --judge` have it. No model runs unless asked: a dry run lists and needs no engine."""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from platform import machine
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from . import attachments, keepers, transcribe
from .chain import Line
from .store import Logbook

SOURCE = "description"  # the `source` of every line this command writes, whatever the engine
KIND = "note"
SCHEMA = "note/v1"
TIER = 2  # RFC 0010: a note is tier 2, MUST
EXTRA = "openlogbook[describe]"
DEFAULT_MODEL = "mlx-community/Qwen2-VL-2B-Instruct-4bit"
MAX_TOKENS = 200
MAX_THINGS = 12  # the list is short on purpose
THING_WORDS = 4  # a thing is a noun phrase, not a sentence
ORIGINALS = "originals"  # a Photos library keeps the originals here, by the UUID's first character
LIBRARY_SUFFIX = ".photoslibrary"
REFERENCES = ("media", "attachments", "file", "content")  # the payload fields a §1.1 reference may sit in
VISIBLE = "Visible: "

NO_FILE = "skipped_no_file"
NO_PHOTO = "skipped_no_photo"
PHRASES = {
    NO_FILE: "without its photo file (the attachment store, or a folder given with --photos)",
    NO_PHOTO: "whose photo line is not in the record",
}

PROMPT = (
    "Describe this photograph for a private diary. Answer with one JSON object and nothing else: "
    '{"description": one factual sentence saying what is in the picture, "things": a list of the '
    "visible things, each a short lowercase noun phrase}. Never name or identify a person: write "
    '"a person", "two people", "a child". Never guess or name where the picture was taken: no '
    "place, city, country, landmark, shop or brand. Describe only what is visible; do not interpret."
)


class EngineMissing(Exception):
    """No vision engine is installed."""


class ModelMissing(Exception):
    """The model is not on this machine and the run was not told to fetch it."""


class Engine(Protocol):
    """A local vision model: `describe` is its text for one image and one prompt, sampled at
    temperature 0."""

    name: str
    model: str

    def ready(self) -> bool: ...
    def fetch(self) -> None: ...
    def describe(self, image: Path, prompt: str) -> str: ...


@dataclass(frozen=True)
class Photo:
    """A standing keeper whose photo file is reachable: what one run has to do."""

    keeper: Line
    photo: Line
    file: Path

    @property
    def id(self) -> str:
        return str(self.photo["id"])

    @property
    def name(self) -> str:
        return keepers.name_of(self.keeper)

    @property
    def at(self) -> str:
        return str(self.photo["at"])


@dataclass(frozen=True)
class Description:
    """What the model saw: one sentence and the visible things, cleaned."""

    text: str
    things: list[str]


@dataclass(frozen=True)
class Done:
    photo: Photo
    found: Description


@dataclass
class Report:
    """What one run did."""

    found: int  # keepers with a reachable, undescribed photo when the run began
    already: int  # photos a description already stands for
    counts: dict[str, int]  # what was skipped and why
    photos: list[Photo]  # the ones found, in time order
    dry_run: bool
    engine: str | None
    model: str | None
    since: str | None = None
    written: int = 0
    unparsed: int = (
        0  # answers with no description in them, or one naming a face; not written, tried again next run
    )
    done: list[Done] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "since": self.since,
            "dry_run": self.dry_run,
            "engine": self.engine,
            "model": self.model,
            "found": self.found,
            "already": self.already,
            "written": self.written,
            "unparsed": self.unparsed,
            "skipped": dict(self.counts),
            "described": [
                {
                    "photo": d.photo.id,
                    "keeper": str(d.photo.keeper["id"]),
                    "file_name": d.photo.name,
                    "text": d.found.text,
                    "things": list(d.found.things),
                }
                for d in self.done
            ],
        }


# -- where the file is -----------------------------------------------------------------------------


class Roots:
    """The folders `--photos` names. A Photos library is looked up by the asset UUID, which is the
    name of its original (`originals/<first character>/<UUID>.<ext>`), so nothing is walked; any
    other folder is walked once, on first need, into a map of original file names, case aside, the
    first found standing for a name that occurs twice."""

    def __init__(self, folders: Iterable[Path]) -> None:
        self.folders = [Path(f) for f in folders]
        self._by_name: dict[str, Path] | None = None

    def find(self, payload: Mapping[str, Any]) -> Path | None:
        asset = payload.get("asset_id")
        if isinstance(asset, str) and asset:
            for folder in self.folders:
                found = _original(folder, asset)
                if found is not None:
                    return found
        file_name = payload.get("file_name")
        if isinstance(file_name, str) and file_name:
            if self._by_name is None:
                self._by_name = self._walk()
            return self._by_name.get(file_name.casefold())
        return None

    def _walk(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for folder in self.folders:
            if folder.suffix.casefold() == LIBRARY_SUFFIX:
                folder = folder / ORIGINALS  # the rest of a library is derivatives and databases
            if not folder.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(folder):
                dirnames.sort()
                for name in sorted(filenames):
                    found.setdefault(name.casefold(), Path(dirpath) / name)
        return found


def _original(folder: Path, asset: str) -> Path | None:
    """`<folder>/originals/<first character of the UUID>/<UUID>.<any extension>`, or None."""
    sub = folder / ORIGINALS / asset[0].upper()
    if not sub.is_dir():
        return None
    wanted = asset.casefold()
    for candidate in sorted(sub.iterdir()):
        if candidate.is_file() and candidate.stem.casefold() == wanted:
            return candidate
    return None


def stored(lb: Logbook, payload: Mapping[str, Any]) -> Path | None:
    """The photo's bytes in the §1.1 store, or None: a reference with a `path` of two parts,
    `attachments/<sha256>`, whose file is there, under `media`, `attachments`, `file` or `content`."""
    for key in REFERENCES:
        value = payload.get(key)
        for ref in value if isinstance(value, list) else [value]:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            parts = Path(ref["path"]).parts
            if len(parts) != 2 or parts[0] != attachments.DIR:
                continue
            file = lb.root / parts[0] / parts[1]
            if file.is_file():
                return file
    return None


def locate(lb: Logbook, photo: Line, roots: Roots) -> Path | None:
    """The photo's file: in the record's own store first, else under the folders given."""
    payload = photo.get("payload") or {}
    return stored(lb, payload) or roots.find(payload)


# -- what is pending -------------------------------------------------------------------------------


def pending(lb: Logbook, since: str | None, roots: Roots, counts: dict[str, int]) -> tuple[list[Photo], int]:
    """The photos to describe, in time order, each once whatever its lanes, and how many a
    description already stands for. A keeper standing from local day `since` on whose photo line is
    not in the record, or whose file is nowhere, is counted."""
    with lb.index() as idx:
        kept = keepers.standing([*idx.by_kind(keepers.KIND, first_day=since), *idx.retractions()])
        kept.sort(key=lambda line: (str(line["at"]), int(line["seq"])))
        ids = [pid for pid in (photo_id_of(k) for k in kept) if pid is not None]
        photos = idx.by_ids(ids)
        done = idx.existing({(SOURCE, pid) for pid in ids}) if ids else set()
    found: list[Photo] = []
    seen: set[str] = set()
    already = 0
    for keeper in kept:
        pid = photo_id_of(keeper)
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        photo = photos.get(pid)
        if photo is None:
            _count(counts, NO_PHOTO)
        elif (SOURCE, pid) in done:
            already += 1
        else:
            file = locate(lb, photo, roots)
            if file is None:
                _count(counts, NO_FILE)
            else:
                found.append(Photo(keeper, photo, file))
    return found, already


photo_id_of = keepers.photo_id_of


def faces_of(photo: Line) -> list[str]:
    """The names the library gave the faces on a photo line (`extra.faces`): what an answer must
    never carry."""
    extra = (photo.get("payload") or {}).get("extra")
    faces = extra.get("faces") if isinstance(extra, dict) else None
    return (
        [" ".join(f.split()) for f in faces if isinstance(f, str) and f.strip()]
        if isinstance(faces, list)
        else []
    )


# -- the answer ------------------------------------------------------------------------------------


def parse(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model's answer, fences and prose aside, or None."""
    decoder = json.JSONDecoder()
    for start in (m.start() for m in re.finditer(r"\{", text)):
        try:
            data, _end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def description_of(text: str, faces: Sequence[str]) -> Description | None:
    """The description in an answer, or None: `description` a non-empty string (whitespace
    collapsed), `things` a list of strings (or one comma-separated string), each cleaned to a short
    lowercase phrase, duplicates and anything over `THING_WORDS` words dropped, at most
    `MAX_THINGS`. An answer that names a face the library knows on this photo — any word of the
    name, in the sentence or among the things — is None: the model was told not to, and the
    record does not keep what it was told not to say."""
    data = parse(text)
    if data is None:
        return None
    sentence = data.get("description")
    if not isinstance(sentence, str):
        return None
    sentence = " ".join(sentence.split())
    if not sentence:
        return None
    raw = data.get("things")
    if isinstance(raw, str):
        raw = raw.split(",")
    things: list[str] = []
    for thing in raw if isinstance(raw, list) else []:
        if not isinstance(thing, str):
            continue
        cleaned = " ".join(thing.split()).casefold().strip(" .;:")
        if not cleaned or len(cleaned.split()) > THING_WORDS or cleaned in things:
            continue
        things.append(cleaned)
        if len(things) == MAX_THINGS:
            break
    if names_a_face(f"{sentence} {' '.join(things)}", faces):
        return None
    return Description(sentence, things)


def names_a_face(text: str, faces: Sequence[str]) -> bool:
    """Whether any word of any face's name (two characters or more) is a whole word of `text`,
    case aside."""
    words = {w.casefold() for face in faces for w in face.split() if len(w) >= 2}
    if not words:
        return False
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text.casefold()) for word in words)


# -- the lines -------------------------------------------------------------------------------------


def draft(photo: Photo, found: Description, engine: Engine) -> dict[str, Any]:
    """One note/v1 draft: the photo's `at` and `tz`, the sentence and the things as text, and under
    `extra` what made it and what it is about."""
    line = photo.photo
    payload = line.get("payload") or {}
    library = str(payload.get("library") or line.get("source") or "")
    ref: dict[str, Any] = {"line": photo.id, "asset_id": payload.get("asset_id"), "library": library}
    if payload.get("file_name"):
        ref["file_name"] = payload["file_name"]
    text = found.text + (f"\n{VISIBLE}{', '.join(found.things)}" if found.things else "")
    return {
        "at": photo.at,
        "end": None,
        "tz": line.get("tz"),
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": {
            "schema": SCHEMA,
            "raw_id": photo.id,
            "text": text,
            "extra": {
                "derived": True,
                "engine": engine.name,
                "model": engine.model,
                "photo": ref,
                "keeper": str(photo.keeper["id"]),
                "things": list(found.things),
            },
        },
    }


def is_description(line: Mapping[str, Any]) -> bool:
    """A note/v1 line this command wrote: `source` `description`, `extra.derived` true, a photo id."""
    if line.get("kind") != KIND or line.get("source") != SOURCE:
        return False
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    return (
        isinstance(extra, dict)
        and extra.get("derived") is True
        and isinstance(extra.get("photo"), dict)
        and isinstance(extra["photo"].get("line"), str)
    )


def by_photo(lines: Iterable[Line]) -> dict[str, Line]:
    """photo line id → its description line, the latest by `seq` when there are two (a photo
    described once has one)."""
    found: dict[str, Line] = {}
    for line in sorted((line for line in lines if is_description(line)), key=lambda line: int(line["seq"])):
        found[str(line["payload"]["extra"]["photo"]["line"])] = line
    return found


def sentence_of(line: Line) -> tuple[str, list[str]]:
    """(the sentence, the things) of a description line, from `extra.things` and the text."""
    payload = line.get("payload") or {}
    text = str(payload.get("text") or "")
    first = next((s for s in text.splitlines() if s.strip()), "").strip()
    extra = payload.get("extra")
    listed = extra.get("things") if isinstance(extra, dict) else None
    things = [str(t) for t in listed if isinstance(t, str)] if isinstance(listed, list) else []
    return first, things


def under_keeper(line: Line) -> str:
    """The description as `show` prints it under its keeper: the sentence, then the things."""
    sentence, things = sentence_of(line)
    return f"{sentence} · {', '.join(things)}" if things else sentence


def row_text(line: Line) -> str:
    """The description as its own row, when its keeper is not shown: `IMG_0001.HEIC: <sentence> · …`."""
    extra = (line.get("payload") or {}).get("extra") or {}
    ref = extra.get("photo") if isinstance(extra, dict) else None
    name = (
        str(ref.get("file_name") or ref.get("asset_id") or ref.get("line")) if isinstance(ref, dict) else "?"
    )
    return f"{name}: {under_keeper(line)}"


# -- the run ---------------------------------------------------------------------------------------


def run(
    lb: Logbook,
    engine: Engine | None,
    *,
    since: str | None = None,
    limit: int | None = None,
    fetch_model: bool = False,
    roots: Roots | None = None,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> Report:
    """Describe every standing keeper's photo from local day `since` on that is reachable and has no
    description yet, oldest first, at most `limit` this run; a line is appended per photo as soon as
    it is described, so an interrupted run keeps what it did and the next carries on. `dry_run`
    lists and writes nothing (no engine needed). `progress` gets one line per photo."""
    counts: dict[str, int] = {}
    photos, already = pending(lb, since, roots or Roots([]), counts)
    report = Report(
        len(photos),
        already,
        counts,
        photos,
        dry_run,
        None if engine is None else engine.name,
        None if engine is None else engine.model,
        since,
    )
    todo = photos if limit is None else photos[: max(0, limit)]
    if dry_run or not todo:
        return report
    if engine is None:
        raise EngineMissing(f"no vision engine; install {EXTRA}")
    if not engine.ready():
        if not fetch_model:
            raise ModelMissing(
                f"model {engine.model!r} is not on this machine; run once with --fetch-model to download it"
                " (the only time this command uses the network)"
            )
        engine.fetch()
    zone = ZoneInfo(str(lb.meta["timezone"]))
    with transcribe.offline():
        report.written = lb.append_many(_drafts(engine, todo, report, zone, progress))
    return report


def _drafts(
    engine: Engine,
    photos: Sequence[Photo],
    report: Report,
    zone: ZoneInfo,
    progress: Callable[[str], None] | None,
) -> Iterator[dict[str, Any]]:
    total = len(photos)
    for n, photo in enumerate(photos, 1):
        found = description_of(engine.describe(photo.file, PROMPT), faces_of(photo.photo))
        if found is None:
            report.unparsed += 1
            said = "no description in the answer"  # never the answer itself: it may hold what it must not
        else:
            report.done.append(Done(photo, found))
            said = found.text if len(found.text) <= 70 else found.text[:69].rstrip() + "…"
        if progress is not None:
            progress(f"  {n}/{total}  {_clock(photo.at, zone)}  {photo.name}: {said}")
        if found is not None:
            yield draft(photo, found, engine)


def summary(report: Report) -> str:
    """The closing lines of the command: what was done, what already was, what was skipped."""
    already = f" ({report.already} already described)" if report.already else ""
    if report.dry_run:
        head = f"dry run: {_plural(report.found, 'keeper')} would be described{already}; nothing written"
    else:
        head = f"described {_plural(report.written, 'keeper')} with {report.engine} ({report.model}){already}"
    lines = [head]
    if report.unparsed:
        lines.append(f"  {_plural(report.unparsed, 'answer')} could not be read; tried again next run")
    skipped = [f"{n:,} {PHRASES.get(key, key)}" for key, n in report.counts.items() if n]
    if skipped:
        lines.append(f"  skipped {', '.join(skipped)}")
    return "\n".join(lines)


def how_to(model: str) -> str:
    """The two lines a run that cannot start prints: how to install the extra, how to fetch the model."""
    return (
        f'  install:  pip install "{EXTRA}"      # or: uv tool install "{EXTRA}"; Apple silicon only\n'
        f"  fetch:    logbook describe keepers --fetch-model   # downloads {model} once; the only network use"
    )


# -- the engine ------------------------------------------------------------------------------------


def detect(
    model: str = DEFAULT_MODEL,
    importer: Callable[[str], Any] = importlib.import_module,
    platform: tuple[str, str] | None = None,
) -> Engine:
    """The engine this machine has: `mlx-vlm`, when it is installed; EngineMissing naming the extra
    and the platform when it is not."""
    try:
        module = importer(MlxVlm.module)
    except ImportError:
        here = platform or (sys.platform, machine())
        where = "" if here == ("darwin", "arm64") else f"; this is {here[0]}/{here[1]}, not Apple silicon"
        raise EngineMissing(
            f"no vision engine is installed; install {EXTRA} (mlx-vlm, Apple silicon only{where})"
        ) from None
    return MlxVlm(model, module, importer)


class MlxVlm:
    """Apple's MLX vision-language runner: any vision model the hub serves in MLX format, by its
    repository name; sampled greedily (temperature 0) for at most `MAX_TOKENS` tokens per answer.
    HEIC originals open when `pillow-heif` is installed (the extra brings it)."""

    name = "mlx-vlm"
    module = "mlx_vlm"

    def __init__(self, model: str, mlx: Any, importer: Callable[[str], Any]) -> None:
        self.model, self._mlx, self._import = model, mlx, importer
        self._loaded: tuple[Any, Any, Any] | None = None
        with contextlib.suppress(ImportError, AttributeError):
            importer("pillow_heif").register_heif_opener()

    def ready(self) -> bool:
        return transcribe.cached(self._import, self.model)

    def fetch(self) -> None:
        transcribe.download(self._import, self.model)

    def describe(self, image: Path, prompt: str) -> str:
        if self._loaded is None:
            model, processor = self._mlx.load(self.model)
            config = self._import("mlx_vlm.utils").load_config(self.model)
            self._loaded = (model, processor, config)
        model, processor, config = self._loaded
        chat = self._import("mlx_vlm.prompt_utils").apply_chat_template(
            processor, config, prompt, num_images=1
        )
        out = self._mlx.generate(
            model, processor, chat, image=[str(image)], max_tokens=MAX_TOKENS, temperature=0.0, verbose=False
        )
        return str(getattr(out, "text", out))


# -- small things ----------------------------------------------------------------------------------


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _clock(at: str, zone: ZoneInfo) -> str:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(zone)
    except ValueError:
        return at
    return when.strftime("%Y-%m-%d %H:%M")
