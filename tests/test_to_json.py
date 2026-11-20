"""``to_json``: a value as JSON text, a ``SecretStr`` masked unless asked (2026-10-22)."""
from dataclasses import field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum, IntEnum, StrEnum
from fractions import Fraction
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import NamedTuple
from uuid import UUID
import json

import pytest

from enforced import TypeModel, dataclass, to_json
from enforced.data_types import Email, Port, SecretStr, Url


class Colour(Enum):
    RED = "red"


class Level(IntEnum):
    HIGH = 2


class Mode(StrEnum):
    FAST = "fast"


class Even(TypeModel[int]):
    @classmethod
    def clean(cls, raw: int) -> int:
        return raw


@dataclass
class Address:
    city: str
    zip: str


@dataclass
class Customer:
    email: Email
    password: SecretStr
    address: Address
    tags: list[str] = field(default_factory = list)


def _back(obj, **options):
    return json.loads(to_json(obj, **options))


# ── what each value becomes ─────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (None, None), (True, True), (False, False), (0, 0), (-3, -3), (1.5, 1.5), ("text", "text"), ("", ""),
    (Port(8080), 8080), (Even(4), 4), (Email("ana@example.com"), "ana@example.com"),
    (Url("https://example.com/x"), "https://example.com/x"),
    (Colour.RED, "red"), (Level.HIGH, 2), (Mode.FAST, "fast"),
    (datetime(2026, 10, 22, 9, 30), "2026-10-22T09:30:00"),
    (datetime(2026, 10, 22, 9, 30, tzinfo = timezone.utc), "2026-10-22T09:30:00+00:00"),
    (date(2026, 10, 22), "2026-10-22"), (time(9, 30), "09:30:00"),
    (Decimal("1.10"), "1.10"), (Fraction(1, 3), "1/3"),
    (UUID(int = 1), "00000000-0000-0000-0000-000000000001"),
    (PurePosixPath("/etc/x"), "/etc/x"),
    ([1, "a"], [1, "a"]), ((1, 2), [1, 2]), (frozenset({1}), [1]), ({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]}),
    (MappingProxyType({"a": 1}), {"a": 1}),
    ], ids = repr)
def test_each_kind_of_value(value, expected):
    assert _back(value) == expected


def test_subclasses_are_written_as_their_base_value():
    #* json.dumps would call a subclass's own __str__ / __repr__ for some: here its value is what counts.
    class Shouty(str):
        def __str__(self) -> str:
            return "NOT THIS"

    assert _back(Shouty("this")) == "this"
    assert type(_back({"p": Port(80)})["p"]) is int


def test_a_dataclass_is_an_object_of_its_fields_nested_ones_included():
    customer = Customer(Email("ana@example.com"), SecretStr("s3cret"), Address("Athens", "10431"), ["vip"])
    assert _back(customer) == {"email": "ana@example.com", "password": "**********",
                                "address": {"city": "Athens", "zip": "10431"}, "tags": ["vip"]}


def test_a_named_tuple_is_an_array():
    class Point(NamedTuple):
        x: int
        y: int

    assert _back(Point(1, 2)) == [1, 2]


# ── secrets ─────────────────────────────────────────────────────────────────

def test_a_secret_is_masked_by_default_unlike_json_dumps():
    secret = SecretStr("s3cret")
    assert json.dumps({"key": secret}) == '{"key": "s3cret"}'        # the trap this function is for
    assert to_json({"key": secret}) == '{"key": "**********"}'
    assert "s3cret" not in to_json([secret, {"nested": (secret,)}])


def test_reveal_secrets_writes_the_real_text():
    assert _back({"key": SecretStr("s3cret")}, reveal_secrets = True) == {"key": "s3cret"}
    customer = Customer(Email("a@b.co"), SecretStr("pw"), Address("x", "y"))
    assert _back(customer, reveal_secrets = True)["password"] == "pw"


def test_a_secret_as_a_key_stays_masked_even_when_revealing():
    assert _back({SecretStr("s3cret"): 1}, reveal_secrets = True) == {"**********": 1}


# ── keys ────────────────────────────────────────────────────────────────────

def test_keys_text_numbers_booleans_none_and_enums():
    assert _back({1: "a", 2.5: "b", None: "d", Colour.RED: "e", Level.HIGH: "f"}) == \
        {"1": "a", "2.5": "b", "null": "d", "red": "e", "2": "f"}
    assert _back({True: "c"}) == {"true": "c"}                     # (True == 1: a key of its own dictionary)


def test_other_keys_are_refused():
    with pytest.raises(TypeError, match = "a key must be text or a number, got a tuple"):
        to_json({(1, 2): "x"})


# ── what is refused ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [b"bytes", timedelta(seconds = 1), 1 + 2j, object(), {1, object()}], ids = repr)
def test_what_has_no_json_form_is_a_type_error(value):
    with pytest.raises(TypeError, match = "can't be written as JSON"):
        to_json(value)


def test_the_error_says_where_the_value_is():
    with pytest.raises(TypeError, match = r"at orders\[1\]\.total"):
        to_json({"orders": [{"total": 1}, {"total": b"x"}]})
    customer = Customer(Email("a@b.co"), SecretStr("pw"), Address("x", "y"), ["ok", b"bad"])   # type: ignore[list-item]
    with pytest.raises(TypeError, match = r"at tags\[1\]"):
        to_json(customer)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")], ids = repr)
def test_nan_and_infinity_are_refused(number):
    with pytest.raises(ValueError, match = "no JSON"):
        to_json({"x": [number]})


def test_a_value_that_contains_itself_is_refused():
    loop: list = [1]
    loop.append(loop)
    with pytest.raises(ValueError, match = r"contains itself at \[1\]"):
        to_json(loop)
    shared = [1]
    assert _back([shared, shared]) == [[1], [1]]                   # the same list twice is no cycle


# ── the text ────────────────────────────────────────────────────────────────

def test_indent_and_unicode():
    assert to_json({"a": 1}, indent = 2) == '{\n  "a": 1\n}'
    assert to_json("café ✓") == '"café ✓"'                         # written as is, not escaped


def test_a_path_from_the_platform():
    assert _back(Path("a") / "b") == str(Path("a") / "b")
