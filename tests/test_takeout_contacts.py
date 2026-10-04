"""Google Takeout Contacts/ → resolution/v1 (RFC 0006): one line per phone and email, one entity per
contact, merged with the people the record already resolves. Everyone here is synthetic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import ios_contacts
from logbook.adapters.takeout import contacts
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "takeout" / "Contacts"
ALL = FIX / "All Contacts" / "All Contacts.vcf"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
KARI_ID = "019cadd3-6bc0-7dcd-9133-000000000001"


def _lines(path=FIX, **kw):
    return list(contacts.run(path, **kw))


def _by_ref(lines):
    return {(p["ref"]["kind"], p["ref"]["value"]): p for p in (line["payload"] for line in lines)}


def test_registry_has_contacts_as_a_file_adapter_under_both_names():
    assert adapters.named("google-takeout-contacts") is contacts
    assert adapters.named("takeout-contacts") is contacts
    assert isinstance(contacts, adapters.Adapter)
    assert adapters.find(FIX) is contacts and adapters.find(ALL) is contacts


def test_sniff_recognises_a_vcard_file_and_the_folder_only(tmp_path):
    assert contacts.sniff(ALL) and contacts.sniff(FIX) and contacts.sniff(FIX / "All Contacts")
    assert not contacts.sniff(ROOT / "tests" / "fixtures" / "takeout" / "Keep")
    assert not contacts.sniff(tmp_path) and not contacts.sniff(tmp_path / "missing.vcf")
    (tmp_path / "notes.vcf").write_text("hello\n", encoding="utf-8")
    assert not contacts.sniff(tmp_path / "notes.vcf")


def test_every_phone_and_email_is_a_line_and_the_envelope_is_complete():
    counts: dict[str, int] = {}
    lines = _lines(counts=counts)
    assert len(lines) == 8  # Kari 3, Ola 3, the marina 2; the old card's email is a duplicate
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "resolution" and line["source"] == "google-takeout" and line["tier"] == 2
        assert line["end"] is None and line["tz"] is None
        p = line["payload"]
        assert p["schema"] == "resolution/v1" and p["method"] == "owner"
        assert p["raw_id"] == f"{p['ref']['kind']}:{p['ref']['value']}"
        assert p["entity"]["registry"] == "logbook"
    assert counts == {"skipped_no_ref": 1, "skipped_duplicate_ref": 1}


def test_the_folder_reads_all_contacts_alone_so_a_label_file_repeats_nothing():
    assert len(_lines(FIX)) == len(_lines(ALL)) == 8
    assert len(_lines(FIX / "Sailing")) == 8  # a label folder on its own is read too


def test_one_entity_per_contact_and_the_refs_are_normalised(monkeypatch):
    monkeypatch.delenv(ios_contacts.DIAL_PREFIX_ENV, raising=False)  # the shell's prefix never reaches a test
    by = _by_ref(_lines())
    kari = by[("email", "kari.nordmann@example.org")]  # lower-cased
    assert kari["label"] == "Kari Nordmann" and kari["entity"]["type"] == "person"
    assert by[("email", "kari@example.org")]["entity"]["id"] == kari["entity"]["id"]
    assert by[("phone", "+4790000002")]["entity"]["id"] == kari["entity"]["id"]  # spaces dropped
    assert kari["extra"] == {
        "label": "home",
        "organization": "Fjordline Design AS",
        "nickname": "Kari N",
        "categories": ["myContacts", "Sailing"],
        "rev": "2026-06-01T08:00:00Z",
    }
    ola = by[("phone", "+4790000001")]
    assert ola["label"] == "Ola Nordmann" and ola["entity"]["id"] != kari["entity"]["id"]
    assert by[("email", "ola@example.org")]["extra"]["label"] == "Boat"  # the item group's X-ABLabel
    national = by[("phone", "90000003")]  # no country code and no LOGBOOK_DIAL_PREFIX: kept, flagged
    assert national["extra"]["unnormalised"] is True and national["extra"]["label"] == "home"
    marina = by[("email", "havn@example.org")]
    assert marina["entity"]["type"] == "company" and marina["label"] == "Oslo Marina AS"
    assert by[("phone", "+4722000000")]["entity"]["id"] == marina["entity"]["id"]
    assert len({p["entity"]["id"] for p in by.values()}) == 3


def test_a_dial_prefix_completes_a_national_number(monkeypatch):
    monkeypatch.setenv(ios_contacts.DIAL_PREFIX_ENV, "47")
    by = _by_ref(_lines())
    assert ("phone", "+4790000003") in by and "unnormalised" not in by[("phone", "+4790000003")]["extra"]


def test_a_person_the_record_already_resolves_keeps_their_id_and_gets_no_second_line():
    resolved = {("email", "kari.nordmann@example.org"): KARI_ID, ("phone", "+4790000002"): KARI_ID}
    counts: dict[str, int] = {}
    by = _by_ref(_lines(resolved=resolved, counts=counts))
    assert ("email", "kari.nordmann@example.org") not in by and ("phone", "+4790000002") not in by
    assert by[("email", "kari@example.org")]["entity"]["id"] == KARI_ID  # the new address joins her
    assert counts == {"skipped_already_resolved": 3, "merged_into_known_people": 1, "skipped_no_ref": 1}
    assert len(by) == 6  # the old card's email is already resolved before it could be a duplicate


def test_cli_add_merges_with_ios_contacts_and_a_re_add_appends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo"])
    lb = Logbook.find()
    lb.append(  # Kari, as `ios-contacts` resolved her from the phone's address book
        at="2026-06-01T08:00:00Z",
        source="ios-contacts",
        kind="resolution",
        tier=2,
        payload={
            "schema": "resolution/v1",
            "raw_id": "phone:+4790000002",
            "ref": {"kind": "phone", "value": "+4790000002"},
            "entity": {"type": "person", "id": KARI_ID, "registry": "logbook"},
            "label": "Kari Nordmann",
            "method": "owner",
        },
    )
    capsys.readouterr()
    cli.main(["add", "takeout-contacts", str(FIX), "--dry-run"])
    out = capsys.readouterr().out
    assert "google-takeout-contacts: 7 lines would be added, 0 already in the record (dry run" in out
    assert lb.meta["seq"] == 1
    cli.main(["add", "takeout-contacts", str(FIX)])
    out = capsys.readouterr().out
    assert "added 7 lines from google-takeout-contacts" in out
    assert "1 already resolved in the record" in out
    assert "1 contacts merged into people the record knows" in out
    with lb.index() as idx:
        lines = idx.resolutions()
    ids = {line["payload"]["entity"]["id"] for line in lines if line["payload"]["label"].startswith("Kari")}
    assert ids == {KARI_ID}  # no second Kari
    cli.main(["add", "takeout-contacts", str(FIX)])
    assert "added 0 lines from google-takeout-contacts" in capsys.readouterr().out
