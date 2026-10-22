"""
``error = ...`` on every API (2026-10-22): a library says which exception its callers get. The class
must be a subclass of ``InvalidDataError``; what a checker raises is of that class, what refuses a
decorator itself stays an ``InvalidDataError``.
"""
from typing import Annotated, Any, Protocol
import gc
import json
import pickle
import warnings

import pytest

import enforced._environment as environment
from enforced import (
    Enforced, InvalidDataError, InvalidDataWarning, dataclass, enforce, enforce_class, make_dataclass, typecheck,
    typecheck_function, typecheck_record,
    )
from enforced.data_types import Port


class ShopError(InvalidDataError):
    """A library's own error: an ``__init__`` enforced must never run, and something of its own."""

    library = "shop"                                                # state a subclass needs: on the class

    def __init__(self, order_id: int, reason: str) -> None:         # pragma: no cover  # never called by enforced
        raise AssertionError("enforced ran the subclass's __init__")

    def shop_code(self) -> str:
        return f"{self.library}:{len(self.problems)}"


class OtherError(InvalidDataError):
    pass


@pytest.fixture(params = [1, 10 ** 6], ids = ["compiled", "general path"])
def tier(request, monkeypatch):
    monkeypatch.setattr(environment, "COMPILE_AFTER", request.param)
    return request.param


def _raised(call: Any) -> InvalidDataError:
    try:
        call()
    except InvalidDataError as e:
        return e
    raise AssertionError("nothing was raised")


def _twice(call: Any) -> InvalidDataError:
    """The error of ``call`` on the second try (the first may compile the wrapper)."""
    _raised(call)
    return _raised(call)


# ── every kind of error, from every API ─────────────────────────────────────

class Unreadable(Protocol):                                         # not runtime_checkable: a call-time error
    def go(self) -> None: ...


def _calls() -> "dict[str, Any]":
    """name -> a call that fails, each through a different API or kind of error, all with error = ShopError."""
    @typecheck(error = ShopError, check_return = True)
    def f(a: int, b: Port = Port(80), *, c: Annotated[int, lambda v: v > 0] = 1) -> int:
        return "x" if a == 9 else a                                 # type: ignore[return-value]

    @typecheck(error = ShopError)
    def three(host: str, port: Port, name: str) -> None: ...        # (1, 0): the full path, which looks for a placement

    @typecheck(error = ShopError)
    def bad_default(x: int = "nope") -> None: ...                   # type: ignore[assignment]

    @typecheck(error = ShopError)
    def protocol(p: Unreadable) -> None: ...

    @typecheck(error = ShopError)
    def unresolved(x: "Nowhere") -> None: ...                       # type: ignore[name-defined]  # noqa: F821

    @typecheck(error = ShopError, deep = True)
    def items(xs: list[int]) -> None: ...

    @enforce(error = ShopError)
    class Shelf:
        def put(self, x: int) -> None: ...

        @property
        def size(self) -> int:
            return 1

        @size.setter
        def size(self, value: int) -> None: ...

    class Base(Enforced, error = ShopError):
        def put(self, x: int) -> None: ...

    class Below(Base):
        def take(self, x: int) -> None: ...

    @dataclass(error = ShopError)
    class Order:
        qty: int
        tags: list[str] = dataclasses_field()

    @dataclass(error = ShopError, frozen = True)
    class Frozen:
        qty: int

    @dataclass(error = ShopError, init = False)
    class NoInit:
        qty: int = "many"                                           # type: ignore[assignment]

    Made = make_dataclass("Made", [("qty", int)], error = ShopError)

    class Plain:
        def go(self, x: int) -> None: ...

    enforce_class(Plain, error = ShopError)

    def loose(x: int) -> int:
        return x

    order = Order(1)
    shelf = Shelf()
    return {
        "wrong argument": lambda: f("a"),
        "missing argument": lambda: f(),
        "call that doesn't bind": lambda: f(1, 2, 3),
        "unknown keyword": lambda: f(1, z = 1),
        "wrong return value": lambda: f(9),
        "refused by a model": lambda: f(1, 0),
        "refused by a check": lambda: f(1, c = -1),
        "missing next to a refused value": lambda: f(b = 0),
        "a missing argument next to one that doesn't fit": lambda: three(1, 0),
        "wrong default": lambda: bad_default(),
        "protocol not runtime checkable": lambda: protocol(1),
        "unresolved annotation": lambda: unresolved(1),
        "deep item": lambda: items([1, "a"]),
        "enforce method": lambda: shelf.put("a"),
        "enforce property setter": lambda: setattr(shelf, "size", "big"),
        "Enforced method": lambda: Base().put("a"),
        "Enforced subclass": lambda: Below().take("a"),
        "dataclass construction": lambda: Order("a"),
        "dataclass assignment": lambda: setattr(order, "qty", "a"),
        "dataclass field of another type": lambda: setattr(order, "tags", 5),
        "frozen dataclass construction": lambda: Frozen("a"),
        "dataclass init=False default": lambda: NoInit(),
        "make_dataclass": lambda: Made("a"),
        "enforce_class": lambda: Plain().go("a"),
        "typecheck_function": lambda: typecheck_function(loose, ("a",), error = ShopError),
        "typecheck_record": lambda: typecheck_record({"object_name": "g", "record": {"x": int}, "kwargs": {"x": "a"},
                                                      "error": ShopError}),
        }


