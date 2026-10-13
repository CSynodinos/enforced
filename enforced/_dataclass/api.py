"""Type-checked drop-in for dataclasses.dataclass."""
from .. import _environment
from .._typechecker._annotations import UNCHECKED_FIELDS
from .._typechecker._class_rules import enforce_members
from .._typechecker._errors import warns
from .._typechecker._scope import remember_scope
from ._assignment import CHECKED, unchecked_setattr, wrap_setattr
from ._init import check_defaults_once, check_factories, storing_init, wrap_init
from typing import Any, Callable, dataclass_transform, Literal, overload
from annotationlib import Format, get_annotations
from types import MemberDescriptorType
import dataclasses
import sys


#* What ``check_methods`` never wraps: ``__init__`` and ``__setattr__`` have their own checks,
#* and ``__post_init__`` is called by ``__init__`` with the values it has checked.
_NOT_METHODS = frozenset({"__init__", "__post_init__", "__setattr__"})


#* What a static type checker is told. The class comes back as the class it was (not ``Any``), and
#* ``dataclass_transform`` says that it now behaves like a standard dataclass: ``__init__`` takes the
#* fields, ``frozen`` forbids assignment, ``field(...)`` describes a field. Without both, a decorated
#* class had no type at all in an editor: no completion, no errors, in every file that used it.
@overload
def dataclass[T](
    cls: type[T], /, *, init: bool = ..., repr: bool = ..., eq: bool = ..., order: bool = ...,
    unsafe_hash: bool = ..., frozen: bool = ..., match_args: bool = ..., kw_only: bool = ..., slots: bool = ...,
    weakref_slot: bool = ..., allow_subclass: bool = ..., check_assignment: bool = ..., convert: bool = ...,
    coerce: bool = ..., deep: bool = ..., on_error: Literal["raise", "warn"] = ..., check_methods: bool = ...,
    check_return: bool = ...,
    ) -> type[T]: ...
@overload
def dataclass[T](
    cls: None = None, /, *, init: bool = ..., repr: bool = ..., eq: bool = ..., order: bool = ...,
    unsafe_hash: bool = ..., frozen: bool = ..., match_args: bool = ..., kw_only: bool = ..., slots: bool = ...,
    weakref_slot: bool = ..., allow_subclass: bool = ..., check_assignment: bool = ..., convert: bool = ...,
    coerce: bool = ..., deep: bool = ..., on_error: Literal["raise", "warn"] = ..., check_methods: bool = ...,
    check_return: bool = ...,
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
    on_error: Literal["raise", "warn"] = "raise",
    check_methods: bool = True,
    check_return: bool = False,
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
        on_error (str): ``"raise"`` (default), or ``"warn"``: a value that fails, on construction
            or on assignment, is reported as a ``TypeCheckerWarning`` and stored as it was given.
            A default that contradicts its annotation is raised all the same.
        check_methods (bool): Also check the methods the class defines, as ``enforce`` does for a
            plain class: their arguments on every call, the value given to a property's setter,
            and the special methods a caller hands values to (``__call__``, ``__getitem__`` ...).
            On by default. A method without annotations stays as it is, ``@skip_typecheck``
            leaves one alone, and a method with its own ``@typecheck`` keeps its own options.
            ``__post_init__`` is not wrapped (``__init__`` has checked what it is given), nor is
            anything ``dataclasses`` generates.
        check_return (bool): With ``check_methods``, also check what each method returns (and
            what a property's getter returns). Off by default.
    """
    warn = warns(on_error)

    def wrap(cls: Any, frame: Any = None) -> Any:
        #* typing.no_type_check on the class: a standard dataclass, with nothing checked. On the class
        #* itself: the mark of a base class speaks for that base (see ``_own_type_hints``).
        #* The same with ENFORCED_TYPECHECK_OFF=1: the class still has to become a dataclass.
        if _environment.TYPECHECK_OFF or vars(cls).get("__no_type_check__"):
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
            bind_factories, restore_factories = check_factories(cls, hooked, allow_subclass, convert, coerce, deep, warn)
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
            remember_scope(cls, frame, fields = True)      # on the finished class: slots=True made a new one
        unchecked = _descriptor_fields(cls)
        if getattr(cls, "__no_type_check__", None) is not None:     # a base class is marked, or one above it was
            unchecked |= _own_type_hints(cls)
        if unchecked:
            setattr(cls, UNCHECKED_FIELDS, unchecked)       # read wherever the annotations are (resolve_annotations)
        if bind_factories is not None:
            bind_factories(cls)
        mark = None
        storing = None
        if hooked:
            #* An __init__ of our own that stores what its wrapper has checked, past the assignment
            #* check: each field is checked once. Where that can't be had, the standard __init__
            #* assigns, and ``mark`` spares the fields whose check is a function call a second run.
            storing = storing_init(cls, slots) if init else None
            mark = wrap_setattr(cls, allow_subclass, convert, coerce, deep, cls.__init__ if init and storing is None else None, warn)
        elif not frozen:
            unchecked_setattr(cls)
        setattr(cls, CHECKED, True)
        if init:
            wrap_init(cls, allow_subclass, convert, coerce, deep, mark, slots, storing, warn)
        elif not slots:                     # with slots, a default that no __init__ assigns never reaches an instance
            check_defaults_once(cls, allow_subclass, convert, coerce, deep)
        if check_methods:
            #* Last, and on the class ``dataclasses`` returned (with slots = True a new one). Not
            #* what is checked already or is called with checked values, and not a field: its
            #* default sits in the class under its name, and may be a function or a property.
            enforce_members(cls, allow_subclass, check_return, convert, coerce, deep, warn,
                            leave = _NOT_METHODS | set(cls.__dataclass_fields__))
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


def _own_type_hints(cls: type) -> frozenset[str]:
    """
    ``cls`` is decorated below a class marked ``typing.no_type_check``. That mark says of the
    class it is written on that its annotations are no type hints, and of no other: not of its
    subclasses (the ``typing`` documentation). But ``typing.get_type_hints`` finds the mark by
    looking it up on the class, where a subclass inherits it, and returns nothing for the whole
    subclass: a dataclass below a marked class had no field checked, while the methods of an
    ``@enforce`` class below the same base were (review finding 35).

    So the decorated class says for itself that it is checked: ``__no_type_check__ = False``, its
    own, which is what ``typing`` then finds. Returned are the fields that stay unchecked: those
    whose annotation was written in a marked class and in none below it.
    """
    type.__setattr__(cls, "__no_type_check__", False)
    unhinted: set[str] = set()
    for klass in reversed(cls.__mro__[:-1]):
        try:
            written = get_annotations(klass, format = Format.FORWARDREF)
        except Exception:
            continue
        if vars(klass).get("__no_type_check__"):
            unhinted.update(written)
        else:
            unhinted.difference_update(written)
    return frozenset(unhinted)
