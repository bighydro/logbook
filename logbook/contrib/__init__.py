"""The contrib tier: what reads the world into the record and the record out into the world.

The adapters, one registry (`adapters`), and the roads in: `import-backup` (`ios_backup`,
`ios_backup_crypto`, `attach`, `inbox`), `sync` (`schedule`, `asset_status`), `setup`, `doctor` and
`backup`. The roads out: the exports (`vault`, `print_page`, `print_layout`, `trip_bundle`), `serve`
and `mcp_server`. The derived readers whose output is a reader's own (SPEC §6.1): `digest`,
`promises`, `questions`, `taskdone`, `gaps`, `people_merge`, `trip_page`; and `demo`, the synthetic
record. Contrib imports core and contrib, never labs (`logbook/layout.py`)."""
