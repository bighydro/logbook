"""`logbook doctor --packet [--out FILE]`: what the owner hands a collaborator when something fails — the
dream's model endpoint answering 500, a sync adapter, the schedule, the service — with no record content
in it, no name, no path that says whose machine it is and no secret (docs/doctor.md, "Sending a
diagnostic"). Plain text, one section after another:

- `machine`: the OS and its version, the platform string, the architecture, the RAM, Python, openlogbook
  and the extras installed, with the version of each package that makes one.
- `record`: the line count and the head as `logbook.json` names them (the head is a hash, not a line),
  the format, where the day begins and whether `index.sqlite` is current. No line is read.
- `sources`: each live source the record uses (doctor's `sync:` lines) or the last scheduled run
  listed: configured, or the variables it lacks by name; the last run's result and lines; and the date
  of its watermark in `state/<name>.json`, the date alone, never the value it was read from.
- `schedule and service`: which installs of the schedule this machine has, the last scheduled run
  (`state/last-run.json`: when, the lines per source, the sources that failed, the doctor's counts and
  the names of the checks that warned or failed), and the serve services with their ports. Whether a
  server answers there is not asked: that is a request, and the packet makes one only.
- `dream endpoint`: the host and port, the model, the policy's dream entry, and one request, the probe:
  the dream's own request (`model_client`; the key as its bearer token when `LOGBOOK_DREAM_KEY` is set)
  with the fixed prompt `PROMPT` where a day would be, and the reply's HTTP status and body as they came
  (up to `BODY_LIMIT` bytes): a model's error is not the record's content. Made only when
  `LOGBOOK_DREAM_ENDPOINT` is set and a model is named; it is the packet's one network call, and is never
  retried.
- `environment`: the names of the variables set that logbook reads — every `LOGBOOK_*`, the proxies, the
  config and cache folders — never a value.
- the logs: the last `LOG_LINES` lines of the schedule's and of the service's output, from
  `~/Library/Logs/` on macOS, from the journal on Linux (`journalctl`, for what is installed here).

Whatever the packet quotes rather than writes — a log line, the reply, an error, a source's result —
passes through `Scrub` first, the longest match first: the value of every `LOGBOOK_*` variable but the
record's folder and the model's name, of every proxy and of every variable named like a key, token or
password becomes its name in brackets (`[LOGBOOK_IMMICH_KEY]`); the record's folder `[record]`; the home
directory `~`; the owner's names and each word of them, handles, addresses and numbers from
`policy/owner.json` and `owner_emails`, and the login name, `[owner]` (a number by its last eight
digits, however it is spaced); this machine's name `[host]`; and the names of the places and assets the
record keeps, `[place]` and `[asset]`. What the packet does not know it cannot replace, so its head says
to read it before sending it. It writes nothing but the file `--out` names."""

from __future__ import annotations

import contextlib
import getpass
import http.client
import importlib.metadata
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from .. import __version__
from ..core import assets, day_start, places, policy
from ..core.store import Logbook
from . import adapters, doctor, last_run, model_client, schedule
from . import service as serve_service

PROMPT = "Reply with the single word ready."  # the probe's whole message: nothing of the record
LOG_LINES = 40
BODY_LIMIT = 64 * 1024  # bytes of the reply's body; a model's error is a few hundred
PROBE_TIMEOUT_S = 60.0  # a local model may load before it answers
COMMAND_TIMEOUT_S = 10.0
TAIL_BYTES = 256 * 1024  # read from the end of a log file for its last lines
DISTRIBUTION = "openlogbook"
GIB = 1024**3

OWNER, HOST, RECORD, HOME, PLACE, ASSET = "[owner]", "[host]", "[record]", "~", "[place]", "[asset]"
PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")  # in either case
SETTING_ENV = (
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "ONEDRIVE",
    "TZ",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)  # upper case: Windows spells `OneDrive`, and its environment ignores case
