"""
Unreachable versions. A version is unreachable when every value its anchor takes is taken by an
earlier candidate, by one of them or by several together (``int``, ``str``, then ``int | str``).

``covers`` must be sound: it may answer "no" where the truth is "yes" (a dead version goes
unnoticed: it never runs), but never "yes" where it is "no" (a working version would be refused).
So each rule below says yes only with an argument, and anything they don't speak for is a no.
The rules read what the checker runs, the compiled deep nodes and the specs of their leaves, not
the annotation as written: ``Iterable[int]`` lets every iterator through unread, so it covers
``Iterator[str]``, which no reading of the annotations would say.

A later anchor is cut into *parts*, each of which must be covered by some earlier candidate:

    ("any",)                         every value
    ("class", C, exact, bools)       the instances of C (``exact``: of C itself, strict mode);
                                     ``bools``: True and False among them
    ("model", M, exact)              a TypeModel at the top of an anchor: its instances, and the
                                     raw values of its base type that ``clean`` accepts
    ("classof", X, exact)            ``type[X]``: the classes X and below it (``exact``: X alone)
    ("checked", parts, checks)       the values of those class parts that every check accepts
    ("value", v)                     one value: a Literal value, a member of an Enum, True, None
    ("node", N)                      what a deep node (``list[int]``, a TypedDict ...) takes
    ("opaque", why)                  something no rule speaks for: covered only by "any"

A finite class (bool, ``NoneType``, an Enum with members) is cut into its values, so that a value
part is answered exactly, by the earlier candidate's own test of it.
"""
from .._validator import _deep
from .._validator._checks import CHECK_ERRORS, metadata_checks
from .._validator._container import TypeContainer, excludes_bool, is_abstract
from .._validator._type_conversion import FAILED, is_value_model as is_model   # a Transform anchor takes instances only
from ._match import Anchor, members, type_only
from typing import Any, Literal, get_args, get_origin, is_protocol
import enum


ANY = ("any",)
Part = tuple[Any, ...]


# ── a later anchor, cut into parts ───────────────────────────────────────────

def parts_of(node: Any, allow_subclass: bool, top: bool, seen: frozenset[int] = frozenset()) -> list[Part]:
    """What ``node`` takes, as parts. ``top``: the anchor itself (where a TypeModel takes raw values)."""
    if isinstance(node, _deep.Guard):
        return parts_of(node.inner, allow_subclass, top, seen)
    if isinstance(node, _deep.Proxy):
        if id(node) in seen or node.target is None:
            return [("opaque", "a recursive alias")]
        return parts_of(node.target, allow_subclass, top, seen | {id(node)})
    if isinstance(node, _deep.UnionNode):
        return [part for member in node.members for part in parts_of(member, allow_subclass, top, seen)]
    if isinstance(node, _deep.Leaf):
        return _leaf_parts(node, allow_subclass, top)
    if isinstance(node, _STRUCTURES):
        return [("node", node)]
    return [("opaque", type(node).__name__)]


def _leaf_parts(leaf: Any, allow_subclass: bool, top: bool) -> list[Part]:
    if leaf.spec[0] == "any":
        return [ANY]
    try:
        c = TypeContainer(None, "?", None, leaf.annotation)
    except Exception:
        return [("opaque", "an annotation that can't be read")]
    if c._is_never:
        return []                                       # Never: no value at all (the check is always_false)
    parts: list[Part] = [("value", v) for _, v in _in_order(c._literal_values, leaf.annotation)]
    exact = not allow_subclass
    for target in members(c._type_arg):
        parts.append(("classof", target, exact) if isinstance(target, type) and type_only(target)
                     else ("opaque", "type[...] of a stand-in"))
    special = c._literal_values is not None or c._type_arg is not None
    other = c._other_types if special else c._expected_type
    if other is None:
        return parts
    if other is object:
        return [ANY]
    #* Over-stated where unsure (bools taken to be among them): a later anchor that takes more is
    #* harder to cover, which is the safe side.
    bools = not excludes_bool(other)
    plain: Any = other
    if c._constraints is not None:
        plain = c._plain_types
        for target, checks in c._constraints:
            parts += _checked(tuple(_class_part(t, allow_subclass, bools, False) for t in members(target)), checks)
    for cls in members(plain):
        parts += _cut(_class_part(cls, allow_subclass, bools, top))
    return parts


