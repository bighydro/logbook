"""A record of companies the owner invested in or passed on, for `show orgs`, `show org NAME` and the
Manifest. Nobody and nothing here exists: the owner is Ines Nordmann of Oslo; every address is at
example.org (a company's at a subdomain of it, which RFC 2606 reserves with the rest of the
domain); phone numbers are in the UK block 07700 900xxx; the code host is `git.example.org`.

**The evidence** (`evidence_drafts`), what the sources saw before the owner said anything:

- **Nordmann Verft AS** (`nordmann-verft.example.org`): mail from the company's own address and
  from Ola Nordmann, a board meeting Ola, Per and Liv attend, a WhatsApp group named "Nordmann
  Verft", and one wire to "Nordmann Verft AS" in the ledger (a merchant seen once: noise).
- **Fjordkiosk AS** (`fjordkiosk.example.org`): a pitch in March and April 2026 — mail from Kari
  Nordmann, a meeting with Kari and Per, its transcript — then nothing.
- **Nordmann Tidevann AS** (`tidevann.example.org`): Per introduces Ines to Liv Berg by mail
  ("Intro: Ines <> Liv (Tidevann)"), mail from Liv, a demo with Liv and Per, and the code-host org
  `nordmann-tidevann` browsed and synced.
- **Nordmann Havbris AS** (`havbris.example.org`): mail from Anders Vik in 2023, three payments to
  "NORDMANN HAVBRIS AS", and nothing since: a hold that has gone stale.
- Noise for the queue: a newsletter (`nytt.example.org`), a company not yet named
  (`robaat.example.org`), and a family's own domain (`nordmann.example.org`, Eva Nordmann).

**The owner's say** (`settle`), written through the functions `review org` and `status` call, at
fixed instants: the four domains named as the four orgs, the group, the code-host org and the
merchant accepted for theirs; Nordmann Verft hold, Fjordkiosk passed (with its reason), Tidevann
hold then add, Havbris hold. Left in the queue: the newsletter, the unnamed company and the family's
domain."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from persona import attendee, event, transcript, utc

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER = {"name": "Ines Nordmann", "email": "ines.nordmann@example.org", "phone": "+447700900300"}
VERFT, KIOSK, TIDEVANN, HAVBRIS = (
    "Nordmann Verft AS",
    "Fjordkiosk AS",
    "Nordmann Tidevann AS",
    "Nordmann Havbris AS",
)
VERFT_DOMAIN = "nordmann-verft.example.org"
KIOSK_DOMAIN = "fjordkiosk.example.org"
TIDEVANN_DOMAIN = "tidevann.example.org"
HAVBRIS_DOMAIN = "havbris.example.org"
NEWS_DOMAIN = "nytt.example.org"
ROBAAT_DOMAIN = "robaat.example.org"
FAMILY_DOMAIN = "nordmann.example.org"
CODE_HOST = "git.example.org"
CODE_ORG = f"{CODE_HOST}/nordmann-tidevann"
GROUP = "Nordmann Verft"
GROUP_CHAT = "120363000000000002@g.us"
HAVBRIS_MERCHANT = "NORDMANN HAVBRIS AS"
PASSED_REASON = "good team, but a kiosk is a place and I do not want to own places"
VERFT_REASON = "led the seed with Per"
TODAY = "2026-10-12"  # the owner's sitting, and the day every reader is read on


def _person(n: int, name: str, email: str) -> dict[str, Any]:
    return {
        "id": f"019cadd3-6bc0-7dcd-9133-0000000003{n:02d}",
        "name": name,
        "email": email,
        "phone": f"+4477009003{n:02d}",
    }


PER = _person(1, "Per Hansen", "per.hansen@example.org")
OLA = _person(2, "Ola Nordmann", f"ola.nordmann@{VERFT_DOMAIN}")
LIV = _person(3, "Liv Berg", f"liv.berg@{TIDEVANN_DOMAIN}")
KARI = _person(4, "Kari Nordmann", f"kari.nordmann@{KIOSK_DOMAIN}")
ANDERS = _person(5, "Anders Vik", f"anders.vik@{HAVBRIS_DOMAIN}")
PEOPLE = (PER, OLA, LIV, KARI, ANDERS)
NEWS = {"name": "Nordmann Nytt", "email": f"news@{NEWS_DOMAIN}"}  # a newsletter in its own name
EVA = {"name": "Eva Nordmann", "email": f"eva@{FAMILY_DOMAIN}"}  # the family's own domain


def resolution(
    ref: tuple[str, str], entity_id: str, label: str, source: str = "ios-contacts"
) -> dict[str, Any]:
    return {
        "at": "2023-01-02T08:00:00Z",
        "source": source,
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": ref[0], "value": ref[1]},
            "entity": {"type": "person", "id": entity_id, "registry": "logbook"},
            "label": label,
            "method": "owner",
            "raw_id": f"{ref[0]}:{ref[1]}",
        },
    }


def mail(
    at: str,
    sender: dict[str, Any],
    to: list[dict[str, Any]],
    subject: str,
    cc: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message_id = f"{at}.{sender['email']}"
    payload: dict[str, Any] = {
        "schema": "mail/v1",
        "raw_id": f"{OWNER['email']}:{message_id}",
        "message_id": message_id,
        "thread": message_id,
        "from": {"email": sender["email"], "name": sender["name"]},
        "to": [{"email": p["email"], "name": p["name"]} for p in to],
        "subject": subject,
        "direction": "sent" if sender is OWNER else "received",
        "size": 1200,
    }
    if cc:
        payload["cc"] = [{"email": p["email"], "name": p["name"]} for p in cc]
    return {"at": at, "source": "mail", "kind": "mail", "tier": 2, "payload": payload}


def meeting(at: str, end: str, title: str, people: list[dict[str, Any]]) -> dict[str, Any]:
    line = event(at, end, title, [attendee(p["email"], p["name"]) for p in people])
    line["payload"]["calendar"] = {"id": "work-1", "name": "Work"}
    line["payload"]["organizer"] = {"kind": "email", "value": OWNER["email"]}
    return line


def group_message(at: str, sender: dict[str, Any], text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "whatsapp",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"m-{at}-{GROUP_CHAT}",
            "chat": {"id": GROUP_CHAT, "type": "group", "name": GROUP},
            "from_me": False,
            "text": text,
            "sender": {"kind": "phone", "value": sender["phone"], "name": sender["name"].split()[0]},
        },
    }


def wire(at: str, merchant: str, amount: float, raw_id: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "copilot",
        "kind": "transaction",
        "tier": 3,
        "payload": {
            "schema": "transaction/v1",
            "raw_id": raw_id,
            "amount": amount,
            "currency": "NOK",
            "merchant": merchant,
            "provider": "copilot",
            "status": "posted",
        },
    }


def browse(at: str, url: str, title: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "safari",
        "kind": "browse",
        "tier": 2,
        "payload": {"schema": "browse/v1", "raw_id": f"b-{at}", "url": url, "title": title},
    }


def github_act(at: str, repo: str, title: str) -> dict[str, Any]:
    """An act as `sync github` writes it, read from the code host `git.example.org`."""
    return {
        "at": at,
        "source": "github",
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"{repo}/pull/12/merged",
            "title": title,
            "calendar": {"id": "github", "name": "GitHub"},
            "all_day": False,
            "extra": {
                "action": "merged",
                "repo": repo,
                "pull": {"number": 12, "url": f"https://{CODE_HOST}/{repo}/pull/12"},
            },
        },
    }


def evidence_drafts(owner_id: str) -> list[dict[str, Any]]:
    """Every line the sources wrote, in a plausible import order: the address book, then the rest."""
    drafts: list[dict[str, Any]] = [
        resolution(("email", OWNER["email"]), owner_id, OWNER["name"], "manual"),
        resolution(("phone", OWNER["phone"]), owner_id, OWNER["name"], "manual"),
    ]
    for p in PEOPLE:
        drafts.append(resolution(("email", p["email"]), p["id"], p["name"]))
        drafts.append(resolution(("phone", p["phone"]), p["id"], p["name"]))
    verft_post = {"name": "Nordmann Verft", "email": f"post@{VERFT_DOMAIN}"}
    drafts += [
        # Nordmann Verft AS
        mail(utc("2026-03-02", "08:00"), verft_post, [OWNER], "Shareholder letter"),
        mail(utc("2026-09-02", "09:15"), OLA, [OWNER], "Q3 numbers"),
        mail(utc("2026-10-09", "16:40"), OLA, [OWNER, PER], "Board pack October"),
        meeting(utc("2026-09-15", "15:00"), utc("2026-09-15", "17:00"), "Verft board", [OLA, PER, LIV]),
        group_message(utc("2026-09-15", "18:30"), OLA, "Thanks all"),
        group_message(utc("2026-10-09", "17:00"), OLA, "Pack is out"),
        wire(utc("2026-04-02", "11:00"), VERFT, -250000, "wire-verft-1"),
        # Fjordkiosk AS
        mail(utc("2026-03-30", "10:00"), KARI, [OWNER], "Pitch deck"),
        meeting(utc("2026-04-10", "10:00"), utc("2026-04-10", "11:00"), "Fjordkiosk pitch", [KARI, PER]),
        transcript(
            utc("2026-04-10", "10:00"),
            utc("2026-04-10", "11:00"),
            "Fjordkiosk pitch",
            [
                {"name": KARI["name"], "email": KARI["email"]},
                {"name": PER["name"], "email": PER["email"]},
                {"name": "me"},
            ],
        ),
        mail(utc("2026-04-20", "12:00"), KARI, [OWNER], "Follow-up"),
        # Nordmann Tidevann AS
        mail(utc("2026-05-04", "09:00"), PER, [OWNER], "Intro: Ines <> Liv (Tidevann)", cc=[LIV]),
        mail(utc("2026-05-10", "14:00"), LIV, [OWNER], "Deck and numbers"),
        meeting(utc("2026-06-01", "13:00"), utc("2026-06-01", "14:00"), "Tidevann demo", [LIV, PER]),
        browse(utc("2026-06-02", "20:00"), f"https://{CODE_ORG}/tide-clock", "tide-clock"),
        browse(utc("2026-06-03", "21:00"), f"https://{CODE_ORG}/tide-clock/issues", "Issues"),
        github_act(utc("2026-09-20", "12:00"), "nordmann-tidevann/tide-clock", "Merged pull request #12"),
        mail(utc("2026-10-01", "08:30"), LIV, [OWNER], "Follow-on round"),
        # Nordmann Havbris AS: 2023, then silence
        mail(utc("2023-05-01", "09:00"), ANDERS, [OWNER], "Havbris seed"),
        mail(utc("2023-06-10", "09:00"), ANDERS, [OWNER], "Signed"),
        wire(utc("2023-06-12", "10:00"), HAVBRIS_MERCHANT, -100000, "wire-havbris-1"),
        wire(utc("2023-06-13", "10:00"), HAVBRIS_MERCHANT, -20000, "wire-havbris-2"),
        wire(utc("2023-07-01", "10:00"), HAVBRIS_MERCHANT, 5000, "wire-havbris-3"),
        # noise for the queue
        mail(utc("2026-08-01", "06:00"), NEWS, [OWNER], "Weekly"),
        mail(utc("2026-08-08", "06:00"), NEWS, [OWNER], "Weekly"),
        mail(
            utc("2026-08-12", "11:00"),
            {"name": "Nordmann Robåt", "email": f"post@{ROBAAT_DOMAIN}"},
            [OWNER],
            "Introducing Nordmann Robåt",
        ),
        mail(utc("2026-08-20", "19:00"), EVA, [OWNER], "Sunday dinner"),
    ]  # fmt: skip
    return drafts


def evidence_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> Logbook:
    """The evidence alone, under `tmp_path / "lb"`, found through LOGBOOK_HOME when `monkeypatch`."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    if monkeypatch is not None:
        monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
        monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb.set_owner_emails([OWNER["email"]])
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    settings = {"code_hosts": [CODE_HOST, "github.com"]}
    (policy / "entities.json").write_text(json.dumps(settings) + "\n", encoding="utf-8")
    lb.append_many(evidence_drafts(str(lb.meta["owner_id"])))
    return lb


