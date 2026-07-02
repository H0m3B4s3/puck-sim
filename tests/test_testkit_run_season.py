"""Lightweight subprocess tests for testkit/run_season.py -- DEVPLAN.md Step 1.14.

DEVPLAN.md's actual done-criteria for this step is a CLI invocation ("python
testkit/run_season.py --seed 1 --seasons 3 completes without exceptions, quickly; same seed ->
identical printed output"), not a pytest suite -- these tests are a fast smoke-test companion,
invoking the real script as a subprocess (mirroring how an actual user/CI would run it) rather than
importing its internals, so a genuine packaging/import regression (e.g. `pucksim` not resolving
from the script's own directory) would actually be caught. Uses a small ``--games-per-season``
override throughout to keep each subprocess call fast -- the real 82-game/32-team scale is
exercised separately (by hand, per this step's instructions), not in this test file.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "testkit" / "run_season.py"


def _run(args):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_runs_cleanly_with_no_traceback():
    result = _run(["--seed", "1", "--seasons", "1", "--games-per-season", "6"])
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert result.stderr == ""


def test_stdout_contains_expected_summary_sections():
    result = _run(["--seed", "1", "--seasons", "1", "--games-per-season", "6"])
    assert "Standings" in result.stdout
    assert "Top 10 Scorers" in result.stdout
    assert "Top 5 Goalies" in result.stdout
    assert "Total elapsed wall-clock time" in result.stdout
    # Sanity check some real team-name content shows up (built from leaguegen's city/nickname
    # pools -- not asserting a specific name, just that the standings table actually rendered
    # rows, not just headers).
    assert "Conference --" in result.stdout


def test_multi_season_run_labels_each_season_and_bumps_season_year():
    result = _run(["--seed", "1", "--seasons", "3", "--games-per-season", "6"])
    assert result.returncode == 0
    assert "season_year=2025" in result.stdout
    assert "season_year=2026" in result.stdout
    assert "season_year=2027" in result.stdout
    assert result.stdout.count("Standings") == 3


def test_same_seed_produces_identical_stdout():
    """Explicit MVP determinism done-criteria: same seed -> identical printed output.

    The one intentionally-excluded line is the final wall-clock timing line, which is real
    elapsed time and expected to vary run-to-run by design (it is not part of the sim's
    deterministic output, just a courtesy diagnostic printed last) -- every other line, including
    full standings/top-scorer/top-goalie content across all seasons, must match exactly.
    """
    args = ["--seed", "1", "--seasons", "3", "--games-per-season", "6"]
    first = _run(args)
    second = _run(args)

    assert first.returncode == 0
    assert second.returncode == 0

    def strip_timing_line(stdout: str) -> str:
        return "\n".join(
            line for line in stdout.splitlines() if not line.startswith("Total elapsed")
        )

    assert strip_timing_line(first.stdout) == strip_timing_line(second.stdout)


def test_different_seeds_produce_different_output():
    """Sanity check the seed is actually wired to the RNG (not silently ignored)."""
    result_a = _run(["--seed", "1", "--seasons", "1", "--games-per-season", "6"])
    result_b = _run(["--seed", "2", "--seasons", "1", "--games-per-season", "6"])
    assert result_a.stdout != result_b.stdout


@pytest.mark.parametrize("rule", ["standard", "retro", "three_two_one_zero"])
def test_all_standings_rules_run_without_exception(rule):
    result = _run([
        "--seed", "3", "--seasons", "1", "--games-per-season", "6",
        "--standings-rule", rule,
    ])
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_save_path_writes_a_file(tmp_path):
    save_path = tmp_path / "smoke_test_save.json"
    result = _run([
        "--seed", "4", "--seasons", "1", "--games-per-season", "6",
        "--save-path", str(save_path),
    ])
    assert result.returncode == 0
    assert save_path.exists()
    assert f"Saved final world state to {save_path}" in result.stdout
