"""
Value conversion for enforced.

Applied only to values that *fail* their type check, so valid calls never pay for it.
Two levels:

**Conversion** (``convert=True``, on by default): lossless changes that the typing rules
already treat as compatible, i.e. the PEP 484 numeric tower.

    int          -> float      1 -> 1.0   (only when exact: 2**53 + 1 is rejected)
    int, float   -> complex    1 -> (1+0j)

    bool is never converted to a number.

**Coercion** (``coerce=True``, off by default): parsing, and lossy changes that are checked
to be safe. Similar to pydantic's lax mode. Coercion includes conversion.

    str          -> int, float, complex, bool, Decimal, Fraction, UUID, pathlib paths
    str          -> datetime, date, time      (ISO 8601, via ``fromisoformat``)
    date         -> datetime                  (midnight, no timezone: what "2026-10-17" gives)
    float        -> int                       (whole numbers only: 3.0 -> 3, 3.5 is rejected)
    int, float   -> bool                      (0 and 1 only)
    str <-> bytes                             (UTF-8)
    value        -> Enum member               (Color("red") -> Color.RED)
    list, tuple, set, frozenset -> each other

**TypeModel** targets (``Email``, ``Port`` ...) are built from a raw value of their base type
under ``convert`` (``"a@b.com"`` -> ``Email("a@b.com")``), after the base type's own conversion
or, with ``coerce``, coercion (``"8080"`` -> ``8080`` -> ``Port(8080)``). Set the class flag
``auto_construct = False`` to only accept existing instances.

**Transform** targets (``class BufferFile(Transform[str, io.BytesIO])``) are built the same way, from
a raw value of their ``In``: the value is made an ``In`` first if it isn't one (by that annotation's
own conversion or coercion), then goes through the class's ``transform`` hook. An instance holds the
result and is no instance of it, which is where the two part (``is_transform``, ``is_value_model``).

For a union, conversions are tried first (members in declared order), then coercions (again in
declared order). The first result that passes the type check wins. A TypeModel member takes its
turn like any other: ``float | Port`` makes ``80.0`` of ``80``, ``Port | float`` a ``Port``.
"""
from typing import Any, Callable
import enum


