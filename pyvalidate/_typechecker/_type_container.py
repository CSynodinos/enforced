from ..utils import formatter, one_decision
from ._file_types import FileType, file_stand_in
from typing import (
    IO, Annotated, Any, BinaryIO, Callable, ClassVar, ForwardRef, Optional, TextIO,
    Literal, LiteralString, Never, NoReturn, NotRequired, ReadOnly, Required, Final,
    Union, TypeGuard, TypeIs, TypeVar,
    get_args, get_origin, is_protocol, is_typeddict,
    )
from types import UnionType
from abc import ABCMeta
from enum import EnumType
import ast
import builtins
import collections
import collections.abc
import dataclasses
import inspect
import pickle
import sys
import threading
import weakref


#* id(annotation) -> what it unpacks to. When full, the oldest entry makes room: a long-running
#* program keeps the annotations it uses now, not the first 4,096 it ever met. Reads take no lock;
#* inserting and evicting do, so two threads can't meet halfway through an eviction.
_UNPACKED: dict[int, tuple] = {}
_UNPACKED_MAX = 4096
_UNPACKED_LOCK = threading.Lock()

#* What can't be an annotation: plain data. ``x: 5`` or a list in a record of typecheck_from_dict is a
#* mistake, and treating it as "anything goes" would hide it.
_NOT_ANNOTATIONS = (int, float, complex, bytes, bytearray, list, dict, set, frozenset, tuple)
OWNER_ATTR = "__typecheck_owner__"


def excludes_bool(expected: "type | TypeUnion") -> bool:
    """
    Whether ``isinstance`` would let a bool through only because bool subclasses int:
    true for ``int`` and ``int | str``; false for ``int | bool``, ``int | Number``, ``object``.
    """
    members = tuple(expected) if isinstance(expected, TypeUnion) else (expected,)
    if int not in members:
        return False
    for m in members:
        if m is int:
            continue
        try:
            if issubclass(bool, m):
                return False
        except TypeError:
            pass
    return True


class TypeUnion(tuple):
    """Ordered, deduplicated set of runtime types unpacked from a compound annotation."""

    def __new__(cls, types: tuple[type, ...]) -> "TypeUnion":
        return super().__new__(cls, types)

    def __repr__(self) -> str:
        names = " | ".join(t.__name__ for t in self)
        return f"TypeUnion({names})"

    def __str__(self) -> str:
        """How messages show a union: every option, like a single type is shown: 'int' | 'bytes'."""
        return " | ".join(f"'{t.__name__}'" for t in self)



