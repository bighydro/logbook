"""`LOGBOOK_DREAM_TEMPERATURE`: the temperature the dream's request carries. Unset, it is 0.2 as it always
was; a number between 0 and 2 is sent as given; `none` sends no temperature at all, for a model that
refuses one. The requests go to a fake chat completions endpoint on 127.0.0.1 in this process; the model
name and the key are synthetic."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import model_client, packet
from logbook.core import policy
from logbook.core.store import Logbook

MODEL = "example-model-1"
KEY = "sentinel-dream-value"
PROMPT = "a synthetic prompt about the ferry to Nesodden"
ANSWER = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ready"}}]}).encode()
REFUSED = json.dumps(
    {
        "error": {
            "message": "`temperature` is deprecated for this model.",
            "type": "invalid_request_error",
            "param": "temperature",
        }
    }
).encode()
PROXIES = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")


@pytest.fixture(autouse=True)
def _direct(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROXIES:  # the fake endpoint is reached directly
        monkeypatch.delenv(name, raising=False)


@contextmanager
def _endpoint(status: int, body: bytes) -> Iterator[tuple[int, list[bytes]]]:
    """A chat completions endpoint on 127.0.0.1 that answers every POST with `status` and `body`, and
    keeps the bytes it was sent."""
    seen: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            seen.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
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


def _env(port: int, **more: str) -> dict[str, str]:
    return {
        model_client.ENDPOINT_ENV: f"http://127.0.0.1:{port}/v1",
        model_client.MODEL_ENV: MODEL,
        model_client.KEY_ENV: KEY,
        **more,
    }


def _ask(env: dict[str, str]) -> str:
    return model_client.complete(
        model_client.from_env(env), [{"role": "user", "content": PROMPT}], pause=lambda _s: None
    )


def test_unset_sends_0_2_byte_for_byte_as_before() -> None:
    with _endpoint(200, ANSWER) as (port, seen):
        assert _ask(_env(port)) == "ready"
    today = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "temperature": 0.2}
    assert seen == [json.dumps(today).encode("utf-8")]


def test_a_number_is_sent_as_given() -> None:
    with _endpoint(200, ANSWER) as (port, seen):
        _ask(_env(port, LOGBOOK_DREAM_TEMPERATURE="0"))
        _ask(_env(port, LOGBOOK_DREAM_TEMPERATURE="1.5"))
    assert [json.loads(sent)["temperature"] for sent in seen] == [0, 1.5]


def test_none_sends_no_temperature_at_all() -> None:
    with _endpoint(200, ANSWER) as (port, seen):
        assert _ask(_env(port, LOGBOOK_DREAM_TEMPERATURE="none")) == "ready"
    [sent] = seen
    assert "temperature" not in json.loads(sent)


@pytest.mark.parametrize("value", ["hot", "3", "-0.1", "nan"])
def test_anything_else_is_an_error_naming_the_variable(value: str) -> None:
    with pytest.raises(model_client.ModelError, match=model_client.TEMPERATURE_ENV):
        model_client.from_env(_env(1, LOGBOOK_DREAM_TEMPERATURE=value))


def test_a_400_about_temperature_says_what_to_set_and_is_not_retried() -> None:
    with _endpoint(400, REFUSED) as (port, seen), pytest.raises(model_client.ModelError) as caught:
        _ask(_env(port))
    message = str(caught.value)
    assert "HTTP 400" in message
    assert "set LOGBOOK_DREAM_TEMPERATURE=none for a model that takes no temperature" in message
    assert len(seen) == 1, "no retry without temperature: the owner sets it"
    assert KEY not in message and PROMPT not in message and "deprecated" not in message


def test_a_400_about_something_else_says_nothing_of_temperature() -> None:
    other = json.dumps({"error": {"message": "unknown model", "type": "invalid_request_error"}}).encode()
    with _endpoint(400, other) as (port, _seen), pytest.raises(model_client.ModelError) as caught:
        _ask(_env(port))
    assert "HTTP 400" in str(caught.value) and model_client.TEMPERATURE_ENV not in str(caught.value)


def _dreaming(tmp_path: Path) -> Logbook:
    """A record whose policy has the `dream` entry the packet's probe needs (S8)."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    data = policy.read(lb.root)
    data[policy.DREAM_DESTINATION] = {"max_tier": 2, "until": "2099-12-31"}
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")
    return lb


@pytest.mark.parametrize(
    ("value", "sent", "said"),
    [
        (None, 0.2, "temperature: 0.2 (the default)"),
        ("0.7", 0.7, "temperature: 0.7 (LOGBOOK_DREAM_TEMPERATURE)"),
        ("none", None, "temperature: none (LOGBOOK_DREAM_TEMPERATURE), the field is not sent"),
    ],
)
def test_the_packet_probe_follows_the_variable_and_names_it(
    value: str | None, sent: float | None, said: str, tmp_path: Path
) -> None:
    with _endpoint(200, ANSWER) as (port, seen):
        env = _env(port) if value is None else _env(port, LOGBOOK_DREAM_TEMPERATURE=value)
        text = packet.build(_dreaming(tmp_path), env)
    assert said in text
    [body] = seen
    assert json.loads(body).get("temperature") == sent
    assert ("temperature" in json.loads(body)) == (sent is not None)


def test_the_packet_says_what_to_set_when_the_probe_is_refused_over_temperature(tmp_path: Path) -> None:
    with _endpoint(400, REFUSED) as (port, _seen):
        text = packet.build(_dreaming(tmp_path), _env(port))
    assert "reply: HTTP 400 Bad Request" in text
    assert "set LOGBOOK_DREAM_TEMPERATURE=none for a model that takes no temperature" in text


def test_a_temperature_the_packet_cannot_read_is_said_and_nothing_is_asked() -> None:
    with _endpoint(200, ANSWER) as (port, seen):
        text = packet.build(None, _env(port, LOGBOOK_DREAM_TEMPERATURE="hot"))
    assert model_client.TEMPERATURE_ENV in text and "nothing was asked" in text and seen == []
