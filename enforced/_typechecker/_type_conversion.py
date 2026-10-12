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
    float        -> int                       (whole numbers only: 3.0 -> 3, 3.5 is rejected)
    int, float   -> bool                      (0 and 1 only)
    str <-> bytes                             (UTF-8)
    value        -> Enum member               (Color("red") -> Color.RED)
    list, tuple, set, frozenset -> each other

**TypeModel** targets (``Email``, ``Port`` ...) are built from a raw value of their base type
under ``convert`` (``"a@b.com"`` -> ``Email("a@b.com")``), after the base type's own conversion
or, with ``coerce``, coercion (``"8080"`` -> ``8080`` -> ``Port(8080)``). Set the class flag
``auto_construct = False`` to only accept existing instances.

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

    if any(_in_mro(target, "datetime", name) for name in ("datetime", "date", "time")):
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


def model_convert(target: Any, value: Any, coerce: bool) -> tuple[Any, str | None]:
    """
    ``(instance | FAILED, reason)``: build ``target`` from ``value``, converting (or coercing) it
    to the base type first if needed. ``reason`` is set when the value had the right type but
    ``validate`` rejected it.
    """
    out, reason = target.__enforced_convert__(value)
    if out is not FAILED or reason is not None:
        return out, reason
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


def _model_step(target: Any, coerce: bool) -> Converter:
    base = target.__base_type__

    def step(value: Any) -> Any:
        if type(value) is base:                 # the common case (a plain str for an Email): build it directly
            try:
                return target(value)
            except ValueError:
                return FAILED
        return model_convert(target, value, coerce)[0]
    return step


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
    if len(targets) == 1 and is_model(targets[0]):
        found.append(_model_step(targets[0], coerce))   # one model: its conversion and coercion in one step
    elif convert or coerce:             # coercion is a superset: it includes the lossless conversions
        #* Members in declared order, a TypeModel in its place among them (models used to come
        #* first, whatever the order: float | Port made a Port of 80).
        found += [_model_step(t, False) if is_model(t) else _CONVERSIONS.get(t) for t in targets]
        if coerce:
            found += [_model_step(t, True) if is_model(t) else _coercion_for(t) for t in targets]
    steps = [step for step in found if step is not None]
    if not steps:
        return None
    ordered = tuple(dict.fromkeys(steps))

    if len(ordered) == 1:                       # the common case (e.g. float: just int -> float), without the loop
        step = ordered[0]

        def single(value: Any) -> Any:
            try:
                result = step(value)
            except (TypeError, ValueError, ArithmeticError):
                return FAILED
            return result if result is not FAILED and accept(result) else FAILED
        return single

    def converter(value: Any) -> Any:
        for step in ordered:
            try:
                result = step(value)
            except (TypeError, ValueError, ArithmeticError):   # unparsable, overflow, bad enum value...
                continue
            if result is not FAILED and accept(result):
                return result
        return FAILED

    return converter
