"""All except junk (RFC 0045, amendment of 20 November 2026): the crossing's third mail mode. Every mail
crosses but a received one the owner's own rule, the destination's `mail_junk` entry in
`policy/crossing.json`, calls junk: by its Gmail category, or by one of its labels (the IMAP road has no
category, so a label lets both roads agree). A person of the record (the sender, never a cc, never the
owner), a label of `never_labels`, an invitation platform, an org in a portfolio and a sender Hold keeps
each spare a mail; a sender Hold let go is held whatever spares it. The package, the dry run, the door
and `day sign` give counts only, never a name, an address or a subject.

Every string here is synthetic: Ines Nordmann (the owner), Kari and Ola Nordmann live in Oslo and do not
exist, nor does Nordmann Robotics AS; the label names are made up for the test, as the owner's mailbox
would make up its own."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import entities, mcp_server, orgs
from logbook.core import crossing, peoples_mail, policy, signing
from logbook.core.chain import Line
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-03-01"
SINCE, UNTIL = "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"
INES, INES_ID = "ines@example.org", "019cadd3-6bc0-7dcd-9133-04aa00000001"
KARI, KARI_ID = "kari@example.org", "019cadd3-6bc0-7dcd-9133-04aa00000002"
OLA, OLA_ID = "ola@example.org", "019cadd3-6bc0-7dcd-9133-04aa00000003"
ROBOTICS_ID, ROBOTICS_DOMAIN = "019cadd3-6bc0-7dcd-9133-04aa00000004", "nordmann-robotics.example.org"
ROBOTICS = f"news@post.{ROBOTICS_DOMAIN}"
SHOP = "offers@shop.example.org"
CLUB = "club@news.example.org"
STRANGER = "hello@fjord-kiosk.example.org"
HARBOUR = "harbour@example.org"
PARTY = "invitations@mail.paperlesspost.com"  # an invitation platform's address: on the reader's list
NOREPLY = "no-reply@shop.example.org"
UNSUBSCRIBE, INFO, LATER = "Triage/Unsubscribe", "Triage/Info", "Triage/Later"
ACTION, REPLY, WAITING = "Triage/Action", "Triage/Reply", "Triage/Waiting"
RULE = {"categories": ["promotions"], "labels": [UNSUBSCRIBE], "never_labels": [ACTION, REPLY, WAITING]}
NAMES = ("Ines Nordmann", "Kari Nordmann", "Ola Nordmann", "Nordmann Robotics", "Ines", "Kari", "Ola")
SUBJECT = "Mooring for the weekend"
DESTINATION = "per-hansen"


def _resolution(value: str, label: str, entity: str) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": value},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


def _mail(
    at: str,
    sender: str,
    to: str = INES,
    direction: str = "received",
    category: str | None = None,
    labels: list[str] | None = None,
    cc: str | None = None,
    listed: bool = False,
    tier: int = 2,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "mail/v1",
        "raw_id": f"m-{at}-{sender}",
        "thread": f"m-{at}-{sender}",
        "subject": SUBJECT,
        "direction": direction,
        "from": {"email": sender},
        "to": [{"email": to}],
        "size": 1024,
    }
    if cc is not None:
        payload["cc"] = [{"email": cc}]
    if labels is not None:
        payload["labels"] = labels
    extra: dict[str, Any] = {}
    if category is not None:
        extra["gmail_category"] = category
    if listed:
        extra["list"] = {"unsubscribe": True}
    if extra:
        payload["extra"] = extra
    return {"at": at, "source": "mail", "kind": "mail", "tier": tier, "payload": payload}


# Each mail of the day by a name for the test, and what the owner's rule does with it, for the default
# inputs (no sender kept, no sender let go, the portfolio read from the record).
MAILS: dict[str, tuple[dict[str, Any], str | None]] = {
    "shop": (_mail("2026-03-01T07:00:00Z", SHOP, category="promotions"), peoples_mail.JUNK_CATEGORY),
    "club_imap": (_mail("2026-03-01T07:10:00Z", CLUB, labels=[UNSUBSCRIBE]), peoples_mail.JUNK_LABEL),
    "kari_promo": (_mail("2026-03-01T07:20:00Z", KARI, category="promotions"), None),  # a: a person
    "cc_ola": (  # a: a cc is never the person the rule asks for
        _mail("2026-03-01T07:30:00Z", SHOP, category="promotions", cc=OLA),
        peoples_mail.JUNK_CATEGORY,
    ),
    "worth_a_look": (  # b: a never-label
        _mail("2026-03-01T07:40:00Z", STRANGER, category="promotions", labels=[UNSUBSCRIBE, ACTION]),
        None,
    ),
    "party": (_mail("2026-03-01T07:50:00Z", PARTY, category="promotions"), None),  # c: an invitation
    "robotics": (_mail("2026-03-01T08:00:00Z", ROBOTICS, category="promotions"), None),  # d: a portfolio
    "harbour": (_mail("2026-03-01T08:10:00Z", HARBOUR, labels=[INFO, UNSUBSCRIBE]), peoples_mail.JUNK_LABEL),
    "own": (  # the owner's own address, received: never a person
        _mail("2026-03-01T08:20:00Z", INES, category="promotions"),
        peoples_mail.JUNK_CATEGORY,
    ),
    "sent": (  # sent mail always crosses
        _mail("2026-03-01T08:30:00Z", INES, SHOP, "sent", category="promotions", labels=[UNSUBSCRIBE]),
        None,
    ),
    "plain": (_mail("2026-03-01T08:40:00Z", STRANGER), None),  # neither a category nor a label
    "updates": (_mail("2026-03-01T08:50:00Z", STRANGER, category="updates", labels=[LATER]), None),
    "noreply": (_mail("2026-03-01T09:00:00Z", NOREPLY, category="promotions"), peoples_mail.JUNK_CATEGORY),
    "listed": (
        _mail("2026-03-01T09:10:00Z", "letters@club.example.org", category="promotions", listed=True),
        peoples_mail.JUNK_CATEGORY,
    ),
}
HELD = {name for name, (_m, reason) in MAILS.items() if reason is not None}
# the held mails whose sender writes for the first time: not a no-reply address, no list mark, no
# earlier mail from the address in the record (the shop's first mail is `shop`; `cc_ola` is its second)
FIRST_TIME_HELD = {"shop", "club_imap", "harbour"}


def _status(org_id: str, portfolio: str) -> dict[str, Any]:
    payload = entities.status_payload(
        entities.ORG, org_id, "Nordmann Robotics AS", "hold", portfolio=portfolio
    )
    return {"at": "2026-02-02T09:00:00Z", "source": "manual", "kind": "status", "tier": 3, "payload": payload}


def _org() -> dict[str, Any]:
    payload = entities.entity_payload(
        entities.ORG, ROBOTICS_ID, "Nordmann Robotics AS", refs=[("domain", ROBOTICS_DOMAIN)]
    )
    return {"at": "2026-02-02T08:00:00Z", "source": "manual", "kind": "entity", "tier": 2, "payload": payload}


def _write_policy(lb: Logbook, entries: dict[str, Any]) -> None:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """One signed day, 2026-03-01, of the mails in `MAILS`; the owner's, Kari's and Ola's addresses
    resolved to persons; Nordmann Robotics AS an org bound by its domain and held in a portfolio on its
    tier-3 status line; an earlier mail from Kari, so hers is no first-time sender's."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([INES])
    lb.append_many(
        [
            _resolution(INES, "Ines Nordmann", INES_ID),
            _resolution(KARI, "Kari Nordmann", KARI_ID),
            _resolution(OLA, "Ola Nordmann", OLA_ID),
            _org(),
            _status(ROBOTICS_ID, "Fund I"),
            _mail("2026-02-20T09:00:00Z", KARI),
            *(mail for mail, _reason in MAILS.values()),
        ]
    )
    signing.sign(lb, DAY, at="2026-03-03T08:00:00Z")
    _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: RULE}, "kari": {"max_tier": 2}})
    return lb


