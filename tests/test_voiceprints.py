"""The voiceprint registry (RFC 0038 §5): `voiceprints.age`, one age file sealed to the record's own
recipients, a cache made from the audio the transcripts name and the standing attributions, rewritten
whole at each write; the owner enrolled from their own microphone without a line; `policy/speakers.json`
read each run. Synthetic Oslo persona (`voiceprints_record`): the embedder is a fake that reads who
speaks from a small JSON file standing in for the audio; no model is downloaded, loaded or called."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from persona import TZ
from speakers_record import CALL, DINNER, KARI_ID, OLA_ID, attribution
from voiceprints_record import DIM, FakeEmbedder, as_text, seal, stored, voiced_record

from logbook.core import sealing, voiceprints
from logbook.core.chain import AGE_MAGIC
from logbook.core.store import Logbook

S = voiceprints.Settings()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The dinner and the call, in a record sealed to two recipients."""
    lb = seal(Logbook.init(tmp_path / "lb", TZ), monkeypatch, tmp_path)
    voiced_record(lb)
    return Logbook(lb.root)


def _owner(lb: Logbook) -> str:
    return str(lb.meta["owner_id"])


def _settings(lb: Logbook, **given: object) -> None:
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "speakers.json").write_text(json.dumps(given), encoding="utf-8")


# -- the settings ---------------------------------------------------------------------------------------


def test_the_settings_are_the_rfc_defaults_without_a_file(tmp_path: Path) -> None:
    assert voiceprints.settings(tmp_path) == voiceprints.Settings(0.75, 0.5, 8.0, 0.6, False, frozenset())


@pytest.mark.parametrize(
    ("given", "said"),
    [
        ({"match": 1.5}, "match must be a number from 0 to 1"),
        ({"floor": 0.8}, "floor must be below match"),
        ({"min_clean_s": -1}, "min_clean_s must be seconds, 0 or more"),
        ({"enrol_unnamed": "yes"}, "enrol_unnamed must be true or false"),
        ({"forget": [""]}, "forget must be a list of entity ids"),
        ({"forget": [42]}, "forget must be a list of entity ids"),
        ({"forget": KARI_ID}, "forget must be a list of entity ids"),
        ({"mtach": 0.8}, "'mtach' is no setting"),
    ],
)
def test_a_setting_that_is_not_one_is_refused_in_one_sentence(tmp_path: Path, given: dict, said: str) -> None:
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "speakers.json").write_text(json.dumps(given), encoding="utf-8")
    with pytest.raises(voiceprints.SettingsError) as e:
        voiceprints.settings(tmp_path)
    assert (
        said in str(e.value) and str(e.value).startswith("policy/speakers.json") and "\n" not in str(e.value)
    )


# -- vectors, clean speech, the score -------------------------------------------------------------------


def test_clean_speech_is_the_voice_alone_in_pieces_of_two_seconds_or_more() -> None:
    document = {
        "turns": [
            {"from": 0.0, "to": 10.0, "speaker": "S1"},
            {"from": 3.0, "to": 4.5, "speaker": "S2"},  # leaves 0-3 and 4.5-10
            {"from": 9.0, "to": 12.0, "speaker": "S2"},  # leaves 4.5-9
            {"from": 20.0, "to": 21.5, "speaker": "S1"},  # alone, but under two seconds
        ]
    }
    pieces = voiceprints.clean_pieces(document, "S1")
    assert pieces == [(0.0, 3.0), (4.5, 9.0)]
    assert voiceprints.clean_seconds(pieces) == 7.5
    assert voiceprints.clean_pieces(document, "S2") == [(10.0, 12.0)]


def test_the_score_is_full_at_match_none_at_floor_and_straight_between() -> None:
    assert voiceprints.points(0.75, S) == voiceprints.points(0.99, S) == 70
    assert voiceprints.points(0.5, S) == voiceprints.points(0.2, S) == 0
    assert voiceprints.points(0.625, S) == 35


def test_a_centre_does_not_depend_on_the_order_of_its_voices() -> None:
    a = voiceprints.Embedded(stored("ines"), 12.0)
    b = voiceprints.Embedded(stored("kari"), 3.5)
    c = voiceprints.Embedded(stored("ola"), 8.0)
    assert voiceprints.centre([a, b, c]) == voiceprints.centre([c, a, b]) == voiceprints.centre([b, c, a])
    assert voiceprints.similarity(voiceprints.centre([a]), a.embedding) == pytest.approx(1.0)


# -- a write --------------------------------------------------------------------------------------------


