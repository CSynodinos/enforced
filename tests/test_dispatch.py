"""``dispatch`` and ``dispatchmethod``: a function that chooses a version of itself by its first argument (2026-10-23)."""
from abc import ABC
from collections.abc import Iterator, Sequence
from dataclasses import field
from typing import Annotated, Any, Literal, NamedTuple, Protocol, Self, TypedDict, runtime_checkable
import gc
import inspect
import pickle
import threading
import warnings
import weakref

import pytest

import enforced._environment as environment
from enforced import (
    InvalidDataError, InvalidDataWarning, TypeModel, dataclass, dispatch, dispatchmethod, enforce, typecheck,
    )
from enforced.data_types import Email, Port, SecretStr


def positive(n: int) -> bool:
    return n > 0


class Point(NamedTuple):
    x: int
    y: int


class Order(TypedDict):
    id: int
    total: float


@runtime_checkable
class Runs(Protocol):
    def run(self) -> None: ...


class Job:
    def run(self) -> None: ...


type Tree = int | list[Tree]


class Animal: ...
class Dog(Animal): ...


@dispatch
def kind(value) -> str:                                             # the base: takes what no version takes
    return "other"


@kind.register
def _(value: list[int]) -> str: return "list[int]"
@kind.register
def _(value: list[str]) -> str: return "list[str]"
@kind.register
def _(value: dict[str, int]) -> str: return "dict[str, int]"
@kind.register
def _(value: tuple[int, str]) -> str: return "tuple[int, str]"
@kind.register
def _(value: Point) -> str: return "Point"
@kind.register
def _(value: Order) -> str: return "Order"
@kind.register
def _(value: Literal["json", "yaml"]) -> str: return "format"
@kind.register
def _(value: Annotated[int, positive]) -> str: return "positive"
@kind.register
def _(value: int | None) -> str: return "int or None"
@kind.register
def _(value: Email) -> str: return "email"
@kind.register
def _(value: type[Animal]) -> str: return "animal class"
@kind.register
def _(value: Runs) -> str: return "runs"


@pytest.mark.parametrize("value, expected", [
    ([1, 2], "list[int]"), (["a"], "list[str]"), ([], "list[int]"), ([1, "a"], "other"),
    ({"a": 1}, "dict[str, int]"), ({"a": "b"}, "other"), ((1, "a"), "tuple[int, str]"), ((1, 2), "other"),
    (Point(1, 2), "Point"), ({"id": 1, "total": 2.5}, "Order"),
    ("json", "format"), ("xml", "other"), (5, "positive"), (-5, "int or None"), (None, "int or None"),
    (Email("a@b.co"), "email"), ("c@d.co", "email"), (Dog, "animal class"), (int, "other"), (Job(), "runs"),
    (True, "other"), (1.5, "other"),
    ], ids = repr)
def test_each_kind_of_anchor(value, expected):
    for _ in range(3):                                              # the cache, and the wrappers compiled
        assert kind(value) == expected


def test_a_raw_value_is_passed_as_the_model_it_became():
    @dispatch
    def show(v) -> Any:
        return v

    @show.register
    def _(v: Email | Port) -> Any:
        return v
    assert type(show("A@B.co")) is Email and show("A@B.co") == "A@b.co"
    assert type(show(8080)) is Port
    assert show("nope") == "nope" and type(show(0)) is int              # refused by validate: the next candidate
    assert type(show(True)) is bool                                 # a bool never becomes a number model


def test_a_model_inside_a_container_takes_models_only():
    @dispatch
    def emails(v) -> str:
        return "other"

    @emails.register
    def _(v: list[Email]) -> str:
        return "emails"
    assert emails([Email("a@b.co")]) == "emails" and emails(["a@b.co"]) == "other"


def test_items_are_checked_at_every_depth_and_a_recursive_alias():
    @dispatch
    def depth(v) -> str:
        return "other"

    @depth.register
    def _(v: list[list[int]]) -> str:
        return "nested"

    @depth.register
    def _(v: Tree) -> str:
        return "tree"
    assert depth([[1], [2, 3]]) == "nested" and depth([[1], ["a"]]) == "other"
    assert depth([1, [2, [3]]]) == "tree" and depth(4) == "tree"


def test_iterators_are_never_read():
    @dispatch
    def it(v) -> str:
        return "other"

    @it.register
    def _(v: Iterator[int]) -> str:
        return "iterator"
    items = iter(["a", "b"])
    assert it(items) == "iterator" and list(items) == ["a", "b"]


# ── the order, and what isn't converted ─────────────────────────────────────

def test_the_first_candidate_in_the_order_of_registration_wins():
    @dispatch
    def first(v) -> str:
        return "base"

    @first.register
    def _(v: list[int]) -> str:
        return "ints"

    @first.register
    def _(v: list[str]) -> str:
        return "strs"
    assert first([]) == "ints"                                      # an empty list fits both


def test_the_anchor_is_never_converted_nor_coerced():
    @dispatch
    def num(v) -> str:
        return "base"

    @num.register
    def _(v: float) -> str:
        return "float"

    @num.register
    def _(v: int) -> str:
        return "int"
    assert num(1) == "int" and num(1.0) == "float" and num("5") == "base"


def test_bool_is_not_int_and_strict_mode():
    @dispatch(allow_subclass = False)
    def strict(v) -> str:
        return "base"

    @strict.register
    def _(v: Animal) -> str:
        return "animal"

    @strict.register
    def _(v: int) -> str:
        return "int"
    assert strict(Animal()) == "animal" and strict(Dog()) == "base"
    assert strict(1) == "int" and strict(True) == "base"
    assert kind(True) == "other"


def test_the_base_annotated_is_the_last_candidate():
    @dispatch
    def only(v: int) -> str:
        return "base"

    @only.register
    def _(v: str) -> str:
        return "str"
    assert only(1) == "base" and only("a") == "str"
    with pytest.raises(InvalidDataError):
        only(1.5)


def test_an_annotated_check_that_breaks_is_a_bug_and_goes_through():
    def broken(v: int) -> bool:
        raise RuntimeError("bug")

    def refusing(v: int) -> bool:
        raise ValueError("no")

    @dispatch
    def checked(v) -> str:
        return "base"

    @checked.register
    def _(v: Annotated[int, refusing]) -> str:
        return "never"

    @checked.register
    def _(v: Annotated[int, broken]) -> str:
        return "never"
    with pytest.raises(RuntimeError, match = "bug"):
        checked(1)
    assert checked("a") == "base"


# ── the other parameters ────────────────────────────────────────────────────

def test_the_other_parameters_are_checked_with_the_dispatcher_s_options():
    @dispatch(check_return = True)
    def area(shape, scale: float = 1.0) -> float:
        return 0.0

    @area.register
    def _(shape: int, scale: float = 1.0) -> float:
        return shape * scale

    @area.register
    def _(shape: str, scale: float = 1.0) -> float:
        return "wrong"                                              # type: ignore[return-value]
    assert area(2, 3) == 6.0 and type(area(2, 3)) is float          # 3 converted to 3.0 (convert, the default)
    with pytest.raises(InvalidDataError, match = "parameter scale"):
        area(2, "x")
    with pytest.raises(InvalidDataError, match = "return value"):
        area("a")
    assert area([1]) == 0.0


def test_the_anchor_is_checked_once():
    seen: list[int] = []

    def counted(v: int) -> bool:
        seen.append(v)
        return True

    @dispatch
    def once(v, other: int = 0) -> str:
        return "base"

    @once.register
    def _(v: Annotated[int, counted], other: int = 0) -> str:
        return "counted"
    for _ in range(5):
        seen.clear()
        assert once(3, 4) == "counted" and seen == [3]


def test_warn_is_for_the_other_parameters_and_a_value_no_version_takes_raises():
    @dispatch(on_error = "warn")
    def soft(v: int, n: int = 0) -> str:
        return "base"
    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        assert soft(1, "x") == "base"                               # type: ignore[arg-type]
    assert [type(w.message) for w in caught] == [InvalidDataWarning]
    with pytest.raises(InvalidDataError):
        soft("a")


def test_no_conversion_of_other_parameters_with_convert_off():
    @dispatch(convert = False)
    def scaled(v, by: float = 1.0) -> Any:
        return by

    @scaled.register
    def _(v: int, by: float = 1.0) -> Any:
        return by
    with pytest.raises(InvalidDataError, match = "parameter by"):
        scaled(1, 2)


# ── the error ───────────────────────────────────────────────────────────────

@dispatch
def shape(node: int) -> str:
    return "int"


@shape.register
def _(node: list[str]) -> str:
    return "strs"


@shape.register
def _(node: Annotated[str, positive]) -> str:
    return "never"


@shape.register
def _(node: Email) -> str:
    return "email"


