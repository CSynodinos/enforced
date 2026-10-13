"""How the checker handles TypeModel classes and Annotated[T, check] annotations."""
from typing import Annotated, Literal, Optional
import pickle
import re

import pytest

from enforced import Check, typecheck, typecheck_record, dataclass, TypeCheckerError
from enforced._typechecker._type_data_model import TypeModel
from enforced._typechecker._type_container import describe_check
import enforced._typechecker.api as api


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _error(fn, *args, **kwargs) -> TypeCheckerError:
    with pytest.raises(TypeCheckerError) as info:
        fn(*args, **kwargs)
    return info.value


def _message(fn, *args, **kwargs) -> str:
    return _plain(str(_error(fn, *args, **kwargs)))


class Slug(TypeModel[str]):
    @classmethod
    def validate(cls, raw):
        raw = raw.strip().lower()
        if not raw or not re.fullmatch(r"[a-z0-9-]+", raw):
            raise ValueError("only letters, digits and '-'")
        return raw


class Percent(TypeModel[float]):
    @classmethod
    def validate(cls, raw):
        if not 0 <= raw <= 100:
            raise ValueError("must be between 0 and 100")
        return raw


class Manual(TypeModel[str]):
    auto_construct = False


def is_even(v):
    return v % 2 == 0


def must_be_short(v):
    if len(v) > 3:
        raise ValueError("at most 3 characters")
    return True


Even = Annotated[int, is_even]
Short = Annotated[str, must_be_short]
Small = Annotated[int, lambda v: v < 10]
Range = Annotated[int, lambda v: v > 0, lambda v: v < 100]
ShortList = Annotated[list[int], lambda xs: len(xs) <= 2]


# ── TypeModel: conversion ────────────────────────────────────────────────────

def test_model_built_from_raw_value_under_default_convert():
    @typecheck
    def f(s: Slug):
        return s
    out = f("  Hello-World ")
    assert type(out) is Slug and out == "hello-world"


def test_model_not_built_with_convert_off():
    @typecheck(convert = False)
    def f(s: Slug):
        return s
    assert f(Slug("ok")) == "ok"
    msg = _message(f, "ok")
    assert "expected type: " in msg and "got type 'str'" in msg and "invalid" not in msg


def test_auto_construct_false_only_accepts_instances():
    @typecheck
    def f(m: Manual):
        return m
    assert type(f(Manual("x"))) is Manual
    assert "got type 'str'" in _message(f, "x")


def test_model_uses_the_numeric_tower_for_its_base():
    @typecheck
    def f(p: Percent):
        return p
    out = f(50)
    assert type(out) is Percent and out == 50.0
    assert "invalid 'Percent': must be between 0 and 100 (Value: 150)" in _message(f, 150)


def test_model_coerces_its_base_first_with_coerce():
    @typecheck(coerce = True)
    def f(p: Percent):
        return p
    assert type(f("12.5")) is Percent
    assert "invalid 'Percent'" in _message(f, "120")


def test_model_in_strict_mode():
    @typecheck(allow_subclass = False)
    def f(s: Slug):
        return s
    assert type(f("abc")) is Slug                       # the conversion result is exactly a Slug


def test_model_subclass_instance_in_strict_mode_is_rejected():
    class SubSlug(Slug):
        pass

    @typecheck(allow_subclass = False)
    def f(s: Slug):
        return s
    msg = _message(f, SubSlug("abc"))
    assert "got type" in msg


def test_optional_model():
    @typecheck
    def f(s: Slug | None = None):
        return s
    assert f() is None and f(None) is None
    assert type(f("abc")) is Slug
    assert "invalid 'Slug'" in _message(f, "a b")


def test_model_in_union_with_other_types():
    @typecheck
    def f(v: Slug | int):
        return v
    assert f(3) == 3 and type(f(3)) is int
    assert type(f("abc")) is Slug
    msg = _message(f, "a b")
    assert "invalid 'Slug': only letters, digits and '-'" in msg


