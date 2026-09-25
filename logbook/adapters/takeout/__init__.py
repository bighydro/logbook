"""Google Takeout: one archive, several witnesses (ADR 0008).

Each Takeout product is its own sub-adapter in this package, registered under its own NAME and
sharing `SOURCE` for the lines it writes:

    location.py   Location History — Records.json and the on-device Timeline.json → location/v1
    photos.py     Google Photos — the album folders and their JSON sidecars → photo/v1

Planned siblings, one file each: calendar, activity.

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
SUB_ADAPTERS = ("location", "photos")
