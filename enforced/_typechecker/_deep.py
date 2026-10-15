"""
Deep checks: the items inside collections, at every depth (opt-in with ``deep=True``).

An annotation is compiled once into a tree of nodes. Every node answers three questions:

    check(value)        -> bool        is the value valid all the way down?
    convert(value)      -> value'      a valid equivalent (new containers where items changed),
                                        or FAILED
    errors(value, path) -> [issue]     what is wrong, with a path to each bad item
                                        ("scores[3]", "prices['apple']", "point.x")

``check`` is the hot path. Each node's ``check`` is a small function generated for its exact
shape (``isinstance(v, list) and _items(v)``, ``... and isinstance(v[0], int) and ...``), and the
items of plain classes are checked in one C-level pass over their *types*
(``set(map(type, items))``) instead of one Python call per item.

What is checked (like pydantic):
    list[T], set[T], frozenset[T], deque[T]           every item
    Sequence[T], MutableSequence[T], Set[T], ...      every item (collections.abc)
    tuple[A, B], tuple[T, ...], tuple[()]             every position, and the length
    tuple[A, *tuple[T, ...], B]                       the fixed positions at both ends, and every item between
    dict[K, V], Mapping[K, V], OrderedDict, ...       every key and every value
    TypedDict                                          required keys present, every value
    NamedTuple                                         every field
    unions, Optional, Annotated, NewType, aliases      followed through, including recursive aliases

Not checked (checking would consume them): Iterable[T], Iterator[T], Generator, async iterators.

An issue is a tuple ``(kind, path, value, annotation, detail)``:
    ("type", path, value, annotation, None)            wrong type at ``path``
    ("length", path, value, annotation, n)             a fixed tuple with the wrong length
    ("missing_key", path, mapping, annotation, key)    a required TypedDict key is absent
    ("cycle", path, value, annotation, None)           data that contains itself (recursive alias)
    ("invalid", path, value, annotation, reason)       no single item is to blame: keys that collide after
                                                       conversion, a container that can't be rebuilt
"""
from ._type_conversion import FAILED
from ._checks import CHECK_ERRORS, metadata_checks
from ._record_strings import read_annotation
from ._container import typevar_types
from typing import (
    Annotated, Any, Callable, ClassVar, Final, ForwardRef, NotRequired, ReadOnly, Required, TypeAliasType, TypeVar,
    Union, Unpack, get_args, get_origin, get_type_hints, is_typeddict,
    )
from types import UnionType
from itertools import chain, compress
from operator import eq, is_, not_
import collections
import collections.abc as abc
import copy
import dataclasses


type Issue = tuple[str, str, Any, Any, Any]

#* Containers whose items are each checked against one annotation.
_ITEM_ORIGINS = frozenset({
    list, set, frozenset, collections.deque,
    abc.Sequence, abc.MutableSequence, abc.Set, abc.MutableSet, abc.Collection,
    })
#* Containers whose keys and values are checked.
_MAPPING_ORIGINS = frozenset({
    dict, collections.OrderedDict, collections.defaultdict, collections.Counter, collections.ChainMap,
    abc.Mapping, abc.MutableMapping,
    })


def _true(_: Any) -> bool:
    return True


# ── code generation for check() ──────────────────────────────────────────────

def _bind(ns: dict[str, Any], obj: Any) -> str:
    """Put ``obj`` into the generated function's namespace under a fresh name."""
    name = f"_n{len(ns)}"
    ns[name] = obj
    return name


def _expr(node: "Node", var: str, ns: dict[str, Any]) -> str:
    """Python source testing ``var`` against ``node`` ("True" when anything passes)."""
    if isinstance(node, Leaf):
        kind = node.spec[0]
        if kind == "any":
            return "True"
        name = _bind(ns, node.spec[1])
        if kind == "isinstance":
            return f"isinstance({var}, {name})"
        if kind == "nobool":
            return f"(isinstance({var}, {name}) and type({var}) is not bool)"
        if kind == "is":
            return f"type({var}) is {name}"
        if kind == "in":
            return f"type({var}) in {name}"
        return f"{name}({var})"                         # "pred"
    return f"{_bind(ns, node.check)}({var})"            # a Proxy's bound check follows its target at call time


def _function(parts: list[str], ns: dict[str, Any]) -> Callable[[Any], bool]:
    """``def check(v): return <part> and <part> ...``"""
    parts = [p for p in parts if p != "True"] or ["True"]
    exec(compile(f"def check(v):\n    return {' and '.join(parts)}\n", "<enforced deep check>", "exec"), ns)
    return ns["check"]


# ── nodes ────────────────────────────────────────────────────────────────────

class Node:
    """Base class. A ``leaf`` is what the shallow checker already does."""
    leaf = False
    #* Whether what ``convert`` returns (when it isn't FAILED) always passes ``check``, so that the
    #* converter needs no second test of it (``_specs.deep_converter``). True only where it is
    #* shown below: a leaf, and a list or a TypedDict made of sound nodes. Everything else (a union,
    #* a mapping, a tuple, an Annotated container, a recursive alias) is tested again.
    sound = False
    _stop: "tuple[int, int] | None" = None             # where the last conversion of items stopped (``_stopped``)
    can_convert = False                                 # whether convert() could ever change a value
    annotation: Any = None

    def check(self, v: Any) -> bool: raise NotImplementedError
    def convert(self, v: Any) -> Any: raise NotImplementedError

    def fix(self, v: Any) -> Any:
        """``convert`` for a value that has just failed ``check`` (a leaf skips testing it again)."""
        return self.convert(v)
    def errors(self, v: Any, path: str) -> list[Issue]: raise NotImplementedError

    def shape_ok(self, v: Any) -> bool:
        """Does the outer type fit? (Picks the union member whose errors are reported.)"""
        return self.check(v)


