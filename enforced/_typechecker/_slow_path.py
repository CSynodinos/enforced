"""
The full path: ``Signature.bind_partial`` and everything wrong with a call, with hints for
misplaced arguments; and the long way for a return value.
"""
from ._container import TypeContainer
from ._errors import Problem, step, InvalidDataError
from ._messages import missing_msg
from ._problems import type_problem, typechecker_type_error_factory, unresolved_error, value_problems
from ._signatures import signature_of
from ._specs import deep_node, SLOW
from ._text import break_trace_colouring
from typing import Any, Callable, TYPE_CHECKING
from functools import lru_cache, partial
import inspect

if TYPE_CHECKING:
    from ._container import TypeContainerList


def full_check(
    fn: Callable[..., Any],
    record: dict[str, Any],
    allow_subclass: bool,
    args: tuple[Any, ...] = (),
    kwargs: "dict[str, Any] | None" = None,
    skip_first: bool = False,
    deep: bool = False,
    nodes: "dict[str, Any] | None" = None,
    sig: "inspect.Signature | None" = None,
    ) -> None:
    """
    The full path: bind one call of ``fn`` the way Python would, check it against ``record``
    (parameter name -> annotation) and raise a ``InvalidDataError`` listing every problem. It is
    where a call ends up that doesn't bind cleanly (a missing, an extra or a duplicate argument).
    With ``deep``, items inside collections are checked too; ``nodes`` passes the deep checks the
    caller has compiled already, and ``sig`` the signature it binds with (``fn``'s own otherwise).

    The public ``typecheck_function`` is something else: it goes through a ``PreparedChecker``.
    """
    if sig is None:
        sig = signature_of(fn)
    if kwargs is None:
        kwargs = {}

    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError as e:
        raise InvalidDataError(break_trace_colouring + str(e)) from None
    arguments = dict(bound.arguments)

    #* bind_partial binds f(p=1) to a positional-only `p`, when an earlier parameter is left to its
    #* default. A real call sends it to **kwargs: move such values where Python actually puts them.
    #* Without **kwargs the call can't be made at all, and Python says so in these words.
    var_kw = next((n for n, p in sig.parameters.items() if p.kind is inspect.Parameter.VAR_KEYWORD), None)
    if kwargs:
        by_keyword = [name for i, (name, p) in enumerate(sig.parameters.items())
                      if p.kind is inspect.Parameter.POSITIONAL_ONLY and i >= len(args) and name in kwargs]
        if by_keyword:
            if var_kw is None:
                raise InvalidDataError(
                    break_trace_colouring + "got some positional-only arguments passed as keyword arguments: "
                    + repr(", ".join(by_keyword))
                    )
            for name in by_keyword:
                if name in arguments:
                    arguments.setdefault(var_kw, {})[name] = arguments.pop(name)

    def find_missing(supplied: dict[str, Any]) -> list[str]:
        return [
            name for name, p in sig.parameters.items()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            and name not in supplied
            ]

    missing = find_missing(arguments)
    likely_shifted = False

    #* If something is missing, see whether skipping different parameters explains the call better.
    if missing and args:
        realigned = _realign_positional(fn, record, allow_subclass, args, kwargs, skip_first, sig)
        if realigned is not None:
            arguments = {**realigned, **kwargs}
            missing = find_missing(arguments)
            likely_shifted = True

    #* Problems are collected as data; the coloured text is only built if someone reads it.
    problems: list[Problem] = []
    if missing:
        problems.append(Problem(
            "missing", tuple(missing), tuple(record.get(m) for m in missing), None, fn,
            partial(missing_msg, fn, tuple(missing), record, likely_shifted),
            ))

    #* Only supplied arguments are checked; defaults were validated separately.
    supplied_record = {k: v for k, v in record.items() if k in arguments}
    containers = _load_to_type_containers(fn, supplied_record, arguments, sig)
    if nodes is None and not deep:
        problems += [type_problem(c, allow_subclass = allow_subclass) for c in containers if not c.check(allow_subclass)]
    else:
        for c in containers:
            root = c._key.split("[", 1)[0]                          # "args[2]" -> "args"
            node = nodes.get(root) if nodes is not None else deep_node(record[root], allow_subclass, False, False)
            if node is SLOW:
                raise unresolved_error(record[root], root)
            if node is None:
                if not c.check(allow_subclass):
                    problems.append(type_problem(c, allow_subclass = allow_subclass))
            elif not node.check(c._input_object):
                problems += value_problems(fn, c._key, c._input_object, record[root], node, "type", allow_subclass)

    if problems:
        raise typechecker_type_error_factory(problems)


