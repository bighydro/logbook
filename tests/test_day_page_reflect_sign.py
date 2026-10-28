"""The Day page's two owner acts (`logbook serve`): Reflect writes the reflection note through `day
reflect`'s own function, the Wispr Flow "reflect" draft offered prefilled, a recording heard through
the `day reflect --audio` path, and the proposals shown as checkboxes; Sign signs the day through
`signing.sign` exactly as `day reflect --sign` does, the reflection among the lines confirmed and the
accepted dispositions in the signature, and a signed day is signed again superseding the standing
signature. Both are a POST from this machine only, and nothing is written without the click. The
policy's `write` list is never read: this is the owner's own page, not the door. Whisper is faked: no
model runs. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import http.client
import itertools
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import serve
from logbook.core import attachments, notes, policy, signing, store
from logbook.core.store import Logbook
from logbook.labs import transcribe

TZ = "Europe/Oslo"
DAY = "2026-03-03"  # a Tuesday, CET
LOOPBACK = "127.0.0.1"
PROMISES = {
    2: "I'll send the mooring photos to the harbour office by Friday.",
    3: "I need to call the crane company about the haul-out.",
    4: "I have to buy varnish for the hatch.",
}
SENTENCES = [
    "Good day on the boat.",
    "The mooring photos went out to the harbour office.",  # 2: kept #2
    "The crane company call about the haul-out is for next week.",  # 3: carried #3
    "Forget the varnish, the hatch can wait.",  # 4: dropped #4
    "I'll fix the bilge pump on Saturday.",  # 5: a commitment
    "Ola should book the ferry for Sunday.",  # 6: a delegation to Ola
    "Ask Ines to send the insurance papers.",  # 7: a delegation to Ines
    "Ich werde die Rechnung morgen bezahlen.",  # 8: a commitment, in German
    "Ola soll den Anhänger zurückbringen.",  # 9: a delegation to Ola, in German
]
REFLECTION = " ".join(SENTENCES)
# the proposals of REFLECTION, numbered as printed: commitments, delegations, then dispositions
COMMITMENT_BILGE, COMMITMENT_BILL, TO_OLA, TO_INES, TO_OLA_DE, KEPT_2, CARRIED_3, DROPPED_4 = range(1, 9)
NO_MODEL = "No model touched this page. What a model drafted is marked as a draft."


def _location(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"dawarich:{at}"},
    }


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """3 March 2026 (CET): two locations and three of the owner's commitments on the page."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
    lb.append_many(
        [
            _location("2026-03-03T06:30:00Z"),  # seq 1
            _note("2026-03-03T07:00:00Z", PROMISES[2]),  # seq 2
            _note("2026-03-03T08:00:00Z", PROMISES[3]),  # seq 3
            _note("2026-03-03T09:00:00Z", PROMISES[4]),  # seq 4
            _location("2026-03-03T18:00:00Z"),  # seq 5
        ]
    )
    return lb


class FakeEngine:
    """Hears REFLECTION in every recording, as `tests/test_day_reflect.py`'s engine does."""

    name = "fake-whisper"

    def __init__(self) -> None:
        self.model = "small"
        self.loaded: list[Path] = []
        self.sizes: list[int] = []

    def ready(self) -> bool:
        return True

    def fetch(self) -> None:
        raise AssertionError("the page never fetches a model")

    def load(self, path: Path) -> tuple[list[float], int]:
        self.loaded.append(Path(path))
        self.sizes.append(Path(path).stat().st_size)
        return [0.0] * 32_000, 16_000

    def transcribe(self, samples: Any, rate: int, language: str | None) -> transcribe.Result:
        cut = REFLECTION.index(" to the harbour office")
        return transcribe.Result(
            [transcribe.Segment(0.0, 9.0, REFLECTION[:cut]), transcribe.Segment(9.0, 18.0, REFLECTION[cut:])],
            language or "en",
        )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    found = FakeEngine()
    monkeypatch.setattr(transcribe, "detect", lambda model="small", **_k: found)
    return found