type TypeContainerList = list[TypeContainer]
class TypeContainer:
    """
    Container for holding type information and performing type checks.

    Call .check() to perform the type check.

    Args:
        origin_obj (Any): The original object being checked.
        key (str): The key or name associated with the input object.
        input_object (Any): The actual input object to be checked.
        expected_type (type): The expected type for the input object.
    """

    #* What an annotation unpacks to (see __init__, where each is explained).
    _expected_type: "type | TypeUnion"
    _literal_values: "frozenset | None"
    _other_types: "type | TypeUnion | None"
    _is_never: bool
    _type_arg: "type | TypeUnion | None"
    _constraints: "tuple[tuple[Any, tuple[Callable[[Any], Any], ...]], ...] | None"
    _plain_types: "type | TypeUnion | None"

    def __init__(self, origin_obj: Any, key: str, input_object: Any, expected_type: type) -> None:
        self._key = key
        self._input_object = input_object
        self._origin_obj = origin_obj
        self._annotation = expected_type                # as written: messages show it for Literal and type[X]
        #* Unpacking depends only on the annotation, so it is cached per annotation *object*
        #* (identity, not equality: ``int | str == str | int``, but member order matters).
        entry = _UNPACKED.get(id(expected_type))
        if entry is not None and entry[0] is expected_type:
            (_, self._expected_type, self._literal_values, self._other_types, self._is_never, self._type_arg,
             self._constraints, self._plain_types) = entry
            return
        self._literal_values = None                     # set by Literal branch (merged across Literals)
        self._literal_types: list[type] = []            # the runtime types Literal values contributed
        self._constraint_groups: list[tuple[Any, tuple[Callable[[Any], Any], ...]]] = []   # Annotated[T, check]
        self._constrained_types: list[type] = []        # the runtime types constrained members contributed
        self._is_never = False                          # set by Never/NoReturn branch
        self._class_targets: list[type] = []            # set by type[X] branch: every X (merged across members)
        self._class_members: list[type] = []            # one `type` for each type[X] member
        self._expected_type = self._unpack_special_types(expected_type)
        #* type[X]: the classes a class value may be (or subclass); None without a type[X] member.
        self._type_arg = _as_expected(self._class_targets) if self._class_targets else None
        #* The ordinary members, checked by their type alone: those that are neither Literal values
        #* nor type[X] ("str | None" in "Literal['r', 'w'] | type[int] | str | None"). None when
        #* there are none. A Literal value or a class is matched on its own, before these.
        special = self._literal_types + self._class_members if self._literal_types or self._class_members else self._literal_types
        self._other_types = (
            _subtract_types(self._flat_with_repeats, special) if special else self._expected_type)
        #* Annotated[int, check] members: ((target, checks), ...), and the members without checks
        #* ("None" in "PositiveInt | None"), which accept a value on their type alone.
        self._constraints = (
            tuple(self._constraint_groups) or None)
        self._plain_types = (
            _subtract_types(self._flat_with_repeats, self._constrained_types + special)
            if self._constraints is not None else None)
        del (self._literal_types, self._flat_with_repeats, self._constraint_groups, self._constrained_types,
             self._class_targets, self._class_members)
        with _UNPACKED_LOCK:
            while len(_UNPACKED) >= _UNPACKED_MAX:
                _UNPACKED.pop(next(iter(_UNPACKED)), None)      # the oldest entry
            #* The entry keeps the annotation alive, so its id stays unique while it is cached.
            _UNPACKED[id(expected_type)] = (
                expected_type, self._expected_type, self._literal_values, self._other_types,
                self._is_never, self._type_arg, self._constraints, self._plain_types,
                )
        return

    def __str__(self) -> str:
        return f"TypeContainer(key = {self._key}, input_object_type = {type(self._input_object)}, expected_type = {self._expected_type})"

    def __repr__(self) -> str:
        k_repr = formatter(self._key, "bold_yellow")
        io_repr = formatter(str(type(self._input_object)), "bold_cyan")
        et_repr = formatter(str(self._expected_type), "bold_magenta")
        return f"TypeContainer(key = {k_repr}, input_object = {io_repr}, expected_type = {et_repr})"

    def _unpack_special_types(self, expected_type: type) -> type | TypeUnion:
        unpacked = self._flatten_expected_types(expected_type)
        self._flat_with_repeats = unpacked                      # read by _non_literal_types
        deduped = tuple(dict.fromkeys(unpacked))
        if not deduped:
            return object  # caller must check _is_never first
        if len(deduped) == 1:
            return deduped[0]
        return TypeUnion(deduped)

    def _flatten_expected_types(self, expected_type: Any) -> tuple[type, ...]:
        """Flatten a potentially complex type annotation into a tuple of runtime types."""

        # ── singleton / special forms ─────────────────────────────────────────
        if expected_type is Any:
            return (object,)

        if expected_type is None:
            return (type(None),)

        if expected_type is Ellipsis:
            return (object,)

        # ── LiteralString: a str (that it was written as a literal can't be seen at runtime) ──
        if expected_type is LiteralString:
            return (str,)

        if expected_type is Never or expected_type is NoReturn:
            self._is_never = True
            return ()

        # ── TypedDict: isinstance raises at runtime; treat as plain dict ──────
        if is_typeddict(expected_type):
            return (dict,)

        # ── typing.IO / TextIO / BinaryIO: no real file inherits from them ────
        if expected_type is TextIO or expected_type is BinaryIO or expected_type is IO:
            return (file_stand_in(expected_type),)      # type: ignore[return-value]

        # ── plain class ───────────────────────────────────────────────────────
        if isinstance(expected_type, type):
            if uncheckable_protocol(expected_type):
                raise protocol_error(expected_type, self._key)
            return (expected_type,)

        # ── forward references: a string of built-in names, read as data ──────
        if isinstance(expected_type, (str, ForwardRef)):
            ref = expected_type if isinstance(expected_type, str) else expected_type.__forward_arg__
            try:
                evaluated = read_annotation(ref)
            except Exception:
                raise TypeCheckerError(
                    break_trace_colouring + f"Cannot resolve annotation {formatter(short_repr(ref, 80), 'bold_yellow')} "
                    f"for parameter {formatter(self._key, 'bold_green')}"
                ) from None
            return self._flatten_expected_types(evaluated)

        # ── NewType (callable with __supertype__) ─────────────────────────────
        supertype = getattr(expected_type, "__supertype__", None)
        if supertype is not None:
            return self._flatten_expected_types(supertype)

        # ── TypeAliasType (PEP 695  `type X = ...`) ───────────────────────────
        alias_value = getattr(expected_type, "__value__", None)
        if alias_value is not None:
            return self._flatten_expected_types(alias_value)

        # ── TypeVar ───────────────────────────────────────────────────────────
        if isinstance(expected_type, TypeVar):
            bound, constraints = typevar_types(expected_type)
            if bound is not None:
                return self._flatten_expected_types(bound)
            if constraints:
                flattened: list[type] = []
                for c in constraints:
                    flattened.extend(self._flatten_expected_types(c))
                return tuple(flattened)
            return (object,)

        # ── bare UnionType (int | str) before get_origin ──────────────────────
        if isinstance(expected_type, UnionType):
            flattened = []
            for arg in get_args(expected_type):
                flattened.extend(self._flatten_expected_types(arg))
            return tuple(flattened)

        origin = get_origin(expected_type)
        args   = get_args(expected_type)

        # ── Union[X, Y] (old syntax) ──────────────────────────────────────────
        if origin is Union:
            flattened = []
            for arg in args:
                flattened.extend(self._flatten_expected_types(arg))
            return tuple(flattened)

        # ── Literal[...]: store allowed values, return their runtime types ────
        if origin is Literal:
            #* Merged, so Literal['a'] | Literal['b'] allows both; other union members are kept
            #* separately (see _non_literal_types), so Literal['r'] | None still accepts None.
            values = frozenset((type(v), v) for v in args)
            self._literal_values = values if self._literal_values is None else self._literal_values | values
            seen: set[type] = set()
            flattened = []
            for v in args:
                t = type(v)
                if t not in seen:
                    seen.add(t)
                    flattened.extend(self._flatten_expected_types(t))
            self._literal_types.extend(flattened)
            return tuple(flattened)

        # ── dataclasses.InitVar[T] → unwrap to T ───────────────────────────────
        if isinstance(expected_type, dataclasses.InitVar):
            return self._flatten_expected_types(expected_type.type)

        # ── Annotated[T, metadata] → T; callables in the metadata are extra checks ──
        if origin is Annotated:
            inner = self._flatten_expected_types(args[0])
            checks = tuple(m for m in args[1:] if callable(m) and not isinstance(m, type))
            if checks and inner:
                deduped = tuple(dict.fromkeys(inner))
                target = deduped[0] if len(deduped) == 1 else TypeUnion(deduped)
                self._constraint_groups.append((target, checks))
                self._constrained_types.extend(inner)
            return inner

        # ── Final[T] / ClassVar[T] / Required[T] / NotRequired[T] / ReadOnly[T] → unwrap ──
        if origin in (Final, ClassVar, Required, NotRequired, ReadOnly):
            return self._flatten_expected_types(args[0]) if args else (object,)

        # ── type[X] → value must be a class; store X for issubclass check ────
        if origin is type:
            if args:
                #* Kept apart from the union's other members (like Literal values): in
                #* type[int] | None the class test applies to classes only, and None still passes.
                self._class_targets.extend(self._flatten_expected_types(args[0]))
                self._class_members.append(type)
            return (type,)

        # ── IO[str] / IO[bytes] / IO[Any]: a text file, a binary one, either ──
        if origin is IO:
            return (file_stand_in(expected_type, origin, args),)    # type: ignore[return-value]

        # ── TypeGuard[X] / TypeIs[X] (a return annotation): the function returns a bool ──
        if origin is TypeGuard or origin is TypeIs:
            return (bool,)

        # ── other generic aliases: list[int]→list, dict[K,V]→dict, etc. ──────
        if origin is not None and isinstance(origin, type):
            return (origin,)

        # ── plain data where an annotation belongs: x: 5, or ["int"] in a record ──
        if isinstance(expected_type, _NOT_ANNOTATIONS):
            where = "the return value" if self._key == "return" else f"parameter {formatter(self._key, 'bold_green')}"
            raise TypeCheckerError(
                break_trace_colouring + f"Cannot check {where}: "
                f"{formatter(short_repr(expected_type), 'bold_yellow')} is not a type annotation"
                )

        #* What is left has no runtime test: a ParamSpec's P.args, a TypeVarTuple, Self outside a class.
        return (object,)

    @property
    def _formatter_origin_obj(self) -> str:
        return describe_origin(self._origin_obj)

    def check(self, allow_subclass: bool = True) -> bool:
        """Check if the input object matches the expected type.

        Args:
            allow_subclass (bool): If True, allow subclasses of the expected type.

        Returns:
            bool: True if the input object matches the expected type, False otherwise.
        """
        if self._is_never:
            return False

        if self._type_arg is not None and matches_class(self._input_object, self._type_arg, allow_subclass):
            return True

        if self._literal_values is not None:
            try:
                if (type(self._input_object), self._input_object) in self._literal_values:
                    return True
            except TypeError:        # unhashable input can never be a Literal member
                pass

        #* Neither such a class nor one of the values: it can still match the union's other members.
        expected = self._other_types
        if expected is None:
            return False
        if not matches_type(self._input_object, expected, allow_subclass):
            return False
        if self._constraints is None:
            return True
        return constraints_pass(self._input_object, self._constraints, self._plain_types, allow_subclass)

    def constraint_failure(self, value: Any, allow_subclass: bool = True) -> "tuple[Any, str] | None":
        """
        ``(type, reason)`` when ``value`` has the type of an ``Annotated[T, check]`` member but
        fails its check (and no other member accepts it); ``None`` otherwise.
        """
        if self._constraints is None:
            return None
        if self._plain_types is not None and matches_type(value, self._plain_types, allow_subclass):
            return None
        failure = None
        for target, checks in self._constraints:
            if not matches_type(value, target, allow_subclass):
                continue
            for check in checks:
                reason = check_failure(check, value)
                if reason is not None:
                    failure = failure or (target, reason)
                    break
            else:
                return None                             # this member accepts it
        return failure


