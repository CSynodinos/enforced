"""Tests for enforced.dataclass, the type-checked drop-in for dataclasses.dataclass."""
from dataclasses import InitVar, field
from typing import Annotated, Any, ClassVar, Literal
from enforced import dataclass, TypeCheckerError
import dataclasses
import re
import weakref
import pytest


def _plain(e: BaseException) -> str:
    """Strip ANSI colour codes so messages can be matched as text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


# ═════════════════════════════════════════════════════════════════════════════
#  DECORATOR FORMS / STDLIB COMPATIBILITY
# ═════════════════════════════════════════════════════════════════════════════

def test_without_parentheses():
    @dataclass
    class Point:
        x: float
        y: float

    p = Point(1.0, 2.0)
    assert (p.x, p.y) == (1.0, 2.0)


def test_with_empty_parentheses():
    @dataclass()
    class Point:
        x: float

    assert Point(1.0).x == 1.0
    with pytest.raises(TypeCheckerError):
        Point("one")


def test_is_still_a_dataclass():
    @dataclass
    class Point:
        x: float

    assert dataclasses.is_dataclass(Point)
    assert dataclasses.asdict(Point(1.0)) == {"x": 1.0}


def test_repr_and_eq_preserved():
    @dataclass
    class Point:
        x: float
        y: float

    assert Point(1.0, 2.0) == Point(1.0, 2.0)
    assert repr(Point(1.0, 2.0)) == f"{Point.__qualname__}(x=1.0, y=2.0)"


def test_order_option_passed_through():
    @dataclass(order = True)
    class Version:
        major: int
        minor: int

    assert Version(1, 2) < Version(1, 3)


def test_init_metadata_preserved():
    @dataclass
    class Point:
        x: float

    assert Point.__init__.__name__ == "__init__"


# ═════════════════════════════════════════════════════════════════════════════
#  CONSTRUCTION
# ═════════════════════════════════════════════════════════════════════════════

def test_wrong_positional_type():
    @dataclass
    class Point:
        x: float
        y: float

    with pytest.raises(TypeCheckerError):
        Point(1.0, "two")


def test_wrong_keyword_type():
    @dataclass
    class Point:
        x: float
        y: float

    with pytest.raises(TypeCheckerError):
        Point(x = 1.0, y = "two")


def test_multiple_wrong_types_reported_together():
    @dataclass
    class Point:
        x: float
        y: float

    with pytest.raises(TypeCheckerError) as exc:
        Point("one", "two")
    assert "2 problems found in call" in _plain(exc.value)


def test_missing_field_reported():
    @dataclass
    class Point:
        x: float
        y: float

    with pytest.raises(TypeCheckerError) as exc:
        Point(y = 2.0)
    assert "x (expecting type float)" in _plain(exc.value)


def test_unexpected_keyword():
    @dataclass
    class Point:
        x: float

    with pytest.raises(TypeCheckerError):
        Point(x = 1.0, z = 2.0)


def test_optional_field():
    @dataclass
    class User:
        name: str
        email: str | None = None

    User("ana")
    User("ana", "a@b.c")
    with pytest.raises(TypeCheckerError):
        User("ana", 42)


def test_literal_field():
    @dataclass
    class Job:
        mode: Literal["fast", "slow"]

    Job("fast")
    with pytest.raises(TypeCheckerError):
        Job("turbo")


def test_nested_dataclass_field():
    @dataclass
    class Point:
        x: float

    @dataclass
    class Line:
        start: Point
        end: Point

    Line(Point(0.0), Point(1.0))
    with pytest.raises(TypeCheckerError):
        Line(Point(0.0), (1.0,))


def test_self_referential_forward_ref():
    @dataclass
    class Node:
        value: int
        next: "Node | None" = None

    Node(1, Node(2))
    with pytest.raises(TypeCheckerError):
        Node(1, "not a node")


def test_kw_only():
    @dataclass(kw_only = True)
    class Opts:
        retries: int
        verbose: bool = False

    Opts(retries = 3)
    with pytest.raises(TypeCheckerError):
        Opts(3)  # positional not allowed
    with pytest.raises(TypeCheckerError):
        Opts(retries = "3")


def test_strict_mode():
    @dataclass(allow_subclass = False)
    class Counter:
        n: int

    Counter(1)
    with pytest.raises(TypeCheckerError):
        Counter(True)  # bool is a subclass of int


def test_replace_goes_through_checks():
    @dataclass
    class Point:
        x: float

    p = Point(1.0)
    assert dataclasses.replace(p, x = 2.0).x == 2.0
    with pytest.raises(TypeCheckerError):
        dataclasses.replace(p, x = "bad")


# ═════════════════════════════════════════════════════════════════════════════
#  DEFAULTS
# ═════════════════════════════════════════════════════════════════════════════

def test_good_default():
    @dataclass
    class Config:
        port: int = 8080

    assert Config().port == 8080


def test_bad_default_raises():
    @dataclass
    class Config:
        port: int = "8080"

    with pytest.raises(TypeCheckerError) as exc:
        Config()
    assert "definition" in _plain(exc.value)


def test_bad_default_raises_even_when_supplied():
    @dataclass
    class Config:
        port: int = "8080"

    with pytest.raises(TypeCheckerError):
        Config(80)


def test_default_factory_not_flagged():
    @dataclass
    class Bag:
        items: list[str] = field(default_factory = list)
        meta: dict[str, int] = field(default_factory = dict)

    b = Bag()
    assert b.items == [] and b.meta == {}
    assert Bag() .items is not b.items  # still a fresh list per instance


def test_factory_wrong_output_caught_on_assignment():
    @dataclass
    class Bag:
        items: list[str] = field(default_factory = lambda: "not a list")    # type: ignore

    with pytest.raises(TypeCheckerError):
        Bag()


def test_default_factory_supplied_value_checked():
    @dataclass
    class Bag:
        items: list[str] = field(default_factory = list)

    Bag(["a"])
    with pytest.raises(TypeCheckerError):
        Bag("a")


@pytest.mark.parametrize("options", [{"frozen": True}, {"frozen": True, "slots": True}, {"check_assignment": False}], ids = str)
def test_factory_wrong_output_caught_without_the_assignment_check(options):
    """No assignment check sees the factory's output here, so the factory itself is wrapped (once it went unchecked)."""
    @dataclass(**options)
    class Bag:
        items: list = field(default_factory = dict)             # type: ignore[arg-type]

    with pytest.raises(TypeCheckerError) as exc:
        Bag()
    assert "Field Bag.items of <Dataclass Bag>: expected type: 'list', got type 'dict'" in _plain(exc.value)
    assert Bag([1]).items == [1]                                # a supplied value never calls the factory


@pytest.mark.parametrize("options", [{}, {"frozen": True}, {"check_assignment": False}], ids = str)
def test_factory_output_converted(options):
    @dataclass(deep = True, **options)
    class Sample:
        weights: list[float] = field(default_factory = lambda: [1, 2])
        tags: "tuple[str, ...]" = field(default_factory = tuple)

    a, b = Sample(), Sample()
    assert a.weights == [1.0, 2.0] and all(type(w) is float for w in a.weights) and a.tags == ()
    assert a.weights is not b.weights                           # still made fresh for each instance


#* field(init=False, default=...): __init__ never receives this default, and only a slots class assigns it.
_EVERY_KIND = [{}, {"frozen": True}, {"slots": True}, {"frozen": True, "slots": True}, {"check_assignment": False},
               {"check_assignment": False, "slots": True}]


@pytest.mark.parametrize("options", _EVERY_KIND, ids = str)
def test_init_false_bad_default_raises(options):
    @dataclass(**options)
    class Job:
        name: str
        retries: int = field(init = False, default = "three")   # type: ignore[assignment]

    for _ in range(2):                                          # a definition error: on every construction
        with pytest.raises(TypeCheckerError) as exc:
            Job("build")
        assert exc.value.context == "definition"
        assert ("For default value of field retries of <Dataclass Job>: expected type: 'int', got type 'str' "
                "(Value: 'three')") in _plain(exc.value)


