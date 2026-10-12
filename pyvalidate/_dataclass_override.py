"""Type-checked drop-in for dataclasses.dataclass."""
from ._typechecker.api import (
    SLOW,
    FAILED,
    _ExtraDefaults,
    PreparedChecker,
    _check_defaults,
    _signature,
    _signature_stub,
    _tag_owner,
    _wrap_callable,
    _resolve_annotations,
    _remember_scope,
    _resolver,
    UNCHECKED_FIELDS,
    expected_text,
    _compile_spec,
    _compile_converter,
    _check_expr,
    _shape_body,
    _subject_path,
    _introspected,
    )
from ._typechecker.api import FAILED
from ._typechecker import TypeCheckerError
from ._typechecker._type_container import short_repr, type_name
from .utils import formatter
from functools import partial, wraps
from types import CodeType, FunctionType, MemberDescriptorType
from typing import Any, Callable, dataclass_transform, overload
import dataclasses
import inspect
import re
import sys


_MISSING = object()

#* Set on every class this module's ``dataclass`` builds. An instance is checked with the options of
#* the first such class in its type's MRO: a decorated subclass replaces the checks of its bases.
_CHECKED = "__pyvalidate_dataclass__"
#* On a generated ``__setattr__``: the function it calls once the value is checked, and a hook that
#* makes it leave the instances of a decorated subclass alone (see ``_plain_setattr``).
_WRAPS = "__pyvalidate_wraps__"
_STEP_ASIDE = "__pyvalidate_step_aside__"


#* What a static type checker is told. The class comes back as the class it was (not ``Any``), and
#* ``dataclass_transform`` says that it now behaves like a standard dataclass: ``__init__`` takes the
#* fields, ``frozen`` forbids assignment, ``field(...)`` describes a field. Without both, a decorated
#* class had no type at all in an editor: no completion, no errors, in every file that used it.
@overload
def dataclass[T](
    cls: type[T], /, *, init: bool = ..., repr: bool = ..., eq: bool = ..., order: bool = ...,
    unsafe_hash: bool = ..., frozen: bool = ..., match_args: bool = ..., kw_only: bool = ..., slots: bool = ...,
    weakref_slot: bool = ..., allow_subclass: bool = ..., check_assignment: bool = ..., convert: bool = ...,
    coerce: bool = ..., deep: bool = ...,
    ) -> type[T]: ...
@overload
def dataclass[T](
    cls: None = None, /, *, init: bool = ..., repr: bool = ..., eq: bool = ..., order: bool = ...,
    unsafe_hash: bool = ..., frozen: bool = ..., match_args: bool = ..., kw_only: bool = ..., slots: bool = ...,
    weakref_slot: bool = ..., allow_subclass: bool = ..., check_assignment: bool = ..., convert: bool = ...,
    coerce: bool = ..., deep: bool = ...,
    ) -> Callable[[type[T]], type[T]]: ...
