"""The notifier: one Telegram message from the scheduled run (`logbook sync --scheduled`), only when
something is wrong — a source failed, `doctor` warned or failed — or once a week, on Sunday evening,
with the week's counts. Never a line's content, never a name from the record: counts, source names and
check names only, in the fixed format below (docs/schedule.md, "What it tells you and when").

It is off unless both `LOGBOOK_NOTIFY_TELEGRAM_TOKEN` and `LOGBOOK_NOTIFY_TELEGRAM_CHAT` are set, in
`~/.config/logbook/sync.env` beside the sources' keys; without them nothing is sent and nothing is
said about it. The owner installing the schedule (`sync --install-schedule`) is the explicit command
that authorises these calls: no other command sends anything, and `sync --all` by hand sends nothing.
One request per run at most, `POST https://api.telegram.org/bot<token>/sendMessage`; the token is never
printed. `LOGBOOK_NOTIFY_TELEGRAM_API` points the request elsewhere (a test's local server).

```
logbook 2026-10-08 19:00: something is wrong
sync: 5 sources: 3 ok, 1 failed (gcal), 1 skipped
doctor: 12 pass, 1 warn, 1 fail; fail: record; warn: sync:gcal

logbook week to 2026-10-11: 14 runs, 13 clean
lines: immich 1,204, gcal 31; 1,235 in all
doctor: 13 pass, 1 warn, 0 fail
restore test: passed 2026-10-04
```

The first block is sent when something is wrong, the second on Sunday evening, both in one message
when both apply.

**The daily loop** (`daily`, docs/digest.md "Delivery"): with the same two variables set, two more
messages a day, each on its own and each at most once a local day (`state/notify-daily.json`, the
day each last went out):

```
Your Day page for 2026-10-16 is ready · 42 lines
https://logbook.example.org/day/2026-10-16

Your question for 2026-10-16: What were you glad of today?
```

The first after the 06:00 close (`sync --scheduled --close`), for the day the close closed: its date,
the count of its lines, and a link when `LOGBOOK_NOTIFY_LINK_HOST` names the host `serve` answers on
(none otherwise). The second at `LOGBOOK_NOTIFY_EVENING_HOUR` (a local hour, 0 to 23; no evening
message without it): the digest's closing question for the day (`digest.read`, the question bank of
RFC 0027), its text alone. A question the bank fills from the day (`Was {proposed} with you?`) would
carry a name or a sentence of the record, so it is not sent: the message says the question waits in
`logbook digest`. Nothing else of the day is in either: no place, no person, no line's text, no
source. The day is claimed in the state file before the request and given back when the request
fails for sure (a refusal, a connection that never opened; a timeout may have delivered it, so the
claim stands), so a day's message is never sent twice; a state file that cannot be written sends
nothing and never fails the run."""

from __future__ import annotations

import contextlib
import json
import os
import re
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..core import day_start
from ..core.store import RETRACTION, Logbook, retractions
from . import last_run

if TYPE_CHECKING:
    from .backup import RestoreTest

TOKEN_ENV = "LOGBOOK_NOTIFY_TELEGRAM_TOKEN"
CHAT_ENV = "LOGBOOK_NOTIFY_TELEGRAM_CHAT"
API_ENV = "LOGBOOK_NOTIFY_TELEGRAM_API"
LINK_ENV = "LOGBOOK_NOTIFY_LINK_HOST"  # the host `serve` answers on: the morning message links its Day
EVENING_ENV = "LOGBOOK_NOTIFY_EVENING_HOUR"  # the local hour of the evening question; none without it
ENV = (TOKEN_ENV, CHAT_ENV, API_ENV)
DAILY_ENV = (LINK_ENV, EVENING_ENV)  # the daily loop's: read only when the notifier is on
DAILY_FILE = PurePosixPath("state/notify-daily.json")  # record-relative: the day each daily message went
READY, QUESTION = "ready", "question"  # the two daily messages, as the state file names them
_HOST = re.compile(r"(https?://)?[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?\Z")
API = "https://api.telegram.org"
TIMEOUT_S = 20.0


@dataclass(frozen=True)
class Telegram:
    token: str
    chat: str
    api: str = API

    @property
    def url(self) -> str:
        return f"{self.api.rstrip('/')}/bot{self.token}/sendMessage"


def configure(env: Mapping[str, str], say: Callable[[str], None] | None = None) -> Telegram | None:
    """The notifier when both variables are set; None, silently, when neither is. One of the two
    set is said once through `say` (the name of the missing one, never a value)."""
    token = env.get(TOKEN_ENV, "").strip()
    chat = env.get(CHAT_ENV, "").strip()
    if not token and not chat:
        return None
    if not token or not chat:
        if say is not None:
            missing = CHAT_ENV if token else TOKEN_ENV
            say(f"notify: telegram: set {missing} too, or neither; nothing sent")
        return None
    return Telegram(token, chat, env.get(API_ENV, "").strip() or API)


