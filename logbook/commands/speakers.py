"""`logbook review speakers` (RFC 0038 §4): the voices not yet named, and the owner's say.

The sitting is `review KIND`'s shape (`logbook.commands.review`): the queue listed, as JSON or asked
on a terminal; the numbers told checked, every one before the first line, then written and said. It
is a sitting of its own rather than `review.sitting` with another queue, because its answers are
five where `sitting` knows three (`--unnamed`, `--same-as` and `--consent` change what a line says
and must be checked with the rest), a number may name one recording of a row (`N.M`), and `--named`
lists another set, the voices already named, to correct. `SpeakerQueue` is the `Queue` that `review`
with no KIND lists like the others. The reading, the checks and the one writer are
`logbook.contrib.speakers_review`; nothing here writes a line."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from ..core.store import Logbook
from .review import NOTHING_ABOVE, Queue

FLAGS = (
    ("--unnamed", "unnamed"),
    ("--same-as", "same_as"),
    ("--consent", "consent"),
    ("--play", "play"),
    ("--named", "named"),
    ("--recording", "recording"),
    ("--day", "day"),
)


class SpeakerQueue(Queue):
    """The speakers' queue as `review` with no KIND lists it."""

    kind = "speakers"

    def __init__(self) -> None:
        from ..contrib import speakers_review

        self.module = speakers_review
        self.error = speakers_review.ReviewError

    def read(self, lb: Logbook, a: argparse.Namespace) -> Any:
        return self.module.read(
            lb,
            bool(getattr(a, "named", False)),
            getattr(a, "recording", None),
            getattr(a, "day", None),
            hear=hearing(lb),
        )

    def shown(self, lb: Logbook, report: Any, a: argparse.Namespace) -> tuple[Any, list[Any], dict[str, Any]]:
        return report, list(report.rows), {}

    def report_json(self, report: Any, shown: Sequence[Any], extra: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = report.to_json()
        return data

    def rows(self, report: Any, shown: Sequence[Any], a: argparse.Namespace) -> Iterable[str]:
        return self.module.rows(report)

    def written_rows(self, written: Sequence[Any]) -> Iterable[str]:
        return self.module.written_rows(written)


def speakers_arguments(s: argparse.ArgumentParser) -> None:
    """The options `review speakers` adds to `review`'s."""
    g = s.add_argument_group("speakers", "with `review speakers` (RFC 0038 §4)")
    g.add_argument("--unnamed", action="append", metavar="N[,N]", help="a person, not you, you will not name")
    g.add_argument("--same-as", metavar="M", help="with --unnamed: the same unnamed person as voice M")
    g.add_argument(
        "--consent",
        action="append",
        metavar="N=yes|no|unknown",
        help="what you state of their consent to be recorded, on the line row N's answer writes",
    )
    g.add_argument(
        "--play", metavar="N", help="play voice N's first twenty seconds alone, here; nothing written"
    )
    g.add_argument("--named", action="store_true", help="the voices already named, to correct one")
    g.add_argument("--recording", metavar="ID", help="with --named: one transcript, by its id or seq")
    g.add_argument("--day", metavar="YYYY-MM-DD", help="with --named: the transcripts of one day")


def refuse_flags(kind: str, a: argparse.Namespace) -> list[str]:
    """The speakers' options given to another kind."""
    return [flag for flag, dest in FLAGS if getattr(a, dest, None) not in (None, False)]


def sitting(lb: Logbook, a: argparse.Namespace) -> None:
    """`review speakers [--accept N[,N]] [--name N NAME] [--unnamed N[,N] [--same-as M]] [--reject
    N[,N]] [--consent N=…] [--all-above SCORE] [--play N] [--named --recording ID|--day DAY] [--json]`.
    Raises `speakers_review.ReviewError` for anything the record cannot act on, nothing written."""
    from ..contrib import speakers_review as module

    report = module.read(lb, bool(a.named), a.recording, a.day, hear=hearing(lb))
    if a.play is not None:
        told = [
            flag
            for flag, dest in (("--accept", "accept"), ("--name", "name"), ("--reject", "reject"))
            if getattr(a, dest)
        ]
        if told or a.unnamed or a.all_above is not None or a.consent:
            raise module.ReviewError("--play writes nothing: give it alone")
        print(module.play(lb, report, a.play, _decoder()))
        return
    answers = module.answers_from(
        report, a.accept, a.name, a.unnamed, a.reject, a.all_above, a.consent, a.same_as
    )
    if answers:
        written = module.answer(lb, report, answers)
        if a.json:
            print(json.dumps({"written": [w.to_json() for w in written]}, indent=2, ensure_ascii=False))
            return
        for text in module.written_rows(written):
            print(text)
        return
    if a.all_above is not None:
        print(NOTHING_ABOVE)
        return
    if a.json:
        print(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
        return
    if report.rows and sys.stdin.isatty() and sys.stdout.isatty():
        ask(lb, report)
        return
    for text in module.rows(report):
        print(text)


def ask(lb: Logbook, report: Any) -> None:
    """On a terminal, row by row (§4.2): `y` accepts, `n` rejects, `u` is unnamed, `p` plays, anything
    else is a name, Enter skips, `q` stops; after a name or an `unnamed` for a voice that is not yours,
    `recorded with their consent? y / n / Enter for unknown`. Each answer is written at once."""
    from ..contrib import speakers_review as module

    lines = list(module.rows(report))
    print(lines[0])
    for row in report.rows:
        for text in module._row_text(row, report, None):
            print(text)
        number = str(row.number)
        offer = "y accepts, n rejects, " if row.candidates and not row.close and not report.named else ""
        hint = f"{offer}u unnamed, p plays, or type a name; Enter skips, q stops: "
        while True:
            try:
                said = input(f"      {hint}").strip()
            except EOFError:
                print()
                return
            folded = said.casefold()
            if folded == "q":
                return
            if not said:
                break
            try:
                if folded == "p":
                    print(f"      {module.play(lb, report, number, _decoder())}")
                    continue
                if folded in ("y", "n") and not offer:
                    raise module.ReviewError(
                        f"row {number} proposes {'two, neither taken' if row.candidates else 'nobody'}:"
                        " type a name, u, p, Enter or q"
                    )
                if folded == "y":
                    found = module.Answer(number, module.ACCEPT)
                elif folded == "n":
                    found = module.Answer(number, module.REJECT)
                elif folded == "u":
                    found = module.Answer(number, module.UNNAMED)
                else:
                    found = module.Answer(number, module.NAME, name=said)
                if found.verdict != module.REJECT and not _owners(module, report, found):
                    found = module.Answer(found.number, found.verdict, found.name, consent=_consent())
                written = module.answer(lb, report, [found])
            except (module.ReviewError, ValueError) as e:
                print(f"      {e}")
                continue
            for text in module.written_rows(written):
                print(f"      {text}")
            break


def _owners(module: Any, report: Any, found: Any) -> bool:
    """Whether the answer binds the owner's own voice, which is not asked for consent."""
    if found.verdict == module.UNNAMED:
        return False
    if found.verdict == module.ACCEPT:
        row, _voices = module.pick(report, found.number)
        return bool(row.candidates and row.candidates[0].owner)
    _entity, _label, owner, _mint = module._named(report, found.name or "")
    return bool(owner)


def _consent() -> str:
    try:
        said = input("      recorded with their consent? y / n / Enter for unknown: ").strip().casefold()
    except EOFError:
        print()
        return "unknown"
    return {"y": "yes", "yes": "yes", "n": "no", "no": "no"}.get(said, "unknown")


def _decoder() -> Any:
    """The transcription engine's own decoder (the `transcribe` extra), loaded now, inside the
    command (`tests/test_cli_lazy.py`); one sentence naming the extra without it."""
    from ..contrib.speakers_review import ReviewError
    from ..labs import transcribe

    try:
        engine = transcribe.detect()
    except transcribe.EngineMissing as e:
        raise ReviewError(f"--play needs the audio decoded on this machine: {e}") from e
    return engine.load


def hearing(lb: Logbook) -> Callable[[], Any] | None:
    """For a record that names no recipients, which keeps no voiceprint registry (RFC 0038 §5.1): the
    pipeline's own embedding model, when the `speakers` extra and its models are on this machine,
    for the review to hear the voices it compares for this run and forget them after. Asked only
    when there is a voice to compare; never downloads; the labs module is imported only then. A
    model the cache holds but cannot load is one sentence naming the fetch."""
    if lb.recipients:
        return None

    def found() -> Any:
        from ..contrib.speakers_review import ReviewError
        from ..labs import diarize

        if not diarize.installed() or not diarize.status().ready:
            return None
        return _Guarded(diarize.embedder(), diarize.ModelsMissing, ReviewError)

    return found


class _Guarded:
    """An embedding model whose `ModelsMissing` is the review's own one sentence."""

    def __init__(self, inner: Any, missing: type[Exception], error: type[Exception]) -> None:
        self._inner, self._missing, self._error = inner, missing, error
        self.model, self.dim = inner.model, inner.dim

    @property
    def digest(self) -> str:
        try:
            return str(self._inner.digest)
        except self._missing as e:
            raise self._error(str(e)) from None

    def load(self, path: Any) -> Any:
        return self._inner.load(path)

    def embed(self, samples: Any, rate: int, pieces: Any) -> Any:
        try:
            return self._inner.embed(samples, rate, pieces)
        except self._missing as e:
            raise self._error(str(e)) from None
