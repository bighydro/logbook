"""A synthetic record for the org, idea and asset queues (RFC 0037 §4): Ines Nordmann of Oslo, who
does not exist, and what her sources saw of a yard, a kiosk, her family, an idea and two craft.

- **The yard**, Nordmann Verft AS: a canonical org minted the old way, a `resolution/v1` of type
  `company` on its domain (the frozen word, read as an org); three mails from Ola Nordmann at
  `nordmann-verft.example.org`, and a WhatsApp group named "Nordmann Verft" Ola writes in.
- **The kiosk**: two mails from `post@fjordkiosk.example.org` ("Fjordkiosk"), and three card payments
  to "FJORDKIOSK AS" (tier 3).
- **The family**: mails from Kari and Per Nordmann at `nordmann.example.org`; one from a public
  provider (`example.org`), which names nobody's org.
- **The idea**: a Notion page "The fjord kiosk" with a page under it, a task "Fjord kiosk", a
  transcript "The fjord kiosk" Ola spoke in, a repository on the code host `git.example.org` that a
  task links and the browser visited.
- **The craft**: the registry names the yacht Solvind and the aircraft Lerka (`ZZABC`); the AIS
  receiver kept reporting a hull the registry no longer names (MMSI 970123456, "GAMLE SOLVIND"), and
  three flights were on `ZZ-ABC`, Lerka's registration spelled another way."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER = {"name": "Ines Nordmann", "email": "ines@example.org"}
OLA = {"id": "019cadd3-6bc0-7dcd-9133-000000000111", "name": "Ola Nordmann",
       "email": "ola@nordmann-verft.example.org", "phone": "+447700900101"}  # fmt: skip
KARI = {
    "id": "019cadd3-6bc0-7dcd-9133-000000000112",
    "name": "Kari Nordmann",
    "email": "kari@nordmann.example.org",
}
YARD = {"id": "019cadd3-6bc0-7dcd-9133-000000000201", "label": "Nordmann Verft AS",
        "domain": "nordmann-verft.example.org"}  # fmt: skip
KIOSK_DOMAIN = "fjordkiosk.example.org"
FAMILY_DOMAIN = "nordmann.example.org"
CODE_HOST = "git.example.org"
REPO = f"{CODE_HOST}/nordmann-verft/kiosk"
ROOT_PAGE, CHILD_PAGE = "1f2e3d4c-0000-0000-0000-000000000031", "1f2e3d4c-0000-0000-0000-000000000032"
HULL_MMSI, HULL = "970123456", "gamle-solvind"
REGISTRY = {
    "assets": [
        {"id": "solvind", "kind": "yacht", "name": "Solvind", "mmsi": "970000001"},
        {"id": "lerka", "kind": "aircraft", "name": "Lerka", "registration": "ZZABC"},
    ]
}


def _at(day: int, hour: int = 10, minute: int = 0) -> str:
    return f"2026-09-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def _resolution(ref: tuple[str, str], kind: str, entity: str, label: str) -> dict[str, Any]:
    return {
        "at": "2026-08-01T08:00:00Z", "source": "manual", "kind": "resolution", "tier": 2,
        "payload": {"schema": "resolution/v1", "ref": {"kind": ref[0], "value": ref[1]},
                    "entity": {"type": kind, "id": entity, "registry": "logbook"}, "label": label,
                    "method": "owner"},
    }  # fmt: skip


def _mail(at: str, sender: dict[str, str], subject: str) -> dict[str, Any]:
    message_id = f"{at}.{sender['email']}"
    return {
        "at": at, "source": "mail", "kind": "mail", "tier": 2,
        "payload": {"schema": "mail/v1", "raw_id": f"mail:{message_id}", "message_id": message_id,
                    "thread": message_id, "from": {"email": sender["email"], "name": sender["name"]},
                    "to": [{"email": OWNER["email"], "name": OWNER["name"]}], "subject": subject,
                    "direction": "received", "size": 900},
    }  # fmt: skip


def _group_message(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at, "source": "whatsapp", "kind": "message", "tier": 2,
        "payload": {"schema": "message/v1", "raw_id": f"wa:{at}",
                    "chat": {"id": "120363000000000001@g.us", "type": "group", "name": "Nordmann Verft"},
                    "sender": {"kind": "phone", "value": OLA["phone"], "name": OLA["name"]},
                    "from_me": False, "text": text},
    }  # fmt: skip


def _payment(at: str, n: int) -> dict[str, Any]:
    return {
        "at": at, "source": "copilot", "kind": "transaction", "tier": 3,
        "payload": {"schema": "transaction/v1", "raw_id": f"copilot:{n}", "amount": -45.0, "currency": "NOK",
                    "merchant": "FJORDKIOSK AS", "provider": "copilot"},
    }  # fmt: skip


def _page(at: str, page: str, title: str, parent: dict[str, str]) -> dict[str, Any]:
    return {
        "at": at, "source": "notion", "kind": "event", "tier": 1,
        "payload": {"schema": "event/v1", "raw_id": f"{page}/{at[:10]}/created", "title": title,
                    "calendar": {"id": "notion", "name": "Notion"}, "all_day": False,
                    "extra": {"action": "created", "page": {"id": page}, "parent": parent,
                              "actor": {"id": "u-1", "name": OLA["name"], "type": "person"}}},
    }  # fmt: skip


def _task(at: str, title: str, links: list[str]) -> dict[str, Any]:
    extra = {"links": [{"type": "url", "url": url} for url in links]} if links else {}
    return {
        "at": at, "source": "gtasks", "kind": "task", "tier": 2,
        "payload": {"schema": "task/v1", "raw_id": f"gtasks:{at}", "title": title, "status": "open",
                    "list": "Ideas", **({"extra": extra} if extra else {})},
    }  # fmt: skip


def _transcript(at: str, title: str) -> dict[str, Any]:
    return {
        "at": at, "end": _at(int(at[8:10]), 11), "source": "granola", "kind": "transcript", "tier": 2,
        "payload": {"schema": "transcript/v1", "raw_id": f"granola:{at}", "title": title,
                    "participants": [{"name": OLA["name"], "email": OLA["email"]}]},
    }  # fmt: skip


def _hull(at: str, n: int) -> dict[str, Any]:
    return {
        "at": at, "source": "ais", "kind": "location", "tier": 1,
        "payload": {"schema": "location/v1", "raw_id": f"aisstream:{HULL_MMSI}:{n}", "lat": 59.9 + n / 1000,
                    "lon": 10.7, "subject": HULL, "tracker": "aisstream",
                    "extra": {"mmsi": HULL_MMSI, "ship_name": "GAMLE SOLVIND"}},
    }  # fmt: skip


def _flight(day: int, number: str) -> dict[str, Any]:
    return {
        "at": _at(day, 7), "end": _at(day, 8), "source": "flighty", "kind": "flight", "tier": 1, "tz": TZ,
        "payload": {"schema": "flight/v1", "raw_id": f"flighty:{day}:{number}", "date": f"2026-09-{day:02d}",
                    "carrier": "XY", "number": number, "from": "OSL", "to": "BGO",
                    "aircraft": {"registration": "ZZ-ABC"}, "evidence": "tracked", "role": "passenger"},
    }  # fmt: skip


def drafts() -> list[dict[str, Any]]:
    found = [
        _resolution(("domain", YARD["domain"]), "company", YARD["id"], YARD["label"]),
        _resolution(("email", OLA["email"]), "person", OLA["id"], OLA["name"]),
        _resolution(("phone", OLA["phone"]), "person", OLA["id"], OLA["name"]),
        _resolution(("email", KARI["email"]), "person", KARI["id"], KARI["name"]),
    ]
    found += [_mail(_at(d), OLA, f"Q3 numbers, part {d}") for d in (1, 2, 3)]
    found += [
        _mail(_at(d, 12), {"name": "Fjordkiosk", "email": f"post@{KIOSK_DOMAIN}"}, "Opening") for d in (4, 6)
    ]
    found += [
        _mail(_at(5, 9), KARI, "Sunday"),
        _mail(_at(5, 9, 30), {"name": "Per Nordmann", "email": f"per@{FAMILY_DOMAIN}"}, "Re: Sunday"),
    ]
    found += [_mail(_at(5, 13), {"name": "Liv Berg", "email": "liv.berg@example.org"}, "Hello")]
    found += [_group_message(_at(d, 15, m), "launch slip") for d, m in ((2, 0), (3, 0), (3, 5))]
    found += [_payment(_at(d, 17), d) for d in (7, 8, 9)]
    found += [
        _page(_at(5, 20), ROOT_PAGE, "The fjord kiosk", {"type": "workspace", "id": "workspace"}),
        _page(_at(10, 20), CHILD_PAGE, "Kiosk / Pricing", {"type": "page", "id": ROOT_PAGE}),
        _task(_at(11, 8), "Fjord kiosk", []),
        _task(_at(12, 8), "Fix the kiosk build", [f"https://{REPO}/issues/1"]),
        _transcript(_at(11, 10), "The fjord kiosk"),
        {"at": _at(12, 9), "source": "chrome", "kind": "browse", "tier": 2,
         "payload": {"schema": "browse/v1", "raw_id": "chrome:1:abc", "url": f"https://{REPO}",
                     "action": "visit", "browser": "chrome"}},
    ]  # fmt: skip
    found += [_hull(_at(14, 6, n), n) for n in range(3)]
    found += [_flight(d, n) for d, n in ((15, "561"), (18, "562"), (21, "563"))]
    return found


def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The record under `tmp_path`, found through LOGBOOK_HOME, its registry and code host set."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([OWNER["email"]])
    (lb.root / "assets.json").write_text(json.dumps(REGISTRY, indent=2) + "\n", encoding="utf-8")
    policy = lb.root / "policy"
    policy.mkdir(exist_ok=True)
    (policy / "entities.json").write_text(json.dumps({"code_hosts": [CODE_HOST]}) + "\n", encoding="utf-8")
    lb.append_many(drafts())
    return lb
