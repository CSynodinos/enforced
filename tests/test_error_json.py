"""
``InvalidDataError.errors()`` and ``.json()``: the problems as data in pydantic's shape (``type``,
``loc``, ``msg``, ``input``, ``ctx``), every value JSON-safe.
"""
from enforced import InvalidDataError, dataclass, enforce, validate, validate_record
from enforced.data_types import Email, SecretStr
from typing import Annotated, Literal, NamedTuple, TypedDict
import json
import math
import pickle
import re
import pytest


def _raised(fn, *args, **kwargs) -> InvalidDataError:
    with pytest.raises(InvalidDataError) as info:
        fn(*args, **kwargs)
    return info.value


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ── the shape ────────────────────────────────────────────────────────────────

def test_a_wrong_type():
    @validate
    def f(a: int, b: str = "x") -> None: ...

    assert _raised(f, "1").errors() == [{
        "type": "type", "loc": ["a"], "msg": "expected type: 'int', got type 'str'", "input": "1",
        "ctx": {"expected": "int", "origin": "Function f", "context": "call"},
        }]


def test_every_problem_in_the_order_of_the_parameters():
    @validate
    def f(a: int, b: Email, c: Annotated[int, lambda x: x > 0], m: Literal["r", "w"] = "r") -> None: ...

    entries = _raised(f, c = -1, b = "nope", a = "1", m = "x").errors()
    assert [(e["type"], e["loc"], e["msg"]) for e in entries] == [
        ("type", ["a"], "expected type: 'int', got type 'str'"),
        ("invalid", ["b"], "invalid 'Email': must contain exactly one '@'"),
        ("invalid", ["c"], "invalid 'int': failed check x > 0"),
        ("type", ["m"], "expected type: Literal['r', 'w'], got type 'str'"),
        ]
    assert entries[1]["ctx"]["reason"] == "must contain exactly one '@'" and entries[1]["ctx"]["expected"] == "Email"
    assert entries[3]["ctx"]["expected"] == "Literal['r', 'w']"


def test_missing_arguments_are_one_entry_each():
    @validate
    def f(a: int, b: list[str], c: float = 0.0) -> None: ...

    assert _raised(f).errors() == [
        {"type": "missing", "loc": ["a"], "msg": "missing required argument",
         "ctx": {"expected": "int", "origin": "Function f", "context": "call"}},
        {"type": "missing", "loc": ["b"], "msg": "missing required argument",
         "ctx": {"expected": "list[str]", "origin": "Function f", "context": "call"}},
        ]


def test_a_call_that_cant_be_bound_is_one_entry_in_python_s_words():
    @validate
    def f(a: int) -> None: ...

    assert _raised(f, 1, 2).errors() == [{"type": "binding", "loc": [], "msg": "too many positional arguments",
                                          "ctx": {"context": "call"}}]
    assert _raised(f, 1, b = 2).errors()[0]["msg"] == "got an unexpected keyword argument 'b'"


def test_an_error_made_from_a_sentence():
    assert InvalidDataError("something is wrong").errors() == [
        {"type": "error", "loc": [], "msg": "something is wrong", "ctx": {"context": "call"}}]


def test_return_default_and_dataclass_field():
    @validate(check_return = True)
    def r(x: int) -> int:
        return "no"                                                  # type: ignore[return-value]

    assert _raised(r, 1).errors()[0] | {"ctx": None} == {
        "type": "return", "loc": ["return"], "msg": "expected type: 'int', got type 'str'", "input": "no", "ctx": None}

    @validate
    def d(x: int = "8080") -> None: ...                              # type: ignore[assignment]

    entry = _raised(d).errors()[0]
    assert (entry["type"], entry["loc"], entry["input"], entry["ctx"]["context"]) == ("default", ["x"], "8080", "definition")

    @dataclass
    class Order:
        qty: int

    order = Order(1)
    assert _raised(setattr, order, "qty", "many").errors() == [{
        "type": "field", "loc": ["qty"], "msg": "expected type: 'int', got type 'str'", "input": "many",
        "ctx": {"expected": "int", "origin": "Dataclass Order", "context": "field assignment"}}]
    assert _raised(Order, "x").errors()[0]["ctx"]["origin"] == "Dataclass Order"


