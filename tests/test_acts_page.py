"""The acts on the Day page of `logbook serve`: a star on every row that is a line and a "with…" field
with names completed from the canonical people. Both post through the functions the CLI runs
(`stars.star`, `stars.unstar`, `presence.state`), so the lines are what `logbook star`, `unstar` and
`with` write, byte for byte but for the clock, and both are answered from this machine only. The
Days page lists the window's stars. On the Oslo persona, who does not exist."""

from __future__ import annotations

import html
import http.client
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from persona import persona_record, utc

from logbook import cli
from logbook.contrib import serve
from logbook.core import policy
from logbook.core.chain import Line
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
WEDNESDAY, FRIDAY = "2026-06-10", "2026-06-12"
LUNCH = utc(WEDNESDAY, "12:00")
CAFE_PHOTO = utc(WEDNESDAY, "12:30")
CLOCK = ("id", "seq", "prev", "hash", "recorded_at")


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return persona_record(tmp_path_factory.mktemp("acts-page"), mp).root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


@pytest.fixture
def other(pristine: Path, tmp_path: Path) -> Path:
    """A second copy of the record, for the CLI's side of a byte-for-byte comparison."""
    root = tmp_path / "other"
    shutil.copytree(pristine, root)
    return root


def _page(site: serve.Site, day: str = WEDNESDAY, query: str = "") -> str:
    response = site.respond(f"/day/{day}", query)
    assert response.status == 200, response.body[:200]
    return response.body.decode("utf-8")


def _of(root: Path, kind: str) -> list[Line]:
    return [line for line in Logbook(root).lines() if line["kind"] == kind]


def _at(root: Path, kind: str, at: str) -> Line:
    (found,) = [line for line in _of(root, kind) if line["at"] == at]
    return found


def _content(line: Line, *also: str) -> dict[str, Any]:
    return {k: v for k, v in line.items() if k not in CLOCK and k not in also}


def _cli(monkeypatch: pytest.MonkeyPatch, root: Path, back: Path, *args: str) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    cli.main(list(args))
    monkeypatch.setenv("LOGBOOK_HOME", str(back))


def _star_form(text: str, line: str) -> str:
    match = re.search(
        rf'<form class="star"[^>]*>(?:(?!</form>).)*value="{re.escape(line)}"(?:(?!</form>).)*</form>', text
    )
    assert match is not None, f"no star form for {line}"
    return match.group(0)


# -- the page ------------------------------------------------------------------------------------------


def test_every_row_that_is_a_line_carries_a_star_and_a_stay_does_not(lb: Logbook) -> None:
    text = _page(serve.Site(lb))
    lunch = _at(lb.root, "event", LUNCH)
    form = _star_form(text, lunch["id"])
    assert 'action="/star"' in form and 'value="star"' in form and "☆" in form
    assert f'name="day" value="{WEDNESDAY}"' in form
    attached = re.findall(r"<ul class=\"attached\">(.*?)</ul>", text, re.S)
    for block in attached:
        for item in re.findall(r"<li[^>]*>.*?</li>", block, re.S):
            if '<span class="kind">messages</span>' in item:
                continue  # a count of lines, not a line
            assert 'class="star"' in item, item
    photo = _at(lb.root, "photo", CAFE_PHOTO)
    assert f'<span id="l-{photo["id"]}">{photo["payload"]["file_name"]}<form class="star"' in text
    for row in re.findall(
        r'<li class="row (?:stay|move)">.*?<span class="kind">(?:stay|move)</span>[^<]*', text
    ):
        assert "form" not in row, "a stay or a move is derived, not a line"


