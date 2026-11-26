"""
The colours of the messages: clitint's, where it is installed (``pip install "enforced[colour]"``), else
plain text. The only module of the package that imports clitint; every other one imports from here.

Without clitint the functions below keep its signatures and return types, and every message is plain:
``colours_on`` always answers False, so nothing ever writes an escape sequence.
"""
from typing import Any
import re

__all__ = ["HAS_CLITINT", "colours_on", "decide", "decision", "escapes", "formatter", "release", "strip_colours",
           "turn_colours_off", "turn_colours_on"]

#* The plain versions come first and clitint's replace them where it is installed. The other way round
#* (`except ImportError:` defining them) a static checker without clitint took each name for the
#* import that can't be resolved: pyright reported "unknown import symbol" at every module that uses one.

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def formatter(text: Any, spec: str) -> str:
    """``text`` as it is: there are no colours without clitint."""
    return str(text)


def colours_on() -> bool:
    """Never: there are no colours without clitint."""
    return False


def decide() -> bool:
    """clitint keeps one answer for a whole message; here it is always False."""
    return False


def decision() -> bool | None:
    """Nothing is ever decided without clitint."""
    return None


def release() -> None:
    """Nothing to forget without clitint."""


def escapes(*specs: str) -> tuple[str, ...]:
    """Empty sequences, two per spec (in front of a text and behind it), as clitint gives them."""
    return ("", "") * len(specs)


def strip_colours(text: str) -> str:
    """``text`` without ANSI formatting (a value's own text may hold some)."""
    return _ANSI.sub("", text)


def turn_colours_off() -> None:
    """Plain text from now on: always the case without clitint (``pip install "enforced[colour]"``)."""


def turn_colours_on() -> None:
    """Coloured text from now on, where clitint is installed (``pip install "enforced[colour]"``); without it, nothing."""


HAS_CLITINT: bool
try:
    from clitint import (                                # type: ignore[import-not-found, no-redef, unused-ignore]  # optional: enforced[colour]
        colours_on,
        decide,
        decision,
        escapes,
        formatter,
        release,
        strip_colours,
        turn_colours_off,
        turn_colours_on,
        )
    HAS_CLITINT = True
except ImportError:
    HAS_CLITINT = False
