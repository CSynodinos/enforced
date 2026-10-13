"""
The environment variables enforced reads (``EnvVar``), and ``ENFORCED_TYPECHECK_OFF=1``, which
switches every check off: each API hands back what it was given.
"""
from enforced import EnvVar, TypeCheckerError
from pathlib import Path
import enum
import os
import subprocess
import sys
import textwrap
import pytest
import enforced
import enforced._environment as environment

ROOT = Path(__file__).resolve().parent.parent


def run(code: str, **env: str) -> subprocess.CompletedProcess:
    """Run ``code`` in a fresh interpreter, with ``env`` added to the environment and colours off."""
    variables = {k: v for k, v in os.environ.items() if k != EnvVar.TYPECHECK_OFF}
    variables.update({"PYTHONPATH": str(ROOT), EnvVar.COLOURS_OFF: "1", **env})
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output = True, text = True, env = variables)


# ── EnvVar ───────────────────────────────────────────────────────────────────

def test_every_variable_is_in_the_enum():
    assert issubclass(EnvVar, enum.StrEnum) and enforced.EnvVar is EnvVar and "EnvVar" in enforced.__all__
    assert {member.name: member.value for member in EnvVar} == {
        "TYPECHECK_OFF": "ENFORCED_TYPECHECK_OFF", "COLOURS_OFF": "ENFORCED_COLOURS_OFF", "NO_COLOR": "NO_COLOR",
        "ANSI_COLORS_DISABLED": "ANSI_COLORS_DISABLED", "FORCE_COLOR": "FORCE_COLOR", "TERM": "TERM"}
    assert EnvVar.COLOURS_OFF == "ENFORCED_COLOURS_OFF" and f"{EnvVar.TYPECHECK_OFF}=1" == "ENFORCED_TYPECHECK_OFF=1"


def test_the_package_names_its_variables_through_the_enum_only():
    #* Outside the module that defines them, no source line of the package spells a variable's name
    #* as a text of its own (a docstring may mention one; code reads EnvVar.<NAME>).
    spelt = []
    for path in (ROOT / "enforced").rglob("*.py"):
        if path.name == "_environment.py":
            continue
        for line in path.read_text().splitlines():
            code = line.split("#")[0]
            if any(f'"{name.value}"' in code or f"'{name.value}'" in code for name in EnvVar):
                spelt.append(f"{path.name}: {line.strip()}")
    assert spelt == []
    #* And the one place that reads the environment directly does it with members.
    elsewhere = "".join(p.read_text() for p in (ROOT / "enforced").rglob("*.py")
                        if p.name not in ("_environment.py", "formatting_tool.py"))
    assert "os.environ" not in elsewhere and "getenv" not in elsewhere


def test_a_member_is_the_key_the_environment_is_read_with(monkeypatch):
    from enforced.formatting_tool import colours_on
    for name in EnvVar:
        monkeypatch.delenv(name, raising = False)
    monkeypatch.setenv(EnvVar.FORCE_COLOR, "1")
    assert colours_on() is True
    monkeypatch.setenv(EnvVar.COLOURS_OFF, "1")
    assert colours_on() is False
    assert environment.typecheck_off() is False
    monkeypatch.setenv(EnvVar.TYPECHECK_OFF, "1")
    assert environment.typecheck_off() is True
    for other in ("0", "", "true", "yes"):                          # "1" and nothing else, like ENFORCED_COLOURS_OFF
        monkeypatch.setenv(EnvVar.TYPECHECK_OFF, other)
        assert environment.typecheck_off() is False


# ── ENFORCED_TYPECHECK_OFF=1, in a program of its own ────────────────────────

PROGRAM = """
    import asyncio, dataclasses, functools
    from typing import Annotated, Self
    from enforced import *
    from enforced.data_types import Email, PositiveInt

    def plain(x: int, y: float = "not a float") -> int:
        return x
    checked, with_options = typecheck(plain), typecheck(check_return = True, deep = True)(plain)

    @enforce(check_return = True)
    class Account:
        def __init__(self, owner: str) -> None:
            self.owner = owner
        def deposit(self, amount: float) -> Self:
            return amount
        @property
        def size(self) -> int:
            return "big"
        @size.setter
        def size(self, value: int) -> None:
            self.kept = value

    @dataclass(frozen = True, deep = True, coerce = True)
    class Point:
        x: int
        tags: list[int] = dataclasses.field(default_factory = list)

    class Later:
        def m(self, x: int): return x

    async def fetch(x: int) -> int: return x

    account = Account(5)
    account.size = "any"
    out = [
        checked is plain, with_options is plain, checked("a"), with_options(["b"]),
        vars(Account)["deposit"].__name__, hasattr(vars(Account)["deposit"], "__wrapped__"), account.owner,
        account.deposit("c"), account.size, account.kept,
        dataclasses.is_dataclass(Point), Point("1", ["x"]).x, Point("1").tags, "__enforced_dataclass__" in vars(Point),
        typecheck_function(plain, ("d",)), typecheck_function(plain, (), {"x": "e"}, coerce = True),
        typecheck_function(account.deposit, ("f",)), enforce_class(Later) is Later, Later().m("g"),
        typecheck_from_dict({"object_name": "f", "record": {"x": int}, "args": ["h"], "kwargs": {"y": "i"}}),
        typecheck_from_dict({"object_name": plain, "record": {"x": "no annotation at all"}}),
        typecheck(5), enforce(5), enforce_class(5), typecheck(Account) is Account,
        asyncio.run(protect(fetch("j"))), Email("A@B.co"),
        ]
    print(out)
    """

