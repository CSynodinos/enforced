"""
The environment variables enforced reads (``EnvVar``), and ``ENFORCED_TYPECHECK_OFF=1``, which
switches every check off: each API hands back what it was given.
"""
from enforced import InvalidDataError
from enforced._environment import EnvVar
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
    variables = {k: v for k, v in os.environ.items() if k not in (EnvVar.TYPECHECK_OFF, EnvVar.COMPILE_AFTER)}
    variables.update({"PYTHONPATH": str(ROOT), EnvVar.COLOURS_OFF: "1", **env})
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output = True, text = True, env = variables)


# ── EnvVar ───────────────────────────────────────────────────────────────────

def test_every_variable_is_in_the_enum():
    #* Private since 2026-10-15 (the owner's decision): the functions below are the way in from code.
    assert issubclass(EnvVar, enum.StrEnum) and not hasattr(enforced, "EnvVar") and "EnvVar" not in enforced.__all__
    assert {member.name: member.value for member in EnvVar} == {
        "TYPECHECK_OFF": "ENFORCED_TYPECHECK_OFF", "COMPILE_AFTER": "ENFORCED_COMPILE_AFTER",
        "COLOURS_OFF": "ENFORCED_COLOURS_OFF", "NO_COLOR": "NO_COLOR",
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
                        if p.name not in ("_environment.py", "_formatting_tool.py"))
    assert "os.environ" not in elsewhere and "getenv" not in elsewhere


def test_a_member_is_the_key_the_environment_is_read_with(monkeypatch):
    from enforced._formatting_tool import colours_on
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

    class Based(Enforced):
        def m(self, x: int) -> int: return x

    account = Account(5)
    account.size = "any"
    out = [
        checked is plain, with_options is plain, checked("a"), with_options(["b"]),
        vars(Account)["deposit"].__name__, hasattr(vars(Account)["deposit"], "__wrapped__"), account.owner,
        account.deposit("c"), account.size, account.kept,
        dataclasses.is_dataclass(Point), Point("1", ["x"]).x, Point("1").tags, "__enforced_dataclass__" in vars(Point),
        typecheck_function(plain, ("d",)), typecheck_function(plain, (), {"x": "e"}, coerce = True),
        typecheck_function(account.deposit, ("f",)), enforce_class(Later) is Later, Later().m("g"),
        typecheck_record({"object_name": "f", "record": {"x": int}, "args": ["h"], "kwargs": {"y": "i"}}),
        typecheck_record({"object_name": plain, "record": {"x": "no annotation at all"}}),
        typecheck(5), enforce(5), enforce_class(5), typecheck(Account) is Account,
        asyncio.run(protect(fetch("j"))), Email("A@B.co"),
        make_dataclass("Made", [("n", int)], coerce = True)("k").n, Based().m("l"),
        ]
    print(out)
    """

SWITCHED_OFF = (
    "[True, True, 'a', ['b'], 'deposit', False, 5, 'c', 'big', 'any', True, '1', [], False, 'd', 'e', 'f', True, 'g', "
    "(('h',), {'y': 'i'}), ((), {}), 5, 5, 5, True, Ok(value='j'), Email('A@b.co'), 'k', 'l']")


def test_with_the_switch_every_api_hands_back_what_it_was_given():
    done = run(PROGRAM, ENFORCED_TYPECHECK_OFF = "1")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == SWITCHED_OFF


@pytest.mark.parametrize("value", [None, "0", "true"], ids = ["unset", "0", "true"])
def test_without_the_switch_the_same_program_is_stopped_at_its_first_mistake(value):
    done = run(PROGRAM, **({} if value is None else {"ENFORCED_TYPECHECK_OFF": value}))
    assert done.returncode == 1
    #* The first thing that is checked and wrong: Account(5), an int for the owner.
    assert "InvalidDataError" in done.stderr and "For parameter owner of <Class Account>: expected type: 'str'" in done.stderr


def test_the_switch_is_read_when_enforced_is_imported():
    #* Set afterwards it changes nothing: what was decorated is checked, and stays so.
    done = run("""
        import os
        from enforced import typecheck, InvalidDataError
        from enforced._environment import EnvVar
        os.environ[EnvVar.TYPECHECK_OFF] = "1"

        @typecheck
        def f(x: int): return x
        try:
            f("a")
            print("accepted")
        except InvalidDataError:
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
    import dataclasses
    from enforced import Enforced, dataclass, enforce, enforce_class, make_dataclass, typecheck, typecheck_record, typecheck_function
    monkeypatch.setattr(environment, "TYPECHECK_OFF", True)

    def f(x: int) -> int:
        return x

    class C:
        def m(self, x: int) -> int:
            return x

    @dataclass
    class D:
        x: int
    M = make_dataclass("M", [("x", int)])

    class E(Enforced):
        def m(self, x: int) -> int:
            return x

    assert E().m("e") == "e" and "__wrapped__" not in vars(vars(E)["m"])

    assert M("d").x == "d" and dataclasses.is_dataclass(M) and "__enforced_dataclass__" not in vars(M)
    assert typecheck(f) is f and typecheck()(f) is f and enforce(C) is C and enforce()(C) is C and enforce_class(C) is C
    assert typecheck_function(f, ("a",)) == "a" and C().m("b") == "b" and D("c").x == "c"
    assert typecheck_record({"object_name": "f", "record": {"x": int}, "args": ("a",)}) == (("a",), {})
    monkeypatch.setattr(environment, "TYPECHECK_OFF", False)
    with pytest.raises(InvalidDataError):
        typecheck(f)("a")
    assert D("still unchecked: it was made while the switch was on").x