@dataclass_transform(field_specifiers = (dataclasses.field, dataclasses.Field))
def dataclass(
    cls: type | None = None,
    /,
    *,
    init: bool = True,
    repr: bool = True,
    eq: bool = True,
    order: bool = False,
    unsafe_hash: bool = False,
    frozen: bool = False,
    match_args: bool = True,
    kw_only: bool = False,
    slots: bool = False,
    weakref_slot: bool = False,
    allow_subclass: bool = True,
    check_assignment: bool = True,
    convert: bool = True,
    coerce: bool = False,
    deep: bool = False,
    ) -> Any:
    """
    Same as ``dataclasses.dataclass``, but field types are enforced at runtime.

    Args:
        init (bool): Whether to generate the ``__init__`` method.
        repr (bool): Whether to generate the ``__repr__`` method.
        eq (bool): Whether to generate the ``__eq__`` method.
        order (bool): Whether to generate the ordering methods.
        unsafe_hash (bool): Whether to generate a ``__hash__`` method.
        frozen (bool): Whether to make the dataclass immutable.
        match_args (bool): Whether to generate the ``__match_args__`` attribute.
        kw_only (bool): Whether to make all fields keyword-only.
        slots (bool): Whether to generate a ``__slots__`` attribute.
        weakref_slot (bool): Whether to include a weakref slot.
        allow_subclass (bool): Passed through to the type checker.
        check_assignment (bool): Also check ``obj.field = value`` after construction
            (ignored for frozen dataclasses, which can't be assigned to).
        convert (bool): Losslessly convert values that fail their check (``1`` -> ``1.0`` for a
            ``float`` field), in construction, defaults and assignment. On by default.
        coerce (bool): Also parse/narrow values (``"42"`` -> ``42``). Off by default.
        deep (bool): Also check the items inside collection fields, at every depth
            (``list[int]``, ``dict[str, list[float]]``, ``tuple[int, str]``, TypedDict ...).
            Off by default.
    """
    def wrap(cls: Any, frame: Any = None) -> Any:
        #* typing.no_type_check on the class: a standard dataclass, with nothing checked.
        if getattr(cls, "__no_type_check__", False):
            return dataclasses.dataclass(
                cls, init = init, repr = repr, eq = eq, order = order,
                unsafe_hash = unsafe_hash, frozen = frozen, match_args = match_args,
                kw_only = kw_only, slots = slots, weakref_slot = weakref_slot,
                )
        #* A class defined inside a function: the local names its string annotations use are looked
        #* up now, where the decorator is written (it is called from there unless ``frame`` says so).
        local = "<locals>" in cls.__qualname__
        if local and frame is None:
            frame = sys._getframe(1)
        hooked = check_assignment and not frozen            # assignments go through a generated __setattr__
        #* What a default_factory returns never passes through __init__'s arguments. The assignment
        #* check sees it; where there is none (frozen, check_assignment=False) the factory is wrapped.
        bind_factories = restore_factories = None
        if init:
            bind_factories, restore_factories = _check_factories(cls, hooked, allow_subclass, convert, coerce, deep)
        #* Build the real dataclass first; with slots=True this returns a *new* class.
        try:
            cls = dataclasses.dataclass(
                cls, init = init, repr = repr, eq = eq, order = order,
                unsafe_hash = unsafe_hash, frozen = frozen, match_args = match_args,
                kw_only = kw_only, slots = slots, weakref_slot = weakref_slot,
                )
        finally:
            if restore_factories is not None:
                restore_factories()
        if local:
            _remember_scope(cls, frame, fields = True)      # on the finished class: slots=True made a new one
        if unchecked := _descriptor_fields(cls):
            setattr(cls, UNCHECKED_FIELDS, unchecked)       # read wherever the annotations are (_resolve_annotations)
        if bind_factories is not None:
            bind_factories(cls)
        mark = None
        if hooked:
            mark = _wrap_setattr(cls, allow_subclass, convert, coerce, deep, cls.__init__ if init else None)
        elif not frozen:
            _unchecked_setattr(cls)
        setattr(cls, _CHECKED, True)
        if init:
            _wrap_init(cls, allow_subclass, convert, coerce, deep, mark, slots)
        elif not slots:                     # with slots, a default that no __init__ assigns never reaches an instance
            _check_defaults_once(cls, allow_subclass, convert, coerce, deep)
        return cls

    #* @dataclass() with parentheses vs @dataclass without.
    if cls is None:
        return wrap

    return wrap(cls, sys._getframe(1) if "<locals>" in getattr(cls, "__qualname__", "") else None)


def _descriptor_fields(cls: type) -> frozenset[str]:
    """
    The fields whose class attribute is a descriptor that takes assignments (it has ``__set__``).
    The standard library hands the values of such a field to the descriptor, which stores what it
    likes, and reads the default from it. Its annotation names the descriptor class, not what the
    values are (``quantity: Conversion = Conversion(default = 100)``), so there is nothing to
    check the values against: they are left to the descriptor.
    """
    names: list[str] = []
    for field in dataclasses.fields(cls):
        for klass in cls.__mro__:
            if field.name in vars(klass):
                held = vars(klass)[field.name]
                #* A slot is a descriptor too: that one is how slots=True stores every field.
                if hasattr(type(held), "__set__") and not isinstance(held, MemberDescriptorType):
                    names.append(field.name)
                break
    return frozenset(names)


