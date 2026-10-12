"""Deep checks (``deep=True``): the items inside collections, at every depth."""
from enforced import typecheck, enforce, dataclass, TypeCheckerError, typecheck_from_dict
from typing import (
    Annotated, Any, Iterable, Iterator, Literal, NamedTuple, NewType, NotRequired, Optional,
    Required, Tuple, TypedDict,
    )
from collections.abc import Collection, Generator, Mapping, MutableSequence, Sequence, Set
from collections import ChainMap, Counter, OrderedDict, UserList, defaultdict, deque
from types import MappingProxyType
from enum import Enum
import asyncio
import pickle
import re
import pytest


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _raised(fn, *args, **kwargs) -> TypeCheckerError:
    with pytest.raises(TypeCheckerError) as exc:
        fn(*args, **kwargs)
    return exc.value


def _paths(fn, *args, **kwargs) -> list[str]:
    return [p.parameter for p in _raised(fn, *args, **kwargs).problems]


def _identity(annotation: Any, **flags: Any):
    """A deep-checked identity function for ``annotation``."""
    def f(x): return x
    f.__annotations__ = {"x": annotation}
    return typecheck(f, deep = True, **flags)


# ── opt-in ───────────────────────────────────────────────────────────────────

def test_shallow_by_default():
    @typecheck
    def f(xs: list[int], m: dict[str, int], p: tuple[int, str]) -> None: ...

    f(["a"], {1: "x"}, ("a", "b", "c"))             # only the outer types are checked


def test_deep_checks_items():
    @typecheck(deep = True)
    def f(xs: list[int]) -> None: ...

    f([1, 2, 3])
    f([])
    assert _paths(f, [1, "a", 3]) == ["xs[1]"]


def test_deep_still_checks_outer_type():
    f = _identity(list[int])
    p = _raised(f, (1, 2)).problems[0]
    assert (p.kind, p.parameter, p.expected, p.value) == ("type", "x", list, (1, 2))


def test_valid_value_passed_through_unchanged():
    f = _identity(dict[str, list[int]])
    value = {"a": [1, 2]}
    assert f(value) is value


# ── containers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("annotation, good, bad, bad_path", [
    (list[int], [1, 2], [1, "a"], "x[1]"),
    (set[int], {1, 2}, {"a"}, "x[0]"),
    (frozenset[str], frozenset({"a"}), frozenset({1}), "x[0]"),
    (deque[int], deque([1, 2]), deque([1, None]), "x[1]"),
    (Sequence[int], (1, 2), (1, 2.5), "x[1]"),
    (MutableSequence[int], [1], [b"x"], "x[0]"),
    (Set[int], {1}, frozenset({"a"}), "x[0]"),
    (Collection[int], [1], ["a"], "x[0]"),
    (tuple[int, ...], (1, 2, 3), (1, 2, "3"), "x[2]"),
    (dict[str, int], {"a": 1}, {"a": "1"}, "x['a']"),
    (dict[str, int], {"a": 1}, {2: 1}, "x[key 2]"),
    (Mapping[str, float], {"a": 1.5}, {"a": None}, "x['a']"),
    (OrderedDict[str, int], OrderedDict(a = 1), OrderedDict(a = "1"), "x['a']"),
    (defaultdict[str, list[int]], defaultdict(list, a = [1]), defaultdict(list, a = ["1"]), "x['a'][0]"),
    (Counter[str], Counter("aab"), Counter({"a": "many"}), "x['a']"),
    (ChainMap[str, int], ChainMap({"a": 1}), ChainMap({"a": "1"}), "x['a']"),
])
def test_containers(annotation, good, bad, bad_path):
    f = _identity(annotation, convert = False)
    assert f(good) is good
    assert _paths(f, bad) == [bad_path]


def test_fixed_tuple_positions_and_length():
    f = _identity(tuple[int, str])
    f((1, "a"))
    assert _paths(f, (1, 2)) == ["x[1]"]
    e = _raised(f, (1, "a", None))
    p = e.problems[0]
    assert (p.kind, p.parameter, p.detail, p.value) == ("length", "x", 2, (1, "a", None))
    assert "expected type: tuple[int, str] with 2 items, got 3 items" in _plain(str(e))
    assert _raised(f, (1,)).problems[0].kind == "length"


def test_empty_tuple_annotation():
    f = _identity(tuple[()])
    f(())
    assert _raised(f, (1,)).problems[0].kind == "length"


def test_empty_typing_tuple_annotation():
    f = _identity(Tuple[()])
    f(())
    assert _raised(f, (1,)).problems[0].kind == "length"


@pytest.mark.parametrize("annotation", [Tuple, Tuple | None, Optional[Tuple]], ids = ["Tuple", "Tuple | None", "Optional[Tuple]"])
def test_bare_typing_tuple_is_a_tuple_of_anything(annotation):
    """typing.Tuple without arguments says nothing about the items (once it was read as "no items")."""
    f = _identity(annotation)
    assert f(()) == () and f((1, "a")) == (1, "a")
    assert _raised(f, [1, 2]).problems[0].kind == "type"            # it still has to be a tuple


def test_tuple_of_any_checks_length_only():
    f = _identity(tuple[Any, Any])
    f((1, "x"))
    assert _raised(f, (1,)).problems[0].kind == "length"


