"""The voiceprint registry as a file (RFC 0038 §5.1; RFC 0029 §3 and §7 for the age form): `voiceprints.age`
is one age file of one JSON document, sealed to the record's own recipients, replaced whole on each write
(the sealed bytes to a temporary name beside it, flushed, then renamed over it), the plaintext never on
disk. These tests pin what `write`, `read` and the write path of `update` guarantee when a step fails
half way (sealing, the write of the temporary file, fsync, the rename, a KeyboardInterrupt at each), what
the file must open to and with which identity, and what a write does with a stale temporary file, a plain
file, a stranger's file or a symlink under the name; and that a change of the record's recipients (`key
add-recipient`, `key remove-recipient`) never leaves a file an identity the record does not name opens,
whatever step of it fails or is interrupted. Every failure is injected; the embedder is a fake that
reads who speaks from a small JSON file standing in for the audio; no model, no network. Synthetic Oslo
persona (`voiceprints_record`)."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from persona import TZ
from speakers_record import CALL, DINNER, KARI_ID
from voiceprints_record import DIGEST, DIM, FakeEmbedder, as_bytes, as_text, seal, stored, voiced_record

from logbook.core import sealing, store, voiceprints
from logbook.core.chain import AGE_MAGIC
from logbook.core.store import Logbook

FILE = voiceprints.FILE
WHO = ("ines", "kari", "ola")


# -- the records ----------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """An empty record sealed to two recipients, this machine's identity the first."""
    return seal(Logbook.init(tmp_path / "lb", TZ), monkeypatch, tmp_path)


@pytest.fixture
def voiced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The dinner and the call, each with its fake audio, in a record sealed to two recipients."""
    lb = seal(Logbook.init(tmp_path / "lb", TZ), monkeypatch, tmp_path)
    voiced_record(lb)
    return Logbook(lb.root)


def _sealed_to(
    folder: Path, monkeypatch: pytest.MonkeyPatch, n: int
) -> tuple[Logbook, list[tuple[str, Path]]]:
    """An empty record sealed to `n` fresh recipients, each identity in a file of its own under
    `keys/`, the first this machine's (`LOGBOOK_IDENTITY_FILE`); the record and (secret, file) each."""
    lb = Logbook.init(folder / "lb", TZ)
    pairs = [sealing.generate_identity() for _ in range(n)]
    meta = lb.meta
    meta["recipients"] = [recipient for _secret, recipient in pairs]
    lb._save_meta(meta)
    keys: list[tuple[str, Path]] = []
    for i, (secret, _recipient) in enumerate(pairs):
        path = folder / "keys" / f"identity-{i}.txt"
        sealing.write_identity_file(path, secret, f"identity {i}")
        keys.append((secret, path))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(keys[0][1]))
    return Logbook(lb.root), keys


def _registry(n: int = 1) -> voiceprints.Registry:
    """A document as a write makes one: Kari's voiceprint from the dinner, the call's other voice and
    the dinner's first voice not yet named; `n` varies the seconds and the head, so two differ."""
    kari = voiceprints.Embedded(stored("kari"), 9.0 + n)
    return voiceprints.Registry(
        voiceprints.MODEL,
        DIGEST,
        DIM,
        f"head-{n}",
        {KARI_ID: voiceprints.Voiceprint(voiceprints.centre([kari]), kari.clean_s, {f"{DINNER}#S2": kari})},
        {
            f"{CALL}#system": voiceprints.Embedded(stored("ola"), 12.0),
            f"{DINNER}#S1": voiceprints.Embedded(stored("ines"), 10.0 + n),
        },
    )


def _siblings(root: Path) -> list[str]:
    """Every entry of the record folder whose name has the registry's in it: the file, a temporary
    file, anything else a write left."""
    return sorted(p.name for p in root.iterdir() if "voiceprints" in p.name)


def _temps(root: Path) -> list[str]:
    return [name for name in _siblings(root) if name != FILE]


def _opened(lb: Logbook) -> dict[str, Any]:
    found = voiceprints.read(Logbook(lb.root))
    assert found is not None
    return found.to_json()


def _needles() -> list[bytes]:
    """What the plaintext document would leave on disk: its format name and every vector's numbers,
    as JSON writes them (`as_text`) and packed as a model holds them (float64 only: a four-byte
    pattern can occur by chance in sealed bytes, an eight-byte one does not)."""
    found = [b'"voiceprints/1"']
    for who in WHO:
        found.extend(text.encode("utf-8") for text in as_text(stored(who)))
        found.extend(packed for packed in as_bytes(stored(who)) if len(packed) == 8)
    return found


def _files_under(*folders: Path) -> Iterator[Path]:
    for folder in folders:
        if folder.is_dir():
            yield from (p for p in folder.rglob("*") if p.is_file() and not p.is_symlink())


# -- the failures injected ------------------------------------------------------------------------------


