"""What ``enforce`` checks in a class: which special methods, properties, and what it leaves alone."""
from ._annotations import tag_owner
from ._wrapping import checked_inside, wrap_callable
from typing import Any, Callable
from functools import cached_property
import inspect


def enforce_property(cls: type, name: str, attr: Any, allow_subclass: bool, check_return: bool,
                      convert: bool, coerce: bool, deep: bool, warn: bool = False) -> None:
    """
    A property (or ``functools.cached_property``) of a class given to ``enforce``: what is
    assigned is checked against the setter's annotation, and with ``check_return`` what the getter
    returns against its own. Only an accessor with something to check is wrapped: a getter without
    ``check_return`` has nothing (it takes ``self`` alone), and stays the function it was, so
    reading the attribute costs what it did. One that is marked ``skip_typecheck`` or
    ``typing.no_type_check``, has no annotation, or carries its own ``@typecheck`` is left alone.
    """
    def checked(fn: Any, returns: bool) -> Any:
        if not inspect.isfunction(fn) or getattr(fn, SKIP, False) or getattr(fn, "__no_type_check__", False):
            return fn
        own = checked_inside(fn) if hasattr(fn, "__wrapped__") else None
        if own is not None:                             # its own @typecheck: those options stand
            adopt(own, cls, True)
            return fn
        if unannotated(fn):
            return fn
        return wrap_callable(fn, allow_subclass, returns, cls, skip_first = True,
                              convert = convert, coerce = coerce, deep = deep, warn = warn)

    if isinstance(attr, cached_property):
        if check_return:
            attr.func = checked(attr.func, True)        # the object stays: it knows the name it was given
        return
    getter = checked(attr.fget, True) if check_return else attr.fget
    setter = checked(attr.fset, False)
    if getter is not attr.fget or setter is not attr.fset:
        made = attr
        if getter is not attr.fget:
            made = made.getter(getter)                  # getter() and setter(): a property of the same class, doc kept
        if setter is not attr.fset:
            made = made.setter(setter)
        setattr(cls, name, made)


#* Set by ``skip_typecheck`` on what ``enforce`` is to leave alone.
SKIP = "__enforced_skip__"


#* The special methods ``enforce`` checks: those whose arguments a caller writes (``Point(1, 2)``,
#* ``obj(x)``, ``obj[key] = value``, ``key in obj``), and ``__enter__`` / ``__aenter__`` for what
#* ``with`` binds. The rest are called by Python itself, often with any object at all: ``==`` and the
#* operators must be able to answer NotImplemented, and ``__exit__`` receives None three times on a
#* normal exit, whatever its annotations say. Those stay as they are; ``@typecheck`` on one still works.
CHECKED_SPECIAL = frozenset({
    "__init__", "__new__", "__call__", "__getitem__", "__setitem__", "__delitem__", "__contains__",
    "__enter__", "__aenter__",
    })
#* What these return is the instance being built: there is nothing of the caller's to check.
CONSTRUCTORS = frozenset({"__init__", "__new__"})


def held_by_a_base(cls: type, name: str, fn: Callable[..., Any]) -> bool:
    """
    Whether ``fn`` is a function a base class holds under ``name`` too: it was handed down, not
    defined for ``cls`` (every ``Enum`` class carries ``Enum.__new__`` in its own namespace).
    Wrapping it would label a method of another class with this one.
    """
    for base in cls.__mro__[1:]:
        held = vars(base).get(name)
        if held is not None and getattr(held, "__func__", held) is fn:
            return True
    return False


def unannotated(fn: Any) -> bool:
    """
    Whether a function has no annotation at all, found out without evaluating any: one that has
    some carries an ``__annotate__`` function, or under ``from __future__ import annotations``
    the dictionary of strings.
    """
    try:
        return fn.__annotate__ is None and not fn.__annotations__
    except Exception:
        return False


def adopt(wrapper: Callable[..., Any], owner: type, skip_first: bool) -> None:
    """
    Tell a method that carries its own ``@typecheck`` which class it belongs to, so that ``Self``
    and the class's own name resolve, and messages read ``<Method Owner.name>``. Nothing else of
    it changes. Too late once the method has been called: its annotations are resolved by then.
    """
    checker = wrapper.__globals__.get("_pv_checker")
    if checker is None or checker.owner is not None or checker.ready:
        return
    checker.owner, checker.skip_first = owner, skip_first
    tag_owner(checker.fn, owner)
    tag_owner(wrapper, owner)


def enforce_members(cls: type, allow_subclass: bool, check_return: bool, convert: bool, coerce: bool, deep: bool,
                    warn: bool = False, leave: "frozenset[str] | set[str]" = frozenset()) -> None:
    """
    Wrap, in place, what ``cls`` itself defines and a caller hands values to: every function,
    static method and class method in its own namespace, its properties (``enforce_property``),
    and of the special methods those in ``CHECKED_SPECIAL``. What ``enforce`` does to a class, and
    ``enforced.dataclass`` to the methods of one.

    Left as they are: a method marked ``skip_typecheck`` or ``typing.no_type_check``, one without
    any annotation, one with its own ``@typecheck`` (those options stand; it is only told its
    class), a special method that a base class holds too, and the names in ``leave``.
    """
    rebuild: Any                                        # None, or the decorator the function was inside
    for name, attr in list(vars(cls).items()):
        if name in leave:
            continue
        if inspect.isfunction(attr):
            fn, rebuild, skip_first = attr, None, True
        elif isinstance(attr, staticmethod) and inspect.isfunction(attr.__func__):
            #* Python stores __new__ as a static method; its first parameter is the class all the same.
            fn, rebuild, skip_first = attr.__func__, staticmethod, name == "__new__"
        elif isinstance(attr, classmethod) and inspect.isfunction(attr.__func__):
            fn, rebuild, skip_first = attr.__func__, classmethod, True
        elif isinstance(attr, (property, cached_property)):
            enforce_property(cls, name, attr, allow_subclass, check_return, convert, coerce, deep, warn)
            continue
        else:
            continue
        #* Only a method that some decorator wrapped has ``__wrapped__``: the usual one skips the search.
        own = checked_inside(fn) if hasattr(fn, "__wrapped__") else None
        if own is not None:                             # its own @typecheck: those options stand
            adopt(own, cls, skip_first)
            continue
        if name.startswith("__") and name.endswith("__"):
            if name not in CHECKED_SPECIAL:
                continue  # leave the other dunders (__eq__, __repr__, ...) alone
            if name != "__init__" and held_by_a_base(cls, name, fn):
                continue
        if getattr(fn, SKIP, False) or (rebuild is not None and getattr(attr, SKIP, False)):
            continue
        #* Nothing to check: no annotation at all, or typing.no_type_check. The method stays plain.
        if unannotated(fn) or getattr(fn, "__no_type_check__", False):
            continue
        checked = wrap_callable(fn, allow_subclass, check_return and name not in CONSTRUCTORS, cls,
                                skip_first = skip_first, convert = convert, coerce = coerce, deep = deep, warn = warn)
        setattr(cls, name, checked if rebuild is None else rebuild(checked))

