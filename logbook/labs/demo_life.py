"""`logbook demo --years N --seed S --out DIR`: the Oslo persona's whole life, invented here.

Ines Nordmann, who does not exist, is born `N` years before the day after `TODAY`, the last day of
the default month, and the record runs from her birth to that day. Her life has phases, by age,
that change the shape of the data:

- childhood (0 to 5), in Bergen: sparse. Scanned photos, a few family events, and stories told about
  her by her sister Kari and by Ola, the boy from across the street. No track, no phone.
- school (6 to 18): the calendar fills (practice every week, the class trip, friends' birthdays), the
  friends Mia and Jens appear; from 14 a phone, so a thin track (three points a day, more on a trip),
  texts, calls, the first flights (declared, from memory: a package holiday every other summer),
  and the family's weeks at the cabin become trips.
- university (19 to 23), in Copenhagen: lectures three times a week, Hanna and Freja, mail, a term in
  Barcelona (the first long trip), Christmas flights home.
- work (24 on): meetings, a monthly transcript, mail three times a week, Zürich for a client twice a
  year, a month in Lisbon at 28; the flight tracker from 30; Ola comes back at 29; the move from
  Copenhagen to Oslo at 32 (the office, the cabin weekends, the Copenhagen visits to Freja); the
  watch at 34, so health data starts there; the boat at 35, with a summer cruise every July and the
  boat's own AIS track; three weeks in Rome at 37.
- the last month, June 2026, is the default month's story at the phone's full resolution, when the
  life is long enough to have the boat (36 years or more); earlier years are thin, as a re-import of
  old exports would be.

People drift in and out: Mia and Jens stop after school (one call, one last message), the
grandmother Solveig is in the photos until Ines is 27, Hanna writes once more at 33, Ola is in the
childhood photos, absent through the university years and back for good at 29. Everything is made
up in this module and `logbook.contrib.demo`, nothing is read from anywhere, and the record is a function
of (`years`, `seed`): the same arguments give the same chain head on any machine."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from ..contrib import demo
from ..contrib.demo import (
    ANDERS,
    BAY_A,
    BERTH,
    BOAT,
    BOAT_DAYS,
    CABIN,
    CARRIER,
    COPENHAGEN,
    CPH,
    CYCLE,
    DAY_TYPES,
    EVA,
    FREJA,
    HOME,
    JONAS,
    KARI,
    LIV,
    MARINA,
    MARTA,
    NILS,
    OFFICE,
    OLA,
    OSL,
    OSLO,
    OWNER,
    OWNER_DAYS,
    PER,
    QUOTES,
    SIGRID,
    ZH_CLIENT,
    ZH_HOTEL,
    ZRH,
    ZURICH,
    Leg,
    Move,
    Person,
    Spot,
    Stay,
    _chat,
    _local,
    _stamp,
    _Story,
    _utc,
)
from ..core import flights, keepers
from ..core.store import Logbook

TODAY = date(2026, 6, 30)  # the last day of the default month; a life ends where the month does

# -- the ages at which the life changes shape ---------------------------------------------------------------

SCHOOL_AGE = 6
PHONE_AGE = 14  # a phone: a thin track, texts, calls, the first flights
STUDENT_AGE = 19  # the move to Copenhagen
WORK_AGE = 24
OLA_BACK_AGE = 29
TRACKER_AGE = 30  # flights tracked by the app from here; declared from memory before
MOVE_AGE = 32  # the move to Oslo, in the autumn of this year of her life
WATCH_AGE = 34  # health data starts with the watch
BOAT_AGE = 35
FULL_MONTH_FROM = BOAT_AGE + 1  # a life this long ends with the default month at full resolution
GRANDMOTHER_UNTIL = 27  # Solveig is in the photos until this age
MIA_LAST_CALL, MIA_LAST_MESSAGE, HANNA_WRITES_AGAIN = 21, 24, 33
BARCELONA_AGE, LONDON_AGE, LISBON_AGE, ROME_AGE = 21, 22, 28, 37
HOLIDAY_ABROAD = {14: "PMI", 16: "LHR", 18: "BCN"}  # the package holiday every other summer


def birthday(years: int, age: int = 0) -> date:
    """The birth day of a life of `years` — the day after TODAY, `years` earlier, so the record ends
    on the eve of a birthday — or the `age`th birthday of that life."""
    first = TODAY + timedelta(days=1)
    return date(first.year - years + age, first.month, first.day)


# -- the places and the cast --------------------------------------------------------------------------------

MADRID, LONDON, LISBON, ROME = "Europe/Madrid", "Europe/London", "Europe/Lisbon", "Europe/Rome"
BG_HOME = Spot("the family home", 60.3913, 5.3221, OSLO)
BG_SCHOOL = Spot("the school", 60.3860, 5.3330, OSLO)
BG_CABIN = Spot("the family cabin", 60.6300, 6.4200, OSLO)
BGO = Spot("BGO", 60.2934, 5.2181, OSLO)
CPH_FLAT = Spot("the Copenhagen flat", 55.6800, 12.5700, COPENHAGEN)
CPH_UNI = Spot("the university", 55.6640, 12.5880, COPENHAGEN)
CPH_OFFICE = Spot("the Copenhagen office", 55.6760, 12.5850, COPENHAGEN)
PMI = Spot("PMI", 39.5517, 2.7388, MADRID)
PMI_HOTEL = Spot("the Mallorca hotel", 39.5400, 2.6500, MADRID)
LHR = Spot("LHR", 51.4707, -0.4599, LONDON)
LONDON_HOTEL = Spot("the London hotel", 51.5150, -0.1300, LONDON)
BCN = Spot("BCN", 41.2971, 2.0785, MADRID)
BCN_ROOM = Spot("the Barcelona room", 41.3900, 2.1700, MADRID)
LIS = Spot("LIS", 38.7813, -9.1359, LISBON)
LIS_FLAT = Spot("the Lisbon flat", 38.7100, -9.1400, LISBON)
FCO = Spot("FCO", 41.8045, 12.2520, ROME)
ROME_FLAT = Spot("the Rome flat", 41.8950, 12.4800, ROME)
AIRPORTS = {s.name: s for s in (BGO, OSL, CPH, ZRH, PMI, LHR, BCN, LIS, FCO)}
CITY = {
    "BGO": "Bergen",
    "OSL": "Oslo",
    "CPH": "Copenhagen",
    "ZRH": "Zürich",
    "PMI": "Palma",
    "LHR": "London",
    "BCN": "Barcelona",
    "LIS": "Lisbon",
    "FCO": "Rome",
}
# the airline XY's routes: (first airport, second) -> (the flight number out, minutes in the air);
# the flight back is the next number
ROUTES = {
    ("BGO", "PMI"): ("611", 220),
    ("BGO", "LHR"): ("621", 125),
    ("BGO", "BCN"): ("631", 205),
    ("BGO", "CPH"): ("641", 85),
    ("CPH", "BCN"): ("651", 180),
    ("CPH", "LHR"): ("661", 115),
    ("CPH", "ZRH"): ("671", 110),
    ("CPH", "LIS"): ("681", 230),
    ("OSL", "BGO"): ("701", 55),
    ("OSL", "FCO"): ("711", 190),
    ("OSL", "ZRH"): ("561", 135),  # the default month's flights
    ("OSL", "CPH"): ("571", 70),
}
HOME_AIRPORT = {BG_HOME: BGO, CPH_FLAT: CPH, HOME: OSL}

SOLVEIG = Person("Solveig Nordmann", "solveig.nordmann@example.org", "+447700900013", "f_13")  # grandmother
MIA = Person("Mia Strand", "mia.strand@example.org", "+447700900014", "f_14")  # a school friend
JENS = Person("Jens Lie", "jens.lie@example.org", "+447700900015")  # a school friend
HANNA = Person("Hanna Dale", "hanna.dale@example.org", "+447700900016", "f_16")  # a university friend
BJORN = Person("Bjørn Aas", "bjorn.aas@example.org", "+447700900017")  # the first boss
PEOPLE = (*demo.PEOPLE, SOLVEIG, MIA, JENS, HANNA, BJORN)
FAMILY = (EVA, KARI)

PLACES: dict[Spot, dict[str, Any]] = {
    BG_HOME: {"radius_m": 120, "kind": "home", "country": "NO", "tags": ["family"]},
    BG_CABIN: {"radius_m": 200, "kind": "other", "tags": ["mountains"]},
}
PLACES_FROM: list[tuple[int, Spot, dict[str, Any]]] = [  # named once the life reaches the age
    (STUDENT_AGE, CPH_FLAT, {"radius_m": 120, "kind": "home", "country": "DK"}),
    (WORK_AGE, CPH_OFFICE, {"radius_m": 120, "kind": "other"}),
    (MOVE_AGE, HOME, demo.PLACES[HOME]),
    (MOVE_AGE, OFFICE, demo.PLACES[OFFICE]),
    (MOVE_AGE, CABIN, demo.PLACES[CABIN]),
    (BOAT_AGE, MARINA, demo.PLACES[MARINA]),
]

# -- the words ---------------------------------------------------------------------------------------------

STORIES = {  # by age: (the teller, what they tell)
    0: (KARI, "Ines came home in July and slept through the whole first night; Mum did not."),
    1: (KARI, "Her first word was 'båt', at the harbour, pointing. Nobody had taught her it."),
    2: (KARI, "She walked into the sea at the cabin in her boots and was furious it was wet."),
    3: (OLA, "The summer she was three she rang our bell every morning to ask if the cat was up."),
    4: (KARI, "Ines drew the fjord on the kitchen wall. Mum kept it for a year before painting."),
    5: (OLA, "She beat me at cards when she was five and I was seven, and told the whole street."),
}
DIARY = (
    "Practice was cold. Mia scored twice. Jens forgot his boots again.",
    "Kari borrowed my jumper without asking. Again.",
    "Rain. Read all afternoon. The book about the lighthouse.",
    "Ola says the harbour band plays on Saturday. We might go.",
    "Mum says the cabin needs a new roof before summer.",
    "Test tomorrow. I know nothing. I know everything. Both.",
)
TEEN_CHAT = (
    (MIA, "practice moved to six", "ok see you there"),
    (JENS, "did you do the maths?", "half of it. copy at lunch?"),
    (OLA, "band on saturday, coming?", "if mum lets me. probably."),
    (MIA, "the lighthouse book is so good", "told you!!"),
    (JENS, "cabin this weekend?", "yes, dad is driving at nine"),
)
LECTURES = ("Lecture: hydrology", "Lecture: statistics", "Seminar: coastal systems", "Lab: field methods")
STUDENT_CHAT = (
    (HANNA, "Library at ten?", "Ten. Bring the notes."),
    (FREJA, "Dinner at mine, the whole corridor", "I'll bring bread."),
    (KARI, "Mum asks if you're eating", "Tell her yes. Mostly."),
    (EVA, "Call on Sunday?", "Sunday at seven."),
    (HANNA, "Exam results are up", "Don't tell me. Tell me. No."),
    (FREJA, "Swim at the harbour baths after?", "Yes. It's freezing. Yes."),
)
STUDENT_MAIL = (
    (HANNA, "Notes from Tuesday", "Attached the notes you missed. The exam covers chapters 4 to 7.\n"),
    (FREJA, "Weekend", "Corridor dinner on Saturday, bring a chair if you have one.\n"),
    (HANNA, "Group work", "Draft is in the shared folder. Your part is the discussion.\n"),
)
STUDENT_NOTES = (
    "Lectures all morning, then the library until it closed. The harbour at dusk.",
    "Freja's corridor dinner; eleven people, one pot.",
    "Called home. Mum is well. The cabin roof is finally done.",
    "Statistics finally makes sense. Hanna explained it on a napkin.",
)
WORK_MAIL_CPH = (
    (BJORN, "Monday", "Planning at nine. Bring the numbers from last week.\n"),
    (FREJA, "Lunch?", "The place by the canal, twelve thirty.\n"),
    (MARTA, "Pilot timeline", "Kickoff in September, review in the spring. Agenda attached.\n"),
    (BJORN, "Client visit", "Zürich dates confirmed. Book the hotel by the river.\n"),
)
WORK_MAIL_OSLO = (
    (LIV, "Scope", "Attached the scope for the quarter. Comments by Friday.\n"),
    (MARTA, "Agenda", "Kickoff on the Tuesday, our office. Lunch after.\n"),
    (NILS, "Cabin", "The key is under the second stone. The road over the pass is open.\n"),
    (PER, "Review", "Review notes attached. Nothing blocking.\n"),
)
WORK_NOTES = (
    "Long day. The planning finally agreed on the scope.",
    "Walked home along the water. Thought about nothing.",
    "Quiet evening. Two chapters and early sleep.",
    "Rain all day. The office radiator finally fixed.",
    "Called Mum. She wants everyone at the cabin in July.",
)
FRIEND_CHAT = (
    (FREJA, "Canal walk at six?", "Six. I'll bring the dog's ball, no dog."),
    (KARI, "Did you see Mum's message?", "Yes. July at the cabin. I'll book the flight."),
    (FREJA, "The pilot is approved!", "Finally. Drinks on Friday."),
    (KARI, "Tromsø in the winter, imagine", "I'd rather not. Come to the cabin instead."),
)
JOURNEY_NOTES = {
    "family": "At the family cabin. Mum and Kari, the lake still cold, the stove lit by six.",
    "christmas": "Christmas at home in Bergen. Kari burnt the rice pudding; nobody minded.",
    "holiday": "Hotel by the beach. Kari read, Mum swam, I counted boats.",
    "client": "Zürich. The hotel by the river; the client at nine tomorrow.",
    "term": "Barcelona. The room is small and the light is enormous.",
    "london": "London with Hanna. Walked until the feet gave up.",
    "lisbon": "Lisbon for a month. Work from the flat in the mornings, the river after.",
    "rome": "Rome. Three weeks, one flat, no plan.",
}
MOVE_NOTES = {
    STUDENT_AGE: "Moved to Copenhagen. The flat is on the fourth floor; the bike is already stolen.",
    MOVE_AGE: "Moved to Oslo. Ola met me at the airport with the keys and bread.",
}
BOAT_NOTE = (
    f"Bought the boat. {demo.BOAT_NAME}, at the marina from today. Ola says she needs a new bilge pump."
)
WATCH_NOTE = "A watch. It counts my steps and watches me sleep; the record starts keeping both."
NOTE_FILES = {
    "christmas": "Christmas Eve. Snow by the afternoon, for once. The whole family round the table.\n",
}


# -- the life -----------------------------------------------------------------------------------------------


class Journey(NamedTuple):
    """Days away from the home of the time: the out day, `nights` nights at `lodging`, and the
    return day. By flight from the home's airport to `airport` (then `drive_min` to the lodging),
    or by car when `airport` is None. `story` replays the default month's day types instead, one
    per day of the journey (the Oslo years' Zürich, Copenhagen, cabin and cruise)."""

    start: date
    nights: int
    lodging: Spot
    kind: str
    airport: Spot | None = None
    drive_min: int = 30
    people: tuple[Person, ...] = ()
    title: str = ""
    story: tuple[int, ...] = ()

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.nights)


