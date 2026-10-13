"""
A module under ``from __future__ import annotations``: every annotation in this file is a string.

A string is resolved when the function is first called, in the module it was written in. Two
kinds of name are not found there, and both used to fail on every call:

    the type parameter of a class written ``class Box[T]``
    a class that is local to a function (tests are full of them)
"""
from __future__ import annotations

from enforced import TypeCheckerError, dataclass, enforce, typecheck
from typing import Any, Generic, Literal, Self, TypeVar
import asyncio
import dataclasses
import gc
import re
import weakref
import pytest
import enforced._typechecker._scope as _scope


def _plain(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


# ═════════════════════════════════════════════════════════════════════════════
#  TYPE PARAMETERS OF A GENERIC CLASS
# ═════════════════════════════════════════════════════════════════════════════

@enforce(check_return = True)
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


@enforce
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

    @enforce(check_return = True)
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

    assert set(f.__wrapped__.__enforced_scope__) == {"Inner"}
    del big
    gc.collect()
    assert gone() is None                                   # the function holds on to Inner, not to its surroundings

    @typecheck
    def g(n: int, text: str = "") -> int:                   # only names of the module and built-ins: nothing to keep
        return n

    assert not hasattr(g.__wrapped__, "__enforced_scope__") and g(1) == 1


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
    assert set(f.__wrapped__.__enforced_scope__) == {"Later"}     # what was found is kept, and nothing else


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
    @enforce(check_return = True)
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


def test_a_name_that_comes_later_is_found_once_its_function_has_returned():
    #* Review finding 31. This was the limit: nothing of the enclosing function is kept alive to
    #* look the name up later. Nothing is, still: the name is read at the moment the function returns.
    def build() -> Any:
        @typecheck
        def f(x: Later, mode: Literal["r", "w"] = "r") -> Any:
            return x

        @dataclass
        class Tree:
            leaves: list[Leaf]
            root: Later | None = None

        @enforce
        class Box:
            def put(self, item: Later) -> Any:
                return item

        class Later:
            pass

        @dataclass
        class Leaf:
            pass
        return f, Later, Tree, Leaf, Box

    f, made, Tree, Leaf, Box = build()  # not under the name Later: this function encloses f too, and would be searched
    one = made()
    assert f(one) is one and Tree([Leaf()], one).root is one and Box().put(one) is one
    for bad in (lambda: f(5), lambda: Tree([Leaf()], 5), lambda: Box().put(5), lambda: Tree(5)):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(e.value)


def test_waiting_for_a_later_name_keeps_nothing_alive():
    #* A frame keeps its caller's frames, and every local of the whole stack with them. So the frame
    #* is not kept: what is waited for travels in the frame itself, and goes when it goes.
    class Heavy:
        pass

    def caller() -> Any:
        heavy = Heavy()
        return build(), weakref.ref(heavy)

    def build() -> Any:
        own = Heavy()

        @typecheck
        def f(x: Later) -> Any:
            return x

        class Later:
            pass
        return f, Later, weakref.ref(own)

    (f, made, own), heavy = caller()
    gc.collect()
    assert heavy() is None and own() is None
    assert build.__code__ not in _scope._WATCHED                       # watched only while a call of it was waited for
    assert f(made()) is not None


def test_a_later_name_belongs_to_the_call_it_was_written_in():
    def build(depth: int) -> list[Any]:
        @typecheck
        def f(x: Later) -> Any:
            return x

        inner = build(depth - 1) if depth else []                   # the same function, running again below this call

        class Later:
            pass
        return inner + [(f, Later)]

    pairs = build(3)
    for f, own in pairs:
        assert f(own()) is not None
        for _, other in pairs:
            if other is not own:
                with pytest.raises(TypeCheckerError):
                    f(other())


def test_a_later_name_through_other_ways_out_and_in():
    async def build_async() -> Any:
        @typecheck
        def f(x: Later) -> Any:
            return x
        await asyncio.sleep(0)

        class Later:
            pass
        return f, Later

    f, made = asyncio.run(build_async())
    assert f(made()) is not None

    def outer() -> Any:
        def inner() -> Any:
            @typecheck
            def f(x: Outside) -> Any:                               # noqa: F821
                return x
            return f
        f = inner()

        class Outside:                                              # defined in the function around the one f is in
            pass
        return f, Outside

    f, made = outer()
    assert f(made()) is not None

    #* A function that is left by an exception is never heard of. Its name stays unknown, as before.
    kept: list[Any] = []

    def fails() -> None:
        @typecheck
        def f(x: Nowhere) -> Any:                                   # noqa: F821
            return x
        kept.append(f)
        raise KeyError("left early")

    with pytest.raises(KeyError):
        fails()
    with pytest.raises(TypeCheckerError, match = "Cannot resolve annotation 'Nowhere'"):
        kept[0](5)


def test_without_a_free_tool_id_a_later_name_is_found_while_the_function_runs(monkeypatch):
    #* sys.monitoring has six tool ids. Where enforced can't have one, the old rule holds.
    monkeypatch.setattr(_scope, "_WATCHER", [None])

    def build() -> Any:
        @typecheck
        def f(x: Later) -> Any:
            return x

        @typecheck
        def g(x: Later) -> Any:
            return x

        class Later:
            pass
        return f, g, Later, g(Later())                              # g is called while build runs: found on the stack

    f, g, made, _ = build()
    assert g(made()) is not None
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