def dataclasses_field() -> Any:
    import dataclasses
    return dataclasses.field(default_factory = list)


CALLS = list(_calls())


@pytest.mark.parametrize("name", CALLS)
def test_every_api_and_every_kind_of_error_raises_the_class_given(name, tier):
    call = _calls()[name]
    for error in (_raised(call), _raised(call)):                    # the first call and the one after it
        assert type(error) is ShopError, f"{name}: {type(error).__name__}"
        assert isinstance(error, InvalidDataError) and isinstance(error, TypeError)
        assert error.shop_code().startswith("shop:")               # its own methods and class attributes work
        assert str(error) and error.errors() and json.loads(error.json()) == error.errors()


@pytest.mark.parametrize("name", CALLS)
def test_without_the_option_nothing_changes(name, tier):
    #* The same calls with the default: an InvalidDataError, the same message as with error = ShopError.
    import re
    source = _calls()[name]
    custom = _twice(source)
    assert type(custom) is ShopError
    plain_calls = _plain_calls()
    if name in plain_calls:
        plain = _twice(plain_calls[name])
        assert type(plain) is InvalidDataError
        same = lambda e: re.sub(r"<locals>\.|test_error_type\.|_plain_calls|_calls", "", str(e))
        assert same(plain) == same(custom)


def _plain_calls() -> "dict[str, Any]":
    @typecheck(check_return = True)
    def f(a: int, b: Port = Port(80), *, c: Annotated[int, lambda v: v > 0] = 1) -> int:
        return "x" if a == 9 else a                                 # type: ignore[return-value]

    @dataclass
    class Order:
        qty: int

    return {
        "wrong argument": lambda: f("a"), "missing argument": lambda: f(), "call that doesn't bind": lambda: f(1, 2, 3),
        "wrong return value": lambda: f(9), "refused by a model": lambda: f(1, 0), "refused by a check": lambda: f(1, c = -1),
        "dataclass construction": lambda: Order("a"),
        }


def test_except_invalid_data_error_still_catches_it():
    @typecheck(error = ShopError)
    def f(x: int) -> None: ...

    with pytest.raises(InvalidDataError):
        f("a")
    with pytest.raises(TypeError):
        f("a")


def test_two_functions_with_two_classes():
    @typecheck(error = ShopError)
    def a(x: int) -> None: ...

    @typecheck(error = OtherError)
    def b(x: int) -> None: ...

    @typecheck
    def c(x: int) -> None: ...

    for _ in range(3):
        assert type(_raised(lambda: a("x"))) is ShopError
        assert type(_raised(lambda: b("x"))) is OtherError
        assert type(_raised(lambda: c("x"))) is InvalidDataError


def test_typecheck_function_keeps_one_wrapper_per_class():
    def f(x: int) -> int:
        return x

    for _ in range(3):
        assert type(_raised(lambda: typecheck_function(f, ("a",), error = ShopError))) is ShopError
        assert type(_raised(lambda: typecheck_function(f, ("a",), error = OtherError))) is OtherError
        assert type(_raised(lambda: typecheck_function(f, ("a",)))) is InvalidDataError
    assert typecheck_function(f, (1,), error = ShopError) == 1


def test_typecheck_record_caches_by_class():
    spec = {"object_name": "g", "record": {"x": int}, "kwargs": {"x": "a"}}
    for _ in range(3):
        assert type(_raised(lambda: typecheck_record({**spec, "error": ShopError}))) is ShopError
        assert type(_raised(lambda: typecheck_record(spec))) is InvalidDataError


def test_with_the_option_in_parentheses_and_partial_forms():
    shop = typecheck(error = ShopError)

    @shop
    def f(x: int) -> None: ...

    @enforce(coerce = True, error = ShopError)
    class C:
        def m(self, x: int) -> int:
            return x

    assert type(_raised(lambda: f("a"))) is ShopError
    assert C().m("3") == 3 and type(_raised(lambda: C().m("a"))) is ShopError


def test_a_method_of_an_enforced_class_routed_for_self_keeps_the_class():
    from typing import Self

    @enforce(error = ShopError)
    class Node:
        def link(self, other: Self | None) -> None: ...

    class Child(Node):
        pass

    for _ in range(3):
        assert type(_raised(lambda: Child().link("x"))) is ShopError        # the wrapper made for Child
        assert type(_raised(lambda: Node().link(1))) is ShopError


# ── Enforced: inherited, and replaced ───────────────────────────────────────