def _dictation(lb: Logbook, at: str, text: str) -> dict[str, Any]:
    """A Wispr Flow dictation as the adapter writes it: a transcript/v1 line, tier 3, its text in the
    attachment store."""
    data = text.encode("utf-8")
    lb.attach(data)
    return lb.append(
        at=at,
        source="wispr-flow",
        kind="transcript",
        tier=3,
        payload={
            "schema": "transcript/v1",
            "provider": "wispr-flow",
            "raw_id": "wispr-flow:00000001-0000-4000-8000-000000000000",
            "participants": [],
            "content": attachments.reference(data, "text/plain"),
            "extra": {"text": "formatted", "app": "com.example.notes"},
        },
    )


def _counting_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every new line's id, `recorded_at` and a signature's moment fixed and in order, so the lines
    two writers append to two copies of one record compare byte for byte."""
    counter = itertools.count(1)
    monkeypatch.setattr(store, "uuid7", lambda: f"019ca000-0000-7000-8000-{next(counter):012d}")
    for module in (store, signing, notes):
        monkeypatch.setattr(module, "now_utc", lambda: "2026-03-03T21:45:00Z")


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _on(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(root))


def _twin(lb: Logbook, tmp_path: Path) -> Path:
    return Path(shutil.copytree(lb.root, tmp_path / "twin"))


def _lines(root: Path) -> list[bytes]:
    return (root / "logbook" / "2026" / "03.jsonl").read_bytes().splitlines()


def _by_seq(lb: Logbook) -> dict[int, dict[str, Any]]:
    return {int(line["seq"]): line for line in lb.lines()}


def _ids(lb: Logbook) -> dict[int, str]:
    return {seq: str(line["id"]) for seq, line in _by_seq(lb).items()}


def _files(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _page(site: serve.Site, day: str = DAY) -> str:
    response = site.respond(f"/day/{day}", "")
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _post(
    site: serve.Site,
    to: str,
    client: str = LOOPBACK,
    origin: str | None = None,
    upload: serve.Upload | None = None,
    day: str = DAY,
    **form: str,
) -> serve.Response:
    """A POST to the Day's `to` (reflect or sign) with these fields, as `Handler.do_POST` hands it on."""
    return site.write(f"/day/{day}/{to}", form, client, origin, upload)


def _form(page: str, cls: str) -> str:
    found = re.search(rf'<form class="{cls}"[^>]*>.*?</form>', page, re.S)
    assert found is not None, f"no form.{cls} on the page"
    return found.group(0)


def _hidden(form: str) -> dict[str, str]:
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)
    }


def _signing(site: serve.Site) -> dict[str, str]:
    """The hidden fields of the page's Sign form: what the browser posts with the boxes ticked."""
    return {k: v for k, v in _hidden(_form(_page(site), "sign")).items() if k != "act"}


# -- Reflect -------------------------------------------------------------------------------------------------


def test_reflect_writes_the_reflection_as_day_reflect_writes_it(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    twin = _twin(lb, tmp_path)
    _counting_ids(monkeypatch)
    _on(monkeypatch, twin)
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION)
    _on(monkeypatch, lb.root)
    _counting_ids(monkeypatch)
    site = serve.Site(lb)
    response = _post(site, "reflect", text=REFLECTION, act="reflect")
    assert response.status == 303 and response.location == f"/day/{DAY}#close"
    assert _lines(lb.root) == _lines(twin), "the note is the line the command writes, byte for byte"
    assert (lb.root / "logbook.json").read_bytes() == (twin / "logbook.json").read_bytes()
    line = _by_seq(lb)[6]
    assert (line["kind"], line["tier"], line["source"]) == ("note", 2, "reflect")
    assert line["payload"] == {"schema": "note/v1", "text": REFLECTION, "labels": ["reflection"]}

    page = _page(site)
    assert page.index("<h2>Reflection</h2>") < page.index("<h2>Timeline</h2>") < page.index('id="close"')
    sign = _form(page, "sign")
    boxes = re.findall(r'<input type="checkbox" name="accept" value="(\d+)"( checked)?>', sign)
    assert [int(n) for n, _ in boxes] == list(range(1, 9)), "every proposal a box, numbered as printed"
    assert all(not checked for _, checked in boxes), "a proposal is a guess until the owner ticks it"
    for word in ("commitment", "delegation", "kept", "carried", "dropped"):
        assert word in sign
    assert "to Ola: “Ola should book the ferry for Sunday.”" in sign
    assert "#2 “I'll send the mooring photos to the harbour office by Friday.”" in html.unescape(sign)
    assert _hidden(sign)["reflection"] == line["id"]

    again = _post(site, "reflect", text=f"  {REFLECTION}\n", act="reflect")
    assert again.status == 303 and lb.meta["seq"] == 6, "the same words on the day: never written twice"


