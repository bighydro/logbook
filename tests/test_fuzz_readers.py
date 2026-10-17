"""Property-based fuzz of every reader: for ANY demo record (any seed, any number of days), ANY
date window, and ANY spec-legal reshaping of the record, every reader exits 0 and prints
well-formed output (JSON under `--json`), never a traceback.

The record is `logbook demo` (`logbook.contrib.demo`), rewritten through `Logbook.append_many` with the
drafts reshaped first: optional payload fields left out (the MAY rows of each profile's RFC
table), a string `chat` (the shape before RFC 0008), a `tz` the host's zone database lacks, a day
with only tier-3 lines; and, after the write, an empty month file. SPEC §5 forbids a reader
failing on a payload it cannot interpret, §3.2 reads a string chat as a direct chat's name, §2
makes a zone name no reader may reject. The long cases are `slow` (LOGBOOK_SLOW=1); the short
ones run in CI. A failure names the seed, the days, the mutations and the command."""

from __future__ import annotations

import contextlib
import io
import json
import random
import uuid
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logbook import cli
from logbook.contrib import demo
from logbook.core import keepers, rollup
from logbook.core.index import local_date
from logbook.core.keepers import LANES
from logbook.core.store import Logbook

Draft = dict[str, Any]
Mutation = Callable[[list[Draft], random.Random], None]

# The MAY rows of each profile's RFC table (rfcs/00xx-*.md): a writer may leave every one of them out.
OPTIONAL: dict[str, tuple[str, ...]] = {
    "location/v1": (
        "accuracy_m",
        "alt_m",
        "speed_mps",
        "heading_deg",
        "provider",
        "tracker",
        "raw_id",
        "subject",
    ),
    "photo/v1": (
        "file_name",
        "media",
        "lat",
        "lon",
        "camera",
        "width",
        "height",
        "duration_s",
        "live_photo",
        "provenance",
        "faces",
        "people",
        "content_hash",
        "favorite",
        "hidden",
        "albums",
    ),
    "transcript/v1": ("raw_id", "title", "participants", "summary", "language", "content", "source_uri"),
    "resolution/v1": ("label", "confidence", "method", "evidence", "supersedes", "logbook_head"),
    "message/v1": ("sender", "text", "media", "media_kind", "reply_to", "starred", "edited"),
    "event/v1": (
        "modified_at",
        "title",
        "calendar",
        "location",
        "organizer",
        "attendees",
        "status",
        "recurrence",
        "recurrence_of",
        "notes",
        "supersedes",
    ),
    "note/v1": ("title", "raw_id", "modified_at", "folder", "labels", "attachments", "supersedes"),
    "call/v1": ("counterparty", "service"),
    "flight/v1": (
        "carrier_icao",
        "scheduled_departure",
        "scheduled_arrival",
        "actual_departure",
        "actual_arrival",
        "scheduled_takeoff",
        "actual_takeoff",
        "scheduled_landing",
        "actual_landing",
        "aircraft",
        "cancelled",
        "supersedes",
    ),
    "health-sample/v1": ("device", "source_name", "supersedes", "extra"),
    "mail/v1": (
        "message_id",
        "from",
        "to",
        "cc",
        "bcc",
        "subject",
        "date",
        "labels",
        "body",
        "attachments",
        "account",
    ),
    "task/v1": (
        "due",
        "completed_at",
        "list",
        "notes",
        "parent",
        "priority",
        "tags",
        "recurrence",
        "modified_at",
        "url",
        "supersedes",
    ),
    "browse/v1": ("title", "transition", "folder", "tags", "status", "supersedes"),
    "watch/v1": ("url", "video_id", "channel", "supersedes"),
    "listen/v1": (
        "artist",
        "show",
        "publisher",
        "album",
        "url",
        "duration_s",
        "played_s",
        "published",
        "supersedes",
    ),
    "trip/v1": ("to", "distance_m", "price", "status", "supersedes"),
    "transaction/v1": ("merchant", "category", "date", "account", "status", "note", "extra"),
    "highlight/v1": ("title", "author", "asset_id", "note", "location", "page", "modified_at", "extra"),
    "voice-memo/v1": ("title", "duration_s", "file_name", "media", "folder", "extra"),
    "keeper/v1": ("marked_at", "supersedes", "note"),
    "goal/v1": ("until", "supersedes"),
    "review/v1": ("note",),
    "chapter/v1": ("to", "supersedes"),
    "star/v1": ("note", "supersedes"),
}

