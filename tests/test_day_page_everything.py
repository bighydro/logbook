"""The Day page shows everything a day held, folded: under each stay or move, the messages that fell
inside it by conversation (who, the network, how many, then each message's clock, sent or received
and its text, cut at 280 characters with the whole one click away on its line); at the foot,
"Everything this day held", every line of the day by source, in time order, each linked to its line.
Every new fold is closed until `?open=1`; the signed page digest does not move; and a busy day of
3,000 messages, 400 mails and 200 Notion events renders from the one `day.read` the page makes. On
the Oslo persona, who does not exist; every number is in 07700 900xxx and every address at
example.org; no test opens a connection."""

from __future__ import annotations

import os
import re
import shutil
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import phone_width
import pytest
from persona import KARI, persona_record, utc

from logbook import cli
from logbook.contrib import serve
from logbook.core import day as day_reader
from logbook.core import reading
from logbook.core.chain import Line
from logbook.core.store import Logbook

WEDNESDAY = "2026-06-10"  # the cafe with Kari at 12:00-13:00, the office either side
JUNE = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
INES = "+447700900123"  # a fictional number: no such person
LONG = "We moored by the north pontoon. " * 14  # 448 characters: cut on the page at 280
BUSY_PAGE_BYTES = 8_000_000  # the busy day's page stays under this (it measures about a third of it)
BUSY_SECONDS = 20.0  # a generous ceiling for slow CI; the PR records what it measured


class BusyDay(UserWarning):
    """How big the busy day's page is and how long it took, said on CI hardware."""


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return persona_record(tmp_path_factory.mktemp("day-everything"), mp).root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def message(
    at: str,
    text: str,
    chat: dict[str, Any],
    sender: dict[str, Any] | None = None,
    source: str = "whatsapp",
    n: int = 0,
    network: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"{source}:{chat['id']}:{at}:{n}",
        "chat": chat,
        "from_me": sender is None,
        "text": text,
    }
    if sender is not None:
        payload["sender"] = sender
    if network is not None:
        payload["extra"] = {"network": network}
    return {"at": at, "source": source, "kind": "message", "tier": 2, "payload": payload}


KARI_CHAT = {"id": f"{KARI['phone'].lstrip('+')}@s.whatsapp.net", "type": "direct", "name": "Kari"}
KARI_REF = {"kind": "phone", "value": KARI["phone"]}
INES_CHAT = {"id": "chat-ines", "type": "direct"}
INES_REF = {"kind": "handle", "value": "ines.nordmann"}
HARBOUR = {"id": "room-harbour", "type": "group", "name": "Harbour friends"}


def _cafe_messages(lb: Logbook) -> list[Line]:
    """Seven messages inside the cafe stay: three with Kari on WhatsApp (one sent), two with a handle
    the record does not name on Telegram, two in a group on Instagram through Beeper."""
    drafts = [
        message(utc(WEDNESDAY, "12:20"), "See you at the cafe?", KARI_CHAT, KARI_REF),
        message(utc(WEDNESDAY, "12:05"), "On my way", KARI_CHAT),
        message(utc(WEDNESDAY, "12:30"), LONG, KARI_CHAT, KARI_REF),
        message(utc(WEDNESDAY, "12:10"), "Ferry at four", INES_CHAT, INES_REF, "telegram"),
        message(utc(WEDNESDAY, "12:11"), "Booked", INES_CHAT, source="telegram"),
        message(
            utc(WEDNESDAY, "12:40"), "Who has the keys", HARBOUR, INES_REF, "beeper", network="instagram"
        ),
        message(utc(WEDNESDAY, "12:41"), "I do", HARBOUR, source="beeper", network="instagram"),
    ]
    lb.append_many(drafts)
    return [line for line in Logbook(lb.root).lines() if line["kind"] == "message"]


def _site(lb: Logbook, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: JUNE, **kw)