class _Failed:
    """Sentinel: the value couldn't be converted."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "FAILED"


FAILED = _Failed()

type Converter = Callable[[Any], Any]          # value -> converted value, or FAILED


# ── conversion: the numeric tower ────────────────────────────────────────────

def _to_float(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool):
        result = float(value)                   # OverflowError for huge ints (caught by caller)
        return result if result == value else FAILED
    return FAILED


def _to_complex(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = complex(value)
        return result if result == value else FAILED
    return FAILED


_CONVERSIONS: dict[type, Converter] = {float: _to_float, complex: _to_complex}


# ── coercion ─────────────────────────────────────────────────────────────────

_TRUE = frozenset({"true", "t", "yes", "y", "on", "1"})
_FALSE = frozenset({"false", "f", "no", "n", "off", "0"})
_COLLECTIONS = (list, tuple, set, frozenset)


def _coerce_int(value: Any) -> Any:
    if isinstance(value, str):
        return int(value)                       # int() accepts " -42 " and "1_000", rejects "1.5"
    if isinstance(value, float):
        return int(value) if value.is_integer() else FAILED
    return FAILED


def _coerce_float(value: Any) -> Any:
    return float(value) if isinstance(value, str) else FAILED


def _coerce_complex(value: Any) -> Any:
    return complex(value.strip()) if isinstance(value, str) else FAILED


def _coerce_bool(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip().lower()
        return True if text in _TRUE else False if text in _FALSE else FAILED
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    return FAILED


def _coerce_str(value: Any) -> Any:
    return bytes(value).decode("utf-8") if isinstance(value, (bytes, bytearray)) else FAILED


def _coerce_bytes(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return FAILED


_COERCIONS: dict[type, Converter] = {
    int: _coerce_int, float: _coerce_float, complex: _coerce_complex,
    bool: _coerce_bool, str: _coerce_str, bytes: _coerce_bytes,
    }


def _in_mro(target: type, module: str, qualname: str) -> bool:
    """``issubclass`` by name, so optional stdlib modules (decimal, uuid, ...) are never imported here."""
    return any(
        getattr(base, "__module__", "").split(".")[0] == module and base.__qualname__ == qualname
        for base in getattr(target, "__mro__", ())
        )


def _coercion_for(target: Any) -> Converter | None:
    if not isinstance(target, type):
        return None
    if (simple := _COERCIONS.get(target)) is not None:
        return simple

    if target in _COLLECTIONS:
        def to_collection(value: Any) -> Any:
            return target(value) if isinstance(value, _COLLECTIONS) and type(value) is not target else FAILED
        return to_collection

    made: Any = target                          # the class, called to make the value (typed loosely: any class)
    if issubclass(target, enum.Enum):
        #* Level(True) finds the member whose value is 1, because True == 1. A bool is no number
        #* anywhere else here, so it is only taken where a member's own value is a bool.
        bools = any(type(member.value) is bool for member in target)

        def to_member(value: Any) -> Any:
            if type(value) is bool and not bools:
                return FAILED
            return made(value)
        return to_member

    if _in_mro(target, "datetime", "datetime"):
        #* A date (YAML reads an unquoted 2026-10-17 as one) is midnight of that day, as the text
        #* "2026-10-17" already is. A datetime is a date too (a subclass), and is left alone here:
        #* it reaches a datetime target only when it failed for another reason (strict mode, a subclass).
        midnight = made.min.time()                              # time(0, 0), without importing datetime here

        def to_datetime(value: Any) -> Any:
            if isinstance(value, str):
                return made.fromisoformat(value.strip())
            kind = type(value)
            if _in_mro(kind, "datetime", "date") and not _in_mro(kind, "datetime", "datetime"):
                return made.combine(value, midnight)
            return FAILED
        return to_datetime

    if any(_in_mro(target, "datetime", name) for name in ("date", "time")):
        return lambda value: made.fromisoformat(value.strip()) if isinstance(value, str) else FAILED

    if _in_mro(target, "decimal", "Decimal") or _in_mro(target, "fractions", "Fraction"):
        return lambda value: made(value.strip() if isinstance(value, str) else value) \
            if isinstance(value, (str, int)) and not isinstance(value, bool) else FAILED

    if _in_mro(target, "uuid", "UUID"):
        return lambda value: made(value.strip()) if isinstance(value, str) else FAILED

    if _in_mro(target, "pathlib", "PurePath"):
        return lambda value: made(value) if isinstance(value, str) else FAILED

    return None


# ── TypeModel targets ─────────────────────────────────────────────────────────

def is_model_class(target: Any) -> bool:
    """A TypeModel class, whether or not it is built from raw values (duck-typed, like ``is_model``)."""
    return isinstance(target, type) and getattr(target, "__enforced_convert__", None) is not None


def is_model(target: Any) -> bool:
    """A TypeModel class that may be built from a raw value (duck-typed: no import of the model module)."""
    if not isinstance(target, type):
        return False
    if getattr(target, "__enforced_convert__", None) is None:     # plain classes: the common, cheap answer
        return False
    return bool(getattr(target, "auto_construct", True))


def is_transform(target: Any) -> bool:
    """A ``Transform`` class: built by the checker as a TypeModel is, but it holds its value and is no instance of it."""
    return isinstance(target, type) and getattr(target, "__enforced_transform__", False) is True


def is_value_model(target: Any) -> bool:
    """``is_model`` without the ``Transform`` classes: a model whose instances are values of its base type."""
    return is_model(target) and not is_transform(target)


class BrokenHook(TypeError):
    """
    A ``Transform`` whose ``transform`` returned something that isn't its ``Out``: a bug in the hook,
    not a wrong value. No converter takes it for a refusal: each one that catches ``TypeError``
    lets this one through first.
    """


#* A traceback reads ``TypeError: BufferFile.transform must return ...``: the class is nobody's to catch by name.
BrokenHook.__module__, BrokenHook.__qualname__, BrokenHook.__name__ = "builtins", "TypeError", "TypeError"


#* What a ``Transform``'s hook refuses a value with. ``ValueError(reason)`` is the way; the other two are
#* taken for a refusal as well, as a TypeModel's are, and say which they were: the value was an ``In``,
#* so "expected ... | 'str', got type 'str'" would contradict itself.
HOOK_REFUSALS = (ValueError, TypeError, ArithmeticError)


def refusal_text(error: BaseException) -> str:
    """The reason a hook's exception gives: its message, after its class when it is no ``ValueError``."""
    return str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"


