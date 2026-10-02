"""`logbook share day`, `logbook receive` and `logbook circle`: the shared-page bundle of RFC 0025.
Two synthetic records (`shared_day.py`: Ines and Ola Nordmann, who do not exist) share one Saturday
both ways; the receiver verifies the signature and every line's hash and keeps the page outside its
chain. The committed bundles under `tests/fixtures/share/` are the cross-implementation fixture."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from shared_day import (
    CREATED,
    DAY,
    FIXTURES,
    INES_BUNDLE,
    INES_ID,
    INES_SEED,
    OLA_BUNDLE,
    OLA_SEED,
    PHOTO_BYTES,
    both,
    use,
)

from logbook import cli, share
from logbook.chain import canonical_json
from logbook.store import Logbook

PHOTO_SHA = hashlib.sha256(PHOTO_BYTES).hexdigest()


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _failure(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    with pytest.raises(SystemExit) as e:
        cli.main(list(args))
    return int(e.value.code or 0), capsys.readouterr().err


def _members(bundle: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(bundle) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist()}


def _manifest(bundle: Path) -> dict[str, Any]:
    return json.loads(_members(bundle)["manifest.json"])


def _lines(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(s) for s in raw.decode("utf-8").splitlines() if s.strip()]


def _rewrite(bundle: Path, members: dict[str, bytes], seed: bytes | None = None) -> Path:
    """Write `members` as a bundle at `bundle`'s side; with `seed`, re-sign the manifest with that
    sender's key first (a sender who altered their own page, or an attacker with the key)."""
    if seed is not None:
        manifest = json.loads(members["manifest.json"])
        manifest.pop("signature", None)
        manifest["signature"] = share.sign(seed, manifest)
        members["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    out = bundle.with_name("altered.zip")
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return out


def _public(seed: bytes) -> str:
    return share.public_key(seed)


def _circle_add(monkeypatch: pytest.MonkeyPatch, lb: Logbook, name: str, seed: bytes) -> None:
    use(monkeypatch, lb)
    cli.main(["circle", "add", name, _public(seed)])


@pytest.fixture
def records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, Logbook]:
    return both(tmp_path, monkeypatch)


@pytest.fixture
def ines_page(records: tuple[Logbook, Logbook], tmp_path: Path) -> Path:
    """Ines's Saturday shared with Ola at tier 2, through the CLI."""
    out = tmp_path / "ines-to-ola.zip"
    cli.main(["share", "day", DAY, "--to", "ola", "--tier", "2", "--out", str(out)])
    return out


# -- share --------------------------------------------------------------------------------------------------


def test_share_writes_a_signed_bundle_of_the_day(records: tuple[Logbook, Logbook], ines_page: Path):
    ines, _ = records
    members = _members(ines_page)
    assert set(members) == {"manifest.json", "lines.jsonl", "package.json", f"attachments/{PHOTO_SHA}"}
    manifest = _manifest(ines_page)
    assert manifest["schema"] == share.SCHEMA
    assert manifest["from"] == INES_ID
    assert manifest["to"] == "ola"
    assert manifest["date"] == DAY
    assert manifest["tz"] == "Europe/Oslo"
    assert manifest["max_tier"] == 2
    assert manifest["lines"] == 4  # two fixes, the photo, the note
    assert manifest["held_back"] == 1  # the steps, tier 3
    assert manifest["attachments"] == [
        {"sha256": PHOTO_SHA, "bytes": len(PHOTO_BYTES), "media_type": "image/jpeg"}
    ]
    assert manifest["key"] == ines.meta["share_key"] == _public(INES_SEED)
    assert manifest["lines_sha256"] == hashlib.sha256(members["lines.jsonl"]).hexdigest()
    assert manifest["package_sha256"] == hashlib.sha256(members["package.json"]).hexdigest()
    assert members[f"attachments/{PHOTO_SHA}"] == PHOTO_BYTES
    # The signature is Ed25519 over the canonical manifest without it, by the key logbook.json names.
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    assert share.verify(manifest["key"], unsigned, manifest["signature"])
    assert not share.verify(manifest["key"], {**unsigned, "lines": 5}, manifest["signature"])


