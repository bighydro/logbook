"""The agreed body shape of `logbook export notion`, checked where the fixture of
`test_export_notion.py` does not reach: an org bound to a host rather than its registered domain, a
status line whose `since` lies before the window, and the status history as `logbook status` really
writes it (every line superseding the last). The record is synthetic: Ines Nordmann of Oslo, who does
not exist, her yard and her fjord kiosk."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from test_export_notion import (
    KIOSK,
    KIOSK_PAGE,
    NOW,
    OLA,
    OWNER,
    TZ,
    YARD,
    YARD_DOMAIN,
    _entity,
    _entry,
    _line,
    _mail,
    _status,
    build,
)

from logbook.contrib import entity_status, notion_export
from logbook.core import policy, signing
from logbook.core.store import Logbook

SIGNED_AT = "2026-10-12T08:00:00Z"


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_export, "now", lambda: NOW)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 10, 15))


def _record(tmp_path: Path) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    lb.set_owner_emails([OWNER["email"]])
    return lb


def _built(lb: Logbook, since: str = "2026-09-01") -> notion_export.Built:
    _entry(lb)
    return notion_export.build(lb, notion_export.request(lb, since))


# -- orgs: by domain ------------------------------------------------------------------------------------


def test_an_org_bound_to_a_host_is_keyed_by_its_registered_domain(tmp_path: Path):
    """The record keys an org by the registered domain of its `domain` ref (`entities.key_of`), and a
    mail touches it through the registered domain of its address. An org whose ref is a host under
    that domain has a key, so it is either matched by it or counted; it never vanishes."""
    lb = _record(tmp_path)
    host = f"post.{YARD_DOMAIN}"
    lb.append_many(
        [
            _entity("org", YARD, "Nordmann Verft AS", [("domain", host)]),
            _mail("2026-09-02", {"name": "Nordmann Verft", "email": f"post@{host}"}, "Invoice"),
            _mail("2026-09-03", OLA, "Hull drawings"),  # ola@nordmann-verft.example.org
        ]
    )
    for day in ("2026-09-02", "2026-09-03"):
        signing.sign(lb, day, at=SIGNED_AT)
    built = _built(lb)
    assert built.left_out["orgs_without_domain"] == 0, "the yard has a domain"
    assert [o["domain"] for o in built.orgs] == [YARD_DOMAIN], "keyed as the record keys it"
    assert built.orgs[0]["touched"] == ["2026-09-02", "2026-09-03"], "both mails reach it"


# -- ideas: an entry per status line in the window ------------------------------------------------------


def test_a_status_line_written_in_the_window_gets_an_entry_whatever_its_since(tmp_path: Path):
    """RFC 0037 §10.2: `since` is the day the status took effect when it is not the line's own day (an
    idea built in June, entered in October). The line is in the window, so the writer gets its entry,
    dated by `since`."""
    lb = build(tmp_path / "lb")
    line = lb.append(
        **_line(_status(("idea", KIOSK), "the fjord kiosk", "built", "2026-10-10", 2, since="2026-06-01"))
    )
    signing.sign(lb, "2026-10-10", at=SIGNED_AT)
    built = _built(lb)
    [kiosk] = built.ideas
    assert kiosk["status"] == {"status": "built", "since": "2026-06-01", "line": line["id"]}
    assert line["id"] in [e["id"] for e in kiosk["entries"]], "a status line in the window has an entry"


def test_every_status_line_in_the_window_gets_an_entry_superseded_or_not(tmp_path: Path):
    """`logbook status` writes every line with `supersedes` naming the standing one, so only the current
    line stands (`entities.statuses`). The history the writer appends is one entry per status line in
    the window, the owner's reason quoted on each, not the current line alone."""
    lb = _record(tmp_path)
    lb.append_many([_entity("idea", KIOSK, "the fjord kiosk", [("page", KIOSK_PAGE)])])
    first = entity_status.write(
        lb, "idea", "the fjord kiosk", "exploring", reason="talked it through with Ola", at="2026-09-05",
        today="2026-10-15",
    )  # fmt: skip
    second = entity_status.write(
        lb,
        "idea",
        "the fjord kiosk",
        "build",
        reason="first stand ordered",
        at="2026-09-20",
        today="2026-10-15",
    )
    assert second.status["payload"]["supersedes"] == first.status["id"], "as the writer always does"
    for day in ("2026-09-05", "2026-09-20"):
        signing.sign(lb, day, at=SIGNED_AT)
    built = _built(lb)
    [kiosk] = built.ideas
    assert kiosk["status"]["status"] == "build" and kiosk["reason"]["text"] == "first stand ordered"
    assert [e["date"] for e in kiosk["entries"]] == ["2026-09-05", "2026-09-20"]
    assert "„talked it through with Ola“" in kiosk["entries"][0]["text"], "the earlier reason, quoted"
