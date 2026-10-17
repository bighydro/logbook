### Fixed
- The dream, `transcript synthesize` and the `doctor --packet` probe can now use a model that refuses any
  temperature: `LOGBOOK_DREAM_TEMPERATURE=none` sends the request with no temperature field, a number from
  0 to 2 is sent as given, and unset keeps `0.2`, so an existing setup sends what it sent before. Anything
  else is refused, naming the variable. An HTTP 400 that names the temperature now says
  `set LOGBOOK_DREAM_TEMPERATURE=none for a model that takes no temperature`; the request is never retried
  without one on its own. The packet's `dream endpoint` section names the temperature that will be sent.
