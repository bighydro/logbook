"""`logbook describe keepers`: a local vision model writes one derived note per keeper whose photo file
is reachable, through a fake engine with deterministic answers; nothing here opens a socket or runs
a model. Synthetic Oslo persona; the photos are a few bytes each and show nothing."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from persona import KARI, photo

from logbook import cli
from logbook.core import attachments, keepers
from logbook.core.store import Logbook
from logbook.labs import describe

DAY = "2026-06-10"
QUAY = "A wooden sailing boat moored at a stone quay under a grey sky."
TABLE = "A table set for two with bread and coffee by a window."
CAFE_AT = f"{DAY}T10:30:00Z"
QUAY_AT = f"{DAY}T17:00:00Z"
ART_AT = f"{DAY}T18:00:00Z"
AWAY_AT = f"{DAY}T19:00:00Z"
LATER_AT = "2026-06-16T18:00:00Z"
UUID_QUAY = "9B4E2C10-5F3A-4D21-8A7B-000000000001"  # a Photos asset: its original lies under originals/9/
UUID_LATER = "0C1D2E3F-1111-4222-8333-000000000002"


def _answer(description: str, things: list[str]) -> str:
    return json.dumps({"description": description, "things": things})


class FakeVision:
    """Answers by the file's bytes (a file in the store is named by its digest, not its name): the
    quay, a table, a face's name for the terrace (what a model must never do), prose without JSON
    for the art photo."""

    name = "fake-vision"

    def __init__(self, model: str = "fake-vlm-4bit", ready: bool = True) -> None:
        self.model = model
        self.seen: list[tuple[Path, str]] = []
        self.fetched = 0
        self._ready = ready
        self.offline_seen: list[str | None] = []

    def ready(self) -> bool:
        return self._ready

    def fetch(self) -> None:
        self.fetched += 1
        self._ready = True

    def describe(self, image: Path, prompt: str) -> str:
        self.seen.append((image, prompt))
        self.offline_seen.append(os.environ.get("HF_HUB_OFFLINE"))
        data = image.read_bytes()
        if data == b"quay":
            return (
                "Here you go:\n```json\n"
                + _answer(QUAY, ["Boat", "quay", " ropes ", "sky", "boat"])
                + "\n```"
            )
        if data.endswith(b"cafe"):
            return _answer(TABLE, ["table", "bread", "coffee", "window"])
        if data == b"terrace":
            return _answer("Kari Nordmann smiles at the camera on a terrace.", ["person", "terrace"])
        if data == b"art":
            return "I see a painting, but I cannot answer in JSON."
        return _answer("A view.", ["view"])


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, Path, dict[str, Any]]:
    """Four keepers on one day and one on a later day, their files reachable three ways: the cafe
    photo's bytes in the attachment store; the quay photo under a Photos library's `originals/`,
    named by its asset UUID; the art photo by file name under a plain folder. The terrace photo
    (a face named) is reachable too; the later day's photo is nowhere. One photo is in both lanes."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cafe = photo(CAFE_AT, favorite=True)
    blob = b"\xff\xd8not really a jpeg, cafe"
    lb.attach(blob)
    cafe["payload"]["media"] = attachments.reference(blob, "image/jpeg")
    quay = photo(QUAY_AT, favorite=True, album="Art", library="apple-photos")
    quay["payload"]["asset_id"] = quay["payload"]["raw_id"] = UUID_QUAY
    quay["payload"]["favorite"] = True
    quay["payload"]["albums"] = ["Art"]
    del quay["payload"]["extra"]
    art = photo(ART_AT, album="Art")
    terrace = photo(AWAY_AT, favorite=True, people=[KARI["face"]])
    terrace["payload"]["extra"]["faces"] = ["Kari Nordmann"]
    later = photo(LATER_AT, favorite=True, library="apple-photos")
    later["payload"]["asset_id"] = later["payload"]["raw_id"] = UUID_LATER
    later["payload"]["favorite"] = True
    del later["payload"]["extra"]
    lb.append_many([cafe, quay, art, terrace, later])
    lb.append_many(keepers.infer(line for line in lb.lines() if line["kind"] == "photo"))
    library = tmp_path / "Photos Library.photoslibrary"
    (library / "originals" / "9").mkdir(parents=True)
    (library / "originals" / "9" / f"{UUID_QUAY}.heic").write_bytes(b"quay")
    folder = tmp_path / "pictures" / "2026"
    folder.mkdir(parents=True)
    (folder / art["payload"]["file_name"]).write_bytes(b"art")
    (folder / terrace["payload"]["file_name"]).write_bytes(b"terrace")
    photos = {line["payload"]["asset_id"]: line for line in lb.lines() if line["kind"] == "photo"}
    return lb, tmp_path, photos


