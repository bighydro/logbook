"""The Library's first write act: `logbook serve`'s Places page names the places the record already
knows. The queue is `setup places review`'s, in its order, paged; each cluster's evidence is folded
(the addresses of one street one line, three lines shown, the rest behind a toggle); Name and Not a
place go through the review engine's own `accept` and `reject`, so `places.json`, the naming note and
`state/places-review.json` are what the CLI writes, byte for byte; a request from off this machine is
refused. The Day page links a stay printed as coordinates to its cluster. On the synthetic fortnight
at sea (`places_record`) and the Oslo persona, who does not exist."""

from __future__ import annotations

import http.client
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from persona import dwell, persona_record, photo, travel, utc
from places_record import BOATHOUSE, CABIN, DAYS, WORKSHOP, record

from logbook import cli
from logbook.contrib import places_review, serve
from logbook.core import places
from logbook.core.store import Logbook

REVIEW = serve.REVIEW_PATH
LOOPBACK = "127.0.0.1"


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("places-page") / "lb"
    record(root)
    return root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _page(site: serve.Site, query: str = "") -> str:
    response = site.respond("/places", query)
    assert response.status == 200, response.body[:200]
    return response.body.decode("utf-8")


def _post(site: serve.Site, client: str = LOOPBACK, origin: str | None = None, **form: str) -> serve.Response:
    return site.write(REVIEW, form, client, origin)


def _ids(text: str) -> list[str]:
    return re.findall(r'<li class="cluster" id="([^"]+)"', text)


def _cluster(text: str, cluster_id: str) -> str:
    """One cluster's markup (its id is also in the cluster before it, as its Skip link)."""
    rest = text[text.index(f'<li class="cluster" id="{cluster_id}"') :]
    return rest.split("</form>\n</li>")[0]


def _notes(root: Path) -> list[dict[str, Any]]:
    return [line for line in Logbook(root).lines() if line["kind"] == "note"]


def _state(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / "state" / "places-review.json").read_text(encoding="utf-8"))
    return data


# -- the page -----------------------------------------------------------------------------------------------


