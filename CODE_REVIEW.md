# Code review of enforced

Tenth review, 2026-10-13. It covers everything since the ninth: errors made late, the dataclass in two tiers, the split of the long files, faster printing of errors, the removal of termcolor, and `on_error`. It replaces the ninth review and the five sections added to it; findings that are still open are carried over below with their numbers.

## Summary

**No finding of High or Medium severity is open, and no known issue.**

- **A wrong call costs about half of what it did.** pydantic was 2.4 times faster on the error path and is 1.3 times faster. Printing an error went from 4.1 µs to 1.8 µs (coloured).
- **A valid call costs what it did.** 1 parameter: 0.064 µs. Constructing a dataclass: 0.44 µs. Assigning a field: 0.060 µs.
- **The package has no dependencies.**
- **`api.py` holds the public functions only** (539 lines, from 3,928). The package is 32 modules.
- **`on_error="warn"` is on every API.** A value that fails is reported as a `TypeCheckerWarning` and the call goes ahead.
- **Eight Low findings are new**, each a consequence of a decision made in this round. Six behaviours changed; see "Behaviour that changed".

| Check | Result |
|---|---|
| `python -m pytest -q tests` | 1,450 passed, 3 skipped (mypy is not in the project venv); the 9 static-typing tests pass from a scratch environment |
| The same with `ENFORCED_COMPILE_AFTER=64` | 1,426 passed, 27 skipped: the 3 for mypy and 24 that look at a compiled wrapper or count checks |
| `python tests/simulation.py -q` | 1,267 checks pass |
| `python tests/fuzz.py --ref HEAD --cases 100000` | every outcome and every message identical to the last commit |
| `python tests/fuzz.py --properties --cases 100000` | no property broken, the new one for `on_error` included (89,653 values) |
| mypy and pyright on the package | no error |
| `python tests/benchmark.py --quick`, calls, classes, errors | tables below |

The fuzz ran after `on_error` was complete and before two small changes: a warning is no longer chained to the error it stands for, and an unusable `on_error` is refused before it is used as a dictionary key. Neither touches a path the fuzz compares.

Open findings:

| # | Severity | Finding |
|---|---|---|
| 2 | inherent | A call that relies on conversion (`connect("a@b.co", 8080)` for `Email` and `Port` parameters) is reported by a static type checker |
| 27 | by design | What `enforce` leaves unchecked: attribute assignment, operators and comparisons, subclasses that aren't decorated, methods added later |
| 34 | Low | `typecheck_function` remembers 512 callables that are not functions |
| 44 | Low | A default of a checked dataclass is validated once, not at every construction |
| 45 | Low | The first 63 calls of a function are slower; the first 63 constructions of a dataclass check each argument twice |
| 47 | Low | A missing argument next to a misplaced one leaves about 27 objects to the garbage collector per error |
| 48 | Low | `e.problems` is a property: the objects are made on first read |
| 50 | Low | **New:** 32 modules take longer to import from a slow disk |
| 52 | Low | **New:** `colours_on` reads a private attribute of the standard library |
| 53 | Low | **New:** with `on_error="warn"`, a dataclass that keeps the standard `__init__` reports a wrong argument twice |
| 54 | Low | **New:** with `on_error="warn"`, a coroutine run by the event loop itself is attributed to a line in `asyncio` |
| 55 | Low | **New:** a warning costs about 3 µs whether or not a filter shows it |
| 56 | Low | **New:** `on_error` is not looked at when `ENFORCED_TYPECHECK_OFF=1` |
| 57 | Low | **New:** one import goes against the module order |
| 58 | Info | **New:** `_deep.py` (1,095 lines) and `_checker.py` (778) are the long files now; some continuation lines are a column off after the renames |

---

## What changed

### 1. Errors

Time to raise and catch, µs (`python tests/benchmark.py --skip-cold --cases "Errors"`):