def test_two_models_in_a_union_first_that_accepts_wins():
    class Upper(TypeModel[str]):
        @classmethod
        def validate(cls, raw):
            if not raw.isupper():
                raise ValueError("must be upper case")
            return raw

    @typecheck
    def f(v: Upper | Slug):
        return v
    assert type(f("ABC")) is Upper
    assert type(f("abc")) is Slug
    assert "invalid 'Upper': must be upper case" in _message(f, "a b")


def test_model_default_is_converted():
    @typecheck
    def f(s: Slug = "Default"):
        return s
    assert type(f()) is Slug and f() == "default"


def test_invalid_model_default_is_a_definition_error():
    with pytest.raises(TypeCheckerError) as info:
        @typecheck
        def f(s: Slug = "not ok"):
            return s
        f()
    msg = _plain(str(info.value))
    assert "in definition" in msg
    assert "For default value of parameter s" in msg and "invalid 'Slug'" in msg


def test_model_return_value():
    @typecheck(check_return = True)
    def f(raw: str) -> Slug:
        return raw
    assert type(f("ABC")) is Slug
    assert "For return value of <Function f>: invalid 'Slug'" in _message(f, "a b")


def test_model_in_varargs_and_kwargs():
    @typecheck
    def f(*slugs: Slug, **named: Slug):
        return slugs, named
    slugs, named = f("a", "B", key = "C")
    assert all(type(s) is Slug for s in slugs) and type(named["key"]) is Slug
    msg = _message(f, "ok", "no way")
    assert "For parameter slugs[1] of <Function f>: invalid 'Slug'" in msg


def test_model_items_with_deep():
    @typecheck(deep = True)
    def f(tags: list[Slug], by_name: dict[str, Slug]):
        return tags, by_name
    tags, by_name = f(["A", Slug("b")], {"x": "C"})
    assert [type(t) for t in tags] == [Slug, Slug] and type(by_name["x"]) is Slug
    msg = _message(f, ["ok", "not ok"], {"x": "y y"})
    assert "For introspected parameter tags at index [1] of <Function f>: invalid 'Slug'" in msg
    assert "For introspected parameter by_name at index ['x'] of <Function f>: invalid 'Slug'" in msg


def test_model_items_without_deep_are_not_built():
    @typecheck
    def f(tags: list[Slug]):
        return tags
    assert f(["NOT VALIDATED"]) == ["NOT VALIDATED"]   # items aren't looked at without deep


def test_model_dataclass_construction_and_assignment():
    @dataclass
    class Page:
        slug: Slug
        score: Percent = 0

    p = Page("Hello")
    assert type(p.slug) is Slug and type(p.score) is Percent
    p.slug = "World"
    assert p.slug == "world" and type(p.slug) is Slug
    with pytest.raises(TypeCheckerError) as info:
        p.slug = "a b"
    msg = _plain(str(info.value))
    assert "1 problem found in field assignment" in msg
    assert "Field Page.slug of <Dataclass Page>: invalid 'Slug': only letters, digits and '-' (Value: 'a b')" in msg
    assert p.slug == "world"                            # unchanged after the failed assignment


def test_model_frozen_dataclass():
    @dataclass(frozen = True)
    class Tag:
        name: Slug

    assert type(Tag("ABC").name) is Slug
    assert "invalid 'Slug'" in _message(Tag, "a b")


def test_bug_in_validate_is_not_hidden():
    class Buggy(TypeModel[str]):
        @classmethod
        def validate(cls, raw):
            raise RuntimeError("bug")

    @typecheck
    def f(b: Buggy):
        return b
    with pytest.raises(RuntimeError, match = "bug"):
        f("x")


# ── Annotated checks ─────────────────────────────────────────────────────────

def test_annotated_check_passes_and_fails():
    @typecheck
    def f(n: Even):
        return n
    assert f(4) == 4
    assert "For parameter n of <Function f>: invalid 'int': failed check is_even (Value: 3)" in _message(f, 3)


