"""
``Transform[In, Out]`` (2026-11-13): a type made from a value of another type, by a hook, that holds only
the result. ``TypeModel``'s sibling: a model *is* its value, a ``Transform`` *holds* one of another type.
"""
from typing import Any, Generic, Optional, TypeVar
import copy
import gc
import io
import pickle
import types
import warnings
import weakref

import pytest

import enforced._environment as environment
from enforced import (
    Enforced, InvalidDataError, InvalidDataWarning, Transform, dataclass, dispatch, enforce, make_dataclass, to_json,
    validate, validate_function, validate_record,
    )


class Upper(Transform[str, str]):
    """The hook counts its calls, and refuses in every way a hook can."""

    calls = 0

    @classmethod
    def transform(cls, raw: str) -> str:
        Upper.calls += 1
        if raw == "":
            raise ValueError("must not be empty")
        if raw == "type error":
            raise TypeError("a type error of the hook")
        if raw == "arithmetic":
            raise ZeroDivisionError("an arithmetic error of the hook")
        if raw == "bug":
            raise KeyError("a bug in the hook")
        return raw.upper()


class BufferFile(Transform[str, io.BytesIO]):
    @classmethod
    def transform(cls, raw: str) -> io.BytesIO:
        return io.BytesIO(raw.encode())


class Half(Transform[float, float]):
    @classmethod
    def transform(cls, raw: float) -> float:
        return raw / 2


class Joined(Transform[list[str], str]):
    @classmethod
    def transform(cls, raw: list[str]) -> str:
        return "-".join(raw)


class Broken(Transform[str, int]):
    @classmethod
    def transform(cls, raw: str) -> int:
        return raw                                                  # type: ignore[return-value]  # the bug under test


class ShopError(InvalidDataError):
    pass


class ShopWarning(InvalidDataWarning):
    pass


@pytest.fixture(params = [1, 10 ** 6], ids = ["compiled", "general path"])
def tier(request, monkeypatch):
    monkeypatch.setattr(environment, "COMPILE_AFTER", request.param)
    return request.param


def _raised(call: Any, kind: type[BaseException] = InvalidDataError) -> Any:
    try:
        call()
    except kind as e:
        return e
    raise AssertionError("nothing was raised")


def _twice(call: Any, kind: type[BaseException] = InvalidDataError) -> Any:
    """The error of ``call`` on the second try (the first may compile the wrapper)."""
    _raised(call, kind)
    return _raised(call, kind)


def _line(error: BaseException) -> str:
    """The one problem of a message, without its head line."""
    return str(error).splitlines()[-1].strip().removeprefix("-> ")


# ── the class ────────────────────────────────────────────────────────────────

def test_it_is_made_of_a_raw_value_and_holds_the_result():
    made = BufferFile("abc")
    assert type(made) is BufferFile and made.value.getvalue() == b"abc"
    assert BufferFile.__input_type__ is str and BufferFile.__output_type__ is io.BytesIO
    assert Upper("abc").value == "ABC"


def test_an_instance_passes_through():
    made = Upper("abc")
    before = Upper.calls
    assert Upper(made) is made and Upper.calls == before


def test_it_is_frozen_and_its_value_may_still_change():
    made = BufferFile("abc")
    with pytest.raises(AttributeError, match = "BufferFile is frozen"):
        made.value = io.BytesIO()                                   # type: ignore[misc]
    with pytest.raises(AttributeError, match = "BufferFile is frozen"):
        del made.value
    with pytest.raises(AttributeError):
        made.other = 1                                              # type: ignore[attr-defined]
    made.value.write(b"def")                                        # the attribute is frozen, not what it holds
    assert made.value.getvalue() == b"def"


def test_repr_equality_and_hashing():
    assert repr(Upper("abc")) == "Upper('ABC')"
    assert repr(BufferFile("abc")).startswith("BufferFile(<_io.BytesIO object at ")
    assert Upper("abc") == Upper("ABC") and Upper("abc") != Upper("abd") and Upper("abc") != "ABC"

    class Other(Transform[str, str]):
        @classmethod
        def transform(cls, raw: str) -> str:
            return raw.upper()

    assert Other("abc") != Upper("abc")                             # the class counts
    assert hash(Upper("abc")) == hash(Upper("ABC")) and len({Upper("a"), Upper("A"), Other("a")}) == 2
    with pytest.raises(TypeError):
        hash(_Unhashable([1]))


