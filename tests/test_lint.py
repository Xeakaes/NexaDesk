"""B79: app code (excluding vendor and tests) must stay F/E9-clean.

The CI lint step enforces this; this test pins the same rule locally so a
contributor sees it before pushing.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_app_code_is_ruff_clean():
    ruff = Path(sys.executable).parent / "ruff"
    if not ruff.exists():
        import shutil

        ruff_path = shutil.which("ruff")
        if ruff_path is None:
            import pytest

            pytest.skip("ruff not installed")
        ruff = Path(ruff_path)
    result = subprocess.run(
        [str(ruff), "check", "--select", "F,E9",
         "--exclude", "vendor", "--exclude", "tests", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
