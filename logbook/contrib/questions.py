"""The digest's closing question, chosen from the record's own bank (RFC 0027).

`policy/questions.json` is a list of question objects, the owner's to edit — `{"questions": [{"id",
"text", "text_de"?, "kind", "when", "weight", "source", "enabled"?}]}`: `id` names the question
(unique, free text); `text` is the English question, `text_de` an optional German one; `kind` is one
of `KINDS` (gratitude, savouring, people, place, body, open); `when` lists the day's facts that must
hold for the question to be asked, every name one of `FACTS`, a name prefixed `!` one that must not
hold, an empty list a question that may always be asked; `weight` is a positive number, the
question's share of the draw among the candidates; `source` is a free-text citation of the research
behind the question, empty in the defaults — the bank's content is left to a future author, and the
defaults carry only the nudges the digest used to choose in code and three placeholders. A text may
hold a placeholder of `PLACEHOLDERS` in braces — `Was {proposed} with you?` — filled from the day;
a question whose placeholder the day cannot fill is not a candidate. The first run writes the
defaults (`write_default`); nothing overwrites an edit. A file that is not this shape stops the
reader naming it (`PolicyError`), as every policy file does.

The day's facts (`facts`, `flags`, `values`) are read from the parts the digest already has — the
Day, its shape, the promises due, the gaps, tomorrow — and one of its own: `reunion`, a person
confirmed present on the day and on no day of the `REUNION_DAYS` before it, whom the record resolved
before that window (a resolution line older than it; a person met for the first time is not seen
again). The window is read through the `days` reader, chunked through the index, and only when
somebody is confirmed.

The choice (`choose`, `pick`): the enabled questions whose `when` holds and whose text fills are the
candidates; one is drawn by weight with a generator seeded by the day, so the same day draws the
same question until the bank or the state changes. Never the same id two days running: the ids
asked on the other remembered days are left out first, and when nothing remains, only the ids asked
the day before and the day after; when nothing remains even then, the digest asks `FALLBACK`,
which belongs to no id and is not remembered. A question asked for a day stands when the day is
read again, as long as it is still enabled and fills. What was asked is remembered in
`state/questions.json`, `{"asked": [{"day", "id"}, ...]}`, the last `REMEMBER` days — bookkeeping
beside the record, like a sync watermark, never in it; losing it only lets a question repeat.

`logbook questions list|add|disable` manages the file (`add`, `disable`); the module writes nothing
but the bank, its default and the state. Nothing here is a line of the record."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from ..core import days
from ..core.policy import PolicyError
from ..core.store import Logbook

QUESTIONS_FILE = PurePosixPath("policy/questions.json")  # record-relative
STATE_FILE = PurePosixPath("state/questions.json")
KINDS = ("gratitude", "savouring", "people", "place", "body", "open")
# The day's facts a `when` may name. Each is a yes or no of the day as the digest reads it.
FACTS = (
    "logged",  # the day has a line at all
    "travelled",  # a flight, or the night after not at home
    "flew",  # a flight on the day
    "aboard",  # a stay aboard an asset, or the night after aboard one
    "night_home",  # the night after at home
    "night_away",  # the night after at a stay that is not home
    "night_in_transit",  # the night after at no stay
    "company",  # somebody confirmed present
    "alone",  # a logged day with nobody confirmed and nobody proposed
    "proposed",  # somebody proposed and confirmed nowhere (a face, an all-day attendee)
    "reunion",  # somebody confirmed after REUNION_DAYS or more without them
    "photos",  # a photo attached to the day's rows
    "notes",  # a note attached to the day's rows
    "long_sleep",  # the night's sleep LONG_SLEEP_H or more
    "short_sleep",  # the night's sleep under SHORT_SLEEP_H
    "gap",  # a usual source with no line
    "promise_due",  # an open promise due on the day or before
    "event_unplaced",  # a calendar entry the track places nowhere
    "tomorrow_busy",  # BUSY_TOMORROW timed entries or more tomorrow
    "weekend",  # a Saturday or a Sunday
)
PLACEHOLDERS = ("person", "proposed", "place", "asset", "missing", "promise", "event")
REMEMBER = 7  # the asked days the state keeps
REUNION_DAYS = 90
LONG_SLEEP_H = 9.0
SHORT_SLEEP_H = 6.0
BUSY_TOMORROW = 3
FALLBACK = "Anything to add?"  # when no question of the bank can be asked; no id, never remembered
WEEKEND = ("Saturday", "Sunday")
ABOARD = "aboard "  # how the Day spells a stay aboard an asset
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

# The defaults the first run writes: the nudges the digest once chose in code, as questions with
# the condition that chose them, and three placeholders for the kinds the bank is to be written
# for (RFC 0027). `source` is empty throughout: nothing here cites anything yet.
DEFAULT_QUESTIONS: list[dict[str, Any]] = [
    {"id": "day-where", "text": "Where were you?", "kind": "place", "when": ["!logged"], "weight": 5},
    {
        "id": "gap-switched-off",
        "text": "Was {missing} switched off?",
        "kind": "open",
        "when": ["gap"],
        "weight": 3,
    },
    {
        "id": "night-where",
        "text": "Where did you sleep?",
        "kind": "place",
        "when": ["night_in_transit"],
        "weight": 4,
    },
    {
        "id": "company-proposed",
        "text": "Was {proposed} with you?",
        "kind": "people",
        "when": ["proposed"],
        "weight": 4,
    },
    {
        "id": "event-happened",
        "text": "Did {event} happen?",
        "kind": "open",
        "when": ["event_unplaced"],
        "weight": 3,
    },
    {
        "id": "promise-done",
        "text": "Is {promise} done?",
        "kind": "open",
        "when": ["promise_due"],
        "weight": 3,
    },
    {
        "id": "people-reunion",
        "text": "How was it, seeing {person} again?",
        "kind": "people",
        "when": ["reunion"],
        "weight": 4,
    },
    {
        "id": "savouring-new",
        "text": "What did you see today that you had not seen before?",
        "kind": "savouring",
        "when": ["travelled"],
        "weight": 2,
    },
    {
        "id": "body-long-sleep",
        "text": "Did the long sleep help?",
        "kind": "body",
        "when": ["long_sleep"],
        "weight": 2,
    },
    {
        "id": "gratitude-day",
        "text": "What were you glad of today?",
        "kind": "gratitude",
        "when": ["logged"],
        "weight": 1,
    },
    {"id": "open-add", "text": FALLBACK, "kind": "open", "when": ["logged"], "weight": 1},
]


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    kind: str
    when: tuple[str, ...] = ()
    weight: float = 1.0
    source: str = ""
    text_de: str | None = None
    enabled: bool = True

    def to_json(self) -> dict[str, Any]:
        weight = int(self.weight) if self.weight == int(self.weight) else self.weight
        out: dict[str, Any] = {"id": self.id, "text": self.text}
        if self.text_de is not None:
            out["text_de"] = self.text_de
        out.update({"kind": self.kind, "when": list(self.when), "weight": weight, "source": self.source})
        out["enabled"] = self.enabled
        return out


@dataclass(frozen=True)
class Facts:
    """The day as `when` sees it: every name of `FACTS` yes or no, and the words a placeholder takes."""

    flags: Mapping[str, bool]
    values: Mapping[str, str]

    def true(self) -> list[str]:
        return [name for name in FACTS if self.flags.get(name)]


# -- the bank ------------------------------------------------------------------------------------------------


def questions_path(root: Path) -> Path:
    return Path(root).joinpath(*QUESTIONS_FILE.parts)


def state_path(root: Path) -> Path:
    return Path(root).joinpath(*STATE_FILE.parts)


def write_default(root: Path) -> Path:
    """Write the default bank where none exists; never overwrite one. Returns the path."""
    path = questions_path(root)
    if not path.exists():
        _write(path, [_question(entry, path) for entry in DEFAULT_QUESTIONS])
    return path


def read(root: Path) -> list[Question]:
    """The bank as written, in its order; a record without the file gets the defaults, so the
    owner finds them. A file that is not the documented shape raises PolicyError naming it."""
    path = write_default(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise PolicyError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise PolicyError(f"{path} must be {_SHAPE}")
    out: list[Question] = []
    seen: set[str] = set()
    for entry in data["questions"]:
        q = _question(entry, path)
        if q.id in seen:
            raise PolicyError(f"{path} names the id {q.id!r} twice; every question has its own")
        seen.add(q.id)
        out.append(q)
    return out


def add(root: Path, question: Question) -> Question:
    """Append one question to the bank; an id already there is refused, and so is a question that
    is not the documented shape. Returns it as written."""
    path = questions_path(root)
    bank = read(root)
    q = _question(question.to_json(), path)
    if any(entry.id == q.id for entry in bank):
        raise PolicyError(f"{path} already has a question {q.id!r}; choose another id or disable it first")
    _write(path, [*bank, q])
    return q


def disable(root: Path, id_: str) -> Question:
    """Mark one question disabled, keeping it in the file so the owner can turn it back on by
    hand; an id the bank does not have is refused naming the file."""
    path = questions_path(root)
    bank = read(root)
    if not any(q.id == id_ for q in bank):
        raise PolicyError(f"{path} has no question {id_!r}; `logbook questions list` names them")
    out = [Question(**{**q.__dict__, "enabled": False}) if q.id == id_ else q for q in bank]
    _write(path, out)
    return next(q for q in out if q.id == id_)


_SHAPE = (
    '{"questions": [{"id": "<name>", "text": "<question>", "kind": "'
    + "|".join(KINDS)
    + '", "when": ["<fact>", "!<fact>", ...], "weight": N, "source": "<citation>"}, ...]}'
)


def _question(entry: object, path: Path) -> Question:
    """One entry of the file checked against the documented shape; a value that is not what it
    should be is refused naming the file and the key."""
    if not isinstance(entry, dict):
        raise PolicyError(f"{path} must be {_SHAPE}")
    id_ = entry.get("id")
    if not isinstance(id_, str) or not id_.strip():
        raise PolicyError(f"{path}: every question needs an id, a non-empty string")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise PolicyError(f"{path}: question {id_!r} needs a text, a non-empty string")
    text_de = entry.get("text_de")
    if text_de is not None and not isinstance(text_de, str):
        raise PolicyError(f"{path}: question {id_!r} has a text_de that is not a string")
    kind = entry.get("kind", "open")
    if kind not in KINDS:
        raise PolicyError(f"{path}: question {id_!r} has kind {kind!r}; it must be one of {', '.join(KINDS)}")
    when = entry.get("when", [])
    if not isinstance(when, list) or not all(isinstance(w, str) for w in when):
        raise PolicyError(f"{path}: question {id_!r} has a when that is not a list of fact names")
    for condition in when:
        if condition.lstrip("!") not in FACTS or condition.startswith("!!"):
            raise PolicyError(
                f"{path}: question {id_!r} names the fact {condition!r} which the digest does not know;"
                f" the facts are {', '.join(FACTS)}, each may be prefixed with !"
            )
    weight = entry.get("weight", 1)
    if isinstance(weight, bool) or not isinstance(weight, int | float) or not weight > 0:
        raise PolicyError(f"{path}: question {id_!r} has weight {weight!r}; it must be a number above zero")
    source = entry.get("source", "")
    if not isinstance(source, str):
        raise PolicyError(f"{path}: question {id_!r} has a source that is not a string")
    enabled = entry.get("enabled", True)
    if not isinstance(enabled, bool):
        raise PolicyError(f"{path}: question {id_!r} has an enabled that is not true or false")
    for name in placeholders(text) + (placeholders(text_de) if text_de else []):
        if name not in PLACEHOLDERS:
            raise PolicyError(
                f"{path}: question {id_!r} has the placeholder {{{name}}} which the digest cannot fill;"
                f" the placeholders are {', '.join('{' + p + '}' for p in PLACEHOLDERS)}"
            )
    return Question(
        id=id_.strip(),
        text=text,
        kind=str(kind),
        when=tuple(when),
        weight=float(weight),
        source=source,
        text_de=text_de,
        enabled=enabled,
    )


def _write(path: Path, bank: Sequence[Question]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"questions": [q.to_json() for q in bank]}, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


# -- the day's facts -----------------------------------------------------------------------------------------


def facts(
    lb: Logbook,
    data: Mapping[str, Any],
    shape: Mapping[str, Any],
    due_today: Sequence[str],
    missing: Sequence[str],
    tomorrow: int,
    day: str,
) -> Facts:
    """The day's facts from the digest's parts: the Day (`data`), its shape, the promises due on the
    day or before as quoted sentences (`due_today`), the usual sources with no line (`missing`) and
    how many timed entries tomorrow has; the reunion read from the record."""
    met = reunion(lb, day, shape["with"]["confirmed"])
    return Facts(
        flags=flags(data, shape, bool(due_today), missing, met, tomorrow),
        values=values(data, shape, due_today, missing, met),
    )


def flags(
    data: Mapping[str, Any],
    shape: Mapping[str, Any],
    due_today: bool,
    missing: Sequence[str],
    reunion: Sequence[str],
    tomorrow: int,
) -> dict[str, bool]:
    """Every name of `FACTS`, yes or no, from the digest's parts (`facts` says which)."""
    logged = bool(data["sources"])
    night = shape["night"]
    with_ = shape["with"]
    counts = {str(a["noun"]): int(a["count"]) for a in shape["attached"]}
    health = data.get("health") or {}
    sleep_h = health.get("sleep_h")
    aboard = bool(night.get("aboard")) or any(e.get("kind") == "aboard" for e in data["timeline"])
    flew = bool(data["flights"])
    out = {
        "logged": logged,
        "travelled": logged and (flew or not night["home"]),
        "flew": flew,
        "aboard": logged and aboard,
        "night_home": logged and bool(night["home"]),
        "night_away": logged and not night["home"] and not night["in_transit"] and bool(night["where"]),
        "night_in_transit": logged and bool(night["in_transit"]),
        "company": bool(with_["confirmed"]),
        "alone": logged and not with_["confirmed"] and not with_["proposed"],
        "proposed": bool(with_["proposed"]),
        "reunion": bool(reunion),
        "photos": counts.get("photo", 0) > 0,
        "notes": counts.get("note", 0) > 0,
        "long_sleep": sleep_h is not None and float(sleep_h) >= LONG_SLEEP_H,
        "short_sleep": sleep_h is not None and float(sleep_h) < SHORT_SLEEP_H,
        "gap": bool(missing),
        "promise_due": due_today,
        "event_unplaced": any(u.get("kind") == "event" for u in data["unplaced"]),
        "tomorrow_busy": tomorrow >= BUSY_TOMORROW,
        "weekend": data["weekday"] in WEEKEND,
    }
    assert set(out) == set(FACTS)
    return out