class _Unhashable(Transform[list[int], list[int]]):
    @classmethod
    def transform(cls, raw: list[int]) -> list[int]:
        return raw


def test_copying_and_pickling_keep_the_value_and_never_run_the_hook():
    made = Upper("abc")
    before = Upper.calls
    assert copy.copy(made) is made
    deep = copy.deepcopy(made)
    assert deep == made and deep is not made
    held = _Unhashable([1, 2])
    assert copy.deepcopy(held).value == [1, 2] and copy.deepcopy(held).value is not held.value
    for protocol in range(2, pickle.HIGHEST_PROTOCOL + 1):
        back = pickle.loads(pickle.dumps(made, protocol))
        assert type(back) is Upper and back == made
    assert Upper.calls == before


def test_what_is_unpickled_is_checked_against_out():
    from enforced._validator._transform import _restore
    assert _restore(Upper, "kept as it is").value == "kept as it is"
    with pytest.raises(TypeError, match = r"Upper holds str, got int \(Value: 5\)"):
        _restore(Upper, 5)


def test_a_generic_base_is_filled_in_by_the_class_that_uses_it():
    T = TypeVar("T")

    class Parsed(Transform[str, T]):
        pass

    class Number(Parsed[int]):
        @classmethod
        def transform(cls, raw: str) -> int:
            return int(raw)

    class Numbers(Parsed[list[int]]):
        @classmethod
        def transform(cls, raw: str) -> list[int]:
            return [int(n) for n in raw.split()]

    class Small(Number):                                            # below a class that is complete
        pass

    assert (Number.__input_type__, Number.__output_type__) == (str, int)
    assert Numbers.__output_type__ == list[int] and Small.__output_type__ is int
    assert Number("4").value == 4 and Numbers("1 2").value == [1, 2] and type(Small("3")) is Small
    with pytest.raises(TypeError, match = "Parsed is still generic"):
        Parsed("4")
    with pytest.raises(TypeError, match = "Transform is still generic"):
        Transform("4")

    @validate
    def take(n: Number) -> int:
        return n.value

    assert take("12") == 12


def test_a_side_may_name_a_class_that_comes_later():
    class Wrapped(Transform["_Later", "list[_Later]"]):
        @classmethod
        def transform(cls, raw: "_Later") -> "list[_Later]":
            return [raw]

    one = _Later()
    assert Wrapped(one).value == [one]
    with pytest.raises(TypeError, match = "Wrapped expects _Later, got int"):
        Wrapped(3)


class _Later:
    pass


def test_a_name_that_is_nowhere_is_said_at_the_first_use():
    class Lost(Transform["Nowhere", int]):                          # type: ignore[name-defined]  # noqa: F821
        @classmethod
        def transform(cls, raw: Any) -> int:
            return 1

    with pytest.raises(TypeError, match = "Lost: In can't be read"):
        Lost(1)


# ── what a class statement refuses ──────────────────────────────────────────

def test_a_class_without_its_types_is_refused():
    with pytest.raises(TypeError, match = r"X must subclass Transform\[In, Out\]"):
        class X(Transform):                                         # type: ignore[type-arg]
            pass


def test_a_class_without_a_hook_is_refused():
    with pytest.raises(TypeError, match = "X must define transform, the class method that makes int of str"):
        class X(Transform[str, int]):
            pass


def test_a_hook_that_is_no_class_method_is_refused():
    with pytest.raises(TypeError, match = "X.transform must be a class method"):
        class X(Transform[str, int]):
            def transform(self, raw: str) -> int:                   # type: ignore[override]
                return 1


@pytest.mark.parametrize("name", ["__new__", "__init__"])
def test_a_constructor_of_its_own_is_refused(name):
    with pytest.raises(TypeError, match = "put the work in the transform classmethod"):
        types.new_class("X", (Transform[str, int],), exec_body = lambda ns: ns.update(
            {name: lambda *a: None, "transform": classmethod(lambda cls, raw: 1)}))


