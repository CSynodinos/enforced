# enforced

**Runtime type checking for Python, driven by the annotations you already write.**

enforced is a lightweight alternative to pydantic. It doesn't use models, schemas or a new DSL. You decorate a function (`@typecheck`), a class (`@enforce`) or a dataclass (`@dataclass`), and its type hints are enforced every time it's called. Where a decorator can't be written, `typecheck_function` and `enforce_class` do the same without one.

```python
from enforced import typecheck

@typecheck
def greet(name: str, times: int = 1) -> str:
    return f"Hello, {name}! " * times

greet("Ana", 2)     # fine
greet("Ana", "2")   # TypeCheckerError
```

```
TypeCheckerError: 1 problem found in call:
    -> For parameter times of <Function greet>: expected type: 'int', got type 'str' (Value: '2')
```

---

## Contents

- [Why enforced](#why-enforced)
- [Installation](#installation)
- [Type checkers and editors](#type-checkers-and-editors)
- [Quick start](#quick-start)
- [Functions](#functions)
- [Classes](#classes)
- [Dataclasses](#dataclasses)
- [Conversion and coercion](#conversion-and-coercion)
- [Checking collection items](#checking-collection-items)
- [Validated values](#validated-values)
- [Checking without a decorator](#checking-without-a-decorator)
- [Results instead of exceptions](#results-instead-of-exceptions)
- [Error messages](#error-messages)
- [Supported annotations](#supported-annotations)
- [Options](#options)
- [Performance](#performance)
- [Limitations](#limitations)
- [Roadmap](#roadmap)

---

## Why enforced

- **It uses plain Python annotations.** If your code is already type-hinted, there's nothing new to learn.
- **It's strict by default.** `"2"` is never silently turned into `2`, and `True` is not accepted as an `int`. The only automatic change is lossless numeric widening (`1` → `1.0` for a `float`), which the typing rules already allow. Parsing is opt-in with `coerce=True`.
- **It reports every problem at once.** One call reports every bad argument, not just the first.
- **It can check every item, at every depth.** With `deep=True`, `list[int]`, `dict[str, list[float]]`, `tuple[int, str]`, `TypedDict` and `NamedTuple` are checked all the way down, and errors point at the bad item (`prices['apple']`, `rows[3][1]`).
- **It explains mistakes.** Missing arguments are named with their expected types, and when positional arguments are shifted, enforced infers which ones you actually skipped.
- **It checks defaults first.** A default value that contradicts its own annotation is reported as a definition error.
- **Its dataclass is a drop-in replacement.** Swap `from dataclasses import dataclass` for `from enforced import dataclass` and fields are validated on construction and on assignment.
- **It's fast.** A checked call costs about 40 ns plus 8 ns per parameter (see [Performance](#performance)).
- **It's small.** Its only dependency is `termcolor`, for coloured error output.

## Installation

enforced requires **Python 3.14+**, because it uses `annotationlib` and the PEP 695 `type` statement.

From the repository root:

```bash
pip install .                # the package; its one dependency, termcolor, comes with it
pip install -e ".[dev]"      # for working on it: editable, with pytest and mypy for the tests
```

The package is described in `pyproject.toml`. `python -m build` makes a wheel and a source distribution from it.

enforced is released under the MIT licence (see `LICENSE`).

## Type checkers and editors

The package ships its type information (a `py.typed` marker), so mypy, pyright and Pylance read it. Both mypy and pyright report nothing in the package's own files.

- **What you decorate keeps its type.** A function under `@typecheck`, a class under `@enforce` and their methods look to a checker exactly as you wrote them, with or without options.
- **A class under enforced's `@dataclass` is a dataclass to the checker too.** It knows the generated `__init__`, completes the fields, and reports a wrong argument, a missing one, or an assignment to a frozen instance before the program runs.
- **A value that relies on conversion is reported by the checker.** `area(3, 4)` is fine for both, since an `int` is acceptable where a `float` is expected. `connect("a@b.co", 8080)` for parameters annotated `Email` and `Port` works at runtime, where the raw values are built into the types, but a checker sees a `str` passed for an `Email`. Write `connect(Email("a@b.co"), Port(8080))` to satisfy both.
- **A validated type is its base type for the checker too.** `class Slug(TypeModel[str])` is a `str` to mypy and pyright, so `Slug("a").upper()` and passing it where a `str` is expected are fine, and the methods and properties the class adds are known. `Email` and `Port` are written this way. An older spelling that named the base a second time, `class Slug(TypeModel[str], str)`, still runs, but a checker now reports a duplicate base class: drop the second base.

## Quick start

```python
from enforced import typecheck, dataclass, TypeCheckerError

@typecheck(check_return=True)
def area(width: float, height: float) -> float:
    return width * height

@dataclass
class User:
    name: str
    age: int
    email: str | None = None

area(3, 4)                 # 12.0: the ints are converted to floats
User("Ana", 30)            # fine
User("Ana", "thirty")      # TypeCheckerError

try:
    area("3", 4.0)
except TypeCheckerError as e:   # TypeCheckerError subclasses TypeError
    print(e)
```

---

## Functions

```python
@typecheck
def f(a: int, b: str = "x") -> None: ...
```

Every call is checked against the annotations, in this order:

1. **Defaults.** Each default value is checked against its annotation, once, on the first call. A bad default raises on every call until it's fixed.
2. **Binding.** Unknown keywords, duplicate values, too many positionals and positional-only parameters passed by keyword are all reported.
3. **Missing arguments.** All of them are listed together, with their expected types.
4. **Argument types.** Every supplied argument is checked, and all failures are reported together. Values that fail but can be converted are converted instead (see [Conversion and coercion](#conversion-and-coercion)).
5. **Return value.** This is optional; see `check_return` under [Options](#options).

All parameter kinds are supported, including positional-only, keyword-only, `*args: T` (each element is checked) and `**kwargs: T` (each value is checked):

```python
@typecheck
def log(level: int, *parts: str, sep: str = " ", **tags: str) -> None: ...

log(1, "a", "b", 3)   # -> For parameter parts[2] ... expected type: 'str', got type 'int'
```

Two spellings give `*args` and `**kwargs` a shape of their own, and both are checked:

```python
from typing import Required, TypedDict, Unpack

class Options(TypedDict, total=False):
    name: Required[str]
    size: int

@typecheck
def build(count: int, **options: Unpack[Options]) -> None: ...      # the keywords are the keys of Options

build(1, name="a")              # fine: size is optional
build(1, name="a", size="2")    # -> For parameter size ... expected type: 'int', got type 'str'
build(1, name="a", colour=1)    # -> got an unexpected keyword argument 'colour'
build(1)                        # -> Missing required argument ... name

@typecheck
def move(speed: float, *point: *tuple[int, str]) -> None: ...       # exactly an int and a str after speed

move(1.0, 2, "north")           # fine
move(1.0, 2, "north", 3)        # -> expected type: tuple[int, str] with 2 items, got 3 items
```

`*args: *tuple[int, ...]` means the same as `*args: int`. A run of unknown length may stand among fixed items: `*args: *tuple[int, *tuple[str, ...], float]` takes an `int`, any number of `str` and a `float`.

### Other callables

`typecheck` can also be called on something that isn't a function you wrote:

- **An object with `__call__`** is checked against that method.
- **A `functools.partial`** is checked against the function it wraps, for the parameters it still takes. An argument fixed by keyword is checked like a default.
- **A function wrapped by another decorator** (`functools.lru_cache`, anything that uses `functools.wraps`) is checked against the function inside.
- **A builtin** has no annotations, so there is nothing to check; the call simply goes through.

A default that needs converting (`factor: float = 2`) reaches all of these as `2.0`: where it can't be written into a function, the checked call passes it along.

### Async functions

Coroutines are supported. Arguments are checked when the coroutine is awaited, and the return check applies to the awaited result, not the coroutine object.

```python
@typecheck(check_return=True)
async def fetch(user_id: int) -> dict:
    ...
```

### Generators

Arguments are checked when the generator function is called, before the first `next()`. Yielded values are not checked.

A decorated generator function is still one for `inspect.isgeneratorfunction`, and an async generator function for `inspect.isasyncgenfunction`. Frameworks that ask, such as pytest for a `yield` fixture, treat it as they would the function you wrote.

This rests on how CPython runs code today, so enforced tries it once when it is imported. On a Python where it would not hold, a decorated generator function is checked and works exactly the same, and only `inspect` takes it for an ordinary function.

### Leaving a function unchecked

`typing.no_type_check` switches the checks off, written above or below `@typecheck`. Below, the function comes back exactly as you wrote it. The same mark on a method keeps `@enforce` away from it, and on a whole class it leaves `@enforce` and `@dataclass` with nothing to check.

The mark speaks for the class it is written on, not for its subclasses. A subclass that is decorated is checked: an `@enforce` class for the methods it defines, a `@dataclass` for the fields it declares. What it inherits from the marked class stays unchecked.

---

## Classes

A class has its own decorator, `enforce`. It checks `__init__` and every ordinary method, `@staticmethod` and `@classmethod` the class defines, and takes the same options as `typecheck`:

```python
from typing import Self
from enforced import enforce, skip_typecheck

@enforce(check_return=True)
class Builder:
    def __init__(self, name: str) -> None:
        self.name = name

    def rename(self, name: str) -> Self:
        self.name = name
        return self

    @staticmethod
    def parse(raw: str) -> "Builder":
        return Builder(raw)

    @skip_typecheck
    def dump(self, sink) -> None:       # left exactly as it is
        print(self.name, file=sink)

Builder(42)                 # TypeCheckerError: for <Class Builder>
Builder("a").rename(1)      # TypeCheckerError: for <Method Builder.rename>
```

- A string forward reference to the class itself (`"Builder"`) resolves to the class.
- **`Self` is the class of the instance the method is called on**, also inside an annotation (`Self | None`, `list[Self]`, `type[Self]`). For a class method it is the class it is called on. So an inherited method follows the subclass: `Special().rename("a")` has to return a `Special`, and `special.merge(other)` with `other: Self` takes a `Special`, not a plain `Builder`.
- `check_return` applies to the methods, not to `__init__` and `__new__`.
- **A method without a single annotation is left exactly as it is.** There is nothing to check, so it costs nothing to call. A call it can't take raises Python's own `TypeError`.
- **Special methods.** Those a caller hands values to are checked like any method: `__new__`, `__call__`, `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`, and with `check_return` what `__enter__` and `__aenter__` return. So `obj("x")`, `obj[1.5]` and `"a" in obj` raise when the annotation says otherwise, and a `NamedTuple` class is checked when it's built.
- The other special methods (`__eq__`, `__lt__`, `__add__`, `__repr__`, `__exit__`, `__setattr__`, ...) are left alone, because Python itself calls them, often with any object: `money == "x"` must stay `False`, not raise. To check one of these, give it its own `@typecheck`.
- **Properties are checked.** What is assigned is checked against the setter's annotation and converted like any argument (`account.balance = 3` stores `3.0` for `value: float`); with `check_return`, what the getter returns is checked too, and so is a `functools.cached_property`. A getter has nothing to check without `check_return` and is left exactly as it is, so reading the attribute costs what it did. Messages read `<Method Account.balance>`. Mark an accessor with `@skip_typecheck` to leave it out.
- **Subclasses.** A subclass inherits the checked methods. The methods it defines itself are checked only when it's decorated too.
- Methods added to the class after it was decorated aren't checked.

**Leaving a method out.** Mark it with `@skip_typecheck`. The method stays the plain function you wrote, so calling it costs nothing extra and its annotations are never looked at. The mark can be written above or below `@classmethod` and `@staticmethod`, and it isn't inherited: a subclass that overrides the method decides again. `typing.no_type_check` on a method has the same effect.

**Other options for one method.** Give the method its own `@typecheck(...)`. It keeps those options, whatever the class was given, and it isn't checked a second time:

```python
@enforce
class Form:
    def name(self, text: str) -> str: ...       # the class's options: "42" for an int would be rejected

    @typecheck(coerce=True)
    def age(self, years: int) -> int: ...       # this method parses: age("42") receives 42
```

### Which decorator

| You have | Use | It checks |
|---|---|---|
| A function, or one method | `@typecheck` | The arguments of every call, and the return value with `check_return` |
| A class | `@enforce` | The same, for `__init__`, every method the class defines, and special methods such as `__call__` and `__getitem__` |
| A dataclass | `@dataclass` (enforced's) | The fields, on construction and on assignment |

Each decorator refuses what belongs to another, at the definition: `@typecheck` on a class and `@enforce` on a function or a dataclass raise a `TypeCheckerError` that names the one to use. A plain subclass of a dataclass is a plain class, and can be enforced. To check a method of a dataclass, decorate the method with `@typecheck`.

> **Changed:** `@typecheck` used to accept classes. Replace `@typecheck` above a class with `@enforce`: the options and the behaviour are the same, except that a method with its own `@typecheck` is now checked with its own options only, where it used to be checked twice. Where `@typecheck` stood above `@dataclasses.dataclass`, use enforced's `@dataclass` instead of the pair. It checks assignments as well (`check_assignment=False` turns that off), and it does not check the class's methods: give those `@typecheck`.

### Methods one by one

`@typecheck` also works on a single method of any class, including property setters:

```python
class Account:
    @property
    def balance(self) -> float: ...

    @balance.setter
    @typecheck
    def balance(self, value: float) -> None: ...

    @typecheck                  # above or below @classmethod: both work
    @classmethod
    def open(cls, owner: str) -> "Account": ...
```

`@typecheck` can be written above or below `@classmethod`, `@staticmethod`, `@property` and `functools.cached_property`. Either way the attribute stays what the other decorator made it. Above any other object that can't be called, it raises a `TypeCheckerError` at the definition.

A method decorated this way finds its class the first time it is called, so `Self` is checked and messages read `<Method Account.open>`, as in an enforced class.

---

## Dataclasses

`enforced.dataclass` takes every argument the standard library's `dataclass` does, plus five of its own:

```python
from dataclasses import field
from enforced import dataclass

@dataclass
class Order:
    item: str
    qty: int
    price: float = 0          # stored as 0.0
    tags: list[str] = field(default_factory=list)
    total: float = field(init=False)

    def __post_init__(self) -> None:
        self.total = self.qty * self.price

o = Order("pen", 3, 2)        # price stored as 2.0
Order("pen", "3")             # TypeCheckerError: construction
o.qty = "many"                # TypeCheckerError: assignment
o.price = 5                   # stored as 5.0
```

| Argument | Default | Meaning |
|---|---|---|
| `allow_subclass` | `True` | Accept subclass instances (see [Options](#options)). |
| `check_assignment` | `True` | Also validate `obj.field = value` after construction. Ignored for `frozen=True`. |
| `convert` | `True` | Losslessly convert values in construction, defaults and assignment (see [Conversion and coercion](#conversion-and-coercion)). |
| `coerce` | `False` | Also parse values, so `Order("pen", "3")` stores `3`. |
| `deep` | `False` | Also check the items inside collection fields, on construction and assignment (see [Checking collection items](#checking-collection-items)). |

What gets checked:

- **Construction:** every `__init__` argument, with defaults checked first and missing fields named.
- **Defaults:** every field default is checked (and converted) once, on the first construction, like the default of a function. That includes the default of an `init=False` field, which `__init__` never receives: `total: float = field(init=False, default=0)` reads `0.0`. A wrong default is a definition error.
- **Assignment:** every write to a declared field, including writes inside `__post_init__` and to `init=False` fields. A rejected write leaves the old value in place.
- **`default_factory`:** the factory output is validated (and converted) like any other value, in frozen dataclasses and with `check_assignment=False` too.
- **Once per value:** an argument is checked once per construction. The class gets an `__init__` of its own that takes what the standard one takes and stores each checked argument directly, so it isn't checked a second time on assignment. What nobody has checked yet still is: the result of a `default_factory`, and whatever `__post_init__` assigns. (Where a class in the line defines `__setattr__` by hand, the standard `__init__` is kept, so that method sees every assignment. The same holds for a class's first 63 constructions, before its checks are compiled: there an argument is checked on construction and again on assignment. See [Performance](#performance).)
- **`InitVar[T]`:** checked as `T`.
- **`ClassVar`:** not an instance field, so not checked.
- **A field held by a descriptor** (`quantity: Conversion = Conversion(default=100)`, as in the standard library's documentation) is left to the descriptor. Its annotation names the descriptor class, not what the values are, so the default and every value go to the descriptor unchecked. The other fields of the class are checked as usual.
- **Inheritance:** inherited fields are checked on both construction and assignment. A decorated subclass is checked once, with its own options, whatever its base classes were given: it can be stricter or looser than its base (`allow_subclass`, `coerce`, `deep`, `check_assignment`), and it can give an inherited field another type. A subclass that isn't decorated keeps the checks of its base. That includes a subclass made a dataclass by the standard library's decorator, with one difference: a field it declares itself, such as an inherited one given another type, is its own and is not checked, like every field of a standard dataclass. Decorate it with enforced's `dataclass` to have its fields checked too.
- **`dataclasses.replace()`:** goes through `__init__`, so it's checked (and converted) too.
- **Stdlib options:** `frozen`, `slots`, `kw_only`, `order` and the rest behave exactly as in the standard library.
- **`@dataclass(init=False)`:** there is no generated `__init__` to check. The field defaults are checked (and converted) when the first instance is built, and assignments as usual, including those your own `__init__` makes. Its arguments aren't checked: decorate it with `@typecheck` for that.

---

## Conversion and coercion

When a value fails its check, enforced can convert it instead of rejecting it. Valid values are never touched, and conversion costs nothing on calls that don't need it.

**Conversion** (`convert=True`, on by default) covers lossless changes that the typing rules already treat as compatible, i.e. the PEP 484 numeric tower:

| From | To | Example |
|---|---|---|
| `int` | `float` | `1` → `1.0`, only when exact (`2**53 + 1` is rejected) |
| `int`, `float` | `complex` | `2` → `(2+0j)` |

`bool` is never converted to a number.

**Coercion** (`coerce=True`, off by default) adds parsing and lossy-but-checked changes, similar to pydantic's lax mode. It includes conversion.

| From | To | Example |
|---|---|---|
| `str` | `int`, `float`, `complex` | `" -7 "` → `-7`, `"1e3"` → `1000.0` |
| `str` | `bool` | `true/false`, `yes/no`, `on/off`, `t/f`, `y/n`, `1/0` (any case) |
| `int`, `float` | `bool` | only `0` and `1` |
| `float` | `int` | whole numbers only: `3.0` → `3`, `3.5` is rejected |
| `str` ↔ `bytes` | | UTF-8 |
| a value | an `Enum` member | `"red"` → `Color.RED`. A `bool` is only taken where a member's own value is one: `True` is not `Level.ON` because `True == 1` |
| `list`, `tuple`, `set`, `frozenset` | each other | `(1, 2)` → `[1, 2]` |
| `str` | `datetime`, `date`, `time` | ISO 8601, via `fromisoformat` |
| `str` | `Decimal`, `Fraction`, `UUID`, `pathlib` paths | `"1.10"` → `Decimal("1.10")` |

```python
@typecheck(coerce=True)
def configure(port: int, debug: bool, mode: Mode) -> None: ...

configure("8080", "yes", "fast")   # port=8080, debug=True, mode=Mode.FAST
configure("80.5", "yes", "fast")   # TypeCheckerError: '80.5' can't become an int
```

How it behaves:

- **Unions:** conversions are tried before coercions, members in declared order, and the first result that passes the check wins. `int | float` turns `"1.5"` into `1.5`; `bool | float` turns `1` into `1.0`. A validated type takes its turn like any other member: `float | Port` turns `80` into `80.0`, `Port | float` into `Port(80)`.
- **Never converted:** `Literal`, `type[X]` and `Any`.
- **Defaults are converted too.** `def f(x: float = 0)` is accepted and `f()` receives `0.0`. The function you wrote keeps the default it was written with: the checked function calls a copy that has the converted one, so `checked = typecheck(scale)` leaves `scale` as it was.
- **Return values** are converted when `check_return=True`, but never coerced. `coerce=True` parses what comes in (arguments and defaults); a function that returns `"42"` for `-> int` has a bug, and it is reported.
- **Error messages** only mention arguments that couldn't be converted, and show the original value.

---

## Checking collection items

By default only the outer type of a collection is checked: `list[int]` accepts `["a", "b"]`. That keeps every call cheap whatever the size of the data. Pass `deep=True` to check the items too, at every depth:

```python
@typecheck(deep=True)
def report(prices: dict[str, list[float]], window: tuple[int, int]) -> None: ...

report({"apple": [1.5, "n/a"], 3: [2.0]}, (1, 2, 3))
```

```
3 problems found in call:
    -> For introspected parameter prices at index ['apple'][1] of <Function report>: expected type: 'float', got type 'str' (Value: 'n/a')
    -> For introspected parameter prices at index [key 3] of <Function report>: expected type: 'str', got type 'int' (Value: 3)
    -> For parameter window of <Function report>: expected type: tuple[int, int] with 2 items, got 3 items (Value: (1, 2, 3))
```

`deep` works everywhere the other options do: `@typecheck(deep=True)`, `@enforce(deep=True)`, `@dataclass(deep=True)`, `typecheck_function(..., deep=True)`, `enforce_class(cls, deep=True)` and `typecheck_record({..., "deep": True})`.

What gets checked:

| Annotation | Checked |
|---|---|
| `list[T]`, `set[T]`, `frozenset[T]`, `deque[T]` | every item |
| `Sequence[T]`, `MutableSequence[T]`, `Set[T]`, `Collection[T]` | every item |
| `tuple[A, B]`, `tuple[()]` | each position, and the length |
| `tuple[T, ...]` | every item |
| `tuple[A, *tuple[T, ...], B]` | the fixed positions at both ends, every item between them, and that there are enough |
| `dict[K, V]`, `Mapping[K, V]`, `OrderedDict`, `defaultdict`, `Counter`, `ChainMap` | every key and every value |
| `TypedDict` | required keys are present (`Required` / `NotRequired` / `total=False` respected), and every value; extra keys are allowed |
| `NamedTuple` | every field |
| `X \| Y`, `Optional[X]` | any member, followed into nested collections |
| `Annotated`, `NewType`, `type` aliases, generic aliases (`Pair[int]`) | followed through |
| recursive aliases (`type Json = ... \| list[Json] \| dict[str, Json]`) | every level; data that contains itself is reported instead of recursing forever |
| `Iterable[T]`, `Iterator[T]`, `Generator` | outer type only: checking the items would consume them |

How it behaves:

- **Every bad item is reported**, each with a path: `[i]` for positions, `['key']` for values, `[key k]` for keys and `.field` for `NamedTuple` fields. The paths are also in `e.problems` (see [Structured errors](#structured-errors)).
- **Unions** report the errors of the member whose outer type fits, so `list[int] | None` given `[1, "a"]` reports `x[1]`, not "expected list or None".
- **Items are converted too.** With the default `convert=True`, `list[float]` turns `[1, 2]` into `[1.0, 2.0]`; with `coerce=True`, `list[int]` turns `("1", "2")` into `[1, 2]`. Conversion builds a **new** container of the same kind (a `deque` keeps its `maxlen`, a `defaultdict` its factory). The caller's object is never changed. Only items that can't be converted are reported.
- **The container type is never swapped.** A value whose items need converting but whose type can't hold the result is rejected, not replaced by a list: a `range`, a `dict` passed for a `Collection` of its keys, a `dict_keys` view, a read-only mapping proxy. The message says so: `invalid 'Collection[float]': its items need converting, but a range cannot be rebuilt with the converted items`. Values that need no conversion pass as they are, whatever their type.
- **Keys must stay distinct.** With `coerce=True`, `dict[int, str]` rejects `{"1": "a", 1: "b"}`: both keys become `1`, and an entry would be lost (`invalid 'dict[int, str]': keys '1' and 1 both convert to 1`).
- **Messages say where the item is** inside the parameter: `For introspected parameter prices at index ['apple'][1]`, `For introspected parameter point at field x`, `For default value of introspected parameter xs at index [1]`, `For introspected return value at index [0]`, and for dataclass assignments `Introspected field Order.lines at index [1][1]`. A problem with the parameter itself keeps the usual wording (`For parameter window`).
- **Defaults and return values** are checked the same way.
- **Valid data is passed through as is**, not copied.

Checking items costs time in proportion to the data, which is why it's opt-in. Items of plain classes are checked in a single C-level pass over their types rather than one Python call per item; see [Performance](#performance).

---

## Validated values

Some values need more than the right type: a port must be 1–65535, an email address needs one `@`. enforced has two ways to say that.

**A check in `Annotated`.** A check is a function that runs on the value once its type is right. It returns a truthy value to accept. It rejects by returning a falsy value, or by raising `ValueError`, `TypeError`, `ArithmeticError` or `LookupError`, whose message becomes the reason. Any other exception is a bug in the check and comes through as it is.

```python
from typing import Annotated
from enforced import Check, typecheck

PositiveInt = Annotated[int, Check(lambda x: x > 0)]    # Better for readability and explicitness
or
PositiveInt = Annotated[int, lambda x: x > 0]


@typecheck
def scale(factor: PositiveInt) -> int: ...

scale(-2)
# For parameter factor of <Function scale>: invalid 'int': failed check x > 0 (Value: -2)
```

`Check(fn)` marks the function as a check. The short form does the same without the marker: a callable written into the metadata as it is, `Annotated[int, lambda x: x > 0]`, is a check too. Both cost the same per call. The marker says what is meant, and it is the only way to make a class a check (`Check(bool)`): a class in the metadata, like a string or a number, is otherwise ignored.

A lambda is shown by its own source (`x > 0`) and a named function by its name. Checks apply only to their own member of a union (`PositiveInt | None` still accepts `None`), run after conversion (`Annotated[float, check]` sees `1.0` for `1`) and work inside collections with `deep=True`.

**A check never changes the value.** Every callable in the metadata is asked for a verdict, also one that was written to transform, such as `str.strip`: its result is read as yes or no, and an empty one rejects. The message then says what came back, so the mistake shows:

```
For parameter name of <Function greet>: invalid 'str': failed check strip, which returned '' (Value: '  ')
```

To normalise a value, use a `TypeModel`, whose `validate` returns the value to keep.

**A `TypeModel`.** A class that *is* its base type (an `Email` is a real `str`), validated once when it's built:

```python
from enforced import TypeModel

class Slug(TypeModel[str]):
    @classmethod
    def validate(cls, raw: str) -> str:          # return the normalised value, or raise ValueError(reason)
        raw = raw.strip().lower()
        if not raw.replace("-", "").isalnum():
            raise ValueError("only letters, digits and '-'")
        return raw
```

`TypeModel[str]` makes a `Slug` a `str`, when the program runs and for mypy and your editor alike.

Under the default `convert=True`, a raw value of the base type is built into the model: `Slug` given `" Hello-World "` receives `Slug("hello-world")`. With `coerce=True` the base type is parsed first (`Port` given `"8080"`). An existing instance passes through untouched, and set `auto_construct = False` on the class to accept only instances. The reason from `ValueError` is in the message:

```
For parameter s of <Function publish>: invalid 'Slug': only letters, digits and '-' (Value: 'a b')
```

The base can be `str`, `int`, `float`, `complex`, `bytes`, `Decimal` or `Fraction`. Instances are immutable, pickle by re-validating, and keep all of the base type's behaviour. They carry no `__dict__`: a model class gets `__slots__ = ()` by itself. One that needs a dictionary, for a `functools.cached_property` say, declares `__slots__ = ("__dict__",)`.

**Ready-made types** are in `enforced.data_types`: `Email`, `Port` (both `TypeModel`s) and `PositiveInt`, `NegativeInt`, `NonNegativeInt`, `Number` (`Annotated` with a `Check`). `Number` is a finite `float`: an `int` is converted, `nan` and the infinities are rejected.

Both kinds report problems of kind `"invalid"`, with the reason in `problem.detail`. Static type checkers don't know a `str` becomes an `Email`, so passing a raw `str` to an `Email` parameter is flagged by mypy and pyright. The `Annotated` form doesn't have that problem.

---

## Checking without a decorator

The decorators have a form without the `@`, for code you can't or don't want to decorate, and there is a third function for a call that only exists as data.

| You have | Use | It does |
|---|---|---|
| A function or a method | `typecheck_function(fn, args, kwargs)` | What `@typecheck` does for one call: checks it, and makes it |
| A class | `enforce_class(cls)` | What `@enforce` does: enforces the class, and returns it |
| Only a description | `typecheck_record(spec)` | Checks a call described by a dictionary |

### A function: `typecheck_function`

```python
from enforced import typecheck_function

def area(width: float, height: float = 1) -> float:    # someone else's function: not decorated
    return width * height

typecheck_function(area, (3, 4))                    # 12.0: checked, the ints converted, then called
typecheck_function(area, (3,), {"height": 2})       # 6.0
typecheck_function(area, ("3",))                    # TypeCheckerError: for <Function area>, and area never runs
```

It is `typecheck(area)(3, 4)` in one step: defaults are checked first, then binding, missing arguments and types, values are converted, the function is called and its result returned.

- **The arguments come as a tuple (or list) and a mapping**, so that the options have a place: `allow_subclass`, `check_return`, `convert`, `coerce` and `deep`, by keyword, meaning what they mean for `typecheck`.
- **The function itself is left as it is.** Calling it directly is still unchecked.
- **A bound method needs no `self`:** `typecheck_function(account.deposit, (5,))`. It is labelled `<Method Account.deposit>` and `Self` is checked.
- **Repeated calls are fast.** The checked function is remembered per set of options, so the second call already runs the compiled check. It is kept on the function itself (in its `__dict__`), and goes when the function goes: nothing is held for a function made in a loop and called once. For an object with `__call__`, a `functools.partial` or a builtin, which take no such note, the 512 used most recently are remembered.
- A class is refused, with a pointer to `enforce_class`.

### A class: `enforce_class`

```python
from enforced import enforce_class
from somewhere import Client                # a class that is already defined

enforce_class(Client, check_return=True)    # the same class comes back, enforced
Client(host=80)                             # TypeCheckerError: for <Class Client>
```

It is `@enforce(...)` applied after the fact: `__init__`, the methods the class defines and the special methods a caller hands values to are checked from then on, with the same options (given by keyword). Everything said under [Classes](#classes) holds.

- **The class is changed in place and returned**, so every user of it gets the checks, wherever they imported it from.
- **Calling it again changes nothing**: methods that are checked already are left alone.
- A dataclass and anything that isn't a class are refused, as by `@enforce`.

### A description: `typecheck_record`

`typecheck_record` checks a call described by a dictionary. This is useful when the "signature" only exists as data, such as a config, an API payload or a plugin interface.

```python
from enforced import typecheck_record

args, kwargs = typecheck_record({
    "object_name": "create_user",
    "record": {"name": str, "score": float},
    "kwargs": {"name": "Ana", "score": 7},
})
# kwargs == {"name": "Ana", "score": 7.0}
```

The dictionary you pass in is never modified.

| Key | Required | Meaning |
|---|---|---|
| `object_name` | yes | A callable, whose real signature is used and defaults are checked, or a string used as the name in messages. |
| `record` | yes | A mapping of parameter name to annotation. An annotation can also be a string, see below. |
| `args` | no | Positional arguments. |
| `kwargs` | no | Keyword arguments. |
| `allow_subclass` | no | Defaults to `True`. |
| `skip_first` | no | Treat the first parameter as `self`/`cls`. |
| `convert` | no | Defaults to `True`. |
| `coerce` | no | Defaults to `False`. |
| `deep` | no | Defaults to `False`. Check the items inside collections too. |

When `object_name` is a string, a signature is built from `record`. Every entry becomes a required positional-or-keyword parameter, in the order given. Unknown or missing spec keys raise a `TypeCheckerError`. Repeated calls with the same spec reuse a cached checker. The cache holds the 512 most recent specs and can be used from several threads at once. When `object_name` is a function, its checkers are kept on the function instead and go when it goes.

An annotation in `record` can be written as a string, so that a record can come from a JSON file or a request: `{"name": "str", "scores": "Optional[list[float]]", "mode": "Literal['r', 'w']"}`. Such a string may use:

- the names of built-in classes (`int`, `str`, `list`, `dict`, ...), subscripts, `|` and `None`;
- the usual annotation forms: `Any`, `Optional`, `Union`, `Literal`, `Sequence`, `Mapping`, `Iterable`, `Callable`, `List`, `Dict`, `Tuple`, `Set`, `deque`, `OrderedDict` and the like, also written with their module (`typing.Optional[int]`, `collections.abc.Mapping[str, int]`);
- the standard library's value classes: `datetime`, `date`, `time`, `timedelta`, `Decimal`, `Fraction`, `UUID`, `Path` and `PurePath`.

The string is parsed and read as data, never executed. A name outside this list, an attribute of anything, or a call raises a `TypeCheckerError` ("Cannot resolve annotation"). A value that is no annotation at all, such as a number or a list, raises one too ("is not a type annotation").

---

## Results instead of exceptions

`protect` awaits something for you and hands back what happened as a value: `Ok` with the result, or `Err` with the exception. It is a small helper next to the checks, for code that would rather branch on a result than wrap every `await` in `try`.

You can use structured pattern matching with `Ok` and `Err` to handle the given results conveniently:

```python
from enforced import protect, Ok, Err

match await protect(fetch(user_id)):
    case Ok(value):     # Value is the result of the cooroutine given back automatically on this branch
        print("Success:", value)
    case Err(error):    # Error is the exception raised by the coroutine given back automatically on this branch
        print("Error:", error)
```

- **It takes anything that can be awaited**: a coroutine, a task, a future, `asyncio.gather(...)`. Anything else is refused with a `TypeCheckerError`. `protect(fetch)` without the call is a mistake in the program, not a failure of the work, so it is not returned as an `Err`.
- **Only `Exception` is caught.** Cancellation (`asyncio.CancelledError`), `KeyboardInterrupt` and `SystemExit` go through as ever, so a protected task can still be cancelled. A timeout from `asyncio.wait_for` is an `Err`.
- **A `TypeCheckerError` raised by the work is an `Err` too**, like any exception of the awaited call.
- **`Ok` and `Err` are frozen dataclasses** of the standard library, with one field each, `value` and `error`. They compare, hash, pickle and work in a `match` statement. Nothing in them is checked: a result holds what `protect` put there, and making one costs about 75 ns.
- **Several at once:** `await asyncio.gather(*(protect(job) for job in jobs))` gives one result per job, where `gather` alone stops at the first exception.

An `Err` keeps its exception, and an exception keeps its traceback, which holds the frames it passed through and their local variables. Drop the result when you are done with it.

---

## Error messages

Errors are `TypeCheckerError`, a subclass of `TypeError`, so existing `except TypeError` handlers keep working. Messages are coloured in the terminal and shown plain here.

**Several problems in one call:**

```
2 problems found in call:
    -> For parameter x of <Dataclass Point>: expected type: 'float', got type 'str' (Value: 'one')
    -> For parameter y of <Dataclass Point>: expected type: 'float', got type 'str' (Value: 'two')
```

**Missing arguments:**

```
1 problem found in call:
    -> Missing required arguments for <Function add>: a (expecting type int), b (expecting type float)
```

**Shifted positional arguments.** If you forget the first arguments, Python fills the parameters from the left, and a naive checker would blame every parameter. enforced looks for the order-preserving placement that best fits the types:

```python
@typecheck
def f(a: int, b: float, c: str) -> None: ...

f("hello")
```

```
1 problem found in call:
    -> Missing required arguments for <Function f>: a (expecting type int), b (expecting type float) (inferred)
```

**Bad defaults:**

```
1 problem found in definition:
    -> For default value of parameter port of <Class Server>: expected type: 'int', got type 'str' (Value: '8080')
```

**Literal values and `type[X]`.** Where the runtime type would say nothing, the annotation itself is shown:

```
-> For parameter mode of <Function open_file>: expected type: Literal['r', 'w'], got type 'str' (Value: 'x')
-> For parameter kind of <Function build>: expected type: 'type[int]', got type 'type' (Value: <class 'str'>)
```

**A call that can't be made at all** is reported in the words Python itself uses, as a `TypeCheckerError` without problems: `too many positional arguments`, `multiple values for argument 'a'`, `got an unexpected keyword argument 'c'`.

Labels identify the target: `<Function f>`, `<Method Service.run>`, `<Class Box>` and `<Dataclass Point>`. Values are shown with a safe, truncated `repr`.

### Structured errors

Every error also carries its problems as data, so code can react without parsing text:

```python
try:
    create_user(name=1, age="x")
except TypeCheckerError as e:
    for p in e.problems:
        print(p.kind, p.parameter, p.expected, p.value)
    # type name <class 'str'> 1
    # type age <class 'int'> x
```

| Attribute | Meaning |
|---|---|
| `kind` | `"type"` (an argument), `"default"`, `"return"`, `"missing"`, `"field"` (a dataclass assignment) or `"invalid"` (the right type, but an `Annotated` check or a `TypeModel` rejected the value); with `deep=True` also `"length"` (a fixed-size tuple of the wrong length), `"missing_key"` (a required `TypedDict` key) and `"cycle"` (data that contains itself) |
| `parameter` | The parameter name (`"args[2]"` / `"kwargs[b]"` for varargs items); a tuple of names for `"missing"`. With `deep=True`, the path to the bad item: `"rows[3][1]"`, `"prices['apple']"`, `"point.x"`, `"return[0]"` |
| `expected` | The expected type; a tuple of annotations for `"missing"` |
| `annotation` | The annotation as it was written, where the problem is about one value: `Literal['r', 'w']` where `expected` is the type of those values (`str`) |
| `value` | The offending value (`None` for `"missing"` and `"missing_key"`) |
| `origin` | The function or class being checked |
| `detail` | The reason for `"invalid"`, the expected length for `"length"`, the key for `"missing_key"`; otherwise `None` |

`e.context` is `"call"`, `"definition"` or `"field assignment"`. `str(problem)` gives that problem's one-line message.

**An error survives pickling**, so it can cross a process boundary (`multiprocessing`, a task queue) with its problems, its context and its message. A part that can't be pickled, such as a value of a local class, arrives as a stand-in that shows its `repr`; `problem.origin` is found again by name.

### Message cost and colours

The message text is only built when the error is turned into a string, for example when it's printed or logged, and is then cached. Code that catches `TypeCheckerError` and moves on never pays for formatting.

Messages are coloured only when both standard streams are terminals. Redirect either one (`2> errors.log`, `| less`, a CI job) and they are plain, so no escape sequence lands in a file. The environment decides first, in this order:

| Variable | Effect |
|---|---|
| `ENFORCED_COLOURS_OFF=1` | Plain messages. |
| `NO_COLOR`, `ANSI_COLORS_DISABLED` (set to anything) | Plain messages. |
| `FORCE_COLOR` (set to anything) | Coloured messages, whatever the streams are. |
| `TERM=dumb` | Plain messages. |

The setting is read each time a message is built, so changing it takes effect at once. A coloured message costs a little more than a plain one (about 3 µs against 2 µs): the escape sequences of each style are worked out once, not once per word.

A message shows the start of the offending value, and only that much of it is formatted: a list of three million items costs no more to report than a short one.

---

## Supported annotations

| Annotation | Behaviour |
|---|---|
| `int`, `str`, `float`, `bool`, `bytes`, `complex`, any class | `isinstance` check, or an exact type match in strict mode |
| `int` and `True` / `False` | Rejected: `bool` subclasses `int`, but a bool is never accepted as an `int` (like pydantic's strict mode). Write `int \| bool` to allow both. Other `int` subclasses (`IntEnum`, ...) are accepted |
| `None` | Value must be `None` |
| `Any` | Accepts anything |
| `X \| Y`, `Union[X, Y]`, `Optional[X]` | Any member matches |
| `Literal[...]` | Value *and* type must match, so `Literal[1]` rejects `True` and `1.0` |
| `LiteralString` | A `str` (that it was written as a literal can't be seen at runtime) |
| `list[int]`, `dict[str, int]`, `tuple[...]`, `set[...]` | Outer container type only; every item, key, value and tuple length with `deep=True` |
| `Sequence`, `Mapping`, `Iterable`, `Iterator`, ... (`collections.abc`) | `isinstance` against the ABC, in strict mode too. As the typing rules have it, a `str` is a `Sequence[str]` and `bytes` a `Sequence[int]`: write `list[str]` where a lone string would be a mistake |
| `Callable[...]` | Value must be callable |
| `IO`, `TextIO`, `BinaryIO`, `IO[str]`, `IO[bytes]` | A file: what `open()` returns, `sys.stdout`, `io.StringIO`, any `io` class (gzip, sockets, ...), or an object with the methods of a file, such as a `tempfile.NamedTemporaryFile` or a `unittest.mock.Mock()`. Text and binary are told apart: `TextIO` and `IO[str]` reject `io.BytesIO()`, `BinaryIO` and `IO[bytes]` reject `sys.stdout`, and your own `class Log(IO[str])` is a text file. A path is not a file |
| `type[X]` | Value must be a class that subclasses `X` (or *is* `X`, or one of the members of `type[X \| Y]`, in strict mode). In a union it only speaks for classes: `type[X] \| None` accepts `None`, `type[X] \| str` any string. `type[TextIO]` takes a file class: an `io` class, one derived from `typing.IO`, any class that defines the methods of a file, or one that passes every name on through `__getattr__` |
| `Annotated[T, ...]` | Checked as `T`, then every check in the metadata runs on the value: each `Check(fn)`, and each callable written without the marker (see [Validated values](#validated-values)); other metadata is ignored |
| `Final[T]`, `ClassVar[T]`, `InitVar[T]` | Checked as `T` |
| `NewType` | Checked as its supertype |
| `TypeVar` | Checked against its bound or constraints, also when they are written as strings (`TypeVar("T", bound="Shape")`); unbounded accepts anything. With `deep=True` the items under a bound or a constraint are checked too |
| `type Alias = ...` (PEP 695) | Expanded, including nested and late-bound aliases |
| `"Forward"` references, and every annotation under `from __future__ import annotations` | Resolved on the first call, as Python would read the name where it is written: in the module, in the class (its own name and the type parameters of `class Box[T]`), and in the function the definition is local to. An unresolvable name raises `TypeCheckerError`, and is retried on the next call |
| Enums, `@runtime_checkable` Protocols | `isinstance`. A Protocol without `@runtime_checkable` can't be tested at runtime: calling the function raises a `TypeCheckerError` that says which Protocol to decorate |
| `NamedTuple` | `isinstance`; every field too with `deep=True` |
| `TypedDict` | Value must be a `dict`; required keys and value types too with `deep=True` |
| `Self` | The class of the instance the method is called on (for a class method, the class it is called on), in an `@enforce` class, a dataclass field and for a method with its own `@typecheck`, also inside an annotation (`Self \| None`, `list[Self]`, `type[Self]`). An instance of a subclass of that class is accepted; in strict mode only an instance of exactly that class. In a static method, which has neither, it is the class the method is written in |
| `**kwargs: Unpack[SomeTypedDict]` | Each key is checked like a keyword-only parameter: required keys, value types, conversion, and no other keyword |
| `*args: *tuple[int, str]` | The extra positional arguments, as that tuple: how many, and the type of each. With a run of unknown length, `*tuple[int, *tuple[str, ...]]`: the fixed ones and every argument of the run |
| `-> TypeGuard[X]`, `-> TypeIs[X]` | The function returns a `bool` (with `check_return=True`) |
| `Never` / `NoReturn` | Returning normally is an error (with `check_return=True`) |

---

## Options

| Option | Default | Applies to | Meaning |
|---|---|---|---|
| `allow_subclass` | `True` | all | When `False`, types must match exactly, so `Dog()` is rejected for `Animal` and an `IntEnum` member for `int`. (`True` is rejected for `int` either way.) A class that has no instances of exactly its own type is still matched with `isinstance`, or nothing would ever pass: an abstract class (`Sequence`, `Callable`, a Protocol, your own ABC with abstract methods), `numbers.Number`, `KeysView` and the other dict views, `pathlib.Path` and `PurePath` (a path is a `PosixPath` or a `WindowsPath`), `datetime.tzinfo`, an Enum base class without members (`enum.Enum`, `IntEnum`), and `type` (a class may have any metaclass). |
| `check_return` | `False` | `typecheck`, `enforce` | Also check the return value (of every method, for a class). It's opt-in because it adds a check after every call. |
| `convert` | `True` | all | Losslessly convert values that fail their check (`1` → `1.0`). |
| `coerce` | `False` | all | Also parse and narrow values (`"42"` → `42`). Includes `convert`. |
| `deep` | `False` | all | Also check the items inside collections, at every depth (see [Checking collection items](#checking-collection-items)). |
| `check_assignment` | `True` | `dataclass` | Validate field assignments after construction. |

All decorator forms work, for `enforce` too:

```python
@typecheck
@typecheck()
@typecheck(allow_subclass=False, check_return=True, coerce=True, deep=True)
```

| Environment variable | Meaning |
|---|---|
| `ENFORCED_COLOURS_OFF=1` | Plain, uncoloured error messages. `NO_COLOR` and `FORCE_COLOR` are honoured too (see [Message cost and colours](#message-cost-and-colours)). |
| `ENFORCED_TYPECHECK_OFF=1` | Switches every check off (see below). |
| `ENFORCED_COMPILE_AFTER=n` | After how many calls a function's check is compiled (default 64; see [Performance](#performance)). |

**Switching the checks off.** With `ENFORCED_TYPECHECK_OFF=1` in the environment, every API returns at once with what it was given:

| API | With the switch |
|---|---|
| `@typecheck`, `@enforce`, `enforce_class` | The function or class comes back exactly as it was written: nothing is wrapped, and a call costs what an undecorated one does. |
| `@dataclass` | A standard `dataclasses.dataclass` with the same options. |
| `typecheck_function(fn, args, kwargs)` | Calls `fn(*args, **kwargs)` and returns the result. |
| `typecheck_record(spec)` | Returns `(args, kwargs)` as they are in the spec. |

Nothing is checked and nothing is converted: `f(1)` for `x: float` receives `1`, and a string for a `Port` field stays a string. Code that relies on conversion behaves differently with the switch on, so it is for running a program you already trust at full speed, not for silencing an error. A `TypeModel` still validates when you build one yourself (`Email("a@b.co")`): that is the type's constructor, not a check.

The variable is read once, when `enforced` is first imported. Set it before the program starts; changing it afterwards has no effect, and a function decorated while the checks were on stays checked. Only the value `1` switches them off.

The names of all the variables enforced reads are members of `enforced.EnvVar`, a `StrEnum`: `os.environ[EnvVar.TYPECHECK_OFF] = "1"` (before the first import of anything else from the package), `EnvVar.COMPILE_AFTER`, `EnvVar.COLOURS_OFF`, `EnvVar.NO_COLOR`, `EnvVar.ANSI_COLORS_DISABLED`, `EnvVar.FORCE_COLOR`, `EnvVar.TERM`.

---

## Performance

Checks are compiled, not interpreted. When a function has been called often enough, enforced generates a small wrapper specialised to its exact signature. That wrapper has one inlined `isinstance` test per parameter, and it replaces the decorated function's code. After that, a valid call does no signature binding, no dictionary building and no per-parameter function calls. Anything unusual, such as a wrong type, a missing argument or an odd call shape, falls back to the general path, which produces the detailed errors.

**Tiered compilation.** Until then a function runs on that general path, which checks a call step by step. The first call resolves the annotations and validates the defaults; the wrapper is compiled at the 64th call. Compiling costs 15 µs when a function of the same shape has been compiled before and 0.2 to 0.9 ms when none has, while a call on the general path costs 0.2 to 0.5 µs more than a compiled one. So a function that is called a handful of times never pays for a wrapper, and a function that runs hot gets one almost at once. A program that decorated 400 functions and called each three times spent 33 ms doing so before, and spends 14 ms now.

A dataclass is tiered the same way. Defining one compiles nothing. Its first 63 constructions run the standard `__init__` behind the general check, and its first 63 field assignments are tested one field at a time; after that the class gets the `__init__` that stores checked arguments directly, and one generated function for all its assignments. Defining a class with six fields and constructing it once took 0.58 ms, and takes 0.33 ms.

`ENFORCED_COMPILE_AFTER=n` changes the number; `1` compiles at the first call. Results and errors are the same on both paths. When timing a function or a dataclass, use it at least 64 times first, or the measurement is of the general path.

Typical costs on CPython 3.14 (AMD Ryzen 9 9900X):

| | Cost |
|---|---|
| Checked call, overhead | about 40 ns + 8.5 ns per parameter |
| Checked call, 2 parameters, positional | 0.07 µs |
| Checked call, 12 parameters, positional | 0.17 µs |
| Dataclass field assignment | 0.06 µs |
| Converting `int` → `float` for two arguments | about 0.4 µs |
| A call before its wrapper is compiled (the first 63) | 0.25 µs for 1 parameter, 0.8 µs for 12 |
| Constructing a dataclass | about 0.33 µs for 3 fields, 0.41 µs for 6 |
| Constructing a dataclass before its checks are compiled (the first 63) | about 1.1 µs for 3 fields, 1.8 µs for 6 |
| Assigning a dataclass field before the check is compiled (the first 63) | about 0.2 µs |
| Raising and catching one type error | about 0.6 µs |
| Raising and catching a wrong return value, or a wrong dataclass assignment | about 0.45 µs |
| Raising and catching a call that can't be bound (an argument too many, an unknown keyword) | about 0.7 µs |
| Raising and catching a missing argument | about 0.55 µs |
| Raising and catching a value that fails an `Annotated` check, or a `TypeModel`'s `validate` | about 1 µs plus the check itself, which runs twice (`validate`: once) |
| Printing that error (`str(e)`) | about 2.5 µs plain, 4 µs coloured |
| `typecheck_function(fn, args)`, a repeated call | about 0.15 µs more than calling the decorated function |
| `await protect(...)` | about 0.5 µs when the awaitable completes, 0.7 µs when it raises |
| A method that takes or returns `Self` | about 10 ns more than without, 20 ns when called on a subclass. Where `Self` is part of an annotation (`Self \| None`) or the method is a class method, a call on a subclass goes through a wrapper of its own: about 90 ns more |
| Decorating a function | under 10 µs |
| First call (annotations resolved, defaults validated) | about 25 µs for 2 parameters |
| Compiling the wrapper, at the 64th call | 15 µs for a shape seen before; 0.2 ms for a new one with 2 parameters, 0.9 ms with 12 |

With `deep=True`, each annotation with items to check is compiled once into a small generated check (`isinstance(v, list) and <one pass over the item types>`). Parameters without collections cost exactly the same as without `deep`. Measured on a slower machine than the table above (run `tests/benchmark.py` for yours):

| `deep=True` | Cost |
|---|---|
| `list[int]` × 10 | 0.3 µs |
| `list[int]` × 1,000 | 9 µs (about 9 ns per item) |
| `dict[str, int]` × 100 | 2.4 µs |
| `dict[str, list[int]]`, 10 × 10 | 2.2 µs |
| `tuple[int, str, float]` | 0.18 µs |
| Converting `list[float]` × 1,000 from ints | about 70 µs |
| Raising for one bad item among 1,000 | about 50 µs |

Functions with the same signature shape share one compiled code object, so the first-call cost falls as more functions are decorated. To see the code enforced generated for a function, look at `fn.__enforced_source__` after its first call.

`tests/benchmark.py` in the repository benchmarks every case and prints a coverage report. Add `--report results.md` to also save the tables as a Markdown file.

---

## Limitations

enforced checks the *shape* of values, not their full structure. In particular:

- **Container contents are only checked with `deep=True`.** By default `list[int]` accepts `["a", "b"]`; see [Checking collection items](#checking-collection-items).
- **`Iterable`, `Iterator` and `Generator` items are never checked**, even with `deep=True`, because checking would consume them.
- **`Callable` signatures aren't checked.** `Callable[[int], str]` accepts any callable.
- **Generic `TypedDict` and `NamedTuple` classes** (`class Box[T](TypedDict)`) are only checked as a `dict` / tuple, even with `deep=True`.
- **Very deep nesting** (hundreds of levels, with `deep=True`) is reported as `"cycle"`: Python's recursion limit is the bound.
- **Generator yields aren't checked.** Only the arguments, and the generator object itself if `check_return` is on.
- **A local name that comes after the decorator** is found: in a string annotation (every annotation is one under `from __future__ import annotations`), a class local to a function may be defined below the function or class that names it. enforced reads such a name at the moment the enclosing function returns, and keeps nothing of that function alive to do so. For this it takes one of the `sys.monitoring` tool ids that no kind of tool is assigned (4, or 3), the first time such a name is met. Two edges: where both ids are taken, and where the enclosing function is left by an exception, the name is only found while that function is still running.
- **`@enforce` checks calls, not attributes.** `self.x = "a"` is not checked against a class-level `x: int`, and operators and comparisons are left alone (see [Classes](#classes) for the special methods and properties that are checked). Fields that should be checked on assignment belong in a `@dataclass`.
- **A value changed in place is not checked.** `order.tags.append(5)` goes through no check: a dataclass checks assignments, and `append` is none.
- **`@dataclasses.dataclass` written above `@enforce`** generates its `__init__` after `enforce` has run, so that `__init__` is unchecked. Use enforced's `@dataclass`.
- **`x: int = None` is rejected.** Implicit `Optional` was removed from the typing spec, so write `x: int | None = None`.
- **A file-like object of an unknown class is judged by its methods**: reading, writing, positioning and closing, not `with` support. For `TextIO` / `BinaryIO` it counts as text when it has an `encoding`. An object with only `write()` is not a file: annotate that with a Protocol. A `unittest.mock.Mock()` answers every one of those names and is taken for a file of either kind; `Mock(spec=io.BytesIO)` is a binary one.
- **`type[TextIO]` can only go by what a class shows.** A class that sets its `encoding` in `__init__`, or has it as a property, is taken for either kind of file. So is a class that answers names through `__getattr__`, such as the wrapper `tempfile.NamedTemporaryFile` returns or a `Mock`: what its instances have can't be read off the class at all.
- **Protocols must be `@runtime_checkable`** to be used as annotations; otherwise every call raises a `TypeCheckerError` naming the Protocol.
- **A function's first 63 calls are slower than its later ones**, by 0.2 to 0.5 µs each: its wrapper is compiled at the 64th (see [Performance](#performance)). A dataclass's first 63 constructions cost about 0.8 µs more each, and check each argument twice. `ENFORCED_COMPILE_AFTER=1` compiles at the first call, which costs up to about 1 ms per function.
- **Errors hold references to the offending values.** The message is built later, so a value mutated between raising and printing appears as it is when printed. The `Problem` objects of a wrong call are made when `e.problems` is first read, from what the check found when it ran: which arguments failed is settled at the call, and never changes afterwards.

## Roadmap

- **More validated types**, such as `Url`, and constraint markers (`Gt`, `MaxLen`, `Match`) next to `Check`, as an alternative to lambdas.
- **Faster error messages**: raising and catching a wrong argument takes 0.6 µs, but printing it (`str(e)`) takes another 2.5 to 4 µs.

---

## Running the tests

```bash
pip install -e ".[dev]"                 # pytest, and mypy for the static-typing tests (skipped without it)
bash run_tests.sh                       # unit tests; add --simulation for the scenario run
```

`run_tests.sh` ends with pytest's own exit status, so a failing test fails the script (and a hook or CI job built on it).

To check that a change to the package alters nothing it shouldn't, `tests/fuzz.py` runs the same random annotations and values through a previous copy and through the working tree, and lists every outcome that differs:

```bash
python tests/fuzz.py --save-baseline    # before the change: keep a copy of the package
python tests/fuzz.py                    # after it: compare the copy with the working tree
python tests/fuzz.py --ref HEAD         # or compare with a git revision
python tests/fuzz.py --properties       # no copy needed: checks what must hold in any version
```
