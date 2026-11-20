"""Hold's sender fates (RFC 0042 §4, RFC 0037 §10, RFC 0045 §4): the owner keeps a sender or lets one
go with `logbook hold sender ADDRESS_OR_DOMAIN --keep | --let-go --reason TEXT`, one `status/v1` line
on a Hold item of sort `sender` under the writer lock; a later line supersedes an earlier one for the
same sender and nothing is ever deleted; the standing fates fill RFC 0045's rule, so a sender let go is
never a person's mail and stays home from a crossing. Every string here is synthetic: Ines is the
owner, Kari Nordmann and Ola live in Oslo, and none of them exists."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import entities
from logbook.core import crossing, peoples_mail, sender_fates, signing, store
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER_EMAIL = "ines@example.org"
KARI, OLA = "019cadd3-6bc0-7dcd-9133-043f5aabf2c1", "019cadd3-6bc0-7dcd-9133-043f5aabf2c2"
KARI_EMAIL, OLA_EMAIL = "kari@example.org", "ola@example.org"
NEWSLETTER, NEWS_DOMAIN = "letters@news.example.org", "news.example.org"
INVITATIONS = "rsvp@invitations.example.org"


def _resolution(value: str, label: str, entity: str) -> dict[str, Any]:
    return {
        "at": "2026-02-01T09:00:00Z",
        "source": "ios-contacts",
        "kind": "resolution",
        "tier": 2,
        "payload": {
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": value},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": label,
            "method": "exact",
        },
    }


def _mail(at: str, sender: str, subject: str = "Berth 14") -> dict[str, Any]:
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"m-{at}@mail.example.org",
            "thread": f"m-{at}@mail.example.org",
            "subject": subject,
            "direction": "received",
            "from": {"email": sender},
            "to": [{"email": OWNER_EMAIL}],
            "size": 1024,
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Ines's record: Kari and Ola are people it names by address; on 1 March 2026 a mail from Kari, one
    from Ola, two from the newsletter and one from the invitation platform."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.set_owner_emails([OWNER_EMAIL])
    lb.append_many(
        [
            _resolution(KARI_EMAIL, "Kari Nordmann", KARI),
            _resolution(OLA_EMAIL, "Ola Nordmann", OLA),
            _mail("2026-03-01T09:00:00Z", KARI_EMAIL, "Mooring for the weekend"),
            _mail("2026-03-01T10:00:00Z", OLA_EMAIL, "The new sail"),
            _mail("2026-03-01T11:00:00Z", NEWSLETTER, "This week at the harbour"),
            _mail("2026-03-01T12:00:00Z", NEWSLETTER, "Winter storage"),
            _mail("2026-03-01T13:00:00Z", INVITATIONS, "You are invited"),
        ]
    )
    return lb


def _cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(args))
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


def _after(lb: Logbook, seq: int) -> list[dict[str, Any]]:
    with Logbook(lb.root).index() as idx:
        found = [*idx.by_kind("status"), *idx.by_kind("note"), *idx.by_kind("retraction")]
    return sorted((line for line in found if int(line["seq"]) > seq), key=lambda line: int(line["seq"]))


def _seq(lb: Logbook) -> int:
    return int(Logbook(lb.root).meta["seq"])


# -- the writer ------------------------------------------------------------------------------------------


def test_keep_writes_one_status_line_on_the_sender_item(lb: Logbook) -> None:
    seq, head = _seq(lb), Logbook(lb.root).meta["head"]
    code, out, err = _cli("hold", "sender", NEWS_DOMAIN, "--keep")
    assert code == 0, err
    (line,) = _after(lb, seq)
    assert line["kind"] == "status" and line["source"] == "manual" and line["tier"] == 2
    payload = line["payload"]
    assert payload["schema"] == "status/v1"
    assert payload["entity"] == {
        "type": "item",
        "id": "sender:domain:news.example.org",
        "registry": "logbook",
    }
    assert payload["label"] == NEWS_DOMAIN and payload["status"] == "keep"
    assert payload["proposed_by"] == "owner"
    assert "supersedes" not in payload and "reason" not in payload and "note" not in payload
    assert payload["logbook_head"] == head  # the head the fate was read against
    assert entities.validate_status(payload) == []
    assert out.startswith(f"{NEWS_DOMAIN}: kept")


def test_let_go_writes_its_reason_as_a_note_first_then_the_line_naming_it(lb: Logbook) -> None:
    seq = _seq(lb)
    code, _out, err = _cli("hold", "sender", INVITATIONS, "--let-go", "--reason", "parties I never go to")
    assert code == 0, err
    note, line = _after(lb, seq)
    assert note["kind"] == "note" and note["tier"] == 2 and note["source"] == "manual"
    assert note["payload"]["text"] == "parties I never go to" and note["payload"]["labels"] == ["status"]
    assert note["payload"]["extra"] == {
        "entity": {"type": "item", "id": f"sender:email:{INVITATIONS}", "registry": "logbook"}
    }
    assert "let-go" not in json.dumps(note["payload"])  # the note carries the entity, never the fate
    assert line["payload"]["status"] == "let-go" and line["payload"]["reason"] == "parties I never go to"
    assert line["payload"]["note"] == note["id"]
    assert entities.validate_status(line["payload"]) == []


def test_let_go_needs_a_reason_and_nothing_is_written_without_one(lb: Logbook) -> None:
    seq = _seq(lb)
    code, _out, err = _cli("hold", "sender", NEWS_DOMAIN, "--let-go")
    assert code == 2 and "--reason" in err
    code, _out, err = _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "   ")
    assert code == 2
    assert _seq(lb) == seq


@pytest.mark.parametrize(
    "args",
    [
        (NEWS_DOMAIN,),
        (NEWS_DOMAIN, "--keep", "--let-go", "--reason", "both"),
        ("not a sender", "--keep"),
        ("news", "--keep"),
        ("@news.example.org", "--keep"),
        ("letters@", "--keep"),
    ],
)
def test_a_fate_that_is_not_one_is_refused_in_one_sentence(lb: Logbook, args: tuple[str, ...]) -> None:
    seq = _seq(lb)
    code, _out, err = _cli("hold", "sender", *args)
    assert code == 2 and err.strip()
    assert _seq(lb) == seq


def test_an_address_and_a_domain_are_written_folded(lb: Logbook) -> None:
    seq = _seq(lb)
    assert _cli("hold", "sender", " Letters@News.Example.ORG ", "--keep")[0] == 0
    assert _cli("hold", "sender", "NEWS.example.org.", "--keep")[0] == 0
    first, second = _after(lb, seq)
    assert first["payload"]["entity"]["id"] == f"sender:email:{NEWSLETTER}"
    assert second["payload"]["entity"]["id"] == "sender:domain:news.example.org"


def test_a_later_fate_supersedes_the_earlier_and_nothing_is_deleted(lb: Logbook) -> None:
    seq = _seq(lb)
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    assert _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "too much")[0] == 0
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    lines = [line for line in _after(lb, seq) if line["kind"] == "status"]
    assert [line["payload"]["status"] for line in lines] == ["keep", "let-go", "keep"]
    assert lines[1]["payload"]["supersedes"] == lines[0]["id"]
    assert lines[2]["payload"]["supersedes"] == lines[1]["id"]
    fates = sender_fates.read(Logbook(lb.root))
    assert fates.kept == frozenset({("domain", NEWS_DOMAIN)}) and fates.let_go == frozenset()


def test_the_same_fate_again_is_refused_and_writes_nothing(lb: Logbook) -> None:
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    seq = _seq(lb)
    code, _out, err = _cli("hold", "sender", NEWS_DOMAIN, "--keep")
    assert code == 2 and "already" in err
    assert _seq(lb) == seq


def test_a_retracted_fate_counts_for_nothing_and_the_one_before_stands_again(lb: Logbook) -> None:
    assert _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "too much")[0] == 0
    seq = _seq(lb)
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    (kept,) = _after(lb, seq)
    lb.append(
        at="2026-03-05T09:00:00Z",
        source="manual",
        kind="retraction",
        tier=1,
        payload={"schema": "retraction/v1", "supersedes": kept["id"], "seq": kept["seq"], "reason": "a slip"},
    )
    fates = sender_fates.read(Logbook(lb.root))
    assert fates.let_go == frozenset({("domain", NEWS_DOMAIN)}) and fates.kept == frozenset()


def test_the_json_names_the_line_written(lb: Logbook) -> None:
    code, out, _err = _cli("hold", "sender", NEWSLETTER, "--let-go", "--reason", "too much", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["sender"] == {"kind": "email", "value": NEWSLETTER}
    assert data["fate"] == "let-go" and data["reason"] == "too much"
    assert isinstance(data["line"], str) and isinstance(data["note"], str) and data["supersedes"] is None


def test_a_busy_record_refuses_with_no_wait_and_writes_nothing(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer takes the record's one writer lock: while another process holds it, `--no-wait`
    refuses in one sentence naming that command, exit 2, and nothing is written."""
    monkeypatch.setattr(store, "WAIT", True)  # `--no-wait` sets it; put back after the test
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lock = lb._lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(
            json.dumps({"pid": other.pid, "command": "sync granola", "since": "2026-10-20T06:00:00Z"}),
            encoding="utf-8",
        )
        seq = _seq(lb)
        code, _out, err = _cli("--no-wait", "hold", "sender", NEWS_DOMAIN, "--keep")
        assert code == 2 and "sync granola" in err
        assert _seq(lb) == seq
    finally:
        other.kill()
        other.wait()


