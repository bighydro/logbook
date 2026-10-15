"""RFC 0037's three profiles in code (`logbook.contrib.entities`): `entity/v1`, `entity-review/v1` and
`status/v1`, validated by their field tables with the owner's twelve decisions applied; each example
line built byte for byte; the dedupe keys; the tier rules; the legacy readers (a `resolution/v1` of
type `company` is an org, a `people-review/v1` line is an `entity-review/v1` of type person); and the
conformance heads, plain and sealed, untouched. Every name, address and id here is synthetic."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import entities
from logbook.core.chain import CONTENT_FIELDS, canonical_json
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "entities.md"
HEAD = "8f1c" + "0" * 60  # a head the examples were read against, written whole (the RFC elides it)
ORG_ID = "019cadd3-6bc0-7dcd-9133-000000000201"
PASSED_ID = "019cadd3-6bc0-7dcd-9133-000000000202"
IDEA_ID = "019cadd3-6bc0-7dcd-9133-000000000301"
PERSON_ID = "019cadd3-6bc0-7dcd-9133-000000000121"
L1 = "58bfa9e704e3388d44d74e63f1d84765d24df79e92fce3b522fbef53b765d3df"
L2 = "0ab4c3e79bacc9a7c19d074094e81d1674fdf6967ceaf0d1711679e3c11481db"

FIXTURES = ROOT / "tests" / "fixtures" / "entities"


def _example(name: str) -> str:
    """One example line as written, from `tests/fixtures/entities/`: RFC 0037 §11's with the decisions
    applied (the org binds its domain through entity/v1, decision 1, so no resolution line; the passed
    company's status is tier 3, RFC 0037 §8 and the owner's decision of 13 October 2026; the heads
    whole), the entity-review/v1 examples of the profiles page, RFC 0035's people-review/v1 example and
    RFC 0037's company resolution, as given."""
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8").strip()


ORG, IDEA, PASSED, EXPLORING = (_example(n) for n in ("org", "idea", "passed", "exploring"))
REVIEW_ORG, REVIEW_PLACE = _example("review-org"), _example("review-place")
PEOPLE_REVIEW, COMPANY = _example("people-review"), _example("company")
PASSED_BECAUSE = json.loads(PASSED)["payload"]["proposal"]["because"]

BUILT: dict[str, tuple[str, dict[str, Any]]] = {
    "org": (
        ORG,
        entities.entity_payload(
            "org",
            ORG_ID,
            "Nordmann Verft AS",
            refs=[
                ("domain", "nordmann-verft.example"),
                ("group", "nordmann verft board"),
                ("repo", "github.com/nordmann-verft"),
            ],
            aliases=["Nordmann Verft"],
            key="domain:nordmann-verft.example",
            evidence=["019cadd3-6bc0-7dcd-9133-0000000001a1", "019cadd3-6bc0-7dcd-9133-0000000001a2"],
            head=HEAD,
        ),
    ),
    "idea": (
        IDEA,
        entities.entity_payload(
            "idea",
            IDEA_ID,
            "the fjord kiosk",
            refs=[
                ("repo", "github.com/nordmann-verft/kiosk"),
                ("page", "notion:1f2e3d4c-0000-0000-0000-000000000031"),
                ("title", "fjord kiosk"),
            ],
            key="repo:github.com/nordmann-verft/kiosk",
            extra={"pitch": "a kiosk on the ferry quay that sells what the ferry forgot"},
        ),
    ),
    "passed": (
        PASSED,
        entities.status_payload(
            "org",
            PASSED_ID,
            "Fjordkiosk AS",
            "passed",
            "good team, but a kiosk is a place and I do not want to own places",
            proposed_by="dream",
            proposal={
                "status": "passed",
                "score": 40,
                "because": PASSED_BECAUSE,
            },
            evidence=["019cadd3-6bc0-7dcd-9133-0000000001b1"],
            head=HEAD,
        ),
    ),
    "exploring": (
        EXPLORING,
        entities.status_payload(
            "idea",
            IDEA_ID,
            "the fjord kiosk",
            "exploring",
            "pricing page written; talk to the ferry company first",
            note="019cadd3-6bc0-7dcd-9133-0000000001d3",
        ),
    ),
    "review-org": (
        REVIEW_ORG,
        entities.review_payload(
            "org",
            ("group", "nordmann verft sailing"),
            refs=[("group", "nordmann verft sailing")],
            observed=["Nordmann Verft sailing"],
            entity_id=ORG_ID,
            label="Nordmann Verft AS",
            evidence=["019cadd3-6bc0-7dcd-9133-0000000001c1"],
            head=HEAD,
        ),
    ),
    "review-place": (
        REVIEW_PLACE,
        entities.review_payload("place", ("centre", "59.902100,10.741200"), label="Boathouse", head=HEAD),
    ),
}


def _content(text: str) -> bytes:
    line = json.loads(text)
    return canonical_json({k: line[k] for k in CONTENT_FIELDS})


# -- the examples ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(BUILT))
def test_each_example_line_is_built_byte_for_byte_and_valid(name: str, tmp_path: Path) -> None:
    text, payload = BUILT[name]
    example = json.loads(text)
    assert canonical_json(payload) == canonical_json(example["payload"]), name
    assert entities.VALIDATORS[payload["schema"]](payload) == []
    assert entities.tier_problems(payload["schema"], example["tier"], {}, payload["entity"]["type"]) == []
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    line = lb.append(
        at=example["at"], source="manual", kind=example["kind"], tier=example["tier"], payload=payload
    )
    assert canonical_json({k: line[k] for k in CONTENT_FIELDS}) == _content(text), "the hashed bytes"
    assert lb.verify()[2] == []


@pytest.mark.parametrize("name", sorted(BUILT))
def test_the_profiles_page_carries_each_example_verbatim(name: str) -> None:
    page = DOCS.read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", page, re.S)]
    assert json.loads(BUILT[name][0]) in blocks, name


# -- validation -----------------------------------------------------------------------------------------


def test_entity_v1_refuses_what_its_table_refuses() -> None:
    good = json.loads(ORG)["payload"]
    assert entities.validate_entity(good) == []
    bad = {**good, "entity": {**good["entity"], "id": "1f2e3d4c-0000-4000-8000-000000000001"}}  # a v4
    assert any("UUIDv7" in p for p in entities.validate_entity(bad))
    assert any(
        "registry" in p
        for p in entities.validate_entity({**good, "entity": {**good["entity"], "registry": "crm"}})
    )
    assert any("label" in p for p in entities.validate_entity({**good, "label": " "}))
    assert any(
        "refs[0].kind" in p
        for p in entities.validate_entity({**good, "refs": [{"kind": "url", "value": "x"}]})
    )
    person = {**good, "entity": {"type": "person", "id": PERSON_ID, "registry": "logbook"}}
    assert any("resolution/v1" in p for p in entities.validate_entity(person)), "decision 1"
    assert entities.validate_entity({**person, "refs": []}) == []
    place = {**good, "entity": {"type": "place", "id": "Hytta", "registry": "logbook"}}
    assert entities.validate_entity(place) == []
    asset = {**good, "entity": {"type": "asset", "id": "Solvind!", "registry": "logbook"}}
    assert any("assets.json" in p for p in entities.validate_entity(asset))
    assert any("logbook_head" in p for p in entities.validate_entity({**good, "logbook_head": "8f1c…"}))


def test_entity_review_v1_takes_every_kind_and_a_new_entity_by_type_alone() -> None:
    org = json.loads(REVIEW_ORG)["payload"]
    assert entities.validate_entity_review(org) == []
    place = json.loads(REVIEW_PLACE)["payload"]
    assert entities.validate_entity_review(place) == [], "a place's no: the spot and the name, no id"
    assert any("verdict" in p for p in entities.validate_entity_review({**org, "verdict": "same"}))
    person = {**org, "entity": {"type": "person"}}
    assert any("canonical person" in p for p in entities.validate_entity_review(person))
    assert any(
        "ref.kind" in p
        for p in entities.validate_entity_review({**org, "ref": {"kind": "url", "value": "x"}})
    )


def test_status_v1_takes_the_four_kinds_and_their_dispositions_and_no_money() -> None:
    for kind, dispositions in entities.DISPOSITIONS.items():
        entity_id = {"org": ORG_ID, "idea": IDEA_ID, "place": "Hytta", "asset": "solvind"}[kind]
        for status in dispositions:
            payload = entities.status_payload(kind, entity_id, "x", status, "because")
            assert entities.validate_status(payload) == [], (kind, status)
    assert entities.DISPOSITIONS["org"] == ("hold", "add", "sell", "let-go", "exited", "passed")
    assert entities.DISPOSITIONS["idea"] == ("spark", "exploring", "build", "built", "killed")
    assert entities.DISPOSITIONS["place"] == ("let-go",) and entities.DISPOSITIONS["asset"] == (
        "sold",
        "let-go",
    )
    good = json.loads(PASSED)["payload"]
    assert any("not one of" in p for p in entities.validate_status({**good, "status": "sold"}))
    assert any(
        "must say why" in p
        for p in entities.validate_status({k: v for k, v in good.items() if k != "reason"})
    )
    assert any("no money" in p for p in entities.validate_status({**good, "amount": -2500}))
    person = {**good, "entity": {"type": "person", "id": PERSON_ID, "registry": "logbook"}}
    assert any("entity.type" in p for p in entities.validate_status(person)), "a person has no status"
    goal = {**good, "entity": {"type": "goal", "id": ORG_ID, "registry": "logbook"}}
    assert any("entity.type" in p for p in entities.validate_status(goal)), "a goal is reviewed by review/v1"


def test_the_tier_rules_name_the_rule_per_kind_an_org_status_is_tier_three() -> None:
    money = {"019cadd3-6bc0-7dcd-9133-0000000001d1": 3}
    assert entities.status_tier("org") == 3 and [
        entities.status_tier(k) for k in ("idea", "place", "asset")
    ] == [
        2,
        2,
        2,
    ]
    assert entities.tier_problems("status/v1", 3, money, "org") == [], "an org's status may cite the ledger"
    assert entities.tier_problems("status/v1", 2, {}, "org") == [
        "a status/v1 line about an org is tier 3, not 2: its dispositions describe a position in money"
    ]
    for kind in ("idea", "place", "asset"):
        assert entities.tier_problems("status/v1", 2, {}, kind) == [], kind
        [wrong] = entities.tier_problems("status/v1", 3, {}, kind)
        assert (
            wrong == f"a status/v1 line about {'an' if kind[0] in 'aeiou' else 'a'} {kind} is tier 2, not 3"
        )
        [cites] = entities.tier_problems("status/v1", 2, money, kind)
        assert cites.startswith(
            f"a status/v1 line about {'an' if kind[0] in 'aeiou' else 'a'} {kind} never cites"
        )
        assert "019cadd3-6bc0-7dcd-9133-0000000001d1 is tier 3" in cites
    assert entities.tier_problems("entity/v1", 2, money, "org") == [
        "an entity/v1 line of kind org never cites a tier-3 line (019cadd3-6bc0-7dcd-9133-0000000001d1"
        " is tier 3): bind a merchant as a `merchant` ref, and the ledger is read at the page, within its"
        " ceiling"
    ], "an entity/v1 line stays tier 2 for every kind, an org's too"
    assert entities.tier_problems("entity/v1", 3, {}, "org") == [
        "an entity/v1 line of kind org is tier 2, not 3"
    ]
    assert entities.tier_problems("entity-review/v1", 3, money, "org") == [], (
        "a no is the highest of its evidence"
    )
    assert entities.tier_problems("entity-review/v1", 2, money, "place")


def test_the_tier_rules_an_entity_line_never_cites_a_tier_three_line() -> None:
    money = {"019cadd3-6bc0-7dcd-9133-0000000001d1": 3, "019cadd3-6bc0-7dcd-9133-0000000001a1": 2}
    problems = entities.tier_problems("entity/v1", 2, money)
    assert len(problems) == 1 and "tier-3" in problems[0] and "merchant" in problems[0]
    assert entities.tier_problems("entity/v1", 3, {}) == ["an entity/v1 line is tier 2, not 3"]
    assert entities.tier_problems("status/v1", 2, {}) == [] and entities.tier_problems("status/v1", 3, {})
    assert entities.tier_problems("entity-review/v1", 3, money) == [], "a no citing the ledger is tier 3"
    assert entities.tier_problems("entity-review/v1", 2, money), "and never tier 2"
    assert entities.review_tier([1, 1]) == 2, "a no is a decision: never under 2"


# -- the keys -------------------------------------------------------------------------------------------


