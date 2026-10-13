"""
Known issues: bugs and gaps that aren't fixed yet. They are also listed in CLAUDE.md and in phase 7
of tests/simulation.py.

Each test states the *correct* behaviour and is marked as an expected failure, so the suite stays
green. The marks are strict and name the exception the issue produces today: a test that starts
passing, or that fails in any other way, fails the suite. When an issue is fixed, move its test to
the file of its subject and drop the mark.

    python -m pytest tests/test_known_issues.py -rx           # list them, with where each one is
    python -m pytest tests/test_known_issues.py --runxfail    # run them as normal tests: the failures in full
"""
import pytest


#* For an issue that lets a bad value through: what pytest.raises fails with ("DID NOT RAISE").
NOT_REJECTED = pytest.fail.Exception


def known_issue(where: str, raises: type[BaseException]) -> pytest.MarkDecorator:
    """Mark a test as stating the correct behaviour of an issue that isn't fixed yet, found at ``where``."""
    return pytest.mark.xfail(strict = True, raises = raises, reason = f"not fixed yet: {where}")


def test_the_marks_are_strict():
    """
    A known issue that starts to pass has to fail the suite, or its test would stay here for good.
    (This test also gives the file something to run while no issue is open: pytest ends with
    status 5 for a file without a single test.)
    """
    mark = known_issue("nowhere", NOT_REJECTED).mark
    assert mark.name == "xfail" and mark.kwargs["strict"] is True and mark.kwargs["raises"] is NOT_REJECTED
