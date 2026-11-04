from collections.abc import (
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
    )
from typing import (
    Annotated,
    Any,
    Callable,
    Final,
    Literal,
    NamedTuple,
    Never,
    NoReturn,
    Optional,
    Protocol,
    Self,
    TypedDict,
    NewType,
    Union,
    runtime_checkable,
    )
from enforced import (
    InvalidDataError,
    enforce,
    validate,
    validate_record,
    dataclass,
    )
import enforced._validator._checker as _checker
import enforced._validator._codegen as _codegen
import enforced._validator._defaults as _defaults
import enforced._validator._remembered as _remembered
import enforced._validator._signatures as _signatures
import enforced._validator._specs as _specs
import enforced._validator._wrapping as _wrapping
import typing
import abc
import dataclasses
import numbers
import enum
import pytest
import asyncio
import re



# ─── int ──────────────────────────────────────────────────────────────────────

def test_int_param():
    @validate
    def f(x: int) -> int:
        return x

    assert f(42) == 42
    with pytest.raises(InvalidDataError):
        f("hello")


def test_int_rejects_float():
    @validate
    def f(x: int) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(3.14)


# ─── str ──────────────────────────────────────────────────────────────────────

def test_str_param():
    @validate
    def f(x: str) -> str:
        return x

    assert f("hello") == "hello"
    with pytest.raises(InvalidDataError):
        f(42)


# ─── float ────────────────────────────────────────────────────────────────────

def test_float_param():
    @validate
    def f(x: float) -> float:
        return x

    assert f(3.14) == 3.14
    with pytest.raises(InvalidDataError):
        f("3.14")


# ─── bool ─────────────────────────────────────────────────────────────────────

def test_bool_param():
    @validate
    def f(x: bool) -> bool:
        return x

    assert f(True) is True
    with pytest.raises(InvalidDataError):
        f(1)  # int is not bool


# ─── bytes ────────────────────────────────────────────────────────────────────

def test_bytes_param():
    @validate
    def f(x: bytes) -> bytes:
        return x

    assert f(b"data") == b"data"
    with pytest.raises(InvalidDataError):
        f("data")


# ─── complex ──────────────────────────────────────────────────────────────────

def test_complex_param():
    @validate
    def f(x: complex) -> complex:
        return x

    assert f(1 + 2j) == 1 + 2j
    with pytest.raises(InvalidDataError):
        f("1+2j")


# ─── None ─────────────────────────────────────────────────────────────────────

def test_none_param():
    @validate
    def f(x: None) -> None:
        pass

    f(None)
    with pytest.raises(InvalidDataError):
        f(0)


# ─── list ─────────────────────────────────────────────────────────────────────

def test_list_bare():
    @validate
    def f(x: list) -> list:
        return x

    assert f([1, 2]) == [1, 2]
    with pytest.raises(InvalidDataError):
        f((1, 2))


def test_list_generic():
    @validate
    def f(x: list[int]) -> list[int]:
        return x

    assert f([1, 2, 3]) == [1, 2, 3]
    f(["a", "b"])  # inner type not checked
    with pytest.raises(InvalidDataError):
        f((1, 2, 3))


# ─── tuple ────────────────────────────────────────────────────────────────────

def test_tuple_bare():
    @validate
    def f(x: tuple) -> tuple:
        return x

    assert f((1, 2)) == (1, 2)
    with pytest.raises(InvalidDataError):
        f([1, 2])


def test_tuple_fixed_length():
    @validate
    def f(x: tuple[int, str]) -> tuple[int, str]:
        return x

    assert f((1, "hello")) == (1, "hello")
    f(("a", "b", "c"))  # inner types not checked
    with pytest.raises(InvalidDataError):
        f([1, "hello"])


def test_tuple_variable_length():
    @validate
    def f(x: tuple[int, ...]) -> tuple[int, ...]:
        return x

    assert f((1, 2, 3)) == (1, 2, 3)
    f(())
    with pytest.raises(InvalidDataError):
        f([1, 2, 3])


# ─── dict ─────────────────────────────────────────────────────────────────────

def test_dict_bare():
    @validate
    def f(x: dict) -> dict:
        return x

    assert f({"a": 1}) == {"a": 1}
    with pytest.raises(InvalidDataError):
        f([("a", 1)])


def test_dict_generic():
    @validate
    def f(x: dict[str, int]) -> dict[str, int]:
        return x

    assert f({"a": 1}) == {"a": 1}
    f({1: "a"})  # key/value types not checked
    with pytest.raises(InvalidDataError):
        f([("a", 1)])


# ─── set ──────────────────────────────────────────────────────────────────────

def test_set_bare():
    @validate
    def f(x: set) -> set:
        return x

    assert f({1, 2}) == {1, 2}
    with pytest.raises(InvalidDataError):
        f([1, 2])


def test_set_generic():
    @validate
    def f(x: set[int]) -> set[int]:
        return x

    assert f({1, 2}) == {1, 2}
    f({"a", "b"})  # inner type not checked
    with pytest.raises(InvalidDataError):
        f([1, 2])


# ─── frozenset ────────────────────────────────────────────────────────────────

def test_frozenset_bare():
    @validate
    def f(x: frozenset) -> frozenset:
        return x

    fs = frozenset({1, 2})
    assert f(fs) == fs
    with pytest.raises(InvalidDataError):
        f({1, 2})


def test_frozenset_generic():
    @validate
    def f(x: frozenset[str]) -> frozenset[str]:
        return x

    fs = frozenset({"a", "b"})
    assert f(fs) == fs
    f(frozenset({1, 2}))  # inner type not checked
    with pytest.raises(InvalidDataError):
        f({"a", "b"})


# ─── nested generic ───────────────────────────────────────────────────────────

def test_nested_generic():
    @validate
    def f(x: list[dict[str, int]]) -> list[dict[str, int]]:
        return x

    assert f([{"a": 1}]) == [{"a": 1}]
    f([1, 2, 3])  # inner type not checked
    with pytest.raises(InvalidDataError):
        f("not a list")


# ─── Union ────────────────────────────────────────────────────────────────────

def test_union_old_syntax():
    @validate
    def f(x: Union[int, str]) -> None:
        pass

    f(1)
    f("hello")
    with pytest.raises(InvalidDataError):
        f(3.14)


def test_union_new_syntax():
    @validate
    def f(x: int | str) -> None:
        pass

    f(1)
    f("hello")
    with pytest.raises(InvalidDataError):
        f(3.14)


def test_union_three_types():
    @validate
    def f(x: int | str | bytes) -> None:
        pass

    f(1)
    f("hello")
    f(b"data")
    with pytest.raises(InvalidDataError):
        f(3.14)


# ─── Optional ─────────────────────────────────────────────────────────────────

def test_optional():
    @validate
    def f(x: Optional[int]) -> Optional[int]:
        return x

    assert f(1) == 1
    assert f(None) is None
    with pytest.raises(InvalidDataError):
        f("hello")


def test_optional_new_syntax():
    @validate
    def f(x: int | None) -> int | None:
        return x

    assert f(1) == 1
    assert f(None) is None
    with pytest.raises(InvalidDataError):
        f("hello")


# ─── Literal ──────────────────────────────────────────────────────────────────

def test_literal_str_values():
    @validate
    def f(x: Literal["north", "south", "east", "west"]) -> None:
        pass

    f("north")
    f("west")
    with pytest.raises(InvalidDataError):
        f("up")
    with pytest.raises(InvalidDataError):
        f(1)


def test_literal_int_values():
    @validate
    def f(x: Literal[1, 2, 3]) -> None:
        pass

    f(1)
    f(3)
    with pytest.raises(InvalidDataError):
        f(4)
    with pytest.raises(InvalidDataError):
        f("1")


def test_literal_bool_value():
    @validate
    def f(x: Literal[True]) -> None:
        pass

    f(True)
    with pytest.raises(InvalidDataError):
        f(False)
    with pytest.raises(InvalidDataError):
        f(1)  # int 1 is not Literal[True]


def test_literal_mixed_values():
    @validate
    def f(x: Literal[1, "a", None]) -> None:
        pass

    f(1)
    f("a")
    f(None)
    with pytest.raises(InvalidDataError):
        f(2)
    with pytest.raises(InvalidDataError):
        f("b")


# ─── Any ──────────────────────────────────────────────────────────────────────

def test_any_accepts_any_type():
    @validate
    def f(x: Any) -> Any:
        return x

    assert f(42) == 42
    assert f("hello") == "hello"
    assert f(None) is None


# ─── Callable ─────────────────────────────────────────────────────────────────

def test_callable_with_signature():
    @validate
    def f(callback: Callable[[int], str]) -> None:
        pass

    f(str)
    f(lambda x: str(x))
    with pytest.raises(InvalidDataError):
        f("not callable")
    with pytest.raises(InvalidDataError):
        f(42)


def test_callable_ellipsis():
    @validate
    def f(callback: Callable[..., Any]) -> None:
        pass

    f(print)
    f(lambda: None)
    with pytest.raises(InvalidDataError):
        f("not callable")


# ─── type[] ───────────────────────────────────────────────────────────────────

def test_type_of_builtin():
    @validate
    def f(cls: type[int]) -> None:
        pass

    f(int)
    f(bool)  # bool is a subclass of int
    with pytest.raises(InvalidDataError):
        f(42)
    with pytest.raises(InvalidDataError):
        f(str)


def test_type_of_custom_class():
    class Animal: ...

    @validate
    def f(cls: type[Animal]) -> None:
        pass

    f(Animal)
    with pytest.raises(InvalidDataError):
        f(Animal())  # instance, not the class itself
    with pytest.raises(InvalidDataError):
        f(int)


@pytest.mark.parametrize("annotation, accepted, rejected", [
    (type[int] | None, [int, bool, None], [str, 1, "int"]),
    (Optional[type[int]], [int, None], [str, 1]),
    (type[int] | str, [int, bool, "a"], [str, 1, None]),
    (type[int] | type[str], [int, bool, str], [float, "a", 1]),
    (type[int] | type, [int, str, float], [1, None]),
    (type[Any] | int, [str, float, 1], ["a", None]),
    (Literal["a"] | type[int] | None, ["a", int, None], ["b", str, 1]),
    ], ids = ["type[int] | None", "Optional[type[int]]", "type[int] | str", "type[int] | type[str]", "type[int] | type",
              "type[Any] | int", "Literal['a'] | type[int] | None"])
def test_type_of_class_in_a_union(annotation, accepted, rejected):
    """type[X] is about classes only: the union's other members still accept their own values (once they didn't)."""
    f = _checked(annotation)
    for value in accepted:
        assert f(value) is value
    for value in rejected:
        with pytest.raises(InvalidDataError):
            f(value)


def test_type_of_class_in_a_union_as_a_default():
    @validate
    def f(cls: type[int] | None = None) -> Any:
        return cls

    assert f() is None                                      # once a definition error
    assert f(bool) is bool


def test_type_of_class_in_a_union_details():
    #* The other members still convert; a class is never produced by conversion.
    f = _checked(type[int] | float)
    assert type(f(1)) is float and f(int) is int
    assert _checked(type[int] | int, coerce = True)("5") == 5

    #* A check beside it applies to the values of its own member, not to classes.
    g = _checked(Annotated[int, lambda v: v > 0] | type[int])
    assert g(1) == 1 and g(bool) is bool
    for bad in (-1, str):
        with pytest.raises(InvalidDataError):
            g(bad)

    #* Strict mode: the class itself, and the exact type for the other members.
    strict = _checked(type[int] | str, allow_subclass = False)
    assert strict(int) is int and strict("a") == "a"
    with pytest.raises(InvalidDataError):
        strict(bool)

    #* Items (deep), a dataclass field and a return value.
    @validate(deep = True)
    def items(xs: list[type[int] | None]) -> None: ...

    items([int, None, bool])
    with pytest.raises(InvalidDataError) as exc:
        items([int, str])
    assert [p.parameter for p in exc.value.problems] == ["xs[1]"]

    @dataclass
    class Column:
        kind: type[int] | type[str] | None = None

    column = Column()
    column.kind = str
    with pytest.raises(InvalidDataError):
        column.kind = float

    @validate(check_return = True)
    def ret(x: object) -> type[int] | None:
        return x                                            # type: ignore[return-value]

    assert ret(None) is None and ret(int) is int
    with pytest.raises(InvalidDataError):
        ret(str)


# ─── Annotated ────────────────────────────────────────────────────────────────

def test_annotated_base_type_enforced():
    @validate
    def f(x: Annotated[int, "must be positive"]) -> int:
        return x

    assert f(5) == 5
    with pytest.raises(InvalidDataError):
        f("five")


def test_annotated_with_generic_base():
    @validate
    def f(x: Annotated[list[str], "non-empty"]) -> list[str]:
        return x

    assert f(["a", "b"]) == ["a", "b"]
    with pytest.raises(InvalidDataError):
        f("not a list")


# ─── collections.abc ──────────────────────────────────────────────────────────

def test_abc_sequence():
    @validate
    def f(x: Sequence[int]) -> None:
        pass

    f([1, 2, 3])
    f((1, 2, 3))
    with pytest.raises(InvalidDataError):
        f(42)
    with pytest.raises(InvalidDataError):
        f({1, 2})  # set is not a Sequence


def test_abc_mutable_sequence():
    @validate
    def f(x: MutableSequence[int]) -> None:
        pass

    f([1, 2, 3])
    with pytest.raises(InvalidDataError):
        f((1, 2, 3))  # tuple is immutable
    with pytest.raises(InvalidDataError):
        f(42)


def test_abc_mapping():
    @validate
    def f(x: Mapping[str, int]) -> None:
        pass

    f({"a": 1})
    with pytest.raises(InvalidDataError):
        f([("a", 1)])
    with pytest.raises(InvalidDataError):
        f("not a mapping")


def test_abc_mutable_mapping():
    @validate
    def f(x: MutableMapping[str, int]) -> None:
        pass

    f({"a": 1})
    with pytest.raises(InvalidDataError):
        f("not a mapping")


def test_abc_iterable():
    @validate
    def f(x: Iterable[int]) -> None:
        pass

    f([1, 2, 3])
    f((1, 2))
    f({1, 2})
    f("abc")  # str is Iterable
    with pytest.raises(InvalidDataError):
        f(42)


def test_abc_iterator():
    @validate
    def f(x: Iterator[int]) -> None:
        pass

    f(iter([1, 2, 3]))
    with pytest.raises(InvalidDataError):
        f([1, 2, 3])  # list is Iterable, not an Iterator


# ─── TypeAliasType (PEP 695) ──────────────────────────────────────────────────

def test_type_alias_simple():
    type Identifier = str

    @validate
    def f(x: Identifier) -> Identifier:
        return x

    assert f("foo") == "foo"
    with pytest.raises(InvalidDataError):
        f(42)


def test_type_alias_union():
    type IntOrStr = int | str

    @validate
    def f(x: IntOrStr) -> None:
        pass

    f(1)
    f("hello")
    with pytest.raises(InvalidDataError):
        f(3.14)


def test_type_alias_generic():
    type Matrix = list[list[float]]

    @validate
    def f(x: Matrix) -> Matrix:
        return x

    assert f([[1.0, 2.0], [3.0, 4.0]]) == [[1.0, 2.0], [3.0, 4.0]]
    with pytest.raises(InvalidDataError):
        f("not a list")


# ─── Enum ─────────────────────────────────────────────────────────────────────

def test_enum_param():
    class Direction(enum.Enum):
        NORTH = "N"
        SOUTH = "S"

    @validate
    def f(d: Direction) -> None:
        pass

    f(Direction.NORTH)
    with pytest.raises(InvalidDataError):
        f("N")
    with pytest.raises(InvalidDataError):
        f(0)


# ─── TypedDict ────────────────────────────────────────────────────────────────

def test_typeddict_param():
    class Movie(TypedDict):
        title: str
        year: int

    @validate
    def f(m: Movie) -> None:
        pass

    f({"title": "Inception", "year": 2010})
    with pytest.raises(InvalidDataError):
        f("not a dict")
    with pytest.raises(InvalidDataError):
        f(42)


