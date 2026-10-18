"""The week's one stale question (RFC 0037 §10.6, `dream_week.stale_question`): `dream week` asks at
most one question a week about the stalest holding or idea, as a proposal in the week's draft
(`extra.question`), never a line of its own and never a status. The stalest is asked; nothing is
asked when nothing is stale; an entity already asked by another week's draft is passed over; and
nothing above the draft's tier is ever named (an org's status is tier 3, so a tier-2 week never asks
about a holding, however stale). On the synthetic fortnight of `dream_fortnight.py`, with the
in-process fake endpoint; nobody and nothing here exists."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import ENV, W24, W25, fake, fortnight, run_cli

from logbook.contrib import dream, dream_week, entities, entity_review
from logbook.core import drafts, policy
from logbook.core.store import Logbook, uuid7

MONDAY_AFTER = "2026-06-22"
MAP = "Harbour Map App"  # exploring since May 2023: stale by the Sundays of June 2026
KIOSK = "Fjord Kiosk"  # exploring since December 2025: not stale
SAUNA = "Floating Sauna"  # exploring since September 2023: stale, less so than the map
HAVN = "Havn Data AS"  # hold since March 2022: the stalest of all, but its status is tier 3


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date.fromisoformat(MONDAY_AFTER))
    return lb


def name(
    lb: Logbook, kind: str, label: str, status: str, since: str, refs: list[tuple[str, str]] | None = None
) -> None:
    """One canonical entity of `kind`, named before the fortnight, and the owner's status on it."""
    entity_id = uuid7()
    found = refs or []
    payload = entities.entity_payload(
        kind, entity_id, label, refs=found, key=entities.key_of(kind, found, entity_id, label)
    )
    entity_review.write_entity(lb, payload, at="2022-01-03T10:00:00Z")
    code, _out, err = run_cli("status", kind, label, status, "--at", since)
    assert code == 0, err


