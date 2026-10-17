"""
``enforce``, the class decorator, and ``enforce.exempt``, the mark for a method it is to leave alone.

Also what each decorator refuses: ``typecheck`` a class, ``enforce`` anything that isn't a plain class.
The class tests that predate the split (``__init__``, methods, defaults, ``Self``) are in test_typechecker.py.
The special methods ``enforce`` checks (``__call__``, ``__getitem__``, ``__new__`` ...) are at the end.
"""
from enforced import InvalidDataError, dataclass, enforce, typecheck
from typing import Any, NamedTuple, Self
import abc
import asyncio
import copy
import enforced
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
    """Whether a class attribute is (or holds) a wrapper made by enforced."""
    fn = getattr(member, "__func__", member)
    return "_pv_bootstrap" in getattr(fn, "__globals__", {})


# ═════════════════════════════════════════════════════════════════════════════
#  THE DECORATOR
# ═════════════════════════════════════════════════════════════════════════════

def test_enforced_returns_the_class():
    class Plain:
        pass

    assert enforce(Plain) is Plain
    assert enforce()(Plain) is Plain
    assert enforce(deep = True)(Plain) is Plain


def test_enforced_takes_the_options_of_typecheck_and_nothing_else():
    #* Every option applies to a class: its methods take arguments and return values as functions do.
    options = {"allow_subclass": True, "check_return": False, "convert": True, "coerce": False, "deep": False,
               "on_error": "raise"}
    for decorator in (enforce, typecheck):
        parameters = inspect.signature(decorator).parameters
        assert {name: p.default for name, p in parameters.items() if name != "obj"} == options


def test_enforced_checks_init_methods_static_and_class_methods():
    @enforce
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
        with pytest.raises(InvalidDataError):
            bad()


def test_enforced_messages_name_the_class_and_the_method():
    @enforce
    class Account:
        def __init__(self, owner: str) -> None: ...
        def deposit(self, amount: float) -> None: ...

    with pytest.raises(InvalidDataError) as init:
        Account(1)
    with pytest.raises(InvalidDataError) as method:
        Account("ana").deposit("x")
    assert "For parameter owner of <Class Account>: expected type: 'str', got type 'int' (Value: 1)" in _plain(init.value)
    assert "For parameter amount of <Method Account.deposit>: expected type: 'float'" in _plain(method.value)


@pytest.mark.parametrize("options, value, outcome", [
    ({}, 1, 1.0),                                           # convert is on by default
    ({"convert": False}, 1, InvalidDataError),
    ({}, "1.5", InvalidDataError),                          # coerce is off by default
    ({"coerce": True}, "1.5", 1.5),
    ({}, True, InvalidDataError),                           # a bool is no number
    ])
def test_enforced_passes_convert_and_coerce_to_every_method(options, value, outcome):
    @enforce(**options)
    class Scale:
        def __init__(self, factor: float) -> None:
            self.factor = factor

        def by(self, factor: float) -> float:
            return factor

        @staticmethod
        def of(factor: float) -> float:
            return factor

    for call in (lambda: Scale(value).factor, lambda: Scale(1.0).by(value), lambda: Scale.of(value)):
        if outcome is InvalidDataError:
            with pytest.raises(InvalidDataError):
                call()
        else:
            result = call()
            assert result == outcome and type(result) is float


def test_enforced_allow_subclass_false_is_exact():
    class Animal: ...
    class Dog(Animal): ...

    @enforce
    class Kennel:
        def take(self, animal: Animal) -> Animal: return animal

    @enforce(allow_subclass = False)
    class StrictKennel:
        def take(self, animal: Animal) -> Animal: return animal

    dog = Dog()
    assert Kennel().take(dog) is dog
    assert isinstance(StrictKennel().take(Animal()), Animal)
    with pytest.raises(InvalidDataError):
        StrictKennel().take(dog)


def test_enforced_check_return_covers_methods_not_init():
    @enforce(check_return = True)
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
    with pytest.raises(InvalidDataError, match = "return value"):
        counter.broken()
    with pytest.raises(InvalidDataError, match = "return value"):
        Counter.named()


def test_enforced_without_check_return_ignores_what_methods_return():
    @enforce
    class Counter:
        def broken(self) -> int:
            return "one"                                    # type: ignore[return-value]

    assert Counter().broken() == "one"


def test_enforced_deep_checks_items_in_every_method():
    @enforce(deep = True)
    class Store:
        def __init__(self, stock: dict[str, int]) -> None:
            self.stock = stock

        def restock(self, names: list[str]) -> int:
            return len(names)

    assert Store({"apple": 1}).restock(["a", "b"]) == 2
    with pytest.raises(InvalidDataError, match = r"stock at index \['apple'\]"):
        Store({"apple": "1"})
    with pytest.raises(InvalidDataError, match = r"names at index \[1\]"):
        Store({}).restock(["a", 1])


def test_enforced_self_and_the_class_name_resolve_to_the_class():
    @enforce(check_return = True)
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
        with pytest.raises(InvalidDataError, match = "Node"):
            bad()


def test_enforced_checks_a_bad_default_on_the_first_call():
    @enforce
    class Retry:
        def wait(self, seconds: float = "soon") -> float:   # type: ignore[assignment]
            return seconds

    with pytest.raises(InvalidDataError, match = "default value of parameter seconds"):
        Retry().wait()


def test_enforced_async_and_generator_methods():
    @enforce(check_return = True)
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
    with pytest.raises(InvalidDataError, match = "return value"):
        asyncio.run(feed.fetch(1))
    with pytest.raises(InvalidDataError):
        asyncio.run(feed.ok("1"))
    with pytest.raises(InvalidDataError):
        feed.pages("3")


# ─── what it leaves alone ─────────────────────────────────────────────────────

def test_enforced_leaves_operators_and_other_attributes_alone():
    @enforce
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
    with pytest.raises(InvalidDataError, match = "value"):
        money.amount = "ten"                                # a property is checked: see the tests at the end
    money.amount = 10
    assert money.amount == 10
    assert Money.Inner().method("x") == "x"                 # a class defined inside is not
    assert Money.currency == "EUR" and Money.rates == {"EUR": 1.0}
    assert isinstance(vars(Money)["amount"], property)


def test_enforced_class_without_methods_or_init():
    @enforce
    class Empty:
        pass

    assert isinstance(Empty(), Empty)


def test_enforced_twice_wraps_once():
    @enforce
    class Box:
        def put(self, item: int) -> int: return item

    once = vars(Box)["put"]
    assert enforce(Box) is Box and enforce(deep = True)(Box) is Box
    assert vars(Box)["put"] is once
    assert once.__wrapped__.__name__ == "put" and not _is_wrapped(once.__wrapped__)