@pytest.mark.parametrize("options", _EVERY_KIND, ids = str)
def test_init_false_default_converted(options):
    @dataclass(**options)
    class Order:
        qty: int
        total: float = field(init = False, default = 0)

    for _ in range(2):
        total = Order(3).total
        assert total == 0.0 and type(total) is float            # like `total: float = 0`


def test_init_false_good_default_untouched():
    marker = object()

    @dataclass
    class Holder:
        x: int
        tag: object = field(init = False, default = marker)
        count: int = field(init = False, default = 0)

    assert Holder(1).tag is marker and Holder(1).count == 0
    assert Holder.count == 0


def test_init_false_default_reported_with_the_other_defaults():
    @dataclass
    class Config:
        port: int = "8080"                                      # type: ignore[assignment]
        retries: int = field(init = False, default = "three")   # type: ignore[assignment]
        timeout: float = field(init = False, default = 1)       # fine: converted

    with pytest.raises(TypeCheckerError) as exc:
        Config()
    assert [(p.kind, p.parameter) for p in exc.value.problems] == [("default", "port"), ("default", "retries")]


def test_init_false_default_follows_the_class_options():
    @dataclass(deep = True, coerce = True, frozen = True)
    class Settings:
        name: str
        ports: tuple[int, ...] = field(init = False, default = ("80", 443))    # type: ignore[assignment]

    assert Settings("web").ports == (80, 443)

    @dataclass(deep = True)
    class Tagged:
        tags: tuple[str, ...] = field(init = False, default = ("a", 1))        # type: ignore[assignment]

    with pytest.raises(TypeCheckerError) as exc:
        Tagged()
    assert [p.parameter for p in exc.value.problems] == ["tags[1]"]

    @dataclass(convert = False)
    class Exact:
        total: float = field(init = False, default = 0)

    with pytest.raises(TypeCheckerError):
        Exact()

    @dataclass
    class Checked:
        level: Annotated[int, lambda v: v > 0] = field(init = False, default = 0)

    with pytest.raises(TypeCheckerError) as exc:
        Checked()
    assert exc.value.problems[0].kind == "invalid"


def test_init_false_default_with_a_forward_reference():
    @dataclass
    class Node:
        value: int
        parent: "Node | None" = field(init = False, default = None)

    child = Node(1)
    assert child.parent is None
    child.parent = Node(0)
    with pytest.raises(TypeCheckerError):
        child.parent = "root"


def test_init_false_default_with_a_hand_written_init():
    @dataclass(slots = True)
    class Counter:
        start: int
        total: float = field(init = False, default = 0)         # nothing assigns it here: accepted, as `0` is for a float

        def __init__(self, start: int) -> None:
            self.start = start
            self.total = start

    assert type(Counter(2).total) is float                      # the assignment is converted as usual
    with pytest.raises(TypeCheckerError):
        Counter("2")


def test_init_false_default_is_only_stored_where_instances_read_it():
    @dataclass
    class Order:
        qty: int
        total: float = field(init = False, default = 0)

    Order.total = 7                                             # replaced before the first construction: left alone
    assert Order(1).total == 7
    assert dataclasses.fields(Order)[1].default == 0            # the declaration itself is never rewritten


#* dataclass(init=False): no generated __init__ takes the defaults. They are checked on the first construction.

@pytest.mark.parametrize("options", [{}, {"frozen": True}, {"check_assignment": False}], ids = str)
def test_class_without_generated_init_checks_its_defaults(options):
    @dataclass(init = False, **options)
    class Config:
        host: str = "localhost"
        port: int = "8080"                                      # type: ignore[assignment]

    for _ in range(2):                                          # a definition error: on every construction
        with pytest.raises(TypeCheckerError) as exc:
            Config()
        assert exc.value.context == "definition"
        assert ("For default value of field port of <Dataclass Config>: expected type: 'int', got type 'str' "
                "(Value: '8080')") in _plain(exc.value)


def test_class_without_generated_init_converts_its_defaults():
    @dataclass(init = False)
    class Vector:
        x: float = 0
        y: float = 0

        def __init__(self, *coords: float) -> None:
            if coords:
                self.x, self.y = coords

    own = vars(Vector)["__init__"].__wrapped__
    assert type(Vector().x) is float                            # like `x: float = 0` in any other dataclass
    assert vars(Vector)["__init__"] is own                      # checked once: the class has its own __init__ back
    assert Vector(1, 2).y == 2.0 and type(Vector().y) is float
    with pytest.raises(TypeCheckerError):
        Vector("1", 2)                                          # the assignments are checked as before


def test_class_without_any_init_gets_its_inherited_one_back():
    @dataclass(init = False)
    class Flags:
        debug: bool = False
        level: float = 1

    assert "__init__" in vars(Flags)
    assert type(Flags().level) is float
    assert "__init__" not in vars(Flags) and Flags.__init__ is object.__init__


def test_class_without_generated_init_is_left_alone_when_nothing_reads_a_default():
    @dataclass(init = False)
    class NoDefaults:
        x: int

        def __init__(self, x: int) -> None:
            self.x = x

    @dataclass(init = False, slots = True)
    class Slotted:
        x: int = "never assigned"                               # type: ignore[assignment]

    assert NoDefaults.__init__.__qualname__.endswith("NoDefaults.__init__") and not hasattr(NoDefaults.__init__, "__wrapped__")
    assert NoDefaults(1).x == 1
    assert Slotted.__init__ is object.__init__                  # with slots the default is on no instance and no class
    assert not hasattr(Slotted(), "x")


def test_class_without_generated_init_and_inheritance():
    @dataclass
    class Base:
        a: int = 1

    @dataclass(init = False)
    class Child(Base):                                          # constructed through Base's checked __init__
        b: float = 0

    child = Child(2)
    assert (child.a, child.b) == (2, 0.0) and type(child.b) is float
    with pytest.raises(TypeCheckerError):
        Child("2")

    @dataclass(init = False)
    class Plain:
        x: float = 0

        def __init__(self) -> None:
            self.ready = True

    class Sub(Plain):                                           # not decorated: its own __init__ calls the checked one
        def __init__(self) -> None:
            super().__init__()
            self.more = True

    sub = Sub()
    assert (type(sub.x), sub.ready, sub.more) == (float, True, True)
    assert type(Plain().x) is float


# ═════════════════════════════════════════════════════════════════════════════
#  ASSIGNMENT
# ═════════════════════════════════════════════════════════════════════════════

def test_assignment_valid():
    @dataclass
    class Point:
        x: float

    p = Point(1.0)
    p.x = 5.0
    assert p.x == 5.0


def test_assignment_invalid():
    @dataclass
    class Point:
        x: float

    p = Point(1.0)
    with pytest.raises(TypeCheckerError) as exc:
        p.x = "oops"
    assert "Point.x" in _plain(exc.value)
    assert p.x == 1.0  # value unchanged after a failed assignment


def test_assignment_to_non_field_unchecked():
    @dataclass
    class Point:
        x: float

    p = Point(1.0)
    p.anything = "fine"  # not a declared field     # type: ignore
    assert p.anything == "fine"     # type: ignore


def test_check_assignment_disabled():
    @dataclass(check_assignment = False)
    class Point:
        x: float

    p = Point(1.0)
    p.x = "allowed"
    assert p.x == "allowed"
    with pytest.raises(TypeCheckerError):
        Point("construction is still checked")


def test_frozen_construction_checked():
    @dataclass(frozen = True)
    class Point:
        x: float

    Point(1.0)
    with pytest.raises(TypeCheckerError):
        Point("one")


