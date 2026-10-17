# enforced comparison

*2026-10-17 18:51*

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
| 1 param | 0.010 | **0.065** | 0.068 | **0.066** | 0.214 | 0.215 | 0.084 | 1.14 |
| 2 params · positional | 0.011 | **0.072** | 0.075 | **0.072** | 0.225 | 0.224 | 0.100 | 1.64 |
| 2 params · keyword | 0.017 | **0.156** | 0.162 | **0.156** | 0.487 | 0.485 | 0.166 | 1.65 |
| 5 params · mixed types | 0.013 | **0.103** | **0.103** | **0.103** | 0.276 | 0.277 | 0.151 | 2.86 |
| 12 params · positional | 0.018 | **0.201** | **0.199** | **0.199** | 0.354 | 0.353 | 0.269 | 5.96 |
| 12 params · keyword | 0.038 | **0.635** | **0.640** | **0.637** | 1.52 | 1.53 | 0.667 | 5.90 |
| defaults used (1 of 5 given) | 0.015 | 0.174 | 0.173 | 0.172 | 0.567 | 0.565 | **0.152** | 4.89 |
| keyword-only params | 0.019 | 0.165 | 0.165 | 0.165 | 0.397 | 0.397 | **0.158** | 2.00 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.208** | **0.211** | **0.209** | 0.502 | 0.502 | 0.229 | 6.05 |
| unions · int \| str \| None, float \| None | 0.011 | **0.085** | **0.085** | **0.084** | 0.274 | 0.262 | 0.116 | 3.98 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.014 | **0.236** | **0.236** | **0.235** | 0.496 | 0.499 | **0.231** | 6.65 |
| user-defined classes | 0.013 | **0.074** | **0.073** | **0.073** | 0.230 | 0.230 | 0.109 | 1.65 |
| Any / object | 0.011 | 0.056 | 0.055 | 0.056 | 0.220 | 0.222 | **0.011** | 1.16 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.267** | **0.268** | **0.266** | 0.431 | 0.434 | 0.516 | 4.08 |
| return value checked | 0.010 | **0.077** | 0.080 | **0.076** | 0.247 | 0.247 | 0.092 | 1.65 |
| async def (coroutine driven) | 0.102 | **0.198** | 0.208 | **0.200** | 0.457 | 0.455 | 0.247 | 1.82 |
| method on an instance | 0.012 | **0.077** | 0.082 | **0.077** | 0.241 | 0.241 | 0.105 | 1.68 |
| positional-only params · one default used | 0.014 | 0.125 | 0.127 | 0.127 | 0.404 | 0.403 | **0.111** | 2.01 |
| float params given ints (numeric tower) | 0.013 | 0.276 | 0.303 | 0.275 | **0.261** | **0.261** | ERR | 1.30 |
| Callable · Iterable | 0.013 | **0.166** | **0.166** | **0.166** | 0.347 | 0.347 | 0.507 | 6.25 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.063† | 0.065† | **0.188** | 0.358 | 0.358 | 0.132† | 1.92† |
| list[int] × 1,000 | 0.013 | 0.063† | 0.065† | **5.00** | 6.87 | 6.83 | 0.144† | 1.94† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.065† | **464** | 1,079 | 1,083 | 0.162† | 1.93† |
| dict[str, int] × 100 | 0.012 | 0.064† | 0.064† | **1.35** | 2.27 | 2.28 | 0.147† | 2.52† |
| tuple[int, str, float] | 0.012 | 0.063† | 0.065† | **0.119** | 0.273 | 0.274 | **0.116** | 2.98 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.063† | **1.30** | 1.44 | 1.46 | 0.188† | 3.32† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.110† | 0.111† | **2.07** | 4.58 | 4.59 | 0.305† | 3.23† |
| TypedDict (4 keys, one a list) | 0.013 | 0.062† | 0.062† | **0.301** | 0.426 | 0.427 | 0.174† | 4.95 |
| list of 100 objects | 0.012 | 0.062† | 0.065† | **0.654** | 0.889 | 0.877 | 0.139† | 1.92† |
| set[str] × 100 | 0.012 | **0.063** | 0.065 | 0.730 | 1.71 | 1.71 | 0.119 | 2.12 |
| list[int \| None] × 1,000 | 0.012 | 0.062† | 0.065† | **5.77** | 6.90 | 6.88 | 0.152† | 3.78† |
| tuple[int, ...] × 1,000 | 0.016 | 0.062† | 0.065† | **4.86** | 6.27 | 6.25 | 0.142† | 2.18† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.101 | 0.429 | 0.431 | 0.425 | 0.595 | 0.594 | 0.405 | 0.332 | 0.099† | **0.304** |
| construct Order tree (5 objects) | 0.476 | 2.03† | 2.07† | 2.21 | 2.86 | 2.86 | 1.96 | 1.73 | 0.478† | **1.55** |
| assign point.x = 5 | 0.004 | **0.061** | **0.061** | **0.060** | 0.290 | 0.289 | 0.391 | 0.004† | 0.004† | 0.120 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.096** | **0.097** | **0.097** | 0.227 | 0.226 | 0.121 |
| list[int > 0] × 1,000 | 0.012 | 0.063† | 0.066† | **19.8** | 21.9 | 21.9 | 0.184† |
| email · already valid str | 0.010 | 0.955 | 0.944 | 0.945 | 0.991 | 0.992 | **0.825** |
| email · normalised (domain lower-cased) | 0.010 | 0.960≠ | 0.954≠ | 0.949≠ | 1.00≠ | 0.997≠ | **0.834** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.583 | 0.731 | 0.583 | **0.476** | **0.476** | n/a | 31.4 | 2.47 | n/a |
| 3 wrong args of 12 | 1.15 | 2.19 | 1.17 | **0.705** | 0.795 | n/a | 31.2 | 3.15 | n/a |
| missing argument | 0.580 | 0.587 | 0.582 | 0.519 | 0.522 | n/a | 0.400 | **0.174** | n/a |
| unknown keyword argument | 0.726 | 0.730 | 0.724 | 0.574 | 0.577 | n/a | 0.451 | **0.133** | n/a |
| wrong keyword-only argument | 0.821 | 0.893 | 0.823 | **0.601** | **0.597** | n/a | 30.9 | 2.56 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.8 | 6.84 | 6.84 | n/a | no err | **3.00** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 8.02 | **1.67** | **1.67** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.475** | **0.481** | **0.482** | no err | 0.546 | n/a | 30.0 | 2.54 | n/a |
| dataclass field wrong type | 0.981 | 1.42 | 0.977 | 0.771 | 0.758 | **0.489** | 32.0 | no err | 0.699 |
| dataclass assignment wrong type | **0.433** | 1.28 | **0.432** | 0.496 | 0.486 | 0.463 | no err | no err | 0.536 |
| value check fails (int > 0 ← -5) | 0.970 | 1.05 | 0.965 | **0.475** | **0.475** | n/a | 44.0 | n/a | n/a |
| invalid email | 1.00 | 0.996 | 0.995 | **0.669** | **0.667** | n/a | 44.8 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.231** |
| typecheck_record · cached spec | **1.07** |
| -> Self · called on the class that defines it | **0.074** |
| -> Self · called on a subclass | **0.084** |
| other: Self · called on a subclass | **0.092** |
| Self \| None · called on a subclass (a wrapper per class) | **0.198** |
| class method -> Self · called on a subclass | **0.205** |
| a method of a dataclass · row.scaled(2) | **0.131** |
| the same method under enforce · plain.scaled(2) | **0.131** |
| on_error='warn' · a valid call | **0.072** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.12** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.07** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.478** |
| protect · the awaitable raises | **0.631** |
| Self: a Base where a Child is expected (raise + catch) | **1.08** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.30 | 2.18 | **0.936** | 0.942 | n/a | 31.1 | 2.69 | n/a |
| 3 wrong args of 12 | 4.96 | 4.74 | **1.64** | 1.68 | n/a | 30.2 | 3.39 | n/a |
| missing argument | 2.38 | 2.15 | 1.04 | 1.04 | n/a | 0.423 | **0.201** | n/a |
| unknown keyword argument | 1.13 | 1.04 | 1.02 | 1.03 | n/a | 0.483 | **0.156** | n/a |
| wrong keyword-only argument | 2.54 | 2.42 | **1.06** | 1.06 | n/a | 30.7 | 2.77 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.38 | 7.36 | n/a | no err | **3.26** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.23 | **2.13** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.14 | 2.03 | no err | **0.923** | n/a | 28.8 | 2.77 | n/a |
| dataclass field wrong type | 2.67 | 2.58 | 1.25 | 1.22 | **0.973** | 32.2 | no err | 1.93 |
| dataclass assignment wrong type | 2.90 | 2.34 | 0.938 | **0.896** | 1.69 | no err | no err | 1.80 |
| value check fails (int > 0 ← -5) | 2.42 | 2.31 | 1.04 | **1.03** | n/a | 44.6 | n/a | n/a |
| invalid email | 2.47 | 2.36 | 1.18 | **1.18** | n/a | 44.7 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.055 | 0.058 | 0.056 | 0.204 | 0.205 | 0.073 | 1.14 |
| 2 params | 0.066 | 0.069 | 0.066 | 0.214 | 0.213 | 0.089 | 1.64 |
| 4 params | 0.092 | 0.097 | 0.092 | 0.242 | 0.242 | 0.121 | 2.60 |
| 8 params | 0.151 | 0.153 | 0.151 | 0.298 | 0.297 | 0.188 | 4.51 |
| 16 params | 0.253 | 0.256 | 0.253 | 0.389 | 0.390 | 0.309 | 8.21 |
| 32 params | 0.457 | 0.461 | 0.461 | 0.625 | 0.633 | 0.553 | 15.8 |
| fixed cost (ns) | 42 | 45 | 42 | 187 | 186 | 60 | 697 |
| per param (ns) | 13.0 | 13.0 | 13.1 | 13.5 | 13.8 | 15.5 | 471.7 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.260 | 0.290 | 0.260 | 0.410 | 148 | 0.0 |
| enforced | 263.6 | 9.38 | 51.2 | 5.86 | 80.6 | 253 | 8.6 |
| enf.coerce | 275.2 | 7.67 | 54.7 | 6.28 | 87.7 | 242 | 10.4 |
| enf.deep | 262.5 | 9.58 | 54.5 | 6.33 | 87.7 | 244 | 8.6 |
| pydantic | 66.3 | 186 | 5.52 | 285 | 2.58 | 414 | 4.0 |
| pyd.strict | 64.6 | 183 | 5.78 | 277 | 2.56 | 423 | 4.0 |
| pyd.model | 54.8 | n/a | n/a | n/a | n/a | 235 | n/a |
| beartype | 55.9 | 247 | 1.38 | 563 | 2.34 | 559 | 2.8 |
| typeguard | 72.5 | 2,301 | 15.6 | 2,371 | 19.3 | 4,254 | 1.7 |
| attrs | 24.8 | n/a | n/a | n/a | n/a | 260 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 11 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 29 |
| pydantic | 2.50× slower  (32 cases) | 1.33× faster  (9 cases) | 1 |
| pyd.strict | 2.50× slower  (32 cases) | 1.27× faster  (10 cases) | 1 |
| pyd.model | 2.45× slower  (2 cases) | 1.37× faster  (2 cases) | 0 |
| beartype | 1.16× slower  (30 cases) | 16.64× slower  (9 cases) | 8 |
| typeguard | 20.64× slower  (27 cases) | 1.48× slower  (6 cases) | 0 |
| attrs | 1.18× slower  (2 cases) | 1.06× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