# IANA-shaped, in no edition of the zone database: a name a newer edition has and this host lacks.
UNKNOWN_TZ = "Asia/Nowhere"
# A month before the record's first line: a writer that opened the file and wrote nothing.
EMPTY_MONTH = ("2026", "04.jsonl")


# -- the reshapings ----------------------------------------------------------------------------------------


def drop_optional_fields(drafts: list[Draft], rng: random.Random) -> None:
    """Each MAY field of each payload is left out with probability one half."""
    for d in drafts:
        payload = d["payload"]
        for key in OPTIONAL.get(str(payload.get("schema")), ()):
            if key in payload and rng.random() < 0.5:
                del payload[key]


def string_chat(drafts: list[Draft], rng: random.Random) -> None:
    """Every message's `chat` is the chat's name alone (the conformance sample's shape, SPEC §3.2)."""
    for d in drafts:
        payload = d["payload"]
        chat = payload.get("chat")
        if payload.get("schema") == "message/v1" and isinstance(chat, dict):
            payload["chat"] = str(chat.get("name") or chat.get("id") or "chat")


def unknown_line_tz(drafts: list[Draft], rng: random.Random) -> None:
    """Every line's `tz` is a zone this host has no table for (SPEC §2: no zone name is invalid)."""
    for d in drafts:
        d["tz"] = UNKNOWN_TZ


def tier_3_day(drafts: list[Draft], rng: random.Random) -> None:
    """One local day of the record carries nothing but tier-3 lines."""
    days = sorted({local_date(d["at"], demo.TZ) for d in drafts})
    day = rng.choice(days)
    for d in drafts:
        if local_date(d["at"], demo.TZ) == day:
            d["tier"] = 3


