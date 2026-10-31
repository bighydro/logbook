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
    """Whether `text` sets any digit at all, a date's and a clock's included, beside one of `names`
    (their full name, or their first name of three letters or more), in any case (`kari`, `KARI`),
    with nothing but separators
    between them, or none, whatever stands around the name (`adjacent`); or names one of them, no
    letter stuck to either end, and writes a figure anywhere (`figures`: dates, clock times and the
    unit's `years` are not figures): a number beside a person."""
    found = {n.strip() for n in names if n and n.strip()}
    found |= {n.split()[0] for n in list(found) if len(n.split()[0]) >= 3}
    if any(adjacent(text, name) for name in found):  # a digit against the name, whatever is around it
        return True
    named = [
        name
        for name in found
        if re.search(rf"{LETTER_BEFORE}{re.escape(name)}{LETTER_AFTER}", text, re.IGNORECASE)
    ]
    return bool(named) and bool(figures(text, years=years, language=language))


# what may stand between a name and a digit and still leave them side by side: no letter, no word
# (a bracket of either kind, a wikilink's too, and a quote as well: the owner, 27 October; guillemets,
# an ellipsis, a plus, a tilde, an underscore and the spaces of no width too)
SEPARATORS = (
    "[\\s()\\[\\]:×x#·,\\-\u2013\u2014/|;=•.'\"\u2018\u2019\u201c\u201d\u2190\u2192"
    "«»\u2039\u203a\u2026+~_\u200b\u200c\u200d\u2060\ufeff]*"
)


# where a name begins and ends when a sentence is read for it (`beside_a_name`'s figures): no letter
# before it, none after it; a digit may touch it (`Ola Nordmann2`), never a letter (`Olav`)
LETTER_BEFORE, LETTER_AFTER = r"(?<![^\W\d_])", r"(?![^\W\d_])"


# a name in another case as a word, but for the one letter that is a separator too, the `x` of `3x`
X_BEFORE, X_AFTER = r"(?<![^\W\d_xX])", r"(?![^\W\d_xX])"


def adjacent(text: str, name: str) -> bool:
    """Whether a digit stands beside `name` in `text` with only `SEPARATORS` between them, on either
    side: `Ola Nordmann, 14:00`, `2026-06-17 · Ola`, `8 June · Ola` (a date in words is one figure,
    `CALENDAR`), a digit stuck to it with nothing between, `Ola Nordmann2`, `3Ola`, or through a
    separator that is a letter, `3xOla`: no boundary is asked of the name as written. In any other
    case it is the name still, `kari 2026`, `2026 KARI` (`beside`), as a word: no letter touches it,
    so `granola 1` and `1 person` are no Ola and no Per. `with Ola at 14:00` has a word between; in
    `Olav 2` the `v` is no separator."""
    text = CALENDAR.sub(" 0 ", text)
    return re.search(beside(re.escape(name), SEPARATORS), text) is not None


def beside(names: str, separators: str) -> str:
    """The strong guard's pattern for `names` (an alternation, escaped): a digit, then nothing but
    `separators`, then a name; or a name, a `?` perhaps, `separators`, then a digit. A name as written
    asks no boundary (`3Ola`); a name in any other case (`kari`, `KARI`) is one when no letter touches
    it (`LETTER_BEFORE`, `LETTER_AFTER`) but the `x` on the digit's side (`3xkari`, `karix2`), so a
    lower-case name typed is caught and a word that holds one (`granola`) is not."""
    after = f"{X_BEFORE}(?:{names}){LETTER_AFTER}"  # after the digit: an `x` of a count may touch it
    before = f"{LETTER_BEFORE}(?:{names}){X_AFTER}"  # before the digit: `karix2` as `Karix2`
    return (
        rf"\d{separators}(?:{names})|(?:{names})\??{separators}\d"
        rf"|(?i:\d{separators}{after}|{before}\??{separators}\d)"
    )
