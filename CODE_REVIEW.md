# Code review of enforced

Ninth review, 2026-10-13. It covers the five changes of this round and what they did to the rest of the package. The eighth review, which this replaces, described the state before them; its open findings are carried over below.

The round: `typecheck_from_dict` became `typecheck_record`, the licence names its owner, errors are made in one pass, a checked dataclass has an `__init__` that checks each field once, and wrappers are compiled in tiers.

## Summary

**No finding of High or Medium severity is open, and no known issue.**

- **Errors cost about half of what they did.** pydantic was 4.4 times faster on the error path and is 2.4 times faster now.
- **Constructing a checked dataclass is 19 to 38% faster**, and each argument is checked once.
- **A program that decorates many functions and calls each a few times starts in under half the time**: a wrapper is compiled at its 64th call, not its first.
- **Calls that were fast before cost the same.** The compiled wrapper is unchanged.
- **Three behaviours changed**, each small: see "Behaviour that changed".
- **Four Low findings are new** (43 to 46), all consequences of this round.
- **The README was not touched, as you asked, and is now behind**: it still says `typecheck_from_dict` and lists two of these changes on the roadmap.

| Check | Result |
|---|---|
| `python -m pytest -q tests` | 1,415 passed, 3 skipped without mypy; 1,418 with mypy (1,391 at the start of the round) |
| The same with `ENFORCED_COMPILE_AFTER=64` (everything on the general path) | 1,404 passed, 14 skipped: the 3 for mypy and 11 that look at a compiled wrapper |
| `python tests/simulation.py -q` | 1,231 checks pass, no known issue (1,212) |
| `python tests/fuzz.py --ref HEAD`, run once, at the end | 100,000 values against the last commit: every outcome and every message identical |
| `python tests/fuzz.py --properties`, run once | 100,000 values over 27 ways of using an annotation: no property broken |
| mypy and pyright on the package | no error |
| `python tests/benchmark.py --skip-cold --cases "Errors"` | before and after, tables below |

The benchmark was run for the error cases only, as asked; it already had the option (`--cases` takes a pattern), so no flag was added.

Open findings:

| # | Severity | Finding |
|---|---|---|
| 2 | inherent | Static typing: the short form of a `TypeModel`, a call that relies on conversion. The licence part is closed |
| 27 | by design | What `enforce` leaves unchecked: attribute assignment, operators and comparisons, subclasses that aren't decorated, methods added later |
| 34 | Low | `typecheck_function` remembers 512 callables that are not functions; a function goes with the garbage collector, not at once |
| 43 | Low | **New:** the README describes the package as it was before this round |
| 44 | Low | **New:** a default of a checked dataclass is validated once, no longer at every construction |
| 45 | Low | **New:** a function's first 63 calls are slower than they were |
| 46 | Low | **New:** a failing `Annotated` check or `TypeModel` still runs twice on the compiled path |

Finding 42 of the eighth review (the first call cost 5% more) is closed by the tiers: the first call takes 25 µs where it took 38.

---

## Added after this review

- **The short `TypeModel` form is a `str` for type checkers** (the option under "What I would do next", which you asked for). For mypy and pyright `TypeModel[str]` now stands for `str`, so `class Slug(TypeModel[str])` has `str`'s methods and passes where a `str` is expected. `Email` and `Port` are written in the short form. The long form, `class Slug(TypeModel[str], str)`, still runs but both checkers report a duplicate base class. That closes the typing half of finding 2 except for what is inherent: a call that relies on conversion is still reported by a checker.
- **The README is up to date** (finding 43 is closed): `typecheck_record`, the storing `__init__`, tiered compilation and `ENFORCED_COMPILE_AFTER`, the new timings, the short `TypeModel` form, and a roadmap without the two items that are done.

After these: 1,415 unit tests pass (1,418 with mypy), 1,231 simulation checks, mypy and pyright clean on the package, and both agree with the sample file on its 21 marked lines. The fuzz was not run again: the alias exists only for type checkers, and the package's two models lost a base that was already in their line.