def typecheck_return_pipeline(
    fn: Callable[..., Any],
    record: dict[str, Any],
    allow_subclass: bool,
    result: Any,
    node: Any = None,
    convert: bool = False,
    coerce: bool = False,
    ) -> None:
    """
    Perform runtime type checking for a function's return value against its annotation.

    Args:
        fn: The function being checked.
        record: A dictionary mapping parameter names to their expected types.
        allow_subclass: Whether to allow subclasses to satisfy type constraints.
        result: The actual return value of the function.
        node: The compiled deep check for the return annotation, if any.

    Raises:
        TypeError: If the return value fails the type check.
    """
    if "return" not in record:
        return
    return_type = record["return"]
    if return_type is None:          # -> None annotation stored as None by get_annotations
        return_type = type(None)
    if node is SLOW:
        raise unresolved_error(return_type, "return")
    if node is not None:
        if not node.check(result):
            raise typechecker_type_error_factory(value_problems(fn, "return", result, return_type, node, "return",
                                                                  allow_subclass, convert, coerce))
        return
    container = TypeContainer(fn, "return", result, return_type)
    if not container.check(allow_subclass):
        raise typechecker_type_error_factory([type_problem(container, "return", None, allow_subclass, convert, coerce)])


def _realign_positional(
    fn: Callable[..., Any],
    record: dict[str, Any],
    allow_subclass: bool,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    skip_first: bool = False,
    sig: "inspect.Signature | None" = None,
    ) -> dict[str, Any] | None:
    """
    Find the order-preserving placement of positional args that best fits the annotations.
    Returns None when the naive left-to-right placement is already as good (or no better).
    """
    P = inspect.Parameter
    if sig is None:
        sig = signature_of(fn)
    if any(p.kind is P.VAR_POSITIONAL for p in sig.parameters.values()):
        return None
    cands = [
        p for p in sig.parameters.values() if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD) and p.name not in kwargs
        ]
    n, k = len(cands), len(args)
    if k >= n:
        return None

    def matches(i: int, j: int) -> bool:
        name = cands[j].name
        if name not in record:
            return True
        return TypeContainer(fn, name, args[i], record[name]).check(allow_subclass)

    #* Every argument fits where it stands (the usual call with one left out): no other placement
    #* can fit more of them, and the search below is not made.
    naive = sum(matches(i, i) for i in range(k))
    if naive == k:
        return None

    NEG = -10**9

    @lru_cache(maxsize = None)
    def best(i: int, j: int) -> tuple[int, tuple[int, ...]]:
        if i == k:
            return 0, ()
        if j == n:
            return NEG, ()
        s, rest = best(i + 1, j + 1)
        assign = (s + matches(i, j), (j,) + rest)
        #* Only required parameters may be skipped, and never self.
        if cands[j].default is P.empty and not (skip_first and j == 0):
            skip = best(i, j + 1)
            if skip[0] > assign[0]:
                return skip
        return assign

    score, placement = best(0, 0)
    if score <= naive:
        return None
    return {cands[j].name: args[i] for i, j in enumerate(placement)}


def _load_to_type_containers(origin_obj: Any, record: dict[str, Any], arguments: dict[str, Any],
                             sig: "inspect.Signature | None" = None) -> TypeContainerList:
    record_of_type_containers: list[TypeContainer] = []
    sig_params = (sig or signature_of(origin_obj)).parameters
    for key, expected_type in record.items():
        if key == "return":
            continue
        value = arguments.get(key)
        param = sig_params.get(key)
        if param is not None and param.kind is inspect.Parameter.VAR_POSITIONAL:
            # *args: T — check each element against T individually
            for i, item in enumerate(value or ()):
                record_of_type_containers.append(TypeContainer(origin_obj, step(key, f"[{i}]", i), item, expected_type))
        elif param is not None and param.kind is inspect.Parameter.VAR_KEYWORD:
            # **kwargs: T — check each value against T individually
            for k, v in (value or {}).items():
                record_of_type_containers.append(TypeContainer(origin_obj, step(key, f"[{k}]", k), v, expected_type))
        else:
            record_of_type_containers.append(TypeContainer(origin_obj, key, value, expected_type))
    return record_of_type_containers
