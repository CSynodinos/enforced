from ..formatting_tool import formatter
from .. import _environment
from . import _deep
from ._type_conversion import (
    FAILED,
    _REJECTED,
    build_converter,
    is_model,
    is_model_class,
    model_convert
    )
from ._type_container import (
    OWNER_ATTR,
    break_trace_colouring,
    CHECK_ERRORS,
    ErrorMessage,
    TypeCheckerError,
    pending_error,
    said_error,
    TypeContainer,
    TypeContainerList,
    Problem,
    TypeUnion,
    excludes_bool,
    matches_type,
    matches_class,
    is_abstract,
    uncheckable_protocol,
    protocol_error,
    constraints_pass,
    describe_check,
    metadata_checks,
    short_repr,
    describe_origin,
    held,
    holds,
    made_for,
    make_room,
    not_cached,
    self_stand_in,
    type_name,
    SelfType,
    )
from ._file_types import FileType
from typing import (
    Annotated, Any, Callable, ForwardRef, Literal, NotRequired, ReadOnly, Union,
    Required, TypedDict, Self, Unpack,
    get_args, get_origin, get_type_hints, is_typeddict, overload,
    )
from types import CodeType, FunctionType, GenericAlias, MethodType, UnionType
from collections.abc import Mapping
import collections
import collections.abc
from annotationlib import Format, get_annotations
from functools import cached_property, partial, lru_cache, reduce, update_wrapper
from operator import or_
import __future__
import builtins
import dataclasses
import inspect
import re
import sys
import threading
import weakref


#* Placeholder for: no value was passed, call the factory
_DATACLASS_FACTORY = getattr(dataclasses, "_HAS_DEFAULT_FACTORY", None)
_MISSING = object()

#* Defaults a definition has besides its parameters' (a dataclass field that __init__ doesn't take):
#* a callable returning ``(name, default, annotation, store)`` for each. See ``_check_defaults``.
type _ExtraDefaults = Callable[[], list[tuple[str, Any, Any, Callable[[Any], None]]]]


@overload
def typecheck[F: Callable[..., Any]](
    obj: F, allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ...,
    ) -> F: ...
@overload
def typecheck[F: Callable[..., Any]](
    obj: None = ..., allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ...,
    ) -> Callable[[F], F]: ...
def typecheck(
    obj: Callable[..., Any] | None = None,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    ) -> Any:
    """
    Enforce the type annotations of a function or a method at runtime: the arguments of every
    call, and with ``check_return`` what it returns.

    A class is not accepted: decorate it with ``enforce`` (and a dataclass with
    ``enforced.dataclass``).

    Args:
        obj (Callable): The function or method to decorate. Also what ``@classmethod``,
            ``@staticmethod``, ``@property`` or ``functools.cached_property`` made of one.
        allow_subclass (bool): When ``True`` (default), subclass instances satisfy a
            type constraint (``isinstance`` semantics).  When ``False``, the
            type must match exactly.
        check_return (bool): When ``True``, the return value is also type-checked against
            its annotation.
        convert (bool): When ``True`` (default), a value that fails its check but has a
            lossless equivalent of the right type is converted instead of rejected:
            ``1`` becomes ``1.0`` for a ``float`` parameter (the PEP 484 numeric tower).
        coerce (bool): When ``True``, also parse or narrow values pydantic-style:
            ``"42"`` -> ``42``, ``3.0`` -> ``3``, ``"yes"`` -> ``True``, ``"red"`` -> ``Color.RED``.
            Off by default. See ``enforced._typechecker._type_conversion`` for the full table.
            Coercion applies to what comes in (arguments, defaults), never to return values: with
            ``check_return`` they are converted like any value (``1`` -> ``1.0``), but not parsed.
        deep (bool): When ``True``, also check the items inside collections, at every depth:
            ``list[int]`` checks every item, ``dict[str, list[int]]`` every key, value and
            nested item, ``tuple[int, str]`` each position and the length, a ``TypedDict``
            its required keys and values. Errors point at the bad item (``scores[3]``).
            With ``convert``/``coerce``, items are converted too, into a new container
            (the caller's object is never changed). Off by default: checking every item
            costs time proportional to the data.

    Returns:
        The callable, wrapped with runtime type validation.

    Example:

        @typecheck
        def greet(name: str) -> str:
            return f"Hello, {name}"

        class Account:
            @typecheck(check_return = True)
            def deposit(self, amount: float) -> float:
                return amount
    """
    #* ENFORCED_TYPECHECK_OFF=1: nothing is wrapped, and what was given comes back as it is.
    if _environment.TYPECHECK_OFF:
        return _unchanged if obj is None else obj
    if obj is None:
        return partial(
            typecheck,
            allow_subclass = allow_subclass,
            check_return = check_return,
            convert = convert,
            coerce = coerce,
            deep = deep
            )
    else:
        #* Function: the usual case, tested first so that decorating one costs no more than it did.
        if type(obj) is FunctionType:
            if "<locals>" in obj.__qualname__:          # defined inside a function: see _remember_scope
                _remember_scope(obj, sys._getframe(1))
            return _wrap_callable(obj, allow_subclass, check_return, convert = convert, coerce = coerce, deep = deep)
        #* Another callable, or what a decorator such as @classmethod made of a function.
        else:
            return _wrap_member(obj, allow_subclass, check_return, convert, coerce, deep, sys._getframe(1))


@overload
def enforce[T: type](
    obj: T, allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ...,
    ) -> T: ...
@overload
def enforce[T: type](
    obj: None = ..., allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ...,
    ) -> Callable[[T], T]: ...
def enforce(
    obj: type | None = None,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    ) -> Any:
    """
    Enforce the type annotations of a class at runtime: the arguments of ``__init__`` and of
    every ordinary method, static method and class method the class defines, on every call.

    Of the special methods, those a caller hands values to are checked as well: ``__new__``,
    ``__call__``, ``__getitem__``, ``__setitem__``, ``__delitem__``, ``__contains__``, and (for
    what they return, with ``check_return``) ``__enter__`` and ``__aenter__``.

    Properties are checked too: what is assigned, against the setter's annotation, and with
    ``check_return`` what the getter (or a ``functools.cached_property``) returns.

    Only a plain class is accepted. A dataclass has ``enforced.dataclass``, and a function
    or a single method has ``typecheck``.

    A method is left as it is when it:

    - is marked with ``@skip_typecheck``: it isn't checked at all;
    - has its own ``@typecheck(...)``: it keeps those options and isn't checked a second time;
    - is any other special method (``__eq__``, ``__add__``, ``__repr__``, ``__exit__``, ...:
      Python itself calls these, often with any object at all), or inherited from a base class.

    Args:
        obj (type): The class to decorate.
        allow_subclass (bool): When ``True`` (default), subclass instances satisfy a
            type constraint (``isinstance`` semantics).  When ``False``, the
            type must match exactly.
        check_return (bool): When ``True``, what each method returns is also type-checked
            against its annotation (not for ``__init__`` and ``__new__``: they build the instance).
        convert (bool): When ``True`` (default), a value that fails its check but has a
            lossless equivalent of the right type is converted instead of rejected
            (``1`` -> ``1.0`` for a ``float`` parameter).
        coerce (bool): When ``True``, also parse or narrow values (``"42"`` -> ``42``).
            Off by default. Never applied to return values.
        deep (bool): When ``True``, also check the items inside collections, at every depth.
            Off by default.

    The options mean what they mean for ``typecheck``, whose docstring has the details.

    Returns:
        The same class, its methods wrapped with runtime type validation.

    Example:

        @enforce
        class Point:
            def __init__(self, x: float, y: float) -> None:
                self.x = x
                self.y = y

            def moved(self, dx: float, dy: float) -> "Point":
                return Point(self.x + dx, self.y + dy)

            @skip_typecheck
            def debug(self, sink) -> None:
                print(self.x, self.y, file = sink)
    """
    if _environment.TYPECHECK_OFF:                      # ENFORCED_TYPECHECK_OFF=1: the class stays as it was written
        return _unchanged if obj is None else obj
    if obj is None:
        return partial(enforce, allow_subclass = allow_subclass, check_return = check_return,
                       convert = convert, coerce = coerce, deep = deep)

    if not isinstance(obj, type):
        shown = describe_origin(obj) if callable(obj) else formatter(short_repr(obj, 60), "bold_red")
        raise TypeCheckerError(
            break_trace_colouring + f"enforce cannot check {shown}: it checks classes. "
            + formatter("A function or a method is checked by @typecheck", "bold_yellow")
            )
    #* Only a class that was made a dataclass itself: a plain subclass of one is a plain class.
    if _is_dataclass(obj):
        raise TypeCheckerError(
            break_trace_colouring + f"enforce cannot check {describe_origin(obj)}: it checks plain classes. "
            + formatter("A dataclass is checked by enforced.dataclass, and a method of one by @typecheck", "bold_yellow")
            )
    if "<locals>" in obj.__qualname__:                  # a class defined inside a function: see _remember_scope
        _remember_scope(obj, sys._getframe(1))

    rebuild: Any                                        # None, or the decorator the function was inside
    for name, attr in list(vars(obj).items()):
        if inspect.isfunction(attr):
            fn, rebuild, skip_first = attr, None, True
        elif isinstance(attr, staticmethod) and inspect.isfunction(attr.__func__):
            #* Python stores __new__ as a static method; its first parameter is the class all the same.
            fn, rebuild, skip_first = attr.__func__, staticmethod, name == "__new__"
        elif isinstance(attr, classmethod) and inspect.isfunction(attr.__func__):
            fn, rebuild, skip_first = attr.__func__, classmethod, True
        elif isinstance(attr, (property, cached_property)):
            _enforce_property(obj, name, attr, allow_subclass, check_return, convert, coerce, deep)
            continue
        else:
            continue
        #* Only a method that some decorator wrapped has ``__wrapped__``: the usual one skips the search.
        own = _checked_inside(fn) if hasattr(fn, "__wrapped__") else None
        if own is not None:                             # its own @typecheck: those options stand
            _adopt(own, obj, skip_first)
            continue
        if name.startswith("__") and name.endswith("__"):
            if name not in _CHECKED_SPECIAL:
                continue  # leave the other dunders (__eq__, __repr__, ...) alone
            if name != "__init__" and _held_by_a_base(obj, name, fn):
                continue
        if getattr(fn, _SKIP, False) or (rebuild is not None and getattr(attr, _SKIP, False)):
            continue
        #* Nothing to check: no annotation at all, or typing.no_type_check. The method stays plain.
        if _unannotated(fn) or getattr(fn, "__no_type_check__", False):
            continue
        checked = _wrap_callable(fn, allow_subclass, check_return and name not in _CONSTRUCTORS, obj,
                                 skip_first = skip_first, convert = convert, coerce = coerce, deep = deep)
        setattr(obj, name, checked if rebuild is None else rebuild(checked))
    return obj


def _enforce_property(cls: type, name: str, attr: Any, allow_subclass: bool, check_return: bool,
                      convert: bool, coerce: bool, deep: bool) -> None:
    """
    A property (or ``functools.cached_property``) of a class given to ``enforce``: what is
    assigned is checked against the setter's annotation, and with ``check_return`` what the getter
    returns against its own. Only an accessor with something to check is wrapped: a getter without
    ``check_return`` has nothing (it takes ``self`` alone), and stays the function it was, so
    reading the attribute costs what it did. One that is marked ``skip_typecheck`` or
    ``typing.no_type_check``, has no annotation, or carries its own ``@typecheck`` is left alone.
    """
    def checked(fn: Any, returns: bool) -> Any:
        if not inspect.isfunction(fn) or getattr(fn, _SKIP, False) or getattr(fn, "__no_type_check__", False):
            return fn
        own = _checked_inside(fn) if hasattr(fn, "__wrapped__") else None
        if own is not None:                             # its own @typecheck: those options stand
            _adopt(own, cls, True)
            return fn
        if _unannotated(fn):
            return fn
        return _wrap_callable(fn, allow_subclass, returns, cls, skip_first = True,
                              convert = convert, coerce = coerce, deep = deep)

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


def _unchanged[X](obj: X) -> X:
    """What ``@typecheck(...)`` and ``@enforce(...)`` decorate with while every check is switched off."""
    return obj


#* Set by ``skip_typecheck`` on what ``enforce`` is to leave alone.
_SKIP = "__enforced_skip__"
def skip_typecheck[M](member: M) -> M:
    """
    Mark a method of an ``enforce`` class as not to be checked: the class decorator leaves it
    exactly as it is, so calling it costs nothing extra.

    It can be written above or below ``@classmethod`` and ``@staticmethod``, and returns what it
    was given. It only speaks to ``enforce``: an explicit ``@typecheck`` on the same method still
    checks it.

        @enforce
        class Report:
            def add(self, line: str) -> None: ...          # checked

            @skip_typecheck
            def render(self, sink) -> None: ...            # not checked
    """
    #* The mark goes on the object and on the function inside it, so that it is found whichever
    #* side of @classmethod / @staticmethod / @property it was written on. (A property takes no
    #* attribute: there the mark is on its accessors, the ones it has at that point.)
    inside = [getattr(member, "__func__", None)]
    if isinstance(member, property):
        inside += [member.fget, member.fset, member.fdel]
    elif isinstance(member, cached_property):
        inside.append(member.func)
    for target in (member, *inside):
        if target is not None:
            try:
                setattr(target, _SKIP, True)
            except (AttributeError, TypeError):         # an object that takes no attributes
                pass
    return member


