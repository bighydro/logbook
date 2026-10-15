"""`phone_width.py`, the check that holds `serve`'s pages to a phone's 400 px column without a
browser, held in turn to small pages a phone would scroll sideways for: each fault is found, and
the same page without it passes. A stylesheet the check cannot read is an error, never a pass."""

from __future__ import annotations

import phone_width
import pytest

PHONE = "body{margin:0}@media (max-width:40rem){details{margin-left:1rem}}"
NESTED = "<details><summary>evidence</summary><details><input></details></details>"
WIDE_DETAILS = "body{margin:0}details{margin-left:7.5rem}input{min-width:16rem}"


def _page(css: str, body: str) -> str:
    return f"<!doctype html><html><head><style>{css}</style></head><body>{body}</body></html>"


@pytest.mark.parametrize(
    ("css", "body", "found"),
    [
        ("div{width:30rem}", "<div>x</div>", "480 px, past the column (fixed by width 30rem)"),
        ("div{min-width:420px}", "<div>x</div>", "420 px, past the column (fixed by min-width 420px)"),
        ("div{width:100%;margin-left:2rem}", "<div>x</div>", "432 px, past the column"),
        ("", '<div style="width:500px">x</div>', "500 px, past the column"),
        ("div{padding:0 3rem}input{min-width:20rem}", "<div><input></div>", "div > input: 432 px"),
        (
            "div{display:grid;grid-template-columns:10rem 10rem 6rem;gap:1rem}",
            "<div><a>a</a><a>b</a><a>c</a></div>",
            "448 px, past the column (a grid of 3 columns, 10rem 10rem 6rem)",
        ),
        (
            "td{white-space:nowrap}",
            "<table><tr><td>2022-01-03 to 2022-03-31</td><td>2022-11-03 to 2023-07-31</td></tr></table>",
            "a table row of 2 cells",
        ),
        ("div{display:flex}a{min-width:9rem}", "<div><a>a</a><a>b</a><a>c</a></div>", "3 items side by side"),
        ("span{white-space:nowrap}", f"<p><span>{'Bergen ' * 8}</span></p>", "the text 'Bergen Bergen"),
        ("", f"<p>{'x' * 60}</p>", "the text 'xxxx"),
        ("", '<img src="/a.jpg" alt="">', "img: no max-width keeps it inside the column"),
        ("", "<pre>x</pre>", "pre: no max-width keeps it inside the column"),
        ("", '<svg width="600" viewBox="0 0 600 10"></svg>', "svg: 600 px, past the column"),
    ],
)
def test_a_fault_a_phone_would_scroll_for_is_found(css: str, body: str, found: str) -> None:
    problems = phone_width.problems(_page(PHONE + css, body))
    assert any(found in p for p in problems), problems


def test_the_same_pages_without_the_fault_pass() -> None:
    assert phone_width.problems(_page(PHONE, "<p>a few words</p>")) == []
    assert phone_width.problems(_page(PHONE + "div{width:20rem}", "<div>x</div>")) == []
    assert (
        phone_width.problems(
            _page(
                PHONE + "div{display:flex;flex-wrap:wrap}a{min-width:9rem}",
                "<div><a>a</a><a>b</a><a>c</a></div>",
            )
        )
        == []
    )
    assert phone_width.problems(_page(PHONE + "p{overflow-wrap:anywhere}", f"<p>{'x' * 60}</p>")) == []
    held = "img,pre{max-width:100%}pre{overflow-x:auto}svg{width:100%;max-width:40rem}"
    body = f'<img src="/a.jpg" alt=""><pre>{"x" * 80}</pre><svg viewBox="0 0 600 10"></svg>'
    assert phone_width.problems(_page(PHONE + held, body)) == []


def test_the_phone_breakpoint_is_what_holds_a_nested_disclosure_in() -> None:
    with_it = WIDE_DETAILS + "@media (max-width:40rem){details{margin-left:1rem}}"
    assert phone_width.phone_breakpoints(with_it) == ["(max-width:40rem)"]
    assert phone_width.problems(_page(with_it, NESTED)) == []
    only_dark = WIDE_DETAILS + "@media (prefers-color-scheme:dark){a{color:#8fb8d6}}"
    assert phone_width.phone_breakpoints(only_dark) == []
    assert phone_width.problems(_page(only_dark, NESTED)) == [
        "no @media rule lays the page out 400 px wide",
        "body > details > details > input: 512 px, past the column (fixed by min-width 16rem)",
    ]


@pytest.mark.parametrize(
    "css",
    [
        "a + b{width:1px}",
        "a:not(.x){width:1px}",
        "@supports (display:grid){a{width:1px}}",
        "a{width:calc(1px + 2px)}",
    ],
)
def test_a_stylesheet_the_check_cannot_read_is_an_error(css: str) -> None:
    with pytest.raises(ValueError, match="the width check does not read"):
        phone_width.problems(_page(PHONE + css, "<a>x</a>"))
