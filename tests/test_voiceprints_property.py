"""The voiceprint registry is a cache of the record (RFC 0038 §5.2), checked by property. A record
sealed to two recipients is taken through what the commands do to it (`derive transcripts` appends a
transcript and writes with the model; the review binds, rebinds and retracts and writes without it;
the owner edits `policy/speakers.json`; `setup speakers --rebuild`; a model change), and after every
write the file is compared with a rebuild from nothing on a copy of the same record and with a model
of who the record says is held (`Who`, `should_hold`). The claims of `voiceprints`' docstring, as
checked here:

1. After a write WITH the embedder the file is exactly the document a rebuild makes from the same
   record (`to_json` equal), and that document is what the model says: every voice of a standing
   transcript that is held and has `min_clean_s` of clean speech, with the vector the fake answers
   for whoever speaks it, no other.
2. After a write WITHOUT the embedder (the review's) the file is the rebuild restricted to the voices
   the file held before the write: every voice it holds has the rebuild's embedding and clean seconds;
   a person's voiceprint is the rebuild's whenever the file holds every voice the rebuild holds for
   them; and the voices the rebuild holds and the file does not are exactly those of the rebuild's in
   `let_go`, the model's set of voices whose embedding the file let go at an earlier write (or never
   had: a transcript heard again and not yet heard), kept as `let_go = (let_go | before) - after` at
   every write.
3. Never: a `forget` entity among `people` or among the holders of the voices held; an unnamed
   person's voice without `enrol_unnamed`; a voice of a transcript that is retracted or superseded;
   a voice with less than `min_clean_s` of clean speech.

Synthetic data only: the Oslo persona of `voiceprints_record`, whose fake embedder reads who speaks
from a JSON file standing in for the audio; no model is downloaded, loaded or called. Clean seconds
are computed here on a half-second grid, not with `voiceprints.clean_pieces`."""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    precondition,
    rule,
    run_state_machine_as_test,
)
from persona import TZ
from speakers_record import (
    CALL,
    CALL_TEXT,
    DINNER,
    DINNER_TEXT,
    KARI_ID,
    OLA_ID,
    ROOM,
    TWO_CHANNELS,
    attribution,
    transcript,
)
from voiceprints_record import CALL_VOICES, DIM, DINNER_VOICES, WHO, FakeEmbedder, seal, stored, voiced_record

from logbook.core import attachments, speakers, voiceprints
from logbook.core.store import Logbook

OTHER_MODEL = "example/other-embedding"
# How far a turn starts before its nominal start (5i): 0 keeps the record's shape (4 s segments, 1 s
# apart); 1.5 and more overlap the turn before by that less one second, leaving it 3.5, 3, 2.5, 2, 1.5
# or 0.5 clean seconds, so pieces fall on both sides of the two-second rule and the clean seconds of
# both voices vary.
OVERLAPS = (0.0, 0.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.5)
CELL = 0.5  # the grid the model computes clean speech on; every turn boundary is a multiple of it
PIECE_CELLS = int(voiceprints.CLEAN_PIECE_S / CELL)
TARGETS = ("owner", "kari", "ola", "fresh", "unnamed")
EPOCH = datetime(2026, 10, 1, tzinfo=UTC)

persons = st.sampled_from(WHO)
# (which voice speaks, the overlap) per turn: long enough that voices reach `min_clean_s` (8 s by
# default) often, short enough that some stay under it
scripts = st.lists(st.tuples(st.integers(0, 2), st.sampled_from(OVERLAPS)), min_size=2, max_size=8)
audio_modes = st.sampled_from(("stored", "stored", "stored", "missing", "none"))
targets = st.sampled_from(TARGETS)


# -- the model ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Who:
    """Whose a standing voice is, as the record says: an entity id (the owner's for `from_me` and for
    a line binding the owner), None for a voice not yet named; `unnamed` for a person the owner
    declined to name."""

    entity: str | None
    unnamed: bool = False


@dataclass
class Voice:
    label: str
    person: str  # whose voice the fake audio carries: a key of `VECTORS`
    from_me: bool
    turns: list[tuple[float, float]]


@dataclass
class Transcript:
    id: str
    seq: int
    voices: dict[str, Voice]
    hearable: bool  # its audio and its spans file are in the store
    supersedes: str | None = None