def _wrap_callable(
    fn: Callable[..., Any],
    allow_subclass: bool,
    check_return: bool,
    owner: type | None = None,
    skip_first: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    extra_defaults: "_ExtraDefaults | None" = None,
    in_place: bool = False,
    me: type | None = None,
    family: "dict[int, Any] | None" = None,
    upgrade: "Callable[[], Callable[..., Any] | None] | None" = None,
    ) -> Callable[..., Any]:
    """
    Wrap ``fn`` so inputs (and optionally the return value) are checked on every call.

    Decoration is cheap: it returns a tiny stub. The stub's first call runs the full
    checks and then replaces the stub's own ``__code__`` with source generated for this
    exact signature (see ``_generate_wrapper``), so later calls pay no indirection.
    If generation isn't possible yet (bad default, unresolved forward ref), the stub
    keeps using the general path and tries again on the next call.

    ``mark`` (used for a dataclass ``__init__``) returns a namespace, or None. While ``fn`` runs,
    the checked arguments are published there as ``_pv_args`` / ``_pv_kw``, so the class's
    ``__setattr__`` can tell which values need no second check (see ``_dataclass_override``).
    ``extra_defaults`` lists the defaults ``fn`` doesn't take as parameters (see ``_check_defaults``).
    ``in_place`` says that ``fn`` is nobody else's (the ``__init__`` that ``dataclasses`` generated):
    a converted default is then written into it, where otherwise a copy of ``fn`` gets it.

    ``me`` and ``family`` are for a method whose annotations use ``Self``. ``Self`` is the class of
    the instance the method is called on, and a check is compiled for one class. So such a method
    can have one wrapper for each class it is called on: this one, in which ``Self`` is ``me`` (the
    owner unless given), and those made for the other classes when a call arrives for them, kept
    in ``family`` (see ``_route``). Nothing of this exists until such a call is made.

    ``upgrade`` is asked once, when the wrapper is about to be compiled: it returns a function to
    call in place of ``fn`` from then on, or ``None``. A dataclass hands over its storing
    ``__init__`` this way, which costs a ``compile`` of its own and is only worth it for a class
    that is constructed often (see ``_dataclass_override._storing_init``).
    """
    #* typing.no_type_check asks for exactly this: the function stays the one that was written.
    #* (``is True``: an object that answers every attribute, a mock, is not thereby marked.)
    if "__no_type_check__" in fn.__dict__ if type(fn) is FunctionType else getattr(fn, "__no_type_check__", False) is True:
        return fn
    if owner is not None:
        _tag_owner(fn, owner)

    #** Prepare the checker for the function.
    checker = PreparedChecker(
        fn,
        allow_subclass,
        owner,
        skip_first,
        convert = convert,
        coerce = coerce,
        rewrite_defaults = _IN_PLACE if in_place else True,
        deep = deep,
        extra_defaults = extra_defaults,
        me = me,
        family = family,
        )
    #* What kind of function ``fn`` is to ``inspect``: the wrapper says the same of itself (see ``_stub_codes``).
    kind = _function_kind(fn)
    is_async = kind == inspect.CO_COROUTINE
    fallback = _make_fallback(checker, check_return, is_async, mark)

    #* ``_pv_checker`` is not used by the wrapper: it is how ``enforce`` reaches the checker of a
    #* method that was decorated on its own (see ``_adopt``).
    ns: dict[str, Any] = {"__builtins__": builtins, "_pv_checker": checker}
    boot = _BOOT_CODES[kind]
    stub = FunctionType(boot, ns, getattr(fn, "__name__", "wrapper"))

    #* Tiered compilation (see ``_environment.COMPILE_AFTER``): the first calls take the general
    #* path, and the wrapper is compiled when the function has shown that it is called often.
    compile_after = _environment.COMPILE_AFTER
    calls = 0

    def install() -> None:
        if checker.ready and stub.__code__ is boot:
            code, source = _generate_wrapper(checker, check_return, is_async, ns, mark, kind)
            stub.__code__ = code
            stub.__enforced_source__ = source      # type: ignore[attr-defined]  # handy for debugging / introspection

    def improve(args: tuple[Any, ...]) -> None:
        #* After ``_prepare``: what ``upgrade`` returns takes the defaults as the first call left them (converted).
        nonlocal upgrade
        if not checker.ready:
            checker._prepare(args)
        if checker.ready and upgrade is not None:
            better, upgrade = upgrade(), None
            if better is not None and checker.call is fn:
                checker.call = better                   # __wrapped__ stays ``fn``: the origin of its problems

    #* ``@no_type_check`` written above ``@typecheck`` marks the wrapper, after it was made. That is
    #* seen on the first call: from then on the wrapper only passes the call on (``_unchecked``).
    if is_async:
        async def async_bootstrap(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            nonlocal calls
            if calls == 0 and "__no_type_check__" in stub.__dict__:
                return await _unchecked(stub, boot, ns, fn, kind)(*args, **kwargs)
            calls += 1
            if calls < compile_after:
                return await fallback(args, kwargs)
            try:
                return await fallback(args, kwargs)
            finally:
                install()
        ns["_pv_bootstrap"] = async_bootstrap
    else:
        def bootstrap(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            nonlocal calls
            if calls == 0 and "__no_type_check__" in stub.__dict__:
                return _unchecked(stub, boot, ns, fn, kind)(*args, **kwargs)
            calls += 1
            if calls < compile_after:
                return fallback(args, kwargs)
            if upgrade is not None:
                improve(args)
            try:
                return fallback(args, kwargs)
            finally:
                install()
        ns["_pv_bootstrap"] = bootstrap

    return update_wrapper(stub, fn)


#* Where a class keeps what was made for it alone: the wrappers of inherited methods in which
#* ``Self`` is this class, and the checkers of inherited dataclass fields that use ``Self``. On the
#* class, so that they go when it goes: each of them names the class, and anything else that held
#* them would keep a class made at run time alive for as long as it did (review finding 36).
_OF_CLASS = "__enforced_self__"
#* For a class that takes no attribute (a metaclass that refuses): the last wrappers made, by themselves.
_SELF_CLASSES_MAX = 128
_HELD_FOR_CLASSES: "collections.deque[Any]" = collections.deque(maxlen = _SELF_CLASSES_MAX)


def _kept_of(cls: type, create: bool = False) -> dict[Any, Any] | None:
    """The dictionary ``cls`` itself keeps under ``_OF_CLASS`` (not one it inherits); with ``create``, made if it can be."""
    kept = vars(cls).get(_OF_CLASS)
    if kept is None and create:
        kept = {}
        try:
            setattr(cls, _OF_CLASS, kept)
        except Exception:
            return None
    return kept


def _forget_wrapper(family: dict[int, Any], key: int, gone: Any) -> None:
    """A wrapper of ``family`` is gone, and its class with it: the entry goes too, unless the id is another's by now."""
    if family.get(key) is gone:
        family.pop(key, None)


def _route(checker: "PreparedChecker", args: tuple[Any, ...], check_return: bool,
           mark: "Callable[[], dict[str, Any] | None] | None") -> Any:
    """
    For a method whose annotations use ``Self``: the wrapper that this call belongs to, or ``None``
    when that is the one ``checker`` is of.

    ``Self`` is the class of the instance a method is called on (for a class method, the class it
    is called on): ``Child().clone()`` has to return a ``Child``, though ``clone`` is defined in
    ``Base``. A check is compiled for one class, and sees one value at a time. So there is one
    wrapper per class: the one decorated (``Self`` is the class that defines the method), and one
    for each other class the method is called on, made here when the first such call arrives.
    ``check_return`` and ``mark`` are what the decorated wrapper was made with.

    The wrappers of one method share a ``family``: id(class) -> a weak reference to its wrapper.
    What holds the wrapper is the class it was made for (``_OF_CLASS``): the two name each other
    and go together. While the wrapper lives the class does, so the id is that class's.

    Only a class that inherits the method is given a wrapper. Anything else in the place of
    ``self`` (a call such as ``Base.method(5)``) is left to the wrapper that was asked.
    """
    if not args:
        return None
    owner, first = checker.owner, args[0]
    cls: Any = type(first)
    try:
        if owner not in cls.__mro__:                    # not an instance: a class method or __new__, called on a class
            if not isinstance(first, type) or owner not in first.__mro__:
                return None
            cls = first
        if cls is (checker.me or owner):
            return None
    except Exception:                                   # a class that can't be compared
        return None
    family, key = checker.family, id(cls)
    held = None if family is None else family.get(key)
    found = None if held is None else held()
    if found is None:
        with _CACHE_LOCK:
            family = checker.family
            if family is None:
                family = checker.family = {}
        made = _wrap_callable(checker.fn, checker.allow_subclass, check_return, owner, checker.skip_first,
                              checker.convert, checker.coerce, checker.deep, mark, checker.extra_defaults,
                              checker.rewrite_defaults is _IN_PLACE, cls, family)
        with _CACHE_LOCK:
            held = family.get(key)
            found = None if held is None else held()    # another thread may have been quicker
            if found is None:
                found = made
                family[key] = weakref.ref(made, partial(_forget_wrapper, family, key))
                kept = _kept_of(cls, True)
                if kept is not None:
                    kept[id(made)] = made
                else:
                    _HELD_FOR_CLASSES.append(made)
    return found


def _elsewhere(checker: "PreparedChecker", args: tuple[Any, ...], check_return: bool,
               mark: "Callable[[], dict[str, Any] | None] | None") -> Any:
    """
    Asked by the general path before it checks a call: the wrapper the call belongs to instead
    (see ``_route``), or ``None``. Whether an annotation that is checked uses ``Self`` at all is
    known once the annotations are resolved, which the first call does here.
    """
    flags = checker.self_in
    if flags is None:
        checker._prepare(args)
        flags = checker.self_in
    if not flags & (_SELF_ANYWHERE if check_return else _SELF_IN_PARAMETERS):       # type: ignore[operator]
        return None
    return _route(checker, args, check_return, mark)


def _return_router(checker: "PreparedChecker", mark: Any) -> Callable[[Any, tuple[Any, ...]], Any]:
    """
    ``check_return(result, args)`` for a wrapper that tests ``-> Self`` against the class of the
    call: a result that fails goes to the checker of that class, which converts it or says what
    is wrong (``checker`` itself where the call was made on its own class).
    """
    def check_return(result: Any, args: tuple[Any, ...]) -> Any:
        other = _route(checker, args, True, mark)
        if other is None:
            return checker.check_return(result)
        of_class = other.__globals__["_pv_checker"]
        if not of_class.ready:
            of_class._prepare(args)
        return of_class.check_return(result)
    return check_return


def _unchecked(stub: Any, boot: CodeType, ns: dict[str, Any], fn: Any, kind: int) -> Any:
    """Turn a wrapper that carries ``typing.no_type_check`` into one that only passes its call on to ``fn``, which is returned."""
    if stub.__code__ is boot:
        ns["_pv_fn"] = fn
        stub.__code__ = _PLAIN_CODES[kind]
    return fn


def _wrap_member(obj: Any, allow_subclass: bool, check_return: bool, convert: bool, coerce: bool, deep: bool,
                 frame: Any = None) -> Any:
    """
    ``@typecheck`` on anything that isn't a plain function. Written above ``@classmethod``,
    ``@staticmethod``, ``@property`` or ``@cached_property`` it receives that decorator's object, not
    a function: the function inside is checked and the object built again around it, so the attribute
    stays a class method (a property, ...). A class, and anything else that can't be called, is
    refused here, at the definition. ``frame`` is where the decorator was written (see ``_remember_scope``).
    """
    if isinstance(obj, type):
        instead = "A dataclass is checked by enforced.dataclass" if _is_dataclass(obj) else "A class is checked by @enforce"
        raise TypeCheckerError(
            break_trace_colouring + f"typecheck cannot check {describe_origin(obj)}: "
            f"it checks functions and methods. {formatter(instead, 'bold_yellow')}"
            )

    def checked(fn: Any, skip_first: bool) -> Any:
        if fn is None or _is_checked(fn):               # no such accessor, or one decorated on its own
            return fn
        if not callable(fn) or isinstance(fn, type):   # nothing to check, or a class: refused like any other
            return _wrap_member(fn, allow_subclass, check_return, convert, coerce, deep, frame)
        if frame is not None and type(fn) is FunctionType and "<locals>" in fn.__qualname__:
            _remember_scope(fn, frame)
        return _wrap_callable(fn, allow_subclass, check_return, skip_first = skip_first,
                              convert = convert, coerce = coerce, deep = deep)

    if isinstance(obj, (classmethod, staticmethod)):
        return type(obj)(checked(obj.__func__, isinstance(obj, classmethod)))
    if isinstance(obj, property):
        return type(obj)(checked(obj.fget, True), checked(obj.fset, True), checked(obj.fdel, True), obj.__doc__)
    if isinstance(obj, cached_property):
        return type(obj)(checked(obj.func, True))
    if not callable(obj):
        raise TypeCheckerError(
            break_trace_colouring + f"typecheck cannot check {formatter(short_repr(obj, 60), 'bold_red')}: "
            f"a {formatter(type(obj).__name__, 'bold_yellow')} object is not callable. "
            f"Put @typecheck directly above the function, below the other decorators"
            )
    return _wrap_callable(obj, allow_subclass, check_return, convert = convert, coerce = coerce, deep = deep)


def _make_fallback(
    checker: "PreparedChecker",
    check_return: bool,
    is_async: bool,
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    ) -> Callable[..., Any]:
    """
    The general path: full checks (with detailed errors), conversion, call, optional return check.

    What is called is ``checker.call``, read at each call: the first one may replace the function
    by a copy that has its converted defaults (see ``_prepare``).

    Where an annotation that is checked uses ``Self`` (``checker.self_in``: not 0, or not known
    yet), a call made on another class than this checker's goes to the wrapper for that class
    first (see ``_elsewhere``).

    ``failed``, from a compiled wrapper: the parameter whose conversion it tried without success.
    """
    if mark is not None and not is_async:
        def marking_fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
            if checker.self_in != 0 and (other := _elsewhere(checker, args, check_return, mark)) is not None:
                return other(*args, **kwargs)
            args, kwargs = checker.check_inputs(args, kwargs, failed)
            state = mark()
            if state is None:
                result = checker.call(*args, **kwargs)
            else:
                state["_pv_kw"], state["_pv_args"] = kwargs, args or _NO_ARGS      # as checked (and converted)
                try:
                    result = checker.call(*args, **kwargs)
                finally:
                    state["_pv_args"], state["_pv_kw"] = _NO_ARGS, _NO_KWARGS
            return checker.check_return(result) if check_return else result
        return marking_fallback

    if is_async:
        async def async_fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
            if checker.self_in != 0 and (other := _elsewhere(checker, args, check_return, mark)) is not None:
                return await other(*args, **kwargs)
            args, kwargs = checker.check_inputs(args, kwargs, failed)
            if checker.inject is not None:
                args, kwargs = checker.with_defaults(args, kwargs)
            result = await checker.call(*args, **kwargs)
            return checker.check_return(result) if check_return else result
        return async_fallback

    def fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
        if checker.self_in != 0 and (other := _elsewhere(checker, args, check_return, mark)) is not None:
            return other(*args, **kwargs)
        args, kwargs = checker.check_inputs(args, kwargs, failed)
        if checker.inject is not None:
            args, kwargs = checker.with_defaults(args, kwargs)
        result = checker.call(*args, **kwargs)
        return checker.check_return(result) if check_return else result
    return fallback


#* ``PreparedChecker.self_in``: where the annotations of a method use ``Self``.
_SELF_IN_PARAMETERS, _SELF_IN_RETURN = 1, 2
_SELF_ANYWHERE = _SELF_IN_PARAMETERS | _SELF_IN_RETURN


#* source -> code object (for a generator function: (source, its kind) -> code object). Like the other
#* two annotation caches, it lets its oldest entry go when it is full (it used to stop taking new
#* ones). Reads take no lock; inserting and evicting do.
_CODE_CACHE: dict[Any, CodeType] = {}
_CODE_CACHE_MAX = 2048
_CACHE_LOCK = threading.Lock()
def _generate_wrapper(
    checker: "PreparedChecker",
    check_return: bool,
    is_async: bool,
    ns: dict[str, Any],
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    kind: int = 0,
    ) -> tuple[CodeType, str]:
    """
    Write and ``exec`` a wrapper specialised to ``checker.fn``'s signature.

    The generated code only decides "definitely fine" and then calls ``fn``: it binds
    arguments with straight-line code and inlines one ``isinstance``/``type`` test per
    parameter. Any doubt (wrong type, missing or duplicate argument, unknown keyword)
    jumps to the fallback, which converts what it can and raises the same detailed
    errors as before for the rest.

    ``kind`` is the flag of a generator function (see ``_stub_codes``); 0 for any other. The code
    carries it where that is harmless (``_FLAGGED``).
    """
    P = inspect.Parameter
    ns.update({
        "_pv_fn": checker.call,
        "_pv_fallback": _make_fallback(checker, check_return, is_async, mark),
        "_pv_ret_fail": checker.check_return,
        "_pv_M": _MISSING,
        "_pv_F": FAILED,
        })
    aw = "await " if is_async else ""
    fail = f"return {aw}_pv_fallback(_pv_a, _pv_k)"
    lines = [f"{'async ' if is_async else ''}def _pv_wrapper(*_pv_a, **_pv_k):"]

    #* A method whose checked annotations use ``Self`` (see ``_route``). Two ways to get the
    #* class of the call into a check that was compiled once:
    #*   - ``by_instance``: every such annotation is ``Self`` itself, tested by nothing but the
    #*     class. The test is then written against the class of the first argument, and one
    #*     wrapper serves every class: ``isinstance(other, type(self))``.
    #*   - otherwise (``Self | None``, ``list[Self]``, a class method ...): this code is for one
    #*     class, ``_pv_me``, and a call made on another goes to the wrapper for that class.
    me = checker.me or checker.owner
    uses = checker.self_uses or {}
    checks_return = check_return and checker.ret_spec is not None
    relative = [name for name in uses if name != "return" or checks_return]

    def plain_self(name: str) -> bool:
        spec = checker.ret_spec if name == "return" else checker.specs.get(name)
        converted = (name in checker.converters or (name == checker.var_pos and checker.var_pos_conv is not None)
                     or (name == checker.var_kw and checker.var_kw_conv is not None))
        return bool(uses[name]) and not converted and spec is not None and spec[0] in ("isinstance", "is") and spec[1] is me

    by_instance = bool(relative) and not checker.class_first and all(plain_self(name) for name in relative)
    by_class = bool(relative) and not by_instance

    def self_expr(name: str, var: str) -> str:
        """The test of ``var`` against the class of this call (``_pv_c0``), as the spec for ``me`` tests it."""
        strict = (checker.ret_spec if name == "return" else checker.specs[name])[0] == "is"     # type: ignore[index]
        return f"type({var}) is _pv_c0" if strict else f"isinstance({var}, _pv_c0)"

    ret_expr = None
    ret_fail = "_pv_ret_fail(_pv_r)"
    if checks_return:
        if by_instance and "return" in relative:
            ret_expr = self_expr("return", "_pv_r")
            #* What went wrong is said by the checker of the class the call was made on.
            ns["_pv_ret_route"] = _return_router(checker, mark)
            ret_fail = "_pv_ret_route(_pv_r, _pv_a)"
        else:
            ret_expr = _check_expr(checker.ret_spec, "_pv_r", ns, "ret")      # type: ignore[arg-type]

    #* A dataclass __init__ whose __setattr__ skips re-checking what was checked here (see ``mark``
    #* in _wrap_callable). Two dict stores per call, and only for classes that asked for it.
    state = mark() if mark is not None and not is_async and ret_expr is None else None
    if state is not None:
        ns.update({"_pv_g": state, "_pv_N": _NO_ARGS, "_pv_E": _NO_KWARGS})

    def emit_call(ind: str, call: str, args: str = "_pv_a", kwargs: str | None = "_pv_k") -> None:
        """``args`` / ``kwargs``: source for the arguments ``call`` passes (``kwargs`` None: it passes none)."""
        if state is not None:
            if kwargs is None:
                lines.append(f"{ind}_pv_g['_pv_args'] = {args}")
                lines.append(f"{ind}try: return {call}")
                lines.append(f"{ind}finally: _pv_g['_pv_args'] = _pv_N")
            else:
                lines.append(f"{ind}_pv_g['_pv_kw'] = {kwargs}; _pv_g['_pv_args'] = {args} or _pv_N")
                lines.append(f"{ind}try: return {call}")
                lines.append(f"{ind}finally: _pv_g['_pv_args'] = _pv_N; _pv_g['_pv_kw'] = _pv_E")
            return
        if ret_expr is None:
            lines.append(f"{ind}return {aw}{call}")
            return
        lines.append(f"{ind}_pv_r = {aw}{call}")
        lines.append(f"{ind}if {ret_expr}: return _pv_r")
        lines.append(f"{ind}return {ret_fail}")            # converts, or raises the detailed error

    def emit_check(ind: str, expr: str | None) -> None:
        if expr is not None:
            lines.append(f"{ind}if not ({expr}): {fail}")

    def emit_value_check(ind: str, expr: str | None, var: str, name: str, tag: str, record: str) -> None:
        """Check ``var``; if it fails and a converter exists, convert inline and run ``record``."""
        converter = checker.converters.get(name)
        if expr is None or converter is None:
            emit_check(ind, expr)
            return
        #* The general path is told which parameter's conversion has just failed, and doesn't
        #* try it again: for a TypeModel that is the user's ``validate``, run twice per wrong call.
        ns[f"_pv_cv_{tag}"], ns[f"_pv_nm_{tag}"] = converter, name
        lines.append(f"{ind}if not ({expr}):")
        lines.append(f"{ind}    {var} = _pv_cv_{tag}({var})")
        lines.append(f"{ind}    if {var} is _pv_F: return {aw}_pv_fallback(_pv_a, _pv_k, _pv_nm_{tag})")
        lines.append(f"{ind}    {record}")

    params = list(checker.sig.parameters.values())
    positional = [p for p in params if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
    kw_only = [p for p in params if p.kind is P.KEYWORD_ONLY]
    var_pos = next((p for p in params if p.kind is P.VAR_POSITIONAL), None)
    var_kw = next((p for p in params if p.kind is P.VAR_KEYWORD), None)
    n_pos = len(positional)
    specs = checker.specs

    #* Converted defaults that could not be written into the function (see ``PreparedChecker.inject``):
    #* the wrapper passes them itself where the call leaves the parameter out.
    inject = checker.inject or {}
    also = ""
    if kw_inject := {p.name: inject[p.name] for p in kw_only if p.name in inject}:
        ns["_pv_dk"] = kw_inject
        also = ", **_pv_dk"                             # the fast lane passes no keyword: all of them, at once
    #* ``*args: *tuple[int, str]``: the extra positional arguments are tested as one tuple.
    tuple_check = None
    if var_pos is not None and checker.var_pos_node is not None:
        ns["_pv_vp"] = checker.var_pos_node.check
        tuple_check = f"_pv_vp(_pv_a[{n_pos}:])"

    def expr_for(p: inspect.Parameter, var: str, tag: object) -> str | None:
        spec = specs.get(p.name)
        if by_instance and p.name in relative:
            return self_expr(p.name, var)
        return None if spec is None else _check_expr(spec, var, ns, str(tag))

    exprs = [expr_for(p, f"_v{i}", i) for i, p in enumerate(positional)]
    var_pos_expr = expr_for(var_pos, "_x", "vp") if var_pos else None
    var_kw_expr = expr_for(var_kw, "_x", "vk") if var_kw else None

    lines.append("    _pv_n = len(_pv_a)")

    if by_instance:
        #* The class of this call, for the tests written against it. What stands in the place of
        #* ``self`` has to be an instance of the class at all: anything else is left to the general path.
        ns["_pv_owner"] = checker.owner
        lines.append(f"    if not _pv_n: {fail}")
        lines.append("    _pv_c0 = type(_pv_a[0])")
        lines.append(f"    if _pv_c0 is not _pv_owner and not isinstance(_pv_a[0], _pv_owner): {fail}")
    elif by_class:
        #* Compiled for ``_pv_me``. A call made on another class goes to the wrapper for that class,
        #* straight from the family when it has been met before, else through the fallback, which
        #* makes one. The family knows a class by its id and holds its wrapper weakly (see ``_route``).
        with _CACHE_LOCK:
            if checker.family is None:
                checker.family = {}
        ns["_pv_me"], ns["_pv_subs"] = me, checker.family
        called_on = "_pv_a[0]" if checker.class_first else "type(_pv_a[0])"
        lines.append(f"    if _pv_n and {called_on} is not _pv_me:")
        lines.append(f"        _pv_s = _pv_subs.get(id({called_on}))")
        lines.append("        if _pv_s is not None:")
        lines.append("            _pv_s = _pv_s()")
        lines.append(f"            if _pv_s is not None: return {aw}_pv_s(*_pv_a, **_pv_k)")
        lines.append(f"        {fail}")

    #* Fast lane: every positional parameter passed positionally, no keywords at all.
    if not any(p.default is P.empty for p in kw_only):
        cond = f"_pv_n >= {n_pos}" if var_pos else f"_pv_n == {n_pos}"
        lines.append(f"    if not _pv_k and {cond}:")
        if n_pos:
            targets = ", ".join(f"_v{i}" for i in range(n_pos))
            source = "_pv_a" if not var_pos else f"_pv_a[:{n_pos}]"
            lines.append(f"        {targets}, = {source}")
        fast_conv = any(exprs[i] is not None and p.name in checker.converters for i, p in enumerate(positional))
        if fast_conv:
            lines.append("        _pv_ch = False")
        for i, (p, e) in enumerate(zip(positional, exprs)):
            emit_value_check("        ", e, f"_v{i}", p.name, str(i), "_pv_ch = True")
        if var_pos and var_pos_expr:
            lines.append(f"        for _x in _pv_a[{n_pos}:]:")
            emit_check("            ", var_pos_expr)
        emit_check("        ", tuple_check)
        if fast_conv:
            rest = f", *_pv_a[{n_pos}:]" if var_pos else ""
            lines.append("        if _pv_ch:")
            given = "".join(f"_v{i}, " for i in range(n_pos)) + (f"*_pv_a[{n_pos}:]" if var_pos else "")
            emit_call("            ", f"_pv_fn({', '.join(f'_v{i}' for i in range(n_pos))}{rest}{also})",
                      f"({given})" if n_pos else "_pv_a", None)
        emit_call("        ", f"_pv_fn(*_pv_a{also})", "_pv_a" if n_pos else "(_pv_a or _pv_N)", None)

    #* General lane: any mix of positional and keyword arguments.
    if not var_pos:
        lines.append(f"    if _pv_n > {n_pos}: {fail}")
    lines.append("    _pv_c = 0")
    general_conv = bool(inject) or any(p.name in checker.converters for p in positional + kw_only)
    if general_conv:
        lines.append("    _pv_ca = _pv_ck = None")         # converted copies of args / kwargs, made on demand
    keep_pos = lambda i, var: f"_pv_ca = list(_pv_a) if _pv_ca is None else _pv_ca; _pv_ca[{i}] = {var}"
    keep_kw = lambda key, var: f"_pv_ck = dict(_pv_k) if _pv_ck is None else _pv_ck; _pv_ck[{key}] = {var}"
    for i, p in enumerate(positional):
        required = p.default is P.empty
        lines.append(f"    if _pv_n > {i}:")
        if p.kind is P.POSITIONAL_OR_KEYWORD:
            ns[f"_pv_name{i}"] = p.name
            lines.append(f"        if _pv_name{i} in _pv_k: {fail}")   # duplicate binding
        lines.append(f"        _v{i} = _pv_a[{i}]")
        emit_value_check("        ", exprs[i], f"_v{i}", p.name, str(i), keep_pos(i, f"_v{i}"))
        if p.kind is P.POSITIONAL_ONLY:
            if required or p.name in inject:            # a default to pass by position: left to the fallback
                lines.append(f"    else: {fail}")
            continue
        lines.append("    else:")
        lines.append(f"        _v{i} = _pv_k.get(_pv_name{i}, _pv_M)")
        lines.append(f"        if _v{i} is _pv_M:")
        if p.name in inject:
            ns[f"_pv_d{i}"] = inject[p.name]
            lines.append(f"            {keep_kw(f'_pv_name{i}', f'_pv_d{i}')}")
        else:
            lines.append(f"            {fail}" if required else "            pass")
        lines.append("        else:")
        lines.append("            _pv_c += 1")
        emit_value_check("            ", exprs[i], f"_v{i}", p.name, str(i), keep_kw(f"_pv_name{i}", f"_v{i}"))
    for j, p in enumerate(kw_only):
        var = f"_w{j}"
        ns[f"_pv_kname{j}"] = p.name
        lines.append(f"    {var} = _pv_k.get(_pv_kname{j}, _pv_M)")
        lines.append(f"    if {var} is _pv_M:")
        if p.name in inject:
            ns[f"_pv_dw{j}"] = inject[p.name]
            lines.append(f"        {keep_kw(f'_pv_kname{j}', f'_pv_dw{j}')}")
        else:
            lines.append(f"        {fail}" if p.default is P.empty else "        pass")
        lines.append("    else:")
        lines.append("        _pv_c += 1")
        emit_value_check("        ", expr_for(p, var, f"k{j}"), var, p.name, f"k{j}", keep_kw(f"_pv_kname{j}", var))
    if var_pos and var_pos_expr:
        lines.append(f"    for _x in _pv_a[{n_pos}:]:")
        emit_check("        ", var_pos_expr)
    emit_check("    ", tuple_check)
    lines.append("    if _pv_c != len(_pv_k):")
    if var_kw is None:
        lines.append(f"        {fail}")         # unknown keyword
    elif var_kw_expr is not None:
        ns["_pv_known"] = frozenset(p.name for p in params if p.kind in (P.POSITIONAL_OR_KEYWORD, P.KEYWORD_ONLY))
        lines.append("        for _kk, _x in _pv_k.items():")
        lines.append("            if _kk not in _pv_known:")
        emit_check("                ", var_kw_expr)
    else:
        lines.append("        pass")
    if general_conv:
        lines.append("    if _pv_ca is not None or _pv_ck is not None:")
        emit_call("        ", "_pv_fn(*(_pv_a if _pv_ca is None else _pv_ca), **(_pv_k if _pv_ck is None else _pv_ck))",
                  "(_pv_a if _pv_ca is None else _pv_ca)", "(_pv_k if _pv_ck is None else _pv_ck)")
    emit_call("    ", "_pv_fn(*_pv_a, **_pv_k)")

    source = "\n".join(lines)
    # Names live in ``ns``, so the source only encodes the signature's *shape*:
    # functions with the same shape share one compiled code object.
    key: Any = (source, kind) if kind & _FLAGGED else source
    code = _CODE_CACHE.get(key)
    if code is None:
        code = _stub_code(source)
        if key is not source:
            code = code.replace(co_flags = code.co_flags | kind)
        with _CACHE_LOCK:
            while len(_CODE_CACHE) >= _CODE_CACHE_MAX:
                _CODE_CACHE.pop(next(iter(_CODE_CACHE)), None)      # the oldest entry
            _CODE_CACHE[key] = code
    return code, source


def _check_expr(spec: tuple, var: str, ns: dict[str, Any], tag: str) -> str | None:
    """Inline Python expression testing ``var`` against a compiled spec (None = always passes)."""
    kind = spec[0]
    if kind == "any":
        return None
    name = f"_pv_t_{tag}"
    ns[name] = spec[1]
    if kind == "isinstance":
        return f"isinstance({var}, {name})"
    if kind == "nobool":
        return f"(isinstance({var}, {name}) and type({var}) is not bool)"
    if kind == "is":
        return f"type({var}) is {name}"
    if kind == "in":
        return f"type({var}) in {name}"
    return f"{name}({var})"                     # "pred": precompiled predicate


def _tag_owner(fn: Callable[..., Any], owner: type) -> None:
    """Record which class a wrapped function belongs to, for error labels."""
    try:
        setattr(fn, OWNER_ATTR, owner)
    except (AttributeError, TypeError):  # builtins etc. can't take attributes
        pass


def _is_checked(fn: Any) -> bool:
    """Whether ``fn`` is a wrapper made by ``_wrap_callable`` (so it isn't wrapped a second time)."""
    return isinstance(fn, FunctionType) and "_pv_bootstrap" in fn.__globals__


def _checked_inside(fn: Callable[..., Any]) -> Callable[..., Any] | None:
    """
    The wrapper made by ``_wrap_callable`` that ``fn`` is, or that it wraps: a method with
    ``@typecheck`` below another decorator that uses ``functools.wraps``. ``None`` without one.
    """
    try:
        inner = inspect.unwrap(fn, stop = _is_checked)
    except ValueError:                                  # a __wrapped__ chain that loops
        return None
    return inner if _is_checked(inner) else None


def _full_check(
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
    (parameter name -> annotation) and raise a ``TypeCheckerError`` listing every problem. It is
    where a call ends up that doesn't bind cleanly (a missing, an extra or a duplicate argument).
    With ``deep``, items inside collections are checked too; ``nodes`` passes the deep checks the
    caller has compiled already, and ``sig`` the signature it binds with (``fn``'s own otherwise).

    The public ``typecheck_function`` is something else: it goes through a ``PreparedChecker``.
    """
    if sig is None:
        sig = _signature(fn)
    if kwargs is None:
        kwargs = {}

    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError as e:
        raise TypeCheckerError(break_trace_colouring + str(e)) from None
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
                raise TypeCheckerError(
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
            partial(_missing_msg, fn, tuple(missing), record, likely_shifted),
            ))

    #* Only supplied arguments are checked; defaults were validated separately.
    supplied_record = {k: v for k, v in record.items() if k in arguments}
    containers = _load_to_type_containers(fn, supplied_record, arguments, sig)
    if nodes is None and not deep:
        problems += [_type_problem(c, allow_subclass = allow_subclass) for c in containers if not c.check(allow_subclass)]
    else:
        for c in containers:
            root = c._key.split("[", 1)[0]                          # "args[2]" -> "args"
            node = nodes.get(root) if nodes is not None else _deep_node(record[root], allow_subclass, False, False)
            if node is SLOW:
                raise _unresolved_error(record[root], root)
            if node is None:
                if not c.check(allow_subclass):
                    problems.append(_type_problem(c, allow_subclass = allow_subclass))
            elif not node.check(c._input_object):
                problems += _value_problems(fn, c._key, c._input_object, record[root], node, "type", allow_subclass)

    if problems:
        raise _typechecker_type_error_factory(problems)


#* The special methods ``enforce`` checks: those whose arguments a caller writes (``Point(1, 2)``,
#* ``obj(x)``, ``obj[key] = value``, ``key in obj``), and ``__enter__`` / ``__aenter__`` for what
#* ``with`` binds. The rest are called by Python itself, often with any object at all: ``==`` and the
#* operators must be able to answer NotImplemented, and ``__exit__`` receives None three times on a
#* normal exit, whatever its annotations say. Those stay as they are; ``@typecheck`` on one still works.
_CHECKED_SPECIAL = frozenset({
    "__init__", "__new__", "__call__", "__getitem__", "__setitem__", "__delitem__", "__contains__",
    "__enter__", "__aenter__",
    })
#* What these return is the instance being built: there is nothing of the caller's to check.
_CONSTRUCTORS = frozenset({"__init__", "__new__"})


def _held_by_a_base(cls: type, name: str, fn: Callable[..., Any]) -> bool:
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


def _unannotated(fn: Any) -> bool:
    """
    Whether a function has no annotation at all, found out without evaluating any: one that has
    some carries an ``__annotate__`` function, or under ``from __future__ import annotations``
    the dictionary of strings.
    """
    try:
        return fn.__annotate__ is None and not fn.__annotations__
    except Exception:
        return False


def _adopt(wrapper: Callable[..., Any], owner: type, skip_first: bool) -> None:
    """
    Tell a method that carries its own ``@typecheck`` which class it belongs to, so that ``Self``
    and the class's own name resolve, and messages read ``<Method Owner.name>``. Nothing else of
    it changes. Too late once the method has been called: its annotations are resolved by then.
    """
    checker = wrapper.__globals__.get("_pv_checker")
    if checker is None or checker.owner is not None or checker.ready:
        return
    checker.owner, checker.skip_first = owner, skip_first
    _tag_owner(checker.fn, owner)
    _tag_owner(wrapper, owner)


def _is_dataclass(cls: type) -> bool:
    """Whether ``cls`` was made a dataclass itself (a plain subclass of a dataclass wasn't)."""
    return "__dataclass_fields__" in vars(cls)


class TypecheckSpec(TypedDict, total = False):
    """Shape of the dictionary accepted by ``typecheck_record``."""
    object_name: Required[str | Callable[..., Any]]
    record: Required[Mapping[str, Any]]
    allow_subclass: NotRequired[bool]
    args: NotRequired[tuple[Any, ...] | list[Any]]
    kwargs: NotRequired[Mapping[str, Any]]
    skip_first: NotRequired[bool]
    convert: NotRequired[bool]
    coerce: NotRequired[bool]
    deep: NotRequired[bool]


_SPEC_REQUIRED = frozenset({"object_name", "record"})
_SPEC_ALLOWED = _SPEC_REQUIRED | {"allow_subclass", "args", "kwargs", "skip_first", "convert", "coerce", "deep"}


def typecheck_record(spec: TypecheckSpec | Mapping[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """
    Type-check a call described by a dictionary instead of a decorator.

    Args:
        spec: Must contain ``object_name`` (a callable, or a string used only for
            messages) and ``record`` (parameter name -> annotation). Optional keys:
            ``allow_subclass`` (default True), ``args``, ``kwargs``, ``skip_first``,
            ``convert`` (default True), ``coerce`` (default False) and ``deep``
            (default False: check the items inside collections too).
            An annotation may be a string of built-in names (``"int"``, ``"list[int] | None"``),
            so a record can come from JSON. The string is parsed and read as data, never run.

    Returns:
        ``(args, kwargs)``: the checked arguments, with any converted/coerced values
        swapped in. Unchanged arguments are returned as given. A default of a real callable
        that had to be converted is added by keyword, so that the callable receives it.

    Raises:
        TypeCheckerError: If the spec is malformed or the call fails type checking.

    Example:

        typecheck_record({
            "object_name": "create_user",
            "record": {"name": str, "age": int},
            "kwargs": {"name": "Ana", "age": "30"},
        })
    """
    #* ENFORCED_TYPECHECK_OFF=1: the arguments, as they came.
    if _environment.TYPECHECK_OFF:
        return tuple(spec.get("args", ())), dict(spec.get("kwargs", {}))
    #* Validate the spec itself before anything else.
    keys = set(spec)
    if missing := _SPEC_REQUIRED - keys:
        raise TypeCheckerError(
            break_trace_colouring + f"Spec is missing required key(s): "
            + ", ".join(formatter(k, 'bold_green') for k in sorted(missing))
        )
    if unknown := keys - _SPEC_ALLOWED:
        raise TypeCheckerError(
            break_trace_colouring + f"Spec has unknown key(s): "
            + ", ".join(formatter(k, 'bold_red') for k in sorted(unknown))
        )
    if not isinstance(spec["record"], Mapping):
        raise TypeCheckerError(break_trace_colouring + "Spec key 'record' must be a mapping of name -> annotation")

    target = spec["object_name"]
    record = dict(spec["record"])
    allow_subclass = bool(spec.get("allow_subclass", True))
    args = tuple(spec.get("args", ()))
    kwargs = dict(spec.get("kwargs", {}))
    skip_first = bool(spec.get("skip_first", False))
    convert = bool(spec.get("convert", True))
    coerce = bool(spec.get("coerce", False))
    deep = bool(spec.get("deep", False))

    if not callable(target) and not isinstance(target, str):
        raise TypeCheckerError(
            break_trace_colouring + f"Spec key 'object_name' must be a callable or a str, "
            f"got {formatter(type(target).__name__, 'bold_red')}"
            )

    #* The prepared checker (signature, defaults, compiled checks) is cached per target + record:
    #* for a name in ``_RECORD_CACHE``, for a callable on the callable itself (see ``_kept_on``).
    key: Any
    cache = _RECORD_CACHE
    if type(target) is FunctionType:                    # ``_kept_on``, written out: this is the path of every call
        entry = target.__dict__.get(_RECORDS)
        cache = entry[1] if entry is not None and entry[0] is target else _NOTHING_KEPT
    try:
        key = (target, tuple(record.items()), allow_subclass, skip_first, convert, coerce, deep)
        cached = cache.get(key)
    except TypeError:                   # unhashable target or annotation: no caching
        key = cached = None

    #* Equal records aren't always the same check: int | float == float | int, yet conversion tries
    #* the members in declared order. A record with unions has one checker per order of their members.
    checker = cached
    if type(cached) is tuple:
        names, by_order = cached
        checker = by_order.get(tuple([_union_order(record[name]) for name in names]))
    if checker is None:
        checker = _new_record_checker(key, target, record, allow_subclass, skip_first, convert, coerce, deep)

    #* For a real callable, defaults are validated first (once), exactly like the decorator.
    args, kwargs = checker.check_inputs(args, kwargs)
    if checker.inject is not None:                      # a default that had to be converted: handed back by keyword
        args, kwargs = checker.with_defaults(args, kwargs)
    return args, kwargs


def _new_record_checker(key: Any, target: Any, record: dict[str, Any], allow_subclass: bool, skip_first: bool,
                        convert: bool, coerce: bool, deep: bool) -> "PreparedChecker":
    """A checker for ``target`` and ``record``, put into the cache under ``key`` (``None``: it can't be cached)."""
    fn = target if callable(target) else _signature_stub(target, record)
    #* We never call ``target``, so its defaults are left alone: a converted one goes back to the caller.
    checker = PreparedChecker(fn, allow_subclass, None, skip_first, record = record,
                               convert = convert, coerce = coerce, rewrite_defaults = _PASSED, deep = deep)
    if key is not None:
        #* Hits read the cache without a lock. Whatever changes it does so one thread at a time:
        #* an eviction must not meet another thread's insert or eviction halfway.
        with _RECORD_LOCK:
            if type(target) is str:
                checker = _remember_checker(key, record, checker)
            else:
                checker = _remember_checker(key, record, checker, _kept_on(target, _RECORDS, _RECORD_CACHE, True),
                                            _OWN_RECORDS_MAX)
    return checker


def typecheck_function(
    fn: Callable[..., Any],
    args: "tuple[Any, ...] | list[Any]" = (),
    kwargs: "Mapping[str, Any] | None" = None,
    *,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    ) -> Any:
    """
    ``@typecheck`` without the decorator: check one call of a function and make it.

    ``typecheck_function(fn, args, kwargs)`` does what ``typecheck(fn)(*args, **kwargs)`` does,
    for a function you can't or don't want to decorate. The arguments are checked against the
    function's annotations (defaults first, then binding, missing arguments and types), converted
    where the options allow, and the function is called with them.

    Args:
        fn (Callable): The function or method to check and call. A bound method
            (``account.deposit``) takes no ``self``. A class is not accepted: see ``enforce_class``.
        args (tuple | list): The positional arguments of the call.
        kwargs (Mapping): The keyword arguments of the call.
        allow_subclass, check_return, convert, coerce, deep: As for ``typecheck``.

    Returns:
        What ``fn`` returns (checked as well, with ``check_return``).

    Raises:
        TypeCheckerError: If the call fails its checks, or ``fn`` is not a function.

    The checked function is remembered per set of options, on the function itself, so a repeated
    call costs little more than one of a decorated function, and nothing outlives the function.

    Example:

        def area(width: float, height: float) -> float:
            return width * height

        typecheck_function(area, (3, 4))            # 12.0: checked, converted, called
        typecheck_function(area, ("3", 4))          # TypeCheckerError
    """
    if _environment.TYPECHECK_OFF:                      # ENFORCED_TYPECHECK_OFF=1: the call, and nothing else
        return fn(*args) if kwargs is None else fn(*args, **kwargs)
    if isinstance(fn, type):
        raise TypeCheckerError(
            break_trace_colouring + f"typecheck_function cannot check {describe_origin(fn)}: it checks and calls a "
            f"function or a method. {formatter('A class is checked by enforce_class', 'bold_yellow')}"
            )
    if not callable(fn):
        raise TypeCheckerError(
            break_trace_colouring + f"typecheck_function cannot check {formatter(short_repr(fn, 60), 'bold_red')}: "
            f"a {formatter(type(fn).__name__, 'bold_yellow')} object is not callable"
            )
    #* A string for ``args`` would be taken apart into one argument per character.
    if not isinstance(args, (tuple, list)):
        raise TypeCheckerError(
            break_trace_colouring + "typecheck_function: 'args' must be a tuple or a list of the positional arguments, "
            f"got {formatter(type(args).__name__, 'bold_red')}"
            )
    if kwargs is not None and not isinstance(kwargs, Mapping):
        raise TypeCheckerError(
            break_trace_colouring + "typecheck_function: 'kwargs' must be a mapping of the keyword arguments, "
            f"got {formatter(type(kwargs).__name__, 'bold_red')}"
            )
    #* A bound method is a new object every time it is looked up, which no cache could hold on to:
    #* the function inside is what gets wrapped, and called with the object it is bound to in front.
    if type(fn) is MethodType:
        args, fn = (fn.__self__, *args), fn.__func__                    # type: ignore[attr-defined]
    options = (allow_subclass, check_return, convert, coerce, deep)
    #* What was made of a function before is kept on the function itself (see ``_kept_on``, written
    #* out here: this is the path of every call). ``entry[0] is fn``: a decorator made with
    #* functools.wraps copies the attributes of what it wraps, and that entry speaks for the function inside.
    if type(fn) is FunctionType:
        entry = fn.__dict__.get(_CALLS)
    else:
        entry = _CALL_WRAPPERS.get(id(fn))
    checked = entry[1].get(options) if entry is not None and entry[0] is fn else None
    if checked is None:
        checked = _call_wrapper(fn, options, sys._getframe(1))
    return checked(*args) if kwargs is None else checked(*args, **kwargs)


#* What typecheck_function and typecheck_record remember about a function is kept on the function,
#* under these names: ``(it, {options: its checked wrapper})`` and ``(it, {key: its checker})``.
#* A cache of their own would hold the wrapper, the wrapper holds the function, and so a function
#* made in a loop and called once stayed until 512 newer ones had come (review finding 34). Kept on
#* the function, the two form a cycle that the garbage collector takes away with the function.
_CALLS = "__enforced_calls__"
_RECORDS = "__enforced_records__"
#* The records one function keeps checkers for (typecheck_record): there is usually one.
_OWN_RECORDS_MAX = 32

#* For any other callable (an object with __call__, a functools.partial, a builtin):
#* id(it) -> (it, {options: its checked wrapper}). The entry holds the callable, so its id can't be
#* another's while it is here; like the other caches, it lets its oldest entry go when it is full.
#* Nothing is written into such an object: its attributes are its state, which is copied and
#* pickled with it, and a wrapper is bound to the one object it was made for.
_CALL_WRAPPERS: "dict[int, tuple[Any, dict[tuple, Callable[..., Any]]]]" = {}
_CALL_WRAPPERS_MAX = 512


def _kept_on(target: Any, name: str, shared: dict[Any, Any], create: bool = False) -> dict[Any, Any]:
    """
    The dictionary a function keeps under ``name``, for what is remembered about it. One that isn't
    its own counts as none: ``functools.wraps`` copies attributes from the function inside. Without
    one, an empty dictionary, or with ``create`` a new one that the function now keeps. ``shared``
    is what any other callable gets instead.
    """
    if type(target) is not FunctionType:
        return shared
    held = target.__dict__
    entry = held.get(name)
    if entry is not None and entry[0] is target:
        return entry[1]
    if not create:
        return _NOTHING_KEPT
    kept: dict[Any, Any] = {}
    held[name] = (target, kept)
    return kept


_NOTHING_KEPT: dict[Any, Any] = {}


def _call_wrapper(fn: Any, options: tuple, frame: Any) -> Callable[..., Any]:
    """The checked wrapper of ``fn`` for these options, made and remembered. ``frame`` is the caller's."""
    allow_subclass, check_return, convert, coerce, deep = [bool(option) for option in options]
    if type(fn) is FunctionType:
        if "<locals>" in fn.__qualname__:
            _remember_scope(fn, frame)
        checked = _wrap_callable(fn, allow_subclass, check_return, convert = convert, coerce = coerce, deep = deep)
    else:
        checked = _wrap_member(fn, allow_subclass, check_return, convert, coerce, deep, frame)
    #* Hits take no lock. Whatever changes the cache does so one thread at a time.
    with _RECORD_LOCK:
        kept = _kept_on(fn, _CALLS, _CALL_WRAPPERS, True)
        if kept is not _CALL_WRAPPERS:
            return kept.setdefault(options, checked)
        entry = _CALL_WRAPPERS.get(id(fn))
        if entry is None or entry[0] is not fn:
            while len(_CALL_WRAPPERS) >= _CALL_WRAPPERS_MAX:
                _CALL_WRAPPERS.pop(next(iter(_CALL_WRAPPERS)), None)        # the oldest entry
            entry = _CALL_WRAPPERS[id(fn)] = (fn, {})
        return entry[1].setdefault(options, checked)


def enforce_class[T: type](
    cls: T,
    *,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    ) -> T:
    """
    ``@enforce`` without the decorator: enforce the annotations of a class that is already
    defined, and return it.

    ``enforce_class(cls, ...)`` does what ``@enforce(...)`` above the class statement does:
    ``__init__``, the methods the class defines and the special methods a caller hands values to
    are checked on every call from now on. It is the same class that comes back, changed in
    place, so every user of it gets the checks. A dataclass and anything that isn't a class are
    refused, as by ``enforce``.

    Args:
        cls (type): The class to enforce.
        allow_subclass, check_return, convert, coerce, deep: As for ``enforce``.

    Returns:
        ``cls`` itself, its methods wrapped with runtime type validation.

    Example:

        class Point:
            def __init__(self, x: float, y: float) -> None: ...

        enforce_class(Point, check_return = True)
        Point("one", 2)                             # TypeCheckerError
    """
    if _environment.TYPECHECK_OFF:
        return cls
    if not isinstance(cls, type):
        shown = describe_origin(cls) if callable(cls) else formatter(short_repr(cls, 60), "bold_red")
        raise TypeCheckerError(
            break_trace_colouring + f"enforce_class cannot check {shown}: it checks classes. "
            + formatter("A function or a method is checked by typecheck_function", "bold_yellow")
            )
    if "<locals>" in cls.__qualname__:
        _remember_scope(cls, sys._getframe(1))
    return enforce(cls, allow_subclass, check_return, convert, coerce, deep)


#* key -> checker, or for a record with unions: (their parameter names, {member order: checker}).
_RECORD_CACHE: dict[tuple, Any] = {}
_RECORD_CACHE_MAX = 512
_RECORD_ORDERS_MAX = 16
_RECORD_LOCK = threading.Lock()


def _remember_checker(key: tuple, record: dict[str, Any], checker: "PreparedChecker",
                      cache: "dict[tuple, Any] | None" = None, limit: int = 0) -> "PreparedChecker":
    """
    Put ``checker`` into the ``typecheck_record`` cache and return the one to use: ``checker``, or
    the one another thread stored for the same spec in the meantime. The caller holds the lock.
    ``cache`` and its ``limit``: the records of one callable, where the target is one (``_kept_on``).
    """
    if cache is None or cache is _RECORD_CACHE:
        cache, limit = _RECORD_CACHE, _RECORD_CACHE_MAX
    entry = cache.get(key)
    if entry is None:
        while len(cache) >= limit:
            del cache[next(iter(cache))]                # the oldest entry
        names = tuple([name for name, annotation in record.items() if _has_union(annotation)])
        if names:
            cache[key] = (names, {tuple([_union_order(record[name]) for name in names]): checker})
        else:
            cache[key] = checker
        return checker
    if type(entry) is not tuple:
        return entry
    names, by_order = entry
    order = tuple([_union_order(record[name]) for name in names])
    if order in by_order or len(by_order) < _RECORD_ORDERS_MAX:
        return by_order.setdefault(order, checker)
    return checker                                      # every slot for this record is taken: used, not kept


def _has_union(annotation: Any, depth: int = 0) -> bool:
    """Whether a union sits anywhere inside ``annotation`` (``int | str``, ``list[int | str]``)."""
    if type(annotation) is UnionType:
        return True
    return depth < 8 and any(_has_union(arg, depth + 1) for arg in getattr(annotation, "__args__", None) or ())


def _union_order(annotation: Any) -> Any:
    """The order of the union members in ``annotation``: equality ignores it, conversion follows it."""
    if type(annotation) is UnionType:
        args = annotation.__args__
        for arg in args:
            if type(arg) is not type:
                return repr(annotation)                 # something nested: the repr keeps every level's order
        return args                                     # the common case: a union of plain classes
    return repr(annotation)


def _signature_stub(name: str, record: dict[str, Any]) -> Callable[..., Any]:
    """Build a no-op function whose name and signature come from a record."""
    try:
        params = [
            inspect.Parameter(key, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation = annotation)
            for key, annotation in record.items() if key != "return"
            ]
    except ValueError as e:  # e.g. a key that isn't a valid identifier
        raise TypeCheckerError(break_trace_colouring + f"Invalid record for {name!r}: {e}") from None

    def stub(*args: Any, **kwargs: Any) -> None: ...
    stub.__name__ = stub.__qualname__ = name
    stub.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return stub


def _check_defaults(
    fn: Callable[..., Any],
    record: dict[str, Any],
    allow_subclass: bool,
    convert: bool = False,
    coerce: bool = False,
    rewrite: bool = False,
    deep: bool = False,
    extra: "_ExtraDefaults | None" = None,
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
        (name, p.default, record[name], p) for name, p in (sig or _signature(fn)).parameters.items()
        if p.default is not inspect.Parameter.empty and p.default is not _DATACLASS_FACTORY
        and p.default is not _NOT_GIVEN and name in record
        ]
    if extra is not None:
        defaults += extra()
    for name, default, annotation, target in defaults:
        node = _deep_node(annotation, allow_subclass, convert, coerce, resolve) if deep else None
        if node is SLOW:
            raise _unresolved_error(annotation, name)
        if node is None:
            if TypeContainer(fn, name, default, annotation).check(allow_subclass):
                continue
        elif node.check(default):
            continue
        converter = _compile_converter(annotation, allow_subclass, name, convert, coerce, deep, resolve)
        if converter is not None and (value := converter(default)) is not FAILED:
            if isinstance(target, inspect.Parameter):
                converted[name] = (target, value)
            else:
                stored.append((target, value))
            continue
        found = _value_problems(fn, name, default, annotation, node, "default", allow_subclass, convert, coerce)
        if not isinstance(target, inspect.Parameter):   # a dataclass field that __init__ doesn't take: no parameter
            for problem in found:
                problem._render = (_as_field, problem._render)
        messages += found
    if messages:
        raise _typechecker_type_error_factory(messages, context="definition")
    if converted and rewrite and _own_signature(fn):
        _rewrite_defaults(fn, converted, sig or _signature(fn))
        _forget_signature(fn)                       # the cached signature still shows the old defaults
    for store, value in stored:
        store(value)
    return converted


def _as_field(problem: Problem, render: Any) -> str:
    """A message about a default, worded for a dataclass field that is no parameter of ``__init__``."""
    text = render[0](problem, *render[1:]) if type(render) is tuple else render()
    return text.replace(" parameter ", " field ", 1)


def _own_signature(fn: Any) -> bool:
    """Whether ``fn`` is a function whose defaults are its own: not borrowed via ``__wrapped__`` / ``__signature__``."""
    return type(fn) is FunctionType and not hasattr(fn, "__wrapped__") and "__signature__" not in vars(fn)


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


def _with_defaults(fn: Any, converted: dict[str, tuple[inspect.Parameter, Any]], sig: inspect.Signature) -> Any:
    """
    A copy of ``fn`` that has the converted defaults: same code, same globals, same closure. The
    wrapper calls the copy, so the function receives ``0.0`` for ``x: float = 0`` at no cost per
    call, and the function that was handed to ``typecheck`` keeps the defaults it was written with:
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
_IN_PLACE = "in place"
#* ... and of one that only checks a call for somebody else: converted defaults go back with the arguments.
_PASSED = "passed"


def _stub_code(source: str) -> CodeType:
    """Compile ``source`` (which defines ``_pv_wrapper``) and return that function's code object."""
    namespace: dict[str, Any] = {}
    exec(compile(source, "<enforced wrapper>", "exec"), namespace)
    return namespace["_pv_wrapper"].__code__


_GENERATOR_FLAGS = inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
_KIND_FLAGS = inspect.CO_COROUTINE | _GENERATOR_FLAGS


def _function_kind(fn: Any) -> int:
    """
    What kind of function ``inspect`` takes ``fn`` for: ``CO_COROUTINE``, ``CO_GENERATOR``,
    ``CO_ASYNC_GENERATOR``, or 0 for an ordinary one.
    """
    #* A function: answered from the flags of its code, which is all inspect reads, unless
    #* inspect.markcoroutinefunction has said otherwise. (Three inspect calls cost more than the
    #* rest of a decoration put together.)
    if type(fn) is FunctionType and "_is_coroutine_marker" not in fn.__dict__:
        return fn.__code__.co_flags & _KIND_FLAGS
    if inspect.iscoroutinefunction(fn):
        return inspect.CO_COROUTINE
    if inspect.isgeneratorfunction(fn):                 # a functools.partial of one, ...
        return inspect.CO_GENERATOR
    return inspect.CO_ASYNC_GENERATOR if inspect.isasyncgenfunction(fn) else 0


_PROBE = "def _pv_wrapper(*_pv_a, **_pv_k):\n    return _pv_fn\n"


def _runs_at_once(kind: int, source: str = _PROBE) -> bool:
    """
    Whether an ordinary function still runs when it is called, once its code carries the flag of
    a generator function (``kind``). It does in every CPython since 3.11: what makes a generator
    is an instruction at the start of a generator function's code, and nothing reads the flag when
    code is run. That is no promise, so it is tried here, once, on the Python that is running: a
    function made of ``source`` with the flag added is called and has to return at once. Where it
    doesn't (it hands back a generator, or Python refuses such code), no wrapper is given the flag.
    """
    try:
        code = _stub_code(source)
        return FunctionType(code.replace(co_flags = code.co_flags | kind), {"_pv_fn": _MISSING})() is _MISSING
    except Exception:
        return False


#* The flags a wrapper may carry on this Python (see ``_stub_codes``): both, or none where they would be acted on.
_FLAGGED: int = sum(kind for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR) if _runs_at_once(kind))


def _stub_codes(call: str, flagged: int | None = None) -> dict[int, CodeType]:
    """
    The code of a wrapper that does nothing but ``call``, for each kind of function: an ordinary one
    (0), a coroutine function, a generator function and an async generator function.

    A wrapper of a generator function is an ordinary function: it checks the arguments when it is
    called and hands back the generator that ``fn`` returns. But ``inspect.isgeneratorfunction``
    reads one thing only, a flag on the code object, and frameworks branch on it (a pytest ``yield``
    fixture, a dependency with teardown): told "not a generator function", they use the generator
    object itself as the value. So the wrapper's code carries the flag of the function it wraps.
    Python itself doesn't read the flag when it runs code (a real generator function starts with an
    instruction that makes the generator), so the wrapper still runs at once, at the call.
    A wrapper keeps the kind it was made with: assigning a function code of another kind is deprecated.

    ``flagged`` (``_FLAGGED`` unless given) holds the flags that were found to be harmless on this
    Python (``_runs_at_once``). A kind that is not among them gets the plain code: its wrapper
    checks and calls as ever, and is an ordinary function to ``inspect``.
    """
    if flagged is None:
        flagged = _FLAGGED
    plain = _stub_code(f"def _pv_wrapper(*_pv_a, **_pv_k):\n    return {call}\n")
    codes = {0: plain, inspect.CO_COROUTINE: _stub_code(f"async def _pv_wrapper(*_pv_a, **_pv_k):\n    return await {call}\n")}
    for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR):
        codes[kind] = plain.replace(co_flags = plain.co_flags | kind) if kind & flagged else plain
    return codes


#* Shared code objects for every stub; each stub gets its own globals dict. ``_BOOT_CODES``: until the
#* first call has compiled the wrapper. ``_PLAIN_CODES``: for a function that is not to be checked.
_BOOT_CODES = _stub_codes("_pv_bootstrap(_pv_a, _pv_k)")
_PLAIN_CODES = _stub_codes("_pv_fn(*_pv_a, **_pv_k)")


#* What a ``mark`` namespace holds while no call is running: a first argument that is no instance.
_NO_ARGS: tuple[Any, ...] = (None,)
_NO_KWARGS: dict[str, Any] = {}


class _Slow:
    """Sentinel: this annotation can't be precompiled; use the full (slow) path."""
    __slots__ = ()


SLOW = _Slow()


def _compile_spec(
    expected: Any,
    allow_subclass: bool,
    key: str = "?",
    deep: bool = False,
    convert: bool = True,
    coerce: bool = False,
    resolve: "Callable[[str], Any] | None" = None,
    ) -> tuple | _Slow:
    """
    Reduce one annotation to the cheapest test that's equivalent to ``TypeContainer.check``:

        ("any",)              anything passes
        ("isinstance", T)     isinstance(v, T)          (T may be a TypeUnion)
        ("nobool", T)         isinstance(v, T), but not a bool (T includes int: True is not an int)
        ("is", T)             type(v) is T              (strict mode)
        ("in", frozenset)     type(v) in members        (strict-mode union)
        ("pred", callable)    callable(v)               (Literal, type[X], Never, deep checks)

    With ``deep``, an annotation with items to check (``list[int]``, ``dict[str, T]`` ...)
    becomes ``("pred", node.check)``; ``convert``/``coerce`` only pick which cached node, and
    ``resolve`` reads a name left as a string inside the annotation (see ``_resolver``).
    Returns ``_SLOW`` when the annotation can't be resolved.
    """
    if deep:
        node = _deep_node(expected, allow_subclass, convert, coerce, resolve)
        if node is SLOW:
            return SLOW
        if node is not None:
            return ("pred", node.check)
    try:
        c = TypeContainer(None, key, None, expected)
    except TypeCheckerError:
        return SLOW
    spec = _container_spec(c, allow_subclass)
    if c._constraints is None or spec[0] == "pred" and spec[1] is _always_false:
        return spec
    #* Annotated[int, check]: the type test, then the checks of the member the value belongs to.
    base = _predicate(spec)
    constraints, plain, literals = c._constraints, c._plain_types, c._literal_values or frozenset()
    if len(constraints) == 1 and plain is None and not literals and spec[0] in ("isinstance", "nobool", "is"):
        return ("pred", _single_constraint(spec, base, constraints[0][1]))    # type: ignore[arg-type]  # the common case: one member
    def check_constrained(v: Any) -> bool:
        if base is not None and not base(v):
            return False
        try:
            if (type(v), v) in literals:                # a Literal value: no checks apply to it
                return True
        except TypeError:
            pass
        return constraints_pass(v, constraints, plain, allow_subclass)
    if c._type_arg is not None:
        return ("pred", _or_class(check_constrained, c._type_arg, allow_subclass))
    return ("pred", check_constrained)


def _or_class(check: Callable[[Any], bool], classes: Any, allow_subclass: bool) -> Callable[[Any], bool]:
    """``check``, for an annotation that also has a ``type[X]`` member: no ``Annotated`` check applies to a class."""
    def check_constrained_or_class(v: Any) -> bool:     # PositiveInt | type[int]
        return matches_class(v, classes, allow_subclass) or check(v)
    return check_constrained_or_class


def _single_constraint(spec: tuple, base: Callable[[Any], bool], checks: tuple) -> Callable[[Any], bool]:
    """``Annotated[T, *checks]`` (no union around it) as one flat predicate."""
    kind, target = spec
    first = checks[0]
    if kind == "isinstance" and len(checks) == 1:
        def check(v: Any) -> bool:
            if not isinstance(v, target):
                return False
            try:
                return bool(first(v))
            except CHECK_ERRORS:
                return False
    elif kind == "nobool" and len(checks) == 1:
        def check(v: Any) -> bool:
            if not isinstance(v, target) or type(v) is bool:
                return False
            try:
                return bool(first(v))
            except CHECK_ERRORS:
                return False
    else:
        def check(v: Any) -> bool:
            if not base(v):
                return False
            try:
                for c in checks:
                    if not c(v):
                        return False
            except CHECK_ERRORS:
                return False
            return True
    #* Read by the deep checks: test all the item types at once, then run only the checks.
    check.type_spec, check.type_pred, check.checks = spec, base, checks     # type: ignore[attr-defined]
    return check


def _container_spec(c: TypeContainer, allow_subclass: bool) -> tuple:
    """The spec for an unpacked annotation, without its ``Annotated`` checks."""
    if c._is_never:
        return ("pred", _always_false)
    if c._literal_values is None and c._type_arg is None:
        return _type_spec(c._expected_type, allow_subclass)
    return _special_spec(c, allow_subclass)


def _special_spec(c: TypeContainer, allow_subclass: bool) -> tuple:
    """
    The spec for an annotation with Literal values or ``type[X]`` among its members, as in
    ``Literal['r', 'w'] | type[int] | str | None``: one of the values, such a class, or anything
    the other members accept.
    """
    allowed, classes = c._literal_values, c._type_arg
    other = None
    if c._other_types is not None:
        other = _predicate(_type_spec(c._other_types, allow_subclass))
        if other is None:
            return ("any",)                             # ... | Any: the Any member accepts everything

    if allowed is None:
        if other is None:
            return _class_spec(classes, allow_subclass)                 # type[X] on its own
        is_class = _predicate(_class_spec(classes, allow_subclass))
        return ("pred", lambda v: other(v) or is_class(v))              # type: ignore[misc]  # type[X] | None

    if classes is None:
        def check_literal(v: Any) -> bool:
            try:
                if (type(v), v) in allowed:
                    return True
            except TypeError:                           # unhashable: can't be a Literal value
                pass
            return other is not None and other(v)
        return ("pred", check_literal)

    is_class = _predicate(_class_spec(classes, allow_subclass))
    def check_literal_or_class(v: Any) -> bool:
        try:
            if (type(v), v) in allowed:
                return True
        except TypeError:
            pass
        return (other is not None and other(v)) or is_class(v)         # type: ignore[misc]
    return ("pred", check_literal_or_class)


def _class_spec(target: Any, allow_subclass: bool) -> tuple:
    """The spec for ``type[X]``: a class that is ``target`` (one of its members), or a subclass unless strict."""
    if not allow_subclass:
        if target is object or (isinstance(target, TypeUnion) and object in target):
            return ("isinstance", type)                 # type[Any]: any class
        if type(target) is SelfType:                    # type[Self]: the class or a subclass, as for Self itself
            owner = target.owner
            return ("pred", lambda v: isinstance(v, type) and issubclass(v, owner))
        if type(target) is FileType:                    # type[TextIO]: no class is the stand-in itself
            return ("pred", lambda v: isinstance(v, type) and issubclass(v, target))
        if not isinstance(target, TypeUnion):
            return ("pred", lambda v: v is target)      # only the class itself is identical to it
        def check_exact_class(v: Any) -> bool:          # type[X | Y]: one of the members, exactly
            return matches_class(v, target, False)
        return ("pred", check_exact_class)
    def check_type_arg(v: Any) -> bool:
        if not isinstance(v, type):
            return False
        try:
            return issubclass(v, target)
        except TypeError:
            return False
    return ("pred", check_type_arg)


def _type_spec(expected_type: Any, allow_subclass: bool) -> tuple:
    """The spec for a flattened type or TypeUnion (the plain-class part of ``_compile_spec``)."""
    if expected_type is object:
        return ("any",)
    if allow_subclass:
        kind = "nobool" if excludes_bool(expected_type) else "isinstance"
        #* A TypeModel class has a metaclass, and isinstance() against such a class is slower for a
        #* value that isn't exactly of it. In a union the ordinary classes are tested first, so the
        #* None of ``Email | None`` is answered before the model is asked.
        if isinstance(expected_type, TypeUnion) and any(is_model_class(t) for t in expected_type):
            return (kind, tuple(sorted(expected_type, key = is_model_class)))
        return (kind, expected_type)
    #* Strict mode: the exact type. An abstract class has no instances of exactly its own type, so
    #* its implementations are accepted (strict ``Sequence`` would otherwise reject every value).
    if isinstance(expected_type, TypeUnion):
        if object in expected_type:                     # Any | int: the Any member accepts everything
            return ("any",)
        abstract = tuple(t for t in expected_type if is_abstract(t))
        if not abstract:
            return ("in", frozenset(expected_type))
        if len(abstract) == len(expected_type):
            return ("isinstance", expected_type)
        exact = frozenset(t for t in expected_type if t not in abstract)
        return ("pred", lambda v: type(v) in exact or isinstance(v, abstract))
    if is_abstract(expected_type):
        return ("isinstance", expected_type)
    return ("is", expected_type)


def _compile_converter(
    expected: Any,
    allow_subclass: bool,
    key: str,
    convert: bool,
    coerce: bool,
    deep: bool = False,
    resolve: "Callable[[str], Any] | None" = None,
    ) -> Callable[[Any], Any] | None:
    """
    ``value -> converted | FAILED`` for one annotation, or ``None`` when nothing applies.

    Args:
        expected (Any): The expected type annotation for the value.
        allow_subclass (bool): Whether to allow subclasses of the expected type.
        key (str): The parameter name or key associated with the value.
        convert (bool): Whether conversion is allowed.
        coerce (bool): Whether coercion is allowed.
        deep (bool): Whether items inside collections are checked (and so converted) too.

    Returns:
        Callable[[Any], Any] | None: A converter function that takes a value and returns the converted value, or ``None`` if no conversion is applicable.
    """
    if not (convert or coerce):
        return None
    if deep:
        node = _deep_node(expected, allow_subclass, convert, coerce, resolve)
        if node is SLOW:
            return None
        if node is not None:
            return _deep_converter(node)
    try:
        c = TypeContainer(None, key, None, expected)
    except TypeCheckerError:
        return None
    #* Literal / type[X] / Never / Any are never converted. In Literal['auto'] | type[int] | float
    #* only the other members convert (1 -> 1.0); conversion never produces a Literal value or a class.
    if c._is_never or c._expected_type is object:
        return None
    convertible = c._other_types
    if convertible is None or convertible is object:
        return None
    targets = tuple(convertible) if isinstance(convertible, TypeUnion) else (convertible,)
    accept = _predicate(_compile_spec(expected, allow_subclass, key))     # type: ignore[arg-type]
    return build_converter(targets, convert, coerce, accept or (lambda v: True))


def _predicate(spec: tuple) -> Callable[[Any], bool] | None:
    """Turn a spec from ``_compile_spec`` into a ``value -> bool`` callable (``None`` = anything passes)."""
    kind = spec[0]
    if kind == "any":
        return None
    target = spec[1]
    if kind == "isinstance":
        return lambda v: isinstance(v, target)
    if kind == "nobool":
        return lambda v: isinstance(v, target) and type(v) is not bool
    if kind == "is":
        return lambda v: type(v) is target
    if kind == "in":
        return lambda v: type(v) in target
    return target


#* (id(annotation), allow_subclass, convert, coerce) -> (the annotation, node). A node keeps its
#* annotation (for messages), so the id can't be another object's while the entry is here. That
#* is also why some annotations are never put here (see the end of ``_deep_node``). When the cache
#* is full its oldest entry makes room (``_CACHE_LOCK``, as for ``_CODE_CACHE``).
_DEEP_NODES: dict[tuple, tuple[Any, Any]] = {}
_DEEP_NODES_MAX = 4096


def _deep_node(expected: Any, allow_subclass: bool, convert: bool, coerce: bool,
               resolve: "Callable[[str], Any] | None" = None) -> Any:
    """
    The compiled deep check for ``expected``: a node, ``None`` when there are no items to
    check (``int``, ``list``, ``list[Any]``: the shallow check is already complete), or
    ``_SLOW`` when part of the annotation can't be resolved yet. ``resolve`` evaluates a name that
    is still a string inside the annotation (``List["Json"]``); without it only built-in names are read.
    """
    #* A plain class has no items to check (a NamedTuple class has: its fields). Answered here, and
    #* not from the cache, where a class made at run time would be kept alive.
    if type(expected) is type and not issubclass(expected, tuple):
        return None
    key = (id(expected), allow_subclass, convert, coerce)
    entry = _DEEP_NODES.get(key)
    if entry is not None and holds(entry[0], expected):
        return entry[1]

    def make_leaf(annotation: Any) -> Any:
        spec = _compile_spec(annotation, allow_subclass)
        if spec is SLOW:
            return _deep.SLOW
        converter = _compile_converter(annotation, allow_subclass, "?", convert, coerce)
        return _deep.Leaf(annotation, spec, _predicate(spec), converter)     # type: ignore[arg-type]

    node = _deep.compile_node(expected, make_leaf, resolve)
    if node is _deep.SLOW:
        return SLOW                                    # not cached: retried once the name exists
    result = None if node.leaf else node                # type: ignore[union-attr]
    #* Not cached: an annotation made for one class (see ``made_for``), and one that names a class
    #* written inside a function. A node keeps its annotation, for messages, so its entry could
    #* never go by itself, and the class would stay with it.
    if id(expected) in not_cached or _names_local_class(expected):
        return result
    with _CACHE_LOCK:
        make_room(_DEEP_NODES, _DEEP_NODES_MAX)
        _DEEP_NODES[key] = (held(expected, _DEEP_NODES, key), result)
    return result


def _names_local_class(annotation: Any, depth: int = 0) -> bool:
    """Whether a class written inside a function stands anywhere in ``annotation``."""
    if isinstance(annotation, type):
        return "<locals>" in annotation.__qualname__
    if depth < 8:
        for part in getattr(annotation, "__args__", None) or ():
            if _names_local_class(part, depth + 1):
                return True
    return False


def _deep_converter(node: "_deep.Node") -> Callable[[Any], Any] | None:
    """``value -> converted | FAILED`` for a deep node; the result always passes ``node.check``."""
    if not node.can_convert:
        return None
    convert, check = node.convert, node.check

    def converter(value: Any) -> Any:
        try:
            out = convert(value)
        except Exception:                               # a custom container that can't be rebuilt, ...
            return FAILED
        return out if out is not FAILED and check(out) else FAILED
    return converter


def _find_uncheckable_protocol(annotation: Any, depth: int = 0) -> type | None:
    """The first Protocol inside ``annotation`` that isinstance can't test (best effort, for the message)."""
    if isinstance(annotation, type):
        return annotation if uncheckable_protocol(annotation) else None
    if depth < 8:
        for arg in get_args(annotation):
            if (found := _find_uncheckable_protocol(arg, depth + 1)) is not None:
                return found
    return None


def _unresolved_error(annotation: Any, key: str) -> TypeCheckerError:
    if (protocol := _find_uncheckable_protocol(annotation)) is not None:
        return protocol_error(protocol, key)
    return TypeCheckerError(
        break_trace_colouring + f"Cannot resolve annotation {formatter(_shortened(_format_annotation(annotation)), 'bold_yellow')} "
        f"for parameter {formatter(key, 'bold_green')} (needed to check its items)"
        )


def _value_problems(
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
        return [_type_problem(TypeContainer(fn, path, value, annotation), kind, None, allow_subclass, convert, coerce)]
    issues = node.errors(value, path) or [("type", path, value, annotation, None)]
    problems: list[Problem] = []
    for tag, where, item, expected, detail in issues:
        if tag == "type":
            problems.append(_type_problem(TypeContainer(fn, where, item, expected), kind, path,
                                          allow_subclass, convert, coerce))
            continue
        problem = Problem(tag, where, expected, None if tag == "missing_key" else item, fn, str, detail, expected)
        problem._render = (_shape_message, kind == "default", path)
        problems.append(problem)
    return problems


def _introspected(root: str | None, path: str) -> str | None:
    """
    Where ``path`` lies inside the value of ``root`` (a deep check looked inside it):
    ``"at index [2]"``, ``"at index ['apple'][1]"``, ``"at field x"``. ``None`` when ``path``
    is the parameter itself.
    """
    if root is None or path == root or not path.startswith(root):
        return None
    rest = path[len(root):]
    if rest.startswith("."):
        return f"at field {formatter(rest[1:], 'bold_green')}"
    return f"at index {formatter(rest, 'bold_green')}"


def _subject(path: str, is_default: bool = False, root: str | None = None) -> str:
    """
    The start of a message: "For parameter x", "For default value of parameter x", "For return value".
    With deep checks, an item inside ``root``: "For introspected parameter x at index [2]".
    """
    if (where := _introspected(root, path)) is not None:
        if root == "return":
            return f"For introspected {formatter('return', 'bold_cyan')} value {where}"
        if is_default:
            return (f"For {formatter('default', 'bold_orange')} value of introspected parameter "
                    f"{formatter(root, 'bold_green')} {where}")
        return f"For introspected parameter {formatter(root, 'bold_green')} {where}"
    if path == "return":
        return f"For {formatter('return', 'bold_cyan')} value"
    if is_default:
        return f"For {formatter('default', 'bold_orange')} value of parameter {formatter(path, 'bold_green')}"
    return f"For parameter {formatter(path, 'bold_green')}"


def _subject_path(problem: Problem) -> str:
    """Where a shape problem is reported: the mapping itself for a missing key."""
    if problem.kind == "missing_key":
        return problem.parameter[: len(problem.parameter) - len(_deep._key_label(problem.detail)) - 2]
    return problem.parameter


def _shape_body(problem: Problem) -> str:
    """What is wrong, for the problems that aren't a plain wrong type."""
    if problem.kind == "length":
        wanted, got = problem.detail, len(problem.value)    # 2, or "at least 2" where the length isn't fixed
        return (
            f"expected type: {formatter(_shortened(_format_annotation(problem.expected)), 'bold_yellow')} with "
            f"{formatter(wanted, 'bold_yellow')} {'item' if wanted in (1, 'at least 1') else 'items'}, "
            f"got {formatter(got, 'bold_red')} {'item' if got == 1 else 'items'} "
            f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
            )
    if problem.kind == "missing_key":
        return (
            f"missing required key {formatter(repr(problem.detail), 'bold_green')} "
            f"(expecting type {formatter(_format_annotation(problem.expected), 'bold_yellow')})"
            )
    if problem.kind == "invalid":
        return (
            f"invalid {formatter(_quoted(problem.expected), 'bold_yellow')}: "
            f"{formatter(problem.detail, 'bold_red')} (Value: {formatter(short_repr(problem.value), 'bold_red')})"
            )
    return (                                            # "cycle"
        f"value contains itself or is nested too deeply "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )


def _shape_message(problem: Problem, is_default: bool = False, root: str | None = None) -> str:
    subject = _subject(_subject_path(problem), is_default, root)
    return f"{subject} of {describe_origin(problem.origin)}: {_shape_body(problem)}"


#* The renderer of a rejected value, as ``_type_problem`` sets it for an argument.
_SHAPE_RENDER = (_shape_message, False, None)


class PreparedChecker:
    """
    Per-function checker compiled on first call and reused afterwards.

    Holds the resolved annotations, validated defaults, the bound-parameter layout
    and one precompiled predicate per parameter. The fast path only ever answers
    "definitely fine"; anything else (errors, odd call shapes) is handed to the full
    path (``_full_check``), so messages are identical to the uncompiled behaviour.
    """
    #* Slots: attribute reads stay fast however many there are (instances with more than ~30
    #* plain attributes lose CPython's inline-attribute fast path, slowing every self.x).
    __slots__ = (
        "fn", "convert", "coerce", "deep", "rewrite_defaults", "_given_record", "allow_subclass", "owner",
        "skip_first", "ready", "defaults_ok", "record", "nodes", "pos_names", "n_pos", "kw_names", "required",
        "var_pos", "var_kw", "checks", "var_pos_check", "var_kw_check", "ret_check", "specs", "ret_spec",
        "converters", "check_order", "var_pos_conv", "var_kw_conv", "can_convert", "ret_conv", "extra_defaults",
        "resolve", "var_pos_node", "var_pos_annotation", "sig", "call", "inject", "me", "self_in", "self_uses", "class_first",
        "family", "plan", "kw_plan", "required_at", "bound_at", "ret_entry",
        )
    var_pos_node: Any
    var_pos_annotation: Any
    sig: inspect.Signature
    plan: Any                   # set by ``_plan``, with ``kw_plan`` and ``required_at``; None: the one pass is not used
    kw_plan: Any
    required_at: Any
    bound_at: int
    ret_entry: Any

    def __init__(
        self,
        fn: Callable[..., Any],
        allow_subclass: bool,
        owner: type | None,
        skip_first: bool,
        record: dict[str, Any] | None = None,
        convert: bool = True,
        coerce: bool = False,
        rewrite_defaults: "bool | str" = False,
        deep: bool = False,
        extra_defaults: "_ExtraDefaults | None" = None,
        resolve: "Callable[[str], Any] | None" = None,
        me: type | None = None,
        family: "dict[int, Any] | None" = None,
        ) -> None:

        self.fn = fn
        self.convert = convert
        self.coerce = coerce
        self.deep = deep
        #* What happens to a default that is converted (``x: float = 0``). False: nothing (a field
        #* checker, a record that is only tested). True: the wrapper is to call something that
        #* receives ``0.0``, without touching ``fn`` (see ``call`` and ``inject``). ``_IN_PLACE``: it is
        #* written into ``fn`` itself. ``_PASSED``: it is handed back with the checked arguments
        #* (typecheck_record, which never calls ``fn`` and never changes it).
        self.rewrite_defaults = rewrite_defaults
        #* What the wrapper calls: ``fn``, or once a default was converted a copy of ``fn`` that has it.
        self.call: Any = fn
        #* Converted defaults that no copy can hold, because the defaults aren't ``fn``'s own (a
        #* decorator made with ``functools.wraps``, a ``functools.partial``, an object with
        #* ``__call__``): name -> value, passed explicitly where a call leaves the parameter out.
        self.inject: dict[str, Any] | None = None
        self.extra_defaults = extra_defaults    # defaults that aren't parameters of fn (see _check_defaults)
        self._given_record = record     # explicit annotations (typecheck_record); None = resolve from fn
        self.allow_subclass = allow_subclass
        self.owner = owner
        self.skip_first = skip_first
        #* For a method: the class ``Self`` stands for in this checker (None: the owner), and where
        #* its annotations use ``Self`` (None until they are resolved by ``_prepare``, then
        #* ``_SELF_IN_PARAMETERS`` and ``_SELF_IN_RETURN``; 0 for anything that isn't a method).
        #* ``family``: the wrappers of the same method for the other classes it was called on, None
        #* until there is one (see ``_route``). ``self_uses`` and ``class_first`` are set by ``_prepare``.
        self.me = me
        self.family = family
        self.self_in: int | None = None
        self.ready = False
        self.plan = None                # until ``_prepare`` has laid one out (``_plan``)
        self.ret_entry = None
        self.defaults_ok = False
        #* Reads a name left as a string inside an annotation. With an explicit record it is only set
        #* by a caller whose record comes from source code (a dataclass's fields): the strings of a
        #* typecheck_record record are data, and are never evaluated.
        self.resolve = resolve
        #* ``var_pos_node`` / ``var_pos_annotation`` are set by ``_prepare``, like the other results:
        #* for ``*args: *tuple[int, str]`` the node that checks the extra positional arguments as one
        #* tuple, and that tuple annotation (for messages); None for every other function.
        return

    def _prepare(self, args: tuple[Any, ...] = ()) -> None:
        P = inspect.Parameter
        fn = self.fn
        sig = _signature(fn)
        self_uses: dict[str, bool] | None = None
        class_first = False
        if self._given_record is not None:
            record, resolve = self._given_record, self.resolve
        else:
            #* A method decorated on its own doesn't know its class until it is called.
            if self.owner is None and (found := _find_owner(fn, args)) is not None:
                self.owner, through_self = found
                self.skip_first = self.skip_first or through_self
                _tag_owner(fn, self.owner)
            #* A method (it takes ``self`` or ``cls``): ``Self`` is the class of this call, exactly.
            uses: dict[str, bool] = {}                  # name -> whether its annotation is ``Self`` and nothing else
            method = self.owner is not None and self.skip_first
            record = _resolve_annotations(fn, self.owner, not self.allow_subclass,
                                          (self.me or self.owner) if method else None, uses)
            if method and uses:
                self_uses = uses
                first = args[0] if args else None
                class_first = (isinstance(first, type) and not isinstance(first, self.owner)       # type: ignore[arg-type]
                               and self.owner in first.__mro__)
            record, sig = _typed_kwargs(record, sig)
            resolve = self.resolve = _resolver(fn, self.owner)
        #* Where ``Self`` stands (name -> whether it is the whole annotation; None: nowhere, or this is
        #* no method), and whether the first argument is the class itself, as for a class method.
        self.self_uses, self.class_first = self_uses, class_first
        self.self_in = 0 if self_uses is None else (
            (_SELF_IN_PARAMETERS if any(name != "return" for name in self_uses) else 0)
            | (_SELF_IN_RETURN if "return" in self_uses else 0))
        self.sig = sig
        if not self.defaults_ok:
            converted = _check_defaults(fn, record, self.allow_subclass, self.convert, self.coerce,
                                        self.rewrite_defaults is _IN_PLACE, self.deep, self.extra_defaults, resolve, sig)
            own = _own_signature(fn)
            if converted and self.rewrite_defaults is True and own:
                self.call = _with_defaults(fn, converted, sig)
            elif converted and (self.rewrite_defaults in (True, _PASSED) or (self.rewrite_defaults is _IN_PLACE and not own)):
                #* Nowhere to write them: they are passed with each call that leaves the parameter out.
                self.inject = {name: value for name, (_, value) in converted.items()}
            self.defaults_ok = True

        pos_names: list[str] = []
        kw_names: set[str] = set()
        required: list[str] = []
        var_pos = var_kw = None
        for name, p in sig.parameters.items():
            if p.kind is P.VAR_POSITIONAL:
                var_pos = name
                continue
            if p.kind is P.VAR_KEYWORD:
                var_kw = name
                continue
            if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD):
                pos_names.append(name)
            if p.kind is not P.POSITIONAL_ONLY:
                kw_names.add(name)
            if p.default is P.empty:
                required.append(name)

        #* Whether a method that uses ``Self`` is called on instances or on the class shows in the
        #* first argument: without one (a call that can't be made anyway) it is found out next time.
        cacheable = not (self.self_in and not args)
        checks: dict[str, Callable[[Any], bool]] = {}
        specs: dict[str, tuple] = {}
        converters: dict[str, Callable[[Any], Any]] = {}
        var_pos_check = var_kw_check = None
        flags = (self.allow_subclass, self.convert, self.coerce)
        ret_flags = self._return_flags()
        #* ``*args: *tuple[...]`` describes the extra positional arguments as a whole.
        var_pos_node = var_pos_annotation = None
        if var_pos is not None and (unpacked := _unpacked_tuple(record.get(var_pos))) is not None:
            items = get_args(unpacked)
            if len(items) == 2 and items[1] is Ellipsis:
                record = {**record, var_pos: items[0]}      # *tuple[int, ...] says what *args: int says
            else:
                record = {**record, var_pos: Any}           # no test per argument: the tuple is checked below
                node = _args_node(unpacked, *flags, self.deep, resolve)
                if node is SLOW:
                    cacheable = False
                elif node is not None:
                    var_pos_node, var_pos_annotation = node, unpacked
        #* Deep checks, per parameter (and "return"): only annotations with items to check.
        nodes: dict[str, Any] = {}
        if self.deep:
            for name, annotation in record.items():
                if name == "return":
                    node = _deep_node(type(None) if annotation is None else annotation, *ret_flags, resolve)
                else:
                    node = _deep_node(annotation, *flags, resolve)
                if node is not None:
                    nodes[name] = node
        for name, annotation in record.items():
            if name == "return":
                continue
            spec = _compile_spec(annotation, self.allow_subclass, name, self.deep, self.convert, self.coerce, resolve)
            if spec is SLOW:
                cacheable = False       # e.g. forward ref not defined yet: retry on the next call
                spec = ("pred", _always_false)
            specs[name] = spec          # type: ignore[assignment]
            compiled = _predicate(spec) # type: ignore[arg-type]
            if name == var_pos:
                var_pos_check = compiled
            elif name == var_kw:
                var_kw_check = compiled
            elif compiled is not None:
                checks[name] = compiled   # type: ignore[assignment]
            converter = _compile_converter(annotation, self.allow_subclass, name, self.convert, self.coerce, self.deep,
                                           resolve)
            if converter is not None:
                converters[name] = converter

        ret_check: Callable[[Any], bool] | None = None
        ret_spec: tuple | None = None
        ret_conv: Callable[[Any], Any] | None = None
        if "return" in record:
            rt = record["return"]
            rt = type(None) if rt is None else rt
            _, ret_convert, ret_coerce = ret_flags
            spec = _compile_spec(rt, self.allow_subclass, "return", self.deep, ret_convert, ret_coerce, resolve)
            if spec is SLOW:
                cacheable = False
                spec = ("pred", _always_false)
            ret_spec = spec             # type: ignore[assignment]
            ret_check = _predicate(spec)  # type: ignore[arg-type]
            ret_conv = _compile_converter(rt, self.allow_subclass, "return", ret_convert, ret_coerce, self.deep, resolve)

        self.record = record
        self.nodes = nodes
        self.pos_names = tuple(pos_names)
        self.n_pos = len(pos_names)
        self.kw_names = frozenset(kw_names)
        self.required = tuple(required)
        self.var_pos = var_pos
        self.var_kw = var_kw
        self.checks = checks
        self.var_pos_check = var_pos_check
        self.var_kw_check = var_kw_check
        self.ret_check = ret_check
        self.specs = specs
        self.ret_spec = ret_spec
        self.converters = converters
        self.check_order = tuple(name for name in record if name != "return")
        self.var_pos_conv = converters.pop(var_pos, None) if var_pos else None
        self.var_kw_conv = converters.pop(var_kw, None) if var_kw else None
        self.var_pos_node, self.var_pos_annotation = var_pos_node, var_pos_annotation
        self.can_convert = (bool(converters) or self.var_pos_conv is not None or self.var_kw_conv is not None
                            or (var_pos_node is not None and var_pos_node.can_convert))
        self.ret_conv = ret_conv
        self.plan = self.kw_plan = self.required_at = self.ret_entry = None
        if cacheable:                           # a checker that isn't ready prepares again at the next call
            self._plan(record, checks, converters, sig, var_pos_node is not None)
            if ret_check is not None and nodes.get("return") is None:
                #* Like a plan entry, for the return value (``check_return``).
                rt = type(None) if record["return"] is None else record["return"]
                self.ret_entry = (ret_check, ret_conv, "return", 0, *_only_type("return", rt, ret_flags[1]), rt)
        self.ready = cacheable

    def _plan(self, record: dict[str, Any], checks: dict[str, Any], converters: dict[str, Any],
              sig: inspect.Signature, tuple_args: bool) -> None:
        """
        Lay the checks out for the one pass that the general path makes over a call (``check_inputs``):
        ``plan`` has one entry per positional parameter, in order (``None``: nothing to check),
        ``kw_plan`` the same by name, ``required_at`` each required parameter with its position
        (-1: keyword-only). An entry is ``(check, converter, name, order, expected, quick, annotation)``;
        ``expected`` is the runtime type where a failure can only be a wrong type, and ``_NO_TYPE``
        where it may also be a rejected value (an ``Annotated`` check, a TypeModel), which the
        slower way of making a problem finds out.

        ``plan`` is ``None`` for a function that the pass doesn't take: ``*args`` / ``**kwargs``,
        or items to check inside collections (``deep``). Those keep the three passes
        (``_fast_ok``, ``_convert``, ``_type_problems``).
        """
        if self.var_pos is not None or self.var_kw is not None or self.nodes or tuple_args:
            return
        tolerant = self.convert or self.coerce
        entries: dict[str, tuple[Any, ...]] = {}
        for order, name in enumerate(self.check_order):
            check = checks.get(name)
            if check is not None:
                entries[name] = (check, converters.get(name), name, order, *_only_type(name, record[name], tolerant), record[name])
        self.kw_plan = {name: entries.get(name) for name in self.kw_names}
        position = {name: i for i, name in enumerate(self.pos_names)}
        self.required_at = tuple([(name, position.get(name, -1)) for name in self.required])
        #* With this many positional arguments, no required parameter is left to ask after.
        at = [position.get(name, -1) for name in self.required]
        self.bound_at = sys.maxsize if -1 in at else max(at, default = -1) + 1
        #* Last: ``check_inputs`` goes by ``plan`` alone, and another thread may be in it now.
        self.plan = tuple([entries.get(name) for name in self.pos_names])
        return

    def _problems_of(self, found: "list[tuple[int, Any, Any]] | None", missing: "list[str] | None") -> list[Problem]:
        """
        The problems of a call that ``check_inputs`` refused, made when the error is asked for
        them (``TypeCheckerError.problems``): the missing arguments first, then each argument
        that failed, in the order of the parameters however they were passed. ``found`` holds
        ``(order, plan entry, value)``, or ``(order, None, problem)`` for one that was made at once.
        """
        problems: list[Problem] = []
        if missing is not None:
            names, record, fn = tuple(missing), self.record, self.fn
            problems.append(Problem("missing", names, tuple([record.get(m) for m in missing]), None, fn,
                                    partial(_missing_msg, fn, names, record, False)))
        if found is not None:
            if len(found) > 1:
                found.sort(key = _first)
            for _, entry, value in found:
                problems.append(value if entry is None else self._problem(entry, value))
        return problems

    def _problem(self, entry: tuple[Any, ...], value: Any, bare: bool = False) -> Problem:
        """
        The problem for an argument that failed its test and couldn't be converted. Where only the
        type can be wrong it is put together from what the plan holds, and the text is left for
        later (``_late_type_message``). ``bare``: next to a missing argument, where the full path
        never looked for a reason behind a rejected value.

        A value that may have been rejected (``_NO_TYPE``) is first asked the short way (see
        ``_only_type``); what that finds is what ``_invalid_reason`` would find first.
        """
        expected, name, annotation = entry[4], entry[2], entry[6]
        if expected is _NO_TYPE:
            quick, failure = entry[5], None
            if type(quick) is TypeContainer:
                failure = quick.constraint_failure(value, self.allow_subclass)
            elif quick is not None and not bare:
                rejected = _REJECTED
                if rejected[0] is value and rejected[1] is quick:
                    failure = (quick, rejected[2])
                    rejected[0] = rejected[1] = rejected[2] = None
            if failure is not None:
                return Problem("invalid", name, failure[0], value, self.fn, _SHAPE_RENDER, failure[1], annotation)
            container = TypeContainer(self.fn, name, value, annotation)
            if bare:
                return _type_problem(container, allow_subclass = self.allow_subclass)
            return _type_problem(container, "type", None, self.allow_subclass, self.convert, self.coerce)
        fn = self.fn
        return Problem("return" if name == "return" else "type", name, expected, value, fn,
                       partial(_late_type_message, fn, name, value, annotation), None, annotation)

    def _return_flags(self) -> tuple[bool, bool, bool]:
        """
        ``(allow_subclass, convert, coerce)`` for the return value. It gets the lossless conversions
        (``1`` -> ``1.0``, which ``coerce`` includes) but is never coerced: parsing is for what comes
        in from outside, and a function that returns ``"42"`` for an ``int`` has a bug to report.
        """
        return self.allow_subclass, self.convert or self.coerce, False

    def _fast_ok(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        n_pos = self.n_pos
        extra_args: tuple[Any, ...] = ()
        if len(args) > n_pos:
            if self.var_pos is None:
                return False
            extra_args = args[n_pos:]
        arguments = dict(zip(self.pos_names, args))
        extra_kwargs: dict[str, Any] | None = None
        if kwargs:
            kw_names = self.kw_names
            for k, v in kwargs.items():
                if k in arguments:
                    return False
                if k in kw_names:
                    arguments[k] = v
                elif self.var_kw is not None and k not in self.pos_names:
                    if extra_kwargs is None:
                        extra_kwargs = {}
                    extra_kwargs[k] = v
                else:
                    return False
        for r in self.required:
            if r not in arguments:
                return False
        checks = self.checks
        for k, v in arguments.items():
            chk = checks.get(k)
            if chk is not None and not chk(v):
                return False
        if extra_args and self.var_pos_check is not None:
            if not all(self.var_pos_check(item) for item in extra_args):
                return False
        if self.var_pos_node is not None and not self.var_pos_node.check(extra_args):      # also when there are none
            return False
        if extra_kwargs and self.var_kw_check is not None:
            if not all(self.var_kw_check(item) for item in extra_kwargs.values()):
                return False
        return True

    def _convert(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any], bool]:
        """Replace every failing argument that has a valid conversion. Binding errors are left for the checks."""
        new_args: list[Any] | None = None
        new_kwargs: dict[str, Any] | None = None
        checks, converters = self.checks, self.converters
        for i, value in enumerate(args):
            if i < self.n_pos:
                name = self.pos_names[i]
                check, converter = checks.get(name), converters.get(name)
            else:
                check, converter = self.var_pos_check, self.var_pos_conv
            if converter is not None and check is not None and not check(value):
                if (out := converter(value)) is not FAILED:
                    new_args = new_args or list(args)
                    new_args[i] = out
        for key, value in kwargs.items():
            if key in self.kw_names:
                check, converter = checks.get(key), converters.get(key)
            elif self.var_kw is not None:
                check, converter = self.var_kw_check, self.var_kw_conv
            else:
                continue
            if converter is not None and check is not None and not check(value):
                if (out := converter(value)) is not FAILED:
                    new_kwargs = new_kwargs or dict(kwargs)
                    new_kwargs[key] = out
        node = self.var_pos_node
        if node is not None and node.can_convert and not node.check(rest := args[self.n_pos:]):
            try:
                fixed: Any = node.convert(rest)
            except Exception:
                fixed = FAILED
            if fixed is not FAILED and node.check(fixed):
                new_args = (new_args or list(args))[:self.n_pos] + list(fixed)
        changed = new_args is not None or new_kwargs is not None
        return (tuple(new_args) if new_args is not None else args,
                new_kwargs if new_kwargs is not None else kwargs, changed)

    #* Core checks
    def check_inputs(self, args: tuple[Any, ...], kwargs: dict[str, Any],
                     failed: str | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        Validate a call; returns ``(args, kwargs)`` with converted values swapped in. Raises on failure.

        Where there is a ``plan`` this is one pass: bind the call, test each argument, convert the
        ones that fail and can be, and note the rest. It is where a wrong call spends its time,
        and with tiered compilation where the first calls of every function do, so it is written
        out here in one piece (as a method of its own it cost a wrong call 50 ns more). What is
        noted is not made into problems: the error makes them when it is asked (``_problems_of``),
        except where finding out what is wrong means running the user's code (an ``Annotated``
        check, a TypeModel), which is done now, on the value as it is.

        ``failed`` names a parameter whose converter the caller has just run on this call's
        value, to no avail: it is not run again.

        The pass leaves (``break``) a call that doesn't bind for another reason than a missing
        argument, and a missing argument next to a positional one that doesn't fit: there the
        full path looks for a better placement.
        """
        plan = self.plan
        if plan is None and not self.ready:
            self._prepare(args)
            plan = self.plan
        while plan is not None:                         # one round: ``break`` hands the call to the slower way
            n = len(args)
            if n > self.n_pos:
                break
            #* Binding first: nothing is converted for a call that turns out not to bind.
            kw_plan = self.kw_plan
            if kwargs:
                given = self.pos_names[:n]
                unbound = False
                for key in kwargs:
                    if key not in kw_plan or key in given:
                        unbound = True
                        break
                if unbound:
                    break
            missing: list[str] | None = None
            if n < self.bound_at:                       # else every required parameter was given by position
                for name, at in self.required_at:
                    if (at < 0 or at >= n) and name not in kwargs:
                        if missing is None:
                            missing = []
                        missing.append(name)

            found: list[tuple[int, Any, Any]] | None = None
            new_args: list[Any] | None = None
            misplaced = False
            i = 0
            for value in args:
                entry = plan[i]
                i += 1
                if entry is None or entry[0](value):
                    continue
                if missing is not None:                 # a missing argument and one that doesn't fit: the full path
                    misplaced = True
                    break
                converter = entry[1]
                if converter is not None and entry[2] != failed and (out := converter(value)) is not FAILED:
                    if new_args is None:
                        new_args = list(args)
                    new_args[i - 1] = out
                    continue
                if found is None:
                    found = []
                if entry[4] is _NO_TYPE:
                    found.append((entry[3], None, self._problem(entry, value)))
                else:
                    found.append((entry[3], entry, value))
            if misplaced:
                break
            new_kwargs: dict[str, Any] | None = None
            if kwargs:
                for key, value in kwargs.items():
                    entry = kw_plan[key]
                    if entry is None or entry[0](value):
                        continue
                    converter = entry[1]
                    if converter is not None and entry[2] != failed and (out := converter(value)) is not FAILED:
                        if new_kwargs is None:
                            new_kwargs = dict(kwargs)
                        new_kwargs[key] = out
                        continue
                    if found is None:
                        found = []
                    if entry[4] is _NO_TYPE:
                        found.append((entry[3], None, self._problem(entry, value, missing is not None)))
                    else:
                        found.append((entry[3], entry, value))

            if found is not None or missing is not None:
                #* Made by a function, never held in a local here: the error's traceback holds this
                #* frame, and a frame that holds the error makes a cycle of the two, which only
                #* the collector frees (a wrong call cost 350 ns more that way).
                raise pending_error(self, found, missing)
            if new_args is not None:
                args = tuple(new_args)
            if new_kwargs is not None:
                kwargs = new_kwargs
            return args, kwargs

        if self.ready:
            if plan is not None and (said := self._binding_error(args, kwargs)) is not None:
                raise said_error(said)
            #* Without converters, _type_problems below answers "fine" just as well (it returns []),
            #* so the error path doesn't run every check (and deep scan) one extra time.
            if self.can_convert:
                if self._fast_ok(args, kwargs):
                    return args, kwargs
                args, kwargs, changed = self._convert(args, kwargs)
                if changed and self._fast_ok(args, kwargs):
                    return args, kwargs
            #* Common failure: the call binds fine and only types are wrong. Report it straight
            #* from the prepared layout. Errors are reported on the (partly) converted call.
            problems = self._type_problems(args, kwargs)
            if problems:
                raise _typechecker_type_error_factory(problems)
            if problems is not None:
                return args, kwargs
        #* An argument too many, a name given twice, a keyword nobody takes: said at once, in the
        #* words Signature.bind uses, without running it (it takes 2 µs to arrive at the same sentence).
        if self.ready and (said := self._binding_error(args, kwargs)) is not None:
            raise said_error(said)
        #* Missing arguments, and whatever else doesn't bind: the full path (with realignment hints).
        _full_check(self.fn, self.record, self.allow_subclass, args, kwargs, self.skip_first,
                    nodes = self.nodes, sig = self.sig)
        return args, kwargs

    def _binding_error(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
        """
        What ``Signature.bind`` says of a call that can't be bound for one of the three usual
        reasons, found in the order it finds them: too many positional arguments, a parameter given
        by position and by name, a keyword that no parameter takes. ``None`` for a call that binds,
        and for a positional-only parameter passed by keyword, which the full path words.
        """
        names, parameters = self.pos_names, self.sig.parameters
        positional_only = inspect.Parameter.POSITIONAL_ONLY
        for i in range(len(args)):
            if i >= self.n_pos:
                if self.var_pos is None:
                    return "too many positional arguments"
                break
            if names[i] in kwargs:
                if parameters[names[i]].kind is positional_only:
                    return None
                return f"multiple values for argument {names[i]!r}"
        unknown = None
        for key in kwargs:
            if key in self.kw_names:
                continue
            if key in names:                            # a positional-only parameter, by keyword
                return None
            if unknown is None and self.var_kw is None:
                unknown = key
        return None if unknown is None else f"got an unexpected keyword argument {unknown!r}"

    def with_defaults(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        A checked call with the converted defaults of ``inject`` filled in for the parameters it
        leaves out: by keyword where the parameter takes one, else by position (which then needs
        the default of every positional-only parameter before it as well).
        """
        inject, given = self.inject, len(args)
        out: dict[str, Any] | None = None
        by_position: list[str] = []
        for name in inject:                                 # type: ignore[union-attr]
            if name in kwargs:
                continue
            if name in self.kw_names:
                if name not in self.pos_names[:given]:
                    out = out or dict(kwargs)
                    out[name] = inject[name]                # type: ignore[index]
            elif name in self.pos_names[given:]:
                by_position.append(name)
        if by_position:
            last = max(self.pos_names.index(name) for name in by_position)
            parameters = self.sig.parameters
            args += tuple(inject.get(name, parameters[name].default) for name in self.pos_names[given:last + 1])  # type: ignore[union-attr]
        return args, kwargs if out is None else out

    def _type_problems(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> "list[Problem] | None":
        """
        Wrong-type problems for a call that binds cleanly, in the same order and wording as
        the full path. Returns ``None`` when binding isn't clean (let the full path explain).
        Only failing arguments get a ``TypeContainer``.
        """
        n_pos = self.n_pos
        if len(args) > n_pos and self.var_pos is None:
            return None
        arguments = dict(zip(self.pos_names, args))
        extra_kwargs: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key in arguments:
                return None
            if key in self.kw_names:
                arguments[key] = value
            elif self.var_kw is not None and key not in self.pos_names:
                extra_kwargs[key] = value
            else:
                return None
        for name in self.required:
            if name not in arguments:
                return None

        if self.nodes:
            return self._deep_problems(args, arguments, extra_kwargs)
        fn, record, checks = self.fn, self.record, self.checks
        flags = (self.allow_subclass, self.convert, self.coerce)
        problems: list[Problem] = []
        for name in self.check_order:
            if name == self.var_pos:
                check = self.var_pos_check
                if self.var_pos_node is not None:
                    problems += self._unpacked_args_problems(args)
                elif check is not None:
                    problems += [_type_problem(TypeContainer(fn, f"{name}[{i}]", item, record[name]), "type", None, *flags)
                                 for i, item in enumerate(args[n_pos:]) if not check(item)]
            elif name == self.var_kw:
                check = self.var_kw_check
                if check is not None:
                    problems += [_type_problem(TypeContainer(fn, f"{name}[{k}]", v, record[name]), "type", None, *flags)
                                 for k, v in extra_kwargs.items() if not check(v)]
            elif name in arguments:
                check = checks.get(name)
                if check is not None and not check(arguments[name]):
                    problems.append(_type_problem(TypeContainer(fn, name, arguments[name], record[name]), "type", None, *flags))
        return problems

    def _deep_problems(
        self, args: tuple[Any, ...], arguments: dict[str, Any], extra_kwargs: dict[str, Any],
        ) -> "list[Problem]":
        """``_type_problems`` when some parameters have deep checks: one problem per bad item."""
        fn, record, checks, nodes = self.fn, self.record, self.checks, self.nodes
        flags = (self.allow_subclass, self.convert, self.coerce)
        problems: list[Problem] = []
        for name in self.check_order:
            node = nodes.get(name)
            if name == self.var_pos:
                check = self.var_pos_check
                if self.var_pos_node is not None:
                    problems += self._unpacked_args_problems(args)
                elif check is not None:
                    for i, item in enumerate(args[self.n_pos:]):
                        if not check(item):
                            problems += _value_problems(fn, f"{name}[{i}]", item, record[name], node, "type", *flags)
            elif name == self.var_kw:
                check = self.var_kw_check
                if check is not None:
                    for k, v in extra_kwargs.items():
                        if not check(v):
                            problems += _value_problems(fn, f"{name}[{k}]", v, record[name], node, "type", *flags)
            elif name in arguments:
                check = checks.get(name)
                if check is not None and not check(arguments[name]):
                    problems += _value_problems(fn, name, arguments[name], record[name], node, "type", *flags)
        return problems

    def _unpacked_args_problems(self, args: tuple[Any, ...]) -> "list[Problem]":
        """``*args: *tuple[int, str]``: what is wrong with the extra positional arguments, taken as that tuple."""
        rest, node, name = args[self.n_pos:], self.var_pos_node, str(self.var_pos)
        if node.check(rest):
            return []
        return _value_problems(self.fn, name, rest, self.var_pos_annotation, node, "type",
                               self.allow_subclass, self.convert, self.coerce)

    def check_return(self, result: Any) -> Any:
        """Validate a return value; returns it (converted if needed). Raises on failure."""
        if not self.ready:
            self._prepare()
        if self.ready:
            chk = self.ret_check
            if "return" not in self.record or chk is None or chk(result):
                return result
            if self.ret_conv is not None and (out := self.ret_conv(result)) is not FAILED:
                return out
            entry = self.ret_entry
            if entry is not None and entry[4] is not _NO_TYPE:  # only the type can be wrong: said when the error is read
                raise pending_error(self, [(0, entry, result)], None)
        allow_subclass, convert, coerce = self._return_flags()
        _typecheck_return_pipeline(self.fn, self.record, allow_subclass, result, self.nodes.get("return"), convert, coerce)
        return result


def _always_false(_: Any) -> bool:
    return False


#* In a plan entry: a failure of this parameter may be a rejected value, not only a wrong type.
_NO_TYPE: Any = object()


def _only_type(name: str, annotation: Any, tolerant: bool) -> tuple[Any, Any]:
    """
    The last two parts of a plan entry, ``(expected, quick)``: what a value that fails
    ``annotation`` can have wrong.

    ``expected`` is the runtime type where it can only be the type, and ``_NO_TYPE`` where it may
    also be a rejected value: an ``Annotated`` check, or with ``tolerant`` (values are converted) a
    TypeModel. Why a value was rejected is found by ``_invalid_reason``, the long way. ``quick``
    is a shorter one for the two usual shapes (``PreparedChecker._problem``): a container of the
    annotation, to ask its checks, or where the annotation is one TypeModel class, that class
    (the converter has just run its ``validate`` and left the reason in ``_REJECTED``).
    """
    try:
        container = TypeContainer(None, name, None, annotation)
        targets = container._expected_type
        models = any(is_model(t) for t in (targets if isinstance(targets, TypeUnion) else (targets,)))
        if container._constraints is not None:
            return _NO_TYPE, container
        if not (tolerant and models):
            return targets, None
        if not isinstance(targets, TypeUnion):
            return _NO_TYPE, targets
    except Exception:
        pass
    return _NO_TYPE, None


def _first(pair: tuple[Any, ...]) -> int:
    return pair[0]


def _late_type_message(fn: Any, name: str, value: Any, annotation: Any) -> str:
    """The text of a wrong-type problem that ``PreparedChecker._problem`` made without a container."""
    return _parameter_type_error_msg_factory(TypeContainer(fn, name, value, annotation))


def _typecheck_return_pipeline(
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
        raise _unresolved_error(return_type, "return")
    if node is not None:
        if not node.check(result):
            raise _typechecker_type_error_factory(_value_problems(fn, "return", result, return_type, node, "return",
                                                                  allow_subclass, convert, coerce))
        return
    container = TypeContainer(fn, "return", result, return_type)
    if not container.check(allow_subclass):
        raise _typechecker_type_error_factory([_type_problem(container, "return", None, allow_subclass, convert, coerce)])


def _resolve_annotations(fn: Callable[..., Any], owner: type | None = None, strict_self: bool = False,
                         me: type | None = None, uses: dict[str, bool] | None = None) -> dict[str, Any]:
    """
    The annotations of ``fn`` as objects: strings are evaluated in its module, with the names that
    are only visible where it was written (``_local_names``).

    ``Self`` becomes ``me``: the class a method is called on, where the caller knows it (see
    ``_route``). Without ``me`` it becomes ``owner``, or with ``strict_self`` a stand-in that
    accepts ``owner`` and its subclasses: the class of the instance isn't known there, and the
    exact type of the owner would reject every instance of a subclass (see ``SelfType``).
    ``uses`` collects the entries in which ``Self`` stands: name -> whether it is the whole annotation.
    """
    localns = _local_names(fn, owner)
    record: Any = None
    try:
        record = get_type_hints(fn, localns = localns, include_extras = True)   # keeps Annotated checks
    except Exception:
        #* The name that isn't known may have come into being since the decorator ran (see _look_again).
        if _look_again(fn, owner):
            localns = _local_names(fn, owner)
            try:
                record = get_type_hints(fn, localns = localns, include_extras = True)
            except Exception:
                pass
    if record is None:
        try:
            raw = get_annotations(fn)
        except Exception:
            raw = {}
        globalns = getattr(_unwrapped(fn), "__globals__", {})
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
        #* Fields of a dataclass whose values a descriptor takes care of (see ``_dataclass_override``).
        if unchecked := vars(owner).get(UNCHECKED_FIELDS):
            record = {k: v for k, v in record.items() if k not in unchecked}
        with_self = [k for k, v in record.items() if _has_self(v)]
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


def _has_self(annotation: Any, depth: int = 0) -> bool:
    """Whether ``Self`` stands anywhere in ``annotation``. By identity: an annotation may define ``==``."""
    if annotation is Self:
        return True
    args = getattr(annotation, "__args__", None)
    if not args or depth > 8 or type(args) is not tuple:
        return False
    for arg in args:
        if _has_self(arg, depth + 1):
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


def _look_again(fn: Any, owner: type | None) -> bool:
    """
    An annotation of ``fn`` names something unknown. If ``fn`` (or its class) was defined inside a
    function, the name may be local to that function and have come into being after the decorator
    ran: a class written a few lines further down. While that function is still running, as it is
    in a test that defines its classes and then uses them, its frame is on the stack, and the
    names are looked up there once more. Nothing is kept alive for this: once the function has
    returned, such a name can't be found any more. Returns whether a new name was found.
    """
    new = False
    for target in (owner, fn):
        if target is None or "<locals>" not in getattr(target, "__qualname__", ""):
            continue
        known = set(vars(target).get(_SCOPE) or ())         # its own: a class would also show its base's
        _remember_scope(target, sys._getframe(2), isinstance(target, type) and _is_dataclass(target), 64, False)
        new = new or bool(set(vars(target).get(_SCOPE) or ()) - known)
    return new


def _unwrapped(fn: Any) -> Any:
    try:
        return inspect.unwrap(fn)
    except ValueError:                                  # a __wrapped__ chain that loops
        return fn


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
    record = _resolve_annotations(source, owner, strict_self)
    try:
        taken = _signature(fn).parameters
    except (TypeError, ValueError):
        return None
    return {name: annotation for name, annotation in record.items() if name in taken or name == "return"}


#* Where a function or class decorated inside another function keeps the local names its string
#* annotations use (see ``_remember_scope``).
_SCOPE = "__enforced_scope__"
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def _local_names(fn: Any, owner: type | None) -> dict[str, Any] | None:
    """
    What a string annotation of ``fn`` may name besides the globals of its module: the class it
    belongs to, the type parameters of that class (``class Box[T]``), and what was local to the
    function it was defined in. ``None`` when there is nothing.
    """
    names: dict[str, Any] = {}
    if owner is not None:
        for klass in reversed(owner.__mro__[:-1]):          # base classes first: the class itself wins
            names.update(vars(klass).get(_SCOPE) or ())
            for parameter in getattr(klass, "__type_params__", ()):
                names[parameter.__name__] = parameter
        names[owner.__name__] = owner
    own = getattr(fn, "__dict__", None)                 # where _remember_scope left it: on the function itself
    if own and (scope := own.get(_SCOPE)):
        names.update(scope)
    return names or None


def _remember_scope(target: Any, frame: Any, fields: bool = False, depth: int = 16, later: bool = True) -> None:
    """
    ``target`` (a function or a class) was decorated inside a function. A string annotation of it
    may name something local to that function, such as a class defined a few lines above, and by the
    first call that scope is gone. So the names its annotations use are looked up now, in the frames
    the definition is written in, and what is found is kept on ``target``.

    Only string annotations need this: under ``from __future__ import annotations`` every
    annotation is one. Without that import Python 3.14 keeps the enclosing scope itself.

    For a class, what is read depends on what is checked: the annotations of its methods (a class
    given to ``enforce``), or with ``fields`` those of the class and its base classes (a dataclass).

    A name that is nowhere yet may be defined further down in the same function. With ``later``,
    it is looked for once more when that function ends (see ``_when_it_ends``).
    """
    try:
        texts: list[str] = []
        if isinstance(target, type) and fields:
            for klass in target.__mro__[:-1]:
                texts += _annotation_texts(klass)
        elif isinstance(target, type):
            for member in vars(target).values():
                member = getattr(member, "__func__", member)
                if isinstance(member, FunctionType):
                    texts += _annotation_texts(_unwrapped(member))
        else:
            texts = _annotation_texts(target)
        text = " ".join(texts)
        wanted = set(_NAME.findall(_QUOTED.sub(" ", text) if "'" in text or '"' in text else text))
        if not wanted:
            return
        qualname, module, found = target.__qualname__, target.__module__, {}
        parents: list[Any] = []
        for _ in range(depth):
            if frame is None or frame.f_locals is frame.f_globals:      # module level: those names are globals
                break
            #* Only the scopes the definition is written in, not whatever happens to be calling.
            if frame.f_globals.get("__name__") == module and qualname.startswith(frame.f_code.co_qualname + "."):
                #* Of a function that calls itself, the innermost call is the one this was written in.
                if all(frame.f_code is not parent.f_code for parent in parents):
                    parents.append(frame)
                local = frame.f_locals
                for name in wanted:
                    if name not in found and name in local:
                        found[name] = local[name]
            frame = frame.f_back
        _keep_scope(target, found)
        if later and parents:
            known = parents[0].f_globals
            missing = [name for name in wanted if name not in found and name not in known
                       and not hasattr(builtins, name) and name != target.__name__]
            if missing:
                _when_it_ends(parents, target, missing)
    except Exception:                                   # never a reason for a definition to fail
        pass


def _keep_scope(target: Any, found: dict[str, Any]) -> None:
    """Add ``found`` to the local names kept on ``target`` (from an earlier look: kept, what is found now comes on top)."""
    if found:
        known = vars(target).get(_SCOPE)
        setattr(target, _SCOPE, {**known, **found} if known else found)


#* A quoted text inside an annotation (``Literal['r', 'w']``) names nothing.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")

#* Under this name a running function carries, among its own local names, what is to be looked up
#* in it when it ends: [(target, names)]. In the frame, and never the frame somewhere else: a frame
#* keeps its caller's frames, and with them every local of the whole stack, alive for as long as
#* it is held (review finding 31). What the frame carries goes when the frame goes.
_PENDING = "__enforced_pending__"
#* code -> how many of its frames carry something; the code is watched while there is one.
_WATCHED: dict[CodeType, int] = {}
_WATCHER: list[Any] = []                                # [tool id], or [None] where none could be had


def _watcher() -> int | None:
    """
    The ``sys.monitoring`` tool id under which enforced hears of a function returning, taken on
    first use: one of the two that no kind of tool is assigned (debuggers, coverage, profilers and
    the optimiser have theirs). ``None`` when both are taken: then a later name is found as before,
    only while its function runs.
    """
    if not _WATCHER:
        chosen = None
        try:
            monitoring = sys.monitoring
            for tool in (4, 3):
                if monitoring.get_tool(tool) is None:
                    monitoring.use_tool_id(tool, "enforced")
                    monitoring.register_callback(tool, monitoring.events.PY_RETURN, _it_returned)
                    chosen = tool
                    break
        except Exception:
            chosen = None
        _WATCHER.append(chosen)
    return _WATCHER[0]


def _when_it_ends(frames: list[Any], target: Any, names: list[str]) -> None:
    """
    ``target`` was decorated inside the functions that ``frames`` are running, and its annotations
    use ``names`` that exist nowhere yet: a class written a few lines further down. They can't be
    waited for by keeping the frame (see ``_PENDING``). So Python is asked to say when each of these
    functions returns: at that moment its local names are final, and the ones wanted are read from
    it (``_it_returned``) and kept on ``target``.

    Only the code of these functions is watched, and only while one of their frames is waited
    for. (A frame that is left by an exception is never heard of: its function stays watched,
    which costs a call at each of its returns and nothing else.)
    """
    tool = _watcher()
    if tool is None:
        return
    for frame in frames:
        code = frame.f_code
        if not code.co_flags & inspect.CO_OPTIMIZED:    # a class body: its names are the class's attributes
            continue
        local = frame.f_locals
        pending = local.get(_PENDING)
        if pending is None:
            local[_PENDING] = pending = []
            with _CACHE_LOCK:
                _WATCHED[code] = _WATCHED.get(code, 0) + 1
                if _WATCHED[code] == 1:
                    sys.monitoring.set_local_events(tool, code, sys.monitoring.events.PY_RETURN)
        pending.append((target, names))


def _it_returned(code: CodeType, *_: Any) -> None:
    """Called by Python when a watched function returns: the frame that returns is the caller's."""
    try:
        local = sys._getframe(1).f_locals
        pending = local.get(_PENDING)
        if pending is None:                             # another call of the same function: nothing waits for it
            return
        with _CACHE_LOCK:
            left = _WATCHED.get(code, 1) - 1
            if left > 0:
                _WATCHED[code] = left
            else:
                _WATCHED.pop(code, None)
                sys.monitoring.set_local_events(_WATCHER[0], code, 0)
        for target, names in pending:
            known = vars(target).get(_SCOPE) or ()      # a name an inner function has supplied stays
            _keep_scope(target, {name: local[name] for name in names if name in local and name not in known})
    except Exception:                                   # never a reason for the function that returned to fail
        pass


_FUTURE_ANNOTATIONS = __future__.annotations.compiler_flag


def _annotation_texts(obj: Any) -> list[str]:
    """
    The annotations of ``obj`` (a function or a class) as source text, when some of them are
    strings: all of them under ``from __future__ import annotations``, otherwise the ones written
    in quotes. Nothing is evaluated. Empty when no annotation is a string: then Python itself
    remembers the enclosing scope, and there is nothing to look up.
    """
    try:
        annotate = getattr(obj, "__annotate__", None)
        if annotate is None:
            #* A class under the future import, or annotations assigned by hand: they are simply there.
            found = vars(obj).get("__annotations__") if isinstance(obj, type) else getattr(obj, "__annotations__", None)
            return [text for text in (found or {}).values() if isinstance(text, str)]
        code = getattr(obj, "__code__", None)
        if code is not None:
            if code.co_flags & _FUTURE_ANNOTATIONS:
                return [text for text in annotate(Format.VALUE).values() if isinstance(text, str)]
            #* Without the import, decorating a local function must stay as cheap as it was. A quoted
            #* annotation shows as a string among the constants of the annotate function, next to the
            #* parameter names: no other string there means nothing is quoted (the usual case).
            names: Any = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount + bool(code.co_flags & 4) + bool(code.co_flags & 8)]
            if not any(text not in names and text != "return" for text in _string_constants(annotate)):
                return []
        elif isinstance(obj, type) and "__annotations_cache__" in vars(obj):
            #* The same test for a class whose annotations have been read already (dataclasses does).
            names = vars(obj)["__annotations_cache__"]
            if not any(text not in names for text in _string_constants(annotate)):
                return []
        return [text for text in get_annotations(obj, format = Format.STRING).values() if isinstance(text, str)]
    except Exception:
        return []


def _string_constants(annotate: Any) -> list[str]:
    """The string constants of a compiler-made annotate function (those folded into a tuple included)."""
    found: list[str] = []
    for constant in getattr(getattr(annotate, "__code__", None), "co_consts", ()):
        if isinstance(constant, str):
            found.append(constant)
        elif isinstance(constant, tuple):
            found += [item for item in constant if isinstance(item, str)]
    return found


def _resolver(fn: Any, owner: type | None) -> Callable[[str], Any]:
    """
    ``text -> object`` for a name that is still a string inside an annotation, as in the old way
    to write a recursive alias: ``Json = Union[int, List["Json"]]``. It is evaluated where the
    annotation was written: in the module of ``fn``, with its local names. Only ever given text
    from source code, never a string of a typecheck_record record.
    """
    namespaces: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    def resolve(text: str) -> Any:
        if not namespaces:                              # on first use: most annotations have no such name
            target = _unwrapped(fn)
            globalns = getattr(target, "__globals__", None)
            if globalns is None:
                module = sys.modules.get(getattr(target, "__module__", None) or "")
                globalns = vars(module) if module is not None else {}
            namespaces.append((globalns, _local_names(fn, owner)))
        return eval(text, *namespaces[0])
    return resolve


def _find_owner(fn: Any, args: tuple[Any, ...]) -> tuple[type, bool] | None:
    """
    The class that a function decorated on its own is a method of, and whether it was found
    through the first argument (``self`` or ``cls``). Without it ``Self`` and the type parameters
    of the class can't be resolved, and messages say ``<Function name>``. A class decorated with
    ``enforce`` tells its methods directly; this is for ``@typecheck`` on a method of any other.
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


#* The default of a keyword that ``**kwargs: Unpack[SomeTypedDict]`` makes optional: nothing was passed.
class _NotGiven:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<not given>"


_NOT_GIVEN: Any = _NotGiven()


def _typed_kwargs(record: dict[str, Any], sig: inspect.Signature) -> tuple[dict[str, Any], inspect.Signature]:
    """
    ``**kwargs: Unpack[Movie]`` says that the keywords are the keys of the TypedDict ``Movie``.
    Such a function is checked as if each key were a keyword-only parameter: the record gets one
    entry per key in place of the one for ``kwargs``, and the signature shows the same. Required
    keys, value types, conversion and unknown keywords then need nothing of their own.

    Both are returned and belong to the checker that asked. The function and its cached signature
    stay as they are, so another checker of the same function (``typecheck_record`` with a
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
        default = P.empty if key in required else _NOT_GIVEN
        try:
            parameters.append(P(key, P.KEYWORD_ONLY, annotation = annotation, default = default))
        except ValueError:
            parameters.append(_KeyParameter(key, default, annotation))
    return sig.replace(parameters = parameters)


def _unpacked_tuple(annotation: Any) -> Any:
    """The ``tuple[...]`` that ``*args: *tuple[...]`` (or ``Unpack[tuple[...]]``) unpacks; None for anything else."""
    if getattr(annotation, "__unpacked__", False) and get_origin(annotation) is tuple:
        return GenericAlias(tuple, get_args(annotation))        # tuple[int, str], made from its items
    if get_origin(annotation) is Unpack:
        inner = get_args(annotation)[0]
        if get_origin(inner) is tuple:
            return inner
    return None


def _args_node(annotation: Any, allow_subclass: bool, convert: bool, coerce: bool, deep: bool,
               resolve: "Callable[[str], Any] | None") -> Any:
    """
    The check for ``*args: *tuple[int, str]``: the extra positional arguments, as a tuple, against
    ``tuple[int, str]`` (how many, and each one's type). With a run of unknown length among them,
    ``*tuple[int, *tuple[str, ...]]``, the fixed ones at both ends and every argument between.
    The types are those of arguments, so they are checked whatever ``deep`` says; ``deep`` decides
    whether a collection among them has its items checked too. ``SLOW`` when one of them can't be
    resolved yet, ``None`` for a shape that isn't understood (left unchecked).
    """
    laid = _deep.spread(get_args(annotation))
    if laid is None:
        return None

    def leaf(item: Any) -> Any:
        spec: Any = _compile_spec(item, allow_subclass)
        if spec is SLOW:
            return SLOW
        return _deep.Leaf(item, spec, _predicate(spec), _compile_converter(item, allow_subclass, "?", convert, coerce))

    def node_for(item: Any) -> Any:
        node = _deep_node(item, allow_subclass, convert, coerce, resolve) if deep else None
        return leaf(item) if node is None else node

    before, middle, after = laid
    nodes = [node_for(item) for item in before + after]
    run = None if middle is _deep.FIXED else node_for(middle)
    if run is SLOW or any(node is SLOW for node in nodes):
        return SLOW
    if run is None:
        return _deep.FixedTuple(annotation, leaf(tuple), nodes)
    return _deep.VariadicTuple(annotation, leaf(tuple), nodes[:len(before)], run, nodes[len(before):])


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
        sig = _signature(fn)
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
    sig_params = (sig or _signature(origin_obj)).parameters
    for key, expected_type in record.items():
        if key == "return":
            continue
        value = arguments.get(key)
        param = sig_params.get(key)
        if param is not None and param.kind is inspect.Parameter.VAR_POSITIONAL:
            # *args: T — check each element against T individually
            for i, item in enumerate(value or ()):
                record_of_type_containers.append(TypeContainer(origin_obj, f"{key}[{i}]", item, expected_type))
        elif param is not None and param.kind is inspect.Parameter.VAR_KEYWORD:
            # **kwargs: T — check each value against T individually
            for k, v in (value or {}).items():
                record_of_type_containers.append(TypeContainer(origin_obj, f"{key}[{k}]", v, expected_type))
        else:
            record_of_type_containers.append(TypeContainer(origin_obj, key, value, expected_type))
    return record_of_type_containers


def _type_problem(container: TypeContainer, kind: str = "type", root: str | None = None,
                  allow_subclass: bool = True, convert: bool = False, coerce: bool = False) -> Problem:
    """
    A wrong-type problem; the message is rendered from the container only when needed.
    ``root`` is the parameter a deep check looked inside (``e`` for the item ``e[2]``).
    When the type is right but the value isn't (an ``Annotated`` check, or a TypeModel's
    ``validate``), the problem is ``"invalid"`` with the reason in ``detail``.
    """
    if container._key == "return":
        kind = "return"
    invalid = _invalid_reason(container, allow_subclass, convert, coerce)
    if invalid is not None:
        expected, reason = invalid
        problem = Problem("invalid", container._key, expected, container._input_object, container._origin_obj,
                          str, reason, container._annotation)
        problem._render = (_shape_message, kind == "default", root)
        return problem
    render = (partial(_parameter_type_error_msg_factory, container, kind == "default") if root is None
              else partial(_parameter_type_error_msg_factory, container, kind == "default", root))
    #* Positional on purpose: creating an instance with a keyword argument takes Python's slow route
    #* (+140 ns measured here, on a path that is slow enough).
    return Problem(kind, container._key, container._expected_type, container._input_object, container._origin_obj, render,
                   None, container._annotation)


def _invalid_reason(container: TypeContainer, allow_subclass: bool, convert: bool, coerce: bool) -> "tuple[Any, str] | None":
    """
    ``(type, reason)`` when the value has the right type but is rejected by an ``Annotated``
    check, or (with ``convert``/``coerce``) by a TypeModel's ``validate``; ``None`` otherwise.
    """
    value = container._input_object
    if container._constraints is not None:
        candidates = [value]
        typed = any(matches_type(value, target, allow_subclass) for target, _ in container._constraints)
        if (convert or coerce) and not typed:           # 3 for Annotated[float, check] is checked as 3.0
            for target, _ in container._constraints:
                targets = tuple(target) if isinstance(target, TypeUnion) else (target,)

                def accepts(v: Any, member: Any = target) -> bool:
                    return matches_type(v, member, allow_subclass)
                conv = build_converter(targets, convert, coerce, accepts)
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
                except Exception:
                    continue
                if reason is not None:
                    return target, reason
    return None


def _missing_msg(fn: Callable[..., Any], missing: tuple[str, ...], record: dict[str, Any], inferred: bool) -> str:
    names = ", ".join(
        f"{formatter(m, 'bold_green')} (expecting type {formatter(_format_annotation(record[m]), 'bold_yellow')})"
        if m in record else formatter(m, 'bold_green')
        for m in missing
        )
    noun = "argument" if len(missing) == 1 else "arguments"
    hint = " (inferred)" if inferred else ""
    return f"Missing required {noun} for {describe_origin(fn)}: {names}{hint}"


def _parameter_type_error_msg_factory(container: TypeContainer, is_default: bool = False,
                                      root: str | None = None) -> ErrorMessage:
    special = container._literal_values is not None or container._type_arg is not None
    exp_tp = formatter(_annotation_text(container._annotation) if special else type_name(container._expected_type), 'bold_yellow')
    actual_tp = formatter(type_name(type(container._input_object)), 'bold_red')
    prefix = _subject(container._key, is_default, root)
    value = formatter(short_repr(container._input_object), 'bold_red')
    return f"{prefix} of {container._formatter_origin_obj}: expected type: {exp_tp}, got type {actual_tp} (Value: {value})"


def expected_text(expected: Any, annotation: Any = None) -> str:
    """
    What a message shows after "expected type". Usually the runtime type the annotation comes down to
    (``'int'``, ``'int' | 'str'``). For Literal values and ``type[X]`` that type says nothing, and can
    even equal the type of the rejected value (``expected type: 'str', got type 'str'`` for
    ``Literal['r', 'w']`` given ``'x'``): there the annotation itself is shown.
    """
    if annotation is not None:
        try:
            container = TypeContainer(None, "?", None, annotation)
            special = container._literal_values is not None or container._type_arg is not None
        except Exception:
            special = False
        if special:
            return _annotation_text(annotation)
    return type_name(expected)


def _annotation_text(annotation: Any) -> str:
    """An annotation as a message shows it in place of a type: ``Literal['r', 'w']``, ``'type[int]'``."""
    while getattr(annotation, "__value__", None) is not None:      # type Mode = Literal['r', 'w']
        annotation = annotation.__value__
    text = _shortened(_format_annotation(annotation))
    return text if "'" in text or '"' in text else f"'{text}'"


#* An annotation is shown as it is written, and a union of long names has no end: the first 80
#* characters say which one is meant.
_ANNOTATION_LIMIT = 80


def _shortened(text: str) -> str:
    return text if len(text) <= _ANNOTATION_LIMIT else text[:_ANNOTATION_LIMIT - 3] + "..."


def _typechecker_type_error_factory(problems: "list[Problem]", context: str = "call") -> TypeCheckerError:
    assert len(problems) > 0, "No problems provided"
    return TypeCheckerError(problems = problems, context = context)


class _Shown:
    """Displays as the given text (a check inside a displayed ``Annotated``)."""
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _for_display(annotation: Any) -> Any:
    """
    ``annotation`` as messages show it: ``Annotated[int, "doc"]`` as ``int`` (metadata that
    isn't a check changes nothing), and ``Annotated[int, lambda x: x > 0]`` as ``Annotated[int, x > 0]``.
    """
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        inner = _for_display(args[0])
        checks = [_Shown(describe_check(check)) for check in metadata_checks(args[1:])]
        return Annotated[inner, *checks] if checks else inner
    if not args:
        return annotation
    shown = tuple(_for_display(a) for a in args)
    if all(a is b for a, b in zip(shown, args)):
        return annotation
    try:
        if isinstance(annotation, UnionType) or origin is Union:
            return reduce(or_, shown)
        return origin[shown if len(shown) != 1 else shown[0]] if origin is not None else annotation
    except Exception:
        return annotation


def _quoted(annotation: Any) -> str:
    """``'Email'``, or ``'int' | 'str'`` for a union (as wrong-type messages show types)."""
    return str(annotation) if isinstance(annotation, TypeUnion) else f"'{_format_annotation(annotation)}'"


def _format_annotation(annotation: Any) -> str:
    """Render an annotation for display, e.g. int, list[int], int | float."""
    if annotation is None or annotation is type(None):
        return "None"
    if "Annotated[" in str(annotation):
        annotation = _for_display(annotation)
    if isinstance(annotation, type) and not get_args(annotation):
        return annotation.__name__
    text = str(annotation).replace("typing.", "")
    return _starred(text) if "Unpack[" in text else text


def _starred(text: str) -> str:
    """``tuple[int, Unpack[tuple[str, ...]]]`` as it is written today: ``tuple[int, *tuple[str, ...]]``."""
    while (start := text.find("Unpack[")) >= 0:
        depth, end = 0, start + 6
        for end in range(start + 6, len(text)):
            depth += (text[end] == "[") - (text[end] == "]")
            if depth == 0:
                break
        text = f"{text[:start]}*{text[start + 7:end]}{text[end + 1:]}"
    return text


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


def _forget_signature(fn: Any) -> None:
    """The cached signature of ``fn`` no longer holds (its defaults were rewritten)."""
    if type(fn) is FunctionType:
        fn.__dict__.pop(_SIGNATURE, None)
    else:
        _SIGNATURES.pop(fn, None)


def _signature(fn: Callable[..., Any]) -> inspect.Signature:
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
        raise TypeCheckerError(
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