def test_a_method_of_an_enforced_class():
    @enforce
    class Account:
        def deposit(self, amount: float) -> None: ...

    assert _raised(Account().deposit, "x").errors()[0]["ctx"]["origin"] == "Method Account.deposit"


# ── loc: where, as a list ────────────────────────────────────────────────────

class Row(TypedDict):
    sku: str
    qty: int


class Point(NamedTuple):
    x: int
    y: int


def test_loc_of_items_inside_a_value():
    @validate(deep = True)
    def f(prices: dict[str, list[float]], rows: list[Row], point: Point, pair: tuple[int, str]) -> None: ...

    entries = _raised(f, {"apple": [1.5, "n/a"], 3: [2.0]}, [{"sku": "a", "qty": "x"}, {"qty": 1}],
                      Point(1, "y"), (1, 2)).errors()
    assert [(e["type"], e["loc"]) for e in entries] == [
        ("type", ["prices", "apple", 1]),
        ("type", ["prices", 3, "[key]"]),                            # the key is wrong: pydantic's marker
        ("type", ["rows", 0, "qty"]),
        ("missing_key", ["rows", 1, "sku"]),
        ("type", ["point", "y"]),
        ("type", ["pair", 1]),
        ]
    missing_key = entries[3]
    assert "input" not in missing_key and missing_key["ctx"]["key"] == "sku"
    assert missing_key["msg"] == "missing required key 'sku' (expecting type str)"


@pytest.mark.parametrize("key", ["a'][0", "with \"quotes\"", "x.y", "[key 1]", ""])
def test_loc_keeps_awkward_keys_as_they_are(key):
    #* Paths are text in the messages; read back from that text, these keys would break the steps.
    @validate(deep = True)
    def f(m: dict[str, int]) -> None: ...

    assert _raised(f, {key: "v"}).errors()[0]["loc"] == ["m", key]


def test_loc_of_a_key_that_is_no_json_value():
    @validate(deep = True)
    def f(m: dict[tuple[int, int], int]) -> None: ...

    assert _raised(f, {(1, 2): "v"}).errors()[0]["loc"] == ["m", "(1, 2)"]


def test_loc_of_varargs_kwargs_and_a_returned_item():
    @validate(check_return = True, deep = True)
    def f(*parts: str, **tags: int) -> list[int]:
        return [1, "two"]                                            # type: ignore[list-item]

    assert [e["loc"] for e in _raised(f, "a", 2, t = "x").errors()] == [["parts", 1], ["tags", "t"]]
    assert _raised(f).errors()[0]["loc"] == ["return", 1]


def test_length_and_its_context():
    @validate(deep = True)
    def f(t: tuple[int, int]) -> None: ...

    entry = _raised(f, (1, 2, 3)).errors()[0]
    assert entry["msg"] == "expected type: tuple[int, int] with 2 items, got 3 items" and entry["input"] == [1, 2, 3]
    assert (entry["ctx"]["expected_length"], entry["ctx"]["actual_length"]) == (2, 3)


# ── input: JSON-safe, bounded, secrets masked ────────────────────────────────

def test_include_input_and_include_context():
    @validate
    def f(a: int) -> None: ...

    error = _raised(f, "secret")
    assert error.errors(include_input = False) == [{"type": "type", "loc": ["a"], "msg": "expected type: 'int', got type 'str'",
                                                     "ctx": {"expected": "int", "origin": "Function f", "context": "call"}}]
    assert error.errors(include_context = False) == [{"type": "type", "loc": ["a"],
                                                       "msg": "expected type: 'int', got type 'str'", "input": "secret"}]
    assert "secret" not in error.json(include_input = False)


