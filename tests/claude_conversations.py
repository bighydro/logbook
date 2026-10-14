"""A synthetic data export of the Claude apps, for the `claude` adapter's tests and the readers'.

Ines Nordmann (Oslo; she does not exist) talks to Claude in the apps about her boat Solvind and a
present for her brother Ola. `export(folder)` writes what Settings → Privacy → Export data gives:
`conversations.json` (a JSON array, one object per conversation with its `chat_messages`),
`projects.json` (her one project, with a description, a prompt and a document of its own) and
`users.json` (the account: her name, an example.org address and a number in the reserved UK range).
`zipped(folder)` writes the same as the zip the apps send. The conversations hold what a real one
holds and what must never become a line: an attachment's extracted text, an uploaded image, a tool
call's input (an artifact's content, a search query) and its result, thinking, the conversation's
own summary. Every `CANARY` text must never reach a line or the stored turns, nor anything of
`users.json` or a project but its name. Every id is invented."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PASSAGE = "0193c1a0-0000-7000-8000-00000000c001"
PRESENT = "0193c1a0-0000-7000-8000-00000000c002"
EMPTY = "0193c1a0-0000-7000-8000-00000000c003"
PROJECT = "0193c1a0-0000-7000-8000-00000000f001"
ACCOUNT = "0193c1a0-0000-7000-8000-00000000a001"
PROJECT_NAME = "Solvind"
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

ATTACHMENT_TEXT = "CANARY-attachment-text-never-in-the-record"
TOOL_INPUT = "CANARY-tool-input-never-in-the-record"
TOOL_OUTPUT = "CANARY-tool-output-never-in-the-record"
ARTIFACT = "CANARY-artifact-content-never-in-the-record"
THINKING = "CANARY-thinking-never-in-the-record"
SUMMARY = "CANARY-conversation-summary-never-in-the-record"
PROJECT_TEXT = "CANARY-project-description-never-in-the-record"
PROJECT_PROMPT = "CANARY-project-prompt-never-in-the-record"
PROJECT_DOC = "CANARY-project-document-never-in-the-record"
OWNER_NAME = "Ines Nordmann"
OWNER_EMAIL = "ines.nordmann@example.org"
OWNER_PHONE = "+447700900125"
CANARIES = (
    ATTACHMENT_TEXT,
    TOOL_INPUT,
    TOOL_OUTPUT,
    ARTIFACT,
    THINKING,
    SUMMARY,
    PROJECT_TEXT,
    PROJECT_PROMPT,
    PROJECT_DOC,
    OWNER_EMAIL,
    OWNER_PHONE,
    ACCOUNT,
)

OWNER_FIRST = "Help me plan the passage to Drøbak. I'll leave the harbour at nine on Saturday."
MACHINE_FIRST = "I'll draft the plan by Friday. Can you send me the tide table?"
OWNER_SECOND = "Thanks. I will send the tide table tomorrow."
MACHINE_SECOND = "Here is the plan for Saturday."
PRESENT_OWNER = "What could I give my brother Ola for his birthday? He sails too."
PRESENT_MACHINE = "A good pair of sailing gloves, or a waterproof logbook."


def stamp(seconds: float) -> str:
    """A time as the export writes one: microseconds and `Z`."""
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def at(seconds: float) -> str:
    """The same instant as the record spells it."""
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def text(words: str, seconds: float = 0) -> dict[str, Any]:
    return {
        "start_timestamp": stamp(seconds),
        "stop_timestamp": stamp(seconds + 1),
        "type": "text",
        "text": words,
        "citations": [],
    }


def message(
    n: int,
    seconds: float,
    sender: str,
    content: list[dict[str, Any]],
    conversation: str = PASSAGE,
    **more: Any,
) -> dict[str, Any]:
    """One chat message as the export writes it: `text` is what the apps show, with a placeholder
    for every block the export cannot render, and `content` the blocks themselves."""
    shown = "\n\n".join(
        b["text"]
        if b.get("type") == "text"
        else "```\nThis block is not supported on your current device yet.\n```"
        for b in content
        if b.get("type") in ("text", "tool_use", "tool_result")
    )
    m: dict[str, Any] = {
        "uuid": f"{conversation[:-4]}{n:04d}",
        "text": shown,
        "content": content,
        "sender": sender,
        "created_at": stamp(seconds),
        "updated_at": stamp(seconds),
        "attachments": [],
        "files": [],
    }
    m.update(more)
    return m


def passage_messages() -> list[dict[str, Any]]:
    """The passage conversation: a file and an image uploaded, thinking, a search and an artifact."""
    return [
        message(
            1,
            0,
            "human",
            [text(OWNER_FIRST)],
            attachments=[
                {
                    "file_name": "harbours.csv",
                    "file_size": 2048,
                    "file_type": "text/csv",
                    "extracted_content": ATTACHMENT_TEXT,
                }
            ],
        ),
        message(
            2,
            30,
            "assistant",
            [
                {"type": "thinking", "thinking": THINKING, "summaries": [{"summary": THINKING}]},
                text(MACHINE_FIRST, 31),
                {
                    "type": "tool_use",
                    "name": "web_search",
                    "input": {"query": TOOL_INPUT},
                    "message": "Searching the web",
                },
                {
                    "type": "tool_result",
                    "name": "web_search",
                    "content": [{"type": "knowledge", "title": "Tides", "text": TOOL_OUTPUT}],
                    "is_error": False,
                },
            ],
        ),
        message(
            3,
            600,
            "human",
            [text(OWNER_SECOND, 600)],
            files=[{"file_name": "chart.png"}],
        ),
        message(
            4,
            630,
            "assistant",
            [
                {
                    "type": "tool_use",
                    "name": "artifacts",
                    "input": {"id": "plan", "type": "text/markdown", "title": "Plan", "content": ARTIFACT},
                },
                {"type": "tool_result", "name": "artifacts", "content": [{"type": "text", "text": "OK"}]},
                text(MACHINE_SECOND, 631),
            ],
        ),
    ]


def present_messages() -> list[dict[str, Any]]:
    """A shorter conversation a day later, in no project and without a name."""
    day = 86400
    return [
        message(1, day, "human", [text(PRESENT_OWNER, day)], conversation=PRESENT),
        message(2, day + 20, "assistant", [text(PRESENT_MACHINE, day + 20)], conversation=PRESENT),
    ]


def conversation(
    uuid: str, name: str, messages: list[dict[str, Any]], created: float, updated: float, **more: Any
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "uuid": uuid,
        "name": name,
        "summary": "",
        "created_at": stamp(created),
        "updated_at": stamp(updated),
        "account": {"uuid": ACCOUNT},
        "chat_messages": messages,
    }
    c.update(more)
    return c


def conversations() -> list[Any]:
    """The passage conversation (in the project), the present (no name, no project) and an empty one."""
    return [
        conversation(
            PASSAGE,
            "Passage to Drøbak",
            passage_messages(),
            0,
            700,
            summary=SUMMARY,
            project_uuid=PROJECT,
        ),
        conversation(PRESENT, "", present_messages(), 86400, 86420),
        conversation(EMPTY, "New chat", [], 90000, 90000),
    ]


def projects() -> list[dict[str, Any]]:
    return [
        {
            "uuid": PROJECT,
            "name": PROJECT_NAME,
            "description": PROJECT_TEXT,
            "is_private": True,
            "is_starter_project": False,
            "prompt_template": PROJECT_PROMPT,
            "created_at": stamp(-86400),
            "updated_at": stamp(-86400),
            "creator": {"uuid": ACCOUNT, "full_name": OWNER_NAME},
            "docs": [
                {
                    "uuid": f"{PROJECT[:-4]}d001",
                    "filename": "solvind.md",
                    "content": PROJECT_DOC,
                    "created_at": stamp(-86400),
                }
            ],
        }
    ]


def users() -> list[dict[str, Any]]:
    return [
        {
            "uuid": ACCOUNT,
            "full_name": OWNER_NAME,
            "email_address": OWNER_EMAIL,
            "verified_phone_number": OWNER_PHONE,
        }
    ]


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def export(folder: Path, chats: list[Any] | None = None) -> Path:
    """The unpacked export: the three files in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "conversations.json").write_bytes(_bytes(conversations() if chats is None else chats))
    (folder / "projects.json").write_bytes(_bytes(projects()))
    (folder / "users.json").write_bytes(_bytes(users()))
    return folder


def zipped(file: Path, chats: list[Any] | None = None) -> Path:
    """The export as the apps send it: one zip holding the three files."""
    file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("conversations.json", _bytes(conversations() if chats is None else chats))
        z.writestr("projects.json", _bytes(projects()))
        z.writestr("users.json", _bytes(users()))
    return file