# -- the message -----------------------------------------------------------------------------------------


def is_wrong(run: last_run.Run) -> bool:
    """A source failed, or the doctor warned or failed: what gets a message."""
    return bool(run.failed_sources) or run.doctor is None or not run.doctor.clean


def alert_block(run: last_run.Run, local: datetime) -> list[str]:
    """The first block: what is wrong, by source name and check name only."""
    ok = sum(1 for s in run.sources if s.result == "ok")
    failed = run.failed_sources
    skipped = sum(1 for s in run.sources if s.result.startswith("skipped"))
    named = f" ({', '.join(failed)})" if failed else ""
    lines = [
        f"logbook {local:%Y-%m-%d %H:%M}: something is wrong",
        f"sync: {len(run.sources)} sources: {ok} ok, {len(failed)} failed{named}, {skipped} skipped",
    ]
    doctor = run.doctor
    if doctor is None:
        lines.append("doctor: did not run")
        return lines
    text = f"doctor: {doctor.passed} pass, {len(doctor.warned)} warn, {len(doctor.failed)} fail"
    parts = []
    if doctor.failed:
        parts.append("fail: " + ", ".join(doctor.failed))
    if doctor.warned:
        parts.append("warn: " + ", ".join(doctor.warned))
    lines.append(text + ("; " + "; ".join(parts) if parts else ""))
    return lines


def week_block(
    run: last_run.Run, week: Sequence[last_run.WeekEntry], local: datetime, restore: RestoreTest | None
) -> list[str]:
    """The second block: the week's runs and lines, the doctor now, the restore test."""
    counted = last_run.week_lines(week)
    total = sum(counted.values())
    lines = [
        f"logbook week to {local:%Y-%m-%d}: {len(week)} runs, {sum(1 for e in week if e.clean)} clean",
        "lines: "
        + (
            ", ".join(f"{n} {c:,}" for n, c in counted.items()) + f"; {total:,} in all" if counted else "none"
        ),
    ]
    doctor = run.doctor
    if doctor is not None:
        lines.append(f"doctor: {doctor.passed} pass, {len(doctor.warned)} warn, {len(doctor.failed)} fail")
    if restore is None:
        lines.append("restore test: none yet")
    else:
        lines.append(f"restore test: {restore.status} {restore.at:%Y-%m-%d}")
    return lines


def compose(
    run: last_run.Run,
    week: Sequence[last_run.WeekEntry],
    local: datetime,
    restore: RestoreTest | None,
    *,
    weekly: bool,
) -> str | None:
    """The one message for this run, or None when there is nothing to say: nothing wrong and not
    the Sunday evening run."""
    blocks: list[list[str]] = []
    if is_wrong(run):
        blocks.append(alert_block(run, local))
    if weekly:
        blocks.append(week_block(run, week, local, restore))
    if not blocks:
        return None
    return "\n\n".join("\n".join(block) for block in blocks)


# -- sending ---------------------------------------------------------------------------------------------


def send(config: Telegram, text: str, opener: Callable[..., object] = urllib.request.urlopen) -> None:
    """One request. OSError (urllib's) when it cannot be delivered; ValueError when the API says no
    (its description, never the token)."""
    body = json.dumps({"chat_id": config.chat, "text": text, "disable_web_page_preview": True}).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        config.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with opener(request, timeout=TIMEOUT_S) as response:  # type: ignore[attr-defined]
        raw = response.read()
    try:
        answer = json.loads(raw)
    except ValueError:
        raise ValueError("the API did not answer with JSON") from None
    if not isinstance(answer, dict) or not answer.get("ok"):
        why = answer.get("description") if isinstance(answer, dict) else None
        raise ValueError(f"the API refused the message: {why or 'no reason given'}")


# -- the daily loop -------------------------------------------------------------------------------------


def link_base(env: Mapping[str, str]) -> str | None:
    """The address the Day's link starts with, from `LOGBOOK_NOTIFY_LINK_HOST` (`logbook.example.org`,
    `https://logbook.example.org:8443`, `http://192.0.2.10:8000`): https:// when no scheme is given,
    no trailing slash. None when it is not set; ValueError, naming the variable and never the value,
    for anything that is not a host with an optional port and path."""
    text = env.get(LINK_ENV, "").strip()
    if not text:
        return None
    if _HOST.match(text) is None:
        raise ValueError(f"{LINK_ENV} is not a host (logbook.example.org, or https://host:port); no link")
    return (text if "://" in text else f"https://{text}").rstrip("/")


def evening_hour(env: Mapping[str, str]) -> int | None:
    """The local hour of the evening question, from `LOGBOOK_NOTIFY_EVENING_HOUR`; None when it is not
    set; ValueError, naming the variable, for anything but a whole hour from 0 to 23."""
    text = env.get(EVENING_ENV, "").strip()
    if not text:
        return None
    if not text.isdigit() or not 0 <= int(text) <= 23:
        raise ValueError(f"{EVENING_ENV} is not an hour from 0 to 23; no evening question")
    return int(text)