class Life:
    """The ages and dates of one life of `years`: which phase a day is in, where home is, what she
    has (a phone, a tracker, a watch, a boat)."""

    def __init__(self, years: int) -> None:
        if years < 1:
            raise ValueError("years must be at least 1")
        self.years = years
        self.birth = birthday(years)
        self.student_move = birthday(years, STUDENT_AGE) + timedelta(days=45)  # mid-August
        self.oslo_move = birthday(years, MOVE_AGE) + timedelta(days=92)  # the first of October
        self.watch_day = birthday(years, WATCH_AGE)
        self.boat_day = birthday(years, BOAT_AGE) + timedelta(days=14)
        self.full_month = years >= FULL_MONTH_FROM

    def age_on(self, day: date) -> int:
        age = day.year - self.birth.year
        if (day.month, day.day) < (self.birth.month, self.birth.day):
            age -= 1
        return age

    def home_on(self, day: date) -> Spot:
        if day >= self.oslo_move:
            return HOME
        if day >= self.student_move:
            return CPH_FLAT
        return BG_HOME

    def office_on(self, day: date) -> Spot | None:
        age = self.age_on(day)
        if age < SCHOOL_AGE:
            return None
        if age < STUDENT_AGE:
            return BG_SCHOOL
        if age < WORK_AGE:
            return CPH_UNI
        return OFFICE if self.home_on(day) is HOME else CPH_OFFICE

    def phase_on(self, day: date) -> str:
        age = self.age_on(day)
        if age < SCHOOL_AGE:
            return "child"
        if age < STUDENT_AGE:
            return "school"
        if age < WORK_AGE:
            return "student"
        return "work"

    def cadence_on(self, day: date) -> int | None:
        """Minutes between the phone's points on an ordinary day — a point per stay, so where she
        slept and where she spent the day, and a point every two hours in the last year — or None
        before the phone."""
        age = self.age_on(day)
        if age < PHONE_AGE:
            return None
        return 120 if age == self.years - 1 else 480

    def ola_around(self, day: date) -> bool:
        age = self.age_on(day)
        return 3 <= age < STUDENT_AGE or age >= OLA_BACK_AGE

    def places(self) -> dict[Spot, dict[str, Any]]:
        out = dict(PLACES)
        for age, spot, entry in PLACES_FROM:
            if self.years > age:
                out[spot] = entry
        return out


