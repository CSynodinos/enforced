"""TypeContainer: an annotation reduced to runtime types, and whether a value matches them."""
from .._formatting_tool import formatter
from ._checks import CHECK_ERRORS, check_failure, metadata_checks, refusal, REFUSED
from ._errors import InvalidDataError
from ._file_types import file_stand_in, FileType
from ._lifetime import held, holds, make_room, not_cached
from ._record_strings import read_annotation
from ._text import break_trace_colouring, describe_origin, short_repr
from typing import (
    Annotated, Any, BinaryIO, Callable, ClassVar, Final, ForwardRef, get_args, get_origin, IO, is_protocol,
    is_typeddict, Literal, LiteralString, Never, NoReturn, NotRequired, ReadOnly, Required, TextIO, TypeGuard,
    TypeIs, TypeVar, Union,
    )
from abc import ABCMeta
from enum import EnumType
from types import UnionType
import dataclasses
import sys
import threading


#* The three typing classes that stand for a file: plain classes that are not checked as such.
_TYPING_FILES = (TextIO, BinaryIO, IO)


#* What can't be an annotation: plain data. ``x: 5`` or a list in a record of typecheck_record is a
#* mistake, and treating it as "anything goes" would hide it.
_NOT_ANNOTATIONS = (int, float, complex, bytes, bytearray, list, dict, set, frozenset, tuple)


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


#* id(annotation) -> what it unpacks to. The annotation is held weakly, and its entry goes with it
#* (see ``held``); a plain class is never put here at all. When full, the oldest entry makes room:
#* a long-running program keeps the annotations it uses now, not the first 4,096 it ever met. Reads
#* take no lock; inserting and evicting do, so two threads can't meet halfway through an eviction.
_UNPACKED: dict[int, tuple] = {}
_UNPACKED_MAX = 4096
_UNPACKED_LOCK = threading.Lock()


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
        #* A plain class is its own answer, and needs no place in the cache (where it would be
        #* kept alive: a class made at run time has to be able to go).
        if type(expected_type) is type and expected_type not in _TYPING_FILES:
            self._expected_type = self._other_types = expected_type
            self._literal_values = self._type_arg = self._constraints = self._plain_types = None
            self._is_never = False
            return
        entry = _UNPACKED.get(id(expected_type))
        if entry is not None and holds(entry[0], expected_type):
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
        if id(expected_type) in not_cached:             # an annotation made for one class (see ``made_for``)
            return
        with _UNPACKED_LOCK:
            make_room(_UNPACKED, _UNPACKED_MAX)
            #* The entry goes when the annotation does (see ``held``), so the id is this annotation's.
            _UNPACKED[id(expected_type)] = (
                held(expected_type, _UNPACKED, id(expected_type)), self._expected_type, self._literal_values, self._other_types,
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
                raise InvalidDataError(
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
            checks = metadata_checks(args[1:])
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
            raise InvalidDataError(
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

    def constraint_failure(self, value: Any, allow_subclass: bool = True, known: bool = False) -> "tuple[Any, str] | None":
        """
        ``(type, reason)`` when ``value`` has the type of an ``Annotated[T, check]`` member but
        fails its check (and no other member accepts it); ``None`` otherwise.

        ``known``: the predicate of this annotation has just refused ``value``. Where it is one
        member with checks, the reason is what that run left behind (``REFUSED``), and no check
        is run a second time.
        """
        if self._constraints is None:
            return None
        if known and len(self._constraints) == 1 and self._plain_types is None:
            refused = REFUSED
            target, checks = self._constraints[0]
            kept = refused[0]
            #* The value itself, or what it was converted to (``-3`` for ``Annotated[float, check]``
            #* is checked as ``-3.0``): of the target's own type and equal to it, by the same check.
            #* The value itself only if it has the target's type: else no check of it ran (a second guard,
            #* after the predicate's own emptying on a wrong type).
            if ((kept is value and matches_type(value, target, allow_subclass))
                    or (type(kept) is target and type(value) is not target and kept == value)) and refused[1] in checks:
                said = refusal(refused[1], refused[2], refused[3])
                refused[0] = refused[1] = refused[3] = None
                return target, said
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
        if type(target) is FileType:                    # type[TextIO]: a file class (no class is the stand-in itself)
            return issubclass(value, target)
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


def protocol_error(tp: type, key: str) -> "InvalidDataError":
    where = "the return value" if key == "return" else f"parameter {formatter(key, 'bold_green')}"
    return InvalidDataError(
        break_trace_colouring + f"Cannot check Protocol {formatter(tp.__name__, 'bold_yellow')} "
        f"for {where}: decorate it with @runtime_checkable"
        )


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


def find_uncheckable_protocol(annotation: Any, depth: int = 0) -> type | None:
    """The first Protocol inside ``annotation`` that isinstance can't test (best effort, for the message)."""
    if isinstance(annotation, type):
        return annotation if uncheckable_protocol(annotation) else None
    if depth < 8:
        for arg in get_args(annotation):
            if (found := find_uncheckable_protocol(arg, depth + 1)) is not None:
                return found
    return None