def _day_mails(lb: Logbook) -> dict[str, Line]:
    """The day's mail lines as the record holds them, by the test's names (in `MAILS`' order)."""
    found = [line for line in lb.lines() if line["kind"] == "mail" and str(line["at"]).startswith(DAY)]
    return dict(zip(MAILS, found[: len(MAILS)], strict=True))


def _rule(lb: Logbook, **inputs: frozenset[tuple[str, str]]) -> peoples_mail.Rule:
    with lb.index() as idx:
        return peoples_mail.Rule.of(lb, idx.retractions(), idx.resolutions(), **inputs)


JUNK = peoples_mail.Junk.of(RULE, "test")


# -- the rule -------------------------------------------------------------------------------------------


def test_each_mail_is_held_or_crosses_as_the_owner_s_rule_says(lb: Logbook) -> None:
    rule = _rule(lb, portfolio=orgs.portfolio_refs(lb))
    found = {name: rule.junk(line, JUNK) for name, line in _day_mails(lb).items()}
    assert found == {name: reason for name, (_m, reason) in MAILS.items()}


def test_the_category_alone_and_the_label_alone_are_each_a_signal(lb: Logbook) -> None:
    mails = _day_mails(lb)
    rule = _rule(lb)
    assert rule.junk(mails["shop"], JUNK) == peoples_mail.JUNK_CATEGORY
    assert rule.junk(mails["shop"], peoples_mail.Junk.of({"labels": [UNSUBSCRIBE]}, "t")) is None
    assert rule.junk(mails["club_imap"], peoples_mail.Junk.of({"categories": ["promotions"]}, "t")) is None