def test_tuple_with_a_run_of_unknown_length():
    #* tuple[int, *tuple[str, ...]] used to stay shallow: any tuple passed.
    f = _identity(tuple[int, *tuple[str, ...]])
    assert f((1, "a", "b")) == (1, "a", "b") and f((1,)) == (1,)
    assert _paths(f, ("anything",)) == ["x[0]"]
    assert _paths(f, (1, "a", 2, "b", 3)) == ["x[2]", "x[4]"]
    problem = _raised(f, ()).problems[0]
    assert (problem.kind, problem.detail) == ("length", "at least 1")
    assert "with at least 1 item, got 0 items" in _plain(str(problem))


def test_tuple_with_fixed_items_at_both_ends():
    f = _identity(tuple[int, *tuple[str, ...], float, bool])
    assert f((1, 2.5, True)) == (1, 2.5, True)
    assert f((1, "a", "b", 2.5, False)) == (1, "a", "b", 2.5, False)
    assert f((1, "a", 2, True)) == (1, "a", 2.0, True) and type(f((1, "a", 2, True))[2]) is float     # converted in place
    assert _paths(f, (1, "a", 2.5, "no")) == ["x[3]"]
    assert _paths(f, ("x", 5, 2.5, True)) == ["x[0]", "x[1]"]
    assert "with at least 3 items, got 2 items" in _plain(str(_raised(f, (1, 2.5))))


def test_unpacked_fixed_tuple_and_type_var_tuple_inside_a_tuple():
    from typing import TypeVarTuple, Unpack
    Ts = TypeVarTuple("Ts")
    fixed = _identity(tuple[int, *tuple[str, float]])                   # simply three positions
    assert fixed((1, "a", 2.5)) == (1, "a", 2.5)
    assert _raised(fixed, (1, "a")).problems[0].kind == "length"
    spelled = _identity(tuple[int, Unpack[tuple[str, ...]]])            # the older spelling of the same
    assert _paths(spelled, (1, 2)) == ["x[1]"]
    anything = _identity(tuple[int, *Ts])                               # a run of anything
    assert anything((1, object(), None)) and _paths(anything, ("a",)) == ["x[0]"]
    assert _identity(tuple[*Ts])(("a", 1)) == ("a", 1)                  # nothing to check: any tuple
    nested = _identity(list[tuple[str, *tuple[int, ...]]])
    assert _paths(nested, [("a", 1), ("b", "c")]) == ["x[1][1]"]


def test_all_bad_items_reported():
    f = _identity(list[int])
    assert _paths(f, ["a", 1, "b", 2.5]) == ["x[0]", "x[2]", "x[3]"]


def test_keys_and_values_both_reported():
    f = _identity(dict[str, int], convert = False)
    assert _paths(f, {1: "a"}) == ["x[key 1]", "x[1]"]


def test_items_use_exact_isinstance_semantics():
    class LooksLikeInt:                             # isinstance(x, int) is True through __class__
        @property
        def __class__(self):
            return int

    fake = LooksLikeInt()
    assert isinstance(fake, int)
    f = _identity(list[int])
    assert f([1, fake]) == [1, fake]
    assert _paths(f, [fake, "a"]) == ["x[1]"]
    assert _paths(f, ["a"]) == ["x[0]"]                                 # a cached rejection stays a rejection
    assert _paths(f, ["a"]) == ["x[0]"]


def test_any_items_are_not_iterated():
    class Exploding(list):
        def __iter__(self):
            raise AssertionError("iterated")

    for annotation in (list[Any], list[object], list):
        _identity(annotation)(Exploding([1]))


# ── every depth ──────────────────────────────────────────────────────────────

def test_nested_paths():
    f = _identity(dict[str, list[tuple[int, str]]])
    f({"a": [(1, "x")], "b": []})
    assert _paths(f, {"a": [(1, "x"), (2, 3)]}) == ["x['a'][1][1]"]


def test_five_levels_deep():
    f = _identity(list[dict[str, list[set[int]]]])
    f([{"a": [{1, 2}]}])
    assert _paths(f, [{"a": [{1}, {"no"}]}]) == ["x[0]['a'][1][0]"]


def test_nested_outer_type_mismatch():
    f = _identity(list[list[int]])
    p = _raised(f, [[1], (2,)]).problems[0]
    assert (p.parameter, p.expected, p.value) == ("x[1]", list, (2,))


# ── TypedDict / NamedTuple ───────────────────────────────────────────────────

class Address(TypedDict):
    city: str
    zip: NotRequired[str]


class User(TypedDict):
    name: str
    age: int
    address: Address
    tags: NotRequired[list[str]]


class Options(TypedDict, total = False):
    verbose: bool
    level: Required[int]


def test_typeddict_valid():
    f = _identity(User)
    f({"name": "Ana", "age": 30, "address": {"city": "Athens"}})
    f({"name": "Ana", "age": 30, "address": {"city": "Athens", "zip": "105"}, "tags": ["x"]})
    f({"name": "Ana", "age": 30, "address": {"city": "Athens"}, "extra": object()})   # extra keys allowed


