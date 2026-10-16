"""`logbook videos`: the family's videos after `sync drive --videos` has named them (RFC 0040).

`videos fetch` is the one command of the videos that touches the network: a file's bytes into the
bounded cache under `state/videos/`, one at a time, verified against the md5 Drive reported, resumable
(`logbook.contrib.videos`); with `--models`, the speech and vision models `videos infer` uses, once,
and nothing else. `videos infer` reads only what the cache holds, on this machine, with no socket: the
scenes of each file, what is said and shown in each, and one draft per scene proposing where and when
(`logbook.labs.scenes`).

`VideoQueue` is the video's queue as `review` drives it (RFC 0040, RFC 0037 §5): the sixth queue of the
one sitting, `review video`, declared here beside the commands whose drafts it answers."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..core.store import Logbook
from .common import Subparsers
from .derive import DESCRIBE_DEFAULT_MODEL, TRANSCRIBE_DEFAULT_MODEL
from .review import Queue

DEFAULT_CAP_GB = 8  # a copy of `contrib.videos.DEFAULT_CAP_BYTES` in gigabytes, for the help text
GB = 1_000_000_000


def videos_arguments(sub: Subparsers) -> None:
    """`logbook videos fetch|infer`."""
    s = sub.add_parser(
        "videos",
        help="family videos: fetch to a bounded cache; infer scenes, locally",
        description="The family's videos, which `sync drive --videos` names from Drive's metadata: `fetch`"
        " downloads files one at a time into a bounded cache under state/videos/ (the only command here"
        " that uses the network); `infer` finds the scenes of each cached file on this machine, hears and"
        " looks at each, and writes one draft per scene proposing where and when it was filmed, for you"
        " to confirm with `review video`. No video is ever copied into the record.",
    )
    verbs = s.add_subparsers(dest="verb", required=True, metavar="<verb>")
    v = verbs.add_parser(
        "fetch",
        help="download the next files nobody has inferred into the cache, one at a time; md5 verified",
        description="Download the video files the record names that are neither inferred nor cached, one"
        " at a time, in the folder's order, into state/videos/: each verified against the md5 Drive"
        " reported, a dropped connection resumed from its byte. The cache has a cap (default"
        f" {DEFAULT_CAP_GB} GB, so the largest file fits): a file bigger than the cap is refused and said"
        " so, and the run stops when the next file would take the cache past it. Needs drive.readonly"
        " delegated to the Google key (docs/adapters/videos.md).",
    )
    v.add_argument("--limit", type=int, metavar="N", help="at most N files this run")
    v.add_argument(
        "--again",
        action="store_true",
        help="fetch the files already inferred too, to infer them again under other models or settings",
    )
    v.add_argument(
        "--cache-gb",
        type=float,
        metavar="N",
        help=f"the cache's cap in gigabytes (default {DEFAULT_CAP_GB}); kept for the next run and for doctor",
    )
    v.add_argument(
        "--models",
        action="store_true",
        help="instead: download the speech and vision models `videos infer` uses, once; no video is fetched",
    )
    v.add_argument(
        "--speech-model",
        default=TRANSCRIBE_DEFAULT_MODEL,
        metavar="NAME",
        help=f"with --models: the Whisper model (default {TRANSCRIBE_DEFAULT_MODEL})",
    )
    v.add_argument(
        "--vision-model",
        default=DESCRIBE_DEFAULT_MODEL,
        metavar="NAME",
        help=f"with --models: the vision model (default {DESCRIBE_DEFAULT_MODEL})",
    )
    v.set_defaults(fn=cmd_videos)
    v = verbs.add_parser(
        "infer",
        help="the scenes of each cached file, heard and looked at here; a draft per scene; no network",
        description="For each file `videos fetch` left in the cache and not yet inferred under these models"
        " and settings: find its scenes (one continuous recording each: cuts in the picture, breaks in"
        " the soundtrack), hear each scene's speech with the transcribe extra and look at a few of its"
        " frames with the describe extra, all on this machine with no socket opened, and write one"
        " transcript line for the file and one draft per scene proposing where and when it was filmed,"
        " from what it shows and says and your places and assets, every sentence with its evidence."
        " The file is then deleted from the cache unless --keep. Needs ffmpeg on the PATH and the"
        " transcribe and describe extras; `videos fetch --models` fetches the models once.",
    )
    v.add_argument("--since", metavar="YYYY-MM-DD", help="only the video lines from this local day on")
    v.add_argument("--limit", type=int, metavar="N", help="at most N files this run")
    v.add_argument("--keep", action="store_true", help="keep each file in the cache once it is inferred")
    v.add_argument(
        "--dry-run",
        action="store_true",
        help="say which cached files would be inferred; no engine, nothing written",
    )
    v.add_argument(
        "--speech-model",
        default=TRANSCRIBE_DEFAULT_MODEL,
        metavar="NAME",
        help=f"the Whisper model (default {TRANSCRIBE_DEFAULT_MODEL})",
    )
    v.add_argument(
        "--vision-model",
        default=DESCRIBE_DEFAULT_MODEL,
        metavar="NAME",
        help=f"the vision model (default {DESCRIBE_DEFAULT_MODEL})",
    )
    v.set_defaults(fn=cmd_videos)


def cmd_videos(a: argparse.Namespace) -> None:
    """`videos fetch` (`_fetch`) and `videos infer` (`_infer`)."""
    if a.verb == "fetch":
        _fetch(a)
    elif a.verb == "infer":
        _infer(a)


def _infer(a: argparse.Namespace) -> None:
    """`videos infer [--since DAY] [--limit N] [--keep] [--dry-run]`: the cached files read on this
    machine (`labs.scenes.run`), a line per file on stderr as it goes, then what was written. Nothing in
    the cache says so and asks for nothing; exit 2 when ffmpeg, an extra or a model is missing, 1 when
    a model fails on a scene."""
    from ..core.export import parse_day
    from ..labs import scenes as infer

    if a.since is not None:
        try:
            parse_day(a.since)
        except ValueError as e:
            print(f"videos infer: {e}", file=sys.stderr)
            sys.exit(2)
    if a.limit is not None and a.limit < 1:
        print("videos infer: --limit is a number of files, 1 or more", file=sys.stderr)
        sys.exit(2)
    lb = Logbook.find()
    with infer.offline():  # before an engine's module is imported: the hub reads the flag once, then
        engines = None
        if not a.dry_run and _anything_cached(lb):
            try:
                engines = infer.detect(a.speech_model, a.vision_model)
            except infer.EngineMissing as e:
                print(f"videos infer: {e}", file=sys.stderr)
                sys.exit(2)
        media, speech, vision = engines if engines is not None else (None, None, None)
        try:
            report = infer.run(
                lb,
                media,
                speech,
                vision,
                since=a.since,
                limit=a.limit,
                keep=a.keep,
                dry_run=a.dry_run,
                progress=lambda text: print(text, file=sys.stderr),
            )
        except (infer.ModelMissing, infer.EngineMissing) as e:
            print(f"videos infer: {e}", file=sys.stderr)
            sys.exit(2)
        except infer.SceneFailed as e:
            print(
                f"videos infer: a model failed on {e}; nothing of that file was written and it stays in"
                " the cache (the files before it are written)",
                file=sys.stderr,
            )
            sys.exit(1)
    print(infer.summary(report))


def _anything_cached(lb: Logbook) -> bool:
    """Whether the cache holds a whole file: with none, no engine is looked for."""
    from ..contrib import videos

    return bool(videos.Cache(lb.root).complete())


def _fetch(a: argparse.Namespace) -> None:
    """`videos fetch [--limit N] [--again] [--cache-gb N]`: the next files into the cache
    (`contrib.videos.fetch`), a line per file, then the cache against its cap; exit 1 when a file
    could not be fetched whole or did not match its md5, or Google refused; 2 for a flag or a setting
    that is not one. `--models`: the two models, and nothing else."""
    from ..contrib import videos
    from ..contrib.adapters import drive_videos

    if a.models:
        _fetch_models(a)
        return
    if a.limit is not None and a.limit < 1:
        print("videos fetch: --limit is a number of files, 1 or more", file=sys.stderr)
        sys.exit(2)
    cap: int | None = None
    if a.cache_gb is not None:
        if not a.cache_gb > 0:
            print("videos fetch: --cache-gb is a size in gigabytes, above 0", file=sys.stderr)
            sys.exit(2)
        cap = max(1, round(a.cache_gb * GB))
    lb = Logbook.find()
    try:
        config = drive_videos.configure(os.environ)
    except ValueError as e:
        print(f"videos fetch: {e}", file=sys.stderr)
        sys.exit(2)
    if config is None:
        missing = [v for v in drive_videos.ENV if not os.environ.get(v, "").strip()]
        print(f"videos fetch: set {' and '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    try:
        report = videos.fetch(
            lb,
            config,
            limit=a.limit,
            cap_bytes=cap,
            progress=lambda text: print(text, file=sys.stderr),
            again=a.again,
        )
    except videos.StateError as e:
        print(f"videos fetch: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:  # Google refused the account, or could not be reached
        print(f"videos fetch: {e}", file=sys.stderr)
        sys.exit(1)
    for text in videos.fetch_lines(report):
        print(text)
    for problem in report.failed:
        print(f"videos fetch: {problem}", file=sys.stderr)
    if report.failed:
        sys.exit(1)


def _fetch_models(a: argparse.Namespace) -> None:
    """`videos fetch --models`: the speech and the vision model onto this machine, each once; the one
    other network event of the videos, and only when asked."""
    from ..labs import describe, transcribe

    try:
        speech = transcribe.detect(a.speech_model)
        vision = describe.detect(a.vision_model)
    except (transcribe.EngineMissing, describe.EngineMissing) as e:
        print(f"videos fetch: {e}", file=sys.stderr)
        sys.exit(2)
    for engine in (speech, vision):
        if engine.ready():
            print(f"{engine.name} {engine.model}: already on this machine")
        else:
            engine.fetch()
            print(f"{engine.name} {engine.model}: fetched")


# -- the review's queue --------------------------------------------------------------------------------


class VideoQueue(Queue):
    """The video's queue as `review` drives it (`logbook.commands.review.sitting`): the scenes `videos
    infer` proposed a place or a date for, `logbook.contrib.video_review`'s reading and writing.

    `--accept` takes what a scene's draft proposes and `--reject` writes the scene's no, as for every
    kind. A scene's own answers ride on the sitting's: `--place N NAME` and `--date N WHEN` accept scene
    N with the owner's own place or date, and `--ask N` keeps it to ask the family; `check` adds their
    numbers to `--accept`, so the sitting checks every number before the first line is written, and
    `write` tells them apart again. `--asked` and `--answered` list the scenes kept to ask and the ones
    confirmed, to answer or correct them; `--top N` the first N scenes."""

    kind = "video"

    def __init__(self) -> None:
        from ..contrib import video_review

        self.module = video_review
        self.error = video_review.ReviewError
        self.places: dict[int, str] = {}
        self.dates: dict[int, str] = {}
        self.asks: set[int] = set()
        self.lb: Logbook | None = None

    def check(self, a: argparse.Namespace) -> None:
        if a.top is not None and a.top < 0:
            raise self.error(f"--top takes a number from 0, not {a.top}")
        if a.asked and a.answered:
            raise self.error("--asked and --answered are two lists; say one")
        self.places = self._parts("--place", a.place)
        self.dates = self._parts("--date", a.date)
        self.asks = set(self.numbers(a.ask))
        accepted = set(self.numbers(a.accept))
        rejected = set(self.numbers(a.reject))
        for n in sorted(self.asks):
            other = next(
                (
                    flag
                    for flag, numbers in (
                        ("--accept", accepted),
                        ("--place", self.places),
                        ("--date", self.dates),
                        ("--reject", rejected),
                    )
                    if n in numbers
                ),
                None,
            )
            if other is not None:
                raise self.error(f"scene {n} is given {other} and --ask; say one")
        own = sorted((set(self.places) | set(self.dates) | self.asks) - accepted)
        a.accept = [*(a.accept or []), *map(str, own)]

    def _parts(self, flag: str, given: Sequence[Sequence[str]] | None) -> dict[int, str]:
        """`--place N NAME` or `--date N WHEN`, by scene number; a scene given the same part twice is
        refused, as the sitting refuses `--name` twice."""
        found: dict[int, str] = {}
        for n, text in given or []:
            number = self._number(n)
            if number in found:
                raise self.error(f"scene {number} is given {flag} twice; say one")
            found[number] = text
        return found

    def read(self, lb: Logbook, a: argparse.Namespace) -> Any:
        from ..core import sealing

        self.lb = lb
        mode = (
            "asked" if getattr(a, "asked", False) else "answered" if getattr(a, "answered", False) else "open"
        )
        try:
            return self.module.read(lb, mode)
        except sealing.IdentityRequired as e:  # said as this queue's refusal, in `review` alone too
            raise self.error(str(e)) from e

    def numbers(self, text: Sequence[str] | None) -> list[int]:
        return [self._number(part) for given in text or [] for part in str(given).split(",") if part.strip()]

    def _number(self, text: str) -> int:
        try:
            return int(str(text).strip())
        except ValueError:
            raise self.error(f"{text!r} is not a scene's number") from None

    def pick(self, report: Any, wanted: Sequence[int]) -> list[Any]:
        for n in wanted:
            if n < 1 or n > len(report.rows):
                raise self.error(f"scene {n} is not in the queue (1 to {len(report.rows)})")
        return [(n, report.rows[n - 1]) for n in wanted]

    def above(self, report: Any, score: str) -> list[Any]:
        raise self.error("a scene's proposal has no score; --all-above goes with person, org, idea and asset")

    def named(self, a: argparse.Namespace) -> list[tuple[str, str]]:
        if super().named(a):
            raise self.error(
                "--name goes with a new org, idea, asset or place;"
                " a scene takes --place N NAME or --date N WHEN"
            )
        return []

    def write(
        self, lb: Logbook, report: Any, chosen: Sequence[tuple[Any, str | None]], rejected: Sequence[Any]
    ) -> list[Any]:
        told = [n for (n, _row), _name in chosen]
        known, owned, today = self._registries(lb)
        answers = self.module.plan(
            report,
            [n for n in told if n not in self.asks],
            [n for n, _row in rejected],
            [n for n in told if n in self.asks],
            self.places,
            self.dates,
            known,
            owned,
            today,
        )
        return self.module.write(lb, report, answers)

    def _registries(self, lb: Logbook) -> tuple[list[Any], list[Any], date]:
        """places.json, assets.json and today, for the owner's own place and date."""
        from ..core import assets, places

        try:
            known, owned = places.read(lb.root), assets.read(lb.root)
        except (places.PlaceError, assets.AssetError) as e:
            raise self.error(str(e)) from e
        return known, owned, datetime.now(ZoneInfo(str(lb.meta["timezone"]))).date()

    def shown(self, lb: Logbook, report: Any, a: argparse.Namespace) -> tuple[Any, list[Any], dict[str, Any]]:
        rows = list(report.rows if a.top is None else report.rows[: a.top])
        return report, rows, {}

    def report_json(self, report: Any, shown: Sequence[Any], extra: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = self.module.to_json(report)
        data["rows"] = data["rows"][: len(shown)]
        return {**data, **extra}

    def rows(self, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> Iterable[str]:
        yield self.module.head_text(report)
        for n, row in enumerate(shown, 1):
            yield from self.module.row_lines(self.lb, n, row)
        if len(shown) < len(report.rows):
            yield f"  and {len(report.rows) - len(shown)} more; --top shows more"
        if report.rows:
            yield (
                "nothing written: `review video --accept N[,N]`, `--place N NAME`, `--date N WHEN`,"
                " `--reject N[,N]` or `--ask N[,N]`"
            )
        else:
            yield "nothing to review: `videos infer` proposes the scenes of the files in the cache"

    def written_rows(self, written: Sequence[Any]) -> Iterable[str]:
        for w in written:
            seq = f" (#{w.line['seq']})" if w.line is not None else ""
            yield f"{w.row.video.name} · {w.row.ref.split('#', 1)[1]}: {w.text}{seq}"

    def ask_on_a_tty(self, lb: Logbook, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> bool:
        """One scene at a time, as every queue asks on a terminal: y confirms what it proposes, n is the
        scene's no, a keeps it to ask the family, Enter skips, q or the end of input stops. The owner is
        asked with no lock held; each answer is written at once."""
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        print(self.module.head_text(report))
        for n, row in enumerate(shown, 1):
            for text in self.module.row_lines(lb, n, row):
                print(text)
            while True:  # the same scene until it is answered, skipped or the sitting stopped
                try:
                    said = input("  y confirm / n not so / a ask the family / Enter skip / q stop: ")
                except EOFError:
                    print()
                    return True
                said = said.strip().casefold()
                if said == "q":
                    return True
                if not said:
                    break
                verb = {"y": "accept", "n": "reject", "a": "ask"}.get(said)
                if verb is None:
                    print("  y, n, a, Enter or q")
                    continue
                try:
                    known, owned, today = self._registries(lb)
                    answers = self.module.plan(
                        report,
                        [n] if verb == "accept" else [],
                        [n] if verb == "reject" else [],
                        [n] if verb == "ask" else [],
                        {},
                        {},
                        known,
                        owned,
                        today,
                    )
                    written = self.module.write(lb, report, answers)
                except (self.error, ValueError) as e:
                    print(f"  {e}")
                    continue
                for text in self.written_rows(written):
                    print(f"  {text}")
                break
        return True