def _in_order(values: Any, annotation: Any) -> list[tuple[type, Any]]:
    """The Literal values of an annotation, in the order they are written (the set of them has none)."""
    if not values:
        return []
    written: list[Any] = []

    def walk(a: Any, depth: int) -> None:
        if get_origin(a) is Literal:
            written.extend(get_args(a))
        elif depth < 8:
            for inner in get_args(a):
                walk(inner, depth + 1)
    walk(annotation, 0)
    order: dict[tuple[type, Any], int] = {}
    for i, v in enumerate(written):
        try:
            order.setdefault((type(v), v), i)
        except TypeError:
            pass
    return sorted(values, key = lambda pair: order.get(pair, len(order)))


def _class_part(cls: Any, allow_subclass: bool, bools: bool, top: bool) -> Part:
    if not isinstance(cls, type):
        return ("opaque", "a stand-in class")
    if is_protocol(cls):
        return ("protocol", cls)                        # its instances are told by their attributes
    if not type_only(cls):
        return ("opaque", f"{cls.__qualname__}, told by its metaclass")
    exact = not allow_subclass and not is_abstract(cls)
    if top and is_model(cls):
        return ("model", cls, exact)
    has_bools = cls is bool if exact else (bools and _subclass(bool, cls))
    return ("class", cls, exact, has_bools)


def _finite(cls: type) -> "list[Any] | None":
    """The values of a class that has a known few, all of them; ``None`` for any other class."""
    if cls is bool:
        return [False, True]
    if cls is type(None):
        return [None]
    if isinstance(cls, enum.EnumType) and cls.__members__ and not issubclass(cls, enum.Flag):   # type: ignore[attr-defined]
        return list(cls.__members__.values())       # type: ignore[attr-defined]           # an Enum with members can have no subclass
    return None


def _cut(part: Part) -> list[Part]:
    """A class part of a finite class, as its values."""
    if part[0] == "class":
        _, cls, exact, has_bools = part
        values = _finite(cls)
        if values is not None:
            return [("value", v) for v in values if has_bools or type(v) is not bool]
    return [part]


def _checked(classes: tuple[Part, ...], checks: tuple[Any, ...]) -> list[Part]:
    """``Annotated[T, *checks]``: the values of T the checks accept; cut into values where T is finite."""
    found: list[Part] = []
    for part in classes:
        if part[0] != "class" or _finite(part[1]) is None:
            return [("checked", classes, checks)]
        for v in _cut(part):
            try:
                if all(check(v[1]) for check in checks):
                    found.append(v)
            except CHECK_ERRORS:
                pass                                    # refused, as the checker refuses it
            except Exception:
                return [("checked", classes, checks)]   # a check that breaks: no value is answered for
    return found


# ── whether an earlier node takes a part ─────────────────────────────────────

def covers_part(earlier: Any, part: Part, allow_subclass: bool, seen: set[tuple[int, int]]) -> bool:
    """Whether every value of ``part`` is taken by the node ``earlier``."""
    kind = part[0]
    if kind == "value":
        return _takes(earlier.check, part[1])
    if isinstance(earlier, _deep.Guard):
        return covers_part(earlier.inner, part, allow_subclass, seen)
    if isinstance(earlier, _deep.Proxy):
        return earlier.target is not None and covers_part(earlier.target, part, allow_subclass, seen)
    if isinstance(earlier, _deep.UnionNode):
        return any(covers_part(member, part, allow_subclass, seen) for member in earlier.members)
    if isinstance(earlier, _deep.Leaf):
        return _leaf_covers(earlier, part, allow_subclass, seen)
    if kind == "node":
        return _structure_covers(earlier, part[1], allow_subclass, seen)
    return False


