"""Tests for TypeCheckerError: structured problems and lazily rendered messages."""
from enforced import typecheck, dataclass, TypeCheckerError
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


# ── review finding 40: a call that can't be bound is said at once, in Python's words ──────────────

import inspect                                                  # noqa: E402
import pickle                                                   # noqa: E402
import random                                                   # noqa: E402
import pytest                                                   # noqa: E402
from enforced import TypeCheckerError, typecheck                # noqa: E402
import enforced.formatting_tool as formatting_tool              # noqa: E402

_SHAPES = [
    "def f(a: int, b: int = 0): pass",
    "def f(a: int, /, b: int = 0, *, c: int = 1): pass",
    "def f(a: int, *args: int, c: int = 0): pass",
    "def f(a: int, b: int = 0, /, **kw: int): pass",
    "def f(*, a: int = 0, b: int = 1): pass",
    "def f(a: int, b: int, /): pass",
    "def f(a: int = 0, *args: int, **kw: int): pass",
    "def f(self, a: int, b: int = 2): pass",
    ]


@pytest.mark.parametrize("source", _SHAPES)
def test_a_binding_error_reads_as_signature_bind_words_it(source):
    #* The three usual ones (too many arguments, a name given twice, an unknown keyword) are no
    #* longer found by running Signature.bind. What is said has to be what it would have said.
    namespace: dict = {}
    exec(source, namespace)
    plain, checked = namespace["f"], typecheck(namespace["f"])
    signature, rng, seen = inspect.signature(plain), random.Random(source), set()
    for _ in range(300):
        args = tuple(1 for _ in range(rng.randint(0, 4)))
        kwargs = {name: 1 for name in rng.sample(["a", "b", "c", "d", "self", "args", "kw"], rng.randint(0, 3))}
        try:
            signature.bind(*args, **kwargs)
            expected = None
        except TypeError as e:
            expected = str(e)
        try:
            checked(*args, **kwargs)
            said = None
        except TypeCheckerError as e:
            said = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
        if expected is None:
            assert said is None, (args, kwargs, said)
        elif expected.startswith(("too many positional", "multiple values", "got an unexpected keyword")):
            assert said == expected, (args, kwargs)
            seen.add(expected.split()[0])
        else:
            assert said is not None, (args, kwargs, expected)       # a missing argument, or one of the rarer kinds
    assert seen                                                     # each shape met at least one of the three


def test_a_binding_error_is_put_together_when_it_is_read(monkeypatch):
    asked = []
    real = formatting_tool.colours_on
    monkeypatch.setattr(formatting_tool, "colours_on", lambda: asked.append(1) or real())

    @typecheck
    def f(a: int, b: str = "x") -> None: ...

    errors = []
    for call in (lambda: f(1, "x", 3), lambda: f(1, a = 2), lambda: f(1, c = 3)):
        with pytest.raises(TypeCheckerError) as e:
            call()
        errors.append(e.value)
    assert asked == []                                              # raised and caught: nothing was formatted
    assert [str(e) for e in errors] == ["too many positional arguments", "multiple values for argument 'a'",
                                         "got an unexpected keyword argument 'c'"]
    assert all(e.problems == [] and e.context == "call" and e.args == (str(e),) for e in errors)
    back = pickle.loads(pickle.dumps(errors[2]))
    assert str(back) == "got an unexpected keyword argument 'c'" and isinstance(back, TypeError)


def test_a_missing_argument_is_still_explained_in_full():
    @typecheck
    def f(name: str, age: int, city: str = "x") -> None: ...

    with pytest.raises(TypeCheckerError) as e:
        f("ana")
    assert "Missing required argument for <Function f>: age (expecting type int)" in re.sub(r"\x1b\[[0-9;]*m", "", str(e.value))
    with pytest.raises(TypeCheckerError) as e:
        f(30)                                                       # the one given fits the other parameter better
    assert "name (expecting type str) (inferred)" in re.sub(r"\x1b\[[0-9;]*m", "", str(e.value))
