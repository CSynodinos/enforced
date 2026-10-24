from ._typechecker import *
from ._typechecker._type_data_model import TypeModel
from ._environment import set_compile_after, turn_typecheck_off, turn_typecheck_on, typecheck_is_off
from ._formatting_tool import turn_colours_off, turn_colours_on
from ._json import to_json
from ._dispatch.api import dispatch, dispatchmethod
from ._dataclass.api import (
    dataclass,
    make_dataclass,
    )
from .utils import protect, Ok, Err
from dataclasses import field, asdict


__version__ = "0.1.0"

#* What the package offers. Type checkers read this list too: in a package that ships ``py.typed``,
#* a name imported above only counts as part of the package when it is named here.
__all__ = [
    "Check",
    "Enforced",
    "Err",
    "Ok",
    "InvalidDataError",
    "InvalidDataWarning",
    "TypeModel",
    "dataclass",
    "dispatch",
    "dispatchmethod",
    "enforce_class",
    "enforce",
    "make_dataclass",
    "field",
    "asdict",
    "protect",
    "to_json",
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
