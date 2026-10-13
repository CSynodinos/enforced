"""How values, types and origins are shown in a message, and how an error's lines are put together."""
from ..formatting_tool import formatter, one_decision
from typing import Any, TYPE_CHECKING
import inspect

if TYPE_CHECKING:
    from ._errors import Problem


OWNER_ATTR = "__typecheck_owner__"


class _TraceReset:
    """
    Goes in front of every message: the escape sequence that switches the terminal's attributes
    off again, so that Python's own colouring of the ``TypeCheckerError:`` line doesn't run into
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


def describe_origin(origin_obj: Any) -> str:
    """Label for messages: <Function f>, <Method A.run>, <Class A>, <Dataclass P>."""
    owner = getattr(origin_obj, OWNER_ATTR, None)
    name = getattr(origin_obj, "__name__", type(origin_obj).__name__)
    Class_str = lambda: formatter("Class", "bold_magenta")
    Dataclass_str = lambda: formatter("Dataclass", "bold_magenta")

    if inspect.isclass(origin_obj):
        kind = Dataclass_str() if made_dataclass(origin_obj) else Class_str()
    elif owner is not None and (name == "__init__" or name == "__new__"):      # building an instance of the class
        kind = Dataclass_str() if made_dataclass(owner) else Class_str()
        name = owner.__name__   # type: ignore[attr-defined]
    elif owner is not None:
        kind = formatter("Method", "bold_magenta")
        name = f"{owner.__name__}.{name}"
    elif name == "__init__":
        #* Untagged __init__ (e.g. passed straight to typecheck_record): best effort from the qualname.
        kind = Class_str()
        name = getattr(origin_obj, "__qualname__", name).removesuffix(".__init__")
    elif inspect.isfunction(origin_obj) or inspect.isbuiltin(origin_obj):
        kind = formatter("Function", "bold_magenta")
    else:
        kind = formatter("Callable", "bold_magenta")

    return f"<{formatter(kind, 'bold')} {formatter(name, 'bold_blue')}>"


def short_repr(value: Any, limit: int = 40) -> str:
    """
    Safe, truncated repr for error messages. What it shows is the start of ``repr(value)``; a large
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
    with one_decision():                                # coloured or not: asked once for the whole message
        msg = (
            f"{formatter(len(problems), 'bold_red')} {noun} found in {context}:\n{' ' * 3} -> "
            + f"\n{' ' * 3} -> ".join(str(p) for p in problems)
            )
        return break_trace_colouring + msg