# ─── NamedTuple ───────────────────────────────────────────────────────────────

def test_namedtuple_param():
    class Point(NamedTuple):
        x: float
        y: float

    @validate
    def f(p: Point) -> None:
        pass

    f(Point(1.0, 2.0))
    with pytest.raises(InvalidDataError):
        f((1.0, 2.0))  # plain tuple is not Point
    with pytest.raises(InvalidDataError):
        f({"x": 1.0, "y": 2.0})


# ─── Protocol ─────────────────────────────────────────────────────────────────

def test_runtime_checkable_protocol():
    @runtime_checkable
    class Closeable(Protocol):
        def close(self) -> None: ...

    class Connection:
        def close(self) -> None:
            pass

    class NotCloseable:
        pass

    @validate
    def f(x: Closeable) -> None:
        pass

    f(Connection())
    with pytest.raises(InvalidDataError):
        f(NotCloseable())
    with pytest.raises(InvalidDataError):
        f("not closeable")


class Walker(Protocol):                                     # not @runtime_checkable
    def walk(self) -> None: ...


class Dog:
    def walk(self) -> None: ...


def _checked(annotation: Any, **options: Any):
    """A type-checked function that returns its only argument, annotated with ``annotation``."""
    def f(x):
        return x
    f.__annotations__ = {"x": annotation}
    return validate(f, **options)


@pytest.mark.parametrize("annotation, options", [
    (Walker, {}), (Walker | None, {}), (type[Walker], {}), (Walker, {"allow_subclass": False}),
    (Walker, {"deep": True}), (list[Walker], {"deep": True}), (dict[str, Walker | None], {"deep": True}),
    ], ids = str)
def test_protocol_without_runtime_checkable_is_a_clear_error(annotation, options):
    """isinstance() can't test such a Protocol: the error says so (once every call died inside the check)."""
    f = _checked(annotation, **options)
    for _ in range(2):                                      # the same error on every call
        with pytest.raises(InvalidDataError) as exc:
            f(Dog())
        assert _plain(exc.value) == "Cannot check Protocol Walker for parameter x: decorate it with @runtime_checkable"


def test_protocol_without_runtime_checkable_as_return_type_and_field():
    @validate(check_return = True)
    def make() -> Walker:
        return Dog()

    @dataclass
    class Owner:
        pet: Walker

    with pytest.raises(InvalidDataError) as exc:
        make()
    assert "Cannot check Protocol Walker for the return value" in _plain(exc.value)
    with pytest.raises(InvalidDataError) as exc:
        Owner(Dog())
    assert "Cannot check Protocol Walker for parameter pet" in _plain(exc.value)


# ─── return type ──────────────────────────────────────────────────────────────

def test_return_type_correct():
    @validate
    def f(x: int) -> str:
        return str(x)

    assert f(42) == "42"


def test_return_type_violated():
    @validate(check_return = True)
    def f(x: int) -> str:
        return x  # type: ignore[return-value]

    with pytest.raises(InvalidDataError):
        f(42)


def test_return_none_violated():
    @validate(check_return = True)
    def f() -> None:
        return 42  # type: ignore[return-value]

    with pytest.raises(InvalidDataError):
        f()


# ─── Never / NoReturn ─────────────────────────────────────────────────────────

def test_never_raises_is_valid():
    @validate
    def f() -> Never:
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        f()


def test_noreturn_normal_return_invalid():
    @validate(check_return = True)
    def f() -> NoReturn:
        pass  # wrongly returns normally

    with pytest.raises(InvalidDataError):
        f()


# ─── Final ────────────────────────────────────────────────────────────────────

def test_final_int_param():
    @validate
    def f(x: Final[int]) -> None:
        pass

    f(42)
    with pytest.raises(InvalidDataError):
        f("hello")


# ─── class decorator ──────────────────────────────────────────────────────────

def test_class_single_param():
    @enforce
    class Box:
        def __init__(self, value: int) -> None:
            self.value = value

    with pytest.raises(InvalidDataError):
        Box("not an int")


def test_class_multiple_params():
    @enforce
    class Vector:
        def __init__(self, x: float, y: float, label: str) -> None:
            self.x, self.y, self.label = x, y, label

    with pytest.raises(InvalidDataError):
        Vector(1.0, "not a float", "v")


def test_dataclass_param():
    @dataclass
    class Coordinate:
        lat: float
        lon: float

    with pytest.raises(InvalidDataError):
        Coordinate("not a float", 0.0)


# ─── varargs ──────────────────────────────────────────────────────────────────

def test_args_annotation():
    @validate
    def f(*args: int) -> None:
        pass

    f(1, 2, 3)
    with pytest.raises(InvalidDataError):
        f(1, "two", 3)


def test_kwargs_annotation():
    @validate
    def f(**kwargs: str) -> None:
        pass

    f(a="hello", b="world")
    with pytest.raises(InvalidDataError):
        f(a="hello", b=42)


# ─── subclass behaviour ───────────────────────────────────────────────────────

def test_subclass_accepted_by_default():
    class Animal: ...
    class Dog(Animal): ...

    @validate
    def f(x: Animal) -> Animal:
        return x

    dog = Dog()
    assert f(dog) is dog  # Dog satisfies Animal with allow_subclass=True


def test_bool_is_not_accepted_as_int():
    @validate
    def f(x: int) -> int:
        return x

    with pytest.raises(InvalidDataError, match = "bool"):   # bool subclasses int, but True is not an int here
        f(True)
    assert f(1) == 1


def test_bool_still_accepted_where_it_is_allowed():
    @validate
    def f(a: int | bool, b: object, c: Literal[True], d: type[int]) -> None: ...

    f(True, True, True, bool)

    import numbers

    @validate
    def g(x: int | numbers.Number) -> None: ...

    g(True)                                                     # bool is a Number

    class MyInt(int):
        pass

    @validate
    def h(x: int) -> None: ...

    h(MyInt(3))                                                 # other int subclasses are still ints


# ─── Self ─────────────────────────────────────────────────────────────────────

def test_self_return_annotation():
    @enforce
    class Builder:
        def set_name(self, name: str) -> Self:
            self.name = name
            return self

    b = Builder()
    result = b.set_name("Alice")
    assert result is b
    with pytest.raises(InvalidDataError):
        b.set_name(42)


# ─── multiple params ──────────────────────────────────────────────────────────

def test_multiple_params_first_wrong():
    @validate
    def f(x: int, y: str) -> None:
        pass

    f(1, "hello")
    with pytest.raises(InvalidDataError):
        f("one", "hello")


def test_multiple_params_second_wrong():
    @validate
    def f(x: int, y: str) -> None:
        pass

    f(1, "hello")
    with pytest.raises(InvalidDataError):
        f(1, 2)


# ─── default values ───────────────────────────────────────────────────────────

def test_default_value_correct_type():
    @validate
    def f(x: int = 0) -> int:
        return x

    assert f() == 0
    assert f(5) == 5
    with pytest.raises(InvalidDataError):
        f("not an int")


def test_default_none_with_optional():
    @validate
    def f(x: str | None = None) -> str | None:
        return x

    assert f() is None
    assert f("hello") == "hello"
    with pytest.raises(InvalidDataError):
        f(42)


# ─── forward references ───────────────────────────────────────────────────────

def test_forward_reference_string():
    @validate
    def f(x: "int") -> "int":
        return x

    assert f(1) == 1
    with pytest.raises(InvalidDataError):
        f("hello")


def test_forward_reference_self_referential():
    @enforce
    class Node:
        def set_next(self, node: "Node") -> "Node":
            self.next = node
            return node

    a, b = Node(), Node()
    assert a.set_next(b) is b
    with pytest.raises(InvalidDataError):
        a.set_next("not a node")


def test_forward_reference_in_union():
    @validate
    def f(x: "int | str") -> None:
        pass

    f(1)
    f("hello")
    with pytest.raises(InvalidDataError):
        f(3.14)


# ─── metadata preservation ────────────────────────────────────────────────────

def test_preserves_function_metadata():
    @validate
    def my_function(x: int) -> int:
        return x

    assert my_function.__name__ == "my_function"
    assert my_function(1) == 1
    with pytest.raises(InvalidDataError):
        my_function("bad")


def _plain(e: BaseException) -> str:
    """Strip ANSI colour codes so messages can be matched as text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


# ─── late-bound aliases (must live at module level) ───────────────────────────

@validate
def _late_good_default(x: "LateDefaultAlias" = 1) -> None:
    pass

@validate
def _late_bad_default(x: "LateDefaultAlias" = 3.14) -> None:
    pass

type LateDefaultAlias = int | str


# ─── TypeVar with a string bound (must live at module level) ──────────────────
#* TypeVar("T", bound="Shape") names a class by a string: the pattern for a method that returns
#* its own type, from before Self. The string is looked up in the module that defines the TypeVar.

BoundToLater = typing.TypeVar("BoundToLater", bound = "LaterShape")
EitherLater = typing.TypeVar("EitherLater", "LaterShape", "int")
BoundToNothing = typing.TypeVar("BoundToNothing", bound = "NoSuchClassAnywhere")
SameNode = typing.TypeVar("SameNode", bound = "LinkedNode")


class LaterShape:
    pass


class LaterSquare(LaterShape):
    pass


class LinkedNode:
    @validate(check_return = True)
    def link(self: SameNode, other: SameNode) -> SameNode:
        return other


def test_typevar_with_a_string_bound():
    @validate(check_return = True)
    def same(x: BoundToLater) -> BoundToLater:
        return x

    square = LaterSquare()
    assert same(square) is square
    with pytest.raises(InvalidDataError) as exc:
        same(5)                                             # type: ignore[type-var]
    assert "LaterShape', got type 'int' (Value: 5)" in _plain(exc.value)


def test_typevar_with_string_constraints():
    @validate
    def either(x: EitherLater) -> EitherLater:
        return x

    assert either(5) == 5
    assert isinstance(either(LaterSquare()), LaterSquare)
    for value in ("a", 1.5, None):
        with pytest.raises(InvalidDataError):
            either(value)                                   # type: ignore[type-var]


def test_typevar_with_a_string_bound_on_self():
    node, other = LinkedNode(), LinkedNode()
    assert node.link(other) is other
    with pytest.raises(InvalidDataError):
        node.link("other")                                  # type: ignore[type-var]


def test_typevar_with_a_string_bound_in_other_places():
    @validate(deep = True)
    def first(shapes: list[BoundToLater], fallback: BoundToLater | None = None) -> typing.Any:
        return shapes[0] if shapes else fallback

    square = LaterSquare()
    assert first([square]) is square
    assert first([], square) is square
    with pytest.raises(InvalidDataError) as exc:
        first([square, 5])                                  # type: ignore[type-var]
    assert [p.parameter for p in exc.value.problems] == ["shapes[1]"]

    @dataclass
    class Holder(typing.Generic[BoundToLater]):
        shape: BoundToLater

    assert Holder(square).shape is square
    with pytest.raises(InvalidDataError):
        Holder(5)                                           # type: ignore[type-var]
    assert validate_record({"object_name": "f", "record": {"x": BoundToLater}, "args": (square,)}) == ((square,), {})


def test_typevar_with_a_bound_that_names_nothing_still_says_so():
    @validate
    def f(x: BoundToNothing) -> None: ...

    for _ in range(2):
        with pytest.raises(InvalidDataError, match = "Cannot resolve annotation"):
            f(1)


# ═════════════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═════════════════════════════════════════════════════════════════════════════

def test_default_correct_type_used():
    @validate
    def f(x: int = 5) -> int:
        return x

    assert f() == 5


def test_default_wrong_type_raises_when_not_supplied():
    @validate
    def f(x: int = "five") -> None:
        pass

    with pytest.raises(InvalidDataError):
        f()


def test_default_wrong_type_raises_even_when_supplied():
    @validate
    def f(x: int = "five") -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(5)  # the definition itself is broken


def test_default_error_msg_mentions_default():
    @validate
    def f(x: int, y: str = 5) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f(1, "ok")
    msg = _plain(exc.value)
    assert "default" in msg
    assert "definition" in msg
    assert "y" in msg


def test_default_checked_before_missing_arguments():
    @validate
    def f(x: int, y: str = 5) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f()  # x missing AND y's default is wrong: defaults are reported first
    msg = _plain(exc.value)
    assert "definition" in msg
    assert "Missing" not in msg


def test_multiple_bad_defaults_reported_together():
    @validate
    def f(a: int = "x", b: str = 1, c: float = 1.0) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f()
    assert "2 problems found in definition" in _plain(exc.value)


def test_bad_default_raises_on_every_call():
    @validate
    def f(x: int = "bad") -> None:
        pass

    for _ in range(3):
        with pytest.raises(InvalidDataError):
            f()


def test_valid_defaults_checked_only_once(monkeypatch):
    calls: list[int] = []
    real = _defaults.check_defaults

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_checker, "check_defaults", counting)

    @validate
    def f(x: int = 0) -> None:
        pass

    f()
    f(1)
    f(x=2)
    assert len(calls) == 1


def test_invalid_defaults_rechecked_each_call(monkeypatch):
    calls: list[int] = []
    real = _defaults.check_defaults

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_checker, "check_defaults", counting)

    @validate
    def f(x: int = "bad") -> None:
        pass

    for _ in range(2):
        with pytest.raises(InvalidDataError):
            f()
    assert len(calls) == 2


def test_none_default_without_optional_rejected():
    @validate
    def f(x: int = None) -> None:  # implicit Optional is not allowed
        pass

    with pytest.raises(InvalidDataError):
        f(1)


def test_none_default_with_optional_accepted():
    @validate
    def f(x: int | None = None) -> None:
        pass

    f()
    f(1)


def test_unannotated_default_ignored():
    @validate
    def f(x, y=5) -> None:
        pass

    f(1)
    f(1, "anything")


def test_keyword_only_bad_default():
    @validate
    def f(*, k: int = "x") -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(k=1)


def test_positional_only_bad_default():
    @validate
    def f(a: int = "x", /) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1)


def test_literal_default_valid():
    @validate
    def f(mode: Literal["fast", "slow"] = "fast") -> None:
        pass

    f()


def test_literal_default_invalid():
    @validate
    def f(mode: Literal["fast", "slow"] = "turbo") -> None:
        pass

    with pytest.raises(InvalidDataError):
        f("fast")


def test_union_default_valid():
    @validate
    def f(x: int | str = "a") -> None:
        pass

    f()


def test_mutable_default_outer_type_checked():
    @validate
    def f(x: list[int] = []) -> None:  # noqa: B006
        pass

    f()

    @validate
    def g(x: list[int] = ()) -> None:
        pass

    with pytest.raises(InvalidDataError):
        g()


def test_bool_default_rejected_for_int():
    @validate
    def f(x: int = True) -> None:  # bool subclasses int, but isn't accepted as one
        pass

    with pytest.raises(InvalidDataError, match = "default"):
        f()


def test_subclass_default_rejected_in_strict_mode():
    @validate(allow_subclass = False)
    def f(x: int = True) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1)


def test_late_bound_alias_default_valid():
    _late_good_default()
    _late_good_default("s")


def test_late_bound_alias_default_invalid():
    with pytest.raises(InvalidDataError):
        _late_bad_default(1)


def test_class_init_bad_default():
    @enforce
    class Box:
        def __init__(self, value: int = "x") -> None:
            self.value = value

    with pytest.raises(InvalidDataError):
        Box(1)


def test_class_init_good_default():
    @enforce
    class Box:
        def __init__(self, value: int = 0) -> None:
            self.value = value

    assert Box().value == 0


def test_dataclass_bad_field_default():
    @dataclass
    class Config:
        port: int = "8080"

    with pytest.raises(InvalidDataError):
        Config(80)


def test_dataclass_good_field_default():
    @dataclass
    class Config:
        port: int = 8080

    assert Config().port == 8080


def test_method_bad_default():
    @enforce
    class Service:
        def run(self, retries: int = "three") -> None:
            pass

    with pytest.raises(InvalidDataError):
        Service().run()


def test_staticmethod_bad_default():
    @enforce
    class Util:
        @staticmethod
        def parse(v: float = "1.0") -> float:
            return v

    with pytest.raises(InvalidDataError):
        Util.parse(1.0)


def test_classmethod_bad_default():
    @enforce
    class Factory:
        @classmethod
        def make(cls, name: str = 0) -> None:
            pass

    with pytest.raises(InvalidDataError):
        Factory.make("x")


def test_async_bad_default():
    @validate
    async def f(x: int = "a") -> None:
        pass

    coro = f()  # creating the coroutine does not check anything yet
    with pytest.raises(InvalidDataError):
        asyncio.run(coro)


# ═════════════════════════════════════════════════════════════════════════════
#  CALL BINDING / MISSING ARGUMENTS
# ═════════════════════════════════════════════════════════════════════════════

def test_missing_single_argument():
    @validate
    def f(x: int, y: str) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f(1)
    msg = _plain(exc.value)
    assert "Missing required argument" in msg
    assert "y" in msg


def test_missing_reports_all_arguments():
    @validate
    def f(a: int, b: int, c: int) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f()
    msg = _plain(exc.value)
    assert "Missing required arguments" in msg
    for name in ("a (expecting type int)", "b (expecting type int)", "c (expecting type int)"):
        assert name in msg


def test_missing_inferred_from_types():
    @validate
    def f(a: int, b: float, c: str) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f("hello")
    msg = _plain(exc.value)
    assert "a (expecting type int), b (expecting type float)" in msg
    assert "(inferred)" in msg
    assert "1 problem found in call" in msg  # no spurious type errors after realignment


def test_missing_ambiguous_not_inferred():
    @validate
    def f(a: str, b: str) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f("x")
    msg = _plain(exc.value)
    assert "b (expecting type str)" in msg
    assert "(inferred)" not in msg


def test_missing_keyword_only():
    @validate
    def f(a: int, *, b: str) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1)


def test_too_many_positional():
    @validate
    def f(a: int) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1, 2)


def test_unexpected_keyword():
    @validate
    def f(a: int) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1, z=2)


def test_duplicate_argument():
    @validate
    def f(a: int) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(1, a=2)


def test_positional_only_passed_as_keyword():
    @validate
    def f(a: int, /) -> None:
        pass

    with pytest.raises(InvalidDataError):
        f(a=1)


# ═════════════════════════════════════════════════════════════════════════════
#  DECORATOR FORMS / OPTIONS
# ═════════════════════════════════════════════════════════════════════════════

def test_decorator_with_empty_parentheses():
    @validate()
    def f(x: int) -> None:
        pass

    f(1)
    with pytest.raises(InvalidDataError):
        f("x")


def test_error_is_a_type_error():
    assert issubclass(InvalidDataError, TypeError)


def test_return_not_checked_by_default():
    @validate
    def f() -> str:
        return 1  # type: ignore[return-value]

    assert f() == 1


def test_strict_mode_rejects_bool_for_int():
    @validate(allow_subclass = False)
    def f(x: int) -> None:
        pass

    f(1)
    with pytest.raises(InvalidDataError):
        f(True)


def test_strict_mode_union():
    @validate(allow_subclass = False)
    def f(x: int | str) -> None:
        pass

    f(1)
    f("a")
    with pytest.raises(InvalidDataError):
        f(True)


def test_strict_mode_accepts_anything_for_any():
    """Any isn't a class a value could be an exact instance of (once `x: Any = 5` was a definition error)."""
    @validate(allow_subclass = False)
    def f(x: Any = 5) -> Any:
        return x

    assert f() == 5
    assert f("anything") == "anything"


