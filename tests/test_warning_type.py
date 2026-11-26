"""
``warning = ...`` on every API (2026-11-01): a library says which warning ``on_error = "warn"`` issues,
as ``error = ...`` says which error is raised. A subclass of ``InvalidDataWarning``, whose ``__init__``
is never run; without ``on_error = "warn"`` it does nothing.
"""
from typing import Any, Self
import pickle
import warnings

import pytest

import enforced._environment as environment
try:
    import clitint._tint as formatting_tool                      # the colour switches are clitint's state
except ImportError:                                              # no clitint: the tests marked "colours" are skipped
    formatting_tool = None
from enforced import (
    Enforced, InvalidDataError, InvalidDataWarning, dataclass, dispatch, dispatchmethod, enforce, enforce_class,
    make_dataclass, validate, validate_function, validate_record,
    )


class ShopWarning(InvalidDataWarning):
    """A library's own warning: an ``__init__`` enforced must never run, and something of its own."""

    library = "shop"

    def __init__(self, order_id: int, reason: str) -> None:         # pragma: no cover  # never called by enforced
        raise AssertionError("enforced ran the subclass's __init__")


class OtherWarning(InvalidDataWarning):
    pass


class ShopError(InvalidDataError):
    pass


@pytest.fixture(params = [1, 10 ** 6], ids = ["compiled", "general path"])
def tier(request, monkeypatch):
    monkeypatch.setattr(environment, "COMPILE_AFTER", request.param)
    return request.param


def _issued(call: Any) -> list[warnings.WarningMessage]:
    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("always")
        call()
    return seen


def _calls(warning: Any) -> "dict[str, Any]":
    """One wrong use per API and kind of member, each made with ``warning``, made anew for each test."""
    options = {"on_error": "warn", "warning": warning}

    @validate(**options)
    def function(n: int) -> None: ...

    @validate(check_return = True, **options)
    def returning() -> int:
        return "a"                                                  # type: ignore[return-value]

    class WithMethod:
        @validate(**options)
        def method(self, n: int) -> None: ...

    @enforce(**options)
    class Under:
        attribute: int = 0

        def method(self, n: int) -> None: ...

        def itself(self, other: Self | None) -> None: ...

        @property
        def size(self) -> int:
            return 0

        @size.setter
        def size(self, value: int) -> None: ...

    class Plain:
        def method(self, n: int) -> None: ...

    enforce_class(Plain, **options)

    class Base(Enforced, **options):
        attribute: int = 0

        def method(self, n: int) -> None: ...

    class Derived(Base):
        def other(self, n: int) -> None: ...

    @dataclass(**options)
    class Data:
        n: int = 0

        def method(self, n: int) -> None: ...

    Made = make_dataclass("Made", [("n", int)], **options)

    @dispatch(**options)
    def chosen(anchor: object, n: int) -> None: ...

    class Host:
        @dispatchmethod(**options)
        def chosen(self, anchor: object, n: int) -> None: ...

    def target(n: int) -> None: ...

    return {
        "validate": lambda: function("a"),
        "validate, return": returning,
        "validate on a method": lambda: WithMethod().method("a"),
        "enforce, method": lambda: Under().method("a"),
        "enforce, Self": lambda: Under().itself("a"),
        "enforce, attribute": lambda: setattr(Under(), "attribute", "a"),
        "enforce, property": lambda: setattr(Under(), "size", "a"),
        "enforce_class": lambda: Plain().method("a"),
        "Enforced, method": lambda: Base().method("a"),
        "Enforced, attribute": lambda: setattr(Base(), "attribute", "a"),
        "Enforced, handed down": lambda: Derived().other("a"),
        "dataclass, construction": lambda: Data("a"),
        "dataclass, assignment": lambda: setattr(Data(), "n", "a"),
        "dataclass, method": lambda: Data().method("a"),
        "make_dataclass": lambda: Made("a"),
        "dispatch": lambda: chosen(1, "a"),
        "dispatchmethod": lambda: Host().chosen(1, "a"),
        "validate_function": lambda: validate_function(target, ("a",), **options),
        "validate_record": lambda: validate_record({"object_name": "f", "record": {"n": "int"}, "args": ("a",), **options}),
        }