def test_frozen_assignment_still_frozen():
    @dataclass(frozen = True)
    class Point:
        x: float

    p = Point(1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.x = 2.0


def test_slots():
    @dataclass(slots = True)
    class Point:
        x: float

    p = Point(1.0)
    assert not hasattr(p, "__dict__")
    with pytest.raises(TypeCheckerError):
        Point("one")
    with pytest.raises(TypeCheckerError):
        p.x = "oops"


def test_frozen_slots():
    @dataclass(frozen = True, slots = True)
    class Point:
        x: float

    Point(1.0)
    with pytest.raises(TypeCheckerError):
        Point("one")


# ═════════════════════════════════════════════════════════════════════════════
#  ONE CHECK PER VALUE
# ═════════════════════════════════════════════════════════════════════════════
#* __init__ validates its arguments and then assigns them, which __setattr__ validates too. A check
#* that calls a function (Annotated, the items of a collection) isn't run a second time.

def _recorder() -> tuple[list[Any], Any]:
    """A check that accepts everything and records each value it is asked about."""
    seen: list[Any] = []

    def record(value: Any) -> bool:
        seen.append(value)
        return True
    return seen, record


@pytest.mark.usefixtures("compiled_at_once")
def test_construction_validates_each_field_once():
    seen, record = _recorder()

    @dataclass
    class Point:
        x: Annotated[int, record]
        y: Annotated[int, record] = 0
        z: Annotated[int, record] = field(default = 0, kw_only = True)

    Point(1)
    assert sorted(seen) == [0, 0, 1]                            # the first use also checks the two defaults, once
    for build in (lambda: Point(1), lambda: Point(1, 2), lambda: Point(x = 1, y = 2), lambda: Point(1, z = 3),
                  lambda: Point(1, 2, z = 3)):
        seen.clear()
        point = build()
        supplied = [v for v in (point.x, point.y, point.z) if v != 0]
        assert sorted(seen) == sorted(supplied), "each supplied argument is checked exactly once"


@pytest.mark.usefixtures("compiled_at_once")
def test_deep_field_is_scanned_once():
    """The costly case: a collection field was once scanned item by item twice per construction."""
    seen, record = _recorder()

    @dataclass(deep = True)
    class Batch:
        rows: list[Annotated[int, record]]
        extra: list[Annotated[int, record]] = field(default_factory = list)

    batch = Batch([1, 2, 3])
    assert seen == [1, 2, 3] and batch.extra == []


@pytest.mark.usefixtures("compiled_at_once")
def test_only_the_validated_object_skips_the_second_check():
    """Every other assignment runs the check: a factory's output, what __post_init__ stores, later writes."""
    seen, record = _recorder()

    @dataclass
    class Account:
        owner: Annotated[str, record]
        balance: Annotated[int, lambda v: v >= 0] = 0
        history: Annotated[list, record] = field(default_factory = lambda: ["opened"])

        def __post_init__(self) -> None:
            self.owner = self.owner.strip()                     # a new value: checked
            if self.balance == 13:
                self.balance = -1                               # rejected, although balance was supplied

    account = Account(" ana ")
    assert seen == [" ana ", ["opened"], "ana"]                 # argument, factory output, __post_init__ value
    seen.clear()
    account.owner = "bea"
    assert seen == ["bea"]
    with pytest.raises(TypeCheckerError):
        account.balance = -5
    with pytest.raises(TypeCheckerError):
        Account("ana", 13)
    with pytest.raises(TypeCheckerError):
        Account("ana", history = "not a list")


def test_converted_argument_is_stored_converted():
    """A converted argument is a new object: it is stored converted (and simply checked again)."""
    @dataclass(deep = True)
    class Series:
        values: list[float]
        scale: Annotated[float, lambda v: v > 0] = 1

    series = Series([1, 2], 3)
    assert series.values == [1.0, 2.0] and all(type(v) is float for v in series.values)
    assert type(series.scale) is float and type(Series([1.5]).scale) is float


def test_subclass_fields_are_checked_against_their_own_annotations():
    """An inherited __setattr__ skips nothing for a subclass, whose __init__ checked other annotations."""
    @dataclass(deep = True)
    class Base:
        items: list[int]

    @dataclass(deep = True)
    class Child(Base):
        names: list[str] = field(default_factory = list)

    child = Child([1, 2], ["a"])
    assert (child.items, child.names) == ([1, 2], ["a"])
    with pytest.raises(TypeCheckerError):
        Child(["x"])
    with pytest.raises(TypeCheckerError):
        Child([1], [2])
    with pytest.raises(TypeCheckerError):
        child.items = ["x"]


@pytest.mark.usefixtures("compiled_at_once")
def test_only_a_class_that_keeps_the_standard_init_publishes_its_arguments():
    """
    A checked dataclass has an __init__ of its own that stores what was checked, past the assignment
    check: nothing is published, because nothing is checked a second time. Only where the standard
    __init__ has to stay (a __setattr__ written by hand must see the assignments) do the fields
    whose check is a function call still learn which values need no second run.
    """
    @dataclass
    class Plain:
        x: int
        y: float = 0.0

    @dataclass
    class Checked:
        x: Annotated[int, lambda v: v > 0]

    class Watched:
        def __setattr__(self, name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

    @dataclass
    class Kept(Watched):
        x: Annotated[int, lambda v: v > 0]

    Plain(1), Checked(1), Kept(1)
    assert "_pv_g" not in Plain.__init__.__enforced_source__ and "_pv_g" not in Checked.__init__.__enforced_source__
    assert "_pv_g['_pv_args'] = _pv_a" in Kept.__init__.__enforced_source__


# ── an __init__ that checks each field once (the roadmap item) ────────────────────────────────────

def _assignments(cls: type) -> list:
    """Replace the check of ``cls`` by one that also records what reaches it: [(name, value)]."""
    seen: list = []
    checking = cls.__setattr__

    def recording(self: Any, name: str, value: Any) -> None:
        seen.append((name, value))
        checking(self, name, value)

    type.__setattr__(cls, "__setattr__", recording)
    return seen


@pytest.mark.usefixtures("compiled_at_once")
def test_an_argument_is_checked_once_and_stored_past_the_assignment_check():
    @dataclass
    class Order:
        qty: int
        price: float = 0
        tags: list = field(default_factory = list)
        note: str = field(default = "", kw_only = True)
        total: float = field(init = False, default = 0.0)
        made: list = field(init = False, default_factory = list)

        def __post_init__(self) -> None:
            self.total = self.qty * self.price

    Order(1)
    seen = _assignments(Order)
    order = Order(2, 3, note = "n")
    #* The arguments never reach the check a second time. What nobody has checked does: the
    #* results of the two factories, and what __post_init__ assigns.
    assert [name for name, _ in seen] == ["tags", "made", "total"]
    assert (order.qty, order.price, order.tags, order.note, order.total, order.made) == (2, 3.0, [], "n", 6.0, [])
    assert type(order.price) is float                               # converted by the wrapper, stored as converted
    seen.clear()
    given = ["a"]
    assert Order(1, 1.0, given).tags is given and [name for name, _ in seen] == ["made", "total"]
    seen.clear()
    order.qty = 5                                                   # an assignment is checked as ever
    assert seen == [("qty", 5)]
    for bad in (lambda: Order("2"), lambda: Order(2, "x"), lambda: Order(2, note = 5), lambda: setattr(order, "qty", "x")):
        with pytest.raises(TypeCheckerError):
            bad()
    with pytest.raises(TypeCheckerError, match = "total"):
        order.total = "x"


def _init_called(cls: Any) -> Any:
    """The ``__init__`` that the checked wrapper of ``cls`` calls: the storing one once the wrapper is compiled."""
    return cls.__init__.__globals__["_pv_checker"].call


def test_the_init_is_the_one_the_standard_library_would_have_made():
    import dataclasses as std
    import inspect

    def build(decorate: Any) -> type:
        class Shape:
            x: int
            y: float = 1.0
            scale: InitVar[int] = 1
            tags: list = field(default_factory = list)
            area: float = field(init = False, default = 0.0)
            label: str = field(default = "s", kw_only = True)

            def __post_init__(self, scale: int) -> None:
                self.area = self.x * self.y * scale
        return decorate(Shape)

    ours, theirs = build(dataclass), build(std.dataclass)
    assert str(inspect.signature(ours)) == str(inspect.signature(theirs))
    for args, kwargs in (((2,), {}), ((2, 3.0), {}), ((2, 3.0, 4), {}), ((2, 3.0, 4, [1]), {"label": "l"}), ((), {"x": 1, "scale": 2})):
        a, b = ours(*args, **kwargs), theirs(*args, **kwargs)
        assert std.asdict(a) == std.asdict(b) and "scale" not in vars(a)        # an InitVar is passed on, not stored
    assert ours(1).tags is not ours(1).tags
    assert _init_called(ours).__globals__ is build.__globals__             # it lives in the module of the class
    assert _init_called(ours).__qualname__.endswith("Shape.__init__")


def test_a_subclass_with_its_own_setattr_still_sees_every_assignment():
    @dataclass
    class Base:
        x: int
        y: float = 0.0

    stored = []

    class Logged(Base):                                             # not decorated: it inherits __init__
        def __setattr__(self, name: str, value: Any) -> None:
            stored.append(name)
            super().__setattr__(name, value)

    Base(1)
    one = Logged(1, 2)
    assert stored == ["x", "y"] and (one.x, one.y) == (1, 2.0)
    with pytest.raises(TypeCheckerError):
        Logged("a")


@pytest.mark.parametrize("options", [{"slots": True}, {"kw_only": True}, {"deep": True}, {"coerce": True}, {"eq": False, "order": False}],
                         ids = str)
@pytest.mark.usefixtures("compiled_at_once")
def test_the_storing_init_under_the_dataclass_options(options):
    @dataclass(**options)
    class Point:
        x: int
        y: float = 0
        items: list[int] = field(default_factory = list)

    make = (lambda *a, **k: Point(**dict(zip(("x", "y", "items"), a)), **k))
    point = make(1, 2)
    assert (point.x, point.y, point.items) == (1, 2.0, []) and type(point.y) is float
    point.y = 3
    assert type(point.y) is float
    for bad in (lambda: make("a") if not options.get("coerce") else make([]), lambda: setattr(point, "x", [])):
        with pytest.raises(TypeCheckerError):
            bad()
    if options.get("deep"):
        with pytest.raises(TypeCheckerError):
            make(1, 2, ["a"])
        with pytest.raises(TypeCheckerError):
            point.items = ["a"]
    assert "_pv_set" in _init_called(Point).__code__.co_freevars           # each has the storing __init__


def test_where_the_standard_init_is_kept():
    class Watched:
        def __setattr__(self, name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

    @dataclass
    class ByHand(Watched):
        x: int

    @dataclass(slots = True)
    class SlotDefault:
        x: int
        kept: float = field(init = False, default = 0)

    @dataclass(frozen = True)
    class Frozen:                                                   # no assignment check: nothing was checked twice
        x: int

    for cls in (ByHand, SlotDefault, Frozen):
        assert cls(1).x == 1
        assert "_pv_set" not in getattr(_init_called(cls).__code__, "co_freevars", ())
        with pytest.raises(TypeCheckerError):
            cls("a")
    assert type(SlotDefault(1).kept) is float                       # the converted default, from the standard __init__


def test_published_arguments_are_cleared_after_construction():
    """A big argument isn't kept alive by the class once __init__ has returned."""
    class Payload(list):
        pass

    @dataclass(deep = True)
    class Holder:
        rows: list[int]

    for _ in range(3):                                          # the first-call path, then the generated one
        payload = Payload([1, 2])
        alive = weakref.ref(payload)
        holder = Holder(payload)
        del payload, holder
        assert alive() is None


# ═════════════════════════════════════════════════════════════════════════════
#  SPECIAL FIELDS
# ═════════════════════════════════════════════════════════════════════════════

def test_classvar_not_a_field():
    @dataclass
    class Point:
        x: float
        registry: ClassVar[int] = 0

    Point(1.0)
    Point.registry = "not checked"  # class attribute, not an instance field


def test_initvar_checked():
    @dataclass
    class Scaled:
        x: int
        factor: InitVar[int] = 1

        def __post_init__(self, factor: int) -> None:
            self.x *= factor

    assert Scaled(2, 3).x == 6
    with pytest.raises(TypeCheckerError):
        Scaled(2, "3")


def test_post_init_assignment_checked():
    @dataclass
    class Labelled:
        x: int
        label: str = ""

        def __post_init__(self) -> None:
            self.label = 5  # wrong type set during post-init

    with pytest.raises(TypeCheckerError):
        Labelled(1)


def test_init_false_field_checked_on_assignment():
    @dataclass
    class Order:
        price: float
        qty: int
        total: float = field(init = False)

        def __post_init__(self) -> None:
            self.total = self.price * self.qty

    assert Order(2.0, 3).total == 6.0
    with pytest.raises(TypeCheckerError):
        Order(2.0, "3")


# ═════════════════════════════════════════════════════════════════════════════
#  INHERITANCE
# ═════════════════════════════════════════════════════════════════════════════

def test_inherited_fields_checked():
    @dataclass
    class Base:
        x: int

    @dataclass
    class Child(Base):
        y: str

    Child(1, "a")
    with pytest.raises(TypeCheckerError):
        Child("1", "a")  # inherited field
    with pytest.raises(TypeCheckerError):
        Child(1, 2)      # own field


def test_inherited_assignment_checked():
    @dataclass
    class Base:
        x: int

    @dataclass
    class Child(Base):
        y: str

    c = Child(1, "a")
    with pytest.raises(TypeCheckerError):
        c.x = "1"
    with pytest.raises(TypeCheckerError):
        c.y = 2


def test_inherited_init_false_default_checked():
    @dataclass
    class Base:
        x: int
        total: float = field(init = False, default = 0)

    @dataclass
    class Child(Base):
        y: int = 2

    @dataclass(slots = True)
    class Slotted(Base):
        pass

    class Plain(Base):                                          # not decorated: uses Base's __init__
        pass

    for cls in (Child, Slotted, Plain, Base):
        assert type(cls(1).total) is float

    @dataclass(convert = False)
    class Exact(Base):
        pass

    with pytest.raises(TypeCheckerError):                       # each class checks with its own options
        Exact(1)


# ═════════════════════════════════════════════════════════════════════════════
#  INHERITANCE BETWEEN CHECKED DATACLASSES: ONE CHECK, THE CLASS'S OWN
# ═════════════════════════════════════════════════════════════════════════════
#* The fields of a decorated subclass include the inherited ones, so its check covers the whole
#* instance with its own options. The check of a decorated base class must not run as well.

class _MyInt(int):
    pass


def _installed_setattr(cls: type) -> Any:
    return vars(cls)["__setattr__"]


@pytest.mark.usefixtures("compiled_at_once")
def test_subclass_checks_each_value_once():
    seen, record = _recorder()

    @dataclass(deep = True)
    class Base:
        rows: list[Annotated[int, record]]

    @dataclass(deep = True)
    class Child(Base):
        name: str = "c"

    @dataclass(deep = True)
    class GrandChild(Child):
        tags: list[Annotated[int, record]] = field(default_factory = lambda: [9])

    for cls, built, assigned in ((Base, [1, 2], [3]), (Child, [1, 2], [3]), (GrandChild, [1, 2, 9], [3])):
        cls([0])                                                # the first use also checks the defaults
        seen.clear()
        instance = cls([1, 2])
        assert seen == built, f"{cls.__name__}: each item is checked once on construction"
        seen.clear()
        instance.rows = [3]
        assert seen == assigned, f"{cls.__name__}: each item is checked once on assignment"


def test_subclass_check_wraps_what_the_base_check_wraps():
    """However deep the hierarchy, an assignment passes through one generated __setattr__."""
    @dataclass
    class A:
        x: int = 0

    @dataclass
    class B(A):
        y: int = 0

    @dataclass
    class C(B):
        z: int = 0

    for cls in (A, B, C):
        instance = cls()
        for _ in range(2):                                      # the bootstrap, then the generated function
            assert _installed_setattr(cls).__enforced_wraps__ is object.__setattr__
            instance.x = 1
        with pytest.raises(TypeCheckerError):
            instance.x = "1"


def test_subclass_can_loosen_its_base():
    @dataclass(allow_subclass = False)
    class Strict:
        x: int

    @dataclass
    class Loose(Strict):
        y: int = 0

    assert Loose(_MyInt(1)).x == 1                              # construction
    loose = Loose(1)
    loose.x = _MyInt(2)                                         # assignment to the inherited field
    assert type(loose.x) is _MyInt
    with pytest.raises(TypeCheckerError):                       # the base class itself is as strict as before
        Strict(_MyInt(1))
    strict = Strict(1)
    with pytest.raises(TypeCheckerError):
        strict.x = _MyInt(2)


def test_subclass_can_tighten_its_base():
    @dataclass
    class Loose:
        x: int

    @dataclass(allow_subclass = False)
    class Strict(Loose):
        y: int = 0

    with pytest.raises(TypeCheckerError):
        Strict(_MyInt(1))
    strict = Strict(1)
    with pytest.raises(TypeCheckerError):
        strict.x = _MyInt(2)
    loose = Loose(_MyInt(1))
    loose.x = _MyInt(2)


def test_subclass_conversion_options_apply_to_inherited_fields():
    @dataclass
    class Exact:
        n: int
        ratio: float = 0.5

    @dataclass(coerce = True)
    class Parsed(Exact):
        pass

    @dataclass(convert = False)
    class Unconverted(Exact):
        pass

    parsed = Parsed("3")
    parsed.n = "4"
    assert (parsed.n, type(parsed.n)) == (4, int)
    unconverted = Unconverted(1)
    with pytest.raises(TypeCheckerError):
        unconverted.ratio = 1                                   # no int -> float here
    exact = Exact(1)
    exact.ratio = 1
    assert type(exact.ratio) is float
    with pytest.raises(TypeCheckerError):
        exact.n = "4"

    @dataclass(deep = True)
    class Deep:
        rows: list[int]

    @dataclass
    class Shallow(Deep):
        pass

    shallow = Shallow(["a"])                                    # only the outer type is checked here
    shallow.rows = ["b"]
    with pytest.raises(TypeCheckerError):
        Deep(["a"])


def test_subclass_errors_name_the_subclass():
    @dataclass
    class Base:
        x: int

    @dataclass
    class Child(Base):
        y: int = 0

    child = Child(1)
    with pytest.raises(TypeCheckerError) as exc:
        child.x = "1"
    assert "Field Child.x of <Dataclass Child>: expected type: 'int', got type 'str'" in _plain(exc.value)
    assert exc.value.problems[0].origin is Child
    with pytest.raises(TypeCheckerError) as exc:
        Base(1).x = "1"
    assert "Field Base.x of <Dataclass Base>" in _plain(exc.value)


def test_subclass_without_the_assignment_check():
    @dataclass
    class Base:
        x: int

    @dataclass(check_assignment = False)
    class Child(Base):
        y: int = 0

    child = Child(1)
    child.x = "inherited"                                       # neither field is checked on assignment
    child.y = "own"
    assert (child.x, child.y) == ("inherited", "own")
    assert Child.__setattr__ is object.__setattr__              # nothing between the assignment and the object
    with pytest.raises(TypeCheckerError):                       # construction still is
        Child("1")
    with pytest.raises(TypeCheckerError):
        Child(1, "2")
    base = Base(1)
    with pytest.raises(TypeCheckerError):                       # and so is the base class
        base.x = "1"

    @dataclass
    class Again(Child):                                         # checked again one level down
        z: int = 0

    again = Again(1)
    for name in ("x", "y", "z"):
        with pytest.raises(TypeCheckerError):
            setattr(again, name, "text")


def test_subclass_can_redeclare_a_field_with_another_type():
    @dataclass
    class Base:
        x: int = 0
        label: str = ""

    @dataclass
    class Child(Base):
        x: str = "a"                                            # type: ignore[assignment]

    assert Child().x == "a"                                     # the base check would reject its own subclass here
    child = Child("b", "l")
    child.x = "c"
    with pytest.raises(TypeCheckerError) as exc:
        child.x = 5                                             # type: ignore[assignment]
    assert "Field Child.x of <Dataclass Child>: expected type: 'str', got type 'int'" in _plain(exc.value)
    with pytest.raises(TypeCheckerError):
        Child(5)                                                # type: ignore[arg-type]
    base = Base(1)
    with pytest.raises(TypeCheckerError):
        base.x = "c"                                            # type: ignore[assignment]


def test_undecorated_subclass_keeps_the_check_of_its_base():
    @dataclass(allow_subclass = False)
    class Base:
        x: int

    class Plain(Base):
        pass

    plain = Plain(1)
    with pytest.raises(TypeCheckerError):
        plain.x = "1"
    with pytest.raises(TypeCheckerError):
        plain.x = _MyInt(1)
    plain.other = "not a field"


def test_stdlib_subclass_keeps_the_check_of_its_base():
    @dataclass
    class Base:
        x: int

    @dataclasses.dataclass
    class Child(Base):
        y: int = 0

    child = Child(1, "unchecked")                               # type: ignore[arg-type]
    with pytest.raises(TypeCheckerError):
        child.x = "1"                                           # type: ignore[assignment]
    with pytest.raises(TypeCheckerError):
        Child("1")                                              # type: ignore[arg-type]


@pytest.mark.usefixtures("compiled_at_once")
def test_subclass_of_two_checked_dataclasses():
    seen, record = _recorder()

    @dataclass
    class Named:
        name: Annotated[str, record]

    @dataclass
    class Sized:
        size: Annotated[int, record] = 0

    @dataclass
    class Box(Sized, Named):                                    # fields: name, size, full
        full: bool = False

    Box(name = "a")
    seen.clear()
    box = Box(name = "a", size = 2)
    assert sorted(seen, key = str) == [2, "a"]
    seen.clear()
    box.size = 3
    box.name = "b"
    assert seen == [3, "b"]
    for name, value in (("size", "3"), ("name", 4), ("full", "yes")):
        with pytest.raises(TypeCheckerError):
            setattr(box, name, value)


@pytest.mark.parametrize("options", [{"slots": True}, {"kw_only": True}, {"eq": False}, {"init": False}], ids = str)
def test_subclass_built_with_other_dataclass_options(options):
    @dataclass(allow_subclass = False)
    class Base:
        x: int = 0

    @dataclass(**options)
    class Child(Base):
        y: int = 0

    child = Child()
    child.x = _MyInt(1)                                         # the base is strict, the subclass isn't
    child.y = 2
    with pytest.raises(TypeCheckerError):
        child.x = "1"
    with pytest.raises(TypeCheckerError):
        child.y = "2"


# ── a hand-written __setattr__ in the hierarchy ──────────────────────────────

def test_own_setattr_runs_once_after_the_check():
    calls: list[tuple[str, Any]] = []

    @dataclass
    class Tracked:
        x: float = 0.0

        def __setattr__(self, name: str, value: Any) -> None:
            calls.append((name, value))
            super().__setattr__(name, value)

    @dataclass
    class Child(Tracked):
        y: int = 0

    for cls in (Tracked, Child):
        instance = cls()
        calls.clear()
        instance.x = 1
        assert calls == [("x", 1.0)]                            # once, with the converted value
        with pytest.raises(TypeCheckerError):
            instance.x = "1"
        assert calls == [("x", 1.0)]                            # a rejected value never reaches it


@pytest.mark.usefixtures("compiled_at_once")
@pytest.mark.parametrize("base_used_first", [False, True], ids = ["base not used yet", "base already used"])
def test_subclass_with_its_own_setattr_that_calls_super(base_used_first):
    """super().__setattr__ leads to the base class's check, which must leave the subclass's instances alone."""
    seen, record = _recorder()

    @dataclass(allow_subclass = False)
    class Base:
        x: int = 0
        tag: Annotated[str, record] = ""

    if base_used_first:                                         # its __setattr__ has been generated already
        Base().x = 1

    calls: list[str] = []

    @dataclass
    class Child(Base):
        x: str = "a"                                            # type: ignore[assignment]

        def __setattr__(self, name: str, value: Any) -> None:
            calls.append(name)
            super().__setattr__(name, value)

    child = Child("b")                                          # the base alone would want an int
    child.x = "c"
    assert calls == ["x", "tag", "x"]
    with pytest.raises(TypeCheckerError):
        child.x = 5                                             # type: ignore[assignment]
    seen.clear()
    child.tag = "t"
    assert seen == ["t"]                                        # checked once, not by both classes

    class Plain(Child):                                         # not decorated: follows Child
        pass

    Plain("d").x = "e"

    base = Base(1)                                              # the base class is checked as before
    for value in ("c", _MyInt(2)):
        with pytest.raises(TypeCheckerError):
            base.x = value
    base.x = 2
    Base(1, "t")
    seen.clear()
    Base(1, "u")
    assert seen == ["u"]                                        # and still validates a value once


def test_setattr_in_an_undecorated_class_between_two_checked_ones():
    @dataclass
    class Base:
        x: int = 0

    class Middle(Base):
        def __setattr__(self, name: str, value: Any) -> None:
            super().__setattr__(name, value)

    @dataclass(check_assignment = False)
    class Unchecked(Middle):
        pass

    @dataclass
    class Child(Middle):
        x: str = "a"                                            # type: ignore[assignment]

    Child("b").x = "c"
    with pytest.raises(TypeCheckerError):
        Child().x = 5                                           # type: ignore[assignment]
    Unchecked().x = "anything"
    with pytest.raises(TypeCheckerError):                       # Middle isn't decorated: the base's check is its check
        Middle().x = "c"
    with pytest.raises(TypeCheckerError):
        Middle("c")
    with pytest.raises(TypeCheckerError):
        Base().x = "c"


# ── inherited default_factory fields ─────────────────────────────────────────

@pytest.mark.parametrize("options", [{"frozen": True}, {"check_assignment": False}], ids = str)
def test_inherited_factory_of_a_stdlib_base_is_checked(options):
    @dataclasses.dataclass(frozen = options.get("frozen", False))
    class Plain:
        xs: list = dataclasses.field(default_factory = dict)    # type: ignore[arg-type]
        ratios: list[float] = dataclasses.field(default_factory = lambda: [1, 2])

    @dataclass(deep = True, **options)
    class Good(Plain):
        xs: list = dataclasses.field(default_factory = list)

    @dataclass(**options)
    class Bad(Plain):
        y: int = 0

    assert Good().ratios == [1.0, 2.0] and type(Good().ratios[0]) is float
    with pytest.raises(TypeCheckerError) as exc:
        Bad()
    assert "Field Bad.xs of <Dataclass Bad>: expected type: 'list', got type 'dict'" in _plain(exc.value)
    assert Plain().xs == {}                                     # the unchecked base is untouched


def test_inherited_factory_follows_the_subclass_options():
    made: list[int] = []

    def make() -> list:
        made.append(1)
        return [1, 2]

    @dataclass(deep = True)
    class Base:
        ratios: list[float] = field(default_factory = make)

    base_factory = dataclasses.fields(Base)[0].default_factory

    @dataclass(deep = True, check_assignment = False)
    class Converted(Base):
        pass

    @dataclass(deep = True, convert = False, check_assignment = False)
    class Exact(Base):
        pass

    @dataclass(deep = True, convert = False, frozen = False)
    class ExactChecked(Base):
        pass

    assert dataclasses.fields(Base)[0].default_factory is base_factory      # the base's Field is as it was
    assert Converted().ratios == [1.0, 2.0] and type(Converted().ratios[0]) is float
    assert type(Base().ratios[0]) is float
    for cls in (Exact, ExactChecked):
        with pytest.raises(TypeCheckerError) as exc:
            cls()
        assert f"{cls.__name__}.ratios" in _plain(exc.value)
    made.clear()
    Converted([0.5])
    assert made == []                                           # a supplied value doesn't call the factory


def test_inherited_factory_result_is_checked_once():
    seen, record = _recorder()

    @dataclass(deep = True, check_assignment = False)
    class Base:
        rows: list[Annotated[int, record]] = field(default_factory = lambda: [7, 8])

    @dataclass(deep = True)
    class Child(Base):                                          # its __setattr__ checks what the factory returns
        pass

    @dataclass(deep = True, check_assignment = False)
    class Other(Base):                                          # here the wrapped factory does
        pass

    for cls in (Base, Child, Other):
        cls()
        seen.clear()
        cls()
        assert seen == [7, 8], f"{cls.__name__}: the factory's result is checked once"


# ═════════════════════════════════════════════════════════════════════════════
#  FIELD MESSAGES SHOW A Literal OR type[X] ANNOTATION AS WRITTEN (review finding 6)
# ═════════════════════════════════════════════════════════════════════════════

import enum                                                     # noqa: E402


class FieldColor(enum.Enum):
    RED = 1


def test_field_message_for_literal_class_and_enum_annotations():
    @dataclass
    class Config:
        mode: Literal["r", "w"] = "r"
        kind: type[int] = int
        maybe: Literal["on"] | None = None
        color: FieldColor = FieldColor.RED
        size: int = 0

    config = Config()
    for name, value, text in (
            ("mode", "x", "Field Config.mode of <Dataclass Config>: expected type: Literal['r', 'w'], got type 'str' (Value: 'x')"),
            ("kind", str, "Field Config.kind of <Dataclass Config>: expected type: 'type[int]', got type 'type'"),
            ("maybe", "off", "Field Config.maybe of <Dataclass Config>: expected type: Literal['on'] | None, got type 'str'"),
            ("color", 5, "Field Config.color of <Dataclass Config>: expected type: 'test_dataclass_override.FieldColor', got type 'int'"),
            ("size", "x", "Field Config.size of <Dataclass Config>: expected type: 'int', got type 'str' (Value: 'x')"),
            ):
        with pytest.raises(TypeCheckerError) as e:
            setattr(config, name, value)
        assert text in _plain(e.value)
        assert e.value.problems[0].kind == "field"
    with pytest.raises(TypeCheckerError) as e:
        Config(mode = "x")
    assert "For parameter mode of <Dataclass Config>: expected type: Literal['r', 'w'], got type 'str'" in _plain(e.value)


def test_dataclass_field_of_a_strict_class_accepts_what_the_class_describes():
    import numbers
    import pathlib

    @dataclass(allow_subclass = False)
    class Job:
        path: pathlib.Path = pathlib.Path("a")
        weight: numbers.Number = 1
        kind: type = int

    job = Job()
    job.path, job.weight, job.kind = pathlib.Path("b"), 2.5, FieldColor
    assert Job(pathlib.Path("c"), 3, dict).weight == 3
    for name, value in (("path", "a"), ("weight", "1"), ("kind", 5)):
        with pytest.raises(TypeCheckerError):
            setattr(job, name, value)


# ═════════════════════════════════════════════════════════════════════════════
#  A FIELD THAT A DESCRIPTOR TAKES CARE OF  (review finding 19)
# ═════════════════════════════════════════════════════════════════════════════

class _Conversion:
    """The example of the dataclasses documentation: the annotation names the descriptor, the values are ints."""

    def __init__(self, *, default: Any) -> None:
        self._default = default

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = "_" + name

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        if obj is None:
            return self._default
        return getattr(obj, self._name, self._default)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj, self._name, int(value))


@pytest.mark.parametrize("options", [{}, {"deep": True}, {"coerce": True}, {"check_assignment": False}, {"allow_subclass": False}], ids = str)
def test_descriptor_field_is_left_to_its_descriptor(options):
    @dataclass(**options)
    class Item:
        name: str
        quantity: _Conversion = _Conversion(default = 100)
        note: str = ""

    item = Item("pen")                                              # it was a definition error: 100 is no _Conversion
    assert item.quantity == 100 and Item("pen", "5").quantity == 5 and Item("pen", quantity = 7.9).quantity == 7
    item.quantity = "12"
    assert item.quantity == 12                                      # the descriptor converts, as it was written to
    for bad in (lambda: Item(5), lambda: Item("pen", 1, 5)):        # the other fields are checked as ever
        with pytest.raises(TypeCheckerError):
            bad()
    if options.get("check_assignment", True):
        with pytest.raises(TypeCheckerError):
            item.name = 5
    assert Item.__enforced_unchecked__ == frozenset({"quantity"})


def test_descriptor_field_is_found_in_a_base_class_and_ordinary_fields_are_not_taken_for_one():
    @dataclass
    class Base:
        quantity: _Conversion = _Conversion(default = 1)

    @dataclass(deep = True)
    class Child(Base):
        tags: list[str] = dataclasses.field(default_factory = list)
        size: int = 0

    assert Child("3", ["a"]).quantity == 3
    with pytest.raises(TypeCheckerError):
        Child(1, [1])
    with pytest.raises(TypeCheckerError):
        Child(1, [], "x")

    @dataclass(slots = True)                                        # a slot is a descriptor too, and no reason to skip
    class Slotted:
        size: int = 0

    with pytest.raises(TypeCheckerError):
        Slotted("x")
    with pytest.raises(TypeCheckerError):
        Slotted().size = "x"
    assert not hasattr(Slotted, "__enforced_unchecked__")


# ── review finding 23: a standard dataclass below a checked one may give a field another type ─────

@pytest.mark.parametrize("base_options", [{}, {"deep": True}, {"coerce": True}, {"allow_subclass": False}], ids = str)
def test_standard_dataclass_below_a_checked_one_may_give_a_field_another_type(base_options):
    #* This was the last known issue: Child inherits the __setattr__ of Base, which held x to int.
    import dataclasses as std

    @dataclass(**base_options)
    class Base:
        x: int
        ratio: float = 1.0
        tags: list[int] = field(default_factory = list)

    @std.dataclass
    class Child(Base):
        x: str = ""                                                 # type: ignore[assignment]
        tags: Any = None

    @std.dataclass
    class Grandchild(Child):
        ratio: str = "half"                                         # type: ignore[assignment]

    child = Child("a")
    assert child.x == "a" and child.tags is None
    child.x = "b"
    child.x = 5                                                     # a standard dataclass checks nothing of its own
    child.tags = "anything"
    #* What Child leaves as it is stays checked, with the base's options.
    with pytest.raises(TypeCheckerError, match = "ratio"):
        child.ratio = "half"
    with pytest.raises(TypeCheckerError, match = "ratio"):
        Child("a", ratio = [])
    child.ratio = 2 if base_options.get("convert", True) else 2.0
    assert child.ratio == 2.0
    grand = Grandchild("a")
    assert grand.ratio == "half" and grand.x == "a"
    grand.ratio = None
    grand.x = None
    #* The base itself, and a plain subclass that declares nothing, are held to the base's types.
    for cls in (Base, type("Plain", (Base,), {})):
        with pytest.raises(TypeCheckerError, match = "x"):
            cls("a")
        one = cls(1)
        with pytest.raises(TypeCheckerError, match = "x"):
            one.x = "a"


def test_a_checked_dataclass_below_the_standard_one_checks_again():
    import dataclasses as std

    @dataclass
    class Base:
        x: int

    @std.dataclass
    class Loose(Base):
        x: str = ""                                                 # type: ignore[assignment]

    @dataclass
    class Tight(Loose):
        x: bytes = b""                                              # type: ignore[assignment]

    assert Tight(b"a").x == b"a" and Loose("a").x == "a"
    for bad in (lambda: Tight("a"), lambda: Tight(1), lambda: setattr(Tight(), "x", "a")):
        with pytest.raises(TypeCheckerError, match = "x"):
            bad()


def test_a_valid_assignment_is_not_asked_whose_field_it_is(monkeypatch):
    import enforced._dataclass._assignment as _assignment
    asked = []
    real = _assignment._retyped_below
    monkeypatch.setattr(_assignment, "_retyped_below", lambda *args: asked.append(args) or real(*args))

    @dataclass
    class Base:
        x: int

    class Plain(Base):
        pass

    one = Plain(1)
    one.x = 2
    one.x = 3
    assert asked == []                                              # only a value that fails gets there
    with pytest.raises(TypeCheckerError):
        one.x = "a"
    assert len(asked) >= 1


# ── the methods of a dataclass (check_methods, on by default) ────────────────────────────────────
#* The owner's decision, 2026-10-13: enforced.dataclass checks what the class defines as ``enforce``
#* does for a plain class. Before, each method needed its own @typecheck.

from functools import cached_property                      # noqa: E402
from typing import Self                                     # noqa: E402
from enforced import TypeCheckerWarning, enforce, typecheck         # noqa: E402
import inspect                                              # noqa: E402
import warnings                                             # noqa: E402

METHOD_OPTIONS = [{}, {"slots": True}, {"frozen": True}, {"kw_only": True}, {"order": True}, {"check_assignment": False},
                  {"deep": True}, {"coerce": True}, {"eq": False}, {"unsafe_hash": True}]


def _order_class(**options: Any) -> Any:
    @dataclass(**options)
    class Order:
        qty: int = 1
        price: float = 2.0

        def total(self, discount: float = 0) -> float:
            return self.qty * self.price - discount

        def more(self, other: Self | None = None) -> Self:
            return other or self                            # type: ignore[return-value]

        @staticmethod
        def parse(text: str) -> int:
            return len(text)

        @classmethod
        def of(cls, qty: int) -> Self:
            return cls(qty = qty)

        @property
        def label(self) -> str:
            return f"{self.qty}x"

        @label.setter
        def label(self, value: str) -> None:
            object.__setattr__(self, "qty", len(value))

        def __call__(self, times: int) -> float:
            return self.total() * times

        def __getitem__(self, key: str) -> Any:
            return getattr(self, key)

        def __eq__(self, other: object) -> bool:           # called by Python with anything: never wrapped
            return isinstance(other, Order) and other.qty == self.qty

        def untyped(self, anything):                        # nothing to check
            return anything

    return Order


@pytest.mark.parametrize("options", METHOD_OPTIONS, ids = repr)
def test_the_methods_of_a_dataclass_are_checked(options):
    Order = _order_class(**options)
    order = Order()
    assert order.total() == 2.0 and order.total(1) == 1.0 and type(order.total(1)) is float     # 1 converted for the float
    assert order.more() is order and Order.parse("abc") == 3 and Order.of(3).qty == 3
    assert order(2) == 4.0 and order["qty"] == 1 and order.label == "1x" and order.untyped(object) is object
    for wrong, said in ((lambda: order.total("a"), "For parameter discount of <Method Order.total>: expected type: 'float', got type 'str'"),
                        (lambda: order.more(5), "For parameter other of <Method Order.more>"),
                        (lambda: Order.parse(5), "For parameter text of <Method Order.parse>: expected type: 'str', got type 'int'"),
                        (lambda: Order.of("3" if not options.get("coerce") else []), "For parameter qty of <Method Order.of>"),
                        (lambda: order("x" if not options.get("coerce") else []), "For parameter times of <Method Order.__call__>"),
                        (lambda: order[0], "For parameter key of <Method Order.__getitem__>: expected type: 'str', got type 'int'"),
                        (lambda: setattr(order, "label", 5), "For parameter value of <Method Order.label>: expected type: 'str', got type 'int'")):
        if options.get("frozen") and "Order.label" in said:   # a frozen instance takes no assignment: Python's own error
            with pytest.raises(dataclasses.FrozenInstanceError):
                wrong()
            continue
        with pytest.raises(TypeCheckerError) as e:
            wrong()
        assert said in _plain(e.value), said
    assert (order == 5) is False                            # __eq__ takes anything, as Python needs it to
    assert vars(Order)["untyped"].__name__ == "untyped" and not hasattr(vars(Order)["untyped"], "__wrapped__")
    #* The fields are checked as ever, and constructing costs no second check of anything.
    with pytest.raises(TypeCheckerError, match = "For parameter qty of <Dataclass Order>"):
        Order(qty = "a" if not options.get("coerce") else [])


def test_what_is_left_alone_in_a_dataclass():
    def fallback(value: int) -> int:
        return value

    seen: list[Any] = []

    @dataclass
    class Job:
        retries: int = 0
        scale: InitVar[int] = 1
        handler: Any = fallback                            # a field whose default is a function: no method
        shared: ClassVar[Any] = staticmethod(fallback)     # nor is a class variable

        def __post_init__(self, scale: int) -> None:
            seen.append(scale)
            self.retries = self.retries * scale

        @enforce.exempt
        def loose(self, a: int) -> Any:
            return a

        @typecheck(check_return = True)                    # its own options stand
        def strict(self, a: int) -> int:
            return str(a)                                   # type: ignore[return-value]

        def plain(self, a: int) -> int:
            return str(a)                                   # type: ignore[return-value]  # no check_return on the class

    job = Job(2, 3)
    assert job.retries == 6 and seen == [3]
    assert vars(Job)["handler"] is fallback and job.handler("not an int") == "not an int"
    assert Job.shared("x") == "x"
    assert vars(Job)["__post_init__"].__name__ == "__post_init__" and not hasattr(vars(Job)["__post_init__"], "__wrapped__")
    assert job.loose("a") == "a" and job.plain(1) == "1"
    with pytest.raises(TypeCheckerError, match = "For return value of <Method Job.strict>"):
        job.strict(1)
    with pytest.raises(TypeCheckerError, match = "For parameter a of <Method Job.strict>"):
        job.strict("a")
    with pytest.raises(TypeCheckerError, match = "For parameter a of <Method Job.plain>"):
        job.plain("a")
    #* What dataclasses generated is what it generated.
    assert not hasattr(vars(Job)["__eq__"], "__wrapped__") and "enforced" not in vars(Job)["__repr__"].__code__.co_filename


def test_check_methods_off_and_check_return_on():
    def build(**options: Any) -> Any:
        @dataclass(**options)
        class Meter:
            unit: str = "m"

            def read(self, scale: int) -> int:
                return str(scale)                           # type: ignore[return-value]

            @property
            def size(self) -> int:
                return self.unit                            # type: ignore[return-value]

            @cached_property
            def once(self) -> int:
                return self.unit                            # type: ignore[return-value]

        return Meter

    unchecked = build(check_methods = False)()
    assert unchecked.read("a") == "a" and unchecked.size == "m"             # as before the option existed
    assert not hasattr(vars(type(unchecked))["read"], "__wrapped__")
    with pytest.raises(TypeCheckerError):
        type(unchecked)(unit = 5)                           # the fields are checked all the same
    default = build()()
    assert default.read(1) == "1" and default.size == "m" and default.once == "m"
    with pytest.raises(TypeCheckerError, match = "For parameter scale of <Method Meter.read>"):
        default.read("a")
    returning = build(check_return = True)()
    for wrong, said in ((lambda: returning.read(1), "For return value of <Method Meter.read>: expected type: 'int', got type 'str'"),
                        (lambda: returning.size, "For return value of <Method Meter.size>"),
                        (lambda: returning.once, "For return value of <Method Meter.once>")):
        with pytest.raises(TypeCheckerError) as e:
            wrong()
        assert said in _plain(e.value)
    assert build(check_return = True, check_methods = False)().read(1) == "1"       # check_return is about the methods
    for name, default_value in (("check_methods", True), ("check_return", False)):
        assert inspect.signature(dataclass).parameters[name].default is default_value


def test_a_slots_dataclass_keeps_super_and_class_in_its_methods():
    #* slots = True makes a new class, and a method that uses super() or __class__ holds a cell
    #* with the class in it. The methods are wrapped on the class dataclasses returned.
    @dataclass
    class Base:
        x: int = 0

        def describe(self, prefix: str) -> str:
            return f"{prefix}{self.x}"

    @dataclass(slots = True)
    class Child(Base):
        y: int = 0

        def describe(self, prefix: str) -> str:
            return super().describe(prefix) + f"/{self.y}/{__class__.__name__}"

    assert Child(1, 2).describe(">") == ">1/2/Child" and "__slots__" in vars(Child)
    with pytest.raises(TypeCheckerError, match = "For parameter prefix of <Method Child.describe>"):
        Child().describe(5)
    with pytest.raises(TypeCheckerError, match = "For parameter prefix of <Method Base.describe>"):
        Base().describe(5)


def test_subclasses_and_self_in_the_methods_of_a_dataclass():
    @dataclass
    class Node:
        value: int = 0

        def join(self, other: Self) -> Self:
            return other

    class Plain(Node):                                      # not decorated: inherits the checked method
        def extra(self, a: int) -> Any:
            return a

    @dataclass
    class Leaf(Node):
        weight: float = 0

        def scaled(self, by: int) -> float:
            return self.weight * by

    assert Plain().join(Plain()).value == 0 and Plain().extra("unchecked") == "unchecked"
    with pytest.raises(TypeCheckerError, match = "For parameter other of <Method Node.join>"):
        Plain().join(Node())                                # Self is Plain there
    assert Leaf(1, 2).scaled(2) == 4.0
    with pytest.raises(TypeCheckerError, match = "For parameter by of <Method Leaf.scaled>"):
        Leaf().scaled("a")
    with pytest.raises(TypeCheckerError, match = "For parameter other of <Method Node.join>"):
        Leaf().join(Node())


def test_on_error_warn_covers_the_methods_too():
    @dataclass(on_error = "warn", check_return = True)
    class Loose:
        n: int = 0

        def add(self, more: int) -> int:
            return more

    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("always")
        assert Loose().add("x") == "x"
    assert [w.category for w in seen] == [TypeCheckerWarning] * 2
    assert "For parameter more of <Method Loose.add>" in str(seen[0].message) and "For return value of <Method Loose.add>" in str(seen[1].message)


def test_a_written_init_is_left_to_its_author():
    #* init = False: the class has no generated __init__. One written by hand is not wrapped by
    #* check_methods (its defaults are still checked once, as before): @typecheck on it checks it.
    @dataclass(init = False)
    class Manual:
        x: int = 0

        def __init__(self, x: int) -> None:
            self.x = x

        def double(self, by: int) -> int:
            return self.x * by

    assert Manual(2).double(2) == 4
    with pytest.raises(TypeCheckerError, match = "Field Manual.x of <Dataclass Manual>"):
        Manual("a")                                         # stopped by the assignment check, not by __init__
    with pytest.raises(TypeCheckerError, match = "For parameter by of <Method Manual.double>"):
        Manual(1).double("a")


def test_a_wrong_item_assigned_to_a_deep_field_is_named_after_its_second_use():
    #* The reporter keeps a short route for a field whose type alone can be wrong. A deep field
    #* is no such field: once its checker had a plan entry for it (2026-10-15), the short route
    #* took it, and the message showed the plan's marker where the expected type belongs.
    @dataclass(deep = True)
    class Order:
        lines: list[tuple[str, int]] = field(default_factory = list)

    order = Order()
    for _ in range(3):                                          # the first assignment makes the checker; later ones use it
        with pytest.raises(TypeCheckerError) as e:
            order.lines = [("pen", 1), ("ink", "two")]
        text = _plain(e.value)
        assert "Introspected field Order.lines at index [1][1] of <Dataclass Order>: expected type: 'int'" in text
        assert "object at 0x" not in text
        with pytest.raises(TypeCheckerError, match = r"tuple\[str, int\] with 2 items"):
            order.lines = [("pen",)]