## Added after this review (2): faster errors, a dataclass in two tiers

Both were on the roadmap; you asked for them.

**Errors.** pydantic was 2.4 times faster on the error path and is 1.3 times faster now (`python tests/benchmark.py --skip-cold --cases "Errors"`, µs to raise and catch):

| Case | Before | Now | pydantic |
|---|---|---|---|
| 1 wrong argument of 2 | 1.05 | 0.57 | 0.47 |
| 3 wrong arguments of 12 | 2.15 | 1.09 | 0.70 |
| Missing argument | 0.99 | 0.55 | 0.53 |
| Unknown keyword argument | 0.86 | 0.71 | 0.58 |
| Wrong keyword-only argument | 1.23 | 0.81 | 0.59 |
| Wrong return value | 1.23 | 0.46 | 0.54 (strict) |
| Dataclass field, wrong type | 1.38 | 0.98 | 0.78 |
| Dataclass assignment, wrong type | 1.54 | 0.42 | 0.47 |
| Value check fails | 1.80 | 0.94 | 0.49 |
| Invalid email | 2.35 | 1.14 | 0.68 |

- **The largest part was a reference cycle, not work.** An error's traceback holds the frame it was raised in. My first version of this change held the error in a local of that frame, which made wrong calls slower (1.08 to 1.25 µs): every error was left to the garbage collector. Raising what a helper returns removed 350 ns. The same kind of cycle existed before this round in every rejected value (`Annotated` check, `TypeModel`, deep items): the problem's renderer held the problem. It is gone too.
- **`Problem` objects are made when `e.problems` is first read.** The check notes which arguments failed; code that only catches the error never pays for the objects. Which arguments failed is settled at the call.
- **A `TypeModel`'s `validate` runs once per wrong call** (it was three times, then two): the compiled wrapper tells the general path which conversion it already tried. That closes the `TypeModel` half of finding 46.
- **A wrong return value and a wrong dataclass assignment** take the same short route as a wrong argument.

**Dataclass tiers.** Defining a checked dataclass compiles nothing now. The `__init__` that stores checked arguments is made at the 64th construction, and the generated assignment check at the 64th assignment; before that the standard `__init__` runs behind the general check and fields are tested one at a time.

| | Before | Now |
|---|---|---|
| Defining a class with 6 fields | 0.33 ms | 0.23 ms |
| Its first construction | 0.25 ms | 0.10 ms |
| A construction before the 64th, 3 fields / 6 fields | 0.33 / 0.41 µs | 1.1 / 1.8 µs |
| An assignment before the 64th | 0.06 µs | 0.2 µs |
| Construction and assignment once compiled | 0.43 µs, 0.06 µs | unchanged |

The 0.33 ms for defining a class was a regression of the ninth review's own storing `__init__` (0.22 ms at the last commit), which was compiled at definition. It is undone.

Findings:

| # | Severity | Finding |
|---|---|---|
| 45 | Low | **Wider:** a dataclass's first 63 constructions cost about 0.8 µs more each and check each argument twice (once by the `__init__` check, once on assignment). A `validate` or `Annotated` check with side effects sees two runs there |
| 46 | Low | **Half closed:** `validate` runs once. A failing `Annotated` check still runs twice on the general path and three times from a compiled wrapper |
| 47 | Low | **New:** a missing argument next to a misplaced one still leaves about 27 objects to the garbage collector per error (`_realign_positional`: nested functions that call themselves). It is the rarest error path and the slowest already |
| 48 | Low | **New:** `e.problems` is a property now. `vars(e)` no longer has a `problems` key, and the `Problem` objects of two reads are the same list but did not exist before the first |
| 49 | fixed here | A race I introduced and removed: the checker's layout was published before it was complete, and a second thread could read a missing attribute. The simulation's thread check caught it in 1 run of 6; the layout's first field is now assigned last. No unit test reproduces it on demand |

Checks after this addition:

| Check | Result |
|---|---|
| `python -m pytest -q tests` | 1,421 passed, 3 skipped (mypy not in the project venv) |
| The same with `ENFORCED_COMPILE_AFTER=64` and `=7` | 1,397 passed, 27 skipped: the 3 for mypy and 24 that look at a compiled wrapper or count checks |
| `python tests/simulation.py -q` | 1,248 checks pass, 7 runs in a row |
| `python tests/fuzz.py --ref HEAD --cases 100000`, once | every outcome and message identical to the last commit |
| `python tests/fuzz.py --properties --cases 100000`, once | no property broken |
| mypy and pyright on the package | no error |
| Valid calls (`benchmark.py --quick`, calls and classes only) | unchanged: 1 parameter 0.063 µs, construct 0.43 µs, assign 0.060 µs |

New tests: both dataclass tiers over 3 classes, 10 fields, 19 values and 5 option sets; the construction and assignment at which each part is compiled; 15 kinds of wrong call leaving nothing to the collector; problems made on first read. 17 simulation checks in phase 7 "review 10".

Limits: the simulation passes at its own setting only (with `ENFORCED_COMPILE_AFTER=64`, 12 of its checks that count how often a dataclass checks a value fail, as designed). The full benchmark and the free-threaded build were not run. `benchmarks_report.md` is from before. Nothing is committed.

---

## The five changes

### 1. `typecheck_record`

`typecheck_from_dict` is `typecheck_record`, everywhere in the code: the function, its export, its internal caches and lock, the tests, the simulation, the benchmark case and the fuzz. No alias is left under the old name. The fuzz can still call the old name in a baseline from before the rename.

### 2. The licence

`LICENSE` reads "Copyright (c) 2026 Christos Synodinos", the name you gave. That closes the licence part of finding 2.

You wrote that only the licence was meant. Before that message arrived I had tried the typing half as well, and it turns out not to be inherent after all. I changed nothing for it; the option is under "What I would do next".

### 3. Errors

| Raise and catch, µs | Before | After | pydantic |
|---|---|---|---|
| 1 wrong argument of 2 | 1.62 | 1.04 | 0.48 |
| 3 wrong arguments of 12 | 5.22 | 2.15 | 0.70 |
| A missing argument | 4.74 | 1.00 | 0.53 |
| An unknown keyword | 1.08 | 0.87 | 0.58 |
| A wrong keyword-only argument | 2.38 | 1.24 | 0.63 |
| A wrong return value | 1.28 | 1.21 | not caught |
| A dataclass field of the wrong type | 2.55 | 1.37 | 0.78 |
| A dataclass assignment of the wrong type | 2.04 | 1.57 | 0.47 |
| A value check that fails | 2.08 | 1.83 | 0.48 |
| An invalid email | 3.53 | 2.39 | 0.68 |

With the message built and read as well (plain text): one wrong argument 3.51 → 3.08 µs, three of twelve 9.24 → 6.70, a missing argument 7.42 → 2.96.

What changed:

- **One pass in place of three.** A call that reached the general path was bound and tested, then walked again to convert, then a third time to collect problems; a missing argument went through `Signature.bind_partial` on top. Now one function binds, tests, converts and reports ([api.py](enforced/_typechecker/api.py), `PreparedChecker._scan`).
- **A wrong-type problem is made from what is already known.** The expected type is worked out when the function is prepared, not at each error, and the text is left for when it is read.
- **A missing argument no longer takes the long way**, unless a given positional argument doesn't fit either: there the search for a better placement still runs, and the "(inferred)" hint with it.
- **A model's reason for refusing a value is kept** from the run that refused it. The message used to run `validate` again to get it.
- **The error object is cheaper to make.** It takes its list of problems as it is.

The old three passes are still there, for the two cases the single pass doesn't take: a function with `*args` or `**kwargs`, and `deep` item checks. Those errors cost what they did.

How I know the wording did not move: a test runs 1,500 random calls per option set through the single pass and through the old passes and compares outcome, order, and text; and the differential fuzz compared 100,000 values with the last commit, message for message.

### 4. A dataclass `__init__` that checks each field once

