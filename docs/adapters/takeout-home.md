# Takeout: Home App → `event/v1`

`Takeout/Home App/HomeHistory.json` is the Google Home app's history of what the home's devices
saw: a phone arriving or leaving, the alarm armed and disarmed, a device added, a routine run.
Beside it Takeout puts `SoundSensing/` (the sounds a speaker heard, with recordings) and
`SecurityAlarmClips/` (camera clips an alarm kept); this adapter never opens either. The adapter is
`google-takeout-home` (`takeout-home`); `logbook add` recognises the file and the `Home App/` folder:

```bash
logbook add ~/Takeout/"Home App"
logbook add takeout-home ~/Takeout/"Home App"/HomeHistory.json --dry-run
```

## What becomes a line

The household's presence, one `event/v1` line each (RFC 0009), tier 1, source `google-takeout`,
`at` the event's instant, `end` null, `calendar` `{google-home, Google Home}`, the home's name as
`location`:

| Activity | Title | When |
|---|---|---|
| `arrival` | `Arrived home` (`Arrived Cabin` for a home not called Home) | a member's phone came home, a presence event to *home* |
| `departure` | `Left home` | it left |
| `alarm_armed` | `Alarm armed (home)`, `Alarm armed (away)` | the alarm set to a level; the level under `extra.level` |
| `alarm_disarmed` | `Alarm disarmed` | |

Under `extra`: the `activity`, the export's own `event_type`, the `structure` (the home), the
`device`, the alarm `level`, the household `member` the words name (*Ines arrived home*, *Alarm
disarmed by Ola*) and the `description` verbatim. `raw_id` is `home:<event id>`, else
`home:<time as spelled>:<sha256(type, description)[:16]>`.

Google has moved this file's keys between exports, so the reader finds what it needs by what a key
says: the time under `timestamp`, `time`, `eventTime`, `createdTime` or `timestampMs` (an epoch in
milliseconds), the kind under `eventType`, `type`, `event` or `activityType`, the home under
`structureName`, `structure` or `home`, the device under `deviceName` or `device`, the words under
`description`, `summary`, `message` or `title`. A key it does not need may be missing or renamed and
the events still read.

**Skipped and counted:** sound events (`sound sensing`, by their type), alarm clips (`security alarm
clips`, by their type or the clip they carry), any other event (`of another activity`: a device
added, a routine), and an event with no time. Nothing is written back, nothing is fetched, no
recording or clip is opened.

## Evidence of a night at home

The Day (SPEC §3.2.3) decides the night from the owner's stays: the stay with the longest overlap of
the night window is the night, at home when it lies in a place of kind `home`. These lines are the
evidence that goes with it. An `event/v1` line inside a cluster of the owner's points promotes a
short cluster to a stay (rule 5) and is attached to it, so `logbook day` shows *Alarm armed (home)*
under the night's stay and a ten-minute cluster at home with an arrival inside it is a stay, not a
stop. What the lines do not do yet is stand in for the track: a night with no location points at
all has no stay to attach to, and the Day does not read an arrival at 23:00 and a departure at
07:30 as a night at home on their own. That is a Day rule, not an adapter's, and would be a spec
change (SPEC §3.2.3 rule 8).

The fixture is `tests/fixtures/takeout/Home App/`, two synthetic days of the Oslo persona's home,
with a sound event, a clip and a device added to show what is left alone.
