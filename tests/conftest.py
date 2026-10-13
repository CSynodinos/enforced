import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import enforced._environment as _environment

#* Tiered compilation: a wrapper is compiled after 64 calls by default. Most tests call a function
#* two or three times, the first for the general path and the others for the compiled wrapper, so
#* here a wrapper is compiled at its first call, as it was before there were tiers. Set before any
#* test module is imported: a wrapper takes the value that holds when it is made.
#*
#*     ENFORCED_COMPILE_AFTER=64 python -m pytest -q tests
#*
#* runs the same tests on the general path instead (the few that look at a compiled wrapper are skipped).
_environment.COMPILE_AFTER = int(os.environ.get("ENFORCED_COMPILE_AFTER", "1"))


@pytest.fixture
def compiled_at_once():
    """For a test that looks at the compiled wrapper itself: skipped when the run keeps functions on the general path."""
    if _environment.COMPILE_AFTER != 1:
        pytest.skip("looks at a compiled wrapper: run without ENFORCED_COMPILE_AFTER")


@pytest.fixture(autouse = True)
def plain_messages(monkeypatch):
    """
    Messages are compared as text in these tests, so they are rendered without colours, whatever
    the shell exports (``FORCE_COLOR=1`` used to fail the tests that match on a whole message).
    A test that is about colours switches them back on (see test_formatter.py).
    """
    monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")