def test_the_error_says_why_each_candidate_refused():
    with pytest.raises(InvalidDataError) as info:
        shape(["a", 1, 2])
    assert str(info.value).splitlines() == [
        "4 problems found in dispatch:",
        "    -> Version 1 (list[str]) of <Function shape> refuses node: at node[1]: expected type: 'str', got type "
        "'int'; at node[2]: expected type: 'str', got type 'int' (Value: ['a', 1, 2])",
        "    -> Version 2 (Annotated[str, positive]) of <Function shape> refuses node: expected type: 'str', got type "
        "'list' (Value: ['a', 1, 2])",
        "    -> Version 3 (Email) of <Function shape> refuses node: expected type: 'enforced.data_types.Email', got "
        "type 'list' (Value: ['a', 1, 2])",
        "    -> The base (int) of <Function shape> refuses node: expected type: 'int', got type 'list' "
        "(Value: ['a', 1, 2])",
        ]


def test_a_model_s_reason_is_its_validate_s():
    with pytest.raises(InvalidDataError) as info:
        shape("nope")
    assert "Version 3 (Email) of <Function shape> refuses node: invalid 'Email':" in str(info.value)


def test_errors_one_entry_per_candidate():
    with pytest.raises(InvalidDataError) as info:
        shape(1.5)
    entries = info.value.errors()
    assert [e["loc"] for e in entries] == [["node", 1], ["node", 2], ["node", 3], ["node", 0]]
    assert {e["type"] for e in entries} == {"dispatch"} and entries[0]["input"] == 1.5
    assert entries[0]["ctx"]["anchor"] == "list[str]" and entries[0]["ctx"]["version"] == 1
    assert entries[0]["ctx"]["reasons"] == [{"type": "type", "loc": ["node"], "msg": "expected type: 'list', got type 'float'"}]
    assert entries[0]["msg"] == "expected type: 'list', got type 'float'"
    assert info.value.json(include_input = False) and "input" not in info.value.errors(include_input = False)[0]


def test_a_secret_never_shows():
    @dispatch
    def secret(v: int) -> None: ...
    with pytest.raises(InvalidDataError) as info:
        secret(SecretStr("hunter2"))
    assert "hunter2" not in str(info.value) + info.value.json()


class DispatchFailed(InvalidDataError):
    pass


@dispatch(error = DispatchFailed)
def own(v: int) -> int:
    return v


def test_the_error_class_and_pickling():
    with pytest.raises(DispatchFailed) as info:
        own("a")
    back = pickle.loads(pickle.dumps(info.value))
    assert type(back) is DispatchFailed and str(back) == str(info.value) and back.errors() == info.value.errors()
    with pytest.raises(DispatchFailed):
        own()                                                       # no anchor: the dispatcher's class too


def test_a_call_without_its_anchor():
    with pytest.raises(InvalidDataError, match = "Missing required argument node of <Function shape>"):
        shape()
    with pytest.raises(InvalidDataError, match = "takes node positionally"):
        shape(node = 1)


def test_an_error_is_freed_without_the_collector():
    calls = [lambda: shape(1.5), lambda: shape(["a", 1]), lambda: shape("nope"), lambda: shape()]

    def caught(call: Any, read: bool) -> None:
        try:
            call()
        except InvalidDataError as e:
            if read:
                assert str(e) and e.problems is not None
        else:
            raise AssertionError("no error")
    for call in calls:
        for _ in range(5):
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


# ── registering ─────────────────────────────────────────────────────────────

def test_the_ways_to_register_and_what_they_return():
    @dispatch
    def f(v) -> str:
        return "base"

    def ints(v) -> str:
        return "ints"

    def strs(v: object) -> str:
        return "strs"
    assert f.register(list[int], ints) is ints
    assert f.register(list[str])(strs) is strs                      # the given annotation wins over the function's own
    assert f([1]) == "ints" and f(["a"]) == "strs" and f(1) == "base"
    assert f.registry() == ((list[int], ints), (list[str], strs), (Any, f.__wrapped__))
    assert f.dispatch([1]) is ints and f.dispatch(1) is f.__wrapped__


@pytest.mark.parametrize("source, message", [
    ("def v(x) -> None: ...", "its anchor, x, has no annotation"),
    ("def v(*, x: int) -> None: ...", "x, which is not positional"),
    ("def v(*xs: int) -> None: ...", "xs, which is not positional"),
    ("def v() -> None: ...", "has no parameter"),
    ], ids = ["unannotated", "keyword-only", "*args", "no parameter"])
