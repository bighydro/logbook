"""The one Google sign-in every Google source shares: one service account with domain-wide delegation.

The owner runs his own Google Workspace. A service account in its Cloud project, allowed by the Workspace
admin console to act as a user of the domain for named scopes (domain-wide delegation), reads that user's
mail, calendars, Drive activity and file metadata, tasks, Meet calls, sign-ins and contacts with no
browser, no consent screen and nothing that expires: each run signs a short assertion with the account's
key and trades it for an access token valid an hour, held in memory for that run and never written
anywhere. There is no refresh token to rot in a scheduled job, which is how an OAuth client signed in once
by hand ends (the token is revoked, expires unused, or is rotated out from under the job). What can stop
it is the owner: a key deleted, the delegation withdrawn, the user suspended.

The sources on the key (`SOURCES`), configured by the environment alone, in one place:

    LOGBOOK_DRIVE_SA_KEY   the key file, JSON, as the Cloud console downloads it (`~` is expanded)
    LOGBOOK_DRIVE_USER     the address of the user to read as: the owner

(The names say Drive because `sync drive` came first; every Google source reads the same two.)

The key is a password for everything the delegation grants. It stays outside the record and outside
any repository, at mode 600; `describe` (doctor's check) says when the file is readable by others. The
config's repr shows neither the path, the user nor the account, and no error echoes a value.

Each call asks for one scope, read-only, and nothing else (`SCOPES`): `gmail.readonly` for `sync gmail`,
`calendar.readonly` for `sync gcal`, `drive.activity.readonly` for `sync drive` and
`drive.metadata.readonly` for the folder paths its lines carry, `tasks.readonly` for `sync gtasks`,
`meetings.space.readonly` for `sync meet`, `admin.reports.audit.readonly` for `sync gaudit`, and
`contacts.readonly` and `contacts.other.readonly` for `people review --from-google`, which reads the
owner's contacts as names for the review and writes no line of them. A `Session` is one scope's calls, its
token minted on the first. A scope the delegation does not grant is Google's `unauthorized_client`, which
`ScopeRefused` turns into where to grant it.

Signing is RS256, PKCS#1 v1.5 over SHA-256, done by `cryptography` (the `crypto` extra, which the
encrypted iOS backup and the signed page already use); without it a run says which extra to install.

Every request goes through `send`, the only network call in this module and the sources on it, which
their `pull` alone reaches (ADR 0012). A 429, a 500, 502, 503 or 504, a 403 whose reason is a rate limit
and a lost connection are retried after a wait that doubles from one second (`Retry-After`, when the
server sends one, is honoured up to `BACKOFF_MAX_S`), `RETRIES` times; then the run stops with the last
error. A 401 mints the token again, once. Any other answer that is not a success is an `ApiError`
carrying the status and Google's reasons, so a source can tell a history too old to read (404) or a
start too long ago (410) from a failure. A session told not to wait (`wait_on_limits=False`, a dry run)
raises `LimitReached` on the first 429, rate-limit or quota 403 (`quotaExceeded`, `dailyLimitExceeded`) or
`RESOURCE_EXHAUSTED`, with Google's own words, and sleeps not at all. Tests put an in-process fake in place
of `send` and of `sleep`."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import LimitReached

__all__ = [
    "BACKOFF_MAX_S",
    "BACKOFF_S",
    "ENV",
    "GRANT",
    "KEY_ENV",
    "NAMES",
    "RETRIES",
    "SCOPES",
    "SOURCES",
    "TOKEN_URL",
    "USER_ENV",
    "Account",
    "ApiError",
    "GoogleError",
    "Response",
    "ScopeRefused",
    "Session",
    "configure",
    "describe",
    "is_address",
    "read_key",
]

KEY_ENV = "LOGBOOK_DRIVE_SA_KEY"
USER_ENV = "LOGBOOK_DRIVE_USER"
ENV = (KEY_ENV, USER_ENV)
SOURCES = (
    "gmail",
    "gcal",
    "drive",
    "gtasks",
    "meet",
    "gaudit",
)  # the sources on the key, in `sync --all`'s order
NAMES = ("contacts", "other contacts")  # what `people review --from-google` reads: names, never lines
AUTH = "https://www.googleapis.com/auth/"
SCOPES = {  # one read-only scope per call; what the Workspace's domain-wide delegation must grant
    "gmail": f"{AUTH}gmail.readonly",
    "gcal": f"{AUTH}calendar.readonly",
    "drive": f"{AUTH}drive.activity.readonly",
    "drive paths": f"{AUTH}drive.metadata.readonly",
    "gtasks": f"{AUTH}tasks.readonly",
    "meet": f"{AUTH}meetings.space.readonly",
    "gaudit": f"{AUTH}admin.reports.audit.readonly",
    "contacts": f"{AUTH}contacts.readonly",
    "other contacts": f"{AUTH}contacts.other.readonly",
}
TOKEN_URL = "https://oauth2.googleapis.com/token"
GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
LIFETIME_S = 3600  # the longest an assertion may ask for, and what the token then lasts
MARGIN_S = 300  # a token this close to its end is minted again before the next call
TIMEOUT_S = 60
RETRIES = 5  # after the first try: six tries in all
BACKOFF_S = 1.0  # the first wait; each next one doubles
BACKOFF_MAX_S = 64.0  # no wait is longer, whatever Retry-After says
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})  # a day's quota spent: never retried
EXTRA = 'pip install "openlogbook[crypto]"'
NO_CRYPTO = f"signing with the service-account key needs the crypto extra: {EXTRA}"
USER_AGENT = "logbook"


class GoogleError(OSError):
    """A call to Google that did not succeed, in words that carry no token, key or assertion. An OSError,
    so `sync` says it on one line and exits 1, as for any source that could not be reached."""


class ApiError(GoogleError):
    """An API's answer that was neither a success nor worth retrying, with its status and Google's
    reasons (`updatedMinTooLongAgo`, `notFound`), for a source that has something better to do with one
    than stop: a Gmail history id too old to read is a 404, a calendar's `updatedMin` too long ago a 410."""

    def __init__(self, message: str, status: int, reasons: frozenset[str] = frozenset()) -> None:
        super().__init__(message)
        self.status = status
        self.reasons = reasons