def _page(site: serve.Site, day: str = WEDNESDAY, query: str = "") -> str:
    response = site.respond(f"/day/{day}", query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _cafe_row(page: str) -> str:
    """The cafe stay's row, from its `<li>` to the next row of the timeline."""
    start = page.index('<li class="row stay"><span class="clock">12:0')
    end = page.index('<li class="row', start + 1)
    return page[start:end]


def _everything(page: str) -> str:
    start = page.index('<details class="held"')
    return page[start : page.index("</details>\n</section>", start)]


def test_messages_sit_under_their_row_by_conversation(lb: Logbook) -> None:
    lines = _cafe_messages(lb)
    page = _page(_site(lb))
    row = _cafe_row(page)
    assert "7 messages" in row, "the count stays on the row's summary line"
    summaries = re.findall(r'<details class="conversation"><summary>([^<]*)</summary>', row)
    assert summaries == [
        "Kari Nordmann · whatsapp · 3 messages",  # the canonical person the record names
        "ines.nordmann · telegram · 2 messages",  # the handle as the line has it
        "Harbour friends · instagram · 2 messages",  # a group by its name, the network Beeper says
    ], summaries
    kari_part = row[row.index(summaries[0]) : row.index(summaries[1])]
    clocks = re.findall(r'<span class="clock">([0-9:]+)</span>', kari_part)
    assert clocks == ["12:05", "12:20", "12:30"], "in time order"
    assert re.findall(r'<span class="way">(sent|received)</span>', kari_part) == [
        "sent",
        "received",
        "received",
    ]
    shown = LONG[:279] + "…"
    assert shown.replace("…", "") in kari_part and LONG.strip() not in kari_part, "cut at 280"
    (long_line,) = [line for line in lines if (line["payload"].get("text") == LONG)]
    assert f'href="/line/{long_line["id"]}"' in kari_part, "the whole text one click away"
    harbour = row[row.index(summaries[2]) :]
    assert "ines.nordmann" in harbour, "in a group, who wrote it"


def test_a_long_conversation_shows_ten_and_folds_the_rest(lb: Logbook) -> None:
    lb.append_many(
        message(utc(WEDNESDAY, f"12:{m:02d}"), f"note {m}", KARI_CHAT, KARI_REF, n=m) for m in range(5, 50)
    )
    row = _cafe_row(_page(_site(lb)))
    conversation = row[row.index('<details class="conversation">') :]
    assert "Kari Nordmann · whatsapp · 45 messages" in conversation
    head = conversation[: conversation.index('<details class="all">')]
    assert len(re.findall(r'<li class="message"', head)) == 10
    assert re.findall(r'<span class="clock">([0-9:]+)</span>', head) == [f"12:{m:02d}" for m in range(5, 15)]
    assert "<summary>show all 45</summary>" in conversation
    assert len(re.findall(r'<li class="message"', conversation)) == 45, "every message is on the page"
    short = [
        message(utc(WEDNESDAY, f"12:{m:02d}"), "x", INES_CHAT, INES_REF, "telegram", n=m) for m in range(30)
    ]
    lb.append_many(short)
    row = _cafe_row(_page(_site(lb)))
    ines = row[row.index("ines.nordmann · telegram · 30 messages") :]
    ines = ines[: ines.index("</details>")]
    assert len(re.findall(r'<li class="message"', ines)) == 30 and "show all" not in ines, (
        "30 is not more than 30"
    )


def test_everything_this_day_held_at_the_foot(lb: Logbook) -> None:
    lines = _cafe_messages(lb)
    page = _page(_site(lb))
    held = _everything(page)
    assert held.startswith('<details class="held"><summary>'), "closed by default"
    data = day_reader.read(lb, WEDNESDAY)
    summary = held[: held.index("</summary>")]
    for s in data["sources"]:
        assert f"{s['source']} {s['lines']:,}" in summary, s
    assert summary.index("dawarich") < summary.index("whatsapp"), "in the sources row's order"
    assert sum(s["lines"] for s in data["sources"]) == len(re.findall(r'<td class="at">', held))
    assert sum(s["lines"] for s in data["sources"]) == len(re.findall(r'class="raw"', held)), "each linked"
    (lunch,) = [
        x for x in Logbook(lb.root).lines() if x["kind"] == "event" and x["at"] == utc(WEDNESDAY, "12:00")
    ]
    for line in [*lines, lunch]:
        assert f'href="/line/{line["id"]}"' in held, line["kind"]
    whatsapp = held[held.index("<h3>whatsapp") :]
    whatsapp = whatsapp[: whatsapp.index("</table>")]
    assert re.findall(r'<td class="at">([0-9:]+)</td>', whatsapp) == ["12:05", "12:20", "12:30"]
    assert '<span class="kind">message</span>' in whatsapp
    assert "Kari Nordmann: See you at the cafe?" in whatsapp, "one line of what it was"
    assert "Lunch" in held, "the calendar entry, by its title"


def test_a_message_with_no_sender_is_not_mine_and_a_withheld_draft_keeps_its_words(lb: Logbook) -> None:
    unsigned = message(
        utc(WEDNESDAY, "12:42"), "Keys are in the box", HARBOUR, source="beeper", network="instagram"
    )
    unsigned["payload"]["from_me"] = False  # received, and the source named nobody
    words = "It rained every day and nobody went sailing."
    draft = {
        "at": utc(WEDNESDAY, "21:00"),
        "source": "model:example-7b",
        "kind": "draft",
        "tier": 2,
        "payload": {
            "schema": "draft/v1",
            "unit": "day",
            "subject": [WEDNESDAY],
            "read_head": "b" * 64,
            "read_count": 40,
            "language": "en",
            "segments": [{"text": words, "unsupported": True}],
        },
    }
    lb.append_many([unsigned, draft])  # no `dream` entry in the policy: every draft is withheld
    page = _page(_site(lb))
    held = _everything(page)
    assert "Harbour friends: Keys are in the box" in held and "me: Keys" not in held
    row = _cafe_row(page)
    assert '<span class="way">received</span> Keys are in the box' in row
    assert words not in page
    model = held[held.index("<h3>model:example-7b") :]
    model = model[: model.index("</table>")]
    assert "superseded by policy" in model and 'class="raw"' not in model, "a row, no words, no link"


def test_every_new_fold_is_closed_until_open_1(lb: Logbook) -> None:
    lb.append_many(
        message(utc(WEDNESDAY, f"12:{m:02d}"), f"note {m}", KARI_CHAT, KARI_REF, n=m) for m in range(5, 50)
    )
    closed = _page(_site(lb))
    for cls in ("conversation", "all", "held"):
        assert f'<details class="{cls}">' in closed, cls
        assert f'<details class="{cls}" open>' not in closed, cls
    opened = _page(_site(lb), query="open=1")
    for cls in ("conversation", "all", "held"):
        assert f'<details class="{cls}" open>' in opened, cls
        assert f'<details class="{cls}">' not in opened, cls
    assert "<script" not in closed.split("</h1>", 1)[1].split('<section class="close"')[0], "no script"


def test_every_fold_open_fits_a_phone(lb: Logbook) -> None:
    """#315's walk on a day with conversations, a group, a long text and an unbroken run: every fold
    open, the page still fits a phone's column."""
    _cafe_messages(lb)
    lb.append_many(
        [
            message(
                utc(WEDNESDAY, "12:50"), "https://example.org/" + "harbour" * 30, KARI_CHAT, KARI_REF, n=1
            ),
            *(
                message(utc(WEDNESDAY, f"12:{m:02d}"), f"note {m}", KARI_CHAT, KARI_REF, n=m)
                for m in range(5, 45)
            ),
        ]
    )
    page = _page(_site(lb), query="open=1")
    assert 'class="all" open' in page and 'class="held" open' in page
    assert phone_width.problems(page) == []


def test_a_line_above_the_gate_is_nowhere_on_the_page(lb: Logbook) -> None:
    _cafe_messages(lb)
    page = _page(_site(lb, tiers=[1]))
    assert "See you at the cafe" not in page and "whatsapp" not in page
    assert 'class="conversation"' not in page
    held = _everything(page)
    assert "message" not in held.split("</summary>", 1)[1]
    assert "Lunch" in held, "a tier-1 line is still there"


def test_a_static_page_keeps_to_its_rows(lb: Logbook) -> None:
    _cafe_messages(lb)
    page = _page(_site(lb, href=lambda path: f"site{path}.html"), query="open=1")
    assert "7 messages" in _cafe_row(page), "counted, as before"
    assert 'class="conversation"' not in page and 'class="held"' not in page
    assert "See you at the cafe" not in page


def test_the_signed_page_digest_does_not_move(lb: Logbook) -> None:
    _cafe_messages(lb)
    cli.main(["day", "sign", WEDNESDAY, "--at", "2026-06-10T22:00:00+02:00"])
    plain = day_reader.read(lb, WEDNESDAY)
    held = day_reader.read(lb, WEDNESDAY, held=True)
    assert plain["signed"]["page_matches"] is True
    assert held["signed"] == plain["signed"], "the folds read the same page"
    page = _page(_site(lb))
    opened = _page(_site(lb), query="open=1")
    sha = plain["signed"]["page_sha256"]
    for shown in (page, opened):
        assert f'page sha256 <code class="sha">{sha}</code>' in shown
        assert "the page has changed since" not in shown
    assert day_reader.read(lb, WEDNESDAY)["signed"] == plain["signed"], "rendering wrote nothing"


def test_the_day_reader_s_object_is_unchanged_without_held(lb: Logbook) -> None:
    _cafe_messages(lb)
    data = day_reader.read(lb, WEDNESDAY)
    assert "held" not in data
    for entry in data["timeline"]:
        assert set((entry.get("attached") or {}).get("messages") or {"count": 0, "lines": []}) == {
            "count",
            "lines",
        }


def _busy(lb: Logbook) -> None:
    """3,000 messages across 40 conversations through the office afternoon, 400 mails and 200 Notion
    events: every line synthetic, every number 07700 900xxx, every address at example.org."""
    drafts: list[dict[str, Any]] = []
    start = datetime.fromisoformat(utc(WEDNESDAY, "13:15").replace("Z", "+00:00"))
    for i in range(3_000):
        c = i % 40
        at = (start.timestamp() + i * 5) // 1
        stamp = datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        chat = {"id": f"4477009001{c:02d}@s.whatsapp.net", "type": "direct", "name": f"Friend {c}"}
        ref = {"kind": "phone", "value": f"+4477009001{c:02d}"}
        drafts.append(
            message(
                stamp,
                f"Message {i} about the mooring, the ferry and the weather." * 2,
                chat,
                None if i % 3 == 0 else ref,
                n=i,
            )
        )
    for i in range(400):
        stamp = utc(WEDNESDAY, f"{9 + i // 60:02d}:{i % 60:02d}")
        drafts.append(
            {
                "at": stamp,
                "source": "mail",
                "kind": "mail",
                "tier": 2,
                "payload": {
                    "schema": "mail/v1",
                    "raw_id": f"mail:{i}",
                    "message_id": f"{i}@mail.example.org",
                    "thread": f"thread-{i % 50}@mail.example.org",
                    "from": {"email": f"crew{i % 7}@example.org", "name": f"Crew {i % 7}"},
                    "to": [{"email": "ines@example.org", "name": "Ines Nordmann"}],
                    "subject": f"Harbour notice {i % 50}",
                    "direction": "received",
                },
            }
        )
    for i in range(200):
        stamp = utc(WEDNESDAY, f"{14 + i // 60:02d}:{i % 60:02d}")
        drafts.append(
            {
                "at": stamp,
                "end": stamp,
                "source": "notion",
                "kind": "event",
                "tier": 1,
                "payload": {
                    "schema": "event/v1",
                    "raw_id": f"notion:{i}",
                    "title": f"Edited the boat budget, page {i}",
                    "calendar": {"id": "notion", "name": "Notion"},
                    "all_day": False,
                },
            }
        )
    lb.append_many(drafts)


def test_a_busy_day_renders_from_one_reading(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _busy(lb)
    readings: list[tuple[str, str]] = []
    real = reading.read

    def counted(lb_: Logbook, first: str, last: str, *a: Any, **kw: Any) -> reading.Reading:
        readings.append((first, last))
        return real(lb_, first, last, *a, **kw)

    monkeypatch.setattr(reading, "read", counted)
    site = _site(lb)
    began = time.perf_counter()
    page = _page(site)
    took = time.perf_counter() - began
    assert readings == [("2026-06-09", WEDNESDAY)], "one reading of the record, the Day's own"
    size = len(page.encode("utf-8"))
    if os.environ.get("CI"):  # the figure the pull request records, in CI's warnings summary from any worker
        warnings.warn(BusyDay(f"busy day: {size:,} bytes, rendered in {took:.2f} s"), stacklevel=1)
    assert size < BUSY_PAGE_BYTES
    assert took < BUSY_SECONDS
    assert len(re.findall(r'<details class="conversation"', page)) == 40
    assert len(re.findall(r'<details class="all"', page)) == 40, "75 messages each: ten, then the rest folded"
    held = _everything(page)
    assert "whatsapp 3,000" in held[: held.index("</summary>")]
    assert "mail 400" in held[: held.index("</summary>")]
    assert "notion 200" in held[: held.index("</summary>")]