def _notes(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in lb.lines() if line["kind"] == "note"]


def _roots(root: Path) -> list[Path]:
    return [root / "Photos Library.photoslibrary", root / "pictures"]


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


# -- what is pending ---------------------------------------------------------------------------------


def test_pending_is_every_standing_keeper_whose_photo_file_is_reachable_once_per_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, root, photos = _record(tmp_path, monkeypatch)
    counts: dict[str, int] = {}
    found, already = describe.pending(lb, None, describe.Roots(_roots(root)), counts)
    assert already == 0 and counts == {describe.NO_FILE: 1}
    # time order, each photo once
    assert [p.photo["at"] for p in found] == [CAFE_AT, QUAY_AT, ART_AT, AWAY_AT]
    by_at = {p.photo["at"]: p for p in found}
    assert (
        by_at[CAFE_AT].file == lb.root / "attachments" / photos[f"p-{CAFE_AT}"]["payload"]["media"]["sha256"]
    )
    assert by_at[QUAY_AT].file.name == f"{UUID_QUAY}.heic" and by_at[QUAY_AT].file.parent.name == "9"
    assert by_at[ART_AT].file == root / "pictures" / "2026" / photos[f"p-{ART_AT}"]["payload"]["file_name"]
    assert by_at[QUAY_AT].keeper["payload"]["lane"] == "memory"  # the first lane stands for the photo
    without_roots, _ = describe.pending(lb, None, describe.Roots([]), {})
    assert [p.photo["at"] for p in without_roots] == [CAFE_AT]  # without a folder only the store is reachable
    since, _ = describe.pending(lb, "2026-06-11", describe.Roots(_roots(root)), {})
    assert since == []


def test_a_retracted_keeper_is_not_described(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, root, _photos = _record(tmp_path, monkeypatch)
    cafe = next(line for line in lb.lines() if line["kind"] == "keeper" and line["at"] == CAFE_AT)
    lb.retract(cafe["seq"], "not a keeper")
    found, _ = describe.pending(lb, None, describe.Roots(_roots(root)), {})
    assert CAFE_AT not in {p.photo["at"] for p in found}


# -- the answer --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        _answer(QUAY, ["Boat", "quay", " ropes ", "sky", "boat"]),
        "Sure:\n```json\n" + _answer(QUAY, ["boat", "quay", "ropes", "sky"]) + "\n```",
        json.dumps({"description": f"  {QUAY}\n", "things": "boat, quay, ropes, sky"}),
    ],
)
def test_an_answer_is_the_first_json_object_with_the_things_cleaned(text: str) -> None:
    found = describe.description_of(text, [])
    assert found is not None
    assert found.text == QUAY and found.things == ["boat", "quay", "ropes", "sky"]


@pytest.mark.parametrize(
    "text",
    [
        "I see a painting, but I cannot answer in JSON.",
        '{"things": ["boat"]}',
        '{"description": "", "things": ["boat"]}',
        '{"description": 7, "things": ["boat"]}',
    ],
)
def test_an_answer_without_a_sentence_is_no_description(text: str) -> None:
    assert describe.description_of(text, []) is None


def test_an_answer_that_names_a_face_the_library_knows_is_refused() -> None:
    faces = ["Kari Nordmann"]
    assert describe.description_of(_answer("Kari Nordmann smiles on a terrace.", ["person"]), faces) is None
    assert describe.description_of(_answer("A person smiles on a terrace.", ["kari nordmann"]), faces) is None
    assert describe.description_of(_answer("A person smiles on a terrace.", ["person"]), faces) is not None
    first_name_only = describe.description_of(_answer("Kari smiles on a terrace.", ["person"]), faces)
    assert first_name_only is None, "a first name alone is still the name"


def test_things_are_short_lowercase_unique_and_at_most_twelve() -> None:
    things = [f"Thing number {n} of many words here" for n in range(3)] + [f"item {n}" for n in range(20)]
    found = describe.description_of(_answer(QUAY, things), [])
    assert found is not None
    assert found.things == [f"item {n}" for n in range(describe.MAX_THINGS)], "a long phrase is dropped"


def test_the_prompt_forbids_names_and_places_and_carries_none() -> None:
    prompt = describe.PROMPT.casefold()
    assert "never" in prompt and "person" in prompt and "place" in prompt and "json" in prompt
    assert "nordmann" not in prompt and "oslo" not in prompt


# -- the run -----------------------------------------------------------------------------------------