def weeks(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {
        line["payload"]["subject"]: line
        for line in Logbook(lb.root).lines()
        if line["kind"] == drafts.KIND and line["payload"]["unit"] == drafts.UNIT_WEEK
    }


def statuses(lb: Logbook) -> int:
    return sum(1 for line in Logbook(lb.root).lines() if line["kind"] == entities.STATUS)


def test_the_stalest_idea_is_asked_once_and_never_a_line_of_its_own(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.IDEA, KIOSK, "exploring", "2025-12-01")
    name(lb, entities.IDEA, SAUNA, "exploring", "2023-09-10")
    name(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    before = statuses(lb)
    seen = fake(monkeypatch)
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  dreamed" in out and f"{W25}  dreamed" in out, out + err
    found = weeks(lb)
    asked = found[W24]["payload"]["extra"]["question"]
    assert asked["label"] == MAP and asked["status"] == "exploring" and asked["since"] == "2023-05-02"
    assert asked["entity"]["type"] == "idea"
    assert asked["text"] == "Harbour Map App: still exploring? Nothing since May 2023."
    then = found[W25]["payload"]["extra"]["question"]
    assert then["label"] == SAUNA, "the map was asked once, so the next week asks the next stalest"
    assert statuses(lb) == before, "a question is never a status"
    assert all(line["kind"] != "note" or line["source"] != "dream" for line in Logbook(lb.root).lines())
    for draft in found.values():
        texts = " ".join(s["text"] for s in draft["payload"]["segments"])
        assert MAP not in texts and SAUNA not in texts, "never a segment"
    for material in seen["weeks"]:
        assert MAP not in str(material) and SAUNA not in str(material), "nothing of it goes to the model"


def test_one_question_a_week_and_the_same_one_when_the_week_is_read_again(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    name(lb, entities.IDEA, SAUNA, "exploring", "2023-09-10")
    fake(monkeypatch)
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0, out + err
    first = weeks(lb)[W24]["payload"]["extra"]["question"]
    assert set(first) == {"entity", "label", "status", "status_line", "since", "text", "read"}
    assert first["status_line"] in first["read"]
    assert read_again(lb, W24).question == first, "its own week's draft does not count as asked"
    assert read_again(lb, W25).question["label"] == SAUNA, "another week's does"


def read_again(lb: Logbook, week: str) -> Any:
    week_, monday, sunday = dream_week.which(week, date.fromisoformat(MONDAY_AFTER))
    return dream_week.material(lb, week_, monday, sunday, dream.ceiling(lb))


def test_nothing_is_asked_when_nothing_is_stale(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.IDEA, KIOSK, "exploring", "2025-12-01")
    name(lb, entities.IDEA, MAP, "spark", "2023-05-02")  # a spark never goes stale
    fake(monkeypatch)
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0, out + err
    for draft in weeks(lb).values():
        assert "question" not in draft["payload"]["extra"]


def test_a_holding_above_the_draft_s_tier_is_never_named(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.ORG, HAVN, "hold", "2022-03-01")
    name(lb, entities.IDEA, SAUNA, "exploring", "2023-09-10")
    fake(monkeypatch)
    run_cli("dream", "--catch-up")
    found = weeks(lb)
    assert found[W24]["tier"] <= 2
    assert found[W24]["payload"]["extra"]["question"]["label"] == SAUNA, "the stalest the draft may name"
    for draft in found.values():
        assert HAVN not in str(draft["payload"]), "a tier-3 status never reaches a tier-2 draft"
    assert "question" not in found[W25]["payload"]["extra"], "the sauna was asked; the holding never is"


def test_an_idea_above_the_ceiling_is_never_read_or_named(lb: Logbook) -> None:
    """Under a ceiling of 1 the entity and status lines (tier 2) are not read at all, and a draft of
    tier 1 never names a tier-2 idea even under a ceiling of 2."""
    name(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    _week, _monday, sunday = dream_week.which(W24, date.fromisoformat(MONDAY_AFTER))
    assert dream_week.stale_question(lb, W24, sunday, [0, 1], 1) == (None, {})
    assert dream_week.stale_question(lb, W24, sunday, [0, 1, 2], 1) == (None, {})
    question, read_ids = dream_week.stale_question(lb, W24, sunday, [0, 1, 2], 2)
    assert question is not None and question["label"] == MAP
    assert read_ids and max(read_ids.values()) == 2 and question["status_line"] in read_ids


def test_a_holding_is_asked_only_of_a_tier_3_week_and_a_touched_one_never(lb: Logbook) -> None:
    """The holding's staleness is the Manifest's: a mail from its domain this month is a touch."""
    name(lb, entities.ORG, HAVN, "hold", "2022-03-01", refs=[("domain", "havn.example.org")])
    name(lb, entities.ORG, "Nordmann Verft AS", "hold", "2021-05-01", refs=[("domain", "verft.example.org")])
    lb.append(
        at="2026-06-02T09:00:00Z",
        source="mail",
        kind="mail",
        tier=2,
        payload={
            "schema": "mail/v1",
            "raw_id": "mail:verft-1",
            "message_id": "verft-1@verft.example.org",
            "thread": "verft-1@verft.example.org",
            "from": {"email": "ola@verft.example.org", "name": "Ola Nordmann"},
            "to": [{"email": "ines@example.org", "name": "Ines Nordmann"}],
            "subject": "The berth",
            "direction": "received",
            "size": 900,
        },
    )
    _week, _monday, sunday = dream_week.which(W24, date.fromisoformat(MONDAY_AFTER))
    question, read_ids = dream_week.stale_question(lb, W24, sunday, [0, 1, 2, 3], 3)
    assert question is not None and question["label"] == HAVN, "the yard was touched in June: not stale"
    assert question["text"] == "Havn Data AS: still hold? Nothing since March 2022."
    assert read_ids[question["status_line"]] == 3
    assert dream_week.stale_question(lb, W24, sunday, [0, 1, 2, 3], 2) == (None, {}), "a tier-2 week"
    assert dream_week.stale_question(lb, W24, sunday, [0, 1, 2], 2) == (None, {}), "a ceiling of 2"


def test_any_status_stale_days_names_is_asked(lb: Logbook) -> None:
    (lb.root / "policy" / "entities.json").write_text('{"stale_days": {"build": 365}}', encoding="utf-8")
    name(lb, entities.IDEA, KIOSK, "build", "2025-03-01")
    _week, _monday, sunday = dream_week.which(W24, date.fromisoformat(MONDAY_AFTER))
    question, _read = dream_week.stale_question(lb, W24, sunday, [0, 1, 2], 2)
    assert question is not None and question["text"] == "Fjord Kiosk: still build? Nothing since March 2025."


def test_an_unreadable_entities_policy_asks_nothing_and_refuses_no_week(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    (lb.root / "policy" / "entities.json").write_text(
        '{"stale_days": {"exploring": "two years"}}', encoding="utf-8"
    )
    fake(monkeypatch)
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  dreamed" in out and f"{W25}  dreamed" in out, out + err
    assert all("question" not in draft["payload"]["extra"] for draft in weeks(lb).values())


def test_an_answer_to_the_question_never_sends_the_week_again_by_itself(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network: Any
) -> None:
    name(lb, entities.IDEA, MAP, "exploring", "2023-05-02")
    seen = fake(monkeypatch)
    run_cli("dream", "--catch-up")
    sent = len(seen["weeks"])
    assert run_cli("status", "idea", MAP, "spark", "--reason", "Still on my mind.")[0] == 0
    _code, out, err = run_cli("dream", "--catch-up")
    assert f"{W24}  unchanged" in out and f"{W25}  unchanged" in out, out + err
    assert len(seen["weeks"]) == sent
