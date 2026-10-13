"""
The annotation caches and what keeps them from holding a class alive: weak entries, eviction,
the annotations written for one class.
"""
from typing import Any
from functools import partial
import threading
import weakref


def held(annotation: Any, cache: dict[Any, Any], key: Any) -> Any:
    """
    How a cache entry refers to the annotation it is about: weakly, with the entry taken out of
    ``cache`` when the annotation goes. A cache that held the annotation itself kept it alive, and
    with it every class it names: a class local to a function stayed until 4,096 newer annotations
    had come. An annotation that takes no weak reference (a string, a ``type`` alias) is held as it
    is; those are written once, in a module.
    """
    try:
        return weakref.ref(annotation, partial(_gone, cache, key))
    except TypeError:
        return annotation


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
