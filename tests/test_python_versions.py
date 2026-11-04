"""
What must read and work alike on 3.13 and later (``enforced/_compat.py``). On 3.14 most of this holds
by itself; each test here broke on 3.13 first, and none can be told from the rest of the suite. The two
Pythons are compared outcome by outcome with ``tests/fuzz.py --dump`` / ``--compare-dumps``.
"""
from enforced import dataclass, dispatch, enforce, make_dataclass, validate, validate_function, validate_record, InvalidDataError
from enforced._compat import annotated_of, annotation_text, get_annotations, Format, union_of
from enforced._validator._class_rules import unannotated
from enforced._validator._container import _UNPACKED, type_name, TypeContainer
from enforced._validator._lifetime import cacheable, holds
from enforced._validator._messages import format_annotation
from enforced._validator._remembered import union_order
from enforced._validator._scope import _names_in
from enforced._validator._text import short_repr
from pathlib import Path, PurePosixPath
from types import NoneType
from typing import Annotated, Any, Callable, get_args, Literal, Optional, Self, Union
import ast
import builtins
import collections.abc
import dataclasses
import enforced
import functools
import gc
import json
import pickle
import pytest
import subprocess
import sys
import types
import typing
import weakref

PACKAGE = Path(enforced.__file__).parent
ROOT = PACKAGE.parent


# ── what a message shows ────────────────────────────────────────────────────

@pytest.mark.parametrize("annotation, text", [
    (Optional[int], "int | None"),
    (None | Literal["a"], "None | Literal['a']"),
    (Union[None, list[int]], "None | list[int]"),
    (Union[int, str], "int | str"),
    (Union[int, str, None], "int | str | None"),
    (int | None, "int | None"),
    (list[Optional[int]], "list[int | None]"),
    (Optional[list[int]], "list[int] | None"),
    (dict[str, Union[int, list[Optional[str]]]], "dict[str, int | list[str | None]]"),
    (Literal["r"] | None, "Literal['r'] | None"),
    (Union[Literal[1, "one"], float], "Literal[1, 'one'] | float"),
    (Optional[Literal["Union[", "x, y"]], "Literal['Union[', 'x, y'] | None"),
    (Callable[[Optional[int]], Union[int, str]], "Callable[[int | None], int | str]"),
    (tuple[int, *tuple[Optional[str], ...]], "tuple[int, *tuple[str | None, ...]]"),
    (Annotated[int, lambda n: n < 0] | None, "Annotated[int, n < 0] | None"),
    (list[Path], "list[pathlib.Path]"),
    (Optional[PurePosixPath], "pathlib.PurePosixPath | None"),
    (Path, "Path"),
    ], ids = lambda value: value if isinstance(value, str) else "")
def test_an_annotation_reads_the_same_on_every_version(annotation, text):
    assert format_annotation(annotation) == text


class Box[T]:
    pass


class MyUnion[T]:
    pass


@pytest.mark.parametrize("annotation, text", [
    (list[type(None)], "list[None]"),
    (list[Annotated[None, "n"]], "list[None]"),                     # what is no check isn't shown
    (collections.abc.Collection[Annotated[None, "n"]], "collections.abc.Collection[None]"),
    (Annotated[int, None, "text"], "int"),
    (Annotated[None | int, abs], "Annotated[None | int, abs]"),
    (typing.List[Optional[int]], "List[int | None]"),
    (Literal["pathlib._local.x"], "Literal['pathlib._local.x']"),
    ], ids = str)
def test_what_else_reads_the_same(annotation, text):
    assert format_annotation(annotation) == text


def test_a_name_that_only_ends_in_union_is_left_alone():
    assert annotation_text(MyUnion[int]).endswith("MyUnion[int]")
    assert annotation_text(Box[Optional[int]]).endswith("Box[int | None]")


@pytest.mark.parametrize("tp, text", [(Path, "'pathlib.Path'"), (PurePosixPath, "'pathlib.PurePosixPath'"), (int, "'int'")])
def test_a_class_of_pathlib_is_named_by_its_public_module(tp, text):
    assert type_name(tp) == text


