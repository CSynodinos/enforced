# enforced comparison

*2026-10-13 22:20*

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
| 1 param | 0.011 | **0.064** | 0.067 | **0.064** | 0.216 | 0.213 | 0.091 | 1.14 |
| 2 params · positional | 0.012 | **0.072** | 0.075 | **0.072** | 0.227 | 0.229 | 0.108 | 1.63 |
| 2 params · keyword | 0.017 | **0.157** | 0.164 | **0.158** | 0.480 | 0.485 | 0.175 | 1.65 |
| 5 params · mixed types | 0.013 | **0.104** | **0.104** | **0.105** | 0.276 | 0.277 | 0.157 | 2.89 |
| 12 params · positional | 0.019 | **0.201** | **0.201** | **0.201** | 0.351 | 0.353 | 0.276 | 5.88 |
| 12 params · keyword | 0.040 | **0.630** | **0.634** | **0.636** | 1.54 | 1.54 | 0.654 | 5.90 |
| defaults used (1 of 5 given) | 0.015 | 0.173 | 0.170 | 0.174 | 0.562 | 0.562 | **0.163** | 4.86 |
| keyword-only params | 0.023 | **0.166** | **0.165** | **0.168** | 0.397 | 0.390 | 0.171 | 2.01 |
| Optional · Literal · Sequence · type[] | 0.015 | **0.206** | **0.210** | **0.204** | 0.498 | 0.498 | 0.231 | 5.90 |
| unions · int \| str \| None, float \| None | 0.012 | **0.085** | **0.084** | **0.084** | 0.273 | 0.259 | 0.121 | 3.99 |
| optional forms · type[] \| None, Literal \| None, Sequence \| None | 0.014 | **0.234** | **0.236** | **0.235** | 0.503 | 0.499 | **0.239** | 6.50 |
| user-defined classes | 0.013 | **0.072** | **0.072** | **0.072** | 0.228 | 0.228 | 0.118 | 1.64 |
| Any / object | 0.012 | 0.056 | 0.055 | 0.055 | 0.222 | 0.222 | **0.012** | 1.15 |
| \*args / \*\*kwargs (3 + 2) | 0.041 | **0.257** | **0.256** | **0.262** | 0.423 | 0.426 | 0.504 | 4.04 |
| return value checked | 0.011 | **0.077** | **0.079** | **0.077** | 0.247 | 0.248 | 0.101 | 1.66 |
| async def (coroutine driven) | 0.104 | **0.203** | 0.210 | **0.201** | 0.450 | 0.452 | 0.242 | 1.81 |
| method on an instance | 0.013 | **0.078** | 0.081 | **0.079** | 0.241 | 0.241 | 0.112 | 1.67 |
| positional-only params · one default used | 0.014 | 0.124 | 0.125 | 0.124 | 0.397 | 0.399 | **0.119** | 2.00 |
| float params given ints (numeric tower) | 0.013 | 0.273 | 0.299 | 0.275 | **0.258** | **0.257** | ERR | 1.31 |
| Callable · Iterable | 0.013 | **0.168** | **0.167** | **0.168** | 0.339 | 0.338 | 0.511 | 6.19 |

  ERR: rejected a valid call: BeartypeCallHintParamViolation: Function _pv_bench_targets.f_floats() parameter a=1 violates type hint \<class 'float'>, as  

## Collections

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| list[int] × 10 | 0.016 | 0.063† | 0.065† | **0.188** | 0.331 | 0.330 | 0.133† | 1.95† |
| list[int] × 1,000 | 0.013 | 0.063† | 0.065† | **4.97** | 6.83 | 6.79 | 0.143† | 1.92† |
| list[int] × 100,000 | 0.013 | 0.063† | 0.065† | **467** | 1,070 | 1,078 | 0.156† | 1.94† |
| dict[str, int] × 100 | 0.012 | 0.063† | 0.063† | **1.33** | 2.26 | 2.26 | 0.144† | 2.48† |
| tuple[int, str, float] | 0.012 | 0.064† | 0.066† | **0.118** | 0.275 | 0.272 | 0.122 | 2.93 |
| dict[str, list[int]] (10 × 10) | 0.012 | 0.062† | 0.062† | **1.28** | 1.39 | 1.39 | 0.192† | 3.30† |
| Mapping[str, Sequence[float]] (10 × 10) | 0.012 | 0.111† | 0.110† | **2.06** | 4.62 | 4.60 | 0.302† | 3.20† |
| TypedDict (4 keys, one a list) | 0.013 | 0.062† | 0.063† | **0.294** | 0.419 | 0.420 | 0.179† | 4.88 |
| list of 100 objects | 0.012 | 0.062† | 0.065† | **0.669** | 0.871 | 0.869 | 0.144† | 1.94† |
| set[str] × 100 | 0.012 | **0.063** | 0.065 | 0.727 | 1.73 | 1.74 | 0.127 | 2.12 |
| list[int \| None] × 1,000 | 0.012 | 0.063† | 0.066† | **5.73** | 6.82 | 6.82 | 0.150† | 3.78† |
| tuple[int, ...] × 1,000 | 0.012 | 0.062† | 0.065† | **4.86** | 6.25 | 6.28 | 0.142† | 2.13† |

