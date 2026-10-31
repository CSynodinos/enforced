"""Default values: checked when a function is first called, and where a converted one is put."""
from ._container import TypeContainer
from ._messages import as_field
from ._problems import validation_error_factory, unresolved_error, value_problems
from ._signatures import forget_signature, NOT_GIVEN, own_signature, signature_of
from ._specs import compile_converter, deep_node, SLOW
from ._type_conversion import FAILED
from typing import Any, Callable, TYPE_CHECKING
from types import FunctionType
import dataclasses
import inspect

if TYPE_CHECKING:
    from ._errors import Problem


#* Placeholder for: no value was passed, call the factory
_DATACLASS_FACTORY = getattr(dataclasses, "_HAS_DEFAULT_FACTORY", None)


#* Defaults a definition has besides its parameters' (a dataclass field that __init__ doesn't take):
#* a callable returning ``(name, default, annotation, store)`` for each. See ``check_defaults``.
type ExtraDefaults = Callable[[], list[tuple[str, Any, Any, Callable[[Any], None]]]]


def check_defaults(
    fn: Callable[..., Any],
    record: dict[str, Any],
    allow_subclass: bool,
    convert: bool = False,
    coerce: bool = False,
    rewrite: bool = False,
    deep: bool = False,
    extra: "ExtraDefaults | None" = None,
    resolve: "Callable[[str], Any] | None" = None,
    sig: "inspect.Signature | None" = None,
    ) -> dict[str, tuple[inspect.Parameter, Any]]:
    """
    Validate annotated defaults (a wrong default is a definition error).

    With ``convert``/``coerce``, a default that can be converted is accepted, e.g.
    ``x: float = 0``. The converted ones are returned (name -> its parameter and the value): it is
    the caller's business how the function comes to receive ``0.0`` (see ``PreparedChecker._prepare``).
    With ``rewrite`` they are written straight into ``fn.__defaults__`` / ``__kwdefaults__``.
    With ``deep``, the items inside a default collection are checked too.

    ``extra`` lists the defaults that belong to the definition without being parameters of ``fn``
    (a dataclass field that ``__init__`` doesn't take), as ``(name, default, annotation, store)``.
    A converted one is handed to ``store``, which puts it where it is read from.
    """
    messages: list[Problem] = []
    converted: dict[str, tuple[inspect.Parameter, Any]] = {}
    stored: list[tuple[Callable[[Any], None], Any]] = []
    #* (name, default, annotation, where a converted value goes)
    defaults: list[tuple[str, Any, Any, Any]] = [
        (name, p.default, record[name], p) for name, p in (sig or signature_of(fn)).parameters.items()
        if p.default is not inspect.Parameter.empty and p.default is not _DATACLASS_FACTORY
        and p.default is not NOT_GIVEN and name in record
        ]
    if extra is not None:
        defaults += extra()
    for name, default, annotation, target in defaults:
        node = deep_node(annotation, allow_subclass, convert, coerce, resolve) if deep else None
        if node is SLOW:
            raise unresolved_error(annotation, name)
        if node is None:
            if TypeContainer(fn, name, default, annotation).check(allow_subclass):
                continue
        elif node.check(default):
            continue
        converter = compile_converter(annotation, allow_subclass, name, convert, coerce, deep, resolve)
        if converter is not None and (value := converter(default)) is not FAILED:
            if isinstance(target, inspect.Parameter):
                converted[name] = (target, value)
            else:
                stored.append((target, value))
            continue
        found = value_problems(fn, name, default, annotation, node, "default", allow_subclass, convert, coerce)
        if not isinstance(target, inspect.Parameter):   # a dataclass field that __init__ doesn't take: no parameter
            for problem in found:
                problem._render = (as_field, problem._render)
        messages += found
    if messages:
        raise validation_error_factory(messages, context="definition")
    if converted and rewrite and own_signature(fn):
        _rewrite_defaults(fn, converted, sig or signature_of(fn))
        forget_signature(fn)                       # the cached signature still shows the old defaults
    for store, value in stored:
        store(value)
    return converted


def _rewrite_defaults(fn: Any, converted: dict[str, tuple[inspect.Parameter, Any]], sig: inspect.Signature) -> None:
    """Swap converted defaults into a plain function's ``__defaults__`` / ``__kwdefaults__`` (``sig`` is its signature)."""
    P = inspect.Parameter
    positional = [p.name for p in sig.parameters.values() if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
    defaults = list(fn.__defaults__ or ())
    kwdefaults = dict(fn.__kwdefaults__ or {})
    offset = len(positional) - len(defaults)
    for name, (p, value) in converted.items():
        if p.kind is P.KEYWORD_ONLY:
            kwdefaults[name] = value
        else:
            defaults[positional.index(name) - offset] = value
    fn.__defaults__ = tuple(defaults)
    fn.__kwdefaults__ = kwdefaults or None


def copy_with_defaults(fn: Any, converted: dict[str, tuple[inspect.Parameter, Any]], sig: inspect.Signature) -> Any:
    """
    A copy of ``fn`` that has the converted defaults: same code, same globals, same closure. The
    wrapper calls the copy, so the function receives ``0.0`` for ``x: float = 0`` at no cost per
    call, and the function that was handed to ``validate`` keeps the defaults it was written with:
    whoever still holds it sees no change, and a second wrapper of it starts from the same defaults.
    """
    copy = FunctionType(fn.__code__, fn.__globals__, fn.__name__, fn.__defaults__, fn.__closure__, fn.__kwdefaults__)
    copy.__dict__.update(fn.__dict__)
    copy.__qualname__, copy.__module__, copy.__doc__ = fn.__qualname__, fn.__module__, fn.__doc__
    copy.__type_params__ = fn.__type_params__
    if fn.__annotate__ is not None:
        copy.__annotate__ = fn.__annotate__
    _rewrite_defaults(copy, converted, sig)
    return copy


#* ``rewrite_defaults`` of a checker whose function is nobody else's: converted defaults go straight into it.
IN_PLACE = "in place"
#* ... and of one that only checks a call for somebody else: converted defaults go back with the arguments.
PASSED = "passed"
