"""What a page says of its tier is only what is true of the page: the tier its gate reads (`read at
tier N`), never `nothing read above tier N` from the highest tier among its lines, which understates
where a name on it came from (a person a tier-2 contact resolved, named on a page of tier-1 lines). A
page that read no lines says `no lines`. On the synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from logbook.contrib import demo, serve
from logbook.core.store import Logbook


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    with pytest.MonkeyPatch.context() as mp:
        root = tmp_path_factory.mktemp("gate-tier-said") / "Demo"
        mp.setenv("LOGBOOK_HOME", str(root))
        return demo.generate(Path(root), days=10)


@pytest.mark.parametrize(
    ("tiers", "said"),
    [
        (None, "read at tier 3"),
        ((1, 2), "read at tier 2"),
        ((1,), "read at tier 1"),
        ((1, 3), "read at tiers 1 and 3"),
        ((0, 1, 2), "read at tier 2"),
        ((3,), "read at tier 3 alone"),
        ((2, 3), "read at tiers 2 and 3"),
        ((0,), "read at tier 0"),
        ((), "read at no tier"),
    ],
)
def test_the_heading_says_the_gates_tier_whatever_its_lines_are(
    record: Logbook, tiers: tuple[int, ...] | None, said: str
) -> None:
    site = serve.Site(record, tiers=tiers)
    small = site.tier_small("2 promises", 1)  # every line the page read is tier 1
    assert small.endswith(f"2 promises · {said}</small>"), small
    assert "nothing read above" not in small
    assert site.tier_small("0 promises", None).endswith("0 promises · no lines</small>")


@pytest.mark.parametrize(("tiers", "said"), [(None, "read at tier 3"), ((1, 2), "read at tier 2")])
def test_a_page_says_the_tier_its_gate_reads(
    record: Logbook, tiers: tuple[int, ...] | None, said: str
) -> None:
    page = serve.Site(record, tiers=tiers).respond("/search", "q=kari").body.decode("utf-8")
    head = re.search(r"<h1>.*?</h1>", page, re.S)
    assert head is not None and head.group(0).endswith(f"{said}</small></h1>"), head
    assert "nothing read above" not in page


def test_the_tier_on_hover_is_the_gates() -> None:
    assert "gate" in serve.TIER_TITLE and "highest tier among the lines" not in serve.TIER_TITLE
    assert "tier 3" not in serve.TIER_TITLE  # a gated page never says the tier it does not read


@pytest.mark.parametrize(("tiers", "said"), [(None, "Read at tier 3."), ((1, 2), "Read at tier 2.")])
def test_the_ask_footer_says_the_gates_tier(
    record: Logbook, tiers: tuple[int, ...] | None, said: str
) -> None:
    """Ask's foot says the tier its gate reads, not `Nothing read above tier N` from its hits."""
    page = serve.Site(record, tiers=tiers).respond("/ask", "q=kari").body.decode("utf-8")
    foot = re.search(r'<p class="foot">(.*?)</p>', page, re.S)
    assert foot is not None and foot.group(1) == said, foot
    assert "Nothing read above" not in page
