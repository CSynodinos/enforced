"""
The environment variables enforced reads, and the switches they set: every check off, when a
wrapper is compiled (colours are clitint's: ``turn_colours_off`` and its variables). Each switch can also be set from code (``turn_validation_off``,
``set_compile_after``, ``turn_colours_off`` ...): those functions are the public way in, and the
names of the variables (``EnvVar``) are the package's own (the owner's decision, 2026-10-15).
"""
from enum import StrEnum
import os


class EnvVar(StrEnum):
    """
    Every environment variable enforced reads. A member is its name, as a ``str``:
    ``os.environ[EnvVar.VALIDATION_OFF] = "1"``. Private: what a program sets from code goes through
    the functions below, and the variables are documented by their names.
    """
    #* "1": no check at all. Every API hands back what it was given (see ``validation_off``).
    VALIDATION_OFF = "ENFORCED_VALIDATION_OFF"
    #* A number: how many calls a function takes on the general path before its wrapper is compiled.
    COMPILE_AFTER = "ENFORCED_COMPILE_AFTER"
    #* The colours are clitint's, and so are their variables (``CLITINT_COLOURS_OFF``, ``NO_COLOR``,
    #* ``FORCE_COLOR`` ...): enforced reads none of them (2026-11-15, the owner's decision).


def validation_off() -> bool:
    """Whether ``ENFORCED_VALIDATION_OFF=1`` is set in the environment right now."""
    return os.environ.get(EnvVar.VALIDATION_OFF, "0") == "1"


#* Read once, when enforced is imported, and asked by every API as its first step. Not read again at
#* each call: looking a name up in the environment costs about as much as a checked call does, and
#* a function decorated while the checks were on stays checked whatever is set afterwards. So the
#* variable has to be set before the program starts (or before the first import of enforced).
VALIDATION_OFF: bool = validation_off()


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


#* Read once, like VALIDATION_OFF. A wrapper takes the value that holds when it is made.
COMPILE_AFTER: int = compile_after()


# ── the same switches, from code ─────────────────────────────────────────────

def turn_validation_off() -> None:
    """
    Switch every check off, from now on: what is decorated (``validate``, ``enforce``,
    ``dataclass``) or called (``validate_function``, ``validate_record``) after this is handed
    back as it was given, as with ``ENFORCED_VALIDATION_OFF=1``.

    What was decorated before stays checked: a decorator has already made its wrapper, and the
    wrapper doesn't ask at each call (that would cost every checked call). So call it before the
    modules whose functions are to stay unchecked are imported::

        import enforced
        enforced.turn_validation_off()
        import app              # decorated with the checks off
    """
    global VALIDATION_OFF
    VALIDATION_OFF = True


def turn_validation_on() -> None:
    """Switch the checks back on, from now on (``turn_validation_off``): what is decorated after this is checked."""
    global VALIDATION_OFF
    VALIDATION_OFF = False


def validation_is_off() -> bool:
    """Whether the checks are switched off (by ``ENFORCED_VALIDATION_OFF=1`` or ``turn_validation_off``)."""
    return VALIDATION_OFF


def set_compile_after(calls: int) -> None:
    """
    After how many calls a checked function's wrapper is compiled (64 unless
    ``ENFORCED_COMPILE_AFTER`` says otherwise; 1: at the first call). For functions decorated
    from now on: a wrapper takes the number that holds when it is made.
    """
    global COMPILE_AFTER
    if type(calls) is not int:
        raise TypeError(f"set_compile_after takes a whole number of calls, got {type(calls).__name__}")
    if calls < 1:
        raise ValueError(f"set_compile_after takes 1 or more calls, got {calls}")
    COMPILE_AFTER = calls
