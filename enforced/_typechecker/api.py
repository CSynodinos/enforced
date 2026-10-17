"""
The public API: typecheck, enforce, the Enforced base class, and the same without decorators
(typecheck_function, enforce_class, typecheck_record).
"""
from .. import _environment
from .._formatting_tool import formatter
from ._class_rules import BASE_OPTIONS, SKIP, enforce_members
from ._errors import TypeCheckerError, warns
from ._lifetime import frame_above
from . import _remembered
from ._remembered import (
    NOTHING_KEPT,
    RECORDS,
    CALLS,
    call_wrapper,
    new_record_checker,
    union_order
    )
from ._scope import remember_scope
from ._text import break_trace_colouring, describe_origin, made_dataclass, short_repr
from ._wrapping import unchanged, wrap_callable, wrap_member
from typing import (
    Any,
    Callable,
    Literal,
    NotRequired,
    Required,
    TypedDict,
    overload
    )
from collections.abc import Mapping
from functools import cached_property, partial
from types import FunctionType, MethodType


@overload
def typecheck[F: Callable[..., Any]](
    obj: F, allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ..., *, on_error: Literal["raise", "warn"] = ...,
    ) -> F: ...
@overload
def typecheck[F: Callable[..., Any]](
    obj: None = ..., allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
    deep: bool = ..., *, on_error: Literal["raise", "warn"] = ...,
    ) -> Callable[[F], F]: ...