def read_annotation(text: str) -> Any:
    """
    The annotation a string spells: ``"int"``, ``"list[int] | None"``, ``"Optional[int]"``,
    ``"Literal['a', 'b']"``, ``"Sequence[datetime]"``. The string is parsed and read, never run as
    code: ``typecheck_from_dict`` takes its annotations as data, and data must not be able to call
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


def typevar_types(variable: TypeVar) -> tuple[Any, tuple[Any, ...]]:
    """
    ``(bound, constraints)`` of a TypeVar. One written as a string (``TypeVar("T", bound="Shape")``,
    for a class defined further down) is looked up in the module that defines the variable; if it
    can't be found there it is returned as it is.
    """
    bound, constraints = variable.__bound__, variable.__constraints__
    if isinstance(bound, (str, ForwardRef)):
        bound = _named_in_module(bound, variable)
    elif constraints and any(isinstance(c, (str, ForwardRef)) for c in constraints):
        constraints = tuple([_named_in_module(c, variable) for c in constraints])
    return bound, constraints


def _named_in_module(ref: Any, variable: TypeVar) -> Any:
    """What ``ref`` (a string or ForwardRef in ``variable``'s definition) names in the variable's module."""
    if not isinstance(ref, (str, ForwardRef)):
        return ref
    module = sys.modules.get(getattr(variable, "__module__", None) or "")
    if module is None:
        return ref
    try:
        #* Source code of that module, like any annotation in it: evaluated where it was written.
        return eval(ref if isinstance(ref, str) else ref.__forward_arg__, vars(module))
    except Exception:
        return ref


def _subtract_types(flat: tuple[type, ...], removed: list[type]) -> "type | TypeUnion | None":
    """``flat`` minus one occurrence of each type in ``removed``, deduplicated (``None`` if nothing is left)."""
    others = list(flat)
    for t in removed:
        if t in others:
            others.remove(t)
    if len(others) < 2:                                 # the usual outcomes, without the deduplication
        return others[0] if others else None
    return _as_expected(others)


def _as_expected(types: "list[type] | tuple[type, ...]") -> "type | TypeUnion | None":
    """Flattened types as one expected type: the type, a TypeUnion of the distinct ones, or ``None`` for none."""
    deduped = tuple(dict.fromkeys(types))
    if not deduped:
        return None
    return deduped[0] if len(deduped) == 1 else TypeUnion(deduped)


class SelfType(type):
    """
    Metaclass of the stand-in for ``Self`` under ``allow_subclass=False``. ``Self`` is the class of
    the instance, which for an inherited method is a subclass of the class that defines it: asking
    for exactly the defining class would reject ``return self`` for every subclass. The stand-in
    accepts an instance of the class, or of a subclass of it.
    """
    owner: type

    def __instancecheck__(cls, value: Any) -> bool:
        return isinstance(value, cls.owner)

    def __subclasscheck__(cls, sub: Any) -> bool:
        return issubclass(sub, cls.owner)


def self_stand_in(owner: type) -> type:
    """The class to test ``Self`` with in strict mode. It is named like ``owner``, so messages read the same."""
    cls = SelfType(owner.__name__, (), {"__slots__": ()})
    cls.__module__, cls.__qualname__, cls.owner = owner.__module__, owner.__qualname__, owner
    return cls


#* ABCs of these modules without an abstract method left: Number, and the views of a dict
#* (``{}.keys()`` is a ``dict_keys``, registered as a KeysView and never an instance of exactly that).
_ABSTRACT_MODULES = frozenset({"numbers", "collections.abc", "_collections_abc"})
_ABSTRACT_BY_NAME = {"pathlib": ("Path", "PurePath"), "datetime": ("tzinfo",)}


def is_abstract(tp: Any) -> bool:
    """
    Whether ``tp`` is a class whose values are never instances of exactly ``tp`` itself, so that
    strict mode (``allow_subclass=False``) has to use ``isinstance``: asking for the exact type
    would reject every value.

        an ABC with abstract methods       Sequence, Callable, your own base class
        a Protocol
        Number, KeysView and the like      ABCs without abstract methods; what they describe (an int,
                                           ``{}.keys()``) is registered with them, not derived from them
        pathlib.Path, PurePath             ``Path("a")`` is a PosixPath or a WindowsPath
        datetime.tzinfo                    what is passed is a ``timezone`` or a ``ZoneInfo``
        enum.Enum, IntEnum, Flag ...       an Enum class without members has no instances at all
        type                               a class may have any metaclass (an Enum class, an ABC)
        the stand-ins                      for a file annotation (``TextIO``) and for ``Self``
    """
    if getattr(tp, "__abstractmethods__", None) or is_protocol(tp):
        return True
    kind = type(tp)
    if kind is FileType or kind is SelfType or tp is type:
        return True
    module = getattr(tp, "__module__", None)
    if not isinstance(module, str):
        return False
    if kind is ABCMeta and module in _ABSTRACT_MODULES:
        return True
    if isinstance(tp, EnumType):
        return not tp.__members__
    #* By name: pathlib and datetime are not imported for the sake of this test.
    return getattr(tp, "__name__", None) in _ABSTRACT_BY_NAME.get(module.partition(".")[0], ())


def matches_type(value: Any, expected: "type | TypeUnion", allow_subclass: bool) -> bool:
    """The plain type test: isinstance (bool is not an int), or the exact type in strict mode."""
    if allow_subclass:
        if not isinstance(value, expected):
            return False
        #* bool subclasses int, but True is not accepted as an int (like pydantic's strict mode).
        return type(value) is not bool or not excludes_bool(expected)
    #* Strict mode. ``object`` is what Any flattens to: it accepts everything here too.
    if isinstance(expected, TypeUnion):
        if type(value) in expected or object in expected:
            return True
    elif type(value) is expected or expected is object:
        return True
    return _implements(value, expected)


def _implements(value: Any, expected: "type | TypeUnion") -> bool:
    """Strict mode: whether ``value`` is an instance of an abstract member of ``expected``."""
    #* Kept out of matches_type: a loop or generator over ``value`` there would turn its argument
    #* into a closure cell, which slows every call (measured: +40% on the isinstance path).
    for member in (expected if isinstance(expected, TypeUnion) else (expected,)):
        if is_abstract(member) and isinstance(value, member):
            return True
    return False


def matches_class(value: Any, target: "type | TypeUnion", allow_subclass: bool) -> bool:
    """The ``type[X]`` test: ``value`` is a class that is X (one of X's members), or a subclass unless strict."""
    if not isinstance(value, type):
        return False
    try:
        if allow_subclass:
            return issubclass(value, target)
        if isinstance(target, TypeUnion):
            return value in target or object in target
        if type(target) is SelfType:                    # type[Self]: the class of the instance, or a subclass
            return issubclass(value, target.owner)
        return value is target or target is object
    except TypeError:
        return False


def uncheckable_protocol(tp: Any) -> bool:
    """A Protocol class that ``isinstance`` refuses to test (it isn't ``@runtime_checkable``)."""
    if not (isinstance(tp, type) and is_protocol(tp)):
        return False
    try:
        isinstance(None, tp)
    except TypeError:
        return True
    return False


def protocol_error(tp: type, key: str) -> "TypeCheckerError":
    where = "the return value" if key == "return" else f"parameter {formatter(key, 'bold_green')}"
    return TypeCheckerError(
        break_trace_colouring + f"Cannot check Protocol {formatter(tp.__name__, 'bold_yellow')} "
        f"for {where}: decorate it with @runtime_checkable"
        )


#* A check may also reject a value by raising one of these (its message becomes the reason).
#* LookupError: ``lambda s: s[0] == "a"`` given ``""`` rejects it, and used to escape as an IndexError.
CHECK_ERRORS = (ValueError, TypeError, ArithmeticError, LookupError)


def constraints_pass(value: Any, constraints: tuple, plain: "type | TypeUnion | None", allow_subclass: bool) -> bool:
    """Whether some member accepts ``value``: a member without checks by type, or one with checks by all of them."""
    if plain is not None and matches_type(value, plain, allow_subclass):
        return True
    for target, checks in constraints:
        if matches_type(value, target, allow_subclass):
            try:
                if all(check(value) for check in checks):
                    return True
            except CHECK_ERRORS:
                pass
    return False


def check_failure(check: Callable[[Any], Any], value: Any) -> str | None:
    """Why ``check`` rejects ``value`` (``None`` if it accepts it)."""
    try:
        if check(value):
            return None
    except CHECK_ERRORS as e:
        if str(e):
            return str(e)
    return f"failed check {describe_check(check)}"


_DESCRIBED: "weakref.WeakKeyDictionary[Any, str]" = weakref.WeakKeyDictionary()


def describe_check(check: Callable[[Any], Any]) -> str:
    """A readable name for a check: its name, or a lambda's own source (``x > 0``). Cached per check."""
    try:
        return _DESCRIBED[check]
    except (KeyError, TypeError):
        pass
    text = _describe_check(check)
    try:
        _DESCRIBED[check] = text
    except TypeError:                                   # not weak-referenceable
        pass
    return text


def _describe_check(check: Callable[[Any], Any]) -> str:
    name = getattr(check, "__name__", None)
    if name and name != "<lambda>":
        return name
    code = getattr(check, "__code__", None)
    if code is not None:
        try:
            import linecache
            #* A lambda returns its body, so its last instruction's position spans exactly that source.
            first, last, start, end = list(code.co_positions())[-1]
            if None not in (first, last, start, end):
                lines = [linecache.getline(code.co_filename, n) for n in range(first, last + 1)]
                text = lines[0][start:end] if first == last else lines[0][start:] + "".join(lines[1:-1]) + lines[-1][:end]
                text = " ".join(text.split())
                if text:
                    return text
        except Exception:
            pass
    return repr(check) if name is None else name


class TypeCheckerError(TypeError):
    """
    Exception raised for type checking errors.

    ``problems`` holds each issue as a :class:`Problem`. The (coloured) message is only
    built the first time the error is turned into text, so code that catches and
    handles the error never pays for formatting.
    """

    def __init__(self, message: str = "", *, problems: "list[Problem] | tuple[Problem, ...]" = (), context: str = "call") -> None:
        super().__init__(message)
        self.problems: list[Problem] = list(problems)
        self.context = context
        self._message: str | None = message if (message or not problems) else None

    @property
    def message(self) -> str:
        if self._message is None:
            self._message = _render_error(self.problems, self.context)
        return self._message

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r})"

    @property                                   # type: ignore[override]
    def args(self) -> tuple[str]:
        return (self.message,)

    @args.setter
    def args(self, value: tuple[Any, ...]) -> None:        # type: ignore[override]
        self._message = str(value[0]) if value else ""

    def __reduce__(self) -> tuple[Any, ...]:
        #* Rebuilt through a module-level function: pickle can't find the class itself,
        #* because __module__ is "builtins" (see below). The message travels as text, rendered
        #* now, and the problems as data (see Problem.__reduce__).
        return (_restore_error, (self.message, self.context, self.problems))

