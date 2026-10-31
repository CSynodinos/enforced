"""
What a dispatcher raises: a value that no candidate takes (one ``"dispatch"`` problem per
candidate, with that candidate's own reasons), a version that can never be chosen, and an
anchor that can't be read.
"""
from .._formatting_tool import formatter
from .._validator import _messages
from .._validator._container import type_name
from .._validator._errors import InvalidDataError, Problem, jsonable, location, make_error, plain, said_error
from .._validator._messages import format_annotation, short_message, shortened
from .._validator._problems import value_problems
from .._validator._text import break_trace_colouring, describe_origin, short_repr
from .._validator import _deep
from .._validator._annotations import tag_owner
from .._validator._text import OWNER_ATTR
from typing import Any, TYPE_CHECKING
import os

if TYPE_CHECKING:
    from ._candidates import Candidate


def anchor_text(annotation: Any) -> str:
    """An anchor as messages show it."""
    try:
        return shortened(format_annotation(annotation))
    except Exception:
        return short_repr(annotation, 80)


def which(candidate: "Candidate") -> str:
    """``version 2 (list[int])``, or ``the base (Any)``."""
    shown = anchor_text(candidate.annotation)
    return f"version {candidate.number} ({shown})" if candidate.number else f"the base ({shown})"


def version_label(base: Any, candidate: "Candidate") -> str:
    """
    How messages name a version: ``<Version 2 (str) of <Function worker>, line 16>`` (the file too, where
    it isn't the base's). Made when a message is, from what is known then: a method's class is found at
    its first call, by the version's checker or the base's.
    """
    fn = candidate.fn
    owner = getattr(fn, OWNER_ATTR, None)
    if owner is not None and getattr(base, OWNER_ATTR, None) is None:
        tag_owner(base, owner)                          # a dispatchmethod whose base hasn't been called yet
    code = getattr(fn, "__code__", None)
    where = ""
    if code is not None:
        base_file = getattr(getattr(base, "__code__", None), "co_filename", None)
        place = "" if code.co_filename == base_file else f"{os.path.basename(code.co_filename)}, "
        where = f", {place}line {code.co_firstlineno}"
    return (f"<{formatter('Version', 'bold_magenta')} {candidate.number} ({anchor_text(candidate.annotation)}) "
            f"of {describe_origin(base)}{where}>")


# ── a value no candidate takes ───────────────────────────────────────────────

def no_version_error(label_of: Any, value: Any, candidates: "tuple[Candidate, ...]", allow_subclass: bool,
                     cls: "type[InvalidDataError]") -> InvalidDataError:
    """
    The error of a value that no candidate takes. Its problems are made at once (the value is the
    caller's, and may change before they are read: as ``_deep_entry_problems`` does); the message,
    when it is read.
    """
    problems = [_refusal(label_of, candidate, value, allow_subclass) for candidate in candidates]
    return make_error(cls, problems = problems, context = "dispatch")


def _refusal(label_of: Any, candidate: "Candidate", value: Any, allow_subclass: bool) -> Problem:
    anchor = candidate.anchor
    node = anchor.node if anchor is not None and not isinstance(anchor.node, _deep.Leaf) else None
    #* A TypeModel at the top takes a raw value through ``validate``: its refusal is the reason
    #* (found as conversion finds it, ``_invalid_reason``).
    models = bool(anchor is not None and anchor.models)
    inner = value_problems(candidate.fn, candidate.name, value, candidate.annotation, node, "type", allow_subclass,
                           models, False)
    return Problem("dispatch", candidate.name, candidate.annotation, value, candidate.fn,
                   (_render_refusal, label_of, which(candidate)), (candidate.number, tuple(inner)), candidate.annotation)


def _reasons(problem: Problem) -> list[str]:
    detail = problem.detail
    if type(detail) is not tuple or len(detail) != 2:
        return []
    texts = []
    for inner in detail[1]:
        text = short_message(inner)
        texts.append(text if inner.parameter == problem.parameter else f"at {inner.parameter}: {text}")
    return texts


