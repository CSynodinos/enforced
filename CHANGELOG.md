# Changelog

All notable changes to enforced. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/) (before 1.0, a minor or patch release may still change
the API; such changes are listed under **Changed** and marked **breaking**).

## [0.2.1] - 2026-11-28

### Fixed

- **A list coerced to a `set[X]`, `frozenset[X]` or `tuple[X, ...]` names its failing items** (`deep = True`,
  `coerce = True`). When every item was good the list was converted, but when one failed the problem blamed the
  container (`expected type: 'set', got type 'list'`, `loc` `['tags']`). Now each failing item is reported as for
  `list[X]`, by its place in what was given:

  ```python
  @validate(coerce = True, deep = True)
  def label(tags: set[int]) -> set[int]: ...

  label(["1", "x", "y"])   # InvalidDataError: tags[1] and tags[2], each "expected type: 'int', got type 'str'"
  ```

  The same inside `Optional` / `| None`, other unions, `Annotated` and nested containers, for the `typing` forms
  (`Set`, `FrozenSet`, `Tuple[X, ...]`), and the other way round (a tuple or a set coerced to a `list[X]`). An
  `Annotated` check that refuses what the list became is reported as that check (`invalid 'frozenset': failed check
  ...`). Without `coerce` nothing changes: a list isn't converted to a set or a tuple there, so it is the wrong
  container. Valid calls are unaffected: the change is on the error path only.

## [0.2.0] - 2026-11-27

### Changed

- **Breaking: a `date` takes no `datetime`.** `datetime` is a subclass of `date`, so a `date` field used to keep a
  datetime's time, and two values meaning the same day compared unequal. Now a `datetime` is a wrong type for
  `date`, `date | None`, `list[date]` and every other place a `date` is checked, as `int` takes no `bool`:

  ```python
  @validate
  def due(day: date) -> date: ...

  due(datetime(2026, 10, 17, 15, 30))   # InvalidDataError: expected type: 'datetime.date', got type 'datetime.datetime'
  ```

  Write `date | datetime` (or `object`) where both are meant. A `date` subclass that is no `datetime` is still a
  `date`.
  - Under `coerce`, a naive midnight is its day: `datetime(2026, 10, 17)` becomes `date(2026, 10, 17)`, the mirror
    of a `date` for a `datetime`, so a value goes `date` → `datetime` → `date` unchanged. A time is refused with
    `has a time (15:30:00): a date field takes a day`; a time zone, midnight included, with
    `has a time zone: which day it is depends on where it is read`.
  - `dispatch`: a version registered for `date` no longer takes a `datetime`. A version for `datetime` (or a
    subclass of it) registered after one for `date` is reachable now, where it was refused as unreachable.

### Added

- **Durations under `coerce`**: text becomes a `timedelta`.
  - The short form: `"500ms"`, `"30s"`, `"5m"`, `"2h"`, `"1d"`, `"1w"`, `"1h30m"`, `"1h 30m"`, `"1.5h"`, `"-5m"`.
    Units are lower case, largest first, each once.
  - ISO 8601: `"PT30S"`, `"P1DT2H"`, `"P2W"`. Years and months are refused: they have no fixed length.
  - What `str(timedelta)` writes: `"0:00:30"`, `"1 day, 2:03:04.5"`, `"-1 day, 23:59:59"`.

  A number is refused (`write it with a unit: "30s", "5m"`): seconds or milliseconds would be a guess. So is
  anything finer than a microsecond, and anything too large for a `timedelta`; nothing is rounded. Every
  refusal says why. Without `coerce`, text is refused as before.

### Internal

No change to what a call does or returns.

- **A compiled wrapper takes about 30% less memory.** Wrappers of the same signature shape now share one source
  string as `__enforced_source__`, where each held its own copy: 18.6 KB → 12.1 KB for a function with five
  parameters. The speed of a call is the same (38 ns fixed + 13 ns per parameter, as before).
- **The names in generated code say what they are.** The code that wraps a function (`wrapper.__enforced_source__`,
  and the globals of a wrapper or of a dataclass's `__setattr__`) now uses descriptive names with the `_pv_` prefix:
  `_pv_args` / `_pv_kwargs` / `_pv_n_args` for the call, `_pv_arg_0` for a parameter's value, `_pv_converted_args`
  for what was converted, `_pv_function` for what is called, `_pv_fallback` for the general path. A name that is a
  numbered one in the old code is spelt out the same way (`_pv_type_0`, `_pv_converter_0`, `_pv_param_name_0`). A
  check made with a function (`Annotated`, `Literal`) uses `_pv_predicate_0`, not `_pv_type_0`. Only code that reads
  these names is affected.
- `_codegen.py` is easier to read and change: the writer of the source is the class `_WrapperWriter`, with a method
  for each part (`emit_self_class_setup`, `emit_fast_args_only_lane`, `emit_general_binding_lane`), and the decisions
  that `generate_wrapper` used to make inline are small functions. `generate_wrapper` takes the fallback as an argument
  and no longer makes a second one.

## [0.1.4] - 2026-11-20

### Changed

- **Breaking: a `TypeModel`'s hook is now `clean`, not `validate`.** The old name was also the name of the
  `@validate` decorator, which made a model's code confusing to read, and inside a model's class body it
  hid the decorator. Rename the method in your models:

  ```python
  class Username(TypeModel[str]):
      @classmethod
      def clean(cls, raw: str) -> str:      # was: def validate(cls, raw: str) -> str
          ...
  ```

  Nothing else changes: `clean` returns the normalised value or raises `ValueError(reason)`, as `validate` did.
  A model that still defines `validate` is not refused, but its method is no longer called, so update every model
  when you upgrade.
- **No dependencies.** clitint, which colours the messages, is now an optional extra:
  `pip install "enforced[colour]"`. Without it, every message is plain text and everything else works the same.
  With it, the colours and messages are what they were. `turn_colours_off()` and `turn_colours_on()` are still
  exported; without clitint they do nothing. If you want coloured messages after upgrading, install the extra.
- `Err` is generic in its exception (`Err[E: BaseException]`), and `protect` is declared to return
  `Ok[T] | Err[Exception]`, which is exactly what it catches. A type checker now knows the type of `error` in a
  `match` on the result.
- The overloads of `validate`, `enforce`, `dataclass`, `dispatch` and `dispatchmethod` show the real default
  of every option (`allow_subclass: bool = True`), where an editor showed `= ...` on hover.

### Added

- `unwrap_protected(result)`: what a result of `protect` holds, the value of an `Ok` or the exception of an `Err`.
  The exception is returned, not raised.
- The `colour` extra (`pip install "enforced[colour]"`).
- README, Limitations: a `TypeVar` is not checked for consistency (`def f(a: T, b: T)` accepts `(1, "x")`, and so
  does a PEP 695 generic), and `check_return` on a generator checks the generator, not what it yields.

## [0.1.3] - 2026-11-15

The releases up to 0.1.3 have no changelog entries: see the
[tags](https://github.com/CSynodinos/enforced/tags) for their code.

[0.2.1]: https://github.com/CSynodinos/enforced/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/CSynodinos/enforced/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/CSynodinos/enforced/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/CSynodinos/enforced/releases/tag/v0.1.3
