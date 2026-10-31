"""
A dispatcher's state: its candidates in order (the versions, then the base), the anchor of each,
the cache of what plain classes are answered by, and the choice of a version for a value.
"""
from .. import _environment
from .._validator._annotations import has_self, resolve_annotations
from .._validator._errors import InvalidDataError
from .._validator._scope import resolver
from .._validator._signatures import signature_of
from .._validator._specs import SLOW
from .._validator._type_conversion import FAILED
from .._validator._wrapping import checked_inside, wrap_callable
from ._errors import version_label, anchor_text, no_anchor_error, no_version_error, refused, unreachable_error, which
from ._match import Anchor, compile_anchor, take_raw
from ._reach import what_covers
from .._validator._text import VERSION_ATTR, short_repr
from functools import partial
from typing import Any, Callable, ForwardRef
from abc import get_cache_token
import inspect
import threading
import weakref


_NOT_ANNOTATED: Any = object()
_POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


class Candidate:
    """
    One version (``number`` from 1, in the order of registration) or the base (``number`` 0, the
    last candidate). ``fn`` is the function as written; ``call`` what a dispatcher calls (``fn``
    with its other parameters checked); ``member`` for a method, what is bound (the checked
    function, or a ``classmethod`` / ``staticmethod`` of it). ``annotation`` is the anchor's;
    ``anchor`` its compiled test, None until it resolves. ``checked``: its reachability is known.
    """
    __slots__ = ("fn", "number", "name", "annotation", "given", "anchor", "call", "member", "checked", "binds")

    def __init__(self, fn: Callable[..., Any], number: int, name: str, annotation: Any, given: bool) -> None:
        self.fn, self.number, self.name, self.annotation, self.given = fn, number, name, annotation, given
        self.anchor: Anchor | None = None
        self.call: Any = fn
        self.member: Any = fn
        self.checked = False
        #* For a method, what ``call`` is given first: 0 the instance, 1 the class, 2 nothing (a static method).
        self.binds = 0


