"""A name the record learned only from a tier-3 resolution never reaches the model under a `dream`
entry of `max_tier` 2 (R2), whatever the unit: the day, the week, the month, the journey, the chapter;
and a proposal the owner accepts writes no such name into its event line. A draft's own tier is the
highest tier of any resolution that supplied a name the model was given."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import test_dream_month
from dream_fortnight import ENV, JOURNEY, W25, ZURICH, fake, run_cli, week_answer
from persona import HOME, KARI, KARI_ID, dwell, note, photo, resolution, utc
from test_dream_chapter import opened

from logbook.commands import day as day_command
from logbook.contrib import dream, dream_journey, model_client
from logbook.core import drafts, policy
from logbook.core.store import Logbook

DAY = "2026-06-10"
SECRET = "Per Hemmelig"  # a person the record names only at tier 3
SECRET_ID = "019cadd3-6bc0-7dcd-9133-000000000099"
SECRET_PHONE = "+447700900123"
SECRET_FACE = "p_99"


def _message(at: str, text: str, sender: str, chat: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "chat": {"type": "direct", "id": chat},
            "sender": {"kind": "phone", "value": sender},
            "from_me": False,
            "text": text,
            "raw_id": f"msg:{at}",
        },
    }


def secret_resolutions() -> list[dict[str, Any]]:
    """The only lines that name the person: tier-3 resolutions of their phone and their face."""
    return [
        {**resolution(("phone", SECRET_PHONE), SECRET_ID, SECRET), "tier": 3},
        {**resolution(("provider_id", f"immich:{SECRET_FACE}"), SECRET_ID, SECRET), "tier": 3},
    ]


def _policy(lb: Logbook, max_tier: int) -> None:
    data = {policy.DREAM_DESTINATION: {"max_tier": max_tier, "until": "2026-12-31"}}
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lines: list[dict[str, Any]] = [
        resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        *secret_resolutions(),
    ]
    lines += dwell(DAY, "08:00", "18:00", HOME, every_min=20)
    lines.append(note(utc(DAY, "12:30"), "Lunch at the cafe."))
    lines.append(photo(utc(DAY, "13:00"), HOME, people=[SECRET_FACE]))
    lines.append(_message(utc(DAY, "15:00"), "Ses i morgen?", KARI["phone"], "chat-kari"))
    lines.append(_message(utc(DAY, "16:00"), "Har du tid i kveld?", SECRET_PHONE, "chat-secret"))
    lb.append_many(lines)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    _policy(lb, 2)
    return lb


def test_the_day_never_sends_a_name_learned_only_at_tier_3(lb: Logbook) -> None:
    made = dream.material(lb, DAY, dream.ceiling(lb))
    dream.enrich(lb, made, dream.ceiling(lb))
    sent = json.dumps(dream.prompt(made), ensure_ascii=False)
    assert SECRET not in sent and "Hemmelig" not in sent
    assert "Kari Nordmann" in sent  # a tier-2 name is the entry's to send
    assert SECRET_ID not in made.canonical and made.tier == 2


def test_the_day_under_max_tier_3_sends_the_name_and_the_draft_is_tier_3(lb: Logbook) -> None:
    _policy(lb, 3)
    made = dream.material(lb, DAY, dream.ceiling(lb))
    sent = json.dumps(dream.prompt(made), ensure_ascii=False)
    assert SECRET in sent
    assert made.tier == 3  # the name came from a tier-3 resolution: the draft is tier 3


# -- the week, the journey, the month and the chapter, on the fortnight --------------------------------------

ZURICH_DAYS = ("2026-06-15", "2026-06-16", "2026-06-17")
SECRET_SAID = "Per Hemmelig moved the most this week."  # what a model wrote when it was given the name


def _with_the_secret(lb: Logbook) -> None:
    """The fortnight with the tier-3-only person: their tier-3 resolutions, a photo of them in Zürich on
    the journey, a message from them each day of it (one a promise to the owner) and one at home."""

    lines = [*secret_resolutions(), photo(utc(ZURICH_DAYS[1], "13:00"), ZURICH, people=[SECRET_FACE])]
    for day in ZURICH_DAYS:
        lines.append(_message(utc(day, "08:00"), "God morgen!", SECRET_PHONE, "chat-secret"))
    lines.append(
        _message(
            utc(ZURICH_DAYS[2], "08:05"), "I'll send you the charts tomorrow.", SECRET_PHONE, "chat-secret"
        )
    )
    lines.append(_message(utc("2026-06-19", "18:00"), "Takk for turen.", SECRET_PHONE, "chat-secret"))
    lb.append_many(lines)


@pytest.fixture
def june(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = test_dream_month.june(tmp_path, monkeypatch)
    _with_the_secret(lb)
    return lb


def _named_secret(material: object) -> bool:
    return SECRET in json.dumps(material, ensure_ascii=False) or "Hemmelig" in json.dumps(material)


def test_the_week_never_sends_a_name_learned_only_at_tier_3(
    june: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):

    seen = fake(monkeypatch)
    test_dream_month.today_is(monkeypatch, "2026-06-22")
    code, out, err = run_cli("dream", "--catch-up")
    assert code == 0 and f"{W25}  dreamed" in out, out + err
    (week,) = [w for w in seen["weeks"] if w["week"] == W25]
    assert not _named_secret(week)
    assert "Ola Nordmann" in json.dumps(week, ensure_ascii=False), "a tier-2 name is the entry's"
    assert not any(_named_secret(json.loads(c["messages"][1]["content"])) for c in seen["calls"])


def test_the_journey_never_sends_a_name_learned_only_at_tier_3(
    june: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):

    found = policy.dream_entry(june.root)
    rd, trip = dream_journey.locate(june, JOURNEY, found)
    read = dream_journey.material(june, rd, trip, found)
    assert not _named_secret(dream_journey.prompt(read))
    assert read.made.tier == 2
    _policy(june, 3)  # under max_tier 3 the name is the entry's, and the draft is tier 3
    found = policy.dream_entry(june.root)
    rd, trip = dream_journey.locate(june, JOURNEY, found)
    read = dream_journey.material(june, rd, trip, found)
    assert _named_secret(dream_journey.prompt(read)) and read.made.tier == 3


def _leaky_day(material: dict[str, Any]) -> dict[str, Any]:
    """A day's answer as a model wrote it before the dream read names at its entry's tiers: the
    tier-3-only person by name, on the day's first reference."""

    refs = re.findall(r'"(L\d+)"', json.dumps(material))
    return {
        "story": [{"text": "A day.", "evidence": refs[:1]}, {"text": SECRET_SAID, "evidence": refs[:1]}],
        "threads": [],
        "questions": [],
        "people": [],
    }


