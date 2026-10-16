"""The owner's say over what the sources saw (RFC 0037): `review KIND`, one sitting for a person, an
org, an idea, an asset and a place, and `status KIND ENTITY DISPOSITION`, what the owner decided.

`review` is one loop, `sitting`, over one queue per kind (`Queue`): the person's is people review's
(`logbook.contrib.people_review`, its queue declared beside `people review` in `people.py`), the
place's is places review's (`places_review`, beside `setup places review` in `places.py`), and the
org's, the idea's and the asset's are `logbook.contrib.entity_review`'s (`EntityQueue`, here).
`people review` and `setup places review` run the same sitting, so the numbers, the checks, what is
written and what is printed are one implementation for all five. Nothing is written unless told;
every number is checked before the first line is written. `review` with no kind lists every queue,
one block each, and writes nothing.

A sixth queue is no kind of thing the record names: `video`, the scenes `videos infer` proposed a place
or a date for (RFC 0040), `logbook.contrib.video_review`'s (`VideoQueue`, declared beside `videos` in
`videos.py`). The same sitting drives it: `--accept` takes what a scene's draft proposes, `--reject`
writes the scene's no (`scene-review/v1`, never an `entity-review/v1` line), and its own answers
(`VIDEO_FLAGS`) are refused for every other kind as a place's options are."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from typing import Any, NoReturn

from ..core.store import Logbook
from .common import Subparsers

# speakers: RFC 0038 §4, `commands.speakers`; video: RFC 0040, `commands.videos`
KINDS = ("person", "org", "idea", "asset", "place", "speakers", "video")
PLACE_FLAGS = (
    ("--near", "near"),
    ("--radius", "radius"),
    ("--verbose", "verbose"),
    ("--ask-photos", "ask_photos"),
    ("--all", "all"),
    ("--limit", "limit"),
    ("--photos-library", "photos_library"),
    ("--migrate-rejects", "migrate_rejects"),
)
TOP_FLAGS = (("--top", "top"),)  # a place's and a video's: the first N proposals, or scenes
VIDEO_FLAGS = (
    ("--place", "place"),
    ("--date", "date"),
    ("--ask", "ask"),
    ("--asked", "asked"),
    ("--answered", "answered"),
)
TELLS = (("--accept", "accept"), ("--reject", "reject"), ("--name", "name"), ("--all-above", "all_above"))
NOTHING_ABOVE = "nothing to write: no proposal at or above that score"


class Queue:
    """One kind's queue as the sitting drives it: the kind's module reads and writes, this says how
    the sitting asks. `error` is the kind's refusal (one sentence, nothing written)."""

    kind = ""
    error: type[Exception] = ValueError

    def check(self, a: argparse.Namespace) -> None:
        """Refuse the options that do not go with this kind."""

    def read(self, lb: Logbook, a: argparse.Namespace) -> Any:
        raise NotImplementedError

    def numbers(self, text: Sequence[str] | None) -> list[int]:
        raise NotImplementedError

    def pick(self, report: Any, wanted: Sequence[int]) -> list[Any]:
        raise NotImplementedError

    def above(self, report: Any, score: str) -> list[Any]:
        raise NotImplementedError

    def named(self, a: argparse.Namespace) -> list[tuple[str, str]]:
        """The `--name N NAME` pairs as given."""
        value = getattr(a, "name", None)
        return [(str(n), str(text)) for n, text in value] if isinstance(value, list) else []

    def before_writing(
        self,
        lb: Logbook,
        report: Any,
        accepted: Sequence[int],
        rejected: Sequence[int],
        a: argparse.Namespace,
    ) -> Any:
        """The report the told numbers are written against (places: with the photos asked)."""
        return report

    def write(
        self, lb: Logbook, report: Any, chosen: Sequence[tuple[Any, str | None]], rejected: Sequence[Any]
    ) -> list[Any]:
        raise NotImplementedError

    def shown(self, lb: Logbook, report: Any, a: argparse.Namespace) -> tuple[Any, list[Any], dict[str, Any]]:
        """The report, the proposals to list, and what the JSON adds."""
        return report, list(report.proposals), {}

    def report_json(self, report: Any, shown: Sequence[Any], extra: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = report.to_json()
        return {**data, **extra}

    def rows(self, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> Iterable[str]:
        raise NotImplementedError

    def written_rows(self, written: Sequence[Any]) -> Iterable[str]:
        raise NotImplementedError

    def ask_on_a_tty(self, lb: Logbook, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> bool:
        """Ask for each proposal shown when on a terminal; True when it did."""
        return False


def sitting(queue: Queue, lb: Logbook, a: argparse.Namespace) -> None:
    """One review sitting over `queue`: the numbers told (`--accept`, `--name`, `--reject`,
    `--all-above`) checked, every one of them before the first line is written, then written and
    said; or, told nothing, the queue listed (as JSON, asked on a terminal, or printed). Raises
    `queue.error` for anything the record cannot act on."""
    queue.check(a)
    report = queue.read(lb, a)
    accepted = queue.numbers(getattr(a, "accept", None))
    rejected = queue.numbers(getattr(a, "reject", None))
    named: list[tuple[int, str]] = []
    for number, text in queue.named(a):
        found = queue.numbers([number])
        if len(found) != 1:
            raise queue.error(f'--name takes one number and a name: --name 3 "The cabin", not {number!r}')
        named.append((found[0], text))
    told = [*accepted, *(n for n, _ in named)]
    both = sorted(set(told) & set(rejected))
    if both:
        raise queue.error(f"proposal {', '.join(map(str, both))} is both accepted and rejected; say one")
    twice = sorted({n for n in told if told.count(n) > 1})
    if twice:
        raise queue.error(
            f"proposal {', '.join(map(str, twice))} is given --accept and --name, or --name twice; say one"
        )
    score = getattr(a, "all_above", None)
    if score is not None:
        accepted = [*accepted, *(p.number for p in queue.above(report, score) if p.number not in told)]
    if accepted or named or rejected:
        queue.pick(report, [*accepted, *(n for n, _ in named), *rejected])  # every number, before anything
        report = queue.before_writing(lb, report, accepted, rejected, a)
        chosen: list[tuple[Any, str | None]] = [(p, None) for p in queue.pick(report, accepted)]
        chosen += [
            (p, text) for p, (_n, text) in zip(queue.pick(report, [n for n, _ in named]), named, strict=True)
        ]
        written = queue.write(lb, report, chosen, queue.pick(report, rejected))
        if getattr(a, "json", False):
            print(json.dumps({"written": [w.to_json() for w in written]}, indent=2, ensure_ascii=False))
            return
        if not written:
            print(NOTHING_ABOVE)
        for text in queue.written_rows(written):
            print(text)
        return
    if score is not None:
        print(NOTHING_ABOVE)
        return
    report, shown, extra = queue.shown(lb, report, a)
    if getattr(a, "json", False):
        print(json.dumps(queue.report_json(report, shown, extra), indent=2, ensure_ascii=False))
        return
    if shown and queue.ask_on_a_tty(lb, report, shown, a):
        return
    for text in queue.rows(report, shown, a):
        print(text)


# -- org, idea, asset ------------------------------------------------------------------------------------


class EntityQueue(Queue):
    """The org's, the idea's or the asset's queue (`logbook.contrib.entity_review`)."""

    def __init__(self, kind: str):
        from ..contrib import entity_review

        self.kind = kind
        self.module = entity_review
        self.error = entity_review.ReviewError

    def read(self, lb: Logbook, a: argparse.Namespace) -> Any:
        return self.module.read(lb, self.kind)

    def numbers(self, text: Sequence[str] | None) -> list[int]:
        return self.module.numbers(text, self.kind)

    def pick(self, report: Any, wanted: Sequence[int]) -> list[Any]:
        return self.module.pick(report, wanted)

    def above(self, report: Any, score: str) -> list[Any]:
        return self.module.above(report, score)

    def write(
        self, lb: Logbook, report: Any, chosen: Sequence[tuple[Any, str | None]], rejected: Sequence[Any]
    ) -> list[Any]:
        return [*self.module.accept(lb, report, chosen), *self.module.reject(lb, report, rejected)]

    def rows(self, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> Iterable[str]:
        return self.module.rows(report)

    def written_rows(self, written: Sequence[Any]) -> Iterable[str]:
        return self.module.written_rows(written)

    def ask_on_a_tty(self, lb: Logbook, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> bool:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        rows = list(self.module.rows(report))
        print(rows[0])
        by_number = {p.number: p for p in report.proposals}
        for text in rows[1:-1]:
            print(text)
            number = int(text.split()[0])
            p = by_number[number]
            hint = "y to accept, n to reject" + (", or type a name" if p.new else "")
            while True:
                try:
                    answer = input(f"      {hint}; Enter skips, q stops: ").strip()
                except EOFError:
                    print()
                    return True
                if answer.casefold() == "q":
                    return True
                if not answer:
                    break
                try:
                    if answer.casefold() == "n":
                        written = self.module.reject(lb, report, [p])
                    elif answer.casefold() == "y" or not p.new:
                        written = self.module.accept(lb, report, [(p, None)])
                    else:
                        written = self.module.accept(lb, report, [(p, answer)])
                except (self.error, ValueError) as e:
                    print(f"      {e}")
                    continue
                for line in self.module.written_rows(written):
                    print(f"      {line}")
                break
        return True


# -- the command -----------------------------------------------------------------------------------------


def review_arguments(sub: Subparsers) -> None:
    """`logbook review [KIND]`."""
    s = sub.add_parser(
        "review",
        help="what the sources saw, set beside what you named; accept, reject",
        description="One sitting for the five kinds of thing the record names (RFC 0037): the observed"
        " people, orgs, ideas, assets and places not yet placed, each proposed against the canonical"
        " ones with the evidence, numbered, or as a new one; nothing is written unless told, and nothing"
        " is looked up. `review person` is `people review`, `review place` is `setup places review`;"
        " `review speakers` the voices of your recordings not yet named (RFC 0038)."
        " With no KIND, every queue, one block each."
        " `review video`: the scenes `videos infer` proposed a place or a date for (RFC 0040).",
    )
    s.add_argument("kind", nargs="?", choices=KINDS, metavar="KIND", help=f"one of {', '.join(KINDS)}")
    s.add_argument("--accept", action="append", metavar="N[,N]", help="accept these proposals")
    s.add_argument(
        "--reject",
        action="append",
        metavar="N[,N]",
        help="reject these: one entity-review/v1 line each (a scene's: scene-review/v1)",
    )
    s.add_argument(
        "--name",
        nargs=2,
        action="append",
        metavar=("N", "NAME"),
        help="accept a new one under your own name",
    )
    s.add_argument("--all-above", metavar="SCORE", help="accept every proposal at or above this score")
    s.add_argument("--json", action="store_true", help="the queue, or what was written, as one JSON object")
    g = s.add_argument_group("place", "with `review place`, as `setup places review` takes them")
    g.add_argument("--top", type=int, metavar="N", help="only the first N")
    g.add_argument("--near", metavar="PLACE", help="only those within 5 km of a named place, or of lat,lon")
    g.add_argument("--radius", type=float, metavar="M", help="metres: one spot (default 75)")
    g.add_argument("--verbose", action="store_true", help="every name on its own")
    g.add_argument(
        "--ask-photos", action="store_true", help="ask your photo libraries what they call each blank"
    )
    g.add_argument("--all", action="store_true", help="with --ask-photos: the places that have a name too")
    g.add_argument("--limit", type=int, metavar="N", help="with --ask-photos: photos per place (default 50)")
    g.add_argument("--photos-library", metavar="PATH", help="with --ask-photos: the Photos library to read")
    g.add_argument(
        "--migrate-rejects",
        action="store_true",
        help="write the noes state/places-review.json holds from before 0.7 as lines, once",
    )
    from .speakers import speakers_arguments

    speakers_arguments(s)
    v = s.add_argument_group("video", "with `review video` (RFC 0040); --top above counts its scenes")
    v.add_argument(
        "--place",
        nargs=2,
        action="append",
        metavar=("N", "NAME"),
        help="confirm scene N at your own place: a name of places.json or an asset of assets.json; none for"
        " no place",
    )
    v.add_argument(
        "--date",
        nargs=2,
        action="append",
        metavar=("N", "WHEN"),
        help="confirm scene N on your own date: 1994, 1994-07, 1994-07-14, 'summer 1994', 1994-06..1994-08;"
        " none for no date",
    )
    v.add_argument(
        "--ask", action="append", metavar="N[,N]", help="ask the family: an open task, list videos"
    )
    v.add_argument(
        "--asked", action="store_true", help="the scenes kept to ask the family, to answer them now"
    )
    v.add_argument(
        "--answered",
        action="store_true",
        help="the scenes already confirmed, to correct one: a new answer supersedes the standing line",
    )
    s.set_defaults(fn=cmd_review)


def cmd_review(a: argparse.Namespace) -> None:
    """`review [KIND] [--accept N[,N]] [--reject N[,N]] [--name N NAME] [--all-above SCORE] [--json]`
    (and, for a place, `setup places review`'s options): one sitting (`sitting`). With no KIND,
    every queue in turn, nothing written."""
    lb = Logbook.find()
    if a.kind is None:
        _every_queue(lb, a)
        return
    if a.kind not in ("place", "video") and a.top is not None:  # --top first, as when it was a place's alone
        given = [flag for flag, dest in (*TOP_FLAGS, *PLACE_FLAGS) if getattr(a, dest) not in (None, False)]
        _refuse(
            f"review {a.kind}",
            f"{', '.join(given)} go with `review place`"
            if len(given) > 1
            else "--top goes with `review place` or `review video`",
        )
    if a.kind != "place":
        given = [flag for flag, dest in PLACE_FLAGS if getattr(a, dest) not in (None, False)]
        if given:
            _refuse(
                f"review {a.kind}",
                f"{', '.join(given)} {'goes' if len(given) == 1 else 'go'} with `review place`",
            )
    if a.kind != "video":
        given = [flag for flag, dest in VIDEO_FLAGS if getattr(a, dest) not in (None, False)]
        if given:
            _refuse(
                f"review {a.kind}",
                f"{', '.join(given)} {'goes' if len(given) == 1 else 'go'} with `review video`",
            )
    from . import speakers

    if a.kind == "speakers":
        from ..contrib.speakers_review import ReviewError

        try:
            speakers.sitting(lb, a)
        except (ReviewError, ValueError) as e:
            _refuse("review speakers", str(e))
        return
    given = speakers.refuse_flags(a.kind, a)
    if given:
        _refuse(
            f"review {a.kind}",
            f"{', '.join(given)} {'goes' if len(given) == 1 else 'go'} with `review speakers`",
        )
    queue = queue_of(a.kind)
    try:
        sitting(queue, lb, a)
    except (queue.error, ValueError) as e:
        _refuse(f"review {a.kind}", str(e))


def queue_of(kind: str) -> Queue:
    """The queue of one kind, its module imported now."""
    if kind == "person":
        from .people import PersonQueue

        return PersonQueue()
    if kind == "place":
        from .places import PlaceQueue

        return PlaceQueue()
    if kind == "speakers":
        from .speakers import SpeakerQueue

        return SpeakerQueue()
    if kind == "video":
        from .videos import VideoQueue

        return VideoQueue()
    return EntityQueue(kind)


def _every_queue(lb: Logbook, a: argparse.Namespace) -> None:
    from .speakers import FLAGS as SPEAKER_FLAGS

    told = [
        flag
        for flag, dest in (*TELLS, *TOP_FLAGS, *PLACE_FLAGS, *VIDEO_FLAGS, *SPEAKER_FLAGS)
        if getattr(a, dest, None) not in (None, False)
    ]
    if told:
        _refuse("review", f"say which kind {' '.join(told)} is for: `review {'|'.join(KINDS)} …`")
    found: dict[str, Any] = {}
    for kind in KINDS:
        queue = queue_of(kind)
        try:
            report = queue.read(lb, a)
            report, shown, extra = queue.shown(lb, report, a)
        except (queue.error, ValueError) as e:
            _refuse(f"review {kind}", str(e))
        if a.json:
            found[kind] = queue.report_json(report, shown, extra)
            continue
        print(kind)
        for text in queue.rows(report, shown, a):
            print(f"  {text}")
    if a.json:
        print(json.dumps(found, indent=2, ensure_ascii=False))


def _refuse(prog: str, reason: str) -> NoReturn:
    print(f"{prog}: {reason}", file=sys.stderr)
    sys.exit(2)


# -- status ----------------------------------------------------------------------------------------------


def status_arguments(sub: Subparsers) -> None:
    """`logbook status KIND ENTITY DISPOSITION` and `logbook status list KIND`."""
    s = sub.add_parser(
        "status",
        help="what you decided about an org, idea, place or asset; list KIND",
        description="One status/v1 line (RFC 0037): an org's hold, add, sell, let-go, exited or passed; an"
        " idea's spark, exploring, build, built or killed; a place let go; an asset sold or let go. Tier 3"
        " for an org, 2 for the rest, no money on it; --reason puts your words on the line, and for an idea,"
        " a place or an asset also as a tier-2 note beside it (an org's stay on its line); a place or an"
        " asset it closes keeps its registry entry, closed with `until`; --portfolio names which portfolio"
        " holds an org, on its tier-3 line. `status list KIND`: every one of a kind, its current status,"
        " stale ones and muted proposals said. A person has no status; a goal is reviewed.",
    )
    s.add_argument(
        "words",
        nargs="+",
        metavar="KIND ENTITY DISPOSITION | list KIND",
        help="org, idea, place or asset; the entity by name, alias, id or ref; the disposition",
    )
    s.add_argument("--reason", metavar="TEXT", help="why, in your words; required for passed, let-go, killed")
    s.add_argument("--at", metavar="YYYY-MM-DD", help="the day you decided (default today)")
    s.add_argument(
        "--portfolio",
        metavar="TEXT",
        help='org only: which portfolio holds it, free text, on its tier-3 status line; "" clears it;'
        " left out, it stays as it stood",
    )
    s.add_argument("--json", action="store_true", help="the line written, or the list, as one JSON object")
    s.set_defaults(fn=cmd_status)


def cmd_status(a: argparse.Namespace) -> None:
    """`status KIND ENTITY DISPOSITION [--reason "…"] [--at DATE] [--portfolio TEXT] [--json]`: one
    status line through
    the writer (`logbook.contrib.entity_status.write`); `status list KIND [--json]`: the list. A
    refusal is one sentence on stderr, exit 2, nothing written."""
    from ..contrib import entities, entity_status

    lb = Logbook.find()
    words = list(a.words)
    try:
        if words[0] == "list":
            if len(words) != 2 or a.reason is not None or a.at is not None or a.portfolio is not None:
                raise entity_status.StatusError("`status list KIND` takes a kind and nothing else")
            found = entity_status.listing(lb, words[1])
            if a.json:
                print(json.dumps(found.to_json(), indent=2, ensure_ascii=False))
                return
            for text in entity_status.rows(found):
                print(text)
            return
        if len(words) != 3:
            entity_status.check_kind(words[0])
            raise entity_status.StatusError(
                'say KIND ENTITY DISPOSITION: `status org "Nordmann Verft AS" hold`'
            )
        written = entity_status.write(lb, words[0], words[1], words[2], a.reason, a.at, portfolio=a.portfolio)
    except (entity_status.StatusError, entities.EntityError) as e:
        _refuse("status", str(e))
    if a.json:
        print(json.dumps(written.to_json(), indent=2, ensure_ascii=False))
        return
    for text in entity_status.written_rows(written):
        print(text)
