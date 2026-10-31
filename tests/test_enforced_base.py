"""
``Enforced``: the base class that checks every class derived from it, as ``@enforce`` checks one,
with the options given as class keywords and handed down to subclasses.
"""
from enforced import Enforced, InvalidDataError, InvalidDataWarning, dataclass, enforce, enforce_class, validate
from typing import Any, ClassVar, Self, no_type_check
import annotationlib
import dataclasses
import pickle
import warnings
import pytest

import enforced._environment as environment


def _raised(fn, *args, **kwargs) -> InvalidDataError:
    with pytest.raises(InvalidDataError) as info:
        fn(*args, **kwargs)
    return info.value


class Account(Enforced, check_return = True):
    def __init__(self, owner: str, balance: float = 0) -> None:
        self.owner, self.balance = owner, balance

    def deposit(self, amount: float) -> float:
        self.balance += amount
        return self.balance

    def broken(self) -> int:
        return "no"                                                  # type: ignore[return-value]

    @staticmethod
    def parse(raw: str) -> "Account":
        return Account(raw)

    @classmethod
    def opened(cls, owner: str) -> Self:
        return cls(owner)

    @property
    def limit(self) -> float:
        return 100.0

    @limit.setter
    def limit(self, value: float) -> None:
        self.kept = value


class Savings(Account):
    def withdraw(self, amount: float) -> float:
        return "x"                                                   # type: ignore[return-value]


class Lenient(Account, coerce = True):
    def take(self, n: int) -> int:
        return n


# ── what is checked ──────────────────────────────────────────────────────────

def test_the_class_itself_is_checked_like_an_enforced_one():
    assert Account("ana").deposit(1) == 1.0 and type(Account("ana").deposit(1)) is float
    assert "<Class Account>" in str(_raised(Account, 5))
    assert "<Method Account.deposit>" in str(_raised(Account("a").deposit, "x"))
    assert "return value" in str(_raised(Account("a").broken))               # check_return=True
    assert type(Account.parse("a")) is Account and type(Savings.opened("a")) is Savings
    _raised(Account.parse, 1)
    account = Account("a")
    account.limit = 5
    assert account.kept == 5.0                                                # the setter converts
    _raised(setattr, account, "limit", "high")


def test_a_subclass_is_checked_without_a_decorator():
    assert "<Method Savings.withdraw>" in str(_raised(Savings("a").withdraw, 1))   # check_return, from Account
    _raised(Savings("a").withdraw, "x")
    _raised(Savings("a").deposit, "x")                                         # what it inherits, as before
    assert Savings.deposit is Account.deposit                                  # not wrapped a second time

    class Grandchild(Savings):
        def more(self, n: int) -> None: ...
    _raised(Grandchild("a").more, "x")


def test_options_are_handed_down_and_each_one_given_replaces_that_one():
    assert Account.__enforced_options__ == (True, True, True, False, False, "raise", InvalidDataError)
    assert Savings.__enforced_options__ == Account.__enforced_options__
    assert Lenient.__enforced_options__ == (True, True, True, True, False, "raise", InvalidDataError)
    assert Lenient("a").take("42") == 42                                       # coerce=True, its own
    assert "return value" in str(_raised(Lenient("a").broken))                 # check_return=True, inherited

    class Strict(Lenient, coerce = False, allow_subclass = False):
        def take2(self, n: int) -> int:
            return n
    assert Strict.__enforced_options__ == (False, True, True, False, False, "raise", InvalidDataError)
    _raised(Strict("a").take2, "42")

    class Plain(Enforced):
        def f(self, x: int) -> int:
            return "x"                                                       # type: ignore[return-value]
    assert Plain.__enforced_options__ == (True, False, True, False, False, "raise", InvalidDataError)
    assert Plain().f(1) == "x"                                                 # no check_return by default


def test_deep_and_warn_as_class_keywords():
    class Rows(Enforced, deep = True, on_error = "warn"):
        def load(self, xs: list[int]) -> int:
            return len(xs)

    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        assert Rows().load([1, "two"]) == 2
    assert [w.category for w in caught] == [InvalidDataWarning] and "xs at index [1]" in str(caught[0].message)


def test_special_methods_and_what_is_left_alone():
    class Table(Enforced):
        def __getitem__(self, key: str) -> int:
            return 1

        def __eq__(self, other: "Table") -> bool:                            # type: ignore[override]
            return other is self

        @enforce.exempt
        def raw(self, x: int) -> Any:
            return x

        @validate(coerce = True)
        def own(self, x: int) -> int:
            return x

        def untyped(self, x):
            return x

    table = Table()
    _raised(table.__getitem__, 1)
    assert (table == "x") is False                                           # Python calls __eq__ with anything
    assert table.raw("x") == "x" and table.own("7") == 7 and table.untyped("y") == "y"
    assert "__wrapped__" not in vars(vars(Table)["untyped"])


