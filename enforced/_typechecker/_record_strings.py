"""Annotations written as strings in a record: parsed and read, never run."""
from typing import Any, BinaryIO, IO, Literal, LiteralString, Never, NoReturn, Optional, TextIO, Union
import ast
import builtins
import collections
import collections.abc
import sys


def read_annotation(text: str) -> Any:
    """
    The annotation a string spells: ``"int"``, ``"list[int] | None"``, ``"Optional[int]"``,
    ``"Literal['a', 'b']"``, ``"Sequence[datetime]"``. The string is parsed and read, never run as
    code: ``typecheck_record`` takes its annotations as data, and data must not be able to call
    anything. It may hold names from a fixed list (the built-in classes and ``_RECORD_NAMES``),
    subscripts, ``|``, tuples, lists and constants; anything else raises ``ValueError``.
    """
    return _annotation_node(ast.parse(text.strip(), mode = "eval").body)


#* What a record string may name besides the built-in classes: the annotation forms a record needs,
#* each a fixed object. Nothing here can be called to any effect.
_RECORD_NAMES: dict[str, Any] = {
    "Any": Any, "Optional": Optional, "Union": Union, "Literal": Literal, "LiteralString": LiteralString,
    "Never": Never, "NoReturn": NoReturn, "IO": IO, "TextIO": TextIO, "BinaryIO": BinaryIO,
    "List": list, "Dict": dict, "Set": set, "FrozenSet": frozenset, "Tuple": tuple, "Type": type,
    "Deque": collections.deque, "DefaultDict": collections.defaultdict,
    "AbstractSet": collections.abc.Set,
    **{name: getattr(collections, name) for name in ("deque", "defaultdict", "OrderedDict", "Counter", "ChainMap")},
    **{name: getattr(collections.abc, name) for name in (
        "Sequence", "MutableSequence", "Mapping", "MutableMapping", "MutableSet", "Collection",
        "Iterable", "Iterator", "Callable", "Hashable", "Sized", "Container", "Reversible",
        )},
    }
#* Classes of the standard library that data is made of: name -> the module it is imported from,
#* the first time a record names it (none of them is imported for the sake of this list).
_RECORD_CLASSES = {
    "datetime": "datetime", "date": "datetime", "time": "datetime", "timedelta": "datetime",
    "Decimal": "decimal", "Fraction": "fractions", "UUID": "uuid", "Path": "pathlib", "PurePath": "pathlib",
    }
#* The modules a name may be written with: "typing.Optional[int]", "collections.abc.Sequence[int]".
_RECORD_MODULES = frozenset({"typing", "collections", "collections.abc", "builtins"})


def _record_name(name: str, module: str | None = None) -> Any:
    """What ``name`` (written with ``module`` in front, if any) stands for in a record string."""
    if module is None or module in _RECORD_MODULES:
        value = getattr(builtins, name, None)
        if isinstance(value, type):                     # int, list, ValueError ...: never a function such as eval
            return value
        if name in _RECORD_NAMES:
            return _RECORD_NAMES[name]
    home = _RECORD_CLASSES.get(name)
    if home is not None and module in (None, home):
        return getattr(sys.modules.get(home) or __import__(home), name)
    raise ValueError(f"{name!r} is not a name an annotation in a record may use")


def _dotted(node: ast.expr) -> list[str]:
    """``collections.abc.Sequence`` as its parts. Attributes of anything but a plain name are refused."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + [node.attr]
    raise ValueError(f"{type(node).__name__} is not part of an annotation")


def _annotation_node(node: ast.expr) -> Any:
    if isinstance(node, ast.Constant):                  # None, ..., a number, a nested string
        return node.value
    if isinstance(node, ast.Name):
        return _record_name(node.id)
    if isinstance(node, ast.Attribute):
        *module, name = _dotted(node)
        return _record_name(name, ".".join(module))
    if isinstance(node, ast.Subscript):
        return _annotation_node(node.value)[_annotation_node(node.slice)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _annotation_node(node.left) | _annotation_node(node.right)
    if isinstance(node, ast.Tuple):
        return tuple([_annotation_node(item) for item in node.elts])
    if isinstance(node, ast.List):
        return [_annotation_node(item) for item in node.elts]
    raise ValueError(f"{type(node).__name__} is not part of an annotation")