def test_typeddict_missing_key():
    f = _identity(User)
    e = _raised(f, {"name": "Ana", "address": {"city": "Athens"}})
    p = e.problems[0]
    assert (p.kind, p.parameter, p.expected, p.detail, p.value) == ("missing_key", "x['age']", int, "age", None)
    assert "For parameter x of <Function f>: missing required key 'age' (expecting type int)" in _plain(str(e))


def test_typeddict_nested_errors():
    f = _identity(User)
    assert _paths(f, {"name": 1, "age": 30, "address": {"zip": 1}, "tags": ["a", 2]}) == [
        "x['name']", "x['address']['city']", "x['address']['zip']", "x['tags'][1]",
        ]


def test_typeddict_total_false_and_required():
    f = _identity(Options)
    f({"level": 1})
    assert _raised(f, {"verbose": True}).problems[0].kind == "missing_key"
    assert _paths(f, {"level": 1, "verbose": "yes"}) == ["x['verbose']"]


class Point(NamedTuple):
    x: int
    y: float


class Segment(NamedTuple):
    start: Point
    end: Point
    label: str = ""


def test_namedtuple_fields():
    f = _identity(Segment, convert = False)
    f(Segment(Point(0, 0.0), Point(1, 1.0)))
    assert _paths(f, Segment(Point(0, 0.0), Point("1", 1), 3)) == ["x.end.x", "x.end.y", "x.label"]


# ── unions, aliases, wrappers ────────────────────────────────────────────────

def test_optional_collection():
    f = _identity(Optional[list[int]])
    f(None)
    f([1])
    assert _paths(f, [1, "a"]) == ["x[1]"]
    assert _raised(f, "a").problems[0].parameter == "x"


def test_union_errors_come_from_the_member_with_the_right_shape():
    f = _identity(int | list[int] | dict[str, int])
    f(1)
    f([1])
    f({"a": 1})
    assert _paths(f, [1, "a"]) == ["x[1]"]
    assert _paths(f, {"a": "b"}) == ["x['a']"]
    assert _paths(f, "nope") == ["x"]


def test_union_of_same_container_picks_fewest_errors():
    f = _identity(list[int] | list[str], convert = False)
    f([1, 2])
    f(["a"])
    assert _paths(f, ["a", "b", 3]) == ["x[2]"]


def test_items_union():
    f = _identity(list[int | str])
    f([1, "a"])
    assert _paths(f, [1, None]) == ["x[1]"]


type Matrix = list[list[float]]
type Pair[T] = tuple[T, T]
type Tree = int | list[Tree]
type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


def test_type_alias():
    f = _identity(Matrix, convert = False)
    f([[1.0, 2.0]])
    assert _paths(f, [[1.0], [2]]) == ["x[1][0]"]


def test_generic_alias():
    f = _identity(Pair[int])
    f((1, 2))
    assert _paths(f, (1, "2")) == ["x[1]"]
    assert _raised(f, (1, 2, 3)).problems[0].kind == "length"


def test_recursive_alias():
    f = _identity(Tree)
    f(1)
    f([1, [2, [3, []]]])
    assert _paths(f, [1, [2, ["x"]]]) == ["x[1][1][0]"]


def test_recursive_json_alias():
    f = _identity(Json)
    f({"a": [1, 2.5, None, True, {"b": "c"}]})
    assert _paths(f, {"a": [1, {"b": object()}]}) == ["x['a'][1]['b']"]


def test_data_that_contains_itself():
    f = _identity(Tree)
    loop: list[Any] = []
    loop.append(loop)
    e = _raised(f, loop)
    assert e.problems[0].kind == "cycle"
    assert "contains itself" in _plain(str(e))


UserIds = NewType("UserIds", list[int])


def test_wrappers_are_followed():
    for annotation in (Annotated[list[int], "meta"], UserIds):
        f = _identity(annotation)
        f([1])
        assert _paths(f, ["a"]) == ["x[0]"]


class Color(Enum):
    RED = "red"
    BLUE = "blue"


def test_special_items():
    f = _identity(list[Literal["a", "b"]])
    f(["a", "b"])
    assert _paths(f, ["a", "c"]) == ["x[1]"]

    g = _identity(list[type[int]])
    g([int, bool])
    assert _paths(g, [int, str]) == ["x[1]"]

    h = _identity(list[Color])
    h([Color.RED])
    assert _paths(h, ["red"]) == ["x[0]"]


# ── never consumed ───────────────────────────────────────────────────────────

def test_iterables_and_iterators_are_not_consumed():
    for annotation in (Iterable[int], Iterator[int], Generator[int, None, None]):
        f = _identity(annotation)
        gen = (i for i in ["not", "ints"])
        assert f(gen) is gen
        assert list(gen) == ["not", "ints"]


# ── strict mode ──────────────────────────────────────────────────────────────

def test_bool_items_are_not_ints():
    assert _paths(_identity(list[int]), [1, True, 2, False]) == ["x[1]", "x[3]"]
    assert _paths(_identity(dict[str, int]), {"a": True}) == ["x['a']"]
    assert _paths(_identity(tuple[int, str]), (True, "a")) == ["x[0]"]
    assert _identity(list[int | bool])([1, True]) == [1, True]
    assert _identity(list[bool])([True]) == [True]
    assert _paths(_identity(list[int], coerce = True), [True]) == ["x[0]"]     # not coerced either


