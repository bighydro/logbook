"""Logbook — a diary that writes itself. Layer 1: the folder, the chain, the CLI."""

__version__ = "0.5.0"
FORMAT = "logbook/0.2"  # SPEC §3.1: 0.2 hashes with RFC 8785 exactly; a 0.1 record must be migrated

from ._shim import install as _install_moved_paths  # noqa: E402  (the constants above come first)

_install_moved_paths()  # `import logbook.store` still works: layout.MOVED, docs/migration-0.6.md
