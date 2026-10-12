"""Tests for TypeCheckerError: structured problems and lazily rendered messages."""
from enforced import typecheck, dataclass, TypeCheckerError
import enforced.utils as utils
import enforced as pv
import pickle
import re
import pytest


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _raised(fn, *args, **kwargs) -> TypeCheckerError:
    with pytest.raises(TypeCheckerError) as exc:
        fn(*args, **kwargs)
    return exc.value


def test_type_problem_fields():
    @typecheck
    def f(a: int, b: str) -> None: ...

    e = _raised(f, 1, 2)
    assert len(e.problems) == 1
    p = e.problems[0]
    assert (p.kind, p.parameter, p.expected, p.value) == ("type", "b", str, 2)
    assert p.origin.__name__ == "f"
    assert e.context == "call"


def test_problems_in_parameter_order():
    @typecheck
    def f(a: int, b: str, c: float) -> None: ...

    e = _raised(f, c = "x", b = 1, a = "y")
    assert [p.parameter for p in e.problems] == ["a", "b", "c"]


def test_varargs_problem_names():
    @typecheck
    def f(*args: int, **kwargs: str) -> None: ...

    e = _raised(f, 1, "x", k = 2)
    assert [p.parameter for p in e.problems] == ["args[1]", "kwargs[k]"]


def test_missing_problem_fields():
    @typecheck
    def f(a: int, b: str, c: float) -> None: ...

    p = _raised(f, b = "x").problems[0]
    assert p.kind == "missing" and p.parameter == ("a", "c") and p.expected == (int, float)


def test_default_problem_and_context():
    @typecheck
    def f(x: int = "bad") -> None: ...      # type: ignore[assignment]

    e = _raised(f)
    assert e.context == "definition"
    assert e.problems[0].kind == "default" and e.problems[0].value == "bad"


def test_return_problem():
    @typecheck(check_return = True)
    def f() -> int:
        return "x"                          # type: ignore[return-value]

    p = _raised(f).problems[0]
    assert (p.kind, p.parameter, p.value) == ("return", "return", "x")


def test_dataclass_assignment_problem():
    @dataclass
    class Point:
        x: float

    pt = Point(1.0)
    e = _raised(setattr, pt, "x", "oops")
    assert e.problems[0].parameter == "x" and e.problems[0].value == "oops"
    assert "Point.x" in _plain(str(e))


def test_message_not_built_until_needed():
    @typecheck
    def f(a: int) -> None: ...

    e = _raised(f, "x")
    assert e._message is None                       # nothing rendered by raising/catching
    text = str(e)
    assert "1 problem found in call" in _plain(text)
    assert e._message is text and str(e) is text    # rendered once, then cached

def test_args_repr_and_pickle():
    @typecheck
    def f(a: int) -> None: ...

    e = _raised(f, "x")
    assert e.args == (str(e),)
    assert repr(e).startswith("TypeCheckerError(")
    clone = pickle.loads(pickle.dumps(e))
    assert type(clone) is TypeCheckerError and str(clone) == str(e)


def test_plain_message_still_supported():
    e = TypeCheckerError("custom message")
    assert str(e) == "custom message" and e.args == ("custom message",) and e.problems == []
    with pytest.raises(TypeError, match = "custom"):
        raise e


def test_problem_repr_is_safe_for_huge_values():
    @typecheck
    def f(a: int) -> None: ...

    p = _raised(f, "x" * 10_000).problems[0]
    assert len(repr(p)) < 200


def test_union_message_lists_every_option():
    @typecheck
    def f(x: int | float | None) -> None: ...

    assert "expected type: 'int' | 'float' | 'NoneType', got type 'str'" in _plain(str(_raised(f, "a")))

    @dataclass(deep = True)
    class Example:
        e: list[int | bytearray]

    text = _plain(str(_raised(Example, [1, None])))
    assert "at index [1] of <Dataclass Example>: expected type: 'int' | 'bytearray', got type 'NoneType'" in text