def clock(minute: int) -> Iterator[str]:
    """Fixed instants on the sitting's day, a minute apart."""
    for m in range(minute, 60):
        yield f"{TODAY}T18:{m:02d}:00Z"


def settle(lb: Logbook) -> None:
    """The owner's sitting, through the functions `review org` and `status` call (the Manifest's
    acts call the same), at fixed instants and with fixed minted ids."""
    from logbook.contrib import entity_review, entity_status

    instants = clock(0)
    minted = (f"019cadd3-6bc0-7dcd-9133-0000000002{n:02d}" for n in range(1, 100))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(entity_review, "now_utc", lambda: next(instants))
        mp.setattr(entity_review, "uuid7", lambda: next(minted))
        for domain, label in (
            (VERFT_DOMAIN, VERFT),
            (KIOSK_DOMAIN, KIOSK),
            (TIDEVANN_DOMAIN, TIDEVANN),
            (HAVBRIS_DOMAIN, HAVBRIS),
        ):
            report = entity_review.read(lb, "org")
            [p] = [p for p in report.proposals if p.new and p.observed.key == ("domain", domain)]
            entity_review.accept(lb, report, [(p, label)])
        for key in (("group", "nordmann verft"), ("repo", CODE_ORG), ("merchant", "nordmann havbris as")):
            report = entity_review.read(lb, "org")
            [p] = [p for p in report.proposals if not p.new and p.observed.key == key]
            entity_review.accept(lb, report, [(p, None)])
    for label, status, reason, day in (
        (VERFT, "hold", VERFT_REASON, "2026-04-02"),
        (KIOSK, "passed", PASSED_REASON, "2026-06-14"),
        (TIDEVANN, "hold", "first cheque", "2026-06-05"),
        (TIDEVANN, "add", "follow-on with Per", "2026-10-02"),
        (HAVBRIS, "hold", None, "2023-06-15"),
    ):
        entity_status.write(lb, "org", label, status, reason, at=day, today=TODAY)


def settled_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch | None = None) -> Logbook:
    lb = evidence_record(tmp_path, monkeypatch)
    settle(lb)
    return lb
