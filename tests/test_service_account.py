"""The sign-in `sync drive` and `sync gtasks` share: a Google service account with domain-wide
delegation, configured by two variables (the key file, the user to read as), a token minted per run from
a signed assertion and never stored, every call retried with backoff on 429 and 5xx. Against the
in-process fake of `tests/google_fake.py`; nothing leaves the process (`no_network`)."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from google_fake import CLIENT_EMAIL, DRIVE_SCOPE, TASKS_SCOPE, USER, Fake, private_key, write_key

from logbook.contrib.adapters import service_account

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
QUERY = "https://driveactivity.googleapis.com/v2/activity:query"
LISTS = "https://tasks.googleapis.com/tasks/v1/users/@me/lists"


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def key_file(tmp_path: Path, key: Any) -> Path:
    return write_key(tmp_path / "google-sa.json", key)


@pytest.fixture
def env(key_file: Path) -> dict[str, str]:
    return {KEY_ENV: str(key_file), USER_ENV: USER}


@pytest.fixture
def fake(key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key)
    waits: list[float] = []
    monkeypatch.setattr(service_account, "send", server)
    monkeypatch.setattr(service_account, "sleep", waits.append)
    server.waits = waits  # type: ignore[attr-defined]
    yield server
    assert no_network == [], "the fake is the only way out"


def _account(env: dict[str, str]) -> service_account.Account:
    account = service_account.configure(env)
    assert account is not None
    return account


# -- configure ------------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [KEY_ENV, USER_ENV])
def test_configure_is_none_until_both_variables_are_set(env: dict[str, str], missing: str) -> None:
    env[missing] = " "
    assert service_account.configure(env) is None
    assert service_account.configure({}) is None


def test_configure_reads_the_key_and_the_user_and_its_repr_shows_neither(env: dict[str, str]) -> None:
    account = _account(env)
    assert account.user == USER and account.client_email == CLIENT_EMAIL
    assert Path(account.key_file) == Path(env[KEY_ENV])
    shown = repr(account)
    for secret in (USER, CLIENT_EMAIL, env[KEY_ENV], "private"):
        assert secret not in shown


def test_configure_expands_a_home_relative_path(tmp_path: Path, key: Any) -> None:
    """The schedule's environment file is read by systemd, which expands nothing: `~` is ours to expand.
    The fixture of conftest.py points the home directory at the test's own folder."""
    home = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    write_key(home / "google-sa.json", key)
    account = _account({KEY_ENV: "~/google-sa.json", USER_ENV: USER})
    assert Path(account.key_file) == home / "google-sa.json"


@pytest.mark.parametrize(
    ("content", "says"),
    [
        (None, "names no readable file"),
        ("not json {", "not JSON"),
        (json.dumps({"installed": {"client_id": "x"}}), "not a service-account key"),
        (json.dumps({"type": "service_account", "client_email": CLIENT_EMAIL}), "not a service-account key"),
    ],
)
def test_configure_refuses_a_key_file_it_cannot_use_without_echoing_the_path(
    tmp_path: Path, content: str | None, says: str
) -> None:
    path = tmp_path / "secret-folder" / "key.json"
    if content is not None:
        path.parent.mkdir()
        path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=says) as e:
        service_account.configure({KEY_ENV: str(path), USER_ENV: USER})
    assert "secret-folder" not in str(e.value) and KEY_ENV in str(e.value)


@pytest.mark.parametrize("user", ["ines", "@example.org", "ines@", "ines @example.org"])
def test_configure_refuses_a_user_that_is_not_an_address(env: dict[str, str], user: str) -> None:
    env[USER_ENV] = user
    with pytest.raises(ValueError, match=USER_ENV) as e:
        service_account.configure(env)
    assert user.strip() not in str(e.value) or user.strip() == ""


# -- the token --------------------------------------------------------------------------------------


def test_the_assertion_is_signed_by_the_key_for_the_user_and_the_one_scope(
    env: dict[str, str], fake: Fake
) -> None:
    session = service_account.Session(_account(env), DRIVE_SCOPE)
    assert session.post_json(QUERY, {"pageSize": 10}) == {"activities": []}
    (claims,) = fake.assertions
    assert claims["iss"] == CLIENT_EMAIL and claims["sub"] == USER and claims["scope"] == DRIVE_SCOPE
    assert claims["aud"] == service_account.TOKEN_URL and claims["exp"] - claims["iat"] == 3600


def test_one_token_serves_every_call_of_a_run(env: dict[str, str], fake: Fake) -> None:
    session = service_account.Session(_account(env), TASKS_SCOPE)
    for _ in range(3):
        session.get_json(LISTS, {"maxResults": "100"})
    assert len(fake.calls("oauth2.googleapis.com/token")) == 1


