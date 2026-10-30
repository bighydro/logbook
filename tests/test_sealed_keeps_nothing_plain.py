"""A sealed record keeps no reading of its tier 2 and 3 lines in plain text on this disk (RFC 0047 §15,
decided for v1): the kept readings beside the index (`kept`), the review pages' observed tables in the
index file, and the Library's built pages (`library_build`) stay in memory for the life of the process,
unless the owner turns on `plaintext_cache` in `logbook.json`. A record that seals nothing keeps them
on disk as before. On the Oslo persona's fortnight (`persona.py`), who does not exist, sealed to two
fresh recipients as `test_sealing.py`'s `sealed_lb` is."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from persona import persona_drafts

from logbook.contrib import entity_review, library_build, people_review, places_review, serve
from logbook.core import kept, sealing
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
OBSERVED = ("person", "org", "idea", "asset", "place")


def _record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sealed: bool, plain: bool | None = None
) -> Logbook:
    """The persona's fortnight, sealed or not, with `plaintext_cache` as given (absent for None)."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    if sealed:
        pairs = [sealing.generate_identity() for _ in range(2)]
        lb.set_meta(recipients=[recipient for _identity, recipient in pairs])
        path = tmp_path / "keys" / "owner.txt"
        sealing.write_identity_file(path, str(pairs[0][0]), "test")
        monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
        lb = Logbook(lb.root)
        assert lb.identities
    if plain is not None:
        lb.set_meta(**{kept.PLAIN: plain})
    lb.append_many(persona_drafts())
    return lb


def _read_every_door(lb: Logbook, built: library_build.Library | None = None) -> dict[str, bytes]:
    site = serve.Site(lb, now=lambda: NOW, library=built)
    pages = {}
    for door in library_build.DOORS:
        response = site.respond(door, "")
        assert response.status == 200, door
        pages[door] = response.body
    return pages


def _kept_files(lb: Logbook) -> set[str]:
    """Every file beside the index but the index itself (and its journal), whatever its name."""
    return {
        p.name
        for p in lb.index_path.parent.iterdir()
        if p.is_file() and not p.name.startswith(lb.index_path.name)
    }


def _stamped(lb: Logbook) -> set[str]:
    with lb.index() as idx:
        return {kind for kind in OBSERVED if idx.observed_stamp(kind)}


def _observed(lb: Logbook) -> list[object]:
    return [
        [o._row() for o in people_review.observed(lb)],
        *([o.row() for o in entity_review.observed(lb, kind)] for kind in ("org", "idea", "asset")),
        [o._row() for o in places_review.observed(lb)],
    ]


def test_a_sealed_record_keeps_no_reading_on_disk_and_reads_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True)
    assert not kept.on_disk(lb), "sealed, and the owner has not turned plaintext_cache on: off by default"
    first = _read_every_door(lb)
    assert _kept_files(lb) == set(), "no kept reading beside the index"
    assert _stamped(lb) == set(), "no observed table in the index file"
    again = _read_every_door(lb)
    assert again == first, "kept in memory for the life of the process: the same pages"


def test_kept_in_memory_a_reading_is_brought_forward_and_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True)
    at = kept.path(lb, "a-reading.json")
    assert at is not None
    kept.save(at, {"seq": 1, "people": ["Kari Nordmann"]})
    assert not at.exists(), "never written to the disk"
    assert kept.load(at) == {"seq": 1, "people": ["Kari Nordmann"]}, "held in memory"
    found = kept.load(at)
    assert found is not None
    found["people"].append("Ola Nordmann")
    assert kept.load(at) == {"seq": 1, "people": ["Kari Nordmann"]}, "a reader never changes what is kept"


