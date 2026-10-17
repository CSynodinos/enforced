# enforced comparison

*2026-10-17 11:09*

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
| 1 param | 0.010 | **0.064** | 0.068 | **0.064** | 0.230 | 0.232 | 0.093 | 1.15 |
| 2 params · positional | 0.011 | **0.073** | 0.077 | **0.073** | 0.244 | 0.243 | 0.110 | 1.64 |
| 2 params · keyword | 0.017 | **0.162** | **0.167** | **0.163** | 0.490 | 0.497 | 0.175 | 1.69 |
| 5 params · mixed types | 0.013 | **0.103** | **0.104** | **0.103** | 0.295 | 0.297 | 0.161 | 2.93 |
| 12 params · positional | 0.019 | **0.201** | **0.200** | **0.200** | 0.384 | 0.380 | 0.281 | 5.91 |
| 12 params · keyword | 0.039 | **0.657** | **0.662** | **0.662** | 1.52 | 1.54 | 0.693 | 5.98 |
| defaults used (1 of 5 given) | 0.016 | 0.186 | 0.186 | 0.185 | 0.605 | 0.604 | **0.164** | 5.02 |
| keyword-only params | 0.019 | 0.166 | 0.166 | 0.164 | 0.419 | 0.419 | **0.159** | 2.03 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.209** | **0.212** | **0.213** | 0.540 | 0.541 | 0.236 | 6.03 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.086** | **0.085** | 0.284 | 0.276 | 0.127 | 4.09 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.014 | **0.238** | **0.238** | **0.236** | 0.504 | 0.506 | 0.246 | 6.65 |
| user-defined classes | 0.013 | **0.072** | **0.072** | **0.073** | 0.237 | 0.238 | 0.123 | 1.66 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.054 | 0.246 | 0.245 | **0.011** | 1.16 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.258** | **0.260** | **0.258** | 0.441 | 0.441 | 0.519 | 4.13 |
| return value checked | 0.011 | **0.076** | 0.080 | **0.077** | 0.264 | 0.264 | 0.101 | 1.64 |
| async def (coroutine driven) | 0.102 | **0.196** | 0.207 | **0.198** | 0.469 | 0.469 | 0.258 | 1.83 |
| method on an instance | 0.012 | **0.079** | 0.083 | **0.079** | 0.273 | 0.273 | 0.116 | 1.70 |
| positional-only params · one default used | 0.014 | 0.137 | 0.137 | 0.136 | 0.442 | 0.439 | **0.121** | 2.01 |
| float params given ints (numeric tower) | 0.012 | **0.279** | 0.305 | **0.282** | **0.281** | **0.277** | ERR | 1.31 |
| Callable · Iterable | 0.013 | **0.164** | **0.165** | **0.165** | 0.346 | 0.347 | 0.518 | 6.24 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.068† | **0.188** | 0.342 | 0.342 | 0.143† | 1.95† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.069† | **4.98** | 6.85 | 6.87 | 0.153† | 1.96† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.068† | **468** | 1,083 | 1,080 | 0.162† | 1.93† |
| dict[str, int] × 100 | 0.012 | 0.063† | 0.062† | **1.34** | 2.31 | 2.32 | 0.148† | 2.51† |
| tuple[int, str, float] | 0.012 | 0.062† | 0.068† | **0.118** | 0.281 | 0.282 | 0.126 | 2.96 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.062† | **1.29** | 1.44 | 1.44 | 0.200† | 3.29† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.110† | 0.110† | **2.07** | 4.59 | 4.61 | 0.311† | 3.25† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.062† | **0.301** | 0.424 | 0.423 | 0.197† | 5.02 |
| list of 100 objects | 0.012 | 0.062† | 0.069† | **0.661** | 0.905 | 0.907 | 0.147† | 1.93† |
| set[str] × 100 | 0.012 | **0.063** | 0.069 | 0.739 | 1.74 | 1.75 | 0.131 | 2.14 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.068† | **5.85** | 6.95 | 6.94 | 0.161† | 3.82† |
| tuple[int, ...] × 1,000 | 0.014 | 0.062† | 0.068† | **4.90** | 6.28 | 6.34 | 0.153† | 2.16† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.100 | 0.448 | 0.446 | 0.445 | 0.600 | 0.601 | 0.401 | 0.349 | 0.099† | **0.311** |
| construct Order tree (5 objects) | 0.464 | 2.03† | 2.10† | 2.23 | 2.87 | 2.87 | 1.92 | 1.77 | 0.464† | **1.56** |
| assign point.x = 5 | 0.004 | **0.060** | **0.061** | **0.062** | 0.279 | 0.279 | 0.372 | 0.004† | 0.004† | 0.122 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.092** | 0.096 | **0.093** | 0.244 | 0.243 | 0.133 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.068† | **19.6** | 22.0 | 22.0 | 0.193† |
| email · already valid str | 0.010 | 0.945 | 0.944 | 0.960 | 0.993 | 0.992 | **0.833** |
| email · normalised (domain lower-cased) | 0.010 | 0.936≠ | 0.932≠ | 0.933≠ | 0.978≠ | 0.984≠ | **0.820** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.580 | 0.731 | 0.580 | **0.501** | **0.494** | n/a | 31.5 | 2.49 | n/a |
| 3 wrong args of 12 | 1.16 | 2.21 | 1.15 | **0.709** | 0.788 | n/a | 31.5 | 3.22 | n/a |
| missing argument | 0.579 | 0.582 | 0.578 | 0.527 | 0.529 | n/a | 0.413 | **0.174** | n/a |
| unknown keyword argument | 0.744 | 0.755 | 0.742 | 0.589 | 0.591 | n/a | 0.464 | **0.134** | n/a |
| wrong keyword-only argument | 0.830 | 0.897 | 0.833 | **0.625** | **0.620** | n/a | 32.1 | 2.59 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.9 | 6.92 | 6.95 | n/a | no err | **3.02** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 8.07 | **1.68** | **1.65** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.488** | **0.492** | **0.481** | no err | 0.572 | n/a | 31.8\~ | 2.59 | n/a |
| dataclass field wrong type | 0.984 | 1.45\~ | 0.993 | 0.799\~ | 0.779 | **0.502** | 33.5 | no err | 0.735 |
| dataclass assignment wrong type | **0.431** | 1.30 | **0.434** | 0.483 | 0.472 | 0.459 | no err | no err | 0.555 |
| value check fails (int > 0 ← -5) | 0.982 | 1.07 | 0.968 | **0.485** | **0.483** | n/a | 45.1 | n/a | n/a |
| invalid email | 1.01 | 1.01 | 1.00 | **0.675** | **0.673** | n/a | 46.6 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.227** |
| typecheck_record · cached spec | **1.10** |
| -> Self · called on the class that defines it | **0.076** |
| -> Self · called on a subclass | **0.085** |
| other: Self · called on a subclass | **0.096** |
| Self \| None · called on a subclass (a wrapper per class) | **0.209** |
| class method -> Self · called on a subclass | **0.220\~** |
| a method of a dataclass · row.scaled(2) | **0.148** |
| the same method under enforce · plain.scaled(2) | **0.149** |
| on_error='warn' · a valid call | **0.074** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.05** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.07** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.473** |
| protect · the awaitable raises | **0.645\~** |
| Self: a Base where a Child is expected (raise + catch) | **1.09** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.34 | 2.21 | 0.987 | **0.974** | n/a | 31.8 | 2.83 | n/a |
| 3 wrong args of 12 | 4.91 | 4.71 | **1.73** | 1.77 | n/a | 31.3 | 3.50 | n/a |
| missing argument | 2.37 | 2.12 | 1.09 | 1.08 | n/a | 0.438 | **0.202** | n/a |
| unknown keyword argument | 1.11 | 1.02 | 1.05 | 1.06 | n/a | 0.493 | **0.158** | n/a |
| wrong keyword-only argument | 2.57 | 3.02 | **1.11** | 1.11 | n/a | 32.8 | 2.86 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.49 | 7.39 | n/a | no err | **3.34** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.20 | **2.15** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.18 | 2.06 | no err | **0.956** | n/a | 30.5 | 2.82 | n/a |
| dataclass field wrong type | 2.67 | 2.56 | 1.28 | 1.27 | **1.000** | 32.0 | no err | 1.99 |
| dataclass assignment wrong type | 2.87 | 2.34 | 0.942 | **0.907** | 1.73 | no err | no err | 1.80 |
| value check fails (int > 0 ← -5) | 2.42 | 2.34 | **1.04** | 1.05 | n/a | 44.9 | n/a | n/a |
| invalid email | 2.45 | 2.39 | 1.21 | **1.19** | n/a | 45.8 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.055 | 0.058 | 0.055 | 0.224 | 0.225 | 0.085 | 1.14 |
| 2 params | 0.068 | 0.073 | 0.068 | 0.241 | 0.236 | 0.102 | 1.63 |
| 4 params | 0.094 | 0.096 | 0.094 | 0.271 | 0.271 | 0.132 | 2.66 |
| 8 params | 0.150 | 0.155 | 0.149 | 0.321 | 0.323 | 0.201 | 4.55 |
| 16 params | 0.258 | 0.263 | 0.261 | 0.417 | 0.415 | 0.324 | 8.36 |
| 32 params | 0.462 | 0.467 | 0.466 | 0.672 | 0.662 | 0.577 | 16.1 |
| fixed cost (ns) | 43 | 47 | 43 | 208 | 209 | 70 | 690 |
| per param (ns) | 13.2 | 13.2 | 13.3 | 14.2 | 13.9 | 15.9 | 480.5 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.270 | 0.260 | 0.240 | 0.430 | 156 | 0.0 |
| enforced | 276.8 | 9.03 | 48.6 | 5.54 | 74.5 | 259 | 8.6 |
| enf.coerce | 275.2 | 9.13 | 52.1 | 5.77 | 84.5 | 225 | 10.4 |
| enf.deep | 278.2 | 9.65 | 51.1 | 5.91 | 79.3 | 233 | 8.6 |
| pydantic | 68.0 | 187 | 5.59 | 270 | 2.57 | 455 | 4.0 |
| pyd.strict | 67.6 | 202 | 6.38 | 275 | 2.61 | 452 | 4.0 |
| pyd.model | 57.0 | n/a | n/a | n/a | n/a | 278 | n/a |
| beartype | 61.0 | 310 | 1.46 | 601 | 2.62 | 542 | 2.8 |
| typeguard | 78.9 | 2,364 | 16.0 | 2,472 | 20.3 | 4,309 | 1.7 |
| attrs | 27.0 | n/a | n/a | n/a | n/a | 303 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 11 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× faster  (10 cases) | 30 |
| pydantic | 2.62× slower  (32 cases) | 1.31× faster  (9 cases) | 1 |
| pyd.strict | 2.62× slower  (32 cases) | 1.25× faster  (10 cases) | 1 |
| pyd.model | 2.35× slower  (2 cases) | 1.36× faster  (2 cases) | 0 |
| beartype | 1.22× slower  (30 cases) | 17.02× slower  (9 cases) | 6 |
| typeguard | 20.63× slower  (27 cases) | 1.48× slower  (6 cases) | 0 |
| attrs | 1.19× slower  (2 cases) | 1.02× faster  (2 cases) | 2 |
| enforced | reference | reference | 19 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