def covers_node(earlier: Any, later: Any, allow_subclass: bool, seen: set[tuple[int, int]]) -> bool:
    """Whether every value the node ``later`` takes is taken by ``earlier`` (nested in a structure)."""
    key = (id(earlier), id(later))
    if key in seen:
        return True                                     # a recursive alias: assumed while its parts are compared
    seen.add(key)
    try:
        return all(covers_part(earlier, part, allow_subclass, seen) for part in parts_of(later, allow_subclass, False))
    finally:
        seen.discard(key)


def _takes(check: Any, value: Any) -> bool:
    try:
        return bool(check(value))
    except Exception:
        return False


class _Groups:
    """What a leaf takes, as the checker tests it: groups of classes, each with its checks, and ``type[X]`` targets."""
    __slots__ = ("anything", "groups", "classof")

    def __init__(self, leaf: Any) -> None:
        self.anything = leaf.spec[0] == "any"
        self.groups: list[tuple[tuple[Any, ...], tuple[Any, ...], bool]] = []   # (classes, checks, takes bools)
        self.classof: tuple[Any, ...] = ()
        if self.anything:
            return
        try:
            c = TypeContainer(None, "?", None, leaf.annotation)
        except Exception:
            return
        if c._is_never:
            return
        self.classof = members(c._type_arg)
        special = c._literal_values is not None or c._type_arg is not None
        other = c._other_types if special else c._expected_type
        if other is None:
            return
        #* Under-stated where unsure (bools refused when any test on the way refuses them): an
        #* earlier anchor that takes less covers less, which is the safe side.
        outer = not excludes_bool(other)
        if c._constraints is None:
            self.groups.append((members(other), (), outer))
            return
        if c._plain_types is not None:
            self.groups.append((members(c._plain_types), (), outer and not excludes_bool(c._plain_types)))
        for target, checks in c._constraints:
            self.groups.append((members(target), tuple(checks), outer and not excludes_bool(target)))


def _leaf_covers(earlier: Any, part: Part, allow_subclass: bool, seen: set[tuple[int, int]]) -> bool:
    groups = _Groups(earlier)
    if groups.anything:
        return True
    kind = part[0]
    if kind in ("class", "model", "protocol"):
        return any(not checks and _class_covered(classes, bools, part, allow_subclass)
                   for classes, checks, bools in groups.groups)
    if kind == "checked":
        _, classes_of, checks = part
        #* By the classes alone (a check only narrows), each class by some group without checks ...
        if all(any(not g_checks and _class_covered(g_classes, bools, p, allow_subclass)
                   for g_classes, g_checks, bools in groups.groups) for p in classes_of):
            return True
        #* ... or by a group whose checks are all among these, the same objects (a check can't be read).
        for g_classes, g_checks, bools in groups.groups:
            if g_checks and all(any(c is d for d in checks) for c in g_checks) and \
               all(_class_covered(g_classes, bools, p, allow_subclass) for p in classes_of):
                return True
        return False
    if kind == "classof":
        return _classof_covered(groups, part, allow_subclass)
    if kind == "node":
        later = part[1]
        if isinstance(later, _deep.Constrained):
            return covers_node(earlier, later.inner, allow_subclass, seen) or _leaf_covers(
                earlier, ("checked", _outer_class_parts(later.inner, allow_subclass), _checks_of(later)), allow_subclass, seen)
        #* A structure's values are instances of its outer class: what takes all of those takes them.
        outer = getattr(later, "outer", None)
        return outer is not None and covers_node(earlier, outer, allow_subclass, seen)
    return False


def _outer_class_parts(node: Any, allow_subclass: bool) -> tuple[Part, ...]:
    """The class parts of a structure's outer class (``list`` for ``list[int]``)."""
    outer = getattr(node, "outer", None)
    if outer is None:
        return (("opaque", "no outer class"),)
    return tuple(parts_of(outer, allow_subclass, False))