class Leaf(Node):
    """A shallow check: ``spec``/``pred`` from the type checker's compiler, ``conv`` from its converter."""
    leaf = True

    def __init__(self, annotation: Any, spec: tuple, pred: Callable[[Any], bool] | None,
                 conv: Callable[[Any], Any] | None) -> None:
        self.annotation, self.spec, self.pred, self.conv = annotation, spec, pred, conv
        self.can_convert = conv is not None
        self.check = pred if pred is not None else _true            # type: ignore[assignment, method-assign]
        self.batch = _batch_check(spec, pred)
        #* ``conv`` accepts only what passes the same spec (``compile_converter``'s ``accept``).
        self.sound = True

    def convert(self, v: Any) -> Any:
        if self.check(v):
            return v
        return self.conv(v) if self.conv is not None else FAILED

    def fix(self, v: Any) -> Any:
        """``convert`` for a value the caller has just seen fail ``check``: not tested a second time."""
        return self.conv(v) if self.conv is not None else FAILED

    def errors(self, v: Any, path: str) -> list[Issue]:
        return [("type", path, v, self.annotation, None)] if _bad(self, v) else []


def _batch_check(spec: tuple, pred: Callable[[Any], bool] | None) -> Callable[[Any], bool] | None:
    """``items -> bool`` for many values at once (``None`` = anything passes)."""
    if pred is None:
        return None
    type_spec = getattr(pred, "type_spec", None)
    if type_spec is not None:                           # Annotated[int, check]: types in bulk, then the checks
        type_batch = _batch_check(type_spec, pred.type_pred)                # type: ignore[attr-defined]
        passes = tuple(_check_pass(check) for check in pred.checks)         # type: ignore[attr-defined]

        def constrained(items: Any) -> bool:
            """``items`` is read once per pass, so it must be a container, not an iterator."""
            if type_batch is not None and not type_batch(items):
                return False
            for one_pass in passes:
                if not one_pass(items):
                    return False
            return True
        #* Read by _items_expr, which gives every pass its own iterator over the items.
        constrained.passes = (type_batch, *passes)      # type: ignore[attr-defined]
        return constrained
    kind = spec[0]
    if kind in ("isinstance", "nobool"):
        targets = spec[1]
        no_bool = kind == "nobool"
        if all(_plain_metaclass(type(t)) for t in (targets if isinstance(targets, tuple) else (targets,))):
            #* Plain classes: one C-level pass over the item types, then a cached subclass test.
            known: set[type] = set()                    # item types already found to be fine
            rejected: set[type] = set()                 # plain item types already found to fail

            def batch(items: Any, types: set[type] | None = None) -> bool:
                if types is None:
                    types = set(map(type, items))
                if types <= known:
                    return True
                ok = True
                for t in types - known:
                    if t in rejected:
                        ok = False
                    elif issubclass(t, targets) and not (no_bool and t is bool):
                        if len(known) < 64:
                            known.add(t)                # learnt even when another type fails (see _suspects)
                    elif _plain_class(t):
                        if len(rejected) < 64:
                            rejected.add(t)
                        ok = False
                    else:                               # isinstance() can pass by faking __class__ (proxies, mocks)
                        return all(map(pred, items))
                return ok
            batch.known = known                         # type: ignore[attr-defined]  # inlined by _items_expr
            return batch
    elif kind in ("is", "in"):
        allowed = frozenset({spec[1]}) if kind == "is" else spec[1]

        def exact(items: Any) -> bool:
            return set(map(type, items)) <= allowed
        exact.allowed = allowed                         # type: ignore[attr-defined]
        return exact
    return lambda items: all(map(pred, items))


def _plain_metaclass(meta: type) -> bool:
    """
    Whether classes of this metaclass answer ``isinstance`` the way ``type`` does: by the class of
    the value alone. True for ``type`` itself and for a metaclass that leaves both checks as they
    are (a TypeModel's); not for ABCMeta, where a class can be registered.
    """
    return meta is type or (meta.__instancecheck__ is type.__instancecheck__ and meta.__subclasscheck__ is type.__subclasscheck__)


def _check_pass(check: Callable[[Any], Any]) -> Callable[[Any], bool]:
    """``items -> bool``: one ``Annotated`` check over every item (a check may also reject by raising)."""
    def one_pass(items: Any) -> bool:
        try:
            return all(map(check, items))
        except CHECK_ERRORS:
            return False
    return one_pass


def _plain_class(t: type) -> bool:
    """No class in ``t``'s MRO overrides ``__class__``, so ``isinstance`` is decided by ``type(x)`` alone."""
    return not any("__class__" in vars(base) for base in t.__mro__[:-1])


def _suspects(node: "Node", values: Any) -> Any:
    """
    ``(index, value)`` pairs that may fail ``node`` (callers confirm each with ``_bad``). For
    plain classes the good items are skipped at C speed, so finding one bad item among a
    million costs about as much as checking them.
    """
    if isinstance(node, Leaf) and node.batch is not None:
        batch = node.batch
        good = getattr(batch, "known", None)
        if good is not None:
            if not good:
                batch(values)                               # learn the good types (unknown ones are only suspects)
        else:
            good = getattr(batch, "allowed", None)
        if good is not None:
            flags = map(not_, map(good.__contains__, map(type, values)))
            if isinstance(values, (list, tuple)):          # indices only: no tuple per good item
                return ((i, values[i]) for i in compress(range(len(values)), flags))
            return compress(enumerate(values), flags)
    return enumerate(values)


#* The numeric tower in bulk: items of exactly these types convert with one C-level map.
_TOWER = {float: frozenset({int, float}), complex: frozenset({int, float, complex})}


def _fix_all(node: "Node", values: Any) -> list[Any] | None:
    """Every value made valid for ``node`` (converted where needed), or ``None`` if one can't be."""
    out: list[Any] = []
    append = out.append
    if isinstance(node, Leaf):                          # the common case, without per-item method calls
        check, conv = node.check, node.conv
        target = node.spec[1] if node.spec[0] in ("isinstance", "is") else None
        if conv is not None and target in _TOWER and set(map(type, values)) <= _TOWER[target]:
            try:
                bulk = list(map(target, values))        # type: ignore[arg-type]  # 1 -> 1.0; floats come back unchanged
            except OverflowError:
                bulk = None
            if bulk is not None and all(map(eq, bulk, values)):     # exact (2**53 + 1 isn't; NaN takes the slow path)
                return bulk
        if conv is None:
            return out if all(map(check, values)) else None    # nothing converts: only "already valid" works
        for x in values:
            if not check(x):
                x = conv(x)
                if x is FAILED:
                    _stopped(node, values, len(out))
                    return None
            append(x)
        return out
    check, fix = node.check, node.fix
    if type(node) is TypedDictNode:
        #* A TypedDict's own conversion tests each field, and hands back the very dict when every
        #* one is valid: testing the whole row first is a second test of every field of a row
        #* that has to be converted (the rows of an import), and saves nothing on one that doesn't.
        convert = node.convert
        for x in values:
            x = convert(x)
            if x is FAILED:
                _stopped(node, values, len(out))
                return None
            append(x)
        return out
    for x in values:
        if not check(x):
            x = fix(x)
            if x is FAILED:
                _stopped(node, values, len(out))
                return None
        append(x)
    return out


#* Where ``_fix_all`` last stopped for a node, kept on the node (``_stop``): the id of the items
#* and the index of the item that couldn't be made valid. Every item before it was valid or
#* converted, so the errors looked for next, for the same items, start there (``_start_of``): a
#* bad row among 50 had every row converted a second time, the 37 good ones before it included.
#* Read once. On the node, so that two parameters don't overwrite each other's; the id, not the
#* items, so that nothing of the caller's is kept. Errors are only looked for right after a
#* conversion of the same value was tried (a node that can't convert sets nothing), so the entry
#* is that conversion's.


def _stopped(node: "Node", values: Any, index: int) -> None:
    node._stop = (id(values), index)


def _start_of(node: "Node", values: Any) -> int:
    stop = node._stop
    if stop is not None and stop[0] == id(values):
        node._stop = None
        return stop[1]
    return 0


def _items_expr(node: "Node", var: str, ns: dict[str, Any]) -> str:
    """
    Python source testing every item of ``var`` against ``node`` ("True" = anything passes).

    Items that are themselves collections (``list[list[int]]``, ``dict[str, list[int]]``) are
    checked a level at a time: first every inner container's type, then every inner item,
    through one chained pass, instead of one call per inner container.

    ``var`` is source as well, and for nested items it builds an iterator that can be read only
    once. So ``var`` is written out again for every pass over the items: each gets its own.
    """
    if type(node) is Items and isinstance(node.outer, Leaf) and node.outer.batch is not None:
        inner = f"{_bind(ns, chain.from_iterable)}({var})"
        return f"({_items_expr(node.outer, var, ns)} and {_items_expr(node.item, inner, ns)})"
    if not isinstance(node, Leaf):
        return f"all(map({_bind(ns, node.check)}, {var}))"
    return _batch_expr(node.batch, var, ns)


def _batch_expr(batch: Callable[[Any], bool] | None, var: str, ns: dict[str, Any]) -> str:
    """Source for one batch check (from ``_batch_check``) over the items ``var``."""
    if batch is None:
        return "True"
    if (passes := getattr(batch, "passes", None)) is not None:
        #* Annotated[T, check]: the types, then one pass per check. Sharing one iterator would leave
        #* every pass after the first with nothing to read, and "all of nothing" is True.
        parts = [_batch_expr(one_pass, var, ns) for one_pass in passes]
        return f"({' and '.join(p for p in parts if p != 'True') or 'True'})"
    if (known := getattr(batch, "known", None)) is not None:
        types = f"_t{len(ns)}"
        return f"(({types} := set(map(type, {var}))) <= {_bind(ns, known)} or {_bind(ns, batch)}({var}, {types}))"
    if (allowed := getattr(batch, "allowed", None)) is not None:
        return f"set(map(type, {var})) <= {_bind(ns, allowed)}"
    return f"{_bind(ns, batch)}({var})"


def _bad(node: Node, v: Any) -> bool:
    """Neither valid nor convertible: only these are reported (a convertible item isn't an error)."""
    if node.check(v):
        return False
    try:
        return not node.can_convert or node.fix(v) is FAILED     # it has just failed the test above
    except Exception:
        return True


def _all(node: Node) -> Callable[[Any], bool] | None:
    """``items -> bool`` for a node (``None`` = anything passes)."""
    if isinstance(node, Leaf):
        return node.batch
    check = node.check
    return lambda items: all(map(check, items))


class Proxy(Node):
    """Stand-in for a recursive type alias while it is being compiled."""
    can_convert = True                                  # unknown while compiling: assume it can

    def __init__(self) -> None:
        self.target: Node | None = None

    def check(self, v: Any) -> bool: return self.target.check(v)                            # type: ignore[union-attr]
    def convert(self, v: Any) -> Any: return self.target.convert(v)                         # type: ignore[union-attr]
    def errors(self, v: Any, path: str) -> list[Issue]: return self.target.errors(v, path)  # type: ignore[union-attr]
    def shape_ok(self, v: Any) -> bool: return self.target.shape_ok(v)                      # type: ignore[union-attr]


class Guard(Node):
    """Root of a recursive alias: data that contains itself is reported instead of recursing forever."""

    def __init__(self, inner: Node) -> None:
        self.inner, self.annotation, self.can_convert = inner, inner.annotation, inner.can_convert
        check = inner.check

        def guarded(v: Any) -> bool:
            try:
                return check(v)
            except RecursionError:
                return False
        self.check = guarded                                        # type: ignore[assignment, method-assign]

    def convert(self, v: Any) -> Any:
        try:
            return self.inner.convert(v)
        except RecursionError:
            return FAILED

    def errors(self, v: Any, path: str) -> list[Issue]:
        try:
            issues = self.inner.errors(v, path)
        except RecursionError:
            issues = []
        return issues or [("cycle", path, v, self.annotation, None)]

    def shape_ok(self, v: Any) -> bool:
        return self.inner.shape_ok(v)