def test_the_writer_holds_the_lock_and_rereads_the_head(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both lines of a let-go are written under one hold of the writer lock."""
    taken: list[int] = []
    real = Logbook.writer

    def counting(self: Logbook, *args: Any, **kwargs: Any) -> Any:
        taken.append(store._held.get(self._lock_path(), 0))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Logbook, "writer", counting)
    sender_fates.write(lb, NEWSLETTER, sender_fates.LET_GO, "too much")
    assert taken[0] == 0 and all(depth >= 1 for depth in taken[1:])  # one outer hold, every append inside


# -- the profile -----------------------------------------------------------------------------------------


def test_the_profile_refuses_a_disposition_that_is_not_a_senders(lb: Logbook) -> None:
    good = sender_fates.payload(("domain", NEWS_DOMAIN), "keep")
    assert entities.validate_status(good) == []
    assert entities.validate_status({**good, "status": "hold"})
    assert entities.validate_status({**good, "status": "let-go"})  # without its reason
    assert entities.validate_status(
        {**good, "entity": {**good["entity"], "id": "sender:phone:+447700900123"}}
    )
    assert entities.validate_status({**good, "entity": {**good["entity"], "id": "news.example.org"}})


def test_an_org_or_idea_reader_never_sees_a_sender_fate(lb: Logbook) -> None:
    """A sender's line is an item's, never an org's: `status list org` and the portfolios read none."""
    assert _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "too much")[0] == 0
    with Logbook(lb.root).index() as idx:
        said = [*idx.retractions(), *idx.by_kind("status")]
    assert entities.statuses(said) == {}
    assert entities.portfolios(said) == {}


