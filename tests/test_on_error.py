"""
``on_error = "warn"``: a value that fails its check is reported as a ``InvalidDataWarning`` and
the call goes ahead. The option of every API (the owner's design, 2026-10-13: for finding out
what would fail in code that already runs).
"""
from dataclasses import field
from typing import Annotated, Any, Self
from enforced import (
    InvalidDataError, InvalidDataWarning, TypeModel, dataclass, enforce, enforce_class, validate,
    validate_function, validate_record,
    )
import asyncio
import inspect
import subprocess
import sys
import warnings
import pytest
import enforced._environment as environment


class Caught(list):
    """The warnings of a ``with caught()`` block: each one as (text of the first problem line, line number)."""

    def texts(self) -> list[str]:
        return [str(w.message).split("-> ", 1)[-1] for w in self]


class caught:
    """Record every warning, whatever line it comes from (Python's default shows one per line)."""

    def __init__(self, action: str = "always") -> None:
        self.action = action

    def __enter__(self) -> Caught:
        self.inner = warnings.catch_warnings(record = True)
        seen = self.inner.__enter__()
        warnings.simplefilter(self.action)
        self.seen = Caught()
        self.raw = seen
        return self.seen

    def __exit__(self, *exc: Any) -> None:
        self.seen.extend(self.raw)                                  # type: ignore[arg-type]
        self.inner.__exit__(*exc)


@validate(on_error = "warn", check_return = True)
def scale(x: int, factor: float = 2, *, label: str = "") -> int:
    return x * factor if isinstance(x, int) else x                 # type: ignore[return-value]


def test_a_wrong_argument_is_warned_about_and_the_call_goes_ahead():
    with caught() as seen:
        assert scale("ab") == "ab"                                  # called with the value as it was given
    assert seen.texts() == [
        "For parameter x of <Function scale>: expected type: 'int', got type 'str' (Value: 'ab')",
        "For return value of <Function scale>: expected type: 'int', got type 'str' (Value: 'ab')",
        ]
    assert all(w.category is InvalidDataWarning for w in seen)
    assert str(seen[0].message).startswith("1 problem found in call:")


def test_a_right_call_warns_about_nothing_and_what_can_be_converted_is():
    @validate(on_error = "warn")
    def f(a: int, b: float = 0) -> Any:
        return a, b

    with caught() as seen:
        assert f(1) == (1, 0.0) and type(f(1, 2)[1]) is float
        assert f("a", 2) == ("a", 2.0) and type(f("a", 2)[1]) is float      # b converted, a passed as it is
    assert len(seen) == 2 and all("parameter a" in text for text in seen.texts())


def test_several_problems_are_one_warning():
    @validate(on_error = "warn")
    def f(a: int, b: str, c: bytes) -> None: ...

    with caught() as seen:
        f("a", 2, c = 3)
    assert len(seen) == 1 and str(seen[0].message).startswith("3 problems found in call:")
    assert [p.parameter for p in seen[0].message.error.problems] == ["a", "b", "c"]


def test_the_warning_carries_the_error_that_was_not_raised():
    with caught() as seen:
        scale("x", label = 5)
    error = seen[0].message.error
    assert isinstance(error, InvalidDataError) and isinstance(seen[0].message, UserWarning)
    assert [(p.kind, p.parameter, p.expected, p.value) for p in error.problems] == [("type", "x", int, "x"), ("type", "label", str, 5)]
    assert str(seen[0].message) == str(error)


def test_the_warning_is_attributed_to_the_line_of_the_call():
    with caught() as seen:
        line = inspect.currentframe().f_lineno + 1                  # type: ignore[union-attr]
        scale("x")
    assert {(w.filename, w.lineno) for w in seen} == {(__file__, line)}


def test_python_shows_one_warning_per_line_by_default():
    @validate(on_error = "warn")
    def f(a: int) -> None: ...

    with caught("default") as seen:
        for _ in range(50):
            f("in a loop")                                          # one line, one warning
        f("elsewhere")
        f("elsewhere")
    assert seen.texts() == [
        "For parameter a of <Function f>: expected type: 'int', got type 'str' (Value: 'in a loop')",
        "For parameter a of <Function f>: expected type: 'int', got type 'str' (Value: 'elsewhere')",
        "For parameter a of <Function f>: expected type: 'int', got type 'str' (Value: 'elsewhere')",
        ]


