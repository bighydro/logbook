"""The apps: a bundle id's name and category, for `rollup attention` and the Screen Time adapter.

Screen Time knows an app by its bundle id (`com.apple.Safari`); the owner knows it by name, and a
year of attention reads by category: `communication`, `browser`, `media`, `work`, `other`. A small
built-in table (`BUILT_IN`) names and sorts the common apps; the owner's own file, `policy/apps.json`,
adds to it and overrides it:

    {"com.apple.dt.Xcode": "other",
     "org.example.puzzle": {"name": "Puzzle", "category": "media"}}

A bare string is a category. A bundle id neither names is sorted by a hint in the id itself
(`mail`, `chat`, `music`, …, `HINTS`) and otherwise `other`, with no name. The file is the owner's:
nothing here writes it, and a record without it reads with the built-in table alone. A file that is
not the documented shape, or names a category outside the five, is a `PolicyError` naming the file.

The adapter uses the built-in names only (`built_in_name`): a line's `title` is the record of what
the source said, read once; the owner's naming and sorting are the reader's, applied at rollup time
so a renamed app re-sorts a year without a new line."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .policy import PolicyError

KIND = (
    "app-use"  # the kind of a Screen Time line; `adapters.screentime` writes it, `rollup attention` reads it
)
SCHEMA = "event/v1"  # its payload schema

__all__ = ["PolicyError"]

APPS_FILE = PurePosixPath("policy/apps.json")  # record-relative
COMMUNICATION, BROWSER, MEDIA, WORK, OTHER = "communication", "browser", "media", "work", "other"
CATEGORIES = (COMMUNICATION, BROWSER, MEDIA, WORK, OTHER)

# bundle id → (name, category). Apple's own apps under both their Mac and their iOS bundle ids.
BUILT_IN: dict[str, tuple[str, str]] = {
    # communication
    "com.apple.MobileSMS": ("Messages", COMMUNICATION),
    "com.apple.iChat": ("Messages", COMMUNICATION),
    "com.apple.mobilemail": ("Mail", COMMUNICATION),
    "com.apple.mail": ("Mail", COMMUNICATION),
    "com.apple.facetime": ("FaceTime", COMMUNICATION),
    "com.apple.FaceTime": ("FaceTime", COMMUNICATION),
    "com.apple.mobilephone": ("Phone", COMMUNICATION),
    "net.whatsapp.WhatsApp": ("WhatsApp", COMMUNICATION),
    "net.whatsapp.WhatsApp.Desktop": ("WhatsApp", COMMUNICATION),
    "com.tinyspeck.chatlyio": ("Slack", COMMUNICATION),
    "com.tinyspeck.slackmacgap": ("Slack", COMMUNICATION),
    "com.microsoft.teams": ("Microsoft Teams", COMMUNICATION),
    "com.microsoft.teams2": ("Microsoft Teams", COMMUNICATION),
    "com.microsoft.skype.teams": ("Microsoft Teams", COMMUNICATION),
    "us.zoom.xos": ("Zoom", COMMUNICATION),
    "us.zoom.videomeetings": ("Zoom", COMMUNICATION),
    "ph.telegra.Telegraph": ("Telegram", COMMUNICATION),
    "ru.keepcoder.Telegram": ("Telegram", COMMUNICATION),
    "org.whispersystems.signal": ("Signal", COMMUNICATION),
    "org.whispersystems.signal-desktop": ("Signal", COMMUNICATION),
    "com.facebook.Messenger": ("Messenger", COMMUNICATION),
    "com.hnc.Discord": ("Discord", COMMUNICATION),
    "com.hammerandchisel.discord": ("Discord", COMMUNICATION),
    "com.beeper.ios": ("Beeper", COMMUNICATION),
    # browser
    "com.apple.Safari": ("Safari", BROWSER),
    "com.apple.mobilesafari": ("Safari", BROWSER),
    "com.google.Chrome": ("Google Chrome", BROWSER),
    "com.google.chrome.ios": ("Google Chrome", BROWSER),
    "org.mozilla.firefox": ("Firefox", BROWSER),
    "org.mozilla.ios.Firefox": ("Firefox", BROWSER),
    "company.thebrowser.Browser": ("Arc", BROWSER),
    "com.brave.Browser": ("Brave", BROWSER),
    "com.brave.ios.browser": ("Brave", BROWSER),
    "com.microsoft.edgemac": ("Microsoft Edge", BROWSER),
    "com.microsoft.msedge": ("Microsoft Edge", BROWSER),
    "com.duckduckgo.mobile.ios": ("DuckDuckGo", BROWSER),
    # media
    "com.apple.Music": ("Music", MEDIA),
    "com.apple.TV": ("TV", MEDIA),
    "com.apple.podcasts": ("Podcasts", MEDIA),
    "com.apple.mobileslideshow": ("Photos", MEDIA),
    "com.apple.Photos": ("Photos", MEDIA),
    "com.apple.news": ("News", MEDIA),
    "com.apple.iBooks": ("Books", MEDIA),
    "com.apple.iBooksX": ("Books", MEDIA),
    "com.spotify.client": ("Spotify", MEDIA),
    "com.google.ios.youtube": ("YouTube", MEDIA),
    "com.netflix.Netflix": ("Netflix", MEDIA),
    "com.burbn.instagram": ("Instagram", MEDIA),
    "com.zhiliaoapp.musically": ("TikTok", MEDIA),
    "com.facebook.Facebook": ("Facebook", MEDIA),
    "com.atebits.Tweetie2": ("X", MEDIA),
    "com.reddit.Reddit": ("Reddit", MEDIA),
    "tv.twitch": ("Twitch", MEDIA),
    "com.shazam.Shazam": ("Shazam", MEDIA),
    # work
    "com.apple.dt.Xcode": ("Xcode", WORK),
    "com.apple.Terminal": ("Terminal", WORK),
    "com.googlecode.iterm2": ("iTerm2", WORK),
    "com.microsoft.VSCode": ("Visual Studio Code", WORK),
    "com.apple.iWork.Pages": ("Pages", WORK),
    "com.apple.iWork.Numbers": ("Numbers", WORK),
    "com.apple.iWork.Keynote": ("Keynote", WORK),
    "com.microsoft.Word": ("Microsoft Word", WORK),
    "com.microsoft.Excel": ("Microsoft Excel", WORK),
    "com.microsoft.Powerpoint": ("Microsoft PowerPoint", WORK),
    "com.microsoft.Outlook": ("Microsoft Outlook", COMMUNICATION),
    "com.apple.Notes": ("Notes", WORK),
    "com.apple.mobilenotes": ("Notes", WORK),
    "com.apple.reminders": ("Reminders", WORK),
    "com.apple.iCal": ("Calendar", WORK),
    "com.apple.mobilecal": ("Calendar", WORK),
    "com.apple.Preview": ("Preview", WORK),
    "notion.id": ("Notion", WORK),
    "md.obsidian": ("Obsidian", WORK),
    "com.culturedcode.ThingsMac": ("Things", WORK),
    "com.omnigroup.OmniFocus4": ("OmniFocus", WORK),
    "com.figma.Desktop": ("Figma", WORK),
    "com.apple.Numbers": ("Numbers", WORK),
    # other
    "com.apple.finder": ("Finder", OTHER),
    "com.apple.Maps": ("Maps", OTHER),
    "com.apple.camera": ("Camera", OTHER),
    "com.apple.Preferences": ("Settings", OTHER),
    "com.apple.systempreferences": ("System Settings", OTHER),
    "com.apple.AppStore": ("App Store", OTHER),
    "com.apple.weather": ("Weather", OTHER),
    "com.apple.Health": ("Health", OTHER),
    "com.apple.Passbook": ("Wallet", OTHER),
    "com.apple.loginwindow": ("Login Window", OTHER),
}

# A word in a bundle id that sorts an app the table does not know; the first match wins.
HINTS: tuple[tuple[str, str], ...] = (
    ("mail", COMMUNICATION),
    ("messag", COMMUNICATION),
    ("chat", COMMUNICATION),
    ("telegram", COMMUNICATION),
    ("browser", BROWSER),
    ("firefox", BROWSER),
    ("chrome", BROWSER),
    ("music", MEDIA),
    ("video", MEDIA),
    ("podcast", MEDIA),
    ("youtube", MEDIA),
    ("netflix", MEDIA),
    ("spotify", MEDIA),
    ("game", MEDIA),
    ("terminal", WORK),
    ("code", WORK),
    ("office", WORK),
)


@dataclass(frozen=True)
class Apps:
    """The table a reader asks: the built-in rows under the owner's overrides."""

    names: dict[str, str] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)

    def name(self, bundle_id: str) -> str | None:
        """The app's name, or None when neither the owner nor the built-in table names it."""
        return self.names.get(bundle_id) or built_in_name(bundle_id)

    def category(self, bundle_id: str) -> str:
        """The owner's category, else the built-in one, else a hint in the id, else `other`."""
        found = self.categories.get(bundle_id)
        if found is not None:
            return found
        built_in = BUILT_IN.get(bundle_id)
        if built_in is not None:
            return built_in[1]
        lowered = bundle_id.casefold()
        return next((category for word, category in HINTS if word in lowered), OTHER)


