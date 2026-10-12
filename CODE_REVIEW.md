# Code review of enforced

Eighth review, 2026-10-13. It is the final one of this round and replaces the seventh: it covers the whole `enforced/` package as it stands, the test tools, and the packaging. Python 3.14.4, project venv.

The round started from the sixth review, with eleven Low findings open. Since then: the eight you named first (2, 15, 17, 21, 28, 33, 34, 35), the review of `protect` / `Ok` / `Err`, five more (21, 23, 31, 36, 40), and your last decisions (properties under `enforce`, `formatter` no longer exported, `Ok` and `Err` as standard dataclasses, the MIT licence).

## Summary

**No finding of High or Medium severity is open, and no known issue is left**: the file of expected failures holds none.

- **Four entries are open**: two Low findings (one of them new in this review), one that is by design, and one that is inherent. None blocks a release.
- **`Self` is the class of the instance a method is called on.** That was the larger known issue.
- **A standard dataclass below a checked one may retype a field.** That was the other.
- **Properties of an `@enforce` class are checked**: the setter's argument, and with `check_return` what the getter returns.
- **Nothing global keeps a class alive that was made at run time.** Fixing that found a leak older than this round and without a bound.
- **A local name defined after the decorator is found**, without keeping anything alive, through `sys.monitoring`.
- **The package has a licence (MIT)**, and the name `enforced` was free on PyPI on 2026-10-12.
- **Valid calls cost what they did.** A method that checks `Self` costs 10 to 20 ns more; the first call of any function about 5% more.

| Check | Result |
|---|---|
| `python -m pytest -q tests` | 1,381 passed, 3 skipped without mypy; 1,384 with mypy. No expected failure (1,249 passed and 2 expected failures at the start of the round) |
| `python tests/simulation.py -q` | 1,208 checks pass, no known issue (1,101 and 2) |
| `python tests/fuzz.py`, baseline = the package before the round | 50,000 values (seed 1) and 300,000 (seed 7): every outcome identical |
| `python tests/fuzz.py --properties` | 50,000 (seed 1) and 200,000 (seed 7) over 27 ways of using an annotation: no property broken |
| mypy and pyright on the package itself | no error |
| mypy and pyright on the sample file | errors exactly on the 21 lines meant to have one |
| Wheel | builds; 18 files, `License-Expression: MIT`, `LICENSE` inside |

`tests/benchmark.py` was not run in full, as asked throughout. The 20 cases added in this round were run once, to see that they execute. `benchmarks_report.md` predates the round.

Open:

| # | Severity | Finding |
|---|---|---|
| 2 | inherent | Static typing: the short form of a `TypeModel`, a call that relies on conversion. Also: the copyright line of `LICENSE` names the git user |
| 27 | by design | What `enforce` leaves unchecked: attribute assignment, operators and comparisons, subclasses that aren't decorated, methods added later |
| 34 | Low | `typecheck_function` remembers 512 callables that are not functions; a function goes with the garbage collector, not at once |
| 42 | Low | **New:** the first call of a function costs about 5% more than before the round |

Closed since the sixth review: 15 (a bare callable stays a check: your decision), 17, 21, 23, 28, 31, 33, 35, 36, 37, 38, 40, and 41, which this review found and which was fixed the same day: a problem raised by a property's getter or setter keeps its `origin` when pickled (the accessor is named along with the property; two tests). Finding 39 was removed at your request.

---

## What was done, by subject

### `Self` (28)

```python
@enforce(check_return = True)
class Base:
    def clone(self) -> Self:
        return Base()

class Child(Base): ...

Child().clone()      # passed. Now: expected type: 'Child', got type 'Base'
```

A check is compiled for one class and sees one value at a time. Two mechanisms get the class of the call into it:

- **`Self` alone** (`other: Self`, `-> Self`): the test is written against the class of the first argument. One wrapper serves every class.
- **`Self` inside an annotation, or a class method** (`Self | None`, `list[Self]`, `type[Self]`): a call on another class goes to a wrapper made for that class when the first such call arrives. The class holds its wrapper, so the two go together.

It covers methods, class methods, `__new__`, properties, a method with its own `@typecheck`, `typecheck_function`, async and generator methods, `deep`, strict mode, and a dataclass field in a subclass that isn't decorated. A method that doesn't use `Self` in what is checked gets the same generated code as before, character for character.

