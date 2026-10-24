"""`people mail`: which mail is a person's (RFC 0045, `logbook.core.peoples_mail`). Its arguments are
`people`'s (`people_arguments`); this module is the verb."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from ..core import day_start, peoples_mail, policy, sealing
from ..core.store import Logbook
from .common import EN_DASH, _plural


def cmd_people_mail(a: argparse.Namespace) -> None:
    """`people mail [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json]`: the window's mail lines
    counted, a person's mail and other mail by reason; never an address or a name in the terminal,
    and `--json` carries person ids, never an address."""
    lb = Logbook.find()
    today = day_start.of(lb.meta).today(datetime.now(UTC))
    try:
        first, last = peoples_mail.window(today, a.since, a.until)
        report = peoples_mail.read(lb, first, last)
    except (ValueError, policy.PolicyError, sealing.SealError) as e:
        print(f"people mail: {e}", file=sys.stderr)
        sys.exit(2)
    if a.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
        return
    c = report.counts()
    reasons = c["by_reason"]
    print(f"mail {first} {EN_DASH} {last}: {_plural(c['mail'], 'line')}")
    print(
        f"  people's mail: {c['person']} ({c['received']} received, {c['sent']} sent),"
        f" from or to {_plural(c['people'], 'person', 'people')}"
    )
    said = [
        f"{reasons[peoples_mail.NO_PERSON]} no person on it",
        f"{reasons[peoples_mail.NO_REPLY]} a no-reply sender",
        f"{reasons[peoples_mail.AGENT]} an agent's",
    ]
    if reasons[peoples_mail.SEALED]:
        said.append(f"{reasons[peoples_mail.SEALED]} sealed, not opened on this machine")
    print(f"  other mail: {c['other']} ({', '.join(said)})")
    print("  let go in Hold: nothing yet; Hold writes no fates")