def _class_covered(classes: tuple[Any, ...], takes_bools: bool, part: Part, allow_subclass: bool) -> bool:
    """Whether the instances ``part`` stands for are all instances of one of ``classes``, as the checker tests them."""
    kind = part[0]
    if kind == "model":
        _, model, exact = part
        #* Its instances, and the raw values of its base type (never a bool, whatever the base).
        return (_class_covered(classes, takes_bools, ("class", model, exact, False), allow_subclass)
                and _class_covered(classes, takes_bools, ("class", model.__base_type__, False, False), allow_subclass))
    if kind == "protocol":
        #* Told by attributes: taken only by a Protocol it derives from (which asks for fewer of them).
        later = part[1]
        return any(isinstance(p, type) and is_protocol(p) and p in later.__mro__ for p in classes)
    if kind != "class":
        return False
    _, cls, exact, has_bools = part
    for p in classes:
        if not isinstance(p, type):
            continue
        if is_protocol(p):
            #* A class that derives from a runtime Protocol of methods only has them all (it inherits
            #* them), so its instances pass. A data member may be missing on an instance: no answer.
            if p in cls.__mro__ and not getattr(p, "__non_callable_proto_members__", True):
                return True
            continue
        if not type_only(p):
            continue
        if allow_subclass:
            if _subclass(cls, p) and (takes_bools or not has_bools):
                return True
        elif is_abstract(p):                            # strict, yet tested with isinstance
            if _subclass(cls, p):
                return True
        elif exact and cls is p:
            return True
    return False


def _classof_covered(groups: _Groups, part: Part, allow_subclass: bool) -> bool:
    _, target, exact = part
    for y in groups.classof:
        if not isinstance(y, type) or not type_only(y):
            continue
        if allow_subclass and _subclass(target, y):
            return True
        if not allow_subclass and (y is target or y is object):
            return True
    #* Classes are instances of their metaclass, and a subclass's metaclass derives from it.
    meta = type(target)
    for classes, checks, bools in groups.groups:
        if checks:
            continue
        for p in classes:
            if not isinstance(p, type) or not type_only(p):
                continue
            if allow_subclass or is_abstract(p):
                if _subclass(meta, p) and (target is not object or _subclass(type, p)):
                    return True
            elif exact and meta is p and target is not object:
                return True
    return False


def _subclass(cls: Any, base: Any) -> bool:
    try:
        return issubclass(cls, base)
    except TypeError:
        return False


def _checks_of(node: Any) -> tuple[Any, ...]:
    return tuple(metadata_checks(get_args(node.annotation)[1:]))


# ── structure against structure ──────────────────────────────────────────────

_STRUCTURES = (_deep.Constrained, _deep.Items, _deep.FixedTuple, _deep.VariadicTuple, _deep.Mapping,
               _deep.TypedDictNode, _deep.NamedTupleNode)


def _structure_covers(earlier: Any, later: Any, allow_subclass: bool, seen: set[tuple[int, int]]) -> bool:
    a = allow_subclass
    while isinstance(later, (_deep.Guard, _deep.Proxy)):
        later = later.inner if isinstance(later, _deep.Guard) else later.target
        if later is None:
            return False
    if isinstance(later, _deep.Constrained):
        if isinstance(earlier, _deep.Constrained):
            mine, theirs = _checks_of(earlier), _checks_of(later)
            if all(any(c is d for d in theirs) for c in mine) and covers_node(earlier.inner, later.inner, a, seen):
                return True
        return covers_node(earlier, later.inner, a, seen)           # its values are values of what it narrows
    if isinstance(earlier, _deep.Constrained):
        return False
    if not covers_node(earlier.outer, later.outer, a, seen):
        return False
    if isinstance(earlier, _deep.Items):
        if isinstance(later, _deep.Items):
            return covers_node(earlier.item, later.item, a, seen)
        if isinstance(later, (_deep.FixedTuple, _deep.VariadicTuple)):
            run = _tuple_shape(later)
            return all(covers_node(earlier.item, n, a, seen) for n in [*run[0], *([run[1]] if run[1] else []), *run[2]])
        return False
    if isinstance(earlier, (_deep.FixedTuple, _deep.VariadicTuple)):
        if isinstance(later, (_deep.FixedTuple, _deep.VariadicTuple, _deep.Items)):
            return _tuple_covers(_tuple_shape(earlier), _tuple_shape(later), a, seen)
        return False
    if isinstance(earlier, _deep.Mapping):
        return (isinstance(later, _deep.Mapping) and covers_node(earlier.key, later.key, a, seen)
                and covers_node(earlier.value, later.value, a, seen))
    if isinstance(earlier, _deep.TypedDictNode):
        if not isinstance(later, _deep.TypedDictNode) or not earlier.required <= later.required:
            return False
        for key, field in earlier.fields.items():
            if isinstance(field, _deep.Leaf) and field.pred is None:
                continue                                # any value: nothing to cover
            theirs_field = later.fields.get(key)
            #* A key the later TypedDict doesn't name may hold anything there, and this one checks it.
            if theirs_field is None or not covers_node(field, theirs_field, a, seen):
                return False
        return True
    if isinstance(earlier, _deep.NamedTupleNode):
        return (isinstance(later, _deep.NamedTupleNode) and len(earlier.fields) == len(later.fields)
                and all(covers_node(e, n, a, seen) for (_, e), (_, n) in zip(earlier.fields, later.fields)))
    return False


