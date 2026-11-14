"""Transform[In, Out]: a type made from a value of another type, by a hook, that holds only the result."""
from ._container import TypeContainer
from ._errors import InvalidDataError
from ._messages import format_annotation
from ._specs import SLOW, compile_converter, compile_spec, predicate
from ._text import short_repr
from ._type_conversion import FAILED, BrokenHook, HOOK_REFUSALS, refusal_text
from .._formatting_tool import formatter
from typing import Any, Callable, ClassVar, ForwardRef, Generic, Self, TypeVar, get_args, get_origin
from types import get_original_bases
import copy
import sys

In = TypeVar("In")
Out = TypeVar("Out")
_SIDES: tuple[Any, Any] = (In, Out)                     # as values: what the base itself has for its two sides

#* Where a class keeps what its two sides compile to (its own dictionary: it goes with the class).
_CHECKS = "__enforced_checks__"


class Transform(Generic[In, Out]):
    """
    Subclass `Transform[In, Out]`

    Must define `transform` class method:

        class BytesLoader(Transform[str, io.BytesIO]):
            @classmethod
            def transform(cls, raw: str) -> io.BytesIO:     # return the Out, or raise ValueError(reason)
                return io.BytesIO(raw.encode())

    `BytesLoader("abc")` checks that `"abc"` is an `In` (str), calls `transform`, checks that what it
    returned is an `Out` (BytesIO) and keeps that as `.value`. What was given is gone from memory. Where a checked function,
    field or attribute is annotated `BytesLoader`, a raw `In` is transformed (under `convert`, the
    default) and an instance passes through.

    A `TypeModel` *is* its value (an `Email` is a `str`); a `Transform` *holds* one, of another type.

    Instances are frozen: `value` can't be assigned again (what it holds may itself be mutable).
    `transform` has to be pure: it may run for a value that is then refused, or more than once for
    one that fails, so it must not open or hold anything. `In` and `Out` are checked with their
    items (`list[str]`), whatever the options of the function that takes the value.
    """
    value: Out
    __slots__ = ("value",)
    __input_type__: ClassVar[Any] = _SIDES[0]           # In and Out, as the class was written
    __output_type__: ClassVar[Any] = _SIDES[1]
    __enforced_transform__: ClassVar[bool] = True       # what tells it from a TypeModel (`is_transform`)
    auto_construct: ClassVar[bool] = True               # enforced builds it from a raw In under convert=True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        sides = _sides(cls)
        if sides is None:
            raise TypeError(f"{formatter(cls.__name__, 'bold_yellow')} must subclass Transform[In, Out], e.g. Transform[str, int]")
        if "__new__" in vars(cls) or "__init__" in vars(cls):
            raise TypeError(f"{formatter(cls.__name__, 'bold_yellow')} -> Put the work in {formatter('@classmethod', 'bold')} {formatter('transform', 'bold_blue')}, not {formatter('__new__', 'cyan')}/{formatter('__init__', 'cyan')}")
        own = vars(cls).get("transform")
        if own is not None and not isinstance(own, (classmethod, staticmethod)):
            raise TypeError(f"{formatter(cls.__name__, 'bold_yellow')}.transform must be a class method")
        cls.__input_type__, cls.__output_type__ = sides
        if _open(sides[0]) or _open(sides[1]):
            return                                      # still generic: a base for other classes
        if getattr(cls.transform, "__func__", None) is _NO_HOOK:
            side_left = _shown(sides[0])
            side_right = _shown(sides[1])
            tab = " " * 3
            raise TypeError(
                f"{formatter(cls.__name__, 'bold_yellow')} must define {formatter('@classmethod', 'bold')} {formatter('transform', 'bold_blue')}, "
                f"which must take raw [In]: {formatter(side_left, 'bold_yellow')} and return [Out]: {formatter(side_right, 'bold_yellow')}.\n"
                f"\n{tab}{formatter('Example', 'bold')}\n\n{tab}{formatter('@classmethod', 'yellow')} "
                f"\n{tab}{formatter('def', 'magenta')} transform(cls, raw: {side_left}) -> {side_right}:\n{tab * 2}...\n"
                )
        for side, name in zip(sides, ("In", "Out")):
            if isinstance(side, (str, ForwardRef)):
                continue                                # a name that may come later: read at the first use
            try:
                TypeContainer(None, "?", None, side)
            except InvalidDataError:
                raise TypeError(f"{formatter(cls.__name__, 'bold_yellow')} -> {formatter(name, 'bold')} is {side!r}, which is no type to check a value against") from None

    def __new__(cls, raw: In) -> Self:
        if isinstance(raw, cls):
            return raw                                  # an instance passes through
        test = _checks(cls)[0]
        if test is not None and not test(raw):
            raise TypeError(
                f"{formatter(cls.__name__, 'bold_yellow')} transformer expects {formatter(_shown(cls.__input_type__), 'bold_yellow')}, "
                f"got {formatter(type(raw).__name__, 'bold_red')} (Value: {formatter(short_repr(raw), 'bold_red')})"
                )
        return cls.__enforced_build__(raw)

    @classmethod
    def transform(cls, raw: In) -> Out:
        """Override: return what `raw` becomes, or raise ValueError with a reason."""
        raise NotImplementedError(f"{cls.__name__} doesn't define transform")

    # ── the hooks enforced calls ──────────────────────────────────────────────
    @classmethod
    def __enforced_build__(cls, raw: Any) -> Self:
        """An instance of a `raw` that is an `In`: the hook, then its result against `Out`."""
        out = cls.transform(raw)
        del raw
        test = _checks(cls)[1]
        if test is not None and not test(out):
            #* Hook bug caught
            raise BrokenHook(
                f"{cls.__qualname__}.transform must return {_shown(cls.__output_type__)}, not {type(out).__name__} (Value: {short_repr(out)})"
                )
        self = object.__new__(cls)
        object.__setattr__(self, "value", out)
        return self

    @classmethod
    def __enforced_convert__(cls, value: Any) -> "tuple[Any, str | None]":
        """`(instance | FAILED, reason)`, as a TypeModel's: an instance, or a value that is an `In` transformed."""
        if isinstance(value, cls):
            return value, None
        test = _checks(cls)[0]
        if test is not None and not test(value):
            return FAILED, None                         # no In: the usual type error
        try:
            return cls.__enforced_build__(value), None
        except BrokenHook:
            raise
        except HOOK_REFUSALS as e:
            return FAILED, refusal_text(e)              # the reason shown in the error message

    @classmethod
    def __enforced_input__(cls, coerce: bool) -> "tuple[Callable[[Any], bool] | None, Callable[[Any], Any] | None]":
        """The test of `In`, and what makes an `In` of another value (`1` -> `1.0`; with `coerce`, `"1"` -> `1`)."""
        kept = _checks(cls)
        index = 3 if coerce else 2
        if kept[index] is _UNMADE:
            kept[index] = compile_converter(kept[4], True, "raw", True, coerce, True, _resolver(cls))
        return kept[0], kept[index]

    # ── a held value ──────────────────────────────────────────────────────────
    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is frozen")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.value!r})"

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        return bool(self.value == other.value)          # type: ignore[attr-defined]  # the same class: it has one

    def __hash__(self) -> int:
        return hash((type(self), self.value))

    def __copy__(self) -> Self:
        return self                                     # frozen: a copy is the instance

    def __deepcopy__(self, memo: Any) -> Self:
        return _restore(type(self), copy.deepcopy(self.value, memo))

    def __reduce__(self) -> tuple[Any, ...]:
        #* What was given is gone, so there is nothing to transform again: the value travels.
        return (_restore, (type(self), self.value))