def test_a_version_without_a_proper_anchor_is_refused(source, message):
    @dispatch
    def f(v) -> None: ...
    space: dict[str, Any] = {}
    exec(source, space)
    with pytest.raises(InvalidDataError, match = message):
        f.register(space["v"])
    assert f.registry() == ((Any, f.__wrapped__),)                  # nothing was added


def test_what_isn_t_a_function_is_refused():
    with pytest.raises(InvalidDataError, match = "decorates a function"):
        dispatch(5)                                                 # type: ignore[call-overload]
    with pytest.raises(InvalidDataError, match = "use dispatchmethod"):
        dispatch(classmethod(lambda cls, v: v))                     # type: ignore[call-overload]

    @dispatch
    def f(v) -> None: ...
    with pytest.raises(InvalidDataError, match = "a version must be a function"):
        f.register(int, print)
    with pytest.raises(InvalidDataError, match = "on_error must be"):
        dispatch(on_error = "loud")                                 # type: ignore[call-overload]
    with pytest.raises(InvalidDataError, match = "error must be a subclass"):
        dispatch(error = ValueError)                                # type: ignore[call-overload]


def test_the_same_function_twice_is_refused():
    @dispatch
    def f(v) -> None: ...

    def g(v: int) -> None: ...
    f.register(g)
    with pytest.raises(InvalidDataError, match = "registered already"):
        f.register(str, g)


def test_a_base_with_an_anchor_that_can_t_be_checked_is_refused_at_once():
    class Plain(Protocol):
        def go(self) -> None: ...
    with pytest.raises(InvalidDataError, match = "runtime_checkable"):
        @dispatch
        def f(v: Plain) -> None: ...


def test_self_and_a_protocol_that_can_t_be_checked_are_refused():
    class Plain(Protocol):
        def go(self) -> None: ...

    @dispatch
    def f(v) -> None: ...
    with pytest.raises(InvalidDataError, match = "Self can't be an anchor"):
        f.register(Self)(_version())
    with pytest.raises(InvalidDataError, match = "runtime_checkable"):
        f.register(Plain)(_version())


def _version() -> Any:
    def v(x) -> None: ...
    return v


def test_a_name_defined_after_the_version_is_read_at_the_first_call():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: "Later") -> str:                                       # noqa: F821
        return "later"

    @f.register
    def _(v: int) -> str:
        return "int"
    globals()["Later"] = type("Later", (), {})
    try:
        assert f(Later()) == "later" and f(1) == "int" and f("a") == "base"     # noqa: F821
    finally:
        del globals()["Later"]


def test_a_name_that_never_comes_is_an_error_at_each_call():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: "Nowhere") -> str:                                     # noqa: F821
        return "x"
    for _ in range(2):
        with pytest.raises(InvalidDataError, match = "cannot resolve the anchor of version 1"):
            f(1)


def test_an_unreachable_version_named_only_later_is_refused_at_the_first_call():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: "Soon") -> str:                                        # noqa: F821
        return "soon"

    @f.register
    def _(v: int) -> str:
        return "int"
    globals()["Soon"] = int
    try:
        with pytest.raises(InvalidDataError, match = "version 2 \\(int\\) can never be chosen"):
            f(1)
    finally:
        del globals()["Soon"]


# ── the cache ───────────────────────────────────────────────────────────────

def test_a_class_anchor_is_answered_from_the_cache():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: int) -> str:
        return "int"
    assert f(1) == "int"
    table = f.__enforced_dispatch__.table
    assert table is not None and id(int) in table[1] and table[1][id(int)][1:] == (0, True)

    @f.register
    def _(v: str) -> str:
        return "str"
    assert f.__enforced_dispatch__.table is None                   # a registration starts a new table
    assert f("a") == "str" and f(1) == "int"


def test_a_generic_or_model_anchor_is_asked_each_time():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: list[int]) -> str:
        return "ints"
    f([1])
    assert f.__enforced_dispatch__.table[1][id(list)][1:] == (0, False)
    assert f(["a"]) == "base"


def test_an_abc_registration_is_seen():
    class Shape(ABC): ...

    class Square: ...

    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: Shape) -> str:
        return "shape"
    assert f(Square()) == "base"
    Shape.register(Square)
    assert f(Square()) == "shape"