def _rebuild(original: Any, items: list[Any]) -> Any:
    """
    A container of ``original``'s own type holding ``items``, or FAILED when that type can't be
    built from them: the caller's value is never swapped for a list (the caller re-checks the result).
    """
    t = type(original)
    if t is list:
        return items                                    # made for this by every caller: no copy of it
    if t in (tuple, set, frozenset):
        return t(items)
    if t is collections.deque:
        return collections.deque(items, original.maxlen)
    if isinstance(original, tuple) and hasattr(t, "_make"):                         # a NamedTuple
        try:
            return t._make(items)
        except Exception:
            pass
    #* Text holds no converted items, and a mapping iterates over its keys alone (dict(items) would
    #* even "work" for keys that are pairs).
    if isinstance(original, (str, bytes, bytearray, abc.Mapping)):
        return FAILED
    try:
        out = t(items)
        #* The type must take an iterable *and* really hold these items: range(...) raises, while
        #* some constructors read their argument as a size or a shape.
        if isinstance(out, abc.Set) or (len(out) == len(items) and all(map(is_, out, items))):
            return out
    except Exception:
        pass
    return FAILED


def _rebuild_mapping(original: Any, keys: list[Any], values: list[Any]) -> Any:
    """
    A mapping of ``original``'s own type holding ``keys`` and ``values`` (those of ``original``, in
    its order, converted), or FAILED when that type can't be built from them.
    """
    t = type(original)
    if t is dict:
        return dict(zip(keys, values))
    pairs = list(zip(keys, values))
    if t is collections.defaultdict:
        return collections.defaultdict(original.default_factory, pairs)
    if t is collections.Counter:
        return collections.Counter(dict(pairs))
    if isinstance(original, collections.ChainMap):
        return _rebuild_chain(original, keys, values)
    try:
        return t(pairs)
    except Exception:
        return FAILED                                   # e.g. a mappingproxy: not swapped for a dict


def _rebuild_chain(original: Any, keys: list[Any], values: list[Any]) -> Any:
    """
    A ChainMap is several mappings looked up in turn. Each of them is rebuilt on its own, as its own
    type, so that the result has the same maps in the same order (they used to be merged into one
    dict). An entry that an earlier map hides was never looked at by the check: it keeps its value,
    and gets the same converted key as the entry that hides it, so that it stays hidden.
    """
    try:
        originals = list(original.keys())               # the order ``keys`` and ``values`` were read in
        new_key, new_value = dict(zip(originals, keys)), dict(zip(originals, values))
        seen: set[Any] = set()
        maps = []
        for one in original.maps:
            pairs = [(new_key[k], new_value[k] if k not in seen else v) for k, v in one.items()]
            seen.update(one.keys())
            rebuilt = _rebuild_mapping(one, [k for k, _ in pairs], [v for _, v in pairs])
            if rebuilt is FAILED:
                return FAILED
            maps.append(rebuilt)
        return type(original)(*maps)
    except Exception:
        return FAILED


def _copy_of(v: Any) -> Any:
    """A shallow copy of a dict that is still what ``v`` is (an OrderedDict, a defaultdict, your own subclass), or FAILED."""
    if type(v) is dict:
        return dict(v)
    try:
        out = copy.copy(v)
    except Exception:
        return FAILED
    return out if type(out) is type(v) and out is not v else FAILED


def _cannot_rebuild(v: Any) -> str:
    """The reason shown when a value needs converted items but its type can't be built from them."""
    return f"its items need converting, but a {type(v).__name__} cannot be rebuilt with the converted items"


def key_label(k: Any) -> str:
    """How a mapping key appears in a path: ``prices['apple']``."""
    try:
        text = repr(k)
    except Exception:
        text = f"<{type(k).__name__}>"
    return text if len(text) <= 30 else text[:27] + "..."


class Constrained(Node):
    """``Annotated[list[int], check]``: the items through ``inner``, then the checks on the whole value."""

    def __init__(self, annotation: Any, inner: Node, outer: Leaf) -> None:
        self.annotation, self.inner, self.outer = annotation, inner, outer
        self.can_convert = inner.can_convert
        inner_check, outer_check = inner.check, outer.check
        self.check = lambda v: inner_check(v) and outer_check(v)   # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return self.inner.shape_ok(v)

    def convert(self, v: Any) -> Any:
        out = self.inner.convert(v)
        return out if out is not FAILED and self.outer.check(out) else FAILED

    def errors(self, v: Any, path: str) -> list[Issue]:
        issues = self.inner.errors(v, path)
        if issues or self.outer.check(v):
            return issues
        return [("type", path, v, self.annotation, None)]


class Items(Node):
    """list / set / frozenset / deque / Sequence / Set / tuple[T, ...]: every item against one node."""

    def __init__(self, annotation: Any, outer: Leaf, item: Node) -> None:
        self.annotation, self.outer, self.item = annotation, outer, item
        self.items_ok = _all(item) or _true
        self.can_convert = outer.can_convert or item.can_convert
        #* A converted container is of the type it was (``_rebuild``), and holds valid items.
        self.sound = outer.sound and item.sound
        ns: dict[str, Any] = {}
        self.check = _function([_expr(outer, "v", ns), _items_expr(item, "v", ns)], ns)  # type: ignore[assignment, method-assign]
        if self.can_convert and isinstance(item, Leaf) and not (item.conv is not None and item.spec[0] in ("isinstance", "is")
                                                                 and item.spec[1] in _TOWER):
            self.convert = self._converter()                        # type: ignore[method-assign, assignment]

    def _converter(self) -> Callable[[Any], Any]:
        """
        ``convert``, written out for items that are leaves: each item tested inline, and converted
        where it fails. Half of what converting the two tags of an import's row cost was the general
        way's calls (``_fix_all`` and the test and conversion behind it). Lists of floats and complex
        numbers keep ``_fix_all``, which converts those in one C-level pass. The same steps: the outer
        type (converted where it can be), the very container back when every item is valid, else a
        container of its type holding the converted items, or FAILED at the first that can't be,
        noting where (``_stopped``).
        """
        item: Any = self.item                           # a Leaf: see __init__
        ns: dict[str, Any] = {"_F": FAILED, "_outer": self.outer, "_ok": self.items_ok, "_rebuild": _rebuild,
                              "_stopped": _stopped, "_item": item, "_conv": item.conv}
        test = _expr(item, "x", ns)
        lines = ["def convert(v):",
                 f"    if not ({_expr(self.outer, 'v', ns)}):",
                 "        v = _outer.convert(v)",
                 "        if v is _F: return _F",
                 "    if _ok(v): return v"]
        if item.conv is None:
            lines.append("    return _F")                                     # an item fails, and nothing converts it
        else:
            lines += ["    out = []",
                      "    append = out.append",
                      "    for x in v:",
                      f"        if not ({test}):",
                      "            x = _conv(x)",
                      "            if x is _F:",
                      "                _stopped(_item, v, len(out))",
                      "                return _F",
                      "        append(x)",
                      "    return _rebuild(v, out)"]
        exec(compile("\n".join(lines), "<enforced deep convert>", "exec"), ns)
        return ns["convert"]                                        # type: ignore[no-any-return]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v)

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v):
            v = self.outer.convert(v)                   # e.g. tuple -> list, with coerce=True
            if v is FAILED:
                return FAILED
        if self.items_ok(v):
            return v
        out = _fix_all(self.item, v)
        return FAILED if out is None else _rebuild(v, out)

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        item, issues = self.item, []
        start = _start_of(item, v)                      # what the conversion got past is valid
        if isinstance(item, Leaf):                      # inlined Leaf.errors / _bad: this loop can be long
            check, conv, annotation = item.check, item.conv, item.annotation
            for i, x in _suspects(item, v):
                if i >= start and not check(x) and (conv is None or conv(x) is FAILED):
                    issues.append(("type", f"{path}[{i}]", x, annotation, None))
            return issues or self._whole_value_issue(v, path)
        for i, x in _suspects(item, v):
            if i >= start and _bad(item, x):
                issues += item.errors(x, f"{path}[{i}]")
        return issues or self._whole_value_issue(v, path)

    def _whole_value_issue(self, v: Any, path: str) -> list[Issue]:
        """No single item is to blame: the items convert, but ``v``'s type can't hold the result."""
        if self.can_convert and not self.items_ok(v) and _rebuild(v, list(v)) is FAILED:
            return [("invalid", path, v, self.annotation, _cannot_rebuild(v))]
        return []


