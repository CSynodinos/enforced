"""From a function to its annotations as objects: resolving strings, ``Self``, the owner class."""
from ._container import self_stand_in, SelfType
from ._lifetime import made_for
from ._scope import local_names, look_again, unwrapped
from ._signatures import signature_of
from ._text import OWNER_ATTR
from typing import (
    Annotated, Any, Callable, ForwardRef, get_args, get_origin, get_type_hints, Literal, Self, Union,
    )
from annotationlib import get_annotations
from functools import partial
from types import FunctionType, UnionType
import collections
import collections.abc
import inspect
import sys


#* ``PreparedChecker.self_in``: where the annotations of a method use ``Self``.
SELF_IN_PARAMETERS, SELF_IN_RETURN = 1, 2
SELF_ANYWHERE = SELF_IN_PARAMETERS | SELF_IN_RETURN


def tag_owner(fn: Callable[..., Any], owner: type) -> None:
    """Record which class a wrapped function belongs to, for error labels."""
    try:
        setattr(fn, OWNER_ATTR, owner)
    except (AttributeError, TypeError):  # builtins etc. can't take attributes
        pass


def resolve_annotations(fn: Callable[..., Any], owner: type | None = None, strict_self: bool = False,
                         me: type | None = None, uses: dict[str, bool] | None = None) -> dict[str, Any]:
    """
    The annotations of ``fn`` as objects: strings are evaluated in its module, with the names that
    are only visible where it was written (``local_names``).

    ``Self`` becomes ``me``: the class a method is called on, where the caller knows it (see
    ``_route``). Without ``me`` it becomes ``owner``, or with ``strict_self`` a stand-in that
    accepts ``owner`` and its subclasses: the class of the instance isn't known there, and the
    exact type of the owner would reject every instance of a subclass (see ``SelfType``).
    ``uses`` collects the entries in which ``Self`` stands: name -> whether it is the whole annotation.
    """
    localns = local_names(fn, owner)
    record: Any = None
    try:
        record = get_type_hints(fn, localns = localns, include_extras = True)   # keeps Annotated checks
    except Exception:
        #* The name that isn't known may have come into being since the decorator ran (see look_again).
        if look_again(fn, owner):
            localns = local_names(fn, owner)
            try:
                record = get_type_hints(fn, localns = localns, include_extras = True)
            except Exception:
                pass
    if record is None:
        try:
            raw = get_annotations(fn)
        except Exception:
            raw = {}
        globalns = getattr(unwrapped(fn), "__globals__", {})
        record = {}
        for key, value in raw.items():
            if isinstance(value, str):
                try:
                    value = eval(value, globalns, localns)
                except Exception:
                    value = ForwardRef(value)
            record[key] = value
    if not record and (borrowed := _annotations_of_what_it_calls(fn, owner, strict_self)) is not None:
        return borrowed
    if owner is not None:
        #* Fields of a dataclass whose values a descriptor takes care of (see ``_dataclass.api``).
        if unchecked := vars(owner).get(UNCHECKED_FIELDS):
            record = {k: v for k, v in record.items() if k not in unchecked}
        with_self = [k for k, v in record.items() if has_self(v)]
        if with_self:
            if uses is not None:
                uses.update({k: record[k] is Self for k in with_self})
            if me is None:
                me = self_stand_in(owner) if strict_self else owner
            record = {k: _with_self(v, me) if k in with_self else v for k, v in record.items()}
            if me is not owner and type(me) is not SelfType:
                #* Written for the class of one call: kept by the checker of that class, by no cache.
                made_for(me, [record[k] for k in with_self])
        #* A class written inside a function, and an annotation of its own method that names it
        #* (``others: list["Node"]``): the class holds the method, the method the annotation, and a
        #* cache entry about the annotation would hold the class. Not cached, so that all three can go.
        if "<locals>" in owner.__qualname__:
            made_for(owner, list(record.values()))
    return record


#* On a dataclass: the names of the fields that are not checked against their annotation.
UNCHECKED_FIELDS = "__enforced_unchecked__"


def has_self(annotation: Any, depth: int = 0) -> bool:
    """Whether ``Self`` stands anywhere in ``annotation``. By identity: an annotation may define ``==``."""
    if annotation is Self:
        return True
    args = getattr(annotation, "__args__", None)
    if not args or depth > 8 or type(args) is not tuple:
        return False
    for arg in args:
        if has_self(arg, depth + 1):
            return True
    return False


def _with_self(annotation: Any, me: Any, depth: int = 0) -> Any:
    """``annotation`` with ``me`` wherever ``Self`` stands in it: ``Self | None``, ``list[Self]``, ``type[Self]``."""
    if annotation is Self:
        return me
    origin, args = get_origin(annotation), get_args(annotation)
    if not args or depth > 8 or origin is Literal or origin is collections.abc.Callable:
        return annotation
    new = tuple([_with_self(arg, me, depth + 1) for arg in args])
    if all(a is b for a, b in zip(new, args)):
        return annotation
    try:
        if isinstance(annotation, UnionType) or origin is Union:
            return Union[new]
        if origin is Annotated:
            return Annotated[new]
        return origin[new if len(new) != 1 else new[0]]
    except Exception:
        return annotation


def _annotations_of_what_it_calls(fn: Any, owner: type | None, strict_self: bool) -> dict[str, Any] | None:
    """
    For a callable that carries no annotations of its own: those of what it calls. An object with
    ``__call__`` is checked against that method, and a ``functools.partial`` against the function
    it wraps, for the parameters it still takes. ``None`` for anything else (a builtin, a function
    that simply has no annotations).
    """
    if isinstance(fn, partial):
        source: Any = fn.func
    elif isinstance(fn, type) or inspect.isroutine(fn):
        return None
    else:
        source = getattr(type(fn), "__call__", None)
        if type(source) is not FunctionType:
            return None
        owner = type(fn)
    record = resolve_annotations(source, owner, strict_self)
    try:
        taken = signature_of(fn).parameters
    except (TypeError, ValueError):
        return None
    return {name: annotation for name, annotation in record.items() if name in taken or name == "return"}


def find_owner(fn: Any, args: tuple[Any, ...]) -> tuple[type, bool] | None:
    """
    The class that a function decorated on its own is a method of, and whether it was found
    through the first argument (``self`` or ``cls``). Without it ``Self`` and the type parameters
    of the class can't be resolved, and messages say ``<Function name>``. A class decorated with
    ``enforce`` tells its methods directly; this is for ``@validate`` on a method of any other.
    """
    if type(fn) is not FunctionType:
        return None
    prefix = fn.__qualname__.rpartition(".")[0]
    if not prefix or prefix.endswith(">"):              # a function of a module, or one defined inside another
        return None
    module, name = fn.__module__, fn.__name__
    if args:
        first = args[0]
        for klass in (first if isinstance(first, type) else type(first)).__mro__:
            if klass.__qualname__ == prefix and klass.__module__ == module and _holds(klass, name):
                return klass, True
    found: Any = sys.modules.get(module)                # a static method has no such argument: by name
    for part in prefix.split("."):
        found = getattr(found, part, None)
    if isinstance(found, type) and found.__qualname__ == prefix and _holds(found, name):
        return found, False
    return None


def _holds(cls: type, name: str) -> bool:
    """Whether ``cls`` itself has an attribute of this name (a private one is stored under its mangled name)."""
    return name in vars(cls) or f"_{cls.__name__.lstrip('_')}{name}" in vars(cls)
