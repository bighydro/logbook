"""The whole Library walked, two ways. Every act `logbook serve` answers, under another command's
writer lock: one answer for all of them, the owner's of 14 October 2026 (a 409, one sentence, the
form's input kept to send again) and nothing written. Every page it serves, from `/` through every
link on every page, read as a phone 400 px wide reads it (`phone_width.py`, no browser). On the four
synthetic years (`library_record.py`), the Oslo persona's fortnight (`persona.py`), the orgs
record (`orgs_record.py`) and the ideas record (`ideas_record.py`); nobody and nothing here exists."""

from __future__ import annotations

import html
import inspect
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, deque
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

import beside_a_name
import ideas_record
import page_text
import phone_width
import pytest
import shelves_record
from four_years import ASTRID
from library_record import BERGEN_WINTER, library_record
from orgs_record import TODAY, evidence_record, settle
from persona import persona_record

from logbook.contrib import (
    entity_review,
    ideas,
    orgs,
    people_review,
    places_review,
    reflect,
    serve,
    week_paper,
)
from logbook.core import store
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
OCTOBER = datetime(2025, 10, 1, 12, 0, tzinfo=UTC)
DAY = "2022-01-10"  # a day of the Bergen winter, with the promise on it
PHOTO_DAY = "2022-01-03"  # a day of it with a photo, for the photo review
SAID = "Another command is writing to the record; nothing was written. Try again in a moment."
HEARD = "Heard on this machine: the harbour office, then the ferry home."
JUNE = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)  # after the persona's fortnight
WEDNESDAY = "2026-06-10"  # a day of it, with rows to star
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
KIOSK_COPY = "1f2e3d4c-0000-4000-8000-000000000061"  # a page titled like the kiosk: the Ideas queue's match
DETAILS = (
    ("/day/D", serve.DAY_PATH),
    ("/journeys/A/B", serve.JOURNEY_PATH),
    ("/people/ID", serve.PERSON_PATH),
    ("/org/ID", serve.ORG_PATH),
    ("/idea/ID", serve.IDEA_PATH),
    ("/promises/ID", serve.PROMISE_PATH),
    ("/goals/ID", serve.GOAL_PATH),
    ("/line/ID", serve.LINE_PATH),
    ("/week/W", serve.WEEK_PATH),
    ("/timeline/Z", serve.TIMELINE_PATH),
)  # the pages one of many: a route each
ROUTES = frozenset(
    {
        "/",
        "/shelves",
        "/day/D",
        "/days",
        "/trips",
        "/places",
        "/assets",
        "/gaps",
        "/world",
        "/journeys",
        "/journeys/A/B",
        "/people",
        "/people/ID",
        "/manifest",
        "/manifest/people",
        "/org/ID",
        "/ideas",
        "/idea/ID",
        "/promises",
        "/promises/ID",
        "/goals",
        "/goals/ID",
        "/search",
        "/agents",
        "/line/ID",
        "/week/W",
        "/timeline",
        "/timeline/Z",
        "/life",
    }
)  # every page `Site._page` answers
EACH = 1  # pages of one kind (a route and the names in its query) the walk reads, beside its seeds
ANSWERS = "an error or a redirect"  # the walk's pages that are not a 200


class Page(NamedTuple):
    target: str
    status: int
    text: str