```python
@dataclass
class Order:
    qty: int
    price: float = 0
    tags: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.total = self.qty * self.price
```

The standard `__init__` assigns its arguments, and every assignment went through the generated `__setattr__`, so an argument the wrapper had just checked was checked again. A checked dataclass now gets an `__init__` of its own ([_dataclass_override.py](enforced/_dataclass_override.py), `_storing_init`): the same parameters, the same steps in the same order, but an argument is stored past the assignment check.

| Construct, ns | Before | After |
|---|---|---|
| `Point(x=1, y=2.0)`, 3 fields | 554 | 448 |
| The same, positional | 424 | 328 |
| 6 fields | 655 | 408 |
| A `deep` list field | 560 | 428 |
| Assignment (unchanged path) | 78 | 75 |

- **What nobody has checked still goes through the check**: the result of a `default_factory`, and whatever `__post_init__` assigns. For `Order(2, 3)` above, exactly `tags` and `total` reach it.
- **An instance of a subclass is handed to the standard `__init__`.** A subclass may define `__setattr__`, and an assignment has to reach it. A test holds that.
- **The standard `__init__` is kept** where a `__setattr__` written by hand sits anywhere in the class's line, for a slots class with a default that `__init__` doesn't take, for a frozen class (it never checked twice), and for anything the generator doesn't recognise.
- **Its signature is the standard one's.** A test compares it, and the instances it builds, with `dataclasses.dataclass` on the same class, `InitVar`, `kw_only` and `init=False` fields included.

### 5. Tiered compilation

A checked function starts on the general path and has its wrapper compiled at its 64th call.

| | Before | After |
|---|---|---|
| Decorate a function and call it once | 38.2 µs | 25.4 µs |
| 400 functions of varied shapes, 3 calls each | 33 ms | 14 ms |
| A hot call, 2 parameters | 80 ns | 80 ns |

Why 64: compiling costs 15 µs where a function of the same shape was compiled before, and 200 to 900 µs where none was; a call on the general path costs 0.2 to 0.5 µs more than a compiled one. 64 calls is about where the cheaper compilation is paid off. A function that runs hot reaches it at once and loses some 15 µs in total.

- **`ENFORCED_COMPILE_AFTER=n`** sets the number; `1` compiles at the first call, as before. It is a member of `EnvVar` and is read once, at import.
- **Both tiers behave the same.** The whole unit suite passes on either: 1,415 tests with wrappers compiled at once, and 1,404 with everything kept on the general path (the 11 others look at the compiled wrapper itself and are skipped there).
- **The tests, the simulation and the fuzz compile at the first call**, so that the second call of a test still exercises the compiled wrapper. Without that, most of the suite would have stopped testing it.

The assignment check of a dataclass is not tiered: it is still generated at the first assignment.

---

## Behaviour that changed

- **A dataclass default is validated once** (finding 44). `label: str = "x"` was assigned through the check at every construction. It is now checked when the class is first constructed, like the default of a function. A default that was valid then stays valid; the difference shows only for a check with side effects, which ran per construction and runs once.
- **The first calls of a function take the general path** (finding 45). Results and errors are the same. `fn.__enforced_source__` appears at the 64th call, not the second.
- **A model's `validate` runs once less** for a refused value. A `validate` that counts its calls sees the difference.
- **`typecheck_from_dict` no longer exists.** Nothing answers under the old name.
- **`Problem` objects are the same data**, but a wrong-type problem made by the single pass builds its text from the annotation when read. `str(problem)` is unchanged.

---

## Open

### 2. What is left: static typing

A model written `class Slug(TypeModel[str])` is not a `str` for a type checker, and a call that relies on conversion (`connect("a@b.co", 8080)` for `Email` and `Port` parameters) is reported by one. The second is inherent: caller and function body see one parameter type. The first is not; see "What I would do next".

### 27, 34

Unchanged from the eighth review.

### 43. The README is behind (new)

