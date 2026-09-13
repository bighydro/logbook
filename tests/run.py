"""Zero-dependency test runner: python tests/run.py  (pytest also works if installed)."""

import inspect
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_chain

failed = 0
for name, fn in inspect.getmembers(test_chain, inspect.isfunction):
    if not name.startswith("test_"):
        continue
    try:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d)) if "tmp_path" in inspect.signature(fn).parameters else fn()
        print("ok   ", name)
    except Exception:
        failed += 1
        print("FAIL ", name)
        traceback.print_exc()
sys.exit(1 if failed else 0)
