"""
The annotation caches and what keeps them from holding a class alive: weak entries, eviction,
the annotations written for one class. And ``frame_above``: the frames of the stack, read
without keeping one.
"""
from dataclasses import InitVar
from typing import Any, Callable, NewType, TypeAliasType, TypeVar
from functools import partial
from types import FrameType
import inspect
import sys
import threading
import weakref


def frame_above(levels: int = 1) -> FrameType | None:
    """
    The frame ``levels`` calls above the function that calls this: 1 is its caller. ``None`` on a
    Python without frames, or above the top of the stack. Through ``inspect.currentframe``, the
    public way (the owner's decision, 2026-10-16: no ``sys._getframe`` in the package).
    """
    frame = inspect.currentframe()                      # this function's own: rebound below, so no cycle
    for _ in range(levels + 1):
        if frame is None:
            return None
        frame = frame.f_back
    return frame


def held(annotation: Any, cache: dict[Any, Any], key: Any) -> Any:
    """
    How a cache entry refers to the annotation it is about: weakly, with the entry taken out of
    ``cache`` when the annotation goes. A cache that held the annotation itself kept it alive, and
    with it every class it names: a class local to a function stayed until 4,096 newer annotations
    had come. An annotation that takes no weak reference (a string, a ``type`` alias, on 3.13 an
    ``int | str``) is held as it is: ``cacheable`` has said that nothing is lost by that.
    """
    try:
        return weakref.ref(annotation, partial(_gone, cache, key))
    except TypeError:
        return annotation


_HEAP_TYPE = 1 << 9                                     # Py_TPFLAGS_HEAPTYPE: a class made when a program runs


def cacheable(annotation: Any) -> bool:
    """
    Whether a cache may take ``annotation``: not one it could never let go of (``held``) that names a
    class which has to be able to go. On 3.13 that is ``LocalClass | None``, whose ``|`` takes no weak reference.
    """
    try:
        weakref.ref(annotation)
    except TypeError:
        return not names_a_class(annotation, can_go)
    return True


def names_a_class(annotation: Any, test: Callable[[type], bool], depth: int = 0) -> bool:
    """
    Whether ``test`` holds for a class anywhere in ``annotation``: through its members, and what an alias
    (``type A = ...``), an ``InitVar``, a ``NewType`` or a ``TypeVar`` stands for. A value (``Literal[Color.RED]``)
    counts as its class. What can't be read counts as yes.
    """
    if isinstance(annotation, type):
        return test(annotation)
    if depth >= 8:                                      # a recursive alias: nothing new below
        return False
    try:
        if isinstance(annotation, TypeAliasType):
            return names_a_class(annotation.__value__, test, depth + 1)
        if isinstance(annotation, InitVar):
            return names_a_class(annotation.type, test, depth + 1)
        if isinstance(annotation, NewType):
            return names_a_class(annotation.__supertype__, test, depth + 1)
        if isinstance(annotation, TypeVar):
            return (names_a_class(annotation.__bound__, test, depth + 1)
                    or any(names_a_class(part, test, depth + 1) for part in annotation.__constraints__))
    except Exception:                                   # read late, and it may not resolve yet
        return True
    parts = getattr(annotation, "__args__", None)
    if not parts:
        return test(type(annotation))
    origin = getattr(annotation, "__origin__", None)    # a generic alias's own: ``A[int]``
    return names_a_class(origin, test, depth + 1) or any(names_a_class(part, test, depth + 1) for part in parts)


def can_go(cls: type) -> bool:
    """Whether ``cls`` may be dropped by the program: not one built into Python (``NoneType``, which no module names), nor one its module holds."""
    return bool(cls.__flags__ & _HEAP_TYPE) and not findable(cls)


def findable(cls: type) -> bool:
    """Whether ``cls`` is found by its name in its module: what pickle asks, and no class written in a function or made at run time."""
    found: Any = sys.modules.get(cls.__module__)
    for part in cls.__qualname__.split("."):
        found = getattr(found, part, None)
    return found is cls


def holds(kept: Any, annotation: Any) -> bool:
    """Whether a cache entry made with ``held`` is about this very annotation."""
    return kept is annotation or (type(kept) is weakref.ReferenceType and kept() is annotation)


def _gone(cache: dict[Any, Any], key: Any, reference: Any) -> None:
    #* No lock: this runs wherever the garbage collector does, also inside a block that holds one.
    entry = cache.get(key)
    if entry is not None and entry[0] is reference:
        cache.pop(key, None)


def make_room(cache: dict[Any, Any], limit: int) -> None:
    """Let the oldest entries of a full cache go. The caller holds the cache's lock."""
    while len(cache) >= limit:
        try:
            cache.pop(next(iter(cache)), None)
        except (RuntimeError, StopIteration):           # an entry went by itself meanwhile (see ``_gone``)
            pass


#* The ids of annotations that no cache takes: those written for one class, in place of ``Self``
#* (see ``made_for``). A cache keeps what it holds alive, and these name a class that may have
#* been made at run time and has to be able to go.
not_cached: set[int] = set()


def made_for(cls: type, annotations: list[Any]) -> None:
    """
    ``annotations`` were written for ``cls`` alone: ``Self | None`` as ``cls | None``, for a call
    of an inherited method on ``cls``. They, and the parts of them that name ``cls``, are kept out
    of the annotation caches for as long as ``cls`` lives. The checker made for ``cls`` holds them
    and what was compiled from them; it goes with the class (``api._OF_CLASS``).
    """
    ids: set[int] = set()

    def names_it(annotation: Any, depth: int = 0) -> bool:
        found = annotation is cls
        if depth < 8:
            for part in getattr(annotation, "__args__", None) or ():
                found = names_it(part, depth + 1) or found
        if found and annotation is not cls:             # the class itself is never cached: see TypeContainer
            ids.add(id(annotation))
        return found

    for annotation in annotations:
        names_it(annotation)
    if ids:
        not_cached.update(ids)
        try:
            weakref.finalize(cls, not_cached.difference_update, ids)
        except TypeError:                               # a class that takes no weak reference: they stay listed
            pass


CACHE_LOCK = threading.Lock()
