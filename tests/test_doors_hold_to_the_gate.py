"""The readers the doors use hold to the page's gate (the privacy review of 26 October, its LATER list).

A tier is where a line may travel: 1 where the owner was, 2 what was said, 3 money and health. A page
read through a gate of tier N never shows, counts or hints at a line, a name or a count from above N.
Each test reads the same page of three records that differ only above a gate, and asserts the page is
the same: `ones` holds the tier-1 lines; `below` is a copy of it with the tier-2 lines appended; `whole`
is a copy of that with the tier-3 lines appended. Through a gate of tier 1, `whole` reads as `ones`;
through tiers 1 and 2, as `below`. The copies keep every line's id, so a page that differs has read
something above its gate. Then the words, ids and numbers of the lines above are looked for directly.

The people: Kari Nordmann, named by a tier-1 resolution and at dinner on a tier-1 calendar entry; Ola
Nordmann, named by a tier-2 resolution only, who wrote a tier-2 message; and Per Hemmelig, a person
only tier-3 lines know: his name, his message, the evening at the clinic with Kari. One tier-2 note and
one tier-3 note sit in years no other line has, so a year a filter offers can come only from them.
Nobody here exists: the addresses are at example.org."""

from __future__ import annotations

import difflib
import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, KARI_ID, OLA, OLA_ID, TZ, attendee, dwell, event, note, resolution, utc

from logbook.contrib import serve
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
DAYS = ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14"]
DINNER, OLA_WROTE, CLINIC = "2026-06-11", "2026-06-12", "2026-06-13"
OLD_TWO, OLD_THREE = "2024-03-03", "2025-03-03"  # the years only a tier-2 and a tier-3 note have
PER = "Per Hemmelig"
PER_EMAIL = "per.hemmelig@example.org"
PER_ID = "019cadd3-6bc0-7dcd-9133-0000000003e3"
TWO_WORD, THREE_WORD = "TOPAZ", "RUBY"  # in every tier-2 line's text, and in every tier-3 line's
T1, T12 = (1,), (1, 2)


def _message(at: str, text: str, tier: int, email: str, name: str) -> dict[str, Any]:
    payload = {
        "schema": "message/v1",
        "raw_id": f"m-{at}",
        "chat": {"id": f"chat-{name.casefold()}", "type": "direct", "name": name},
        "from_me": False,
        "text": text,
        "sender": {"kind": "email", "value": email, "name": name},
    }
    return {"at": at, "source": "whatsapp", "kind": "message", "tier": tier, "payload": payload}


def ones_lines() -> list[dict[str, Any]]:
    days = [line for d in DAYS for line in dwell(d, "00:00", "24:00", HOME)]
    return [
        {**resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"), "tier": 1},
        *days,
        event(utc(DINNER, "18:00"), utc(DINNER, "21:00"), "Dinner", [attendee(KARI["email"])]),
    ]


def two_lines() -> list[dict[str, Any]]:
    return [
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        _message(
            utc(OLA_WROTE, "19:00"), f"{TWO_WORD}: I will bring the charts tomorrow", 2, OLA["email"], "Ola"
        ),
        note(utc(OLA_WROTE, "20:00"), f"{TWO_WORD} I will send Kari the photos tomorrow"),
        note(f"{OLD_TWO}T12:00:00Z", f"{TWO_WORD} an old note about the boat"),
    ]


def three_lines() -> list[dict[str, Any]]:
    return [
        {**resolution(("email", PER_EMAIL), PER_ID, PER), "tier": 3},
        {
            **event(
                utc(CLINIC, "15:00"),
                utc(CLINIC, "17:00"),
                f"{THREE_WORD} clinic",
                [attendee(KARI["email"]), attendee(PER_EMAIL)],
            ),
            "tier": 3,
        },
        _message(
            utc(CLINIC, "18:00"), f"{THREE_WORD}: I will send the results tomorrow", 3, PER_EMAIL, "Per"
        ),
        _message(utc(CLINIC, "19:00"), f"{THREE_WORD}: the bill was 4000", 3, KARI["email"], "Kari"),
        {**note(utc(CLINIC, "20:00"), f"{THREE_WORD} I will pay Per Hemmelig back tomorrow"), "tier": 3},
        {**note(f"{OLD_THREE}T12:00:00Z", f"{THREE_WORD} an old note about the doctor"), "tier": 3},
    ]


def _three(base: Path, ones_of: list[Any], two_of: list[Any], three_of: list[Any]) -> dict[str, Logbook]:
    """`ones`, `below` (a copy of it, the tier-2 lines appended) and `whole` (a copy of that, the
    tier-3 lines appended), under `base`."""
    ones = Logbook.init(base / "ones", TZ)
    ones.append_many(ones_of)
    places = {"Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"}}
    (ones.root / "places.json").write_text(json.dumps(places), encoding="utf-8")
    policy = ones.root / "policy" / "crossing.json"
    policy.parent.mkdir(exist_ok=True)
    policy.write_text(json.dumps({"world": {"max_tier": 2}, "site": {"max_tier": 2}}), encoding="utf-8")
    shutil.copytree(ones.root, base / "below")
    Logbook(base / "below").append_many(two_of)
    shutil.copytree(base / "below", base / "whole")
    Logbook(base / "whole").append_many(three_of)
    return {name: Logbook(base / name) for name in ("ones", "below", "whole")}