def test_allow_subclass_applies_to_items():
    class MyInt(int):
        pass

    assert _identity(list[int])([MyInt(1)]) == [1]
    f = _identity(list[int], allow_subclass = False)
    assert _paths(f, [1, MyInt(2)]) == ["x[1]"]


def test_strict_mode_abstract_containers_and_items():
    """An abstract container or item type is matched by isinstance in strict mode too: nothing is exactly a Sequence."""
    f = _identity(Sequence[int], allow_subclass = False)
    assert f([1]) == [1] and f((1,)) == (1,)
    assert _paths(f, [1, "a"]) == ["x[1]"]
    assert _paths(f, [1, True]) == ["x[1]"]                         # the items are still exact
    assert _paths(f, {1}) == ["x"]                                  # a set is no Sequence

    g = _identity(list[Sequence[int]], allow_subclass = False)
    assert g([[1], (2,)]) == [[1], (2,)]
    assert _paths(g, [[1], (2, "a")]) == ["x[1][1]"]
    assert _paths(g, ([1],)) == ["x"]                               # the list itself is concrete: exact

    h = _identity(Mapping[str, Sequence[int]], allow_subclass = False)
    assert h({"a": [1]}) == {"a": [1]}
    assert _paths(h, {"a": [1.5]}) == ["x['a'][0]"]


# ── conversion and coercion ──────────────────────────────────────────────────

def test_items_converted_into_a_new_container():
    f = _identity(list[float])
    original = [1, 2.5]
    out = f(original)
    assert out == [1.0, 2.5] and type(out[0]) is float
    assert original == [1, 2.5] and type(original[0]) is int         # the caller's list is untouched
    assert out is not original


def test_conversion_at_every_depth():
    f = _identity(dict[str, list[tuple[float, complex]]])
    out = f({"a": [(1, 2)]})
    assert out == {"a": [(1.0, 2 + 0j)]}
    assert type(out["a"][0][0]) is float and type(out["a"][0][1]) is complex


def test_bulk_numeric_conversion_edge_cases():
    f = _identity(list[float])
    out = f(list(range(500)) + [0.5])
    assert out[:2] == [0.0, 1.0] and all(type(x) is float for x in out)
    nan = float("nan")
    out = f([1, nan])                                                  # NaN != NaN: still converted correctly
    assert out[0] == 1.0 and out[1] is nan
    assert _paths(f, [1, 2**53 + 1]) == ["x[1]"]                       # not exactly representable
    assert _paths(f, [1, True]) == ["x[1]"]                            # bool is never converted

    class MyFloat(float):
        pass

    g = _identity(list[float], allow_subclass = False)
    assert _paths(g, [1, MyFloat(2.0)]) == ["x[1]"]
    h = _identity(list[complex])
    assert h([1, 2.5, 3j]) == [1 + 0j, 2.5 + 0j, 3j]


def test_bad_items_found_in_large_containers():
    f = _identity(list[int])
    big = list(range(10_000))
    assert _paths(f, big[:5000] + ["x"] + big[5000:] + [None]) == ["x[5000]", "x[10001]"]
    g = _identity(dict[str, int])
    d = {str(i): i for i in range(1000)}
    d["bad"] = "x"
    d[7] = 7
    assert _paths(g, d) == ["x['bad']", "x[key 7]"]
    s = _identity(set[int])
    assert len(_paths(s, set(range(100)) | {"a"})) == 1


def test_conversion_off():
    f = _identity(list[float], convert = False)
    assert _paths(f, [1]) == ["x[0]"]


def test_coercion_of_items():
    f = _identity(list[int], coerce = True)
    assert f(["1", 2.0, 3]) == [1, 2, 3]
    g = _identity(dict[int, bool], coerce = True)
    assert g({"1": "yes", 2: 0}) == {1: True, 2: False}
    h = _identity(list[Color], coerce = True)
    assert h(["red"]) == [Color.RED]


def test_coercion_of_outer_and_items_together():
    f = _identity(list[int], coerce = True)
    assert f(("1", "2")) == [1, 2]                                     # tuple -> list, then items
    g = _identity(set[float], coerce = True)
    assert g(["1.5"]) == {1.5}


def test_only_unconvertible_items_are_reported():
    f = _identity(list[float])
    assert _paths(f, [1, "x", 2]) == ["x[1]"]                         # 1 and 2 would convert fine
    g = _identity(list[int], coerce = True)
    assert _paths(g, ["1", "one"]) == ["x[1]"]


def test_container_types_are_kept_when_converting():
    f = _identity(deque[float])
    out = f(deque([1, 2], maxlen = 5))
    assert type(out) is deque and out.maxlen == 5 and list(out) == [1.0, 2.0]

    g = _identity(defaultdict[str, float])
    out = g(defaultdict(list, a = 1))
    assert type(out) is defaultdict and out.default_factory is list and out["a"] == 1.0

    h = _identity(OrderedDict[str, float])
    out = h(OrderedDict([("b", 1), ("a", 2)]))
    assert type(out) is OrderedDict and list(out) == ["b", "a"]

    t = _identity(tuple[float, ...])
    assert t((1, 2)) == (1.0, 2.0)

    s = _identity(frozenset[float])
    out = s(frozenset({1}))
    assert type(out) is frozenset and out == {1.0}