def test_enforced_keeps_name_doc_and_signature_of_methods():
    @enforce
    class Box:
        def put(self, item: int, *, quiet: bool = False) -> int:
            """Put an item in."""
            return item

    assert Box.put.__name__ == "put" and Box.put.__doc__ == "Put an item in."
    assert Box.put.__qualname__.endswith("Box.put")
    assert list(inspect.signature(Box.put).parameters) == ["self", "item", "quiet"]


# ─── other kinds of class ─────────────────────────────────────────────────────

def test_enforced_slots_class():
    @enforce
    class Pixel:
        __slots__ = ("x", "y")

        def __init__(self, x: int, y: int) -> None:
            self.x, self.y = x, y

    assert Pixel(1, 2).y == 2
    with pytest.raises(InvalidDataError):
        Pixel(1, "2")


def test_enforced_enum_class():
    @enforce
    class Level(enum.Enum):
        LOW = 1
        HIGH = 2

        def above(self, other: "Level") -> bool:
            return self.value > other.value

    assert Level.HIGH.above(Level.LOW) is True and list(Level) == [Level.LOW, Level.HIGH]
    with pytest.raises(InvalidDataError):
        Level.HIGH.above(1)


def test_enforced_abstract_class_and_its_implementation():
    @enforce
    class Shape(abc.ABC):
        @abc.abstractmethod
        def scaled(self, factor: float) -> "Shape": ...

        def describe(self, prefix: str) -> str:
            return prefix

    @enforce
    class Square(Shape):
        def scaled(self, factor: float) -> "Square":
            return self

    with pytest.raises(TypeError, match = "abstract"):
        Shape()                                             # still abstract
    square = Square()
    assert square.scaled(2) is square and square.describe("a") == "a"
    for bad in (lambda: square.scaled("2"), lambda: square.describe(1)):
        with pytest.raises(InvalidDataError):
            bad()


def test_enforced_generic_class():
    @enforce
    class Stack[T]:
        def __init__(self) -> None:
            self.items: list[T] = []

        def push(self, item: T, times: int = 1) -> None:
            self.items += [item] * times

    stack = Stack[int]()
    stack.push("anything")                                  # an unbound type variable accepts every value
    assert stack.items == ["anything"]
    with pytest.raises(InvalidDataError):
        stack.push(1, times = "2")


def test_enforced_plain_subclass_of_a_dataclass_is_a_plain_class():
    @dataclass
    class Point:
        x: int

    @enforce
    class Labelled(Point):                                  # not a dataclass itself: no fields of its own
        def label(self, prefix: str) -> str:
            return f"{prefix}{self.x}"

    assert Labelled(1).label("p") == "p1"
    with pytest.raises(InvalidDataError):
        Labelled(1).label(1)
    with pytest.raises(InvalidDataError):
        Labelled("1")                                       # the dataclass's own check


# ─── inheritance ──────────────────────────────────────────────────────────────

def test_subclass_inherits_the_checked_methods_but_its_own_are_not_checked():
    @enforce
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
    with pytest.raises(InvalidDataError):
        Child("1")                                          # the inherited __init__ is still checked


def test_enforced_subclass_checks_its_own_methods_and_keeps_the_base_as_it_is():
    @enforce
    class Base:
        def add(self, n: int) -> int:
            return n

    inherited = vars(Base)["add"]

    @enforce(allow_subclass = False, coerce = True)
    class Child(Base):
        def extra(self, n: int) -> int:
            return n

    assert "add" not in vars(Child) and vars(Base)["add"] is inherited
    assert Child().extra("5") == 5                          # the child's options
    with pytest.raises(InvalidDataError):
        Child().add("5")                                    # the base's options: no coercion


# ═════════════════════════════════════════════════════════════════════════════
#  enforce.exempt
# ═════════════════════════════════════════════════════════════════════════════

def test_exempt_leaves_the_method_exactly_as_it_is():
    def render(self, sink: int) -> int:
        return sink

    assert enforce.exempt(render) is render

    @enforce(check_return = True)
    class Report:
        def add(self, line: str) -> None: ...

        draw = render

    assert vars(Report)["draw"] is render and not _is_wrapped(vars(Report)["draw"])
    assert Report().draw("anything") == "anything"         # neither the argument nor the return value
    with pytest.raises(InvalidDataError):
        Report().add(1)                                     # the others are still checked


def test_enforce_is_one_object_that_pickles_and_copies_as_itself():
    import pickle
    assert pickle.loads(pickle.dumps(enforce)) is enforce
    assert copy.copy(enforce) is enforce and copy.deepcopy(enforce) is enforce
    assert repr(enforce) == "<decorator enforced.enforce>"
    assert "Enforce the type annotations of a class" in (enforce.__doc__ or "")
    assert "Enforce the type annotations of a class" in (type(enforce).__call__.__doc__ or "")
    assert "skip_typecheck" not in enforced.__all__ and not hasattr(enforced, "skip_typecheck")


def test_exempt_inside_an_enforced_dataclass():
    @dataclass
    class Row:
        n: int

        def checked(self, x: int) -> int:
            return x

        @enforce.exempt
        def loose(self, x: int) -> int:
            return x

    with pytest.raises(InvalidDataError):
        Row(1).checked("a")
    assert Row(1).loose("a") == "a"


def test_exempt_on_init():
    @enforce
    class Loose:
        @enforce.exempt
        def __init__(self, value: int) -> None:
            self.value = value

        def set(self, value: int) -> None:
            self.value = value

    assert Loose("x").value == "x"
    with pytest.raises(InvalidDataError):
        Loose(1).set("x")


def test_exempt_above_or_below_classmethod_and_staticmethod():
    @enforce
    class Tools:
        @enforce.exempt
        @classmethod
        def above_class(cls, x: int) -> Any: return x

        @classmethod
        @enforce.exempt
        def below_class(cls, x: int) -> Any: return x

        @enforce.exempt
        @staticmethod
        def above_static(x: int) -> Any: return x

        @staticmethod
        @enforce.exempt
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
        with pytest.raises(InvalidDataError):
            getattr(Tools, name)("x")


def test_exempt_method_is_never_looked_at():
    @enforce
    class Notes:
        @enforce.exempt
        def keep(self, text: "NoSuchName", times: int = "many") -> Any:   # type: ignore[assignment]  # noqa: F821
            return text

    assert Notes().keep(1) == 1                             # an annotation that resolves nowhere, a bad default


def test_exempt_does_not_reach_a_subclass_that_overrides():
    @enforce
    class Base:
        @enforce.exempt
        def load(self, source: str) -> Any:
            return source

    @enforce
    class Child(Base):
        def load(self, source: str) -> Any:                 # its own method, not marked
            return source

    @enforce
    class Other(Base):
        pass

    assert Base().load(1) == 1 and Other().load(1) == 1
    with pytest.raises(InvalidDataError):
        Child().load(1)


