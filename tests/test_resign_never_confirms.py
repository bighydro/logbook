"""A re-sign never confirms a line the owner did not confirm (RFC 0034 amendment 4). For any sequence
of first signatures, lines added, retractions (of a line or of the standing signature) and bare
re-signs through any of the four ways (`day sign`, the MCP tool `sign_day`, `day reflect --sign`, the
Day page's "Sign again"), every id a bare re-sign confirms is one of: a line the standing signature
confirmed, still on the page; a line given a disposition in that very call; a line the act itself
wrote (the reflection). And every line the standing signature confirmed that is still on the page is
kept. A day with no standing signature is signed whole, as a first signature is. Synthetic Oslo
persona, who does not exist."""

from __future__ import annotations

import html
import json
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logbook import cli
from logbook.commands import day as day_command
from logbook.contrib import mcp_server, serve
from logbook.core import policy, signing
from logbook.core.store import Logbook, retractions

TZ = "Europe/Oslo"
DAY = "2026-03-03"
FIRST_AT = "2026-03-03T19:00:00+01:00"
AGAIN_AT = "2026-03-04T08:00:00+01:00"
REFLECTION = "Good day on the boat."
WAYS = ("day sign", "sign_day", "day reflect --sign", "Sign again")


def _note(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


def _hidden(form: str) -> dict[str, str]:
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)
    }


def _page(lb: Logbook) -> tuple[list[dict[str, Any]], set[str]]:
    """The page of DAY as `show` lists it, and the ids retracted (any line, signatures too)."""
    with lb.index() as idx:
        lines = signing.page(idx, DAY)
        retracted = set(retractions(idx.retractions()))
    return [line for line in lines if str(line["id"]) not in retracted], retracted


def _standing(lb: Logbook) -> dict[str, Any] | None:
    with lb.index() as idx:
        return signing.signature_of(idx, DAY, str(lb.meta["owner_id"]))


def _sign_bare(lb: Logbook, way: str, disposed: str | None, capsys: pytest.CaptureFixture[str]) -> None:
    """DAY signed again the `way` named with no `--confirm`; `disposed`, when given, is a seq or id
    typed under `--kept` (the two command ways only)."""
    if way == "day sign":
        extra = [] if disposed is None else ["--kept", disposed]
        cli.main(["day", "sign", DAY, "--at", AGAIN_AT, *extra])
    elif way == "sign_day":
        given = {} if disposed is None else {"kept": [disposed]}
        mcp_server.call(lb.root, "sign_day", {"day": DAY, "at": AGAIN_AT, **given})
    elif way == "day reflect --sign":
        cli.main(["day", "reflect", DAY, "--text", REFLECTION, "--sign"])
    else:
        site = serve.Site(lb)
        assert site.write(
            f"/day/{DAY}/reflect", {"text": REFLECTION, "act": "reflect"}, "127.0.0.1", None, None
        )
        page = site.respond(f"/day/{DAY}", "").body.decode("utf-8")
        found = re.search(r'<form class="sign"[^>]*>.*?</form>', page, re.S)
        assert found is not None
        form = {k: v for k, v in _hidden(found.group(0)).items() if k != "act"}
        response = site.write(f"/day/{DAY}/sign", {**form, "act": "sign"}, "127.0.0.1", None, None)
        assert response.status == 303, response.body[:300]
    capsys.readouterr()


