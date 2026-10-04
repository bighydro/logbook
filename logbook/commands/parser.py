"""The parser: every command's arguments, registered in the order `logbook --help` lists them.

A command's arguments live next to the command, in its family's module (`<command>_arguments`
beside `cmd_<command>`); this module only says which families there are and in what order. A
new command is one function pair in its family's module and one line in `ARGUMENTS`, where its
help should appear."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from .. import __version__
from . import add, day, derive, export, keepers, people, places, promises, record, rollup, serve, sync, trips
from .common import Subparsers

ARGUMENTS: tuple[Callable[[Subparsers], None], ...] = (
    record.init_arguments,
    add.add_arguments,
    sync.sync_arguments,
    add.import_backup_arguments,
    add.inbox_arguments,
    add.attach_arguments,
    derive.infer_arguments,
    derive.transcribe_arguments,
    derive.describe_arguments,
    record.retract_arguments,
    day.search_arguments,
    day.show_arguments,
    people.people_arguments,
    people.person_arguments,
    day.day_arguments,
    day.digest_arguments,
    day.questions_arguments,
    day.days_arguments,
    day.year_arguments,
    trips.trip_arguments,
    record.stats_arguments,
    derive.derive_arguments,
    places.places_arguments,
    rollup.rollup_arguments,
    trips.trips_arguments,
    rollup.ledger_arguments,
    keepers.keepers_arguments,
    promises.promises_arguments,
    promises.tasks_arguments,
    serve.serve_arguments,
    serve.mcp_arguments,
    record.demo_arguments,
    record.index_arguments,
    record.verify_arguments,
    record.setup_arguments,
    record.doctor_arguments,
    export.export_arguments,
    export.import_arguments,
    sync.sources_arguments,
    sync.assets_arguments,
    record.repair_arguments,
    export.share_arguments,
    export.receive_arguments,
    export.circle_arguments,
    record.migrate_arguments,
    record.backup_arguments,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="logbook", description="A diary that writes itself.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for arguments in ARGUMENTS:
        arguments(sub)
    return ap