def _wrap_init(
    cls: Any,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool = False,
    mark: Callable[[], dict[str, Any] | None] | None = None,
    slots: bool = False,
    ) -> None:
    """
    Check constructor arguments (defaults first, then supplied args) before the real __init__ runs.
    ``mark`` comes from ``_wrap_setattr``: where the checked arguments are published while it runs.
    """
    cls.__init__ = _wrap_callable(  # type: ignore[method-assign]
        cls.__init__, allow_subclass, False, cls, skip_first = True, convert = convert, coerce = coerce,
        deep = deep, mark = mark, extra_defaults = _unlisted_defaults(cls, slots),
        in_place = True,                    # the generated __init__ is this class's alone: converted defaults go into it
        )
    return


def _check_defaults_once(cls: Any, allow_subclass: bool, convert: bool, coerce: bool, deep: bool) -> None:
    """
    ``dataclass(init=False)``: no generated ``__init__`` takes the field defaults. They stay on the
    class, where instances read them, so they are checked (and converted) when the first instance is
    built. Until then the class's ``__init__`` is a thin wrapper around the real one, which takes
    itself away once the defaults are right: later constructions cost nothing extra.
    """
    extra = _unlisted_defaults(cls, False, every = True)
    if extra is None:
        return
    inherited = "__init__" not in vars(cls)
    original = cls.__init__                                    # the class's own, or the one it inherits
    stub = _signature_stub("__init__", {})                      # what the problems are reported against
    _tag_owner(stub, cls)

    @wraps(original)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        _check_defaults(stub, {}, allow_subclass, convert, coerce, False, deep, extra, _resolver(cls, cls))    # raises until right
        if vars(cls).get("__init__") is __init__:
            if inherited:
                type.__delattr__(cls, "__init__")
            else:
                type.__setattr__(cls, "__init__", original)
        original(self, *args, **kwargs)

    cls.__init__ = __init__                                    # type: ignore[method-assign]
    return


def _unlisted_defaults(cls: Any, slots: bool, every: bool = False) -> _ExtraDefaults | None:
    """
    The plain defaults that ``__init__`` doesn't list as parameters: ``field(init=False, default=...)``,
    or with ``every`` all of them (a class without a generated ``__init__``). Nothing passes them to
    the checker, so they are handed to it here and checked (and converted) with the other defaults,
    on the first construction. Returns None for a class without such a field.
    """
    names = [f.name for f in dataclasses.fields(cls) if (every or not f.init) and f.default is not dataclasses.MISSING]
    if not names:
        return None
    init = cls.__init__                                        # the generated one, before it is wrapped

    def defaults() -> list[tuple[str, Any, Any, Callable[[Any], None]]]:
        hints = _resolve_annotations(cls, cls)
        fields = cls.__dataclass_fields__                       # type: ignore[attr-defined]
        return [(name, fields[name].default, hints[name], _default_store(cls, init, name, fields[name].default, slots))
                for name in names if name in hints]

    return defaults


def _default_store(cls: type, init: Callable[..., Any], name: str, default: Any, slots: bool) -> Callable[[Any], None]:
    """Where the converted default of an ``init=False`` field goes, so that instances get it."""
    if not slots:
        def store_on_class(value: Any) -> None:
            if getattr(cls, name, _MISSING) is default:         # instances read the default from the class
                type.__setattr__(cls, name, value)
        return store_on_class

    #* With slots there is no class attribute to read: the generated __init__ assigns the default on
    #* every construction, from a closure cell that dataclasses gives the functions it generates.
    try:
        cell = init.__closure__[init.__code__.co_freevars.index(f"__dataclass_dflt_{name}__")]   # type: ignore
    except (AttributeError, TypeError, ValueError):
        cell = None                                             # an __init__ written by hand: nothing assigns the default

    def store_in_init(value: Any) -> None:
        if cell is not None and cell.cell_contents is default:
            cell.cell_contents = value
    return store_in_init