#* Tracebacks print "TypeCheckerError: ..." instead of the full module path.
TypeCheckerError.__module__ = "builtins"


def _restore_error(message: str, context: str = "call", problems: "list[Problem] | tuple[Problem, ...]" = ()) -> TypeCheckerError:
    """Unpickle a TypeCheckerError: its message as it was rendered, its context and its problems."""
    return TypeCheckerError(message, problems = problems, context = context)


class Unpickled:
    """
    Stands in an unpickled ``Problem`` for a part that could not travel: a value of a local class,
    a lock, a function that pickle can't find by name. It shows the ``repr`` of what it replaces.
    """
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Unpickled) and other.text == self.text

    def __hash__(self) -> int:
        return hash(self.text)

    def __reduce__(self) -> tuple[Any, ...]:
        return (Unpickled, (self.text,))


def _picklable(part: Any) -> Any:
    """``part`` if pickle takes it, else a stand-in that shows its repr."""
    if part is None or type(part) in (str, int, float, bool):
        return part
    try:
        pickle.dumps(part)
        return part
    except Exception:
        return Unpickled(short_repr(part, 80))


def _origin_reference(origin: Any) -> Any:
    """
    How the function or class a problem belongs to is pickled. A decorated function can't go by
    name the usual way: its name leads to the wrapper, and what the problem holds is the function
    inside. So it goes as ``(module, qualname)`` when following that name, and then the wrappers,
    leads back to it; a class goes as it is; anything else as a stand-in.
    """
    module, qualname = getattr(origin, "__module__", None), getattr(origin, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str) and not isinstance(origin, type):
        try:
            if _find_origin(module, qualname) is origin:
                return (module, qualname)
        except Exception:
            pass
    return _picklable(origin)


