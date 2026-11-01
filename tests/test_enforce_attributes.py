"""
``check_assignment`` under ``enforce``, ``enforce_class`` and ``Enforced`` (2026-10-31): what is assigned to
the attributes a class annotates is checked, as a dataclass's fields are.
"""
from functools import cached_property
from typing import Annotated, Any, ClassVar, Self, no_type_check
import dataclasses
import gc
import pickle
import warnings
import weakref

import pytest

import enforced._environment as environment
from enforced import (
    Enforced, InvalidDataError, InvalidDataWarning, enforce, enforce_class, validate,
    )
from enforced.data_types import Email


def _raised(call: Any, *args: Any) -> InvalidDataError:
    with pytest.raises(InvalidDataError) as info:
        call(*args)
    return info.value


@enforce
class Account:
    owner: str
    balance: float
    tags: list[str]
    opened: ClassVar[int] = 0

    def __init__(self, owner: str, balance: float = 0.0) -> None:
        self.owner = owner
        self.balance = balance
        self.tags = []
        self.notes = None                                           # not annotated: anything goes

    @property
    def doubled(self) -> float:
        return self.balance * 2


# ── what is checked ─────────────────────────────────────────────────────────

def test_an_annotated_attribute_is_checked_whenever_it_is_assigned():
    account = Account("ana", 1)
    for _ in range(80):                                             # both tiers: the bootstrap, then the generated one
        account.balance = 2
        assert type(account.balance) is float                      # converted, as for a float parameter
        _raised(setattr, account, "balance", "x")
        _raised(setattr, account, "owner", 5)
    assert account.balance == 2.0 and account.owner == "ana"       # a refused value is never stored


def test_the_message_names_the_attribute_and_the_class():
    error = _raised(setattr, Account("ana"), "balance", "lots")
    assert str(error).splitlines() == [
        "1 problem found in attribute assignment:",
        "    -> Attribute Account.balance of <Class Account>: expected type: 'float', got type 'str' (Value: 'lots')",
        ]
    assert error.errors() == [{"type": "field", "loc": ["balance"], "msg": "expected type: 'float', got type 'str'",
                               "input": "lots", "ctx": {"expected": "float", "origin": "Class Account",
                                                        "context": "attribute assignment"}}]
    assert str(pickle.loads(pickle.dumps(error))) == str(error)


def test_init_s_own_assignments_are_checked_too():
    @enforce
    class Loose:
        n: int

        def __init__(self, n) -> None:                              # no annotation: only the assignment checks
            self.n = n
    assert Loose(1).n == 1
    _raised(Loose, "1")


def test_what_is_left_alone():
    account = Account("ana")
    account.notes = 5                                               # not annotated
    account.extra = "new"                                           # not even declared
    Account.opened = "class attribute"                              # a ClassVar, and a class-level assignment
    Account.opened = 0
    with pytest.raises(AttributeError):
        account.doubled = 1                                         # a property: what it does with it is its own affair

    class Store:
        def __set_name__(self, owner: type, name: str) -> None:
            self.name = "_" + name

        def __get__(self, obj: Any, owner: Any = None) -> Any:
            return getattr(obj, self.name, None)

        def __set__(self, obj: Any, value: Any) -> None:
            obj.__dict__[self.name] = value

    @enforce
    class Held:
        value: int = Store()                                        # type: ignore[assignment]  # a descriptor takes it
        cached: int

        @cached_property
        def computed(self) -> int:
            return 1
    held = Held()
    held.value = "text"                                             # type: ignore[assignment]
    assert held.value == "text"
    _raised(setattr, held, "cached", "x")


def test_a_class_with_nothing_to_check_gets_no_setattr():
    @enforce
    class Bare:
        def __init__(self, x: int) -> None:
            self.x = x

    @enforce
    class OnlyClassVars:
        kind: ClassVar[str] = "a"
    assert "__setattr__" not in vars(Bare) and "__setattr__" not in vars(OnlyClassVars)


def test_the_options_apply():
    @enforce(coerce = True, deep = True)
    class Parsed:
        n: int
        items: list[int]

    @enforce(allow_subclass = False, convert = False)
    class Strict:
        x: float
        animal: Exception
    parsed = Parsed()
    parsed.n = "5"
    parsed.items = ["1", 2]
    assert parsed.n == 5 and parsed.items == [1, 2]
    _raised(setattr, parsed, "items", ["a"])
    strict = Strict()
    _raised(setattr, strict, "x", 1)                                # no conversion
    _raised(setattr, strict, "animal", ValueError())                # exactly the class
    strict.animal = Exception()


def test_checks_models_items_and_self():
    def positive(n: int) -> bool:
        return n > 0

    @enforce
    class Node:
        mail: Email
        size: Annotated[int, positive]
        parent: Self | None

        def __init__(self) -> None:
            self.parent = None
    node = Node()
    node.mail = "A@B.co"
    assert type(node.mail) is Email and node.mail == "A@b.co"
    assert "invalid 'Email'" in str(_raised(setattr, node, "mail", "nope"))
    _raised(setattr, node, "size", -1)
    node.parent = Node()
    _raised(setattr, node, "parent", "a node")


def test_a_slotted_class_is_checked():
    @enforce
    class Slotted:
        __slots__ = ("x",)
        x: int
    slotted = Slotted()
    slotted.x = 1
    _raised(setattr, slotted, "x", "1")


# ── turning it off ──────────────────────────────────────────────────────────

