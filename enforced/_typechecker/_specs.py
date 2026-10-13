"""From an annotation to a check: specs, predicates, converters, and the nodes of ``deep``."""
from . import _deep
from ._checks import CHECK_ERRORS, REFUSED
from ._container import (
    constraints_pass, excludes_bool, is_abstract, matches_class, SelfType, TypeContainer, TypeUnion,
    )
from ._errors import TypeCheckerError
from ._file_types import FileType
from ._lifetime import CACHE_LOCK, held, holds, make_room, not_cached
from ._type_conversion import build_converter, FAILED, is_model_class
from typing import Any, Callable, get_args, get_origin, Unpack
from types import GenericAlias


class _Slow:
    """Sentinel: this annotation can't be precompiled; use the full (slow) path."""
    __slots__ = ()


SLOW = _Slow()


def compile_spec(
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
    ``resolve`` reads a name left as a string inside the annotation (see ``resolver``).
    Returns ``_SLOW`` when the annotation can't be resolved.
    """
    if deep:
        node = deep_node(expected, allow_subclass, convert, coerce, resolve)
        if node is SLOW:
            return SLOW
        if node is not None:
            return ("pred", node.check)
    try:
        c = TypeContainer(None, key, None, expected)
    except TypeCheckerError:
        return SLOW
    spec = _container_spec(c, allow_subclass)
    if c._constraints is None or spec[0] == "pred" and spec[1] is always_false:
        return spec
    #* Annotated[int, check]: the type test, then the checks of the member the value belongs to.
    base = predicate(spec)
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
    refused = REFUSED                                   # where a refusal leaves its reason: see ``_checks.REFUSED``
    if kind == "isinstance" and len(checks) == 1:
        def check(v: Any) -> bool:
            if not isinstance(v, target):
                return False
            try:
                answer = first(v)
            except CHECK_ERRORS as e:
                refused[0], refused[1], refused[2], refused[3] = v, first, True, str(e)
                return False
            if answer:
                return True
            refused[0], refused[1], refused[2], refused[3] = v, first, False, answer
            return False
    elif kind == "nobool" and len(checks) == 1:
        def check(v: Any) -> bool:
            if not isinstance(v, target) or type(v) is bool:
                return False
            try:
                answer = first(v)
            except CHECK_ERRORS as e:
                refused[0], refused[1], refused[2], refused[3] = v, first, True, str(e)
                return False
            if answer:
                return True
            refused[0], refused[1], refused[2], refused[3] = v, first, False, answer
            return False
    else:
        def check(v: Any) -> bool:
            if not base(v):
                return False
            c = first
            try:
                for c in checks:
                    answer = c(v)
                    if not answer:
                        refused[0], refused[1], refused[2], refused[3] = v, c, False, answer
                        return False
            except CHECK_ERRORS as e:
                refused[0], refused[1], refused[2], refused[3] = v, c, True, str(e)
                return False
            return True
    #* Read by the deep checks: test all the item types at once, then run only the checks.
    check.type_spec, check.type_pred, check.checks = spec, base, checks     # type: ignore[attr-defined]
    return check


def _container_spec(c: TypeContainer, allow_subclass: bool) -> tuple:
    """The spec for an unpacked annotation, without its ``Annotated`` checks."""
    if c._is_never:
        return ("pred", always_false)
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
        other = predicate(_type_spec(c._other_types, allow_subclass))
        if other is None:
            return ("any",)                             # ... | Any: the Any member accepts everything

    if allowed is None:
        if other is None:
            return _class_spec(classes, allow_subclass)                 # type[X] on its own
        is_class = predicate(_class_spec(classes, allow_subclass))
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

    is_class = predicate(_class_spec(classes, allow_subclass))
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
    """The spec for a flattened type or TypeUnion (the plain-class part of ``compile_spec``)."""
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


def compile_converter(
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
        node = deep_node(expected, allow_subclass, convert, coerce, resolve)
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
    accept = predicate(compile_spec(expected, allow_subclass, key))     # type: ignore[arg-type]
    return build_converter(targets, convert, coerce, accept or (lambda v: True))


def predicate(spec: tuple) -> Callable[[Any], bool] | None:
    """Turn a spec from ``compile_spec`` into a ``value -> bool`` callable (``None`` = anything passes)."""
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
#* is also why some annotations are never put here (see the end of ``deep_node``). When the cache
#* is full its oldest entry makes room (``CACHE_LOCK``, as for ``_CODE_CACHE``).
_DEEP_NODES: dict[tuple, tuple[Any, Any]] = {}
_DEEP_NODES_MAX = 4096


def deep_node(expected: Any, allow_subclass: bool, convert: bool, coerce: bool,
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
        spec = compile_spec(annotation, allow_subclass)
        if spec is SLOW:
            return _deep.SLOW
        converter = compile_converter(annotation, allow_subclass, "?", convert, coerce)
        return _deep.Leaf(annotation, spec, predicate(spec), converter)     # type: ignore[arg-type]

    node = _deep.compile_node(expected, make_leaf, resolve)
    if node is _deep.SLOW:
        return SLOW                                    # not cached: retried once the name exists
    result = None if node.leaf else node                # type: ignore[union-attr]
    #* Not cached: an annotation made for one class (see ``made_for``), and one that names a class
    #* written inside a function. A node keeps its annotation, for messages, so its entry could
    #* never go by itself, and the class would stay with it.
    if id(expected) in not_cached or _names_local_class(expected):
        return result
    with CACHE_LOCK:
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


def always_false(_: Any) -> bool:
    return False


def unpacked_tuple(annotation: Any) -> Any:
    """The ``tuple[...]`` that ``*args: *tuple[...]`` (or ``Unpack[tuple[...]]``) unpacks; None for anything else."""
    if getattr(annotation, "__unpacked__", False) and get_origin(annotation) is tuple:
        return GenericAlias(tuple, get_args(annotation))        # tuple[int, str], made from its items
    if get_origin(annotation) is Unpack:
        inner = get_args(annotation)[0]
        if get_origin(inner) is tuple:
            return inner
    return None


def args_node(annotation: Any, allow_subclass: bool, convert: bool, coerce: bool, deep: bool,
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
        spec: Any = compile_spec(item, allow_subclass)
        if spec is SLOW:
            return SLOW
        return _deep.Leaf(item, spec, predicate(spec), compile_converter(item, allow_subclass, "?", convert, coerce))

    def node_for(item: Any) -> Any:
        node = deep_node(item, allow_subclass, convert, coerce, resolve) if deep else None
        return leaf(item) if node is None else node

    before, middle, after = laid
    nodes = [node_for(item) for item in before + after]
    run = None if middle is _deep.FIXED else node_for(middle)
    if run is SLOW or any(node is SLOW for node in nodes):
        return SLOW
    if run is None:
        return _deep.FixedTuple(annotation, leaf(tuple), nodes)
    return _deep.VariadicTuple(annotation, leaf(tuple), nodes[:len(before)], run, nodes[len(before):])
