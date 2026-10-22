# enforced

A small runtime type checker in the style of pydantic. Python 3.14+, no dependencies (termcolor was the one, until 2026-10-13).
Its selling points are **speed and ease of use**. It is not trying to replace pydantic, so don't add
features that only make sense for a schema/serialisation library.

## Commands

```bash
python -m pytest -q tests          # unit tests (must all pass)
python tests/simulation.py -q      # scenario simulation; ends with "Simulation passed!" or raises
python tests/benchmark.py --quick  # benchmark vs pydantic, beartype, typeguard, attrs
python tests/benchmark.py --quick --skip-cold --cases "Validated|Errors"    # a faster, narrower run
python tests/benchmark.py --quick --report out/bench.md   # also write what is printed as a Markdown file (path must end in .md)
python tests/fuzz.py --save-baseline   # before changing the package: keep a copy of it in tests/.baseline (git-ignored)
python tests/fuzz.py                   # differential fuzz, that copy vs the working tree; ends with "Fuzz passed!" or exit 1
python tests/fuzz.py --ref HEAD        # the same against a git revision; --expect REGEX names an intended difference
python tests/fuzz.py --properties      # no baseline: what must hold in any version (errors, repeat calls, looser options)
pip install -e ".[dev]"                # the dev environment: editable install with pytest and mypy
python -m build                        # wheel + sdist from pyproject.toml (needs the "build" package)
```

Run them from the project root. `benchmark.py` needs `pydantic beartype typeguard attrs` installed (each is skipped if missing;
`pip install -e ".[bench]"` installs them). `tests/test_static_typing.py` runs mypy on `tests/static_typing_sample.py`
and is skipped when mypy isn't installed.
Set `ENFORCED_COLOURS_OFF=1` to get plain-text messages, and `ENFORCED_TYPECHECK_OFF=1` to switch every check off.
`ENFORCED_COMPILE_AFTER=n` sets after how many calls a wrapper is compiled (default 64). The tests and the simulation
run with 1 (see `tests/conftest.py`); `ENFORCED_COMPILE_AFTER=64 python -m pytest -q tests` runs the suite on the
general path instead. The benchmark's errors alone: `python tests/benchmark.py --skip-cold --cases "Errors"`.

## Public API

- `@typecheck` for functions and single methods. Options: `allow_subclass`, `check_return`, `convert`, `coerce`, `deep`,
  and `on_error` (keyword only; every API has it, see "How it works").
  It refuses a class.