def test_exempt_on_what_enforced_leaves_alone_anyway_is_harmless():
    @enforce
    class Thing:
        @enforce.exempt
        @property
        def size(self) -> int:
            return "big"                                    # type: ignore[return-value]

        @enforce.exempt
        @functools.cache
        def cached(self, n: int) -> Any:
            return n

    assert Thing().size == "big" and isinstance(vars(Thing)["size"], property)
    assert Thing().cached("x") == "x"
    assert enforce.exempt(len) is len                       # an object that takes no attributes


def test_exempt_below_a_decorator_that_uses_wraps():
    def logged(fn):
        @functools.wraps(fn)                                # copies the mark along with the name
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner

    @enforce
    class Thing:
        @logged
        @enforce.exempt
        def below(self, x: int) -> Any: return x

        @enforce.exempt
        @logged
        def above(self, x: int) -> Any: return x

        @logged
        def checked(self, x: int) -> Any: return x

    assert Thing().below("x") == "x" and Thing().above("x") == "x"
    assert not _is_wrapped(vars(Thing)["below"]) and not _is_wrapped(vars(Thing)["above"])
    with pytest.raises(InvalidDataError):
        Thing().checked("x")


def test_explicit_typecheck_wins_over_exempt():
    @enforce
    class Thing:
        @enforce.exempt
        @typecheck
        def a(self, x: int, other: Self | None = None) -> Any: return x

        @typecheck
        @enforce.exempt
        def b(self, x: int, other: Self | None = None) -> Any: return x

    for call in (Thing().a, Thing().b):
        with pytest.raises(InvalidDataError, match = r"<Method Thing\.[ab]>"):     # checked, and it knows its class
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

    @enforce
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
    with pytest.raises(InvalidDataError):
        form.plain("42")
    assert form.plain(MyInt(3)) == 3
    with pytest.raises(InvalidDataError):
        form.flag(MyInt(3))
    form.once(7)
    assert seen == [7]


def test_own_typecheck_learns_its_class():
    @enforce
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
    with pytest.raises(InvalidDataError) as e:
        node.attach(5)
    assert "For parameter child of <Method Node.attach>" in _plain(e.value)
    with pytest.raises(InvalidDataError, match = "return value"):
        node.attach(node)                                   # returns None for -> Self
    for bad in (lambda: node.attach(node, 5), lambda: Node.above(5), lambda: Node.below(5), lambda: Node.static(5)):
        with pytest.raises(InvalidDataError, match = "Node"):
            bad()


def test_own_typecheck_below_another_decorator_is_not_checked_twice():
    def logged(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)
        return inner

    @enforce
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
    with pytest.raises(InvalidDataError):
        Form().name(1)


def test_typecheck_on_a_method_of_a_class_that_is_not_enforced_still_works():
    class Account:
        @typecheck
        def deposit(self, amount: float) -> float:
            return amount

    assert Account().deposit(1) == 1.0
    with pytest.raises(InvalidDataError):
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
        with pytest.raises(InvalidDataError) as e:
            decorate(Box)                                   # type: ignore[arg-type]
        assert _plain(e.value) == ("typecheck cannot check <Class Box>: it checks functions and methods. "
                                   "A class is checked by @enforce")
    assert isinstance(e.value, TypeError) and Box.__init__ is untouched
    with pytest.raises(InvalidDataError):
        @typecheck
        class Other:                                        # the usual way to meet it
            pass


def test_typecheck_refuses_a_class_inside_another_decorator_too():
    class Box:
        pass

    for wrapped in (staticmethod(Box), classmethod(Box)):
        with pytest.raises(InvalidDataError, match = "typecheck cannot check <Class Box>"):
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
        with pytest.raises(InvalidDataError):
            checked(*bad)


@pytest.mark.parametrize("make_dataclass", [dataclasses.dataclass, dataclass], ids = ["dataclasses", "enforced"])
def test_typecheck_refuses_a_dataclass_and_names_the_decorator_for_it(make_dataclass):
    @make_dataclass
    class Point:
        x: int

    with pytest.raises(InvalidDataError) as e:
        typecheck(Point)                                    # type: ignore[arg-type]
    assert _plain(e.value) == ("typecheck cannot check <Dataclass Point>: it checks functions and methods. "
                               "A dataclass is checked by enforced.dataclass")


@pytest.mark.parametrize("make_dataclass", [
    dataclasses.dataclass, dataclass, dataclasses.dataclass(slots = True, frozen = True), dataclass(slots = True),
    ], ids = ["dataclasses", "enforced", "dataclasses, slots and frozen", "enforced, slots"])
def test_enforced_refuses_a_dataclass(make_dataclass):
    @make_dataclass
    class Point:
        x: int

        def moved(self, dx: int) -> int:
            return self.x + dx

    untouched = vars(Point)["moved"]
    for decorate in (enforce, enforce(), enforce(deep = True)):
        with pytest.raises(InvalidDataError) as e:
            decorate(Point)
        assert _plain(e.value) == ("enforce cannot check <Dataclass Point>: it checks plain classes. "
                                   "A dataclass is checked by enforced.dataclass, its methods included")
    assert vars(Point)["moved"] is untouched


def test_a_method_of_a_dataclass_is_checked_with_typecheck():
    @dataclass
    class Point:
        x: int

        @typecheck
        def moved(self, dx: int) -> int:
            return self.x + dx

    assert Point(1).moved(2) == 3
    with pytest.raises(InvalidDataError):
        Point(1).moved("2")


def test_enforced_refuses_what_is_not_a_class():
    def function(x: int) -> int:
        return x

    class Callable_:
        def __call__(self, x: int) -> int: return x

    told = "it checks classes. A function or a method is checked by @typecheck"
    for target, shown in ((function, "<Function function>"), (len, "<Function len>"), (Callable_(), "<Callable Callable_>"),
                          (5, "5"), ("Box", "'Box'")):
        for decorate in (enforce, enforce(), enforce(coerce = True)):
            with pytest.raises(InvalidDataError) as e:
                decorate(target)                            # type: ignore[call-overload]
            assert _plain(e.value) == f"enforce cannot check {shown}: {told}"
    with pytest.raises(InvalidDataError):
        class Box:
            @enforce                                       # on a method: the wrong decorator
            def put(self, item: int) -> None: ...


# ═════════════════════════════════════════════════════════════════════════════
#  SPECIAL METHODS: THOSE A CALLER HANDS VALUES TO ARE CHECKED, THE REST ARE LEFT ALONE
# ═════════════════════════════════════════════════════════════════════════════

def test_enforced_checks_call():
    @enforce
    class Scale:
        def __call__(self, value: float, *, times: int = 1) -> float:
            return value * times

    scale = Scale()
    assert scale(2) == 2.0 and type(scale(2)) is float      # converted, as for any method
    assert scale(1.5, times = 2) == 3.0
    for bad in (lambda: scale("2"), lambda: scale(1.0, times = "2"), lambda: scale()):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert "<Method Scale.__call__>" in _plain(e.value)
    assert _is_wrapped(vars(Scale)["__call__"]) and callable(scale)