def _tuple_shape(node: Any) -> tuple[list[Any], Any, list[Any]]:
    """A tuple node as ``(fixed at the start, the run between or None, fixed at the end)``."""
    if isinstance(node, _deep.FixedTuple):
        return list(node.items), None, []
    if isinstance(node, _deep.VariadicTuple):
        return list(node.before), node.middle, list(node.after)
    return [], node.item, []                            # Items: tuple[T, ...]


def _tuple_covers(earlier: tuple[list[Any], Any, list[Any]], later: tuple[list[Any], Any, list[Any]], a: bool,
                  seen: set[tuple[int, int]]) -> bool:
    (b1, m1, a1), (b2, m2, a2) = earlier, later
    if m1 is None:                                      # a fixed length: the later one must be that length
        return (m2 is None and not a2 and len(b2) == len(b1)
                and all(covers_node(e, n, a, seen) for e, n in zip(b1, b2)))
    #* A run between: every later value is at least as long as the earlier's fixed ends, so its first
    #* items meet the earlier start, its last ones the earlier end, and what is between the run.
    if m2 is None:
        items = b2 + a2
        if len(items) < len(b1) + len(a1):
            return False
        head, tail = items[:len(b1)], items[len(items) - len(a1):] if a1 else []
        body = items[len(b1):len(items) - len(a1)]
        return (all(covers_node(e, n, a, seen) for e, n in zip(b1, head))
                and all(covers_node(e, n, a, seen) for e, n in zip(a1, tail))
                and all(covers_node(m1, n, a, seen) for n in body))
    if len(b2) < len(b1) or len(a2) < len(a1):
        return False
    return (all(covers_node(e, n, a, seen) for e, n in zip(b1, b2))
            and all(covers_node(m1, n, a, seen) for n in b2[len(b1):])
            and covers_node(m1, m2, a, seen)
            and all(covers_node(m1, n, a, seen) for n in a2[:len(a2) - len(a1)])
            and all(covers_node(e, n, a, seen) for e, n in zip(a1, a2[len(a2) - len(a1):])))


# ── a version against the candidates before it ───────────────────────────────

def what_covers(later: Anchor, earlier: "list[Anchor]", allow_subclass: bool) -> "list[tuple[Part, int]] | None":
    """
    For an anchor that can never be chosen after ``earlier``, each of its parts with the index of an
    earlier anchor that takes it (an empty list: it takes no value at all); ``None`` when some value
    of it reaches it.
    """
    found: list[tuple[Part, int]] = []
    for part in parts_of(later.node, allow_subclass, True):
        for index, anchor in enumerate(earlier):
            if _anchor_covers(anchor, part, allow_subclass):
                found.append((part, index))
                break
        else:
            return None
    return found


def _anchor_covers(anchor: Anchor, part: Part, allow_subclass: bool) -> bool:
    try:
        if part[0] == "value":
            return _takes(lambda v: anchor.take(v) is not FAILED, part[1])
        if part[0] == "model" and part[1] in anchor.models:
            return True                                 # the same model: the same clean
        return covers_part(anchor.node, part, allow_subclass, set())
    except Exception:                                   # a class or a check that breaks the question: no answer
        return False

