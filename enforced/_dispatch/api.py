"""
The public functions: `dispatch` (a function that chooses a version of itself by the type of
its first argument, as `functools.singledispatch` does, with every annotation enforced checks)
and `dispatchmethod` (the same for a method). See `PLAN_dispatch.md`.
"""
from .._validator._class_rules import SKIP
from .._validator._lifetime import frame_above
from .._validator._scope import remember_scope
from .._validator._errors import (
    InvalidDataError,
    InvalidDataWarning,
    WarnAs,
    check_error_type,
    warns
    )
from ._candidates import Dispatcher, _NOT_ANNOTATED
from ._errors import refuse_node
from functools import update_wrapper
from types import CodeType, FunctionType
from typing import (
    Any,
    Callable,
    Concatenate,
    Literal,
    Protocol,
    overload,
    )
import inspect


class _Function(Protocol):
    """A function to a type checker: it has code (a class, `list[int]` or `int | None` has none)."""
    __code__: CodeType

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


class DispatchFunction[**P, R](Protocol):
    """What `dispatch` returns, to a type checker: the base's signature, and `register`."""

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...

    @overload
    def register[F: _Function](self, fn: F, /) -> F: ...
    @overload
    def register[F: Callable[..., Any]](self, annotation: Any, /) -> Callable[[F], F]: ...
    @overload
    def register[F: Callable[..., Any]](self, annotation: Any, fn: F, /) -> F: ...

    def registry(self) -> tuple[tuple[Any, Callable[..., Any]], ...]: ...
    def dispatch(self, value: Any) -> Callable[..., Any]: ...


@overload
def dispatch[**P, R](
    fn: Callable[P, R], *,
    allow_subclass: bool = ...,
    convert: bool = ...,
    check_return: bool = ...,
    on_error: Literal["raise", "warn"] = ...,
    error: type[InvalidDataError] = ...,
    warning: type[InvalidDataWarning] = ...,
    ) -> DispatchFunction[P, R]: ...
@overload
def dispatch[**P, R](
    fn: None = ..., *,
    allow_subclass: bool = ...,
    convert: bool = ...,
    check_return: bool = ...,
    on_error: Literal["raise", "warn"] = ...,
    error: type[InvalidDataError] = ...,
    warning: type[InvalidDataWarning] = ...,
    ) -> Callable[[Callable[P, R]], DispatchFunction[P, R]]: ...
def dispatch(
    fn: Callable[..., Any] | None = None,
    *,
    allow_subclass: bool = True,
    convert: bool = True,
    check_return: bool = False,
    on_error: Literal["raise", "warn"] = "raise",
    error: type[InvalidDataError] = InvalidDataError,
    warning: type[InvalidDataWarning] = InvalidDataWarning,
    ) -> Any:
    """
    Make `fn` the base of a function that chooses a version of itself by its first argument type, the
    *anchor*:

    Implements the behaviour of  `functools.singledispatch` with every type annotation validated via enforcelib.

    Register each version with `@fn.register`: its first parameter's annotation is what it matches on.
    A call goes to the first version, in the order they were registered.

    A value that no candidate takes raises an error with each candidate's reason. A version that can
    never be chosen (what it takes is all taken before it) is refused where it is registered.

    Args:
        fn (Callable): The base function.
        allow_subclass (bool): As for `validate`: an instance of a subclass is taken (default).
        convert (bool): Convert the *other* parameters of the chosen version, as `validate` does.
        check_return (bool): Check what the chosen version returns.
        on_error (str): `"warn"`: a wrong *other* parameter is a warning. A value that no
            version takes is raised all the same: there is nothing to call.
        error (type): The class of what a call raises (a subclass of `InvalidDataError`).
        warning (type): The class `on_error = "warn"` issues (a subclass of `InvalidDataWarning`).

    This decorator allows you for the implementation of functional strategy pattern, based on the type of the first argument.
    Each registered version is a different branch of the strategy.

    Example:

        >>> from enforced import dispatch, Check
        ...
        ... @dispatch
        ... def render(node) -> str:
        ...     raise TypeError("Unsupported node type")
        ...
        ... @render.register
        ... def _(node: float) -> str: ...
        ...
        ... @render.register
        ... def _(node: list[int]) -> str: ...
        ...
        ... @render.register
        ... def _(node: Annotated[int, Check(lambda number: number < 0)]) -> str: ...
        ...
        ... @render.register
        ... def _(node: Annotated[int, Check(lambda number: number >= 0)]) -> str: ...
        ...
        ... render(3.14)        # goes to float node
        ... render([1, 2, 3])   # goes to list[int] node
        ... render(-5)          # goes to first Annotated node
        ... render(5)           # goes to second Annotated node
    """
    if error is not InvalidDataError:
        check_error_type(error)
    warn = warns(on_error, warning)
    if fn is None:
        def decorate(fn: Callable[..., Any]) -> Any:
            return _make_dispatched_func(fn, allow_subclass, convert, check_return, warn, error, frame_above())
        return decorate
    return _make_dispatched_func(fn, allow_subclass, convert, check_return, warn, error, frame_above())


