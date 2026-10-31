"""Signatures: where a function's is kept, ``**kwargs: Unpack[TypedDict]`` laid out, stand-in functions."""
from ._errors import InvalidDataError
from ._text import break_trace_colouring, describe_origin
from typing import (
    Any, Callable, get_args, get_origin, get_type_hints, is_typeddict, NotRequired, ReadOnly, Required,
    Unpack,
    )
from types import FunctionType
import inspect
import weakref


def signature_stub(name: str, record: dict[str, Any]) -> Callable[..., Any]:
    """Build a no-op function whose name and signature come from a record."""
    try:
        params = [
            inspect.Parameter(key, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation = annotation)
            for key, annotation in record.items() if key != "return"
            ]
    except ValueError as e:  # e.g. a key that isn't a valid identifier
        raise InvalidDataError(break_trace_colouring + f"Invalid record for {name!r}: {e}") from None

    def stub(*args: Any, **kwargs: Any) -> None: ...
    stub.__name__ = stub.__qualname__ = name
    stub.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return stub


def own_signature(fn: Any) -> bool:
    """Whether ``fn`` is a function whose defaults are its own: not borrowed via ``__wrapped__`` / ``__signature__``."""
    return type(fn) is FunctionType and not hasattr(fn, "__wrapped__") and "__signature__" not in vars(fn)


#* The default of a keyword that ``**kwargs: Unpack[SomeTypedDict]`` makes optional: nothing was passed.
class _NotGiven:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<not given>"


NOT_GIVEN: Any = _NotGiven()


def typed_kwargs(record: dict[str, Any], sig: inspect.Signature) -> tuple[dict[str, Any], inspect.Signature]:
    """
    ``**kwargs: Unpack[Movie]`` says that the keywords are the keys of the TypedDict ``Movie``.
    Such a function is checked as if each key were a keyword-only parameter: the record gets one
    entry per key in place of the one for ``kwargs``, and the signature shows the same. Required
    keys, value types, conversion and unknown keywords then need nothing of their own.

    Both are returned and belong to the checker that asked. The function and its cached signature
    stay as they are, so another checker of the same function (``validate_record`` with a
    record of its own) sees ``**kwargs`` as it is written.
    """
    #* The usual function takes no **kwargs at all, and when it does it is the last parameter.
    parameters = list(sig.parameters.values())
    last = parameters[-1] if parameters else None
    if last is None or last.kind is not inspect.Parameter.VAR_KEYWORD:
        return record, sig
    annotation = record.get(last.name)
    if get_origin(annotation) is not Unpack or not is_typeddict(get_args(annotation)[0]):
        return record, sig
    typed_dict = get_args(annotation)[0]
    try:
        hints = {key: _unqualified(hint) for key, hint in get_type_hints(typed_dict, include_extras = True).items()}
        sig = _with_typed_kwargs(sig, hints, frozenset(typed_dict.__required_keys__))
    except Exception:
        return record, sig
    out = {key: annotation for key, annotation in record.items() if key != last.name}
    for key, annotation in hints.items():
        out.setdefault(key, annotation)                 # a real parameter of that name keeps its own annotation
    return out, sig


def _unqualified(annotation: Any) -> Any:
    """``Required[str]`` as ``str``: whether a key is required is the parameter's business, not its type's."""
    while get_origin(annotation) in (Required, NotRequired, ReadOnly):
        annotation = get_args(annotation)[0]
    return annotation


class _KeyParameter(inspect.Parameter):
    """
    A keyword-only parameter named by a TypedDict key that is no identifier (``"my-key"``,
    ``"class"``). Such a keyword can still be passed, as ``f(**{"my-key": 1})``, so it is checked
    like the others. ``inspect.Parameter`` refuses the name; nothing else about it is different.
    """
    __slots__ = ()

    def __init__(self, name: str, default: Any, annotation: Any) -> None:
        self._name, self._kind, self._default, self._annotation = name, inspect.Parameter.KEYWORD_ONLY, default, annotation


def _with_typed_kwargs(sig: inspect.Signature, hints: dict[str, Any], required: frozenset[str]) -> inspect.Signature:
    """``sig`` with its ``**kwargs`` replaced by one keyword-only parameter per key of the TypedDict."""
    P = inspect.Parameter
    parameters = [p for p in sig.parameters.values() if p.kind is not P.VAR_KEYWORD]
    taken = {p.name for p in parameters}
    for key, annotation in hints.items():
        if key in taken:
            continue
        default = P.empty if key in required else NOT_GIVEN
        try:
            parameters.append(P(key, P.KEYWORD_ONLY, annotation = annotation, default = default))
        except ValueError:
            parameters.append(_KeyParameter(key, default, annotation))
    return sig.replace(parameters = parameters)


#* For a callable that is no function (an object with ``__call__``, a partial, a builtin).
_SIGNATURES: "weakref.WeakKeyDictionary[Callable[..., Any], inspect.Signature]" = weakref.WeakKeyDictionary()


_ANY_ARGUMENTS = inspect.Signature([
    inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL),
    inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
    ])


#* Where a function keeps its signature: (id of the function, the signature). On the function, not in
#* ``_SIGNATURES``: a signature holds the annotations, an annotation can name a class, and the class
#* can hold the function (its method, or a checker made for it). A weak key whose value leads back
#* to the key never goes, so such a class, made at run time, stayed for good. Kept together, the
#* two are an ordinary cycle. The id says whose it is: functools.wraps copies the attribute along.
_SIGNATURE = "__enforced_signature__"


def forget_signature(fn: Any) -> None:
    """The cached signature of ``fn`` no longer holds (its defaults were rewritten)."""
    if type(fn) is FunctionType:
        fn.__dict__.pop(_SIGNATURE, None)
    else:
        _SIGNATURES.pop(fn, None)


def signature_of(fn: Callable[..., Any]) -> inspect.Signature:
    """``inspect.signature`` with a per-function cache (it is slow, and the error path needs it)."""
    plain = type(fn) is FunctionType
    if plain:
        entry = fn.__dict__.get(_SIGNATURE)
        if entry is not None and entry[0] == id(fn):
            return entry[1]
    else:
        try:
            return _SIGNATURES[fn]
        except (KeyError, TypeError):           # TypeError: not weak-referenceable / unhashable
            pass
    try:
        sig = inspect.signature(fn)
    except ValueError:
        #* A builtin that doesn't say what it takes (max, min, ...): it takes whatever it is given.
        #* Nothing can be checked, but the call must still go through.
        sig = _ANY_ARGUMENTS
    except TypeError as e:
        #* Not a fault of the call: the callable describes itself wrongly (a ``__signature__`` that is none).
        raise InvalidDataError(
            break_trace_colouring + f"Cannot read the signature of {describe_origin(fn)}: {e}"
            ) from None
    if plain:
        fn.__dict__[_SIGNATURE] = (id(fn), sig)
        return sig
    try:
        _SIGNATURES[fn] = sig
    except TypeError:
        pass
    return sig