def _journeys(life: Life, rng: random.Random) -> dict[date, tuple[Journey, str]]:
    """Every day of every journey of the life, mapped to the journey and the day's part in it
    (`out`, `stay`, `back`); a journey that would overlap one already planned is dropped."""
    taken: dict[date, tuple[Journey, str]] = {}

    def add(journey: Journey) -> None:
        days = [journey.start + timedelta(days=i) for i in range(journey.nights + 1)]
        if any(d in taken or d > TODAY or (life.full_month and d >= demo.START) for d in days):
            return
        for i, d in enumerate(days):
            taken[d] = (journey, "out" if i == 0 else "back" if i == journey.nights else "stay")

    def to_bergen(start: date, nights: int, lodging: Spot, kind: str, title: str) -> None:
        home = life.home_on(start)
        airport = None if home is BG_HOME else BGO
        drive = 120 if lodging is BG_CABIN else 30
        add(Journey(start, nights, lodging, kind, airport, drive, FAMILY, title))

    for age in range(PHONE_AGE, life.years):
        b = birthday(life.years, age)
        at_home_in_bergen = age < STUDENT_AGE
        in_oslo = life.years > MOVE_AGE and b >= life.oslo_move
        # the family's weeks: the cabin in July, Easter in the mountains while at school, Christmas home
        to_bergen(b + timedelta(days=9), 7, BG_CABIN, "family", "Summer at the family cabin")
        if at_home_in_bergen:
            to_bergen(b + timedelta(days=270), 4, BG_CABIN, "family", "Easter at the cabin")
        else:
            to_bergen(b + timedelta(days=174), 5, BG_HOME, "christmas", "Christmas in Bergen")
        if age in HOLIDAY_ABROAD:
            airport = AIRPORTS[HOLIDAY_ABROAD[age]]
            hotel = {PMI: PMI_HOTEL, LHR: LONDON_HOTEL, BCN: BCN_ROOM}[airport]
            add(Journey(b + timedelta(days=20), 7, hotel, "holiday", airport, 40, FAMILY, "Holiday"))
        if age == BARCELONA_AGE:
            add(Journey(b + timedelta(days=193), 131, BCN_ROOM, "term", BCN, 45, (), "The Barcelona term"))
        if age == LONDON_AGE:
            add(Journey(b + timedelta(days=330), 5, LONDON_HOTEL, "london", LHR, 50, (HANNA,), "London"))
        if age == LISBON_AGE:
            add(Journey(b + timedelta(days=40), 34, LIS_FLAT, "lisbon", LIS, 35, (), "A month in Lisbon"))
        if age == ROME_AGE:
            add(Journey(b + timedelta(days=60), 20, ROME_FLAT, "rome", FCO, 45, (), "Three weeks in Rome"))
        if age >= 26:
            for offset in (75, 285):
                start = b + timedelta(days=offset)
                if in_oslo:
                    start -= timedelta(days=start.weekday())  # the story flies out on a Monday
                    add(Journey(start, 3, ZH_HOTEL, "client", story=(7, 8, 9, 10)))
                else:
                    add(Journey(start, 3, ZH_HOTEL, "client", ZRH, 30, (MARTA, JONAS), "Zürich"))
        if in_oslo:
            start = b + timedelta(days=110)
            start += timedelta(days=(3 - start.weekday()) % 7)  # a Thursday
            add(Journey(start, 2, demo.CPH_HOTEL, "story", story=(24, 25, 26)))
            if age >= BOAT_AGE:
                add(Journey(b + timedelta(days=21), 6, BAY_A, "story", story=tuple(range(14, 21))))
            saturdays = [b + timedelta(days=i) for i in range(365) if (b + timedelta(days=i)).weekday() == 5]
            for start in sorted(rng.sample(saturdays, 6)):
                add(Journey(start, 1, CABIN, "story", story=(5, 6)))
            if age >= WATCH_AGE:  # a run in the park with Tore every other Sunday
                for sunday in (saturday + timedelta(days=1) for saturday in saturdays[::2]):
                    add(Journey(sunday, 0, HOME, "story", story=(13,)))
    return taken


