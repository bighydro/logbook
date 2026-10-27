"""`logbook doctor --packet`: the diagnostic the owner hands a collaborator, on a synthetic record of
the Oslo persona, who does not exist. Every value an environment variable holds is a sentinel the
packet must never show; the owner's names, address and number come from `policy/owner.json` and must
come out as `[owner]`; the logs name the home directory, which must come out as `~`. The one request
the packet makes, the dream endpoint's probe, goes to a fake endpoint on 127.0.0.1 in this process."""

from __future__ import annotations

import json
import re
import socket
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from logbook import __version__, cli
from logbook.contrib import last_run, packet, schedule, service
from logbook.core import policy
from logbook.core.store import Logbook

OWNER = {
    "names": ["Ines Nordmann", "@inesn"],
    "emails": ["ines.nordmann@example.org"],
    "phones": ["+44 7700 900461"],
}
PLACES = {"Storgata 1": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}
NOTE = "a synthetic note about the sauna on the fjord"
MESSAGE = "a synthetic message: the ferry leaves at eight"
SECRET = "sentinel-immich-value"
DREAM_KEY = "sentinel-dream-value"
MODEL = "qwen2.5-7b-instruct"
HOST = "ines-macbook-pro.local"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
PROXIES = ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")  # the fake endpoint is reached directly


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """A record with a note, a message and a location; the owner's aliases and home place; a watermark
    for immich and a resume state for mail; a scheduled run in which mail failed."""
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    for name in PROXIES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(packet, "hostname", lambda: HOST)
    monkeypatch.setattr(packet, "login_name", lambda: "ines")
    monkeypatch.setattr(packet, "run_command", lambda args: pytest.fail(f"not asked here: {args}"))
    monkeypatch.setattr(last_run, "now", lambda: NOW)
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append("2026-10-12T06:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": NOTE})
    lb.append(
        "2026-10-12T07:00:00Z",
        "imessage",
        "message",
        2,
        {
            "schema": "message/v1",
            "chat": {"type": "direct", "id": "chat-1", "name": "Kari"},
            "sender": {"kind": "phone", "value": "+4790000002"},
            "from_me": False,
            "text": MESSAGE,
            "raw_id": "msg:1",
        },
    )
    lb.append(
        "2026-10-12T08:00:00Z",
        "dawarich",
        "location",
        1,
        {"schema": "location/v1", "lat": 59.9139, "lon": 10.7522, "raw_id": "dawarich:1"},
    )
    _write(root / "policy" / "owner.json", OWNER)
    _write(root / "places.json", PLACES)
    _write(root / "state" / "immich.json", {"since": "2026-10-12T21:14:03.123Z"})
    _write(root / "state" / "mail.json", {"resume": {"checkpoint": {"folders": {"INBOX": {"uid": 4312}}}}})
    sources = (last_run.Source("immich", "ok", 12), last_run.Source("mail", "failed (status 1)", 0))
    report = last_run.Doctor(14, ("sync:mail",), ())
    run = last_run.Run(NOW - timedelta(hours=3), sources, report, "mail  failed (status 1)")
    last_run.write(root, last_run.State(run, (), None))
    _dream(lb, {"max_tier": 2, "until": "2099-12-31"})  # the owner's leave to send the probe (S8)
    return lb


def _dream(lb: Logbook, entry: dict[str, Any] | None) -> None:
    """The record's `dream` entry, or none."""
    data = policy.read(lb.root)
    data.pop(policy.DREAM_DESTINATION, None)
    if entry is not None:
        data[policy.DREAM_DESTINATION] = entry
    _write(policy.policy_path(lb.root), data)


def _env(**more: str) -> dict[str, str]:
    return {"LOGBOOK_IMMICH_URL": "https://photos.example.org", "LOGBOOK_IMMICH_KEY": SECRET, **more}


def _sync_log(lb: Logbook) -> list[str]:
    """What launchd's log of the schedule holds on a Mac: 45 lines, the last 40 of them in the packet."""
    home = Path.home()
    return [
        *(f"early line {n}" for n in range(5)),
        *(f"middle line {n}" for n in range(30)),
        f"immich: 12 new lines; watermark 2026-10-12 in {lb.root / 'state' / 'immich.json'}",
        f"mail: could not read {home / 'Mail' / 'export.mbox'}: permission denied",
        "mail: login refused for ines.nordmann@example.org (Ines Nordmann, @inesn)",
        "notify: the callback number 07700900461 is not a Telegram chat",
        f"immich: GET https://photos.example.org/api/assets x-api-key={SECRET} answered 401",
        f"launchd: running on {HOST} as ines",
        "pass  places      1 place(s), home: Storgata 1",
        f"{home.as_posix()}/.config/logbook/sync.env read",
        "warn  sync:mail   set LOGBOOK_IMAP_HOST and LOGBOOK_IMAP_USER and LOGBOOK_IMAP_PASSWORD",
        "10 checks: 9 pass, 1 warn, 0 fail",
    ]