def _find_origin(module: str, qualname: str) -> Any:
    """The function that ``module.qualname`` names, or the one a pyvalidate wrapper found there checks."""
    found: Any = sys.modules.get(module) or __import__(module, fromlist = ["*"])
    for part in qualname.split("."):
        found = getattr(found, part)
    found = getattr(found, "__func__", found)           # a method, a class method
    inner = found
    for _ in range(16):
        if "_pv_bootstrap" in getattr(inner, "__globals__", ()):    # a wrapper made by _wrap_callable
            return inner.__wrapped__
        inner = getattr(inner, "__wrapped__", None)
        if inner is None:
            break
    return found


def _restore_problem(kind: str, parameter: Any, expected: Any, value: Any, origin: Any, detail: Any,
                     annotation: Any, text: str) -> "Problem":
    """Unpickle a Problem: its data, and its message as text."""
    if type(origin) is tuple:
        try:
            origin = _find_origin(*origin)
        except Exception:
            origin = Unpickled(".".join(origin))
    problem = Problem(kind, parameter, expected, value, origin, str, detail, annotation)
    problem._text = text
    return problem


class _TraceReset:
    """
    Goes in front of every message: the escape sequence that switches the terminal's attributes
    off again, so that Python's own colouring of the ``TypeCheckerError:`` line doesn't run into
    the message. It is worked out when a message is built, not at import: with colours switched
    off later on, it is the empty string like every other colour.
    """
    __slots__ = ()

    def __str__(self) -> str:
        return formatter("", "bold")

    def __add__(self, text: str) -> str:
        return formatter("", "bold") + text

    def __radd__(self, text: str) -> str:
        return text + formatter("", "bold")