# ── tiered compilation: ENFORCED_COMPILE_AFTER ───────────────────────────────

def _is_compiled(fn) -> bool:
    return "__enforced_source__" in vars(fn)


@pytest.mark.parametrize("after", [1, 2, 5, 64])
def test_a_wrapper_is_compiled_at_the_call_the_setting_names(monkeypatch, after):
    from enforced import typecheck
    monkeypatch.setattr(environment, "COMPILE_AFTER", after)

    @typecheck(check_return = True)
    def f(x: float, y: int = 0) -> float:
        return x

    for call in range(1, after + 3):                                # every call counts, a refused one too
        assert _is_compiled(f) is (call > after)
        if call % 3:
            assert type(f(call)) is float                           # converted on either path
        else:
            with pytest.raises(InvalidDataError):
                f("a")
    assert _is_compiled(f)


def test_both_tiers_do_the_same(monkeypatch):
    #* The general path and the compiled wrapper: same results, same conversions, same errors.
    from enforced import dataclass, enforce, typecheck
    from typing import Self
    import asyncio

    def build(after: int):
        monkeypatch.setattr(environment, "COMPILE_AFTER", after)

        @typecheck(check_return = True)
        def f(a: int, b: float = 1, *args: str, c: bool = False, **kw: int) -> float:
            return a * b

        @enforce(check_return = True)
        class C:
            def __init__(self, n: int = 0) -> None:
                self.n = n
            def twin(self, other: Self | None = None) -> Self:
                return other or self
            @classmethod
            def make(cls, n: int) -> Self:
                return cls(n)
            async def later(self, x: float) -> float:
                return x

        @dataclass
        class D:
            x: int
            y: float = 0

        return f, C, D

    def outcomes(made):
        f, C, D = made
        out = []
        calls = [lambda: f(1), lambda: f(2, 3), lambda: f(1, 2, "a", "b", c = True, z = 1), lambda: f("x"), lambda: f(1, "y"),
                 lambda: f(1, 2, 3), lambda: f(1, z = "no"), lambda: f(), lambda: f(1, a = 2), lambda: f(1, c = 5),
                 lambda: type(C(1).twin()).__name__, lambda: C().twin(5), lambda: C.make("n"), lambda: C.make(2).n,
                 lambda: asyncio.run(C().later(1)), lambda: asyncio.run(C().later("x")),
                 lambda: (D(1, 2).y, type(D(1, 2).y).__name__), lambda: D("a"), lambda: D(1, y = "b"), lambda: D()]
        for _ in range(3):
            for call in calls:
                try:
                    out.append(("ok", repr(call())))
                except InvalidDataError as e:
                    out.append(("error", str(e), [(p.kind, p.parameter) for p in e.problems]))
        return out

    general, compiled = build(10 ** 6), build(1)
    assert outcomes(general) == outcomes(compiled)
    assert not _is_compiled(general[0]) and _is_compiled(compiled[0])


def _generated(cls) -> bool:
    """Whether the assignment check of a dataclass is the function generated for its fields."""
    return vars(cls)["__setattr__"].__code__.co_filename.startswith("<enforced __setattr__")


def _stores(cls) -> bool:
    """Whether the ``__init__`` of a dataclass stores its arguments past the assignment check (``storing_init``)."""
    return "_pv_set" in cls.__init__.__globals__["_pv_checker"].call.__code__.co_freevars