def test_enforced_hands_the_class_down_and_a_subclass_may_replace_it():
    class Base(Enforced, error = ShopError):
        def m(self, x: int) -> None: ...

    class Same(Base, coerce = True):
        def n(self, x: int) -> None: ...

    class Other(Base, error = OtherError):
        def o(self, x: int) -> None: ...

    assert Base.__enforced_options__[6] is ShopError and Same.__enforced_options__[6] is ShopError
    assert type(_raised(lambda: Same().n("a"))) is ShopError
    assert type(_raised(lambda: Other().o("a"))) is OtherError
    assert type(_raised(lambda: Other().m("a"))) is ShopError                # what it inherits keeps its own


# ── on_error = "warn" ───────────────────────────────────────────────────────

def test_a_warning_carries_an_error_of_the_class(tier):
    @typecheck(on_error = "warn", error = ShopError, check_return = True)
    def f(x: int) -> int:
        return "y"                                                  # type: ignore[return-value]

    @dataclass(on_error = "warn", error = ShopError)
    class Order:
        qty: int

    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        f("a")
        Order("a")
        setattr(Order(1), "qty", "b")
    assert len(caught) >= 3 and {w.category for w in caught} == {InvalidDataWarning}
    assert {type(w.message.error) for w in caught} == {ShopError}
    with pytest.raises(ShopError):                                  # raised all the same: a missing argument
        f()


# ── what is refused ─────────────────────────────────────────────────────────

class Slotted(InvalidDataError):
    __slots__ = ("extra",)


WRONG = [5, "ShopError", ValueError, TypeError, InvalidDataWarning, InvalidDataError(), ShopError, Slotted]
APIS = {
    "typecheck": lambda e: typecheck(error = e),
    "typecheck on a function": lambda e: typecheck(lambda x: x, error = e),
    "enforce": lambda e: enforce(error = e),
    "enforce_class": lambda e: enforce_class(type("K", (), {}), error = e),
    "dataclass": lambda e: dataclass(error = e),
    "make_dataclass": lambda e: make_dataclass("M", [("x", int)], error = e),
    "Enforced": lambda e: type("K", (Enforced,), {}, error = e),
    "typecheck_function": lambda e: typecheck_function(lambda: None, error = e),
    "typecheck_record": lambda e: typecheck_record({"object_name": "g", "record": {}, "error": e}),
    }


@pytest.mark.parametrize("api", APIS)
@pytest.mark.parametrize("wrong", WRONG, ids = repr)
def test_what_is_no_subclass_of_invalid_data_error_is_refused_where_it_is_written(api, wrong):
    if wrong is ShopError:
        APIS[api](wrong)                                            # the right kind: accepted
        return
    error = _raised(lambda: APIS[api](wrong))
    assert type(error) is InvalidDataError
    assert ("subclass of InvalidDataError" in str(error)) or ("__slots__" in str(error)), str(error)


def test_misuse_of_a_decorator_stays_an_invalid_data_error():
    for misuse in (lambda: typecheck(int, error = ShopError), lambda: typecheck(error = ShopError)(5),
                   lambda: typecheck(on_error = "log", error = ShopError), lambda: enforce(lambda: 0, error = ShopError),
                   lambda: typecheck_record({"object_name": "g", "error": ShopError})):
        assert type(_raised(misuse)) is InvalidDataError


def test_the_default_is_invalid_data_error_itself():
    @typecheck(error = InvalidDataError)
    def f(x: int) -> None: ...

    assert type(_raised(lambda: f("a"))) is InvalidDataError


# ── pickling ────────────────────────────────────────────────────────────────

def test_an_importable_subclass_pickles_as_itself():
    @typecheck(error = ShopError)
    def f(x: int) -> None: ...

    error = _raised(lambda: f("a"))
    back = pickle.loads(pickle.dumps(error))
    assert type(back) is ShopError and str(back) == str(error)
    assert [p.kind for p in back.problems] == ["type"] and back.shop_code() == "shop:1"


def test_a_local_subclass_pickles_as_invalid_data_error():
    class LocalError(InvalidDataError):
        pass

    @typecheck(error = LocalError)
    def f(x: int) -> None: ...

    error = _raised(lambda: f("a"))
    assert type(error) is LocalError
    back = pickle.loads(pickle.dumps(error))
    assert type(back) is InvalidDataError and str(back) == str(error)


# ── nothing is left to the collector ────────────────────────────────────────

def test_an_error_of_the_class_is_freed_without_the_collector():
    @typecheck(error = ShopError, check_return = True)
    def f(a: int, b: Port = Port(80)) -> int:
        return "x" if a == 9 else a                                 # type: ignore[return-value]

    @dataclass(error = ShopError)
    class Order:
        qty: int

    order = Order(1)
    calls = [lambda: f("a"), lambda: f(), lambda: f(1, 2, 3), lambda: f(9), lambda: f(1, 0),
             lambda: Order("a"), lambda: setattr(order, "qty", "a")]

    def caught(call: Any, read: bool) -> None:
        try:
            call()
        except ShopError as e:
            if read:
                assert str(e) and e.problems is not None
        else:
            raise AssertionError("no error")

    for call in calls:
        for _ in range(70):
            caught(call, True)
        for _ in range(3):
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
