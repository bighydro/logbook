"""Identity (RFC 0006: a raw line carries the ref its source gave, `{kind, value}`, and a resolution line
maps a ref to a person minted in this record; SPEC §3.2.2: the owner's identities are refs and their
closure over the resolution lines; `logbook/adapters/phone.py`: one phone normalisation for every
adapter, so the same number from two sources is one ref; `logbook/people_merge.py`: two spellings of
one phone number or one address, case aside, are the same person). Stated for any number in the
reserved ranges and any address at example.org, in any spelling: references that normalise equal
resolve to the same person, and references that differ after normalisation never collide."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from logbook import people, people_merge, resolve
from logbook.adapters import phone
from logbook.adapters.ios_contacts import _normalise as contact_normalise
from logbook.store import Logbook
from properties.common import CI

# Numbers come only from reserved fictional ranges: the UK 07700 900xxx range and the +47 9000 000x range
# of the project's RFC examples; nobody is reachable at any of them.
RANGES = {"44": ("7700900", 3), "47": ("9000000", 1)}
PUNCTUATION = " -.()"
PERSON = "019cadd3-6bc0-7dcd-9133-0000000000"


def person(n: int) -> str:
    return f"{PERSON}{n:02x}"


@st.composite
def numbers(draw: st.DrawFn) -> tuple[str, str]:
    """(country code, national number) in a reserved range."""
    cc = draw(st.sampled_from(sorted(RANGES)))
    stem, digits = RANGES[cc]
    return cc, stem + "".join(draw(st.lists(st.sampled_from("0123456789"), min_size=digits, max_size=digits)))


@st.composite
def spelled(draw: st.DrawFn, number: tuple[str, str], national: bool = True) -> str:
    """One spelling of the number: `+44 …`, `0044 …` or, when `national`, `07700 …`, with spaces, dashes,
    dots and parentheses anywhere between its characters and whitespace around it."""
    cc, local = number
    forms = [f"+{cc}{local}", f"00{cc}{local}", *([f"0{local}"] if national else [])]
    plain = draw(st.sampled_from(forms))
    out = draw(st.text(PUNCTUATION, max_size=2))
    for ch in plain:
        out += ch + draw(st.text(PUNCTUATION, max_size=2))
    return out


def e164(number: tuple[str, str]) -> str:
    return f"+{number[0]}{number[1]}"


addresses = st.from_regex(r"[a-z0-9]{1,8}(\.[a-z0-9]{1,8}){0,2}", fullmatch=True).map(
    lambda s: f"{s}@example.org"
)


@st.composite
def spelled_address(draw: st.DrawFn, address: str) -> str:
    """The address with any case and whitespace around it."""
    cased = "".join(ch.upper() if draw(st.booleans()) else ch for ch in address)
    return draw(st.text(" \t", max_size=2)) + cased + draw(st.text(" \t", max_size=2))


def resolution(seq: int, ref: tuple[str, str], entity: str, label: str) -> dict[str, Any]:
    """A resolution line as the record holds it (RFC 0006), the envelope fields the readers use."""
    return {
        "id": f"{PERSON[:-2]}{seq:04x}",
        "seq": seq,
        "at": "2026-06-01T08:00:00Z",
        "source": "manual",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": ref[0], "value": ref[1]},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": label,
        },
    }


def proposals(lines: list[dict[str, Any]], prefix: str) -> list[people_merge.Proposal]:
    """What `people merge` proposes over these resolution lines: the pure path, no record."""
    standing = resolve.standing(lines)
    identities = resolve.identities_from(lines)
    return people_merge.propose(people_merge.candidates_from(standing, identities, frozenset()), prefix)


# -- normalisation: one value for one identifier --------------------------------------------------------


@settings(CI, max_examples=150)
@given(numbers(), st.data())
def test_every_spelling_of_a_number_normalises_to_its_e164_form(
    number: tuple[str, str], data: st.DataObject
) -> None:
    """`phone.normalise`: spaces, dashes, dots and parentheses are dropped and `00` becomes `+`, so
    `+44 7700 900123`, `0044-7700-900123` and `(07700) 900123` with the dial prefix 44 are one ref
    value, E.164, and never flagged."""
    cc = number[0]
    assert phone.normalise(data.draw(spelled(number, national=False)), "") == (e164(number), False)
    assert phone.normalise(data.draw(spelled(number)), cc) == (e164(number), False)
    assert contact_normalise("phone", data.draw(spelled(number)), cc) == (e164(number), False)


@settings(CI, max_examples=150)
@given(numbers(), numbers(), st.data())
def test_two_numbers_never_normalise_to_the_same_value(
    a: tuple[str, str], b: tuple[str, str], data: st.DataObject
) -> None:
    """Two refs that differ after normalisation are two numbers: the normalised value is the number,
    so spellings of different numbers never meet, whatever the punctuation or prefix form."""
    spelling_a, spelling_b = data.draw(spelled(a)), data.draw(spelled(b))
    same = phone.normalise(spelling_a, a[0])[0] == phone.normalise(spelling_b, b[0])[0]
    assert same == (a == b)


@settings(CI, max_examples=150)
@given(addresses, addresses, st.data())
def test_an_address_is_one_ref_whatever_its_case_and_whitespace(a: str, b: str, data: st.DataObject) -> None:
    """RFC 0006 and `people_merge`: an email ref is the address lower-cased and trimmed, so two
    spellings are one ref and two addresses are two, as the contacts adapters write it, as `people
    merge` keys it, and as `logbook person <ref>` reads it."""
    sa, sb = data.draw(spelled_address(a)), data.draw(spelled_address(b))
    assert contact_normalise("email", sa, "") == (a, False)
    assert people_merge._email_key(("email", sa)) == ("email", a)
    as_handle = people_merge._email_key(("handle", sa))
    assert as_handle == ("email", a), "an address used as a handle is the address"
    assert people._refs_of(sa.strip())[0] == ("email", a)
    assert (people_merge._email_key(("email", sa)) == people_merge._email_key(("email", sb))) == (a == b)


# -- resolution: one person for one identifier ----------------------------------------------------------


def joined(found: list[people_merge.Proposal]) -> set[str]:
    """The entities one proposal joins; empty when nothing is proposed."""
    assert len(found) <= 1
    return {found[0].primary.entity, *(c.entity for c in found[0].secondary)} if found else set()


@settings(CI, max_examples=100)
@given(numbers(), numbers(), st.data())
def test_two_refs_that_normalise_equal_resolve_to_one_person_and_two_that_differ_never_collide(
    a: tuple[str, str], b: tuple[str, str], data: st.DataObject
) -> None:
    """RFC 0006 and `people_merge`: one source minted a person from the E.164 number; another wrote a
    ref of its own for a spelling of a number — the number as entered (an import without the dial
    prefix), punctuation and all (a hand resolution), or the WhatsApp JID that spells it — and minted
    a second person. The record proposes the two as one person exactly when the refs are of the same
    number; and when the second ref is the very same value, there is one ref and the last resolution
    wins (RFC 0006 rule 4). The dial prefix is the first number's country code."""
    spelling = data.draw(spelled(b))
    second = data.draw(
        st.sampled_from(
            [
                ("phone", spelling),
                ("phone", phone.normalise(spelling, "")[0]),
                ("handle", f"{b[0]}{b[1]}@s.whatsapp.net"),
            ]
        )
    )
    lines = [
        resolution(1, ("phone", e164(a)), person(1), "Kari Nordmann"),
        resolution(2, second, person(2), "Kari"),
    ]
    found = proposals(lines, a[0])
    if second == ("phone", e164(a)):
        assert found == [] and resolve.identities_from(lines)[second].entity == person(2)
    elif a == b:
        assert joined(found) == {person(1), person(2)}
        assert [(m.kind, m.value) for m in found[0].matches] == [("phone", e164(a))]
    else:
        assert found == []


