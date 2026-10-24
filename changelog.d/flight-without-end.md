### Fixed
- The Library's Day page no longer crashes when the day, or a day it looks back to, has a flight
  line with no arrival: such a flight counts as ending at its departure, and one with no departure
  is skipped. `export vault` writes it at its departure time.
