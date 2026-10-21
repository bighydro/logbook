"""Reading never opens a connection. The rule (SECURITY.md, CONTRIBUTING.md): network calls happen only
behind the commands that say so — `sync` for a live source, `videos fetch` for a video's bytes, a
`--fetch-model`, `dream` and `transcript synthesize` for the model endpoint, `serve` listening on
127.0.0.1 — never in a reader (every command
`logbook --help` names that prints from the record and writes nothing, `READERS` below), a page `serve`
renders (`PAGES`) or `mcp --inspect`. This module makes that a test, not a promise: the `no_network`
fixture of `tests/conftest.py` replaces every way out of the process with one that records the attempt
and refuses, each reader runs against the demo record (thirty days of the Oslo persona, who does not
exist), and the list of attempts must be empty afterwards, whatever the command printed or caught.
The same guard covers `verify` on the conformance sample, which must still print the head
`conformance/README.md` documents."""

from __future__ import annotations

import json
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
import shelves_record
from orgs_record import VERFT, settled_record
from policy_entry import allow

from logbook import cli
from logbook.contrib import journeys, orgs, serve, shelf_promises
from logbook.core import people
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "conformance" / "sample-logbook"
EXPECTED = ROOT / "conformance" / "expected.json"
OUT = "OUT"  # replaced by a file under the test's tmp_path, for the commands that write a page
BACKUPS = "BACKUPS"  # replaced by a folder holding one snapshot of the demo record (`backups`)

# A reader of what an extra's engine finds reads only with the extra installed; without it, it exits 2
# with the sentence that names the extra (tests/test_setup_speakers.py, under the same guard). Here a
# stand-in module is where `import` finds the engine, so the reader runs to its end: the engine itself
# is never what says whether a model is here.
INSTALLED: dict[tuple[str, ...], tuple[str, ...]] = {("setup", "speakers"): ("pyannote.audio",)}