class Stack(list):
    pass


@pytest.mark.parametrize("value", [[1, 2], (1, 2), {1, 2}, frozenset({1, 2}), deque([1, 2], maxlen = 5), Stack([1, 2]),
                                   UserList([1, 2])], ids = lambda v: type(v).__name__)
def test_converted_items_come_back_in_the_callers_container_type(value):
    out = _identity(Collection[float])(value)
    assert type(out) is type(value) and sorted(out) == [1.0, 2.0]
    assert all(type(x) is float for x in out)
    assert getattr(out, "maxlen", None) == getattr(value, "maxlen", None)


@pytest.mark.parametrize("value", [{1: "a"}, range(3), {1: "a"}.keys(), b"ab"], ids = lambda v: type(v).__name__)
def test_a_container_that_cannot_hold_converted_items_is_rejected(value):
    """It is never swapped for another type (once a dict or a range passed for Collection[float] arrived as a list)."""
    e = _raised(_identity(Collection[float]), value)
    assert [(p.kind, p.parameter) for p in e.problems] == [("invalid", "x")]
    assert (f"its items need converting, but a {type(value).__name__} cannot be rebuilt with the converted items"
            in _plain(str(e)))


def test_a_container_that_needs_no_conversion_is_passed_as_is():
    f = _identity(Collection[float])
    for value in ({1.0: "a"}, {1.0: "a"}.keys()):
        assert f(value) is value                                    # only conversion needs a rebuild


def test_a_mapping_that_cannot_hold_converted_items_is_rejected():
    f = _identity(Mapping[str, float])
    proxy = MappingProxyType({"a": 1.0})
    assert f(proxy) is proxy
    e = _raised(f, MappingProxyType({"a": 1}))                      # a read-only proxy isn't replaced by a dict
    assert "but a mappingproxy cannot be rebuilt with the converted items" in _plain(str(e))


def test_keys_that_collide_after_conversion_are_rejected():
    """Keys that convert to the same key would silently drop entries (once three such keys left one entry)."""
    f = _identity(dict[int, str], coerce = True)
    assert f({"1": "a", "2": "b"}) == {1: "a", 2: "b"}              # distinct keys convert fine
    data = {"1": "a", 1: "b", " 1": "c"}
    e = _raised(f, data)
    assert data == {"1": "a", 1: "b", " 1": "c"}                    # the caller's dict is untouched
    assert [(p.kind, p.parameter) for p in e.problems] == [("invalid", "x")]
    assert "invalid 'dict[int, str]': keys '1' and 1 both convert to 1" in _plain(str(e))


def test_typeddict_and_namedtuple_conversion():
    f = _identity(User, coerce = True)
    out = f({"name": "Ana", "age": "30", "address": {"city": "Athens"}})
    assert out["age"] == 30

    g = _identity(Point)
    out = g(Point(1, 2))
    assert type(out) is Point and type(out.y) is float


def test_union_conversion_in_declared_order():
    f = _identity(list[float] | list[str], coerce = True)
    assert f([1, "2"]) == [1.0, 2.0]


# ── where deep applies ───────────────────────────────────────────────────────

def test_varargs_items():
    @typecheck(deep = True)
    def f(*args: list[int], **kwargs: dict[str, int]) -> None: ...

    f([1], [2], a = {"k": 1})
    assert _paths(f, [1], [2, "x"], a = {"k": 1}, b = {"k": "no"}) == ["args[1][1]", "kwargs[b]['k']"]


def test_keyword_and_positional_calls():
    @typecheck(deep = True)
    def f(a: list[int], *, b: set[str]) -> None: ...

    f([1], b = {"x"})
    assert _paths(f, [1, "a"], b = {1}) == ["a[1]", "b[0]"]
    assert _paths(f, a = ["a"], b = set()) == ["a[0]"]


def test_missing_argument_with_deep():
    @typecheck(deep = True)
    def f(a: list[int], b: int) -> None: ...

    e = _raised(f, ["x"])
    assert [p.kind for p in e.problems] == ["missing", "type"]
    assert e.problems[1].parameter == "a[0]"


def test_return_value():
    @typecheck(deep = True, check_return = True)
    def f(x: Any) -> list[int]:
        return x

    assert f([1]) == [1]
    e = _raised(f, [1, "a"])
    p = e.problems[0]
    assert (p.kind, p.parameter) == ("return", "return[1]")
    assert "For introspected return value at index [1] of <Function f>" in _plain(str(e))


def test_return_value_converted():
    @typecheck(deep = True, check_return = True)
    def f() -> dict[str, float]:
        return {"a": 1}

    out = f()
    assert out == {"a": 1.0} and type(out["a"]) is float


def test_return_items_are_not_coerced():
    @typecheck(deep = True, check_return = True, coerce = True)
    def f(xs: list[int]) -> list[int]:
        return [str(x) for x in xs]                                 # type: ignore[misc]

    assert _paths(f, ["1", "2"]) == ["return[0]", "return[1]"]     # the arguments were coerced, the result isn't