def goals_and_chapters(drafts: list[Draft], rng: random.Random) -> None:
    """The owner's lines of RFC 0036 on the record's days: a goal and the goal reworded, a review of
    each line of it (one backfilled, one for another period on the same day), a review of a goal the
    record does not hold, a goal with no text, a chapter closed and one open, and two chapters that
    hold the same days (two writers' record: the reader shows the later and says so). Added first,
    so `optional-fields` may take their MAY fields away."""
    days = sorted({local_date(d["at"], demo.TZ) for d in drafts})
    first, last = days[0], days[-1]
    middle = days[len(days) // 2]
    goal, reworded = str(uuid.UUID(int=rng.getrandbits(128))), str(uuid.UUID(int=rng.getrandbits(128)))

    def line(at_day: str, kind: str, payload: dict[str, Any], id_: str | None = None) -> Draft:
        draft: Draft = {
            "at": f"{at_day}T18:00:00Z",
            "source": "manual",
            "kind": kind,
            "tier": 2,
            "payload": payload,
        }
        if id_ is not None:
            draft["id"] = id_
        return draft

    opening = {"schema": "goal/v1", "text": "Sail to the islands and back.", "horizon": "year", "from": first}
    drafts.extend(
        [
            line(first, "goal", opening, goal),
            line(middle, "goal", {"schema": "goal/v1", "text": "Sail there, at anchor.", "horizon": "year",
                 "from": first, "until": last, "supersedes": goal}, reworded),
            line(rng.choice(days), "review", {"schema": "review/v1", "goal": goal, "disposition": "advancing",
                 "period": "month", "note": "Two nights out."}),
            line(last, "review", {"schema": "review/v1", "goal": reworded, "disposition": "let go",
                 "period": "month"}) | {"recorded_at": "2026-10-11T18:30:00Z"},
            line(last, "review", {"schema": "review/v1", "goal": reworded, "disposition": "stalled",
                 "period": "year"}),
            line(rng.choice(days), "review", {"schema": "review/v1", "goal": "elsewhere",
                 "disposition": "done", "period": "week"}),
            line(rng.choice(days), "goal", {"schema": "goal/v1", "horizon": "quarter"}),
            line(middle, "chapter", {"schema": "chapter/v1", "name": "Aboard", "from": first, "to": middle,
                 "rules": "Nights at anchor count."}),
            line(middle, "chapter", {"schema": "chapter/v1", "name": "Ashore", "from": middle, "rules": ""}),
            line(last, "chapter", {"schema": "chapter/v1", "name": "The yard", "from": rng.choice(days),
                 "rules": ""}),
        ]
    )  # fmt: skip


def owner_acts(drafts: list[Draft], rng: random.Random) -> None:
    """The owner's acts on lines already there: a star on a few lines (RFC 0041; a photo's is a
    `memory` keeper, RFC 0024) at each line's `at` and tier, and on a few days the note `logbook with`
    writes, `with <name>` labelled `with`."""
    marked = [d for d in drafts if d["kind"] not in ("star", "keeper", "retraction", "resolution")]
    for d in rng.sample(marked, min(8, len(marked))):
        d.setdefault("id", str(uuid.UUID(int=rng.getrandbits(128), version=4)))  # a draft may bring its id
        if d["kind"] == "photo":
            keeper = keepers.draft(d, keepers.MEMORY)
            keeper["source"] = keeper["payload"]["source"] = "manual"
            keeper["payload"]["note"] = "worth keeping"
            drafts.append(keeper)
            continue
        star = {"schema": "star/v1", "line": d["id"], "kind": d["kind"], "note": "worth keeping"}
        drafts.append({"at": d["at"], "source": "manual", "kind": "star", "tier": d["tier"], "payload": star})
    for d in rng.sample(drafts, min(3, len(drafts))):
        said = {
            "schema": "note/v1",
            "text": "with Ola Nordmann",
            "labels": ["with"],
            "extra": {"person": "p"},
        }
        drafts.append({"at": d["at"], "source": "manual", "kind": "note", "tier": 2, "payload": said})


def voices(drafts: list[Draft], rng: random.Random) -> None:
    """RFC 0038: the demo's transcripts carry voices (a room's, a call's two channels, and payloads a
    reader cannot interpret), and the owner's answers bind some of them: to a person the record names,
    to a person minted for a name, unnamed, to another voice (`alias_of`), corrected by a line that
    supersedes, with a consent the profile does not allow, and to a voice of no transcript."""
    people = [
        d["payload"]["entity"]["id"]
        for d in drafts
        if d.get("kind") == "resolution"
        and isinstance(d["payload"].get("entity"), dict)
        and d["payload"]["entity"].get("type") == "person"
    ]
    refs: list[str] = []
    for i, d in enumerate(d for d in drafts if d.get("kind") == "transcript"):
        d.setdefault("id", str(uuid.UUID(int=rng.getrandbits(128))))
        payload, shape = d["payload"], i % 4
        if shape == 0:
            payload["speakers"] = [
                {"label": f"S{n}", "seconds": rng.uniform(1, 900), "turns": n} for n in (1, 2, 3)
            ]
            payload["diarization"] = {"engine": "pyannote", "channels": 1}
        elif shape == 1:
            payload["speakers"] = [
                {"label": "mic", "seconds": 60.0, "turns": 2, "channel": "mic", "from_me": True},
                {"label": "system", "seconds": 50.0, "turns": 2, "channel": "system", "name": "Ola Nordmann"},
            ]
            payload["diarization"] = {"engine": "granola", "channels": 2}
        elif shape == 2:
            payload["speakers"] = rng.choice([{"S1": 3}, [{"label": "a#b", "turns": -1}, "S2", {"turns": 1}]])
        refs += [
            f"{d['id']}#{v['label']}"
            for v in payload.get("speakers") or []
            if isinstance(v, dict) and isinstance(v.get("label"), str) and "#" not in v["label"]
        ]
    if not refs:
        return
    at = max(d["at"] for d in drafts)

    def said(ref: str, **payload: Any) -> Draft:
        line = {
            "schema": "resolution/v1",
            "ref": {"kind": "speaker", "value": ref},
            "method": "owner",
            "basis": "voice",
            **payload,
        }
        return {
            "id": str(uuid.UUID(int=rng.getrandbits(128))),
            "at": at,
            "source": "manual",
            "kind": "resolution",
            "tier": 2,
            "payload": line,
        }

    def person(entity: str, label: str | None = None) -> dict[str, Any]:
        found: dict[str, Any] = {"entity": {"type": "person", "id": entity, "registry": "logbook"}}
        return {**found, "label": label} if label else found

    minted = str(uuid.UUID(int=rng.getrandbits(128)))
    first = said(rng.choice(refs), **person(rng.choice(people) if people else minted, "Per Hansen"))
    drafts.extend(
        [
            first,
            said(first["payload"]["ref"]["value"], **person(minted, "Per Hansen"), supersedes=first["id"]),
            said(rng.choice(refs), **person(str(uuid.UUID(int=rng.getrandbits(128)))), unnamed=True,
                 consent="unknown"),
            said(rng.choice(refs), alias_of={"kind": "speaker", "value": rng.choice(refs)}, consent="maybe"),
            said(rng.choice(refs), **person(minted), basis="text", confidence=0.4),
            said(f"{uuid.UUID(int=rng.getrandbits(128))}#S9", **person(minted, "Per Hansen")),
            said(rng.choice(refs), entity={"type": "company", "id": minted, "registry": "logbook"}),
        ]
    )  # fmt: skip


MUTATIONS: dict[str, Mutation | None] = {
    "goals-and-chapters": goals_and_chapters,
    "voices": voices,
    "optional-fields": drop_optional_fields,
    "owner-acts": owner_acts,
    "string-chat": string_chat,
    "unknown-line-tz": unknown_line_tz,
    "tier-3-day": tier_3_day,
    "empty-month-file": None,  # on the folder, after the write
}


def make_record(root: Path, days: int, seed: int, mutations: frozenset[str]) -> Logbook:
    """The demo record of (`days`, `seed`) with the drafts reshaped before `append_many` writes them, so
    the record is hashed and chained as any writer's would be; then the folder-level reshaping."""
    rng = random.Random(seed * 1_000_003 + days)
    original = demo.story_of

    def reshaped(days_: int, seed_: int, recorded_at: str) -> Any:
        story = original(days_, seed_, recorded_at)
        for name in sorted(mutations):
            mutate = MUTATIONS[name]
            if mutate is not None:
                mutate(story.drafts, rng)
        return story

    with mock.patch.object(demo, "story_of", reshaped):
        lb = demo.generate(root, days=days, seed=seed)
    if "empty-month-file" in mutations:
        path = lb.log_dir.joinpath(*EMPTY_MONTH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return lb


# -- running a reader --------------------------------------------------------------------------------------


def run(label: str, args: list[str]) -> tuple[int, str, str]:
    """`logbook <args>` in this process: (exit status, stdout, stderr). Anything but a clean exit is the
    failure, named by the record and the command, with the exception chained."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(args)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            raise AssertionError(f"{label}: `logbook {' '.join(args)}` raised {type(e).__name__}: {e}") from e
    return code, out.getvalue(), err.getvalue()


def assert_reads_cleanly(label: str, args: list[str]) -> None:
    code, out, err = run(label, args)
    command = f"{label}: `logbook {' '.join(args)}`"
    assert code == 0, f"{command} exited {code}: {err.strip()[-500:]}"
    assert "Traceback" not in err, f"{command} printed a traceback: {err[-500:]}"
    assert out.strip(), f"{command} printed nothing"
    if "--json" in args:
        try:
            if args[:2] == ["show", "days"]:  # JSON Lines: one object per line
                parsed: Any = [json.loads(line) for line in out.splitlines() if line.strip()]
                assert parsed and all(isinstance(p, dict) for p in parsed)
            else:
                parsed = json.loads(out)
                assert isinstance(parsed, dict)
        except (ValueError, AssertionError) as e:
            raise AssertionError(f"{command} printed invalid JSON: {e}\n{out[:300]}") from e


REFLECTION = "The photos went out. I'll call the yard tomorrow. Ola should book the ferry."  # `day reflect`


def windowed_readers(
    since: str, until: str, day: str, person: str, kind: str, by: str, lane: str, subject: str, top: int
) -> list[list[str]]:
    return [
        ["show", day],
        ["show", day, "--raw"],
        ["show", "person", person, "--json"],
        ["show", "asset", demo.BOAT, "--json"],
        ["show", "place", "Home", "--json"],
        ["day", day],
        ["day", day, "--json"],
        ["day", "reflect", day, "--text", REFLECTION, "--dry-run"],
        ["show", "days", "--from", since, "--to", until],
        ["show", "days", "--from", since, "--to", until, "--json"],
        ["show", "trips", "--since", since, "--until", until],
        ["show", "trips", "--since", since, "--until", until, "--json"],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run"],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run", "--json"],
        ["derive", "stays", "--day", day, "--subject", subject, "--dry-run", "--json"],
        ["derive", "flights", "--since", since, "--until", until, "--dry-run"],
        ["rollup", kind, "--since", since, "--until", until],
        ["rollup", kind, "--since", since, "--until", until, "--json"],
        ["rollup", "health", "--by", by, "--since", since, "--until", until, "--json"],
        ["rollup", "places", "--with", "--since", since, "--until", until, "--json"],
        ["setup", "places", "propose", "--since", since, "--until", until, "--top", str(top)],
        ["setup", "places", "propose", "--since", since, "--until", until, "--json"],
        ["setup", "places", "review", "--top", str(top)],
        ["setup", "places", "review", "--near", "Home", "--json"],
        ["setup", "places", "review", "--ask-photos", "--top", str(top)],
        ["show", "keepers", "--since", since, "--until", until],
        ["show", "keepers", "--since", since, "--until", until, "--lane", lane, "--json"],
        ["doctor", "sources", "--gaps", "--since", since],
        ["doctor", "sources", "--gaps", "--since", since, "--json"],
        ["promises", "--all", "--since", since],
        ["promises", "--all", "--since", since, "--json"],
        ["review", "speakers", "--named", "--day", day],
        ["review", "speakers", "--named", "--day", day, "--json"],
        ["people", "nearby", "--days", since, until],
        ["people", "nearby", "--days", since, until, "--json"],
        ["setup", "assets", "status"],
        ["setup", "assets", "status", "--json"],
        ["doctor"],
    ]


WHOLE_RECORD_READERS: list[list[str]] = [
    ["show"],
    ["show", "days"],
    ["show", "days", "--json"],
    ["show", "trips"],
    ["show", "trips", "--json"],
    *([["rollup", kind, "--json"] for kind in rollup.KINDS]),
    ["rollup", "countries"],
    ["setup", "places", "propose"],
    ["setup", "places", "propose", "--json"],
    ["setup", "places", "review"],
    ["setup", "places", "review", "--json"],
    ["setup", "places", "review", "--ask-photos", "--all", "--json"],
    ["show", "keepers"],
    ["show", "keepers", "--json"],
    ["doctor", "sources", "--gaps"],
    ["doctor", "sources", "--gaps", "--json"],
    ["promises", "--all"],
    ["promises", "--all", "--json"],
    ["promises"],
    ["promises", "--open", "--json"],
    ["derive", "flights", "--dry-run"],
    ["show", "stats", "--json"],
    ["people", "drift"],
    ["people", "drift", "--show", "--json"],
    ["people", "drift", "--quiet-days", "0", "--min-days", "1", "--show"],
    ["people", "nearby", "Home", "--json"],
    ["people", "review"],
    ["people", "review", "--json"],
    ["review", "org"],
    ["review", "org", "--json"],
    ["show", "orgs"],
    ["show", "orgs", "--json", "--money"],
    ["people"],
    ["people", "--json"],
    ["review", "speakers"],
    ["review", "speakers", "--json"],
    ["show", "orgs", "--portfolio", "Fund I"],
    ["status", "list", "org", "--json"],
    ["review", "idea"],
    ["review", "idea", "--json"],
    ["show", "ideas"],
    ["show", "ideas", "--json"],
    ["status", "list", "idea", "--json"],
    ["goal", "list"],
    ["goal", "list", "--open", "--json"],
    ["chapter", "list"],
    ["chapter", "list", "--json"],
    ["verify"],
]


# -- the strategies ----------------------------------------------------------------------------------------

# Around the record, which starts 2026-06-01 and may run for weeks; a window may miss it on either side.
FIRST, LAST = date(2026, 4, 15), date(2026, 9, 30)
local_day = st.integers(0, (LAST - FIRST).days).map(lambda n: (FIRST + timedelta(days=n)).isoformat())
window = st.tuples(local_day, local_day).map(sorted)
mutation_sets = st.frozensets(st.sampled_from(sorted(MUTATIONS)))
person = st.sampled_from([p.entity for p in demo.PEOPLE])  # an entity id finds a person without a label
rollup_kind = st.sampled_from(rollup.KINDS)
period = st.sampled_from(rollup.PERIODS)
lane = st.sampled_from(LANES)
subject = st.sampled_from(["owner", demo.BOAT])
top = st.integers(0, 5)


class Records:
    """The records of this session, generated once per (days, seed, mutations) and kept."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.made: dict[tuple[int, int, frozenset[str]], Logbook] = {}

    def get(self, days: int, seed: int, mutations: frozenset[str]) -> tuple[Logbook, bool]:
        key = (days, seed, mutations)
        fresh = key not in self.made
        if fresh:
            name = f"d{days}-s{seed}-" + ("-".join(sorted(mutations)) or "plain")
            self.made[key] = make_record(self.folder / name, days, seed, mutations)
        return self.made[key], fresh


@pytest.fixture(scope="module")
def records(tmp_path_factory: pytest.TempPathFactory) -> Records:
    return Records(tmp_path_factory.mktemp("fuzz"))


@contextlib.contextmanager
def at_home(lb: Logbook) -> Iterator[None]:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(lb.root))
        yield


def every_reader_reads(
    records: Records,
    days: int,
    seed: int,
    mutations: frozenset[str],
    since_until: list[str],
    day: str,
    who: str,
    kind: str,
    by: str,
    which_lane: str,
    whose: str,
    n: int,
) -> None:
    label = f"demo --days {days} --seed {seed}, mutations {sorted(mutations) or 'none'}"
    lb, fresh = records.get(days, seed, mutations)
    since, until = since_until
    with at_home(lb):
        if fresh:
            for args in WHOLE_RECORD_READERS:
                assert_reads_cleanly(label, args)
        for args in windowed_readers(since, until, day, who, kind, by, which_lane, whose, n):
            assert_reads_cleanly(label, args)


# -- the properties ----------------------------------------------------------------------------------------


@pytest.mark.slow
@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    days=st.sampled_from([1, 2, 3, 5]),
    seed=st.sampled_from([1, 2, 3]),
    mutations=mutation_sets,
    since_until=window,
    day=local_day,
    who=person,
    kind=rollup_kind,
    by=period,
    which_lane=lane,
    whose=subject,
    n=top,
)
def test_every_reader_reads_any_short_record_in_any_window(
    records: Records,
    days: int,
    seed: int,
    mutations: frozenset[str],
    since_until: list[str],
    day: str,
    who: str,
    kind: str,
    by: str,
    which_lane: str,
    whose: str,
    n: int,
) -> None:
    every_reader_reads(records, days, seed, mutations, since_until, day, who, kind, by, which_lane, whose, n)