def test_the_standard_filters_apply_to_the_category():
    with warnings.catch_warnings():
        warnings.simplefilter("error", InvalidDataWarning)          # back to an exception, by the caller's choice
        with pytest.raises(InvalidDataWarning, match = "For parameter x of <Function scale>"):
            scale("x")
    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("ignore", InvalidDataWarning)
        assert scale("x") == "x" and not seen


# ── what is raised all the same ───────────────────────────────────────────────

@pytest.mark.parametrize("call, said", [
    (lambda: scale(), "Missing required argument"),
    (lambda: scale(1, 2, 3), "too many positional arguments"),
    (lambda: scale(1, nothing = 2), "unexpected keyword argument 'nothing'"),
    (lambda: scale(1, x = 2), "multiple values for argument 'x'"),
    (lambda: scale(label = "a"), "Missing required argument"),
    ])
def test_a_call_that_cannot_be_made_is_raised(call, said):
    with caught() as seen:
        for _ in range(3):
            with pytest.raises(InvalidDataError, match = said):
                call()
    assert not seen


def test_a_missing_argument_next_to_a_wrong_one_is_raised_with_both():
    @validate(on_error = "warn")
    def f(a: int, b: str, *, c: int = 0) -> None: ...

    with caught() as seen, pytest.raises(InvalidDataError) as e:
        f(1, c = "x")
    assert not seen and [p.kind for p in e.value.problems] == ["missing", "type"]


def test_a_mistake_in_the_definition_is_raised():
    @validate(on_error = "warn")
    def bad_default(a: int = "one") -> None: ...                    # type: ignore[assignment]

    @validate(on_error = "warn")
    def unresolved(a: "NoSuchName") -> None: ...                    # type: ignore[name-defined]  # noqa: F821

    with caught() as seen:
        with pytest.raises(InvalidDataError, match = "1 problem found in definition"):
            bad_default(1)
        with pytest.raises(InvalidDataError, match = "NoSuchName"):
            unresolved(1)
    assert not seen


@pytest.mark.parametrize("value", ["log", "", None, True, "WARN", 1, [], {"warn": 1}], ids = repr)
def test_any_other_value_of_the_option_is_refused_where_it_is_written(value):
    def f(a: int) -> None: ...

    class C:
        def m(self, a: int) -> None: ...

    validate_function(f, (1,))                                      # a function that has a wrapper already
    for use in (lambda: validate(on_error = value), lambda: validate(f, on_error = value), lambda: enforce(on_error = value),
                lambda: enforce(C, on_error = value), lambda: enforce_class(C, on_error = value), lambda: dataclass(on_error = value),
                lambda: validate_function(f, (1,), on_error = value),
                lambda: validate_record({"object_name": "f", "record": {"a": int}, "args": (1,), "on_error": value})):
        with pytest.raises(InvalidDataError, match = "on_error must be 'raise' or 'warn'"):
            use()


def test_raise_is_the_default_everywhere():
    for api in (validate, enforce, enforce_class, validate_function, dataclass):
        assert inspect.signature(api).parameters["on_error"].default == "raise"
        assert inspect.signature(api).parameters["on_error"].kind is inspect.Parameter.KEYWORD_ONLY

    @validate(on_error = "raise")
    def f(a: int) -> None: ...

    with caught() as seen, pytest.raises(InvalidDataError):
        f("a")
    assert not seen


# ── every kind of check ───────────────────────────────────────────────────────

class Word(TypeModel[str]):
    @classmethod
    def validate(cls, raw: str) -> str:
        if not raw.isalpha():
            raise ValueError("letters only")
        return raw.lower()


