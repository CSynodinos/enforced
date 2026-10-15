# enforced comparison

*2026-10-16 00:30*

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
| 1 param | 0.010 | **0.066** | 0.069 | **0.066** | 0.217 | 0.219 | 0.085 | 1.17 |
| 2 params · positional | 0.011 | **0.075** | **0.077** | **0.075** | 0.227 | 0.231 | 0.104 | 1.69 |
| 2 params · keyword | 0.017 | **0.164** | 0.171 | **0.166** | 0.485 | 0.491 | 0.177 | 1.70 |
| 5 params · mixed types | 0.013 | **0.104** | **0.104** | **0.104** | 0.278 | 0.276 | 0.152 | 2.96 |
| 12 params · positional | 0.019 | **0.203** | **0.205** | **0.202** | 0.362 | 0.359 | 0.271 | 5.95 |
| 12 params · keyword | 0.039 | **0.664** | **0.664** | **0.657** | 1.50 | 1.51 | **0.675** | 6.02 |
| defaults used (1 of 5 given) | 0.015 | 0.175 | 0.173 | 0.177 | 0.577 | 0.576 | **0.152** | 4.96 |
| keyword-only params | 0.019 | 0.174 | 0.167 | 0.170 | 0.393 | 0.393 | **0.161** | 2.07 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.210** | **0.212** | **0.212** | 0.503 | 0.501 | 0.228 | 5.99 |
| unions · int \| str \| None, float \| None | 0.011 | **0.085** | **0.085** | **0.085** | 0.312 | 0.289 | 0.116 | 4.04 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.242** | **0.242** | **0.243** | 0.506 | 0.507 | **0.239** | 6.67 |
| user-defined classes | 0.013 | **0.075** | **0.075** | **0.075** | 0.230 | 0.229 | 0.112 | 1.70 |
| Any / object | 0.011 | 0.056 | 0.057 | 0.056 | 0.221 | 0.221 | **0.011** | 1.18 |
| \*args / \*\*kwargs (3 + 2) | 0.043 | **0.258** | **0.258** | **0.258** | 0.430 | 0.428 | 0.539 | 4.17 |
| return value checked | 0.011 | **0.078** | 0.081 | **0.079** | 0.277 | 0.278 | 0.093 | 1.67 |
| async def (coroutine driven) | 0.102 | **0.200** | 0.208 | **0.199** | 0.451 | 0.455 | 0.247 | 1.86 |
| method on an instance | 0.012 | **0.079** | 0.082 | **0.078** | 0.244 | 0.241 | 0.105 | 1.73 |
| positional-only params · one default used | 0.014 | 0.126 | 0.128 | 0.125 | 0.406 | 0.406 | **0.112** | 2.08 |
| float params given ints (numeric tower) | 0.013 | 0.276 | 0.301 | 0.277 | **0.263** | **0.263** | ERR | 1.34 |
| Callable · Iterable | 0.013 | **0.172** | **0.175** | **0.175** | 0.375 | 0.375 | 0.516 | 6.34 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.064† | 0.066† | **0.194** | 0.365 | 0.363 | 0.136† | 1.98† |
| list[int] × 1,000 | 0.012 | 0.063† | 0.067† | **5.04** | 6.87 | 6.85 | 0.147† | 1.98† |
| list[int] × 100,000 | 0.012 | 0.063† | 0.066† | **471** | 1,116 | 1,091 | 0.170†\~ | 1.97† |
| dict[str, int] × 100 | 0.012 | 0.064† | 0.063† | **1.35** | 2.34 | 2.33 | 0.139† | 2.56† |
| tuple[int, str, float] | 0.012 | 0.064† | 0.066† | **0.119** | 0.274 | 0.272 | **0.116** | 3.04 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.063† | 0.063† | **1.32** | 1.44 | 1.43 | 0.192† | 3.30† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.114† | 0.115† | **2.08** | 4.73 | 4.63 | 0.301† | 3.30† |
| TypedDict (4 keys, one a list) | 0.012 | 0.064† | 0.063† | **0.305** | 0.420 | 0.423 | 0.176† | 5.13 |
| list of 100 objects | 0.012 | 0.063† | 0.066† | **0.666** | 0.881 | 0.882 | 0.139† | 1.94† |
| set[str] × 100 | 0.012 | **0.064** | 0.066 | 0.753 | 1.73 | 1.72 | 0.122 | 2.15 |
| list[int \| None] × 1,000 | 0.012 | 0.064† | 0.067† | **5.83** | 7.00 | 7.00 | 0.156† | 3.88† |
| tuple[int, ...] × 1,000 | 0.012 | 0.064† | 0.067† | **4.93** | 6.31 | 6.33 | 0.147† | 2.20† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.100 | 0.435 | 0.436 | 0.438 | 0.592 | 0.593 | 0.398 | 0.337 | 0.098† | **0.306** |
| construct Order tree (5 objects) | 0.469 | 2.03† | 2.09† | 2.26 | 2.90 | 2.88 | 1.98 | 1.75 | 0.469† | **1.54** |
| assign point.x = 5 | 0.004 | **0.061** | **0.062** | **0.061** | 0.278 | 0.277 | 0.379 | 0.004† | 0.004† | 0.125 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.099** | **0.098** | **0.098** | 0.229 | 0.230 | 0.124 |
| list[int > 0] × 1,000 | 0.012 | 0.063† | 0.066† | **20.0** | 22.2 | 22.1 | 0.188† |
| email · already valid str | 0.010 | 0.956 | 0.972 | 0.960 | 1.01 | 1.01 | **0.842** |
| email · normalised (domain lower-cased) | 0.011 | 0.965≠ | 0.962≠ | 0.965≠ | 1.02≠ | 1.01≠ | **0.852** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.589 | 0.739 | 0.587 | **0.483** | **0.481** | n/a | 32.0 | 2.52 | n/a |
| 3 wrong args of 12 | 1.18 | 2.27 | 1.17 | **0.707** | 0.782 | n/a | 31.1 | 3.23 | n/a |
| missing argument | 0.586 | 0.598 | 0.584 | 0.539 | 0.532 | n/a | 0.408 | **0.175** | n/a |
| unknown keyword argument | 0.729 | 0.741 | 0.736 | 0.581 | 0.579 | n/a | 0.446 | **0.133** | n/a |
| wrong keyword-only argument | 0.829 | 0.897 | 0.825 | **0.605** | **0.598** | n/a | 32.0 | 2.70 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 24.8 | 6.95 | 6.88 | n/a | no err | **3.03** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 7.84 | **1.67** | **1.66** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.487** | **0.498** | **0.498** | no err | 0.566 | n/a | 35.5\~ | 2.63 | n/a |
| dataclass field wrong type | 0.992 | 1.45 | 0.984 | 0.795 | 0.781 | **0.505** | 32.9 | no err | 0.705 |
| dataclass assignment wrong type | **0.425** | 1.29 | **0.422** | 0.479 | 0.477 | 0.455 | no err | no err | 0.544 |
| value check fails (int > 0 ← -5) | 0.967 | 1.05 | 0.973 | **0.485** | **0.479** | n/a | 45.0 | n/a | n/a |
| invalid email | 1.01 | 1.01 | 0.995 | **0.670** | **0.670** | n/a | 45.5 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.227** |
| typecheck_record · cached spec | **1.08** |
| -> Self · called on the class that defines it | **0.076** |
| -> Self · called on a subclass | **0.086** |
| other: Self · called on a subclass | **0.096** |
| Self \| None · called on a subclass (a wrapper per class) | **0.196** |
| class method -> Self · called on a subclass | **0.203** |
| a method of a dataclass · row.scaled(2) | **0.133** |
| the same method under enforce · plain.scaled(2) | **0.133** |
| on_error='warn' · a valid call | **0.075** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **3.04** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **3.04** |
| Ok(value) | **0.070** |
| protect · the awaitable completes | **0.475** |
| protect · the awaitable raises | **0.646** |
| Self: a Base where a Child is expected (raise + catch) | **1.09** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.36 | 2.19 | 0.950 | **0.938** | n/a | 31.2 | 2.74 | n/a |
| 3 wrong args of 12 | 4.99 | 4.78 | **1.67** | 1.68 | n/a | 30.6 | 3.45 | n/a |
| missing argument | 2.35 | 2.16 | 1.04 | 1.02 | n/a | 0.421 | **0.194** | n/a |
| unknown keyword argument | 1.15 | 1.02 | 1.02 | 1.01 | n/a | 0.480 | **0.156** | n/a |
| wrong keyword-only argument | 2.55 | 2.38 | 1.08 | **1.07** | n/a | 30.7 | 2.77 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.35 | 7.34 | n/a | no err | **3.30** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.16 | **2.11** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.20 | 2.02 | no err | **0.916** | n/a | 29.1 | 2.75 | n/a |
| dataclass field wrong type | 2.66 | 2.54 | 1.27 | 1.23 | **0.966** | 31.9 | no err | 1.93 |
| dataclass assignment wrong type | 2.90 | 2.35 | 0.936 | **0.896** | 1.66 | no err | no err | 1.77 |
| value check fails (int > 0 ← -5) | 2.47 | 2.33 | **1.01** | 1.03 | n/a | 44.0 | n/a | n/a |
| invalid email | 2.47 | 2.33 | 1.22 | **1.19** | n/a | 44.6 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.057 | 0.059 | 0.057 | 0.210 | 0.206 | 0.076 | 1.16 |
| 2 params | 0.067 | 0.069 | 0.067 | 0.216 | 0.216 | 0.089 | 1.67 |
| 4 params | 0.092 | 0.098 | 0.093 | 0.245 | 0.246 | 0.125 | 2.71 |
| 8 params | 0.150 | 0.154 | 0.150 | 0.297 | 0.296 | 0.187 | 4.68 |
| 16 params | 0.253 | 0.257 | 0.253 | 0.391 | 0.390 | 0.312 | 8.18 |
| 32 params | 0.456 | 0.462 | 0.456 | 0.625 | 0.629 | 0.553 | 15.9 |
| fixed cost (ns) | 43 | 46 | 43 | 190 | 188 | 62 | 756 |
| per param (ns) | 13.0 | 13.0 | 13.0 | 13.4 | 13.6 | 15.4 | 472.1 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.270 | 0.260 | 0.260 | 0.410 | 148 | 0.0 |
| enforced | 262.8 | 7.36 | 52.2 | 5.84 | 76.9 | 219 | 8.6 |
| enf.coerce | 266.2 | 9.29 | 52.2 | 5.77 | 80.3 | 239 | 10.4 |
| enf.deep | 263.8 | 7.55 | 56.2 | 6.13 | 83.0 | 234 | 8.6 |
| pydantic | 66.9 | 206 | 8.27 | 287 | 2.60 | 419 | 4.0 |
| pyd.strict | 67.6 | 184 | 6.11 | 282 | 2.48 | 410 | 4.0 |
| pyd.model | 55.3 | n/a | n/a | n/a | n/a | 243 | n/a |
| beartype | 59.2 | 242 | 1.31 | 564 | 2.37 | 525 | 2.8 |
| typeguard | 74.5 | 2,331 | 17.0 | 2,367 | 20.3 | 4,229 | 1.6 |
| attrs | 25.7 | n/a | n/a | n/a | n/a | 266 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.30× slower  (10 cases) | 12 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× faster  (10 cases) | 29 |
| pydantic | 2.50× slower  (32 cases) | 1.33× faster  (9 cases) | 1 |
| pyd.strict | 2.50× slower  (32 cases) | 1.27× faster  (10 cases) | 1 |
| pyd.model | 2.38× slower  (2 cases) | 1.35× faster  (2 cases) | 0 |
| beartype | 1.16× slower  (30 cases) | 17.01× slower  (9 cases) | 9 |
| typeguard | 20.72× slower  (27 cases) | 1.50× slower  (6 cases) | 0 |
| attrs | 1.20× slower  (2 cases) | 1.05× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
