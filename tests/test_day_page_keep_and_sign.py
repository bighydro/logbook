"""Keep and sign on the Day page (RFC 0043 §5, slice C, part 2): one form at the foot of the evening and
signed-again shapes, one POST to `/day/YYYY-MM-DD/sign`, one hold of the writer lock, in §5's order:
the pencil's kept sentences and links (boxes numbered as `--keep` takes them), a kept decision's revisit
day, the day in a word, each of today's tasks answered (done, tomorrow, let go), the delegations, then
the signature through `reflect.close`. Every click writes what `logbook day sign DAY --keep …` and
`logbook day reflect DAY --sign --keep …` write, byte for byte; any refusal writes nothing and says why
in one sentence. The evening's pencil: a *Dream the day so far* button only with a `dream` entry, and
the draft it writes in pencil above the form. The write gate is the Library's: this machine, or the
owner's named phone.

Synthetic throughout: Ines Nordmann of Oslo, who does not exist, and her boat-share log
(`test_keep_and_sign.py`'s record); Ola Nordmann, to whom a delegation goes; the model is an
in-process fake (`model_client.send` replaced) and no test opens a connection."""

from __future__ import annotations

import html
import http.client
import itertools
import json
import re
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
import test_dream_learns as dreams
import test_keep_and_sign as keeping
import test_no_count_beside_a_name as beside
import test_serve_phone as phones
from persona import utc
from test_keep_and_sign import (
    BILGE,
    DAY,
    DECIDED,
    EVENT,
    IDEA,
    KEEP_DECIDED,
    KEEP_IDEA,
    KEEP_LEARNED,
    KEEP_PHOTO,
    KEEP_UNSUPPORTED,
    LATER,
    LEARNED,
    LINK,
    PHOTO_TEXT,
    ROPE,
)

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import dream, entity_review, keep, phone, serve
from logbook.core import drafts, notes, policy, signing, stars, store
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
REFLECTION = "A good day for the crew list. Ola should book the ferry for Sunday."
TO_OLA = 1  # the reflection's one proposal: a delegation to Ola
AFTER = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)  # the next morning: DAY is past and unsigned, so evening
EVENING = datetime(2026, 10, 20, 19, 30, tzinfo=UTC)  # 21:30 in Oslo, on DAY: today, after the evening hour
REVISIT = "2026-11-20"

lb = keeping.lb


@pytest.fixture
def closing(lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Logbook:
    """DAY with the owner's reflection on it, written by the command: the page's Sign signs with it."""
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    cli.main(["day", "reflect", DAY, "--text", REFLECTION])
    capsys.readouterr()
    return Logbook(lb.root)


def _site(lb: Logbook, now: datetime = AFTER, **kwargs: Any) -> serve.Site:
    return serve.Site(Logbook(lb.root), now=lambda: now, **kwargs)


def _page(site: serve.Site, query: str = "") -> str:
    response = site.respond(f"/day/{DAY}", query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _form(page: str, cls: str) -> str:
    found = re.search(rf'<form class="{cls}"[^>]*>.*?</form>', page, re.S)
    assert found is not None, f"no form.{cls} on the page"
    return found.group(0)


def _hidden(form: str) -> dict[str, str]:
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)
    }


def _signing(site: serve.Site) -> dict[str, str]:
    """The hidden fields of the page's Sign form: what the browser posts beside the controls."""
    return _hidden(_form(_page(site), "sign"))


def _post(site: serve.Site, form: dict[str, str], to: str = "sign", **kwargs: Any) -> serve.Response:
    client = kwargs.pop("client", LOOPBACK)
    origin = kwargs.pop("origin", None)
    return site.write(f"/day/{DAY}/{to}", form, client, origin, **kwargs)


def _text(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _said(response: serve.Response) -> str:
    """The one sentence of a refusal, as the page says it."""
    found = re.search(r"<h1>\d{3}</h1>\n<p>(.*?)</p>", response.body.decode("utf-8"), re.S)
    return "" if found is None else _text(found.group(1))


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


def _record(root: Path) -> dict[str, bytes]:
    """The record's lines, month by month, and its meta: what two writers must agree on byte for byte."""
    found = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "logbook").rglob("*.jsonl")}
    found["logbook.json"] = (root / "logbook.json").read_bytes()
    return found


