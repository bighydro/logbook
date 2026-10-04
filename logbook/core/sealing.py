"""Tiers 2 and 3 sealed at rest with age (SPEC §2, §4; RFC 0029; ADR 0020). Pure functions over bytes
and a few file conventions; nothing here reads or writes the record.

A sealed line keeps a plain `payload` that is a *reference* to its content and carries the content
sealed in `payload_enc`, outside the hash as `id` is:

    plain       = canonical_json({"payload": <the real payload>, "salt": <16 random bytes, 32 hex>})
    digest      = sha256(plain)                                               lowercase hex
    payload     = {"schema": "sealed/v1", "of": <the real payload's schema>, "digest": digest}
    payload_enc = base64( age( plain, recipients ) )                          standard base64, padded

The salt is inside the sealed bytes and inside the digest, so the digest confirms nothing to anyone
who cannot open the line. The sealed bytes *are* the canonical text, so an opener hashes what it
decrypted and compares before it parses. age is age-encryption.org/v1 through `pyrage` (rage
underneath), X25519 recipients only, the binary file, never the armor.

Keys: the long-term secret is one X25519 identity per record, the owner's; the public recipients
live in `logbook.json`, the identity never does. The identity file is age's own format
(`AGE-SECRET-KEY-1…`, `#` comments), at `<config dir>/logbook/identities/<owner_id>.txt` unless
`LOGBOOK_IDENTITY_FILE` names another path. A path may be in the environment; a key never is.

`pyrage` is the `sealed` extra, imported lazily: the package installs and runs without it, keyless
`verify` needs nothing from here, and the first seal or open without it raises `MissingExtra`."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .chain import (
    AGE_MAGIC,
    SEALED_FIELD,
    SEALED_SCHEMA,
    canonical_json,
    decode_sealed,
    is_sealed,
    sealed_envelope_error,
)

SCHEMA = SEALED_SCHEMA
FIELD = SEALED_FIELD
decode = decode_sealed
envelope_error = sealed_envelope_error
is_sealed = is_sealed
SALT_BYTES = 16
SECRET_PREFIX = "AGE-SECRET-KEY-1"
RECIPIENT_PREFIX = "age1"
IDENTITY_ENV = "LOGBOOK_IDENTITY_FILE"
IDENTITIES_DIR = "identities"
EXTRA = 'pip install "openlogbook[sealed]"'
MIN_RECIPIENTS = 2  # the owner's identity and a recovery identity: one recipient is none (RFC 0029 §6.1)


class MissingExtra(ImportError):
    """`pyrage` is not installed: the `sealed` extra is needed to seal or open a line."""

    def __init__(self) -> None:
        super().__init__(f"sealing and opening need the sealed extra: {EXTRA}")


class SealError(ValueError):
    """A sealed line or file that does not open, or whose content does not match its digest."""


class IdentityRequired(Exception):
    """The record seals tiers 2 and 3 and this command needs the identity to proceed; the message
    names where it looked."""


def _pyrage() -> Any:
    try:
        import pyrage
    except ImportError:
        raise MissingExtra() from None
    return pyrage


# -- the primitives ---------------------------------------------------------------------------


def plain_of(payload: Mapping[str, Any], salt: str) -> bytes:
    """The bytes that are sealed and hashed: RFC 8785 of {payload, salt}, UTF-8, nothing else."""
    return canonical_json({"payload": payload, "salt": salt}).encode("utf-8")


def new_salt() -> str:
    return secrets.token_hex(SALT_BYTES)


def reference(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
    """The plain `payload` of a sealed line: the hashed reference to its content."""
    return {"schema": SCHEMA, "of": str(payload.get("schema")), "digest": digest}


def seal(
    payload: Mapping[str, Any], recipients: Sequence[str], salt: str | None = None
) -> tuple[dict[str, Any], str]:
    """(the reference that becomes `payload`, the base64 age file that becomes `payload_enc`).
    A `salt` is given only by the conformance generator, so its fixture reproduces its head."""
    if "schema" not in payload:
        raise ValueError("payload.schema is required")
    if len(recipients) < 1:
        raise ValueError("sealing needs at least one recipient")
    plain = plain_of(payload, salt or new_salt())
    digest = hashlib.sha256(plain).hexdigest()
    sealed = _pyrage().encrypt(plain, [parse_recipient(r) for r in recipients])
    return reference(payload, digest), base64.b64encode(sealed).decode("ascii")


def open_line(line: Mapping[str, Any], identities: Sequence[Any]) -> dict[str, Any]:
    """The real payload of a sealed line, after the digest matched. SealError names the line by
    its seq when it does not open, or opens to bytes that do not hash to `payload.digest`, or to
    a payload whose schema is not the reference's `of` (RFC 0029 §5 rules 2 and 6)."""
    plain = open_bytes(line, identities)
    try:
        opened = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise SealError(f"line {line.get('seq')}: sealed bytes are not the canonical text: {e}") from None
    payload = opened.get("payload") if isinstance(opened, dict) else None
    if not isinstance(payload, dict) or not isinstance(opened.get("salt"), str):
        raise SealError(f"line {line.get('seq')}: sealed bytes are not {{payload, salt}}")
    of = (line.get("payload") or {}).get("of")
    if payload.get("schema") != of:
        raise SealError(f"line {line.get('seq')}: sealed payload is {payload.get('schema')!r}, not {of!r}")
    return payload