## Classes

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| construct Point (2 of 3 fields) | 0.096 | 0.429 | 0.429 | 0.429 | 0.589 | 0.581 | 0.393 | 0.340 | 0.096† | **0.304** |
| construct Order tree (5 objects) | 0.462 | 2.00† | 2.10† | 2.19 | 2.83 | 2.84 | 1.92 | 1.74 | 0.463† | **1.55** |
| assign point.x = 5 | 0.004 | **0.061** | **0.061** | 0.062 | 0.270 | 0.271 | 0.371 | 0.004† | 0.004† | 0.120 |

## Validated values

*µs per call, median*

| case | plain | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype |
|:--|--:|--:|--:|--:|--:|--:|--:|
| int > 0 (value check) | 0.011 | **0.097** | **0.098** | **0.096** | 0.227 | 0.229 | 0.135 |
| list[int > 0] × 1,000 | 0.012 | 0.062† | 0.066† | **19.3** | 21.3 | 21.4 | 0.183† |
| email · already valid str | 0.012 | 1.01 | 1.01 | 1.00 | 0.976 | 0.967 | **0.799** |
| email · normalised (domain lower-cased) | 0.012 | 1.01≠ | 1.01≠ | 0.999≠ | 0.971≠ | 0.970≠ | **0.798** |

## Errors (raise + catch)

*µs per call, median · time to raise and catch*

| case | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 0.575 | 0.644 | 0.572 | **0.484** | **0.484** | n/a | 32.2 | 2.47 | n/a |
| 3 wrong args of 12 | 1.08 | 2.03 | 1.08 | **0.701** | 0.781 | n/a | 30.4 | 3.12 | n/a |
| missing argument | 0.568 | 0.567 | 0.570 | 0.526 | 0.525 | n/a | 0.395 | **0.175** | n/a |
| unknown keyword argument | 0.721 | 0.713 | 0.721 | 0.587 | 0.578 | n/a | 0.440 | **0.133** | n/a |
| wrong keyword-only argument | 0.811 | 0.873 | 0.817 | **0.600** | **0.596** | n/a | 31.1 | 2.54 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 29.7 | 6.71 | 6.80 | n/a | no err | **3.01** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 9.26 | **1.64** | **1.63** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | **0.467** | **0.474** | **0.470** | no err | 0.537 | n/a | 29.3 | 2.53 | n/a |
| dataclass field wrong type | 0.985 | 1.44 | 0.976 | 0.765 | 0.762 | **0.488** | 32.4 | no err | 0.694 |
| dataclass assignment wrong type | **0.415** | 1.27 | **0.417** | 0.469 | 0.460 | 0.448 | no err | no err | 0.541 |
| value check fails (int > 0 ← -5) | 0.943 | 1.03 | 0.937 | **0.472** | **0.472** | n/a | 43.6 | n/a | n/a |
| invalid email | 1.14 | 1.13 | 1.13 | **0.666** | **0.663** | n/a | 44.5 | n/a | n/a |

## enforced only

*µs per call, median*

| case | enforced |
|:--|--:|
| typecheck_function(fn, args) · repeated | **0.220** |
| typecheck_record · cached spec | **1.03** |
| -> Self · called on the class that defines it | **0.075** |
| -> Self · called on a subclass | **0.083** |
| other: Self · called on a subclass | **0.092** |
| Self \| None · called on a subclass (a wrapper per class) | **0.191** |
| class method -> Self · called on a subclass | **0.204** |
| Ok(value) | **0.071** |
| protect · the awaitable completes | **0.469** |
| protect · the awaitable raises | **0.624** |
| Self: a Base where a Child is expected (raise + catch) | **1.03** |

## Error messages, rendered

*µs per raise + catch + str(e), median · fresh interpreter each, FORCE_COLOR=1 · enf.nocolour = ENFORCED_COLOURS_OFF=1*

| case | enforced | enf.nocolour | pydantic | pyd.strict | pyd.model | beartype | typeguard | attrs |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 wrong arg of 2 | 2.41 | 2.31 | **0.916** | 0.929 | n/a | 32.6 | 2.69 | n/a |
| 3 wrong args of 12 | 5.32 | 5.03 | **1.63** | 1.69 | n/a | 30.0 | 3.39 | n/a |
| missing argument | 2.48 | 2.27 | 1.05 | 1.06 | n/a | 0.416 | **0.198** | n/a |
| unknown keyword argument | 1.09 | 1.01 | 1.04 | 1.05 | n/a | 0.476 | **0.153** | n/a |
| wrong keyword-only argument | 2.66 | 2.50 | **1.05** | 1.08 | n/a | 30.6 | 2.79 | n/a |
| bad first item of list[int] × 1,000 | no err | no err | 7.37 | 7.40 | n/a | no err | **3.22** | n/a |
| bad last item in dict[str, list[int]] (10 × 10) | no err | no err | 2.17 | **2.12** | n/a | no err | no err | n/a |
| wrong return value (-> int returns a str) | 2.41 | 2.16 | no err | **0.930** | n/a | 28.4 | 2.76 | n/a |
| dataclass field wrong type | 2.90 | 2.77 | 1.24 | 1.22 | **0.975** | 31.4 | no err | 1.90 |
| dataclass assignment wrong type | 2.83 | 2.30 | 0.916 | **0.887** | 1.66 | no err | no err | 1.76 |
| value check fails (int > 0 ← -5) | 2.92 | 2.56 | **1.01** | 1.03 | n/a | 43.8 | n/a | n/a |
| invalid email | 3.10 | 2.75 | **1.17** | 1.19 | n/a | 44.2 | n/a | n/a |
| colour codes in the message | yes | no | no | no | no | no | no | no |