**Strict mode changed with it**: `Self` is exactly the class of the instance. Before, an instance of any subclass passed, because the class of the instance was not known.

### Properties under `enforce` (from 27)

```python
@enforce(check_return = True)
class Account:
    @property
    def balance(self) -> float: ...
    @balance.setter
    def balance(self, value: float) -> None: ...

account.balance = "a lot"     # For parameter value of <Method Account.balance>: expected type: 'float'
```

- **The setter is wrapped when it has annotations.** Assigning costs 89 ns where the plain property costs 36.
- **The getter is wrapped only with `check_return`.** Without it there is nothing to check, and reading stays at 16 ns (80 ns when checked).
- **A `functools.cached_property` likewise**, with `check_return`. The deleter never.
- **The property stays what it was**: same class, same docstring, abstract if it was. `@skip_typecheck` above or below `@property` leaves an accessor out, and one with its own `@typecheck` keeps its options.

The rest of finding 27 is unchanged, by design.

### Lifetime: what no longer keeps things alive (34, 36)

- **A function given to `typecheck_function` or `typecheck_from_dict`** keeps its wrapper on itself and goes when it is dropped.
- **A class made at run time** was held from four places. The oldest had no bound at all: the signature cache was keyed weakly by the function, but a signature names classes, and a class can hold the function, so the entry never went. A function's signature is on the function now.
- **The annotation cache** holds annotations weakly, and a plain class is not put in it.

Three tests make 40 classes in a loop, use them and drop them; none survives. Left of 34: an object with `__call__`, a partial and a builtin are still remembered in a cache of 512, and a function is freed by the garbage collector, not at the moment its last name goes. My advice stands: close it, unless many short-lived callable objects go through `typecheck_function`.

### A local name that comes after the decorator (31)

The name is read at the moment the enclosing function returns. Python reports that return through `sys.monitoring`, for that one function, and the list of what is waited for travels in the function's own frame.

What it costs and where it stops:

- **It takes a `sys.monitoring` tool id** (4, or 3), the first time such a name is met. Where both are taken, the old rule holds: found only while the function runs.
- **A function left by an exception is not heard of.** Python reports that only for all functions at once.
- **The enclosing function has one more local name**, `__enforced_pending__`, visible to `locals()`.
- **Decorating such a function takes 13 µs** where it took 7.6. Nothing else pays.

### Dataclasses (23, 35)

- **A standard dataclass below a checked one** owns the fields it declares: they are unchecked, like every field of a standard dataclass. The fields it leaves alone stay checked. Asked only after a value has failed, so a valid assignment costs what it did.
- **`no_type_check` on a base class** speaks for that class only, as the `typing` documentation has it. A decorated dataclass below it checks its own fields.

### Checks in `Annotated` (15)

`Check(fn)` marks a callable as a check and is exported. A bare callable is one too, which you confirmed. A function that transforms (`str.strip`) still gives a verdict, and the message now says what it returned. The ready-made types use the marker.

### Errors and messages (17, 40)

| | Before | After |
|---|---|---|
| Print a coloured message | 6.86 µs | 3.08 µs |
| Raise and catch: an unknown keyword | 2.68 µs | 1.23 µs |
| Raise and catch: too many arguments | 1.72 µs | 0.75 µs |
| Raise and catch: a missing argument | 8.53 µs | 5.01 µs |

Binding errors are worded directly, in the sentences `Signature.bind` uses; a test compares 300 random calls per signature shape with it. termcolor is asked once per style, not once per word.

### Files (21)

A `Mock()` is a file. `type[TextIO]` takes a file class that is no `io` class, and a class that answers names through `__getattr__` (the `NamedTemporaryFile` wrapper, a proxy). That last rule is lenient on purpose: nothing of such a class's instances shows on the class.

### The generator flag (33)

Still carried, since it is what makes `inspect` and pytest right, but tried once at import. On a Python that acted on it, checked generator functions keep working and only `inspect` sees an ordinary function.

### `protect`, `Ok`, `Err`, and the exports (37, 38)

