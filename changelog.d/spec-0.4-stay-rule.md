### Changed
- SPEC 0.4: §3.2.3 rule 5 says what #263 made the reference do. An event makes a stop a stay only when
  it happened somewhere: it comes from a calendar (`ios-calendar`, `ics`) or Google Home's history,
  or it carries a `location` or `attendees`. A page edited or a file changed promotes nothing and is
  not counted in `attached`; transcripts, notes, calls, messages and photos promote as before
  ([ADR 0023](docs/adr/0023-digital-events-do-not-make-a-stay.md)). A reader's rule, not the format:
  a record still names `logbook/0.3`, and no conformance fixture or head changes. SPEC gains a
  version history.