def test_the_lines_are_the_record_s_own_verbatim_and_the_rest_of_the_day_stays_home(
    records: tuple[Logbook, Logbook], ines_page: Path
):
    ines, _ = records
    lines = _lines(_members(ines_page)["lines.jsonl"])
    by_seq = {line["seq"]: line for line in ines.lines()}
    assert [line["seq"] for line in lines] == [2, 4, 5, 7]  # in time order; the chain's own envelopes
    for line in lines:
        assert line == by_seq[line["seq"]]
    kinds = [line["kind"] for line in lines]
    assert "health-sample" not in kinds  # tier 3, above the page's tier
    assert "message" not in kinds  # retracted, and the retraction is not an event of the day
    assert all(line["at"] not in ("2026-06-12T21:00:00Z", "2026-06-13T22:30:00Z") for line in lines)
    package = json.loads(_members(ines_page)["package.json"])
    assert package["schema"] == "day-package/v1"
    assert package["date"] == DAY and package["owner_id"] == INES_ID
    assert [e["id"] for e in package["entries"]] == [line["id"] for line in lines]
    assert all("payload" not in e for e in package["entries"])
    assert package["attachments"] == [
        {"sha256": PHOTO_SHA, "bytes": len(PHOTO_BYTES), "media_type": "image/jpeg"}
    ]


def test_a_share_is_recorded_as_a_crossing_line(
    records: tuple[Logbook, Logbook], ines_page: Path, capsys: pytest.CaptureFixture[str]
):
    """ADR 0016: a crossing is never invisible. The page's head is the head before the line."""
    ines, _ = records
    last = list(ines.lines())[-1]
    manifest = _manifest(ines_page)
    assert last["kind"] == "crossing" and last["tier"] == 1 and last["source"] == "logbook"
    payload = last["payload"]
    assert payload["schema"] == "crossing/v1"
    assert payload["destination"] == "ola"
    assert payload["bundle_id"] == manifest["bundle_id"]
    assert payload["window"] == {"from": "2026-06-12T22:00:00Z", "to": "2026-06-13T22:00:00Z"}
    assert payload["tiers"] == [1, 2]
    assert payload["counts"]["crossed"] == 4 and payload["counts"]["held_back"] == 1
    assert payload["counts"]["by_tier"] == {"1": 3, "2": 1, "3": 0}
    assert payload["policy"] == {"file": "policy/crossing.json", "max_tier": 2}
    assert payload["logbook_head"] == manifest["logbook_head"] == last["prev"]
    assert payload["package_sha256"] == hashlib.sha256(_members(ines_page)["manifest.json"]).hexdigest()
    assert payload["extra"] == {"schema": share.SCHEMA, "date": DAY}
    out = _run(capsys, "verify")
    assert "valid" in out


def test_the_sharing_key_is_made_on_first_use_and_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    lb = Logbook.init(tmp_path / "fresh", "Europe/Oslo")
    use(monkeypatch, lb)
    lb.append_many(
        [
            {
                "at": f"{DAY}T10:00:00Z",
                "source": "manual",
                "kind": "note",
                "tier": 1,
                "payload": {"schema": "note/v1", "text": "hello"},
            }
        ]
    )
    _allow(lb, "ola", 1)
    assert "share_key" not in lb.meta
    key_file = share.key_path(str(lb.meta["owner_id"]))
    assert not key_file.exists()
    out = _run(capsys, "share", "day", DAY, "--to", "ola", "--out", str(tmp_path / "a.zip"))
    assert key_file.is_file()
    if sys.platform != "win32":
        assert key_file.stat().st_mode & 0o777 == 0o600
    public = lb.meta["share_key"]
    assert len(public) == 64 and public == share.public_key(share.read_key(key_file))
    assert f"key {public[:12]}" in out or public in out
    _run(capsys, "share", "day", DAY, "--to", "ola", "--out", str(tmp_path / "b.zip"))
    assert lb.meta["share_key"] == public  # reused, never rotated behind the owner's back
    assert _manifest(tmp_path / "b.zip")["key"] == public
    # The same key is the one `circle key` prints for handing to a friend.
    assert _run(capsys, "circle", "key").split()[0] == public
    # A record whose logbook.json names a key this machine does not hold is refused, naming the file.
    key_file.unlink()
    code, err = _failure(capsys, "share", "day", DAY, "--to", "ola", "--out", str(tmp_path / "c.zip"))
    assert code == 2 and str(key_file) in err and "share_key" in err
    assert not (tmp_path / "c.zip").exists()


