"""`logbook lab hold census files|senders|drive` (Hold v0, docs/hold.md, RFC 0042): what each census
counts, on synthetic folders and synthetic lines of the Oslo persona, who does not exist. The safety
of the walk and of the names is `tests/test_lab_hold_safety.py`."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core.store import Logbook
from logbook.labs import hold

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
OLD = datetime(2021, 3, 1, 12, 0, tzinfo=UTC).timestamp()  # more than two years before NOW
RECENT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC).timestamp()
OWNER = "ines.nordmann@example.org"
OLA = "ola.nordmann@example.org"
KARI = "kari.nordmann@example.org"
LETTER = "news@boatclub.example.org"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, "Europe/Oslo")


def _file(path: Path, data: bytes, mtime: float = RECENT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Ines's Documents: photos (two the same), a tax folder untouched since 2021, an empty file."""
    top = tmp_path / "Documents"
    _file(top / "Photos" / "fjord.JPG", b"\xff\xd8" + b"a" * 3000)
    _file(top / "Photos" / "fjord copy.jpg", b"\xff\xd8" + b"a" * 3000)
    _file(top / "Photos" / "berth.jpg", b"\xff\xd8" + b"b" * 3000)  # the same size, other bytes
    _file(top / "Tax" / "2020" / "return.pdf", b"%PDF" + b"t" * 5000, OLD)
    _file(top / "Tax" / "2020" / "receipts.csv", b"a,b\n" * 10, OLD)
    _file(top / "Tax" / "notes.txt", b"kept", OLD)
    _file(top / "empty-one.txt", b"")
    _file(top / "empty-two.txt", b"")
    _file(top / "README", b"no extension here", RECENT)
    return top