def test_an_imap_line_with_a_label_and_no_category_is_held_by_its_label(lb: Logbook) -> None:
    line = _day_mails(lb)["club_imap"]
    assert "gmail_category" not in (line["payload"].get("extra") or {})
    assert _rule(lb).junk(line, JUNK) == peoples_mail.JUNK_LABEL


def test_labels_and_categories_are_compared_case_aside(lb: Logbook) -> None:
    shouting = peoples_mail.Junk.of({"categories": ["PROMOTIONS"], "labels": ["triage/unsubscribe"]}, "t")
    mails = _day_mails(lb)
    assert _rule(lb).junk(mails["shop"], shouting) == peoples_mail.JUNK_CATEGORY
    assert _rule(lb).junk(mails["club_imap"], shouting) == peoples_mail.JUNK_LABEL


def test_a_person_of_the_record_spares_a_mail_but_only_as_its_sender(lb: Logbook) -> None:
    mails = _day_mails(lb)
    assert _rule(lb).junk(mails["kari_promo"], JUNK) is None  # exception a
    assert _rule(lb).junk(mails["cc_ola"], JUNK) == peoples_mail.JUNK_CATEGORY  # a cc is not the sender
    assert _rule(lb).junk(mails["own"], JUNK) == peoples_mail.JUNK_CATEGORY  # the owner is no person


def test_a_never_label_spares_a_mail(lb: Logbook) -> None:
    line = _day_mails(lb)["worth_a_look"]
    assert _rule(lb).junk(line, JUNK) is None  # exception b
    assert _rule(lb).junk(line, peoples_mail.Junk.of({"categories": ["promotions"]}, "t")) == "junk_category"


def test_an_invitation_platform_spares_a_mail(lb: Logbook) -> None:
    assert _rule(lb).junk(_day_mails(lb)["party"], JUNK) is None  # exception c
    assert peoples_mail.invitation("hosts@lu.ma") and peoples_mail.invitation("x@mail.evite.com")
    assert not peoples_mail.invitation("x@notevite.com") and not peoples_mail.invitation(SHOP)


def test_an_org_in_a_portfolio_spares_its_mail_and_only_while_it_is_in_one(lb: Logbook) -> None:
    line = _day_mails(lb)["robotics"]
    portfolio = orgs.portfolio_refs(lb)
    assert ("domain", ROBOTICS_DOMAIN) in portfolio
    assert _rule(lb, portfolio=portfolio).junk(line, JUNK) is None  # exception d, a domain under the org's
    assert _rule(lb).junk(line, JUNK) == peoples_mail.JUNK_CATEGORY  # without the portfolio: held, not sent
    lb.append(at="2026-03-04T09:00:00Z", source="manual", kind="status", tier=3,
              payload=_status(ROBOTICS_ID, "")["payload"])  # fmt: skip
    assert orgs.portfolio_refs(lb) == frozenset(), "an empty portfolio clears it"


def test_a_sender_hold_keeps_spares_a_mail(lb: Logbook) -> None:
    line = _day_mails(lb)["harbour"]
    assert _rule(lb).junk(line, JUNK) == peoples_mail.JUNK_LABEL
    assert _rule(lb, kept=frozenset({("email", HARBOUR)})).junk(line, JUNK) is None  # exception e
    assert _rule(lb, kept=frozenset({("domain", "example.org")})).junk(line, JUNK) is None