@pytest.mark.parametrize("sides, said", [((5, int), "In is 5"), ((str, 5), "Out is 5")])
def test_a_side_that_is_no_type_is_refused(sides, said):
    with pytest.raises(TypeError, match = f"X: {said}, which is no type to check a value against"):
        types.new_class("X", (Transform[sides],), exec_body = lambda ns: ns.update(transform = classmethod(lambda cls, raw: 1)))


# ── both sides, made directly ───────────────────────────────────────────────

def test_a_raw_value_of_the_wrong_type_is_a_type_error_when_made_directly():
    with pytest.raises(TypeError, match = r"Upper expects str, got int \(Value: 5\)") as caught:
        Upper(5)                                                    # type: ignore[arg-type]
    assert not isinstance(caught.value, InvalidDataError)           # as a TypeModel's


def test_in_is_checked_with_its_items():
    assert Joined(["a", "b"]).value == "a-b"
    with pytest.raises(TypeError, match = r"Joined expects list\[str\], got list"):
        Joined(["a", 1])                                            # type: ignore[list-item]

    @validate                                                       # not deep: the class's own sides are
    def join(j: Joined) -> str:
        return j.value

    assert join(["a", "b"]) == "a-b"
    assert "expected type: " in _line(_twice(lambda: join(["a", 1])))


def test_the_refusal_of_a_hook_is_its_own_when_made_directly():
    with pytest.raises(ValueError, match = "must not be empty"):
        Upper("")
    with pytest.raises(KeyError):
        Upper("bug")


def test_a_hook_that_returns_no_out_is_a_loud_type_error():
    error = _raised(lambda: Broken("x"), TypeError)
    assert type(error).__name__ == "TypeError" and type(error).__module__ == "builtins"
    assert not isinstance(error, InvalidDataError)
    assert str(error) == "Broken.transform must return int, not str (Value: 'x')"


# ── in a checked call ───────────────────────────────────────────────────────

def test_a_raw_value_is_transformed_and_an_instance_passes(tier):
    @validate
    def shout(text: Upper, twice: bool = False) -> str:
        assert type(text) is Upper
        return text.value * (2 if twice else 1)

    made = Upper("kept")
    for _ in range(3):
        Upper.calls = 0
        assert shout("abc") == "ABC" and Upper.calls == 1           # once per transformed value
        assert shout(made, twice = True) == "KEPTKEPT" and shout(text = "kw") == "KW"
        assert Upper.calls == 2


def test_the_wording_of_each_refusal(tier):
    @validate
    def shout(text: Upper) -> str:
        return text.value

    @validate
    def either(text: int | Upper | None) -> Any:
        return text

    name = f"{__name__}.Upper"
    assert _line(_twice(lambda: shout(5))) == (
        f"For parameter text of <Function shout>: expected type: '{name}' | 'str', got type 'int' (Value: 5)")
    assert _line(_twice(lambda: shout(""))) == "For parameter text of <Function shout>: invalid 'Upper': must not be empty (Value: '')"
    assert _line(_twice(lambda: either(1.5))) == (
        "For parameter text of <Function either>: expected type: 'int' | 'Upper' | 'NoneType' | 'str', got type 'float' (Value: 1.5)")
    assert _line(_twice(lambda: either(""))) == "For parameter text of <Function either>: invalid 'Upper': must not be empty (Value: '')"

    @validate
    def named_already(text: Upper | str | list[str]) -> Any:
        return text

    assert "expected type: 'Upper' | 'str' | 'list', got type 'int'" in _line(_twice(lambda: named_already(5)))


def test_errors_carry_the_reason_and_the_place(tier):
    @validate
    def shout(text: Upper) -> str:
        return text.value

    refused = _twice(lambda: shout(""))
    (problem,) = refused.problems
    assert (problem.kind, problem.parameter, problem.detail, problem.value) == ("invalid", "text", "must not be empty", "")
    (entry,) = refused.errors()
    assert entry["type"] == "invalid" and entry["loc"] == ["text"] and "must not be empty" in entry["msg"]
    (problem,) = _twice(lambda: shout(5)).problems
    assert (problem.kind, problem.detail) == ("type", None)