def typecheck(
    obj: Callable[..., Any] | None = None,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    *,
    on_error: Literal["raise", "warn"] = "raise",
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
        on_error (str): ``"raise"`` (default): a value that fails raises a ``TypeCheckerError``.
            ``"warn"``: the same message is issued as a ``TypeCheckerWarning`` and the call goes
            ahead, with the value as it was given (what could be converted still is). For
            finding out what would fail in code that already runs, before making it an error.
            Python shows a warning once for each line it comes from. Two things are raised all
            the same: a call that can't be made (a missing argument, one too many) and a mistake
            in the definition (a default that contradicts its annotation).

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
        return unchanged if obj is None else obj
    if obj is None:
        warns(on_error)                                 # a wrong value is refused where it is written
        return partial(
            typecheck,
            allow_subclass = allow_subclass,
            check_return = check_return,
            convert = convert,
            coerce = coerce,
            deep = deep,
            on_error = on_error,
            )
    else:
        #* Function: the usual case, tested first so that decorating one costs no more than it did.
        if type(obj) is FunctionType:
            if "<locals>" in obj.__qualname__:          # defined inside a function: see remember_scope
                remember_scope(obj, frame_above())
            return wrap_callable(obj, allow_subclass, check_return, convert = convert, coerce = coerce, deep = deep,
                                 warn = on_error != "raise" and warns(on_error))
        #* Another callable, or what a decorator such as @classmethod made of a function.
        else:
            return wrap_member(obj, allow_subclass, check_return, convert, coerce, deep, frame_above(), warns(on_error))


class _Enforce:
    "Enforce the type annotations of a class"

    #* An object, not a function, so that ``@enforce.exempt`` is known to mypy and pyright as well
    #* (an attribute set on a function is not). There is one, ``enforce``.
    __slots__ = ()

    @overload
    def __call__[T: type](
        self, obj: T, allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
        deep: bool = ..., *, on_error: Literal["raise", "warn"] = ...,
        ) -> T: ...
    @overload
    def __call__[T: type](
        self, obj: None = ..., allow_subclass: bool = ..., check_return: bool = ..., convert: bool = ..., coerce: bool = ...,
        deep: bool = ..., *, on_error: Literal["raise", "warn"] = ...,
        ) -> Callable[[T], T]: ...
    def __call__(
        self,
        obj: type | None = None,
        allow_subclass: bool = True,
        check_return: bool = False,
        convert: bool = True,
        coerce: bool = False,
        deep: bool = False,
        *,
        on_error: Literal["raise", "warn"] = "raise",
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

        - is marked with ``@enforce.exempt``: it isn't checked at all;
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
            on_error (str): ``"raise"`` (default) or ``"warn"``: a value that fails is reported as a
                ``TypeCheckerWarning`` and the call goes ahead.

        The options mean what they mean for ``typecheck``, whose docstring has the details.

        Returns:
            The same class, its methods wrapped with runtime type validation.

        Example:

            >>> from enforced import enforce
            ... @enforce
            ... class Point:
            ...    def __init__(self, x: float, y: float) -> None:
            ...        self.x = x
            ...        self.y = y
            ...        return
            ...
            ...    def moved(self, dx: float, dy: float) -> "Point":
            ...        return Point(self.x + dx, self.y + dy)
            ...
            ...    @enforce.exempt
            ...    def debug(self, sink) -> None:
            ...        print(self.x, self.y, file = sink)
            ...        return
        """
        if _environment.TYPECHECK_OFF:                      # ENFORCED_TYPECHECK_OFF=1: the class stays as it was written
            return unchanged if obj is None else obj
        warn = warns(on_error)
        if obj is None:
            return partial(enforce, allow_subclass = allow_subclass, check_return = check_return,
                           convert = convert, coerce = coerce, deep = deep, on_error = on_error)

        if not isinstance(obj, type):
            shown = describe_origin(obj) if callable(obj) else formatter(short_repr(obj, 60), "bold_red")
            raise TypeCheckerError(
                break_trace_colouring + f"enforce cannot check {shown}: it checks classes. "
                + formatter("A function or a method is checked by @typecheck", "bold_yellow")
                )
        #* Only a class that was made a dataclass itself: a plain subclass of one is a plain class.
        if made_dataclass(obj):
            raise TypeCheckerError(
                break_trace_colouring + f"enforce cannot check {describe_origin(obj)}: it checks plain classes. "
                + formatter("A dataclass is checked by enforced.dataclass, its methods included", "bold_yellow")
                )
        if getattr(obj, BASE_OPTIONS, None) is not None:
            raise TypeCheckerError(
                break_trace_colouring + f"enforce cannot check {describe_origin(obj)}: it inherits from Enforced, which "
                "checks it already. " + formatter("Give the options as class keywords: class X(Enforced, coerce=True)", "bold_yellow")
                )
        if "<locals>" in obj.__qualname__:                  # a class defined inside a function: see remember_scope
            remember_scope(obj, frame_above())

        enforce_members(obj, allow_subclass, check_return, convert, coerce, deep, warn)
        return obj

    @staticmethod
    def exempt[M](member: M) -> M:
        """
        Mark a method of an ``enforce`` class or an ``enforced.dataclass`` as not to be checked:
        the class decorator leaves it exactly as it is, so calling it costs nothing extra.

        It can be written above or below ``@classmethod``, ``@staticmethod`` and ``@property``,
        and returns what it was given. It only speaks to the class decorators: an explicit
        ``@typecheck`` on the same method still checks it.

            @enforce
            class Report:
                def add(self, line: str) -> None: ...          # checked

                @enforce.exempt
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
                    setattr(target, SKIP, True)
                except (AttributeError, TypeError):         # an object that takes no attributes
                    pass
        return member

    def __repr__(self) -> str:
        return "<decorator enforced.enforce>"

    def __reduce__(self) -> str:
        return "enforce"                                # pickled by name: there is one


_Enforce.__call__.__doc__ = _Enforce.__doc__            # what an editor shows over @enforce
enforce = _Enforce()


#* What a class that inherits from Enforced is checked with when neither it nor a base says otherwise.
_BASE_DEFAULTS: tuple[Any, ...] = (True, False, True, False, False, "raise")


class Enforced:
    """
    A base class that enforces the type annotations of every class derived from it, as ``@enforce``
    does for one: ``__init__``, the methods, static methods, class methods and properties each
    subclass defines, and the special methods a caller hands values to. A subclass of a subclass is
    checked too, without a decorator: a library can hand this behaviour on to classes it never sees.

    The options are those of ``enforce``, given as class keywords. A class that names none takes
    those of its nearest base that does; each one it names replaces that one alone::

        class Account(Enforced, check_return=True):
            def deposit(self, amount: float) -> float: ...

        class Savings(Account):                     # checked, with check_return=True
            def withdraw(self, amount: float) -> float: ...

        class Lenient(Account, coerce=True):        # check_return=True as well, and coerce=True
            ...

    ``@enforce.exempt`` leaves a method alone, a method with its own ``@typecheck`` keeps its own
    options, and ``typing.no_type_check`` on a class leaves that class unchecked, as under ``enforce``.
    It adds no instance attribute (``__slots__ = ()``) and no metaclass, so it combines with any other
    base class. Keyword arguments it doesn't know are passed on to the next ``__init_subclass__``.

    For plain classes: ``enforce`` and ``enforced.dataclass`` refuse a class derived from it.

    Args:
        allow_subclass (bool): See ``typecheck``. Default ``True``.
        check_return (bool): Also check what each method returns. Default ``False``.
        convert (bool): Lossless conversion (``1`` -> ``1.0``). Default ``True``.
        coerce (bool): Also parse values (``"42"`` -> ``42``). Default ``False``.
        deep (bool): Also check the items inside collections. Default ``False``.
        on_error (str): ``"raise"`` (default) or ``"warn"``.
    """
    __slots__ = ()

    def __init_subclass__(
        cls,
        *,
        allow_subclass: bool | None = None,
        check_return: bool | None = None,
        convert: bool | None = None,
        coerce: bool | None = None,
        deep: bool | None = None,
        on_error: Literal["raise", "warn"] | None = None,
        **kwargs: Any,
        ) -> None:
        super().__init_subclass__(**kwargs)
        given = (allow_subclass, check_return, convert, coerce, deep, on_error)
        inherited = getattr(cls, BASE_OPTIONS, _BASE_DEFAULTS)
        options = tuple(base if mine is None else mine for mine, base in zip(given, inherited))
        warn = warns(options[5])                            # an unknown on_error is refused here, at the class
        setattr(cls, BASE_OPTIONS, options)
        subclass, returns, converts, coerces, deeply = (bool(option) for option in options[:5])
        if _environment.TYPECHECK_OFF or vars(cls).get("__no_type_check__"):
            return                                          # the class stays as written; its subclasses ask again
        if "<locals>" in cls.__qualname__:                  # a class defined inside a function: see remember_scope
            remember_scope(cls, frame_above())
        enforce_members(cls, subclass, returns, converts, coerces, deeply, warn)


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
    on_error: NotRequired[Literal["raise", "warn"]]


_SPEC_REQUIRED = frozenset({"object_name", "record"})
_SPEC_ALLOWED = _SPEC_REQUIRED | {"allow_subclass", "args", "kwargs", "skip_first", "convert", "coerce", "deep", "on_error"}


def typecheck_record(spec: TypecheckSpec | Mapping[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """
    Type-check a call described by a dictionary instead of a decorator.

    Args:
        spec: Must contain ``object_name`` (a callable, or a string used only for
            messages) and ``record`` (parameter name -> annotation). Optional keys:
            ``allow_subclass`` (default True), ``args``, ``kwargs``, ``skip_first``,
            ``convert`` (default True), ``coerce`` (default False), ``deep``
            (default False: check the items inside collections too) and ``on_error``
            (``"raise"``, the default, or ``"warn"``: a value that fails is reported as a
            ``TypeCheckerWarning``, and the arguments are returned as they are).
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
    warn = warns(spec.get("on_error", "raise"))

    if not callable(target) and not isinstance(target, str):
        raise TypeCheckerError(
            break_trace_colouring + f"Spec key 'object_name' must be a callable or a str, "
            f"got {formatter(type(target).__name__, 'bold_red')}"
            )

    #* The prepared checker (signature, defaults, compiled checks) is cached per target + record:
    #* for a name in ``RECORD_CACHE``, for a callable on the callable itself (see ``_kept_on``).
    key: Any
    cache = _remembered.RECORD_CACHE                   # through the module: a test may put another in its place
    if type(target) is FunctionType:                    # ``_kept_on``, written out: this is the path of every call
        entry = target.__dict__.get(RECORDS)
        cache = entry[1] if entry is not None and entry[0] is target else NOTHING_KEPT
    try:
        key = (target, tuple(record.items()), allow_subclass, skip_first, convert, coerce, deep, warn)
        cached = cache.get(key)
    except TypeError:                   # unhashable target or annotation: no caching
        key = cached = None

    #* Equal records aren't always the same check: int | float == float | int, yet conversion tries
    #* the members in declared order. A record with unions has one checker per order of their members.
    checker = cached
    if type(cached) is tuple:
        names, by_order = cached
        checker = by_order.get(tuple([union_order(record[name]) for name in names]))
    if checker is None:
        checker = new_record_checker(key, target, record, allow_subclass, skip_first, convert, coerce, deep, warn)

    #* For a real callable, defaults are validated first (once), exactly like the decorator.
    args, kwargs = checker.check_inputs(args, kwargs)
    if checker.inject is not None:                      # a default that had to be converted: handed back by keyword
        args, kwargs = checker.with_defaults(args, kwargs)
    return args, kwargs


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
    on_error: Literal["raise", "warn"] = "raise",
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
        allow_subclass, check_return, convert, coerce, deep, on_error: As for ``typecheck``.

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
    if on_error != "raise":
        warns(on_error)                                 # refused here if it is neither: the options are a dictionary key below
    options = (allow_subclass, check_return, convert, coerce, deep, on_error)
    #* What was made of a function before is kept on the function itself (see ``_kept_on``, written
    #* out here: this is the path of every call). ``entry[0] is fn``: a decorator made with
    #* functools.wraps copies the attributes of what it wraps, and that entry speaks for the function inside.
    if type(fn) is FunctionType:
        entry = fn.__dict__.get(CALLS)
    else:
        entry = _remembered.CALL_WRAPPERS.get(id(fn))
    checked = entry[1].get(options) if entry is not None and entry[0] is fn else None
    if checked is None:
        checked = call_wrapper(fn, options, frame_above())
    return checked(*args) if kwargs is None else checked(*args, **kwargs)


def enforce_class[T: type](
    cls: T,
    *,
    allow_subclass: bool = True,
    check_return: bool = False,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    on_error: Literal["raise", "warn"] = "raise",
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
        allow_subclass, check_return, convert, coerce, deep, on_error: As for ``enforce``.

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
        remember_scope(cls, frame_above())
    return enforce(cls, allow_subclass, check_return, convert, coerce, deep, on_error = on_error)
