"""
``enforced``, the class decorator, and ``skip_typecheck``, the mark for a method it is to leave alone.

Also what each decorator refuses: ``typecheck`` a class, ``enforced`` anything that isn't a plain class.
The class tests that predate the split (``__init__``, methods, defaults, ``Self``) are in test_typechecker.py.
The special methods ``enforced`` checks (``__call__``, ``__getitem__``, ``__new__`` ...) are at the end.
"""
from pyvalidate import TypeCheckerError, dataclass, enforced, skip_typecheck, typecheck
from typing import Any, NamedTuple, Self
import abc
import asyncio
import copy
import dataclasses
import enum
import functools
import inspect
import pickle
import re
import pytest


def _plain(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


def _is_wrapped(member: Any) -> bool:
    """Whether a class attribute is (or holds) a wrapper made by pyvalidate."""
    fn = getattr(member, "__func__", member)
    return "_pv_bootstrap" in getattr(fn, "__globals__", {})


# ═════════════════════════════════════════════════════════════════════════════
#  THE DECORATOR
# ═════════════════════════════════════════════════════════════════════════════

def test_enforced_returns_the_class():
    class Plain:
        pass

    assert enforced(Plain) is Plain
    assert enforced()(Plain) is Plain
    assert enforced(deep = True)(Plain) is Plain


def test_enforced_takes_the_five_options_of_typecheck_and_nothing_else():
    #* Every option applies to a class: its methods take arguments and return values as functions do.
    options = {"allow_subclass": True, "check_return": False, "convert": True, "coerce": False, "deep": False}
    for decorator in (enforced, typecheck):
        parameters = inspect.signature(decorator).parameters
        assert {name: p.default for name, p in parameters.items() if name != "obj"} == options


def test_enforced_checks_init_methods_static_and_class_methods():
    @enforced
    class Account:
        def __init__(self, owner: str, balance: float = 0.0) -> None:
            self.owner, self.balance = owner, balance

        def deposit(self, amount: float) -> float:
            self.balance += amount
            return self.balance

        @staticmethod
        def parse(text: str) -> float:
            return float(text)

        @classmethod
        def opened_by(cls, owner: str) -> "Account":
            return cls(owner)

        def _audit(self, note: str) -> str:              # a single underscore is an ordinary method
            return note

    account = Account("ana")
    assert account.deposit(5) == 5.0                     # converted: int -> float
    assert Account.parse("2.5") == 2.5 and account.parse("2.5") == 2.5
    assert Account.opened_by("bo").owner == "bo" and account.opened_by("bo").owner == "bo"
    for bad in (lambda: Account(1), lambda: account.deposit("5"), lambda: Account.parse(2.5),
                lambda: Account.opened_by(None), lambda: account._audit(1)):
        with pytest.raises(TypeCheckerError):
            bad()


def test_enforced_messages_name_the_class_and_the_method():
    @enforced
    class Account:
        def __init__(self, owner: str) -> None: ...
        def deposit(self, amount: float) -> None: ...

    with pytest.raises(TypeCheckerError) as init:
        Account(1)
    with pytest.raises(TypeCheckerError) as method:
        Account("ana").deposit("x")
    assert "For parameter owner of <Class Account>: expected type: 'str', got type 'int' (Value: 1)" in _plain(init.value)
    assert "For parameter amount of <Method Account.deposit>: expected type: 'float'" in _plain(method.value)


@pytest.mark.parametrize("options, value, outcome", [
    ({}, 1, 1.0),                                           # convert is on by default
    ({"convert": False}, 1, TypeCheckerError),
    ({}, "1.5", TypeCheckerError),                          # coerce is off by default
    ({"coerce": True}, "1.5", 1.5),
    ({}, True, TypeCheckerError),                           # a bool is no number
    ])
def test_enforced_passes_convert_and_coerce_to_every_method(options, value, outcome):
    @enforced(**options)
    class Scale:
        def __init__(self, factor: float) -> None:
            self.factor = factor

        def by(self, factor: float) -> float:
            return factor

        @staticmethod
        def of(factor: float) -> float:
            return factor

    for call in (lambda: Scale(value).factor, lambda: Scale(1.0).by(value), lambda: Scale.of(value)):
        if outcome is TypeCheckerError:
            with pytest.raises(TypeCheckerError):
                call()
        else:
            result = call()
            assert result == outcome and type(result) is float


def test_enforced_allow_subclass_false_is_exact():
    class Animal: ...
    class Dog(Animal): ...

    @enforced
    class Kennel:
        def take(self, animal: Animal) -> Animal: return animal

    @enforced(allow_subclass = False)
    class StrictKennel:
        def take(self, animal: Animal) -> Animal: return animal

    dog = Dog()
    assert Kennel().take(dog) is dog
    assert isinstance(StrictKennel().take(Animal()), Animal)
    with pytest.raises(TypeCheckerError):
        StrictKennel().take(dog)


def test_enforced_check_return_covers_methods_not_init():
    @enforced(check_return = True)
    class Counter:
        def __init__(self) -> int:                          # a wrong annotation: __init__ returns None
            self.n = 0

        def next(self) -> int:
            self.n += 1
            return self.n

        def broken(self) -> int:
            return "one"                                    # type: ignore[return-value]

        def ratio(self) -> float:
            return 1                                        # converted on the way out

        @classmethod
        def named(cls) -> str:
            return 5                                        # type: ignore[return-value]

    counter = Counter()                                     # the return annotation of __init__ is not checked
    assert counter.next() == 1
    assert type(counter.ratio()) is float
    with pytest.raises(TypeCheckerError, match = "return value"):
        counter.broken()
    with pytest.raises(TypeCheckerError, match = "return value"):
        Counter.named()


def test_enforced_without_check_return_ignores_what_methods_return():
    @enforced
    class Counter:
        def broken(self) -> int:
            return "one"                                    # type: ignore[return-value]

    assert Counter().broken() == "one"


def test_enforced_deep_checks_items_in_every_method():
    @enforced(deep = True)
    class Store:
        def __init__(self, stock: dict[str, int]) -> None:
            self.stock = stock

        def restock(self, names: list[str]) -> int:
            return len(names)

    assert Store({"apple": 1}).restock(["a", "b"]) == 2
    with pytest.raises(TypeCheckerError, match = r"stock at index \['apple'\]"):
        Store({"apple": "1"})
    with pytest.raises(TypeCheckerError, match = r"names at index \[1\]"):
        Store({}).restock(["a", 1])


def test_enforced_self_and_the_class_name_resolve_to_the_class():
    @enforced(check_return = True)
    class Node:
        def __init__(self, parent: "Node | None" = None) -> None:
            self.parent = parent

        def attach(self, child: Self) -> Self:
            child.parent = self
            return child

        def detached(self) -> Self:
            return None                                     # type: ignore[return-value]

    root = Node()
    leaf = root.attach(Node())
    assert leaf.parent is root
    for bad in (lambda: Node(5), lambda: root.attach(5), lambda: root.detached()):
        with pytest.raises(TypeCheckerError, match = "Node"):
            bad()


def test_enforced_checks_a_bad_default_on_the_first_call():
    @enforced
    class Retry:
        def wait(self, seconds: float = "soon") -> float:   # type: ignore[assignment]
            return seconds

    with pytest.raises(TypeCheckerError, match = "default value of parameter seconds"):
        Retry().wait()


def test_enforced_async_and_generator_methods():
    @enforced(check_return = True)
    class Feed:
        async def fetch(self, page: int) -> str:
            return page                                     # type: ignore[return-value]

        async def ok(self, page: int) -> int:
            return page

        def pages(self, upto: int):
            yield from range(upto)

    feed = Feed()
    assert asyncio.run(feed.ok(2)) == 2
    assert list(feed.pages(3)) == [0, 1, 2]
    with pytest.raises(TypeCheckerError, match = "return value"):
        asyncio.run(feed.fetch(1))
    with pytest.raises(TypeCheckerError):
        asyncio.run(feed.ok("1"))
    with pytest.raises(TypeCheckerError):
        feed.pages("3")


# ─── what it leaves alone ─────────────────────────────────────────────────────

def test_enforced_leaves_operators_properties_and_other_attributes_alone():
    @enforced
    class Money:
        currency: str = "EUR"
        rates = {"EUR": 1.0}

        def __init__(self, amount: int) -> None:
            self._amount = amount

        def __eq__(self, other: "Money") -> bool:           # type: ignore[override]
            return False

        def __add__(self, other: "Money") -> Any:
            return other

        @property
        def amount(self) -> int:
            return self._amount

        @amount.setter
        def amount(self, value: int) -> None:
            self._amount = value

        class Inner:
            def method(self, x: int) -> Any:
                return x

    money = Money(1)
    assert (money == "not money") is False
    assert money + "x" == "x"
    money.amount = "ten"                                    # a property is not checked
    assert money.amount == "ten"
    assert Money.Inner().method("x") == "x"                 # nor a class defined inside
    assert Money.currency == "EUR" and Money.rates == {"EUR": 1.0}
    assert isinstance(vars(Money)["amount"], property)


def test_enforced_class_without_methods_or_init():
    @enforced
    class Empty:
        pass

    assert isinstance(Empty(), Empty)


def test_enforced_twice_wraps_once():
    @enforced
    class Box:
        def put(self, item: int) -> int: return item

    once = vars(Box)["put"]
    assert enforced(Box) is Box and enforced(deep = True)(Box) is Box
    assert vars(Box)["put"] is once
    assert once.__wrapped__.__name__ == "put" and not _is_wrapped(once.__wrapped__)


def test_enforced_keeps_name_doc_and_signature_of_methods():
    @enforced
    class Box:
        def put(self, item: int, *, quiet: bool = False) -> int:
            """Put an item in."""
            return item

    assert Box.put.__name__ == "put" and Box.put.__doc__ == "Put an item in."
    assert Box.put.__qualname__.endswith("Box.put")
    assert list(inspect.signature(Box.put).parameters) == ["self", "item", "quiet"]


# ─── other kinds of class ─────────────────────────────────────────────────────

def test_enforced_slots_class():
    @enforced
    class Pixel:
        __slots__ = ("x", "y")

        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y

    assert Pixel(1, 2).y == 2
    with pytest.raises(TypeCheckerError):
        Pixel(1, "2")


def test_enforced_enum_class():
    @enforced
    class Level(enum.Enum):
        LOW = 1
        HIGH = 2

        def above(self, other: "Level") -> bool:
            return self.value > other.value

    assert Level.HIGH.above(Level.LOW) is True and list(Level) == [Level.LOW, Level.HIGH]
    with pytest.raises(TypeCheckerError):
        Level.HIGH.above(1)


def test_enforced_abstract_class_and_its_implementation():
    @enforced
    class Shape(abc.ABC):
        @abc.abstractmethod
        def scaled(self, factor: float) -> "Shape": ...

        def describe(self, prefix: str) -> str:
            return prefix

    @enforced
    class Square(Shape):
        def scaled(self, factor: float) -> "Square":
            return self

    with pytest.raises(TypeError, match = "abstract"):
        Shape()                                             # still abstract
    square = Square()
    assert square.scaled(2) is square and square.describe("a") == "a"
    for bad in (lambda: square.scaled("2"), lambda: square.describe(1)):
        with pytest.raises(TypeCheckerError):
            bad()


def test_enforced_generic_class():
    @enforced
    class Stack[T]:
        def __init__(self) -> None:
            self.items: list[T] = []

        def push(self, item: T, times: int = 1) -> None:
            self.items += [item] * times

    stack = Stack[int]()
    stack.push("anything")                                  # an unbound type variable accepts every value
    assert stack.items == ["anything"]
    with pytest.raises(TypeCheckerError):
        stack.push(1, times = "2")


def test_enforced_plain_subclass_of_a_dataclass_is_a_plain_class():
    @dataclass
    class Point:
        x: int

    @enforced
    class Labelled(Point):                                  # not a dataclass itself: no fields of its own
        def label(self, prefix: str) -> str:
            return f"{prefix}{self.x}"

    assert Labelled(1).label("p") == "p1"
    with pytest.raises(TypeCheckerError):
        Labelled(1).label(1)
    with pytest.raises(TypeCheckerError):
        Labelled("1")                                       # the dataclass's own check


# ─── inheritance ──────────────────────────────────────────────────────────────

def test_subclass_inherits_the_checked_methods_but_its_own_are_not_checked():
    @enforced
    class Base:
        def __init__(self, n: int) -> None:
            self.n = n

        def add(self, n: int) -> int:
            return self.n + n

    class Child(Base):                                      # not decorated
        def add(self, n: int) -> Any:                       # overrides: no longer checked
            return n

        def extra(self, text: str) -> Any:
            return text

    child = Child(1)
    assert child.add("x") == "x" and child.extra(5) == 5
    with pytest.raises(TypeCheckerError):
        Child("1")                                          # the inherited __init__ is still checked


def test_enforced_subclass_checks_its_own_methods_and_keeps_the_base_as_it_is():
    @enforced
    class Base:
        def add(self, n: int) -> int:
            return n

    inherited = vars(Base)["add"]

    @enforced(allow_subclass = False, coerce = True)
    class Child(Base):
        def extra(self, n: int) -> int:
            return n

    assert "add" not in vars(Child) and vars(Base)["add"] is inherited
    assert Child().extra("5") == 5                          # the child's options
    with pytest.raises(TypeCheckerError):
        Child().add("5")                                    # the base's options: no coercion


# ═════════════════════════════════════════════════════════════════════════════
#  skip_typecheck
# ═════════════════════════════════════════════════════════════════════════════

def test_skip_typecheck_leaves_the_method_exactly_as_it_is():
    def render(self, sink: int) -> int:
        return sink

    assert skip_typecheck(render) is render

    @enforced(check_return = True)
    class Report:
        def add(self, line: str) -> None: ...

        draw = render

    assert vars(Report)["draw"] is render and not _is_wrapped(vars(Report)["draw"])
    assert Report().draw("anything") == "anything"         # neither the argument nor the return value
    with pytest.raises(TypeCheckerError):
        Report().add(1)                                     # the others are still checked


def test_skip_typecheck_on_init():
    @enforced
    class Loose:
        @skip_typecheck
        def __init__(self, value: int) -> None:
            self.value = value

        def set(self, value: int) -> None:
            self.value = value

    assert Loose("x").value == "x"
    with pytest.raises(TypeCheckerError):
        Loose(1).set("x")


def test_skip_typecheck_above_or_below_classmethod_and_staticmethod():
    @enforced
    class Tools:
        @skip_typecheck
        @classmethod
        def above_class(cls, x: int) -> Any: return x

        @classmethod
        @skip_typecheck
        def below_class(cls, x: int) -> Any: return x

        @skip_typecheck
        @staticmethod
        def above_static(x: int) -> Any: return x

        @staticmethod
        @skip_typecheck
        def below_static(x: int) -> Any: return x

        @classmethod
        def checked_class(cls, x: int) -> Any: return x

        @staticmethod
        def checked_static(x: int) -> Any: return x

    for name in ("above_class", "below_class", "above_static", "below_static"):
        assert not _is_wrapped(vars(Tools)[name])
        assert getattr(Tools, name)("x") == "x" and getattr(Tools(), name)("x") == "x"
    assert isinstance(vars(Tools)["above_class"], classmethod) and isinstance(vars(Tools)["above_static"], staticmethod)
    for name in ("checked_class", "checked_static"):
        with pytest.raises(TypeCheckerError):
            getattr(Tools, name)("x")


def test_skip_typecheck_method_is_never_looked_at():
    @enforced
    class Notes:
        @skip_typecheck
        def keep(self, text: "NoSuchName", times: int = "many") -> Any:   # type: ignore[assignment]  # noqa: F821
            return text

    assert Notes().keep(1) == 1                             # an annotation that resolves nowhere, a bad default


def test_skip_typecheck_does_not_reach_a_subclass_that_overrides():
    @enforced
    class Base:
        @skip_typecheck
        def load(self, source: str) -> Any:
            return source

    @enforced
    class Child(Base):
        def load(self, source: str) -> Any:                 # its own method, not marked
            return source

    @enforced
    class Other(Base):
        pass

    assert Base().load(1) == 1 and Other().load(1) == 1
    with pytest.raises(TypeCheckerError):
        Child().load(1)


def test_skip_typecheck_on_what_enforced_leaves_alone_anyway_is_harmless():
    @enforced
    class Thing:
        @skip_typecheck
        @property
        def size(self) -> int:
            return "big"                                    # type: ignore[return-value]

        @skip_typecheck
        @functools.cache
        def cached(self, n: int) -> Any:
            return n

    assert Thing().size == "big" and isinstance(vars(Thing)["size"], property)
    assert Thing().cached("x") == "x"
    assert skip_typecheck(len) is len                       # an object that takes no attributes


def test_skip_typecheck_below_a_decorator_that_uses_wraps():
    def logged(fn):
        @functools.wraps(fn)                                # copies the mark along with the name
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner

    @enforced
    class Thing:
        @logged
        @skip_typecheck
        def below(self, x: int) -> Any: return x

        @skip_typecheck
        @logged
        def above(self, x: int) -> Any: return x

        @logged
        def checked(self, x: int) -> Any: return x

    assert Thing().below("x") == "x" and Thing().above("x") == "x"
    assert not _is_wrapped(vars(Thing)["below"]) and not _is_wrapped(vars(Thing)["above"])
    with pytest.raises(TypeCheckerError):
        Thing().checked("x")


def test_explicit_typecheck_wins_over_skip_typecheck():
    @enforced
    class Thing:
        @skip_typecheck
        @typecheck
        def a(self, x: int, other: Self | None = None) -> Any: return x

        @typecheck
        @skip_typecheck
        def b(self, x: int, other: Self | None = None) -> Any: return x

    for call in (Thing().a, Thing().b):
        with pytest.raises(TypeCheckerError, match = r"<Method Thing\.[ab]>"):     # checked, and it knows its class
            call("x")


# ═════════════════════════════════════════════════════════════════════════════
#  A METHOD WITH ITS OWN @typecheck KEEPS ITS OPTIONS
# ═════════════════════════════════════════════════════════════════════════════

def test_own_typecheck_options_stand_and_the_method_is_checked_once():
    seen: list[Any] = []

    def record(value: Any) -> bool:
        seen.append(value)
        return True

    from typing import Annotated

    @enforced
    class Form:
        @typecheck(coerce = True)
        def age(self, years: int) -> int:                   # looser than the class
            return years

        @typecheck(allow_subclass = False)
        def flag(self, value: int) -> int:                  # stricter than the class
            return value

        @typecheck
        def once(self, value: Annotated[int, record]) -> int:
            return value

        def plain(self, years: int) -> int:
            return years

    class MyInt(int): ...

    own = vars(Form)["age"]
    assert _is_wrapped(own) and not _is_wrapped(own.__wrapped__)      # not wrapped a second time
    form = Form()
    assert form.age("42") == 42
    with pytest.raises(TypeCheckerError):
        form.plain("42")
    assert form.plain(MyInt(3)) == 3
    with pytest.raises(TypeCheckerError):
        form.flag(MyInt(3))
    form.once(7)
    assert seen == [7]


def test_own_typecheck_learns_its_class():
    @enforced
    class Node:
        @typecheck(check_return = True)
        def attach(self, child: Self, parent: "Node | None" = None) -> Self:
            return parent                                   # type: ignore[return-value]

        @typecheck
        @classmethod
        def above(cls, other: Self) -> Any: return other

        @classmethod
        @typecheck
        def below(cls, other: Self) -> Any: return other

        @staticmethod
        @typecheck
        def static(other: "Node") -> Any: return other

    node = Node()
    assert node.attach(node, node) is node
    assert Node.above(node) is node and Node.below(node) is node and Node.static(node) is node
    with pytest.raises(TypeCheckerError) as e:
        node.attach(5)
    assert "For parameter child of <Method Node.attach>" in _plain(e.value)
    with pytest.raises(TypeCheckerError, match = "return value"):
        node.attach(node)                                   # returns None for -> Self
    for bad in (lambda: node.attach(node, 5), lambda: Node.above(5), lambda: Node.below(5), lambda: Node.static(5)):
        with pytest.raises(TypeCheckerError, match = "Node"):
            bad()


def test_own_typecheck_below_another_decorator_is_not_checked_twice():
    def logged(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner

    @enforced
    class Form:
        @logged
        @typecheck(coerce = True)
        def age(self, years: int) -> int:
            return years

        @logged
        def name(self, text: str) -> str:                   # no @typecheck inside: the class checks it
            return text

    assert not _is_wrapped(vars(Form)["age"])               # left as @logged made it
    assert Form().age("42") == 42
    assert _is_wrapped(vars(Form)["name"])
    with pytest.raises(TypeCheckerError):
        Form().name(1)


def test_typecheck_on_a_method_of_a_class_that_is_not_enforced_still_works():
    class Account:
        @typecheck
        def deposit(self, amount: float) -> float:
            return amount

    assert Account().deposit(1) == 1.0
    with pytest.raises(TypeCheckerError):
        Account().deposit("1")


# ═════════════════════════════════════════════════════════════════════════════
#  WHAT EACH DECORATOR REFUSES
# ═════════════════════════════════════════════════════════════════════════════

def test_typecheck_refuses_a_class_at_the_definition():
    class Box:
        def __init__(self, value: int) -> None:
            self.value = value

    untouched = Box.__init__
    for decorate in (typecheck, typecheck(), typecheck(deep = True, check_return = True)):
        with pytest.raises(TypeCheckerError) as e:
            decorate(Box)                                   # type: ignore[arg-type]
        assert _plain(e.value) == ("typecheck cannot check <Class Box>: it checks functions and methods. "
                                   "A class is checked by @enforced")
    assert isinstance(e.value, TypeError) and Box.__init__ is untouched
    with pytest.raises(TypeCheckerError):
        @typecheck
        class Other:                                        # the usual way to meet it
            pass


def test_typecheck_refuses_a_class_inside_another_decorator_too():
    class Box:
        pass

    for wrapped in (staticmethod(Box), classmethod(Box)):
        with pytest.raises(TypeCheckerError, match = "typecheck cannot check <Class Box>"):
            typecheck(wrapped)


def test_typecheck_still_takes_a_bound_method_and_a_function_another_decorator_wrapped():
    class Adder:
        def add(self, a: int, b: int) -> int:
            return a + b

    @functools.lru_cache
    def square(n: int) -> int:
        return n * n

    for checked, good, bad in ((typecheck(Adder().add), (1, 2), (1, "2")), (typecheck(square), (3,), ("3",))):
        assert checked(*good) in (3, 9)
        with pytest.raises(TypeCheckerError):
            checked(*bad)


@pytest.mark.parametrize("make_dataclass", [dataclasses.dataclass, dataclass], ids = ["dataclasses", "pyvalidate"])
def test_typecheck_refuses_a_dataclass_and_names_the_decorator_for_it(make_dataclass):
    @make_dataclass
    class Point:
        x: int

    with pytest.raises(TypeCheckerError) as e:
        typecheck(Point)                                    # type: ignore[arg-type]
    assert _plain(e.value) == ("typecheck cannot check <Dataclass Point>: it checks functions and methods. "
                               "A dataclass is checked by pyvalidate.dataclass")


@pytest.mark.parametrize("make_dataclass", [
    dataclasses.dataclass, dataclass, dataclasses.dataclass(slots = True, frozen = True), dataclass(slots = True),
    ], ids = ["dataclasses", "pyvalidate", "dataclasses, slots and frozen", "pyvalidate, slots"])
def test_enforced_refuses_a_dataclass(make_dataclass):
    @make_dataclass
    class Point:
        x: int

        def moved(self, dx: int) -> int:
            return self.x + dx

    untouched = vars(Point)["moved"]
    for decorate in (enforced, enforced(), enforced(deep = True)):
        with pytest.raises(TypeCheckerError) as e:
            decorate(Point)
        assert _plain(e.value) == ("enforced cannot check <Dataclass Point>: it checks plain classes. "
                                   "A dataclass is checked by pyvalidate.dataclass, and a method of one by @typecheck")
    assert vars(Point)["moved"] is untouched


def test_a_method_of_a_dataclass_is_checked_with_typecheck():
    @dataclass
    class Point:
        x: int

        @typecheck
        def moved(self, dx: int) -> int:
            return self.x + dx

    assert Point(1).moved(2) == 3
    with pytest.raises(TypeCheckerError):
        Point(1).moved("2")


def test_enforced_refuses_what_is_not_a_class():
    def function(x: int) -> int:
        return x

    class Callable_:
        def __call__(self, x: int) -> int: return x

    told = "it checks classes. A function or a method is checked by @typecheck"
    for target, shown in ((function, "<Function function>"), (len, "<Function len>"), (Callable_(), "<Callable Callable_>"),
                          (5, "5"), ("Box", "'Box'")):
        for decorate in (enforced, enforced(), enforced(coerce = True)):
            with pytest.raises(TypeCheckerError) as e:
                decorate(target)                            # type: ignore[call-overload]
            assert _plain(e.value) == f"enforced cannot check {shown}: {told}"
    with pytest.raises(TypeCheckerError):
        class Box:
            @enforced                                       # on a method: the wrong decorator
            def put(self, item: int) -> None: ...


# ═════════════════════════════════════════════════════════════════════════════
#  SPECIAL METHODS: THOSE A CALLER HANDS VALUES TO ARE CHECKED, THE REST ARE LEFT ALONE
# ═════════════════════════════════════════════════════════════════════════════

def test_enforced_checks_call():
    @enforced
    class Scale:
        def __call__(self, value: float, *, times: int = 1) -> float:
            return value * times

    scale = Scale()
    assert scale(2) == 2.0 and type(scale(2)) is float      # converted, as for any method
    assert scale(1.5, times = 2) == 3.0
    for bad in (lambda: scale("2"), lambda: scale(1.0, times = "2"), lambda: scale()):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "<Method Scale.__call__>" in _plain(e.value)
    assert _is_wrapped(vars(Scale)["__call__"]) and callable(scale)


def test_enforced_checks_item_access_and_membership():
    @enforced
    class Prices:
        def __init__(self) -> None:
            self.data: dict[str, float] = {}

        def __getitem__(self, name: str) -> float:
            return self.data[name]

        def __setitem__(self, name: str, price: float) -> None:
            self.data[name] = price

        def __delitem__(self, name: str) -> None:
            del self.data[name]

        def __contains__(self, name: str) -> bool:
            return name in self.data

    prices = Prices()
    prices["tea"] = 3                                       # stored converted
    assert prices["tea"] == 3.0 and type(prices["tea"]) is float
    assert "tea" in prices and "milk" not in prices
    del prices["tea"]
    assert "tea" not in prices

    def store(name: Any, price: Any) -> None: prices[name] = price
    def remove(name: Any) -> None: del prices[name]

    for bad, method in ((lambda: store(1, 2.0), "__setitem__"), (lambda: store("tea", "3"), "__setitem__"),
                        (lambda: prices[1], "__getitem__"), (lambda: prices[0:2], "__getitem__"),
                        (lambda: remove(1), "__delitem__"), (lambda: 1 in prices, "__contains__")):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert f"<Method Prices.{method}>" in _plain(e.value)
    assert prices.data == {}                                # nothing was stored by the rejected assignments


def test_enforced_checks_new_and_reports_it_as_the_class():
    @enforced(check_return = True)
    class Token:
        def __new__(cls, text: str, weight: float = 1) -> "Token":
            self = super().__new__(cls)
            self.text, self.weight = text, weight
            return self

    token = Token("a")
    assert isinstance(token, Token) and token.weight == 1.0 and type(token.weight) is float   # the default, converted
    assert isinstance(vars(Token)["__new__"], staticmethod)
    with pytest.raises(TypeCheckerError) as e:
        Token(1)
    assert "For parameter text of <Class Token>: expected type: 'str', got type 'int' (Value: 1)" in _plain(e.value)
    with pytest.raises(TypeCheckerError, match = "Missing required argument for <Class Token>"):
        Token()

    class Sub(Token):                                       # the inherited __new__ is still checked
        pass

    assert type(Sub("a")) is Sub
    with pytest.raises(TypeCheckerError):
        Sub(1)


def test_enforced_does_not_check_what_new_returns():
    @enforced(check_return = True)
    class Maybe:
        def __new__(cls, value: int) -> "Maybe":
            return None if value == 0 else super().__new__(cls)     # type: ignore[return-value]

    assert Maybe(0) is None and isinstance(Maybe(1), Maybe)


def test_enforced_checks_new_and_init_each_with_its_own_annotations():
    @enforced
    class Both:
        def __new__(cls, value: int, *rest: Any) -> "Both":
            return super().__new__(cls)

        def __init__(self, value: int, label: str = "") -> None:
            self.value, self.label = value, label

    assert Both(1, "a").label == "a"
    with pytest.raises(TypeCheckerError, match = "parameter value"):
        Both("1")
    with pytest.raises(TypeCheckerError, match = "parameter label"):
        Both(1, 2)


@enforced
class Point(NamedTuple):                                    # at module level, so that an instance pickles
    x: int
    y: float = 0.0

    def moved(self, dx: int) -> "Point":
        return Point(self.x + dx, self.y)


def test_enforced_namedtuple_class_checks_construction():
    point = Point(1, 2)
    assert point == (1, 2.0) and type(point.y) is float and Point(3).y == 0.0
    assert point.moved(1) == Point(2, 2.0)
    for bad in (lambda: Point("1"), lambda: Point(x = 1, y = "2"), lambda: Point(), lambda: point.moved("1")):
        with pytest.raises(TypeCheckerError):
            bad()
    #* The helpers of a named tuple build through tuple.__new__, as they always did.
    assert Point._make([1, 2.0]) == point and point._replace(x = 5) == Point(5, 2.0)
    assert pickle.loads(pickle.dumps(point)) == point and copy.deepcopy(point) == point


def test_enforced_checks_what_enter_returns_only_with_check_return():
    def make(**options: Any) -> type:
        @enforced(**options)
        class Session:
            def __enter__(self) -> Self:
                return "not a session"                      # type: ignore[return-value]

            def __exit__(self, kind: type, error: Exception, trace: int) -> None:    # annotations Python won't honour
                return None

            async def __aenter__(self) -> Self:
                return "not a session"                      # type: ignore[return-value]

            async def __aexit__(self, kind: type, error: Exception, trace: int) -> None:
                return None
        return Session

    def use(cls: type) -> Any:
        with cls() as session:
            return session

    async def use_async(cls: type) -> Any:
        async with cls() as session:
            return session

    assert use(make()) == "not a session" and asyncio.run(use_async(make())) == "not a session"
    checked = make(check_return = True)
    with pytest.raises(TypeCheckerError, match = r"return value of <Method Session\.__enter__>"):
        use(checked)
    with pytest.raises(TypeCheckerError, match = r"return value of <Method Session\.__aenter__>"):
        asyncio.run(use_async(checked))


def test_enforced_exit_is_left_alone():
    @enforced(check_return = True)
    class Session:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, kind: type, error: Exception, trace: int) -> int:   # receives None three times
            return None                                     # type: ignore[return-value]

    with Session() as session:
        assert isinstance(session, Session)
    assert not _is_wrapped(vars(Session)["__exit__"])


def test_enforced_leaves_the_special_methods_python_calls_alone():
    @enforced(check_return = True)
    class Money:
        def __init__(self, amount: int) -> None:
            object.__setattr__(self, "amount", amount)

        def __eq__(self, other: "Money") -> bool:           # type: ignore[override]
            return NotImplemented
        def __lt__(self, other: "Money") -> bool: return NotImplemented
        def __add__(self, other: "Money") -> "Money": return NotImplemented
        def __radd__(self, other: "Money") -> "Money": return self
        def __hash__(self) -> str: return 1                 # type: ignore[override]
        def __repr__(self) -> int: return "Money"           # type: ignore[override]
        def __len__(self) -> str: return 2                  # type: ignore[override]
        def __bool__(self) -> str: return True              # type: ignore[override]
        def __iter__(self) -> int: return iter(())          # type: ignore[override]
        def __getattr__(self, name: int) -> int: raise AttributeError(name)
        def __setattr__(self, name: int, value: int) -> None: object.__setattr__(self, name, value)
        def __format__(self, spec: int) -> int: return "m"  # type: ignore[override]
        def __init_subclass__(cls, flag: int = "no") -> None: ...        # type: ignore[assignment]
        def __class_getitem__(cls, item: int) -> Any: return cls

    money = Money(1)
    assert (money == "x") is False and money != 5           # == against any object still answers
    assert sum([money]) is money                            # 0 + money: NotImplemented, then __radd__
    with pytest.raises(TypeError, match = "unsupported operand"):
        money + "x"
    assert repr(money) == "Money" and len(money) == 2 and bool(money) and list(money) == [] and hash(money) == 1
    assert f"{money}" == "m" and Money["x"] is Money and not hasattr(money, "missing")
    money.label = "assigned"                                # __setattr__ is not checked
    assert money.label == "assigned"

    class Sub(Money):
        pass

    untouched = [name for name in vars(Money) if name.startswith("__") and name.endswith("__")
                 and name != "__init__" and _is_wrapped(vars(Money)[name])]
    assert untouched == []


def test_skip_typecheck_on_a_special_method():
    @enforced
    class Loose:
        @skip_typecheck
        def __call__(self, n: int) -> Any:
            return n

        @skip_typecheck
        def __getitem__(self, key: int) -> Any:
            return key

        def __contains__(self, key: int) -> bool:
            return True

    loose = Loose()
    assert loose("x") == "x" and loose["k"] == "k" and not _is_wrapped(vars(Loose)["__call__"])
    with pytest.raises(TypeCheckerError):
        "k" in loose


def test_own_typecheck_on_a_special_method_keeps_its_options_and_learns_its_class():
    @enforced
    class Form:
        @typecheck(coerce = True)
        def __call__(self, age: int) -> int:                # looser than the class
            return age

        def __getitem__(self, age: int) -> int:
            return age

        @typecheck
        def __eq__(self, other: Self) -> bool:              # type: ignore[override]  # not one enforced checks itself
            return True

    form = Form()
    assert form("42") == 42 and form == form
    with pytest.raises(TypeCheckerError):
        form["42"]
    with pytest.raises(TypeCheckerError) as e:
        form == 5                                           # asked for by the explicit @typecheck
    assert "For parameter other of <Method Form.__eq__>" in _plain(e.value)


def test_enforced_special_methods_follow_the_class_options():
    @enforced(coerce = True, deep = True, check_return = True)
    class Table:
        def __init__(self) -> None:
            self.rows: dict[int, list[int]] = {}

        def __setitem__(self, row: int, cells: list[int]) -> None:
            self.rows[row] = cells

        def __getitem__(self, row: int) -> list[int]:
            return self.rows[row]

        def __call__(self, row: int) -> int:
            return "many"                                   # type: ignore[return-value]

    table = Table()
    table["1"] = ["2", 3]                                   # coerced, items included
    assert table.rows == {1: [2, 3]} and table[1] == [2, 3]
    with pytest.raises(TypeCheckerError, match = r"cells at index \[1\]"):
        table[2] = [1, "x"]
    with pytest.raises(TypeCheckerError, match = "return value"):
        table(1)


def test_enforced_special_methods_of_a_subclass():
    @enforced
    class Base:
        def __call__(self, n: int) -> Any:
            return n

    class Plain(Base):                                      # not decorated: its own __call__ is unchecked
        def __call__(self, n: int) -> Any:
            return n

    class Inherits(Base):
        pass

    @enforced
    class Checked(Base):
        def __call__(self, n: str) -> Any:                  # type: ignore[override]
            return n

    assert Plain()("x") == "x" and Checked()("x") == "x" and Inherits()(1) == 1
    with pytest.raises(TypeCheckerError):
        Inherits()("x")
    with pytest.raises(TypeCheckerError):
        Checked()(1)


def test_enforced_enum_class_keeps_the_new_it_was_given():
    @enforced
    class Planet(enum.Enum):
        EARTH = (1, 9.8)
        MARS = (2, 3.7)

        def __new__(cls, number: int, gravity: float) -> "Planet":
            member = object.__new__(cls)
            member._value_, member.gravity = number, gravity
            return member

        def heavier(self, other: "Planet") -> bool:
            return self.gravity > other.gravity

    #* Every Enum class carries Enum.__new__ in its own namespace: it is not this class's to wrap.
    assert vars(Planet)["__new__"] is enum.Enum.__new__ and not hasattr(enum.Enum.__new__, "__typecheck_owner__")
    assert Planet(2) is Planet.MARS and Planet["EARTH"].gravity == 9.8
    assert Planet.EARTH.heavier(Planet.MARS) is True
    with pytest.raises(TypeCheckerError):
        Planet.EARTH.heavier(2)
    with pytest.raises(ValueError):
        Planet(3)


def test_enforced_metaclass_call_is_checked_like_any_call():
    @enforced
    class Registry(type):
        def __call__(cls, name: str, *args: Any) -> Any:
            return super().__call__(name, *args)

    class Service(metaclass = Registry):
        def __init__(self, name: Any) -> None:
            self.name = name

    assert Service("db").name == "db"
    with pytest.raises(TypeCheckerError, match = r"<Method Registry\.__call__>"):
        Service(5)


def test_enforced_twice_does_not_wrap_special_methods_twice():
    @enforced
    class Box:
        def __new__(cls, item: int) -> "Box":
            return super().__new__(cls)

        def __call__(self, item: int) -> Any:
            return item

    once = (vars(Box)["__new__"], vars(Box)["__call__"])
    assert enforced(Box) is Box and (vars(Box)["__new__"], vars(Box)["__call__"]) == once


# ═════════════════════════════════════════════════════════════════════════════
#  Self UNDER allow_subclass=False (review finding 8)
# ═════════════════════════════════════════════════════════════════════════════

def test_strict_class_accepts_self_from_a_subclass():
    @enforced(check_return = True, allow_subclass = False)
    class Builder:
        def __init__(self, name: str = "") -> None:
            self.name = name

        def named(self, name: str) -> Self:
            self.name = name
            return self                                     # for a subclass instance, an instance of the subclass

        def after(self, other: Self) -> Self:
            return other

        def broken(self) -> Self:
            return "not a builder"                          # type: ignore[return-value]

        @classmethod
        def make(cls) -> Self:
            return cls()

    class Special(Builder):
        pass

    special = Special()
    assert special.named("a") is special and Special.make().name == ""
    assert special.after(special) is special and Builder().after(special) is special
    for bad in (lambda: special.broken(), lambda: special.after(5), lambda: Builder().after("x")):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Builder'" in _plain(e.value)                # named like the class it stands for


def test_strict_class_is_still_exact_for_its_other_annotations():
    class Animal: ...
    class Dog(Animal): ...

    @enforced(allow_subclass = False)
    class Kennel:
        def take(self, animal: Animal, other: Self | None = None) -> Any:
            return animal

    assert isinstance(Kennel().take(Animal()), Animal)
    with pytest.raises(TypeCheckerError):
        Kennel().take(Dog())


def test_method_with_its_own_strict_typecheck_accepts_self_from_a_subclass():
    class Node:
        @typecheck(allow_subclass = False, check_return = True)
        def me(self) -> Self:
            return self

    class Leaf(Node):
        pass

    leaf = Leaf()
    assert leaf.me() is leaf and Node().me() is not None


# ═════════════════════════════════════════════════════════════════════════════
#  METHODS WITH NOTHING TO CHECK STAY PLAIN  (review finding 27)
# ═════════════════════════════════════════════════════════════════════════════

def test_method_without_annotations_is_left_as_it_was_written():
    def helper(self, a, b = 1):
        return a, b

    @enforced(check_return = True)
    class Mixed:
        def __init__(self, x):                                      # nothing to check here either
            self.x = x

        plain = helper

        def typed(self, a: int) -> int:
            return a

        def returns_only(self) -> int:                              # one annotation is enough to be checked
            return "no"                                             # type: ignore[return-value]

        @classmethod
        def made(cls, x):
            return cls(x)

        @staticmethod
        def free(x):
            return x

    assert vars(Mixed)["plain"] is helper and not _is_wrapped(vars(Mixed)["__init__"])
    assert not _is_wrapped(vars(Mixed)["made"]) and not _is_wrapped(vars(Mixed)["free"])
    assert _is_wrapped(vars(Mixed)["typed"]) and _is_wrapped(vars(Mixed)["returns_only"])
    mixed = Mixed.made("anything")
    assert mixed.plain("a") == ("a", 1) and Mixed.free([]) == [] and mixed.typed(1) == 1
    with pytest.raises(TypeCheckerError):
        mixed.typed("a")
    with pytest.raises(TypeCheckerError):
        mixed.returns_only()
    #* A call that can't be made is Python's own TypeError there, as for any plain method.
    with pytest.raises(TypeError) as e:
        mixed.plain()
    assert type(e.value) is TypeError


def test_unannotated_method_under_future_annotations_and_with_its_own_typecheck():
    namespace: dict[str, Any] = {"enforced": enforced, "typecheck": typecheck}
    exec(compile(
        "from __future__ import annotations\n"
        "@enforced\n"
        "class Later:\n"
        "    def plain(self, a): return a\n"
        "    def typed(self, a: int): return a\n"
        "    @typecheck\n"
        "    def own(self, a): return a\n",
        "<future>", "exec"), namespace)
    Later = namespace["Later"]
    assert not _is_wrapped(vars(Later)["plain"]) and _is_wrapped(vars(Later)["typed"])
    assert _is_wrapped(vars(Later)["own"])                          # asked for by name: wrapped, annotations or not
    assert Later().plain("a") == "a" and Later().own("b") == "b"
    with pytest.raises(TypeCheckerError):
        Later().typed("a")
    with pytest.raises(TypeCheckerError, match = "Missing required argument"):
        Later().own()


def test_annotations_are_not_evaluated_to_find_out_whether_there_are_any():
    @enforced
    class Forward:
        def use(self, later: "NotDefinedYet", n: int = 0) -> Any:    # noqa: F821
            return n

        def other(self, later: NotDefinedAnywhere) -> Any:          # noqa: F821  (evaluating this would raise)
            return later

    assert _is_wrapped(vars(Forward)["use"]) and _is_wrapped(vars(Forward)["other"])
    with pytest.raises(TypeCheckerError, match = "Cannot resolve annotation"):
        Forward().use(1)