def values(
    data: Mapping[str, Any],
    shape: Mapping[str, Any],
    due_today: Sequence[str],
    missing: Sequence[str],
    reunion: Sequence[str],
) -> dict[str, str]:
    """The words a placeholder takes, those the day has: `person` (the reunion's, else the first
    confirmed), `proposed`, `place` (the first stay that is not home), `asset` (the one aboard),
    `missing`, `promise` (the first due, quoted) and `event` (the first unplaced entry's title,
    quoted)."""
    out: dict[str, str] = {}
    with_ = shape["with"]
    if reunion or with_["confirmed"]:
        out["person"] = str(reunion[0] if reunion else with_["confirmed"][0])
    if with_["proposed"]:
        out["proposed"] = str(with_["proposed"][0])
    night = shape["night"]
    home = str(night["where"]) if night["home"] and night["where"] else None
    places = [str(w) for w in shape["where"] if str(w) != home and not str(w).startswith(ABOARD)]
    if places:
        out["place"] = places[0]
    aboard = [str(w)[len(ABOARD) :] for w in shape["where"] if str(w).startswith(ABOARD)]
    if aboard:
        out["asset"] = aboard[0]
    if missing:
        out["missing"] = str(missing[0])
    if due_today:
        out["promise"] = str(due_today[0])
    planned = [u for u in data["unplaced"] if u.get("kind") == "event"]
    if planned:
        out["event"] = f"“{planned[0]['title']}”"
    return out


