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
