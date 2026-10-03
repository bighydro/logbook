"""Google Takeout: one archive, several witnesses (ADR 0008).

Each Takeout product is its own sub-adapter in this package, registered under its own NAME and
sharing `SOURCE` for the lines it writes:

    location.py   Location History — Records.json and the on-device Timeline.json → location/v1
    calendar.py   Calendar/ — one plain .ics per calendar; a thin sibling that hands the folder to
                  the `ics` adapter → event/v1, under that adapter's own NAME and source, not SOURCE
    photos.py     Google Photos — the album folders and their JSON sidecars → photo/v1
    keep.py       Keep/ — one JSON per note, attachments beside → note/v1
    tasks.py      Tasks/ — Tasks.json, every list and task → task/v1
    chrome.py     Chrome/ — History.json and Bookmarks.html → browse/v1
    youtube.py    YouTube and YouTube Music/history/ — watch and search history → watch/v1
    pay.py        Google Pay/ — the transactions CSV → transaction/v1; the passes that are tickets → event/v1
    chat.py       Google Chat/ — Groups/<conversation>/messages.json → message/v1
    meet.py       Google Meet/ — the call history CSV → call/v1
    access_log.py Access Log Activity/ — every access to a Google service → event/v1, tier 3 (off by default)
    activity.py   My Activity/ — searches, visited results and apps opened → browse/v1; YouTube → watch/v1
                  through youtube.py's own mapping (off by default)
    contacts.py   Contacts/ — the vCards → resolution/v1, merged with the people the record resolves
    maps.py       Maps (your places)/ — Reviews.json → highlight/v1; Saved Places.json never lines, but
                  candidates for `places propose --takeout` (with places.py, the `Saved/` CSV lists)
    home.py       Home App/ — HomeHistory.json: arrivals, departures and the alarm → event/v1
    fit.py        Fit/ — All Data/ streams, All Sessions/ workouts, Daily activity metrics/ CSVs →
                  health-sample/v1, tier 3
    times.py      the three clocks Takeout writes, read to one UTC instant (shared)

Every sub-adapter answers to `takeout-<name>` as well as `google-takeout-<name>` (`adapters.TAKEOUT`,
`ALIASES`). `docs/adapters/takeout.md` is the owner's page.

Folder dispatch (roadmap): a whole unzipped Takeout folder handed to `logbook add` is walked file
by file today, because `add` already processes a folder's files and each sub-adapter sniffs its
own; a folder that a sub-adapter claims as a whole (`Google Photos/`, or the root that holds it) is
handed to that sub-adapter instead of being walked. This package will grow a `walk(folder)` that
knows the Takeout layout (`Takeout/<Product>/...`) and dispatches each file to the matching
sub-adapter without sniffing every file, and a `zip` reader so the archive never has to be
unpacked. Neither exists yet.
"""

from __future__ import annotations

SOURCE = "google-takeout"
SUB_ADAPTERS = (
    "location",
    "calendar",
    "photos",
    "keep",
    "tasks",
    "chrome",
    "youtube",
    "pay",
    "chat",
    "meet",
    "access_log",
    "activity",
    "contacts",
    "maps",
    "home",
    "fit",
)
