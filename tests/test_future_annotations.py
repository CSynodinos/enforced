"""
A module under ``from __future__ import annotations``: every annotation in this file is a string.

A string is resolved when the function is first called, in the module it was written in. Two
kinds of name are not found there, and both used to fail on every call:

    the type parameter of a class written ``class Box[T]``
    a class that is local to a function (tests are full of them)
"""
from __future__ import annotations

from pyvalidate import TypeCheckerError, dataclass, enforced, typecheck
from typing import Any, Generic, Self, TypeVar
import dataclasses
import gc
import re
import weakref
import pytest


def _plain(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


# ═════════════════════════════════════════════════════════════════════════════
#  TYPE PARAMETERS OF A GENERIC CLASS
# ═════════════════════════════════════════════════════════════════════════════

@enforced(check_return = True)
class Stack[T]:
    def __init__(self) -> None:
        self.items: list[T] = []

    def push(self, item: T, times: int = 1) -> None:
        self.items += [item] * times

    def merged(self, other: Stack[T]) -> Stack[T]:
        return other

    def me(self) -> Self:
        return self

    @classmethod
    def of(cls, item: T, times: int = 1) -> Stack[T]:
        stack = cls()
        stack.push(item, times)
        return stack


@dataclass
class Box[W]:
    item: W
    count: int = 0


@dataclass(deep = True, frozen = True)
class Page[V]:
    items: list[V]
    size: int = 10


class Plain[X]:
    @typecheck
    def push(self, item: X, times: int = 1) -> Any:
        return item


Old = TypeVar("Old")


@enforced
class Legacy(Generic[Old]):
    def push(self, item: Old, times: int = 1) -> Any:
        return item


class Bounded[N: (int, str)]:
    @typecheck
    def take(self, value: N) -> Any:
        return value


@typecheck
def first[V](values: list[V], index: int = 0) -> V:
    return values[index]


def test_method_of_a_generic_class_can_name_its_type_parameter():
    stack = Stack()
    stack.push("anything")                                  # an unbound type parameter accepts every value
    stack.push(1, times = 2)
    assert stack.items == ["anything", 1, 1]
    assert stack.merged(Stack()).items == [] and stack.me() is stack
    assert Stack.of("a", 2).items == ["a", "a"]
    for bad in (lambda: stack.push(1, "2"), lambda: stack.merged(5), lambda: Stack.of(1, "2")):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_generic_dataclass_can_be_built():
    box = Box("anything", 2)
    assert (box.item, box.count) == ("anything", 2)
    box.item = [1]
    with pytest.raises(TypeCheckerError, match = "count"):
        Box(1, "2")
    with pytest.raises(TypeCheckerError, match = "Field Box.count"):
        box.count = "x"


def test_generic_dataclass_with_deep_and_frozen():
    assert Page([1, "a"]).size == 10
    with pytest.raises(TypeCheckerError, match = "size"):
        Page([1], "x")
    with pytest.raises(TypeCheckerError):
        Page("not a list")


def test_typecheck_on_a_method_of_a_generic_class():
    assert Plain().push("anything") == "anything"
    with pytest.raises(TypeCheckerError) as e:
        Plain().push(1, "x")
    assert "For parameter times of <Method Plain.push>" in _plain(e.value)


def test_a_constrained_type_parameter_is_checked():
    assert Bounded().take(1) == 1 and Bounded().take("a") == "a"
    with pytest.raises(TypeCheckerError):
        Bounded().take(1.5)


def test_what_already_worked_still_does():
    assert Legacy().push("anything") == "anything"         # a TypeVar of the module
    assert first([1, 2], 1) == 2                            # a generic function has its own parameters
    for bad in (lambda: Legacy().push(1, "x"), lambda: first([1], "0")):
        with pytest.raises(TypeCheckerError):
            bad()


# ═════════════════════════════════════════════════════════════════════════════
#  A CLASS LOCAL TO A FUNCTION
# ═════════════════════════════════════════════════════════════════════════════

def test_function_naming_a_local_class():
    class Inner:
        pass

    @typecheck(check_return = True)
    def f(x: Inner, others: list[Inner] | None = None) -> Inner:
        return x

    inner = Inner()
    assert f(inner) is inner and f(inner, [inner]) is inner
    with pytest.raises(TypeCheckerError) as e:
        f(5)
    assert "expected type: 'test_future_annotations.test_function_naming_a_local_class.<locals>.Inner'" in _plain(e.value)


def test_function_keeps_working_after_its_scope_is_gone():
    def build() -> Any:
        class Inner:
            pass

        @typecheck
        def f(x: Inner) -> Any:
            return x
        return f, Inner

    f, Inner = build()                                      # build() has returned: nothing of it is running
    inner = Inner()
    assert f(inner) is inner
    with pytest.raises(TypeCheckerError):
        f(5)


def test_typecheck_with_options_and_above_another_decorator():
    class Inner:
        pass

    class Service:
        @typecheck(deep = True)
        def all(self, items: list[Inner]) -> Any:
            return items

        @typecheck
        @classmethod
        def make(cls, inner: Inner) -> Any:
            return inner

        @typecheck
        @staticmethod
        def keep(inner: Inner) -> Any:
            return inner

    inner = Inner()
    assert Service().all([inner]) == [inner] and Service.make(inner) is inner and Service.keep(inner) is inner
    for bad in (lambda: Service().all([5]), lambda: Service.make(5), lambda: Service.keep(5)):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_dataclass_naming_local_classes():
    class Inner:
        pass

    @dataclass
    class Holder:
        inner: Inner
        others: list[Inner] = dataclasses.field(default_factory = list)

    @dataclass(frozen = True, slots = True, deep = True)
    class Outer:
        holder: Holder
        spare: Holder | None = None
        inners: tuple[Inner, ...] = ()

    inner = Inner()
    holder = Holder(inner)
    assert Outer(holder, None, (inner,)).holder is holder
    holder.inner = Inner()
    for bad in (lambda: Holder(5), lambda: Outer(5), lambda: Outer(holder, 5), lambda: Outer(holder, None, (5,)),
                lambda: setattr(holder, "inner", 5)):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_dataclass_inheriting_from_a_local_dataclass():
    class Inner:
        pass

    @dataclass
    class Base:
        inner: Inner

    @dataclass
    class Child(Base):
        again: Inner | None = None

    inner = Inner()
    assert Child(inner, inner).again is inner
    for bad in (lambda: Child(5), lambda: Child(inner, 5)):
        with pytest.raises(TypeCheckerError):
            bad()


def test_enforced_class_naming_local_classes():
    class Inner:
        pass

    @enforced(check_return = True)
    class Service:
        def __init__(self, inner: Inner) -> None:
            self.inner = inner

        def swap(self, inner: Inner, spare: Service | None = None) -> Inner:
            self.inner, old = inner, self.inner
            return old

        @classmethod
        def make(cls, inner: Inner) -> Service:
            return cls(inner)

        def __call__(self, inner: Inner) -> Self:
            return self

    inner = Inner()
    service = Service.make(inner)
    assert service.swap(Inner(), service) is inner and service(inner) is service
    for bad in (lambda: Service(5), lambda: service.swap(5), lambda: service.swap(inner, 5), lambda: Service.make(5),
                lambda: service(5)):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_the_innermost_scope_wins():
    class Thing:                                            # this one is not the one meant below
        pass

    def build() -> Any:
        class Thing:                                        # noqa: F811
            pass

        @typecheck
        def f(x: Thing) -> Any:
            return x
        return f, Thing

    f, inner_thing = build()
    assert isinstance(f(inner_thing()), inner_thing)
    with pytest.raises(TypeCheckerError):
        f(Thing())


def test_a_name_from_the_caller_is_not_taken_for_a_local_one():
    #* What is looked at is where the function is written, not who happens to be decorating it.
    def decorate(fn: Any) -> Any:
        Inner = int                                         # a local of the helper, of the same name
        return typecheck(fn), Inner

    class Inner:
        pass

    def f(x: Inner) -> Any:
        return x

    checked, _ = decorate(f)
    inner = Inner()
    assert checked(inner) is inner
    with pytest.raises(TypeCheckerError):
        checked(5)                                          # an int would pass if the helper's Inner had been taken


def test_only_the_names_the_annotations_use_are_kept():
    class Inner:
        pass

    class Big:
        pass

    big = Big()
    gone = weakref.ref(big)

    @typecheck
    def f(x: Inner, big: int = 0) -> Any:                   # a parameter named like a local: not an annotation name
        return x

    assert set(f.__wrapped__.__pyvalidate_scope__) == {"Inner"}
    del big
    gc.collect()
    assert gone() is None                                   # the function holds on to Inner, not to its surroundings

    @typecheck
    def g(n: int, text: str = "") -> int:                   # only names of the module and built-ins: nothing to keep
        return n

    assert not hasattr(g.__wrapped__, "__pyvalidate_scope__") and g(1) == 1


def test_a_name_that_exists_nowhere_is_still_reported():
    @typecheck
    def f(x: Missing) -> Any:                               # noqa: F821
        return x

    with pytest.raises(TypeCheckerError, match = "Cannot resolve annotation 'Missing'"):
        f(1)


# ═════════════════════════════════════════════════════════════════════════════
#  A LOCAL NAME THAT COMES AFTER THE DECORATOR  (review finding 31)
# ═════════════════════════════════════════════════════════════════════════════

def test_function_naming_a_class_defined_after_it():
    @typecheck(deep = True)
    def f(x: Later, more: list[Later] | None = None) -> Any:
        return x

    class Later:
        pass

    later = Later()
    for _ in range(3):
        assert f(later) is later and f(later, [later]) is later
        for bad in (lambda: f(5), lambda: f(later, [5])):
            with pytest.raises(TypeCheckerError) as e:
                bad()
            assert "Cannot resolve" not in _plain(e.value)
    assert set(f.__wrapped__.__pyvalidate_scope__) == {"Later"}     # what was found is kept, and nothing else


def _trees() -> Any:
    """Two local dataclasses that name each other, used once while this function runs."""
    @dataclass(deep = True)
    class Tree:
        leaves: list[Leaf]
        best: Leaf | None = None
        root: Tree | None = None

    @dataclass
    class Leaf:
        size: int
        home: Tree | None = None

    leaf = Leaf(1)
    tree = Tree([leaf, Leaf(2)], leaf)
    leaf.home = tree
    tree.best = Leaf(3)
    for bad in (lambda: Tree([leaf, 5]), lambda: Tree([leaf], 5), lambda: Leaf(1, 5), lambda: setattr(tree, "best", 5),
                lambda: setattr(leaf, "home", 5)):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)
    return Tree, Leaf