break_trace_colouring = _TraceReset()
type ErrorMessage = str

class Problem:
    """
    One thing wrong with a call or a definition, kept as data.

    Attributes:
        kind: ``"type"`` (an argument), ``"default"``, ``"return"`` or ``"missing"``; with deep
            checks also ``"length"`` (a fixed tuple of the wrong length), ``"missing_key"``
            (a required TypedDict key) and ``"cycle"`` (data that contains itself). ``"invalid"``
            is a value of the right type that is rejected all the same: a failed ``Annotated``
            check or TypeModel ``validate``, keys that collide after conversion, a container
            whose type can't hold its converted items.
        parameter: The parameter name (``"args[2]"`` / ``"kwargs[b]"`` for varargs items);
            for ``"missing"``, a tuple of all missing names. With deep checks, the path to
            the bad item: ``"scores[3]"``, ``"prices['apple']"``, ``"point.x"``, ``"return[0]"``.
        expected: The expected type (for ``"missing"``, a tuple of annotations).
        annotation: The annotation as it was written, where the problem is about one value:
            ``Literal['r', 'w']`` where ``expected`` is the type of those values (``str``).
        value: The offending value (``None`` for ``"missing"`` and ``"missing_key"``).
        origin: The function or class being checked.
        detail: Extra data: the expected length for ``"length"``, the key for ``"missing_key"``,
            the reason for ``"invalid"``.

    ``str(problem)`` gives the coloured one-line message.
    """
    __slots__ = ("kind", "parameter", "expected", "value", "origin", "detail", "annotation", "_render", "_text")

    def __init__(self, kind: str, parameter: Any, expected: Any, value: Any, origin: Any,
                 render: Callable[[], str], detail: Any = None, annotation: Any = None) -> None:
        self.kind = kind
        self.parameter = parameter
        self.expected = expected
        self.annotation = annotation
        self.value = value
        self.origin = origin
        self.detail = detail
        self._render = render
        self._text: str | None = None

    def __str__(self) -> str:
        if self._text is None:
            self._text = self._render()
        return self._text

    def __repr__(self) -> str:
        return f"Problem(kind={self.kind!r}, parameter={self.parameter!r}, expected={self.expected!r}, value={short_repr(self.value)})"

    def __reduce__(self) -> tuple[Any, ...]:
        #* A problem travels as data, with its message as text: what renders the message holds the
        #* function, the value and the annotation, and any of them may refuse to be pickled. A part
        #* that refuses is replaced by a stand-in (``Unpickled``), so the error still arrives.
        return (_restore_problem, (
            self.kind, _picklable(self.parameter), _picklable(self.expected), _picklable(self.value),
            _origin_reference(self.origin), _picklable(self.detail), _picklable(self.annotation), str(self),
            ))


