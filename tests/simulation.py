"""
Manual simulation for enforced: every scenario is counted, and the run ends with a
RuntimeError if any of them doesn't behave as expected.

    python tests/simulation.py          # print every check
    python tests/simulation.py -q       # print only failures and the summary

Phase 7 holds the fixes of both code reviews and ends with the known issues: checks that state
the correct behaviour of bugs that aren't fixed yet. They never fail the run; one that starts
passing is announced as FIXED. Phase 8 puts
everything together: a small application end to end, re-entrant construction, threads and
stacked decorators.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from collections import ChainMap, Counter, OrderedDict, defaultdict, deque
from collections.abc import (
    KeysView,
    Collection,
    Generator,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
    Set,
    )
from dataclasses import InitVar, field
from types import MappingProxyType
import types
from typing import (
    IO,
    Annotated,
    Any,
    BinaryIO,
    Callable,
    ClassVar,
    Dict,
    List,
    Literal,
    LiteralString,
    NamedTuple,
    Never,
    NewType,
    NoReturn,
    NotRequired,
    Optional,
    Protocol,
    Required,
    Self,
    TextIO,
    Tuple,
    TypedDict,
    TypeGuard,
    TypeVar,
    Union,
    Unpack,
    runtime_checkable,
    )
from enforced import (
    Check,
    InvalidDataError,
    InvalidDataWarning,
    TypeModel,
    Enforced,
    dataclass,
    enforce_class,
    enforce,
    make_dataclass,
    typecheck,
    typecheck_record,
    typecheck_function,
    )
from enforced.data_types import (
    Email,
    PositiveInt,
    NegativeInt,
    NonNegativeInt,
    Number,
    Port,
    AwareDatetime,
    NonEmptyStr,
    Percentage,
    PhoneNumber,
    Probability,
    SecretStr,
    Slug as DtSlug,                  # the simulation has a Slug model of its own (phase 6)
    Url,
    )
from enforced._formatting_tool import formatter
import enforced._environment as _environment

#* Tiered compilation: here a wrapper is compiled at its first call, so that the second call of a
#* check runs the compiled wrapper, as each scenario expects (ENFORCED_COMPILE_AFTER says otherwise).
_environment.COMPILE_AFTER = int(os.environ.get("ENFORCED_COMPILE_AFTER", "1"))
import asyncio
import contextlib
import copy
import dataclasses
import datetime
import json
import enum
import functools
import inspect
import io
import numbers
import pathlib
import pickle
import re
import tempfile
import threading
import time


QUIET = "-q" in sys.argv[1:]
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ═════════════════════════════════════════════════════════════════════════════
#  HARNESS: every helper counts, so any surprise fails the run
# ═════════════════════════════════════════════════════════════════════════════

_stats = {"ok": 0, "miss": 0, "unexpected": 0}
_failures: list[str] = []
_sections: dict[str, list[int]] = {}     # title -> [passed, total]
_current = "setup"
_known: str | None = None                # set while a known-issue check runs: where the bug is
_open_issues: list[str] = []             # known issues that still reproduce
_fixed_issues: list[str] = []            # known issues that now behave correctly


def section(title: str) -> None:
    global _current
    _current = title
    _sections.setdefault(title, [0, 0])
    if not QUIET:
        print(f"\n{'─' * 72}\n{formatter(f'  {title}', 'bold')}\n{'─' * 72}")


def _passed(tag: str, desc: str) -> None:
    if _known is not None:
        _fixed_issues.append(f"{desc}  ({_known})")
        print(f"  {formatter('FIXED ', 'bold_cyan')} {desc}  ← now correct: make it a regular check")
        return
    _stats["ok"] += 1
    counts = _sections.setdefault(_current, [0, 0])
    counts[0] += 1
    counts[1] += 1
    if not QUIET:
        print(f"  {formatter(f'{tag:<6}', 'bold_green')} {desc}")


def _failed(kind: str, desc: str, detail: str) -> None:
    if _known is not None:
        _open_issues.append(f"{desc}  ({_known})")
        if not QUIET:
            print(f"  {formatter('KNOWN ', 'bold_yellow')} {desc}  ← {detail}")
        return
    _stats[kind] += 1
    _sections.setdefault(_current, [0, 0])[1] += 1
    label = "MISS" if kind == "miss" else "WRONG"
    line = f"[{_current}] {desc}: {detail}"
    _failures.append(f"{formatter(label, 'bold_red')} {line}")
    print(f"  {formatter(f'{label:<6}', 'bold_red')} {desc}  ← {detail}")


def _plain(e: BaseException) -> str:
    return _ANSI.sub("", str(e))


def expect_ok(desc: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """The call must succeed."""
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        _failed("unexpected", desc, f"raised {type(e).__name__}: {_plain(e).splitlines()[-1].strip()}")
        return None
    _passed("OK", desc)
    return result


def expect_raises(desc: str, fn: Callable[..., Any], *args: Any, exc: type[BaseException] = InvalidDataError, **kwargs: Any) -> None:
    """The call must raise ``exc`` (InvalidDataError by default)."""
    try:
        fn(*args, **kwargs)
    except exc:
        _passed("CAUGHT", desc)
        return
    except Exception as e:
        _failed("unexpected", desc, f"expected {exc.__name__}, got {type(e).__name__}: {_plain(e)[:80]}")
        return
    _failed("miss", desc, f"{exc.__name__} not raised")


def expect_message(desc: str, present: tuple[str, ...], fn: Callable[..., Any], *args: Any,
                   absent: tuple[str, ...] = (), **kwargs: Any) -> None:
    """The call must raise InvalidDataError whose plain text contains ``present`` and none of ``absent``."""
    try:
        fn(*args, **kwargs)
    except InvalidDataError as e:
        text = _plain(e)
        lacking = [p for p in present if p not in text]
        leaked = [a for a in absent if a in text]
        if lacking or leaked:
            _failed("unexpected", desc, f"missing {lacking}, unexpected {leaked} in: {' '.join(text.split())}")
        else:
            _passed("MSG", desc)
        return
    except Exception as e:
        _failed("unexpected", desc, f"got {type(e).__name__}: {_plain(e)[:80]}")
        return
    _failed("miss", desc, "InvalidDataError not raised")


def expect_value(desc: str, expected: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """The call must succeed and return ``expected``, with exactly the same type (catches silent conversions)."""
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        _failed("unexpected", desc, f"raised {type(e).__name__}: {_plain(e).splitlines()[-1].strip()}")
        return
    if type(result) is type(expected) and result == expected:
        _passed("VALUE", desc)
    else:
        _failed("unexpected", desc, f"expected {expected!r} ({type(expected).__name__}), "
                                    f"got {result!r} ({type(result).__name__})")


def expect_exact(desc: str, expected: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Like ``expect_value``, but also compares ``repr``, so ``[1]`` vs ``[1.0]`` inside containers counts as different."""
    try:
        result = fn(*args, **kwargs)
    except Exception as e:
        _failed("unexpected", desc, f"raised {type(e).__name__}: {_plain(e).splitlines()[-1].strip()}")
        return
    if type(result) is type(expected) and result == expected and repr(result) == repr(expected):
        _passed("VALUE", desc)
    else:
        clip = lambda v: (r := repr(v)) if len(r) <= 80 else r[:77] + "..."
        _failed("unexpected", desc, f"expected {clip(expected)}, got {clip(result)}")


