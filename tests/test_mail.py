"""Google Takeout mbox → mail/v1 (RFC 0015): one line per message, nothing skipped silently."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import mail
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "mail"
MBOX = FIX / "takeout.mbox"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
OWNER = "kari.nordmann@example.org"
OLA = "ola@example.org"
TZ = "Europe/Oslo"


def _lines(**kw):
    return list(mail.run(MBOX, timezone=TZ, **kw))


def _by_subject(lines):
    return {line["payload"].get("subject"): line for line in lines}


def _by_id(lines, message_id: str):
    return next(line["payload"] for line in lines if line["payload"].get("message_id") == message_id)


# -- registry and sniff ---------------------------------------------------------------------------


def test_registry_has_mail_as_a_file_adapter():
    assert adapters.named("mail") is mail
    assert isinstance(mail, adapters.Adapter)


def test_sniff_recognises_an_mbox_file_and_a_folder_of_them(tmp_path):
    assert mail.sniff(MBOX)
    folder = tmp_path / "Mail"
    folder.mkdir()
    shutil.copy(MBOX, folder / "All mail Including Spam and Trash.mbox")
    assert mail.sniff(folder)
    assert adapters.find(MBOX) is mail


def test_sniff_rejects_other_files_and_empty_folders(tmp_path):
    assert not mail.sniff(ROOT / "tests" / "fixtures" / "dawarich" / "export.json")
    (tmp_path / "notes.txt").write_text("From here on, nothing\n", encoding="utf-8")
    assert not mail.sniff(tmp_path / "notes.txt")
    assert not mail.sniff(tmp_path)
    assert not mail.sniff(tmp_path / "missing.mbox")


# -- the mapping ----------------------------------------------------------------------------------


def test_every_message_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = list(mail.run(MBOX, timezone=TZ, counts=counts))
    assert len(lines) == 6
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "mail" and line["source"] == "mail" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "mail/v1"
        assert isinstance(line["payload"]["size"], int) and line["payload"]["size"] > 0
    assert not any(k.startswith("skipped_") for k in counts)


def test_headers_map_to_the_payload_and_the_date_keeps_its_offset():
    line = next(line for line in _lines() if line["payload"]["message_id"] == "a1b2c3@mail.example.org")
    assert line["at"] == "2026-03-02T10:15:00Z"
    p = line["payload"]
    assert p["raw_id"] == "a1b2c3@mail.example.org"
    assert p["date"] == "2026-03-02T11:15:00+01:00"
    assert p["from"] == {"email": OLA, "name": "Ola Nordmann"}
    assert p["to"] == [{"email": OWNER, "name": "Kari Nordmann"}]  # lower-cased
    assert p["cc"] == [{"email": "havn@example.org", "name": "Havnekontoret, Oslo"}]
    assert "bcc" not in p
    assert p["labels"] == ["Inbox", "Important", "Category Personal"]
    assert p["extra"]["gmail_thread_id"] == "1795123456789012345"
    assert p["extra"]["in_reply_to"] == "9f8e7d@mail.example.org"
    assert p["extra"]["references"] == ["9f8e7d@mail.example.org", "0a0b0c@mail.example.org"]


def test_thread_is_the_root_of_references_else_in_reply_to_else_the_own_id():
    by = {line["payload"].get("message_id"): line["payload"] for line in _lines()}
    assert by["a1b2c3@mail.example.org"]["thread"] == "9f8e7d@mail.example.org"
    assert by["b2c3d4@mail.example.org"]["thread"] == "9f8e7d@mail.example.org"  # the same thread
    assert by["d4e5f6@mail.example.org"]["thread"] == "d4e5f6@mail.example.org"  # no parent: itself


def test_from_lines_in_the_body_are_unescaped_and_the_body_is_verbatim():
    p = _by_subject(_lines())["Rope for Saturday"]["payload"]
    assert p["body"] == "Can you bring the long rope?\n"
    lines = _lines()
    p = _by_id(lines, "a1b2c3@mail.example.org")
    assert "\nFrom the east berth you can see the lighthouse.\n" in p["body"]
    assert "\n>From here, nothing.\n" in p["body"]  # mboxrd: one `>` is removed, the rest stays
    assert ">From the east" not in p["body"]
    assert "body_from" not in p.get("extra", {})


def test_direction_is_sent_only_for_the_owners_addresses():
    by = _by_subject(_lines(owner_emails=[OWNER]))
    assert by["Rope for Saturday"]["payload"]["direction"] == "sent"
    assert by["You won"]["payload"]["direction"] == "received"
    assert all(line["payload"]["direction"] == "received" for line in _lines())  # nobody configured
    by = _by_subject(_lines(owner_emails=["Kari.Nordmann@Example.org"]))  # case never matters
    assert by["Rope for Saturday"]["payload"]["direction"] == "sent"


def test_an_account_prefixes_the_raw_id_and_counts_as_the_owner():
    by = _by_subject(_lines(account=OWNER))
    p = by["Rope for Saturday"]["payload"]
    assert p["raw_id"] == f"{OWNER}:d4e5f6@mail.example.org"
    assert p["message_id"] == "d4e5f6@mail.example.org"
    assert p["account"] == OWNER and p["direction"] == "sent"


def test_an_html_only_message_is_stripped_to_text_and_says_so():
    p = _by_subject(_lines())["Nytt fra havna \u2013 mars"]["payload"]
    assert p["extra"]["body_from"] == "html"
    body = p["body"]
    assert "<" not in body and "alert" not in body and "color" not in body and "hidden" not in body
    assert "Nytt fra havna" in body  # the h1, not the title
    assert "Hei Kari,\nse på dette & les mer." in body  # <br> breaks, entities decode, tags go
    assert "Bryggeplasser\nPriser" in body
    assert "Les mer" in body and "https://example.org/x" not in body


def test_a_nested_multipart_message_takes_the_plain_part_and_lists_its_attachments():
    p = _by_id(_lines(), "b2c3d4@mail.example.org")
    assert p["body"] == "Berth plan attached.\n"
    txt = b"East berth: free from Friday.\nWest berth: taken.\n"
    pdf = b"%PDF-1.4 synthetic berth plan\n"
    assert p["attachments"] == [
        {
            "filename": "berth-plan.txt",
            "media_type": "text/plain",
            "sha256": hashlib.sha256(txt).hexdigest(),
            "bytes": len(txt),
        },
        {
            "filename": "plan.pdf",
            "media_type": "application/pdf",
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "bytes": len(pdf),
        },
    ]
    assert "attachments" not in _by_subject(_lines())["Rope for Saturday"]["payload"]


def test_attachments_are_stored_only_when_asked(tmp_path):
    stored: list[bytes] = []
    counts: dict[str, int] = {}
    lines = list(mail.run(MBOX, timezone=TZ, counts=counts, store=stored.append))
    p = _by_id(lines, "b2c3d4@mail.example.org")
    assert "path" not in p["attachments"][0] and stored == []
    assert counts["attachments_referenced"] == 2 and "attachments_stored" not in counts

    stored.clear()
    counts.clear()
    lines = list(mail.run(MBOX, timezone=TZ, counts=counts, store=stored.append, attachments=True))
    p = _by_id(lines, "b2c3d4@mail.example.org")
    assert [a["path"] for a in p["attachments"]] == [f"attachments/{a['sha256']}" for a in p["attachments"]]
    assert [hashlib.sha256(b).hexdigest() for b in stored] == [a["sha256"] for a in p["attachments"]]
    assert counts["attachments_stored"] == 2 and "attachments_referenced" not in counts


def test_a_message_without_a_message_id_is_keyed_by_its_bytes_and_counted():
    counts: dict[str, int] = {}
    p = _by_subject(list(mail.run(MBOX, timezone=TZ, counts=counts)))["You won"]["payload"]
    assert "message_id" not in p
    assert p["raw_id"].startswith("sha256:") and len(p["raw_id"]) == len("sha256:") + 64
    assert p["thread"] == p["raw_id"]
    assert p["from"] == {"email": "spam@example.org"}  # no display name, no `name`
    assert p["date"] == "2026-03-04T06:00:00-05:00"
    assert counts["no_message_id"] == 1
    again = _by_subject(_lines())["You won"]["payload"]
    assert again["raw_id"] == p["raw_id"]  # stable across runs
    assert _by_subject(_lines(account=OWNER))["You won"]["payload"]["raw_id"] == f"{OWNER}:{p['raw_id']}"


def test_a_message_without_a_date_is_timed_by_the_separator_and_counted():
    counts: dict[str, int] = {}
    line = _by_subject(list(mail.run(MBOX, timezone=TZ, counts=counts)))["(no date)"]
    assert line["at"] == "2026-03-04T13:00:00Z" and "date" not in line["payload"]
    assert counts["date_from_separator"] == 1


def test_undecodable_bytes_are_replaced_never_dropped():
    counts: dict[str, int] = {}
    p = _by_subject(list(mail.run(MBOX, timezone=TZ, counts=counts)))["(no date)"]["payload"]
    assert "Kari, bryggeplassen er ledig." in p["body"] and "�" in p["body"]
    assert p["extra"]["decoding_errors"] is True and counts["decoding_errors"] == 1


def test_label_filters_keep_or_drop_by_any_label_and_count_the_rest():
    counts: dict[str, int] = {}
    kept = list(mail.run(MBOX, timezone=TZ, counts=counts, only_labels=["Inbox", "Sent"]))
    assert {line["payload"]["subject"] for line in kept} == {
        "Re: Mooring for the weekend",
        "Rope for Saturday",
        "Nytt fra havna \u2013 mars",
    }
    assert counts["skipped_label"] == 2
    counts.clear()
    kept = list(mail.run(MBOX, timezone=TZ, counts=counts, skip_labels=["spam", "TRASH"]))  # any case
    assert len(kept) == 4 and counts["skipped_label"] == 2
    counts.clear()
    kept = list(mail.run(MBOX, timezone=TZ, counts=counts, only_labels=["Inbox"], skip_labels=["Important"]))
    assert {line["payload"]["message_id"] for line in kept} == {
        "news-2026-03-03@news.example.org",
        "b2c3d4@mail.example.org",
    }
    assert counts["skipped_label"] == 4


def test_since_filters_on_at():
    assert len(_lines(since="2026-03-03T00:00:00Z")) == 4
    assert len(_lines(since="2026-03-04T12:00:00Z")) == 1


def test_tier_is_2_by_default_and_the_option_applies_to_the_whole_import():
    assert {line["tier"] for line in _lines()} == {2}
    assert {line["tier"] for line in _lines(tier=1)} == {1}


def test_the_file_is_streamed_never_read_whole(monkeypatch):
    def refuse(self, *a, **kw):
        raise AssertionError("the mbox must be streamed, not read whole")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    it = mail.run(MBOX, timezone=TZ)
    first = next(it)
    assert first["payload"]["message_id"] == "a1b2c3@mail.example.org"
    assert len(list(it)) == 5


def test_a_folder_reads_every_mbox_in_name_order(tmp_path):
    folder = tmp_path / "Mail"
    folder.mkdir()
    shutil.copy(MBOX, folder / "b.mbox")
    shutil.copy(MBOX, folder / "a.mbox")
    (folder / "notes.txt").write_text("not mail\n", encoding="utf-8")
    lines = list(mail.run(folder, timezone=TZ))
    assert len(lines) == 12  # the record's dedupe, not the adapter, makes them six


def test_every_line_is_valid_against_the_schema_appends_and_dedupes(tmp_path):
    lb = Logbook.init(tmp_path / "lb", TZ)
    lines = _lines(owner_emails=[OWNER])
    assert lb.append_many(lines) == 6
    assert lb.append_many(_lines(owner_emails=[OWNER])) == 0
    assert lb.verify()[2] == []
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


def test_strip_html_is_a_pure_function_over_odd_input():
    assert mail.strip_html("") == ""
    assert mail.strip_html("plain") == "plain"
    assert mail.strip_html("<p>a</p><p>b</p>") == "a\nb"
    assert mail.strip_html("a<br/>b<br />c") == "a\nb\nc"
    assert mail.strip_html("<div>x &lt;y&gt; &#169;</div>") == "x <y> ©"
    assert mail.strip_html("<p>unclosed <b>bold") == "unclosed bold"
    assert mail.strip_html("<script>if (a < b) {}</script>after") == "after"
    assert mail.strip_html("  a  \n\n\n\n  b  ") == "a\n\nb"


# -- the CLI --------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    meta = lb.meta
    meta["owner_emails"] = [OWNER]
    (lb.root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def test_add_mail_by_name_reads_owner_emails_from_logbook_json(lb, capsys):
    cli.main(["add", "mail", str(MBOX)])
    out = capsys.readouterr().out
    assert "added 6 lines from mail" in out
    assert "1 without a Message-ID, keyed by digest" in out
    assert "2 attachments referenced, not stored" in out
    by = {line["payload"].get("subject"): line for line in lb.lines()}
    assert by["Rope for Saturday"]["payload"]["direction"] == "sent"
    assert not (lb.root / "attachments").exists()


def test_add_mail_is_sniffed_without_the_keyword(lb, capsys):
    cli.main(["add", str(MBOX)])
    assert "added 6 lines from mail" in capsys.readouterr().out


def test_add_mail_with_attachments_account_filters_since_and_tier(lb, capsys):
    cli.main(
        [
            "add",
            "mail",
            str(MBOX),
            "--attachments",
            "--account",
            OWNER,
            "--skip-labels",
            "Spam,Trash",
            "--since",
            "2026-03-03",
            "--tier",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert "added 2 lines from mail" in out and "skipped 2 by label" in out and "2 attachments stored" in out
    lines = list(lb.lines())
    assert {line["tier"] for line in lines} == {1}
    assert all(line["payload"]["raw_id"].startswith(f"{OWNER}:") for line in lines)
    p = next(line["payload"] for line in lines if "attachments" in line["payload"])
    for a in p["attachments"]:
        assert (lb.root / a["path"]).stat().st_size == a["bytes"]


def test_add_mail_only_labels(lb, capsys):
    cli.main(["add", "mail", str(MBOX), "--only-labels", "Sent"])
    assert "added 1 lines from mail" in capsys.readouterr().out


def test_add_mail_re_adding_appends_nothing(lb, capsys):
    cli.main(["add", "mail", str(MBOX)])
    cli.main(["add", "mail", str(MBOX)])
    assert capsys.readouterr().out.count("added 6 lines") == 1 and len(list(lb.lines())) == 6


def test_add_mail_flags_are_refused_for_an_adapter_that_does_not_take_them(lb, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["add", str(ROOT / "tests" / "fixtures" / "dawarich" / "export.json"), "--attachments"])
    assert e.value.code == 2 and "--attachments" in capsys.readouterr().err


def test_add_mail_hints_when_no_owner_address_is_known(tmp_path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cli.main(["add", "mail", str(MBOX)])
    assert "owner_emails" in capsys.readouterr().err


def _show(capsys, *args: str) -> list[str]:
    cli.main(["show", *args])
    return capsys.readouterr().out.splitlines()


def _text(out: list[str]) -> list[str]:
    return [" ".join(line.split()[3:]) for line in out[1:]]


def test_show_renders_a_mail_line_with_names_from_resolution_lines(lb, capsys):
    cli.main(["add", "mail", str(MBOX)])
    lb.append(
        at="2026-03-01T00:00:00Z",
        source="manual",
        kind="resolution",
        tier=2,
        payload={
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": OLA},
            "entity": {"type": "person", "id": "019cadd3-6bc0-7dcd-9133-043f5aabf2a9", "registry": "logbook"},
            "label": "Ola N.",
        },
    )
    capsys.readouterr()
    assert _text(_show(capsys, "2026-03-02")) == [
        "✉ Re: Mooring for the weekend — Ola N. → Kari Nordmann, Havnekontoret, Oslo",
        "\u2709 Rope for Saturday \u2014 me \u2192 Ola N.",  # sent: me → the recipient, by its resolution
    ]
    rows = _show(capsys, "2026-03-03")
    assert _text(rows)[1] == "✉ Re: Mooring for the weekend — Ola N. → Kari Nordmann (2 attachments)"
    assert _text(rows)[0] == "\u2709 Nytt fra havna \u2013 mars \u2014 Harbour News \u2192 " + OWNER
    assert not any("Berth plan attached" in row for row in rows)  # never the body


def test_show_raw_prints_refs_as_given_and_the_body(lb, capsys):
    cli.main(["add", "mail", str(MBOX)])
    capsys.readouterr()
    rows = _show(capsys, "2026-03-02", "--raw")
    assert _text(rows)[0] == "✉ Re: Mooring for the weekend — " + OLA + " → " + OWNER + ", havn@example.org"
    assert "    Photos attached. The east berth is free from Friday." in rows
    assert "    From the east berth you can see the lighthouse." in rows
