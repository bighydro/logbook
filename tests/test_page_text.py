"""`page_text`: what a reader sees of a page, the words the Library's checks read when a page must never
say a number. The markup is the pages' own (the busy answer's kept form, an evidence row, the footer);
the ids in it are synthetic, and each holds the number a check looks for."""

from __future__ import annotations

import page_text
import pytest

UNSEEN = [
    '<input type="hidden" name="line" value="01a1455c-0d41-7503-b7bc-6e84e26be254">',  # a kept form's id
    '<li>at Home <a href="/day/2024-02-01">2024-02-01</a> <span class="id"'
    ' title="line 01a1455d-53f5-744d-8ea0-a879aa2025cc">…aa2025cc</span></li>',  # an evidence row
    "<footer>read-only · head <code>e1e9503a412b…</code> · Europe/Oslo</footer>",  # the record's head
    '<a href="/day/2025-09-04">the day</a>',  # a link's target
    "<style>main{max-width:503px}</style><script>const year = 2025;</script>",
    '<input type="checkbox" name="accept" value="503">',
]
SAID = [
    "<h1>503</h1>",
    '<p class="busy">Service unavailable (503).</p>',
    "<title>503 · Logbook</title>",
    '<input type="text" name="name" value="Gate 503" aria-label="the name">',  # a field shows its value
    '<textarea name="text" rows="6">The 503 to the harbour.</textarea>',
    "<details><summary>more</summary><p>503 days</p></details>",  # a closed disclosure's text too
    "<table><tr><td>12</td><td>503</td></tr></table>",  # a cell is a word apart from the one beside it
    "<p>Gate 5<sup>0</sup><u>3</u></p>",  # a line runs on through its inline elements
    '<input type="text" name="names" value="" placeholder="503 and the ferry">',  # an empty field's hint
]


@pytest.mark.parametrize("markup", UNSEEN)
def test_a_random_id_an_attribute_or_the_stylesheet_says_nothing(markup: str) -> None:
    assert not page_text.says(markup, "503") and not page_text.says(markup, "2025"), page_text.seen(markup)


@pytest.mark.parametrize("markup", SAID)
def test_a_number_the_page_says_is_seen(markup: str) -> None:
    assert page_text.says(markup, "503"), page_text.seen(markup)


def test_a_year_a_row_or_a_day_says_is_seen() -> None:
    assert page_text.says("<li><p><b>2025</b> · 10 days</p></li>", "2025")
    assert page_text.says('<li>at Home <a href="/day/2025-09-04">2025-09-04</a></li>', "2025")
    assert not page_text.says("<li><p><b>2024</b> · 10 days</p></li>", "2025")


# -- a year, a number or a date as a whole word, never inside a random id (#463's kind; the life door) --

PLANTED = [  # random on every run: each holds "2055" by chance, none says it
    "<footer>read-only · head <code>3c4aea205561…</code> · Europe/Oslo</footer>",  # the life door's failure
    '<li>a line <span class="id" title="line 019cadd3-2055-7dcd-95ae-05ae5ae1454f">…aa2055cc</span></li>',
    "<p>line 019cadd3-2055-7dcd-95ae-05ae5ae1454f</p>",  # a line id shown in full: a group is four digits
    '<a href="/line/019cadd3-2055-7dcd">a line</a> 019cadd3-1454-7dcd-95ae-2055…',  # ids cut short
    '<a href="/line/019cadd3-1454-7dcd-95ae-3c4aea205561">a line</a>',
    '<input type="hidden" name="reflection" value="' + "c" * 20 + "2055" + "d" * 24 + '">',  # a sealed token
    '<input type="text" name="name" value="3c4aea205561">',  # a field showing a digest
]
SHOWN = [  # the year where a reader meets it
    "<p>Your life, 2026 to 2055</p>",
    "<p>2055</p>",
    '<li><a href="/day/2055-03-01">2055-03-01</a></li>',
    "<p>(2055)</p>",
    "<p>the_2055 plan</p>",  # an underscore is no part of a number
    "<p>Gate 20<b>55</b></p>",  # a line runs on through its inline elements
    '<input type="text" name="name" value="Lofoten 2055">',
    "<details><summary>more</summary><p>in 2055</p></details>",
    "<p>head <code>3c4aea205561…</code>, then 2055</p>",  # an id beside the year hides nothing
    "<p>line 019cadd3-1454-7dcd-95ae-05ae5ae1454f in 2055</p>",
    "<p>2026-06-15 to 2055-01-01</p>",  # a date is no id
]
IN_THE_SOURCE = [  # not seen as text, but in the page's source as a value of its own: `holds` finds it
    '<a href="/life?at=2055">later</a>',
    '<span title="until 2055"></span>',
    "<script>const last = 2055;</script>",
    '<a href="/day/2055-03-01">a day</a>',
    '<a href="/day/2026-06-15?at=stay:owner:20550301T0900Z@59.9,10.7">a stay</a>',  # a compact stamp
    "<p>called 2055-1234-5678</p>",  # no line id
    "<p>2055-0930-1234</p>",
]


@pytest.mark.parametrize(
    "markup, word",
    [
        ("<p>22334455-1234</p>", "22334455"),
        ("<p>20260615-0930</p>", "20260615"),
        ("<p>22334455-1234-5678</p>", "22334455"),
    ],
)
def test_a_phone_number_or_a_time_shaped_like_part_of_an_id_is_still_read(markup: str, word: str) -> None:
    assert page_text.says(markup, word) and page_text.holds(markup, word), page_text.seen(markup)


def _old(page: str) -> bool:
    """The check the tests made before: the digits anywhere in the source."""
    return "2055" in page


@pytest.mark.parametrize("markup", PLANTED)
def test_a_year_by_chance_inside_a_random_id_is_neither_said_nor_held(markup: str) -> None:
    assert _old(markup), "the old form would have failed a right page here"
    assert not page_text.says(markup, "2055"), page_text.seen(markup)
    assert not page_text.holds(markup, "2055"), markup


@pytest.mark.parametrize("markup", SHOWN)
def test_a_year_a_reader_meets_is_said_and_held(markup: str) -> None:
    assert page_text.says(markup, "2055"), page_text.seen(markup)
    assert page_text.holds(markup, "2055") or "<b>" in markup, markup


@pytest.mark.parametrize("markup", IN_THE_SOURCE)
def test_a_year_in_a_link_an_attribute_or_the_script_is_held(markup: str) -> None:
    assert page_text.holds(markup, "2055"), markup
