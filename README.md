<div align="center">

# enforced

**Runtime type checking for Python, from the annotations you already write.**

![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-3776ab)
![No dependencies](https://img.shields.io/badge/dependencies-none-2ea44f)
![Typed](https://img.shields.io/badge/typed-mypy%20%7C%20pyright-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

</div>

```python
from enforced import typecheck

@typecheck
def greet(name: str, times: int = 1) -> str:
    return f"Hello, {name}! " * times

greet("Ana", 2)      # 'Hello, Ana! Hello, Ana! '
greet("Ana", "2")    # TypeCheckerError
```

```
TypeCheckerError: 1 problem found in call:
    -> For parameter times of <Function greet>: expected type: 'int', got type 'str' (Value: '2')
```

No models, no schemas, no new syntax: decorate a function, a class or a dataclass, and its type hints are checked on every call.

enforced takes [beartype](https://github.com/beartype/beartype)'s approach, checking the hints your code already has, and adds what [pydantic](https://github.com/pydantic/pydantic) users rely on: conversion, validated values and structured errors. See [how they compare](#enforced-beartype-and-pydantic).

- ⚡ **Fast.** A checked call costs about 40 ns plus 8 ns per parameter, less than a third of what pydantic's `validate_call` costs.
- 🎯 **Strict by default.** `"2"` never quietly becomes `2`, and `True` is not an `int`. Parsing is opt-in.
- 📋 **Every problem at once.** One error lists every bad argument, not just the first.
- 🔍 **Deep when you ask.** `deep=True` checks every item of `list[int]`, `dict[str, list[float]]`, `TypedDict` ..., and points at the bad one.
- 🧩 **Drop-in dataclass.** Swap `from dataclasses import dataclass` for `from enforced import dataclass`.
- 📦 **No dependencies**, and fully typed for mypy, pyright and your editor.

## Contents

[Compared](#enforced-beartype-and-pydantic) · [Install](#install) · [Functions](#functions) · [Classes](#classes) · [Dataclasses](#dataclasses) · [Validated values](#validated-values) · [Conversion](#conversion-and-coercion) · [Collections](#checking-collection-items) · [Errors](#errors) · [Warnings](#warnings-instead-of-errors) · [Without a decorator](#without-a-decorator) · [Results](#results-instead-of-exceptions) · [Options](#options) · [Performance](#performance) · [Limitations](#limitations)

---

## enforced, beartype and pydantic

**beartype** checks the type hints of your own code when it is called, and nothing more: no models, no
conversion. **pydantic** parses data into models, with schemas and serialization. **enforced** works the
way beartype does, on the functions, classes and dataclasses you already have, and brings the parts of
pydantic that fit that model: conversion, validated values, every problem reported, errors as data.

| | beartype | enforced | pydantic |
|---|---|---|---|
| What you write | decorate your code, or a whole package at import (`beartype.claw`) | decorate your code | models (`BaseModel`), or `validate_call` |
| `1` for a `float` | refused, unless you opt in | accepted, stored as `1.0` | accepted, `1.0` |
| `True` for an `int` | accepted | refused | accepted (lax mode) |
| `"42"` for an `int` | refused | refused; `coerce=True` parses it | parsed (lax mode) |
| Items of a `list[int]` | one random item per call | none by default; every item with `deep=True` | every item |
| A value's own rules | `Annotated[int, Is[...]]` | `Annotated[int, Check(...)]`, and `TypeModel` to normalise | `Field(...)`, validators |
| Dataclass fields | checked on construction | on construction and assignment | `pydantic.dataclasses`, `validate_assignment` |
| Errors | the first problem | every problem, as data or JSON | every problem, as data or JSON |
| Parsing, schemas, serialization | – | – | ✓ |
| Valid calls, this repo's benchmark | 1.22× enforced's time | – | 2.63× enforced's time |
| Raising an error | 16.6× enforced's time | – | 1.3× faster than enforced |

The timings are geometric means over the cases where the libraries do the same work (`python tests/benchmark.py --quick` on Python 3.14, beartype 0.23, pydantic 2.14). beartype stays as fast for a list of a million items, since it looks at one; enforced with `deep=True` looks at every one.

Choose **beartype** for the widest coverage of the typing spec at the lowest cost, **pydantic** for data that arrives as JSON and must be parsed, documented and serialized, and **enforced** to check your own code strictly, with conversion and errors you can return to a client.

---

## Install

```bash
pip install .            # from the repository root; Python 3.14+
```

## Functions

```python
from enforced import typecheck

@typecheck(check_return=True)
def area(width: float, height: float) -> float:
    return width * height

area(3, 4)          # 12.0: ints are accepted for float, and converted
area("3", None)     # TypeCheckerError, naming both arguments
```

Each call is checked for defaults (once), binding, missing arguments, every argument's type and, with `check_return=True`, the return value. Every kind of parameter works:

```python
@typecheck
def log(level: int, *parts: str, sep: str = " ", **tags: str) -> None: ...

log(1, "a", "b", 3)       # -> For parameter parts[2] ...: expected type: 'str', got type 'int'
```

`**kwargs: Unpack[SomeTypedDict]` checks each keyword like a parameter, and `*args: *tuple[int, str]` checks the extra arguments as that tuple.

- **Async functions:** arguments are checked when the coroutine is awaited; `check_return` checks the awaited result.
- **Generators:** arguments are checked at the call; yielded values aren't. `inspect.isgeneratorfunction` still says yes.
- **Other callables:** an object with `__call__`, a `functools.partial` or a function under `functools.wraps` is checked against the function it calls.
- **Opting out:** `typing.no_type_check` above or below `@typecheck` leaves the function unchecked.

## Classes

`@enforce` checks `__init__`, every method, static method and class method the class defines, and property setters:

```python
from typing import Self
from enforced import enforce

@enforce(check_return=True)
class Account:
    def __init__(self, owner: str, balance: float = 0) -> None:
        self.owner, self.balance = owner, balance

    def deposit(self, amount: float) -> Self:
        self.balance += amount
        return self

    @enforce.exempt                  # left exactly as written
    def dump(self, sink) -> None:
        print(self.owner, self.balance, file=sink)

Account("Ana").deposit(10)          # fine: 10 arrives as 10.0
Account(42)                         # TypeCheckerError: for <Class Account>
Account("Ana").deposit("lots")      # TypeCheckerError: for <Method Account.deposit>
```

- **`Self`** is the class the method is called on, so an inherited method follows the subclass.
- **Special methods** a caller hands values to are checked: `__call__`, `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`, `__new__`. Those Python calls itself (`__eq__`, `__add__`, `__repr__` ...) are left alone, so `account == "x"` stays `False`.
- **A method with its own `@typecheck(...)`** keeps its own options.
- **A method without annotations** stays the plain function and costs nothing.
- `@typecheck` also works on a single method of any class, above or below `@classmethod`, `@staticmethod` and `@property`.

| You have | Use |
|---|---|
| A function or one method | `@typecheck` |
| A class | `@enforce` |
| A dataclass | `@dataclass` (enforced's) |

Each one refuses the others' targets, with a message that names the right decorator.

## Dataclasses

`enforced.dataclass` takes every argument of the standard one, and checks construction, defaults, assignment and the class's methods:

```python
from enforced import dataclass, field

@dataclass
class Order:
    item: str
    qty: int
    price: float = 0                  # stored as 0.0
    tags: list[str] = field(default_factory=list)

order = Order("pen", 3, 2)            # price stored as 2.0
Order("pen", "3")                     # TypeCheckerError: construction
order.qty = "many"                    # TypeCheckerError: assignment, old value kept
order.price = 5                       # stored as 5.0
```

```
1 problem found in field assignment:
    -> Field Order.qty of <Dataclass Order>: expected type: 'int', got type 'str' (Value: 'many')
```

Its own options: `allow_subclass`, `check_assignment`, `convert`, `coerce`, `deep`, `on_error`, `check_methods` (on by default) and `check_return`. Each argument is checked once per construction, `default_factory` results and `__post_init__` assignments are checked too, and `frozen`, `slots`, `kw_only`, `InitVar` and `dataclasses.replace()` work as usual.

**Made at run time.** `make_dataclass` is the standard function with enforced's checks, and takes the same options:

```python
from enforced import field, make_dataclass

Point = make_dataclass("Point", [("x", float), ("y", float, field(default=0))], frozen=True)
Point(1)          # Point(x=1.0, y=0.0)
Point("a")        # TypeCheckerError
```

## Validated values

When the type isn't enough, add a check with `Annotated`:

```python
from typing import Annotated
from enforced import Check, typecheck

Positive = Annotated[int, Check(lambda x: x > 0)]       # or just: Annotated[int, lambda x: x > 0]

@typecheck
def scale(factor: Positive) -> int: ...

scale(-2)
# -> For parameter factor of <Function scale>: invalid 'int': failed check x > 0 (Value: -2)
```

A check returns a truthy value to accept, and rejects by returning a falsy one or raising `ValueError` (its message becomes the reason). Checks never change the value.

To validate **and** normalise, write a `TypeModel`. An instance *is* its base type, both at runtime and for type checkers:

```python
from enforced import TypeModel

class Username(TypeModel[str]):
    @classmethod
    def validate(cls, raw: str) -> str:
        name = raw.strip().lower()
        if not name.isalnum():
            raise ValueError("letters and digits only")
        return name

@typecheck
def register(user: Username) -> None: ...

register(" Ana99 ")      # user == Username('ana99'), a str
register("a b")
# -> For parameter user of <Function register>: invalid 'Username': letters and digits only (Value: 'a b')
```

### Ready-made types

From `enforced.data_types`:

| Type | Accepts | Stored as |
|---|---|---|
| `Email` | `name@example.com` | domain lower-cased |
| `Url` | `http`/`https` with any host: a name, `localhost`, IPv4, `[IPv6]` | scheme and host lower-cased; `.host`, `.port`, `.path`, `.query`, `.fragment` |
| `Slug` | `my-post-2` | stripped and lower-cased |
| `PhoneNumber` | E.164: `+44 20 7946 0958` | `+442079460958` |
| `SecretStr` | any text | shown as `'**********'`; `.get_secret_value()` returns it |
| `Port` | 1 to 65535 | `.is_system`, `.is_registered`, `.is_ephemeral` |
| `NonEmptyStr` | text that isn't blank | as given |
| `AwareDatetime` | a `datetime` with a time zone | as given |
| `Probability`, `Percentage` | 0–1, 0–100 | `float` |
| `Number` | a finite number | `float` |
| `PositiveInt`, `NegativeInt`, `NonNegativeInt` | what the name says | `int` |

```python
from enforced.data_types import Url, SecretStr

url = Url(" HTTPS://Shop.Example:8443/items?page=2 ")
url, url.host, url.port         # Url('https://shop.example:8443/items?page=2'), 'shop.example', 8443
Url("https://good.example@evil.example")   # ValueError: must not contain a user name or password

@dataclass
class Login:
    user: str
    password: SecretStr

Login("ana", "hunter2")         # Login(user='ana', password=SecretStr('**********'))
```

`SecretStr` keeps the text out of reprs, `print`, logging and error messages, but it is still a `str`: code that reads its characters (`==`, `.encode()`, a driver) gets the real text. `str(secret)` gives the mask, so use `get_secret_value()` where the text is needed.

## Conversion and coercion

Only values that fail their check are ever touched.

- **Conversion** (`convert=True`, the default) is lossless: `int` → `float` (when exact) and `int`/`float` → `complex`. A `bool` is never a number.
- **Coercion** (`coerce=True`, off by default) parses as well, like pydantic's lax mode:

```python
from enum import Enum

class Mode(Enum):
    FAST = "fast"
    SAFE = "safe"

@typecheck(coerce=True)
def configure(port: int, debug: bool, mode: Mode) -> None: ...

configure("8080", "yes", "fast")    # port=8080, debug=True, mode=Mode.FAST
configure("80.5", "yes", "fast")    # TypeCheckerError: "80.5" is no whole number
```

<details>
<summary>What coercion converts</summary>

| From | To | Example |
|---|---|---|
| `str` | `int`, `float`, `complex` | `" -7 "` → `-7`, `"1e3"` → `1000.0` |
| `str` | `bool` | `true/false`, `yes/no`, `on/off`, `t/f`, `y/n`, `1/0` |
| `int`, `float` | `bool` | `0` and `1` only |
| `float` | `int` | whole numbers only: `3.0` → `3` |
| `str` ↔ `bytes` | | UTF-8 |
| a value | an `Enum` member | `"red"` → `Color.RED` |
| `list`, `tuple`, `set`, `frozenset` | each other | `(1, 2)` → `[1, 2]` |
| `str` | `datetime`, `date`, `time` | ISO 8601 |
| `str` | `Decimal`, `Fraction`, `UUID`, `Path` | `"1.10"` → `Decimal("1.10")` |

In a union, conversions are tried before coercions, members in the order written. Defaults are converted too (`x: float = 0` gives `0.0`). Return values are converted but never coerced: a function that returns `"42"` for `-> int` has a bug.

</details>

## Checking collection items

By default only the container is checked, so `list[int]` accepts `["a"]` and a call stays cheap whatever the data. Add `deep=True` to check every item, at every depth:

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

It covers lists, sets, tuples, dicts and the `collections.abc` types, `TypedDict`, `NamedTuple`, unions and recursive aliases (`type Json = ... | list[Json]`). Items are converted into a **new** container of the same kind; the caller's object is never changed. Iterators and generators are never consumed.

## Errors

A `TypeCheckerError` is a `TypeError`. It lists every problem, coloured in a terminal:

```
2 problems found in call:
    -> For parameter x of <Dataclass Point>: expected type: 'float', got type 'str' (Value: 'one')
    -> For parameter y of <Dataclass Point>: expected type: 'float', got type 'str' (Value: 'two')
```

It says which arguments were left out, and works out which ones you skipped when the rest have shifted:

```python
@typecheck
def f(a: int, b: float, c: str) -> None: ...

f("hello")
# -> Missing required arguments for <Function f>: a (expecting type int), b (expecting type float) (inferred)
```

The problems are also data, for code that reacts to them (an API returning a 422, say):

```python
@typecheck
def create_user(name: str, age: int) -> None: ...

try:
    create_user(name=1, age="x")
except TypeCheckerError as e:
    for p in e.problems:
        print(p.kind, p.parameter, p.expected, p.value)
# type name <class 'str'> 1
# type age <class 'int'> x
```

A problem has `kind` (`type`, `missing`, `default`, `return`, `field`, `invalid` ...), `parameter` (a path like `rows[3][1]` with `deep`), `expected`, `value`, `origin` and `detail` (the reason for `invalid`). The text is only built when the error is printed, and errors pickle with their problems.

**As JSON**, in pydantic's shape, for an API response:

```python
@typecheck(deep=True)
def order(customer: Email, lines: list[dict[str, int]]) -> None: ...

try:
    order("nope", [{"pen": 1}, {"ink": "two"}])
except TypeCheckerError as e:
    body = e.json()        # or e.errors(): the same as a list of dicts
```

```json
[
  {"type": "invalid", "loc": ["customer"], "msg": "invalid 'Email': must contain exactly one '@'",
   "input": "nope", "ctx": {"expected": "Email", "reason": "must contain exactly one '@'", "origin": "Function order", "context": "call"}},
  {"type": "type", "loc": ["lines", 1, "ink"], "msg": "expected type: 'int', got type 'str'",
   "input": "two", "ctx": {"expected": "int", "origin": "Function order", "context": "call"}}
]
```

`type` is the problem's `kind`, `loc` the path as a list (a wrong key ends in `"[key]"`), and every value is JSON-safe (bounded, `nan` as text). A missing argument is one entry per name, and a call that can't be bound is one entry of type `"binding"`. **The input is echoed, as in pydantic:** pass `include_input=False` where it may be sensitive. A `SecretStr` is always masked. `include_context=False` leaves out `ctx`.

## Warnings instead of errors

Adding enforced to code that already runs? Start with `on_error="warn"`: what fails is reported as a `TypeCheckerWarning`, and the call goes ahead.

```python
@typecheck(on_error="warn")
def label(n: int) -> str:
    return f"#{n}"

label("7")          # warns, then returns '#7'
```

```
app.py:5: TypeCheckerWarning: 1 problem found in call:
    -> For parameter n of <Function label>: expected type: 'int', got type 'str' (Value: '7')
```

Every API takes it. The warning points at your line, `warning.error` is the error, and the usual filters apply (`warnings.simplefilter("error", TypeCheckerWarning)` to make it an error after all). A call that can't be made at all (a missing argument) is still raised.

## Without a decorator

| You have | Use |
|---|---|
| A function you can't decorate | `typecheck_function(fn, args, kwargs)`: checks the call, then makes it |
| A class that is already defined | `enforce_class(cls)`: enforces it in place |
| A call described by data | `typecheck_record(spec)`: checks it and returns `(args, kwargs)` |

```python
from enforced import typecheck_function, typecheck_record

def area(width: float, height: float) -> float:      # not decorated
    return width * height

typecheck_function(area, (3, 4))        # 12.0, the ints converted
typecheck_function(area, ("3", 4))      # TypeCheckerError, and area never runs

args, kwargs = typecheck_record({
    "object_name": "create_user",
    "record": {"name": "str", "score": "float | None"},    # annotations may be strings, e.g. from JSON
    "kwargs": {"name": "Ana", "score": 7},
})
kwargs                                   # {'name': 'Ana', 'score': 7.0}
```

A string annotation in a record is parsed, never executed: only built-in classes, the usual `typing` forms and the standard value classes (`datetime`, `Decimal`, `UUID`, `Path` ...) are allowed in it.

## Results instead of exceptions

`protect` awaits something and gives back `Ok(value)` or `Err(error)`, ready for `match`:

```python
from enforced import protect, Ok, Err

match await protect(fetch(user_id)):
    case Ok(user):
        print("got", user)
    case Err(error):
        print("failed:", error)
```

Only `Exception` is caught: cancellation and `KeyboardInterrupt` go through. `await asyncio.gather(*(protect(job) for job in jobs))` gives one result per job.

## Options

| Option | Default | Meaning |
|---|---|---|
| `allow_subclass` | `True` | `False`: the exact type only (`Dog()` is no `Animal`) |
| `check_return` | `False` | Also check the return value |
| `convert` | `True` | Lossless conversion (`1` → `1.0`) |
| `coerce` | `False` | Also parse (`"42"` → `42`) |
| `deep` | `False` | Check items inside collections |
| `on_error` | `"raise"` | `"warn"`: warn and go ahead |
| `check_assignment` | `True` | Dataclasses: check `obj.field = value` |
| `check_methods` | `True` | Dataclasses: check the class's methods |

`@typecheck`, `@typecheck()` and `@typecheck(coerce=True, ...)` all work, for `@enforce` too.

**Switches.** Set in the environment, or from code:

| Environment | From code | Effect |
|---|---|---|
| `ENFORCED_TYPECHECK_OFF=1` | `turn_typecheck_off()` / `turn_typecheck_on()` | Every API hands back what it was given: no checks, no cost |
| `ENFORCED_COMPILE_AFTER=n` | `set_compile_after(n)` | Compile a function's check after `n` calls (default 64) |
| `ENFORCED_COLOURS_OFF=1` | `turn_colours_off()` / `turn_colours_on()` | Plain messages (`NO_COLOR` and `FORCE_COLOR` are honoured too) |

From code, the off switch applies to what is decorated **after** it, so call it before importing your modules.

## Performance

A function that has been called 64 times gets a wrapper generated for its exact signature: one inlined `isinstance` per parameter, nothing else on a valid call. Until then it runs on the general path, so code that is called a few times never pays to compile.

| CPython 3.14, Ryzen 9 9900X | Cost |
|---|---|
| Checked call | about 40 ns + 8.5 ns per parameter |
| Dataclass construction, 6 fields | 0.41 µs |
| Dataclass field assignment | 0.06 µs |
| Raising and catching a type error | about 0.6 µs |
| Printing that error | about 1.7 µs |
| `deep=True`, `list[int]` × 1,000 | about 9 µs |

In example FastAPI and Flask apps, served over HTTP, enforced and pydantic handle the same number of requests per second (within 2%). Run `python tests/benchmark.py --quick` for a comparison with pydantic, beartype, typeguard and attrs on your machine.

## Limitations

- Items of a collection are checked only with `deep=True`, and those of iterators and generators never.
- `Callable[[int], str]` accepts any callable: signatures aren't compared.
- `@enforce` checks calls, not attributes: `self.x = "a"` isn't checked. Use a dataclass for that.
- A value changed in place (`order.tags.append(5)`) isn't checked.
- A Protocol must be `@runtime_checkable` to be used as an annotation.
- `x: int = None` is refused: write `x: int | None = None`.
- Type checkers don't know about conversion: passing `"a@b.co"` to an `Email` parameter works at runtime but is flagged by mypy. Write `Email("a@b.co")`, or annotate with `Annotated`.
- A function's first 63 calls are 0.2 to 0.5 µs slower than later ones, before its wrapper is compiled.
- pydantic doesn't know enforced's types. In a pydantic model, an `Annotated` check (`Check(...)`, a bare lambda, `PositiveInt`) is ignored without a word, so `-1` passes, and a `TypeModel` such as `Email` is refused when the model is defined. Validate those values with enforced, or give pydantic its own validator.

## Development

```bash
pip install -e ".[dev]"          # pytest and mypy
bash run_tests.sh                # unit tests; --simulation for the scenario run
python tests/fuzz.py --ref HEAD  # differential fuzz against a git revision
```

MIT licence.