def test_let_go_beats_every_exception(lb: Logbook) -> None:
    """A sender let go is held whatever spares it: a person, a never-label, an invitation platform, an
    org in a portfolio, a kept sender; and with no category and no label at all."""
    mails = _day_mails(lb)
    let_go = frozenset({("email", KARI), ("email", STRANGER), ("domain", "mail.paperlesspost.com"),
                        ("email", ROBOTICS), ("email", HARBOUR)})  # fmt: skip
    rule = _rule(lb, let_go=let_go, kept=frozenset({("email", HARBOUR)}), portfolio=orgs.portfolio_refs(lb))
    for name in ("kari_promo", "worth_a_look", "party", "robotics", "harbour", "plain"):
        assert rule.junk(mails[name], JUNK) == peoples_mail.LET_GO, name
    assert rule.junk(mails["sent"], JUNK) is None, "a sent mail always crosses"


def test_sent_mail_always_crosses_and_unlabelled_mail_passes(lb: Logbook) -> None:
    mails = _day_mails(lb)
    assert _rule(lb).junk(mails["sent"], JUNK) is None
    assert _rule(lb).junk(mails["plain"], JUNK) is None
    assert _rule(lb).junk(mails["updates"], JUNK) is None  # a category and a label the rule does not name


def test_first_time_is_a_new_address_writing_and_never_a_no_reply_or_a_list(lb: Logbook) -> None:
    mails = _day_mails(lb)
    with lb.index() as idx:
        first = _rule(lb).first_times(idx, list(mails.values()))
    names = {name for name, line in mails.items() if str(line["id"]) in first}
    # Kari wrote in February; the shop's second mail is `cc_ola`; the stranger's first is `worth_a_look`;
    # a no-reply sender, the owner's own address, a list's mail and a sent mail are never a first time
    assert names == {"shop", "club_imap", "worth_a_look", "party", "robotics", "harbour"}


def test_first_time_reads_the_mails_time_not_the_order_they_were_imported(lb: Logbook) -> None:
    """A mail from the shop imported after the day's mails, dated a week before them, makes the shop's
    first mail of the day no first time; a mail from the club dated a day after changes nothing."""
    lb.append(**_mail("2026-02-22T09:00:00Z", SHOP))
    lb.append(**_mail("2026-03-02T09:00:00Z", CLUB))
    mails = _day_mails(lb)
    with lb.index() as idx:
        first = _rule(lb).first_times(idx, list(mails.values()), DAY)
    assert str(mails["shop"]["id"]) not in first
    assert str(mails["club_imap"]["id"]) in first


def test_a_mail_junk_entry_that_is_not_a_rule_is_refused_naming_the_file(lb: Logbook) -> None:
    for wrong in ([UNSUBSCRIBE], {"label": [UNSUBSCRIBE]}, {"labels": UNSUBSCRIBE}, {"labels": [""]}):
        _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: wrong}})
        with pytest.raises(policy.PolicyError, match=r"crossing\.json"):
            peoples_mail.junk_of(lb.root, DESTINATION)


# -- the crossing ---------------------------------------------------------------------------------------


def _export(out: Path, *args: str) -> None:
    cli.main(["export", "crossing", "--to", DESTINATION, "--since", SINCE, "--until", UNTIL,
              "--tier", "1,2", "--kinds", "mail", "--out", str(out), *args])  # fmt: skip


def _manifest(out: Path) -> dict[str, Any]:
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _crossed(out: Path) -> set[str]:
    text = (out / "entries.jsonl").read_text(encoding="utf-8")
    return {json.loads(row)["id"] for row in text.splitlines() if row.strip()}


def _tier_3(lb: Logbook) -> None:
    """The destination's entry raised to tier 3, so a crossing of tiers 1 to 3 reads the portfolio (a
    tier-3 status line) as the owner's rule asks; below it the crossing reads none (the door's rule)."""
    _write_policy(lb, {DESTINATION: {"max_tier": 3, peoples_mail.JUNK_KEY: RULE}, "kari": {"max_tier": 2}})


