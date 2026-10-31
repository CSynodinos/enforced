"""
The decorators without the decorator syntax: ``validate_function`` checks one call of a function
and makes it, ``enforce_class`` enforces a class that is already defined and returns it.

Also here: what a string in a record of ``validate_record`` may name.
"""
from enforced import InvalidDataError, dataclass, enforce_class, enforce, validate, validate_record, validate_function
from typing import Any, Iterator, NamedTuple, Self
import asyncio
import collections
import copy
import dataclasses
import datetime
import decimal
import functools
import gc
import pathlib
import re
import threading
import weakref
import pytest
import enforced._validator._remembered as _remembered


def _plain(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


def _error(fn: Any, *args: Any, **kwargs: Any) -> InvalidDataError:
    with pytest.raises(InvalidDataError) as raised:
        fn(*args, **kwargs)
    return raised.value


# ═════════════════════════════════════════════════════════════════════════════
#  validate_function: check one call, and make it
# ═════════════════════════════════════════════════════════════════════════════

calls: list[tuple] = []


def area(width: float, height: float = 1, *, unit: str = "m") -> float:
    calls.append((width, height, unit))
    return width * height


def test_call_is_checked_converted_and_made():
    calls.clear()
    assert validate_function(area, (3, 4)) == 12.0
    assert validate_function(area, [3], {"height": 2, "unit": "cm"}) == 6.0
    assert validate_function(area, kwargs = {"width": 1.5}) == 1.5
    assert calls == [(3.0, 4.0, "m"), (3.0, 2.0, "cm"), (1.5, 1.0, "m")]
    assert [type(v) for v in calls[0][:2] + calls[2][:2]] == [float] * 4      # converted, the default too
    for _ in range(3):                                              # the same as the decorator, call after call
        assert validate_function(area, (2, 2)) == validate(area)(2, 2) == 4.0


def test_bad_call_raises_and_the_function_does_not_run():
    calls.clear()
    error = _error(validate_function, area, ("3", 4.0), {"unit": 5})
    assert [(p.kind, p.parameter, p.value) for p in error.problems] == [("type", "width", "3"), ("type", "unit", 5)]
    assert "For parameter width of <Function area>: expected type: 'float', got type 'str' (Value: '3')" in _plain(error)
    assert "Missing required argument for <Function area>: width (expecting type float)" in _plain(_error(validate_function, area))
    assert "too many positional arguments" in _plain(_error(validate_function, area, (1.0, 2.0, 3.0)))
    assert "unexpected keyword argument 'depth'" in _plain(_error(validate_function, area, (1.0,), {"depth": 1}))
    assert calls == []


def test_the_function_itself_is_left_as_it_is():
    before = (area.__defaults__, dict(area.__kwdefaults__), dict(vars(area)))
    validate_function(area, (1,))
    assert (area.__defaults__, dict(area.__kwdefaults__), dict(vars(area))) == before
    assert not hasattr(area, "__wrapped__") and area("unchecked", 2) == "uncheckedunchecked"


def test_options_mean_what_they_mean_for_validate():
    def f(n: int, xs: list[int] | None = None, flag: bool = False) -> str:
        return n, xs, flag                                          # type: ignore[return-value]

    assert validate_function(f, ("5", ["1", 2], "yes"), coerce = True) == (5, ["1", 2], True)
    assert validate_function(f, (5, ["a"])) == (5, ["a"], False)                    # items only with deep
    assert _error(validate_function, f, (5, [1, "a"]), deep = True).problems[0].parameter == "xs[1]"
    assert validate_function(f, (5, ("1",)), deep = True, coerce = True) == (5, [1], False)
    assert _error(validate_function, f, (5,), check_return = True).problems[0].kind == "return"

    def g(x: float, kind: int = 0) -> float:
        return x

    assert _error(validate_function, g, (1,), convert = False).problems[0].parameter == "x"
    assert _error(validate_function, g, (1.5, True)).problems[0].parameter == "kind"
    assert _error(validate_function, g, (1.5, Flag.ON), allow_subclass = False).problems[0].parameter == "kind"
    assert validate_function(g, (1.5, Flag.ON)) == 1.5


class Flag(int):
    ON: "Flag"


Flag.ON = Flag(1)


class Account:
    def __init__(self, owner: str, balance: float = 0.0) -> None:
        self.owner, self.balance = owner, balance

    def deposit(self, amount: float, note: str = "") -> Self:
        self.balance += amount
        return self

    def merge(self, other: Self | None = None) -> Self:
        return self

    @classmethod
    def open(cls, owner: str) -> "Account":
        return cls(owner)

    @staticmethod
    def fee(amount: float) -> float:
        return amount


def test_methods_bound_and_unbound():
    account = Account("ana")
    assert validate_function(account.deposit, (5,)) is account and account.balance == 5.0      # bound: no self to pass
    assert validate_function(Account.deposit, (account, 5)) is account and account.balance == 10.0
    assert validate_function(Account.open, ("bo",)).owner == "bo" and validate_function(Account.fee, (1,)) == 1.0
    assert validate_function(account.merge, (account,), check_return = True) is account
    for bad, label in ((lambda: validate_function(account.deposit, ("x",)), "<Method Account.deposit>"),
                       (lambda: validate_function(Account.open, (5,)), "<Method Account.open>"),
                       (lambda: validate_function(account.merge, (5,)), "<Method Account.merge>")):
        assert label in _plain(_error(bad))
    assert "Missing required argument for <Method Account.deposit>: amount" in _plain(_error(validate_function, account.deposit))
    assert not hasattr(Account.deposit, "__wrapped__")              # the class itself is as it was


def test_other_callables_and_kinds_of_function():
    class Scaler:
        def __call__(self, x: int, scale: float = 2) -> float:
            return x * scale

    assert validate_function(Scaler(), (1,)) == 2.0 and type(validate_function(Scaler(), (1,))) is float
    assert _error(validate_function, Scaler(), ("a",)).problems[0].parameter == "x"
    assert validate_function(functools.partial(area, unit = "cm"), (2,)) == 2.0
    assert validate_function(len, ("abc",)) == 3 and validate_function(max, (1, 2)) == 2

    async def fetch(user_id: int) -> int:
        return user_id

    def numbers(start: int) -> Iterator[int]:
        yield start

    assert asyncio.run(validate_function(fetch, (1,))) == 1 and list(validate_function(numbers, (1,))) == [1]
    with pytest.raises(InvalidDataError):
        asyncio.run(validate_function(fetch, ("a",)))
    with pytest.raises(InvalidDataError):
        validate_function(numbers, ("a",))                          # at the call, before any next()

    @validate(coerce = True)
    def decorated(n: int) -> int:
        return n

    assert validate_function(decorated, ("5",), coerce = True) == 5
    assert _error(validate_function, decorated, ("5",)).problems[0].parameter == "n"    # these options come first


def test_local_function_with_quoted_local_names():
    class Inner:
        pass

    def f(x: "Inner", more: "list[Inner] | None" = None) -> Any:
        return x

    inner = Inner()
    assert validate_function(f, (inner,)) is inner
    assert "Cannot resolve" not in _plain(_error(validate_function, f, (5,)))


def test_what_validate_function_refuses():
    text = _plain(_error(validate_function, Account, ("ana",)))
    assert "validate_function cannot check <Class Account>" in text and "checked by enforce_class" in text
    assert "a int object is not callable" in _plain(_error(validate_function, 5))
    #* A string would be taken apart into one argument per character.
    for args in ("ab", b"ab", None, 5, {"a": 1}, iter((1,))):
        text = _plain(_error(validate_function, area, args))
        assert "validate_function: 'args' must be a tuple or a list" in text and type(args).__name__ in text
    for kwargs in ([("a", 1)], "a", 5):
        assert "validate_function: 'kwargs' must be a mapping" in _plain(_error(validate_function, area, (), kwargs))


@pytest.mark.usefixtures("compiled_at_once")
def test_checked_functions_are_remembered_per_function_and_set_of_options(monkeypatch):
    monkeypatch.setattr(_remembered, "CALL_WRAPPERS", {})

    def f(x: int) -> int:
        return x

    validate_function(f, (1,))
    owner, first = vars(f)[_remembered.CALLS]                             # kept on the function itself
    wrapper = next(iter(first.values()))
    validate_function(f, (2,))
    validate_function(f, ("3",), coerce = True)
    assert owner is f and vars(f)[_remembered.CALLS][1] is first and len(first) == 2 and next(iter(first.values())) is wrapper
    assert "__enforced_source__" in vars(wrapper)                 # compiled once, used again: the fast wrapper
    assert _remembered.CALL_WRAPPERS == {}                               # no cache elsewhere holds a function


def test_a_function_given_to_validate_function_goes_when_it_is_dropped(monkeypatch):
    #* Review finding 34: the wrapper was kept in a cache of 512, and a wrapper holds its function.
    #* A function made in a loop and called once stayed until 512 newer ones had come.
    monkeypatch.setattr(_remembered, "CALL_WRAPPERS", {})
    gc.collect()
    made, alive = [], []
    for i in range(50):
        def g(x: int if i % 2 else str) -> None: ...
        made.append(_plain(_error(validate_function, g, (1.5,))))
        alive.append(weakref.ref(g))
        del g
    assert sum("expected type: 'int'" in text for text in made) == 25 and sum("expected type: 'str'" in text for text in made) == 25
    gc.collect()                                                  # function and wrapper hold each other: a cycle
    assert [ref() for ref in alive] == [None] * 50
    assert _remembered.CALL_WRAPPERS == {}


def test_validate_record_keeps_nothing_of_a_function_that_is_dropped():
    size = len(_remembered.RECORD_CACHE)
    gc.collect()
    alive = []
    for i in range(20):
        def g(x: float, y: int = 0) -> None: ...
        for _ in range(2):                                        # the second call finds the checker of the first
            assert validate_record({"object_name": g, "record": {"x": float}, "args": (i,)}) == ((float(i),), {})
        assert len(vars(g)[_remembered.RECORDS][1]) == 1
        alive.append(weakref.ref(g))
        del g
    gc.collect()
    assert [ref() for ref in alive] == [None] * 20
    assert len(_remembered.RECORD_CACHE) == size                      # that cache is for targets given by name


def test_a_function_keeps_a_bounded_number_of_records(monkeypatch):
    monkeypatch.setattr(_remembered, "_OWN_RECORDS_MAX", 3)

    def g(x: Any) -> None: ...

    for annotation in (int, str, bytes, float, list, int):
        validate_record({"object_name": g, "record": {"x": annotation}, "args": (annotation(),)})
    assert len(vars(g)[_remembered.RECORDS][1]) == 3


def test_what_is_remembered_belongs_to_one_function_only():
    #* functools.wraps copies the attributes of the function inside, the remembered wrapper with
    #* them. It is the wrapper of that function, and must not answer for the one around it.
    def inner(x: int) -> str:
        return "inner"

    assert validate_function(inner, (1,)) == "inner"

    @functools.wraps(inner)
    def outer(*args: Any, **kwargs: Any) -> str:
        return "outer"

    assert _remembered.CALLS in vars(outer) and vars(outer)[_remembered.CALLS][0] is inner
    assert validate_function(outer, (1,)) == "outer"
    assert vars(outer)[_remembered.CALLS][0] is outer and vars(inner)[_remembered.CALLS][0] is inner
    assert validate_function(inner, (1,)) == "inner"
    assert "expected type: 'int'" in _plain(_error(validate_function, outer, ("a",)))


def test_an_object_that_is_called_gets_no_attribute(monkeypatch):
    #* Its attributes are its state: copied and pickled with it. The wrapper of a callable object,
    #* a partial or a builtin is remembered apart from it, in a cache that lets the oldest go.
    monkeypatch.setattr(_remembered, "CALL_WRAPPERS", {})
    monkeypatch.setattr(_remembered, "_CALL_WRAPPERS_MAX", 4)

    class Doubler:
        def __call__(self, x: int) -> int:
            return x * 2

    double, part = Doubler(), functools.partial(area, unit = "cm")
    assert validate_function(double, (2,)) == 4 and validate_function(part, (2,)) == 2.0
    assert validate_function(len, ("abc",)) == 3
    assert vars(double) == {} and vars(part) == {}
    assert copy.deepcopy(double)(3) == 6 and len(_remembered.CALL_WRAPPERS) == 3
    for _ in range(20):
        assert validate_function(Doubler(), (1,)) == 2
    assert len(_remembered.CALL_WRAPPERS) <= 4


def test_from_several_threads():
    def f(x: int, y: float = 0) -> float:
        return x + y

    errors: list[BaseException] = []

    def work() -> None:
        try:
            for i in range(300):
                assert validate_function(f, (i, i)) == 2.0 * i
        except BaseException as e:                                  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target = work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
#  enforce_class: enforce a class that is already defined, and get it back
# ═════════════════════════════════════════════════════════════════════════════

def _make() -> type:
    class Service:
        def __init__(self, name: str, retries: float = 3) -> None:
            self.name, self.retries = name, retries

        def run(self, times: int, tags: list[str] | None = None) -> str:
            return times                                            # type: ignore[return-value]

        @classmethod
        def make(cls, name: str) -> Self:
            return cls(name)

        @staticmethod
        def fee(amount: float) -> float:
            return amount

        def __call__(self, x: int) -> int:
            return x

        @enforce.exempt
        def free(self, anything: int) -> Any:
            return anything

        def plain(self, a, b = 1):
            return a
    return Service


def test_enforce_class_returns_the_same_class_enforced():
    Service = _make()
    assert Service(5).name == 5                                     # nothing is checked yet
    assert enforce_class(Service) is Service
    service = Service("a")
    assert type(service.retries) is float and service.run(1) == 1 and Service.make("b").name == "b" and Service.fee(1) == 1.0
    assert service(2) == 2 and service.free("x") == "x" and service.plain("y") == "y"
    for bad, label in ((lambda: Service(5), "<Class Service>"), (lambda: service.run("x"), "<Method Service.run>"),
                       (lambda: Service.make(5), "<Method Service.make>"), (lambda: Service.fee("x"), "<Method Service.fee>"),
                       (lambda: service("x"), "<Method Service.__call__>")):
        assert label in _plain(_error(bad))


def test_enforce_class_does_what_the_decorator_does():
    def outcome(cls: type) -> list:
        results = []
        for call in (lambda: cls("a").retries, lambda: cls(5), lambda: cls("a").run(1), lambda: cls("a").run("x"),
                     lambda: cls("a").run(1, [1]), lambda: cls.make(5), lambda: cls.fee("1"), lambda: cls("a")("x")):
            try:
                results.append(call())
            except InvalidDataError as e:
                results.append(_plain(e))
        return results

    for options in ({}, {"check_return": True}, {"deep": True}, {"coerce": True, "check_return": True}, {"allow_subclass": False},
                    {"convert": False}):
        assert outcome(enforce_class(_make(), **options)) == outcome(enforce(**options)(_make())), options


def test_enforce_class_options_are_keyword_only_and_a_second_call_changes_nothing():
    Service = _make()
    with pytest.raises(TypeError):
        enforce_class(Service, False)                               # type: ignore[misc]
    enforce_class(Service, check_return = True)
    run = vars(Service)["run"]
    assert enforce_class(Service) is Service and vars(Service)["run"] is run       # already checked: left alone
    assert _error(Service("a").run, 1).problems[0].kind == "return"


def test_enforce_class_on_a_class_from_somewhere_else():
    class Point(NamedTuple):
        x: float
        y: float = 0

    assert enforce_class(Point) is Point and Point(1) == (1.0, 0.0) and type(Point(1).y) is float
    assert "<Class Point>" in _plain(_error(Point, "one"))

    class Base:
        def scale(self, by: float) -> float:
            return by

    class Child(Base):
        def shift(self, by: float) -> float:
            return by

    enforce_class(Child)
    assert Child().scale("unchecked") == "unchecked"                # an inherited method belongs to the base class
    assert _error(Child().shift, "x").problems[0].parameter == "by"


def test_enforce_class_with_local_names_in_string_annotations():
    class Inner:
        pass

    class Holder:
        def use(self, inner: "Inner", others: "list[Inner] | None" = None) -> Any:
            return inner

    inner = Inner()
    assert enforce_class(Holder)().use(inner) is inner
    assert "Cannot resolve" not in _plain(_error(Holder().use, 5))


def test_what_enforce_class_refuses():
    text = _plain(_error(enforce_class, area))
    assert "enforce_class cannot check <Function area>" in text and "checked by validate_function" in text
    assert "enforce_class cannot check 5:" in _plain(_error(enforce_class, 5))

    @dataclasses.dataclass
    class Standard:
        x: int

    @dataclass
    class Checked:
        x: int

    for cls in (Standard, Checked):                                 # as @enforce refuses them
        assert "A dataclass is checked by enforced.dataclass" in _plain(_error(enforce_class, cls))


# ═════════════════════════════════════════════════════════════════════════════
#  WHAT A STRING IN A RECORD MAY NAME  (review finding 11)
# ═════════════════════════════════════════════════════════════════════════════

def _check(annotation: str, value: Any, **options: Any) -> Any:
    return validate_record({"object_name": "f", "record": {"x": annotation}, "args": (value,), **options})[0][0]


@pytest.mark.parametrize("annotation, good, bad", [
    ("Optional[int]", None, "x"),
    ("Optional[int]", 5, 1.5),
    ("Union[int, str]", "a", 1.5),
    ("Literal['a', 'b']", "a", "c"),
    ("Literal[1, 2] | None", None, 3),
    ("Sequence[int]", [1], 5),
    ("Mapping[str, int]", {"a": 1}, []),
    ("Iterable[str]", iter("a"), 5),
    ("Callable[[int], str]", len, 5),
    ("List[int]", [1], (1,)),
    ("Dict[str, List[int]]", {"a": [1]}, []),
    ("Tuple[int, ...]", (1,), [1]),
    ("Set[int] | FrozenSet[int]", frozenset(), []),
    ("Type[int]", bool, 5),
    ("deque[int]", collections.deque(), []),
    ("OrderedDict[str, int]", collections.OrderedDict(), {}),
    ("typing.Optional[int]", 1, "x"),
    ("collections.abc.Mapping[str, int]", {"a": 1}, []),
    ("collections.deque", collections.deque(), []),
    ("builtins.int", 1, "x"),
    ("datetime", datetime.datetime(2026, 1, 1), 5),
    ("date | None", datetime.date(2026, 1, 1), "2026-01-01"),
    ("datetime.timedelta", datetime.timedelta(1), 1),
    ("Decimal", decimal.Decimal(1), 1.5),
    ("decimal.Decimal | int", 1, 1.5),
    ("Path", pathlib.Path("."), "."),
    ("pathlib.PurePath", pathlib.PurePath("."), 5),
    ("TextIO", __import__("io").StringIO(), 5),
    ("LiteralString", "a", 5),
    ])
def test_record_string_may_use_typing_names(annotation, good, bad):
    assert _check(annotation, good) is good
    with pytest.raises(InvalidDataError) as e:
        _check(annotation, bad)
    assert "Cannot resolve" not in _plain(e.value)


def test_record_string_with_typing_names_goes_all_the_way_down():
    assert _check("Any", object()) is not None and _check("Any", None) is None
    assert _error(_check, "Sequence[int]", [1, "a"], deep = True).problems[0].parameter == "x[1]"
    assert _error(_check, "Dict[str, Optional[List[int]]]", {"a": None, "b": [1, "x"]}, deep = True).problems[0].parameter == "x['b'][1]"
    assert _check("Optional[float]", 1) == 1.0 and type(_check("Optional[float]", 1)) is float
    assert _check("Decimal", "1.5", coerce = True) == decimal.Decimal("1.5")
    assert _check("date", "2026-01-02", coerce = True) == datetime.date(2026, 1, 2)
    assert "expected type: Literal['a', 'b'], got type 'str'" in _plain(_error(_check, "Literal['a', 'b']", "c"))


@pytest.mark.parametrize("text", [
    "os.system", "typing.cast", "typing.sys", "typing.get_type_hints", "builtins.eval", "builtins.__import__", "eval", "open",
    "Optional.__class__", "collections.abc.Callable.__subclasses__", "datetime.sys", "datetime.datetime.now", "pathlib.os",
    "decimal.getcontext", "typing", "collections", "collections.abc", "datetime.datetime.__subclasses__()", "Literal[print]",
    "Optional[__import__('os')]", "pickle.loads", "Path.home()", "a.b.c.d", "TypeModel", "functools.partial", "(lambda: 1)()",
    "Sequence[exec]", "typing.Optional.__origin__", "__builtins__", "Decimal.__init__", "uuid.uuid4",
    ])
def test_record_string_still_cannot_reach_anything_else(text):
    with pytest.raises(InvalidDataError, match = "Cannot resolve annotation"):
        _check(text, 1)
    with pytest.raises(InvalidDataError, match = "Cannot resolve annotation"):
        _check(text, [1], deep = True)


def test_record_classes_are_imported_only_when_named():
    import subprocess
    import sys

    code = ("import sys, enforced; from enforced import validate_record as t;"
            "before = [m for m in ('uuid', 'pathlib') if m in sys.modules];"
            "t({'object_name': 'f', 'record': {'x': 'UUID | None'}, 'args': (None,)});"
            "print(before, 'uuid' in sys.modules, 'pathlib' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output = True, text = True, cwd = pathlib.Path(__file__).parent.parent)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[] True False"                    # the one that was named, when it was named