def test_a_class_given_as_a_value_is_named_so_too():
    @validate
    def f(k: type[int]) -> None: ...

    with pytest.raises(InvalidDataError) as caught:
        f(Path)
    assert "(Value: <class 'pathlib.Path'>)" in str(caught.value)
    assert "_local" not in caught.value.json()


def test_a_value_is_shown_as_it_is():
    #* Only a class is named by its public module: a text that reads like one was given as that text.
    assert short_repr("pathlib._local.Path") == "'pathlib._local.Path'"
    assert short_repr(["pathlib._local.x"]) == "['pathlib._local.x']"
    assert short_repr(Path) == "<class 'pathlib.Path'>"
    assert short_repr([Path]) == "[<class 'pathlib.Path'>]"
    assert short_repr([int, Path, Path]).endswith("...")


def test_the_messages_say_it():
    @validate
    def f(x: Literal["r"] | None, y: Path) -> None: ...

    with pytest.raises(InvalidDataError) as caught:
        f("w", 1)
    assert "expected type: Literal['r'] | None, got type 'str'" in str(caught.value)
    assert "expected type: 'pathlib.Path', got type 'int'" in str(caught.value)


# ── the order of a union, in validate_record ────────────────────────────────

def _coerced(annotation: Any) -> Any:
    return validate_record({"object_name": "ordered", "record": {"x": annotation}, "args": ("1",), "coerce": True})[0][0]


def test_every_way_to_write_a_union_keeps_its_order():
    #* They are all equal, and a record is looked up by equality; conversion follows the order. On 3.13
    #* ``Union[...]`` is no ``UnionType``, and the first one answered for all of them.
    first = _coerced(Union[int, float])
    assert (first, type(first)) == (1, int)
    for annotation in (Union[float, int], float | int, "float | int"):
        assert type(_coerced(annotation)) is float, annotation
    for annotation in (int | float, "int | float", Union[int, float]):
        assert type(_coerced(annotation)) is int, annotation


def test_equal_unions_of_one_order_share_a_checker():
    assert union_order(Union[int, float]) == union_order(int | float) == (int, float)
    assert union_order(Optional[int]) == union_order(int | None) == (int, NoneType)
    assert union_order(Union[float, int]) != union_order(Union[int, float])
    assert union_order(Optional[list[int]]) != union_order(Optional[list[str]])     # something nested: by its text


def test_an_order_inside_another_annotation_is_kept_too():
    def items(annotation: Any) -> Any:
        return validate_record({"object_name": "ordered", "record": {"x": annotation}, "args": (["1"],), "coerce": True, "deep": True})[0][0]

    assert items(list[Union[int, float]]) == [1] and type(items(list[Union[int, float]])[0]) is int
    assert type(items(list[Union[float, int]])[0]) is float


# ── nothing may keep a class made at run time alive ─────────────────────────

def _alive(body: Callable[[int], type]) -> int:
    alive = [weakref.ref(body(i)) for i in range(40)]
    for _ in range(3):
        gc.collect()
    return sum(ref() is not None for ref in alive)


@enforce
class Family:
    def in_union(self, other: Self | None = None) -> None: ...
    def in_optional(self, other: Optional[Self] = None) -> None: ...
    def in_old_union(self, other: Union[Self, int] = 0) -> None: ...
    def in_annotated(self, other: Annotated[Self, lambda value: True]) -> None: ...
    def in_annotated_union(self, other: Annotated[Self, lambda value: True] | None = None) -> None: ...
    def in_list(self, other: list[Annotated[Self, lambda value: True] | None]) -> None: ...


@pytest.mark.parametrize("method, argument", [
    ("in_union", lambda one: one), ("in_optional", lambda one: one), ("in_old_union", lambda one: one),
    ("in_annotated", lambda one: one), ("in_annotated_union", lambda one: one), ("in_list", lambda one: [one]),
    ], ids = lambda value: value if isinstance(value, str) else "")
def test_a_class_in_place_of_self_goes_when_it_is_dropped(method, argument):
    def body(i: int) -> type:
        sub = type(f"Sub{i}", (Family,), {})
        one = sub()
        getattr(one, method)(argument(one))
        return sub

    assert _alive(body) == 0