def test_the_hook_runs_once_for_a_value_it_refuses(tier):
    @validate
    def shout(text: Upper) -> str:
        return text.value

    _raised(lambda: shout(""))
    Upper.calls = 0
    _raised(lambda: shout(""))
    assert Upper.calls == 1


def test_a_type_error_or_an_arithmetic_error_of_the_hook_is_a_refusal_that_names_it(tier):
    #* The value was an In, so a plain wrong type would read "expected ... | 'str', got type 'str'".
    @validate
    def shout(text: Upper) -> str:
        return text.value

    @validate(deep = True)
    def all_of(texts: list[Upper | None]) -> Any:
        return texts

    for raw, reason in (("type error", "TypeError: a type error of the hook"),
                        ("arithmetic", "ZeroDivisionError: an arithmetic error of the hook")):
        Upper.calls = 0
        (problem,) = _twice(lambda: shout(raw)).problems
        assert (problem.kind, problem.detail, problem.value) == ("invalid", reason, raw) and Upper.calls == 2
        assert reason in str(_twice(lambda: all_of([None, raw])))


def test_another_exception_of_the_hook_is_a_bug_and_propagates(tier):
    @validate
    def shout(text: Upper) -> str:
        return text.value

    for _ in range(2):
        with pytest.raises(KeyError, match = "a bug in the hook"):
            shout("bug")


def _broken_everywhere() -> list[tuple[str, Any]]:
    @validate
    def plain(b: Broken) -> Any: return b

    @validate
    def default(b: Broken = "x") -> Any: return b                   # type: ignore[assignment]

    @validate
    def optional(b: Broken | None) -> Any: return b

    @validate
    def union(b: int | Broken) -> Any: return b

    @validate(deep = True)
    def items(b: list[Broken]) -> Any: return b

    @validate(deep = True)
    def mapping(b: dict[str, Broken]) -> Any: return b

    @validate(deep = True)
    def pair(b: tuple[int, Broken]) -> Any: return b

    @validate(coerce = True)
    def coerced(b: Broken) -> Any: return b

    @validate(on_error = "warn")
    def warned(b: Broken) -> Any: return b

    @validate(check_return = True)
    def returned(x: Any) -> Broken: return x

    @dataclass
    class Field:
        b: Broken

    @dataclass(deep = True)
    class Fields:
        b: list[Broken]

    @dataclass(frozen = True)
    class Frozen:
        b: Broken

    @enforce
    class Plain:
        b: Broken

        def __init__(self, b: Any) -> None:
            self.b = b

        def method(self, b: Broken) -> Any:
            return b

    def assign(cls: Any) -> Any:
        one = object.__new__(cls)
        one.b = "x"

    @dispatch
    def chosen(x: Any, b: Broken) -> Any: return b

    return [
        ("a parameter", lambda: plain("x")), ("a default", default), ("an optional", lambda: optional("x")),
        ("a union", lambda: union("x")), ("deep items", lambda: items(["x"])), ("deep values", lambda: mapping({"a": "x"})),
        ("a deep tuple", lambda: pair((1, "x"))), ("coerce", lambda: coerced("x")), ("on_error = warn", lambda: warned("x")),
        ("a return value", lambda: returned("x")), ("a dataclass", lambda: Field("x")), ("a deep dataclass", lambda: Fields(["x"])),
        ("a frozen dataclass", lambda: Frozen("x")), ("an attribute", lambda: Plain("x")),
        ("a method", lambda: object.__new__(Plain).method("x")), ("a field assignment", lambda: assign(Field)),
        ("an attribute assignment", lambda: assign(Plain)), ("validate_function", lambda: validate_function(plain, ("x",))),
        ("validate_record", lambda: validate_record({"object_name": "f", "record": {"b": Broken}, "args": ("x",), "kwargs": {}})),
        ("a dispatched version", lambda: chosen(1, "x")),
        ]


