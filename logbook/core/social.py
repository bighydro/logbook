"""`social/v1` (RFC 0048, draft) in words: one act on a social network as a row says it.

`followed by @ola.example`, `liked a post by @sailing.example`, `commented on a post by
@ola.example: Så fint!`, `searched for @per.example`. The account is its handle with an `@`, the
network's prefix (`instagram:`) left off: an account, never a person, and never resolved here (a
handle becomes a person only by a resolution the owner confirms, RFC 0006). An act whose account the
export did not give says the act alone; an action this version does not know is said as it is spelled.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KIND = "social"
SCHEMA = "social/v1"

WORDS = {  # action → the words before the account
    "follow": "followed",
    "followed_by": "followed by",
    "close_friend": "added to close friends:",
    "block": "blocked",
    "restrict": "restricted",
    "follow_request_sent": "asked to follow",
    "follow_request_received": "a follow request from",
    "unfollow": "unfollowed",
    "like": "liked a post by",
    "comment": "commented on a post by",
    "story_like": "liked a story by",
    "search": "searched for",
}
ALONE = {  # action → the words when the export named no account
    "like": "liked a post",
    "comment": "commented on a post",
    "story_like": "liked a story",
    "search": "searched",
}


def account(payload: Mapping[str, Any]) -> str | None:
    """`@<handle>` of the act's counterpart, its network's prefix off; None when it names none."""
    ref = payload.get("counterpart")
    value = ref.get("value") if isinstance(ref, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        return None
    network = payload.get("network")
    handle = value.strip()
    if isinstance(network, str) and handle.startswith(f"{network}:"):
        handle = handle[len(network) + 1 :]
    return f"@{handle}"


def text(payload: Mapping[str, Any]) -> str:
    """The act in words, a comment's own words after a colon."""
    action = str(payload.get("action") or "an act")
    who = account(payload)
    if who is not None:
        said = f"{WORDS.get(action, action.replace('_', ' '))} {who}"
    else:
        said = ALONE.get(
            action, WORDS.get(action, action.replace("_", " ")).removesuffix(":").removesuffix(" by")
        )
    words = payload.get("text")
    if isinstance(words, str) and words.strip():
        said += f": {' '.join(words.split())}"
    return said
