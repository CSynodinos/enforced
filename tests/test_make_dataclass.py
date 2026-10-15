"""
``enforced.make_dataclass``: ``dataclasses.make_dataclass`` with the class made by ``enforced.dataclass``.
"""
from enforced import TypeCheckerError, TypeCheckerWarning, dataclass, make_dataclass
from typing import Any
import dataclasses
import inspect
import pickle
import warnings
import pytest


class Unit:
    """Named by a string annotation below: it is looked up in this module."""


#* At module level, under its own name, so that pickle can find it.
Measured = make_dataclass("Measured", [("value", float), ("unit", "Unit | None", dataclasses.field(default = None))])


def test_the_class_belongs_to_the_module_that_made_it():
    #* The standard function names the module after its caller, which would be enforced's own.
    assert Measured.__module__ == __name__
    assert type(Measured(1, Unit()).unit) is Unit                   # the string, read in this module
    assert pickle.loads(pickle.dumps(Measured(2.5))) == Measured(2.5)
    assert make_dataclass("Elsewhere", [("n", int)], module = "somewhere").__module__ == "somewhere"


def test_construction_defaults_and_assignment_are_checked():
    assert Measured(1).value == 1.0 and type(Measured(1).value) is float  # converted, as by the decorator
    with pytest.raises(TypeCheckerError, match = r"parameter value of <Dataclass Measured>"):
        Measured("a")
    measured = Measured(1)
    with pytest.raises(TypeCheckerError, match = r"Field Measured.unit of <Dataclass Measured>"):
        measured.unit = "kg"
    Bad = make_dataclass("Bad", [("n", int, dataclasses.field(default = "x"))])
    with pytest.raises(TypeCheckerError, match = "default value"):
        Bad()
    Listed = make_dataclass("Listed", [("tags", list[int], dataclasses.field(default_factory = list))])
    assert Listed().tags == []


def test_a_name_alone_is_a_field_of_any_type():
    Loose = make_dataclass("Loose", ["anything"])
    assert Loose(object).anything is object


def test_it_takes_the_options_of_the_decorator():
    assert make_dataclass("C", [("n", int)], coerce = True)("42").n == 42
    with pytest.raises(TypeCheckerError):
        make_dataclass("C", [("x", float)], convert = False)(1)
    with pytest.raises(TypeCheckerError, match = r"index \[1\]"):
        make_dataclass("C", [("xs", list[int])], deep = True)([1, "b"])
    assert make_dataclass("C", [("xs", list[int])])([1, "b"]).xs == [1, "b"]

    class Base: ...
    class Sub(Base): ...
    with pytest.raises(TypeCheckerError):
        make_dataclass("C", [("b", Base)], allow_subclass = False)(Sub())
    unchecked = make_dataclass("C", [("n", int)], check_assignment = False)(1)
    unchecked.n = "fine"
    assert unchecked.n == "fine"


def test_it_takes_the_options_of_the_standard_function():
    Frozen = make_dataclass("Frozen", [("n", int)], frozen = True, slots = True, kw_only = True, order = True)
    assert Frozen(n = 1) < Frozen(n = 2) and "__slots__" in vars(Frozen)
    with pytest.raises(TypeError):
        Frozen(1)                                                    # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Frozen(n = 1).n = 2                                          # type: ignore[misc]
    with pytest.raises(TypeCheckerError):
        Frozen(n = "a")


def test_bases_and_the_methods_in_its_namespace():
    @dataclass
    class Base:
        id: int

    def scaled(self, by: float) -> float:
        return by

    def broken(self) -> int:
        return "no"                                                  # type: ignore[return-value]

    Child = make_dataclass("Child", [("name", str)], bases = (Base,), namespace = {"scaled": scaled, "broken": broken})
    assert Child(1, "a").scaled(2) == 2.0
    with pytest.raises(TypeCheckerError):
        Child("x", "a")                                              # the base's field, checked by the child
    with pytest.raises(TypeCheckerError, match = "parameter by"):
        Child(1, "a").scaled("b")
    assert Child(1, "a").broken() == "no"                            # what a method returns: only with check_return
    Returned = make_dataclass("Returned", [], namespace = {"broken": broken}, check_return = True)
    with pytest.raises(TypeCheckerError, match = "return value"):
        Returned().broken()
    Plain = make_dataclass("Plain", [], namespace = {"scaled": scaled}, check_methods = False)
    assert Plain().scaled("b") == "b"


def test_warn_is_attributed_to_the_line_that_constructs():
    Warned = make_dataclass("Warned", [("n", int)], on_error = "warn")
    with warnings.catch_warnings(record = True) as caught:
        warnings.simplefilter("always")
        assert Warned("z").n == "z"
    assert [w.category for w in caught] == [TypeCheckerWarning] and caught[0].filename == __file__


def test_an_unknown_on_error_is_refused_before_a_class_is_made():
    with pytest.raises(TypeCheckerError, match = "on_error"):
        make_dataclass("C", [("n", int)], on_error = "log")          # type: ignore[arg-type]


def test_it_does_what_the_decorator_does():
    #* The same fields made both ways answer every value alike, constructed and assigned.
    annotations = [int, float, str | None, list[int], dict[str, float], tuple[int, str], bool]
    values: list[Any] = [1, 1.5, "a", None, True, [1, "x"], {"k": 1}, (1, "s"), b"", 3 + 0j, "42"]
    for options in ({}, {"coerce": True}, {"deep": True}, {"convert": False}, {"allow_subclass": False}):
        for annotation in annotations:
            made = make_dataclass("C", [("x", annotation)], **options)
            decorated = dataclass(type("C", (), {"__annotations__": {"x": annotation}}), **options)

            def outcome(cls: type, value: Any) -> Any:
                try:
                    instance = cls(value)
                    instance.x = value
                    return ("ok", repr(instance.x), type(instance.x))
                except TypeCheckerError as error:
                    return ("error", [(p.kind, p.parameter) for p in error.problems])
            for value in values:
                assert outcome(made, value) == outcome(decorated, value), (options, annotation, value)


def test_its_options_are_those_of_both_functions():
    #* Kept in step: what dataclasses.make_dataclass takes (but the decorator: that is ours), and
    #* what enforced.dataclass takes, in the same order, with the same defaults.
    ours = inspect.signature(make_dataclass).parameters
    standard = [p for name, p in inspect.signature(dataclasses.make_dataclass).parameters.items() if name != "decorator"]
    decorator = [p for name, p in inspect.signature(dataclass).parameters.items() if name != "cls"]
    assert {p.name: p.default for p in standard} == {name: ours[name].default for name in (p.name for p in standard)}
    assert [(p.name, p.default) for p in decorator] == [(name, ours[name].default) for name in (p.name for p in decorator)]
    assert set(ours) == {p.name for p in standard} | {p.name for p in decorator}