@pytest.mark.parametrize("place", range(20))
def test_a_broken_hook_is_loud_wherever_it_is_met(tier, place):
    label, call = _broken_everywhere()[place]
    for _ in range(3):                                              # before and after the wrapper is compiled
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            error = _raised(call, TypeError)
        assert not isinstance(error, InvalidDataError), label
        assert str(error) == "Broken.transform must return int, not str (Value: 'x')", label


# ── every place ─────────────────────────────────────────────────────────────

def test_items_are_transformed_into_a_new_container(tier):
    @validate(deep = True)
    def all_of(texts: list[Upper], by_name: dict[str, Upper] | None = None) -> Any:
        return texts, by_name

    given = ["a", Upper("b")]
    for _ in range(2):
        texts, by_name = all_of(given, {"k": "v"})
        assert [t.value for t in texts] == ["A", "B"] and texts[1] is given[1] and given[0] == "a"
        assert by_name == {"k": Upper("v")}
    assert "invalid 'Upper': must not be empty" in str(_twice(lambda: all_of(["a", ""])))
    assert _twice(lambda: all_of(["a", ""])).errors()[0]["loc"] == ["texts", 1]
    assert "got type 'int'" in str(_twice(lambda: all_of(["a", 5])))


def test_optional_and_a_union_in_its_declared_order(tier):
    @validate
    def maybe(text: Optional[Upper] = None) -> Any:
        return text

    @validate
    def number_first(x: float | Half) -> Any:
        return x

    @validate
    def half_first(x: Half | float) -> Any:
        return x

    @validate
    def text_or_file(x: Upper | BufferFile) -> Any:
        return x

    for _ in range(2):
        assert maybe() is None and maybe(None) is None and maybe("a") == Upper("a")
        assert number_first(3) == 3.0 and type(number_first(3)) is float
        assert half_first(3) == Half(3.0) and half_first(2.5) == 2.5        # a float passes before anything converts
        assert type(text_or_file("a")) is Upper and type(text_or_file(BufferFile("a"))) is BufferFile


def test_a_return_value_is_transformed(tier):
    @validate(check_return = True)
    def make(raw: Any) -> Upper:
        return raw

    for _ in range(2):
        assert make("a") == Upper("a") and make(Upper("b")).value == "B"
    assert _line(_twice(lambda: make(5))).startswith("For return value of <Function make>: expected type: ")
    assert "invalid 'Upper': must not be empty" in _line(_twice(lambda: make("")))


def test_a_default_is_transformed_once(tier):
    @validate
    def shout(text: Upper = "quiet") -> Upper:                      # type: ignore[assignment]
        return text

    Upper.calls = 0
    assert shout().value == "QUIET" and shout() is shout() and Upper.calls == 1

    @validate
    def wrong(text: Upper = "") -> Upper:                           # type: ignore[assignment]
        return text

    assert "For default value of parameter text" in str(_raised(wrong)) and "must not be empty" in str(_raised(wrong))


def test_a_dataclass_field_and_its_assignment(tier):
    @dataclass
    class Job:
        name: Upper
        size: Half = 2                                              # type: ignore[assignment]

    for _ in range(2):
        job = Job("build")
        assert job.name == Upper("build") and job.size == Half(2.0)
        job.name = "test"                                           # type: ignore[assignment]
        assert job.name.value == "TEST"
        made = Upper("kept")
        job.name = made
        assert job.name is made
    assert "invalid 'Upper': must not be empty" in str(_twice(lambda: Job("")))
    said = str(_twice(lambda: setattr(job, "name", 5)))
    assert f"Field Job.name of <Dataclass Job>: expected type: '{__name__}.Upper' | 'str', got type 'int' (Value: 5)" in said
    assert "Field Job.name of <Dataclass Job>: invalid 'Upper': must not be empty" in str(_twice(lambda: setattr(job, "name", "")))

    @dataclass(frozen = True, slots = True)
    class Fixed:
        name: Upper

    assert Fixed("a").name == Upper("a") and Fixed("a") == Fixed(Upper("A"))