def _render_refusal(problem: Problem, label_of: Any, which_one: str) -> str:
    reasons = _reasons(problem)
    shown = "; ".join(reasons[:3]) + (f"; and {len(reasons) - 3} more" if len(reasons) > 3 else "")
    head = which_one[0].upper() + which_one[1:]
    return (f"{head} of {describe_origin(label_of)} refuses {formatter(problem.parameter, 'bold_green')}: "
            f"{shown} (Value: {formatter(short_repr(problem.value), 'bold_red')})")


def _details(problem: Problem, context: str, include_input: bool, include_context: bool) -> list[dict[str, Any]]:
    """``errors()`` for a ``"dispatch"`` problem: one entry, ``loc`` the parameter and the version's number."""
    detail = problem.detail
    number = detail[0] if type(detail) is tuple and len(detail) == 2 else None
    entry: dict[str, Any] = {
        "type": "dispatch",
        "loc": [*location(problem.parameter), number],
        "msg": "; ".join(plain(text) for text in _reasons(problem)) or plain(str(problem)),
        }
    if include_input:
        entry["input"] = jsonable(problem.value)
    if include_context:
        inner = detail[1] if number is not None else ()
        entry["ctx"] = {
            "version": number,
            "anchor": plain(anchor_text(problem.annotation)),
            "reasons": [{"type": p.kind, "loc": location(p.parameter), "msg": plain(short_message(p))} for p in inner],
            "origin": plain(describe_origin(problem.origin)).strip("<>"),
            "context": context,
            }
    return [entry]


_messages.KIND_DETAILS["dispatch"] = _details


# ── a call without its anchor ────────────────────────────────────────────────

def no_anchor_error(label_of: Any, name: str, kwargs: dict[str, Any], cls: "type[InvalidDataError]") -> InvalidDataError:
    if name in kwargs:
        return said_error(f"{describe_origin(label_of)} takes {formatter(name, 'bold_green')} positionally: it "
                          f"chooses the version, whose parameter may have another name", cls)
    return said_error(f"Missing required argument {formatter(name, 'bold_green')} of {describe_origin(label_of)}: "
                      f"the argument that chooses the version", cls)


# ── what refuses a version, where it is registered ───────────────────────────

def refused(label_of: Any, text: str) -> InvalidDataError:
    """A refusal of a version or of the dispatcher itself: always an ``InvalidDataError`` (as for every decorator)."""
    return InvalidDataError(break_trace_colouring + f"dispatch of {describe_origin(label_of)}: {text}")


def describe_part(part: tuple[Any, ...]) -> str:
    kind = part[0]
    try:
        if kind == "any":
            return "every value"
        if kind in ("class", "model", "protocol"):
            return type_name(part[1])
        if kind == "value":
            return short_repr(part[1], 40)
        if kind == "classof":
            return f"type[{type_name(part[1]).strip(chr(39))}]"
        if kind == "checked":
            return " | ".join(describe_part(p) for p in part[1]) + " with its checks"
        if kind == "node":
            return anchor_text(part[1].annotation)
    except Exception:
        pass
    return str(part[-1])


def unreachable_error(label_of: Any, candidate: "Candidate", found: "list[tuple[tuple[Any, ...], Candidate]]",
                      base: "Candidate | None" = None) -> InvalidDataError:
    """
    The refusal of ``candidate``, a version that can never be chosen (``found``: each part of its
    anchor and the candidate that takes it), or, with ``base``, one after which the base can't be.
    """
    head = which(candidate)
    if not found:
        return refused(label_of, f"{head} can never be chosen: its anchor takes no value")
    lines = "\n".join(f"    {formatter(describe_part(part), 'bold_yellow')} is taken by {which(by)}" for part, by in found)
    if base is not None:
        return refused(label_of, f"{head} leaves {which(base)} unreachable: it would never be called\n{lines}")
    return refused(label_of, f"{head} can never be chosen: what it takes is taken before it\n{lines}")
