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
