import copy
import pickle
from decimal import Decimal
from fractions import Fraction

import pytest

from pyvalidate._typechecker._type_data_model import FAILED, TypeModel
from pyvalidate.data_types import Email, Port


# ── helpers ──────────────────────────────────────────────────────────────────
class Percent(TypeModel[float]):
    @classmethod
    def validate(cls, raw):
        if not 0.0 <= raw <= 100.0:
            raise ValueError("must be between 0 and 100")
        return raw


class Token(TypeModel[bytes]):
    @classmethod
    def validate(cls, raw):
        if len(raw) != 4:
            raise ValueError("must be 4 bytes")
        return raw


class Money(TypeModel[Decimal]):
    @classmethod
    def validate(cls, raw):
        return raw.quantize(Decimal("0.01"))


class Ratio(TypeModel[Fraction]):
    @classmethod
    def validate(cls, raw):
        if raw < 0:
            raise ValueError("must not be negative")
        return raw


# ── construction and validation ──────────────────────────────────────────────
def test_valid_value_builds_an_instance():
    e = Email("ana@example.com")
    assert type(e) is Email
    assert e == "ana@example.com"


def test_validate_normalises_the_value():
    assert Email("  Ana@Example.COM ") == "Ana@example.com"


@pytest.mark.parametrize("raw, reason", [
    ("nope", "exactly one '@'"),
    ("a@@b.com", "exactly one '@'"),
    ("@example.com", "before '@'"),
    ("ana@localhost", "domain must look like"),
    ("ana@-bad.com", "domain must look like"),
    ("ana@bad-.com", "domain must look like"),
    ("ana@exa mple.com", "domain must look like"),
])
def test_invalid_value_raises_value_error_with_reason(raw, reason):
    with pytest.raises(ValueError, match=reason):
        Email(raw)


def test_default_validate_accepts_anything_of_the_base_type():
    class Anything(TypeModel[str]):
        pass
    assert Anything("x") == "x"


def test_validate_never_sees_a_model_subclass():
    seen = []

    class Spy(TypeModel[str]):
        @classmethod
        def validate(cls, raw):
            seen.append(type(raw))
            return raw
    Spy("a")
    assert seen == [str]


# ── it really is a T ─────────────────────────────────────────────────────────
def test_instance_is_a_real_base_type():
    e = Email("ana@example.com")
    assert isinstance(e, str) and isinstance(e, Email) and isinstance(e, TypeModel)
    assert e.upper() == "ANA@EXAMPLE.COM"
    assert len(e) == 15
    assert e.domain == "example.com"


def test_str_operations_return_plain_str():
    assert type(Email("ana@example.com").upper()) is str
    assert type(Email("ana@example.com") + "!") is str


def test_int_model_supports_arithmetic():
    p = Port(8080)
    assert isinstance(p, int)
    assert p + 1 == 8081 and type(p + 1) is int


def test_models_are_hashable_and_equal_to_the_raw_value():
    e = Email("ana@example.com")
    assert hash(e) == hash("ana@example.com")
    assert {e: 1}["ana@example.com"] == 1


def test_instances_are_immutable():
    e = Email("ana@example.com")
    with pytest.raises(AttributeError):
        e.extra = 1


def test_repr():
    assert repr(Email("ana@example.com")) == "Email('ana@example.com')"
    assert repr(Port(80)) == "Port(80)"
    assert str(Email("ana@example.com")) == "ana@example.com"


# ── input type checks ────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [1, 1.5, None, b"a@b.com", ["a@b.com"]])
def test_wrong_input_type_raises_type_error(bad):
    with pytest.raises(TypeError, match="Email expects a str"):
        Email(bad)


def test_int_model_rejects_bool():
    with pytest.raises(TypeError):
        Port(True)


def test_int_model_rejects_str_and_float():
    with pytest.raises(TypeError):
        Port("8080")
    with pytest.raises(TypeError):
        Port(80.0)


def test_out_of_range_int_is_a_value_error():
    for bad in (0, -1, 65536):
        with pytest.raises(ValueError, match="between 1 and 65535"):
            Port(bad)


def test_constructor_requires_exactly_one_argument():
    with pytest.raises(TypeError):
        Email()
    with pytest.raises(TypeError):
        Email("a@b.com", "c")


# ── idempotence ──────────────────────────────────────────────────────────────
def test_constructing_from_an_instance_returns_it():
    e = Email("ana@example.com")
    assert Email(e) is e


def test_a_different_model_is_revalidated():
    class Loose(TypeModel[str]):
        pass
    loose = Loose("not an email")
    with pytest.raises(ValueError):
        Email(loose)


def test_subclass_of_a_model_accepts_parent_instances():
    class Corp(Email):
        @classmethod
        def validate(cls, raw):
            raw = super().validate(raw)
            if not raw.endswith("@corp.com"):
                raise ValueError("must be a corp address")
            return raw
    assert Corp("a@corp.com").domain == "corp.com"
    with pytest.raises(ValueError, match="corp address"):
        Corp("a@example.com")
    with pytest.raises(ValueError, match="corp address"):
        Corp(Email("a@example.com"))      # a parent instance is not a Corp


# ── other base types ─────────────────────────────────────────────────────────
def test_float_model():
    assert Percent(12.5) == 12.5 and isinstance(Percent(1.0), float)
    with pytest.raises(ValueError):
        Percent(101.0)
    with pytest.raises(TypeError):
        Percent(5)                         # int is not a float