# -- the days -----------------------------------------------------------------------------------------------


def _hm(when: datetime, tz: str) -> str:
    return when.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _route(origin: Spot, destination: Spot) -> tuple[str, int]:
    """The flight number and minutes in the air between two airports the airline XY serves."""
    if (origin.name, destination.name) in ROUTES:
        return ROUTES[(origin.name, destination.name)]
    number, minutes = ROUTES[(destination.name, origin.name)]
    return str(int(number) + 1), minutes


def _flight(
    story: _Story, day: date, origin: Spot, destination: Spot, dep_clock: str, tracked: bool
) -> tuple[datetime, datetime]:
    """A calendar entry for the flight and its line: the tracker's (evidence `tracked`) once she
    has the app, else her own word (`declared`), as `logbook add flight` writes it. Returns the
    departure and arrival instants."""
    number, minutes = _route(origin, destination)
    dep_local = _local(day, dep_clock, origin.tz)
    arr_local = dep_local + timedelta(minutes=minutes)
    dep, arr = _stamp(dep_local), _stamp(arr_local)
    story.event(dep, arr, f"Flight to {CITY[destination.name]} (XY {number})", tz=origin.tz)
    k = (day.isoformat(), CARRIER, number)
    if tracked:
        draft = flights.build(
            source="flighty",
            raw_id=f"fx-{number}@{flights.digest(k)}",
            airports=story.airports,
            date=day.isoformat(),
            carrier=CARRIER,
            number=number,
            from_=flights.airport_ref(origin.name, story.airports),
            to=flights.airport_ref(destination.name, story.airports),
            aircraft={"type": "A320", "registration": "ZZ-ABC"},
            times={
                "scheduled_departure": dep,
                "scheduled_arrival": arr,
                "actual_departure": _stamp(dep_local + timedelta(minutes=story.rng.randint(2, 14))),
                "actual_arrival": _stamp(arr_local - timedelta(minutes=story.rng.randint(0, 9))),
            },
            extra={"seat": f"{story.rng.randint(4, 28)}{story.rng.choice('ACDF')}", "cabin": "economy"},
        )
    else:
        declared = (
            f"{CARRIER} {number} {origin.name} {destination.name} {day.isoformat()} passenger "
            f"{_hm(dep_local, origin.tz)}-{_hm(arr_local, destination.tz)}"
        )
        draft = flights.build(
            source="manual",
            raw_id=f"{flights.key_text(k)}@{flights.digest(declared)}",
            airports=story.airports,
            date=day.isoformat(),
            carrier=CARRIER,
            number=number,
            from_=flights.airport_ref(origin.name, story.airports),
            to=flights.airport_ref(destination.name, story.airports),
            times={"actual_departure": dep, "actual_arrival": arr},
            extra={"declared": declared},
        )
    story.drafts.append({"id": story.uuid7(dep), "recorded_at": story.recorded_at, **draft})
    return dep_local, arr_local


def _fly_out(
    home: Spot, origin: Spot, destination: Spot, lodging: Spot, dep: datetime, arr: datetime, drive_min: int
) -> list[Leg]:
    leave = dep - timedelta(hours=2)
    there = leave + timedelta(minutes=40)
    landed = arr + timedelta(minutes=35)
    arrived = landed + timedelta(minutes=drive_min)
    return [
        Stay("00:00", _hm(leave, home.tz), home),
        Move(_hm(leave, home.tz), _hm(there, origin.tz), home, origin, 6),
        Stay(_hm(there, origin.tz), _hm(dep, origin.tz), origin),
        Stay(_hm(arr, destination.tz), _hm(landed, destination.tz), destination),
        Move(_hm(landed, destination.tz), _hm(arrived, lodging.tz), destination, lodging, 6),
        Stay(_hm(arrived, lodging.tz), "24:00", lodging, 60),
    ]


def _fly_back(
    lodging: Spot, origin: Spot, destination: Spot, home: Spot, dep: datetime, arr: datetime, drive_min: int
) -> list[Leg]:
    there = dep - timedelta(hours=1, minutes=30)
    leave = there - timedelta(minutes=drive_min)
    landed = arr + timedelta(minutes=35)
    arrived = landed + timedelta(minutes=40)
    return [
        Stay("00:00", _hm(leave, lodging.tz), lodging, 60),
        Move(_hm(leave, lodging.tz), _hm(there, origin.tz), lodging, origin, 6),
        Stay(_hm(there, origin.tz), _hm(dep, origin.tz), origin),
        Stay(_hm(arr, destination.tz), _hm(landed, destination.tz), destination),
        Move(_hm(landed, destination.tz), _hm(arrived, home.tz), destination, home, 6),
        Stay(_hm(arrived, home.tz), "24:00", home),
    ]


def _drive(a: Spot, b: Spot, clock: str, minutes: int) -> list[Leg]:
    t0 = _local(date(2000, 1, 1), clock, a.tz)
    t1 = t0 + timedelta(minutes=minutes)
    return [Stay("00:00", clock, a), Move(clock, _hm(t1, b.tz), a, b, 12), Stay(_hm(t1, b.tz), "24:00", b)]