@pytest.mark.slow
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    days=st.integers(1, 70),
    seed=st.integers(1, 1_000_000),
    mutations=mutation_sets,
    since_until=window,
    day=local_day,
    who=person,
    kind=rollup_kind,
    by=period,
    which_lane=lane,
    whose=subject,
    n=top,
)
def test_every_reader_reads_any_record_in_any_window(
    records: Records,
    days: int,
    seed: int,
    mutations: frozenset[str],
    since_until: list[str],
    day: str,
    who: str,
    kind: str,
    by: str,
    which_lane: str,
    whose: str,
    n: int,
) -> None:
    every_reader_reads(records, days, seed, mutations, since_until, day, who, kind, by, which_lane, whose, n)


@pytest.mark.slow
@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(1, 1_000_000), since_until=window, day=local_day, who=person)
def test_every_reader_reads_a_fully_reshaped_long_record(
    records: Records, seed: int, since_until: list[str], day: str, who: str
) -> None:
    """Every reshaping at once on a record longer than the story's four-week cycle."""
    every_reader_reads(
        records, 35, seed, frozenset(MUTATIONS), since_until, day, who, "places", "week", LANES[0], "owner", 3
    )


# -- the edges, once -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def short(records: Records) -> Logbook:
    lb, _fresh = records.get(2, 11, frozenset())
    return lb