def test_annotated_lambda_is_shown_by_its_source():
    @typecheck
    def f(n: Small):
        return n
    assert "failed check v < 10 (Value: 11)" in _message(f, 11)


def test_annotated_check_reason_from_value_error():
    @typecheck
    def f(s: Short):
        return s
    assert f("abc") == "abc"
    assert "invalid 'str': at most 3 characters (Value: 'abcd')" in _message(f, "abcd")


def test_annotated_several_checks_first_failure_reported():
    @typecheck
    def f(n: Range):
        return n
    assert f(50) == 50
    assert "failed check v > 0" in _message(f, 0)
    assert "failed check v < 100" in _message(f, 100)


def test_annotated_type_is_checked_before_the_check():
    @typecheck
    def f(n: Even):
        return n
    msg = _message(f, "4")
    assert "expected type: 'int', got type 'str'" in msg     # the check never sees the str
    assert "invalid" not in msg


def test_annotated_check_runs_on_converted_value():
    seen = []

    def record(v):
        seen.append(v)
        return v > 0

    @typecheck
    def f(x: Annotated[float, record]):
        return x
    assert f(2) == 2.0
    assert seen[-1] == 2.0 and type(seen[-1]) is float
    msg = _message(f, -2)
    assert "invalid 'float': failed check record (Value: -2)" in msg


def test_annotated_non_callable_metadata_is_ignored():
    @typecheck
    def f(n: Annotated[int, "a description", 42]):
        return n
    assert f(-1) == -1
    assert "expected type: 'int'" in _message(f, "x")


def test_annotated_class_metadata_is_not_a_check():
    class Marker:
        pass

    @typecheck
    def f(n: Annotated[int, Marker]):
        return n
    assert f(0) == 0


def test_annotated_in_optional():
    @typecheck
    def f(n: Even | None = None):
        return n
    assert f() is None and f(None) is None and f(2) == 2
    assert "failed check is_even" in _message(f, 1)


def test_annotated_checks_apply_only_to_their_own_member():
    @typecheck
    def f(v: Even | str):
        return v
    assert f("anything") == "anything"
    assert f(2) == 2
    assert "failed check is_even" in _message(f, 3)


def test_annotated_with_literal():
    @typecheck
    def f(v: Literal["auto"] | Even):
        return v
    assert f("auto") == "auto" and f(2) == 2
    assert "failed check is_even" in _message(f, 3)
    assert "invalid" not in _message(f, "manual")


def test_annotated_in_strict_mode():
    @typecheck(allow_subclass = False)
    def f(n: Even):
        return n
    assert f(2) == 2
    assert "failed check is_even" in _message(f, 3)


def test_annotated_items_with_deep():
    @typecheck(deep = True)
    def f(xs: list[Even], m: dict[str, Optional[Even]]):
        return xs, m
    assert f([2, 4], {"a": None, "b": 6}) == ([2, 4], {"a": None, "b": 6})
    msg = _message(f, [2, 3, 5], {"a": 1})
    assert msg.startswith("3 problems found in call:")
    assert "For introspected parameter xs at index [1] of <Function f>: invalid 'int': failed check is_even (Value: 3)" in msg
    assert "For introspected parameter m at index ['a']" in msg


@pytest.mark.parametrize("annotation, good, bad", [
    (list[list[Even]], [[2], [4]], [[2], [3]]),
    (dict[str, list[Even]], {"a": [2]}, {"a": [3]}),
    (list[tuple[Even, ...]], [(2, 4)], [(2, 3)]),
    (list[list[list[Even]]], [[[2]], [[4]]], [[[2]], [[4, 3]]]),
    ], ids = ["list[list[Even]]", "dict[str, list[Even]]", "list[tuple[Even, ...]]", "three levels"])
def test_annotated_items_at_every_depth(annotation, good, bad):
    """The check also runs on items one level down (once it never did: 3 passed as an Even in a nested list)."""
    def f(x):
        return x
    f.__annotations__ = {"x": annotation}
    f = typecheck(f, deep = True)
    assert f(good) == good
    assert [(p.kind, p.value) for p in _error(f, bad).problems] == [("invalid", 3)]


