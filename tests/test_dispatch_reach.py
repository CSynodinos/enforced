"""
Unreachable versions of a ``dispatch`` (``_dispatch._reach``): what must be caught, what must not be
refused, and, by property, that no refusal is ever wrong (a value the refused version would take
that nothing before it takes).
"""
from collections.abc import Iterable, Iterator, Sequence
from enum import Enum
from typing import Annotated, Any, Literal, NamedTuple, NotRequired, Protocol, TypedDict, Union, runtime_checkable
import itertools
import random

import pytest

from enforced import InvalidDataError, dispatch
from enforced._dispatch._match import compile_anchor
from enforced._dispatch._reach import what_covers
from enforced._validator._type_conversion import FAILED
from enforced.data_types import Email, Port


def pos(n: Any) -> bool:
    return n > 0


def even(n: Any) -> bool:
    return n % 2 == 0


def filled(v: Any) -> bool:
    return len(v) > 0


class Work(Email):
    pass


class Color(Enum):
    RED = 1
    BLUE = 2


class Full(TypedDict):
    a: int
    b: str


class Partial(TypedDict):
    a: int
    b: NotRequired[str]


class Pt(NamedTuple):
    x: int
    y: int


@runtime_checkable
class HasRun(Protocol):
    def run(self) -> None: ...


class Runs:
    def run(self) -> None: ...


class Base:
    pass


class Sub(Base):
    pass


type Json = int | str | list[Json] | dict[str, Json]


def covered(earlier: list[Any], later: Any, allow_subclass: bool = True) -> bool:
    anchors = [compile_anchor(e, allow_subclass, "x", None) for e in earlier]
    return what_covers(compile_anchor(later, allow_subclass, "x", None), anchors, allow_subclass) is not None


# ── what must be caught ─────────────────────────────────────────────────────

CAUGHT = [
    ([Sequence[int]], list[int]), ([int, str], int | str), ([list], list[int]), ([int], Literal[1, 2]),
    ([str], Email), ([Annotated[int, pos]], Annotated[int, pos, even]), ([Iterable[int]], Iterator[str]),
    ([tuple[int, ...]], tuple[int, int]), ([object], list[str]), ([Any], int), ([int], int), ([Json], Json),
    ([bool], Literal[True]), ([Literal[True], Literal[False]], bool), ([Color], Literal[Color.RED]),
    ([Literal[Color.RED, Color.BLUE]], Color), ([None], None), ([type[Base]], type[Sub]), ([type], type[int]),
    ([Full], Full), ([dict], Full), ([Partial], Full), ([Pt], Pt), ([tuple], Pt), ([Email], Email),
    ([HasRun], HasRun), ([Base], Sub), ([tuple[int, *tuple[str, ...]]], tuple[int, str, str]),
    ([Annotated[list[int], filled]], Annotated[list[int], filled, pos]), ([list[int]], Annotated[list[int], filled]),
    ([int | None], Annotated[int, pos] | None), ([Literal[1, 2], int], int), ([Annotated[bool, lambda b: b]], Literal[True]),
    ([Literal["r", "w"]], Literal["w"]), ([dict[str, list[int]]], dict[str, list[int]]), ([Sequence[Json]], list[Json]),
    ([Email | Port], Port), ([list[Email]], list[Work]), ([Any], Annotated[str, filled]),
    ]


@pytest.mark.parametrize("earlier, later", CAUGHT, ids = [f"{e}-{l}" for e, l in CAUGHT])
def test_an_unreachable_version_is_caught(earlier, later):
    assert covered(earlier, later)


def test_strict_mode_catches_by_the_exact_class():
    assert covered([Sequence[int]], list[int], False)               # an abstract class is tested with isinstance
    assert covered([object], int, False) and covered([Base], Base, False) and covered([Literal[1]], Literal[1], False)


# ── what must not be refused ────────────────────────────────────────────────

REACHABLE = [
    ([int], bool), ([list[str]], list[int]), ([Email], str), ([Email], Work), ([int], float), ([Literal[1]], int),
    ([Annotated[int, lambda n: n > 0]], Annotated[int, lambda n: n > 0]),
    ([tuple[int, int]], tuple[int, ...]), ([Sequence[int]], str), ([HasRun], Runs), ([Full], Partial),
    ([type[Sub]], type[Base]), ([dict[str, int]], dict[str, bool]), ([list[int]], list[bool]),
    ([Annotated[int, pos]], int), ([Iterator[int]], Iterable[int]), ([int], int | str), ([int], int | bool),
    ([dict[str, int]], dict[str, bool | int]), ([Literal[Color.RED]], Color), ([list[int]], list[int] | None),
    ([tuple[int, str]], tuple[int, str, str]), ([Pt], tuple[int, int]), ([dict], dict[int, str] | list[int]),
    ([Annotated[list[int], filled]], list[int]), ([Email], Email | Port), ([Literal[True]], bool),
    ([Json], dict[int, int]), ([Port], int),
    ]