def test_return_length_problem():
    @typecheck(deep = True, check_return = True)
    def f() -> tuple[int, int]:
        return (1, 2, 3)                            # type: ignore[return-value]

    e = _raised(f)
    assert e.problems[0].kind == "length"
    assert "For return value of <Function f>" in _plain(str(e))


def test_defaults_are_checked_deeply():
    @typecheck(deep = True)
    def f(xs: list[int] = [1, "x"]) -> None: ...    # type: ignore[list-item]

    e = _raised(f)
    assert e.context == "definition"
    p = e.problems[0]
    assert (p.kind, p.parameter, p.value) == ("default", "xs[1]", "x")
    assert "For default value of introspected parameter xs at index [1]" in _plain(str(e))


def test_default_converted_deeply():
    @typecheck(deep = True)
    def f(xs: list[float] = [1, 2]) -> list[float]:
        return xs

    out = f()
    assert out == [1.0, 2.0] and all(type(x) is float for x in out)


def test_class_methods():
    @enforce(deep = True)
    class Store:
        def __init__(self, stock: dict[str, int]) -> None:
            self.stock = stock

        def add(self, names: list[str]) -> None: ...

        @staticmethod
        def parse(rows: list[tuple[str, int]]) -> None: ...

    s = Store({"apple": 1})
    assert _paths(Store, {"apple": "1"}) == ["stock['apple']"]
    assert _paths(s.add, ["a", 1]) == ["names[1]"]
    assert _paths(Store.parse, [("a", "1")]) == ["rows[0][1]"]


def test_async_function():
    @typecheck(deep = True)
    async def f(xs: list[int]) -> int:
        return len(xs)

    assert asyncio.run(f([1, 2])) == 2
    with pytest.raises(TypeCheckerError):
        asyncio.run(f([1, "a"]))


def test_typecheck_from_dict():
    spec = {"object_name": "create", "record": {"tags": list[str], "scores": dict[str, float]}}
    args, kwargs = typecheck_from_dict({**spec, "kwargs": {"tags": ["a"], "scores": {"x": 1}}, "deep": True})
    assert kwargs["scores"] == {"x": 1.0}
    with pytest.raises(TypeCheckerError) as exc:
        typecheck_from_dict({**spec, "kwargs": {"tags": ["a", 2], "scores": {}}, "deep": True})
    assert [p.parameter for p in exc.value.problems] == ["tags[1]"]
    typecheck_from_dict({**spec, "kwargs": {"tags": ["a", 2], "scores": {}}})          # deep off: passes


# ── dataclasses ──────────────────────────────────────────────────────────────

def test_dataclass_init_and_assignment():
    @dataclass(deep = True)
    class Order:
        lines: list[tuple[str, int]]
        notes: dict[str, str] | None = None

    o = Order([("apple", 2)])
    e = _raised(Order, [("apple", "2")])
    assert e.problems[0].parameter == "lines[0][1]"

    e = _raised(setattr, o, "lines", [("apple", 2), ("pear", None)])
    p = e.problems[0]
    assert (p.kind, p.parameter, p.value) == ("field", "lines[1][1]", None)
    assert "Introspected field Order.lines at index [1][1] of <Dataclass Order>: expected type: 'int'" in _plain(str(e))
    assert e.context == "field assignment"

    o.notes = {"a": "b"}
    assert _paths(setattr, o, "notes", {"a": 1}) == ["notes['a']"]


def test_dataclass_shape_problems_on_assignment():
    @dataclass(deep = True)
    class Box:
        size: tuple[int, int]
        meta: User | None = None

    b = Box((1, 2))
    e = _raised(setattr, b, "size", (1, 2, 3))
    assert e.problems[0].kind == "length"
    assert "Field Box.size of <Dataclass Box>: expected type: tuple[int, int] with 2 items" in _plain(str(e))

    e = _raised(setattr, b, "meta", {"name": "x", "address": {"city": "y"}})
    assert e.problems[0].kind == "missing_key"
    assert "Field Box.meta of <Dataclass Box>: missing required key 'age'" in _plain(str(e))


def test_dataclass_conversion_of_items():
    @dataclass(deep = True)
    class Series:
        values: list[float]

    s = Series([1, 2])
    assert all(type(v) is float for v in s.values)
    s.values = [3]
    assert type(s.values[0]) is float


def test_dataclass_shallow_by_default():
    @dataclass
    class Series:
        values: list[float]

    s = Series(["not", "floats"])                   # only the outer type is checked
    s.values = [None]


def test_frozen_dataclass():
    @dataclass(deep = True, frozen = True)
    class Frozen:
        values: tuple[int, ...]

    Frozen((1, 2))
    assert _paths(Frozen, (1, "2")) == ["values[1]"]


# ── errors ───────────────────────────────────────────────────────────────────

def test_deep_error_is_lazy_and_picklable():
    f = _identity(list[int])
    e = _raised(f, ["a"])
    assert e._message is None
    clone = pickle.loads(pickle.dumps(e))
    assert str(clone) == str(e)
    assert "For introspected parameter x at index [0] of <Function f>: expected type: 'int', got type 'str' (Value: 'a')" in _plain(str(e))