SHOWN_ENV = frozenset({"LOGBOOK_HOME", model_client.MODEL_ENV})  # the folder as [record], the model as named
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|CREDENTIAL|AUTH", re.IGNORECASE)
SECRET_CHARS = 6  # a shorter value (`1`, `48`, `true`) is a setting, and would match everywhere
WORD_CHARS = 3  # a name's word, an address, a login or a label shorter than this is not replaced
NAME_CHARS = 2  # a whole name shorter than this (`I`) would replace a letter wherever it stands alone
GENERIC_ACCOUNTS = frozenset({"root", "admin", "administrator", "user", "guest", "runner", "ubuntu"})
SEPARATOR = r"[\s\-.()/]{0,2}"  # between the digits of a number as people write it
PHONE_TAIL = 8  # a number is found by its last eight digits, with or without its country code
PHONE_DIGITS = 6  # fewer digits than this is not a number to look for
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
HEAD = re.compile(r"[0-9a-f]{64}")


# -- what is replaced ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    pattern: str
    replacement: str
    length: int  # of the text as the owner wrote it: the longest is tried first


class Scrub:
    """Replaces, in text the packet quotes, what would say whose machine this is (`scrubber` builds
    it): one pass, the longest rule first where two match at the same place."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        ordered = sorted(rules, key=lambda rule: -rule.length)
        self.replacements = {f"r{n}": rule.replacement for n, rule in enumerate(ordered)}
        joined = "|".join(f"(?P<r{n}>{rule.pattern})" for n, rule in enumerate(ordered))
        self.pattern = re.compile(joined) if ordered else None

    def __call__(self, text: str) -> str:
        if self.pattern is None:
            return text
        return self.pattern.sub(lambda m: self.replacements[m.lastgroup or ""], text)


def _word(text: str, replacement: str, *, cased: bool = False) -> Rule:
    """`text` with no letter, digit or underscore on either side, in any case unless `cased`."""
    body = rf"(?<!\w){re.escape(text)}(?!\w)"
    return Rule(body if cased else f"(?i:{body})", replacement, len(text))


def _anywhere(text: str, replacement: str) -> Rule:
    return Rule(f"(?i:{re.escape(text)})", replacement, len(text))


def _phone(number: str, replacement: str) -> Rule | None:
    """The number by its last `PHONE_TAIL` digits, spaced or not, after up to six more and a `+` or
    `00`: `+44 7700 900461`, `07700900461` and `(+44) 7700-900-461` are one number."""
    digits = re.sub(r"\D", "", number)
    if len(digits) < PHONE_DIGITS:
        return None
    tail = SEPARATOR.join(digits[-PHONE_TAIL:])
    return Rule(rf"(?<!\d)(?:\+|00)?(?:\d{SEPARATOR}){{0,6}}{tail}(?!\d)", replacement, len(number))


def _path_forms(path: Path) -> set[str]:
    """`path` as a log may spell it: as given, absolute and resolved, with the platform's separator
    and with `/`; never a bare root or a single name, which would match everywhere."""
    found = {path}
    with contextlib.suppress(OSError):
        found.add(path.absolute())
        found.add(path.resolve())
    return {text for p in found if len(p.parts) > 1 for text in (str(p), p.as_posix())}


def secret(name: str) -> bool:
    """Whether a variable's value is replaced by its name: every `LOGBOOK_*` but the record's folder
    and the model's name, the proxies (a proxy URL can carry a password), and any variable named like
    a key, a token or a password."""
    if name in SHOWN_ENV:
        return False
    return name.startswith("LOGBOOK_") or name.upper() in PROXY_ENV or SECRET_NAME.search(name) is not None


def hostname() -> str:
    """This machine's name, which often carries its owner's. Tests replace it."""
    try:
        return socket.gethostname()
    except OSError:
        return ""


def login_name() -> str | None:
    """The account the command runs as. Tests replace it."""
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):  # no name for the uid, or no pwd module
        return None


@dataclass(frozen=True)
class Owner:
    names: tuple[str, ...]
    emails: tuple[str, ...]
    phones: tuple[str, ...]
    problem: str | None  # why policy/owner.json could not be read, or None


def owner_of(lb: Logbook | None) -> Owner:
    """The owner's names, emails and phones: `policy/owner.json` (read, never written: a record
    without one keeps none) and `owner_emails` in `logbook.json`."""
    if lb is None:
        return Owner((), (), (), None)
    found: dict[str, list[str]] = {key: [] for key in policy.OWNER_KEYS}
    problem = None
    if policy.owner_path(lb.root).exists():
        try:
            found = policy.owner_aliases(lb.root)
        except policy.PolicyError:
            problem = (
                f"{policy.OWNER_FILE.as_posix()} could not be read, so the owner's names, addresses and"
                " numbers are not replaced (logbook doctor says why)"
            )
    with contextlib.suppress(OSError, ValueError):
        listed = lb.meta.get("owner_emails")
        if isinstance(listed, str):  # one address where a list belongs: the address, never its letters
            listed = [listed]
        if isinstance(listed, list):
            found["emails"] += [str(e).strip() for e in listed if str(e).strip()]
    return Owner(
        tuple(found["names"]), tuple(dict.fromkeys(found["emails"])), tuple(found["phones"]), problem
    )


def _owner_words(owner: Owner) -> set[str]:
    """Each name whole and each word of it, a handle with and without its `@`, each address whole,
    and the login name unless it is a generic account's; never a single letter."""
    words: set[str] = set()
    for name in owner.names:
        if len(name) >= NAME_CHARS:
            words.add(name)
        for part in [*name.split(), name.lstrip("@")]:
            bare = part.strip("@.,;:()<>\"'")
            if len(bare) >= WORD_CHARS:
                words.add(bare)
    words.update(e for e in owner.emails if len(e) >= WORD_CHARS)
    login = (login_name() or "").strip()
    if len(login) >= WORD_CHARS and login.casefold() not in GENERIC_ACCOUNTS:
        words.add(login)
    return words


