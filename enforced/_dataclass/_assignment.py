"""
Assignment to the fields of a checked dataclass: the generated ``__setattr__``, its first tier,
and the reporter of a value that fails.
"""
from .. import _environment
from .._typechecker._annotations import resolve_annotations
from .._typechecker._checker import DEEP, NO_TYPE, PreparedChecker
from .._typechecker._codegen import check_expr
from .._typechecker._errors import field_error, InvalidDataError, warn_of
from .._typechecker._scope import resolver
from .._typechecker._self_routing import kept_of
from .._typechecker._signatures import signature_of, signature_stub
from .._typechecker._specs import compile_converter, compile_spec, predicate, SLOW
from .._typechecker._type_conversion import FAILED
from ._field_messages import as_field_error
from typing import Any, Callable
from annotationlib import Format, get_annotations
import dataclasses
import inspect


MISSING = object()

#* Set on every class this module's ``dataclass`` builds. An instance is checked with the options of
#* the first such class in its type's MRO: a decorated subclass replaces the checks of its bases.
CHECKED = "__enforced_dataclass__"
#* On a generated ``__setattr__``: the function it calls once the value is checked, and a hook that
#* makes it leave the instances of a decorated subclass alone (see ``plain_setattr``).
_WRAPS = "__enforced_wraps__"
_STEP_ASIDE = "__enforced_step_aside__"


def field_reporter(
    owner: list[type],
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool,
    warn: bool = False,
    error: "type[InvalidDataError]" = InvalidDataError,
    ) -> Callable[[Any, str, Any], Any]:
    """
    ``report(instance, name, value)``: the slow path for one field. Returns ``value`` (converted if
    allowed) or raises the detailed error. ``owner[0]`` is the dataclass; it is read on first use,
    so the reporter can be made before the class exists.

    A field whose annotation uses ``Self`` is checked against the class of ``instance``, where
    that is a subclass of the dataclass which is not decorated itself (one that is has a check of
    its own): ``Self`` is the class of the instance, not the class that declares the field.
    """
    #* One checker per field, once its annotation resolves: (name, None). For a field that uses
    #* Self, one more for each other class it is assigned on, which that class keeps itself.
    field_checkers: dict[tuple[str, type | None], PreparedChecker] = {}
    self_fields: set[str] = set()
    #* The usual case in short: a field of the dataclass's own instances whose checker is ready
    #* and where only the type can be wrong. name -> (checker, its plan entry for the field).
    quick: dict[str, tuple[PreparedChecker, tuple[Any, ...]]] = {}

    def report(instance: Any, name: str, value: Any) -> Any:
        cls = owner[0]
        if (hit := quick.get(name)) is not None and (instance is None or type(instance) is cls):
            planned = hit[1]
            if planned[0](value):
                return value
            if planned[1] is not None and (out := planned[1](value)) is not FAILED:
                return out
            if not warn:
                raise field_error(hit[0], planned, value, cls)
            warn_of(field_error(hit[0], planned, value, cls))       # on_error = "warn": said, and stored as given
            return value
        kind = type(instance) if instance is not None else None
        if kind is cls or (kind is not None and cls not in kind.__mro__):
            kind = None
        if kind is not None and _retyped_below(kind, cls, name):
            return value                                        # the field is another class's now: see _retyped_below
        #* The checker of a field that uses Self, for another class than the dataclass: kept by that
        #* class (``kept_of``), as (the class, the checker). A copy of the class has a copy of the entry.
        of_kind = kept_of(kind) if kind is not None and name in self_fields else None
        key = (name, None)
        checker = field_checkers.get(key) if kind is None or name not in self_fields else None
        if of_kind is not None and (entry := of_kind.get((cls, name))) is not None and entry[0] is kind:
            checker = entry[1]
        if checker is None:
            uses: dict[str, bool] = {}
            hints = resolve_annotations(cls, cls, False, kind, uses)
            if name not in hints:
                return value
            if name in uses:
                self_fields.add(name)
            record = {name: hints[name]}
            checker = PreparedChecker(
                signature_stub(f"{cls.__name__}.{name}", record),
                allow_subclass,
                None,
                False,
                record = record,
                convert = convert,
                coerce = coerce,
                deep = deep,
                resolve = resolver(cls, cls),              # the record is the class's own annotations: source code
                error = error,
                )
        refused = None
        try:
            _, checked = checker.check_inputs((), {name: value})
        except InvalidDataError as e:
            #* Raised, also with on_error = "warn", where the value is not what is wrong (an
            #* annotation that can't be read has no problems to show).
            if not warn or not (e._pending is not None or e._problems):
                raise as_field_error(e, cls) from None
            #* Warned about below, outside this block: a filter that turns the warning into an
            #* exception would chain it to this error. Without its traceback, which holds this frame.
            refused = as_field_error(e, cls).with_traceback(None)
            checked = {name: value}
        finally:
            if checker.ready:                                   # unresolved forward refs are retried next time
                if kind is not None and name in self_fields:
                    if (of_kind := kept_of(kind, True)) is not None:
                        of_kind[(cls, name)] = (kind, checker)
                else:
                    field_checkers[key] = checker
                    plan = checker.kw_plan
                    #* Only where the type alone can be wrong: not a rejected value (NO_TYPE), not items (DEEP).
                    if name not in self_fields and plan is not None and (planned := plan.get(name)) is not None \
                            and planned[4] is not NO_TYPE and planned[4] is not DEEP:
                        quick[name] = (checker, planned)
        if refused is not None:
            warn_of(refused)
        return checked[name]

    return report


