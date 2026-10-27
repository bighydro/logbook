"""RFC 0038 §5.3: the voiceprint registry never leaves. `voiceprints.age` is part of no crossing,
whatever the tier and whatever a policy entry says: not the crossing package (RFC 0005), the shared
page (RFC 0025), the trip bundle (RFC 0030), the vault, the site, the world page, the Notion folder,
a day package, the whole log exported, the paper editions, a backup, the diagnostic packet, an MCP
tool's answer, a dream's material, the index, or what any reader prints. Every crossing here is built
over one sealed record whose registry holds several voices (the owner's, Kari's after an attribution
line, Ola's, one not yet named), with every policy entry at its highest ceiling, and everything each
produced (the files, recursively and inside a zip; what was printed; what was sent to the fake model;
what each tool answered) goes through one scan: for the file by name, for its bytes, and for every
number of every vector, as text and as packed floats. Three mutation tests make a real path leak and
show that the scan sees it, so no test here can pass for want of looking.

Synthetic Oslo persona (`voiceprints_record`, `persona`): the embedder is a fake that reads who speaks
from a small JSON file standing in for the audio; no model is downloaded, loaded or called; the model
the dream talks to and the hub `setup speakers` asks are in-process fakes; no socket opens."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import io
import json
import shutil
import struct
import sys
import types
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from persona import HOME, TZ, dwell, travel
from speakers_record import CALL, CALL_DAY, DINNER, DINNER_DAY, KARI_ID, OLA_ID, attribution
from voiceprints_record import FakeEmbedder, as_bytes, as_text, seal, stored, voiced_record

from logbook import cli
from logbook.contrib import backup, mcp_server, model_client, packet, serve, vault
from logbook.core import policy, sealing, signing, voiceprints
from logbook.core.chain import AGE_MAGIC
from logbook.core.store import Logbook

pytest.importorskip("mcp")  # the `mcp` extra: every tool's answer is one of the crossings

CABIN = (60.8600, 8.5500)  # a cabin in the mountains, which does not exist: two nights away, the trip
THU, FRI, SAT, SUN, MON = "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12"
TRIP_DAY = SAT  # any day inside the trip names it
TODAY = date(2026, 10, 12)  # the day every policy entry and the MCP door are held against
SINCE = "2026-09-01T00:00:00Z"  # the crossing's window opens before the record's first line
PLACES = {
    "Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"},
    "Cabin": {"lat": CABIN[0], "lon": CABIN[1], "radius_m": 150},
}
POLICY = {  # every destination at its highest ceiling: the registry crosses to none of them
    "hermes": {"max_tier": 3},  # given a recipient when the record is built: sealed lines resealed to it
    "athena": {"max_tier": 3},  # no recipient: sealed lines cross opened, with --open
    "ola": {"max_tier": 3},
    "mcp": {"max_tier": 3, "write": ["sign_day", "note_day", "add_note", "promise_done"]},
    "vault": {"max_tier": 2},
    "site": {"max_tier": 2},
    "world": {"max_tier": 3},
    "notion": {"max_tier": 2, "write": [], "include_unsigned": True},
    "dream": {"max_tier": 3, "until": "2027-12-31"},
}
MODEL = "qwen2.5-7b-instruct"
ENDPOINT = "http://127.0.0.1:8080/v1"
ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")  # a text output in any encoding a page or a file may use
WINDOW = 64  # bytes of the sealed file looked for at a time
# the arguments each MCP tool is called with; a tool this table does not name fails the test
ARGUMENTS: dict[str, dict[str, Any]] = {
    "day": {"date": DINNER_DAY},
    "days": {"from": "2026-10-01", "to": MON},
    "trips": {"year": "2026"},
    "places": {},
    "people": {},
    "person": {"name": "Kari"},
    "promises": {"open": True},
    "gaps": {"since": "2026-10-01"},
    "search": {"text": "Middag", "since": "2026-10-01", "until": MON},
    "day_lines": {"day": DINNER_DAY},
    "line": {"id": DINNER},
    "digest": {"period": "week", "date": DINNER_DAY},
    "add_note": {"text": "Called the yard about the crane.", "at": "2026-10-12T10:00:00+02:00"},
    "promise_done": {"id": "0000000000000000"},  # no such proposal: the refusal is the answer scanned
    "sign_day": {"day": CALL_DAY, "confirm": "none"},
    "note_day": {"day": CALL_DAY, "text": "Ferja var sen.", "kind": "proposal"},
}
MAY_REFUSE = {"promise_done"}  # the one call made to be refused


# -- what is looked for, and where ------------------------------------------------------------------------


@dataclass(frozen=True)
class Needles:
    """What no crossing may hold: windows of the sealed file's bytes, and every number of every
    vector the registry holds, as JSON writes it after its point and as a float32 or float64."""

    windows: tuple[bytes, ...]
    texts: tuple[str, ...]
    packed: tuple[bytes, ...]


def needles_of(sealed: bytes, registry: voiceprints.Registry) -> Needles:
    vectors = [p.voiceprint for p in registry.people.values()]
    vectors += [e.embedding for p in registry.people.values() for e in p.voices.values()]
    vectors += [e.embedding for e in registry.voices.values()]
    assert len(vectors) >= 5 and len(set(vectors)) >= 3, "several voices, several vectors"
    # A number of a vector is looked for from its point on, `.918273` (`as_text`), never as bare
    # digits: a record's outputs carry thousands of 64-character hashes and ids, in which a run of six
    # digits turns up by chance, and no hex string holds a point.
    texts = sorted({number for v in vectors for number in as_text(v)})
    packed = sorted({b for v in vectors for b in as_bytes(v)})
    assert len(texts) >= 12 and len(packed) >= 24, "every number of every vector, in every form"
    head, middle = len(AGE_MAGIC), len(sealed) // 2
    windows = (sealed[head : head + WINDOW], sealed[middle : middle + WINDOW], sealed[-WINDOW:])
    assert all(len(w) == WINDOW for w in windows) and len(set(windows)) == 3
    return Needles(windows, tuple(texts), tuple(packed))


Found = tuple[
    str, str | None, bytes
]  # what a crossing produced: a label, the file's name if a file, the bytes


def files_under(folder: Path, label: str) -> list[Found]:
    """Every file under `folder`, recursively, and every member of every zip among them."""
    out: list[Found] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        where = f"{label}/{path.relative_to(folder).as_posix()}"
        out.append((where, path.name, path.read_bytes()))
        if zipfile.is_zipfile(path):
            out.extend(zip_members(path, where))
    return out


def zip_members(path: Path, label: str) -> list[Found]:
    with zipfile.ZipFile(path) as zf:
        return [(f"{label}!{i.filename}", PurePosixPath(i.filename).name, zf.read(i)) for i in zf.infolist()]


def text(label: str, said: str) -> Found:
    """What a command printed, a tool answered or a request carried."""
    return (label, None, said.encode("utf-8"))


def leaks(found: Iterable[Found], needles: Needles) -> list[str]:
    """Every leak among `found`: a file named as the registry (by name, case aside: the file systems
    the record lives on tell no files apart by case), the registry file's bytes, or a number of a
    vector as text in any encoding or as a packed float. The leak is named, never the number."""
    out: list[str] = []
    for label, name, data in found:
        if name is not None and name.casefold() == voiceprints.FILE.casefold():
            out.append(f"{label}: a file named {voiceprints.FILE}")
        if any(window in data for window in needles.windows):
            out.append(f"{label}: holds the registry file's bytes")
        if any(needle.encode(encoding) in data for needle in needles.texts for encoding in ENCODINGS):
            out.append(f"{label}: a number of a vector, as text")
        if any(packed in data for packed in needles.packed):
            out.append(f"{label}: a number of a vector, as a packed float")
    return out


# -- the record ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    lb: Logbook
    registry: voiceprints.Registry
    needles: Needles

    @property
    def owner(self) -> str:
        return str(self.lb.meta["owner_id"])


def _trip() -> list[dict[str, Any]]:
    """Thursday night and Sunday night at home, Friday and Saturday night at the cabin: one trip."""
    return (
        dwell(THU, "18:30", "24:00", HOME, every_min=10)
        + dwell(FRI, "00:00", "07:30", HOME, every_min=10)
        + travel(FRI, "07:30", "11:00", HOME, CABIN, steps=8)
        + dwell(FRI, "11:00", "24:00", CABIN, every_min=10)
        + dwell(SAT, "00:00", "24:00", CABIN, every_min=10)
        + dwell(SUN, "00:00", "11:00", CABIN, every_min=10)
        + travel(SUN, "11:00", "15:00", CABIN, HOME, steps=8)
        + dwell(SUN, "15:00", "24:00", HOME, every_min=10)
        + dwell(MON, "00:00", "07:30", HOME, every_min=10)
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Built once per module: the dinner and the call (`voiced_record`) in a record sealed to two
    recipients, the week after at the cabin, Home and Cabin named, both recorded days signed, every
    policy entry at its highest ceiling, and the registry written twice: heard by the fake embedder,
    then regrouped without it after the owner named Kari and Ola. The identity is at `keys/owner.txt`."""
    base = tmp_path_factory.mktemp("voiced")
    with pytest.MonkeyPatch.context() as mp:
        lb = seal(Logbook.init(base / "lb", TZ), mp, base)
        voiced_record(lb)
        lb.append_many(_trip())
        (lb.root / "places.json").write_text(json.dumps(PLACES, indent=2), encoding="utf-8")
        _secret, recipient = sealing.generate_identity()  # hermes's own key: sealed lines are resealed to it
        entries = {**POLICY, "hermes": {**POLICY["hermes"], "recipient": recipient}}
        (lb.root / "policy" / "crossing.json").write_text(
            json.dumps(entries, indent=2) + "\n", encoding="utf-8"
        )
        signing.sign(lb, DINNER_DAY, at="2026-10-04T08:00:00Z")
        signing.sign(lb, CALL_DAY, at="2026-10-07T08:00:00Z")
        assert voiceprints.update(lb, FakeEmbedder()).written
        lb.append(**attribution(DINNER, "S2", KARI_ID, name="Kari Nordmann"))
        lb.append(**attribution(CALL, "system", OLA_ID, name="Ola Nordmann"))
        assert voiceprints.update(lb).written
    return base