@pytest.mark.parametrize("after", [1, 2, 5])
def test_a_dataclass_is_compiled_at_the_use_the_setting_names(monkeypatch, after):
    from enforced import dataclass
    monkeypatch.setattr(environment, "COMPILE_AFTER", after)

    @dataclass
    class Point:
        x: int
        y: float = 0

    assert not _generated(Point) and not _stores(Point)             # defining the class compiles nothing
    for n in range(1, after):
        assert type(Point(n, n).y) is float
        assert not _stores(Point)
    point = Point(0)
    assert _stores(Point)                                           # the construction the setting names
    #* The storing __init__ assigns nothing, so the assignment check has its own count. (Before
    #* it, the standard __init__ assigned two fields per construction.)
    for n in range(after):
        point.x = n
    assert _generated(Point)
    for n in range(3):
        point.y = n
        assert type(point.y) is float
    with pytest.raises(InvalidDataError, match = "Field Point.x of <Dataclass Point>"):
        point.x = "a"
    with pytest.raises(InvalidDataError, match = "For parameter x of <Dataclass Point>"):
        Point("a")


def test_both_tiers_of_a_dataclass_do_the_same(monkeypatch):
    #* The test of one field at a time, and the function generated for all of them.
    import dataclasses
    from enforced import TypeModel, dataclass
    from typing import Annotated, Literal, Optional, Self

    class Word(TypeModel[str]):
        @classmethod
        def validate(cls, raw: str) -> str:
            if not raw.isalpha():
                raise ValueError("letters only")
            return raw.lower()

    def build(after: int, **options):
        monkeypatch.setattr(environment, "COMPILE_AFTER", after)

        @dataclass(**options)
        class Node:
            n: int
            ratio: float = 0
            word: Word = "a"                                        # type: ignore[assignment]
            mode: Literal["r", "w"] = "r"
            small: Annotated[int, lambda v: v < 10] = 1
            tags: list[int] = dataclasses.field(default_factory = list)
            parent: Optional[Self] = None
            anything: object = None
            total: float = dataclasses.field(init = False, default = 0)

            def __post_init__(self) -> None:
                self.total = self.n if isinstance(self.n, int) else 0       # converted by the assignment check

        class Leaf(Node):                                           # not decorated: Self is Leaf for its instances
            pass

        @dataclasses.dataclass
        class Retyped(Node):                                        # a standard dataclass that makes ``n`` its own
            n: str = ""                                             # type: ignore[assignment]

        return Node, Leaf, Retyped

    values = [1, 1.5, "a", "Abc", "a1", "r", "x", 5, 50, True, None, [1], ["a"], (1,), 2 ** 60, b"b", {}]
    fields = ["n", "ratio", "word", "mode", "small", "tags", "parent", "anything", "total", "unknown"]

    def outcomes(made):
        Node, Leaf, Retyped = made
        out = []
        for cls in (Node, Leaf, Retyped):
            for name in fields:
                for value in values + [Node(1), Leaf(2)]:
                    instance = cls(3) if cls is not Retyped else cls("three")
                    try:
                        setattr(instance, name, value)
                        got = getattr(instance, name)
                        out.append((cls.__name__, name, type(got).__name__, repr(got) if type(got) in (int, float, str, list) else ""))
                    except InvalidDataError as e:
                        out.append((cls.__name__, name, "error", str(e), [(p.kind, p.parameter, p.detail) for p in e.problems]))
                    except AttributeError as e:                     # slots: no such attribute
                        out.append((cls.__name__, name, "no attribute", str(e)))
            for args in ((1,), ("a",), (1, 2, "Up"), (1, 2, "1"), (1, 2, "b", "z"), (1, 2, "b", "w", 50), (1, 2, "b", "w", 5, ["a"])):
                try:
                    made_one = cls(*args)
                    out.append((cls.__name__, args, repr(dataclasses.astuple(made_one)), type(made_one.total).__name__))
                except InvalidDataError as e:
                    out.append((cls.__name__, args, "error", str(e)))
        return out

    for options in ({}, {"deep": True}, {"coerce": True}, {"allow_subclass": False}, {"slots": True}):
        general, compiled = build(10 ** 6, **options), build(1, **options)
        first, second = outcomes(general), outcomes(compiled)
        assert first == second, options
        assert any(entry[2] == "error" for entry in first) and any(entry[2] != "error" for entry in first)
        assert not _generated(general[0]) and _generated(compiled[0])


