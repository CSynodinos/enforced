"""The sentences of the messages: which parameter, what was expected, what was given."""
from .._formatting_tool import coloured, escapes, formatter
from . import _deep, _errors
from ._errors import jsonable, location, plain
from ._checks import describe_check, metadata_checks
from ._container import type_name, TypeContainer, TypeUnion
from ._lifetime import CACHE_LOCK, held, holds, make_room
from ._text import describe_origin, short_repr
from typing import Annotated, Any, Callable, get_args, get_origin, TYPE_CHECKING, Union
from functools import reduce
from operator import or_
from types import UnionType

if TYPE_CHECKING:
    from ._errors import ErrorMessage, Problem


def as_field(problem: Problem, render: Any) -> str:
    """A message about a default, worded for a dataclass field that is no parameter of ``__init__``."""
    text = render[0](problem, *render[1:]) if type(render) is tuple else render()
    return text.replace(" parameter ", " field ", 1)


def introspected(root: str | None, path: str) -> str | None:
    """
    Where ``path`` lies inside the value of ``root`` (a deep check looked inside it):
    ``"at index [2]"``, ``"at index ['apple'][1]"``, ``"at field x"``. ``None`` when ``path``
    is the parameter itself.
    """
    if root is None or path == root or not path.startswith(root):
        return None
    rest = path[len(root):]
    if rest.startswith("."):
        return f"at field {formatter(rest[1:], 'bold_green')}"
    return f"at index {formatter(rest, 'bold_green')}"


def _subject(path: str, is_default: bool = False, root: str | None = None) -> str:
    """
    The start of a message: "For parameter x", "For default value of parameter x", "For return value".
    With deep checks, an item inside ``root``: "For introspected parameter x at index [2]".
    """
    if (where := introspected(root, path)) is not None:
        if root == "return":
            return f"For introspected {formatter('return', 'bold_cyan')} value {where}"
        if is_default:
            return (f"For {formatter('default', 'bold_orange')} value of introspected parameter "
                    f"{formatter(root, 'bold_green')} {where}")
        return f"For introspected parameter {formatter(root, 'bold_green')} {where}"
    if path == "return":
        return f"For {formatter('return', 'bold_cyan')} value"
    if is_default:
        return f"For {formatter('default', 'bold_orange')} value of parameter {formatter(path, 'bold_green')}"
    return f"For parameter {formatter(path, 'bold_green')}"


def subject_path(problem: Problem) -> str:
    """Where a shape problem is reported: the mapping itself for a missing key."""
    if problem.kind == "missing_key":
        return problem.parameter[: len(problem.parameter) - len(_deep.key_label(problem.detail)) - 2]
    return problem.parameter


def shape_body(problem: Problem) -> str:
    """What is wrong, for the problems that aren't a plain wrong type."""
    if problem.kind == "length":
        wanted, got = problem.detail, len(problem.value)    # 2, or "at least 2" where the length isn't fixed
        return (
            f"expected type: {formatter(shortened(format_annotation(problem.expected)), 'bold_yellow')} with "
            f"{formatter(wanted, 'bold_yellow')} {'item' if wanted in (1, 'at least 1') else 'items'}, "
            f"got {formatter(got, 'bold_red')} {'item' if got == 1 else 'items'} "
            f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
            )
    if problem.kind == "missing_key":
        return (
            f"missing required key {formatter(repr(problem.detail), 'bold_green')} "
            f"(expecting type {formatter(format_annotation(problem.expected), 'bold_yellow')})"
            )
    if problem.kind == "invalid":
        return (
            f"invalid {formatter(_quoted(problem.expected), 'bold_yellow')}: "
            f"{formatter(problem.detail, 'bold_red')} (Value: {formatter(short_repr(problem.value), 'bold_red')})"
            )
    return (                                            # "cycle"
        f"value contains itself or is nested too deeply "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )


def shape_message(problem: Problem, is_default: bool = False, root: str | None = None) -> str:
    path = subject_path(problem)
    if problem.kind == "invalid":
        return invalid_head(problem, is_default, root) + invalid_tail(problem)
    subject = _subject(path, is_default, root)
    return f"{subject} of {describe_origin(problem.origin)}: {shape_body(problem)}"


def invalid_head(problem: Problem, is_default: bool = False, root: str | None = None) -> str:
    """
    A rejected value's message up to the reason: ``For parameter x of <Function f>: invalid 'Email': ``.
    The same for every value of one parameter that one type refuses (kept like ``type_head``).
    The message of a rejected value is the usual one after a wrong type: in one piece, the escape
    sequences as constants.
    """
    yellow, unyellow, red, unred, green, ungreen = (_STYLES or _styles()) if coloured() else _NO_STYLES
    path = problem.parameter
    if root is None and not is_default and path != "return":
        subject = f"For parameter {green}{path}{ungreen}"
    else:
        subject = _subject(path, is_default, root)
    return f"{subject} of {describe_origin(problem.origin)}: invalid {yellow}{_quoted(problem.expected)}{unyellow}: "


