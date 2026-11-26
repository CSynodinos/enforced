"""Type-checked drop-in for dataclasses.dataclass."""
from .. import _environment
from .._validator._annotations import UNCHECKED_FIELDS
from .._validator._class_rules import BASE_OPTIONS, enforce_members
from .._validator._errors import check_error_type, InvalidDataError, InvalidDataWarning, warns
from .._validator._text import break_trace_colouring, describe_origin
from .._colours import formatter
from .._validator._lifetime import frame_above
from .._validator._scope import remember_scope
from ._assignment import CHECKED, class_attribute, takes_assignments, unchecked_setattr, wrap_setattr
from ._init import check_defaults_once, check_factories, storing_init, wrap_init
from typing import Any, Callable, dataclass_transform, Literal, overload
from collections.abc import Iterable
from functools import partial
from .._compat import Format, get_annotations, standard_make_dataclass
import dataclasses


#* What ``check_methods`` never wraps: ``__init__`` and ``__setattr__`` have their own checks,
#* and ``__post_init__`` is called by ``__init__`` with the values it has checked.
_NOT_METHODS = frozenset({"__init__", "__post_init__", "__setattr__"})


#* What a static type checker is told. The class comes back as the class it was (not ``Any``), and
#* ``dataclass_transform`` says that it now behaves like a standard dataclass: ``__init__`` takes the
#* fields, ``frozen`` forbids assignment, ``field(...)`` describes a field. Without both, a decorated
#* class had no type at all in an editor: no completion, no errors, in every file that used it.
@overload
def dataclass[T](
    cls: type[T], /, *,
    init: bool = True, repr: bool = True, eq: bool = True, order: bool = False, unsafe_hash: bool = False,
    frozen: bool = False, match_args: bool = True, kw_only: bool = False, slots: bool = False,
    weakref_slot: bool = False, allow_subclass: bool = True, check_assignment: bool = True, convert: bool = True,
    coerce: bool = False, deep: bool = False, on_error: Literal["raise", "warn"] = "raise", check_methods: bool = True,
    check_return: bool = False, error: type[InvalidDataError] = InvalidDataError,
    warning: type[InvalidDataWarning] = InvalidDataWarning,
    ) -> type[T]: ...