def ready_text(day: str, count: int, base: str | None) -> str:
    """The morning message: the date, the count of its lines, the link when there is a host."""
    text = f"Your Day page for {day} is ready · {count} line{'s' if count != 1 else ''}"
    return text if base is None else f"{text}\n{base}/day/{day}"


def question_text(day: str, question: str | None) -> str:
    """The evening message: the date and the question, or, for a question filled from the day, where
    it waits."""
    if question is None:
        return f"Your question for {day} waits in `logbook digest`"
    return f"Your question for {day}: {question}"


def lines_on(lb: Logbook, day: str) -> int:
    """How many lines the record holds on the local `day`: the ones not retracted, a retraction
    itself not counted. A count, never what they say."""
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        return sum(
            1 for line in idx.day(day) if line.get("kind") != RETRACTION and str(line["id"]) not in retracted
        )


def evening_question(lb: Logbook, day: str) -> str | None:
    """The digest's closing question for `day` as `logbook digest` asks it, its text when the bank's
    question is fixed text; None when the bank filled it from the day (a placeholder), which is not
    sent."""
    from . import digest, questions

    asked = digest.read(lb, day)["question"]
    if asked.get("id") is None:
        return str(asked["text"])  # the fallback: fixed text, of no id
    bank = {q.id: q for q in questions.read(lb.root)}
    found = bank.get(str(asked["id"]))
    if found is None or questions.placeholders(found.text):
        return None
    return str(asked["text"])


def daily_path(root: Path) -> Path:
    return Path(root).joinpath(*DAILY_FILE.parts)


def _sent(root: Path) -> dict[str, str]:
    try:
        data = json.loads(daily_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def _keep(root: Path, sent: Mapping[str, str]) -> None:
    path = daily_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(dict(sent), indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def _maybe_delivered(e: Exception) -> bool:
    """Whether a failed request may still have reached the API: a timeout, after the request went,
    unlike a refusal or a connection that never opened. Such a day stays claimed: never twice."""
    reason = getattr(e, "reason", None)
    return isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)


def daily(
    lb: Logbook,
    env: Mapping[str, str],
    now: datetime,
    *,
    close: bool,
    say: Callable[[str], None],
    warn: Callable[[str], None],
    opener: Callable[..., object] = urllib.request.urlopen,
) -> list[str]:
    """The daily loop's messages for this scheduled run, each sent at most once a local day: after
    the close (`close`), the Day page of the day it closed; at or after the evening hour, the day's
    question. Nothing at all when the notifier is not configured. The kinds sent, in order; what it
    did is said through `say`, a failure through `warn` (never the token)."""
    config = configure(env)
    if config is None:
        return []
    try:
        days = day_start.of(lb.meta)
    except day_start.DayStartError as e:
        warn(f"notify: telegram: {e}; no daily message")
        return []
    today = days.today(now)
    wanted: list[tuple[str, str, Callable[[], str]]] = []
    if close:
        closed = (today - timedelta(days=1)).isoformat()
        try:
            base = link_base(env)
        except ValueError as e:
            warn(f"notify: {e}")
            base = None
        wanted.append((READY, closed, lambda: ready_text(closed, lines_on(lb, closed), base)))
    try:
        hour = evening_hour(env)
    except ValueError as e:
        warn(f"notify: {e}")
        hour = None
    if hour is not None and now.astimezone(days.zone).hour >= hour:
        evening = today.isoformat()
        wanted.append((QUESTION, evening, lambda: question_text(evening, evening_question(lb, evening))))
    done: list[str] = []
    for kind, day, compose_text in wanted:
        sent = _sent(lb.root)
        if sent.get(kind) is not None and sent[kind] >= day:
            continue
        try:
            text = compose_text()
        except Exception as e:  # the run goes on: a message is never the run's failure
            warn(f"notify: telegram: the {kind} message for {day} was not sent: {e}")
            continue
        try:
            _keep(lb.root, {**sent, kind: day})  # claimed before the request: never twice
        except OSError as e:
            warn(f"notify: telegram: {DAILY_FILE} cannot be written ({e.strerror}); nothing sent")
            continue
        try:
            send(config, text, opener)
        except (OSError, ValueError) as e:
            if not _maybe_delivered(e):  # a timeout may have delivered it: the claim stands
                with contextlib.suppress(OSError):
                    _keep(lb.root, sent)  # given back: a later run may send it
            warn(f"notify: telegram: {e}")
            continue
        done.append(kind)
        what = "the Day page" if kind == READY else "the evening question"
        say(f"notify: telegram: sent ({what} for {day})")
    return done


__all__ = [
    "API",
    "CHAT_ENV",
    "ENV",
    "TOKEN_ENV",
    "Telegram",
    "alert_block",
    "compose",
    "configure",
    "daily",
    "evening_hour",
    "is_wrong",
    "link_base",
    "send",
    "week_block",
]