class _Handle:
    """The temporary file's handle, as `write` opens it: every byte written through it is recorded;
    `spy.fail` makes the first write put half the bytes on disk and then fail, as a full disk does."""

    def __init__(self, fh: Any, spy: _Spy) -> None:
        self._fh = fh
        self._spy = spy
        spy.handles.append(self)
        spy.fds.add(fh.fileno())

    def write(self, data: bytes) -> int:
        if self._spy.fail is not None:
            self._fh.write(data[: len(data) // 2])
            self._fh.flush()
            raise self._spy.fail()
        self._spy.written.append(bytes(data))
        return int(self._fh.write(data))

    def flush(self) -> None:
        self._fh.flush()

    def fileno(self) -> int:
        return int(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    @property
    def closed(self) -> bool:
        return bool(self._fh.closed)

    def __enter__(self) -> _Handle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Spy:
    """Watches one write: the temporary file's handle (`_Handle`), which descriptors were fsynced,
    and what the rename found (the handle closed? the bytes synced first?); and fails one step
    when told (`install`)."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.handles: list[_Handle] = []
        self.fds: set[int] = set()
        self.synced: list[int] = []
        self.replaced: list[tuple[bool, bool]] = []  # (every handle closed, its bytes synced) at each rename
        self.fail: Callable[[], BaseException] | None = None

    @staticmethod
    def is_temp(path: Path) -> bool:
        return path.name.startswith(f".{FILE}.") and path.name.endswith(".tmp")

    def install(
        self,
        monkeypatch: pytest.MonkeyPatch,
        step: str | None = None,
        error: Callable[[], BaseException] | None = None,
    ) -> None:
        """Watch `Path.open` of the temporary file, `os.fsync` of its descriptor and `os.replace` over
        the registry; with `step`, that step raises `error()`."""
        spy = self
        real_open, real_fsync, real_replace = Path.open, os.fsync, os.replace

        def open_(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            fh = real_open(self, mode, *args, **kwargs)
            return _Handle(fh, spy) if "w" in mode and spy.is_temp(self) else fh

        def fsync(fd: int) -> None:
            if fd in spy.fds:
                if step == "fsync":
                    assert error is not None
                    raise error()
                spy.synced.append(fd)
            real_fsync(fd)

        def replace(src: Any, dst: Any) -> None:
            if Path(dst).name == FILE:
                spy.replaced.append((all(h.closed for h in spy.handles), bool(spy.synced)))
                if step == "replace":
                    assert error is not None
                    raise error()
            real_replace(src, dst)

        def seal_bytes(data: bytes, recipients: Any) -> bytes:
            assert error is not None
            raise error()

        monkeypatch.setattr(Path, "open", open_)
        monkeypatch.setattr(os, "fsync", fsync)
        monkeypatch.setattr(os, "replace", replace)
        if step == "write":
            self.fail = error
        if step == "seal":
            monkeypatch.setattr(sealing, "seal_bytes", seal_bytes)


FAILURES: list[tuple[str, Callable[[], BaseException]]] = [
    ("seal", sealing.MissingExtra),  # pyrage is not installed, found at the first seal
    ("seal", KeyboardInterrupt),
    ("write", lambda: OSError(errno.ENOSPC, "No space left on device")),  # half the bytes are on disk
    ("write", KeyboardInterrupt),
    ("fsync", lambda: OSError(errno.EIO, "Input/output error")),
    ("fsync", KeyboardInterrupt),
    # on Windows, a reader that holds the old file open while it is replaced
    ("replace", lambda: PermissionError(errno.EACCES, "Permission denied")),
    ("replace", KeyboardInterrupt),
]
FAILURE_IDS = [f"{step}-{type(error()).__name__}" for step, error in FAILURES]


# -- a write, and what it leaves ------------------------------------------------------------------------


def test_a_write_leaves_one_sealed_file_that_opens_to_the_document(lb: Logbook) -> None:
    assert voiceprints.read(lb) is None and voiceprints.about(lb) is None and _siblings(lb.root) == []
    path = voiceprints.write(lb, _registry(1))
    assert path == lb.root / FILE and _siblings(lb.root) == [FILE]
    first = path.read_bytes()
    assert first.startswith(AGE_MAGIC)
    assert _opened(lb) == _registry(1).to_json()
    voiceprints.write(lb, _registry(2))
    second = path.read_bytes()
    assert second.startswith(AGE_MAGIC) and second != first, "replaced whole"
    assert _opened(lb) == _registry(2).to_json() and _siblings(lb.root) == [FILE]
    voiceprints.write(lb, _registry(2))
    assert path.read_bytes() != second, "sealing is randomised (RFC 0029 §3): a fresh file key each write"
    assert _opened(lb) == _registry(2).to_json()


def test_the_bytes_are_flushed_and_the_handle_closed_before_the_rename_and_nothing_stays_open(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _Spy()
    spy.install(monkeypatch)
    path = voiceprints.write(lb, _registry())
    assert len(spy.handles) == 1 and spy.replaced == [(True, True)], "closed and fsynced, then renamed"
    assert b"".join(spy.written) == path.read_bytes()
    assert voiceprints.read(lb) is not None and voiceprints.about(lb) is not None
    path.unlink()  # Windows refuses while any handle holds the file: `write`, `read` and `about` left none
    assert not path.exists() and _siblings(lb.root) == []


@pytest.mark.parametrize(("step", "error"), FAILURES, ids=FAILURE_IDS)
def test_a_failure_at_any_step_leaves_the_old_file_as_it_was_and_no_temporary_file(
    lb: Logbook, step: str, error: Callable[[], BaseException]
) -> None:
    path = voiceprints.write(lb, _registry(1))
    before = path.read_bytes()
    with pytest.MonkeyPatch.context() as mp:
        _Spy().install(mp, step, error)
        with pytest.raises(type(error())):
            voiceprints.write(lb, _registry(2))
    assert path.read_bytes() == before, "byte for byte the old file"
    assert _siblings(lb.root) == [FILE], "no temporary file left"
    assert _opened(lb) == _registry(1).to_json()
    voiceprints.write(lb, _registry(3))  # the module recovered: the next write goes through
    assert _opened(lb) == _registry(3).to_json() and _siblings(lb.root) == [FILE]


@pytest.mark.parametrize(("step", "error"), FAILURES, ids=FAILURE_IDS)
def test_a_failure_before_the_first_write_leaves_no_file(
    lb: Logbook, step: str, error: Callable[[], BaseException]
) -> None:
    with pytest.MonkeyPatch.context() as mp:
        _Spy().install(mp, step, error)
        with pytest.raises(type(error())):
            voiceprints.write(lb, _registry())
    assert _siblings(lb.root) == [] and voiceprints.read(lb) is None and voiceprints.about(lb) is None


def test_a_stale_temporary_file_of_a_crashed_write_is_removed_by_the_next_write(lb: Logbook) -> None:
    stale = [lb.root / f".{FILE}.424242.tmp", lb.root / f".{FILE}.{os.getpid()}.tmp"]
    for path in stale:
        path.write_bytes(AGE_MAGIC + b"half of an earlier write")
    assert voiceprints.read(lb) is None, "a temporary file is never the registry"
    voiceprints.write(lb, _registry())
    assert _siblings(lb.root) == [FILE] and not any(p.exists() for p in stale)
    assert _opened(lb) == _registry().to_json()


# -- never plain, sealed to the recipients ----------------------------------------------------------------


def test_the_plaintext_never_touches_the_disk(
    voiced: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through a write that hears (the audio is opened to a temporary copy for the decoder): every
    byte that went through the temporary file is the sealed file's, and no file under the record,
    the system temp dir or the identity folder holds the document or a number of a vector."""
    system_tmp = tmp_path / "system-tmp"
    system_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_tmp))
    spy = _Spy()
    spy.install(monkeypatch)
    summary = voiceprints.update(voiced, FakeEmbedder())
    assert summary.written and summary.people == 1 and summary.voices == 3
    path = voiced.root / FILE
    document = _opened(voiced)
    plain = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    needles = _needles()
    assert all(text in plain for text in needles if len(text) > 8), "the needles would find the document"
    sealed = b"".join(spy.written)
    assert sealed.startswith(AGE_MAGIC) and sealed == path.read_bytes()
    assert not any(needle in sealed for needle in needles)
    for file in _files_under(tmp_path):
        data = file.read_bytes()
        assert not any(needle in data for needle in needles), file
    assert list(_files_under(system_tmp)) == [], "the decoder's temporary copies are gone"


def test_the_file_opens_with_each_recipients_identity_and_with_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, keys = _sealed_to(tmp_path, monkeypatch, 3)
    path = voiceprints.write(lb, _registry())
    data = path.read_bytes()
    header = data.split(b"\n---", 1)[0]
    assert header.count(b"\n-> X25519 ") == 3, "one stanza per recipient logbook.json names, no more"
    for secret, file in keys:
        identity = sealing.parse_identity(secret)
        assert sealing.open_sealed_bytes(data, [identity]) == _registry().to_bytes()
        monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(file))
        assert _opened(lb) == _registry().to_json()
    stranger, _recipient = sealing.generate_identity()
    with pytest.raises(sealing.SealError):
        sealing.open_sealed_bytes(data, [sealing.parse_identity(stranger)])
    other = tmp_path / "keys" / "stranger.txt"
    sealing.write_identity_file(other, stranger, "not this record's")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(other))
    with pytest.raises(voiceprints.RegistryError, match="does not open"):
        voiceprints.read(Logbook(lb.root))


def test_a_write_seals_to_the_recipients_logbook_json_names_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recipient added to `logbook.json` by hand opens the file from the next write on."""
    lb, _keys = _sealed_to(tmp_path, monkeypatch, 2)
    voiceprints.write(lb, _registry())
    secret, recipient = sealing.generate_identity()
    identity = sealing.parse_identity(secret)
    with pytest.raises(sealing.SealError):
        sealing.open_sealed_bytes((lb.root / FILE).read_bytes(), [identity])
    meta = lb.meta
    meta["recipients"] = [*meta["recipients"], recipient]
    lb._save_meta(meta)
    lb = Logbook(lb.root)
    assert voiceprints.update(lb).written
    assert sealing.open_sealed_bytes((lb.root / FILE).read_bytes(), [identity]).startswith(b"{")


def test_a_record_without_recipients_gets_no_file(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "open", TZ)
    voiced_record(lb)
    with pytest.raises(voiceprints.RegistryError, match="names no recipients"):
        voiceprints.write(lb, _registry())
    assert _siblings(lb.root) == []
    embedder = FakeEmbedder()
    assert voiceprints.update(lb, embedder).state == voiceprints.NO_RECIPIENTS
    assert _siblings(lb.root) == [] and embedder.loaded == [], "nothing heard either"
    meta = lb.meta
    meta["recipients"] = ["not a recipient", 42]  # names nothing `age1…`: names none
    lb._save_meta(meta)
    lb = Logbook(lb.root)
    with pytest.raises(voiceprints.RegistryError, match="names no recipients"):
        voiceprints.write(lb, _registry())
    assert voiceprints.update(lb, FakeEmbedder()).state == voiceprints.NO_RECIPIENTS
    assert _siblings(lb.root) == []


# -- what is found under the name -------------------------------------------------------------------------


def _foreign(lb: Logbook, kind: str) -> bytes:
    """Bytes that are not this record's registry, under its name."""
    if kind == "plain":
        return _registry().to_bytes()
    if kind == "half":
        return AGE_MAGIC + b"\x00" * 200  # a header and no body: what a lesser write leaves on a crash
    if kind == "strangers":
        return sealing.seal_bytes(_registry().to_bytes(), [sealing.generate_identity()[1] for _ in range(2)])
    if kind == "not-json":
        return sealing.seal_bytes(b"not a document", lb.recipients)
    assert kind == "not-the-format"
    return sealing.seal_bytes(b'{"format":"places/1"}', lb.recipients)


FOREIGN = [
    ("plain", "is not sealed"),
    ("half", "does not open"),
    ("strangers", "does not open"),
    ("not-json", "is not JSON"),
    ("not-the-format", "is not a voiceprints/1 document"),
]


@pytest.mark.parametrize(
    ("kind", "said"),
    FOREIGN,
)
def test_a_file_that_is_not_the_registry_is_refused_in_one_sentence_naming_nothing_in_it(
    voiced: Logbook, kind: str, said: str
) -> None:
    (voiced.root / FILE).write_bytes(_foreign(voiced, kind))
    with pytest.raises(voiceprints.RegistryError, match=said) as e:
        voiceprints.read(voiced)
    message = str(e.value)
    assert message.startswith(FILE) and "\n" not in message
    assert not any(needle.decode("utf-8", "replace") in message for needle in _needles() if needle.isascii())


@pytest.mark.parametrize(("kind", "said"), FOREIGN)
def test_a_file_that_is_not_the_registry_is_left_without_a_model_and_replaced_by_a_write_that_hears(
    voiced: Logbook, kind: str, said: str
) -> None:
    path = voiced.root / FILE
    planted = _foreign(voiced, kind)
    path.write_bytes(planted)
    with pytest.raises(voiceprints.RegistryError, match=said) as e:
        voiceprints.read(voiced)
    message = str(e.value)
    about = voiceprints.about(voiced)
    assert about is not None and about.error == message and about.model is None
    summary = voiceprints.update(voiced)  # without a model it cannot make the file again
    assert summary.state == voiceprints.UNREADABLE and summary.reason == message
    assert path.read_bytes() == planted and _siblings(voiced.root) == [FILE]
    summary = voiceprints.update(voiced, FakeEmbedder())
    assert summary.state == voiceprints.REBUILT and summary.reason == message
    assert path.read_bytes().startswith(AGE_MAGIC) and _siblings(voiced.root) == [FILE]
    found = voiceprints.read(voiced)
    assert found is not None and found.voices[f"{DINNER}#S2"].embedding == stored("kari")


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):  # Windows without the privilege
        pytest.skip("this platform or user cannot make a symbolic link")


def test_a_symlink_under_the_name_is_replaced_and_what_it_pointed_at_is_untouched(
    lb: Logbook, tmp_path: Path
) -> None:
    decoy = tmp_path / "elsewhere.txt"
    decoy.write_bytes(b"not the registry\n")
    path = lb.root / FILE
    _symlink(decoy, path)
    with pytest.raises(voiceprints.RegistryError, match="is not sealed"):
        voiceprints.read(lb)
    voiceprints.write(lb, _registry(1))
    assert not path.is_symlink() and path.read_bytes().startswith(AGE_MAGIC)
    assert decoy.read_bytes() == b"not the registry\n", "the rename replaces the link, not what it points at"
    assert _opened(lb) == _registry(1).to_json()
    tmp = lb.root / f".{FILE}.{os.getpid()}.tmp"
    _symlink(decoy, tmp)
    voiceprints.write(lb, _registry(2))
    assert not tmp.exists() and not tmp.is_symlink() and decoy.read_bytes() == b"not the registry\n"
    assert _opened(lb) == _registry(2).to_json() and _siblings(lb.root) == [FILE]


# -- the write path of `update` ---------------------------------------------------------------------------