@overload
def dataclass[T](
    cls: None = None, /, *,
    init: bool = True, repr: bool = True, eq: bool = True, order: bool = False, unsafe_hash: bool = False,
    frozen: bool = False, match_args: bool = True, kw_only: bool = False, slots: bool = False,
    weakref_slot: bool = False, allow_subclass: bool = True, check_assignment: bool = True, convert: bool = True,
    coerce: bool = False, deep: bool = False, on_error: Literal["raise", "warn"] = "raise", check_methods: bool = True,
    check_return: bool = False, error: type[InvalidDataError] = InvalidDataError,
    warning: type[InvalidDataWarning] = InvalidDataWarning,
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
    error: type[InvalidDataError] = InvalidDataError,
    warning: type[InvalidDataWarning] = InvalidDataWarning,
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
            or on assignment, is reported as a ``InvalidDataWarning`` and stored as it was given.
            A default that contradicts its annotation is raised all the same.
        check_methods (bool): Also check the methods the class defines, as ``enforce`` does for a
            plain class: their arguments on every call, the value given to a property's setter,
            and the special methods a caller hands values to (``__call__``, ``__getitem__`` ...).
            On by default. A method without annotations stays as it is, ``@enforce.exempt``
            leaves one alone, and a method with its own ``@validate`` keeps its own options.
            ``__post_init__`` is not wrapped (``__init__`` has checked what it is given), nor is
            anything ``dataclasses`` generates.
        check_return (bool): With ``check_methods``, also check what each method returns (and
            what a property's getter returns). Off by default.
        error (type): the class of every error the class's checks raise (construction, assignment,
            defaults, methods): ``InvalidDataError`` (default) or a subclass of it, a library's own.
            Its ``__init__`` is never run by enforced. What refuses the decorator itself stays an
            ``InvalidDataError``.
        warning (type): the class ``on_error = "warn"`` issues: ``InvalidDataWarning`` (default) or a
            subclass of it, a library's own. Its ``__init__`` is never run by enforced.
    """
    warn = warns(on_error, warning)
    error = check_error_type(error)                     # refused here, where it is written
    standard = partial(dataclasses.dataclass, init = init, repr = repr, eq = eq, order = order, unsafe_hash = unsafe_hash,
                       frozen = frozen, match_args = match_args, kw_only = kw_only, slots = slots, weakref_slot = weakref_slot)

    def wrap(cls: Any, frame: Any = None) -> Any:
        #* typing.no_type_check on the class: a standard dataclass, with nothing checked. On the class
        #* itself: the mark of a base class speaks for that base (see ``_own_type_hints``).
        #* The same with ENFORCED_VALIDATION_OFF=1: the class still has to become a dataclass.
        if _environment.VALIDATION_OFF or vars(cls).get("__no_type_check__"):
            return standard(cls)
        #* A class derived from Enforced has its methods checked already, with the class's own options,
        #* and as functions wrapped before ``dataclasses`` runs: with slots=True it would rebuild the class
        #* around them, and their ``super()`` and ``Self`` would point at the class it replaced.
        if getattr(cls, BASE_OPTIONS, None) is not None:
            raise InvalidDataError(
                break_trace_colouring + f"enforced.dataclass cannot make {describe_origin(cls)} a dataclass: it "
                "inherits from Enforced, which checks plain classes. "
                + formatter("Use enforced.dataclass alone: it checks the methods too", "bold_yellow")
                )
        #* A class defined inside a function: the local names its string annotations use are looked
        #* up now, where the decorator is written (it is called from there unless ``frame`` says so).
        local = "<locals>" in cls.__qualname__
        if local and frame is None:
            frame = frame_above()
        hooked = check_assignment and not frozen            # assignments go through a generated __setattr__
        #* What a default_factory returns never passes through __init__'s arguments. The assignment
        #* check sees it; where there is none (frozen, check_assignment=False) the factory is wrapped.
        bind_factories = restore_factories = None
        if init:
            bind_factories, restore_factories = check_factories(cls, hooked, allow_subclass, convert, coerce, deep, warn, error)
        #* Build the real dataclass first; with slots=True this returns a *new* class.
        try:
            cls = standard(cls)
        finally:
            if restore_factories is not None:
                restore_factories()
        if local:
            remember_scope(cls, frame)                     # on the finished class: slots=True made a new one
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
            mark = wrap_setattr(cls, allow_subclass, convert, coerce, deep, cls.__init__ if init and storing is None else None, warn, error)
        elif not frozen:
            unchecked_setattr(cls)
        setattr(cls, CHECKED, True)
        if init:
            wrap_init(cls, allow_subclass, convert, coerce, deep, mark, slots, storing, warn, error)
        elif not slots:                     # with slots, a default that no __init__ assigns never reaches an instance
            check_defaults_once(cls, allow_subclass, convert, coerce, deep, error)
        if check_methods:
            #* Last, and on the class ``dataclasses`` returned (with slots = True a new one). Not
            #* what is checked already or is called with checked values, and not a field: its
            #* default sits in the class under its name, and may be a function or a property.
            enforce_members(cls, allow_subclass, check_return, convert, coerce, deep, warn,
                            leave = _NOT_METHODS | set(cls.__dataclass_fields__), error = error)
        return cls

    #* @dataclass() with parentheses vs @dataclass without.
    if cls is None:
        return wrap

    return wrap(cls, frame_above() if "<locals>" in getattr(cls, "__qualname__", "") else None)


def make_dataclass(
    cls_name: str,
    fields: Iterable[str | tuple[str, Any] | tuple[str, Any, Any]],
    *,
    bases: tuple[type, ...] = (),
    namespace: dict[str, Any] | None = None,
    module: str | None = None,
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
    error: type[InvalidDataError] = InvalidDataError,
    warning: type[InvalidDataWarning] = InvalidDataWarning,
    ) -> type:
    """
    Same as ``dataclasses.make_dataclass``, but the class is made with ``enforced.dataclass``:
    its field types are enforced at runtime.

    ``fields`` is what the standard function takes: names, ``(name, type)`` or
    ``(name, type, dataclasses.field(...))``; a name alone is typed ``typing.Any``. Methods go in
    ``namespace``, and are checked like those of a decorated class (``check_methods``).

    The class belongs to the module that calls this, unless ``module`` names another: that is where
    an annotation written as a string is looked up, and where pickle finds the class.

    Every other option is that of ``dataclass``, whose docstring has the details.

    Example:

        >>> from enforced import make_dataclass
        ... Point = make_dataclass("Point", [("x", float), ("y", float, dataclasses.field(default = 0.0))])
        ... Point(1)    # 1 -> 1.0 (convert)
        Point(x=1.0, y=0.0)
        ... Point("a")  # InvalidDataError
    """
    #* The standard function names the module after the frame that calls it, which would be this
    #* one: string annotations would be looked up here, and pickle would look for the class here.
    if module is None:
        caller = frame_above()                          # None on a Python without frames: then "__main__", as there
        module = caller.f_globals.get("__name__", "__main__") if caller is not None else "__main__"
    warns(on_error, warning) # checks unknown on_error, and a warning class that isn't one
    check_error_type(error)                             # and an error class that isn't one
    # insert enforced.dataclass as the decorator instead of dataclasses.dataclass
    # partial prepares the enforced.dataclass decorator with the given options
    enforced_dataclass = partial(
        dataclass,
        allow_subclass = allow_subclass,
        check_assignment = check_assignment,
        convert = convert,
        coerce = coerce,
        deep = deep,
        on_error = on_error,
        check_methods = check_methods,
        check_return = check_return,
        error = error,
        warning = warning,
        )
    return standard_make_dataclass(
        cls_name = cls_name,
        fields = fields,
        bases = bases,
        namespace = namespace,
        module = module,
        init = init,
        repr = repr,
        eq = eq,
        order = order,
        unsafe_hash = unsafe_hash,
        frozen = frozen,
        match_args = match_args,
        kw_only = kw_only,
        slots = slots,
        weakref_slot = weakref_slot,
        decorator = enforced_dataclass,
        )


def _descriptor_fields(cls: type) -> frozenset[str]:
    """
    The fields whose class attribute is a descriptor that takes assignments (it has ``__set__``).
    The standard library hands the values of such a field to the descriptor, which stores what it
    likes, and reads the default from it. Its annotation names the descriptor class, not what the
    values are (``quantity: Conversion = Conversion(default = 100)``), so there is nothing to
    check the values against: they are left to the descriptor.
    """
    return frozenset(f.name for f in dataclasses.fields(cls) if takes_assignments(class_attribute(cls, f.name)))


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