def test_a_message_that_names_such_a_class_keeps_nothing_either():
    def body(i: int) -> type:
        sub = type(f"Sub{i}", (Family,), {})
        one = sub()
        with pytest.raises(InvalidDataError) as caught:
            one.in_annotated_union("wrong")
        assert "expected" in str(caught.value)
        del caught
        return sub

    assert _alive(body) == 0


def _a_bar_in_a_function() -> type:
    class Local: ...

    @validate
    def f(x: Local | None) -> None: ...

    f(Local())
    return Local


def _a_bar_in_a_message() -> type:
    class Local: ...

    @validate
    def f(x: Local | None) -> None: ...

    with pytest.raises(InvalidDataError) as caught:
        f(1)
    str(caught.value)
    del caught
    return Local


def _a_bar_in_a_field() -> type:
    class Local: ...

    @dataclass
    class Data:
        a: Local | None = None

    Data(Local()).a = None
    return Local


def _a_bar_inside_items() -> type:
    class Local: ...

    @validate(deep = True)
    def f(x: list[Local | None], y: dict[str, Local | int]) -> None: ...

    f([Local()], {"a": Local()})
    return Local


def _a_bar_in_a_class() -> type:
    class Local: ...

    @enforce
    class Holder:
        attribute: Local | int = 0

        def method(self, x: Local | None) -> None: ...

    Holder().method(Local())
    Holder().attribute = Local()
    return Local


def _a_bar_with_a_class_made_by_type() -> type:
    #* No ``<locals>`` in its name: only that its module doesn't know it tells that it can go.
    made = type("Made", (), {})

    @validate
    def f(x: made | None) -> None: ...

    f(made())
    return made


def _a_bar_in_a_dispatch() -> type:
    class Local: ...

    @dispatch
    def chosen(value: object) -> int:
        return 0

    @chosen.register
    def _(value: Local | None) -> int:
        return 1

    assert chosen(Local()) == 1
    return Local


@pytest.mark.parametrize("body", [_a_bar_in_a_function, _a_bar_in_a_message, _a_bar_in_a_field, _a_bar_inside_items, _a_bar_in_a_class,
                                  _a_bar_with_a_class_made_by_type, _a_bar_in_a_dispatch], ids = lambda body: body.__name__)
def test_a_class_named_with_a_bar_goes_when_it_is_dropped(body):
    #* On 3.13 ``Local | None`` takes no weak reference: a cache that took it held the class for good.
    assert _alive(lambda i: body()) == 0


def test_a_bar_of_classes_that_stay_is_cached_all_the_same():
    annotation = list[int] | None
    TypeContainer(None, "x", None, annotation)
    assert holds(_UNPACKED[id(annotation)][0], annotation)
    assert cacheable(int | None) and cacheable(list[int] | str) and cacheable(Path | None) and cacheable(Family | None)


def test_a_bar_of_a_class_that_can_go_is_not_cached():
    made = type("Made", (), {})
    annotation = made | None
    TypeContainer(None, "x", None, annotation)
    if sys.version_info < (3, 14):
        assert not cacheable(annotation) and id(annotation) not in _UNPACKED
    else:
        assert cacheable(annotation)                                # weakly held: it goes by itself


def test_the_annotations_made_past_the_cache_are_the_real_thing():
    class Local:
        pass

    check = lambda value: True                                      # noqa: E731
    assert union_of((Local, None)) == Optional[Local] and union_of((int, str, int)) == Union[int, str]
    assert union_of((int,)) is int
    assert annotated_of((Local, check)) == Annotated[Local, check]
    assert get_args(annotated_of((Local, check))) == (Local, check)


# ── a quoted name inside an annotation, in a function ───────────────────────

def _optional() -> tuple[Any, type]:
    class Quoted1: ...

    @validate
    def f(x: Optional["Quoted1"]) -> None: ...

    return f, Quoted1


def _items() -> tuple[Any, type]:
    class Quoted2: ...

    @validate(deep = True)
    def f(x: list["Quoted2"]) -> None: ...

    return (lambda value: f([value])), Quoted2


def _nested() -> tuple[Any, type]:
    class Quoted3: ...

    @validate(deep = True)
    def f(x: dict[str, list[Optional["Quoted3"]]]) -> None: ...

    return (lambda value: f({"a": [value]})), Quoted3


def _field() -> tuple[Any, type]:
    class Quoted4: ...

    @dataclass
    class Data:
        a: Optional["Quoted4"]

    return Data, Quoted4


def _method() -> tuple[Any, type]:
    class Quoted5: ...

    @enforce
    class Holder:
        def method(self, x: Optional["Quoted5"]) -> None: ...

    return (lambda value: Holder().method(value)), Quoted5


def _below() -> tuple[Any, type]:
    #* Written further down: it comes into being after the decorator ran, and is read when this function ends.
    @validate
    def f(x: Optional["Quoted6"]) -> None: ...

    class Quoted6: ...

    return f, Quoted6


@pytest.mark.parametrize("make", [_optional, _items, _nested, _field, _method, _below], ids = lambda make: make.__name__)
def test_a_quoted_name_inside_an_annotation_is_found(make):
    check, cls = make()
    check(cls())                                                    # it was "Cannot resolve annotation" for every value
    with pytest.raises(InvalidDataError) as caught:
        check("wrong")
    assert "Cannot resolve" not in str(caught.value)


@pytest.mark.parametrize("text, names", [
    ("Optional['Loc']", {"Optional", "Loc"}),
    ("list['Loc']", {"list", "Loc"}),
    ("dict[str, list[Optional['Loc']]]", {"dict", "str", "list", "Optional", "Loc"}),
    ("Optional['list[Loc]']", {"Optional", "list", "Loc"}),
    ("Literal['Value', 'r']", {"Literal"}),
    ("typing.Literal['Value']", {"typing"}),
    ("Literal[Color.RED, 'Value']", {"Literal", "Color"}),
    ("Annotated['Loc', 'a note']", {"Annotated", "Loc"}),
    ("Annotated[int, positive, 'a note']", {"Annotated", "int", "positive"}),
    ("Annotated[int, Check(lambda value: value > limit), 'a note']", {"Annotated", "int", "Check", "value", "limit"}),
    ("list[int]", {"list", "int"}),
    ], ids = str)
def test_what_a_text_names(text, names):
    assert _names_in([text]) == names


def test_text_that_is_no_annotation_names_nothing():
    assert _names_in(["not 'an annotation ("]) == set()
    assert _names_in(["Annotated[int, 'a note here']"]) == {"Annotated", "int"}


def test_a_literal_value_is_not_looked_up():
    def outer() -> Any:
        Value = 5                                                   # noqa: F841  (it must not be picked up)

        @validate
        def f(x: Literal["Value"]) -> None: ...

        return f

    assert "Value" not in (vars(outer()).get("__enforced_scope__") or {})


# ── what a callable object is checked against ───────────────────────────────

class Scorer:
    threshold: float = 0.5

    def __call__(self, x: int) -> int:
        return x


class Named:
    x: str = ""                                                     # the same name as the parameter: no relation

    def __call__(self, x: int) -> int:
        return x


@dataclass
class DataCallable:
    limit: int = 0

    def __call__(self, x: int) -> int:
        return x


@pytest.mark.parametrize("make", [Scorer, Named, DataCallable], ids = lambda make: make.__name__)
def test_a_callable_object_is_checked_against_its_call_not_its_attributes(make):
    checked = validate(make())
    assert checked(1) == 1
    with pytest.raises(InvalidDataError, match = "For parameter x"):
        checked("a")
    with pytest.raises(InvalidDataError, match = "For parameter x"):
        validate_function(make(), ("a",))


def test_a_callable_object_made_with_wraps_keeps_going_through_what_it_wraps():
    class Wrapper:
        note: float = 1.0

        def __init__(self, fn: Any) -> None:
            functools.update_wrapper(self, fn)
            self.fn = fn

        def __call__(self, *args: Any) -> Any:
            return self.fn(*args)

    def target(x: int) -> int:
        return x

    checked = validate(Wrapper(target))
    assert checked(1) == 1
    with pytest.raises(InvalidDataError, match = "For parameter x"):
        checked("a")


# ── what 3.13 doesn't have ──────────────────────────────────────────────────