class FixedTuple(Node):
    """tuple[A, B, C] and tuple[()]: the length and each position."""

    def __init__(self, annotation: Any, outer: Leaf, items: list[Node]) -> None:
        self.annotation, self.outer, self.items, self.n = annotation, outer, items, len(items)
        self.can_convert = outer.can_convert or any(n.can_convert for n in items)
        ns: dict[str, Any] = {}
        parts = [_expr(outer, "v", ns), f"len(v) == {self.n}"]
        parts += [_expr(node, f"v[{i}]", ns) for i, node in enumerate(items)]
        self.check = _function(parts, ns)                           # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v) and len(v) == self.n

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v):
            v = self.outer.convert(v)
            if v is FAILED:
                return FAILED
        if len(v) != self.n:
            return FAILED
        out, changed = [], False
        for node, x in zip(self.items, v):
            if not node.check(x):
                x = node.fix(x)
                if x is FAILED:
                    return FAILED
                changed = True
            out.append(x)
        return _rebuild(v, out) if changed else v

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        if len(v) != self.n:
            return [("length", path, v, self.annotation, self.n)]
        issues: list[Issue] = []
        for i, (node, x) in enumerate(zip(self.items, v)):
            if _bad(node, x):
                issues += node.errors(x, f"{path}[{i}]")
        return issues


class VariadicTuple(Node):
    """
    ``tuple[A, *tuple[T, ...], B]``: fixed positions at the start and at the end, and any number of
    ``T`` between them. Also what ``*args: *tuple[A, *tuple[T, ...]]`` is checked as.
    """

    def __init__(self, annotation: Any, outer: Leaf, before: list[Node], middle: Node, after: list[Node]) -> None:
        self.annotation, self.outer, self.before, self.middle, self.after = annotation, outer, before, middle, after
        self.n = len(before) + len(after)                           # the fewest items there can be
        self.middle_ok = _all(middle) or _true
        self.can_convert = outer.can_convert or middle.can_convert or any(n.can_convert for n in before + after)
        ns: dict[str, Any] = {}
        first, last = len(before), len(after)
        self.run = slice(first, -last if last else None)            # where the items between the ends are
        parts = [_expr(outer, "v", ns), f"len(v) >= {self.n}"]
        parts += [_expr(node, f"v[{i}]", ns) for i, node in enumerate(before)]
        parts += [_expr(node, f"v[{i - last}]", ns) for i, node in enumerate(after)]
        parts.append(_items_expr(middle, f"v[{first}:{-last if last else ''}]", ns))
        self.check = _function(parts, ns)                           # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v) and len(v) >= self.n

    def _nodes(self, length: int) -> list[Node]:
        """The node of each position of a tuple of ``length`` items."""
        return self.before + [self.middle] * (length - self.n) + self.after

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v):
            v = self.outer.convert(v)
            if v is FAILED:
                return FAILED
        if len(v) < self.n:
            return FAILED
        out, changed = [], False
        for node, x in zip(self._nodes(len(v)), v):
            if not node.check(x):
                x = node.fix(x)
                if x is FAILED:
                    return FAILED
                changed = True
            out.append(x)
        return _rebuild(v, out) if changed else v

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        if len(v) < self.n:
            return [("length", path, v, self.annotation, f"at least {self.n}")]
        issues: list[Issue] = []
        for i, (node, x) in enumerate(zip(self._nodes(len(v)), v)):
            if _bad(node, x):
                issues += node.errors(x, f"{path}[{i}]")
        return issues


#* ``spread`` says of a tuple's items: no run of unknown length among them.
FIXED: Any = object()


