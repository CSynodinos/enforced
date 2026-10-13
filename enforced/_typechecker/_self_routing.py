"""``Self`` as the class of the call: one wrapper per class a method is called on."""
from ._annotations import SELF_ANYWHERE, SELF_IN_PARAMETERS
from ._defaults import IN_PLACE
from ._lifetime import CACHE_LOCK
from typing import Any, Callable, TYPE_CHECKING
from functools import partial
import collections
import collections.abc
import weakref

if TYPE_CHECKING:
    from ._checker import PreparedChecker


#* Where a class keeps what was made for it alone: the wrappers of inherited methods in which
#* ``Self`` is this class, and the checkers of inherited dataclass fields that use ``Self``. On the
#* class, so that they go when it goes: each of them names the class, and anything else that held
#* them would keep a class made at run time alive for as long as it did (review finding 36).
_OF_CLASS = "__enforced_self__"
#* For a class that takes no attribute (a metaclass that refuses): the last wrappers made, by themselves.
_SELF_CLASSES_MAX = 128
_HELD_FOR_CLASSES: "collections.deque[Any]" = collections.deque(maxlen = _SELF_CLASSES_MAX)


def kept_of(cls: type, create: bool = False) -> dict[Any, Any] | None:
    """The dictionary ``cls`` itself keeps under ``_OF_CLASS`` (not one it inherits); with ``create``, made if it can be."""
    kept = vars(cls).get(_OF_CLASS)
    if kept is None and create:
        kept = {}
        try:
            setattr(cls, _OF_CLASS, kept)
        except Exception:
            return None
    return kept


def _forget_wrapper(family: dict[int, Any], key: int, gone: Any) -> None:
    """A wrapper of ``family`` is gone, and its class with it: the entry goes too, unless the id is another's by now."""
    if family.get(key) is gone:
        family.pop(key, None)


def _route(checker: "PreparedChecker", args: tuple[Any, ...], check_return: bool,
           mark: "Callable[[], dict[str, Any] | None] | None") -> Any:
    """
    For a method whose annotations use ``Self``: the wrapper that this call belongs to, or ``None``
    when that is the one ``checker`` is of.

    ``Self`` is the class of the instance a method is called on (for a class method, the class it
    is called on): ``Child().clone()`` has to return a ``Child``, though ``clone`` is defined in
    ``Base``. A check is compiled for one class, and sees one value at a time. So there is one
    wrapper per class: the one decorated (``Self`` is the class that defines the method), and one
    for each other class the method is called on, made here when the first such call arrives.
    ``check_return`` and ``mark`` are what the decorated wrapper was made with.

    The wrappers of one method share a ``family``: id(class) -> a weak reference to its wrapper.
    What holds the wrapper is the class it was made for (``_OF_CLASS``): the two name each other
    and go together. While the wrapper lives the class does, so the id is that class's.

    Only a class that inherits the method is given a wrapper. Anything else in the place of
    ``self`` (a call such as ``Base.method(5)``) is left to the wrapper that was asked.
    """
    if not args:
        return None
    owner, first = checker.owner, args[0]
    cls: Any = type(first)
    try:
        if owner not in cls.__mro__:                    # not an instance: a class method or __new__, called on a class
            if not isinstance(first, type) or owner not in first.__mro__:
                return None
            cls = first
        if cls is (checker.me or owner):
            return None
    except Exception:                                   # a class that can't be compared
        return None
    family, key = checker.family, id(cls)
    held = None if family is None else family.get(key)
    found = None if held is None else held()
    if found is None:
        with CACHE_LOCK:
            family = checker.family
            if family is None:
                family = checker.family = {}
        from ._wrapping import wrap_callable            # here: that module is built on this one
        made = wrap_callable(checker.fn, checker.allow_subclass, check_return, owner, checker.skip_first,
                              checker.convert, checker.coerce, checker.deep, mark, checker.extra_defaults,
                              checker.rewrite_defaults is IN_PLACE, cls, family, warn = checker.warn)
        with CACHE_LOCK:
            held = family.get(key)
            found = None if held is None else held()    # another thread may have been quicker
            if found is None:
                found = made
                family[key] = weakref.ref(made, partial(_forget_wrapper, family, key))
                kept = kept_of(cls, True)
                if kept is not None:
                    kept[id(made)] = made
                else:
                    _HELD_FOR_CLASSES.append(made)
    return found


def elsewhere(checker: "PreparedChecker", args: tuple[Any, ...], check_return: bool,
               mark: "Callable[[], dict[str, Any] | None] | None") -> Any:
    """
    Asked by the general path before it checks a call: the wrapper the call belongs to instead
    (see ``_route``), or ``None``. Whether an annotation that is checked uses ``Self`` at all is
    known once the annotations are resolved, which the first call does here.
    """
    flags = checker.self_in
    if flags is None:
        checker._prepare(args)
        flags = checker.self_in
    if not flags & (SELF_ANYWHERE if check_return else SELF_IN_PARAMETERS):       # type: ignore[operator]
        return None
    return _route(checker, args, check_return, mark)


def return_router(checker: "PreparedChecker", mark: Any) -> Callable[[Any, tuple[Any, ...]], Any]:
    """
    ``check_return(result, args)`` for a wrapper that tests ``-> Self`` against the class of the
    call: a result that fails goes to the checker of that class, which converts it or says what
    is wrong (``checker`` itself where the call was made on its own class).
    """
    def check_return(result: Any, args: tuple[Any, ...]) -> Any:
        other = _route(checker, args, True, mark)
        if other is None:
            return checker.check_return(result)
        of_class = other.__globals__["_pv_checker"]
        if not of_class.ready:
            of_class._prepare(args)
        return of_class.check_return(result)
    return check_return