def test_enforced_checks_item_access_and_membership():
    @enforce
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
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert f"<Method Prices.{method}>" in _plain(e.value)
    assert prices.data == {}                                # nothing was stored by the rejected assignments


def test_enforced_checks_new_and_reports_it_as_the_class():
    @enforce(check_return = True)
    class Token:
        def __new__(cls, text: str, weight: float = 1) -> "Token":
            self = super().__new__(cls)
            self.text, self.weight = text, weight
            return self

    token = Token("a")
    assert isinstance(token, Token) and token.weight == 1.0 and type(token.weight) is float   # the default, converted
    assert isinstance(vars(Token)["__new__"], staticmethod)
    with pytest.raises(InvalidDataError) as e:
        Token(1)
    assert "For parameter text of <Class Token>: expected type: 'str', got type 'int' (Value: 1)" in _plain(e.value)
    with pytest.raises(InvalidDataError, match = "Missing required argument for <Class Token>"):
        Token()

    class Sub(Token):                                       # the inherited __new__ is still checked
        pass

    assert type(Sub("a")) is Sub
    with pytest.raises(InvalidDataError):
        Sub(1)


def test_enforced_does_not_check_what_new_returns():
    @enforce(check_return = True)
    class Maybe:
        def __new__(cls, value: int) -> "Maybe":
            return None if value == 0 else super().__new__(cls)     # type: ignore[return-value]

    assert Maybe(0) is None and isinstance(Maybe(1), Maybe)


def test_enforced_checks_new_and_init_each_with_its_own_annotations():
    @enforce
    class Both:
        def __new__(cls, value: int, *rest: Any) -> "Both":
            return super().__new__(cls)

        def __init__(self, value: int, label: str = "") -> None:
            self.value, self.label = value, label

    assert Both(1, "a").label == "a"
    with pytest.raises(InvalidDataError, match = "parameter value"):
        Both("1")
    with pytest.raises(InvalidDataError, match = "parameter label"):
        Both(1, 2)


@enforce
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
        with pytest.raises(InvalidDataError):
            bad()
    #* The helpers of a named tuple build through tuple.__new__, as they always did.
    assert Point._make([1, 2.0]) == point and point._replace(x = 5) == Point(5, 2.0)
    assert pickle.loads(pickle.dumps(point)) == point and copy.deepcopy(point) == point


def test_enforced_checks_what_enter_returns_only_with_check_return():
    def make(**options: Any) -> type:
        @enforce(**options)
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
    with pytest.raises(InvalidDataError, match = r"return value of <Method Session\.__enter__>"):
        use(checked)
    with pytest.raises(InvalidDataError, match = r"return value of <Method Session\.__aenter__>"):
        asyncio.run(use_async(checked))


def test_enforced_exit_is_left_alone():
    @enforce(check_return = True)
    class Session:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, kind: type, error: Exception, trace: int) -> int:   # receives None three times
            return None                                     # type: ignore[return-value]

    with Session() as session:
        assert isinstance(session, Session)
    assert not _is_wrapped(vars(Session)["__exit__"])


def test_enforced_leaves_the_special_methods_python_calls_alone():
    @enforce(check_return = True)
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


def test_exempt_on_a_special_method():
    @enforce
    class Loose:
        @enforce.exempt
        def __call__(self, n: int) -> Any:
            return n

        @enforce.exempt
        def __getitem__(self, key: int) -> Any:
            return key

        def __contains__(self, key: int) -> bool:
            return True

    loose = Loose()
    assert loose("x") == "x" and loose["k"] == "k" and not _is_wrapped(vars(Loose)["__call__"])
    with pytest.raises(InvalidDataError):
        "k" in loose


def test_own_typecheck_on_a_special_method_keeps_its_options_and_learns_its_class():
    @enforce
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
    with pytest.raises(InvalidDataError):
        form["42"]
    with pytest.raises(InvalidDataError) as e:
        form == 5                                           # asked for by the explicit @typecheck
    assert "For parameter other of <Method Form.__eq__>" in _plain(e.value)


def test_enforced_special_methods_follow_the_class_options():
    @enforce(coerce = True, deep = True, check_return = True)
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
    with pytest.raises(InvalidDataError, match = r"cells at index \[1\]"):
        table[2] = [1, "x"]
    with pytest.raises(InvalidDataError, match = "return value"):
        table(1)


def test_enforced_special_methods_of_a_subclass():
    @enforce
    class Base:
        def __call__(self, n: int) -> Any:
            return n

    class Plain(Base):                                      # not decorated: its own __call__ is unchecked
        def __call__(self, n: int) -> Any:
            return n

    class Inherits(Base):
        pass

    @enforce
    class Checked(Base):
        def __call__(self, n: str) -> Any:                  # type: ignore[override]
            return n

    assert Plain()("x") == "x" and Checked()("x") == "x" and Inherits()(1) == 1
    with pytest.raises(InvalidDataError):
        Inherits()("x")
    with pytest.raises(InvalidDataError):
        Checked()(1)


def test_enforced_enum_class_keeps_the_new_it_was_given():
    @enforce
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
    with pytest.raises(InvalidDataError):
        Planet.EARTH.heavier(2)
    with pytest.raises(ValueError):
        Planet(3)


def test_enforced_metaclass_call_is_checked_like_any_call():
    @enforce
    class Registry(type):
        def __call__(cls, name: str, *args: Any) -> Any:
            return super().__call__(name, *args)

    class Service(metaclass = Registry):
        def __init__(self, name: Any) -> None:
            self.name = name

    assert Service("db").name == "db"
    with pytest.raises(InvalidDataError, match = r"<Method Registry\.__call__>"):
        Service(5)


def test_enforced_twice_does_not_wrap_special_methods_twice():
    @enforce
    class Box:
        def __new__(cls, item: int) -> "Box":
            return super().__new__(cls)

        def __call__(self, item: int) -> Any:
            return item

    once = (vars(Box)["__new__"], vars(Box)["__call__"])
    assert enforce(Box) is Box and (vars(Box)["__new__"], vars(Box)["__call__"]) == once


# ═════════════════════════════════════════════════════════════════════════════
#  Self UNDER allow_subclass=False (review finding 8)
# ═════════════════════════════════════════════════════════════════════════════

