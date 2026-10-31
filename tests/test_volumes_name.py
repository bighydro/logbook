"""Volumes is the name of the printed edition (RFC 0047 §10, the captain's answer of 23 October in §15):
the words a person reads say "a Volume" and "the Volume's pick", never "the paper edition" or "the
press". Words only: the commands, their flags, `docs/print.md` and the module names stay. The one page
the words reach, the Day's photo review, is held to every rule a door is: what it counts is what the
page's tiers give, no number touches a name, no pencil, no script, nothing fetched, and its answer
forbids every frame. On the Oslo persona's fortnight, who does not exist."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from persona import persona_record
from test_no_count_beside_a_name import beside

from logbook import cli
from logbook.contrib import serve
from logbook.core.store import Logbook

WEDNESDAY = "2026-06-10"
PRIVATE = "IMG_190000.HEIC"  # a tier-2 photo of Wednesday: no tier-1 page counts or names it
OLD = re.compile(r"paper edition|the press\b|press's|press picks", re.I)
REVIEW = re.compile(r'<section class="review">\n<h2 id="photos">Photo review</h2>.*?</section>', re.S)
ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    "ARCHITECTURE.md",
    "docs/acts.md",
    "docs/commands.md",
    "docs/letter.md",
    "docs/print.md",
    "docs/serve.md",
    "docs/tour.md",
    "docs/year.md",
)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        lb = persona_record(tmp_path_factory.mktemp("volumes"), mp)
        photo = next(line for line in lb.lines() if line["kind"] == "photo" and line["at"][:10] == WEDNESDAY)
        payload = {**photo["payload"], "asset_id": "p-private-1900", "raw_id": "p-private-1900"}
        lb.append(
            at=f"{WEDNESDAY}T17:00:00Z",
            source=photo["source"],
            kind="photo",
            tier=2,
            payload={**payload, "file_name": PRIVATE},
        )
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _review(response: serve.Response) -> str:
    assert response.status == 200, response.body[:200]
    found = REVIEW.search(response.body.decode("utf-8"))
    assert found is not None, "no photo review on the Day"
    return found.group(0)


@pytest.mark.parametrize(("tiers", "waiting"), [(None, 2), ((1, 2), 2), ((1,), 1)])
def test_the_photo_review_says_the_volume_s_pick_and_counts_only_the_photos_of_its_tiers(
    lb: Logbook, tiers: tuple[int, ...] | None, waiting: int
) -> None:
    response = serve.Site(lb, tiers=tiers).respond(f"/day/{WEDNESDAY}", "")
    review, page = _review(response), response.body.decode("utf-8")
    said = f"{waiting} photo{'s' if waiting != 1 else ''} of the day not starred"
    assert f"{said}: Star makes one the day's hero and the Volume's pick;" in review
    assert OLD.search(page) is None, "the old names are gone from the page"
    assert (PRIVATE in page) is (tiers != (1,)), "a tier-2 photo is neither counted nor named at tier 1"
    assert beside(review) == [] and beside(page) == []
    assert "<script" not in review and not re.search(r"\son[a-z]+=", review), "the review runs nothing"
    assert not re.search(r"(?:src|href|action)=\"(?:https?:)?//", review), "the review fetches nothing"
    assert "Pencil" not in review and "pencil" not in review, "the review is ink: the owner's photos"
    policy = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in [d.strip() for d in policy.split(";")]


def test_the_review_leaves_when_every_photo_is_starred_and_a_static_page_never_carries_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    for line in lb.lines():
        if line["kind"] == "photo" and line["at"][:10] == WEDNESDAY:
            cli.main(["star", line["id"]])
    capsys.readouterr()
    for site in (serve.Site(Logbook(lb.root)), serve.Site(Logbook(lb.root), href=lambda path: None)):
        page = site.respond(f"/day/{WEDNESDAY}", "") if not site.static else None
        text = page.body.decode("utf-8") if page is not None else site.page_day(WEDNESDAY)
        assert REVIEW.search(text) is None and "Volume's pick" not in text
        assert OLD.search(text) is None and beside(text) == []


def _said(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    try:
        cli.main(list(argv))
        code = 0
    except SystemExit as stop:
        code = int(stop.code or 0)
    out = capsys.readouterr()
    return code, out.out + out.err


def test_the_help_and_the_refusals_say_a_volume_and_keep_their_commands(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    code, star = _said(capsys, "star", "--help")
    assert code == 0 and "the Volume's pick" in star and OLD.search(star) is None
    code, year = _said(capsys, "show", "year", "--help")
    assert code == 0 and "--print" in year and "a Volume" in year and OLD.search(year) is None
    code, refused = _said(capsys, "show", "year", "2026", "--print")
    assert (code, refused) == (2, "year: --print writes a Volume where --html PATH says; give both\n")
    code, both = _said(capsys, "show", "year", "2026", "--poster", "--print")
    assert (code, both) == (2, "year: --poster is one sheet and --print a Volume; give one\n")


@pytest.mark.parametrize("doc", DOCS)
def test_the_docs_say_volumes_and_keep_the_print_page_where_it_is(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert OLD.search(text) is None, doc
    assert (ROOT / "docs" / "print.md").is_file() and not (ROOT / "docs" / "volumes.md").exists()
