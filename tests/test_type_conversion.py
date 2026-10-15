"""Tests for value conversion (convert=True by default) and coercion (coerce=False by default)."""
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Literal, NewType
from enforced import typecheck, enforce, dataclass, typecheck_record, TypeCheckerError
import asyncio
import dataclasses
import datetime
import enum
import functools
import pathlib
import re
import uuid
import pytest


def _plain(e: BaseException) -> str:
    """Strip ANSI colour codes so messages can be matched as text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


def _same(result, expected) -> bool:
    return type(result) is type(expected) and result == expected


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


# ═════════════════════════════════════════════════════════════════════════════
#  CONVERSION (on by default): the PEP 484 numeric tower, exact values only
# ═════════════════════════════════════════════════════════════════════════════

def test_int_to_float_converted():
    @typecheck
    def f(x: float) -> float:
        return x

    assert _same(f(1), 1.0)


def test_int_and_float_to_complex_converted():
    @typecheck
    def f(x: complex) -> complex:
        return x

    assert _same(f(2), 2 + 0j)
    assert _same(f(1.5), 1.5 + 0j)


def test_conversion_is_exact_only():
    @typecheck
    def f(x: float) -> float:
        return x

    assert _same(f(2**53), float(2**53))
    with pytest.raises(TypeCheckerError):
        f(2**53 + 1)            # float can't represent it exactly


def test_huge_int_rejected_not_crashing():
    @typecheck
    def f(x: float) -> float:
        return x

    with pytest.raises(TypeCheckerError):
        f(10**400)              # OverflowError inside the conversion must not leak


def test_bool_never_converted_to_number():
    @typecheck
    def f(x: float, y: complex) -> None:
        pass

    with pytest.raises(TypeCheckerError):
        f(True, 1j)
    with pytest.raises(TypeCheckerError):
        f(1.0, False)


def test_float_not_converted_to_int():
    @typecheck
    def f(x: int) -> int:
        return x

    with pytest.raises(TypeCheckerError):
        f(1.0)                  # narrowing is coercion, not conversion
    with pytest.raises(TypeCheckerError):
        f(1.5)


def test_convert_false_rejects():
    @typecheck(convert = False)
    def f(x: float) -> float:
        return x

    with pytest.raises(TypeCheckerError):
        f(1)


def test_valid_values_passed_through_untouched():
    @typecheck
    def f(x: float, items: list[int]) -> tuple:
        return x, items

    value, items = 1.5, [1, 2]
    got_value, got_items = f(value, items)
    assert got_value is value and got_items is items


def test_keyword_arguments_converted():
    @typecheck
    def f(x: float, y: float) -> tuple:
        return x, y

    assert f(x = 1, y = 2) == (1.0, 2.0)
    assert all(type(v) is float for v in f(x = 1, y = 2))


def test_mixed_positional_and_keyword_converted():
    @typecheck
    def f(a: float, b: str, c: float = 0.5) -> tuple:
        return a, b, c

    a, b, c = f(1, "x", c = 3)
    assert _same(a, 1.0) and b == "x" and _same(c, 3.0)


def test_keyword_only_converted():
    @typecheck
    def f(*, k: float) -> float:
        return k

    assert _same(f(k = 4), 4.0)


def test_positional_only_converted():
    @typecheck
    def f(a: float, /) -> float:
        return a

    assert _same(f(4), 4.0)


def test_var_positional_converted():
    @typecheck
    def f(*args: float) -> tuple:
        return args

    result = f(1, 2.5, 3)
    assert result == (1.0, 2.5, 3.0) and all(type(v) is float for v in result)


def test_var_keyword_converted():
    @typecheck
    def f(**kwargs: float) -> dict:
        return kwargs

    assert f(a = 1, b = 2.5) == {"a": 1.0, "b": 2.5}
    assert type(f(a = 1)["a"]) is float


def test_union_keeps_value_valid_for_another_member():
    @typecheck
    def f(x: int | float) -> int | float:
        return x

    assert _same(f(1), 1)       # already an int: nothing to convert


def test_optional_float_converted():
    @typecheck
    def f(x: float | None) -> float | None:
        return x

    assert _same(f(3), 3.0)
    assert f(None) is None


def test_wrapped_annotations_converted():
    Meters = NewType("Meters", float)
    type Ratio = float

    @typecheck
    def f(a: Annotated[float, "unit"], b: Meters, c: Ratio) -> tuple:
        return a, b, c

    assert all(type(v) is float for v in f(1, 2, 3))


def test_literal_never_converted():
    @typecheck
    def f(x: Literal[1.0, 2.0]) -> None:
        pass

    f(1.0)
    with pytest.raises(TypeCheckerError):
        f(1)


def test_strict_mode_still_converts():
    @typecheck(allow_subclass = False)
    def f(x: float) -> float:
        return x

    assert _same(f(1), 1.0)


def test_strict_mode_bool_for_int_rejected_even_with_coerce():
    @typecheck(allow_subclass = False, coerce = True)
    def f(x: int) -> int:
        return x

    with pytest.raises(TypeCheckerError):
        f(True)


def test_return_value_converted_when_checked():
    @typecheck(check_return = True)
    def f() -> float:
        return 1

    assert _same(f(), 1.0)


def test_return_value_untouched_when_not_checked():
    @typecheck
    def f() -> float:
        return 1                # type: ignore[return-value]

    assert _same(f(), 1)


def test_async_arguments_and_return_converted():
    @typecheck(check_return = True)
    async def f(x: float) -> float:
        return 2

    assert _same(asyncio.run(f(1)), 2.0)


def test_class_decorator_methods_converted():
    @enforce
    class Shape:
        def __init__(self, side: float) -> None:
            self.side = side

        def scale(self, k: float) -> float:
            return self.side * k

        @staticmethod
        def unit(x: float) -> float:
            return x

        @classmethod
        def make(cls, side: float) -> "Shape":
            return cls(side)

    s = Shape(2)
    assert _same(s.side, 2.0)
    assert _same(s.scale(3), 6.0)
    assert _same(Shape.unit(1), 1.0)
    assert _same(Shape.make(5).side, 5.0)


def test_error_only_mentions_unconvertible_arguments():
    @typecheck
    def f(a: float, b: int) -> None:
        pass

    with pytest.raises(TypeCheckerError) as exc:
        f(1, "x")
    msg = _plain(exc.value)
    assert "1 problem found in call" in msg
    assert "parameter b" in msg and "parameter a" not in msg


def test_failed_conversion_reports_original_value():
    @typecheck
    def f(x: float) -> None:
        pass

    with pytest.raises(TypeCheckerError) as exc:
        f(True)
    assert "bool" in _plain(exc.value)


# ═════════════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═════════════════════════════════════════════════════════════════════════════

def test_int_default_for_float_accepted_and_converted():
    @typecheck
    def f(x: float = 0) -> float:
        return x

    assert _same(f(), 0.0)


def test_keyword_only_default_converted():
    @typecheck
    def f(*, x: float = 1) -> float:
        return x

    assert _same(f(), 1.0)


def test_converted_default_is_what_the_function_receives():
    @typecheck
    def f(a: int, x: float = 0, *, k: complex = 1) -> tuple:
        return x, k

    for _ in range(3):                                              # the first call, and the compiled wrapper
        x, k = f(1)
        assert type(x) is float and x == 0.0 and type(k) is complex and k == 1
    assert f(1, 2) == (2.0, 1) and type(f(1, k = 2)[1]) is complex


def test_the_function_given_to_typecheck_keeps_its_defaults():
    #* Review finding 25: the converted default used to be written into the function that was passed
    #* in, so calling typecheck(scale) changed what a plain scale() returned.
    def scale(x: float = 2, *, k: complex = 1) -> tuple:
        return x, k

    checked = typecheck(scale)
    assert type(scale()[0]) is int
    assert type(checked()[0]) is float and type(checked()[1]) is complex
    assert type(scale()[0]) is int and type(scale()[1]) is int      # the original is as it was written
    assert scale.__defaults__ == (2,) and scale.__kwdefaults__ == {"k": 1}
    assert checked.__wrapped__ is scale


def test_two_wrappers_of_one_function_do_not_depend_on_each_other():
    def scale(x: float = 2) -> float:
        return x

    strict, loose = typecheck(scale, convert = False), typecheck(scale)
    assert type(loose()) is float
    for _ in range(2):                                              # still a definition error, whatever ran first
        with pytest.raises(TypeCheckerError) as exc:
            strict()
        assert exc.value.context == "definition"
    assert type(loose()) is float


def test_a_copy_with_converted_defaults_is_still_the_same_function():
    calls = []

    def outer(tag: str):
        def inner(x: float = 1, *items: int, k: float = 2) -> tuple:
            """doc"""
            calls.append(tag)                                       # a closure variable
            return x, items, k
        return inner

    inner = outer("a")
    inner.marker = "kept"                                           # type: ignore[attr-defined]
    checked = typecheck(inner)
    assert checked() == (1.0, (), 2.0) and type(checked()[0]) is float and type(checked()[2]) is float
    assert checked(3, 4, 5, k = 6) == (3.0, (4, 5), 6.0)
    assert calls == ["a"] * 4 and checked.__doc__ == "doc" and checked.marker == "kept"
    assert checked.__name__ == "inner" and "outer.<locals>.inner" in checked.__qualname__


def test_default_conversion_disabled_is_definition_error():
    @typecheck(convert = False)
    def f(x: float = 0) -> None:
        pass

    with pytest.raises(TypeCheckerError) as exc:
        f()
    assert "definition" in _plain(exc.value)


def test_default_coerced_when_coerce_on():
    @typecheck(coerce = True)
    def f(x: int = "5") -> int:     # type: ignore[assignment]
        return x

    assert _same(f(), 5)


def test_unconvertible_default_still_definition_error():
    @typecheck
    def f(x: float = "a") -> None:  # type: ignore[assignment]
        pass

    with pytest.raises(TypeCheckerError) as exc:
        f(1.0)
    assert "definition" in _plain(exc.value)


def test_defaults_of_wrapped_functions_not_rewritten():
    def inner(x: float = 0) -> float:
        return x

    @functools.wraps(inner)
    def outer(*args, **kwargs):
        return inner(*args, **kwargs)

    checked = typecheck(outer)
    checked()                       # accepted (convertible default)...
    assert outer.__defaults__ is None and inner.__defaults__ == (0,)   # ...but nothing was rewritten


# ═════════════════════════════════════════════════════════════════════════════
#  COERCION (off by default)
# ═════════════════════════════════════════════════════════════════════════════

UID = "12345678-1234-5678-1234-567812345678"

COERCIONS = [
    (int, "42", 42), (int, " -7 ", -7), (int, "1_000", 1000), (int, 3.0, 3),
    (float, "3.5", 3.5), (float, "1e3", 1000.0), (float, 2, 2.0),
    (complex, "1+2j", 1 + 2j),
    (bool, "true", True), (bool, "No", False), (bool, " on ", True), (bool, "0", False), (bool, 1, True), (bool, 0.0, False),
    (str, b"hi", "hi"), (str, bytearray(b"hi"), "hi"),
    (bytes, "hi", b"hi"), (bytes, bytearray(b"x"), b"x"),
    (Color, "red", Color.RED), (Level, 2, Level.HIGH),
    (list, (1, 2), [1, 2]), (tuple, [1, 2], (1, 2)), (set, [1, 1, 2], {1, 2}), (frozenset, (1,), frozenset({1})),
    (list[int], (1, 2), [1, 2]),
    (datetime.date, "2024-02-29", datetime.date(2024, 2, 29)),
    (datetime.datetime, "2024-01-01T10:00:00", datetime.datetime(2024, 1, 1, 10)),
    (datetime.time, "10:30", datetime.time(10, 30)),
    (Decimal, "1.10", Decimal("1.10")), (Decimal, 5, Decimal(5)),
    (Fraction, "1/3", Fraction(1, 3)),
    (uuid.UUID, UID, uuid.UUID(UID)),
    (pathlib.Path, "/tmp/x", pathlib.Path("/tmp/x")),
    ]


@pytest.mark.parametrize("annotation, value, expected", COERCIONS, ids = lambda v: repr(v)[:30])
def test_coercion_table(annotation, value, expected):
    @typecheck(coerce = True)
    def f(x: annotation):
        return x

    assert _same(f(value), expected)


REJECTED = [
    (int, "1.5"), (int, "abc"), (int, 3.5), (int, float("inf")), (int, float("nan")), (int, b"1"),
    (float, "abc"), (bool, "maybe"), (bool, 2), (bool, 0.5), (str, 1), (str, b"\xff"), (bytes, 1),
    (Color, "blue"), (list, "ab"), (list, {"a": 1}), (set, [[1]]),
    (datetime.date, "2024-13-01"), (uuid.UUID, "nope"), (Decimal, "abc"), (Decimal, True),
    ]


@pytest.mark.parametrize("annotation, value", REJECTED, ids = lambda v: repr(v)[:30])
def test_coercion_rejects(annotation, value):
    @typecheck(coerce = True)
    def f(x: annotation):
        return x

    with pytest.raises(TypeCheckerError):
        f(value)


def test_coerce_off_by_default():
    @typecheck
    def f(x: int) -> int:
        return x

    with pytest.raises(TypeCheckerError):
        f("42")


def test_coerce_includes_conversion():
    @typecheck(convert = False, coerce = True)
    def f(x: float) -> float:
        return x

    assert _same(f(1), 1.0)


def test_union_members_tried_in_declared_order():
    @typecheck(coerce = True)
    def f(x: int | float) -> int | float:
        return x

    @typecheck(coerce = True)
    def g(x: bool | int) -> bool | int:
        return x

    @typecheck(coerce = True)
    def h(x: int | bool) -> int | bool:
        return x

    assert _same(f("1.5"), 1.5)     # int fails to parse, float succeeds
    assert _same(g("1"), True)
    assert _same(h("1"), 1)


def test_conversion_tried_before_coercion():
    @typecheck(coerce = True)
    def f(x: bool | float) -> bool | float:
        return x

    assert _same(f(1), 1.0)         # lossless int -> float beats int -> bool


def test_literal_never_coerced():
    @typecheck(coerce = True)
    def f(x: Literal[1, 2]) -> None:
        pass

    with pytest.raises(TypeCheckerError):
        f("1")


def test_return_value_is_never_coerced():
    """Coercion is for what comes in: a function that returns '7' for an int has a bug, which is reported."""
    @typecheck(check_return = True, coerce = True)
    def f(x: int) -> int:
        return str(x)               # type: ignore[return-value]

    for _ in range(2):              # the first call, then the generated wrapper
        with pytest.raises(TypeCheckerError) as exc:
            f("7")                  # the argument is coerced to 7; the returned '7' isn't
        assert "For return value of <Function f>: expected type: 'int', got type 'str' (Value: '7')" in _plain(exc.value)


def test_return_value_still_converted_with_coerce():
    @typecheck(check_return = True, coerce = True, convert = False)
    def f() -> float:
        return 1                    # type: ignore[return-value]

    assert _same(f(), 1.0)          # coerce includes the lossless conversions, for return values too


def test_failed_coercion_message_shows_original_value():
    @typecheck(coerce = True)
    def f(quantity: int) -> None:
        pass

    with pytest.raises(TypeCheckerError) as exc:
        f("abc")
    msg = _plain(exc.value)
    assert "quantity" in msg and "'abc'" in msg and "str" in msg


def test_coerce_keyword_and_varargs():
    @typecheck(coerce = True)
    def f(a: int, *rest: int, b: bool = False, **extra: float) -> tuple:
        return a, rest, b, extra

    assert f("1", "2", 3.0, b = "yes", z = "0.5") == (1, (2, 3), True, {"z": 0.5})


# ═════════════════════════════════════════════════════════════════════════════
#  DATACLASS
# ═════════════════════════════════════════════════════════════════════════════

def test_dataclass_converts_init_default_and_assignment():
    @dataclass
    class Point:
        x: float
        y: float = 0

    p = Point(1)
    assert _same(p.x, 1.0) and _same(p.y, 0.0)
    p.x = 5
    assert _same(p.x, 5.0)
    assert _same(Point(x = 2, y = 3).y, 3.0)


def test_dataclass_coerce_option():
    @dataclass(coerce = True)
    class Row:
        id: int
        active: bool
        color: Color

    r = Row("7", "yes", "green")
    assert _same(r.id, 7) and r.active is True and r.color is Color.GREEN
    r.id = "8"
    assert _same(r.id, 8)


def test_dataclass_convert_false():
    @dataclass(convert = False)
    class Point:
        x: float

    with pytest.raises(TypeCheckerError):
        Point(1)
    p = Point(1.0)
    with pytest.raises(TypeCheckerError):
        p.x = 2


def test_dataclass_failed_assignment_keeps_old_value():
    @dataclass
    class Point:
        x: float

    p = Point(1)
    with pytest.raises(TypeCheckerError):
        p.x = "a"
    assert _same(p.x, 1.0)


def test_dataclass_frozen_and_slots_convert_on_init():
    @dataclass(frozen = True, slots = True)
    class Point:
        x: float

    assert _same(Point(1).x, 1.0)


def test_dataclass_replace_converts():
    @dataclass
    class Point:
        x: float

    assert _same(dataclasses.replace(Point(1.0), x = 2).x, 2.0)


def test_dataclass_kw_only_default_converted():
    @dataclass(kw_only = True)
    class Opts:
        timeout: float = 30

    assert _same(Opts().timeout, 30.0)


# ═════════════════════════════════════════════════════════════════════════════
#  typecheck_record
# ═════════════════════════════════════════════════════════════════════════════

def test_record_returns_converted_arguments():
    args, kwargs = typecheck_record({
        "object_name": "f", "record": {"a": float, "b": int}, "args": (1,), "kwargs": {"b": 2},
        })
    assert args == (1.0,) and type(args[0]) is float and kwargs == {"b": 2}


def test_record_valid_arguments_returned_as_given():
    items = [1, 2]
    args, kwargs = typecheck_record({"object_name": "f", "record": {"a": list}, "args": (items,)})
    assert args[0] is items and kwargs == {}


def test_record_does_not_mutate_input():
    supplied = {"a": 1}
    typecheck_record({"object_name": "f", "record": {"a": float}, "kwargs": supplied})
    assert type(supplied["a"]) is int


def test_record_flags():
    spec = {"object_name": "f", "record": {"a": int}, "kwargs": {"a": "9"}}
    with pytest.raises(TypeCheckerError):
        typecheck_record(spec)
    assert typecheck_record({**spec, "coerce": True}) == ((), {"a": 9})
    with pytest.raises(TypeCheckerError):          # cached checker for coerce=True must not leak
        typecheck_record(spec)
    with pytest.raises(TypeCheckerError):
        typecheck_record({"object_name": "g", "record": {"a": float}, "kwargs": {"a": 1}, "convert": False})


def test_record_callable_defaults_left_alone():
    def f(x: float = 0) -> None: ...

    typecheck_record({"object_name": f, "record": {"x": float}})
    assert f.__defaults__ == (0,) and type(f.__defaults__[0]) is int


# ═════════════════════════════════════════════════════════════════════════════
#  REVIEW FINDINGS 12 AND 13
# ═════════════════════════════════════════════════════════════════════════════

class _Level(enum.IntEnum):
    OFF = 0
    ON = 1


class _Answer(enum.Enum):
    NO = False
    YES = True


def test_bool_is_not_coerced_to_an_enum_member_by_its_number():
    #* Finding 12: Level(True) is Level.ON, because True == 1. A bool is no number anywhere else.
    @typecheck(coerce = True)
    def f(level: _Level) -> _Level:
        return level

    assert f(1) is _Level.ON and f(0) is _Level.OFF and f(1.0) is _Level.ON and f(_Level.ON) is _Level.ON
    for value in (True, False):
        for _ in range(2):
            with pytest.raises(TypeCheckerError) as e:
                f(value)
            assert "got type 'bool'" in _plain(e.value)

    @typecheck(coerce = True)
    def g(answer: _Answer, level: _Level | None = None) -> _Answer:
        return answer

    assert g(True) is _Answer.YES and g(False) is _Answer.NO        # a bool is what these members are
    with pytest.raises(TypeCheckerError):
        g(True, True)

    @dataclass(coerce = True)
    class Switch:
        level: _Level

    assert Switch(1).level is _Level.ON
    with pytest.raises(TypeCheckerError):
        Switch(True)


def test_union_conversion_follows_the_declared_order_with_a_model_among_the_members():
    from enforced.data_types import Email, Port

    #* Finding 13: every TypeModel member was tried before the numeric tower, whatever the order.
    @typecheck
    def number_first(x: float | Port) -> Any:
        return x

    @typecheck
    def model_first(x: Port | float) -> Any:
        return x

    for _ in range(3):
        assert _same(number_first(80), 80.0)
        assert _same(model_first(80), Port(80))
        assert _same(model_first(70000), 70000.0)                   # not a port: the next member takes it
        assert _same(number_first(Port(80)), Port(80)) and _same(model_first(1.5), 1.5)     # valid values are untouched

    @typecheck(coerce = True)
    def coerced_number_first(x: float | Port) -> Any:
        return x

    @typecheck(coerce = True)
    def coerced_model_first(x: Port | float) -> Any:
        return x

    @typecheck(coerce = True)
    def text_or_model(x: Email | int) -> Any:
        return x

    assert _same(coerced_number_first("80"), 80.0) and _same(coerced_model_first("80"), Port(80))
    assert _same(coerced_model_first(80), Port(80)) and _same(coerced_number_first(80), 80.0)
    assert _same(coerced_model_first("1.5"), 1.5)
    assert _same(text_or_model("a@b.co"), Email("a@b.co")) and _same(text_or_model("42"), 42)

    @typecheck(deep = True)
    def many(xs: list[float | Port]) -> Any:
        return xs

    assert many([80, Port(1), 2.5]) == [80.0, Port(1), 2.5] and type(many([80])[0]) is float


def test_single_model_still_converts_and_coerces_in_one_step():
    from enforced.data_types import Port

    @typecheck
    def f(port: Port) -> Port:
        return port

    @typecheck(coerce = True)
    def g(port: Port, other: Port | None = None) -> Port:
        return port

    assert _same(f(80), Port(80)) and _same(g("8080"), Port(8080)) and _same(g(80, "81"), Port(80))
    with pytest.raises(TypeCheckerError):
        f("80")
    with pytest.raises(TypeCheckerError) as e:
        g("70000")
    assert "invalid 'Port': must be between 1 and 65535" in _plain(e.value)


# ── one TypeModel: the converter written out (_one_model) ────────────────────────────────────────

def test_the_converter_of_one_model_answers_as_the_long_way():
    #* The converter of an annotation that is one TypeModel calls validate itself, where it went
    #* through four calls. It must answer exactly what they answered, for every kind of value.
    import enforced._typechecker._type_conversion as conversion
    from enforced import TypeModel
    FAILED = conversion.FAILED

    class Slug(TypeModel[str]):
        @classmethod
        def validate(cls, raw: str) -> str:
            if raw == "boom":
                raise RuntimeError("a bug in validate")             # not a refusal: it propagates
            if raw == "type":
                raise TypeError("refused with a TypeError")
            if raw == "math":
                raise ZeroDivisionError("refused with an ArithmeticError")
            if raw == "wrong":
                return 5                                           # type: ignore[return-value]  # not a str
            if not raw.replace("-", "").isalnum():
                raise ValueError("letters, digits and dashes")
            return raw.lower()

    class Text(str):
        pass

    class Level(TypeModel[int]):
        @classmethod
        def validate(cls, raw: int) -> int:
            if not 0 <= raw <= 9:
                raise ValueError("0 to 9")
            return raw

    def long_way(target: Any, coerce: bool, accept: Any) -> Any:
        step = conversion._model_step(target, coerce)

        def single(value: Any) -> Any:
            try:
                result = step(value)
            except (TypeError, ValueError, ArithmeticError):
                return FAILED
            return result if result is not FAILED and accept(result) else FAILED
        return single

    def outcome(converter: Any, value: Any) -> Any:
        conversion.REJECTED[:] = [None, None, None]
        try:
            result = converter(value)
        except Exception as e:
            return ("raised", type(e).__name__)
        reason = conversion.REJECTED[2] if conversion.REJECTED[0] is value else None
        return ("failed", reason) if result is FAILED else (type(result).__name__, result)

    for target, values in ((Slug, ["Ok-1", "not ok", "boom", "type", "math", "wrong", Text("Sub-Class"), Slug("kept"), 5, b"x", None]),
                           (Level, [3, 12, True, 3.0, "4", Level(2), -1])):
        for coerce in (False, True):
            for accept in (lambda v: True, lambda v: str(v) != "ok-1" and v != 3):
                fast, slow = conversion.build_converter((target,), True, coerce, accept), long_way(target, coerce, accept)
                for value in values:
                    assert outcome(fast, value) == outcome(slow, value), (target.__name__, coerce, value)