def _make_dispatched_func(
    fn: Any,
    allow_subclass: bool,
    convert: bool,
    check_return: bool,
    warn: WarnAs,
    error: "type[InvalidDataError]",
    frame: Any
    ) -> Any:
    """
    Create a dispatcher for the given function with the specified options.

    Args:
        fn: The function to dispatch.
        allow_subclass (bool): Whether to allow subclass instances.
        convert (bool): Whether to convert other parameters.
        check_return (bool): Whether to check the return value.
        warn (bool): Whether to warn on errors.
        error (type): The error class to use.
        frame: The frame above for context.

    Returns:
        A dispatched function.
    """

    if not inspect.isfunction(fn):
        raise InvalidDataError(
            f"dispatch decorates a function, got {type(fn).__name__}" + (": use dispatchmethod in a class" if isinstance(fn, (classmethod, staticmethod)) else "")
            )
    _remember(fn, frame)
    state = Dispatcher(fn, 0, allow_subclass, check_return, convert, warn, error)
    choose, no_anchor = state.choose, state.no_anchor

    def dispatcher(*args: Any, **kwargs: Any) -> Any:
        if not args:
            raise no_anchor(kwargs)
        #* The common case first, written out (a call less): a class answered from the cache, no
        #* ABC token to compare, and the value passed on as it came.
        table = state.table
        if table is not None and table[2] is None:
            cls = type(args[0])
            entry = table[1].get(id(cls))
            if entry is not None and entry[2] and entry[0]() is cls:
                return table[0][entry[1]].call(*args, **kwargs)
        candidate, value = choose(args[0])
        return candidate.call(value, *args[1:], **kwargs)

    def register(what: Any, version: Any = _NOT_ANNOTATED) -> Any:
        frame = frame_above()
        if version is not _NOT_ANNOTATED:               # register(list[int], fn)
            _remember(version, frame)
            state.register(version, what)
            return version
        if inspect.isfunction(what):                    # @register
            _remember(what, frame)
            state.register(what)
            return what

        def with_annotation(version: Any) -> Any:       # @register(list[int])
            _remember(version, frame)
            state.register(version, what)
            return version
        return with_annotation

    def chosen(value: Any) -> Callable[..., Any]:
        """The version that would take `value` (the function as it was written), or the error."""
        return choose(value)[0].fn

    #* Update the wrapper to look like the original function, and attach dispatch-related attributes.
    update_wrapper(dispatcher, fn)
    dispatcher.register = register                      # type: ignore[attr-defined]
    dispatcher.registry = state.registry                # type: ignore[attr-defined]
    dispatcher.dispatch = chosen                        # type: ignore[attr-defined]
    dispatcher.__enforced_dispatch__ = state            # type: ignore[attr-defined]
    #* `enforce` and `dataclass` leave it alone: its versions are checked already, and wrapped
    #* with the base's annotations it would check the anchor as the base's.
    setattr(dispatcher, SKIP, True)

    return dispatcher


def _remember(fn: Any, frame: Any) -> None:
    """A version written in a function: the local names its string annotations use (see `remember_scope`)."""
    inner = getattr(fn, "__func__", fn)
    if type(inner) is FunctionType and "<locals>" in inner.__qualname__ and frame is not None:
        remember_scope(inner, frame)
    return


# ── methods ──────────────────────────────────────────────────────────────────

def _kind_of(member: Any) -> tuple[Callable[..., Any], Any, int]:
    """A method's `(function, rebuild, parameters before the anchor)`: self / cls is skipped, not a static method's."""
    if isinstance(member, staticmethod):
        return member.__func__, staticmethod, 0
    if isinstance(member, classmethod):
        return member.__func__, classmethod, 1
    return member, None, 1


class _NoSelf:
    """To a type checker, `S` of a `dispatchmethod` whose base is a class or static method: nothing to bind by hand."""


