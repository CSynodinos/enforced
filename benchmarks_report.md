# pyvalidate comparison

*2026-10-12 01:09*

CPython 3.14.4 (GIL) · Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43  
AMD Ryzen 9 9900X 12-Core Processor · 24 CPUs  
timing: 9 interleaved rounds × ≥30 ms per library per case, median reported, GC off  

| library | version | what is measured |
|:--|:--|:--|
| plain | - | no checks: undecorated function / stdlib dataclass |
| pyvalidate | 1.0.0 | @typecheck / pyvalidate.dataclass, defaults (convert on, coerce off) |
| pyv.coerce | 1.0.0 | pyvalidate with coerce=True (parses '42' -> 42, like pydantic lax) |
| pyv.deep | 1.0.0 | pyvalidate with deep=True (checks every item inside collections, like pydantic) |
| pydantic | 2.14.0 | validate_call / pydantic dataclass, default lax mode (coerces) |
| pyd.strict | 2.14.0 | validate_call / pydantic dataclass, strict=True (no coercion) |
| pyd.model | 2.14.0 | pydantic BaseModel (validate_assignment=True), classes only |
| beartype | 0.23.0 | @beartype (O(1): checks one random item per collection) |
| typeguard | 4.6.0 | @typechecked (default: checks the first item of collections) |
| attrs | 26.1.0 | attrs with explicit validators (validated on init and setattr), classes only |

## Coverage

*what each library does with each input (25 trials each)*

| input | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
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

✓ expected behaviour · ✗ wrong · \~ value silently converted · ◐ caught in some trials only (random sampling) · – deep off: items aren't checked by default, enable with deep=True (see the pyv.deep column)  

## Error messages

*p_named(quantity: int) called with 'abc' · class-only libraries: Named(quantity='abc')*

**pyvalidate**
```
TypeCheckerError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**pyv.coerce**
```
TypeCheckerError: 1 problem found in call:
    -> For parameter quantity of <Function p_named>: expected type: 'int', got type 'str' (Value: 'abc')