def test_the_cache_keeps_no_class_alive():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: int) -> str:
        return "int"
    refs = []
    for i in range(40):
        cls = type(f"Made{i}", (), {})
        assert f(cls()) == "base"
        refs.append(weakref.ref(cls))
    del cls
    for _ in range(3):
        gc.collect()
    assert sum(r() is not None for r in refs) == 0
    assert all(r() is None for r in refs) and len(f.__enforced_dispatch__.table[1]) <= 1


def test_threads_that_register_and_call_at_once():
    @dispatch
    def f(v) -> Any:
        return "base"
    classes = [type(f"T{i}", (), {}) for i in range(30)]
    wrong: list[Any] = []

    def call() -> None:
        for _ in range(300):
            for i, cls in enumerate(classes):
                out = f(cls())
                if out not in ("base", i):
                    wrong.append((i, out))

    def register() -> None:
        for i, cls in enumerate(classes):
            f.register(cls, lambda v, i = i: i)
    workers = [threading.Thread(target = call) for _ in range(4)] + [threading.Thread(target = register)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert wrong == [] and [f(cls()) for cls in classes] == list(range(30))


# ── methods ─────────────────────────────────────────────────────────────────

class Shapes:
    def __init__(self, unit: str) -> None:
        self.unit = unit

    @dispatchmethod
    def area(self, shape) -> str:
        return f"? {self.unit}"

    @area.register
    def _(self, shape: int) -> str:
        return f"{shape * shape} {self.unit}"

    @area.register
    def _(self, shape: list[int]) -> str:
        return f"{sum(shape)} {self.unit}"

    @dispatchmethod
    @classmethod
    def named(cls, x) -> str:
        return f"{cls.__name__} base"

    @named.register
    @classmethod
    def _(cls, x: int) -> str:
        return f"{cls.__name__} int"

    @dispatchmethod
    @staticmethod
    def plain(x) -> str:
        return "base"

    @plain.register
    @staticmethod
    def _(x: str) -> str:
        return "str"


def test_a_method_dispatches_on_the_argument_after_self():
    s = Shapes("m2")
    assert s.area(3) == "9 m2" and s.area([1, 2]) == "3 m2" and s.area("x") == "? m2"
    assert s.named(1) == "Shapes int" and Shapes.named("a") == "Shapes base"
    assert s.plain("a") == "str" and Shapes.plain(1) == "base"
    assert Shapes.area.__name__ == "area" and Shapes.__dict__["area"].dispatch(3).__name__ == "_"
    assert Shapes.area(s, 3) == "9 m2" and Shapes.area(s, "x") == "? m2"     # through the class: the anchor comes second


def test_a_method_s_other_parameters_and_error():
    class Scale:
        @dispatchmethod
        def by(self, v: int, factor: float = 1.0) -> float:
            return v * factor

        @by.register
        def _(self, v: str, factor: float = 1.0) -> float:
            return len(v) * factor
    assert Scale().by("abc", 2) == 6.0
    with pytest.raises(InvalidDataError, match = "parameter factor"):
        Scale().by(1, "x")
    with pytest.raises(InvalidDataError, match = "2 problems found in dispatch"):
        Scale().by(1.5)


def test_enforce_and_dataclass_leave_a_dispatcher_alone():
    @dispatch
    def module_level(v) -> str:
        return "base"

    @enforce
    class Holder:
        handler = staticmethod(module_level)

        @dispatchmethod
        def m(self, v) -> str:
            return "base"

        @m.register
        def _(self, v: int) -> str:
            return "int"

    @dataclass
    class Data:
        n: int = 0

        @dispatchmethod
        def m(self, v) -> str:
            return "base"

        @m.register
        def _(self, v: int) -> str:
            return "int"
    assert Holder().m(1) == "int" and Holder().m("a") == "base" and Data().m(1) == "int"
    assert isinstance(Holder.__dict__["m"], dispatchmethod) and isinstance(Data.__dict__["m"], dispatchmethod)


def test_a_typecheck_wrapper_as_a_version_keeps_its_own_options():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    @typecheck(coerce = True)
    def _(v: int, n: int = 0) -> str:
        return f"int {n}"
    assert f(1, "2") == "int 2"


# ── what it is to the rest of Python ────────────────────────────────────────

def test_signature_name_and_pickling_by_name():
    assert inspect.signature(shape) == inspect.signature(shape.__wrapped__)
    assert shape.__name__ == "shape" and shape.__doc__ is None
    assert pickle.loads(pickle.dumps(shape)) is shape


def test_switched_off_it_still_dispatches_and_refuses_what_can_never_run(monkeypatch):
    monkeypatch.setattr(environment, "TYPECHECK_OFF", True)

    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: int, n: int = 0) -> str:
        return f"int {n!r}"
    assert f(1, "x") == "int 'x'" and f("a") == "base"                # the other parameters go unchecked
    with pytest.raises(InvalidDataError, match = "can never be chosen"):
        @f.register
        def _(v: Literal[1]) -> str:
            return "never"


