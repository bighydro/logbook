"""Tiers 2 and 3 sealed at rest (SPEC §2 and §4, RFC 0029, ADR 0020): the primitives of
`logbook/core/sealing.py`, then the record: a tier 2 or 3 line is sealed on append when `logbook.json` names
recipients, keyless `verify` checks the chain and counts what it did not open, keyed `verify` opens
every sealed line and fails on bytes that do not match their digest. Every key here is generated for
the test or is the published example pair from age's README; nothing is real."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.core import sealing
from logbook.core.chain import canonical_json, is_sealed

# the fixture's recipient, conformance/identity.txt
EXAMPLE_RECIPIENT = "age1x5ut7lplvtgkzcnvtjux674z32mu5q72r6ffaxemxtg9g08p7g5qa8ytxl"
NOTE = {"schema": "note/v1", "text": "Dinner with Kari at the marina; Solvind needs a new impeller."}


@pytest.fixture
def keys() -> tuple[list[str], list[object]]:
    """Two fresh identities (this machine's and a recovery one) and their recipients."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    return [r for _, r in pairs], [sealing.parse_identity(s) for s, _ in pairs]


# -- the primitives -----------------------------------------------------------------------------


def test_sealed_bytes_are_the_canonical_text_of_payload_and_salt():
    salt = "3b9f0c2e7d1a4f6b8c0d2e4f6a8b0c1d"
    assert sealing.plain_of(NOTE, salt) == canonical_json({"payload": NOTE, "salt": salt}).encode()
    assert sealing.plain_of(NOTE, salt).startswith(b'{"payload":{"schema":"note/v1"')


def test_seal_gives_the_reference_and_a_base64_age_file(keys):
    recipients, identities = keys
    reference, payload_enc = sealing.seal(NOTE, recipients)
    assert set(reference) == {"schema", "of", "digest"}
    assert reference["schema"] == "sealed/v1" and reference["of"] == "note/v1"
    raw = base64.b64decode(payload_enc, validate=True)
    assert raw.startswith(sealing.AGE_MAGIC)
    plain = sealing.open_bytes({"seq": 1, "payload": reference, "payload_enc": payload_enc}, identities)
    assert hashlib.sha256(plain).hexdigest() == reference["digest"]
    assert json.loads(plain)["payload"] == NOTE


def test_a_fixed_salt_reproduces_the_digest_and_a_fresh_one_does_not(keys):
    recipients, _ = keys
    salt = "00112233445566778899aabbccddeeff"
    first, _ = sealing.seal(NOTE, recipients, salt)
    second, _ = sealing.seal(NOTE, recipients, salt)
    third, _ = sealing.seal(NOTE, recipients)
    assert first["digest"] == second["digest"] != third["digest"]


def test_open_line_returns_the_payload_and_checks_the_inner_schema(keys):
    recipients, identities = keys
    reference, payload_enc = sealing.seal(NOTE, recipients)
    line = {"seq": 7, "payload": reference, "payload_enc": payload_enc}
    assert sealing.open_line(line, identities) == NOTE
    wrong = {**line, "payload": {**reference, "of": "message/v1"}}
    with pytest.raises(sealing.SealError, match="not 'message/v1'"):
        sealing.open_line(wrong, identities)


def test_opening_needs_a_recipient_identity(keys):
    recipients, _ = keys
    reference, payload_enc = sealing.seal(NOTE, recipients)
    other = sealing.parse_identity(sealing.generate_identity()[0])
    with pytest.raises(sealing.SealError, match="does not open with this identity"):
        sealing.open_line({"seq": 1, "payload": reference, "payload_enc": payload_enc}, [other])
    with pytest.raises(sealing.SealError, match="no identity"):
        sealing.open_line({"seq": 1, "payload": reference, "payload_enc": payload_enc}, [])


def test_a_swapped_ciphertext_fails_the_digest_even_when_it_opens(keys):
    recipients, identities = keys
    reference, _ = sealing.seal(NOTE, recipients)
    _, other_enc = sealing.seal({"schema": "note/v1", "text": "something else"}, recipients)
    with pytest.raises(sealing.SealError, match=r"do not hash to payload\.digest"):
        sealing.open_line({"seq": 2, "payload": reference, "payload_enc": other_enc}, identities)


def test_decode_accepts_only_standard_base64_of_an_age_file(keys):
    recipients, _ = keys
    _, payload_enc = sealing.seal(NOTE, recipients)
    assert sealing.decode(payload_enc) is not None
    assert sealing.decode(payload_enc.rstrip("=") + "!") is None
    assert sealing.decode(base64.b64encode(b"not an age file").decode()) is None
    assert sealing.decode("") is None and sealing.decode(None) is None


def test_envelope_rule_ties_sealed_v1_and_payload_enc_together(keys):
    recipients, _ = keys
    reference, payload_enc = sealing.seal(NOTE, recipients)
    assert sealing.envelope_error({"payload": reference, "payload_enc": payload_enc}) is None
    assert sealing.envelope_error({"payload": NOTE}) is None
    assert "without a well-formed payload_enc" in str(sealing.envelope_error({"payload": reference}))
    assert "not sealed/v1" in str(sealing.envelope_error({"payload": NOTE, "payload_enc": payload_enc}))
    extra = {"payload": {**reference, "x": 1}, "payload_enc": payload_enc}
    assert "exactly" in str(sealing.envelope_error(extra))


def test_needs_sealing_only_tiers_2_and_3_with_recipients_and_never_a_reference():
    assert sealing.needs_sealing(2, NOTE, [EXAMPLE_RECIPIENT])
    assert sealing.needs_sealing(3, NOTE, [EXAMPLE_RECIPIENT])
    assert not sealing.needs_sealing(1, NOTE, [EXAMPLE_RECIPIENT])
    assert not sealing.needs_sealing(2, NOTE, [])
    reference = {"schema": "sealed/v1", "of": "note/v1", "digest": "0" * 64}
    assert not sealing.needs_sealing(2, reference, [EXAMPLE_RECIPIENT])


# -- files -------------------------------------------------------------------------------------


def test_a_file_seals_streamed_and_opens_to_the_same_bytes(tmp_path: Path, keys):
    recipients, identities = keys
    src = tmp_path / "memo.wav"
    src.write_bytes(bytes(range(256)) * 1000)
    sealed, back = tmp_path / "sealed", tmp_path / "back.wav"
    sealing.seal_file(src, sealed, recipients)
    assert sealing.is_sealed_file(sealed) and not sealing.is_sealed_file(src)
    sealing.open_file(sealed, back, identities)
    assert back.read_bytes() == src.read_bytes()


# -- keys --------------------------------------------------------------------------------------


def test_identity_file_is_age_keygen_format_owner_readable_and_never_overwritten(tmp_path: Path):
    secret, recipient = sealing.generate_identity()
    path = tmp_path / "ids" / "owner.txt"
    sealing.write_identity_file(path, secret, "logbook identity for the test record")
    text = path.read_text()
    assert text.splitlines()[0].startswith("# ") and f"# public key: {recipient}" in text
    assert sealing.load_identities(path) and str(sealing.load_identities(path)[0].to_public()) == recipient
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        sealing.write_identity_file(path, secret, "again")


def test_identity_is_looked_for_in_the_given_path_then_the_variable_then_the_default(tmp_path: Path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "APPDATA": str(tmp_path / "cfg")}  # XDG, or Windows
    default = sealing.identity_path("owner-1", env)
    assert default == tmp_path / "cfg" / "logbook" / "identities" / "owner-1.txt"
    named = {**env, "LOGBOOK_IDENTITY_FILE": str(tmp_path / "k.txt")}
    assert sealing.identity_path("owner-1", named) == tmp_path / "k.txt"
    assert sealing.identity_path("owner-1", env, given=tmp_path / "given.txt") == tmp_path / "given.txt"


def test_cache_dir_follows_the_platform_and_the_override(tmp_path: Path):
    assert sealing.cache_dir({"LOGBOOK_CACHE_HOME": str(tmp_path / "c")}) == tmp_path / "c"
    chosen = sealing.cache_dir({})
    assert chosen.name in ("logbook", "cache") and "logbook" in chosen.parts


def test_recipients_two_at_least_distinct_and_parseable():
    secret, recipient = sealing.generate_identity()
    with pytest.raises(ValueError, match="2 recipients at least"):
        sealing.check_recipients([recipient])
    with pytest.raises(ValueError, match="2 recipients at least"):
        sealing.check_recipients([recipient, recipient])
    with pytest.raises(ValueError, match="not an age recipient"):
        sealing.check_recipients([recipient, "age1notakey"])
    assert sealing.check_recipients([recipient, EXAMPLE_RECIPIENT]) == [recipient, EXAMPLE_RECIPIENT]
    assert sealing.recipient_of(secret) == recipient


def test_recipients_of_logbook_json_ignores_what_is_not_a_recipient():
    assert sealing.recipients_of({"recipients": [EXAMPLE_RECIPIENT, 3, "nope"]}) == [EXAMPLE_RECIPIENT]
    assert sealing.recipients_of({}) == [] and sealing.recipients_of({"recipients": "x"}) == []


def test_index_key_round_trips_sealed_and_blinds_deterministically(keys):
    recipients, identities = keys
    key = sealing.new_index_key()
    assert sealing.open_index_key(sealing.seal_index_key(key, recipients), identities) == key
    assert sealing.blind(key, "chat:4477009001:1") == sealing.blind(key, "chat:4477009001:1")
    assert sealing.blind(key, "a") != sealing.blind(key, "b") and sealing.blind(key, "a").startswith("blind:")


# -- the record ---------------------------------------------------------------------------------

from logbook.core.store import Logbook  # noqa: E402


@pytest.fixture
def sealed_lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys) -> Logbook:
    """A record that names two recipients; the first identity's file is where
    LOGBOOK_IDENTITY_FILE points. `init` writes no key: that is `logbook key init` (§6.1)."""
    recipients, identities = keys
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = recipients
    lb._save_meta(meta)
    path = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(path, str(identities[0]), "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    return Logbook(lb.root)


def _stored(lb: Logbook) -> list[dict]:
    return [json.loads(raw) for f in lb.files() for raw in f.read_text().splitlines() if raw.strip()]


def test_a_tier_2_line_is_sealed_on_append_and_a_tier_1_line_is_not(sealed_lb: Logbook):
    note = sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    point = sealed_lb.append(
        at="2026-10-01T18:43:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.9, "lon": 10.7},
    )
    stored = _stored(sealed_lb)
    digest = note["payload"]["digest"]
    assert stored[0]["payload"] == {"schema": "sealed/v1", "of": "note/v1", "digest": digest}
    assert sealing.decode(stored[0]["payload_enc"]) is not None
    assert "text" not in json.dumps(stored[0])
    assert stored[1]["payload"]["schema"] == "location/v1" and "payload_enc" not in stored[1]
    assert point["tier"] == 1


def test_opened_gives_the_real_payload_and_the_sealed_form_without_the_identity(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    line = _stored(sealed_lb)[0]
    opened = sealed_lb.opened(line)
    assert opened["payload"] == NOTE and "payload_enc" not in opened and opened["hash"] == line["hash"]
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    assert keyless.opened(line) == line


def test_verify_keyless_checks_the_chain_and_counts_sealed_lines(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    point = {"schema": "location/v1"}
    sealed_lb.append(at="2026-10-01T18:43:00Z", source="sim-phone", kind="location", tier=1, payload=point)
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    counts: dict[str, int] = {}
    seq, _head, errors = keyless.verify(counts=counts)
    assert errors == [] and seq == 2
    assert counts == {"sealed": 1, "opened": 0, "plain": 0}
    with_key: dict[str, int] = {}
    assert sealed_lb.verify(counts=with_key)[2] == []
    assert with_key == {"sealed": 1, "opened": 1, "plain": 0}


def test_keyed_verify_fails_on_sealed_bytes_that_do_not_match_their_digest(sealed_lb: Logbook, keys):
    recipients, _ = keys
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    f = sealed_lb.files()[0]
    line = json.loads(f.read_text())
    _, line["payload_enc"] = sealing.seal({"schema": "note/v1", "text": "swapped in"}, recipients)
    f.write_text(json.dumps(line, sort_keys=True) + "\n")
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    assert keyless.verify()[2] == [], "the chain is intact: the hash never covered the ciphertext"
    _, _, errors = sealed_lb.verify()
    assert len(errors) == 1 and "do not hash to payload.digest" in errors[0]
    assert errors[0].startswith("line 1: ") and errors[0].count("line 1:") == 1, errors[0]
    assert "no identity" in keyless.verify(keyed=True)[2][0]


def test_a_sealed_line_without_payload_enc_or_the_reverse_is_invalid_to_everyone(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    f = sealed_lb.files()[0]
    line = json.loads(f.read_text())
    enc = line.pop("payload_enc")
    f.write_text(json.dumps(line, sort_keys=True) + "\n")
    assert "without a well-formed payload_enc" in sealed_lb.verify(keyed=False)[2][0]
    line["payload_enc"] = enc
    line["payload"] = {**line["payload"], "note": "extra key"}
    f.write_text(json.dumps(line, sort_keys=True) + "\n")
    assert "exactly" in sealed_lb.verify(keyed=False)[2][0]


def test_a_writer_without_the_identity_refuses_tiers_2_and_3_and_writes_tier_1(sealed_lb: Logbook):
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    with pytest.raises(sealing.IdentityRequired, match="needs the identity"):
        keyless.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    drafts = [{"at": "2026-10-01T18:42:00Z", "source": "s", "kind": "note", "tier": 3, "payload": NOTE}]
    with pytest.raises(sealing.IdentityRequired):
        keyless.append_many(drafts)
    keyless.append(
        at="2026-10-01T18:43:00Z", source="ais", kind="location", tier=1, payload={"schema": "location/v1"}
    )
    assert keyless.meta["seq"] == 1


def test_a_record_without_recipients_writes_tier_2_plain_and_verify_counts_it(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    assert _stored(lb)[0]["payload"] == NOTE
    counts: dict[str, int] = {}
    assert lb.verify(counts=counts)[2] == [] and counts == {"sealed": 0, "opened": 0, "plain": 1}


def test_a_0_2_record_is_read_and_written_without_migration(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    meta = lb.meta
    meta["format"] = "logbook/0.2"
    lb._save_meta(meta)
    lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    assert lb.verify()[2] == [] and lb.meta["format"] == "logbook/0.2"
    assert Logbook.init(tmp_path / "new", "UTC").meta["format"] == "logbook/0.3"


def test_a_re_added_sealed_line_keeps_its_payload_enc(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    line = _stored(sealed_lb)[0]
    draft = {k: line[k] for k in ("at", "end", "tz", "source", "kind", "tier", "payload", "payload_enc")}
    assert sealed_lb.append_many([draft]) == 1
    again = _stored(sealed_lb)[1]
    assert again["payload"] == line["payload"] and again["payload_enc"] == line["payload_enc"]
    assert sealed_lb.opened(again)["payload"] == NOTE


# -- the index (RFC 0029 §8) --------------------------------------------------------------------


def _index_rows(lb: Logbook, sql: str) -> list[tuple]:
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(lb.index_path)) as db:
        return list(db.execute(sql))


def test_the_index_lives_in_the_cache_directory_not_the_record(sealed_lb: Logbook, tmp_path: Path):
    with sealed_lb.index():
        pass
    assert sealed_lb.index_path.exists()
    assert sealed_lb.root not in sealed_lb.index_path.parents
    assert sealed_lb.index_path.parent.name == sealed_lb.meta["owner_id"]
    assert sealed_lb.index_path.is_relative_to(tmp_path), "the test's HOME, never the real cache"
    assert not (sealed_lb.root / "index.sqlite").exists()


def test_a_sealed_lines_raw_id_is_blinded_and_its_words_are_not_in_the_search_table(sealed_lb: Logbook):
    message = {"schema": "message/v1", "raw_id": "447700900123:1", "text": "see you at the marina"}
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="whatsapp", kind="message", tier=2, payload=message)
    with sealed_lb.index():
        pass
    rows = _index_rows(sealed_lb, "SELECT raw_id, supersedes FROM lines")
    assert rows[0][0].startswith("blind:") and "447700900123" not in rows[0][0]
    key_rows = _index_rows(sealed_lb, "SELECT value FROM meta WHERE key = 'index_key'")
    assert len(key_rows) == 1
    words = json.dumps(_index_rows(sealed_lb, "SELECT body FROM search"))
    assert "marina" not in words and words == "[]", "sealed words stay sealed"


def test_dedupe_finds_a_sealed_line_by_its_raw_id(sealed_lb: Logbook):
    draft = {
        "at": "2026-10-01T18:42:00Z",
        "source": "whatsapp",
        "kind": "message",
        "tier": 2,
        "payload": {"schema": "message/v1", "raw_id": "447700900123:1", "text": "hello"},
    }
    assert sealed_lb.append_many([draft]) == 1
    assert sealed_lb.append_many([draft]) == 0, "the same observation again appends nothing (ADR 0017)"
    with sealed_lb.index() as idx:
        found = idx.line_id("whatsapp", "447700900123:1")
    assert found is not None
    tier1 = {**draft, "tier": 1, "payload": {"schema": "location/v1", "raw_id": "trk:1"}, "kind": "location"}
    assert sealed_lb.append_many([tier1]) == 1 and sealed_lb.append_many([tier1]) == 0


def test_an_index_built_without_the_identity_is_rebuilt_opened_by_the_first_keyed_reader(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    with sealed_lb.index():
        pass
    sealed_lb.index_path.unlink()
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    with keyless.index() as idx:
        assert idx.day("2026-10-01")[0]["payload"]["schema"] == "sealed/v1"
    assert _index_rows(keyless, "SELECT value FROM meta WHERE key = 'opened'") == [("false",)]
    with Logbook(sealed_lb.root).index() as idx:
        assert idx.day("2026-10-01")[0]["payload"] == NOTE
    assert _index_rows(sealed_lb, "SELECT value FROM meta WHERE key = 'opened'") == [("true",)]


def test_readers_through_the_index_get_opened_lines(sealed_lb: Logbook):
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    assert sealed_lb.day_lines("2026-10-01")[0]["payload"] == NOTE
    assert sealed_lb.line_by_seq(1)["payload"] == NOTE
    stored = _stored(sealed_lb)[0]
    assert stored["payload"]["schema"] == "sealed/v1", "the file holds the sealed form"


# -- attachments (RFC 0029 §7) ------------------------------------------------------------------

from logbook.core import attachments  # noqa: E402

TEXT = "Kari: Skal vi ta turen til Tromsø i mai?\nOla: Ja, gjerne.\n".encode()
SHA = hashlib.sha256(TEXT).hexdigest()


def test_an_attachment_is_sealed_under_its_plaintext_name_and_opens_with_the_identity(sealed_lb: Logbook):
    path = sealed_lb.attach(TEXT)
    assert path == sealed_lb.root / "attachments" / SHA, "the name is the plaintext digest"
    assert sealing.is_sealed_file(path) and TEXT not in path.read_bytes()
    assert sealed_lb.attachment_bytes(SHA) == TEXT
    assert attachments.reference(TEXT, "text/plain")["sha256"] == SHA, "the reference is unchanged"
    with sealed_lb.attachment(SHA) as plain:
        assert plain != path and plain.read_bytes() == TEXT
    assert not plain.exists(), "the opened copy is gone"


def test_a_tier_1_attachment_stays_plain_and_a_file_streams_sealed(sealed_lb: Logbook, tmp_path: Path):
    photo = sealed_lb.attach(b"\xff\xd8 a photo", tier=1)
    assert not sealing.is_sealed_file(photo)
    with sealed_lb.attachment(photo.name) as plain:
        assert plain == photo
    memo = tmp_path / "memo.m4a"
    memo.write_bytes(TEXT * 3000)
    stored = sealed_lb.attach_file(memo)
    assert sealing.is_sealed_file(stored) and stored.name == hashlib.sha256(TEXT * 3000).hexdigest()
    assert sealed_lb.attachment_bytes(stored.name) == TEXT * 3000


def test_attaching_the_same_bytes_twice_keeps_one_sealed_file(sealed_lb: Logbook):
    first = sealed_lb.attach(TEXT)
    before = first.read_bytes()
    assert sealed_lb.attach(TEXT) == first and first.read_bytes() == before, "write-once"


def test_a_plain_file_attached_again_by_a_sealing_record_is_sealed_in_place(sealed_lb: Logbook):
    plain = sealed_lb.attach(TEXT, tier=1)
    assert not sealing.is_sealed_file(plain)
    assert sealed_lb.attach(TEXT) == plain and sealing.is_sealed_file(plain), "the protection is raised"
    assert sealed_lb.attach(TEXT, tier=1) == plain and sealing.is_sealed_file(plain), "and never lowered"
    assert sealed_lb.attachment_bytes(SHA) == TEXT


def test_a_sealed_attachment_without_the_identity_is_a_clear_error_and_check_says_it_cannot_tell(
    sealed_lb: Logbook,
):
    path = sealed_lb.attach(TEXT)
    keyless = Logbook(sealed_lb.root, identity_file=sealed_lb.root / "nowhere.txt")
    with pytest.raises(sealing.SealError, match="no identity"):
        keyless.attachment_bytes(SHA)
    assert attachments.check(path) is None
    assert attachments.check(path, sealed_lb.identities) is True
    path.write_bytes(sealing.seal_bytes(b"other bytes", sealed_lb.recipients))
    assert attachments.check(path, sealed_lb.identities) is False
    with pytest.raises(sealing.SealError, match="do not hash to its name"):
        sealed_lb.attachment_bytes(SHA)


def test_a_record_without_recipients_attaches_plain_as_before(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    path = lb.attach(TEXT)
    assert path.read_bytes() == TEXT and lb.attachment_bytes(SHA) == TEXT


# -- sealing the past, resealing (RFC 0029 §6.4, §10.2) -----------------------------------------


def _plain_record(tmp_path: Path) -> Logbook:
    """A record written before any key: a note, a point, a transcript with its text in the store."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    point = {"schema": "location/v1"}
    lb.append(at="2026-10-01T18:43:00Z", source="sim-phone", kind="location", tier=1, payload=point)
    lb.attach(TEXT)
    lb.append(
        at="2026-10-01T19:00:00Z",
        source="granola",
        kind="transcript",
        tier=3,
        payload={"schema": "transcript/v1", "content": attachments.reference(TEXT, "text/plain")},
    )
    return lb


def _give_keys(lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keys) -> Logbook:
    recipients, identities = keys
    meta = lb.meta
    meta["recipients"] = recipients
    lb._save_meta(meta)
    path = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(path, str(identities[0]), "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    return Logbook(lb.root)


def test_seal_all_seals_the_past_recomputes_the_chain_and_records_the_old_head(tmp_path, monkeypatch, keys):
    lb = _give_keys(_plain_record(tmp_path), tmp_path, monkeypatch, keys)
    old = _stored(lb)
    old_head = lb.meta["head"]
    result = lb.seal_all()
    assert (result["lines"], result["sealed_lines"], result["sealed_attachments"]) == (3, 2, 1)
    new = _stored(lb)
    assert [line["payload"]["schema"] for line in new[:3]] == ["sealed/v1", "location/v1", "sealed/v1"]
    assert new[0]["hash"] != old[0]["hash"] and new[1]["prev"] == new[0]["hash"]
    for before, after in zip(old, new, strict=False):
        assert all(after[k] == before[k] for k in ("id", "seq", "at", "end", "tz", "source", "kind", "tier"))
        assert after["recorded_at"] == before["recorded_at"]
    assert new[3]["kind"] == "migration" and new[3]["payload"]["from_head"] == old_head
    assert new[3]["payload"]["sealed_lines"] == 2 and new[3]["payload"]["sealed_attachments"] == 1
    assert lb.meta["lineage"][0]["from_head"] == old_head and lb.meta["format"] == "logbook/0.3"
    assert sealing.is_sealed_file(lb.root / "attachments" / SHA) and lb.attachment_bytes(SHA) == TEXT
    assert not (lb.root / "logbook.sealing").exists() and not (lb.root / "logbook.sealing.old").exists()
    counts: dict[str, int] = {}
    assert lb.verify(counts=counts)[2] == [] and counts == {"sealed": 2, "opened": 2, "plain": 0}
    assert lb.opened(new[0])["payload"] == NOTE
    assert "text" not in json.dumps(new), "no plaintext of a tier 2 or 3 payload is left in the files"


def test_seal_all_refuses_without_recipients_or_identity_and_touches_nothing(tmp_path, monkeypatch, keys):
    lb = _plain_record(tmp_path)
    before = {f: f.read_bytes() for f in lb.files()}
    with pytest.raises(sealing.IdentityRequired, match="names no recipients"):
        lb.seal_all()
    lb = _give_keys(lb, tmp_path, monkeypatch, keys)
    keyless = Logbook(lb.root, identity_file=lb.root / "nowhere.txt")
    with pytest.raises(sealing.IdentityRequired, match="needs the identity"):
        keyless.seal_all()
    assert {f: f.read_bytes() for f in lb.files()} == before


def test_reseal_to_a_new_recipient_changes_no_hash_and_records_a_rekey_line(tmp_path, monkeypatch, keys):
    lb = _give_keys(_plain_record(tmp_path), tmp_path, monkeypatch, keys)
    lb.seal_all()
    head = lb.meta["head"]
    before = _stored(lb)
    recipients, _ = keys
    third_secret, third = sealing.generate_identity()
    result = lb.reseal([*recipients, third])
    assert result["sealed_lines"] == 2 and result["sealed_attachments"] == 1
    after = _stored(lb)
    for b, a in zip(before, after, strict=False):
        assert a["hash"] == b["hash"] and a["payload"] == b["payload"]
        if "payload_enc" in b:
            assert a["payload_enc"] != b["payload_enc"]
    assert after[-1]["kind"] == "rekey" and after[-1]["prev"] == head
    assert after[-1]["payload"]["recipients"] == [*recipients, third]
    assert lb.meta["recipients"] == [*recipients, third]
    third_file = tmp_path / "third.txt"
    sealing.write_identity_file(third_file, third_secret, "the new laptop")
    as_third = Logbook(lb.root, identity_file=third_file)
    assert as_third.opened(after[0])["payload"] == NOTE and as_third.attachment_bytes(SHA) == TEXT
    assert as_third.verify()[2] == []


def test_reseal_refuses_fewer_than_two_recipients(tmp_path, monkeypatch, keys):
    lb = _give_keys(_plain_record(tmp_path), tmp_path, monkeypatch, keys)
    with pytest.raises(ValueError, match="2 recipients at least"):
        lb.reseal([keys[0][0]])


# -- the CLI ------------------------------------------------------------------------------------

from logbook import cli  # noqa: E402


def _cli(capsys, *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _cli_fails(capsys, *args: str) -> tuple[int, str]:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    return int(e.value.code or 0), capsys.readouterr().err


def test_key_init_refuses_one_recipient_and_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "id.txt"))
    code, err = _cli_fails(capsys, "key", "init")
    assert code == 2 and "second recipient is required" in err
    assert not (tmp_path / "id.txt").exists() and "recipients" not in lb.meta


def test_key_init_with_recovery_writes_the_identity_prints_the_recovery_once_and_seals_from_then_on(
    tmp_path: Path, monkeypatch, capsys
):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "id.txt"))
    lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    out = _cli(capsys, "key", "init", "--recovery")
    assert "RECOVERY IDENTITY" in out and out.count("AGE-SECRET-KEY-1") == 1
    assert "`logbook seal --all` seals the 1 line already there" in out
    secret = next(word for word in out.split() if word.startswith("AGE-SECRET-KEY-1"))
    meta = lb.meta
    assert meta["format"] == "logbook/0.3" and len(meta["recipients"]) == 2
    assert sealing.recipient_of(secret) in meta["recipients"]
    assert (tmp_path / "id.txt").exists() and secret not in (tmp_path / "id.txt").read_text()
    assert "AGE-SECRET-KEY" not in json.dumps(meta)
    _cli(capsys, "add", "sealed from now on")
    assert _stored(lb)[-1]["payload"]["schema"] == "sealed/v1"
    show = _cli(capsys, "key", "show")
    assert "recipients: 2" in show and "opens this record" in show
    code, err = _cli_fails(capsys, "key", "init", "--recovery")
    assert code == 2 and "already names 2 recipients" in err


def test_verify_reports_sealed_lines_opened_or_not_and_keyless_never_opens(
    sealed_lb: Logbook, monkeypatch, capsys
):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    out = _cli(capsys, "verify")
    assert out.splitlines()[0].startswith("valid — 1 lines, head ")
    assert "sealed: 1 line, every one opened and checked" in out
    assert "sealed: 1 line, not opened" in _cli(capsys, "verify", "--keyless")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(sealed_lb.root / "nowhere.txt"))
    assert "not opened (no identity at" in _cli(capsys, "verify")


def test_verify_warns_when_a_record_names_one_recipient(sealed_lb: Logbook, monkeypatch, capsys):
    """RFC 0029 §6.1: a record with one recipient is a record that can lose its only key. `key init`
    refuses it; a logbook.json edited by hand can still say so, and `verify` says it back."""
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    assert "recipients: 1" not in _cli(capsys, "verify")
    meta = json.loads((sealed_lb.root / "logbook.json").read_text())
    meta["recipients"] = meta["recipients"][:1]
    (sealed_lb.root / "logbook.json").write_text(json.dumps(meta))
    out = _cli(capsys, "verify")
    assert out.splitlines()[0].startswith("valid — ")
    assert "recipients: 1" in out and "two at least" in out


def test_show_prints_a_sealed_line_as_sealed_without_the_identity(sealed_lb: Logbook, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    assert "Dinner with Kari" in _cli(capsys, "show", "2026-10-01")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(sealed_lb.root / "nowhere.txt"))
    out = _cli(capsys, "show", "2026-10-01")
    assert "[sealed note/v1; no identity to open it]" in out and "Dinner" not in out


def test_add_without_the_identity_refuses_in_one_sentence(sealed_lb: Logbook, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(sealed_lb.root / "nowhere.txt"))
    code, err = _cli_fails(capsys, "add", "a note that must not land")
    assert code == 2 and "needs the identity" in err and "nowhere.txt" in err
    assert sealed_lb.meta["seq"] == 0


def test_export_opens_by_default_writes_sealed_verbatim_on_request_and_refuses_without_the_key(
    sealed_lb: Logbook, monkeypatch, capsys, tmp_path: Path
):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    out = _cli(capsys, "export", str(tmp_path / "opened.jsonl"))
    assert "opened for re-entry" in out
    opened = json.loads((tmp_path / "opened.jsonl").read_text())
    assert opened["payload"] == NOTE and "payload_enc" not in opened
    _cli(capsys, "export", "--sealed", str(tmp_path / "sealed.jsonl"))
    verbatim = json.loads((tmp_path / "sealed.jsonl").read_text())
    assert verbatim == _stored(sealed_lb)[0]
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(sealed_lb.root / "nowhere.txt"))
    code, err = _cli_fails(capsys, "export", str(tmp_path / "no.jsonl"))
    assert code == 2 and "--sealed" in err and not (tmp_path / "no.jsonl").exists()
    assert "verbatim" in _cli(capsys, "export", "--sealed", str(tmp_path / "ok.jsonl"))


def test_identity_file_flag_names_the_identity_for_one_command(sealed_lb: Logbook, monkeypatch, capsys):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    sealed_lb.append(at="2026-10-01T18:42:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    path = Path(__import__("os").environ["LOGBOOK_IDENTITY_FILE"])
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(sealed_lb.root / "nowhere.txt"))
    assert "not opened" in _cli(capsys, "verify")
    assert "every one opened" in _cli(capsys, "--identity-file", str(path), "verify")


def test_seal_all_and_add_recipient_from_the_command_line(tmp_path: Path, monkeypatch, keys, capsys):
    lb = _give_keys(_plain_record(tmp_path), tmp_path, monkeypatch, keys)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    code, err = _cli_fails(capsys, "seal")
    assert code == 2 and "--all" in err
    out = _cli(capsys, "key", "seal", "--all")
    assert "sealed 2 lines and 1 attachment of 3" in out and "backup taken before now" in out
    assert lb.verify()[2] == []
    _, third = sealing.generate_identity()
    out = _cli(capsys, "key", "add-recipient", "--recipient", third)
    assert "resealed 2 lines and 1 attachment to 3 recipients" in out and "no hash changed" in out
    assert lb.meta["recipients"][-1] == third
    out = _cli(capsys, "key", "remove-recipient", "--recipient", third)
    assert "to 2 recipients" in out and third not in lb.meta["recipients"]
    code, err = _cli_fails(capsys, "key", "remove-recipient", "--recipient", third)
    assert code == 2 and "not a recipient" in err


# -- crossing packages (RFC 0005, RFC 0029 §7) --------------------------------------------------


def _crossing_policy(lb: Logbook, recipient: str | None) -> None:
    entry: dict = {"max_tier": 2}
    if recipient:
        entry["recipient"] = recipient
    (lb.root / "policy" / "crossing.json").write_text(json.dumps({"hermes": entry}), encoding="utf-8")


def _sealed_day(sealed_lb: Logbook) -> None:
    ref = attachments.reference(TEXT, "text/plain")
    sealed_lb.attach(TEXT)
    sealed_lb.append_many(
        [
            {
                "at": "2026-03-01T08:00:00Z",
                "source": "sim",
                "kind": "location",
                "tier": 1,
                "payload": {"schema": "location/v1"},
            },
            {"at": "2026-03-01T09:00:00Z", "source": "manual", "kind": "note", "tier": 2, "payload": NOTE},
            {
                "at": "2026-03-01T10:00:00Z",
                "source": "granola",
                "kind": "transcript",
                "tier": 2,
                "payload": {"schema": "transcript/v1", "content": ref},
            },
        ]
    )


def test_a_crossing_reseals_sealed_lines_and_files_to_the_destination(
    sealed_lb: Logbook, monkeypatch, tmp_path
):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    _sealed_day(sealed_lb)
    hermes_secret, hermes = sealing.generate_identity()
    _crossing_policy(sealed_lb, hermes)
    out = tmp_path / "out"
    window = ["--since", "2026-03-01T00:00:00Z", "--until", "2026-03-02T00:00:00Z"]
    cli.main(["export", "crossing", "--to", "hermes", *window, "--tier", "1,2", "--out", str(out)])
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text().splitlines()]
    stored = {line["seq"]: line for line in _stored(sealed_lb)}
    hermes_id = [sealing.parse_identity(hermes_secret)]
    for entry in entries:
        mine = stored[entry["seq"]]
        assert entry["hash"] == mine["hash"] and entry["payload"] == mine["payload"]
        if is_sealed(entry):
            assert entry["payload_enc"] != stored[entry["seq"]]["payload_enc"], "resealed, not the owner's"
            with pytest.raises(sealing.SealError):
                sealing.open_line(entry, sealed_lb.identities)
            assert sealing.open_line(entry, hermes_id)["schema"] == entry["payload"]["of"]
    assert sum(1 for e in entries if sealing.is_sealed(e)) == 2
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sealing"] == {"lines": 2, "mode": "resealed", "recipient": hermes}
    assert manifest["blobs"][0]["bytes"] == len(TEXT)
    crossed_file = out / "attachments" / SHA
    assert sealing.is_sealed_file(crossed_file)
    assert sealing.open_sealed_bytes(crossed_file.read_bytes(), hermes_id) == TEXT


def test_a_crossing_to_a_destination_without_a_recipient_needs_open_and_then_ships_the_pre_image(
    sealed_lb: Logbook, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed_lb.root))
    _sealed_day(sealed_lb)
    _crossing_policy(sealed_lb, None)
    window = ["--since", "2026-03-01T00:00:00Z", "--until", "2026-03-02T00:00:00Z"]
    args = ["export", "crossing", "--to", "hermes", *window, "--tier", "1,2", "--out", str(tmp_path / "no")]
    code, err = _cli_fails(capsys, *args)
    assert code == 2 and "--open" in err and not (tmp_path / "no").exists()
    out = tmp_path / "out"
    cli.main(["export", "crossing", "--to", "hermes", *window, "--tier", "1,2", "--open", "--out", str(out)])
    entries = [json.loads(s) for s in (out / "entries.jsonl").read_text().splitlines()]
    note = next(e for e in entries if e["kind"] == "note")
    assert "payload_enc" not in note and note["payload_open"]["payload"] == NOTE
    plain = canonical_json(note["payload_open"]).encode()
    assert hashlib.sha256(plain).hexdigest() == note["payload"]["digest"], "the member recomputes the digest"
    assert (out / "attachments" / SHA).read_bytes() == TEXT
    assert json.loads((out / "manifest.json").read_text())["sealing"] == {"lines": 2, "mode": "opened"}


def test_a_crossing_of_a_plain_record_is_unchanged(tmp_path: Path, monkeypatch):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(at="2026-03-01T09:00:00Z", source="manual", kind="note", tier=2, payload=NOTE)
    out = tmp_path / "out"
    window = ["--since", "2026-03-01T00:00:00Z", "--until", "2026-03-02T00:00:00Z"]
    cli.main(["export", "crossing", "--to", "hermes", *window, "--tier", "1,2", "--out", str(out)])
    entry = json.loads((out / "entries.jsonl").read_text())
    assert entry["payload"] == NOTE and "sealing" not in json.loads((out / "manifest.json").read_text())