def _field_reporter(
    owner: list[type],
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool,
    ) -> Callable[[Any, str, Any], Any]:
    """
    ``report(instance, name, value)``: the slow path for one field. Returns ``value`` (converted if
    allowed) or raises the detailed error. ``owner[0]`` is the dataclass; it is read on first use,
    so the reporter can be made before the class exists.
    """
    field_checkers: dict[str, PreparedChecker] = {}           # one per field, once its annotation resolves

    def report(_: Any, name: str, value: Any) -> Any:
        cls = owner[0]
        checker = field_checkers.get(name)
        if checker is None:
            hints = _resolve_annotations(cls, cls)
            if name not in hints:
                return value
            record = {name: hints[name]}
            checker = PreparedChecker(
                _signature_stub(f"{cls.__name__}.{name}", record),
                allow_subclass,
                None,
                False,
                record = record,
                convert = convert,
                coerce = coerce,
                deep = deep,
                resolve = _resolver(cls, cls),              # the record is the class's own annotations: source code
                )
        try:
            _, checked = checker.check_inputs((), {name: value})
        except TypeCheckerError as e:
            raise _as_field_error(e, cls) from None
        finally:
            if checker.ready:                                   # unresolved forward refs are retried next time
                field_checkers[name] = checker
        return checked[name]

    return report


def _check_factories(
    cls: type,
    hooked: bool,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool,
    ) -> tuple[Callable[[type], None], Callable[[], None]]:
    """
    Decide who checks what each ``default_factory`` returns, before the dataclass is built. With
    ``hooked`` the class's ``__setattr__`` does, so ``__init__`` is given the factory as it was
    written. Otherwise the factory is wrapped: its result is checked (and converted) like an
    assignment to its field, with this class's options.

    Inherited fields are covered too. Their ``Field`` objects belong to the base class, so their
    factory is swapped only while ``dataclasses`` generates this class's ``__init__`` (which is when
    it is read). Returns ``(bind, restore)``: ``restore()`` puts the base classes' factories back,
    ``bind(cls)`` gives the wrappers the finished class.
    """
    owner: list[type] = []
    report = _field_reporter(owner, allow_subclass, convert, coerce, deep)
    own = {name: value for name, value in vars(cls).items() if isinstance(value, dataclasses.Field)}
    inherited: dict[str, Any] = {}
    for base in cls.__mro__[1:]:                                # the nearest base wins, as in dataclasses
        for name, base_field in getattr(base, "__dataclass_fields__", {}).items():
            inherited.setdefault(name, base_field)
    borrowed: list[tuple[Any, Any]] = []                        # (a base class's Field, its own factory)
    for name, value in {**inherited, **own}.items():
        if value.default_factory is dataclasses.MISSING:
            continue
        #* A Field seen before (a checked base class, an object reused in two classes) may hold a
        #* wrapper made for that class: start again from the factory itself.
        factory = getattr(value.default_factory, "__pyvalidate_factory__", value.default_factory)
        if name not in own:
            borrowed.append((value, value.default_factory))
        value.default_factory = factory if hooked else _checked_factory(
            factory, name, owner, report, allow_subclass, convert, coerce, deep)

    def restore() -> None:
        for base_field, factory in borrowed:
            base_field.default_factory = factory

    return owner.append, restore


def _factory_code(body: str) -> CodeType:
    namespace: dict[str, Any] = {}
    exec(compile(f"def checked():\n    {body}\n", "<pyvalidate default_factory>", "exec"), namespace)
    return namespace["checked"].__code__


#* Until the field's annotation has been resolved: hand the result to ``first``.
_FACTORY_BOOT = _factory_code("return _pv_first(_pv_factory())")