| Case | Ninth review | Now | pydantic |
|---|---|---|---|
| 1 wrong argument of 2 | 1.05 | 0.56 | 0.48 |
| 3 wrong arguments of 12 | 2.15 | 1.08 | 0.70 |
| Missing argument | 0.99 | 0.55 | 0.53 |
| Unknown keyword argument | 0.86 | 0.71 | 0.58 |
| Wrong keyword-only argument | 1.23 | 0.81 | 0.59 |
| Wrong return value | 1.23 | 0.46 | 0.54 (strict) |
| Dataclass field, wrong type | 1.38 | 0.98 | 0.78 |
| Dataclass assignment, wrong type | 1.54 | 0.42 | 0.47 |
| Value check fails | 1.80 | 0.94 | 0.49 |
| Invalid email | 2.35 | 1.14 | 0.68 |

- **The largest part was a reference cycle, not work.** An error's traceback holds the frame it was raised in. My first version of this change held the error in a local of that frame and was slower than what it replaced (1.08 to 1.25 µs): every error went to the garbage collector. Raising what a helper returns removed 350 ns. A second cycle had existed for a long time in every rejected value: the problem's renderer held the problem. Both are gone, and a test counts what 15 kinds of wrong call leave behind (nothing).
- **`Problem` objects are made when `e.problems` is first read** (finding 48). The check notes which arguments failed; code that only catches the error pays for no objects.
- **A `TypeModel`'s `validate` runs once per wrong call.** It was three times, then two. The compiled wrapper tells the general path which conversion it already tried.
- **A race, introduced and removed.** The checker's layout was visible to another thread before it was complete. The simulation's thread check caught it in 1 run of 6. The field that other code goes by is now assigned last. No unit test reproduces it on demand.

### 2. Printing an error

`str(e)` for one problem: 4.1 µs to 1.8 µs coloured, 2.5 µs to 1.7 µs plain. pydantic: about 0.45 µs.

- **Asking whether to colour was a quarter of it.** Five lookups in `os.environ` took 1 µs. `colours_on` reads the dictionary underneath (0.07 µs; finding 52).
- **The usual message is written in one piece**, with the escape sequences as constants. The text is the same.
- What is left is spread thinly; no part costs more than 0.25 µs.

### 3. The dataclass in two tiers

| | Ninth review | Now |
|---|---|---|
| Defining a class with 6 fields | 0.33 ms | 0.23 ms |
| Its first construction | 0.25 ms | 0.10 ms |
| A construction before the 64th, 3 / 6 fields | 0.33 / 0.41 µs | 1.1 / 1.8 µs |
| An assignment before the 64th | 0.06 µs | 0.2 µs |
| Once compiled | 0.43 µs, 0.06 µs | unchanged |

Defining a class compiles nothing. The `__init__` that stores checked arguments is made at the 64th construction, and the generated assignment check at the 64th assignment. The 0.33 ms was a regression of the ninth review's own work, which compiled that `__init__` at definition. A test compares both tiers over 3 classes, 10 fields, 19 values and 5 option sets.

### 4. The split

`api.py` (3,928 lines), `_type_container.py` (1,255) and `_dataclass_override.py` (963) became 26 modules: 22 beside `api.py`, flat, and a `_dataclass/` package of four. The layout and the import order are in `CLAUDE.md`.

- **Names.** 94 helpers that other modules use lost their leading underscore; 196 that only their own file uses kept it. `signature_of` and `copy_with_defaults` were renamed outright, and `_is_dataclass` was a second copy of `made_dataclass`.
- **A cache lives where it is read.** `from x import CACHE` takes the object as it is at import, so a test that replaced a cache in one module no longer reached the code in another. Three caches moved for that reason, and `api.py` reads two through their module.
- **Pickles of errors from before the split don't load**, as agreed.

### 5. No dependencies

termcolor is gone. `formatting_tool.STYLES` holds the escape sequences of `bold` and seven colours, which are the ones termcolor wrote. A test checks in a fresh interpreter that only the standard library is imported, and another fails when a spec in the package and the table disagree.

### 6. `on_error`

One option on every API, `"raise"` (the default) or `"warn"`. You proposed `async_error_policy` and `sync_error_policy` on the functional APIs; I advised one option everywhere, since a function is either sync or async, and you agreed.

