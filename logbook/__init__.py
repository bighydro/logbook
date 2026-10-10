"""Logbook — a diary that writes itself. Layer 1: the folder, the chain, the CLI."""

__version__ = "0.6.1"
FORMAT = "logbook/0.3"  # SPEC §3.1: RFC 8785 exactly, tiers 2 and 3 sealable (RFC 0029); 0.1 is migrated
PREVIOUS_FORMAT = "logbook/0.2"  # the same hash rule without sealing: read and written as is, never migrated

from ._shim import install as _install_moved_paths  # noqa: E402  (the constants above come first)

_install_moved_paths()  # `import logbook.store` still works: layout.MOVED, docs/migration-0.6.md