def known_issue(where: str, expect: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """
    Run one ``expect_*`` check that states the *correct* behaviour of a bug that isn't fixed yet
    (``where`` says where the bug is). It is listed instead of failing the run, and announced as
    FIXED once it passes: then turn it into a regular check.
    """
    global _known
    _known = where
    try:
        expect(*args, **kwargs)
    finally:
        _known = None


def expect_paths(desc: str, paths: tuple[str, ...] | list[str], fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """The call must raise InvalidDataError whose problems point at exactly ``paths``, in order (``e.problems[i].parameter``)."""
    try:
        fn(*args, **kwargs)
    except InvalidDataError as e:
        got = [p.parameter for p in e.problems]
        if got == list(paths):
            _passed("PATH", desc)
        else:
            _failed("unexpected", desc, f"expected paths {list(paths)}, got {got}")
        return
    except Exception as e:
        _failed("unexpected", desc, f"got {type(e).__name__}: {_plain(e)[:80]}")
        return
    _failed("miss", desc, "InvalidDataError not raised")


# ═════════════════════════════════════════════════════════════════════════════
#  SUPPORTING TYPES
# ═════════════════════════════════════════════════════════════════════════════

class Animal: ...
class Dog(Animal): ...
class Cat(Animal): ...
class Unrelated: ...

class Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"

class Point(NamedTuple):
    x: float
    y: float

class Config(TypedDict):
    host: str
    port: int

@runtime_checkable
class Drawable(Protocol):
    def draw(self) -> None: ...

class Circle:
    def draw(self) -> None: pass

class Square:
    def draw(self) -> None: pass

class NoDrawMethod: ...

type Vector2D      = tuple[float, float]
type JsonValue     = str | int | float | bool | None
type Matrix        = list[list[float]]
type Coords        = list[Vector2D]
type AnimalOrColor = Animal | Color

UserId = NewType("UserId", int)

class _Level(enum.IntEnum):
    HIGH = 2


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 1: one function, 61 typed parameters, one scenario per override
# ═════════════════════════════════════════════════════════════════════════════

@typecheck
def process(
    # primitives
    p_int:            int,
    p_str:            str,
    p_float:          float,
    p_bool:           bool,
    p_bytes:          bytes,
    p_complex:        complex,
    # NoneType
    p_none:           None,
    # bare builtins
    p_list:           list,
    p_tuple:          tuple,
    p_dict:           dict,
    p_set:            set,
    p_frozenset:      frozenset,
    # generic builtins (inner type not checked by default; see phase 5)
    p_list_int:       list[int],
    p_tuple_fixed:    tuple[int, str],
    p_tuple_variadic: tuple[float, ...],
    p_dict_str_int:   dict[str, int],
    p_set_str:        set[str],
    p_frozenset_int:  frozenset[int],
    # Union
    p_union_new:      int | str,
    p_union_old:      Union[int, str],
    p_union_three:    int | str | bytes,
    p_union_four:     int | str | bytes | None,
    p_union_custom:   Animal | Color,
    # Optional
    p_optional:       Optional[str],
    p_optional_new:   float | None,
    # Literal
    p_literal_str:    Literal["fast", "slow", "medium"],
    p_literal_int:    Literal[1, 2, 3],
    p_literal_bool:   Literal[True],
    p_literal_none:   Literal[None],
    p_literal_mixed:  Literal[42, "yes", True, None],
    # Any
    p_any:            Any,
    # Callable
    p_callable_typed: Callable[[int], str],
    p_callable_any:   Callable[..., Any],
    p_callable_noret: Callable[[], None],
    # type[]
    p_type_builtin:   type[int],
    p_type_custom:    type[Animal],
    # Annotated (metadata ignored, base type enforced)
    p_ann_int:        Annotated[int, "positive"],
    p_ann_str:        Annotated[str, {"min_length": 1}],
    p_ann_list:       Annotated[list[float], "sorted"],
    # collections.abc
    p_sequence:       Sequence[int],
    p_mut_seq:        MutableSequence[str],
    p_mapping:        Mapping[str, int],
    p_mut_map:        MutableMapping[str, Any],
    p_iterable:       Iterable[int],
    p_iterator:       Iterator[str],
    # custom classes
    p_animal:         Animal,
    p_dog:            Dog,
    p_color:          Color,
    p_point:          Point,
    p_drawable:       Drawable,
    # TypedDict
    p_config:         Config,
    # TypeAliasType (PEP 695)
    p_vector2d:       Vector2D,
    p_json_value:     JsonValue,
    p_matrix:         Matrix,
    p_coords:         Coords,
    # forward references (string annotations)
    p_fwd_int:        "int",
    p_fwd_animal:     "Animal",
    p_fwd_union:      "int | str",
    p_fwd_alias:      "Vector2D",
    # nested generics (outer type only by default; see phase 5)
    p_nested_list:    list[dict[str, int]],
    p_nested_dict:    dict[str, list[float]],
) -> dict[str, Any]:
    return locals()             # lets scenarios see what the function actually received


VALID = dict(
    p_int=1,                        p_str="hello",
    p_float=3.14,                   p_bool=True,
    p_bytes=b"data",                p_complex=1 + 2j,
    p_none=None,
    p_list=[1, 2],                  p_tuple=(1, 2),
    p_dict={"a": 1},                p_set={1, 2},
    p_frozenset=frozenset({1}),
    p_list_int=[1, 2],              p_tuple_fixed=(1, "hi"),
    p_tuple_variadic=(1.0, 2.0),    p_dict_str_int={"a": 1},
    p_set_str={"a", "b"},           p_frozenset_int=frozenset({1, 2}),
    p_union_new=1,                  p_union_old="hi",
    p_union_three=b"bytes",         p_union_four=None,
    p_union_custom=Color.RED,
    p_optional=None,                p_optional_new=3.14,
    p_literal_str="fast",           p_literal_int=2,
    p_literal_bool=True,            p_literal_none=None,
    p_literal_mixed="yes",
    p_any="anything",
    p_callable_typed=str,           p_callable_any=print,
    p_callable_noret=lambda: None,
    p_type_builtin=int,             p_type_custom=Dog,
    p_ann_int=5,                    p_ann_str="hello",
    p_ann_list=[1.0, 2.0],
    p_sequence=[1, 2],              p_mut_seq=["a"],
    p_mapping={"a": 1},             p_mut_map={"x": 1},
    p_iterable=[1, 2],              p_iterator=iter(["a"]),
    p_animal=Dog(),                 p_dog=Dog(),
    p_color=Color.RED,              p_point=Point(1.0, 2.0),
    p_drawable=Circle(),
    p_config={"host": "localhost", "port": 8080},
    p_vector2d=(1.0, 2.0),          p_json_value=42,
    p_matrix=[[1.0, 2.0]],          p_coords=[(1.0, 2.0)],
    p_fwd_int=1,                    p_fwd_animal=Animal(),
    p_fwd_union="hi",               p_fwd_alias=(1.0, 2.0),
    p_nested_list=[{"a": 1}],       p_nested_dict={"a": [1.0]},
)


def good(desc: str, **overrides: Any) -> None:
    expect_ok(desc, process, **{**VALID, **overrides})


def bad(param: str, value: Any, desc: str) -> None:
    expect_raises(f"{param}: {desc}", process, **{**VALID, param: value})


def received(desc: str, param: str, value: Any, expected: Any) -> None:
    """``process`` must accept ``value`` for ``param`` and see exactly ``expected`` inside."""
    expect_value(desc, expected, lambda: process(**{**VALID, param: value})[param])


section("phase 1 · baseline: all 61 params with correct types")
good("full valid call")
expect_ok("all 61 params passed positionally", process, *VALID.values())

section("phase 1 · primitives")
bad("p_int",     "1",      "str instead of int")
bad("p_str",     42,       "int instead of str")
bad("p_float",   "3.14",   "str instead of float")
bad("p_bool",    1,        "int 1 is not bool")
bad("p_bytes",   "data",   "str instead of bytes")
bad("p_complex", "1+2j",   "str instead of complex")
bad("p_int",     3.0,      "float 3.0 is not int (narrowing needs coerce=True)")
received("int for float converted (default convert=True)", "p_float", 3, 3.0)
received("int for complex converted", "p_complex", 2, 2 + 0j)
bad("p_float",   True,     "bool is never converted to float")
bad("p_int",     True,     "bool is not accepted as an int")
bad("p_int",     False,    "False is not accepted as an int either")
bad("p_union_new", True,   "bool not in int | str")
received("IntEnum member is still an int", "p_int", _Level.HIGH, _Level.HIGH)

section("phase 1 · NoneType")
bad("p_none", 0,     "0 is not None")
bad("p_none", False, "False is not None")

section("phase 1 · bare builtins")
bad("p_list",      (1, 2),     "tuple not list")
bad("p_tuple",     [1, 2],     "list not tuple")
bad("p_dict",      [("a", 1)], "list-of-tuples not dict")
bad("p_set",       [1, 2],     "list not set")
bad("p_frozenset", {1, 2},     "mutable set not frozenset")

section("phase 1 · generic builtins (outer type only by default)")
bad("p_list_int",       (1, 2),     "tuple not list[int]")
bad("p_tuple_fixed",    [1, "hi"],  "list not tuple[int, str]")
bad("p_tuple_variadic", [1.0, 2.0], "list not tuple[float, ...]")
bad("p_dict_str_int",   "a=1",      "str not dict[str, int]")
bad("p_set_str",        ["a", "b"], "list not set[str]")
bad("p_frozenset_int",  {1, 2},     "mutable set not frozenset[int]")
good("list[int] inner not checked: list[str] passes",     p_list_int=["a", "b"])
good("dict[str, int] inner not checked: {int: str} passes", p_dict_str_int={1: "flip"})

section("phase 1 · Union")
bad("p_union_new",    3.14,  "float not in int | str")
bad("p_union_old",    3.14,  "float not in Union[int, str]")
bad("p_union_three",  3.14,  "float not in int | str | bytes")
bad("p_union_four",   3.14,  "float not in int | str | bytes | None")
bad("p_union_custom", "red", "str not in Animal | Color")
good("Dog() satisfies the Animal branch",      p_union_custom=Dog())
good("Color.BLUE satisfies the Color branch",  p_union_custom=Color.BLUE)

section("phase 1 · Optional")
bad("p_optional",     42,     "int not in Optional[str]")
bad("p_optional_new", "3.14", "str not in float | None")
good("Optional[str]: None",  p_optional=None)
good("Optional[str]: str",   p_optional="hello")
good("float | None: None",   p_optional_new=None)
received("float | None: int converted to float", "p_optional_new", 2, 2.0)

section("phase 1 · Literal")
bad("p_literal_str",   "turbo", "not in Literal['fast', 'slow', 'medium']")
bad("p_literal_str",   1,       "int not in str Literal")
bad("p_literal_int",   4,       "4 not in Literal[1, 2, 3]")
bad("p_literal_int",   "2",     "str '2' not in int Literal")
bad("p_literal_int",   2.0,     "2.0 not in Literal[1, 2, 3] (Literal is never converted)")
bad("p_literal_bool",  False,   "False not in Literal[True]")
bad("p_literal_bool",  1,       "int 1 is not Literal[True]")
bad("p_literal_none",  0,       "0 not in Literal[None]")
bad("p_literal_none",  False,   "False not in Literal[None]")
bad("p_literal_mixed", "no",    "not in Literal[42, 'yes', True, None]")
bad("p_literal_mixed", 43,      "43 not in Literal")
bad("p_literal_int",   [1],     "unhashable input: InvalidDataError, not a raw TypeError")

section("phase 1 · Any")
good("Any accepts int",    p_any=99)
good("Any accepts None",   p_any=None)
good("Any accepts list",   p_any=[1, 2, 3])
good("Any accepts custom", p_any=Dog())

section("phase 1 · Callable")
bad("p_callable_typed", "not_fn", "str not Callable")
bad("p_callable_typed", 42,       "int not Callable")
bad("p_callable_any",   "not_fn", "str not Callable[...]")
bad("p_callable_noret", 42,       "int not Callable[[], None]")
good("lambda is Callable", p_callable_typed=lambda x: str(x))
good("class is Callable",  p_callable_any=Dog)

section("phase 1 · type[]")
bad("p_type_builtin", 42,       "instance instead of type[int]")
bad("p_type_builtin", str,      "str is not type[int]")
bad("p_type_custom",  Animal(), "instance instead of type[Animal]")
bad("p_type_custom",  int,      "int not type[Animal]")
good("bool is a subclass of int",    p_type_builtin=bool)
good("Dog is a subclass of Animal",  p_type_custom=Dog)

section("phase 1 · Annotated (non-check metadata ignored, base type enforced)")
bad("p_ann_int",  "five",   "str not int")
bad("p_ann_int",  None,     "None not int")
bad("p_ann_str",  42,       "int not str")
bad("p_ann_list", "sorted", "str not list")

section("phase 1 · collections.abc")
bad("p_sequence", 42,          "int not Sequence")
bad("p_sequence", {1, 2},      "set not Sequence")
bad("p_mut_seq",  (1, 2),      "tuple is immutable: not MutableSequence")
bad("p_mapping",  [("a", 1)],  "list not Mapping")
bad("p_mapping",  "a=1",       "str not Mapping")
bad("p_mut_map",  (("a", 1),), "tuple not MutableMapping")
bad("p_iterable", 42,          "int not Iterable")
bad("p_iterator", [1, 2],      "list is Iterable but not Iterator")
bad("p_iterator", 42,          "int not Iterator")
good("tuple is a Sequence", p_sequence=(1, 2, 3))
good("set is Iterable",     p_iterable={1, 2})
good("str is Iterable",     p_iterable="abc")

section("phase 1 · custom classes and subclasses")
bad("p_animal", "animal", "str not Animal")
bad("p_animal", 42,       "int not Animal")
bad("p_dog",    Animal(), "Animal() is a superclass of Dog")
bad("p_dog",    Cat(),    "Cat() is a sibling, not Dog")
good("Dog() satisfies Animal", p_animal=Dog())
good("Cat() satisfies Animal", p_animal=Cat())

section("phase 1 · Enum, NamedTuple, Protocol, TypedDict")
bad("p_color",    "red",                "raw str not Color (coercion is off)")
bad("p_color",    1,                    "raw int not Color")
good("Color.GREEN",                     p_color=Color.GREEN)
bad("p_point",    (1.0, 2.0),           "plain tuple not Point")
bad("p_point",    {"x": 1.0, "y": 2.0}, "dict not Point")
bad("p_point",    [1.0, 2.0],           "list not Point")
bad("p_drawable", NoDrawMethod(),       "missing draw(): not Drawable")
bad("p_drawable", "circle",             "str not Drawable")
good("Square has draw()",               p_drawable=Square())
good("ad-hoc class with draw()",        p_drawable=type("Hex", (), {"draw": lambda self: None})())
bad("p_config",   "localhost:8080",     "str not Config")
bad("p_config",   ("localhost", 80),    "tuple not Config")

section("phase 1 · TypeAliasType (PEP 695)")
bad("p_vector2d",   [1.0, 2.0], "list not tuple (Vector2D = tuple[float, float])")
bad("p_vector2d",   "1.0,2.0",  "str not Vector2D")
bad("p_json_value", [1, 2],     "list not JsonValue")
bad("p_json_value", {"k": "v"}, "dict not JsonValue")
bad("p_matrix",     "matrix",   "str not Matrix")
bad("p_matrix",     (1.0, 2.0), "tuple not Matrix")
bad("p_coords",     "coords",   "str not Coords")
good("JsonValue: str",               p_json_value="hello")
good("JsonValue: None",              p_json_value=None)
good("Matrix inner not checked",     p_matrix=[["a", "b"]])
good("Coords inner not checked",     p_coords=[[1, 2]])

section("phase 1 · forward references (string annotations)")
bad("p_fwd_int",    "1",        "str not 'int'")
bad("p_fwd_int",    None,       "None not 'int'")
bad("p_fwd_animal", "animal",   "str not 'Animal'")
bad("p_fwd_animal", 42,         "int not 'Animal'")
bad("p_fwd_union",  3.14,       "float not in 'int | str'")
bad("p_fwd_union",  None,       "None not in 'int | str'")
bad("p_fwd_alias",  [1.0, 2.0], "list not 'Vector2D'")
good("'int': int",          p_fwd_int=42)
good("'Animal': Dog()",     p_fwd_animal=Dog())
good("'int | str': int",    p_fwd_union=1)
good("'int | str': str",    p_fwd_union="hi")
good("'Vector2D': tuple",   p_fwd_alias=(3.0, 4.0))

section("phase 1 · nested generics (outer type only by default)")
bad("p_nested_list", "nope",   "str not list[dict[str, int]]")
bad("p_nested_list", {"a": 1}, "dict not list")
bad("p_nested_dict", "nope",   "str not dict[str, list[float]]")
bad("p_nested_dict", [1, 2],   "list not dict")
good("list[list] passes (inner not checked)",  p_nested_list=[[1, 2]])
good("{str: str} passes (inner not checked)",  p_nested_dict={"a": "x"})


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 2: small focused functions
# ═════════════════════════════════════════════════════════════════════════════

@typecheck
def takes_animal(a: Animal) -> None: pass
@typecheck
def takes_dog(d: Dog) -> None: pass
@typecheck
def takes_color(c: Color) -> None: pass
@typecheck
def takes_point(p: Point) -> None: pass
@typecheck
def takes_config(cfg: Config) -> None: pass
@typecheck
def takes_drawable(d: Drawable) -> None: pass
@typecheck
def takes_json(v: JsonValue) -> None: pass
@typecheck
def takes_vector(v: Vector2D) -> None: pass
@typecheck
def takes_matrix(m: Matrix) -> None: pass
@typecheck
def takes_animal_or_color(x: AnimalOrColor) -> None: pass
@typecheck
def takes_coords(c: Coords) -> None: pass
@typecheck
def takes_annotated(x: Annotated[int, "positive", "non-zero"]) -> None: pass
@typecheck
def takes_union_three(x: int | str | bytes) -> None: pass
@typecheck
def takes_literal_mixed(x: Literal[1, "on", True, None]) -> None: pass
@typecheck
def takes_nested_mapping(m: Mapping[str, list[int]]) -> None: pass
@typecheck
def takes_callable_typed(fn: Callable[[int, str], bool]) -> None: pass
@typecheck
def takes_type_ref(cls: type[Animal]) -> None: pass
@typecheck
def takes_type_or_none(cls: type[Animal] | None = None) -> Any: return cls
@typecheck
def takes_type_or_str(cls: type[Animal] | str) -> Any: return cls
@typecheck
def takes_either_type(cls: type[Animal] | type[Color]) -> Any: return cls
@typecheck
def takes_iterator(it: Iterator[int]) -> None: pass
@typecheck
def forward_ref_animal(a: "Animal") -> "Animal": return a
@typecheck
def forward_ref_union(x: "int | str") -> None: pass
@typecheck
def forward_ref_alias(v: "Vector2D") -> None: pass


section("phase 2 · subclass / inheritance")
expect_ok("Animal() satisfies Animal",        takes_animal, Animal())
expect_ok("Dog() satisfies Animal",           takes_animal, Dog())
expect_ok("Cat() satisfies Animal",           takes_animal, Cat())
expect_raises("Unrelated() fails Animal",     takes_animal, Unrelated())
expect_ok("Dog() satisfies Dog",              takes_dog, Dog())
expect_raises("Animal() fails Dog",           takes_dog, Animal())
expect_raises("Cat() fails Dog",              takes_dog, Cat())

section("phase 2 · Enum / NamedTuple / TypedDict / Protocol")
expect_ok("Color.RED",                        takes_color, Color.RED)
expect_raises("'red' fails Color",            takes_color, "red")
expect_raises("1 fails Color",                takes_color, 1)
expect_ok("Point(1, 2)",                      takes_point, Point(1.0, 2.0))
expect_raises("plain tuple fails Point",      takes_point, (1.0, 2.0))
expect_raises("dict fails Point",             takes_point, {"x": 1.0, "y": 2.0})
expect_ok("valid Config dict",                takes_config, {"host": "localhost", "port": 8080})
expect_raises("str fails Config",             takes_config, "localhost:8080")
expect_raises("list fails Config",            takes_config, ["localhost", 8080])
expect_ok("Circle is Drawable",               takes_drawable, Circle())
expect_ok("Square is Drawable",               takes_drawable, Square())
expect_raises("NoDrawMethod fails Drawable",  takes_drawable, NoDrawMethod())
expect_raises("str fails Drawable",           takes_drawable, "not drawable")

section("phase 2 · aliases")
expect_ok("JsonValue: str",                   takes_json, "hello")
expect_ok("JsonValue: int",                   takes_json, 42)
expect_ok("JsonValue: None",                  takes_json, None)
expect_raises("JsonValue: list fails",        takes_json, [1, 2])
expect_ok("Vector2D: tuple",                  takes_vector, (1.0, 2.0))
expect_raises("Vector2D: list fails",         takes_vector, [1.0, 2.0])
expect_ok("Matrix: list[list]",               takes_matrix, [[1.0, 2.0], [3.0, 4.0]])
expect_ok("Matrix: inner not checked",        takes_matrix, [["a", "b"]])
expect_raises("Matrix: str fails",            takes_matrix, "not a matrix")
expect_ok("Coords: list of tuples",           takes_coords, [(1.0, 2.0), (3.0, 4.0)])
expect_ok("Coords: inner not checked",        takes_coords, [1, 2, 3])
expect_raises("Coords: str fails",            takes_coords, "nope")
expect_ok("AnimalOrColor: Dog()",             takes_animal_or_color, Dog())
expect_ok("AnimalOrColor: Color.RED",         takes_animal_or_color, Color.RED)
expect_raises("AnimalOrColor: 'red' fails",   takes_animal_or_color, "red")
expect_raises("AnimalOrColor: 42 fails",      takes_animal_or_color, 42)

section("phase 2 · Annotated / Union / Literal")
expect_ok("Annotated[int]: 5",                takes_annotated, 5)
expect_raises("Annotated[int]: str fails",    takes_annotated, "five")
expect_raises("Annotated[int]: None fails",   takes_annotated, None)
expect_ok("int | str | bytes: int",           takes_union_three, 99)
expect_ok("int | str | bytes: str",           takes_union_three, "hi")
expect_ok("int | str | bytes: bytes",         takes_union_three, b"hi")
expect_raises("int | str | bytes: float fails", takes_union_three, 3.14)
expect_raises("int | str | bytes: list fails",  takes_union_three, [1])
for value in (1, "on", True, None):
    expect_ok(f"Literal[1, 'on', True, None]: {value!r}", takes_literal_mixed, value)
for value in (2, "off", False):
    expect_raises(f"Literal[1, 'on', True, None]: {value!r} fails", takes_literal_mixed, value)

section("phase 2 · Mapping / Callable / type[] / Iterator")
expect_ok("Mapping: valid dict",              takes_nested_mapping, {"a": [1, 2]})
expect_ok("Mapping: inner not checked",       takes_nested_mapping, {"a": ["x"]})
expect_raises("Mapping: int fails",           takes_nested_mapping, 42)
expect_raises("Mapping: list fails",          takes_nested_mapping, [("a", [1])])
expect_ok("Callable: lambda",                 takes_callable_typed, lambda x, s: True)
expect_ok("Callable: builtin",                takes_callable_typed, isinstance)
expect_raises("Callable: str fails",          takes_callable_typed, "not callable")
expect_raises("Callable: 42 fails",           takes_callable_typed, 42)
expect_ok("type[Animal]: Animal",             takes_type_ref, Animal)
expect_ok("type[Animal]: Dog",                takes_type_ref, Dog)
expect_raises("type[Animal]: instance fails", takes_type_ref, Animal())
expect_raises("type[Animal]: int fails",      takes_type_ref, int)
expect_value("type[Animal] | None: the None default", None, takes_type_or_none)
expect_value("type[Animal] | None: Dog",      Dog, takes_type_or_none, Dog)
expect_raises("type[Animal] | None: int fails", takes_type_or_none, int)
expect_raises("type[Animal] | None: instance fails", takes_type_or_none, Animal())
expect_value("type[Animal] | str: a str",     "dog", takes_type_or_str, "dog")
expect_value("type[Animal] | str: Dog",       Dog, takes_type_or_str, Dog)
expect_raises("type[Animal] | str: str (the class) fails", takes_type_or_str, str)
expect_raises("type[Animal] | str: 5 fails",  takes_type_or_str, 5)
expect_value("type[Animal] | type[Color]: Cat", Cat, takes_either_type, Cat)
expect_value("type[Animal] | type[Color]: Color", Color, takes_either_type, Color)
expect_raises("type[Animal] | type[Color]: int fails", takes_either_type, int)
expect_ok("Iterator: iter([...])",            takes_iterator, iter([1, 2, 3]))
expect_raises("Iterator: list fails",         takes_iterator, [1, 2, 3])
expect_raises("Iterator: 42 fails",           takes_iterator, 42)

section("phase 2 · forward references")
expect_ok("'Animal': Dog()",                  forward_ref_animal, Dog())
expect_raises("'Animal': str fails",          forward_ref_animal, "nope")
expect_ok("'int | str': int",                 forward_ref_union, 1)
expect_ok("'int | str': str",                 forward_ref_union, "hi")
expect_raises("'int | str': float fails",     forward_ref_union, 3.14)
expect_ok("'Vector2D': tuple",                forward_ref_alias, (1.0, 2.0))
expect_raises("'Vector2D': list fails",       forward_ref_alias, [1.0, 2.0])


@typecheck
def process_small(
    count: int,
    label: str,
    ratio: float,
    flag: bool,
    data: list[int],
    mapping: dict[str, int],
    mode: Literal["fast", "slow"],
    callback: Callable[..., Any],
    items: Sequence[str],
    optional: Optional[str],
    union: int | bytes,
) -> None:
    pass


CALLBACK = lambda: None
BASE = (1, "hello", 3.14, True, [1, 2], {"a": 1}, "fast", CALLBACK, ["x"], None, 0)


def small(**changes: Any) -> tuple[Any, ...]:
    """BASE with some positions replaced by name."""
    names = ("count", "label", "ratio", "flag", "data", "mapping", "mode", "callback", "items", "optional", "union")
    return tuple(changes.get(n, v) for n, v in zip(names, BASE))


section("phase 2 · 11-param positional calls")
expect_ok("all correct types",                       process_small, *BASE)
expect_ok("optional is a str",                       process_small, *small(optional="opt", union=b"hi"))
expect_ok("union is bytes",                          process_small, *small(union=b"bytes", mode="slow"))
expect_ok("list contents not checked",               process_small, *small(data=["a", "b"]))
expect_ok("ratio given as int is converted",         process_small, *small(ratio=3))
expect_raises("count is str",                        process_small, *small(count="one"))
expect_raises("label is int",                        process_small, *small(label=42))
expect_raises("ratio is str",                        process_small, *small(ratio="3.14"))
expect_raises("flag is int (not bool)",              process_small, *small(flag=1))
expect_raises("data is tuple, not list",             process_small, *small(data=(1, 2)))
expect_raises("mapping is a list",                   process_small, *small(mapping=[("a", 1)]))
expect_raises("mode not in Literal",                 process_small, *small(mode="turbo"))
expect_raises("callback is not callable",            process_small, *small(callback="not_callable"))
expect_raises("items is not a Sequence",             process_small, *small(items=42))
expect_raises("optional is int",                     process_small, *small(optional=99))
expect_raises("union is float",                      process_small, *small(union=3.14))
expect_message("several wrong args reported together", ("3 problems found in call",),
               process_small, *small(count="one", label=42, mode="turbo"))


@typecheck
def bind_target(a: int, /, b: str, *, c: float) -> None:
    pass


section("phase 2 · call binding")
expect_ok("positional + keyword",                    bind_target, 1, "x", c=1.5)
expect_raises("missing keyword-only c",              bind_target, 1, "x")
expect_message("missing c is named with its type",   ("c (expecting type float)",), bind_target, 1, "x")
expect_raises("unexpected keyword",                  bind_target, 1, "x", c=1.5, d=2)
expect_raises("multiple values for b",               bind_target, 1, "x", b="y", c=1.5)
expect_raises("positional-only passed as keyword",   bind_target, a=1, b="x", c=1.5)


def base_accept(a: Animal) -> None:
    pass


section("phase 2 · subclass policy toggle")
checked_default = typecheck(base_accept)
checked_strict = typecheck(base_accept, allow_subclass=False)
expect_ok("allow_subclass=True accepts Dog",         checked_default, Dog())
expect_raises("allow_subclass=False rejects Dog",    checked_strict, Dog())
expect_ok("allow_subclass=False accepts Animal",     checked_strict, Animal())


class Service:
    def __init__(self) -> None:
        self._size = 0

    @typecheck
    def instance(self, x: int) -> None:
        self._size = x

    @classmethod
    @typecheck
    def make(cls, name: str) -> str:
        return name

    @staticmethod
    @typecheck
    def parse(v: float) -> float:
        return v

    @property
    def size(self) -> int:
        return self._size

    @size.setter
    @typecheck
    def size(self, value: int) -> None:
        self._size = value


section("phase 2 · methods and descriptors")
svc = Service()
expect_ok("instance method",                         svc.instance, 10)
expect_raises("instance method, bad arg",            svc.instance, "ten")
expect_ok("classmethod",                             Service.make, "alpha")
expect_raises("classmethod, bad arg",                Service.make, 123)
expect_ok("staticmethod",                            Service.parse, 1.25)
expect_raises("staticmethod, bad arg",               Service.parse, "1.25")
expect_value("staticmethod, int converted to float", 2.0, Service.parse, 2)
expect_ok("property setter",                         setattr, svc, "size", 3)
expect_raises("property setter, bad value",          setattr, svc, "size", "large")


@typecheck
async def async_worker(x: int) -> str:
    return str(x)

@typecheck(check_return=True)
async def async_bad_return(x: int) -> str:
    return x                    # type: ignore[return-value]

@typecheck
def make_iter(n: int) -> Iterator[int]:
    yield from range(n)


section("phase 2 · async and generators")
expect_value("async, valid arg",                     "5", lambda: asyncio.run(async_worker(5)))
expect_raises("async, bad arg raises when awaited",  lambda: asyncio.run(async_worker("5")))
expect_raises("async, bad return",                   lambda: asyncio.run(async_bad_return(1)))
expect_value("generator, valid arg",                 [0, 1, 2], lambda: list(make_iter(3)))
expect_raises("generator, bad arg raises on call",   make_iter, "3")


@typecheck
def unresolved_ref(x: "DoesNotExist") -> None:          # noqa: F821
    pass

@typecheck
def late_alias_fn(x: "LateAlias") -> None:
    pass

type LateAlias = int | str

@typecheck
def takes_user_id(user_id: UserId) -> None:
    pass


section("phase 2 · forward refs, aliases, NewType")
expect_message("unresolved forward ref",             ("DoesNotExist",), unresolved_ref, 1)
expect_ok("late-bound alias: int",                   late_alias_fn, 10)
expect_ok("late-bound alias: str",                   late_alias_fn, "ten")
expect_raises("late-bound alias: float fails",       late_alias_fn, 3.14)
expect_ok("NewType value",                           takes_user_id, UserId(7))
expect_raises("NewType rejects str",                 takes_user_id, "7")


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 3: defaults, messages, returns, classes, varargs, strict, typecheck_record, dataclass
# ═════════════════════════════════════════════════════════════════════════════

@typecheck
def d_good(x: int = 5) -> int:
    return x

@typecheck
def d_bad(x: int = "five") -> None:                      # type: ignore[assignment]
    pass

@typecheck
def d_bad_and_missing(x: int, y: str = 5) -> None:       # type: ignore[assignment]
    pass

@typecheck
def d_none_no_optional(x: int = None) -> None:           # type: ignore[assignment]
    pass

@typecheck
def d_none_optional(x: int | None = None) -> None:
    pass

@typecheck
def d_kwonly_bad(*, k: int = "x") -> None:               # type: ignore[assignment]
    pass

@typecheck
def d_literal_bad(mode: Literal["fast", "slow"] = "turbo") -> None:   # type: ignore[assignment]
    pass

@typecheck
def d_two_bad(a: int = "x", b: str = 1, c: float = 1.0) -> None:      # type: ignore[assignment]
    pass

@enforce
class DService:
    def run(self, retries: int = "three") -> None:       # type: ignore[assignment]
        pass


section("phase 3 · defaults")
expect_value("valid default used",                   5, d_good)
expect_raises("bad default, not supplied",           d_bad)
expect_raises("bad default, even when supplied",     d_bad, 5)
expect_raises("bad default raises on every call",    d_bad)
expect_message("bad default reported before missing argument",
               ("definition", "default"), d_bad_and_missing, absent=("Missing",))
expect_message("two bad defaults reported together", ("2 problems found in definition",), d_two_bad)
expect_raises("x: int = None (no implicit Optional)", d_none_no_optional, 1)
expect_ok("x: int | None = None",                    d_none_optional)
expect_raises("keyword-only bad default",            d_kwonly_bad, k=1)
expect_raises("Literal bad default",                 d_literal_bad, "fast")
expect_raises("method bad default via class decorator", DService().run)


@typecheck
def m_three(a: int, b: int, c: int) -> None: pass

@typecheck
def m_shift(a: int, b: float, c: str) -> None: pass

@typecheck
def m_ambiguous(a: str, b: str) -> None: pass


section("phase 3 · missing argument messages")
expect_message("all missing arguments listed",
               ("a (expecting type int)", "b (expecting type int)", "c (expecting type int)"), m_three)
expect_message("shifted call inferred from types",
               ("a (expecting type int), b (expecting type float)", "(inferred)", "1 problem"), m_shift, "hello")
expect_message("ambiguous call not inferred",
               ("b (expecting type str)",), m_ambiguous, "x", absent=("(inferred)",))
expect_raises("too many positional arguments",       m_ambiguous, "a", "b", "c")


@typecheck
def r_unchecked() -> str:
    return 1                                             # type: ignore[return-value]

@typecheck(check_return=True)
def r_none_violated() -> None:
    return 42                                            # type: ignore[return-value]

@typecheck(check_return=True)
def r_noreturn_returns() -> NoReturn:
    pass                                                 # type: ignore[misc]

@typecheck(check_return=True)
def r_never_raises() -> Never:
    raise RuntimeError("always")

@typecheck(check_return=True)
def r_union_ok(flag: bool) -> int | str:
    return 1 if flag else "one"


section("phase 3 · return checking")
expect_value("return not checked by default",        1, r_unchecked)
expect_raises("-> None returning 42",                r_none_violated)
expect_raises("-> NoReturn returning normally",      r_noreturn_returns)
expect_raises("-> Never: original exception propagates", r_never_raises, exc=RuntimeError)
expect_value("-> int | str returning int",           1, r_union_ok, True)
expect_value("-> int | str returning str",           "one", r_union_ok, False)


def logged_method(fn: Callable[..., Any]) -> Callable[..., Any]:
    """An ordinary decorator that uses functools.wraps."""
    @functools.wraps(fn)
    def inner(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)
    return inner


@enforce(check_return=True)
class CBuilder:
    def __init__(self, name: str) -> None:
        self.name = name

    def rename(self, name: str) -> Self:
        self.name = name
        return self

    def broken(self) -> Self:
        return 42                                        # type: ignore[return-value]

    @staticmethod
    def parse(v: float) -> float:
        return v

    @classmethod
    def make(cls, name: str) -> "CBuilder":
        return cls(name)

    def __eq__(self, other: "CBuilder") -> bool:         # type: ignore[override]
        return False

@enforce
class CEmpty:
    pass


section("phase 3 · class decorator")
expect_ok("__init__ valid",                          CBuilder, "a")
expect_raises("__init__ invalid",                    CBuilder, 1)
expect_ok("method returning Self",                   CBuilder("a").rename, "b")
expect_raises("method, bad arg",                     CBuilder("a").rename, 1)
expect_raises("method returning non-Self",           CBuilder("a").broken)
expect_ok("staticmethod",                            CBuilder.parse, 1.5)
expect_raises("staticmethod, bad arg",               CBuilder.parse, "1.5")
expect_ok("classmethod",                             CBuilder.make, "a")
expect_raises("classmethod, bad arg",                CBuilder.make, 1)
expect_value("dunder __eq__ left unchecked",         False, lambda: CBuilder("a") == "not a builder")
expect_ok("class without its own __init__",          CEmpty)
expect_value("enforced returns the class itself",    True, lambda: enforce(CEmpty) is CEmpty and enforce(deep=True)(CEmpty) is CEmpty)


@enforce(check_return=True)
class EReport:
    def __init__(self, title: str) -> None:
        self.title = title

    def add(self, line: str) -> int:
        return len(line)

    @enforce.exempt
    def render(self, sink: int) -> int:                  # annotated, and left alone
        return sink                                      # type: ignore[return-value]

    @enforce.exempt
    @classmethod
    def blank(cls, title: int) -> Any:
        return title

    @staticmethod
    @enforce.exempt
    def width(columns: int) -> Any:
        return columns

    @typecheck(coerce=True)
    def pages(self, count: int) -> int:                  # its own options: looser than the class
        return count

    @typecheck(allow_subclass=False, check_return=True)
    def owner(self, other: Self, by: Animal) -> Self:    # its own options: stricter than the class
        return other

    def keeper(self, by: Animal) -> Animal:
        return by

    @logged_method
    @typecheck(coerce=True)
    def copies(self, count: int) -> int:                 # its own typecheck below another decorator
        return count

class EChild(EReport):                                   # not decorated
    def add(self, line: str) -> Any:                     # type: ignore[override]
        return line

    def extra(self, n: int) -> Any:
        return n

@enforce
class EChecked(EReport):
    def extra(self, n: int) -> Any:
        return n

@dataclasses.dataclass
class EStdData:
    x: int

@dataclass
class EData:
    x: int

    @typecheck
    def moved(self, dx: int) -> int:
        return self.x + dx

class EPlainSub(EData):                                  # a plain subclass of a dataclass
    def label(self, prefix: str) -> str:
        return f"{prefix}{self.x}"


def _e_wrapped(cls: type, name: str) -> bool:
    """Whether the class's own attribute ``name`` is (or holds) a wrapper made by enforced."""
    member = vars(cls)[name]
    return "_pv_bootstrap" in getattr(getattr(member, "__func__", member), "__globals__", {})


section("phase 3 · enforced: skipped methods, a method's own options, what each decorator refuses")
e_report = EReport("q3")
expect_raises("the other methods are still checked",                 e_report.add, 1)
expect_value("enforce.exempt: argument and return value pass",       "anything", e_report.render, "anything")
expect_value("enforce.exempt above @classmethod",                    "t", EReport.blank, "t")
expect_value("enforce.exempt below @staticmethod",                   "w", EReport.width, "w")
expect_value("enforce.exempt: the methods are left as they were",    [False, False, False],
             lambda: [_e_wrapped(EReport, name) for name in ("render", "blank", "width")])
expect_value("enforce.exempt: still a classmethod, a staticmethod",  (True, True),
             lambda: (isinstance(vars(EReport)["blank"], classmethod), isinstance(vars(EReport)["width"], staticmethod)))
expect_exact("own @typecheck(coerce=True) under a class without",    42, e_report.pages, "42")
expect_raises("the class itself does not coerce",                    e_report.add, 42)
expect_ok("own strict @typecheck: exact type",                       e_report.owner, e_report, Animal())
expect_raises("own strict @typecheck: subclass rejected",            e_report.owner, e_report, Dog())
expect_ok("the class itself accepts the subclass",                   e_report.keeper, Dog())
expect_message("own @typecheck: Self is the class, message names the method",
               ("For parameter other of <Method EReport.owner>", "EReport"), e_report.owner, 5, Animal())
expect_value("own @typecheck: wrapped once",                         (True, False),
             lambda: (_e_wrapped(EReport, "pages"), "_pv_bootstrap" in vars(EReport)["pages"].__wrapped__.__globals__))
expect_exact("own @typecheck below another decorator: its options",  3, e_report.copies, "3")
expect_value("own @typecheck below another decorator: left as it is", False, _e_wrapped, EReport, "copies")
expect_value("enforced a second time changes nothing",               True,
             lambda: (lambda before: enforce(EReport) is EReport and vars(EReport)["add"] is before)(vars(EReport)["add"]))
expect_raises("subclass: the inherited __init__ is checked",         EChild, 1)
expect_value("subclass: its own methods are not checked",            (1, "n"), lambda: (EChild("a").add(1), EChild("a").extra("n")))
expect_raises("enforced subclass: its own methods are checked",      EChecked("a").extra, "n")
expect_raises("enforced subclass: inherited methods stay checked",   EChecked("a").add, 1)
expect_value("enforced subclass: nothing inherited is wrapped again", False, lambda: "add" in vars(EChecked))
expect_message("typecheck refuses a class",
               ("typecheck cannot check <Class EChild>: it checks functions and methods. A class is checked by @enforce",),
               typecheck, EChild)
expect_message("typecheck with options refuses a class",             ("A class is checked by @enforce",),
               typecheck(deep=True), EChild)
expect_message("typecheck refuses a dataclass",                      ("A dataclass is checked by enforced.dataclass",),
               typecheck, EStdData)
expect_message("enforced refuses a dataclass",
               ("enforce cannot check <Dataclass EStdData>: it checks plain classes. "
                "A dataclass is checked by enforced.dataclass, its methods included",), enforce, EStdData)
expect_message("enforced refuses an enforced dataclass",            ("<Dataclass EData>: it checks plain classes",), enforce, EData)
expect_message("enforced refuses a function",
               ("enforce cannot check <Function takes_animal>: it checks classes. "
                "A function or a method is checked by @typecheck",), enforce, takes_animal.__wrapped__)
expect_message("enforced with options refuses what is no class",     ("enforce cannot check 5: it checks classes",),
               enforce(coerce=True), 5)
expect_raises("a dataclass method takes @typecheck",                 EData(1).moved, "2")
expect_value("a dataclass method takes @typecheck: valid",           3, EData(1).moved, 2)
expect_value("a plain subclass of a dataclass can be enforced",      True, lambda: enforce(EPlainSub) is EPlainSub)
expect_raises("... and its methods are checked",                     EPlainSub(1).label, 1)
expect_raises("... next to the dataclass's own check",               EPlainSub, "1")


@enforce(check_return=True)
class ELedger:
    def __new__(cls, owner: str, *rest: Any) -> "ELedger":
        return super().__new__(cls)

    def __init__(self, owner: str, limit: float = 100) -> None:
        self.owner, self.limit, self.entries = owner, limit, {}

    def __call__(self, amount: float) -> float:
        return amount

    def __getitem__(self, key: str) -> float:
        return self.entries[key]

    def __setitem__(self, key: str, amount: float) -> None:
        self.entries[key] = amount

    def __delitem__(self, key: str) -> None:
        del self.entries[key]

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __enter__(self) -> Self:
        return self.owner                                # type: ignore[return-value]

    def __exit__(self, kind: type, error: Exception, trace: int) -> None:   # None three times on a normal exit
        return None

    def __eq__(self, other: "ELedger") -> bool:          # type: ignore[override]
        return NotImplemented

    def __add__(self, other: "ELedger") -> "ELedger":
        return NotImplemented

    def __len__(self) -> str:                            # type: ignore[override]
        return len(self.entries)                         # type: ignore[return-value]

    def __setattr__(self, name: int, value: int) -> None:                   # type: ignore[override]
        object.__setattr__(self, name, value)            # type: ignore[arg-type]

    @enforce.exempt
    def __iter__(self) -> int:                           # type: ignore[override]
        return iter(self.entries)                        # type: ignore[return-value]

@enforce
class EPoint(NamedTuple):
    x: int
    y: float = 0.0

@enforce
class EPlanet(enum.Enum):
    EARTH = (1, 9.8)

    def __new__(cls, number: int, gravity: float) -> "EPlanet":
        member = object.__new__(cls)
        member._value_, member.gravity = number, gravity
        return member


def _e_item(ledger: Any, key: Any, amount: Any) -> Any:
    ledger[key] = amount
    return ledger.entries.get(key)

def _e_del(ledger: Any, key: Any) -> None:
    del ledger[key]

def _e_with(ledger: Any) -> Any:
    with ledger as bound:
        return bound


section("phase 3 · enforced: the special methods a caller hands values to")
e_ledger = ELedger("ana")
expect_message("__new__: bad argument, reported as the class",       ("For parameter owner of <Class ELedger>",), ELedger, 5)
expect_raises("__init__ next to __new__: its own parameter",         ELedger, "ana", "high")
expect_exact("__init__ default converted",                           100.0, lambda: e_ledger.limit)
expect_exact("__call__: valid, converted",                           2.0, e_ledger, 2)
expect_message("__call__: bad argument",                             ("<Method ELedger.__call__>",), e_ledger, "2")
expect_exact("__setitem__: valid, converted",                        5.0, _e_item, e_ledger, "rent", 5)
expect_message("__setitem__: bad key",                               ("For parameter key of <Method ELedger.__setitem__>",), _e_item, e_ledger, 1, 5.0)
expect_raises("__setitem__: bad value",                              _e_item, e_ledger, "rent", "5")
expect_exact("__getitem__: valid",                                   5.0, lambda: e_ledger["rent"])
expect_raises("__getitem__: bad key",                                lambda: e_ledger[0])
expect_raises("__getitem__: a slice for a str key",                  lambda: e_ledger[0:1])
expect_value("__contains__: valid",                                  (True, False), lambda: ("rent" in e_ledger, "food" in e_ledger))
expect_raises("__contains__: bad key",                               lambda: 5 in e_ledger)
expect_raises("__delitem__: bad key",                                _e_del, e_ledger, 5)
expect_ok("__delitem__: valid",                                      _e_del, e_ledger, "rent")
expect_message("__enter__: what it returns, with check_return",      ("For return value of <Method ELedger.__enter__>",), _e_with, e_ledger)
expect_value("== against any object still answers",                  (False, True), lambda: (e_ledger == "x", e_ledger != 5))
expect_raises("+ with NotImplemented is Python's own TypeError",     lambda: e_ledger + 1, exc=TypeError)
expect_value("__len__, __setattr__, __exit__ are left as written",   [False, False, False],
             lambda: [_e_wrapped(ELedger, name) for name in ("__len__", "__setattr__", "__exit__")])
expect_value("len() with a wrong return annotation is not checked",  0, len, e_ledger)
expect_ok("assignment goes through the unchecked __setattr__",       setattr, e_ledger, "note", "free text")
expect_value("enforce.exempt on a special method",                   [], list, e_ledger)
expect_exact("NamedTuple class: construction converted",             (1, 2.0), lambda: tuple(EPoint(1, 2)))
expect_message("NamedTuple class: construction checked",             ("For parameter x of <Class EPoint>",), EPoint, "1")
expect_value("NamedTuple class: _make and _replace as before",       (EPoint(1, 2.0), EPoint(3, 0.0)), lambda: (EPoint._make([1, 2.0]), EPoint(1)._replace(x=3)))
expect_value("Enum class: Enum.__new__ is not wrapped",              True, lambda: vars(EPlanet)["__new__"] is enum.Enum.__new__)
expect_value("Enum class: lookups work",                             (EPlanet.EARTH, 9.8), lambda: (EPlanet(1), EPlanet["EARTH"].gravity))


@typecheck
def v_args(*args: int) -> None: pass

@typecheck
def v_kwargs(**kwargs: str) -> None: pass

@typecheck
def v_mixed(a: int, *rest: str, flag: bool = False, **extra: float) -> None: pass


section("phase 3 · *args / **kwargs")
expect_ok("*args all int",                           v_args, 1, 2, 3)
expect_ok("*args empty",                             v_args)
expect_message("*args failure labels the index",     ("args[2]",), v_args, 1, 2, "x")
expect_message("**kwargs failure labels the key",    ("kwargs[b]",), v_kwargs, a="x", b=1)
expect_ok("mixed signature",                         v_mixed, 1, "a", "b", flag=True, z=1.5)
expect_raises("mixed signature, bad *rest",          v_mixed, 1, 2)
expect_raises("mixed signature, bad **extra",        v_mixed, 1, z="x")


@typecheck(allow_subclass=False)
def s_int(x: int) -> None: pass

@typecheck(allow_subclass=False)
def s_union(x: int | str) -> None: pass

@typecheck(allow_subclass=False)
def s_type(cls: type[Animal]) -> None: pass

@typecheck(allow_subclass=False)
def s_float(x: float) -> float: return x

@typecheck(allow_subclass=False)
def s_sequence(xs: Sequence[int]) -> Any: return xs

@typecheck(allow_subclass=False)
def s_callable(fn: Callable[[int], str]) -> None: pass

@typecheck(allow_subclass=False)
def s_drawable(d: Drawable) -> None: pass

@typecheck(allow_subclass=False)
def s_sequence_or_int(x: Sequence | int) -> Any: return x

@typecheck(allow_subclass=False)
def s_type_or_none(cls: type[Animal] | None = None) -> Any: return cls


section("phase 3 · strict mode (allow_subclass=False)")
expect_ok("int accepts int",                         s_int, 1)
expect_raises("int rejects bool",                    s_int, True)
expect_ok("union accepts str",                       s_union, "a")
expect_raises("union rejects bool",                  s_union, True)
expect_ok("type[Animal] accepts Animal",             s_type, Animal)
expect_raises("type[Animal] rejects Dog",            s_type, Dog)
expect_value("strict float still converts int",      1.0, s_float, 1)
expect_value("abstract Sequence[int] accepts a list", [1], s_sequence, [1])
expect_value("abstract Sequence[int] accepts a tuple", (1,), s_sequence, (1,))
expect_raises("abstract Sequence[int] rejects a set", s_sequence, {1})
expect_ok("abstract Callable accepts a function",    s_callable, str)
expect_raises("abstract Callable rejects 42",        s_callable, 42)
expect_ok("Protocol accepts an implementation",      s_drawable, Circle())
expect_raises("Protocol rejects a non-implementation", s_drawable, NoDrawMethod())
expect_value("Sequence | int accepts a list",        [1], s_sequence_or_int, [1])
expect_value("Sequence | int accepts an int",        1, s_sequence_or_int, 1)
expect_raises("Sequence | int: int stays exact (no bool)", s_sequence_or_int, True)
expect_value("type[Animal] | None: the None default", None, s_type_or_none)
expect_raises("type[Animal] | None: still rejects Dog", s_type_or_none, Dog)


@typecheck
def l_one_true(x: Literal[1, True]) -> None: pass

@typecheck
def l_small(x: Literal[1, 2]) -> None: pass


section("phase 3 · Literal edge cases")
expect_ok("Literal[1, True] accepts 1",              l_one_true, 1)
expect_ok("Literal[1, True] accepts True",           l_one_true, True)
expect_raises("Literal[1, True] rejects False",      l_one_true, False)
expect_raises("unhashable input: InvalidDataError",  l_small, [1])
expect_raises("1.0 is not Literal[1]",               l_small, 1.0)


def fd_real(a: int, b: str = "x") -> None: pass
def fd_bad_default(a: int, b: str = 5) -> None: pass     # type: ignore[assignment]

USER = {"object_name": "create_user", "record": {"name": str, "age": int}}


section("phase 3 · typecheck_record")
expect_value("string name, valid args (returned as given)", (("ana", 30), {}),
             typecheck_record, {**USER, "args": ("ana", 30)})
expect_raises("string name, wrong kwarg type",       typecheck_record, {**USER, "kwargs": {"name": "ana", "age": "30"}})
expect_message("missing arg names the target",       ("create_user", "age (expecting type int)"),
               typecheck_record, {**USER, "args": ("ana",)})
expect_ok("callable, real signature with default",   typecheck_record, {"object_name": fd_real, "record": {"a": int, "b": str}, "args": (1,)})
expect_raises("callable, bad default",               typecheck_record, {"object_name": fd_bad_default, "record": {"a": int, "b": str}, "args": (1,)})
expect_ok("strict via spec: int accepted",           typecheck_record, {"object_name": "f", "record": {"x": int}, "args": (1,), "allow_subclass": False})
expect_raises("strict via spec: bool rejected",      typecheck_record, {"object_name": "f", "record": {"x": int}, "args": (True,), "allow_subclass": False})
expect_raises("spec missing 'record'",               typecheck_record, {"object_name": "f"})
expect_raises("spec unknown key",                    typecheck_record, {"object_name": "f", "record": {}, "extra": 1})
expect_raises("spec object_name wrong type",         typecheck_record, {"object_name": 42, "record": {}})
expect_raises("spec record not a mapping",           typecheck_record, {"object_name": "f", "record": [("a", int)]})
expect_raises("spec record key not an identifier",   typecheck_record, {"object_name": "f", "record": {"not valid": int}})


@dataclass
class DPoint:
    x: float
    y: float

@dataclass
class DConfig:
    port: int = "8080"                                   # type: ignore[assignment]

@dataclass
class DBag:
    items: list[str] = field(default_factory=list)

@dataclass
class DBadFactory:
    items: list[str] = field(default_factory=lambda: "not a list")   # type: ignore[arg-type]

@dataclass(check_assignment=False)
class DLoose:
    x: float

@dataclass(frozen=True, slots=True)
class DFrozen:
    x: float

@dataclass
class DScaled:
    x: int
    factor: InitVar[int] = 1
    registry: ClassVar[int] = 0

    def __post_init__(self, factor: int) -> None:
        self.x *= factor

@dataclass
class DOrder:
    price: float
    qty: int
    total: float = field(init=False)

    def __post_init__(self) -> None:
        self.total = self.price * self.qty

@dataclass
class DHidden:
    x: int
    retries: int = field(init=False, default="three")    # type: ignore[assignment]

@dataclass(frozen=True, slots=True)
class DHiddenFrozen:
    x: int
    retries: int = field(init=False, default="three")    # type: ignore[assignment]

@dataclass(init=False)
class DNoInit:
    port: int = "8080"                                   # type: ignore[assignment]

@dataclass(init=False)
class DOwnInit:
    x: float = 0
    y: float = 0

    def __init__(self, *coords: float) -> None:
        if coords:
            self.x, self.y = coords

@dataclass
class DBase:
    x: int

@dataclass
class DChild(DBase):
    y: str

@dataclass
class DNode:
    value: int
    next: "DNode | None" = None


section("phase 3 · dataclass override")
_pt, _loose, _frozen, _child = DPoint(1.0, 2.0), DLoose(1.0), DFrozen(1.0), DChild(1, "a")
expect_ok("valid construction",                      DPoint, 1.0, 2.0)
expect_raises("wrong field type",                    DPoint, 1.0, "two")
expect_message("missing field named",                ("x (expecting type float)",), DPoint, y=2.0)
expect_raises("bad field default",                   DConfig)
expect_ok("default_factory not flagged",             DBag)
expect_raises("default_factory producing wrong type", DBadFactory)
expect_ok("valid assignment",                        setattr, _pt, "x", 5.0)
expect_message("invalid assignment names the field", ("1 problem found in field assignment", "Field DPoint.x of <Dataclass DPoint>"),
               setattr, _pt, "x", "oops")
expect_value("failed assignment keeps the old value", 5.0, lambda: _pt.x)
expect_ok("non-field attribute unchecked",           setattr, _pt, "anything", "fine")
expect_ok("check_assignment=False allows a bad write", setattr, _loose, "x", "allowed")
expect_raises("frozen+slots construction checked",   DFrozen, "one")
expect_raises("frozen assignment still FrozenInstanceError", setattr, _frozen, "x", 2.0, exc=dataclasses.FrozenInstanceError)
expect_value("InitVar used in __post_init__",        6, lambda: DScaled(2, 3).x)
expect_raises("InitVar wrong type",                  DScaled, 2, "3")
expect_ok("ClassVar is not a field",                 setattr, DScaled, "registry", "anything")
expect_value("init=False field set in __post_init__", 6.0, lambda: DOrder(2.0, 3).total)
expect_message("init=False field: a bad default is a definition error",
               ("1 problem found in definition", "For default value of field retries of <Dataclass DHidden>"), DHidden, 1)
expect_raises("init=False field: bad default, frozen + slots", DHiddenFrozen, 1)
expect_message("dataclass(init=False): a bad default is a definition error",
               ("1 problem found in definition", "For default value of field port of <Dataclass DNoInit>"), DNoInit)
expect_value("dataclass(init=False): default converted for the user's own __init__", 0.0, lambda: DOwnInit().x)
expect_value("dataclass(init=False): the own __init__ is back after the first construction", "DOwnInit.__init__",
             lambda: vars(DOwnInit)["__init__"].__qualname__)
expect_value("dataclass(init=False): assignments in the own __init__ converted", 2.0, lambda: DOwnInit(1, 2).y)
expect_raises("dataclass(init=False): assignments in the own __init__ checked", DOwnInit, "1", 2)
expect_raises("inherited field checked",             DChild, "1", "a")
expect_raises("own field checked",                   DChild, 1, 2)
expect_raises("inherited field assignment checked",  setattr, _child, "x", "1")
expect_ok("self-referential forward ref",            DNode, 1, DNode(2))
expect_raises("self-referential forward ref, wrong type", DNode, 1, "nope")
expect_raises("dataclasses.replace goes through checks", dataclasses.replace, _pt, x="bad")


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 4: conversion (convert=True, default) and coercion (coerce=True, opt-in)
# ═════════════════════════════════════════════════════════════════════════════

@typecheck(check_return=True)
def c_float(x: float) -> float:
    return x

@typecheck
def c_complex(x: complex) -> complex:
    return x

@typecheck
def c_mixed(a: float, b: str, *rest: float, k: float = 1.0, **extra: float) -> tuple:
    return a, b, rest, k, extra

@typecheck
def c_default(x: float = 0, *, k: complex = 1) -> tuple:
    return x, k

@typecheck(check_return=True)
def c_return() -> float:
    return 7                                             # type: ignore[return-value]

@typecheck(convert=False)
def c_off(x: float) -> float:
    return x

@typecheck
def c_partly(a: float, b: int) -> None:
    pass


section("phase 4 · conversion (on by default)")
expect_value("int -> float",                         1.0, c_float, 1)
expect_value("int -> complex",                       2 + 0j, c_complex, 2)
expect_value("float -> complex",                     1.5 + 0j, c_complex, 1.5)
expect_value("valid float passes through",           2.5, c_float, 2.5)
expect_raises("bool is never converted",             c_float, True)
expect_raises("inexact int (2**53 + 1) rejected",    c_float, 2**53 + 1)
expect_raises("huge int rejected, no OverflowError", c_float, 10**400)
expect_value("positional, *args, keyword and **kwargs all converted",
             (1.0, "s", (2.0, 3.0), 4.0, {"z": 5.0}), c_mixed, 1, "s", 2, 3, k=4, z=5)
expect_value("int defaults converted (x: float = 0)", (0.0, 1 + 0j), c_default)
expect_value("return value converted with check_return", 7.0, c_return)
expect_raises("convert=False rejects int for float", c_off, 1)
expect_message("only the unconvertible argument is reported",
               ("1 problem found in call", "parameter b"), c_partly, 1, "x", absent=("parameter a",))
received("61-param function: int for float converted", "p_float", 1, 1.0)
received("61-param function: valid list passed through", "p_list", [9], [9])


class Mode(enum.Enum):
    FAST = "fast"
    SLOW = "slow"

@typecheck(coerce=True)
def k_int(x: int) -> int: return x

@typecheck(coerce=True)
def k_bool(x: bool) -> bool: return x

@typecheck(coerce=True)
def k_mode(x: Mode) -> Mode: return x

@typecheck(coerce=True)
def k_list(x: list[int]) -> list[int]: return x

@typecheck(coerce=True)
def k_date(x: datetime.date) -> datetime.date: return x

@typecheck(coerce=True)
def k_datetime(x: datetime.datetime) -> datetime.datetime: return x

@typecheck(coerce=True)
def k_bytes(x: bytes) -> bytes: return x

@typecheck(coerce=True)
def k_union(x: int | float) -> int | float: return x

@typecheck(coerce=True)
def k_order(x: bool | float) -> bool | float: return x

@typecheck(coerce=True)
def k_literal(x: Literal[1, 2]) -> None: pass

@typecheck(coerce=True, check_return=True)
def k_return(x: int) -> int:
    return str(x)                                        # type: ignore[return-value]

@typecheck(coerce=True, convert=False, check_return=True)
def k_return_float() -> float:
    return 2                                             # type: ignore[return-value]

@typecheck(coerce=True)
def k_named(quantity: int) -> None: pass

@typecheck
def k_off(x: int) -> int: return x


section("phase 4 · coercion (coerce=True)")
expect_raises("off by default: '42' rejected for int", k_off, "42")
expect_value("'42' -> 42",                           42, k_int, "42")
expect_value("' -7 ' -> -7",                         -7, k_int, " -7 ")
expect_value("3.0 -> 3",                             3, k_int, 3.0)
expect_raises("3.5 rejected (not a whole number)",   k_int, 3.5)
expect_raises("'abc' rejected",                      k_int, "abc")
expect_value("'yes' -> True",                        True, k_bool, "yes")
expect_value("'Off' -> False",                       False, k_bool, "Off")
expect_value("1 -> True",                            True, k_bool, 1)
expect_raises("2 rejected for bool",                 k_bool, 2)
expect_value("'fast' -> Mode.FAST",                  Mode.FAST, k_mode, "fast")
expect_raises("'turbo' rejected for Mode",           k_mode, "turbo")
expect_value("tuple -> list",                        [1, 2], k_list, (1, 2))
expect_value("ISO string -> date",                   datetime.date(2024, 2, 29), k_date, "2024-02-29")
expect_raises("invalid date rejected",               k_date, "2024-13-01")
expect_value("a date -> datetime (midnight), as YAML hands one", datetime.datetime(2026, 10, 17), k_datetime, datetime.date(2026, 10, 17))
expect_raises("... a time is no datetime",           k_datetime, datetime.time(10, 30))
expect_value("str -> bytes (UTF-8)",                 b"hi", k_bytes, "hi")
expect_value("union: int fails, float parses",       1.5, k_union, "1.5")
expect_value("union: lossless conversion beats coercion", 1.0, k_order, 1)
expect_raises("Literal never coerced",               k_literal, "1")
expect_message("return value never coerced (its argument is)",
               ("For return value of <Function k_return>: expected type: 'int', got type 'str' (Value: '11')",), k_return, "11")
expect_value("return value still converted (int -> float)", 2.0, k_return_float)
expect_message("failed coercion shows the original value",
               ("quantity", "'abc'", "str"), k_named, "abc")


@dataclass
class CPoint:
    x: float
    y: float = 0

@dataclass(coerce=True)
class CRow:
    id: int
    active: bool
    mode: Mode

@dataclass(convert=False)
class CStrict:
    x: float

@dataclass
class CTotal:
    qty: int
    total: float = field(init=False, default=0)

@dataclass(frozen=True, slots=True)
class CTotalFrozen:
    qty: int
    total: float = field(init=False, default=0)


section("phase 4 · dataclass conversion")
_cp = CPoint(1)
expect_value("init: int -> float",                   1.0, lambda: _cp.x)
expect_value("default: 0 -> 0.0",                    0.0, lambda: _cp.y)
expect_value("assignment: int -> float",             5.0, lambda: (setattr(_cp, "x", 5), _cp.x)[1])
expect_value("keyword construction converted",       3.0, lambda: CPoint(x=2, y=3).y)
expect_value("dataclasses.replace converted",        9.0, lambda: dataclasses.replace(_cp, x=9).x)
expect_value("coerce=True dataclass",                (7, True, Mode.SLOW), lambda: (lambda r: (r.id, r.active, r.mode))(CRow("7", "yes", "slow")))
expect_value("coerce=True assignment",               8, lambda: (lambda r: (setattr(r, "id", "8"), r.id)[1])(CRow(1, True, Mode.FAST)))
expect_raises("convert=False dataclass rejects int", CStrict, 1)
expect_value("init=False default: 0 -> 0.0",         0.0, lambda: CTotal(1).total)
expect_value("init=False default: 0 -> 0.0 (frozen + slots)", 0.0, lambda: CTotalFrozen(1).total)


section("phase 4 · typecheck_record conversion")
_supplied = {"a": 1}
expect_value("returns converted (args, kwargs)",     ((1.0,), {"b": 2}),
             typecheck_record, {"object_name": "f", "record": {"a": float, "b": int}, "args": (1,), "kwargs": {"b": 2}})
expect_value("coerce key",                           ((), {"a": 9}),
             typecheck_record, {"object_name": "f", "record": {"a": int}, "kwargs": {"a": "9"}, "coerce": True})
expect_raises("convert key = False",                 typecheck_record,
              {"object_name": "f", "record": {"a": float}, "kwargs": {"a": 1}, "convert": False})
typecheck_record({"object_name": "f", "record": {"a": float}, "kwargs": _supplied})
expect_value("caller's kwargs dict is not modified", 1, lambda: _supplied["a"])


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 5: deep checks (deep=True, opt-in): the items inside collections, at every depth
# ═════════════════════════════════════════════════════════════════════════════

#* The same 61-param function as phase 1, decorated again with deep=True.
process_deep = typecheck(process.__wrapped__, deep=True)


def good_deep(desc: str, **overrides: Any) -> None:
    expect_ok(desc, process_deep, **{**VALID, "p_iterator": iter(["a"]), **overrides})


def bad_deep(param: str, value: Any, desc: str, path: str | list[str] | None = None) -> None:
    """``process_deep`` must reject ``value`` and blame exactly ``path`` (``param`` itself by default)."""
    paths = [path or param] if not isinstance(path, list) else path
    expect_paths(f"{param}: {desc}", paths, process_deep, **{**VALID, "p_iterator": iter(["a"]), param: value})


def received_deep(desc: str, param: str, value: Any, expected: Any) -> None:
    """``process_deep`` must accept ``value`` for ``param`` and see exactly ``expected`` (types included) inside."""
    expect_exact(desc, expected, lambda: process_deep(**{**VALID, "p_iterator": iter(["a"]), param: value})[param])


section("phase 5 · 61 params with deep=True: valid calls still pass")
good_deep("full valid call")
expect_ok("all 61 params passed positionally", process_deep, *{**VALID, "p_iterator": iter(["a"])}.values())
_it = iter(["first", "second"])
process_deep(**{**VALID, "p_iterator": _it})
expect_value("Iterator[str] is not consumed by the check", "first", next, _it)
_valid_list = [1, 2]
expect_value("valid list is passed through as is, not copied", True,
             lambda: process_deep(**{**VALID, "p_iterator": iter(["a"]), "p_list_int": _valid_list})["p_list_int"] is _valid_list)
good_deep("Iterable[int] items are not checked (checking would consume them)", p_iterable=["a", "b"])
good_deep("bare list has no items to check",     p_list=["anything", 1, None])
good_deep("MutableMapping[str, Any]: values are Any", p_mut_map={"x": object()})

section("phase 5 · items now checked (outer-only in phase 1)")
expect_ok("deep=False (phase 1) still lets list[str] through", process, **{**VALID, "p_list_int": ["a", "b"]})
bad_deep("p_list_int",       ["a", "b"],          "every bad item reported", ["p_list_int[0]", "p_list_int[1]"])
bad_deep("p_list_int",       [1, "b"],            "second item wrong",        "p_list_int[1]")
bad_deep("p_dict_str_int",   {1: 1},              "int key in dict[str, int]", "p_dict_str_int[key 1]")
bad_deep("p_dict_str_int",   {"a": "flip"},       "str value in dict[str, int]", "p_dict_str_int['a']")
bad_deep("p_tuple_fixed",    (1, 2),              "tuple[int, str] second position", "p_tuple_fixed[1]")
bad_deep("p_tuple_fixed",    (1, "hi", 3),        "tuple[int, str] too long")
bad_deep("p_tuple_fixed",    (1,),                "tuple[int, str] too short")
bad_deep("p_tuple_variadic", (1.0, "x"),          "tuple[float, ...] item", "p_tuple_variadic[1]")
bad_deep("p_set_str",        {1},                 "set[str] item", "p_set_str[0]")
bad_deep("p_frozenset_int",  frozenset({"a"}),    "frozenset[int] item", "p_frozenset_int[0]")
bad_deep("p_ann_list",       [1.0, "x"],          "Annotated[list[float], ...] item", "p_ann_list[1]")
bad_deep("p_sequence",       [1, "a"],            "Sequence[int] item", "p_sequence[1]")
bad_deep("p_mut_seq",        ["a", 1],            "MutableSequence[str] item", "p_mut_seq[1]")
bad_deep("p_mapping",        {"a": "1"},          "Mapping[str, int] value", "p_mapping['a']")
bad_deep("p_point",          Point("a", 2.0),     "NamedTuple field", "p_point.x")
bad_deep("p_config",         {"host": "h"},       "TypedDict missing 'port'", "p_config['port']")
bad_deep("p_config",         {"host": 1, "port": 80}, "TypedDict wrong value", "p_config['host']")
bad_deep("p_vector2d",       (1.0, "2"),          "Vector2D alias position", "p_vector2d[1]")
bad_deep("p_vector2d",       (1.0, 2.0, 3.0),     "Vector2D alias length")
bad_deep("p_matrix",         [[1.0, "b"]],        "Matrix alias inner item", "p_matrix[0][1]")
bad_deep("p_coords",         [[1, 2]],            "Coords: list where tuple expected", "p_coords[0]")
bad_deep("p_fwd_alias",      (1.0, "x"),          "'Vector2D' forward ref followed", "p_fwd_alias[1]")
bad_deep("p_nested_list",    [[1, 2]],            "list[dict[str, int]] inner list", "p_nested_list[0]")
bad_deep("p_nested_list",    [{"a": "x"}],        "list[dict[str, int]] inner value", "p_nested_list[0]['a']")
bad_deep("p_nested_dict",    {"a": "x"},          "dict[str, list[float]] inner str", "p_nested_dict['a']")
bad_deep("p_nested_dict",    {"a": [1.0, None]},  "dict[str, list[float]] inner item", "p_nested_dict['a'][1]")
expect_paths("every bad item in every parameter, in parameter order",
             ["p_list_int[0]", "p_dict_str_int['b']", "p_nested_dict['a'][0]"],
             process_deep, **{**VALID, "p_iterator": iter(["a"]), "p_list_int": ["x", 1],
                              "p_dict_str_int": {"a": 1, "b": None}, "p_nested_dict": {"a": ["no"]}})

section("phase 5 · items converted (convert=True by default)")
received_deep("tuple[float, ...]: ints -> floats",           "p_tuple_variadic", (1, 2), (1.0, 2.0))
received_deep("Annotated[list[float], ...]: ints -> floats", "p_ann_list", [1, 2.5], [1.0, 2.5])
received_deep("Matrix alias: inner ints -> floats",          "p_matrix", [[1, 2]], [[1.0, 2.0]])
received_deep("Coords alias: list of tuples converted",      "p_coords", [(1, 2)], [(1.0, 2.0)])
received_deep("NamedTuple fields converted, type kept",      "p_point", Point(1, 2), Point(1.0, 2.0))
received_deep("dict[str, list[float]] values converted",     "p_nested_dict", {"a": [1]}, {"a": [1.0]})
received_deep("Vector2D alias converted",                    "p_vector2d", (3, 4), (3.0, 4.0))
_caller = [[1, 2]]
process_deep(**{**VALID, "p_iterator": iter(["a"]), "p_matrix": _caller})
expect_exact("the caller's list is never changed",           [[1, 2]], lambda: _caller)
expect_exact("deep=False (phase 1 function) doesn't convert items", [1, 2.5],
             lambda: process(**{**VALID, "p_ann_list": [1, 2.5]})["p_ann_list"])


@typecheck(deep=True)
def d_set(x: set[int]) -> set[int]: return x
@typecheck(deep=True)
def d_deque(x: deque[float]) -> deque[float]: return x
@typecheck(deep=True)
def d_ordered(x: OrderedDict[str, int]) -> OrderedDict[str, int]: return x
@typecheck(deep=True)
def d_default(x: defaultdict[str, list[float]]) -> defaultdict[str, list[float]]: return x
@typecheck(deep=True)
def d_counter(x: Counter[str]) -> Counter[str]: return x
@typecheck(deep=True)
def d_chain(x: ChainMap[str, int]) -> ChainMap[str, int]: return x
@typecheck(deep=True)
def d_abc_set(x: Set[int]) -> Set[int]: return x
@typecheck(deep=True)
def d_collection(x: Collection[str]) -> Collection[str]: return x
@typecheck(deep=True)
def d_empty_tuple(x: tuple[()]) -> tuple[()]: return x
@typecheck(deep=True)
def d_any_pair(x: tuple[Any, Any]) -> tuple[Any, Any]: return x


section("phase 5 · containers")
expect_ok("set[int]: valid",                        d_set, {1, 2})
expect_paths("set[int]: str item",                  ["x[0]"], d_set, {"a"})
expect_paths("deque[float]: None item",             ["x[1]"], d_deque, deque([1.0, None]))
expect_paths("OrderedDict[str, int]: bad value",    ["x['b']"], d_ordered, OrderedDict(a=1, b="2"))
expect_paths("defaultdict[str, list[float]]: inner", ["x['a'][0]"], d_default, defaultdict(list, a=["x"]))
expect_ok("Counter[str]: counts are ints",          d_counter, Counter("hello"))
expect_paths("Counter[str]: non-int count",         ["x['a']"], d_counter, Counter({"a": "many"}))
expect_paths("ChainMap[str, int]: bad value",       ["x['a']"], d_chain, ChainMap({"a": "1"}))
expect_paths("Set[int] (abc): frozenset item",      ["x[0]"], d_abc_set, frozenset({"a"}))
expect_paths("Collection[str]: list item",          ["x[1]"], d_collection, ["a", 2])
expect_ok("tuple[()]: empty tuple",                 d_empty_tuple, ())
expect_raises("tuple[()]: any item is too many",    d_empty_tuple, (1,))
expect_ok("tuple[Any, Any]: any items",             d_any_pair, (None, object()))
expect_raises("tuple[Any, Any]: length still checked", d_any_pair, (1, 2, 3))


class Address(TypedDict):
    city: str
    zip: NotRequired[str]

class Customer(TypedDict):
    name: str
    address: Address
    tags: NotRequired[list[str]]

class Segment(NamedTuple):
    start: Point
    end: Point

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type Tree = int | list[Tree]
type Pair[T] = tuple[T, T]
Scores = NewType("Scores", list[int])


@typecheck(deep=True)
def d_five(x: list[dict[str, list[set[int]]]]) -> None: pass
@typecheck(deep=True)
def d_customer(c: Customer) -> None: pass
@typecheck(deep=True)
def d_segment(s: Segment) -> Segment: return s
@typecheck(deep=True)
def d_json(v: Json) -> None: pass
@typecheck(deep=True)
def d_tree(t: Tree) -> None: pass
@typecheck(deep=True)
def d_pair(p: Pair[int]) -> None: pass
@typecheck(deep=True)
def d_scores(s: Scores) -> None: pass


section("phase 5 · every depth")
expect_ok("5 levels: valid",                        d_five, [{"a": [{1, 2}, set()]}])
expect_paths("5 levels: one bad int at the bottom", ["x[0]['a'][1][0]"], d_five, [{"a": [{1}, {"no"}]}])
expect_ok("TypedDict inside TypedDict: valid",      d_customer, {"name": "Ana", "address": {"city": "Athens"}})
expect_paths("nested TypedDict: missing key and bad values",
             ["c['address']['city']", "c['tags'][1]"],
             d_customer, {"name": "Ana", "address": {"zip": "105"}, "tags": ["vip", 7]})
expect_paths("NamedTuple of NamedTuples",           ["s.end.x"], d_segment, Segment(Point(0.0, 0.0), Point("1", 1.0)))
expect_exact("NamedTuple of NamedTuples converted", Segment(Point(0.0, 0.0), Point(1.0, 1.0)),
             d_segment, Segment(Point(0, 0), Point(1, 1)))
expect_ok("recursive Json alias: valid document",   d_json, {"a": [1, 2.5, None, True, {"b": "c"}]})
expect_paths("recursive Json alias: bad leaf deep inside", ["v['a'][1]['b']"], d_json, {"a": [1, {"b": object()}]})
expect_ok("recursive Tree alias: valid",            d_tree, [1, [2, [3, []]]])
expect_paths("recursive Tree alias: bad leaf",      ["t[1][1][0]"], d_tree, [1, [2, ["x"]]])
_loop: list[Any] = []
_loop.append(_loop)
expect_message("data that contains itself is reported, not a RecursionError",
               ("contains itself",), d_tree, _loop)
expect_ok("generic alias Pair[int]: valid",         d_pair, (1, 2))
expect_paths("generic alias Pair[int]: bad position", ["p[1]"], d_pair, (1, "2"))
expect_paths("NewType over list[int]",              ["s[0]"], d_scores, ["a"])


@typecheck(deep=True)
def d_optional(x: Optional[list[int]]) -> None: pass
@typecheck(deep=True)
def d_shapes(x: int | list[int] | dict[str, int]) -> None: pass
@typecheck(deep=True, convert=False)
def d_two_lists(x: list[int] | list[str]) -> None: pass
@typecheck(deep=True)
def d_item_union(x: list[int | str]) -> None: pass


section("phase 5 · unions")
expect_ok("Optional[list[int]]: None",              d_optional, None)
expect_paths("Optional[list[int]]: points at the bad item, not the union", ["x[1]"], d_optional, [1, "a"])
expect_paths("Optional[list[int]]: wrong outer type", ["x"], d_optional, "abc")
expect_ok("int | list[int] | dict[str, int]: each shape", lambda: (d_shapes(1), d_shapes([1]), d_shapes({"a": 1})))
expect_paths("the member with the right shape explains", ["x['a']"], d_shapes, {"a": "b"})
expect_ok("list[int] | list[str]: either list",     lambda: (d_two_lists([1]), d_two_lists(["a"])))
expect_paths("list[int] | list[str]: closest member's errors", ["x[2]"], d_two_lists, ["a", "b", 3])
expect_ok("list[int | str]: mixed items",           d_item_union, [1, "a"])
expect_paths("list[int | str]: None item",          ["x[1]"], d_item_union, [1, None])


@typecheck(deep=True)
def d_report(prices: dict[str, list[float]], window: tuple[int, int]) -> None: pass
@typecheck(deep=True, check_return=True)
def d_ret(x: Any) -> list[int]: return x
@typecheck(deep=True)
def d_varargs(*rows: list[int], **named: dict[str, int]) -> None: pass


section("phase 5 · messages and paths")
expect_message("message names each bad item, key and the tuple length",
               ("3 problems found in call",
                "For introspected parameter prices at index ['apple'][1] of <Function d_report>: expected type: 'float', got type 'str' (Value: 'n/a')",
                "For introspected parameter prices at index [key 3] of <Function d_report>: expected type: 'str', got type 'int' (Value: 3)",
                "For parameter window of <Function d_report>: expected type: tuple[int, int] with 2 items, got 3 items"),
               d_report, {"apple": [1.5, "n/a"], 3: [2.0]}, (1, 2, 3))
expect_message("missing TypedDict key names the key and its type",
               ("For introspected parameter c at index ['address'] of <Function d_customer>: missing required key 'city' (expecting type str)",),
               d_customer, {"name": "Ana", "address": {}})
expect_message("return value item",                 ("For introspected return value at index [1] of <Function d_ret>",), d_ret, [1, "x"])
expect_message("NamedTuple field named as a field",  ("For introspected parameter s at field end.x of <Function d_segment>",),
               d_segment, Segment(Point(0.0, 0.0), Point("1", 1.0)))
expect_message("the parameter itself keeps the usual wording", ("For parameter window of <Function d_report>",),
               d_report, {}, (1, 2, 3), absent=("introspected",))
expect_paths("*args / **kwargs items",              ["rows[1][0]", "named[b]['k']"],
             d_varargs, [1], ["x"], a={"k": 1}, b={"k": "no"})


def _problem(fn: Callable[..., Any], *args: Any) -> tuple:
    try:
        fn(*args)
    except InvalidDataError as e:
        p = e.problems[0]
        return (p.kind, p.parameter, p.detail)
    return ("no error",)


expect_value("problem kind 'length' with the expected length as detail", ("length", "window", 2),
             _problem, d_report, {}, (1, 2, 3))
expect_value("problem kind 'missing_key' with the key as detail", ("missing_key", "c['address']['city']", "city"),
             _problem, d_customer, {"name": "Ana", "address": {}})
expect_value("problem kind 'cycle'",                 ("cycle", "t", None), _problem, d_tree, _loop)
expect_value("return problems keep kind 'return'",   ("return", "return[1]", None), _problem, d_ret, [1, "x"])


@typecheck(deep=True, coerce=True)
def d_coerce(ids: list[int], flags: dict[str, bool], modes: list[Mode]) -> tuple: return ids, flags, modes
@typecheck(deep=True, coerce=True)
def d_coerce_outer(x: list[int]) -> list[int]: return x
@typecheck(deep=True)
def d_floats(x: list[float]) -> list[float]: return x
@typecheck(deep=True, convert=False)
def d_floats_strict(x: list[float]) -> list[float]: return x
@typecheck(deep=True)
def d_complex(x: dict[str, complex]) -> dict[str, complex]: return x


section("phase 5 · conversion and coercion of items")
expect_exact("list[float]: ints -> floats",         [1.0, 2.5], d_floats, [1, 2.5])
expect_exact("1,000 ints -> floats (bulk path)",    [float(i) for i in range(1000)], d_floats, list(range(1000)))
expect_paths("only the unconvertible item is reported", ["x[1]"], d_floats, [1, "x", 2])
expect_paths("inexact int item (2**53 + 1) rejected", ["x[1]"], d_floats, [1, 2**53 + 1])
expect_paths("bool item is never converted",        ["x[1]"], d_floats, [1, True])
expect_paths("convert=False: int item rejected",    ["x[0]"], d_floats_strict, [1])
expect_exact("dict values -> complex",              {"a": 1 + 0j, "b": 2.5 + 0j}, d_complex, {"a": 1, "b": 2.5})
expect_exact("coerce: '1', 2.0 -> ints; 'yes'/0 -> bools; 'fast' -> Mode",
             ([1, 2], {"a": True, "b": False}, [Mode.FAST]), d_coerce, ["1", 2.0], {"a": "yes", "b": 0}, ["fast"])
expect_exact("coerce: tuple -> list, then each item",  [1, 2], d_coerce_outer, ("1", "2"))
expect_paths("coerce: only the unparsable item is reported", ["x[1]"], d_coerce_outer, ["1", "one"])
_dq = d_deque(deque([1, 2], maxlen=5))
expect_value("deque keeps its maxlen when converted", (deque, 5, [1.0, 2.0]), lambda: (type(_dq), _dq.maxlen, list(_dq)))
_dd = d_default(defaultdict(list, a=[1]))
expect_value("defaultdict keeps its factory when converted", (defaultdict, list), lambda: (type(_dd), _dd.default_factory))
expect_exact("defaultdict inner items converted",   [1.0], lambda: _dd["a"])


@enforce(deep=True)
class Store:
    def __init__(self, stock: dict[str, int]) -> None:
        self.stock = stock

    def restock(self, names: list[str]) -> None: pass

    @staticmethod
    def parse(rows: list[tuple[str, int]]) -> None: pass

@typecheck(deep=True)
async def d_async(xs: list[int]) -> int:
    return len(xs)

@typecheck(deep=True)
def d_gen(xs: list[int]) -> Iterator[int]:
    yield from xs

@typecheck(deep=True)
def d_bad_default(xs: list[int] = [1, "x"]) -> None: pass          # type: ignore[list-item]

@typecheck(deep=True)
def d_float_default(xs: list[float] = [1, 2]) -> list[float]: return xs

@typecheck(deep=True, check_return=True)
def d_ret_conv() -> dict[str, float]:
    return {"a": 1}                                                    # type: ignore[dict-item]


section("phase 5 · where deep applies")
expect_ok("class: __init__ valid",                  Store, {"apple": 1})
expect_paths("class: __init__ item",                ["stock['apple']"], Store, {"apple": "1"})
expect_paths("class: method item",                  ["names[1]"], Store({}).restock, ["a", 1])
expect_paths("class: staticmethod nested item",     ["rows[0][1]"], Store.parse, [("a", "1")])
expect_value("async: valid",                        2, lambda: asyncio.run(d_async([1, 2])))
expect_raises("async: bad item raised on await",    lambda: asyncio.run(d_async([1, "a"])))
expect_value("generator: items checked when called", [1, 2], lambda: list(d_gen([1, 2])))
expect_paths("generator: bad item raised at call",  ["xs[1]"], d_gen, [1, "a"])
expect_message("default: bad item is a definition error",
               ("1 problem found in definition", "For default value of introspected parameter xs at index [1]"), d_bad_default)
expect_exact("default: items converted",            [1.0, 2.0], d_float_default)
expect_exact("return value: items converted",       {"a": 1.0}, d_ret_conv)


@dataclass(deep=True)
class Order:
    lines: list[tuple[str, int]]
    weights: list[float] = field(default_factory=list)
    notes: dict[str, str] | None = None

@dataclass(deep=True)
class BadFactory:
    tags: list[str] = field(default_factory=lambda: ["ok", 1])

@dataclass(deep=True, frozen=True)
class FrozenRow:
    values: tuple[int, ...]

@dataclass
class ShallowOrder:
    lines: list[tuple[str, int]]


section("phase 5 · dataclass deep=True")
_order = expect_ok("init: valid",                   Order, [("apple", 2)])
expect_paths("init: nested item",                   ["lines[0][1]"], Order, [("apple", "2")])
expect_paths("assignment: nested item",             ["lines[1][1]"], setattr, _order, "lines", [("a", 1), ("b", None)])
expect_message("assignment message names the field path",
               ("1 problem found in field assignment", "Introspected field Order.lines at index [1][1] of <Dataclass Order>: expected type: 'int'"),
               setattr, _order, "lines", [("a", 1), ("b", None)])
expect_message("assignment: tuple length",          ("Introspected field Order.lines at index [0] of <Dataclass Order>: expected type: tuple[str, int] with 2 items",),
               setattr, _order, "lines", [("a", 1, 2)])
expect_value("failed assignment keeps the old value", [("apple", 2)], lambda: _order.lines)
_order.weights = [1, 2]
expect_exact("assignment: items converted",         [1.0, 2.0], lambda: _order.weights)
expect_paths("assignment: Optional[dict] value",    ["notes['a']"], setattr, _order, "notes", {"a": 1})
expect_paths("default_factory output checked",      ["tags[1]"], BadFactory)
expect_ok("frozen: valid",                          FrozenRow, (1, 2))
expect_paths("frozen: init item",                   ["values[1]"], FrozenRow, (1, "2"))
expect_paths("dataclasses.replace checks items",    ["lines[0][0]"], dataclasses.replace, _order, lines=[(1, 1)])
expect_ok("deep=False dataclass doesn't check items", ShallowOrder, [("apple", "2")])


section("phase 5 · typecheck_record deep")
_spec = {"object_name": "create", "record": {"tags": list[str], "scores": dict[str, float]}}
expect_exact("deep key: valid, items converted",    ((), {"tags": ["a"], "scores": {"x": 1.0}}),
             typecheck_record, {**_spec, "kwargs": {"tags": ["a"], "scores": {"x": 1}}, "deep": True})
expect_paths("deep key: bad item",                  ["tags[1]"], typecheck_record,
             {**_spec, "kwargs": {"tags": ["a", 2], "scores": {}}, "deep": True})
expect_ok("no deep key: items not checked",         typecheck_record,
          {**_spec, "kwargs": {"tags": ["a", 2], "scores": {}}})


@typecheck(deep=True)
def d_iterable(x: Iterable[int]) -> Iterable[int]: return x
@typecheck(deep=True)
def d_iterator(x: Iterator[int]) -> Iterator[int]: return x
@typecheck(deep=True)
def d_generator(x: Generator[int, None, None]) -> Generator[int, None, None]: return x


section("phase 5 · iterables are never consumed")
for _name, _fn in (("Iterable[int]", d_iterable), ("Iterator[int]", d_iterator), ("Generator[int, ...]", d_generator)):
    _g = (s for s in ["not", "ints"])
    expect_value(f"{_name}: generator passed through untouched", ["not", "ints"], lambda: list(_fn(_g)))


@typecheck(deep=True)
def d_big(xs: list[int]) -> None: pass
@typecheck(deep=True)
def d_big_map(m: dict[str, int]) -> None: pass
@typecheck(deep=True, allow_subclass=False)
def d_strict(xs: list[int], pets: dict[str, Animal]) -> None: pass


section("phase 5 · large data and strict mode")
expect_paths("bool items are not ints",             ["xs[1]"], d_big, [1, True])
_big = list(range(100_000))
expect_ok("100,000 valid ints",                     d_big, _big)
expect_paths("one bad item among 100,000 is found", ["xs[100000]"], d_big, _big + ["x"])
expect_paths("bad items at both ends",              ["xs[0]", "xs[100001]"], d_big, [None] + _big + [None])
_bigmap = {str(i): i for i in range(10_000)}
expect_paths("10,000-entry dict: one bad key and one bad value", ["m['5']", "m[key 7]"],
             d_big_map, {**_bigmap, "5": "five", 7: 7})
expect_ok("strict: exact types pass",               d_strict, [1, 2], {"a": Animal()})
expect_paths("strict: bool item rejected for int",  ["xs[1]"], d_strict, [1, True], {})
expect_paths("strict: subclass value rejected",     ["pets['rex']"], d_strict, [], {"rex": Dog()})


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 6: validated values: TypeModel classes and Annotated[T, check]
# ═════════════════════════════════════════════════════════════════════════════

class Slug(TypeModel[str]):
    @classmethod
    def validate(cls, raw: str) -> str:
        raw = raw.strip().lower()
        if not raw or not re.fullmatch(r"[a-z0-9-]+", raw):
            raise ValueError("only letters, digits and '-'")
        return raw


class Percent(TypeModel[float]):
    @classmethod
    def validate(cls, raw: float) -> float:
        if not 0 <= raw <= 100:
            raise ValueError("must be between 0 and 100")
        return raw


class Locked(TypeModel[str]):
    auto_construct = False


def is_even(v: int) -> bool:
    return v % 2 == 0


def at_most_3(v: str) -> bool:
    if len(v) > 3:
        raise ValueError("at most 3 characters")
    return True


Even = Annotated[int, is_even]
Short = Annotated[str, at_most_3]
Band = Annotated[int, lambda v: v >= 10, lambda v: v <= 20]
TwoInts = Annotated[list[int], lambda xs: len(xs) == 2]


def _built(fn: Callable[..., Any], cls: type) -> Callable[..., Any]:
    """Wrap ``fn`` so expect_value can also check that the result is exactly ``cls``."""
    def call(*args: Any, **kwargs: Any) -> Any:
        out = fn(*args, **kwargs)
        if type(out) is not cls:
            raise AssertionError(f"expected a {cls.__name__}, got {type(out).__name__}")
        return out
    return call


@typecheck
def v_connect(admin: Email, port: Port) -> tuple: return admin, port
@typecheck
def v_slug(s: Slug) -> Slug: return s
@typecheck(convert=False)
def v_slug_noconv(s: Slug) -> Slug: return s
@typecheck(coerce=True)
def v_port_coerce(port: Port) -> Port: return port
@typecheck
def v_percent(p: Percent) -> Percent: return p
@typecheck
def v_locked(x: Locked) -> Locked: return x
@typecheck
def v_slug_or_int(v: Slug | int) -> Any: return v
@typecheck
def v_opt_slug(s: Slug | None = None) -> Any: return s
@typecheck
def v_default_slug(s: Slug = "Home") -> Slug: return s
@typecheck(check_return=True)
def v_ret_slug(raw: str) -> Slug: return raw
@typecheck
def v_var_slugs(*slugs: Slug) -> tuple: return slugs
@typecheck(allow_subclass=False)
def v_strict_slug(s: Slug) -> Slug: return s

@typecheck
def v_numbers(p: PositiveInt, n: NegativeInt, z: NonNegativeInt, x: Number) -> tuple: return p, n, z, x
@typecheck
def v_even(n: Even) -> int: return n
@typecheck
def v_short(s: Short) -> str: return s
@typecheck
def v_band(n: Band) -> int: return n
@typecheck
def v_even_or_str(v: Even | str) -> Any: return v
@typecheck
def v_opt_even(n: Even | None = None) -> Any: return n
@typecheck
def v_auto_or_even(v: Literal["auto"] | Even) -> Any: return v
@typecheck(coerce=True)
def v_even_coerce(n: Even) -> int: return n
@typecheck(check_return=True)
def v_ret_even(n: int) -> Even: return n
@typecheck
def v_pair(xs: TwoInts) -> list: return xs
@typecheck
def v_ann_doc(n: Annotated[int, "a description", 3]) -> int: return n


@typecheck(deep=True)
def vd_slugs(tags: list[Slug], by_name: dict[str, Slug]) -> tuple: return tags, by_name
@typecheck(deep=True)
def vd_evens(xs: list[Even], m: dict[str, Optional[Even]]) -> tuple: return xs, m
@typecheck(deep=True)
def vd_pair(xs: TwoInts) -> list: return xs
@typecheck(deep=True)
def vd_emails(es: tuple[Email, ...]) -> tuple: return es


@dataclass
class Server:
    admin: Email
    port: Port = 8080
    workers: PositiveInt = 4


def _set(obj: Any, name: str, value: Any) -> Any:
    setattr(obj, name, value)
    return getattr(obj, name)


section("phase 6 · data_types: Email and Port")
expect_value("Email: raw str built and normalised", Email("Ana@example.com"), _built(lambda: v_connect(" Ana@Example.COM ", 80)[0], Email))
expect_value("Port: raw int built", Port(80), _built(lambda: v_connect("a@b.io", 80)[1], Port))
_e = Email("ana@example.com")
expect_value("Email instance passes unchanged (same object)", True, lambda: v_connect(_e, 22)[0] is _e)
expect_message("invalid email: the reason is shown",
               ("For parameter admin of <Function v_connect>: invalid 'Email': must contain exactly one '@' (Value: 'nope')",),
               v_connect, "nope", 80)
expect_message("invalid port: the reason is shown",
               ("For parameter port of <Function v_connect>: invalid 'Port': must be between 1 and 65535 (Value: 0)",),
               v_connect, "a@b.io", 0)
expect_message("both invalid: both reported", ("2 problems found in call",), v_connect, "a b@c.io", 70000)
expect_message("wrong type is a type error, not 'invalid'", ("got type 'int'",), v_connect, 5, 80, absent=("invalid",))
expect_message("bool is not a Port", ("got type 'bool'",), v_connect, "a@b.io", True, absent=("invalid",))
expect_message("Port ← '8080' needs coerce", ("got type 'str'",), v_connect, "a@b.io", "8080")
expect_value("Port ← '8080' with coerce=True", Port(8080), _built(lambda: v_port_coerce("8080"), Port))
expect_message("Port ← '99999' with coerce=True: reason shown", ("invalid 'Port': must be between 1 and 65535 (Value: '99999')",),
               v_port_coerce, "99999")
for _bad in ("", "a@@b.io", "@b.io", ".a@b.io", "a..b@c.io", "a@b", "a@-b.io", "a@b_c.io", "a" * 65 + "@b.io"):
    expect_raises(f"Email({_bad[:20]!r}) raises ValueError", Email, _bad, exc=ValueError)
expect_value("Email.local / .domain", ("Ana", "example.com"), lambda: (lambda e: (e.local, e.domain))(Email("Ana@EXAMPLE.com")))

section("phase 6 · data_types: number checks")
expect_value("all valid", (1, -1, 0, 1.5), v_numbers, 1, -1, 0, 1.5)
expect_exact("Number: int converted to float", (1, -1, 0, 2.0), v_numbers, 1, -1, 0, 2)
expect_message("PositiveInt ← 0", ("For parameter p of <Function v_numbers>: invalid 'int': failed check x > 0 (Value: 0)",),
               v_numbers, 0, -1, 0, 1.0)
expect_message("NegativeInt ← 0", ("invalid 'int': failed check x < 0 (Value: 0)",), v_numbers, 1, 0, 0, 1.0)
expect_message("NonNegativeInt ← -1", ("invalid 'int': failed check x >= 0 (Value: -1)",), v_numbers, 1, -1, -1, 1.0)
expect_message("three failed checks reported together", ("3 problems found in call",), v_numbers, 0, 0, -1, 1.0)
expect_message("PositiveInt ← True: type error first", ("got type 'bool'",), v_numbers, True, -1, 0, 1.0, absent=("invalid",))
expect_message("PositiveInt ← 1.0: type error", ("got type 'float'",), v_numbers, 1.0, -1, 0, 1.0, absent=("invalid",))

section("phase 6 · TypeModel conversion")
expect_value("Slug built from a str", Slug("hello-world"), _built(lambda: v_slug("  Hello-World "), Slug))
expect_message("convert=False: a raw str is a type error", ("got type 'str'",), v_slug_noconv, "abc", absent=("invalid",))
expect_value("convert=False: an instance passes", Slug("abc"), _built(lambda: v_slug_noconv(Slug("abc")), Slug))
expect_message("auto_construct=False: only instances", ("got type 'str'",), v_locked, "abc")
expect_value("auto_construct=False: instance passes", Locked("abc"), _built(lambda: v_locked(Locked("abc")), Locked))
expect_value("float model ← int (numeric tower first)", Percent(50.0), _built(lambda: v_percent(50), Percent))
expect_message("float model ← 150: reason shown", ("invalid 'Percent': must be between 0 and 100 (Value: 150)",), v_percent, 150)
expect_value("Slug | int ← 3 stays int", 3, v_slug_or_int, 3)
expect_value("Slug | int ← 'ABC' builds a Slug", Slug("abc"), _built(lambda: v_slug_or_int("ABC"), Slug))
expect_message("Slug | int ← 'a b': reason shown", ("invalid 'Slug': only letters, digits and '-'",), v_slug_or_int, "a b")
expect_value("Slug | None: default None", None, v_opt_slug)
expect_value("Slug | None ← 'X'", Slug("x"), _built(lambda: v_opt_slug("X"), Slug))
expect_value("default 'Home' becomes Slug('home')", Slug("home"), _built(v_default_slug, Slug))
expect_value("return value built", Slug("abc"), _built(lambda: v_ret_slug("ABC"), Slug))
expect_message("return value invalid", ("For return value of <Function v_ret_slug>: invalid 'Slug'",), v_ret_slug, "a b")
expect_value("*slugs: each built", (Slug("a"), Slug("b")), v_var_slugs, "A", "B")
expect_paths("*slugs: bad item path", ["slugs[1]"], v_var_slugs, "ok", "no way")
expect_value("strict mode: built value is exactly a Slug", Slug("abc"), _built(lambda: v_strict_slug("abc"), Slug))

section("phase 6 · Annotated checks")
expect_value("Even ← 4", 4, v_even, 4)
expect_message("Even ← 3: check name shown", ("For parameter n of <Function v_even>: invalid 'int': failed check is_even (Value: 3)",),
               v_even, 3)
expect_message("Short ← 'abcd': ValueError text is the reason", ("invalid 'str': at most 3 characters (Value: 'abcd')",), v_short, "abcd")
expect_message("Band ← 5: first failing lambda shown", ("failed check v >= 10",), v_band, 5)
expect_message("Band ← 25: second lambda shown", ("failed check v <= 20",), v_band, 25)
expect_message("Even ← '4': type checked before the check", ("expected type: 'int', got type 'str'",), v_even, "4", absent=("invalid",))
expect_value("Even | str ← 'any str'", "any str", v_even_or_str, "any str")
expect_message("Even | str ← 3", ("failed check is_even",), v_even_or_str, 3)
expect_value("Even | None: default", None, v_opt_even)
expect_message("Even | None ← 1", ("failed check is_even",), v_opt_even, 1)
expect_value("Literal['auto'] | Even ← 'auto'", "auto", v_auto_or_even, "auto")
expect_message("Literal['auto'] | Even ← 3", ("failed check is_even",), v_auto_or_even, 3)
expect_value("coerce=True: '4' parsed, then checked", 4, v_even_coerce, "4")
expect_message("coerce=True: '3' parsed, then fails the check", ("failed check is_even",), v_even_coerce, "3")
expect_message("return value checked", ("For return value of <Function v_ret_even>: invalid 'int': failed check is_even",), v_ret_even, 1)
expect_value("Annotated[list[int], len == 2] ← [1, 2]", [1, 2], v_pair, [1, 2])
expect_message("Annotated[list[int], len == 2] ← [1]", ("invalid 'list': failed check len(xs) == 2",), v_pair, [1])
expect_value("non-callable metadata changes nothing", -7, v_ann_doc, -7)
expect_message("missing argument shows the check",
               ("n (expecting type Annotated[int, is_even])",), v_even)

section("phase 6 · deep checks")
expect_exact("list[Slug] / dict[str, Slug]: items built", ([Slug("a"), Slug("b")], {"x": Slug("c")}), vd_slugs, ["A", Slug("b")], {"x": "C"})
expect_paths("bad Slug items: paths", ["tags[1]", "by_name['x']"], vd_slugs, ["ok", "not ok"], {"x": "y y"})
expect_message("bad Slug item: reason", ("For introspected parameter tags at index [1] of <Function vd_slugs>: invalid 'Slug'",),
               vd_slugs, ["ok", "not ok"], {})
expect_value("list[Even] / dict[str, Even | None]", ([2, 4], {"a": None, "b": 6}), vd_evens, [2, 4], {"a": None, "b": 6})
expect_paths("failed checks inside collections", ["xs[1]", "xs[2]", "m['a']"], vd_evens, [2, 3, 5], {"a": 1})
expect_message("item check message", ("For introspected parameter xs at index [1] of <Function vd_evens>: invalid 'int': failed check is_even (Value: 3)",),
               vd_evens, [2, 3], {})
expect_paths("Annotated around a list: items first", ["xs[1]"], vd_pair, [1, "a"])
expect_message("Annotated around a list: then the check", ("invalid 'list': failed check len(xs) == 2",), vd_pair, [1, 2, 3])
expect_exact("tuple[Email, ...]: items built", (Email("a@b.io"), Email("c@d.io")), vd_emails, ("a@b.io", "c@D.io"))
_evens = list(range(0, 200_000, 2))
expect_ok("100,000 checked items", vd_evens, _evens, {})
expect_paths("one failed check among 100,000", ["xs[100000]"], vd_evens, _evens + [1], {})

section("phase 6 · dataclass")
_srv = expect_ok("Server('Admin@Example.com')", Server, "Admin@Example.com")
expect_value("field built as Email", Email("Admin@example.com"), _built(lambda: _srv.admin, Email))
expect_value("default port built as Port", Port(8080), _built(lambda: _srv.port, Port))
expect_value("assignment builds a Port", Port(443), _built(lambda: _set(_srv, "port", 443), Port))
expect_message("assignment: failed check",
               ("1 problem found in field assignment", "Field Server.workers of <Dataclass Server>: invalid 'int': failed check x > 0 (Value: 0)"),
               _set, _srv, "workers", 0)
expect_value("failed assignment leaves the old value", 4, lambda: _srv.workers)
expect_message("construction: invalid Port", ("invalid 'Port': must be between 1 and 65535",), Server, "a@b.io", port=70000)
expect_message("construction: invalid Email", ("invalid 'Email': must contain exactly one '@'",), Server, "nope")


def _first_problem() -> Any:
    try:
        v_even("4")
    except InvalidDataError as e:
        return e
    raise AssertionError("no error raised")


def _define_model_with_init() -> None:
    class WithInit(TypeModel[str]):
        def __init__(self, raw: str) -> None: pass


section("phase 6 · TypeModel values and errors as data")
_err = _first_problem()
expect_value("InvalidDataError is a TypeError", True, lambda: isinstance(_err, TypeError))
expect_value("problem carries kind, parameter, expected, value, origin", ("type", "n", int, "4", "v_even"),
             lambda: (lambda p: (p.kind, p.parameter, p.expected, p.value, p.origin.__name__))(_err.problems[0]))
expect_value("error pickles and keeps its message", (InvalidDataError, str(_err)),
             lambda: (lambda e: (type(e), str(e)))(pickle.loads(pickle.dumps(_err))))
expect_value("an Email is a str", (True, True, "A@B.IO"),
             lambda: (lambda e: (isinstance(e, str), e == "a@b.io", e.upper()))(Email("a@b.io")))
expect_value("Email pickles back into an Email", Email("a@b.io"), _built(lambda: pickle.loads(pickle.dumps(Email("a@b.io"))), Email))
expect_value("Port deep-copies into a Port", Port(80), _built(lambda: copy.deepcopy(Port(80)), Port))
expect_raises("TypeModel instances are immutable", setattr, Email("a@b.io"), "note", 1, exc=AttributeError)
expect_raises("a TypeModel subclass can't define __init__", _define_model_with_init, exc=TypeError)
expect_raises("TypeModel[list]: mutable base refused", lambda: TypeModel[list], exc=TypeError)


section("phase 6 · the data types of 2026-10-16")

@typecheck
def dt_signup(name: NonEmptyStr, site: Url, handle: DtSlug, phone: PhoneNumber, token: SecretStr,
              joined: AwareDatetime, share: Probability, score: Percentage) -> tuple:
    return name, site, handle, phone, token, joined, share, score

_dt_when = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
_dt_ok = ("Ana", " HTTPS://Ana.Example/blog ", " Ana-B ", "+44 20 7946 0958", "pw", _dt_when, 1, 99)
expect_value("data types: all normalised in one call",
             ("Ana", "https://ana.example/blog", "ana-b", "+442079460958", "pw", _dt_when, 1.0, 99.0), dt_signup, *_dt_ok)
expect_value("... each made the right type", [str, Url, DtSlug, PhoneNumber, SecretStr, datetime.datetime, float, float],
             lambda: [type(v) for v in dt_signup(*_dt_ok)])
expect_value("Url: parts", ("ana.example", 443, "/blog", ""),
             lambda: (lambda u: (u.host, u.port, u.path, u.query))(Url("https://ana.example/blog")))
expect_message("Url: another scheme is refused", ("invalid 'Url': must be an http or https URL",),
               dt_signup, "Ana", "ftp://x.example", *_dt_ok[2:])
expect_message("Url: a user name before the host is refused", ("must not contain a user name or password",),
               dt_signup, "Ana", "https://good.example@evil.example", *_dt_ok[2:])
expect_value("Url: an IPv6 host and a port", ("::1", 8000), lambda: (lambda u: (u.host, u.port))(Url("http://[::1]:8000")))
expect_message("NonEmptyStr: only whitespace", ("must not be empty or only whitespace",), dt_signup, "  ", *_dt_ok[1:])
expect_message("Slug: a double hyphen", ("joined by single hyphens",), dt_signup, "Ana", _dt_ok[1], "a--b", *_dt_ok[3:])
expect_message("PhoneNumber: no country code", ("+ and a country code",), dt_signup, *_dt_ok[:3], "020 7946 0958", *_dt_ok[4:])
expect_message("AwareDatetime: a naive datetime", ("must have a time zone",),
               dt_signup, *_dt_ok[:5], datetime.datetime(2026, 1, 1), *_dt_ok[6:])
expect_message("Probability and Percentage: out of range", ("must be between 0 and 1", "must be between 0 and 100"),
               dt_signup, *_dt_ok[:6], 1.5, 120)
expect_value("SecretStr: masked in repr, str and format", ("SecretStr('**********')", "**********", "**********"),
             lambda: (lambda t: (repr(t), str(t), f"{t}"))(SecretStr("hunter2")))
expect_value("... the text itself on request, and through pickle", ("hunter2", "hunter2"),
             lambda: (SecretStr("hunter2").get_secret_value(), pickle.loads(pickle.dumps(SecretStr("hunter2"))).get_secret_value()))
@typecheck
def dt_count(n: int) -> int:
    return n

expect_message("... and never in a message", ("SecretStr('**********')",), dt_count, SecretStr("hunter2"), absent=("hunter2",))


section("phase 6 · the Enforced base class")

class EbSchema(Enforced, deep=True):
    """A library's base: its users' subclasses are checked without a decorator."""
    def __init_subclass__(cls, *, name: str = "", **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.schema_name = name or cls.__name__

    def validate(self, rows: list[dict[str, float]]) -> int:
        return len(rows)

class EbPrices(EbSchema, name="prices", check_return=True):
    def scale(self, factor: float) -> float:
        return factor

    def broken(self) -> int:
        return "no"  # type: ignore[return-value]

class EbLenient(EbPrices, coerce=True):
    def take(self, n: int) -> int:
        return n

expect_value("Enforced: a subclass is checked, options from its class keywords", 2.0, EbPrices().scale, 2)
expect_raises("... a wrong argument", EbPrices().scale, "x")
expect_raises("... check_return, its own keyword", EbPrices().broken)
expect_message("... deep, from the library's base", ("For introspected parameter rows at index [0]['a']",),
               EbPrices().validate, [{"a": "x"}])
expect_value("... a grandchild inherits check_return and adds coerce", (42, (True, True, True, True, True, "raise", InvalidDataError)),
             lambda: (EbLenient().take("42"), EbLenient.__enforced_options__))
expect_raises("... and is checked on what it inherits", EbLenient().broken)
expect_value("... the library's own class keyword passes through", ("prices", "EbLenient"),
             lambda: (EbPrices.schema_name, EbLenient.schema_name))
expect_value("... an inherited method isn't wrapped again", True, lambda: EbLenient.scale is EbPrices.scale)
expect_raises("@enforce refuses a class derived from Enforced", enforce, EbPrices)
expect_raises("enforced.dataclass refuses one too", dataclass, type("EbRow", (Enforced,), {"__annotations__": {"n": int}}))
expect_raises("an unknown on_error is refused at the class", type, "EbBad", (Enforced,), {}, on_error="log")


section("phase 6 · errors as JSON")

@typecheck(deep=True)
def ej_order(customer: Email, lines: list[dict[str, int]], token: SecretStr, note: str = "") -> None: ...

def _ej_error(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> InvalidDataError:
    try:
        fn(*args, **kwargs)
    except InvalidDataError as e:
        return e
    raise AssertionError("no error")

_ej = _ej_error(ej_order, "nope", [{"pen": 1}, {"ink": "two"}], 5)
expect_value("errors(): one entry per problem, in order", ["invalid", "type", "type"], lambda: [e["type"] for e in _ej.errors()])
expect_value("... loc is a list down to the item", [["customer"], ["lines", 1, "ink"], ["token"]],
             lambda: [e["loc"] for e in _ej.errors()])
expect_value("... msg in plain words, without the value", "invalid 'Email': must contain exactly one '@'",
             lambda: _ej.errors()[0]["msg"])
expect_value("... input and ctx", ("two", "int", "Function ej_order"),
             lambda: (lambda e: (e["input"], e["ctx"]["expected"], e["ctx"]["origin"]))(_ej.errors()[1]))
expect_value("json(): the same, as text", True, lambda: json.loads(_ej.json()) == _ej.errors())
expect_value("include_input=False leaves every value out", False, lambda: any("input" in e for e in _ej.errors(include_input=False)))
expect_value("missing arguments: one entry each", [["customer"], ["lines"], ["token"]],
             lambda: [e["loc"] for e in _ej_error(ej_order).errors()])
expect_value("a SecretStr given where it doesn't fit is masked", "**********",
             lambda: _ej_error(ej_order, "a@b.co", SecretStr("hunter2"), SecretStr("x")).errors()[0]["input"])
expect_value("a call that can't be bound", [{"type": "binding", "loc": [], "msg": "got an unexpected keyword argument 'colour'",
                                           "ctx": {"context": "call"}}],
             lambda: _ej_error(ej_order, "a@b.co", [], SecretStr("x"), colour=1).errors())


section("phase 6 · make_dataclass")
MadeOrder = make_dataclass("MadeOrder", [("item", str), ("qty", int), ("price", float, field(default=0)),
                                         ("buyer", "Email | None", field(default=None))],
                           namespace={"total": lambda self: self.qty * self.price}, coerce=True)
expect_value("make_dataclass: the class belongs to the caller's module", __name__, lambda: MadeOrder.__module__)
expect_value("... fields converted and coerced", (3, 2.0), lambda: (lambda o: (o.qty, o.price))(MadeOrder("pen", "3", 2)))
expect_value("... a string annotation, read in the caller's module", Email("a@b.io"),
             lambda: MadeOrder("pen", 1, buyer="a@b.io").buyer)
expect_raises("... a wrong field is rejected on construction", MadeOrder, "pen", "many")
expect_raises("... and on assignment", lambda: setattr(MadeOrder("pen", 1), "qty", "x"))
expect_value("... a method from the namespace", 6.0, lambda: MadeOrder("pen", 3, 2).total())
expect_raises("... an unknown on_error is refused", make_dataclass, "X", [("n", int)], on_error="log")


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 7: findings of the code review (CODE_REVIEW.md), then the issues still open
# ═════════════════════════════════════════════════════════════════════════════

class Walker(Protocol):                                 # not @runtime_checkable
    def walk(self) -> None: ...

class Stack(list):
    pass


@typecheck(deep=True)
def rv_nested_check(x: list[list[PositiveInt]]) -> Any: return x
@typecheck(deep=True)
def rv_nested_band(x: dict[str, list[Band]]) -> Any: return x
@typecheck(deep=True, coerce=True)
def rv_int_keys(d: dict[int, str]) -> Any: return d
@typecheck(deep=True)
def rv_collection(c: Collection[float]) -> Any: return c
@typecheck(deep=True)
def rv_mapping(m: Mapping[str, float]) -> Any: return m
@typecheck(deep=True)
def rv_bare_tuple(t: Tuple) -> Any: return t
@typecheck(deep=True)
def rv_empty_tuple(t: Tuple[()]) -> Any: return t
@typecheck
def rv_protocol(w: Walker) -> Any: return w
@typecheck(deep=True)
def rv_protocol_items(ws: list[Walker]) -> Any: return ws
@typecheck(allow_subclass=False)
def rv_strict_any(x: Any = 5) -> Any: return x
@typecheck(allow_subclass=False)
def rv_strict_any_union(x: Any | int) -> Any: return x
@typecheck(allow_subclass=False)
def rv_strict_any_missing(x: Any, y: int) -> Any: return x
@typecheck(allow_subclass=False)
def rv_strict_type_union(c: type[int | str]) -> Any: return c

@dataclass(frozen=True)
class RvFrozenFactory:
    xs: list = field(default_factory=dict)              # type: ignore[arg-type]

@dataclass(check_assignment=False)
class RvLooseFactory:
    xs: list = field(default_factory=dict)              # type: ignore[arg-type]

@dataclass(frozen=True, deep=True)
class RvFrozenConverted:
    weights: list[float] = field(default_factory=lambda: [1, 2])

_rv_seen: list[Any] = []

def _rv_record(value: Any) -> bool:
    _rv_seen.append(value)
    return True

@dataclass(deep=True)
class RvOnce:
    rows: list[Annotated[int, _rv_record]]
    label: Annotated[str, _rv_record] = "none"
    extra: list[Annotated[int, _rv_record]] = field(default_factory=lambda: [7])

    def __post_init__(self) -> None:
        self.label = self.label.upper()


def _checks_seen(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> list[Any]:
    """The values the recording check was asked about while ``fn`` ran."""
    _rv_seen.clear()
    fn(*args, **kwargs)
    return list(_rv_seen)


def _record_order() -> Any:
    spec = {"object_name": "rv_order", "kwargs": {"x": "3"}, "coerce": True}
    typecheck_record({**spec, "record": {"x": int | float}})
    return typecheck_record({**spec, "record": {"x": float | int}})[1]["x"]


section("phase 7 · review: bad values are no longer accepted")
expect_ok("deep: list[list[PositiveInt]] valid",       rv_nested_check, [[1], [2, 3]])
expect_paths("deep: Annotated check runs one level down", ["x[1][0]"], rv_nested_check, [[1], [-5]])
expect_message("deep: nested check names the item",    ("For introspected parameter x at index [1][0] of <Function rv_nested_check>: invalid 'int': failed check x > 0 (Value: -5)",),
               rv_nested_check, [[1], [-5]])
expect_paths("deep: every check of the item type runs on nested items", ["x['b'][1]"], rv_nested_band, {"a": [15], "b": [15, 25]})
for _address in ("a\n@b.com", "a@b\n.com", "a@b.com\n.org"):
    expect_raises(f"Email({_address!r}) raises ValueError", Email, _address, exc=ValueError)
expect_value("Email still strips surrounding whitespace", Email("a@b.com"), Email, " a@b.com\n")
expect_message("deep + coerce: keys that convert to the same key are rejected",
               ("For parameter d of <Function rv_int_keys>: invalid 'dict[int, str]': keys '1' and 1 both convert to 1",),
               rv_int_keys, {"1": "a", 1: "b", " 1": "c"})
expect_exact("deep + coerce: distinct keys still convert", {1: "a", 2: "b"}, rv_int_keys, {"1": "a", "2": "b"})
expect_raises("frozen dataclass: default_factory result is checked", RvFrozenFactory)
expect_message("check_assignment=False: default_factory result is checked",
               ("Field RvLooseFactory.xs of <Dataclass RvLooseFactory>: expected type: 'list', got type 'dict'",), RvLooseFactory)
expect_exact("frozen dataclass: default_factory result is converted", [1.0, 2.0], lambda: RvFrozenConverted().weights)
expect_value("frozen dataclass: a supplied value doesn't call the factory", [0.5], lambda: RvFrozenConverted([0.5]).weights)

section("phase 7 · review: converted containers keep their type")
for _value in ([1, 2], (1, 2), deque([1, 2], maxlen=4), Stack([1, 2])):
    expect_value(f"deep: Collection[float] ← {type(_value).__name__} of ints keeps its type", type(_value),
                 lambda v=_value: type(rv_collection(v)))
for _value in ({1: "a"}, range(3), {1: "a"}.keys(), b"ab"):
    expect_message(f"deep: Collection[float] ← {type(_value).__name__} of ints is rejected, not turned into a list",
                   (f"invalid 'collections.abc.Collection[float]': its items need converting, but a {type(_value).__name__} cannot be rebuilt",),
                   rv_collection, _value)
_float_keys = {1.0: "a"}
expect_value("deep: a dict with valid keys passes as it is", True, lambda: rv_collection(_float_keys) is _float_keys)
expect_message("deep: Mapping[str, float] ← mappingproxy of ints is rejected, not turned into a dict",
               ("but a mappingproxy cannot be rebuilt with the converted items",), rv_mapping, MappingProxyType({"a": 1}))

section("phase 7 · review: valid values are no longer rejected")
expect_value("deep: typing.Tuple ← (1, 2)",            (1, 2), rv_bare_tuple, (1, 2))
expect_raises("deep: typing.Tuple still needs a tuple", rv_bare_tuple, [1, 2])
expect_raises("deep: Tuple[()] still means empty",     rv_empty_tuple, (1, 2))
expect_value("strict: x: Any = 5 is a valid default",  5, rv_strict_any)
expect_value("strict: Any accepts any value",          "text", rv_strict_any, "text")
expect_value("strict: Any | int ← 'a'",                "a", rv_strict_any_union, "a")
expect_message("strict: Any isn't blamed beside a missing argument", ("1 problem found in call", "Missing required argument"),
               rv_strict_any_missing, "s", absent=("For parameter x",))
expect_value("strict: type[int | str] ← int",          int, rv_strict_type_union, int)
expect_value("strict: type[int | str] ← str",          str, rv_strict_type_union, str)
expect_raises("strict: type[int | str] rejects bool (a subclass)", rv_strict_type_union, bool)
expect_message("Protocol without @runtime_checkable: a clear error",
               ("Cannot check Protocol Walker for parameter w: decorate it with @runtime_checkable",), rv_protocol, object())
expect_message("Protocol without @runtime_checkable inside a collection",
               ("Cannot check Protocol Walker for parameter ws",), rv_protocol_items, [object()])
expect_value("typecheck_record: float | int ← '3' gives 3.0 even after int | float was seen", 3.0, _record_order)

section("phase 7 · review: a dataclass field is validated once")
_rows = [1, 2]
RvOnce(_rows)                                           # the first use also checks the defaults
expect_value("construction: each item and the factory result checked once", [1, 2, 7, "NONE"], _checks_seen, RvOnce, _rows)
expect_value("construction: a supplied label is checked once, its __post_init__ value too", [1, 2, "a", 7, "A"],
             _checks_seen, RvOnce, _rows, "a")
_once = RvOnce(_rows)
expect_value("assignment after construction is checked", [3, 4], _checks_seen, setattr, _once, "rows", [3, 4])
expect_raises("assignment of a bad item is rejected", setattr, _once, "rows", [3, "x"])
expect_raises("construction with a bad item is rejected", RvOnce, [1, "x"])


# ── the second review: file annotations, checked dataclasses that inherit, decorator order ──

@typecheck
def rv_text(out: TextIO) -> Any: return out
@typecheck
def rv_binary(raw: BinaryIO) -> Any: return raw
@typecheck
def rv_any_file(f: IO) -> Any: return f
@typecheck
def rv_text_or_none(f: IO[str] | None = None) -> Any: return f
@typecheck(allow_subclass=False)
def rv_text_strict(out: TextIO) -> Any: return out
@typecheck(deep=True)
def rv_binary_files(fs: list[IO[bytes]]) -> Any: return fs

@dataclass
class RvReport:
    out: TextIO = sys.stdout
    raw: BinaryIO | None = None

class RvWriter:
    """Enough for print(), but not a file."""
    def write(self, text: str) -> int: return len(text)

_rv_text, _rv_bytes = io.StringIO(), io.BytesIO()
_rv_null = open(os.devnull, "w")
_rv_temp = tempfile.NamedTemporaryFile("w+")                # a wrapper object, not an io class
_rv_temp_binary = tempfile.NamedTemporaryFile()


section("phase 7 · review 2: file annotations accept files")
expect_value("TextIO ← sys.stdout",                     True, lambda: rv_text(sys.stdout) is sys.stdout)
expect_value("TextIO ← an open text file",              True, lambda: rv_text(_rv_null) is _rv_null)
expect_value("TextIO ← io.StringIO()",                  True, lambda: rv_text(_rv_text) is _rv_text)
expect_value("TextIO ← tempfile.NamedTemporaryFile('w+')", True, lambda: rv_text(_rv_temp) is _rv_temp)
expect_raises("TextIO ← io.BytesIO() (a binary file)",  rv_text, _rv_bytes)
expect_raises("TextIO ← a binary NamedTemporaryFile",   rv_text, _rv_temp_binary)
expect_raises("TextIO ← 'notes.txt' (the path, not the file)", rv_text, "notes.txt")
expect_raises("TextIO ← io.StringIO (the class)",       rv_text, io.StringIO)
expect_raises("TextIO ← an object with only write()",   rv_text, RvWriter())
expect_value("BinaryIO ← io.BytesIO()",                 True, lambda: rv_binary(_rv_bytes) is _rv_bytes)
expect_value("BinaryIO ← sys.stdout.buffer",            True, lambda: rv_binary(_rv_null.buffer) is _rv_null.buffer)
expect_value("BinaryIO ← a binary NamedTemporaryFile",  True, lambda: rv_binary(_rv_temp_binary) is _rv_temp_binary)
expect_raises("BinaryIO ← a text file",                 rv_binary, _rv_null)
expect_value("IO ← text and binary files alike",        True, lambda: rv_any_file(_rv_text) is _rv_text and rv_any_file(_rv_bytes) is _rv_bytes)
expect_raises("IO ← 5",                                 rv_any_file, 5)
expect_value("IO[str] | None ← None, and ← a text file", True, lambda: rv_text_or_none() is None and rv_text_or_none(_rv_text) is _rv_text)
expect_raises("IO[str] | None ← a binary file",         rv_text_or_none, _rv_bytes)
expect_value("strict mode: TextIO ← io.StringIO()",     True, lambda: rv_text_strict(_rv_text) is _rv_text)
expect_raises("strict mode: TextIO ← io.BytesIO()",     rv_text_strict, _rv_bytes)
expect_value("deep: list[IO[bytes]] ← two binary files", 2, lambda: len(rv_binary_files([_rv_bytes, _rv_temp_binary])))
expect_paths("deep: list[IO[bytes]] points at the text file", ["fs[1]"], rv_binary_files, [_rv_bytes, _rv_text])
expect_message("the message names the annotation",      ("For parameter out of <Function rv_text>: expected type: 'typing.TextIO', got type '_io.BytesIO'",),
               rv_text, _rv_bytes)
expect_message("... also for IO[str] in a union",       ("expected type: 'IO[str]' | 'NoneType', got type 'int'",), rv_text_or_none, 5)
_rv_report = expect_ok("dataclass: out: TextIO = sys.stdout", RvReport)
expect_ok("dataclass: assign a text file, then a binary one to the other field",
          lambda: (setattr(_rv_report, "out", _rv_text), setattr(_rv_report, "raw", _rv_bytes)))
expect_message("dataclass: a binary file for the text field", ("Field RvReport.out of <Dataclass RvReport>: expected type: 'typing.TextIO'",),
               setattr, _rv_report, "out", _rv_bytes)
for _rv_file in (_rv_null, _rv_temp, _rv_temp_binary):
    _rv_file.close()


class RvInt(int):
    pass

@dataclass(deep=True)
class RvRows:
    rows: list[Annotated[int, _rv_record]]

@dataclass(deep=True)
class RvNamedRows(RvRows):
    name: str = "n"

@dataclass(deep=True)
class RvTaggedRows(RvNamedRows):
    tags: list[Annotated[int, _rv_record]] = field(default_factory=lambda: [9])

@dataclass(allow_subclass=False)
class RvExact:
    x: int = 0

@dataclass
class RvLoose(RvExact):
    y: int = 0

@dataclass(check_assignment=False)
class RvUnchecked(RvExact):
    y: int = 0

@dataclass
class RvRetyped(RvExact):
    x: str = "a"                                            # type: ignore[assignment]

@dataclass
class RvOwnSetattr(RvExact):
    x: str = "a"                                            # type: ignore[assignment]

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)                    # leads to RvExact's check

class RvMiddle(RvExact):                                    # not decorated
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)

@dataclass
class RvBelowMiddle(RvMiddle):
    x: str = "a"                                            # type: ignore[assignment]

class RvPlainSub(RvExact):                                  # not decorated: RvExact's check is its check
    pass

@dataclasses.dataclass
class RvStdlibBase:
    xs: list = field(default_factory=dict)                  # type: ignore[arg-type]

@dataclass(check_assignment=False)
class RvStdlibChild(RvStdlibBase):
    y: int = 0

@dataclass(deep=True)
class RvRatios:
    ratios: list[float] = field(default_factory=lambda: [1, 2])

@dataclass(deep=True, convert=False, check_assignment=False)
class RvExactRatios(RvRatios):
    pass


def _rv_setattr_depth(cls: type) -> bool:
    """Whether ``cls``'s generated __setattr__ hands a checked value straight to object.__setattr__."""
    return vars(cls)["__setattr__"].__enforced_wraps__ is object.__setattr__


section("phase 7 · review 2: one check in a dataclass hierarchy, the class's own")
for _rv_cls in (RvRows, RvNamedRows, RvTaggedRows):
    _rv_cls([0])                                            # the first use also checks the defaults
_rv_rows = RvTaggedRows([0])
expect_value("subclass construction: each item checked once", [1, 2], _checks_seen, RvNamedRows, [1, 2])
expect_value("two levels down, with a factory: each item checked once", [1, 2, 9], _checks_seen, RvTaggedRows, [1, 2])
expect_value("subclass assignment: each item checked once", [3, 4], _checks_seen, setattr, _rv_rows, "rows", [3, 4])
expect_value("every level's __setattr__ stores through object.__setattr__", (True, True, True),
             lambda: tuple(_rv_setattr_depth(c) for c in (RvRows, RvNamedRows, RvTaggedRows)))
expect_value("a default subclass of a strict base accepts an int subclass", RvInt(1), lambda: RvLoose(RvInt(1)).x)
expect_ok("... on assignment too",                      lambda: setattr(RvLoose(), "x", RvInt(2)))
expect_raises("... while the strict base still rejects it", RvExact, RvInt(1))
expect_raises("... on assignment too",                  lambda: setattr(RvExact(), "x", RvInt(2)))
expect_message("a subclass's error names the subclass", ("Field RvLoose.x of <Dataclass RvLoose>: expected type: 'int', got type 'str'",),
               lambda: setattr(RvLoose(), "x", "1"))
_rv_unchecked = RvUnchecked()
expect_ok("check_assignment=False subclass: an inherited field isn't checked", setattr, _rv_unchecked, "x", "text")
expect_ok("... nor its own",                            setattr, _rv_unchecked, "y", "text")
expect_raises("... its construction still is",          RvUnchecked, "1")
expect_value("a subclass may give an inherited field another type", "b", lambda: RvRetyped("b").x)
expect_value("... its default included",                "a", lambda: RvRetyped().x)
expect_message("... and is checked against that type",  ("Field RvRetyped.x of <Dataclass RvRetyped>: expected type: 'str', got type 'int'",),
               lambda: setattr(RvRetyped(), "x", 5))
expect_value("a subclass with its own __setattr__ that calls super()", "c", lambda: (o := RvOwnSetattr("b"), setattr(o, "x", "c"), o.x)[2])
expect_raises("... is still checked, once, by its own check", lambda: setattr(RvOwnSetattr(), "x", 5))
expect_value("a hand-written __setattr__ in a class between the two", "c", lambda: (o := RvBelowMiddle("b"), setattr(o, "x", "c"), o.x)[2])
expect_raises("... the undecorated class in the middle keeps the base's check", lambda: setattr(RvMiddle(), "x", "c"))
expect_raises("an undecorated subclass keeps the base's check", lambda: setattr(RvPlainSub(), "x", RvInt(1)))
expect_raises("the base stays strict after all of that", lambda: setattr(RvExact(), "x", RvInt(1)))
expect_message("inherited default_factory of a stdlib dataclass is checked", ("Field RvStdlibChild.xs of <Dataclass RvStdlibChild>: expected type: 'list', got type 'dict'",),
               RvStdlibChild)
expect_exact("inherited default_factory: the base converts its result", [1.0, 2.0], lambda: RvRatios().ratios)
expect_message("... a convert=False subclass rejects it", ("RvExactRatios.ratios",), RvExactRatios)


class RvAccount:
    def __init__(self) -> None:
        self._balance = 0.0

    @typecheck
    @classmethod
    def named(cls, name: str, scale: float = 1) -> str: return f"{cls.__name__}:{name}:{scale!r}"

    @typecheck
    @staticmethod
    def double(x: float) -> float: return x * 2

    @typecheck(check_return=True)
    @property
    def balance(self) -> float: return self._balance

    @typecheck
    @balance.setter
    def balance(self, value: float) -> None: self._balance = value

    @typecheck(check_return=True)
    @functools.cached_property
    def limit(self) -> float: return 100

class RvSavings(RvAccount):
    pass

_rv_account = RvAccount()


section("phase 7 · review 2: @typecheck above another decorator")
expect_value("above @classmethod: called on the class",  "RvAccount:a:1.0", RvAccount.named, "a")
expect_value("... on an instance, and on a subclass",    ("RvAccount:a:2.0", "RvSavings:a:1.0"), lambda: (_rv_account.named("a", 2), RvSavings.named("a")))
expect_raises("... a bad argument",                      RvAccount.named, 1)
expect_value("above @staticmethod: on the class and on an instance", (4.0, 4.0), lambda: (RvAccount.double(2), _rv_account.double(2)))
expect_raises("... a bad argument",                      _rv_account.double, "2")
expect_value("above @property: reading gives the value", 0.0, lambda: _rv_account.balance)
expect_value("... the setter converts",                  5.0, lambda: (setattr(_rv_account, "balance", 5), _rv_account.balance)[1])
expect_message("... and rejects",                        ("For parameter value of <Method RvAccount.balance>: expected type: 'float', got type 'str'",),
               setattr, _rv_account, "balance", "5")
expect_value("above @cached_property: the value, converted once", 100.0, lambda: _rv_account.limit)
expect_value("the attributes are still what the other decorator made", ("classmethod", "staticmethod", "property", "cached_property"),
             lambda: tuple(type(vars(RvAccount)[n]).__name__ for n in ("named", "double", "balance", "limit")))
expect_message("something that can't be called is refused at the definition",
               ("typecheck cannot check 42: a int object is not callable", "Put @typecheck directly above the function"), typecheck, 42)


RvSameShape = TypeVar("RvSameShape", bound="RvShape")       # the class is defined below: the bound is a string
RvShapeOrInt = TypeVar("RvShapeOrInt", "RvShape", "int")

class RvShape:
    @typecheck(check_return=True)
    def beside(self: RvSameShape, other: RvSameShape) -> RvSameShape: return other

class RvCircle(RvShape):
    pass

@typecheck(check_return=True)
def rv_same_shape(x: RvSameShape) -> RvSameShape: return x
@typecheck(deep=True)
def rv_shapes(xs: list[RvSameShape]) -> Any: return xs
@typecheck
def rv_shape_or_int(x: RvShapeOrInt) -> Any: return x

_rv_circle = RvCircle()


section("phase 7 · review 2: TypeVar with a string bound")
expect_value("TypeVar(bound='RvShape') ← an RvCircle",   True, lambda: rv_same_shape(_rv_circle) is _rv_circle)
expect_message("... ← 5 is rejected against the class",  ("RvShape', got type 'int' (Value: 5)",), rv_same_shape, 5)
expect_value("the method that returns its own type",     True, lambda: RvShape().beside(_rv_circle) is _rv_circle)
expect_raises("... a bad argument",                      RvShape().beside, "circle")
expect_ok("deep: list[T] with a string bound",           rv_shapes, [_rv_circle, RvShape()])
expect_paths("... points at the bad item",               ["xs[1]"], rv_shapes, [_rv_circle, 5])
expect_value("string constraints: TypeVar('T', 'RvShape', 'int') ← 5", 5, rv_shape_or_int, 5)
expect_raises("... ← 'a'",                               rv_shape_or_int, "a")


_rv_ran: list[int] = []

def _rv_record_string(annotation: Any, value: Any, **options: Any) -> Any:
    """typecheck_record with ``annotation`` for its one parameter; ``_rv_ran`` fills up if a string in it is run."""
    import builtins
    builtins._rv_ran = _rv_ran                              # type: ignore[attr-defined]  (what eval would reach)
    _rv_ran.clear()
    try:
        return typecheck_record({"object_name": "rv_record", "record": {"x": annotation}, "args": (value,), **options})[0][0]
    finally:
        del builtins._rv_ran                                # type: ignore[attr-defined]


section("phase 7 · review 2: strings in a record are read, never run")
expect_value("record 'int' ← 1",                         1, _rv_record_string, "int", 1)
expect_raises("record 'int' ← 'a'",                      _rv_record_string, "int", "a")
expect_value("record 'list[int] | None' ← None",         None, _rv_record_string, "list[int] | None", None)
expect_exact("record 'dict[str, tuple[int, ...]]' ← a valid dict", {"a": (1, 2)}, _rv_record_string, "dict[str, tuple[int, ...]]", {"a": (1, 2)})
expect_paths("deep: the items of a string annotation are checked", ["x['a'][1]"], _rv_record_string, "dict[str, list[int]]", {"a": [1, "2"]}, deep=True)
expect_exact("deep + convert: and converted",            [1.0, 2.5], _rv_record_string, "list[float]", [1, 2.5], deep=True)
for _rv_code in ("_rv_ran.append(1) or int", "__import__('os').getcwd() and int", "(lambda: _rv_ran.append(1))() or int",
                 "[_rv_ran.append(1) for _ in (1,)] and int", "int.__subclasses__()[0]", "eval", "open('x')"):
    expect_message(f"record {_rv_code!r} is refused", ("Cannot resolve annotation",), _rv_record_string, _rv_code, 1)
    expect_value("... and nothing in it ran",            [], lambda: list(_rv_ran))
expect_message("a string nested in a generic is refused the same way", ("Cannot resolve annotation",),
               _rv_record_string, list["_rv_ran.append(1) or int"], [1], deep=True)
expect_value("... and nothing in it ran",                [], lambda: list(_rv_ran))


# ── review 4: the Medium findings 4 to 10, and static typing ─────────────────────

class R4Film(TypedDict):
    year: float
    title: NotRequired[str]

class R4Shelf(dict):
    pass

@typecheck(deep=True)
def r4_film(m: R4Film) -> Any: return m

@typecheck(deep=True)
def r4_prices(m: ChainMap[str, float]) -> Any: return m


section("phase 7 · review 4: a converted mapping keeps its own type")
_r4_ordered = OrderedDict(title="Up", year=2009)
expect_value("TypedDict from an OrderedDict: still one, in order",   (OrderedDict, [("title", "Up"), ("year", 2009.0)]),
             lambda: (lambda out: (type(out), list(out.items())))(r4_film(_r4_ordered)))
expect_value("... and the caller's own is untouched",                2009, lambda: _r4_ordered["year"])
expect_value("TypedDict from a defaultdict keeps its factory",       (defaultdict, list),
             lambda: (lambda out: (type(out), out.default_factory))(r4_film(defaultdict(list, year=1))))
expect_value("TypedDict from a dict subclass",                       R4Shelf, lambda: type(r4_film(R4Shelf(year=1))))
expect_value("nothing to convert: the same object",                  True, lambda: (lambda d: r4_film(d) is d)(R4Shelf(year=1.5)))
expect_value("ChainMap: the maps stay apart, each its own type",     ([{"a": 1.0}, {"b": 2.0}], [dict, OrderedDict]),
             lambda: (lambda out: ([dict(m) for m in out.maps], [type(m) for m in out.maps]))(
                 r4_prices(ChainMap({"a": 1}, OrderedDict(b=2)))))
expect_value("ChainMap: a hidden entry stays hidden and unconverted", (1.0, {"a": "hidden", "b": 2.0}),
             lambda: (lambda out: (out["a"], out.maps[1]))(r4_prices(ChainMap({"a": 1}, {"a": "hidden", "b": 2}))))
expect_paths("ChainMap: a bad value is still reported",              ["m['b']"], r4_prices, ChainMap({"a": 1.0}, {"b": "x"}))


class R4Options(TypedDict, total=False):
    name: Required[str]
    size: int

@typecheck(check_return=True)
def r4_build(count: int, **options: Unpack[R4Options]) -> dict: return options

@typecheck
def r4_move(speed: float, *point: *tuple[int, str]) -> Any: return speed, point

@typecheck
def r4_floats(*values: *tuple[float, ...]) -> Any: return values

@typecheck
def r4_query(sql: LiteralString) -> Any: return sql

@typecheck(check_return=True)
def r4_is_int(value: object) -> TypeGuard[int]: return "yes"            # type: ignore[return-value]

class R4Lone:
    @typecheck(check_return=True)
    def link(self, other: Self) -> Self: return other

    @typecheck
    @staticmethod
    def static(n: int) -> int: return n

class R4Adder:
    def __call__(self, a: int, b: float = 0) -> float: return a + b

def r4_send(host: str, port: int, retries: float = 1) -> tuple: return host, port, retries

R4ListOrMap = TypeVar("R4ListOrMap", list[int], dict[str, float])

@typecheck(deep=True)
def r4_constrained(x: R4ListOrMap) -> Any: return x

def _r4_record(annotation: Any) -> Any:
    return typecheck_record({"object_name": "f", "record": {"x": annotation}, "kwargs": {"x": "anything"}})


section("phase 7 · review 4: annotations and targets that were accepted without a check")
expect_exact("**kwargs: Unpack[TypedDict]: valid, optional key left out", {"name": "a"}, r4_build, 1, name="a")
expect_exact("... again, through the compiled wrapper",              {"name": "b", "size": 2}, r4_build, 2, name="b", size=2)
expect_message("... a wrong value is reported by its key",           ("For parameter size of <Function r4_build>",), r4_build, 1, name="a", size="2")
expect_message("... an unknown keyword",                             ("unexpected keyword argument 'colour'",), r4_build, 1, name="a", colour="red")
expect_message("... a missing required key",                         ("Missing required argument for <Function r4_build>: name",), r4_build, 1)
expect_value("... the written signature is what inspect shows",      True, lambda: "**options" in str(inspect.signature(r4_build)))
expect_exact("*args: *tuple[int, str]: valid, speed converted",      (1.0, (2, "north")), r4_move, 1, 2, "north")
expect_paths("... each position has its type",                       ["point[0]", "point[1]"], r4_move, 1.0, "north", 2)
expect_message("... and the count is part of it",                    ("expected type: tuple[int, str] with 2 items, got 3 items",), r4_move, 1.0, 2, "n", 3)
expect_exact("*args: *tuple[float, ...] is *args: float",            (1.0, 2.5), r4_floats, 1, 2.5)
expect_raises("... bad item",                                        r4_floats, 1.0, "x")
expect_message("LiteralString is a str",                             ("expected type: 'str', got type 'int'",), r4_query, 5)
expect_message("-> TypeGuard[int] must return a bool",               ("For return value of <Function r4_is_int>: expected type: 'bool'",), r4_is_int, 1)
expect_message("Self in a method decorated on its own",              ("For parameter other of <Method R4Lone.link>", "R4Lone'"), R4Lone().link, 5)
expect_ok("... valid",                                               R4Lone().link, R4Lone())
expect_message("a static method decorated on its own names its class", ("<Method R4Lone.static>",), R4Lone.static, "x")
expect_exact("an object with __call__ is checked, and converted",    3.0, typecheck(R4Adder()), 1, 2)
expect_message("... bad argument",                                   ("For parameter b of <Callable R4Adder>",), typecheck(R4Adder()), 1, "2")
expect_value("functools.partial: the parameters it still takes",     ("localhost", 80, 1), typecheck(functools.partial(r4_send, "localhost")), 80)
expect_paths("... bad argument",                                     ["port"], typecheck(functools.partial(r4_send, "localhost")), "80")
expect_value("a builtin without a readable signature still works",   3, typecheck(max), 1, 3, 2)
expect_paths("TypeVar constraints: items checked with deep",         ["x[0]"], r4_constrained, ["a"])
expect_value("... valid, converted",                                 {"a": 1.0}, r4_constrained, {"a": 1})
for _r4_bad in (5, ["int"], {"a": "int"}, "5", (int, str)):
    expect_message(f"a record value that is no annotation: {_r4_bad!r}", ("is not a type annotation",), _r4_record, _r4_bad)
expect_ok("a record string that is one",                             typecheck_record, {"object_name": "f", "record": {"x": "int | None"}, "kwargs": {"x": None}})


class R4Color(enum.Enum):
    RED = 1

type R4Mode = Literal["r", "w"]

@typecheck
def r4_messages(mode: Literal["r", "w"] = "r", kind: type[int] = int, maybe: Literal["r"] | None = None,
                alias: R4Mode = "r", color: R4Color = R4Color.RED, both: int | str = 1) -> None: pass

@typecheck(deep=True)
def r4_modes(modes: list[Literal["a", "b"]]) -> None: pass

@dataclass
class R4Config:
    mode: Literal["r", "w"] = "r"
    kind: type[int] = int
    color: R4Color = R4Color.RED


section("phase 7 · review 4: a message shows the annotation where the type alone would mislead")
expect_message("Literal, wrong value of the right type",             ("expected type: Literal['r', 'w'], got type 'str' (Value: 'x')",), r4_messages, mode="x")
expect_message("type[int] given another class",                      ("expected type: 'type[int]', got type 'type' (Value: <class 'str'>)",), r4_messages, kind=str)
expect_message("Literal | None",                                     ("expected type: Literal['r'] | None, got type 'int'",), r4_messages, maybe=5)
expect_message("a Literal behind a type alias",                      ("expected type: Literal['r', 'w'], got type 'str'",), r4_messages, alias="x")
expect_message("an Enum class is named like any class",              ("expected type: '__main__.R4Color', got type 'int'",), r4_messages, color=5)
expect_message("an ordinary union reads as before",                  ("expected type: 'int' | 'str', got type 'float' (Value: 1.5)",), r4_messages, both=1.5)
expect_message("a Literal item inside a list",                       ("modes at index [1] of <Function r4_modes>: expected type: Literal['a', 'b'], got type 'str'",), r4_modes, ["a", "c"])
expect_message("dataclass field, Literal",                           ("Field R4Config.mode of <Dataclass R4Config>: expected type: Literal['r', 'w'], got type 'str'",), setattr, R4Config(), "mode", "x")
expect_message("dataclass field, type[int]",                         ("expected type: 'type[int]', got type 'type'",), setattr, R4Config(), "kind", str)
expect_message("dataclass field, Enum",                              ("expected type: '__main__.R4Color', got type 'int'",), setattr, R4Config(), "color", 5)


def _r4_cache_stays_small() -> tuple[bool, bool, bool]:
    """Fill each annotation cache past a small limit: the newest entry is always kept, the size is bounded."""
    import enforced._typechecker._container as _container
    import enforced._typechecker._lifetime as _lifetime
    saved = (_container._UNPACKED_MAX, _specs._DEEP_NODES_MAX, _codegen._CODE_CACHE_MAX,
             dict(_container._UNPACKED), dict(_specs._DEEP_NODES), dict(_codegen._CODE_CACHE))
    try:
        _container._UNPACKED_MAX, _specs._DEEP_NODES_MAX, _codegen._CODE_CACHE_MAX = 8, 8, 4
        _container._UNPACKED.clear(); _specs._DEEP_NODES.clear(); _codegen._CODE_CACHE.clear()
        ok_unpacked = ok_nodes = ok_code = True
        for i in range(30):
            annotation = list[int]
            _container.TypeContainer(None, "x", 1, annotation)
            ok_unpacked &= id(annotation) in _container._UNPACKED and len(_container._UNPACKED) <= 8
            _specs.deep_node(annotation, True, True, False)
            ok_nodes &= (id(annotation), True, True, False) in _specs._DEEP_NODES and len(_specs._DEEP_NODES) <= 8
            namespace: dict[str, Any] = {}
            exec(f"def f({', '.join(f'p{n}: int' for n in range(i % 9 + 1))}): return 1", namespace)
            f = typecheck(namespace["f"])
            f(*range(i % 9 + 1))
            ok_code &= f.__enforced_source__ in _codegen._CODE_CACHE and len(_codegen._CODE_CACHE) <= 4
        return ok_unpacked, ok_nodes, ok_code
    finally:
        _container._UNPACKED_MAX, _specs._DEEP_NODES_MAX, _codegen._CODE_CACHE_MAX = saved[:3]
        for cache, old in zip((_container._UNPACKED, _specs._DEEP_NODES, _codegen._CODE_CACHE), saved[3:]):
            cache.clear(); cache.update(old)


section("phase 7 · review 4: the annotation caches let their oldest entry go")
import enforced._typechecker._codegen as _codegen
import enforced._typechecker._remembered as _remembered
import enforced._typechecker._specs as _specs
expect_value("unpacked annotations, deep nodes, wrapper code: newest kept, size bounded", (True, True, True), _r4_cache_stays_small)


@typecheck(allow_subclass=False)
def r4_strict(path: pathlib.Path = pathlib.Path("a"), pure: pathlib.PurePath | None = None, weight: numbers.Number = 1,
              keys: KeysView | None = None, cls: type = int, error: Exception | None = None, n: int = 1) -> Any:
    return path

@enforce(check_return=True, allow_subclass=False)
class R4Builder:
    def me(self) -> Self: return self
    def after(self, other: Self) -> Self: return other
    def broken(self) -> Self: return 5                                  # type: ignore[return-value]

class R4Special(R4Builder):
    pass


section("phase 7 · review 4: strict mode and classes with no instance of exactly their own type")
expect_value("strict pathlib.Path, as default and as argument",      pathlib.Path("b"), r4_strict, pathlib.Path("b"))
expect_ok("strict PurePath",                                         r4_strict, pure=pathlib.PurePath("b"))
expect_ok("strict numbers.Number: a float",                          r4_strict, weight=1.5)
expect_raises("... a str is still rejected",                         r4_strict, weight="1")
expect_ok("strict KeysView: dict keys",                              r4_strict, keys={}.keys())
expect_ok("strict type: an Enum class, an ABC",                      lambda: (r4_strict(cls=R4Color), r4_strict(cls=Sequence)))
expect_raises("... not an instance",                                 r4_strict, cls=5)
expect_raises("strict Path: a str is still rejected",                r4_strict, "a")
expect_raises("an ordinary class stays exact: Exception <- ValueError", r4_strict, error=ValueError("x"))
expect_raises("... int <- True",                                     r4_strict, n=True)
expect_value("strict Self: an inherited method returning self",      True, lambda: (lambda s: s.me() is s and s.after(s) is s)(R4Special()))
expect_message("... a wrong value is still rejected",                ("For return value of <Method R4Builder.broken>", "R4Special'"), R4Special().broken)


def _r4_local_names() -> tuple[Any, ...]:
    """A quoted annotation naming a class that is local to this function: a function, a dataclass, an enforced class."""
    class Inner:
        pass

    @typecheck
    def f(x: "Inner", others: "list[Inner] | None" = None) -> Any: return x

    @dataclass
    class Holder:
        inner: "Inner"

    @enforce
    class Service:
        def use(self, inner: "Inner", holder: "Holder | None" = None) -> Any: return inner

    return Inner, f, Holder, Service

R4Inner, r4_local_f, R4Holder, R4Service = _r4_local_names()            # the function has returned: its scope is gone

_R4_FUTURE = """
from __future__ import annotations
from enforced import dataclass, enforce, typecheck

@dataclass
class Box[T]:
    item: T
    count: int = 0

@enforce
class Stack[T]:
    def push(self, item: T, times: int = 1) -> list:
        return [item] * times

def build():
    class Inner:
        pass

    @typecheck
    def f(x: Inner) -> Inner:
        return x
    return Inner, f
"""
#* A real module: under the future import, dataclasses looks a class's module up to read its annotations.
_r4_future_module = types.ModuleType("r4_future_module")
sys.modules["r4_future_module"] = _r4_future_module
_r4_future = vars(_r4_future_module)
exec(compile(_R4_FUTURE, "<a module under the future import>", "exec"), _r4_future)
R4FutureInner, r4_future_f = _r4_future["build"]()


section("phase 7 · review 4: names a string annotation may use")
expect_ok("quoted local class: function",                            r4_local_f, R4Inner(), [R4Inner()])
expect_message("... wrong type, not 'Cannot resolve'",               ("expected type: '__main__._r4_local_names.<locals>.Inner'",), r4_local_f, 5)
expect_ok("quoted local class: dataclass field",                     R4Holder, R4Inner())
expect_raises("... bad",                                             R4Holder, 5)
expect_ok("quoted local class: enforced method",                     R4Service().use, R4Inner(), R4Holder(R4Inner()))
expect_raises("... bad",                                             R4Service().use, R4Inner(), 5)
expect_value("future import: a generic dataclass can be built",      ("anything", 2), lambda: (lambda b: (b.item, b.count))(_r4_future["Box"]("anything", 2)))
expect_message("... and its other fields are checked",               ("For parameter count of <Dataclass Box>",), _r4_future["Box"], 1, "2")
expect_value("future import: a method naming the type parameter",    [1, 1], _r4_future["Stack"]().push, 1, 2)
expect_message("... bad",                                            ("For parameter times of <Method Stack.push>",), _r4_future["Stack"]().push, 1, "2")
expect_ok("future import: a local class, after its scope is gone",   r4_future_f, R4FutureInner())
expect_raises("... bad",                                             r4_future_f, 5)


R4Json = Union[None, bool, int, float, str, List["R4Json"], Dict[str, "R4Json"]]

@typecheck(deep=True)
def r4_load(v: R4Json) -> Any: return v

@dataclass(deep=True)
class R4Doc:
    body: R4Json = None

_r4_loop: list[Any] = []
_r4_loop.append(_r4_loop)


section("phase 7 · review 4: the old way to write a recursive alias, with deep")
expect_ok("valid, nested",                                           r4_load, {"a": [1, {"b": None, "c": [1.5, "x"]}]})
expect_paths("a bad leaf, three levels down",                        ["v['a'][1]['b']"], r4_load, {"a": [1, {"b": object()}]})
expect_paths("a bad key",                                            ["v[key 1]"], r4_load, {1: 1})
expect_message("data that contains itself",                          ("value contains itself or is nested too deeply",), r4_load, _r4_loop)
expect_ok("as a dataclass field",                                    R4Doc, {"a": [1]})
expect_raises("... bad",                                             R4Doc, {"a": [object()]})
expect_raises("... bad assignment",                                  setattr, R4Doc(), "body", [object()])


# ── review 5: what was still open (1, 3, 11 to 32), and the functional API ──────────────
from typing import no_type_check as typing_no_type_check       # noqa: E402

class R5VeryLongClassNameNumberOne:
    pass

class R5VeryLongClassNameNumberTwo:
    pass

@typecheck
def r5_long(x: defaultdict[str, R5VeryLongClassNameNumberOne] | type[R5VeryLongClassNameNumberTwo] | Literal["some-quite-long-literal"] | None) -> Any:
    return x

class R5Broken:
    __signature__ = "nonsense"
    def __call__(self, x: int) -> Any: return x

@dataclass
class R5Job:
    name: str
    retries: int = field(init = False, default = "three")          # type: ignore[assignment]


@typecheck
def r5_numbers(start: int = 5, step: float = 1):
    yield start
    yield start + step

@typecheck
async def r5_stream(start: int = 5):
    yield start

@enforce
class R5Feed:
    def items(self, n: int):
        yield from range(n)
    def plain(self, a, b = 1):
        return a, b
    def typed(self, a: int):
        return a

section("phase 7 · review 5: a checked generator function is one for inspect")
expect_value("inspect.isgeneratorfunction",                           True, inspect.isgeneratorfunction, r5_numbers)
expect_value("... and for an async generator function",              True, inspect.isasyncgenfunction, r5_stream)
expect_value("... and for a generator method of an enforced class",  True, inspect.isgeneratorfunction, R5Feed().items)
expect_value("an ordinary function is none",                         False, inspect.isgeneratorfunction, r4_film)
expect_raises("arguments are still checked at the call",             r5_numbers, "a")
expect_raises("... also for the async one",                          r5_stream, "a")
expect_exact("it yields what it yielded, defaults converted",        [5, 6.0], lambda: list(r5_numbers()))
expect_exact("... again, through the compiled wrapper",              [1, 3.0], lambda: list(r5_numbers(1, 2)))
expect_value("still a generator function once compiled",             True, inspect.isgeneratorfunction, r5_numbers)
expect_exact("a generator method",                                   [0, 1], lambda: list(R5Feed().items(2)))


def r5_logged(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)
    return wrapper

@typecheck
@r5_logged
def r5_scaled(x: int, factor: float = 2, *, bias: complex = 1) -> Any:
    return factor, bias

def r5_scale(x: float = 2) -> Any:
    return x

r5_checked_scale = typecheck(r5_scale)
r5_strict_scale = typecheck(r5_scale, convert = False)

class R5Scaler:
    def __call__(self, x: int, scale: float = 2) -> Any:
        return scale

section("phase 7 · review 5: converted defaults, and the function they belong to")
expect_exact("under a functools.wraps decorator the default is converted", (2.0, (1+0j)), r5_scaled, 1)
expect_exact("... on the second call too",                           (2.0, (1+0j)), r5_scaled, 1)
expect_exact("... and with the other one given",                     (2.0, (3+0j)), r5_scaled, 1, bias = 3)
expect_value("for a callable object",                                2.0, typecheck(R5Scaler()), 1)
expect_exact("for an argument a partial fixes by keyword",           (3.0, (1+0j)), typecheck(functools.partial(r5_scaled.__wrapped__, factor = 3)), 1)
expect_value("the checked function receives the converted default",  2.0, r5_checked_scale)
expect_value("the function it was given keeps its own",              2, r5_scale)
expect_value("... in its __defaults__ as well",                      (2,), lambda: r5_scale.__defaults__)
expect_message("a second wrapper without conversion still objects",  ("1 problem found in definition",), r5_strict_scale)
expect_value("... and the first one still converts",                 2.0, r5_checked_scale)


class R5Level(enum.IntEnum):
    OFF = 0
    ON = 1

@typecheck(coerce = True)
def r5_level(level: R5Level) -> Any: return level

@typecheck
def r5_number_first(x: float | Port) -> Any: return x

@typecheck
def r5_model_first(x: Port | float) -> Any: return x

@typecheck
def r5_starts_with_a(s: Annotated[str, lambda s: s[0] == "a"]) -> Any: return s

@typecheck
def r5_finite(x: Number) -> Any: return x

section("phase 7 · review 5: conversion corners")
expect_value("coerce: a number becomes the enum member",             R5Level.ON, r5_level, 1)
expect_raises("... a bool does not (True == 1)",                     r5_level, True)
expect_value("float | Port: the float comes first",                  80.0, r5_number_first, 80)
expect_value("Port | float: the model comes first",                  Port(80), r5_model_first, 80)
expect_value("... and the float takes what is no port",              70000.0, r5_model_first, 70000)
expect_message("a check that raises IndexError rejects the value",   ("invalid 'str': string index out of range",), r5_starts_with_a, "")
expect_ok("... and accepts a good one",                              r5_starts_with_a, "abc")
expect_value("Number: an int is converted",                          2.0, r5_finite, 2)
expect_raises("Number: nan is no number to calculate with",          r5_finite, float("nan"))
expect_value("a Port carries no __dict__",                           False, lambda: hasattr(Port(80), "__dict__"))


def r5_record(annotation: str, value: Any, **options: Any) -> Any:
    return typecheck_record({"object_name": "f", "record": {"x": annotation}, "args": (value,), **options})[0][0]

section("phase 7 · review 5: what a string in a record may name")
expect_value("Optional[int]: None",                                  None, r5_record, "Optional[int]", None)
expect_raises("Optional[int]: a str",                                r5_record, "Optional[int]", "x")
expect_message("Literal['a', 'b']",                                  ("expected type: Literal['a', 'b'], got type 'str'",), r5_record, "Literal['a', 'b']", "c")
expect_paths("Sequence[int], items with deep",                       ["x[1]"], r5_record, "Sequence[int]", [1, "a"], deep = True)
expect_ok("typing.Optional[int], written with its module",           r5_record, "typing.Optional[int]", 1)
expect_ok("collections.abc.Mapping[str, int]",                       r5_record, "collections.abc.Mapping[str, int]", {"a": 1})
expect_value("date, coerced from text",                              datetime.date(2026, 1, 2), r5_record, "date", "2026-01-02", coerce = True)
expect_raises("Decimal | None: a float",                             r5_record, "Decimal | None", 1.5)
for _text in ("os.system", "typing.cast", "builtins.eval", "Optional.__class__", "datetime.sys", "Literal[print]", "Path.home()"):
    expect_message(f"still refused: {_text}",                        ("Cannot resolve annotation",), r5_record, _text, 1)


@typecheck
def r5_top(x: int, mode: Literal["r", "w"] = "r") -> Any: return x

def r5_error(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> InvalidDataError:
    try:
        fn(*args, **kwargs)
    except InvalidDataError as e:
        return e
    raise AssertionError("no InvalidDataError")

_r5_sent = r5_error(r5_top, "a", "x")
_r5_received = pickle.loads(pickle.dumps(_r5_sent))

section("phase 7 · review 5: an error that crosses a process boundary")
expect_value("the message arrives",                                  True, lambda: str(_r5_received) == str(_r5_sent))
expect_value("... and the problems, as data",                        [("type", "x", int, "a"), ("type", "mode", str, "x")],
             lambda: [(p.kind, p.parameter, p.expected, p.value) for p in _r5_received.problems])
expect_value("... with the annotation",                              True, lambda: _r5_received.problems[1].annotation == Literal["r", "w"])
expect_value("... and the function, found again by name",            True, lambda: _r5_received.problems[0].origin is r5_top.__wrapped__)
expect_value("the context too",                                      "field assignment",
             lambda: pickle.loads(pickle.dumps(r5_error(setattr, R4Config(), "kind", str))).context)
expect_value("a value that can't be pickled is replaced, the error still arrives", "Unpickled",
             lambda: type(pickle.loads(pickle.dumps(r5_error(r5_top, threading.Lock()))).problems[0].value).__name__)
expect_value("copy.deepcopy keeps the problems",                     2, lambda: len(copy.deepcopy(_r5_sent).problems))


class R5Movie(TypedDict, total = False):
    title: Required[str]
    year: int

def r5_film(**kwargs: Unpack[R5Movie]) -> Any: return kwargs

R5Odd = TypedDict("R5Odd", {"my-key": int, "ok": Required[int]}, total = False)

@typecheck
def r5_odd(**options: Unpack[R5Odd]) -> Any: return options             # type: ignore[valid-type]

@typecheck
def r5_point(speed: float, *point: *tuple[int, str]) -> Any: return point

@typecheck
def r5_run(tag: str, *rest: *tuple[int, *tuple[str, ...], float]) -> Any: return rest

@typecheck
def r5_positional(a: int = 1, b: int = 2, /) -> Any: return a, b

@enforce(check_return = True, deep = True)
class R5Node:
    def parent(self, of: Self | None = None) -> Self | None: return of
    def all(self, others: list[Self]) -> list[Self]: return others
    @classmethod
    def kind(cls) -> type[Self]: return cls

_r5_node = R5Node()
_r5_spec = {"object_name": r5_film, "record": {"kwargs": float}, "kwargs": {"a": 1}}

section("phase 7 · review 5: annotations that were checked loosely or not at all")
expect_ok("Self | None: an instance",                                _r5_node.parent, _r5_node)
expect_ok("Self | None: None",                                       _r5_node.parent)
expect_message("Self | None: anything else",                         ("expected type: 'R5Node' | 'NoneType', got type 'int'",), _r5_node.parent, 5)
expect_paths("list[Self], with deep",                                ["others[1]"], _r5_node.all, [_r5_node, 5])
expect_value("type[Self]",                                           R5Node, R5Node.kind)
expect_exact("a record of its own sees **kwargs as written",         ((), {"a": 1.0}), typecheck_record, _r5_spec)
expect_ok("the decorated function is called",                        typecheck(r5_film), title = "Up")
expect_exact("... and the record still sees **kwargs",               ((), {"a": 1.0}), typecheck_record, _r5_spec)
expect_message("a TypedDict key that is no identifier is checked",   ("For parameter my-key of <Function r5_odd>: expected type: 'int', got type 'str'",),
               lambda: r5_odd(**{"my-key": "x", "ok": 1}))
expect_ok("... and accepted when it is right",                       lambda: r5_odd(**{"my-key": 1, "ok": 1}))
expect_ok("*args as a tuple",                                        r5_point, 1.0, 2, "n")
expect_value("... gets the compiled wrapper",                        True, lambda: "__enforced_source__" in vars(r5_point))
expect_message("... and still counts",                               ("with 2 items, got 3 items",), r5_point, 1.0, 2, "n", 3)
expect_exact("*args with a run of unknown length",                   (1, "a", "b", 2.5), r5_run, "t", 1, "a", "b", 2.5)
expect_paths("... a wrong one in the run",                           ["rest[2]"], r5_run, "t", 1, "a", 2, 2.5)
expect_message("... too few",                                        ("with at least 2 items, got 1 item (",), r5_run, "t", 1)
expect_message("a positional-only parameter passed by keyword",      ("got some positional-only arguments passed as keyword arguments: 'b'",), r5_positional, b = 2)
expect_value("an unannotated method of an enforced class stays plain", False, lambda: hasattr(vars(R5Feed)["plain"], "__wrapped__"))
expect_value("... an annotated one is checked",                      True, lambda: hasattr(vars(R5Feed)["typed"], "__wrapped__"))
expect_raises("... a call it can't take is Python's own error",      R5Feed().plain, exc = TypeError)


@typing_no_type_check
@typecheck
def r5_unchecked_above(x: int) -> Any: return x

@typing_no_type_check
def r5_marked(x: int) -> Any: return x

class R5Conversion:
    def __init__(self, *, default: Any) -> None: self._default = default
    def __set_name__(self, owner: type, name: str) -> None: self._name = "_" + name
    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        return self._default if obj is None else getattr(obj, self._name, self._default)
    def __set__(self, obj: Any, value: Any) -> None: setattr(obj, self._name, int(value))

@dataclass
class R5Item:
    name: str
    quantity: R5Conversion = R5Conversion(default = 100)

class R5Text(IO[str]):
    pass

@typecheck
def r5_binary(f: BinaryIO) -> Any: return f

@typecheck
def r5_text(f: TextIO) -> Any: return f

_r5_big = [object()] * 200_000

section("phase 7 · review 5: smaller gaps")
expect_value("@no_type_check above @typecheck: not checked",         "a", r5_unchecked_above, "a")
expect_value("@no_type_check below: the function is returned as it is", True, lambda: typecheck(r5_marked) is r5_marked)
expect_value("a descriptor field reads its default from the descriptor", 100, lambda: R5Item("pen").quantity)
expect_value("... and its values go through the descriptor",         5, lambda: R5Item("pen", "5").quantity)
expect_raises("... the other fields are checked as ever",            R5Item, 5)
expect_raises("a subclass of IO[str] is no binary file",             r5_binary, R5Text())
expect_ok("... it is a text file",                                   r5_text, R5Text())
expect_value("a huge value is not formatted in full for a message",  True,
             lambda: (lambda t0: (str(r5_error(r5_top, _r5_big)), time.perf_counter() - t0)[1] < 0.02)(time.perf_counter()))
expect_value("a long annotation is cut in a message",                True,
             lambda: len(_plain(r5_error(r5_long, 5))) < 220)
expect_message("a callable with a broken __signature__ is reported", ("Cannot read the signature of <Callable R5Broken>",), typecheck(R5Broken()), 1)
expect_message("a default of a field that __init__ doesn't take is called a field", ("For default value of field retries of <Dataclass R5Job>",), R5Job, "build")
expect_message("a field message has the colon too",                  ("Field R4Config.kind of <Dataclass R4Config>: expected type: 'type[int]'",), setattr, R4Config(), "kind", str)


def r5_area(width: float, height: float = 1, *, unit: str = "m") -> float:
    return width * height

class R5Account:
    def __init__(self, owner: str, balance: float = 0) -> None:
        self.owner, self.balance = owner, balance
    def deposit(self, amount: float) -> str:
        self.balance += amount
        return self.balance                                         # type: ignore[return-value]
    def plain(self, a):
        return a

_r5_account = R5Account("ana")

class R5Count(TypeModel[int]):
    pass

section("phase 7 · review 5: the decorators without the decorator")
expect_value("typecheck_function: checked, converted and called",    12.0, typecheck_function, r5_area, (3, 4))
expect_value("... a default is converted on the way",                3.0, typecheck_function, r5_area, (3,))
expect_value("... with keywords",                                    6.0, typecheck_function, r5_area, [3], {"height": 2})
expect_value("... the function itself keeps its default",            (1,), lambda: r5_area.__defaults__)
expect_message("... a wrong argument",                               ("For parameter width of <Function r5_area>: expected type: 'float', got type 'str'",), typecheck_function, r5_area, ("3",))
expect_message("... a missing one",                                  ("Missing required argument for <Function r5_area>: width",), typecheck_function, r5_area)
expect_value("... with coerce",                                      12.0, typecheck_function, r5_area, ("3", "4"), coerce = True)
expect_value("... a bound method, without self",                     5.0, typecheck_function, _r5_account.deposit, (5,))
expect_message("... labelled as a method",                           ("For parameter amount of <Method R5Account.deposit>",), typecheck_function, _r5_account.deposit, ("x",))
expect_message("... with check_return",                              ("For return value of <Method R5Account.deposit>",), typecheck_function, _r5_account.deposit, (5,), check_return = True)
expect_message("... a class is sent to enforce_class",               ("typecheck_function cannot check <Class R5Account>", "enforce_class"), typecheck_function, R5Account, ("a",))
expect_message("... a string is no list of arguments",               ("'args' must be a tuple or a list",), typecheck_function, r5_area, "ab")
expect_value("before enforce_class nothing is checked",              5, lambda: R5Account(5).owner)
expect_value("enforce_class returns the class it was given",         True, lambda: enforce_class(R5Account, check_return = True) is R5Account)
expect_message("... its __init__ is checked from then on",           ("For parameter owner of <Class R5Account>",), R5Account, 5)
expect_value("... defaults are converted",                           0.0, lambda: R5Account("a").balance)
expect_message("... its methods too, with the options given",        ("For return value of <Method R5Account.deposit>",), R5Account("a").deposit, 1)
expect_value("... a method without annotations stays plain",         "x", R5Account("a").plain, "x")
expect_message("... a function is sent to typecheck_function",       ("enforce_class cannot check <Function r5_area>", "typecheck_function"), enforce_class, r5_area)
expect_message("... a dataclass is refused, as by enforced",         ("A dataclass is checked by enforced.dataclass",), enforce_class, R4Config)
expect_value("a TypeModel class carries no __dict__ unasked",        False, lambda: hasattr(R5Count(1), "__dict__"))


# ── review 6: what was open after it (2, 15, 17, 21, 28, 33, 34, 35) ─────────────────────

def _r6_dropped(call: Callable[[Any], Any]) -> int:
    """How many of 20 functions, each made, handed to ``call`` and dropped, are still alive afterwards."""
    import gc
    import weakref
    alive = []
    for _ in range(20):
        def made(x: float) -> float:
            return x
        call(made)
        alive.append(weakref.ref(made))
        del made
    gc.collect()
    return sum(ref() is not None for ref in alive)

section("phase 7 · review 6: nothing outlives a function that was only called")
expect_value("typecheck_function: a function goes when it is dropped", 0, _r6_dropped, lambda fn: typecheck_function(fn, (1,)))
expect_value("typecheck_record: the same, for a callable target",  0, _r6_dropped,
             lambda fn: typecheck_record({"object_name": fn, "record": {"x": float}, "args": (1,)}))
expect_value("... and a second call still finds the compiled check", True,
             lambda: (typecheck_function(r5_area, (3, 4)), "__enforced_source__" in vars(next(iter(vars(r5_area)["__enforced_calls__"][1].values()))))[1])


import enforced._typechecker._codegen as _codegen
from unittest import mock as _r6_mock                           # noqa: E402

@typing_no_type_check
@dataclasses.dataclass
class R6Loose:
    x: int

@dataclass
class R6Checked(R6Loose):
    y: int = 0

@typing_no_type_check
class R6LooseBase:
    def inherited(self, x: int) -> Any: return x

@enforce
class R6Enforced(R6LooseBase):
    def own(self, x: int) -> Any: return x

class R6Pipe:
    """Every method of a file except the two that ``with`` needs."""
    encoding = "utf-8"
    def read(self, size: int = -1) -> str: return ""
    def readline(self, size: int = -1) -> str: return ""
    def readlines(self, hint: int = -1) -> list[str]: return []
    def write(self, text: str) -> int: return len(text)
    def writelines(self, lines: Any) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
    def seek(self, offset: int, whence: int = 0) -> int: return 0
    def tell(self) -> int: return 0
    def truncate(self, size: Any = None) -> int: return 0
    def fileno(self) -> int: return -1
    def isatty(self) -> bool: return False
    def readable(self) -> bool: return True
    def writable(self) -> bool: return True
    def seekable(self) -> bool: return False

@typecheck
def r6_text_class(kind: type[TextIO]) -> Any: return kind

@typecheck
def r6_binary_class(kind: type[BinaryIO]) -> Any: return kind

@typecheck(allow_subclass = False)
def r6_text_class_strict(kind: type[TextIO]) -> Any: return kind

@typecheck
def r6_marked(n: Annotated[int, Check(lambda v: v > 0)], word: Annotated[str, str.strip] = "a") -> Any: return n

def r6_coloured(fn: Callable[..., Any], *args: Any) -> str:
    """The message of the error ``fn(*args)`` raises, rendered with colours switched on."""
    error = r5_error(fn, *args)
    kept = {name: os.environ.pop(name, None) for name in ("ENFORCED_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED", "FORCE_COLOR")}
    os.environ["FORCE_COLOR"] = "1"
    try:
        return str(error)
    finally:
        del os.environ["FORCE_COLOR"]
        os.environ.update({name: value for name, value in kept.items() if value is not None})

def _r6_third_party() -> list[str]:
    """The modules a fresh interpreter has loaded for enforced that are neither its own nor the standard library's."""
    import subprocess
    code = ("import sys; before = set(sys.modules); import enforced, enforced.data_types\n"
            "new = {name.split('.')[0] for name in set(sys.modules) - before}\n"
            "print(sorted(new - set(sys.stdlib_module_names) - {'enforced'}))")
    return eval(subprocess.run([sys.executable, "-c", code], capture_output = True, text = True).stdout or "['?']")

@typecheck
def r6_three(x: int, y: str, z: float) -> None: ...

section("phase 7 · review 6: no_type_check, files, colours, checks, the generator flag")
expect_raises("a dataclass below a class marked no_type_check checks its own fields", R6Checked, 1, "b")
expect_value("... what the marked base annotated is no type hint",   "anything", lambda: R6Checked("anything", 2).x)
expect_value("... the marked base itself stays unchecked",           "a", lambda: R6Loose("a").x)
expect_raises("an enforced class below a marked one: the same rule", R6Enforced().own, "a")
expect_value("... the method it inherits is the base's, unchecked",  "a", R6Enforced().inherited, "a")
expect_ok("a Mock() stands for a file",                              r5_text, _r6_mock.Mock())
expect_ok("... for a binary one too",                                r5_binary, _r6_mock.Mock())
expect_raises("... a mock of something else does not",               r5_text, _r6_mock.Mock(spec = dict))
expect_ok("a file-like object needs no with support",                r5_text, R6Pipe())
expect_raises("... it has an encoding: no binary file",              r5_binary, R6Pipe())
expect_value("type[TextIO]: a class that defines a file's methods",  R6Pipe, r6_text_class, R6Pipe)
expect_value("... a class derived from IO[str]",                     R5Text, r6_text_class, R5Text)
expect_raises("... which is no class of binary files",               r6_binary_class, R5Text)
expect_raises("... the class says it holds text",                    r6_binary_class, R6Pipe)
expect_raises("... a class that is no file class",                   r6_text_class, dict)
expect_value("... in strict mode an io class is one too",            io.StringIO, r6_text_class_strict, io.StringIO)
expect_raises("... and a binary one is not",                         r6_text_class_strict, io.BytesIO)
expect_value("a coloured message is the plain one with escape sequences", True,
             lambda: _ANSI.sub("", r6_coloured(r6_three, "a", 1, "b")) == _plain(r5_error(r6_three, "a", 1, "b")) != r6_coloured(r6_three, "a", 1, "b"))
expect_value("no dependency: nothing is imported but the standard library", [], _r6_third_party)
expect_raises("... and a style the messages don't use is refused by name", lambda: __import__("enforced._formatting_tool")._formatting_tool._escapes("on_red"), exc = ValueError)
expect_value("Check(fn): the check passes",                          5, r6_marked, 5)
expect_message("... and fails, like the short form",                 ("For parameter n of <Function r6_marked>: invalid 'int': failed check v > 0 (Value: 0)",), r6_marked, 0)
expect_message("a function that transforms shows what it returned",  ("invalid 'str': failed check strip, which returned '' (Value: '  ')",), r6_marked, 1, "  ")
expect_value("... and never changes the value",                      1, r6_marked, 1, " a ")
expect_raises("Check refuses what is no function",                   Check, 5, exc = TypeError)
expect_value("the generator flag was tried on this Python",          True, lambda: _codegen._runs_at_once(inspect.CO_GENERATOR) and bool(_codegen._FLAGGED))
expect_value("... a Python that made a generator of such code would be noticed", False,
             _codegen._runs_at_once, inspect.CO_GENERATOR, "def _pv_wrapper(*_pv_a, **_pv_k):\n    yield _pv_fn\n")


@enforce(check_return = True)
class R6Base:
    def clone(self) -> Self:
        return R6Base()                                             # type: ignore[return-value]
    def same(self) -> Self:
        return self
    def fresh(self) -> Self:
        return type(self)()
    def merge(self, other: Self, *more: Self) -> Any:
        return other
    def maybe(self, other: Self | None = None, kind: type[Self] | None = None) -> Self | None:
        return other
    @classmethod
    def make(cls, like: Self | None = None) -> Self:
        return cls()
    @classmethod
    def wrong(cls) -> Self:
        return R6Base()                                             # type: ignore[return-value]

class R6Child(R6Base):
    pass

class R6Grandchild(R6Child):
    pass

@enforce(check_return = True, allow_subclass = False, deep = True)
class R6Strict:
    def pair(self, others: list[Self]) -> tuple[Self, int]:
        return self, len(others)

class R6StrictChild(R6Strict):
    pass

@dataclass
class R6Node:
    parent: Self | None = None

class R6Leaf(R6Node):                                               # a plain subclass: not decorated
    pass

_r6_base, _r6_child, _r6_grand = R6Base(), R6Child(), R6Grandchild()

section("phase 7 · review 6: Self is the class of the instance the method is called on")
expect_raises("-> Self: a Base returned from a call on a Child",     _r6_child.clone)
expect_value("... the same method on a Base returns a Base",         R6Base, lambda: type(_r6_base.clone()))
expect_value("... return self is right for every class",             True, lambda: all(o.same() is o for o in (_r6_base, _r6_child, _r6_grand)))
expect_value("... and so is type(self)()",                           R6Grandchild, lambda: type(_r6_grand.fresh()))
expect_message("... the message names the class Self is in that call", ("For return value of <Method R6Base.clone>: expected type: '__main__.R6Child', got type '__main__.R6Base'",), _r6_child.clone)
expect_value("other: Self takes an instance of the same class",      True, lambda: _r6_child.merge(_r6_child) is _r6_child)
expect_value("... and of a subclass of it",                          True, lambda: _r6_child.merge(_r6_grand, _r6_child) is _r6_grand)
expect_raises("... not of the base class",                           _r6_child.merge, _r6_base)
expect_raises("... also among *args",                                _r6_child.merge, _r6_child, _r6_base)
expect_ok("... which a Base takes",                                  _r6_base.merge, _r6_child, _r6_base)
expect_raises("Self | None: the base is no Child",                   _r6_child.maybe, _r6_base)
expect_value("... None is",                                          None, _r6_child.maybe)
expect_raises("type[Self]: the base class is no class of a Child",   _r6_child.maybe, None, R6Base)
expect_ok("... a subclass of it is",                                 _r6_child.maybe, None, R6Grandchild)
expect_value("a class method: Self is the class it is called on",    R6Child, lambda: type(R6Child.make()))
expect_raises("... for what it takes",                               R6Child.make, _r6_base)
expect_raises("... and for what it returns",                         R6Child.wrong)
expect_value("... on the class that defines it, as before",          R6Base, lambda: type(R6Base.wrong()))
expect_value("... called through an instance",                       R6Grandchild, lambda: type(_r6_grand.make(_r6_grand)))
expect_value("called a second time, the compiled check answers",     True, lambda: (_r6_child.merge(_r6_child), _r6_child.merge(_r6_child))[1] is _r6_child)
expect_raises("... and still rejects",                               _r6_child.merge, _r6_base)
expect_value("an unbound call finds the class in its first argument", True, lambda: R6Base.merge(_r6_child, _r6_child) is _r6_child)
expect_raises("... and checks against it",                           R6Base.merge, _r6_child, _r6_base)
expect_value("strict and deep: exactly the class of the instance",   2, lambda: R6StrictChild().pair([R6StrictChild(), R6StrictChild()])[1])
expect_paths("... an instance of the base class, inside a list",     ["others[1]"], R6StrictChild().pair, [R6StrictChild(), R6Strict()])
expect_raises("... and of a subclass, in strict mode",               R6Strict().pair, [R6StrictChild()])
expect_raises("a dataclass field: Self in a subclass that isn't decorated", R6Leaf, R6Node())
expect_value("... takes its own kind",                               True, lambda: (lambda leaf: R6Leaf(leaf).parent is leaf)(R6Leaf()))
expect_raises("... on assignment too",                               setattr, R6Leaf(), "parent", R6Node())
expect_ok("... the decorated class itself takes a subclass instance", R6Node, R6Leaf())


# ── review 7: 21, 23, 31, 36, 40 ─────────────────────────────────────────────────────────

class R7Proxy:
    """Passes every name on to the file inside: its class defines no method of a file."""
    def __init__(self, inside: Any) -> None:
        self._inside = inside
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inside, name)

@typecheck
def r7_two(a: int, b: int = 0) -> Any: return a

@enforce
class R7Base:
    def maybe(self, other: Self | None = None) -> Any: return other

@dataclass
class R7Node:
    parent: Self | None = None

def _r7_late() -> Any:
    """A checked function, a dataclass and an enforced class whose annotations name a class written below them."""
    @typecheck
    def f(x: "R7Later") -> Any: return x
    @dataclass
    class Tree:
        root: "R7Later | None" = None
    @enforce
    class Box:
        def put(self, item: "R7Later") -> Any: return item
    class R7Later: ...
    return f, Tree, Box, R7Later

_r7_f, _R7Tree, _R7Box, _R7Later = _r7_late()                 # _r7_late has returned: its names are gone

def _r7_alive(use: Callable[[int], type], count: int = 30) -> int:
    """How many of ``count`` classes, each made by ``use`` and dropped, are alive afterwards."""
    import gc
    import weakref
    alive = []
    for i in range(count):
        made = use(i)
        alive.append(weakref.ref(made))
        del made
    for _ in range(3):
        gc.collect()
    return sum(ref() is not None for ref in alive)

def _r7_method_class(i: int) -> type:
    made = type(f"R7Sub{i}", (R7Base,), {})
    one = made()
    one.maybe(one)
    return made

def _r7_field_class(i: int) -> type:
    made = type(f"R7Leaf{i}", (R7Node,), {})
    made(made()).parent = made()
    return made

def _r7_local_class(i: int) -> type:
    class Local: ...
    @typecheck(deep = True)
    def f(x: Local, xs: list[Local] | None = None) -> Any: return x
    f(Local(), [Local()])
    return Local

def _r7_asked(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
    """How often it is asked whether messages are coloured while the call is made and its error caught."""
    import enforced._formatting_tool as tool
    real, asked = tool.colours_on, []
    tool.colours_on = lambda: asked.append(1) or real()        # type: ignore[assignment]
    try:
        fn(*args, **kwargs)
    except InvalidDataError:
        pass
    finally:
        tool.colours_on = real
    return len(asked)

section("phase 7 · review 7: what was still open")
expect_value("type[TextIO]: the class of a wrapper around a file",   True, lambda: r6_text_class(type(tempfile.NamedTemporaryFile())) is not None)
expect_value("... a proxy class that passes every name on",          R7Proxy, r6_binary_class, R7Proxy)
expect_raises("... a class that is nothing of the kind",             r6_text_class, dict)
expect_ok("... and an instance of the proxy is a file",              r5_text, R7Proxy(io.StringIO()))
expect_value("a later local name, after its function has returned",  True, lambda: isinstance(_r7_f(_R7Later()), _R7Later))
expect_raises("... is checked against",                              _r7_f, 5)
expect_value("... as a dataclass field",                             True, lambda: isinstance(_R7Tree(_R7Later()).root, _R7Later))
expect_raises("... rejected there too",                              _R7Tree, 5)
expect_raises("... and in a method of an enforced class",            _R7Box().put, 5)
expect_value("a class made at run time and used with Self goes",     0, _r7_alive, _r7_method_class)
expect_value("... a subclass of a dataclass with a Self field",      0, _r7_alive, _r7_field_class)
expect_value("... a local class in a plain annotation, with deep",   0, _r7_alive, _r7_local_class)
expect_message("too many arguments, in Python's words",              ("too many positional arguments",), r7_two, 1, 2, 3)
expect_message("a name given twice",                                 ("multiple values for argument 'a'",), r7_two, 1, a = 2)
expect_message("an unknown keyword",                                 ("got an unexpected keyword argument 'c'",), r7_two, 1, c = 3)
expect_value("... raised and caught without a message being built",  0, _r7_asked, r7_two, 1, c = 3)
expect_message("a missing argument is explained as before",          ("Missing required argument for <Function r7_two>: a",), r7_two)


@enforce(check_return = True)
class R8Account:
    def __init__(self) -> None:
        self._balance: Any = 0.0
    @property
    def balance(self) -> float:
        return self._balance
    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = value
    @functools.cached_property
    def label(self) -> str:
        return self._balance                                        # type: ignore[return-value]
    @property
    @enforce.exempt
    def raw(self) -> int:
        return self._balance                                        # type: ignore[return-value]

@enforce
class R8Quiet:
    @property
    def size(self) -> int:
        return "big"                                                # type: ignore[return-value]

def _r8_set(obj: Any, name: str, value: Any) -> Any:
    setattr(obj, name, value)
    return getattr(obj, name)

section("phase 7 · review 8: properties of an enforced class")
expect_value("a property: what is assigned is checked and converted", 3.0, _r8_set, R8Account(), "balance", 3)
expect_message("... a wrong value, in the words of a method",        ("For parameter value of <Method R8Account.balance>: expected type: 'float', got type 'str'",), _r8_set, R8Account(), "balance", "a lot")
expect_message("... what the getter returns, with check_return",     ("For return value of <Method R8Account.balance>",), lambda: (lambda a: (setattr(a, "_balance", "x"), a.balance))(R8Account()))
expect_message("... a cached_property too",                          ("For return value of <Method R8Account.label>",), lambda: R8Account().label)
expect_value("... one marked enforce.exempt is left alone",          0.0, lambda: R8Account().raw)
expect_value("... without check_return a getter is not wrapped",     "big", lambda: R8Quiet().size)
expect_value("... and is still a property, with its accessors",      True, lambda: type(vars(R8Account)["balance"]) is property and vars(R8Account)["label"].attrname == "label")


def _r8_switched_off(value: str | None) -> str:
    """What a small program prints in an interpreter of its own, with ENFORCED_TYPECHECK_OFF set to ``value``."""
    import subprocess
    from enforced._environment import EnvVar
    program = (
        "from enforced import *\n"
        "@typecheck\n"
        "def f(x: int): return x\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
        "@enforce\n"
        "class C:\n"
        "    def m(self, x: int): return x\n"
        "try:\n"
        "    print(f('a'), P('b').x, C().m('c'), typecheck_function(f, ('d',)), hasattr(f, '__wrapped__'))\n"
        "except InvalidDataError:\n"
        "    print('rejected')\n")
    env = {k: v for k, v in os.environ.items() if k != EnvVar.TYPECHECK_OFF}
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if value is not None:
        env[EnvVar.TYPECHECK_OFF] = value
    return subprocess.run([sys.executable, "-c", program], capture_output = True, text = True, env = env).stdout.strip()

section("phase 7 · review 8: ENFORCED_TYPECHECK_OFF and the variables in one enum")
expect_value("ENFORCED_TYPECHECK_OFF=1: every API hands back what it got", "a b c d False", _r8_switched_off, "1")
expect_value("... unset, the same program is checked",               "rejected", _r8_switched_off, None)
expect_value("... and with any value but 1",                         "rejected", _r8_switched_off, "0")
expect_value("every variable enforced reads is a member of EnvVar",  True,
             lambda: (lambda E: [m.value for m in E] == ["ENFORCED_TYPECHECK_OFF", "ENFORCED_COMPILE_AFTER", "ENFORCED_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED", "FORCE_COLOR", "TERM"])(__import__("enforced._environment", fromlist = ["EnvVar"]).EnvVar))


def _r9_tier(after: int, calls: int) -> bool:
    """Whether a function is compiled after ``calls`` calls when wrappers are compiled after ``after``."""
    kept, _environment.COMPILE_AFTER = _environment.COMPILE_AFTER, after
    try:
        @typecheck
        def f(x: float) -> Any: return x
    finally:
        _environment.COMPILE_AFTER = kept
    for n in range(calls):
        f(n)
    return "__enforced_source__" in vars(f)

def _r9_general_path() -> Any:
    """A function, a class and a dataclass that stay on the general path, used like any other."""
    kept, _environment.COMPILE_AFTER = _environment.COMPILE_AFTER, 10 ** 6
    try:
        @typecheck(check_return = True)
        def scale(x: float, factor: float = 2, *, label: str = "") -> float: return x * factor
        @enforce
        class Box:
            def put(self, item: int, other: Self | None = None) -> Any: return item
        @dataclass
        class Row:
            n: int
            ratio: float = 1
    finally:
        _environment.COMPILE_AFTER = kept
    return scale, Box, Row

_r9_scale, _R9Box, _R9Row = _r9_general_path()

@dataclass
class R9Order:
    qty: int
    price: float = 0
    tags: list = field(default_factory = list)
    def __post_init__(self) -> None:
        self.total = self.qty * self.price

def _r9_checked_assignments() -> list[str]:
    """The fields that reach the assignment check while one R9Order is built."""
    R9Order(1)
    seen: list[str] = []
    checking = R9Order.__setattr__
    def recording(self: Any, name: str, value: Any) -> None:
        seen.append(name)
        checking(self, name, value)
    type.__setattr__(R9Order, "__setattr__", recording)
    try:
        R9Order(2, 3)
    finally:
        type.__setattr__(R9Order, "__setattr__", checking)
    return seen

@typecheck
def r9_three(a: int, b: str, c: bytes, *, d: int = 0) -> None: ...

section("phase 7 · review 9: typecheck_record, one pass for errors, a storing __init__, tiers")
expect_value("typecheck_record: the name typecheck_from_dict has now", ((1.0,), {}), typecheck_record, {"object_name": "f", "record": {"x": float}, "args": (1,)})
expect_value("... the old name is gone",                             False, lambda: hasattr(__import__("enforced"), "typecheck_from_dict"))
expect_paths("problems in the order of the parameters, however passed", ["a", "b", "c", "d"], r9_three, d = "y", c = 3, b = 2, a = "x")
expect_message("a missing argument and a wrong one, together",       ("2 problems found in call", "Missing required arguments for <Function r9_three>: b (expecting type str), c (expecting type bytes)", "For parameter d of"), r9_three, 1, d = "y")
expect_message("a missing argument next to one that doesn't fit: the hint", ("(inferred)",), r9_three, "b", b"c")
expect_value("a dataclass argument is checked once: only the rest is assigned", ["tags", "total"], _r9_checked_assignments)
expect_value("... and stored as converted",                          3.0, lambda: R9Order(2, 3).price)
expect_raises("... a wrong one is still refused",                    R9Order, "2")
expect_raises("... and so is a wrong assignment",                    setattr, R9Order(1), "qty", "x")
expect_value("a wrapper is compiled at the call the setting names",  (False, True), lambda: (_r9_tier(5, 4), _r9_tier(5, 5)))
expect_value("on the general path: checked, converted, called",      6.0, _r9_scale, 3)
expect_value("... with keywords",                                    8.0, _r9_scale, 2, factor = 4, label = "x")
expect_raises("... a wrong argument",                                _r9_scale, "a")
expect_raises("... a wrong keyword",                                 _r9_scale, 1, label = 5)
expect_raises("... a method, with Self",                             _R9Box().put, 1, 5)
expect_value("... a dataclass",                                      2.0, lambda: _R9Row(1, 2).ratio)
expect_raises("... refused there too",                               _R9Row, "a")
expect_value("... none of them was compiled",                        False, lambda: "__enforced_source__" in vars(_r9_scale))


section("phase 7 · review 9, added: errors made late and freed at once, a dataclass in two tiers")

class R10Word(TypeModel[str]):
    runs: list = []
    @classmethod
    def validate(cls, raw: str) -> str:
        cls.runs.append(raw)
        if not raw.isalpha():
            raise ValueError("letters only")
        return raw

@typecheck(check_return = True)
def r10_f(a: int, b: str = "", *, small: Annotated[int, lambda v: v < 10] = 1, word: R10Word = "a") -> int:     # type: ignore[assignment]
    return "text" if a == 0 else a                      # type: ignore[return-value]

def _r10_error(*args: Any, **kwargs: Any) -> InvalidDataError:
    try:
        r10_f(*args, **kwargs)
    except InvalidDataError as e:
        return e
    raise AssertionError("no error")

def _r10_left_to_the_collector() -> int:
    """How many objects 50 wrong calls of every kind leave for the garbage collector."""
    import gc
    point = _R10Point(1)
    calls = [lambda: r10_f("x"), lambda: r10_f(), lambda: r10_f(1, 2), lambda: r10_f(1, small = 50), lambda: r10_f(1, word = "1"),
             lambda: r10_f(0), lambda: r10_f(1, nothing = 1), lambda: _R10Point("a"), lambda: setattr(point, "y", "a")]
    def caught(call: Any) -> None:
        try:
            call()
        except InvalidDataError as e:
            str(e)
    for call in calls:
        for _ in range(70):                             # past the call at which a wrapper is compiled
            caught(call)
    for _ in range(3):
        gc.collect()
    gc.disable()
    try:
        for _ in range(50):
            for call in calls:
                caught(call)
        return gc.collect()
    finally:
        gc.enable()

def _r10_validate_runs() -> int:
    r10_f(1, word = "ok")
    R10Word.runs.clear()
    _r10_error(1, word = "1")
    return len(R10Word.runs)

def _r10_dataclass(after: int) -> Any:
    kept, _environment.COMPILE_AFTER = _environment.COMPILE_AFTER, after
    try:
        @dataclass
        class Point:
            x: int
            y: float = 0
            tags: list = field(default_factory = list)
    finally:
        _environment.COMPILE_AFTER = kept
    return Point

_R10Point = _r10_dataclass(1)
_R10Slow = _r10_dataclass(10 ** 6)

def _r10_generated(cls: Any) -> bool:
    return vars(cls)["__setattr__"].__code__.co_filename.startswith("<enforced __setattr__")

def _r10_tiers(after: int) -> tuple[bool, bool, bool, bool]:
    """(the storing __init__ before the construction the setting names, at it; the generated assignment check at first, in the end)."""
    Point = _r10_dataclass(after)
    stores = lambda: "_pv_set" in Point.__init__.__globals__["_pv_checker"].call.__code__.co_freevars
    Point(-1)
    checked = _r10_generated(Point)
    for n in range(after - 2):
        Point(n)                                        # the standard __init__ assigns: these count for the check
    before = stores()
    Point(0)
    return before, stores(), checked, _r10_generated(Point)

expect_value("the problems of a wrong call are made when they are read", (None, 2), lambda: (lambda e: (e._problems, len(e.problems)))(_r10_error("x", 2)))
expect_value("... a wrong return value too",                          [("return", "return", int, "text")], lambda: [(p.kind, p.parameter, p.expected, p.value) for p in _r10_error(0).problems])
expect_message("... with the message it always had",                 ("For return value of <Function r10_f>: expected type: 'int', got type 'str' (Value: 'text')",), r10_f, 0)
expect_message("a failed check: the reason, the short way",          ("invalid 'int': failed check v < 10 (Value: 50)",), r10_f, 1, small = 50)
expect_message("... the wrong type for it is still a wrong type",    ("For parameter small of <Function r10_f>: expected type: 'int', got type 'str' (Value: 'x')",), r10_f, 1, small = "x")
expect_message("a rejected TypeModel value: the reason",             ("invalid 'R10Word': letters only (Value: '1')",), r10_f, 1, word = "1")
expect_value("... validate runs once for a wrong call (it was 3, then 2)", 1, _r10_validate_runs)
expect_value("no wrong call leaves anything to the garbage collector", 0, _r10_left_to_the_collector)
expect_value("a pickled error still carries its problems",            ["b"], lambda: [p.parameter for p in pickle.loads(pickle.dumps(_r10_error(1, 2))).problems])
expect_value("a dataclass is compiled at the use the setting names", (False, True, False, True), _r10_tiers, 4)
expect_value("... defining it compiles nothing",                      (False, False), lambda: (lambda P: (_r10_generated(P), "_pv_set" in P.__init__.__globals__["_pv_checker"].call.__code__.co_freevars))(_r10_dataclass(1)))
expect_value("on the first tier: constructed, converted",             (2.0, []), lambda: (lambda p: (p.y, p.tags))(_R10Slow(1, 2)))
expect_value("... an assignment is converted",                        3.0, lambda: (lambda p: (setattr(p, "y", 3), p.y)[1])(_R10Slow(1)))
expect_raises("... a wrong argument is refused",                      _R10Slow, "a")
expect_message("... and a wrong assignment, in the same words",       ("1 problem found in field assignment", "Field Point.x of <Dataclass Point>: expected type: 'int', got type 'str' (Value: 'a')"), setattr, _R10Slow(1), "x", "a")
expect_message("... as on the second",                               ("1 problem found in field assignment", "Field Point.x of <Dataclass Point>: expected type: 'int', got type 'str' (Value: 'a')"), setattr, _R10Point(1), "x", "a")
expect_value("... the first tier is still what it runs on",           False, lambda: _r10_generated(_R10Slow))


section("phase 7 · review 10: on_error = 'warn'")

def _r11_warned(call: Callable[[], Any]) -> tuple[Any, list[str]]:
    """What ``call`` returned (or the error it raised), and the first problem line of each InvalidDataWarning it issued."""
    import warnings
    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("always")
        try:
            result: Any = call()
        except InvalidDataError as e:
            result = "raised: " + _plain(e).split("-> ", 1)[-1].strip()
    return result, [_plain(w.message).split("-> ", 1)[-1].strip() for w in seen if issubclass(w.category, InvalidDataWarning)]

def r11_plain(s: int) -> Any:
    return s

@typecheck(on_error = "warn", check_return = True)
def r11_scale(x: int, factor: float = 2) -> int:
    return x

@typecheck(on_error = "warn")
async def r11_fetch(url: str) -> Any:
    return url

@dataclass(on_error = "warn")
class R11Order:
    qty: int
    price: float = 0
    tags: list = field(default_factory = list)

@enforce(on_error = "warn")
class R11Box:
    def put(self, item: int) -> Any:
        return item

def _r11_once_per_line() -> int:
    """How many warnings Python shows, by its default filter, for one wrong call made 20 times from one line."""
    import warnings
    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("default")
        for _ in range(20):
            r11_scale("again")
    return len([w for w in seen if w.message.args[0].count("'again'") and "parameter" in w.message.args[0]])

def _r11_as_error() -> str:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", InvalidDataWarning)
        try:
            r11_scale("x")
        except InvalidDataWarning as w:
            return type(w).__name__ + ": " + type(w.error).__name__
    return "nothing"

_R11_X = "For parameter x of <Function r11_scale>: expected type: 'int', got type 'str' (Value: 'a')"
expect_value("a wrong argument: a warning, and the call goes ahead with it", ("a", [_R11_X, _R11_X.replace("parameter x", "return value")]), _r11_warned, lambda: r11_scale("a"))
expect_value("... what can be converted still is",                    (1, []), _r11_warned, lambda: r11_scale(1, 3))
expect_value("... a right call warns about nothing",                  (5, []), _r11_warned, lambda: r11_scale(5))
expect_value("a missing argument is raised all the same",             ("raised: Missing required argument for <Function r11_scale>: x (expecting type int)", []), _r11_warned, lambda: r11_scale())
expect_value("... and an argument too many",                          True, lambda: _r11_warned(lambda: r11_scale(1, 2, 3))[0].startswith("raised:"))
expect_value("a coroutine function",                                  (5, ["For parameter url of <Function r11_fetch>: expected type: 'str', got type 'int' (Value: 5)"]), _r11_warned, lambda: asyncio.run(r11_fetch(5)))
expect_value("a dataclass: constructed with the value as given",      ("two", ["For parameter qty of <Dataclass R11Order>: expected type: 'int', got type 'str' (Value: 'two')"]), _r11_warned, lambda: R11Order("two", 1).qty)
expect_value("... and assigned",                                      ("free", ["Field R11Order.price of <Dataclass R11Order>: expected type: 'float', got type 'str' (Value: 'free')"]), _r11_warned, lambda: (lambda o: (setattr(o, "price", "free"), o.price)[1])(R11Order(1)))
expect_value("... a convertible assignment is converted, silently",   (3.0, []), _r11_warned, lambda: (lambda o: (setattr(o, "price", 3), o.price)[1])(R11Order(1)))
expect_value("a class under enforce",                                 ("a", ["For parameter item of <Method R11Box.put>: expected type: 'int', got type 'str' (Value: 'a')"]), _r11_warned, lambda: R11Box().put("a"))
expect_value("typecheck_function",                                    ("a", ["For parameter s of <Function r11_plain>: expected type: 'int', got type 'str' (Value: 'a')"]), _r11_warned, lambda: typecheck_function(r11_plain, ("a",), on_error = "warn"))
expect_raises("... the same function without the option still raises", typecheck_function, r11_plain, ("a",))
expect_value("typecheck_record: the arguments, as they are",          ((("a",), {}), ["For parameter n of <Function r11>: expected type: 'int', got type 'str' (Value: 'a')"]), _r11_warned, lambda: typecheck_record({"object_name": "r11", "record": {"n": "int"}, "args": ("a",), "on_error": "warn"}))
expect_value("Python shows one warning per line by default",          1, _r11_once_per_line)
expect_value("the filters turn it back into an exception, with the error on it", "InvalidDataWarning: InvalidDataError", _r11_as_error)
expect_raises("any other value of the option is refused",             lambda: typecheck(on_error = "log"))
expect_raises("... by the dataclass too",                             lambda: dataclass(on_error = "log"))
expect_value("the default is to raise",                               True, lambda: all(inspect.signature(api).parameters["on_error"].default == "raise" for api in (typecheck, enforce, dataclass, typecheck_function, enforce_class)))


section("phase 7 · the methods of a dataclass (check_methods)")

def _r12_fallback(value: int) -> int:
    return value

@dataclass(check_return = True)
class R12Invoice:
    qty: int = 1
    price: float = 2.0
    on_error_call: Any = _r12_fallback                  # a field whose default is a function: no method

    def total(self, discount: float = 0) -> float:
        return self.qty * self.price - discount

    def broken(self) -> int:
        return "text"                                   # type: ignore[return-value]

    @staticmethod
    def parse(text: str) -> int:
        return len(text)

    @classmethod
    def of(cls, qty: int) -> Self:
        return cls(qty)

    @property
    def label(self) -> str:
        return f"{self.qty}x"

    @label.setter
    def label(self, value: str) -> None:
        self.qty = len(value)

    def __call__(self, times: int) -> float:
        return self.total() * times

    @enforce.exempt
    def loose(self, a: int) -> Any:
        return a

    def untyped(self, a):
        return a

@dataclass(check_methods = False)
class R12Old:
    n: int = 0
    def add(self, more: int) -> Any:
        return more

@dataclass(slots = True)
class R12Slots(R12Old):
    m: int = 0
    def add(self, more: int) -> Any:
        return super().add(more) + self.m

expect_value("a method of a dataclass: called, its argument converted",  (1.0, "float"), lambda: (lambda v: (v, type(v).__name__))(R12Invoice().total(1)))
expect_message("... a wrong argument",                                ("For parameter discount of <Method R12Invoice.total>: expected type: 'float', got type 'str' (Value: 'a')",), R12Invoice().total, "a")
expect_message("... a wrong return value, with check_return",        ("For return value of <Method R12Invoice.broken>: expected type: 'int', got type 'str' (Value: 'text')",), R12Invoice().broken)
expect_message("... a static method",                                 ("For parameter text of <Method R12Invoice.parse>",), R12Invoice.parse, 5)
expect_message("... a class method",                                  ("For parameter qty of <Method R12Invoice.of>",), R12Invoice.of, "3")
expect_value("... and what it returns for Self",                      3, lambda: R12Invoice.of(3).qty)
expect_message("... a special method the caller hands a value to",    ("For parameter times of <Method R12Invoice.__call__>",), R12Invoice(), "x")
expect_message("... a property's setter",                             ("For parameter value of <Method R12Invoice.label>",), setattr, R12Invoice(), "label", 5)
expect_value("... a field whose default is a function stays a field", ("anything", True), lambda: (R12Invoice().on_error_call("anything"), vars(R12Invoice)["on_error_call"] is _r12_fallback))
expect_value("... enforce.exempt and a method without annotations",   ("a", "b"), lambda: (R12Invoice().loose("a"), R12Invoice().untyped("b")))
expect_raises("... the fields are checked as before",                 R12Invoice, "many")
expect_value("check_methods = False: the methods are as they were written", "x", lambda: R12Old().add("x"))
expect_raises("... the fields are still checked",                      R12Old, "n")
expect_value("a slots dataclass: super() in a checked method",        7, lambda: R12Slots(0, 3).add(4))
expect_message("... and the method is checked",                       ("For parameter more of <Method R12Slots.add>",), R12Slots().add, "a")
expect_message("enforce refuses a dataclass and says where its methods are checked", ("A dataclass is checked by enforced.dataclass, its methods included",), enforce, R12Old)
expect_value("the defaults: check_methods on, check_return off",      (True, False), lambda: tuple(inspect.signature(dataclass).parameters[name].default for name in ("check_methods", "check_return")))


section("phase 7 · the switches from code (turn_typecheck_off and the others)")

def _r13_switches() -> tuple[Any, ...]:
    """What the switches do from code; each is put back as it was."""
    import enforced._environment as env, enforced._formatting_tool as tool
    kept = (env.TYPECHECK_OFF, env.COMPILE_AFTER, tool._CHOSEN)
    try:
        @typecheck
        def before(x: int) -> Any: return x
        enforced_module = __import__("enforced")
        enforced_module.turn_typecheck_off()
        off = enforced_module.typecheck_is_off()

        @typecheck
        def after(x: int) -> Any: return x
        enforced_module.turn_typecheck_on()
        try:
            before("a")
            stays = "unchecked"
        except InvalidDataError:
            stays = "checked"
        enforced_module.set_compile_after(3)
        @typecheck
        def tiered(x: int) -> Any: return x
        compiled = []
        for n in range(4):
            compiled.append("__enforced_source__" in vars(tiered))
            tiered(n)
        enforced_module.turn_colours_on()
        coloured = "\x1b[" in _raw_message(before, "b")
        enforced_module.turn_colours_off()
        plain = "\x1b[" not in _raw_message(before, "c")
        return off, after("a"), stays, compiled, coloured, plain, enforced_module.typecheck_is_off()
    finally:
        env.TYPECHECK_OFF, env.COMPILE_AFTER, tool._CHOSEN = kept

def _raw_message(fn: Callable[..., Any], *args: Any) -> str:
    try:
        fn(*args)
    except InvalidDataError as e:
        return str(e)
    return ""

expect_value("the switches from code: off for what is decorated after, existing wrappers stay, compile after 3, colours",
             (True, "a", "checked", [False, False, False, True], True, True, False), _r13_switches)
expect_raises("set_compile_after refuses 0", lambda: __import__("enforced").set_compile_after(0), exc = ValueError)
expect_raises("... and a text", lambda: __import__("enforced").set_compile_after("3"), exc = TypeError)
expect_value("EnvVar is private now",                                False, lambda: hasattr(__import__("enforced"), "EnvVar"))


section("phase 7 · the reason of a refused value, next to a missing argument")
#* Until 2026-10-18 both paths reported such a value without looking for the reason (a Port of 0
#* read "expected type: 'Port', got type 'int'"). Found by the configured prototype, which leaves
#* a section that failed out of the construction.

@typecheck
def r14_port(host: str, port: Port) -> None: ...

@typecheck(coerce = True, deep = True)
def r14_deep(host: str, ports: list[Port], admin: Email) -> None: ...

@typecheck
def r14_check(host: str, n: Annotated[int, lambda v: v > 0]) -> None: ...

@dataclass(kw_only = True)
class R14Server:
    host: str
    port: Port

def r14_kinds(fn: Callable[..., Any], **kwargs: Any) -> list[str]:
    try:
        fn(**kwargs)
    except InvalidDataError as e:
        return [p.kind for p in e.problems]
    return []

expect_message("a Port of 0 next to a missing argument says why", ("Missing required argument", "must be between 1 and 65535"), r14_port, port = 0,
               absent = ("got type 'int'",))
expect_value("... its kinds: missing, then invalid",                 ["missing", "invalid"], r14_kinds, r14_port, port = 0)
expect_message("deep items and a model next to a missing argument", ("must be between 1 and 65535", "exactly one '@'"),
               r14_deep, ports = ["1", "0"], admin = "nope")
expect_value("... a coercible item is not reported",                 ["missing", "invalid", "invalid"], r14_kinds, r14_deep,
             ports = ["1", "0"], admin = "nope")
expect_message("an Annotated check next to a missing argument",       ("Missing required argument", "failed check v > 0"), r14_check, n = -1)
expect_value("... it is invalid, with the check's reason",           ["missing", "invalid"], r14_kinds, r14_check, n = -1)
expect_message("a dataclass field next to a missing one",            ("must be between 1 and 65535",), R14Server, port = 0)
expect_message("by position, the full path: what doesn't fit and what is missing", ("Missing required argument", "port"), r14_port, 0)


section("phase 7 · a refusal left behind is never another value's reason")
#* The property fuzz (2026-10-18): a note left by an Annotated check (REFUSED) about one object was
#* read as the reason for the same object refused for its type elsewhere.

def r15_positive(v: Any) -> bool: return v > 0

@typecheck(deep = True)
def r15_floats(xs: list[Annotated[float, r15_positive]]) -> None: ...

@typecheck
def r15_int(x: Annotated[int, r15_positive]) -> None: ...

def r15_after_a_note(value: Any) -> list[str]:
    try:
        r15_floats([value])
    except InvalidDataError:
        pass
    return r14_kinds(r15_int, x = value)

_r15_value = -0.5
expect_value("a float refused by a deep check, then for its type: a type problem", ["type"], r15_after_a_note, _r15_value)
expect_value("... again, through the compiled wrapper",               ["type"], r15_after_a_note, _r15_value)
expect_message("a refusal of the value itself still says why",        ("failed check r15_positive",), r15_int, -3)


section("phase 7 · known issues (listed, never fail the run)")
#* A bug that is known but not fixed yet goes here, stating the correct behaviour:
#*     known_issue("where the bug is", expect_value, "what should happen", expected, fn, *args)
#* and gets a strict xfail test in tests/test_known_issues.py.

@dataclass
class KiChecked:
    x: int

@dataclasses.dataclass
class KiRetyped(KiChecked):
    x: str = ""                                                     # type: ignore[assignment]

#* None is open at the moment. The last one is a regular check now:
expect_value("a standard dataclass may give an inherited field another type", "a", lambda: KiRetyped("a").x)
expect_value("... and assign to it what it likes",                   5, lambda: (lambda k: (setattr(k, "x", 5), k.x)[1])(KiRetyped("a")))
expect_raises("... the checked base itself is held to its type",     KiChecked, "a")


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 8: everything together: an application end to end, re-entrancy, threads, stacked decorators
# ═════════════════════════════════════════════════════════════════════════════

class Sku(TypeModel[str]):
    """A stock code such as ABC-0042: three letters and four digits, stored in upper case."""
    @classmethod
    def validate(cls, raw: str) -> str:
        code = raw.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}-\d{4}", code):
            raise ValueError("must look like ABC-0042")
        return code

Quantity = Annotated[int, lambda q: 0 < q <= 1000]
Money = Annotated[float, lambda v: v >= 0]


@dataclass(coerce=True, deep=True, frozen=True)
class AppConfig:
    """Built from strings, as they come out of the environment or a config file."""
    host: str
    port: Port
    admin: Email
    debug: bool = False
    retries: NonNegativeInt = 3
    regions: tuple[str, ...] = ("eu",)
    timeout: float = field(init=False, default=30)

@dataclass(deep=True)
class OrderLine:
    sku: Sku
    qty: Quantity
    unit_price: Money

    @property
    def total(self) -> float:
        return self.qty * self.unit_price

class GiftLine(OrderLine):
    pass

@dataclass(deep=True)
class Order:
    id: PositiveInt
    customer: Email
    lines: list[OrderLine] = field(default_factory=list)
    status: Literal["new", "paid", "shipped"] = "new"
    notes: dict[str, str] | None = None
    total: float = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.total = sum(line.total for line in self.lines)

@typecheck(coerce=True)
def parse_line(sku: Sku, qty: Quantity, unit_price: Money) -> OrderLine:
    return OrderLine(sku, qty, unit_price)

def load_order(raw: Mapping[str, Any]) -> Order:
    """A record as it arrives (everything may be a string): validated first, then turned into objects."""
    _, record = typecheck_record({
        "object_name": "order_record", "record": {"id": PositiveInt, "customer": Email, "lines": list[dict[str, Any]]},
        "kwargs": dict(raw), "coerce": True, "deep": True,
        })
    return Order(record["id"], record["customer"], [parse_line(**line) for line in record["lines"]])

@typecheck(deep=True, check_return=True)
def price(order: Order, discounts: Mapping[str, float] | None = None) -> float:
    rates = discounts or {}
    return sum(line.total * (1 - rates.get(line.sku, 0)) for line in order.lines)

@typecheck(check_return=True)
async def ship(order: Order, carrier: Literal["dhl", "ups"]) -> Order:
    order.status = "shipped"
    return order

@typecheck(allow_subclass=False, deep=True)
def audit(lines: Sequence[OrderLine], clock: Callable[[], float]) -> int:
    return len(lines)

def problems_of(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> list[str]:
    """What an API would send back: one "kind:where" entry per problem, read from the error as data."""
    try:
        fn(*args, **kwargs)
    except InvalidDataError as e:
        return [f"{p.kind}:{p.parameter}" for p in e.problems]
    return []


section("phase 8 · an application, end to end")
_config = expect_ok("config built from strings", AppConfig, "api.local", "8080", " Ops@Example.COM ", "yes", "5", ["eu", "us"])
expect_exact("config: every field parsed into its type", (Port(8080), Email("Ops@example.com"), True, 5, ("eu", "us"), 30.0),
             lambda: (_config.port, _config.admin, _config.debug, _config.retries, _config.regions, _config.timeout))
expect_value("config: defaults", (False, 3, ("eu",)), lambda: (lambda c: (c.debug, c.retries, c.regions))(AppConfig("h", 80, "a@b.io")))
expect_value("config: a bad port and a bad address are both reported, as data", ["invalid:port", "invalid:admin"],
             problems_of, AppConfig, "h", "99999", "nobody")
expect_raises("config is frozen", setattr, _config, "debug", False, exc=dataclasses.FrozenInstanceError)

_raw = {"id": "7", "customer": "Ana@Shop.IO",
        "lines": [{"sku": "abc-0042", "qty": "2", "unit_price": "9.5"}, {"sku": " xyz-0001 ", "qty": 1, "unit_price": 3}]}
_order = expect_ok("order loaded from a raw record", load_order, _raw)
expect_exact("order: values parsed and normalised", (7, Email("Ana@shop.io"), [Sku("ABC-0042"), Sku("XYZ-0001")], [2, 1], 22.0),
             lambda: (_order.id, _order.customer, [l.sku for l in _order.lines], [l.qty for l in _order.lines], _order.total))
expect_value("order: the raw record is left as it was", ("7", "2"), lambda: (_raw["id"], _raw["lines"][0]["qty"]))
expect_value("raw record: a quantity out of range is named", ["invalid:qty"], problems_of, load_order,
             {**_raw, "lines": [{"sku": "abc-0042", "qty": "0", "unit_price": "1"}]})
expect_value("raw record: a malformed stock code is named", ["invalid:sku"], problems_of, load_order,
             {**_raw, "lines": [{"sku": "42", "qty": 1, "unit_price": 1}]})
expect_value("raw record: every bad field is reported at once", ["invalid:id", "invalid:customer", "type:lines"],
             problems_of, load_order, {"id": "-1", "customer": "nobody", "lines": "none"})
expect_value("price: plain total",                       22.0, price, _order)
expect_value("price: with a discount",                   12.5, price, _order, {"ABC-0042": 0.5})
expect_paths("price: a bad discount is located",         ["discounts['ABC-0042']"], price, _order, {"ABC-0042": "half"})
expect_value("price: the int total of an empty order comes back as a float", 0.0, price, Order(8, "b@shop.io"))
expect_raises("order: a status outside the Literal is rejected", setattr, _order, "status", "lost")
expect_value("order: the rejected write left the old status", "new", lambda: _order.status)
expect_message("order: a bad line in an assigned list is located", ("Introspected field Order.lines at index [1]",),
               setattr, _order, "lines", [_order.lines[0], "x"])
expect_value("order: replace() is checked",              9, lambda: dataclasses.replace(_order, id=9).id)
expect_raises("order: replace() with a bad id",          dataclasses.replace, _order, id=0)
expect_value("order: shipped through an async function", "shipped", lambda: asyncio.run(ship(_order, "dhl")).status)
expect_raises("order: unknown carrier",                  lambda: asyncio.run(ship(_order, "fedex")))
expect_value("order: survives pickle",                   True, lambda: pickle.loads(pickle.dumps(_order)) == _order)
expect_value("order: a deep copy is equal and independent", (True, False),
             lambda: (lambda c: (c == _order, c.lines is _order.lines))(copy.deepcopy(_order)))
expect_value("strict audit: a list is a Sequence, a function is a Callable", 2, audit, _order.lines, time.time)
expect_paths("strict audit: a subclass of OrderLine is not an OrderLine", ["lines[0]"], audit, [GiftLine("abc-0001", 1, 1.0)], time.time)


_reentry_seen: list[Any] = []

def _reentry_record(value: Any) -> bool:
    _reentry_seen.append(value)
    return True

def _reentry_checks(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> list[Any]:
    _reentry_seen.clear()
    fn(*args, **kwargs)
    return list(_reentry_seen)

@typecheck(check_return=True)
def fib(n: NonNegativeInt) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)

@typecheck
def is_even(n: int) -> bool: return True if n == 0 else is_odd(n - 1)

@typecheck
def is_odd(n: int) -> bool: return False if n == 0 else is_even(n - 1)

@dataclass(deep=True)
class Chain:
    """Builds the next link while it is being built itself."""
    depth: Annotated[int, _reentry_record]
    tags: list[str] = field(default_factory=list)
    next: "Chain | None" = None

    def __post_init__(self) -> None:
        if self.depth > 0 and self.next is None:
            self.next = Chain(self.depth - 1, self.tags)

    def length(self) -> int:
        return 1 if self.next is None else 1 + self.next.length()

@dataclass
class Nested:
    """Its default_factory builds the same class: between the outer check and the outer assignments."""
    child: "Nested | None" = field(default_factory=lambda: Nested(child=None, label="inner"))
    label: Annotated[str, _reentry_record] = "outer"

@dataclass(deep=True)
class Batch:
    rows: list[int]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("no rows")

@typecheck
def _below_ten(n: int) -> bool: return n < 10

@typecheck
def takes_small(n: Annotated[int, _below_ten]) -> int: return n


section("phase 8 · recursion and re-entrant construction")
expect_value("recursive function, arguments and returns checked at every level", 610, fib, 15)
expect_raises("recursive function: a bad argument at the top",  fib, -1)
expect_value("mutually recursive functions",             True, is_even, 40)
Chain(0)                                                # the first use also checks the defaults
expect_value("a class built inside its own __post_init__: each link checked once", [3, 2, 1, 0], _reentry_checks, Chain, 3)
expect_value("... and every link is there",              4, lambda: Chain(3).length())
expect_paths("... a bad item is caught in the outer object", ["tags[0]"], Chain, 2, [1])
expect_raises("... and in the inner one",                Chain, 2, next=5)
expect_value("a class built inside its own default_factory", ("outer", "inner", None),
             lambda: (lambda n: (n.label, n.child.label, n.child.child))(Nested()))
#* The outer object's label is its default, validated once like any default; the inner one was
#* passed, and is checked in the call that passes it. (While __init__ assigned through the checked
#* __setattr__, this line watched that building the inner object didn't make the outer one skip.)
expect_value("... what the inner object was given is checked, once", ["inner"], _reentry_checks, Nested)
expect_value("... and a value passed to the outer one as well",   ["mine", "inner"], _reentry_checks, lambda: Nested(label = "mine"))
expect_raises("... a bad outer value is still rejected", Nested, label=5)
expect_raises("an exception in __post_init__ comes out as it is", Batch, [], exc=ValueError)
_batch = Batch([1])
expect_raises("... and leaves nothing behind: the next bad assignment is rejected", setattr, _batch, "rows", ["x"])
expect_value("... while a good one is stored",           [2, 3], lambda: (setattr(_batch, "rows", [2, 3]), _batch.rows)[1])
expect_value("a check that calls a checked function",    5, takes_small, 5)
expect_message("... and rejects through it",             ("invalid 'int': failed check _below_ten",), takes_small, 50)


def _in_threads(count: int, work: Callable[[int], Any]) -> list[Any]:
    """Run ``work(i)`` in ``count`` threads released together; their results in order (an exception as a value)."""
    barrier = threading.Barrier(count)
    results: list[Any] = [None] * count

    def run(i: int) -> None:
        barrier.wait()
        try:
            results[i] = work(i)
        except Exception as e:                          # reported by the check that reads the results
            results[i] = e

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                         # switch threads as often as possible
    try:
        for t in threads: t.start()
        for t in threads: t.join()
    finally:
        sys.setswitchinterval(interval)
    return results

def _first_calls_race() -> int:
    """New functions, each called for the first time by 8 threads at once; how many results were wrong."""
    wrong = 0
    for _ in range(25):
        @typecheck(deep=True)
        def scaled(xs: list[int], scale: float = 2) -> float:
            return sum(xs) * scale
        results = _in_threads(8, lambda i: scaled(list(range(i + 1))))
        wrong += sum(1 for i, r in enumerate(results) if type(r) is not float or r != sum(range(i + 1)) * 2.0)
        wrong += sum(1 for r in _in_threads(8, lambda i: scaled([i, "x"])) if not isinstance(r, InvalidDataError))
    return wrong

@dataclass(deep=True)
class Reading:
    sensor: Annotated[str, lambda s: s.startswith("s")]
    values: list[float]

def _constructions_race() -> int:
    """Threads build the same class at once, half of them with a bad value; how many outcomes were wrong."""
    def work(i: int) -> int:
        wrong = 0
        for n in range(200):
            good = (i + n) % 2 == 0
            try:
                reading = Reading(f"s{i}" if good else f"x{i}", [n, n + 0.5])
            except InvalidDataError:
                wrong += good
                continue
            wrong += (not good) or reading.values != [float(n), n + 0.5] or type(reading.values[0]) is not float
        return wrong
    return sum(_in_threads(8, work))

def _assignments_race() -> int:
    """Threads write to one object, valid and invalid values in turn; how many invalid values got stored."""
    target = Reading("s0", [0.0])
    def work(i: int) -> int:
        stored = 0
        for n in range(200):
            try:
                target.values = [n] if n % 2 else ["bad"]
            except InvalidDataError:
                pass
            stored += any(type(v) is not float for v in target.values)
        return stored
    return sum(_in_threads(8, work))

@typecheck
def _four_wrong(a: int, b: str, c: float, d: bytes) -> None: ...

def _first_reads_race() -> int:
    """Errors whose problems 8 threads read for the first time at once; how many readers got other than the one full list."""
    wrong = 0
    for _ in range(150):
        try:
            _four_wrong(d = 1, c = "z", b = 2, a = "x")          # type: ignore[arg-type]
        except InvalidDataError as e:
            error = e
        got = _in_threads(8, lambda i: error.problems)
        wrong += sum(1 for problems in got if problems is not got[0] or [p.parameter for p in problems] != ["a", "b", "c", "d"])
    return wrong

def _record_race() -> int:
    """Equal records with their unions in the other order, used at once: each must keep its own order."""
    def work(i: int) -> int:
        annotation, expected = (int | float, int) if i % 2 == 0 else (float | int, float)
        spec = {"object_name": "race", "record": {"x": annotation}, "kwargs": {"x": "3"}, "coerce": True}
        return sum(type(typecheck_record(spec)[1]["x"]) is not expected for _ in range(200))
    return sum(_in_threads(8, work))

def _record_full_cache_race() -> list[str]:
    """
    The cache of typecheck_record is filled to its limit, then 8 threads bring 150 new specs
    each: every one of them evicts an entry while the other threads do the same. Returns what
    went wrong, in words (a thread that died, a wrong outcome, a cache over its limit).
    """
    import enforced._typechecker._remembered as _remembered
    cache, limit = _remembered.RECORD_CACHE, _remembered._RECORD_CACHE_MAX
    cache.clear()
    for n in range(limit):
        typecheck_record({"object_name": f"filler_{n}", "record": {"x": int}, "args": (1,)})

    def work(i: int) -> int:
        wrong = 0
        for n in range(150):
            spec = {"object_name": f"thread_{i}_{n}", "record": {"x": float}, "args": (n,)}
            wrong += type(typecheck_record(spec)[0][0]) is not float
            try:
                typecheck_record({**spec, "args": ("x",)})
                wrong += 1
            except InvalidDataError:
                pass
        return wrong

    problems: list[str] = []
    for i, result in enumerate(_in_threads(8, work)):
        if isinstance(result, Exception):
            problems.append(f"thread {i} died with {type(result).__name__}: {str(result)[:60]}")
        elif result:
            problems.append(f"thread {i}: {result} wrong outcomes")
    if len(cache) > limit:
        problems.append(f"the cache holds {len(cache)} entries, its limit is {limit}")
    return problems


section("phase 8 · threads")
expect_value("first calls from 8 threads at once: every result right", 0, _first_calls_race)
expect_value("constructions from 8 threads: valid accepted, invalid rejected", 0, _constructions_race)
expect_value("assignments from 8 threads: no invalid value is ever stored", 0, _assignments_race)
expect_value("an error's problems read by 8 threads at once: one full list", 0, _first_reads_race)
expect_value("typecheck_record from 8 threads: each record keeps its union order", 0, _record_race)
expect_value("typecheck_record with a full cache, 8 threads of new specs: no thread fails, the limit holds", [],
             _record_full_cache_race)


def logged(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A decorator like any a user would write."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        wrapper.calls += 1                              # type: ignore[attr-defined]
        return fn(*args, **kwargs)
    wrapper.calls = 0                                   # type: ignore[attr-defined]
    return wrapper

@logged
@typecheck
def st_below(x: int, y: float = 2) -> float:
    """Multiply."""
    return x * y

@typecheck
@logged
def st_above(x: int, y: float = 2.0) -> float: return x * y

@functools.lru_cache(maxsize=None)
@typecheck
def st_cached(n: int) -> int: return n * n

@typecheck
@functools.lru_cache(maxsize=None)
def st_cached_inside(n: int) -> int: return n * n

@typecheck
def st_add(a: int, b: int, c: int = 0) -> int: return a + b + c

@contextlib.contextmanager
@typecheck
def st_opened(name: str) -> Iterator[str]:
    yield name.upper()

def _with_opened(name: Any) -> str:
    with st_opened(name) as opened:
        return opened

class StScaler:
    @typecheck
    def __call__(self, x: float) -> float: return x * 2

    @staticmethod
    @typecheck
    def half(x: float) -> float: return x / 2

    @classmethod
    @typecheck
    def named(cls, name: str) -> str: return f"{cls.__name__}:{name}"

@typecheck
async def st_async(n: int) -> int: return n


section("phase 8 · stacked decorators and introspection")
expect_value("under a user decorator: checked, converted default", (6.0, 1), lambda: (st_below(3), st_below.calls))
expect_raises("under a user decorator: bad argument",    st_below, "3")
expect_value("above a functools.wraps decorator: its signature is followed", 6.0, st_above, 3)
expect_raises("above a functools.wraps decorator: bad argument", st_above, "3")
expect_value("under lru_cache: cached after the check",  (16, 16, 1), lambda: (st_cached(4), st_cached(4), st_cached.cache_info().hits))
expect_raises("under lru_cache: a bad argument is not cached", st_cached, "4")
expect_value("above lru_cache",                          16, st_cached_inside, 4)
expect_raises("above lru_cache: bad argument",           st_cached_inside, "4")
expect_value("functools.partial of a checked function",  3, functools.partial(st_add, 1), 2)
expect_raises("functools.partial: bad later argument",   functools.partial(st_add, 1), "2")
expect_raises("functools.partial: bad bound keyword",    functools.partial(st_add, c="x"), 1, 2)
expect_value("under contextlib.contextmanager",          "A", _with_opened, "a")
expect_raises("under contextlib.contextmanager: bad argument at the call", _with_opened, 1)
expect_value("__call__, a static method and a class method", (4.0, 1.5, "StScaler:x"),
             lambda: (StScaler()(2), StScaler.half(3), StScaler.named("x")))
expect_raises("__call__: bad argument",                  StScaler(), "2")
expect_raises("static method: bad argument",             StScaler.half, "3")
expect_raises("class method: bad argument",              StScaler.named, 3)
expect_value("name, docstring and __wrapped__ are the function's own", ("st_add", "Multiply.", "st_add"),
             lambda: (st_add.__name__, st_below.__doc__, st_add.__wrapped__.__name__))
expect_value("inspect.signature shows the real parameters", "(a: int, b: int, c: int = 0) -> int", lambda: str(inspect.signature(st_add)))
expect_value("a checked coroutine function is still one", True, inspect.iscoroutinefunction, st_async)
expect_value("a checked function pickles by name",       True, lambda: pickle.loads(pickle.dumps(st_add)) is st_add)


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 9: protect, Ok and Err: what an awaitable did, as a value
# ═════════════════════════════════════════════════════════════════════════════

from enforced import Err, Ok, protect                           # noqa: E402

async def p9_fetch(user_id: int, fail: BaseException | None = None) -> dict[str, Any]:
    await asyncio.sleep(0)
    if fail is not None:
        raise fail
    return {"id": user_id}

@typecheck
async def p9_checked(user_id: int) -> int:
    return user_id

def p9_read(result: Any) -> str:
    match result:
        case Ok(value):
            return f"ok:{value}"
        case Err(error):
            return f"err:{type(error).__name__}"
    return "neither"

def p9_run(awaitable: Any) -> Any:
    return asyncio.run(protect(awaitable))

async def p9_batch() -> list[str]:
    """Six requests at once, every other one failing: each comes back as its own result."""
    results = await asyncio.gather(*(protect(p9_fetch(n, KeyError(n) if n % 2 else None)) for n in range(6)))
    return [p9_read(r) for r in results]

async def p9_cancel() -> str:
    task = asyncio.create_task(protect(asyncio.sleep(60)))
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return "cancelled"
    return "swallowed"

async def p9_timeout() -> str:
    return p9_read(await protect(asyncio.wait_for(asyncio.sleep(60), 0.001)))

@dataclass(frozen = True)
class P9Report:
    done: list[Ok[dict[str, Any]]]
    failed: list[Err]

async def p9_report() -> P9Report:
    results = await asyncio.gather(*(protect(p9_fetch(n, ValueError(n) if n > 2 else None)) for n in range(5)))
    return P9Report([r for r in results if isinstance(r, Ok)], [r for r in results if isinstance(r, Err)])

section("phase 9 · protect, Ok and Err")
expect_value("an awaitable that completes: Ok with its result",      Ok({"id": 7}), p9_run, p9_fetch(7))
expect_value("... read with match",                                  "ok:{'id': 7}", lambda: p9_read(p9_run(p9_fetch(7))))
expect_value("an awaitable that raises: Err with the exception",     "err:ValueError", lambda: p9_read(p9_run(p9_fetch(7, ValueError("no")))))
expect_value("... the very exception, traceback and all",            True,
             lambda: (lambda e: (lambda r: r.error is e and e.__traceback__ is not None)(p9_run(p9_fetch(1, e))))(RuntimeError("x")))
expect_value("an InvalidDataError of the work is an Err like any other", "err:InvalidDataError", lambda: p9_read(p9_run(p9_checked("7"))))
expect_value("... and a checked coroutine that is fine an Ok",       Ok(7), p9_run, p9_checked(7))
expect_raises("what can't be awaited is refused, not reported as Err", p9_run, p9_fetch)
expect_message("... in the usual words",                             ("For parameter c of <Function protect>: expected type: 'collections.abc.Awaitable', got type 'int'",), p9_run, 5)
expect_raises("cancellation goes through",                           p9_run, p9_fetch(1, asyncio.CancelledError()), exc = asyncio.CancelledError)
expect_raises("... and so does KeyboardInterrupt",                   p9_run, p9_fetch(1, KeyboardInterrupt()), exc = KeyboardInterrupt)
expect_value("a protected task can be cancelled",                    "cancelled", asyncio.run, p9_cancel())
expect_value("a timeout is an Err",                                  "err:TimeoutError", asyncio.run, p9_timeout())
expect_value("several at once: each its own result",                 ["ok:{'id': 0}", "err:KeyError", "ok:{'id': 2}", "err:KeyError", "ok:{'id': 4}", "err:KeyError"], asyncio.run, p9_batch())
expect_value("results as fields of a checked dataclass (deep off)",  (3, 2), lambda: (lambda r: (len(r.done), len(r.failed)))(asyncio.run(p9_report())))
expect_value("Ok holds anything, None too",                          None, lambda: Ok(None).value)
expect_value("a result is a standard dataclass: nothing in it is checked", True,
             lambda: dataclasses.is_dataclass(Ok) and "__enforced_dataclass__" not in vars(Ok) and "__enforced_dataclass__" not in vars(Err))
expect_raises("a result can't be changed",                           setattr, Ok(1), "value", 2, exc = dataclasses.FrozenInstanceError)
expect_value("equal results are equal, and hash alike",              True, lambda: Ok(1) == Ok(1) and hash(Ok("a")) == hash(Ok("a")) and Ok(1) != Ok(2))
expect_value("a result pickles",                                     Ok([1, 2]), lambda: pickle.loads(pickle.dumps(Ok([1, 2]))))
expect_value("... an Err with its exception",                        ("KeyError", ("k",)), lambda: (lambda e: (type(e).__name__, e.args))(pickle.loads(pickle.dumps(Err(KeyError("k")))).error))
expect_value("protect is a coroutine function to inspect",           True, lambda: inspect.iscoroutinefunction(protect))


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 10 · dispatch: a version chosen by the type of the first argument
# ═════════════════════════════════════════════════════════════════════════════

from enforced import dispatch, dispatchmethod                      # noqa: E402
from enforced.data_types import Email as p10_Email, Port as p10_Port   # noqa: E402
import gc as p10_gc                                                 # noqa: E402
import weakref as p10_weakref                                       # noqa: E402

section("phase 10 · dispatch: each kind of anchor")


def p10_positive(n: int) -> bool:
    return n > 0


@dispatch
def p10_kind(value) -> str:
    return "base"


@p10_kind.register
def _(value: list[int]) -> str: return "list[int]"
@p10_kind.register
def _(value: list[str]) -> str: return "list[str]"
@p10_kind.register
def _(value: dict[str, list[int]]) -> str: return "dict[str, list[int]]"
@p10_kind.register
def _(value: tuple[int, str]) -> str: return "tuple[int, str]"
@p10_kind.register
def _(value: Literal["json", "yaml"]) -> str: return "format"
@p10_kind.register
def _(value: Annotated[int, p10_positive]) -> str: return "positive"
@p10_kind.register
def _(value: int | None) -> str: return "int or None"
@p10_kind.register
def _(value: p10_Email) -> str: return "email"
@p10_kind.register
def _(value: type[Animal]) -> str: return "animal class"


for p10_value, p10_expected in [([1, 2], "list[int]"), (["a"], "list[str]"), ([], "list[int]"), ([1, "a"], "base"),
                                ({"k": [1]}, "dict[str, list[int]]"), ({"k": ["x"]}, "base"), ((1, "a"), "tuple[int, str]"),
                                ("json", "format"), ("xml", "base"), (5, "positive"), (-5, "int or None"),
                                (None, "int or None"), (True, "base"), (1.5, "base"), (p10_Email("a@b.co"), "email"),
                                ("c@d.co", "email"), (Dog, "animal class")]:
    expect_value(f"{repr(p10_value)[:30]} goes to {p10_expected}", p10_expected, p10_kind, p10_value)


@dispatch
def p10_show(v) -> Any:
    return v


@p10_show.register
def _(v: p10_Email | p10_Port) -> Any:
    return v


expect_value("... an Email built from its text",                   "Email", lambda: type(p10_show("A@B.co")).__name__)
expect_value("... a Port from its number",                         "Port", lambda: type(p10_show(8080)).__name__)
expect_value("... a refused one goes to the next candidate",       0, p10_show, 0)

section("phase 10 · dispatch: the order, and nothing converted")


@dispatch
def p10_num(v) -> str:
    return "base"


@p10_num.register
def _(v: float) -> str: return "float"
@p10_num.register
def _(v: int) -> str: return "int"


expect_value("1 goes to int, not to float as 1.0",                 "int", p10_num, 1)
expect_value("'5' is not coerced",                                 "base", p10_num, "5")
expect_value("the first registered wins: [] is list[int]",        "list[int]", p10_kind, [])

section("phase 10 · dispatch: the error of a value no version takes")
def _p10_error(call: Any) -> Any:
    try:
        call()
    except InvalidDataError as e:
        return e
    raise AssertionError("no error")



@dispatch
def p10_shape(node: int) -> str:
    return "int"


@p10_shape.register
def _(node: list[str]) -> str: return "strs"


expect_message("each candidate says why",                          ("2 problems found in dispatch:",
               "Version 1 (list[str]) of <Function p10_shape> refuses node: at node[1]: expected type: 'str', got type 'int'",
               "The base (int) of <Function p10_shape> refuses node: expected type: 'int', got type 'list'"), p10_shape, ["a", 1])
expect_value("errors(): one entry per candidate",                  [["node", 1], ["node", 0]],
             lambda: (lambda e: [x["loc"] for x in e.errors()])(_p10_error(lambda: p10_shape(1.5))))
expect_message("no anchor",                                        ("Missing required argument node of <Function p10_shape>",), p10_shape)
expect_message("the anchor by keyword",                            ("takes node positionally",), p10_shape, node = 1)


section("phase 10 · dispatch: unreachable versions are refused where they are registered")


def p10_register(annotation: Any) -> Any:
    @dispatch
    def f(v) -> str:
        return "base"
    f.register(int, lambda v: "int")
    f.register(str, lambda v: "str")
    f.register(Sequence[int], lambda v: "ints")
    return f.register(annotation, lambda v: "new")


for p10_ann in (int | str, Literal[1, "a"], list[int], object, Literal[3]):
    expect_raises(f"{p10_ann!r} after int, str, Sequence[int]",    p10_register, p10_ann)
for p10_ann in (bool, float, list[str], bytes, tuple[str, ...]):
    expect_ok(f"{p10_ann!r} still reaches its version",            p10_register, p10_ann)
expect_message("the message names each part and who takes it",     ("version 4 (int | str) can never be chosen",
               "'int' is taken by version 1 (int)", "'str' is taken by version 2 (str)"), p10_register, int | str)
expect_message("a version that hides the base",                    ("leaves the base (Any) unreachable",), p10_register, Any)

section("phase 10 · dispatch: the other parameters, methods, the cache")


@dispatch(check_return = True)
def p10_area(shape, scale: float = 1.0) -> float:
    return 0.0


@p10_area.register
def _(shape: int, scale: float = 1.0) -> float:
    return shape * scale


expect_value("the other parameters are converted (3 -> 3.0)",      6.0, p10_area, 2, 3)
expect_message("... and checked",                                  ("parameter scale",), p10_area, 2, "x")
expect_message("... a version's error names the version and its line", ("For parameter scale of <Version 1 (int) of <Function p10_area>, line",),
               p10_area, 2, "x")


class P10Shapes:
    @dispatchmethod
    def area(self, shape) -> str:
        return "?"

    @area.register
    def _(self, shape: list[int]) -> str:
        return f"sum {sum(shape)}"


expect_value("a method dispatches on the argument after self",     "sum 3", lambda: P10Shapes().area([1, 2]))
expect_value("... and falls back to its base",                     "?", lambda: P10Shapes().area("x"))


def p10_classes_left() -> int:
    @dispatch
    def f(v) -> str:
        return "base"
    f.register(int, lambda v: "int")
    refs = []
    for i in range(40):
        cls = type(f"P10Made{i}", (), {})
        f(cls())
        refs.append(p10_weakref.ref(cls))
    del cls
    for _ in range(3):
        p10_gc.collect()
    return sum(r() is not None for r in refs)


expect_message("typecheck refuses a dispatcher",                   ("typecheck cannot check the dispatcher",), typecheck, p10_area)
expect_value("the cache keeps no class alive",                     0, p10_classes_left)
for _ in range(80):                                                 # past the call at which a wrapper is compiled
    p10_kind([1]); p10_area(2, 3)
expect_value("compiled, the same answers",                         ("list[int]", 6.0), lambda: (p10_kind([1]), p10_area(2, 3)))


# ═════════════════════════════════════════════════════════════════════════════
#  RESULTS
# ═════════════════════════════════════════════════════════════════════════════

total = _stats["ok"] + _stats["miss"] + _stats["unexpected"]
failed = _stats["miss"] + _stats["unexpected"]
elapsed = time.process_time()

print(f"\n{'═' * 72}\n{formatter('  Results by section', 'bold')}\n{'─' * 72}")
for title, (passed, count) in _sections.items():
    if count:
        mark = formatter("✓", "bold_green") if passed == count else formatter("✗", "bold_red")
        print(f"  {mark} {title:<58} {passed:>3}/{count:<3}")
print(f"{'─' * 72}")
print(f"  {formatter(str(_stats['ok']), 'bold_green')} passed")
if _stats["miss"]:
    print(f"  {formatter(str(_stats['miss']), 'bold_red')} missed (expected an error, none raised)")
if _stats["unexpected"]:
    print(f"  {formatter(str(_stats['unexpected']), 'bold_red')} unexpected (wrong error, wrong value, or raised when it shouldn't)")
for line in _failures:
    print(f"    {line}")
print(f"  {total} total checks in {elapsed:.2f}s CPU")
if _open_issues:
    hint = "run without -q to list them" if QUIET else "listed under phase 7 above"
    print(f"  {formatter(str(len(_open_issues)), 'bold_yellow')} known issues still open ({hint})")
if _fixed_issues:
    print(f"  {formatter(str(len(_fixed_issues)), 'bold_cyan')} known issues now fixed: make them regular checks")
    for line in _fixed_issues:
        print(f"    {formatter('FIXED', 'bold_cyan')} {line}")
print(f"{'═' * 72}")

if failed:
    raise RuntimeError(
        f"{formatter('Simulation failed', 'bold_red')}\n{' ' * 3}{failed} of {total} checks did not pass "
        f"({_stats['miss']} missed, {_stats['unexpected']} unexpected)"
        ) from None

print(formatter("Simulation passed!", "bold_green"))