def test_a_method_without_annotations_stays_the_plain_function():
    def bare(self, x): ...
    def some(self, x: int): ...

    assert unannotated(bare) and not unannotated(some)

    @enforce
    class Holder:
        def method(self, x):
            return x

    assert not hasattr(vars(Holder)["method"], "__wrapped__")
    assert Holder().method("anything") == "anything"


def test_a_copy_with_converted_defaults_keeps_its_annotations():
    @validate
    def f(x: float = 0) -> float:
        return x

    assert f() == 0.0 and type(f()) is float
    assert typing.get_type_hints(f) == {"x": float, "return": float}


def test_get_annotations_takes_every_format():
    class Annotated_:
        x: int
        y: "Later"                                                  # noqa: F821

    for format in (Format.VALUE, Format.FORWARDREF):
        assert set(get_annotations(Annotated_, format = format)) == {"x", "y"}


# ── make_dataclass ──────────────────────────────────────────────────────────

Point = make_dataclass("Point", [("x", float), ("y", float, dataclasses.field(default = 0.0))])


def test_make_dataclass_makes_a_checked_class():
    assert Point(1) == Point(1.0, 0.0) and type(Point(1).x) is float
    with pytest.raises(InvalidDataError):
        Point("a")
    assert pickle.loads(pickle.dumps(Point(2.0))) == Point(2.0)
    assert Point.__module__ == __name__


def test_make_dataclass_takes_what_the_standard_one_takes():
    made = make_dataclass("Made", ["anything", ("n", int, 3)], bases = (dict,), namespace = {"double": lambda self: self.n * 2},
                          frozen = True, kw_only = True, module = "somewhere")
    one = made(anything = object())
    assert one.double() == 6 and made.__module__ == "somewhere" and issubclass(made, dict)
    assert dataclasses.is_dataclass(made) and made.__dataclass_params__.frozen
    assert typing.get_type_hints(made)["anything"] is Any
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.n = 4


@pytest.mark.parametrize("fields, message", [
    (["class"], "must not be keywords"),
    (["not a name"], "must be valid identifiers"),
    ([(1, int)], "must be valid identifiers"),
    (["x", "x"], "duplicated"),
    ([("x", int, 1, 2)], "Invalid field"),
    ], ids = str)
def test_make_dataclass_refuses_what_the_standard_one_refuses(fields, message):
    with pytest.raises(TypeError, match = message):
        make_dataclass("Bad", fields)


# ── the rule of the bridge ──────────────────────────────────────────────────

def _sources() -> list[Path]:
    return [path for path in PACKAGE.rglob("*.py") if path.name != "_compat.py"]


def test_only_the_bridge_asks_which_python_this_is():
    for path in _sources():
        text = path.read_text(encoding = "utf-8")
        assert "version_info" not in text, path
        assert "import annotationlib" not in text and "from annotationlib" not in text, path


def test_nothing_reads_annotate_without_getattr():
    #* A plain ``fn.__annotate__`` raises on 3.13, and ``unannotated`` would catch that and answer wrongly.
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding = "utf-8"))):
            assert not (isinstance(node, ast.Attribute) and node.attr == "__annotate__"), f"{path}:{node.lineno}"


def test_nothing_else_asks_what_a_union_is():
    #* ``UNION_TYPES`` answers for every way to write one: an ``isinstance`` of only ``UnionType`` misses ``Union[...]`` on 3.13.
    for path in _sources():
        assert "UnionType" not in path.read_text(encoding = "utf-8"), path


def _too_early(source: str) -> list[str]:
    """
    What 3.13 would raise ``NameError`` for and 3.14 doesn't: an annotation it evaluates where it stands,
    naming what isn't there yet. Function bodies run later, so what a nested ``def`` names needs only to exist by then.
    """
    tree = ast.parse(source)
    if any(isinstance(node, ast.ImportFrom) and node.module == "__future__" and any(a.name == "annotations" for a in node.names)
           for node in tree.body):
        return []
    problems: list[str] = []

    def bound_by(node: ast.AST) -> set[str]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return {node.name}
        if isinstance(node, ast.If) and getattr(node.test, "id", "") == "TYPE_CHECKING":
            return bound_in(node.orelse)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            return {node.id}
        return {name for child in ast.iter_child_nodes(node) for name in bound_by(child)}

    def bound_in(body: list[ast.stmt]) -> set[str]:
        return {name for node in body for name in bound_by(node)}

    final = bound_in(tree.body)

    def check(annotation: ast.AST | None, known: set[str], line: int) -> None:
        for node in ast.walk(annotation) if annotation is not None else ():
            if isinstance(node, ast.Name) and node.id not in known and not hasattr(builtins, node.id):
                problems.append(f"line {line}: {node.id}")

    def walk(body: list[ast.stmt], known: set[str], in_function: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parameters = node.args
                inner = known | {p.name for p in node.type_params}
                for parameter in (*parameters.posonlyargs, *parameters.args, *parameters.kwonlyargs, parameters.vararg, parameters.kwarg):
                    if parameter is not None:
                        check(parameter.annotation, inner, node.lineno)
                check(node.returns, inner, node.lineno)
                arguments = {p.arg for p in (*parameters.posonlyargs, *parameters.args, *parameters.kwonlyargs, parameters.vararg, parameters.kwarg) if p}
                #* Its body runs after the module has been run.
                walk(node.body, final | known | inner | arguments | bound_in(node.body), True)
                known.add(node.name)
            elif isinstance(node, ast.ClassDef):
                walk(node.body, known | {p.name for p in node.type_params}, in_function)
                known.add(node.name)
            elif isinstance(node, ast.If) and getattr(node.test, "id", "") == "TYPE_CHECKING":
                walk(node.orelse, known, in_function)
            elif isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                for part in ("body", "handlers", "orelse", "finalbody"):
                    for child in getattr(node, part, []):
                        walk(child.body if isinstance(child, ast.ExceptHandler) else [child], known, in_function)
                known |= bound_by(node)
            else:
                if isinstance(node, ast.AnnAssign) and not in_function:     # a local variable's annotation is never evaluated
                    check(node.annotation, known, node.lineno)
                known |= bound_by(node)

    walk(tree.body, set(), False)
    return problems


@pytest.mark.parametrize("source, name", [
    ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from x import A\ndef f(a: A): ...\n", "A"),
    ("def f(a: Later): ...\nclass Later: ...\n", "Later"),
    ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from x import A\nNAME: dict[str, A] = {}\n", "A"),
    ("class C:\n    def f(self) -> C: ...\n", "C"),
    ("class C:\n    x: Later = 1\nclass Later: ...\n", "Later"),
    ("def outer():\n    def inner(a: Nowhere): ...\n", "Nowhere"),
    ], ids = lambda value: value if value.isidentifier() else "")
def test_the_check_of_annotations_finds_what_3_13_would_refuse(source, name):
    assert [problem.split(": ")[1] for problem in _too_early(source)] == [name]


@pytest.mark.parametrize("source", [
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from x import A\ndef f(a: 'A'): ...\nNAME: 'dict[str, A]' = {}\n",
    "class Later: ...\ndef f(a: Later) -> int: ...\n",
    "def f[T](a: T) -> T: ...\nclass B[T]:\n    x: T\n",
    "def outer():\n    def inner(a: Later): ...\nclass Later: ...\n",
    "def outer():\n    class L: ...\n    def inner(a: L): ...\n    x: Nowhere = 1\n",
    "from __future__ import annotations\ndef f(a: Later): ...\n",
    ])
def test_the_check_of_annotations_leaves_what_3_13_takes(source):
    assert _too_early(source) == []


def test_no_annotation_in_the_package_needs_a_later_python():
    #* 3.13 raises at the first import; this finds the same on 3.14, where every annotation is lazy.
    #* A name that only exists for a checker, or further down, must be quoted.
    for path in PACKAGE.rglob("*.py"):
        assert _too_early(path.read_text(encoding = "utf-8")) == [], path


def test_the_first_import_works():
    done = subprocess.run([sys.executable, "-c", "import enforced, enforced.data_types, enforced.utils"],
                          capture_output = True, text = True)
    assert done.returncode == 0, done.stderr


# ── every way to write a name, in every place, with and without the future import ───

_FORMS: dict[str, tuple[str, str, str]] = {
    #* name: (the annotation, a value it takes, whether it quotes every local name)
    "quoted": ('"Loc"', "Loc()", True),
    "quoted bar": ('"Loc | None"', "Loc()", True),
    "unquoted bar": ("Loc | None", "Loc()", False),
    "quoted in Optional": ('Optional["Loc"]', "Loc()", True),
    "unquoted in Optional": ("Optional[Loc]", "Loc()", False),
    "quoted in list": ('list["Loc"]', "[Loc()]", True),
    "quoted in dict": ('dict[str, "Loc"]', '{"a": Loc()}', True),
    "quoted in nested": ('dict[str, list[Optional["Loc"]]]', '{"a": [Loc()]}', True),
    "quoted in Annotated": ('Annotated["Loc", is_any]', "Loc()", False),
    "local check, a doc": ('Annotated[int, is_any, "a doc"]', "1", False),
    "local check only": ("Annotated[int, is_any]", "1", False),
    "local enum in Literal": ('Literal[Color.RED, "x"]', "Color.RED", False),
    "quoted Literal": ("Literal['r', 'w']", '"r"', True),
    "whole annotation quoted": ('"Annotated[int, is_any, \'a doc\']"', "1", True),
    }

_PLACES: dict[str, str] = {
    "function": """
    @validate(deep = True)
    def check(x: ANNOTATION): return x
""",
    "dataclass field": """
    @dataclass(deep = True)
    class Holder:
        x: ANNOTATION
    check = Holder
""",
    "dataclass assignment": """
    @dataclass(deep = True)
    class Holder:
        x: ANNOTATION = None
    def check(value):
        holder = Holder.__new__(Holder)
        holder.x = value
""",
    "enforce method": """
    @enforce(deep = True)
    class Holder:
        def method(self, x: ANNOTATION): return x
    check = lambda value: Holder().method(value)
""",
    "enforce attribute": """
    @enforce(deep = True)
    class Holder:
        x: ANNOTATION
    def check(value):
        Holder().x = value
""",
    "Enforced method": """
    class Holder(Enforced, deep = True):
        def method(self, x: ANNOTATION): return x
    check = lambda value: Holder().method(value)
""",
    "Enforced attribute": """
    class Holder(Enforced, deep = True):
        x: ANNOTATION
    def check(value):
        Holder().x = value
""",
    "static method": """
    class Holder:
        @staticmethod
        @validate(deep = True)
        def method(x: ANNOTATION): return x
    check = Holder.method
""",
    "validate on a method": """
    class Holder:
        @validate(deep = True)
        def method(self, x: ANNOTATION): return x
    check = lambda value: Holder().method(value)
""",
    }

_NAMES = """
    class Loc: ...
    class Color(Enum):
        RED = 1
    def is_any(value): return True
"""

_PROGRAM = """{future}
from enum import Enum
from typing import Annotated, Literal, Optional
from enforced import dataclass, Enforced, enforce, validate

def make():
    {first}
    {second}
    return check, lambda: {value}
"""


def _grid() -> list[tuple[str, str, str, str]]:
    cases = []
    for form, (_, _, all_quoted) in _FORMS.items():
        for place in _PLACES:
            for future in ("no future import", "future import"):
                for order in ("above", "below"):
                    #* Below needs every name quoted, or the future import: 3.13 evaluates the rest where it stands.
                    if order == "above" or future == "future import" or all_quoted:
                        cases.append((form, place, future, order))
    return cases


@pytest.mark.parametrize("form, place, future, order", _grid(), ids = " · ".join)
def test_a_local_name_is_found_in_every_form_and_place(form, place, future, order):
    annotation, value, _ = _FORMS[form]
    definition = _PLACES[place].replace("ANNOTATION", annotation)
    first, second = (_NAMES, definition) if order == "above" else (definition, _NAMES)
    source = _PROGRAM.format(future = "from __future__ import annotations" if future == "future import" else "", first = first,
                             second = second, value = value)
    #* The enclosing function has returned before the first call: nothing of its frame is left to look in.
    module = types.ModuleType(f"grid_{abs(hash((form, place, future, order)))}")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, module.__name__, "exec", dont_inherit = True), module.__dict__)
        check, good = module.make()
        check(good())
    finally:
        del sys.modules[module.__name__]


