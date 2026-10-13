"""One key for every Google source: `service_account` signs in `sync gmail`, `sync gcal`, `sync drive` and
`sync gtasks` alike, a scope per call and an hour's token in memory, never on disk; `doctor` shows one
`google` line for the key, the user and the sources on it, and asks Google nothing.

Against the in-process fake of `tests/google_fake.py`; Ines Nordmann of Oslo does not exist."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from google_fake import DRIVE_SCOPE, GMAIL_SCOPE, USER, Fake, private_key, write_key

from logbook.contrib import doctor
from logbook.contrib.adapters import service_account
from logbook.core import policy
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
PROFILE = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
MISSING = "https://gmail.googleapis.com/gmail/v1/users/me/messages/0"


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key)
    server.waits = []  # type: ignore[attr-defined]
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", server.waits.append)  # type: ignore[attr-defined]
    monkeypatch.setenv(KEY_ENV, str(write_key(tmp_path / "google-sa.json", key)))
    monkeypatch.setenv(USER_ENV, USER)
    yield server
    assert no_network == [], "the fake is the only way out"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _account() -> service_account.Account:
    account = service_account.configure(os.environ)
    assert account is not None
    return account


def _google(lb: Logbook, env: dict[str, str] | None = None) -> doctor.Check | None:
    checks = doctor.run(lb, dict(os.environ) if env is None else env, installed=lambda _m: True)
    return next((c for c in checks if c.name == "google"), None)


# -- the one module -----------------------------------------------------------------------------------


def test_every_google_source_is_named_with_its_one_read_only_scope() -> None:
    assert service_account.SOURCES == ("gmail", "gcal", "drive", "gtasks")
    assert service_account.SCOPES == {
        "gmail": "https://www.googleapis.com/auth/gmail.readonly",
        "gcal": "https://www.googleapis.com/auth/calendar.readonly",
        "drive": "https://www.googleapis.com/auth/drive.activity.readonly",
        "drive paths": "https://www.googleapis.com/auth/drive.metadata.readonly",
        "gtasks": "https://www.googleapis.com/auth/tasks.readonly",
    }
    assert all(scope.endswith(".readonly") for scope in service_account.SCOPES.values())


def test_a_session_asks_for_its_one_scope_and_no_other(fake: Fake) -> None:
    service_account.Session(_account(), GMAIL_SCOPE).get_json(PROFILE, {})
    assert [a["scope"] for a in fake.assertions] == [GMAIL_SCOPE]


def test_an_answer_not_worth_retrying_carries_its_status_and_reasons(fake: Fake) -> None:
    with pytest.raises(service_account.ApiError) as e:
        service_account.Session(_account(), GMAIL_SCOPE).get_json(MISSING, {"format": "raw"})
    assert e.value.status == 404 and "not found" in str(e.value)
    assert isinstance(e.value, service_account.GoogleError) and isinstance(e.value, OSError)
    assert fake.waits == []  # type: ignore[attr-defined]
    fake.fail(410, reason="updatedMinTooLongAgo")
    with pytest.raises(service_account.ApiError) as e:
        service_account.Session(_account(), GMAIL_SCOPE).get_json(PROFILE, {})
    assert e.value.status == 410 and e.value.reasons == frozenset({"updatedMinTooLongAgo"})


def test_a_scope_not_delegated_is_its_own_error_naming_the_scope(fake: Fake) -> None:
    fake.delegated = {DRIVE_SCOPE}
    with pytest.raises(service_account.ScopeRefused) as e:
        service_account.Session(_account(), GMAIL_SCOPE).get_json(PROFILE, {})
    assert e.value.scope == GMAIL_SCOPE and GMAIL_SCOPE in str(e.value)
    assert "domain-wide delegation" in str(e.value)


def test_the_token_lives_in_memory_and_no_file_is_written(fake: Fake, tmp_path: Path) -> None:
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    session = service_account.Session(_account(), GMAIL_SCOPE)
    session.get_json(PROFILE, {})
    session.get_json(PROFILE, {})
    assert len(fake.issued) == 1, "one token for the run"
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    token = next(iter(fake.issued))
    assert token not in repr(session) and not hasattr(service_account, "TOKEN_FILE")


# -- doctor's google line ------------------------------------------------------------------------------


def test_doctor_shows_one_google_line_key_user_and_the_sources_on_it(lb: Logbook, fake: Fake) -> None:
    check = _google(lb)
    assert check is not None
    assert check.status == "pass"
    assert check.detail == "key present, user set; sources on the key: gmail, gcal, drive, gtasks"
    assert fake.requests == [], "doctor asks Google nothing"
    assert USER not in check.detail and "google-sa.json" not in check.detail


def test_doctor_puts_the_google_line_before_the_sources_it_covers(lb: Logbook, fake: Fake) -> None:
    names = [c.name for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)]
    google = names.index("google")
    assert all(google < i for i, name in enumerate(names) if name.startswith("sync:"))
    assert {"sync:drive", "sync:gtasks"} <= set(names)


def test_doctor_names_a_disabled_source_on_the_google_line(lb: Logbook, fake: Fake) -> None:
    path = policy.import_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "disabled": [
                    {"source": "gtasks", "reason": "not mine"},
                    {"source": "gmail", "reason": "IMAP for now"},
                ]
            }
        ),
        encoding="utf-8",
    )
    check = _google(lb)
    assert check is not None and check.status == "pass"
    assert check.detail.endswith("sources on the key: gcal, drive (gmail, gtasks disabled)")


def test_doctor_without_either_variable_shows_no_google_line(lb: Logbook) -> None:
    assert _google(lb, {}) is None


@pytest.mark.parametrize(
    ("env", "said"),
    [
        ({USER_ENV: USER}, f"{KEY_ENV} not set, user set"),
        (
            {KEY_ENV: "~/nowhere/google-sa.json", USER_ENV: USER},
            f"{KEY_ENV} names no readable file, user set",
        ),
        ({KEY_ENV: "KEY"}, f"key present, {USER_ENV} not set"),
        ({KEY_ENV: "KEY", USER_ENV: "ines"}, f"key present, {USER_ENV} is not an address"),
    ],
)
def test_doctor_warns_on_the_google_line_when_the_key_or_the_user_is_wrong(
    lb: Logbook, fake: Fake, env: dict[str, str], said: str
) -> None:
    given = {k: (os.environ[KEY_ENV] if v == "KEY" else v) for k, v in env.items()}
    check = _google(lb, given)
    assert check is not None and check.status == "warn"
    assert check.detail.startswith(said + "; sources on the key: ")
    assert fake.requests == []


def test_doctor_says_when_the_key_file_is_not_a_service_account_key(lb: Logbook, tmp_path: Path) -> None:
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"type": "authorized_user"}), encoding="utf-8")
    check = _google(lb, {KEY_ENV: str(other), USER_ENV: USER})
    assert check is not None and check.status == "warn"
    assert check.detail.startswith(f"{KEY_ENV}: the file is not a service-account key")