_NO_HOOK = Transform.__dict__["transform"].__func__
_UNMADE: Any = object()


def _restore(cls: "type[Transform[Any, Any]]", value: Any) -> Any:
    """An instance around `value`, checked against `Out`; the hook isn't run (copying, unpickling)."""
    test = _checks(cls)[1]
    if test is not None and not test(value):
        raise TypeError(f"{cls.__name__} holds {_shown(cls.__output_type__)}, got {type(value).__name__} "
                        f"(Value: {short_repr(value)})")
    self = object.__new__(cls)
    object.__setattr__(self, "value", value)
    return self


def _open(side: Any) -> bool:
    """Whether a side still has a type variable in it (`Transform[str, T]`)."""
    return isinstance(side, TypeVar) or bool(getattr(side, "__parameters__", ()))


def _shown(side: Any) -> str:
    try:
        return format_annotation(side.__forward_arg__ if isinstance(side, ForwardRef) else side)
    except Exception:
        return repr(side)


def _sides(cls: type) -> "tuple[Any, Any] | None":
    """`(In, Out)` of a class, from the base it was written with; a generic base's variables filled in."""
    for base in get_original_bases(cls):
        origin = get_origin(base) or base
        if origin is Transform:
            args = get_args(base)
            return (args[0], args[1]) if len(args) == 2 else None
        if isinstance(origin, type) and issubclass(origin, Transform):
            sides = getattr(origin, "__input_type__", None), getattr(origin, "__output_type__", None)
            given = dict(zip(getattr(origin, "__parameters__", ()), get_args(base)))
            return (_filled(sides[0], given), _filled(sides[1], given)) if given else sides
    return None


def _filled(side: Any, given: dict[Any, Any]) -> Any:
    if isinstance(side, TypeVar):
        return given.get(side, side)
    parameters = getattr(side, "__parameters__", ())
    return side[tuple(given.get(p, p) for p in parameters)] if parameters else side


def _resolver(cls: type) -> Callable[[str], Any]:
    """Reads a name that is still a string in `In` or `Out`: in the module of the class, as its source would."""
    def resolve(name: str) -> Any:
        module = sys.modules.get(cls.__module__)
        names = {p.__name__: p for p in getattr(cls, "__type_params__", ())}
        names.setdefault(cls.__name__, cls)
        return eval(name, getattr(module, "__dict__", {}), names)
    return resolve


def _checks(cls: Any) -> list[Any]:
    """
    `[test of In, test of Out, In's converter, In's converter with coerce, In]` of a class. Made at
    the first use, not at the class statement: either side may name a class defined further down.
    Each test is the annotation's check with its items (`deep`); `None` means anything passes.
    """
    kept = cls.__dict__.get(_CHECKS)
    if kept is not None:
        return kept                                     # type: ignore[no-any-return]
    if _open(cls.__input_type__) or _open(cls.__output_type__):
        raise TypeError(f"{cls.__name__} is still generic: it is a base for classes that say what In and Out are")
    resolve = _resolver(cls)
    sides, tests = [], []
    for side, name in ((cls.__input_type__, "In"), (cls.__output_type__, "Out")):
        try:
            if isinstance(side, (str, ForwardRef)):
                side = resolve(side.__forward_arg__ if isinstance(side, ForwardRef) else side)
            spec = compile_spec(side, True, name, True, False, False, resolve)
        except Exception as e:
            raise TypeError(f"{cls.__name__}: {name} can't be read ({type(e).__name__}: {e})") from None
        if spec is SLOW:
            raise TypeError(f"{cls.__name__}: {name} is {_shown(side)}, which can't be resolved")
        sides.append(side)
        tests.append(predicate(spec))                   # type: ignore[arg-type]
    kept = [tests[0], tests[1], _UNMADE, _UNMADE, sides[0]]
    setattr(cls, _CHECKS, kept)
    return kept