- **Where it is asked.** In four places, each where an error is about to be raised: the two paths of `check_inputs`, `check_return`, and the dataclass field reporter. Nothing is added to a valid call (0.072 µs with the option, 0.072 without).
- **What is raised all the same.** A missing argument, a call that doesn't bind, and a mistake in the definition.
- **Where the warning points.** At the first frame outside the package and its generated code. Python shows a warning once per line it is attributed to; attributed to a line in the package, every warning of a program after the first would have been dropped.
- **A dataclass gets its storing `__init__` at once.** Behind the standard one a wrong argument is met twice, and would have been reported twice for the first 63 constructions.
- **The fuzz holds the rule as a property:** for 89,653 values, `"warn"` gave the same result where `"raise"` gave one, and where `"raise"` raised it gave either the same error or a warning with the same text.

---

## Closed after this review

- **46: a failing `Annotated` check runs once per wrong call.** It ran twice on the general path and three times from a compiled wrapper. The check's own run now leaves the reason behind, and the compiled wrapper tells the general path which parameter's test failed. In the benchmark a failed value check costs what it did (0.94 µs): its check is a one-line lambda, and running it is the cheapest part of the error. What is saved is the check's own cost, once or twice per wrong call, so it matters for a check that does real work or has side effects. A check that passes, for another argument of the same wrong call, is still run twice. The same hand-over spares the general path one type test on every wrong call.
- **51: `formatter` is internal.** The module is `enforced/_formatting_tool.py`. That it takes eight styles is no longer anyone's concern but the package's.

After these: 1,451 unit tests (1,427 with `ENFORCED_COMPILE_AFTER=64`), 1,267 simulation checks, mypy and pyright clean, the fuzz once more (100,000 values identical to the last commit, no property broken).

## Added after this review: the methods of a dataclass

`enforced.dataclass` checks the methods the class defines, as `enforce` does for a plain class. Two options are new: `check_methods` (on by default, your decision) and `check_return`.

- **One loop for both decorators.** What was the body of `enforce` is `_class_rules.enforce_members`; `enforce` and `dataclass` call it. `api.py` is 40 lines shorter.
- **Left alone:** `__init__` and `__setattr__` (checked already), `__post_init__` (its arguments were checked by `__init__`), what `dataclasses` generates, and every field name. A field's default sits in the class under the field's name and may be a function; without that rule `handler: Callable = fallback` would have been wrapped as a method.
- **A method costs what it costs under `enforce`:** 0.131 µs for the same two-parameter method in both, side by side in the benchmark.
- **This changes existing code.** A dataclass method called with a wrong argument was let through and now raises. `check_methods=False` restores the old behaviour, and `on_error="warn"` reports without raising.

| # | Severity | Finding |
|---|---|---|
| 59 | Low | **New:** a hand-written `__init__` in a `@dataclass(init=False)` class is not wrapped. Its assignments are checked field by field, so a wrong value is still caught, but as a field error, not as a wrong argument |
| 60 | Low | **New:** on a frozen dataclass, assigning to a property raises Python's `FrozenInstanceError` before the setter's check is reached. That is `dataclasses`' own behaviour |

Checks: 1,471 unit tests (1,447 with `ENFORCED_COMPILE_AFTER=64`; 16 are new, over ten dataclass option sets), 1,284 simulation checks, mypy and pyright clean, and the fuzz once: 100,000 values identical to the last commit, no property broken. Its first run showed 5 differences, all the same message cut at a different column: the tool's comparison did not allow for the baseline's longer package name in "Cannot resolve annotation" messages. That is fixed in the tool.

---

## Behaviour that changed

- **`e.problems` is a property.** `vars(e)` has no `problems` key.
- **`enforced.formatting_tool` is `enforced._formatting_tool`**, and its `formatter` takes eight styles.
- **A model's `validate` runs once for a refused value**, where it ran two or three times.
- **The first 63 constructions of a dataclass check each argument twice** (finding 45). A check with side effects sees two runs there.
- **`fn.__wrapped__` of a dataclass's `__init__`** is the standard one again, at every tier.
- **Private names moved.** Anything imported from `enforced._typechecker.api`, `_type_container` or `_dataclass_override` beyond the public functions is somewhere else, and often without its underscore.

Your own change of this round is in the same working tree: `protect`'s parameter is `c`, not `coroutine`. I changed two tests and one simulation check that named it.

---

## Open

### 2, 27, 34, 44

Unchanged from the ninth review.

### 45. The first uses are slower

A function's first 63 calls take 0.2 to 0.5 µs more each. A dataclass's first 63 constructions take about 0.8 µs more each, and each argument is checked by the `__init__` check and again on assignment. `ENFORCED_COMPILE_AFTER=1` gives the old behaviour at the old price.