def _watching_the_lock(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """How many `writer` blocks of this process are open, counted at the moments that matter."""
    depth = {"now": 0}
    real = Logbook.writer

    @contextlib.contextmanager
    def held(self: Logbook, *args: Any, **kwargs: Any) -> Iterator[None]:
        with real(self, *args, **kwargs):
            depth["now"] += 1
            try:
                yield
            finally:
                depth["now"] -= 1

    monkeypatch.setattr(Logbook, "writer", held)
    return depth


def test_update_hears_before_the_writer_lock_and_writes_under_it(
    voiced: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    depth = _watching_the_lock(monkeypatch)
    seen: dict[str, list[int]] = {"load": [], "open": []}

    class Embedder(FakeEmbedder):
        def load(self, path: Path) -> tuple[list[int], int]:
            seen["load"].append(depth["now"])
            return super().load(path)

    real_open = Path.open

    def open_(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "w" in mode and _Spy.is_temp(self):
            seen["open"].append(depth["now"])
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_)
    assert voiceprints.update(voiced, Embedder()).written
    assert seen["load"] == [0, 0], "the hearing is done before the lock is taken"
    assert seen["open"] == [1], "the file is written under it"
    assert not (voiced.root / "state" / "writer.lock").exists(), "and it is released"


@pytest.mark.parametrize(("step", "error"), FAILURES, ids=FAILURE_IDS)
def test_a_failed_write_of_update_leaves_the_old_file_and_releases_the_lock(
    voiced: Logbook, step: str, error: Callable[[], BaseException]
) -> None:
    assert voiceprints.update(voiced, FakeEmbedder()).written
    path = voiced.root / FILE
    before = path.read_bytes()
    with pytest.MonkeyPatch.context() as mp:
        _Spy().install(mp, step, error)
        with pytest.raises((type(error()), voiceprints.RegistryError)):
            voiceprints.update(voiced)
    assert path.read_bytes() == before and _siblings(voiced.root) == [FILE]
    assert not (voiced.root / "state" / "writer.lock").exists(), "the lock is released on the way out"
    assert voiceprints.update(voiced).written, "and the next write goes through"
    found = voiceprints.read(voiced)
    assert found is not None and found.voices[f"{DINNER}#S2"].embedding == stored("kari")


def test_a_disk_error_of_the_write_is_one_sentence_naming_the_file(
    voiced: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert voiceprints.update(voiced, FakeEmbedder()).written
    path = voiced.root / FILE
    before = path.read_bytes()
    _Spy().install(monkeypatch, "replace", lambda: PermissionError(errno.EACCES, "Permission denied"))
    with pytest.raises(voiceprints.RegistryError, match=FILE) as e:
        voiceprints.update(voiced)
    assert "\n" not in str(e.value) and "Permission denied" in str(e.value)
    assert path.read_bytes() == before and _siblings(voiced.root) == [FILE]


def test_two_writes_of_one_process_at_once_leave_one_whole_file(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    voiceprints.write(lb, _registry(1))
    meeting = threading.Barrier(2, timeout=1.0)  # both writes inside the temporary file at the same moment
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        with contextlib.suppress(threading.BrokenBarrierError):  # a serialised write waits here alone
            meeting.wait()
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    errors: list[BaseException] = []

    def go(n: int) -> None:
        try:
            voiceprints.write(lb, _registry(n))
        except BaseException as e:  # whatever a thread raised is the finding
            errors.append(e)

    threads = [threading.Thread(target=go, args=(n,)) for n in (2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _opened(lb) in (_registry(2).to_json(), _registry(3).to_json()), "one of the two, whole"
    assert _siblings(lb.root) == [FILE]


# -- a change of the recipients (RFC 0029 §6.4) ---------------------------------------------------------


def _keyed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n: int = 3) -> tuple[Logbook, list[str]]:
    """The dinner and the call in a record sealed to `n` recipients, its registry written and the
    command line pointed at it; the record and each recipient's identity (`secret`), in order."""
    lb, keys = _sealed_to(tmp_path, monkeypatch, n)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    voiced_record(lb)
    lb = Logbook(lb.root)
    assert voiceprints.update(lb, FakeEmbedder()).written
    return lb, [secret for secret, _path in keys]


def _opens(path: Path, secret: str) -> bool:
    """Whether the identity `secret` opens the sealed file at `path`."""
    try:
        sealing.open_sealed_bytes(path.read_bytes(), [sealing.parse_identity(secret)])
    except sealing.SealError:
        return False
    return True


def _key(*args: str) -> None:
    from logbook import cli

    cli.main(["key", *args])


def _failing(mp: pytest.MonkeyPatch, step: str, error: Callable[[], BaseException]) -> None:
    """`voiceprints.reseal` with `step` of its write failing (`_Spy`), and nothing else: the spy is
    there for the registry's reseal alone, so the record's own reseal runs as it always does."""
    real = voiceprints.reseal

    def reseal(lb: Logbook, recipients: list[str]) -> str | None:
        with pytest.MonkeyPatch.context() as inner:
            _Spy().install(inner, step, error)
            return real(lb, recipients)

    mp.setattr(voiceprints, "reseal", reseal)


def _rekeyed(lb: Logbook) -> bool:
    return any(line["kind"] == store.REKEY for line in Logbook(lb.root).lines())


def test_a_rotation_of_the_recipients_leaves_no_registry_the_removed_identity_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`key add-recipient` and `key remove-recipient` reseal every sealed line and file (RFC 0029
    §6.4), and the voiceprints with them: to the new list, and to nothing else."""
    lb, (kept_secret, removed_secret) = _keyed(tmp_path, monkeypatch, 2)
    removed_recipient = lb.recipients[1]
    new_secret, new_recipient = sealing.generate_identity()
    _key("add-recipient", "--recipient", new_recipient)
    _key("remove-recipient", "--recipient", removed_recipient)
    assert capsys.readouterr().out.count("voiceprints.age sealed again to the new recipients") == 2
    path = lb.root / FILE
    assert not _opens(path, removed_secret)
    assert _opens(path, kept_secret) and _opens(path, new_secret)
    assert _temps(lb.root) == []


def test_remove_recipient_seals_the_registry_again_before_the_record_and_add_recipient_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The order is the guarantee: when a recipient goes, the registry is theirs no longer before
    a line of the record is resealed; when one comes, it is theirs only once the record is."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    new_secret, new_recipient = sealing.generate_identity()
    everyone = [*secrets, new_secret]
    path = lb.root / FILE
    seen: list[list[bool]] = []
    real = Logbook.reseal

    def reseal(self: Logbook, recipients: list[str], progress: Any = None) -> dict[str, Any]:
        seen.append([_opens(path, secret) for secret in everyone])
        return real(self, recipients, progress)

    monkeypatch.setattr(Logbook, "reseal", reseal)
    _key("remove-recipient", "--recipient", lb.recipients[2])
    _key("add-recipient", "--recipient", new_recipient)
    assert seen == [[True, True, False, False], [True, True, False, False]]
    assert [_opens(path, secret) for secret in everyone] == [True, True, False, True]


def test_a_key_change_takes_the_writer_lock_once_for_the_registry_and_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One hold, so no other writer comes between the two: `update` writes under the same lock,
    and a write between them would seal the registry to the list logbook.json names at that moment."""
    lb, _secrets = _keyed(tmp_path, monkeypatch)
    taken: list[str] = []
    real = store._take_lock

    def take(path: Path, command: str, wait: bool, notice: Callable[[str], None]) -> None:
        taken.append(command)
        real(path, command, wait, notice)

    monkeypatch.setattr(store, "_take_lock", take)
    _key("remove-recipient", "--recipient", lb.recipients[2])
    assert taken == ["key remove-recipient"]
    _key("add-recipient", "--recipient", sealing.generate_identity()[1])
    assert taken == ["key remove-recipient", "key add-recipient"]


@pytest.mark.parametrize(("step", "error"), FAILURES, ids=FAILURE_IDS)
def test_a_failure_at_any_step_of_remove_recipient_leaves_no_registry_the_removed_identity_opens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    step: str,
    error: Callable[[], BaseException],
) -> None:
    """A failure at the registry's seal, write, fsync or rename, a KeyboardInterrupt too: the file
    goes rather than stay sealed to the old list. A failure goes on to the record, said; an
    interrupt stops before it, the record as it was."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    removed = lb.recipients[2]
    interrupted = not isinstance(error(), Exception)
    with pytest.MonkeyPatch.context() as mp:
        _failing(mp, step, error)
        with pytest.raises(KeyboardInterrupt) if interrupted else contextlib.nullcontext():
            _key("remove-recipient", "--recipient", removed)
    path = lb.root / FILE
    assert not path.exists(), "removed: a cache, made again by the next write that hears"
    assert _temps(lb.root) == []
    assert not (lb.root / "state" / "writer.lock").exists()
    if interrupted:
        assert removed in Logbook(lb.root).recipients and not _rekeyed(lb), "stopped before the record"
        _key("remove-recipient", "--recipient", removed)
    else:
        assert f"{FILE} removed" in capsys.readouterr().out
    assert removed not in Logbook(lb.root).recipients and _rekeyed(lb)
    assert voiceprints.update(Logbook(lb.root), FakeEmbedder()).written
    assert [_opens(path, secret) for secret in secrets] == [True, True, False]


@pytest.mark.parametrize(
    "error",
    [lambda: OSError(errno.ENOSPC, "No space left on device"), KeyboardInterrupt],
    ids=["OSError", "KeyboardInterrupt"],
)
def test_remove_recipient_stopped_in_the_record_leaves_the_registry_to_those_who_stay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Callable[[], BaseException],
) -> None:
    """The registry is sealed again first, so a reseal of the record that stops half way leaves
    it opening with fewer identities than the record, never more; the change run again finishes."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    removed, before = lb.recipients[2], Logbook(lb.root).meta

    def broken(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        raise error()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Logbook, "_rewrite", broken)
        with pytest.raises(type(error())):
            _key("remove-recipient", "--recipient", removed)
    said = capsys.readouterr().err
    assert f"{FILE} was sealed again first, to the recipients who stay" in said
    assert "the change can be run again" in said
    path = lb.root / FILE
    assert [_opens(path, secret) for secret in secrets] == [True, True, False]
    after = Logbook(lb.root).meta
    assert (after["recipients"], after["head"]) == (before["recipients"], before["head"])
    assert _temps(lb.root) == [] and not (lb.root / "state" / "writer.lock").exists()
    _key("remove-recipient", "--recipient", removed)
    assert removed not in Logbook(lb.root).recipients
    assert [_opens(path, secret) for secret in secrets] == [True, True, False]


@pytest.mark.parametrize(("step", "error"), FAILURES, ids=FAILURE_IDS)
def test_a_failure_at_any_step_of_add_recipient_leaves_no_registry_beyond_the_record_s_recipients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, error: Callable[[], BaseException]
) -> None:
    """The registry is sealed again after the record, so the record already names the new
    recipient when its step fails; it goes rather than stay half done, and a write makes it again."""
    lb, secrets = _keyed(tmp_path, monkeypatch, 2)
    new_secret, new_recipient = sealing.generate_identity()
    interrupted = not isinstance(error(), Exception)
    with pytest.MonkeyPatch.context() as mp:
        _failing(mp, step, error)
        with pytest.raises(KeyboardInterrupt) if interrupted else contextlib.nullcontext():
            _key("add-recipient", "--recipient", new_recipient)
    path = lb.root / FILE
    assert new_recipient in Logbook(lb.root).recipients and _rekeyed(lb), "the record first"
    assert not path.exists() and _temps(lb.root) == []
    assert voiceprints.update(Logbook(lb.root), FakeEmbedder()).written
    assert [_opens(path, secret) for secret in [*secrets, new_secret]] == [True, True, True]


def _stuck(mp: pytest.MonkeyPatch) -> None:
    """The registry can be neither replaced nor removed: as on Windows while another program holds
    it open."""
    _Spy().install(mp, "replace", lambda: PermissionError(errno.EACCES, "Permission denied"))
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == FILE:
            raise PermissionError(errno.EACCES, "Permission denied")
        real_unlink(self, missing_ok=missing_ok)

    mp.setattr(Path, "unlink", unlink)


def test_a_registry_that_can_be_neither_sealed_again_nor_removed_stops_remove_recipient_before_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _secrets = _keyed(tmp_path, monkeypatch)
    path = lb.root / FILE
    before, meta = path.read_bytes(), Logbook(lb.root).meta
    with pytest.MonkeyPatch.context() as mp:
        _stuck(mp)
        with pytest.raises(SystemExit) as e:
            _key("remove-recipient", "--recipient", lb.recipients[2])
    assert e.value.code == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("key remove-recipient: ") and FILE in err and "\n" not in err
    assert "Permission denied" in err and "the record was not changed" in err
    assert path.read_bytes() == before and Logbook(lb.root).meta == meta and not _rekeyed(lb)
    assert _temps(lb.root) == []


def test_a_registry_that_can_be_neither_sealed_again_nor_removed_after_add_recipient_is_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """After the record, so the change stands; the file stays sealed to the old list, every one of
    whom the record still names, and the next write seals it to the new one."""
    lb, secrets = _keyed(tmp_path, monkeypatch, 2)
    new_secret, new_recipient = sealing.generate_identity()
    path = lb.root / FILE
    before = path.read_bytes()
    with pytest.MonkeyPatch.context() as mp:
        _stuck(mp)
        _key("add-recipient", "--recipient", new_recipient)
    err = capsys.readouterr().err
    assert FILE in err and "Permission denied" in err
    assert new_recipient in Logbook(lb.root).recipients and path.read_bytes() == before
    assert voiceprints.update(Logbook(lb.root)).written
    assert [_opens(path, secret) for secret in [*secrets, new_secret]] == [True, True, True]


@pytest.mark.parametrize("registry", ["this record's", "a stranger's"])
def test_remove_recipient_leaves_no_temporary_file_a_crashed_write_sealed_to_the_old_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registry: str
) -> None:
    """A write killed between its temporary file and the rename leaves sealed bytes under a
    temporary name, sealed to the list of that moment: the key change removes them, whether the
    registry itself is sealed again or removed."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    path = lb.root / FILE
    if registry == "a stranger's":
        path.write_bytes(sealing.seal_bytes(b"{}", [sealing.generate_identity()[1]]))
    stale = lb.root / f".{FILE}.424242.tmp"
    stale.write_bytes(sealing.seal_bytes(_registry().to_bytes(), lb.recipients))
    assert _opens(stale, secrets[2])
    _key("remove-recipient", "--recipient", lb.recipients[2])
    assert _temps(lb.root) == []
    assert not path.exists() if registry == "a stranger's" else not _opens(path, secrets[2])


def test_a_key_change_the_record_refuses_leaves_the_registry_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fewer than two recipients left, no identity here, or one that is none of the record's
    recipients: refused before the registry is touched, so a refused change seals nothing again and
    removes nothing."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    path = lb.root / FILE
    before = path.read_bytes()
    with pytest.raises(SystemExit) as e:
        _key("remove-recipient", "--recipient", lb.recipients[1], "--recipient", lb.recipients[2])
    assert e.value.code == 2 and "2 recipients at least" in capsys.readouterr().err
    assert path.read_bytes() == before
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(tmp_path / "keys" / "absent.txt"))
    with pytest.raises(SystemExit) as e:
        _key("remove-recipient", "--recipient", lb.recipients[2])
    assert e.value.code == 2 and "identity" in capsys.readouterr().err
    assert path.read_bytes() == before
    stranger = tmp_path / "keys" / "stranger.txt"
    sealing.write_identity_file(stranger, sealing.generate_identity()[0], "none of this record's")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(stranger))
    with pytest.raises(SystemExit) as e:
        _key("remove-recipient", "--recipient", lb.recipients[2])
    assert e.value.code == 2 and "not one of this record's recipients" in capsys.readouterr().err
    assert path.read_bytes() == before and [_opens(path, secret) for secret in secrets] == [True] * 3
    assert Logbook(lb.root).recipients == lb.recipients and not _rekeyed(lb)


def test_a_write_of_another_thread_sealed_before_a_key_change_does_not_land_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer lock re-enters for every thread of a process (the Library answers in threads), so
    `update` in a second thread runs inside the key change's hold. A write that had read the old
    list and sealed to it must not rename its file over the registry once the change is done: it
    seals and renames under `_WRITING`, which the key change holds throughout."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    removed = lb.recipients[2]
    sealed_old = threading.Event()
    changed = threading.Event()
    real = sealing.seal_bytes
    errors: list[BaseException] = []

    def seal_bytes(data: bytes, recipients: list[str]) -> bytes:
        out = real(data, recipients)
        if threading.current_thread() is other:
            sealed_old.set()
            changed.wait(1.0)  # the key change waits for this write now, so the wait ends by itself
        return out

    def go() -> None:
        try:
            voiceprints.update(Logbook(lb.root))
        except BaseException as e:  # whatever the thread raised is the finding
            errors.append(e)

    monkeypatch.setattr(sealing, "seal_bytes", seal_bytes)
    other = threading.Thread(target=go)
    other.start()
    assert sealed_old.wait(5.0)
    try:
        _key("remove-recipient", "--recipient", removed)
    finally:
        changed.set()
        other.join(10.0)
    assert not other.is_alive() and errors == []
    assert removed not in Logbook(lb.root).recipients
    assert [_opens(lb.root / FILE, secret) for secret in secrets] == [True, True, False]


def test_a_write_of_another_thread_between_the_registry_and_the_record_waits_for_the_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write of another thread that comes after the registry is sealed to those who stay and
    before logbook.json names them would seal it to the list of that moment, the removed
    identity's among them: it waits until the change is done, then seals to the new list."""
    lb, secrets = _keyed(tmp_path, monkeypatch)
    removed = lb.recipients[2]
    at_write = threading.Event()
    errors: list[BaseException] = []
    real_write = voiceprints.write

    def write(lb_: Logbook, registry: voiceprints.Registry, recipients: Any = None) -> Path:
        if threading.current_thread() is other:
            at_write.set()
        return real_write(lb_, registry, recipients)

    def go() -> None:
        try:
            voiceprints.update(Logbook(lb.root))
        except BaseException as e:
            errors.append(e)

    other = threading.Thread(target=go)
    real_reseal = Logbook.reseal

    def reseal(self: Logbook, recipients: list[str], progress: Any = None) -> dict[str, Any]:
        other.start()
        assert at_write.wait(5.0)
        other.join(0.5)  # a write that need not wait for the change is done by now
        return real_reseal(self, recipients, progress)

    monkeypatch.setattr(voiceprints, "write", write)
    monkeypatch.setattr(Logbook, "reseal", reseal)
    _key("remove-recipient", "--recipient", removed)
    other.join(10.0)
    assert not other.is_alive() and errors == []
    assert removed not in Logbook(lb.root).recipients
    assert [_opens(lb.root / FILE, secret) for secret in secrets] == [True, True, False]


def test_remove_recipient_reads_no_registry_through_a_symlink_and_says_what_it_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A link under the name is not the registry: never read through, never written through. The
    link goes; what it pointed at is not the registry's to seal again or delete, and is said."""
    lb, _secrets = _keyed(tmp_path, monkeypatch)
    path = lb.root / FILE
    elsewhere = tmp_path / "elsewhere" / "voiceprints-copy.age"
    elsewhere.parent.mkdir()
    os.replace(path, elsewhere)
    _symlink(elsewhere, path)
    before = elsewhere.read_bytes()
    _key("remove-recipient", "--recipient", lb.recipients[2])
    assert not path.exists() and not path.is_symlink()
    assert elsewhere.read_bytes() == before
    out = capsys.readouterr().out
    assert f"{FILE} was a link to another file" in out and "left as it was" in out


@pytest.mark.skipif(sys.platform == "win32", reason="a directory cannot be opened for fsync on Windows")
def test_a_registry_a_reseal_removes_is_gone_from_the_disk_too(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    (lb.root / FILE).write_bytes(sealing.seal_bytes(b"{}", [sealing.generate_identity()[1]]))
    synced: set[tuple[int, int]] = set()
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        st = os.fstat(fd)
        synced.add((st.st_dev, st.st_ino))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    said = voiceprints.reseal(lb, lb.recipients)
    assert said is not None and said.startswith(f"{FILE} removed") and not (lb.root / FILE).exists()
    folder = lb.root.stat()
    assert (folder.st_dev, folder.st_ino) in synced, "the record folder, after the unlink"


def test_a_rotation_removes_a_registry_this_machine_cannot_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, _keys = _sealed_to(tmp_path, monkeypatch, 2)
    (lb.root / FILE).write_bytes(sealing.seal_bytes(b"{}", [sealing.generate_identity()[1]]))
    said = voiceprints.reseal(Logbook(lb.root), lb.recipients)
    assert said is not None and said.startswith(f"{FILE} removed") and not (lb.root / FILE).exists()
    assert voiceprints.reseal(Logbook(lb.root), lb.recipients) is None


@pytest.mark.skipif(sys.platform == "win32", reason="a directory cannot be opened for fsync on Windows")
def test_the_renamed_entry_is_flushed_to_the_disk(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: set[tuple[int, int]] = set()
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        st = os.fstat(fd)
        synced.add((st.st_dev, st.st_ino))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    voiceprints.write(lb, _registry())
    folder = lb.root.stat()
    assert (folder.st_dev, folder.st_ino) in synced, "the record folder itself, after the rename"