def test_strict_class_takes_self_for_the_exact_class_of_the_instance():
    @enforce(check_return = True, allow_subclass = False)
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

    special, builder = Special(), Builder()
    assert special.named("a") is special and Special.make().name == "" and type(Special.make()) is Special
    assert special.after(special) is special and builder.after(builder) is builder and type(Builder.make()) is Builder
    #* Self is the class of the instance the method is called on (review finding 28), and strict
    #* mode asks for exactly that class: an instance of the base class is no Special, and an
    #* instance of a subclass is not exactly a Builder. (Until the class of the instance was known,
    #* Self stood for "Builder or a subclass" here, and both of these passed.)
    for bad, named in ((lambda: special.broken(), "Special"), (lambda: special.after(5), "Special"),
                       (lambda: special.after(builder), "Special"), (lambda: builder.after("x"), "Builder"),
                       (lambda: builder.after(special), "Builder")):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert f"{named}'" in _plain(e.value)               # named like the class Self is in that call


def test_strict_class_is_still_exact_for_its_other_annotations():
    class Animal: ...
    class Dog(Animal): ...

    @enforce(allow_subclass = False)
    class Kennel:
        def take(self, animal: Animal, other: Self | None = None) -> Any:
            return animal

    assert isinstance(Kennel().take(Animal()), Animal)
    with pytest.raises(InvalidDataError):
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

    @enforce(check_return = True)
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
    with pytest.raises(InvalidDataError):
        mixed.typed("a")
    with pytest.raises(InvalidDataError):
        mixed.returns_only()
    #* A call that can't be made is Python's own TypeError there, as for any plain method.
    with pytest.raises(TypeError) as e:
        mixed.plain()
    assert type(e.value) is TypeError


