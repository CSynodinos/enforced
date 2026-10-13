# enforced comparison

*2026-10-13 01:11*

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
| 1 param | 0.010 | **0.064** | 0.067 | **0.064** | 0.214 | 0.212 | 0.084 | 1.18 |
| 2 params · positional | 0.011 | **0.073** | 0.076 | **0.072** | 0.229 | 0.227 | 0.100 | 1.68 |
| 2 params · keyword | 0.016 | **0.155** | 0.162 | **0.155** | 0.491 | 0.489 | 0.167 | 1.69 |
| 5 params · mixed types | 0.013 | **0.102** | **0.103** | **0.103** | 0.276 | 0.276 | 0.152 | 2.91 |
| 12 params · positional | 0.019 | **0.202** | **0.203** | **0.202** | 0.354 | 0.357 | 0.270 | 5.88 |
| 12 params · keyword | 0.039 | **0.649** | **0.653** | **0.646** | 1.51 | 1.54 | 0.680 | 6.02 |
| defaults used (1 of 5 given) | 0.015 | 0.172 | 0.174 | 0.173 | 0.579 | 0.583 | **0.151** | 5.04 |
| keyword-only params | 0.019 | 0.165 | 0.164 | 0.165 | 0.395 | 0.395 | **0.159** | 2.07 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.208** | **0.211** | **0.210** | 0.494 | 0.498 | 0.231 | 5.97 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.084** | **0.085** | 0.274 | 0.262 | 0.115 | 3.97 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.242** | **0.241** | **0.242** | 0.505 | 0.498 | **0.239** | 6.54 |
| user-defined classes | 0.013 | **0.072** | **0.073** | **0.071** | 0.230 | 0.229 | 0.107 | 1.69 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.055 | 0.219 | 0.218 | **0.011** | 1.18 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.262** | **0.262** | **0.263** | 0.437 | 0.438 | 0.539 | 4.07 |
| return value checked | 0.010 | **0.077** | 0.082 | **0.078** | 0.275 | 0.278 | 0.090 | 1.67 |
| async def (coroutine driven) | 0.106 | **0.200** | 0.209 | **0.202** | 0.472 | 0.459 | 0.251 | 1.91 |
| method on an instance | 0.012 | **0.079** | 0.082 | **0.079** | 0.241 | 0.242 | 0.104 | 1.74 |
| positional-only params · one default used | 0.014 | 0.124 | 0.124 | 0.123 | 0.413 | 0.413 | **0.116** | 2.04 |
| float params given ints (numeric tower) | 0.013 | 0.283 | 0.305 | 0.276 | **0.265** | **0.258** | ERR | 1.33 |
| Callable · Iterable | 0.013 | **0.168** | **0.170** | **0.167** | 0.382 | 0.381 | 0.522 | 6.25 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.063† | 0.067† | **0.190** | 0.360 | 0.362 | 0.136† | 1.97† |
| list[int] × 1,000 | 0.012 | 0.063† | 0.067† | **5.00** | 6.89 | 6.82 | 0.147† | 1.96† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.066† | **505** | 796 | 788 | 0.195† | 1.98† |
| dict[str, int] × 100 | 0.012 | 0.062† | 0.063† | **1.33** | 2.26 | 2.24 | 0.137† | 2.55† |
| tuple[int, str, float] | 0.012 | 0.062† | 0.066† | **0.118** | 0.273 | 0.273 | **0.116** | 3.00 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.062† | **1.29** | 1.41 | 1.41 | 0.191† | 3.36† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.111† | 0.111† | **2.08** | 4.60 | 4.58 | 0.313† | 3.28† |
| TypedDict (4 keys, one a list) | 0.012 | 0.063† | 0.062† | **0.299** | 0.418 | 0.417 | 0.174† | 4.97 |
| list of 100 objects | 0.012 | 0.063† | 0.066† | **0.669** | 0.901 | 0.894 | 0.140† | 1.99† |
| set[str] × 100 | 0.013 | **0.064** | 0.066 | 0.736 | 1.73 | 1.74 | 0.122 | 2.14 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.066† | **5.73** | 6.90 | 6.94 | 0.152† | 3.79† |
| tuple[int, ...] × 1,000 | 0.012 | 0.063† | 0.065† | **4.89** | 6.35 | 6.29 | 0.147† | 2.18† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.096 | 0.538 | 0.532 | 0.538 | 0.593 | 0.592 | 0.401 | 0.334 | 0.096† | **0.303** |
| construct Order tree (5 objects) | 0.484 | 2.52† | 2.59† | 2.76 | 2.88 | 2.85 | 1.96 | 1.79 | 0.481† | **1.54** |
| assign point.x = 5 | 0.004 | **0.061** | **0.060** | **0.061** | 0.266 | 0.267 | 0.381 | 0.004† | 0.004† | 0.122 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.011 | **0.094** | 0.097 | **0.095** | 0.226 | 0.227 | 0.122 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.065† | **19.8** | 22.0 | 22.0 | 0.185† |
| email · already valid str | 0.011 | 1.02 | 1.02 | 1.02 | 0.993 | 0.977 | **0.822** |
| email · normalised (domain lower-cased) | 0.011 | 1.04≠ | 1.04≠ | 1.04≠ | 0.995≠ | 0.986≠ | **0.820** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 1.62 | 2.49 | 1.64 | **0.477** | **0.475** | n/a | 31.2 | 2.51 | n/a |
| 3 wrong args of 12 | 5.29 | 6.96 | 5.26 | **0.721** | 0.802 | n/a | 31.2 | 3.18 | n/a |
| missing argument | 4.86 | 5.34 | 4.87 | 0.525 | 0.529 | n/a | 0.401 | **0.175** | n/a |
| unknown keyword argument | 1.13 | 1.72 | 1.13 | 0.582 | 0.586 | n/a | 0.454 | **0.134** | n/a |
| wrong keyword-only argument | 2.44 | 2.65 | 2.43 | **0.602** | **0.599** | n/a | 32.1 | 2.63 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 29.7 | 6.91 | 6.91 | n/a | no err | **3.03** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.33 | **1.67** | **1.66** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 1.30 | 1.30 | 1.29 | no err | **0.542** | n/a | 30.0 | 2.58 | n/a |
| dataclass field wrong type | 2.66 | 3.66 | 2.70 | 0.790 | 0.777 | **0.504** | 32.7 | no err | 0.710 |
| dataclass assignment wrong type | 2.04 | 3.56 | 2.01 | 0.481 | 0.465 | **0.447** | no err | no err | 0.550 |
| value check fails (int > 0 ← -5) | 2.15 | 2.87 | 2.14 | **0.492** | **0.495** | n/a | 45.4 | n/a | n/a |
| invalid email | 3.61 | 3.59 | 3.61 | **0.670** | **0.674** | n/a | 44.7 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.216** |
| typecheck_from_dict · cached spec | **1.21** |
| -> Self · called on the class that defines it | **0.075** |
| -> Self · called on a subclass | **0.084** |
| other: Self · called on a subclass | **0.091** |
| Self \| None · called on a subclass (a wrapper per class) | **0.193** |
| class method -> Self · called on a subclass | **0.207** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.469** |
| protect · the awaitable raises | **0.630** |
| Self: a Base where a Child is expected (raise + catch) | **2.11** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 5.03 | 3.56 | 0.935 | **0.929** | n/a | 32.6 | 2.76 | n/a |
| 3 wrong args of 12 | 12.4 | 9.39 | **1.68** | 1.70 | n/a | 30.1 | 3.54 | n/a |
| missing argument | 10.5 | 7.40 | 1.06 | 1.05 | n/a | 0.419 | **0.200** | n/a |
| unknown keyword argument | 2.49 | 1.51 | 1.06 | 1.04 | n/a | 0.477 | **0.156** | n/a |
| wrong keyword-only argument | 6.05 | 4.43 | 1.07 | **1.06** | n/a | 32.0 | 2.81 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.37 | 7.36 | n/a | no err | **3.31** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.22 | **2.13** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 4.65 | 3.19 | no err | **0.919** | n/a | 29.2 | 2.76 | n/a |
| dataclass field wrong type | 6.06 | 4.61 | 1.26 | 1.22 | **0.989** | 31.1 | no err | 1.94 |
| dataclass assignment wrong type | 5.75 | 4.23 | 0.939 | **0.906** | 1.67 | no err | no err | 1.74 |
| value check fails (int > 0 ← -5) | 5.93 | 4.34 | 1.05 | **1.02** | n/a | 44.5 | n/a | n/a |
| invalid email | 7.41 | 5.90 | **1.19** | 1.20 | n/a | 45.5 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.054 | 0.057 | 0.054 | 0.205 | 0.207 | 0.075 | 1.16 |
| 2 params | 0.067 | 0.070 | 0.067 | 0.215 | 0.214 | 0.092 | 1.66 |
| 4 params | 0.091 | 0.099 | 0.090 | 0.244 | 0.244 | 0.127 | 2.68 |
| 8 params | 0.152 | 0.154 | 0.151 | 0.297 | 0.298 | 0.188 | 4.62 |
| 16 params | 0.257 | 0.255 | 0.254 | 0.388 | 0.392 | 0.311 | 8.25 |
| 32 params | 0.458 | 0.466 | 0.457 | 0.593 | 0.599 | 0.553 | 16.0 |
| fixed cost (ns) | 42 | 45 | 42 | 193 | 193 | 63 | 729 |
| per param (ns) | 13.1 | 13.1 | 13.0 | 12.5 | 12.7 | 15.4 | 475.9 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.290 | 0.250 | 0.270 | 0.450 | 152 | 0.0 |
| enforced | 100.5 | 7.43 | 223 | 6.54 | 1,217 | 196 | 10.6 |
| enf.coerce | 100.9 | 8.46 | 340 | 10.5 | 1,555 | 199 | 13.7 |
| enf.deep | 99.6 | 7.61 | 228 | 6.71 | 1,219 | 184 | 10.6 |
| pydantic | 65.5 | 185 | 6.07 | 282 | 2.53 | 453 | 4.0 |
| pyd.strict | 65.6 | 190 | 5.78 | 266 | 2.45 | 407 | 4.0 |
| pyd.model | 55.6 | n/a | n/a | n/a | n/a | 243 | n/a |
| beartype | 57.2 | 277 | 1.49 | 651 | 2.57 | 524 | 2.8 |
| typeguard | 73.8 | 2,290 | 15.4 | 2,438 | 19.9 | 4,284 | 1.6 |
| attrs | 26.2 | n/a | n/a | n/a | n/a | 265 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.28× slower  (10 cases) | 10 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× faster  (10 cases) | 29 |
| pydantic | 2.49× slower  (32 cases) | 4.40× faster  (9 cases) | 1 |
| pyd.strict | 2.48× slower  (32 cases) | 4.11× faster  (10 cases) | 1 |
| pyd.model | 2.17× slower  (2 cases) | 4.91× faster  (2 cases) | 0 |
| beartype | 1.15× slower  (30 cases) | 5.37× slower  (9 cases) | 8 |
| typeguard | 20.91× slower  (27 cases) | 2.21× faster  (6 cases) | 0 |
| attrs | 1.06× slower  (2 cases) | 3.73× faster  (2 cases) | 2 |
| enforced | reference | reference | 18 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
