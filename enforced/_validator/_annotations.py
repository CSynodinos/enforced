"""From a function to its annotations as objects: resolving strings, ``Self``, the owner class."""
from ._container import self_stand_in, SelfType
from ._lifetime import can_go, made_for
from ._scope import SCOPE, local_names, look_again, strings_in, unwrapped
from ._signatures import signature_of
from ._text import OWNER_ATTR
from typing import (
    Annotated, Any, Callable, ForwardRef, get_args, get_origin, get_type_hints, Literal, Self,
    )
from .._compat import annotated_of, Format, get_annotations, UNION_TYPES, union_of
from dataclasses import InitVar
from functools import partial
from types import FunctionType
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
    #* A class, and the __init__ dataclasses wrote for one: each annotation is read where it was written.
    #* One set of names for the whole MRO would let a local name of a subclass replace what a base meant,
    #* and the generated __init__ would read every field in the subclass's module.
    read: "partial[dict[str, Any]]" = partial(get_type_hints, fn, localns = localns, include_extras = True)
    if owner is not None and fn is owner:
        read = partial(_class_hints, owner)
    elif owner is not None and _generated_init(fn, owner):
        read = partial(_init_hints, fn, owner)
    #* The annotated attributes of a callable object's class say nothing about the call.
    if type(fn) is not FunctionType and owner is None and _annotations_are_its_class(fn):
        record = {}
    else:
        try:
            record = read()                             # keeps Annotated checks
        except Exception:
            #* The name that isn't known may have come into being since the decorator ran (see look_again).
            #* For a generated __init__ the class is asked: its own annotations are the bases' too.
            if look_again(owner if read.func is _init_hints else fn, owner):
                localns = local_names(fn, owner)
                if read.func is get_type_hints:
                    read = partial(get_type_hints, fn, localns = localns, include_extras = True)
                try:
                    record = read()
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
    for key, value in record.items():
        if isinstance(value, InitVar) and strings_in(value):
            record[key] = _resolved_init_var(value, fn, owner, localns)
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


def _class_hints(cls: type) -> dict[str, Any]:
    """
    ``typing.get_type_hints(cls)``, each class of the MRO read in its own module with its own local names:
    those it keeps (``SCOPE``), its type parameters, and the class itself. A base that can go (written in a
    function, as the class may be) also takes what the class keeps: ``remember_scope`` looked its names up
    there, where both were written. A base its module holds means what its names mean in that module.
    """
    if getattr(cls, "__no_type_check__", None):        # as typing has it: a mark found on the class, also inherited
        return {}
    hints: dict[str, Any] = {}
    kept = vars(cls).get(SCOPE) or {}
    for klass in reversed(cls.__mro__[:-1]):            # the bases first: the class itself wins
        try:
            own = get_annotations(klass, format = Format.FORWARDREF)
        except Exception:
            continue
        if not own:
            continue
        names: dict[str, Any] = dict(kept) if klass is not cls and can_go(klass) else {}
        names.update(vars(klass).get(SCOPE) or ())
        for parameter in getattr(klass, "__type_params__", ()):
            names[parameter.__name__] = parameter
        names[cls.__name__] = cls
        module = sys.modules.get(klass.__module__)
        #* A class of its own, holding one class's annotations: typing reads them as a class's (a ClassVar is
        #* allowed, None is NoneType), with the globals and names given here and no others.
        holder = type(klass.__name__, (), {"__annotations__": dict(own), "__module__": klass.__module__})
        hints.update(get_type_hints(holder, vars(module) if module is not None else {}, names, include_extras = True))
    return hints


def _generated_init(fn: Any, owner: type) -> bool:
    """Whether ``fn`` is the ``__init__`` that ``dataclasses`` wrote for ``owner``: its parameters are fields."""
    code = getattr(fn, "__code__", None)
    return (code is not None and code.co_filename == "<string>" and getattr(fn, "__name__", None) == "__init__"
            and "__dataclass_fields__" in vars(owner) and getattr(fn, "__qualname__", None) == f"{owner.__qualname__}.__init__")


def _init_hints(fn: Any, owner: type) -> dict[str, Any]:
    """A generated ``__init__``'s annotations: its parameters, with the types the class's annotations say."""
    hints = _class_hints(owner)
    code = fn.__code__
    record = {name: hints[name] for name in code.co_varnames[1:code.co_argcount + code.co_kwonlyargcount] if name in hints}
    try:
        if "return" in get_annotations(fn, format = Format.FORWARDREF):
            record["return"] = type(None)
    except Exception:
        pass
    return record


def _resolved_init_var(value: Any, fn: Any, owner: type | None, localns: dict[str, Any] | None) -> Any:
    """``InitVar['Loc']``: ``typing`` doesn't look inside one. What can't be resolved is left, and said by the check."""
    def holder() -> None: ...
    holder.__annotations__ = {"x": value.type}
    module = sys.modules.get(getattr(owner or fn, "__module__", None) or "")
    try:
        return InitVar(get_type_hints(holder, vars(module) if module is not None else {}, localns, include_extras = True)["x"])
    except Exception:
        return value


def _annotations_are_its_class(fn: Any) -> bool:
    """
    Whether reading ``__annotations__`` on this object finds the dictionary of its class: where a class keeps
    them on 3.13, and under the future import later. ``functools.wraps`` puts them on the object itself.
    """
    if isinstance(fn, type) or "__annotations__" in getattr(fn, "__dict__", ()) or hasattr(fn, "__wrapped__"):
        return False
    return any(isinstance(vars(klass).get("__annotations__"), dict) for klass in type(fn).__mro__)


#* On a dataclass: the names of the fields that are not checked against their annotation.
UNCHECKED_FIELDS = "__enforced_unchecked__"


def has_self(annotation: Any, depth: int = 0) -> bool:
    """Whether ``Self`` stands anywhere in ``annotation``. By identity: an annotation may define ``==``."""
    if annotation is Self:
        return True
    if isinstance(annotation, InitVar):                 # keeps what it was given, and has no ``__args__``
        return depth <= 8 and has_self(annotation.type, depth + 1)
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
    if isinstance(annotation, InitVar):
        return InitVar(_with_self(annotation.type, me, depth + 1))
    origin, args = get_origin(annotation), get_args(annotation)
    if not args or depth > 8 or origin is Literal or origin is collections.abc.Callable:
        return annotation
    new = tuple([_with_self(arg, me, depth + 1) for arg in args])
    if all(a is b for a, b in zip(new, args)):
        return annotation
    try:
        if isinstance(annotation, UNION_TYPES):
            return union_of(new)
        if origin is Annotated:
            return annotated_of(new)
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
