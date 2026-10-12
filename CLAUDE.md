# enforced

A small runtime type checker in the style of pydantic. Python 3.14+, one dependency (`termcolor`).
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
Set `ENFORCED_COLOURS_OFF=1` to get plain-text messages.

## Public API

- `@typecheck` for functions and single methods. Options: `allow_subclass`, `check_return`, `convert`, `coerce`, `deep`.
  It refuses a class.
- `@enforce` for plain classes: `__init__`, every method the class defines and the special methods a caller hands
  values to (`__call__`, `__getitem__`, `__new__` ...), with the same five options.
  `@skip_typecheck` marks a method it is to leave alone. It refuses a dataclass and anything that isn't a class.
- `@dataclass` (enforced's drop-in for `dataclasses.dataclass`): checks construction, defaults and assignment.
- The decorators without the `@`: `typecheck_function(fn, args, kwargs, **options)` checks one call and makes it
  (`typecheck(fn)(*args, **kwargs)` in one step, the wrapper remembered), `enforce_class(cls, **options)` enforces a
  class that is already defined and returns it (`enforce`, options by keyword only).
- `typecheck_from_dict(spec)`: a call described by a dictionary; it checks and returns `(args, kwargs)`, calling nothing.
- `TypeModel[T]` and `enforced.data_types` (`Email`, `Port`, `PositiveInt`, `NegativeInt`, `NonNegativeInt`, `Number`).
- `TypeCheckerError` (a `TypeError`): carries `.problems` as data (`kind`, `parameter`, `expected`, `value`, `origin`, `detail`).

## Layout

```
pyproject.toml                the package: name, version (read from enforced.__version__), termcolor as the only
                              dependency, the `dev` and `bench` extras, py.typed as package data. setup.py is a shim
MANIFEST.in                   puts the whole tests/ folder into the sdist
enforced/
  __init__.py                 exports dataclass, the typechecker API and TypeModel; __version__ and __all__
  py.typed                    empty marker: the package ships its own type information (PEP 561)
  data_types.py               Email, Port, PositiveInt ... (user-facing validated types)
  utils.py                    formatter() for coloured messages, and colours_on(): whether a message is coloured now
  _dataclass_override.py      enforced.dataclass: init wrapper + generated __setattr__
  _typechecker/
    api.py                    typecheck, enforce, the functional API, PreparedChecker, spec/converter compilation,
                              messages
    _type_container.py        TypeContainer (annotation -> runtime types), TypeUnion, TypeCheckerError, Problem
    _file_types.py            stand-in classes for typing.IO / TextIO / BinaryIO (isinstance knows what a file is)
    _type_conversion.py       convert/coerce rules, TypeModel conversion hook, FAILED sentinel
    _deep.py                  deep=True: node tree that checks items inside collections
    _type_data_model.py       TypeModel base class
tests/                        pytest, one file per subject; test_type_data_model / test_data_types / test_validated_types
                              cover validated values, test_enforced the class decorator and what each decorator refuses,
                              test_functional typecheck_function, enforce_class and what a record string may name,
                              test_future_annotations a module where every annotation is a string, test_static_typing
                              what a type checker is told (static_typing_sample.py is the file mypy reads),
                              test_scripts that run_tests.sh fails when a test does, test_formatter the colours.
                              test_known_issues.py holds the issues still open, as strict xfails (two at the moment).
                              conftest.py renders every message without colours (a test about colours switches them on)
tests/simulation.py           phases 1-6 by feature; every check is counted and any surprise fails the run.
                              Phase 7: the fixes of both code reviews, then the known issues (correct behaviour of
                              unfixed bugs): they never fail the run, and print FIXED once they pass (then make them
                              regular checks). Phase 8: an application end to end, re-entrancy, threads, stacked decorators
tests/benchmark.py            benchmark + coverage matrix
tests/fuzz.py                 differential fuzz against a previous copy of the package, and property checks on the
                              working tree alone (not a pytest file). 24 ways to use an annotation (USES)
```

## How it works (read before changing anything)

- **The first call compiles a wrapper.** `PreparedChecker` reduces every annotation to a *spec* (`("any",)`,
  `("isinstance", T)`, `("nobool", T)`, `("is", T)`, `("in", set)`, `("pred", callable)`) and exec-generates a wrapper
  per signature shape (`_CODE_CACHE`). The hot path only answers "definitely fine"; anything else goes to the
  slower path that builds the detailed error. Don't slow the valid-call path to improve the error path.
- **Errors are lazy.** A `Problem` stores data and a `_render` callable; the coloured text is built only when
  `str()` is called. Keep that: message formatting must never run on the hot path.
- **Conversion runs only on values that fail the check.** `convert=True` (default) applies the numeric tower
  (int -> float/complex, never bool). `coerce=True` (off by default) adds parsing (`"42"` -> 42) and includes conversion.
  Converters return `FAILED` (from `_type_conversion`) on failure; it is the one sentinel, shared with `_type_data_model.py`.
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
- **`Self`.** `_resolve_annotations` swaps it for the owner class, wherever it stands in an annotation (`_has_self`,
  `_with_self`: `Self | None`, `list[Self]`, `type[Self]`; found by identity, the annotation rebuilt around it). With
  `allow_subclass=False` it is swapped for a stand-in instead (`self_stand_in`, metaclass `SelfType`) that accepts the
  owner and its subclasses: for an inherited method `self` is a subclass instance, and "exactly the defining class"
  rejected every `return self`. `type[Self]` in strict mode tests `issubclass` against the stand-in's owner
  (`_class_spec`, `matches_class`). It is the class that *defines* the method, never `type(self)`: a check sees one
  value at a time (known issue, with an xfail test).
- **TypeModel.** `class Email(TypeModel[str])` with a `validate(cls, raw)` classmethod that returns the normalised value or
  raises `ValueError(reason)`. `TypeModel[T]` returns a cached real base `(TypeModel, T)`, so an `Email` *is* a `str`. The checker calls
  `__enforced_convert__` under `convert=True` (class flag `auto_construct`); a rejected raw value becomes an `"invalid"` problem.
  Subclasses can't define `__new__`/`__init__`; instances are immutable and pickle by re-validating.
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
  `TypeModel` inherits `Generic[T]` only for static checkers (mypy refuses `TypeModel[str]` otherwise; our own
  `__class_getitem__` still answers at runtime). A checker learns that a model is a `str` when the base is named again,
  `class Email(TypeModel[str], str)`, which is how `data_types.py` writes its models; the MRO is the same either way.
- **`Annotated[T, check]`.** Callable metadata runs as extra checks after the type test (`TypeContainer._constraints`,
  `constraints_pass`). A check rejects by returning falsy or raising one of `CHECK_ERRORS`: `ValueError`, `TypeError`,
  `ArithmeticError`, `LookupError` (its message becomes the reason). Anything else is a bug in the check and
  propagates. Non-callable metadata is ignored. `get_type_hints(..., include_extras=True)` is what keeps the metadata.
- **Problem kinds:** `type`, `default`, `return`, `missing`, `field` (dataclass assignment), and with deep/validated types
  `length`, `missing_key`, `cycle`, `invalid` (right type, rejected value; reason in `detail`). With `deep`, `invalid` is also
  the whole-value verdict when no single item is to blame: keys that collide after conversion, or a container whose type
  can't be rebuilt with converted items (`_rebuild` / `_rebuild_mapping` return `FAILED`; they never fall back to list/dict).
- **Nested items are read through one-shot iterators** (`chain.from_iterable`). `_items_expr` writes the items expression out
  again for every pass (the types, then each `Annotated` check); a batch function must never read its argument twice.
- **Dataclass fields are validated once.** The generated `__init__` wrapper publishes its checked arguments in the generated
  `__setattr__`'s globals (`_pv_args` / `_pv_kw`, the `mark` hook of `_wrap_callable`) while the real `__init__` runs. A field
  whose check calls a function (`"pred"` spec: deep items, `Annotated` checks, `Literal`) skips it for the very object it was
  given, or for its already-checked default. Inline type tests are simply repeated: cheaper than any bookkeeping. Classes
  without `"pred"` fields generate exactly the old code.
- **`default_factory`.** With the assignment check, `__setattr__` validates what a factory returns. Without it (frozen,
  `check_assignment=False`) `_check_factories` wraps each factory before the dataclass is built.
- **Defaults `__init__` doesn't take.** `field(init=False, default=...)` is no parameter, and only a slots class ever assigns
  it. `_unlisted_defaults` hands these to `_check_defaults` (the `extra_defaults` hook of `_wrap_callable`), so they are
  checked with the other defaults on the first construction. A converted one is stored where instances read it: the class
  attribute, or with `slots=True` the closure cell `__dataclass_dflt_<name>__` of the generated `__init__`.
  With `@dataclass(init=False)` there is no generated `__init__` at all: `_check_defaults_once` puts a thin wrapper around
  the class's `__init__` (its own or the inherited one) that checks every field default on the first construction and then
  takes itself away again. With `slots=True` it does nothing: no instance and no class holds such a default.
- **The annotation caches evict.** `_UNPACKED` (`_type_container`), `_DEEP_NODES` and `_CODE_CACHE` (`api`) drop their
  oldest entry when full, under a lock (`_UNPACKED_LOCK`, `_CACHE_LOCK`); reads take none. Before, a full cache stopped
  taking entries and every later function went without. Without the lock an eviction can meet another thread's insert
  (`RuntimeError: dictionary changed size during iteration`, seen in 1 run of 10 under a tight switch interval).
- **`typecheck_function` and `enforce_class`** (the user's design, 2026-10-12: a non-decorator way to do the same
  thing; an earlier version that only checked and returned the arguments was replaced). `typecheck_function` wraps
  the function exactly as `typecheck` would and calls the wrapper; the wrapper is kept in `_CALL_WRAPPERS`, by `id()`
  of the function (the entry holds it, so the id stays its own), one per set of options, the 512 most recent. A bound
  method is taken apart (`__func__` with `__self__` in front): it is a new object at every lookup. The function
  itself is never replaced, so a direct call stays unchecked. `enforce_class` is `enforce` behind a check that it
  was given a class.
- **Converted defaults** (`x: float = 0`). `_check_defaults` returns them; `PreparedChecker._prepare` decides by
  `rewrite_defaults`. `True` (a decorator): the wrapper calls a copy of the function that has them (`_with_defaults`,
  kept as `checker.call`): no cost per call, and the function that was decorated keeps its own. Where the defaults
  aren't the function's own (`functools.wraps`, a `partial`, an object with `__call__`: `_own_signature`), they are
  passed with each call that leaves the parameter out: `checker.inject`, applied by the generated wrapper (`_pv_dk`
  for keyword-only ones in the fast lane, `keep_kw` in the general lane) and by `with_defaults` on the fallback path.
  `_IN_PLACE` (a dataclass's generated `__init__`, nobody else's): written into the function. `_PASSED`
  (`typecheck_from_dict`): handed back with the checked arguments. `False`: nothing (a field checker).
  The fallback calls `checker.call`, read at each call: the first one may swap in the copy.
- **A checker has its own signature** (`checker.sig`). `_signature(fn)` is the function's, cached and never
  altered; `_typed_kwargs(record, sig)` returns the record and signature with `**kwargs: Unpack[TypedDict]` laid
  out, for that checker alone. Everything that binds takes `sig` from the checker (`_generate_wrapper`,
  `_full_check`, `_check_defaults`, `_realign_positional`).
- **`typecheck_from_dict` cache.** Keyed by the record with `==`; a record with unions inside holds one checker per member
  order (`_union_order`), because `int | float == float | int` while conversion follows the declared order. Hits read the
  cache without a lock; everything that changes it (`_remember_checker`: insert, evict the oldest) runs under
  `_FROM_DICT_LOCK`, so misses from several threads can't meet halfway through an eviction.
- **Strings are read, not run.** An annotation that is still a string when it reaches `TypeContainer` (a record of
  `typecheck_from_dict`, or a name that resolves nowhere) goes through `read_annotation`: `ast.parse`, then only names
  from a fixed list, subscripts, `|`, tuples, lists and constants. The list (`_record_name`): the built-in classes,
  `_RECORD_NAMES` (`Any`, `Optional`, `Union`, `Literal`, `Sequence`, `Mapping`, `List` ...: each a fixed object),
  and `_RECORD_CLASSES` (`datetime`, `Decimal`, `UUID`, `Path` ...: imported when a record first names one). A dotted
  name is accepted for the modules in `_RECORD_MODULES` only; no attribute of anything else is ever read. No `eval`
  there: a record is data and may come from a request. Adding a name to the list means: nothing callable to any
  effect may become reachable through it. `_deep._compile` reads a string the same way, so `"list[int]"` has its items checked. A function's own string
  annotations are resolved earlier, by `_resolve_annotations`, in its module (that is source code, and may be evaluated).
  A record value that is plain data (`5`, `["int"]`) is refused in `_flatten_expected_types` (`_NOT_ANNOTATIONS`); what
  falls through to "anything" after that are typing forms without a runtime test (`P.args`, a TypeVarTuple).
- **What a string annotation may name** (`_local_names`): the globals of its module, the owner class, the type parameters
  of that class and its bases (`class Box[T]`: without them every method and a generic dataclass failed under
  `from __future__ import annotations`), and names local to the function the definition is written in. Those last ones
  are gone by the first call, so `_remember_scope` looks them up at decoration, in the frames that are lexical parents
  (`co_qualname` is a prefix of the target's `__qualname__`: never the caller of a helper), and keeps only the names the
  annotations use, on the function or class (`__enforced_scope__`). It runs only for `<locals>` targets, and
  `_annotation_texts` returns nothing when no annotation is a string (no future import, nothing quoted: Python keeps the
  scope itself), which is the test that keeps decorating a local function cheap.
  A name that comes into being after the decorator ran (a class a few lines further down) is looked for once more
  when resolving fails (`_look_again`): on the stack, where the enclosing function's frame still is if it is running.
  What is found is added to the kept scope. No frame is held on to for this: a frame keeps its caller's frames, and
  with them every local of the whole stack, alive. Once the function has returned the name can't be found.
- **A nested name inside an annotation** (`List["Json"]`, the old way to write a recursive alias) is resolved by the deep
  compiler through `resolve` (`_resolver`: `eval` in the function's module with `_local_names`). It is threaded from
  `PreparedChecker` through `_compile_spec` / `_compile_converter` / `_deep_node` to `_deep.compile_node`, and is only
  ever set for annotations from source code: a `typecheck_from_dict` checker has none, so its strings stay data. A name
  that resolves to an annotation already being compiled becomes a `Proxy` cycle, like a recursive `type` alias.
- **A method decorated on its own finds its class** on the first call (`_find_owner`, from `PreparedChecker._prepare`):
  through `self` / `cls` when the first argument's MRO holds a class whose `__qualname__` is the function's prefix,
  else by name from the module (a static method). That gives it `Self`, the class's type parameters and the label
  `<Method Owner.name>`. Functions with `<locals>` right before their name are plain functions and are not looked up.
- **Callables without annotations of their own** (`_annotations_of_what_it_calls`): an object with `__call__` is checked
  against that method, a `functools.partial` against the function it wraps (for the parameters it still takes). Only
  when the callable's own record is empty, so a wrapper made with `functools.wraps` keeps going through `__wrapped__`.
  A builtin whose signature `inspect` can't read (`max`) gets `(*args, **kwargs)` in `_signature` and passes through.
- **`**kwargs: Unpack[TypedDict]`** is checked as if each key were a keyword-only parameter (`_typed_kwargs`): the record
  gets one entry per key and the checker's signature shows the same (`_with_typed_kwargs`; an optional key has the
  default `_NOT_GIVEN`, which `_check_defaults` skips). Everything else (generated wrapper, conversion, missing and
  unknown keywords) then works unchanged. `inspect.signature` of the wrapper still shows what was written. A key that
  is no identifier (`"my-key"`, `"class"`) becomes a `_KeyParameter`: `inspect.Parameter` refuses such a name, and
  the generated wrapper never writes names into source (they live in its namespace).
- **`*args: *tuple[int, str]`** is checked as one tuple by a `FixedTuple` node, and
  `*tuple[int, *tuple[str, ...], float]` by a `VariadicTuple` (`_args_node`, kept on the checker as `var_pos_node`;
  `_deep.spread` lays the items out). The generated wrapper tests the extra arguments with the node's `check`
  (`_pv_vp(_pv_a[n:])`); a call that needs converting goes to the fallback, where `_fast_ok`, `_convert` and
  `_type_problems` have the three small branches. `*tuple[int, ...]` is rewritten to the plain per-argument check.
  With `deep`, `tuple[A, *tuple[T, ...], B]` as an ordinary annotation compiles to the same node.
- **A wrapper says what kind of function it wraps.** `inspect.isgeneratorfunction` reads one flag on the code object,
  and pytest (`yield` fixtures) and others branch on it. The wrapper of a generator function is an ordinary function
  that checks at the call and returns the generator, so its code objects carry that flag (`_stub_codes`: `_BOOT_CODES`
  until compiled, `_PLAIN_CODES` for an unchecked one; `_generate_wrapper` flags what it compiles, cached under
  `(source, kind)`). Python doesn't read the flag when it runs code (a real generator function begins with
  `RETURN_GENERATOR`), which `test_checked_generator_function_is_still_checked_when_it_is_called` holds: if a future
  Python changes that, this test fails. A function keeps the kind of code it was made with: assigning another kind
  is deprecated (3.14 warns). `_function_kind` answers from the code flags for a plain function, and decorating got
  cheaper for it (three `inspect` calls cost more than everything else).
- **`typing.no_type_check`.** Marked before decoration: `_wrap_callable` returns the function as it is, `enforce`
  skips the method, `dataclass` builds a standard one. Marked after (`@no_type_check` above `@typecheck`): the mark
  lands on the wrapper, is seen on its first call and turns it into a pass-through (`_unchecked`).
- **TypeVar bounds written as strings.** `typevar_types` looks `bound="Shape"` (and string constraints) up in the module
  that defines the TypeVar; `_flatten_expected_types` and `_deep._compile` both use it.
- **File annotations.** No real file inherits from `typing.IO` / `TextIO` / `BinaryIO`, so `_flatten_expected_types` swaps
  each for a stand-in class from `_file_types.py` (also `IO[str]` / `IO[bytes]`). Its metaclass (`FileType`) answers
  `isinstance`: the built-in file classes first (plain C types, the fast answer), then the `io` ABCs and the typing class,
  then "a file of the other kind" (rejected), and last an object with every file method (text when it has an
  `encoding`). The stand-ins are named and placed in module `typing` so messages read `'typing.TextIO'`; `is_abstract`
  is true for them, so strict mode uses `isinstance` too.
- **One check per dataclass instance, its own class's.** A decorated class's fields include the inherited ones, so its
  generated `__setattr__` covers the whole instance with its own options. It calls what a decorated base's `__setattr__`
  wraps (`__enforced_wraps__`, found by `_plain_setattr`), never that `__setattr__` itself: checks don't stack, and
  a subclass can loosen, tighten or retype what it inherits. `check_assignment=False` below a checking base installs the
  wrapped function directly (`_unchecked_setattr`). A base's check that is still reachable through a hand-written
  `__setattr__` calling `super()` is told to `step_aside`: it is generated again with one test at the top
  (`_governed_by_subclass`, which looks for the `__enforced_dataclass__` mark every decorated class carries) and leaves
  such instances alone. Only classes in that position pay for the test.
- **Inherited `default_factory` fields.** Their `Field` objects belong to the base class. `_check_factories` swaps the
  factory only while `dataclasses` generates this class's `__init__` (the raw factory when this class's `__setattr__`
  checks the result, a wrapper bound to this class otherwise), then restores it.