def test_no_type_check_on_a_subclass_and_the_off_switch(monkeypatch):
    @no_type_check
    class Loose(Enforced):
        def f(self, x: int) -> int:
            return x
    assert Loose().f("x") == "x"

    monkeypatch.setattr(environment, "VALIDATION_OFF", True)

    class Off(Enforced):
        def f(self, x: int) -> int:
            return x
    assert Off().f("x") == "x" and "__wrapped__" not in vars(vars(Off)["f"])
    monkeypatch.setattr(environment, "VALIDATION_OFF", False)

    class On(Off):                                                           # asks again
        def g(self, x: int) -> int:
            return x
    _raised(On().g, "x")
    assert On().f("x") == "x"                                                # what it inherits stays as it was


def test_a_local_class_with_string_annotations():
    class Unit:
        pass

    class Measured(Enforced):
        def set(self, unit: "Unit") -> "Unit":
            return unit

    assert isinstance(Measured().set(Unit()), Unit)
    _raised(Measured().set, 5)


# ── the class keywords and other bases ───────────────────────────────────────

def test_an_unknown_on_error_and_an_unknown_keyword_are_refused_at_the_class():
    with pytest.raises(InvalidDataError, match = "on_error"):
        type("Bad", (Enforced,), {}, on_error = "log")
    with pytest.raises(TypeError):
        type("Bad", (Enforced,), {}, colour = 1)


def test_it_cooperates_with_a_library_s_own_init_subclass():
    #* A schema library: its base reads the column annotations of each subclass, and takes a
    #* keyword of its own; enforced checks the methods. Neither gets in the other's way.
    class Schema(Enforced, deep = True):
        columns: ClassVar[dict[str, Any]] = {}

        def __init_subclass__(cls, *, strict_columns: bool = False, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            #* Python 3.14 evaluates annotations lazily: they are read with annotationlib, not __annotations__.
            cls.columns = {name: hint for name, hint in annotationlib.get_annotations(cls).items() if name != "columns"}
            cls.strict_columns = strict_columns

        def validate(self, rows: list[dict[str, Any]]) -> int:
            return len(rows)

    class Prices(Schema, strict_columns = True, coerce = True):
        sku: str
        price: float

        def threshold(self, limit: float) -> float:
            return limit

    assert Prices.columns == {"sku": str, "price": float} and Prices.strict_columns is True
    assert Prices.__enforced_options__ == (True, False, True, True, True, "raise", InvalidDataError)
    assert Prices().threshold("2.5") == 2.5                                  # coerce, from the class keyword
    assert _raised(Prices().validate, [{"sku": "a"}, "not a row"]).errors()[0]["loc"] == ["rows", 1]   # deep, from Schema
    prices = Prices()
    prices.price = "anything"                                                # attributes aren't checked: data
    assert prices.price == "anything"


def test_it_combines_with_other_bases_and_adds_no_attributes():
    import abc

    class Shape(Enforced, abc.ABC):
        @abc.abstractmethod
        def area(self, scale: float) -> float: ...

    class Square(Shape):
        def area(self, scale: float) -> float:
            return scale

    with pytest.raises(TypeError):
        Shape()                                                              # still abstract
    _raised(Square().area, "x")

    class Slotted(Enforced):
        __slots__ = ("x",)

    assert not hasattr(Slotted(), "__dict__") and Enforced.__slots__ == ()
    assert isinstance(Square(), Enforced)


def test_instances_pickle():
    account = pickle.loads(pickle.dumps(Account("ana", 3)))
    assert (account.owner, account.balance) == ("ana", 3.0)


# ── what refuses it ──────────────────────────────────────────────────────────

def test_enforce_and_enforce_class_refuse_it():
    class Mine(Enforced):
        pass

    assert "class keywords" in str(_raised(enforce, Mine))
    _raised(enforce(coerce = True), Mine)
    _raised(enforce_class, Mine)


def test_enforced_dataclass_refuses_it():
    with pytest.raises(InvalidDataError, match = "inherits from Enforced"):
        @dataclass
        class Row(Enforced):
            n: int


def test_a_standard_dataclass_keeps_its_own_init_unchecked():
    #* Documented in the README (Limitations): __init_subclass__ runs before dataclasses writes __init__.
    @dataclasses.dataclass
    class Row(Enforced):
        n: int

        def double(self, k: int) -> int:
            return self.n * k

    assert Row("x").n == "x"                                                 # the generated __init__: unchecked
    _raised(Row(1).double, "x")                                              # the methods: checked