You asked for no README update in this round. As it stands it names `typecheck_from_dict` in a section heading, the table of functions and several examples, keeps "a generated dataclass `__init__`" and "tiered compilation" on the roadmap, says nothing of `ENFORCED_COMPILE_AFTER`, and quotes error and construction timings from before. A reader who copies its `typecheck_from_dict` example gets an `ImportError`.

### 44. A dataclass default is validated once (new)

See "Behaviour that changed". It brings dataclasses in line with functions and is where most of the construction time went, but it is a change. It also means a mutable default that is replaced on the class after the first construction (`Order.price = "free"`) is not noticed for the fields the standard library reads from the class; that was so for function defaults already.

### 45. The first 63 calls are slower (new)

A call on the general path takes 250 to 770 ns where the compiled wrapper takes 75 to 250 (1 to 12 parameters). For a function called millions of times that is noise. A function called 30 times in a tight loop and never again pays about 6 µs more than before, in exchange for not paying 15 to 900 µs for a wrapper. A benchmark that calls a function ten times and takes the mean would show enforced slower than it is once warm; `ENFORCED_COMPILE_AFTER=1` gives the old behaviour.

### 46. A failing check still runs twice on the compiled path (new)

The compiled wrapper tries to convert a failing value before it gives up, and the general path, which doesn't know that, tries again. For a `TypeModel` that is two runs of `validate` per refused value (it was three). An `Annotated` check that fails likewise runs once to fail and once for its reason. Removing the second run needs the wrapper to hand over what it found, which touches the compiled code; I left it.

---

## What I would do next

- **Update the README** (finding 43). It is the only thing here that would mislead a user.
- **Make the short `TypeModel` form a `str` for type checkers.** I tested this with mypy and pyright: declaring `TypeModel` as a type alias for checkers only makes `class Slug(TypeModel[str])` a `str` in both, with its own methods and properties intact. The price: the long form, `class Slug(TypeModel[str], str)`, then gets a "duplicate base class" error from both checkers (it still runs), so `Email`, `Port` and the README would switch to the short form. About 15 lines plus the sample file. Not done, since you scoped item 2 to the licence.
- **Tier the dataclass assignment check**, if construction of classes that are built once matters: its code is generated at the first assignment.

---

## Tests and tools

- **Unit tests: 24 more** (1,391 to 1,415): the single pass against the old three (four option sets, 1,500 calls each), problem order, missing arguments, the kept reason, the storing `__init__` (six tests), tiers (three), and the renames.
- **`tests/conftest.py`** compiles wrappers at the first call and offers a fixture for the tests that look at a compiled wrapper.
- **Simulation: 19 more checks** (1,212 to 1,231), in phase 7 "review 9". Two older checks changed: one counted the environment variables, one watched for a re-entrancy hazard that the storing `__init__` removes.
- **Fuzz:** calls the record function under either name, and compiles at the first call for both versions it compares.
- **Benchmark:** only the case name changed. `benchmarks_report.md` is from before this round.

---

## How this review was done, and its limits

1. Each change was measured against the last commit, from a copy of it outside the project folder. My first construction timing compared the working tree with itself, because the script ran from the project root and imported from there; the figures above are from the corrected run.
2. For the errors, only the benchmark and the unit tests were used, as asked. The profile that showed where the time went is a script of mine, not the benchmark.
3. The fuzz ran once, after everything else: 100,000 values against the last commit and 100,000 property checks. I judged it necessary because items 3, 4 and 5 all rewrite paths whose output has to stay word for word the same, and it is the only tool that compares that at volume.
4. mypy and pyright ran from a scratch environment.

Limits:

- `tests/benchmark.py` was run for the error cases only. The construction and tier figures are from scripts of mine.
- The simulation passes at its own setting (wrappers compiled at once). With `ENFORCED_COMPILE_AFTER=64` three of its checks, which look for a compiled wrapper, fail; the unit suite is the one that was made to run on both tiers.
- The free-threaded build was not tried. The call counter of a wrapper is not locked: two threads may compile the same wrapper twice, which is harmless (both arrive at the same code).
- Wheel and sdist were not rebuilt.
- Nothing is committed.