def test_a_write_seals_the_file_and_holds_the_owner_without_a_line(lb: Logbook) -> None:
    seq = lb.meta["seq"]
    embedder = FakeEmbedder()
    summary = voiceprints.update(lb, embedder)
    assert summary.written and Logbook(lb.root).meta["seq"] == seq, "enrolment writes no line (§5.4)"
    data = (lb.root / voiceprints.FILE).read_bytes()
    assert data.startswith(AGE_MAGIC)
    assert not any(text.encode() in data for who in ("ines", "kari", "ola") for text in as_text(stored(who)))
    found = voiceprints.read(lb)
    assert found is not None and (found.model, found.dim) == (voiceprints.MODEL, DIM)
    owner = found.people[_owner(lb)]
    assert owner.refs == [f"{CALL}#mic"] and owner.voiceprint == stored("ines"), "from_me: the owner's"
    assert sorted(found.voices) == sorted([f"{CALL}#system", f"{DINNER}#S1", f"{DINNER}#S2"]), "S3: 4 s clean"
    assert found.voices[f"{DINNER}#S2"].embedding == stored("kari")
    assert found.head == Logbook(lb.root).meta["head"]
    for shown in (repr(found), repr(owner), repr(found.voices)):
        assert "0." not in shown, "a registry printed by accident shows no number of a voice"


def test_a_record_without_recipients_keeps_no_registry(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "open", TZ)
    voiced_record(lb)
    embedder = FakeEmbedder()
    summary = voiceprints.update(lb, embedder)
    assert summary.state == voiceprints.NO_RECIPIENTS and not summary.written
    assert not (lb.root / voiceprints.FILE).exists() and embedder.loaded == []
    heard, owner = voiceprints.standing_voices(lb)
    kept = voiceprints.in_memory(lb, embedder, heard, owner, S)
    assert kept.people[_owner(lb)].voiceprint == stored("ines") and not (lb.root / voiceprints.FILE).exists()


def test_an_answer_moves_a_voice_without_the_model_and_a_retraction_moves_it_back(lb: Logbook) -> None:
    voiceprints.update(lb, FakeEmbedder())
    line = lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    summary = voiceprints.update(lb)  # no embedder: the review's write
    found = voiceprints.read(lb)
    assert summary.written and found is not None
    assert found.people[KARI_ID].refs == [f"{DINNER}#S2"] and f"{DINNER}#S2" not in found.voices
    assert found.people[KARI_ID].voiceprint == stored("kari")
    lb.retract(int(line["seq"]), "not her")
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None and KARI_ID not in found.people
    assert found.voices[f"{DINNER}#S2"].embedding == stored("kari"), "back in the queue, still heard"


def test_the_owner_is_also_every_voice_bound_to_them(lb: Logbook) -> None:
    voiceprints.update(lb, FakeEmbedder())
    lb.append(**_draft(attribution(DINNER, "S1", _owner(lb))))
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None
    assert found.people[_owner(lb)].refs == sorted([f"{CALL}#mic", f"{DINNER}#S1"])
    assert found.people[_owner(lb)].clean_s == 20.0


def test_forget_is_never_held_and_unnamed_only_when_enrolled(lb: Logbook) -> None:
    voiceprints.update(lb, FakeEmbedder())
    lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    lb.append(**_draft(attribution(CALL, "system", OLA_ID, unnamed=True)))
    _settings(lb, forget=[KARI_ID])
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None and set(found.people) == {_owner(lb)} and set(found.voices) == {f"{DINNER}#S1"}
    data = voiceprints.read(lb)
    assert data is not None and f"{DINNER}#S2" not in data.pool() and f"{CALL}#system" not in data.pool()
    _settings(lb, enrol_unnamed=True)
    embedder = FakeEmbedder()
    voiceprints.update(lb, embedder)  # the file let them go: a write that hears hears them again
    found = voiceprints.read(lb)
    assert found is not None and found.people[OLA_ID].voiceprint == stored("ola")
    assert found.people[KARI_ID].voiceprint == stored("kari") and len(embedder.loaded) == 2