def _checked_factory(
    factory: Callable[[], Any],
    name: str,
    owner: list[type],
    report: Callable[[Any, str, Any], Any],
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool,
    ) -> Callable[[], Any]:
    """
    ``factory``, with its result checked against field ``name`` of ``owner[0]``. On first use the
    wrapper's code is replaced by one with the check inlined, as for a function's wrapper: a valid
    result then costs one call and one type test. Anything else goes to ``report``.
    """
    ns: dict[str, Any] = {"_pv_factory": factory}
    checked = FunctionType(_FACTORY_BOOT, ns, getattr(factory, "__name__", "default_factory"))

    def slow(value: Any) -> Any:
        return report(None, name, value) if owner else value   # converted, or raises the field error

    def first(value: Any) -> Any:
        if owner:
            hints = _resolve_annotations(owner[0], owner[0])
            spec = (_compile_spec(hints[name], allow_subclass, name, deep, convert, coerce, _resolver(owner[0], owner[0]))
                    if name in hints else ("any",))
            if spec is not SLOW:                               # else: an unresolved forward ref, retried next time
                expr = _check_expr(spec, "_pv_v", ns, "f")      # type: ignore[arg-type]
                checked.__code__ = _factory_code(
                    "return _pv_factory()" if expr is None
                    else f"_pv_v = _pv_factory()\n    if {expr}: return _pv_v\n    return _pv_slow(_pv_v)"
                    )
        return slow(value)

    ns.update(_pv_first = first, _pv_slow = slow)
    checked.__wrapped__ = checked.__pyvalidate_factory__ = factory      # type: ignore[attr-defined]
    return checked


def _init_params(init: Callable[..., Any]) -> dict[str, tuple[int | None, Any]]:
    """
    How ``__init__`` receives each parameter after self: ``(positional index, default)``. The index
    counts self as 0 and is None for a keyword-only parameter; the default is ``_MISSING`` when
    there is none.
    """
    P = inspect.Parameter
    params: dict[str, tuple[int | None, Any]] = {}
    index = 1
    for p in list(_signature(init).parameters.values())[1:]:
        default = _MISSING if p.default is P.empty else p.default
        if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD):
            params[p.name] = (index, default)
            index += 1
        elif p.kind is P.KEYWORD_ONLY:
            params[p.name] = (None, default)
    return params


