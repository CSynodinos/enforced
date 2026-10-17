"""
Differential fuzz for enforced: the same random annotations and values go through a previous
copy of the package (the *baseline*) and through the working tree, and every outcome that differs
is listed. Run it for every change that touches checking: a refactor must show no difference at
all, a fix only the differences it is meant to make.

    python tests/fuzz.py --save-baseline            # before changing the package: keep a copy of it
    python tests/fuzz.py                            # compare that copy with the working tree
    python tests/fuzz.py --cases 200000 --seed 7    # more comparisons, other random cases
    python tests/fuzz.py --ref HEAD                 # take the baseline from a git revision instead
    python tests/fuzz.py --baseline ../old/enforced
    python tests/fuzz.py --expect "hidden default"  # a difference the change is meant to make
    python tests/fuzz.py --properties               # no baseline: what must hold in any version

Each case is one annotation with one set of options, used in one way and tried with several values.
The ways are named in the output: ``argument``, ``keyword``, ``varargs``, ``kwargs``, ``binding`` (calls
with too few, too many or misnamed arguments), ``return``, ``method`` (a class decorated with
``enforce``, or with ``typecheck`` in a baseline from before the two were split), ``own options``
(a method with its own ``typecheck`` in an enforced class, which must behave like the class's own
check with the same options, and next to it a method marked ``enforce.exempt``), ``special method``
(``__call__``, ``__getitem__``, ``__setitem__``, ``__contains__`` and ``__new__`` of an enforced class,
which must behave like an ordinary method with the same annotations), ``typed kwargs``
(``**kwargs: Unpack[TypedDict]``, which must behave like a keyword-only parameter), ``tuple args``
(``*args: *tuple[...]``, like a positional parameter), ``callable object`` (``typecheck`` on an object
with ``__call__``, like the plain function), ``member``
(``typecheck`` written above ``@classmethod``, ``@staticmethod`` and ``@property``), ``coroutine``,
``default``, ``record``, ``field`` (a dataclass field: construction, then assignment),
``inherited field`` (the same through a checked subclass, which must behave like the flat class),
``field default``, ``factory default``, ``hidden default`` (``field(init=False, default=...)``) and
``class default`` (``dataclass(init=False)``). A value is either built from the annotation (valid,
or one conversion away) or random. An outcome is the returned value or the error with its message.
Six more things count as a difference: a value that is changed by the call it is passed to, a
second call that disagrees with the first, a returned value that isn't accepted as it is when
passed in again, a checked subclass that disagrees with the flat class of the same fields, a
method whose own ``typecheck`` disagrees with the class's, and a special method that disagrees with
an ordinary one.

Cases are split in two zones. In ``core`` (``deep=False``, no ``Annotated`` check, no ``TypeModel``)
the outcomes are expected to be identical; ``extended`` covers the rest. A difference is fine when
the change was meant to make it: describe it with ``--expect REGEX`` (repeatable), which is searched
in the difference as it is printed, joined on one line with " ; " between the parts:

    zone ; use ; options ; annotation <- value ; baseline: outcome ; now: outcome

so ``--expect "; return ; [^;]*coerce"`` names the return values of functions checked with ``coerce``.
A change in how messages name a type touches thousands of errors that no regex describes well: with
``--ignore-type-names`` two errors that differ only there count as identical, and their number is shown.
The run ends with "Fuzz passed!", or with exit status 1 when a difference is left unexplained.

``--properties`` needs no baseline. It checks the working tree alone against what must hold in any
version: an error is a ``TypeCheckerError`` (or one Python itself raises, such as a mutable dataclass
default), repeats agree (a second call, a returned value passed in again, a subclass, a method's own
check, a special method), and a looser setting never rejects what the stricter one accepts (``deep=False`` for ``deep=True``, ``allow_subclass=True`` for
``False``, ``coerce`` and ``convert`` on for off).

This is not a pytest file: run it by hand, as the simulation and the benchmark.
"""
import sys
import os
os.environ["ENFORCED_COLOURS_OFF"] = "1"          # the messages are compared as text
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
import abc
import argparse
import atexit
import collections
import dataclasses
import datetime
import decimal
import enum
import filecmp
import importlib
import inspect
import importlib.util
import io
import numbers
import random
import re
import shutil
import subprocess
import tarfile
import tempfile
import types
import typing
import uuid
import warnings
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable, Collection, Iterable, KeysView, Mapping, MutableSequence, Sequence, Set
from pathlib import Path, PurePosixPath
from typing import (
    IO, Annotated, Any, BinaryIO, Dict, Final, List, Literal, LiteralString, NamedTuple, NewType, Optional, Protocol,
    TextIO, Tuple, TypedDict, TypeVar, Union, runtime_checkable,
    )

import enforced


PACKAGE = Path(PROJECT_ROOT) / "enforced"
SAVED = Path(PROJECT_ROOT) / "tests" / ".baseline"      # holds a copy of the package (git-ignored)
BASELINE_NAME = "enforced_baseline"                    # what the previous copy is imported as
VALUES_PER_CASE = 5


# ═════════════════════════════════════════════════════════════════════════════
#  THE BASELINE: a previous copy of the package, imported next to the working tree
# ═════════════════════════════════════════════════════════════════════════════

def save_baseline() -> None:
    """Copy the package as it is now to ``tests/.baseline``, replacing the copy already there."""
    shutil.rmtree(SAVED, ignore_errors = True)
    shutil.copytree(PACKAGE, SAVED / "enforced", ignore = shutil.ignore_patterns("__pycache__"))
    print(f"Baseline saved: {SAVED.relative_to(PROJECT_ROOT)} is a copy of enforced/ as it is now.")
    print("Change the package, then run  python tests/fuzz.py  to compare the two.")


def baseline_from_git(ref: str) -> Path:
    """Extract ``enforced/`` as it is at git revision ``ref`` into a temporary directory."""
    done = subprocess.run(["git", "-C", PROJECT_ROOT, "archive", "--format=tar", ref, "enforced"], capture_output = True)
    if done.returncode != 0:
        sys.exit(f"Cannot read enforced/ at git revision {ref!r}: {done.stderr.decode().strip()}")
    target = tempfile.mkdtemp(prefix = "pv_fuzz_")
    atexit.register(shutil.rmtree, target, ignore_errors = True)
    with tarfile.open(fileobj = io.BytesIO(done.stdout)) as archive:
        archive.extractall(target, filter = "data")
    return Path(target) / "enforced"


def find_baseline(path: str | None, ref: str | None) -> tuple[Path, str]:
    """The directory of the baseline package and a line that says where it comes from."""
    if path is not None:
        folder = Path(path).resolve()
        if not (folder / "__init__.py").exists():
            folder = folder / "enforced"                  # a directory that holds the copy
        if not (folder / "__init__.py").exists():
            sys.exit(f"No copy of the package at {path!r} (expected __init__.py there, or in its enforced/ folder).")
        return folder, str(folder)
    if ref is not None:
        return baseline_from_git(ref), f"git revision {ref}"
    folder = SAVED / "enforced"
    if not folder.exists():
        sys.exit("There is no baseline to compare with. Before changing the package, run\n"
                 "    python tests/fuzz.py --save-baseline\n"
                 "or name one: --ref HEAD (a git revision) or --baseline DIR (a copy of the package).")
    saved = datetime.datetime.fromtimestamp(SAVED.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return folder, f"{SAVED.relative_to(PROJECT_ROOT)} (saved {saved})"


def compile_at_once(package: types.ModuleType) -> None:
    """
    Tiered compilation off for ``package`` (a version without tiers has nothing to switch): a
    wrapper is compiled at its first call, so that of the values of a case the first takes the
    general path and the others the compiled wrapper, as the cases are laid out for.
    """
    environment = sys.modules.get(f"{package.__name__}._environment")
    if environment is not None and hasattr(environment, "COMPILE_AFTER"):
        environment.COMPILE_AFTER = 1


def load_baseline(folder: Path) -> types.ModuleType:
    """Import the package found in ``folder`` under another name, so both versions live in one process."""
    spec = importlib.util.spec_from_file_location(BASELINE_NAME, folder / "__init__.py", submodule_search_locations = [str(folder)])
    module = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    sys.modules[BASELINE_NAME] = module                     # its relative imports resolve to the copy
    spec.loader.exec_module(module)                         # type: ignore[union-attr]
    return module


def same_sources(a: Path, b: Path) -> bool:
    """Whether two copies of the package hold the same ``.py`` files."""
    def sources(folder: Path) -> list[str]:
        return sorted(str(f.relative_to(folder)) for f in folder.rglob("*.py"))
    names = sources(a)
    return names == sources(b) and all(filecmp.cmp(a / name, b / name, shallow = False) for name in names)


# ═════════════════════════════════════════════════════════════════════════════
#  RANDOM ANNOTATIONS
# ═════════════════════════════════════════════════════════════════════════════

class Animal:
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self)

    def __hash__(self) -> int:
        return 7


class Dog(Animal):
    pass


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Level(enum.IntEnum):
    LOW = 1


class MyList(list):
    pass


class Movie(TypedDict):
    title: str
    year: int


class Options(TypedDict, total = False):
    verbose: bool
    tags: list[str]


class Point(NamedTuple):
    x: float
    y: float


@runtime_checkable
class Closeable(Protocol):
    def close(self) -> None: ...


class Shape(abc.ABC):
    @abc.abstractmethod
    def area(self) -> float: ...


class Square(Shape):
    """A concrete Shape, which also happens to be Closeable."""
    def area(self) -> float:
        return 1.0

    def close(self) -> None:
        return None

    def __repr__(self) -> str:
        return "Square()"

    def __eq__(self, other: object) -> bool:
        return type(other) is Square

    def __hash__(self) -> int:
        return 11


UserId = NewType("UserId", int)
IntOrStr = TypeVar("IntOrStr", int, str)
SomeAnimal = TypeVar("SomeAnimal", bound = Animal)
LaterAnimal = TypeVar("LaterAnimal", bound = "Animal")      # the bound as a string, looked up in this module
ListOrMap = TypeVar("ListOrMap", list[int], dict[str, float])  # constraints with items of their own
type Vec = tuple[float, float]
type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
#* The same alias written the old way: the inner name stays a string, and is looked up in this module.
OldJson = Union[None, bool, int, float, str, List["OldJson"], Dict[str, "OldJson"]]


def positive(value: Any) -> bool:
    return value > 0


def short(value: Any) -> bool:
    return len(value) < 3


def small(value: Any) -> bool:
    if value >= 100:
        raise ValueError("must be below 100")
    return True


#* Annotations that mean the same in both versions of the package.
LEAVES: list[Any] = [
    int, str, float, bool, bytes, complex, None, list, dict, tuple, set, frozenset, Any, object, Animal, Dog, Color, Level,
    Literal["a", "b"], Literal[1, 2], Literal[1, "a", None, True], type[int], type[Animal], type, type[int | str], type[Any],
    Callable, Sequence, Mapping, Iterable, Collection, UserId, Vec, Json, Tuple, List, Dict, int | str, float | None,
    "int", "Animal", Movie, Options, Point, Closeable, Shape, Square, IntOrStr, SomeAnimal, Final[int], numbers.Real,
    datetime.date, decimal.Decimal, uuid.UUID, PurePosixPath, type[Animal] | None, type[int] | str, Literal["a"] | None,
    TextIO, BinaryIO, IO, IO[str], IO[bytes], TextIO | None, LaterAnimal, "list[int]", "dict[str, float] | None",
    LiteralString, Path, numbers.Number, KeysView, ListOrMap, OldJson, typing.ChainMap[str, float],
    ]
CHECKED: list[Any] = [
    Annotated[int, positive], Annotated[str, short], Annotated[float, positive], Annotated[list, short],
    Annotated[int, positive, small],
    ]
SET_ITEMS: list[Any] = [int, str, float, Color, Animal]


def validated_types(package: types.ModuleType) -> list[Any]:
    """
    The validated types of one version of the package: ``CHECKED``, its ready-made ``data_types`` and
    a ``TypeModel`` of our own. Both versions give the same list, name for name.
    """
    data_types = importlib.import_module(f"{package.__name__}.data_types")

    class Even(package.TypeModel[int]):                     # type: ignore[name-defined]
        @classmethod
        def validate(cls, raw: int) -> int:
            if raw % 2:
                raise ValueError("must be even")
            return raw

    return CHECKED + [data_types.Email, data_types.Port, data_types.PositiveInt, data_types.NonNegativeInt, Even]


def random_annotation(rng: random.Random, depth: int, validated: list[Any] | None) -> Any:
    """
    A random annotation, at most ``depth`` levels of nesting. ``validated`` adds the validated types
    of one version of the package. Run again from the same ``rng`` state with the other version's
    list, it gives the same annotation for that version.
    """
    if depth <= 0 or rng.random() < 0.38:
        return rng.choice(LEAVES + validated * 3 if validated else LEAVES)
    try:
        return _composed(rng, depth, validated)
    except TypeError:                                       # a form typing refuses, e.g. Final[int] inside a union
        return rng.choice(LEAVES)


def _composed(rng: random.Random, depth: int, validated: list[Any] | None) -> Any:
    """A generic or a union around random annotations."""
    inner = lambda: random_annotation(rng, depth - 1, validated)
    kind = rng.randrange(17)
    if kind == 0: return list[inner()]
    if kind == 1: return dict[rng.choice([str, int, inner()]) if rng.random() < 0.8 else inner(), inner()]
    if kind == 2: return tuple[inner(), inner()]
    if kind == 3: return tuple[inner(), ...]
    if kind == 4: return set[rng.choice(SET_ITEMS)]
    if kind in (5, 6):
        left, right = inner(), inner()
        try:
            return left | right
        except TypeError:                                   # e.g. two strings
            return Union[left, right]
    if kind == 7: return Optional[inner()]
    if kind == 8: return Sequence[inner()]
    if kind == 9: return Mapping[str, inner()]
    if kind == 10: return Collection[inner()]
    if kind == 11: return Annotated[inner(), "a note"]
    if kind == 12: return frozenset[rng.choice([int, str, float])]
    if kind == 13: return deque[inner()]
    if kind == 14: return MutableSequence[inner()]
    if kind == 15: return OrderedDict[str, inner()]
    return defaultdict[str, inner()]


# ═════════════════════════════════════════════════════════════════════════════
#  RANDOM VALUES
# ═════════════════════════════════════════════════════════════════════════════

class FileProxy:
    """Not an io class, but everything a file has: what it wraps answers for it."""
    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)

    def __enter__(self) -> "FileProxy": return self
    def __exit__(self, *exc: Any) -> None: return None

    def __repr__(self) -> str:
        return f"FileProxy({type(self.wrapped).__name__})"


TEXT_FILE, BINARY_FILE = io.StringIO(), io.BytesIO()
FILES: list[Any] = [TEXT_FILE, BINARY_FILE, FileProxy(TEXT_FILE), FileProxy(BINARY_FILE), sys.stdout, "notes.txt", io.StringIO, 5]

SCALARS: list[Any] = [
    0, 1, -3, 7, 2**60, 100, True, False, 1.0, 2.5, -0.5, 3.0, float("inf"), "", "a", "ab", "abcd", "1", " 42 ", "2.5", "yes",
    "red", "true", "b", "ana@Example.com", b"x", b"", 1 + 2j, None, Animal(), Dog(), Color.RED, Level.LOW, int, str, bool,
    Animal, Dog, float, len, print, 2, 8080, 70000, Square(), Point(1.0, 2.0), Point(1, 2), datetime.date(2024, 2, 29),
    Color, Shape, Path("a/b"), {"a": 1}.keys(),
    "2024-02-29", decimal.Decimal("1.10"), "1.10", uuid.UUID(int = 7), "00000000-0000-0000-0000-000000000007",
    PurePosixPath("a/b"), "a/b", TEXT_FILE, BINARY_FILE,
    ]

#* Values for a class: valid ones, and ones that conversion or coercion can make valid.
BY_CLASS: dict[type, list[Any]] = {
    int: [0, 1, 7, -3, True, 2.0, "5", Level.LOW], str: ["", "a", "abcd", b"x", 1], float: [1.5, -0.5, 2, 0, "2.5", True],
    bool: [True, False, 1, 0, "yes", "no"], bytes: [b"x", "x"], complex: [1j, 2, 1.5], type(None): [None],
    list: [[], [1], (1, 2)], dict: [{}, {"a": 1}], tuple: [(), (1, "a"), [1]], set: [set(), {1}, [1]],
    frozenset: [frozenset({1}), {1}], Animal: [Animal(), Dog()], Dog: [Dog(), Animal()], Color: [Color.RED, "red", "nope"],
    Level: [Level.LOW, 1], type: [int, str, Dog, bool, Color, Shape, 5], object: [1, "a", None, Dog()],
    Path: [Path("a/b"), PurePosixPath("a/b"), "a/b"], numbers.Number: [1, 1.5, 1j, True, "1"],
    KeysView: [{}.keys(), {"a": 1}.keys(), OrderedDict(a = 1).keys(), {}.items(), ["a"]],
    collections.ChainMap: [collections.ChainMap({"a": 1}, {"b": 2.5}), collections.ChainMap({"a": 1.5}),
                           collections.ChainMap({"a": 1}, OrderedDict(a = "x", b = 2)), collections.ChainMap({"a": "x"}), {"a": 1}],
    Movie: [{"title": "t", "year": 1999}, {"title": "t", "year": "1999"}, {"title": "t"}, {"title": 1, "year": 2, "more": 3}, "t",
            OrderedDict(title = "t", year = 1999), OrderedDict(year = "1999", title = "t"), defaultdict(list, title = "t", year = "7")],
    Options: [{}, {"verbose": True}, {"verbose": "yes", "tags": ["a", 1]}, {"tags": ("a",)}],
    Point: [Point(1.0, 2.0), Point(1, 2), (1.0, 2.0), Point("a", 2.0)],                 # type: ignore[arg-type]
    Closeable: [Square(), Animal()], Shape: [Square(), Animal()], Square: [Square(), Dog()],
    numbers.Real: [1, 1.5, True, "1", 1j],
    datetime.date: [datetime.date(2024, 2, 29), "2024-02-29", "2024-13-01", 5],
    decimal.Decimal: [decimal.Decimal("1.10"), "1.10", 1, 1.5, "x"],
    uuid.UUID: [uuid.UUID(int = 7), "00000000-0000-0000-0000-000000000007", "nope"],
    PurePosixPath: [PurePosixPath("a/b"), "a/b", 1],
    TextIO: FILES, BinaryIO: FILES, IO: FILES,
    }
