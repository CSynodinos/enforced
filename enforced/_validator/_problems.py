"""Problems made from a value that failed: wrong type, rejected value, items inside a collection."""
from termtint import formatter
from . import _deep
from ._container import (
    TypeContainer,
    TypeUnion,
    find_uncheckable_protocol,
    matches_type,
    protocol_error,
    )
from ._errors import Problem, InvalidDataError, make_error
from ._messages import format_annotation, only_instances, parameter_type_error_msg_factory, shape_message, shortened
from ._text import break_trace_colouring
from ._type_conversion import build_converter, BrokenHook, FAILED, is_model, model_convert
from typing import Any, Callable
from functools import partial


def unresolved_error(annotation: Any, key: str) -> InvalidDataError:
    if (protocol := find_uncheckable_protocol(annotation)) is not None:
        return protocol_error(protocol, key)
    return InvalidDataError(
        break_trace_colouring + f"Cannot resolve annotation {formatter(shortened(format_annotation(annotation)), 'bold_yellow')} "
        f"for parameter {formatter(key, 'bold_green')} (needed to check its items)"
        )


def value_problems(
    fn: Callable[..., Any],
    path: str,
    value: Any,
    annotation: Any,
    node: "_deep.Node | None",
    kind: str = "type",
    allow_subclass: bool = True,
    convert: bool = False,
    coerce: bool = False,
    ) -> list[Problem]:
    """
    Problems for one failing value: a single wrong-type problem for a shallow check, or one
    problem per bad item for a deep one (``scores[3]``, ``prices['apple']``, ``point.x``).
    ``kind`` is ``"type"`` for arguments, ``"default"`` or ``"return"``.
    """
    if node is None:
        return [type_problem(TypeContainer(fn, path, value, annotation), kind, None, allow_subclass, convert, coerce)]
    issues = node.errors(value, path) or [("type", path, value, annotation, None)]
    problems: list[Problem] = []
    for tag, where, item, expected, detail in issues:
        if tag == "type":
            problems.append(
                type_problem(
                    TypeContainer(fn, where, item, expected),
                    kind, path, allow_subclass, convert, coerce
                    )
                )
            continue
        problem = Problem(tag, where, expected, None if tag == "missing_key" else item, fn, str, detail, expected)
        problem._render = (shape_message, kind == "default", path)
        problems.append(problem)
    return problems


def late_type_message(fn: Any, name: str, value: Any, annotation: Any) -> str:
    """The text of a wrong-type problem that ``PreparedChecker._problem`` made without a container."""
    return parameter_type_error_msg_factory(TypeContainer(fn, name, value, annotation))


def type_problem(
    container: TypeContainer,
    kind: str = "type",
    root: str | None = None,
    allow_subclass: bool = True,
    convert: bool = False,
    coerce: bool = False,
    keep: "TypeContainer | None" = None,
    ) -> Problem:
    """
    A wrong-type problem; the message is rendered from the container only when needed.
    ``root`` is the parameter a deep check looked inside (``e`` for the item ``e[2]``).
    When the type is right but the value isn't (an ``Annotated`` check, or a TypeModel's
    ``validate``), the problem is ``"invalid"`` with the reason in ``detail``.
    """
    if container._key == "return":
        kind = "return"
    invalid = _invalid_reason(container, allow_subclass, convert, coerce, keep)
    if invalid is not None:
        expected, reason = invalid
        problem = Problem(
            "invalid",
            container._key,
            expected,
            container._input_object,
            container._origin_obj,
            str,
            reason,
            container._annotation
            )
        problem._render = (shape_message, kind == "default", root)
        return problem
    #* A Transform that nothing here converts to is named alone, without its ``In`` (``only_instances``).
    only = only_instances(container._expected_type, convert or coerce)
    render = partial(parameter_type_error_msg_factory, container, kind == "default", root, only is None)
    #* Positional on purpose: creating an instance with a keyword argument takes Python's slow route
    #* (+140 ns measured here, on a path that is slow enough).
    return Problem(
        kind = kind,
        parameter = container._key,
        expected = container._expected_type,
        value = container._input_object,
        origin = container._origin_obj,
        render = render,
        detail = only,
        annotation = container._annotation
        )


def _invalid_reason(container: TypeContainer, allow_subclass: bool, convert: bool, coerce: bool,
                    keep: "TypeContainer | None" = None) -> "tuple[Any, str] | None":
    """
    ``(type, reason)`` when the value has the right type but is rejected by an ``Annotated``
    check, or (with ``convert``/``coerce``) by a TypeModel's ``validate``; ``None`` otherwise.

    ``keep``: a container of the same annotation that lives as long as its checker (the ``quick``
    of a plan entry, made with the same options). The converters below are kept on it: they were
    built again for every rejected value.
    """
    value = container._input_object
    if container._constraints is not None:
        candidates = [value]
        typed = any(matches_type(value, target, allow_subclass) for target, _ in container._constraints)
        if (convert or coerce) and not typed:           # 3 for Annotated[float, check] is checked as 3.0
            kept = None if keep is None else keep.__dict__.get("_candidate_converters")
            if kept is None:
                kept = [_candidate_converter(target, allow_subclass, convert, coerce) for target, _ in container._constraints]
                if keep is not None:
                    keep._candidate_converters = kept           # type: ignore[attr-defined]
            for conv in kept:
                if conv is not None and (out := conv(value)) is not FAILED:
                    candidates.append(out)
        for candidate in candidates:
            if (failure := container.constraint_failure(candidate, allow_subclass)) is not None:
                return failure
    if convert or coerce:
        expected = container._expected_type
        for target in (expected if isinstance(expected, TypeUnion) else (expected,)):
            if is_model(target):
                try:
                    _, reason = model_convert(target, value, coerce)
                except BrokenHook:
                    raise
                except Exception:
                    continue
                if reason is not None:
                    return target, reason
    return None


def _candidate_converter(target: Any, allow_subclass: bool, convert: bool, coerce: bool) -> Any:
    """What makes a candidate of ``target``'s type of a value: ``3`` for ``Annotated[float, check]`` is checked as ``3.0``."""
    targets = tuple(target) if isinstance(target, TypeUnion) else (target,)
    def accepts(v: Any, member: Any = target) -> bool:
        return matches_type(v, member, allow_subclass)
    return build_converter(targets, convert, coerce, accepts)


def validation_error_factory(problems: "list[Problem]", context: str = "call",
                             error: "type[InvalidDataError]" = InvalidDataError) -> InvalidDataError:
    """The error of ``problems``, of the class ``error`` (a checker's: see ``check_error_type``)."""
    assert len(problems) > 0, "No problems provided"
    return make_error(error, problems = problems, context = context)
