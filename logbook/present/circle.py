"""The circle source: a page another member of the circle shared. Not built yet; names nobody."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ..chain import Line
from ..places import Place
from ..resolve import Identity, Ref
from ..stays import Segment
from .model import Presence


def from_circle(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    """A circle page that places someone at the stay. The circle's bundle format is not defined
    yet (ARCHITECTURE: the circle); this names nobody until it is."""
    return []