def test_rejected_values_items_and_extra_arguments():
    @validate(on_error = "warn")
    def checked(small: Annotated[int, lambda v: v < 10], word: Word) -> Any:
        return small, word

    @validate(on_error = "warn", deep = True)
    def deep(items: list[int], pair: tuple[int, str] = (1, "a")) -> Any:
        return items, pair

    @validate(on_error = "warn")
    def many(*numbers: int, **named: str) -> Any:
        return numbers, named

    with caught() as seen:
        assert checked(50, "A1") == (50, "A1")                      # neither converted: passed as given
        assert checked(5, "Ab") == (5, "ab") and type(checked(5, "Ab")[1]) is Word
        assert deep([1, "b", 3], (1, 2, 3)) == ([1, "b", 3], (1, 2, 3))
        assert many(1, "b", x = "s", y = 2) == ((1, "b"), {"x": "s", "y": 2})
    assert seen.texts() == [
        "For parameter small of <Function checked>: invalid 'int': failed check v < 10 (Value: 50)\n"
        "    -> For parameter word of <Function checked>: invalid 'Word': letters only (Value: 'A1')",
        "For introspected parameter items at index [1] of <Function deep>: expected type: 'int', got type 'str' (Value: 'b')\n"
        "    -> For parameter pair of <Function deep>: expected type: tuple[int, str] with 2 items, got 3 items (Value: (1, 2, 3))",
        "For parameter numbers[1] of <Function many>: expected type: 'int', got type 'str' (Value: 'b')\n"
        "    -> For parameter named[y] of <Function many>: expected type: 'str', got type 'int' (Value: 2)",
        ]


def test_a_class_under_enforce_with_self_and_properties():
    @enforce(on_error = "warn", check_return = True)
    class Box:
        def __init__(self, size: int = 0) -> None:
            self.size = size

        def merged(self, other: Self | None = None) -> Self:
            return other or self                                    # type: ignore[return-value]

        @classmethod
        def make(cls, size: int) -> Self:
            return cls(size)

        @property
        def half(self) -> int:
            return self.size / 2                                    # type: ignore[return-value]

        @half.setter
        def half(self, value: int) -> None:
            self.size = value * 2

    class Crate(Box):
        pass

    with caught() as seen:
        box = Box("big")                                            # type: ignore[arg-type]
        assert box.size == "big" and Crate().merged(Box()).size == 0        # a Box where Self is Crate
        assert Box.make("s").size == "s"                            # type: ignore[arg-type]
        assert Box(3).half == 1.5
        box.half = "ab"                                             # type: ignore[assignment]
        assert box.size == "abab"
    texts = seen.texts()
    assert [text.split(": expected")[0] for text in texts] == [
        "For parameter size of <Class Box>", "For parameter other of <Method Box.merged>", "For return value of <Method Box.merged>",
        "For parameter size of <Method Box.make>", "For parameter size of <Class Box>", "For return value of <Method Box.half>",
        "For parameter value of <Method Box.half>",
        ]
    assert "expected type: 'Crate' | 'NoneType', got type" in texts[1] and "Crate" in texts[2]     # Self is the class of the call
    assert texts[5].endswith("expected type: 'int', got type 'float' (Value: 1.5)")


def test_a_method_with_its_own_validate_keeps_its_own_policy():
    @enforce(on_error = "warn")
    class Mixed:
        def loose(self, a: int) -> Any:
            return a

        @validate                                                   # its own options stand: raise
        def strict(self, a: int) -> Any:
            return a

    with caught() as seen:
        assert Mixed().loose("a") == "a"
        with pytest.raises(InvalidDataError):
            Mixed().strict("a")
    assert len(seen) == 1


def test_enforce_class_and_the_functional_calls():
    class Plain:
        def m(self, a: int) -> Any:
            return a

    def f(a: int, b: float = 0) -> Any:
        return a, b

    class Callable_:
        def __call__(self, a: int) -> Any:
            return a

    class Other:
        def m(self, a: int) -> Any:
            return a

    enforce_class(Plain, on_error = "warn")
    with caught() as seen:
        assert Plain().m("a") == "a"
        assert validate_function(f, ("a", 1), on_error = "warn") == ("a", 1.0)
        assert validate_function(Callable_(), ("a",), on_error = "warn") == "a"
        assert validate_function(Other().m, ("b",), on_error = "warn") == "b"        # a bound method
        with pytest.raises(InvalidDataError):                       # the same function, the other policy: its own wrapper
            validate_function(f, ("a",))
        assert validate_function(f, ("a",), on_error = "warn") == ("a", 0.0)
    assert len(seen) == 5


