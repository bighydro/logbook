"""Instagram's "Export your information" archive (JSON) → message/v1, call/v1, photo/v1 and social/v1.

The fixture under tests/fixtures/instagram/export is synthetic, in the newer layout
(`your_instagram_activity/messages/...`, `connections/followers_and_following/...`); the older layout
and the zip are made from it here. Nobody in it exists: Kari Nordmann lives in Oslo and does not."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.contrib import adapters
from logbook.contrib.adapters import claude_export, instagram, whatsapp
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "instagram" / "export"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
OLA_THREAD = "1000000000000001"
GROUP_THREAD = "1000000000000002"
PER_THREAD = "1000000000000003"
ACTIVITY = "your_instagram_activity"


@pytest.fixture(autouse=True)
def hash_media(monkeypatch):
    monkeypatch.delenv(instagram.HASH_MEDIA_ENV, raising=False)


def _newer(tmp_path: Path) -> Path:
    """The fixture as Meta unpacks it: one folder named after the account and the day."""
    folder = tmp_path / "instagram-kari.n.example-2026-10-30-SYNTH"
    shutil.copytree(FIXTURE, folder)
    return folder


def _older(tmp_path: Path) -> Path:
    """The same export in the older layout: no `your_instagram_activity/`, followers at the top, and the
    media references without the prefix."""
    folder = tmp_path / "older"
    shutil.copytree(FIXTURE, folder)
    activity = folder / ACTIVITY
    for child in list(activity.iterdir()):
        shutil.move(str(child), str(folder / child.name))
    activity.rmdir()
    shutil.move(
        str(folder / "connections" / "followers_and_following"), str(folder / "followers_and_following")
    )
    (folder / "connections").rmdir()
    for file in folder.rglob("*.json"):
        text = file.read_text(encoding="utf-8").replace(f"{ACTIVITY}/", "")
        file.write_bytes(text.encode("utf-8"))
    return folder


def _zip(folder: Path, to: Path) -> Path:
    with zipfile.ZipFile(to, "w", zipfile.ZIP_DEFLATED) as z:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                z.write(file, file.relative_to(folder.parent).as_posix())
    return to


def _lines(path: Path, **kw) -> list[dict]:
    return list(instagram.run(path, **kw))


def _of(lines: list[dict], kind: str) -> list[dict]:
    return [line for line in lines if line["kind"] == kind]


def _messages(lines: list[dict], thread: str) -> list[dict]:
    return [m for m in _of(lines, "message") if m["payload"]["chat"]["id"] == thread]


# -- registry and sniff -----------------------------------------------------------------------------


def test_registry_lists_instagram_and_finds_the_folder_and_the_zip(tmp_path):
    assert "instagram" in [a.NAME for a in adapters.all_adapters()]
    folder = _newer(tmp_path)
    assert adapters.find(folder).NAME == "instagram"
    assert adapters.find(_zip(folder, tmp_path / "export.zip")).NAME == "instagram"
    assert adapters.named("instagram") is instagram
    assert adapters.named("instagram-export") is instagram


def test_sniff_knows_both_layouts_and_says_no_to_other_things(tmp_path):
    assert instagram.sniff(_newer(tmp_path)) is True
    assert instagram.sniff(_older(tmp_path)) is True
    assert instagram.sniff(tmp_path / "missing") is False
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert instagram.sniff(tmp_path / "notes.txt") is False
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("conversations.json", "[]")
    assert instagram.sniff(other) is False
    facebook = tmp_path / "facebook"
    (facebook / "your_facebook_activity" / "messages" / "inbox" / "x_1").mkdir(parents=True)
    assert instagram.sniff(facebook) is False


def test_other_adapters_reject_the_export(tmp_path):
    folder = _newer(tmp_path)
    archive = _zip(folder, tmp_path / "export.zip")
    assert claude_export.sniff(archive) is False and claude_export.sniff(folder) is False
    assert whatsapp.sniff(archive) is False


def test_sniff_and_run_never_touch_the_source(tmp_path):
    folder = _newer(tmp_path)
    archive = _zip(folder, tmp_path / "export.zip")
    before = {f: f.read_bytes() for f in folder.rglob("*") if f.is_file()}
    zipped = archive.read_bytes()
    _lines(folder)
    _lines(archive)
    assert {f: f.read_bytes() for f in folder.rglob("*") if f.is_file()} == before
    assert archive.read_bytes() == zipped


# -- the encoding Meta gets wrong ----------------------------------------------------------------------


def _as_meta_writes(text: str) -> object:
    """The JSON string as the export spells it, escapes and all, read as `json` reads it."""
    return json.loads(f'"{text}"')


def test_fix_reads_the_latin1_escapes_back_as_utf8():
    assert instagram.fix(_as_meta_writes(r"B\u00c3\u00a5ten")) == "Båten"
    assert instagram.fix(_as_meta_writes(r"\u00e2\u009b\u00b5")) == "\u26f5"
    assert instagram.fix(_as_meta_writes(r"\u00f0\u009f\u0098\u008a")) == "\U0001f60a"
    assert instagram.fix(_as_meta_writes(r"bl\u00c3\u00a5b\u00c3\u00a6r")) == "blåbær"
    assert instagram.fix("plain ascii") == "plain ascii"
    assert instagram.fix("Båten") == "Båten"  # already right: not latin-1 bytes of UTF-8, left alone
    assert instagram.fix("ok \u26f5") == "ok \u26f5"  # outside latin-1 altogether
    assert instagram.fix({"a": [_as_meta_writes(r"\u00c3\u00b8"), 1, None]}) == {"a": ["ø", 1, None]}


def test_every_string_of_every_line_is_fixed(tmp_path):
    lines = _lines(_newer(tmp_path))
    first = _messages(lines, OLA_THREAD)[0]["payload"]
    assert first["text"] == "Båten er klar ⛵ — blåbær og kaffe"
    assert first["extra"]["reactions"] == [{"reaction": "❤", "actor": "Kari Nordmann"}]
    group = _messages(lines, GROUP_THREAD)[0]["payload"]
    assert group["chat"]["name"] == "Seilgjengen ⚓" and group["text"] == "Første melding i gruppa"
    comment = next(s for s in _of(lines, "social") if s["payload"]["action"] == "comment")
    assert comment["payload"]["text"] == "Så fint! 😍"
    post = _of(lines, "photo")[0]
    assert post["payload"]["extra"]["post"]["caption"] == "Første tur på fjorden i år ⛵"
    for line in lines:
        assert "Ã" not in json.dumps(line, ensure_ascii=False)


# -- direct messages -----------------------------------------------------------------------------------


def test_one_message_line_per_message_with_the_source_time_in_utc(tmp_path):
    lines = _lines(_newer(tmp_path))
    ola = _messages(lines, OLA_THREAD)
    assert [m["at"] for m in ola] == [
        "2026-05-16T10:00:00Z",
        "2026-05-16T10:01:00Z",
        "2026-05-16T10:02:00Z",
        "2026-05-16T10:03:00Z",
    ]
    for m in _of(lines, "message"):
        assert set(m) == ENVELOPE
        assert m["source"] == "instagram" and m["tier"] == 2 and m["end"] is None and m["tz"] is None
        assert m["payload"]["schema"] == "message/v1"
        assert m["payload"]["raw_id"].startswith(m["payload"]["chat"]["id"] + ":")


def test_tier_is_the_tier_of_whatsapp_messages(tmp_path):
    assert {m["tier"] for m in _of(_lines(_newer(tmp_path)), "message")} == {whatsapp.TIER}


def test_direct_chat_owner_sender_and_name_hint(tmp_path):
    ola = _messages(_lines(_newer(tmp_path)), OLA_THREAD)
    first, mine = ola[0]["payload"], ola[1]["payload"]
    assert first["chat"] == {"id": OLA_THREAD, "type": "direct", "name": "Ola Nordmann"}
    assert first["from_me"] is False
    assert first["sender"] == {
        "kind": "provider_id",
        "value": "instagram:Ola Nordmann",
        "name": "Ola Nordmann",
    }
    assert mine["from_me"] is True and "sender" not in mine
    assert mine["text"] == "Takk! Ser deg på brygga 😊"
    assert first["extra"]["box"] == "inbox" and first["extra"]["thread"] == "olanordmann_1000000000000001"


def test_group_thread_is_one_group_across_its_files(tmp_path):
    group = _messages(_lines(_newer(tmp_path)), GROUP_THREAD)
    assert [m["payload"].get("text") for m in group] == [
        "Første melding i gruppa",
        "Hvem tar med fendere?",
        "Jeg tar med fendere",
        None,
    ]
    assert {m["payload"]["chat"]["type"] for m in group} == {"group"}
    assert group[1]["payload"]["sender"]["name"] == "Ingrid Berg"
    assert group[2]["payload"]["from_me"] is True
    assert group[0]["payload"]["extra"]["participants"] == ["Ingrid Berg", "Kari Nordmann", "Ola Nordmann"]


def test_message_requests_are_read_and_marked(tmp_path):
    per = _messages(_lines(_newer(tmp_path)), PER_THREAD)
    assert len(per) == 1
    assert per[0]["payload"]["extra"]["box"] == "message_requests"
    assert per[0]["payload"]["text"] == "Hei, vi møttes på Aker brygge"


def test_archived_threads_are_read(tmp_path):
    folder = _newer(tmp_path)
    messages = folder / ACTIVITY / "messages"
    shutil.move(str(messages / "message_requests"), str(messages / "archived_threads"))
    per = _messages(_lines(folder), PER_THREAD)
    assert len(per) == 1 and per[0]["payload"]["extra"]["box"] == "archived_threads"


def test_a_shared_post_keeps_its_link_and_its_owners_handle(tmp_path):
    shared = _messages(_lines(_newer(tmp_path)), OLA_THREAD)[3]["payload"]
    assert shared["media_kind"] == "link" and shared["text"] == "Se denne"
    assert shared["extra"]["share"] == {
        "link": "https://www.instagram.com/reel/SYNTHETIC1/",
        "text": "Fin tur på fjorden",
        "owner": {"kind": "handle", "value": "instagram:sailing.example"},
    }


def test_media_is_referenced_by_its_path_in_the_archive_hashed_and_never_copied(tmp_path):
    folder = _newer(tmp_path)
    photo = _messages(_lines(folder), OLA_THREAD)[2]["payload"]
    path = f"{ACTIVITY}/messages/inbox/olanordmann_1000000000000001/photos/2000000000000001.jpg"
    data = (folder / path).read_bytes()
    assert photo["media_kind"] == "image" and "media" not in photo
    assert photo["extra"]["media"] == [
        {"path": path, "kind": "image", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    ]
    missing = _messages(_lines(folder), GROUP_THREAD)[3]["payload"]
    assert missing["media_kind"] == "video" and missing["extra"]["media_missing"] is True
    assert missing["extra"]["media"][0]["path"].endswith("3000000000000001.mp4")
    assert "sha256" not in missing["extra"]["media"][0]


def test_hashing_media_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv(instagram.HASH_MEDIA_ENV, "0")
    photo = _messages(_lines(_newer(tmp_path)), OLA_THREAD)[2]["payload"]
    assert set(photo["extra"]["media"][0]) == {"path", "kind"}


def test_a_media_path_never_leaves_the_archive(tmp_path):
    folder = _newer(tmp_path)
    file = folder / ACTIVITY / "messages" / "inbox" / "olanordmann_1000000000000001" / "message_1.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["messages"][5]["photos"][0]["uri"] = "../../outside.jpg"
    file.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "outside.jpg").write_bytes(b"not the archive's")
    photo = _messages(_lines(folder), OLA_THREAD)[2]["payload"]
    assert photo["extra"]["media_missing"] is True and "sha256" not in photo["extra"]["media"][0]


def test_calls_are_call_lines(tmp_path):
    calls = _of(_lines(_newer(tmp_path)), "call")
    assert len(calls) == 2
    made, missed = (c["payload"] for c in calls)
    assert calls[0]["at"] == "2026-05-16T10:04:00Z" and calls[0]["end"] == "2026-05-16T10:06:05Z"
    assert calls[0]["tier"] == whatsapp.TIER and calls[0]["source"] == "instagram"
    assert made["schema"] == "call/v1" and made["service"] == "instagram"
    assert made["direction"] == "outgoing" and made["answered"] is True and made["duration_s"] == 125
    assert made["counterparty"] == {"kind": "provider_id", "value": "instagram:Ola Nordmann"}
    assert missed["direction"] == "incoming" and missed["answered"] is False and missed["duration_s"] == 0
    assert calls[1]["end"] is None
    assert made["extra"]["chat"] == {"id": OLA_THREAD, "type": "direct", "name": "Ola Nordmann"}


def test_what_is_not_a_message_is_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    _lines(_newer(tmp_path), counts=counts)
    assert counts["skipped_no_body"] == 1
    assert counts["skipped_bad_date"] == 1
    assert counts["media_hashed"] == 4  # the DM photo, the post's two images, the story
    assert counts["media_missing"] == 1


def test_since_leaves_out_what_came_before(tmp_path):
    lines = _lines(_newer(tmp_path), since="2026-05-16T10:02:30Z")
    assert lines and all(line["at"] >= "2026-05-16T10:02:30Z" for line in lines)


# -- the owner -----------------------------------------------------------------------------------------


def test_without_the_profile_the_owner_is_the_one_in_every_thread(tmp_path):
    folder = _newer(tmp_path)
    shutil.rmtree(folder / "personal_information")
    counts: dict[str, int] = {}
    ola = _messages(_lines(folder, counts=counts), OLA_THREAD)
    assert ola[1]["payload"]["from_me"] is True and counts["owner_in_every_chat"] == 1


def test_owner_aliases_name_the_owner_when_the_export_cannot(tmp_path):
    folder = _newer(tmp_path)
    shutil.rmtree(folder / "personal_information")
    shutil.rmtree(folder / ACTIVITY / "messages" / "inbox")
    per = _messages(_lines(folder, owner_aliases={"names": ["Kari Nordmann"]}), PER_THREAD)
    assert per[0]["payload"]["from_me"] is False


def test_no_owner_at_all_is_one_sentence_and_nothing_read(tmp_path):
    folder = _newer(tmp_path)
    shutil.rmtree(folder / "personal_information")
    shutil.rmtree(folder / ACTIVITY / "messages" / "inbox")
    with pytest.raises(adapters.Unreadable, match=r"policy/owner\.json"):
        _lines(folder)


# -- connections, own content, interactions --------------------------------------------------------------


def test_connections_are_social_lines_by_handle(tmp_path):
    social = [s for s in _of(_lines(_newer(tmp_path)), "social")]
    by_action: dict[str, list[str]] = {}
    for line in social:
        assert line["tier"] == 2 and line["source"] == "instagram" and line["end"] is None
        assert line["payload"]["schema"] == "social/v1" and line["payload"]["network"] == "instagram"
        ref = line["payload"].get("counterpart")
        by_action.setdefault(line["payload"]["action"], []).append(ref["value"] if ref else None)
    assert by_action["followed_by"] == ["instagram:ola.example", "instagram:ingrid.example"]
    assert by_action["follow"] == ["instagram:ola.example", "instagram:sailing.example"]
    assert by_action["close_friend"] == ["instagram:ola.example"]
    assert by_action["block"] == ["instagram:spam.example"]
    assert by_action["restrict"] == ["instagram:noisy.example"]
    assert by_action["follow_request_sent"] == ["instagram:per.example"]
    assert by_action["unfollow"] == ["instagram:old.example"]
    follower = next(s for s in social if s["payload"]["action"] == "followed_by")
    assert follower["at"] == "2026-05-06T00:00:00Z"
    assert follower["payload"]["url"] == "https://www.instagram.com/ola.example"
    assert follower["payload"]["counterpart"] == {"kind": "handle", "value": "instagram:ola.example"}


def test_interactions_are_social_lines(tmp_path):
    social = {s["payload"]["action"]: s for s in _of(_lines(_newer(tmp_path)), "social")}
    like = social["like"]["payload"]
    assert like["url"] == "https://www.instagram.com/p/SYNTHETIC2/"
    assert like["counterpart"] == {"kind": "handle", "value": "instagram:sailing.example"}
    comment = social["comment"]["payload"]
    assert comment["counterpart"]["value"] == "instagram:ola.example" and comment["text"] == "Så fint! 😍"
    assert social["story_like"]["payload"]["counterpart"]["value"] == "instagram:ingrid.example"
    search = social["search"]["payload"]
    assert search["counterpart"]["value"] == "instagram:per.example"
    assert search["url"] == "https://www.instagram.com/per.example"


def test_own_posts_and_stories_are_photo_lines_with_caption_and_place(tmp_path):
    folder = _newer(tmp_path)
    photos = _of(_lines(folder), "photo")
    assert [p["payload"]["file_name"] for p in photos] == [
        "4000000000000001.jpg",
        "4000000000000002.jpg",
        "5000000000000001.mp4",
    ]
    first, second, story = (p["payload"] for p in photos)
    assert photos[0]["at"] == "2026-05-16T10:30:00Z" and photos[0]["tier"] == 2
    assert first["schema"] == "photo/v1" and first["library"] == "instagram" and first["media"] == "image"
    assert first["lat"] == 59.9075 and first["lon"] == 10.724
    data = (folder / "media" / "posts" / "202605" / "4000000000000001.jpg").read_bytes()
    assert first["content_hash"] == hashlib.sha256(data).hexdigest()
    assert first["extra"]["post"] == {
        "kind": "post",
        "id": "post:4000000000000001.jpg",
        "caption": "Første tur på fjorden i år ⛵",
        "items": 2,
    }
    assert second["extra"]["post"]["id"] == "post:4000000000000001.jpg" and "lat" not in second
    assert story["media"] == "video" and story["extra"]["post"]["kind"] == "story"
    assert "lat" not in story  # 0, 0 is no place
    assert first["extra"]["path"] == "media/posts/202605/4000000000000001.jpg"


def test_ads_logins_and_devices_are_never_read(tmp_path):
    text = json.dumps(_lines(_newer(tmp_path)))
    assert "advertiser.example" not in text and "192.0.2.1" not in text
    assert "kari.nordmann@example.org" not in text  # the profile gives the owner's name, nothing else


# -- layouts, zip, HTML -----------------------------------------------------------------------------------


def _keys(lines: list[dict]) -> list[tuple[str, str, str]]:
    return sorted((line["kind"], line["payload"]["raw_id"], line["at"]) for line in lines)


def test_both_layouts_and_the_zip_give_the_same_lines(tmp_path):
    newer = _lines(_newer(tmp_path))
    older = _lines(_older(tmp_path))
    zipped = _lines(_zip(_newer(tmp_path / "z"), tmp_path / "export.zip"))
    assert len(newer) == 27
    assert _keys(older) == _keys(newer) == _keys(zipped)
    strip = [
        json.dumps({**line, "payload": {**line["payload"], "extra": None}}, sort_keys=True) for line in newer
    ]
    assert sorted(strip) == sorted(
        json.dumps({**line, "payload": {**line["payload"], "extra": None}}, sort_keys=True) for line in zipped
    )


def test_an_html_export_is_refused_with_how_to_ask_for_json(tmp_path):
    folder = tmp_path / "instagram-html"
    thread = folder / ACTIVITY / "messages" / "inbox" / "olanordmann_1"
    thread.mkdir(parents=True)
    (thread / "message_1.html").write_text("<html></html>", encoding="utf-8")
    followers = folder / "connections" / "followers_and_following"
    followers.mkdir(parents=True)
    (followers / "followers_1.html").write_text("<html></html>", encoding="utf-8")
    assert instagram.sniff(folder) is True  # so `add` reaches the sentence below
    for given in (folder, _zip(folder, tmp_path / "html.zip")):
        with pytest.raises(adapters.Unreadable, match="HTML") as e:
            _lines(given)
        assert "JSON" in str(e.value) and "Export your information" in str(e.value)


def test_a_damaged_zip_is_one_sentence(tmp_path):
    archive = _zip(_newer(tmp_path), tmp_path / "export.zip")
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])  # the central directory gone, as a download cut short
    with pytest.raises(adapters.Unreadable):
        _lines(archive)


def test_a_thread_file_that_does_not_parse_is_skipped_and_counted(tmp_path):
    folder = _newer(tmp_path)
    (folder / ACTIVITY / "messages" / "inbox" / "olanordmann_1000000000000001" / "message_1.json").write_text(
        "{not json", encoding="utf-8"
    )
    counts: dict[str, int] = {}
    lines = _lines(folder, counts=counts)
    assert counts["skipped_unreadable_file"] == 1
    assert _messages(lines, OLA_THREAD) == [] and _messages(lines, GROUP_THREAD)


# -- through the log: idempotent, a newer export adds only what is new ----------------------------------


def test_lines_append_and_importing_again_appends_nothing(tmp_path):
    folder = _newer(tmp_path)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(instagram.run(folder)) == 27
    assert lb.append_many(instagram.run(folder)) == 0
    assert lb.append_many(instagram.run(_older(tmp_path))) == 0
    assert lb.append_many(instagram.run(_zip(folder, tmp_path / "export.zip"))) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 27
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


def test_a_newer_export_adds_only_what_is_new(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(instagram.run(_older(tmp_path))) == 27
    later = _newer(tmp_path)
    file = later / ACTIVITY / "messages" / "inbox" / "olanordmann_1000000000000001" / "message_1.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data["messages"].insert(
        0, {"sender_name": "Ola Nordmann", "timestamp_ms": 1_780_000_000_000, "content": "Ny"}
    )
    file.write_text(json.dumps(data), encoding="utf-8")
    followers = later / "connections" / "followers_and_following" / "followers_1.json"
    rows = json.loads(followers.read_text(encoding="utf-8"))
    rows.append(
        {
            "title": "",
            "media_list_data": [],
            "string_list_data": [
                {
                    "href": "https://www.instagram.com/new.example",
                    "value": "new.example",
                    "timestamp": 1_780_000_000,
                }
            ],
        }
    )
    followers.write_text(json.dumps(rows), encoding="utf-8")
    assert lb.append_many(instagram.run(later)) == 2


def _cli(tmp_path: Path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}
    env.pop(instagram.HASH_MEDIA_ENV, None)

    def run(*a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_instagram_reports_and_a_second_run_adds_nothing(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    archive = _zip(_newer(tmp_path), tmp_path / "instagram.zip")
    out = run("add", "instagram", str(archive)).stdout
    assert "added 27 lines from instagram" in out
    assert "skipped 1 with an unusable date, 1 without a body" in out
    assert "4 with media hashed, 1 with media missing" in out
    assert "added 0 lines from instagram" in run("add", "instagram", str(archive)).stdout
    assert "valid — 27 lines" in run("verify").stdout


def test_cli_add_an_html_export_says_so_and_exits_2(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    folder = tmp_path / "html"
    (folder / "connections" / "followers_and_following").mkdir(parents=True)
    (folder / "connections" / "followers_and_following" / "followers_1.html").write_text(
        "<html/>", encoding="utf-8"
    )
    with pytest.raises(subprocess.CalledProcessError) as e:
        run("add", "instagram", str(folder))
    assert e.value.returncode == 2 and "JSON" in e.value.stderr


def test_doctor_sources_lists_instagram(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    rows = [row.split() for row in run("doctor", "sources").stdout.splitlines()]
    assert ["instagram", "file", "enabled"] in rows


# -- people: proposals by name, never a merge ------------------------------------------------------------


def test_people_review_proposes_an_instagram_sender_against_a_whatsapp_person_by_name(tmp_path):
    from logbook.contrib import people_review

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    ola = "019cadd3-6bc0-7dcd-9133-043f5aabf2a9"
    contact = (
        {
            "at": "2026-05-01T09:00:00Z", "end": None, "tz": "Europe/Oslo", "source": "ios-contacts",
            "kind": "resolution", "tier": 2,
            "payload": {"schema": "resolution/v1", "ref": {"kind": "phone", "value": "+447700900101"},
                        "entity": {"type": "person", "id": ola, "registry": "logbook"},
                        "label": "Ola Nordmann", "method": "exact"},
        }
    )  # fmt: skip
    message = (
        {
            "at": "2026-05-02T09:00:00Z", "end": None, "tz": "Europe/Oslo", "source": "whatsapp",
            "kind": "message", "tier": 2,
            "payload": {"schema": "message/v1", "raw_id": "447700900101@s.whatsapp.net:A1",
                        "chat": {"id": "447700900101@s.whatsapp.net", "type": "direct"}, "from_me": False,
                        "sender": {"kind": "phone", "value": "+447700900101"}, "text": "hei"},
        }
    )  # fmt: skip
    assert lb.append_many([contact, message]) == 2
    before = sum(1 for _ in lb.lines())
    lb.append_many(instagram.run(_newer(tmp_path)))
    report = people_review.read(lb)
    ref = ("provider_id", "instagram:Ola Nordmann")
    proposed = [
        p
        for p in report.proposals
        if p.canonical is not None and p.canonical.entity == ola and ref in p.observed.identifiers
    ]
    assert proposed and "same name Ola Nordmann" in proposed[0].evidence
    resolutions = [line for line in lb.lines() if line["kind"] == "resolution"]
    assert len(resolutions) == 1  # nothing merged on its own
    assert sum(1 for _ in lb.lines()) == before + 27
