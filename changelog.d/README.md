# Changelog fragments

One file per pull request, `changelog.d/<short-slug>.md`, in the wording of [CHANGELOG.md](../CHANGELOG.md): one or a few `- ` lines, optionally under `### Added`, `### Fixed`, `### Adapters` or another heading the changelog already uses. The second line of a bullet is indented. Nothing else: no title, no prose.

    ### Fixed
    - `verify` names the month file when a line is out of order (#123).

At release time `scripts/changelog_assemble.py X.Y.Z` folds every fragment here into `## X.Y.Z — <date>` at the top of CHANGELOG.md and deletes it; this README stays. The `changelog` check fails a pull request that edits CHANGELOG.md or adds no fragment, unless the pull request carries the `no-changelog` label (nothing to tell the user, or the release itself).
