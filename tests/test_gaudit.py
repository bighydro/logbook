"""`logbook sync gaudit`: the owner's own sign-ins from the Workspace's login audit log (Admin SDK Reports API
v1), one `event/v1` line (RFC 0009) per login event, read-only, with the service account the other Google
sources use. The address a sign-in came from is never in a line: only the place Google derived from it,
when the answer names one.

Against the in-process fake of `tests/google_fake.py`. The addresses are from the ranges reserved for
documentation (192.0.2.0/24, 2001:db8::/32); nobody here exists, and nothing leaves the process."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from google_fake import AUDIT_SCOPE, DRIVE_SCOPE, USER, Fake, private_key, write_key

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import gaudit, service_account
from logbook.core.store import Logbook

KEY_ENV, USER_ENV = service_account.KEY_ENV, service_account.USER_ENV
IPS = ("192.0.2.17", "2001:db8::17", "192.0.2.99")
OTHER = "ola@example.org"


def _activity(
    when: str, qualifier: str, ip: str, events: list[dict[str, Any]], **more: Any
) -> dict[str, Any]:
    return {
        "kind": "admin#reports#activity",
        "id": {
            "time": when,
            "uniqueQualifier": qualifier,
            "applicationName": "login",
            "customerId": "C0synth",
        },
        "actor": {"email": more.pop("email", USER), "profileId": "1000", "callerType": "USER"},
        "ipAddress": ip,
        "events": events,
        **more,
    }


def _event(name: str, *parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "login", "name": name, "parameters": list(parameters)}


def _logins() -> list[dict[str, Any]]:
    return [
        _activity(
            "2026-09-14T06:58:12.345Z",
            "-101",
            IPS[0],
            [
                _event(
                    "login_success",
                    {"name": "login_type", "value": "google_password"},
                    {"name": "login_challenge_method", "multiValue": ["password", "totp"]},
                    {"name": "is_suspicious", "boolValue": False},
                    {"name": "affected_email_address", "value": USER},
                )
            ],
            networkInfo={"ipAsn": [64500], "regionCode": "NO", "subdivisionCode": "NO-03", "city": "Oslo"},
        ),
        _activity(
            "2026-09-14T07:30:00Z",
            "-102",
            IPS[1],
            [
                _event(
                    "login_failure",
                    {"name": "login_type", "value": "google_password"},
                    {"name": "login_failure_type", "value": "login_failure_invalid_password"},
                )
            ],
            networkInfo={"ipAsn": [64501], "regionCode": "NO"},
        ),
        _activity(
            "2026-09-15T08:00:00Z",
            "-103",
            IPS[0],
            [
                _event("login_challenge", {"name": "login_challenge_status", "value": "Challenge Passed"}),
                _event("login_success", {"name": "login_type", "value": "google_password"}),
            ],
        ),
        _activity("2026-09-15T18:00:00Z", "-104", IPS[2], [_event("logout")]),
        _activity("2026-09-15T09:00:00Z", "-105", IPS[2], [_event("login_success")], email=OTHER),
    ]


KEYS = [
    "login:2026-09-14T06:58:12.345Z:-101:login_success",
    "login:2026-09-14T07:30:00Z:-102:login_failure",
    "login:2026-09-15T08:00:00Z:-103:login_challenge",
    "login:2026-09-15T08:00:00Z:-103:login_success",
    "login:2026-09-15T18:00:00Z:-104:logout",
]


@pytest.fixture(scope="module")
def key() -> Any:
    return private_key()


@pytest.fixture
def fake(tmp_path: Path, key: Any, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> Any:
    server = Fake(key, logins=_logins())
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


def _config() -> service_account.Account:
    account = gaudit.configure(os.environ)
    assert account is not None
    return account


def _pull(**kw: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    return list(gaudit.pull(_config(), counts=counts, timezone="Europe/Oslo", **kw)), counts


def _by(drafts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["payload"]["raw_id"]: d for d in drafts}


def _log_calls(fake: Fake) -> list[dict[str, Any]]:
    return fake.calls(f"admin.googleapis.com/admin/reports/v1/activity/users/{USER}/applications/login")


# -- registry ---------------------------------------------------------------------------------------


def test_registry_has_gaudit_as_a_live_adapter_on_the_one_key() -> None:
    assert adapters.live("gaudit") is gaudit
    assert gaudit.ENV == service_account.ENV and gaudit.configure is service_account.configure
    assert (gaudit.KIND, gaudit.TIER, gaudit.SCOPE) == ("event", 1, AUDIT_SCOPE)
    assert "gaudit" in service_account.SOURCES and service_account.SCOPES["gaudit"] == AUDIT_SCOPE


# -- the lines --------------------------------------------------------------------------------------


def test_pull_writes_one_event_per_login_event_oldest_first(fake: Fake) -> None:
    drafts, _ = _pull()
    assert [d["payload"]["raw_id"] for d in drafts] == KEYS, "two events of one activity are two lines"
    assert {(d["source"], d["kind"], d["tier"], d["tz"]) for d in drafts} == {
        ("gaudit", "event", 1, "Europe/Oslo")
    }, "RFC 0009's tier: where a line may travel, not who wrote it"
    assert [d["payload"]["title"] for d in drafts] == [
        "Signed in",
        "Sign-in failed",
        "Sign-in challenge",
        "Signed in",
        "Signed out",
    ]


def test_a_sign_in_has_the_time_the_app_and_the_place_google_derived(fake: Fake) -> None:
    line = _by(_pull()[0])[KEYS[0]]
    assert (line["at"], line["end"]) == ("2026-09-14T06:58:12.345Z", None)
    payload = line["payload"]
    assert payload["schema"] == "event/v1" and payload["all_day"] is False
    assert payload["calendar"] == {"id": "google-sign-in", "name": "Google sign-ins"}
    assert payload["location"] == "Oslo, NO-03, NO"
    assert payload["extra"] == {
        "app": "login",
        "event": "login_success",
        "country": "NO",
        "subdivision": "NO-03",
        "city": "Oslo",
        "login_type": "google_password",
        "login_challenge_method": ["password", "totp"],
        "is_suspicious": False,
    }, "only the parameters on the list: never an address of any kind"


def test_a_sign_in_without_a_city_says_what_the_answer_gives_and_no_more(fake: Fake) -> None:
    by = _by(_pull()[0])
    failed = by[KEYS[1]]["payload"]
    assert failed["location"] == "NO" and "city" not in failed["extra"]
    assert failed["extra"]["login_failure_type"] == "login_failure_invalid_password"
    assert "location" not in by[KEYS[4]]["payload"], "no place given, none written"


def test_the_raw_address_is_never_in_a_line_nor_its_digest(fake: Fake) -> None:
    text = json.dumps(_pull()[0])
    for ip in IPS:
        assert ip not in text
        assert hashlib.sha256(ip.encode()).hexdigest()[:12] not in text
    assert "64500" not in text and "ipAsn" not in text, "nor the network it came through"


def test_only_the_owners_own_sign_ins_are_asked_for(fake: Fake) -> None:
    drafts, _ = _pull()
    paths = {path for _m, path, _p in fake.requests if path.startswith("admin.googleapis.com")}
    assert paths == {f"admin.googleapis.com/admin/reports/v1/activity/users/{USER}/applications/login"}, (
        "the owner's address as the user key, never `all`"
    )
    assert not any("09:00:00" in d["at"] for d in drafts)


# -- the API: what is asked, paging, backoff ---------------------------------------------------------


def test_since_is_the_start_time_asked(fake: Fake) -> None:
    drafts, _ = _pull(since="2026-09-15T00:00:00Z")
    assert [d["payload"]["raw_id"] for d in drafts] == KEYS[2:]
    assert _log_calls(fake)[0]["startTime"] == "2026-09-15T00:00:00Z"


def test_pull_pages_until_the_last_page_and_reports_each(fake: Fake) -> None:
    fake.page = 2
    reported: list[int] = []
    drafts, _ = _pull(progress=lambda n, _s: reported.append(n))
    assert len(drafts) == 5
    assert [c.get("pageToken") for c in _log_calls(fake)] == [None, "2"] and reported == [2, 4]


def test_pull_backs_off_on_429_and_5xx_and_carries_on(fake: Fake) -> None:
    fake.fail(500)
    fake.fail(429, retry_after="3")
    drafts, _ = _pull()
    assert len(drafts) == 5 and fake.waits == [1.0, 3.0]  # type: ignore[attr-defined]


def test_the_client_only_reads(fake: Fake) -> None:
    _pull()
    assert fake.methods() == {("POST", "oauth2.googleapis.com"), ("GET", "admin.googleapis.com")}
    assert {c["scope"] for c in fake.assertions} == {AUDIT_SCOPE}


def test_watermark_is_the_sign_in_time_and_resume_looks_back_a_day(fake: Fake) -> None:
    by = _by(_pull()[0])
    assert gaudit.watermark(by[KEYS[0]]) == "2026-09-14T06:58:12Z", "whole seconds: marks compare as text"
    assert gaudit.resume(_config(), "2026-09-15T18:00:00Z") == "2026-09-14T18:00:00Z"
    assert gaudit.group(by[KEYS[1]]) == "Sign-in failed"


# -- sync: the CLI ----------------------------------------------------------------------------------


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "gaudit", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_sync_first_run_writes_every_sign_in_and_the_second_none(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "gaudit: 5 new lines of 5 seen from the beginning" in out
    assert "Signed in: 2 new of 2 seen" in out
    assert lb.verify()[2] == [] and lb.meta["seq"] == 5
    state = json.loads((lb.root / "state" / "gaudit.json").read_text(encoding="utf-8"))
    assert state["since"] == "2026-09-15T18:00:00Z"
    assert _sync() == 0
    assert "gaudit: 0 new lines of 3 seen since 2026-09-14T18:00:00Z (3 already in the record)" in (
        capsys.readouterr().out
    )
    assert lb.meta["seq"] == 5
    assert not any(ip in path.read_text(encoding="utf-8") for path in lb.root.rglob("*.jsonl") for ip in IPS)


def test_sync_since_is_used_as_given(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--since", "2026-09-15T12:00:00Z") == 0
    assert "gaudit: 1 new lines of 1 seen since 2026-09-15T12:00:00Z" in capsys.readouterr().out


def test_sync_dry_run_counts_and_writes_nothing(lb: Logbook, fake: Fake, capsys: Any) -> None:
    assert _sync("--dry-run") == 0
    assert "gaudit: 5 lines from the beginning (dry run, nothing written)" in capsys.readouterr().out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_without_the_audit_scope_delegated_is_one_line_and_exit_1(
    lb: Logbook, fake: Fake, capsys: Any
) -> None:
    fake.delegated = {DRIVE_SCOPE}
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: gaudit:") and AUDIT_SCOPE in err


def test_doctor_shows_sync_gaudit_and_asks_google_nothing(lb: Logbook, fake: Fake) -> None:
    checks = {c.name: c for c in doctor.run(lb, dict(os.environ), installed=lambda _m: True)}
    assert checks["sync:gaudit"].status == "pass"
    assert "gaudit" in checks["google"].detail
    assert fake.requests == []
