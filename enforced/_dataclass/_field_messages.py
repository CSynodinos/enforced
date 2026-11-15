"""
The wording of a failed assignment: to a field of a dataclass (``Field Order.qty of <Dataclass Order>``),
or to an annotated attribute of an ``enforce`` class (``Attribute Account.balance of <Class Account>``).
"""
from .._validator import _errors
from .._validator._container import type_name
from .._validator._messages import INSTANCES_ONLY, expected_text, introspected, shape_body, subject_path
from .._validator._text import made_dataclass, short_repr
from clitint import formatter
from typing import Any, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from .._validator._errors import InvalidDataError


def as_field_error(error: "InvalidDataError", cls: type) -> "InvalidDataError":
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
            problem._render = (_field_message, cls)
        elif problem.kind in ("length", "missing_key", "cycle", "invalid"):    # deep checks: the shape is wrong
            problem.origin = cls
            problem._render = (_field_shape_message, cls)


_errors.as_field_problems = _as_field_problems


def _field_origin(cls: type) -> tuple[str, str, str]:
    """``(the class's name, its label, the word for a member)``: ``Order``, ``<Dataclass Order>``, ``field``."""
    dataclass = made_dataclass(cls)
    kind = formatter(formatter("Dataclass" if dataclass else "Class", "bold_magenta"), "bold")
    cls_name = formatter(cls.__name__, 'bold_blue')
    return cls_name, f"<{kind} {cls_name}>", "field" if dataclass else "attribute"


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


#* A problem's renderer: called with the problem in front (see ``Problem.__str__``).
def _field_shape_message(problem: Any, cls: type) -> str:
    cls_name, origin, word = _field_origin(cls)
    return f"{_field_subject(cls_name, subject_path(problem), word)} of {origin}: {shape_body(problem)}"


def _field_message(problem: Any, cls: type) -> str:
    cls_name, origin, word = _field_origin(cls)
    return (
        f"{_field_subject(cls_name, problem.parameter, word)} of {origin}: "
        f"expected type: {formatter(expected_text(problem.expected, problem.annotation, problem.detail != INSTANCES_ONLY), 'bold_yellow')}, "
        f"got type {formatter(type_name(type(problem.value)), 'bold_red')} "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )
