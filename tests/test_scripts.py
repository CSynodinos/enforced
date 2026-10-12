"""
``run_tests.sh``: a failing test has to fail the script. It used to end with status 0 whatever
pytest said (review finding 3), so a hook or a CI job built on it could not see a failure.

The script is run in a scratch folder with one small test in it. Skipped where there is no bash.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "run_tests.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32" or not SCRIPT.is_file(),
                                reason = "run_tests.sh needs bash (and to be there)")


def _run(folder: Path, *arguments: str) -> subprocess.CompletedProcess:
    #* "python" in the script is the interpreter that runs these tests.
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run([str(BASH), str(SCRIPT), *arguments], cwd = folder, env = env, capture_output = True,
                          text = True, timeout = 300)


def test_failing_test_fails_the_script(tmp_path):
    (tmp_path / "test_one.py").write_text("def test_it():\n    assert 1 == 2\n")
    done = _run(tmp_path)
    assert done.returncode == 1, done.stdout[-500:] + done.stderr[-500:]
    assert "1 failed" in done.stdout


def test_passing_tests_end_with_status_zero_and_the_simulation_is_looked_for(tmp_path):
    (tmp_path / "test_one.py").write_text("def test_it():\n    assert 1 == 1\n")
    done = _run(tmp_path)
    assert done.returncode == 0 and "1 passed" in done.stdout, done.stdout[-500:] + done.stderr[-500:]
    done = _run(tmp_path, "--no-unit-tests", "--simulation")
    assert done.returncode == 1 and "tests/simulation.py not found" in done.stdout


def test_failing_simulation_fails_the_script_and_arguments_are_checked(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "simulation.py").write_text("raise SystemExit(3)\n")
    assert _run(tmp_path, "--no-unit-tests", "--simulation").returncode == 3
    (tmp_path / "tests" / "simulation.py").write_text("print('Simulation passed!')\n")
    done = _run(tmp_path, "--no-unit-tests", "--simulation")
    assert done.returncode == 0 and "Simulation passed!" in done.stdout
    assert _run(tmp_path, "--nonsense").returncode == 1 and _run(tmp_path, "--help").returncode == 0