def test_enforce_a_method_and_an_attribute(tier):
    @enforce
    class Speaker:
        last: Upper

        def __init__(self, first: Upper) -> None:
            self.last = first

        def say(self, text: Upper) -> str:
            self.last = text
            return text.value

    for _ in range(2):
        speaker = Speaker("hello")
        assert speaker.last == Upper("hello") and speaker.say("again") == "AGAIN"
        speaker.last = "set"                                        # type: ignore[assignment]
        assert speaker.last == Upper("set")
    assert "invalid 'Upper': must not be empty" in str(_twice(lambda: speaker.say("")))
    said = str(_twice(lambda: setattr(speaker, "last", 5)))
    assert f"Attribute Speaker.last of <Class Speaker>: expected type: '{__name__}.Upper' | 'str', got type 'int'" in said


def test_an_enforced_base_and_a_made_dataclass(tier):
    class Speaker(Enforced):
        last: Upper

        def say(self, text: Upper) -> str:
            self.last = text
            return text.value

    Made = make_dataclass("Made", [("name", Upper)])
    for _ in range(2):
        speaker = Speaker()
        assert speaker.say("a") == "A" and speaker.last == Upper("a")
        speaker.last = "b"                                          # type: ignore[assignment]
        assert speaker.last == Upper("b") and Made("x").name == Upper("x")
    assert "must not be empty" in str(_twice(lambda: speaker.say(""))) and "must not be empty" in str(_twice(lambda: Made("")))


def test_without_a_decorator(tier):
    def shout(text: Upper) -> str:
        return text.value

    spec = {"object_name": "shout", "record": {"text": Upper}, "args": ("abc",), "kwargs": {}}
    for _ in range(2):
        assert validate_function(shout, ("abc",)) == "ABC"
        assert validate_record(spec) == ((Upper("abc"),), {})
    assert "must not be empty" in str(_twice(lambda: validate_function(shout, ("",))))
    assert "must not be empty" in str(_twice(lambda: validate_record({**spec, "args": ("",)})))
    assert "'str', got type 'int'" in str(_twice(lambda: validate_record({**spec, "args": (5,)})))


def test_a_warning_lets_the_value_through_as_it_was_given(tier):
    @validate(on_error = "warn", warning = ShopWarning)
    def shout(text: Upper) -> Any:
        return text

    for raw in ("", 5):
        for _ in range(2):
            with warnings.catch_warnings(record = True) as caught:
                warnings.simplefilter("always")
                assert shout(raw) == raw                            # type: ignore[arg-type]
            (warning,) = caught
            assert warning.category is ShopWarning
    assert "must not be empty" in str(caught[0].message) or "got type 'int'" in str(caught[0].message)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert shout("fine") == Upper("fine")


def test_the_error_is_of_the_class_given(tier):
    @validate(error = ShopError)
    def shout(text: Upper) -> str:
        return text.value

    assert type(_twice(lambda: shout(""))) is ShopError and type(_twice(lambda: shout(5))) is ShopError


# ── the options ─────────────────────────────────────────────────────────────

def test_without_convert_only_an_instance_is_taken(tier):
    @validate(convert = False)
    def shout(text: Upper, other: Upper | None = None) -> str:
        return text.value

    @dataclass(convert = False)
    class Job:
        name: Upper

    made = Upper("abc")
    for _ in range(2):
        assert shout(made) == "ABC" and Job(made).name is made
    error = _twice(lambda: shout("abc"))
    assert _line(error) == f"For parameter text of <Function shout>: expected type: '{__name__}.Upper', got type 'str' (Value: 'abc')"
    assert error.problems[0].detail == "instances only"
    assert "'str'" not in _line(_twice(lambda: shout(made, 5))).split("got type")[0]
    job = Job(made)
    said = _line(_twice(lambda: setattr(job, "name", "abc")))
    assert said == f"Field Job.name of <Dataclass Job>: expected type: '{__name__}.Upper', got type 'str' (Value: 'abc')"


