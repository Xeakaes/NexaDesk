"""B61: Settings model-fetch workers must survive aggressive replacement.

A per-job signal carrier destroyed on the worker thread while its queued
MetaCall event was still in flight segfaults the app (Shiboken use-after-free
on the SbkObject wrapper). The old signal-based workers failed this test
20/20 in the frozen build and 16/20 unfrozen; the polling design is 0/20.

Run as a subprocess so a segfault kills the child, not the pytest session.
Do NOT wrap in retries — a retry would mask a real regression.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_CHILD = Path(__file__).resolve().parents[1] / "helpers" / "fetch_race_child.py"


@pytest.mark.parametrize("rep", range(3))
def test_settings_fetch_workers_survive_churn(rep):
    p = subprocess.run(
        [sys.executable, str(_CHILD)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, (
        f"child died with {p.returncode} (SIGSEGV = -11 / 139)\n{p.stderr}"
    )
