"""
Construction of a checked dataclass: the wrapped ``__init__``, the one that stores checked
arguments directly, defaults and ``default_factory``.
"""
from .._typechecker._annotations import resolve_annotations, tag_owner
from .._typechecker._codegen import check_expr
from .._typechecker._defaults import check_defaults
from .._typechecker._scope import resolver
from .._typechecker._signatures import signature_stub
from .._typechecker._specs import compile_spec, SLOW
from .._typechecker._wrapping import wrap_callable
from ._assignment import field_reporter, MISSING, plain_setattr
from typing import Any, Callable, TYPE_CHECKING
from functools import wraps
from types import CodeType, FunctionType
import dataclasses
import inspect

if TYPE_CHECKING:
    from .._typechecker._defaults import ExtraDefaults


def wrap_init(
    cls: Any,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool = False,
    mark: Callable[[], dict[str, Any] | None] | None = None,
    slots: bool = False,
    storing: Callable[..., Any] | None = None,
    warn: bool = False,
    ) -> None:
    """
    Check constructor arguments (defaults first, then supplied args) before the real __init__ runs.
    ``mark`` comes from ``wrap_setattr``: where the checked arguments are published while it runs.
    ``storing`` makes the __init__ that is called in place of the standard one, once the wrapper is compiled
    (see ``storing_init``).
    """
    extra = _unlisted_defaults(cls, slots)              # reads the standard __init__: before it is replaced
    cls.__init__ = wrap_callable(  # type: ignore[method-assign]
        cls.__init__, allow_subclass, False, cls, skip_first = True, convert = convert, coerce = coerce,
        deep = deep, mark = mark, extra_defaults = extra,
        in_place = True,                    # the generated __init__ is this class's alone: converted defaults go into it
        upgrade = storing,
        warn = warn,
        )
    return


def storing_init(cls: Any, slots: bool) -> Callable[[], Callable[..., Any] | None] | None:
    """
    An ``__init__`` for a dataclass whose assignments are checked, which checks each field once.

    The standard ``__init__`` assigns its arguments (``self.x = x``), and every assignment goes
    through the generated ``__setattr__``: an argument that the wrapper of ``__init__`` had just
    checked was checked again there. This one takes the same parameters and does what the standard
    one does, in the same order, but stores an argument with ``object.__setattr__``, past the
    check. Only an argument: what a ``default_factory`` returns has been checked by nobody, and is
    assigned the ordinary way, and so is whatever ``__post_init__`` assigns.

        def __init__(self, x, tags=<factory>, *, label=_pv_d2):
            if type(self) is not _pv_cls: return _pv_std(self, x, tags, label=label)
            _pv_set(self, 'x', x)
            if tags is _pv_factory: self.tags = _pv_f1()
            else: _pv_set(self, 'tags', tags)
            _pv_set(self, 'label', label)
            self.__post_init__()

    An instance of a subclass is handed to the standard ``__init__`` (the first line): a subclass
    may have a ``__setattr__`` of its own, which an assignment has to reach.

    Returned is what makes it, not the function: compiling it takes 100 µs, a third of what
    defining the class takes, and a class that is constructed a few times never earns that back.
    It is made when the wrapper of ``__init__`` is compiled (``upgrade`` of ``wrap_callable``);
    until then the standard ``__init__`` assigns, and each argument is checked twice.

    ``None`` where the standard one is kept: a ``__setattr__`` written by hand somewhere in the
    class's line (it must see the assignments), a field named like one of ours, a slots class with
    a default that ``__init__`` doesn't take, or a ``dataclasses`` that keeps its fields another way.
    """
    try:
        std = cls.__init__
        if plain_setattr(cls) is not object.__setattr__:
            return None
        P = inspect.Parameter
        parameters = list(inspect.signature(std).parameters.values())
        if not parameters or parameters[0].name != "self":
            return None
        ns: dict[str, Any] = {"_pv_cls": cls, "_pv_std": std, "_pv_set": object.__setattr__, "_pv_factory": _HAS_DEFAULT_FACTORY}
        written, passed, keyword_only = ["self"], ["self"], False
        for i, p in enumerate(parameters[1:]):
            if p.kind not in (P.POSITIONAL_OR_KEYWORD, P.KEYWORD_ONLY) or not p.name.isidentifier() or p.name.startswith("_pv_"):
                return None
            if p.kind is P.KEYWORD_ONLY and not keyword_only:
                written.append("*")
                keyword_only = True
            if p.default is P.empty:
                written.append(p.name)
            else:
                ns[f"_pv_d{i}"] = None                  # read when it is made: the first call may convert a default
                written.append(f"{p.name}=_pv_d{i}")
            passed.append(f"{p.name}={p.name}" if keyword_only else p.name)
        taken = {p.name for p in parameters[1:]}
        lines = [f"    def __init__({', '.join(written)}):",
                 f"        if type(self) is not _pv_cls: return _pv_std({', '.join(passed)})"]
        init_vars: list[str] = []
        for i, f in enumerate(cls.__dataclass_fields__.values()):
            kind = f._field_type.name                   # a private name of dataclasses: read inside the try
            if kind == "_FIELD_CLASSVAR":
                continue
            if kind == "_FIELD_INITVAR":
                if f.init:
                    init_vars.append(f.name)
                continue
            if kind != "_FIELD" or not f.name.isidentifier():
                return None
            has_factory = f.default_factory is not dataclasses.MISSING
            if has_factory:
                #* The factory as it was written: an inherited field may hold a wrapper that checks
                #* for the base class, and the result is checked here, by the assignment.
                ns[f"_pv_f{i}"] = getattr(f.default_factory, "__enforced_factory__", f.default_factory)
            if f.init:
                if f.name not in taken:
                    return None
                if has_factory:
                    lines.append(f"        if {f.name} is _pv_factory: self.{f.name} = _pv_f{i}()")
                    lines.append(f"        else: _pv_set(self, {f.name!r}, {f.name})")
                else:
                    lines.append(f"        _pv_set(self, {f.name!r}, {f.name})")
            elif has_factory:
                lines.append(f"        self.{f.name} = _pv_f{i}()")
            elif slots and f.default is not dataclasses.MISSING:
                return None                             # the standard __init__ assigns it from a cell of its own
        if hasattr(cls, "__post_init__"):
            lines.append(f"        self.__post_init__({', '.join(init_vars)})")
        #* Made inside a function that takes our names as its arguments: the __init__ then lives in
        #* the module of the class, like the standard one, which is where a string annotation of a
        #* field is read (its globals), and finds our names in its closure.
        source = "\n".join([f"def _pv_make({', '.join(ns)}):", *lines, "    return __init__"])
    except Exception:                                   # anything unforeseen: the standard __init__, checked as before
        return None

    def make() -> Callable[..., Any] | None:
        try:
            for i, p in enumerate(list(inspect.signature(std).parameters.values())[1:]):
                if p.default is not P.empty:
                    ns[f"_pv_d{i}"] = p.default
            scratch: dict[str, Any] = {}
            exec(compile(source, f"<enforced __init__ for {cls.__qualname__}>", "exec"), std.__globals__, scratch)
            made = scratch["_pv_make"](**ns)
            made.__qualname__, made.__module__, made.__doc__ = std.__qualname__, std.__module__, std.__doc__
            if getattr(std, "__annotate__", None) is not None:
                made.__annotate__ = std.__annotate__
            else:
                made.__annotations__ = dict(getattr(std, "__annotations__", None) or {})
            return made                                 # type: ignore[no-any-return]
        except Exception:
            return None
    return make



