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
when both apply."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from . import last_run

if TYPE_CHECKING:
    from .backup import RestoreTest

TOKEN_ENV = "LOGBOOK_NOTIFY_TELEGRAM_TOKEN"
CHAT_ENV = "LOGBOOK_NOTIFY_TELEGRAM_CHAT"
API_ENV = "LOGBOOK_NOTIFY_TELEGRAM_API"
ENV = (TOKEN_ENV, CHAT_ENV, API_ENV)
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


__all__ = [
    "API",
    "CHAT_ENV",
    "ENV",
    "TOKEN_ENV",
    "Telegram",
    "alert_block",
    "compose",
    "configure",
    "is_wrong",
    "send",
    "week_block",
]
