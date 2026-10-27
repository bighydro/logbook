"""`phone` in `logbook.json`: the owner's own phone may write through the Library, off by default.

The Library binds 127.0.0.1 only, and its write gate (`serve.Site.write`) answers a POST from this
machine's own pages. Behind `tailscale serve --bg 8765` on the same machine, the phone reads the pages at
the machine's tailnet name, `https://server.tail1234.ts.net/today`: tailscaled forwards each request to
127.0.0.1:8765, so it arrives from loopback, but the browser's `Origin` names the tailnet name, and the
gate refuses it. The setting names that one origin and the owner's tailnet login:

    "phone": {"origin": "https://server.tail1234.ts.net", "login": "ines@example.org"}

With it, a POST is also answered when all of these hold (`allows`): the client is loopback
(tailscaled's proxy; `serve` checks it); exactly one `Origin`, equal to the setting's after the
standard normalisation (the scheme, the host case-insensitive, the port, 443 written or not); exactly
one `Host`, the setting's host (a page of another tailnet name proxied in is not the phone's); exactly
one `Tailscale-User-Login`, the header Tailscale Serve sets on a request from a tailnet user's device,
equal to the setting's login; and no `Sec-Fetch-Dest` but `document`, so a form posted from inside a
frame (a page that frames the Day to borrow a click) is not. A process on this machine could forge
every one of these headers, but such a process can already write through the gate today. A
`Tailscale-User-Login` sent by the phone itself is not trusted on its own: it is tailscaled's to set
(it sets it from the device's identity and sends none for a tagged device or a Funnel request, so
those are refused), and the Origin is what a hostile page in the phone's browser cannot choose.

The same setting decides who reads (`reads`): the Library answers a GET from this machine (`here`:
no proxy, and a Host this machine reads it at, with the server's port) or from the phone (one Host,
the setting's; one login, the setting's; never a `Tailscale-Funnel-Request`), and refuses every
other request before it reads anything (`serve.Site.gate`); without the setting, everything proxied.

The setting is the owner's, written through `logbook setup phone` only (`commands/serve.py`), never
by the Library and never by an agent: the policy's `write` list (ADR 0022, the MCP door) is not this
and is never read here. The Library reads it from `logbook.json` with every POST, as it reads
`day_start`, so writing or removing it needs no restart. A value that is not the shape (written by
hand) lets nothing in, and `doctor` says why (`problem`)."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlsplit

KEY = "phone"  # the key of logbook.json
LOGIN_HEADER = "Tailscale-User-Login"  # what Tailscale Serve sets on a proxied request from a user's device
FUNNEL_HEADER = "Tailscale-Funnel-Request"  # what Tailscale Funnel sets on a request from the open internet
SUFFIX = ".ts.net"
PORT = 443
# a MagicDNS name: the machine, the tailnet, ts.net; each label letters, digits and inner hyphens
_TAILNET = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net")
_LOGIN = re.compile(r"[^\s@]+@[^\s@]+")
_LOOPBACK_HOST = re.compile(r"(?:127\.0\.0\.1|\[::1\])(?::\d{1,5})?")  # a Host this machine's browser sends
HERE = ("127.0.0.1", "[::1]", "localhost")  # the names this machine reads the Library at, with its port
HTTP_PORT = 80  # a Host with no port names this one
PROXY_HEADERS = (
    "tailscale-",
    "x-forwarded-",
)  # a header a proxy adds, by the start of its name in lower case
PROXY_NAMES = ("forwarded", "via", "x-real-ip")  # and the ones a proxy adds by their whole name
EXAMPLE = "https://server.tail1234.ts.net"
FROM_PHONE = "or from your phone once `logbook setup phone` names it"  # the refusal's clause


class PhoneError(ValueError):
    """An origin or a login the setting cannot hold: the message is one sentence."""


class Phone(NamedTuple):
    """The setting, read: the origin normalised (`https://host`), its host, the login as written."""

    origin: str
    host: str
    login: str


class Headers(Protocol):
    """A request's headers as `http.server` holds them (`email.message.Message`)."""

    def __iter__(self) -> Iterator[str]: ...  # the names of the headers sent, in order

    def get_all(self, name: str) -> list[str] | None: ...


