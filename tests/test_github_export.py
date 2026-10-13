"""`logbook add github-export DIR`: an old project's history as lines, so its ideas have a first-said date.

The input is a clone (a working copy or a bare repository) or an account export GitHub made (the
migration archive: its JSON files and the bare repositories beside them). The commits come from the
git log with their messages in full; each version of a README or a doc is one line with its digest
and word count, never its text; the archive's issues, pull requests, reviews and comments are the
lines `sync github` writes for them. Both sides share one mapping, so the same commit (by sha) and
the same issue (by number) read either way are one line.

Every repository here is made by the test with `git`, under the test's own folder, from synthetic
content: Ines Nordmann of Oslo and her brother Ola, who do not exist. A test that needs git is
skipped where it is not on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from github_api import INES, OLA, SAILPLAN, TOKEN, FakeGitHub, account, issue

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import github
from logbook.core.store import Logbook

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")

INES_EMAIL, OLA_EMAIL = "ines.nordmann@example.org", "ola@example.org"
README_1 = b"# Old boat\n\nIdea: a logbook that writes itself, from what the phone already knows.\n"
README_2 = README_1 + b"\nCrew: Ines and Ola.\n"
IDEAS = b"Ideas\n\n- tide tables for the fjord\n- a day page\n"
OLDBOAT = "ines-example/oldboat"
FIRST_MESSAGE = "Start the old boat project\n\nThe first idea, written down before anything else.\n"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """`git` in `repo`, the machine's and the user's configuration aside, so a signing or a line-ending
    setting can never change a hash."""
    base = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(repo.parent / "no-gitconfig"),
        "GIT_TERMINAL_PROMPT": "0",
    }
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo,
        env={**base, **(env or {})},
        capture_output=True,
        check=True,
    )
    return done.stdout.decode("utf-8")


def _commit(
    repo: Path,
    message: str,
    at: str,
    files: dict[str, bytes | None],
    name: str = "Ines Nordmann",
    email: str = "",
) -> str:
    """One commit at `at` (RFC 3339 with an offset) by `name`; a file given None is removed."""
    for path, data in files.items():
        target = repo.joinpath(*path.split("/"))
        if data is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(repo, "add", "-A")
    who = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email or INES_EMAIL,
        "GIT_AUTHOR_DATE": at,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email or INES_EMAIL,
        "GIT_COMMITTER_DATE": at,
    }
    _git(repo, "commit", "-q", "-m", message, env=who)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def oldboat(tmp_path: Path) -> tuple[Path, list[str]]:
    """Ines's old self-hosted project, 2019: five commits on `main`, its remote on her own server.

    1. README.md, docs/ideas.md, docs/plan.png and src/main.py, the first idea written down.
    2. Ola adds the crew to the README.
    3. Only the code changes.
    4. The README goes back to its first version, byte for byte.
    5. The ideas grow.
    """
    repo = tmp_path / "oldboat"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", f"https://git.example.org/{OLDBOAT}.git")
    shas = [
        _commit(
            repo,
            FIRST_MESSAGE,
            "2019-05-01T10:00:00+02:00",
            {
                "README.md": README_1,
                "docs/ideas.md": IDEAS,
                "docs/plan.png": b"\x89PNG",
                "src/main.py": b"pass\n",
            },
        ),
        _commit(
            repo,
            "README: the crew",
            "2019-06-01T09:00:00+02:00",
            {"README.md": README_2},
            "Ola Nordmann",
            OLA_EMAIL,
        ),
        _commit(repo, "Main loop", "2019-07-01T21:00:00+02:00", {"src/main.py": b"while True:\n    pass\n"}),
        _commit(repo, "Back to the first README", "2019-08-01T08:00:00+02:00", {"README.md": README_1}),
        _commit(
            repo, "More ideas", "2019-09-01T08:00:00+02:00", {"docs/ideas.md": IDEAS + b"- a year poster\n"}
        ),
    ]
    return repo, shas


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = {"names": [], "emails": [INES_EMAIL], "phones": [], "handles": ["ines-example"]}
    (lb.root / "policy" / "owner.json").write_text(json.dumps(data), encoding="utf-8")
    return lb


def _add(*args: str) -> int:
    try:
        cli.main(["add", "github-export", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _lines(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["source"] == "github"]


def _keyed(lb: Logbook) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in _lines(lb)}


def _versions(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in _lines(lb) if line["payload"]["extra"]["action"] == "revised"]


# -- the registry ---------------------------------------------------------------------------------------


def test_the_export_is_the_github_file_adapter_read_by_name_only(tmp_path: Path) -> None:
    assert adapters.named("github-export") is github
    assert adapters.named("github") is github
    assert github.NAME == "github", "the live source's name: the two dedupe each other"
    assert github.sniff(tmp_path) is False, "a folder is never guessed to be a project"


# -- a clone --------------------------------------------------------------------------------------------


def test_a_clone_gives_a_line_per_commit_with_its_message_in_full(
    lb: Logbook, oldboat: tuple[Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, shas = oldboat
    assert _add(str(repo)) == 0
    out = capsys.readouterr().out
    keyed = _keyed(lb)
    commits = [keyed[f"commit/{sha}"] for sha in shas]
    first = commits[0]
    assert first["at"] == "2019-05-01T08:00:00Z" and (first["kind"], first["tier"]) == ("event", 1)
    p = first["payload"]
    assert p["title"] == "Start the old boat project" and p["notes"] == FIRST_MESSAGE
    assert p["extra"]["action"] == "committed" and p["extra"]["repo"] == OLDBOAT
    assert p["extra"]["branch"] == "main" and p["extra"]["commit"] == {"sha": shas[0]}
    assert p["extra"]["files"] == 4
    assert p["extra"]["actor"] == {"name": "Ines Nordmann", "role": "owner"}
    ola = commits[1]["payload"]["extra"]["actor"]
    assert ola == {"name": "Ola Nordmann", "role": "other"}
    assert "organizer" not in commits[1]["payload"], "an address is never a handle"
    assert OLA_EMAIL not in json.dumps(commits[1]), "an address is read to tell the owner, never kept"
    assert "can be deleted" not in out, "a clone is the owner's working copy, never consumed"


def test_each_version_of_a_readme_or_a_doc_is_a_line_with_its_digest_never_its_text(
    lb: Logbook, oldboat: tuple[Path, list[str]]
) -> None:
    repo, shas = oldboat
    assert _add(str(repo)) == 0
    versions = {(v["payload"]["title"], v["at"]): v for v in _versions(lb)}
    assert set(versions) == {
        ("README.md", "2019-05-01T08:00:00Z"),
        ("docs/ideas.md", "2019-05-01T08:00:00Z"),
        ("README.md", "2019-06-01T07:00:00Z"),
        ("docs/ideas.md", "2019-09-01T06:00:00Z"),
    }, "the png and the code are no docs, and the README's return to its first text is no new version"
    first = versions[("README.md", "2019-05-01T08:00:00Z")]["payload"]
    blob = _git(repo, "rev-parse", f"{shas[0]}:README.md").strip()
    assert first["raw_id"] == f"{OLDBOAT}/file/README.md@{blob}"
    assert first["extra"]["file"] == {"path": "README.md", "blob": blob}
    assert first["extra"]["commit"] == {"sha": shas[0]}
    import hashlib

    assert first["extra"]["content"] == {
        "sha256": hashlib.sha256(README_1).hexdigest(),
        "bytes": len(README_1),
        "media_type": "text/markdown",
        "words": len(README_1.decode("utf-8").split()),
    }
    second = versions[("README.md", "2019-06-01T07:00:00Z")]["payload"]
    assert second["extra"]["content"]["words_delta"] == 4
    assert second["extra"]["actor"]["role"] == "other"
    for v in _versions(lb):
        assert "notes" not in v["payload"]
        assert "logbook that writes itself" not in json.dumps(v), "the text is never kept"


def test_adding_the_clone_again_writes_nothing(lb: Logbook, oldboat: tuple[Path, list[str]]) -> None:
    repo, _shas = oldboat
    assert _add(str(repo)) == 0
    n = len(_lines(lb))
    assert n == 9, "five commits, four doc versions"
    assert _add(str(repo)) == 0
    assert len(_lines(lb)) == n


def test_a_dry_run_counts_and_writes_nothing(
    lb: Logbook, oldboat: tuple[Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, _shas = oldboat
    assert _add(str(repo), "--dry-run") == 0
    assert "9" in capsys.readouterr().out
    assert _lines(lb) == []


def test_since_reads_from_there(lb: Logbook, oldboat: tuple[Path, list[str]]) -> None:
    repo, shas = oldboat
    assert _add(str(repo), "--since", "2019-07-15") == 0
    keyed = _keyed(lb)
    assert set(keyed) >= {f"commit/{shas[3]}", f"commit/{shas[4]}"}
    assert f"commit/{shas[2]}" not in keyed
    assert [v["payload"]["title"] for v in _versions(lb)] == ["docs/ideas.md"]


def test_a_bare_repository_reads_as_its_clone(
    lb: Logbook, oldboat: tuple[Path, list[str]], tmp_path: Path
) -> None:
    repo, shas = oldboat
    bare = tmp_path / "oldboat.git"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    assert _add(str(bare)) == 0
    assert len(_lines(lb)) == 9
    assert _keyed(lb)[f"commit/{shas[0]}"]["payload"]["extra"]["repo"] == "oldboat", "no remote: its folder"


def test_a_noreply_address_spells_the_login(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github, "NOREPLY", "users.noreply.example.org")
    repo = tmp_path / "noreply"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    sha = _commit(
        repo,
        "Hello",
        "2020-01-01T10:00:00+01:00",
        {"a.txt": b"a\n"},
        "Ola",
        "970000002+ola-example@users.noreply.example.org",
    )
    assert _add(str(repo)) == 0
    p = _keyed(lb)[f"commit/{sha}"]["payload"]
    assert p["extra"]["actor"] == {"login": "ola-example", "name": "Ola", "role": "other"}
    assert p["organizer"] == {"kind": "handle", "value": "github:ola-example"}


def test_a_folder_that_is_no_project_is_one_sentence(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "plain").mkdir()
    assert _add(str(tmp_path / "plain")) == 2
    err = capsys.readouterr().err
    assert "not a git clone" in err and len(err.strip().splitlines()) == 1


def test_the_git_it_runs_reads_and_never_fetches(
    lb: Logbook, oldboat: tuple[Path, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    real = subprocess.Popen

    def watched(args: list[str], *rest: Any, **kwargs: Any) -> Any:
        calls.append((list(args), dict(kwargs.get("env") or {})))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(github.subprocess, "Popen", watched)
    repo, _shas = oldboat
    assert _add(str(repo)) == 0
    assert calls
    for args, env in calls:
        assert args[0] == "git"
        verb = next(a for a in args[1:] if not a.startswith("-") and a not in {str(repo)} and "=" not in a)
        assert verb in {"rev-parse", "symbolic-ref", "config", "log", "cat-file"}, args
        assert env.get("GIT_NO_LAZY_FETCH") == "1" and env.get("GIT_TERMINAL_PROMPT") == "0"


# -- an account export ----------------------------------------------------------------------------------

ARCHIVE_WEB = "https://github.example.org"


def _archive(root: Path, work: Path) -> Path:
    """GitHub's account export (the migration archive) of sailplan, as its files spell things: the
    repository, its bare git beside, issue #1 (Ola's, which Ines closed), pull request #2 (Ines's, an
    agent's, merged), a comment, a review and an inline comment."""
    archive = root / "github-export"
    target = archive / "repositories" / "ines-example" / "sailplan.git"
    target.parent.mkdir(parents=True)
    _git(root, "clone", "-q", "--bare", str(work), str(target))
    url = f"{ARCHIVE_WEB}/{SAILPLAN}"

    def write(name: str, rows: list[dict[str, Any]]) -> None:
        (archive / name).write_text(json.dumps(rows), encoding="utf-8")

    (archive / "schema.json").write_text(json.dumps({"version": "1.2.0"}), encoding="utf-8")
    write(
        "repositories_000001.json",
        [
            {
                "type": "repository",
                "url": url,
                "owner": f"{ARCHIVE_WEB}/ines-example",
                "name": "sailplan",
                "private": False,
                "default_branch": "main",
                "git_url": "tarball://root/repositories/ines-example/sailplan.git",
            }
        ],
    )
    write(
        "issues_000001.json",
        [
            {
                "type": "issue",
                "url": f"{url}/issues/1",
                "repository": url,
                "user": f"{ARCHIVE_WEB}/ola-example",
                "title": "Which harbour first?",
                "body": "Drøbak or Hvaler? The wind decides.",
                "labels": [f"{url}/labels/question"],
                "created_at": "2026-03-01T13:00:00.000+01:00",
                "closed_at": "2026-03-02T09:00:00.000+01:00",
            }
        ],
    )
    write(
        "pull_requests_000001.json",
        [
            {
                "type": "pull_request",
                "url": f"{url}/pull/2",
                "repository": url,
                "user": f"{ARCHIVE_WEB}/ines-example",
                "title": "Tide table for March",
                "body": "Adds the table.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
                "base": {"ref": "main"},
                "head": {"ref": "feature-2"},
                "created_at": "2026-03-03T11:30:00.000+01:00",
                "closed_at": "2026-03-03T16:00:00.000+01:00",
                "merged_at": "2026-03-03T16:00:00.000+01:00",
            }
        ],
    )
    write(
        "issue_events_000001.json",
        [
            {
                "type": "issue_event",
                "url": f"{url}/issues/1#event-970600001",
                "issue": f"{url}/issues/1",
                "actor": f"{ARCHIVE_WEB}/ines-example",
                "event": "closed",
                "created_at": "2026-03-02T09:00:00.000+01:00",
            },
            {
                "type": "issue_event",
                "url": f"{url}/pull/2#event-970600002",
                "pull_request": f"{url}/pull/2",
                "actor": f"{ARCHIVE_WEB}/ines-example",
                "event": "merged",
                "created_at": "2026-03-03T16:00:00.000+01:00",
            },
        ],
    )
    write(
        "issue_comments_000001.json",
        [
            {
                "type": "issue_comment",
                "url": f"{url}/issues/1#issuecomment-970300101",
                "issue": f"{url}/issues/1",
                "user": f"{ARCHIVE_WEB}/ines-example",
                "body": "Drøbak first.",
                "created_at": "2026-03-01T14:00:00.000+01:00",
            }
        ],
    )
    write(
        "pull_request_reviews_000001.json",
        [
            {
                "type": "pull_request_review",
                "url": f"{url}/pull/2/files#pullrequestreview-970400201",
                "pull_request": f"{url}/pull/2",
                "user": f"{ARCHIVE_WEB}/ola-example",
                "body": "Looks right.",
                "state": "approved",
                "submitted_at": "2026-03-03T15:00:00.000+01:00",
            }
        ],
    )
    write(
        "pull_request_review_comments_000001.json",
        [
            {
                "type": "pull_request_review_comment",
                "url": f"{url}/pull/2#discussion_r970500301",
                "pull_request": f"{url}/pull/2",
                "pull_request_review": f"{url}/pull/2/files#pullrequestreview-970400201",
                "user": f"{ARCHIVE_WEB}/ola-example",
                "body": "Check the 14:00 entry.",
                "path": "tides.md",
                "created_at": "2026-03-03T14:50:00.000+01:00",
            }
        ],
    )
    write(
        "users_000001.json", [{"type": "user", "url": f"{ARCHIVE_WEB}/ines-example", "login": "ines-example"}]
    )
    return archive