def _journey_legs(
    story: _Story, life: Life, journey: Journey, part: str, day: date, home: Spot, tracked: bool
) -> list[Leg]:
    """The day's legs on a journey, and the flight lines of the out and back days."""
    if journey.airport is None:
        if part == "out":
            return _drive(home, journey.lodging, "09:00", journey.drive_min)
        if part == "back":
            return _drive(journey.lodging, home, "14:00", journey.drive_min)
        return [Stay("00:00", "24:00", journey.lodging, 60)]
    origin = HOME_AIRPORT[home]
    if part == "out":
        dep, arr = _flight(story, day, origin, journey.airport, "10:00", tracked)
        return _fly_out(home, origin, journey.airport, journey.lodging, dep, arr, journey.drive_min)
    if part == "back":
        dep, arr = _flight(story, day, journey.airport, origin, "15:00", tracked)
        return _fly_back(journey.lodging, journey.airport, origin, home, dep, arr, journey.drive_min)
    if journey.kind == "client":
        return OWNER_DAYS["zurich_meeting"]
    return [Stay("00:00", "24:00", journey.lodging, 60)]


def _journey_lines(story: _Story, life: Life, journey: Journey, part: str, day: date, age: int) -> None:
    """What a day away leaves besides the track: the note of arrival, a photo or two, the client's
    kickoff, Christmas Eve, a taxi, the dinner paid."""
    rng = story.rng
    tz = journey.lodging.tz
    first_night = part == "out"
    if first_night:
        if journey.title:
            story.event(
                _utc(day, "00:00", tz),
                _utc(journey.end + timedelta(days=1), "00:00", tz),
                journey.title,
                journey.people,
                tz=tz,
                all_day=True,
                location=journey.lodging.name,
            )
        story.note(_utc(day, "21:30", tz), JOURNEY_NOTES[journey.kind], tz=tz)
        if journey.airport is not None and age >= WORK_AGE:
            origin = HOME_AIRPORT[life.home_on(day)]
            landed = _local(day, "10:00", origin.tz) + timedelta(
                minutes=_route(origin, journey.airport)[1] + 35
            )
            story.trip(
                _stamp(landed),
                _stamp(landed + timedelta(minutes=journey.drive_min)),
                "ride",
                "taxi",
                journey.airport,
                journey.lodging,
                40 + journey.drive_min,
                "EUR",
                tz=tz,
            )
        if journey.airport is not None and life.ola_around(day) and age >= OLA_BACK_AGE:
            story.message(_utc(day, "14:25", tz), "Landed?", False, OLA, _chat(OLA), tz=tz)
            story.message(_utc(day, "14:27", tz), "Just now. Taxi in ten.", True, OWNER, _chat(OLA), tz=tz)
    if part == "stay" and journey.kind == "client" and (day - journey.start).days == 1:
        story.event(
            _utc(day, "09:00", ZURICH),
            _utc(day, "12:00", ZURICH),
            "Project kickoff",
            (MARTA, JONAS),
            tz=ZURICH,
            location=ZH_CLIENT.name,
        )
        story.transcript(
            _utc(day, "09:00", ZURICH),
            _utc(day, "09:40", ZURICH),
            "Project kickoff",
            (MARTA, JONAS),
            [
                "Kickoff: the pilot runs over the season, the review after.",
                f"{MARTA.first} owns the data, {JONAS.first} the integration.",
                "Weekly call on Tuesdays.",
            ],
            tz=ZURICH,
        )
        story.transaction(
            _utc(day, "21:05", ZURICH), "Gasthaus zur Brücke", -94.5, "restaurants", "CHF", tz=ZURICH
        )
    if part == "stay" and rng.random() < 0.35:
        faces = tuple(p for p in journey.people if p is not EVA)
        if journey.kind == "christmas" and age <= GRANDMOTHER_UNTIL:
            faces += (SOLVEIG,)
        story.photo(
            _utc(day, f"{rng.randint(10, 18)}:{rng.randint(0, 59):02d}", tz),
            journey.lodging,
            faces[: rng.randint(0, len(faces))],
            favorite=rng.random() < 0.3,
        )
    if part == "stay" and age >= WORK_AGE and journey.lodging.tz != OSLO and rng.random() < 0.3:
        story.transaction(
            _utc(day, f"{rng.randint(12, 21)}:{rng.randint(0, 59):02d}", tz),
            "Café da Praça" if journey.kind == "lisbon" else "Trattoria" if journey.kind == "rome" else "Bar",
            -round(rng.uniform(8, 60), 1),
            "restaurants",
            {ZURICH: "CHF", LONDON: "GBP"}.get(tz, "EUR"),
            tz=tz,
        )