NAMES = list(_calls(InvalidDataWarning))


@pytest.mark.parametrize("name", NAMES)
def test_every_api_issues_the_class_given(name, tier):
    call = _calls(ShopWarning)[name]
    #* Twice: the first may be what compiles the wrapper.
    for _ in range(2):
        seen = _issued(call)
        assert seen and {w.category for w in seen} == {ShopWarning}, name
        warning = seen[0].message
        assert type(warning) is ShopWarning and warning.library == "shop"
        assert str(warning) == str(warning.args[0]) and isinstance(warning.error, InvalidDataError)


@pytest.mark.parametrize("name", NAMES)
def test_without_the_option_it_is_invalid_data_warning_itself(name, tier):
    call = _calls(InvalidDataWarning)[name]
    assert {w.category for w in _issued(call)} == {InvalidDataWarning}


def test_the_default_is_invalid_data_warning_itself():
    @validate(on_error = "warn")
    def f(n: int) -> None: ...

    assert [w.category for w in _issued(lambda: f("a"))] == [InvalidDataWarning]


def test_a_filter_takes_the_class_alone_or_the_base_with_it():
    @validate(on_error = "warn", warning = ShopWarning)
    def f(n: int) -> None: ...

    @validate(on_error = "warn", warning = OtherWarning)
    def g(n: int) -> None: ...

    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("always")
        warnings.simplefilter("ignore", ShopWarning)
        f("a")
        g("a")
    assert [w.category for w in seen] == [OtherWarning]
    with warnings.catch_warnings(record = True) as seen:
        warnings.simplefilter("always")
        warnings.simplefilter("ignore", InvalidDataWarning)
        f("a")
        g("a")
    assert seen == []


def test_a_filter_turns_it_into_an_exception_of_the_class():
    @validate(on_error = "warn", warning = OtherWarning)
    def f(n: int) -> None: ...

    with warnings.catch_warnings():
        warnings.simplefilter("error", OtherWarning)
        with pytest.raises(OtherWarning):
            f("a")


def test_error_and_warning_go_together():
    @validate(on_error = "warn", warning = OtherWarning, error = ShopError)
    def f(n: int) -> None: ...

    seen = _issued(lambda: f("a"))
    assert type(seen[0].message) is OtherWarning and type(seen[0].message.error) is ShopError


def test_under_on_error_raise_it_changes_nothing():
    @validate(warning = OtherWarning)
    def f(n: int) -> None: ...

    with pytest.raises(InvalidDataError):
        f("a")


def test_what_cannot_be_warned_is_raised_all_the_same():
    @validate(on_error = "warn", warning = OtherWarning)
    def f(n: int) -> None: ...

    with pytest.raises(InvalidDataError):
        f()


def test_two_functions_with_two_classes():
    @validate(on_error = "warn", warning = OtherWarning)
    def f(n: int) -> None: ...

    @validate(on_error = "warn", warning = ShopWarning)
    def g(n: int) -> None: ...

    assert [w.category for w in _issued(lambda: (f("a"), g("a")))] == [OtherWarning, ShopWarning]


def test_validate_function_and_validate_record_keep_one_per_class():
    def f(n: int) -> None: ...

    def issued(*classes: Any) -> list[Any]:
        return [w.category for c in classes for w in _issued(lambda: validate_function(f, ("a",), on_error = "warn", warning = c))]

    assert issued(OtherWarning, ShopWarning, OtherWarning) == [OtherWarning, ShopWarning, OtherWarning]

    def record(c: Any) -> list[Any]:
        spec = {"object_name": "r", "record": {"n": "int"}, "args": ("a",), "on_error": "warn", "warning": c}
        return [w.category for w in _issued(lambda: validate_record(spec))]

    assert record(OtherWarning) + record(ShopWarning) + record(OtherWarning) == [OtherWarning, ShopWarning, OtherWarning]