_HAS_DEFAULT_FACTORY = getattr(dataclasses, "_HAS_DEFAULT_FACTORY", None)


def check_defaults_once(cls: Any, allow_subclass: bool, convert: bool, coerce: bool, deep: bool) -> None:
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
    stub = signature_stub("__init__", {})                      # what the problems are reported against
    tag_owner(stub, cls)

    @wraps(original)
    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        check_defaults(stub, {}, allow_subclass, convert, coerce, False, deep, extra, resolver(cls, cls))    # raises until right
        if vars(cls).get("__init__") is __init__:
            if inherited:
                type.__delattr__(cls, "__init__")
            else:
                type.__setattr__(cls, "__init__", original)
        original(self, *args, **kwargs)

    cls.__init__ = __init__                                    # type: ignore[method-assign]
    return


def _unlisted_defaults(cls: Any, slots: bool, every: bool = False) -> ExtraDefaults | None:
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
        hints = resolve_annotations(cls, cls)
        fields = cls.__dataclass_fields__                       # type: ignore[attr-defined]
        return [(name, fields[name].default, hints[name], _default_store(cls, init, name, fields[name].default, slots))
                for name in names if name in hints]

    return defaults


def _default_store(cls: type, init: Callable[..., Any], name: str, default: Any, slots: bool) -> Callable[[Any], None]:
    """Where the converted default of an ``init=False`` field goes, so that instances get it."""
    if not slots:
        def store_on_class(value: Any) -> None:
            if getattr(cls, name, MISSING) is default:         # instances read the default from the class
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


def check_factories(
    cls: type,
    hooked: bool,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool,
    warn: bool = False,
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
    report = field_reporter(owner, allow_subclass, convert, coerce, deep, warn)
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
        factory = getattr(value.default_factory, "__enforced_factory__", value.default_factory)
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
    exec(compile(f"def checked():\n    {body}\n", "<enforced default_factory>", "exec"), namespace)
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
            hints = resolve_annotations(owner[0], owner[0])
            spec = (compile_spec(hints[name], allow_subclass, name, deep, convert, coerce, resolver(owner[0], owner[0]))
                    if name in hints else ("any",))
            if spec is not SLOW:                               # else: an unresolved forward ref, retried next time
                expr = check_expr(spec, "_pv_v", ns, "f")      # type: ignore[arg-type]
                checked.__code__ = _factory_code(
                    "return _pv_factory()" if expr is None
                    else f"_pv_v = _pv_factory()\n    if {expr}: return _pv_v\n    return _pv_slow(_pv_v)"
                    )
        return slow(value)

    ns.update(_pv_first = first, _pv_slow = slow)
    checked.__wrapped__ = checked.__enforced_factory__ = factory      # type: ignore[attr-defined]
    return checked