@pytest.fixture(scope="module")
def records(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Logbook]:
    return _three(tmp_path_factory.mktemp("gate"), ones_lines(), two_lines(), three_lines())


def _reader(records: dict[str, Logbook], monkeypatch: pytest.MonkeyPatch, now: datetime = NOW) -> Any:
    """`read(name, tiers, address)`: the page `address` of record `name` through the gate `tiers`, its
    index in a folder of its own (the copies share the owner's id, the index's key)."""

    def read(name: str, tiers: tuple[int, ...], address: str) -> str:
        lb = records[name]
        monkeypatch.setenv("LOGBOOK_CACHE_HOME", str(lb.root.parent / f"cache-{name}"))
        path, _, query = address.partition("?")
        response = serve.Site(Logbook(lb.root), now=lambda: now, tiers=tiers).respond(path, query)
        return f"{response.status}\n{response.body.decode('utf-8')}"

    return read


@pytest.fixture
def at(records: dict[str, Logbook], monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    yield _reader(records, monkeypatch)


HEAD = re.compile(r"head <code>[0-9a-f]+…</code>")  # the chain's head: it moves with any line appended
# how far a page below the notes read, sealed (`serve._read_through`): it moves with any line appended,
# as the head does, and says no more (the Sign form's test below)
SEALED = re.compile(r'(name="reflection" value=")[0-9a-f]{48}(")')


def _plain(page: str) -> list[str]:
    """A page's lines, the head and the sealed seq aside: what moves with any line, whatever its tier."""
    return SEALED.sub(r"\1…\2", HEAD.sub("head", page)).splitlines()


def _same(at: Any, addresses: list[str]) -> None:
    """Each page through tier 1 of `whole` reads as of `ones`, and through tiers 1 and 2 as of `below`."""
    for tiers, lower in ((T1, "ones"), (T12, "below")):
        for address in addresses:
            got, want = _plain(at("whole", tiers, address)), _plain(at(lower, tiers, address))
            moved = [line[:300] for line in difflib.unified_diff(want, got, lineterm="", n=0)][2:12]
            assert got == want, (address, tiers, moved)


def _ids_above(records: dict[str, Logbook], tiers: tuple[int, ...]) -> list[str]:
    return [str(line["id"]) for line in records["whole"].lines() if int(line.get("tier") or 0) not in tiers]


def _absent(records: dict[str, Logbook], page: str, tiers: tuple[int, ...]) -> None:
    """Nothing of the lines above `tiers` on `page`: no name, no word of their text, no id."""
    words = [PER, "Hemmelig", PER_ID, PER_EMAIL, THREE_WORD]
    if 2 not in tiers:
        words += ["Ola Nordmann", OLA_ID, TWO_WORD]
    for word in words:
        assert word not in page, (word, tiers)
    for line_id in _ids_above(records, tiers):
        assert line_id not in page and line_id[-8:] not in page, (line_id, tiers)


def test_the_control_each_page_moves_without_its_gate(at: Any) -> None:
    """The records do differ where the tests below look: read every tier, the lines above are there."""
    assert at("whole", (1, 2, 3), "/shelves") != at("below", (1, 2, 3), "/shelves")
    assert THREE_WORD in at("whole", (1, 2, 3), f"/day/{CLINIC}")
    assert "2025" in at("whole", (1, 2, 3), "/search?q=note")


# -- 2. People: closeness, order, the last contact and the days together, from the gate's lines alone ----


def test_the_people_door_ranks_and_tells_from_the_lines_at_its_tiers(
    at: Any, records: dict[str, Logbook]
) -> None:
    """Kari's last real contact through tiers 1 and 2 is the dinner, not the evening at the clinic a
    tier-3 line puts her at; nor is she left with none because that line is the latest."""
    _same(at, ["/people", f"/people/{KARI_ID}", "/people?year=2026"])
    for tiers in (T1, T12):
        door = at("whole", tiers, "/people")
        _absent(records, door, tiers)
        assert "no real contact" not in door, tiers
        thread = at("whole", tiers, f"/people/{KARI_ID}")
        _absent(records, thread, tiers)
        assert CLINIC not in thread, tiers


HANSEN, HANSEN_EMAIL, HANSEN_ID = (
    "Per Hansen",
    "per.hansen@example.org",
    "019cadd3-6bc0-7dcd-9133-000000000004",
)


def test_the_days_reconnect_names_a_silence_the_lines_at_its_tiers_keep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Day's morning reconnect (`day_rhythm.drifted`): Per Hansen, named at tier 1, was at home
    with the owner on twenty days of 2024, on tier-1 calendar entries, and since then only a tier-2
    message has come from him, and a later tier-3 one. Through tier 1 he has drifted, the last contact
    a meeting in 2024; through tiers 1 and 2 the message ends the silence; the tier-3 message is no
    contact and ends no silence on either page."""
    days = [f"2024-{m:02d}-{d:02d}" for m in (3, 4, 5, 6) for d in (3, 10, 17, 24, 27)]
    seen = [
        line
        for day in days
        for line in (
            *dwell(day, "15:00", "20:00", HOME),
            event(utc(day, "16:00"), utc(day, "18:00"), "Sail", [attendee(HANSEN_EMAIL)]),
        )
    ]
    named = {**resolution(("email", HANSEN_EMAIL), HANSEN_ID, HANSEN), "tier": 1}
    ones = [*ones_lines(), named, *seen]
    two = [_message(utc(OLA_WROTE, "09:00"), f"{TWO_WORD}: the boat is in", 2, HANSEN_EMAIL, "Per")]
    three = [_message(utc(CLINIC, "09:00"), f"{THREE_WORD}: the results are in", 3, HANSEN_EMAIL, "Per")]
    morning = datetime(2026, 6, 17, 6, 0, tzinfo=UTC)  # with one person drifted, an even day's ordinal
    read = _reader(_three(tmp_path, ones, two, three), monkeypatch, morning)
    address = f"/day/{morning.date().isoformat()}?shape=morning"
    for tiers, lower in ((T1, "ones"), (T12, "below")):
        got, want = (_plain(read(name, tiers, address)) for name in ("whole", lower))
        moved = [line[:300] for line in difflib.unified_diff(want, got, lineterm="", n=0)][2:12]
        assert got == want, (tiers, moved)
    assert "you saw each other often" in read("whole", T1, address)
    assert "you saw each other often" not in read("whole", T12, address)
    assert THREE_WORD not in read("whole", T12, address)


# -- 3. The Day page's "with …": who was there, through the gate ------------------------------------------


def test_the_day_page_says_who_was_there_from_the_lines_at_its_tiers(
    at: Any, records: dict[str, Logbook]
) -> None:
    _same(at, [f"/day/{day}" for day in DAYS])
    for tiers in (T1, T12):
        _absent(records, at("whole", tiers, f"/day/{CLINIC}"), tiers)


def test_a_day_only_lines_above_the_gate_touch_reads_as_a_day_the_record_has_not(at: Any) -> None:
    """The Day of a date only a tier-3 (or tier-2) line is on says the record holds nothing for it,
    with the days the gate's own lines run over: the sentence is not dropped for a line it cannot read."""
    _same(at, [f"/day/{OLD_TWO}", f"/day/{OLD_THREE}"])
    for day in (OLD_TWO, OLD_THREE):
        assert f"The record holds nothing for {day}" in at("whole", T1, f"/day/{day}")
    assert f"The record holds nothing for {OLD_THREE}" in at("whole", T12, f"/day/{OLD_THREE}")


# -- 4. The pages that count: the shelves, the gaps and the gear's sources, the world, Life's bands -------


def test_the_shelves_count_only_the_lines_at_their_tiers(at: Any, records: dict[str, Logbook]) -> None:
    _same(at, ["/shelves"])
    n = {name: sum(1 for line in lb.lines() if int(line["tier"]) <= 2) for name, lb in records.items()}
    total = sum(1 for _ in records["whole"].lines())
    for tiers in (T1, T12):
        page = at("whole", tiers, "/shelves")
        assert f"{total:,} lines" not in page, tiers
        assert OLD_THREE not in page, tiers
    assert f"{n['below']:,} lines" in at("whole", T12, "/shelves") or n["below"] > 0
    assert OLD_TWO not in at("whole", T1, "/shelves")


def test_the_gaps_and_the_gears_sources_count_only_the_lines_at_their_tiers(
    at: Any, records: dict[str, Logbook]
) -> None:
    _same(at, ["/gaps", "/gaps?since=2026-06-01", "/gear/sources", "/gear"])
    page = at("whole", T1, "/gaps")
    assert "whatsapp" not in page  # its every line is a message: tier 2 or 3
    assert "manual" not in page  # the notes


def test_the_world_reads_and_counts_through_the_gate(at: Any, records: dict[str, Logbook]) -> None:
    """The world's own policy lets tier 2 go to it: through a gate of tier 1 it draws tier 1 alone, and
    what it says it held back are the lines at the gate's tiers it leaves out, never one above."""
    _same(at, ["/world", "/world?from=2026-06-10&to=2026-06-14"])
    one = at("whole", T1, "/world")
    assert '"tiers":[1]' in one
    assert "held back" not in one
    _absent(records, one, T1)
    _absent(records, at("whole", T12, "/world"), T12)


def test_lifes_bands_and_the_timeline_count_only_the_lines_at_their_tiers(at: Any) -> None:
    _same(
        at,
        [
            "/life",
            "/life?zoom=year&at=2026",
            f"/life?zoom=year&at={OLD_THREE[:4]}",
            "/life?zoom=month&at=2026-06",
            f"/life?zoom=day&at={CLINIC}",
            "/timeline",
            "/timeline/life",
            f"/timeline/year/{OLD_THREE[:4]}",
            "/days",
            "/week/2026-W24",
        ],
    )


# -- 5. Search and Ask: the hits, the year filters, the counts ---------------------------------------------


def test_search_and_ask_offer_only_the_years_and_hits_at_their_tiers(
    at: Any, records: dict[str, Logbook]
) -> None:
    addresses = [
        "/search?q=note",
        "/search?q=tomorrow",
        f"/search?q=note&year={OLD_THREE[:4]}",
        "/search?q=note&kind=note",
        "/ask?q=note",
        "/ask?q=tomorrow",
    ]
    _same(at, addresses)
    for tiers in (T1, T12):
        for address in addresses:
            _absent(records, at("whole", tiers, address), tiers)
        assert f"year={OLD_THREE[:4]}" not in at("whole", tiers, "/search?q=note"), tiers
    assert f"year={OLD_TWO[:4]}" not in at("whole", T1, "/search?q=note")


# -- the Day's Sign form, on a page that reads no notes ---------------------------------------------------

READ_THROUGH = re.compile(r'<input type="hidden" name="reflection" value="([^"]*)">')


def test_the_sign_form_of_a_page_below_the_notes_does_not_count_the_record(
    at: Any, records: dict[str, Logbook]
) -> None:
    """What the Sign form carries for the reflection a tier-1 page cannot show (`_read_through`, #436)
    is how far the page read, for Sign to tell a form older than the reflection apart: never that as a
    number a reader of the page can count the record's lines by, those above its gate among them."""
    seq = int(records["whole"].meta["seq"])
    page = at("whole", T1, f"/day/{CLINIC}")
    (token,) = READ_THROUGH.findall(page)
    assert token not in (f"{seq:016x}", f"{seq:x}", str(seq))
    assert f"{seq:x}" not in token and f"{seq:,}" not in page
    assert at("whole", T1, f"/day/{CLINIC}") == page  # the same page read again, the same form


# -- 6. GatedIndex: every index method the Library calls, through a tier-1 gate ----------------------------


def test_every_index_method_the_library_calls_holds_to_a_tier_one_gate(
    records: dict[str, Logbook], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MCP server's index (`GatedIndex`) over `whole` at tier 1 answers each method as the plain
    index of `ones` does: no line, id, row, kind or count of a line above the ceiling. The methods are
    those the Library's pages call (a crawl of every door through a gate, with each call recorded); the
    index's own bookkeeping (`indexed`, `appended`, `existing`, `matches`, `rebuild`, `add`, `close`)
    serves the writer and the kept readings, never a page, and is the record's whole by design."""
    from logbook.contrib import mcp_server
    from logbook.core import search

    whole, ones = records["whole"], records["ones"]
    monkeypatch.setenv("LOGBOOK_CACHE_HOME", str(whole.root.parent / "cache-gated"))
    gated = mcp_server.GatedLogbook(whole.root, mcp_server.Gate(1, set())).index()
    monkeypatch.setenv("LOGBOOK_CACHE_HOME", str(ones.root.parent / "cache-ones"))
    plain = Logbook(ones.root).index()
    every = range(1, int(whole.meta["seq"]) + 1)
    above = [line for line in whole.lines() if int(line["tier"]) > 1]
    keys = [
        (str(line["source"]), str(line["payload"]["raw_id"])) for line in above if "raw_id" in line["payload"]
    ]
    first, last = "2000-01-01", "2030-12-31"
    since, until = "2000-01-01T00:00:00Z", "2030-12-31T00:00:00Z"
    expression = search.expression("tomorrow OR note OR clinic OR dinner")
    assert expression is not None

    def hits(idx: Any) -> list[str]:
        return sorted(str(h.id) for h in idx.search(expression, 3, first, last, None, 50))

    def tally(idx: Any) -> int:
        counted, edges = idx.window_tally(since, until)
        return sum(n for _t, kind, n in counted if kind != "retraction") + sum(
            1 for p in edges if p.kind != "retraction"
        )

    asked = {
        "day": lambda idx: [idx.day(d) for d in (*DAYS, OLD_TWO, OLD_THREE)],
        "between": lambda idx: idx.between(first, last),
        "by_seq": lambda idx: [idx.by_seq(n) for n in every],
        "by_seqs": lambda idx: idx.by_seqs(every),
        "by_id": lambda idx: [idx.by_id(str(line["id"])) for line in above],
        "by_ids": lambda idx: idx.by_ids(str(line["id"]) for line in above),
        "ids": lambda idx: idx.ids(every),
        "by_kind": lambda idx: [idx.by_kind(k) for k in ("note", "message", "event", "resolution")],
        "of_kind": lambda idx: [list(idx.of_kind(k)) for k in ("note", "message", "event")],
        "stream": lambda idx: [list(idx.stream(k)) for k in ("note", "message", "event")],
        "of_source": lambda idx: idx.of_source("message", "whatsapp", first, last),
        "read": lambda idx: idx.read(
            idx.db.execute("SELECT file, offset FROM lines ORDER BY seq").fetchall()
        ),
        "lines_of": lambda idx: idx.lines_of(keys),
        "line_id": lambda idx: [idx.line_id(source, raw) for source, raw in keys],
        "holders": lambda idx: idx.holders(raw for _source, raw in keys),
        "resolutions": lambda idx: idx.resolutions(),
        "retractions": lambda idx: idx.retractions(),
        "superseded": lambda idx: [idx.superseded(k) for k in ("note", "message", "event")],
        "newest": lambda idx: [idx.newest("whatsapp", "message"), idx.newest("manual", "note")],
        "span": lambda idx: [idx.span(k) for k in (None, "note", "message", "event", "location")],
        "kind_names": lambda idx: idx.kind_names(),
        "kinds": lambda idx: idx.kinds(),
        "years": lambda idx: idx.years(),
        "totals": lambda idx: idx.totals(),
        "source_days": lambda idx: idx.source_days(first, last),
        "kind_source_days": lambda idx: idx.kind_source_days(first, last, ["note", "message", "event"]),
        "activity": lambda idx: idx.activity(first, last),
        "window": lambda idx: [p.seq for p in idx.window(since, until)],
        "window_tally": tally,
        "locations": lambda idx: idx.locations(first, last),
        "location_rows": lambda idx: idx.location_rows(first, last),
        "evidence": lambda idx: idx.evidence(["event", "message", "note"], first, last),
        "search": hits,
        "media_by_source": lambda idx: list(idx.media_by_source()),
        "attachment_counts": lambda idx: idx.attachment_counts(lambda digest: True),
    }
    try:
        moved = [name for name, ask in asked.items() if ask(gated) != ask(plain)]
        assert moved == [], ", ".join(moved)
    finally:
        gated.close()
        plain.close()
