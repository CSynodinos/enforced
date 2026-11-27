"""
The names in a wrapper's globals that Python code reads or writes by string in more than one module.

Generated code finds everything it needs in its globals under a `_pv_` name (CODEGEN.md, "Names"). Most of
those names are put in and read back by one module. The ones below cross a module boundary: one module puts
the value in, another looks it up. A misspelt string there doesn't fail; it finds nothing. Written as these
constants, a misspelling is a `NameError` at import. Generated source still spells them out (a test holds
that the two agree: `test_shared_names_are_those_of_the_generated_code`).

Imports nothing: it is the bottom of `_validator`'s order.
"""

#* What a stub calls until it is compiled (`BOOT_CODES`). Its presence marks a wrapper made by
#* `wrap_callable` (`_is_checked`, `_errors`).
BOOTSTRAP_CODE_KEY = "_pv_bootstrap"

#* The wrapper's checker. Not read by generated code: how `enforce` (`adopt`) and `Self` routing reach it.
CHECKER_CODE_KEY = "_pv_checker"

#* What the wrapper calls: `checker.call` (`generate_wrapper`), or the function itself in a pass-through
#* (`PLAIN_CODES`, `_unchecked`).
FUNCTION_CODE_KEY = "_pv_function"

#* The arguments a dataclass `__init__` wrapper has checked, in the globals of the generated `__setattr__`
#* while the standard `__init__` runs (`mark`): written by `_codegen` and `_general_path`, read by `_assignment`.
INIT_ARGS_CODE_KEY = "_pv_init_args"
INIT_KWARGS_CODE_KEY = "_pv_init_kwargs"
