"""Apple Podcasts' MTLibrary.sqlite → listen/v1 (RFC 0019): a line per played episode, from a copy, an
iPhone backup or live; `completed` from the playhead, the feed's transcript URL kept and never fetched."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import apple_podcasts as podcasts
from logbook.core.store import Logbook

ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200
LINES = 4

SHOWS = [  # (Z_PK, ZUUID, ZTITLE, ZAUTHOR)
    (1, "SHOW-1", "Havnepodden", "Havnekontoret"),
    (2, "SHOW-2", "Knots Weekly", None),
]
# (Z_PK, ZUUID, ZTITLE, ZLASTDATEPLAYED, ZPLAYHEAD, ZDURATION, ZPLAYCOUNT, ZPUBDATE, ZWEBPAGEURL,
#  ZENCLOSUREURL, ZAUTHOR, ZPODCAST, ZPODCASTUUID, ZTRANSCRIPTURL, ZTRANSCRIPTIDENTIFIER)
EPISODES = [
    (
        10,
        "EP-10",
        "Episode 12: the east berth",
        1772614800.0 - APPLE_EPOCH,  # 2026-03-04T09:00:00Z
        1801.5,
        2400.0,
        1,
        1772528400.0 - APPLE_EPOCH,  # 2026-03-03T09:00:00Z
        "https://havn.example.org/podden/12",
        "https://havn.example.org/podden/12.mp3",
        "Havnekontoret",
        1,
        "SHOW-1",
        None,
        "transcript-ep-10",  # Apple's own transcript asset, not a public URL: never recorded
    ),
    (
        11,
        "EP-11",
        "Bowline",
        1770796800.0 - APPLE_EPOCH,
        0.0,
        600.0,
        0,
        None,
        None,
        None,
        None,
        2,
        "SHOW-2",
        None,
        None,
    ),
    (
        12,
        "EP-12",
        "Orphan",
        1767225600.0 - APPLE_EPOCH,
        30.0,
        None,
        2,
        None,
        None,
        "https://x.example.org/o.mp3",
        "Ola",
        None,
        "NOPE",
        None,
        None,
    ),
    (13, "EP-13", "Never played", None, 0.0, 100.0, 0, None, None, None, None, 1, "SHOW-1", None, None),
    (
        14,
        "EP-14",
        "",
        1767225600.0 - APPLE_EPOCH,
        0.0,
        100.0,
        0,
        None,
        None,
        None,
        None,
        1,
        "SHOW-1",
        None,
        None,
    ),
    (  # played to the end: the store rewound the playhead and counted the play; a transcript in its feed
        15,
        "EP-15",
        "Reef knot",
        1772691000.0 - APPLE_EPOCH,  # 2026-03-05T06:10:00Z
        0.0,
        900.0,
        1,
        None,
        None,
        "https://knots.example.org/reef.mp3",
        None,
        2,
        "SHOW-2",
        "https://knots.example.org/reef.vtt",
        None,
    ),
]


def _store(folder: Path, columns: str = "modern", wal: bool = False) -> Path:
    """A synthetic MTLibrary.sqlite. `columns`: `modern` (every column the adapter reads), `older`
    (no ZWEBPAGEURL, ZPLAYCOUNT or ZPODCAST, and no ZMTPODCAST table), `bare` (the required three)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "MTLibrary.sqlite"
    con = sqlite3.connect(path)
    try:
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        episode_columns = [
            "Z_PK INTEGER PRIMARY KEY",
            "ZUUID VARCHAR",
            "ZTITLE VARCHAR",
            "ZLASTDATEPLAYED TIMESTAMP",
        ]
        keep = {
            "modern": set(podcasts.OPTIONAL),
            "older": {"ZPLAYHEAD", "ZDURATION", "ZPUBDATE", "ZENCLOSUREURL", "ZAUTHOR", "ZPODCASTUUID"},
            "bare": set(),
        }[columns]
        episode_columns += [f"{c} {_type(c)}" for c in podcasts.OPTIONAL if c in keep]
        episode_columns += ["ZENTITLEMENTSTATE INTEGER", "ZCLEANEDTITLE VARCHAR"]  # columns nobody reads
        con.execute(f"CREATE TABLE ZMTEPISODE ({', '.join(episode_columns)})")
        names = ["Z_PK", "ZUUID", "ZTITLE", "ZLASTDATEPLAYED"] + [c for c in podcasts.OPTIONAL if c in keep]
        for row in EPISODES:
            values = dict(
                zip(["Z_PK", "ZUUID", "ZTITLE", "ZLASTDATEPLAYED", *podcasts.OPTIONAL], row, strict=True)
            )
            con.execute(
                f"INSERT INTO ZMTEPISODE ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                [values[n] for n in names],
            )
        if columns != "older":
            con.execute(
                "CREATE TABLE ZMTPODCAST (Z_PK INTEGER PRIMARY KEY, ZUUID VARCHAR, ZTITLE VARCHAR,"
                " ZAUTHOR VARCHAR, ZFEEDURL VARCHAR)"
            )
            con.executemany("INSERT INTO ZMTPODCAST (Z_PK, ZUUID, ZTITLE, ZAUTHOR) VALUES (?,?,?,?)", SHOWS)
        con.commit()
    finally:
        con.close()
    return path


