"""`logbook videos`: the family's videos after `sync drive --videos` has named them (RFC 0039).

`videos fetch` is the one command of the videos that touches the network: a file's bytes into the
bounded cache under `state/videos/`, one at a time, verified against the md5 Drive reported, resumable
(`logbook.contrib.videos`); with `--models`, the speech and vision models `videos infer` uses, once,
and nothing else. `videos infer` reads only what the cache holds, on this machine, with no socket: the
scenes of each file, what is said and shown in each, and one draft per scene proposing where and when
(`logbook.labs.scenes`)."""

from __future__ import annotations

import argparse
import os
import sys

from ..core.store import Logbook
from .common import Subparsers
from .derive import DESCRIBE_DEFAULT_MODEL, TRANSCRIBE_DEFAULT_MODEL

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
        " to confirm with `review videos`. No video is ever copied into the record.",
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
    the cache says so and asks for nothing; exit 2 when ffmpeg, an extra or a model is missing."""
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