def test_run_writes_one_derived_note_per_photo_and_a_rerun_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, root, photos = _record(tmp_path, monkeypatch)
    engine = FakeVision()
    seen: list[str] = []
    report = describe.run(lb, engine, roots=describe.Roots(_roots(root)), progress=seen.append)
    assert (report.found, report.already, report.written, report.unparsed) == (4, 0, 2, 2)
    assert report.counts == {describe.NO_FILE: 1}
    assert len(engine.seen) == 4 and all(prompt == describe.PROMPT for _f, prompt in engine.seen)
    assert len(seen) == 4 and any("Kari" not in s for s in seen)
    assert not any("Kari" in s for s in seen), "a refused answer is never echoed"
    notes = _notes(lb)
    assert len(notes) == 2
    quay_photo = photos[UUID_QUAY]
    note = next(n for n in notes if n["at"] == QUAY_AT)
    assert (note["kind"], note["tier"], note["source"], note["end"], note["tz"]) == (
        "note", 2, describe.SOURCE, None, quay_photo.get("tz"),
    )  # fmt: skip
    payload = note["payload"]
    assert payload["schema"] == "note/v1" and payload["raw_id"] == quay_photo["id"]
    assert payload["text"] == f"{QUAY}\nVisible: boat, quay, ropes, sky"
    extra = payload["extra"]
    assert extra["derived"] is True and extra["model"] == "fake-vlm-4bit" and extra["engine"] == "fake-vision"
    assert extra["photo"] == {
        "line": quay_photo["id"],
        "asset_id": UUID_QUAY,
        "library": "apple-photos",
        "file_name": quay_photo["payload"]["file_name"],
    }
    assert extra["things"] == ["boat", "quay", "ropes", "sky"]
    keeper = next(k for k in lb.lines() if k["kind"] == "keeper" and k["at"] == QUAY_AT)
    assert extra["keeper"] == keeper["id"]
    assert lb.verify()[2] == []
    again = describe.run(lb, FakeVision(model="another"), roots=describe.Roots(_roots(root)))
    assert (again.found, again.already, again.written, again.unparsed) == (2, 2, 0, 2)
    assert len(_notes(lb)) == 2, "a photo described once is never described again"
    assert _notes(lb)[0]["payload"]["extra"]["model"] == "fake-vlm-4bit"


def test_run_describes_at_most_limit_photos_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, root, _photos = _record(tmp_path, monkeypatch)
    engine = FakeVision()
    report = describe.run(lb, engine, roots=describe.Roots(_roots(root)), limit=1)
    assert (report.found, report.written, len(engine.seen)) == (4, 1, 1)
    assert _notes(lb)[0]["at"] == CAFE_AT
    more = describe.run(lb, engine, roots=describe.Roots(_roots(root)), limit=1)
    assert (more.found, more.already, more.written) == (3, 1, 1)
    assert [n["at"] for n in _notes(lb)] == [CAFE_AT, QUAY_AT]


def test_a_dry_run_lists_and_writes_nothing_and_needs_no_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, root, _photos = _record(tmp_path, monkeypatch)
    seq = lb.meta["seq"]
    report = describe.run(lb, None, roots=describe.Roots(_roots(root)), dry_run=True)
    assert report.dry_run and report.found == 4 and report.written == 0 and lb.meta["seq"] == seq
    assert "4 keepers would be described" in describe.summary(report)


def test_no_socket_is_opened_while_describing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a socket was opened while describing")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    lb, root, _photos = _record(tmp_path, monkeypatch)
    engine = FakeVision()
    report = describe.run(lb, engine, roots=describe.Roots(_roots(root)))
    assert report.written == 2
    assert set(engine.offline_seen) == {"1"}  # the hub is told so too, for the real engine's sake
    assert os.environ.get("HF_HUB_OFFLINE") != "1"  # and only for the run


def test_a_model_not_on_this_machine_stops_with_the_flag_that_fetches_it_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, root, _photos = _record(tmp_path, monkeypatch)
    engine = FakeVision(ready=False)
    with pytest.raises(describe.ModelMissing, match="--fetch-model"):
        describe.run(lb, engine, roots=describe.Roots(_roots(root)))
    assert engine.fetched == 0 and _notes(lb) == []
    report = describe.run(lb, engine, roots=describe.Roots(_roots(root)), fetch_model=True)
    assert engine.fetched == 1 and report.written == 2


# -- the engine --------------------------------------------------------------------------------------


def _importer(*present: str) -> Any:
    def import_module(name: str) -> Any:
        if name in present:
            return object()
        raise ImportError(name)

    return import_module


def test_without_mlx_vlm_the_message_names_the_extra_and_apple_silicon() -> None:
    with pytest.raises(describe.EngineMissing, match=r"openlogbook\[describe\].*Apple silicon"):
        describe.detect(importer=_importer())


