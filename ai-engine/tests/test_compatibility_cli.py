from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_documented_compatibility_cli_runs_on_windows_console_encoding():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONIOENCODING="cp949")
    result = subprocess.run([sys.executable, "tools/validate_compatibility.py"], cwd=root,
                            env=env, capture_output=True, timeout=30)
    output = result.stdout.decode("cp949")
    assert result.returncode == 0, output + result.stderr.decode("cp949", errors="replace")
    assert "Result: 7 passed, 0 failed" in output