def spread(args: tuple[Any, ...]) -> "tuple[list[Any], Any, list[Any]] | None":
    """
    The items of ``tuple[...]`` with what is unpacked among them laid out:
    ``(before, middle, after)``. ``middle`` is the annotation of a run of unknown length
    (``*tuple[str, ...]`` gives ``str``, ``*Ts`` gives ``Any``), or ``FIXED`` without one, where
    every item is in ``before`` (``*tuple[int, str]`` is simply two of them). ``None`` for what
    isn't understood, such as two runs.
    """
    before: list[Any] = []
    after: list[Any] = []
    middle: Any = FIXED
    for arg in args:
        run: Any = FIXED
        if getattr(arg, "__unpacked__", False) and get_origin(arg) is tuple:        # *tuple[...]
            inner = get_args(arg)
        elif get_origin(arg) is Unpack:                                             # Unpack[tuple[...]], *Ts
            packed = get_args(arg)[0]
            if get_origin(packed) is tuple:
                inner = get_args(packed)
            else:
                inner, run = (), Any                    # a TypeVarTuple: any number of anything
        else:
            (before if middle is FIXED else after).append(arg)
            continue
        if run is FIXED and len(inner) == 2 and inner[1] is Ellipsis:
            run = inner[0]
        if run is FIXED:                                # *tuple[int, str]: two more fixed items
            laid = spread(inner)
            if laid is None or laid[1] is not FIXED:
                return None
            (before if middle is FIXED else after).extend(laid[0])
        elif middle is not FIXED:
            return None                                 # a second run: where one ends can't be told
        else:
            middle = run
    return before, middle, after


class Mapping(Node):
    """dict / Mapping / OrderedDict / defaultdict / Counter ...: every key and every value."""

    def __init__(self, annotation: Any, outer: Leaf, key: Node, value: Node) -> None:
        self.annotation, self.outer, self.key, self.value = annotation, outer, key, value
        self.keys_ok = _all(key) or _true
        self.values_ok = _all(value) or _true
        self.can_convert = outer.can_convert or key.can_convert or value.can_convert
        ns: dict[str, Any] = {}
        parts = [_expr(outer, "v", ns), _items_expr(key, "v.keys()", ns), _items_expr(value, "v.values()", ns)]
        self.check = _function(parts, ns)                           # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v)

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v):
            v = self.outer.convert(v)
            if v is FAILED:
                return FAILED
        keys_ok, values_ok = self.keys_ok(v.keys()), self.values_ok(v.values())
        if keys_ok and values_ok:
            return v
        keys: list[Any] | None
        if keys_ok:
            keys = list(v.keys())
        else:
            keys = _fix_all(self.key, v.keys())
            #* '1' and 1 both become 1: rebuilding would silently drop an entry.
            if keys is None or len(set(keys)) != len(keys):
                return FAILED
        values = list(v.values()) if values_ok else _fix_all(self.value, v.values())
        if values is None:
            return FAILED
        return _rebuild_mapping(v, keys, values)

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        key, value = self.key, self.value
        #* Suspect positions among the keys and among the values, merged in dict order.
        keys, values = list(v.keys()), list(v.values())
        suspects = {i for i, _ in _suspects(key, keys)} | {i for i, _ in _suspects(value, values)}
        issues: list[Issue] = []
        for i in sorted(suspects):
            k, x = keys[i], values[i]
            if _bad(key, k):
                issues += key.errors(k, f"{path}[key {key_label(k)}]")
            if _bad(value, x):
                issues += value.errors(x, f"{path}[{key_label(k)}]")
        return issues or self._whole_value_issue(v, path, keys, values)

    def _whole_value_issue(self, v: Any, path: str, keys: list[Any], values: list[Any]) -> list[Issue]:
        """No single key or value is to blame: two keys convert to the same key, or ``v`` can't be rebuilt."""
        if not self.can_convert:
            return []
        keys_ok = self.keys_ok(keys)
        if not keys_ok:
            check, convert = self.key.check, self.key.convert
            seen: dict[Any, Any] = {}
            try:
                for k in keys:
                    new = k if check(k) else convert(k)
                    if new in seen:
                        reason = f"keys {key_label(seen[new])} and {key_label(k)} both convert to {key_label(new)}"
                        return [("invalid", path, v, self.annotation, reason)]
                    seen[new] = k
            except Exception:                           # an unhashable converted key, ...
                pass
        if not (keys_ok and self.values_ok(values)) and _rebuild_mapping(v, keys, values) is FAILED:
            return [("invalid", path, v, self.annotation, _cannot_rebuild(v))]
        return []


class TypedDictNode(Node):
    """A TypedDict: a dict with its required keys present and each known value of its declared type."""

    def __init__(self, annotation: Any, outer: Leaf, fields: dict[str, Node], hints: dict[str, Any],
                 required: frozenset[str]) -> None:
        self.annotation, self.outer, self.fields, self.hints, self.required = annotation, outer, fields, hints, required
        self.can_convert = any(n.can_convert for n in fields.values())
        #* A converted TypedDict is a copy of the same type, with its keys, and valid values.
        self.sound = outer.sound and all(n.sound for n in fields.values())
        ns: dict[str, Any] = {}
        parts = [_expr(outer, "v", ns)]
        if required:
            parts.append(f"{_bind(ns, required)} <= v.keys()")
        for k, node in fields.items():
            name = _bind(ns, k)
            expr = _expr(node, f"v[{name}]", ns)
            if expr != "True":
                parts.append(expr if k in required else f"({name} not in v or {expr})")
        self.check = _function(parts, ns)                           # type: ignore[assignment, method-assign]
        if self.can_convert:
            self.convert = self._converter()                        # type: ignore[method-assign, assignment]

    def _converter(self) -> Callable[[Any], Any]:
        """
        ``convert``, written out for this TypedDict: one test and one conversion per field, inline.
        The loop over the fields, a method call per test and per conversion and the lookups of the
        general ``convert`` cost half of what converting a row of an import did. The same steps, in
        the same order: the outer type and the required keys, then each field present that fails
        its test is converted, into a copy of the dict made at the first one.
        """
        ns: dict[str, Any] = {"_F": FAILED, "_copy": _copy_of}
        lines = ["def convert(v):"]
        outer = _expr(self.outer, "v", ns)
        lines.append(f"    if not ({outer}) or not ({_bind(ns, self.required)} <= v.keys()): return _F")
        lines.append("    out = None")
        for k, node in self.fields.items():
            name = _bind(ns, k)
            expr = _expr(node, "x", ns)
            if expr == "True":
                continue                                    # anything passes: nothing to convert
            ind = "    "
            if k not in self.required:
                lines.append(f"    if {name} in v:")
                ind += "    "
            lines.append(f"{ind}x = v[{name}]")
            lines.append(f"{ind}if not ({expr}):")
            if isinstance(node, Leaf):
                if node.conv is None:
                    lines.append(f"{ind}    return _F")         # nothing converts it
                    continue
                lines.append(f"{ind}    x = {_bind(ns, node.conv)}(x)")
            else:
                lines.append(f"{ind}    x = {_bind(ns, node.fix)}(x)")
            lines.append(f"{ind}    if x is _F: return _F")
            lines.append(f"{ind}    if out is None:")
            lines.append(f"{ind}        out = _copy(v)")
            lines.append(f"{ind}        if out is _F: return _F")
            lines.append(f"{ind}    out[{name}] = x")
        lines.append("    return v if out is None else out")
        exec(compile("\n".join(lines), "<enforced deep convert>", "exec"), ns)
        return ns["convert"]                                        # type: ignore[no-any-return]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v)

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v) or not self.required <= v.keys():
            return FAILED
        out = None
        for k, node in self.fields.items():
            if k in v and not node.check(v[k]):
                x = node.fix(v[k])
                if x is FAILED:
                    return FAILED
                if out is None:
                    out = _copy_of(v)
                    if out is FAILED:
                        return FAILED
                out[k] = x
        return v if out is None else out

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        issues: list[Issue] = []
        for k, node in self.fields.items():
            if k not in v:
                if k in self.required:
                    issues.append(("missing_key", f"{path}[{key_label(k)}]", v, self.hints[k], k))
            elif _bad(node, v[k]):
                issues += node.errors(v[k], f"{path}[{key_label(k)}]")
        return issues