def _host_names(name: str) -> set[str]:
    """The machine's name in full and before its first dot (`ines-mbp.local`, `ines-mbp`)."""
    full = name.strip()
    found = {full, full.split(".")[0]}
    return {n for n in found if len(n) >= WORD_CHARS and n.casefold() != "localhost"}


def _labels(lb: Logbook) -> list[Rule]:
    """The names of the places and the assets the record keeps, as written."""
    rules: list[Rule] = []
    with contextlib.suppress(places.PlaceError, OSError):
        rules += [_word(p.name, PLACE, cased=True) for p in places.read(lb.root) if len(p.name) >= WORD_CHARS]
    with contextlib.suppress(assets.AssetError, OSError, ValueError, KeyError, TypeError):
        for a in assets.read(lb.root):
            rules += [_word(text, ASSET, cased=True) for text in {a.id, a.name} if len(text) >= WORD_CHARS]
    return rules


def scrubber(lb: Logbook | None, env: Mapping[str, str]) -> Scrub:
    """Every rule for this record, this environment and this machine (the module's documentation)."""
    rules = [
        _anywhere(value.strip(), f"[{name}]")
        for name, value in env.items()
        if secret(name) and len(value.strip()) >= SECRET_CHARS
    ]
    if lb is not None:
        rules += [_word(form, RECORD) for form in _path_forms(lb.root)]
    rules += [_word(form, HOME) for form in _path_forms(Path.home())]
    owner = owner_of(lb)
    rules += [rule for number in owner.phones if (rule := _phone(number, OWNER)) is not None]
    rules += [_word(word, OWNER) for word in _owner_words(owner)]
    rules += [_word(name, HOST) for name in _host_names(hostname())]
    if lb is not None:
        rules += _labels(lb)
    return Scrub(rules)


# -- the machine -----------------------------------------------------------------------------------------


def os_name() -> str:
    """`macOS 15.1`, `Ubuntu 24.04.5 LTS, Linux 6.8.0`, `Windows 11 (10.0.22631)`."""
    system = platform.system()
    if system == "Darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    if system == "Linux":
        with contextlib.suppress(OSError):
            pretty = platform.freedesktop_os_release().get("PRETTY_NAME")
            if pretty:
                return f"{pretty}, Linux {platform.release()}"
        return f"Linux {platform.release()}"
    if system == "Windows":
        return f"Windows {platform.release()} ({platform.version()})"
    return f"{system} {platform.release()}".strip() or "unknown"


def ram_bytes() -> int | None:
    """The machine's physical memory, or None when it cannot say. Tests replace it."""
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):  # MEMORYSTATUSEX
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullTotalPhys)
    else:
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError):  # a name this system's sysconf does not know
            return None
        return total if total > 0 else None