# ── comparing two Pythons ───────────────────────────────────────────────────

def _compared(tmp_path: Path, first: list[Any], second: list[Any], value: str = "str:'1'") -> subprocess.CompletedProcess:
    paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    for path, outcome in zip(paths, (first, second)):
        path.write_text(json.dumps([0, "argument", "", "int", value, outcome]) + "\n")
    return subprocess.run([sys.executable, str(ROOT / "tests" / "fuzz.py"), "--compare-dumps", *map(str, paths)],
                          capture_output = True, text = True, cwd = ROOT)


@pytest.mark.parametrize("first, second", [
    (["ok", "int:1"], ["ok", "float:1.0"]),                         # both accepted it, and made another value of it
    (["ok", "int:1"], ["error", "InvalidDataError", "", "m"]),
    (["error", "InvalidDataError", "", "m"], ["error", "TypeError", "", "m"]),
    ], ids = ["another result", "accepted by one", "another error class"])
def test_comparing_dumps_fails_where_an_outcome_differs(tmp_path, first, second):
    done = _compared(tmp_path, first, second)
    assert done.returncode == 1 and "1 in their outcome" in done.stdout


def test_comparing_dumps_passes_where_only_the_order_of_a_set_differs(tmp_path):
    done = _compared(tmp_path, ["ok", "list[int:1, str:'a']"], ["ok", "list[str:'a', int:1]"], "set{int:1, str:'a'}")
    assert done.returncode == 0 and "1 differ by the order of a set" in done.stdout
    #* A value that holds a set doesn't excuse another result.
    done = _compared(tmp_path, ["ok", "list[int:1]"], ["ok", "list[float:1.0]"], "set{int:1}")
    assert done.returncode == 1