def test_strict_mode_any_is_not_blamed_next_to_a_real_problem():
    @validate(allow_subclass = False)
    def g(x: Any, y: int) -> None: ...

    g("s", 1)
    with pytest.raises(InvalidDataError) as exc:
        g("s")
    assert [p.kind for p in exc.value.problems] == ["missing"]


@pytest.mark.parametrize("annotation", [Any | int, Optional[Any], Any | None], ids = ["Any | int", "Optional[Any]", "Any | None"])
def test_strict_mode_any_inside_a_union(annotation):
    f = _checked(annotation, allow_subclass = False)
    for value in ("text", True, 1.5, None, str):
        assert f(value) is value


def test_strict_mode_type_of_any_accepts_every_class():
    f = _checked(type[Any], allow_subclass = False)
    for value in (str, bool, dict):
        assert f(value) is value
    with pytest.raises(InvalidDataError):
        f("not a class")


@pytest.mark.parametrize("cls", [int, str])
def test_strict_mode_type_of_union_accepts_its_members(cls):
    """type[int | str] names two classes (once strict mode compared the value with the union itself)."""
    f = _checked(type[int | str], allow_subclass = False)
    assert f(cls) is cls
    with pytest.raises(InvalidDataError):
        f(float)                                            # not a member
    with pytest.raises(InvalidDataError):
        f(bool)                                             # a subclass of int: strict mode wants the exact class


@pytest.mark.parametrize("annotation, accepted, rejected", [
    (Sequence[int], [[1], (1,), "ab"], [1, {1}]),
    (Mapping[str, int], [{"a": 1}], [[1]]),
    (Callable, [len], [1]),
    (Iterable, [[1], "a"], [1]),
    (numbers.Real, [1, 1.5], ["a", 1j]),
    (Sequence | int, [[1], 1], [True, 1.5]),
    (Sequence | Mapping, [[1], {}], [1]),
    ], ids = ["Sequence[int]", "Mapping[str, int]", "Callable", "Iterable", "numbers.Real", "Sequence | int", "Sequence | Mapping"])
def test_strict_mode_accepts_implementations_of_an_abstract_class(annotation, accepted, rejected):
    """
    Nothing has an abstract class as its exact type, so strict mode accepts what implements it
    (once it rejected every value). A concrete member beside it stays exact: True is no int.
    """
    f = _checked(annotation, allow_subclass = False)
    for value in accepted:
        assert f(value) is value
    for value in rejected:
        with pytest.raises(InvalidDataError):
            f(value)


def test_strict_mode_abstract_base_class_and_protocol():
    class Shape(abc.ABC):
        @abc.abstractmethod
        def area(self) -> float: ...

    class Circle(Shape):
        def area(self) -> float:
            return 3.14

    class UnitCircle(Circle):
        pass

    @runtime_checkable
    class Closeable(Protocol):
        def close(self) -> None: ...

    class Connection:
        def close(self) -> None: ...

    shape = _checked(Shape, allow_subclass = False)
    assert isinstance(shape(Circle()), Circle) and isinstance(shape(UnitCircle()), UnitCircle)
    with pytest.raises(InvalidDataError):
        shape(1)

    circle = _checked(Circle, allow_subclass = False)       # a class that can be instantiated keeps the exact match
    circle(Circle())
    with pytest.raises(InvalidDataError):
        circle(UnitCircle())

    closeable = _checked(Closeable, allow_subclass = False)
    closeable(Connection())
    with pytest.raises(InvalidDataError):
        closeable(1)


def test_strict_mode_abstract_class_details():
    #* A check on an abstract type, a default, and the class form: type[X] still wants the class itself.
    short = _checked(Annotated[Sequence, lambda s: len(s) < 3], allow_subclass = False)
    assert short([1]) == [1]
    with pytest.raises(InvalidDataError) as exc:
        short([1, 2, 3])
    assert exc.value.problems[0].kind == "invalid"

    @validate(allow_subclass = False)
    def f(xs: Sequence[int] = ()) -> Any:
        return xs

    assert f() == () and f([1]) == [1]

    cls = _checked(type[Sequence], allow_subclass = False)
    assert cls(Sequence) is Sequence
    with pytest.raises(InvalidDataError):
        cls(list)


# ═════════════════════════════════════════════════════════════════════════════
#  CLASSES
# ═════════════════════════════════════════════════════════════════════════════

def test_class_without_own_init():
    @enforce
    class Empty:
        pass

    Empty()


def test_dunder_methods_not_checked():
    @enforce
    class Money:
        def __eq__(self, other: "Money") -> bool:
            return False

    assert (Money() == "not money") is False


def test_staticmethod_checked_by_class_decorator():
    @enforce
    class Util:
        @staticmethod
        def parse(v: float) -> float:
            return v

    assert Util.parse(1.5) == 1.5
    with pytest.raises(InvalidDataError):
        Util.parse("1.5")


def test_classmethod_checked_by_class_decorator():
    @enforce
    class Factory:
        @classmethod
        def make(cls, name: str) -> str:
            return name

    assert Factory.make("a") == "a"
    with pytest.raises(InvalidDataError):
        Factory.make(1)


# ── @validate above another decorator: the attribute stays what that decorator made it ──

def test_validate_above_classmethod():
    class Factory:
        @validate(check_return = True)
        @classmethod
        def make(cls, name: str, size: float = 1) -> str:
            return f"{cls.__name__}:{name}:{size!r}"

        @classmethod
        @validate
        def usual_order(cls, name: str) -> str:
            return name

    class Child(Factory):
        pass

    assert isinstance(vars(Factory)["make"], classmethod)
    assert Factory.make("a") == "Factory:a:1.0"             # on the class, with the default converted
    assert Factory().make("a", 2) == "Factory:a:2.0"        # on an instance
    assert Child.make("a") == "Child:a:1.0"                 # cls is the class it was called on
    assert Factory.make.__name__ == "make"
    for call in (lambda: Factory.make(1), lambda: Factory().make(1), lambda: Child.make("a", "big")):
        with pytest.raises(InvalidDataError):
            call()
    with pytest.raises(InvalidDataError) as exc:
        Factory.make()                                      # cls isn't counted as the missing argument
    assert "Missing required argument" in _plain(exc.value) and "name (expecting type str)" in _plain(exc.value)


def test_validate_above_staticmethod():
    class Util:
        @validate
        @staticmethod
        def double(x: float) -> float:
            return x * 2

    assert isinstance(vars(Util)["double"], staticmethod)
    assert Util.double(2) == 4.0
    assert Util().double(2) == 4.0                          # an instance isn't passed in as x
    for call in (lambda: Util.double("2"), lambda: Util().double("2")):
        with pytest.raises(InvalidDataError) as exc:
            call()
        assert "For parameter x of <Function double>: expected type: 'float', got type 'str'" in _plain(exc.value)


def test_validate_above_property():
    class Account:
        def __init__(self) -> None:
            self._balance = 0.0

        @validate(check_return = True)
        @property
        def balance(self) -> float:
            """The money in the account."""
            return self._balance

        @validate
        @balance.setter
        def balance(self, value: float) -> None:
            self._balance = value

        @validate(check_return = True)
        @property
        def broken(self) -> int:
            return "no"                                     # type: ignore[return-value]

    assert isinstance(vars(Account)["balance"], property)
    assert Account.balance.__doc__ == "The money in the account."
    account = Account()
    assert account.balance == 0.0                           # a value, not a bound method
    account.balance = 5
    assert account.balance == 5.0 and type(account.balance) is float
    with pytest.raises(InvalidDataError) as exc:
        account.balance = "5"                               # type: ignore[assignment]
    assert "For parameter value of <Method Account.balance>" in _plain(exc.value)     # it finds its class through self
    with pytest.raises(InvalidDataError, match = "return"):
        account.broken


def test_validate_above_property_keeps_accessors_that_are_already_checked():
    class Account:
        @validate(check_return = True)
        @property
        def balance(self) -> float:
            return 1.0

        getter = balance.fget

        @validate
        @balance.setter
        def balance(self, value: float) -> None: ...

        @balance.deleter
        def balance(self) -> None: ...

    balance = vars(Account)["balance"]
    assert balance.fget is Account.getter                   # not wrapped a second time by the setter's decorator
    assert balance.fset is not None and balance.fdel is not None
    del Account().balance


def test_validate_above_cached_property():
    from functools import cached_property
    calls: list[int] = []

    class Report:
        @validate(check_return = True)
        @cached_property
        def total(self) -> float:
            calls.append(1)
            return 3                                        # converted to 3.0

        @validate(check_return = True)
        @cached_property
        def broken(self) -> int:
            return "no"                                     # type: ignore[return-value]

    assert isinstance(vars(Report)["total"], cached_property)
    report = Report()
    assert (report.total, report.total, type(report.total), calls) == (3.0, 3.0, float, [1])
    with pytest.raises(InvalidDataError, match = "return"):
        report.broken


def test_validate_above_abstract_classmethod_stays_abstract():
    class Base(abc.ABC):
        @validate
        @classmethod
        @abc.abstractmethod
        def make(cls, name: str) -> "Base": ...

    class Concrete(Base):
        @validate
        @classmethod
        def make(cls, name: str) -> "Concrete":
            return cls()

    with pytest.raises(TypeError, match = "abstract"):
        Base()
    assert isinstance(Concrete.make("a"), Concrete)
    with pytest.raises(InvalidDataError):
        Concrete.make(1)


def test_validate_on_something_that_is_not_callable_is_refused_at_the_definition():
    with pytest.raises(InvalidDataError) as exc:
        validate(42)                                        # type: ignore[call-overload]
    text = _plain(exc.value)
    assert "validate cannot check 42: a int object is not callable" in text
    assert "Put @validate directly above the function" in text
    with pytest.raises(InvalidDataError):
        validate(deep = True)("not a function")             # type: ignore[arg-type]

    class Slot:                                             # a descriptor validate doesn't know
        def __get__(self, instance: Any, owner: Any) -> int: return 1

    with pytest.raises(InvalidDataError, match = "Slot"):
        validate(Slot())                                    # type: ignore[call-overload]


def test_self_return_violation_with_check_return():
    @enforce(check_return = True)
    class Builder:
        def build(self) -> Self:
            return 42  # type: ignore[return-value]

    with pytest.raises(InvalidDataError):
        Builder().build()


def test_class_missing_init_argument():
    @enforce
    class Point:
        def __init__(self, x: float, y: float) -> None:
            self.x, self.y = x, y

    with pytest.raises(InvalidDataError) as exc:
        Point(y=1.0)
    assert "x (expecting type float)" in _plain(exc.value)


# ═════════════════════════════════════════════════════════════════════════════
#  ASYNC / GENERATORS
# ═════════════════════════════════════════════════════════════════════════════

def test_async_valid():
    @validate(check_return = True)
    async def f(x: int) -> str:
        return str(x)

    assert asyncio.run(f(1)) == "1"


def test_async_invalid_argument():
    @validate
    async def f(x: int) -> None:
        pass

    with pytest.raises(InvalidDataError):
        asyncio.run(f("1"))


def test_async_invalid_return():
    @validate(check_return = True)
    async def f(x: int) -> str:
        return x  # type: ignore[return-value]

    with pytest.raises(InvalidDataError):
        asyncio.run(f(1))


def test_generator_argument_checked():
    @validate
    def gen(n: int) -> Iterator[int]:
        yield from range(n)

    assert list(gen(3)) == [0, 1, 2]
    with pytest.raises(InvalidDataError):
        gen("3")


# ═════════════════════════════════════════════════════════════════════════════
#  EDGE CASES
# ═════════════════════════════════════════════════════════════════════════════

def test_unresolved_forward_ref_raises():
    @validate
    def f(x: "DoesNotExist") -> None:  # noqa: F821
        pass

    with pytest.raises(InvalidDataError):
        f(1)


def test_literal_unhashable_input():
    @validate
    def f(x: Literal[1, 2]) -> None:
        pass

    with pytest.raises(InvalidDataError):  # must not leak a raw TypeError
        f([1])


def test_literal_true_and_one_distinct():
    @validate
    def f(x: Literal[1, True]) -> None:
        pass

    f(1)
    f(True)
    with pytest.raises(InvalidDataError):
        f(False)


def test_newtype():
    UserId = NewType("UserId", int)

    @validate
    def f(u: UserId) -> None:
        pass

    f(UserId(5))
    with pytest.raises(InvalidDataError):
        f("5")