def extras_text() -> str:
    """`crypto (cryptography 46.0.1), mcp (mcp 2.1.0); not installed: ais, describe, …`: each extra of the
    package with the packages of it that are installed; an extra is installed when one of them is."""
    try:
        requires = importlib.metadata.requires(DISTRIBUTION) or []
    except importlib.metadata.PackageNotFoundError:  # run from a checkout nobody installed
        found = [extra for extra, modules in doctor.EXTRAS if any(map(doctor.module_installed, modules))]
        return ", ".join(found) or "none of " + ", ".join(extra for extra, _ in doctor.EXTRAS)
    extras: dict[str, list[str]] = {}
    for requirement in requires:
        extra = re.search(r"""extra\s*==\s*["']([^"']+)["']""", requirement)
        name = re.match(r"[A-Za-z0-9._-]+", requirement)
        if extra is None or name is None:
            continue
        installed = extras.setdefault(extra.group(1), [])
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            installed.append(f"{name.group(0)} {importlib.metadata.version(name.group(0))}")
    have = [f"{extra} ({', '.join(found)})" for extra, found in sorted(extras.items()) if found]
    lack = [extra for extra, found in sorted(extras.items()) if not found]
    said = ", ".join(have) or "none"
    return f"{said}; not installed: {', '.join(lack)}" if lack else said


def machine_lines() -> list[str]:
    ram = ram_bytes()
    return [
        f"os: {os_name()}",
        f"platform: {platform.platform()}",
        f"architecture: {platform.machine() or 'unknown'}",
        f"ram: {ram / GIB:,.1f} GiB" if ram else "ram: unknown",
        f"python: {platform.python_version()} ({platform.python_implementation()})",
        f"openlogbook: {__version__}",
        f"extras: {extras_text()}",
    ]


# -- the record and its sources --------------------------------------------------------------------------


def record_lines(lb: Logbook | None, index: str) -> list[str]:
    """The count and the head `logbook.json` names, its format, the day's start and the index: never
    a line. `logbook verify` is what says the head is right."""
    if lb is None:
        return ["record: none found (LOGBOOK_HOME, the working folder or its parents, ~/Logbook)"]
    try:
        meta = lb.meta
    except (OSError, ValueError) as e:
        return [f"record: logbook.json could not be read ({type(e).__name__})"]
    seq, head = meta.get("seq"), str(meta.get("head"))
    try:
        starts = day_start.of(meta).text
    except day_start.DayStartError:
        starts = "not a clock (logbook doctor says why)"
    return [
        f"lines: {seq}" if isinstance(seq, int) else "lines: not a count (logbook verify)",
        f"head: {head}" if HEAD.fullmatch(head) else "head: not a hash (logbook verify)",
        f"format: {meta.get('format')}",
        f"day starts: {starts}",
        f"index: {index}",
    ]


def watermark_text(path: Path) -> str:
    """`watermark 2026-10-12`: the date of the state file's `since`, the date alone; else the day the
    file was last saved."""
    if not path.exists():
        return "no state file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "a state file that is not JSON"
    since = data.get("since") if isinstance(data, dict) else None
    found = DAY.match(since.strip()) if isinstance(since, str) else None
    if found is not None:
        with contextlib.suppress(ValueError):
            return f"watermark {date.fromisoformat(found.group(0)).isoformat()}"
    saved = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return f"no watermark date (state saved {saved:%Y-%m-%d})"


def _configured(adapter: adapters.LiveAdapter | None, env: Mapping[str, str], disabled: set[str]) -> str:
    if adapter is None:
        return "no adapter of that name in this version"
    if adapter.NAME in disabled:
        return "disabled in policy/import.json"
    try:
        config = adapter.configure(env)
    except (OSError, ValueError):
        return f"a variable is set but refused (`logbook sync {adapter.NAME}` says why)"
    return "configured" if config is not None else "set " + adapters.needs(adapter, env)