# -- the reader, into RFC 0045's rule ------------------------------------------------------------------------


def _reasons(lb: Logbook) -> list[tuple[str, str | None]]:
    report = peoples_mail.read(Logbook(lb.root), "2026-03-01", "2026-03-01")
    return [(c.id, c.reason) for c in report.mails]


def test_a_sender_let_go_is_held_and_one_kept_is_not(lb: Logbook) -> None:
    assert _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "too much")[0] == 0
    assert _cli("hold", "sender", OLA_EMAIL, "--let-go", "--reason", "we no longer write")[0] == 0
    reasons = [reason for _id, reason in _reasons(lb)]
    assert reasons == [None, "let_go", "let_go", "let_go", "no_person"]
    assert _cli("hold", "sender", OLA_EMAIL, "--keep")[0] == 0
    assert [reason for _id, reason in _reasons(lb)] == [None, None, "let_go", "let_go", "no_person"]


def test_a_domain_let_go_holds_an_address_kept_on_it_as_rfc_0045_says(lb: Logbook) -> None:
    """RFC 0045's all-except-junk amendment: a sender let go is held whatever spares it, and a sender Hold
    keeps is one of the spares. So an address kept on a domain let go is still let go; keeping the domain
    lifts it."""
    assert _cli("hold", "sender", "example.org", "--let-go", "--reason", "all of it")[0] == 0
    assert _cli("hold", "sender", KARI_EMAIL, "--keep")[0] == 0
    reasons = [reason for _id, reason in _reasons(lb)]
    assert reasons == ["let_go", "let_go", "no_person", "no_person", "no_person"]
    assert sender_fates.read(Logbook(lb.root)).fate(KARI_EMAIL) == "let-go"
    assert _cli("hold", "sender", "example.org", "--keep")[0] == 0
    assert [reason for _id, reason in _reasons(lb)] == [None, None, "no_person", "no_person", "no_person"]