def _darwin_logs(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "darwin")
    monkeypatch.setattr(service, "system", lambda: "darwin")
    logs = Path.home() / "Library" / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "logbook-sync.log").write_bytes(("\n".join(_sync_log(lb)) + "\n").encode("utf-8"))
    serve_log = [f"serving {lb.root} at http://127.0.0.1:8765/", "GET /today 200"]
    (logs / "logbook-serve.log").write_bytes(("\n".join(serve_log) + "\n").encode("utf-8"))


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    try:
        cli.main(["doctor", "--packet", *args])
    except SystemExit as e:
        return int(e.code or 0), capsys.readouterr().out
    return 0, capsys.readouterr().out


def _absent(text: str, *needles: str) -> None:
    """Each needle is nowhere in `text`, in any case, as a word or inside one."""
    for needle in needles:
        assert needle.casefold() not in text.casefold(), needle


# -- nothing personal ------------------------------------------------------------------------------------


def test_the_packet_holds_no_line_text_no_owner_no_path_and_no_secret(
    lb: Logbook, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _darwin_logs(lb, monkeypatch)
    for name, value in _env(LOGBOOK_IMAP_PASSWORD="sentinel-imap-password").items():
        monkeypatch.setenv(name, value)
    status, out = _cli(capsys)
    assert status == 0, out
    _absent(out, NOTE, MESSAGE, "sauna", "ferry", "Kari", "59.9139", "+4790000002")  # the lines
    _absent(out, "Nordmann", "inesn", "ines.nordmann@example.org", "900461", "900 461")  # the owner
    assert re.search(r"\bines\b", out, re.IGNORECASE) is None, "the owner's first name, or login"
    _absent(out, SECRET, "sentinel-imap-password", "photos.example.org")  # the values of variables
    _absent(out, str(Path.home()), Path.home().as_posix(), str(lb.root), lb.root.as_posix())  # paths
    _absent(out, HOST, "macbook", "Storgata")
    assert "[owner]" in out and "[host]" in out and "[place]" in out
    assert str(Path("~") / "Mail" / "export.mbox") in out and "~/.config/logbook/sync.env" in out
    assert str(Path("[record]") / "state" / "immich.json") in out
    assert "x-api-key=[LOGBOOK_IMMICH_KEY]" in out
    for name in ("LOGBOOK_IMMICH_URL", "LOGBOOK_IMMICH_KEY", "LOGBOOK_IMAP_PASSWORD", "LOGBOOK_HOME"):
        assert name in out, name


def test_the_packet_names_the_machine_the_record_and_the_sources(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _darwin_logs(lb, monkeypatch)
    monkeypatch.setattr(packet, "ram_bytes", lambda: 16 * 1024**3)
    text = packet.build(lb, _env())
    meta = lb.meta
    assert f"openlogbook: {__version__}" in text
    assert "ram: 16.0 GiB" in text
    assert re.search(r"^python: 3\.\d+\.\d+", text, re.MULTILINE)
    assert re.search(r"^extras: ", text, re.MULTILINE)
    assert f"lines: {meta['seq']}" in text and f"head: {meta['head']}" in text
    assert re.search(r"^immich: configured; last run ok, 12 lines; watermark 2026-10-12$", text, re.MULTILINE)
    mail = re.search(r"^mail: .*$", text, re.MULTILINE)
    assert mail is not None and "failed (status 1)" in mail.group(0) and "no watermark date" in mail.group(0)
    assert "set LOGBOOK_IMAP_HOST" in mail.group(0)
    assert "last run: 2026-10-13 06:00 UTC (3 h ago): immich 12 lines; mail failed" in text
    assert "doctor 14 pass, 1 warn, 0 fail; warned: sync:mail" in text


def test_the_logs_are_their_last_40_lines(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _darwin_logs(lb, monkeypatch)
    text = packet.build(lb, _env())
    assert "early line 4" not in text and "middle line 0" in text
    assert "10 checks: 9 pass, 1 warn, 0 fail" in text
    assert "## sync log, the last 40 lines (~/Library/Logs/logbook-sync.log)" in text
    assert "## service log, the last 40 lines (~/Library/Logs/logbook-serve.log)" in text
    assert "serving [record] at http://127.0.0.1:8765/" in text


def test_the_journal_is_read_on_linux_for_what_is_installed(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "linux")
    monkeypatch.setattr(service, "system", lambda: "linux")
    schedule.install(schedule.plan("linux", Path.home(), "/opt/py"), lambda _text: None)
    asked: list[Sequence[str]] = []

    def journal(args: Sequence[str]) -> str:
        asked.append(list(args))
        return f"2026-10-13T06:00:02+0200 {HOST} python3[812]: reading {Path.home() / 'Logbook'}\n"

    monkeypatch.setattr(packet, "run_command", journal)
    text = packet.build(lb, _env())
    assert asked == [
        [
            "journalctl",
            "--user",
            "-u",
            "logbook-sync.service",
            "-u",
            "logbook-sync-close.service",
            "-n",
            "40",
            "--no-pager",
            "-o",
            "short-iso",
        ]
    ], "the serve service is not installed, so its journal is not read"
    assert f"[host] python3[812]: reading {Path('~') / 'Logbook'}" in text
    assert "schedule: installed for the user (systemd user timers)" in text
    assert "no serve service on this machine" in text


def test_a_name_part_an_email_and_a_number_in_another_format_are_the_owner(lb: Logbook) -> None:
    scrub = packet.scrubber(lb, {})
    assert scrub("from INES NORDMANN <Ines.Nordmann@Example.org>") == "from [owner] <[owner]>"
    assert scrub("Nordmann, Ines (@inesn)") == "[owner], [owner] ([owner])"
    assert (
        scrub("call +447700900461, 07700 900461 or (+44) 7700-900-461") == "call [owner], [owner] or ([owner]"
    )
    assert scrub("lines 3, seq 12345678") == "lines 3, seq 12345678", "other numbers stay"
    assert scrub("Inesfjord and Nordmannsvei") == "Inesfjord and Nordmannsvei", "only whole words"


def test_a_one_letter_alias_or_owner_emails_written_as_one_string_replaces_no_letter(lb: Logbook) -> None:
    _write(lb.root / "policy" / "owner.json", {"names": ["I", "Ines Nordmann"], "emails": [], "phones": []})
    meta = json.loads((lb.root / "logbook.json").read_text(encoding="utf-8"))
    meta["owner_emails"] = "ines.nordmann@example.org"  # a string where a list belongs
    _write(lb.root / "logbook.json", meta)
    scrub = packet.scrubber(lb, {})
    assert scrub("mail: login refused, I said, for ines.nordmann@example.org") == (
        "mail: login refused, I said, for [owner]"
    )


def test_a_broken_owner_file_is_said_in_the_packet(lb: Logbook) -> None:
    (lb.root / "policy" / "owner.json").write_text("{", encoding="utf-8")
    text = packet.build(lb, _env())
    assert "policy/owner.json could not be read" in text


# -- the dream endpoint ----------------------------------------------------------------------------------


@contextmanager
def _endpoint(status: int, body: bytes) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """A chat completions endpoint on 127.0.0.1 that answers every POST with `status` and `body`, and
    keeps what it was sent."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            sent = json.loads(self.rfile.read(length).decode("utf-8"))
            seen.append({"path": self.path, "headers": dict(self.headers.items()), "body": sent})
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1]), seen
    finally:
        server.shutdown()
        server.server_close()


ERROR = (
    b'{\n  "error": {\n    "code": 500,\n    "message": "llama_model_load: failed to allocate 4.2 GiB'
    b' for the KV cache",\n    "type": "server_error"\n  }\n}'
)


def test_the_probe_of_an_endpoint_answering_500_lands_in_the_packet_verbatim(lb: Logbook) -> None:
    with _endpoint(500, ERROR) as (port, seen):
        env = _env(
            LOGBOOK_DREAM_ENDPOINT=f"http://127.0.0.1:{port}/v1",
            LOGBOOK_DREAM_MODEL=MODEL,
            LOGBOOK_DREAM_KEY=DREAM_KEY,
        )
        text = packet.build(lb, env)
    assert f"endpoint: 127.0.0.1:{port} (http)" in text
    assert f"model: {MODEL}" in text
    assert "reply: HTTP 500 Internal Server Error" in text
    assert f"\n{ERROR.decode('utf-8')}\n" in text, "the body as it came, every line"
    _absent(text, DREAM_KEY, SECRET)
    [request] = seen
    assert request["path"] == "/v1/chat/completions"
    assert request["body"]["model"] == MODEL
    assert request["body"]["messages"] == [{"role": "user", "content": "Reply with the single word ready."}]
    assert request["headers"]["Authorization"] == f"Bearer {DREAM_KEY}"
    _absent(json.dumps(request["body"]), NOTE, MESSAGE, "Ines")


def test_a_probe_answered_200_shows_the_reply(lb: Logbook) -> None:
    answer = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ready"}}]}).encode()
    with _endpoint(200, answer) as (port, seen):
        text = packet.build(
            lb, _env(LOGBOOK_DREAM_ENDPOINT=f"http://127.0.0.1:{port}", LOGBOOK_DREAM_MODEL=MODEL)
        )
    assert "reply: HTTP 200 OK" in text and answer.decode("utf-8") in text
    assert len(seen) == 1 and "Authorization" not in seen[0]["headers"], "no key, no header"


def test_an_endpoint_nothing_answers_is_said(lb: Logbook) -> None:
    with socket.socket() as s:  # a port that was free a moment ago, and is closed now
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    text = packet.build(
        lb, _env(LOGBOOK_DREAM_ENDPOINT=f"http://127.0.0.1:{port}/v1", LOGBOOK_DREAM_MODEL=MODEL)
    )
    assert "reply: none, " in text


def test_nothing_is_fetched_when_no_endpoint_is_configured(
    lb: Logbook,
    no_network: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the endpoint, and not the serve service's port either: `doctor` asks whether a server
    answers there, the packet does not."""
    monkeypatch.setattr(schedule, "system", lambda: "linux")
    monkeypatch.setattr(service, "system", lambda: "linux")
    svc = service.plan("linux", Path.home(), "/opt/py")
    [unit] = svc.plan.files.values()
    svc.path.parent.mkdir(parents=True, exist_ok=True)
    svc.path.write_text(unit, encoding="utf-8")
    monkeypatch.setattr(packet, "run_command", lambda args: "")
    status, out = _cli(capsys)
    assert status == 0, out
    assert no_network == []
    assert "endpoint: not configured (LOGBOOK_DREAM_ENDPOINT is not set); nothing was asked" in out
    assert "serve: systemd user service on port 8765" in out


def test_an_endpoint_without_a_model_is_not_asked(lb: Logbook, no_network: list[str]) -> None:
    text = packet.build(lb, _env(LOGBOOK_DREAM_ENDPOINT="http://127.0.0.1:8080/v1"))
    assert no_network == []
    assert "LOGBOOK_DREAM_MODEL is not set" in text and "nothing was asked" in text


# -- the command -----------------------------------------------------------------------------------------


def test_out_writes_the_packet_to_a_file(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "win32")
    monkeypatch.setattr(service, "system", lambda: "win32")
    out = tmp_path / "packet.txt"
    status, said = _cli(capsys, "--out", str(out))
    assert status == 0
    data = out.read_bytes()
    assert b"\r\n" not in data
    text = data.decode("utf-8")
    assert text.startswith("logbook diagnostic packet\n")
    assert f"lines: {lb.meta['seq']}" in text
    assert said.startswith(f"wrote {out}: ") and "read it before you send it" in said


def test_the_packet_without_a_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "nowhere"))
    monkeypatch.setattr(schedule, "system", lambda: "win32")
    monkeypatch.setattr(service, "system", lambda: "win32")
    status, out = _cli(capsys)
    assert status == 0, out
    assert "record: none found" in out
    assert f"openlogbook: {__version__}" in out


def test_out_without_packet_is_refused(
    lb: Logbook, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["doctor", "--out", str(tmp_path / "p.txt")])
    assert e.value.code == 2
    assert not (tmp_path / "p.txt").exists()


@pytest.mark.parametrize(
    ("entry", "why"),
    [(None, "names no 'dream' entry"), ({"max_tier": 2, "until": "2026-01-31"}, "expired on 2026-01-31")],
    ids=["no-entry", "expired"],
)
def test_without_the_dream_entry_the_probe_is_never_sent(
    lb: Logbook, entry: dict[str, Any] | None, why: str
) -> None:
    """The probe carries the bearer key to the endpoint, a crossing like the dream's own (S8): with
    no `dream` entry, or one that has expired, it is not sent, and one line says why."""
    _dream(lb, entry)
    with _endpoint(200, b"{}") as (port, seen):
        text = packet.build(
            lb,
            _env(
                LOGBOOK_DREAM_ENDPOINT=f"http://127.0.0.1:{port}/v1",
                LOGBOOK_DREAM_MODEL=MODEL,
                LOGBOOK_DREAM_KEY=DREAM_KEY,
            ),
        )
    assert seen == [], "nothing was sent"
    [said] = [line for line in text.splitlines() if line.startswith("probe:")]
    assert "not sent" in said and why in said and "crossing.json" in said, said
    assert "reply:" not in text
    _absent(text, DREAM_KEY)


def test_when_the_entry_s_model_and_the_variable_disagree_the_probe_is_never_sent(lb: Logbook) -> None:
    _dream(lb, {"max_tier": 2, "until": "2099-12-31", "model": "another-model"})
    with _endpoint(200, b"{}") as (port, seen):
        text = packet.build(
            lb,
            _env(
                LOGBOOK_DREAM_ENDPOINT=f"http://127.0.0.1:{port}/v1",
                LOGBOOK_DREAM_MODEL=MODEL,
                LOGBOOK_DREAM_KEY=DREAM_KEY,
            ),
        )
    assert seen == [] and "probe: not sent" in text and "key: LOGBOOK_DREAM_KEY set, not sent" in text