def test_what_a_sealed_record_left_on_disk_before_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept readings, observed tables and built pages written while the owner had plaintext_cache on
    (or before the record was sealed) go when it is off: the next reading leaves none of them."""
    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    assert kept.on_disk(lb)
    library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    folder = library_build.folder_of(lb)
    assert list(folder.glob("*.html")) and (folder / library_build.MANIFEST).exists()
    _read_every_door(lb)
    assert _kept_files(lb) and _stamped(lb), "on disk while the owner allows it"
    lb.set_meta(**{kept.PLAIN: False})
    with pytest.raises(library_build.Sealed):
        library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    assert not folder.exists(), "the built pages are gone"
    _read_every_door(lb)
    assert _kept_files(lb) == set() and _stamped(lb) == set()


def test_plaintext_cache_keeps_readings_on_disk_as_a_record_that_seals_nothing_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = _record(tmp_path / "plain", monkeypatch, sealed=False)
    allowed = _record(tmp_path / "allowed", monkeypatch, sealed=True, plain=True)
    for lb in (plain, allowed):
        assert kept.on_disk(lb)
        _read_every_door(lb)
        assert "people-whole.json" in _kept_files(lb)
        assert _stamped(lb) >= {"person", "org", "idea", "place"}
        if os.name == "posix":
            for f in lb.index_path.parent.glob("*.json"):
                assert f.stat().st_mode & 0o777 == 0o600, f.name


def test_the_observed_tables_held_in_memory_are_the_tables_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = _record(tmp_path / "sealed", monkeypatch, sealed=True)
    in_memory = _observed(sealed)
    assert in_memory == _observed(sealed), "the second reading, from memory, is the first"
    sealed.set_meta(**{kept.PLAIN: True})
    assert _observed(sealed) == in_memory, "the same rows as the table on disk would hold"
    assert _stamped(sealed) == set(OBSERVED)


def test_a_sealed_record_builds_no_pages_and_serves_them_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True)
    with pytest.raises(library_build.Sealed, match=kept.PLAIN):
        library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    assert not library_build.folder_of(lb).exists()
    server = serve.make_server(lb, port=0, built=True)
    try:
        assert server.site.library is None, "--built on a sealed record renders every page live"
        assert server.rebuilder is None
    finally:
        server.server_close()
    assert not library_build.folder_of(lb).exists()


def test_a_sealed_record_builds_no_page_even_of_tier_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page of tier 1 still shows who is who, and a resolution is tier 2: none is built."""
    lb = _record(tmp_path, monkeypatch, sealed=True)
    with pytest.raises(library_build.Sealed):
        library_build.build(lb, serve.Site(lb, now=lambda: NOW, tiers=(1,)))
    assert not library_build.folder_of(lb).exists()


def test_plaintext_cache_builds_every_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    result = library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    assert result.pages and not result.failed
    server = serve.make_server(lb, port=0, built=True)
    try:
        assert server.site.library is not None
    finally:
        if server.rebuilder is not None:
            server.rebuilder.stop()
        server.server_close()


def test_a_server_running_built_adds_no_page_once_the_owner_turns_plaintext_cache_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    library = library_build.Library(lb)
    site = serve.Site(lb, now=lambda: NOW, library=library)
    lb.set_meta(**{kept.PLAIN: False})
    assert site.respond("/days", "from=2026-06-08&to=2026-06-09").status == 200
    assert (
        library_build.address("/days", "from=2026-06-08&to=2026-06-09")
        not in library_build.Library(lb).pages()
    )


def test_every_kept_file_left_from_before_goes_whatever_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readings kept under names the next reading never asks for (a gate's, a window's), and a file a
    crash left half written, go too: the first reading of a sealed record clears the folder of them."""
    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    _read_every_door(lb)
    folder = lb.index_path.parent
    for name in ("orgs-touches-1.json", "people-to-end.json", ".promises-whole.json.4242.tmp"):
        (folder / name).write_text("{}", encoding="utf-8")
    lb.set_meta(**{kept.PLAIN: False})
    assert kept.path(lb, "promises-whole.json") is not None
    assert _kept_files(lb) == set()


def test_built_pages_another_process_is_building_are_left_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build another live process holds is not pulled from under it; that build's own end, or the
    next one, removes the pages."""
    import subprocess
    import sys

    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    lb.set_meta(**{kept.PLAIN: False})
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    lock = library_build.folder_of(lb) / library_build.LOCK
    try:
        lock.write_text(f'{{"pid": {child.pid}}}', encoding="utf-8")
        library_build.clear(lb)
        assert (library_build.folder_of(lb) / library_build.MANIFEST).exists(), "left to the live builder"
    finally:
        child.kill()
        child.wait()
    lock.write_text(f'{{"pid": {_dead_pid()}}}', encoding="utf-8")  # the builder gone
    library_build.clear(lb)
    assert not library_build.folder_of(lb).exists(), "its builder gone: removed"