def test_a_record_is_returned_as_it_is_with_a_warning():
    spec = {"object_name": "load", "record": {"path": "str", "retries": "int", "ratio": float}, "args": (5, "x"),
            "kwargs": {"ratio": 1}}
    with caught() as seen:
        assert validate_record({**spec, "on_error": "warn"}) == ((5, "x"), {"ratio": 1.0})
        with pytest.raises(InvalidDataError):                       # cached apart: the same record, raising
            validate_record(spec)
        with pytest.raises(InvalidDataError):
            validate_record({**spec, "on_error": "raise"})
        assert validate_record({**spec, "on_error": "warn"}) == ((5, "x"), {"ratio": 1.0})
        with pytest.raises(InvalidDataError, match = "Missing required argument"):
            validate_record({**spec, "args": (), "on_error": "warn"})
    assert len(seen) == 2 and str(seen[0].message).startswith("2 problems found in call")


def test_a_coroutine_function():
    @validate(on_error = "warn", check_return = True)
    async def fetch(url: str) -> bytes:
        return url                                                  # type: ignore[return-value]

    async def main() -> Any:
        line = inspect.currentframe().f_lineno + 1                  # type: ignore[union-attr]
        return await fetch(5), line                                 # type: ignore[arg-type]

    with caught() as seen:
        result, line = asyncio.run(main())
    assert result == 5 and inspect.iscoroutinefunction(fetch)
    assert seen.texts() == [
        "For parameter url of <Function fetch>: expected type: 'str', got type 'int' (Value: 5)",
        "For return value of <Function fetch>: expected type: 'bytes', got type 'int' (Value: 5)",
        ]
    assert {(w.filename, w.lineno) for w in seen} == {(__file__, line)}     # the line that awaits it


# ── dataclasses ───────────────────────────────────────────────────────────────

def test_a_dataclass_stores_what_it_was_given():
    @dataclass(on_error = "warn")
    class Order:
        qty: int
        price: float = 0
        tags: list = field(default_factory = list)
        note: str = field(init = False, default = "")

        def __post_init__(self) -> None:
            self.note = self.qty                                    # type: ignore[assignment]

    with caught() as seen:
        order = Order("two", 3)                                     # type: ignore[arg-type]
        assert (order.qty, order.price, type(order.price)) == ("two", 3.0, float)
        order.qty = "four"                                          # type: ignore[assignment]
        order.price = "free"                                        # type: ignore[assignment]  # a field with a converter
        order.price = 2
        assert (order.qty, order.price, type(order.price)) == ("four", 2.0, float)
        assert Order(1).note == 1
    assert seen.texts() == [
        "For parameter qty of <Dataclass Order>: expected type: 'int', got type 'str' (Value: 'two')",
        "Field Order.qty of <Dataclass Order>: expected type: 'int', got type 'str' (Value: 'four')",
        "Field Order.price of <Dataclass Order>: expected type: 'float', got type 'str' (Value: 'free')",
        "Field Order.note of <Dataclass Order>: expected type: 'str', got type 'int' (Value: 1)",     # from __post_init__
        ]
    assert "field assignment" in str(seen[2].message)


@pytest.mark.parametrize("options", [{}, {"frozen": True}, {"check_assignment": False}, {"slots": True}, {"deep": True}, {"kw_only": True}])
def test_a_dataclass_under_its_options(options):
    @dataclass(on_error = "warn", **options)
    class Point:
        x: int
        items: list[int] = field(default_factory = lambda: ["made"])      # type: ignore[list-item]

    with caught() as seen:
        point = Point(x = "a")                                      # type: ignore[arg-type]
        assert point.x == "a" and point.items == ["made"]
    expected = ["For parameter x of <Dataclass Point>: expected type: 'int', got type 'str' (Value: 'a')"]
    if options.get("deep"):                                         # what the factory returned is looked into
        expected.append("Introspected field Point.items at index [0] of <Dataclass Point>: expected type: 'int', got type 'str' (Value: 'made')")
    assert seen.texts() == expected


def test_a_default_that_contradicts_its_annotation_is_raised():
    @dataclass(on_error = "warn")
    class Bad:
        x: int = "one"                                              # type: ignore[assignment]

    with caught() as seen, pytest.raises(InvalidDataError, match = "1 problem found in definition"):
        Bad()
    assert not seen