def test_all_except_junk_sends_every_mail_but_junk_and_counts_by_reason(lb: Logbook, tmp_path: Path) -> None:
    mails = _day_mails(lb)
    out = tmp_path / "out"
    _tier_3(lb)
    _export(out, "--mail", "all-except-junk", "--tier", "1,2,3")
    assert _crossed(out) == {str(line["id"]) for name, line in mails.items() if name not in HELD}
    manifest = _manifest(out)
    assert manifest["policy"]["mail"] == "all-except-junk"
    counts = manifest["counts"]
    assert counts["mail_held_back"] == len(HELD)
    assert counts["mail_held_by_reason"] == {"let_go": 0, "junk_category": 5, "junk_label": 2}
    assert counts["mail_held_first_time"] == len(FIRST_TIME_HELD)
    line = list(lb.lines())[-1]
    assert line["kind"] == "crossing"
    assert line["payload"]["counts"] == counts and line["payload"]["policy"]["mail"] == "all-except-junk"
    _no_one_in(json.dumps(counts))
    assert "Fund I" not in json.dumps(manifest) and "Fund I" not in json.dumps(line)


def test_the_dry_run_prints_the_same_counts(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _tier_3(lb)
    cli.main(["export", "crossing", "--to", DESTINATION, "--since", SINCE, "--until", UNTIL,
              "--tier", "1,2,3", "--mail", "all-except-junk", "--dry-run"])  # fmt: skip
    text = capsys.readouterr().out
    assert (
        "7 mail(s) held back by your mail_junk rule: 0 let go in Hold, 5 junk by category, 2 junk by label;"
        " 3 from a first-time sender (--mail all sends them)"
    ) in text
    _no_one_in(text)
    assert not (lb.root / "export").exists()


def test_without_mail_junk_the_mode_is_refused_and_nothing_is_exported(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    before = len(list(lb.lines()))
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "crossing", "--to", "kari", "--since", SINCE, "--until", UNTIL,
                  "--tier", "1,2", "--mail", "all-except-junk", "--out", str(out)])  # fmt: skip
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "--mail all-except-junk needs your own rule for junk" in err and '"mail_junk"' in err
    assert "nothing is exported" in err
    assert not out.exists() and len(list(lb.lines())) == before


def test_all_mail_is_mail_all_and_the_two_do_not_disagree(lb: Logbook, tmp_path: Path) -> None:
    _export(tmp_path / "flag", "--all-mail")
    _export(tmp_path / "word", "--mail", "all")
    assert (
        _crossed(tmp_path / "flag")
        == _crossed(tmp_path / "word")
        == {str(line["id"]) for line in _day_mails(lb).values()}
    )
    assert (
        _manifest(tmp_path / "flag")["policy"]["mail"]
        == _manifest(tmp_path / "word")["policy"]["mail"]
        == "all"
    )
    with pytest.raises(crossing.CrossingError, match="--all-mail is --mail all"):
        crossing.request(lb, DESTINATION, SINCE, UNTIL, (1, 2), all_mail=True, mail="people")


def test_people_mode_is_what_it_was(lb: Logbook, tmp_path: Path) -> None:
    """The default mode reads no junk rule: the package carries no junk counts and no `policy.mail`."""
    _export(tmp_path / "out")
    manifest = _manifest(tmp_path / "out")
    assert "mail" not in manifest["policy"] and "mail_held_by_reason" not in manifest["counts"]
    assert _crossed(tmp_path / "out") == {str(_day_mails(lb)["kari_promo"]["id"])}


# -- the door -------------------------------------------------------------------------------------------


def _door(lb: Logbook, mcp_tier: int, allow_tier_3: bool = False, **arguments: str) -> dict[str, Any]:
    """`held_mail` through the door, the `mcp` entry naming it (`"held_mail": true`) at `mcp_tier`."""
    _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: RULE}, "kari": {"max_tier": 2},
                       "mcp": {"max_tier": mcp_tier, peoples_mail.DOOR_KEY: True}})  # fmt: skip
    return mcp_server.call(lb.root, "held_mail", {"day": DAY, **arguments}, allow_tier_3=allow_tier_3)


