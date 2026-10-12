from ._dataclass_override import dataclass
from ._typechecker import *
from ._typechecker._type_data_model import TypeModel

__version__ = "1.0.0"

#* What the package offers. Type checkers read this list too: in a package that ships ``py.typed``,
#* a name imported above only counts as part of the package when it is named here.
__all__ = [
    "TypeCheckerError",
    "TypeModel",
    "dataclass",
    "enforce_class",
    "enforced",
    "skip_typecheck",
    "typecheck",
    "typecheck_from_dict",
    "typecheck_function",
    ]
