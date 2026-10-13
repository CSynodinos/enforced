from termcolor import colored
from functools import lru_cache
from typing import Any
import os
import sys


ATTRS = {"bold", "dark", "underline", "blink", "reverse", "concealed"}
COLORS = {"grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white", "orange"}
COLOURS_OFF = "ENFORCED_COLOURS_OFF"
ORANGE_RGB = (255, 165, 0)
TEAL_RGB = (0, 128, 128)


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
    if env.get(COLOURS_OFF, "0") == "1" or "NO_COLOR" in env or "ANSI_COLORS_DISABLED" in env:
        return False
    if "FORCE_COLOR" in env:
        return True
    if env.get("TERM") == "dumb":
        return False
    return _both_terminals()


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

    def __exit__(self, *exc: Any) -> None:
        global _decided
        _decided = None


@lru_cache(maxsize = 256)
def _parse(spec: str) -> tuple[Any, str | None, tuple[str, ...]]:
    """``(color, on_color, attrs)`` for a spec such as ``"red_bold_on_blue"``. Cached: the specs are few."""
    color: Any = None
    on_color = None
    attrs = []
    tokens = spec.split("_")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "light" and i + 1 < len(tokens):      # light_red
            tok = f"light_{tokens[i + 1]}"
            i += 1
        if tok == "on" and i + 1 < len(tokens):         # on_red, on_light_red
            i += 1
            bg = tokens[i]
            if bg == "light" and i + 1 < len(tokens):
                i += 1
                bg = f"light_{tokens[i]}"
            on_color = f"on_{bg}"
        elif tok in ATTRS:
            attrs.append(tok)
        else:
            color = tok
        i += 1

    # Handle custom RGB colors for orange and teal
    match color:
        case "orange":
            color = ORANGE_RGB
        case "teal":
            color = TEAL_RGB
    return color, on_color, tuple(attrs)


#* Stands for the text while termcolor is asked what it writes around it.
_MARK = "\x00enforced\x00"


@lru_cache(maxsize = 256)
def _escapes(spec: str) -> tuple[str, str]:
    """
    What termcolor writes in front of and behind a text for ``spec``: the escape sequences that
    switch the style on, and the one that resets it. They depend on the spec alone, so termcolor
    is asked once per spec and not once per word of every message: a message of one problem has
    some fifteen coloured words, and the calls were most of what printing it cost (review finding 17).
    """
    color, on_color, attrs = _parse(spec)
    #* force_color: whether to colour is decided by ``colours_on``. termcolor would make its own
    #* decision, from stdout alone, and keeps its first answer for the life of the process.
    before, _, after = colored(_MARK, color, on_color, attrs = list(attrs), force_color = True).partition(_MARK)
    return before, after


def formatter(text: Any, spec: str) -> str:
    """
    Format the given text with the specified color, background color, and attributes.

    Args:
        text (Any): The text/object to be formatted.
        spec (str): The formatting specification string, e.g., "red_bold_on_blue".

    Returns:
        str: The formatted text with the specified color, background color, and attributes,
        or the plain text when colours are off (see ``colours_on``).

    Supports:
        - Text colors: grey, red, green, yellow, blue, magenta, cyan, white
        - Background colors: on_grey, on_red, on_green, on_yellow, on_blue, on_magenta, on_cyan, on_white
        - Attributes: bold, dark, underline, blink, reverse, concealed
        - Custom colors: orange

    Example:
        >>> formatter("hello", "red_bold_on_blue")  # Returns "hello" formatted with red text, bold attribute, and blue background.
    """
    if not (colours_on() if _decided is None else _decided):
        return str(text)
    before, after = _escapes(spec)
    return before + str(text) + after