def test_enforced_hands_the_class_down_and_a_subclass_may_replace_it():
    class Base(Enforced, on_error = "warn", warning = OtherWarning):
        def m(self, n: int) -> None: ...

    class Same(Base):
        def s(self, n: int) -> None: ...

    class Replaced(Base, warning = ShopWarning):
        def r(self, n: int) -> None: ...

    assert [w.category for w in _issued(lambda: Same().s("a"))] == [OtherWarning]
    assert [w.category for w in _issued(lambda: Replaced().r("a"))] == [ShopWarning]
    assert [w.category for w in _issued(lambda: Replaced().m("a"))] == [OtherWarning]       # the method is Base's


WRONG = [5, "ShopWarning", UserWarning, Warning, ValueError, InvalidDataError, InvalidDataWarning(), None]

APIS = {
    "validate": lambda w: validate(warning = w),
    "validate, directly": lambda w: validate(lambda: None, warning = w),
    "enforce": lambda w: enforce(warning = w),
    "enforce_class": lambda w: enforce_class(type("C", (), {}), warning = w),
    "Enforced": lambda w: type("C", (Enforced,), {}, warning = w if w is not None else 5),
    "dataclass": lambda w: dataclass(warning = w),
    "make_dataclass": lambda w: make_dataclass("M", ["x"], warning = w),
    "dispatch": lambda w: dispatch(warning = w),
    "dispatchmethod": lambda w: dispatchmethod(warning = w),
    "validate_function": lambda w: validate_function(lambda: None, warning = w),
    "validate_record": lambda w: validate_record({"object_name": "f", "record": {}, "warning": w}),
    }


@pytest.mark.parametrize("api", APIS)
@pytest.mark.parametrize("wrong", WRONG, ids = repr)
def test_what_is_no_subclass_is_refused_where_it_is_written(api, wrong):
    with pytest.raises(InvalidDataError, match = "warning must be"):
        APIS[api](wrong)


@pytest.mark.parametrize("on_error", ["raise", "warn"])
def test_a_refusal_comes_with_either_on_error(on_error):
    with pytest.raises(InvalidDataError, match = "warning must be"):
        validate(lambda: None, on_error = on_error, warning = UserWarning)


def test_an_importable_subclass_pickles_as_itself():
    @validate(on_error = "warn", warning = ShopWarning)
    def f(n: int) -> None: ...

    warning = _issued(lambda: f("a"))[0].message
    copy = pickle.loads(pickle.dumps(warning))
    assert type(copy) is ShopWarning and str(copy) == str(warning) and type(copy.error) is InvalidDataError


def test_a_local_subclass_pickles_as_invalid_data_warning():
    class Local(InvalidDataWarning):
        pass

    @validate(on_error = "warn", warning = Local)
    def f(n: int) -> None: ...

    warning = _issued(lambda: f("a"))[0].message
    copy = pickle.loads(pickle.dumps(warning))
    assert type(copy) is InvalidDataWarning and str(copy) == str(warning)


@pytest.mark.colours
def test_the_warning_is_coloured_under_its_own_name(monkeypatch):
    monkeypatch.setattr(formatting_tool, "_CHOSEN", True)

    @validate(on_error = "warn", warning = OtherWarning)
    def f(n: int) -> None: ...

    seen = _issued(lambda: f("a"))[0]
    text = warnings.formatwarning(seen.message, seen.category, "/a/b.py", 7, "f('a')")
    assert "OtherWarning\x1b[0m: " in text and seen.message.shown() in text and "\x1b" not in str(seen.message)


@pytest.mark.colours
def test_a_shown_that_fails_never_fails_the_warning(monkeypatch):
    monkeypatch.setattr(formatting_tool, "_CHOSEN", True)

    class Needs(InvalidDataWarning):
        def __init__(self, entries: list[str]) -> None:             # pragma: no cover  # never called by enforced
            self.entries = entries

        def shown(self) -> str:
            return ", ".join(self.entries)                          # never set: enforced runs no __init__

    @validate(on_error = "warn", warning = Needs)
    def f(n: int) -> None: ...

    seen = _issued(lambda: f("a"))[0]
    text = warnings.formatwarning(seen.message, seen.category, "/a/b.py", 7, "f('a')")
    assert str(seen.message) in text
