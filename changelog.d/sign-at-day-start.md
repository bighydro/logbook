### Fixed
- `day sign --at` (and `sign_day` and `day reflect --sign`, which sign through the same code) checks the
  moment against the day's start under `day_start`, by the rule the index puts every line on its day by,
  rather than against midnight: with the day beginning at 06:00, a moment at 01:30 signs the day before and
  is refused for the date it falls on, which has not begun, so a signature never covers a page that starts
  after it. A signature already in the record is never checked again.
