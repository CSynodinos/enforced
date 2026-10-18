# enforced comparison

*2026-10-18 11:15*

CPython 3.14.4 (GIL) · Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43  
AMD Ryzen 9 9900X 12-Core Processor · 24 CPUs  
timing: 9 interleaved rounds × ≥30 ms per library per case, median reported, GC off  

| library | version | what is measured |
|:--|:--|:--|
| plain | - | no checks: undecorated function / stdlib dataclass |
| enforced | 1.0.0 | @typecheck / enforced.dataclass, defaults (convert on, coerce off) |
| enf.coerce | 1.0.0 | enforced with coerce=True (parses '42' -> 42, like pydantic lax) |
| enf.deep | 1.0.0 | enforced with deep=True (checks every item inside collections, like pydantic) |
| pydantic | 2.14.0 | validate_call / pydantic dataclass, default lax mode (coerces) |
| pyd.strict | 2.14.0 | validate_call / pydantic dataclass, strict=True (no coercion) |
| pyd.model | 2.14.0 | pydantic BaseModel (validate_assignment=True), classes only |
| beartype | 0.23.0 | @beartype (O(1): checks one random item per collection) |
| typeguard | 4.6.0 | @typechecked (default: checks the first item of collections) |
| attrs | 26.1.0 | attrs with explicit validators (validated on init and setattr), classes only |

## Coverage

*what each library does with each input (25 trials each)*

| input | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| int ← 'abc'  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| int ← '1' (coercible string)  (should reject) | ✓ catches | \~ coerces | ✓ catches | \~ coerces | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| int ← True (bool subclasses int)  (should reject) | ✓ catches | ✓ catches | ✓ catches | \~ coerces | ✓ catches | n/a | ✗ misses | ✗ misses | n/a |
| float ← 1 (PEP 484 numeric tower)  (should accept) | \~ converts | \~ converts | \~ converts | \~ converts | \~ converts | n/a | ✗ rejects | ✓ accepts | n/a |
| float ← 1 with convert=False  (should reject) | ✓ catches | \~ coerces | ✓ catches | n/a | n/a | n/a | n/a | n/a | n/a |
| int \| None ← None  (should accept) | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | n/a | ✓ accepts | ✓ accepts | n/a |
| Literal['r', 'w'] ← 'x'  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| type[Animal] ← int  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| type[Animal] \| None ← None  (should accept) | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | n/a | ✓ accepts | ✓ accepts | n/a |
| tuple[int, str] ← (1, 2)  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| tuple[int, str] ← (1, 'a', 2) (too long)  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| list[int], bad first of 1,000  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✓ catches | n/a |
| list[int], bad last of 1,000  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✗ misses | n/a |
| dict[str, int], bad value  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✗ misses | n/a |
| dict[str, int], bad key  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✗ misses | n/a |
| TypedDict, bad value for a key  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✓ catches | n/a |
| TypedDict, a required key is missing  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ✗ misses | ✓ catches | n/a |
| list[float] ← [1, 2.5] (items on the numeric tower)  (should accept) | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | n/a | ◐ sometimes | ✓ accepts | n/a |
| -> int, but returns a str  (should reject) | ✓ catches | ✓ catches | ✓ catches | \~ coerces | ✓ catches | n/a | ✓ catches | ✓ catches | n/a |
| dataclass: int field ← 'abc'  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✗ misses | ✓ catches |
| dataclass: obj.x = 'abc' after init  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✗ misses | ✗ misses | ✓ catches |
| dataclass: list[Item] ← [1]  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✗ misses | ✓ catches |
| int > 0 ← -5 (value check)  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | n/a | n/a |
| int > 0 ← 5  (should accept) | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | n/a | ✓ accepts | n/a | n/a |
| int > 0 ← '5' (wrong type)  (should reject) | ✓ catches | \~ coerces | ✓ catches | \~ coerces | ✓ catches | n/a | ✓ catches | n/a | n/a |
| list[int > 0] ← [1, -2]  (should reject) | – deep off | – deep off | ✓ catches | ✓ catches | ✓ catches | n/a | ◐ sometimes | n/a | n/a |
| email ← 'nope' (custom validator)  (should reject) | ✓ catches | ✓ catches | ✓ catches | ✓ catches | ✓ catches | n/a | ✓ catches | n/a | n/a |
| email ← 'ana@example.com'  (should accept) | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | ✓ accepts | n/a | ✓ accepts | n/a | n/a |
| email ← 'ana@example.com' with convert=False  (should reject) | ✓ catches | \~ coerces | ✓ catches | n/a | n/a | n/a | n/a | n/a | n/a |
| reports all 3 wrong args in one error | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | 1/3 | 1/3 |

✓ expected behaviour · ✗ wrong · \~ value silently converted · ◐ caught in some trials only (random sampling) · – deep off: items aren't checked by default, enable with deep=True (see the enf.deep column)  

## Error messages

*p_named(quantity: int) called with 'abc' · class-only libraries: Named(quantity='abc')*

**enforced**
```
InvalidDataError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**enf.coerce**
```
InvalidDataError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**enf.deep**
```
InvalidDataError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**pydantic**
```
ValidationError: 1 validation error for p_named
quantity
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_ty…
    For further information visit https://errors.pydantic.dev/2.14/v/int_parsing
```

**pyd.strict**
```
ValidationError: 1 validation error for p_named
quantity
  Input should be a valid integer [type=int_type, input_value='abc', input_type=str]
    For further information visit https://errors.pydantic.dev/2.14/v/int_type
```

**pyd.model**
```
ValidationError: 1 validation error for Named
quantity
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_ty…
    For further information visit https://errors.pydantic.dev/2.14/v/int_parsing
```

**beartype**
```
BeartypeCallHintParamViolation: Function _pv_bench_targets.p_named() parameter quantity='abc' violates type hint <clas…
```

**typeguard**
```
TypeCheckError: argument "quantity" (str) is not an instance of int
```

**attrs**
```
TypeError: ("'quantity' must be <class 'int'> (got 'abc' that is a <class 'str'>).", Attribute(name='quantity', defaul…
```

## Function calls

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.012 | **0.066** | 0.070 | **0.066** | 0.217 | 0.218 | 0.087 | 1.18 |
| 2 params · positional | 0.011 | **0.073** | 0.076 | **0.074** | 0.226 | 0.226 | 0.100 | 1.66 |
| 2 params · keyword | 0.017 | **0.156** | 0.162 | **0.157** | 0.491 | 0.492 | 0.166 | 1.67 |
| 5 params · mixed types | 0.013 | **0.103** | **0.103** | **0.104** | 0.275 | 0.276 | 0.150 | 2.87 |
| 12 params · positional | 0.018 | **0.199** | **0.200** | **0.199** | 0.358 | 0.357 | 0.269 | 5.92 |
| 12 params · keyword | 0.038 | **0.663** | **0.676** | **0.665** | 1.59 | 1.59 | **0.678** | 5.94 |
| defaults used (1 of 5 given) | 0.015 | 0.173 | 0.172 | 0.174 | 0.582 | 0.588 | **0.151** | 4.89 |
| keyword-only params | 0.020 | **0.163** | **0.164** | 0.165 | 0.392 | 0.394 | **0.160** | 2.05 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.203** | **0.209** | **0.204** | 0.491 | 0.494 | 0.223 | 5.85 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.084** | **0.084** | 0.273 | 0.259 | 0.112 | 4.02 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | 0.234 | 0.234 | 0.235 | 0.496 | 0.493 | **0.224** | 6.45 |
| user-defined classes | 0.013 | **0.074** | **0.074** | **0.075** | 0.225 | 0.226 | 0.107 | 1.66 |
| Any / object | 0.011 | 0.055 | 0.056 | 0.056 | 0.219 | 0.219 | **0.011** | 1.17 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.260** | **0.260** | **0.260** | 0.428 | 0.425 | 0.512 | 4.13 |
| return value checked | 0.010 | **0.076** | 0.079 | **0.077** | 0.246 | 0.246 | 0.089 | 1.64 |
| async def (coroutine driven) | 0.101 | **0.195** | 0.207 | **0.197** | 0.453 | 0.456 | 0.251 | 1.81 |
| method on an instance | 0.012 | **0.077** | 0.081 | **0.077** | 0.238 | 0.242 | 0.107 | 1.69 |
| positional-only params · one default used | 0.014 | 0.124 | 0.124 | 0.123 | 0.407 | 0.408 | **0.116** | 2.02 |
| float params given ints (numeric tower) | 0.012 | 0.274 | 0.302 | 0.274 | **0.262** | **0.261** | ERR | 1.31 |
| Callable · Iterable | 0.013 | **0.166** | **0.167** | **0.168** | 0.343 | 0.337 | 0.500 | 6.22 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.066† | **0.187** | 0.335 | 0.335 | 0.133† | 1.98† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.065† | **4.99** | 6.81 | 6.81 | 0.145† | 1.93† |
| list[int] × 100,000 | 0.012 | 0.063† | 0.066† | **470** | 1,102 | 1,080 | 0.161†\~ | 1.93† |
| dict[str, int] × 100 | 0.012 | 0.063† | 0.062† | **1.35** | 2.24 | 2.24 | 0.139† | 2.53† |
| tuple[int, str, float] | 0.012 | 0.064† | 0.068† | **0.119** | 0.273 | 0.276 | **0.120** | 2.97 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.063† | **1.30** | 1.45 | 1.47 | 0.189† | 3.30† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.112† | 0.111† | **2.09** | 4.58 | 4.64 | 0.305† | 3.24† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.062† | **0.301** | 0.424 | 0.424 | 0.174† | 5.03 |
| list of 100 objects | 0.012 | 0.063† | 0.066† | **0.660** | 0.867 | 0.877 | 0.141† | 1.95† |
| set[str] × 100 | 0.012 | **0.062** | 0.066 | 0.740 | 1.74 | 1.78 | 0.119 | 2.12 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.066† | **5.74** | 6.88 | 6.91 | 0.153† | 3.86† |
| tuple[int, ...] × 1,000 | 0.012 | 0.063† | 0.066† | **4.88** | 6.22 | 6.27 | 0.145† | 2.17† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.097 | 0.431 | 0.429 | 0.440 | 0.590 | 0.607 | 0.399 | 0.334 | 0.097† | **0.305** |
| construct Order tree (5 objects) | 0.454 | 2.00† | 2.06† | 2.18 | 2.86 | 2.85 | 1.92 | 1.71 | 0.460† | **1.54** |
| assign point.x = 5 | 0.004 | **0.060** | **0.060** | **0.060** | 0.271 | 0.270 | 0.377 | 0.004† | 0.004† | 0.122 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.096** | **0.098** | **0.096** | 0.228 | 0.227 | 0.121 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.065† | **19.8** | 23.2 | 22.9 | 0.189† |
| email · already valid str | 0.010 | 0.938 | 0.940 | 0.944 | 0.992 | 0.988 | **0.833** |
| email · normalised (domain lower-cased) | 0.010 | 0.939≠ | 0.939≠ | 0.953≠ | 0.991≠ | 0.998≠ | **0.822** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.575 | 0.722 | 0.583 | **0.480** | **0.479** | n/a | 31.8 | 2.52 | n/a |
| 3 wrong args of 12 | 1.15 | 2.23 | 1.14 | **0.702** | 0.777 | n/a | 31.0 | 3.15 | n/a |
| missing argument | 0.575 | 0.578 | 0.577 | 0.524 | 0.525 | n/a | 0.395 | **0.171** | n/a |
| unknown keyword argument | 0.729 | 0.733 | 0.725 | 0.585 | 0.589 | n/a | 0.437 | **0.131** | n/a |
| wrong keyword-only argument | 0.815 | 0.887 | 0.818 | **0.607** | **0.600** | n/a | 31.4 | 2.57 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.6 | 6.89 | 6.80 | n/a | no err | **3.03** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 7.74 | **1.66** | **1.66** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.465** | **0.475** | **0.472** | no err | 0.541 | n/a | 29.7 | 2.57 | n/a |
| dataclass field wrong type | 0.974 | 1.43 | 0.981 | 0.790 | 0.775 | **0.496** | 32.8 | no err | 0.716 |
| dataclass assignment wrong type | **0.429** | 1.28 | **0.425** | 0.475 | 0.470 | 0.450 | no err | no err | 0.557 |
| value check fails (int > 0 ← -5) | 0.967 | 1.05 | 0.966 | **0.487** | **0.482** | n/a | 44.9 | n/a | n/a |
| invalid email | 0.995 | 1.00 | 1.00 | **0.671** | **0.674** | n/a | 45.1 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.228** |
| typecheck_record · cached spec | **1.08** |
| -> Self · called on the class that defines it | **0.077** |
| -> Self · called on a subclass | **0.084** |
| other: Self · called on a subclass | **0.093** |
| Self \| None · called on a subclass (a wrapper per class) | **0.193** |
| class method -> Self · called on a subclass | **0.204** |
| a method of a dataclass · row.scaled(2) | **0.132** |
| the same method under enforce · plain.scaled(2) | **0.133** |
| on_error='warn' · a valid call | **0.072** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.01** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.03** |
| Ok(value) | **0.069** |
| protect · the awaitable completes | **0.467** |
| protect · the awaitable raises | **0.633** |
| Self: a Base where a Child is expected (raise + catch) | **1.06** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.32 | 2.17 | **0.941** | 0.946 | n/a | 30.7 | 2.74 | n/a |
| 3 wrong args of 12 | 4.95 | 4.73 | **1.67** | 1.69 | n/a | 29.7 | 3.53 | n/a |
| missing argument | 2.30 | 2.12 | 1.04 | 1.07 | n/a | 0.427 | **0.200** | n/a |
| unknown keyword argument | 1.11 | 1.01 | 1.04 | 1.03 | n/a | 0.474 | **0.156** | n/a |
| wrong keyword-only argument | 2.52 | 2.37 | **1.05** | 1.06 | n/a | 30.6 | 2.78 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.31 | 7.29 | n/a | no err | **3.30** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.23 | **2.16** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.17 | 2.00 | no err | **0.924** | n/a | 29.5 | 2.79 | n/a |
| dataclass field wrong type | 2.62 | 2.54 | 1.26 | 1.22 | **0.977** | 31.8 | no err | 1.98 |
| dataclass assignment wrong type | 2.83 | 2.31 | 0.948 | **0.889** | 1.71 | no err | no err | 1.80 |
| value check fails (int > 0 ← -5) | 2.44 | 2.30 | 1.03 | **1.02** | n/a | 43.4 | n/a | n/a |
| invalid email | 2.43 | 2.34 | 1.20 | **1.20** | n/a | 45.0 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.055 | 0.058 | 0.054 | 0.205 | 0.204 | 0.075 | 1.14 |
| 2 params | 0.067 | 0.072 | 0.067 | 0.215 | 0.215 | 0.090 | 1.62 |
| 4 params | 0.091 | 0.097 | 0.091 | 0.241 | 0.241 | 0.120 | 2.59 |
| 8 params | 0.151 | 0.153 | 0.150 | 0.294 | 0.295 | 0.187 | 4.41 |
| 16 params | 0.258 | 0.257 | 0.254 | 0.388 | 0.393 | 0.307 | 8.08 |
| 32 params | 0.463 | 0.463 | 0.463 | 0.637 | 0.638 | 0.552 | 15.8 |
| fixed cost (ns) | 42 | 46 | 41 | 184 | 185 | 60 | 654 |
| per param (ns) | 13.2 | 13.1 | 13.2 | 13.9 | 13.9 | 15.4 | 471.9 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.270 | 0.270 | 0.260 | 0.420 | 150 | 0.0 |
| enforced | 260.3 | 8.75 | 47.8 | 5.64 | 76.4 | 221 | 8.6 |
| enf.coerce | 266.4 | 9.69 | 55.2 | 6.16 | 89.0 | 274 | 10.4 |
| enf.deep | 262.2 | 8.92 | 52.0 | 5.69 | 84.8 | 236 | 8.6 |
| pydantic | 67.2 | 192 | 6.23 | 269 | 2.56 | 455 | 4.0 |
| pyd.strict | 70.9 | 228 | 6.78 | 297 | 2.66 | 421 | 4.0 |
| pyd.model | 55.4 | n/a | n/a | n/a | n/a | 240 | n/a |
| beartype | 55.7 | 270 | 1.45 | 643 | 2.62 | 531 | 2.8 |
| typeguard | 73.6 | 2,311 | 15.3 | 2,396 | 19.7 | 4,211 | 1.7 |
| attrs | 24.9 | n/a | n/a | n/a | n/a | 300 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 11 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 28 |
| pydantic | 2.51× slower  (32 cases) | 1.32× faster  (9 cases) | 1 |
| pyd.strict | 2.51× slower  (32 cases) | 1.25× faster  (10 cases) | 1 |
| pyd.model | 2.41× slower  (2 cases) | 1.37× faster  (2 cases) | 0 |
| beartype | 1.16× slower  (30 cases) | 16.81× slower  (9 cases) | 9 |
| typeguard | 20.67× slower  (27 cases) | 1.50× slower  (6 cases) | 0 |
| attrs | 1.20× slower  (2 cases) | 1.02× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