def test_the_rule_carries_the_kept_senders_for_the_keep_exception(lb: Logbook) -> None:
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    with Logbook(lb.root).index() as idx:
        marks, resolutions = idx.retractions(), idx.resolutions()
        fates = sender_fates.of(Logbook(lb.root), [*marks, *idx.by_kind("status")])
    rule = peoples_mail.Rule.of(Logbook(lb.root), marks, resolutions, let_go=fates.let_go, kept=fates.kept)
    assert rule.kept == frozenset({("domain", NEWS_DOMAIN)})
    assert rule.fate(NEWSLETTER) == "keep" and rule.fate(KARI_EMAIL) is None


def test_people_mail_counts_the_senders_let_go_and_prints_no_address(lb: Logbook) -> None:
    assert _cli("hold", "sender", NEWS_DOMAIN, "--let-go", "--reason", "too much")[0] == 0
    code, out, _err = _cli("people", "mail", "--since", "2026-03-01", "--until", "2026-03-01")
    assert code == 0
    assert "let go in Hold: 2 mails; 1 sender let go in all" in out
    assert "@" not in out and NEWS_DOMAIN not in out
    code, out, _err = _cli("people", "mail", "--since", "2026-03-01", "--until", "2026-03-01", "--json")
    data = json.loads(out)
    assert data["counts"]["by_reason"]["let_go"] == 2
    assert data["fates"] == {"let_go": 1, "kept": 0}
    assert "@" not in out and NEWS_DOMAIN not in out


def test_a_person_let_go_stays_home_from_the_crossing_and_crosses_again_once_kept(
    lb: Logbook, tmp_path: Path
) -> None:
    signing.sign(lb, "2026-03-01", at="2026-03-03T08:00:00Z")
    policy = lb.root / "policy" / "crossing.json"
    policy.parent.mkdir(exist_ok=True)
    policy.write_text(json.dumps({"kari-nordmann": {"max_tier": 2}}), encoding="utf-8")

    def senders(out: Path) -> list[str]:
        assert (
            _cli(
                "export", "crossing", "--to", "kari-nordmann", "--since", "2026-03-01T00:00:00Z",
                "--until", "2026-03-02T00:00:00Z", "--tier", "1,2", "--kinds", "mail", "--out", str(out),
            )[0]
            == 0
        )  # fmt: skip
        text = (out / "entries.jsonl").read_text(encoding="utf-8")
        return [json.loads(s)["payload"]["from"]["email"] for s in text.splitlines() if s.strip()]

    assert senders(tmp_path / "before") == [KARI_EMAIL, OLA_EMAIL]
    assert _cli("hold", "sender", OLA_EMAIL, "--let-go", "--reason", "we no longer write")[0] == 0
    assert senders(tmp_path / "let-go") == [KARI_EMAIL]
    assert _cli("hold", "sender", OLA_EMAIL, "--keep")[0] == 0
    assert senders(tmp_path / "kept") == [KARI_EMAIL, OLA_EMAIL]