def _census(lb: Logbook, *args: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()
    cli.main(["lab", "hold", "census", *args, "--json"])
    return dict(json.loads(capsys.readouterr().out))


def _report(lb: Logbook, census: str) -> dict[str, Any]:
    return dict(json.loads((lb.root / "state" / "hold" / f"{census}.json").read_text(encoding="utf-8")))


# -- files ---------------------------------------------------------------------------------------------------


def test_files_counts_by_type_extension_and_year(lb: Logbook, folder: Path) -> None:
    report = hold.census_files(lb, [folder], NOW)
    assert report["totals"] == {"files": 9, "bytes": 3002 * 3 + 5004 + 40 + 4 + 17, "folders": 4}
    types = {row["type"]: (row["files"], row["bytes"]) for row in report["by_type"]}
    assert types["image"] == (3, 9006)
    assert types["document"] == (4, 5004 + 4)  # the pdf, notes.txt and the two empty .txt
    assert types["spreadsheet"] == (1, 40)
    assert types["none"] == (1, 17)
    extensions = {row["extension"]: row["files"] for row in report["by_extension"]}
    assert extensions[".jpg"] == 3, "the extension is lower-cased: .JPG is .jpg"
    assert extensions["(none)"] == 1
    years = {row["year"]: row["files"] for row in report["by_year"]}
    assert years == {2021: 3, 2026: 6}
    assert report["tier"] == hold.FILES_TIER == 3
    assert report["changed"] == {"moved": 0, "renamed": 0, "deleted": 0, "written": 0}


def test_files_finds_duplicates_by_digest_never_by_size_and_never_empty_files(
    lb: Logbook, folder: Path
) -> None:
    report = hold.census_files(lb, [folder], NOW)
    dups = report["duplicates"]
    assert dups["sets"] == 1 and dups["files"] == 2 and dups["spare_bytes"] == 3002
    (found,) = dups["list"]
    assert [f["path"] for f in found["files"]] == ["Photos/fjord copy.jpg", "Photos/fjord.JPG"]
    assert len(found["sha256"]) == 64


def test_a_hard_link_is_one_file_not_a_duplicate(lb: Logbook, folder: Path) -> None:
    try:
        os.link(folder / "Photos" / "berth.jpg", folder / "Photos" / "berth-link.jpg")
    except OSError:
        pytest.skip("this filesystem makes no hard links")
    report = hold.census_files(lb, [folder], NOW)
    assert report["duplicates"]["sets"] == 1, "the hard link is not a second copy"
    assert report["skipped"]["hard_links"] == 1
    assert report["totals"]["files"] == 9, "nor a second file"


def test_files_lists_the_largest_first_and_at_most_largest(
    lb: Logbook, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = hold.census_files(lb, [folder], NOW)["largest"]
    assert [row["bytes"] for row in whole] == [5004, 3002, 3002, 3002, 40, 17, 4, 0, 0]
    monkeypatch.setattr(hold, "LARGEST", 1)
    report = hold.census_files(lb, [folder], NOW)
    assert [(row["path"], row["bytes"]) for row in report["largest"]] == [("Tax/2020/return.pdf", 5004)]
    assert report["largest"][0]["modified"] == "2021-03-01"


def test_files_lists_the_highest_folder_untouched_for_two_years_only(lb: Logbook, folder: Path) -> None:
    report = hold.census_files(lb, [folder], NOW)
    assert report["untouched"] == [
        {"root": 1, "path": "Tax", "files": 3, "bytes": 5048, "newest": "2021-03-01"}
    ], "Tax/2020 is inside Tax, so only Tax is listed"


def test_a_root_untouched_as_a_whole_is_listed_as_itself(lb: Logbook, folder: Path) -> None:
    report = hold.census_files(lb, [folder / "Tax"], NOW)
    assert [row["path"] for row in report["untouched"]] == ["."]


def test_system_and_claude_folders_are_skipped_and_counted(lb: Logbook, folder: Path) -> None:
    _file(folder / ".git" / "objects" / "ab", b"x")
    _file(folder / ".Claude" / "projects" / "session.jsonl", b"{}")  # case folded
    _file(folder / "Library" / "Caches" / "c", b"x")  # directly inside a given folder: the system's
    _file(folder / "Books" / "Library" / "a-novel.epub", b"novel")  # further down: the owner's
    _file(folder / "Photos" / ".DS_Store", b"x")
    report = hold.census_files(lb, [folder], NOW)
    assert report["skipped"]["system_folders"] == 3
    assert report["skipped"]["system_files"] == 1
    assert report["totals"]["files"] == 10, "the novel is counted"


def test_two_folders_one_inside_the_other_are_counted_once(lb: Logbook, folder: Path) -> None:
    report = hold.census_files(lb, [folder / "Photos", folder, folder], NOW)
    assert [Path(root["path"]) for root in report["roots"]] == [Path(os.path.realpath(folder))]
    assert report["totals"]["files"] == 9


def test_the_report_holds_the_names_and_the_summary_none(
    lb: Logbook, folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = _census(lb, "files", str(folder), capsys=capsys)
    assert summary["totals"]["files"] == 9 and summary["duplicates"]["sets"] == 1
    assert "fjord" not in json.dumps(summary) and "Documents" not in json.dumps(summary)
    markdown = (lb.root / "state" / "hold" / "files.md").read_text(encoding="utf-8")
    assert "fjord copy.jpg" in markdown and "## Duplicates" in markdown
    assert _report(lb, "files")["census"] == "files"
    cli.main(["lab", "hold", "census", "files", str(folder)])
    text = capsys.readouterr().out
    assert text.startswith("hold census files: 9 files") and "fjord" not in text
    assert "nothing was moved, renamed or deleted" in text


def test_a_name_with_a_bar_or_a_line_break_keeps_its_row_in_the_markdown(lb: Logbook, tmp_path: Path) -> None:
    top = tmp_path / "Odd"
    # Windows refuses a `|` in a name; a `[` breaks a row's meaning there as much
    name, escaped = ("a[b].txt", "a\\[b\\].txt") if os.name == "nt" else ("a|b.txt", "a\\|b.txt")
    _file(top / name, b"same")
    _file(top / "c.txt", b"same")
    report = hold.census_files(lb, [top], NOW)
    rows = [line for line in hold.markdown(report).splitlines() if escaped in line]
    assert rows, "the bar is escaped, the row kept"


@pytest.mark.parametrize("given", ["missing", "a-file.txt"])
def test_a_path_that_is_no_folder_exits_2(
    lb: Logbook, tmp_path: Path, given: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _file(tmp_path / "a-file.txt", b"x")
    with pytest.raises(SystemExit) as e:
        cli.main(["lab", "hold", "census", "files", str(tmp_path / given)])
    assert e.value.code == 2
    assert "is not a folder" in capsys.readouterr().err
    assert not (lb.root / "state" / "hold" / "files.json").exists()


def test_a_census_rerun_replaces_its_report(lb: Logbook, folder: Path) -> None:
    hold.run(lb, "files", [folder])
    _file(folder / "new.txt", b"new")
    hold.run(lb, "files", [folder])
    assert _report(lb, "files")["totals"]["files"] == 10
    assert sorted(p.name for p in (lb.root / "state" / "hold").iterdir()) == ["files.json", "files.md"]


# -- senders -------------------------------------------------------------------------------------------------


def _mail(
    lb: Logbook,
    at: str,
    sender: str,
    to: str,
    thread: str,
    direction: str = "received",
    tier: int = 2,
    extra: dict[str, Any] | None = None,
    name: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "schema": "mail/v1",
        "raw_id": f"{OWNER}:{at}.{sender}@mail.example.org",
        "message_id": f"{at}.{sender}@mail.example.org",
        "thread": thread,
        "from": {"email": sender, **({"name": name} if name else {})},
        "to": [{"email": to}],
        "subject": "Mooring for the weekend",
        "direction": direction,
        "size": 1200,
        "account": OWNER,
    }
    if extra:
        payload["extra"] = extra
    return str(lb.append(at, "mail", "mail", tier, payload)["id"])


@pytest.fixture
def mailbox(lb: Logbook) -> Logbook:
    """Ola wrote three times and was answered; Kari once, in a thread the owner answered from another
    address's reply; the boat club's newsletter twice, never answered; a tier-3 mail from the clinic."""
    _mail(lb, "2026-03-02T10:15:00Z", OLA, OWNER, "t-ola", name="Ola Nordmann")
    _mail(lb, "2026-03-04T10:15:00Z", OLA, OWNER, "t-ola", name="Ola N.")
    _mail(lb, "2026-05-04T10:15:00Z", OLA, OWNER, "t-ola-2", name="Ola Nordmann")
    _mail(lb, "2026-03-05T08:00:00Z", OWNER, OLA, "t-ola", direction="sent")
    _mail(lb, "2026-04-01T09:00:00Z", KARI.upper(), OWNER, "t-kari", name="Kari Nordmann")
    _mail(lb, "2026-04-01T10:00:00Z", OWNER, "crew@example.org", "t-kari", direction="sent")
    _mail(
        lb,
        "2026-02-01T07:00:00Z",
        LETTER,
        OWNER,
        "t-n1",
        extra={"list_unsubscribe": "<mailto:u@example.org>"},
    )
    _mail(lb, "2026-03-01T07:00:00Z", LETTER, OWNER, "t-n2")
    _mail(lb, "2026-06-01T07:00:00Z", "clinic@example.org", OWNER, "t-c", tier=3)
    return lb


def test_senders_by_count_last_seen_and_answered(mailbox: Logbook) -> None:
    report = hold.census_senders(mailbox, now=NOW)
    rows = {row["email"]: row for row in report["senders"]}
    assert [row["email"] for row in report["senders"]] == [OLA, LETTER, KARI]
    ola = rows[OLA]
    assert (ola["messages"], ola["threads"], ola["threads_answered"]) == (3, 2, 1)
    assert ola["name"] == "Ola Nordmann" and ola["answered"] and ola["written_to"]
    assert (ola["first_seen"], ola["last_seen"]) == ("2026-03-02T10:15:00Z", "2026-05-04T10:15:00Z")
    assert ola["last_written"] == "2026-03-05T08:00:00Z"
    kari = rows[KARI]
    assert kari["answered"] and not kari["written_to"], "answered in her thread, to someone else; case folded"
    assert not rows[LETTER]["answered"]
    assert report["totals"] == {"lines": 8, "received": 6, "sent": 2, "senders": 3, "never_answered": 1}


def test_senders_newsletters_by_the_header_when_a_line_holds_it(mailbox: Logbook) -> None:
    report = hold.census_senders(mailbox, now=NOW)
    rows = {row["email"]: row for row in report["senders"]}
    assert rows[LETTER]["newsletter"] is True and rows[OLA]["newsletter"] is None
    assert report["newsletters"] == {"held": True, "lines_with_header": 1, "senders": 1, "note": None}


def test_without_the_header_newsletters_are_unknown_not_none(lb: Logbook) -> None:
    _mail(lb, "2026-03-02T10:15:00Z", OLA, OWNER, "t-ola")
    report = hold.census_senders(lb, now=NOW)
    assert report["newsletters"]["held"] is False
    assert "List-Unsubscribe" in report["newsletters"]["note"]
    assert "newsletters are unknown" in hold.markdown(report)


def test_senders_leave_tier_3_out_unless_asked_and_take_the_highest_tier_read(mailbox: Logbook) -> None:
    default = hold.census_senders(mailbox, now=NOW)
    assert default["tier"] == 2 and default["max_tier"] == 2
    assert default["left_out"] == {"above_tier": 1}
    assert "clinic@example.org" not in json.dumps(default)
    three = hold.census_senders(mailbox, max_tier=3, now=NOW)
    assert three["tier"] == 3 and "clinic@example.org" in {row["email"] for row in three["senders"]}
    one = hold.census_senders(mailbox, max_tier=1, now=NOW)
    assert one["tier"] is None and one["senders"] == [] and one["left_out"] == {"above_tier": 9}


def test_a_retracted_mail_is_not_counted(mailbox: Logbook) -> None:
    seq = mailbox.append(
        "2026-07-01T07:00:00Z", "mail", "mail", 2,
        {"schema": "mail/v1", "raw_id": "x", "thread": "t-x", "from": {"email": "wrong@example.org"},
         "direction": "received", "size": 10},
    )["seq"]  # fmt: skip
    mailbox.retract(int(seq), "imported by mistake")
    assert "wrong@example.org" not in {
        row["email"] for row in hold.census_senders(mailbox, now=NOW)["senders"]
    }


def test_senders_summary_names_nobody(mailbox: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    summary = _census(mailbox, "senders", capsys=capsys)
    assert summary["totals"]["senders"] == 3 and summary["tier"] == 2
    assert "@" not in json.dumps({k: v for k, v in summary.items() if k != "report"})
    cli.main(["lab", "hold", "census", "senders", "--tier", "3"])
    text = capsys.readouterr().out
    assert "4 senders" in text and "example.org" not in text.replace(str(mailbox.root), "")
    assert OLA in (mailbox.root / "state" / "hold" / "senders.md").read_text(encoding="utf-8")


# -- drive ---------------------------------------------------------------------------------------------------


def _drive(lb: Logbook, at: str, file_id: str, name: str, activity: str, **extra: Any) -> None:
    lb.append(
        at,
        "drive",
        "event",
        1,
        {
            "schema": "event/v1",
            "raw_id": f"{file_id}/{activity}@{at}",
            "title": f"{activity} {name}",
            "calendar": {"id": "google-drive", "name": "Google Drive"},
            "all_day": False,
            "modified_at": at,
            "extra": {
                "activity": activity,
                "count": extra.pop("count", 1),
                "file": {"id": file_id, "name": name, "mime_type": extra.pop("mime", "application/pdf"),
                         "path": extra.pop("path", ["My Drive", "Boat"])},
                "by_owner": True,
                **extra,
            },
        },
    )  # fmt: skip


@pytest.fixture
def drive(lb: Logbook) -> Logbook:
    """Four files: the crew list edited often and shared with a group; an old insurance scan untouched
    since 2021; a budget trashed; a photo trashed and restored."""
    _drive(lb, "2026-09-01T10:00:00Z", "f-crew", "Crew list", "create")
    _drive(lb, "2026-09-02T10:00:00Z", "f-crew", "Crew list", "edit", count=5)
    _drive(lb, "2026-09-03T10:00:00Z", "f-crew", "Crew list", "share",
           shares=[{"change": "added", "role": "writer", "with": {"group": "crew@example.org"}}])  # fmt: skip
    _drive(lb, "2021-05-01T10:00:00Z", "f-ins", "Insurance 2021", "create", path=["My Drive", "Papers"])
    _drive(
        lb,
        "2026-08-01T10:00:00Z",
        "f-budget",
        "Budget 2027",
        "edit",
        mime="application/vnd.google-apps.sheet",
    )
    _drive(
        lb,
        "2026-08-02T10:00:00Z",
        "f-budget",
        "Budget 2027",
        "trash",
        mime="application/vnd.google-apps.sheet",
    )
    _drive(lb, "2026-07-01T10:00:00Z", "f-photo", "berth.jpg", "trash", mime="image/jpeg")
    _drive(lb, "2026-07-02T10:00:00Z", "f-photo", "berth.jpg", "restore", mime="image/jpeg")
    return lb


def test_drive_files_by_activity_untouched_shared_and_gone(drive: Logbook) -> None:
    report = hold.census_drive(drive, now=NOW)
    rows = {row["id"]: row for row in report["files"]}
    assert report["totals"] == {"lines": 8, "files": 4, "untouched": 1, "shared": 1, "gone": 1}
    assert rows["f-crew"]["activities"] == 7 and rows["f-crew"]["shared_with"] == ["group"]
    assert rows["f-crew"]["folder"] == "My Drive/Boat"
    assert rows["f-ins"]["untouched"] and not rows["f-crew"]["untouched"]
    assert rows["f-budget"]["gone"] == "trash" and rows["f-photo"]["gone"] is None
    assert report["files"][0]["id"] == "f-crew", "the most active first"
    assert report["tier"] == 1
    folders = {row["folder"]: row["files"] for row in report["by_folder"]}
    assert folders == {"My Drive/Boat": 2, "My Drive/Papers": 1}, "a trashed file is not counted in place"
    years = {row["year"]: row["files"] for row in report["by_year"]}
    assert years == {2021: 1, 2026: 2}


def test_a_share_removed_later_is_not_shared(drive: Logbook) -> None:
    removed = [{"change": "removed", "role": "writer", "with": {"group": "crew@example.org"}}]
    _drive(drive, "2026-09-04T10:00:00Z", "f-crew", "Crew list", "share", shares=removed)
    report = hold.census_drive(drive, now=NOW)
    assert report["totals"]["shared"] == 0
    assert "crew@example.org" not in json.dumps(report), (
        "who a file is shared with is a kind, never an address"
    )


def test_drive_on_a_record_without_drive_lines_is_an_empty_report(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = _census(lb, "drive", capsys=capsys)
    assert summary["totals"]["files"] == 0 and summary["tier"] is None
    assert "(none)" in (lb.root / "state" / "hold" / "drive.md").read_text(encoding="utf-8")


def test_drive_summary_names_no_file(drive: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["lab", "hold", "census", "drive"])
    text = capsys.readouterr().out
    assert text.startswith("hold census drive: 4 files in 8 Drive lines; 1 untouched")
    assert "Crew list" not in text and "Insurance" not in text
    assert "Crew list" in (drive.root / "state" / "hold" / "drive.md").read_text(encoding="utf-8")


def test_a_payload_it_cannot_read_is_counted_never_a_traceback(lb: Logbook) -> None:
    lb.append(
        "2026-09-01T10:00:00Z", "drive", "event", 1, {"schema": "event/v1", "raw_id": "odd", "extra": []}
    )
    lb.append("2026-09-01T10:00:00Z", "mail", "mail", 2, {"schema": "mail/v1", "raw_id": "odd", "from": "x"})
    assert hold.census_drive(lb, now=NOW)["left_out"] == {"no_file": 1}
    assert hold.census_senders(lb, now=NOW)["left_out"] == {"no_sender": 1}


def test_size_text_reads_as_the_finder_does() -> None:
    assert [hold.size_text(n) for n in (0, 999, 1500, 3_200_000_000)] == ["0 B", "999 B", "1.5 KB", "3.2 GB"]


def test_a_modified_time_no_calendar_holds_is_unknown_never_a_traceback() -> None:
    assert hold._year(1e20, UTC) is None and hold._day(1e20, UTC) is None
    assert hold._year(RECENT, UTC) == 2026


def test_without_inodes_the_record_is_known_by_its_path(tmp_path: Path) -> None:
    assert hold._is_record(tmp_path, None, tmp_path)
    assert not hold._is_record(tmp_path / "other", None, tmp_path)


def test_a_name_that_is_markup_shows_as_written_and_fetches_nothing(lb: Logbook) -> None:
    _mail(
        lb,
        "2026-03-02T10:15:00Z",
        "promo@example.org",
        OWNER,
        "t-p",
        name="<img src=https://example.org/p.gif>",
    )
    _mail(lb, "2026-03-03T10:15:00Z", "link@example.org", OWNER, "t-l", name="[win](https://example.org/x)")
    text = hold.markdown(hold.census_senders(lb, now=NOW))
    assert not re.search(r"(?<!\\)<img", text) and "](" not in text, "every < and every ]( escaped"
    assert "\\<img src=https://example.org/p.gif\\>" in text
    assert "\\[win\\]\\(https://example.org/x\\)" in text


def test_a_cloud_placeholder_is_counted_and_never_read(
    lb: Logbook, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An iCloud file evicted from the Mac, a OneDrive file on demand: hashing it would fetch it."""
    away = {os.lstat(folder / "Photos" / "fjord.JPG").st_ino, os.lstat(folder / "Tax").st_ino}
    monkeypatch.setattr(hold, "_not_local", lambda st: st.st_ino in away)
    opened: list[str] = []
    real_open = hold._open

    def spy(path: Path) -> int:
        opened.append(path.name)
        return real_open(path)

    monkeypatch.setattr(hold, "_open", spy)
    report = hold.census_files(lb, [folder], NOW)
    assert report["skipped"]["not_local"] == 2, "one file, one folder"
    assert "fjord.JPG" not in opened and report["duplicates"]["sets"] == 0
    assert report["totals"]["files"] == 6, "the file is counted from its metadata; the folder not entered"


def test_the_flags_that_say_the_bytes_are_elsewhere() -> None:
    class Stat:
        st_flags = 0
        st_file_attributes = 0

    mac, windows, here = Stat(), Stat(), Stat()
    mac.st_flags = hold.SF_DATALESS
    windows.st_file_attributes = 0x00400000
    assert hold._not_local(mac) and hold._not_local(windows) and not hold._not_local(here)  # type: ignore[arg-type]


def test_a_disk_mounted_inside_is_not_entered(
    lb: Logbook, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _file(folder / "nas" / "backup.img", b"x" * 10)
    real_lstat = os.lstat

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        st = real_lstat(path, *args, **kwargs)
        if Path(path).name == "nas":
            values = list(st)
            values[2] = st.st_dev + 1  # st_dev: another disk
            return os.stat_result(values)
        return st

    monkeypatch.setattr(os, "lstat", lstat)
    report = hold.census_files(lb, [folder], NOW)
    assert report["skipped"]["other_disk"] == 1 and report["totals"]["files"] == 9


def test_claudes_folder_under_the_application_folders_is_skipped(lb: Logbook, folder: Path) -> None:
    _file(folder / "Application Support" / "Claude" / "config.json", b"{}")
    _file(folder / "Roaming" / "claude" / "log.txt", b"x")
    _file(folder / "People" / "Claude" / "letter.txt", b"a friend's letters are the owner's")
    _file(folder / ".claude.json", b"{}")
    report = hold.census_files(lb, [folder], NOW)
    assert report["skipped"]["system_folders"] == 2 and report["skipped"]["system_files"] == 1
    assert report["totals"]["files"] == 10


def test_a_report_folder_that_is_a_link_is_refused(lb: Logbook, folder: Path, tmp_path: Path) -> None:
    (lb.root / "state").mkdir(exist_ok=True)
    try:
        os.symlink(folder, lb.root / "state" / "hold", target_is_directory=True)
    except OSError:
        pytest.skip("this system makes no symbolic link here")
    before = sorted(p.name for p in folder.iterdir())
    with pytest.raises(hold.CensusError, match="not a plain folder"):
        hold.run(lb, "files", [tmp_path / "Documents"])
    assert sorted(p.name for p in folder.iterdir()) == before


def test_without_sent_mail_the_report_says_why_nobody_is_answered(lb: Logbook) -> None:
    _mail(lb, "2026-03-02T10:15:00Z", OLA, OWNER, "t-ola")
    report = hold.census_senders(lb, now=NOW)
    assert report["answered_note"] and "owner_emails" in report["answered_note"]
    assert "owner_emails" in hold.markdown(report)
    rows = hold.summary_rows(hold.summary(report, (Path("a.md"), Path("a.json"))))
    assert any(row.startswith("note: ") for row in rows)


def test_the_owners_own_access_is_no_share(drive: Logbook) -> None:
    owner = [{"change": "added", "role": "owner", "with": {"owner": True}}]
    _drive(drive, "2026-09-05T10:00:00Z", "f-ins", "Insurance 2021", "share", shares=owner)
    rows = {row["id"]: row for row in hold.census_drive(drive, now=NOW)["files"]}
    assert rows["f-ins"]["shared_with"] == []