- **`protect` refuses what can't be awaited.** `protect(fetch)`, without the call, came back as `Err(TypeError)`. It raises a `TypeCheckerError` now.
- **`Ok` and `Err` are standard frozen dataclasses**, as you asked: 76 ns to make, where the checked ones took 130. Nothing in them is checked any more, so `Err("text")` is accepted at run time; mypy and pyright still report it.
- **`Ok`, `Err`, `protect` and `Check` are in `__all__`.** `formatter` is not imported into the package any more: `from enforced.formatting_tool import formatter`.

### Publishing (2)

- **`LICENSE` is MIT**, and `pyproject.toml` says so (`license = "MIT"`). A wheel built from it carries both.
- **The copyright line reads "Copyright (c) 2026 Syno"**, your git user name. If the licence should name you differently, that is the one line to change.
- **`enforced` was not registered on PyPI** on 2026-10-12. `enforce`, one letter shorter, is another project in the same field.

---

## Open

### 2. What is inherent in static typing

A model written `class Slug(TypeModel[str])` is not a `str` for a checker (the long form is), and a call that relies on conversion is reported by one. Both are in the README. Neither can be fixed in code.

### 27. What `enforce` leaves unchecked, by design

Attribute assignment (`self.x = "a"` under a class-level `x: int`), operators and comparisons, subclasses that aren't decorated, methods added after decoration, and `@dataclasses.dataclass` written above `@enforce`.

### 34. What is left of it

See "Lifetime" above.

### 42. The first call costs about 5% more (new)

Decorating a function and calling it once took 30.0 µs before the round and takes 31.5 µs. The first call now also finds out whether the annotations use `Self`, and stores the signature on the function. Decorating alone went from 2.02 to 2.09 µs. Every later call is unchanged. A program that decorates thousands of functions and calls each once would see it; the tiered compilation on the roadmap is the answer to that whole cost.

---

## Behaviour that changed in this round

Listed together, since code may rely on any of it.

- **Newly rejected**
  - A base-class instance for `Self` in a call on a subclass.
  - In strict mode, a subclass instance for `Self`.
  - A wrong value assigned to a property of an `@enforce` class, and with `check_return` a wrong value from its getter.
  - `protect` given something that can't be awaited.
- **Newly accepted**
  - A `Mock()`, or any object with a file's methods but no `with` support, for a file annotation.
  - For `type[TextIO]`: a file class that is no `io` class, a class with `__getattr__`, and `io.StringIO` in strict mode.
  - A field that a standard dataclass retypes below a checked one.
  - A local name defined after the decorator, once its function has returned.
  - `Err` given anything (it checks nothing now).
- **Newly checked**
  - The fields a `@dataclass` declares below a class marked `no_type_check`.
- **Messages**
  - A check that returned something falsy other than `False` or `None` adds `, which returned ...`.
  - A `Self` message names the class of the call.
- **Attributes written on your objects**
  - On a function: `__enforced_signature__`, and after `typecheck_function` / `typecheck_from_dict` also `__enforced_calls__` / `__enforced_records__`.
  - On a subclass used with a `Self` method: `__enforced_self__`.
  - On a dataclass decorated below a marked class: `__no_type_check__ = False`.
- **Process-wide**
  - A `sys.monitoring` tool id named "enforced", from the first late local name on.
- **Names**
  - `enforced.formatting_tool.formatter` (it was `enforced.utils.formatter`, and for a while `enforced.formatter`).
  - `Check`, `Ok`, `Err`, `protect` are exported.

---

## Performance

Old against new, the same script for both, median of 7 to 9 rounds, messages plain. "Before" is the package as it was before the round.

| Case | Before | After |
|---|---|---|
| Call, 2 parameters | 80.9 ns | 80.5 ns |
| Call that leaves a default out | 120.3 ns | 119.7 ns |
| Enforced method, no `Self` | 77.3 ns | 77.2 ns |
| Dataclass construction | 277.4 ns | 278 to 287 ns |
| Dataclass assignment | 76.1 ns | 77.9 ns |
| `typecheck_function`, repeated | 240.5 ns | 223.9 ns |
| `typecheck_from_dict`, a name | 1,206 ns | 1,215 ns |
| `typecheck_from_dict`, a function | 1,023 ns | 1,086 ns |
| Wrong argument, raise and catch | 1,592 ns | 1,603 ns |
| Decorate a function | 2,020 ns | 2,095 ns |
| Decorate and call once | 30.0 µs | 31.5 µs |
| `-> Self` without `check_return` | 75.3 ns | 72.8 ns |
| `-> Self`, on the defining class | 74.2 ns | 86.7 ns |
| `-> Self`, on a subclass | 76.1 ns | 95.6 ns |
| Class method `-> Self`, on a subclass | 107.4 ns | 217.6 ns |
| Property of an enforced class: assign | 36 ns (unchecked) | 89 ns |
| Property: read, without / with `check_return` | 16 ns (unchecked) | 16 / 80 ns |

