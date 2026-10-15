# enforced comparison

*2026-10-15 21:08*

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
| 1 param | 0.011\~ | **0.068\~** | 0.072 | 0.070 | 0.219 | 0.220 | 0.090\~ | 1.19 |
| 2 params · positional | 0.011 | **0.077** | **0.079** | **0.077\~** | 0.229 | 0.231 | 0.106 | 1.69 |
| 2 params · keyword | 0.018 | **0.165** | 0.173 | **0.164** | 0.486 | 0.490 | 0.178 | 1.72 |
| 5 params · mixed types | 0.013 | **0.104** | **0.104** | **0.104** | 0.276 | 0.281 | 0.157 | 2.91 |
| 12 params · positional | 0.019 | **0.204** | **0.203** | **0.202** | 0.364 | 0.356 | 0.276 | 5.95 |
| 12 params · keyword | 0.039 | **0.662** | **0.662** | **0.660** | 1.56 | 1.57 | 0.687 | 5.95 |
| defaults used (1 of 5 given) | 0.017 | 0.175 | 0.172 | 0.174 | 0.586 | 0.581 | **0.153** | 4.90 |
| keyword-only params | 0.020 | **0.167** | **0.166** | **0.166** | 0.393 | 0.394 | **0.165** | 2.04 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.211** | **0.214** | **0.213** | 0.494 | 0.498 | 0.231 | 5.86 |
| unions · int \| str \| None, float \| None | 0.011 | **0.087** | **0.087** | **0.087** | 0.273 | 0.262 | 0.116 | 4.04 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.242** | **0.242** | **0.241** | 0.497 | 0.494 | **0.237** | 6.54 |
| user-defined classes | 0.013 | **0.075** | **0.075** | **0.075** | 0.229 | 0.231 | 0.109 | 1.66 |
| Any / object | 0.011 | 0.059 | 0.059 | 0.060 | 0.222 | 0.224 | **0.011** | 1.17 |
| \*args / \*\*kwargs (3 + 2) | 0.043 | **0.260** | **0.260** | **0.261** | 0.427 | 0.428 | 0.509 | 4.09 |
| return value checked | 0.011 | **0.080** | 0.082 | **0.078** | 0.247 | 0.248 | 0.092 | 1.66 |
| async def (coroutine driven) | 0.101 | **0.196** | 0.208 | **0.195** | 0.453 | 0.458 | 0.241 | 1.84 |
| method on an instance | 0.012 | **0.079** | 0.084 | 0.082 | 0.244 | 0.244 | 0.109 | 1.69 |
| positional-only params · one default used | 0.016 | 0.129 | 0.129 | 0.128 | 0.406 | 0.404 | **0.113** | 2.03 |
| float params given ints (numeric tower) | 0.013 | 0.281 | 0.304 | 0.282 | **0.264** | **0.261** | ERR | 1.32 |
| Callable · Iterable | 0.013 | **0.168** | **0.168** | **0.169** | 0.336 | 0.340 | 0.510 | 6.31 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.064† | 0.069† | **0.190** | 0.335 | 0.334 | 0.134† | 1.97† |
| list[int] × 1,000 | 0.012 | 0.063† | 0.068† | **5.03** | 6.91 | 6.82 | 0.143† | 1.95† |
| list[int] × 100,000 | 0.012 | 0.064† | 0.067† | **474** | 1,092 | 1,097 | 0.159† | 1.95† |
| dict[str, int] × 100 | 0.012 | 0.065† | 0.063† | **1.37** | 2.24 | 2.25 | 0.139† | 2.54† |
| tuple[int, str, float] | 0.012 | 0.064† | 0.067† | **0.118** | 0.273 | 0.273 | **0.118** | 2.97 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.064† | 0.064† | **1.31** | 1.41 | 1.41 | 0.189† | 3.35† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.112† | 0.111† | **2.06** | 4.54 | 4.52 | 0.312† | 3.21† |
| TypedDict (4 keys, one a list) | 0.012 | 0.064† | 0.064† | **0.306** | 0.426 | 0.427 | 0.175† | 5.00 |
| list of 100 objects | 0.012 | 0.064† | 0.067† | **0.667** | 0.876 | 0.867 | 0.139† | 1.94† |
| set[str] × 100 | 0.012 | **0.063** | 0.069 | 0.723 | 1.72 | 1.72 | 0.122 | 2.14 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.067† | **5.83** | 6.87 | 6.90 | 0.153† | 3.80† |
| tuple[int, ...] × 1,000 | 0.012 | 0.064† | 0.067† | **4.88** | 6.24 | 6.27 | 0.146† | 2.16† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.096 | 0.429 | 0.429 | 0.431 | 0.602 | 0.598 | 0.401 | 0.331 | 0.095† | **0.308** |
| construct Order tree (5 objects) | 0.462 | 2.01† | 2.07† | 2.21 | 2.87 | 2.84 | 1.95 | 1.72 | 0.462† | **1.55** |
| assign point.x = 5 | 0.004 | **0.061** | **0.061** | **0.061** | 0.272 | 0.267 | 0.362 | 0.004† | 0.004† | 0.125 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.094** | 0.100 | **0.096** | 0.226 | 0.228 | 0.124 |
| list[int > 0] × 1,000 | 0.012 | 0.065† | 0.068† | **20.0** | 21.4 | 21.7 | 0.184† |
| email · already valid str | 0.010 | 0.914 | 0.911 | 0.909 | 0.966 | 0.966 | **0.794** |
| email · normalised (domain lower-cased) | 0.010 | 0.913≠ | 0.922≠ | 0.914≠ | 0.969≠ | 0.966≠ | **0.800** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.584 | 0.728 | 0.580 | **0.476** | **0.473** | n/a | 30.8 | 2.49 | n/a |
| 3 wrong args of 12 | 1.14 | 2.20 | 1.17 | **0.701** | 0.782 | n/a | 30.6 | 3.23 | n/a |
| missing argument | 0.571 | 0.586 | 0.573 | 0.525 | 0.531 | n/a | 0.400 | **0.174** | n/a |
| unknown keyword argument | 0.719 | 0.725 | 0.721 | 0.574 | 0.573 | n/a | 0.441 | **0.134** | n/a |
| wrong keyword-only argument | 0.817 | 0.890 | 0.812 | **0.595** | **0.594** | n/a | 31.2 | 2.57 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.6 | 6.83 | 6.79 | n/a | no err | **3.06** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 7.64 | **1.66** | **1.67** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.476** | **0.487** | **0.474** | no err | 0.541 | n/a | 29.4 | 2.52 | n/a |
| dataclass field wrong type | 0.992 | 1.43 | 0.985 | 0.793 | 0.780 | **0.493** | 33.7 | no err | 0.706 |
| dataclass assignment wrong type | **0.431** | 1.29 | **0.432** | 0.481 | 0.468 | 0.451 | no err | no err | 0.555 |
| value check fails (int > 0 ← -5) | 0.957 | 1.04 | 0.959 | **0.487** | **0.490** | n/a | 45.4 | n/a | n/a |
| invalid email | 0.997 | 0.989 | 0.990 | **0.663** | **0.672** | n/a | 44.8 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.243** |
| typecheck_record · cached spec | **1.07** |
| -> Self · called on the class that defines it | **0.078** |
| -> Self · called on a subclass | **0.090** |
| other: Self · called on a subclass | **0.097** |
| Self \| None · called on a subclass (a wrapper per class) | **0.206** |
| class method -> Self · called on a subclass | **0.206** |
| a method of a dataclass · row.scaled(2) | **0.133** |
| the same method under enforce · plain.scaled(2) | **0.134** |
| on_error='warn' · a valid call | **0.075** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **2.84** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **2.88** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.475** |
| protect · the awaitable raises | **0.631** |
| Self: a Base where a Child is expected (raise + catch) | **1.08** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.21 | 2.08 | 0.950 | **0.940** | n/a | 30.9 | 2.68 | n/a |
| 3 wrong args of 12 | 4.85 | 4.63 | **1.65** | 1.71 | n/a | 30.1 | 3.38 | n/a |
| missing argument | 2.26 | 2.05 | 1.04 | 1.02 | n/a | 0.421 | **0.200** | n/a |
| unknown keyword argument | 1.10 | 1.03 | 1.02 | 1.00 | n/a | 0.475 | **0.159** | n/a |
| wrong keyword-only argument | 2.45 | 2.34 | **1.05** | 1.05 | n/a | 31.5 | 2.78 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.37 | 7.30 | n/a | no err | **3.28** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.14 | **2.14** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.05 | 1.92 | no err | **0.929** | n/a | 28.9 | 2.74 | n/a |
| dataclass field wrong type | 2.61 | 2.45 | 1.25 | 1.21 | **0.961** | 31.0 | no err | 1.94 |
| dataclass assignment wrong type | 2.78 | 2.24 | 0.916 | **0.881** | 1.64 | no err | no err | 1.75 |
| value check fails (int > 0 ← -5) | 2.34 | 2.20 | 1.02 | **1.02** | n/a | 43.8 | n/a | n/a |
| invalid email | 2.39 | 2.24 | **1.20** | 1.20 | n/a | 44.9 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.056 | 0.060 | 0.056 | 0.206 | 0.205 | 0.076 | 1.14 |
| 2 params | 0.071 | 0.072 | 0.070 | 0.218 | 0.215 | 0.095 | 1.66 |
| 4 params | 0.094 | 0.097 | 0.095 | 0.243 | 0.243 | 0.125 | 2.61 |
| 8 params | 0.150 | 0.153 | 0.150 | 0.295 | 0.295 | 0.190 | 4.55 |
| 16 params | 0.256 | 0.261 | 0.255 | 0.390 | 0.387 | 0.310 | 8.18 |
| 32 params | 0.459 | 0.487 | 0.455 | 0.625 | 0.622 | 0.557 | 15.9 |
| fixed cost (ns) | 44 | 43 | 45 | 189 | 187 | 64 | 697 |
| per param (ns) | 13.0 | 13.8 | 12.9 | 13.4 | 13.4 | 15.4 | 473.7 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.310 | 0.270 | 0.280 | 0.410 | 178 | 0.0 |
| enforced | 266.2 | 7.47 | 50.1 | 8.06 | 76.7 | 240 | 8.6 |
| enf.coerce | 262.5 | 7.99 | 58.0 | 6.30 | 85.1 | 238 | 10.4 |
| enf.deep | 261.0 | 7.42 | 50.3 | 8.11 | 80.0 | 233 | 8.6 |
| pydantic | 65.3 | 179 | 5.75 | 280 | 2.68 | 429 | 4.0 |
| pyd.strict | 65.5 | 183 | 6.10 | 283 | 2.54 | 419 | 4.0 |
| pyd.model | 53.5 | n/a | n/a | n/a | n/a | 237 | n/a |
| beartype | 56.6 | 244 | 1.41 | 611 | 2.76 | 526 | 2.8 |
| typeguard | 73.3 | 2,280 | 15.3 | 2,544 | 20.8 | 4,214 | 1.7 |
| attrs | 24.9 | n/a | n/a | n/a | n/a | 293 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 12 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 28 |
| pydantic | 2.46× slower  (32 cases) | 1.32× faster  (9 cases) | 1 |
| pyd.strict | 2.46× slower  (32 cases) | 1.26× faster  (10 cases) | 1 |
| pyd.model | 2.36× slower  (2 cases) | 1.39× faster  (2 cases) | 0 |
| beartype | 1.16× slower  (30 cases) | 16.75× slower  (9 cases) | 8 |
| typeguard | 20.36× slower  (27 cases) | 1.50× slower  (6 cases) | 0 |
| attrs | 1.21× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 19 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