def test_local_dataclasses_that_name_each_other():
    _trees()


def test_names_found_while_the_function_ran_are_kept_afterwards():
    Tree, Leaf = _trees()                                           # the function that defined them has returned
    tree = Tree([Leaf(1)], Leaf(2))
    with pytest.raises(TypeCheckerError):
        tree.best = "x"
    with pytest.raises(TypeCheckerError):
        Tree(["x"])


def test_enforced_class_naming_a_class_defined_after_it():
    @enforced(check_return = True)
    class Service:
        def use(self, part: Part, spare: Part | None = None) -> Part:
            return part

        @typecheck(deep = True)
        def all(self, parts: list[Part]) -> Any:
            return parts

    class Part:
        pass

    part = Part()
    assert Service().use(part, part) is part and Service().all([part]) == [part]
    for bad in (lambda: Service().use(5), lambda: Service().use(part, 5), lambda: Service().all([5])):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_a_name_that_comes_later_is_not_found_once_its_function_has_returned():
    #* Nothing of the enclosing function is kept alive to look the name up later: that is the limit.
    def build() -> Any:
        @typecheck
        def f(x: Later) -> Any:
            return x

        class Later:
            pass
        return f, Later

    f, made = build()                   # not under the name Later: this function encloses f too, and would be searched
    with pytest.raises(TypeCheckerError, match = "Cannot resolve annotation 'Later'"):
        f(made())


def test_the_helper_that_calls_is_not_searched_for_a_later_name():
    def call_it(fn: Any, value: Any) -> Any:
        Later = int                                                 # noqa: F841  (a local of a function that only calls)
        return fn(value)

    def build() -> Any:
        @typecheck
        def f(x: Later) -> Any:                                     # noqa: F821
            return x
        return f

    with pytest.raises(TypeCheckerError, match = "Cannot resolve annotation 'Later'"):
        call_it(build(), 5)
