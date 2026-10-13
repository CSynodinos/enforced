# enforced comparison

*2026-10-13 23:01*

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
| 1 param | 0.010 | **0.064** | 0.067 | **0.065** | 0.213 | 0.215 | 0.088 | 1.15 |
| 2 params · positional | 0.011 | **0.072** | 0.076 | **0.072** | 0.223 | 0.223 | 0.103 | 1.65 |
| 2 params · keyword | 0.018 | **0.156** | 0.162 | **0.156** | 0.481 | 0.482 | 0.168 | 1.66 |
| 5 params · mixed types | 0.013 | **0.103** | **0.104** | **0.103** | 0.272 | 0.273 | 0.152 | 2.86 |
| 12 params · positional | 0.018 | **0.198** | **0.201** | **0.199** | 0.354 | 0.360 | 0.273 | 5.86 |
| 12 params · keyword | 0.038 | **0.640** | **0.642** | **0.641** | 1.47 | 1.47 | 0.670 | 5.90 |
| defaults used (1 of 5 given) | 0.015 | 0.173 | 0.173 | 0.174 | 0.568 | 0.570 | **0.154** | 4.84 |
| keyword-only params | 0.019 | **0.166** | **0.167** | **0.167** | 0.392 | 0.393 | **0.163** | 1.99 |
| Optional · Literal · Sequence · type[] | 0.015 | **0.205** | 0.211 | **0.204** | 0.496 | 0.504 | 0.233 | 5.80 |
| unions · int \| str \| None, float \| None | 0.011 | **0.083** | **0.083** | **0.084** | 0.274 | 0.258 | 0.115 | 3.99 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.014 | 0.237 | **0.233** | **0.233** | 0.500 | 0.496 | **0.228** | 6.42 |
| user-defined classes | 0.013 | **0.074** | **0.074** | **0.075** | 0.227 | 0.226 | 0.110 | 1.64 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.056 | 0.219 | 0.218 | **0.011** | 1.18 |
| \*args / \*\*kwargs (3 + 2) | 0.041 | **0.255** | **0.255** | **0.255** | 0.425 | 0.424 | 0.514 | 4.10 |
| return value checked | 0.010 | **0.077** | 0.080 | **0.078** | 0.244 | 0.244 | 0.092 | 1.63 |
| async def (coroutine driven) | 0.104 | **0.199** | 0.210 | **0.202** | 0.447 | 0.448 | 0.254 | 1.80 |
| method on an instance | 0.012 | **0.077** | 0.082 | **0.078** | 0.238 | 0.237 | 0.106 | 1.69 |
| positional-only params · one default used | 0.014 | 0.124 | 0.123 | 0.125 | 0.398 | 0.396 | **0.114** | 1.98 |
| float params given ints (numeric tower) | 0.012 | 0.272 | 0.305 | 0.274 | **0.260** | **0.257** | ERR | 1.30 |
| Callable · Iterable | 0.013 | **0.164** | **0.164** | **0.164** | 0.337 | 0.335 | 0.498 | 6.26 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.063† | 0.066† | **0.193** | 0.335 | 0.333 | 0.133† | 1.94† |
| list[int] × 1,000 | 0.012 | 0.063† | 0.066† | **5.44** | 6.93 | 6.81 | 0.148† | 1.95† |
| list[int] × 100,000 | 0.012 | 0.061† | 0.064† | **520** | 1,106 | 1,075 | 0.159† | 1.94† |
| dict[str, int] × 100 | 0.012 | 0.061† | 0.062† | **1.34** | 2.35 | 2.33 | 0.139† | 2.52† |
| tuple[int, str, float] | 0.012 | 0.062† | 0.065† | **0.116** | 0.270 | 0.269 | **0.116** | 2.95 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.061† | 0.061† | **1.28** | 1.40 | 1.39 | 0.189† | 3.32† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.109† | 0.109† | **2.06** | 4.64 | 4.61 | 0.300† | 3.22† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.061† | **0.299** | 0.422 | 0.420 | 0.172† | 4.98 |
| list of 100 objects | 0.012 | 0.062† | 0.065† | **0.697** | 0.870 | 0.872 | 0.139† | 1.94† |
| set[str] × 100 | 0.012 | **0.062** | 0.065 | 0.717 | 1.69 | 1.70 | 0.120 | 2.11 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.064† | **6.29** | 7.07 | 6.88 | 0.153† | 3.77† |
| tuple[int, ...] × 1,000 | 0.012 | 0.063† | 0.066† | **4.88** | 6.18 | 6.18 | 0.147† | 2.15† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.096 | 0.431 | 0.432 | 0.430 | 0.580 | 0.583 | 0.390 | 0.333 | 0.097† | **0.301** |
| construct Order tree (5 objects) | 0.455 | 1.99† | 2.06† | 2.18 | 2.82 | 2.82 | 1.90 | 1.73 | 0.457† | **1.56** |
| assign point.x = 5 | 0.004 | 0.062 | **0.060** | **0.060** | 0.274 | 0.275 | 0.373 | 0.004† | 0.004† | 0.121 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.092** | 0.095 | **0.092** | 0.226 | 0.224 | 0.122 |
| list[int > 0] × 1,000 | 0.012 | 0.061† | 0.065† | **19.4** | 22.2 | 22.2 | 0.184† |
| email · already valid str | 0.010 | 1.02 | 1.02 | 1.02 | 0.971 | 0.970 | **0.816** |
| email · normalised (domain lower-cased) | 0.010 | 1.02≠ | 1.02≠ | 1.02≠ | 0.968≠ | 0.982≠ | **0.819** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.562 | 0.633 | 0.562 | **0.471** | **0.467** | n/a | 31.4 | 2.48 | n/a |
| 3 wrong args of 12 | 1.13 | 2.06 | 1.12 | **0.692** | 0.783 | n/a | 30.4 | 3.16 | n/a |
| missing argument | 0.569 | 0.577 | 0.566 | 0.534 | 0.528 | n/a | 0.404 | **0.174** | n/a |
| unknown keyword argument | 0.718 | 0.723 | 0.718 | 0.577 | 0.574 | n/a | 0.433 | **0.133** | n/a |
| wrong keyword-only argument | 0.793 | 0.866 | 0.789 | **0.588** | **0.587** | n/a | 31.4 | 2.57 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 29.5 | 6.92 | 6.84 | n/a | no err | **3.00** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.16 | **1.67** | **1.64** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.463** | **0.470** | **0.464** | no err | 0.537 | n/a | 29.2 | 2.50 | n/a |
| dataclass field wrong type | 0.956 | 1.38 | 0.949 | 0.757 | 0.750 | **0.494** | 32.0 | no err | 0.696 |
| dataclass assignment wrong type | **0.422** | 1.26 | **0.421** | 0.471 | 0.458 | 0.448 | no err | no err | 0.539 |
| value check fails (int > 0 ← -5) | 0.933 | 1.02 | 0.937 | **0.468** | **0.472** | n/a | 44.1 | n/a | n/a |
| invalid email | 1.12 | 1.09 | 1.10 | **0.671** | **0.668** | n/a | 44.7 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.228** |
| typecheck_record · cached spec | **1.06** |
| -> Self · called on the class that defines it | **0.074** |
| -> Self · called on a subclass | **0.083** |
| other: Self · called on a subclass | **0.092** |
| Self \| None · called on a subclass (a wrapper per class) | **0.192** |
| class method -> Self · called on a subclass | **0.205** |
| on_error='warn' · a valid call | **0.072** |
| on_error='warn' · a wrong argument, the warning ignored by a filter | **2.95** |
| on_error='warn' · a wrong argument, the warning shown once (Python's default) | **2.99** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.467** |
| protect · the awaitable raises | **0.625** |
| Self: a Base where a Child is expected (raise + catch) | **1.04** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.42 | 2.24 | 0.926 | **0.924** | n/a | 31.1 | 2.69 | n/a |
| 3 wrong args of 12 | 5.31 | 5.07 | **1.67** | 1.67 | n/a | 29.5 | 3.41 | n/a |
| missing argument | 2.46 | 2.30 | 1.04 | 1.02 | n/a | 0.422 | **0.198** | n/a |
| unknown keyword argument | 1.09 | 1.02 | 0.995 | 0.989 | n/a | 0.479 | **0.153** | n/a |
| wrong keyword-only argument | 2.63 | 2.49 | 1.05 | **1.05** | n/a | 31.1 | 2.75 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.30 | 7.38 | n/a | no err | **3.25** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.18 | **2.11** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.41 | 2.19 | no err | **0.910** | n/a | 28.7 | 2.72 | n/a |
| dataclass field wrong type | 2.91 | 2.72 | 1.23 | 1.23 | **0.970** | 31.4 | no err | 1.91 |
| dataclass assignment wrong type | 2.81 | 2.32 | 0.907 | **0.880** | 1.65 | no err | no err | 1.74 |
| value check fails (int > 0 ← -5) | 2.92 | 2.57 | 1.03 | **1.01** | n/a | 42.2 | n/a | n/a |
| invalid email | 3.03 | 2.74 | 1.18 | **1.18** | n/a | 44.8 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.053 | 0.059 | 0.055 | 0.204 | 0.203 | 0.074 | 1.13 |
| 2 params | 0.066 | 0.069 | 0.066 | 0.215 | 0.215 | 0.091 | 1.63 |
| 4 params | 0.094 | 0.097 | 0.094 | 0.241 | 0.242 | 0.123 | 2.59 |
| 8 params | 0.148 | 0.153 | 0.148 | 0.293 | 0.291 | 0.189 | 4.45 |
| 16 params | 0.256 | 0.252 | 0.258 | 0.384 | 0.386 | 0.310 | 8.05 |
| 32 params | 0.457 | 0.456 | 0.453 | 0.591 | 0.594 | 0.554 | 15.5 |
| fixed cost (ns) | 42 | 46 | 43 | 191 | 190 | 61 | 706 |
| per param (ns) | 13.1 | 12.8 | 12.9 | 12.4 | 12.6 | 15.4 | 462.8 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.280 | 0.260 | 0.280 | 0.411 | 148 | 0.0 |
| enforced | 259.7 | 9.19 | 51.4 | 7.45 | 81.9 | 228 | 8.6 |
| enf.coerce | 265.5 | 7.52 | 55.3 | 7.87 | 90.4 | 229 | 10.4 |
| enf.deep | 255.2 | 9.50 | 54.3 | 7.56 | 84.6 | 217 | 8.6 |
| pydantic | 64.6 | 175 | 5.72 | 270 | 2.61 | 426 | 4.0 |
| pyd.strict | 65.0 | 182 | 5.75 | 282 | 2.78 | 422 | 4.0 |
| pyd.model | 54.9 | n/a | n/a | n/a | n/a | 233 | n/a |
| beartype | 55.1 | 256 | 1.42 | 621 | 2.57 | 502 | 2.8 |
| typeguard | 72.0 | 2,278 | 15.5 | 2,364 | 19.3 | 4,170 | 1.7 |
| attrs | 24.7 | n/a | n/a | n/a | n/a | 248 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.27× slower  (10 cases) | 10 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× faster  (10 cases) | 30 |
| pydantic | 2.47× slower  (32 cases) | 1.33× faster  (9 cases) | 1 |
| pyd.strict | 2.47× slower  (32 cases) | 1.27× faster  (10 cases) | 1 |
| pyd.model | 2.34× slower  (2 cases) | 1.35× faster  (2 cases) | 0 |
| beartype | 1.17× slower  (30 cases) | 16.72× slower  (9 cases) | 8 |
| typeguard | 20.62× slower  (27 cases) | 1.52× slower  (6 cases) | 0 |
| attrs | 1.17× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 17 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