class dispatchmethod[S, **P, R]:
    """
    `dispatch` for a method: the anchor is the first parameter after `self` (or `cls`; a
    static method's first). The base and each version may be a function, a `classmethod` or a
    `staticmethod`, as with `functools.singledispatchmethod`:

        >>> class Shapes:
        ...     @dispatchmethod
        ...     def area(self, shape) -> float:
        ...         raise NotImplementedError
        ...
        ...     @dispatchmethod
        ...     def volume(self, shape) -> float:
        ...         raise NotImplementedError
        ...
        ...     @area.register
        ...     def _(self, shape: Circle) -> float: ...
        ...
        ...     @area.register
        ...     def _(self, shape: Square) -> float: ...
        ...
        ...     @volume.register
        ...     def _(self, shape: Cube) -> float: ...
        ...
        ...     @volume.register
        ...     def _(self, shape: Sphere) -> float: ...

    To a type checker a call has the base's signature: `S` is the type of `self`, `P` the
    parameters after it, `R` what it returns. mypy and pyright both see a `@staticmethod` under this
    decorator as a plain function, and take its first parameter for `self`: they report a valid call
    through an instance. `plain = dispatchmethod(staticmethod(fn))` is typed correctly.
    """
    @overload
    def __init__[**P2, R2](
        self: "dispatchmethod[_NoSelf, P2, R2]",
        fn: "staticmethod[P2, R2]", /, *,
        allow_subclass: bool = ..., convert: bool = ..., check_return: bool = ...,
        on_error: Literal["raise", "warn"] = ..., error: type[InvalidDataError] = ...,
        warning: type[InvalidDataWarning] = ...
        ) -> None: ...
    @overload
    def __init__[**P2, R2](
        self: "dispatchmethod[_NoSelf, P2, R2]",
        fn: "classmethod[Any, P2, R2]", /, *,
        allow_subclass: bool = ..., convert: bool = ..., check_return: bool = ...,
        on_error: Literal["raise", "warn"] = ..., error: type[InvalidDataError] = ...,
        warning: type[InvalidDataWarning] = ...
        ) -> None: ...
    @overload
    def __init__(
        self, fn: Callable[Concatenate[S, P], R], /, *, allow_subclass: bool = ...,
        convert: bool = ..., check_return: bool = ..., on_error: Literal["raise", "warn"] = ...,
        error: type[InvalidDataError] = ..., warning: type[InvalidDataWarning] = ...
        ) -> None: ...
    @overload
    def __init__(
        self: "dispatchmethod[Any, ..., Any]",
        fn: None = ..., /, *,
        allow_subclass: bool = ..., convert: bool = ...,
        check_return: bool = ..., on_error: Literal["raise", "warn"] = ...,
        error: type[InvalidDataError] = ..., warning: type[InvalidDataWarning] = ...
        ) -> None: ...
    def __init__(
        self, fn: Any = None, /,
        *,
        allow_subclass: bool = True,
        convert: bool = True,
        check_return: bool = False,
        on_error: Literal["raise", "warn"] = "raise",
        error: type[InvalidDataError] = InvalidDataError,
        warning: type[InvalidDataWarning] = InvalidDataWarning,
        ) -> None:

        if error is not InvalidDataError:
            check_error_type(error)
        self._options = (allow_subclass, convert, check_return, warns(on_error, warning), error)
        self._state: Dispatcher | None = None
        self._frame = frame_above()
        if fn is not None:
            self._take(fn)

        return

    @overload
    def __call__[**P2, R2](self, fn: "staticmethod[P2, R2]", /) -> "dispatchmethod[_NoSelf, P2, R2]": ...
    @overload
    def __call__[**P2, R2](self, fn: "classmethod[Any, P2, R2]", /) -> "dispatchmethod[_NoSelf, P2, R2]": ...
    @overload
    def __call__[S2, **P2, R2](self, fn: Callable[Concatenate[S2, P2], R2], /) -> "dispatchmethod[S2, P2, R2]": ...
    def __call__(self, fn: Any, /) -> Any:
        """`@dispatchmethod(...)`: the options first, then the base."""
        if self._state is not None:
            raise refuse_node(self._state.base, "a dispatchmethod is called through its instance or class")
        self._take(fn)
        return self

    def _take(self, member: Any) -> None:
        function = _kind_of(member)[0]
        if not inspect.isfunction(function):
            raise InvalidDataError(f"dispatchmethod decorates a function, a classmethod or a staticmethod, got {type(member).__name__}")
        _remember(function, self._frame)
        allow_subclass, convert, check_return, warn, error = self._options
        self._state = Dispatcher(member, 1, allow_subclass, check_return, convert, warn, error, _kind_of)
        self.__wrapped__ = function
        self.__doc__ = function.__doc__
        setattr(self, SKIP, True)
        return

    @property
    def _known(self) -> Dispatcher:
        if self._state is None:
            raise InvalidDataError("dispatchmethod(...) has no base function yet")
        return self._state

    @overload
    def register[F: _Function](self, fn: F, /) -> F: ...
    @overload
    def register[**P2, R2](self, fn: "staticmethod[P2, R2]", /) -> "staticmethod[P2, R2]": ...  # pyright: ignore[reportOverlappingOverload]
    @overload
    def register[T, **P2, R2](self, fn: "classmethod[T, P2, R2]", /) -> "classmethod[T, P2, R2]": ...
    @overload
    def register[F](self, annotation: Any, /) -> Callable[[F], F]: ...
    @overload
    def register[F](self, annotation: Any, fn: F, /) -> F: ...
    def register(self, what: Any, version: Any = _NOT_ANNOTATED, /) -> Any:
        """As `dispatch`'s `register`: `@m.register`, `@m.register(list[int])`, `m.register(list[int], fn)`."""
        state, frame = self._known, frame_above()
        if version is not _NOT_ANNOTATED:
            _remember(version, frame)
            state.register(version, what)
            return version
        if inspect.isfunction(_kind_of(what)[0]):
            _remember(what, frame)
            state.register(what)
            return what

        def with_annotation(version: Any) -> Any:
            _remember(version, frame)
            state.register(version, what)
            return version
        return with_annotation

    def registry(self) -> tuple[tuple[Any, Callable[..., Any]], ...]:
        return self._known.registry()

    def dispatch(self, value: Any) -> Callable[..., Any]:
        return self._known.choose(value)[0].fn

    @overload
    def __get__(self: "dispatchmethod[_NoSelf, P, R]", obj: Any, cls: Any = ..., /) -> Callable[P, R]: ...
    @overload
    def __get__(self: "dispatchmethod[type[Any], P, R]", obj: Any, cls: Any = ..., /) -> Callable[P, R]: ...
    @overload
    def __get__(self, obj: None, cls: Any, /) -> Callable[Concatenate[S, P], R]: ...
    @overload
    def __get__(self, obj: S, cls: Any = ..., /) -> Callable[P, R]: ...
    def __get__(self, obj: Any, cls: Any = None, /) -> Any:
        state = self._known
        if obj is None and _kind_of(state.base_candidate.member)[1] is None:
            return _Unbound(state, cls)                 # Shapes.area(shapes, 3): the instance comes first
        return _Bound(state, obj, cls if cls is not None else type(obj))


