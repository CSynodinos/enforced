"""
Known issues: bugs and gaps that aren't fixed yet. They are also listed in CLAUDE.md and in phase 7
of tests/simulation.py.

Each test states the *correct* behaviour and is marked as an expected failure, so the suite stays
green. The marks are strict and name the exception the issue produces today: a test that starts
passing, or that fails in any other way, fails the suite. When an issue is fixed, move its test to
the file of its subject and drop the mark.

    python -m pytest tests/test_known_issues.py -rx           # list them, with where each one is
    python -m pytest tests/test_known_issues.py --runxfail    # run them as normal tests: the failures in full
"""
from dataclasses import InitVar
from typing import Optional
import sys
import types

import pytest

from enforced import dataclass, InvalidDataError, validate


#* For an issue that lets a bad value through: what pytest.raises fails with ("DID NOT RAISE").
NOT_REJECTED = pytest.fail.Exception


def known_issue(where: str, raises: type[BaseException]) -> pytest.MarkDecorator:
    """Mark a test as stating the correct behaviour of an issue that isn't fixed yet, found at ``where``."""
    return pytest.mark.xfail(strict = True, raises = raises, reason = f"not fixed yet: {where}")


def test_the_marks_are_strict():
    """
    A known issue that starts to pass has to fail the suite, or its test would stay here for good.
    (This test also gives the file something to run while no issue is open: pytest ends with
    status 5 for a file without a single test.)
    """
    mark = known_issue("nowhere", NOT_REJECTED).mark
    assert mark.name == "xfail" and mark.kwargs["strict"] is True and mark.kwargs["raises"] is NOT_REJECTED


# ── a local name that is out of reach (the owner's decision, 2026-11-04: recorded, not chased) ──

def _run(source: str, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[module.__name__] = module
    exec(compile(source, name, "exec", dont_inherit = True), module.__dict__)
    return module


@known_issue("local_names: one set of local names for every annotation of a class's MRO", InvalidDataError)
def test_a_local_name_of_a_subclass_does_not_replace_what_a_base_at_module_level_means():
    #* A wrong answer, not only a refusal: 3 is accepted here. It takes a local name that is also a name in the base's module.
    module = _run("""
from __future__ import annotations
import dataclasses
from enforced import dataclass

class Meant: ...

@dataclasses.dataclass
class ModuleBase:
    v: Meant

def written_here():
    Meant = int

    @dataclass
    class Sub(ModuleBase):
        w: Meant = 1

    return Sub
""", "known_shadow")
    module.written_here()(module.Meant())


@known_issue("resolve_annotations: an InitVar is read after look_again's turn", InvalidDataError)
def test_a_quoted_init_var_may_name_what_is_written_further_down():
    @dataclass
    class Holder:
        a: InitVar["Later"]                                         # noqa: F821

    class Later: ...

    Holder(Later())


@known_issue("strings_in: the value of a ``type`` alias isn't looked into", InvalidDataError)
def test_a_type_alias_may_quote_a_local_name():
    def make() -> tuple:
        class Local: ...

        type Alias = Optional["Local"]

        @validate
        def f(x: Alias) -> None: ...

        return f, Local

    f, local = make()
    f(local())


@known_issue("_it_returned: what a later alias quotes isn't followed", InvalidDataError)
def test_an_alias_may_quote_what_is_written_further_down():
    module = _run("""
from __future__ import annotations
from typing import Optional
from enforced import validate

def make():
    Alias = Optional["Local"]

    @validate
    def f(x: Alias): ...

    class Local: ...

    return f, Local
""", "known_alias_below")
    f, local = module.make()
    f(local())


@pytest.mark.xfail(sys.version_info >= (3, 14), strict = True, raises = InvalidDataError,
                   reason = "not fixed yet: _annotation_texts doesn't evaluate, and an alias's quotes show only then (3.13 has evaluated it)")
def test_an_alias_may_quote_a_local_name():
    def make() -> tuple:
        class Local: ...

        Alias = Optional["Local"]

        @validate
        def f(x: Alias) -> None: ...

        return f, Local

    f, local = make()
    f(local())


@known_issue("resolve_annotations: a class's annotations are read in its own module, also those a base in another module wrote", InvalidDataError)
def test_a_field_inherited_from_another_module_means_what_that_module_means():
    #* A wrong answer: an int is accepted here, for a field that says Decimal.
    _run("""
from __future__ import annotations
import dataclasses
from decimal import Decimal as Amount

@dataclasses.dataclass
class Base:
    total: Amount
""", "known_models")
    module = _run("""
from __future__ import annotations
from decimal import Decimal
from enforced import dataclass
from known_models import Base

Amount = int

@dataclass
class Sub(Base): ...
""", "known_app")
    module.Sub(module.Decimal(1))


@known_issue("look_again: the generated __init__ of a dataclass goes to remember_scope, with the names of the bases' fields", InvalidDataError)
def test_a_name_looked_for_again_does_not_replace_what_a_base_means():
    module = _run("""
from __future__ import annotations
import dataclasses
from enforced import dataclass

class Meant: ...

@dataclasses.dataclass
class ModuleBase:
    v: Meant

def written_here():
    Meant = int

    @dataclass
    class Sub(ModuleBase):
        w: Later | None = None

    class Later: ...

    return Sub(globals()["Meant"]())
""", "known_look_again")
    module.written_here()

