"""Google Takeout Calendar → event/v1 (RFC 0009), through the `ics` adapter.

Takeout writes `Takeout/Calendar/<calendar>.ics`, one plain iCalendar file per calendar (RFC 5545, with
X-WR-CALNAME naming it), so there is nothing Google-specific to read: this sibling only knows where the
files live. It is the calendar entry of the package's dispatch (`SUB_ADAPTERS`; the `walk(folder)` of the
package docstring is not built yet) and hands the folder, or a file in it, to `logbook.adapters.ics`,
whose lines it yields unchanged — source `ics`, so a calendar reached through the Takeout folder and the
same file added on its own are the same lines and dedupe. Not in the adapter registry: `ics` already
sniffs every such file, and `logbook add Takeout/Calendar` reaches it that way today.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from logbook.adapters import ics

NAME = ics.NAME
FOLDER = "Calendar"  # Takeout/Calendar/


def sniff(path: Path) -> bool:
    """The Takeout `Calendar/` folder holding at least one iCalendar file, or such a file inside it."""
    path = Path(path)
    folder = path if path.is_dir() else path.parent
    return folder.name == FOLDER and ics.sniff(path)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    return ics.run(path, since=since, counts=counts, timezone=timezone)