class Asked(NamedTuple):
    """What a request carried that the gates read beside a POST's Origin, every value of each header as
    sent: `Origin`, `Host`, `Tailscale-User-Login`, `Sec-Fetch-Dest` and `Sec-Fetch-Site`; and
    `forwarded`, the name of every `Tailscale-*` and `X-Forwarded-*` header it carried, which a proxy
    adds (`proxied`)."""

    origin: tuple[str, ...]
    host: tuple[str, ...]
    login: tuple[str, ...]
    dest: tuple[str, ...]
    forwarded: tuple[str, ...] = ()
    site: tuple[str, ...] = ()

    @classmethod
    def of(cls, headers: Headers) -> Asked:
        """From a request's headers."""

        def every(name: str) -> tuple[str, ...]:
            return tuple(headers.get_all(name) or ())

        names = tuple(
            name for name in headers if name.lower().startswith(PROXY_HEADERS) or name.lower() in PROXY_NAMES
        )
        return cls(
            every("Origin"),
            every("Host"),
            every(LOGIN_HEADER),
            every("Sec-Fetch-Dest"),
            names,
            every("Sec-Fetch-Site"),
        )


def proxied(asked: Asked | None) -> bool:
    """Whether a request came through a proxy (Tailscale Serve, or any other) rather than from this
    machine's own browser or programs: its Host is not a loopback literal, `127.0.0.1` or `[::1]` with
    any port or none (a name, `localhost` included, is not one), it carries more than one Host, or it
    carries a `Tailscale-*` or `X-Forwarded-*` header. A request with no Host at all (an HTTP/1.0
    client) is this machine's, as is a call with no headers (`asked` None, the server's own callers)."""
    if asked is None:
        return False
    return (
        bool(asked.forwarded)
        or len(asked.host) > 1
        or any(_LOOPBACK_HOST.fullmatch(h) is None for h in asked.host)
    )


def here(asked: Asked, port: int) -> bool:
    """Whether a request is this machine's own, to the server on `port`: through no proxy (no
    `Tailscale-*` or `X-Forwarded-*` header), and no Host (an HTTP/1.0 client) or exactly one, a name
    this machine reads the Library at (`HERE`, `localhost` among them: only this machine resolves it
    to itself) with `port`, written or, for port 80, not. A website the owner opens that points its
    own name at 127.0.0.1 (DNS rebinding) sends its own name as the Host, and is not this machine."""
    if asked.forwarded or len(asked.host) > 1:
        return False
    if not asked.host:
        return True
    host = asked.host[0].strip().lower()
    return host in {f"{name}:{port}" for name in HERE} or (port == HTTP_PORT and host in HERE)


def looks_proxied(asked: Asked) -> bool:
    """Whether a request that is not this machine's (`here`) came, or says it came, through a proxy: a
    `Tailscale-*` or `X-Forwarded-*` header, more than one Host, or a tailnet name as its Host. A
    refusal of it is a 403; of anything else, a Host this server is not (421)."""
    hosts = [h.strip().lower().rpartition(":")[0] or h.strip().lower() for h in asked.host]
    return bool(asked.forwarded) or len(asked.host) > 1 or any(h.endswith(SUFFIX) for h in hosts)


def cross(asked: Asked | None) -> bool:
    """Whether this machine's browser says a POST was sent from inside a frame (`Sec-Fetch-Dest`, when
    sent, not `document`) or from another site (`Sec-Fetch-Site`, when sent, not `same-origin`, nor
    `none`, a request the owner made by hand): either is a page that is not the Library's own, posting
    to it, with an Origin or without one. Each header sent more than once is one of those too."""
    if asked is None:
        return False
    dest = [d.strip().lower() for d in asked.dest]
    site = [s.strip().lower() for s in asked.site]
    return dest not in ([], ["document"]) or site not in ([], ["same-origin"], ["none"])


def funnel(asked: Asked) -> bool:
    """Whether a request came through Tailscale Funnel, from the open internet: its header, any value."""
    return any(name.lower() == FUNNEL_HEADER.lower() for name in asked.forwarded)