@pytest.fixture
def sailplan(tmp_path: Path) -> tuple[Path, list[str]]:
    """sailplan's history as a clone: two commits, Ines's and Ola's, its README twice."""
    repo = tmp_path / "sailplan"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", f"git@git.example.org:{SAILPLAN}.git")
    shas = [
        _commit(repo, "Start the sail plan", "2026-03-01T09:00:00+01:00", {"README.md": b"# Sail plan\n"}),
        _commit(
            repo,
            "Add the crew list",
            "2026-03-02T10:30:00+01:00",
            {"README.md": b"# Sail plan\n\nCrew: Ola.\n"},
            "Ola Nordmann",
            OLA_EMAIL,
        ),
    ]
    return repo, shas


ARCHIVE_KEYS = {
    "ines-example/sailplan/issues/1/created",
    "ines-example/sailplan/issues/1/closed@2026-03-02T08:00:00Z",
    "ines-example/sailplan/pull/2/created",
    "ines-example/sailplan/pull/2/merged",
    "ines-example/sailplan/issues/comments/970300101",
    "ines-example/sailplan/pull/2/reviews/970400201",
    "ines-example/sailplan/pulls/comments/970500301",
}


def test_an_account_export_gives_the_lines_sync_github_writes(
    lb: Logbook, sailplan: tuple[Path, list[str]], tmp_path: Path
) -> None:
    work, shas = sailplan
    archive = _archive(tmp_path, work)
    assert _add(str(archive)) == 0
    keyed = _keyed(lb)
    assert set(keyed) >= ARCHIVE_KEYS | {f"commit/{sha}" for sha in shas}
    assert keyed[f"commit/{shas[0]}"]["payload"]["extra"]["repo"] == SAILPLAN
    opened = keyed["ines-example/sailplan/issues/1/created"]
    assert opened["at"] == "2026-03-01T12:00:00Z" and opened["tier"] == 1
    p = opened["payload"]
    assert (p["title"], p["notes"]) == ("Which harbour first?", "Drøbak or Hvaler? The wind decides.")
    assert p["extra"]["issue"] == {"number": 1, "url": f"{ARCHIVE_WEB}/{SAILPLAN}/issues/1"}
    assert p["extra"]["labels"] == ["question"]
    assert p["extra"]["actor"] == {"login": "ola-example", "role": "other"}
    assert p["organizer"] == {"kind": "handle", "value": "github:ola-example"}
    closed = keyed["ines-example/sailplan/issues/1/closed@2026-03-02T08:00:00Z"]["payload"]
    assert closed["extra"]["actor"] == {"login": "ines-example", "role": "owner"}
    merged = keyed["ines-example/sailplan/pull/2/merged"]["payload"]
    assert merged["extra"]["agent"] is True and merged["extra"]["actor"]["role"] == "owner"
    assert (merged["extra"]["base"], merged["extra"]["head"]) == ("main", "feature-2")
    assert keyed["ines-example/sailplan/pull/2/created"]["payload"]["extra"]["agent"] is True
    review = keyed["ines-example/sailplan/pull/2/reviews/970400201"]["payload"]
    assert review["extra"]["review"]["state"] == "approved" and review["notes"] == "Looks right."
    inline = keyed["ines-example/sailplan/pulls/comments/970500301"]["payload"]
    assert inline["extra"]["path"] == "tides.md" and inline["extra"]["pull"]["number"] == 2
    comment = keyed["ines-example/sailplan/issues/comments/970300101"]["payload"]
    assert comment["title"] == "Which harbour first?" and comment["extra"]["actor"]["role"] == "owner"


