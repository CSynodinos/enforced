from ._environment import EnvVar
from typing import Any
import os
import sys


COLOURS_OFF = EnvVar.COLOURS_OFF  # the name it had before the variables were gathered in EnvVar

#* The styles a spec may name, and the escape sequence that switches each on. They are the ones the
#* package's own messages use: it used to hand a spec to termcolor, which knows many more, and was
#* its only dependency (the owner's decision, 2026-10-13: none at all, and only what is used).
#* The sequences are the ones termcolor wrote, so every message is the text it was.
STYLES: dict[str, str] = {
    "bold": "\x1b[1m",
    "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m", "blue": "\x1b[34m",
    "magenta": "\x1b[35m", "cyan": "\x1b[36m",
    "orange": "\x1b[38;2;255;165;0m",
    }
_RESET = "\x1b[0m"


def colours_on() -> bool:
    """
    Whether a message is coloured now.

    A message is one string, and where it ends up isn't known when it is built: an uncaught error
    goes to stderr, ``print(e)`` to stdout, a logger to a file. So colours are used only when both
    standard streams are terminals. Redirect either one (``2> errors.log``, ``| less``, a CI job)
    and messages are plain: no escape sequence lands in a file.

    The environment decides first, in this order: ``ENFORCED_COLOURS_OFF=1``, ``NO_COLOR`` and
    ``ANSI_COLORS_DISABLED`` switch colours off, ``FORCE_COLOR`` switches them on whatever the
    streams are, and ``TERM=dumb`` switches them off. Read at every message, so a change takes
    effect at once.
    """
    env = os.environ
    #* Read from ``os.environ`` as it is now: a program may have put another mapping in its place.
    data = getattr(env, "_data", None) if _FAST else None
    if type(data) is not dict:
        if env.get(EnvVar.COLOURS_OFF, "0") == "1" or EnvVar.NO_COLOR in env or EnvVar.ANSI_COLORS_DISABLED in env:
            return False
        if EnvVar.FORCE_COLOR in env:
            return True
        if env.get(EnvVar.TERM) == "dumb":
            return False
        return _both_terminals()
    if data.get(_K_OFF) == _V_ONE or _K_NO_COLOR in data or _K_ANSI in data:
        return False
    if _K_FORCE in data:
        return True
    if data.get(_K_TERM) == _V_DUMB:
        return False
    return _both_terminals()


#* ``os.environ`` encodes the name at every lookup and decodes the value: five of them took 1 µs, a
#* quarter of what rendering a message cost. Below it is the dictionary it keeps, which is asked
#* directly, with the names and the two values encoded once, the way ``os.environ`` does it on
#* this platform. It is the same data: what ``os.environ`` is given lands there. Where a Python
#* has no such dictionary, ``os.environ`` is asked as before.
_FAST = False
try:
    _encode_key, _encode_value = os.environ.encodekey, os.environ.encodevalue      # type: ignore[attr-defined]
    _K_OFF, _K_NO_COLOR, _K_ANSI, _K_FORCE, _K_TERM = (_encode_key(str(name)) for name in (
        EnvVar.COLOURS_OFF, EnvVar.NO_COLOR, EnvVar.ANSI_COLORS_DISABLED, EnvVar.FORCE_COLOR, EnvVar.TERM))
    _V_ONE, _V_DUMB = _encode_value("1"), _encode_value("dumb")
    _FAST = type(os.environ._data) is dict                                          # type: ignore[attr-defined]
except Exception:
    _FAST = False


#* (sys.stdout, sys.stderr, whether both are terminals): asked again only when a stream was replaced.
_streams: tuple[Any, Any, bool] = (None, None, False)


def _both_terminals() -> bool:
    global _streams
    out, err = sys.stdout, sys.stderr
    if _streams[0] is out and _streams[1] is err:
        return _streams[2]
    answer = _is_terminal(out) and _is_terminal(err)
    _streams = (out, err, answer)
    return answer


def _is_terminal(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:                   # no stream at all (pythonw), a closed one, an object without isatty
        return False


#* While one message is rendered: the answer of ``colours_on`` for all of it (None: ask each time).
_decided: bool | None = None


class one_decision:
    """
    ``with one_decision():`` around the rendering of a message asks once whether it is coloured,
    where every ``formatter`` call in it would ask again (the environment is slow to read).
    """
    __slots__ = ()

    def __enter__(self) -> None:
        global _decided
        _decided = colours_on()
        return

    def __exit__(self, *_: Any) -> None:
        global _decided
        _decided = None
        return


def _escapes(spec: str) -> tuple[str, str]:
    """
    What is written in front of and behind a text for ``spec``: the sequences that switch its
    styles on (``bold`` first, as termcolor had it), and the one that switches everything off.
    A spec names styles from ``STYLES``, joined by ``_`` in any order: ``"bold_red"``, ``"cyan"``.
    """
    names = spec.split("_")
    unknown = [name for name in names if name not in STYLES]
    if unknown:
        raise ValueError(f"unknown style {unknown[0]!r} in {spec!r}: a spec is made of {', '.join(STYLES)}, joined by '_'")
    return "".join([STYLES[name] for name in sorted(set(names), key = lambda name: name != "bold")]), _RESET


def formatter(text: Any, spec: str) -> str:
    """
    ``text`` in the styles ``spec`` names, or as it is when colours are off (see ``colours_on``).

    Args:
        text (Any): The text, or any object: its ``str`` is what is written.
        spec (str): Styles joined by ``_``, in any order: ``"bold_red"``, ``"cyan"``, ``"bold"``.
            The styles are ``bold`` and the colours ``red``, ``green``, ``yellow``, ``blue``,
            ``magenta``, ``cyan`` and ``orange`` (``STYLES``). Any other name is a ``ValueError``.

    Returns:
        str: The text between the escape sequences of its styles, or the plain text.

    Example:
        >>> formatter("hello", "bold_red")
        '\\x1b[1m\\x1b[31mhello\\x1b[0m'    # Imagine colour
    """
    if not (colours_on() if _decided is None else _decided):
        return str(text)
    escapes = _ESCAPES.get(spec)
    if escapes is None:
        escapes = _ESCAPES[spec] = _escapes(spec)
    return escapes[0] + str(text) + escapes[1]


#* spec -> what ``_escapes`` answered.
_ESCAPES: dict[str, tuple[str, str]] = {}


def escapes(*specs: str) -> tuple[str, ...]:
    """
    What is written in front of and behind a text for each of ``specs``, in one flat tuple:
    ``before, after, before, after ...``. For a message that is put together in one piece, with
    the sequences as constants (see ``_text.describe_origin``): a ``formatter`` call per coloured
    word was a third of what rendering a message cost.
    """
    return tuple([part for spec in specs for part in _escapes(spec)])


def coloured() -> bool:
    """Whether the message being rendered is coloured: the one decision made for it, or ``colours_on()``."""
    return colours_on() if _decided is None else _decided