def test_one_dedupe_key_per_kind_strongest_first() -> None:
    key = entities.key_of
    assert key("person", [("phone", "+447700900123"), ("email", "Ola.Nordmann@Example.org")]) == (
        "email:ola.nordmann@example.org"
    )
    assert key("person", [("name", "nordmann ola")]) == "name:nordmann ola"
    assert key("org", [("group", "Nordmann Verft Board"), ("domain", "post.nordmann-verft.example")]) == (
        "domain:nordmann-verft.example"
    )
    assert key("org", [("repo", "github.com/nordmann-verft/kiosk")]) == "repo-org:github.com/nordmann-verft"
    assert key("org", [("merchant", "  FJORDKIOSK  AS ")]) == "merchant:fjordkiosk as"
    assert key("idea", [("title", "The Fjord Kiosk"), ("page", "notion:1f2e")]) == "page:notion:1f2e"
    assert (
        key("idea", [("repo", "github.com/Nordmann-Verft/Kiosk")]) == "repo:github.com/nordmann-verft/kiosk"
    )
    assert key("idea", [("title", "The Fjord Kiosk")]) == "title:fjord kiosk"
    assert key("place", [("place", "Hytta på Banken")]) == "place:hytta på banken"
    assert key("asset", [("registration", "ZZ-ABC"), ("mmsi", "970123456")]) == "mmsi:970123456"
    assert key("asset", [("registration", "ZZ-ABC")]) == "registration:zzabc"
    assert key("asset", [], "solvind") == "subject:solvind"


def test_the_registered_domain_is_the_public_suffix_and_one_label() -> None:
    domain = entities.registered_domain
    assert domain("post.nordmann-verft.example") == "nordmann-verft.example"
    assert domain("mail.fjordkiosk.co.uk") == "fjordkiosk.co.uk"
    assert domain("post.verft.example.org") == "verft.example.org", "RFC 2606: a subdomain is a party"
    assert domain("example.org") == "example.org" and domain("localhost") is None
    assert domain("a.b.club.example", ["club.example"]) == "b.club.example", "a suffix the settings add"


# -- the legacy readers ---------------------------------------------------------------------------------


def _lines(*texts: str) -> list[dict[str, Any]]:
    found = []
    for n, text in enumerate(texts, start=1):
        line = json.loads(text)
        found.append({**line, "seq": n, "id": f"019cadd3-6bc0-7dcd-9133-00000000f{n:03d}"})
    return found


def test_a_resolution_of_type_company_resolves_as_an_org_entity() -> None:
    found = entities.canonical(_lines(COMPANY))
    org = found[("org", ORG_ID)]
    assert org.label == "Nordmann Verft AS" and org.refs == [("domain", "nordmann-verft.example")]
    assert org.key == "domain:nordmann-verft.example"
    assert ("company", ORG_ID) not in found, "company is the frozen word, never a kind"
    assert entities.bindings(_lines(COMPANY)) == {("domain", "nordmann-verft.example"): ("org", ORG_ID)}
    both = entities.canonical(_lines(COMPANY, ORG))
    assert both[("org", ORG_ID)].lines and ("group", "nordmann verft board") in both[("org", ORG_ID)].refs
    assert entities.lookup(both, "org", "Nordmann Verft").id == ORG_ID, "by its alias"
    assert entities.lookup(both, "org", "domain:nordmann-verft.example").id == ORG_ID, "by its ref"
    with pytest.raises(entities.EntityError, match="no org"):
        entities.lookup(both, "org", "Fjordkiosk")


def test_a_people_review_line_is_read_as_an_entity_review_of_type_person() -> None:
    [review] = entities.reviews(_lines(PEOPLE_REVIEW))
    assert (review.kind, review.entity, review.label) == ("person", PERSON_ID, "Hanna Foss")
    assert review.ref == ("email", "hanna.foss@example.org")
    assert review.holds([("email", "hanna.foss@example.org")], PERSON_ID)
    both = entities.reviews(_lines(PEOPLE_REVIEW, REVIEW_ORG, REVIEW_PLACE))
    assert [r.kind for r in both] == ["person", "org", "place"]
    assert both[2].entity is None and both[2].label == "Boathouse"
    hide = {"schema": "retraction/v1", "supersedes": "019cadd3-6bc0-7dcd-9133-00000000f001"}
    retraction = json.dumps(
        {"at": "2026-10-11T08:00:00Z", "end": None, "tz": "Europe/Oslo", "source": "manual",
         "kind": "retraction", "tier": 2, "payload": hide}
    )  # fmt: skip
    assert entities.reviews(_lines(PEOPLE_REVIEW, retraction)) == [], "retracted: the proposal returns"


# -- the conformance heads ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("folder", "head"), [("sample-logbook", L1), ("sample-logbook-sealed", L2)], ids=["plain", "sealed"]
)
def test_the_conformance_heads_hold(folder: str, head: str) -> None:
    lb = Logbook(ROOT / "conformance" / folder)
    seq, found, errors = lb.verify()[:3]
    assert errors == [] and found == head and seq == 32
    expected = "expected.json" if folder == "sample-logbook" else "expected-sealed.json"
    assert json.loads((ROOT / "conformance" / expected).read_text(encoding="utf-8"))["head"] == head