def source_lines(
    lb: Logbook | None, env: Mapping[str, str], in_index: set[str], run: last_run.Run | None, scrub: Scrub
) -> list[str]:
    """One line per live source the record uses or the last run listed: configured, the last run, the
    watermark's date."""
    if lb is None:
        return ["none: no record"]
    ran = {s.name: s for s in run.sources} if run is not None else {}
    state = lb.root / "state"
    used = {a.NAME for a in doctor.syncs_used(lb, in_index, env)}
    names = [
        a.NAME
        for a in adapters.live_adapters()
        if a.NAME in used or a.NAME in ran or (state / f"{a.NAME}.json").exists()
    ]
    names += sorted(set(ran) - set(names))
    if not names:
        return ["none: no live source is configured, has a watermark or was in the last run"]
    disabled = doctor.disabled_sources(lb)
    lines = []
    for name in names:
        source = ran.get(name)
        lines.append(
            f"{scrub(name)}: {_configured(adapters.live(name), env, disabled)}; "
            + (
                f"last run {scrub(source.result)}, {source.lines:,} lines"
                if source
                else "not in the last run"
            )
            + f"; {watermark_text(state / f'{name}.json')}"
        )
    return lines


# -- the schedule and the service ------------------------------------------------------------------------


def _installs_text(installs: Sequence[str], system: str) -> str:
    kinds = (
        {"user": "launchd agents", "system": "launchd daemons"}
        if system == "darwin"
        else {"user": "systemd user timers", "system": "systemd system timers"}
    )
    if not installs:
        return "not installed on this machine"
    said = " and ".join(f"for the {which} ({kinds[which]})" for which in installs)
    return f"installed twice, {said}" if len(installs) > 1 else f"installed {said}"


def _config_home(env: Mapping[str, str]) -> Path | None:
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    return Path(xdg).expanduser() if xdg else None


def schedule_lines(
    lb: Logbook | None,
    env: Mapping[str, str],
    state: last_run.State | None,
    problem: str | None,
    scrub: Scrub,
) -> list[str]:
    lines = [f"schedule: {_installs_text(doctor.schedules_installed(env), schedule.system())}"]
    if lb is not None:
        if problem is not None:
            lines.append(f"last run: {problem}")
        elif state is None:
            lines.append(f"last run: none recorded ({last_run.LAST_RUN_FILE.as_posix()})")
        else:
            run = state.run
            age = last_run.age_text(last_run.now() - run.at)
            said = f"last run: {run.at:%Y-%m-%d %H:%M} UTC ({age}): {scrub(last_run.sources_text(run))}"
            said += f"; {last_run.doctor_text(run.doctor)}"
            if run.doctor is not None and run.doctor.warned:
                said += f"; warned: {scrub(', '.join(run.doctor.warned))}"
            if run.doctor is not None and run.doctor.failed:
                said += f"; failed: {scrub(', '.join(run.doctor.failed))}"
            lines.append(said)
    found = serve_service.find(serve_service.system(), Path.home(), _config_home(env))
    if not found:
        lines.append("serve: no serve service on this machine")
    for item in found:
        lines.append(
            f"serve: {item.kind} on port {item.port}; whether it answers is not asked here"
            " (`logbook doctor` asks)"
        )
    return lines


# -- the dream endpoint ----------------------------------------------------------------------------------