def _counting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every new line's id and every clock fixed and in order, so the lines two writers append to two
    copies of one record compare byte for byte."""
    counter = itertools.count(1)
    monkeypatch.setattr(store, "uuid7", lambda: f"019ca000-0000-7000-8000-{next(counter):012d}")
    monkeypatch.setattr(entity_review, "uuid7", lambda: f"019ca000-0000-7000-8000-{next(counter):012d}")
    for module in (store, signing, notes, stars, entity_review):
        monkeypatch.setattr(module, "now_utc", lambda: "2026-10-20T19:45:00Z")


def _twin(lb: Logbook, tmp_path: Path, name: str) -> Path:
    return Path(shutil.copytree(lb.root, tmp_path / name))


def _cli(monkeypatch: pytest.MonkeyPatch, root: Path, *args: str) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    code, out, err = keeping._cli(*args)
    assert code == 0, (args, out, err)


def _labels(line: dict[str, Any]) -> list[str]:
    return list((line.get("payload") or {}).get("labels") or [])


def _after(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if int(line["seq"]) > seq]


# -- the form ----------------------------------------------------------------------------------------------


def test_the_evening_form_offers_the_acts_in_the_order_they_are_written(closing: Logbook) -> None:
    page = _page(_site(closing))
    assert "Close the day" in page, "the evening shape"
    sign = _form(page, "sign")
    boxes = re.findall(r'<input type="checkbox" name="keep" value="(\d+)">', sign)
    assert sorted(int(n) for n in boxes) == [LINK, KEEP_LEARNED, KEEP_DECIDED, KEEP_IDEA, KEEP_PHOTO]
    assert str(EVENT) not in boxes and str(KEEP_UNSUPPORTED) not in boxes, "an event is accepted, not kept"
    assert f'name="revisit-{KEEP_DECIDED}"' in sign and 'type="date"' in sign
    assert re.search(rf'name="revisit-{KEEP_DECIDED}"[^>]* min="2026-10-21"', sign), "a later day"
    assert sign.count('type="date"') == 1, "a revisit day goes with a decision alone"
    assert '<input type="text" name="word"' in sign
    for task in (ROPE, BILGE):  # each task's field carries its id, never the number `--done` takes
        values = re.findall(rf'<input type="radio" name="task-{task}" value="([a-z-]+)"( checked)?>', sign)
        assert [v for v, _ in values] == ["done", "tomorrow", "let-go"], task
        assert not any(checked for _, checked in values), "none chosen means no line"
    assert "Buy rope" in sign and "Fix the bilge pump" in sign
    assert not re.search(r"\btask \d|\(task", _text(sign)), "no task number on the page"
    assert re.search(rf'<input type="checkbox" name="accept" value="{TO_OLA}">', sign)
    order = [
        sign.index('name="keep"'),
        sign.index(f'name="revisit-{KEEP_DECIDED}"'),
        sign.index('name="word"'),
        sign.index(f'name="task-{ROPE}"'),
        sign.index('name="accept"'),
        sign.index('<button name="act" value="sign">'),
    ]
    assert order == sorted(order), "§5's order: kept, revisit, word, tasks, delegations, the signature"
    for words in (LEARNED, DECIDED, IDEA, PHOTO_TEXT):
        assert html.escape(words, quote=False) in sign
    text = _text(sign)
    assert f"{KEEP_DECIDED} {DECIDED}" not in text, "no number beside the name the sentence opens with"
    assert "--keep" in text and "--word" in text and "--done" in text, "the command beside the form"
    hidden = _hidden(sign)
    assert hidden["draft"] == next(x["id"] for x in closing.lines() if x["kind"] == drafts.KIND)
    assert hidden["tasks"]


def test_the_pencil_is_offered_in_pencil_and_what_was_kept_in_ink(closing: Logbook) -> None:
    site = _site(closing)
    fields = {**_signing(site), "keep": f"{KEEP_LEARNED}", "word": "calm", "act": "sign"}
    assert _post(site, fields).status == 303
    page = _page(site, "shape=evening")
    sign = _form(page, "sign")
    assert re.search(r'<li class="pencil">', sign), "a sentence not kept is the model's, in pencil"
    learned = next(x for x in closing.lines() if "learned" in _labels(x))
    kept = re.search(rf'<li class="kept">.*?{re.escape(LEARNED)}.*?</li>', sign, re.S)
    assert kept is not None and f"kept as #{learned['seq']}" in kept.group(0)
    assert f'value="{KEEP_LEARNED}"' not in sign, "a kept sentence is not offered again"
    assert '<input type="text" name="word"' not in sign and "“calm”" in sign, "a word is kept once"


def test_a_morning_or_live_page_carries_no_keep(closing: Logbook) -> None:
    for shape in ("morning", "live"):
        page = _page(_site(closing), f"shape={shape}")
        assert 'name="keep"' not in page and f'name="task-{ROPE}"' not in page, shape


# -- parity: every click writes the command's lines --------------------------------------------------------

CASES = {
    "learned": ({"keep": str(KEEP_LEARNED)}, ["--keep", str(KEEP_LEARNED)]),
    "decision": (
        {"keep": str(KEEP_DECIDED), f"revisit-{KEEP_DECIDED}": REVISIT},
        ["--keep", str(KEEP_DECIDED), "--revisit", f"{KEEP_DECIDED}={REVISIT}"],
    ),
    "idea": ({"keep": str(KEEP_IDEA)}, ["--keep", str(KEEP_IDEA)]),
    "link": ({"keep": str(LINK)}, ["--keep", str(LINK)]),
    "photo": ({"keep": str(KEEP_PHOTO)}, ["--keep", str(KEEP_PHOTO)]),
    "word": ({"word": "calm"}, ["--word", "calm"]),
    "done": ({f"task-{ROPE}": "done"}, ["--done", "1"]),
    "tomorrow": ({f"task-{BILGE}": "tomorrow"}, ["--tomorrow", "2"]),
    "let go": ({f"task-{ROPE}": "let-go"}, ["--let-go", "1"]),
    "everything": (
        {
            "keep": f"{LINK},{KEEP_LEARNED},{KEEP_DECIDED},{KEEP_IDEA},{KEEP_PHOTO}",
            f"revisit-{KEEP_DECIDED}": REVISIT,
            "word": "calm",
            f"task-{ROPE}": "done",
            f"task-{BILGE}": "let-go",
        },
        [
            "--keep",
            f"{LINK},{KEEP_LEARNED},{KEEP_DECIDED},{KEEP_IDEA},{KEEP_PHOTO}",
            "--revisit",
            f"{KEEP_DECIDED}={REVISIT}",
            "--word",
            "calm",
            "--done",
            "1",
            "--let-go",
            "2",
        ],
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_page_writes_what_day_sign_keep_writes_byte_for_byte(
    closing: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    fields, flags = CASES[case]
    twin = _twin(closing, tmp_path, "twin")
    seq = _seq(closing)
    _counting(monkeypatch)
    _cli(monkeypatch, twin, "day", "sign", DAY, *flags)
    monkeypatch.setenv("LOGBOOK_HOME", str(closing.root))
    _counting(monkeypatch)
    site = _site(closing)
    response = _post(site, {**_signing(site), **fields, "act": "sign"})
    assert response.status == 303, response.body[:400]
    assert response.location == f"/day/{DAY}#close"
    assert _record(closing.root) == _record(twin), "the command's lines, byte for byte"
    written = _after(closing, seq)
    assert written[-1]["kind"] == signing.KIND and len(written) >= 2


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_page_writes_what_day_reflect_sign_keep_writes_with_the_delegations(
    closing: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    fields, flags = CASES[case]
    twin = _twin(closing, tmp_path, "twin")
    _counting(monkeypatch)
    _cli(monkeypatch, twin, "day", "reflect", DAY, "--sign", "--accept", str(TO_OLA), *flags)
    monkeypatch.setenv("LOGBOOK_HOME", str(closing.root))
    _counting(monkeypatch)
    site = _site(closing)
    assert _post(site, {**_signing(site), **fields, "accept": str(TO_OLA), "act": "sign"}).status == 303
    assert _record(closing.root) == _record(twin), "delegation, kept lines and signature: the command's"
    labels = [_labels(x) for x in Logbook(closing.root).lines()]
    assert ["delegation"] in labels


def test_the_lines_come_in_the_order_of_section_5_under_one_hold(
    closing: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    holds: list[int] = []
    real = Logbook.writer

    def counted(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        holds.append(store._held.get(self._lock_path(), 0))
        return real(self, *args, **kwargs)

    site = _site(closing)
    fields = {**_signing(site), **CASES["everything"][0], "accept": str(TO_OLA), "act": "sign"}
    seq = _seq(closing)
    monkeypatch.setattr(Logbook, "writer", counted)
    assert _post(site, fields).status == 303
    assert no_network == []
    kinds = [(x["kind"], _labels(x)) for x in _after(closing, seq)]
    assert kinds == [
        ("note", ["learned"]),
        ("note", ["decision"]),
        ("note", ["idea"]),
        ("entity", []),
        ("keeper", []),
        ("note", ["word"]),
        ("note", ["task"]),
        ("note", ["task"]),
        ("note", ["delegation"]),
        ("signed-day", []),
    ]
    assert holds and holds[0] == 0 and all(h >= 1 for h in holds[1:]), "one hold, re-entered"
    *kept, signature = _after(closing, seq)
    draft = next(x for x in closing.lines() if x["kind"] == drafts.KIND)
    confirmed = set(signature["payload"]["confirmed"])
    assert {x["id"] for x in kept} <= confirmed and draft["id"] not in confirmed


def test_signing_again_offers_what_is_not_kept_yet_and_keeps_the_rest(
    closing: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = _site(closing)
    first = {**_signing(site), "keep": str(KEEP_LEARNED), f"task-{ROPE}": "done", "act": "sign"}
    assert _post(site, first).status == 303
    page = _page(site)
    assert "Sign again" in _form(page, "sign")
    sign = _form(page, "sign")
    assert f'value="{KEEP_LEARNED}"' not in sign and f'value="{KEEP_DECIDED}"' in sign
    assert f'name="task-{ROPE}"' not in sign and f'name="task-{BILGE}"' in sign and "done today" in sign
    twin = _twin(closing, tmp_path, "twin")
    _counting(monkeypatch)
    _cli(monkeypatch, twin, "day", "sign", DAY, "--keep", str(KEEP_DECIDED), "--tomorrow", "2")
    monkeypatch.setenv("LOGBOOK_HOME", str(closing.root))
    _counting(monkeypatch)
    again = {**_signing(site), "keep": str(KEEP_DECIDED), f"task-{BILGE}": "tomorrow", "act": "sign"}
    assert _post(site, again).status == 303
    assert _record(closing.root) == _record(twin), "the command's re-signature, byte for byte"
    signature = [x for x in Logbook(closing.root).lines() if x["kind"] == signing.KIND][-1]
    learned = next(x for x in closing.lines() if "learned" in _labels(x))
    assert signature["payload"]["supersedes"] and learned["id"] in signature["payload"]["confirmed"]


# -- refused, and nothing written ----------------------------------------------------------------------------

REFUSALS = [
    ({"keep": "99"}, "no keepable sentence or link 99"),
    ({"keep": str(EVENT)}, "is an event"),
    ({"keep": str(KEEP_UNSUPPORTED)}, "rests on no line"),
    ({"keep": "x"}, "takes numbers"),
    ({f"revisit-{KEEP_DECIDED}": REVISIT}, "not kept"),
    ({"keep": str(KEEP_DECIDED), f"revisit-{KEEP_DECIDED}": DAY}, "comes after"),
    ({"keep": str(KEEP_DECIDED), f"revisit-{KEEP_DECIDED}": "20 Nov"}, "YYYY-MM-DD"),
    ({"keep": str(KEEP_LEARNED), f"revisit-{KEEP_LEARNED}": REVISIT}, "not a decision"),
    ({"keep": str(KEEP_LEARNED), "word": "two words"}, "one word"),
    ({"keep": str(KEEP_LEARNED), "word": "42"}, "not a number"),
    ({"keep": str(KEEP_LEARNED), f"task-{ROPE}": "done,let-go"}, "done, tomorrow or let go"),
    ({"keep": str(KEEP_LEARNED), f"task-{ROPE}": "someday"}, "done, tomorrow or let go"),
    ({"keep": str(KEEP_LEARNED), f"task-{LATER}": "done"}, "not among the tasks of"),
]


@pytest.mark.parametrize(("fields", "said"), REFUSALS)
def test_any_refusal_writes_nothing_and_the_page_says_why_in_one_sentence(
    closing: Logbook, fields: dict[str, str], said: str
) -> None:
    site = _site(closing)
    seq = _seq(closing)
    response = _post(site, {**_signing(site), **fields, "accept": str(TO_OLA), "act": "sign"})
    assert response.status == 400, (response.status, response.body[:400])
    body = response.body.decode("utf-8")
    found = re.search(r"<h1>400</h1>\n<p>(.*?)</p>", body, re.S)
    assert found is not None, body[:600]
    sentence = _text(found.group(1))
    assert said in sentence and sentence.count(". ") == 0 and "\n" not in sentence
    assert _seq(closing) == seq, "nothing written: not the delegation, not a kept line"


def test_a_refusal_of_the_last_item_leaves_the_first_unwritten(closing: Logbook) -> None:
    browse = next(x for x in closing.lines() if x["kind"] == "browse")
    closing.retract(int(browse["seq"]), "not mine")
    site = _site(closing)
    seq = _seq(closing)
    response = _post(
        site, {**_signing(site), "keep": f"{KEEP_LEARNED},{LINK}", "word": "calm", "act": "sign"}
    )
    assert response.status == 400 and f"link {LINK}" in response.body.decode("utf-8")
    assert _seq(closing) == seq


def test_a_pencil_or_a_plan_older_than_the_record_is_refused(closing: Logbook) -> None:
    site = _site(closing)
    fields = _signing(site)
    seq = _seq(closing)
    stale = _post(site, {**fields, "keep": str(KEEP_LEARNED), "draft": "019ca000-dead", "act": "sign"})
    assert stale.status == 409 and "since this page was read" in stale.body.decode("utf-8")
    moved = _post(site, {**fields, f"task-{ROPE}": "done", "tasks": "0" * 16, "act": "sign"})
    assert moved.status == 409 and "since this page was read" in moved.body.decode("utf-8")
    assert _seq(closing) == seq
    assert _post(site, {**fields, "word": "calm", "draft": "", "tasks": "", "act": "sign"}).status == 303, (
        "a form that keeps nothing from the pencil or the plan is not held to them"
    )


def test_a_moved_head_is_head_moved_and_the_close_writes_nothing(
    closing: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = _site(closing)
    fields = {
        **_signing(site),
        "keep": str(KEEP_LEARNED),
        "word": "calm",
        "accept": str(TO_OLA),
        "act": "sign",
    }
    real = keep.prepared

    def intruded(lb: Logbook, day: str, a: keep.Asked, tiers: Any = None) -> list[keep.Item]:
        found = real(lb, day, a, tiers)
        Logbook(lb.root).append(
            f"{DAY}T18:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Late."}
        )
        return found

    monkeypatch.setattr(keep, "prepared", intruded)
    seq = _seq(closing)
    response = _post(site, fields)
    assert response.status == 409, response.body[:400]
    after = _after(closing, seq)
    assert [x["payload"].get("text") for x in after] == ["Late."], "only the other writer's line"


# -- the write gate ------------------------------------------------------------------------------------------


def test_only_this_machine_and_the_owners_named_phone_may_post(closing: Logbook) -> None:
    site = _site(closing)
    fields = {
        **_signing(site),
        "keep": str(KEEP_LEARNED),
        "word": "calm",
        f"task-{ROPE}": "done",
        "act": "sign",
    }
    seq = _seq(closing)
    for client in ("192.0.2.7", "203.0.113.9", "::ffff:203.0.113.9"):
        refused = _post(site, fields, client=client)
        assert refused.status == 403 and "this machine" in refused.body.decode("utf-8"), client
    assert _post(site, fields, origin="http://example.org").status == 403
    # the phone, through Tailscale Serve, before `logbook setup phone` names it: refused
    unnamed = _post(site, fields, origin=phones.ORIGIN, asked=phones._asked())
    assert unnamed.status == 403 and phone.FROM_PHONE in html.unescape(unnamed.body.decode("utf-8"))
    Logbook(closing.root).set_meta(**{phone.KEY: phones.SETTING})
    site = _site(closing)
    other = _post(site, fields, origin=phones.ORIGIN, asked=phones._asked(login="per@example.org"))
    assert other.status == 403, "a login the setting does not name"
    framed = _post(site, fields, origin=phones.ORIGIN, asked=phones._asked(dest="iframe"))
    assert framed.status == 403, "a form posted from inside a frame"
    assert _seq(closing) == seq, "nothing written"
    named = _post(site, fields, origin=phones.ORIGIN, asked=phones._asked())
    assert named.status == 303, named.body[:400]
    kinds = [(x["kind"], _labels(x)) for x in _after(closing, seq)]
    assert kinds == [("note", ["learned"]), ("note", ["word"]), ("note", ["task"]), ("signed-day", [])]


# -- the evening's pencil -----------------------------------------------------------------------------------


@pytest.fixture
def evening(closing: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """DAY is today, after the evening hour; the model an in-process fake."""
    monkeypatch.setenv("LOGBOOK_NOTIFY_EVENING_HOUR", "18")
    monkeypatch.setattr(dream, "now_utc", lambda: "2026-10-20T19:30:00Z")
    for name, value in dreams.ENV.items():
        monkeypatch.setenv(name, value)
    return closing


def _no_dream_entry(lb: Logbook) -> None:
    path = policy.policy_path(lb.root)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data[policy.DREAM_DESTINATION]
    path.write_text(json.dumps(data), encoding="utf-8")


def test_dream_the_day_so_far_writes_the_evening_draft_in_pencil_above_the_form(
    evening: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    def answer(material: dict[str, Any]) -> dict[str, Any]:
        learned = [{"text": "Saturday needs a full crew.", "evidence": dreams._refs(material)[1][:1]}]
        return dreams._answer(material, learned=learned)

    seen = dreams._fake(monkeypatch, answer)
    site = _site(evening, EVENING)
    page = _page(site)
    assert "Close the day" in page
    button = _form(page, "dream")
    assert f'action="/day/{DAY}/reflect"' in button and "Dream the day so far" in button
    seq = _seq(evening)
    response = _post(site, {"act": "dream"}, to="reflect")
    assert response.status == 303, _said(response)
    assert response.location == f"/day/{DAY}#pencil"
    assert no_network == [] and len(seen["calls"]) == 1
    (draft,) = _after(evening, seq)
    assert draft["kind"] == drafts.KIND and draft["payload"]["extra"]["evening"] is True
    page = _page(site)
    pencil = page.index("Saturday needs a full crew.")
    assert pencil < page.index('<form class="sign"'), "the pencil above the form"
    assert page.rfind('<div class="paper"', 0, pencil) != -1, "in pencil"
    sign = _form(page, "sign")
    assert "Saturday needs a full crew." in sign and _hidden(sign)["draft"] == draft["id"]


def test_without_a_dream_entry_there_is_no_button_and_nothing_is_sent(
    evening: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = dreams._fake(monkeypatch)
    _no_dream_entry(evening)
    site = _site(evening, EVENING)
    page = _page(site)
    assert '<form class="dream"' not in page
    close = page.split('id="close"')[1]
    found = re.search(r'<p class="mute dream">(.*?)</p>', close, re.S)
    assert found is not None
    said = _text(found.group(1))
    assert "policy/crossing.json" in said and '"dream"' in said and said.count(". ") == 0
    seq = _seq(evening)
    refused = _post(site, {"act": "dream"}, to="reflect")
    assert refused.status == 400 and "dream" in refused.body.decode("utf-8")
    assert seen["calls"] == [] and _seq(evening) == seq


def test_the_button_is_for_today_alone_and_from_this_machine_alone(
    evening: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = dreams._fake(monkeypatch)
    assert '<form class="dream"' not in _page(_site(evening, AFTER)), "a past day is dreamed whole by the CLI"
    site = _site(evening, EVENING)
    seq = _seq(evening)
    assert _post(site, {"act": "dream"}, to="reflect", client="192.0.2.7").status == 403
    assert (
        _post(site, {"act": "dream"}, to="reflect", origin=phones.ORIGIN, asked=phones._asked()).status == 403
    )
    assert seen["calls"] == [] and _seq(evening) == seq
    assert _post(_site(evening, AFTER), {"act": "dream"}, to="reflect").status == 400, "not today"
    assert seen["calls"] == [] and _seq(evening) == seq


def test_a_page_whose_gate_is_below_the_dream_entry_offers_no_dream(
    evening: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entry lets the dream read up to tier 2; through a gate of tier 1 the page would never show
    the draft it writes, so it offers no button, says why in one sentence, and a post sends nothing."""
    seen = dreams._fake(monkeypatch)
    site = _site(evening, EVENING, tiers=(1,))
    page = _page(site)
    assert '<form class="dream"' not in page
    found = re.search(r'<p class="mute dream">(.*?)</p>', page.split('id="close"')[1], re.S)
    assert found is not None
    said = _text(found.group(1))
    assert "tier 2" in said and "tier 1" in said and said.count(". ") == 0, said
    seq = _seq(evening)
    refused = _post(site, {"act": "dream"}, to="reflect")
    assert refused.status == 400 and "tier 2" in _said(refused)
    assert seen["calls"] == [] and _seq(evening) == seq
    assert '<form class="dream"' in _page(_site(evening, EVENING, tiers=(1, 2))), "a gate that holds it"