### 47. One error path still leaves a cycle

`_realign_positional` uses nested functions that call themselves. It runs for a missing argument next to a misplaced one, the rarest and already the slowest error.

### 48. `e.problems` is made on first read

Which arguments failed is settled at the call and can't change. The `Problem` objects, their `value` included, did not exist before the first read.

### 50. Import time on a slow disk

19 ms on a native disk (17 before the split). On this machine's Windows mount each module costs about 7 ms: about 255 ms for the package, where it was 60. A test run starts that much later. An installed package is not affected.

### 52. A private attribute of the standard library

`colours_on` reads `os.environ._data`. Where it is missing or is no dictionary, or `os.environ` has been replaced by another mapping, `os.environ` is asked as before. A test covers each way of changing a variable. If a future Python renames the attribute, messages get 1 µs slower and nothing else changes.

### 53. Two warnings from some dataclasses

A dataclass with a `__setattr__` written by hand in its line, or with slots and a default that `__init__` doesn't take, keeps the standard `__init__`. With `on_error="warn"` a wrong argument is then reported for the call and again for the assignment. Documented in the README.

### 54. A coroutine run by the event loop

A coroutine handed to `asyncio.run`, or a task, has no caller on the stack when it runs. Its warning is attributed to a line in `asyncio`. Python then shows one warning per distinct message for that line, not per call site. Awaited from the user's own coroutine it is attributed correctly, which is what the test covers.

### 55. A warning is not free when ignored

About 3 µs per wrong call: the message is rendered before Python's filter is asked. Asking first would mean reading the filter list by hand. It matters only where a hot path fails constantly.

### 56. `on_error` and the off switch

With `ENFORCED_TYPECHECK_OFF=1` nothing is wrapped and `on_error="log"` is accepted silently. The other options behave the same way there.

### 57. One import against the order

`_route` imports `wrap_callable` inside the function: wrapping is built on routing, and routing makes a wrapper for a class it hasn't met. It runs once per class.

### 58. Long files and layout

`_deep.py` was left alone, as agreed; it has one job. `_checker.py` is one class. A handful of continuation lines sit a column to the right after a function lost its underscore.

---

## What I would do next

- **Regenerate `benchmarks_report.md`.** It is from before all of this, and every error figure in it is about twice what is measured now.
- **Run the suite on a free-threaded build** before claiming it. The call counters of the tiers are not locked. Two threads may compile the same wrapper twice, which is harmless, but it has not been run.

---

## Tests and tools

- **Unit tests: 1,450** (1,415 at the ninth review). New files or groups: `tests/test_on_error.py` (41 tests), both dataclass tiers, errors freed without the collector, problems made on first read, the environment read each way it can change, the standard-library-only import. The formatter tests were rewritten for the built-in styles.
- **Simulation: 1,267 checks** (1,231). Two sections are new: the ninth review's additions, and `on_error`.
- **Fuzz:** one new property, for `on_error`. The use `self` is left out of it: that use hands over a wrong value on purpose and takes a refusal for its answer.
- **Benchmark:** three cases for `on_error`.

---

## How this review was done, and its limits

1. Each change was measured before and after with the benchmark where it has the case, and with scripts of mine where it doesn't (the dataclass tiers, the parts of rendering).
2. The fuzz ran four times in this round, each after a change that rewrote a checking path: the errors, the split, and `on_error`; not for printing or termcolor, whose output the unit tests compare byte for byte.
3. For this review I read the new `on_error` code again and tried it against cases the tests did not have. Three things came out and are fixed: a warning turned into an exception was chained to the error it stood for, an unhashable `on_error` reached a dictionary lookup as a bare `TypeError`, and `typecheck(on_error="log")` without a function was not refused until it was applied.

Limits:

- The full benchmark was not run; only calls, classes, errors and the new cases.
- The simulation passes at its own setting (wrappers compiled at once). With `ENFORCED_COMPILE_AFTER=64`, 12 of its checks that count how often a dataclass checks a value fail, as designed.
- The free-threaded build was not tried, and wheel and sdist were not rebuilt after termcolor left `pyproject.toml`.
- I committed nothing. The last two commits are yours.
