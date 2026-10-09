"""`logbook promises` over mail and messages: the owner's own commitments told from the requests made
to them by who wrote the line, with the rules alone. The fixture is the Oslo persona's fortnight
(`tests/fixtures/promises/wider-net.json`): 24 planted commitments and 12 planted requests across
mail, iMessage, WhatsApp and one transcript, among 60 distractor lines; nobody in it exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import resolution

from logbook import cli
from logbook.contrib import promises
from logbook.core import attachments, policy
from logbook.core.store import Logbook

FIXTURE = Path(__file__).parent / "fixtures" / "promises" / "wider-net.json"
MIN_PROMISES, MIN_REQUESTS, MIN_PRECISION = 20, 10, 0.8


def _doc() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _person(doc: dict[str, Any], key: str) -> dict[str, str]:
    return doc["people"][key]


def _mail(doc: dict[str, Any], entry: dict[str, Any], n: int) -> dict[str, Any]:
    sender = _person(doc, entry["from"])
    recipients = [_person(doc, key) for key in entry["to"]]
    owner_mail = sender["email"] == _person(doc, "owner")["email"]
    direction = entry.get("direction") or ("sent" if owner_mail else "received")
    return {
        "at": entry["at"],
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"ines@example.org:m{n}@mail.example.org",
            "message_id": f"m{n}@mail.example.org",
            "thread": f"m{n}@mail.example.org",
            "from": {"email": sender["email"], "name": sender["name"]},
            "to": [{"email": p["email"], "name": p["name"]} for p in recipients],
            "subject": entry["subject"],
            "direction": direction,
            "body": entry["body"],
            "size": 1000 + len(entry["body"]),
        },
    }


def _message(doc: dict[str, Any], entry: dict[str, Any], n: int) -> dict[str, Any]:
    other = _person(doc, entry["chat"])
    whatsapp = entry["source"] == "whatsapp"
    chat_id = f"{other['phone'].lstrip('+')}@s.whatsapp.net" if whatsapp else other["phone"]
    payload: dict[str, Any] = {
        "schema": "message/v1",
        "raw_id": f"{entry['source']}-{n}",
        "chat": {"id": chat_id, "type": "direct", "name": other["name"].split()[0]},
        "from_me": bool(entry["from_me"]),
        "text": entry["text"],
    }
    if not entry["from_me"]:
        sender = _person(doc, entry["sender"])
        payload["sender"] = {"kind": "phone", "value": sender["phone"], "name": sender["name"].split()[0]}
    return {"at": entry["at"], "source": entry["source"], "kind": "message", "tier": 2, "payload": payload}


def _transcript(doc: dict[str, Any], entry: dict[str, Any], blob: bytes) -> dict[str, Any]:
    return {
        "at": entry["at"],
        "end": entry["end"],
        "source": "granola",
        "kind": "transcript",
        "tier": 2,
        "payload": {
            "schema": "transcript/v1",
            "provider": "granola",
            "raw_id": f"t-{entry['at']}",
            "title": entry["title"],
            "participants": [
                {"name": _person(doc, key)["name"], "email": _person(doc, key)["email"]}
                for key in entry["participants"]
            ],
            "content": attachments.reference(blob, "text/markdown"),
        },
    }


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, dict[str, Any], list[Any]]:
    """The fixture as a record: the owner from `logbook.json` and `policy/owner.json`, three people
    resolved, every line appended in fixture order; returns the record, the fixture and the lines
    appended, in order."""
    doc = _doc()
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    meta = lb.meta
    meta["owner_id"] = doc["owner"]["id"]
    meta["owner_emails"] = list(doc["owner"]["emails"])
    lb._save_meta(meta)
    policy.write_default_owner(lb.root).write_text(json.dumps(doc["owner"]["policy"]), encoding="utf-8")
    drafts: list[dict[str, Any]] = [
        resolution(("email", _person(doc, "owner")["email"]), doc["owner"]["id"], "Ines Nordmann")
    ]
    for key in ("ola", "kari", "mia"):
        who = _person(doc, key)
        drafts.append(resolution(("email", who["email"]), who["id"], who["name"]))
        drafts.append(resolution(("phone", who["phone"]), who["id"], who["name"]))
    for n, entry in enumerate(doc["lines"]):
        if entry["kind"] == "mail":
            drafts.append(_mail(doc, entry, n))
        elif entry["kind"] == "message":
            drafts.append(_message(doc, entry, n))
        else:
            blob = entry["text"].encode("utf-8")
            lb.attach(blob)
            drafts.append(_transcript(doc, entry, blob))
    lb.append_many(drafts)
    return lb, doc, list(lb.lines())[-len(doc["lines"]) :]


def _planted(doc: dict[str, Any], lines: list[Any]) -> dict[str, set[tuple[str, str]]]:
    """role → {(line id, quote)} as planted."""
    out: dict[str, set[tuple[str, str]]] = {"promise": set(), "request": set()}
    for entry, line in zip(doc["lines"], lines, strict=True):
        for planted in entry["planted"]:
            out[planted["role"]].add((str(line["id"]), planted["quote"]))
    return out


def _found(report: promises.Report) -> dict[str, set[tuple[str, str]]]:
    out: dict[str, set[tuple[str, str]]] = {"promise": set(), "request": set()}
    for p in report.proposals:
        if p.role in out:
            out[p.role].add((p.line, p.match.quote))
    return out


def test_the_fixture_is_the_one_the_task_asked_for() -> None:
    doc = _doc()
    planted = [p for entry in doc["lines"] for p in entry["planted"]]
    assert sum(p["role"] == "promise" for p in planted) == 24
    assert sum(p["role"] == "request" for p in planted) == 12
    assert sum(not entry["planted"] for entry in doc["lines"]) == 60
    assert {entry["kind"] for entry in doc["lines"]} == {"mail", "message", "transcript"}
    assert sum(entry["kind"] == "transcript" for entry in doc["lines"]) == 1
    text = FIXTURE.read_text(encoding="utf-8")
    assert "@example.org" in text and "gmail" not in text.casefold()


def test_recall_and_precision_over_mail_messages_and_the_transcript(
    record: tuple[Logbook, dict[str, Any], list[Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    lb, doc, lines = record
    planted, found = _planted(doc, lines), _found(promises.extract(lb))
    hit = {role: planted[role] & found[role] for role in planted}
    proposed = len(found["promise"]) + len(found["request"])
    precision = (len(hit["promise"]) + len(hit["request"])) / proposed if proposed else 0.0
    with capsys.disabled():
        print(
            f"\npromises recall {len(hit['promise'])}/{len(planted['promise'])}, "
            f"requests recall {len(hit['request'])}/{len(planted['request'])}, "
            f"precision {precision:.2f} ({len(hit['promise']) + len(hit['request'])} of {proposed} proposed)"
        )
        for role in ("promise", "request"):
            for _line, quote in sorted(planted[role] - found[role], key=lambda t: t[1]):
                print(f"  missed {role}: {quote}")
            for _line, quote in sorted(found[role] - planted[role], key=lambda t: t[1]):
                print(f"  false {role}: {quote}")
    assert len(hit["promise"]) >= MIN_PROMISES
    assert len(hit["request"]) >= MIN_REQUESTS
    assert precision >= MIN_PRECISION


def test_direction_comes_from_who_wrote_the_line(record: tuple[Logbook, dict[str, Any], list[Any]]) -> None:
    lb, _doc, _lines = record
    by_quote = {p.match.quote: p for p in promises.extract(lb).proposals}
    mine = by_quote["I'll send the mooring photos by Friday."]  # mail the owner sent
    assert mine.role == "promise" and mine.kind == "mail" and mine.counterpart == "Ola Nordmann"
    assert mine.speaker is not None and mine.speaker.owner and mine.direction == "owed_by_owner"
    alias = by_quote[
        "We'll bring the spare anchor on Saturday."
    ]  # sent from the alias policy/owner.json names
    assert alias.role == "promise" and alias.counterpart == "Ola Nordmann"
    asked = by_quote["Can you send me the berth number before Friday?"]  # mail the owner received
    assert asked.role == "request" and asked.counterpart == "Ola Nordmann" and asked.kind == "mail"
    assert asked.speaker is not None and not asked.speaker.owner and asked.due == "2026-06-12"
    chat = by_quote["Schick mir die Fotos vom Anleger."]  # a message received, the sender resolved by phone
    assert chat.role == "request" and chat.counterpart == "Ola Nordmann" and chat.source == "imessage"
    sent = by_quote["Will do, by Friday."]  # a message sent: the counterpart is the chat's one other person
    assert sent.role == "promise" and sent.counterpart == "Kari Nordmann" and sent.source == "whatsapp"
    meeting = by_quote["Kannst du die Zahlen bis Mittwoch nachreichen?"]  # Ola's turn in the transcript
    assert (
        meeting.role == "request" and meeting.counterpart == "Ola Nordmann" and meeting.kind == "transcript"
    )
    minutes = by_quote["I'll write up the minutes tonight."]  # the owner's turn
    assert minutes.role == "promise" and minutes.counterpart == "Ola Nordmann"
    theirs = by_quote[
        "I'll send you the photos tonight."
    ]  # Ola's own commitment: not the owner's, not a request
    assert theirs.role == "theirs" and theirs.direction == "owed_to_owner"
    assert "Can you send me the invoice?" not in by_quote  # the owner asking: neither section
    assert "Let me know if Friday works for you." not in by_quote
    assert "I'll send you the photos tonight." in by_quote
    quoted = [q for q in by_quote if "berth number" in q]  # a quoted reply is never read as a new promise
    assert quoted == ["Can you send me the berth number before Friday?"]


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def test_the_text_has_two_sections_with_counterpart_and_line_id(
    record: tuple[Logbook, dict[str, Any], list[Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _doc, _lines = record
    out = _run(capsys, "promises")
    rows = out.splitlines()
    assert "I promised" in rows and "I was asked" in rows
    assert rows.index("I promised") < rows.index("I was asked")
    assert "not facts" in rows[0] and "day sign" in rows[0]
    by_quote = {p.match.quote: p for p in promises.extract(lb).proposals}
    mine = by_quote["I'll send the mooring photos by Friday."]
    row = next(r for r in rows if "mooring photos" in r)
    assert rows.index(row) > rows.index("I promised") and rows.index(row) < rows.index("I was asked")
    assert "2026-06-08" in row and "Ola Nordmann" in row and mine.id in row and mine.line in row
    asked = by_quote["Kannst du mir die Flugnummer schicken?"]
    row = next(r for r in rows if "Flugnummer" in r)
    assert rows.index(row) > rows.index("I was asked") and "Kari Nordmann" in row and asked.line in row
    assert "I'll send you the photos tonight." not in out  # others' commitments only under --all
    assert "I'll send you the photos tonight." in _run(capsys, "promises", "--all")


def test_mine_theirs_source_and_since_narrow_the_report(
    record: tuple[Logbook, dict[str, Any], list[Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    mine = _run(capsys, "promises", "--mine")
    assert "I promised" in mine and "I was asked" not in mine and "Flugnummer" not in mine
    theirs = _run(capsys, "promises", "--theirs")
    assert "I was asked" in theirs and "I promised" not in theirs and "mooring photos" not in theirs
    mail = json.loads(_run(capsys, "promises", "--source", "mail", "--json"))
    assert mail["sources"] == ["mail"] and {p["kind"] for p in mail["proposals"]} == {"mail"}
    both = json.loads(_run(capsys, "promises", "--source", "message,transcript", "--json"))
    assert both["sources"] == ["message", "transcript"]
    assert {p["kind"] for p in both["proposals"]} == {"message", "transcript"}
    assert all(p["role"] in ("promise", "request") for p in both["proposals"])
    since = json.loads(_run(capsys, "promises", "--since", "2026-06-15", "--json"))
    assert since["since"] == "2026-06-15" and all(p["day"] >= "2026-06-15" for p in since["proposals"])
    narrowed = json.loads(_run(capsys, "promises", "--mine", "--json"))
    assert narrowed["mine_only"] is True and all(p["role"] == "promise" for p in narrowed["proposals"])
    row = next(p for p in narrowed["proposals"] if "mooring" in p["quote"])
    assert row["counterpart"] == "Ola Nordmann" and row["kind"] == "mail" and row["role"] == "promise"
    with pytest.raises(SystemExit) as e:
        cli.main(["promises", "--source", "calendar"])
    assert e.value.code == 2
    assert "calendar" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["promises", "--mine", "--theirs"])
    assert e.value.code == 2


def test_a_promise_in_a_message_closes_like_any_other(
    record: tuple[Logbook, dict[str, Any], list[Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _doc, _lines = record
    by_quote = {p.match.quote: p for p in promises.extract(lb).proposals}
    found = by_quote["Ich kümmere mich um den Kran."]
    seq = lb.meta["seq"]
    out = _run(capsys, "promises", "done", found.id)
    assert f"#{seq + 1}" in out and "Kran" in out
    task = lb.line_by_seq(seq + 1)
    assert task is not None and task["payload"]["extra"]["origin"] == found.line
    assert task["payload"]["extra"]["speaker"] == "Ines Nordmann"
    assert lb.verify()[2] == []
    assert found.id not in {
        p["id"] for p in json.loads(_run(capsys, "promises", "--open", "--json"))["proposals"]
    }


# -- the signed day's dispositions (RFC 0034, amendment 1) hold on both sections ------------------------


def test_a_signed_day_closes_a_request_or_a_promise_by_its_line_and_the_row_says_so(
    record: tuple[Logbook, dict[str, Any], list[Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.core import signing

    lb, _doc, _lines = record
    by_quote = {p.match.quote: p for p in promises.extract(lb).proposals}
    asked = by_quote["Kannst du mir die Flugnummer schicken?"]  # a mail received on the 10th
    mine = by_quote["Ich kümmere mich um den Kran."]  # a message sent on the 9th
    kept = signing.sign(lb, asked.day, at="2026-06-20T08:00:00Z", dispositions={"kept": [asked.line]})
    signing.sign(lb, mine.day, at="2026-06-20T08:01:00Z", dispositions={"carried": [mine.line]})
    out = json.loads(_run(capsys, "promises", "--all", "--json"))
    by_id = {p["id"]: p for p in out["proposals"]}
    assert by_id[asked.id]["role"] == "request" and by_id[asked.id]["status"] == "done"
    assert by_id[asked.id]["disposition"] == {"value": "kept", "day": asked.day, "line": kept["id"]}
    assert by_id[asked.id]["counterpart"] == "Kari Nordmann" and by_id[asked.id]["closed_by"] is None
    assert by_id[mine.id]["role"] == "promise" and by_id[mine.id]["status"] == "open"
    assert by_id[mine.id]["disposition"]["value"] == "carried"
    text = _run(capsys, "promises")
    rows = text.splitlines()
    row = next(r for r in rows if asked.id in r)
    assert rows.index(row) > rows.index("I was asked") and row.rstrip().endswith(
        f"kept  {asked.id}  line {asked.line}"
    )
    row = next(r for r in rows if mine.id in r)
    assert rows.index("I promised") < rows.index(row) < rows.index("I was asked") and "carried" in row
    open_text = _run(capsys, "promises", "--open")
    assert "Flugnummer" not in open_text and "Kran" in open_text
    seq = lb.meta["seq"]
    out_text = _run(capsys, "promises", "done", asked.id)
    assert "already kept" in out_text and lb.meta["seq"] == seq