@pytest.fixture(scope="module")
def years(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("walk-years") / "lb"
    library_record(root)
    return root


@pytest.fixture(scope="module")
def fortnight(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        return persona_record(tmp_path_factory.mktemp("walk-fortnight"), mp).root


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        lb = evidence_record(tmp_path_factory.mktemp("walk-orgs"))
        settle(lb)
        return lb.root


@pytest.fixture(scope="module")
def shelf_of_ideas(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ideas record and the owner's sitting on it, with one more page titled like the kiosk, so the
    queue holds a match to accept beside the new ones to name and to reject."""
    with pytest.MonkeyPatch.context() as mp:
        copy = ideas_record.notion(
            "2026-09-25T10:00:00Z", KIOSK_COPY, "The fjord kiosk", action="created", words=60
        )
        lb = ideas_record.record(
            tmp_path_factory.mktemp("walk-ideas"), mp, [*ideas_record.ideas_drafts(), copy]
        )
        ideas_record.settle(lb)
        return lb.root


def _copy(source: Path, to: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    shutil.copytree(source, to)
    monkeypatch.setenv("LOGBOOK_HOME", str(to))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return Logbook(to)


def _hear(path: Path) -> reflect.Reflection:
    """A Day's recording, heard as `day reflect --audio` hears one, without a model."""
    assert path.read_bytes()
    return reflect.Reflection(HEARD, reflect.HEARD, extra={"heard_by": "fake-whisper"})


def _years_site(lb: Logbook) -> serve.Site:
    return serve.Site(lb, now=lambda: OCTOBER, voice=serve.Voice(_hear))


def _manifest_site(lb: Logbook) -> serve.Site:
    return serve.Site(lb, now=lambda: datetime.fromisoformat(f"{TODAY}T12:00:00").replace(tzinfo=UTC))


def _ideas_site(lb: Logbook) -> serve.Site:
    today = ideas_record.TODAY
    return serve.Site(lb, now=lambda: datetime.fromisoformat(f"{today}T12:00:00").replace(tzinfo=UTC))


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# -- forms, read as a browser reads them -------------------------------------------------------------------


class Form(NamedTuple):
    action: str
    method: str
    enctype: str
    fields: dict[str, str]  # what the form sends as it stands: every named field but the buttons' and a file
    files: list[str]  # the names of its file fields
    buttons: list[tuple[str, str]]  # (name, value) of each named button


class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[dict[str, str], Form]] = []
        self.area: str | None = None  # the textarea being read

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            form = Form(a.get("action", ""), a.get("method", "get"), a.get("enctype", ""), {}, [], [])
            self.found.append((a, form))
        elif not self.found:
            return
        fields = self.found[-1][1]
        if tag == "input" and a.get("name"):
            kind = a.get("type", "text")
            if kind == "file":
                fields.files.append(a["name"])
            elif kind == "checkbox":
                fields.fields[a["name"]] = ",".join(
                    filter(None, (fields.fields.get(a["name"]), a.get("value")))
                )
            elif kind not in ("submit", "button", "reset"):
                fields.fields[a["name"]] = a.get("value", "")
        elif tag == "textarea" and a.get("name"):
            self.area = a["name"]
            fields.fields[self.area] = ""
        elif tag == "select" and a.get("name"):
            self.area = None
            fields.fields.setdefault(a["name"], "")
            self._select = a["name"]
        elif tag == "option" and getattr(self, "_select", None) and not fields.fields[self._select]:
            fields.fields[self._select] = a.get("value", "")
        elif tag == "button" and a.get("name"):
            fields.buttons.append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea":
            self.area = None
        elif tag == "select":
            self._select = None

    def handle_data(self, data: str) -> None:
        if self.area is not None and self.found:
            self.found[-1][1].fields[self.area] += data


def _forms(page: str, cls: str | None = None) -> list[Form]:
    """The page's forms that post, in order; with `cls`, only those of that class."""
    parser = _Forms()
    parser.feed(page)
    parser.close()
    return [
        f
        for attrs, f in parser.found
        if f.method == "post" and (cls is None or cls in attrs.get("class", "").split())
    ]


def _paragraphs(page: str, cls: str) -> list[str]:
    start, found = f'<p class="{cls}">', []
    for part in page.split(start)[1:]:
        found.append(part.partition("</p>")[0])
    return found


# -- every act, under another command's lock ---------------------------------------------------------------


class Act(NamedTuple):
    site: serve.Site
    path: str
    form: dict[str, str]
    upload: serve.Upload | None = None


def _acts(years: Logbook, manifest: Logbook, shelf_of_ideas: Logbook) -> list[Act]:
    """Every act the Library serves, each with a form as its page sends it: the shelves' (Places, a
    journey's name, the People queue), the Manifest's (its queue, an org's status), the Ideas' (its
    queue, an idea's status) and the Day's (Reflect in words and by a recording, Sign, a star and an
    unstar, the "with…" field). Before the lock: a reflection on the day, so the Day carries its Sign
    form, and a star, to unstar."""
    site = _years_site(years)
    assert (
        site.write(
            f"/day/{DAY}/reflect",
            {"act": "reflect", "text": "I'll send Astrid the harbour map by Friday."},
            LOOPBACK,
            None,
        ).status
        == 303
    )
    day = site.respond(f"/day/{DAY}", "").body.decode("utf-8")
    stars = [f.fields["line"] for f in _forms(day, "star")]
    assert len(stars) >= 2, "the day carries rows to star"
    assert (
        site.write(serve.STAR_PATH, {"act": "star", "line": stars[0], "day": DAY}, LOOPBACK, None).status
        == 303
    )
    (sign,) = _forms(site.respond(f"/day/{DAY}", "").body.decode("utf-8"), "sign")
    keep, passing = _forms(site.respond(f"/day/{PHOTO_DAY}", "").body.decode("utf-8"), "keep")  # the review
    clusters = [p.id for p in places_review.read(years).proposals]
    (person,) = people_review.read(years).proposals
    queue = entity_review.read(manifest, "org").proposals
    named = {o.label: o.id for o in orgs.named(manifest).values()}
    org = next(iter(named.values()))
    shelf = _manifest_site(manifest)
    proposed = {p.observed.key: p.id for p in entity_review.read(shelf_of_ideas, "idea").proposals}
    match, new, other = (
        proposed[("page", f"notion:{page}")] for page in (KIOSK_COPY, ideas_record.GARDEN, ideas_record.HUB)
    )
    kiosk = {e.label: e.id for e in ideas.named(shelf_of_ideas).values()}[ideas_record.KIOSK]
    idea_site = _ideas_site(shelf_of_ideas)
    return [
        Act(
            site,
            serve.REVIEW_PATH,
            {"id": clusters[0], "page": "1", "name": "The harbour office", "act": "name"},
        ),
        Act(site, serve.REVIEW_PATH, {"id": clusters[1], "page": "1", "name": "", "act": "reject"}),
        Act(site, serve.NAME_PATH, {"id": BERGEN_WINTER, "name": "The Bergen winter"}),
        Act(site, serve.PEOPLE_REVIEW_PATH, {"id": person.id, "year": "2025", "act": "merge"}),
        Act(site, serve.PEOPLE_REVIEW_PATH, {"id": person.id, "year": "2025", "act": "reject"}),
        Act(
            shelf,
            serve.MANIFEST_REVIEW,
            {"id": queue[0].id, "back": "/manifest", "name": "Robåt AS", "act": "name"},
        ),
        Act(shelf, serve.MANIFEST_REVIEW, {"id": queue[1].id, "back": "/manifest", "act": "accept"}),
        Act(shelf, serve.MANIFEST_REVIEW, {"id": queue[2].id, "back": "/manifest", "act": "reject"}),
        Act(
            shelf,
            serve.MANIFEST_STATUS,
            {
                "org": org,
                "back": f"/org/{org}",
                "status": "hold",
                "reason": "came back to it",
                "at": "",
                "act": "status",
            },
        ),
        Act(idea_site, serve.IDEAS_REVIEW, {"id": match, "back": "/ideas", "act": "accept"}),
        Act(
            idea_site,
            serve.IDEAS_REVIEW,
            {"id": new, "back": "/ideas", "name": "the garden notes", "act": "name"},
        ),
        Act(idea_site, serve.IDEAS_REVIEW, {"id": other, "back": "/ideas", "act": "reject"}),
        Act(
            idea_site,
            serve.IDEAS_STATUS,
            {
                "idea": kiosk,
                "back": f"/idea/{kiosk}",
                "status": "build",
                "reason": "the ferry company said yes to a trial",
                "at": "",
                "act": "status",
            },
        ),
        Act(site, f"/day/{DAY}/sign", {**sign.fields, "act": "sign"}),  # every box ticked
        Act(
            site,
            f"/day/{DAY}/reflect",
            {"text": "Other words.\nOn two lines, the harbour and the ferry.", "act": "reflect"},
        ),
        Act(
            site,
            f"/day/{DAY}/reflect",
            {"act": "hear"},
            serve.Upload("reflection.webm", "audio/webm", b"\x1aE\xdf\xa3"),
        ),
        Act(site, serve.STAR_PATH, {"day": DAY, "line": stars[1], "act": "star"}),
        Act(site, serve.STAR_PATH, {"day": DAY, "line": stars[0], "act": "unstar"}),
        Act(site, serve.WITH_PATH, {"day": DAY, "names": f"{ASTRID['name']}, Bjørn Lie", "at": "13:30"}),
        Act(site, serve.STAR_PATH, {**passing.fields, "act": serve.PASS}),  # the photo review's Not a keeper
        Act(site, serve.STAR_PATH, {**keep.fields, "act": "star"}),  # and its Star
        Act(  # the week page's Close the week: next week's intention kept on its Sunday
            site,
            f"/week/{week_paper.week_of(DAY)}/close",
            {"act": "close", "intention": "Send Astrid the harbour map first thing.", "keep": "1"},
        ),
    ]


def _path(act: Act) -> str:
    """The act's path, a Day's with the day left out."""
    found = serve.DAY_ACT.match(act.path)
    if serve.WEEK_ACT.match(act.path) is not None:
        return "/week/W/close"
    return f"/day/D/{found.group(2)}" if found is not None else act.path


def _kind(act: Act) -> str:
    """The act as the Library names it: its path and its `act`."""
    return f"{_path(act)} {act.form.get('act', '')}".strip()


@pytest.fixture
def holder() -> Iterator[dict[str, object]]:
    """Another command's writer lock as the store writes it, held by a process that is alive."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield {"pid": other.pid, "command": "logbook sync", "since": "2025-10-01T06:00:00Z"}
    finally:
        other.kill()
        other.wait()


def test_every_act_answers_a_busy_record_one_way_and_writes_nothing(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    holder: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While another command holds the record's writer lock, every act of the Library, the shelves',
    the Manifest's, the Ideas' and the Day's alike, answers the same: a 409 whose page says the one
    sentence (and who holds the lock, in the store's words), and keeps the form's input in a form that
    posts it again; and nothing is written, not a line, not a file. Once the lock is free, the kept
    form sent again is the act."""
    mine = _copy(years, tmp_path / "years", monkeypatch)
    theirs = _copy(manifest, tmp_path / "orgs", monkeypatch)
    hers = _copy(shelf_of_ideas, tmp_path / "ideas", monkeypatch)
    acts = _acts(mine, theirs, hers)
    found = re.search(r"/\(([a-z|]+)\)\$$", serve.DAY_ACT.pattern)  # the Day's acts, from its route
    assert found is not None, serve.DAY_ACT.pattern
    day_acts = {f"/day/D/{act}" for act in found.group(1).split("|")}
    assert day_acts == {"/day/D/reflect", "/day/D/sign"}
    every = {*serve.WRITE_PATHS, *serve.LINE_ACTS, *day_acts, "/week/W/close"}
    assert {_path(a) for a in acts} == every, "every act's path"
    assert {_kind(a) for a in acts} >= {
        f"{serve.REVIEW_PATH} name",
        f"{serve.REVIEW_PATH} reject",
        f"{serve.PEOPLE_REVIEW_PATH} merge",
        f"{serve.PEOPLE_REVIEW_PATH} reject",
        f"{serve.MANIFEST_REVIEW} accept",
        f"{serve.MANIFEST_REVIEW} name",
        f"{serve.MANIFEST_REVIEW} reject",
        f"{serve.IDEAS_REVIEW} accept",
        f"{serve.IDEAS_REVIEW} name",
        f"{serve.IDEAS_REVIEW} reject",
        f"{serve.IDEAS_STATUS} status",
        f"/day/D/reflect {serve.REFLECT}",
        f"/day/D/reflect {serve.HEAR}",
        f"{serve.STAR_PATH} star",
        f"{serve.STAR_PATH} unstar",
        f"{serve.STAR_PATH} {serve.PASS}",
    }
    locks = [lb.root.joinpath(*store.LOCK_FILE.parts) for lb in (mine, theirs, hers)]
    for lock in locks:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps(holder), encoding="utf-8")
    before = {lb.root: (_files(lb.root), lb.meta["head"]) for lb in (mine, theirs, hers)}
    answers: dict[str, str] = {}
    kept: list[Form] = []
    for act in acts:
        response = act.site.write(act.path, act.form, LOOPBACK, f"http://{LOOPBACK}:8765", act.upload)
        page = response.body.decode("utf-8")
        assert response.status == 409, (_kind(act), response.status, page[:400])
        assert _paragraphs(page, "busy") == [SAID], _kind(act)
        assert "another logbook command is writing to this record (logbook sync" in page, _kind(act)
        assert page_text.says(page, "409") and _neither_503_nor_no_wait(page), _kind(act)
        (again,) = _forms(page, "again")
        assert again.action == act.path and again.buttons == [], _kind(act)
        assert again.fields == act.form, (_kind(act), again.fields)
        assert again.files == (["audio"] if act.upload is not None else []), _kind(act)
        assert again.enctype == ("multipart/form-data" if act.upload is not None else ""), _kind(act)
        assert phone_width.problems(page) == [], _kind(act)
        main = page[page.index("<main>") : page.index("</main>")]
        answers[_kind(act)] = main[: main.index('<form class="again"')]
        kept.append(again)
    assert len(set(answers.values())) == 1, "one answer, word for word, for every act"
    for lb in (mine, theirs, hers):
        assert (_files(lb.root), Logbook(lb.root).meta["head"]) == before[lb.root], "nothing written"
    for lock in locks:
        assert json.loads(lock.read_text(encoding="utf-8")) == holder
        lock.unlink()
    for act, again in zip(acts, kept, strict=True):  # the lock free: the kept form is the act
        response = act.site.write(again.action, again.fields, LOOPBACK, None, act.upload)
        assert SAID not in response.body.decode("utf-8"), _kind(act)
        if _kind(act) == f"{serve.PEOPLE_REVIEW_PATH} reject":  # merged a moment ago: out of the queue
            assert response.status == 409 and "not in the queue" in response.body.decode("utf-8")
        else:
            assert response.status == 303, (_kind(act), response.status, response.body[:400])
    assert Logbook(mine.root).meta["head"] != before[mine.root][1]
    assert Logbook(hers.root).meta["head"] != before[hers.root][1]


def _neither_503_nor_no_wait(page: str) -> bool:
    """The busy page's words: a reader never sees 503 on it, the status the Library's acts answered
    a busy record with before #315 (`page_text.says`: what the page shows, as a word; the line ids
    of its kept form are random hex and hold "503" now and then, as the head's hash may); and it
    never mentions the store's `--no-wait` anywhere, attributes and all (no id or hash holds it)."""
    return "--no-wait" not in page and not page_text.says(page, "503")


def test_the_busy_check_reads_what_a_reader_sees(
    years: Path, holder: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check above that the busy page never says 503 reads the page as a reader does, not its
    source: a kept form's line id is random hex and holds "503" now and then (one did on CI, in a
    hidden field, and a whole-page substring failed a right page), as the head's hash in the footer
    may; a page that says 503 still fails it."""
    lb = _copy(years, tmp_path / "years", monkeypatch)
    lock = lb.root.joinpath(*store.LOCK_FILE.parts)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(holder), encoding="utf-8")
    line = "01a1455c-0d41-7503-b7bc-6e84e26be254"  # a line id as UUIDv7 draws one, with 503 in it
    form = {"day": DAY, "line": line, "act": "star"}
    response = _years_site(lb).write(serve.STAR_PATH, form, LOOPBACK, f"http://{LOOPBACK}:8765")
    page = response.body.decode("utf-8")
    assert response.status == 409 and _paragraphs(page, "busy") == [SAID], page[:400]
    (again,) = _forms(page, "again")
    assert again.fields == form and f'type="hidden" name="line" value="{line}"' in page
    assert _neither_503_nor_no_wait(page), "a right page, the id in its kept form"
    head = re.search(r"head <code>([0-9a-f]+)…</code>", page)
    assert head is not None, page[-400:]
    assert _neither_503_nor_no_wait(page.replace(head.group(1), "e1e9503a412b")), "the head's hash"
    for said in ("<h1>503</h1>", '<h1>409</h1>\n<p class="mute">Service unavailable (503).</p>'):
        assert not _neither_503_nor_no_wait(page.replace("<h1>409</h1>", said)), said
    assert not _neither_503_nor_no_wait(page.replace("</main>", "<p>logbook sync --no-wait</p>\n</main>"))


def test_the_owner_s_sentence_is_the_library_s_one_busy_answer() -> None:
    assert serve.BUSY == SAID


# -- every page, on a phone ----------------------------------------------------------------------------------


def _route(path: str) -> str:
    return next((name for name, pattern in DETAILS if pattern.match(path)), path)


def _sort(target: str) -> str:
    """A page's kind: its route and the names in its query."""
    path, _, query = target.partition("?")
    names = sorted({part.partition("=")[0] for part in query.split("&") if part})
    return _route(path) + ("?" + "&".join(names) if names else "")


def _walk(site: serve.Site, seeds: Sequence[str]) -> dict[str, tuple[int, str]]:
    """Every page the Library serves from `seeds` on, through every link on every page it reads (a
    redirect's target among them), up to `EACH` of a kind: (status, text) by the page's target."""
    queue, seen, kinds = deque(seeds), set(seeds), Counter(_sort(seed) for seed in seeds)
    read: dict[str, tuple[int, str]] = {}
    while queue:
        target = queue.popleft()
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        text = response.body.decode("utf-8")
        read[target] = (response.status, text)
        links = [response.location] if response.location else [html.unescape(t) for t in HREF.findall(text)]
        for link in links:
            link = link.partition("#")[0]
            if (
                not link.startswith("/")
                or link.startswith("//")
                or link in seen
                or kinds[_sort(link)] >= EACH
            ):
                continue
            kinds[_sort(link)] += 1
            seen.add(link)
            queue.append(link)
    return read


@pytest.fixture(scope="module")
def walked(
    fortnight: Path, manifest: Path, shelf_of_ideas: Path, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, list[Page]]:
    """Every page the Library serves, walked once (`_walk`) from `/` on the persona's fortnight, whose
    Day carries every form it can (Reflect and Sign, a reflection standing on it; the recording; the
    stars; the "with…" field), on the orgs record, for the Manifest, and on the ideas record, for the
    Ideas; with an error of each kind and a redirect. By route, a page that is not a 200 under
    `ANSWERS`."""
    folder = tmp_path_factory.mktemp("walk")
    with pytest.MonkeyPatch.context() as mp:
        mine = _copy(fortnight, folder / "fortnight", mp)
        site = serve.Site(mine, now=lambda: JUNE, voice=serve.Voice(_hear))
        said = {"act": "reflect", "text": "I'll send Ola the harbour map by Friday. Ola will book the ferry."}
        assert site.write(f"/day/{WEDNESDAY}/reflect", said, LOOPBACK, None).status == 303
        day = site.respond(f"/day/{WEDNESDAY}", "").body.decode("utf-8")
        assert all(_forms(day, cls) for cls in ("reflect", "audio", "sign", "star", "with")), "every form"
        sites = (
            (
                site,
                [
                    "/",
                    f"/day/{WEDNESDAY}",
                    f"/day/{WEDNESDAY}?open=1",
                    "/nowhere",
                    "/days?from=2026-13-01",
                    "/search?q=ola",  # a search with hits
                    "/search?q=ola&page=0",  # and one refused
                    "/life",  # the Life door, not in the navigation yet
                ],
            ),
            (_manifest_site(_copy(manifest, folder / "orgs", mp)), ["/", "/manifest/people?money=1"]),
            (_ideas_site(_copy(shelf_of_ideas, folder / "ideas", mp)), ["/", "/ideas"]),
            # the Promises, Goals and Agents shelves, on their record (`shelves_record.py`)
            (
                serve.Site(shelves_record.record(folder / "shelves", mp), now=lambda: shelves_record.NOW),
                ["/", "/promises", "/goals", "/agents", "/life"],
            ),
        )
        found: dict[str, list[Page]] = {}
        for one, seeds in sites:
            for target, (status, text) in _walk(one, seeds).items():
                key = _route(target.partition("?")[0]) if status == 200 else ANSWERS
                found.setdefault(key, []).append(Page(target, status, text))
        return found


def test_the_walk_knows_every_page_the_server_answers(walked: dict[str, list[Page]]) -> None:
    """`ROUTES` is what `Site._page` answers, read from it: a page added there and not here fails
    this; and the walk reaches every one of them, an error and a redirect besides, so the test below
    holds each to the column."""
    source = inspect.getsource(serve.Site._page)
    literal = set(re.findall(r'path == "(/[^"]*)"', source))
    patterns = {getattr(serve, name) for name in re.findall(r"\b([A-Z_]+_PATH)\.match\(path\)", source)}
    assert literal | {name for name, pattern in DETAILS if pattern in patterns} == ROUTES
    assert patterns == {pattern for _, pattern in DETAILS}
    assert set(walked) == {*ROUTES, ANSWERS}, {*ROUTES, ANSWERS} ^ set(walked)
    assert {p.status for p in walked[ANSWERS]} >= {302, 400, 404}


@pytest.mark.parametrize("route", [*sorted(ROUTES), ANSWERS])
def test_every_page_the_library_serves_fits_a_phone(walked: dict[str, list[Page]], route: str) -> None:
    """Read as a phone 400 px wide reads them, every disclosure open, from the HTML and the page's own
    stylesheet (`phone_width`, no browser): every page `logbook serve` serves (`walked`: the Day,
    every shelf, the Manifest, the Ideas, each detail page, an error, a redirect), by route: no element passes
    the column with the frames around it, every image and pre is held inside it, and every stylesheet
    has its phone breakpoint. The four years' widest shelves are held to it in `test_library_pages.py`
    besides."""
    for page in walked[route]:
        assert phone_width.problems(page.text) == [], page.target
        assert phone_width.phone_breakpoints(phone_width.parse(page.text)[1]), page.target


@pytest.mark.parametrize("route", [*sorted(ROUTES), ANSWERS])
def test_no_page_the_library_serves_sets_a_number_beside_a_name(
    walked: dict[str, list[Page]], route: str
) -> None:
    """The owner's rule, no number beside a person's name (RFC 0043 §2.5), held by the strong guard
    (`beside_a_name`) over every page of the walk, a row at a time as a reader sees it: the persona's
    people are the demo record's (Ines, Kari and Ola Nordmann, Per Hansen), the guard's names. A
    person's own page (/people/ID) is held to it too: it may say how many days together, never beside
    the name."""
    for page in walked[route]:
        assert beside_a_name.page(page.text) == [], (page.target, beside_a_name.page(page.text))