class _Bound:
    """A `dispatchmethod` read through an instance or its class: the call binds the chosen version there."""
    __slots__ = ("_state", "_obj", "_cls")

    def __init__(self, state: Dispatcher, obj: Any, cls: Any) -> None:
        self._state, self._obj, self._cls = state, obj, cls
        return

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if not args:
            raise self._state.no_anchor(kwargs)
        candidate, value = self._state.choose(args[0])
        #* Called with what it binds, not through `__get__`: a bound method made per call costs more.
        binds = candidate.binds
        if binds == 0:
            return candidate.call(self._obj, value, *args[1:], **kwargs)
        if binds == 1:
            return candidate.call(self._cls, value, *args[1:], **kwargs)
        return candidate.call(value, *args[1:], **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._state.base_candidate.fn, name)

    def __repr__(self) -> str:
        return f"<dispatchmethod {self._state.base_candidate.fn.__qualname__} of {self._obj!r}>"


class _Unbound(_Bound):
    """A `dispatchmethod` of instances read through the class: the instance is the first argument, the anchor the second."""
    __slots__ = ()

    def __init__(self, state: Dispatcher, cls: Any) -> None:
        super().__init__(state, None, cls)
        return

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if len(args) < 2:
            raise self._state.no_anchor(kwargs)
        candidate, value = self._state.choose(args[1])
        return candidate.member.__get__(args[0], self._cls)(value, *args[2:], **kwargs)

    def __repr__(self) -> str:
        return f"<dispatchmethod {self._state.base_candidate.fn.__qualname__}>"
