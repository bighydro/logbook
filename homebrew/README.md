# The Homebrew tap

`logbook.rb` here is the formula behind

```bash
brew install bighydro/logbook/logbook
```

Homebrew finds a formula by looking in a *tap*: a GitHub repository named `homebrew-<name>` under
the user's account, with the formula files in a `Formula/` folder. `brew install bighydro/logbook/logbook`
reads as *the formula `logbook` in the tap `bighydro/logbook`*, and the tap is the repository
`github.com/bighydro/homebrew-logbook`. Homebrew clones it the first time and `git pull`s it on every
`brew update`, so publishing and updating the formula is pushing a file to that repository. Nothing
is submitted to Homebrew itself; `homebrew-core` is for projects with a following, and a tap is the
documented way to ship before that.

This repository keeps the source of truth; the tap holds a copy. CI builds the formula from here on
`macos-latest` on every pull request (the `homebrew` job of `.github/workflows/ci.yml`): installs it
from source into a throwaway local tap, runs its `test` block, and audits it. What passes there is
what gets pushed to the tap.

## Publish the tap, once

1. Create the public repository `bighydro/homebrew-logbook` on GitHub, empty, with a `README.md` of a
   line or two (the install command and a link back here). The name must start with `homebrew-`;
   that prefix is how `brew tap bighydro/logbook` finds it.
2. Put the formula in it at `Formula/logbook.rb`:

   ```bash
   git clone https://github.com/bighydro/homebrew-logbook.git
   mkdir -p homebrew-logbook/Formula
   cp homebrew/logbook.rb homebrew-logbook/Formula/logbook.rb
   cd homebrew-logbook && git add Formula/logbook.rb && git commit -s -S -m "logbook 0.5.0" && git push
   ```

3. Try it as a user would, on a Mac that has never seen the tap:

   ```bash
   brew install bighydro/logbook/logbook
   logbook --version
   brew test logbook
   brew uninstall logbook
   ```

   The first line taps the repository and builds the formula; it takes a minute or two because it
   builds `ijson` from source. (Homebrew bottles, prebuilt binaries, are a later step and need a
   release workflow in the tap; `brew install` works without them.)

## Update the formula, on every release

The formula pins one release of `openlogbook` by the URL and SHA-256 of its sdist on PyPI, so each
release means a new pair. The `release` workflow has published `X.Y.Z` to PyPI by the time this is
done (step 6 of `docs/releasing.md`).

1. Read the sdist's URL and digest from PyPI's JSON, never from a download you made yourself:

   ```bash
   curl -s https://pypi.org/pypi/openlogbook/X.Y.Z/json |
     python3 -c 'import json,sys; [print(f["url"], f["digests"]["sha256"]) for f in json.load(sys.stdin)["urls"] if f["packagetype"]=="sdist"]'
   ```

2. Put them in `url` and `sha256` of `homebrew/logbook.rb`. If `pyproject.toml` gained a runtime
   dependency, add it as a `resource` block the same way (`brew update-python-resources logbook`
   rewrites every resource from the sdist's metadata once the formula is in a tap on this Mac); if
   PyPI has a newer `ijson`, update that resource too.
3. Check it on a Mac the way CI does:

   ```bash
   brew tap-new --no-git local/logbook
   cp homebrew/logbook.rb "$(brew --repository local/logbook)/Formula/logbook.rb"
   brew install --build-from-source local/logbook/logbook
   brew test local/logbook/logbook
   brew audit --strict --online local/logbook/logbook
   brew uninstall logbook && brew untap local/logbook
   ```

4. Commit here (`fix: homebrew formula X.Y.Z`, `no-changelog`), and when the pull request is merged
   copy the file into the tap and push it as in step 2 above, with the message `logbook X.Y.Z`.
   Within the hour every `brew upgrade` picks it up.

## What the formula does

- `url` and `sha256` name the release sdist on PyPI; `head` lets `brew install --HEAD` build `main`.
- `depends_on "python@3.13"`: Homebrew's own Python, installed as a bottle, so the user needs none.
- `resource "ijson"`: the one runtime dependency (`tzdata` is Windows-only and not installed on a
  Mac). `virtualenv_install_with_resources` makes a virtualenv under the Cellar, installs each
  resource into it from source, then the package itself, and links `bin/logbook`.
- `test do`: `logbook --version` prints the formula's version; `logbook init` makes a record in the
  test folder, `logbook add` appends one invented sentence and `logbook verify` on it prints `valid`.
  Only commands every release has had, so the block does not change with the pinned version (the
  release on PyPI can lag `main` by a command: `logbook demo` is not in 0.5.0). Nothing of the
  tester's is read.

The formula installs the base package only. An optional extra (`openlogbook[encrypted]`,
`openlogbook[share]`, `openlogbook[mcp]`, `[ais]`, `[transcribe]`, `[judge]`, `[describe]`) is a
`pipx inject logbook <package>`-style addition that Homebrew does not model; a user who needs one
installs with `pipx install "openlogbook[encrypted]"` or `uv tool install "openlogbook[encrypted]"`
instead, as `docs/install.md` says.
