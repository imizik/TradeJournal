"""Cached session hooks must retire without launching models or blocking exit."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'pr_review.py'


@pytest.mark.parametrize('owner', ['codex', 'claude'])
def test_cached_hook_is_a_silent_noop(owner, tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), 'hook', '--owner', owner],
        input='not even valid hook JSON', text=True, capture_output=True,
        cwd=tmp_path, env={'PATH': ''}, timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ''
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('command', ['review', 'finish', 'retry'])
def test_retired_command_cannot_report_success(command, tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), command], text=True,
        capture_output=True, cwd=tmp_path, env={'PATH': ''}, timeout=5,
    )
    assert result.returncode == 2
    assert 'docs/agent/pr-review.md' in result.stderr
    assert result.stdout == ''
    assert list(tmp_path.iterdir()) == []
