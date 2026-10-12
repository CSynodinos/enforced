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
from enforced import TypeCheckerError, dataclass, enforce
from typing import Self
import dataclasses
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


@known_issue("api.py, _resolve_annotations: Self is the class that defines the method, not the class of the instance",
             NOT_REJECTED)
def test_self_is_the_class_of_the_instance_the_method_is_called_on():
    #* Review finding 28. Exact would be: checked against type(self), which a check of one value can't see.
    @enforce(check_return = True)
    class Base:
        def clone(self) -> Self:
            return Base()                                           # type: ignore[return-value]

    class Child(Base):
        pass

    assert type(Base().clone()) is Base
    with pytest.raises(TypeCheckerError):
        Child().clone()                                             # a Base where Self is Child


@known_issue("_dataclass_override.py, _wrap_setattr: a subclass made a dataclass by the standard library keeps the check "
             "of its base, also for a field it gives another type", TypeCheckerError)
def test_standard_dataclass_below_a_checked_one_may_give_a_field_another_type():
    #* Review finding 23. The way out today: decorate the subclass with enforced.dataclass too.
    @dataclass
    class Base:
        x: int

    @dataclasses.dataclass
    class Child(Base):
        x: str = ""                                                 # type: ignore[assignment]

    assert Child("a").x == "a"