class Dispatcher:
    """
    Everything a dispatcher knows. ``table`` is what a call reads, without a lock: ``(candidates,
    cache, abc)``, replaced whole by every change (``None``: to be worked out, ``settle``).
    ``cache`` maps ``id(class)`` to ``(weak reference to the class, index, chosen)``: where the
    candidates are walked from for a value of that class, and whether the candidate there is
    chosen by the class alone. ``abc``: the ABC cache token the table was made with, or None
    when no class anchor is an ABC.
    """
    __slots__ = ("base", "skip", "allow_subclass", "check_return", "convert", "warn", "error", "versions",
                 "base_candidate", "table", "lock", "kind_of", "__weakref__")

    def __init__(self, base: Callable[..., Any], skip: int, allow_subclass: bool, check_return: bool, convert: bool,
                 warn: bool, error: "type[InvalidDataError]", kind_of: "Callable[[Any], Any] | None" = None) -> None:
        #* ``base`` is what was decorated (for a method maybe a classmethod); ``self.base`` the function in it.
        self.base, self.skip = (base if kind_of is None else kind_of(base)[0]), skip
        self.allow_subclass, self.check_return, self.convert, self.warn, self.error = (
            allow_subclass, check_return, convert, warn, error)
        self.versions: list[Candidate] = []
        self.table: Any = None
        self.lock = threading.RLock()
        #* For a method: ``member -> (function, rebuild)``, a classmethod / staticmethod taken apart.
        self.kind_of = kind_of
        self.base_candidate = self._candidate(base, 0, _NOT_ANNOTATED)
        self._compile(self.base_candidate)              # a base refused for its anchor is refused where it is written
        self._wrap(self.base_candidate)

    # ── making a candidate ───────────────────────────────────────────────────

    def _parts(self, member: Any) -> tuple[Callable[..., Any], Any, int]:
        """``(function, rebuild, parameters before the anchor)`` of what was registered."""
        if self.kind_of is None:
            return member, None, 0
        return self.kind_of(member)

    def _candidate(self, member: Any, number: int, annotation: Any) -> Candidate:
        fn, _, skip = self._parts(member)
        if not inspect.isfunction(fn):
            raise refused(self.base, f"a version must be a function, got {short_repr(member, 60)}")
        params = list(signature_of(fn).parameters.values())[skip:]
        if not params or params[0].kind not in _POSITIONAL:
            what = "no parameter" if not params else f"{params[0].name}, which is not positional"
            raise refused(self.base, f"{fn.__qualname__} has {what} to choose by: the anchor is the first "
                                     f"parameter{' after self / cls' if skip else ''}, passed positionally")
        name = params[0].name
        given = annotation is not _NOT_ANNOTATED
        if not given:
            annotation = self._annotation_of(fn, name, number)
        candidate = Candidate(fn, number, name, annotation, given)
        candidate.member = member
        return candidate

    def _annotation_of(self, fn: Callable[..., Any], name: str, number: int) -> Any:
        try:
            record = resolve_annotations(fn)
        except Exception:
            record = {}
        if name in record:
            return record[name]
        if number == 0:
            return Any                                  # an unannotated base takes everything
        raise refused(self.base, f"{fn.__qualname__}: its anchor, {name}, has no annotation (or pass one: "
                                 f"register(list[int], fn))")

    def _wrap(self, candidate: Candidate) -> None:
        """What the dispatcher calls: the version with its other parameters checked (none, all switched off)."""
        fn, rebuild, skip = self._parts(candidate.member)
        if _environment.VALIDATION_OFF or (not self.check_return and _nothing_else(fn, skip)):
            checked = fn                                # nothing left to check: called as it is
        elif checked_inside(fn) is not None:
            checked = fn                                # its own @validate: those options stand
        else:
            checked = wrap_callable(fn, self.allow_subclass, self.check_return, skip_first = bool(skip),
                                    convert = self.convert, coerce = False, deep = True, warn = self.warn,
                                    error = self.error, leave = frozenset({candidate.name}))
        candidate.call = checked
        candidate.member = checked if rebuild is None else rebuild(checked)
        if candidate.number:                            # a version: named by what it is in messages
            try:
                fn.__dict__[VERSION_ATTR] = partial(version_label, self.base, candidate)
            except (AttributeError, TypeError):
                pass
        candidate.binds = 1 if rebuild is classmethod else 2 if rebuild is staticmethod else 0

    def _compile(self, candidate: Candidate) -> bool:
        """Compile the anchor of ``candidate``; False while part of it can't be resolved yet."""
        if candidate.anchor is not None:
            return True
        annotation = candidate.annotation
        fn = candidate.fn
        if not candidate.given and type(annotation) is not str and _unresolved(annotation):
            try:
                annotation = resolve_annotations(fn).get(candidate.name, annotation)     # a name defined since
            except Exception:
                pass
        if isinstance(annotation, str):
            try:
                annotation = resolver(fn, None)(annotation)
            except Exception:
                return False
        if has_self(annotation):
            raise refused(self.base, f"{which(candidate)}: Self can't be an anchor (the class of the call isn't "
                                     f"known when the version is chosen)")
        anchor = compile_anchor(annotation, self.allow_subclass, candidate.name, resolver(fn, None))
        if anchor is SLOW:
            return False
        candidate.annotation, candidate.anchor = annotation, anchor
        return True

    # ── registering ──────────────────────────────────────────────────────────

    def register(self, member: Any, annotation: Any = _NOT_ANNOTATED) -> None:
        """Add a version. Refused (and nothing changes) when it can never be chosen, or hides the base."""
        with self.lock:
            candidate = self._candidate(member, len(self.versions) + 1, annotation)
            for earlier in self.versions:
                if earlier.fn is candidate.fn:
                    raise refused(self.base, f"{candidate.fn.__qualname__} is registered already, as {which(earlier)}")
            if self._compile(candidate) and all(c.checked for c in self.versions) and self._compile(self.base_candidate):
                self._check(candidate)                  # what it can be checked against is known: now
            self._wrap(candidate)
            self.versions.append(candidate)
            self.table = None

    def _check(self, candidate: Candidate) -> None:
        """Refuse ``candidate`` (the newest version) if it can never be chosen, or leaves the base unreachable."""
        earlier = self.versions[:candidate.number - 1]
        found = what_covers(candidate.anchor, [c.anchor for c in earlier], self.allow_subclass)     # type: ignore[arg-type, misc]
        if found is not None:
            raise unreachable_error(self.base, candidate, [(part, earlier[i]) for part, i in found])
        before = [*earlier, candidate]
        base = self.base_candidate
        found = what_covers(base.anchor, [c.anchor for c in before], self.allow_subclass)        # type: ignore[arg-type, misc]
        if found is not None:
            raise unreachable_error(self.base, candidate, [(part, before[i]) for part, i in found], base)
        candidate.checked = True

    def settle(self) -> Any:
        """
        The table a call reads, worked out: every anchor compiled (a name defined since it was
        registered), every version not yet checked checked, in order. Raises while one can't be.
        """
        with self.lock:
            table = self.table
            if table is not None:
                return table
            for candidate in (*self.versions, self.base_candidate):
                if not self._compile(candidate):
                    raise refused(self.base, f"cannot resolve the anchor of {which(candidate)}: "
                                             f"{anchor_text(candidate.annotation)}")
            for candidate in self.versions:
                if not candidate.checked:
                    self._check(candidate)
            candidates = (*self.versions, self.base_candidate)
            abc = any(c.anchor.abc for c in candidates)         # type: ignore[union-attr]
            table = self.table = (candidates, {}, get_cache_token() if abc else None)
            return table

    # ── choosing ─────────────────────────────────────────────────────────────

    def choose(self, value: Any) -> tuple[Candidate, Any]:
        """The candidate that takes ``value``, and the value as it is passed (a model built from a raw one)."""
        table = self.table
        if table is None:
            table = self.settle()
        candidates, cache, token = table
        if token is not None and token != get_cache_token():  # an ABC registration may change what a class is
            with self.lock:
                if self.table is table:
                    self.table = None
            table = self.settle()
            candidates, cache, token = table
        cls = type(value)
        entry = cache.get(id(cls))
        if entry is None or entry[0]() is not cls:
            entry = _learn(cls, value, candidates, cache)
        start = entry[1]
        if entry[2]:
            return candidates[start], value
        for i in range(start, len(candidates)):
            candidate = candidates[i]
            anchor = candidate.anchor
            test = anchor.test                          # type: ignore[union-attr]
            if test is None or test(value):
                return candidate, value
            if anchor.models:                           # type: ignore[union-attr]
                out = take_raw(anchor.models, value)    # type: ignore[union-attr]
                if out is not FAILED:
                    return candidate, out
        raise no_version_error(self.base, value, candidates, self.allow_subclass, self.error)

    def no_anchor(self, kwargs: dict[str, Any]) -> InvalidDataError:
        return no_anchor_error(self.base, self.base_candidate.name, kwargs, self.error)

    def registry(self) -> tuple[tuple[Any, Callable[..., Any]], ...]:
        return tuple((c.annotation, c.fn) for c in (*self.versions, self.base_candidate))