def test_kwargs_partial_failure_reports_key():
    @validate
    def f(**kwargs: int) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f(a=1, b="x")
    assert "kwargs[b]" in _plain(exc.value)


def test_args_partial_failure_reports_index():
    @validate
    def f(*args: int) -> None:
        pass

    with pytest.raises(InvalidDataError) as exc:
        f(1, 2, "x")
    assert "args[2]" in _plain(exc.value)


def test_dict_spec_string_name_valid():
    validate_record({"object_name": "f", "record": {"a": int}, "args": (1,)})

def test_dict_spec_string_name_invalid():
    with pytest.raises(InvalidDataError):
        validate_record({"object_name": "f", "record": {"a": int}, "kwargs": {"a": "x"}})

def test_dict_spec_callable_uses_real_signature():
    def f(a: int, b: str = "x") -> None: ...
    validate_record({"object_name": f, "record": {"a": int, "b": str}, "args": (1,)})

def test_dict_spec_callable_bad_default():
    def f(a: int, b: str = 5) -> None: ...
    with pytest.raises(InvalidDataError):
        validate_record({"object_name": f, "record": {"a": int, "b": str}, "args": (1,)})

def test_dict_spec_missing_key():
    with pytest.raises(InvalidDataError):
        validate_record({"object_name": "f"})

def test_dict_spec_unknown_key():
    with pytest.raises(InvalidDataError):
        validate_record({"object_name": "f", "record": {}, "extra": 1})


"""Tests for the prepared (compiled) fast path: it must agree with the slow path."""
from typing import Literal, Never
from enforced import validate, InvalidDataError
import pytest


def test_fast_and_slow_agree_on_call_shapes():
    @validate
    def f(a: int, /, b: str, *rest: int, c: float = 1.0, **extra: str) -> None: ...

    f(1, "x"); f(1, b="x"); f(1, "x", 2, 3, c=2.0, k="v")
    with pytest.raises(InvalidDataError): f("1", "x")
    with pytest.raises(InvalidDataError): f(1, "x", "bad")
    with pytest.raises(InvalidDataError): f(1, "x", k=5)
    with pytest.raises(InvalidDataError): f(1, "x", c="no")
    with pytest.raises(InvalidDataError, match="Missing"): f(1)
    with pytest.raises(TypeError): f(1, "x", b="again")      # duplicate binding
    with pytest.raises(TypeError): f(a=1, b="x")             # positional-only by keyword


def test_forward_ref_defined_later_is_retried():
    @validate
    def g(x: "Late") -> None: ...

    with pytest.raises(InvalidDataError, match="resolve"):
        g(1)
    globals()["Late"] = int
    try:
        g(1)                                   # now resolvable: must not stay broken
        with pytest.raises(InvalidDataError): g("s")
    finally:
        del globals()["Late"]


def test_literal_never_strict_and_return():
    @validate(allow_subclass=False, check_return=True)
    def h(m: Literal["a", True], n: int) -> int:
        return n

    h("a", 1); h(True, 1)
    with pytest.raises(InvalidDataError): h(1, 1)
    with pytest.raises(InvalidDataError): h("a", True)       # bool is not exactly int

    @validate
    def never(x: Never) -> None: ...
    with pytest.raises(InvalidDataError): never(1)

    @validate(check_return=True)
    def bad() -> int:
        return "s"                                            # type: ignore[return-value]
    with pytest.raises(InvalidDataError, match="return"): bad()


def test_defaults_checked_once_and_still_raise():
    @validate
    def d(x: int = "oops") -> None: ...                      # type: ignore[assignment]
    for _ in range(2):
        with pytest.raises(InvalidDataError, match="default"): d()


def test_record_cached_checker_behaves_identically():
    from enforced import validate_record

    spec = {"object_name": "make", "record": {"a": int, "b": str}}
    for _ in range(3):                                        # 2nd/3rd calls hit the cache
        validate_record({**spec, "kwargs": {"a": 1, "b": "x"}})
        with pytest.raises(InvalidDataError): validate_record({**spec, "kwargs": {"a": "1", "b": "x"}})
        with pytest.raises(InvalidDataError, match="Missing"): validate_record({**spec, "kwargs": {"a": 1}})


def test_record_cache_distinguishes_records_and_flags():
    from enforced import validate_record

    validate_record({"object_name": "f", "record": {"a": int}, "kwargs": {"a": 1}})
    with pytest.raises(InvalidDataError):                     # same name, different record
        validate_record({"object_name": "f", "record": {"a": str}, "kwargs": {"a": 1}})
    class MyInt(int):
        pass
    with pytest.raises(InvalidDataError):                     # same record, strict mode
        validate_record({"object_name": "f", "record": {"a": int}, "kwargs": {"a": MyInt(1)}, "allow_subclass": False})
    validate_record({"object_name": "f", "record": {"a": int}, "kwargs": {"a": MyInt(1)}})


def test_record_cache_keeps_the_order_of_union_members():
    """int | float == float | int, yet conversion follows the declared order: the cached checker must too."""
    def coerce_three(name: str, annotation: Any) -> Any:
        spec = {"object_name": name, "record": {"x": annotation}, "kwargs": {"x": "3"}, "coerce": True}
        return validate_record(spec)[1]["x"]

    alone = coerce_three("union_order_alone", float | int)          # nothing cached under this name yet
    assert type(alone) is float                                     # float is declared first, so '3' -> 3.0

    assert type(coerce_three("union_order_shared", int | float)) is int
    after = coerce_three("union_order_shared", float | int)         # the same spec as `alone`, after int | float
    assert type(after) is float, f"float | int gave {after!r} once int | float had been seen"


def test_record_cache_keeps_the_order_of_nested_unions():
    def coerce_item(annotation: Any) -> Any:
        spec = {"object_name": "union_order_nested", "record": {"xs": annotation, "n": int},
                "kwargs": {"xs": ["3"], "n": 1}, "coerce": True, "deep": True}
        return validate_record(spec)[1]["xs"][0]

    for _ in range(2):                                              # the second round comes from the cache
        assert type(coerce_item(list[int | float])) is int
        assert type(coerce_item(list[float | int])) is float
        assert type(coerce_item(Optional[list[float | int]])) is float


def test_record_cache_reuses_equal_specs_with_unions():
    """A spec rebuilt on every call (new but equal annotation objects) still finds its compiled checker."""
    def call() -> None:
        validate_record({"object_name": "union_order_cached", "record": {"x": int | None, "y": list[int]},
                             "kwargs": {"x": 1, "y": [1]}})

    call()
    size = len(_remembered.RECORD_CACHE)
    for _ in range(3):
        call()
    assert len(_remembered.RECORD_CACHE) == size


def _fill_record_cache() -> None:
    _remembered.RECORD_CACHE.clear()
    for i in range(_remembered._RECORD_CACHE_MAX):
        validate_record({"object_name": f"filler_{i}", "record": {"x": int}, "args": (1,)})


def test_record_cache_evicts_the_oldest_entry_when_full():
    _fill_record_cache()
    oldest, newest = next(iter(_remembered.RECORD_CACHE)), list(_remembered.RECORD_CACHE)[-1]
    for i in range(10):
        validate_record({"object_name": f"extra_{i}", "record": {"x": int}, "args": (1,)})
    assert len(_remembered.RECORD_CACHE) == _remembered._RECORD_CACHE_MAX
    assert oldest not in _remembered.RECORD_CACHE and newest in _remembered.RECORD_CACHE
    with pytest.raises(InvalidDataError):                     # an evicted spec is simply compiled again
        validate_record({"object_name": "filler_0", "record": {"x": int}, "args": ("1",)})


def test_record_full_cache_under_threads():
    """Misses from several threads at once, each evicting an entry: no thread may fail, the limit must hold."""
    import sys
    import threading

    _fill_record_cache()
    threads, rounds = 8, 150
    failures: list[BaseException] = []
    results: list[Any] = []
    start = threading.Barrier(threads)

    def work(n: int) -> None:
        try:
            start.wait()
            for i in range(rounds):
                spec = {"object_name": f"thread_{n}_{i}", "record": {"x": float}, "args": (i,)}
                results.append(validate_record(spec)[0][0])
                with pytest.raises(InvalidDataError):
                    validate_record({**spec, "args": ("x",)})
        except BaseException as e:                            # RuntimeError / KeyError before the fix
            failures.append(e)

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                               # switch threads as often as possible
    try:
        workers = [threading.Thread(target = work, args = (n,)) for n in range(threads)]
        for w in workers: w.start()
        for w in workers: w.join()
    finally:
        sys.setswitchinterval(interval)

    assert failures == []
    assert len(results) == threads * rounds and all(type(r) is float for r in results)
    assert len(_remembered.RECORD_CACHE) <= _remembered._RECORD_CACHE_MAX


def test_record_same_new_spec_from_several_threads_shares_one_checker():
    import threading

    _remembered.RECORD_CACHE.clear()
    threads = 8
    start = threading.Barrier(threads)
    outcomes: list[Any] = []

    def work() -> None:
        start.wait()
        try:
            outcomes.append(validate_record({"object_name": "shared_spec", "record": {"x": int | float, "y": str},
                                                 "args": (1, "a")}))
        except BaseException as e:
            outcomes.append(e)

    workers = [threading.Thread(target = work) for _ in range(threads)]
    for w in workers: w.start()
    for w in workers: w.join()
    assert outcomes == [((1, "a"), {})] * threads
    assert len(_remembered.RECORD_CACHE) == 1
    (names, by_order), = _remembered.RECORD_CACHE.values()         # one record with a union: one member order, one checker
    assert names == ("x",) and len(by_order) == 1


def test_record_checker_stored_meanwhile_is_the_one_used():
    """Two threads that miss on the same spec both build a checker; the second must adopt the first one's."""
    _remembered.RECORD_CACHE.clear()
    record = {"x": int}
    key = ("adopted", tuple(record.items()), True, False, True, False, False)
    first, second = object(), object()
    assert _remembered._remember_checker(key, record, first) is first             # type: ignore[arg-type]
    assert _remembered._remember_checker(key, record, second) is first            # type: ignore[arg-type]
    union = {"x": int | str}
    key = ("adopted", tuple(union.items()), True, False, True, False, False)
    assert _remembered._remember_checker(key, union, first) is first              # type: ignore[arg-type]
    assert _remembered._remember_checker(key, union, second) is first             # type: ignore[arg-type]
    assert _remembered._remember_checker(key, {"x": str | int}, second) is second     # type: ignore[arg-type]
    _remembered.RECORD_CACHE.clear()


# ── annotations given as strings in a record: read as data, never run ────────

@pytest.mark.parametrize("annotation, good, bad", [
    ("int", 1, "a"), (" str ", "a", 1), ("list[int]", [1], (1,)), ("int | None", None, "a"), ("dict[str, list[int]]", {"a": [1]}, []),
    ("tuple[int, ...]", (1, 2), [1]), ("type[int]", bool, str), ("ValueError", ValueError("x"), KeyError("x")), ("None", None, 0),
    ("list[int] | tuple[int, str] | None", (1, "a"), {1}),
    ], ids = lambda v: v if isinstance(v, str) else "")
def test_record_string_annotation_names_builtin_classes(annotation, good, bad):
    spec = {"object_name": "f", "record": {"x": annotation}}
    assert validate_record({**spec, "args": (good,)}) == ((good,), {})
    with pytest.raises(InvalidDataError) as exc:
        validate_record({**spec, "args": (bad,)})
    assert "Cannot resolve" not in _plain(exc.value)


def test_record_string_annotation_checks_items_with_deep():
    spec = {"object_name": "f", "record": {"x": "dict[str, list[int]]"}, "deep": True}
    assert validate_record({**spec, "args": ({"a": [1, 2]},)})[0] == ({"a": [1, 2]},)
    with pytest.raises(InvalidDataError) as exc:
        validate_record({**spec, "args": ({"a": [1, "2"]},)})
    assert [p.parameter for p in exc.value.problems] == ["x['a'][1]"]


def test_record_string_annotation_is_never_run_as_code():
    """A record may come from a config file or a request: a string in it must not be able to call anything."""
    import builtins
    ran: list[int] = []
    builtins._enforced_probe = ran                          # type: ignore[attr-defined]  (what eval would reach)
    attempts = [
        "_enforced_probe.append(1) or int",
        "__import__('os').getcwd() and int",
        "(lambda: _enforced_probe.append(1))() or int",
        "[_enforced_probe.append(1) for _ in (1,)] and int",
        "int if _enforced_probe.append(1) is None else str",
        "int.__subclasses__()[0]",
        "_enforced_probe",                                  # a name that isn't a built-in class
        "eval",                                               # a built-in, but not a class
        "open('x', 'w')",
        typing.ForwardRef("_enforced_probe.append(1) or int"),
        list["_enforced_probe.append(1) or int"],
        typing.Optional["_enforced_probe.append(1) or int"],
        ]
    try:
        for annotation in attempts:
            for deep in (False, True):
                spec = {"object_name": "f", "record": {"x": annotation}, "kwargs": {"x": [1]}, "deep": deep}
                try:
                    validate_record(spec)
                except InvalidDataError:
                    pass                                      # "Cannot resolve annotation": the usual outcome
                assert ran == [], f"{annotation!r} was run"
        with pytest.raises(InvalidDataError, match = "Cannot resolve annotation"):
            validate_record({"object_name": "f", "record": {"x": attempts[0]}, "kwargs": {"x": 1}})
    finally:
        del builtins._enforced_probe                        # type: ignore[attr-defined]


def test_string_annotation_on_a_function_still_sees_its_module():
    """The names in a function's own annotations come from its source: they are resolved as before."""
    @validate
    def f(walker: "Dog | None", sizes: "typing.Sequence[int]" = ()) -> None: ...

    f(Dog()), f(None, [1])
    with pytest.raises(InvalidDataError):
        f(5)


def test_record_callable_defaults_and_unhashable_data():
    from enforced import validate_record

    def bad(x: int = "no"): ...                               # type: ignore[assignment]
    for _ in range(2):
        with pytest.raises(InvalidDataError, match="default"):
            validate_record({"object_name": bad, "record": {"x": int}, "kwargs": {"x": 1}})

    #* An unhashable annotation just skips the cache instead of crashing.
    class Weird:
        __hash__ = None   # type: ignore[assignment]
    validate_record({"object_name": "w", "record": {"a": Weird()}, "kwargs": {"a": 1}})


# ── generated (exec) wrappers ────────────────────────────────────────────────
import inspect
import pickle


@validate
def module_level(a: int, b: str = "x") -> int:
    return a


@pytest.mark.usefixtures("compiled_at_once")
def test_generated_wrapper_preserves_metadata_and_pickles():
    assert module_level.__name__ == "module_level"
    assert module_level.__wrapped__ is not None
    assert list(inspect.signature(module_level).parameters) == ["a", "b"]
    assert not hasattr(module_level, "__enforced_source__")   # generated lazily...
    assert module_level(1) == 1
    assert "def _pv_wrapper" in module_level.__enforced_source__  # ...on the first call
    assert pickle.loads(pickle.dumps(module_level)) is module_level


def test_positional_only_name_as_kwrd_goes_to_var_kwargs():
    @validate
    def f(p: int = 0, /, **extra: str) -> tuple:
        return p, extra

    assert f(p="s") == (0, {"p": "s"})         # Python sends p= to **extra
    with pytest.raises(InvalidDataError, match=r"extra\[p\]"):
        f(p=1)                                  # ... so it is checked against str


def test_parameter_names_that_shadow_wrapper_internals():
    @validate
    def f(args: int, kwargs: str, _pv_a: int = 0, *, _pv_k: float = 0.0) -> int:
        return args

    assert f(1, "x") == 1
    assert f(args=1, kwargs="x", _pv_a=2, _pv_k=1.5) == 1
    with pytest.raises(InvalidDataError): f(1, 2)
    with pytest.raises(InvalidDataError): f(1, "x", _pv_k="no")