def reunion(lb: Logbook, day: str, confirmed: Sequence[str]) -> list[str]:
    """Of the people confirmed present on `day`, those confirmed on no day of the `REUNION_DAYS`
    before it whom the record resolved before that window — a resolution line carrying their label,
    recorded before the window's first day. Nobody confirmed: nothing is read."""
    if not confirmed:
        return []
    d = date.fromisoformat(day)
    first = (d - timedelta(days=REUNION_DAYS)).isoformat()
    last = (d - timedelta(days=1)).isoformat()
    seen: set[str] = set()
    for row in days.read(lb, first, last):
        seen.update(str(name) for name in row["people"]["names"])
    known: set[str] = set()
    with lb.index() as idx:
        for line in idx.resolutions():
            label = (line.get("payload") or {}).get("label")
            if isinstance(label, str) and str(line.get("at", ""))[:10] < first:
                known.add(label)
    return [str(name) for name in confirmed if name not in seen and name in known]


# -- the choice ----------------------------------------------------------------------------------------------


def matches(question: Question, facts: Facts) -> bool:
    """Every fact `when` names holds, and every one it negates does not; no condition always holds."""
    for condition in question.when:
        wanted = not condition.startswith("!")
        if bool(facts.flags.get(condition.lstrip("!"), False)) != wanted:
            return False
    return True


