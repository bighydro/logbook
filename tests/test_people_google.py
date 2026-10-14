"""`logbook people review --from-google`: the owner's Google contacts and other contacts as a name source for
the review, read on the one Google key (People API v1, read-only), cached in state/ for a day. A contact is
evidence for a pair and a name the owner may give an observed person; it never becomes a line, nothing is
merged unless the owner says so, and contacts that share an address or a number are proposed as one.

The review fixture (`review_people.py`, 25 people who do not exist) and the in-process Google fake
(`google_fake.py`): Maren (group C, her number placed, her address not), Jakob and Nora (group D, nobody
placed them), Kari (group A, placed). Nothing leaves the process."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google_fake import CONTACTS_SCOPE, OTHER_CONTACTS_SCOPE, USER, Fake, private_key, write_key
from review_people import PEOPLE, review_record

from logbook import cli
from logbook.contrib import google_contacts, people_review
from logbook.contrib.adapters import service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
MAREN, JAKOB, NORA, KARI = PEOPLE[19], PEOPLE[24], PEOPLE[25], PEOPLE[1]
UNSEEN = "jakob@example.org"  # an address of Jakob's contact the record never saw
PHOTO = "https://photos.example.org/c102.jpg"


def _person(
    resource: str,
    name: str | None = None,
    emails: tuple[str, ...] = (),
    phones: tuple[tuple[str, str | None], ...] = (),
    photo: str | None = None,
) -> dict[str, Any]:
    """A People API person as the fields names,emailAddresses,phoneNumbers,photos return it."""
    found: dict[str, Any] = {"resourceName": resource, "etag": "%EgUBAi43PRoEAQIFByIM"}
    if name:
        found["names"] = [{"displayName": name, "metadata": {"primary": True}}]
    if emails:
        found["emailAddresses"] = [
            {"value": e, "metadata": {"primary": n == 0}} for n, e in enumerate(emails)
        ]
    if phones:
        found["phoneNumbers"] = [
            {"value": value, **({"canonicalForm": e164} if e164 else {})} for value, e164 in phones
        ]
    found["photos"] = (
        [{"url": photo}] if photo else [{"url": "https://photos.example.org/a.png", "default": True}]
    )
    return found


def _contacts() -> list[dict[str, Any]]:
    return [
        _person("people/c101", "Maren Eide", (MAREN["email"],), (("07700 900119", MAREN["phone"]),)),
        _person("people/c102", "Jakob Holm", (JAKOB["email"], UNSEEN), photo=PHOTO),
        _person("people/c103", "Nora Aas", phones=(("07700 900125", NORA["phone"]),)),
        _person("people/c104", "Kari Nordmann", (KARI["email"],), ((KARI["phone"], KARI["phone"]),)),
    ]


def _other_contacts() -> list[dict[str, Any]]:
    return [
        _person("otherContacts/c201", "J. Holm", ("Jakob.Holm@example.org",), (("+44 7700 900124", None),)),
        _person("otherContacts/c202", None, (NORA["email"],)),
        _person("otherContacts/c203", "Nora Aas", phones=((NORA["phone"], NORA["phone"]),)),
    ]


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, contacts=_contacts(), other_contacts=_other_contacts())
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return review_record(tmp_path, monkeypatch)


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main([*args])
    except SystemExit as e:
        code = int(e.code or 0)
    else:
        code = 0
    out, err = capsys.readouterr()
    return code, out, err


def _review(capsys: pytest.CaptureFixture[str], *more: str) -> dict[str, Any]:
    code, out, err = _cli(capsys, "people", "review", "--from-google", "--json", *more)
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def _key(p: dict[str, Any]) -> tuple[str, str]:
    return p["observed"]["key"]["kind"], p["observed"]["key"]["value"]


def _naming(data: dict[str, Any]) -> dict[tuple[tuple[str, str], str], dict[str, Any]]:
    return {
        (_key(p), p["contact"]["name"] + "/" + p["contact"]["book"]): p
        for p in data["proposals"]
        if "contact" in p
    }


def _number(data: dict[str, Any], key: tuple[str, str], contact: str) -> str:
    return str(_naming(data)[(key, contact)]["number"])


def _record_text(lb: Logbook) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((lb.root / "logbook").rglob("*.jsonl")))


# -- the proposals --------------------------------------------------------------------------------------


def test_a_contact_names_observed_people_with_the_evidence_and_nothing_is_written(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    data = _review(capsys)
    assert lb.meta["seq"] == seq, "proposing writes nothing"
    naming = _naming(data)
    jakob_mail, jakob_phone = ("email", JAKOB["email"]), ("phone", JAKOB["phone"])
    nora_mail, nora_phone = ("email", NORA["email"]), ("phone", NORA["phone"])
    assert {k: (p["score"], p["evidence"]) for k, p in naming.items()} == {
        (jakob_mail, "Jakob Holm/contacts"): (80, [f"same email {JAKOB['email']}", "same name Jakob Holm"]),
        (jakob_mail, "J. Holm/other contacts"): (
            80,
            [f"same email {JAKOB['email']}", "same name Jakob Holm ~ J. Holm"],
        ),
        (jakob_phone, "J. Holm/other contacts"): (50, [f"same phone {JAKOB['phone']}"]),
        (nora_mail, "Nora Aas/contacts"): (20, ["same name Nora Aas"]),
        (nora_mail, "Nora Aas/other contacts"): (20, ["same name Nora Aas"]),
        (nora_phone, "Nora Aas/contacts"): (50, [f"same phone {NORA['phone']}"]),
        (nora_phone, "Nora Aas/other contacts"): (50, [f"same phone {NORA['phone']}"]),
    }, "a contact touching a placed person (Maren's, Kari's) names nobody new; one with no name neither"
    for p in naming.values():
        assert p["canonical"] is None and set(p["contact"]) == {"name", "book", "photo"}
    assert naming[(jakob_mail, "Jakob Holm/contacts")]["contact"]["photo"] is True, (
        "a reference, never fetched"
    )
    assert len(data["proposals"]) == 15 + 7, "the queue as before, and the contacts' proposals"
    assert [p["number"] for p in data["proposals"]] == list(range(1, 23))
    scores = [p["score"] for p in data["proposals"]]
    assert scores == sorted(scores, reverse=True), "one queue, ranked by the evidence"


def test_a_contact_that_holds_both_identifiers_is_evidence_for_the_pair(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {_key(p): p for p in json.loads(_cli(capsys, "people", "review", "--json")[1])["proposals"]}
    after = {_key(p): p for p in _review(capsys)["proposals"] if p["canonical"] is not None}
    maren = ("email", MAREN["email"])
    assert before[maren]["score"] == 22 and after[maren]["score"] == 72
    assert after[maren]["evidence"] == [
        "same name Maren Eide",
        f"Google contact Maren Eide has {MAREN['email']} and {MAREN['phone']}",
        "together on 1 day",
    ]
    assert after[maren]["id"] == before[maren]["id"], (
        "the same pair, the same id: --accept acts on it as before"
    )
    assert {k: p["score"] for k, p in before.items() if k != maren} == {
        k: p["score"] for k, p in after.items() if k != maren
    }


def test_contacts_that_share_an_address_or_a_number_are_proposed_as_one(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _review(capsys)
    assert data["contacts"]["duplicates"] == [
        {
            "contacts": [
                {"name": "J. Holm", "book": "other contacts", "photo": False},
                {"name": "Jakob Holm", "book": "contacts", "photo": True},
            ],
            "evidence": [f"same email {JAKOB['email']}"],
        },
        {
            "contacts": [
                {"name": "Nora Aas", "book": "contacts", "photo": False},
                {"name": "Nora Aas", "book": "other contacts", "photo": False},
            ],
            "evidence": [f"same phone {NORA['phone']}"],
        },
    ]
    _code, out, _err = _cli(capsys, "people", "review", "--from-google")
    lines = out.splitlines()
    at = lines.index(next(x for x in lines if x.startswith("2 groups of duplicate contacts")))
    assert "merge in Google Contacts" in lines[at] and "the key only reads" in lines[at]
    assert lines[at + 1] == f"  J. Holm ↔ Jakob Holm: same email {JAKOB['email']}"
    assert lines[at + 2] == f"  Nora Aas ↔ Nora Aas: same phone {NORA['phone']}"
    assert lines[-1].startswith("nothing written: `people review --from-google --accept")


def test_the_contacts_read_are_counted_and_never_printed_in_full(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _err = _cli(capsys, "people", "review", "--from-google")
    assert code == 0
    assert "google contacts: 4 contacts, 3 other contacts, read " in out and "kept 24 h in state/" in out
    as_json = json.dumps(_review(capsys))
    for text in (out, as_json):
        assert UNSEEN not in text and PHOTO not in text, (
            "a contact's other identifiers and its photo stay out"
        )
        assert "people/c1" not in text and "otherContacts/" not in text, "and its resource name"
    assert json.loads(as_json)["contacts"]["books"] == {"contacts": 4, "other contacts": 3}


# -- the owner's say --------------------------------------------------------------------------------------


def test_accepting_a_contact_writes_the_name_and_the_identifiers_seen_and_nothing_else(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _review(capsys)
    n = _number(data, ("email", JAKOB["email"]), "Jakob Holm/contacts")
    seq = lb.meta["seq"]
    code, out, err = _cli(capsys, "people", "review", "--from-google", "--accept", n)
    assert code == 0, err
    assert out.startswith(f"accepted {JAKOB['email']} → Jakob Holm, new (Google contacts): 1 line")
    (line,) = [x for x in lb.lines() if x["seq"] > seq]
    payload = line["payload"]
    assert (line["source"], line["kind"], line["tier"]) == ("manual", "resolution", 2)
    assert payload["ref"] == {"kind": "email", "value": JAKOB["email"]} and payload["label"] == "Jakob Holm"
    assert payload["entity"]["type"] == "person" and payload["entity"]["registry"] == "logbook"
    assert payload["method"] == "owner" and payload["extra"]["named_from"] == "google contacts"
    text = _record_text(lb)
    assert UNSEEN not in text and PHOTO not in text and "people/c102" not in text, "no contact becomes a line"
    _code, listed, _err = _cli(capsys, "people")
    assert "Jakob Holm" in listed, "a person of the record now"
    again = _review(capsys)
    phone = next(p for p in again["proposals"] if _key(p) == ("phone", JAKOB["phone"]))
    assert phone["canonical"] == {"id": payload["entity"]["id"], "name": "Jakob Holm"}
    assert f"Google contact J. Holm has {JAKOB['phone']} and {JAKOB['email']}" in phone["evidence"], (
        "his other contact now links his number to the person just named"
    )
    assert not any(_key(p)[1] == JAKOB["email"] for p in again["proposals"]), "placed: proposed no more"


def test_one_contact_accepted_twice_in_a_run_is_one_person(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _review(capsys)
    both = [
        _number(data, ("email", JAKOB["email"]), "J. Holm/other contacts"),
        _number(data, ("phone", JAKOB["phone"]), "J. Holm/other contacts"),
    ]
    seq = lb.meta["seq"]
    code, _out, err = _cli(capsys, "people", "review", "--from-google", "--accept", ",".join(both))
    assert code == 0, err
    written = [x for x in lb.lines() if x["seq"] > seq]
    assert len(written) == 2 and len({x["payload"]["entity"]["id"] for x in written}) == 1
    assert {x["payload"]["label"] for x in written} == {"J. Holm"}


def test_two_contacts_for_one_observed_person_are_never_both_accepted(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _review(capsys)
    jakob = ("email", JAKOB["email"])
    both = [_number(data, jakob, "Jakob Holm/contacts"), _number(data, jakob, "J. Holm/other contacts")]
    seq = lb.meta["seq"]
    code, _out, err = _cli(capsys, "people", "review", "--from-google", "--accept", ",".join(both))
    assert code == 2 and "with two people" in err
    assert lb.meta["seq"] == seq, "nothing auto-merged, nothing written"


def test_rejecting_a_contact_writes_no_line_and_it_does_not_come_back(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _review(capsys)
    nora = ("phone", NORA["phone"])
    p = _naming(data)[(nora, "Nora Aas/contacts")]
    seq = lb.meta["seq"]
    code, out, err = _cli(capsys, "people", "review", "--from-google", "--reject", str(p["number"]))
    assert code == 0, err
    assert "no line, a contact is not in the record" in out
    assert lb.meta["seq"] == seq
    kept = (lb.root / "state" / "google-contacts-review.json").read_text(encoding="utf-8")
    assert p["id"] in kept and "Nora" not in kept and NORA["phone"] not in kept, "a digest that names no one"
    again = _naming(_review(capsys))
    assert (nora, "Nora Aas/contacts") not in again and (nora, "Nora Aas/other contacts") in again


def test_without_from_google_the_review_is_as_it_was_and_google_is_not_asked(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(_cli(capsys, "people", "review", "--json")[1])
    assert len(data["proposals"]) == 15 and "contacts" not in data
    assert all("contact" not in p for p in data["proposals"])
    assert fake.requests == []


# -- the cache, the key, the API ------------------------------------------------------------------------


def test_the_contacts_are_kept_in_state_for_a_day_then_read_again(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _review(capsys)
    asked = len(fake.requests)
    cache = lb.root / "state" / "google-contacts.json"
    assert cache.is_file() and json.loads(cache.read_text(encoding="utf-8"))["user"] != USER
    if os.name == "posix":
        assert stat.S_IMODE(cache.stat().st_mode) == 0o600, "the owner's alone"
    assert _review(capsys)["contacts"]["cached"] is True
    assert len(fake.requests) == asked, "within the day, Google is not asked"
    later = datetime.now(UTC) + google_contacts.TTL + timedelta(hours=1)
    monkeypatch.setattr(google_contacts, "_now", lambda: later)
    assert _review(capsys)["contacts"]["cached"] is False
    assert len(fake.requests) > asked


def test_a_cache_read_as_another_user_is_not_used(lb: Logbook, fake: Fake) -> None:
    account = service_account.configure(os.environ)
    assert account is not None
    google_contacts.load(lb.root, account)
    other = service_account.Account(account.key_file, account.client_email, "ola@example.org")
    fetched: list[str] = []

    def fetch(who: service_account.Account) -> tuple[list[google_contacts.Contact], list[str]]:
        fetched.append(who.user)
        return [], []

    assert google_contacts.load(lb.root, other, fetch=fetch).contacts == ()
    assert fetched == ["ola@example.org"]


def test_both_books_are_read_page_by_page_and_only_read(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.page = 2
    data = _review(capsys)
    assert data["contacts"]["books"] == {"contacts": 4, "other contacts": 3}
    connections = fake.calls("people.googleapis.com/v1/people/me/connections")
    others = fake.calls("people.googleapis.com/v1/otherContacts")
    assert [c.get("pageToken") for c in connections] == [None, "2"]
    assert [c.get("pageToken") for c in others] == [None, "2"]
    assert (
        connections[0]["personFields"] == others[0]["readMask"] == "names,emailAddresses,phoneNumbers,photos"
    )
    assert fake.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "people.googleapis.com")}
    assert {a["scope"] for a in fake.assertions} == {CONTACTS_SCOPE, OTHER_CONTACTS_SCOPE}


def test_a_book_the_delegation_does_not_grant_is_said_and_left_out(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.delegated = {CONTACTS_SCOPE}
    code, out, err = _cli(capsys, "people", "review", "--from-google", "--json")
    assert code == 0 and OTHER_CONTACTS_SCOPE in err and "other contacts not read" in err
    data = json.loads(out)
    assert data["contacts"]["books"] == {"contacts": 4, "other contacts": 0}
    assert data["contacts"]["refused"] == ["other contacts"]


def test_neither_book_granted_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.delegated = set()
    code, _out, err = _cli(capsys, "people", "review", "--from-google")
    assert code == 1 and err.count("\n") == 1 and CONTACTS_SCOPE in err and OTHER_CONTACTS_SCOPE in err
    assert not (lb.root / "state" / "google-contacts.json").exists()


def test_without_the_key_it_says_what_to_set(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _out, err = _cli(capsys, "people", "review", "--from-google")
    assert code == 2 and f"set {KEY_ENV} and {USER_ENV}" in err


def test_from_google_goes_with_review(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = _cli(capsys, "people", "--from-google")
    assert code == 2 and "go with `people review`" in err


def test_the_proposals_are_the_pure_functions(lb: Logbook) -> None:
    """`propose` with contacts and without: the contacts add to the queue, never take from it."""
    report = people_review.read(lb)
    contacts = [
        c for raw in _contacts() if (c := google_contacts.person(raw, google_contacts.CONTACTS)) is not None
    ]
    unplaced = [o for o in people_review.observed(lb) if o.entity is None]
    plain = people_review.propose(unplaced, report.canonicals, report.rejected, "44")
    weighed = people_review.propose(unplaced, report.canonicals, report.rejected, "44", contacts)
    assert {p.id for p in plain} <= {p.id for p in weighed}
    assert contacts[0].phones == (MAREN["phone"],), "Google's E.164 form when it gives one"
