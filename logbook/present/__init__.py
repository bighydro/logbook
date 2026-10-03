"""Who was with the owner at a stay: the "with" module.

For one stay (`stays.Segment`) and the lines of its window, `present` lists each person present
with a confidence, a status and the reason, one entry per piece of evidence; `company` merges
them per person. The sources, in the order a Day lists them:

| source       | what                                                            | status    | confidence |
|--------------|-----------------------------------------------------------------|-----------|------------|
| `circle`     | a page another member of the circle shared (not built yet)      | confirmed | —          |
| `calendar`   | an attendee of a timed `event/v1` held at the stay **            | confirmed | 0.8, 0.6 * |
| `calendar`   | an attendee of an all-day `event/v1` located at the stay **     | proposed  | 0.3        |
| `transcript` | a participant of a `transcript/v1` recorded inside the stay *** | confirmed | 0.9        |
| `note`       | a `note/v1` written inside the stay that says "with <name>" *** | confirmed | 1.0        |
| `photo`      | a face the library tagged in a `photo/v1` taken inside the stay | proposed  | 0.5        |

* 0.8 for an attendee who accepted, 0.6 for one who has not answered or is tentative; one who
declined is not listed.

** An all-day event places nobody, unless it is located at the stay (below): then its attendees
are proposed only, at `ALL_DAY`, since the entry still names no hour. A timed event is held at
the stay when its location geocodes
within `EVENT_INSIDE_M` of the stay's centre — coordinates under `extra.location`, or a `location`
that is the name of a place in places.json — or when it has no location and overlaps the stay by
more than `EVENT_OVERLAP_S`. A located event the record cannot place does not count: a meeting
elsewhere that the owner joined from the hotel is not company. An attendee that does not resolve
and has no display name is a bare address and is dropped, and a calendar system address
(`@calendar.google.com`, `noreply`, `reservations@`, `invite@`) is never a person.

*** Only a participant the record resolves to a person: by email, phone or provider id, else by
the spoken name matching a label. A diarization label (`Speaker A`), `me`, `them`, `Unknown` or
a name no resolution knows is not company. A note's name follows the same rule: "with Ola" names
Ola Nordmann when a resolution line gives a person that label (`_by_name`); "with US", "with
XYZ", a country, an acronym or a name the record does not know names nobody.

Confirmed is what the calendar, a recording or the owner's own words say; a face is a library's
guess and stays proposed until the owner says otherwise, and so are the attendees of an all-day
entry located at the stay: it names no hour. Names resolve through the record's resolution lines
(RFC 0006, `resolve.identities_from`): an email, a phone number or a library's person id
(`provider_id`, `<library>:<id>`) to the person it names; a bare name in a transcript or a note to
the person whose label it is; a name that resolves to no person is dropped, in a note as in a
transcript. The owner is never listed as their own company: evidence
carrying one of the owner's own refs (`owner`, the addresses `logbook.json` lists under
`owner_emails`) is dropped. Nothing here reads a file or writes a line.

The package follows the table: one module per source (`circle`, `calendar`, `transcript`, `notes`,
`photos`), `company` for `present` and `company`, `model` for the dataclasses and the constants,
`owner` for the owner's identities, `evidence` for a window's lines by day and the span rules,
`names` for the lookups through the resolution lines. Everything is re-exported here, so
`present.<name>` is the whole module as before; a new source is a new module and a line in
`company.FROM`."""

from __future__ import annotations

from .calendar import (
    EVENT_INSIDE_M,
    EVENT_OVERLAP_S,
    SYSTEM_ADDRESS,
    _event_coordinates,
    _held_at,
    _system_address,
    from_calendar,
)
from .circle import from_circle
from .company import FROM, company, present
from .evidence import Evidence, _inside, _overlap_s, _overlaps
from .model import (
    ACCEPTED,
    ALL_DAY,
    CONFIRMED,
    EVIDENCE_KINDS,
    NOTE,
    PERSON_TYPES,
    PHOTO,
    PROPOSED,
    SOURCES,
    TENTATIVE,
    TRANSCRIPT,
    Companion,
    Presence,
)
from .names import _by_name, _normal, _ref, _resolve, by_name, resolve_ref
from .notes import AND, NAME, WITH, from_notes
from .owner import Owner, owner_of
from .photos import from_photos
from .transcript import from_transcript

__all__ = [
    "ACCEPTED",
    "ALL_DAY",
    "AND",
    "CONFIRMED",
    "EVENT_INSIDE_M",
    "EVENT_OVERLAP_S",
    "EVIDENCE_KINDS",
    "FROM",
    "NAME",
    "NOTE",
    "PERSON_TYPES",
    "PHOTO",
    "PROPOSED",
    "SOURCES",
    "SYSTEM_ADDRESS",
    "TENTATIVE",
    "TRANSCRIPT",
    "WITH",
    "Companion",
    "Evidence",
    "Owner",
    "Presence",
    "_by_name",
    "_event_coordinates",
    "_held_at",
    "_inside",
    "_normal",
    "_overlap_s",
    "_overlaps",
    "_ref",
    "_resolve",
    "_system_address",
    "by_name",
    "company",
    "from_calendar",
    "from_circle",
    "from_notes",
    "from_photos",
    "from_transcript",
    "owner_of",
    "present",
    "resolve_ref",
]