# ── both tiers ────────────────────────────────────────────────────────────────

def test_both_tiers_warn_alike(monkeypatch):
    def build(after: int) -> Any:
        monkeypatch.setattr(environment, "COMPILE_AFTER", after)

        @validate(on_error = "warn", check_return = True)
        def f(a: int, b: float = 0, *, c: Word = "x") -> int:      # type: ignore[assignment]
            return a

        @dataclass(on_error = "warn")
        class D:
            x: int
            y: float = 0
            tags: list[int] = field(default_factory = list)

        @enforce(on_error = "warn")
        class C:
            def m(self, a: int, other: Self | None = None) -> Any:
                return a

        return f, D, C

    def outcomes(made: Any) -> list[Any]:
        f, D, C = made
        calls = [lambda: f(1), lambda: f("a"), lambda: f(1, "b"), lambda: f(1, 2, c = "1"), lambda: f("a", "b", c = 5), lambda: f(),
                 lambda: f(1, 2, 3), lambda: repr(D(1, 2)), lambda: repr(D("a")), lambda: repr(D(1, "b", "c")),
                 lambda: setattr(D(1), "x", "s"), lambda: setattr(D(1), "y", 3), lambda: C().m("a"), lambda: C().m(1, 2)]
        out: list[Any] = []
        for _ in range(3):
            for call in calls:
                with caught() as seen:
                    try:
                        result: Any = ("ok", repr(call()))
                    except InvalidDataError as e:
                        result = ("raised", str(e))
                out.append((result, seen.texts()))
        return out

    general, compiled = outcomes(build(10 ** 6)), outcomes(build(1))
    assert general == compiled
    assert sum(len(texts) for _, texts in general) == 3 * 11       # one warning per mistake, on either tier


def test_switched_off_there_is_nothing_to_warn_about():
    code = ("import warnings; warnings.simplefilter('error')\n"
            "from enforced import validate, dataclass, validate_function\n"
            "@validate(on_error = 'warn')\n"
            "def f(a: int): return a\n"
            "@dataclass(on_error = 'warn')\n"
            "class P:\n    x: int\n"
            "print(f('a'), P('b').x, validate_function(f, ('c',), on_error = 'warn'))")
    done = subprocess.run([sys.executable, "-c", code], capture_output = True, text = True,
                          env = {"ENFORCED_VALIDATION_OFF": "1", "PATH": "", "PYTHONPATH": str(__import__("pathlib").Path(__file__).parent.parent)})
    assert done.stdout.strip() == "a b c", done.stderr


def test_an_uncaught_warning_is_printed_once_with_the_line_of_the_call():
    code = ("from enforced import validate\n"
            "@validate(on_error = 'warn')\n"
            "def f(a: int): return a\n"
            "for _ in range(5):\n"
            "    f('a')\n"
            "print('done')")
    done = subprocess.run([sys.executable, "-c", code], capture_output = True, text = True,
                          env = {"ENFORCED_COLOURS_OFF": "1", "PATH": "", "PYTHONPATH": str(__import__("pathlib").Path(__file__).parent.parent)})
    assert done.stdout.strip() == "done"
    assert done.stderr.count("InvalidDataWarning: 1 problem found in call:") == 1 and "<string>:5:" in done.stderr


def test_a_warning_made_an_exception_stands_alone_and_pickles():
    import pickle

    @dataclass(on_error = "warn", deep = True)
    class Bag:
        items: list[int] = field(default_factory = list)

    bag = Bag()
    with warnings.catch_warnings():
        warnings.simplefilter("error", InvalidDataWarning)
        with pytest.raises(InvalidDataWarning, match = "Introspected field Bag.items at index") as raised:
            bag.items = [1, "b"]                                    # type: ignore[list-item]
        assert raised.value.__context__ is None                     # not "during handling of" the error it stands for
        with pytest.raises(InvalidDataWarning) as raised:
            scale("x")
        assert raised.value.__context__ is None
    back = pickle.loads(pickle.dumps(raised.value))
    assert str(back) == str(raised.value) and [p.parameter for p in back.error.problems] == ["x"]