- **`@typecheck` above another decorator.** `typecheck` sends a plain function straight to `_wrap_callable` (decorating
  must stay cheap). Anything else goes through `_wrap_member`, which takes a `classmethod`, `staticmethod`, `property` or
  `cached_property` apart, checks the function inside and builds the object again; another non-callable raises at the
  definition. `_is_checked` recognises a wrapper already made, so `@typecheck @prop.setter` doesn't wrap the getter twice.
- **One decorator per kind of thing.** `typecheck` takes functions and methods, `enforce` plain classes,
  `enforced.dataclass` dataclasses. Each refuses the others' at the definition with a `TypeCheckerError` that names the
  right one (`_wrap_member` for a class given to `typecheck`; the top of `enforce`). "Dataclass" there means a class that
  was made one itself (`_is_dataclass`: `__dataclass_fields__` in its own `vars`): a plain subclass of a dataclass is a
  plain class.
- **`enforce`** wraps, in place, `__init__` and every function, `staticmethod` and `classmethod` in the class's own
  `vars` with `_wrap_callable(..., owner = cls)`: exactly what `typecheck` did for a class before the split (the fuzz's
  `method` use compares the two). Properties, inherited and later-added methods are not touched. A method without a
  single annotation stays the plain function (`_unannotated`: read from `__annotate__` / `__annotations__` without
  evaluating anything); a call it can't take is then Python's own `TypeError`.
