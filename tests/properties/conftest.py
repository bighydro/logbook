"""The Hypothesis profile of the property suite: deterministic (`derandomize`, so a CI run draws the
same examples every time and a failure reproduces on a laptop), no deadline (a record on disk is
slower on a Windows runner than on a Mac), and the blob printed with a failure so it can be replayed
with `@reproduce_failure`. `pyproject.toml` registers no profile; this one is loaded here, for this
package only (a module outside it keeps its own `@settings`)."""

from __future__ import annotations

from hypothesis import settings

settings.register_profile("properties", derandomize=True, deadline=None, print_blob=True)
