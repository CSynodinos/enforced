# Code review of pyvalidate

Sixth review, 2026-10-12. It covers the whole `pyvalidate/` package as it stands after this round, plus `pyproject.toml`, `MANIFEST.in`, `run_tests.sh` and the test tools. Python 3.14.4, project venv.

The fifth review ended with two Medium findings and 23 Low ones open. This round was asked to fix all of them, and to add two functions: `typecheck_function` and `enforce_class`. This review records what was fixed, what could not be and why, what the checks and new probes found afterwards, and what is open now.

## Summary

**No finding of High or Medium severity is open.**

- **Both Medium findings are fixed.** A checked generator function is a generator function for `inspect` again, and still checks its arguments at the call (1). `run_tests.sh` fails when a test fails (3).
- **Of the 23 Low findings, 14 are fixed in full**: 11, 12, 13, 14, 16, 18, 19, 20, 22, 25, 26, 29, 30 and 32.
- **Seven are fixed in part**, and what is left of each is stated below with the reason: 2, 15, 17, 21, 27, 28 and 31.
- **Two cannot be fixed in code and are documented**: 23 and 24. Finding 23 and the rest of 28 now have expected-failure tests.
- **Two functions are new**, the decorators without the `@`: `typecheck_function` checks one call of a function and makes it, `enforce_class` enforces a class that is already defined and returns it.
- **The package's own files are clean under mypy and pyright.** They reported 59 and 27 errors before.
- **Three new Low findings** (33 to 35), each a consequence of a choice made in this round.
- **Before publishing, two decisions are still yours:** the name `pyvalidate` is taken on PyPI, and the repository has no licence file.

| Check | Result |
|---|---|
| `python -m pytest -q tests` | 1,249 passed, 3 skipped without mypy, 2 expected failures; 1,252 passed with mypy (1,061 at the start of the round) |
| The tests against the package as it was | about 200 fail: the 78 of `test_functional.py` need the new functions, some 120 others fail (counted before the last change to the two functions) |
| `python tests/simulation.py -q` | 1,101 checks pass (996), 2 known issues listed |
| `python tests/fuzz.py`, baseline = the package before the round | 2,300,000 values compared: every difference is a reworded message or one of two fixes. Run before the last two changes (see "Limits") |
| `python tests/fuzz.py --properties` | 360,000 values over 24 ways of using an annotation, no property broken |
| mypy and pyright on the package itself | no error (59 and 27 before) |
| mypy and pyright on a file that uses the package | every class and function keeps its type; errors exactly on the 17 lines meant to have one |
| Wheel and sdist | both build and install into a fresh environment with `termcolor` alone; the sdist's own tests pass |
| Valid calls, old against new, interleaved `timeit` | unchanged (within ±2%) |

`tests/benchmark.py` was not run for this review. The first performance table at the end is from the first review.

Open findings:

| # | Severity | Finding |
|---|---|---|
| 2 | Low | Static typing, what is inherent: the short form of a `TypeModel`, a call that relies on conversion. Before publishing: the PyPI name, a licence |
| 15 | Low | Every callable in `Annotated` metadata is a check, also one meant to transform |
| 17 | Low | A coloured message still costs one termcolor call per word |
| 21 | Low | File-like objects: a `Mock()` is no file, and `type[TextIO]` knows the `io` classes only |
| 23 | Low | A standard-library dataclass below a checked one is held to the base's field types (expected-failure test) |
| 27 | Low | What `enforced` leaves unchecked, by design |
| 28 | Low | `Self` is the class that defines the method, not the class of the instance (expected-failure test) |
| 31 | Low | A local name that comes after the decorator is found only while its function runs |
| 33 | Low | **New:** the wrapper of a generator function carries a code flag that Python doesn't read today |
| 34 | Low | **New:** `typecheck_function` keeps the 512 functions called last alive |
| 35 | Low | **New:** a `@dataclass` below a class marked `no_type_check` is unchecked, an `@enforced` class is not |

---

## Fixed in this round

Each fix has tests that fail on the package as it was, simulation checks (phase 7, "review 5") and a README note.

### A checked generator function was not one for `inspect` (finding 1, Medium)

```python
@pytest.fixture
@typecheck
def number(start: int = 5):
    yield start

def test_it(number):
    assert number == 5      # failed: the fixture gave a generator object. It passes now.
```

`inspect.isgeneratorfunction` reads one thing: a flag on the function's code object. The wrapper is an ordinary function that checks the arguments and returns the generator, so it had no flag, and frameworks that ask (pytest for a `yield` fixture) took it for an ordinary function.