# -- over the socket, and beside the page ------------------------------------------------------------------


def test_keep_and_sign_round_trips_over_the_socket(closing: Logbook) -> None:
    """The browser sends a box ticked twice as two `keep` fields and a task's choice as its radio: the
    server joins them as `--keep N,N` takes them. On `logbook serve` the tasks are read beside the page,
    so the form offers them once they are read."""
    server = serve.make_server(Logbook(closing.root), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    seq = _seq(closing)
    try:
        port = server.server_address[1]
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{LOOPBACK}:{port}"}
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=30)

        def page() -> str:
            connection.request("GET", f"/day/{DAY}")
            reply = connection.getresponse()
            return reply.read().decode("utf-8")

        first = page()
        server.site.settle(timeout=30)  # the tasks, read beside the page
        sign = _form(page() if f'name="task-{ROPE}"' not in first else first, "sign")
        assert f'name="task-{ROPE}"' in sign
        fields = [
            *_hidden(sign).items(),
            ("keep", str(KEEP_LEARNED)),
            ("keep", str(KEEP_DECIDED)),
            (f"revisit-{KEEP_DECIDED}", REVISIT),
            ("word", "calm"),
            (f"task-{BILGE}", "tomorrow"),
            ("act", "sign"),
        ]
        connection.request("POST", f"/day/{DAY}/sign", body=urlencode(fields), headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b""
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    kinds = [(x["kind"], _labels(x)) for x in _after(closing, seq)]
    assert kinds == [
        ("note", ["learned"]),
        ("note", ["decision"]),
        ("note", ["word"]),
        ("note", ["task"]),
        ("signed-day", []),
    ]
    decided, task = _after(closing, seq)[1], _after(closing, seq)[3]
    assert (
        decided["payload"]["extra"]["revisit"] == REVISIT
        and task["payload"]["extra"]["outcome"] == "tomorrow"
    )


def test_a_plan_read_before_the_close_never_stands_in_for_the_tasks(closing: Logbook) -> None:
    """Beside the page (`read_later`, as on `logbook serve`), the tasks read at an earlier head are
    not offered after a sign moved it: the form waits for its own reading, so a task answered since is
    never offered again."""
    site = _site(closing, read_later=True)
    _page(site)
    site.settle(timeout=30)
    fields = {**_signing(site), f"task-{ROPE}": "done", "act": "sign"}
    assert f'name="task-{ROPE}"' in _form(_page(site), "sign")
    assert _post(site, fields).status == 303
    sign = _form(_page(site), "sign")
    assert f'name="task-{ROPE}"' not in sign and "being read" in sign
    site.settle(timeout=30)
    sign = _form(_page(site), "sign")
    assert f'name="task-{ROPE}"' not in sign and "done today" in sign and f'name="task-{BILGE}"' in sign


# -- no number beside a name ---------------------------------------------------------------------------------

FERRY = "00000804-0000-4000-8000-000000000804"
NAMED = {  # a task whose title opens with a person's name, and one whose title ends with one
    "opens": "Ola Nordmann: ferry tickets",
    "ends": "Ferry tickets for Ola",
}


def _clean(text: str) -> None:
    found = beside.GUARD.search(text)
    assert found is None, f"a number beside a name: {found.group(0)!r} in {text!r}"


def _clean_page(page: str) -> None:
    """The close of the page, the reflection to the Sign button, its words and every attribute a
    reader hears (`aria-label`, `title`), held to the strong guard (#394)."""
    close = page.split('id="close"', 1)[1]
    markup = close[: close.index("</form>", close.index('<form class="sign"'))]
    _clean(_text(markup))
    for said in re.findall(r'(?:aria-label|title)="([^"]*)"', markup):
        _clean(html.unescape(said))


@pytest.mark.parametrize("where", sorted(NAMED))
def test_a_task_titled_with_a_name_shows_no_number_on_the_page(
    closing: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """No task number on the page: the title alone, in the form, the choices' name, the answered row
    and the refusal, each held to the strong guard (#394) over its text, titles and aria-labels. The
    form's field carries the task's id; `--done N` on the command line still takes its number, and the
    page's answer writes what it writes, byte for byte."""
    title = NAMED[where]
    closing.append_many(
        [keeping._task(utc(DAY, "07:10"), FERRY, title, {"Due": {"start": DAY, "end": None}})]
    )
    rows = keeping.plan.read(Logbook(closing.root), DAY).to_json()["tasks"]["rows"]
    number = [r["title"] for r in rows].index(title) + 1  # as `show plan` numbers it, the CLI's `--done N`
    assert number in (2, 3) and len(rows) == 3

    site = _site(closing)
    page = _page(site)
    _clean_page(page)
    sign = _form(page, "sign")
    assert not re.search(r"\btask \d|\(task", _text(sign)), "no task number on the page"
    assert f'aria-label="{html.escape(title)}"' in sign
    assert re.search(rf'<input type="radio" name="task-{FERRY}" value="done">', sign)
    assert not re.search(r'name="task-\d+"', sign), "the field carries the id, not the number"

    twin = _twin(closing, tmp_path, "twin")
    _counting(monkeypatch)
    _cli(monkeypatch, twin, "day", "sign", DAY, "--done", str(number))
    monkeypatch.setenv("LOGBOOK_HOME", str(closing.root))
    _counting(monkeypatch)
    site = _site(closing)
    assert _post(site, {**_signing(site), f"task-{FERRY}": "done", "act": "sign"}).status == 303
    assert _record(closing.root) == _record(twin), "the page's answer is `--done N`'s, byte for byte"

    page = _page(site)
    _clean_page(page)
    sign = _form(page, "sign")
    assert f'name="task-{FERRY}"' not in sign and html.escape(title, quote=False) in sign
    refused = _post(site, {**_signing(site), f"task-{FERRY}": "done", "act": "sign"})
    assert refused.status == 400
    said = _said(refused)
    _clean(said)
    assert said.startswith(f"\u201c{title}\u201d is answered on {DAY} already"), said
    assert not re.search(r"\btask \d|\(task", said), said


# -- the page's tier gate ----------------------------------------------------------------------------------


def _drafted(lb: Logbook) -> list[str]:
    """Every sentence and link the fixture's tier-2 draft of DAY holds."""
    draft = next(x for x in lb.lines() if x["kind"] == drafts.KIND)
    assert draft["tier"] == 2, "the draft read the day's tier-2 note and browse"
    return [str(s["text"]) for s in draft["payload"]["segments"]] + [
        str(p.get("text") or p.get("title")) for p in draft["payload"]["proposals"]
    ]


def test_a_page_at_tier_1_shows_and_keeps_nothing_of_a_tier_2_draft(closing: Logbook) -> None:
    """Through a gate of tier 1 the Keep form reads the draft as the rest of the Day does: a draft of
    tier 2 is not there, so none of its sentences is shown or offered, and a form that names one
    anyway (its number, the draft's id) writes nothing."""
    words = _drafted(closing)
    draft = next(x for x in closing.lines() if x["kind"] == drafts.KIND)
    site = _site(closing, tiers=(1,))
    page = _page(site)
    for said in words:
        assert html.escape(said, quote=False) not in page and said not in page, said
    sign = _form(page, "sign")
    assert 'name="keep"' not in sign and 'name="revisit-' not in sign
    assert _hidden(sign)["draft"] == ""
    seq = _seq(closing)
    for fields in (
        {"keep": str(KEEP_LEARNED)},
        {"keep": str(KEEP_LEARNED), "draft": str(draft["id"])},
        {"keep": str(KEEP_DECIDED), f"revisit-{KEEP_DECIDED}": REVISIT, "draft": str(draft["id"])},
        {"keep": str(LINK)},
    ):
        response = _post(site, {**_signing(site), **fields, "act": "sign"})
        assert response.status in (400, 409), (fields, response.status, response.body[:400])
        body = response.body.decode("utf-8")
        assert not any(html.escape(said, quote=False) in body for said in words), body[:600]
    assert _seq(closing) == seq, "nothing written"
    assert f'value="{KEEP_LEARNED}"' in _form(_page(_site(closing)), "sign"), "the whole record offers it"


def test_a_page_at_tier_1_keeps_from_the_tier_1_draft_a_tier_2_one_superseded(closing: Logbook) -> None:
    """A tier-1 draft that a tier-2 draft superseded is the standing draft through a gate of tier 1:
    the page offers its sentence, and keeping that number writes the tier-1 draft's words, never the
    tier-2 draft's sentence of the same number."""
    upper = next(x for x in closing.lines() if x["kind"] == drafts.KIND)
    photo = next(x for x in closing.lines() if x["kind"] == "photo")
    lower = closing.append(
        utc(DAY, "20:00"),
        keeping.MODEL,
        drafts.KIND,
        1,
        {
            **upper["payload"],
            "segments": [
                {"text": "You were out on the water.", "evidence": [photo["id"]]},
                {"text": "The light holds late in October.", "evidence": [photo["id"]]},
            ],
            "proposals": [],
            "extra": {"parts": ["story", "learned"]},
        },
    )
    again = closing.append(
        utc(DAY, "21:30"), keeping.MODEL, drafts.KIND, 2, {**upper["payload"], "supersedes": lower["id"]}
    )
    whole = _hidden(_form(_page(_site(closing)), "sign"))
    assert whole["draft"] == again["id"], "the whole record's pencil is the tier-2 draft"
    site = _site(closing, tiers=(1,))
    sign = _form(_page(site), "sign")
    assert _hidden(sign)["draft"] == lower["id"]
    assert "The light holds late in October." in sign
    for said in _drafted(closing):
        assert html.escape(said, quote=False) not in sign, said
    boxes = re.findall(r'<input type="checkbox" name="keep" value="(\d+)">', sign)
    assert boxes == ["1"]
    seq = _seq(closing)
    assert _post(site, {**_signing(site), "keep": "1", "act": "sign"}).status == 303
    kept = [x for x in _after(closing, seq) if x["kind"] == "note"]
    assert [x["payload"]["text"] for x in kept] == ["The light holds late in October."]
    assert kept[0]["payload"]["extra"]["from"] == lower["id"]


def test_a_page_at_tier_1_neither_shows_nor_quotes_a_tier_2_word(
    closing: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The day in a word is a note, tier 2: through a gate of tier 1 it is absent from the page, as
    every line above the gate is, and the refusal of a second word says the day has one without
    quoting it. The whole record's page shows it, and its refusal names it, as before."""
    _cli(monkeypatch, closing.root, "day", "sign", DAY, "--word", "stormy")
    word = next(x for x in Logbook(closing.root).lines() if "word" in _labels(x))
    assert word["tier"] == 2 and word["payload"]["text"] == "stormy"
    site = _site(closing, tiers=(1,))
    page = _page(site)
    assert "stormy" not in page
    assert '<input type="text" name="word"' in _form(page, "sign"), "absent, as if there were none"
    seq = _seq(closing)
    refused = _post(site, {**_signing(site), "word": "calm", "act": "sign"})
    assert refused.status == 400, refused.body[:400]
    said = _said(refused)
    assert "has its word already" in said and "stormy" not in refused.body.decode("utf-8"), said
    assert _seq(closing) == seq, "nothing written"
    whole = _site(closing)
    assert "stormy" in _form(_page(whole), "sign")
    named = _post(whole, {**_signing(whole), "word": "calm", "act": "sign"})
    assert named.status == 400 and "stormy" in _said(named)