def test_both_tiers_give_the_same_answers():
    #* conftest compiles at the first call (or never, with ENFORCED_COMPILE_AFTER=64): many calls either way.
    @dispatch
    def f(v, n: int = 0) -> str:
        return "base"

    @f.register
    def _(v: list[int], n: int = 0) -> str:
        return f"ints {n}"
    for _ in range(80):
        assert f([1], 2) == "ints 2" and f(["a"]) == "base"
        with pytest.raises(InvalidDataError):
            f([1], "x")


def test_a_dataclass_field_holding_a_dispatcher():
    @dataclass
    class Config:
        handler: Any = field(default = shape)
    assert Config().handler(1) == "int"


# ── a version is named by what it is (2026-10-24) ───────────────────────────

def _line(fn: Any) -> int:
    return fn.__code__.co_firstlineno


def test_a_version_s_own_errors_name_the_version_and_its_line():
    @dispatch(check_return = True)
    def worker(x) -> Any:
        raise TypeError("none")

    @worker.register
    def _(x: str) -> int:
        return x, str                                               # type: ignore[return-value]
    returns = _

    @worker.register
    def _(x: int, n: int = 0) -> int:
        return x
    takes = _
    with pytest.raises(InvalidDataError) as info:
        worker("s")
    assert str(info.value).splitlines()[1] == (
        f"    -> For return value of <Version 1 (str) of <Function worker>, line {_line(returns)}>: expected type: "
        f"'int', got type 'tuple' (Value: ('s', <class 'str'>))")
    with pytest.raises(InvalidDataError) as info:
        worker(1, "n")
    assert f"For parameter n of <Version 2 (int) of <Function worker>, line {_line(takes)}>" in str(info.value)
    assert info.value.errors()[0]["ctx"]["origin"] == f"Version 2 (int) of <Function worker>, line {_line(takes)}"
    assert str(pickle.loads(pickle.dumps(info.value))) == str(info.value)       # the text travels


def test_a_warning_names_the_version_too():
    @dispatch(on_error = "warn")
    def soft(x) -> str:
        return "base"

    @soft.register
    def _(x: int, n: int = 0) -> str:
        return "int"
    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        soft(1, "x")                                                # type: ignore[arg-type]
    assert "<Version 1 (int) of <Function soft>, line" in str(caught[0].message)


def test_a_method_s_version_is_named_with_its_class():
    class Shapes:
        @dispatchmethod
        def area(self, s) -> float:
            return 0.0

        @area.register
        def _(self, s: int, scale: float = 1.0) -> float:
            return s * scale
    with pytest.raises(InvalidDataError, match = r"For parameter scale of <Version 1 \(int\) of <Method Shapes.area>, line"):
        Shapes().area(1, "x")


def test_another_file_is_named_and_the_last_dispatcher_names_a_shared_version():
    space: dict[str, Any] = {}
    exec(compile("def version(x: int, n: int = 0) -> int:\n    return x\n", "elsewhere.py", "exec"), space)
    version = space["version"]

    @dispatch
    def first(x) -> Any: ...

    @dispatch
    def second(x) -> Any: ...
    first.register(version)
    second.register(version)
    with pytest.raises(InvalidDataError, match = r"<Version 1 \(int\) of <Function second>, elsewhere.py, line 1>"):
        first(1, "x")


def test_the_base_keeps_its_own_name():
    @dispatch
    def plain(x, n: int = 0) -> Any:
        return x
    with pytest.raises(InvalidDataError, match = "For parameter n of <Function plain>:"):
        plain(1, "x")


def test_typecheck_refuses_a_dispatcher():
    @dispatch
    def f(v: int) -> int:
        return v

    class Holder:
        @dispatchmethod
        def m(self, v) -> None: ...
    for target in (f, Holder.__dict__["m"]):
        with pytest.raises(InvalidDataError, match = "typecheck cannot check the dispatcher"):
            typecheck(target)
        with pytest.raises(InvalidDataError, match = "cannot check the dispatcher"):
            typecheck(check_return = True)(target)