def test_the_crossing_rule_reads_the_fates_given(lb: Logbook) -> None:
    with Logbook(lb.root).index() as idx:
        marks, resolutions = idx.retractions(), idx.resolutions()
        lines = idx.by_kind("mail")
    fates = sender_fates.Fates(let_go=frozenset({("email", KARI_EMAIL)}), kept=frozenset())
    kept, held = crossing.peoples_mail_only(Logbook(lb.root), marks, resolutions, lines, fates)
    assert held == 4 and [line["payload"]["from"]["email"] for line in kept] == [OLA_EMAIL]


# -- the fates under all except junk (RFC 0045, amendment of 20 November 2026) --------------------------------

JUNK_RULE = {"categories": ["promotions"]}


def _junk_day(lb: Logbook) -> None:
    """Two promotions on 2 March, the newsletter's and Kari's, and a policy entry with a junk rule."""
    for at, sender in (("2026-03-02T09:00:00Z", NEWSLETTER), ("2026-03-02T10:00:00Z", KARI_EMAIL)):
        line = _mail(at, sender, "This week only")
        line["payload"]["extra"] = {"gmail_category": "promotions"}
        lb.append(**line)
    signing.sign(lb, "2026-03-02", at="2026-03-04T08:00:00Z")
    policy = lb.root / "policy" / "crossing.json"
    policy.parent.mkdir(exist_ok=True)
    policy.write_text(json.dumps({"per-hansen": {"max_tier": 2, "mail_junk": JUNK_RULE}}), encoding="utf-8")


def _crossed(lb: Logbook, out: Path) -> list[str]:
    code, _out, err = _cli(
        "export", "crossing", "--to", "per-hansen", "--since", "2026-03-02T00:00:00Z",
        "--until", "2026-03-03T00:00:00Z", "--tier", "1,2", "--kinds", "mail",
        "--mail", "all-except-junk", "--out", str(out),
    )  # fmt: skip
    assert code == 0, err
    text = (out / "entries.jsonl").read_text(encoding="utf-8")
    return [json.loads(s)["payload"]["from"]["email"] for s in text.splitlines() if s.strip()]


def test_a_kept_sender_crosses_under_all_except_junk_and_one_let_go_is_held(
    lb: Logbook, tmp_path: Path
) -> None:
    _junk_day(lb)
    assert _crossed(lb, tmp_path / "before") == [KARI_EMAIL]  # the newsletter is junk; Kari is a person
    assert _cli("hold", "sender", NEWS_DOMAIN, "--keep")[0] == 0
    assert _crossed(lb, tmp_path / "kept") == [NEWSLETTER, KARI_EMAIL]
    assert _cli("hold", "sender", KARI_EMAIL, "--let-go", "--reason", "we no longer write")[0] == 0
    assert _crossed(lb, tmp_path / "let-go") == [NEWSLETTER]
    manifest = json.loads((tmp_path / "let-go" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["mail_held_by_reason"] == {"let_go": 1, "junk_category": 0, "junk_label": 0}


def test_the_days_verdicts_read_the_standing_fates(lb: Logbook) -> None:
    """The door's reader (`day_verdicts`) holds a sender let go and spares one kept, as the crossing does."""
    _junk_day(lb)
    rules = {"per-hansen": peoples_mail.Junk.of(JUNK_RULE, "test")}

    def reasons() -> list[str | None]:
        return [
            v.reason for v in peoples_mail.day_verdicts(Logbook(lb.root), "2026-03-02", rules)["per-hansen"]
        ]

    assert reasons() == ["junk_category", None]
    assert _cli("hold", "sender", NEWSLETTER, "--keep")[0] == 0
    assert _cli("hold", "sender", KARI_EMAIL, "--let-go", "--reason", "we no longer write")[0] == 0
    assert reasons() == [None, "let_go"]