@pytest.mark.parametrize("earlier, later", REACHABLE, ids = [f"{e}-{l}" for e, l in REACHABLE])
def test_a_reachable_version_is_never_refused(earlier, later):
    assert not covered(earlier, later)


def test_strict_mode_never_takes_a_subclass_for_its_base():
    assert not covered([Base], Sub, False) and not covered([int], bool, False) and not covered([list], Sequence, False)


# ── the refusal, at register ────────────────────────────────────────────────

def test_the_message_names_each_part_and_who_takes_it():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: int) -> str:
        return "int"

    @f.register
    def _(v: str) -> str:
        return "str"
    with pytest.raises(InvalidDataError) as info:
        @f.register
        def _(v: int | str) -> str:
            return "never"
    assert str(info.value).splitlines() == [
        "dispatch of <Function f>: version 3 (int | str) can never be chosen: what it takes is taken before it",
        "    'int' is taken by version 1 (int)",
        "    'str' is taken by version 2 (str)",
        ]


def test_a_version_that_hides_the_base_is_refused():
    @dispatch
    def f(v: int) -> str:
        return "base"
    with pytest.raises(InvalidDataError, match = r"version 1 \(int\) leaves the base \(int\) unreachable"):
        @f.register
        def _(v: int) -> str:
            return "int"

    @dispatch
    def g(v) -> str:
        return "base"
    with pytest.raises(InvalidDataError, match = r"version 1 \(object\) leaves the base \(Any\) unreachable"):
        @g.register
        def _(v: object) -> str:
            return "all"


def test_an_anchor_that_takes_nothing_is_refused():
    from typing import Never

    @dispatch
    def f(v) -> str:
        return "base"
    with pytest.raises(InvalidDataError, match = "its anchor takes no value"):
        @f.register
        def _(v: Never) -> str:
            return "never"


def test_a_refused_version_leaves_the_dispatcher_as_it_was():
    @dispatch
    def f(v) -> str:
        return "base"

    @f.register
    def _(v: int) -> str:
        return "int"
    before = f.registry()
    with pytest.raises(InvalidDataError):
        f.register(Literal[3], lambda v: "three")
    assert f.registry() == before and f(3) == "int" and f("a") == "base"


def test_together_several_versions_cover_a_union():
    @dispatch
    def f(v) -> str:
        return "base"
    f.register(Literal[True], lambda v: "yes")
    f.register(Literal[False], lambda v: "no")
    with pytest.raises(InvalidDataError, match = "True is taken by version 1"):
        f.register(bool, lambda v: "bool")
    assert f(False) == "no" and f(True) == "yes"


# ── the property: a refusal is never wrong ──────────────────────────────────

ATOMS: list[Any] = [int, str, float, bool, None, bytes, Email, Work, Port, Color, Base, Sub, HasRun, Runs,
                    Literal[1, 2], Literal["a"], Literal[True], Literal[Color.RED], Literal[b"x"],
                    Annotated[int, pos], Annotated[int, pos, even], Annotated[str, filled], type[Base], type[Sub],
                    Full, Partial, Pt, Json, object]


def _random_annotation(rng: random.Random, depth: int = 0) -> Any:
    if depth >= 2 or rng.random() < 0.4:
        return rng.choice(ATOMS)
    inner = _random_annotation(rng, depth + 1)
    other = _random_annotation(rng, depth + 1)
    shape = rng.randrange(12)
    try:
        return [list[inner], set[inner] if _hashable_kind(inner) else list[inner], Sequence[inner], tuple[inner, ...],
                tuple[inner, other], dict[str, inner], Union[inner, other], Iterable[inner], Iterator[inner],
                Annotated[list[inner], filled], tuple[inner, *tuple[other, ...]], Union[list[inner], None]][shape]
    except TypeError:                                   # a union of two that can't be put together
        return inner


