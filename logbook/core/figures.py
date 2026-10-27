"""What a sentence counts (`figures`) and whether it sets a count beside a person (`beside_a_name`): the
one rule the dream holds a sentence to when it writes one (`logbook.contrib.dream.hold_numbers`,
`hold_names`) and every reader of a draft holds a stored sentence to when it prints one
(`drafts.hold_beside`), so a draft written before the rule, or by another writer, never prints a number
beside a name either (VISION: no metrics near people). Pure: text in, figures out."""

from __future__ import annotations

import re
from collections.abc import Collection

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# a figure: digits, a decimal point or comma and more digits, glued to a unit or not (`45min`, `7,5t`),
# never a piece of an id (`L12`, `6bc0`)
NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![.,]?\d)(?!\w*\d)")
MONTHS = (
    "january|february|march|april|june|july|august|september|october|november|december"
    "|januar|februar|mars|mai|juni|juli|oktober|desember"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|okt|nov|dec|des|(?-i:May)"  # `may`, lower-case, is a verb
)
# what a figure in a sentence may be without being a number: a date (ISO, `16.06.2026`, `16/6`), a
# clock (`19:30`, `kl. 19`, `9am`), an ISO week, a day of the month beside its month's name, an ordinal
CALENDAR = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:T[\d:]+(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|\b\d{4}-W\d{2}\b|\bW\d{1,2}\b|\b(?:week|uke|woche|semaine|semana)\s+\d{1,2}\b"
    r"|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b\d{1,2}:\d{2}\b|\b(?:kl\.?|klokka|klokken)\s*\d{1,2}(?:[:.]\d{2})?\b|\b\d{1,2}\s?(?:am|pm)\b"
    rf"|\b\d{{1,2}}(?:\.|st|nd|rd|th)?\s+(?:{MONTHS})\b|\b(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")  # a year, when it is one of the unit's (`figures`)
# numbers written in words, in the languages a draft is most often in: a word is a figure too
NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
    | {"ten": 10, "eleven": 11, "twelve": 12},
    "nb": {"to": 2, "tre": 3, "fire": 4, "fem": 5, "seks": 6, "sju": 7, "syv": 7, "åtte": 8, "ni": 9}
    | {"ti": 10, "elleve": 11, "tolv": 12},
}


def figures(
    text: str, calendar: bool = True, years: Collection[str] | None = None, language: str | None = None
) -> set[float]:
    """The numbers written in `text`: in figures, a decimal comma read as a point and a thousands
    comma dropped (`1,250`), and, in `language`, in words (`NUMBER_WORDS`). With `calendar`, dates,
    clocks, ISO weeks and days of the month beside their month are not numbers (`CALENDAR`), nor is a
    year: any (`YEAR`), or only one of `years` when they are given, so `2000 kroner` is a number."""
    if calendar:
        text = CALENDAR.sub(" ", text)
        text = YEAR.sub(lambda m: " " if years is None or m.group(0) in years else m.group(0), text)
    out: set[float] = set()
    for token in NUMBER.findall(text):
        if re.fullmatch(r"\d{1,3}(,\d{3})+", token):
            token = token.replace(",", "")
        try:
            out.add(float(token.replace(",", ".")))
        except ValueError:
            continue
    words = NUMBER_WORDS.get(language or "", {})
    if words:
        out |= {float(words[w]) for w in WORD.findall(text.lower()) if w in words}
    return out


def years_of(text: str) -> set[str]:
    """The years a unit's words name, each with the year before and after: years a sentence about the
    unit may write without writing a number (`figures`, `years`)."""
    return {str(y + d) for y in map(int, re.findall(r"\b(?:19|20)\d{2}\b", text)) for d in (-1, 0, 1)}


def beside_a_name(
    text: str, names: Collection[str], years: Collection[str] | None = None, language: str | None = None
) -> bool:
    """Whether `text` names one of `names` (their full name, or their first name of three letters or
    more, whole words, as written) and writes a figure (`figures`: dates, clock times and the unit's
    `years` are not figures), or sets any digit at all, a date's and a clock's included, beside the
    name with nothing but separators between them (`SEPARATORS`): a number beside a person."""
    found = {n.strip() for n in names if n and n.strip()}
    found |= {n.split()[0] for n in list(found) if len(n.split()[0]) >= 3}
    named = [name for name in found if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)]
    if not named:
        return False
    if any(adjacent(text, name) for name in named):
        return True
    return bool(figures(text, years=years, language=language))


# what may stand between a name and a digit and still leave them side by side: no letter, no word
SEPARATORS = "[\\s(:×x#·,\\-\u2013\u2014/|;=•.'\u2190\u2192]*"  # the dashes and arrows by code point


def adjacent(text: str, name: str) -> bool:
    """Whether a digit stands beside `name` in `text` with only `SEPARATORS` between them, on either
    side: `Ola Nordmann, 14:00`, `2026-06-17 · Ola`; `with Ola at 14:00` has a word between."""
    alt = re.escape(name)
    return (
        re.search(rf"\d{SEPARATORS}(?<!\w){alt}(?!\w)|(?<!\w){alt}(?!\w)\??{SEPARATORS}\d", text) is not None
    )