def _wrap_setattr(
    cls: type,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool = False,
    init: Callable[..., Any] | None = None,
    ) -> Callable[[], dict[str, Any] | None] | None:
    """
    Check assignments to declared fields, e.g. ``p.x = "oops"``.

    On first use, a ``__setattr__`` specialised to this class's fields is generated
    (one inlined ``isinstance``/``type`` test per field) and installed. A failing value is
    converted when allowed (``p.x = 1`` stores ``1.0`` for a ``float`` field); otherwise the
    error is raised by a cached per-field checker, with the usual messages.

    ``init`` is the dataclass's own ``__init__``. Its checked wrapper has validated every argument
    by the time ``__init__`` assigns it. An inline type test is cheaper to repeat than to avoid, but
    a check that calls a function (the items of a collection, an ``Annotated`` check) isn't run
    twice: while ``__init__`` runs, the wrapper publishes its arguments in this ``__setattr__``'s
    globals, and such a field skips the check for the very object it was given. Returns the
    ``mark`` hook for ``_wrap_callable`` (None without ``init``).

    The fields of a class include the inherited ones, so this one check covers the whole instance,
    with this class's options. It therefore calls what a checked base class's ``__setattr__`` wraps,
    not that ``__setattr__`` itself (see ``_plain_setattr``): one check per assignment.
    """
    field_names = [f.name for f in dataclasses.fields(cls)]   # excludes ClassVar and InitVar
    field_set = frozenset(field_names)
    original_setattr = _plain_setattr(cls)
    impl: Any = None
    aside = False                                              # set by step_aside()
    published: dict[str, Any] | None = None                    # the generated function's globals, if a field skips
    report = _field_reporter([cls], allow_subclass, convert, coerce, deep)
    #* The generated function's globals: one dict for good, because __init__'s wrapper keeps hold of it.
    #* _pv_args / _pv_kw: the arguments of the __init__ call now running (self first), else (None,) / {}.
    ns: dict[str, Any] = {"_pv_orig": original_setattr, "_pv_report": report, "_pv_F": FAILED,
                          "_pv_args": (None,), "_pv_kw": {}, "_pv_cls": cls, "_pv_governed": _governed_by_subclass}

    def build() -> Any:
        nonlocal published
        hints = _resolve_annotations(cls, cls)
        resolve = _resolver(cls, cls)
        params = _init_params(init) if init is not None else {}
        lines = ["def __setattr__(self, name, value):"]
        if aside:
            #* Reached through a hand-written __setattr__ for an instance of a decorated subclass,
            #* whose own check has done the work. Only classes in that position pay for this test.
            lines.append("    if type(self) is not _pv_cls and _pv_governed(type(self), _pv_cls):")
            lines.append("        return _pv_orig(self, name, value)")
        keyword = "if"
        skips = False
        for i, name in enumerate(field_names):
            if name not in hints:
                continue
            spec = _compile_spec(hints[name], allow_subclass, name, deep, convert, coerce, resolve)
            if spec is SLOW:
                return None                 # unresolved forward ref: retry on a later assignment
            expr = _check_expr(spec, "value", ns, str(i))   # type: ignore
            if expr is None:
                continue
            lines.append(f"    {keyword} name == {name!r}:")
            ind = "        "
            if spec[0] == "pred" and name in params:          # type: ignore[index]
                #* Skip only the object __init__ received for this field (or its default, when it got
                #* none): that one passed this very check a moment ago. Anything else is checked: a
                #* default_factory's result, what __post_init__ assigns, every later assignment.
                pos, ns[f"_pv_dflt_{i}"] = params[name]
                by_keyword = f"_pv_kw.get({name!r}, _pv_dflt_{i})"
                given = by_keyword if pos is None else f"(_pv_args[{pos}] if len(_pv_args) > {pos} else {by_keyword})"
                lines.append(f"{ind}if _pv_args[0] is not self or value is not {given}:")
                ind += "    "
                skips = True
            converter = _compile_converter(hints[name], allow_subclass, name, convert, coerce, deep, resolve)
            if converter is None:
                lines.append(f"{ind}if not ({expr}): _pv_report(self, name, value)")   # raises
            else:
                ns[f"_pv_conv_{i}"] = converter
                lines.append(f"{ind}if not ({expr}):")
                lines.append(f"{ind}    _pv_out = _pv_conv_{i}(value)")
                lines.append(f"{ind}    if _pv_out is _pv_F: _pv_report(self, name, value)")   # raises
                lines.append(f"{ind}    value = _pv_out")
            keyword = "elif"
        lines.append("    _pv_orig(self, name, value)")
        exec(compile("\n".join(lines), f"<pyvalidate __setattr__ for {cls.__qualname__}>", "exec"), ns)
        published = ns if skips else None
        return _tag_setattr(ns["__setattr__"], original_setattr, step_aside)

    def ready() -> bool:
        """Generate and install the specialised __setattr__ (False while an annotation can't be resolved)."""
        nonlocal impl
        if impl is None:
            impl = build()
            if impl is None:
                return False
            if cls.__dict__.get("__setattr__") is __setattr__:
                type.__setattr__(cls, "__setattr__", impl)   # later lookups skip this bootstrap
        return True

    def step_aside() -> None:
        """From now on, leave the instances of a decorated subclass to that subclass's own check."""
        nonlocal aside, impl
        if aside:
            return
        aside = True
        stale, impl = impl, None                                # generated again on the next use, with the test
        if stale is not None and cls.__dict__.get("__setattr__") is stale:
            type.__setattr__(cls, "__setattr__", __setattr__)

    def __setattr__(self: Any, name: str, value: Any) -> None:
        #* @no_type_check written above @dataclass marks the class after this was made: seen on first use.
        if impl is None and vars(cls).get("__no_type_check__"):
            if cls.__dict__.get("__setattr__") is __setattr__:
                type.__setattr__(cls, "__setattr__", original_setattr)
            original_setattr(self, name, value)
            return
        if not ready():
            if name in field_set and not (aside and type(self) is not cls and _governed_by_subclass(type(self), cls)):
                value = report(self, name, value)
            original_setattr(self, name, value)
            return
        impl(self, name, value)                             # type: ignore[misc]  # ready() has just made it

    cls.__setattr__ = _tag_setattr(__setattr__, original_setattr, step_aside)  # type: ignore[method-assign]

    if init is None:
        return None

    def mark() -> dict[str, Any] | None:
        return published if ready() else None

    return mark


