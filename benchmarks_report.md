# enforced comparison

*2026-10-13 00:50*

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
| 1 param | 0.011 | **0.067** | 0.069 | **0.066** | 0.218 | 0.218 | 0.086 | 1.15 |
| 2 params · positional | 0.011 | **0.074** | 0.079 | **0.074** | 0.231 | 0.228 | 0.103 | 1.69 |
| 2 params · keyword | 0.017 | **0.157** | 0.165 | **0.156** | 0.477 | 0.479 | 0.169 | 1.67 |
| 5 params · mixed types | 0.013 | **0.104** | 0.107 | **0.104** | 0.276 | 0.278 | 0.153 | 2.88 |
| 12 params · positional | 0.018 | **0.203** | **0.202** | **0.199** | 0.350 | 0.351 | 0.269 | 5.91 |
| 12 params · keyword | 0.038 | **0.654** | **0.651** | **0.651** | 1.49 | 1.51 | 0.677 | 5.92 |
| defaults used (1 of 5 given) | 0.015 | 0.176 | 0.174 | 0.173 | 0.571 | 0.574 | **0.151** | 4.89 |
| keyword-only params | 0.020 | **0.165** | 0.168 | **0.166** | 0.401 | 0.394 | **0.161** | 2.03 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.211** | **0.212** | **0.210** | 0.502 | 0.497 | 0.224 | 5.99 |
| unions · int \| str \| None, float \| None | 0.011 | **0.089** | **0.090** | **0.090** | 0.271 | 0.263 | 0.115 | 4.08 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.014 | **0.236** | **0.234** | **0.235** | 0.502 | 0.507 | **0.233** | 6.57 |
| user-defined classes | 0.013 | **0.073** | **0.073** | 0.075 | 0.233 | 0.230 | 0.107 | 1.67 |
| Any / object | 0.011 | 0.057 | 0.057 | 0.056 | 0.220 | 0.222 | **0.011** | 1.19 |
| \*args / \*\*kwargs (3 + 2) | 0.043 | **0.256** | **0.256** | **0.258** | 0.427 | 0.426 | 0.531 | 4.12 |
| return value checked | 0.010 | **0.079** | 0.082 | **0.078** | 0.250 | 0.252 | 0.093 | 1.66 |
| async def (coroutine driven) | 0.105 | **0.196** | 0.209 | **0.199** | 0.457 | 0.459 | 0.244 | 1.83 |
| method on an instance | 0.012 | **0.080** | 0.084 | **0.079** | 0.241 | 0.243 | 0.108 | 1.70 |
| positional-only params · one default used | 0.014 | 0.128 | 0.128 | 0.128 | 0.404 | 0.403 | **0.113** | 2.04 |
| float params given ints (numeric tower) | 0.012 | 0.295 | 0.305 | 0.297 | **0.262** | **0.260** | ERR | 1.34 |
| Callable · Iterable | 0.013 | **0.168** | **0.169** | **0.172** | 0.384 | 0.385 | 0.516 | 6.24 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.065† | 0.067† | **0.193** | 0.335 | 0.333 | 0.133† | 1.96† |
| list[int] × 1,000 | 0.012 | 0.065† | 0.067† | **5.01** | 6.89 | 6.90 | 0.144† | 1.94† |
| list[int] × 100,000 | 0.012 | 0.065† | 0.065† | **463** | 653 | 657 | 0.155† | 1.97† |
| dict[str, int] × 100 | 0.012 | 0.064† | 0.065† | **1.34** | 2.28 | 2.27 | 0.139† | 2.53† |
| tuple[int, str, float] | 0.012 | 0.065† | 0.066† | **0.120** | 0.272 | 0.272 | **0.117** | 2.96 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.065† | 0.066† | **1.29** | 1.43 | 1.42 | 0.191† | 3.29† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.113† | 0.114† | **2.09** | 4.68 | 4.66 | 0.312† | 3.25† |
| TypedDict (4 keys, one a list) | 0.012 | 0.066† | 0.065† | **0.312** | 0.421 | 0.423 | 0.176† | 4.97 |
| list of 100 objects | 0.012 | 0.065† | 0.066† | **0.664** | 0.871 | 0.870 | 0.139† | 1.95† |
| set[str] × 100 | 0.012 | **0.065** | 0.067 | 0.737 | 1.76 | 1.76 | 0.123 | 2.17 |
| list[int \| None] × 1,000 | 0.012 | 0.065† | 0.066† | **5.73** | 6.95 | 6.89 | 0.152† | 3.79† |
| tuple[int, ...] × 1,000 | 0.012 | 0.065† | 0.068† | **5.00** | 6.31 | 6.37 | 0.144† | 2.14† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.097 | 0.534 | 0.550 | 0.541 | 0.599 | 0.602 | 0.399 | 0.330 | 0.096† | **0.301** |
| construct Order tree (5 objects) | 0.463 | 2.52† | 2.57† | 2.75 | 2.90 | 2.91 | 1.98 | 1.72 | 0.469† | **1.54** |
| assign point.x = 5 | 0.004 | **0.062** | **0.061** | **0.060** | 0.273 | 0.272 | 0.371 | 0.004† | 0.004† | 0.121 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.094** | 0.099 | **0.096** | 0.231 | 0.231 | 0.124 |
| list[int > 0] × 1,000 | 0.012 | 0.065† | 0.066† | **19.5** | 21.5 | 21.4 | 0.185† |
| email · already valid str | 0.011 | 1.01 | 1.02 | 1.03 | 0.981 | 0.983 | **0.823** |
| email · normalised (domain lower-cased) | 0.011 | 1.02≠ | 1.03≠ | 1.04≠ | 0.999≠ | 0.990≠ | **0.817** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 1.64 | 2.48 | 1.65 | **0.479** | **0.479** | n/a | 31.0 | 2.50 | n/a |
| 3 wrong args of 12 | 5.21 | 6.94 | 5.21 | **0.697** | 0.768 | n/a | 30.5 | 3.15 | n/a |
| missing argument | 4.77 | 5.27 | 4.84 | 0.531 | 0.531 | n/a | 0.397 | **0.174** | n/a |
| unknown keyword argument | 1.11 | 1.69 | 1.09 | 0.578 | 0.578 | n/a | 0.436 | **0.134** | n/a |
| wrong keyword-only argument | 2.42 | 2.65 | 2.43 | **0.601** | **0.593** | n/a | 31.7 | 2.56 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 30.0 | 6.90 | 6.93 | n/a | no err | **3.01** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.21 | **1.67** | **1.67** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 1.29 | 1.29 | 1.29 | no err | **0.538** | n/a | 29.7 | 2.53 | n/a |
| dataclass field wrong type | 2.60 | 3.59 | 2.62 | 0.793 | 0.780 | **0.495** | 32.4 | no err | 0.692 |
| dataclass assignment wrong type | 1.99 | 3.57 | 1.97 | 0.474 | **0.464** | **0.453** | no err | no err | 0.540 |
| value check fails (int > 0 ← -5) | 2.10 | 2.85 | 2.09 | **0.478** | **0.475** | n/a | 44.1 | n/a | n/a |
| invalid email | 3.62 | 3.64 | 3.65 | **0.668** | **0.670** | n/a | 45.3 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.221** |
| typecheck_from_dict · cached spec | **1.20** |
| -> Self · called on the class that defines it | **0.077** |
| -> Self · called on a subclass | **0.085** |
| other: Self · called on a subclass | **0.096** |
| Self \| None · called on a subclass (a wrapper per class) | **0.197** |
| class method -> Self · called on a subclass | **0.208** |
| Ok(value) | **0.072** |
| protect · the awaitable completes | **0.467** |
| protect · the awaitable raises | **0.637** |
| Self: a Base where a Child is expected (raise + catch) | **2.10** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 4.92 | 3.53 | **0.912** | 0.919 | n/a | 31.4 | 2.69 | n/a |
| 3 wrong args of 12 | 11.9 | 9.34 | **1.67** | 1.68 | n/a | 29.6 | 3.39 | n/a |
| missing argument | 9.32 | 7.38 | 1.05 | 1.07 | n/a | 0.425 | **0.201** | n/a |
| unknown keyword argument | 2.44 | 1.50 | 1.04 | 1.04 | n/a | 0.483 | **0.155** | n/a |
| wrong keyword-only argument | 5.89 | 4.33 | **1.06** | 1.06 | n/a | 30.9 | 2.76 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.34 | 7.31 | n/a | no err | **3.31** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.18 | **2.18** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 4.63 | 3.19 | no err | **0.924** | n/a | 28.5 | 2.75 | n/a |
| dataclass field wrong type | 6.04 | 4.59 | 1.24 | 1.23 | **0.970** | 31.5 | no err | 1.90 |
| dataclass assignment wrong type | 5.75 | 4.18 | 0.913 | **0.883** | 1.65 | no err | no err | 1.74 |
| value check fails (int > 0 ← -5) | 5.77 | 4.30 | **1.00** | 1.01 | n/a | 43.8 | n/a | n/a |
| invalid email | 7.34 | 6.02 | **1.17** | 1.18 | n/a | 46.8 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.055 | 0.057 | 0.054 | 0.207 | 0.206 | 0.076 | 1.14 |
| 2 params | 0.067 | 0.071 | 0.067 | 0.218 | 0.217 | 0.090 | 1.65 |
| 4 params | 0.095 | 0.098 | 0.093 | 0.242 | 0.242 | 0.122 | 2.60 |
| 8 params | 0.151 | 0.155 | 0.150 | 0.295 | 0.296 | 0.190 | 4.42 |
| 16 params | 0.255 | 0.261 | 0.255 | 0.389 | 0.387 | 0.310 | 8.07 |
| 32 params | 0.456 | 0.466 | 0.470 | 0.593 | 0.593 | 0.547 | 16.0 |
| fixed cost (ns) | 44 | 46 | 41 | 193 | 193 | 63 | 636 |
| per param (ns) | 13.0 | 13.2 | 13.4 | 12.4 | 12.5 | 15.2 | 477.5 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.320 | 0.270 | 0.280 | 0.420 | 152 | 0.0 |
| enforced | 97.5 | 7.65 | 234 | 6.90 | 1,259 | 198 | 10.6 |
| enf.coerce | 97.0 | 8.07 | 337 | 7.21 | 1,502 | 191 | 13.7 |
| enf.deep | 99.0 | 7.52 | 235 | 7.06 | 1,589 | 182 | 10.6 |
| pydantic | 65.0 | 177 | 5.67 | 270 | 2.55 | 429 | 4.0 |
| pyd.strict | 65.9 | 176 | 5.41 | 286 | 2.41 | 433 | 4.0 |
| pyd.model | 53.7 | n/a | n/a | n/a | n/a | 240 | n/a |
| beartype | 56.3 | 249 | 1.34 | 621 | 2.77 | 555 | 2.8 |
| typeguard | 72.4 | 2,290 | 15.5 | 2,419 | 19.9 | 4,250 | 1.6 |
| attrs | 24.9 | n/a | n/a | n/a | n/a | 283 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.29× slower  (10 cases) | 9 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 29 |
| pydantic | 2.45× slower  (32 cases) | 4.37× faster  (9 cases) | 1 |
| pyd.strict | 2.45× slower  (32 cases) | 4.10× faster  (10 cases) | 1 |
| pyd.model | 2.12× slower  (2 cases) | 4.81× faster  (2 cases) | 0 |
| beartype | 1.14× slower  (30 cases) | 5.35× slower  (9 cases) | 8 |
| typeguard | 20.46× slower  (27 cases) | 2.22× faster  (6 cases) | 0 |
| attrs | 1.05× slower  (2 cases) | 3.72× faster  (2 cases) | 2 |
| enforced | reference | reference | 19 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
