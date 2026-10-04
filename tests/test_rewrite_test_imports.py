"""`scripts/rewrite_test_imports.py`: the test suite imports the 0.6 paths, never the 0.5 ones that
`logbook._shim` keeps alive (`layout.MOVED`). The script rewrites an import statement from an old
path to the new one and is re-runnable; `--check` on this repository's tests/ finds nothing left."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rewrite_test_imports.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rewrite_test_imports", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("from logbook.store import Logbook\n", "from logbook.core.store import Logbook\n"),
        (
            "from logbook.store import Logbook  # noqa: E402\n",
            "from logbook.core.store import Logbook  # noqa: E402\n",
        ),
        ("from logbook.adapters.takeout import fit\n", "from logbook.contrib.adapters.takeout import fit\n"),
        ("from logbook.adapters import phone\n", "from logbook.contrib.adapters import phone\n"),
        (
            "from logbook.adapters.ios_contacts import _normalise as n\n",
            "from logbook.contrib.adapters.ios_contacts import _normalise as n\n",
        ),
        ("from logbook import sealing\n", "from logbook.core import sealing\n"),
        ("from logbook.setup import wizard\n", "from logbook.commands.setup import wizard\n"),
        (
            "from logbook import adapters, cli, health\n",
            "from logbook import cli\n"
            "from logbook.contrib import adapters\n"
            "from logbook.core import health\n",
        ),
        (
            "from logbook import people, people_merge, resolve  # noqa: E402\n",
            "from logbook.contrib import people_merge  # noqa: E402\n"
            "from logbook.core import people, resolve  # noqa: E402\n",
        ),
        (
            "import logbook.adapters.takeout.maps as maps\n",
            "import logbook.contrib.adapters.takeout.maps as maps\n",
        ),
        ("def f():\n    from logbook import stays\n", "def f():\n    from logbook.core import stays\n"),
    ],
)
def test_an_old_path_is_rewritten(before: str, after: str) -> None:
    module = _load()
    source = "import os\n\n" + before + "\nprint(os)\n"
    assert module.rewrite(source, Path("t.py")) == "import os\n\n" + after + "\nprint(os)\n"


@pytest.mark.parametrize(
    "source",
    [
        "from logbook.core.store import Logbook\n",
        "from logbook import cli, layout, FORMAT\n",
        "import logbook\n",
        "from logbook.contrib.adapters import immich\n",
        "from .store import x\n",
        "import os\nfrom pathlib import Path\n",
    ],
)
def test_a_new_path_is_left_alone(source: str) -> None:
    module = _load()
    assert module.rewrite(source, Path("t.py")) == source


def test_a_bare_dotted_import_is_refused() -> None:
    """`import logbook.store` binds `logbook`; the test then reads `logbook.store.X`, which an
    edited import line alone would break, so the script stops and names the line."""
    module = _load()
    with pytest.raises(SystemExit, match=r"import logbook\.store"):
        module.rewrite("import logbook.store\n", Path("t.py"))


def test_the_suite_is_on_the_new_paths() -> None:
    """`--check` over this repository's tests/: nothing left to rewrite, exit 0."""
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, encoding="utf-8", cwd=ROOT
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip() == "0 file(s) to rewrite", out.stdout