def test_comparing_dumps_fails_where_another_parameter_or_kind_is_blamed(tmp_path):
    done = _compared(tmp_path, ["error", "InvalidDataError", "type@x", "m"], ["error", "InvalidDataError", "invalid@y", "m"])
    assert done.returncode == 1 and "1 in their outcome" in done.stdout
    done = _compared(tmp_path, ["error", "InvalidDataError", "type@x", "m"], ["error", "InvalidDataError", "invalid@y", "m"], "set{int:1}")
    assert done.returncode == 1


def test_comparing_dumps_lets_a_set_move_what_is_blamed(tmp_path):
    done = _compared(tmp_path, ["error", "InvalidDataError", "type@x[0]", "at index [0]: int"],
                     ["error", "InvalidDataError", "type@x[1]", "at index [1]: int"], "set{int:1, str:'a'}")
    assert done.returncode == 0 and "1 differ by the order of a set" in done.stdout


def test_a_case_skipped_on_one_python_is_reported_as_what_it_is(tmp_path):
    done = _compared(tmp_path, ["skipped", "NameError"], ["ok", "int:1"])
    assert done.returncode == 1 and "1 in their outcome" in done.stdout


def test_comparing_dumps_of_different_lengths_says_so(tmp_path):
    paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    line = json.dumps([0, "argument", "", "int", "", ["ok", "int:1"]]) + "\n"
    paths[0].write_text(line)
    paths[1].write_text(line * 2)
    done = subprocess.run([sys.executable, str(ROOT / "tests" / "fuzz.py"), "--compare-dumps", *map(str, paths)],
                          capture_output = True, text = True, cwd = ROOT)
    assert done.returncode != 0 and "different lengths" in done.stderr


def test_comparing_dumps_tells_a_text_and_passes(tmp_path):
    done = _compared(tmp_path, ["error", "InvalidDataError", "", "one"], ["error", "InvalidDataError", "", "other"])
    assert done.returncode == 0 and "1 in their text" in done.stdout


def test_a_dump_makes_the_folder_it_is_written_to(tmp_path):
    path = tmp_path / "not" / "yet" / "dump.jsonl"
    done = subprocess.run([sys.executable, str(ROOT / "tests" / "fuzz.py"), "--dump", str(path), "--cases", "10"],
                          capture_output = True, text = True, cwd = ROOT)
    assert done.returncode == 0, done.stderr
    assert len(path.read_text().splitlines()) >= 5