def test_check_assignment_false_and_exempt_setattr_and_no_type_check():
    @enforce(check_assignment = False)
    class Off:
        x: int

    @enforce
    class Exempt:
        x: int

        @enforce.exempt
        def __setattr__(self, name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

    @enforce
    @no_type_check
    class Unchecked:
        x: int
    for cls in (Off, Exempt, Unchecked):
        obj = cls()
        obj.x = "anything"
        assert obj.x == "anything", cls


def test_switched_off(monkeypatch):
    monkeypatch.setattr(environment, "VALIDATION_OFF", True)

    @enforce
    class Free:
        x: int
    Free().x = "a"
    assert "__setattr__" not in vars(Free)


def test_enforce_class_takes_the_option():
    class Later:
        x: int
    enforce_class(Later)
    _raised(setattr, Later(), "x", "a")

    class NotThis:
        x: int
    enforce_class(NotThis, check_assignment = False)
    NotThis().x = "a"


# ── a hand-written __setattr__, warnings, the error class ───────────────────

def test_a_hand_written_setattr_runs_after_the_check():
    seen: list[tuple[str, Any]] = []

    @enforce
    class Logged:
        x: float

        def __setattr__(self, name: str, value: Any) -> None:
            seen.append((name, value))
            super().__setattr__(name, value)
    logged = Logged()
    logged.x = 1
    _raised(setattr, logged, "x", "a")
    assert seen == [("x", 1.0)]                                     # converted first; the refused one never reached it


def test_on_error_warn_and_the_error_class():
    class AccountError(InvalidDataError):
        pass

    @enforce(on_error = "warn")
    class Soft:
        x: int

    @enforce(error = AccountError)
    class Own:
        x: int
    soft = Soft()
    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        soft.x = "a"
    assert soft.x == "a" and [type(w.message) for w in caught] == [InvalidDataWarning]
    assert "Attribute Soft.x of <Class Soft>" in str(caught[0].message)
    with pytest.raises(AccountError):
        Own().x = "a"


# ── classes below and above ─────────────────────────────────────────────────

def test_inherited_annotations_are_checked_and_checks_never_stack():
    calls: list[int] = []

    def counted(n: int) -> bool:
        calls.append(n)
        return True

    @enforce
    class Base:
        n: Annotated[int, counted]

    @enforce(coerce = True)
    class Child(Base):
        m: int

    class Plain(Child):                                             # not decorated: Child's checks
        extra: int
    child = Child()
    child.n = "3"                                                   # the base's annotation, with Child's options
    assert child.n == 3
    calls.clear()
    child.n = 4
    assert calls == [4]                                             # one check, not Base's and Child's
    _raised(setattr, Base(), "n", "3")                              # Base keeps its own options
    plain = Plain()
    plain.m = "5"
    assert plain.m == 5
    plain.extra = "not checked"                                     # annotated below the decorated class


def test_enforced_hands_the_option_down():
    class Model(Enforced):
        x: int

    class Loose(Model, check_assignment = False):
        y: int

    class Strict(Loose, check_assignment = True):
        z: int
    _raised(setattr, Model(), "x", "a")
    loose = Loose()
    loose.x = "a"                                                   # its own option: off, for what it inherits too
    loose.y = "b"
    _raised(setattr, Strict(), "z", "c")
    _raised(setattr, Strict(), "x", "c")


def test_a_name_defined_later_is_resolved_at_the_first_assignment():
    @enforce
    class Holder:
        item: "Later"                                               # noqa: F821

    globals()["Later"] = type("Later", (), {})
    try:
        holder = Holder()
        holder.item = Later()                                       # noqa: F821
        _raised(setattr, holder, "item", 1)
    finally:
        del globals()["Later"]


def test_a_plain_subclass_of_a_dataclass_checks_the_fields_with_its_own_options():
    @dataclasses.dataclass
    class Point:
        x: float

    @enforce(coerce = True)
    class Labelled(Point):
        label: str
    labelled = Labelled(1.0)
    labelled.x = "2"
    assert labelled.x == 2.0
    _raised(Labelled, "not a number")


def test_classes_made_in_a_loop_go_when_dropped():
    refs = []
    for i in range(40):
        cls = enforce(type(f"Made{i}", (), {"__annotations__": {"x": int}}))
        obj = cls()
        obj.x = 1
        refs.append(weakref.ref(cls))
    del cls, obj
    for _ in range(3):
        gc.collect()
    assert sum(r() is not None for r in refs) == 0


def test_an_instance_pickles_and_copies():
    account = Account("ana", 3)
    back = pickle.loads(pickle.dumps(account))
    assert back.balance == 3.0 and back.owner == "ana"
    _raised(setattr, back, "balance", "x")


def test_validate_on_a_method_is_unaffected():
    @enforce
    class Mixed:
        x: int

        @validate(coerce = True)
        def set_x(self, value: int) -> None:
            self.x = value
    mixed = Mixed()
    mixed.set_x("5")                                                # the method coerces, the assignment then passes
    assert mixed.x == 5


def test_an_annotation_written_in_a_method_is_not_checked():
    #* Documented (enforce, Enforced, README): Python keeps an annotation on ``self.x`` nowhere (PEP 526).
    @enforce
    class InInit:
        def __init__(self, balance: float = 0.0) -> None:
            self.balance: float = balance

    class Based(Enforced):
        def __init__(self) -> None:
            self.n: int = 0
    for obj, name in ((InInit(1.0), "balance"), (Based(), "n")):
        setattr(obj, name, "a")
        assert getattr(obj, name) == "a"
    assert "__setattr__" not in vars(InInit) and "__setattr__" not in vars(Based)