def test_the_door_says_per_mail_whether_it_would_be_held(lb: Logbook) -> None:
    answer = _door(lb, 3, allow_tier_3=True)
    (found,) = answer["data"]["destinations"]
    assert found["destination"] == DESTINATION
    ids = {str(line["id"]): name for name, line in _day_mails(lb).items()}
    by_name = {ids[m["id"]]: m for m in found["mails"]}
    assert {n for n, m in by_name.items() if m["held"]} == HELD
    assert by_name["club_imap"] == {"id": by_name["club_imap"]["id"], "held": True, "reason": "junk_label",
                                    "first_time": True}  # fmt: skip
    assert found["held"] == len(HELD) and found["first_time"] == len(FIRST_TIME_HELD)
    assert "above_ceiling" not in answer["data"]
    _no_one_in(json.dumps(answer))


def test_the_door_never_reveals_a_mail_the_gate_withholds(lb: Logbook) -> None:
    """The ceiling at 1: one tier-1 mail is judged; the day's tier-2 mails are not listed, not counted
    among the held, and not counted at all, above the ceiling or in the gate's withheld (the owner, after
    #465: held mail above the entry's tiers is absent, not counted, not hinted at), nothing of them
    crossing, not even an id."""
    tier1 = lb.append(
        **_mail("2026-03-01T10:00:00Z", "deals@outlet.example.org", category="promotions", tier=1)
    )
    answer = _door(lb, 1)
    (found,) = answer["data"]["destinations"]
    assert [m["id"] for m in found["mails"]] == [str(tier1["id"])]
    assert found["mails"][0]["held"] is True and found["held"] == 1
    assert "above_ceiling" not in answer["data"]
    assert answer["gate"]["withheld"] == 0
    text = json.dumps(answer)
    assert all(str(line["id"]) not in text for line in _day_mails(lb).values())


def test_below_tier_three_the_door_tells_no_portfolio(lb: Logbook) -> None:
    """Through a gate without tier 3 no status line is read, so no portfolio spares a mail: the door
    says the org's mail would be held, as it says of any other, and never which orgs a portfolio holds."""
    (found,) = _door(lb, 2)["data"]["destinations"]
    robotics = [m for m in found["mails"] if m["id"] == str(_day_mails(lb)["robotics"]["id"])]
    assert robotics and robotics[0]["held"] is True and robotics[0]["reason"] == "junk_category"
    (found,) = _door(lb, 3, allow_tier_3=True)["data"]["destinations"]
    robotics = [m for m in found["mails"] if m["id"] == str(_day_mails(lb)["robotics"]["id"])]
    assert robotics[0]["held"] is False


def test_the_door_refuses_a_destination_without_a_rule(lb: Logbook) -> None:
    with pytest.raises(mcp_server.ToolError, match="no mail_junk rule"):
        _door(lb, 2, destination="kari")


def test_the_door_answers_held_mail_only_when_its_entry_names_it(lb: Logbook) -> None:
    """Held mail through the door only when the `mcp` entry names it (`"held_mail": true`), as a write
    tool is named under `write`: otherwise it is absent, the refusal one sentence that names the key and
    the file and says nothing of the day's mail, not an id, not a count."""
    for entry in ({"max_tier": 2}, {"max_tier": 2, peoples_mail.DOOR_KEY: False}):
        _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: RULE}, "mcp": entry})
        with pytest.raises(mcp_server.ToolError) as refused:
            mcp_server.call(lb.root, "held_mail", {"day": DAY})
        text = str(refused.value)
        assert f'"{peoples_mail.DOOR_KEY}": true' in text and "crossing.json" in text
        assert not re.search(r"\d", text.replace("crossing.json", "")), text
    _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: RULE},
                       "mcp": {"max_tier": 2, peoples_mail.DOOR_KEY: "yes"}})  # fmt: skip
    with pytest.raises(mcp_server.ToolError, match=r"crossing\.json"):
        mcp_server.call(lb.root, "held_mail", {"day": DAY})
    assert _door(lb, 2)["data"]["destinations"]


def test_held_mail_above_the_door_s_ceiling_leaves_no_trace_in_the_log(
    lb: Logbook, caplog: pytest.LogCaptureFixture
) -> None:
    """The log line of a call counts what the answer holds and what the gate withheld: for held mail at
    a ceiling below the day's mails, nothing is withheld that the log could count."""
    caplog.set_level(logging.INFO, logger="logbook.mcp")
    _door(lb, 1)
    (logged,) = [r.getMessage() for r in caplog.records if r.name == "logbook.mcp"]
    assert logged.startswith("held_mail") and "withheld=0" in logged and "above" not in logged