def test_starring_on_the_page_writes_what_the_cli_writes(
    lb: Logbook, other: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = serve.Site(lb)
    lunch = _at(lb.root, "event", LUNCH)
    _cli(monkeypatch, other, lb.root, "star", lunch["id"])
    response = site.write(
        serve.STAR_PATH, {"act": "star", "line": lunch["id"], "day": WEDNESDAY}, LOOPBACK, None
    )
    assert response.status == 303 and response.location == f"/day/{WEDNESDAY}#l-{lunch['id']}"
    [mine], [theirs] = _of(lb.root, "star"), _of(other, "star")
    assert _content(mine) == _content(theirs)
    form = _star_form(_page(site), lunch["id"])
    assert 'value="unstar"' in form and 'aria-pressed="true"' in form and "★" in form
    again = site.write(
        serve.STAR_PATH, {"act": "star", "line": lunch["id"], "day": WEDNESDAY}, LOOPBACK, None
    )
    assert again.status == 303 and len(_of(lb.root, "star")) == 1, "starred already: nothing written"

    _cli(monkeypatch, other, lb.root, "unstar", lunch["id"])
    response = site.write(
        serve.STAR_PATH, {"act": "unstar", "line": lunch["id"], "day": WEDNESDAY, "open": "1"}, LOOPBACK, None
    )
    assert response.status == 303 and response.location == f"/day/{WEDNESDAY}?open=1#l-{lunch['id']}"
    [mine], [theirs] = _of(lb.root, "retraction"), _of(other, "retraction")
    [my_star], [their_star] = _of(lb.root, "star"), _of(other, "star")
    assert (
        mine["payload"]["supersedes"] == my_star["id"] and theirs["payload"]["supersedes"] == their_star["id"]
    )
    mine["payload"]["supersedes"] = theirs["payload"]["supersedes"] = "the star"  # a line's id is its own
    assert _content(mine, "at") == _content(theirs, "at")
    stale = site.write(
        serve.STAR_PATH, {"act": "unstar", "line": lunch["id"], "day": WEDNESDAY}, LOOPBACK, None
    )
    assert stale.status == 409 and "not starred" in stale.body.decode("utf-8")


def test_a_photo_starred_on_the_page_is_the_keeper_the_cli_writes(
    lb: Logbook, other: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = serve.Site(lb)
    photo = _at(lb.root, "photo", CAFE_PHOTO)
    _cli(monkeypatch, other, lb.root, "star", photo["id"])
    assert (
        site.write(
            serve.STAR_PATH, {"act": "star", "line": photo["id"], "day": WEDNESDAY}, LOOPBACK, None
        ).status
        == 303
    )
    [mine], [theirs] = _of(lb.root, "keeper"), _of(other, "keeper")
    assert _content(mine) == _content(theirs) and mine["payload"]["lane"] == "memory"
    text = _page(site)
    assert 'value="unstar"' in _star_form(text, photo["id"])
    keeper_row = re.search(r'<li id="l-[^"]*" [^>]*><span class="kind">keeper</span>.*?</li>', text, re.S)
    assert keeper_row is not None and "★" in keeper_row.group(0), "the keeper's row is a star too"


def test_a_form_that_is_wrong_or_stale_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    site = serve.Site(lb)
    lunch = _at(lb.root, "event", LUNCH)
    seq = lb.meta["seq"]
    assert (
        site.write(
            serve.STAR_PATH, {"act": "shine", "line": lunch["id"], "day": WEDNESDAY}, LOOPBACK, None
        ).status
        == 400
    )
    assert site.write(serve.STAR_PATH, {"act": "star", "day": WEDNESDAY}, LOOPBACK, None).status == 400
    assert (
        site.write(
            serve.STAR_PATH, {"act": "star", "line": lunch["id"], "day": "Wednesday"}, LOOPBACK, None
        ).status
        == 400
    )
    cli.main(["derive", "keepers"])
    capsys.readouterr()
    keeper = _of(lb.root, "keeper")[0]
    seq = Logbook(lb.root).meta["seq"]
    refused = site.write(
        serve.STAR_PATH, {"act": "star", "line": keeper["id"], "day": WEDNESDAY}, LOOPBACK, None
    )
    assert refused.status == 400 and "is a keeper" in refused.body.decode("utf-8")
    assert site.write(serve.WITH_PATH, {"day": FRIDAY, "names": " , "}, LOOPBACK, None).status == 400
    assert Logbook(lb.root).meta["seq"] == seq
    for path in (serve.STAR_PATH, serve.WITH_PATH):
        assert site.respond(path, "").status == 405


# -- with -----------------------------------------------------------------------------------------------


def test_the_with_field_completes_from_the_canonical_people_and_never_the_owner(lb: Logbook) -> None:
    text = _page(serve.Site(lb), FRIDAY)
    form = re.search(r'<form class="with".*?</form><datalist id="people">(.*?)</datalist>', text, re.S)
    assert form is not None and 'action="/with"' in form.group(0) and 'list="people"' in form.group(0)
    assert re.findall(r'<option value="([^"]+)">', form.group(1)) == ["Kari Nordmann", "Ola Nordmann"]
    assert '<dt id="with">with</dt><dd><span class="mute">nobody the record saw</span>' in text


def test_with_on_the_page_writes_what_the_cli_writes(
    lb: Logbook, other: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = serve.Site(lb)
    _cli(monkeypatch, other, lb.root, "with", FRIDAY, "Ola", "Kari", "--at", "12:00")
    response = site.write(
        serve.WITH_PATH, {"day": FRIDAY, "names": "Ola, Kari", "at": "12:00"}, LOOPBACK, None
    )
    assert response.status == 303 and response.location == f"/day/{FRIDAY}#with"
    mine = [line for line in _of(lb.root, "note") if "with" in (line["payload"].get("labels") or [])]
    theirs = [line for line in _of(other, "note") if "with" in (line["payload"].get("labels") or [])]
    assert [_content(line) for line in mine] == [_content(line) for line in theirs] and len(mine) == 2
    text = _page(site, FRIDAY)
    row = text[text.index('<dt id="with">') :].split("</dd>")[0]
    assert "Ola Nordmann (you said)" in row and "Kari Nordmann (you said)" in row


def test_a_name_the_record_does_not_place_is_refused_on_the_page_with_the_hint(lb: Logbook) -> None:
    site = serve.Site(lb)
    seq = lb.meta["seq"]
    response = site.write(serve.WITH_PATH, {"day": FRIDAY, "names": "Ola, Per"}, LOOPBACK, None)
    body = response.body.decode("utf-8")
    assert response.status == 400 and "Per" in body and "people review" in body
    assert Logbook(lb.root).meta["seq"] == seq


# -- this machine only -----------------------------------------------------------------------------------


def test_an_act_that_is_not_from_this_machine_is_refused(lb: Logbook) -> None:
    site = serve.Site(lb)
    lunch = _at(lb.root, "event", LUNCH)
    forms = {
        serve.STAR_PATH: {"act": "star", "line": lunch["id"], "day": WEDNESDAY},
        serve.WITH_PATH: {"day": FRIDAY, "names": "Ola", "at": "12:00"},
    }
    seq = lb.meta["seq"]
    for path, form in forms.items():
        for client in ("192.168.1.20", "203.0.113.9", "::ffff:203.0.113.9", ""):
            response = site.write(path, form, client, None)
            assert response.status == 403 and "this machine" in response.body.decode("utf-8"), (path, client)
        for origin in ("http://example.org", "http://localhost:8765", "null"):
            assert site.write(path, form, LOOPBACK, origin).status == 403, (path, origin)
    assert Logbook(lb.root).meta["seq"] == seq
    assert site.write(serve.STAR_PATH, forms[serve.STAR_PATH], "::1", "http://[::1]:8765").status == 303
    assert (
        site.write(serve.WITH_PATH, forms[serve.WITH_PATH], LOOPBACK, "http://127.0.0.1:8765").status == 303
    )


def test_the_star_round_trips_over_the_socket(lb: Logbook) -> None:
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        lunch = _at(lb.root, "event", LUNCH)
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=10)
        body = urlencode({"act": "star", "line": lunch["id"], "day": WEDNESDAY})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{LOOPBACK}:{port}"}
        connection.request("POST", serve.STAR_PATH, body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b""
        connection.request("GET", f"/day/{WEDNESDAY}")
        reply = connection.getresponse()
        page = reply.read().decode("utf-8")
        assert reply.status == 200 and 'aria-pressed="true"' in _star_form(page, lunch["id"])
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- what a static page and the Days page show --------------------------------------------------------------


def test_a_static_page_shows_the_stars_and_carries_no_form(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lunch = _at(lb.root, "event", LUNCH)
    cli.main(["star", lunch["id"], "--note", "the window table"])
    capsys.readouterr()
    text = serve.Site(Logbook(lb.root), href=lambda path: None).page_day(WEDNESDAY)
    assert "<form" not in text and "<datalist" not in text
    assert '<span class="star on" title="starred: the window table">★</span>' in text


def test_the_days_page_lists_the_window_s_stars(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lunch = _at(lb.root, "event", LUNCH)
    photo = _at(lb.root, "photo", CAFE_PHOTO)
    cli.main(["star", lunch["id"], "--note", "the window table"])
    cli.main(["star", photo["id"]])
    capsys.readouterr()
    text = serve.Site(Logbook(lb.root)).respond("/days", f"from={WEDNESDAY}&to={FRIDAY}").body.decode("utf-8")
    starred = text[text.index("<h2>Starred</h2>") :]
    items = re.findall(r"<li>.*?</li>", starred)
    assert len(items) == 2
    assert f'<span class="clock">{WEDNESDAY} 12:00</span>' in items[0], "the record's day, then the clock"
    assert f'<a href="/day/{WEDNESDAY}#l-{lunch["id"]}">Lunch</a> · the window table' in items[0]
    assert f'<a href="/day/{WEDNESDAY}#l-{photo["id"]}">{photo["payload"]["file_name"]}</a>' in items[1]
    empty = (
        serve.Site(Logbook(lb.root)).respond("/days", "from=2026-06-17&to=2026-06-18").body.decode("utf-8")
    )
    assert "Starred" not in empty


# -- another writer -------------------------------------------------------------------------------------


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_star_unstar_and_with_answer_409_while_another_command_writes(lb: Logbook) -> None:
    """The owner's decision of 14 October: an act in the Library never waits for another writer.
    While a command holds the record's writer lock, the star, the unstar and the "with…" field each
    answer 409 with one sentence, and nothing is written, as Reflect and Sign do."""
    site = serve.Site(lb)
    lunch = _at(lb.root, "event", LUNCH)
    photo = _at(lb.root, "photo", CAFE_PHOTO)
    assert (
        site.write(
            serve.STAR_PATH, {"act": "star", "line": lunch["id"], "day": WEDNESDAY}, LOOPBACK, None
        ).status
        == 303
    )
    path = lb.root / "state" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = {"pid": os.getppid(), "command": "logbook sync", "since": "2026-06-12T21:00:00Z"}
    path.write_text(json.dumps(holder), encoding="utf-8")
    before = _files(lb.root)
    forms = (
        (serve.STAR_PATH, {"act": "star", "line": photo["id"], "day": WEDNESDAY}),
        (serve.STAR_PATH, {"act": "unstar", "line": lunch["id"], "day": WEDNESDAY}),
        (serve.WITH_PATH, {"day": FRIDAY, "names": "Ola", "at": "12:00"}),
    )
    for to, form in forms:
        response = site.write(to, form, LOOPBACK, None)
        said = response.body.decode("utf-8")
        assert response.status == 409, (to, form)
        assert "another logbook command is writing to this record (logbook sync" in said, said
        assert "nothing was written" in said and "--no-wait" not in said
    assert _files(lb.root) == before and json.loads(path.read_text(encoding="utf-8")) == holder
    path.unlink()
    assert (
        site.write(
            serve.STAR_PATH, {"act": "star", "line": photo["id"], "day": WEDNESDAY}, LOOPBACK, None
        ).status
        == 303
    )


# -- every row main's Day has ----------------------------------------------------------------------------

THURSDAY = "2026-06-11"
BOAT_PLANS = utc(THURSDAY, "14:00")  # a transcript, tier 2: the call
HEAD = "ab" * 32  # a head the dream read at: any 64 hex characters


def _dream_entry(lb: Logbook, max_tier: int) -> None:
    """The `dream` entry of the crossing policy as the owner edits it; the head does not move."""
    policy.policy_path(lb.root).write_text(
        json.dumps(
            {"mcp": {"max_tier": 1}, policy.DREAM_DESTINATION: {"max_tier": max_tier, "until": "2026-12-31"}}
        ),
        encoding="utf-8",
    )


def _every_row(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> dict[str, Line]:
    """Thursday with every row kind main's Day has beside the persona's own: the dream's draft of the
    day proposing two events, the first confirmed by the owner (`day sign --accept 1`); a synthesis
    of the call; the owner's goal, the goal reworded, a review of it and a chapter (RFC 0036)."""
    _dream_entry(lb, 2)
    call = _at(lb.root, "transcript", BOAT_PLANS)
    proposal = {"kind": "event", "place": None, "people": [], "evidence": [call["id"]]}
    draft = lb.append(
        at=utc(THURSDAY, "21:00"),
        source="model:test-model",
        kind="draft",
        tier=2,
        payload={
            "schema": "draft/v1",
            "unit": "day",
            "subject": THURSDAY,
            "read_head": HEAD,
            "read_count": 5,
            "language": "en",
            "segments": [{"text": "A day of boat plans.", "evidence": [call["id"]]}],
            "proposals": [
                {
                    **proposal,
                    "title": "Boat plans",
                    "start": utc(THURSDAY, "14:00"),
                    "end": utc(THURSDAY, "15:00"),
                },
                {
                    **proposal,
                    "title": "Rigging check",
                    "start": utc(THURSDAY, "16:00"),
                    "end": utc(THURSDAY, "17:00"),
                },
            ],
        },
    )
    synthesis = lb.append(
        at=utc(THURSDAY, "21:05"),
        source="model:test-model",
        kind="draft",
        tier=2,
        payload={
            "schema": "draft/v1",
            "unit": "event",
            "subject": [call["id"]],
            "read_head": HEAD,
            "read_count": 1,
            "language": "en",
            "segments": [{"text": "Check the rigging before Saturday.", "evidence": [call["id"]]}],
            "extra": {"segments": [{"part": "actions", "utterances": [{"n": 1}]}]},
        },
    )
    owner = {"source": "manual", "tier": 2}
    goal = lb.append(
        at=utc(THURSDAY, "18:00"),
        kind="goal",
        payload={
            "schema": "goal/v1",
            "text": "Sail to the islands and back.",
            "horizon": "year",
            "from": THURSDAY,
        },
        **owner,
    )
    reworded = lb.append(
        at=utc(THURSDAY, "18:10"),
        kind="goal",
        payload={
            "schema": "goal/v1",
            "text": "Sail to the islands, at anchor.",
            "horizon": "year",
            "from": THURSDAY,
            "supersedes": goal["id"],
        },
        **owner,
    )
    review = lb.append(
        at=utc(THURSDAY, "18:20"),
        kind="review",
        payload={
            "schema": "review/v1",
            "goal": reworded["id"],
            "disposition": "advancing",
            "period": "month",
        },
        **owner,
    )
    chapter = lb.append(
        at=utc(THURSDAY, "18:30"),
        kind="chapter",
        payload={"schema": "chapter/v1", "name": "Aboard", "from": THURSDAY, "rules": ""},
        **owner,
    )
    seq = Logbook(lb.root).meta["seq"]
    cli.main(["day", "sign", THURSDAY, "--accept", "1", "--at", "2026-06-11T23:30:00+02:00"])
    capsys.readouterr()
    event = Logbook(lb.root).line_by_seq(seq + 1)
    assert event is not None and event["kind"] == "event" and event["payload"]["extra"]["from"] == draft["id"]
    return {
        "call": call,
        "draft": draft,
        "synthesis": synthesis,
        "goal": goal,
        "reworded": reworded,
        "review": review,
        "chapter": chapter,
        "event": event,
    }


def _forms(text: str) -> list[str]:
    """The line each star form on the page names."""
    return re.findall(r'<form class="star"[^>]*>(?:(?!</form>).)*?name="line" value="([^"]+)"', text, re.S)


def test_the_day_carries_a_star_on_every_row_main_added_that_is_the_owner_s_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _every_row(lb, capsys)
    text = _page(serve.Site(Logbook(lb.root)), THURSDAY)
    named = _forms(text)
    for kind in ("call", "event", "reworded", "review", "chapter"):
        assert rows[kind]["id"] in named, f"the {kind}'s row carries a star"
    assert rows["draft"]["id"] not in named and rows["synthesis"]["id"] not in named
    assert rows["goal"]["id"] not in named, "a superseded goal takes no star: star the one that stands"

    draft = text[text.index('<div class="draft">') :].split("</div>")[0]
    confirmed = re.search(r'<li class="proposal confirmed".*?</li>', draft, re.S)
    proposed = re.search(r'<li class="proposal proposed mute".*?</li>', draft, re.S)
    assert confirmed is not None and _forms(confirmed.group(0)) == [rows["event"]["id"]]
    assert proposed is not None and "Rigging check" in proposed.group(0) and "<form" not in proposed.group(0)
    assert "<form" not in draft.split('<ul class="proposals">')[0], "a draft's sentences take no star"

    synthesis = re.search(r'<details class="synthesis".*?</details>', text, re.S)
    assert synthesis is not None and "Check the rigging" in synthesis.group(0)
    assert "<form" not in synthesis.group(0), "a synthesis is a model's draft, never starred"
    owner = text[text.index("<h2>Reviews</h2>") :].split("<h2>Timeline</h2>")[0]
    assert sorted(_forms(owner)) == sorted(
        [rows["reworded"]["id"], rows["review"]["id"], rows["chapter"]["id"]]
    )


def test_a_row_the_policy_withholds_carries_no_star(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    rows = _every_row(lb, capsys)
    _dream_entry(lb, 1)  # the draft and the synthesis, tier 2, are above the entry now
    text = _page(serve.Site(Logbook(lb.root)), THURSDAY)
    assert "superseded by policy" in text and "Check the rigging" not in text and "Rigging check" not in text
    named = _forms(text)
    assert rows["draft"]["id"] not in named and rows["synthesis"]["id"] not in named
    for withheld in re.findall(r'<p class="(?:synthesis )?mute" title="line [^"]+">.*?</p>', text, re.S):
        assert "<form" not in withheld
    assert rows["call"]["id"] in named and rows["event"]["id"] in named, "the owner's lines keep theirs"


def test_a_star_on_a_draft_a_synthesis_or_a_withheld_row_is_refused_and_writes_nothing(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = _every_row(lb, capsys)
    site = serve.Site(Logbook(lb.root))
    before = _files(lb.root)
    for policy_tier in (2, 1):  # shown, then withheld by the policy
        _dream_entry(lb, policy_tier)
        before = _files(lb.root)
        for kind in ("draft", "synthesis"):
            line = rows[kind]["id"]
            response = site.write(
                serve.STAR_PATH, {"act": "star", "line": line, "day": THURSDAY}, LOOPBACK, None
            )
            said = html.unescape(response.body.decode("utf-8"))
            assert response.status == 400 and "a model's draft" in said, (kind, policy_tier, said)
            with pytest.raises(SystemExit) as stop:
                cli.main(["star", line])
            assert stop.value.code == 2 and "a model's draft" in capsys.readouterr().err
        assert _files(lb.root) == before


def test_the_text_day_marks_a_starred_goal(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    rows = _every_row(lb, capsys)
    cli.main(["star", rows["reworded"]["id"]])
    capsys.readouterr()
    cli.main(["day", THURSDAY, "--no-anniversaries"])
    out = capsys.readouterr().out
    goals = [row for row in out.splitlines() if row.startswith("  goal ")]
    assert [row.split(None, 1)[1].startswith("★ ") for row in goals] == [False, True], goals
    assert "Sail to the islands, at anchor." in goals[1] and "superseded" in goals[0]


# -- a star never shows what a reader hides ------------------------------------------------------------------


def test_a_star_above_the_reader_s_gate_is_not_shown(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """A star is at its line's tier, so a reader through a gate sees neither: `day --json` through
    tiers 1, the static site (`export site`), the Days page. And a star whose own tier says less
    than its line's (one no writer here makes) is shown only beside a line the reader shows."""
    from logbook.core import day as day_reader

    plans = _at(lb.root, "transcript", BOAT_PLANS)
    cli.main(["star", plans["id"], "--note", "the boat plans"])
    capsys.readouterr()
    lb = Logbook(lb.root)
    [star] = _of(lb.root, "star")
    assert star["tier"] == plans["tier"] == 2
    assert [s["line"] for s in day_reader.read(lb, THURSDAY)["stars"]] == [plans["id"]]
    assert "stars" not in day_reader.read(lb, THURSDAY, tiers=(1,))
    static = serve.Site(lb, href=lambda path: None, tiers=(1,))
    assert "★" not in static.page_day(THURSDAY) and "the boat plans" not in static.page_day(THURSDAY)
    days = serve.Site(lb, tiers=(1,)).respond("/days", f"from={WEDNESDAY}&to={FRIDAY}").body.decode("utf-8")
    assert "Starred" not in days and "the boat plans" not in days

    lb.append(  # a star that lies about its tier: tier 1 on the tier-2 recording
        at=plans["at"],
        source="manual",
        kind="star",
        tier=1,
        payload={"schema": "star/v1", "line": plans["id"], "kind": "transcript", "note": "a tier that lies"},
    )
    lb = Logbook(lb.root)
    assert "stars" not in day_reader.read(lb, THURSDAY, tiers=(1,))
    assert "a tier that lies" not in serve.Site(lb, href=lambda path: None, tiers=(1,)).page_day(THURSDAY)
    days = serve.Site(lb, tiers=(1,)).respond("/days", f"from={WEDNESDAY}&to={FRIDAY}").body.decode("utf-8")
    assert "a tier that lies" not in days and "Boat plans" not in days


def test_a_moved_head_is_a_409_on_the_star_and_the_with_field(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another writer appended between the read and the append (`HeadMoved`): 409, nothing written."""
    from logbook.core import presence, stars
    from logbook.core.store import HeadMoved

    def moved(*_args: Any, **_kwargs: Any) -> Any:
        raise HeadMoved("the record's head moved from seq 1 to seq 2 while it was read; nothing was written")

    monkeypatch.setattr(stars, "star", moved)
    monkeypatch.setattr(presence, "state", moved)
    site = serve.Site(lb)
    lunch = _at(lb.root, "event", LUNCH)
    before = _files(lb.root)
    for to, form in (
        (serve.STAR_PATH, {"act": "star", "line": lunch["id"], "day": WEDNESDAY}),
        (serve.WITH_PATH, {"day": FRIDAY, "names": "Ola", "at": "12:00"}),
    ):
        response = site.write(to, form, LOOPBACK, None)
        assert response.status == 409 and "head moved" in response.body.decode("utf-8"), to
    assert _files(lb.root) == before