def _ordinary(
    story: _Story, life: Life, day: date, age: int, phase: str, home: Spot, journey: Journey | None
) -> None:
    """The lines of a day at home in each phase: the fixtures (birthdays, Christmas, the first day
    of school), the weekly rhythm (practice, lectures, meetings, calls, mail), and the sampled rest
    (photos, notes, texts, pages, music, spending)."""
    rng = story.rng
    tz = home.tz
    b = birthday(life.years, age)
    weekday = day.weekday()
    office = life.office_on(day)
    family = FAMILY + ((SOLVEIG,) if age <= GRANDMOTHER_UNTIL else ())
    away = journey is not None
    christmas_home = journey.lodging if journey is not None and journey.kind == "christmas" else home
    # -- fixtures of the year --
    if day == b:
        if age == 0:
            story.event(
                _utc(day, "00:00", tz),
                _utc(day + timedelta(days=1), "00:00", tz),
                "Ines is born",
                family,
                tz=tz,
                all_day=True,
                location=BG_HOME.name,
                source="manual",
            )
        else:
            friends: tuple[Person, ...] = ()
            if SCHOOL_AGE <= age < STUDENT_AGE:
                friends = (MIA, JENS)
            elif STUDENT_AGE <= age < WORK_AGE:
                friends = (HANNA, FREJA)
            guests = family + friends + ((OLA,) if life.ola_around(day) else ())
            story.event(
                _utc(day, "00:00", tz),
                _utc(day + timedelta(days=1), "00:00", tz),
                f"Ines turns {age}",
                guests,
                tz=tz,
                all_day=True,
                source="manual" if age < PHONE_AGE else "ios-calendar",
            )
        story.photo(
            _utc(day, "15:00", tz),
            home,
            (KARI,) + ((OLA,) if life.ola_around(day) else ()),
            favorite=True,
            provenance="camera" if age >= PHONE_AGE else "other",
        )
    if (day.month, day.day) == (12, 24) and (not away or christmas_home is not home):
        story.event(
            _utc(day, "17:00", tz),
            _utc(day, "22:00", tz),
            "Christmas Eve",
            family + ((OLA,) if age >= OLA_BACK_AGE else ()),
            tz=tz,
            location=christmas_home.name,
            source="manual" if age < PHONE_AGE else "ios-calendar",
        )
    if age in STORIES and day == b + timedelta(days=100 if STORIES[age][0] is KARI else 200):
        teller, text = STORIES[age]
        story.note(_utc(day, "20:00", tz), f"{teller.name}: {text}", tz=tz)
    if age < SCHOOL_AGE and day == b + timedelta(days=9):
        story.event(
            _utc(day, "00:00", tz),
            _utc(day + timedelta(days=8), "00:00", tz),
            "Summer at the family cabin",
            FAMILY,
            tz=tz,
            all_day=True,
            location=BG_CABIN.name,
            source="manual",
        )
    if age == SCHOOL_AGE and day == b + timedelta(days=48):
        story.event(
            _utc(day, "08:30", tz),
            _utc(day, "12:00", tz),
            "First day of school",
            (EVA,),
            tz=tz,
            location=BG_SCHOOL.name,
            source="manual",
        )
    if phase == "school" and age >= 10 and day == b + timedelta(days=320):
        story.event(
            _utc(day, "00:00", tz),
            _utc(day + timedelta(days=3), "00:00", tz),
            "Class trip",
            (MIA, JENS),
            tz=tz,
            all_day=True,
        )
    if phase == "student" and day in (b + timedelta(days=160), b + timedelta(days=340)):
        story.event(_utc(day, "09:00", tz), _utc(day, "13:00", tz), "Exam", (), tz=tz, location=CPH_UNI.name)
    if day == life.student_move or day == life.oslo_move:
        story.note(
            _utc(day, "22:00", tz), MOVE_NOTES[STUDENT_AGE if day == life.student_move else MOVE_AGE], tz=tz
        )
    if day == life.watch_day and life.years > WATCH_AGE:
        story.note(_utc(day, "19:00", tz), WATCH_NOTE, tz=tz)
    if day == life.boat_day and life.years > BOAT_AGE:
        story.note(_utc(day, "16:00", tz), BOAT_NOTE, tz=tz)
        story.photo(_utc(day, "15:30", tz), MARINA, (OLA,), favorite=True)
    # -- people who drift --
    if age == MIA_LAST_CALL and day == b + timedelta(days=150):
        story.call(_utc(day, "19:30", tz), MIA, 24.0, incoming=True, tz=tz)
    if age == MIA_LAST_MESSAGE and day == b + timedelta(days=200):
        story.message(
            _utc(day, "20:15", tz),
            "Long time! Saw your mum at the shop. Hope Copenhagen is good.",
            False,
            MIA,
            _chat(MIA),
            tz=tz,
        )
        story.message(_utc(day, "20:40", tz), "Mia! It is. Come visit.", True, OWNER, _chat(MIA), tz=tz)
    if age == HANNA_WRITES_AGAIN and day == b + timedelta(days=123):
        story.message(
            _utc(day, "21:00", tz),
            "Found a napkin with statistics on it and thought of you.",
            False,
            HANNA,
            _chat(HANNA),
            tz=tz,
        )
    if away:
        return
    # -- the weekly rhythm --
    if phase == "school" and weekday == 2 and (day.month >= 9 or day.month <= 5) and office is not None:
        story.event(
            _utc(day, "17:00", tz),
            _utc(day, "18:30", tz),
            "Football practice",
            (MIA, JENS),
            tz=tz,
            location=office.name,
            source="manual" if age < PHONE_AGE else "ios-calendar",
        )
    if (
        phase == "student"
        and weekday in (0, 2, 4)
        and (day.month in (9, 10, 11) or (day.month == 12 and day.day <= 15) or 2 <= day.month <= 5)
    ):
        story.event(
            _utc(day, "10:00", tz),
            _utc(day, "12:00", tz),
            LECTURES[(day.isocalendar().week + weekday) % len(LECTURES)],
            (HANNA, FREJA),
            tz=tz,
            location=CPH_UNI.name,
        )
    if phase == "student" and weekday == 0 and rng.random() < 0.6:
        sender, subject, body = STUDENT_MAIL[day.isocalendar().week % len(STUDENT_MAIL)]
        story.mail(
            _utc(day, f"{rng.randint(8, 16)}:{rng.randint(0, 59):02d}", tz), sender, subject, body, tz=tz
        )
    if phase == "work" and weekday in (1, 3) and office is not None and rng.random() < 0.8:
        in_oslo = home is HOME
        colleagues = (PER, LIV) if in_oslo else (BJORN, FREJA)
        title = demo.MEETINGS[(day.isocalendar().week + weekday) % len(demo.MEETINGS)][0]
        story.event(
            _utc(day, "09:00", tz),
            _utc(day, "09:45", tz),
            title,
            colleagues[: 1 + weekday % 2],
            tz=tz,
            location=office.name,
        )
        if weekday == 3 and day.day <= 7:
            story.transcript(
                _utc(day, "14:00", tz),
                _utc(day, "14:30", tz),
                title,
                colleagues,
                [
                    f"{title}: agreed the month's scope.",
                    f"{colleagues[0].first} takes the first half, {colleagues[1].first} the review.",
                    "Next check-in in two weeks.",
                ],
                tz=tz,
            )
    if phase == "work" and weekday in (0, 2, 4):
        table = WORK_MAIL_OSLO if home is HOME else WORK_MAIL_CPH
        sender, subject, body = table[(day.isocalendar().week + weekday) % len(table)]
        story.mail(
            _utc(day, f"{rng.randint(8, 16)}:{rng.randint(0, 59):02d}", tz), sender, subject, body, tz=tz
        )
    if phase in ("student", "work") and weekday == 6:
        story.call(_utc(day, "19:00", tz), EVA, rng.uniform(12, 40), incoming=day.day % 2 == 0, tz=tz)
    if phase in ("student", "work") and weekday == 2 and day.isocalendar().week % 2 == 0:
        story.call(_utc(day, "20:10", tz), KARI, rng.uniform(5, 25), incoming=False, tz=tz)
    # -- messages: with friends, with Ola --
    if age >= OLA_BACK_AGE and day.toordinal() % 2 == 0:
        asked, answered = demo.OLA_CHAT[day.toordinal() % len(demo.OLA_CHAT)]
        hour = rng.randint(10, 17)
        story.message(_utc(day, f"{hour}:{rng.randint(0, 29):02d}", tz), asked, False, OLA, _chat(OLA), tz=tz)
        story.message(
            _utc(day, f"{hour}:{rng.randint(30, 59):02d}", tz), answered, True, OWNER, _chat(OLA), tz=tz
        )
    elif age >= PHONE_AGE and rng.random() < (0.3 if phase == "school" else 0.4):
        if phase == "school":
            who, asked, answered = TEEN_CHAT[rng.randrange(len(TEEN_CHAT))]
            if who is OLA and not life.ola_around(day):
                who = MIA
            source, chat = "imessage", (who.phone, "direct", who.first)
        elif phase == "student":
            who, asked, answered = STUDENT_CHAT[rng.randrange(len(STUDENT_CHAT))]
            source, chat = "whatsapp", _chat(who)
        else:
            who, asked, answered = FRIEND_CHAT[rng.randrange(len(FRIEND_CHAT))]
            source, chat = "whatsapp", _chat(who)
        hour = rng.randint(9, 21)
        story.message(
            _utc(day, f"{hour}:{rng.randint(0, 29):02d}", tz), asked, False, who, chat, tz=tz, source=source
        )
        story.message(
            _utc(day, f"{hour}:{rng.randint(30, 59):02d}", tz),
            answered,
            True,
            OWNER,
            chat,
            tz=tz,
            source=source,
        )
    if phase == "school" and age >= PHONE_AGE and rng.random() < 0.07:
        who = rng.choice((MIA, JENS, EVA))
        story.call(
            _utc(day, f"{rng.randint(16, 21)}:{rng.randint(0, 59):02d}", tz),
            who,
            rng.uniform(2, 20),
            incoming=rng.random() < 0.5,
            tz=tz,
        )
    # -- the sampled rest --
    photo_rate = {"child": 10, "school": 15, "student": 20, "work": 30}[phase] / 365
    if rng.random() < photo_rate:
        faces = _faces(life, day, age, phase)
        story.photo(
            _utc(day, f"{rng.randint(9, 19)}:{rng.randint(0, 59):02d}", tz),
            rng.choice((home, office or home)),
            faces,
            favorite=rng.random() < 0.2,
            album="Art" if phase == "work" and rng.random() < 0.1 else None,
            provenance="camera" if age >= PHONE_AGE else "other",
        )
    note_rate = (
        0
        if phase == "child" or (phase == "school" and age < 10)
        else {"school": 8, "student": 12, "work": 20}[phase] / 365
    )
    if rng.random() < note_rate:
        words = DIARY if phase == "school" else STUDENT_NOTES if phase == "student" else WORK_NOTES
        story.note(_utc(day, "21:30", tz), words[rng.randrange(len(words))], tz=tz)
    if age >= STUDENT_AGE:
        if rng.random() < (0.3 if phase == "student" else 0.4):
            url, title = demo.PAGES[rng.randrange(len(demo.PAGES))]
            story.browse(_utc(day, f"{rng.randint(7, 22)}:{rng.randint(0, 59):02d}", tz), url, title, tz=tz)
        if rng.random() < (0.15 if phase == "student" else 0.3):
            if rng.random() < 0.7:
                story.listen(
                    _utc(day, f"{rng.randint(8, 21)}:{rng.randint(0, 59):02d}", tz),
                    demo.TRACKS[day.toordinal() % len(demo.TRACKS)],
                    None,
                    tz=tz,
                )
            else:
                story.listen(
                    _utc(day, "07:40", tz), None, demo.EPISODES[day.toordinal() % len(demo.EPISODES)], tz=tz
                )
        if phase == "work" and rng.random() < 0.15:
            story.watch(
                _utc(day, f"{rng.randint(19, 22)}:{rng.randint(0, 59):02d}", tz),
                demo.VIDEOS[day.toordinal() % len(demo.VIDEOS)],
                tz=tz,
            )
        if rng.random() < (4 if phase == "student" else 6) / 365:
            story.highlight(_utc(day, "22:10", tz), QUOTES[day.toordinal() % len(QUOTES)], tz=tz)
        if rng.random() < (6 if phase == "student" else 12) / 365:
            title, status, _offset = demo.TASKS[day.toordinal() % len(demo.TASKS)]
            story.task(_utc(day, "08:30", tz), title, status, day + timedelta(days=rng.randint(2, 9)))
        if weekday in (4, 5) and rng.random() < (0.5 if phase == "student" else 0.9):
            merchant, amount, category = demo.MERCHANTS[day.toordinal() % len(demo.MERCHANTS)]
            story.transaction(
                _utc(day, f"{rng.randint(8, 19)}:{rng.randint(0, 59):02d}", tz),
                merchant,
                amount,
                category,
                "DKK" if home is CPH_FLAT else "NOK",
                tz=tz,
            )
        if phase == "work" and rng.random() < 4 / 365:
            title, seconds, _offset = demo.VOICE_MEMOS[day.toordinal() % len(demo.VOICE_MEMOS)]
            story.voice_memo(_utc(day, "17:45", tz), title, seconds)