def made_dataclass(cls: Any) -> bool:
    """Whether ``cls`` was made a dataclass itself (a plain subclass of a dataclass wasn't)."""
    return "__dataclass_fields__" in vars(cls)


def describe_origin(origin_obj: Any) -> str:
    """Label for messages: <Function f>, <Method A.run>, <Class A>, <Dataclass P>."""
    owner = getattr(origin_obj, OWNER_ATTR, None)
    name = getattr(origin_obj, "__name__", type(origin_obj).__name__)
    Class_str = lambda: formatter("Class", "bold_magenta")
    Dataclass_str = lambda: formatter("Dataclass", "bold_magenta")

    if inspect.isclass(origin_obj):
        kind = Dataclass_str() if made_dataclass(origin_obj) else Class_str()
    elif owner is not None and (name == "__init__" or name == "__new__"):      # building an instance of the class
        kind = Dataclass_str() if made_dataclass(owner) else Class_str()
        name = owner.__name__   # type: ignore[attr-defined]
    elif owner is not None:
        kind = formatter("Method", "bold_magenta")
        name = f"{owner.__name__}.{name}"
    elif name == "__init__":
        #* Untagged __init__ (e.g. passed straight to typecheck_from_dict): best effort from the qualname.
        kind = Class_str()
        name = getattr(origin_obj, "__qualname__", name).removesuffix(".__init__")
    elif inspect.isfunction(origin_obj) or inspect.isbuiltin(origin_obj):
        kind = formatter("Function", "bold_magenta")
    else:
        kind = formatter("Callable", "bold_magenta")

    return f"<{formatter(kind, 'bold')} {formatter(name, 'bold_blue')}>"