def test_unannotated_method_under_future_annotations_and_with_its_own_typecheck():
    namespace: dict[str, Any] = {"enforce": enforce, "typecheck": typecheck}
    exec(compile(
        "from __future__ import annotations\n"
        "@enforce\n"
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
    with pytest.raises(InvalidDataError):
        Later().typed("a")
    with pytest.raises(InvalidDataError, match = "Missing required argument"):
        Later().own()


def test_annotations_are_not_evaluated_to_find_out_whether_there_are_any():
    @enforce
    class Forward:
        def use(self, later: "NotDefinedYet", n: int = 0) -> Any:    # noqa: F821
            return n

        def other(self, later: NotDefinedAnywhere) -> Any:          # noqa: F821  (evaluating this would raise)
            return later

    assert _is_wrapped(vars(Forward)["use"]) and _is_wrapped(vars(Forward)["other"])
    with pytest.raises(InvalidDataError, match = "Cannot resolve annotation"):
        Forward().use(1)


# ═════════════════════════════════════════════════════════════════════════════
#  Self IS THE CLASS OF THE INSTANCE THE METHOD IS CALLED ON (review finding 28)
# ═════════════════════════════════════════════════════════════════════════════

def test_self_is_the_class_of_the_instance_the_method_is_called_on():
    #* This was the known issue: Self stood for the class that defines the method, so a method
    #* called on a Child could return a plain Base for "-> Self".
    @enforce(check_return = True)
    class Base:
        def clone(self) -> Self:
            return Base()                                           # type: ignore[return-value]

    class Child(Base):
        pass

    assert type(Base().clone()) is Base
    for _ in range(3):                                              # the first call, and the compiled check
        with pytest.raises(InvalidDataError) as e:
            Child().clone()                                         # a Base where Self is Child
    assert "For return value of <Method Base.clone>: expected type: " in _plain(e.value)
    assert "Child', got type" in _plain(e.value) and e.value.problems[0].expected is Child


def _family(**options: Any) -> tuple[type, type, type]:
    """A class whose methods use ``Self`` in every position, a subclass of it and a subclass of that."""
    @enforce(check_return = True, **options)
    class Base:
        def __init__(self, tag: str = "") -> None:
            self.tag = tag

        def same(self) -> Self:
            return self

        def fresh(self) -> Self:
            return type(self)()

        def base(self) -> Self:
            return Base()                                           # type: ignore[return-value]

        def merge(self, other: Self, *more: Self, last: Self | None = None) -> Any:
            return other

        def scaled(self, other: Self, factor: float = 2) -> Any:
            return factor

        def maybe(self, other: Self | None = None, kind: type[Self] | None = None) -> Self | None:
            return other

        def group(self, others: list[Self], by: dict[str, Self] | None = None) -> list[Self]:
            return others

        @classmethod
        def make(cls, like: Self | None = None) -> Self:
            return cls()

        @classmethod
        def wrong(cls) -> Self:
            return Base()                                           # type: ignore[return-value]

        @staticmethod
        def any_of(one: Self) -> Any:                               # no instance, no class: Self is the class it is in
            return one

        async def later(self, other: Self) -> Self:
            return other

        def each(self, other: Self):
            yield other

    class Child(Base):
        pass

    class Grandchild(Child):
        pass

    return Base, Child, Grandchild


@pytest.mark.parametrize("options", [{}, {"deep": True}, {"coerce": True}, {"convert": False}], ids = str)
def test_self_follows_the_class_of_each_call(options):
    Base, Child, Grandchild = _family(**options)
    base, child, grand = Base(), Child(), Grandchild()
    for _ in range(3):                                              # bootstrap, then the compiled wrappers
        for one in (base, child, grand):
            assert one.same() is one and type(one.fresh()) is type(one)
            assert one.merge(one) is one and one.merge(one, one, last = one) is one and one.maybe() is None
            assert one.maybe(one, type(one)) is one and one.group([one], {"a": one}) == [one]
            assert type(type(one).make()) is type(one) and type(one.make(one)) is type(one)
            assert asyncio.run(one.later(one)) is one and list(one.each(one)) == [one]
        #* A subclass instance is one of its base class: accepted where Self is the base.
        assert base.merge(child, grand) is child and child.merge(grand) is grand and base.maybe(grand, Child) is grand
        assert type(base.base()) is Base and type(Base.wrong()) is Base
        #* An instance of the base class is not one of the subclass.
        for bad in (child.base, grand.base, Child.wrong, Grandchild.wrong,
                    lambda: child.merge(base), lambda: grand.merge(child), lambda: child.merge(child, base),
                    lambda: child.merge(child, last = base), lambda: child.merge(other = base),
                    lambda: child.maybe(base), lambda: child.maybe(None, Base), lambda: grand.maybe(None, Child),
                    lambda: Child.make(base), lambda: child.make(base), lambda: asyncio.run(child.later(base)),
                    lambda: child.each(base), lambda: child.scaled(base)):
            with pytest.raises(InvalidDataError):
                bad()
        assert Base.any_of(child) is child and Child.any_of(base) is base        # a static method: Self is Base
    #* Conversion still happens next to it, and a default is converted for every class.
    if options.get("convert", True):
        assert type(child.scaled(child, 3)) is float and type(child.scaled(child)) is float and type(base.scaled(base)) is float


def test_self_with_deep_points_at_the_item():
    Base, Child, _ = _family(deep = True)
    child = Child()
    with pytest.raises(InvalidDataError) as e:
        child.group([child, Base(), child], {"a": Base()})
    assert [p.parameter for p in e.value.problems] == ["others[1]", "by['a']"]
    assert all(p.expected is Child for p in e.value.problems)
    with pytest.raises(InvalidDataError) as e:
        Base().group([5])
    assert e.value.problems[0].expected is Base
    assert Base().group([child]) == [child]


def test_self_messages_name_the_class_of_the_call():
    Base, Child, _ = _family()
    child = Child()
    with pytest.raises(InvalidDataError) as e:
        child.merge(Base())
    text = _plain(e.value)
    assert "For parameter other of <Method Base.merge>: expected type: " in text and "Child', got type" in text
    with pytest.raises(InvalidDataError) as e:
        child.merge(child, Base(), 5)
    assert [p.parameter for p in e.value.problems] == ["more[0]", "more[1]"]
    with pytest.raises(InvalidDataError) as e:
        child.maybe(None, Base)
    assert "For parameter kind of <Method Base.maybe>" in _plain(e.value)
    with pytest.raises(InvalidDataError, match = "Missing required argument for <Method Base.merge>: other"):
        child.merge()
    with pytest.raises(InvalidDataError, match = "unexpected keyword argument"):
        child.merge(child, nothing = 1)


def test_self_in_strict_mode_is_exactly_the_class_of_the_call():
    Base, Child, Grandchild = _family(allow_subclass = False)
    base, child, grand = Base(), Child(), Grandchild()
    for _ in range(3):
        for one in (base, child, grand):
            assert one.same() is one and one.merge(one, one) is one and one.maybe(one, type(one)) is one
            assert type(type(one).make(one)) is type(one) and one.group([one]) == [one]
        for bad in (lambda: base.merge(child), lambda: child.merge(base), lambda: child.merge(grand),
                    lambda: child.maybe(grand), lambda: child.maybe(None, Grandchild), lambda: child.maybe(None, Base),
                    child.base, Child.wrong, lambda: Child.make(grand)):
            with pytest.raises(InvalidDataError):
                bad()


@pytest.mark.usefixtures("compiled_at_once")
def test_one_wrapper_serves_every_class_where_self_stands_alone():
    #* "other: Self" and "-> Self" are tested against the class of the first argument, in the one
    #* compiled wrapper: no wrapper per class, and a call on a subclass costs what one on the class does.
    Base, Child, Grandchild = _family()
    for one in (Base(), Child(), Grandchild()):
        for _ in range(3):
            assert one.same() is one and one.fresh() is not one and asyncio.run(one.later(one)) is one
    for name in ("same", "fresh", "later"):
        wrapper = vars(Base)[name]
        assert "_pv_c0" in wrapper.__enforced_source__ and "_pv_me" not in wrapper.__enforced_source__
        #* The first call of all was made before anything was compiled, and went by the class.
        assert set(wrapper.__globals__["_pv_checker"].family or ()) <= {Child, Grandchild}
    assert "isinstance(_pv_r, _pv_c0)" in vars(Base)["same"].__enforced_source__
    #* Anything that is no instance of the class in the place of self: checked as before, Self being the class.
    assert Base.merge(Child(), Child()) is not None
    for bad in (lambda: Base.merge(5, 5), lambda: Base.same(5), lambda: asyncio.run(Base.later(5, 5))):
        with pytest.raises(InvalidDataError) as e:
            bad()
        assert e.value.problems[0].expected is Base


@pytest.mark.usefixtures("compiled_at_once")
def test_a_wrapper_per_class_where_self_is_part_of_an_annotation():
    import enforced._typechecker._self_routing as _self_routing
    Base, Child, Grandchild = _family()
    child, grand = Child(), Grandchild()
    for _ in range(3):
        assert child.maybe(child) is child and grand.maybe(grand) is grand and type(Child.make()) is Child
    wrapper = vars(Base)["maybe"]
    assert "_pv_me" in wrapper.__enforced_source__ and wrapper.__globals__["_pv_me"] is Base
    #* The family knows a class by its id and holds its wrapper weakly: the class holds the wrapper.
    family = wrapper.__globals__["_pv_subs"]
    assert set(family) == {id(Child), id(Grandchild)}
    for_child = family[id(Child)]()
    assert for_child.__globals__["_pv_me"] is Child and for_child in vars(Child)[_self_routing._OF_CLASS].values()
    assert for_child.__globals__["_pv_subs"] is family             # one family for all of them
    assert family is wrapper.__globals__["_pv_checker"].family is for_child.__globals__["_pv_checker"].family
    assert "__enforced_source__" in vars(for_child)                 # each is compiled like any wrapper
    assert set(vars(Base)["make"].__func__.__globals__["_pv_subs"]) == {id(Child)}
    assert _self_routing._OF_CLASS not in vars(Base)                          # the class that defines the method needs none


def _made_and_dropped(use: Any, count: int = 40) -> int:
    """How many of ``count`` classes, each made, handed to ``use`` and dropped, are alive afterwards."""
    import gc
    import weakref
    alive = []
    for i in range(count):
        made = use(i)
        alive.append(weakref.ref(made))
        del made
    #* More than once: the first pass frees the functions, and with them the cached signatures
    #* that name the class; the class itself goes with the pass after that.
    for _ in range(3):
        gc.collect()
    return sum(ref() is not None for ref in alive)


@pytest.mark.parametrize("options", [{}, {"deep": True}, {"allow_subclass": False}], ids = str)
def test_a_class_made_at_run_time_goes_when_it_is_dropped(options):
    #* Review finding 36: a method that uses Self kept a wrapper for each class it was called on,
    #* and the annotation written for that class sat in the annotation cache. 300 classes made in a
    #* loop and used once were all still alive.
    Base, _, _ = _family(**options)

    def use(i: int) -> type:
        Sub = type(f"Sub{i}", (Base,), {})
        one = Sub()
        assert one.maybe(one, Sub) is one and one.same() is one and one.merge(one, one, last = one) is one
        assert type(Sub.make(one)) is Sub and one.group([one], {"a": one}) == [one]
        for bad in (lambda: one.maybe(Base()), lambda: one.merge(Base()), one.base, Sub.wrong):
            with pytest.raises(InvalidDataError):
                bad()
        if options.get("deep"):
            with pytest.raises(InvalidDataError):
                one.group([Base()])
        return Sub

    assert _made_and_dropped(use) == 0
    for name in ("maybe", "group", "merge"):
        assert vars(Base)[name].__globals__["_pv_checker"].family == {}        # and the family has let go of them


def test_a_dataclass_made_at_run_time_goes_when_it_is_dropped():
    @dataclass
    class Node:
        parent: Self | None = None

    def use(i: int) -> type:
        Leaf = type(f"Leaf{i}", (Node,), {})
        leaf = Leaf()
        assert Leaf(leaf).parent is leaf
        leaf.parent = Leaf()
        for bad in (lambda: Leaf(Node()), lambda: setattr(leaf, "parent", Node())):
            with pytest.raises(InvalidDataError):
                bad()
        return Leaf

    assert _made_and_dropped(use) == 0


def test_a_local_class_in_a_plain_annotation_goes_too():
    #* A plain class is its own answer and has no place in the annotation cache, where it was kept.
    def use(i: int) -> type:
        class Local:
            pass

        @typecheck(check_return = True)
        def f(x: Local) -> Local:
            return x

        assert type(f(Local())) is Local
        with pytest.raises(InvalidDataError) as e:
            f(i)
        assert "Local'" in _plain(e.value)
        return Local

    assert _made_and_dropped(use) == 0


def test_a_class_that_takes_no_attribute_is_still_routed(monkeypatch):
    import enforced._typechecker._self_routing as _self_routing
    held: Any = type(_self_routing._HELD_FOR_CLASSES)(maxlen = 4)
    monkeypatch.setattr(_self_routing, "_HELD_FOR_CLASSES", held)

    class Closed(type):
        def __setattr__(cls, name: str, value: Any) -> None:
            raise AttributeError("this class takes no attribute")

    Base, _, _ = _family()
    for i in range(10):
        Sub = Closed(f"Sub{i}", (Base,), {})
        one = Sub()
        assert one.maybe(one) is one and _self_routing._OF_CLASS not in vars(Sub)
        with pytest.raises(InvalidDataError):
            one.maybe(Base())
    assert len(held) == 4                                           # the last few wrappers, held by themselves


@pytest.mark.usefixtures("compiled_at_once")
def test_a_method_without_self_in_what_is_checked_is_compiled_as_ever():
    #* "-> Self" without check_return is the usual fluent method: nothing of it is checked, so
    #* nothing is routed. Its wrapper is the one any method of that shape gets.
    @enforce
    class Fluent:
        def named(self, name: str) -> Self:
            return self

    @enforce
    class Plain:
        def named(self, name: str) -> "Plain":
            return self

    class Child(Fluent):
        pass

    for one in (Fluent(), Child(), Plain()):
        assert one.named("a") is one and one.named("b") is one
    assert vars(Fluent)["named"].__enforced_source__ == vars(Plain)["named"].__enforced_source__
    assert vars(Fluent)["named"].__code__ is vars(Plain)["named"].__code__
    #* Nothing was made for Self: no family of wrappers, and no name for it in the wrapper.
    assert vars(Fluent)["named"].__globals__["_pv_checker"].family is None
    assert not {"_pv_subs", "_pv_me", "_pv_owner"} & set(vars(Fluent)["named"].__globals__)


def test_self_in_a_class_method_and_in_new():
    @enforce(check_return = True)
    class Shape:
        registry: list = []

        def __new__(cls, like: Self | None = None) -> Self:
            return super().__new__(cls)

        def __init__(self, like: Self | None = None) -> None:
            self.like = like

        @classmethod
        def twin(cls, of: Self) -> Self:
            return cls(of)

    class Circle(Shape):
        pass

    for _ in range(3):
        assert type(Circle(Circle())) is Circle and type(Shape(Circle())) is Shape
        assert type(Circle.twin(Circle())) is Circle and type(Circle().twin(Circle())) is Circle
        for bad in (lambda: Circle(Shape()), lambda: Circle.twin(Shape()), lambda: Circle(5)):
            with pytest.raises(InvalidDataError) as e:
                bad()
    assert "of <Class Shape>" in _plain(e.value)


def test_self_with_typecheck_function_and_a_method_decorated_on_its_own():
    from enforced import typecheck_function

    class Base:
        def merge(self, other: Self) -> Self:
            return other

        @typecheck(check_return = True)
        def own(self, other: Self | None = None) -> Self | None:
            return other

    class Child(Base):
        pass

    base, child = Base(), Child()
    for _ in range(2):
        assert typecheck_function(child.merge, (child,), check_return = True) is child
        assert typecheck_function(Base.merge, (child, child)) is child and child.own(child) is child and child.own() is None
        for bad in (lambda: typecheck_function(child.merge, (base,)), lambda: child.own(base),
                    lambda: typecheck_function(Base.merge, (child, base))):
            with pytest.raises(InvalidDataError):
                bad()
        assert typecheck_function(base.merge, (child,)) is child and base.own(child) is child


def test_self_from_several_threads():
    import threading
    Base, Child, Grandchild = _family()
    classes = [Base, Child, Grandchild] + [type(f"T{i}", (Child,), {}) for i in range(5)]
    wrong: list[Any] = []
    start = threading.Barrier(8)

    def work(n: int) -> None:
        start.wait()
        try:
            for i in range(200):
                cls = classes[(n + i) % len(classes)]
                one = cls()
                if one.maybe(one) is not one or one.same() is not one or type(cls.make()) is not cls:
                    wrong.append((cls, "accepted wrongly"))
                if cls is not Base:
                    try:
                        one.maybe(Base())
                        wrong.append((cls, "not rejected"))
                    except InvalidDataError:
                        pass
        except BaseException as e:
            wrong.append(e)

    threads = [threading.Thread(target = work, args = (n,)) for n in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert wrong == []


def test_self_in_a_dataclass_field_of_a_subclass_that_is_not_decorated():
    @dataclass
    class Node:
        parent: Self | None = None
        twin: Self | None = None
        weight: float = 1

    class Leaf(Node):                                               # plain: it inherits __init__ and the checks
        pass

    @dataclass
    class Branch(Node):                                             # decorated: its own checks, Self is Branch
        pass

    leaf, node, branch = Leaf(), Node(), Branch()
    for _ in range(3):
        assert Leaf(leaf).parent is leaf and Node(leaf).parent is leaf and Branch(branch, branch).twin is branch
        assert type(Leaf(leaf, None, 2).weight) is float
        for bad in (lambda: Leaf(node), lambda: Leaf(None, node), lambda: Branch(node), lambda: Leaf(leaf, leaf, "x")):
            with pytest.raises(InvalidDataError):
                bad()
        leaf.twin = Leaf()
        node.parent = leaf
        with pytest.raises(InvalidDataError) as e:
            leaf.parent = node                                      # on assignment too: Self is Leaf
        assert "Field Node.parent of <Dataclass Node>" in _plain(e.value) and "Leaf'" in _plain(e.value)
        with pytest.raises(InvalidDataError):
            branch.parent = node
        with pytest.raises(InvalidDataError, match = "weight"):
            leaf.weight = "heavy"
        leaf.weight = 3
        assert type(leaf.weight) is float and leaf.parent is None


# ═════════════════════════════════════════════════════════════════════════════
#  PROPERTIES OF AN ENFORCED CLASS
# ═════════════════════════════════════════════════════════════════════════════

def _account(**options: Any) -> type:
    @enforce(**options)
    class Account:
        """Properties in every form: read-only, with a setter, with a deleter, cached, and without annotations."""
        def __init__(self) -> None:
            self._balance: Any = 0.0
            self._owner: Any = "ana"
            self.reads = 0

        @property
        def balance(self) -> float:
            """What is on the account."""
            self.reads += 1
            return self._balance

        @balance.setter
        def balance(self, value: float) -> None:
            self._balance = value

        @balance.deleter
        def balance(self) -> None:
            self._balance = 0.0

        @property
        def owner(self) -> str:
            return self._owner

        @functools.cached_property
        def report(self) -> str:
            return self._owner

        @property
        def loose(self):
            return self._owner

        @loose.setter
        def loose(self, value):
            self._owner = value

        @property
        def twin(self) -> Self:
            return self._owner

        @twin.setter
        def twin(self, other: Self | None) -> None:
            self._owner = other

    return Account


def test_what_is_assigned_to_a_property_is_checked():
    Account = _account()
    account = Account()
    account.balance = 2.5
    account.balance = 3                                             # converted, like any argument
    assert account.balance == 3.0 and type(account._balance) is float
    for _ in range(2):
        with pytest.raises(InvalidDataError) as e:
            account.balance = "a lot"
    assert "For parameter value of <Method Account.balance>: expected type: 'float', got type 'str'" in _plain(e.value)
    del account.balance
    assert account.balance == 0.0
    with pytest.raises(AttributeError):
        account.owner = "bo"                                        # no setter: Python's own answer, as ever


def test_what_a_property_returns_is_checked_with_check_return():
    account = _account()()
    account._balance, account._owner = "broken", 5
    assert account.balance == "broken" and account.owner == 5 and account.report == 5      # not asked for: not checked
    account = _account(check_return = True)()
    account._balance = 2
    assert account.balance == 2.0 and type(account.balance) is float
    account._balance, account._owner = "broken", 5
    for read, name in ((lambda: account.balance, "balance"), (lambda: account.owner, "owner"), (lambda: account.report, "report")):
        with pytest.raises(InvalidDataError) as e:
            read()
        assert f"For return value of <Method Account.{name}>" in _plain(e.value)
    account._owner = "cy"
    assert account.report == "cy" and account.report == "cy" and vars(account)["report"] == "cy"       # cached as before


def test_a_property_stays_the_property_it_was():
    for options in ({}, {"check_return": True}):
        Account = _account(**options)
        balance, report = vars(Account)["balance"], vars(Account)["report"]
        assert type(balance) is property and balance.__doc__ == "What is on the account." and balance.fdel is not None
        assert type(report) is functools.cached_property and report.attrname == "report"
        #* Only an accessor with something to check is wrapped: a getter has nothing without check_return.
        assert _is_wrapped(balance.fset) and _is_wrapped(balance.fget) is bool(options) and not _is_wrapped(balance.fdel)
        assert _is_wrapped(report.func) is bool(options)
        assert not _is_wrapped(vars(Account)["loose"].fget) and not _is_wrapped(vars(Account)["loose"].fset)
        account = Account()
        account.loose = 5
        assert account.loose == 5


def test_self_in_a_property_is_the_class_of_the_instance():
    Account = _account(check_return = True)

    class Savings(Account):
        pass

    one, other, plain = Savings(), Savings(), Account()
    one.twin = other
    assert one.twin is other
    one.twin = None
    with pytest.raises(InvalidDataError):
        one.twin                                                    # None is no Savings
    with pytest.raises(InvalidDataError):
        one.twin = plain                                            # an Account is no Savings
    plain.twin = one                                                # a Savings is an Account


def test_properties_that_are_left_alone():
    @enforce(check_return = True)
    class Thing:
        @enforce.exempt
        @property
        def above(self) -> int:
            return "a"                                              # type: ignore[return-value]

        @property
        @enforce.exempt
        def below(self) -> int:
            return "b"                                              # type: ignore[return-value]

        @property
        def half(self) -> int:
            return 1

        @half.setter
        @enforce.exempt
        def half(self, value: int) -> None:
            self.kept = value

        @property
        @typecheck(check_return = True, coerce = True)
        def own(self) -> float:
            return 1                                                # type: ignore[return-value]

        @own.setter
        @typecheck(coerce = True)
        def own(self, value: int) -> None:
            self.kept = value

    thing = Thing()
    assert thing.above == "a" and thing.below == "b"
    thing.half = "anything"
    assert thing.kept == "anything" and thing.half == 1
    thing.own = "42"                                                # its own options: parsed
    assert thing.kept == 42 and thing.own == 1.0
    with pytest.raises(InvalidDataError, match = "<Method Thing.own>"):
        thing.own = "many"


def test_enforce_class_and_a_property_added_by_a_subclass():
    from enforced import enforce_class

    class Plain:
        @property
        def size(self) -> int:
            return self._size

        @size.setter
        def size(self, value: int) -> None:
            self._size = value

    class Child(Plain):                                             # made before the base is enforced: it inherits the property
        pass

    enforce_class(Plain)
    for cls in (Plain, Child):
        one = cls()
        one.size = 3
        with pytest.raises(InvalidDataError):
            one.size = "big"
        assert one.size == 3


class PickledAccount:
    """At module level: pickle finds an origin again by its name."""
    def __init__(self) -> None:
        self._balance: Any = "broken"

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = value

    @functools.cached_property
    def label(self) -> str:
        return self._balance * 2

    def deposit(self, amount: float) -> None: ...


enforce(PickledAccount, check_return = True)


def test_a_problem_from_a_property_keeps_its_origin_when_pickled():
    #* Review finding 41: the name of a property leads to the property, not to a function, and
    #* getter and setter share it. The origin arrived as a stand-in that showed its repr.
    account = PickledAccount()
    cases = {"fset": lambda: setattr(account, "balance", "a lot"), "fget": lambda: account.balance,
             "func": lambda: setattr(account, "_balance", 5) or account.label, None: lambda: account.deposit("x")}
    for which, fail in cases.items():
        with pytest.raises(InvalidDataError) as e:
            fail()
        problem = e.value.problems[0]
        back = pickle.loads(pickle.dumps(e.value))
        assert back.problems[0].origin is problem.origin and inspect.isfunction(problem.origin), which
        assert str(back) == str(e.value) and back.problems[0].parameter == problem.parameter
    setter, getter = vars(PickledAccount)["balance"].fset.__wrapped__, vars(PickledAccount)["balance"].fget.__wrapped__
    assert setter is not getter and setter.__qualname__ == getter.__qualname__        # told apart all the same


def test_a_pickled_origin_reads_nothing_but_an_accessor():
    from enforced._typechecker._errors import _find_origin
    for name in ("__class__", "__doc__", "getter", "__init__"):
        with pytest.raises(ValueError):
            _find_origin(__name__, "PickledAccount.balance", name)