- **Special methods under `enforce`.** `_CHECKED_SPECIAL` lists the dunders that are checked: those whose arguments a
  caller writes (`__init__`, `__new__`, `__call__`, `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`) and
  `__enter__` / `__aenter__` for their return value. Everything else Python calls itself, often with any object
  (`==`, the operators, `__exit__` with three `None`s, `__setattr__`), and stays unwrapped: don't add to the list without
  that test. `__new__` sits in `vars` as a `staticmethod` whose first parameter is still the class (`skip_first`), has no
  return check (`_CONSTRUCTORS`) and is reported as `<Class X>`. A dunder that a base class holds too is left alone
  (`_held_by_a_base`): every `Enum` class carries `Enum.__new__` in its own namespace.
- **Decorator overloads.** With options, `typecheck` and `enforce` are declared `-> Callable[[F], F]` /
  `Callable[[T], T]`. Declared `-> Callable[[Any], Any]`, a class decorated with `@enforce(...)` was `Any` to Pylance in
  every file that used it. `dataclass` has two overloads returning `type[T]` and carries
  `@dataclass_transform(field_specifiers = (field, Field))`, so checkers build `__init__` from the fields. Guarded by
  `tests/test_static_typing.py`: declarations always, mypy's actual reading of a sample file when mypy is installed.
  It leaves a method alone when it carries the `skip_typecheck` mark (`__enforced_skip__`, set on the object and on
  the function inside a `classmethod` / `staticmethod`, so either order works), and when it has its own `@typecheck`
  (`_checked_inside`, which also looks through `functools.wraps` decorators): those options stand and nothing is
  checked twice. Such a method is only told its class (`_adopt`, through `_pv_checker` in the wrapper's globals), so
  that `Self` resolves and messages read `<Method Owner.name>`.
- **Protocols.** A Protocol that isn't `@runtime_checkable` raises a `TypeCheckerError` (`protocol_error`) instead of failing
  inside `isinstance`; it travels the same path as an unresolved forward reference (`_SLOW`, raised on every call).
- **A dataclass field held by a descriptor** (its class attribute has `__set__`, and is no slot) is not checked:
  the annotation names the descriptor class, the values are whatever it stores. `_descriptor_fields` lists them on
  the class (`UNCHECKED_FIELDS`), and `_resolve_annotations` leaves them out of every record of that owner.
- **Colours.** `utils.colours_on()` decides: `ENFORCED_COLOURS_OFF=1`, `NO_COLOR`, `ANSI_COLORS_DISABLED` off,
  `FORCE_COLOR` on, `TERM=dumb` off, else only when stdout *and* stderr are terminals (a message is one string and
  may go to either). `formatter` passes `force_color=True` to termcolor: termcolor decides from stdout alone and
  caches its first answer for the process. `_render_error` asks once per message (`one_decision`), not once per
  word. `break_trace_colouring` is an object that builds the reset sequence when a message is put together
  (`_TraceReset`): as a constant made at import it ignored colours switched off later.
- **An error pickles with its problems.** `TypeCheckerError.__reduce__` carries message, context and problems;
  `Problem.__reduce__` its data and its text, each part through `_picklable` (a stand-in, `Unpickled`, for what
  pickle refuses). `origin` goes as `(module, qualname)` and is found again through the wrapper (`_find_origin`):
  the function a problem holds is the one inside the wrapper, which pickle can't find by name.
- **`short_repr` formats only what it shows** (`bounded_repr`): the items of a built-in container one at a time until
  the budget is full. Its output is the start of `repr(value)`, exactly: self-containing values, quote choice of
  text and the one-item tuple included (a parametrised test compares).
- **The full path** is `_full_check` (it was `_typecheck_function`): `Signature.bind_partial`, then everything wrong
  with the call. `bind_partial` lets a positional-only parameter through by keyword when an earlier one is left to
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
`Problem.annotation`), cut after 80 characters (`_shortened`), as is the annotation of a length message and the text
of "Cannot resolve annotation".

