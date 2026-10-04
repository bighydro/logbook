"""Property-based fuzz of every reader: for ANY demo record (any seed, any number of days), ANY
date window, and ANY spec-legal reshaping of the record, every reader exits 0 and prints
well-formed output (JSON under `--json`), never a traceback.

The record is `logbook demo` (`logbook.demo`), rewritten through `Logbook.append_many` with the
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
from logbook.core import rollup
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
    "keeper/v1": ("marked_at", "supersedes"),
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


MUTATIONS: dict[str, Mutation | None] = {
    "optional-fields": drop_optional_fields,
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
            if args[0] == "days":  # JSON Lines: one object per line
                parsed: Any = [json.loads(line) for line in out.splitlines() if line.strip()]
                assert parsed and all(isinstance(p, dict) for p in parsed)
            else:
                parsed = json.loads(out)
                assert isinstance(parsed, dict)
        except (ValueError, AssertionError) as e:
            raise AssertionError(f"{command} printed invalid JSON: {e}\n{out[:300]}") from e


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
        ["days", "--from", since, "--to", until],
        ["days", "--from", since, "--to", until, "--json"],
        ["trips", "--since", since, "--until", until],
        ["trips", "--since", since, "--until", until, "--json"],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run"],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run", "--json"],
        ["derive", "stays", "--day", day, "--subject", subject, "--dry-run", "--json"],
        ["infer", "flights", "--since", since, "--until", until, "--dry-run"],
        ["rollup", kind, "--since", since, "--until", until],
        ["rollup", kind, "--since", since, "--until", until, "--json"],
        ["rollup", "health", "--by", by, "--since", since, "--until", until, "--json"],
        ["rollup", "places", "--with", "--since", since, "--until", until, "--json"],
        ["places", "propose", "--since", since, "--until", until, "--top", str(top)],
        ["places", "propose", "--since", since, "--until", until, "--json"],
        ["keepers", "--since", since, "--until", until],
        ["keepers", "--since", since, "--until", until, "--lane", lane, "--json"],
        ["sources", "--gaps", "--since", since],
        ["sources", "--gaps", "--since", since, "--json"],
        ["promises", "--all", "--since", since],
        ["promises", "--all", "--since", since, "--json"],
        ["assets", "status"],
        ["assets", "status", "--json"],
        ["doctor"],
    ]


WHOLE_RECORD_READERS: list[list[str]] = [
    ["show"],
    ["days"],
    ["days", "--json"],
    ["trips"],
    ["trips", "--json"],
    *([["rollup", kind, "--json"] for kind in rollup.KINDS]),
    ["rollup", "countries"],
    ["places", "propose"],
    ["places", "propose", "--json"],
    ["keepers"],
    ["keepers", "--json"],
    ["sources", "--gaps"],
    ["sources", "--gaps", "--json"],
    ["promises", "--all"],
    ["promises", "--all", "--json"],
    ["promises"],
    ["promises", "--open", "--json"],
    ["infer", "flights", "--dry-run"],
    ["stats", "--json"],
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
        ["days", "--from", since, "--to", until],
        ["trips", "--since", since, "--until", until],
        ["derive", "stays", "--since", since, "--until", until, "--dry-run"],
        ["rollup", "countries", "--since", since, "--until", until],
        ["places", "propose", "--since", since, "--until", until],
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
        ["days", "--json"],
        ["trips", "--json"],
        ["derive", "stays", "--day", "2026-06-01", "--dry-run", "--json"],
        ["infer", "flights", "--dry-run"],
        ["rollup", "countries", "--json"],
        ["places", "propose", "--json"],
        ["keepers", "--json"],
        ["sources", "--gaps", "--json"],
        ["promises", "--all", "--json"],
        ["assets", "status", "--json"],
    ]
    for args in readers:
        code, out, err = run("unknown record timezone", args)
        assert "Traceback" not in err, (args, err[-500:])
        assert code == 2, (args, code, err)
        assert UNKNOWN_TZ in err and "zone" in err, (args, err)
        assert out == "", (args, out[:200])
