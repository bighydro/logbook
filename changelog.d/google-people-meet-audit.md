### Added

- `logbook people review --from-google`: your Google contacts and other contacts (People API, `contacts.readonly` and `contacts.other.readonly`, on the one Google key) as a name source for the review. A contact that holds an observed address or number and a canonical person's own is evidence for that pair; one that touches no one the record names proposes to name the observed person as a new person (same email, same phone, same name); contacts that share an address or a number are proposed as one, to merge in Google Contacts. Nothing is merged unless you say so, and no contact becomes a line: accepting writes the name and the identifiers the record already saw, rejecting writes no line. The contacts are cached in `state/google-contacts.json` for 24 hours and never printed.
- `logbook sync meet`: your Google Meet calls from the Meet REST API (`meetings.space.readonly`), one `event/v1` line per call that has ended (tier 1, the participants as Meet names them, the conference record as the reference), and when Meet transcribed it one `transcript/v1` line built as Granola's is (tier 3, the words in `attachments/`). A Granola transcript of the same call stays its own line.
- `logbook sync gaudit`: your own sign-ins from the Workspace's login audit log (Admin SDK Reports API, `admin.reports.audit.readonly`), one `event/v1` line per sign-in event, tier 1, with how and the place Google derived; the IP address is never in a line, not even as a digest.
- `doctor`'s `google` line names `meet`, `gaudit` and what `people review --from-google` reads.

### Changed

- `sync --all` runs `meet` and `gaudit` after `gtasks` whenever the Google key is set. A key delegated before this release lacks their two scopes: add them in the Workspace admin console (the tour, *Google, on one key*, step 4) or switch the two sources off in `policy/import.json`, or each scheduled run reports them failed.
