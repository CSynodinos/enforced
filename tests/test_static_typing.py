"""
What a static type checker is told about the decorators. A class or function decorated with
enforced must keep its type: declared carelessly, ``@enforce(...)`` and ``@dataclass`` turned
what they decorated into ``Any`` (no completion and no errors in an editor), and no runtime test
can notice that.

The mypy tests are skipped when mypy isn't installed (``pip install -e ".[dev]"`` installs it).
The others only look at the declarations, and always run.
"""
from enforced import dataclass, enforce, typecheck
from pathlib import Path
from typing import Any
import dataclasses
import os
import re
import sys
import typing
import pytest


SAMPLE = Path(__file__).with_name("static_typing_sample.py")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope = "module")
def mypy_output() -> dict[int, list[str]]:
    """What mypy reports for the sample, by line number."""
    api = pytest.importorskip("mypy.api", reason = "mypy is not installed")
    previous = os.environ.get("MYPYPATH")
    os.environ["MYPYPATH"] = str(ROOT)                      # the package of this working tree, not an installed one
    try:
        out, err, _ = api.run([
            str(SAMPLE), "--follow-imports=silent", "--no-incremental", "--no-error-summary", "--hide-error-context",
            "--python-executable", sys.executable,
            ])
    finally:
        if previous is None:
            del os.environ["MYPYPATH"]
        else:
            os.environ["MYPYPATH"] = previous
    assert not err, err
    lines: dict[int, list[str]] = {}
    for line in out.splitlines():
        if (found := re.match(r".*static_typing_sample\.py:(\d+): (.*)", line)) is not None:
            lines.setdefault(int(found[1]), []).append(found[2])
    assert lines, out
    return lines


def _marked(marker: str) -> dict[int, str]:
    """The lines of the sample that carry ``# marker``, with what follows the marker."""
    marked = {}
    for number, line in enumerate(SAMPLE.read_text().splitlines(), 1):
        if (found := re.search(rf"#\s*{marker}(?::\s*(.*))?$", line)) is not None and not line.lstrip().startswith("#"):
            marked[number] = (found[1] or "").strip()
    return marked


def test_mypy_reports_an_error_exactly_where_one_is_expected(mypy_output):
    reported = {number for number, messages in mypy_output.items() if any(m.startswith("error:") for m in messages)}
    expected = set(_marked("error"))
    assert len(expected) == 24
    assert reported == expected, {number: mypy_output[number] for number in reported ^ expected if number in mypy_output}


def test_mypy_sees_the_type_of_what_is_decorated(mypy_output):
    expected = _marked("revealed")
    assert len(expected) == 32
    for number, text in expected.items():
        revealed = [m for m in mypy_output.get(number, []) if m.startswith("note: Revealed type is")]
        assert revealed, f"line {number}: mypy revealed nothing"
        assert text in revealed[0], f"line {number}: {revealed[0]}"
        assert "Any" not in revealed[0], f"line {number}: {revealed[0]}"


def test_mypy_reports_nothing_in_the_package_itself():
    #* Whoever opens a file of the package in an editor sees what a checker says about it. It was
    #* 59 errors (and 27 from pyright) before the fifth review's leftovers were tidied.
    api = pytest.importorskip("mypy.api", reason = "mypy is not installed")
    out, err, status = api.run([str(ROOT / "enforced"), "--no-incremental", "--no-error-summary",
                                "--python-executable", sys.executable])
    assert not err, err
    assert status == 0, out


# ── the declarations themselves (no type checker needed) ─────────────────────

#* enforce is an object (so that enforce.exempt is known to a checker): its overloads are on __call__.
@pytest.mark.parametrize("decorator", [typecheck, type(enforce).__call__])
def test_typecheck_and_enforce_are_declared_to_return_what_they_are_given(decorator):
    direct, with_options = typing.get_overloads(decorator)
    given = typing.get_type_hints(direct)
    assert given["return"] is given["obj"] and isinstance(given["obj"], typing.TypeVar)
    takes, returns = typing.get_args(typing.get_type_hints(with_options)["return"])
    assert isinstance(returns, typing.TypeVar) and takes == [returns]


def test_exempt_is_declared_to_return_what_it_is_given():
    given = typing.get_type_hints(enforce.exempt)
    assert given["return"] is given["member"] and isinstance(given["member"], typing.TypeVar)


def test_dataclass_is_declared_as_a_dataclass_maker_that_returns_the_class():
    #* dataclass_transform: checkers build __init__ from the fields, know frozen / kw_only / order,
    #* and read dataclasses.field(...) as a field description.
    declared = dataclass.__dataclass_transform__            # type: ignore[attr-defined]
    assert dataclasses.field in declared["field_specifiers"]
    assert (declared["eq_default"], declared["order_default"], declared["kw_only_default"], declared["frozen_default"]) == (
        True, False, False, False)

    direct, with_options = typing.get_overloads(dataclass)
    given = typing.get_type_hints(direct)
    assert typing.get_origin(given["cls"]) is type and given["return"] == given["cls"]
    takes, returns = typing.get_args(typing.get_type_hints(with_options)["return"])
    assert takes == [returns] and typing.get_origin(returns) is type
    assert typing.get_type_hints(with_options)["return"] is not Any


def test_every_option_of_dataclass_is_declared_in_both_overloads():
    import inspect

    real = [name for name in inspect.signature(dataclass).parameters if name != "cls"]
    for overload in typing.get_overloads(dataclass):
        assert [name for name in inspect.signature(overload).parameters if name != "cls"] == real


def test_type_model_is_one_class_at_run_time_and_an_alias_for_a_checker():
    #* For a checker ``TypeModel[str]`` stands for ``str`` (an alias under TYPE_CHECKING), so a model
    #* is its base type there as well, in the short form. When the program runs it is the class.
    from enforced import TypeModel
    from enforced.data_types import Email, Port
    import enforced._typechecker._type_data_model as model_module

    assert isinstance(TypeModel, type) and TypeModel.__name__ == TypeModel.__qualname__ == "TypeModel"
    assert typing.Generic in TypeModel.__mro__ and len(TypeModel.__parameters__) == 1
    assert Email.__bases__ == (TypeModel[str],) and Port.__bases__ == (TypeModel[int],)
    source = Path(model_module.__file__).read_text()
    assert "if TYPE_CHECKING:\n    TypeModel = Annotated[T," in source

    class Short(TypeModel[str]):
        pass

    class Long(TypeModel[str], str):
        pass

    without = [c.__name__ for c in Short.__mro__[1:]]
    assert [c.__name__ for c in Long.__mro__[1:]] == without == ["TypeModel[str]", "TypeModel", "Generic", "str", "object"]
    assert Long(" a ") == " a " and isinstance(Long("a"), str) and type(Long("a") + "b") is str


def test_the_package_says_it_is_typed_and_what_it_exports():
    import enforced

    assert (Path(enforced.__file__).parent / "py.typed").is_file()
    assert sorted(enforced.__all__) == [
        "Check", "Enforced", "Err", "InvalidDataError", "InvalidDataWarning", "Ok", "TypeModel", "asdict", "dataclass", "enforce", "enforce_class", "field",
        "make_dataclass", "protect",
        "set_compile_after", "turn_colours_off", "turn_colours_on", "turn_typecheck_off", "turn_typecheck_on",
        "typecheck", "typecheck_function", "typecheck_is_off", "typecheck_record"]
    assert all(hasattr(enforced, name) for name in enforced.__all__)
    assert re.fullmatch(r"\d+\.\d+\.\d+", enforced.__version__)