def test_a_window_that_runs_backwards_is_refused_without_a_traceback(short: Logbook) -> None:
    since, until = "2026-06-02", "2026-06-01"
    backwards = [
        ["show", "days", "--from", since, "--to", until],
        ["show", "trips", "--since", since, "--until", until],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run"],
        ["rollup", "countries", "--since", since, "--until", until],
        ["setup", "places", "propose", "--since", since, "--until", until],
    ]
    with at_home(short):
        for args in backwards:
            code, out, err = run("backwards window", args)
            assert code == 2 and "backwards" in err and "Traceback" not in err, (args, code, err)
            assert out == ""


def test_a_record_timezone_the_host_lacks_is_said_never_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC §2: a reader that must localise a time and does not know the zone MUST say so, and MUST NOT
    substitute another zone. `logbook.json` names the zone; every reader that localises exits 2 naming it."""
    lb = demo.generate(tmp_path / "Demo", days=2, seed=5)
    meta = lb.meta
    meta["timezone"] = UNKNOWN_TZ
    lb._save_meta(meta)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    readers = [
        ["show", "2026-06-01"],
        ["day", "2026-06-01", "--json"],
        ["show", "days", "--json"],
        ["show", "trips", "--json"],
        ["derive", "stays", "--day", "2026-06-01", "--dry-run", "--json"],
        ["derive", "flights", "--dry-run"],
        ["rollup", "countries", "--json"],
        ["setup", "places", "propose", "--json"],
        ["setup", "places", "review", "--json"],
        ["show", "keepers", "--json"],
        ["doctor", "sources", "--gaps", "--json"],
        ["promises", "--all", "--json"],
        ["setup", "assets", "status", "--json"],
        ["people", "drift", "--json"],
        ["people", "nearby", "Home", "--json"],
    ]
    for args in readers:
        code, out, err = run("unknown record timezone", args)
        assert "Traceback" not in err, (args, err[-500:])
        assert code == 2, (args, code, err)
        assert UNKNOWN_TZ in err and "zone" in err, (args, err)
        assert out == "", (args, out[:200])