# -- the live source and the export, either first ------------------------------------------------------


def _live_from(work: Path, shas: list[str]) -> FakeGitHub:
    """The fake API serving sailplan as the clone has it: the same commits, by the same hashes, and
    issue #1 as the archive has it."""
    fake = account()
    fake.repos = {SAILPLAN: fake.repos[SAILPLAN]}
    fake.commits[SAILPLAN] = []
    for n, sha in enumerate(shas):
        message = _git(work, "log", "-1", "--format=%B", sha)
        when = _git(work, "log", "-1", "--format=%aI", sha).strip()
        by = INES if n == 0 else OLA
        stamp = github.stamp(github.instant(when))  # type: ignore[arg-type]
        person = {"name": "Ines Nordmann" if n == 0 else "Ola Nordmann", "email": INES_EMAIL, "date": stamp}
        fake.add_commit(
            SAILPLAN,
            {
                "sha": sha,
                "commit": {"author": person, "committer": person, "message": message},
                "author": by,
                "committer": by,
                "parents": [],
                "html_url": f"{ARCHIVE_WEB}/{SAILPLAN}/commit/{sha}",
                "_files": [{"filename": "README.md"}],
            },
        )
    fake.issues[SAILPLAN] = [
        issue(
            SAILPLAN,
            1,
            "Which harbour first?",
            "Drøbak or Hvaler? The wind decides.",
            OLA,
            "2026-03-01T12:00Z",
            closed="2026-03-02T08:00Z",
            closed_by=INES,
        )
    ]
    fake.comments[SAILPLAN], fake.reviews, fake.review_comments[SAILPLAN] = [], {}, []
    return fake