def test_dataclass_inheritance_and_slots_assign_checks():
    from enforced import dataclass

    @dataclass
    class Base:
        x: int

    @dataclass
    class Child(Base):
        y: str

    c = Child(1, "a")
    c.x = 2; c.y = "b"
    with pytest.raises(InvalidDataError): c.x = "no"
    with pytest.raises(InvalidDataError): c.y = 3
    b = Base(1)
    with pytest.raises(InvalidDataError): b.x = "no"
    with pytest.raises(InvalidDataError): Child("1", "a")

    @dataclass(slots=True)
    class S:
        v: float

    s = S(1.0)
    s.v = 2.0
    with pytest.raises(InvalidDataError): s.v = "no"


def test_literal_in_union_accepts_the_other_members():
    """
    A Literal inside a union must not swallow the union's other members.
    Today the whole union is checked as "one of the literal values", so None, plain strs,
    ints and the like are rejected even though the annotation allows them.
    """
    #* The common case: an optional mode with a None default.
    @validate
    def open_file(mode: Optional[Literal["r", "w"]] = None) -> None: ...

    open_file()                                 # bug: InvalidDataError "in definition" (the None default)
    open_file(None)                             # bug: rejected
    open_file("r")

    #* Literal next to a plain type: any str must pass, not only the literal values.
    @validate
    def label(x: Literal[1] | str) -> None: ...

    label(1)
    label("hello")                              # bug: rejected

    #* Literal next to another class.
    @validate
    def level(x: Literal["auto"] | int) -> None: ...

    level("auto")
    level(5)                                    # bug: rejected

    #* The same inside collections (deep) and dataclass fields.
    @validate(deep = True)
    def modes(xs: list[Literal["r", "w"] | None]) -> None: ...

    modes(["r", None])                          # bug: None item rejected

    @dataclass
    class File:
        mode: Literal["r", "w"] | None = None   # bug: definition error on the default

    File()
    File("w")

    #* What must still be rejected: values outside every member.
    with pytest.raises(InvalidDataError):
        open_file("x")                          # not a literal value, not None
    with pytest.raises(InvalidDataError):
        label(2)                                # not 1, not a str
    with pytest.raises(InvalidDataError):
        level("manual")                         # not "auto", not an int
    with pytest.raises(InvalidDataError):
        modes(["x"])

# ═════════════════════════════════════════════════════════════════════════════
#  ANNOTATIONS AND TARGETS THAT USED TO BE ACCEPTED WITHOUT A CHECK (review finding 5)
# ═════════════════════════════════════════════════════════════════════════════

import datetime                                                 # noqa: E402
import functools                                                # noqa: E402
import pathlib                                                  # noqa: E402
import threading                                                # noqa: E402
from collections import OrderedDict                             # noqa: E402
from collections.abc import ItemsView, KeysView, MappingView, ValuesView      # noqa: E402
from typing import LiteralString, ReadOnly, Required, TypeGuard, TypeIs, Unpack   # noqa: E402
import enforced._validator._container as _container
import enforced._validator._lifetime as _lifetime
import enforced._validator._text as _text


class MovieKeys(TypedDict):
    year: float
    title: str


class Options(TypedDict, total = False):
    name: Required[str]
    size: int
    tags: ReadOnly[list[str]]


def test_unpacked_typeddict_kwargs_are_checked_key_by_key():
    @validate
    def release(**kwargs: Unpack[MovieKeys]) -> Any:
        return kwargs

    assert release(year = 2009, title = "Up") == {"year": 2009.0, "title": "Up"}      # converted like any argument
    assert type(release(year = 2009, title = "Up")["year"]) is float
    with pytest.raises(InvalidDataError) as wrong:
        release(year = "2009", title = 5)
    assert [p.parameter for p in wrong.value.problems] == ["year", "title"]
    with pytest.raises(InvalidDataError, match = "Missing required argument for <Function release>: title"):
        release(year = 1.0)
    with pytest.raises(InvalidDataError, match = "unexpected keyword argument 'director'"):
        release(year = 1.0, title = "Up", director = "x")


def test_unpacked_typeddict_kwargs_with_optional_keys_and_other_parameters():
    @validate(check_return = True, deep = True)
    def build(count: int, *rest: str, flag: bool = False, **options: Unpack[Options]) -> dict:
        return options

    assert build(1, name = "a") == {"name": "a"}            # the optional keys may be left out
    assert build(1, "x", "y", flag = True, name = "a", size = 2, tags = ["t"]) == {"name": "a", "size": 2, "tags": ["t"]}
    assert build(2, name = "b") == {"name": "b"}            # the compiled wrapper gives the same
    for bad, parameter in ((lambda: build(1, name = "a", size = "2"), "size"), (lambda: build(1, name = 5), "name"),
                           (lambda: build(1, name = "a", tags = ["t", 5]), "tags[1]"), (lambda: build("1", name = "a"), "count")):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert [p.parameter for p in e.value.problems] == [parameter]
    with pytest.raises(InvalidDataError, match = "Missing required argument"):
        build(1)
    #* What the function shows to the outside is what was written.
    assert "**options" in str(inspect.signature(build))


def test_unpacked_typeddict_key_named_like_a_parameter_keeps_the_parameter():
    class Clash(TypedDict):
        count: str
        extra: int

    @validate
    def f(count: int, **kwargs: Unpack[Clash]) -> Any:
        return count, kwargs

    assert f(1, extra = 2) == (1, {"extra": 2})
    with pytest.raises(InvalidDataError):
        f("1", extra = 2)                                   # count is the parameter: an int


def test_plain_kwargs_annotation_is_unchanged():
    @validate
    def f(**kwargs: int) -> Any:
        return kwargs

    assert f(a = 1, anything = 2) == {"a": 1, "anything": 2}
    with pytest.raises(InvalidDataError, match = r"kwargs\[b\]"):
        f(a = 1, b = "x")


def test_unpacked_tuple_args_are_checked_as_that_tuple():
    @validate
    def move(speed: float, *point: *tuple[int, str]) -> Any:
        return speed, point

    assert move(1, 2, "north") == (1.0, (2, "north"))
    assert move(1.5, 2, "north") == (1.5, (2, "north"))     # every call takes the same path
    with pytest.raises(InvalidDataError) as wrong:
        move(1.0, "north", 2)
    assert [p.parameter for p in wrong.value.problems] == ["point[0]", "point[1]"]
    for bad in (lambda: move(1.0), lambda: move(1.0, 2), lambda: move(1.0, 2, "north", 3)):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert [p.kind for p in e.value.problems] == ["length"]
    with pytest.raises(InvalidDataError) as both:
        move("fast", 2, 3)                                  # the other parameters are reported with it
    assert [p.parameter for p in both.value.problems] == ["speed", "point[1]"]


def test_unpacked_tuple_args_convert_and_follow_deep():
    @validate
    def shallow(*args: *tuple[float, list[int]]) -> Any:
        return args

    @validate(deep = True, coerce = True)
    def deep(*args: *tuple[float, list[int]]) -> Any:
        return args

    assert shallow(1, ["a"]) == (1.0, ["a"])                # converted; the list's items only with deep
    assert type(shallow(1, [])[0]) is float
    assert deep("1.5", ["2", 3]) == (1.5, [2, 3])
    with pytest.raises(InvalidDataError) as e:
        deep(1.0, [1, "x"])
    assert [p.parameter for p in e.value.problems] == ["args[1][1]"]


def test_unpacked_tuple_args_of_any_length_and_of_none():
    @validate
    def numbers(*args: *tuple[float, ...]) -> Any:           # what *args: float says
        return args

    @validate
    def nothing(*args: *tuple[()]) -> Any:
        return args

    @validate
    def loose[*Ts](*args: *Ts) -> Any:                       # nothing that can be checked
        return args

    assert numbers() == () and numbers(1, 2.5) == (1.0, 2.5)
    with pytest.raises(InvalidDataError, match = r"args\[1\]"):
        numbers(1.0, "x")
    assert nothing() == ()
    with pytest.raises(InvalidDataError):
        nothing(1)
    assert loose(1, "a", None) == (1, "a", None)


def test_literal_string_is_a_str():
    @validate
    def run(query: LiteralString, limit: int = 1) -> Any:
        return query

    assert run("select 1") == "select 1"
    with pytest.raises(InvalidDataError, match = "expected type: 'str', got type 'int'"):
        run(5)


def test_type_guard_and_type_is_return_a_bool():
    @validate(check_return = True)
    def is_int(value: object) -> TypeGuard[int]:
        return isinstance(value, int)

    @validate(check_return = True)
    def is_str(value: object) -> TypeIs[str]:
        return "yes"                                        # type: ignore[return-value]

    assert is_int(1) is True and is_int("a") is False
    with pytest.raises(InvalidDataError, match = "For return value of <Function is_str>: expected type: 'bool'"):
        is_str("a")


class LoneMethods:
    """Not enforced: each method carries its own ``@validate`` and has to find its class itself."""

    @validate(check_return = True)
    def link(self, other: Self) -> Self:
        return other

    @validate(check_return = True)
    def broken(self) -> Self:
        return 5                                            # type: ignore[return-value]

    @validate
    @classmethod
    def make(cls, count: int) -> "LoneMethods":
        return cls()

    @validate
    @staticmethod
    def static(count: int) -> int:
        return count

    @validate
    def __init__(self, label: str = "") -> None:
        self.label = label


class LoneChild(LoneMethods):
    pass


def test_self_in_a_method_decorated_on_its_own_is_checked():
    one, two, child = LoneMethods(), LoneMethods(), LoneChild()
    assert one.link(two) is two and child.link(child) is child and one.link(LoneChild()) is not None
    with pytest.raises(InvalidDataError) as wrong:
        one.link(5)
    assert "For parameter other of <Method LoneMethods.link>: expected type: 'test_validator.LoneMethods'" in _plain(wrong.value)
    with pytest.raises(InvalidDataError) as wrong:
        child.link(two)                                     # Self is the class of the instance: a LoneChild
    assert "For parameter other of <Method LoneMethods.link>: expected type: 'test_validator.LoneChild'" in _plain(wrong.value)
    with pytest.raises(InvalidDataError, match = "For return value of <Method LoneMethods.broken>"):
        one.broken()


def test_method_decorated_on_its_own_is_reported_as_a_method_of_its_class():
    for bad, label in ((lambda: LoneMethods.make("x"), "<Method LoneMethods.make>"),
                       (lambda: LoneMethods().make("x"), "<Method LoneMethods.make>"),
                       (lambda: LoneMethods.static("x"), "<Method LoneMethods.static>"),
                       (lambda: LoneMethods(5), "<Class LoneMethods>"),
                       (lambda: LoneChild(5), "<Class LoneMethods>")):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert label in _plain(e.value)


def test_a_function_that_only_looks_like_a_method_is_not_given_a_class():
    def free(self, n: int) -> Any:
        return n

    free.__qualname__ = "LoneMethods.free"                  # the class has no such attribute
    with pytest.raises(InvalidDataError) as e:
        validate(free)(LoneMethods(), "x")
    assert "<Function free>" in _plain(e.value)


def test_private_method_decorated_on_its_own_finds_its_class():
    class Vault:
        @validate
        def __seal(self, code: int) -> int:
            return code

        def close(self, code: Any) -> Any:
            return self.__seal(code)

    assert Vault().close(1) == 1
    with pytest.raises(InvalidDataError) as e:
        Vault().close("x")
    assert "<Method Vault.__seal>" in _plain(e.value)


def test_a_plain_function_is_still_a_function():
    def build():
        @validate
        def inner(x: int) -> Any:
            return x
        return inner

    @validate
    def top(x: int) -> Any:
        return x

    for function, label in ((build(), "<Function inner>"), (top, "<Function top>")):
        with pytest.raises(InvalidDataError) as e:
            function("x")
        assert label in _plain(e.value)


def test_callable_object_is_checked_against_its_call_method():
    class Adder:
        def __call__(self, a: int, b: float = 0) -> float:
            return a + b

        def other(self) -> None: ...

    add = validate(Adder(), check_return = True)
    assert add(1, 2) == 3.0 and type(add(1, 2)) is float
    with pytest.raises(InvalidDataError) as e:
        add(1, "2")
    assert "For parameter b of <Callable Adder>: expected type: 'float', got type 'str'" in _plain(e.value)
    with pytest.raises(InvalidDataError, match = "Missing required argument"):
        add()


def test_partial_is_checked_for_the_parameters_it_still_takes():
    def send(host: str, port: int, retries: float = 1) -> tuple:
        return host, port, retries

    to_local = validate(functools.partial(send, "localhost"))
    assert to_local(80) == ("localhost", 80, 1) and to_local(80, retries = 2) == ("localhost", 80, 2.0)
    with pytest.raises(InvalidDataError) as e:
        to_local("80")
    assert [p.parameter for p in e.value.problems] == ["port"]
    with pytest.raises(InvalidDataError):
        to_local(80, retries = "many")
    #* An argument fixed by keyword is the parameter's default now, and is checked as one.
    with pytest.raises(InvalidDataError, match = "default value of parameter retries"):
        validate(functools.partial(send, retries = "many"))("localhost", 80)


def test_callables_without_annotations_anywhere_are_passed_through():
    class Bare:
        def __call__(self, value):
            return value

    assert validate(len)([1, 2]) == 2
    assert validate(Bare())("anything") == "anything"
    #* max doesn't say what it takes: inspect can't read a signature. It used to fail on every call.
    assert validate(max)(1, 3, 2) == 3 and validate(max)([1, 2], key = lambda n: -n) == 1
    assert validate(functools.partial(max, 1))(2) == 2
    with pytest.raises(TypeError, match = "expected at least 1 argument"):
        validate(max)()                                     # the builtin's own error, untouched


@pytest.mark.parametrize("not_an_annotation", [5, 1.5, True, ["int"], {"a": "int"}, (int, str), b"int", "5", "[int]", "(int, str)"])
def test_record_value_that_is_no_annotation_is_refused(not_an_annotation):
    for deep in (False, True):
        with pytest.raises(InvalidDataError, match = "is not a type annotation"):
            validate_record({"object_name": "f", "record": {"x": not_an_annotation}, "kwargs": {"x": "anything"},
                                 "deep": deep})


def test_plain_data_as_a_function_annotation_is_refused_too():
    @validate(check_return = True)
    def f(x: 5 = 1) -> [int]:                               # type: ignore[valid-type]
        return x

    with pytest.raises(InvalidDataError) as e:
        f(1)
    assert "Cannot check parameter x: 5 is not a type annotation" in _plain(e.value)


def test_annotations_without_a_runtime_test_are_still_accepted():
    #* What falls through to "anything" on purpose must not be caught by the test above.
    from typing import Concatenate, ParamSpec

    P = ParamSpec("P")

    @validate
    def call(fn: Callable[Concatenate[int, P], int], *args: P.args, **kwargs: P.kwargs) -> Any:
        return fn(1, *args, **kwargs)

    @validate
    def anything(a: Any, b: object, c: "int | None" = None, d: tuple[()] = (), e: Callable[[int], str] = str) -> Any:
        return a

    assert call(lambda a, b, c = 0: a + b + c, 2, c = 3) == 6
    assert anything(1, 2) == 1
    assert validate_record({"object_name": "f", "record": {"x": "int | None", "y": "tuple[int, ...]"},
                                "kwargs": {"x": None, "y": ()}}) == ((), {"x": None, "y": ()})


# ═════════════════════════════════════════════════════════════════════════════
#  MESSAGES THAT CONTRADICTED THEMSELVES (review finding 6)
# ═════════════════════════════════════════════════════════════════════════════

type ModeAlias = Literal["r", "w"]


class MessageColor(enum.Enum):
    RED = 1


class MessageAnimal:
    pass


@validate(check_return = True)
def message_target(mode: Literal["r", "w"] = "r", kind: type[int] = int, maybe: Literal["r"] | None = None,
                   cls: type[MessageAnimal] | None = None, alias: ModeAlias = "r", color: MessageColor = MessageColor.RED,
                   both: int | str = 1, mixed: Literal[1, "one"] | float = 1) -> Literal["done"]:
    return "not done"                                       # type: ignore[return-value]