- `@enforce` for plain classes: `__init__`, every method the class defines and the special methods a caller hands
  values to (`__call__`, `__getitem__`, `__new__` ...), with the same five options.
  `@enforce.exempt` marks a method it (or `dataclass`) is to leave alone (it was `skip_typecheck` until
  2026-10-15, the owner's choice of name; `enforce` is an object, `_Enforce`, so that checkers know `exempt`).
  `enforce` refuses a dataclass and anything that isn't a class.
- `Enforced` (the owner's request, 2026-10-17, for a dataframe schema library built on it): a base class whose
  `__init_subclass__` runs `enforce_members` on every class derived from it, options as class keywords.
- `@dataclass` (enforced's drop-in for `dataclasses.dataclass`): checks construction, defaults and assignment, and the
  methods the class defines (`check_methods`, on by default; `check_return` for what they return).
- `make_dataclass(name, fields, ...)` (the owner's addition, 2026-10-15): `dataclasses.make_dataclass` with
  `enforced.dataclass` as the decorator; the options of both (not the standard `decorator`).
- The decorators without the `@`: `typecheck_function(fn, args, kwargs, **options)` checks one call and makes it
  (`typecheck(fn)(*args, **kwargs)` in one step, the wrapper remembered), `enforce_class(cls, **options)` enforces a
  class that is already defined and returns it (`enforce`, options by keyword only).
- `typecheck_record(spec)` (it was `typecheck_from_dict` until 2026-10-13): a call described by a dictionary; it checks and returns `(args, kwargs)`, calling nothing.
- `@enforce` also checks properties: the setter's argument, and with `check_return` what the getter returns.
- `TypeModel[T]` and `enforced.data_types`: the models `Email`, `Url`, `Slug`, `PhoneNumber`, `SecretStr`, `Port`, and
  the `Annotated` aliases `NonEmptyStr`, `AwareDatetime`, `Probability`, `Percentage`, `Number`, `PositiveInt` ...
  (the owner's choice, 2026-10-16: `Url` is http/https only and takes every kind of host, refuses user info;
  `CountryCode` / `CurrencyCode` left to users, they need the ISO lists). `SecretStr` masks `repr`, `str()` and
  `format()`, and pickles through `str.__str__` (TypeModel's `__reduce__` calls `str(self)`, the mask).
  The new aliases' checks are named functions that raise `ValueError`, so the reason reads as a sentence.
- `to_json(obj, *, indent, reveal_secrets)` (`_json.py`; the owner's request, 2026-10-22, the name his): a value as
  JSON text. Walks it first (`_plain`), because `json.dumps` writes a `str` / `int` subclass natively, and so a
  `SecretStr`'s real text: masked unless `reveal_secrets` (a key always). Dataclasses, mappings, sequences,
  enums, dates (ISO), `Decimal` / `Fraction` / `UUID` / paths (text); anything else a `TypeError` with its path,
  a cycle or `NaN` a `ValueError`. No JSON Schema and no parsing (the owner: not now). Not on a checking path.
- `Check(fn)`: marks a callable in `Annotated` metadata as a check. A callable without the marker is one too (the short form).
- `protect(awaitable)`, `Ok`, `Err` (`utils.py`): the outcome of an awaitable as a value. `protect` is under `@typecheck`
  (what can't be awaited is a `InvalidDataError`, not an `Err`) and catches `Exception` only: cancellation goes through.
- The switches from code (the owner's decision, 2026-10-15: `EnvVar` is private, functions are the way in):
  `turn_typecheck_off()` / `turn_typecheck_on()` / `typecheck_is_off()`, `set_compile_after(n)`, `turn_colours_off()` /
  `turn_colours_on()`. `ENFORCED_TYPECHECK_OFF=1` makes every API return at once with what it was given (the user's
  design, 2026-10-13); `turn_typecheck_off()` does the same for what is decorated after it (existing wrappers stay).
- `InvalidDataWarning` (a `UserWarning`): what `on_error = "warn"` issues; `.error` is the error that was not raised.
- `error = ...` on every API (the owner's design, 2026-10-22: a library's callers catch the library's own error;
  `PLAN_error_type.md`): a subclass of `InvalidDataError`, the class of everything a checker raises. What refuses
  a decorator itself stays `InvalidDataError`. No global setting, on purpose (one library would change what
  every other raises). See "How it works", next to `on_error`.
- `InvalidDataError` (a `TypeError`): carries `.problems` as data (`kind`, `parameter`, `expected`, `value`, `origin`, `detail`).
  `e.errors()` / `e.json()` (the owner's design, 2026-10-17): pydantic's shape (`type` = the `kind`, `loc`, `msg`,
  `input`, `ctx`), `include_input=True` by default as in pydantic, `include_context`. Built on demand in
  `_messages.problem_details` (hooked into `_errors.details_of`: `_errors` comes first in the order). `loc` comes from
  `_errors.Where`, a `str` that also holds its steps (`step(path, text, *parts)`): every path to an item is made with
  `step`, never an f-string, or `errors()` reports the whole parameter. `jsonable` bounds and cleans the input
  (`SecretStr` through `str()`: its mask). `msg` has no value (it would leak with `include_input=False`); a test checks
  that it is part of the message. A message-only error is one entry, `"binding"` (a call that can't be bound) or `"error"`.

## Layout

```
pyproject.toml                the package: name, version (read from enforced.__version__), no
                              dependency, the `dev` and `bench` extras, py.typed as package data. setup.py is a shim
MANIFEST.in                   puts the whole tests/ folder into the sdist
LICENSE                       MIT
enforced/
  __init__.py                 exports dataclass, the typechecker API, TypeModel, Check, protect / Ok / Err; __version__ and
                              __all__. formatter is internal (the owner's decision, 2026-10-13: the module is private)
  py.typed                    empty marker: the package ships its own type information (PEP 561)
  data_types.py               Email, Port, PositiveInt ... (user-facing validated types)
  _environment.py             EnvVar (private: every environment variable the package reads), TYPECHECK_OFF,
                              COMPILE_AFTER, and the functions that set them from code (turn_typecheck_off ...)
  _formatting_tool.py         formatter() for coloured messages, and colours_on(): whether a message is coloured now
  utils.py                    protect (await something, return Ok(value) or Err(error)) and the two result classes,
                              which are standard frozen dataclasses (the user's decision: nothing in them is checked)
  _dataclass/                 enforced.dataclass
    api.py                    the decorator, and make_dataclass
    _init.py                  the wrapped __init__, the storing one, defaults and default_factory
    _assignment.py            the generated __setattr__, its first tier, the reporter of a value that fails
    _field_messages.py        "Field Order.qty of <Dataclass Order>: ..."
  _typechecker/               flat on purpose (the user's decision, 2026-10-13). Bottom first: a module imports,
                              at run time, only from those listed before it
    _lifetime.py              the weak annotation caches: held, holds, make_room, made_for, CACHE_LOCK
                              frame_above: the one way to a frame (inspect.currentframe; no sys._getframe,
                              the owner's decision 2026-10-16; a test reads the sources)
    _text.py                  short_repr, describe_origin, made_dataclass, render_error: how things are shown
    _errors.py                InvalidDataError, Problem, pending_error / said_error / field_error, pickling
    _checks.py                Check, metadata_checks, check_failure, describe_check
    _record_strings.py        read_annotation: a record's strings, parsed and never run
    _container.py             TypeContainer (annotation -> runtime types), TypeUnion, matches_type, is_abstract
    _messages.py              the sentences: subject, shape and type messages, expected_text, format_annotation
    _problems.py              type_problem, _invalid_reason, value_problems, unresolved_error
    _signatures.py            signature_of (and where a signature is kept), typed **kwargs, signature_stub
    _scope.py                 local names of string annotations: remember_scope, look_again, the sys.monitoring watcher
    _annotations.py           resolve_annotations, Self in an annotation, find_owner, tag_owner
    _specs.py                 compile_spec, compile_converter, predicate, deep_node, args_node, SLOW
    _defaults.py              check_defaults, where a converted default is put
    _slow_path.py             full_check, _realign_positional, the long way for a return value
    _checker.py               PreparedChecker: _prepare, _plan, check_inputs, check_return
    _self_routing.py          Self as the class of the call: _route, elsewhere, return_router, kept_of
    _general_path.py          make_fallback: check, convert, call, check the result
    _codegen.py               generate_wrapper, check_expr, the code cache, the stub code objects
    _wrapping.py              wrap_callable (stub, tiers), wrap_member
    _remembered.py            what typecheck_function and typecheck_record keep between calls
    _class_rules.py           what enforce and dataclass check in a class: enforce_members, the special-method
                              list, properties, adopt
    api.py                    the public functions and nothing else: typecheck, enforce (and enforce.exempt),
                              typecheck_function, enforce_class, typecheck_record
    _file_types.py            stand-in classes for typing.IO / TextIO / BinaryIO (isinstance knows what a file is)
    _type_conversion.py       convert/coerce rules, TypeModel conversion hook, FAILED sentinel
    _deep.py                  deep=True: node tree that checks items inside collections
    _type_data_model.py       TypeModel base class
tests/                        pytest, one file per subject; test_type_data_model / test_data_types / test_validated_types
                              cover validated values, test_enforced the class decorator and what each decorator refuses,
                              test_functional typecheck_function, enforce_class and what a record string may name,
                              test_future_annotations a module where every annotation is a string, test_static_typing
                              what a type checker is told (static_typing_sample.py is the file mypy reads),
                              test_scripts that run_tests.sh fails when a test does, test_formatter the colours,
                              test_utils protect / Ok / Err, test_environment EnvVar and the off switch.
                                                            test_known_issues.py holds the issues still open, as strict xfails (none at the moment).
                              conftest.py renders every message without colours (a test about colours switches them on)
                              and compiles wrappers at their first call (see "Tiered compilation")
tests/simulation.py           phases 1-6 by feature; every check is counted and any surprise fails the run.
                              Phase 7: the fixes of the code reviews, then the known issues (correct behaviour of
                              unfixed bugs): they never fail the run, and print FIXED once they pass (then make them
                              regular checks). Phase 8: an application end to end, re-entrancy, threads, stacked decorators.
                              Phase 9: protect, Ok and Err
tests/benchmark.py            benchmark + coverage matrix. A case of kind "own" (section "enforced only") runs against
                              enforced alone: typecheck_function, Self on a subclass, protect
tests/fuzz.py                 differential fuzz against a previous copy of the package, and property checks on the
                              working tree alone (not a pytest file). 29 ways to use an annotation (USES); on_error is a property there
```

## How it works (read before changing anything)

- **Where things are** (the split of 2026-10-13: `api.py` was 3,900 lines). `api.py` holds the public functions
  only. In a private module, a name that other modules use has no underscore (`_wrapping.wrap_callable`), and one
  that only its own file uses keeps it: the underscore on the module says "not public". The modules are layered
  (see "Layout"); the one import against the order is `_route`'s, of `wrap_callable`, made inside the function.
  A value that is rebound (a cache a test replaces, a limit) is read through its own module by the code that uses
  it: `from x import CACHE` takes the object as it is at import. So each cache lives in the module that reads it,
  and `api.py` reads `_remembered.RECORD_CACHE` / `_remembered.CALL_WRAPPERS` through the module. A test patches
  the module that looks a name up (`_checker.check_defaults`), not the one that defines it.
  On the dev machine's Windows mount each module costs about 7 ms to import (255 ms for the package, 60 before the
  split); on a native disk it is 19 ms (17 before).

- **Tiered compilation** (the user's request, 2026-10-13). A wrapper starts as a stub on the general path
  (`fallback` -> `check_inputs`), and `wrap_callable`'s `bootstrap` compiles it at call number
  `_environment.COMPILE_AFTER` (64; read once, taken by a wrapper when it is made). Compiling costs 15 µs for a
  shape seen before and 200-900 µs for a new one; a call on the general path costs 0.2-0.5 µs more than a compiled
  one. 400 functions called 3 times each: 33 ms before, 14 ms now. Both tiers must do the same: the whole suite passes
  on either (a fixture, `compiled_at_once`, skips the tests that look at a compiled wrapper, or count how often a
  dataclass checks a value, on the general path).
  **A dataclass is tiered too** (2026-10-13). Defining one compiles nothing. `storing_init` returns what makes the
  `__init__`, and `wrap_callable` asks for it (`upgrade`, in `bootstrap` -> `improve`) at the construction that
  compiles the wrapper, after `_prepare` (the storing `__init__` takes the defaults as the first call converted
  them). Until then the standard `__init__` runs and assigns, so an argument is checked twice. The generated
  `__setattr__` is made at assignment number `COMPILE_AFTER` (its own count); before, `wrap_setattr`'s bootstrap
  tests one field at a time (`test_of`: `compile_spec` -> `predicate`, made when the field is first assigned)
  and hands whatever fails to the reporter, which converts, lets a retyped field through or raises, as the
  generated code does. Define + first construction of a 6-field class: 0.58 ms before, 0.33 now. A test compares
  both tiers over 3 classes x 10 fields x 19 values x 5 option sets (`test_both_tiers_of_a_dataclass_do_the_same`).
- **The compiled wrapper.** `PreparedChecker` reduces every annotation to a *spec* (`("any",)`,
  `("isinstance", T)`, `("nobool", T)`, `("is", T)`, `("in", set)`, `("pred", callable)`) and exec-generates a wrapper
  per signature shape (`_CODE_CACHE`). The hot path only answers "definitely fine"; anything else goes to the
  slower path that builds the detailed error. Don't slow the valid-call path to improve the error path.
- **The general path makes one pass**, written out in `PreparedChecker.check_inputs` and laid out by `_plan`: bind,
  test each argument, convert what fails and can be, note the rest, a missing argument included. It replaced three
  passes (`_fast_ok`, `_convert`, `_type_problems`) and, for a missing argument, `full_check` with
  `Signature.bind_partial`. Those remain for what the pass doesn't take (`plan is None`: `*args` / `**kwargs`, `deep`
  items) and for what it leaves (`break`: a call that doesn't bind, or a missing argument next to a positional one
  that doesn't fit, where the full path looks for a better placement). A test runs 1,500 random calls per option set
  through both and compares outcome, order and wording. `plan` is assigned last in `_plan`: `check_inputs` goes by it
  alone, and another thread may be in it (the simulation's thread check failed 1 run in 6 when it was first).
- **The problems of a wrong call are made when they are read** (2026-10-13). The pass notes `(order, plan entry,
  value)` for each argument that failed; the error (`pending_error`) holds that, and `InvalidDataError.problems` is
  a property that makes the `Problem` objects on first use (`_problems_of`). Which arguments failed is settled at
  the call. A wrong return value (`ret_entry`) and a wrong dataclass assignment (`field_error`, `quick` in
  `field_reporter`) go the same way. The first read takes `_errors._MAKING` (raising never does): two threads
  reading at once shared the notes being sorted, and one got no problems (finding 48). Where finding the reason means running the user's code (an `Annotated`
  check, a TypeModel: `NO_TYPE`), the problem is made at once, by the short way first (`_only_type`'s `quick`:
  the container's `constraint_failure`, or the reason the converter left in `REJECTED`), else `_invalid_reason`.
  A compiled wrapper that tried a conversion in vain says so (`_pv_fallback(_pv_a, _pv_k, name)` -> `failed`), and
  the pass doesn't run that converter again: a TypeModel's `validate` runs once per wrong call (it was three times).
  **Next to a missing argument the reason is looked for too** (2026-10-18, found by the `configured` prototype): both
  paths reported a refused value there as a plain wrong type (a `Port` of 0: "expected type 'Port', got type 'int'").
  The pass had a `bare` mode to match the full path, which called `type_problem` without `convert` / `coerce`, and a
  model's reason is found through its conversion. `bare` is gone, and `full_check` takes `convert` / `coerce`
  (only to find reasons: what converts was converted before it). `test_a_refused_value_next_to_a_missing_argument_says_why`.
- **An error must be freed without the collector.** Its traceback holds the frame it was raised in, so:
  never hold an error in a local of the function that raises it (`error = ...; raise error` is a cycle; raise what a
  helper returns: `raise pending_error(...)`), and a problem's renderer never holds the problem (`_render` is
  `(function, *arguments)`, called with the problem in front, where it needs it). The first cost a wrong call 350 ns
  of 1,100; it is why one wrong argument went from 1.04 µs to 0.57. `test_an_error_is_freed_without_the_collector`
  counts what 15 kinds of wrong call leave behind (nothing). One path still leaves a cycle: a missing argument next
  to a misplaced one (`_realign_positional`: nested functions that call themselves).
- **Errors are lazy.** A `Problem` stores data and a `_render` callable; the coloured text is built only when
  `str()` is called. Keep that: message formatting must never run on the hot path.
- **Conversion runs only on values that fail the check.** `convert=True` (default) applies the numeric tower
  (int -> float/complex, never bool). `coerce=True` (off by default) adds parsing (`"42"` -> 42) and includes conversion.
  Converters return `FAILED` (from `_type_conversion`) on failure; it is the one sentinel, shared with `_type_data_model.py`.
  A model's converter leaves the reason of a refusal in `REJECTED` (value, model, reason; read once, by identity), so
  the message doesn't run `validate` again.
- **A `date` for a `datetime` is coerced to its midnight** (2026-10-18, for the `configured` prototype: YAML
  reads an unquoted `2026-10-17` as a date, and the text `"2026-10-17"` was already accepted). Under `coerce`
  only, naive; a `datetime` subclass is never touched there (it reaches the converter only when it failed for
  another reason). Still open, the owner's call: a `date` field accepts a `datetime` (a subclass) and keeps it.
- **Return values are converted, never coerced.** `_return_flags()` gives the return annotation `convert or coerce` and
  `coerce=False`: `1` becomes `1.0` for `-> float`, but `"42"` for `-> int` is reported, whatever `coerce` says. Coercion is
  for what comes in (arguments, defaults).
- **bool is not int.** `excludes_bool()` turns `int` and `int | str` into the `nobool` spec. `int | bool`, `Literal[True]`,
  `object` still accept bools.
- **`deep=True` (opt-in, off by default)** compiles an annotation into nodes (`Leaf`, `Items`, `FixedTuple`, `Mapping`,
  `TypedDictNode`, `NamedTupleNode`, `UnionNode`, `Proxy`, `Guard`, `Constrained`). Items of plain classes are checked in one
  C-level pass over their types. Iterables, iterators and generators are never consumed. Conversion builds a new container and
  never mutates the caller's.
- **Literal and `type[X]` in a union.** `TypeContainer` keeps the Literal values (`_literal_values`) and the classes of
  `type[X]` members (`_type_arg`, merged across members) apart from the ordinary members (`_other_types`), so
  `Literal['r'] | None` and `type[int] | None` still accept `None`. A value is one of the Literal values, or such a class, or
  is checked (and converted) against the ordinary members; `_special_spec` compiles that order.
- **Strict mode and abstract classes.** `allow_subclass=False` means the exact type, except for a class that can't have
  instances of exactly its own type (`is_abstract`): there `isinstance` is used, or strict `Sequence[int]` would reject
  every value. That is: an ABC with abstract methods, a Protocol, an ABC of `numbers` / `collections.abc` without any
  (`Number`, `KeysView`), `pathlib.Path`, `PurePath` and `datetime.tzinfo` (by name: neither module is imported for
  it), an Enum class without members (`enum.Enum` itself), `type`, and the two kinds of stand-in (files, `Self`). A concrete class stays exact, also next to an abstract one in a union, and so does
  a user's ABC without abstract methods.
- **`Self` is the class of the call.** `resolve_annotations` swaps `Self` for a class, wherever it stands in an
  annotation (`_has_self`, `_with_self`: `Self | None`, `list[Self]`, `type[Self]`; found by identity, the annotation
  rebuilt around it). Which class: for a method (`owner` known and `skip_first`), the class it is called on,
  `type(self)` or the `cls` of a class method. A check is compiled for one class and sees one value at a time, so
  there are two ways to get there, chosen in `generate_wrapper` once the annotations are resolved
  (`checker.self_uses`: name -> whether `Self` is the whole annotation; `checker.self_in`: parameters / return):
  - **`by_instance`**: every checked use is `Self` alone, tested by the class and nothing else (`plain_self`). The test
    is written against the class of the first argument (`_pv_c0 = type(_pv_a[0])`, `isinstance(other, _pv_c0)`), so
    one wrapper serves every class: about 10 ns per call, 20 on a subclass. A failing `-> Self` goes to
    `return_router`, which asks the checker of that class.
  - **`by_class`** (`Self | None`, `list[Self]`, a class method, a converter on the parameter): the code is for one
    class (`_pv_me`), and a call made on another goes to the wrapper for that class, straight from
    `checker.family` (`_pv_subs`) or through the fallback, where `_route` makes it (`wrap_callable(..., me = cls,
    family = ...)`). One family per method, at most `family` maps `id(class)` to a weak
    reference to the wrapper; what holds the wrapper is the class it was made for (`_OF_CLASS`, read with
    `kept_of`), so the two go together. `_HELD_FOR_CLASSES` (the last `_SELF_CLASSES_MAX`) is for a class whose
    metaclass refuses the attribute.
  The general path asks `elsewhere` first, so the first call and every failing one are routed as well. Nothing of
  this exists for a function that doesn't use `Self` in what is checked: no dictionary, no closure, the same generated
  source as before (`-> Self` without `check_return` is such a function). Decorating must not pay for it either:
  the first version made the router at decoration and cost every decorated function 50% more.
  Only a class that inherits the method is routed; anything else in the place of `self` is checked with `Self` as
  the owner. In strict mode `Self` is exactly the class of the call. The stand-in (`self_stand_in`, metaclass
  `SelfType`: the owner or a subclass) is what is left for strict mode where there is no call to read the class from:
  a static method. A dataclass field that uses `Self` is checked against `type(self)` for an instance of a subclass
  that isn't decorated: the generated `__setattr__` sends it to the reporter (`field_reporter`; the checker
  for that class is kept by that class, under `_OF_CLASS`).
- **Nothing global may keep a class alive that was made at run time** (review finding 36). Four places did:
  - `_SIGNATURES` was keyed weakly by the function, but a signature holds annotations, an annotation can name a
    class, and the class can hold the function: a weak key whose value leads back to the key never goes. A
    function's signature is on the function now (`__enforced_signature__`: `(id(fn), signature)`; the id because
    `functools.wraps` copies attributes). `_SIGNATURES` is for callables that are no functions.
  - `_UNPACKED` holds its annotation weakly (`held` / `holds`; the entry goes with the annotation, `_gone`, which
    takes no lock: it runs wherever the collector does). A plain class (`type(x) is type`) is answered without the cache.
  - `_DEEP_NODES`: a node keeps its annotation, so an entry can't go by itself. A plain class is answered before
    the cache, and an annotation that names a class written in a function is not put in (`_names_local_class`).
  - Annotations written for one class in place of `Self`, and those of a local class's own methods, are in
    `not_cached` (`made_for`), with a finalizer on the class that takes the ids out again.
  A test for any new cache: make 40 classes in a loop, use them, drop them, collect three times (the first pass
  frees the functions, the class goes with a later one), and count the survivors.
- **TypeModel.** `class Email(TypeModel[str])` with a `validate(cls, raw)` classmethod that returns the normalised value or
  raises `ValueError(reason)`. `TypeModel[T]` returns a cached real base `(TypeModel, T)`, so an `Email` *is* a `str`. The checker calls
  `__enforced_convert__` under `convert=True` (class flag `auto_construct`); a rejected raw value becomes an `"invalid"` problem.
  Subclasses can't define `__new__`/`__init__`; instances are immutable and pickle by re-validating.
  `__base_type__` is public (the owner's decision, 2026-10-17: a dataframe library reads it to map a model to a
  dtype; README, Validated values; `test_base_type_is_public_and_names_the_base`). Checkers don't know it: `getattr`.
  Instances have no `__dict__`: the metaclass `ModelMeta` gives a model class `__slots__ = ()` unless it declares
  slots itself (slots are fixed when the class statement runs; nothing but a metaclass can step in there). A class
  with a metaclass is slower in `isinstance` for a value that isn't exactly of it, so `_type_spec` puts model
  classes last in the tuple of a union's check (`None` for `Email | None` never reaches the model), and
  `_deep._plain_metaclass` keeps the one-pass item check for them. `ModelMeta` must not define `__instancecheck__`.
  A base type with its own metaclass (`Fraction`: ABCMeta) gets `_AbstractModelMeta`.
- **Union conversion follows the declared order** (`build_converter`): conversions for each member in turn, then
  coercions in turn, and a TypeModel member takes its turn like any other (its conversion step in the first round,
  its coercion step in the second). One model alone keeps its single combined step.
  With `coerce`, a bool is only made an Enum member where a member's own value is a bool (`Level(True)` would find
  the member whose value is 1).
  **For a static checker `TypeModel` is an alias** (`_type_data_model.py`, at the end): under `TYPE_CHECKING`,
  `TypeModel = Annotated[T, ...]`, so `class Email(TypeModel[str])` is read as `class Email(str)` by mypy and pyright,
  and a model is its base type for them in the short form (the user's request, 2026-10-13; it closed the typing half
  of review finding 2). At runtime `TypeModel` is the class, defined as `_TypeModel` and renamed. The old long form,
  `class Email(TypeModel[str], str)`, still runs but is a duplicate base class to a checker: don't write it.
  `tests/static_typing_sample.py` holds both.
- **`Annotated[T, check]`.** Callable metadata runs as extra checks after the type test (`TypeContainer._constraints`,
  `constraints_pass`). A check rejects by returning falsy or raising one of `CHECK_ERRORS`: `ValueError`, `TypeError`,
  `ArithmeticError`, `LookupError` (its message becomes the reason). Anything else is a bug in the check and
  propagates. Non-callable metadata is ignored. `get_type_hints(..., include_extras=True)` is what keeps the metadata.
  `Check(fn)` is the explicit form, and the bare callable the short one (the user's roadmap keeps lambdas):
  `metadata_checks` is the one place that reads the metadata, and it unwraps a `Check`, so the marker is never
  called on the hot path. A class is a check only inside a `Check`. A check never changes a value; where a falsy
  result is neither `False` nor `None` (`''` from `str.strip`), `check_failure` adds "which returned ''" to the reason.
- **Problem kinds:** `type`, `default`, `return`, `missing`, `field` (dataclass assignment), and with deep/validated types
  `length`, `missing_key`, `cycle`, `invalid` (right type, rejected value; reason in `detail`). With `deep`, `invalid` is also
  the whole-value verdict when no single item is to blame: keys that collide after conversion, or a container whose type
  can't be rebuilt with converted items (`_rebuild` / `_rebuild_mapping` return `FAILED`; they never fall back to list/dict).
- **Nested items are read through one-shot iterators** (`chain.from_iterable`). `_items_expr` writes the items expression out
  again for every pass (the types, then each `Annotated` check); a batch function must never read its argument twice.
- **A checked dataclass has an `__init__` of its own** (`storing_init`; the user's request, 2026-10-13). It takes
  the parameters of the standard one and does what that does, but stores an argument with `object.__setattr__`,
  past the assignment check: the wrapper has checked it. A `default_factory` result and what `__post_init__` assigns
  go through the check. It is made inside a function whose arguments are our names, with the module of the class
  as globals (a field's string annotation is read there). An instance of a subclass is handed to the standard
  `__init__` (a subclass may have a `__setattr__` of its own). The standard one is kept (`None`) for a `__setattr__`
  written by hand in the class's line, for slots with a default `__init__` doesn't take, and for anything unforeseen.
  Six fields: 655 ns before, 408 now. A default is validated once, like a function's, not at every construction.
  It is made late (see "Tiered compilation"): `checker.call` is swapped, `__wrapped__` stays the standard
  `__init__`, which is the origin of the problems.
- **Where the standard `__init__` is kept for good, fields are still validated once** (once the assignment check is
  generated: `mark` returns nothing before). There the `__init__` wrapper publishes its checked arguments in the generated
  `__setattr__`'s globals (`_pv_args` / `_pv_kw`, the `mark` hook of `wrap_callable`) while the real `__init__` runs. A field
  whose check calls a function (`"pred"` spec: deep items, `Annotated` checks, `Literal`) skips it for the very object it was
  given, or for its already-checked default. Inline type tests are simply repeated: cheaper than any bookkeeping. Classes
  without `"pred"` fields generate exactly the old code.
- **`default_factory`.** With the assignment check, `__setattr__` validates what a factory returns. Without it (frozen,
  `check_assignment=False`) `check_factories` wraps each factory before the dataclass is built.
- **Defaults `__init__` doesn't take.** `field(init=False, default=...)` is no parameter, and only a slots class ever assigns
  it. `_unlisted_defaults` hands these to `check_defaults` (the `extra_defaults` hook of `wrap_callable`), so they are
  checked with the other defaults on the first construction. A converted one is stored where instances read it: the class
  attribute, or with `slots=True` the closure cell `__dataclass_dflt_<name>__` of the generated `__init__`.
  With `@dataclass(init=False)` there is no generated `__init__` at all: `check_defaults_once` puts a thin wrapper around
  the class's `__init__` (its own or the inherited one) that checks every field default on the first construction and then
  takes itself away again. With `slots=True` it does nothing: no instance and no class holds such a default.
- **The annotation caches evict.** `_UNPACKED` (`_container`), `_DEEP_NODES` (`_specs`) and `_CODE_CACHE` (`_codegen`) drop their
  oldest entry when full, under a lock (`_UNPACKED_LOCK`, `CACHE_LOCK`); reads take none. Before, a full cache stopped
  taking entries and every later function went without. Without the lock an eviction can meet another thread's insert
  (`RuntimeError: dictionary changed size during iteration`, seen in 1 run of 10 under a tight switch interval).
- **`typecheck_function` and `enforce_class`** (the user's design, 2026-10-12: a non-decorator way to do the same
  thing; an earlier version that only checked and returned the arguments was replaced).   `typecheck_function` wraps
  the function exactly as `typecheck` would and calls the wrapper, one per set of options. The wrapper of a function
  is kept on the function (`__enforced_calls__` in its `__dict__`: `(the function, {options: wrapper})`, read through
  `_kept_on`), so the two go together: a cache elsewhere holds the wrapper, the wrapper holds the function, and a
  function made in a loop stayed alive until the cache had turned over. `entry[0] is fn` because `functools.wraps`
  copies the attribute to another function. Any other callable (an object with `__call__`, a partial, a builtin)
  is remembered in `CALL_WRAPPERS`, by `id()` (the entry holds it, so the id stays its own), the 512 most recent:
  nothing is written into an object, whose attributes are copied and pickled with it. `typecheck_record` keeps
  the checkers of a function target the same way (`__enforced_records__`, `_OWN_RECORDS_MAX` records). A bound
  method is taken apart (`__func__` with `__self__` in front): it is a new object at every lookup. The function
  itself is never replaced, so a direct call stays unchecked. `enforce_class` is `enforce` behind a check that it
  was given a class.
- **Converted defaults** (`x: float = 0`). `check_defaults` returns them; `PreparedChecker._prepare` decides by
  `rewrite_defaults`. `True` (a decorator): the wrapper calls a copy of the function that has them (`copy_with_defaults`,
  kept as `checker.call`): no cost per call, and the function that was decorated keeps its own. Where the defaults
  aren't the function's own (`functools.wraps`, a `partial`, an object with `__call__`: `own_signature`), they are
  passed with each call that leaves the parameter out: `checker.inject`, applied by the generated wrapper (`_pv_dk`
  for keyword-only ones in the fast lane, `keep_kw` in the general lane) and by `with_defaults` on the fallback path.
  `IN_PLACE` (a dataclass's generated `__init__`, nobody else's): written into the function. `PASSED`
  (`typecheck_record`): handed back with the checked arguments. `False`: nothing (a field checker).
  The fallback calls `checker.call`, read at each call: the first one may swap in the copy.
- **A checker has its own signature** (`checker.sig`). `signature_of(fn)` is the function's, cached and never
  altered; `typed_kwargs(record, sig)` returns the record and signature with `**kwargs: Unpack[TypedDict]` laid
  out, for that checker alone. Everything that binds takes `sig` from the checker (`generate_wrapper`,
  `full_check`, `check_defaults`, `_realign_positional`).
- **`typecheck_record` cache.** Keyed by the record with `==`; a record with unions inside holds one checker per member
  order (`union_order`), because `int | float == float | int` while conversion follows the declared order. Hits read the
  cache without a lock; everything that changes it (`_remember_checker`: insert, evict the oldest) runs under
  `_RECORD_LOCK`, so misses from several threads can't meet halfway through an eviction.
- **Strings are read, not run.** An annotation that is still a string when it reaches `TypeContainer` (a record of
  `typecheck_record`, or a name that resolves nowhere) goes through `read_annotation`: `ast.parse`, then only names
  from a fixed list, subscripts, `|`, tuples, lists and constants. The list (`_record_name`): the built-in classes,
  `_RECORD_NAMES` (`Any`, `Optional`, `Union`, `Literal`, `Sequence`, `Mapping`, `List` ...: each a fixed object),
  and `_RECORD_CLASSES` (`datetime`, `Decimal`, `UUID`, `Path` ...: imported when a record first names one). A dotted
  name is accepted for the modules in `_RECORD_MODULES` only; no attribute of anything else is ever read. No `eval`
  there: a record is data and may come from a request. Adding a name to the list means: nothing callable to any
  effect may become reachable through it. `_deep._compile` reads a string the same way, so `"list[int]"` has its items checked. A function's own string
  annotations are resolved earlier, by `resolve_annotations`, in its module (that is source code, and may be evaluated).
  A record value that is plain data (`5`, `["int"]`) is refused in `_flatten_expected_types` (`_NOT_ANNOTATIONS`); what
  falls through to "anything" after that are typing forms without a runtime test (`P.args`, a TypeVarTuple).
- **What a string annotation may name** (`local_names`): the globals of its module, the owner class, the type parameters
  of that class and its bases (`class Box[T]`: without them every method and a generic dataclass failed under
  `from __future__ import annotations`), and names local to the function the definition is written in. Those last ones
  are gone by the first call, so `remember_scope` looks them up at decoration, in the frames that are lexical parents
  (`co_qualname` is a prefix of the target's `__qualname__`: never the caller of a helper), and keeps only the names the
  annotations use, on the function or class (`__enforced_scope__`). It runs only for `<locals>` targets, and
  `_annotation_texts` returns nothing when no annotation is a string (no future import, nothing quoted: Python keeps the
  scope itself), which is the test that keeps decorating a local function cheap.
  A name that comes into being after the decorator ran (a class a few lines further down) is looked for once more
  when resolving fails (`look_again`): on the stack, where the enclosing function's frame still is if it is running.
  What is found is added to the kept scope. No frame is held on to for this: a frame keeps its caller's frames, and
  with them every local of the whole stack, alive. Once the function has returned it is gone from the stack. So a name that is nowhere at decoration (`missing` in
  `remember_scope`) is read at the moment the enclosing function returns (`_when_it_ends`, `_it_returned`): the
  waiting list travels in the frame's own locals under `__enforced_pending__`, and `sys.monitoring` is asked for
  `PY_RETURN` of that one code object, under a tool id taken on first use (`_watcher`: 4, else 3, else nothing).
  Never by keeping the frame, and never a registry by `id(frame)`: `PY_UNWIND` can't be watched per code object,
  so a frame left by an exception would leave a stale id behind. A function that calls itself: only the innermost
  frame of each code is a parent.
- **A nested name inside an annotation** (`List["Json"]`, the old way to write a recursive alias) is resolved by the deep
  compiler through `resolve` (`resolver`: `eval` in the function's module with `local_names`). It is threaded from
  `PreparedChecker` through `compile_spec` / `compile_converter` / `deep_node` to `_deep.compile_node`, and is only
  ever set for annotations from source code: a `typecheck_record` checker has none, so its strings stay data. A name
  that resolves to an annotation already being compiled becomes a `Proxy` cycle, like a recursive `type` alias.
- **A method decorated on its own finds its class** on the first call (`find_owner`, from `PreparedChecker._prepare`):
  through `self` / `cls` when the first argument's MRO holds a class whose `__qualname__` is the function's prefix,
  else by name from the module (a static method). That gives it `Self`, the class's type parameters and the label
  `<Method Owner.name>`. Functions with `<locals>` right before their name are plain functions and are not looked up.
- **Callables without annotations of their own** (`_annotations_of_what_it_calls`): an object with `__call__` is checked
  against that method, a `functools.partial` against the function it wraps (for the parameters it still takes). Only
  when the callable's own record is empty, so a wrapper made with `functools.wraps` keeps going through `__wrapped__`.
  A builtin whose signature `inspect` can't read (`max`) gets `(*args, **kwargs)` in `signature_of` and passes through.
- **`**kwargs: Unpack[TypedDict]`** is checked as if each key were a keyword-only parameter (`typed_kwargs`): the record
  gets one entry per key and the checker's signature shows the same (`_with_typed_kwargs`; an optional key has the
  default `NOT_GIVEN`, which `check_defaults` skips). Everything else (generated wrapper, conversion, missing and
  unknown keywords) then works unchanged. `inspect.signature` of the wrapper still shows what was written. A key that
  is no identifier (`"my-key"`, `"class"`) becomes a `_KeyParameter`: `inspect.Parameter` refuses such a name, and
  the generated wrapper never writes names into source (they live in its namespace).
- **`*args: *tuple[int, str]`** is checked as one tuple by a `FixedTuple` node, and
  `*tuple[int, *tuple[str, ...], float]` by a `VariadicTuple` (`args_node`, kept on the checker as `var_pos_node`;
  `_deep.spread` lays the items out). The generated wrapper tests the extra arguments with the node's `check`
  (`_pv_vp(_pv_a[n:])`); a call that needs converting goes to the fallback, where `_fast_ok`, `_convert` and
  `_type_problems` have the three small branches. `*tuple[int, ...]` is rewritten to the plain per-argument check.
  With `deep`, `tuple[A, *tuple[T, ...], B]` as an ordinary annotation compiles to the same node.
- **A wrapper says what kind of function it wraps.** `inspect.isgeneratorfunction` reads one flag on the code object,
  and pytest (`yield` fixtures) and others branch on it. The wrapper of a generator function is an ordinary function
  that checks at the call and returns the generator, so its code objects carry that flag (`_stub_codes`: `BOOT_CODES`
  until compiled, `PLAIN_CODES` for an unchecked one; `generate_wrapper` flags what it compiles, cached under
  `(source, kind)`). Python doesn't read the flag when it runs code (a real generator function begins with
  `RETURN_GENERATOR`). That is no promise, so it is tried at import, once per flag (`_runs_at_once`: a flagged
  ordinary function has to return at once): `_FLAGGED` holds the flags that may be carried, and on a Python that
  acted on one, wrappers get plain code: checked as ever, an ordinary function to `inspect`.
  `test_checked_generator_function_is_still_checked_when_it_is_called` holds the behaviour itself. A function keeps the kind of code it was made with: assigning another kind
  is deprecated (3.14 warns). `function_kind` answers from the code flags for a plain function, and decorating got
  cheaper for it (three `inspect` calls cost more than everything else).
- **`typing.no_type_check`.** Marked before decoration: `wrap_callable` returns the function as it is, `enforce`
  skips the method, `dataclass` builds a standard one. Marked after (`@no_type_check` above `@typecheck`): the mark
  lands on the wrapper, is seen on its first call and turns it into a pass-through (`_unchecked`).
  The mark is the class's own (`vars(cls)`), as the `typing` documentation has it: a subclass doesn't inherit it.
  But `typing.get_type_hints` looks it up with `getattr` and returns nothing for the whole subclass, so a decorated
  dataclass below a marked class says for itself that it is checked (`_own_type_hints` sets
  `__no_type_check__ = False` on it) and leaves out the fields a marked class annotated (`UNCHECKED_FIELDS`).
- **TypeVar bounds written as strings.** `typevar_types` looks `bound="Shape"` (and string constraints) up in the module
  that defines the TypeVar; `_flatten_expected_types` and `_deep._compile` both use it.
- **File annotations.** No real file inherits from `typing.IO` / `TextIO` / `BinaryIO`, so `_flatten_expected_types` swaps
  each for a stand-in class from `_file_types.py` (also `IO[str]` / `IO[bytes]`). Its metaclass (`FileType`) answers
  `isinstance`: the built-in file classes first (plain C types, the fast answer), then the `io` ABCs and the typing class,
    then "a file of the other kind" (rejected), and last an object with every file method (text when it has an
  `encoding`). `__enter__` / `__exit__` are not among them (`_METHODS`): a `Mock()` has every name but the special
  ones. The stand-ins are named and placed in module `typing` so messages read `'typing.TextIO'`; `is_abstract`
  is true for them, so strict mode uses `isinstance` too. `type[TextIO]` goes through `FileType.__subclasscheck__`,
  which asks a class what an instance is asked, as far as a class shows it, in strict mode as well (`_class_spec`,
  `matches_class`: no class *is* the stand-in). A class that answers names through `__getattr__` (a delegating
  wrapper, a Mock) is taken for a file class of either kind: nothing of its instances shows on it. Only a text as
  the class's own `encoding` says "text file"; a property says nothing.
- **A standard dataclass below a checked one** inherits the generated `__setattr__`. A field it declares itself is
  its own: `_retyped_below` is asked in the generated code only after a value has failed the base's test (so a valid
  assignment pays nothing), and by the reporter. It was the last known issue.
- **One check per dataclass instance, its own class's.** A decorated class's fields include the inherited ones, so its
  generated `__setattr__` covers the whole instance with its own options. It calls what a decorated base's `__setattr__`
  wraps (`__enforced_wraps__`, found by `plain_setattr`), never that `__setattr__` itself: checks don't stack, and
  a subclass can loosen, tighten or retype what it inherits. `check_assignment=False` below a checking base installs the
  wrapped function directly (`unchecked_setattr`). A base's check that is still reachable through a hand-written
  `__setattr__` calling `super()` is told to `step_aside`: it is generated again with one test at the top
  (`_governed_by_subclass`, which looks for the `__enforced_dataclass__` mark every decorated class carries) and leaves
  such instances alone. Only classes in that position pay for the test.
- **Inherited `default_factory` fields.** Their `Field` objects belong to the base class. `check_factories` swaps the
  factory only while `dataclasses` generates this class's `__init__` (the raw factory when this class's `__setattr__`
  checks the result, a wrapper bound to this class otherwise), then restores it.
- **`@typecheck` above another decorator.** `typecheck` sends a plain function straight to `wrap_callable` (decorating
  must stay cheap). Anything else goes through `wrap_member`, which takes a `classmethod`, `staticmethod`, `property` or
  `cached_property` apart, checks the function inside and builds the object again; another non-callable raises at the
  definition. `_is_checked` recognises a wrapper already made, so `@typecheck @prop.setter` doesn't wrap the getter twice.
- **One decorator per kind of thing.** `typecheck` takes functions and methods, `enforce` plain classes,
  `enforced.dataclass` dataclasses. Each refuses the others' at the definition with a `InvalidDataError` that names the
  right one (`wrap_member` for a class given to `typecheck`; the top of `enforce`). "Dataclass" there means a class that
  was made one itself (`made_dataclass`: `__dataclass_fields__` in its own `vars`): a plain subclass of a dataclass is a
  plain class.
- **`enforce`** wraps, in place, `__init__` and every function, `staticmethod` and `classmethod` in the class's own
  `vars` with `wrap_callable(..., owner = cls)`: exactly what `typecheck` did for a class before the split (the fuzz's
  `method` use compares the two). Inherited and later-added methods are not touched.
  A `property` / `cached_property` goes to `enforce_property` (the user's decision, 2026-10-13: of what `enforce`
  left unchecked, properties only): the setter is wrapped when it has annotations, the getter and a cached property's
  function only with `check_return` (without it a getter has nothing to check, and reading must stay as cheap as it
  was: 16 ns against 80). The property is rebuilt with `.getter()` / `.setter()`, so its class and doc stay; a
  cached property is changed in place (it knows its name). `enforce.exempt` above `@property` marks the accessors. A method without a
  single annotation stays the plain function (`unannotated`: read from `__annotate__` / `__annotations__` without
  evaluating anything); a call it can't take is then Python's own `TypeError`.
- **`make_dataclass`** hands `dataclasses.make_dataclass` a `partial` of `dataclass` with our options (it calls
  the decorator with the standard ones). The module is the caller's, read with `frame_above()`
  (public, where the standard function uses `sys._getframemodulename`): left to the standard function it named
  `enforced._dataclass.api`, where string annotations didn't resolve and pickle didn't find the class. Its
  signature is the two functions' options together, kept in step by `test_its_options_are_those_of_both_functions`.
- **The methods of a dataclass** (the owner's decision, 2026-10-13; built 2026-10-14). `check_methods = True` (the
  default, matching `enforce`) wraps what the class itself defines with `_class_rules.enforce_members`, the loop
  that was `enforce`'s own and is now shared: same members, same exceptions, the class's own options, and
  `check_return` (new on `dataclass`; it is about the methods, never `__init__`). It runs last in
  `_dataclass/api.wrap`, on the class `dataclasses` returned (with `slots = True` a new one; `super()` in a method
  works because the functions are still plain when `dataclasses` rewrites their `__class__` cell). Left out
  (`leave`): `__init__` and `__setattr__` (checked already), `__post_init__` (called by `__init__` with checked
  values), and every name in `__dataclass_fields__`: a field's default sits in the class under its name and may be
  a function or a property (`handler: Callable = fallback` would be wrapped as a method otherwise; a test holds it).
  What `dataclasses` generates is no member of `CHECKED_SPECIAL`. A method call costs what it does under
  `enforce` (a benchmark case holds the two side by side), and the fuzz's "dataclass method" use compares the
  outcomes call for call. `enforce` still refuses a dataclass.
- **`Enforced`** (in `api.py`; no metaclass, `__slots__ = ()`). `__init_subclass__` takes the five options and
  `on_error` as keywords, `None` meaning "inherit": the resolved tuple is stored on each class under
  `_class_rules.BASE_OPTIONS` (`__enforced_options__`) and read through the bases with `getattr`, so a subclass that
  names one option replaces that one only. Unknown keywords go to `super().__init_subclass__`, so a library's
  base with keywords of its own cooperates. It asks `TYPECHECK_OFF` and the class's own `__no_type_check__`
  at each class, calls `remember_scope` for a `<locals>` class (`frame_above()` from `__init_subclass__` is the
  class statement's frame), then `enforce_members`: only what the class defines, so inherited methods are not
  wrapped twice. `enforce` / `enforce_class` and `enforced.dataclass` refuse a class that carries
  `BASE_OPTIONS`. The dataclass refusal is not taste: the methods are wrapped before `dataclasses` runs, so with
  `slots = True` it would rebuild the class around wrappers whose `super()` cell and `Self` owner are the old
  class. The standard `@dataclasses.dataclass` can't be refused (it writes `__init__` after
  `__init_subclass__`): README, Limitations. The fuzz's "enforced base" use compares it with `enforce`.
- **Special methods under `enforce`.** `CHECKED_SPECIAL` lists the dunders that are checked: those whose arguments a
  caller writes (`__init__`, `__new__`, `__call__`, `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`) and
  `__enter__` / `__aenter__` for their return value. Everything else Python calls itself, often with any object
  (`==`, the operators, `__exit__` with three `None`s, `__setattr__`), and stays unwrapped: don't add to the list without
  that test. `__new__` sits in `vars` as a `staticmethod` whose first parameter is still the class (`skip_first`), has no
  return check (`CONSTRUCTORS`) and is reported as `<Class X>`. A dunder that a base class holds too is left alone
  (`held_by_a_base`): every `Enum` class carries `Enum.__new__` in its own namespace.
- **Decorator overloads.** With options, `typecheck` and `enforce` are declared `-> Callable[[F], F]` /
  `Callable[[T], T]`. Declared `-> Callable[[Any], Any]`, a class decorated with `@enforce(...)` was `Any` to Pylance in
  every file that used it. `dataclass` has two overloads returning `type[T]` and carries
  `@dataclass_transform(field_specifiers = (field, Field))`, so checkers build `__init__` from the fields. Guarded by
  `tests/test_static_typing.py`: declarations always, mypy's actual reading of a sample file when mypy is installed.
  It leaves a method alone when it carries the `enforce.exempt` mark (`__enforced_skip__`, set on the object and on
  the function inside a `classmethod` / `staticmethod`, so either order works), and when it has its own `@typecheck`
  (`checked_inside`, which also looks through `functools.wraps` decorators): those options stand and nothing is
  checked twice. Such a method is only told its class (`adopt`, through `_pv_checker` in the wrapper's globals), so
  that `Self` resolves and messages read `<Method Owner.name>`.
- **Protocols.** A Protocol that isn't `@runtime_checkable` raises a `InvalidDataError` (`protocol_error`) instead of failing
  inside `isinstance`; it travels the same path as an unresolved forward reference (`_SLOW`, raised on every call).
- **A dataclass field held by a descriptor** (its class attribute has `__set__`, and is no slot) is not checked:
  the annotation names the descriptor class, the values are whatever it stores. `_descriptor_fields` lists them on
  the class (`UNCHECKED_FIELDS`), and `resolve_annotations` leaves them out of every record of that owner.
- **`on_error = "warn"`** (the owner's design, 2026-10-13: one option on every API, not a sync/async pair). A value
  that fails is issued as a `InvalidDataWarning` (`_errors.warn_of`) and the call goes ahead with it; what could be
  converted is. The flag is `PreparedChecker.warn` (`wrap_callable(..., warn = ...)`, from `_errors.warns(on_error)`,
  which refuses any other value where it is written). It is asked in four places only, each where an error is
  about to be raised: the one pass and the three-pass path of `check_inputs`, `check_return`, and the dataclass
  field reporter. **Raised all the same:** a missing argument (also next to a wrong one), a call that doesn't bind,
  and whatever has no problems or the context "definition" (a default, an unreadable annotation): those are not
  the caller's value being wrong. Nothing is added to a valid call.
  `warn_of` attributes the warning to the first frame outside the package and its generated code (`_OUR_FILES`,
  and the `__init__` that `dataclasses` writes), with `warnings.warn_explicit` and that frame's registry: Python
  shows a warning once per line it comes from, and attributed to a line in here every warning after the first
  would be dropped. A dataclass with `warn` gets its storing `__init__` at the first construction (`improve` in
  `bootstrap`): behind the standard one a wrong argument is met twice and would be reported twice until the
  wrapper is compiled. Where the standard `__init__` is kept for good, it is reported twice (README, Limitations).
  The fuzz holds the rule as a property (`WARNS`): a warning that says what the error said, or the same error.
- **`error = ...`** (2026-10-22). `check_error_type` (in `_errors`) checks it where it is written: a subclass of
  `InvalidDataError` whose instances have the base's layout (no `__slots__` of its own: `retype` below assigns
  `__class__`). It travels with `warn`, the same road (`wrap_callable`, `wrap_member`, `enforce_members`,
  `enforce_property`, `new_record_checker`, `call_wrapper`'s options tuple, `field_reporter`, `wrap_setattr`,
  `wrap_init`, `check_factories`, `check_defaults_once`, the `Self` router) to `PreparedChecker.error`, read only
  where an error is made: valid calls and generated code are unchanged (the code cache doesn't know the class).
  `pending_error` / `field_error` make `checker.error`, `said_error(said, cls)` and
  `typechecker_type_error_factory(problems, context, error)` the class given (`make_error`: `InvalidDataError`'s
  own `__init__`; **a subclass's `__init__` is never run**, it may take a library's own arguments). An error
  made by code that doesn't know the checker (`full_check`, the return pipeline, `check_defaults`, an annotation
  `TypeContainer` can't read) is made as `InvalidDataError` and given the class at the checker's door
  (`retype`, in `_prepare`, around `full_check` and `typecheck_return_pipeline`, and in `check_defaults_once`):
  a `try` costs nothing when nothing is raised. `Enforced` keeps it as the seventh of `BASE_OPTIONS`.
  Pickling: `__reduce__` carries the class when pickle finds it by name (`_findable`), else it comes back an
  `InvalidDataError`. `tests/test_error_type.py` holds every API x every kind of error x both tiers.
- **`ENFORCED_TYPECHECK_OFF=1`.** `_environment.TYPECHECK_OFF` is read once, at import, and is the first thing each
  API asks: `typecheck` / `enforce` / `enforce_class` return what they were given (`unchanged` for the form with
  options), `dataclass` builds a standard one, `typecheck_function` makes the call, `typecheck_record` returns
  the arguments. Not read per call: an environment lookup costs about what a checked call does. A new API has to ask
  it too (`tests/test_environment.py` runs one program with and without it). A variable the package reads is a
  member of `EnvVar`, and only `_environment.py` and `_formatting_tool.py` touch `os.environ` (a test reads the sources).
  `turn_typecheck_off()` sets `_environment.TYPECHECK_OFF`, which every API reads through the module at each call of
  the API (not of a wrapper): what is decorated after it is unchecked, what was decorated before stays checked. A
  per-call test in the wrappers would make it reach those too, and cost every checked call: not done.
  `turn_colours_off` / `turn_colours_on` set `_formatting_tool._CHOSEN`, which `colours_on` asks first.
- **Colours.** `_formatting_tool.colours_on()` decides: `ENFORCED_COLOURS_OFF=1`, `NO_COLOR`, `ANSI_COLORS_DISABLED` off,
  `FORCE_COLOR` on, `TERM=dumb` off, else only when stdout *and* stderr are terminals (a message is one string and
  may go to either). `render_error` asks once per message, not once per
  word. A spec (`"bold_red"`) is made of the styles in `_formatting_tool.STYLES`: `bold` and seven colours, the ones
  the package's own messages use and no others (the owner's decision when termcolor went: zero dependencies, and
  only what is used; an unknown style is a `ValueError`). The escape sequences are the ones termcolor wrote, so no
  message changed; `_escapes` works a spec out once (`_ESCAPES`). A new colour in a message means a new entry in
  `STYLES`, and a test fails until the table and the specs in the package agree. `break_trace_colouring` is an object that builds the reset sequence when a message is put together
  (`_TraceReset`): as a constant made at import it ignored colours switched off later.
  **Rendering was made cheaper on 2026-10-13** (coloured 4.1 µs -> 1.8, plain 2.5 -> 1.7 for one problem):
  `colours_on` reads the dictionary below `os.environ` (`os.environ._data`, the names encoded once: 1 µs -> 0.07;
  read from `os.environ` at each call, so another mapping put in its place is seen, and `os.environ` itself is
  asked where there is no such dictionary: `_FAST`). The message of a wrong type, the origin label and the head
  line are each written as one f-string with the escape sequences as constants (`escapes`, `_STYLES`), where
  each coloured word was a `formatter` call; `render_error` sets `_formatting_tool._decided` itself. The output
  is the same string as before (a test compares a whole message, sequence by sequence). Other
  messages still go through `formatter`, which is fine: use the constants only where a message is hot.
- **An error pickles with its problems.** `InvalidDataError.__reduce__` carries message, context and problems;
  `Problem.__reduce__` its data and its text, each part through `_picklable` (a stand-in, `Unpickled`, for what
  pickle refuses). `origin` goes as `(module, qualname)`, or `(module, qualname, which)` for the accessor of a property
  (`fget`, `fset`, `fdel`, `func`: the only names read), and is found again through the wrapper (`_find_origin`):
  the function a problem holds is the one inside the wrapper, which pickle can't find by name.
- **`short_repr` formats only what it shows** (`bounded_repr`): the items of a built-in container one at a time until
  the budget is full. Its output is the start of `repr(value)`, exactly: self-containing values, quote choice of
  text and the one-item tuple included (a parametrised test compares).
- **A call that can't be bound** for one of the three usual reasons (too many positional arguments, a name given
  twice, an unknown keyword) is worded by `PreparedChecker._binding_error`, in the sentences `Signature.bind` uses
  (a test compares 300 random calls per shape with it), and raised as `InvalidDataError(said = ...)`: like every
  message, it is put together when it is read. It was 2.7 µs through `bind_partial`, and is 1.2.
- **The full path** is `full_check` (it was `_typecheck_function`): `Signature.bind_partial`, then everything wrong
  with the call. `_realign_positional` returns at once when every given argument fits where it stands. `bind_partial` lets a positional-only parameter through by keyword when an earlier one is left to
  its default; that is caught there and reported in Python's words.

## Message wording (tests assert on these exact strings)

```
For parameter x of <Function f>: expected type: 'int', got type 'str' (Value: 'a')
For parameter m of <Function f>: expected type: Literal['r', 'w'], got type 'str' (Value: 'x')
For parameter k of <Function f>: expected type: 'type[int]', got type 'type' (Value: <class 'str'>)
For parameter x of <Function f>: invalid 'Email': must contain exactly one '@' (Value: 'nope')
For parameter t of <Function f>: expected type: tuple[int, str] with 2 items, got 1 item (Value: (1,))
For introspected parameter xs at index [1] of <Function f>: ...
For default value of parameter x ...        For return value of ...
For default value of field retries of <Dataclass Job>: ...   (a field that __init__ doesn't take)
Field Order.qty of <Dataclass Order>: expected type: 'int', got type 'str' (Value: 'many')   (dataclass assignment)
```

What follows "expected type" comes from `expected_text`: the flattened runtime type (`type_name`: module and qualname,
`'int' | 'str'` for a union), except for Literal values and `type[X]`, where that type says nothing and can equal the
type of the rejected value. There the annotation is shown as written (kept on `TypeContainer._annotation` and on
`Problem.annotation`), cut after 80 characters (`shortened`), as is the annotation of a length message and the text
of "Cannot resolve annotation".

`InvalidDataError.__module__` is set to `"builtins"` after the class body so tracebacks show a short name; `__reduce__`
goes through `_restore_error` so it still pickles.

## Rules for changes

1. **Run all three** (pytest, `tests/simulation.py`, `tests/benchmark.py --quick`) before calling something done. New behaviour needs
   pytest tests *and* simulation checks; user-visible behaviour needs a README note. The package's own files are
   clean under mypy and pyright: keep them so (`mypy enforced`; an explanation after `# type: ignore[code]` goes
   in a second comment, `# type: ignore[code]  # why`, or mypy rejects the line).
2. **No regression on the hot path.** Compare against the previous copy of the package. Typical figures on the dev machine:
   a 1-param call is ~60 ns of overhead (pydantic ~215 ns); the fixed cost is ~42 ns plus ~13 ns per parameter.
3. **Differential fuzz** changes that touch checking, with `tests/fuzz.py`: save a baseline first (or use `--ref`), then
   compare. In its `core` zone (`deep=False`, no `Annotated` check, no `TypeModel`) the outcomes must be identical; a fix
   names the differences it is meant to make with `--expect`, and nothing else may differ. Run `--properties` too.
   A new way to use an annotation (a decorator option, a kind of field) gets a `USES` entry there.
4. Prefer small, flat Python in hot code (slots, closures, no per-call allocation). Add a comment when a choice is for speed.
   A function on the hot path must not capture its arguments in a nested function, lambda or generator expression: the
   argument becomes a closure cell and every call pays for it (`matches_type` got 40% slower that way; see `_implements`).
   Where an error is raised, it is never a local of that function (see "An error must be freed without the collector").
5. Style: 4-space indent, `x = y` spacing as in the existing code (`kwarg = value` with spaces is common), `#*` for
   important comments, docstrings on public functions, type hints everywhere.

## Known issues and ideas

- A bug that is known but not fixed gets a strict `xfail` test in `tests/test_known_issues.py` (run it with `--runxfail` to
  see it fail) and a `known_issue(...)` line in simulation phase 7. A fixed one moves to the test file of its subject and
  becomes a regular simulation check. None is open at the moment.
- `CODE_REVIEW.md` holds the latest review of the package (the tenth, 2026-10-13: errors made late, the dataclass tiers, the split into modules, printing, no dependencies, `on_error`). Read it before starting on a fix, and update it
  when one lands.
- Static typing: mypy and pyright report nothing in the package's own files (pyright was run from a scratch
  environment; `pip install -e ".[dev]"` adds mypy to the project venv, and two tests are skipped without it).
  Inherent: a call that relies on conversion (`connect("a@b.co", 8080)` for `Email` / `Port` parameters) is reported
  by a checker: caller and body see one parameter type.
- Publishing: the project was renamed from `pyvalidate` to `enforced` (the decorator `enforced` became `enforce`). The name
  `enforced` was not registered on PyPI on 2026-10-12 (`pypi.org/pypi/enforced/json` answered 404); `enforce`, one
  letter shorter, is another project's (runtime type hint enforcement, 0.3.4). The licence is MIT (the owner's decision, 2026-10-13): `LICENSE`, and
  `license = "MIT"` in `pyproject.toml`. The copyright line names the owner, Christos Synodinos. Nothing in the repository depends on the distribution name except `pyproject.toml`.
- Error path: about 1.3x pydantic's time now (it was 4.4x, then 2.4x). What is left is frames (wrapper, fallback,
  `check_inputs`) and, for the keyword lanes, the binding. A failing `Annotated` check runs once (finding 46, closed 2026-10-13):
  the predicate of `Annotated[T, check]` leaves why it refused in `_checks.REFUSED` (value, check, raised, answer;
  a value refused for its type runs no check and empties it, and `constraint_failure` takes the note for the value
  itself only if it has the target's type: 2026-10-18, the property fuzz found a note about the same `-0.5`
  object, left by a deep list and never read, given as the reason for `Annotated[int, positive]`),
  `PreparedChecker._problem` reads it at once (`constraint_failure(..., known = True)`; by identity, emptied), and
  the compiled wrapper names the parameter whose test failed (`_pv_fallback(_pv_a, _pv_k, name)` -> `failed` ->
  `skip` in `check_inputs`), so the pass doesn't run that test again. Not for a parameter tested against the
  class of the call (`Self`), whose test is the wrapper's own. A check that passes, for another argument of the
  same wrong call, is still run by the wrapper and by the pass.
  Rendering a message (`str(e)`) is about 1.7 µs (pydantic: 0.45), spread thinly: no single part is above 0.25 µs.
- **Five changes from the app benchmark** (`prototypes/enforced-apps`, 2026-10-15; the owner chose 1, 2, 3, 5, 6 of
  a plan of seven, and left `typecheck_record` alone):
  - `Problem.__str__` read on its own decides colours once (an app renders each problem of a 422 separately).
  - `_invalid_reason` keeps its candidate converters on the plan entry's container (`keep`); they were built per error.
  - One `TypeModel` is converted by `_one_model`: `validate` called directly, where four calls did it. A test
    compares it with the long way over every kind of value.
  - Deep parameters have plan entries (`DEEP`, the node as `quick`; `_deep_entry_problems`), so a wrong call of a
    deep function takes the one pass. Their converter is made from that same node (`deep_converter(nodes[name])`).
    The dataclass reporter's short route must skip `DEEP` entries as it skips `NO_TYPE` ones (a test holds it).
    `_only_type`'s `quick` also covers one model in a union (`Url | None`), and `constraint_failure(known)` takes a
    refusal of the converted value (`-3.0` for `-3`).
  - `_deep`: a node's `fix` converts a value that has just failed its test without testing it again; a TypedDict
    row is converted field by field without the row test first; `_fix_all` notes on the node where it stopped
    (`_stop`: the id of the items and the index), and `Items.errors` searches from there.
  Effect in the apps: a bad row among 50 328 -> 139 µs (pydantic 46), a valid 50-row import 207 -> 183 (119);
  over HTTP enforced and pydantic now serve within 1% of each other.
- **Bulk conversion** (the owner's request, 2026-10-15). Three changes in `_deep`, measured on the apps' 50-row
  import (148 -> 114 µs for the whole call; pydantic about 119):
  - A `TypedDictNode` and an `Items` of a leaf write their `convert` out (`_converter`, exec'd like `check`):
    each field or item tested inline and converted with the leaf's `conv` directly. The class's own `convert`
    method stays: it is the general way, and `test_the_written_out_converters_answer_as_the_general_ones`
    compares the two on random values. Lists of floats and complex numbers keep `_fix_all`, which has the
    one-pass C-level conversion of the numeric tower.
  - `Node.sound`: what `convert` returns always passes `check`. True for a leaf (its `conv` accepts only what
    its own spec accepts), and for a list or a TypedDict made of sound nodes; `deep_converter` then skips the
    second test of the result. Everything else (unions, mappings, tuples, Annotated containers, recursive
    aliases) is tested again: don't mark a node sound without the argument for it.
  - `_rebuild` hands back the list it was given for a list (every caller made it for this).
- **Error paths** (2026-10-15, the apps' invalid requests 0.60x -> 0.69x pydantic's time):
  - `format_annotation` keeps the text of an annotation (`_SHOWN`, held weakly, never one naming a `<locals>` class).
  - `describe_origin` keeps a function's label on it (`__enforced_label__`: its id, its owner then, both texts).
  - A checker keeps the head of each message (`heads`, `_head`: `type_head` / `invalid_head`, by parameter,
    colours and owner; at most `_HEADS_MAX`), and a problem made by `_problem` renders only its tail
    (`_render_type`, `_render_invalid`: `(function, checker)` as `_render`).
  - The compiled wrapper hands the general path the call as converted so far (`so_far` / `so_far_fast` in
    `generate_wrapper`), so arguments before the failing one are not converted twice.
  - `_problem` makes a plain wrong type at once where the long way could find no reason (`_only_a_type`): one
    `Annotated` member, no TypeModel, a value not of its type, and no refusal by its checks noted since the pass
    (or the wrapper) tried the value (`fresh`; after a hand-over only while nothing has failed yet). A refusal by
    one of its checks means a converted value was refused ("-5" coerced to -5): the long way decides.
    `test_reasons_through_the_compiled_wrapper_are_those_of_the_long_way` compares 2,000 calls per option set.
- Import time is 19 ms on a native disk, and about 255 ms on the dev machine's Windows mount (26 modules, 7 ms each).
- A callable in `Annotated` metadata without the `Check` marker is still a check (the short form), also one that was
  meant to transform (`str.strip`): its message now says what it returned. Taking only marked callables for checks
  would end the ambiguity for good and break every `Annotated[int, lambda ...]` written so far: the owner's call.
- A dataclass field that uses `Self`, in a subclass that isn't decorated, is checked on the slow path (the reporter,
  about 1 µs per assignment). A `default_factory` result for such a field is checked with `Self` as the decorated class.
- `README.md` mentions `bash run_tests.sh`; keep that script and the commands above in step.
- **A pydantic hook is parked** (the owner's decision, 2026-10-17: not sure the combination is worth it; README,
  Limitations, says pydantic ignores enforced's checks). If it is taken up: `__get_pydantic_core_schema__` on
  `TypeModel` and `Check`, `pydantic_core` imported inside it (no dependency), pydantic parsing first, a guard so no
  number-based model takes a bool, a masking serializer for `SecretStr`, no JSON schema. The experiment is
  `prototypes/enforced-apps/combined_fastapi` (its `edge()` is what the hook would replace).


## `enforce`: notes for later

`typecheck` and `enforce` were split on 2026-10-11 (the user's design: `typecheck` for functions and methods only,
`enforce` for plain classes only, the same five options, a way to leave methods out). The user asked for anything else
that came up to be written down here rather than built. None of these is implemented:

- **Assignment to annotated attributes.** `enforce` checks calls only. `self.x = "a"` under a class-level `x: int` passes.
  Checking it (as `dataclass(check_assignment=True)` does, with a generated `__setattr__`) is what would set `enforce`
  apart from decorating each method.
- **Properties.** Done on 2026-10-13 (see "How it works"). The deleter is never wrapped.
- **Special methods.** Done on 2026-10-11 for the ones a caller hands values to (see "How it works"). Still unchecked,
  on purpose: comparisons, operators, `__exit__`, `__setattr__` (the user: "leave setattr alone"), `__iter__`,
  `__len__`, `__getattr__`. Candidates if asked: `__missing__`, `__format__`, the return value of `__len__` / `__bool__`.
- **Subclasses.** A subclass is enforced only when it is decorated too. `__init_subclass__` could carry the options down.
- **Methods without annotations.** Done on 2026-10-12: they stay plain. A method with only a return annotation and
  no `check_return` still gets a wrapper with nothing to do (`def __init__(self) -> None`); telling that apart
  needs the annotation names, which are not known without evaluating the annotations.
- **Methods added after decoration** (monkeypatching, a mixin assigned later) are not wrapped. Documented in the README.
- **`typing.no_type_check`.** Done on 2026-10-12: honoured above or below `@typecheck`, on a method and on a class
  (see "How it works").
- **Callable objects.** Done on 2026-10-12: an object with `__call__` and a `functools.partial` are checked against
  what they call (see "How it works").
- **A list of names instead of a mark.** The user's first idea was a class attribute, `skip_typecheck = ["render"]` (the mark's old name).
  The mark on the method was chosen because it survives a rename, can't be misspelt, leaves nothing on the class and
  isn't inherited by accident. A list (or `@enforce(skip = (...))`) would be easy to add next to it if one place for
  all the names is wanted; as a class attribute it can't share a name with the decorator, which a
  class body would then shadow.
- **Methods of a dataclass.** Done on 2026-10-14 (see "How it works"). A hand-written `__init__` of an `init = False`
  dataclass is still not wrapped.
- **`@dataclasses.dataclass` written above `@enforce`** is not noticed: `enforce` runs first, on what is still a plain
  class, and the `__init__` generated afterwards is unchecked.
- **A method with `@typecheck` in a class that isn't enforced.** Done on 2026-10-12: it finds its class on the first
  call (see "How it works").
- **Keyword-only options.** `enforce(cls, False)` is legal, as with `typecheck`. `dataclass` takes its options by
  keyword only; `enforce` could do the same before anyone depends on the positions.
- **Static checkers** still accept `typecheck(SomeClass)`, since a class is a `Callable`. It fails at import time.
