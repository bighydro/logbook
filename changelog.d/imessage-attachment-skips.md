### Fixed
- `imessage` counts every attachment row of a kept message whose file is not in the backup under its reason, `skipped_attachment_<reason>` (no attachment row, no filename, an unsupported kind, a file not in the backup), so `logbook add` and `logbook sync imessage` say where the gap to the attachment table went. The message's line stays as before, `extra.media_missing` and all (#80).
