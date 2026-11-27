"""From a function to its checked wrapper: the stub, the tiers, and other decorators' objects."""
from .. import _environment
from .._colours import formatter
from ._annotations import tag_owner
from ._checker import PreparedChecker
from ._codegen import BOOT_CODES, function_kind, generate_wrapper, PLAIN_CODES
from ._defaults import IN_PLACE
from ._errors import InvalidDataError, WarnAs
from ._general_path import make_fallback
from ._scope import remember_scope
from ._text import break_trace_colouring, describe_origin, made_dataclass, short_repr
from typing import Any, Callable, TYPE_CHECKING
from functools import cached_property, update_wrapper
from types import CodeType, FunctionType
import builtins
import inspect

if TYPE_CHECKING:
    from ._defaults import ExtraDefaults


def unchanged[X](obj: X) -> X:
    """What `@validate(...)` and `@enforce(...)` decorate with while every check is switched off."""
    return obj


def wrap_callable(
    fn: Callable[..., Any],
    allow_subclass: bool,
    check_return: bool,
    owner: type | None = None,
    skip_first: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    extra_defaults: "ExtraDefaults | None" = None,
    in_place: bool = False,
    me: type | None = None,
    family: "dict[int, Any] | None" = None,
    upgrade: "Callable[[], Callable[..., Any] | None] | None" = None,
    warn: WarnAs = False,
    error: "type[InvalidDataError]" = InvalidDataError,
    leave: "frozenset[str]" = frozenset(),
    ) -> Callable[..., Any]:
    """
    Wrap `fn` so inputs (and optionally the return value) are checked on every call.

    Decoration is cheap: it returns a tiny stub. The stub's first call runs the full
    checks and then replaces the stub's own `__code__` with source generated for this
    exact signature (see `generate_wrapper`), so later calls pay no indirection.
    If generation isn't possible yet (bad default, unresolved forward ref), the stub
    keeps using the general path and tries again on the next call.

    `mark` (used for a dataclass `__init__`) returns a namespace, or None. While `fn` runs,
    the checked arguments are published there as `_pv_init_args` / `_pv_init_kwargs`, so the class's
    `__setattr__` can tell which values need no second check (see `_dataclass._assignment`).
    `extra_defaults` lists the defaults `fn` doesn't take as parameters (see `check_defaults`).
    `in_place` says that `fn` is nobody else's (the `__init__` that `dataclasses` generated):
    a converted default is then written into it, where otherwise a copy of `fn` gets it.

    `me` and `family` are for a method whose annotations use `Self`. `Self` is the class of
    the instance the method is called on, and a check is compiled for one class. So such a method
    can have one wrapper for each class it is called on: this one, in which `Self` is `me` (the
    owner unless given), and those made for the other classes when a call arrives for them, kept
    in `family` (see `_route`). Nothing of this exists until such a call is made.

    `upgrade` is asked once, when the wrapper is about to be compiled: it returns a function to
    call in place of `fn` from then on, or `None`. A dataclass hands over its storing
    `__init__` this way, which costs a `compile` of its own and is only worth it for a class
    that is constructed often (see `_dataclass._init.storing_init`).

    `leave` names parameters that are not checked at all (the anchor of a version of
    `enforced.dispatch`, which the choice of the version has tested already).
    """
    #* typing.no_type_check asks for exactly this: the function stays the one that was written.
    #* (`is True`: an object that answers every attribute, a mock, is not thereby marked.)
    if "__no_type_check__" in fn.__dict__ if type(fn) is FunctionType else getattr(fn, "__no_type_check__", False) is True:
        return fn
    if owner is not None:
        tag_owner(fn, owner)

    checker = PreparedChecker(
        fn,
        allow_subclass,
        owner,
        skip_first,
        convert = convert,
        coerce = coerce,
        rewrite_defaults = IN_PLACE if in_place else True,
        deep = deep,
        extra_defaults = extra_defaults,
        me = me,
        family = family,
        warn = warn,
        error = error,
        leave = leave,
        )
    #* What kind of function `fn` is to `inspect`: the wrapper says the same of itself (see `_stub_codes`).
    kind = function_kind(fn)
    is_async = kind == inspect.CO_COROUTINE
    fallback = make_fallback(checker, check_return, is_async, mark)

    #* `_pv_checker` is not used by the wrapper: it is how `enforce` reaches the checker of a
    #* method that was decorated on its own (see `adopt`).
    ns: dict[str, Any] = {"__builtins__": builtins, "_pv_checker": checker}
    boot = BOOT_CODES[kind]
    stub = FunctionType(boot, ns, getattr(fn, "__name__", "wrapper"))

    #* Tiered compilation (see `_environment.COMPILE_AFTER`): the first calls take the general
    #* path, and the wrapper is compiled when the function has shown that it is called often.
    compile_after = _environment.COMPILE_AFTER
    calls = 0

    def install_compiled_wrapper() -> None:
        """Swap the stub's code for the generated wrapper, once the checker is ready (and only once)."""
        if checker.ready and stub.__code__ is boot:
            code, source = generate_wrapper(checker, check_return, is_async, ns, fallback, mark, kind)
            stub.__code__ = code
            stub.__enforced_source__ = source      # type: ignore[attr-defined]  # handy for debugging / introspection

    def improve(args: tuple[Any, ...]) -> None:
        #* After `_prepare`: what `upgrade` returns takes the defaults as the first call left them (converted).
        nonlocal upgrade
        if not checker.ready:
            checker._prepare(args)
        if checker.ready and upgrade is not None:
            better, upgrade = upgrade(), None
            if better is not None and checker.call is fn:
                checker.call = better                   # __wrapped__ stays `fn`: the origin of its problems

    #* `@no_type_check` written above `@validate` marks the wrapper, after it was made. That is
    #* seen on the first call: from then on the wrapper only passes the call on (`_unchecked`).
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
                install_compiled_wrapper()
        ns["_pv_bootstrap"] = async_bootstrap
    else:
        def bootstrap(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            nonlocal calls
            if calls == 0 and "__no_type_check__" in stub.__dict__:
                return _unchecked(stub, boot, ns, fn, kind)(*args, **kwargs)
            calls += 1
            if calls < compile_after:
                #* on_error = "warn" for a dataclass: its storing __init__ from the first
                #* construction. Behind the standard one a wrong argument is met twice (here, and
                #* when it is assigned), and would be reported twice until the wrapper is compiled.
                if warn and upgrade is not None:
                    improve(args)
                return fallback(args, kwargs)
            if upgrade is not None:
                improve(args)
            try:
                return fallback(args, kwargs)
            finally:
                install_compiled_wrapper()
        ns["_pv_bootstrap"] = bootstrap

    return update_wrapper(stub, fn)


def _unchecked(stub: Any, boot: CodeType, ns: dict[str, Any], fn: Any, kind: int) -> Any:
    """Turn a wrapper that carries `typing.no_type_check` into one that only passes its call on to `fn`, which is returned."""
    if stub.__code__ is boot:
        ns["_pv_function"] = fn
        stub.__code__ = PLAIN_CODES[kind]
    return fn


def dispatcher_refused(obj: Any) -> InvalidDataError:
    """
    `validate` on a dispatcher (`enforced.dispatch`): its versions are checked already, and wrapped
    with the base's annotations the anchor would be checked against the base's before any version is chosen.
    """
    name = getattr(obj, "__qualname__", None) or getattr(getattr(obj, "__wrapped__", None), "__qualname__", "?")
    return InvalidDataError(
        break_trace_colouring + f"validate cannot check the dispatcher {formatter(name, 'bold_red')}: its versions "
        f"are checked already. {formatter('Give dispatch its options instead: @dispatch(check_return = True)', 'bold_yellow')}"
        )


def wrap_member(obj: Any, allow_subclass: bool, check_return: bool, convert: bool, coerce: bool, deep: bool,
                frame: Any = None, warn: WarnAs = False, error: "type[InvalidDataError]" = InvalidDataError) -> Any:
    """
    `@validate` on anything that isn't a plain function. Written above `@classmethod`,
    `@staticmethod`, `@property` or `@cached_property` it receives that decorator's object, not
    a function: the function inside is checked and the object built again around it, so the attribute
    stays a class method (a property, ...). A class, and anything else that can't be called, is
    refused here, at the definition. `frame` is where the decorator was written (see `remember_scope`).
    """
    if getattr(obj, "__enforced_dispatch__", None) is not None or type(obj).__name__ == "dispatchmethod" \
            and type(obj).__module__ == "enforced._dispatch.api":
        raise dispatcher_refused(obj)
    if isinstance(obj, type):
        instead = "A dataclass is checked by enforced.dataclass" if made_dataclass(obj) else "A class is checked by @enforce"
        raise InvalidDataError(
            break_trace_colouring + f"validate cannot check {describe_origin(obj)}: "
            f"it checks functions and methods. {formatter(instead, 'bold_yellow')}"
            )

    def checked(fn: Any, skip_first: bool) -> Any:
        if fn is None or _is_checked(fn):               # no such accessor, or one decorated on its own
            return fn
        if not callable(fn) or isinstance(fn, type):   # nothing to check, or a class: refused like any other
            return wrap_member(fn, allow_subclass, check_return, convert, coerce, deep, frame, warn, error)
        if frame is not None and type(fn) is FunctionType and "<locals>" in fn.__qualname__:
            remember_scope(fn, frame)
        return wrap_callable(
            fn,
            allow_subclass, check_return,
            skip_first = skip_first,
            convert = convert,
            coerce = coerce,
            deep = deep,
            warn = warn,
            error = error
            )

    match obj:
        case classmethod() | staticmethod():
            return type(obj)(checked(obj.__func__, isinstance(obj, classmethod)))
        case property():
            return type(obj)(checked(obj.fget, True), checked(obj.fset, True), checked(obj.fdel, True), obj.__doc__)
        case cached_property():
            return type(obj)(checked(obj.func, True))
        case _:
            if not callable(obj):
                raise InvalidDataError(
                    break_trace_colouring + f"validate cannot check {formatter(short_repr(obj, 60), 'bold_red')}: "
                    f"a {formatter(type(obj).__name__, 'bold_yellow')} object is not callable. "
                    f"Put @validate directly above the function, below the other decorators"
                    )
            return wrap_callable(
                obj,
                allow_subclass,
                check_return,
                convert = convert,
                coerce = coerce,
                deep = deep,
                warn = warn,
                error = error
                )


def _is_checked(fn: Any) -> bool:
    """Whether `fn` is a wrapper made by `wrap_callable` (so it isn't wrapped a second time)."""
    return isinstance(fn, FunctionType) and "_pv_bootstrap" in fn.__globals__


def checked_inside(fn: Callable[..., Any]) -> Callable[..., Any] | None:
    """
    The wrapper made by `wrap_callable` that `fn` is, or that it wraps: a method with
    `@validate` below another decorator that uses `functools.wraps`. `None` without one.
    """
    try:
        inner = inspect.unwrap(fn, stop = _is_checked)
    except ValueError:                                  # a __wrapped__ chain that loops
        return None
    return inner if _is_checked(inner) else None