def _hashable_kind(annotation: Any) -> bool:
    return annotation in (int, str, bool, bytes, Email, Port, Color) or annotation in ATOMS[14:19]


def _values(annotation: Any, rng: random.Random, depth: int = 0) -> list[Any]:
    """Values of many kinds that ``annotation`` takes, or nearly takes."""
    from typing import get_args, get_origin
    simple = {int: [0, 7, -2], str: ["", "a", "a@b.co"], float: [1.5], bool: [True, False], None: [None],
              bytes: [b"x"], Email: [Email("a@b.co"), "c@d.co"], Work: [Work("w@b.co")], Port: [Port(80), 8080, 0],
              Color: [Color.RED, Color.BLUE], Base: [Base(), Sub()], Sub: [Sub()], HasRun: [Runs()], Runs: [Runs()],
              object: [object()], Full: [{"a": 1, "b": "x"}], Partial: [{"a": 1}, {"a": 1, "b": "x"}], Pt: [Pt(1, 2)],
              Json: [1, "j", [1, ["a"]], {"k": [2]}]}
    if annotation in simple if _hashable(annotation) else False:
        return simple[annotation]
    origin, args = get_origin(annotation), get_args(annotation)
    if depth > 3:
        return [1]
    if origin is Literal:
        return list(args)
    if origin is Annotated:
        return _values(args[0], rng, depth + 1)
    if origin is type:
        return [args[0], Sub, Base, int]
    if args and (origin is None or str(origin).endswith("UnionType") or origin.__class__.__name__ == "_UnionGenericAlias"
                 or getattr(origin, "_name", None) == "Union"):
        return [v for a in args for v in _values(a, rng, depth + 1)]
    items = _values(args[0], rng, depth + 1) if args else [1]
    pick = items[: 3]
    if origin is list:
        return [[], pick, [pick[0]]]
    if origin is set:
        try:
            return [set(), set(pick)]
        except TypeError:
            return [set()]
    if origin is Sequence:
        return [pick, tuple(pick), [], "ab"]
    if origin is dict:
        values = _values(args[1], rng, depth + 1)
        return [{}, {"k": values[0]}, {"k": v for v in values[:2]}]
    if origin in (Iterable, Iterator):
        return [iter(pick), (x for x in pick)]
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return [(), tuple(pick)]
        laid = [(_values(a, rng, depth + 1) if not getattr(a, "__unpacked__", False) else _values(get_args(a)[0], rng, depth + 1))
                for a in args]
        return [tuple(v[0] for v in laid), tuple(v[-1] for v in laid), tuple(v[0] for v in laid) + tuple(laid[-1][:2])]
    return pick


def _hashable(x: Any) -> bool:
    try:
        hash(x)
        return True
    except TypeError:
        return False


POOL = [0, 1, 2, -1, True, False, None, 1.5, "", "a", "w", "a@b.co", b"x", [], [1], ["a"], [1, "a"], [[1]], (), (1,),
        (1, "a"), (1, 2), {}, {"k": 1}, {"k": "a"}, {"a": 1, "b": "x"}, {"a": 1}, set(), {1}, Color.RED, Color.BLUE,
        Email("a@b.co"), Work("w@b.co"), Port(80), 8080, Base(), Sub(), Runs(), Pt(1, 2), Base, Sub, int, object()]


@pytest.mark.parametrize("allow_subclass", [True, False], ids = ["subclass", "strict"])
def test_no_refusal_is_ever_wrong(allow_subclass):
    rng = random.Random(20261023)
    refused = 0
    for _ in range(1500):
        earlier = [_random_annotation(rng) for _ in range(rng.choice((1, 1, 2)))]
        later = _random_annotation(rng)
        if rng.random() < 0.3:                          # a later one built from an earlier one: refusals are likelier
            later = rng.choice([earlier[0], list[earlier[0]] if rng.random() < 0.5 else Union[earlier[0], None]])
        try:
            anchors = [compile_anchor(e, allow_subclass, "x", None) for e in earlier]
            anchor = compile_anchor(later, allow_subclass, "x", None)
        except Exception:
            continue
        if what_covers(anchor, anchors, allow_subclass) is None:
            continue
        refused += 1
        for value in itertools.chain(_values(later, rng), POOL):
            if anchor.take(value) is FAILED:
                continue
            assert any(a.take(value) is not FAILED for a in anchors), (
                f"refused {later!r} after {earlier!r}, yet {value!r} reaches it")
    assert refused > 150                                # the property has refusals to test