class NamedTupleNode(Node):
    """A NamedTuple instance with every field of its declared type."""

    def __init__(self, annotation: Any, outer: Leaf, fields: list[tuple[str, Node]]) -> None:
        self.annotation, self.outer, self.fields = annotation, outer, fields
        self.can_convert = any(n.can_convert for _, n in fields)
        ns: dict[str, Any] = {}
        parts = [_expr(outer, "v", ns)] + [_expr(node, f"v[{i}]", ns) for i, (_, node) in enumerate(fields)]
        self.check = _function(parts, ns)                           # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return self.outer.check(v)

    def convert(self, v: Any) -> Any:
        if not self.outer.check(v):
            return FAILED
        out, changed = [], False
        for (_, node), x in zip(self.fields, v):
            if not node.check(x):
                x = node.fix(x)
                if x is FAILED:
                    return FAILED
                changed = True
            out.append(x)
        return type(v)._make(out) if changed else v

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not self.outer.check(v):
            return [("type", path, v, self.annotation, None)]
        issues: list[Issue] = []
        for (name, node), x in zip(self.fields, v):
            if _bad(node, x):
                issues += node.errors(x, f"{path}.{name}")
        return issues


class UnionNode(Node):
    """A union with at least one deep member: valid when any member is valid."""

    def __init__(self, annotation: Any, members: list[Node]) -> None:
        self.annotation, self.members = annotation, members
        self.can_convert = any(m.can_convert for m in members)
        ns: dict[str, Any] = {}
        exprs = [_expr(m, "v", ns) for m in members]
        if "True" in exprs:
            self.check = _true                                      # type: ignore[assignment, method-assign]
        else:
            self.check = _function([f"({' or '.join(exprs)})"], ns)  # type: ignore[assignment, method-assign]

    def shape_ok(self, v: Any) -> bool:
        return any(m.shape_ok(v) for m in self.members)

    def convert(self, v: Any) -> Any:
        if self.check(v):
            return v
        for m in self.members:                          # declared order: the first that works wins
            out = m.convert(v)
            if out is not FAILED:
                return out
        return FAILED

    def errors(self, v: Any, path: str) -> list[Issue]:
        if not _bad(self, v):
            return []
        #* Report the inner errors of the member whose outer type fits (the fewest, if several do).
        best: list[Issue] | None = None
        for m in self.members:
            if m.shape_ok(v):
                issues = m.errors(v, path)
                if best is None or len(issues) < len(best):
                    best = issues
        return best or [("type", path, v, self.annotation, None)]


# ── compilation ──────────────────────────────────────────────────────────────

class _Slow:
    """Returned when part of an annotation can't be resolved yet (e.g. a forward reference)."""
    __slots__ = ()


SLOW = _Slow()

type LeafFactory = Callable[[Any], "Leaf | _Slow"]


class _Unresolved(Exception):
    pass


_UNREAD: Any = object()


class _State:
    __slots__ = ("make_leaf", "resolve", "seen", "recursive")

    def __init__(self, make_leaf: LeafFactory, resolve: "Callable[[str], Any] | None" = None) -> None:
        self.make_leaf = make_leaf
        self.resolve = resolve
        self.seen: dict[Any, Proxy] = {}
        self.recursive = False

    def leaf(self, annotation: Any) -> Leaf:
        out = self.make_leaf(annotation)
        if isinstance(out, _Slow):
            raise _Unresolved
        return out


def compile_node(annotation: Any, make_leaf: LeafFactory, resolve: "Callable[[str], Any] | None" = None) -> "Node | _Slow":
    """
    Compile ``annotation`` into a node tree. ``make_leaf(annotation)`` builds a shallow check
    (it comes from the type checker, which knows ``allow_subclass``, ``convert`` and ``coerce``).
    A ``Leaf`` result means there is nothing deep to check. ``SLOW`` means: try again later.

    ``resolve(text)`` evaluates a name that is still a string inside the annotation, where the
    annotation was written. It is only passed for annotations that come from source code. Without
    it a string is read as data (built-in names only), which is all a typecheck_record record gets.
    """
    state = _State(make_leaf, resolve)
    try:
        node = _compile(annotation, state)
    except _Unresolved:
        return SLOW
    except Exception:                                   # an annotation shape we don't understand: stay shallow
        return make_leaf(annotation)
    return Guard(node) if state.recursive and not node.leaf else node


def _alias_key(origin: Any, args: tuple[Any, ...]) -> Any:
    try:
        hash(args)
        return (id(origin), args)
    except TypeError:
        return (id(origin), tuple(map(id, args)))


def _accepts_anything(node: Node) -> bool:
    return isinstance(node, Leaf) and node.pred is None


