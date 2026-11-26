# Changelog

All notable changes to enforced. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/) (before 1.0, a minor or patch release may still change
the API; such changes are listed under **Changed** and marked **breaking**).

## [0.1.4] - unreleased

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

[0.1.4]: https://github.com/CSynodinos/enforced/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/CSynodinos/enforced/releases/tag/v0.1.3
