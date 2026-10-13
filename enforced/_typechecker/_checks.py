"""Checks in ``Annotated`` metadata: the ``Check`` marker, running them, and naming one in a message."""
from ._text import short_repr
from typing import Any, Callable
from functools import partial
import weakref


#* A check may also reject a value by raising one of these (its message becomes the reason).
#* LookupError: ``lambda s: s[0] == "a"`` given ``""`` rejects it, and used to escape as an IndexError.
CHECK_ERRORS = (ValueError, TypeError, ArithmeticError, LookupError)


class Check:
    """
    Marks a callable in the metadata of ``Annotated`` as a check of the value:

        Port = Annotated[int, Check(lambda p: 0 < p < 65536)]

    The check runs once the type is right. It accepts by returning a truthy value; it rejects by
    returning a falsy one, or by raising ``ValueError``, ``TypeError``, ``ArithmeticError`` or
    ``LookupError`` (the message becomes the reason).

    A callable written into the metadata as it is, ``Annotated[int, lambda p: p > 0]``, is read
    the same way: that is the short form. They behave identically. ``Check`` makes it more documented.
    """
    __slots__ = ("check",)
    check: Callable[[Any], Any]

    def __init__(self, check: Callable[[Any], Any]) -> None:
        if isinstance(check, Check):                    # Check(Check(f)) is Check(f)
            check = check.check
        if not callable(check):
            raise TypeError(f"Check() takes the function that checks a value, got {type(check).__name__}: {short_repr(check)}")
        self.check = check

    def __call__(self, value: Any) -> Any:
        return self.check(value)

    def __repr__(self) -> str:
        return f"Check({describe_check(self.check)})"

    #* Two annotations with the same check are the same annotation: typecheck_record finds its
    #* cached checker by comparing records.
    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Check) and other.check == self.check

    def __hash__(self) -> int:
        return hash((Check, self.check))

    def __reduce__(self) -> tuple[Any, ...]:
        return (Check, (self.check,))


def metadata_checks(metadata: tuple[Any, ...]) -> tuple[Callable[[Any], Any], ...]:
    """
    The checks among the metadata of an ``Annotated``: what each ``Check`` wraps, and every other
    callable that is no class (the short form). What a ``Check`` wraps is called directly, so the
    marker costs nothing per call.
    """
    return tuple([m.check if isinstance(m, Check) else m for m in metadata if callable(m) and not isinstance(m, type)])


def check_failure(check: Callable[[Any], Any], value: Any) -> str | None:
    """
    Why ``check`` rejects ``value`` (``None`` if it accepts it). A check answers yes or no; where
    the "no" was something else that happens to be falsy (``''`` from ``str.strip``, ``0`` from
    ``len``), the reason says what came back: a function that was meant to transform the value
    then shows itself for what it is, instead of looking like a check that failed.
    """
    try:
        result = check(value)
    except CHECK_ERRORS as e:
        return refusal(check, True, str(e))
    if result:
        return None
    return refusal(check, False, result)


def refusal(check: Callable[[Any], Any], raised: bool, answer: Any) -> str:
    """The reason a check gave by refusing: the text of what it raised, or what it returned (falsy)."""
    if raised:
        return answer or f"failed check {describe_check(check)}"
    if answer is False or answer is None:
        return f"failed check {describe_check(check)}"
    return f"failed check {describe_check(check)}, which returned {short_repr(answer)}"


#* The last value a check of ``Annotated[T, check]`` refused: the value, the check, whether it
#* raised, and the text it raised or what it returned. The message of the error that follows needs
#* the reason, and used to run the check again to get it (review finding 46: a failing check ran
#* twice on the general path, three times from a compiled wrapper). Left by the predicate of the
#* annotation, read once and emptied by ``PreparedChecker._problem``, right after the predicate
#* failed; value and check are compared by identity, so what anything else left here is not taken.
REFUSED: list[Any] = [None, None, False, None]


#* id(check) -> (a weak reference to the check, its description). Asked on the path of every
#* rejected value: a WeakKeyDictionary makes a reference at each lookup (150 ns against 30).
_DESCRIBED: "dict[int, tuple[Any, str]]" = {}


def _undescribe(key: int, gone: Any) -> None:
    held = _DESCRIBED.get(key)
    if held is not None and held[0] is gone:
        _DESCRIBED.pop(key, None)


def describe_check(check: Callable[[Any], Any]) -> str:
    """A readable name for a check: its name, or a lambda's own source (``x > 0``). Cached per check."""
    held = _DESCRIBED.get(id(check))
    if held is not None and held[0]() is check:
        return held[1]
    text = _describe_check(check)
    try:
        _DESCRIBED[id(check)] = (weakref.ref(check, partial(_undescribe, id(check))), text)
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
