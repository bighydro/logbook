### Fixed
- The health export reader (the CSV reader the Withings, MyFitnessPal and Google Takeout Fit adapters
  share) no longer emits an empty row for a degenerate file. A row with no text under any column the
  header names — its only text past the header, or under a blank name — is skipped as a blank row is,
  so such a file reads as an empty export does: no lines and nothing counted, where each such row was
  counted as a bad date or a bad start. A column name the header repeats keeps the last cell with text
  under it; a blank or missing cell under the repeat no longer covers the text. Found by the reader's
  property test.
