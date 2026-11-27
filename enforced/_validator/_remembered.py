"""What validate_function and validate_record keep between calls: wrappers and checkers."""
from ._checker import PreparedChecker
from ._defaults import PASSED
from ._errors import InvalidDataError, WarnAs, warns
from ._scope import remember_scope
from ._signatures import signature_stub
from ._wrapping import wrap_callable, wrap_member
from .._compat import UNION_TYPES
from typing import Any, Callable
from types import FunctionType
import threading


def new_record_checker(key: Any, target: Any, record: dict[str, Any], allow_subclass: bool, skip_first: bool,
                        convert: bool, coerce: bool, deep: bool, warn: WarnAs = False,
                        error: "type[InvalidDataError]" = InvalidDataError) -> "PreparedChecker":
    """A checker for ``target`` and ``record``, put into the cache under ``key`` (``None``: it can't be cached)."""
    fn = target if callable(target) else signature_stub(target, record)
    #* We never call ``target``, so its defaults are left alone: a converted one goes back to the caller.
    checker = PreparedChecker(fn, allow_subclass, None, skip_first, record = record,
                               convert = convert, coerce = coerce, rewrite_defaults = PASSED, deep = deep, warn = warn,
                               error = error)
    if key is not None:
        #* Hits read the cache without a lock. Whatever changes it does so one thread at a time:
        #* an eviction must not meet another thread's insert or eviction halfway.
        with _RECORD_LOCK:
            if type(target) is str:
                checker = _remember_checker(key, record, checker)
            else:
                checker = _remember_checker(key, record, checker, _kept_on(target, RECORDS, RECORD_CACHE, True),
                                            _OWN_RECORDS_MAX)
    return checker


#* What validate_function and validate_record remember about a function is kept on the function,
#* under these names: ``(it, {options: its checked wrapper})`` and ``(it, {key: its checker})``.
#* A cache of their own would hold the wrapper, the wrapper holds the function, and so a function
#* made in a loop and called once would stay until 512 newer ones had come. Kept on
#* the function, the two form a cycle that the garbage collector takes away with the function.
CALLS = "__enforced_calls__"
RECORDS = "__enforced_records__"
#* The records one function keeps checkers for (validate_record): there is usually one.
_OWN_RECORDS_MAX = 32

#* For any other callable (an object with __call__, a functools.partial, a builtin):
#* id(it) -> (it, {options: its checked wrapper}). The entry holds the callable, so its id can't be
#* another's while it is here; like the other caches, it lets its oldest entry go when it is full.
#* Nothing is written into such an object: its attributes are its state, which is copied and
#* pickled with it, and a wrapper is bound to the one object it was made for.
CALL_WRAPPERS: "dict[int, tuple[Any, dict[tuple, Callable[..., Any]]]]" = {}
_CALL_WRAPPERS_MAX = 512


def _kept_on(target: Any, name: str, shared: dict[Any, Any], create: bool = False) -> dict[Any, Any]:
    """
    The dictionary a function keeps under ``name``, for what is remembered about it. One that isn't
    its own counts as none: ``functools.wraps`` copies attributes from the function inside. Without
    one, an empty dictionary, or with ``create`` a new one that the function now keeps. ``shared``
    is what any other callable gets instead.
    """
    if type(target) is not FunctionType:
        return shared
    held = target.__dict__
    entry = held.get(name)
    if entry is not None and entry[0] is target:
        return entry[1]
    if not create:
        return NOTHING_KEPT
    kept: dict[Any, Any] = {}
    held[name] = (target, kept)
    return kept


NOTHING_KEPT: dict[Any, Any] = {}


def call_wrapper(fn: Any, options: tuple, frame: Any) -> Callable[..., Any]:
    """
    The checked wrapper of ``fn`` for these options, made and remembered. ``frame`` is the caller's.
    ``options``: the five flags, ``on_error``, ``error`` and ``warning`` (checked by the caller).
    """
    allow_subclass, check_return, convert, coerce, deep = [bool(option) for option in options[:5]]
    warn, error = warns(options[5], options[7]), options[6]
    if type(fn) is FunctionType:
        if "<locals>" in fn.__qualname__:
            remember_scope(fn, frame)
        checked = wrap_callable(fn, allow_subclass, check_return, convert = convert, coerce = coerce, deep = deep, warn = warn,
                                error = error)
    else:
        checked = wrap_member(fn, allow_subclass, check_return, convert, coerce, deep, frame, warn, error)
    #* Hits take no lock. Whatever changes the cache does so one thread at a time.
    with _RECORD_LOCK:
        kept = _kept_on(fn, CALLS, CALL_WRAPPERS, True)
        if kept is not CALL_WRAPPERS:
            return kept.setdefault(options, checked)
        entry = CALL_WRAPPERS.get(id(fn))
        if entry is None or entry[0] is not fn:
            while len(CALL_WRAPPERS) >= _CALL_WRAPPERS_MAX:
                CALL_WRAPPERS.pop(next(iter(CALL_WRAPPERS)), None)        # the oldest entry
            entry = CALL_WRAPPERS[id(fn)] = (fn, {})
        return entry[1].setdefault(options, checked)


#* key -> checker, or for a record with unions: (their parameter names, {member order: checker}).
RECORD_CACHE: dict[tuple, Any] = {}
_RECORD_CACHE_MAX = 512
_RECORD_ORDERS_MAX = 16
_RECORD_LOCK = threading.Lock()


def _remember_checker(key: tuple, record: dict[str, Any], checker: "PreparedChecker",
                      cache: "dict[tuple, Any] | None" = None, limit: int = 0) -> "PreparedChecker":
    """
    Put ``checker`` into the ``validate_record`` cache and return the one to use: ``checker``, or
    the one another thread stored for the same spec in the meantime. The caller holds the lock.
    ``cache`` and its ``limit``: the records of one callable, where the target is one (``_kept_on``).
    """
    if cache is None or cache is RECORD_CACHE:
        cache, limit = RECORD_CACHE, _RECORD_CACHE_MAX
    entry = cache.get(key)
    if entry is None:
        while len(cache) >= limit:
            del cache[next(iter(cache))]                # the oldest entry
        names = tuple([name for name, annotation in record.items() if _has_union(annotation)])
        if names:
            cache[key] = (names, {tuple([union_order(record[name]) for name in names]): checker})
        else:
            cache[key] = checker
        return checker
    if type(entry) is not tuple:
        return entry
    names, by_order = entry
    order = tuple([union_order(record[name]) for name in names])
    if order in by_order or len(by_order) < _RECORD_ORDERS_MAX:
        return by_order.setdefault(order, checker)
    return checker                                      # every slot for this record is taken: used, not kept


def _has_union(annotation: Any, depth: int = 0) -> bool:
    """Whether a union sits anywhere inside ``annotation`` (``int | str``, ``list[int | str]``)."""
    if isinstance(annotation, UNION_TYPES):
        return True
    return depth < 8 and any(_has_union(arg, depth + 1) for arg in getattr(annotation, "__args__", None) or ())


def union_order(annotation: Any) -> Any:
    """The order of the union members in ``annotation``: equality ignores it, conversion follows it."""
    if isinstance(annotation, UNION_TYPES):
        args = annotation.__args__
        for arg in args:
            if type(arg) is not type:
                return repr(annotation)                 # something nested: the repr keeps every level's order
        return args                                     # the common case: a union of plain classes
    return repr(annotation)