def placeholders(text: str | None) -> list[str]:
    """The names in braces, in order of appearance."""
    return _PLACEHOLDER.findall(text or "")


def fill(text: str, values: Mapping[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def choose(bank: Sequence[Question], facts: Facts, exclude: set[str], seed: str) -> Question | None:
    """One question drawn by weight from the enabled questions of `bank` whose `when` holds, whose
    text fills, and whose id is not in `exclude`; None when there is none. The draw is seeded by
    `seed` (the day), so the same inputs draw the same question."""
    candidates = [
        q
        for q in bank
        if q.enabled
        and q.id not in exclude
        and matches(q, facts)
        and all(name in facts.values for name in placeholders(q.text))
    ]
    if not candidates:
        return None
    rng = random.Random(seed)
    return rng.choices(candidates, weights=[q.weight for q in candidates])[0]


def pick(root: Path, facts: Facts, day: str) -> dict[str, Any]:
    """The question of `day`: `{"id", "kind", "text", "facts"}`, the text filled, `facts` the names
    that hold. A question asked for the day before stands when it is still enabled and fills; else
    one is chosen (`choose`) leaving out the ids asked on the other remembered days, then only
    those asked the day before and the day after, and the choice is remembered in the state. When
    nothing can be asked the text is `FALLBACK` with id None, and nothing is remembered."""
    bank = read(root)
    by_day = {entry["day"]: entry["id"] for entry in asked(root)}
    enabled = {q.id: q for q in bank if q.enabled}
    chosen: Question | None = None
    standing = enabled.get(by_day.get(day, ""))
    if standing is not None and all(name in facts.values for name in placeholders(standing.text)):
        chosen = standing
    else:
        d = date.fromisoformat(day)
        others = {id_ for asked_day, id_ in by_day.items() if asked_day != day}
        adjacent = {
            id_
            for asked_day, id_ in by_day.items()
            if asked_day in ((d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat())
        }
        chosen = choose(bank, facts, others, day) or choose(bank, facts, adjacent, day)
    if chosen is None:
        return {"id": None, "kind": "open", "text": FALLBACK, "facts": facts.true()}
    remember(root, day, chosen.id)
    return {
        "id": chosen.id,
        "kind": chosen.kind,
        "text": fill(chosen.text, facts.values),
        "facts": facts.true(),
    }


# -- the state -----------------------------------------------------------------------------------------------


def asked(root: Path) -> list[dict[str, str]]:
    """The remembered `{"day", "id"}` entries, by day; a state file that is missing or not the
    shape is bookkeeping lost, never an error."""
    path = state_path(root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    entries = data.get("asked") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    out = [
        {"day": str(e["day"]), "id": str(e["id"])}
        for e in entries
        if isinstance(e, dict) and isinstance(e.get("day"), str) and isinstance(e.get("id"), str)
    ]
    return sorted(out, key=lambda e: e["day"])


def remember(root: Path, day: str, id_: str) -> None:
    """Record that `id_` was asked for `day`, replacing what the day held; the last `REMEMBER` days
    are kept."""
    entries = [e for e in asked(root) if e["day"] != day]
    entries.append({"day": day, "id": id_})
    entries.sort(key=lambda e: e["day"])
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"asked": entries[-REMEMBER:]}, indent=2) + "\n", encoding="utf-8")