class ScopeRefused(GoogleError):
    """Google would not mint a token for the scope: the delegation does not grant it (`unauthorized_client`).
    The message says where to grant it; `scope` is the one refused, so a source that can do without it
    (the Drive folder paths) carries on."""

    def __init__(self, message: str, scope: str) -> None:
        super().__init__(message)
        self.scope = scope


@dataclass(frozen=True)
class Account:
    """The service account and the user it reads as. Nothing here is printed: the repr shows none of it."""

    key_file: Path = field(repr=False)
    client_email: str = field(repr=False)
    user: str = field(repr=False)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]  # names lower-cased
    body: bytes


def configure(env: Mapping[str, str]) -> Account | None:
    """The account from LOGBOOK_DRIVE_SA_KEY and LOGBOOK_DRIVE_USER; None until both are set. Raises
    ValueError, naming the variable and never its value, when the file is not there, is not JSON or is
    not a service-account key, or when the user is not an address."""
    raw_key = env.get(KEY_ENV, "").strip()
    user = env.get(USER_ENV, "").strip()
    if not raw_key or not user:
        return None
    path = Path(raw_key).expanduser()
    key = read_key(path)
    if not is_address(user):
        raise ValueError(f"{USER_ENV} must be the address of the Workspace user to read as (name@domain)")
    return Account(key_file=path, client_email=str(key["client_email"]), user=user)


def is_address(text: str) -> bool:
    """Whether the text reads as one address, `name@domain`."""
    local, at, domain = text.partition("@")
    return bool(at and local and domain) and "@" not in domain and not any(c.isspace() for c in text)