def test_forget_takes_any_id_and_one_that_is_no_one_s_forgets_no_one(lb: Logbook) -> None:
    """`forget` is entity ids as `people --json` gives them, and anything else a non-empty string:
    an id in capitals, a name, a typo is read, not refused, and simply matches no one."""
    voiceprints.update(lb, FakeEmbedder())
    lb.append(**_draft(attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann")))
    odd = [KARI_ID.upper(), "Kari Nordmann", "{" + KARI_ID + "}", " " + KARI_ID]
    _settings(lb, forget=odd)
    assert voiceprints.settings(lb.root).forget == frozenset(odd)
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None and set(found.people) == {_owner(lb), KARI_ID}
    assert found.people[KARI_ID].refs == [f"{DINNER}#S2"]


def test_a_model_change_rebuilds_and_a_superseded_transcript_leaves(lb: Logbook) -> None:
    voiceprints.update(lb, FakeEmbedder(model="example/older-embedding"))
    embedder = FakeEmbedder()
    summary = voiceprints.update(lb, embedder)
    assert summary.state == voiceprints.REBUILT and summary.reason == "the model changed"
    assert len(embedder.loaded) == 2
    found = voiceprints.read(lb)
    assert found is not None and found.model == voiceprints.MODEL
    lb.retract(int(next(line for line in lb.lines() if line["id"] == DINNER)["seq"]), "heard wrong")
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None and not any(ref.startswith(DINNER) for ref in found.pool())


def test_min_clean_s_is_read_each_run(lb: Logbook) -> None:
    _settings(lb, min_clean_s=4)
    voiceprints.update(lb, FakeEmbedder())
    found = voiceprints.read(lb)
    assert found is not None and found.voices[f"{DINNER}#S3"].clean_s == 4.0
    _settings(lb, min_clean_s=8)
    voiceprints.update(lb)
    found = voiceprints.read(lb)
    assert found is not None and f"{DINNER}#S3" not in found.voices


def test_a_write_without_the_model_and_without_a_file_writes_none(lb: Logbook) -> None:
    assert voiceprints.update(lb).state == voiceprints.NO_REGISTRY
    assert not (lb.root / voiceprints.FILE).exists()


def test_the_file_is_never_read_plain_and_never_without_the_identity(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    voiceprints.update(lb, FakeEmbedder())
    other = tmp_path / "keys" / "other.txt"
    sealing.write_identity_file(other, sealing.generate_identity()[0], "not this record's")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(other))
    with pytest.raises(voiceprints.RegistryError, match="does not open"):
        voiceprints.read(Logbook(lb.root))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "absent.txt"))
    with pytest.raises(voiceprints.RegistryError, match="no identity"):
        voiceprints.read(Logbook(lb.root))
    (lb.root / voiceprints.FILE).write_text('{"format": "voiceprints/1"}', encoding="utf-8")
    with pytest.raises(voiceprints.RegistryError, match="not sealed"):
        voiceprints.read(Logbook(lb.root))


def test_a_recording_without_its_audio_is_counted_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = seal(Logbook.init(tmp_path / "quiet", TZ), monkeypatch, tmp_path)
    voiced_record(lb, audio=False)
    summary = voiceprints.update(Logbook(lb.root), FakeEmbedder())
    assert summary.written and summary.skipped == {voiceprints.NO_AUDIO: 2}
    found = voiceprints.read(Logbook(lb.root))
    assert found is not None and found.people == {} and found.voices == {}


def _draft(line: dict) -> dict:
    """A `speakers_record` line as `Logbook.append` takes it."""
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}


def test_verify_ignores_the_registry_and_backup_leaves_it_out(lb: Logbook, tmp_path: Path) -> None:
    from logbook.contrib import backup
    from logbook.core import attachments

    voiceprints.update(lb, FakeEmbedder())
    seq, head, errors = Logbook(lb.root).verify(walk=attachments.Walk())
    assert errors == [] and head == Logbook(lb.root).meta["head"] and seq == Logbook(lb.root).meta["seq"]
    assert voiceprints.FILE not in {path.name for path in backup.record_files(lb.root)}
    done = backup.snapshot(Logbook(lb.root), tmp_path / "backups", env={})
    assert not any(path.name == voiceprints.FILE for path in done.path.rglob("*"))


def test_voices_that_cancel_out_have_the_heaviest_as_their_centre() -> None:
    a = voiceprints.Embedded((1.0, 0.0, 0.0, 0.0), 8.0)
    b = voiceprints.Embedded((-1.0, 0.0, 0.0, 0.0), 8.0)
    c = voiceprints.Embedded((-1.0, 0.0, 0.0, 0.0), 4.0)
    assert (
        voiceprints.centre([a, b])
        == voiceprints.centre([b, a])
        in ((1.0, 0.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0))
    )
    assert voiceprints.centre([a, b, c]) == (-1.0, 0.0, 0.0, 0.0), "no longer cancelling: the plain centre"


def test_a_file_that_cannot_be_read_is_one_sentence(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    voiceprints.update(lb, FakeEmbedder())
    real = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self.name == voiceprints.FILE:
            raise PermissionError(13, "Permission denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(voiceprints.RegistryError, match="could not be read: Permission denied"):
        voiceprints.read(lb)
    about = voiceprints.about(lb)
    assert about is not None and about.error is not None and "could not be read" in about.error


def test_a_rebuild_without_the_model_is_refused_and_writes_nothing(lb: Logbook) -> None:
    with pytest.raises(voiceprints.RegistryError, match="needs the embedding model"):
        voiceprints.update(lb, rebuild=True)
    assert not (lb.root / voiceprints.FILE).exists()


def test_a_reseal_that_cannot_write_removes_the_file_rather_than_leave_it(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    voiceprints.update(lb, FakeEmbedder())

    def full(_lb: Logbook, _registry: voiceprints.Registry, _recipients: object = None) -> Path:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(voiceprints, "write", full)
    said = voiceprints.reseal(lb, lb.recipients)
    assert said is not None and said.startswith(f"{voiceprints.FILE} removed")
    assert not (lb.root / voiceprints.FILE).exists()