def test_the_setting_is_read_from_the_environment(monkeypatch):
    for value, expected in (("1", 1), ("0", 1), ("200", 200), ("-5", 1), ("many", 64), ("", 64)):
        monkeypatch.setenv(EnvVar.COMPILE_AFTER, value)
        assert environment.compile_after() == expected, value
    monkeypatch.delenv(EnvVar.COMPILE_AFTER)
    assert environment.compile_after() == 64
    done = run("""
        from enforced import typecheck
        @typecheck
        def f(x: int): return x
        f(1); f(2)
        print("__enforced_source__" in vars(f))
        f(3)
        print("__enforced_source__" in vars(f))
        """, ENFORCED_COMPILE_AFTER = "3")
    assert done.stdout.split() == ["False", "True"]
    done = run("""
        from enforced import typecheck
        @typecheck
        def f(x: int): return x
        for i in range(63): f(i)
        print("__enforced_source__" in vars(f))
        f(1)
        print("__enforced_source__" in vars(f))
        """)
    assert done.stdout.split() == ["False", "True"]                 # the default: at the 64th call


# ── the same switches from code (2026-10-15) ─────────────────────────────────

@pytest.fixture
def switches(monkeypatch):
    """Whatever a test switches is put back: the switches are the process's."""
    import enforced._formatting_tool as tool
    monkeypatch.setattr(environment, "TYPECHECK_OFF", environment.TYPECHECK_OFF)
    monkeypatch.setattr(environment, "COMPILE_AFTER", environment.COMPILE_AFTER)
    monkeypatch.setattr(tool, "_CHOSEN", None)
    return tool


def test_turn_typecheck_off_is_for_what_is_decorated_after_it(switches):
    from enforced import dataclass, enforce, turn_typecheck_off, turn_typecheck_on, typecheck, typecheck_function, \
        typecheck_is_off, typecheck_record

    @typecheck
    def before(x: int) -> int:
        return x

    assert typecheck_is_off() is False
    turn_typecheck_off()
    assert typecheck_is_off() is True

    def f(x: int) -> int:
        return x

    assert typecheck(f) is f and typecheck(check_return = True)(f) is f        # nothing wrapped: what was given
    class C:
        def m(self, x: int) -> int:
            return x
    assert enforce(C) is C and C().m("a") == "a"

    @dataclass
    class P:
        x: int
    assert P("b").x == "b"
    assert typecheck_function(f, ("c",)) == "c"
    assert typecheck_record({"object_name": "f", "record": {"x": int}, "args": ("d",)}) == (("d",), {})
    with pytest.raises(InvalidDataError):
        before("e")                                     # made while the checks were on: still checked
    turn_typecheck_on()
    assert typecheck_is_off() is False
    with pytest.raises(InvalidDataError):
        typecheck(f)("f")


def test_set_compile_after(switches):
    from enforced import set_compile_after, typecheck
    set_compile_after(3)

    @typecheck
    def f(x: int) -> int:
        return x

    seen = []
    for n in range(4):
        seen.append("__enforced_source__" in vars(f))
        f(n)
    assert seen == [False, False, False, True]          # compiled at the third call
    for wrong, error in ((0, ValueError), (-2, ValueError), ("3", TypeError), (2.0, TypeError), (True, TypeError), (None, TypeError)):
        with pytest.raises(error, match = "set_compile_after"):
            set_compile_after(wrong)                    # type: ignore[arg-type]
    assert environment.COMPILE_AFTER == 3


def test_turn_colours_off_and_on_come_before_the_environment(switches, monkeypatch):
    from enforced import turn_colours_off, turn_colours_on, typecheck

    @typecheck
    def f(x: int) -> int:
        return x

    def message() -> str:
        with pytest.raises(InvalidDataError) as e:
            f("a")
        return str(e.value)

    monkeypatch.setenv("FORCE_COLOR", "1")
    turn_colours_off()
    assert "\x1b[" not in message() and not switches.colours_on()
    monkeypatch.delenv("FORCE_COLOR")
    monkeypatch.setenv("NO_COLOR", "1")
    turn_colours_on()
    text = message()
    assert "\x1b[" in text and "\x1b[1m\x1b[32mx\x1b[0m" in text         # coloured, whatever NO_COLOR says
    switches._CHOSEN = None                                                # back to the environment
    assert not switches.colours_on()


# ── frames: read the public way ──────────────────────────────────────────────

def test_frames_are_read_through_inspect_only():
    #* The owner's decision, 2026-10-16: no sys._getframe (or _getframemodulename) in the package;
    #* _lifetime.frame_above, through inspect.currentframe, is the one way to a frame.
    import sys
    from enforced._typechecker._lifetime import frame_above
    sources = "".join(p.read_text() for p in (ROOT / "enforced").rglob("*.py"))
    assert "_getframe(" not in sources and "_getframemodulename" not in sources     # a call, not a mention

    def inner():
        return frame_above(), frame_above(2)
    def outer():
        return inner()
    caller, above = outer()
    assert caller.f_code is outer.__code__ and above.f_code is sys._getframe().f_code
    assert frame_above(10_000) is None                              # above the top of the stack