SWITCHED_OFF = (
    "[True, True, 'a', ['b'], 'deposit', False, 5, 'c', 'big', 'any', True, '1', [], False, 'd', 'e', 'f', True, 'g', "
    "(('h',), {'y': 'i'}), ((), {}), 5, 5, 5, True, Ok(value='j'), Email('A@b.co')]")


def test_with_the_switch_every_api_hands_back_what_it_was_given():
    done = run(PROGRAM, ENFORCED_TYPECHECK_OFF = "1")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == SWITCHED_OFF


@pytest.mark.parametrize("value", [None, "0", "true"], ids = ["unset", "0", "true"])
def test_without_the_switch_the_same_program_is_stopped_at_its_first_mistake(value):
    done = run(PROGRAM, **({} if value is None else {"ENFORCED_TYPECHECK_OFF": value}))
    assert done.returncode == 1
    #* The first thing that is checked and wrong: Account(5), an int for the owner.
    assert "TypeCheckerError" in done.stderr and "For parameter owner of <Class Account>: expected type: 'str'" in done.stderr


def test_the_switch_is_read_when_enforced_is_imported():
    #* Set afterwards it changes nothing: what was decorated is checked, and stays so.
    done = run("""
        import os
        from enforced import typecheck, TypeCheckerError, EnvVar
        os.environ[EnvVar.TYPECHECK_OFF] = "1"

        @typecheck
        def f(x: int): return x
        try:
            f("a")
            print("accepted")
        except TypeCheckerError:
            print("rejected")
        """)
    assert done.stdout.strip() == "rejected"
    #* Set before the import, from inside the program: that works.
    done = run("""
        import os
        os.environ["ENFORCED_TYPECHECK_OFF"] = "1"
        from enforced import typecheck

        @typecheck
        def f(x: int): return x
        print(f("a"), f is f.__wrapped__ if hasattr(f, "__wrapped__") else "plain")
        """)
    assert done.stdout.strip() == "a plain"


def test_switched_off_nothing_is_added_to_a_call():
    done = run("""
        from enforced import typecheck, enforce, dataclass
        import enforced._environment as environment
        def f(x: int): return x
        class C:
            def m(self, x: int): return x
        raw = C.__dict__["m"]
        @dataclass
        class D:
            x: int
        print(environment.TYPECHECK_OFF, typecheck(f) is f, typecheck(deep = True)(f) is f, enforce(C).__dict__["m"] is raw,
              type(D.__init__).__name__, "_pv_bootstrap" in D.__init__.__globals__, D.__setattr__ is object.__setattr__)
        """, ENFORCED_TYPECHECK_OFF = "1")
    assert done.stdout.strip() == "True True True True function False True"


# ── the same, switched inside this process ───────────────────────────────────

def test_each_api_asks_the_switch_first(monkeypatch):
    from enforced import dataclass, enforce, enforce_class, typecheck, typecheck_from_dict, typecheck_function
    monkeypatch.setattr(environment, "TYPECHECK_OFF", True)

    def f(x: int) -> int:
        return x

    class C:
        def m(self, x: int) -> int:
            return x

    @dataclass
    class D:
        x: int

    assert typecheck(f) is f and typecheck()(f) is f and enforce(C) is C and enforce()(C) is C and enforce_class(C) is C
    assert typecheck_function(f, ("a",)) == "a" and C().m("b") == "b" and D("c").x == "c"
    assert typecheck_from_dict({"object_name": "f", "record": {"x": int}, "args": ("a",)}) == (("a",), {})
    monkeypatch.setattr(environment, "TYPECHECK_OFF", False)
    with pytest.raises(TypeCheckerError):
        typecheck(f)("a")
    assert D("still unchecked: it was made while the switch was on").x