def _compile(annotation: Any, st: _State) -> Node:
    #* An annotation still written as a string (in a record of typecheck_record, or one that
    #* names nothing yet): read it as data, so that "list[int]" has its items checked like list[int].
    if isinstance(annotation, (str, ForwardRef)):
        text = annotation if isinstance(annotation, str) else annotation.__forward_arg__
        written: Any = _UNREAD
        if st.resolve is not None:
            try:
                written = st.resolve(text)
            except Exception:
                pass
        if written is _UNREAD:
            try:
                written = read_annotation(text)
            except Exception:
                raise _Unresolved from None
        #* The name may stand for the very annotation being compiled: the old way to write a recursive
        #* alias, Json = Union[int, List["Json"]]. Like a recursive ``type`` alias, it becomes a cycle
        #* through a Proxy the second time round.
        key = ("name", id(written))
        if key in st.seen:
            st.recursive = True
            return st.seen[key]
        proxy = st.seen[key] = Proxy()
        try:
            proxy.target = inner = _compile(written, st)
        finally:
            del st.seen[key]
        return inner

    origin, args = get_origin(annotation), get_args(annotation)

    #* Type aliases, including generic (`Pair[int]`) and recursive (`type Tree = int | list[Tree]`) ones.
    #* A recursive alias compiles to a cycle through a Proxy.
    if isinstance(annotation, TypeAliasType) or isinstance(origin, TypeAliasType):
        key = _alias_key(annotation, ()) if isinstance(annotation, TypeAliasType) else _alias_key(origin, args)
        if key in st.seen:
            st.recursive = True
            return st.seen[key]
        if isinstance(annotation, TypeAliasType):
            value = annotation.__value__
        else:
            try:
                value = origin.__value__[args]
            except Exception:
                return st.leaf(annotation)
        proxy = st.seen[key] = Proxy()
        try:
            proxy.target = inner = _compile(value, st)
        finally:
            del st.seen[key]
        return inner

    #* Wrappers: follow them to what they wrap.
    inner_annotation: Any = None
    if origin is Annotated and metadata_checks(args[1:]):
        #* Annotated[T, check]: the checks are part of the shallow test of the whole value.
        inner = _compile(args[0], st)
        return st.leaf(annotation) if inner.leaf else Constrained(annotation, inner, st.leaf(annotation))
    if origin in (Annotated, Final, ClassVar, Required, NotRequired, ReadOnly):
        inner_annotation = args[0] if args else Any
    elif isinstance(annotation, dataclasses.InitVar):
        inner_annotation = annotation.type
    elif getattr(annotation, "__supertype__", None) is not None:                   # NewType
        inner_annotation = annotation.__supertype__
    elif isinstance(annotation, TypeVar) and annotation.__bound__ is not None:
        inner_annotation = typevar_types(annotation)[0]         # a string bound, looked up in its module
    elif isinstance(annotation, TypeVar) and annotation.__constraints__:
        #* TypeVar("L", list[int], dict[str, int]): one of them, items included.
        inner_annotation = Union[typevar_types(annotation)[1]]
    if inner_annotation is not None:
        return _compile(inner_annotation, st)

    if isinstance(annotation, UnionType) or origin is Union:
        members = [_compile(a, st) for a in args]
        if all(m.leaf for m in members):
            return st.leaf(annotation)                  # shallow union: the existing check and conversion order
        return UnionNode(annotation, members)

    if is_typeddict(annotation):
        try:
            hints = get_type_hints(annotation, include_extras=True)
        except Exception:
            raise _Unresolved from None
        fields = {k: _compile(t, st) for k, t in hints.items()}
        required = frozenset(annotation.__required_keys__)             # type: ignore[union-attr]
        if not required and all(_accepts_anything(n) for n in fields.values()):
            return st.leaf(annotation)
        return TypedDictNode(annotation, st.leaf(annotation), fields, hints, required)

    if isinstance(annotation, type) and issubclass(annotation, tuple) and hasattr(annotation, "_fields"):
        try:
            hints = get_type_hints(annotation, include_extras=True)
        except Exception:
            raise _Unresolved from None
        names: tuple[str, ...] = annotation._fields                  # type: ignore[attr-defined]
        named = [(f, _compile(hints[f], st) if f in hints else st.leaf(Any)) for f in names]
        if all(_accepts_anything(n) for _, n in named):
            return st.leaf(annotation)
        return NamedTupleNode(annotation, st.leaf(annotation), named)

    if origin is tuple:
        outer = st.leaf(annotation)
        if not hasattr(annotation, "__args__"):
            return outer                                # bare typing.Tuple: any tuple (tuple[()] has empty __args__)
        if any(getattr(a, "__unpacked__", False) or get_origin(a) is Unpack for a in args):
            laid = spread(args)                         # tuple[int, *tuple[str, ...]]: a run of unknown length
            if laid is None:
                return outer
            before, middle, after = laid
            if middle is FIXED:
                return FixedTuple(annotation, outer, [_compile(a, st) for a in before])
            run = _compile(middle, st)
            if not before and not after:
                return outer if _accepts_anything(run) else Items(annotation, outer, run)
            return VariadicTuple(annotation, outer, [_compile(a, st) for a in before], run, [_compile(a, st) for a in after])
        if len(args) == 2 and args[1] is Ellipsis:
            item = _compile(args[0], st)
            return outer if _accepts_anything(item) else Items(annotation, outer, item)
        if args == ((),):                               # tuple[()] on older spellings
            args = ()
        return FixedTuple(annotation, outer, [_compile(a, st) for a in args])

    if origin in _ITEM_ORIGINS and len(args) == 1:
        item = _compile(args[0], st)
        outer = st.leaf(annotation)
        return outer if _accepts_anything(item) else Items(annotation, outer, item)

    if origin in _MAPPING_ORIGINS and args:
        keys = _compile(args[0], st)
        values = _compile(args[1], st) if len(args) > 1 else st.leaf(int)         # Counter[K]: counts are ints
        outer = st.leaf(annotation)
        if _accepts_anything(keys) and _accepts_anything(values):
            return outer
        return Mapping(annotation, outer, keys, values)

    return st.leaf(annotation)