def _faces(life: Life, day: date, age: int, phase: str) -> tuple[Person, ...]:
    rng = random.Random(day.toordinal())  # which faces, by the day: nothing else reads this stream
    pool: list[Person] = [KARI]
    if age <= GRANDMOTHER_UNTIL:
        pool.append(SOLVEIG)
    if life.ola_around(day):
        pool.append(OLA)
    if phase == "school":
        pool.append(MIA)
    if phase == "student":
        pool += [HANNA, FREJA]
    if phase == "work" and life.home_on(day) is CPH_FLAT:
        pool.append(FREJA)
    return tuple(rng.sample(pool, rng.randint(0, min(2, len(pool)))))


def _thin_health(story: _Story, day: date, tz: str, busy: float) -> None:
    """A watch day outside the full month: resting rate, the day's steps as one sample, a heart
    rate in the afternoon."""
    rng = story.rng
    story.health(_utc(day, "06:00", tz), "resting_hr", rng.randint(52, 61), "bpm", "Watch", tz=tz)
    start, end = _local(day, "07:00", tz), _local(day, "22:00", tz)
    story.health(
        _stamp(start),
        "steps",
        round(rng.randint(4000, 11000) * busy),
        "count",
        "Phone",
        end=_stamp(end),
        tz=tz,
        extra={"samples": rng.randint(40, 90)},
    )
    story.health(
        _utc(day, f"14:{rng.randint(0, 59):02d}", tz),
        "heart_rate",
        rng.randint(60, 100),
        "bpm",
        "Watch",
        tz=tz,
    )


def _thin_night(story: _Story, day: date, tz: str) -> None:
    """The night that starts on `day`: in bed, asleep a few minutes later, two stages that fill
    the sleep (a stage never shares its instant with the in-bed line: the raw id is the instant)."""
    rng = story.rng
    t = _local(day, "23:30", tz) + timedelta(minutes=rng.randint(0, 60))
    total = timedelta(minutes=rng.randint(410, 530))
    story.health(
        _stamp(t),
        "sleep",
        round(total.total_seconds()),
        "s",
        "Watch",
        end=_stamp(t + total),
        tz=tz,
        stage="in_bed",
    )
    asleep = t + timedelta(minutes=rng.randint(5, 15))
    core = timedelta(minutes=round((t + total - asleep).total_seconds() / 60 * 0.6))
    story.health(
        _stamp(asleep),
        "sleep",
        round(core.total_seconds()),
        "s",
        "Watch",
        end=_stamp(asleep + core),
        tz=tz,
        stage="core",
    )
    deep = t + total - asleep - core
    story.health(
        _stamp(asleep + core),
        "sleep",
        round(deep.total_seconds()),
        "s",
        "Watch",
        end=_stamp(t + total),
        tz=tz,
        stage="deep",
    )


