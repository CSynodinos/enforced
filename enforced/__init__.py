from ._dataclass.api import dataclass
from ._typechecker import *
from ._typechecker._type_data_model import TypeModel
from .utils import protect, Ok, Err
from ._environment import set_compile_after, turn_typecheck_off, turn_typecheck_on, typecheck_is_off
from ._formatting_tool import turn_colours_off, turn_colours_on


__version__ = "1.0.0"

#* What the package offers. Type checkers read this list too: in a package that ships ``py.typed``,
#* a name imported above only counts as part of the package when it is named here.
__all__ = [
    "Check",
    "Err",
    "Ok",
    "TypeCheckerError",
    "TypeCheckerWarning",
    "TypeModel",
    "dataclass",
    "enforce_class",
    "enforce",
    "protect",
    "set_compile_after",
    "typecheck",
    "typecheck_record",
    "typecheck_function",
    "turn_colours_off",
    "turn_colours_on",
    "turn_typecheck_off",
    "turn_typecheck_on",
    "typecheck_is_off",
    ]
