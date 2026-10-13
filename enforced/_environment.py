"""The environment variables enforced reads, and the switch that turns every check off."""
from enum import StrEnum
import os


class EnvVar(StrEnum):
    """
    Every environment variable enforced reads. A member is its name, as a ``str``:
    ``os.environ[EnvVar.TYPECHECK_OFF] = "1"``.
    """
    #* "1": no check at all. Every API hands back what it was given (see ``typecheck_off``).
    TYPECHECK_OFF = "ENFORCED_TYPECHECK_OFF"
    #* A number: how many calls a function takes on the general path before its wrapper is compiled.
    COMPILE_AFTER = "ENFORCED_COMPILE_AFTER"
    #* "1": plain messages, whatever the other colour variables say.
    COLOURS_OFF = "ENFORCED_COLOURS_OFF"
    #* The conventions other tools follow too. Set to anything: plain messages ...
    NO_COLOR = "NO_COLOR"
    ANSI_COLORS_DISABLED = "ANSI_COLORS_DISABLED"
    #* ... coloured messages, also where the output is no terminal ...
    FORCE_COLOR = "FORCE_COLOR"
    #* ... and "dumb": plain messages.
    TERM = "TERM"


def typecheck_off() -> bool:
    """Whether ``ENFORCED_TYPECHECK_OFF=1`` is set in the environment right now."""
    return os.environ.get(EnvVar.TYPECHECK_OFF, "0") == "1"


#* Read once, when enforced is imported, and asked by every API as its first step. Not read again at
#* each call: looking a name up in the environment costs about as much as a checked call does, and
#* a function decorated while the checks were on stays checked whatever is set afterwards. So the
#* variable has to be set before the program starts (or before the first import of enforced).
TYPECHECK_OFF: bool = typecheck_off()


#* Tiered compilation. A checked function starts on the general path, which binds and checks a call
#* step by step, and gets a wrapper compiled for its signature only once it has been called this
#* often. Compiling costs 15 µs where a function of the same shape has been compiled before and
#* 200 to 900 µs where none has; a call on the general path costs 0.2 to 0.5 µs more than a compiled
#* one. So a function called a handful of times never earns its wrapper back, and a program that
#* decorates a thousand functions paid for a thousand at startup. 64 is about where the cheaper of
#* the two compilations is paid off; a function that runs hot gets there at once and loses 15 µs.
_COMPILE_AFTER_DEFAULT = 64


def compile_after() -> int:
    """``ENFORCED_COMPILE_AFTER`` as a number (1, or 0: compile on the first call), or the default."""
    try:
        return max(1, int(os.environ.get(EnvVar.COMPILE_AFTER, _COMPILE_AFTER_DEFAULT)))
    except ValueError:
        return _COMPILE_AFTER_DEFAULT


#* Read once, like TYPECHECK_OFF. A wrapper takes the value that holds when it is made.
COMPILE_AFTER: int = compile_after()
