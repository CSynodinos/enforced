"""
The wording of a failed assignment: to a field of a dataclass (``Field Order.qty of <Dataclass Order>``),
or to an annotated attribute of an ``enforce`` class (``Attribute Account.balance of <Class Account>``).
"""
from .._validator import _errors
from .._validator._container import type_name
from .._validator._messages import expected_text, introspected, shape_body, subject_path
from .._validator._text import made_dataclass, short_repr
from .._formatting_tool import formatter
from typing import Any, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from .._validator._errors import InvalidDataError


def as_field_error(error: InvalidDataError, cls: type) -> InvalidDataError:
    """
    Re-label a failed assignment: ``Field qty of <Dataclass Order>: ...`` and
    ``1 problem found in assignment``. Still lazy: nothing is formatted until printed, and the
    problems of an error that hasn't made them yet are worded when it does.
    """
    if error._problems is None:
        error._field_of = cls
    else:
        _as_field_problems(error._problems, cls)
    error.context = assignment_context(cls)
    return error


def assignment_context(cls: type) -> str:
    """What a failed assignment is called: ``field assignment``, or for a plain class ``attribute assignment``."""
    return "field assignment" if made_dataclass(cls) else "attribute assignment"


def _as_field_problems(problems: list[Any], cls: type) -> None:
    for problem in problems:
        if problem.kind == "type":
            problem.kind = "field"
            problem.origin = cls
            problem._render = (_field_message_of, cls)
        elif problem.kind in ("length", "missing_key", "cycle", "invalid"):    # deep checks: the shape is wrong
            problem.origin = cls
            problem._render = (_field_shape_message_of, cls)


_errors.as_field_problems = _as_field_problems


def _field_origin(cls: type) -> tuple[str, str]:
    kind = formatter(formatter("Dataclass" if made_dataclass(cls) else "Class", "bold_magenta"), "bold")
    cls_name = formatter(cls.__name__, 'bold_blue')
    return cls_name, f"<{kind} {cls_name}>"


def _field_subject(cls_name: str, path: str, word: str = "field") -> str:
    """
    ``Field Order.qty``, or for an item inside a field ``Introspected field Order.lines at index [1][1]``.
    ``word`` is ``"attribute"`` for a plain class.
    """
    head = word.capitalize()
    if "[" not in path and "." not in path:                 # the field itself, as nearly always: no pattern to run
        return f"{head} {cls_name}.{formatter(path, 'bold_green')}"
    root = re.match(r"[^\[.]+", path).group()               # type: ignore[union-attr]  # the field name: an identifier
    if (where := introspected(root, path)) is not None:
        return f"Introspected {word} {cls_name}.{formatter(root, 'bold_green')} {where}"
    return f"{head} {cls_name}.{formatter(path, 'bold_green')}"


def _word(cls: type) -> str:
    return "field" if made_dataclass(cls) else "attribute"


def _field_message_of(problem: Any, cls: type) -> str:
    """``_field_message`` as a problem's own renderer (see ``Problem.__str__``)."""
    return _field_message(cls, problem)


def _field_shape_message_of(problem: Any, cls: type) -> str:
    return _field_shape_message(cls, problem)


def _field_shape_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return f"{_field_subject(cls_name, subject_path(problem), _word(cls))} of {origin}: {shape_body(problem)}"


def _field_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return (
        f"{_field_subject(cls_name, problem.parameter, _word(cls))} of {origin}: "
        f"expected type: {formatter(expected_text(problem.expected, problem.annotation), 'bold_yellow')}, "
        f"got type {formatter(type_name(type(problem.value)), 'bold_red')} "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )
