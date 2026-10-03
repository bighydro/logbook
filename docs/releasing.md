# Releasing

The captain releases ([GOVERNANCE.md](GOVERNANCE.md)); this is the checklist, in order. `X.Y.Z` is the version being released.

1. **Only the captain and bots have ever committed.** `git log --all --format='%an %ae %cn %ce' | sort -u` shows bighydro, GitHub and dependabot, nothing else.
2. **Bump the version** in `pyproject.toml` and `__version__` in `logbook/__init__.py` together, then `uv lock` so `uv.lock` carries it too.
3. **Assemble the changelog.** `uv run python scripts/changelog_assemble.py X.Y.Z` folds every fragment in `changelog.d/` (and the `## Unreleased` block of CHANGELOG.md, while one exists) into `## X.Y.Z — <today>` at the top of CHANGELOG.md and deletes the fragments. `--dry-run` prints the section first. Read the result: headings come in the order the fragments named them, and a release reads better when they are reworded or reordered by hand, as 0.5.0 was.
4. **Commit on a branch and open the release pull request**, labelled `no-changelog`: it is the one pull request that edits CHANGELOG.md. `git commit -s -S`, then `git log -1 --format='%G?'` prints `G`.
5. **Tag the merged commit.** `git grep __version__ HEAD -- logbook/__init__.py` prints X.Y.Z; CHANGELOG.md has X.Y.Z with today's date; then `git tag -s vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`. The `release` workflow builds the wheel, attests it, publishes to PyPI and makes the GitHub release.
