"""`logbook.present`, the "with" module: who was present at a stay, with a confidence and a reason,
from calendar attendees, transcript speakers, a note that says "with <name>", and faces in photos
(proposed only). Names resolve through the record's resolution lines. Synthetic persona; pure."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import (
    KARI,
    KARI_ID,
    OLA,
    OLA_ID,
    attendee,
    event,
    note,
    persona_record,
    photo,
    resolution,
    transcript,
)

from logbook import present, reading, resolve, stays


def _stay(start: str, end: str, place: str | None = "Office", aboard: str | None = None) -> stays.Segment:
    return stays.Segment(
        kind=stays.STAY,
        subject=None,
        start=datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC),
        end=datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(UTC),
        points=10,
        lat=59.91,
        lon=10.76,
        place=place,
        aboard=aboard,
        first_line="first",
        last_line="last",
    )


def _lines(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**d, "id": f"line-{i}", "seq": i + 1, "end": d.get("end")} for i, d in enumerate(drafts)]


IDENTITIES = resolve.identities_from(
    _lines(
        [
            resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
            resolution(("provider_id", f"immich:{KARI['face']}"), KARI_ID, "Kari Nordmann"),
            resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
            resolution(("phone", OLA["phone"]), OLA_ID, "Ola Nordmann"),
        ]
    )
)
STAY = _stay("2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")


def test_a_calendar_attendee_of_an_overlapping_event_is_confirmed() -> None:
    lines = _lines(
        [
            event(
                "2026-06-10T10:30:00Z",
                "2026-06-10T12:30:00Z",
                "Lunch",
                [attendee(KARI["email"], "Kari Nordmann")],
            ),
            event("2026-06-10T13:00:00Z", "2026-06-10T14:00:00Z", "Later", [attendee(OLA["email"])]),  # after
            event(
                "2026-06-10T10:00:00Z",
                "2026-06-10T11:30:00Z",
                "Call",
                [attendee(OLA["email"], response="declined")],
            ),
        ]
    )
    [kari] = present.present(STAY, lines, IDENTITIES)
    assert kari.person == KARI_ID and kari.name == "Kari Nordmann"
    assert kari.status == present.CONFIRMED and kari.source == "calendar"
    assert kari.confidence == 0.8 and "Lunch" in kari.reason and kari.line == "line-0"


def test_a_tentative_attendee_counts_for_less_and_an_unresolved_bare_address_is_dropped() -> None:
    lines = _lines(
        [
            event(
                "2026-06-10T10:00:00Z",
                "2026-06-10T11:30:00Z",
                "Standup",
                [
                    attendee(KARI["email"], response="tentative"),
                    attendee("nobody@example.org", response="none"),
                    attendee("guest@example.org", "A Guest", response="none"),
                ],
            )
        ]
    )
    kari, guest = present.present(STAY, lines, IDENTITIES)
    assert kari.confidence == 0.6
    assert guest.person is None and guest.name == "A Guest", "an unresolved attendee with a name is kept"


def test_an_all_day_event_puts_nobody_at_a_stay() -> None:
    lines = _lines(
        [
            event(
                "2026-06-09T22:00:00Z",
                "2026-06-10T22:00:00Z",
                "Conference",
                [attendee(KARI["email"], "Kari Nordmann")],
                all_day=True,
            )
        ]
    )
    assert present.present(STAY, lines, IDENTITIES) == []


def test_a_timed_event_located_inside_the_stay_puts_its_attendees_there() -> None:
    inside = {"location": "Office", "extra": {"location": {"latitude": 59.9105, "longitude": 10.7605}}}
    away = {"location": "Elsewhere", "extra": {"location": {"latitude": 59.95, "longitude": 10.76}}}  # 4.4 km
    lines = _lines(
        [
            event(
                "2026-06-10T11:30:00Z", "2026-06-10T12:00:00Z", "Coffee", [attendee(KARI["email"])], **inside
            ),
            event(
                "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z", "Elsewhere", [attendee(OLA["email"])], **away
            ),
        ]
    )
    [kari] = present.present(STAY, lines, IDENTITIES)
    assert kari.person == KARI_ID and kari.reason == "attendee of Coffee"


def test_a_located_event_geocodes_through_the_named_places_and_an_unknown_location_does_not_count() -> None:
    from logbook.places import Place

    places = [Place("Office", 59.91, 10.76, 120), Place("Cafe", 59.92, 10.74, 120)]
    lines = _lines(
        [
            event(
                "2026-06-10T11:30:00Z",
                "2026-06-10T12:00:00Z",
                "Coffee",
                [attendee(KARI["email"])],
                location="office",
            ),
            event(
                "2026-06-10T11:30:00Z",
                "2026-06-10T12:00:00Z",
                "Tea",
                [attendee(OLA["email"])],
                location="Cafe",
            ),
            event(
                "2026-06-10T10:00:00Z",
                "2026-06-10T12:00:00Z",
                "Somewhere",
                [attendee(OLA["email"])],
                location="Room 4",
            ),
        ]
    )
    [kari] = present.present(STAY, lines, IDENTITIES, places=places)
    assert kari.person == KARI_ID, "a location that names a place in places.json geocodes to it, case aside"


def test_an_event_without_a_location_needs_more_than_an_hour_of_overlap() -> None:
    lines = _lines(
        [
            event(
                "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z", "Short", [attendee(KARI["email"])]
            ),  # 60 min
            event("2026-06-10T10:00:00Z", "2026-06-10T11:01:00Z", "Long", [attendee(OLA["email"])]),  # 61 min
        ]
    )
    [ola] = present.present(STAY, lines, IDENTITIES)
    assert ola.person == OLA_ID and ola.reason == "attendee of Long"


def test_calendar_system_addresses_are_never_people() -> None:
    lines = _lines(
        [
            event(
                "2026-06-10T10:00:00Z",
                "2026-06-10T12:00:00Z",
                "Booking",
                [
                    attendee("abc123@group.calendar.google.com", "Team Calendar"),
                    attendee("noreply@example.org", "Example Hotel"),
                    attendee("no-reply@example.org", "Example Hotel"),
                    attendee("reservations@example.org", "Example Hotel"),
                    attendee("invite@example.org", "Example Hotel"),
                    attendee(OLA["email"]),
                ],
            )
        ]
    )
    [ola] = present.present(STAY, lines, IDENTITIES)
    assert ola.person == OLA_ID


def test_a_speaker_in_a_transcript_recorded_inside_the_stay_is_confirmed() -> None:
    lines = _lines(
        [
            transcript(
                "2026-06-10T10:15:00Z",
                "2026-06-10T10:45:00Z",
                "Boat plans",
                [
                    {"name": "Ola Nordmann", "email": OLA["email"]},
                    {"name": "Kari Nordmann"},
                    {"name": "A Stranger"},
                ],
            ),
            transcript("2026-06-10T13:00:00Z", "2026-06-10T13:30:00Z", "Later", [{"email": OLA["email"]}]),
        ]
    )
    ola, kari = present.present(STAY, lines, IDENTITIES)
    assert (ola.person, ola.source, ola.status, ola.confidence) == (
        OLA_ID,
        "transcript",
        present.CONFIRMED,
        0.9,
    )
    assert kari.person == KARI_ID, "a bare name matches a label"
    assert "Boat plans" in ola.reason


def test_a_transcript_speaker_counts_only_when_resolved_to_a_person() -> None:
    lines = _lines(
        [
            transcript(
                "2026-06-10T10:15:00Z",
                "2026-06-10T10:45:00Z",
                "Standup",
                [
                    {"name": "Speaker A"},
                    {"name": "me"},
                    {"name": "them"},
                    {"name": "Unknown"},
                    {"name": "A Stranger"},
                    {"name": "Speaker B", "email": "nobody@example.org"},
                    {"name": "Speaker C", "email": OLA["email"]},
                ],
            )
        ]
    )
    [ola] = present.present(STAY, lines, IDENTITIES)
    assert ola.person == OLA_ID, "a diarization label resolves through its address"
    assert ola.name == "Ola Nordmann"


def test_a_note_that_says_with_someone_is_a_declaration() -> None:
    lines = _lines(
        [
            note("2026-06-10T11:00:00Z", "Anchored in the bay with Ola Nordmann and Kari. Grilled."),
            note("2026-06-10T11:10:00Z", "Lunch with Trude at the cafe"),
            note("2026-06-10T11:20:00Z", "nothing to do with anyone"),
            note("2026-06-10T14:00:00Z", "with Ola"),  # after the stay
        ]
    )
    found = present.present(STAY, lines, IDENTITIES)
    assert [(p.person, p.name) for p in found] == [
        (OLA_ID, "Ola Nordmann"),
        (KARI_ID, "Kari Nordmann"),
        (None, "Trude"),
    ]
    assert all(p.source == "note" and p.status == present.CONFIRMED and p.confidence == 1.0 for p in found)
    assert found[2].reason == "note says with Trude"


def test_a_face_in_a_photo_is_only_proposed() -> None:
    lines = _lines(
        [
            photo("2026-06-10T11:00:00Z", people=[KARI["face"], "p_99"]),
            photo("2026-06-10T11:30:00Z", people=[]),
            photo("2026-06-10T13:00:00Z", people=[KARI["face"]]),  # after
        ]
    )
    kari, unknown = present.present(STAY, lines, IDENTITIES)
    assert (kari.person, kari.status, kari.source, kari.confidence) == (
        KARI_ID,
        present.PROPOSED,
        "photo",
        0.5,
    )
    assert kari.ref == ("provider_id", f"immich:{KARI['face']}")
    assert unknown.person is None and unknown.name == "immich:p_99"


def test_the_circle_page_is_a_stub_that_names_nobody_yet() -> None:
    assert present.from_circle(STAY, [], IDENTITIES) == []
    assert "circle" in present.SOURCES


def test_company_merges_a_person_across_sources_confirmed_first() -> None:
    lines = _lines(
        [
            photo("2026-06-10T11:00:00Z", people=[KARI["face"]]),
            event("2026-06-10T10:30:00Z", "2026-06-10T12:30:00Z", "Lunch", [attendee(KARI["email"])]),
            note("2026-06-10T11:40:00Z", "with Ola"),
            photo("2026-06-10T11:50:00Z", people=["p_99"]),
        ]
    )
    people = present.company(STAY, lines, IDENTITIES)
    assert [(p.person, p.status) for p in people] == [
        (OLA_ID, present.CONFIRMED),
        (KARI_ID, present.CONFIRMED),
        (None, present.PROPOSED),
    ]
    kari = people[1]
    assert kari.confidence == 0.8 and kari.sources == ("calendar", "photo") and len(kari.lines) == 2
    assert kari.to_json()["reasons"] == ["attendee of Lunch", "face in IMG_101100.HEIC"]


def test_on_the_persona_the_office_stay_has_ola_and_the_cafe_has_kari(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    read = reading.read(lb, "2026-06-10", "2026-06-14")
    cafe = next(s for s in read.owner_stays if s.start.astimezone(read.tz).strftime("%d %H:%M") == "10 12:00")
    [kari] = present.company(cafe, read.lines, read.identities)
    assert (
        kari.person == KARI_ID and kari.status == present.CONFIRMED and kari.sources == ("calendar", "photo")
    )
    office = next(
        s for s in read.owner_stays if s.place == "Office" and s.start.astimezone(read.tz).day == 11
    )
    [ola] = present.company(office, read.lines, read.identities)
    assert ola.person == OLA_ID and ola.sources == ("transcript",)
    fjord = next(s for s in read.owner_stays if s.aboard == "solvind" and s.duration_s > 20 * 3600)
    [ola] = present.company(fjord, read.lines, read.identities)
    assert ola.sources == ("note",) and ola.status == present.CONFIRMED


def test_an_all_day_events_attendees_are_only_proposed() -> None:
    """An all-day entry located at the stay names its attendees, but no hour: they are proposed, not
    confirmed (the Day's rule: timed and held at the stay confirms, all-day proposes). One with no
    location overlaps every stay of its day and places nobody (the test above)."""
    lines = _lines(
        [
            event(
                "2026-06-09T22:00:00Z",
                "2026-06-10T22:00:00Z",
                "Kari in town",
                [attendee(KARI["email"], "Kari Nordmann")],
                all_day=True,
                location="Office",
                extra={"location": {"latitude": 59.9105, "longitude": 10.7605}},
            ),
        ]
    )
    [kari] = present.present(STAY, lines, IDENTITIES)
    assert kari.status == present.PROPOSED and kari.source == "calendar"
    assert kari.confidence == present.ALL_DAY and "all day" in kari.reason


def test_the_owners_address_in_logbook_json_is_never_their_own_company() -> None:
    """`owner_emails` alone, with no resolution line for the owner, is enough to drop them."""
    lines = _lines(
        [
            event(
                "2026-06-10T10:00:00Z",
                "2026-06-10T11:30:00Z",
                "Standup",
                [attendee(KARI["email"], "Kari Nordmann"), attendee("ines@example.org", "Ines Nordmann")],
            )
        ]
    )
    owner = present.owner_of("owner-id", ["ines@example.org"], {}, IDENTITIES)
    [kari] = present.present(STAY, lines, IDENTITIES, owner=owner)
    assert kari.person == KARI_ID
    [kari] = present.company(STAY, lines, IDENTITIES, owner=owner)
    assert kari.person == KARI_ID


# -- the owner ---------------------------------------------------------------------------------------------

INES_ID = "019cadd3-6bc0-7dcd-9133-000000000003"  # the persona herself, whose record this is
INES = {"email": "ines@example.org"}
WITH_INES = resolve.identities_from(
    _lines(
        [
            resolution(("email", INES["email"]), INES_ID, "Ines Nordmann"),
            resolution(("phone", "+4790000003"), INES_ID, "I. Nordmann"),
            resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        ]
    )
)
EVIDENCE = [
    event(
        "2026-06-10T10:00:00Z",
        "2026-06-10T12:00:00Z",
        "Dinner",
        [attendee(INES["email"]), attendee(OLA["email"])],
    ),
    transcript(
        "2026-06-10T10:15:00Z", "2026-06-10T10:45:00Z", "Plans", [{"name": "I. Nordmann"}, {"name": "Ola"}]
    ),
    note("2026-06-10T11:00:00Z", "with Ola Nordmann and Nordmann"),
]


def test_the_owner_is_never_their_own_company() -> None:
    owner = present.owner_of(INES_ID, [], {}, WITH_INES)
    assert owner.entities == {INES_ID}
    assert owner.refs == {("email", INES["email"]), ("phone", "+4790000003")}
    assert owner.names == {"ines nordmann", "i. nordmann"}, "every label the owner's refs carry"
    found = present.present(STAY, _lines(EVIDENCE), WITH_INES, owner=owner)
    assert INES_ID not in {p.person for p in found}
    assert not {p.name for p in found} & {"Ines Nordmann", "I. Nordmann", "ines@example.org"}
    assert [c.name for c in present.company(STAY, _lines(EVIDENCE), WITH_INES, owner=owner)] == [
        "Ola Nordmann",
        "Nordmann",
    ]


def test_the_owner_is_found_from_their_addresses_and_policy_aliases() -> None:
    by_address = present.owner_of("unresolved-owner-id", [INES["email"]], {}, WITH_INES)
    assert by_address.entities == {"unresolved-owner-id", INES_ID}, "owner_emails lead to the resolved person"
    assert by_address.refs == {("email", INES["email"]), ("phone", "+4790000003")}
    aliases = {"names": ["Nordmann"], "emails": [], "phones": ["+4790000003"]}
    by_policy = present.owner_of("unresolved-owner-id", [], aliases, WITH_INES)
    assert INES_ID in by_policy.entities and "nordmann" in by_policy.names
    found = present.company(STAY, _lines(EVIDENCE), WITH_INES, owner=by_policy)
    assert [c.name for c in found] == ["Ola Nordmann"], "the note's unresolved alias is the owner too"