def type_name(tp: Any) -> str:
    """
    How messages show a type: ``'int'``, ``'shop.Order'``, and a union member by member
    (``'int' | 'bytes'``). Built from the class's module and name, not cut out of its ``repr``:
    an Enum class prints as ``<enum 'Color'>`` and a local one has ``<locals>`` in its name.
    """
    if isinstance(tp, TypeUnion):
        return str(tp)
    if isinstance(tp, type):
        module, name = tp.__module__, tp.__qualname__
        return f"'{name}'" if module == "builtins" else f"'{module}.{name}'"
    return f"'{tp}'"


def short_repr(value: Any, limit: int = 40) -> str:
    """
    Safe, truncated repr for error messages. What it shows is the start of ``repr(value)``; a large
    built-in container isn't formatted in full to get there (see ``bounded_repr``).
    """
    try:
        text = bounded_repr(value, limit)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"
    return text if len(text) <= limit else text[:limit - 3] + "..."


#* The built-in containers a message may meet with millions of items: (opening, closing, what it
#* prints for itself when it contains itself).
_BRACKETS: dict[type, tuple[str, str, str]] = {
    list: ("[", "]", "[...]"), tuple: ("(", ")", "(...)"), dict: ("{", "}", "{...}"),
    set: ("{", "}", "set(...)"), frozenset: ("frozenset({", "})", "frozenset(...)"),
    }


def bounded_repr(value: Any, budget: int, _inside: tuple[int, ...] = ()) -> str:
    """
    ``repr(value)``, or for a built-in container or text the beginning of it: at least ``budget``
    characters, or all there is. ``repr`` builds the whole text first, which for a list of three
    million items takes 48 ms and the memory of all of it, to show forty characters. Here the
    items are formatted one at a time, until there is enough.
    """
    kind = type(value)
    if kind is str or kind is bytes or kind is bytearray:
        if len(value) <= budget:
            return repr(value)
        start = value[:budget]
        single, double = ("'", '"') if kind is str else (b"'", b'"')
        #* repr writes text between single quotes, unless it holds one and no double quote. The
        #* start is written as the whole would be only where that test gives both the same answer.
        if (single in start and double not in start) == (single in value and double not in value):
            return repr(start)
        if kind is not str:
            return repr(value)
        body = repr(start)[1:-1]
        return '"' + body if single in value and double not in value else "'" + body.replace("'", "\\'")
    brackets = _BRACKETS.get(kind)
    if brackets is None or not value:
        return repr(value)
    opening, closing, itself = brackets
    if id(value) in _inside:
        return itself
    inside = _inside + (id(value),)
    parts: list[str] = []
    size = len(opening)                                 # the length of what is written so far
    for item in (value.items() if kind is dict else value):
        #* What an item may still fill. One that is cut short is longer than that, so the test
        #* below ends the loop with it: nothing is ever written after an item that isn't whole.
        left = max(budget - size, 8)
        if kind is dict:
            key = bounded_repr(item[0], left, inside)
            part = key if len(key) > left else f"{key}: {bounded_repr(item[1], left, inside)}"
        else:
            part = bounded_repr(item, left, inside)
        size += len(part) + (2 if parts else 0)
        parts.append(part)
        if size > budget:                               # enough to fill the message: the rest isn't looked at
            return opening + ", ".join(parts)
    if kind is tuple and len(parts) == 1:
        parts[0] += ","
    return opening + ", ".join(parts) + closing


def _render_error(problems: "list[Problem]", context: str) -> str:
    noun = "problem" if len(problems) == 1 else "problems"
    with one_decision():                                # coloured or not: asked once for the whole message
        msg = (
            f"{formatter(len(problems), 'bold_red')} {noun} found in {context}:\n{' ' * 3} -> "
            + f"\n{' ' * 3} -> ".join(str(p) for p in problems)
            )
        return break_trace_colouring + msg