@pytest.mark.parametrize("argument, expected, got", [
    ({"mode": "x"}, "Literal['r', 'w']", "'str' (Value: 'x')"),
    ({"mode": 5}, "Literal['r', 'w']", "'int' (Value: 5)"),
    ({"kind": str}, "'type[int]'", "'type' (Value: <class 'str'>)"),
    ({"maybe": "w"}, "Literal['r'] | None", "'str' (Value: 'w')"),
    ({"cls": int}, "'type[test_validator.MessageAnimal] | None'", "'type' (Value: <class 'int'>)"),
    ({"alias": "x"}, "Literal['r', 'w']", "'str' (Value: 'x')"),
    ({"mixed": "two"}, "Literal[1, 'one'] | float", "'str' (Value: 'two')"),
    ])
def test_literal_and_class_annotations_are_shown_as_written(argument, expected, got):
    with pytest.raises(InvalidDataError) as e:
        message_target(**argument)
    name = next(iter(argument))
    assert f"For parameter {name} of <Function message_target>: expected type: {expected}, got type {got}" in _plain(e.value)
    problem = e.value.problems[0]
    assert problem.annotation == message_target.__wrapped__.__annotations__[name]     # the annotation, as data


def test_ordinary_types_are_shown_as_before():
    for argument, text in (({"both": 1.5}, "expected type: 'int' | 'str', got type 'float' (Value: 1.5)"),
                           ({"mode": "r", "both": None}, "expected type: 'int' | 'str', got type 'NoneType' (Value: None)")):
        with pytest.raises(InvalidDataError) as e:
            message_target(**argument)
        assert text in _plain(e.value)


def test_literal_return_value_and_default_are_shown_as_written():
    with pytest.raises(InvalidDataError) as e:
        message_target()
    assert "For return value of <Function message_target>: expected type: Literal['done'], got type 'str' (Value: 'not done')" in _plain(e.value)

    @validate
    def bad_default(mode: Literal["fast", "slow"] = "turbo") -> None: ...      # type: ignore[assignment]

    with pytest.raises(InvalidDataError) as e:
        bad_default()
    assert "For default value of parameter mode of <Function bad_default>: expected type: Literal['fast', 'slow']" in _plain(e.value)


def test_enum_and_local_classes_are_named_in_full():
    class Local:
        pass

    @validate
    def f(color: MessageColor = MessageColor.RED, local: Local | None = None) -> None: ...

    with pytest.raises(InvalidDataError) as e:
        f(5)
    assert "expected type: 'test_validator.MessageColor', got type 'int'" in _plain(e.value)        # was: <enum 'MessageColor'
    with pytest.raises(InvalidDataError) as e:
        f(MessageColor.RED, MessageColor.RED)
    assert "got type 'test_validator.MessageColor'" in _plain(e.value)
    with pytest.raises(InvalidDataError) as e:
        f(local = 5)
    assert "'Local' | 'NoneType'" in _plain(e.value)

    @validate
    def g(local: Local) -> None: ...

    with pytest.raises(InvalidDataError) as e:
        g(5)
    assert "expected type: 'test_validator.test_enum_and_local_classes_are_named_in_full.<locals>.Local'," in _plain(e.value)


def test_literal_item_inside_a_collection_is_shown_as_written():
    @validate(deep = True)
    def f(modes: list[Literal["a", "b"]], kinds: dict[str, type[int]] | None = None) -> None: ...

    with pytest.raises(InvalidDataError) as e:
        f(["a", "c"], {"k": str})
    text = _plain(e.value)
    assert "modes at index [1] of <Function f>: expected type: Literal['a', 'b'], got type 'str' (Value: 'c')" in text
    assert "kinds at index ['k'] of <Function f>: expected type: 'type[int]', got type 'type'" in text


# ═════════════════════════════════════════════════════════════════════════════
#  THE ANNOTATION CACHES LET THEIR OLDEST ENTRY GO (review finding 7)
# ═════════════════════════════════════════════════════════════════════════════

def test_unpacked_cache_evicts_the_oldest_entry_when_full(monkeypatch):
    monkeypatch.setattr(_container, "_UNPACKED_MAX", 8)
    monkeypatch.setattr(_container, "_UNPACKED", {})
    cache = _container._UNPACKED
    kept = [int | str if i % 2 else list[int] for i in range(40)]      # 40 distinct annotation objects
    for annotation in kept:
        _container.TypeContainer(None, "x", 1, annotation)
        assert id(annotation) in cache                      # the newest one is always cached
        assert len(cache) <= 8
    assert [id(a) in cache for a in kept[-8:]] == [True] * 8
    assert not any(id(a) in cache for a in kept[:32])
    #* An entry that was pushed out is simply worked out again.
    assert _container.TypeContainer(None, "x", 1, kept[0]).check() is False
    assert _container.TypeContainer(None, "x", 1, kept[1]).check() is True


def test_deep_node_cache_evicts_the_oldest_entry_when_full(monkeypatch):
    monkeypatch.setattr(_specs, "_DEEP_NODES_MAX", 6)
    monkeypatch.setattr(_specs, "_DEEP_NODES", {})
    annotations = [list[int] for _ in range(30)]
    for annotation in annotations:
        node = _specs.deep_node(annotation, True, True, False)
        assert node is not None and (id(annotation), True, True, False) in _specs._DEEP_NODES
        assert len(_specs._DEEP_NODES) <= 6
    assert _specs.deep_node(annotations[-1], True, True, False) is _specs.deep_node(annotations[-1], True, True, False)
    assert _specs.deep_node(annotations[0], True, True, False).check([1]) is True      # compiled again, and right


@pytest.mark.usefixtures("compiled_at_once")
def test_wrapper_cache_evicts_the_oldest_entry_when_full(monkeypatch):
    monkeypatch.setattr(_codegen, "_CODE_CACHE_MAX", 4)
    monkeypatch.setattr(_codegen, "_CODE_CACHE", {})

    def function_with(count: int) -> Callable[..., Any]:
        names = ", ".join(f"p{i}: int" for i in range(count))
        namespace: dict[str, Any] = {}
        exec(f"def f({names}): return {count}", namespace)
        return validate(namespace["f"])

    for count in range(1, 13):                              # twelve signature shapes
        f = function_with(count)
        assert f(*range(count)) == count
        assert f.__enforced_source__ in _codegen._CODE_CACHE    # a function defined late is cached like an early one
        assert len(_codegen._CODE_CACHE) <= 4
        with pytest.raises(InvalidDataError):
            f(*["x"] * count)