def test_the_month_never_sends_a_name_learned_only_at_tier_3(
    june: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):

    seen = test_dream_month.fake_arcs(monkeypatch)
    monkeypatch.setattr(test_dream_month, "day_answer", _leaky_day)  # the days' drafts name the person
    test_dream_month.dreamed_days(monkeypatch, june)
    leaky = [x for x in Logbook(june.root).lines() if x["kind"] == "draft" and SECRET_SAID in json.dumps(x)]
    assert leaky, "the days' drafts carry the name, as a draft written before the fix does"
    test_dream_month.today_is(monkeypatch, "2026-07-01")
    code, out, err = run_cli("dream", "month", test_dream_month.JUNE)
    assert code == 0, out + err
    (material,) = seen["months"]
    assert not _named_secret(material)
    assert [d["day"] for d in material["days"]] == list(test_dream_month.SIGNED)


def test_the_chapter_never_sends_a_name_learned_only_at_tier_3(
    june: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    from test_dream_month import dreamed_days, fake_arcs

    def leaky_week(material: dict[str, Any]) -> dict[str, Any]:
        found = week_answer(material)
        first = found["time"][0]["evidence"]
        found["time"].append({"text": SECRET_SAID, "evidence": first})
        return found

    seen = fake_arcs(monkeypatch, week=leaky_week)
    opened(monkeypatch, june)
    dreamed_days(monkeypatch, june)
    weeks = [x for x in Logbook(june.root).lines() if x["kind"] == "draft" and x["payload"]["unit"] == "week"]
    assert any(SECRET_SAID in json.dumps(w) for w in weeks), "a week's draft carries the name"
    test_dream_month.today_is(monkeypatch, "2026-06-23")
    code, out, err = run_cli("dream", "chapter")
    assert code == 0, out + err
    (material,) = seen["chapters"]
    assert material["weeks"] and not _named_secret(material)


def test_under_max_tier_1_no_unit_sends_a_name_learned_at_tier_2(
    june: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """The rule is the entry's tiers, not tier 3: the fortnight names its people at tier 2, so a dream
    under `max_tier` 1 names none of them, the days' and the weeks' materials alike."""
    _policy(june, 1)
    seen = fake(monkeypatch)
    test_dream_month.today_is(monkeypatch, "2026-06-22")
    code, out, err = run_cli("dream", "--catch-up")
    assert code in (0, 1) and f"{W25}  dreamed" in out, out + err
    sent = [json.loads(c["messages"][1]["content"]) for c in seen["calls"]]
    assert sent and not any("Nordmann" in json.dumps(m, ensure_ascii=False) for m in sent)


# -- an accepted event --------------------------------------------------------------------------------------


def _send(monkeypatch: pytest.MonkeyPatch, answer: Any) -> None:
    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        material = json.loads(body["messages"][1]["content"])
        return {"choices": [{"message": {"content": json.dumps(answer(material))}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)


def _coffee(material: dict[str, Any]) -> dict[str, Any]:
    """An answer proposing one event at the day's first stay, with the tier-3-only person there."""
    entry = next(e for e in material["timeline"] if e.get("place"))
    return {
        "story": [{"text": "A day at home.", "evidence": entry["ref"][:1]}],
        "events": [
            {
                "title": "Coffee",
                "start": entry["start"],
                "end": entry["end"],
                "place": entry["place"],
                "people": [SECRET_ID],
                "evidence": entry["ref"][:1],
            }
        ],
    }


def _events(lb: Logbook) -> list[dict[str, Any]]:
    return [x for x in Logbook(lb.root).lines() if x["kind"] == "event" and x["source"] == "owner"]


def test_an_accepted_event_never_writes_a_name_above_its_tier(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A day's draft that proposes the tier-3-only person, as one dreamed before the fix could at tier
    2, accepted: the event is a tier-1 calendar entry, so the person, whom only a tier-3 resolution
    names, is left out of it, its attendees and its title alike (the owner, 27 October)."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    _send(monkeypatch, _coffee)
    _policy(lb, 3)
    code, out, err = run_cli("dream", "day", DAY)
    assert code == 0, out + err
    (draft,) = [x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND]
    assert draft["tier"] == 3 and draft["payload"]["proposals"][0]["people"] == [SECRET_ID]
    _policy(lb, 2)  # the same proposals in a tier-2 draft under the entry at 2: one written before the fix
    payload = {**draft["payload"], "supersedes": draft["id"]}
    payload["proposals"] = [{**payload["proposals"][0], "title": f"Coffee with {SECRET}"}]
    payload["extra"] = {**payload["extra"], "policy_version": policy.version(policy.dream_entry(lb.root))}
    lb.append(draft["at"], draft["source"], drafts.KIND, 2, payload, tz=draft.get("tz"))
    code, out, err = run_cli("day", "sign", DAY, "--accept", "1")
    assert code == 0, out + err
    (event,) = _events(lb)
    assert event["tier"] == 1 and "Hemmelig" not in json.dumps(event, ensure_ascii=False)
    assert event["payload"]["title"] == "Coffee with someone" and not event["payload"].get("attendees")


# -- what the review found ----------------------------------------------------------------------------------


def test_a_first_name_learned_only_at_tier_3_is_withheld_too(lb: Logbook) -> None:
    made = dream.material(lb, DAY, dream.ceiling(lb))
    assert made.withholds("Per moved the most this week.") and made.withholds(SECRET)
    assert not made.withholds("Kari Nordmann moved the most.")
    assert made.name_of("Per") is None and made.name_of("Kari Nordmann") == "Kari Nordmann"


def test_a_withheld_name_with_a_digit_stuck_to_it_is_still_that_name(lb: Logbook) -> None:
    """`Per Hemmelig2`, `3Per`: a digit touching a name is no letter, so the name is still written
    there, withheld, and a label in the material raises the draft's tier however it is glued."""
    made = dream.material(lb, DAY, dream.ceiling(lb))
    assert made.withholds(f"{SECRET}2 came for coffee.") and made.withholds("3Per came for coffee.")
    assert not made.withholds("Perhaps 3 came for coffee."), "a longer word is another word"
    ref = ("phone", SECRET_PHONE)
    names = dream.Names(labels={ref: SECRET}, identities={}, tiers={ref: 3}, every={}, withheld=frozenset())
    assert names.tier_in({"said": f"Coffee with {SECRET}2"}) == 3
    assert names.tier_in({"said": f"Coffee with {SECRET}s"}) == 1, "a letter after it: another word"


def test_the_number_rule_holds_a_name_the_entry_withholds(lb: Logbook) -> None:
    """A name the material never gives can still be written (the owner's tier-2 text names Per): a figure
    beside it is held as beside any name, whatever its tier."""
    made = dream.material(lb, DAY, dream.ceiling(lb))
    segments = [{"text": "Per: 3 calls.", "evidence": [next(iter(made.ids))]}]
    assert dream.hold_names(segments, made) == 1 and segments[0]["text"] == dream.HELD


def test_the_gated_day_names_no_proposal_s_person_above_its_tiers(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, no_network
):
    """A tier-2 draft that proposes the tier-3-only person (one written before the fix): the Day read
    through tiers 1 and 2 shows the proposal without the name; the whole record's reader names them."""
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    _send(monkeypatch, _coffee)
    _policy(lb, 3)
    assert run_cli("dream", "day", DAY)[0] == 0
    draft = [x for x in Logbook(lb.root).lines() if x["kind"] == drafts.KIND][-1]
    payload = {**draft["payload"], "supersedes": draft["id"]}
    lb.append(draft["at"], draft["source"], drafts.KIND, 2, payload, tz=draft.get("tz"))
    with lb.index() as idx:
        gated, _ = drafts.for_day(idx, DAY, (1, 2))
        whole, _ = drafts.for_day(idx, DAY)
    assert gated is not None and gated["proposals"] and whole is not None
    assert SECRET not in json.dumps(gated["proposals"], ensure_ascii=False)
    assert SECRET in json.dumps(whole["proposals"], ensure_ascii=False)


# -- a tier-1 output names a person only from a resolution at tier 1 (the owner, 27 October) ----------------


def test_no_tier_1_output_names_a_person_only_a_tier_2_resolution_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_network
):
    """The fortnight names Kari and Ola only at tier 2, and its calendar entries give their addresses
    and no name: every output read through tier 1 alone names neither, the Library's pages, the static
    site, the vault and a letter; and once a tier-1 resolution names Kari, the reading through tier 1
    names her, and Ola still not (`test_site` holds the pages that then name her)."""
    from dream_fortnight import DAYS, W25, fortnight

    from logbook.contrib import serve

    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    crossing = policy.policy_path(lb.root)
    entries = json.loads(crossing.read_text(encoding="utf-8"))
    entries |= {"letter": {"max_tier": 1}, "site": {"max_tier": 1}, "vault": {"max_tier": 1}}
    crossing.write_text(json.dumps(entries), encoding="utf-8")

    def outputs(at: Path) -> dict[str, str]:
        texts: dict[str, str] = {}
        site = serve.Site(lb, tiers=(1,))
        _trip, first, last = JOURNEY.split(":")
        for path in (*(f"/day/{d}" for d in DAYS), "/journeys", f"/journeys/{first}/{last}", f"/week/{W25}"):
            texts[path] = site.respond(path, "").body.decode("utf-8")
        for name, args in (
            ("site", ("export", "site", str(at / "site"), "--tier", "1")),
            ("vault", ("export", "vault", str(at / "vault"), "--tier", "1")),
            ("letter", ("export", "letter", DAYS[0], DAYS[-1], "--out", str(at / "letter"), "--tier", "1")),
        ):
            code, _out, err = run_cli(*args, "--unsigned") if name == "letter" else run_cli(*args)
            assert code == 0, (name, err)
        for found in at.rglob("*"):
            if found.is_file() and found.suffix in (".html", ".md"):
                texts[found.relative_to(at).as_posix()] = found.read_text(encoding="utf-8")
        return texts

    def naming(texts: dict[str, str], name: str) -> list[str]:
        return sorted(k for k, t in texts.items() if name in re.sub(r"<[^>]+>", " ", t))

    texts = outputs(tmp_path / "before")
    assert len(texts) > 20 and naming(texts, "Ola Nordmann") == [] and naming(texts, "Kari Nordmann") == []
    from logbook.core import reading

    assert reading.read(lb, DAYS[0], DAYS[-1], tiers=(1,)).names == {}, "nobody named through tier 1"
    lb.append_many([{**resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"), "tier": 1}])
    named = reading.read(lb, DAYS[0], DAYS[-1], tiers=(1,)).names
    assert set(named.values()) == {"Kari Nordmann"}, "a contact at tier 1 names her there, and nobody else"