def test_coerce_makes_an_in_of_the_raw_value_first(tier):
    @validate(coerce = True)
    def halve(x: Half) -> float:
        return x.value

    @validate
    def strict(x: Half) -> float:
        return x.value

    for _ in range(2):
        assert halve("3") == 1.5 and halve(3) == 1.5 and halve(3.0) == 1.5
        assert strict(3) == 1.5                                     # the numeric tower, under convert
    assert "got type 'str'" in str(_twice(lambda: strict("3")))
    assert "got type 'bool'" in str(_twice(lambda: strict(True)))       # a bool is no number
    assert "got type 'str'" in str(_twice(lambda: halve("three")))


def test_a_class_may_refuse_to_be_made_by_the_checker(tier):
    class Explicit(Transform[str, str]):
        auto_construct = False

        @classmethod
        def transform(cls, raw: str) -> str:
            return raw

    @validate
    def take(x: Explicit) -> str:
        return x.value

    assert take(Explicit("a")) == "a"
    said = _line(_twice(lambda: take("a")))
    assert said.endswith("expected type: 'Explicit', got type 'str' (Value: 'a')") or "Explicit', got type 'str'" in said
    assert "| 'str'" not in said


# ── dispatch, to_json ───────────────────────────────────────────────────────

def test_dispatch_chooses_by_instance_only():
    @dispatch
    def kind(x: Any) -> str:
        return "base"

    @kind.register
    def _(x: Upper) -> str:
        return "upper"

    @kind.register
    def _(x: list[BufferFile]) -> str:
        return "files"

    before = Upper.calls
    assert kind(Upper("a")) == "upper" and kind("a") == "base" and kind([BufferFile("a")]) == "files" and kind(["a"]) == "base"
    assert Upper.calls == before + 1                                # the hook is never run to choose a version

    @dispatch
    def only(x: Upper) -> str:
        return x.value

    assert only(Upper("a")) == "A"
    said = str(_raised(lambda: only("a")))
    assert f"expected type: '{__name__}.Upper', got type 'str'" in said and "| 'str'" not in said


def test_the_other_parameters_of_a_version_are_transformed():
    @dispatch
    def send(kind: Any, text: Upper) -> str:
        return "base " + text.value

    @send.register
    def _(kind: int, text: Upper) -> str:
        return "int " + text.value

    assert send("k", "a") == "base A" and send(1, "a") == "int A"
    assert "must not be empty" in str(_raised(lambda: send(1, "")))


def test_to_json_writes_the_value():
    assert to_json(Upper("a")) == '"A"'
    assert to_json({"names": [Upper("a"), Joined(["b", "c"])]}) == '{"names": ["A", "b-c"]}'
    with pytest.raises(TypeError, match = "BytesIO"):
        to_json({"file": BufferFile("a")})


# ── nothing is kept alive ───────────────────────────────────────────────────

@pytest.mark.parametrize("options", [{}, {"deep": True}, {"coerce": True}], ids = str)
def test_a_class_made_at_run_time_goes_when_it_is_dropped(options):
    def use(i: int) -> type:
        class Held:
            pass

        class Local(Transform[int, Held]):
            @classmethod
            def transform(cls, raw: int) -> Held:
                if raw < 0:
                    raise ValueError("negative")
                return Held()

        @validate(**options)
        def take(x: Local, xs: list[Local] | None = None, y: Local | None = None) -> Any:
            return x

        @dataclass(**options)
        class Row:
            x: Local

        for _ in range(3):
            assert type(take(1, [2, Local(3)], 4)) is Local and type(Row(1).x) is Local
            for wrong in ("a", -1):
                for call in (lambda: take(wrong), lambda: Row(wrong), lambda: take(1, [wrong])):
                    try:
                        call()
                    except InvalidDataError as e:
                        str(e)
        assert pickle.loads is not None and copy.deepcopy(Local(1)) is not None
        return Local

    alive = []
    for i in range(40):
        made = use(i)
        alive.append(weakref.ref(made))
        del made
    for _ in range(3):
        gc.collect()
    assert sum(ref() is not None for ref in alive) == 0


def test_generic_alias_of_the_class_is_not_needed():
    #* ``Generic`` is in the bases for a type checker; at run time a class is used as it is.
    assert Generic in Transform.__mro__ and Transform.__parameters__ == (Transform.__input_type__, Transform.__output_type__)