def test_bytes_model():
    assert Token(b"abcd") == b"abcd" and isinstance(Token(b"abcd"), bytes)
    with pytest.raises(ValueError):
        Token(b"abc")


def test_decimal_model_normalises():
    assert Money(Decimal("1.5")) == Decimal("1.50")
    assert str(Money(Decimal("1.5"))) == "1.50"


def test_fraction_model():
    assert Ratio(Fraction(1, 2)) + 1 == Fraction(3, 2)
    with pytest.raises(ValueError):
        Ratio(Fraction(-1, 2))


def test_complex_model():
    class Phase(TypeModel[complex]):
        pass
    assert Phase(1 + 2j) == 1 + 2j


# ── TypeModel[T] ─────────────────────────────────────────────────────────────
def test_subscripting_is_cached():
    assert TypeModel[str] is TypeModel[str]
    assert TypeModel[str] is not TypeModel[int]


def test_parameterised_base_shape():
    base = TypeModel[str]
    assert issubclass(base, TypeModel) and issubclass(base, str)
    assert base.__base_type__ is str


@pytest.mark.parametrize("bad", [list, dict, tuple, bool, object, "str", None, 3])
def test_unsupported_bases_are_rejected(bad):
    with pytest.raises(TypeError):
        TypeModel[bad]


def test_parameterising_twice_is_an_error():
    with pytest.raises(TypeError, match="already parameterised"):
        Email[str]


def test_subclassing_bare_typemodel_is_an_error():
    with pytest.raises(TypeError, match="must subclass TypeModel"):
        class Bare(TypeModel):
            pass


@pytest.mark.parametrize("attr", ["__new__", "__init__"])
def test_overriding_construction_is_forbidden(attr):
    with pytest.raises(TypeError, match="validate classmethod"):
        type("Broken", (TypeModel[str],), {attr: lambda self, *a, **k: None})


def test_validate_must_return_the_base_type():
    class Wrong(TypeModel[str]):
        @classmethod
        def validate(cls, raw):
            return 5
    with pytest.raises(TypeError, match="must return a str"):
        Wrong("x")


# ── pickle and copy ──────────────────────────────────────────────────────────
def test_failed_is_the_converters_sentinel():
    from pyvalidate._typechecker._type_conversion import FAILED as CONVERTER_FAILED
    assert FAILED is CONVERTER_FAILED


def test_pickle_round_trip():
    e = Email("ana@example.com")
    back = pickle.loads(pickle.dumps(e))
    assert back == e and type(back) is Email


def test_pickle_round_trip_for_every_base():
    for value in (Port(80), Percent(2.5), Token(b"abcd"), Money(Decimal("3")), Ratio(Fraction(1, 3))):
        back = pickle.loads(pickle.dumps(value))
        assert back == value and type(back) is type(value)


def test_copy_and_deepcopy():
    e = Email("ana@example.com")
    assert copy.copy(e) == e and type(copy.copy(e)) is Email
    assert copy.deepcopy(e) == e and type(copy.deepcopy(e)) is Email


class Gate(TypeModel[str]):
    allowed = {"ok", "fine"}

    @classmethod
    def validate(cls, raw):
        if raw not in cls.allowed:
            raise ValueError("not allowed")
        return raw


def test_unpickling_revalidates():
    data = pickle.dumps(Gate("fine"))
    Gate.allowed = {"ok"}                  # the rule tightens before the data is loaded
    try:
        with pytest.raises(ValueError, match="not allowed"):
            pickle.loads(data)
        assert pickle.loads(pickle.dumps(Gate("ok"))) == "ok"
    finally:
        Gate.allowed = {"ok", "fine"}


# ── the pyvalidate hook ──────────────────────────────────────────────────────
def test_hook_builds_an_instance_from_a_raw_value():
    value, reason = Email.__pyvalidate_convert__("  Ana@Example.COM ")
    assert type(value) is Email and value == "Ana@example.com" and reason is None


def test_hook_passes_an_instance_through_unchanged():
    e = Email("ana@example.com")
    value, reason = Email.__pyvalidate_convert__(e)
    assert value is e and reason is None


def test_hook_reports_the_reason_for_an_invalid_value():
    value, reason = Email.__pyvalidate_convert__("nope")
    assert value is FAILED and reason == "must contain exactly one '@'"


@pytest.mark.parametrize("bad", [5, None, b"x", 1.5])
def test_hook_wrong_type_fails_without_a_reason(bad):
    assert Email.__pyvalidate_convert__(bad) == (FAILED, None)


def test_hook_rejects_bool_for_int_models():
    assert Port.__pyvalidate_convert__(True) == (FAILED, None)
    assert Port.__pyvalidate_convert__(False) == (FAILED, None)


def test_hook_int_model():
    value, reason = Port.__pyvalidate_convert__(8080)
    assert type(value) is Port and value == 8080 and reason is None
    assert Port.__pyvalidate_convert__(70000) == (FAILED, "must be between 1 and 65535")


def test_hook_does_not_leak_other_exceptions():
    class Boom(TypeModel[str]):
        @classmethod
        def validate(cls, raw):
            raise RuntimeError("bug in validate")
    with pytest.raises(RuntimeError):
        Boom.__pyvalidate_convert__("x")     # a bug is not a validation failure


def test_auto_construct_defaults_to_true_and_can_be_switched_off():
    assert Email.auto_construct is True

    class Manual(TypeModel[str]):
        auto_construct = False
    assert Manual.auto_construct is False
    assert TypeModel[str].auto_construct is True
