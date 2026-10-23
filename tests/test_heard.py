"""What you heard (RFC 0046), read back: the words of each text format, `logbook show heard` over a day or a
window with an excerpt and the text's length, `search` finding words inside a text, the row `show`
prints, the tier, and nothing leaving: a crossing and a shared page leave every `heard` line and its
text at home unless the destination's entry says `"heard": true`. The texts are written by `sync heard`
against a fake web of example.org feeds; invented podcasts and the Oslo persona, who does not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_heard_sync import FEED, JSON, SRT, TEXT, VTT, _heard, _listen, _ttml, _watch, _web

from logbook import cli
from logbook.commands import heard as heard_command
from logbook.contrib.adapters import heard as step
from logbook.core import crossing, heard, share
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
DAY = "2026-10-14"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Logbook:
    """A record with two listens and a watch on 14 October, a listen on the 16th, and the texts of all
    four, written by `sync heard` from a fake web and the owner's caption folder."""
    import os

    record = Logbook.init(Path(os.environ["LOGBOOK_HOME"]), TZ)
    _listen(record, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")
    _listen(record, "2026-10-14T16:10:00Z", "EP-2", "Episode 13: the tide", f"{FEED}/13.srt")
    _watch(record, "2026-10-14T19:05:00Z", "aB3dE5fG7hI", "Splicing a three-strand rope")
    _listen(record, "2026-10-16T07:00:00Z", "EP-3", "Episode 14: knots", f"{FEED}/14.json")
    _web(
        monkeypatch,
        {
            f"{FEED}/12.vtt": (VTT, {"Content-Type": "text/vtt"}),
            f"{FEED}/13.srt": (SRT, {"Content-Language": "en"}),
            f"{FEED}/14.json": (JSON, {"Content-Type": "application/json"}),
        },
    )
    monkeypatch.setattr(step, "sleep", lambda _s: None)
    captions = tmp_path / "Captions"
    captions.mkdir()
    (captions / "aB3dE5fG7hI.en.vtt").write_bytes(
        b"WEBVTT\n\n00:00.000 --> 00:02.000\nToday we splice a three-strand rope.\n"
    )
    monkeypatch.setenv("LOGBOOK_HEARD", "feed,captions")
    monkeypatch.setenv("LOGBOOK_HEARD_CAPTIONS_DIR", str(captions))
    cli.main(["sync", "heard"])
    capsys.readouterr()
    assert len(_heard(record)) == 4
    return record


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


# -- the words of a text -----------------------------------------------------------------------------------


def test_the_words_of_each_format_drop_timings_tags_and_numbers() -> None:
    assert heard.words_of(VTT, "vtt") == "Velkommen til Havnepodden.\nI dag snakker vi om østkaia."
    assert heard.words_of(SRT, "srt") == "The east berth is full.\nThe tide turns at noon."
    assert heard.words_of(JSON, "json") == "Knots first,\nthen the splice."
    assert heard.words_of(TEXT, "text") == "Per Hansen reads the harbour notices.\nThe ferry leaves at seven."
    ttml = _ttml("nb", ("Hei", ",", "Kari", "."), ("Ha", "det", "."))
    assert heard.words_of(ttml, "ttml") == "Hei, Kari.\nHa det."
    assert heard.language_of(ttml, "ttml") == "nb"
    assert heard.language_of(VTT, "vtt") == "nb"
    with pytest.raises(heard.Unreadable):
        heard.words_of(b"\xff\xfe not utf-8", "text")
    with pytest.raises(heard.Unreadable):
        heard.words_of(b"{not json", "json")


def test_the_format_is_the_media_type_else_the_name_else_the_first_bytes() -> None:
    assert heard.format_of("application/srt", None, SRT) == "srt"
    assert heard.format_of("text/plain; charset=utf-8", None, VTT) == "vtt"
    assert heard.format_of(None, "t.json", b"{}") == "json"
    assert heard.format_of("application/octet-stream", None, SRT) == "srt"
    assert heard.format_of(None, None, b"<!DOCTYPE html><p>x</p>") == "html"
    assert heard.format_of(None, None, b"just words") is None


def test_an_excerpt_is_one_line_cut_at_a_word() -> None:
    words = "Velkommen til Havnepodden.\n" + "I dag snakker vi om østkaia og om tidevannet " * 5
    cut = heard.excerpt(words)
    assert "\n" not in cut and cut.endswith("…") and len(cut) <= heard.EXCERPT_CHARS + 1
    assert words.replace("\n", " ").startswith(cut[:-1])
    assert heard.excerpt("Kort.") == "Kort."


# -- logbook show heard ----------------------------------------------------------------------------------


def test_heard_lists_a_days_texts_with_source_language_length_and_excerpt(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _run(capsys, "show", "heard", "--day", DAY)
    assert status == 0, err
    lines = out.splitlines()
    assert lines[0] == "2026-10-14 Wednesday"
    assert (
        lines[1].startswith("  08:40  feed      nb")
        and "words  Episode 12: the east berth — Havnepodden" in lines[1]
    )
    assert lines[2] == "         «Velkommen til Havnepodden. I dag snakker vi om østkaia.»"
    assert "  18:10  feed      en" in out and "«The east berth is full. The tide turns at noon.»" in out
    assert "  21:05  captions  en" in out and "Splicing a three-strand rope — Knots by Ola" in out
    assert lines[-1] == "3 texts, 2026-10-14"
    assert "Episode 14" not in out  # the 16th is another day


def test_heard_json_and_a_window(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = _run(capsys, "show", "heard", "--since", "2026-10-13", "--until", "2026-10-16", "--json")
    assert status == 0
    data = json.loads(out)
    assert data["since"] == "2026-10-13" and data["until"] == "2026-10-16" and data["count"] == 4
    first = data["texts"][0]
    assert set(first) == {
        "id", "of", "at", "day", "media", "title", "by", "text_source", "language",
        "chars", "words", "excerpt", "sealed",
    }  # fmt: skip
    assert [t["day"] for t in data["texts"]] == ["2026-10-14", "2026-10-14", "2026-10-14", "2026-10-16"]
    assert (
        first["chars"] == len("Velkommen til Havnepodden. I dag snakker vi om østkaia.")
        and first["words"] == 9
    )
    status, out, _ = _run(capsys, "show", "heard", "--since", "2026-10-13", "--until", "2026-10-16")
    assert out.splitlines()[0] == "2026-10-16 Friday"  # the latest day first
    assert out.splitlines()[-1] == "4 texts, 2026-10-13 to 2026-10-16"


def test_heard_without_a_window_is_the_last_two_weeks(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(heard_command, "_today", lambda: "2026-10-27")
    status, out, _ = _run(capsys, "show", "heard")
    assert status == 0 and out.splitlines()[-1] == "4 texts, 2026-10-14 to 2026-10-27"
    monkeypatch.setattr(heard_command, "_today", lambda: "2026-12-01")
    status, out, _ = _run(capsys, "show", "heard")
    assert status == 0 and out.startswith("nothing heard from 2026-11-18 to 2026-12-01")


def test_heard_refuses_a_day_beside_a_window_and_a_window_backwards(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(capsys, "show", "heard", "--day", DAY, "--since", DAY)[0] == 2
    status, _, err = _run(capsys, "show", "heard", "--since", "2026-10-16", "--until", "2026-10-14")
    assert status == 2 and "backwards" in err
    status, _, err = _run(capsys, "show", "heard", "--day", "14 October")
    assert status == 2 and "not a date" in err


def test_show_heard_takes_no_name_and_the_root_help_keeps_its_32_commands(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _, err = _run(capsys, "show", "heard", DAY)
    assert status == 2 and f"one day is `--day {DAY}`" in err
    status, _, err = _run(capsys, "heard", "--day", DAY)  # never a command of its own
    assert status == 2 and "invalid choice: 'heard'" in err
    root = _run(capsys, "--help")[1]
    assert not any(line.lstrip().startswith("heard ") for line in root.splitlines())
    status, out, _ = _run(capsys, "show", "--help")
    assert status == 0 and "heard" in out and "--day YYYY-MM-DD" in out


def test_show_defines_day_once_for_every_reader_that_takes_one_day() -> None:
    from logbook.commands import parser

    (sub,) = (action for action in parser.build_parser()._actions if action.dest == "cmd")
    days = [action for action in sub.choices["show"]._actions if "--day" in action.option_strings]
    assert [(action.dest, action.help) for action in days] == [("show_day", "one local day")]
    assert parser.build_parser().parse_args(["show", "heard", "--day", DAY]).show_day == DAY


def test_a_retracted_text_or_a_text_of_a_retracted_listen_is_not_listed(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = sorted(_heard(lb), key=lambda line: line["at"])
    lb.retract(int(lines[0]["seq"]), "not mine")
    listens = {str(line["id"]): line for line in lb.lines() if line["kind"] == "listen"}
    lb.retract(int(listens[lines[1]["payload"]["of"]]["seq"]), "the car played it")
    status, out, _ = _run(capsys, "show", "heard", "--day", DAY, "--json")
    assert status == 0
    assert [t["title"] for t in json.loads(out)["texts"]] == ["Splicing a three-strand rope"]


def test_a_text_missing_from_the_store_is_said_so(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    line = sorted(_heard(lb), key=lambda line: line["at"])[0]
    (lb.root / "attachments" / line["payload"]["text"]["sha256"]).unlink()
    status, out, _ = _run(capsys, "show", "heard", "--day", DAY)
    assert status == 0 and "(the text is not in the attachment store)" in out


# -- search, show, the tier ------------------------------------------------------------------------------


def test_search_finds_words_inside_a_text(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = _run(capsys, "search", "østkaia", "--json")
    assert status == 0, err
    data = json.loads(out)
    hits = [hit for day in data["days"] for hit in day["lines"]]
    assert data["hits"] == 1 and hits[0]["kind"] == "heard" and "[østkaia]" in hits[0]["snippet"]
    status, out, _ = _run(capsys, "search", '"three-strand rope"', "--kinds", "heard", "--json")
    assert status == 0 and json.loads(out)["hits"] == 1
    status, out, _ = _run(capsys, "search", "example", "--kinds", "heard", "--json")
    assert status == 0 and json.loads(out)["hits"] == 0  # never the URL's or the digest's words


def test_show_prints_a_heard_row(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = _run(capsys, "show", DAY)
    assert status == 0
    assert "heard      heard          Episode 12: the east berth — Havnepodden · feed · nb · 9 words" in out


def test_every_text_is_tier_2_like_the_listen_it_belongs_to(lb: Logbook) -> None:
    assert {line["tier"] for line in _heard(lb)} == {2}
    assert {line["tier"] for line in lb.lines() if line["kind"] in ("listen", "watch")} == {2}


# -- nothing leaves ------------------------------------------------------------------------------------


def _policy(lb: Logbook, entry: dict[str, Any]) -> None:
    (lb.root / "policy" / "crossing.json").write_text(json.dumps({"ola": entry}), encoding="utf-8")


def test_a_crossing_leaves_every_text_home_unless_the_entry_names_it(lb: Logbook) -> None:
    _policy(lb, {"max_tier": 2})
    req = crossing.request(
        lb, "ola", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", (1, 2), signed_only=False
    )
    sel = crossing.select(lb, req)
    assert "heard" not in sel.by_kind and sel.by_kind.get("listen") == 3
    assert sel.held_back_by_entry == 4
    texts = {line["payload"]["text"]["sha256"] for line in _heard(lb)}
    assert not texts & {blob["sha256"] for blob in sel.blobs}

    _policy(lb, {"max_tier": 2, "heard": True})
    sel = crossing.select(lb, req)
    assert sel.by_kind["heard"] == 4 and sel.held_back_by_entry == 0
    assert texts <= {blob["sha256"] for blob in sel.blobs}

    _policy(lb, {"max_tier": 1, "heard": True})  # the entry names them, the tier still decides
    req = crossing.request(lb, "ola", "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", (1,), signed_only=False)
    assert "heard" not in crossing.select(lb, req).by_kind


def test_a_shared_page_carries_no_text_unless_the_entry_names_it(lb: Logbook) -> None:
    _policy(lb, {"max_tier": 2})
    sel = share.select(lb, DAY, 2, "ola")
    assert not [line for line in sel.lines if line["kind"] == "heard"]
    assert [line["kind"] for line in sel.lines].count("listen") == 2
    assert not share.select(lb, DAY, 2).lines or all(
        line["kind"] != "heard" for line in share.select(lb, DAY, 2).lines
    )
    _policy(lb, {"max_tier": 2, "heard": True})
    assert len([line for line in share.select(lb, DAY, 2, "ola").lines if line["kind"] == "heard"]) == 3


def test_the_key_is_read_strictly(tmp_path: Path) -> None:
    (tmp_path / "policy").mkdir()
    for entry, crosses in (({"max_tier": 2, "heard": "yes"}, False), ({"max_tier": 2, "heard": True}, True)):
        (tmp_path / "policy" / "crossing.json").write_text(json.dumps({"ola": entry}), encoding="utf-8")
        assert heard.crosses(tmp_path, "ola") is crosses
    assert heard.crosses(tmp_path, "per") is False and heard.crosses(tmp_path, None) is False


def test_heard_and_peoples_mail_are_two_rules_a_line_passes_both_and_neither_decides_for_the_other(
    lb: Logbook,
) -> None:
    """RFC 0046 §9 beside RFC 0045: a heard line crosses only under an entry that says `"heard": true`,
    a mail only when a person is on it unless the request says `--all-mail`. With each key on and off,
    the heard lines that cross depend on the entry alone and the mails on `--all-mail` alone."""
    kari = "019cadd3-6bc0-7dcd-9133-043f5aabf2b1"
    lb.set_owner_emails(["ines@example.org"])
    resolution = {
        "schema": "resolution/v1",
        "ref": {"kind": "email", "value": "kari@example.org"},
        "entity": {"type": "person", "id": kari, "registry": "logbook"},
        "label": "Kari Nordmann",
        "method": "exact",
    }
    lb.append("2026-10-01T09:00:00Z", "ios-contacts", "resolution", 2, resolution, tz=TZ)

    def mail(at: str, sender: str) -> str:
        payload = {
            "schema": "mail/v1",
            "raw_id": f"m-{at}@mail.example.org",
            "thread": f"m-{at}@mail.example.org",
            "subject": "Berth 14",
            "direction": "received",
            "from": {"email": sender},
            "to": [{"email": "ines@example.org"}],
            "size": 1024,
        }
        return str(lb.append(at, "mail", "mail", 2, payload, tz=TZ)["id"])

    from_kari = mail("2026-10-14T09:00:00Z", "kari@example.org")
    mail("2026-10-14T10:00:00Z", "no-reply@harbour.example.org")  # no person on it
    heard_ids = {str(line["id"]) for line in _heard(lb)}
    texts = {line["payload"]["text"]["sha256"] for line in _heard(lb)}

    def crossed(heard_key: bool, all_mail: bool) -> crossing.Selection:
        _policy(lb, {"max_tier": 2, "heard": True} if heard_key else {"max_tier": 2})
        req = crossing.request(
            lb,
            "ola",
            "2026-10-01T00:00:00Z",
            "2026-11-01T00:00:00Z",
            (1, 2),
            signed_only=False,
            all_mail=all_mail,
        )
        return crossing.select(lb, req)

    def kinds(sel: crossing.Selection, kind: str) -> set[str]:
        return {str(line["id"]) for line in sel.lines if line["kind"] == kind}

    every_mail = {str(line["id"]) for line in lb.lines() if line["kind"] == "mail"}
    runs = {(h, m): crossed(h, m) for h in (False, True) for m in (False, True)}
    for (heard_key, all_mail), sel in runs.items():
        assert kinds(sel, "heard") == (heard_ids if heard_key else set()), (heard_key, all_mail)
        assert kinds(sel, "mail") == (every_mail if all_mail else {from_kari}), (heard_key, all_mail)
        assert len(kinds(sel, "listen")) == 3  # neither rule touches a listen
        assert sel.held_back_by_entry == (0 if heard_key else 4), (heard_key, all_mail)
        assert sel.mail_held_back == (None if all_mail else 1), (heard_key, all_mail)
        assert (texts <= {b["sha256"] for b in sel.blobs}) is heard_key  # a text leaves with its line only
    for all_mail in (False, True):  # the heard key never changes which mails cross
        assert kinds(runs[(False, all_mail)], "mail") == kinds(runs[(True, all_mail)], "mail")
    for heard_key in (False, True):  # --all-mail never changes which heard lines cross
        assert kinds(runs[(heard_key, False)], "heard") == kinds(runs[(heard_key, True)], "heard")


def test_a_share_refuses_a_sealed_day_first_and_carries_heard_only_under_the_entry(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`export share` (#370 beside RFC 0046 §9): a day holding a heard line and a sealed line is refused
    with #370's sentence, whatever the entry says of `heard`, before anything is written; a plain day
    with heard lines shares without them, and without their texts, unless the entry says `"heard": true`."""
    import os
    import zipfile

    from logbook.core import sealing

    # a record that seals: the listen, its heard line and a note are tier 2, so all three are sealed
    pairs = [sealing.generate_identity() for _ in range(2)]
    identity = tmp_path / "keys" / "ines.txt"
    sealing.write_identity_file(identity, pairs[0][0], "synthetic, for the sealed share test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(identity))
    sealed = Logbook.init(tmp_path / "sealed", TZ)
    meta = sealed.meta
    meta["recipients"] = [recipient for _, recipient in pairs]
    sealed._save_meta(meta)
    sealed = Logbook(sealed.root)
    _listen(sealed, "2026-10-14T06:40:00Z", "EP-1", "Episode 12: the east berth", f"{FEED}/12.vtt")
    sealed.append(
        "2026-10-14T12:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "Solvind at the berth"}
    )
    monkeypatch.setenv("LOGBOOK_HOME", str(sealed.root))
    cli.main(["sync", "heard"])
    capsys.readouterr()
    assert [line["kind"] for line in sealed.lines() if line["kind"] == "heard"] == ["heard"]
    refusal = (
        f"export share day {DAY}: this day holds sealed lines, and a shared page cannot carry them yet; "
        "a sealed day shares after v1 (RFC 0029)"
    )
    for entry in ({"max_tier": 2}, {"max_tier": 2, "heard": True}):
        _policy(sealed, entry)
        before = (sealed.meta["seq"], sealed.meta["head"])
        out = tmp_path / "pages" / "sealed-to-ola.zip"
        with pytest.raises(share.ShareError) as refused:
            share.share_day(sealed, DAY, "ola", 2, out)
        assert str(refused.value) == refusal, entry
        assert not out.parent.exists() and (sealed.meta["seq"], sealed.meta["head"]) == before

    # a plain record (the fixture's): the day's three texts leave only under the entry that names them
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    os.environ.pop("LOGBOOK_IDENTITY_FILE", None)
    texts = {
        line["payload"]["text"]["sha256"] for line in _heard(lb) if line["at"].startswith(DAY)
    }  # fmt: skip
    for entry, carried in (({"max_tier": 2}, False), ({"max_tier": 2, "heard": True}, True)):
        _policy(lb, entry)
        out = tmp_path / f"plain-{carried}.zip"
        shared = share.share_day(lb, DAY, "ola", 2, out)
        kinds = [line["kind"] for line in shared.selection.lines]
        assert kinds.count("heard") == (3 if carried else 0) and kinds.count("listen") == 2, entry
        with zipfile.ZipFile(out) as zf:
            members = {name.rsplit("/", 1)[-1] for name in zf.namelist() if name.startswith("attachments/")}
        assert (texts <= members) is carried and (not texts & members) is (not carried), entry