@settings(CI, max_examples=100)
@given(addresses, addresses, st.data())
def test_two_spellings_of_an_address_resolve_to_one_person_and_two_addresses_never_collide(
    a: str, b: str, data: st.DataObject
) -> None:
    """The same for addresses: the ref a hand resolution spelled with capitals and the ref an import
    wrote lower-cased are one person; two addresses are never joined; the same value twice is one
    ref, last resolution wins."""
    second = ("email", data.draw(spelled_address(b)).strip())
    lines = [
        resolution(1, ("email", a), person(1), "Per Hansen"),
        resolution(2, second, person(2), "Per"),
    ]
    found = proposals(lines, "")
    if second == ("email", a):
        assert found == [] and resolve.identities_from(lines)[second].entity == person(2)
    elif a == b:
        assert joined(found) == {person(1), person(2)}
    else:
        assert found == []


@settings(CI, max_examples=20)
@given(addresses, addresses, numbers(), st.data())
def test_a_person_is_found_by_any_spelling_of_their_ref_and_never_by_another_persons(
    tmp_path_factory: pytest.TempPathFactory, a: str, b: str, number: tuple[str, str], data: st.DataObject
) -> None:
    """`logbook person <ref>` (§3.2.2: names come from the resolution lines): an address in any case,
    with whitespace around it, or a `+` number with spaces, finds the person it resolves to; a second
    person's address finds the second person, never the first."""
    lb = Logbook.init(tmp_path_factory.mktemp("lb") / "lb", "Europe/Oslo")
    ids = {}
    for n, (kind, value, label) in enumerate(
        (
            (("email", a, "Kari Nordmann")),
            ("phone", e164(number), "Kari Nordmann"),
            ("email", b, "Ola Nordmann"),
        ),
        1,
    ):
        if (kind, value) in ids:
            continue
        line = resolution(n, (kind, value), person(1 if label.startswith("Kari") else 2), label)
        lb.append(**{k: line[k] for k in ("at", "source", "kind", "tier", "payload")})
        ids[(kind, value)] = person(1 if label.startswith("Kari") else 2)
    report = people.read(lb, "2026-06-01", "2026-06-01")
    assert people.find(data.draw(spelled_address(a)), report).entity == person(1)
    spaced = e164(number)[:3] + " " + e164(number)[3:7] + " " + e164(number)[7:]
    assert people.find(spaced, report).entity == person(1)
    assert people.find(data.draw(spelled_address(b)), report).entity == ids[("email", b)]
    if a != b:
        assert people.find(b.upper(), report).entity == person(2)