`TypeCheckerError.__module__` is set to `"builtins"` after the class body so tracebacks show a short name; `__reduce__`
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
5. Style: 4-space indent, `x = y` spacing as in the existing code (`kwarg = value` with spaces is common), `#*` for
   important comments, docstrings on public functions, type hints everywhere.

## Known issues and ideas

- A bug that is known but not fixed gets a strict `xfail` test in `tests/test_known_issues.py` (run it with `--runxfail` to
  see it fail) and a `known_issue(...)` line in simulation phase 7. A fixed one moves to the test file of its subject and
  becomes a regular simulation check. Two are open: `Self` is the class that defines the method and not `type(self)`,
  and a subclass made a dataclass by the standard library is held to its checked base's type for a field it retypes.
- `CODE_REVIEW.md` holds the latest review of the package (the sixth, 2026-10-12, after every finding that could be
  fixed in code was). Read it before starting on a fix, and update it when one lands.
- Static typing: mypy and pyright report nothing in the package's own files (pyright was run from a scratch
  environment; `pip install -e ".[dev]"` adds mypy to the project venv, and two tests are skipped without it).
  Inherent: a model written in the short form, `class X(TypeModel[str])`, is not a `str` to a checker (the long form
  is), and a call that relies on conversion is reported by a checker.