def test_introspected_wording():
    @dataclass(deep = True)
    class Example:
        e: list[int]

    e = _raised(Example, [1, 2, bytearray(b"x")])
    assert _plain(str(e)).endswith(
        "-> For introspected parameter e at index [2] of <Dataclass Example>: "
        "expected type: 'int', got type 'bytearray' (Value: bytearray(b'x'))"
        )
    assert e.problems[0].parameter == "e[2]"                              # the data keeps the full path

    #* A problem with the parameter itself keeps the usual wording.
    assert "For parameter e of <Dataclass Example>" in _plain(str(_raised(Example, "no")))

    f = _identity(dict[str, Segment], convert = False)
    text = _plain(str(_raised(f, {"a": Segment(Point(0, 0.0), Point(1, "1"))})))
    assert "For introspected parameter x at index ['a'] of <Function f>" not in text
    assert "For introspected parameter x at index ['a'].end.y of <Function f>" in text

    g = _identity(Point, convert = False)
    assert "For introspected parameter x at field y of <Function f>" in _plain(str(_raised(g, Point(1, 2))))

    @typecheck(deep = True)
    def v(*rows: list[int]) -> None: ...

    text = _plain(str(_raised(v, [1, "z"], "whole")))
    assert "For introspected parameter rows[0] at index [1] of <Function v>" in text
    assert "For parameter rows[1] of <Function v>" in text


def test_problem_count_in_message():
    f = _identity(list[int])
    assert "3 problems found in call" in _plain(str(_raised(f, ["a", "b", "c"])))


def test_long_keys_are_shortened_in_paths():
    f = _identity(dict[str, int])
    key = "k" * 100
    path = _paths(f, {key: "x"})[0]
    assert path.startswith("x['kkk") and path.endswith("...]") and len(path) < 40


# ── forward references ───────────────────────────────────────────────────────

def test_unresolved_item_annotation_is_retried(monkeypatch):
    @typecheck(deep = True)
    def f(xs: list["LaterDefined"]) -> None: ...   # type: ignore[name-defined]  # noqa: F821

    with pytest.raises(TypeCheckerError, match = "Cannot resolve"):
        f([1])

    class LaterDefined:
        pass

    monkeypatch.setitem(globals(), "LaterDefined", LaterDefined)
    f([LaterDefined()])
    assert _paths(f, [LaterDefined(), 1]) == ["xs[1]"]


# ── the same annotation, different settings ──────────────────────────────────

def test_compiled_checks_are_not_shared_across_settings():
    annotation = list[float]
    converting = _identity(annotation)
    strict = _identity(annotation, convert = False)
    assert converting([1]) == [1.0]
    assert _paths(strict, [1]) == ["x[0]"]
    assert converting([2]) == [2.0]


# ═════════════════════════════════════════════════════════════════════════════
#  A CONVERTED MAPPING KEEPS ITS OWN TYPE (review finding 4)
# ═════════════════════════════════════════════════════════════════════════════

class Film(TypedDict):
    year: float
    title: NotRequired[str]


class Shelf(dict):
    """A dict subclass with nothing of its own."""


@typecheck(deep = True)
def film(m: Film) -> Any:
    return m


@typecheck(deep = True)
def prices(m: ChainMap[str, float]) -> Any:
    return m


def test_typeddict_conversion_keeps_an_ordered_dict():
    given = OrderedDict(title = "Up", year = 2009)
    out = film(given)
    assert type(out) is OrderedDict and list(out.items()) == [("title", "Up"), ("year", 2009.0)]
    assert type(out["year"]) is float and out is not given
    assert given["year"] == 2009 and type(given["year"]) is int       # the caller's own is never changed


def test_typeddict_conversion_keeps_a_defaultdict_and_a_dict_subclass():
    out = film(defaultdict(list, year = 1))
    assert type(out) is defaultdict and out.default_factory is list and out == {"year": 1.0}
    out = film(Shelf(year = 1))
    assert type(out) is Shelf and out == {"year": 1.0}
    assert type(film({"year": 1})) is dict                  # a plain dict stays a plain dict


def test_typeddict_without_conversion_returns_the_same_object():
    for given in (OrderedDict(year = 1.5), Shelf(year = 1.5), {"year": 1.5}):
        assert film(given) is given


def test_typeddict_value_whose_copy_fails_is_reported_not_swapped():
    class Fussy(dict):
        def __copy__(self):
            raise RuntimeError("no copies")

    with pytest.raises(TypeCheckerError):
        film(Fussy(year = 1))                               # it needs a converted copy, and can't have one
    assert film(Fussy(year = 1.0)) == {"year": 1.0}         # nothing to convert: nothing to copy


def test_chainmap_conversion_keeps_its_maps_apart():
    first, second = {"a": 1}, OrderedDict(b = 2)
    out = prices(ChainMap(first, second))
    assert type(out) is ChainMap and len(out.maps) == 2
    assert out.maps[0] == {"a": 1.0} and type(out.maps[0]) is dict
    assert out.maps[1] == {"b": 2.0} and type(out.maps[1]) is OrderedDict
    assert first == {"a": 1} and type(first["a"]) is int    # the caller's maps are untouched
    out["c"] = 3.0                                          # writes go to the first map, as in any ChainMap
    assert "c" in out.maps[0] and "c" not in out.maps[1]