The fifth review gave two options: a real generator wrapper, which checks only at the first `next()`, or documenting the limit. There is a third, and it is what was built: the wrapper's code object carries the flag of the function it wraps ([api.py:1369](pyvalidate/_typechecker/api.py#L1369), `_stub_codes`).

- **`inspect` is right**, for generator functions and for async generator functions.
- **Arguments are still checked at the call**, not at the first `next()`: Python does not read the flag when it runs code. A real generator function starts with an instruction that makes the generator; the wrapper has no such instruction and runs at once.
- **Iterating costs nothing extra.** The caller gets the function's own generator, where a delegating wrapper would add a step to every item.
- **No deprecation warning.** Python 3.14 warns when a function is given code of another kind. A wrapper is made with code of its kind and keeps it.

The flag is a statement about the code that the code does not live up to, which is finding 33 below. Proof: seven tests in `test_typechecker.py` (`test_checked_generator_function_...`, `test_pytest_yield_fixture_under_typecheck`, `test_no_warning_when_a_wrapper_gets_its_compiled_code`).

Found on the way: deciding the kind of a function took three `inspect` calls, more than the rest of a decoration together. A plain function is now answered from its code flags ([api.py:1352](pyvalidate/_typechecker/api.py#L1352)), and decorating one became 8% cheaper than before the round.

### `run_tests.sh` reported success when tests failed (finding 3, Medium)

The script wrapped pytest in `if ! ...; then echo ""; fi`, which threw the status away. It now runs `python -m pytest` directly ([run_tests.sh:31](run_tests.sh#L31)): with `set -e` a failing test stops the script with pytest's status, and the pytest used is the active interpreter's.

Proof: `tests/test_scripts.py` runs the script in a scratch folder with a failing test (status 1), a passing one (status 0) and a failing simulation (its own status). `MANIFEST.in` now ships the script in the sdist, since a test needs it.

### Type-checker errors inside the package (finding 2)

pyright reported 27 errors in the package's own files and mypy 59. Both report none now. Most were sentinel values in a union, attributes set on functions, and one variable reused for two types. None was a runtime fault; Pylance shows them to anyone who opens the files.

A test keeps it that way when mypy is installed (`test_mypy_reports_nothing_in_the_package_itself`). One rule came out of it, now in CLAUDE.md: an explanation after `# type: ignore[code]` goes into a second comment, or mypy rejects the line.

### Strings in a record could only name built-in classes (finding 11)

A record string may now also use the usual annotation forms and the standard library's value classes ([_type_container.py:386](pyvalidate/_typechecker/_type_container.py#L386), `_RECORD_NAMES`):

```python
typecheck_from_dict({"object_name": "f", "record": {"x": "Optional[list[int]]", "mode": "Literal['r', 'w']"}, ...})
```

- **Forms:** `Any`, `Optional`, `Union`, `Literal`, `Sequence`, `Mapping`, `Iterable`, `Callable`, `List`, `Dict`, `Tuple`, `deque`, `OrderedDict` and the like, also written with their module (`typing.Optional[int]`).
- **Value classes:** `datetime`, `date`, `time`, `timedelta`, `Decimal`, `Fraction`, `UUID`, `Path`, `PurePath`. Their modules are imported when a record first names one, not before.
- **Still data, never code.** Each name stands for one fixed object. A dotted name is accepted for four modules only, and no attribute of anything else is read. 31 hostile strings are refused in a test (`typing.cast`, `builtins.eval`, `Optional.__class__`, `datetime.sys`, `Path.home()`, `Literal[print]`).

Proof: `tests/test_functional.py`, 29 parametrised annotations and the hostile strings, shallow and with `deep`.

### `coerce=True` made a bool an enum member (finding 12)

`Level(True)` is `Level.ON`, because `True == 1`. A bool is now only coerced where a member's own value is a bool ([_type_conversion.py:146](pyvalidate/_typechecker/_type_conversion.py#L146)). Numbers and strings are coerced as before.

### Union conversion tried `TypeModel` members first (finding 13)

`float | Port` given `80` made a `Port`, against the documented order. Members are now tried in declared order, a validated type in its place among them ([_type_conversion.py:221](pyvalidate/_typechecker/_type_conversion.py#L221)): conversions for each member in turn, then coercions in turn.

```python
float | Port    <- 80      # 80.0       (was Port(80))
Port | float    <- 80      # Port(80)
Port | float    <- 70000   # 70000.0: not a port, the next member takes it
```

### Converted defaults: under another decorator, and in the function you passed in (findings 14 and 25)

Two faults with one cause: a converted default (`factor: float = 2`) was written into the function's `__defaults__`.

- **Where that was impossible, the default went through unconverted** (14): below a `functools.wraps` decorator, for a `functools.partial`, for an object with `__call__`.
- **Where it was possible, it changed the caller's function** (25): after `checked = typecheck(scale)`, a plain `scale()` returned `2.0` too, and a second wrapper with `convert=False` stopped objecting once the first had run.

Now nothing is written into the function you pass in:

- **A plain function is copied** ([api.py:1318](pyvalidate/_typechecker/api.py#L1318), `_with_defaults`): same code, globals and closure, with the converted defaults. The wrapper calls the copy. It costs nothing per call, and the original keeps what it was written with.
- **Where a copy can't hold them, the wrapper passes them** ([api.py:2162](pyvalidate/_typechecker/api.py#L2162), `with_defaults`, and the generated wrapper): by keyword for a call that leaves the parameter out, by position for a positional-only one.
- **A dataclass's generated `__init__`** is still rewritten in place: it belongs to the class alone.

`inspect.signature` of a checked function now shows the default as written (`= 2`), where it showed `2.0` after the first call.

Proof: seven tests (`test_the_function_given_to_typecheck_keeps_its_defaults`, `test_two_wrappers_of_one_function_...`, `test_default_is_converted_under_a_functools_wraps_decorator` and the two after it).

### A pickled `TypeCheckerError` lost its data (finding 16)

An error now pickles with its problems, its context and its message ([_type_container.py:756](pyvalidate/_typechecker/_type_container.py#L756)):

- **Each problem travels as data**, with its message as text.
- **A part that can't be pickled** (a value of a local class, a lock) arrives as a stand-in that shows its `repr`. The error still arrives.
- **`problem.origin` is found again by name.** The function a problem holds is the one inside the wrapper, which pickle cannot find by name: it is looked up through the wrapper ([_type_container.py:771](pyvalidate/_typechecker/_type_container.py#L771)).

Checked through a real process boundary as well: two errors raised in spawned workers of a `ProcessPoolExecutor` arrived with their problems, values and origins. `copy.copy` and `copy.deepcopy` keep the problems too.

### Colours (finding 17)

- **The reset sequence in front of every message was computed at import.** With colours switched off later, a message still began with an escape sequence. It is built with the message now ([_type_container.py:817](pyvalidate/_typechecker/_type_container.py#L817)).
- **Colours follow both streams.** termcolor decided from stdout alone, and it keeps its first answer for the life of the process. pyvalidate now decides itself ([utils.py:15](pyvalidate/utils.py#L15), `colours_on`): messages are coloured only when stdout and stderr are both terminals, so `2> errors.log` gets plain text. `NO_COLOR` and `FORCE_COLOR` are honoured.
- **A message asks once** whether it is coloured, not once per word. Printing a plain message went from 2.7 µs to 2.0 µs.
- **The tests no longer depend on the shell.** `PYVALIDATE_COLOURS_OFF=1` failed 43 of them and `FORCE_COLOR=1` another 19. `tests/conftest.py` renders every message plain, and the formatter tests switch colours on for themselves. The suite passes under all four settings.

What is left is in the open findings: a coloured message still makes one termcolor call per word.

### Fields and annotations that were wrongly rejected (findings 19, 20)

- **A dataclass field held by a descriptor** (19). `quantity: Conversion = Conversion(default=100)`, the standard library's own example, was a definition error: `100` is no `Conversion`. Such a field is now left to its descriptor ([_dataclass_override.py:165](pyvalidate/_dataclass_override.py#L165)). The other fields are checked as before.
- **A positional-only parameter passed by keyword** (20). For `def f(a=1, b=2, /)`, `f(b=2)` ended in Python's own `TypeError` and `f(b="x")` in a type error for a call that cannot be made. Both are binding errors now, in Python's words ([api.py:744](pyvalidate/_typechecker/api.py#L744), `_full_check`).

### A message formatted the whole value (finding 22)

`short_repr` built the full `repr` to show 40 characters: 48 ms for a list of three million items. It now formats the items of a built-in container one at a time until the message is full ([_type_container.py:961](pyvalidate/_typechecker/_type_container.py#L961)): five items of a 100,000-item list.

The output is the start of `repr(value)`, exactly. A parametrised test compares 39 values at nine widths, and a probe compared 90,000 random nested values: no difference, including values that contain themselves and the quote that `repr` picks for text.

### `typing.no_type_check` worked in one order only (finding 26)

- **Below `@typecheck`:** the function comes back exactly as written, not wrapped.
- **Above `@typecheck`:** the mark lands on the wrapper after it was made. It is seen on the first call, and the wrapper becomes a pass-through ([api.py:388](pyvalidate/_typechecker/api.py#L388)).
- **On a method or a class:** `enforced` leaves marked methods plain, and `dataclass` builds a standard dataclass.

### Methods without annotations were wrapped (finding 27, in part)

A method of an enforced class without a single annotation now stays the plain function ([api.py:866](pyvalidate/_typechecker/api.py#L866)). A call that leaves a default out took 115 ns through the wrapper and takes 11 ns now. Whether there are annotations is read without evaluating any.

The rest of finding 27 is by design and stays open.

### `Self` inside an annotation accepted anything (finding 28, in part)

`Self | None`, `list[Self]`, `dict[str, Self]` and `type[Self]` are now checked as the class ([api.py:2391](pyvalidate/_typechecker/api.py#L2391), `_with_self`), in an enforced class, a dataclass field and a method with its own `@typecheck`, with `deep` and in strict mode.

What `Self` means is unchanged, and is the open half of the finding.

### Typed `**kwargs` (finding 29)

- **They belong to the checker now.** The keywords of `**kwargs: Unpack[Movie]` were written into pyvalidate's cached signature of the function, so `typecheck_from_dict` with a record of its own saw them, or not, depending on what had run first. A checker has its own signature ([api.py:2642](pyvalidate/_typechecker/api.py#L2642)); the function's is never altered.
- **A key that is no identifier is checked.** `"my-key"` or `"class"` left the whole function's keywords unchecked, without a message.

### `*args` as a tuple (finding 30)

- **Such a function gets the compiled wrapper.** A call costs 155 ns, where it took 535.
- **A run of unknown length is checked**: `*args: *tuple[int, *tuple[str, ...], float]`, and with `deep` the same shape as an ordinary annotation, `tuple[int, *tuple[str, ...]]` ([_deep.py:594](pyvalidate/_typechecker/_deep.py#L594), `VariadicTuple`). Both were accepted as they came.

`*args: *Ts` has nothing to check and is passed through.

### A local name that comes after the decorator (finding 31, in part)

```python
def test_tree():
    @dataclass
    class Tree:
        leaves: list[Leaf]      # Leaf is defined below
    @dataclass
    class Leaf: ...
    Tree([Leaf()])              # was: Cannot resolve annotation. Works now.
```

When a name can't be resolved, the enclosing function's frame is searched once more if that function is still running ([api.py:2411](pyvalidate/_typechecker/api.py#L2411), `_look_again`). What is found is kept. The limit is the open half of the finding.

### Long annotations in messages (finding 32)

An annotation shown in a message is cut after 80 characters, and so is the text of "Cannot resolve annotation".

### Smaller fixes

- **`Number`** had a check no value could fail. It is a finite `float` now: `nan` and the infinities are rejected.
- **A subclass of `typing.IO[str]`** passed as a binary file too. Its kind is read from its bases (finding 21, in part).
- **A check that raises `LookupError`** rejects the value, like the other three kinds. `lambda s: s[0] == "a"` given `""` escaped as an `IndexError` (finding 15, in part).
- **A callable with a broken `__signature__`** was passed through unchecked. It is reported.
- **Messages:** a field message has the colon parameter messages have (`expected type: 'int'`); the default of a field that `__init__` doesn't take is called a field; "got 1 item" in the singular; a plain subclass of a dataclass is called a class.
- **`python -m pytest tests/test_known_issues.py`** no longer ends with status 5: the file has tests.
- **`activate_env.sh`** names the environment through `$HOME`, and `PYVALIDATE_VENV` overrides it.
- **The docstring of `formatter`** called it `frmt`.

---

## The two new functions

```python
typecheck_function(area, (3, 4))                # checks the call, converts, calls: 12.0
enforce_class(Client, check_return = True)      # enforces the class in place and returns it
```

They are the decorators without the `@`, as you asked: `typecheck_function` typechecks and runs, `enforce_class` returns the type. They are at [api.py:1013](pyvalidate/_typechecker/api.py#L1013) and [api.py:1115](pyvalidate/_typechecker/api.py#L1115). A first version of this round checked a call and handed the arguments back without calling anything; it was replaced, and what only it needed was taken out again.

- **`typecheck_function(fn, args, kwargs, **options)`** wraps `fn` exactly as `typecheck` would and calls the wrapper. The arguments come as a tuple and a mapping, so that the five options have a place. The wrapper is remembered per function and set of options, so a second call runs the compiled check: 230 ns for two arguments, where a decorated function costs 81 ns.
- **The function is not replaced.** A direct call of it stays unchecked.
- **A bound method needs no `self`**, and is labelled as a method.
- **`enforce_class(cls, **options)`** is `enforced` with the options by keyword only. The class is changed in place, like under the decorator, and a second call leaves checked methods alone. A dataclass is refused, as by `@enforced`.
- **Each refuses the other's target** and names the right function.
- **`args` must be a tuple or a list.** A string would be taken apart into one argument per character.

Proof: `tests/test_functional.py`, 78 tests with those for record strings. One of them holds `enforce_class` against `@enforced` on the same class under six sets of options.

### A `TypeModel` class had a `__dict__` per instance (finding 18)

Asked for after the first version of this review, which had left it open. A model class now gets `__slots__ = ()` by itself, through a metaclass ([_type_data_model.py:20](pyvalidate/_typechecker/_type_data_model.py#L20), `ModelMeta`): 44 bytes for any `int` model where it was 60. A class that needs a dictionary declares `__slots__ = ("__dict__",)`.

The reason it was left open was speed: `isinstance` against a class with a metaclass is slower for a value that is no instance of exactly that class. Two things keep that off the valid-call path:

- **In a union the ordinary classes are tested first** ([api.py:1580](pyvalidate/_typechecker/api.py#L1580)), so `None` for `Email | None` never reaches the model.
- **The one-pass check of collection items still applies** to model classes with `deep`.

Measured old against new: `Email` given an `Email` 76 ns both; `Email | None` given `None` 80 ns before, 73 ns now; given an `Email` 78 ns before, 84 ns now; `list[Email]` × 100 with `deep` 664 ns both. So the order of the union's test moved 6 ns from one valid case to the other; nothing else changed.

Found with it: `copy.copy` of a `Fraction`-based model raised, because `Fraction` copies itself by calling its class with two arguments. A copy of a model is the model now.

---

## Behaviour that changed, and that code may have relied on

- **Messages.** Field messages have a colon after "expected type". "For default value of field x" for a field that is no parameter. "got 1 item". A long annotation is cut. `<Class Child>` for a plain subclass of a dataclass.
- **Newly rejected.** A bool for an enum under `coerce`. `nan` and infinities for `Number`. A wrong item in a tuple with a run of unknown length. A wrong value for `Self | None` or `list[Self]`. A keyword that is no identifier under `Unpack[TypedDict]`. A subclass of `IO[str]` as a binary file. A value whose `Annotated` check raises `LookupError` (it was an escaping exception).
- **Newly accepted.** A dataclass with a descriptor field. Local classes that name each other, while their function runs.
- **Other results.** `float | Port` gives a `float` for an `int`. A function passed to `typecheck` keeps its defaults, and `inspect.signature` of the checked one shows them as written. `typecheck_from_dict` returns a converted default by keyword. A `TypeModel` instance has no `__dict__`, and `copy.copy` of one returns it.
- **Other errors.** A call that an unannotated method of an enforced class can't take raises Python's `TypeError`, not a `TypeCheckerError` (which is a `TypeError`). A positional-only parameter passed by keyword raises a `TypeCheckerError`.
- **Colours.** Messages are plain unless both streams are terminals. The dependency is `termcolor>=2.1`.
- **Names.** The internal `_typecheck_function` is `_full_check`, so that it is not taken for the public function.

---

## Open, all Low

### 2. Static typing and publishing: what is inherent

- **A model in the short form is not its base type for a checker.** `class Slug(TypeModel[str])` works at runtime; a checker needs `class Slug(TypeModel[str], str)`. The type system cannot express a class that inherits from its own parameter.
- **A call that relies on conversion is reported by a checker.** `connect("a@b.co", 8080)` for `Email` and `Port` parameters is valid at runtime.
- **Before a release:** the name `pyvalidate` is taken on PyPI (another project, 1.3.1), and there is no `LICENSE` file.

### 15. Every callable in `Annotated` metadata is a check

`Annotated[str, str.strip]` rejects `" "`: the empty result counts as "no". That is the documented rule, and the README now says so in as many words. Ending the ambiguity needs a marker (`Check(fn)`), which is a design decision and belongs with the constraint markers on the roadmap.

### 17. A coloured message costs one termcolor call per word

7 µs coloured against 2 µs plain, for a message of one problem. Caching the escape sequences per style would remove it. `tests/test_formatter.py` asserts on each termcolor call, so that is a rewrite of your tests, which I left alone. Colours are only on at a terminal now, where 5 µs is not felt.

### 21. File-like objects: two edges

- A `unittest.mock.Mock()` is no file: it has no `__enter__`, which `typing.IO` declares. `MagicMock()` and `Mock(spec=io.StringIO)` are.
- `type[TextIO]` accepts the `io` classes, not the class of a file-like wrapper: whether its instances are text is not visible on the class.

Both are in the README.

### 23. A standard-library dataclass below a checked one

`@dataclasses.dataclass class Child(Base)` with a pyvalidate `Base` inherits the base's check. A field it gives another type is still held to the base's type. Noticing such a subclass needs a hook at class creation or a test on every assignment; decorating the child with pyvalidate's `dataclass` is the answer, and the README says so. It has an expected-failure test.

### 24. A value changed in place is not checked

`order.tags.append(5)` is no assignment. Inherent, and now listed under Limitations. Not in the table above: there is nothing to fix.

### 27. What `enforced` leaves unchecked, by design

Attribute assignment, properties, comparisons and operators, subclasses that aren't decorated, methods added later, and `@dataclasses.dataclass` written above `@enforced`. All are in the README. One small thing remains from this round: a method with only a return annotation, such as `def __init__(self) -> None`, is still wrapped although nothing is checked without `check_return`. Telling that apart needs the annotation's names, which are not known without evaluating it.

### 28. `Self` is the class that defines the method

A method called on a `Child` may return a plain `Base` for `-> Self`. Checking against `type(self)` needs a check that sees two values at once; every check here sees one, in the generated wrapper and on the error path. It has an expected-failure test.

### 31. A local name that comes after the decorator is found only while its function runs

```python
def build():
    @typecheck
    def f(x: "Later"): ...
    class Later: ...
    return f            # called after build() has returned: Later is not found
```

Finding it later would mean keeping the frame of `build`. A frame keeps its caller's frames, and with them every local variable of the whole call stack, alive. That is too much to hold on to for an annotation.

### 33. The wrapper of a generator function carries a flag Python doesn't read (new)

The fix for finding 1 marks an ordinary function's code as a generator function's. It works because CPython, since 3.11, makes a generator through an instruction at the start of the code and never consults the flag when it runs a function. Tracing, `sys.monitoring`, the specialising interpreter and `-X dev` were tried and behave.

It is still a statement about the code that is not true of it. A future CPython could check it.

- **If that happens, a test fails**: `test_checked_generator_function_is_still_checked_when_it_is_called`.
- **The way back is one line**: without the flag everything works as before the round, and finding 1 is open again.

### 34. `typecheck_function` keeps the functions it called alive (new)

It remembers the checked wrapper per function, for the 512 called last. A wrapper holds its function, so an entry cannot go when the function does: a function made in a loop and called once this way stays until 512 newer ones have come. `typecheck_from_dict` has always done the same. The bound is what keeps it from growing.

### 35. `no_type_check` on a base class reaches a dataclass, not an enforced class (new)

`typing.get_type_hints` returns nothing for a class whose base is marked, so a `@dataclass` below a marked class is unchecked, and built as a standard dataclass. The methods of an `@enforced` class below the same base are checked: a function carries its own mark. Both follow from how `typing` reads the mark; neither is documented.

---

## Fixed in earlier reviews

Kept short.

- **`typing.TextIO`, `IO[str]`, `BinaryIO` rejected every real file** (was High).
- **`typecheck_from_dict` crashed under threads once its cache was full** (was High; [api.py:1167](pyvalidate/_typechecker/api.py#L1167)).
- **A subclass of a checked dataclass was checked by every decorated ancestor** (was High; [_dataclass_override.py:576](pyvalidate/_dataclass_override.py#L576)).
- **A string in a `typecheck_from_dict` record was run as code** (was High; [_type_container.py:373](pyvalidate/_typechecker/_type_container.py#L373), `read_annotation`).
- **A `TypeVar` with a string bound made every call fail** (was High).
- **`@typecheck` above `@classmethod` broke every call** (was Medium; [api.py:396](pyvalidate/_typechecker/api.py#L396)).
- **`typecheck` and `enforced` were split** ([api.py:74](pyvalidate/_typechecker/api.py#L74), [api.py:157](pyvalidate/_typechecker/api.py#L157)), with `skip_typecheck` ([api.py:272](pyvalidate/_typechecker/api.py#L272)) and the checked special methods ([api.py:845](pyvalidate/_typechecker/api.py#L845)).
- **`dataclass` was `Any` to type checkers**, mypy refused `TypeModel[str]`, and the package had no `pyproject.toml` ([_dataclass_override.py:66](pyvalidate/_dataclass_override.py#L66)).
- **Findings 4 to 10 of the fourth review**: mapping types under `deep`, unchecked annotations and targets, contradictory messages, caches that stopped caching, strict mode for abstract classes, string annotations with local names, old-style recursive aliases.

---

## Performance

Measured for the first review with `tests/benchmark.py --quick`. The hot paths were compared again after each round of changes, old against new and interleaved, and moved by no more than the noise between runs.

| Area | pyvalidate | Compared with | Note |
|---|---|---|---|
| Missing argument (raise + catch) | 7.27 µs | pydantic 0.51, typeguard 0.17 | 14× pydantic; on the roadmap |
| 3 wrong arguments of 12 | 5.24 µs | pydantic 0.68 | 7.7× |
| 1 wrong argument of 2 | 1.62 µs | pydantic 0.48 | 3.4× |
| Bad item in `dict[str, list[int]]` (`deep`) | 9.19 µs | pydantic 1.64 | 5.6× |
| Dataclass assignment of a wrong type | 1.90 µs | pydantic 0.48, attrs 0.54 | 4× |
| Construct `Point(x=1, y=2.0)` | 0.534 µs | attrs 0.306, beartype 0.326, pydantic model 0.402 | the generated `__init__` on the roadmap |
| Call with defaults omitted (1 of 5 given) | 0.171 µs | beartype 0.150 | the general lane |
| Function with only `Any` / `object` parameters | 0.057 µs | beartype 0.010 | nothing to check, still wrapped |
| First call of a 12-parameter function | 1.17 ms | pydantic 0.27 ms, beartype 0.58 ms | tiered compilation on the roadmap |
| Memory per decorated function | 9.7 KB | pydantic 4.0, beartype 2.8 | not listed anywhere yet |

This round, old against new (interleaved `timeit`, median of 15 rounds, messages plain):

| Case | Before | After | Change |
|---|---|---|---|
| Call, 1 parameter | 76.9 ns | 76.4 ns | −0.7% |
| Call, 2 parameters | 83.8 ns | 84.0 ns | +0.3% |
| Call, 12 parameters | 211.6 ns | 210.7 ns | −0.4% |
| Call with `check_return` | 97.2 ns | 98.4 ns | +1.2% |
| Call: `Optional`, `Literal`, `Sequence`, `type[X]` | 232.6 ns | 235.0 ns | +1.0% |
| Call, strict, 3 parameters | 90.7 ns | 87.2 ns | −3.9% |
| Call with `*args` and `**kwargs` | 261.1 ns | 260.7 ns | −0.2% |
| Call converting two `int` to `float` | 283.2 ns | 284.1 ns | +0.3% |
| Call that leaves converted defaults out | 169.3 ns | 167.3 ns | −1.2% |
| Call with a keyword | 160.3 ns | 166.7 ns | +4.0% |
| Deep `list[int]` × 1,000 | 4,797.7 ns | 4,814.5 ns | +0.4% |
| Enforced method | 78.5 ns | 78.7 ns | +0.2% |
| Enforced `__call__` | 88.3 ns | 87.9 ns | −0.5% |
| Enforced construction | 115.5 ns | 114.9 ns | −0.5% |
| Dataclass construction | 275.9 ns | 276.9 ns | +0.4% |
| Dataclass assignment | 78.1 ns | 78.4 ns | +0.4% |
| Call of a generator function | 90.0 ns | 91.2 ns | +1.4% |
| Call with `*args: *tuple[int, str]` | 534.7 ns | 154.9 ns | −71.0% |
| `typecheck_from_dict`, cached | 1,147.8 ns | 1,158.7 ns | +1.0% |
| Wrong argument, raise and catch | 1,623.3 ns | 1,628.9 ns | +0.3% |
| Missing argument, raise and catch | 7.71 µs | 7.69 µs | −0.2% |
| Wrong dataclass assignment | 1,885.9 ns | 1,877.6 ns | −0.4% |
| Wrong argument: raise, catch and print | 4,255.8 ns | 3,579.9 ns | −15.9% |
| `Literal` mismatch: raise, catch and print | 6.50 µs | 5.78 µs | −11.1% |
| Decorate a function | 2,609.4 ns | 2,414.8 ns | −7.5% |
| Decorate a function and call it once | 35.33 µs | 35.78 µs | +1.3% |
| The same, with a default that is converted | 48.51 µs | 42.52 µs | −12.3% |
| Enforce a class of 3 methods, one without annotations | 11.17 µs | 9.14 µs | −18.2% |
| Define a dataclass and build one instance | 267.85 µs | 275.38 µs | +2.8% |

- **Valid calls are unchanged.** The generated wrapper is the same source as before, character for character, for the twelve shapes compared (functions, methods, a dataclass `__init__`, a generator, a coroutine). The 4% on "call with a keyword" is noise: 41 more rounds of that case gave 166.2 ns and 165.9 ns.
- **`*args: *tuple[...]` is 3.5 times faster**: it has the compiled wrapper now.
- **Printing a message is faster**, since it asks once whether it is coloured.
- **Decorating is cheaper**, for a function and for a class with a method that has no annotations.
- **The first call of a function with a converted default is 6 µs cheaper.** The function is copied, which takes about 1 µs; before, the signature was worked out a second time after the defaults were rewritten.
- **Defining a dataclass costs 1 to 3% more** (about 3 to 7 µs, once per class), for the look at which fields a descriptor holds.

For reference: `typecheck_function(fn, (1.0, 2.0))` costs 230 ns where the decorated function costs 81 ns and the plain one 17 ns; `typecheck_from_dict` 1.17 µs.

---

## Smaller items

- The converted default of an enforced `NamedTuple` class is what instances get, while `Point._field_defaults` still shows the unconverted one.
- The missing-argument message for a typed `**kwargs` key says "argument" where Python says "keyword-only argument".
- `Sequence[str]` accepts a plain `str`, as the typing rules have it. The README now says so in the table of annotations.
- `Problem.__reduce__` pickles each part once to find out whether it can, and pickle then does it again. Only when an error is pickled.
- `tests/benchmark.py` was not run and not changed. It still parses and uses none of the names that changed.
- `tests/fuzz.py` has two more ways to use an annotation (`function call`, `class call`), and `--expect` is now searched in the whole outcome, not in the 240 characters that are printed: an intended difference can sit in the sixth problem of a long message.
- A new file `protector.py` and an empty `tests.output.log` appeared in the repository root during the round. Neither is mine; both were left alone.

---

## What held up

- **Differential fuzz.** 2,300,000 values against the package from before the round, each difference sorted by a script. Of 2,000,000 values sorted by a script, 66,699 differ. 66,657 are a message worded differently: the field wording, the colon and plural of a length message, a cut annotation. 22 are a bool that is no longer coerced to an enum member (finding 12), and 20 a union with a validated type that is now converted in declared order (finding 13). Nothing else differs. Three more runs of 100,000 are the documented kind, with the five intended differences named through `--expect` and `--ignore-type-names`; each ends with "Fuzz passed!".
- **Properties.** 360,000 values over 24 ways of using an annotation: every error a `TypeCheckerError` or one Python itself raises; no second call, returned value, subclass, typed keyword, tuple argument, callable object, `typecheck_function` or `enforce_class` disagreed with the plain form; no looser setting rejected what the stricter one accepted.
- **Converted defaults at their edges.** Below a `functools.wraps` decorator with `*args` and `**kwargs`, on an async function, a method and a class method, positional-only, in a recursive function, in a generator function, with zero-argument `super()` in a copied `__init__`, and in a dataclass whose hand-written `__init__` is wrapped: each receives the converted value on the first call and on later ones.
- **The two functions at their edges.** `typecheck_function` with bound and unbound methods, class and static methods, a `partial`, an object with `__call__`, builtins, an already decorated function, async and generator functions, local names in quoted annotations, eight threads. `enforce_class` against `@enforced` on the same class under six sets of options, a `NamedTuple`, a subclass, a second call.
- **Record strings** are still never run: 31 hostile strings, shallow and deep.
- **Errors across processes.** Raised in spawned workers, received with problems, values and origins.
- **The suite under four colour settings**: default, `PYVALIDATE_COLOURS_OFF=1`, `FORCE_COLOR=1`, `NO_COLOR=1`.
- **Packaging.** Wheel (16 files, `py.typed`, no tests) and sdist build; the wheel installs with `termcolor` alone; the sdist's tests pass against the installed package.

---

## How this review was done

1. Each fix was built against a copy of the package taken before the round. Tests, simulation and both type checkers were run after each step, and the finished tests were run against the old copy.
2. The diff of the round was read again as a whole: about 1,600 changed lines in the package. Reading and probing found four faults in the new code, all fixed before this was written: a cache that could never let go of a function, a value preview that came out too short, a label written onto a function that was only described, and a string taken apart as arguments.
3. Probe scripts were run on the final code for every finding and for the new functions at their edges (the lists under "What held up").
4. mypy and pyright were run from a scratch environment on the package and on the sample file.
5. Both distributions were built and installed into fresh environments, and the sdist's own test suite was run.

Limits of what was checked:

- **The fuzz runs predate the last two changes**: `typecheck_function` and `enforce_class` in their final form, and the `TypeModel` metaclass. At your request only the unit tests and the simulation were run on those. The two fuzz uses were rewritten for the new functions (`tests/fuzz.py` compiles) but have not been run.
- The free-threaded build of Python was not tried: the thread tests ran with the GIL.
- `tests/benchmark.py` was not run.
- The generator flag (finding 33) was tried on CPython 3.14.4 only, and not on a debug build.
- The type checkers were run on the package and on a file written for the purpose, not on a real program that uses the package.
- Nothing was uploaded anywhere.