def _type(column: str) -> str:
    if column in ("ZPLAYCOUNT", "ZPODCAST"):
        return "INTEGER"
    return "FLOAT" if column in ("ZPLAYHEAD", "ZDURATION", "ZPUBDATE") else "VARCHAR"


def _lines(path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(podcasts.run(path, timezone=TZ, **kw))


# -- registry, sniff ----------------------------------------------------------------------------


def test_registry_has_apple_podcasts_as_a_file_and_a_live_adapter(tmp_path):
    assert adapters.named("apple-podcasts") is podcasts and adapters.live("apple-podcasts") is podcasts
    assert isinstance(podcasts, adapters.Adapter) and isinstance(podcasts, adapters.LiveAdapter)
    assert adapters.find(_store(tmp_path)) is podcasts


def test_sniff_wants_the_episode_table_with_its_three_columns(tmp_path):
    assert podcasts.sniff(_store(tmp_path / "a", columns="bare"))
    assert not podcasts.sniff(tmp_path / "a")
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE ZMTEPISODE (Z_PK INTEGER, ZTITLE VARCHAR)")
    con.commit()
    con.close()
    assert not podcasts.sniff(other)
    (tmp_path / "garbage.sqlite").write_bytes(b"SQLite format 3\0" + b"\x02" * 1000)
    assert not podcasts.sniff(tmp_path / "garbage.sqlite")


# -- the mapping ----------------------------------------------------------------------------------


def test_every_played_episode_is_a_line_and_the_envelope_is_complete(tmp_path):
    counts: dict[str, int] = {}
    lines = list(podcasts.run(_store(tmp_path), timezone=TZ, counts=counts))
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "listen" and line["source"] == "apple-podcasts" and line["tier"] == 2
        assert line["end"] is None and line["tz"] == TZ
        assert line["payload"]["schema"] == "listen/v1" and line["payload"]["media"] == "episode"
    assert counts == {"skipped_never_played": 1, "skipped_no_title": 1}
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_completed_reads_the_playhead_against_the_duration_or_a_rewound_full_play(tmp_path):
    by = {line["payload"]["title"]: line["payload"] for line in _lines(_store(tmp_path))}
    assert by["Episode 12: the east berth"]["completed"] is False  # 1801.5 s of 2400
    assert by["Bowline"]["completed"] is False  # never started: playhead 0, no play counted
    assert by["Orphan"]["completed"] is False  # 30 s in, on its third play
    assert by["Reef knot"]["completed"] is True  # rewound to 0 with a play counted
    assert all("completed" in payload for payload in by.values())


def test_the_feeds_transcript_url_is_kept_under_extra_and_an_apple_identifier_is_not(tmp_path):
    by = {line["payload"]["title"]: line["payload"] for line in _lines(_store(tmp_path))}
    assert by["Reef knot"]["extra"] == {
        "play_count": 1,
        "transcript_url": "https://knots.example.org/reef.vtt",
    }
    assert "transcript_url" not in by["Episode 12: the east berth"]["extra"]
    assert "transcript" not in json.dumps(by["Episode 12: the east berth"]).lower()


def test_an_episode_maps_show_publisher_url_durations_published_and_play_count(tmp_path):
    by = {line["payload"]["title"]: line for line in _lines(_store(tmp_path))}
    line = by["Episode 12: the east berth"]
    assert line["at"] == "2026-03-04T09:00:00Z"
    assert line["payload"] == {
        "schema": "listen/v1",
        "raw_id": "apple-podcasts:EP-10@2026-03-04T09:00:00Z",
        "media": "episode",
        "title": "Episode 12: the east berth",
        "show": "Havnepodden",
        "publisher": "Havnekontoret",
        "url": "https://havn.example.org/podden/12",
        "duration_s": 2400.0,
        "played_s": 1801.5,
        "completed": False,
        "published": "2026-03-03T09:00:00Z",
        "service": "apple-podcasts",
        "extra": {"play_count": 1},
    }
    bowline = by["Bowline"]["payload"]
    assert bowline["show"] == "Knots Weekly" and "publisher" not in bowline and "played_s" not in bowline
    assert "url" not in bowline and "extra" not in bowline and bowline["duration_s"] == 600.0
    orphan = by["Orphan"]["payload"]  # its show is not in the store: the episode's own author stands
    assert (
        "show" not in orphan
        and orphan["publisher"] == "Ola"
        and orphan["url"] == "https://x.example.org/o.mp3"
    )
    assert "duration_s" not in orphan and orphan["extra"] == {"play_count": 2}


@pytest.mark.parametrize("columns", ["older", "bare"])
def test_a_store_with_other_columns_still_reads_what_it_has(tmp_path, columns):
    lines = _lines(_store(tmp_path, columns=columns))
    assert [line["payload"]["title"] for line in lines] == [
        "Orphan",
        "Bowline",
        "Episode 12: the east berth",
        "Reef knot",
    ]
    first, reef = lines[2]["payload"], lines[3]["payload"]
    if columns == "older":
        assert "show" not in first and first["publisher"] == "Havnekontoret" and "extra" not in first
        assert first["url"] == "https://havn.example.org/podden/12.mp3" and first["played_s"] == 1801.5
        assert first["completed"] is False
        assert reef["completed"] is False, "no play count to tell a rewound full play from an unplayed one"
        assert "extra" not in reef, "no transcript column: nothing under extra"
    else:
        assert set(first) == {"schema", "raw_id", "media", "title", "service"}, "no playhead: no completed"


def test_since_cuts_on_at_and_a_replay_is_a_new_line(tmp_path):
    store = _store(tmp_path)
    assert [line["payload"]["title"] for line in _lines(store, since="2026-03-01T00:00:00Z")] == [
        "Episode 12: the east berth",
        "Reef knot",
    ]
    lb = Logbook.init(tmp_path / "lb", TZ)
    assert lb.append_many(podcasts.run(store, timezone=TZ)) == LINES
    assert lb.append_many(podcasts.run(store, timezone=TZ)) == 0
    con = sqlite3.connect(store)
    con.execute(
        "UPDATE ZMTEPISODE SET ZLASTDATEPLAYED = ?, ZPLAYHEAD = 2400.0 WHERE ZUUID = 'EP-10'",
        (1772701200.0 - APPLE_EPOCH,),
    )
    con.commit()
    con.close()
    assert lb.append_many(podcasts.run(store, timezone=TZ)) == 1  # played again: a new listen (rule 1)
    assert lb.verify()[2] == []
    replay = [line for line in lb.lines() if line["payload"]["raw_id"].startswith("apple-podcasts:EP-10@")]
    assert [line["payload"]["completed"] for line in replay] == [False, True], "to the end this time"


def test_the_store_is_never_written(tmp_path):
    store = _store(tmp_path)
    before = store.read_bytes()
    list(podcasts.run(store, timezone=TZ))
    assert store.read_bytes() == before and not (tmp_path / "MTLibrary.sqlite-journal").exists()


# -- live: configure, pull, sync ------------------------------------------------------------------


def test_configure_defaults_to_the_macs_own_store_and_reads_the_override(monkeypatch, tmp_path):
    # Path.home() and expanduser() read HOME on POSIX and USERPROFILE on Windows; pin both
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert podcasts.configure({}).db == tmp_path.joinpath(*podcasts.DEFAULT_DB)
    assert podcasts.configure({podcasts.DB_ENV: "~/copy.sqlite"}).db == tmp_path / "copy.sqlite"
    assert podcasts.ENV == ("LOGBOOK_PODCASTS_DB",)


def test_the_file_import_and_the_live_pull_are_the_same_lines(tmp_path):
    store = _store(tmp_path, wal=True)
    config = podcasts.Config(db=store)
    assert list(podcasts.pull(config, timezone=TZ)) == _lines(store)
    assert podcasts.watermark(_lines(store)[-1]) == "2026-03-05T06:10:00Z"
    assert [
        line["payload"]["title"] for line in podcasts.pull(config, since="2026-03-01T00:00:00Z", timezone=TZ)
    ] == ["Episode 12: the east berth", "Reef knot"]


def test_pull_reports_progress_and_an_unreadable_store_raises_oserror(tmp_path):
    seen: list[tuple[int, float]] = []
    list(podcasts.pull(podcasts.Config(db=_store(tmp_path)), progress=lambda n, t: seen.append((n, t))))
    assert seen[-1][0] == LINES
    with pytest.raises(OSError):
        list(podcasts.pull(podcasts.Config(db=tmp_path / "missing.sqlite")))
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).close()
    with pytest.raises(OSError, match="not an Apple Podcasts library"):
        list(podcasts.pull(podcasts.Config(db=other)))


def test_sync_appends_the_listens_dedupes_a_prior_import_and_keeps_the_watermark(
    tmp_path, monkeypatch, capsys
):
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    store = _store(tmp_path / "store")
    monkeypatch.setenv(podcasts.DB_ENV, str(store))
    cli.main(["add", "apple-podcasts", str(store)])
    assert f"added {LINES} lines from apple-podcasts" in capsys.readouterr().out
    cli.main(["sync", "apple-podcasts"])
    out = capsys.readouterr().out
    assert f"apple-podcasts: 0 new lines of {LINES} seen" in out
    state = json.loads((lb.root / "state" / "apple-podcasts.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-03-05T06:10:00Z"
    assert lb.verify()[0] == LINES
