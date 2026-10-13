# enforced comparison

*2026-10-13 21:12*

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
| 1 param | 0.010 | **0.064** | 0.067 | **0.064** | 0.214 | 0.214 | 0.086 | 1.14 |
| 2 params · positional | 0.011 | **0.072** | 0.076 | **0.073** | 0.226 | 0.229 | 0.106 | 1.63 |
| 2 params · keyword | 0.016 | **0.155** | 0.161 | **0.156** | 0.483 | 0.484 | 0.171 | 1.65 |
| 5 params · mixed types | 0.013 | **0.104** | **0.103** | **0.104** | 0.275 | 0.275 | 0.160 | 2.86 |
| 12 params · positional | 0.018 | **0.200** | **0.203** | **0.199** | 0.354 | 0.357 | 0.274 | 5.79 |
| 12 params · keyword | 0.038 | **0.648** | **0.652** | **0.648** | 1.51 | 1.52 | 0.673 | 5.93 |
| defaults used (1 of 5 given) | 0.015 | 0.174 | 0.175 | 0.173 | 0.568 | 0.566 | **0.152** | 4.92 |
| keyword-only params | 0.019 | **0.166** | **0.166** | **0.166** | 0.401 | 0.400 | **0.163** | 2.02 |
| Optional · Literal · Sequence · type[] | 0.014 | **0.210** | **0.214\~** | **0.208** | 0.507 | 0.513 | 0.229 | 5.99 |
| unions · int \| str \| None, float \| None | 0.011 | **0.084** | **0.085** | **0.084** | 0.279 | 0.264 | 0.117 | 3.97 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.013 | **0.237** | **0.237** | **0.236** | 0.506 | 0.508 | **0.231** | 6.57 |
| user-defined classes | 0.013 | **0.072** | **0.072** | **0.072** | 0.229 | 0.228 | 0.112 | 1.64 |
| Any / object | 0.011 | 0.055 | 0.055 | 0.055 | 0.219 | 0.219 | **0.011** | 1.16 |
| \*args / \*\*kwargs (3 + 2) | 0.042 | **0.259** | **0.261** | **0.259** | 0.426 | 0.427 | 0.516 | 4.06 |
| return value checked | 0.010 | **0.077** | 0.079 | **0.076** | 0.247 | 0.247 | 0.093 | 1.65 |
| async def (coroutine driven) | 0.104 | **0.203** | 0.210 | **0.202** | 0.453 | 0.454 | 0.253 | 1.80 |
| method on an instance | 0.012 | **0.078** | 0.081 | **0.079** | 0.243 | 0.245 | 0.110 | 1.66 |
| positional-only params · one default used | 0.014 | 0.125 | 0.123 | 0.124 | 0.397 | 0.399 | **0.113** | 1.99 |
| float params given ints (numeric tower) | 0.012 | 0.274 | 0.298 | 0.275 | **0.260** | **0.258** | ERR | 1.32 |
| Callable · Iterable | 0.013 | **0.168** | **0.167** | **0.169** | 0.337 | 0.335 | 0.511 | 6.22 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.012 | 0.062† | 0.064† | **0.187** | 0.335 | 0.334 | 0.138† | 1.92† |
| list[int] × 1,000 | 0.012 | 0.062† | 0.065† | **5.04** | 6.90 | 6.83 | 0.149† | 1.93† |
| list[int] × 100,000 | 0.012 | 0.062† | 0.065† | **462** | 1,086 | 1,077 | 0.166† | 1.92† |
| dict[str, int] × 100 | 0.012 | 0.062† | 0.062† | **1.33** | 2.23 | 2.25 | 0.139† | 2.50† |
| tuple[int, str, float] | 0.012 | 0.063† | 0.065† | **0.116** | 0.270 | 0.269 | **0.120** | 2.95 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.063† | **1.29** | 1.41 | 1.39 | 0.192† | 3.28† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.110† | 0.110† | **2.05** | 4.60 | 4.60 | 0.306† | 3.18† |
| TypedDict (4 keys, one a list) | 0.012 | 0.062† | 0.062† | **0.299** | 0.426 | 0.427 | 0.177† | 4.93 |
| list of 100 objects | 0.012 | 0.062† | 0.065† | **0.660** | 0.870 | 0.875 | 0.137† | 1.92† |
| set[str] × 100 | 0.013 | **0.062** | 0.067 | 0.734 | 1.72 | 1.73 | 0.124 | 2.15 |
| list[int \| None] × 1,000 | 0.012 | 0.062† | 0.065† | **5.70** | 6.87 | 6.89 | 0.150† | 3.76† |
| tuple[int, ...] × 1,000 | 0.012 | 0.063† | 0.066† | **4.85** | 6.25 | 6.19 | 0.149† | 2.13† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.096 | 0.431 | 0.431 | 0.431 | 0.584 | 0.583 | 0.393 | 0.338 | 0.096† | **0.303** |
| construct Order tree (5 objects) | 0.458 | 2.02† | 2.06† | 2.20 | 2.83 | 2.84 | 1.94 | 1.73 | 0.459† | **1.55** |
| assign point.x = 5 | 0.004 | **0.060** | **0.061** | **0.061** | 0.277 | 0.271 | 0.369 | 0.004† | 0.004† | 0.121 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.010 | **0.095** | **0.096** | **0.095** | 0.225 | 0.225 | 0.127 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.065† | **19.4** | 21.4 | 21.2 | 0.184† |
| email · already valid str | 0.011 | 1.03 | 1.03 | 1.02 | 0.998 | 0.988 | **0.823** |
| email · normalised (domain lower-cased) | 0.011 | 1.03≠ | 1.03≠ | 1.03≠ | 0.986≠ | 0.983≠ | **0.822** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.568 | 0.636 | 0.568 | **0.482** | **0.482** | n/a | 31.0 | 2.46 | n/a |
| 3 wrong args of 12 | 1.08 | 2.03 | 1.09 | **0.704** | 0.803 | n/a | 30.0 | 3.14 | n/a |
| missing argument | 0.563 | 0.570 | 0.567 | 0.549 | 0.550 | n/a | 0.403 | **0.174** | n/a |
| unknown keyword argument | 0.714 | 0.722 | 0.711 | 0.584 | 0.585 | n/a | 0.444 | **0.132** | n/a |
| wrong keyword-only argument | 0.808 | 0.875 | 0.805 | **0.597** | **0.592** | n/a | 30.9 | 2.54 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 29.7 | 6.84 | 6.86 | n/a | no err | **3.01** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.11 | **1.64** | **1.63** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.465** | **0.474** | **0.463** | no err | 0.544 | n/a | 29.1 | 2.52 | n/a |
| dataclass field wrong type | 0.979 | 1.42 | 0.973 | 0.775 | 0.773 | **0.496** | 32.1 | no err | 0.703 |
| dataclass assignment wrong type | **0.416** | 1.26 | **0.417** | 0.469 | 0.463 | 0.444 | no err | no err | 0.535 |
| value check fails (int > 0 ← -5) | 0.943 | 1.02 | 0.946 | **0.479** | **0.483** | n/a | 43.2 | n/a | n/a |
| invalid email | 1.14 | 1.14 | 1.15 | **0.676** | **0.674** | n/a | 43.9 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.218** |
| typecheck_record · cached spec | **1.01** |
| -> Self · called on the class that defines it | **0.074** |
| -> Self · called on a subclass | **0.084** |
| other: Self · called on a subclass | **0.092** |
| Self \| None · called on a subclass (a wrapper per class) | **0.193** |
| class method -> Self · called on a subclass | **0.202** |
| Ok(value) | **0.070** |
| protect · the awaitable completes | **0.470** |
| protect · the awaitable raises | **0.626** |
| Self: a Base where a Child is expected (raise + catch) | **1.03** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 4.59 | 3.00 | **0.928** | 0.931 | n/a | 30.1 | 2.68 | n/a |
| 3 wrong args of 12 | 8.74 | 6.29 | **1.64** | 1.70 | n/a | 29.7 | 3.37 | n/a |
| missing argument | 4.29 | 2.90 | 1.06 | 1.07 | n/a | 0.418 | **0.198** | n/a |
| unknown keyword argument | 2.19 | 1.13 | 1.05 | 1.05 | n/a | 0.456 | **0.153** | n/a |
| wrong keyword-only argument | 4.83 | 3.26 | **1.06** | 1.08 | n/a | 30.3 | 2.77 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.31 | 7.27 | n/a | no err | **3.27** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.16 | **2.14** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 4.38 | 2.86 | no err | **0.935** | n/a | 29.1 | 2.71 | n/a |
| dataclass field wrong type | 5.06 | 3.43 | 1.26 | 1.22 | **0.966** | 31.2 | no err | 1.90 |
| dataclass assignment wrong type | 4.68 | 3.14 | 0.934 | **0.886** | 1.67 | no err | no err | 1.73 |
| value check fails (int > 0 ← -5) | 4.79 | 3.26 | 1.03 | **1.01** | n/a | 42.9 | n/a | n/a |
| invalid email | 5.00 | 3.43 | **1.19** | 1.20 | n/a | 44.5 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.056 | 0.058 | 0.056 | 0.205 | 0.205 | 0.080 | 1.14 |
| 2 params | 0.066 | 0.068 | 0.065 | 0.216 | 0.214 | 0.092 | 1.64 |
| 4 params | 0.090 | 0.094 | 0.092 | 0.244 | 0.243 | 0.128 | 2.57 |
| 8 params | 0.149 | 0.157 | 0.149 | 0.293 | 0.293 | 0.189 | 4.47 |
| 16 params | 0.252 | 0.256 | 0.250 | 0.385 | 0.386 | 0.313 | 8.00 |
| 32 params | 0.452 | 0.461 | 0.452 | 0.593 | 0.592 | 0.550 | 15.6 |
| fixed cost (ns) | 43 | 45 | 43 | 192 | 191 | 66 | 690 |
| per param (ns) | 12.8 | 13.1 | 12.9 | 12.5 | 12.5 | 15.2 | 465.2 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.280 | 0.260 | 0.280 | 0.400 | 150 | 0.0 |
| enforced | 103.6 | 6.46 | 51.2 | 5.90 | 74.0 | 203 | 8.5 |
| enf.coerce | 103.6 | 6.92 | 52.1 | 5.15 | 80.6 | 203 | 10.4 |
| enf.deep | 105.1 | 6.60 | 52.2 | 5.34 | 77.5 | 202 | 8.5 |
| pydantic | 65.4 | 190 | 6.07 | 268 | 2.52 | 415 | 4.0 |
| pyd.strict | 64.9 | 180 | 5.51 | 273 | 2.54 | 428 | 4.0 |
| pyd.model | 53.8 | n/a | n/a | n/a | n/a | 232 | n/a |
| beartype | 56.6 | 305 | 1.52 | 606 | 2.86 | 520 | 2.8 |
| typeguard | 71.6 | 2,270 | 15.3 | 2,375 | 19.4 | 4,191 | 1.7 |
| attrs | 24.9 | n/a | n/a | n/a | n/a | 255 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.28× slower  (10 cases) | 12 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× slower  (10 cases) | 30 |
| pydantic | 2.48× slower  (32 cases) | 1.31× faster  (9 cases) | 1 |
| pyd.strict | 2.48× slower  (32 cases) | 1.24× faster  (10 cases) | 1 |
| pyd.model | 2.36× slower  (2 cases) | 1.36× faster  (2 cases) | 0 |
| beartype | 1.18× slower  (30 cases) | 16.56× slower  (9 cases) | 8 |
| typeguard | 20.57× slower  (27 cases) | 1.52× slower  (6 cases) | 0 |
| attrs | 1.19× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 19 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