def _init_params(init: Callable[..., Any]) -> dict[str, tuple[int | None, Any]]:
    """
    How ``__init__`` receives each parameter after self: ``(positional index, default)``. The index
    counts self as 0 and is None for a keyword-only parameter; the default is ``MISSING`` when
    there is none.
    """
    P = inspect.Parameter
    params: dict[str, tuple[int | None, Any]] = {}
    index = 1
    for p in list(signature_of(init).parameters.values())[1:]:
        default = MISSING if p.default is P.empty else p.default
        if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD):
            params[p.name] = (index, default)
            index += 1
        elif p.kind is P.KEYWORD_ONLY:
            params[p.name] = (None, default)
    return params


def wrap_setattr(
    cls: type,
    allow_subclass: bool,
    convert: bool,
    coerce: bool,
    deep: bool = False,
    init: Callable[..., Any] | None = None,
    warn: bool = False,
    error: "type[InvalidDataError]" = InvalidDataError,
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
    ``mark`` hook for ``wrap_callable`` (None without ``init``).

    The fields of a class include the inherited ones, so this one check covers the whole instance,
    with this class's options. It therefore calls what a checked base class's ``__setattr__`` wraps,
    not that ``__setattr__`` itself (see ``plain_setattr``): one check per assignment.
    """
    field_names = [f.name for f in dataclasses.fields(cls)]   # excludes ClassVar and InitVar
    field_set = frozenset(field_names)
    original_setattr = plain_setattr(cls)
    impl: Any = None
    aside = False                                              # set by step_aside()
    published: dict[str, Any] | None = None                    # the generated function's globals, if a field skips
    report = field_reporter([cls], allow_subclass, convert, coerce, deep, warn, error)
    #* The generated function's globals: one dict for good, because __init__'s wrapper keeps hold of it.
    #* _pv_args / _pv_kw: the arguments of the __init__ call now running (self first), else (None,) / {}.
    ns: dict[str, Any] = {"_pv_orig": original_setattr, "_pv_report": report, "_pv_F": FAILED,
                          "_pv_args": (None,), "_pv_kw": {}, "_pv_cls": cls, "_pv_governed": _governed_by_subclass,
                          "_pv_retyped": _retyped_below}

    def build() -> Any:
        nonlocal published
        uses_self: dict[str, bool] = {}
        hints = resolve_annotations(cls, cls, uses = uses_self)
        resolve = resolver(cls, cls)
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
            spec = compile_spec(hints[name], allow_subclass, name, deep, convert, coerce, resolve)
            if spec is SLOW:
                return None                 # unresolved forward ref: retry on a later assignment
            expr = check_expr(spec, "value", ns, str(i))   # type: ignore
            if expr is None:
                continue
            lines.append(f"    {keyword} name == {name!r}:")
            ind = "        "
            if name in uses_self:
                #* ``Self`` is the class of the instance. The test below was compiled for this class;
                #* an instance of a subclass that isn't decorated itself is checked against its own
                #* class, by the reporter (the slow path: such a subclass is rare, and so is the field).
                lines.append(f"{ind}if type(self) is not _pv_cls: value = _pv_report(self, name, value)")
                lines.append(f"{ind}else:")
                ind += "    "
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
            converter = compile_converter(hints[name], allow_subclass, name, convert, coerce, deep, resolve)
            #* A value that fails may belong to a subclass that gave the field another type without
            #* being checked itself (``_retyped_below``). Asked only once the test has failed: a
            #* valid assignment pays nothing for it.
            theirs = f" and not (type(self) is not _pv_cls and _pv_retyped(type(self), _pv_cls, {name!r}))"
            if converter is None:
                lines.append(f"{ind}if not ({expr}){theirs}: _pv_report(self, name, value)")   # raises, or warns
            else:
                ns[f"_pv_conv_{i}"] = converter
                lines.append(f"{ind}if not ({expr}){theirs}:")
                lines.append(f"{ind}    _pv_out = _pv_conv_{i}(value)")
                lines.append(f"{ind}    if _pv_out is _pv_F: _pv_report(self, name, value)")   # raises, or warns
                lines.append(f"{ind}    else: value = _pv_out")
            keyword = "elif"
        lines.append("    _pv_orig(self, name, value)")
        exec(compile("\n".join(lines), f"<enforced __setattr__ for {cls.__qualname__}>", "exec"), ns)
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

    #* Tiered, like a wrapper (see ``_environment.COMPILE_AFTER``): generating the function above
    #* takes 150 µs, and a class whose instances are assigned to a few times never earns that
    #* back. Until then each field has a test of its own, made when the field is first assigned.
    compile_after = _environment.COMPILE_AFTER
    assignments = 0
    #* name -> the test of that field, None (nothing to test) or False (everything goes to the reporter).
    tests: dict[str, Any] = {}
    self_fields: set[str] = set()
    resolved: dict[str, Any] | None = None

    def test_of(name: str) -> Any:
        nonlocal resolved
        if resolved is None:
            uses: dict[str, bool] = {}
            resolved = resolve_annotations(cls, cls, uses = uses)
            self_fields.update(uses)
        test: Any = None
        if name in resolved:
            spec = compile_spec(resolved[name], allow_subclass, name, deep, convert, coerce, resolver(cls, cls))
            if spec is SLOW:
                return False                                # an unresolved forward reference: asked again next time
            #* ``Self`` is the class of the instance: tested here for the dataclass's own instances only.
            test = predicate(spec)                         # type: ignore[arg-type]
        tests[name] = test
        return test

    def __setattr__(self: Any, name: str, value: Any) -> None:
        nonlocal assignments
        #* @no_type_check written above @dataclass marks the class after this was made: seen on first use.
        if impl is None and vars(cls).get("__no_type_check__"):
            if cls.__dict__.get("__setattr__") is __setattr__:
                type.__setattr__(cls, "__setattr__", original_setattr)
            original_setattr(self, name, value)
            return
        assignments += 1
        if assignments >= compile_after and ready():
            impl(self, name, value)                         # type: ignore[misc]  # ready() has just made it
            return
        if name in field_set and not (aside and type(self) is not cls and _governed_by_subclass(type(self), cls)):
            test = tests.get(name, tests)
            if test is tests:
                test = test_of(name)
            #* The reporter does what the generated function does for a value that fails: converts
            #* it, lets it through for a subclass that retyped the field, or raises.
            if test is not None and (test is False or (name in self_fields and type(self) is not cls) or not test(value)):
                value = report(self, name, value)
        original_setattr(self, name, value)

    cls.__setattr__ = _tag_setattr(__setattr__, original_setattr, step_aside)  # type: ignore[method-assign]

    if init is None:
        return None

    def mark() -> dict[str, Any] | None:
        return published if impl is not None else None      # not made yet: the fields are simply checked again

    return mark


def _tag_setattr(hook: Any, wraps: Any, step_aside: Callable[[], None]) -> Any:
    """Mark ``hook`` as a generated ``__setattr__`` (see ``plain_setattr``)."""
    setattr(hook, _WRAPS, wraps)
    setattr(hook, _STEP_ASIDE, step_aside)
    return hook


def plain_setattr(cls: type) -> Any:
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


def _retyped_below(tp: type, cls: type, name: str) -> bool:
    """
    Whether a class between ``tp`` and the checked dataclass ``cls`` was made a dataclass by the
    standard library and declares the field ``name`` itself:

        @enforced.dataclass
        class Base:
            x: int

        @dataclasses.dataclass
        class Child(Base):
            x: str = ""

    ``Child`` inherits the ``__setattr__`` of ``Base``, and with it the check of ``x`` as an
    ``int``, which refused every ``Child("a")`` (review finding 23). The field is ``Child``'s now,
    and a standard dataclass checks nothing: a value the base's test refuses is let through for it.
    The fields ``Child`` leaves as they are stay checked.
    """
    for klass in tp.__mro__:
        if klass is cls:
            return False
        own = vars(klass)
        if "__dataclass_fields__" in own and CHECKED not in own:
            try:
                if name in get_annotations(klass, format = Format.FORWARDREF):
                    return True
            except Exception:
                pass
    return False


def _governed_by_subclass(tp: type, cls: type) -> bool:
    """Whether a decorated subclass of ``cls`` comes before it in ``tp``'s MRO: its options apply to ``tp``'s instances."""
    for klass in tp.__mro__:
        if klass is cls:
            return False
        if CHECKED in vars(klass):
            return True
    return False


def unchecked_setattr(cls: type) -> None:
    """
    ``check_assignment=False`` below a base class that checks assignments: this class's instances
    skip that check, for the inherited fields as for its own.
    """
    plain = plain_setattr(cls)
    if plain is not cls.__setattr__:
        cls.__setattr__ = plain                                 # type: ignore[method-assign]
