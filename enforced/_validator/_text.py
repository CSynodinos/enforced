"""How values, types and origins are shown in a message, and how an error's lines are put together."""
from .. import _formatting_tool
from .._compat import class_repr, PUBLIC_MODULES
from .._formatting_tool import coloured, escapes, formatter
from types import BuiltinFunctionType, FunctionType
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ._errors import Problem


OWNER_ATTR = "__enforced_owner__"
_FUNCTIONS = (FunctionType, BuiltinFunctionType)         # what inspect.isfunction and inspect.isbuiltin accept


class _TraceReset:
    """
    Goes in front of every message: the escape sequence that switches the terminal's attributes
    off again, so that Python's own colouring of the ``InvalidDataError:`` line doesn't run into
    the message. It is worked out when a message is built, not at import: with colours switched
    off later on, it is the empty string like every other colour.
    """
    __slots__ = ()

    def __str__(self) -> str:
        return formatter("", "bold")

    def __add__(self, text: str) -> str:
        return formatter("", "bold") + text

    def __radd__(self, text: str) -> str:
        return text + formatter("", "bold")


break_trace_colouring = _TraceReset()


def made_dataclass(cls: Any) -> bool:
    """Whether ``cls`` was made a dataclass itself (a plain subclass of a dataclass wasn't)."""
    return "__dataclass_fields__" in vars(cls)


#* The escape sequences of the styles the messages below are written with (see ``escapes``), made
#* when the first coloured message is, and their plain counterpart: nothing at all.
_STYLES: tuple[str, ...] = ()
_NO_STYLES = ("",) * 6


def _styles() -> tuple[str, ...]:
    global _STYLES
    _STYLES = escapes("bold_magenta", "bold", "bold_blue")
    return _STYLES


#* On a function: (its id, its owner then, the label without colours, the label with them). The
#* label is in every message, and the same each time; the id because ``functools.wraps`` copies the
#* attribute to another function, the owner because a method finds its class at its first call.
_LABEL = "__enforced_label__"
#* On a version of ``enforced.dispatch``: what makes its label (``<Version 2 (str) of <Function worker>,
#* line 16>``), set where it is registered (``_dispatch._errors.version_label``). A version is usually
#* named ``_``, and ``<Function _>`` said neither which version nor which dispatcher.
VERSION_ATTR = "__enforced_version__"


def describe_origin(origin_obj: Any) -> str:
    """Label for messages: <Function f>, <Method A.run>, <Class A>, <Dataclass P>."""
    if type(origin_obj) is FunctionType:                # the usual origin, read without a failed lookup
        own = origin_obj.__dict__
        if (version := own.get(VERSION_ATTR)) is not None:
            return version()
        owner = own.get(OWNER_ATTR)
        kept = own.get(_LABEL)
        on = coloured()
        if kept is not None and kept[0] == id(origin_obj) and kept[1] is owner:
            return kept[3] if on else kept[2]
        plain, rich = _label(origin_obj, owner, origin_obj.__name__, False), _label(origin_obj, owner, origin_obj.__name__, True)
        try:
            own[_LABEL] = (id(origin_obj), owner, plain, rich)
        except Exception:                               # a read-only namespace: computed every time
            pass
        return rich if on else plain
    owner = getattr(origin_obj, OWNER_ATTR, None)
    return _label(origin_obj, owner, getattr(origin_obj, "__name__", type(origin_obj).__name__), coloured())


def _label(origin_obj: Any, owner: Any, name: str, on: bool) -> str:
    if isinstance(origin_obj, type):
        kind = "Dataclass" if made_dataclass(origin_obj) else "Class"
    elif owner is not None and (name == "__init__" or name == "__new__"):      # building an instance of the class
        kind = "Dataclass" if made_dataclass(owner) else "Class"
        name = owner.__name__
    elif owner is not None:
        kind = "Method"
        name = f"{owner.__name__}.{name}"
    elif name == "__init__":
        #* Untagged __init__ (e.g. passed straight to validate_record): best effort from the qualname.
        kind = "Class"
        name = getattr(origin_obj, "__qualname__", name).removesuffix(".__init__")
    elif isinstance(origin_obj, _FUNCTIONS):
        kind = "Function"
    else:
        kind = "Callable"

    #* One piece, the sequences as constants: what four ``formatter`` calls put together.
    magenta, plain, bold, unbold, blue, unblue = (_STYLES or _styles()) if on else _NO_STYLES
    return f"<{bold}{magenta}{kind}{plain}{unbold} {blue}{name}{unblue}>"