# a step: a first signature (confirming these seqs of the four, nothing, or the page), a line added,
# a bare re-sign one way with maybe a disposition on one of the first four lines (by seq or id), or
# a retraction (of one of the first four lines, or of the standing signature)
_STEP = st.one_of(
    st.tuples(
        st.just("first"), st.one_of(st.none(), st.just("none"), st.sets(st.integers(1, 4), min_size=1))
    ),
    st.tuples(st.just("add"), st.just(None)),
    st.tuples(
        st.just("resign"),
        st.tuples(st.sampled_from(WAYS), st.one_of(st.none(), st.integers(1, 4)), st.booleans()),
    ),
    st.tuples(st.just("retract"), st.one_of(st.integers(1, 4), st.just("signature"))),
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(steps=st.lists(_STEP, min_size=1, max_size=7))
def test_a_bare_re_sign_confirms_only_what_the_owner_confirmed(
    steps: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lb = Logbook.init(Path(tmp) / "lb", TZ)
        monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
        monkeypatch.setattr(day_command, "_on_a_tty", lambda: False)
        monkeypatch.setattr(mcp_server, "_today", lambda _lb: "2026-03-04")
        monkeypatch.setattr(policy, "today", lambda: date(2026, 3, 4))
        lb.append_many([_note(f"2026-03-03T0{h}:00:00Z", f"line {h}") for h in range(6, 10)])  # seqs 1-4
        path = policy.policy_path(lb.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcp": {"max_tier": 1, "write": ["sign_day"]}}), encoding="utf-8")
        added = 0
        for kind, arg in steps:
            if kind == "first":
                page, _ = _page(lb)
                if arg is None:
                    extra = []
                elif arg == "none":
                    extra = ["--confirm", "none"]
                else:
                    seqs = {int(line["seq"]) for line in page}
                    wanted = sorted(s for s in arg if s in seqs)
                    if not wanted:
                        continue  # every seq named is retracted: refused, by design
                    extra = ["--confirm", ",".join(str(s) for s in wanted)]
                cli.main(["day", "sign", DAY, "--at", FIRST_AT, *extra])
                capsys.readouterr()
            elif kind == "add":
                added += 1
                lb.append(**_note("2026-03-03T12:00:00Z", f"not read {added}"))
            elif kind == "retract":
                if arg == "signature":
                    standing = _standing(lb)
                    if standing is None:
                        continue
                    lb.retract(int(standing["seq"]), "signed the wrong day")
                else:
                    _, retracted = _page(lb)
                    rows = {int(line["seq"]): line for line in lb.lines()}
                    if str(rows[arg]["id"]) in retracted:
                        continue
                    lb.retract(arg, "the wrong harbour")
            else:
                way, seq, by_id = arg
                page_before, retracted = _page(lb)
                standing = _standing(lb)
                on_page = {str(line["id"]) for line in page_before}
                by_seq = {int(line["seq"]): str(line["id"]) for line in lb.lines()}
                disposed = None
                if seq is not None and way in ("day sign", "sign_day") and by_seq[seq] in on_page:
                    disposed = by_seq[seq] if by_id else str(seq)
                # `day reflect --sign` and the page's Sign sign *with* the reflection standing on the
                # day (`reflect.close`: `joined`), confirmed even when the standing signature left it out
                reflection = (
                    {
                        str(line["id"])
                        for line in page_before
                        if line["kind"] == "note" and line["payload"].get("text") == REFLECTION
                    }
                    if way in ("day reflect --sign", "Sign again")
                    else set()
                )
                head = int(lb.meta["seq"])
                _sign_bare(lb, way, disposed, capsys)
                lines = {int(line["seq"]): line for line in lb.lines()}
                signature = lines[int(lb.meta["seq"])]
                assert signature["kind"] == "signed-day"
                confirmed = set(signature["payload"]["confirmed"])
                written = {str(lines[s]["id"]) for s in range(head + 1, int(lb.meta["seq"]))}  # the act's own
                page_after, _ = _page(lb)
                assert confirmed <= {str(line["id"]) for line in page_after}
                if standing is None:
                    assert confirmed == {str(line["id"]) for line in page_after}, (
                        "a first signature: the page"
                    )
                    continue
                assert signature["payload"]["supersedes"] == standing["id"]
                kept = {str(i) for i in standing["payload"]["confirmed"]} & on_page
                allowed = kept | written | reflection | ({by_seq[seq]} if disposed is not None else set())
                assert confirmed <= allowed, f"confirmed silently: {confirmed - allowed}"
                assert kept <= confirmed, f"a confirmation lost: {kept - confirmed}"
        assert lb.verify()[2] == []