def test_an_expired_token_is_minted_again_on_a_401(env: dict[str, str], fake: Fake) -> None:
    session = service_account.Session(_account(env), TASKS_SCOPE)
    session.get_json(LISTS, {})
    fake.issued.clear()  # Google forgot it: the next call is a 401
    assert session.get_json(LISTS, {}) == {"kind": "tasks#taskLists", "items": []}
    assert len(fake.calls("oauth2.googleapis.com/token")) == 2


def test_a_scope_the_delegation_does_not_grant_says_where_to_grant_it(
    env: dict[str, str], fake: Fake
) -> None:
    fake.delegated = {DRIVE_SCOPE}
    session = service_account.Session(_account(env), TASKS_SCOPE)
    with pytest.raises(service_account.GoogleError) as e:
        session.get_json(LISTS, {})
    text = str(e.value)
    assert "unauthorized_client" in text and "domain-wide delegation" in text and TASKS_SCOPE in text
    assert "eyJ" not in text, "never the assertion"


def test_nothing_is_written_to_disk_but_what_was_there(
    env: dict[str, str], fake: Fake, tmp_path: Path
) -> None:
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    service_account.Session(_account(env), DRIVE_SCOPE).post_json(QUERY, {})
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before, "no token is kept"


# -- backoff ---------------------------------------------------------------------------------------


def test_429_waits_as_long_as_retry_after_says_and_5xx_doubles(env: dict[str, str], fake: Fake) -> None:
    fake.fail(429, retry_after="7")
    fake.fail(503)
    fake.fail(500)
    session = service_account.Session(_account(env), DRIVE_SCOPE)
    assert session.post_json(QUERY, {}) == {"activities": []}
    assert fake.waits == [7.0, 2.0, 4.0]  # type: ignore[attr-defined]
    assert len(fake.calls("driveactivity.googleapis.com/v2/activity:query")) == 4


def test_a_403_rate_limit_is_retried_and_any_other_403_is_not(env: dict[str, str], fake: Fake) -> None:
    session = service_account.Session(_account(env), DRIVE_SCOPE)
    fake.fail(403, reason="userRateLimitExceeded")
    assert session.post_json(QUERY, {}) == {"activities": []}
    fake.fail(403, reason="insufficientPermissions")
    with pytest.raises(service_account.GoogleError, match="HTTP 403"):
        session.post_json(QUERY, {})


def test_retry_after_is_capped(env: dict[str, str], fake: Fake) -> None:
    fake.fail(429, retry_after="86400")
    service_account.Session(_account(env), DRIVE_SCOPE).post_json(QUERY, {})
    assert fake.waits == [service_account.BACKOFF_MAX_S]  # type: ignore[attr-defined]


def test_it_gives_up_after_the_last_retry_and_says_so(env: dict[str, str], fake: Fake) -> None:
    for _ in range(service_account.RETRIES + 1):
        fake.fail(503)
    with pytest.raises(service_account.GoogleError) as e:
        service_account.Session(_account(env), DRIVE_SCOPE).post_json(QUERY, {})
    assert "HTTP 503" in str(e.value) and f"{service_account.RETRIES + 1} tries" in str(e.value)


def test_a_lost_connection_is_retried_like_a_5xx(env: dict[str, str], fake: Fake, monkeypatch: Any) -> None:
    lost = [True]

    def flaky(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> Any:
        if url == QUERY and lost:
            lost.pop()
            raise ConnectionResetError("connection reset by peer")
        return fake(method, url, headers, body, timeout)

    monkeypatch.setattr(service_account, "send", flaky)
    assert service_account.Session(_account(env), DRIVE_SCOPE).post_json(QUERY, {}) == {"activities": []}
    assert fake.waits == [1.0]  # type: ignore[attr-defined]


# -- doctor's check ------------------------------------------------------------------------------


def test_describe_reads_the_key_and_asks_no_one(env: dict[str, str], fake: Fake) -> None:
    text = service_account.describe(_account(env))
    assert "service-account key" in text and "never stored" in text
    assert fake.requests == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_describe_warns_when_the_key_is_readable_by_others(env: dict[str, str], key_file: Path) -> None:
    key_file.chmod(0o644)
    with pytest.raises(ValueError, match="chmod 600"):
        service_account.describe(_account(env))


def test_without_the_crypto_extra_the_error_names_it(
    env: dict[str, str], fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in [n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")]:
        monkeypatch.setitem(sys.modules, name, None)  # an import of any of them now fails, as uninstalled
    with pytest.raises(service_account.GoogleError, match=r"openlogbook\[crypto\]"):
        service_account.Session(_account(env), DRIVE_SCOPE).post_json(QUERY, {})
    with pytest.raises(ValueError, match=r"openlogbook\[crypto\]"):
        service_account.describe(_account(env))


def test_base64url_is_unpadded() -> None:
    assert service_account.b64url(b"\xff\xfe") == base64.urlsafe_b64encode(b"\xff\xfe").decode().rstrip("=")