def model_convert(target: Any, value: Any, coerce: bool) -> tuple[Any, str | None]:
    """
    ``(instance | FAILED, reason)``: build ``target`` from ``value``, converting (or coercing) it
    to the base type first if needed. ``reason`` is set when the value had the right type but
    ``clean`` rejected it.
    """
    #* The converter has just run ``clean`` on this very value and been refused: its reason.
    rejected = REJECTED
    if rejected[0] is value and rejected[1] is target:
        reason = rejected[2]
        rejected[0] = rejected[1] = rejected[2] = None
        return FAILED, reason
    out, reason = target.__enforced_convert__(value)
    if out is not FAILED or reason is not None:
        return out, reason
    if is_transform(target):
        #* A Transform has no base type: the raw value is made an ``In`` by that annotation's own converter.
        to_input = target.__enforced_input__(coerce)[1]
        if to_input is None or (raw := to_input(value)) is FAILED:
            passed_on(target, value)
            rejected = REJECTED
            if rejected[0] is value and rejected[1] is target:
                reason = rejected[2]
                rejected[0] = rejected[1] = rejected[2] = None
                return FAILED, reason
            return FAILED, None
        return target.__enforced_convert__(raw)
    base = target.__base_type__
    for step in (_CONVERSIONS.get(base), _coercion_for(base) if coerce else None):
        if step is None:
            continue
        try:
            raw = step(value)
        except (TypeError, ValueError, ArithmeticError):
            continue
        if raw is not FAILED:
            return target.__enforced_convert__(raw)
    return FAILED, None


#* The last raw value a model's ``clean`` refused, the model, and the reason it gave. The message
#* of the error that follows needs that reason, and used to run ``clean`` a second time to get
#* it. Read once and emptied (``model_convert``); value and model are compared by identity, so what
#* another thread or another call left here is simply not taken.
REJECTED: list[Any] = [None, None, None]


def _model_step(target: Any, coerce: bool) -> Converter:
    base = target.__base_type__

    def step(value: Any) -> Any:
        if type(value) is base:                 # the common case (a plain str for an Email): build it directly
            try:
                return target(value)
            except ValueError as e:
                rejected = REJECTED
                rejected[0], rejected[1], rejected[2] = value, target, str(e)
                return FAILED
        return model_convert(target, value, coerce)[0]
    return step


def _transform_step(target: Any, coerce: bool) -> Converter:
    """
    A ``Transform`` class's turn in a converter: the value as an ``In`` (converted to one first, as the
    caller's options allow), through the hook, into an instance. A ``ValueError`` of the hook leaves its
    reason in ``REJECTED``, as a model's ``clean`` does. What the hook needs is asked of the class at
    the first value: ``In`` may name a class that is defined after this converter is made.
    """
    rejected = REJECTED
    parts: list[Any] = [None]

    def step(value: Any) -> Any:
        made = parts[0]
        if made is None:                        # put in whole: another thread may be here too
            made = parts[0] = (*target.__enforced_input__(coerce), target.__enforced_build__)
        test, to_input, build = made
        raw = value
        if test is not None and not test(value):
            if to_input is None or (raw := to_input(value)) is FAILED:
                passed_on(target, value)
                return FAILED
        try:
            return build(raw)
        except BrokenHook:
            raise
        except HOOK_REFUSALS as e:
            rejected[0], rejected[1], rejected[2] = value, target, refusal_text(e)
            return FAILED
    return step