def _tag_setattr(hook: Any, wraps: Any, step_aside: Callable[[], None]) -> Any:
    """Mark ``hook`` as a generated ``__setattr__`` (see ``_plain_setattr``)."""
    setattr(hook, _WRAPS, wraps)
    setattr(hook, _STEP_ASIDE, step_aside)
    return hook


def _plain_setattr(cls: type) -> Any:
    """
    What stores an attribute of ``cls`` once the value is checked: the ``__setattr__`` it inherits or
    defines, or, when that is the check of a decorated base class, what that check wraps. So the
    checks of a class hierarchy never stack: each instance has one, its own class's.

    A base class's check can still be reached another way, through a hand-written ``__setattr__``
    that calls ``super().__setattr__``. Each such check is told to step aside for the instances
    of a decorated subclass.
    """
    hand_written = False
    for klass in cls.__mro__[:-1]:                              # object.__setattr__ is where they all end
        attr = vars(klass).get("__setattr__")
        if attr is None:
            continue
        step_aside = getattr(attr, _STEP_ASIDE, None)
        if step_aside is None:
            hand_written = True
        elif hand_written:
            step_aside()
    found = cls.__setattr__
    return getattr(found, _WRAPS, found)


def _governed_by_subclass(tp: type, cls: type) -> bool:
    """Whether a decorated subclass of ``cls`` comes before it in ``tp``'s MRO: its options apply to ``tp``'s instances."""
    for klass in tp.__mro__:
        if klass is cls:
            return False
        if _CHECKED in vars(klass):
            return True
    return False


def _unchecked_setattr(cls: type) -> None:
    """
    ``check_assignment=False`` below a base class that checks assignments: this class's instances
    skip that check, for the inherited fields as for its own.
    """
    plain = _plain_setattr(cls)
    if plain is not cls.__setattr__:
        cls.__setattr__ = plain                                 # type: ignore[method-assign]


def _as_field_error(error: TypeCheckerError, cls: type) -> TypeCheckerError:
    """
    Re-label a failed assignment: ``Field qty of <Dataclass Order>: ...`` and
    ``1 problem found in assignment``. Still lazy: nothing is formatted until printed.
    """
    for problem in error.problems:
        if problem.kind == "type":
            problem.kind = "field"
            problem.origin = cls
            problem._render = partial(_field_message, cls, problem)
        elif problem.kind in ("length", "missing_key", "cycle", "invalid"):    # deep checks: the shape is wrong
            problem.origin = cls
            problem._render = partial(_field_shape_message, cls, problem)
    error.context = "field assignment"
    return error


def _field_origin(cls: type) -> tuple[str, str]:
    kind = formatter(formatter("Dataclass", "bold_magenta"), "bold")
    cls_name = formatter(cls.__name__, 'bold_blue')
    return cls_name, f"<{kind} {cls_name}>"


def _field_subject(cls_name: str, path: str) -> str:
    """``Field Order.qty``, or for an item inside a field ``Introspected field Order.lines at index [1][1]``."""
    root = re.match(r"[^\[.]+", path).group()               # type: ignore[union-attr]  # the field name: an identifier
    if (where := _introspected(root, path)) is not None:
        return f"Introspected field {cls_name}.{formatter(root, 'bold_green')} {where}"
    return f"Field {cls_name}.{formatter(path, 'bold_green')}"


def _field_shape_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return f"{_field_subject(cls_name, _subject_path(problem))} of {origin}: {_shape_body(problem)}"


def _field_message(cls: type, problem: Any) -> str:
    cls_name, origin = _field_origin(cls)
    return (
        f"{_field_subject(cls_name, problem.parameter)} of {origin}: "
        f"expected type: {formatter(expected_text(problem.expected, problem.annotation), 'bold_yellow')}, "
        f"got type {formatter(type_name(type(problem.value)), 'bold_red')} "
        f"(Value: {formatter(short_repr(problem.value), 'bold_red')})"
        )