def test_an_empty_reflection_and_a_day_ahead_are_refused_with_nothing_written(lb: Logbook) -> None:
    site = serve.Site(lb)
    before = _files(lb.root)
    empty = _post(site, "reflect", text="   ", act="reflect")
    assert empty.status == 400 and "empty" in empty.body.decode("utf-8")
    ahead = "2099-06-01"
    page = _page(site, ahead)
    assert "ahead of today" in page and "<form" not in page.split('id="close"')[1]
    refused = _post(site, "reflect", day=ahead, text="Not yet lived.", act="reflect")
    assert refused.status == 400 and "ahead of today" in refused.body.decode("utf-8")
    assert _post(site, "sign", day=ahead, act="sign").status == 400
    assert _files(lb.root) == before


def test_the_wispr_draft_is_offered_prefilled_and_taken_only_on_the_click(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dictation = _dictation(lb, "2026-03-03T20:40:00Z", f"Reflect: {REFLECTION}")  # seq 6
    twin = _twin(lb, tmp_path)
    site = serve.Site(lb)
    before = _files(lb.root)
    form = _form(_page(site), "reflect")
    assert f">{html.escape(REFLECTION, quote=False)}</textarea>" in form, "the draft, without the cue"
    assert _hidden(form)["dictation"] == dictation["id"]
    assert "Wispr Flow" in form and "#6" in form
    assert _files(lb.root) == before, "offered, not taken: reading the page writes nothing"

    _counting_ids(monkeypatch)
    _on(monkeypatch, twin)
    _run(capsys, "day", "reflect", DAY, "--from-wispr")
    _on(monkeypatch, lb.root)
    _counting_ids(monkeypatch)
    assert _post(site, "reflect", text=REFLECTION, dictation=dictation["id"], act="reflect").status == 303
    assert _lines(lb.root) == _lines(twin)
    note = _by_seq(lb)[7]
    assert note["payload"]["extra"] == {"dictation": dictation["id"]} and note["at"] == dictation["at"]
    taken = _form(_page(site), "reflect")
    assert "dictation" not in _hidden(taken), "a dictation taken up is not offered again"


def test_an_edited_draft_keeps_the_dictation_it_came_from(lb: Logbook) -> None:
    dictation = _dictation(lb, "2026-03-03T20:40:00Z", f"reflect, {REFLECTION}")
    site = serve.Site(lb)
    edited = "Good day on the boat. Ola should book the ferry for Sunday."
    assert _post(site, "reflect", text=edited, dictation=dictation["id"], act="reflect").status == 303
    note = _by_seq(lb)[7]
    assert note["payload"]["text"] == edited
    assert note["payload"]["extra"] == {"dictation": dictation["id"]} and note["at"] == dictation["at"]
    gone = _post(site, "reflect", text="Other words.", dictation="019ca000-dead", act="reflect")
    assert gone.status == 409 and lb.meta["seq"] == 7


# -- a recording -------------------------------------------------------------------------------------------


def test_a_recording_is_heard_through_the_day_reflect_audio_path(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: FakeEngine,
) -> None:
    audio = tmp_path / "evening.m4a"
    audio.write_bytes(b"not really audio: the fake engine never decodes it")
    twin = _twin(lb, tmp_path)
    _counting_ids(monkeypatch)
    _on(monkeypatch, twin)
    _run(capsys, "day", "reflect", DAY, "--audio", str(audio))
    _on(monkeypatch, lb.root)
    _counting_ids(monkeypatch)
    site = serve.Site(lb, voice=serve.Voice(day_command.heard))
    form = _form(_page(site), "audio")
    assert 'enctype="multipart/form-data"' in form and f'action="/day/{DAY}/reflect"' in form
    assert '<input type="file" name="audio" accept="audio/*" capture>' in form
    assert '<button type="button" class="record" hidden>' in form, "shown by the script where it can record"
    upload = serve.Upload("evening.m4a", "audio/mp4", audio.read_bytes())
    response = _post(site, "reflect", upload=upload, act="hear")
    assert response.status == 303
    assert _lines(lb.root) == _lines(twin), "heard and written as `--audio` hears and writes it"
    heard = _by_seq(lb)[6]["payload"]["extra"]["heard_by"]
    assert heard == {"engine": "fake-whisper", "model": "small", "language": "en"}
    assert engine.loaded[-1].suffix == ".m4a" and engine.sizes[-1] == len(upload.data)
    assert not engine.loaded[-1].exists(), "the recording is not kept"


def test_without_an_engine_the_page_says_why_and_offers_no_recording(lb: Logbook) -> None:
    missing = "no transcription engine is installed; install openlogbook[transcribe]"
    site = serve.Site(lb, voice=serve.Voice(None, missing))
    page = _page(site)
    assert "openlogbook[transcribe]" in page and 'class="audio"' not in page and "<script" not in page
    refused = _post(site, "reflect", upload=serve.Upload("a.webm", "audio/webm", b"x"), act="hear")
    assert refused.status == 400 and "openlogbook[transcribe]" in refused.body.decode("utf-8")
    assert lb.meta["seq"] == 5


def test_the_voice_says_what_this_machine_lacks(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> None:
    """`serve` asks once, when it starts, whether this machine can hear: the extra, then the model."""
    assert day_command.voice().hear is not None and day_command.voice().missing is None
    monkeypatch.setattr(engine, "ready", lambda: False)
    absent = day_command.voice()
    assert absent.hear is None and absent.missing is not None and "--fetch-model" in absent.missing

    def nothing(*_a: Any, **_k: Any) -> Any:
        raise transcribe.EngineMissing(
            "no transcription engine is installed; install openlogbook[transcribe]"
        )

    monkeypatch.setattr(transcribe, "detect", nothing)
    assert "openlogbook[transcribe]" in str(day_command.voice().missing)


def test_without_an_engine_the_voice_gives_the_command_for_this_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stranger test (26 October): the Day and Today said `install openlogbook[transcribe]`, which is
    no command. The page gives the line doctor gives for how this Logbook was installed."""
    from logbook.contrib import doctor

    def nothing(*_a: Any, **_k: Any) -> Any:
        raise transcribe.EngineMissing(
            "no transcription engine is installed; install openlogbook[transcribe]"
        )

    monkeypatch.setattr(transcribe, "detect", nothing)
    pipx = doctor.Install("pipx", frozenset({"crypto"}), "==0.7.0", venv="openlogbook")
    monkeypatch.setattr(doctor, "detect_install", lambda: pipx)
    missing = str(day_command.voice().missing)
    assert missing.endswith('pipx inject openlogbook "openlogbook[crypto,transcribe]==0.7.0"'), missing
    assert "install openlogbook[transcribe]" not in missing and "restart" in missing
    clone = doctor.Install(
        "checkout", folder="/home/ines/src/logbook", python="/home/ines/src/logbook/.venv/bin/python"
    )
    monkeypatch.setattr(doctor, "detect_install", lambda: clone)
    said = str(day_command.voice().missing)  # the short line, every extra the clone has named beside it
    assert "in the clone, /home/ines/src/logbook: uv sync --extra " in said and "--inexact" not in said, said
    assert said.endswith(" --extra transcribe"), said


# -- Sign ----------------------------------------------------------------------------------------------------


def test_sign_through_the_page_is_byte_for_byte_the_cli_signature(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    accepted = f"{TO_OLA},{KEPT_2},{CARRIED_3}"
    twin = _twin(lb, tmp_path)
    _counting_ids(monkeypatch)
    _on(monkeypatch, twin)
    _run(capsys, "day", "reflect", DAY, "--text", REFLECTION, "--sign", "--accept", accepted)
    _on(monkeypatch, lb.root)
    _counting_ids(monkeypatch)
    site = serve.Site(lb)
    assert _post(site, "reflect", text=REFLECTION, act="reflect").status == 303
    response = _post(site, "sign", accept=accepted, act="sign", **_signing(site))
    assert response.status == 303 and response.location == f"/day/{DAY}#close"
    assert _lines(lb.root) == _lines(twin), "reflection, delegation and signature: the command's lines"
    assert (lb.root / "logbook.json").read_bytes() == (twin / "logbook.json").read_bytes()
    ids = _ids(lb)
    signature = _by_seq(lb)[8]
    p = signature["payload"]
    assert p["confirmed"] == [ids[1], ids[2], ids[3], ids[4], ids[5], ids[6], ids[7]]
    assert p["dispositions"] == {ids[2]: "kept", ids[3]: "carried"}
    assert _by_seq(lb)[7]["payload"]["extra"] == {"to": "Ola", "reflection": ids[6]}
    assert lb.verify()[2] == []

    page = _page(site)
    header = page.split("</dl>")[0]
    assert "signed 2026-03-03 22:45" in header and p["page"]["sha256"] in header
    closed = page.split('id="close"')[1]
    assert f"{DAY}: signed 2026-03-03T21:45:00Z as #8 signed-day/v1" in closed
    assert f"page sha256 {p['page']['sha256'][:12]}" in closed
    assert "Sign again" in _form(page, "sign")


def test_signing_with_nothing_ticked_accepts_nothing(lb: Logbook) -> None:
    site = serve.Site(lb)
    _post(site, "reflect", text=REFLECTION, act="reflect")
    assert _post(site, "sign", act="sign", **_signing(site)).status == 303
    p = _by_seq(lb)[7]["payload"]
    assert "dispositions" not in p and len(p["confirmed"]) == 6, "the page and the reflection; no delegation"
    assert [line["kind"] for line in lb.lines()].count("note") == 4


def test_signing_a_signed_day_again_supersedes_and_keeps_what_it_said(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        capsys,
        "day",
        "sign",
        DAY,
        "--confirm",
        "1,2,3,4",
        "--kept",
        "4",
        "--note",
        "Quiet day.",
        "--at",
        "2026-03-03T19:00:00+01:00",
    )
    first = _by_seq(lb)[6]
    site = serve.Site(lb)
    assert _post(site, "reflect", text=REFLECTION, act="reflect").status == 303  # seq 7
    page = _page(site)
    sign = _form(page, "sign")
    assert "Sign again" in sign and "keeps from the signature it supersedes (#6)" in sign
    twin = _twin(lb, tmp_path)
    _counting_ids(monkeypatch)
    assert _post(site, "sign", accept=str(CARRIED_3), act="sign", **_signing(site)).status == 303
    ids = _ids(lb)
    p = _by_seq(lb)[8]["payload"]
    assert p["supersedes"] == first["id"]
    assert p["confirmed"] == [ids[1], ids[2], ids[3], ids[4], ids[7]], (
        "what was confirmed, and the reflection"
    )
    assert p["dispositions"] == {ids[3]: "carried", ids[4]: "kept"}
    assert p["note"] == "Quiet day."
    with lb.index() as idx:
        assert signing.signature_of(idx, DAY)["id"] == _by_seq(lb)[8]["id"]
    assert "supersedes " + first["id"] in _page(site).split('id="close"')[1]

    _counting_ids(monkeypatch)
    _on(monkeypatch, twin)
    _run(capsys, "day", "reflect", DAY, "--sign", "--accept", str(CARRIED_3))
    assert _lines(lb.root) == _lines(twin), "the command's re-signature, byte for byte"


def test_the_policy_write_list_is_never_read(lb: Logbook) -> None:
    """The page is the owner's own Sign path, not the door: an empty `write` list, or none at all,
    changes nothing, and the page never reads the file to find out."""
    path = policy.policy_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": {"max_tier": 1, "write": []}}), encoding="utf-8")
    site = serve.Site(lb)
    _post(site, "reflect", text=REFLECTION, act="reflect")
    assert _post(site, "sign", act="sign", **_signing(site)).status == 303
    assert _by_seq(lb)[7]["kind"] == "signed-day"
    assert json.loads(path.read_text(encoding="utf-8")) == {"mcp": {"max_tier": 1, "write": []}}


# -- refused, and nothing written without the click ------------------------------------------------


def test_a_post_that_is_not_from_this_machine_is_refused(lb: Logbook) -> None:
    site = serve.Site(lb)
    for to, form in (("reflect", {"text": REFLECTION, "act": "reflect"}), ("sign", {"act": "sign"})):
        for client in ("192.168.1.20", "10.0.0.5", "203.0.113.9", "::ffff:203.0.113.9", ""):
            response = _post(site, to, client=client, **form)
            assert response.status == 403, (to, client)
            assert "this machine" in response.body.decode("utf-8")
        for origin in ("http://example.org", "https://logbook.example.org", "http://localhost:8765", "null"):
            assert _post(site, to, origin=origin, **form).status == 403, (to, origin)
    assert lb.meta["seq"] == 5
    assert (
        _post(site, "reflect", origin="http://127.0.0.1:8765", text=REFLECTION, act="reflect").status == 303
    )
    assert (
        _post(site, "sign", client="::1", origin="http://[::1]:8765", act="sign", **_signing(site)).status
        == 303
    )
    assert [line["kind"] for line in lb.lines()][-2:] == ["note", "signed-day"]


def test_nothing_is_written_without_the_click(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    _dictation(lb, "2026-03-03T20:40:00Z", f"Reflect: {REFLECTION}")  # seq 6: a draft offered
    site = serve.Site(lb)
    unsigned = _post(site, "sign", act="sign", reflection="", proposals="")
    assert unsigned.status == 409 and "reflect first" in unsigned.body.decode("utf-8")
    _run(capsys, "day", "reflect", DAY, "--text", "Good day on the boat. The mooring photos went out.")
    site.respond(f"/day/{DAY}", "")  # the first reader brings the index to the head
    before, head = _files(lb.root), lb.meta["head"]
    for path, query in ((f"/day/{DAY}", ""), (f"/day/{DAY}", "open=1"), ("/today", ""), ("/", "")):
        site.respond(path, query)
    fields = _signing(site)
    for to, form in (
        ("reflect", {"text": REFLECTION}),  # no act: not the button
        ("reflect", {"text": REFLECTION, "act": "dance"}),
        ("sign", fields),
        ("sign", {**fields, "act": "reflect"}),
    ):
        assert _post(site, to, **form).status == 400, (to, form)
    stale = _post(site, "sign", act="sign", **{**fields, "proposals": "0" * 16})
    assert stale.status == 409 and "since this page was read" in stale.body.decode("utf-8")
    other = _post(site, "sign", act="sign", **{**fields, "reflection": _ids(lb)[1]})
    assert other.status == 409
    unknown = _post(site, "sign", act="sign", accept="99", **fields)
    assert unknown.status == 400 and "no proposal 99" in unknown.body.decode("utf-8")
    for to in ("reflect", "sign"):
        assert site.respond(f"/day/{DAY}/{to}", "").status == 405
    assert site.write("/day/2026-03-03/close", {"act": "sign"}, LOOPBACK, None).status == 404
    assert lb.meta["head"] == head and _files(lb.root) == before


def test_another_writer_is_refused_without_waiting(lb: Logbook) -> None:
    site = serve.Site(lb)
    _post(site, "reflect", text=REFLECTION, act="reflect")
    fields = _signing(site)
    path = lb.root / "state" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = {"pid": os.getppid(), "command": "logbook sync", "since": "2026-03-03T21:00:00Z"}
    path.write_text(json.dumps(holder), encoding="utf-8")
    for to, form in (
        ("reflect", {"text": "Other words.", "act": "reflect"}),
        ("sign", {**fields, "act": "sign"}),
    ):
        response = _post(site, to, **form)
        assert response.status == 409, to
        said = response.body.decode("utf-8")
        assert (
            "another logbook command is writing to this record (logbook sync" in said
            and "--no-wait" not in said
        )
    assert lb.meta["seq"] == 6 and json.loads(path.read_text(encoding="utf-8")) == holder


# -- the page ------------------------------------------------------------------------------------------------


def test_the_day_page_says_no_model_touched_it_and_names_its_one_script(lb: Logbook) -> None:
    plain = serve.Site(lb).respond(f"/day/{DAY}", "")
    assert NO_MODEL in plain.body.decode("utf-8").split("<footer>")[1]
    assert (
        "<script" not in plain.body.decode("utf-8")
        and "script-src" not in plain.headers["Content-Security-Policy"]
    )
    voiced = serve.Site(lb, voice=serve.Voice(lambda path: None)).respond(f"/day/{DAY}", "")  # type: ignore[arg-type, return-value]
    text = voiced.body.decode("utf-8")
    assert text.count("<script") == 1 and "<script src" not in text
    csp = voiced.headers["Content-Security-Policy"]
    assert f"script-src '{serve.DAY_SCRIPT_HASH}'" in csp and csp.startswith("default-src 'none'")
    assert "connect-src" not in csp, "the recording goes up with the form, never by a fetch"
    static = serve.Site(lb, href=lambda path: path, footer="a static site").page_day(DAY)
    assert NO_MODEL in static and "<form" not in static and "<script" not in static


def test_the_reflection_field_is_in_the_day_s_language(lb: Logbook) -> None:
    """The words of the day decide the field's `lang`, as they decide the language a draft is written
    in (`dream.language_of`), so a phone's keyboard and its spelling follow the owner."""
    assert re.search(r'<textarea[^>]* lang="en"', _form(_page(serve.Site(lb)), "reflect"))
    german = (
        "Ich war heute mit der Fähre auf der Insel, und das Wetter war gut. Die Kinder waren mit Ola auf"
        " dem Boot, und ich habe das Deck gestrichen. Das war ein guter Tag, und der Wind war still."
    )
    Logbook(lb.root).append(**_note("2026-03-03T10:00:00Z", german))
    assert re.search(r'<textarea[^>]* lang="de"', _form(_page(serve.Site(lb)), "reflect"))


def test_reflect_and_sign_round_trip_over_the_socket(lb: Logbook) -> None:
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        origin = f"http://{LOOPBACK}:{port}"
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=10)
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Origin": origin}
        body = urlencode({"text": REFLECTION, "act": "reflect"})
        connection.request("POST", f"/day/{DAY}/reflect", body=body, headers=headers)
        reply = connection.getresponse()
        assert (
            reply.status == 303 and reply.read() == b"" and reply.getheader("Location") == f"/day/{DAY}#close"
        )
        connection.request("GET", f"/day/{DAY}")
        reply = connection.getresponse()
        page = reply.read().decode("utf-8")
        fields = {k: v for k, v in _hidden(_form(page, "sign")).items() if k != "act"}
        ticked = [("accept", str(TO_OLA)), ("accept", str(KEPT_2)), ("act", "sign"), *fields.items()]
        connection.request("POST", f"/day/{DAY}/sign", body=urlencode(ticked), headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b""
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    ids = _ids(lb)
    p = _by_seq(lb)[8]["payload"]
    assert p["dispositions"] == {ids[2]: "kept"} and ids[7] in p["confirmed"]


def test_a_recording_goes_up_as_a_form_over_the_socket(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine
) -> None:
    server = serve.make_server(lb, port=0, voice=serve.Voice(day_command.heard))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        boundary = "----logbook-test-boundary"
        audio = bytes(range(256)) * 64 + b"\r\n--" + b"\r\n\r\n"  # bytes a parser must not cut at
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="act"\r\n\r\nhear\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="audio";'
                ' filename="reflection.webm"\r\nContent-Type: audio/webm\r\n\r\n'
            ).encode()
            + audio
            + f"\r\n--{boundary}--\r\n".encode()
        )
        connection = http.client.HTTPConnection(LOOPBACK, port, timeout=10)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": f"http://{LOOPBACK}:{port}",
        }
        connection.request("POST", f"/day/{DAY}/reflect", body=body, headers=headers)
        reply = connection.getresponse()
        assert reply.status == 303 and reply.read() == b""
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert engine.loaded[-1].suffix == ".webm" and engine.sizes[-1] == len(audio)
    assert _by_seq(lb)[6]["payload"]["text"] == REFLECTION