def test_the_tier_gate_is_the_policy_s_per_destination(
    records: tuple[Logbook, Logbook], tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    ines, _ = records
    out = tmp_path / "page.zip"
    # The default is tier 1: the note stays home and is counted.
    _run(capsys, "share", "day", DAY, "--to", "ola", "--out", str(out))
    manifest = _manifest(out)
    assert manifest["max_tier"] == 1 and manifest["lines"] == 3 and manifest["held_back"] == 2
    assert all(line["tier"] == 1 for line in _lines(_members(out)["lines.jsonl"]))
    # Above the ceiling: refused, naming the file; nothing written, nothing appended.
    head = ines.meta["head"]
    code, err = _failure(
        capsys, "share", "day", DAY, "--to", "ola", "--tier", "3", "--out", str(tmp_path / "no.zip")
    )
    assert code == 2 and "policy/crossing.json" in err.replace("\\", "/") and "max_tier 2" in err
    assert not (tmp_path / "no.zip").exists() and ines.meta["head"] == head
    # A destination the policy does not name has no ceiling and gets nothing.
    code, err = _failure(capsys, "share", "day", DAY, "--to", "kari", "--out", str(tmp_path / "no.zip"))
    assert code == 2 and "kari" in err and "crossing.json" in err
    # A tier that is not 1, 2 or 3, a day that is not one, a name that is not a folder name.
    assert _failure(capsys, "share", "day", DAY, "--to", "ola", "--tier", "4")[0] == 2
    assert _failure(capsys, "share", "day", "2026-13-01", "--to", "ola")[0] == 2
    assert _failure(capsys, "share", "day", DAY, "--to", "../ola")[0] == 2


def test_the_default_output_is_under_the_record(
    records: tuple[Logbook, Logbook], capsys: pytest.CaptureFixture[str]
):
    ines, _ = records
    out = _run(capsys, "share", "day", DAY, "--to", "ola")
    bundle = ines.root / "export" / "share" / "ola" / f"{DAY}.zip"
    assert bundle.is_file() and str(bundle) in out
    assert "3 lines" in out and "ola" in out


def test_share_needs_the_extra(
    records: tuple[Logbook, Logbook],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(share, "_ed25519", lambda: (_ for _ in ()).throw(share.MissingExtra()))
    code, err = _failure(capsys, "share", "day", DAY, "--to", "ola", "--out", str(tmp_path / "x.zip"))
    assert code == 2 and "openlogbook[share]" in err


# -- circle -------------------------------------------------------------------------------------------------


def test_circle_add_and_list(records: tuple[Logbook, Logbook], capsys: pytest.CaptureFixture[str]):
    ines, _ = records
    assert _run(capsys, "circle").strip().startswith("nobody")
    _run(capsys, "circle", "add", "ola", _public(OLA_SEED))
    circle = json.loads((ines.root / "policy" / "circle.json").read_text(encoding="utf-8"))
    assert circle == {"ola": {"key": _public(OLA_SEED)}}
    out = _run(capsys, "circle")
    assert "ola" in out and _public(OLA_SEED) in out
    # The same key again is nothing; another key for the same name is refused, so a key is never
    # swapped by a typo; a key that is not 64 hex characters is refused.
    assert "already" in _run(capsys, "circle", "add", "ola", _public(OLA_SEED))
    code, err = _failure(capsys, "circle", "add", "ola", _public(INES_SEED))
    assert code == 2 and "ola" in err and "circle.json" in err
    assert _failure(capsys, "circle", "add", "kari", "abc")[0] == 2
    assert _failure(capsys, "circle", "add", "k/ari", _public(INES_SEED))[0] == 2
    assert json.loads((ines.root / "policy" / "circle.json").read_text(encoding="utf-8")) == circle


# -- receive ------------------------------------------------------------------------------------------------


def test_receive_verifies_and_stores_the_page_outside_the_chain(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    _, ola = records
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    before = ola.meta
    out = _run(capsys, "receive", str(ines_page))
    assert "from ines" in out and DAY in out and "4 lines" in out
    page = ola.root / "circle" / "ines" / DAY
    assert (page / "manifest.json").read_bytes() == _members(ines_page)["manifest.json"]
    assert (page / "lines.jsonl").read_bytes() == _members(ines_page)["lines.jsonl"]
    assert (page / "package.json").read_bytes() == _members(ines_page)["package.json"]
    assert (page / "attachments" / PHOTO_SHA).read_bytes() == PHOTO_BYTES
    received = json.loads((page / "received.json").read_text(encoding="utf-8"))
    assert received["from"] == "ines" and received["key"] == _public(INES_SEED)
    assert received["bundle_sha256"] == hashlib.sha256(ines_page.read_bytes()).hexdigest()
    # Nothing of Ola's own changed: not the chain, not the head, not the store.
    after = ola.meta
    assert (after["seq"], after["head"]) == (before["seq"], before["head"])
    assert not (ola.root / "attachments" / PHOTO_SHA).exists()
    assert sorted(ola.root.joinpath("logbook").glob("*/*.jsonl")) == [
        ola.root / "logbook" / "2026" / "06.jsonl"
    ]
    assert "valid" in _run(capsys, "verify")


def test_receive_with_from_names_the_key_to_check_against(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    _, ola = records
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    _circle_add(monkeypatch, ola, "kari", OLA_SEED)  # a key that is not Ines's, under another name
    code, err = _failure(capsys, "receive", str(ines_page), "--from", "kari")
    assert code == 1 and "kari" in err and "signature" in err
    assert not (ola.root / "circle").exists()
    _run(capsys, "receive", str(ines_page), "--from", "ines")
    assert (ola.root / "circle" / "ines" / DAY / "manifest.json").is_file()
    assert _failure(capsys, "receive", str(ines_page), "--from", "nils")[0] == 2


def test_receive_refuses_an_unknown_sender(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    _, ola = records
    use(monkeypatch, ola)
    code, err = _failure(capsys, "receive", str(ines_page))
    assert code == 1 and "circle add" in err and INES_ID in err
    assert not (ola.root / "circle").exists()


def test_receive_refuses_a_tampered_line(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A line whose text was changed after it was hashed: refused whether or not the sender
    re-signed the page, and nothing is stored either way."""
    _, ola = records
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    members = _members(ines_page)
    lines = _lines(members["lines.jsonl"])
    lines[2]["payload"]["text"] = "Anchored off Hovedøya alone."
    raw = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines).encode(
        "utf-8"
    )
    manifest = json.loads(members["manifest.json"])
    manifest["lines_sha256"] = hashlib.sha256(raw).hexdigest()
    altered = dict(members, **{"lines.jsonl": raw, "manifest.json": json.dumps(manifest).encode("utf-8")})
    # Changed and not re-signed: the signature no longer covers the manifest.
    code, err = _failure(capsys, "receive", str(_rewrite(ines_page, dict(altered))))
    assert code == 1 and "signature" in err
    # Re-signed by the sender's own key: the line still does not hash to what it claims.
    code, err = _failure(capsys, "receive", str(_rewrite(ines_page, dict(altered), INES_SEED)))
    assert code == 1 and "line 3" in err and "hash" in err
    assert not (ola.root / "circle").exists()


def test_receive_checks_every_file_against_the_manifest(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    _, ola = records
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    good = _members(ines_page)

    def refused(members: dict[str, bytes], *words: str, seed: bytes | None = INES_SEED) -> None:
        code, err = _failure(capsys, "receive", str(_rewrite(ines_page, members, seed)))
        assert code == 1, err
        for word in words:
            assert word in err, (word, err)
        assert not (ola.root / "circle").exists()

    # An attachment whose bytes are not its name; one the manifest lists but the zip lacks; a
    # file the manifest does not name; a path that would climb out of the page.
    refused({**good, f"attachments/{PHOTO_SHA}": b"other bytes"}, PHOTO_SHA[:12], "hash")
    refused({k: v for k, v in good.items() if not k.startswith("attachments/")}, PHOTO_SHA[:12], "missing")
    refused({**good, "notes.txt": b"hi"}, "notes.txt", "not named")
    refused({**good, "../escape": b"x"}, "../escape")
    # The lines file: a digest that does not match, a count that does not, a line above the page's
    # tier, a line of another day, a line whose payload has no schema.
    lines = _lines(good["lines.jsonl"])
    refused({**good, "lines.jsonl": good["lines.jsonl"] + b"\n"}, "lines.jsonl", "lines_sha256")
    manifest = json.loads(good["manifest.json"])

    def with_lines(rows: list[dict[str, Any]], **fields: Any) -> dict[str, bytes]:
        raw = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")
        m = {**manifest, "lines_sha256": hashlib.sha256(raw).hexdigest(), **fields}
        return {**good, "lines.jsonl": raw, "manifest.json": json.dumps(m).encode("utf-8")}

    refused(with_lines(lines[:3]), "3 lines", "manifest says 4")
    refused(with_lines(lines, max_tier=1, lines=4), "line 3", "tier 2", "max_tier 1")
    refused(with_lines(lines, date="2026-06-14"), "line 1", "2026-06-14")
    stripped = [
        dict(line, payload={k: v for k, v in line["payload"].items() if k != "schema"}) for line in lines
    ]
    refused(with_lines(stripped), "schema")
    # The package: its digest, and that its entries are the lines.
    refused({**good, "package.json": good["package.json"] + b" "}, "package.json", "package_sha256")
    package = json.loads(good["package.json"])
    package["entries"] = package["entries"][:-1]
    raw = canonical_json(package).encode("utf-8") + b"\n"
    m = {**manifest, "package_sha256": hashlib.sha256(raw).hexdigest()}
    refused(
        {**good, "package.json": raw, "manifest.json": json.dumps(m).encode("utf-8")},
        "package.json",
        "entries",
    )
    # The manifest itself: a schema this reader does not know; a key that is not the circle's.
    refused(
        {**good, "manifest.json": json.dumps({**manifest, "schema": "shared-page/v2"}).encode()},
        "shared-page/v2",
    )
    refused(
        {**good, "manifest.json": json.dumps({**manifest, "key": _public(OLA_SEED)}).encode()}, "circle add"
    )
    # Not a zip at all.
    bad = ines_page.with_name("not.zip")
    bad.write_bytes(b"hello")
    code, err = _failure(capsys, "receive", str(bad))
    assert code == 1 and "not a zip" in err


def test_receive_the_same_page_again_and_a_newer_one(
    records: tuple[Logbook, Logbook],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    ines, ola = records
    ines_page = share.share_day(ines, DAY, "ola", 2, tmp_path / "first.zip", created=CREATED).out
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    _run(capsys, "receive", str(ines_page))
    assert "already" in _run(capsys, "receive", str(ines_page))
    # Ines shares the day again, later, at tier 1 this time: the newer page replaces the older whole.
    newer = share.share_day(ines, DAY, "ola", 1, tmp_path / "newer.zip", created="2026-06-20T08:00:00Z").out
    out = _run(capsys, "receive", str(newer))
    assert "replaced" in out
    page = ola.root / "circle" / "ines" / DAY
    assert json.loads((page / "manifest.json").read_text(encoding="utf-8"))["max_tier"] == 1
    assert (page / "attachments" / PHOTO_SHA).read_bytes() == PHOTO_BYTES  # the photo is tier 1: still there
    assert json.loads((page / "manifest.json").read_text(encoding="utf-8"))["lines"] == 3
    # An older page never replaces a newer one.
    code, err = _failure(capsys, "receive", str(ines_page))
    assert code == 1 and "newer" in err
    assert json.loads((page / "manifest.json").read_text(encoding="utf-8"))["max_tier"] == 1


# -- the day shows a received page ---------------------------------------------------------------------------


def test_day_shows_the_received_page_as_a_from_section(
    records: tuple[Logbook, Logbook],
    ines_page: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    _, ola = records
    use(monkeypatch, ola)
    text = _run(capsys, "day", DAY)
    assert "from ines" not in text
    assert json.loads(_run(capsys, "day", DAY, "--json"))["received"] == []
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    _run(capsys, "receive", str(ines_page))
    text = _run(capsys, "day", DAY)
    assert "from ines" in text
    assert "4 lines" in text and "location 2" in text and "note 1" in text and "photo 1" in text
    assert "Anchored off Hovedøya with Ola." in text
    assert "tier 2" in text and "shared 20" in text
    data = json.loads(_run(capsys, "day", DAY, "--json"))
    assert data["received"] == [
        {
            "from": "ines",
            "owner_id": INES_ID,
            "created": data["received"][0]["created"],
            "max_tier": 2,
            "lines": 4,
            "held_back": 1,
            "by_kind": {"location": 2, "note": 1, "photo": 1},
            "named": [
                {
                    "kind": "note",
                    "at": "2026-06-13T19:00:00Z",
                    "title": "Anchored off Hovedøya with Ola. Still water, late light.",
                    "line": lines_id(ines_page, 2),
                }
            ],
            "attachments": 1,
        }
    ]
    # Another day shows nothing from Ines.
    assert "from ines" not in _run(capsys, "day", "2026-06-14")


def lines_id(bundle: Path, n: int) -> str:
    return str(_lines(_members(bundle)["lines.jsonl"])[n]["id"])


# -- both ways, and the committed fixture ------------------------------------------------------------


def _share_both(records: tuple[Logbook, Logbook], tmp_path: Path) -> tuple[Path, Path]:
    ines, ola = records
    a = share.share_day(
        ines, DAY, "ola", 2, tmp_path / "ines-to-ola.zip", created=CREATED, bundle_id=INES_BUNDLE
    )
    b = share.share_day(
        ola, DAY, "ines", 1, tmp_path / "ola-to-ines.zip", created=CREATED, bundle_id=OLA_BUNDLE
    )
    return a.out, b.out


def test_both_ways_and_an_over_tier_line_is_omitted(
    records: tuple[Logbook, Logbook],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    ines, ola = records
    to_ola, to_ines = _share_both(records, tmp_path)
    manifest = _manifest(to_ines)
    kinds = [line["kind"] for line in _lines(_members(to_ines)["lines.jsonl"])]
    assert manifest["max_tier"] == 1 and kinds == [
        "location",
        "photo",
    ]  # the note and the transcript stay home
    assert manifest["held_back"] == 2 and manifest["attachments"] == []
    _circle_add(monkeypatch, ola, "ines", INES_SEED)
    _run(capsys, "receive", str(to_ola))
    _circle_add(monkeypatch, ines, "ola", OLA_SEED)
    _run(capsys, "receive", str(to_ines))
    text = _run(capsys, "day", DAY)
    assert "from ola" in text and "2 lines" in text and "Great weekend" not in text
    use(monkeypatch, ola)
    assert "from ines" in _run(capsys, "day", DAY)


def test_the_committed_fixture_regenerates(records: tuple[Logbook, Logbook], tmp_path: Path):
    """`tests/fixtures/share/`: the two pages as directories, byte for byte, and the two public keys.
    To regenerate after a deliberate format change, delete the directory and run this test once: it
    writes what is missing, and every later run compares."""
    to_ola, to_ines = _share_both(records, tmp_path)
    keys = {"ines": _public(INES_SEED), "ola": _public(OLA_SEED)}
    if not FIXTURES.exists():  # first run: write the fixture, then compare like any other run
        for name, bundle in (("ines-to-ola", to_ola), ("ola-to-ines", to_ines)):
            with zipfile.ZipFile(bundle) as zf:
                zf.extractall(FIXTURES / name)
        (FIXTURES / "keys.json").write_text(json.dumps(keys, indent=2) + "\n", encoding="utf-8")
    assert json.loads((FIXTURES / "keys.json").read_text(encoding="utf-8")) == keys
    for name, bundle in (("ines-to-ola", to_ola), ("ola-to-ines", to_ines)):
        members = _members(bundle)
        files = {
            p.relative_to(FIXTURES / name).as_posix(): p.read_bytes()
            for p in (FIXTURES / name).rglob("*")
            if p.is_file()
        }
        assert files == members, name


def test_the_committed_fixture_is_received(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A second implementation that writes this fixture's bundles is read by this one."""
    lb = Logbook.init(tmp_path / "reader", "Europe/Oslo")
    use(monkeypatch, lb)
    keys = json.loads((FIXTURES / "keys.json").read_text(encoding="utf-8"))
    for name in ("ines", "ola"):
        cli.main(["circle", "add", name, keys[name]])
    for name, sender in (("ines-to-ola", "ines"), ("ola-to-ines", "ola")):
        bundle = tmp_path / f"{name}.zip"
        with zipfile.ZipFile(bundle, "w") as zf:
            for p in sorted((FIXTURES / name).rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(FIXTURES / name).as_posix())
        assert f"from {sender}" in _run(capsys, "receive", str(bundle))
    text = _run(capsys, "day", DAY)
    assert "from ines" in text and "from ola" in text


def _allow(lb: Logbook, name: str, max_tier: int) -> None:
    path = lb.root / "policy" / "crossing.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy[name] = {"max_tier": max_tier}
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
