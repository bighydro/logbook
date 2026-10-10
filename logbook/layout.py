"""Where every module of the package lives: one package, three tiers, declared here and nowhere
else (`tests/test_layout.py` holds the tree to it).

    logbook/core/      the format and what is frozen with it: canonicalisation, the hash chain, the
                       record, verify, the privacy tiers, the attachment store, and the readers whose
                       JSON a second implementation is held to (SPEC §3.2, §6.1): show, day, days,
                       trips, year, people, person, places, the rollups, derive stays
    logbook/contrib/   what reads the world into the record and the record out into the world: the
                       adapters (one registry), import-backup, sync, the exports (vault, paper, trip
                       bundles), and the derived readers whose output is a reader's own
    logbook/labs/      everything that runs a model, or is still an experiment: judge, describe,
                       transcribe, demo --years
    logbook/commands/  the CLI, one module per command family; `cli.py` is the entry point

The arrow points down: core imports core; contrib imports core and contrib; labs imports anything;
commands import anything, adapters and labs only inside the function that runs the command.

`MOVED` keeps the 0.5 import paths working for one minor version (`logbook._shim`): `import
logbook.store` is `logbook.core.store`, the same module object, with a DeprecationWarning once.
`docs/migration-0.6.md` lists them with the version that removes them."""

from __future__ import annotations

# tier -> the modules under logbook/<tier>/; a package name covers everything under it
TIERS: dict[str, tuple[str, ...]] = {
    "core": (
        "apps",
        "assets",
        "attachments",
        "chain",
        "countries",
        "crossing",
        "day",
        "days",
        "drifting",
        "events",
        "export",
        "flights",
        "fork",
        "health",
        "index",
        "keepers",
        "ledger",
        "listen_rollup",
        "pages",
        "people",
        "places",
        "policy",
        "present",
        "readiness",
        "reading",
        "repair",
        "resolve",
        "rollup",
        "sealing",
        "search",
        "share",
        "signing",
        "stays",
        "store",
        "story",
        "transcripts",
        "trips",
        "weather",
        "year",
    ),
    "contrib": (
        "adapters",
        "asset_status",
        "attach",
        "backup",
        "demo",
        "digest",
        "doctor",
        "gaps",
        "home",
        "inbox",
        "ios_backup",
        "ios_backup_crypto",
        "last_run",
        "mcp_server",
        "notify",
        "people_merge",
        "people_review",
        "print_layout",
        "print_page",
        "promises",
        "questions",
        "rows",
        "schedule",
        "serve",
        "site",
        "stream",
        "taskdone",
        "trip_bundle",
        "trip_page",
        "vault",
        "week_paper",
        "year_poster",
    ),
    "labs": (
        "chapters",
        "demo_life",
        "describe",
        "introductions",
        "judge",
        "transcribe",
    ),
}

# the modules beside the tiers: the package itself, the entry point, this table and the shim
ROOT: tuple[str, ...] = ("__init__", "cli", "layout", "_shim")
COMMANDS = "commands"  # every module under logbook/commands/

# 0.5 import path -> where it lives now; a package covers everything under it
NEW_IN_0_6: frozenset[str] = frozenset(
    {
        "home",
        "chapters",
        "fork",
        "introductions",
        "people_review",
        "last_run",
        "notify",
        "readiness",
        "rows",
        "signing",
        "site",
        "stream",
        "transcripts",
        "week_paper",
        "year_poster",
    }
)  # born in a tier: no 0.5 path to keep
MOVED: dict[str, str] = {
    f"logbook.{name}": f"logbook.{tier}.{name}"
    for tier, names in TIERS.items()
    for name in names
    if name not in NEW_IN_0_6
}
MOVED["logbook.setup"] = "logbook.commands.setup"  # the wizard drives the commands, so it lives with them
REMOVED_IN = "0.7"  # the version that drops the old paths