def short_repr(value: Any, limit: int = 40) -> str:
    """
    Safe, truncated repr for error messages. What it shows is the start of ``repr(value)`` (see ``bounded_repr``); a large
    built-in container isn't formatted in full to get there (see ``bounded_repr``).
    """
    try:
        text = bounded_repr(value, limit)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"
    return text if len(text) <= limit else text[:limit - 3] + "..."


#* The built-in containers a message may meet with millions of items: (opening, closing, what it
#* prints for itself when it contains itself).
_BRACKETS: dict[type, tuple[str, str, str]] = {
    list: ("[", "]", "[...]"), tuple: ("(", ")", "(...)"), dict: ("{", "}", "{...}"),
    set: ("{", "}", "set(...)"), frozenset: ("frozenset({", "})", "frozenset(...)"),
    }


def bounded_repr(value: Any, budget: int, _inside: tuple[int, ...] = ()) -> str:
    """
    ``repr(value)``, or for a built-in container or text the beginning of it: at least ``budget``
    characters, or all there is. ``repr`` builds the whole text first, which for a list of three
    million items takes 48 ms and the memory of all of it, to show forty characters. Here the
    items are formatted one at a time, until there is enough.
    """
    kind = type(value)
    if kind is str or kind is bytes or kind is bytearray:
        if len(value) <= budget:
            return repr(value)
        start = value[:budget]
        single, double = ("'", '"') if kind is str else (b"'", b'"')
        #* repr writes text between single quotes, unless it holds one and no double quote. The
        #* start is written as the whole would be only where that test gives both the same answer.
        if (single in start and double not in start) == (single in value and double not in value):
            return repr(start)
        if kind is not str:
            return repr(value)
        body = repr(start)[1:-1]
        return '"' + body if single in value and double not in value else "'" + body.replace("'", "\\'")
    brackets = _BRACKETS.get(kind)
    if brackets is None or not value:
        #* A class under a module that 3.13 alone has: named as every other version names it. Not any text that looks like it.
        if PUBLIC_MODULES and isinstance(value, type) and value.__module__ in PUBLIC_MODULES:
            return class_repr(value)
        return repr(value)
    opening, closing, itself = brackets
    if id(value) in _inside:
        return itself
    inside = _inside + (id(value),)
    parts: list[str] = []
    size = len(opening)                                 # the length of what is written so far
    for item in (value.items() if kind is dict else value):
        #* What an item may still fill. One that is cut short is longer than that, so the test
        #* below ends the loop with it: nothing is ever written after an item that isn't whole.
        left = max(budget - size, 8)
        if kind is dict:
            key = bounded_repr(item[0], left, inside)
            part = key if len(key) > left else f"{key}: {bounded_repr(item[1], left, inside)}"
        else:
            part = bounded_repr(item, left, inside)
        size += len(part) + (2 if parts else 0)
        parts.append(part)
        if size > budget:                               # enough to fill the message: the rest isn't looked at
            return opening + ", ".join(parts)
    if kind is tuple and len(parts) == 1:
        parts[0] += ","
    return opening + ", ".join(parts) + closing


def render_error(problems: "list[Problem]", context: str) -> str:
    noun = "problem" if len(problems) == 1 else "problems"
    #* Coloured or not: asked once for the whole message (what ``one_decision`` does, without the
    #* context manager: this runs for every message that is read).
    _formatting_tool._decided = on = _formatting_tool.colours_on()
    try:
        lines = str(problems[0]) if len(problems) == 1 else "\n    -> ".join([str(p) for p in problems])
        if on:
            red, plain, bold, unbold = _COUNT or _count_styles()
            return f"{bold}{unbold}{red}{len(problems)}{plain} {noun} found in {context}:\n    -> {lines}"
        return f"{len(problems)} {noun} found in {context}:\n    -> {lines}"
    finally:
        _formatting_tool._decided = None


_COUNT: tuple[str, ...] = ()


def _count_styles() -> tuple[str, ...]:
    global _COUNT
    _COUNT = escapes("bold_red", "bold")
    return _COUNT
