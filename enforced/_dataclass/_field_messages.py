"""The wording of a failed field assignment."""
from .._typechecker import _errors
from .._typechecker._container import type_name
from .._typechecker._messages import expected_text, introspected, shape_body, subject_path
from .._typechecker._text import short_repr
from ..formatting_tool import formatter
from typing import Any, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from .._typechecker._errors import TypeCheckerError


def as_field_error(error: TypeCheckerError, cls: type) -> TypeCheckerError:
    """
    Re-label a failed assignment: ``Field qty of <Dataclass Order>: ...`` and
    ``1 problem found in assignment``. Still lazy: nothing is formatted until printed, and the
    problems of an error that hasn't made them yet are worded when it does.
    """
    if error._problems is None:
        error._field_of = cls
    else:
        _as_field_problems(error._problems, cls)
    error.context = "field assignment"
    return error


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
    kind = formatter(formatter("Dataclass", "bold_magenta"), "bold")
    cls_name = formatter(cls.__name__, 'bold_blue')
    return cls_name, f"<{kind} {cls_name}>"


def _field_subject(cls_name: str, path: str) -> str:
    """``Field Order.qty``, or for an item inside a field ``Introspected field Order.lines at index [1][1]``."""
    root = re.match(r"[^\[.]+", path).group()               # type: ignore[union-attr]  # the field name: an identifier
    if (where := introspected(root, path)) is not None:
        return f"Introspected field {cls_name}.{formatter(root, 'bold_green')} {where}"
    return f"Field {cls_name}.{formatter(path, 'bold_green')}"


def _field_message_of(problem: Any, cls: type) -> str:
    """``_field_message`` as a problem's own renderer (see ``Problem.__str__``)."""
    return _field_message(cls, problem)


def _field_shape_message_of(problem: Any, cls: type) -> str:
    return _field_shape_message(cls, problem)


def _field_shape_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return f"{_field_subject(cls_name, subject_path(problem))} of {origin}: {shape_body(problem)}"


def _field_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return (
        f"{_field_subject(cls_name, problem.parameter)} of {origin}: "
        f"expected type: {formatter(expected_text(problem.expected, problem.annotation), 'bold_yellow')}, "
        f"got type {formatter(type_name(type(problem.value)), 'bold_red')} "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )
