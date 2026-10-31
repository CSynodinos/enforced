# enforced comparison

*2026-10-24 00:20*

CPython 3.14.4 (GIL) · Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43  
AMD Ryzen 9 9900X 12-Core Processor · 24 CPUs  
timing: 9 interleaved rounds × ≥30 ms per library per case, median reported, GC off  

| library | version | what is measured |
|:--|:--|:--|
| plain | - | no checks: undecorated function / stdlib dataclass |
| enforced | 0.1.0 | @validate / enforced.dataclass, defaults (convert on, coerce off) |
| enf.coerce | 0.1.0 | enforced with coerce=True (parses '42' -> 42, like pydantic lax) |
| enf.deep | 0.1.0 | enforced with deep=True (checks every item inside collections, like pydantic) |
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
| 1 param | 0.010 | **0.064** | 0.067 | **0.064** | 0.214 | 0.215 | 0.084 | 1.17 |
| 2 params · positional | 0.011 | **0.074** | 0.077 | **0.073** | 0.228 | 0.227 | 0.102 | 1.69 |
| 2 params · keyword | 0.016 | **0.156** | 0.162 | **0.157** | 0.477 | 0.480 | 0.170 | 1.67 |
| 5 params · mixed types | 0.013 | **0.103** | **0.103** | **0.103** | 0.274 | 0.275 | 0.151 | 2.88 |
| 12 params · positional | 0.020 | **0.198** | **0.200** | **0.198** | 0.362 | 0.355 | 0.274 | 5.93 |
| 12 params · keyword | 0.038 | **0.645** | **0.648** | **0.654** | 1.50 | 1.50 | 0.669 | 5.91 |
| defaults used (1 of 5 given) | 0.015 | 0.171 | 0.173 | 0.171 | 0.568 | 0.568 | **0.153** | 4.93 |
| keyword-only params | 0.020 | **0.163** | **0.164** | **0.164** | 0.429 | 0.434 | **0.160** | 2.05 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.208** | **0.210** | **0.205** | 0.494 | 0.492 | 0.220 | 5.87 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.085** | **0.085** | 0.272 | 0.258 | 0.112 | 4.04 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | 0.236 | 0.234 | 0.237 | 0.499 | 0.495 | **0.227** | 6.57 |
| user-defined classes | 0.013 | **0.072** | **0.073** | **0.073** | 0.228 | 0.229 | 0.107 | 1.66 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.056 | 0.219 | 0.220 | **0.011** | 1.18 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.266** | **0.262** | **0.265** | 0.432 | 0.429 | 0.523 | 4.13 |
| return value checked | 0.010 | **0.078** | 0.081 | **0.078** | 0.250 | 0.251 | 0.091 | 1.67 |
| async def (coroutine driven) | 0.101 | **0.196** | 0.207 | **0.194** | 0.450 | 0.453 | 0.249 | 1.84 |
| method on an instance | 0.012 | **0.077** | 0.082 | **0.077** | 0.242 | 0.242 | 0.105 | 1.72 |
| positional-only params · one default used | 0.014 | 0.125 | 0.125 | 0.123 | 0.410 | 0.407 | **0.111** | 2.02 |
| float params given ints (numeric tower) | 0.012 | 0.272 | 0.297 | 0.274 | **0.261** | **0.259** | ERR | 1.33 |
| Callable · Iterable | 0.013 | **0.166** | **0.166** | **0.166** | 0.371 | 0.374 | 0.511 | 6.37 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.065† | **0.189** | 0.334 | 0.331 | 0.132† | 1.98† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.065† | **4.97** | 6.86 | 6.79 | 0.145† | 1.98† |
| list[int] × 100,000 | 0.013 | 0.062† | 0.065† | **466** | 1,070 | 1,079 | 0.161† | 1.97† |
| dict[str, int] × 100 | 0.012 | 0.063† | 0.063† | **1.34** | 2.30 | 2.32 | 0.138† | 2.56† |
| tuple[int, str, float] | 0.012 | 0.062† | 0.065† | **0.118** | 0.273 | 0.272 | **0.115** | 3.02 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.063† | **1.29** | 1.40 | 1.40 | 0.192† | 3.30† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.110† | 0.111† | **2.07** | 4.60 | 4.61 | 0.303† | 3.22† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.062† | **0.309** | 0.420 | 0.421 | 0.173† | 5.02 |
| list of 100 objects | 0.012 | 0.064† | 0.067† | **0.665** | 0.870 | 0.873 | 0.138† | 1.97† |
| set[str] × 100 | 0.012 | **0.062** | 0.065 | 0.731 | 1.70 | 1.72 | 0.120 | 2.21 |
| list[int \| None] × 1,000 | 0.012 | 0.062† | 0.065† | **5.76** | 6.92 | 6.95 | 0.149† | 3.84† |
| tuple[int, ...] × 1,000 | 0.012 | 0.063† | 0.066† | **4.89** | 6.34 | 6.27 | 0.148† | 2.17† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.100 | 0.442 | 0.437 | 0.445 | 0.609 | 0.608 | 0.416 | 0.341 | 0.100† | **0.316** |
| construct Order tree (5 objects) | 0.489 | 2.02† | 2.11† | 2.20 | 2.89 | 2.87 | 1.95 | 1.76 | 0.475† | **1.55** |
| assign point.x = 5 | 0.004 | **0.061** | **0.060** | **0.060** | 0.269 | 0.270 | 0.372 | 0.004† | 0.004† | 0.120 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.091** | 0.096 | **0.094** | 0.225 | 0.225 | 0.123 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.065† | **19.7** | 21.9 | 21.9 | 0.185† |
| email · already valid str | 0.010 | 0.950 | 0.947 | 0.946 | 0.981 | 0.983 | **0.819** |
| email · normalised (domain lower-cased) | 0.011 | 0.932≠ | 0.934≠ | 0.938≠ | 0.963≠ | 0.965≠ | **0.806** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.585 | 0.736 | 0.586 | **0.477** | **0.480** | n/a | 31.8 | 2.48 | n/a |
| 3 wrong args of 12 | 1.16 | 2.21 | 1.17 | **0.698** | 0.783 | n/a | 30.8 | 3.17 | n/a |
| missing argument | 0.573 | 0.578 | 0.580 | 0.522 | 0.526 | n/a | 0.394 | **0.171** | n/a |
| unknown keyword argument | 0.732 | 0.743 | 0.734 | 0.578 | 0.571 | n/a | 0.449 | **0.142** | n/a |
| wrong keyword-only argument | 0.826 | 0.888 | 0.824 | **0.590** | **0.591** | n/a | 31.5 | 2.56 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.4 | 6.88 | 6.81 | n/a | no err | **3.07** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 7.92 | **1.67** | **1.65** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.488** | **0.495** | **0.489** | no err | 0.541 | n/a | 29.3 | 2.50 | n/a |
| dataclass field wrong type | 0.980 | 1.46 | 0.984 | 0.791 | 0.784 | **0.499** | 32.1 | no err | 0.707 |
| dataclass assignment wrong type | **0.435** | 1.29 | **0.434** | 0.482 | 0.466 | 0.460 | no err | no err | 0.554 |
| value check fails (int > 0 ← -5) | 0.988 | 1.08 | 0.992 | **0.489** | **0.496** | n/a | 43.3 | n/a | n/a |
| invalid email | 1.00 | 0.994 | 0.994 | **0.670** | **0.670** | n/a | 45.7 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| validate_function(fn, args) · repeated | **0.234** |
| validate_record · cached spec | **1.08** |
| -> Self · called on the class that defines it | **0.074** |
| -> Self · called on a subclass | **0.083** |
| other: Self · called on a subclass | **0.092** |
| Self \| None · called on a subclass (a wrapper per class) | **0.202** |
| class method -> Self · called on a subclass | **0.202** |
| a method of a dataclass · row.scaled(2) | **0.130** |
| the same method under enforce · plain.scaled(2) | **0.130** |
| on_error='warn' · a valid call | **0.072** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.08** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.05** |
| dispatch · a class anchor (int, after str) | **0.110** |
| functools.singledispatch · the same, for comparison | **0.115** |
| dispatch · list[int] × 10, after list[str] | **0.749** |
| dispatch · an Email from its text | **1.38** |
| dispatchmethod · a class anchor | **0.362** |
| functools.singledispatchmethod · the same, for comparison | **0.354** |
| dispatch · no version takes it (raise + catch) | **3.45** |
| Ok(value) | **0.070** |
| protect · the awaitable completes | **0.474** |
| protect · the awaitable raises | **0.636** |
| Self: a Base where a Child is expected (raise + catch) | **1.08** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.32 | 2.20 | 0.939 | **0.923** | n/a | 32.4 | 2.70 | n/a |
| 3 wrong args of 12 | 4.88 | 4.74 | **1.65** | 1.70 | n/a | 30.4 | 3.39 | n/a |
| missing argument | 2.34 | 2.19 | 1.05 | 1.04 | n/a | 0.430 | **0.213** | n/a |
| unknown keyword argument | 1.14 | 1.03 | 1.03 | 1.02 | n/a | 0.484 | **0.165** | n/a |
| wrong keyword-only argument | 2.57 | 2.45 | 1.07 | **1.04** | n/a | 31.3 | 2.85 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.37 | 7.34 | n/a | no err | **3.37** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.21 | **2.13** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.17 | 2.04 | no err | **0.938** | n/a | 28.6 | 2.79 | n/a |
| dataclass field wrong type | 2.71 | 2.59 | 1.27 | 1.22 | **0.979** | 30.7 | no err | 1.93 |
| dataclass assignment wrong type | 2.91 | 2.43 | 0.935 | **0.882** | 1.68 | no err | no err | 1.76 |
| value check fails (int > 0 ← -5) | 2.47 | 2.33 | 1.03 | **1.01** | n/a | 44.4 | n/a | n/a |
| invalid email | 2.48 | 2.33 | 1.21 | **1.20** | n/a | 45.2 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.054 | 0.057 | 0.054 | 0.202 | 0.204 | 0.075 | 1.15 |
| 2 params | 0.069 | 0.071 | 0.069 | 0.215 | 0.215 | 0.090 | 1.65 |
| 4 params | 0.092 | 0.096 | 0.092 | 0.242 | 0.244 | 0.124 | 2.59 |
| 8 params | 0.149 | 0.152 | 0.148 | 0.294 | 0.291 | 0.192 | 4.44 |
| 16 params | 0.252 | 0.254 | 0.253 | 0.388 | 0.386 | 0.319 | 8.10 |
| 32 params | 0.459 | 0.462 | 0.453 | 0.588 | 0.591 | 0.569 | 15.6 |
| fixed cost (ns) | 42 | 45 | 43 | 191 | 191 | 61 | 707 |
| per param (ns) | 13.1 | 13.0 | 12.9 | 12.4 | 12.4 | 16.0 | 464.6 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.330 | 0.270 | 0.280 | 0.440 | 149 | 0.0 |
| enforced | 334.0 | 9.64 | 52.5 | 7.87 | 83.4 | 239 | 8.6 |
| enf.coerce | 328.5 | 8.04 | 55.2 | 8.36 | 87.0 | 259 | 10.5 |
| enf.deep | 333.0 | 10.2 | 54.7 | 8.16 | 86.6 | 246 | 8.6 |
| pydantic | 66.8 | 256 | 7.02 | 286 | 2.62 | 407 | 4.0 |
| pyd.strict | 65.4 | 182 | 5.76 | 278 | 2.65 | 418 | 4.0 |
| pyd.model | 55.3 | n/a | n/a | n/a | n/a | 249 | n/a |
| beartype | 57.1 | 247 | 1.44 | 599 | 2.83 | 515 | 2.8 |
| typeguard | 73.8 | 2,336 | 16.6 | 2,381 | 20.0 | 4,292 | 1.7 |
| attrs | 25.7 | n/a | n/a | n/a | n/a | 259 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 10 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 29 |
| pydantic | 2.51× slower  (32 cases) | 1.33× faster  (9 cases) | 1 |
| pyd.strict | 2.51× slower  (32 cases) | 1.27× faster  (10 cases) | 1 |
| pyd.model | 2.39× slower  (2 cases) | 1.36× faster  (2 cases) | 0 |
| beartype | 1.17× slower  (30 cases) | 16.52× slower  (9 cases) | 8 |
| typeguard | 20.87× slower  (27 cases) | 1.48× slower  (6 cases) | 0 |
| attrs | 1.19× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