def _sync(fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch) -> int:
    from logbook.contrib.adapters import github_live

    monkeypatch.setattr(github_live, "_sleep", lambda _s: None)
    monkeypatch.setenv("LOGBOOK_GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("LOGBOOK_GITHUB_REPOS", SAILPLAN)
    monkeypatch.setenv("LOGBOOK_GITHUB_URL", fake.url)
    try:
        cli.main(["sync", "github"])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


@pytest.mark.parametrize("live_first", [True, False])
def test_the_same_commit_and_issue_read_either_way_are_one_line(
    lb: Logbook,
    sailplan: tuple[Path, list[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    live_first: bool,
) -> None:
    work, shas = sailplan
    archive = _archive(tmp_path, work)
    fake = _live_from(work, shas)
    fake.start()
    try:
        if live_first:
            assert _sync(fake, monkeypatch) == 0
            capsys.readouterr()
            assert _add(str(archive)) == 0
            out = capsys.readouterr().out
            assert "4 already in the record" in out, "two commits, issue #1 created and closed"
        else:
            assert _add(str(archive)) == 0
            capsys.readouterr()
            assert _sync(fake, monkeypatch) == 0
            out = capsys.readouterr().out
            assert "(4 already in the record)" in out
    finally:
        fake.stop()
    keys = [line["payload"]["raw_id"] for line in _lines(lb)]
    assert len(keys) == len(set(keys)), "each act once"
    assert {f"commit/{sha}" for sha in shas} <= set(keys)
    assert "ines-example/sailplan/issues/1/created" in keys
    assert len([k for k in keys if "/file/README.md@" in k]) == 2, (
        "the doc versions come from the export alone"
    )