def test_the_places_page_is_the_named_places_then_the_queue_in_the_cli_s_order(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    site = serve.Site(lb)
    report = places_review.read(lb)
    text = _page(site)
    assert "Name this place" in text
    assert _ids(text) == [p.id for p in report.proposals], "the review queue, in its order"
    cli.main(["setup", "places", "review", "--top", "3"])
    printed = capsys.readouterr().out
    head = re.search(r"<h2>Name this place <small>(.*?)</small>", text)
    assert head is not None and "12 to review" in head.group(1) and "0 named" in head.group(1)
    first = _cluster(text, _ids(text)[0])
    for fact in ("6 visits", "6 nights", "91.5 h", f"2026-02-02 {places_review.EN_DASH} 2026-02-14"):
        assert fact in first and fact in printed, fact
    assert f'value="{CABIN}"' in first, "the field is prefilled with the best proposal"
    assert 'google-takeout timeline: "Home" (3 visits, type)' in first
    assert "<svg" in first and "</svg>" in first, "a dot on a plain canvas, drawn here"
    assert re.search(r'<button[^>]*name="act"[^>]*value="name"[^>]*>Name</button>', first)
    assert re.search(r'<button[^>]*name="act"[^>]*value="reject"[^>]*>Not a place</button>', first)
    third = _cluster(text, _ids(text)[2])
    assert 'value=""' in third, "a blank where no source names it"
    assert "no source names it" in third
    assert "name one below" in text, "an empty registry is an invitation, not a dead end"


def test_the_named_places_come_first_with_their_nights_and_last_visit(lb: Logbook) -> None:
    cabin = places_review.read(lb).proposals[0].id
    cli.main(["setup", "places", "review", "--accept", "1"])
    site = serve.Site(Logbook(lb.root))
    text = _page(site)
    named = text[: text.index("Name this place")]
    assert f"<td>{CABIN}</td>" in named
    row = named[named.index(f"<td>{CABIN}</td>") :].split("</tr>")[0]
    assert '<td class="num">6</td>' in row, "six nights"
    assert "2026-02-14" in row, "the last visit"
    assert cabin not in _ids(text), "named: out of the queue"
    assert "<td>Hytta" not in text[text.index("Name this place") :]


def test_the_queue_is_paged_twenty_at_a_time_with_more(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    assert serve.PAGE_SIZE == 20
    monkeypatch.setattr(serve, "PAGE_SIZE", 5)
    site = serve.Site(lb)
    report = places_review.read(lb)
    ids = [p.id for p in report.proposals]
    first = _page(site)
    assert _ids(first) == ids[:5]
    assert 'href="/places?page=2"' in first and "more" in first
    assert f'href="/places?page=1#{ids[1]}"' in first, "Skip is a link to the next cluster"
    second = _page(site, "page=2")
    assert _ids(second) == ids[5:10] and 'href="/places?page=3"' in second
    last = _page(site, "page=3")
    assert _ids(last) == ids[10:] and "?page=4" not in last
    assert _ids(_page(site, "page=9")) == ids[10:], "past the end: the last page"
    assert site.respond("/places", "page=0").status == 400
    assert site.respond("/places", "page=two").status == 400


def test_the_page_carries_one_inline_script_for_the_keys_and_nothing_fetched(lb: Logbook) -> None:
    response = serve.Site(lb).respond("/places", "")
    text = response.body.decode("utf-8")
    assert text.count("<script>") == 1 and "<script src" not in text
    script = re.search(r"<script>(.*?)</script>", text, re.S)
    assert script is not None and script.group(1) == serve.PLACES_SCRIPT
    csp = response.headers["Content-Security-Policy"]
    assert csp.startswith("default-src 'none'") and f"script-src '{serve.PLACES_SCRIPT_HASH}'" in csp
    for key in ("Enter", "n:", '" ":', "button[value=name]", "button[value=reject]", "a.skip"):
        assert key in serve.PLACES_SCRIPT
    assert "http" not in serve.PLACES_SCRIPT and "fetch" not in serve.PLACES_SCRIPT


# -- the evidence, folded ------------------------------------------------------------------------------------


STREET, NIGHTS = (56.2, 3.1), (56.22, 3.1)  # two spots in the North Sea, 2.2 km apart


def _street_record(root: Path) -> Logbook:
    """Six mornings at one spot in the North Sea, the nights 2 km north, Dawarich's geocoder
    writing a different house number of Plattformveien on five of the mornings and a name on the
    sixth; two photos there, one named by its library, one with a city only."""
    lb = Logbook.init(root, "Europe/Oslo")
    for n, day in enumerate(DAYS[:6], 1):
        points = dwell(day, "09:00", "12:00", STREET, every_min=10, noise_m=15)
        place = {"name": "Kaia"} if n == 6 else {"street": "Plattformveien", "housenumber": str(n)}
        for p in points:
            p["payload"]["extra"] = {"place": {**place, "city": "Nordsjøen", "countrycode": "XX"}}
        lb.append_many(
            [
                *travel(day, "08:30", "09:00", NIGHTS, STREET),
                *points,
                *travel(day, "12:00", "12:30", STREET, NIGHTS),
                *dwell(day, "12:30", "24:00", NIGHTS, every_min=15, noise_m=15),
                *dwell(DAYS[n], "00:00", "08:30", NIGHTS, every_min=15, noise_m=15),
            ]
        )
    named = photo(utc(DAYS[0], "10:00"), STREET, library="apple-photos")
    named["payload"]["extra"] = {"place": {"names": ["Brygga"]}}
    city = photo(utc(DAYS[1], "10:00"), STREET)
    city["payload"]["extra"] = {"place": {"city": "Nordsjøen"}}
    lb.append_many([named, city])
    return lb


def test_the_evidence_folds_a_street_s_addresses_into_one_line_and_shows_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = _street_record(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    nights, p = places_review.read(lb).proposals
    assert nights.observed.nights == 6 and p.observed.visits == 6 and p.observed.nights == 0
    assert len(p.observed.names) == 8, "five addresses, a name, a photo's name and a city"
    folded = places_review.groups(p.observed.names)
    assert [(g.name, g.count, g.addresses) for g in folded] == [
        ("Plattformveien", 5, 5),
        ("Brygga", 1, 0),
        ("Kaia", 1, 0),
        ("Nordsjøen", 1, 0),
    ]
    street = places_review.group_text(folded[0])
    assert street == 'dawarich: "Plattformveien" (5 addresses, 5 stays)'
    text = places_review.evidence_text(p.observed.names)
    assert text.startswith(street) and text.endswith("… and 1 more")
    assert 'apple-photos: "Brygga" (1 photo)' in text and "Plattformveien 1" not in text
    verbose = places_review.evidence_text(p.observed.names, verbose=True)
    assert "… and" not in verbose and all(
        f'"Plattformveien {n}" (1 stay, address)' in verbose for n in range(1, 6)
    )

    cli.main(["setup", "places", "review"])
    out = capsys.readouterr().out
    assert street in out and "… and 1 more" in out and "Plattformveien 1" not in out
    cli.main(["setup", "places", "review", "--verbose"])
    out = capsys.readouterr().out
    assert '"Plattformveien 3" (1 stay, address)' in out and "… and" not in out

    page = _page(serve.Site(lb))
    cluster = _cluster(page, p.id)
    shown = cluster[cluster.index('<ul class="evidence">') : cluster.index("<details>")]
    assert shown.count("<li>") == 3 and street in shown
    assert "<summary>… and 1 more</summary>" in cluster
    assert cluster.count('"Nordsjøen"') == 1 and cluster.index("… and 1 more") < cluster.index('"Nordsjøen"')
    assert "Plattformveien 1" not in page


def test_a_library_s_answer_renders_as_a_first_class_source_through_the_same_function() -> None:
    """What `--ask-photos` adds (origin `library`, #262) is a line like any other of the evidence,
    from the one rendering the CLI and the page share: counted by photo and labelled by library,
    its addresses folded by street as a line's are, and weighed into the three lines shown."""
    Name = places_review.Name
    library = [
        Name("library", "immich", "Havbyen", "city", 12, []),
        Name("library", "apple-photos", "Plattformen", "name", 3, []),
        Name("library", "apple-photos", "Bøyeveien 1", "address", 2, []),
        Name("library", "apple-photos", "Bøyeveien 2", "address", 1, []),
    ]
    lines = places_review.evidence_lines(library)
    assert lines == [
        "immich ×12: Havbyen",
        "photos ×3: Bøyeveien (2 addresses)",
        "photos ×3: Plattformen",
    ], "a city weighs 1 a photo, a Photos name or address 2: 12, then the street and the name at 6, by name"
    assert places_review.evidence_lines(library, verbose=True) == [
        "immich ×12: Havbyen",
        "photos ×3: Plattformen",
        "photos ×2: Bøyeveien 1",
        "photos ×1: Bøyeveien 2",
    ], "`--verbose`: every name on its own, as the names are ranked"
    mixed = [Name("timeline", "google-takeout", "Hytta", "name", 3, []), *library]
    text = places_review.evidence_text(mixed)
    assert text == (
        'immich ×12: Havbyen · google-takeout timeline: "Hytta" (3 visits)'
        " · photos ×3: Bøyeveien (2 addresses) · … and 1 more"
    )


def test_street_of_an_address() -> None:
    street = places_review.street_of
    assert street("Plattformveien 12") == "Plattformveien"
    assert street("Plattformveien 12B") == "Plattformveien"
    assert street("Plattformveien 12-14, Nordsjøen") == "Plattformveien"
    assert street("38 Bøyeveien, Nordsjøen") == "Bøyeveien"
    assert street("Bøyeveien") is None, "no house number: not an address to fold"
    assert street("12") is None and street("") is None


# -- the writes: one path, the CLI's -----------------------------------------------------------------------


def test_naming_through_the_page_writes_what_the_cli_writes_byte_for_byte(
    lb: Logbook, pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two copies of the record: `--name 1 "…"` on one, Name on the page on the other; then
    `--accept 2` against the page's prefilled field. `places.json` is the same file and the naming
    note the same line (its `at` aside: the clock)."""
    other = tmp_path / "other"
    shutil.copytree(pristine, other)
    site = serve.Site(lb)
    report = places_review.read(lb)
    first, second = report.proposals[0], report.proposals[1]
    before = _page(site)
    monkeypatch.setenv("LOGBOOK_HOME", str(other))
    cli.main(["setup", "places", "review", "--name", "1", "Hytta"])
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))

    response = _post(site, id=first.id, name="Hytta", page="1", act="name")
    assert response.status == 303 and response.location == f"/places?page=1#{second.id}"
    assert (lb.root / "places.json").read_bytes() == (other / "places.json").read_bytes()
    [mine], [theirs] = _notes(lb.root), _notes(other)
    assert mine["payload"] == theirs["payload"] and mine["payload"]["text"].startswith("named 55.6")
    assert (mine["source"], mine["kind"], mine["tier"]) == (theirs["source"], theirs["kind"], theirs["tier"])

    after = _page(site)
    assert after != before and "<td>Hytta</td>" in after and first.id not in _ids(after)
    assert _ids(after)[0] == second.id, "the page re-read the record after the write"
    assert site.respond("/places", "", if_none_match=site.respond("/places", "").etag).status == 304

    monkeypatch.setenv("LOGBOOK_HOME", str(other))
    cli.main(["setup", "places", "review", "--accept", "1"])
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    field = re.search(r'name="name" value="([^"]*)"', after)
    assert field is not None and field.group(1) == WORKSHOP
    _post(site, id=second.id, name=field.group(1), page="1", act="name")
    assert (lb.root / "places.json").read_bytes() == (other / "places.json").read_bytes()
    assert [n["payload"] for n in _notes(lb.root)] == [n["payload"] for n in _notes(other)]


def test_a_blank_name_takes_the_proposal_and_refuses_a_cluster_without_one(lb: Logbook) -> None:
    site = serve.Site(lb)
    report = places_review.read(lb)
    assert _post(site, id=report.proposals[0].id, name="   ", page="1", act="name").status == 303
    assert set(json.loads((lb.root / "places.json").read_text(encoding="utf-8"))) == {CABIN}
    blank = report.proposals[2]
    assert blank.name is None
    refused = _post(site, id=blank.id, name="", page="1", act="name")
    assert refused.status == 400 and "has no name" in refused.body.decode("utf-8")
    taken = _post(site, id=report.proposals[3].id, name=CABIN.lower(), page="1", act="name")
    assert taken.status == 400 and "already a place" in taken.body.decode("utf-8")
    assert len(_notes(lb.root)) == 1, "nothing else written"


def test_rejecting_through_the_page_lands_in_the_state_list_as_the_cli_writes_it(
    lb: Logbook, pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    shutil.copytree(pristine, other)
    site = serve.Site(lb)
    report = places_review.read(lb)
    fourth = report.proposals[3]
    seq = Logbook(lb.root).meta["seq"]
    response = _post(site, id=fourth.id, page="1", act="reject")
    assert response.status == 303 and response.location == f"/places?page=1#{report.proposals[4].id}"
    monkeypatch.setenv("LOGBOOK_HOME", str(other))
    cli.main(["setup", "places", "review", "--reject", "4"])
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    [mine], [theirs] = _state(lb.root)["rejected"], _state(other)["rejected"]
    assert {k: v for k, v in mine.items() if k not in ("rejected_at", "line")} == {
        k: v for k, v in theirs.items() if k not in ("rejected_at", "line")
    }
    assert mine["name"] == BOATHOUSE
    assert Logbook(lb.root).meta["seq"] == seq + 1, "one entity-review/v1 line (RFC 0037, decision 3)"
    after = _page(site)
    cluster = _cluster(after, fourth.id)
    assert f'value="{BOATHOUSE}"' not in cluster and 'value=""' in cluster, "its only name rejected: a blank"
    assert _post(site, id=fourth.id, page="1", act="reject").status == 303
    assert fourth.id not in _ids(_page(site)), "a rejected blank: out of the queue"


def test_a_stale_form_and_a_bad_one_write_nothing(lb: Logbook) -> None:
    site = serve.Site(lb)
    report = places_review.read(lb)
    gone = _post(site, id="place:78.2000,15.6000", page="1", act="name", name="Svalbard")
    assert gone.status == 409 and "not in the queue" in gone.body.decode("utf-8")
    assert _post(site, id=report.proposals[0].id, page="1", act="dance").status == 400
    assert _post(site, id=report.proposals[0].id, page="1").status == 400
    assert site.write("/places", {"act": "name"}, LOOPBACK, None).status == 404
    assert site.respond(REVIEW, "").status == 405
    assert not (lb.root / "places.json").exists() and not (lb.root / "state").exists()


def test_a_post_that_is_not_from_this_machine_is_refused(lb: Logbook) -> None:
    """The connection must come from this machine and the form from the server's own pages: any
    other client address, and any Origin a browser sends that is not 127.0.0.1, is a 403 and
    nothing is written. No Origin (a client that is not a browser, on this machine) passes."""
    site = serve.Site(lb)
    report = places_review.read(lb)
    form = {"id": report.proposals[0].id, "name": "Hytta", "page": "1", "act": "name"}
    for client in ("192.168.1.20", "10.0.0.5", "203.0.113.9", "::ffff:203.0.113.9", ""):
        response = site.write(REVIEW, form, client, None)
        assert response.status == 403, client
        assert "this machine" in response.body.decode("utf-8")
    for origin in ("http://example.org", "https://logbook.example.org", "http://localhost:8765", "null"):
        assert site.write(REVIEW, form, LOOPBACK, origin).status == 403, origin
    assert not (lb.root / "places.json").exists() and _notes(lb.root) == []
    assert site.write(REVIEW, form, LOOPBACK, "http://127.0.0.1:8765").status == 303
    second = {**form, "id": report.proposals[1].id, "name": "Verkstedet"}
    assert site.write(REVIEW, second, "::1", "http://[::1]:8765").status == 303
    third = {**form, "id": report.proposals[2].id, "name": "Base"}
    assert site.write(REVIEW, third, LOOPBACK, None).status == 303
    assert len(_notes(lb.root)) == 3


def test_the_form_round_trips_over_the_socket(lb: Logbook) -> None:
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        report = places_review.read(lb)
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=10)
        body = urlencode({"id": report.proposals[0].id, "name": "Hytta", "page": "1", "act": "name"})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://example.org"}
        connection.request("POST", REVIEW, body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 403 and reply.read()
        assert not (lb.root / "places.json").exists()
        headers["Origin"] = f"http://{LOOPBACK}:{port}"
        connection.request("POST", REVIEW, body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b""
        location = reply.getheader("Location") or ""
        assert location.startswith("/places?page=1#place:")
        assert set(json.loads((lb.root / "places.json").read_text(encoding="utf-8"))) == {"Hytta"}
        connection.request("GET", location.partition("#")[0])
        reply = connection.getresponse()
        page = reply.read().decode("utf-8")
        assert (
            reply.status == 200 and "<td>Hytta</td>" in page and f'id="{report.proposals[0].id}"' not in page
        )
        connection.request("GET", REVIEW)
        reply = connection.getresponse()
        assert reply.status == 405 and reply.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- the Day page ------------------------------------------------------------------------------------------


def test_the_day_page_links_a_stay_printed_as_coordinates_to_its_cluster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wednesday 10 June: lunch at the cafe, which is not in places.json. Its row carries the link;
    the office's and home's do not. The link lands on the Places page at the cafe's cluster."""
    lb = persona_record(tmp_path, monkeypatch)
    site = serve.Site(lb)
    text = site.respond("/day/2026-06-10", "").body.decode("utf-8")
    cafe = text[text.index("59.9200,10.7400") :].split("</li>")[0]
    assert '<a class="name" href="/places?at=59.9200,10.7400">name this place</a>' in cafe
    office = text[text.index("Office") :].split("</li>")[0]
    assert "name this place" not in office
    assert text.count("name this place") == 1 == text.count('<span class="kind">stay</span> 59.9200,10.7400')
    moved = site.respond("/places", "at=59.9200,10.7400")
    assert moved.status == 302 and moved.etag is None
    assert re.fullmatch(r"/places\?page=1#place:59\.92\d\d,10\.7\d\d\d", moved.location or "")
    page = moved.location.partition("#")[2]  # type: ignore[union-attr]
    assert f'id="{page}"' in site.respond("/places", "page=1").body.decode("utf-8")
    nowhere = site.respond("/places", "at=78.2,15.6")
    assert nowhere.status == 200 and "no place to name at 78.2000,15.6000" in nowhere.body.decode("utf-8")
    assert site.respond("/places", "at=north").status == 400
    static = serve.Site(lb, href=lambda path: None)
    assert "name this place" not in static.page_day("2026-06-10"), "a static page has nothing to submit to"


def test_the_stay_s_coordinates_in_the_link_are_the_row_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    text = serve.Site(lb).respond("/day/2026-06-10", "").body.decode("utf-8")
    for found in re.findall(r'href="/places\?at=([^"]+)"', text):
        lat, lon = places.parse_stay_id(found)
        assert f"{lat:.4f},{lon:.4f}" in text
        assert quote(found, safe=",.") == found