def test_full_caches_under_threads(monkeypatch):
    monkeypatch.setattr(_container, "_UNPACKED_MAX", 16)
    monkeypatch.setattr(_specs, "_DEEP_NODES_MAX", 16)
    monkeypatch.setattr(_codegen, "_CODE_CACHE_MAX", 4)
    for module, name in ((_container, "_UNPACKED"), (_specs, "_DEEP_NODES"), (_codegen, "_CODE_CACHE")):
        monkeypatch.setattr(module, name, {})
    failures: list[str] = []
    barrier = threading.Barrier(8)

    def work(seed: int) -> None:
        try:
            barrier.wait(timeout = 10)
            for i in range(120):
                def f(a, b = None, *rest): return a
                f.__annotations__ = {"a": list[int], "b": int | str | None, "rest": dict[str, float]}
                del f.__defaults__                          # another shape now and then: two required parameters
                f.__defaults__ = (None,) if (i + seed) % 3 else ()
                checked = validate(f, deep = bool(i % 2))
                arguments = ([1], 2) if (i + seed) % 3 else ([1], "b")
                assert checked(*arguments) == [1]
                try:
                    checked(5, 2)
                except InvalidDataError as e:
                    str(e)                                  # rendering goes through the unpacked cache too
                else:
                    failures.append("a wrong argument was accepted")
        except Exception as error:                          # noqa: BLE001
            failures.append(f"{type(error).__name__}: {error}")

    threads = [threading.Thread(target = work, args = (n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert len(_container._UNPACKED) <= 16 and len(_specs._DEEP_NODES) <= 16 and len(_codegen._CODE_CACHE) <= 4


# ═════════════════════════════════════════════════════════════════════════════
#  STRICT MODE AND CLASSES THAT HAVE NO INSTANCE OF EXACTLY THEIR OWN TYPE (review finding 8)
# ═════════════════════════════════════════════════════════════════════════════

class StrictLevel(enum.IntEnum):
    LOW = 1


class StrictFlag(enum.Flag):
    A = 1


@pytest.mark.parametrize("annotation, value", [
    (pathlib.Path, pathlib.Path("a")),
    (pathlib.PurePath, pathlib.PurePath("a")),
    (pathlib.PurePath, pathlib.Path("a")),
    (numbers.Number, 1), (numbers.Number, 1.5), (numbers.Number, 1j),
    (KeysView, {}.keys()), (ItemsView, {}.items()), (ValuesView, {}.values()), (MappingView, {}.keys()),
    (KeysView, OrderedDict().keys()),
    (type, int), (type, enum.Enum), (type, MessageColor), (type, abc.ABC), (type, Sequence),
    (enum.Enum, MessageColor.RED), (enum.IntEnum, StrictLevel.LOW), (enum.Flag, StrictFlag.A),
    (datetime.tzinfo, datetime.timezone.utc),
    ], ids = repr)
def test_strict_mode_accepts_what_these_classes_describe(annotation, value):
    def f(x): return x
    f.__annotations__ = {"x": annotation, "return": annotation}
    for flags in ({}, {"deep": True}, {"check_return": True}):
        assert validate(f, allow_subclass = False, **flags)(value) is value

    def g(x = value): return x
    g.__annotations__ = {"x": annotation}
    assert validate(g, allow_subclass = False)() is value           # as a default too

    def h(xs): return xs
    h.__annotations__ = {"xs": list[annotation] | None}
    assert validate(h, allow_subclass = False, deep = True)([value]) == [value]


@pytest.mark.parametrize("annotation, value", [
    (pathlib.Path, "a"), (pathlib.Path, pathlib.PurePosixPath("a")), (numbers.Number, "1"), (KeysView, []),
    (ItemsView, {}.keys()), (type, 5), (type, MessageColor.RED), (enum.Enum, 1), (enum.IntEnum, MessageColor.RED),
    (datetime.tzinfo, "UTC"), (MessageColor, StrictLevel.LOW), (int, StrictLevel.LOW),
    ], ids = repr)
def test_strict_mode_still_rejects_what_they_do_not_describe(annotation, value):
    def f(x): return x
    f.__annotations__ = {"x": annotation}
    with pytest.raises(InvalidDataError):
        validate(f, allow_subclass = False)(value)


def test_strict_mode_is_still_exact_for_ordinary_classes():
    class Animal: ...
    class Dog(Animal): ...
    class Shape(abc.ABC):                                   # an ABC of the user's, without abstract methods
        pass
    class Square(Shape): ...

    @validate(allow_subclass = False)
    def f(a: Animal | None = None, n: int = 1, e: Exception | None = None, p: pathlib.PosixPath | None = None,
          s: Shape | None = None, r: numbers.Real | None = None) -> None: ...

    f(Animal(), 1, Exception("x"), s = Shape(), r = 1.5)    # Real has abstract methods: an implementation passes
    for bad in ({"a": Dog()}, {"n": True}, {"e": ValueError("x")}, {"s": Square()}):
        with pytest.raises(InvalidDataError):
            f(**bad)
    assert _container.is_abstract(Shape) is False and _container.is_abstract(pathlib.PosixPath) is False
    assert _container.is_abstract(pathlib.Path) and _container.is_abstract(numbers.Number)
    assert _container.is_abstract(type) and not _container.is_abstract(int)


# ═════════════════════════════════════════════════════════════════════════════
#  A QUOTED NAME THAT IS LOCAL TO A FUNCTION (review finding 9; this file has no future import)
# ═════════════════════════════════════════════════════════════════════════════

def test_quoted_annotation_naming_a_local_class():
    class Inner:
        pass

    @validate(check_return = True)
    def f(x: "Inner", others: "list[Inner] | None" = None) -> "Inner":
        return x

    @dataclass
    class Holder:
        inner: "Inner"

    @enforce
    class Service:
        def use(self, inner: "Inner", holder: "Holder | None" = None) -> Any:
            return inner

    inner = Inner()
    assert f(inner) is inner and Holder(inner).inner is inner and Service().use(inner, Holder(inner)) is inner
    for bad in (lambda: f(5), lambda: Holder(5), lambda: Service().use(5), lambda: Service().use(inner, 5)):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_unquoted_local_annotations_cost_nothing_to_remember():
    #* Without the future import Python keeps the scope of an unquoted annotation itself.
    class Inner:
        pass

    @validate
    def f(x: Inner, n: int = 0) -> Any:
        return x

    assert not hasattr(f.__wrapped__, "__enforced_scope__")
    assert isinstance(f(Inner()), Inner)
    with pytest.raises(InvalidDataError):
        f(5)


# ═════════════════════════════════════════════════════════════════════════════
#  THE FIFTH REVIEW: THE FINDINGS THAT WERE STILL OPEN
# ═════════════════════════════════════════════════════════════════════════════
import collections                                              # noqa: E402
import copy                                                     # noqa: E402
import warnings                                                 # noqa: E402
import contextlib                                               # noqa: E402
from typing import TypeVarTuple, no_type_check                  # noqa: E402


# ── finding 1: a checked generator function is one for inspect, and is still checked at the call ──

@validate
def r5_numbers(start: int = 5, step: float = 1):
    yield start
    yield start + step
    return "done"


@validate(check_return = True)
async def r5_async_numbers(start: int = 5):
    yield start
    yield start + 1


@pytest.fixture
@validate
def r5_number(request: Any, start: int = 5):
    """A yield fixture: pytest takes the generator apart only when it is told this is a generator function."""
    yield start


@pytest.mark.usefixtures("compiled_at_once")
def test_checked_generator_function_is_a_generator_function_for_inspect():
    assert inspect.isgeneratorfunction(r5_numbers)
    assert not inspect.iscoroutinefunction(r5_numbers) and not inspect.isasyncgenfunction(r5_numbers)
    assert list(r5_numbers()) == [5, 6.0] and list(r5_numbers(1, 2)) == [1, 3.0]
    assert inspect.isgeneratorfunction(r5_numbers)                  # also once the wrapper is compiled
    assert "__enforced_source__" in vars(r5_numbers)


def test_checked_generator_function_is_still_checked_when_it_is_called():
    with pytest.raises(InvalidDataError, match = "start"):
        r5_numbers("a")                                             # at the call: no next() was needed
    generator = r5_numbers(2)
    assert inspect.isgenerator(generator) and inspect.getgeneratorstate(generator) == "GEN_CREATED"
    assert next(generator) == 2

    def relay():
        return (yield from r5_numbers(1))                           # the return value comes through

    assert list(relay()) == [1, 2.0]
    drained = relay()
    with pytest.raises(StopIteration) as stop:
        while True:
            next(drained)
    assert stop.value.value == "done"


def test_pytest_yield_fixture_under_validate(r5_number):
    assert r5_number == 5                                           # it was the generator object itself


def test_checked_async_generator_function_is_one_for_inspect():
    assert inspect.isasyncgenfunction(r5_async_numbers)
    assert not inspect.iscoroutinefunction(r5_async_numbers) and not inspect.isgeneratorfunction(r5_async_numbers)

    async def collect(*args: Any) -> list:
        return [item async for item in r5_async_numbers(*args)]

    assert asyncio.run(collect()) == [5, 6] and asyncio.run(collect(1)) == [1, 2]
    with pytest.raises(InvalidDataError):
        r5_async_numbers("a")                                       # checked at the call here too
    assert inspect.isasyncgenfunction(r5_async_numbers)


def test_other_functions_keep_their_kind():
    @validate
    def ordinary(x: int) -> int:
        return x

    @validate
    async def coroutine(x: int) -> int:
        return x

    @validate
    def returns_a_generator(n: int) -> Iterator[int]:               # no generator function: it returns one
        return iter(range(n))

    for fn in (ordinary, returns_a_generator):
        assert not inspect.isgeneratorfunction(fn) and not inspect.iscoroutinefunction(fn)
    assert inspect.iscoroutinefunction(coroutine) and not inspect.isgeneratorfunction(coroutine)
    assert ordinary(1) == 1 and asyncio.run(coroutine(2)) == 2 and list(returns_a_generator(2)) == [0, 1]
    assert ordinary(2) == 2 and asyncio.run(coroutine(3)) == 3      # compiled: still the same kinds
    assert not inspect.isgeneratorfunction(ordinary) and inspect.iscoroutinefunction(coroutine)


def test_generator_kinds_through_other_decorators_and_callables():
    def numbers(start: int):
        yield start

    assert inspect.isgeneratorfunction(validate(validate(numbers)))             # stacked
    assert inspect.isgeneratorfunction(validate(functools.partial(numbers, 1)))
    managed = contextlib.contextmanager(validate(numbers))
    with managed(3) as value:
        assert value == 3
    with pytest.raises(InvalidDataError):
        managed("a")

    @enforce
    class Feed:
        def items(self, n: int):
            yield from range(n)

        async def stream(self, n: int):
            yield n

        @classmethod
        def made(cls, n: int):
            yield n

    assert inspect.isgeneratorfunction(Feed.items) and inspect.isgeneratorfunction(Feed().items)
    assert inspect.isasyncgenfunction(Feed.stream) and inspect.isgeneratorfunction(Feed.made)
    assert list(Feed().items(2)) == [0, 1] and list(Feed.made(1)) == [1]
    with pytest.raises(InvalidDataError):
        Feed().items("a")


def test_no_warning_when_a_wrapper_gets_its_compiled_code():
    #* Python 3.14 deprecates giving a function the code of another kind (a generator's to a plain one).
    with warnings.catch_warnings():
        warnings.simplefilter("error")

        @validate(check_return = True)
        def numbers(start: int) -> Iterator[int]:
            yield start

        @validate
        async def stream(start: int):
            yield start

        @validate
        async def coroutine(x: int) -> int:
            return x

        @validate
        def ordinary(x: float) -> float:
            return x

        for _ in range(3):
            assert list(numbers(1)) == [1] and ordinary(1) == 1.0 and asyncio.run(coroutine(1)) == 1
            assert inspect.isasyncgen(stream(1))


# ── finding 33: the flag is tried on the Python that runs, before any wrapper carries it ──────────

def test_the_generator_flag_is_tried_before_it_is_used():
    #* On this Python a flagged ordinary function runs at once, so wrappers carry both flags.
    assert _codegen._runs_at_once(inspect.CO_GENERATOR) and _codegen._runs_at_once(inspect.CO_ASYNC_GENERATOR)
    assert _codegen._FLAGGED == inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
    #* What a Python that acts on the flag would do: calling the function hands back a generator
    #* and runs nothing. Code that really is a generator function's shows the trial notices.
    made_a_generator = "def _pv_wrapper(*_pv_a, **_pv_k):\n    yield _pv_fn\n"
    assert not _codegen._runs_at_once(inspect.CO_GENERATOR, made_a_generator)
    assert not _codegen._runs_at_once(inspect.CO_GENERATOR, "def _pv_wrapper(:\n")       # code Python refuses


def test_without_the_flag_a_generator_function_is_checked_all_the_same(monkeypatch):
    #* Where the trial fails, wrappers get plain code: review finding 1 is back (inspect takes the
    #* wrapper for an ordinary function), and nothing else changes. No check is lost.
    monkeypatch.setattr(_codegen, "_FLAGGED", 0)
    monkeypatch.setattr(_wrapping, "BOOT_CODES", _codegen._stub_codes("_pv_bootstrap(_pv_a, _pv_k)"))
    monkeypatch.setattr(_wrapping, "PLAIN_CODES", _codegen._stub_codes("_pv_fn(*_pv_a, **_pv_k)"))
    assert _wrapping.BOOT_CODES[inspect.CO_GENERATOR] is _wrapping.BOOT_CODES[0]

    with warnings.catch_warnings():
        warnings.simplefilter("error")

        @validate(check_return = True)
        def numbers(start: int, step: float = 1) -> Iterator[float]:
            yield start
            yield start + step

        @validate
        async def stream(start: int):
            yield start

        @no_type_check
        @validate
        def unchecked(start: int):
            yield start

        for _ in range(3):                                          # the bootstrap, then the compiled wrapper
            assert list(numbers(1)) == [1, 2.0] and list(unchecked("a")) == ["a"]
            with pytest.raises(InvalidDataError, match = "start"):
                numbers("a")                                        # at the call
            assert inspect.isasyncgen(stream(1))
            with pytest.raises(InvalidDataError):
                stream("a")
    assert not inspect.isgeneratorfunction(numbers) and not inspect.isasyncgenfunction(stream)
    assert not numbers.__code__.co_flags & inspect.CO_GENERATOR


# ── finding 14: a converted default reaches a function whose defaults aren't its own ──────────────

def _r5_logged(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)
    return wrapper


@pytest.mark.usefixtures("compiled_at_once")
def test_default_is_converted_under_a_functools_wraps_decorator():
    @validate
    @_r5_logged
    def scaled(x: int, factor: float = 2, *, bias: complex = 1) -> tuple:
        return factor, bias

    for call in (lambda: scaled(1), lambda: scaled(x = 1), lambda: scaled(1, bias = 2), lambda: scaled(1, 3),
                 lambda: scaled(1, factor = 3), lambda: scaled(1, 3, bias = 4)):
        for _ in range(3):                                          # the first call, and the compiled wrapper
            factor, bias = call()
            assert type(factor) is float and type(bias) is complex, (factor, bias)
    assert scaled(1) == (2.0, 1) and scaled(1, 3, bias = 4) == (3.0, 4)
    with pytest.raises(InvalidDataError):
        scaled("a")
    assert "__enforced_source__" in vars(scaled)                  # it does get the fast wrapper


def test_default_is_converted_for_a_partial_a_callable_object_and_a_stacked_decorator():
    def send(host: str, port: int, retries: float = 3) -> Any:
        return retries

    fixed = validate(functools.partial(send, retries = 2))          # fixed by keyword: the parameter's default now
    assert [type(fixed("h", 1)) for _ in range(3)] == [float] * 3 and fixed("h", 1, retries = 5) == 5.0

    class Scaler:
        def __call__(self, x: int, scale: float = 2) -> Any:
            return scale

    scaler = validate(Scaler())
    assert [type(scaler(1)) for _ in range(3)] == [float] * 3 and type(scaler(1, 3)) is float

    @validate
    @validate
    def twice(x: int, factor: float = 2) -> Any:
        return factor

    @validate
    @functools.lru_cache
    def cached(x: int, factor: float = 2) -> Any:
        return factor

    assert [type(twice(1)) for _ in range(3)] == [float] * 3
    assert [type(cached(1)) for _ in range(3)] == [float] * 3


def test_converted_default_of_a_positional_only_parameter_is_passed_by_position():
    @validate
    @_r5_logged
    def f(a: int, b: float = 2, c: str = "c", d: float = 4, /) -> tuple:
        return b, c, d

    for _ in range(3):
        assert f(1) == (2.0, "c", 4.0) and [type(v) for v in f(1)] == [float, str, float]
        assert f(1, 5) == (5.0, "c", 4.0) and type(f(1, 5)[2]) is float
        assert f(1, 5, "x", 6) == (5.0, "x", 6.0)


# ── finding 16: a pickled error keeps its problems ────────────────────────────────────────────────

@validate
def r5_top(x: int, mode: Literal["r", "w"] = "r") -> int:
    return x


@enforce
class R5Service:
    def run(self, n: int) -> int:
        return n

    @classmethod
    def make(cls, n: int) -> "R5Service":
        return cls()


@dataclass
class R5Point:
    x: float
    y: float = 0.0


def _r5_error(fn: Any, *args: Any, **kwargs: Any) -> InvalidDataError:
    with pytest.raises(InvalidDataError) as raised:
        fn(*args, **kwargs)
    return raised.value


def test_pickled_error_keeps_its_problems_and_its_message():
    error = _r5_error(r5_top, "a", "x")
    for restored in (pickle.loads(pickle.dumps(error)), copy.deepcopy(error), copy.copy(error),
                     pickle.loads(pickle.dumps(pickle.loads(pickle.dumps(error))))):     # and a second trip
        assert type(restored) is InvalidDataError and isinstance(restored, TypeError)
        assert str(restored) == str(error) and restored.context == "call" and restored.args == (str(error),)
        assert [(p.kind, p.parameter, p.expected, p.value, p.detail) for p in restored.problems] == [
            ("type", "x", int, "a", None), ("type", "mode", str, "x", None)]
        assert restored.problems[1].annotation == Literal["r", "w"]
        assert [str(p) for p in restored.problems] == [str(p) for p in error.problems]
        assert all(p.origin is r5_top.__wrapped__ for p in restored.problems)   # the function itself, found again


def test_pickled_error_finds_methods_and_classes_again():
    for error, origin in ((_r5_error(R5Service().run, "a"), R5Service.run.__wrapped__),
                          (_r5_error(R5Service.make, "a"), R5Service.make.__func__.__wrapped__),
                          (_r5_error(R5Point, "a"), R5Point.__init__.__wrapped__)):
        restored = pickle.loads(pickle.dumps(error))
        assert restored.problems[0].origin is origin and str(restored) == str(error)
    assignment = _r5_error(setattr, R5Point(1.0), "x", "a")
    restored = pickle.loads(pickle.dumps(assignment))
    assert restored.context == "field assignment" and restored.problems[0].kind == "field"
    assert restored.problems[0].origin is R5Point and "Field R5Point.x of <Dataclass R5Point>" in _plain(restored)
    missing = pickle.loads(pickle.dumps(_r5_error(r5_top)))
    assert (missing.problems[0].kind, missing.problems[0].parameter, missing.problems[0].expected) == ("missing", ("x",), (int,))

    @validate
    def bad_default(x: int = "a") -> Any:                           # type: ignore[assignment]
        return x

    definition = pickle.loads(pickle.dumps(_r5_error(bad_default)))
    assert definition.context == "definition" and definition.problems[0].kind == "default"
    assert "1 problem found in definition" in _plain(definition)


def test_pickled_error_replaces_what_cannot_be_pickled():
    from enforced._validator._errors import Unpickled

    class LocalValue:                                               # pickle can't find a local class
        def __repr__(self) -> str:
            return "<a local value>"

    @validate
    def local(x: int, lock: int = 0) -> Any:
        return x

    error = _r5_error(local, LocalValue(), threading.Lock())
    restored = pickle.loads(pickle.dumps(error))
    assert str(restored) == str(error) and len(restored.problems) == 2
    value, lock = (p.value for p in restored.problems)
    assert isinstance(value, Unpickled) and repr(value) == "<a local value>"
    assert isinstance(lock, Unpickled) and "lock" in repr(lock)
    assert isinstance(restored.problems[0].origin, Unpickled)       # a local function can't be found by name
    assert [p.parameter for p in restored.problems] == ["x", "lock"] and restored.problems[0].expected is int
    again = pickle.loads(pickle.dumps(restored))
    assert again.problems[0].value == value and str(again) == str(error)
    assert pickle.loads(pickle.dumps(InvalidDataError("plain message"))).args == ("plain message",)


# ── finding 20: a positional-only parameter passed by keyword ─────────────────────────────────────

def test_positional_only_parameter_passed_by_keyword_is_a_binding_error():
    @validate
    def f(a: int = 1, b: int = 2, /) -> tuple:
        return a, b

    for kwargs in ({"b": 2}, {"b": "x"}, {"a": 1, "b": 2}):         # it used to end in Python's own TypeError,
        for _ in range(2):                                          # or in a type error for a call that can't be made
            with pytest.raises(InvalidDataError) as e:
                f(**kwargs)
            assert e.value.problems == []
            assert "got some positional-only arguments passed as keyword arguments: " + repr(", ".join(kwargs)) in _plain(e.value)
    assert f(1, 2) == (1, 2) and f() == (1, 2)

    @validate
    def g(a: int = 1, b: int = 2, /, **extra: int) -> tuple:        # with **kwargs the keyword is simply another one
        return a, b, extra

    assert g(b = 5) == (1, 2, {"b": 5})
    with pytest.raises(InvalidDataError) as e:
        g(b = "x")
    assert e.value.problems[0].parameter == "extra[b]"


# ── finding 22: a message doesn't format the whole value ──────────────────────────────────────────

def test_short_repr_formats_only_what_it_shows():
    formatted = []

    class Item:
        def __init__(self, index: int) -> None:
            self.index = index

        def __repr__(self) -> str:
            formatted.append(self.index)
            return f"Item({self.index})"

    items = [Item(i) for i in range(100_000)]
    assert _text.short_repr(items) == "[Item(0), Item(1), Item(2), Item(3), ..."
    assert len(formatted) <= 6                                      # it used to be all 100,000

    @validate(deep = True)
    def f(xs: dict[str, int]) -> Any:
        return xs

    formatted.clear()
    with pytest.raises(InvalidDataError) as e:
        f({"a": items})
    assert "(Value: [Item(0), Item(1), Item(2), Item(3), ...)" in _plain(e.value) and len(formatted) <= 6


@pytest.mark.parametrize("value", [
    [], (), {}, set(), frozenset(), (1,), [1], {1}, frozenset({1}), {"a": 1}, [[]], ([],), "", b"",
    list(range(100)), tuple(range(100)), set(range(100)), frozenset(range(100)), {i: str(i) for i in range(50)},
    [list(range(50))] * 3, {"key": [{"nested": (1, 2, [3, {4, 5}])}] * 9}, [(), {}, set(), frozenset(), [[]]] * 9,
    "x" * 200, "it's" + "y" * 200, 'say "hi"' + "z" * 200, "a" * 50 + "'", "a" * 50 + "'\"", "\n\t\\é" * 30,
    b"x" * 200, b"it's" + b"y" * 99, bytearray(b"ab" * 99), [b"x" * 99, "y" * 99], ("a" * 39, 1), ("a" * 38, 1),
    [1.5, None, True, 2j, ..., int, len], {(1, 2): [3]}, [{"a": "b" * 40}], collections.deque(range(99)), range(10**9),
    ])
def test_short_repr_is_the_start_of_repr(value):
    for limit in (20, 30, 37, 38, 39, 40, 41, 60, 80):
        full = repr(value)
        assert _text.short_repr(value, limit) == (full if len(full) <= limit else full[:limit - 3] + "...")


def test_short_repr_of_values_that_contain_themselves_or_cannot_be_shown():
    itself: list = [1, 2]
    itself.append(itself)
    mapping: dict = {"a": 1}
    mapping["me"] = mapping
    pair: tuple = ([],)
    pair[0].append(pair)
    for value in (itself, mapping, pair, [itself] * 30, {"k": mapping}):
        full = repr(value)
        assert _text.short_repr(value) == (full if len(full) <= 40 else full[:37] + "...")

    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("no repr")

    assert _text.short_repr(Broken()) == "<unrepresentable Broken>"
    assert _text.short_repr([Broken()] * 99) == "<unrepresentable list>"


# ── finding 26: typing.no_type_check, written above or below ──────────────────────────────────────

def test_no_type_check_below_validate_leaves_the_function_as_it_is():
    @no_type_check
    def plain(x: int) -> int:
        return x

    assert validate(plain) is plain and validate(check_return = True)(plain) is plain
    assert plain("a") == "a"

    class Holder:
        @validate
        @classmethod
        @no_type_check
        def make(cls, x: int) -> Any:
            return x

    assert Holder.make("a") == "a" and not hasattr(Holder.make.__func__, "__wrapped__")


def test_no_type_check_above_validate_switches_the_checks_off():
    @no_type_check
    @validate(check_return = True)
    def late(x: int) -> int:                                        # marked after the wrapper was made
        return x

    @no_type_check
    @validate
    async def late_coroutine(x: int) -> int:
        return x

    @no_type_check
    @validate
    def late_generator(x: int):
        yield x

    for _ in range(3):
        assert late("a") == "a" and asyncio.run(late_coroutine("b")) == "b" and list(late_generator("c")) == ["c"]
    assert "__enforced_source__" not in vars(late)                # no checking code was ever generated
    assert inspect.iscoroutinefunction(late_coroutine) and inspect.isgeneratorfunction(late_generator)

    @validate
    def checked(x: int) -> int:
        return x

    with pytest.raises(InvalidDataError):
        checked("a")


def test_no_type_check_on_an_enforced_class_and_on_a_dataclass():
    def build(decorate: Any) -> type:
        class Thing:
            def __init__(self, x: int) -> None:
                self.x = x

            def twice(self, y: int) -> Any:
                return y

            @classmethod
            def made(cls, y: int) -> Any:
                return y

            @staticmethod
            def fee(y: int) -> Any:
                return y
        return decorate(Thing)

    below = build(lambda cls: enforce(no_type_check(cls)))
    above = build(lambda cls: no_type_check(enforce(cls)))
    for Thing in (below, above):
        for _ in range(2):
            assert Thing("a").twice("b") == "b" and Thing.made("c") == "c" and Thing.fee("d") == "d"
    assert not hasattr(below.twice, "__wrapped__")                  # marked first: never wrapped at all

    @enforce
    class Mixed:
        def checked(self, x: int) -> Any:
            return x

        @no_type_check
        def free(self, x: int) -> Any:
            return x

    assert Mixed().free("a") == "a" and not hasattr(Mixed.free, "__wrapped__")
    with pytest.raises(InvalidDataError):
        Mixed().checked("a")

    for decorate in (lambda cls: dataclass(no_type_check(cls)), lambda cls: no_type_check(dataclass(cls)),
                     lambda cls: no_type_check(dataclass(slots = True)(cls))):
        class Record:
            x: int
            y: float = 0

        Record = decorate(Record)
        record = Record("a")
        record.x = []                                               # neither construction nor assignment is checked
        assert dataclasses.is_dataclass(Record) and record.x == [] and record.y == 0


# ── finding 35: typing.no_type_check speaks for the class it is written on, not for a subclass ────

@pytest.mark.parametrize("mark_base", [
    lambda cls: no_type_check(dataclasses.dataclass(cls)),          # a standard dataclass, marked
    lambda cls: dataclass(no_type_check(cls)),                      # enforced's, marked below
    lambda cls: no_type_check(dataclass(cls)),                      # enforced's, marked above
    ], ids = ["standard", "below", "above"])
@pytest.mark.parametrize("options", [{}, {"slots": True}, {"deep": True}, {"check_assignment": False}],
                         ids = ["plain", "slots", "deep", "no assignment check"])
def test_a_dataclass_below_a_class_marked_no_type_check_is_checked(mark_base, options):
    class Base:
        x: int
        tags: list = dataclasses.field(default_factory = list)
    Base = mark_base(Base)

    @dataclass(**options)
    class Child(Base):
        y: int = 0
        ratio: float = 1

    #* Its own fields are checked (it was an unchecked standard dataclass: typing.get_type_hints
    #* returns nothing for a class that inherits the mark).
    with pytest.raises(InvalidDataError, match = "y"):
        Child(1, [], "b")
    child = Child("anything", "at all", 2, 3)
    assert type(child.ratio) is float and child.ratio == 3.0       # ... and converted
    #* What the marked base annotated is no type hint: those fields take what they are given.
    assert child.x == "anything" and child.tags == "at all"
    if not options:
        child.x = None
        with pytest.raises(InvalidDataError, match = "Field Child.y"):
            child.y = "b"
    assert Base("a").x == "a"                                       # the base itself is unchecked, as before
    assert vars(Child)["__no_type_check__"] is False and Base.__no_type_check__ is True


def test_no_type_check_of_a_base_class_further_down_the_line():
    @no_type_check
    @dataclasses.dataclass
    class Base:
        x: int
        y: int = 0

    @dataclass
    class Child(Base):
        x: str = ""                                                 # written again below the mark: a type hint

    @dataclass
    class Grandchild(Child):
        z: int = 0

    @no_type_check
    @dataclass
    class Free(Grandchild):
        w: int = 0

    for cls in (Child, Grandchild):
        assert cls("a", "anything").y == "anything"
        with pytest.raises(InvalidDataError, match = "x"):
            cls(5)
    with pytest.raises(InvalidDataError, match = "z"):
        Grandchild("a", 1, "c")
    assert Free(5, 6, "c", "d").w == "d"                            # marked itself: a standard dataclass again
    assert typing.get_type_hints(Free) == {} and set(typing.get_type_hints(Child)) == {"x", "y"}


def test_an_enforced_class_below_a_class_marked_no_type_check_is_checked_too():
    #* The same rule for both decorators: the mark is the base's own.
    @no_type_check
    class Base:
        def inherited(self, x: int) -> Any:
            return x

    @enforce
    class Child(Base):
        def own(self, x: int) -> Any:
            return x

    assert Child().inherited("a") == "a"
    with pytest.raises(InvalidDataError):
        Child().own("a")


# ── finding 28: Self inside an annotation ─────────────────────────────────────────────────────────

def test_self_inside_an_annotation_is_the_class():
    @enforce(check_return = True)
    class Node:
        def parent(self, of: Self | None = None) -> Self | None:
            return of

        def both(self, others: list[Self], named: dict[str, Self] | None = None) -> tuple[Self, ...]:
            return tuple(others)

        @classmethod
        def kind(cls) -> type[Self]:
            return cls

        def wrong(self) -> Optional[Self]:
            return 5                                                # type: ignore[return-value]

        def wrong_class(self) -> type[Self]:
            return int                                              # type: ignore[return-value]

    class Leaf(Node):
        pass

    node = Node()
    assert node.parent(node) is node and node.parent() is None and node.parent(Leaf()) is not None
    assert node.both([node]) == (node,) and Node.kind() is Node and Leaf.kind() is Leaf
    for bad in (lambda: node.parent(5), node.wrong, node.wrong_class, lambda: node.both("ab")):
        with pytest.raises(InvalidDataError):
            bad()
    with pytest.raises(InvalidDataError) as e:
        node.parent("x")
    assert "expected type: 'Node' | 'NoneType', got type 'str'" in _plain(e.value)   # Self | None accepted anything before


def test_self_inside_a_collection_is_checked_with_deep():
    @enforce(deep = True, check_return = True)
    class Node:
        def all(self, others: list[Self]) -> list[Self]:
            return others

        def by_name(self, named: dict[str, Self | None]) -> Any:
            return named

    node = Node()
    assert node.all([node, node]) == [node, node] and node.by_name({"a": node, "b": None})
    with pytest.raises(InvalidDataError) as e:
        node.all([node, 5])
    assert e.value.problems[0].parameter == "others[1]"
    with pytest.raises(InvalidDataError) as e:
        node.by_name({"a": "x"})
    assert e.value.problems[0].parameter == "named['a']"


def test_self_inside_an_annotation_in_strict_mode_and_in_a_lone_method_and_a_dataclass():
    @enforce(check_return = True, allow_subclass = False)
    class Strict:
        def me(self) -> Self | None:
            return self

        @classmethod
        def kind(cls) -> type[Self]:
            return cls

        def other(self) -> type[Self]:
            return int                                              # type: ignore[return-value]

    class Child(Strict):
        pass

    assert isinstance(Child().me(), Child) and Child.kind() is Child and Strict.kind() is Strict
    with pytest.raises(InvalidDataError):
        Strict().other()

    class Lone:
        @validate(check_return = True)
        def pick(self, other: Self | None = None) -> Self | None:
            return other

    lone = Lone()
    assert lone.pick(lone) is lone and lone.pick() is None
    with pytest.raises(InvalidDataError) as e:
        lone.pick(5)
    assert "For parameter other of <Method Lone.pick>" in _plain(e.value)

    @dataclass
    class Link:
        value: int
        next: Self | None = None

    assert Link(1, Link(2)).next.value == 2
    with pytest.raises(InvalidDataError):
        Link(1, "x")
    with pytest.raises(InvalidDataError):
        Link(1).next = 5


# ── finding 29: typed **kwargs belong to the checker, and any key can be a keyword ────────────────

class R5Movie(TypedDict, total = False):
    title: Required[str]
    year: int


def test_typed_kwargs_do_not_change_what_another_checker_sees():
    def film(**kwargs: Unpack[R5Movie]) -> Any:
        return kwargs

    spec = {"object_name": film, "record": {"kwargs": float}, "kwargs": {"a": 1, "b": 2}}
    assert validate_record(spec) == ((), {"a": 1.0, "b": 2.0})           # **kwargs: float, as the record says
    checked = validate(film)
    assert checked(title = "Up", year = 2009) == {"title": "Up", "year": 2009}
    with pytest.raises(InvalidDataError):
        checked(title = "Up", other = 1)
    #* The same again after the decorated call: it used to see one keyword per key of the TypedDict.
    assert validate_record(spec) == ((), {"a": 1.0, "b": 2.0})
    assert validate_record({**spec, "kwargs": {"anything": 3}}) == ((), {"anything": 3.0})
    assert "**kwargs" in str(inspect.signature(film)) and "**kwargs" in str(inspect.signature(checked))
    assert _signatures.signature_of(film).parameters.keys() == {"kwargs"}


def test_typed_kwargs_with_keys_that_are_no_identifiers():
    Odd = TypedDict("Odd", {"my-key": int, "class": str, "ok": Required[float]}, total = False)

    @validate
    def f(**options: Unpack[Odd]) -> Any:                           # type: ignore[valid-type]
        return options

    for _ in range(3):                                              # these keywords went unchecked before
        assert f(**{"my-key": 1, "class": "a", "ok": 1}) == {"my-key": 1, "class": "a", "ok": 1.0}
        assert f(ok = 2.5) == {"ok": 2.5}
        with pytest.raises(InvalidDataError) as e:
            f(**{"my-key": "x", "ok": 1})
        assert "For parameter my-key of <Function f>: expected type: 'int', got type 'str'" in _plain(e.value)
        with pytest.raises(InvalidDataError):
            f(**{"class": 5, "ok": 1})
        with pytest.raises(InvalidDataError, match = "unexpected keyword"):
            f(ok = 1, other = 2)
        with pytest.raises(InvalidDataError, match = "Missing required argument"):
            f(**{"my-key": 1})


# ── finding 30: *args as a tuple gets the fast wrapper, and may hold a run of unknown length ──────

@pytest.mark.usefixtures("compiled_at_once")
def test_tuple_args_function_gets_the_compiled_wrapper():
    @validate
    def move(speed: float, *point: *tuple[int, str]) -> tuple:
        return speed, point

    assert move(1, 2, "n") == (1.0, (2, "n"))
    assert "__enforced_source__" in vars(move)                    # it stayed on the general path before
    for _ in range(3):
        assert move(1.0, 2, "n") == (1.0, (2, "n"))
        for bad in (lambda: move(1.0, 2), lambda: move(1.0, 2, "n", 3), lambda: move(1.0, "a", "n"), lambda: move(1.0)):
            with pytest.raises(InvalidDataError):
                bad()

    @validate
    def scaled(*point: *tuple[float, float]) -> tuple:              # conversion still happens, on the general path
        return point

    for _ in range(3):
        assert scaled(1, 2) == (1.0, 2.0) and all(type(v) is float for v in scaled(1, 2))


def test_tuple_args_with_a_run_of_unknown_length():
    @validate
    def record(tag: str, *rest: *tuple[int, *tuple[str, ...], float]) -> tuple:
        return rest

    for _ in range(3):
        assert record("t", 1, 2.5) == (1, 2.5) and record("t", 1, "a", "b", 2.5) == (1, "a", "b", 2.5)
        assert record("t", 1, "a", 2) == (1, "a", 2.0)                          # the last one is converted
        for bad, where in ((lambda: record("t", 1, 2, 3.0), "rest[1]"), (lambda: record("t", "a", 2.0), "rest[0]"),
                           (lambda: record("t", 1, "a", "b"), "rest[2]")):
            with pytest.raises(InvalidDataError) as e:
                bad()
            assert [p.parameter for p in e.value.problems] == [where]
        with pytest.raises(InvalidDataError) as e:
            record("t", 1)
        assert "expected type: tuple[int, *tuple[str, ...], float] with at least 2 items, got 1 item" in _plain(e.value)

    Ts = TypeVarTuple("Ts")

    @validate
    def head(*rest: *tuple[int, *Ts]) -> tuple:                     # type: ignore[valid-type]
        return rest

    @validate
    def anything(first: int, *rest: *Ts) -> tuple:                  # type: ignore[valid-type]
        return rest

    assert head(1, "x", None) == (1, "x", None) and anything(1, "x", None) == ("x", None)
    with pytest.raises(InvalidDataError):
        head("a")
    with pytest.raises(InvalidDataError, match = "with at least 1 item, got 0 items"):
        head()


def test_length_message_counts_one_item_in_the_singular():
    @validate(deep = True)
    def f(one: tuple[int] = (1,), two: tuple[int, int] = (1, 2)) -> Any:
        return one, two

    assert "expected type: tuple[int] with 1 item, got 2 items" in _plain(_r5_error(f, (1, 2)))
    assert "expected type: tuple[int, int] with 2 items, got 1 item (Value: (1,))" in _plain(_r5_error(f, (1,), (1,)))
    assert "with 2 items, got 0 items" in _plain(_r5_error(f, (1,), ()))


# ── finding 32: an annotation shown in a message has an end ───────────────────────────────────────

class R5VeryLongClassNameNumberOne:
    pass


class R5VeryLongClassNameNumberTwo:
    pass


def test_long_annotation_is_cut_in_a_message():
    @validate
    def f(x: collections.defaultdict[str, R5VeryLongClassNameNumberOne] | type[R5VeryLongClassNameNumberTwo]
          | Literal["some-quite-long-literal"] | None) -> Any:
        return x

    line = _plain(_r5_error(f, 5))
    shown = line.split("expected type: ")[1].split(", got type")[0]
    assert shown.startswith("'collections.defaultdict[str, test_validator.R5VeryLongClassNameNumberOne]")
    assert shown.endswith("...'") and len(shown) == 82              # 80 characters between the quotes

    @validate
    def g(mode: Literal["r", "w"], kind: type[int]) -> Any:         # a short one is shown whole, as before
        return mode

    assert "expected type: Literal['r', 'w'], got type 'str'" in _plain(_r5_error(g, "x", int))
    text = _plain(_r5_error(validate_record, {"object_name": "f", "record": {"x": "nonsense(" + "a" * 300 + ")"}, "args": (1,)}))
    assert text.startswith("Cannot resolve annotation 'nonsense(aaa") and "... for parameter x" in text and len(text) < 140


# ── smaller items ─────────────────────────────────────────────────────────────────────────────────

def test_callable_that_describes_itself_wrongly_is_reported():
    class Broken:
        __signature__ = 5                                           # text would be parsed on 3.13: a builtin to inspect

        def __call__(self, x: int) -> int:
            return x

    checked = validate(Broken())
    for _ in range(2):                                              # it was passed through unchecked
        with pytest.raises(InvalidDataError, match = "Cannot read the signature of <Callable Broken>"):
            checked(1)
    assert validate(max)(1, 2) == 2 and validate(len)("ab") == 2    # a builtin without a signature still goes through


def test_plain_subclass_of_a_dataclass_is_called_a_class():
    @dataclass
    class Base:
        x: int

    class Child(Base):
        def describe(self, prefix: str) -> str:
            return prefix

    with pytest.raises(InvalidDataError) as e:
        validate(Child)
    assert "validate cannot check <Class Child>" in _plain(e.value) and "A class is checked by @enforce" in _plain(e.value)
    with pytest.raises(InvalidDataError) as e:
        validate(Base)
    assert "validate cannot check <Dataclass Base>" in _plain(e.value)
    with pytest.raises(InvalidDataError) as e:
        enforce(Child)(1).describe(5)
    assert "<Method Child.describe>" in _plain(e.value)