def test_a_secret_is_masked_in_input():
    @validate
    def f(n: int, m: int) -> None: ...

    error = _raised(f, SecretStr("hunter2"), [SecretStr("in a list")])
    assert [e["input"] for e in error.errors()] == ["**********", ["**********"]]
    assert "hunter2" not in error.json() and "in a list" not in error.json()


class _Odd:
    def __repr__(self) -> str:
        return "<odd>"


class _Broken:
    def __repr__(self) -> str:
        raise RuntimeError("no repr")


@pytest.mark.parametrize("value, shown", [
    (None, None), (True, True), (3, 3), (1.5, 1.5),
    (math.nan, "nan"), (math.inf, "inf"), (-math.inf, "-inf"),
    ("x" * 300, "x" * 200 + "..."),
    (10 ** 2000, "<int of 6644 bits>"),
    (b"raw", "b'raw'"),
    ((1, "a"), [1, "a"]), ({3}, [3]),
    ({"k": [1, {"n": math.nan}], 2: None}, {"k": [1, {"n": "nan"}], "2": None}),
    (list(range(60)), list(range(50)) + ["..."]),
    (_Odd(), "<odd>"),
    (Email("a@b.co"), "a@b.co"),
    ])
def test_input_is_json_safe(value, shown):
    @validate
    def f(x: Literal["only this"]) -> None: ...

    entry = _raised(f, value).errors()[0]
    assert entry["input"] == shown
    json.dumps(entry, allow_nan = False)                             # never fails


def test_input_of_values_that_refuse_to_be_shown():
    @validate
    def f(x: int) -> None: ...

    assert json.loads(_raised(f, _Broken()).json())[0]["input"].startswith("<")
    nested: list = []
    nested.append(nested)                                            # a list that contains itself
    json.loads(_raised(f, nested).json())


# ── json() ───────────────────────────────────────────────────────────────────

def test_json_is_errors_as_text():
    @validate(deep = True)
    def f(a: int, xs: list[float]) -> None: ...

    error = _raised(f, "ü", [1, "n/a"])
    assert json.loads(error.json()) == error.errors()
    assert "ü" in error.json()                                       # written as UTF-8, not \u escapes
    assert error.json(indent = 2).startswith("[\n  {")


def test_msg_is_plain_whatever_the_colours(monkeypatch):
    import clitint._tint as tool                                    # the switches are clitint's state

    @validate
    def f(a: int) -> None: ...

    monkeypatch.setattr(tool, "_CHOSEN", True)                        # colours on
    error = _raised(f, "x")
    assert "\x1b" in str(error) and "\x1b" not in error.json()


def test_msg_says_what_the_message_says():
    #* The short form is the message without its subject and its value: they can't drift apart.
    @validate(check_return = True, deep = True)
    def f(a: int, b: Email, t: tuple[int, int], rows: list[Row], m: Literal["r"] = "r") -> int:
        return "x"                                                   # type: ignore[return-value]

    for error in (_raised(f, "1", "nope", (1,), [{"qty": "x"}], m = "w"), _raised(f, 1, "a@b.co", (1, 2), [])):
        for problem, entry in zip(error.problems, error.errors()):
            assert entry["msg"] in _plain(str(problem))


@validate(deep = True)
def _pickled(m: dict[str, list[int]], n: int) -> None: ...


def test_the_same_after_pickling():
    #* At module level: pickle finds a function again by its name (a local one comes back as a stand-in).
    error = _raised(_pickled, {"a": [1, "x"]}, "y")
    assert pickle.loads(pickle.dumps(error)).errors() == error.errors()


def test_from_a_record_and_a_warning():
    import warnings
    entries = _raised(validate_record, {"object_name": "make", "record": {"n": int}, "args": ("x",)}).errors()
    assert entries[0]["ctx"]["origin"] == "Function make" and entries[0]["loc"] == ["n"]

    @validate(on_error = "warn")
    def f(a: int) -> None: ...

    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        f("x")
    assert caught[0].message.error.errors()[0]["loc"] == ["a"]