- **Nothing that doesn't use `Self` or a property moved** beyond the noise between runs (the dataclass construction figure varied by 3% between two runs of the same code).
- **A class method that returns `Self`, called on a subclass, doubled.** It goes through a wrapper of its own, found by the id of the class. Before the round it tested against the wrong class.
- Memory per decorated function that is never called: 2,738 bytes before, 2,818 now.

---

## Tests and tools

- **Unit tests: 132 more than at the start** (1,249 to 1,381), in `test_utils.py` (new), `test_enforced.py` (`Self`, lifetimes, properties), `test_future_annotations.py` (late names), `test_typechecker_errors.py` (binding errors), and smaller groups for each finding. `test_known_issues.py` holds no issue; it keeps the helper and its own test for the next one.
- **Simulation: 107 more checks** (1,101 to 1,208): phase 7 "review 6", "review 7" and "review 8", and a new phase 9 for `protect`.
- **Benchmark: 20 more cases**, among them a section "enforced only" that runs against enforced alone (`typecheck_function`, `Self` on a class and a subclass, `Ok`, `protect`), for use with `--baseline`.
- **Fuzz: 3 more ways to use an annotation** (27): `Check(fn)` against the short form, a method with `Self` on a subclass, a property against a plain function. The tool also learned that the baseline's longer import name moves the place where a long annotation is cut in a message.

---

## What held up

- **Differential fuzz, 350,000 values**: identical to the package before the round. What changed lies in uses the baseline doesn't have, and those are held by the property checks.
- **Properties, 250,000 values**: every error a `TypeCheckerError` or one Python itself raises; no second call, returned value, subclass, marked check, `Self` method or property disagreed with the plain form; no looser setting rejected what a stricter one accepted.
- **Binding errors**: 3,200 random calls over eight signature shapes gave the same outcome and the same message as the old package.
- **Probes of the last changes**: an abstract property stays abstract; enforcing a class twice wraps a setter once; an `Enum` property, a `NamedTuple` with a property, a subclass of `property`, a setter with an unresolvable annotation, and a dataclass's property (left alone: `enforced.dataclass` checks fields).
- **Both type checkers**, on the package and on the sample file.
- **A wheel** built from the tree carries the licence and the new module.

---

## How this review was done, and its limits

1. Every fix was built against a copy of the package taken before the round, with the unit tests and the simulation run after each step and the hot paths timed old against new.
2. For lifetimes I traced referrers from a leaked class up to a module-level root. That is how the signature cache was found; the per-class wrappers alone would not have shown it.
3. mypy and pyright ran from a scratch environment, so the project venv is as it was.

Things that went wrong along the way, all caught before they stayed:

- A first version of the `Self` routing made decorating any function 50% slower. It is built on first use now.
- A script inserted a simulation phase 22 times. Removed and inserted once; the check count confirms it.
- Two fuzz checks and three tests I wrote were wrong themselves (a check that depended on conversion, a test that expected `deep` behaviour without `deep`, an abstract property in a probe). Each showed up as a false alarm and was corrected.
- My first plan for finding 31 was to keep the frame. A check showed that a returned frame still holds its caller, as the sixth review had said.

Limits:

- **One reading of yours I had to guess**: "for 15 apply type check for properties only". Finding 15 is about `Annotated`, so I took it for finding 27 and checked properties under `enforce`. If you meant something else, this part is easy to take out: one function, `_enforce_property`.
- `tests/benchmark.py` was not run in full.
- The free-threaded build was not tried. The generator flag and `sys.monitoring` were tried on CPython 3.14.4 only.
- The sdist was not rebuilt; only a wheel was.
- Nothing was uploaded, and nothing is committed.