BY_MODEL: dict[str, list[Any]] = {
    "Email": ["ana@Example.com", " a@b.io\n", "nope", "a\n@b.com", 5], "Port": [80, 8080, 0, 70000, "443", 80.0, True],
    "Even": [2, 4, 3, "6", 2.0],
    }
ITEM_CONTAINERS = (list, Sequence, MutableSequence, Collection, deque, set, frozenset, Set)


def random_value(rng: random.Random, depth: int) -> Any:
    """Any value at all, at most ``depth`` levels of nesting."""
    if depth <= 0 or rng.random() < 0.45:
        return rng.choice(SCALARS)
    count = rng.choice([0, 1, 1, 2, 3])
    items = [random_value(rng, depth - 1) for _ in range(count)]
    kind = rng.randrange(14)
    if kind == 0: return items
    if kind == 1: return tuple(items)
    if kind in (2, 3):
        try:
            return set(items) if kind == 2 else frozenset(items)
        except TypeError:                                   # an unhashable item
            return items
    if kind in (4, 5):
        keys = ["a", "b", "1", 1, 2, " 1", 1.0, True, (1, 2), None]
        return {rng.choice(keys + [f"k{i}"]): item for i, item in enumerate(items)}
    if kind == 6: return deque(items, maxlen = rng.choice([None, 5]))
    if kind == 7: return MyList(items)
    if kind == 8: return range(count)
    if kind == 9: return {"a": items, "b": tuple(items)}
    if kind == 10: return [items, items]
    if kind == 11: return OrderedDict((f"k{i}", item) for i, item in enumerate(items))
    if kind == 12: return defaultdict(list, {f"k{i}": item for i, item in enumerate(items)})
    return (items, random_value(rng, depth - 1))


def value_for(rng: random.Random, annotation: Any, depth: int = 3) -> Any:
    """A value built from the annotation: usually valid, or one conversion away from valid."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if depth <= 0 or rng.random() < 0.06:
        return random_value(rng, 1)
    if annotation is Any: return rng.choice(SCALARS)
    if annotation is None: return None
    if isinstance(annotation, typing.ForwardRef): annotation = annotation.__forward_arg__
    if isinstance(annotation, str):
        return value_for(rng, {"int": int, "Animal": Animal, "list[int]": list[int], "OldJson": OldJson,
                               "dict[str, float] | None": dict[str, float] | None}[annotation], depth - 1)
    if isinstance(annotation, typing.TypeAliasType): return value_for(rng, annotation.__value__, depth - 1)
    if getattr(annotation, "__supertype__", None) is not None: return value_for(rng, annotation.__supertype__, depth)
    if isinstance(annotation, TypeVar):
        return value_for(rng, annotation.__bound__ or rng.choice(annotation.__constraints__ or (object,)), depth)
    if annotation is LiteralString: return rng.choice(["a", "", 5, b"x"])
    if origin is collections.ChainMap: return rng.choice(BY_CLASS[collections.ChainMap])
    if isinstance(annotation, type):
        return rng.choice(BY_MODEL.get(annotation.__name__) or BY_CLASS.get(annotation) or [random_value(rng, 1)])
    if origin in (Annotated, Final): return value_for(rng, args[0], depth)
    if origin is Literal: return rng.choice(list(args) + ["zz", 1.0])
    if origin in (Union, types.UnionType): return value_for(rng, rng.choice(args), depth)
    if origin is type: return rng.choice([int, str, bool, Dog, Animal, float])
    if origin is IO: return rng.choice(FILES)
    count = rng.choice([0, 1, 2, 2, 3, 6])
    if origin in ITEM_CONTAINERS:
        items = [value_for(rng, args[0], depth - 1) if args else random_value(rng, 1) for _ in range(count)]
        container: Any = rng.choice([list, list, tuple, MyList, deque, set, frozenset, "range", "keys"])
        if origin in (set, frozenset): container = rng.choice([set, frozenset, list])
        if origin is deque: container = rng.choice([deque, list])
        try:
            if container == "range": return range(count)
            if container == "keys": return dict.fromkeys(items).keys() if rng.random() < 0.5 else dict.fromkeys(items)
            return container(items)
        except TypeError:                                   # an unhashable item
            return items
    if origin is tuple:
        if not args: return tuple(random_value(rng, 1) for _ in range(count))
        if len(args) == 2 and args[1] is Ellipsis: return tuple(value_for(rng, args[0], depth - 1) for _ in range(count))
        items = [value_for(rng, arg, depth - 1) for arg in args]
        return tuple(items) if rng.random() < 0.85 else tuple(items + [1])
    if origin in (dict, Mapping, OrderedDict, defaultdict):
        entries: dict[Any, Any] = {}
        for i in range(count):
            key = value_for(rng, args[0], depth - 1) if args else f"k{i}"
            try:
                entries[key] = value_for(rng, args[1], depth - 1) if args else random_value(rng, 1)
            except TypeError:                               # an unhashable key
                entries[f"k{i}"] = 1
        if rng.random() < 0.1: return types.MappingProxyType(entries)
        if rng.random() < 0.1: return defaultdict(list, entries)
        return OrderedDict(entries) if rng.random() < 0.15 else entries
    return random_value(rng, 2)


# ═════════════════════════════════════════════════════════════════════════════
#  OUTCOMES
# ═════════════════════════════════════════════════════════════════════════════

ADDRESS = re.compile(r" at 0x[0-9a-f]+")
SHOWN_VALUE = re.compile(r"\(Value: .*?\)(?=\n|$)", re.S)


def show(value: Any) -> str:
    """A repr with each type spelled out, which doesn't depend on set order or on memory addresses."""
    if isinstance(value, (set, frozenset)):
        return f"{type(value).__name__}{{{', '.join(sorted(show(item) for item in value))}}}"
    if isinstance(value, (dict, types.MappingProxyType)):
        return f"{type(value).__name__}{{{', '.join(f'{show(k)}: {show(v)}' for k, v in value.items())}}}"
    if isinstance(value, type({}.keys())):
        return f"dict_keys[{', '.join(show(item) for item in value)}]"
    if isinstance(value, types.CoroutineType):
        value.close()                                       # never awaited: a call that only made the coroutine
        return "coroutine"
    if isinstance(value, (list, tuple, deque)):
        limit = f" maxlen={value.maxlen}" if isinstance(value, deque) else ""
        return f"{type(value).__name__}[{', '.join(show(item) for item in value)}{limit}]"
    return ADDRESS.sub("", f"{type(value).__name__}:{value!r}")


#* A message cuts a long annotation after 80 characters. The baseline is imported under a longer
#* name (``BASELINE_NAME``), so an annotation that names a type of the package is cut earlier there,
#* and the same message read differently in the two versions (12 of 300,000 values). Such an
#* annotation is compared by its first 40 characters, which the cut never reaches.
CUT_ANNOTATION = re.compile(r"(expected type: )(.{41,}?)(, got type | with (?:at least )?\d+ items?, got )")
#* "Cannot resolve annotation ..." cuts the annotation the same way, and the baseline's longer name
#* moves the cut there too (5 of 100,000 values differed by that alone).
CUT_UNRESOLVED = re.compile(r"(Cannot resolve annotation )(.{41,}?)( for )")


def _same_cut(found: re.Match[str]) -> str:
    start, shown, end = found.groups()
    return f"{start}{shown[:40]}[...]{end}" if "enforced" in shown else found.group()       # also a name the cut went through


def attempt(call: Callable[[], Any], keep: list[Any] | None = None, raw: bool = False) -> tuple[str, ...]:
    """
    ``("ok", value)`` or ``("error", exception type, problem kinds, message)`` for one call. A result
    is also appended to ``keep``. With ``raw``, ``call`` returns an outcome itself, which is passed on.
    """
    try:
        result = call()
        if raw:
            return result
        if keep is not None:
            keep.append(result)
        return ("ok", show(result))
    except Exception as error:
        kinds = ",".join(f"{p.kind}@{p.parameter}" for p in getattr(error, "problems", ()))
        return ("error", type(error).__name__, kinds, message_text(error))


def message_text(error: Any) -> str:
    """The message of an error or a warning, without what differs from run to run."""
    text = CUT_ANNOTATION.sub(_same_cut, ADDRESS.sub("", str(error)).replace(BASELINE_NAME, "enforced"))
    text = CUT_UNRESOLVED.sub(_same_cut, text)
    return SHOWN_VALUE.sub("(Value: ...)", text)            # a converted set can list its items in another order