def invalid_tail(problem: Problem) -> str:
    """What follows ``invalid_head``: the reason and the value."""
    yellow, unyellow, red, unred, green, ungreen = (_STYLES or _styles()) if coloured() else _NO_STYLES
    return f"{red}{problem.detail}{unred} (Value: {red}{short_repr(problem.value)}{unred})"


#* The renderer of a rejected value, as ``type_problem`` sets it for an argument.
SHAPE_RENDER = (shape_message, False, None)


def missing_msg(fn: Callable[..., Any], missing: tuple[str, ...], record: dict[str, Any], inferred: bool) -> str:
    names = ", ".join(
        f"{formatter(m, 'bold_green')} (expecting type {formatter(format_annotation(record[m]), 'bold_yellow')})"
        if m in record else formatter(m, 'bold_green')
        for m in missing
        )
    noun = "argument" if len(missing) == 1 else "arguments"
    hint = " (inferred)" if inferred else ""
    return f"Missing required {noun} for {describe_origin(fn)}: {names}{hint}"


def parameter_type_error_msg_factory(container: TypeContainer, is_default: bool = False,
                                      root: str | None = None) -> ErrorMessage:
    return type_head(container, is_default, root) + type_tail(container._input_object)


def type_head(container: TypeContainer, is_default: bool = False, root: str | None = None) -> str:
    """
    A wrong-type message up to the value's type: ``For parameter x of <Function f>: expected type:
    'int', got type ``. The same for every wrong value of one parameter, so a checker keeps it
    (``PreparedChecker._problem``). In one piece, the escape sequences as constants.
    """
    special = container._literal_values is not None or container._type_arg is not None
    expected = _annotation_text(container._annotation) if special else type_name(container._expected_type)
    yellow, unyellow, red, unred, green, ungreen = (_STYLES or _styles()) if coloured() else _NO_STYLES
    key = container._key
    if root is None and not is_default and key != "return":
        prefix = f"For parameter {green}{key}{ungreen}"
    else:
        prefix = _subject(key, is_default, root)
    return f"{prefix} of {describe_origin(container._origin_obj)}: expected type: {yellow}{expected}{unyellow}, got type "


def type_tail(given: Any) -> str:
    """What follows ``type_head``: the value's type and the value."""
    yellow, unyellow, red, unred, green, ungreen = (_STYLES or _styles()) if coloured() else _NO_STYLES
    return f"{red}{type_name(type(given))}{unred} (Value: {red}{short_repr(given)}{unred})"


_STYLES: tuple[str, ...] = ()
_NO_STYLES = ("",) * 6


def _styles() -> tuple[str, ...]:
    global _STYLES
    _STYLES = escapes("bold_yellow", "bold_red", "bold_green")
    return _STYLES


def expected_text(expected: Any, annotation: Any = None) -> str:
    """
    What a message shows after "expected type". Usually the runtime type the annotation comes down to
    (``'int'``, ``'int' | 'str'``). For Literal values and ``type[X]`` that type says nothing, and can
    even equal the type of the rejected value (``expected type: 'str', got type 'str'`` for
    ``Literal['r', 'w']`` given ``'x'``): there the annotation itself is shown.
    """
    if annotation is not None:
        try:
            container = TypeContainer(None, "?", None, annotation)
            special = container._literal_values is not None or container._type_arg is not None
        except Exception:
            special = False
        if special:
            return _annotation_text(annotation)
    return type_name(expected)


def _annotation_text(annotation: Any) -> str:
    """An annotation as a message shows it in place of a type: ``Literal['r', 'w']``, ``'type[int]'``."""
    while getattr(annotation, "__value__", None) is not None:      # type Mode = Literal['r', 'w']
        annotation = annotation.__value__
    text = shortened(format_annotation(annotation))
    return text if "'" in text or '"' in text else f"'{text}'"


#* An annotation is shown as it is written, and a union of long names has no end: the first 80
#* characters say which one is meant.
_ANNOTATION_LIMIT = 80


def shortened(text: str) -> str:
    return text if len(text) <= _ANNOTATION_LIMIT else text[:_ANNOTATION_LIMIT - 3] + "..."


class _Shown:
    """Displays as the given text (a check inside a displayed ``Annotated``)."""
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _for_display(annotation: Any) -> Any:
    """
    ``annotation`` as messages show it: ``Annotated[int, "doc"]`` as ``int`` (metadata that
    isn't a check changes nothing), and ``Annotated[int, lambda x: x > 0]`` as ``Annotated[int, x > 0]``.
    """
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        inner = _for_display(args[0])
        checks = [_Shown(describe_check(check)) for check in metadata_checks(args[1:])]
        return Annotated[inner, *checks] if checks else inner
    if not args:
        return annotation
    shown = tuple(_for_display(a) for a in args)
    if all(a is b for a, b in zip(shown, args)):
        return annotation
    try:
        if isinstance(annotation, UnionType) or origin is Union:
            return reduce(or_, shown)
        return origin[shown if len(shown) != 1 else shown[0]] if origin is not None else annotation
    except Exception:
        return annotation


def _quoted(annotation: Any) -> str:
    """``'Email'``, or ``'int' | 'str'`` for a union (as wrong-type messages show types)."""
    return str(annotation) if isinstance(annotation, TypeUnion) else f"'{format_annotation(annotation)}'"


#* id(annotation) -> (the annotation, held as ``held`` holds it, its display text). Building the text of
#* ``Literal['domestic', 'eu', 'world']`` goes through ``typing``'s repr of each value: two thirds of
#* what rendering such a message cost, and the same text every time. An annotation that names a class
#* written in a function is not kept (its text says ``<locals>``): the entry would keep the class.
_SHOWN: dict[int, tuple[Any, str]] = {}
_SHOWN_MAX = 1024


def format_annotation(annotation: Any) -> str:
    """Render an annotation for display, e.g. int, list[int], int | float."""
    entry = _SHOWN.get(id(annotation))
    if entry is not None and holds(entry[0], annotation):
        return entry[1]
    text = _format_annotation(annotation)
    if "<locals>" not in text:
        key = id(annotation)
        with CACHE_LOCK:
            make_room(_SHOWN, _SHOWN_MAX)
            _SHOWN[key] = (held(annotation, _SHOWN, key), text)
    return text


def _format_annotation(annotation: Any) -> str:
    if annotation is None or annotation is type(None):
        return "None"
    if "Annotated[" in str(annotation):
        annotation = _for_display(annotation)
    if isinstance(annotation, type) and not get_args(annotation):
        return annotation.__name__
    text = str(annotation).replace("typing.", "")
    return _starred(text) if "Unpack[" in text else text


def _starred(text: str) -> str:
    """``tuple[int, Unpack[tuple[str, ...]]]`` as it is written today: ``tuple[int, *tuple[str, ...]]``."""
    while (start := text.find("Unpack[")) >= 0:
        depth, end = 0, start + 6
        for end in range(start + 6, len(text)):
            depth += (text[end] == "[") - (text[end] == "]")
            if depth == 0:
                break
        text = f"{text[:start]}*{text[start + 7:end]}{text[end + 1:]}"
    return text


# ── TypeCheckerError.errors(): each problem as data, in plain words ──────────

def problem_details(problem: Problem, context: str, include_input: bool, include_context: bool) -> list[dict[str, Any]]:
    """
    The entries of ``TypeCheckerError.errors()`` for one problem: one, or for missing arguments
    one per name. ``msg`` says what is wrong as the message does after "For parameter x of ...:",
    without colours and without the value, which is ``input`` (and is left out with it).
    """
    kind = problem.kind
    if kind == "missing":
        entries: list[dict[str, Any]] = []
        for name, annotation in zip(problem.parameter, problem.expected):
            entry: dict[str, Any] = {"type": "missing", "loc": [name], "msg": "missing required argument"}
            if include_context:
                entry["ctx"] = _ctx(problem, context, annotation)
            entries.append(entry)
        return entries
    entry = {"type": kind, "loc": location(problem.parameter), "msg": _short_message(problem)}
    if include_input and kind != "missing_key":         # a missing key has no value to show
        entry["input"] = jsonable(problem.value)
    if include_context:
        shown = problem.expected if kind == "invalid" or problem.annotation is None else problem.annotation
        entry["ctx"] = _ctx(problem, context, shown)
    return [entry]


def _short_message(problem: Problem) -> str:
    """What is wrong, in the words of the message, but no more than that."""
    kind = problem.kind
    try:
        if kind == "invalid":
            return f"invalid {_quoted(problem.expected)}: {problem.detail}"
        if kind == "length":
            wanted, got = problem.detail, len(problem.value)
            return (f"expected type: {shortened(format_annotation(problem.expected))} with {wanted} "
                    f"{'item' if wanted in (1, 'at least 1') else 'items'}, got {got} {'item' if got == 1 else 'items'}")
        if kind == "missing_key":
            return f"missing required key {problem.detail!r} (expecting type {format_annotation(problem.expected)})"
        if kind == "cycle":
            return "value contains itself or is nested too deeply"
        #* "type", "default", "return", "field": a wrong type.
        return f"expected type: {expected_text(problem.expected, problem.annotation)}, got type {type_name(type(problem.value))}"
    except Exception:                                   # a problem that was pickled and lost a part: its own text
        return plain(str(problem))


def _ctx(problem: Problem, context: str, expected: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    if expected is not None:
        try:
            ctx["expected"] = shortened(format_annotation(expected))
        except Exception:
            ctx["expected"] = short_repr(expected, 80)
    kind = problem.kind
    if kind == "invalid":
        ctx["reason"] = str(problem.detail)
    elif kind == "length":
        ctx["expected_length"] = jsonable(problem.detail)
        try:
            ctx["actual_length"] = len(problem.value)
        except Exception:
            pass
    elif kind == "missing_key":
        ctx["key"] = jsonable(problem.detail)
    ctx["origin"] = plain(describe_origin(problem.origin)).strip("<>")
    ctx["context"] = context
    return ctx


_errors.details_of = problem_details