def _dead_pid() -> int:
    """A pid no process has: a child that has exited, confirmed gone (as `test_reader_behind_index.py`
    finds one: Windows keeps an exited process while a handle to it is open)."""
    import subprocess
    import sys

    from logbook.core import store

    for _ in range(20):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        pid = child.pid
        del child
        if not store._alive(pid):
            return pid
    pytest.fail("could not find a pid no process has")


def test_serve_built_on_a_sealed_record_reads_every_page_to_its_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--built` falls back to rendering live on a sealed record, and live reads a page to its end, as
    `logbook serve` does: no 15 s limit and no *Still reading* for a page nothing builds."""
    import math

    from logbook import cli
    from logbook.commands import day

    lb = _record(tmp_path, monkeypatch, sealed=True)
    asked: dict[str, object] = {}
    monkeypatch.setattr(serve, "serve", lambda _lb, **kw: asked.update(kw))
    monkeypatch.setattr(day, "voice", lambda: None)
    cli.main(["serve", "--built", "--port", "0"])
    assert asked["built"] is False and asked["limit_s"] == math.inf
    assert kept.PLAIN in capsys.readouterr().err, "it says why, and what turns it on"
    assert lb.root.exists()


def test_the_close_says_a_sealed_record_builds_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.commands import sync

    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    library_build.build(lb, serve.Site(lb, now=lambda: NOW))
    lb.set_meta(**{kept.PLAIN: False})
    for _ in range(2):  # the close that removes the pages, and every close after it
        assert sync._build_library(lb) == "library off"
        said = capsys.readouterr().out
        assert "sealed record" in said and kept.PLAIN in said and "--built turns them on" not in said
    assert not library_build.folder_of(lb).exists()


def test_a_running_rebuild_says_the_record_is_sealed_not_that_it_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    library = library_build.Library(lb)
    site = serve.Site(lb, now=lambda: NOW, library=library)
    said: list[str] = []
    heard = threading.Event()

    def say(text: str) -> None:
        said.append(text)
        heard.set()

    rebuilder = library_build.Rebuilder(lb, site, library, say).start()
    try:
        lb.set_meta(**{kept.PLAIN: False})
        rebuilder.kick()
        assert heard.wait(60)
    finally:
        rebuilder.stop()
    assert said and "failed" not in said[0] and "sealed record" in said[0]


def test_no_write_of_the_build_lab_keeps_a_page_of_a_sealed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every way the lab writes a page or names one: `put`, `drop`, `save`, a build at any gate. A
    sealed record without `plaintext_cache` keeps none of them, not even of tier 1."""
    lb = _record(tmp_path, monkeypatch, sealed=True)
    site = serve.Site(lb, now=lambda: NOW)
    library = library_build.Library(lb)
    with pytest.raises(library_build.Sealed):
        library.put("/people", site.respond("/people"), "x")
    with pytest.raises(library_build.Sealed):
        library.drop(["/people"])
    with pytest.raises(library_build.Sealed):
        library.save()
    for tiers in (None, (1,), (1, 2)):
        with pytest.raises(library_build.Sealed):
            library_build.build(lb, serve.Site(lb, now=lambda: NOW, tiers=tiers))
    assert not library_build.folder_of(lb).exists()


def test_a_record_sealed_while_it_builds_keeps_nothing_it_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _record(tmp_path, monkeypatch, sealed=True, plain=True)
    site = serve.Site(lb, now=lambda: NOW)
    real = site.respond
    answered: list[str] = []

    def respond(path: str, query: str = "", if_none_match: str | None = None) -> serve.Response:
        answered.append(path)
        if len(answered) == len(library_build.DOORS) + 3:
            lb.set_meta(**{kept.PLAIN: False})  # the owner turns it off mid-build
        return real(path, query, if_none_match)

    monkeypatch.setattr(site, "respond", respond)
    with pytest.raises(library_build.Sealed):
        library_build.build(lb, site)
    assert not library_build.folder_of(lb).exists(), "the pages written before it are removed"