def _sail(story: _Story, day: date) -> None:
    """A Saturday's sail: out to the bay and back, the boat's own track at ten minutes."""
    owner: list[Leg] = [
        Stay("00:00", "09:00", HOME),
        Move("09:00", "09:15", HOME, MARINA, 3),
        Stay("09:15", "10:00", MARINA, 15),
        Move("10:00", "12:30", MARINA, BAY_A, 30),
        Stay("12:30", "15:00", BAY_A, 15),
        Move("15:00", "17:30", BAY_A, MARINA, 30),
        Stay("17:30", "18:00", MARINA, 15),
        Move("18:00", "18:15", MARINA, HOME, 3),
        Stay("18:15", "24:00", HOME),
    ]
    boat: list[Leg] = [
        Stay("00:00", "10:00", MARINA, 5),
        Move("10:00", "12:30", MARINA, BAY_A, 30),
        Stay("12:30", "15:00", BAY_A, 5),
        Move("15:00", "17:30", BAY_A, MARINA, 30),
        Stay("17:30", "24:00", MARINA, 5),
    ]
    story.track(day, owner, None, 120)
    story.track(day, boat, BOAT, 10)
    story.event(_utc(day, "10:00"), _utc(day, "17:30"), "Day sail", (OLA, ANDERS), location=MARINA.name)
    story.note(_utc(day, "19:00"), "Sailed to the bay and back. Anders brought the good coffee.")
    story.photo(
        _utc(day, "13:30"), BAY_A, (OLA, ANDERS) if day.day % 2 else (SIGRID,), favorite=day.day % 3 == 0
    )


def _month_day(story: _Story, day: date) -> None:
    """One day of the default month at full resolution, as `demo.story_of` writes it."""
    d = (day - demo.START).days
    kind = DAY_TYPES[d % CYCLE]
    points = story.track(day, OWNER_DAYS[kind], None, 5)
    story.track(day, BOAT_DAYS.get(kind, BERTH), BOAT, 10 if kind in BOAT_DAYS else 60)
    demo._day(story, d, day, points)
    demo._daytime_health(story, day, demo._zone_of(kind), kind)
    if day < TODAY:
        demo._night(story, day, demo._end_spot(kind).tz)


def story_of(years: int, seed: int, recorded_at: str) -> _Story:
    """The whole life as drafts, in a plausible import order: people first, then each day's
    tracks, lines and night; keepers last, as `logbook infer keepers` would add them."""
    life = Life(years)
    story = _Story(random.Random(seed), flights.Airports.load(), flights.Airlines.load(), recorded_at)
    demo._resolutions(story, PEOPLE, life.birth)
    journeys = _journeys(life, story.rng)
    sails: set[date] = set()
    if years > BOAT_AGE:
        for age in range(BOAT_AGE, years):
            b = birthday(years, age)
            saturdays = [b + timedelta(days=i) for i in range(365) if (b + timedelta(days=i)).weekday() == 5]
            summer = [
                d
                for d in saturdays
                if d.month in (5, 6, 8, 9)
                and d not in journeys
                and d >= life.boat_day
                and not (life.full_month and d >= demo.START)
            ]
            sails.update(story.rng.sample(summer, min(4, len(summer))))
    day = life.birth
    while day <= TODAY:
        age = life.age_on(day)
        if life.full_month and day >= demo.START:
            _month_day(story, day)
            day += timedelta(days=1)
            continue
        phase = life.phase_on(day)
        home = life.home_on(day)
        away = journeys.get(day)
        tracked = age >= TRACKER_AGE
        has_boat = years > BOAT_AGE and day >= life.boat_day
        tz = home.tz
        busy = 1.0
        if away is not None:
            journey, part = away
            tz = journey.lodging.tz if part != "back" else home.tz
            if journey.story:
                d = journey.story[(day - journey.start).days]
                kind = DAY_TYPES[d]
                points = story.track(day, OWNER_DAYS[kind], None, 120)
                if has_boat:
                    story.track(day, BOAT_DAYS.get(kind, BERTH), BOAT, 10 if kind in BOAT_DAYS else 1440)
                demo._day(story, d, day, points)
                tz = demo._zone_of(kind)
                busy = 0.8 if kind.startswith("boat") else 1.3
            else:
                story.track(day, _journey_legs(story, life, journey, part, day, home, tracked), None, 120)
                if has_boat:
                    story.track(day, BERTH, BOAT, 1440)
                _journey_lines(story, life, journey, part, day, age)
                busy = 1.3
            _ordinary(story, life, day, age, phase, home, journey)
        else:
            cadence = life.cadence_on(day)
            if day in sails:
                _sail(story, day)
            elif cadence is not None:
                if day == life.student_move or day == life.oslo_move:
                    origin = BGO if day == life.student_move else CPH
                    old = BG_HOME if day == life.student_move else CPH_FLAT
                    dep, arr = _flight(story, day, origin, HOME_AIRPORT[home], "10:00", tracked)
                    story.track(day, _fly_out(old, origin, HOME_AIRPORT[home], home, dep, arr, 40), None, 120)
                else:
                    office = life.office_on(day)
                    legs: list[Leg] = [Stay("00:00", "24:00", home)]
                    if office is not None and day.weekday() < 5 and age >= STUDENT_AGE:
                        legs = [
                            Stay("00:00", "08:00", home),
                            Move("08:00", "08:20", home, office, 1),
                            Stay("08:20", "16:30", office),
                            Move("16:30", "16:50", office, home, 1),
                            Stay("16:50", "24:00", home),
                        ]
                    story.track(day, legs, None, cadence)
                if has_boat:
                    story.track(day, BERTH, BOAT, 1440)
            _ordinary(story, life, day, age, phase, home, None)
        if years > WATCH_AGE and day >= life.watch_day:
            _thin_health(story, day, tz, busy)
            if day < TODAY:
                _thin_night(story, day, tz)
        day += timedelta(days=1)
    for keeper in keepers.infer(story.photos):
        story.drafts.append({"id": story.uuid7(keeper["at"]), "recorded_at": recorded_at, **keeper})
    return story


def generate(root: Path, years: int, seed: int = 1) -> Logbook:
    """Write the life under `root` (a folder that is not yet a logbook) and return it. `demo.write`
    does the writing; the places are the homes she lived in and what the life reached."""
    life = Life(years)
    recorded_at = _utc(TODAY + timedelta(days=1), "08:00")
    story = story_of(years, seed, recorded_at)
    notes: dict[date, str] = {}
    for age in range(STUDENT_AGE, years):
        notes[birthday(years, age) + timedelta(days=176)] = NOTE_FILES["christmas"]
    if life.full_month:
        for d in range(CYCLE + 2):
            day = demo.START + timedelta(days=d)
            text = demo.NOTE_FILES.get(DAY_TYPES[d % CYCLE])
            if text and day <= TODAY:
                notes[day] = text
    return demo.write(root, seed, story, life.birth, life.places(), notes)