def _learn(cls: type, value: Any, candidates: tuple[Candidate, ...], cache: dict[int, Any]) -> tuple[Any, ...]:
    """
    Where the walk starts for a value of ``cls``: the first candidate whose answer depends on more
    than the class (from there each is asked), or the first that the class is taken by (chosen at
    once). Kept by ``id`` with a weak reference, which takes the entry away with the class: a class
    made at run time must not be kept alive by a dispatcher.
    """
    index, chosen = len(candidates), False
    for i, candidate in enumerate(candidates):
        anchor = candidate.anchor
        if not anchor.by_class:                         # type: ignore[union-attr]
            index = i
            break
        if anchor.test is None or anchor.test(value):   # type: ignore[union-attr]
            index, chosen = i, True
            break
    key = id(cls)

    def gone(_: Any, cache: dict[int, Any] = cache, key: int = key) -> None:
        cache.pop(key, None)
    try:
        entry = (weakref.ref(cls, gone), index, chosen)
    except TypeError:                                   # a class that takes no weak reference: not kept
        return (lambda: cls, index, chosen)
    cache[key] = entry
    return entry


def _nothing_else(fn: Callable[..., Any], skip: int) -> bool:
    """Whether ``fn`` takes the anchor (after ``skip`` parameters) and nothing else, so that there is no other parameter to check."""
    try:
        return len(signature_of(fn).parameters) == skip + 1
    except Exception:
        return False


def _unresolved(annotation: Any, depth: int = 0) -> bool:
    """Whether a name inside ``annotation`` is still a string (``ForwardRef``)."""
    if isinstance(annotation, (str, ForwardRef)):
        return True
    if depth < 8:
        return any(_unresolved(a, depth + 1) for a in getattr(annotation, "__args__", None) or ())
    return False