@pytest.fixture
def record(built: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Record:
    """A copy of the built record for this test alone, found by `LOGBOOK_HOME`, its identity where
    `LOGBOOK_IDENTITY_FILE` points, today pinned; the registry read and held to be several voices."""
    root = tmp_path / "lb"
    shutil.copytree(built / "lb", root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(built / "keys" / "owner.txt"))
    monkeypatch.setattr(policy, "today", lambda: TODAY)
    monkeypatch.setattr(mcp_server, "_today", lambda _lb: TODAY.isoformat())
    monkeypatch.delenv("OneDrive", raising=False)
    lb = Logbook(root)
    sealed = (root / voiceprints.FILE).read_bytes()
    assert sealed.startswith(AGE_MAGIC), "the registry is sealed"
    registry = voiceprints.read(lb)
    assert registry is not None
    owner = str(lb.meta["owner_id"])
    assert registry.people[owner].voiceprint == stored("ines"), "the owner, from the call's microphone"
    assert registry.people[KARI_ID].voiceprint == stored("kari"), "Kari, after the attribution line"
    assert registry.people[KARI_ID].refs == [f"{DINNER}#S2"]
    assert registry.people[OLA_ID].voiceprint == stored("ola"), "Ola, the far end of the call"
    assert set(registry.voices) == {f"{DINNER}#S1"}, "a voice not yet named"
    assert registry.voices[f"{DINNER}#S1"].embedding == stored("ines")
    return Record(lb, registry, needles_of(sealed, registry))


def run(*args: str) -> tuple[int, str]:
    """`logbook <args>` in this process: its exit code and everything it printed, stdout and stderr."""
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue()


def ran(*args: str) -> Found:
    """The command run, held to exit 0, and what it printed as one thing to scan."""
    code, said = run(*args)
    assert code == 0, f"{' '.join(args)} exited {code}:\n{said}"
    return text("logbook " + " ".join(args), said)


def clean(found: Iterable[Found], record: Record) -> None:
    found = list(found)
    assert found, "nothing was produced: a scan over nothing proves nothing"
    assert leaks(found, record.needles) == []


# -- the record holds a registry worth leaking -----------------------------------------------------------


def test_the_registry_holds_the_owner_two_people_named_and_a_voice_not_yet_named(record: Record) -> None:
    assert set(record.registry.people) == {record.owner, KARI_ID, OLA_ID}
    assert len(record.needles.texts) >= 12 and len(record.needles.packed) >= 24
    # the needles do find the registry's own document, so a document copied anywhere is found
    plain = record.registry.to_bytes()
    assert leaks([("the document", None, plain)], record.needles) == [
        "the document: a number of a vector, as text"
    ]
    sealed = (record.lb.root / voiceprints.FILE).read_bytes()
    assert leaks([("the file", voiceprints.FILE, sealed)], record.needles) == [
        f"the file: a file named {voiceprints.FILE}",
        "the file: holds the registry file's bytes",
    ]


# -- every crossing ---------------------------------------------------------------------------------------


def test_the_crossing_package(record: Record, tmp_path: Path) -> None:
    """Both forms of the package: the sealed lines and files resealed to hermes's key, and, for
    athena, who has none, shipped opened with `--open`; and a dry run."""
    window = ("--since", SINCE, "--tier", "1,2,3", "--unsigned")
    resealed, opened = tmp_path / "resealed", tmp_path / "opened"
    said = [ran("export", "crossing", "--to", "hermes", *window, "--out", str(resealed))]
    said.append(ran("export", "crossing", "--to", "athena", *window, "--open", "--out", str(opened)))
    said.append(ran("export", "crossing", "--to", "athena", *window, "--open", "--dry-run"))
    for out, mode in ((resealed, "resealed"), (opened, "opened")):
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["sealing"]["mode"] == mode and manifest["sealing"]["lines"] > 0
        assert (out / "attachments").is_dir(), "the files the lines name crossed"
    assert b'"payload_open"' in (opened / "entries.jsonl").read_bytes()
    clean([*said, *files_under(resealed, "resealed"), *files_under(opened, "opened")], record)


def test_the_shared_page(record: Record, tmp_path: Path) -> None:
    """The dinner's day at tier 1 and the cabin Saturday at tier 3, each one signed page for Ola. (A
    day whose tier-2 lines name sealed attachments is one `share` refuses on a sealed record, since the
    store's file does not hash to its name: that is the page's own rule, not the registry's.)"""
    said, members = [], []
    for day, tier in ((DINNER_DAY, "1"), (TRIP_DAY, "3")):
        page = tmp_path / f"{day}.zip"
        said.append(ran("export", "share", "day", day, "--to", "ola", "--tier", tier, "--out", str(page)))
        found = zip_members(page, f"page {day}")
        assert {name for _label, name, _data in found} >= {"manifest.json", "lines.jsonl", "package.json"}
        assert any(name == "lines.jsonl" and day.encode() in data for _label, name, data in found)
        members += [(str(page), page.name, page.read_bytes()), *found]
    clean([*said, *members], record)


def test_the_trip_bundle(record: Record, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    said = ran(
        "export",
        "trip-bundle",
        TRIP_DAY,
        "--to",
        "ola",
        "--tier",
        "1,2,3",
        "--attachments",
        "--out",
        str(out),
    )
    trip = json.loads((out / "trip.json").read_text(encoding="utf-8"))
    assert [s["place"] for s in trip["stays"]] == ["Cabin"], "the trip is the two nights at the cabin"
    clean([said, *files_under(out, "bundle")], record)


def test_the_vault(record: Record, tmp_path: Path) -> None:
    folder = tmp_path / "Vault"
    said = ran("export", "vault", str(folder), "--tier", "1,2")
    pages = files_under(folder, "vault")
    assert any(name == "Kari Nordmann.md" for _label, name, _data in pages)
    clean([said, *pages], record)


def test_the_site(record: Record, tmp_path: Path) -> None:
    folder = tmp_path / "Site"
    said = ran("export", "site", str(folder), "--tier", "1,2")
    pages = files_under(folder, "site")
    assert any(name == "kari-nordmann.html" for _label, name, _data in pages)
    clean([said, *pages], record)


def test_the_world_page(record: Record, tmp_path: Path) -> None:
    folder = tmp_path / "World"
    said = ran("export", "world", "--out", str(folder), "--tier", "1,2,3")
    pages = files_under(folder, "world")
    assert any(name == "world.html" for _label, name, _data in pages)
    clean([said, *pages], record)


def test_the_notion_folder(record: Record, tmp_path: Path, no_network: list[str]) -> None:
    folder = tmp_path / "Notion"
    said = ran("export", "notion", str(folder), "--include-unsigned")
    assert no_network == []
    persons = json.loads((folder / "persons.json").read_text(encoding="utf-8"))["persons"]
    assert {p["id"] for p in persons} >= {KARI_ID, OLA_ID}, "the people the record names left for Notion"
    clean([said, *files_under(folder, "notion")], record)
    dry = ran("export", "notion", str(tmp_path / "Dry"), "--include-unsigned", "--dry-run")
    clean([dry], record)


def test_the_day_packages_and_the_whole_log(record: Record, tmp_path: Path) -> None:
    out = tmp_path / "out"
    said = [ran("export", "--days", "2026-10-01", MON, "--out", str(out / "days"), "--empty")]
    said.append(ran("export", "--day", DINNER_DAY, "--out", str(out / "one")))
    opened, sealed = out / "opened.jsonl", out / "sealed.jsonl"
    said.append(ran("export", str(opened)))
    said.append(ran("export", str(sealed), "--sealed"))
    assert (out / "days" / DINNER_DAY / "package.json").is_file() and b"payload_enc" in sealed.read_bytes()
    assert b"payload_enc" not in opened.read_bytes(), "the lines opened for re-entry"
    clean([*said, *files_under(out, "export")], record)


def test_the_paper_editions_and_the_pages(record: Record, tmp_path: Path) -> None:
    out = tmp_path / "out"
    said = []
    for name, args in (
        ("year.html", ("show", "year", "2026", "--html")),
        ("poster.html", ("show", "year", "2026", "--poster", "--html")),
        ("year-print.html", ("show", "year", "2026", "--print", "--html")),
        ("trip.html", ("show", "trip", TRIP_DAY, "--html")),
        ("trip-print.html", ("show", "trip", TRIP_DAY, "--print", "--html")),
        ("week.html", ("digest", DINNER_DAY, "--paper", "--html")),
    ):
        said.append(ran(*args, str(out / name)))
    said.append(ran("show", "year", "2026", "--poster"))  # to stdout
    said.append(ran("digest", DINNER_DAY, "--paper"))
    pages = files_under(out, "pages")
    assert len(pages) == 6 and all(
        data.lstrip().lower().startswith(b"<!doctype html>") for _l, _n, data in pages
    )
    clean([*said, *pages], record)


def _answers(record: Record) -> dict[str, tuple[bool, str]]:
    """Every tool called through the SDK's in-process client, as a host would: name → (refused, the
    answer's text)."""
    from mcp.client.client import Client

    server = mcp_server.build_server(record.lb.root, allow_tier_3=True)

    async def go() -> dict[str, tuple[bool, str]]:
        found: dict[str, tuple[bool, str]] = {}
        async with Client(server) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            assert set(names) == set(ARGUMENTS) == set(mcp_server.TOOLS), "every tool is called"
            for name in names:
                result = await client.call_tool(name, ARGUMENTS[name])
                said = "".join(getattr(c, "text", "") for c in result.content)
                found[name] = (bool(result.is_error), said)
        return found

    return asyncio.run(go())


def test_every_mcp_tool_s_answer(record: Record) -> None:
    answers = _answers(record)
    assert {name for name, (refused, _said) in answers.items() if refused} <= MAY_REFUSE
    assert all(said for _refused, said in answers.values())
    assert KARI_ID in answers["person"][1] and DINNER in answers["line"][1], "the tools answered in full"
    clean([text(f"mcp {name}", said) for name, (_refused, said) in answers.items()], record)


def _fake_model(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`model_client.send` replaced: every request body kept; the answer cites the day's first stay."""
    sent: list[dict[str, Any]] = []

    def send(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        sent.append(body)
        material = json.loads(body["messages"][1]["content"])
        refs = [r for entry in material["timeline"] for r in entry["ref"]]
        answer = {
            "story": [{"text": "Dinner at home; Kari came.", "evidence": refs[:1]}],
            "threads": [],
            "people": [],
            "promises": [],
            "questions": [{"text": "Did the cake arrive on Friday?", "evidence": refs[:1]}],
        }
        return {"choices": [{"message": {"content": json.dumps(answer)}}]}

    monkeypatch.setattr(model_client, "send", send)
    monkeypatch.setattr(model_client, "RETRY_PAUSE_S", 0.0)
    monkeypatch.setenv(model_client.ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setenv(model_client.MODEL_ENV, MODEL)
    return sent


def test_the_dream_s_material(record: Record, monkeypatch: pytest.MonkeyPatch, no_network: list[str]) -> None:
    sent = _fake_model(monkeypatch)
    said = [ran("dream", "day", DINNER_DAY, "--dry-run", "--show-prompt"), ran("dream", "day", DINNER_DAY)]
    assert len(sent) == 2 and no_network == []
    assert all(len(body["messages"]) == 2 and "Middag" in body["messages"][1]["content"] for body in sent)
    said.append(ran("day", DINNER_DAY, "--json"))  # the draft on its day
    assert "draft" in json.loads(said[-1][2].decode("utf-8"))
    requests = [
        text(f"dream request {n}", json.dumps(body, ensure_ascii=False)) for n, body in enumerate(sent)
    ]
    clean([*said, *requests], record)


def test_the_backup(record: Record, tmp_path: Path) -> None:
    dest = tmp_path / "Backups"
    said = [ran("backup", str(dest), "--verify"), ran("backup", "list", str(dest))]
    copied = files_under(dest, "backup")
    assert any(name == "logbook.json" for _label, name, _data in copied)
    assert any(label.endswith("/policy/crossing.json") for label, _name, _data in copied), "policy/ is copied"
    clean([*said, *copied], record)


def test_the_diagnostic_packet_and_doctor(
    record: Record, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    monkeypatch.setattr(packet, "run_command", lambda args: "")  # no journal, no launchctl
    out = tmp_path / "out"
    out.mkdir()
    said = [ran("doctor", "--packet"), ran("doctor", "--packet", "--out", str(out / "packet.txt"))]
    code, printed = run("doctor")  # exit 1 when a check fails: what it says is what is scanned
    assert code in (0, 1) and printed
    said.append(text("logbook doctor", printed))
    built = packet.build(record.lb, {"LOGBOOK_HOME": str(record.lb.root)})
    assert no_network == []
    assert "lines:" in built
    clean([*said, text("packet.build", built), *files_under(out, "packet")], record)


def test_the_index(record: Record) -> None:
    with record.lb.index():
        pass
    data = record.lb.index_path.read_bytes()
    assert data.startswith(b"SQLite format 3") and DINNER.encode() in data
    clean([(str(record.lb.index_path), record.lb.index_path.name, data)], record)


def _fake_speakers_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """pyannote.audio installed and a hub with nothing cached, as far as `setup speakers` can tell."""
    engine = types.ModuleType("pyannote.audio")
    engine.__version__ = "4.0.7"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyannote.audio", engine)
    hub = types.ModuleType("huggingface_hub")

    def snapshot_download(repo: str, **options: Any) -> str:
        if options.get("local_files_only"):
            raise FileNotFoundError(repo)
        raise AssertionError(f"a download of {repo} was asked for")

    hub.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)


def test_what_the_readers_print(record: Record, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_speakers_extra(monkeypatch)
    said = [
        ran("review", "speakers", "--json"),
        ran("review", "speakers"),
        ran("review", "speakers", "--named", "--day", DINNER_DAY, "--json"),
        ran("day", DINNER_DAY, "--json"),
        ran("day", DINNER_DAY),
        ran("day", CALL_DAY, "--json"),
        ran("people", "--json"),
        ran("people"),
        ran("people", "Kari", "--json"),
        ran("show", DINNER_DAY),
        ran("show", DINNER_DAY, "--json"),
        ran("show", "trips", "--json"),
        ran("show", "trip", TRIP_DAY, "--json"),
        ran("show", "year", "2026", "--json"),
        ran("digest", DINNER_DAY, "--json"),
        ran("setup", "speakers"),
    ]
    queue, named = json.loads(said[0][2]), json.loads(said[2][2])
    assert queue["not_yet_named"] >= 1 and queue["named"] == 2, "the queue, over the record's attributions"
    assert KARI_ID in json.dumps(named), "the voices named, Kari's among them"
    assert voiceprints.FILE in said[-1][2].decode("utf-8"), "setup speakers says the registry is there"
    clean(said, record)


def test_the_library_s_pages(record: Record) -> None:
    """The pages `serve` renders, as a browser would get them, over the record with the registry.
    (The Library's *Who spoke?* page, which may open the registry, is a later build's; the day, the
    people and the person are the pages the voices stand on.)"""
    site = serve.Site(record.lb)
    pages = {
        "index": site.page_index(),
        "day": site.page_day(DINNER_DAY, expanded=True),
        "call day": site.page_day(CALL_DAY, expanded=True),
        "days": site.page_days(None, None),
        "trips": site.page_trips(None),
        "journey": site.page_journey(FRI, SAT),
        "places": site.page_places(),
        "people": site.page_people(None),
        "person": site.page_person("Kari Nordmann"),
        "manifest": site.page_manifest(),
        "manifest people": site.page_manifest_people(),
        "assets": site.page_assets(),
        "world": site.page_world(None, None),
        "gaps": site.page_gaps(None),
    }
    assert all(page for page in pages.values()) and "Kari Nordmann" in pages["person"]
    assert "Middag" in pages["day"], "the dinner's transcript is on its day"
    clean([text(f"serve {name}", page) for name, page in pages.items()], record)


# -- the scan sees a leak: three real paths made to leak -------------------------------------------------


def test_the_scan_sees_the_file_in_a_backup_made_to_carry_it(
    record: Record, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "FILES", (*backup.FILES, voiceprints.FILE))
    dest = tmp_path / "Backups"
    assert run("backup", str(dest))[0] == 0
    found = leaks(files_under(dest, "backup"), record.needles)
    assert [f for f in found if f.endswith(f"a file named {voiceprints.FILE}")]
    assert [f for f in found if f.endswith("holds the registry file's bytes")]
    assert all(f"/{voiceprints.FILE}: " in f for f in found), "and nothing else in the snapshot"


def test_the_scan_sees_a_vector_in_a_tool_s_answer_made_to_hold_one(
    record: Record, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector = record.registry.people[KARI_ID].voiceprint

    def leaky(_lb: Any, _a: Any) -> dict[str, Any]:
        return {"years": [], "voiceprint": list(vector)}

    monkeypatch.setitem(mcp_server.TOOLS, "people", dataclasses.replace(mcp_server.TOOLS["people"], fn=leaky))
    answers = _answers(record)
    found = leaks([text(f"mcp {name}", said) for name, (_refused, said) in answers.items()], record.needles)
    assert found == ["mcp people: a number of a vector, as text"]


def test_the_scan_sees_packed_floats_in_a_vault_made_to_write_them(
    record: Record, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector = record.registry.voices[f"{DINNER}#S1"].embedding
    real = vault.export

    def leaky(lb: Logbook, req: Any, built: Any, folder: Path, generated_at: str) -> Any:
        result = real(lb, req, built, folder, generated_at)
        (folder / "voices.bin").write_bytes(b"".join(struct.pack("<f", v) for v in vector))
        (folder / "wide.bin").write_bytes(b"".join(struct.pack("<d", v) for v in vector))
        return result

    monkeypatch.setattr(vault, "export", leaky)
    folder = tmp_path / "Vault"
    assert run("export", "vault", str(folder))[0] == 0
    found = leaks(files_under(folder, "vault"), record.needles)
    assert found == [
        "vault/voices.bin: a number of a vector, as a packed float",
        "vault/wide.bin: a number of a vector, as a packed float",
    ]
