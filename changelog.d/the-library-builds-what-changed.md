### Changed
- The Library's build renders what the lines since the last build touched: every door, a Day only when
  a line landed on it, a journey only when it holds such a day. `serve --build --full` renders every
  page, and is never needed in normal use.
- The people of the whole record, the promises and each person's last real contact are kept beside the
  index between readings and brought forward by the lines appended since, instead of read again from
  every line: on two million lines a person's page reads in seconds rather than minutes. A
  resolution, a retraction, a corrected line, a backfill or a changed setting reads the whole record
  again, as before.
- The world keeps each year before the current one beside the index and reads only the current
  year again, unless a line comes for an earlier year's days.
- The Manifest and each org's page read the org sightings and touches kept beside the index and the
  lines appended since, instead of every mail, meeting and chat.
- `serve --build` names the five pages that took longest to build.
- The agents' shelf keeps which lines are a session's beside the index and streams only the messages
  appended since, instead of every message of the record.
- A year's trips and journeys are built again only when a line lands on the days they were read from
  (a journey that ran on past the year included), or a draft is written.
- The People page's year so far is brought forward with the record, and a closed year's ranking is
  kept until a line lands on its days.
- The world reads its tracks and stays from the index rather than from every line of the year, and
  counts the lines it holds back in one query: the same page, in a third of the time.
- Gaps keeps every source's activity beside the index and adds the lines since; of two equally long
  silences it names the first.
- A year's trips and journeys read only the lines a trip is made of (flights, weather, events,
  transcripts, notes and photos) and the stays from the index: the same pages, read faster.
- A build of a large record renders its pages on several processes, the doors first, side by side
  (`LOGBOOK_BUILD_WORKERS` sets how many).
