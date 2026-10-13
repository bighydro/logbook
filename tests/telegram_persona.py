"""The Oslo persona's own Telegram bots, for the `telegram` adapters' tests. Nobody here exists.

Ines Nordmann runs two bots of her own: `Nordlys` (a logbook helper) and `Fjordvakt` (a weather
watch). Telegram Desktop's JSON export of her account holds both bot chats, a personal chat with
Ola that the adapter must leave alone, and her saved messages. Every id is invented: the owner is
900000000 and the bots 900000001 and 900000002, numbers chosen to look made up; the phone number
is in the reserved UK range 07700 900xxx; the tokens are `<bot id>:not-a-real-token`.

`export(folder)` writes the export (result.json and two media files) and returns its folder;
`at(minutes)` is an instant `minutes` after 2026-03-01 10:00 UTC, as the record spells it, and
`unix(minutes)` the same instant in seconds, as the export and the Bot API spell it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

OWNER_ID = 900000000
NORDLYS_ID = 900000001
FJORDVAKT_ID = 900000002
OLA_ID = 900000010
NORDLYS_TOKEN = f"{NORDLYS_ID}:not-a-real-token-nordlys"
FJORDVAKT_TOKEN = f"{FJORDVAKT_ID}:not-a-real-token-fjordvakt"
T0 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
OSLO = ZoneInfo("Europe/Oslo")
PHOTO_BYTES = b"\xff\xd8\xff synthetic jpeg, not a photo of anything"
VOICE_BYTES = b"OggS synthetic voice, nobody speaks"


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def unix(minutes: float) -> int:
    return int((T0 + timedelta(minutes=minutes)).timestamp())


def _local(minutes: float) -> str:
    """The export's `date`: local time on the exporting machine, without an offset."""
    return (T0 + timedelta(minutes=minutes)).astimezone(OSLO).strftime("%Y-%m-%dT%H:%M:%S")


def message(
    msg_id: int, minutes: float, sender_id: int, sender: str, text: Any = "", **more: Any
) -> dict[str, Any]:
    """One message as Telegram Desktop writes it: `text` a string or a list of strings and entities."""
    m: dict[str, Any] = {
        "id": msg_id,
        "type": "message",
        "date": _local(minutes),
        "date_unixtime": str(unix(minutes)),
        "from": sender,
        "from_id": f"user{sender_id}",
    }
    m.update(more)
    m["text"] = text
    plain = text if isinstance(text, list) else [text] if text else []
    m["text_entities"] = [
        part if isinstance(part, dict) else {"type": "plain", "text": part} for part in plain
    ]
    return m


def mine(msg_id: int, minutes: float, text: Any = "", **more: Any) -> dict[str, Any]:
    return message(msg_id, minutes, OWNER_ID, "Ines Nordmann", text, **more)


def nordlys(msg_id: int, minutes: float, text: Any = "", **more: Any) -> dict[str, Any]:
    return message(msg_id, minutes, NORDLYS_ID, "Nordlys", text, **more)


NORDLYS_MESSAGES: list[dict[str, Any]] = [
    {
        "id": 400,
        "type": "service",
        "date": _local(0),
        "date_unixtime": str(unix(0)),
        "actor": "Ines Nordmann",
        "actor_id": f"user{OWNER_ID}",
        "action": "pin_message",
        "message_id": 401,
        "text": "",
        "text_entities": [],
    },
    mine(401, 15, "Plan the passage to Drøbak for Saturday, and remind me to call Ola"),
    nordlys(
        402,
        16,
        [
            "I'll have the passage plan ready by ",
            {"type": "bold", "text": "Friday"},
            ". Can you send me the tide table?",
        ],
        reply_to_message_id=401,
    ),
    mine(403, 20, "the anchorage", photo="photos/photo_1@01-03-2026_11-20-00.jpg", width=800, height=600),
    mine(
        404,
        25,
        "",
        file="voice_messages/audio_1@01-03-2026_11-25-00.ogg",
        media_type="voice_message",
        mime_type="audio/ogg",
        duration_seconds=4,
    ),
    nordlys(
        405,
        26,
        "",
        file="(File not included. Change data exporting settings to download.)",
        file_name="passage-plan.pdf",
        mime_type="application/pdf",
    ),
    mine(406, 30, "I will check the anchor chain tomorrow", edited=_local(31), edited_unixtime=str(unix(31))),
    mine(407, 35, "I'll bring the charts on Friday", forwarded_from="Ola Nordmann"),
    mine(408, 40, "", photo="photos/photo_2@01-03-2026_11-40-00.jpg"),  # an album: same second
    mine(409, 40, "", photo="photos/photo_3@01-03-2026_11-40-00.jpg"),
    mine(410, 45, "", photo="../outside.jpg"),  # a path that leaves the export: missing, never read
]
FJORDVAKT_MESSAGES: list[dict[str, Any]] = [
    message(501, 60, FJORDVAKT_ID, "Fjordvakt", "Gale warning for Oslofjord tonight"),
    message(502, 62, OWNER_ID, "Ines Nordmann", "Thanks, I'll double the mooring lines"),
]
OLA_MESSAGES: list[dict[str, Any]] = [
    message(601, 70, OLA_ID, "Ola Nordmann", "I'll bring the charts on Friday"),
    message(602, 71, OWNER_ID, "Ines Nordmann", "Great"),
]


def document(chats: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The whole export: personal information and the chat list."""
    listed = (
        chats
        if chats is not None
        else [
            {"name": "Nordlys", "type": "bot_chat", "id": NORDLYS_ID, "messages": NORDLYS_MESSAGES},
            {"name": "Fjordvakt", "type": "bot_chat", "id": FJORDVAKT_ID, "messages": FJORDVAKT_MESSAGES},
            {"name": "Ola Nordmann", "type": "personal_chat", "id": OLA_ID, "messages": OLA_MESSAGES},
            {
                "type": "saved_messages",
                "id": OWNER_ID,
                "messages": [message(701, 80, OWNER_ID, "Ines Nordmann", "x")],
            },
        ]
    )
    return {
        "about": "Here is the data you requested. Synthetic: nobody in it exists.",
        "personal_information": {
            "user_id": OWNER_ID,
            "first_name": "Ines",
            "last_name": "Nordmann",
            "phone_number": "+44 7700 900000",
            "bio": "",
        },
        "chats": {"about": "This page lists all chats from this export.", "list": listed},
    }


def export(folder: Path, doc: dict[str, Any] | None = None) -> Path:
    """Write the export under `folder` (created) and return it."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "photos").mkdir(exist_ok=True)
    (folder / "voice_messages").mkdir(exist_ok=True)
    (folder / "photos" / "photo_1@01-03-2026_11-20-00.jpg").write_bytes(PHOTO_BYTES)
    (folder / "photos" / "photo_2@01-03-2026_11-40-00.jpg").write_bytes(PHOTO_BYTES + b"2")
    (folder / "photos" / "photo_3@01-03-2026_11-40-00.jpg").write_bytes(PHOTO_BYTES + b"3")
    (folder / "voice_messages" / "audio_1@01-03-2026_11-25-00.ogg").write_bytes(VOICE_BYTES)
    body = json.dumps(doc if doc is not None else document(), ensure_ascii=False, indent=1)
    (folder / "result.json").write_bytes(body.encode("utf-8"))
    return folder
