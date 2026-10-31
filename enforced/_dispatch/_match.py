"""
How one candidate of a dispatcher tests a value: its anchor's annotation, compiled as a check with
``deep`` on and no conversion, plus the TypeModels at the top of it, which take a raw value that
their ``validate`` accepts.
"""
from .._validator import _deep
from .._validator._container import TypeContainer, TypeUnion, find_uncheckable_protocol, protocol_error
from .._validator._specs import SLOW, compile_spec, deep_node, predicate
from .._validator._type_conversion import FAILED, is_model
from typing import Any, Callable, is_protocol
from abc import ABCMeta


#* Specs whose answer depends on the class of the value alone (``_candidates`` caches it by class).
CLASS_KINDS = frozenset({"any", "isinstance", "nobool", "is", "in"})


class Anchor:
    """
    An anchor's annotation, compiled. ``test`` answers whether a value is taken as it is (None:
    anything is); ``models`` are the TypeModels at the top of the annotation (alone, or members of
    its union), each tried on a raw value with ``take``; ``node`` is the deep node (a ``Leaf`` where
    there are no items), which ``_reach`` reads; ``by_class``: the answer of ``test`` depends on
    the class of the value only (no models, no checks, no items, no Protocol); ``abc``: an ABC is
    among those classes, so a registration with it can change the answer (``abc.get_cache_token``).
    """
    __slots__ = ("annotation", "test", "models", "node", "by_class", "abc")

    def __init__(self, annotation: Any, test: "Callable[[Any], bool] | None", models: tuple[type, ...], node: Any,
                 by_class: bool, abc: bool) -> None:
        self.annotation, self.test, self.models, self.node, self.by_class, self.abc = (
            annotation, test, models, node, by_class, abc)

    def take(self, value: Any) -> Any:
        """``value`` as the version receives it (a model built from a raw value), or ``FAILED``."""
        test = self.test
        if test is None or test(value):
            return value
        return take_raw(self.models, value) if self.models else FAILED


def take_raw(models: tuple[type, ...], value: Any) -> Any:
    """The first of ``models`` that a raw value of its base type is accepted by, built; or ``FAILED``."""
    for model in models:
        out, _ = model.__enforced_convert__(value)      # type: ignore[attr-defined]  # base type, never a bool, then validate
        if out is not FAILED:
            return out
    return FAILED


def compile_anchor(annotation: Any, allow_subclass: bool, key: str, resolve: "Callable[[str], Any] | None") -> Any:
    """The ``Anchor`` of ``annotation``, or ``SLOW`` while part of it can't be resolved yet."""
    if (protocol := find_uncheckable_protocol(annotation)) is not None:
        raise protocol_error(protocol, key)
    spec = compile_spec(annotation, allow_subclass, key, deep = True, convert = False, coerce = False, resolve = resolve)
    if not isinstance(spec, tuple):
        return SLOW
    node = deep_node(annotation, allow_subclass, False, False, resolve)
    if node is SLOW:
        return SLOW
    test = predicate(spec)
    if node is None:                                    # no items to check: the shallow check is all
        node = _deep.Leaf(annotation, spec, test, None)
    models = tuple(dict.fromkeys(top_models(node)))
    classes = _classes(spec) if spec[0] in CLASS_KINDS else None
    by_class = not models and classes is not None and all(type_only(c) for c in classes)
    abc = by_class and classes is not None and any(isinstance(c, ABCMeta) for c in classes)
    return Anchor(annotation, test, models, node, by_class, abc)


def top_models(node: Any) -> list[type]:
    """The TypeModel classes at the top of an anchor: its own class, or members of its union (rule 5 of the plan)."""
    if isinstance(node, _deep.Guard):
        return top_models(node.inner)
    if isinstance(node, _deep.UnionNode):
        return [m for member in node.members for m in top_models(member)]
    if not isinstance(node, _deep.Leaf):
        return []
    try:
        c = TypeContainer(None, "?", None, node.annotation)
    except Exception:
        return []
    special = c._literal_values is not None or c._type_arg is not None
    plain = c._other_types if special else c._expected_type
    if c._constraints is not None:
        plain = c._plain_types                          # a model inside Annotated[...] is checked as it is
    return [t for t in members(plain) if is_model(t)]


def members(types: Any) -> tuple[Any, ...]:
    """The classes of a flattened type: one, a ``TypeUnion``, or none."""
    if types is None:
        return ()
    if isinstance(types, (TypeUnion, tuple, frozenset)):
        return tuple(types)
    return (types,)


def _classes(spec: tuple) -> tuple[Any, ...]:
    return () if spec[0] == "any" else members(spec[1])


def type_only(cls: Any) -> bool:
    """
    Whether ``isinstance`` / ``issubclass`` with ``cls`` go by the classes alone: the metaclass
    answers them as ``type`` or ``ABCMeta`` do. Not so for a Protocol (it looks at the instance's
    attributes), the file stand-ins (methods), and any metaclass with its own ``__instancecheck__``.
    """
    if not isinstance(cls, type) or is_protocol(cls):
        return False
    meta = type(cls)
    return _own(meta, "__instancecheck__") in (type, ABCMeta) and _own(meta, "__subclasscheck__") in (type, ABCMeta)


def _own(meta: type, name: str) -> type | None:
    """The class in ``meta``'s MRO that defines ``name``."""
    for klass in meta.__mro__:
        if name in klass.__dict__:
            return klass
    return None