def read_key(path: Path) -> dict[str, Any]:
    """The key file's JSON, checked to be a service-account key; ValueError naming the variable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ValueError(f"{KEY_ENV} names no readable file") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(f"{KEY_ENV}: the file is not JSON") from None
    if (
        not isinstance(data, dict)
        or data.get("type") != "service_account"
        or not isinstance(data.get("client_email"), str)
        or not isinstance(data.get("private_key"), str)
    ):
        raise ValueError(
            f"{KEY_ENV}: the file is not a service-account key (IAM → Service accounts → the account →"
            " Keys → Add key → JSON)"
        )
    return data


def describe(account: Account) -> str:
    """Doctor's check, local only: the key file still reads, signing can load it, and no other user of
    this machine can read it. ValueError says what is wrong; nothing is sent anywhere."""
    key = read_key(account.key_file)
    with contextlib.suppress(OSError):
        if os.name == "posix" and stat.S_IMODE(account.key_file.stat().st_mode) & 0o077:
            raise ValueError("the key file is readable by other users of this machine: chmod 600 it")
    try:
        _private_key(str(key["private_key"]))
    except GoogleError as e:
        raise ValueError(str(e)) from None
    return "a service-account key; each run mints its own token, never stored"


def b64url(data: bytes) -> str:
    """Base64url without padding, as a JWT spells each part."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _private_key(pem: str) -> Any:
    """The key, loaded by `cryptography`; GoogleError naming the extra when it is not installed, or
    saying the key does not load (never its text)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        raise GoogleError(NO_CRYPTO) from None
    try:
        key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeEncodeError):
        raise GoogleError(f"{KEY_ENV}: the private key in the file does not load") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise GoogleError(f"{KEY_ENV}: the private key in the file is not an RSA key")
    return key


def assertion(account: Account, scope: str, now: float) -> str:
    """The signed JWT the token endpoint takes: the account asking, as the user, for one scope, for an
    hour from `now`."""
    key_data = read_key(account.key_file)
    key = _private_key(str(key_data["private_key"]))  # first: it names the extra when it is missing
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT"}
    if isinstance(key_data.get("private_key_id"), str):
        header["kid"] = key_data["private_key_id"]
    issued = int(now)
    claims = {
        "iss": account.client_email,
        "sub": account.user,
        "scope": scope,
        "aud": TOKEN_URL,
        "iat": issued,
        "exp": issued + LIFETIME_S,
    }
    signing_input = ".".join(
        b64url(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
    )
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{b64url(signature)}"


def send(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> Response:
    """One HTTP request, its status, headers and body whatever the status. The only network call of the
    Google sources. An unreachable host is an OSError (URLError is one)."""
    req = Request(url, data=body, headers={"User-Agent": USER_AGENT, **headers}, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            return Response(response.status, _lower(response.headers.items()), response.read())
    except HTTPError as e:
        with e:
            return Response(e.code, _lower(e.headers.items() if e.headers else ()), e.read())
    except URLError as e:
        raise OSError(str(e.reason)) from None


def _lower(items: Any) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in items}


sleep = time.sleep  # a test puts a recorder here
clock = time.time


class Session:
    """One run's calls to one Google API as the user, with one scope: the token minted on the first call
    and again when it nears its end or a call says it is no longer good."""

    def __init__(self, account: Account, scope: str, wait_on_limits: bool = True) -> None:
        self.account = account
        self.scope = scope
        self.wait_on_limits = wait_on_limits
        self._token: str | None = None
        self._expires = 0.0

    def get_json(self, url: str, params: Mapping[str, str]) -> dict[str, Any]:
        query = urlencode([(k, v) for k, v in params.items() if v is not None])
        return self._call("GET", f"{url}?{query}" if query else url, None)

    def post_json(self, url: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", url, json.dumps(body, separators=(",", ":")).encode("utf-8"))

    def _call(self, method: str, url: str, body: bytes | None) -> dict[str, Any]:
        reminted = False
        tries = 0
        while True:
            headers = {"Authorization": f"Bearer {self._bearer()}", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            response, problem = _attempt(method, url, headers, body)
            tries += 1
            if response is not None and response.status == 401 and not reminted:
                self._token, reminted = None, True  # Google no longer takes it: mint another, once
                tries -= 1
                continue
            if response is not None and 200 <= response.status < 300:
                return _parse(response)
            if response is not None and not self.wait_on_limits and _limited(response):
                raise LimitReached(_api_error(response))
            if response is not None and not _retryable(response):
                raise ApiError(_api_error(response), response.status, frozenset(_reasons(response)))
            if response is not None:
                problem = _api_error(response)
            if tries > RETRIES:
                raise GoogleError(f"{problem} (gave up after {tries} tries)")
            sleep(_wait(response, tries - 1))

    def _bearer(self) -> str:
        if self._token is None or clock() > self._expires - MARGIN_S:
            self._token, self._expires = self._mint()
        return self._token

    def _mint(self) -> tuple[str, float]:
        now = clock()
        form = urlencode({"grant_type": GRANT, "assertion": assertion(self.account, self.scope, now)})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        tries = 0
        while True:
            response, problem = _attempt("POST", TOKEN_URL, headers, form.encode("ascii"))
            tries += 1
            if response is not None and response.status == 200:
                data = _parse(response)
                token = data.get("access_token")
                if not isinstance(token, str) or not token:
                    raise GoogleError("the token endpoint answered without a token")
                lifetime = data.get("expires_in")
                return token, now + (float(lifetime) if isinstance(lifetime, int | float) else LIFETIME_S)
            if response is not None and response.status == 429 and not self.wait_on_limits:
                raise LimitReached("token endpoint: HTTP 429")
            if response is not None and response.status not in RETRY_STATUS:
                message, refused = self._refused(response)
                raise ScopeRefused(message, self.scope) if refused else GoogleError(message)
            if response is not None:
                problem = f"token endpoint: HTTP {response.status}"
            if tries > RETRIES:
                raise GoogleError(f"{problem} (gave up after {tries} tries)")
            sleep(_wait(response, tries - 1))

    def _refused(self, response: Response) -> tuple[str, bool]:
        """Why Google would not mint a token, with what to do about it, and whether it is the scope."""
        try:
            data = json.loads(response.body)
        except ValueError:
            data = {}
        error = str(data.get("error") or f"HTTP {response.status}") if isinstance(data, dict) else ""
        if error == "unauthorized_client":
            return (
                f"Google refused the service account (unauthorized_client): domain-wide delegation does not"
                f" grant {self.scope} to this key's client id; add it in the Workspace admin console,"
                " Security → Access and data control → API controls → Domain-wide delegation"
            ), True
        if error == "invalid_grant":
            return (
                "Google refused the service account (invalid_grant): the key may be deleted or disabled, the"
                f" clock of this machine wrong, or {USER_ENV} not a user of the domain"
            ), False
        return f"Google refused the service account ({error})", False


def _attempt(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[Response | None, str]:
    """One try: the response, or None and why there was none (a lost connection, a timeout)."""
    try:
        return send(method, url, headers, body, TIMEOUT_S), ""
    except (OSError, TimeoutError) as e:
        return None, f"connection: {e}"


def _retryable(response: Response) -> bool:
    if response.status in RETRY_STATUS:
        return True
    return response.status == 403 and bool(_reasons(response) & RATE_REASONS)


def _limited(response: Response) -> bool:
    """A quota or rate-limit answer: a 429, or a 403 whose reason is a rate limit or a spent quota
    (`RESOURCE_EXHAUSTED` counts as a rate limit, `_reasons`)."""
    if response.status == 429:
        return True
    return response.status == 403 and bool(_reasons(response) & (RATE_REASONS | QUOTA_REASONS))


def _wait(response: Response | None, retry: int) -> float:
    """How long to wait before retry number `retry` (0 for the first): Retry-After when the server says,
    else a second doubling each time; never above BACKOFF_MAX_S."""
    wait = BACKOFF_S * 2.0**retry
    if response is not None:
        given = response.headers.get("retry-after", "").strip()
        if given.isdigit():
            wait = float(given)
    return min(wait, BACKOFF_MAX_S)


def _reasons(response: Response) -> set[str]:
    error = _error_object(response)
    found = {str(e.get("reason")) for e in error.get("errors") or [] if isinstance(e, dict)}
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            found.add(str(detail["reason"]))
    if error.get("status") == "RESOURCE_EXHAUSTED":
        found.add("rateLimitExceeded")
    return found


def _error_object(response: Response) -> dict[str, Any]:
    try:
        data = json.loads(response.body)
    except ValueError:
        return {}
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, dict) else {}


def _api_error(response: Response) -> str:
    """`HTTP 403: <Google's message>`, the message cut to one line of reasonable length."""
    message = " ".join(str(_error_object(response).get("message") or "").split())[:300]
    return f"HTTP {response.status}" + (f": {message}" if message else "")


def _parse(response: Response) -> dict[str, Any]:
    try:
        data = json.loads(response.body)
    except ValueError:
        raise GoogleError(f"HTTP {response.status}: the answer is not JSON") from None
    if not isinstance(data, dict):
        raise GoogleError(f"HTTP {response.status}: the answer is not a JSON object")
    return data