def test_every_check_on_a_nested_item_runs():
    """With several checks on one item type, each of them reads the nested items, not only the first."""
    Band = Annotated[int, lambda v: v >= 10, lambda v: v <= 20]

    @typecheck(deep = True)
    def f(m: dict[str, list[Band]]):
        return m
    assert f({"a": [10, 20]}) == {"a": [10, 20]}
    for bad in (5, 25):
        assert [p.value for p in _error(f, {"a": [15], "b": [15, bad]}).problems] == [bad]


def test_annotated_items_at_every_depth_in_a_dataclass():
    @dataclass(deep = True)
    class Grid:
        rows: list[list[Even]]

    assert Grid([[2, 4]]).rows == [[2, 4]]
    with pytest.raises(TypeCheckerError):
        Grid([[2, 3]])


def test_annotated_items_without_deep_are_not_checked():
    @typecheck
    def f(xs: list[Even]):
        return xs
    assert f([1, 3]) == [1, 3]


def test_annotated_on_a_collection_with_deep():
    @typecheck(deep = True)
    def f(xs: ShortList):
        return xs
    assert f([1, 2]) == [1, 2]
    assert "For parameter xs of <Function f>: invalid 'list': failed check len(xs) <= 2" in _message(f, [1, 2, 3])
    msg = _message(f, [1, "a"])                         # the items are checked first
    assert "For introspected parameter xs at index [1]" in msg and "got type 'str'" in msg


def test_annotated_on_a_collection_without_deep():
    @typecheck
    def f(xs: ShortList):
        return xs
    assert f([1, "a"]) == [1, "a"]
    assert "failed check len(xs) <= 2" in _message(f, [1, 2, 3])


def test_annotated_default_is_checked():
    with pytest.raises(TypeCheckerError) as info:
        @typecheck
        def f(n: Even = 3):
            return n
        f()
    msg = _plain(str(info.value))
    assert "For default value of parameter n" in msg and "failed check is_even" in msg


def test_annotated_return_value():
    @typecheck(check_return = True)
    def f(n: int) -> Even:
        return n
    assert f(2) == 2
    assert "For return value of <Function f>: invalid 'int': failed check is_even" in _message(f, 1)


def test_annotated_dataclass_fields():
    @dataclass
    class Box:
        size: Even
        label: Short = "box"

    b = Box(2)
    with pytest.raises(TypeCheckerError) as info:
        b.size = 5
    assert "Field Box.size of <Dataclass Box>: invalid 'int': failed check is_even (Value: 5)" in _plain(str(info.value))
    assert "invalid 'str': at most 3 characters" in _message(Box, 2, "toolong")


def test_check_errors_that_are_no_verdict_propagate():
    def broken(v):
        raise RuntimeError("bug")

    @typecheck
    def f(n: Annotated[int, broken]):
        return n
    with pytest.raises(RuntimeError):
        f(1)

    @typecheck(deep = True)
    def g(ns: list[Annotated[int, lambda v: v.missing]]):
        return ns
    with pytest.raises(AttributeError):
        g([1])


def test_check_raising_a_lookup_error_counts_as_failure():
    #* Review finding 15: ``s[0] == "a"`` on an empty string is a check that says no, by raising
    #* IndexError. It used to escape as it was.
    @typecheck
    def f(s: Annotated[str, lambda s: s[0] == "a"], d: Annotated[dict, lambda d: d["k"] > 0] = {"k": 1}):
        return s
    assert f("abc") == "abc"
    assert "invalid 'str': string index out of range" in _message(f, "")
    assert "invalid 'dict'" in _message(f, "a", {})                 # KeyError: 'k'
    assert "invalid 'str'" in _message(f, "b")                      # an ordinary rejection still reads the same

    @typecheck(deep = True)
    def g(words: list[Annotated[str, lambda s: s[0] == "a"]]):
        return words
    assert g(["ab", "a"]) == ["ab", "a"]
    with pytest.raises(TypeCheckerError) as exc:
        g(["ab", ""])
    assert exc.value.problems[0].parameter == "words[1]" and exc.value.problems[0].kind == "invalid"