WHOLE = 10 ** 9                                             # a width for ``brief`` that cuts nothing


def brief(outcome: tuple[str, ...], width: int = 240) -> str:
    """One line for an outcome."""
    if outcome[0] == "ok":
        text = f"ok {outcome[1]}"
    else:
        text = f"{outcome[1]}: " + " / ".join(line.strip() for line in outcome[3].splitlines())
    return text if len(text) <= width else text[:width - 3] + "..."


# ═════════════════════════════════════════════════════════════════════════════
#  WAYS TO USE AN ANNOTATION
# ═════════════════════════════════════════════════════════════════════════════
#* Each one returns ``check(value) -> outcome``. Where the value isn't part of the definition, the
#* checked function or class is made once and used for every value of the case: the first value takes
#* the first-call path, the others the generated wrapper. Where it is (a default), each value gets
#* its own definition and is tried twice, for the same reason.

Check = Callable[[Any], tuple[str, ...]]


def function(package: types.ModuleType, f: Callable[..., Any], annotations: dict[str, Any], **options: Any) -> Callable[..., Any]:
    """``f`` with these annotations, type-checked by ``package``."""
    f.__annotations__ = annotations
    return package.typecheck(f, **options)


def as_argument(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def f(x): return x
    checked = function(package, f, {"x": annotation}, **options)

    def check(value: Any) -> tuple[str, ...]:
        kept: list[Any] = []
        outcome = attempt(lambda: checked(value), kept)
        #* What a call returns is a valid value: passed in again, it has to come back as it is.
        if kept and (again := attempt(lambda: checked(kept[0]))) != outcome:
            return ("error", "Unstable", "", f"result: {brief(outcome, 120)} / the result passed in again: {brief(again, 120)}")
        return outcome
    return check


def as_keyword(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def f(x): return x
    checked = function(package, f, {"x": annotation}, **options)
    return lambda value: attempt(lambda: checked(x = value))


def as_varargs(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def f(*xs): return xs
    checked = function(package, f, {"xs": annotation}, **options)
    return lambda value: attempt(lambda: checked(value, value))


def as_kwargs(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def f(**named): return named
    checked = function(package, f, {"named": annotation}, **options)
    return lambda value: attempt(lambda: checked(a = value, b = value))


def as_binding(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """Calls that bind in every way, right and wrong: too few arguments, too many, unknown or repeated names."""
    def f(a, b = 0, *, c = "c"): return a, b, c
    checked = function(package, f, {"a": annotation, "b": int, "c": str}, **options)
    shapes: list[Callable[[Any], Any]] = [
        lambda v: checked(), lambda v: checked(v, 1, 2), lambda v: checked(v, c = 1), lambda v: checked(b = v),
        lambda v: checked(v, v), lambda v: checked(v, d = v), lambda v: checked(a = v, b = 2, c = "z"),
        lambda v: checked(v, a = v), lambda v: checked(c = "z"), lambda v: checked(1, v, c = v),
        ]
    calls = iter(range(10 ** 9))                            # the same sequence of shapes in both versions
    return lambda value: attempt(lambda: shapes[next(calls) % len(shapes)](value))


def enforcer(package: types.ModuleType) -> Callable[..., Any] | None:
    """The class decorator: ``enforce``, or ``enforced`` in a version from before it was renamed. None before the split."""
    return getattr(package, "enforce", None) or getattr(package, "enforced", None)


def class_decorator(package: types.ModuleType) -> Callable[..., Any]:
    """``enforce``, or ``typecheck`` in a version from before the two were split: it took classes too."""
    return enforcer(package) or package.typecheck


def _exempt(package: types.ModuleType) -> Callable[..., Any]:
    """``enforce.exempt``, or ``skip_typecheck`` in a version from before it was renamed (2026-10-15)."""
    return getattr(enforcer(package), "exempt", None) or package.skip_typecheck


def as_method(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """A class decorated with ``enforce``: its ``__init__``, a method, a static method and a class method."""
    def __init__(self, x): self.x = x
    def method(self, x): return x
    def static(x): return x
    def make(cls, x): return x
    for f in (__init__, method, static, make):
        f.__annotations__ = {"x": annotation}
    method.__annotations__["return"] = annotation
    body = {"__init__": __init__, "method": method, "static": staticmethod(static), "make": classmethod(make)}
    cls = class_decorator(package)(type("Fuzzed", (), body), check_return = True, **options)

    def use(value: Any) -> Any:
        instance = cls(value)
        return instance.x, instance.method(value), cls.static(value), cls.make(value)
    return lambda value: attempt(lambda: use(value))


def as_enforced_base(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A class derived from ``Enforced``, and a subclass of it that isn't decorated, against the same
    class under ``enforce``: every call must give what it gives there. The outcome is the decorated
    class's, so a version without ``Enforced`` compares equal; where there is one, a difference is
    reported as unstable.
    """
    def body() -> dict[str, Any]:
        def __init__(self, x): self.x = x
        def method(self, x): return x
        def static(x): return x
        def make(cls, x): return x
        for f in (__init__, method, static, make):
            f.__annotations__ = {"x": annotation}
        method.__annotations__["return"] = annotation
        return {"__init__": __init__, "method": method, "static": staticmethod(static), "make": classmethod(make)}

    plain = class_decorator(package)(type("Fuzzed", (), body()), check_return = True, **options)
    derived = None
    if getattr(package, "Enforced", None) is not None:
        base = type("Fuzzed", (package.Enforced,), body(), check_return = True, **options)
        derived = type("Below", (base,), {})            # checked through its base, undecorated

    def use(cls: Any, value: Any) -> Any:
        instance = cls(value)
        return instance.x, instance.method(value), cls.static(value), cls.make(value)

    def check(value: Any) -> tuple[str, ...]:
        outcome = attempt(lambda: use(plain, value))
        if derived is not None and (theirs := attempt(lambda: use(derived, value))) != outcome:
            return ("error", "Unstable", "", f"under enforce: {brief(outcome, 120)} / from Enforced: {brief(theirs, 120)}")
        return outcome
    return check


def as_dataclass_method(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    The methods of a dataclass against the same methods of a class under ``enforce``: a method, a
    static method and a class method must give, call for call, what they give there. The outcome
    is the plain class's, so a version whose dataclass doesn't check its methods compares equal;
    where it does (``check_methods``), a difference between the two is reported as unstable.
    """
    def members() -> dict[str, Any]:
        def method(self, x): return x
        def static(x): return x
        def make(cls, x): return x
        for f in (method, static, make):
            f.__annotations__ = {"x": annotation, "return": annotation}
        return {"method": method, "static": staticmethod(static), "make": classmethod(make)}

    plain = class_decorator(package)(type("Fuzzed", (), members()), check_return = True, **options)
    checked = None
    if "check_methods" in inspect.signature(package.dataclass).parameters:
        checked = package.dataclass(type("Fuzzed", (), {**members(), "__annotations__": {}}), check_return = True, **options, **extra)

    def use(cls: Any, value: Any) -> Any:
        return cls().method(value), cls.static(value), cls.make(value)

    def check(value: Any) -> tuple[str, ...]:
        outcome = attempt(lambda: use(plain, value))
        if checked is not None and (theirs := attempt(lambda: use(checked, value))) != outcome:
            return ("error", "Unstable", "", f"under enforce: {brief(outcome, 120)} / in a dataclass: {brief(theirs, 120)}")
        return outcome
    return check


def as_own_options(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A method that carries its own ``typecheck`` in a class ``enforce`` with the opposite
    ``allow_subclass`` and no return check. Its own options stand, so it must give exactly what
    the same method gives in a class enforced with these options. Next to it, a method marked
    ``enforce.exempt`` must hand every value back untouched. (A version from before ``enforce``
    is only asked for the class decorated as a whole.)
    """
    def method() -> Callable[..., Any]:
        def method(self, x): return x
        method.__annotations__ = {"x": annotation, "return": annotation}
        return method

    whole = class_decorator(package)(type("Fuzzed", (), {"method": method()}), check_return = True, **options)
    if enforcer(package) is None:
        return lambda value: attempt(lambda: whole().method(value))
    body = {"method": package.typecheck(method(), check_return = True, **options), "left": _exempt(package)(method())}
    mixed = class_decorator(package)(type("Fuzzed", (), body), **{**options, "allow_subclass": not options["allow_subclass"]})

    def check(value: Any) -> tuple[str, ...]:
        outcome, own = attempt(lambda: whole().method(value)), attempt(lambda: mixed().method(value))
        if outcome != own:
            return ("error", "Unstable", "", f"the class's options: {brief(outcome, 120)} / its own, the same: {brief(own, 120)}")
        left = attempt(lambda: mixed().left(value) is value)
        if left != ("ok", "bool:True"):
            return ("error", "Unstable", "", f"a method marked enforce.exempt: {brief(left, 120)}")
        return outcome
    return check


_CHECKS_SPECIAL: dict[str, bool] = {}
FUZZED_LABEL = re.compile(r"<Method Fuzzed\.\w+>|<Class Fuzzed>")


def checks_special_methods(package: types.ModuleType) -> bool:
    """Whether this version's ``enforce`` checks ``__call__`` and the other special methods a caller hands values to."""
    if package.__name__ not in _CHECKS_SPECIAL:
        def __call__(self, x): return x
        __call__.__annotations__ = {"x": int}
        enforce = enforcer(package)
        _CHECKS_SPECIAL[package.__name__] = enforce is not None and hasattr(
            vars(enforce(type("Probe", (), {"__call__": __call__})))["__call__"], "__wrapped__")
    return _CHECKS_SPECIAL[package.__name__]


def as_special_method(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    The special methods of an enforced class that take a caller's values: ``__call__`` and
    ``__getitem__`` (argument and return value), ``__setitem__``, ``__contains__`` and ``__new__``
    (argument). Each must give what an ordinary method with the same annotations gives, the name in
    the message apart. (A version from before these were checked is only asked for the ordinary methods.)
    """
    def echo(self, x): return x
    def put(self, x): return x
    def __call__(self, x): return x
    def __getitem__(self, x): return x
    def __setitem__(self, key, x): self.kept = x
    def __contains__(self, x): return True
    def __new__(cls, x):
        self = object.__new__(cls)
        self.made = x
        return self
    for f in (put, __setitem__, __contains__, __new__):
        f.__annotations__ = {"x": annotation}
    for f in (echo, __call__, __getitem__):
        f.__annotations__ = {"x": annotation, "return": annotation}
    special = {"__call__": __call__, "__getitem__": __getitem__, "__setitem__": __setitem__, "__contains__": __contains__}
    cls = class_decorator(package)(type("Fuzzed", (), {"echo": echo, "put": put, **special}), check_return = True, **options)
    if not checks_special_methods(package):
        return lambda value: attempt(lambda: cls().echo(value))
    made = class_decorator(package)(type("Fuzzed", (), {"__new__": __new__}), check_return = True, **options)

    def assigned(value: Any) -> Any:
        instance = cls()
        instance[0] = value
        return instance.kept

    def same(outcome: tuple[str, ...]) -> tuple[str, ...]:
        return outcome[:3] + (FUZZED_LABEL.sub("<Fuzzed>", outcome[3]),) if outcome[0] == "error" else outcome

    def check(value: Any) -> tuple[str, ...]:
        outcome, argument = attempt(lambda: cls().echo(value)), attempt(lambda: cls().put(value))
        found = {
            "__call__": (outcome, attempt(lambda: cls()(value))),
            "__getitem__": (outcome, attempt(lambda: cls()[value])),
            "__setitem__": (argument, attempt(lambda: assigned(value))),
            "__new__": (argument, attempt(lambda: made(value).made)),
            #* ``in`` answers with a bool: the same error, or True where the ordinary method accepts.
            "__contains__": (argument if argument[0] == "error" else ("ok", "bool:True"), attempt(lambda: value in cls())),
            }
        for name, (ordinary, through) in found.items():
            if same(ordinary) != same(through):
                return ("error", "Unstable", "", f"an ordinary method: {brief(ordinary, 120)} / {name}: {brief(through, 120)}")
        return outcome
    return check


_SUPPORTS: dict[tuple[str, str], bool] = {}


def supports(package: types.ModuleType, what: str) -> bool:
    """
    Whether this version checks ``**kwargs: Unpack[TypedDict]`` ("typed kwargs"), ``*args: *tuple[...]``
    ("tuple args") or an object with ``__call__`` ("callable object"), and whether ``Self`` is the
    class a method is called on ("self"). Before they were checked they were accepted as they
    came, so a baseline without them is only asked for the plain function.
    """
    key = (package.__name__, what)
    if key not in _SUPPORTS:
        class Keys(TypedDict):
            x: int

        class Called:
            def __call__(self, x: int) -> Any: return x

        def kwargs(**named: typing.Unpack[Keys]) -> Any: return named
        def args(*found: *tuple[int]) -> Any: return found
        def call(x: int) -> Any: return x
        def base_for_self(self) -> typing.Self: return made_as[0]()
        made_as = [class_decorator(package)(type("Base", (), {"clone": base_for_self}), check_return = True)]
        probe = {"typed kwargs": lambda: package.typecheck(kwargs)(x = "no"), "tuple args": lambda: package.typecheck(args)("no"),
                 "callable object": lambda: package.typecheck(Called())("no"),
                 "self": lambda: type("Child", (made_as[0],), {})().clone(),      # a Base where Self is the Child
                 "function call": lambda: package.typecheck_function(call, (1,), check_return = True) + ""}[what]
        #* "function call": typecheck_function that checks and calls (it returns the 1; an older one returned the arguments).
        _SUPPORTS[key] = attempt(probe)[:2] == ("error", "TypeCheckerError" if what != "function call" else "TypeError") \
            and (what != "function call" or "int" in attempt(probe)[3])
    return _SUPPORTS[key]


def as_typed_kwargs(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    ``**kwargs: Unpack[TypedDict]`` with one key of this annotation: the keyword must give what an
    ordinary keyword-only parameter of the same name and annotation gives.
    """
    def plain(*, x): return x
    checked = function(package, plain, {"x": annotation}, **options)
    try:
        Keys = TypedDict("Keys", {"x": annotation})         # type: ignore[misc]
    except TypeError:                                       # Final[int]: typing itself refuses it as a key's type
        Keys = None
    if Keys is None or not supports(package, "typed kwargs"):
        return lambda value: attempt(lambda: checked(x = value))
    def f(**named): return named["x"]
    f.__annotations__ = {"named": typing.Unpack[Keys]}
    unpacked = package.typecheck(f, **options)

    def check(value: Any) -> tuple[str, ...]:
        outcome, through = attempt(lambda: checked(x = value)), attempt(lambda: unpacked(x = value))
        if _labelled(outcome) != _labelled(through):
            return ("error", "Unstable", "", f"a keyword: {brief(outcome, 120)} / Unpack[TypedDict]: {brief(through, 120)}")
        return outcome
    return check


def as_tuple_args(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    ``*args: *tuple[annotation, int]``: the first extra argument must give what a positional
    parameter of this annotation gives (the place it is reported at apart).
    """
    def plain(x, n = 0, /): return x
    checked = function(package, plain, {"x": annotation, "n": int}, **options)
    if not supports(package, "tuple args"):
        return lambda value: attempt(lambda: checked(value, 1))
    def f(*found): return found[0]
    f.__annotations__ = {"found": typing.Unpack[tuple[annotation, int]]}        # what *tuple[...] is at runtime
    unpacked = package.typecheck(f, **options)

    def check(value: Any) -> tuple[str, ...]:
        outcome, through = attempt(lambda: checked(value, 1)), attempt(lambda: unpacked(value, 1))
        if outcome[:2] != through[:2] or (outcome[0] == "ok" and outcome != through):
            return ("error", "Unstable", "", f"a parameter: {brief(outcome, 120)} / *tuple[...]: {brief(through, 120)}")
        return outcome
    return check


def as_callable_object(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """An object with ``__call__``, decorated as an object: it must give what the plain function gives."""
    def plain(x): return x
    checked = function(package, plain, {"x": annotation, "return": annotation}, check_return = True, **options)
    if not supports(package, "callable object"):
        return lambda value: attempt(lambda: checked(value))

    def __call__(self, x): return x
    __call__.__annotations__ = {"x": annotation, "return": annotation}
    called = package.typecheck(type("Fuzzed", (), {"__call__": __call__})(), check_return = True, **options)

    def check(value: Any) -> tuple[str, ...]:
        outcome, through = attempt(lambda: checked(value)), attempt(lambda: called(value))
        if _labelled(outcome) != _labelled(through):
            return ("error", "Unstable", "", f"a function: {brief(outcome, 120)} / an object with __call__: {brief(through, 120)}")
        return outcome
    return check


def as_function_call(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    ``typecheck_function``, the decorator without the decorator: it must give what the decorated
    function gives, value and error. A version from before it worked this way is asked for the
    decorated function alone.
    """
    def plain(x, n = 0): return x
    checked = function(package, plain, {"x": annotation, "n": int, "return": annotation}, check_return = True, **options)
    if not supports(package, "function call"):
        return lambda value: attempt(lambda: checked(value))

    def called(x, n = 0): return x
    called.__name__ = "plain"
    called.__annotations__ = {"x": annotation, "n": int, "return": annotation}

    def check(value: Any) -> tuple[str, ...]:
        outcome = attempt(lambda: checked(value))
        through = attempt(lambda: package.typecheck_function(called, (value,), check_return = True, **options))
        if _labelled(outcome) != _labelled(through):
            return ("error", "Unstable", "", f"decorated: {brief(outcome, 120)} / typecheck_function: {brief(through, 120)}")
        return outcome
    return check


def as_class_call(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """``enforce_class`` on a class that is already defined: it must give what the class decorator gives."""
    def body() -> dict[str, Any]:
        def __init__(self, x, n = 0): self.x = x
        def method(self, x): return x
        __init__.__annotations__ = {"x": annotation, "n": int}
        method.__annotations__ = {"x": annotation, "return": annotation}
        return {"__init__": __init__, "method": method}

    cls = class_decorator(package)(type("Fuzzed", (), body()), check_return = True, **options)
    use = lambda made, value: (made(value).x, made(value).method(value))
    if not supports(package, "function call"):
        return lambda value: attempt(lambda: use(cls, value))
    later = package.enforce_class(type("Fuzzed", (), body()), check_return = True, **options)

    def check(value: Any) -> tuple[str, ...]:
        outcome, through = attempt(lambda: use(cls, value)), attempt(lambda: use(later, value))
        if outcome != through:
            return ("error", "Unstable", "", f"enforce: {brief(outcome, 120)} / enforce_class: {brief(through, 120)}")
        return outcome
    return check


def settled(value: Any) -> bool:
    """A check that any value can be given: a verdict that depends on the value alone."""
    return len(show(value)) % 4 != 0


def as_marked_check(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A check written with the marker, ``Annotated[T, Check(fn)]``: it must give what the short form
    ``Annotated[T, fn]`` gives, value and error. A version from before the marker is asked for the
    short form alone.

    The check sits on a parameter of its own, which takes anything and converts nothing: the
    verdict then depends on the value as it was passed, whatever the options make of it for ``x``.
    """
    def short(x, y): return x
    checked = function(package, short, {"x": annotation, "y": Annotated[object, settled], "return": annotation},
                       check_return = True, **options)
    marker = getattr(package, "Check", None)
    if marker is None:
        return lambda value: attempt(lambda: checked(value, value))

    def marked(x, y): return x
    marked.__name__ = "short"
    through = function(package, marked, {"x": annotation, "y": Annotated[object, marker(settled)], "return": annotation},
                       check_return = True, **options)

    def check(value: Any) -> tuple[str, ...]:
        outcome, with_marker = attempt(lambda: checked(value, value)), attempt(lambda: through(value, value))
        if outcome != with_marker:
            return ("error", "Unstable", "", f"the short form: {brief(outcome, 120)} / Check(fn): {brief(with_marker, 120)}")
        return outcome
    return check


def as_property(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A property of a class given to ``enforce``: what is assigned and what the getter returns must
    be checked as the argument and the return value of a plain function are. A version from before
    properties were checked is asked for the plain function alone.
    """
    def plain(x): return x
    checked = function(package, plain, {"x": annotation, "return": annotation}, check_return = True, **options)

    def get(self): return self.kept
    def put(self, x): self.kept = x
    get.__annotations__, put.__annotations__ = {"return": annotation}, {"x": annotation}
    get.__name__ = put.__name__ = "plain"
    cls = class_decorator(package)(type("Fuzzed", (), {"value": property(get, put)}), check_return = True, **options)
    probe = cls()
    probe.kept = None
    if "_pv_bootstrap" not in getattr(vars(cls)["value"].fset, "__globals__", ()):
        return lambda value: attempt(lambda: checked(value))

    def through(value: Any) -> Any:
        one = cls()
        one.value = value
        return one.value

    def check(value: Any) -> tuple[str, ...]:
        outcome, by_property = attempt(lambda: checked(value)), attempt(lambda: through(value))
        if _labelled(outcome) != _labelled(by_property):
            return ("error", "Unstable", "", f"a function: {brief(outcome, 120)} / a property: {brief(by_property, 120)}")
        return outcome
    return check


def as_self(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A method that takes ``Self`` next to the annotation, called on an instance of a subclass. The
    annotation must be checked as in a plain function, whatever class the call is made on, and
    ``Self`` must be that class: an instance of the base class is refused where the subclass is
    asked for. (A version in which ``Self`` was the class that defines the method accepted it.)
    """
    def plain(x): return x
    checked = function(package, plain, {"x": annotation, "return": annotation}, check_return = True, **options)

    def method(self, x, other = None, *more): return x
    def twin(self, x, other): return other
    method.__annotations__ = {"x": annotation, "other": typing.Self | None, "more": typing.Self, "return": annotation}
    twin.__annotations__ = {"x": annotation, "other": typing.Self, "return": typing.Self}
    base = class_decorator(package)(type("Fuzzed", (), {"method": method, "twin": twin}), check_return = True, **options)
    child = type("Child", (base,), {})
    follows = supports(package, "self")

    def check(value: Any) -> tuple[str, ...]:
        outcome = attempt(lambda: checked(value))
        for cls in (base, child, child):                    # the class itself, a subclass, the subclass once compiled
            one = cls()
            for how, call in (("Self in an annotation", lambda: one.method(value, one, one)),
                              ("Self alone", lambda: (one.twin(value, one), one.method(value))[1])):
                through = attempt(call)
                if _labelled(outcome) != _labelled(through):
                    return ("error", "Unstable", "", f"a function: {brief(outcome, 120)} / a method of {cls.__name__}, {how}: {brief(through, 120)}")
        if follows and outcome[0] == "ok":
            for how, call in (("Self | None", lambda: child().method(value, base())), ("*args: Self", lambda: child().method(value, None, base())),
                              ("Self", lambda: child().twin(value, base()))):
                if attempt(call)[:2] != ("error", "TypeCheckerError"):
                    return ("error", "Unstable", "", f"an instance of the base class was accepted for {how} in a call on the subclass")
        return outcome
    return check


ANY_LABEL = re.compile(r"<(Function|Callable|Method|Class) [\w.]+>")


def _labelled(outcome: tuple[str, ...]) -> tuple[str, ...]:
    """``outcome`` without the name of what was called, which differs between two ways to write the same check."""
    return outcome[:3] + (ANY_LABEL.sub("<it>", outcome[3]),) if outcome[0] == "error" else outcome


def as_member(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """``typecheck`` written above ``@classmethod``, ``@staticmethod`` and ``@property`` (getter and setter)."""
    def make(cls, x): return x
    def static(x): return x
    def get(self): return self._x
    def put(self, x): self._x = x
    for f in (make, static, put):
        f.__annotations__ = {"x": annotation}
    get.__annotations__ = {"return": annotation}
    above = lambda member: package.typecheck(member, check_return = True, **options)
    cls = type("Fuzzed", (), {"make": above(classmethod(make)), "static": above(staticmethod(static)),
                              "x": above(property(get, put))})

    def use(value: Any) -> Any:
        instance = cls()
        instance.x = value
        return instance.x, cls.make(value), instance.make(value), cls.static(value), instance.static(value)
    return lambda value: attempt(lambda: use(value))


def as_coroutine(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    async def f(x): return x
    checked = function(package, f, {"x": annotation, "return": annotation}, check_return = True, **options)

    def drive(value: Any) -> Any:
        coroutine = checked(value)
        try:
            coroutine.send(None)
        except StopIteration as done:
            return done.value
        raise RuntimeError("the coroutine did not finish")
    return lambda value: attempt(lambda: drive(value))


def as_return(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def f(x): return x
    checked = function(package, f, {"return": annotation}, check_return = True, **options)
    return lambda value: attempt(lambda: checked(value))


def as_default(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    def check(value: Any) -> tuple[str, ...]:
        def f(x = value): return x
        f.__annotations__ = {"x": annotation}
        checked = package.typecheck(f, **options)
        return twice(checked)
    return check


def as_record(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    #* One name for every case: the cache of typecheck_record is part of what is compared.
    #* (A version from before it was renamed has it as typecheck_from_dict.)
    checked = getattr(package, "typecheck_record", None) or package.typecheck_from_dict

    def check(value: Any) -> tuple[str, ...]:
        spec = {"object_name": "fuzzed", "record": {"x": annotation}, "kwargs": {"x": value}, **options}
        return attempt(lambda: checked(spec)[1]["x"])
    return check


def as_field(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    cls = package.dataclass(type("Fuzzed", (), {"__annotations__": {"x": annotation}}), **options, **extra)

    def use(value: Any) -> Any:
        instance = cls(value)
        built = instance.x
        if extra.get("frozen"):
            return (built,)
        instance.x = value
        return built, instance.x
    return lambda value: attempt(lambda: use(value))


def as_inherited_field(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
    """
    A field declared in a checked dataclass and used through a checked subclass, whose base has
    the opposite ``allow_subclass``. Each class follows its own options, so the subclass must give
    exactly what a flat class with the same two fields gives.
    """
    fields = {"__annotations__": {"x": annotation}}
    base = package.dataclass(type("Base", (), dict(fields)), **{**options, "allow_subclass": not options["allow_subclass"]}, **extra)
    own = {"__annotations__": {"y": int}, "y": 0}
    child = package.dataclass(type("Fuzzed", (base,), dict(own)), **options, **extra)
    flat = package.dataclass(type("Fuzzed", (), {"__annotations__": {"x": annotation, "y": int}, "y": 0}), **options, **extra)

    def use(cls: type, value: Any) -> Any:
        instance = cls(value)
        built = instance.x
        if extra.get("frozen"):
            return (built,)
        instance.x = value
        return built, instance.x

    def check(value: Any) -> tuple[str, ...]:
        outcome, alone = attempt(lambda: use(child, value)), attempt(lambda: use(flat, value))
        if outcome != alone:
            return ("error", "Unstable", "", f"subclass: {brief(outcome, 120)} / the flat class: {brief(alone, 120)}")
        return outcome
    return check


def as_field_default(how: str) -> Callable[..., Check]:
    """
    A dataclass field whose default is the value: plain, from a factory, of an ``init=False`` field,
    or in a class without a generated ``__init__`` (``dataclass(init=False)``).
    """
    def make(package: types.ModuleType, annotation: Any, options: dict[str, Any], extra: dict[str, Any]) -> Check:
        def check(value: Any) -> tuple[str, ...]:
            default: Any = value
            if how == "factory":
                default = dataclasses.field(default_factory = lambda: value)
            elif how == "hidden":
                default = dataclasses.field(init = False, default = value)

            def define() -> type:
                return package.dataclass(type("Fuzzed", (), {"__annotations__": {"x": annotation}, "x": default}),
                                         init = how != "class", **options, **extra)
            try:
                cls = define()
            except Exception:                               # e.g. a mutable default: dataclasses refuses the class
                return attempt(define)
            return twice(lambda: cls().x)
        return check
    return make


def twice(call: Callable[[], Any]) -> tuple[str, ...]:
    """The outcome of ``call``; when a second call disagrees with the first, both."""
    first, second = attempt(call), attempt(call)
    if first == second:
        return first
    return ("error", "Unstable", "", f"first call: {brief(first, 120)} / second call: {brief(second, 120)}")


USES: dict[str, Callable[..., Check]] = {
    "argument": as_argument,
    "keyword": as_keyword,
    "varargs": as_varargs,
    "kwargs": as_kwargs,
    "binding": as_binding,
    "return": as_return,
    "method": as_method,
    "own options": as_own_options,
    "special method": as_special_method,
    "typed kwargs": as_typed_kwargs,
    "tuple args": as_tuple_args,
    "callable object": as_callable_object,
    "member": as_member,
    "coroutine": as_coroutine,
    "default": as_default,
    "record": as_record,
    "field": as_field,
    "inherited field": as_inherited_field,
    "field default": as_field_default("plain"),
    "factory default": as_field_default("factory"),
    "hidden default": as_field_default("hidden"),
    "class default": as_field_default("class"),
    "function call": as_function_call,
    "class call": as_class_call,
    "marked check": as_marked_check,
    "self": as_self,
    "property": as_property,
    "dataclass method": as_dataclass_method,
    "enforced base": as_enforced_base,
    }
USE_WEIGHTS = [6, 2, 1, 1, 2, 3, 2, 1, 1, 1, 1, 1, 1, 2, 2, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
DATACLASS_USES = ("field", "inherited field", "field default", "factory default", "hidden default", "class default",
                  "dataclass method")


# ═════════════════════════════════════════════════════════════════════════════
#  THE RUN
# ═════════════════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class Difference:
    zone: str
    use: str
    options: str
    annotation: str
    value: str
    before: tuple[str, ...]
    after: tuple[str, ...]

    @property
    def line(self) -> str:
        """
        Everything on one line, the parts separated by " ; ": what ``--expect`` is searched in. The
        outcomes are whole here, not cut as they are when printed: an intended difference may be in
        the sixth problem of a long message.
        """
        return (f"{self.zone} ; {self.use} ; {self.options} ; {self.annotation} <- {self.value} ; "
                f"baseline: {brief(self.before, WHOLE)} ; now: {brief(self.after, WHOLE)}")

    @property
    def group(self) -> str:
        return f"{self.zone} ; {self.use} ; {self.before[0]} -> {self.after[0]}"

    def render(self) -> str:
        value = self.value if len(self.value) <= 160 else self.value[:157] + "..."
        return (f"      {self.zone} ; {self.use} ; {self.options}\n"
                f"      {self.annotation} <- {value}\n"
                f"         baseline: {brief(self.before)}\n"
                f"         now:      {brief(self.after)}")


def describe(options: dict[str, Any], extra: dict[str, Any]) -> str:
    """Only the options that differ from the defaults, e.g. ``allow_subclass=False coerce deep frozen``."""
    words = []
    if not options["allow_subclass"]: words.append("allow_subclass=False")
    if not options["convert"]: words.append("convert=False")
    words += [name for name in ("coerce", "deep") if options.get(name)]
    words += [name if on else f"{name}=False" for name, on in extra.items()]
    return " ".join(words) or "defaults"


def random_case(rng: random.Random, index: int) -> tuple[str, str, dict[str, Any], dict[str, Any], int, bool]:
    """One case: ``(zone, use, options, dataclass options, depth of the annotation, with validated types)``."""
    core = index % 2 == 0                                   # half the cases in each zone
    deep = not core and rng.random() < 0.8
    validated = not core and (not deep or rng.random() < 0.5)
    options = {"allow_subclass": rng.random() < 0.75, "convert": rng.random() < 0.8, "coerce": rng.random() < 0.35}
    if deep:
        options["deep"] = True
    use = rng.choices(list(USES), USE_WEIGHTS)[0]
    extra: dict[str, Any] = {}
    if use in DATACLASS_USES:
        if rng.random() < 0.25: extra["frozen"] = True
        if rng.random() < 0.25: extra["slots"] = True
        if rng.random() < 0.15: extra["check_assignment"] = False
    return "core" if core else "extended", use, options, extra, rng.choice([1, 2, 2, 3]), validated


def random_input(rng: random.Random, annotation: Any) -> Any:
    """A value for one check: built from the annotation most of the time, anything at all otherwise."""
    return value_for(rng, annotation) if rng.random() < 0.7 else random_value(rng, rng.choice([0, 1, 2, 2, 3]))


#* What --ignore-type-names leaves out of a message: how the expected and the actual type are written.
TYPE_NAMES = re.compile(r"expected type:? .*?, got type .*? \(Value: \.\.\.\)")


def without_type_names(outcome: tuple[str, ...]) -> tuple[str, ...]:
    """An error outcome with the types in its message left out: what must still agree when only their wording changed."""
    if outcome[0] != "error":
        return outcome
    return outcome[:3] + (TYPE_NAMES.sub("expected <type>, got <type> (Value: ...)", outcome[3]),)


#* Main function for running fuzz tests
def run(old: types.ModuleType, new: types.ModuleType, cases: int, seed: int, expected: list[re.Pattern[str]],
        ignore_type_names: bool = False,
        ) -> tuple[collections.Counter, dict[str, list[Difference]], dict[str, list[Difference]]]:
    """
    Compare ``old`` and ``new`` on ``cases`` values. Returns the counts and the differences, expected and not.
    With ``ignore_type_names``, two errors that only differ in how a type is named count as identical
    (counted apart, as "renamed").
    """
    rng = random.Random(seed)
    kits = (validated_types(old), validated_types(new))
    counts: collections.Counter = collections.Counter()
    explained: dict[str, list[Difference]] = collections.defaultdict(list)
    unexplained: dict[str, list[Difference]] = collections.defaultdict(list)

    for index in range(-(-cases // VALUES_PER_CASE)):
        zone, use, options, extra, depth, validated = random_case(rng, index)
        #* The same annotation for each version: the same random choices, from that version's types.
        state = rng.getstate()
        old_annotation = random_annotation(rng, depth, kits[0] if validated else None)
        rng.setstate(state)
        new_annotation = random_annotation(rng, depth, kits[1] if validated else None)
        try:
            checks = (USES[use](old, old_annotation, options, extra), USES[use](new, new_annotation, options, extra))
        except Exception as error:                          # neither version got as far as a check
            counts[zone, "skipped"] += 1
            counts["skipped", type(error).__name__] += 1
            continue

        for _ in range(VALUES_PER_CASE):
            value = random_input(rng, new_annotation)
            shown = show(value)
            before = checks[0](value)
            after = checks[1](value) if show(value) == shown else ("error", "Skipped", "", "the baseline changed its input")
            if show(value) != shown and after[1:2] != ("Skipped",):
                after = ("error", "ChangedInput", "", f"the value passed in is now {show(value)}")
            counts[zone, "comparisons"] += 1
            if before == after and after[1:2] != ("Unstable",):     # two calls that disagree are a finding in any version
                counts[zone, "identical"] += 1
                continue
            if ignore_type_names and after[1:2] != ("Unstable",) and without_type_names(before) == without_type_names(after):
                counts[zone, "identical"] += 1
                counts[zone, "renamed"] += 1
                continue
            difference = Difference(zone, use, describe(options, extra), repr(new_annotation), shown, before, after)
            pattern = next((p for p in expected if p.search(difference.line)), None)
            if pattern is None:
                counts[zone, "unexplained"] += 1
                unexplained[difference.group].append(difference)
            else:
                counts[zone, "expected"] += 1
                explained[pattern.pattern].append(difference)
    return counts, explained, unexplained


# ═════════════════════════════════════════════════════════════════════════════
#  PROPERTIES: what must hold in any version, checked on the working tree alone
# ═════════════════════════════════════════════════════════════════════════════

#* Errors a use is allowed to end with besides TypeCheckerError: each comes from Python itself.
OWN_ERRORS = ("TypeCheckerError", "Unstable")
PYTHON_ERRORS: list[tuple[str, str]] = [
    ("ValueError", "mutable default"),                      # dataclasses refuses a list, dict or set as a default
    ("FrozenInstanceError", ""),
    ("AttributeError", "object has no attribute 'x'"),      # dataclass(init=False, slots=True): nothing sets the field
    ]

WARNS = "on_error='warn': a warning where 'raise' raises, the same result where it doesn't"

#* A looser setting never rejects what the stricter one accepts: (name, applies to these options, the looser options).
LOOSER: list[tuple[str, Callable[[dict[str, Any]], bool], dict[str, Any]]] = [
    ("accepted with deep=True, rejected without", lambda o: bool(o.get("deep")), {"deep": False}),
    ("accepted with allow_subclass=False, rejected without", lambda o: not o["allow_subclass"], {"allow_subclass": True}),
    ("accepted without coerce, rejected with it", lambda o: not o["coerce"], {"coerce": True}),
    ("accepted without convert, rejected with it", lambda o: not o["convert"] and not o["coerce"], {"convert": True}),
    ]


def run_properties(package: types.ModuleType, cases: int, seed: int) -> tuple[collections.Counter, dict[str, list[str]]]:
    """
    Check the properties on ``cases`` values. Returns how often each was checked and, for those
    that broke, the cases as text.
    """
    rng = random.Random(seed)
    kit = validated_types(package)
    counts: collections.Counter = collections.Counter()
    broken: dict[str, list[str]] = collections.defaultdict(list)

    def outcome(use: str, annotation: Any, options: dict[str, Any], extra: dict[str, Any], value: Any) -> tuple[str, ...]:
        return attempt(lambda: USES[use](package, annotation, options, extra)(value), raw = True)

    for index in range(-(-cases // VALUES_PER_CASE)):
        zone, use, options, extra, depth, validated = random_case(rng, index)
        annotation = random_annotation(rng, depth, kit if validated else None)
        for _ in range(VALUES_PER_CASE):
            value = random_input(rng, annotation)
            case = f"{use} ; {describe(options, extra)} ; {annotation!r} <- {show(value)}"
            result = outcome(use, annotation, options, extra, value)
            counts["an error is a TypeCheckerError, or one Python itself raises"] += 1
            if result[0] == "error" and result[1] not in OWN_ERRORS and not any(
                    result[1] == name and text in result[3] for name, text in PYTHON_ERRORS):
                broken["an error is a TypeCheckerError, or one Python itself raises"].append(f"{case}\n         {brief(result)}")
            counts["repeats agree: second call, returned value, subclass, own check, dunder"] += 1
            if result[1:2] == ("Unstable",):
                broken["repeats agree: second call, returned value, subclass, own check, dunder"].append(f"{case}\n         {result[3]}")
            #* on_error = "warn": where the call was fine, the same result and no warning. Where it
            #* raised a TypeCheckerError, either the same error (a call that can't be made, a
            #* mistake in the definition) or a warning that says what the error said.
            #* ("self" is left out: that use itself hands over a wrong value and takes a refusal for the answer.)
            if use not in ("binding", "self") and (result[0] == "ok" or result[1] == "TypeCheckerError"):
                counts[WARNS] += 1
                with warnings.catch_warnings(record = True) as seen:
                    warnings.simplefilter("always")
                    warned = outcome(use, annotation, {**options, "on_error": "warn"}, extra, value)
                said = [message_text(w.message) for w in seen if issubclass(w.category, package.TypeCheckerWarning)]
                if result[0] == "ok":
                    wrong = warned != result or bool(said)
                else:
                    wrong = not ((warned == result and not said) or (bool(said) and said[0] == result[3]))
                if wrong:
                    broken[WARNS].append(f"{case}\n         raise: {brief(result)}\n         warn:  {brief(warned)}"
                                         f"\n         warnings: {[text.replace(chr(10), ' / ')[:200] for text in said[:2]]}")
            if use == "binding" or result[0] != "ok":       # binding: each call has another shape
                continue
            for name, applies, looser in LOOSER:
                if applies(options):
                    counts[name] += 1
                    if outcome(use, annotation, {**options, **looser}, extra, value)[0] != "ok":
                        broken[name].append(case)
    return counts, broken


def report_properties(counts: collections.Counter, broken: dict[str, list[str]], show_examples: int) -> None:
    print(f"{'property':<74}{'checked':>10}{'broken':>9}")
    for name, checked in counts.items():
        print(f"{name:<74}{checked:>10,}{len(broken.get(name, [])):>9,}")
    for name, found in broken.items():
        print(f"\n  {name}: {len(found):,}")
        for case in found[:show_examples]:
            print(f"      {case}")
    if broken:
        print(f"\nFuzz failed: {sum(map(len, broken.values())):,} cases break a property.")
        sys.exit(1)
    print("\nFuzz passed!")


def main() -> None:
    parser = argparse.ArgumentParser(description = "Differential fuzz: a previous copy of enforced against the working tree.")
    parser.add_argument("--save-baseline", action = "store_true",
                        help = "copy the package as it is now to tests/.baseline and stop (do this before changing it)")
    parser.add_argument("--properties", action = "store_true",
                        help = "no baseline: check on the working tree alone what must hold in any version")
    parser.add_argument("--baseline", metavar = "DIR", help = "a copy of the package to compare with (default: tests/.baseline)")
    parser.add_argument("--ref", metavar = "REV", help = "compare with the package at this git revision, e.g. HEAD")
    parser.add_argument("--cases", type = int, default = 50_000, metavar = "N", help = "values to compare (default: 50000)")
    parser.add_argument("--seed", type = int, default = 1, help = "which random cases (default: 1)")
    parser.add_argument("--expect", action = "append", default = [], metavar = "REGEX",
                        help = "a difference the change is meant to make: searched in 'zone ; use ; options ; "
                               "annotation <- value ; baseline: outcome ; now: outcome' (repeatable)")
    parser.add_argument("--ignore-type-names", action = "store_true",
                        help = "for a change in how messages name a type: errors that differ only in the text between "
                               "'expected type' and '(Value' count as identical")
    parser.add_argument("--show", type = int, default = 3, metavar = "N", help = "examples printed per kind of difference (default: 3)")
    args = parser.parse_args()

    if args.save_baseline:
        save_baseline()
        return
    compile_at_once(enforced)
    if args.properties:
        print(f"working tree: enforced/\nseed {args.seed}: {args.cases:,} values, {VALUES_PER_CASE} per annotation\n")
        report_properties(*run_properties(enforced, args.cases, args.seed), args.show)
        return

    folder, origin = find_baseline(args.baseline, args.ref)
    old = load_baseline(folder)
    compile_at_once(old)
    print(f"baseline:     {origin}")
    print("working tree: enforced/")
    if same_sources(folder, PACKAGE):
        print("note: the baseline has the same sources as the working tree, so nothing can differ")
    print(f"seed {args.seed}: {args.cases:,} values, {VALUES_PER_CASE} per annotation\n")

    expected = [re.compile(pattern) for pattern in args.expect]
    counts, explained, unexplained = run(old, enforced, args.cases, args.seed, expected, args.ignore_type_names)

    print(f"{'zone':<10}{'compared':>12}{'identical':>12}{'expected':>12}{'unexplained':>13}")
    for zone in ("core", "extended"):
        print(f"{zone:<10}" + "".join(f"{counts[zone, column]:>{width},}" for column, width in
                                      (("comparisons", 12), ("identical", 12), ("expected", 12), ("unexplained", 13))))
    skipped = counts["core", "skipped"] + counts["extended", "skipped"]
    if skipped:
        reasons = ", ".join(f"{n} {name}" for (kind, name), n in counts.items() if kind == "skipped")
        print(f"({skipped} annotations could not be used in either version: {reasons})")
    if args.ignore_type_names:
        renamed = counts["core", "renamed"] + counts["extended", "renamed"]
        print(f"(of the identical ones, {renamed:,} are errors that only name a type differently: --ignore-type-names)")

    if explained:
        print("\nExpected differences (check that each pattern matches only what you meant):")
        for pattern in args.expect:
            found = explained.get(pattern, [])
            print(f"\n  {len(found):>6,}  --expect {pattern!r}")
            for difference in found[:1]:
                print(difference.render())
    unused = [pattern for pattern in args.expect if pattern not in explained]
    if unused:
        print("\nPatterns that matched nothing: " + ", ".join(repr(pattern) for pattern in unused))

    total = sum(len(found) for found in unexplained.values())
    if total:
        print(f"\nUnexplained differences: {total:,}")
        for group, found in sorted(unexplained.items(), key = lambda item: -len(item[1])):
            print(f"\n  {len(found):>6,}  {group}")
            for difference in found[:args.show]:
                print(difference.render())
        print(f"\nFuzz failed: {total:,} differences are not explained. A fix is meant to make some: name those with --expect.")
        sys.exit(1)
    print("\nFuzz passed!")


if __name__ == "__main__":
    main()