def test_chainmap_entry_hidden_by_an_earlier_map_stays_hidden_and_unconverted():
    out = prices(ChainMap({"a": 1}, {"a": "hidden", "b": 2}))
    assert out["a"] == 1.0 and out.maps[1] == {"a": "hidden", "b": 2.0}
    assert dict(out) == {"a": 1.0, "b": 2.0}


def test_chainmap_without_conversion_and_with_a_bad_value():
    given = ChainMap({"a": 1.0}, {"b": 2.0})
    assert prices(given) is given
    assert _paths(prices, ChainMap({"a": 1.0}, {"b": "x"})) == ["m['b']"]


def test_chainmap_subclass_and_coerced_keys():
    class Layers(ChainMap):
        pass

    @typecheck(deep = True, coerce = True)
    def by_number(m: ChainMap[int, float]) -> Any:
        return m

    out = by_number(Layers({"1": 1}, {"2": "2.5"}))
    assert type(out) is Layers and [dict(m) for m in out.maps] == [{1: 1.0}, {2: 2.5}]


# ═════════════════════════════════════════════════════════════════════════════
#  THE CONSTRAINTS OF A TypeVar HAVE THEIR ITEMS CHECKED (review finding 5)
# ═════════════════════════════════════════════════════════════════════════════

from typing import TypeVar, Union, List, Dict                   # noqa: E402

ListOrMap = TypeVar("ListOrMap", list[int], dict[str, float])


def test_typevar_constraints_are_checked_item_by_item():
    f = _identity(ListOrMap)
    assert f([1, 2]) == [1, 2] and f({"a": 1}) == {"a": 1.0}
    assert _paths(f, ["a"]) == ["x[0]"]
    assert _paths(f, {"a": "x"}) == ["x['a']"]
    with pytest.raises(TypeCheckerError):
        f((1, 2))                                           # neither a list nor a dict


def test_typevar_constraints_without_deep_stay_shallow():
    @typecheck
    def f(x: ListOrMap) -> Any:
        return x

    assert f(["a"]) == ["a"]
    with pytest.raises(TypeCheckerError):
        f(5)


# ═════════════════════════════════════════════════════════════════════════════
#  THE OLD WAY TO WRITE A RECURSIVE ALIAS (review finding 10)
# ═════════════════════════════════════════════════════════════════════════════

OldJson = Union[None, bool, int, float, str, List["OldJson"], Dict[str, "OldJson"]]
OldTree = Union[int, List["OldTree"]]


@typecheck(deep = True)
def load(v: OldJson) -> Any:
    return v


@typecheck(deep = True, check_return = True)
def grow(t: OldTree, twice: "list[OldTree] | None" = None) -> OldTree:
    return t


def test_old_style_recursive_alias_is_checked_at_every_depth():
    document = {"a": [1, {"b": None, "c": [1.5, "x", True]}], "d": {}}
    assert load(document) is document
    assert load(None) is None and load([]) == [] and load("text") == "text"
    assert _paths(load, {"a": [1, {"b": object()}]}) == ["v['a'][1]['b']"]
    assert _paths(load, {1: 1}) == ["v[key 1]"]
    assert _paths(load, [[[b"bytes"]]]) == ["v[0][0][0]"]


def test_old_style_recursive_alias_in_a_second_parameter_and_the_return_value():
    assert grow([1, [2, [3]]], [[4], 5]) == [1, [2, [3]]]
    assert _paths(grow, [1, ["x"]]) == ["t[1][0]"]
    assert _paths(grow, 1, [[1, "x"]]) == ["twice[0][1]"]


def test_old_style_recursive_alias_and_data_that_contains_itself():
    loop: list = []
    loop.append(loop)
    assert [p.kind for p in _raised(load, loop).problems] == ["cycle"]


def test_old_style_recursive_alias_without_deep_still_works():
    @typecheck
    def shallow(v: OldJson) -> Any:
        return v

    assert shallow({"a": object()}) is not None             # only the outer type is looked at
    with pytest.raises(TypeCheckerError):
        shallow(b"bytes")


def test_old_style_recursive_alias_as_a_dataclass_field_and_in_an_enforced_class():
    @dataclass(deep = True)
    class Doc:
        body: OldJson = None

    @enforce(deep = True)
    class Store:
        def put(self, body: OldJson) -> Any:
            return body

    doc = Doc({"a": [1]})
    doc.body = [1, [2]]
    assert Store().put({"k": [None]}) == {"k": [None]}
    for bad in (lambda: Doc({"a": [object()]}), lambda: setattr(doc, "body", [object()]), lambda: Store().put([object()])):
        with pytest.raises(TypeCheckerError) as e:
            bad()
        assert "Cannot resolve" not in _plain(str(e.value))


def test_a_name_in_a_record_is_still_only_read_as_data():
    #* typecheck_from_dict has no module to look in, and must not get one: a record is data.
    record = {"object_name": "f", "record": {"v": List["OldJson"]}, "kwargs": {"v": [1]}, "deep": True}
    with pytest.raises(TypeCheckerError, match = "Cannot resolve"):
        typecheck_from_dict(record)