@dataclass
class Attribution:
    id: str
    seq: int
    ref: str
    entity: str
    unnamed: bool
    supersedes: str | None


def clean_seconds(turns: dict[str, list[tuple[float, float]]], label: str) -> float:
    """The clean speech of `label` on a half-second grid: the cells its turns cover and no other
    voice's do, in runs of two seconds or more."""
    cells = int(max((to for spans in turns.values() for _from, to in spans), default=0.0) / CELL)
    mine, others = [False] * cells, [False] * cells
    for who, spans in turns.items():
        for start, end in spans:
            for cell in range(int(start / CELL), int(end / CELL)):
                (mine if who == label else others)[cell] = True
    total = run = 0
    for cell in range(cells + 1):
        if cell < cells and mine[cell] and not others[cell]:
            run += 1
            continue
        if run >= PIECE_CELLS:
            total += run
        run = 0
    return total * CELL


def stamp(instant: datetime) -> str:
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _draft(line: dict[str, Any]) -> dict[str, Any]:
    """A `speakers_record` line as `Logbook.append` takes it."""
    return {k: line[k] for k in ("at", "source", "kind", "tier", "payload")}


# -- the machine ----------------------------------------------------------------------------------------


class RegistryMachine(RuleBasedStateMachine):
    """One sealed record and the model of what its registry should hold; every rule ends in a write
    and the checks of the module docstring."""

    def __init__(self, example: int, folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__()
        self.folder = folder
        lb = Logbook.init(folder / "lb", TZ)
        # The owner's id is drawn from (`forget`) in sorted company, so a minted one would give the
        # same draws another meaning on every run: fixed per example, the run replays exactly.
        lb.set_meta(owner_id=f"0199f3a0-7c21-7000-8002-{example:012x}")
        self.lb = seal(lb, monkeypatch, folder)
        self.owner_id = str(self.lb.meta["owner_id"])
        self.transcripts: dict[str, Transcript] = {}
        self.attributions: list[Attribution] = []
        self.retracted: set[str] = set()
        self.forget: frozenset[str] = frozenset()
        self.enrol_unnamed = False
        self.min_clean_s = float(voiceprints.DEFAULTS["min_clean_s"])
        self.model = voiceprints.MODEL
        self.let_go: set[str] = set()  # hearable voices whose embedding the file does not hold
        self.minted = count(1)
        self.copies = count(1)

    # -- the record ---------------------------------------------------------------------------------

    @initialize(seeded=st.booleans(), with_audio=st.booleans())
    def start(self, seeded: bool, with_audio: bool) -> None:
        """Empty, or the dinner and the call of `voiced_record`, with or without their audio."""
        if not seeded:
            return
        voiced_record(self.lb, audio=with_audio)
        seqs = {
            str(line["id"]): int(line["seq"]) for line in self.lb.lines() if line.get("kind") == "transcript"
        }
        for id_, said, voices, who in (
            (DINNER, DINNER_TEXT, ROOM, DINNER_VOICES),
            (CALL, CALL_TEXT, TWO_CHANNELS, CALL_VOICES),
        ):
            found = {}
            for v in voices:
                label = str(v["label"])
                turns = [
                    (5.0 * i, 5.0 * i + 4.0) for i, (spoken, _text) in enumerate(said) if spoken == label
                ]
                found[label] = Voice(label, who[label], v.get("from_me") is True, turns)
            self.remember(Transcript(id_, seqs[id_], found, with_audio))

    def remember(self, found: Transcript) -> None:
        self.transcripts[found.id] = found
        self.let_go |= self.hearable_refs(found)

    def add_transcript(
        self,
        call: bool,
        people: list[str],
        script: list[tuple[int, float]],
        audio: str,
        supersedes: str | None,
    ) -> Transcript:
        """A transcript with its text, its spans file and (stored, named but missing, or not named)
        its fake audio, through `Logbook.attach` and `append_many` as `derive transcripts` does."""
        n = next(self.minted)
        id_ = f"0199f3a0-7c21-7000-8000-{n:012x}"
        labels: list[tuple[str, str | None, bool]] = (
            [("mic", "mic", True), ("system", "system", False)]
            if call
            else [(f"S{i + 1}", None, False) for i in range(len(people))]
        )
        persons = {label: (people * 2)[k] for k, (label, _channel, _from_me) in enumerate(labels)}
        turns: dict[str, list[tuple[float, float]]] = {label: [] for label, _channel, _from_me in labels}
        said: list[tuple[str, tuple[float, float], str]] = []
        for i, (which, overlap) in enumerate(script):
            label = labels[which % len(labels)][0]
            span = (max(0.0, 5.0 * i - overlap), 5.0 * i + 4.0)
            turns[label].append(span)
            said.append((label, span, f"Setning {i + 1}."))
        text = "\n".join(t for _label, _span, t in said).encode("utf-8") + b"\n"
        content = attachments.reference(text, "text/plain")
        self.lb.attach(text)
        segments = [{"from": start, "to": end, "speaker": label} for label, (start, end), _t in said]
        document = {
            "format": speakers.FORMAT,
            "content": content["sha256"],
            "segments": segments,
            "turns": segments,
        }
        raw = speakers.spans_bytes(document)
        self.lb.attach(raw)
        spans = attachments.reference(raw, speakers.MEDIA_TYPE)
        sound = json.dumps(
            {"fake-audio": 1, "who": [[start, end, persons[label]] for label, (start, end), _t in said]},
            sort_keys=True,
        ).encode("utf-8")
        digest = None if audio == "none" else attachments.digest(sound)
        if audio == "stored":
            self.lb.attach(sound)
        voices: list[dict[str, Any]] = []
        for label, channel, from_me in labels:
            voice: dict[str, Any] = {
                "label": label,
                "seconds": round(math.fsum(end - start for start, end in turns[label]), 2),
                "turns": len(turns[label]),
            }
            if channel is not None:
                voice["channel"] = channel
            if from_me:
                voice["from_me"] = True
            voices.append(voice)
        at = EPOCH + timedelta(hours=n)
        draft = transcript(
            id_,
            stamp(at),
            stamp(at + timedelta(minutes=10)),
            f"Opptak {n}",
            voices,
            raw_id=f"memo-{n}",
            content=content,
            spans=spans,
            audio=digest,
            supersedes=supersedes,
        )
        assert self.lb.append_many([draft]) == 1
        found = Transcript(
            id_,
            int(self.lb.meta["seq"]),
            {label: Voice(label, persons[label], from_me, turns[label]) for label, _c, from_me in labels},
            audio == "stored",
            supersedes,
        )
        self.remember(found)
        return found

    def attribute(self, ref: str, target: str, supersedes: str | None) -> None:
        """One `speaker` resolution as the review writes it: to the owner, Kari, Ola, a person
        minted now, or an unnamed person minted now."""
        entity, unnamed, name = {
            "owner": (self.owner_id, False, None),
            "kari": (KARI_ID, False, "Kari Nordmann"),
            "ola": (OLA_ID, False, "Ola Nordmann"),
            "fresh": (self.mint_entity(), False, "Gjest"),
            "unnamed": (self.mint_entity(), True, None),
        }[target]
        line_id, _sep, label = ref.partition("#")
        line = self.lb.append(
            **_draft(attribution(line_id, label, entity, name=name, unnamed=unnamed, supersedes=supersedes))
        )
        self.attributions.append(
            Attribution(str(line["id"]), int(line["seq"]), ref, entity, unnamed, supersedes)
        )

    def mint_entity(self) -> str:
        return f"0199f3a0-7c21-7000-8001-{next(self.minted):012x}"

    # -- the rules ----------------------------------------------------------------------------------

    @rule(
        call=st.booleans(),
        people=st.lists(persons, min_size=1, max_size=3),
        script=scripts,
        audio=audio_modes,
    )
    def append_transcript(
        self, call: bool, people: list[str], script: list[tuple[int, float]], audio: str
    ) -> None:
        """`derive transcripts`: a new transcript, then a write that hears."""
        self.add_transcript(call, people, script, audio, supersedes=None)
        self.write(FakeEmbedder(model=self.model))

    @precondition(lambda self: self.standing_refs())
    @rule(data=st.data(), who=targets)
    def bind(self, data: st.DataObject, who: str) -> None:
        """An answer in the review: a voice bound, then a write without the model."""
        ref = data.draw(st.sampled_from(self.standing_refs()), label="ref")
        self.attribute(ref, who, supersedes=None)
        self.write(None)

    @precondition(lambda self: self.standing_attributions())
    @rule(data=st.data(), who=targets)
    def rebind(self, data: st.DataObject, who: str) -> None:
        """A correction (§4.5): a new line for the same voice, `supersedes` the standing one."""
        old = data.draw(st.sampled_from(self.standing_attributions()), label="attribution")
        self.attribute(old.ref, who, supersedes=old.id)
        self.write(None)

    @precondition(lambda self: self.live_attributions())
    @rule(data=st.data())
    def retract_attribution(self, data: st.DataObject) -> None:
        line = data.draw(st.sampled_from(self.live_attributions()), label="attribution")
        self.lb.retract(line.seq, "not them")
        self.retracted.add(line.id)
        self.write(None)

    @precondition(lambda self: self.live_transcripts())
    @rule(data=st.data())
    def retract_transcript(self, data: st.DataObject) -> None:
        line = data.draw(st.sampled_from(self.live_transcripts()), label="transcript")
        self.lb.retract(line.seq, "heard wrong")
        self.retracted.add(line.id)
        self.write(None)

    @precondition(lambda self: self.standing_transcripts())
    @rule(
        data=st.data(),
        call=st.booleans(),
        people=st.lists(persons, min_size=1, max_size=3),
        script=scripts,
        audio=audio_modes,
    )
    def supersede_transcript(
        self, data: st.DataObject, call: bool, people: list[str], script: list[tuple[int, float]], audio: str
    ) -> None:
        """A transcript heard again (§2.8): a new line that `supersedes` a standing one, followed by
        the review's write; its voices wait for the next write that hears."""
        old = data.draw(st.sampled_from(sorted(self.standing_transcripts())), label="transcript")
        self.add_transcript(call, people, script, audio, supersedes=old)
        self.write(None)

    @rule(
        data=st.data(),
        enrol_unnamed=st.booleans(),
        min_clean_s=st.sampled_from((4, 8, 12)),
        hear=st.booleans(),
    )
    def change_settings(self, data: st.DataObject, enrol_unnamed: bool, min_clean_s: int, hear: bool) -> None:
        """`policy/speakers.json` edited, then a write with or without the model."""
        forget = data.draw(
            st.lists(st.sampled_from(sorted(self.known_entities())), max_size=2, unique=True), label="forget"
        )
        (self.lb.root / "policy").mkdir(exist_ok=True)
        (self.lb.root / "policy" / "speakers.json").write_text(
            json.dumps({"forget": forget, "enrol_unnamed": enrol_unnamed, "min_clean_s": min_clean_s}),
            encoding="utf-8",
        )
        self.forget, self.enrol_unnamed, self.min_clean_s = (
            frozenset(forget),
            enrol_unnamed,
            float(min_clean_s),
        )
        self.write(FakeEmbedder(model=self.model) if hear else None)

    @rule(how=st.sampled_from(("hear", "hear", "rebuild", "model")))
    def derive(self, how: str) -> None:
        """A write that hears: `derive speakers` (what the file should hold and does not), `setup
        speakers --rebuild`, or `derive speakers` after the configured model changed (which
        rebuilds)."""
        if how == "model":
            self.model = OTHER_MODEL if self.model == voiceprints.MODEL else voiceprints.MODEL
        self.write(FakeEmbedder(model=self.model), rebuild=how == "rebuild")

    # -- what the record says -----------------------------------------------------------------------

    def live_transcripts(self) -> list[Transcript]:
        return sorted(
            (t for t in self.transcripts.values() if t.id not in self.retracted), key=lambda t: t.seq
        )

    def standing_transcripts(self) -> dict[str, Transcript]:
        """Not retracted, not superseded by a transcript that is not retracted (§3.3 rule 5)."""
        live = self.live_transcripts()
        superseded = {t.supersedes for t in live if t.supersedes is not None}
        return {t.id: t for t in live if t.id not in superseded}

    def standing_refs(self) -> list[str]:
        return sorted(f"{t.id}#{label}" for t in self.standing_transcripts().values() for label in t.voices)

    def live_attributions(self) -> list[Attribution]:
        return sorted((a for a in self.attributions if a.id not in self.retracted), key=lambda a: a.seq)

    def standing_attributions(self) -> list[Attribution]:
        """The line that decides each voice (RFC 0006 rule 4, as `resolve.standing` reads it): the
        last line in chain order that is not retracted and that no line standing `supersedes`."""
        live = self.live_attributions()
        superseded = {a.supersedes for a in live if a.supersedes is not None}
        last: dict[str, Attribution] = {}
        for line in live:
            if line.id not in superseded:
                last[line.ref] = line
        return sorted(last.values(), key=lambda a: a.seq)

    def whose(self) -> dict[str, Who]:
        """Every voice of a standing transcript, joined to who it is (§3.4)."""
        deciding = {a.ref: a for a in self.standing_attributions()}
        found: dict[str, Who] = {}
        for t in self.standing_transcripts().values():
            for voice in t.voices.values():
                ref = f"{t.id}#{voice.label}"
                line = deciding.get(ref)
                if line is not None:
                    found[ref] = Who(line.entity, line.unnamed and line.entity != self.owner_id)
                elif voice.from_me:
                    found[ref] = Who(self.owner_id)
                else:
                    found[ref] = Who(None)
        return found

    def held(self, who: Who) -> bool:
        if who.entity is not None and who.entity in self.forget:
            return False
        return not who.unnamed or self.enrol_unnamed

    def clean(self, t: Transcript, label: str) -> float:
        return clean_seconds({v.label: v.turns for v in t.voices.values()}, label)

    def hearable_refs(self, t: Transcript) -> set[str]:
        """The voices of `t` a write that hears could embed: its audio and spans file in the store,
        and some clean speech."""
        if not t.hearable:
            return set()
        return {f"{t.id}#{label}" for label in t.voices if self.clean(t, label) > 0}

    def should_hold(self) -> dict[str, tuple[voiceprints.Vector, float, Who]]:
        """ref → (the vector the fake answers, the clean seconds, whose) for every voice a rebuild
        holds: of a standing transcript whose audio is there, held, with `min_clean_s` of clean
        speech."""
        whose = self.whose()
        found: dict[str, tuple[voiceprints.Vector, float, Who]] = {}
        for t in self.standing_transcripts().values():
            if not t.hearable:
                continue
            for voice in t.voices.values():
                ref = f"{t.id}#{voice.label}"
                seconds = self.clean(t, voice.label)
                if self.held(whose[ref]) and seconds > 0 and seconds >= self.min_clean_s:
                    found[ref] = (stored(voice.person), seconds, whose[ref])
        return found

    def known_entities(self) -> set[str]:
        return {self.owner_id, KARI_ID, OLA_ID} | {a.entity for a in self.attributions}

    # -- a write and its checks ---------------------------------------------------------------------

    def write(self, embedder: FakeEmbedder | None, *, rebuild: bool = False) -> None:
        before = voiceprints.read(self.lb)
        summary = voiceprints.update(self.lb, embedder, rebuild=rebuild)
        if embedder is None and before is None:
            assert summary.state == voiceprints.NO_REGISTRY and not voiceprints.path_of(self.lb.root).exists()
            return
        assert summary.written, summary
        again = embedder is not None and before is not None and (rebuild or before.model != embedder.model)
        assert summary.state == (voiceprints.REBUILT if again else voiceprints.WRITTEN), summary
        after = voiceprints.read(self.lb)
        assert after is not None
        model = embedder.model if embedder is not None else after.model
        expected = self.rebuilt(model)
        self.check_rebuild(expected, model)
        if embedder is not None:
            assert after.to_json() == expected.to_json(), "a write that hears leaves the rebuild's document"
        else:
            assert before is not None
            self.check_review_write(before, after, expected)
        self.check_never(after)
        was = set(before.pool()) if before is not None else set()
        self.let_go = (self.let_go | was) - set(after.pool())
        hearable = set().union(*(self.hearable_refs(t) for t in self.transcripts.values()))
        assert self.let_go | set(after.pool()) == hearable and self.let_go.isdisjoint(after.pool())

    def rebuilt(self, model: str) -> voiceprints.Registry:
        """The document `setup speakers --rebuild` makes from nothing, on a copy of the record, so
        the record under test is not disturbed. The copy is at the same head with the same
        `owner_id`, so it reads through the same index (RFC 0029 §8: the index is keyed by the
        owner, outside the record), which a rebuild never writes."""
        copy = self.folder / f"copy-{next(self.copies)}"
        shutil.copytree(self.lb.root, copy)
        voiceprints.path_of(copy).unlink(missing_ok=True)
        other = Logbook(copy)
        summary = voiceprints.update(other, FakeEmbedder(model=model), rebuild=True)
        assert summary.written, summary
        found = voiceprints.read(other)
        assert found is not None
        shutil.rmtree(copy, ignore_errors=True)
        return found

    def check_rebuild(self, found: voiceprints.Registry, model: str) -> None:
        """The rebuild against the model: who is held, each voice's vector and clean seconds, how
        they are grouped."""
        wanted = self.should_hold()
        pool = found.pool()
        assert set(pool) == set(wanted)
        for ref, (vector, seconds, who) in wanted.items():
            assert pool[ref].embedding == vector and pool[ref].clean_s == seconds, ref
            if who.entity is None:
                assert ref in found.voices
            else:
                assert ref in found.people[who.entity].voices
        assert set(found.people) == {who.entity for _v, _s, who in wanted.values() if who.entity is not None}
        for entity, print_ in found.people.items():
            assert print_.refs == sorted(ref for ref, (_v, _s, who) in wanted.items() if who.entity == entity)
            assert print_.clean_s == round(math.fsum(wanted[ref][1] for ref in print_.refs), 2)
        assert (found.model, found.dim, found.head) == (model, DIM, str(self.lb.meta["head"]))

    def check_review_write(
        self, before: voiceprints.Registry, after: voiceprints.Registry, expected: voiceprints.Registry
    ) -> None:
        """Claim 2: the file is the rebuild restricted to the voices the file held before."""
        assert (after.model, after.model_sha256, after.dim, after.head) == (
            expected.model,
            expected.model_sha256,
            expected.dim,
            expected.head,
        )
        was, now, want = before.pool(), after.pool(), expected.pool()
        assert set(now) == set(was) & set(want), (
            "a write without the model keeps what stands and hears nothing"
        )
        for ref in now:
            assert now[ref] == want[ref], ref
        missing = set(want) - set(now)
        assert missing == self.let_go & set(want), "the voices lacking are exactly those let go earlier"
        assert set(after.voices) == set(expected.voices) & set(was)
        assert set(after.people) == {e for e, p in expected.people.items() if set(p.voices) & set(was)}
        for entity, print_ in after.people.items():
            whole = expected.people[entity]
            assert set(print_.voices) <= set(whole.voices)
            if set(print_.voices) == set(whole.voices):
                assert print_.voiceprint == whole.voiceprint and print_.clean_s == whole.clean_s, entity
            else:
                assert print_.voiceprint == voiceprints.centre(print_.voices[ref] for ref in print_.refs)

    def check_never(self, found: voiceprints.Registry) -> None:
        """Claim 3, on the file, from the model alone."""
        whose = self.whose()
        standing = self.standing_transcripts()
        for ref, embedded in found.pool().items():
            line_id, _sep, label = ref.partition("#")
            assert line_id in standing, "a voice of a transcript that is retracted or superseded"
            who = whose[ref]
            assert who.entity is None or who.entity not in self.forget, "a voice of a forgotten entity"
            assert not who.unnamed or self.enrol_unnamed, "an unnamed person's voice without enrol_unnamed"
            assert embedded.clean_s >= self.min_clean_s, "a voice with less than min_clean_s"
            assert embedded.clean_s == self.clean(standing[line_id], label), (
                "the clean seconds are the spans'"
            )
            if who.entity is None:
                assert ref in found.voices
            else:
                assert ref in found.people[who.entity].voices
        for entity in found.people:
            assert entity not in self.forget, "a forgotten entity among people"
            assert not any(whose[ref].unnamed for ref in found.people[entity].voices) or self.enrol_unnamed


def test_the_registry_is_a_cache_of_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    examples = count(1)
    run_state_machine_as_test(
        lambda: RegistryMachine((n := next(examples)), tmp_path / f"example-{n}", monkeypatch),
        settings=settings(
            max_examples=20, stateful_step_count=20, deadline=None, derandomize=True, print_blob=True
        ),
    )