def built_in_name(bundle_id: str) -> str | None:
    found = BUILT_IN.get(bundle_id)
    return found[0] if found else None


def apps_path(root: Path) -> Path:
    return Path(root).joinpath(*APPS_FILE.parts)


def read(root: Path) -> Apps:
    """The owner's table from `policy/apps.json` over the built-in one; the built-in one alone when
    the file does not exist. Nothing is written. A file that is not `{bundle id: category |
    {name?, category?}}`, or names a category outside `CATEGORIES`, raises PolicyError naming it."""
    path = apps_path(root)
    if not path.exists():
        return Apps()
    shape = (
        f'{path} must be {{"<bundle id>": "<category>" | {{"name": "...", "category": "..."}}, ...}}'
        f" with a category among {', '.join(CATEGORIES)}"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise PolicyError(shape)
    names: dict[str, str] = {}
    categories: dict[str, str] = {}
    for bundle_id, entry in data.items():
        if not isinstance(bundle_id, str) or not bundle_id.strip():
            raise PolicyError(shape)
        if isinstance(entry, str):
            entry = {"category": entry}
        if not isinstance(entry, dict):
            raise PolicyError(shape)
        name: Any = entry.get("name")
        category: Any = entry.get("category")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise PolicyError(shape)
            names[bundle_id] = name.strip()
        if category is not None:
            if category not in CATEGORIES:
                raise PolicyError(shape)
            categories[bundle_id] = category
    return Apps(names, categories)