```

**pyv.deep**
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

| case | plain | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.010 | **0.064** | 0.067 | **0.065** | 0.216 | 0.216 | 0.083 | 1.17 |
| 2 params · positional | 0.011 | **0.072** | 0.077 | **0.072** | 0.227 | 0.225 | 0.099 | 1.68 |
| 2 params · keyword | 0.016 | **0.158** | **0.162** | **0.160** | 0.481 | 0.480 | 0.172 | 1.68 |
| 5 params · mixed types | 0.013 | **0.103** | **0.103** | **0.103** | 0.277 | 0.278 | 0.151 | 2.96 |
| 12 params · positional | 0.018 | **0.200** | **0.202** | **0.201** | 0.355 | 0.356 | 0.270 | 5.90 |
| 12 params · keyword | 0.039 | **0.665** | **0.660** | **0.665** | 1.54 | 1.53 | 0.695 | 5.99 |
| defaults used (1 of 5 given) | 0.015 | 0.172 | 0.172 | 0.172 | 0.561 | 0.562 | **0.154** | 4.94 |
| keyword-only params | 0.020 | **0.169** | **0.168** | 0.169 | 0.395 | 0.399 | **0.164** | 2.05 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.205** | 0.211 | **0.205** | 0.496 | 0.497 | 0.223 | 6.00 |
| unions · int \| str \| None, float \| None | 0.011 | **0.086** | **0.085** | **0.086** | 0.275 | 0.262 | 0.119 | 4.00 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.234** | **0.235** | 0.238 | 0.497 | 0.497 | **0.231** | 6.70 |
| user-defined classes | 0.013 | **0.075** | **0.074** | **0.074** | 0.231 | 0.229 | 0.109 | 1.68 |
| Any / object | 0.012 | 0.056 | 0.056 | 0.055 | 0.226 | 0.221 | **0.011** | 1.18 |
| \*args / \*\*kwargs (3 + 2) | 0.043 | **0.257** | **0.259** | **0.259** | 0.436 | 0.430 | 0.517 | 4.22 |
| return value checked | 0.011 | **0.078** | 0.081 | **0.078** | 0.252 | 0.250 | 0.090 | 1.68 |
| async def (coroutine driven) | 0.104 | **0.204** | 0.209 | **0.202** | 0.455 | 0.453 | 0.249 | 1.83 |
| method on an instance | 0.012 | **0.078** | 0.082 | **0.077** | 0.242 | 0.241 | 0.105 | 1.70 |

## Collections

*µs per call, median*

| case | plain | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.065† | **0.189** | 0.335 | 0.334 | 0.133† | 1.97† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.065† | **5.04** | 6.88 | 6.89 | 0.146† | 1.95† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.066† | **467** | 1,104 | 1,113 | 0.165† | 1.96† |
| dict[str, int] × 100 | 0.012 | 0.062† | 0.062† | **1.34** | 2.27 | 2.28 | 0.137† | 2.56† |
| tuple[int, str, float] | 0.012 | 0.063† | 0.066† | **0.118** | 0.271 | 0.274 | **0.116** | 3.00 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.064† | 0.062† | **1.28** | 1.43 | 1.40 | 0.191† | 3.43† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.112† | 0.111† | **2.07** | 4.54 | 4.57 | 0.305† | 3.34† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.062† | **0.302** | 0.421 | 0.420 | 0.175† | 4.93 |
| list of 100 objects | 0.012 | 0.062† | 0.065† | **0.660** | 0.884 | 0.886 | 0.139† | 1.96† |

## Classes

*µs per call, median*

| case | plain | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.097 | 0.549 | 0.560 | 0.553 | 0.615 | 0.625 | 0.419 | 0.338 | 0.097† | **0.316** |
| construct Order tree (5 objects) | 0.463 | 2.48† | 2.54† | 2.76 | 2.91 | 2.90 | 1.97 | 1.70 | 0.461† | **1.55** |
| assign point.x = 5 | 0.004 | **0.062** | **0.061** | **0.062** | 0.305 | 0.306 | 0.411 | 0.004† | 0.004† | 0.122 |

## Validated values

*µs per call, median*

| case | plain | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.094** | 0.097 | **0.093** | 0.228 | 0.228 | 0.121 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.065† | **19.7** | 21.6 | 21.7 | 0.186† |
| email · already valid str | 0.011 | 1.02 | 1.01 | 1.01 | 0.993 | 0.997 | **0.826** |
| email · normalised (domain lower-cased) | 0.011 | 1.01≠ | 1.01≠ | 1.02≠ | 0.995≠ | 1.00≠ | **0.833** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 1.67 | 2.51 | 1.66 | **0.471** | **0.470** | n/a | 32.1 | 2.52 | n/a |
| 3 wrong args of 12 | 5.38 | 7.05 | 5.35 | **0.697** | 0.781 | n/a | 31.5 | 3.25 | n/a |
| missing argument | 7.97 | 8.89 | 8.25 | 0.527 | 0.527 | n/a | 0.396 | **0.175** | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 29.7 | 6.88 | 6.85 | n/a | no err | **3.03** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.31 | **1.66** | **1.67** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 1.30 | 1.31 | 1.30 | no err | **0.543** | n/a | 30.1 | 2.55 | n/a |
| dataclass field wrong type | 2.65 | 3.64 | 2.67 | 0.804 | 0.793 | **0.501** | 32.8 | no err | 0.703 |
| dataclass assignment wrong type | 1.96 | 3.50 | 1.92 | 0.508 | 0.503 | **0.484** | no err | no err | 0.538 |
| value check fails (int > 0 ← -5) | 2.06 | 2.83 | 2.06 | **0.485** | **0.479** | n/a | 45.1 | n/a | n/a |
| invalid email | 3.43 | 3.46 | 3.45 | **0.709** | **0.709** | n/a | 45.4 | n/a | n/a |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · pyv.nocolour = PYVALIDATE_COLOURS_OFF=1*

| case | pyvalidate | pyv.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 10.7 | 4.31 | 0.938 | **0.923** | n/a | 31.1 | 2.76 | n/a |
| 3 wrong args of 12 | 31.2 | 12.4 | **1.63** | 1.69 | n/a | 30.3 | 3.49 | n/a |
| missing argument | 19.5 | 12.6 | 1.03 | 1.04 | n/a | 0.427 | **0.200** | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.41 | 7.33 | n/a | no err | **3.27** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.14 | **2.12** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 10.3 | 4.03 | no err | **0.921** | n/a | 30.1 | 2.74 | n/a |
| dataclass field wrong type | 12.3 | 5.61 | 1.29 | 1.24 | **0.942** | 31.5 | no err | 1.94 |
| dataclass assignment wrong type | 11.7 | 5.03 | 0.945 | **0.913** | 1.67 | no err | no err | 1.78 |
| value check fails (int > 0 ← -5) | 11.6 | 5.18 | **1.01** | 1.02 | n/a | 43.7 | n/a | n/a |
| invalid email | 13.3 | 6.55 | 1.21 | **1.21** | n/a | 45.7 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | pyvalidate | pyv.coerce | pyv.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.055 | 0.057 | 0.055 | 0.205 | 0.206 | 0.074 | 1.15 |
| 2 params | 0.066 | 0.070 | 0.066 | 0.215 | 0.218 | 0.089 | 1.67 |
| 4 params | 0.091 | 0.096 | 0.091 | 0.242 | 0.244 | 0.124 | 2.61 |
| 8 params | 0.148 | 0.153 | 0.149 | 0.294 | 0.294 | 0.187 | 4.47 |
| 16 params | 0.254 | 0.257 | 0.254 | 0.388 | 0.385 | 0.314 | 8.10 |
| 32 params | 0.461 | 0.462 | 0.458 | 0.621 | 0.622 | 0.556 | 15.7 |
| fixed cost (ns) | 41 | 45 | 42 | 187 | 188 | 60 | 699 |
| per param (ns) | 13.2 | 13.1 | 13.1 | 13.4 | 13.3 | 15.6 | 468.9 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.290 | 0.260 | 0.290 | 0.430 | 150 | 0.0 |
| pyvalidate | 93.0 | 10.7 | 234 | 7.52 | 1,208 | 190 | 10.3 |
| pyv.coerce | 91.7 | 14.7 | 384 | 8.64 | 1,515 | 199 | 13.4 |
| pyv.deep | 92.2 | 12.1 | 251 | 7.82 | 1,244 | 190 | 10.3 |
| pydantic | 69.0 | 182 | 5.78 | 327 | 3.51 | 403 | 4.0 |
| pyd.strict | 66.6 | 189 | 6.00 | 294 | 2.59 | 442 | 4.0 |
| pyd.model | 56.7 | n/a | n/a | n/a | n/a | 254 | n/a |
| beartype | 57.3 | 254 | 1.44 | 599 | 2.61 | 579 | 2.8 |
| typeguard | 73.4 | 2,316 | 16.3 | 2,376 | 20.4 | 4,223 | 1.6 |
| attrs | 25.4 | n/a | n/a | n/a | n/a | 274 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs pyvalidate, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| pyv.coerce | 1.02× slower  (28 cases) | 1.29× slower  (8 cases) | 10 |
| pyv.deep | 1.00× slower  (28 cases) | 1.00× slower  (8 cases) | 25 |
| pydantic | 2.35× slower  (28 cases) | 5.23× faster  (7 cases) | 0 |
| pyd.strict | 2.35× slower  (28 cases) | 4.70× faster  (8 cases) | 0 |
| pyd.model | 2.26× slower  (2 cases) | 4.62× faster  (2 cases) | 0 |
| beartype | 1.10× slower  (27 cases) | 6.45× slower  (7 cases) | 7 |
| typeguard | 21.40× slower  (23 cases) | 2.25× faster  (4 cases) | 0 |
| attrs | 1.07× slower  (2 cases) | 3.70× faster  (2 cases) | 2 |
| pyvalidate | reference | reference | 17 |

each cell says how that library compares with pyvalidate (faster or slower; green = pyvalidate is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