def test_with_mlx_vlm_the_engine_is_mlx_vlm_on_the_default_model_or_the_one_named() -> None:
    engine = describe.detect(importer=_importer("mlx_vlm"))
    assert engine.name == "mlx-vlm" and engine.model == describe.DEFAULT_MODEL
    assert "4bit" in describe.DEFAULT_MODEL and "mlx-community/" in describe.DEFAULT_MODEL
    assert (
        describe.detect("example/other-vlm-4bit", importer=_importer("mlx_vlm")).model
        == "example/other-vlm-4bit"
    )


# -- through the CLI ---------------------------------------------------------------------------------


def test_describe_without_an_engine_prints_the_install_and_fetch_lines_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch)
    monkeypatch.setattr(
        describe, "detect", lambda model, **_k: (_ for _ in ()).throw(describe.EngineMissing("x"))
    )
    with pytest.raises(SystemExit) as stop:
        cli.main(["describe", "keepers"])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "openlogbook[describe]" in err and "describe keepers --fetch-model" in err
    assert "pip install" in err
    assert _notes(Logbook.find()) == []


def test_describe_with_the_model_missing_prints_the_fetch_line_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, root, _photos = _record(tmp_path, monkeypatch)
    engine = FakeVision(ready=False)
    monkeypatch.setattr(describe, "detect", lambda model, **_k: engine)
    with pytest.raises(SystemExit) as stop:
        cli.main(["describe", "keepers", "--photos", str(root / "pictures")])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "fake-vlm-4bit" in err and "--fetch-model" in err and engine.fetched == 0


def test_describe_keepers_writes_the_notes_and_show_prints_each_under_its_keeper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, root, photos = _record(tmp_path, monkeypatch)
    engine = FakeVision()
    monkeypatch.setattr(describe, "detect", lambda model, **_k: engine)
    cli.main(
        [
            "describe",
            "keepers",
            "--photos",
            str(root / "Photos Library.photoslibrary"),
            "--photos",
            str(root / "pictures"),
        ]
    )
    captured = capsys.readouterr()
    assert "4/4" in captured.err and "IMG_101030" in captured.err  # the progress lines
    head = captured.out.splitlines()[0]
    assert head.startswith("described 2 keepers with fake-vision (fake-vlm-4bit)")
    assert "2 answers could not be read" in captured.out and "1 without its photo file" in captured.out
    assert len(_notes(lb)) == 2
    rows = _run(capsys, "show", DAY).splitlines()
    cafe_name = photos[f"p-{CAFE_AT}"]["payload"]["file_name"]
    keeper_row = next(i for i, r in enumerate(rows) if "keeper" in r and cafe_name in r)
    under = rows[keeper_row + 1]
    assert under.strip().startswith(TABLE) and "table, bread, coffee, window" in under
    assert under.startswith(" " * 20), "indented under the keeper's text, no clock of its own"
    assert sum(TABLE in r for r in rows) == 1, "the note is shown once, under its keeper"
    quay_rows = [r for r in rows if QUAY in r]
    assert len(quay_rows) == 1, "one description for a photo in both lanes, under its first keeper"
    own_rows = [r for r in rows if "note" in r and describe.SOURCE in r]
    assert own_rows == [], "no row of its own while the keeper shows"
    described = [r for r in rows if r.startswith(" " * 20) or describe.SOURCE in r]
    assert described and not any("Kari" in r for r in described), "a face's name never reaches a description"
    # the rerun says so and writes nothing
    out = _run(capsys, "describe", "keepers", "--photos", str(root / "pictures"), "--json")
    data = json.loads(out)
    assert data["written"] == 0 and data["already"] == 2 and data["engine"] == "fake-vision"
    assert data["model"] == "fake-vlm-4bit" and data["unparsed"] == 2
    assert data["skipped"] == {describe.NO_FILE: 1}, "a photo described once is already, wherever its file is"


def test_show_prints_a_description_whose_keeper_is_retracted_as_its_own_note_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb, root, _photos = _record(tmp_path, monkeypatch)
    describe.run(lb, FakeVision(), roots=describe.Roots(_roots(root)))
    cafe = next(line for line in lb.lines() if line["kind"] == "keeper" and line["at"] == CAFE_AT)
    lb.retract(cafe["seq"], "not a keeper")
    rows = _run(capsys, "show", DAY).splitlines()
    row = next(r for r in rows if TABLE in r)
    assert "note" in row and describe.SOURCE in row and "IMG_101030" in row


def test_describe_only_knows_keepers_and_a_bad_since_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _record(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as stop:
        cli.main(["describe", "photos"])
    assert stop.value.code == 2 and "keepers" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stop:
        cli.main(["describe", "keepers", "--since", "yesterday"])
    assert stop.value.code == 2