def test_check_raising_type_error_counts_as_failure():
    @typecheck
    def f(n: Annotated[int, lambda v: v / 0 > 1]):
        return n
    assert "division by zero" in _message(f, 1)


# ── messages and problems ────────────────────────────────────────────────────

def test_invalid_problem_data():
    @typecheck
    def f(s: Slug, n: Even):
        return s, n
    error = _error(f, "a b", 3)
    first, second = error.problems
    assert (first.kind, first.parameter, first.expected, first.value) == ("invalid", "s", Slug, "a b")
    assert first.detail == "only letters, digits and '-'"
    assert (second.kind, second.parameter, second.expected, second.value) == ("invalid", "n", int, 3)
    assert second.detail == "failed check is_even"


def test_invalid_errors_pickle():
    @typecheck
    def f(s: Slug):
        return s
    error = _error(f, "a b")
    back = pickle.loads(pickle.dumps(error))
    assert str(back) == str(error)


def test_missing_argument_message_shows_the_check():
    @typecheck
    def f(n: Small, m: Annotated[int, "doc"]):
        return n
    msg = _message(f)
    assert "n (expecting type Annotated[int, v < 10])" in msg
    assert "m (expecting type int)" in msg


def test_describe_check():
    assert describe_check(is_even) == "is_even"
    assert describe_check(lambda v: v > 3 and v < 9) == "v > 3 and v < 9"
    assert describe_check(str.isupper) == "isupper"


# ── Check: the explicit way to write a check (review finding 15) ──────────────────────────────────

def is_small(v: int) -> bool:
    return v < 10


@pytest.mark.parametrize("options", [{}, {"deep": True}, {"allow_subclass": False}, {"coerce": True}], ids = str)
def test_a_marked_check_does_what_the_short_form_does(options):
    def build(*metadata):
        @typecheck(check_return = True, **options)
        def f(n: Annotated[int, *metadata], items: list[Annotated[int, *metadata]] = [1]) -> Annotated[int, *metadata] | None:
            return n
        return f

    short, marked = build(lambda v: v > 0, is_small), build(Check(lambda v: v > 0), Check(is_small))
    for f in (short, marked):
        assert f(5) == 5 and f(5, [1, 2]) == 5
    for args in ((0,), (11,), ("a",), (None,)):
        assert _message(short, *args).replace("<lambda>", "v > 0") == _message(marked, *args).replace("<lambda>", "v > 0")
    assert "failed check v > 0 (Value: 0)" in _message(marked, 0) and "failed check is_small (Value: 11)" in _message(marked, 11)
    assert _error(marked, 0).problems[0].kind == "invalid"
    if options.get("deep"):
        assert [p.parameter for p in _error(marked, 5, [1, 0, 11]).problems] == ["items[1]", "items[2]"]


def test_a_marked_check_and_the_short_form_side_by_side():
    @typecheck
    def f(n: Annotated[int, Check(lambda v: v > 0), is_small, "a note", 5]) -> int:
        return n

    assert f(5) == 5
    assert "failed check v > 0" in _message(f, 0) and "failed check is_small" in _message(f, 11)


def test_a_marked_check_costs_no_call_of_its_own():
    #* What the marker wraps is what the compiled check calls: the marker is not in between.
    calls = []

    class Counting(Check):
        def __call__(self, value):                      # would be seen if the marker were called
            calls.append(value)
            return super().__call__(value)

    @typecheck
    def f(n: Annotated[int, Counting(is_small)]) -> int:
        return n

    assert f(1) == 1 and f(2) == 2 and calls == []
    with pytest.raises(TypeCheckerError):
        f(11)
    assert calls == [] and Counting(is_small)(3) is True and calls == [3]


