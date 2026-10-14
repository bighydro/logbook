### Fixed
- `scripts/check_pii.py` reads a commit range: run by `pre-commit run --from-ref A --to-ref B`, as a merge
  desk runs it over a pull request, it checks the lines `git diff A..B` adds instead of the staged diff,
  which is empty then, and no longer reports Passed having checked nothing. `--tree REF` checks every line
  of every file tracked at REF, for a sweep of a whole branch. Every run ends with one line of counts,
  `check-pii: 18 patterns, 9879 lines, 0 matches in …`, shown on a pass too; no patterns file, a file of
  comments only, or nothing to read is that line as a warning. A match names the file, the line and the
  pattern (its first named group, or its line in the patterns file), never the text.
