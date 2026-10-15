# enforced comparison

*2026-10-15 20:12*

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
TypeCheckerError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**enf.coerce**
```
TypeCheckerError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**enf.deep**
```
TypeCheckerError: 1 problem found in call:
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
| 1 param | 0.010 | **0.064** | 0.068 | **0.065** | 0.219 | 0.215 | 0.086 | 1.17 |
| 2 params · positional | 0.011 | **0.074** | 0.076 | **0.072** | 0.226 | 0.228 | 0.102 | 1.74 |
| 2 params · keyword | 0.018 | **0.158** | 0.162 | **0.156** | 0.476 | 0.481 | 0.172 | 1.74 |
| 5 params · mixed types | 0.013 | **0.104** | **0.103** | **0.103** | 0.280 | 0.280 | 0.153 | 3.00 |
| 12 params · positional | 0.018 | **0.199** | **0.203** | **0.200** | 0.353 | 0.356 | 0.270 | 6.10 |
| 12 params · keyword | 0.038 | **0.645** | **0.660** | **0.646** | 1.51 | 1.51 | 0.675 | 6.15 |
| defaults used (1 of 5 given) | 0.015 | 0.174 | 0.177 | 0.177 | 0.580 | 0.586 | **0.155** | 5.14 |
| keyword-only params | 0.020 | 0.167 | **0.165** | **0.165** | 0.413 | 0.412 | **0.161** | 2.13 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.211** | **0.210** | **0.209** | 0.495 | 0.496 | 0.222 | 5.90 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.084** | **0.084** | 0.273 | 0.263 | 0.117 | 4.07 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.236** | **0.237** | **0.237** | 0.486 | 0.491 | **0.230** | 6.68 |
| user-defined classes | 0.013 | **0.073** | **0.072** | **0.072** | 0.231 | 0.230 | 0.108 | 1.69 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.055 | 0.238 | 0.241 | **0.011** | 1.21 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.264** | **0.261** | **0.263** | 0.431 | 0.430 | 0.521 | 4.12 |
| return value checked | 0.010 | **0.076** | 0.080 | **0.077** | 0.247 | 0.248 | 0.094 | 1.65 |
| async def (coroutine driven) | 0.101 | **0.197** | 0.207 | **0.197** | 0.456 | 0.450 | 0.251 | 1.87 |
| method on an instance | 0.012 | **0.078** | 0.080 | **0.078** | 0.272 | 0.270 | 0.105 | 1.75 |
| positional-only params · one default used | 0.014 | 0.125 | 0.125 | 0.125 | 0.414 | 0.409 | **0.114** | 2.06 |
| float params given ints (numeric tower) | 0.012 | 0.273 | 0.296 | 0.272 | **0.264** | **0.259** | ERR | 1.32 |
| Callable · Iterable | 0.013 | **0.168** | **0.169** | **0.168** | 0.336 | 0.340 | 0.507 | 6.26 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.066† | **0.189** | 0.341 | 0.342 | 0.135† | 1.95† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.066† | **5.03** | 6.87 | 6.94 | 0.147† | 1.98† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.066† | **463** | 1,104 | 1,091 | 0.156† | 1.98† |
| dict[str, int] × 100 | 0.012 | 0.062† | 0.062† | **1.36** | 2.31 | 2.32 | 0.138† | 2.60† |
| tuple[int, str, float] | 0.013 | 0.062† | 0.066† | **0.116** | 0.274 | 0.274 | **0.116** | 3.10 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.062† | **1.30** | 1.45 | 1.45 | 0.187† | 3.40† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.113† | 0.112† | **2.07** | 4.79 | 4.76 | 0.311† | 3.29† |
| TypedDict (4 keys, one a list) | 0.012 | 0.063† | 0.063† | **0.299** | 0.425 | 0.428 | 0.178† | 5.05 |
| list of 100 objects | 0.012 | 0.062† | 0.066† | **0.664** | 0.898 | 0.898 | 0.137† | 1.97† |
| set[str] × 100 | 0.012 | **0.063** | 0.066 | 0.732 | 1.73 | 1.75 | 0.122 | 2.16 |
| list[int \| None] × 1,000 | 0.012 | 0.062† | 0.065† | **5.79** | 6.87 | 6.93 | 0.150† | 3.83† |
| tuple[int, ...] × 1,000 | 0.012 | 0.062† | 0.065† | **5.20** | 6.24 | 6.25 | 0.144† | 2.18† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.098 | 0.432 | 0.429 | 0.430 | 0.605 | 0.605 | 0.416 | 0.341 | 0.098† | **0.301** |
| construct Order tree (5 objects) | 0.465 | 2.00† | 2.05† | 2.20 | 2.88 | 2.90 | 1.97 | 1.74 | 0.463† | **1.54** |
| assign point.x = 5 | 0.004 | **0.062** | **0.062** | **0.063** | 0.277 | 0.277 | 0.376 | 0.004† | 0.004† | 0.124 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.092** | **0.095** | **0.093** | 0.228 | 0.228 | 0.126 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.066† | **19.8** | 21.6 | 21.7 | 0.184† |
| email · already valid str | 0.010 | 0.918 | 0.915 | 0.921 | 0.989 | 0.980 | **0.802** |
| email · normalised (domain lower-cased) | 0.010 | 0.925≠ | 0.919≠ | 0.924≠ | 0.999≠ | 0.979≠ | **0.807** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.577 | 0.652 | 0.578 | **0.477** | **0.479** | n/a | 31.2 | 2.52 | n/a |
| 3 wrong args of 12 | 1.15 | 2.10 | 1.15 | **0.705** | 0.783 | n/a | 30.8 | 3.27 | n/a |
| missing argument | 0.581 | 0.579 | 0.574 | 0.530 | 0.524 | n/a | 0.407 | **0.172** | n/a |
| unknown keyword argument | 0.724 | 0.726 | 0.728 | 0.582 | 0.583 | n/a | 0.449 | **0.134** | n/a |
| wrong keyword-only argument | 0.809 | 0.889 | 0.805 | **0.607** | **0.599** | n/a | 30.9 | 2.62 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.7 | 6.90 | 6.79 | n/a | no err | **3.09** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 7.55 | **1.69** | **1.68** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.483** | **0.485** | **0.477** | no err | 0.540 | n/a | 28.9 | 2.65 | n/a |
| dataclass field wrong type | 0.976 | 1.41 | 0.977 | 0.789 | 0.778 | **0.504** | 31.6 | no err | 0.696 |
| dataclass assignment wrong type | **0.420** | 1.28 | **0.428** | 0.479 | 0.476 | 0.472 | no err | no err | 0.542 |
| value check fails (int > 0 ← -5) | 0.961 | 1.03 | 0.967 | **0.479** | **0.483** | n/a | 44.8 | n/a | n/a |
| invalid email | 0.976 | 0.980 | 0.978 | **0.666** | **0.677** | n/a | 45.4 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.227** |
| typecheck_record · cached spec | **1.08** |
| -> Self · called on the class that defines it | **0.075** |
| -> Self · called on a subclass | **0.084** |
| other: Self · called on a subclass | **0.093** |
| Self \| None · called on a subclass (a wrapper per class) | **0.193** |
| class method -> Self · called on a subclass | **0.204** |
| a method of a dataclass · row.scaled(2) | **0.132** |
| the same method under enforce · plain.scaled(2) | **0.132** |
| on_error='warn' · a valid call | **0.073** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.07** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.04** |
| Ok(value) | **0.070** |
| protect · the awaitable completes | **0.487** |
| protect · the awaitable raises | **0.634** |
| Self: a Base where a Child is expected (raise + catch) | **1.10** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.52 | 2.40 | 0.951 | **0.937** | n/a | 30.0 | 2.70 | n/a |
| 3 wrong args of 12 | 5.48 | 5.30 | **1.67** | 1.70 | n/a | 30.0 | 3.39 | n/a |
| missing argument | 2.56 | 2.38 | 1.06 | 1.04 | n/a | 0.427 | **0.197** | n/a |
| unknown keyword argument | 1.10 | 1.03 | 1.01 | 1.01 | n/a | 0.483 | **0.155** | n/a |
| wrong keyword-only argument | 2.74 | 2.58 | **1.08** | 1.09 | n/a | 30.5 | 2.80 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.42 | 7.31 | n/a | no err | **3.29** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.20 | **2.09** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.44 | 2.25 | no err | **0.924** | n/a | 29.5 | 2.78 | n/a |
| dataclass field wrong type | 2.92 | 2.84 | 1.28 | 1.22 | **0.988** | 31.0 | no err | 1.92 |
| dataclass assignment wrong type | 2.87 | 2.43 | 0.946 | **0.894** | 1.71 | no err | no err | 1.74 |
| value check fails (int > 0 ← -5) | 2.93 | 2.68 | 1.05 | **1.01** | n/a | 43.9 | n/a | n/a |
| invalid email | 2.97 | 2.68 | 1.19 | **1.17** | n/a | 47.3 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.054 | 0.057 | 0.054 | 0.208 | 0.207 | 0.075 | 1.16 |
| 2 params | 0.067 | 0.070 | 0.066 | 0.215 | 0.216 | 0.090 | 1.64 |
| 4 params | 0.092 | 0.098 | 0.091 | 0.244 | 0.242 | 0.122 | 2.64 |
| 8 params | 0.151 | 0.154 | 0.151 | 0.300 | 0.299 | 0.190 | 4.47 |
| 16 params | 0.256 | 0.256 | 0.258 | 0.394 | 0.388 | 0.317 | 8.18 |
| 32 params | 0.468 | 0.463 | 0.463 | 0.626 | 0.627 | 0.555 | 16.1 |
| fixed cost (ns) | 41 | 46 | 41 | 189 | 188 | 62 | 657 |
| per param (ns) | 13.4 | 13.1 | 13.3 | 13.5 | 13.5 | 15.5 | 479.6 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.290 | 0.270 | 0.280 | 0.410 | 148 | 0.0 |
| enforced | 267.1 | 7.45 | 48.0 | 5.71 | 77.7 | 227 | 8.6 |
| enf.coerce | 224.1 | 7.13 | 50.7 | 6.02 | 80.3 | 250 | 10.4 |
| enf.deep | 266.5 | 7.67 | 49.3 | 5.86 | 84.4 | 234 | 8.6 |
| pydantic | 66.6 | 174 | 5.45 | 264 | 2.46 | 431 | 4.0 |
| pyd.strict | 66.0 | 200 | 6.37 | 285 | 2.60 | 429 | 4.0 |
| pyd.model | 55.1 | n/a | n/a | n/a | n/a | 232 | n/a |
| beartype | 56.6 | 255 | 1.42 | 621 | 2.69 | 533 | 2.8 |
| typeguard | 74.0 | 2,361 | 17.2 | 2,435 | 20.1 | 4,241 | 1.6 |
| attrs | 25.0 | n/a | n/a | n/a | n/a | 306 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.27× slower  (10 cases) | 12 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 30 |
| pydantic | 2.53× slower  (32 cases) | 1.31× faster  (9 cases) | 1 |
| pyd.strict | 2.52× slower  (32 cases) | 1.25× faster  (10 cases) | 1 |
| pyd.model | 2.41× slower  (2 cases) | 1.31× faster  (2 cases) | 0 |
| beartype | 1.17× slower  (30 cases) | 16.70× slower  (9 cases) | 8 |
| typeguard | 21.04× slower  (27 cases) | 1.51× slower  (6 cases) | 0 |
| attrs | 1.18× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
