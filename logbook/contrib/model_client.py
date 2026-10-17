"""One small client for an OpenAI-compatible chat completions endpoint: the model `logbook dream`
sends a day to (RFC 0036). No SDK: the request is one JSON object over `urllib`, the answer one
JSON object back, so a cloud model today and a local `llama-server` tomorrow are the same three
variables and no code change.

- `LOGBOOK_DREAM_ENDPOINT`: the chat completions URL, e.g. `https://api.example.org/v1/chat/completions`
  or `http://127.0.0.1:8080/v1/chat/completions`. A URL that ends in `/v1` or has no path gets
  `/chat/completions` appended, so the base URL a server prints is enough.
- `LOGBOOK_DREAM_MODEL`: the model's name as the endpoint knows it (`gpt-4o-mini`,
  `qwen2.5-7b-instruct`); the `model` of the policy's `dream` entry wins when the entry names one.
- `LOGBOOK_DREAM_KEY`: the bearer token, optional; a local server needs none and gets no header.
- `LOGBOOK_DREAM_TEMPERATURE`: the request's temperature, a number from 0 to 2 sent as given; `none`
  sends no temperature at all, for a model that refuses one; unset, `TEMPERATURE`.

`complete` sends the messages once and, when the connection fails, times out or the server answers
5xx or 429, once more after a short pause; a 4xx is the request's fault and is said at once, a 400
about the temperature with what to set (it is never retried without one: the owner sets it). The
answer is the first choice's content. `send` is the one place a connection is opened; the tests
replace it with an in-process fake and never open one (`tests/test_dream.py`)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ENDPOINT_ENV = "LOGBOOK_DREAM_ENDPOINT"
MODEL_ENV = "LOGBOOK_DREAM_MODEL"
KEY_ENV = "LOGBOOK_DREAM_KEY"
TEMPERATURE_ENV = "LOGBOOK_DREAM_TEMPERATURE"
COMPLETIONS = "/chat/completions"
TIMEOUT_S = 120.0  # a local 7B model on a laptop takes a minute on a long day
RETRIES = 1  # one more try after a failure that is the network's or the server's
RETRY_PAUSE_S = 2.0
TEMPERATURE = 0.2  # unset LOGBOOK_DREAM_TEMPERATURE
MAX_TEMPERATURE = 2
NO_TEMPERATURE = "none"
TEMPERATURE_HINT = f"set {TEMPERATURE_ENV}={NO_TEMPERATURE} for a model that takes no temperature"
ERROR_BODY_LIMIT = 64 * 1024  # what of a refusal's body is read to see whether it is about the temperature
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ModelError(Exception):
    """The endpoint could not be reached, refused the request, or answered something that is not
    a completion; the message says which and names no key."""


@dataclass(frozen=True)
class Endpoint:
    url: str
    model: str
    key: str | None = None
    temperature: float | None = TEMPERATURE  # None: the request carries no temperature


def from_env(env: Mapping[str, str] | None = None, model: str | None = None) -> Endpoint:
    """The endpoint the variables describe; `model` (the policy's) wins over `LOGBOOK_DREAM_MODEL`.
    A missing URL or model is a `ModelError` naming the variable."""
    found = os.environ if env is None else env
    url = (found.get(ENDPOINT_ENV) or "").strip()
    if not url:
        raise ModelError(f"{ENDPOINT_ENV} is not set; it names the chat completions URL of the model")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ModelError(f"{ENDPOINT_ENV} is not an http(s) URL")
    name = (model or found.get(MODEL_ENV) or "").strip()
    if not name:
        raise ModelError(f"{MODEL_ENV} is not set and the policy names no model; one of them names the model")
    key = (found.get(KEY_ENV) or "").strip() or None
    return Endpoint(completions_url(url), name, key, temperature_of(found.get(TEMPERATURE_ENV)))


def temperature_of(value: str | None) -> float | None:
    """`LOGBOOK_DREAM_TEMPERATURE` read: unset or empty is `TEMPERATURE`, `none` is None (no field), a
    number from 0 to `MAX_TEMPERATURE` is itself (`0` stays an int, so it is sent as written); anything
    else is a `ModelError` naming the variable."""
    given = (value or "").strip()
    if not given:
        return TEMPERATURE
    if given.lower() == NO_TEMPERATURE:
        return None
    try:
        number: float = int(given)
    except ValueError:
        try:
            number = float(given)
        except ValueError:
            number = float("nan")
    if not 0 <= number <= MAX_TEMPERATURE:  # nan fails too
        raise ModelError(
            f"{TEMPERATURE_ENV} is {given!r}; it is a number from 0 to {MAX_TEMPERATURE}, or"
            f" {NO_TEMPERATURE!r} for a model that takes no temperature"
        )
    return number


def temperature_said(endpoint: Endpoint, env: Mapping[str, str]) -> str:
    """`0.2 (the default)`, `0.7 (LOGBOOK_DREAM_TEMPERATURE)`, or `none (…), the field is not sent`:
    what the request will carry, for doctor."""
    if endpoint.temperature is None:
        return f"{NO_TEMPERATURE} ({TEMPERATURE_ENV}), the field is not sent"
    whose = TEMPERATURE_ENV if (env.get(TEMPERATURE_ENV) or "").strip() else "the default"
    return f"{endpoint.temperature} ({whose})"


def request_body(endpoint: Endpoint, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """The chat completions request: the model, the messages and, unless it is `none`, the
    temperature."""
    body: dict[str, Any] = {"model": endpoint.model, "messages": list(messages)}
    if endpoint.temperature is not None:
        body["temperature"] = endpoint.temperature
    return body


def about_temperature(status: int, text: str) -> bool:
    """Whether a refusal is the model's objection to the temperature: a 400 whose message names it."""
    return status == 400 and "temperature" in text.lower()


def refusal_text(error: urllib.error.HTTPError) -> str:
    """The reason and the start of the body of a refusal, to look into; never said as it is."""
    try:
        raw = error.read(ERROR_BODY_LIMIT) if error.fp is not None else b""
    except (OSError, ValueError):
        raw = b""
    finally:
        error.close()
    return f"{error.reason} {raw.decode('utf-8', errors='replace')}"


def completions_url(url: str) -> str:
    """`https://host/v1` and `https://host` become `https://host/v1/chat/completions`; a URL that
    already ends in `/chat/completions` is kept."""
    bare = url.rstrip("/")
    if bare.endswith(COMPLETIONS):
        return bare
    if bare.endswith("/v1"):
        return bare + COMPLETIONS
    parts = urlsplit(bare)
    if parts.path in ("", "/"):
        return bare + "/v1" + COMPLETIONS
    return bare + COMPLETIONS


def send(url: str, body: dict[str, Any], headers: Mapping[str, str], timeout: float) -> dict[str, Any]:
    """POST `body` as JSON to `url`; the JSON answer. `urllib.error.HTTPError` for a status the
    server refused with, `OSError` (a `URLError`, a timeout) when it could not be reached."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    for name, value in headers.items():
        request.add_header(name, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    try:
        answer = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ModelError(f"the endpoint answered something that is not JSON: {e}") from e
    if not isinstance(answer, dict):
        raise ModelError("the endpoint answered JSON that is not an object")
    return answer


Transport = Callable[[str, dict[str, Any], Mapping[str, str], float], dict[str, Any]]


def complete(
    endpoint: Endpoint,
    messages: Sequence[Mapping[str, str]],
    timeout: float = TIMEOUT_S,
    transport: Transport | None = None,
    pause: Callable[[float], None] = time.sleep,
) -> str:
    """The model's answer to `messages` (`[{role, content}, ...]`), as text. One retry after a
    network failure, a timeout, a 429 or a 5xx; a 4xx is said at once."""
    body = request_body(endpoint, messages)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if endpoint.key:
        headers["Authorization"] = f"Bearer {endpoint.key}"
    post = transport if transport is not None else send
    attempt, last = 0, "no attempt was made"
    while attempt <= RETRIES:
        attempt += 1
        try:
            return content_of(post(endpoint.url, body, headers, timeout))
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUSES:
                hint = f"; {TEMPERATURE_HINT}" if about_temperature(e.code, refusal_text(e)) else ""
                raise ModelError(f"the endpoint refused the request: HTTP {e.code} {e.reason}{hint}") from e
            last = f"HTTP {e.code} {e.reason}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", None) or e
            last = f"{type(e).__name__}: {reason}"
        if attempt <= RETRIES:
            pause(RETRY_PAUSE_S)
    raise ModelError(f"the endpoint could not be reached in {attempt} attempts ({last}); nothing was written")


def content_of(answer: Mapping[str, Any]) -> str:
    """The first choice's content of a chat completion; `ModelError` when the answer has none."""
    error = answer.get("error")
    if isinstance(error, dict) and error.get("message"):
        raise ModelError(f"the endpoint answered an error: {error['message']}")
    choices = answer.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelError("the endpoint answered no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):  # a content array: the text parts joined
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ModelError("the endpoint answered an empty completion")
    return content
