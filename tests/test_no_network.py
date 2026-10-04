"""Reading never opens a connection. The rule (SECURITY.md, CONTRIBUTING.md): network calls happen only
behind the commands that say so — `sync` for a live source, `serve` listening on 127.0.0.1 — never in
`day`, `days`, `show`, `trips`, `rollup`, `derive`, `year`, `digest`, the pages `serve` renders or
`mcp --inspect`. This module makes that a test, not a promise: the `no_network` fixture of
`tests/conftest.py` replaces every way out of the process with one that records the attempt and
refuses, each reader runs against the demo record (thirty days of the Oslo persona, who does not
exist), and the list of attempts must be empty afterwards, whatever the command printed or caught.
The same guard covers `verify` on the conformance sample, which must still print the head
`conformance/README.md` documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logbook import cli
from logbook.contrib import serve
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "conformance" / "sample-logbook"
EXPECTED = ROOT / "conformance" / "expected.json"
OUT = "OUT"  # replaced by a file under the test's tmp_path, for the commands that write a page

# every reader of the record, as the user runs it: text first, then its --json and other forms
READERS: tuple[tuple[str, ...], ...] = (
    ("day", "2026-06-08"),
    ("day", "2026-06-08", "--json"),
    ("day", "2026-06-17"),  # a night aboard the boat
    ("days",),
    ("days", "--from", "2026-06-06", "--to", "2026-06-12", "--json"),
    ("show", "2026-06-08"),
    ("show", "2026-06-08", "--raw"),
    ("trips",),
    ("trips", "--year", "2026", "--json"),
    ("trip", "2026-06-09"),
    ("trip", "2026-06-09", "--json"),
    ("trip", "2026-06-09", "--html", OUT),
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
    ("derive", "stays", "--day", "2026-06-03", "--dry-run"),
    ("derive", "stays", "--since", "2026-06-01", "--until", "2026-06-30", "--dry-run", "--json"),
    ("year", "2026"),
    ("year", "2026", "--json"),
    ("year", "2026", "--html", OUT),
    ("digest", "2026-06-08"),
    ("digest", "2026-06-08", "--json"),
    ("digest", "2026-06-08", "--markdown"),
    ("stats",),
    ("stats", "--health", "--json"),
    ("ledger",),
    ("keepers",),
    ("places", "list"),
    ("people",),
    ("assets", "status"),
    ("sources", "--gaps"),
    ("search", "cabin"),
    ("verify",),
)


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """The demo record, generated once per worker; the readers only read it."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "30", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


@pytest.mark.parametrize("argv", READERS, ids=lambda argv: " ".join(argv))
def test_a_reader_opens_no_connection(
    argv: tuple[str, ...],
    lb: Logbook,
    no_network: list[str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main([str(tmp_path / "page.html") if arg == OUT else arg for arg in argv])
    assert no_network == [], f"logbook {' '.join(argv)} tried to connect: {no_network}"
    assert capsys.readouterr().out, "the command printed nothing"


PAGES = ("/", "/day/2026-06-08", "/day/2026-06-17", "/days", "/trips", "/places", "/assets", "/gaps")


@pytest.mark.parametrize("path", PAGES)
def test_a_served_page_opens_no_connection(path: str, lb: Logbook, no_network: list[str]) -> None:
    """The pages `serve` renders, through the `Site` the server answers from. The one socket the
    command itself opens is the listener on 127.0.0.1, refused for any other host before it is
    opened (`tests/test_serve.py`); a page fetches nothing."""
    response = serve.Site(lb).respond(path, "year=2026" if path == "/trips" else "")
    assert response.status == 200, response.body[:200]
    assert no_network == [], f"the page {path} tried to connect: {no_network}"


def test_mcp_inspect_opens_no_connection(no_network: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """`mcp --inspect` prints the tool table and a sample call; it serves nothing and needs no record."""
    cli.main(["mcp", "--inspect"])
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