- Publishing: the project was renamed from `pyvalidate` to `enforced` (the decorator `enforced` became `enforce`); whether the name `enforced` is free on PyPI is unchecked, and there is no LICENSE file.
  Both are the owner's to decide; nothing in the repository depends on the distribution name except `pyproject.toml`.
- Error path is slow compared with pydantic (about 4-5x): missing-argument errors, failed value checks, and a
  `TypeModel` whose `validate` runs a second time to get the reason. Keeping the reason from the first run would save the second.
- Import time is ~60 ms (mostly the bytecode cache on a slow filesystem; measure on a native disk).
- Every callable in `Annotated` metadata is a check, also one that was meant to transform (`str.strip`). An explicit
  marker (`Check(fn)`) would end the ambiguity; it is on the README's roadmap with the constraint markers.
- A coloured message still costs one termcolor call per word (about 7 µs against 2 µs plain). Caching the escape
  sequences per spec would end that; `tests/test_formatter.py` asserts on the termcolor calls and would need rewriting.
- `README.md` mentions `bash run_tests.sh`; keep that script and the commands above in step.

## `enforce`: notes for later

`typecheck` and `enforce` were split on 2026-10-11 (the user's design: `typecheck` for functions and methods only,
`enforce` for plain classes only, the same five options, a way to leave methods out). The user asked for anything else
that came up to be written down here rather than built. None of these is implemented:

- **Assignment to annotated attributes.** `enforce` checks calls only. `self.x = "a"` under a class-level `x: int` passes.
  Checking it (as `dataclass(check_assignment=True)` does, with a generated `__setattr__`) is what would set `enforce`
  apart from decorating each method.
- **Properties.** The getter's return value and the setter's argument of a `property` / `cached_property` in an enforced
  class are not checked. `_wrap_member` already knows how to take them apart.
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
- **A list of names instead of a mark.** The user's first idea was a class attribute, `skip_typecheck = ["render"]`.
  The mark on the method was chosen because it survives a rename, can't be misspelt, leaves nothing on the class and
  isn't inherited by accident. A list (or `@enforce(skip = (...))`) would be easy to add next to it if one place for
  all the names is wanted; as a class attribute it can't share the name `skip_typecheck` with the decorator, which a
  class body would then shadow.
- **Methods of a dataclass.** `enforced.dataclass` checks fields, not methods: each method needs its own `@typecheck`.
  An option there, or letting `enforce` take a dataclass and leave its `__init__` alone, would cover them.
- **`@dataclasses.dataclass` written above `@enforce`** is not noticed: `enforce` runs first, on what is still a plain
  class, and the `__init__` generated afterwards is unchecked.
- **A method with `@typecheck` in a class that isn't enforced.** Done on 2026-10-12: it finds its class on the first
  call (see "How it works").
- **Keyword-only options.** `enforce(cls, False)` is legal, as with `typecheck`. `dataclass` takes its options by
  keyword only; `enforce` could do the same before anyone depends on the positions.
- **Static checkers** still accept `typecheck(SomeClass)`, since a class is a `Callable`. It fails at import time.