def probe(endpoint: model_client.Endpoint, timeout: float = PROBE_TIMEOUT_S) -> tuple[str, bytes | None]:
    """One request, the dream's (`model_client.complete`) with `PROMPT` for its messages, never
    retried: (`HTTP 500 Internal Server Error`, the first `BODY_LIMIT` + 1 bytes of the body), or
    (`none, …` why, None) when no reply came."""
    body = {
        "model": endpoint.model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": model_client.TEMPERATURE,
    }
    request = urllib.request.Request(endpoint.url, data=json.dumps(body).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    if endpoint.key:
        request.add_header("Authorization", f"Bearer {endpoint.key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return f"HTTP {response.status} {response.reason}", response.read(BODY_LIMIT + 1)
    except urllib.error.HTTPError as e:
        try:
            return f"HTTP {e.code} {e.reason}", e.read(BODY_LIMIT + 1)
        finally:
            e.close()
    except TimeoutError:
        return f"none, no reply within {timeout:.0f} s", None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or e
        kind = type(reason).__name__ if isinstance(reason, BaseException) else type(e).__name__
        return f"none, the request failed: {kind}: {reason}", None


def _address(url: str) -> str | None:
    """`127.0.0.1:8080 (http)`: the host and port of the endpoint and its scheme, never its path."""
    parts = urlsplit(url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    host = parts.hostname or ""
    if not host:
        return None
    return f"{f'[{host}]' if ':' in host else host}:{port} ({parts.scheme})"


def dream_lines(lb: Logbook | None, env: Mapping[str, str], scrub: Scrub) -> list[str]:
    url = (env.get(model_client.ENDPOINT_ENV) or "").strip()
    if not url:
        return [f"endpoint: not configured ({model_client.ENDPOINT_ENV} is not set); nothing was asked"]
    address = _address(url) if urlsplit(url).scheme in ("http", "https") else None
    if address is None:
        return [f"endpoint: {model_client.ENDPOINT_ENV} is not an http(s) URL with a host; nothing was asked"]
    lines = [f"endpoint: {scrub(address)}"]
    named = None
    if lb is None:
        lines.append("policy: no record, so no dream entry")
    else:
        try:
            entry = policy.dream_entry(lb.root)
        except policy.PolicyError as e:
            lines.append(f"policy: {scrub(str(e))}")
        else:
            named = entry.model
            until = f" until {entry.until.isoformat()}" if entry.until is not None else ""
            model = f" model {scrub(entry.model)}" if entry.model else ""
            lines.append(f"policy: dream entry, max_tier {entry.max_tier}{until}{model}")
    try:
        endpoint = model_client.from_env(env, named)
    except model_client.ModelError as e:
        return [*lines, f"model: {scrub(str(e))}; nothing was asked"]
    given = (env.get(model_client.MODEL_ENV) or "").strip()
    whose = policy.POLICY_FILE.as_posix() if named else model_client.MODEL_ENV
    disagree = (
        f"; {model_client.MODEL_ENV} names another, and the dream refuses until they agree"
        if named and given and given != named
        else ""
    )
    lines.append(f"model: {scrub(endpoint.model)} ({whose}){disagree}")
    key = f"{model_client.KEY_ENV} set, sent as the bearer token" if endpoint.key else "none"
    lines.append(f"key: {key}")
    lines.append(f"probe: the dream's request with {PROMPT!r} as its only message, sent once")
    status, body = probe(endpoint)
    lines.append(f"reply: {scrub(status)}")
    if body is None:
        return lines
    if not body:
        return [*lines, "body: empty"]
    size = (
        f"more than {BODY_LIMIT:,} bytes; the first {BODY_LIMIT:,}"
        if len(body) > BODY_LIMIT
        else f"{len(body):,} bytes"
    )
    return [*lines, f"body ({size}):", scrub(body[:BODY_LIMIT].decode("utf-8", errors="replace"))]


# -- the environment and the logs ------------------------------------------------------------------------


def env_names(env: Mapping[str, str]) -> list[str]:
    """The names of the variables set that logbook reads: `LOGBOOK_*`, the proxies, the folders."""
    return sorted(
        name
        for name, value in env.items()
        if value.strip()
        and (name.startswith("LOGBOOK_") or name.upper() in PROXY_ENV or name.upper() in SETTING_ENV)
    )


def run_command(args: Sequence[str]) -> str | None:
    """What a command printed, or None when it is not on PATH, fails or takes too long. Tests replace
    it."""
    if shutil.which(args[0]) is None:
        return None
    try:
        done = subprocess.run(
            list(args),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def tail(path: Path, n: int = LOG_LINES) -> list[str] | None:
    """The last `n` lines of a file, read from its end; None when it cannot be read."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - TAIL_BYTES))
            data = f.read()
    except OSError:
        return None
    lines = data.decode("utf-8", errors="replace").splitlines()
    return (lines[1:] if size > TAIL_BYTES else lines)[-n:]  # the first may be cut


@dataclass(frozen=True)
class Log:
    title: str  # `sync log`, `service log`
    where: str | None  # as the owner would look; None when there is nothing to read
    lines: list[str] | None  # None: could not be read
    absent: str = ""  # why there is nothing to read


def _journal(units: Sequence[str], user: bool) -> tuple[str, list[str] | None]:
    args = ["journalctl", *(["--user"] if user else [])]
    for unit in units:
        args += ["-u", f"{unit}.service"]
    where = " ".join(args)
    printed = run_command([*args, "-n", str(LOG_LINES), "--no-pager", "-o", "short-iso"])
    return where, (printed.splitlines()[-LOG_LINES:] if printed is not None else None)


def logs(env: Mapping[str, str]) -> list[Log]:
    """The schedule's log and the service's: the files launchd writes on macOS; the journal on Linux,
    for each install this machine has; nothing elsewhere."""
    system, home = schedule.system(), Path.home()
    if system == "darwin":
        found = []
        for title, parts in (("sync log", schedule.LOG), ("service log", serve_service.LOG)):
            path, where = home.joinpath(*parts), "~/" + "/".join(parts)
            if path.exists():
                found.append(Log(title, where, tail(path)))
            else:
                found.append(Log(title, None, None, f"{where} is not there"))
        return found
    if system != "linux":
        return [Log(title, None, None, f"no log on {system}") for title in ("sync log", "service log")]
    found = []
    installs = doctor.schedules_installed(env)
    for which in installs:
        where, lines = _journal((schedule.UNIT, schedule.CLOSE_UNIT), user=which == "user")
        found.append(Log("sync log", where, lines))
    if not installs:
        found.append(Log("sync log", None, None, "the schedule is not installed on this machine"))
    services = serve_service.find("linux", home, _config_home(env))
    system_path = serve_service.path_of("linux", home, True)
    for item in services:
        where, lines = _journal((serve_service.UNIT,), user=item.path != system_path)
        found.append(Log("service log", where, lines))
    if not services:
        found.append(Log("service log", None, None, "no serve service on this machine"))
    return found


def log_section(log: Log, scrub: Scrub) -> list[str]:
    if log.where is None:
        return [f"## {log.title}", f"none: {log.absent}"]
    head = f"## {log.title}, the last {LOG_LINES} lines ({log.where})"
    if log.lines is None:
        return [head, "none: it could not be read"]
    return [head, *(scrub(line) for line in log.lines)] if log.lines else [head, "empty"]


# -- the packet ------------------------------------------------------------------------------------------


def build(lb: Logbook | None, env: Mapping[str, str]) -> str:
    """The whole packet, as text ending in a newline (the module's documentation)."""
    scrub = scrubber(lb, env)
    owner = owner_of(lb)
    index, in_index = "none", set[str]()
    if lb is not None:
        try:
            index, in_index = doctor.index_state(lb)
        except (OSError, ValueError):  # logbook.json unreadable: the record section says so
            index = "unknown"
    state, problem = None, None
    if lb is not None:
        try:
            state = last_run.read(lb.root)
        except last_run.LastRunError:
            problem = (
                f"{last_run.LAST_RUN_FILE.as_posix()} is not the shape `logbook sync --scheduled` writes"
            )
    counted = ", ".join(
        f"{len(values)} {one if len(values) == 1 else many}"
        for one, many, values in (
            ("name", "names", owner.names),
            ("address", "addresses", owner.emails),
            ("number", "numbers", owner.phones),
        )
    )
    sections: list[list[str]] = [
        [
            "logbook diagnostic packet",
            f"written {last_run.stamp(last_run.now())} by `logbook doctor --packet`",
            "nothing in it is read from a line of the record: no text, no name, no value of a variable",
            "where it quotes a log, a reply or an error, it replaces:",
            f"  {HOME:<16}the home directory",
            f"  {RECORD:<16}the record's folder",
            f"  {OWNER:<16}the owner: {counted} (policy/owner.json, owner_emails), the login name",
            f"  {HOST:<16}this machine's name",
            f"  {PLACE + ' ' + ASSET:<16}the names of the record's places and assets",
            f"  {'[NAME]':<16}the value of the variable NAME",
            *([owner.problem] if owner.problem else []),
            "read it before you send it: the logs are what the programs printed",
        ],
        ["## machine", *machine_lines()],
        ["## record", *record_lines(lb, index)],
        ["## sources", *source_lines(lb, env, in_index, state.run if state else None, scrub)],
        ["## schedule and service", *schedule_lines(lb, env, state, problem, scrub)],
        ["## dream endpoint", *dream_lines(lb, env, scrub)],
        ["## environment, the names of the variables set (never a value)", *(env_names(env) or ["none"])],
        *(log_section(log, scrub) for log in logs(env)),
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"
