"""`logbook sync beeper`: every chat Beeper Desktop bridges, read from its local API, read-only.

Everything here is synthetic: a fake Beeper Desktop on 127.0.0.1 serving the persona's three networks
(WhatsApp, Signal, iMessage), two chats each, nobody in them real. The fake records every request's
method and path, so a test can assert the client only ever issues GET. No test reaches a real Beeper.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from logbook import cli
from logbook.contrib import adapters, doctor
from logbook.contrib.adapters import beeper_live
from logbook.core.store import Logbook

TOKEN_ENV = "LOGBOOK_BEEPER_TOKEN"
URL_ENV = "LOGBOOK_BEEPER_URL"
REMOTE_ENV = "LOGBOOK_BEEPER_ALLOW_REMOTE"
TOKEN = "synthetic-token-not-a-real-one"
PAGE = 2  # messages per page the fake serves: a chat of five messages is three pages

# -- the persona: Ines Nordmann of Oslo, who does not exist ---------------------------------------

ME_WA, ME_SIGNAL, ME_IMESSAGE = (
    "@whatsapp_447700900000:beeper.local",
    "@signal_ines:beeper.local",
    "@ines:imessage",
)
OLA, PER, NILS, KARI = (
    "@whatsapp_447700900123:beeper.local",
    "@signal_per:beeper.local",
    "@imessage_nils:beeper.local",
    "@whatsapp_447700900124:beeper.local",
)
ACCOUNTS = [
    {
        "accountID": "local-whatsapp",
        "network": "WhatsApp",
        "status": "connected",
        "user": {"id": ME_WA, "fullName": "Ines", "isSelf": True},
    },
    {
        "accountID": "local-signal",
        "network": "Signal",
        "status": "connected",
        "user": {"id": ME_SIGNAL, "fullName": "Ines", "isSelf": True},
    },
    {
        "accountID": "local-imessage",
        "network": "iMessage",
        "status": "connected",
        "user": {"id": ME_IMESSAGE, "fullName": "Ines", "isSelf": True},
    },
]
T0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)


def _t(minutes: int) -> str:
    """A timestamp as Beeper spells one: RFC3339 with milliseconds."""
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _at(minutes: int) -> str:
    """The same instant as the record spells it."""
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _user(user_id: str, name: str, **more: Any) -> dict[str, Any]:
    return {"id": user_id, "fullName": name, **more}


def _chat(
    chat_id: str, account: str, network: str, kind: str, title: str, *people: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": chat_id,
        "accountID": account,
        "network": network,
        "type": kind,
        "title": title,
        "unreadCount": 0,
        "participants": {"items": list(people), "hasMore": False, "total": len(people)},
        "lastActivity": _t(60),
    }


def _message(
    chat: str, account: str, msg_id: str, sender: str, minutes: int, text: str | None = None, **more: Any
) -> dict[str, Any]:
    m: dict[str, Any] = {
        "id": msg_id,
        "accountID": account,
        "chatID": chat,
        "senderID": sender,
        "sortKey": f"{minutes:06d}-{msg_id}",
        "timestamp": _t(minutes),
    }
    if text is not None:
        m["text"] = text
        m["type"] = "TEXT"
    m.update(more)
    return m


WA_OLA, WA_CREW = "!wa-ola:beeper.local", "!wa-crew:beeper.local"
SIG_PER, SIG_NIGHT = "!sig-per:beeper.local", "!sig-night:beeper.local"
IM_NILS, IM_FAMILY = "!im-nils:beeper.local", "!im-family:beeper.local"
CHATS = [
    _chat(
        WA_OLA,
        "local-whatsapp",
        "WhatsApp",
        "single",
        "Ola Nordmann",
        _user(ME_WA, "Ines", isSelf=True, phoneNumber="+447700900000"),
        _user(OLA, "Ola Nordmann", phoneNumber="+447700900123"),
    ),
    _chat(
        WA_CREW,
        "local-whatsapp",
        "WhatsApp",
        "group",
        "Sailing crew",
        _user(ME_WA, "Ines", isSelf=True),
        _user(OLA, "Ola Nordmann", phoneNumber="+447700900123"),
        _user(KARI, "Kari", phoneNumber="+447700900124"),
    ),
    _chat(
        SIG_PER,
        "local-signal",
        "Signal",
        "single",
        "Per",
        _user(ME_SIGNAL, "Ines", isSelf=True),
        _user(PER, "Per", username="per.example"),
    ),
    _chat(
        SIG_NIGHT,
        "local-signal",
        "Signal",
        "group",
        "Night watch",
        _user(ME_SIGNAL, "Ines", isSelf=True),
        _user(PER, "Per"),
    ),
    _chat(
        IM_NILS,
        "local-imessage",
        "iMessage",
        "single",
        "Nils",
        _user(ME_IMESSAGE, "Ines", isSelf=True),
        _user(NILS, "Nils", email="nils@example.org"),
    ),
    _chat(
        IM_FAMILY,
        "local-imessage",
        "iMessage",
        "group",
        "Family",
        _user(ME_IMESSAGE, "Ines", isSelf=True),
        _user(NILS, "Nils", email="nils@example.org"),
    ),
]
ASSET = "mxc://beeper.local/synthetic-asset-1"
MESSAGES: dict[str, list[dict[str, Any]]] = {
    WA_OLA: [  # five messages: three pages of two
        _message(WA_OLA, "local-whatsapp", "$wa1", OLA, 0, "mooring lines are on the pontoon"),
        _message(WA_OLA, "local-whatsapp", "$wa2", ME_WA, 5, "thanks, on my way", isSender=True),
        _message(WA_OLA, "local-whatsapp", "$wa3", OLA, 10, "see you there", linkedMessageID="$wa2"),
        _message(
            WA_OLA,
            "local-whatsapp",
            "$wa4",
            OLA,
            15,
            type="IMAGE",
            attachments=[
                {
                    "type": "img",
                    "id": ASSET,
                    "fileName": "pontoon.jpg",
                    "fileSize": 123456,
                    "mimeType": "image/jpeg",
                    "srcURL": "file:///never/opened/pontoon.jpg",
                    "size": {"width": 1200, "height": 800},
                }
            ],
        ),
        _message(
            WA_OLA,
            "local-whatsapp",
            "$wa5",
            ME_WA,
            20,
            type="REACTION",
            isSender=True,
            reactions=[{"id": "r1", "participantID": ME_WA, "reactionKey": "👍"}],
        ),
    ],
    WA_CREW: [
        _message(WA_CREW, "local-whatsapp", "$crew1", KARI, 30, "who has the winch handle?"),
        _message(WA_CREW, "local-whatsapp", "$crew2", OLA, 31, "me"),
        _message(WA_CREW, "local-whatsapp", "$crew3", ME_WA, 32),  # a system event: no text, no attachment
    ],
    SIG_PER: [
        _message(SIG_PER, "local-signal", "$sig1", PER, 40, "ferry at nine?"),
        _message(SIG_PER, "local-signal", "$sig2", ME_SIGNAL, 41, "nine it is", isSender=True),
    ],
    SIG_NIGHT: [
        _message(SIG_NIGHT, "local-signal", "$night1", PER, 50, "I take the first watch"),
        _message(SIG_NIGHT, "local-signal", "$night2", PER, 51, "bad date", timestamp="not a date"),
    ],
    IM_NILS: [
        _message(IM_NILS, "local-imessage", "$im1", NILS, 55, "lunch sunday?"),
    ],
    IM_FAMILY: [
        _message(IM_FAMILY, "local-imessage", "$fam1", ME_IMESSAGE, 56, "yes", isSender=True),
        _message(IM_FAMILY, "local-imessage", "$fam2", NILS, 57, "deleted", isDeleted=True),
    ],
}
DEFAULT_LINES = 9  # whatsapp 4 + 2, signal 2 + 1; imessage left to `sync imessage`
IMESSAGE_LINES = 3
ALL_LINES = DEFAULT_LINES + IMESSAGE_LINES
NEWEST_DEFAULT = _at(50)
NEWEST_ALL = _at(57)


class FakeBeeper:
    """Beeper Desktop's API as `sync beeper` sees it, on 127.0.0.1: `GET /v1/info`, `GET
    /v1/accounts`, `GET /v1/chats?accountIDs=…&limit=…` and `GET /v1/chats/{id}/messages`, the last
    two paged newest first by `cursor` and `direction=before` with `hasMore` and `oldestCursor`, as
    the public API does. Every request's method and path is recorded; anything but a GET is answered
    405 and never acted on."""

    def __init__(self) -> None:
        self.accounts = [dict(a) for a in ACCOUNTS]
        self.chats = [json.loads(json.dumps(c)) for c in CHATS]
        self.messages = {k: [dict(m) for m in v] for k, v in MESSAGES.items()}
        self.requests: list[tuple[str, str]] = []
        self.authorized: list[bool] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, doc: Any) -> None:
                body = json.dumps(doc).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                fake.requests.append(("GET", self.path))
                fake.authorized.append(self.headers.get("Authorization") == f"Bearer {TOKEN}")
                if not fake.authorized[-1]:
                    self._send(401, {"error": "unauthorized"})
                    return
                status, doc = fake.answer(self.path)
                self._send(status, doc)

            def _refuse(self) -> None:
                fake.requests.append((self.command, self.path))
                self._send(405, {"error": "method not allowed"})

            do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def answer(self, raw: str) -> tuple[int, Any]:
        url = urlsplit(raw)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        parts = [unquote(p) for p in url.path.split("/") if p]
        if parts == ["v1", "info"]:
            return 200, {
                "app": {"bundle_id": "com.example.beeper", "name": "Beeper Desktop", "version": "4.2.0"},
                "server": {
                    "base_url": self.url,
                    "hostname": "localhost",
                    "port": 23373,
                    "remote_access": False,
                    "status": "running",
                    "mcp_enabled": False,
                },
                "platform": {"os": "darwin", "arch": "arm64"},
                "endpoints": {
                    "spec": "/v1/openapi.json",
                    "mcp": "/v1/mcp",
                    "ws_events": "/v1/events",
                    "oauth": {},
                },
            }
        if parts == ["v1", "accounts"]:
            return 200, self.accounts
        if parts == ["v1", "chats"]:
            wanted = query.get("accountIDs")
            rows = [c for c in self.chats if wanted is None or c["accountID"] == wanted]
            rows.sort(key=lambda c: c["lastActivity"], reverse=True)
            return 200, self._page(rows, query, int(query.get("limit") or 25), key="id")
        if len(parts) == 4 and parts[:2] == ["v1", "chats"] and parts[3] == "messages":
            rows = sorted(self.messages.get(parts[2], []), key=lambda m: m["sortKey"], reverse=True)
            return 200, self._page(rows, query, PAGE, key="sortKey")
        return 404, {"error": "no such route"}

    @staticmethod
    def _page(rows: list[dict[str, Any]], query: dict[str, str], size: int, key: str) -> dict[str, Any]:
        """Newest first; `cursor` names the last item served and `direction=before` continues past it."""
        cursor = query.get("cursor")
        if cursor is not None:
            assert query.get("direction", "before") == "before"
            keys = [r[key] for r in rows]
            rows = rows[keys.index(cursor) + 1 :]
        items = rows[:size]
        more = len(rows) > size
        return {
            "items": items,
            "hasMore": more,
            "oldestCursor": items[-1][key] if items else None,
            "newestCursor": items[0][key] if items else None,
        }

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def methods(self) -> set[str]:
        return {method for method, _path in self.requests}

    def message_requests(self, chat_id: str) -> list[str]:
        return [path for _m, path in self.requests if f"/v1/chats/{chat_id}/messages" in unquote(path)]

    def add_message(self, chat_id: str, msg_id: str, sender: str, minutes: int, text: str) -> None:
        account = next(c["accountID"] for c in self.chats if c["id"] == chat_id)
        self.messages[chat_id].append(_message(chat_id, account, msg_id, sender, minutes, text))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    server = FakeBeeper()
    server.start()
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv(URL_ENV, server.url)
    monkeypatch.delenv(REMOTE_ENV, raising=False)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    return lb


def _sync(*args: str) -> int:
    try:
        cli.main(["sync", "beeper", *args])
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def _state(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "beeper.json").read_text(encoding="utf-8"))
    return data


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and configuration ---------------------------------------------------------------


def test_registry_has_beeper_as_a_file_and_as_a_live_adapter() -> None:
    assert adapters.live("beeper") is beeper_live
    assert adapters.named("beeper") is not None and adapters.named("beeper") is not beeper_live
    assert beeper_live.NAME == "beeper" and beeper_live.KIND == "message"


def test_configure_needs_the_token_and_defaults_to_localhost() -> None:
    assert beeper_live.configure({}) is None
    assert beeper_live.configure({URL_ENV: "http://localhost:23373"}) is None
    config = beeper_live.configure({TOKEN_ENV: TOKEN})
    assert config is not None
    assert config.url == "http://localhost:23373" and config.token == TOKEN


@pytest.mark.parametrize("url", ["http://localhost:23373/", "http://127.0.0.1:9999", "http://[::1]:23373"])
def test_configure_takes_this_machines_addresses(url: str) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: url})
    assert config is not None and config.url == url.rstrip("/")


def test_configure_refuses_a_remote_url_on_one_line_unless_told_otherwise() -> None:
    with pytest.raises(ValueError, match=REMOTE_ENV) as e:
        beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: "http://beeper.example.org:23373"})
    assert "\n" not in str(e.value) and "beeper.example.org" in str(e.value)
    config = beeper_live.configure(
        {TOKEN_ENV: TOKEN, URL_ENV: "http://beeper.example.org:23373", REMOTE_ENV: "1"}
    )
    assert config is not None and config.url == "http://beeper.example.org:23373"


@pytest.mark.parametrize("url", ["beeper.example.org", "ftp://localhost:1", "http://"])
def test_configure_refuses_an_address_that_is_not_an_http_url(url: str) -> None:
    with pytest.raises(ValueError, match=URL_ENV):
        beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: url})


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("WhatsApp", "whatsapp"),
        ("Facebook Messenger", "facebook-messenger"),
        ("iMessage", "imessage"),
        ("", "unknown"),
    ],
)
def test_network_names_are_lower_case_slugs(raw: str, name: str) -> None:
    assert beeper_live.network_name(raw) == name


def test_networks_flag_is_parsed_as_slugs() -> None:
    assert beeper_live.networks("WhatsApp, signal,,Telegram") == ("whatsapp", "signal", "telegram")
    with pytest.raises(ValueError, match="--networks"):
        beeper_live.networks(" , ")


def test_watermark_is_the_messages_own_time_and_the_group_its_network() -> None:
    draft = {"at": "2026-03-01T10:00:00Z", "payload": {"extra": {"network": "signal"}}}
    assert beeper_live.watermark(draft) == "2026-03-01T10:00:00Z"
    assert beeper_live.group(draft) == "signal"


# -- pull: the walk ---------------------------------------------------------------------------


def test_pull_maps_every_message_of_every_network_but_imessage_by_default(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    counts: dict[str, int] = {}
    lines = list(beeper_live.pull(config, counts=counts))
    assert len(lines) == DEFAULT_LINES
    assert {line["source"] for line in lines} == {"beeper-whatsapp", "beeper-signal"}
    assert all(line["kind"] == "message" and line["tier"] == 2 for line in lines)
    by_id = _by_raw_id(lines)
    received = by_id[f"local-whatsapp/{WA_OLA}/$wa1"]
    assert received["at"] == _at(0)
    assert received["payload"]["from_me"] is False
    assert received["payload"]["sender"] == {
        "kind": "phone",
        "value": "+447700900123",
        "name": "Ola Nordmann",
    }
    assert received["payload"]["chat"] == {"id": WA_OLA, "type": "direct", "name": "Ola Nordmann"}
    assert received["payload"]["text"] == "mooring lines are on the pontoon"
    assert received["payload"]["extra"]["network"] == "whatsapp"
    sent = by_id[f"local-whatsapp/{WA_OLA}/$wa2"]
    assert sent["payload"]["from_me"] is True and "sender" not in sent["payload"]
    reply = by_id[f"local-whatsapp/{WA_OLA}/$wa3"]
    assert reply["payload"]["reply_to"] == f"local-whatsapp/{WA_OLA}/$wa2"
    group = by_id[f"local-whatsapp/{WA_CREW}/$crew1"]
    assert group["payload"]["chat"] == {"id": WA_CREW, "type": "group", "name": "Sailing crew"}
    assert group["payload"]["sender"] == {"kind": "phone", "value": "+447700900124", "name": "Kari"}
    handle = by_id[f"local-signal/{SIG_PER}/$sig1"]
    assert handle["payload"]["sender"] == {"kind": "handle", "value": PER, "name": "Per"}
    assert counts["direct_chat"] == 6 and counts["group_chat"] == 3
    assert counts["skipped_reaction"] == 1 and counts["skipped_system_event"] == 1
    assert counts["skipped_bad_date"] == 1 and counts["media_referenced"] == 1


def test_pull_yields_each_chat_oldest_first(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    lines = [line for line in beeper_live.pull(config) if line["payload"]["chat"]["id"] == WA_OLA]
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    assert [line["payload"]["raw_id"].rpartition("/")[2] for line in lines] == [
        "$wa1",
        "$wa2",
        "$wa3",
        "$wa4",
    ]


def test_pull_pages_a_chat_newest_first_until_the_last_page(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    list(beeper_live.pull(config))
    pages = fake.message_requests(WA_OLA)
    assert len(pages) == 3, "five messages, two a page"
    assert "cursor" not in pages[0]
    assert all("direction=before" in page and "cursor=" in page for page in pages[1:])


def test_pull_references_an_attachment_by_asset_id_and_fetches_nothing(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    line = _by_raw_id(list(beeper_live.pull(config)))[f"local-whatsapp/{WA_OLA}/$wa4"]
    assert line["payload"]["media_kind"] == "image" and "text" not in line["payload"]
    assert line["payload"]["extra"]["media"] == {
        "asset_id": ASSET,
        "bytes": 123456,
        "media_type": "image/jpeg",
        "filename": "pontoon.jpg",
    }
    assert "srcURL" not in json.dumps(line)
    assert not [path for _m, path in fake.requests if "asset" in path], "the bytes stay in Beeper"


@pytest.mark.parametrize(
    ("attachment", "kind"),
    [
        ({"type": "audio", "isVoiceNote": True}, "voice"),
        ({"type": "audio"}, "audio"),
        ({"type": "video"}, "video"),
        ({"type": "img", "isGif": True}, "gif"),
        ({"type": "img", "isSticker": True}, "sticker"),
        ({"type": "unknown", "mimeType": "application/pdf"}, "document"),
        ({"type": "unknown"}, "other"),
    ],
)
def test_media_kind_follows_the_attachments_flags(attachment: dict[str, Any], kind: str) -> None:
    assert beeper_live.media_kind(attachment, None) == kind
    assert beeper_live.media_kind({"type": "unknown"}, "LOCATION") == "location"


def test_pull_only_ever_issues_get_requests(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    list(beeper_live.pull(config, networks=("whatsapp", "signal", "imessage")))
    assert fake.requests and fake.methods() == {"GET"}
    assert all(fake.authorized), "every request carried the bearer token"
    paths = {unquote(path).split("?")[0] for _m, path in fake.requests}
    assert paths <= {"/v1/accounts", "/v1/chats"} | {f"/v1/chats/{c['id']}/messages" for c in CHATS}


def test_pull_networks_chooses_which_accounts_are_read(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    lines = list(beeper_live.pull(config, networks=("imessage",)))
    assert len(lines) == IMESSAGE_LINES and {line["source"] for line in lines} == {"beeper-imessage"}
    assert _by_raw_id(lines)[f"local-imessage/{IM_NILS}/$im1"]["payload"]["sender"] == {
        "kind": "email",
        "value": "nils@example.org",
        "name": "Nils",
    }
    deleted = _by_raw_id(lines)[f"local-imessage/{IM_FAMILY}/$fam2"]
    assert deleted["payload"]["extra"]["deleted"] is True
    assert not fake.message_requests(WA_OLA) and not fake.message_requests(SIG_PER)


def test_pull_honours_since(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    lines = list(beeper_live.pull(config, since=_at(31)))
    assert sorted(line["at"] for line in lines) == [_at(31), _at(40), _at(41), _at(50)]
    assert len(fake.message_requests(WA_OLA)) == 1, "the first page was already older than since"


def test_pull_reads_each_chat_from_its_own_mark_less_the_lookback(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    marks: dict[str, str] = {}
    list(beeper_live.pull(config, marks=marks))
    assert marks == {
        f"local-whatsapp/{WA_OLA}": _at(15),
        f"local-whatsapp/{WA_CREW}": _at(31),
        f"local-signal/{SIG_PER}": _at(41),
        f"local-signal/{SIG_NIGHT}": _at(50),
    }
    fake.requests.clear()
    fake.add_message(SIG_PER, "$sig3", PER, 60 * 30, "a day later")
    marks[f"local-whatsapp/{WA_OLA}"] = _at(60 * 48)  # as if that chat had been read two days on
    lines = list(beeper_live.pull(config, marks=marks))
    assert {line["payload"]["raw_id"].rpartition("/")[2] for line in lines} >= {"$sig3", "$crew1", "$sig1"}
    assert not any(line["payload"]["chat"]["id"] == WA_OLA for line in lines), "nothing in its lookback"
    assert marks[f"local-signal/{SIG_PER}"] == _at(60 * 30)
    assert marks[f"local-whatsapp/{WA_OLA}"] == _at(60 * 48), "a mark never moves backwards"


def test_pull_on_a_closed_port_is_one_sentence(fake: FakeBeeper) -> None:
    fake.stop()
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    with pytest.raises(OSError, match="is Beeper Desktop running") as e:
        list(beeper_live.pull(config))
    assert "\n" not in str(e.value) and "Traceback" not in str(e.value)
    fake.thread = threading.Thread(target=lambda: None)  # the fixture's stop finds nothing to do


def test_pull_with_a_refused_token_says_so_and_never_the_token(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: "another-synthetic-token", URL_ENV: fake.url})
    assert config is not None
    with pytest.raises(OSError, match="refused the token") as e:
        list(beeper_live.pull(config))
    assert "another-synthetic-token" not in str(e.value)


def test_info_asks_one_get_and_names_the_app(fake: FakeBeeper) -> None:
    config = beeper_live.configure({TOKEN_ENV: TOKEN, URL_ENV: fake.url})
    assert config is not None
    assert beeper_live.check(config) == "the API answers: Beeper Desktop 4.2.0, remote access off"
    assert fake.requests == [("GET", "/v1/info")]


# -- sync: the CLI ----------------------------------------------------------------------------


def test_sync_first_run_writes_every_line_and_the_second_none(
    lb: Logbook, fake: FakeBeeper, capsys: Any
) -> None:
    assert _sync() == 0
    out = capsys.readouterr().out
    assert f"beeper: {DEFAULT_LINES} new lines of {DEFAULT_LINES} seen from the beginning" in out
    assert "whatsapp: 6 new of 6 seen" in out and "signal: 3 new of 3 seen" in out
    assert "skipped 1 reactions, 1 group system events, 1 with an unusable date" in out
    assert "1 with media referenced by Beeper asset id, not fetched" in out
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == DEFAULT_LINES
    state = _state(lb)
    assert state["since"] == NEWEST_DEFAULT
    assert set(state["marks"]) == {
        f"local-whatsapp/{WA_OLA}",
        f"local-whatsapp/{WA_CREW}",
        f"local-signal/{SIG_PER}",
        f"local-signal/{SIG_NIGHT}",
    }
    assert state["groups"] == {"signal": _at(50), "whatsapp": _at(31)}
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "beeper: 0 new lines of" in out and "already in the record" in out
    assert lb.meta["seq"] == DEFAULT_LINES and _state(lb)["since"] == NEWEST_DEFAULT
    assert fake.methods() == {"GET"}


def test_sync_second_run_picks_up_one_new_message_in_one_chat(
    lb: Logbook, fake: FakeBeeper, capsys: Any
) -> None:
    _sync()
    fake.add_message(WA_CREW, "$crew4", KARI, 60 * 30, "found it")
    fake.requests.clear()
    assert _sync() == 0
    out = capsys.readouterr().out
    assert "beeper: 1 new lines of" in out
    state = _state(lb)
    assert state["since"] == _at(60 * 30)
    assert state["marks"][f"local-whatsapp/{WA_CREW}"] == _at(60 * 30)
    assert state["marks"][f"local-whatsapp/{WA_OLA}"] == _at(15), "the other chats' marks stand"
    assert lb.meta["seq"] == DEFAULT_LINES + 1


def test_sync_networks_flag_filters_and_imessage_is_left_to_the_local_source(
    lb: Logbook, fake: FakeBeeper, capsys: Any
) -> None:
    assert _sync("--networks", "imessage") == 0
    assert f"beeper: {IMESSAGE_LINES} new lines of {IMESSAGE_LINES} seen" in capsys.readouterr().out
    assert {line["source"] for line in lb.lines()} == {"beeper-imessage"}
    assert _sync("--networks", "whatsapp,signal") == 0
    assert "beeper: 0 new lines of 0 seen since" in capsys.readouterr().out, (
        "a chat with no mark yet starts at the source's watermark: a network added later needs --since once"
    )
    assert _sync("--networks", "whatsapp,signal,imessage", "--since", _at(0)) == 0
    assert lb.meta["seq"] == ALL_LINES
    assert _sync("--networks", "telegram") == 0
    assert "beeper: 0 new lines of 0 seen" in capsys.readouterr().out


def test_sync_networks_is_refused_on_one_line_for_a_bad_value_and_for_another_source(
    lb: Logbook, fake: FakeBeeper, capsys: Any
) -> None:
    assert _sync("--networks", " , ") == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "--networks" in err
    try:
        cli.main(["sync", "dawarich", "--networks", "whatsapp"])
    except SystemExit as e:
        assert e.code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "--networks is for" in err and "beeper" in err


def test_sync_since_is_used_as_given_for_every_chat(lb: Logbook, fake: FakeBeeper, capsys: Any) -> None:
    _sync()
    assert _sync("--since", _at(40)) == 0
    assert "beeper: 0 new lines of 3 seen since" in capsys.readouterr().out
    assert _state(lb)["since"] == NEWEST_DEFAULT


def test_sync_dry_run_writes_nothing(lb: Logbook, fake: FakeBeeper, capsys: Any) -> None:
    assert _sync("--dry-run") == 0
    out = capsys.readouterr().out
    assert f"beeper: {DEFAULT_LINES} lines from the beginning (dry run, nothing written)" in out
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()
    assert fake.methods() == {"GET"}


def test_sync_refuses_a_remote_url_without_the_override(
    lb: Logbook, fake: FakeBeeper, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv(URL_ENV, "http://beeper.example.org:23373")
    assert _sync() == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: beeper:") and REMOTE_ENV in err
    assert not fake.requests and lb.meta["seq"] == 0


def test_sync_without_the_token_says_which_variable(
    lb: Logbook, fake: FakeBeeper, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.delenv(TOKEN_ENV)
    assert _sync() == 2
    assert capsys.readouterr().err == f"sync: beeper: set {TOKEN_ENV}\n"


def test_sync_when_the_app_is_not_running_is_one_line_and_exit_1(
    lb: Logbook, fake: FakeBeeper, capsys: Any
) -> None:
    fake.stop()
    fake.thread = threading.Thread(target=lambda: None)
    assert _sync() == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("sync: beeper:") and "is Beeper Desktop running" in err
    assert lb.meta["seq"] == 0 and not (lb.root / "state").exists()


def test_sync_all_runs_beeper_among_the_quick_sources_and_goes_on_past_it(
    lb: Logbook, fake: FakeBeeper, monkeypatch: Any, capsys: Any
) -> None:
    from test_sync_all import Fake

    from logbook.commands import sync

    after = Fake("zeta", ("LOGBOOK_ZETA_KEY",), drafts=1)
    monkeypatch.setenv("LOGBOOK_ZETA_KEY", "k")
    monkeypatch.setattr(adapters, "live_adapters", lambda: [beeper_live, after])
    fake.stop()
    fake.thread = threading.Thread(target=lambda: None)
    try:
        cli.main(["sync", "--all"])
    except SystemExit as e:
        assert e.code == 1
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == "running beeper, zeta"
    assert "sync: beeper: " in err and "is Beeper Desktop running" in err and "Traceback" not in err
    assert after.pulls == 1
    assert [line.split()[:2] for line in out[out.index("sync --all:") :].splitlines()[1:]] == [
        ["beeper", "failed"],
        ["zeta", "ok"],
    ]
    assert "beeper" in [a.NAME for a in sync._all_order(adapters.live_adapters())]


def test_sync_all_takes_no_networks(lb: Logbook, capsys: Any) -> None:
    try:
        cli.main(["sync", "--all", "--networks", "whatsapp"])
    except SystemExit as e:
        assert e.code == 2
    assert "--all takes no --networks" in capsys.readouterr().err


def test_sync_help_names_beeper(capsys: Any) -> None:
    with pytest.raises(SystemExit):
        cli.main(["sync", "--help"])
    out = capsys.readouterr().out
    assert "beeper" in out and "--networks" in out


# -- doctor -----------------------------------------------------------------------------------


def _checks(lb: Logbook, env: dict[str, str]) -> dict[str, doctor.Check]:
    return {c.name: c for c in doctor.run(lb, env, installed=lambda _m: True)}


def test_doctor_says_configured_and_whether_the_api_answers(lb: Logbook, fake: FakeBeeper) -> None:
    check = _checks(lb, {TOKEN_ENV: TOKEN, URL_ENV: fake.url})["sync:beeper"]
    assert check.status == "pass"
    assert "configured" in check.detail and "the API answers: Beeper Desktop 4.2.0" in check.detail
    assert TOKEN not in check.detail
    assert fake.requests == [("GET", "/v1/info")], "doctor asks the one discovery call and nothing else"


def test_doctor_warns_when_the_app_does_not_answer(lb: Logbook, fake: FakeBeeper) -> None:
    fake.stop()
    fake.thread = threading.Thread(target=lambda: None)
    check = _checks(lb, {TOKEN_ENV: TOKEN, URL_ENV: fake.url})["sync:beeper"]
    assert check.status == "warn" and "is Beeper Desktop running" in check.detail


def test_doctor_says_unconfigured_once_the_record_has_synced(lb: Logbook, fake: FakeBeeper) -> None:
    assert "sync:beeper" not in _checks(lb, {}), "never synced, no variable set: not the record's source"
    _sync()
    fake.requests.clear()
    check = _checks(lb, {})["sync:beeper"]
    assert check.status == "warn" and check.detail == f"set {TOKEN_ENV}"
    assert not fake.requests, "nothing is asked without a token"