# every reader of the record, as the user runs it: text first, then its --json and other forms
READERS: tuple[tuple[str, ...], ...] = (
    ("day", "2026-06-08"),
    ("day", "2026-06-08", "--json"),
    ("day", "2026-06-17"),  # a night aboard the boat
    ("day", "2026-06-08", "--no-dream", "--no-anniversaries"),
    ("day", "reflect", "2026-06-08", "--text", "A long day at the office.", "--dry-run"),  # proposals only
    ("day", "reflect", "2026-06-08", "--text", "I will call Ola tomorrow.", "--dry-run"),  # one commitment
    (
        "show",
        "days",
    ),
    ("show", "days", "--from", "2026-06-06", "--to", "2026-06-12", "--json"),
    ("show", "2026-06-08"),
    ("show", "2026-06-08", "--raw"),
    (
        "show",
        "trips",
    ),
    ("show", "trips", "--year", "2026", "--json"),
    ("show", "trip", "2026-06-09"),
    ("show", "trip", "2026-06-09", "--json"),
    ("show", "trip", "2026-06-09", "--html", OUT),
    ("show", "trip", "2026-06-09", "--html", OUT, "--print"),
    ("show", "person", "Ola Nordmann"),
    ("show", "person", "Ola Nordmann", "--json"),
    ("show", "asset", "nordlys"),
    ("show", "asset", "nordlys", "--json"),
    ("show", "place", "Marina"),
    ("show", "place", "Marina", "--json"),
    ("show", "place", "Cabin"),
    ("show", "place", "Cabin", "--json"),
    ("rollup", "countries"),
    ("rollup", "flights"),
    ("rollup", "nights"),
    ("rollup", "places"),
    ("rollup", "places", "--with"),
    ("rollup", "people"),
    ("rollup", "money"),
    ("rollup", "health"),
    ("rollup", "health", "--by", "week"),
    ("rollup", "attention"),
    ("rollup", "listen"),
    ("rollup", "countries", "--year", "2026", "--json"),
    ("rollup", "flights", "--json"),
    ("rollup", "nights", "--json"),
    ("rollup", "places", "--with", "--json"),
    ("rollup", "people", "--drifting"),
    ("rollup", "attention", "--by", "week"),
    ("rollup", "ledger", "--month", "2026-06"),
    ("rollup", "ledger", "--json"),
    ("derive", "stays", "--day", "2026-06-03", "--dry-run"),
    ("derive", "stays", "--since", "2026-06-01", "--until", "2026-06-30", "--dry-run", "--json"),
    ("derive", "speakers", "--dry-run"),  # RFC 0038 §2.8: what would be heard again, nothing heard
    ("derive", "transcripts", "voice-memos", "--dry-run"),  # no engine, no diarizer asked for
    ("derive", "flights", "--dry-run"),
    ("derive", "keepers", "--dry-run"),
    ("derive", "descriptions", "keepers", "--dry-run"),  # no vision model asked for
    ("show", "year", "2026"),
    ("show", "year", "2026", "--json"),
    ("show", "year", "2026", "--html", OUT),
    ("show", "year", "2026", "--html", OUT, "--print"),
    ("show", "year", "2026", "--poster"),
    ("show", "year", "2026", "--poster", "--html", OUT),
    ("digest", "2026-06-08"),
    ("digest", "2026-06-08", "--json"),
    ("digest", "2026-06-08", "--markdown"),
    ("digest", "2026-06-08", "--paper"),
    ("digest", "2026-06-08", "--paper", "--html", OUT),
    ("digest", "--paper", "--week", "2026-W24"),
    (
        "show",
        "stats",
    ),
    ("show", "stats", "--health", "--json"),
    (
        "rollup",
        "ledger",
    ),
    (
        "show",
        "keepers",
    ),
    ("show", "keepers", "--json"),
    ("show", "keepers", "--lane", "art"),
    ("show", "keepers", "--people"),
    ("setup", "places", "list"),
    ("setup", "places", "propose"),  # without --write: appends nothing
    ("setup", "places", "propose", "--json"),
    ("setup", "places", "review"),  # nothing told: the queue; --ask-photos is the one that asks Immich
    ("setup", "places", "review", "--json"),
    ("setup", "speakers"),  # RFC 0038 §2.9: what is here; only --fetch-model reaches the network
    ("setup", "questions", "list"),  # the first read writes policy/questions.json's defaults, never a line
    ("setup", "questions", "list", "--json"),
    ("setup", "day_start"),  # no value: where the day begins, said
    ("people",),
    ("people", "--json"),
    ("people", "--priority"),
    ("people", "Ola Nordmann"),
    ("people", "Ola Nordmann", "--json"),
    ("people", "merge"),  # --propose, the default: merged only when told
    ("people", "merge", "--json"),
    ("people", "merge", "--export-review", OUT),
    ("people", "review"),  # nothing accepted or rejected; --from-google is the one that asks Google
    ("people", "review", "--json"),
    ("people", "drift"),
    ("people", "drift", "--min-days", "1", "--quiet-days", "1", "--show"),
    ("people", "nearby", "Marina"),
    ("people", "nearby", "Cabin"),
    ("people", "nearby", "--days", "2026-06-08", "2026-06-10"),
    ("review", "speakers"),  # RFC 0038 §4: the queue reads the record and opens nothing
    ("review", "speakers", "--json"),
    ("show", "ideas", "--json"),
    ("setup", "assets", "status"),
    ("setup", "assets", "status", "--json"),
    ("setup", "assets", "list"),
    ("doctor", "sources", "--gaps"),
    ("doctor", "sources", "--gaps", "--json"),
    ("doctor", "sources"),
    ("doctor",),  # no serve service installed here, so no HEAD to 127.0.0.1 to ask whether it answers
    ("doctor", "--implausible"),
    ("doctor", "--packet"),  # LOGBOOK_DREAM_ENDPOINT unset: the one probe the packet may make is not made
    ("doctor", "--packet", "--out", OUT),
    ("search", "cabin"),
    ("search", "cabin", "--json"),
    ("import", "inbox", "list"),
    ("import", "inbox", "list", "--json"),
    ("import", "inbox", "clean", "--delete", "--dry-run"),
    ("import", "attachments", "status"),
    ("import", "attachments", "status", "--json"),
    ("import", "attachments", "verify"),
    ("goal", "list"),
    ("goal", "list", "--json"),
    ("chapter", "list"),
    ("chapter", "list", "--json"),
    ("review",),  # every queue, nothing told: nothing written, nothing looked up
    ("review", "--json"),
    ("review", "person"),
    ("review", "org"),
    ("review", "idea"),
    ("review", "asset"),
    ("review", "place"),
    ("review", "goal"),  # RFC 0036 amendment 1: the open goals not reviewed this week, nothing told
    ("review", "goal", "--json"),
    ("status", "list", "org"),
    ("status", "list", "idea"),
    ("status", "list", "place"),
    ("status", "list", "asset"),
    ("status", "list", "place", "--json"),
    ("promises",),  # the rules alone; --judge runs a local model, tested under its own guard
    ("promises", "--json"),
    ("promises", "--all"),
    ("promises", "tasks"),
    ("promises", "tasks", "--json"),
    ("promises", "tasks", "--propose-done"),
    ("lab", "introductions"),
    ("lab", "introductions", "--json"),
    ("lab", "chapters"),
    ("lab", "chapters", "--json"),
    ("lab", "hold", "census", "senders"),
    ("lab", "hold", "census", "senders", "--tier", "3", "--json"),
    ("lab", "hold", "census", "drive"),
    ("lab", "hold", "census", "drive", "--json"),
    ("lab", "hold", "census", "files", str(ROOT / "docs" / "adr")),  # a folder of the repository, read only
    ("key", "show"),
    ("repair", "tail", "--dry-run"),
    ("repair", "fork"),  # without --apply: which chain is the record, said
    ("repair", "health-units", "--dry-run"),
    ("export", "crossing", "--to", "hermes", "--since", "2026-06-01T00:00:00Z", "--dry-run"),
    ("export", "crossing", "--to", "hermes", "--since", "2026-06-01T00:00:00Z", "--dry-run", "--unsigned"),
    ("export", "trip-bundle", "2026-06-09", "--to", "hermes", "--dry-run"),
    ("backup", "list", BACKUPS),
    ("verify",),
    ("verify", "--keyless"),
    ("videos", "infer"),  # RFC 0040: reads the cache on this machine, never the network
    ("videos", "infer", "--dry-run"),
    ("review", "video"),  # the queue reads the record and the registries alone
    ("review", "video", "--json"),
)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """The demo record, generated once per worker; the readers only read it. Its policy names hermes
    at tier 2, as the owner writes it, for the dry runs that cross to it."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    allow(root, "hermes", 2)
    return Logbook(root)


@pytest.fixture(scope="module")
def backups(record: Logbook, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One snapshot of the demo record, made once per worker before any guard is up, for `backup list`."""
    dest = tmp_path_factory.mktemp("backups")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(record.root))
        cli.main(["backup", str(dest)])
    return dest


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