def passed_on(target: Any, value: Any) -> None:
    """
    A ``Transform`` whose ``In`` is a model (``Transform[Email, ...]``) and a value that model has just
    refused: the reason is the Transform's now (``invalid 'Domain': Email refused it: ...``), or the
    message would read as a plain wrong type and drop the reason.
    """
    rejected = REJECTED
    model = rejected[1]
    if rejected[0] is value and model is not target and model is not None:
        rejected[1], rejected[2] = target, f"{getattr(model, '__name__', model)} refused it: {rejected[2]}"


def _step_of(target: Any, coerce: bool) -> Converter:
    return _transform_step(target, coerce) if is_transform(target) else _model_step(target, coerce)


def _one_model(target: Any, coerce: bool, accept: Callable[[Any], bool]) -> Converter:
    """
    The converter of an annotation that is one TypeModel (``Sku``, ``Email``), written out: what
    ``single`` -> ``step`` -> ``target(value)`` -> ``__new__`` -> ``clean`` did in four Python calls
    for the usual value, a plain instance of the base type, is one call of ``clean`` here
    (0.3 µs less per converted value). The same answers: a ``ValueError`` leaves its reason in
    ``REJECTED`` and is ``FAILED``; ``TypeError`` and ``ArithmeticError`` are ``FAILED``; what
    ``clean`` returns must be of the base type; the result must pass ``accept``. Anything else
    (a subclass of the base type, a value to convert or coerce first) goes the long way.
    """
    base = target.__base_type__
    clean = target.clean
    make = base.__new__
    rejected = REJECTED
    step = _model_step(target, coerce)

    def one_model(value: Any) -> Any:
        try:
            if type(value) is base:
                try:
                    answer = clean(value)
                except ValueError as e:
                    rejected[0], rejected[1], rejected[2] = value, target, str(e)
                    return FAILED
                if type(answer) is not base and not isinstance(answer, base):
                    return FAILED                       # what TypeModel.__new__ refuses with a TypeError
                result = make(target, answer)
            else:
                result = step(value)
        except (TypeError, ValueError, ArithmeticError):
            return FAILED
        return result if result is not FAILED and accept(result) else FAILED
    return one_model


# ── assembly ─────────────────────────────────────────────────────────────────

def build_converter(
    targets: tuple[Any, ...],
    convert: bool,
    coerce: bool,
    accept: Callable[[Any], bool],
    ) -> Converter | None:
    """
    Build ``value -> converted value | FAILED`` for an annotation flattened to ``targets``.

    Every candidate result must satisfy ``accept`` (the annotation's own type check), so a
    converter can never produce a value the checker would reject. Returns ``None`` when no
    conversion applies to any target, so callers can skip conversion entirely.
    """
    found: list[Converter | None] = []
    if len(targets) == 1 and is_value_model(targets[0]):
        return _one_model(targets[0], coerce, accept)   # one model: its conversion and coercion in one step
    if convert or coerce:             # coercion is a superset: it includes the lossless conversions
        #* Members in declared order, a TypeModel in its place among them (models used to come
        #* first, whatever the order: float | Port made a Port of 80).
        found += [_step_of(t, False) if is_model(t) else _CONVERSIONS.get(t) for t in targets]
        if coerce:
            found += [_step_of(t, True) if is_model(t) else _coercion_for(t) for t in targets]
    steps = [step for step in found if step is not None]
    if not steps:
        return None
    ordered = tuple(dict.fromkeys(steps))

    if len(ordered) == 1:                       # the common case (e.g. float: just int -> float), without the loop
        step = ordered[0]

        def single(value: Any) -> Any:
            try:
                result = step(value)
            except BrokenHook:
                raise
            except (TypeError, ValueError, ArithmeticError):
                return FAILED
            return result if result is not FAILED and accept(result) else FAILED
        return single

    def converter(value: Any) -> Any:
        for step in ordered:
            try:
                result = step(value)
            except BrokenHook:
                raise
            except (TypeError, ValueError, ArithmeticError):   # unparsable, overflow, bad enum value...
                continue
            if result is not FAILED and accept(result):
                return result
        return FAILED

    return converter