def open_bytes(line: Mapping[str, Any], identities: Sequence[Any]) -> bytes:
    """The sealed bytes of a line, decrypted and checked against `payload.digest`, unparsed."""
    seq = line.get("seq")
    sealed = decode(line.get(FIELD))
    if sealed is None:
        raise SealError(f"line {seq}: {FIELD} is not base64 of an age file")
    if not identities:
        raise SealError(f"line {seq}: no identity to open it with")
    pyrage = _pyrage()
    try:
        plain: bytes = pyrage.decrypt(sealed, list(identities))
    except pyrage.DecryptError as e:
        raise SealError(f"line {seq}: does not open with this identity: {e}") from None
    digest = (line.get("payload") or {}).get("digest")
    if hashlib.sha256(plain).hexdigest() != digest:
        raise SealError(f"line {seq}: sealed bytes do not hash to payload.digest")
    return plain


def needs_sealing(tier: int, payload: Mapping[str, Any], recipients: Sequence[str]) -> bool:
    """Whether a draft is sealed on append: tiers 2 and 3 when the record names recipients, and
    never a payload that is already a sealed reference (a re-added `export --sealed` line)."""
    return tier in (2, 3) and bool(recipients) and payload.get("schema") != SCHEMA


# -- files: whole or streamed ---------------------------------------------------------------------


def encode(sealed: bytes) -> str:
    """An age file as it is carried in a line: standard base64 with padding, one string."""
    return base64.b64encode(sealed).decode("ascii")


def seal_bytes(data: bytes, recipients: Sequence[str]) -> bytes:
    sealed: bytes = _pyrage().encrypt(data, [parse_recipient(r) for r in recipients])
    return sealed


def open_sealed_bytes(data: bytes, identities: Sequence[Any]) -> bytes:
    pyrage = _pyrage()
    try:
        plain: bytes = pyrage.decrypt(data, list(identities))
    except pyrage.DecryptError as e:
        raise SealError(f"does not open with this identity: {e}") from None
    return plain


def seal_file(src: Path, dst: Path, recipients: Sequence[str]) -> None:
    """age-seal the file at `src` to `dst`, streamed in 64 KiB chunks; a recording is never held whole."""
    _pyrage().encrypt_file(str(src), str(dst), [parse_recipient(r) for r in recipients])


def open_file(src: Path, dst: Path, identities: Sequence[Any]) -> None:
    pyrage = _pyrage()
    try:
        pyrage.decrypt_file(str(src), str(dst), list(identities))
    except pyrage.DecryptError as e:
        raise SealError(f"{src.name} does not open with this identity: {e}") from None


def is_sealed_file(path: Path) -> bool:
    """Whether a store file is an age file: its first 22 bytes are the header (SPEC §1.1)."""
    try:
        with Path(path).open("rb") as fh:
            return fh.read(len(AGE_MAGIC)) == AGE_MAGIC
    except OSError:
        return False


# -- keys -------------------------------------------------------------------------------------


def parse_recipient(text: str) -> Any:
    if not isinstance(text, str) or not text.startswith(RECIPIENT_PREFIX):
        raise ValueError(f"not an age recipient: {text!r}")
    pyrage = _pyrage()
    try:
        return pyrage.x25519.Recipient.from_str(text)
    except pyrage.RecipientError as e:
        raise ValueError(f"not an age recipient: {text!r}: {e}") from None


def parse_identity(text: str) -> Any:
    pyrage = _pyrage()
    try:
        return pyrage.x25519.Identity.from_str(text.strip())
    except pyrage.IdentityError as e:
        raise ValueError(f"not an age identity: {e}") from None