compare with the 'Errors (raise + catch)' table above: the difference is the cost of building the message text  

## Scaling with parameter count

*overhead over the undecorated call, µs (all params int, positional)*

| params | enforced | enf.coerce | enf.deep | pydantic | pyd.strict | beartype | typeguard |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 1 param | 0.054 | 0.055 | 0.055 | 0.204 | 0.204 | 0.080 | 1.12 |
| 2 params | 0.066 | 0.069 | 0.066 | 0.214 | 0.214 | 0.096 | 1.64 |
| 4 params | 0.091 | 0.096 | 0.090 | 0.240 | 0.239 | 0.123 | 2.57 |
| 8 params | 0.147 | 0.147 | 0.146 | 0.289 | 0.288 | 0.192 | 4.40 |
| 16 params | 0.252 | 0.253 | 0.252 | 0.386 | 0.384 | 0.317 | 8.06 |
| 32 params | 0.456 | 0.461 | 0.459 | 0.624 | 0.617 | 0.552 | 15.6 |
| fixed cost (ns) | 41 | 43 | 40 | 184 | 184 | 66 | 671 |
| per param (ns) | 13.0 | 13.1 | 13.1 | 13.5 | 13.3 | 15.3 | 466.5 |

least-squares fit: overhead ≈ fixed + per_param × n  

## Cold start

*fresh interpreter per run, median of 7 · library warmed on an unrelated function first*

| library | import ms | decorate f_2 µs | 1st call µs | decorate f_12 µs | 1st call µs | define Point µs | KB / function |
|:--|--:|--:|--:|--:|--:|--:|--:|
| plain | 0.0 | 0.320 | 0.260 | 0.260 | 0.420 | 151 | 0.0 |
| enforced | 263.8 | 7.62 | 53.3 | 7.22 | 79.6 | 229 | 8.5 |
| enf.coerce | 271.3 | 9.43 | 55.2 | 7.52 | 89.7 | 230 | 10.4 |
| enf.deep | 264.6 | 7.42 | 54.9 | 7.47 | 85.5 | 223 | 8.5 |
| pydantic | 67.5 | 184 | 5.69 | 307 | 2.74 | 404 | 4.0 |
| pyd.strict | 66.1 | 186 | 5.68 | 287 | 2.57 | 418 | 4.0 |
| pyd.model | 54.4 | n/a | n/a | n/a | n/a | 233 | n/a |
| beartype | 55.7 | 250 | 1.35 | 562 | 2.39 | 543 | 2.8 |
| typeguard | 73.1 | 2,290 | 15.2 | 2,401 | 19.7 | 4,275 | 1.6 |
| attrs | 25.8 | n/a | n/a | n/a | n/a | 300 | n/a |

import = the library's import in a bare interpreter (start-up excluded, the standard-library modules it pulls in included); memory = traced allocations per decorated + called function (100 functions, 1-5 params)  

## Summary

*geometric mean of per-call time ratio vs enforced, equivalent-work cases only (no †)*

| library | hot path | error path | fastest in |
|:--|:--|:--|--:|
| enf.coerce | 1.02× slower  (32 cases) | 1.27× slower  (10 cases) | 13 |
| enf.deep | 1.08× slower  (32 cases) | 1.00× faster  (10 cases) | 29 |
| pydantic | 2.48× slower  (32 cases) | 1.33× faster  (9 cases) | 1 |
| pyd.strict | 2.48× slower  (32 cases) | 1.26× faster  (10 cases) | 1 |
| pyd.model | 2.36× slower  (2 cases) | 1.37× faster  (2 cases) | 0 |
| beartype | 1.20× slower  (30 cases) | 16.62× slower  (9 cases) | 6 |
| typeguard | 20.55× slower  (27 cases) | 1.51× slower  (6 cases) | 0 |
| attrs | 1.18× slower  (2 cases) | 1.04× faster  (2 cases) | 2 |
| enforced | reference | reference | 19 |

each cell says how that library compares with enforced (faster or slower; green = enforced is faster, on a colour terminal). 'fastest in' counts hot-path cases won among checkers doing the full work (a tie counts for each).  

legend: bold = fastest checker doing the full work (or within 3% of it; green on a colour terminal) · † skips some checks relevant to this case (see Coverage) · \~ noisy (IQR > 15% of median) · ≠ returned a different value · n/a = no equivalent feature