def test_a_marked_class_is_a_check():
    #* A class in the metadata is taken for metadata (see test_annotated_class_metadata_is_not_a_check).
    #* Marked, it is a check like any callable: bool(value) here.
    @typecheck
    def unmarked(xs: Annotated[list, bool]) -> list:
        return xs

    @typecheck
    def marked(xs: Annotated[list, Check(bool)]) -> list:
        return xs

    assert unmarked([]) == [] and marked([1]) == [1]
    assert "invalid 'list': failed check bool (Value: [])" in _message(marked, [])


def test_check_as_an_object():
    check = Check(is_small)
    assert check(3) is True and check(30) is False and check.check is is_small
    assert repr(check) == "Check(is_small)" and repr(Check(lambda v: v > 3)) == "Check(v > 3)"
    assert Check(check).check is is_small                           # marked twice is marked once
    assert check == Check(is_small) and hash(check) == hash(Check(is_small)) and check != Check(len) and check != is_small
    assert Annotated[int, Check(is_small)] == Annotated[int, Check(is_small)]
    assert pickle.loads(pickle.dumps(check)) == check
    for nothing in (5, "x > 0", None, [is_small]):
        with pytest.raises(TypeError, match = "Check\\(\\) takes the function that checks a value"):
            Check(nothing)                                          # type: ignore[arg-type]


def test_check_in_a_dataclass_and_in_a_record():
    @dataclass
    class Order:
        qty: Annotated[int, Check(lambda q: q > 0)]
        price: Annotated[float, Check(lambda p: p >= 0)] = 0

    order = Order(2, 3)
    assert type(order.price) is float
    with pytest.raises(TypeCheckerError, match = "qty"):
        order.qty = 0
    with pytest.raises(TypeCheckerError, match = "price"):
        Order(1, -1)

    #* A record written anew for every call finds its compiled checker: two markers of one check are equal.
    def call(value):
        return typecheck_record({"object_name": "marked_record", "record": {"n": Annotated[int, Check(is_small)]},
                                    "args": (value,)})

    assert call(1) == ((1,), {})
    size = len(api._RECORD_CACHE)
    assert call(2) == ((2,), {}) and len(api._RECORD_CACHE) == size
    with pytest.raises(TypeCheckerError, match = "is_small"):
        call(11)


def test_the_ready_made_types_check_in_either_form():
    #* Written with the marker or as the bare callable: the same check, and the same message.
    from enforced.data_types import NegativeInt, NonNegativeInt, Number, PositiveInt
    for annotation, good, bad, shown in ((PositiveInt, 1, 0, "x > 0"), (NegativeInt, -1, 0, "x < 0"),
                                         (NonNegativeInt, 0, -1, "x >= 0"), (Number, 1.5, float("nan"), "isfinite")):
        assert callable(annotation.__metadata__[0])

        @typecheck
        def f(x: annotation):                                       # type: ignore[valid-type]
            return x

        assert f(good) == good
        assert f"failed check {shown}" in _message(f, bad)


def test_a_function_that_transforms_shows_what_it_returned():
    #* Every callable in the metadata is asked for a verdict, also one that was meant to change the
    #* value. Its falsy result rejects, as documented, and the reason now says what the result was.
    @typecheck
    def f(s: Annotated[str, str.strip], xs: Annotated[list, len] = [1], n: Annotated[int, Check(abs)] = 1) -> str:
        return s

    assert f(" a ") == " a "                                        # never changed: a check is no conversion
    assert "For parameter s of <Function f>: invalid 'str': failed check strip, which returned '' (Value: '  ')" in _message(f, "  ")
    assert "invalid 'list': failed check len, which returned 0 (Value: [])" in _message(f, "a", [])
    assert "invalid 'int': failed check abs, which returned 0 (Value: 0)" in _message(f, "a", [1], 0)

    #* A check that answers False or None says no more than before.
    @typecheck
    def g(s: Annotated[str, str.isupper], t: Annotated[str, re.compile("a+").fullmatch] = "a") -> str:
        return s

    assert "failed check isupper (Value: 'a')" in _message(g, "a")
    assert "failed check fullmatch (Value: 'b')" in _message(g, "A", "b")