@pytest.mark.parametrize("argv", READERS, ids=lambda argv: " ".join(argv))
def test_a_reader_opens_no_connection(
    argv: tuple[str, ...],
    lb: Logbook,
    backups: Path,
    no_network: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in INSTALLED.get(argv, ()):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    capsys.readouterr()  # what the module's fixtures printed is not this reader's
    placed = {OUT: str(tmp_path / "page.html"), BACKUPS: str(backups)}
    cli.main([placed.get(arg, arg) for arg in argv])
    assert no_network == [], f"logbook {' '.join(argv)} tried to connect: {no_network}"
    assert capsys.readouterr().out, "the command printed nothing"


JOURNEY = "/journeys/FIRST/LAST"  # the demo's latest journey, found as tests/test_journeys.py finds one
PERSON = "/people/ID"  # Ola Nordmann's page, by the entity id the People page links
LINE = "/line/ID"  # a line as written: the first of the Monday's, by its id, as a Day row links it
# every page `serve` answers a GET with (`Site._page`), a query after `?`; the Manifest's and an org's
# read the orgs record (`ORG_PAGES`, below), and /today is a redirect
PAGES = (
    "/",
    "/day/2026-06-08",
    "/day/2026-06-08?open=1",
    "/day/2026-06-17",
    "/days",
    "/days?from=2026-06-15&to=2026-06-20",
    "/trips?year=2026",
    "/places",
    "/ideas",
    "/promises",
    "/goals",
    "/agents",
    "/journeys",
    "/journeys?year=2026",
    JOURNEY,
    "/people",
    "/people?year=2026",
    PERSON,
    "/assets",
    "/gaps",
    "/world",
    "/world?from=2026-06-15&to=2026-06-20",
    "/day/2026-06-14",  # a Sunday: the week's draft, when its week has one
    LINE,
)


def _page(path: str, lb: Logbook) -> str:
    """`path`, with the journey and the person put in as the demo record names them."""
    if path == JOURNEY:
        trip = journeys.shelf(lb, "2026").journeys[0].trip
        return f"/journeys/{trip.start}/{trip.end}"
    if path == PERSON:
        return f"/people/{people.find('Ola Nordmann', people.directory(lb)).entity}"
    if path == LINE:
        with lb.index() as idx:
            return f"/line/{idx.day('2026-06-08')[0]['id']}"
    return path


@pytest.mark.parametrize("page", PAGES)
def test_a_served_page_opens_no_connection(page: str, lb: Logbook, no_network: list[str]) -> None:
    """The pages `serve` renders, through the `Site` the server answers from. The one socket the
    command itself opens is the listener on 127.0.0.1, refused for any other host before it is
    opened (`tests/test_serve.py`); a page fetches nothing."""
    path, _, query = _page(page, lb).partition("?")
    response = serve.Site(lb).respond(path, query)
    assert response.status == 200, response.body[:200]
    assert no_network == [], f"the page {path} tried to connect: {no_network}"


def test_today_redirects_to_the_day_and_opens_no_connection(lb: Logbook, no_network: list[str]) -> None:
    """`/today` is a redirect to the Day the owner is in now (RFC 0036), never a page of its own; the
    Day it names is read like any other."""
    site = serve.Site(lb, now=lambda: datetime(2026, 6, 8, 10, 0, tzinfo=UTC))
    response = site.respond("/today", "")
    assert (response.status, response.location) == (302, "/day/2026-06-08")
    assert site.respond("/day/2026-06-08", "").status == 200
    assert no_network == [], f"/today tried to connect: {no_network}"


def test_a_photo_s_thumbnail_is_read_from_the_store_and_opens_no_connection(
    record: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    """A Day's thumbnail (`/photo/ID`) is the record's own attachment store, never a library's server:
    a photo whose pixels the store holds is served from it, and the Day it is on fetches nothing. On
    a copy of the demo record, which the other tests read as it is."""
    import shutil

    from logbook.core import attachments

    shutil.copytree(record.root, tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    lb = Logbook(tmp_path / "lb")

    data = b"\x89PNG\r\n\x1a\n" + b"\0" * 24  # a PNG's signature: the page checks no more of it
    attachments.write(lb.root, data)
    payload = {
        "schema": "photo/v1",
        "asset_id": "stored-1",
        "library": "apple-photos",
        "file_name": "IMG_0001.PNG",
        "media": "image",
        "raw_id": "stored-1",
        "content": attachments.reference(data, "image/png"),
    }
    line = lb.append(at="2026-06-08T10:00:00Z", source="apple-photos", kind="photo", tier=1, payload=payload)
    site = serve.Site(lb)
    assert f'src="/photo/{line["id"]}"' in site.respond("/day/2026-06-08", "").body.decode("utf-8")
    response = site.respond(f"/photo/{line['id']}", "")
    assert (response.status, response.body) == (200, data)
    assert no_network == []


def test_the_favicon_answers_empty_and_opens_no_connection(lb: Logbook, no_network: list[str]) -> None:
    """`/favicon.ico`, the one other GET the server answers: an empty 204, the record not read."""
    response = serve.Site(lb).respond("/favicon.ico", "")
    assert (response.status, response.body) == (204, b"")
    assert no_network == []


# The orgs the owner named (RFC 0037 §11). The demo record names none, so `show org NAME` and the
# Manifest's pages read the record of `tests/orgs_record.py` instead: the Oslo persona's companies, invested
# in or passed on, none of which exists.
ORG_READERS: tuple[tuple[str, ...], ...] = (
    ("show", "orgs"),
    ("show", "orgs", "--json"),
    ("show", "orgs", "--money"),
    ("show", "org", "verft"),
    ("show", "org", "Nordmann Tidevann", "--json"),
    ("show", "org", "havbris", "--money"),
)
ORG = "/org/ID"  # Nordmann Verft's page, by the entity id the Manifest links
ORG_PAGES = ("/manifest", "/manifest/people", ORG, f"{ORG}?money=1")


@pytest.fixture(scope="module")
def org_record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """The orgs record, the evidence and the owner's sitting, made once per worker; only read here."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_DIAL_PREFIX", "44")
        return settled_record(tmp_path_factory.mktemp("orgs"))


@pytest.fixture
def org_lb(org_record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(org_record.root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    return org_record


@pytest.mark.parametrize("argv", ORG_READERS, ids=lambda argv: " ".join(argv))
def test_an_org_reader_opens_no_connection(
    argv: tuple[str, ...], org_lb: Logbook, no_network: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    cli.main(list(argv))
    assert no_network == [], f"logbook {' '.join(argv)} tried to connect: {no_network}"
    assert capsys.readouterr().out, "the command printed nothing"


@pytest.mark.parametrize("page", ORG_PAGES)
def test_an_org_page_opens_no_connection(page: str, org_lb: Logbook, no_network: list[str]) -> None:
    """The Manifest, its people and one org's page, with and without the ledger's lines (tier 3)."""
    named = {org.label: org.id for org in orgs.named(org_lb).values()}
    path, _, query = page.replace(ORG, f"/org/{named[VERFT]}").partition("?")
    response = serve.Site(org_lb).respond(path, query)
    assert response.status == 200, response.body[:200]
    assert no_network == [], f"the page {path} tried to connect: {no_network}"


# The Promises, Goals and Agents shelves. The demo record has no goal and no agent session, so their
# pages with something on them, and a promise's and a goal's own page, read `tests/shelves_record.py`.
PROMISE, GOAL = "/promises/ID", "/goals/ID"  # the first promise the shelf lists; the quarter goal
SHELF_PAGES = (
    "/promises",
    "/promises?person=Ola Nordmann",
    PROMISE,
    "/goals",
    GOAL,
    "/agents",
    "/agents?day=2026-03-01",
)


@pytest.fixture(scope="module")
def shelves_lb(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    folder = tmp_path_factory.mktemp("shelves")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "home", lambda: folder / "home")
        return shelves_record.record(folder, mp)


@pytest.mark.parametrize("page", SHELF_PAGES)
def test_a_shelf_page_opens_no_connection(
    page: str, shelves_lb: Logbook, no_network: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The three shelves and their detail pages, the promises' verdicts and the sessions' turns read."""
    monkeypatch.setenv("LOGBOOK_HOME", str(shelves_lb.root))
    first = shelf_promises.read(shelves_lb).rows[0].proposal.id
    quarter = shelves_record.ids(shelves_lb)["quarter"]
    path, _, query = (
        page.replace(PROMISE, f"/promises/{first}").replace(GOAL, f"/goals/{quarter}").partition("?")
    )
    response = serve.Site(shelves_lb, now=lambda: shelves_record.NOW).respond(path, query)
    assert response.status == 200, response.body[:200]
    assert no_network == [], f"the page {path} tried to connect: {no_network}"


def test_mcp_inspect_opens_no_connection(no_network: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """`mcp --inspect` prints the tool table and a sample call; it serves nothing and needs no record."""
    cli.main(["serve", "mcp", "--inspect"])
    out = capsys.readouterr().out
    assert "tools over stdio" in out and '"method": "tools/call"' in out
    assert no_network == [], f"mcp --inspect tried to connect: {no_network}"


def test_verify_on_the_conformance_sample_prints_the_documented_head(
    no_network: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """`logbook verify` on `conformance/sample-logbook` is valid and prints the seq and head of
    `expected.json`, the head the table in `conformance/README.md` documents, and opens nothing."""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    readme = (ROOT / "conformance" / "README.md").read_text(encoding="utf-8")
    assert f"| {expected['seq']} | `{expected['head']}` |" in readme, "the README's table is out of date"
    cli.main(["verify", "--root", str(SAMPLE), "--expect", str(EXPECTED)])
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"valid — {expected['seq']} lines, head {expected['head']}"
    assert no_network == []


def test_the_guard_itself_records_and_refuses(no_network: list[str]) -> None:
    """The fixture is not a no-op: a connection attempt is recorded and raises, and is not an OSError,
    so a reader that catches connection errors cannot hide one."""
    import socket
    import urllib.request

    with pytest.raises(RuntimeError, match="may not open"):
        socket.socket()
    with pytest.raises(RuntimeError, match="may not open"):
        urllib.request.urlopen("http://127.0.0.1:9/")
    with pytest.raises(RuntimeError) as e:
        socket.create_connection(("127.0.0.1", 9))
    assert not isinstance(e.value, OSError)
    assert no_network == ["socket.socket", "urllib.request.urlopen", "socket.create_connection"]


@pytest.mark.parametrize(
    "argv",
    [
        ("people", "ask", "Ola Nordmann", "What did we plan for the boat?"),
        ("dream", "person", "Ola Nordmann", "--window", "2026-06-01", "2026-06-30"),
    ],
    ids=lambda argv: " ".join(argv[:2]),
)
def test_the_relationship_reader_without_its_entry_sends_nothing(
    argv: tuple[str, ...],
    lb: Logbook,
    no_network: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The demo record's policy names no `relationship` entry; with an endpoint set, as a cloud model's
    would be, `people ask` and `dream person` refuse in one sentence and open no connection."""
    monkeypatch.setenv("LOGBOOK_DREAM_ENDPOINT", "https://api.example.org/v1")
    monkeypatch.setenv("LOGBOOK_DREAM_MODEL", "xy-chat-1")
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(list(argv))
    assert e.value.code == 2 and "names no 'relationship' entry" in capsys.readouterr().err
    assert no_network == [], f"logbook {' '.join(argv)} tried to connect: {no_network}"