def generate_identity() -> tuple[str, str]:
    """(secret, recipient): a fresh X25519 identity and its public half."""
    identity = _pyrage().x25519.Identity.generate()
    return str(identity), str(identity.to_public())


def recipient_of(secret: str) -> str:
    return str(parse_identity(secret).to_public())


def read_identities(text: str) -> list[Any]:
    """The identities in an age identity file: one per line, `#` comments and blanks ignored."""
    found = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            found.append(parse_identity(stripped))
    return found


def load_identities(path: Path) -> list[Any]:
    found = read_identities(Path(path).read_text(encoding="utf-8"))
    if not found:
        raise ValueError(f"{path} holds no age identity")
    return found


def write_identity_file(path: Path, secret: str, note: str) -> None:
    """Write one identity as `age-keygen` does, readable by its owner only; never over a file."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists; it is not overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"# {note}\n# public key: {recipient_of(secret)}\n{secret}\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    """Where this user's settings live: `%APPDATA%\\logbook` on Windows, else `$XDG_CONFIG_HOME/logbook`
    or `~/.config/logbook`. Built with `pathlib`, never from strings."""
    env = os.environ if env is None else env
    if sys.platform == "win32":
        base = env.get("APPDATA", "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "logbook"
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".config") / "logbook"


def cache_dir(env: Mapping[str, str] | None = None) -> Path:
    """Where this user's disposable caches live (the index, RFC 0029 §8): `%LOCALAPPDATA%\\logbook\\cache`
    on Windows, `~/Library/Caches/logbook` on macOS, else `$XDG_CACHE_HOME/logbook` or `~/.cache/logbook`.
    `LOGBOOK_CACHE_HOME` names another folder on any platform."""
    env = os.environ if env is None else env
    chosen = env.get("LOGBOOK_CACHE_HOME", "").strip()
    if chosen:
        return Path(chosen).expanduser()
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA", "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "logbook" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "logbook"
    xdg = env.get("XDG_CACHE_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".cache") / "logbook"


def default_identity_path(owner_id: str, env: Mapping[str, str] | None = None) -> Path:
    return config_dir(env) / IDENTITIES_DIR / f"{owner_id}.txt"


def identity_path(owner_id: str, env: Mapping[str, str] | None = None, given: Path | None = None) -> Path:
    """Where the identity is looked for, in order: `--identity-file`, `LOGBOOK_IDENTITY_FILE`, the
    default location (RFC 0029 §6.2). The first named wins whether or not it exists."""
    env = os.environ if env is None else env
    if given is not None:
        return Path(given).expanduser()
    named = env.get(IDENTITY_ENV, "").strip()
    if named:
        return Path(named).expanduser()
    return default_identity_path(owner_id, env)


def recipients_of(meta: Mapping[str, Any]) -> list[str]:
    """The recipients `logbook.json` names, as strings; absent or not a list of strings is none."""
    found = meta.get("recipients")
    if not isinstance(found, list):
        return []
    return [r for r in found if isinstance(r, str) and r.startswith(RECIPIENT_PREFIX)]


def check_recipients(recipients: Iterable[str]) -> list[str]:
    """Two or more distinct, parseable recipients (RFC 0029 §6.1), or ValueError saying why."""
    seen: list[str] = []
    for r in recipients:
        parse_recipient(r)
        if r not in seen:
            seen.append(r)
    if len(seen) < MIN_RECIPIENTS:
        raise ValueError(
            f"a record seals to {MIN_RECIPIENTS} recipients at least, this machine's and a recovery one;"
            f" {len(seen)} given"
        )
    return seen


# -- the index's blinding key (RFC 0029 §8) ---------------------------------------------------


def new_index_key() -> bytes:
    return secrets.token_bytes(32)


def seal_index_key(key: bytes, recipients: Sequence[str]) -> str:
    return base64.b64encode(seal_bytes(key, recipients)).decode("ascii")


def open_index_key(sealed: str, identities: Sequence[Any]) -> bytes:
    return open_sealed_bytes(base64.b64decode(sealed), identities)


def blind(key: bytes, raw_id: str) -> str:
    """What the index stores for a sealed line's `raw_id`: deterministic, so dedupe compares
    equals, and keyed, so a phone number cannot be confirmed by guessing."""
    return "blind:" + hmac.new(key, raw_id.encode("utf-8"), hashlib.sha256).hexdigest()