HEMMELIG, HEMMELIG_ID = "per.hemmelig@example.org", "019cadd3-6bc0-7dcd-9133-04aa00000005"


def test_a_crossing_below_tier_three_reads_no_portfolio(lb: Logbook, tmp_path: Path) -> None:
    """The portfolio is a tier-3 status line: a crossing of tiers 1 and 2 reads none, so the org's
    promotion is held like any other, and the counts tell nothing of the portfolio."""
    out = tmp_path / "out"
    _export(out, "--mail", "all-except-junk")
    robotics = str(_day_mails(lb)["robotics"]["id"])
    assert robotics not in _crossed(out)
    counts = _manifest(out)["counts"]
    assert counts["mail_held_back"] == len(HELD) + 1
    assert counts["mail_held_by_reason"]["junk_category"] == 6


def test_a_crossing_judges_a_first_time_sender_by_the_mails_at_its_tiers(lb: Logbook, tmp_path: Path) -> None:
    """An earlier mail from the shop at tier 3 does not cross to a destination of tiers 1 and 2, so it
    does not make the shop's mail of the day a known sender's there: the count is what it was."""
    _export(tmp_path / "before", "--mail", "all-except-junk")
    lb.append(**_mail("2026-02-25T09:00:00Z", SHOP, category="promotions", tier=3))
    _export(tmp_path / "after", "--mail", "all-except-junk")
    before = _manifest(tmp_path / "before")["counts"]["mail_held_first_time"]
    assert _manifest(tmp_path / "after")["counts"]["mail_held_first_time"] == before


def test_a_person_named_above_the_crossing_s_tiers_spares_no_mail(lb: Logbook, tmp_path: Path) -> None:
    """Per Hemmelig is a person only on a tier-3 resolution: to a destination of tiers 1 and 2 their
    promotion is a stranger's and held; with tier 3 asked for, it is a person's and crosses."""
    secret = _resolution(HEMMELIG, "Per Hemmelig", HEMMELIG_ID)
    secret["tier"] = 3
    lb.append(**secret)
    mail = lb.append(**_mail("2026-03-01T11:00:00Z", HEMMELIG, category="promotions"))
    _export(tmp_path / "low", "--mail", "all-except-junk")
    assert str(mail["id"]) not in _crossed(tmp_path / "low")
    _tier_3(lb)
    _export(tmp_path / "high", "--mail", "all-except-junk", "--tier", "1,2,3")
    assert str(mail["id"]) in _crossed(tmp_path / "high")


# -- day sign -------------------------------------------------------------------------------------------


def test_day_sign_says_per_destination_how_many_mails_were_held(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["day", "sign", DAY])
    text = capsys.readouterr().out
    assert f"{DESTINATION}: 7 mails held back (3 from a first-time sender)" in text
    assert "kari:" not in text  # a destination with no rule has no line
    _no_one_in(text)


def test_day_sign_says_when_a_rule_cannot_be_read(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _write_policy(lb, {DESTINATION: {"max_tier": 2, peoples_mail.JUNK_KEY: {"lables": [UNSUBSCRIBE]}}})
    cli.main(["day", "sign", DAY])
    text = capsys.readouterr().out
    assert f"{DESTINATION}: its mail_junk rule cannot be read, so nothing is counted" in text


def test_day_sign_says_nothing_of_mail_without_a_rule(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_policy(lb, {"kari": {"max_tier": 2}})
    cli.main(["day", "sign", DAY])
    assert "held back" not in capsys.readouterr().out


# -- no one in a count ----------------------------------------------------------------------------------

_ALT = "|".join(re.escape(n) for n in NAMES)
BESIDE = re.compile(rf"(\d[\s(:×x#·,\-]*(?:{_ALT}))|((?:{_ALT})\??[\s(:×x#·,\-]*\d)", re.I)


def _no_one_in(text: str) -> None:
    """No address, no subject, no name, and so no number beside a name (tests/test_no_count_beside_a_name)."""
    assert "@" not in text
    assert SUBJECT not in text
    assert not re.search(rf"\b(?:{_ALT})\b", text, re.I), text
    assert not BESIDE.search(text)
