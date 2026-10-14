"""`logbook sync telegram`: the owner's own bots over the Bot API, read-only. A fake Bot API in this
process (a server on 127.0.0.1) serves the persona's two bots and records every call, so a test can
hold the client to the three read-only methods it may use and to never confirming an update (no
`offset`) or changing the bot's subscription (no `allowed_updates`). Synthetic: `telegram_persona`."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import telegram_persona as tp

from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import telegram, telegram_live
from logbook.core import machine
from logbook.core.store import Logbook

TOKENS_ENV, OWNER_ENV, API_ENV = (
    "LOGBOOK_TELEGRAM_BOT_TOKENS",
    "LOGBOOK_TELEGRAM_OWNER_ID",
    "LOGBOOK_TELEGRAM_API",
)
STRANGER_ID = 900000099
BROKEN_TOKEN = "900000003:not-a-real-token-revoked"
INES = {"id": tp.OWNER_ID, "is_bot": False, "first_name": "Ines", "last_name": "Nordmann"}
NORDLYS = {"id": tp.NORDLYS_ID, "is_bot": True, "first_name": "Nordlys", "username": "nordlys_example_bot"}
FJORDVAKT = {
    "id": tp.FJORDVAKT_ID,
    "is_bot": True,
    "first_name": "Fjordvakt",
    "username": "fjordvakt_example_bot",
}
PRIVATE = {"id": tp.OWNER_ID, "type": "private", "first_name": "Ines"}


def _msg(msg_id: int, minutes: float, text: str | None = None, **more: Any) -> dict[str, Any]:
    m: dict[str, Any] = {"message_id": msg_id, "from": INES, "chat": PRIVATE, "date": tp.unix(minutes)}
    if text is not None:
        m["text"] = text
    m.update(more)
    return m


def _photo(unique: str) -> list[dict[str, Any]]:
    return [
        {
            "file_id": f"small-{unique}",
            "file_unique_id": f"{unique}-s",
            "file_size": 900,
            "width": 90,
            "height": 60,
        },
        {
            "file_id": f"large-{unique}",
            "file_unique_id": unique,
            "file_size": 41000,
            "width": 800,
            "height": 600,
        },
    ]


BOT_REPLY = {  # the bot's own message, as an update that replies to it carries it
    "message_id": 2002,
    "from": NORDLYS,
    "chat": PRIVATE,
    "date": tp.unix(16),
    "text": "I'll have the passage plan ready by Friday. Can you send me the tide table?",
}
NORDLYS_UPDATES: list[dict[str, Any]] = [
    {
        "update_id": 7001,
        "message": _msg(2001, 15, "Plan the passage to Drøbak for Saturday, and remind me to call Ola"),
    },
    {"update_id": 7002, "message": _msg(2003, 20, caption="the anchorage", photo=_photo("AQADsynthetic1"))},
    {
        "update_id": 7003,
        "message": _msg(
            2004,
            25,
            voice={
                "file_id": "voice-1",
                "file_unique_id": "AwADsynthetic4",
                "duration": 4,
                "mime_type": "audio/ogg",
                "file_size": 35,
            },
        ),
    },
    {"update_id": 7004, "message": _msg(2006, 30, "I will check the anchor chain tmorrow")},
    {
        "update_id": 7005,
        "edited_message": _msg(2006, 30, "I will check the anchor chain tomorrow", edit_date=tp.unix(31)),
    },
    {"update_id": 7006, "message": _msg(2008, 40, photo=_photo("AQADsynthetic8"), media_group_id="album-1")},
    {"update_id": 7007, "message": _msg(2009, 40, photo=_photo("AQADsynthetic9"), media_group_id="album-1")},
    {"update_id": 7008, "message": _msg(2012, 50, "Here is the tide table", reply_to_message=BOT_REPLY)},
    {
        "update_id": 7009,
        "message": {
            "message_id": 2013,
            "from": {"id": STRANGER_ID, "is_bot": False, "first_name": "Someone"},
            "chat": {"id": STRANGER_ID, "type": "private"},
            "date": tp.unix(51),
            "text": "hello bot, I'll pay you",
        },
    },
    {
        "update_id": 7010,
        "message": _msg(2014, 52, "in a group", chat={"id": -900000500, "type": "group", "title": "Crew"}),
    },
    {"update_id": 7011, "callback_query": {"id": "cb-1", "from": INES, "data": "ok"}},
    {
        "update_id": 7012,
        "message": _msg(
            2015,
            53,
            "I'll bring the charts on Friday",
            forward_origin={
                "type": "user",
                "date": tp.unix(10),
                "sender_user": {
                    "id": tp.OLA_ID,
                    "is_bot": False,
                    "first_name": "Ola",
                    "last_name": "Nordmann",
                },
            },
        ),
    },
]


class BotAPI:
    """A fake Bot API: per token, getMe, getWebhookInfo and getUpdates; every call recorded."""

    def __init__(self) -> None:
        self.calls: list[
            tuple[str, str, str, dict[str, list[str]]]
        ] = []  # (http method, token, method, query)
        self.bots: dict[str, dict[str, Any]] = {
            tp.NORDLYS_TOKEN: {"me": NORDLYS, "webhook": "", "updates": NORDLYS_UPDATES},
            tp.FJORDVAKT_TOKEN: {"me": FJORDVAKT, "webhook": "", "updates": []},
        }
        api = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, http_method: str) -> None:
                parts = urlsplit(self.path)
                token_part, _, method = parts.path.strip("/").partition("/")
                token = token_part.removeprefix("bot")
                api.calls.append((http_method, token, method, parse_qs(parts.query)))
                bot = api.bots.get(token)
                if bot is None:
                    self._send(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
                elif method == "getMe":
                    self._send(200, {"ok": True, "result": bot["me"]})
                elif method == "getWebhookInfo":
                    pending = len(bot["updates"])
                    self._send(
                        200, {"ok": True, "result": {"url": bot["webhook"], "pending_update_count": pending}}
                    )
                elif method == "getUpdates" and bot["webhook"]:
                    self._send(
                        409, {"ok": False, "error_code": 409, "description": "Conflict: webhook is active"}
                    )
                elif method == "getUpdates":
                    self._send(200, {"ok": True, "result": bot["updates"]})
                else:
                    self._send(404, {"ok": False, "error_code": 404, "description": "Not Found"})

            def do_GET(self) -> None:
                self._answer("GET")

            def do_POST(self) -> None:
                self._answer("POST")

            def _send(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def methods(self) -> set[str]:
        return {method for _verb, _token, method, _query in self.calls}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api() -> Any:
    server = BotAPI()
    yield server
    server.close()


def _config(api: BotAPI, *tokens: str) -> telegram_live.Config:
    env = {TOKENS_ENV: ",".join(tokens or (tp.NORDLYS_TOKEN,)), OWNER_ENV: str(tp.OWNER_ID), API_ENV: api.url}
    config = telegram_live.configure(env)
    assert config is not None
    return config


def _pull(config: telegram_live.Config, **options: Any) -> list[dict[str, Any]]:
    return list(telegram_live.pull(config, **options))


def _by_id(lines: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {line["payload"]["extra"]["message_id"]: line for line in lines}


# -- configure ---------------------------------------------------------------------------------------


def test_configure_needs_the_tokens_and_the_owner():
    assert telegram_live.configure({}) is None
    assert telegram_live.configure({TOKENS_ENV: tp.NORDLYS_TOKEN}) is None
    assert telegram_live.configure({OWNER_ENV: str(tp.OWNER_ID)}) is None
    assert adapters.needs(telegram_live, {TOKENS_ENV: tp.NORDLYS_TOKEN}) == OWNER_ENV


def test_configure_reads_comma_separated_tokens_and_keeps_them_out_of_repr():
    config = telegram_live.configure(
        {TOKENS_ENV: f" {tp.NORDLYS_TOKEN} , {tp.FJORDVAKT_TOKEN},", OWNER_ENV: f" {tp.OWNER_ID} "}
    )
    assert config is not None and config.tokens == (tp.NORDLYS_TOKEN, tp.FJORDVAKT_TOKEN)
    assert config.owner == str(tp.OWNER_ID) and config.api == "https://api.telegram.org"
    assert "not-a-real-token" not in repr(config)


@pytest.mark.parametrize(
    ("env", "said"),
    [
        ({TOKENS_ENV: "not a token", OWNER_ENV: "900000000"}, "token 1 of 1 is not <bot id>:<secret>"),
        ({TOKENS_ENV: tp.NORDLYS_TOKEN, OWNER_ENV: "@ines"}, "the owner's numeric Telegram user id"),
        (
            {TOKENS_ENV: tp.NORDLYS_TOKEN, OWNER_ENV: "900000000", API_ENV: "http://bots.example.org"},
            "https, or http on this machine",
        ),
    ],
)
def test_configure_refuses_in_one_sentence_and_never_echoes_a_token(env: dict[str, str], said: str):
    with pytest.raises(ValueError) as e:
        telegram_live.configure(env)
    assert said in str(e.value) and "not-a-real-token" not in str(e.value)


# -- the pull ----------------------------------------------------------------------------------------


def test_only_the_owners_private_messages_are_lines_and_the_rest_is_counted(api: BotAPI):
    counts: dict[str, int] = {}
    lines = _pull(_config(api), counts=counts)
    assert sorted(_by_id(lines)) == [2001, 2003, 2004, 2006, 2008, 2009, 2012, 2015]
    assert len(lines) == 9  # 2006 twice: as sent and as edited
    assert counts["skipped_not_owner"] == 1 and counts["skipped_not_private"] == 1
    assert counts["skipped_other_update"] == 1


def test_the_owners_lines_are_theirs_with_the_bot_as_counterpart(api: BotAPI):
    for line in _pull(_config(api)):
        payload = line["payload"]
        assert (line["source"], line["kind"], line["tier"]) == ("telegram", "message", 2)
        assert payload["from_me"] is True and not machine.is_machine(payload) and "sender" not in payload
        assert payload["chat"] == {"id": str(tp.NORDLYS_ID), "type": "direct", "name": "Nordlys"}
        assert machine.agent_of(payload) == {
            "kind": "agent",
            "ref": {"kind": "provider_id", "value": f"telegram:{tp.NORDLYS_ID}"},
            "name": "Nordlys",
            "username": "nordlys_example_bot",
        }
        assert payload["extra"]["view"] == "bot"


def test_the_same_message_gets_the_same_key_from_the_export_and_from_the_bot(api: BotAPI, tmp_path: Path):
    exported = {
        line["payload"]["extra"]["message_id"]: line["payload"]["raw_id"]
        for line in telegram.run(tp.export(tmp_path / "export"), timezone="Europe/Oslo")
    }
    live = _by_id(_pull(_config(api)))
    assert live[2001]["payload"]["raw_id"] == exported[401]
    assert live[2003]["payload"]["raw_id"] == exported[403]  # a photo with a caption
    assert live[2004]["payload"]["raw_id"] == exported[404]  # a voice message
    assert live[2008]["payload"]["raw_id"] == exported[408]  # an album, one second, two keys
    assert live[2009]["payload"]["raw_id"] == exported[409]
    assert live[2012]["payload"]["reply_to"] == exported[402]  # the bot's message replied to


def test_an_edit_is_keyed_by_the_text_it_has_now(api: BotAPI, tmp_path: Path):
    exported = {
        line["payload"]["extra"]["message_id"]: line["payload"]["raw_id"]
        for line in telegram.run(tp.export(tmp_path / "export"), timezone="Europe/Oslo")
    }
    sent, edited = [line for line in _pull(_config(api)) if line["payload"]["extra"]["message_id"] == 2006]
    assert edited["payload"]["edited"] is True and edited["payload"]["extra"]["edited_at"] == tp.at(31)
    assert edited["payload"]["raw_id"] == exported[406]
    assert sent["payload"]["raw_id"] != exported[406] and "edited" not in sent["payload"]


def test_media_is_referenced_by_the_apis_file_id_never_fetched(api: BotAPI):
    by_id = _by_id(_pull(_config(api)))
    photo = by_id[2003]["payload"]
    assert photo["media_kind"] == "image" and photo["text"] == "the anchorage"
    assert photo["extra"]["media"] == {"file_unique_id": "AQADsynthetic1", "bytes": 41000}
    voice = by_id[2004]["payload"]
    assert voice["media_kind"] == "voice"
    assert voice["extra"]["media"] == {
        "file_unique_id": "AwADsynthetic4",
        "bytes": 35,
        "media_type": "audio/ogg",
    }
    assert "getFile" not in api.methods()


def test_a_forwarded_message_keeps_who_it_came_from(api: BotAPI):
    forwarded = _by_id(_pull(_config(api)))[2015]["payload"]
    assert forwarded["extra"]["forwarded"] is True and forwarded["extra"]["forwarded_from"] == "Ola Nordmann"


def test_the_client_only_reads_and_never_confirms_an_update(api: BotAPI):
    _pull(_config(api, tp.NORDLYS_TOKEN, tp.FJORDVAKT_TOKEN))
    assert api.methods() <= {"getMe", "getWebhookInfo", "getUpdates"}
    assert {verb for verb, *_rest in api.calls} == {"GET"}
    for _verb, _token, method, query in api.calls:
        assert "offset" not in query and "allowed_updates" not in query
        if method == "getUpdates":
            assert query["timeout"] == ["0"]


def test_a_bot_with_nothing_pending_is_never_asked_for_updates(api: BotAPI):
    assert _pull(_config(api, tp.FJORDVAKT_TOKEN)) == []
    assert ("GET", tp.FJORDVAKT_TOKEN, "getUpdates") not in {(v, t, m) for v, t, m, _q in api.calls}


def test_a_bot_on_a_webhook_is_left_alone_and_said_once(api: BotAPI):
    api.bots[tp.FJORDVAKT_TOKEN]["webhook"] = "https://bots.example.org/fjordvakt"
    api.bots[tp.FJORDVAKT_TOKEN]["updates"] = [{"update_id": 1, "message": _msg(1, 1, "x")}]
    failed: list[str] = []
    lines = _pull(_config(api, tp.FJORDVAKT_TOKEN, tp.NORDLYS_TOKEN), failed=failed)
    assert len(lines) == 9  # the other bot is read all the same
    (problem,) = failed
    assert "fjordvakt_example_bot" in problem and "webhook" in problem
    assert "bots.example.org" not in problem and "not-a-real-token" not in problem
    assert ("GET", tp.FJORDVAKT_TOKEN, "getUpdates") not in {(v, t, m) for v, t, m, _q in api.calls}


def test_a_token_the_api_refuses_is_one_line_naming_the_bot_never_the_token(api: BotAPI):
    failed: list[str] = []
    lines = _pull(_config(api, BROKEN_TOKEN, tp.NORDLYS_TOKEN), failed=failed)
    assert len(lines) == 9
    (problem,) = failed
    assert "900000003" in problem and "401" in problem and "not-a-real-token" not in problem


def test_without_a_failed_list_a_refused_token_raises_after_the_others(api: BotAPI):
    with pytest.raises(OSError) as e:
        _pull(_config(api, BROKEN_TOKEN))
    assert "not-a-real-token" not in str(e.value)


def test_a_message_with_neither_text_nor_media_is_counted_not_written(api: BotAPI):
    api.bots[tp.NORDLYS_TOKEN]["updates"] = [
        {"update_id": 1, "message": _msg(3001, 1, dice={"emoji": "x", "value": 3})}
    ]
    counts: dict[str, int] = {}
    assert _pull(_config(api), counts=counts) == [] and counts["skipped_empty"] == 1


def test_since_leaves_out_what_came_before(api: BotAPI):
    lines = _pull(_config(api), since=tp.at(50))
    assert sorted(_by_id(lines)) == [2012, 2015]


def test_no_watermark_is_kept_the_dedupe_is_the_mark(api: BotAPI):
    assert all(telegram_live.watermark(line) is None for line in _pull(_config(api)))


# -- through sync ------------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: BotAPI) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv(TOKENS_ENV, tp.NORDLYS_TOKEN)
    monkeypatch.setenv(OWNER_ENV, str(tp.OWNER_ID))
    monkeypatch.setenv(API_ENV, api.url)
    return lb


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(list(args))
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_sync_after_the_export_writes_only_what_the_export_lacks(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    assert _cli(capsys, "add", "telegram-export", str(tp.export(tmp_path / "export")))[0] == 0
    code, out, err = _cli(capsys, "sync", "telegram")
    assert code == 0, err
    # new: the edit's first version, the reply about the tide table, the forward; the rest is the export's
    assert "telegram: 3 new lines of 9 seen" in out and "6 already in the record" in out
    assert "not-a-real-token" not in out + err
    seq, _head, errors = lb.verify()
    assert seq == 15 and not errors


def test_sync_twice_writes_nothing_the_second_time(lb: Logbook, capsys: pytest.CaptureFixture[str]):
    assert _cli(capsys, "sync", "telegram")[0] == 0
    code, out, _err = _cli(capsys, "sync", "telegram")
    assert code == 0 and "telegram: 0 new lines of 9 seen" in out


def test_sync_says_what_to_set(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.delenv(OWNER_ENV)
    code, _out, err = _cli(capsys, "sync", "telegram")
    assert code == 2 and f"sync: telegram: set {OWNER_ENV}" in err


def test_a_bot_that_failed_exits_1_and_the_others_are_written(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv(TOKENS_ENV, f"{BROKEN_TOKEN},{tp.NORDLYS_TOKEN}")
    code, out, err = _cli(capsys, "sync", "telegram")
    assert code == 1 and "telegram: 9 new lines" in out and "900000003" in err
    assert "not-a-real-token" not in out + err