def origin_of(text: str) -> str:
    """`text` as the setting holds it, `https://host`; `PhoneError` for anything but `https://` and a
    tailnet name (`machine.tailnet.ts.net`), with no path, query, user or port but 443."""
    parts = urlsplit(text.strip())
    host = parts.hostname or ""
    netloc = parts.netloc.lower()
    if (
        parts.scheme.lower() != "https"
        or not _TAILNET.fullmatch(host)
        or netloc not in (host, f"{host}:{PORT}")
        or parts.path
        or "?" in text
        or "#" in text
    ):
        raise PhoneError(
            f"{text!r} is not your machine's tailnet name as the phone opens it: https:// and a name"
            f" ending in {SUFFIX}, with no path, query or port but 443, such as {EXAMPLE}; nothing changed"
        )
    return f"https://{host}"


def login_of(text: str) -> str:
    """`text` as the setting holds it; `PhoneError` for anything but one login, `name@domain`."""
    login = text.strip()
    if not _LOGIN.fullmatch(login) or not login.isascii() or not login.isprintable():
        raise PhoneError(  # not ASCII: Tailscale Serve sends such a login encoded, and it would never match
            f"{text!r} is not a tailnet login: the one `tailscale status` names beside the phone,"
            " in plain ASCII, such as ines@example.org; nothing changed"
        )
    return login


def of(meta: Mapping[str, Any]) -> Phone | None:
    """The setting in `meta` (`logbook.json`); None when absent. `PhoneError` when it is not the shape."""
    found = meta.get(KEY)
    if found is None:
        return None
    if not isinstance(found, Mapping) or not isinstance(found.get("origin"), str):
        raise PhoneError(f'logbook.json {KEY} is not {{"origin": ..., "login": ...}}')
    if not isinstance(found.get("login"), str):
        raise PhoneError(f"logbook.json {KEY} names no login")
    origin = origin_of(found["origin"])
    try:
        login = login_of(found["login"])
    except PhoneError:  # never the login itself: `doctor` prints this
        raise PhoneError(f"logbook.json {KEY} login is not one tailnet login, name@domain") from None
    if origin != found["origin"] or login != found["login"]:
        raise PhoneError(f"logbook.json {KEY} is not written as `logbook setup phone` writes it")
    return Phone(origin, urlsplit(origin).hostname or "", login)


def problem(meta: Mapping[str, Any]) -> str | None:
    """Why the setting in `meta` lets nothing in, or None when it is absent or the shape."""
    try:
        of(meta)
    except PhoneError as e:
        return str(e).removesuffix("; nothing changed")
    return None


def _same_origin(origin: str, phone: Phone) -> bool:
    try:
        return origin_of(origin) == phone.origin
    except PhoneError:
        return False


def _same_host(host: str, phone: Phone) -> bool:
    return host.strip().lower() in (phone.host, f"{phone.host}:{PORT}")


def allows(meta: Mapping[str, Any], origin: str | None, asked: Asked | None) -> bool:
    """Whether a POST from loopback with `origin` is the owner's phone through Tailscale Serve: the
    setting is in `meta` and the shape, and `asked` holds one Origin (the gate's), equal to it, one
    Host, its host, one login, its login, nothing from Funnel (`reads`), and no frame. The client's
    address is the gate's to check."""
    try:
        phone = of(meta)
    except PhoneError:
        return False
    if phone is None or origin is None or asked is None:
        return False
    return (
        asked.origin == (origin,)
        and _same_origin(origin, phone)
        and reads(meta, asked)
        and asked.dest in ((), ("document",))
    )


def reads(meta: Mapping[str, Any], asked: Asked | None) -> bool:
    """Whether a request from loopback is the owner's phone through Tailscale Serve, reading: the
    setting is in `meta` and the shape, and `asked` holds one Host, its host, one login, its login,
    and nothing from Tailscale Funnel. The phone reads every page this machine reads. The client's
    address is the server's to check (it binds 127.0.0.1)."""
    try:
        phone = of(meta)
    except PhoneError:
        return False
    if phone is None or asked is None:
        return False
    return (
        len(asked.host) == 1
        and _same_host(asked.host[0], phone)
        and asked.login == (phone.login,)
        and not funnel(asked)
    )


def shown(login: str) -> str:
    """The login as `doctor` prints it: the part before @ shortened to its first letter."""
    name, at, domain = login.partition("@")
    return f"{name[:1]}…{at}{domain}"
