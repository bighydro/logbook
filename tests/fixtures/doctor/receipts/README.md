# Installer receipts for `doctor`'s install line

What `uv tool install` and `pipx install` leave beside the Logbook they install, read by
`logbook.contrib.doctor.install_of` (tests/test_doctor.py). Each is a trimmed copy of a receipt the
installer wrote on 20 October 2026, installing a wheel of this repository offline (`--find-links`,
`--no-index`): uv 0.11.32, and pipx 1.8.0 run from its source. Every path was moved under the
synthetic `/home/ines`, every URL under `example.org`, and the fields doctor does not read (pipx's app
paths, its interpreter) were dropped; nothing in them is from the machine that wrote them.

Since the third review (20 October) doctor takes what was installed, the version or the git commit, from
the package itself (`importlib.metadata` and its `direct_url.json`, given in the tests as `doctor.Here`);
a receipt gives the extras, pipx's venv and index options, and uv's Python, options and companions.

- `uv-pinned.toml`: `uv tool install --python 3.12 --no-index --find-links … "openlogbook[mcp]==0.7.0"`
- `uv-git.toml`: `"openlogbook[mcp] @ git+…/logbook.git@v0.7.0"`
- `uv-url.toml`: `"openlogbook[mcp] @ https://…/openlogbook-0.7.0-py3-none-any.whl"`
- `uv-path.toml`: the wheel's path, bare
- `uv-with.toml`: `--with ijson "openlogbook[mcp]"`
- `uv-with-executables.toml`: `--with-executables-from uvicorn "openlogbook[mcp]"`
- `uv-constraints.toml`: `-c constraints.txt --with ijson "openlogbook[mcp]"`, a receipt no one line
  reproduces (the constraints came from a file)
- `pipx-git.json`: `pipx install git+…/logbook.git`, the bare URL
- `pipx-suffix.json`: `pipx install --suffix=-ola --pip-args="--no-index --find-links …" "openlogbook[mcp]"`
  (the `--force-reinstall` in its `pip_args` is pipx's own: the first install in a new pipx home adds it)
- `pipx-injected.json`: `pipx install "openlogbook[mcp]"`, then `pipx inject openlogbook ijson`
- `pipx-system-site.json`: `pipx install --python python3.12 --system-site-packages --pip-args="--no-index
  --find-links …" openlogbook`, by pipx 1.18.4 (its uv backend) on 20 October 2026, while pipx itself ran on
  3.13: the venv's Python and option, which no `pipx install --force` line keeps and `pipx runpip` does

`homebrew-INSTALL_RECEIPT.json` is the one written by hand, in the shape Homebrew writes into a keg
(`Cellar/logbook/0.7.0/INSTALL_RECEIPT.json`): no Mac with Homebrew was at hand, and doctor reads
only the keg's path, never this file's fields.
