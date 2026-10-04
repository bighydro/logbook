### Housekeeping
- The test suite imports the 0.6 paths (`logbook.core.store`, `logbook.contrib.adapters`, …), never the 0.5 ones
  `logbook._shim` keeps alive, and in the suite the shim's DeprecationWarning is an error, so no test drifts back
  to an old path; `scripts/rewrite_test_imports.py` (`layout.MOVED`, re-runnable, `--check`) is what moved them.
  The shims and `docs/migration-0.6.md` are unchanged.
- The ruff hook in `.pre-commit-config.yaml` is the version CI runs (`uv.lock`), so the two agree on import order.
