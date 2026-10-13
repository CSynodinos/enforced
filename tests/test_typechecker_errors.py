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
import enforced._formatting_tool as _formatting_tool              # noqa: E402

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
    real = _formatting_tool.colours_on
    monkeypatch.setattr(_formatting_tool, "colours_on", lambda: asked.append(1) or real())

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


# ── the one pass the general path makes over a call (PreparedChecker._scan) ──────────────────────

from enforced import TypeModel                                  # noqa: E402
from typing import Any                                          # noqa: E402


def _plain_text(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


def _old_way(checked, args, kwargs):
    """What the three passes and the full path make of a call: the checker with its plan taken away."""
    checker = checked.__globals__["_pv_checker"]
    plan, checker.plan = checker.plan, None
    try:
        return _outcome(checker.check_inputs, args, kwargs)
    finally:
        checker.plan = plan


def _outcome(call, *args):
    try:
        return ("ok", repr(call(*args)))
    except TypeCheckerError as e:
        return ("error", _plain_text(e), [(p.kind, p.parameter, repr(p.expected), repr(p.value), repr(p.annotation)) for p in e.problems])


class _Even(TypeModel[int]):
    @classmethod
    def validate(cls, raw: int) -> int:
        if raw % 2:
            raise ValueError("must be even")
        return raw


@pytest.mark.parametrize("options", [{}, {"coerce": True}, {"convert": False}, {"allow_subclass": False}], ids = str)
def test_the_single_pass_says_what_the_three_passes_said(options):
    #* Same arguments back, same problems, same order, same words, for calls of every shape.
    from typing import Annotated, Literal

    @typecheck(**options)
    def f(a: int, b: float = 1.0, /, c: str = "c", *, d: _Even = _Even(2), e: Annotated[int, lambda v: v > 0] = 1,
          g: Literal["r", "w"] = "r", h=None, i: float | None = None) -> None: ...

    f(1)
    checker = f.__globals__["_pv_checker"]
    assert checker.plan is not None
    rng = random.Random(7)
    values = [1, 2, 3, -1, 1.5, "x", "r", "4", None, True, [1], 2.0]
    seen = set()
    for _ in range(1500):
        args = tuple(rng.choice(values) for _ in range(rng.randint(0, 4)))
        kwargs = {name: rng.choice(values) for name in rng.sample(["a", "c", "d", "e", "g", "h", "i", "zz"], rng.randint(0, 4))}
        new, old = _outcome(checker.check_inputs, args, kwargs), _old_way(f, args, kwargs)
        assert new == old, (args, kwargs)
        seen.add(new[0] if new[0] == "ok" else tuple(sorted({kind for kind, *_ in new[2]})) or "binding")
    assert {"ok", "binding", ("type",), ("missing",)} <= seen and any("invalid" in kinds for kinds in seen if kinds != "ok")


def test_problems_come_in_the_order_of_the_parameters_however_they_are_passed():
    @typecheck
    def f(a: int, b: str, c: bytes, *, d: int = 0) -> None: ...

    f(1, "b", b"c")
    for call in (lambda: f("x", 2, d = "y", c = 3), lambda: f(d = "y", c = 3, b = 2, a = "x"), lambda: f("x", c = 3, d = "y", b = 2)):
        with pytest.raises(TypeCheckerError) as e:
            call()
        assert [p.parameter for p in e.value.problems] == ["a", "b", "c", "d"]
    with pytest.raises(TypeCheckerError) as e:
        f(1, d = "y")                                               # missing first, then what is wrong with what was given
    assert [(p.kind, p.parameter) for p in e.value.problems] == [("missing", ("b", "c")), ("type", "d")]


def test_a_missing_argument_next_to_one_that_does_not_fit_still_gets_the_hint():
    @typecheck
    def f(name: str, age: int, city: str = "x") -> None: ...

    f("a", 1)
    with pytest.raises(TypeCheckerError) as e:
        f(30)
    assert "Missing required argument for <Function f>: name (expecting type str) (inferred)" in _plain_text(e.value)
    with pytest.raises(TypeCheckerError) as e:
        f("ana")
    assert "Missing required argument for <Function f>: age (expecting type int)" in _plain_text(e.value)
    assert "(inferred)" not in _plain_text(e.value)


def test_what_can_be_converted_is_and_the_rest_is_reported():
    @typecheck
    def f(a: float, b: float, *, c: float = 0.0) -> tuple:
        return a, b, c

    assert f(1, 2, c = 3) == (1.0, 2.0, 3.0) and [type(v) for v in f(1, 2, c = 3)] == [float] * 3
    checker = f.__globals__["_pv_checker"]
    args, kwargs = (1, 2.5), {"c": 4}
    out_args, out_kwargs = checker.check_inputs(args, kwargs)
    assert out_args == (1.0, 2.5) and out_kwargs == {"c": 4.0} and args == (1, 2.5) and kwargs == {"c": 4}     # the caller's stay
    same = (1.0, 2.0)
    assert checker.check_inputs(same, {})[0] is same                # nothing to convert: handed back as it came
    with pytest.raises(TypeCheckerError) as e:
        f(1, "x", c = "y")
    assert [p.parameter for p in e.value.problems] == ["b", "c"]


@pytest.mark.usefixtures("compiled_at_once")
def test_the_reason_for_a_rejected_value_is_not_asked_for_again():
    #* The converter runs validate and is refused. The message needs the reason, and used to run
    #* validate once more to get it; and the general path, handed the call by the compiled wrapper,
    #* tried the conversion again. It was three runs per wrong call, and is one: the wrapper says
    #* which parameter it couldn't convert.
    runs = []

    class Counted(TypeModel[str]):
        @classmethod
        def validate(cls, raw: str) -> str:
            runs.append(raw)
            if "@" not in raw:
                raise ValueError("no @ in it")
            return raw

    @typecheck
    def f(address: Counted, other: Counted | None = None) -> Any:
        return address

    assert f("a@b") == "a@b"
    runs.clear()
    for _ in range(3):
        with pytest.raises(TypeCheckerError) as e:
            f("nope")
        assert "invalid 'Counted': no @ in it (Value: 'nope')" in _plain_text(e.value)
    assert runs == ["nope"] * 3                                     # once per call
    checker = f.__globals__["_pv_checker"]
    runs.clear()
    with pytest.raises(TypeCheckerError):
        checker.check_inputs(("nope",), {})
    assert runs == ["nope"]                                         # the general path alone: once
    with pytest.raises(TypeCheckerError) as e:
        f("x", "y")
    assert [p.detail for p in e.value.problems] == ["no @ in it", "no @ in it"]
    #* What one call left behind is not taken by the next: another value, another reason.
    class Other(TypeModel[str]):
        @classmethod
        def validate(cls, raw: str) -> str:
            raise ValueError(f"never {raw}")

    @typecheck
    def g(x: Other) -> Any: ...

    for word in ("one", "two"):
        with pytest.raises(TypeCheckerError) as e:
            g(word)
        assert e.value.problems[0].detail == f"never {word}"


def test_an_error_takes_its_list_of_problems_as_it_is():
    @typecheck
    def f(a: int) -> None: ...

    with pytest.raises(TypeCheckerError) as e:
        f("x")
    error = e.value
    assert type(error.problems) is list and error.args == (str(error),) and error.context == "call"
    assert TypeCheckerError("plain").args == ("plain",) and TypeCheckerError("plain").problems == []
    assert TypeCheckerError(problems = tuple(error.problems)).problems == error.problems


# ── what an error costs: made late, and left to nobody ───────────────────────────────────────────

def test_the_problems_of_a_wrong_call_are_made_when_they_are_read():
    @typecheck(check_return = True)
    def f(a: int, b: str = "", *, c: float = 0.0) -> int:
        return "text" if a == 0 else a                              # type: ignore[return-value]

    for call, expected in ((lambda: f("x", 2), [("type", "a", int, "x"), ("type", "b", str, 2)]),
                           (lambda: f(1, c = "y"), [("type", "c", float, "y")]),
                           (lambda: f(b = "z"), [("missing", ("a",), (int,), None)]),
                           (lambda: f(0), [("return", "return", int, "text")])):
        error = _raised(call)
        assert error._problems is None                              # nothing made yet: the error knows what failed
        first = error.problems
        assert [(p.kind, p.parameter, p.expected, p.value) for p in first] == expected
        assert error.problems is first and error._pending is None   # made once, and what they were made from let go
        assert all(p.origin is f.__wrapped__ for p in first)
    #* The message is the same whichever is read first, and a caller may still hand over a list.
    assert str(_raised(f, "x", 2)) == str(error := _raised(f, "x", 2)) and len(error.problems) == 2
    error.problems = ()
    assert error.problems == []
    assert pickle.loads(pickle.dumps(_raised(f, 1, 2))).problems[0].parameter == "b"


def test_an_error_is_freed_without_the_collector():
    #* The traceback of an error holds the frame it was raised in. A frame that holds the error in
    #* a local makes a cycle of the two, and so does a problem whose renderer holds the problem:
    #* each wrong call then left its objects to the collector, and paid for it (350 ns of 1,100).
    import gc
    from typing import Annotated
    from enforced import TypeModel, enforce

    class Word(TypeModel[str]):
        @classmethod
        def validate(cls, raw: str) -> str:
            if not raw.isalpha():
                raise ValueError("letters only")
            return raw

    @typecheck(check_return = True)
    def f(a: int, b: str = "", *, c: Annotated[int, lambda v: v > 0] = 1, w: Word = "a") -> int:     # type: ignore[assignment]
        return "text" if a == 0 else a                              # type: ignore[return-value]

    @typecheck(deep = True)
    def deep(items: list[int], *more: int) -> None: ...

    @dataclass
    class Point:
        x: float
        tags: list[int]

    @dataclass(deep = True)
    class Deep:
        tags: list[int]

    @enforce
    class Box:
        def put(self, item: int) -> None: ...

    point, box, held = Point(1.0, []), Box(), Deep([])
    calls = [lambda: f("x"), lambda: f(1, 2), lambda: f(), lambda: f(1, c = -1), lambda: f(1, w = "1"), lambda: f(0),
             lambda: f(1, 2, 3), lambda: f(1, z = 1), lambda: f(1, a = 1), lambda: deep([1, "a"]), lambda: deep([], "a"),
             lambda: Point("a", []), lambda: setattr(point, "x", "a"), lambda: setattr(held, "tags", ["a"]),
             lambda: box.put("a")]
    def caught(call: Any, read: bool) -> None:                      # not pytest.raises: what it returns is a cycle itself
        try:
            call()
        except TypeCheckerError as e:
            if read:
                assert str(e) and e.problems is not None            # the problems and the text are made
        else:
            raise AssertionError("no error")

    for call in calls:
        for _ in range(70):                                         # past the call at which a wrapper is compiled
            caught(call, True)
        for _ in range(3):                                          # what earlier tests left takes more than one pass
            gc.collect()
        gc.disable()
        try:
            for _ in range(20):
                caught(call, False)
                caught(call, True)
            left = gc.collect()
        finally:
            gc.enable()
        assert left == 0, f"call {calls.index(call)}: {left} objects left to the collector"


def test_a_failing_check_runs_once(monkeypatch):
    #* Review finding 46: the check ran to fail, again on the general path the compiled wrapper
    #* handed the call to, and a third time for the reason. Its first run leaves the reason behind.
    #* (A check that passes, for another argument of the same wrong call, is still run by both.)
    from typing import Annotated
    import enforced._environment as environment
    runs: list[Any] = []

    def small(v: int) -> bool:
        runs.append(("small", v))
        return v < 10

    def even(v: int) -> Any:
        runs.append(("even", v))
        if v % 2:
            raise ValueError("odd")
        return v != 4 and "yes"                                     # False for 4: a falsy answer that is no exception

    def blank(v: str) -> str:
        runs.append(("blank", v))
        return v.strip()                                            # '' for a blank text: falsy, and not False

    for after in (1, 10 ** 6):                                      # the compiled wrapper, and the general path alone
        monkeypatch.setattr(environment, "COMPILE_AFTER", after)

        @typecheck
        def f(a: Annotated[int, small], b: Annotated[int, small, even] = 0, *, c: Annotated[str, blank] = "x") -> Any:
            return a

        assert f(1, 2, c = "y") == 1 and f(3) == 3
        for call, failing, reasons in (
                (lambda: f(50), [("small", 50)], ["failed check small"]),
                (lambda: f(1, 3), [("even", 3)], ["odd"]),
                (lambda: f(1, 4), [("even", 4)], ["failed check even"]),
                (lambda: f(1, 50), [("small", 50)], ["failed check small"]),
                (lambda: f(1, c = " "), [("blank", " ")], ["failed check blank, which returned ''"]),
                (lambda: f(50, 3, c = " "), [("small", 50), ("even", 3), ("blank", " ")],
                 ["failed check small", "odd", "failed check blank, which returned ''"]),
                (lambda: f("a"), [], None),                         # the wrong type: no check is asked at all
                ):
            for _ in range(3):
                runs.clear()
                error = _raised(call)
                assert [runs.count(run) for run in failing] == [1] * len(failing), (after, runs)
                if reasons is None:
                    assert [p.kind for p in error.problems] == ["type"] and not runs
                else:
                    assert [(p.kind, p.detail) for p in error.problems] == [("invalid", reason) for reason in reasons]
        #* What one call left behind is not taken for another: 50 fails ``small`` here, then passes a check of its own.
        @typecheck
        def g(a: Annotated[int, lambda v: v > 10]) -> Any:
            return a

        _raised(f, 50)
        assert g(50) == 50
        assert _raised(g, 5).problems[0].detail == "failed check v > 10"
