"""
What a static type checker makes of code that uses enforced. Not run: tests/test_static_typing.py
hands this file to mypy and compares what it reports with the comments here.

    # revealed: TEXT     the type mypy shows for the ``reveal_type`` on that line contains TEXT
    # error              mypy reports an error on that line (and on no line without this comment)
"""
import dataclasses
from dataclasses import KW_ONLY, InitVar, field
from typing import reveal_type
from enforced import dataclass, enforce, typecheck


# ── typecheck ────────────────────────────────────────────────────────────────

@typecheck
def plain(name: str) -> str:
    return name


@typecheck(check_return = True)
def with_options(name: str, times: int = 1) -> str:
    return name * times


@typecheck()
def with_parentheses(n: int) -> int:
    return n


reveal_type(plain)                          # revealed: def (name: str) -> str
reveal_type(with_options)                   # revealed: def (name: str, times: int =) -> str
reveal_type(with_parentheses)               # revealed: def (n: int) -> int
with_options(5)                             # error
plain("a", "b")                             # error


# ── enforced ─────────────────────────────────────────────────────────────────

@enforce
class Bare:
    def __init__(self, balance: float = 0.0) -> None:
        self.balance = balance

    def deposit(self, amount: float) -> float:
        return amount


@enforce(check_return = True, deep = True)
class WithOptions:
    def deposit(self, amount: float) -> float:
        return amount

    @enforce.exempt
    def dump(self, sink: int) -> int:
        return sink

    @typecheck(coerce = True)
    def parse(self, text: str) -> int:
        return int(text)

    @enforce.exempt
    @classmethod
    def make(cls) -> "WithOptions":
        return cls()


def uses_them_as_types(a: Bare, b: WithOptions) -> None: ...


reveal_type(Bare)                           # revealed: def (balance: float =) -> static_typing_sample.Bare
reveal_type(WithOptions)                    # revealed: def () -> static_typing_sample.WithOptions
reveal_type(WithOptions().deposit)          # revealed: def (amount: float) -> float
reveal_type(WithOptions().dump)             # revealed: def (sink: int) -> int
reveal_type(WithOptions().parse)            # revealed: def (text: str) -> int
reveal_type(WithOptions.make)               # revealed: def () -> static_typing_sample.WithOptions
WithOptions().deposit("x")                  # error
Bare().withdraw(1)                          # error
enforce(plain)                             # error


# ── dataclass ────────────────────────────────────────────────────────────────

@dataclass
class Transaction:
    amount: int
    kind: str = "deposit"
    tags: list[str] = field(default_factory = list)


@dataclass(frozen = True, order = True)
class Frozen:
    x: int
    y: float = 0.0


@dataclass(kw_only = True, slots = True, deep = True, coerce = True, check_assignment = False)
class Options:
    name: str
    size: int = 1


@dataclass()
class Parentheses:
    a: int
    _: KW_ONLY
    b: str = ""
    scale: InitVar[float] = 1.0


@dataclass
class Child(Transaction):
    note: str = ""


reveal_type(Transaction)                    # revealed: def (amount: int, kind: str =, tags: list[str] =) -> static_typing_sample.Transaction
reveal_type(Transaction(1).amount)          # revealed: int
reveal_type(Transaction(1).tags)            # revealed: list[str]
reveal_type(Frozen(1) < Frozen(2))          # revealed: bool
reveal_type(Options(name = "a").size)       # revealed: int
reveal_type(Parentheses(1, b = "x").a)      # revealed: int
reveal_type(Child(1, "k", [], "n").note)    # revealed: str
reveal_type(dataclasses.replace(Frozen(1), x = 2))      # revealed: static_typing_sample.Frozen
dataclasses.asdict(Transaction(1))
Transaction("x")                            # error
Transaction()                               # error
Transaction(1, colour = "red")              # error
Frozen(1).x = 2                             # error
Options("a")                                # error
Transaction(1).missing                      # error


# ── TypeModel ────────────────────────────────────────────────────────────────

from enforced import TypeModel                    # noqa: E402
from enforced.data_types import Email, Port       # noqa: E402


class Slug(TypeModel[str]):                         # a str for the checker too, as it is when the program runs
    @classmethod
    def validate(cls, raw: str) -> str:
        return raw.strip().lower()


#* The spelling that was needed before, with the base type named twice: a duplicate base now.
class Long(TypeModel[str], str):                    # error
    @classmethod
    def validate(cls, raw: str) -> str:
        return raw


def needs_str(text: str) -> None: ...
def needs_int(number: int) -> None: ...


@typecheck
def connect(admin: Email, port: Port) -> None: ...


reveal_type(Slug("a"))                      # revealed: static_typing_sample.Slug
reveal_type(Slug("a").upper())              # revealed: str
reveal_type(Email("a@b.co").lower())        # revealed: str
reveal_type(Email("a@b.co").domain)         # revealed: str
reveal_type(Port(80) + 1)                   # revealed: int
needs_str(Slug("a"))
needs_str(Email("a@b.co"))
needs_int(Port(80))
connect(Email("a@b.co"), Port(8080))
connect("a@b.co", 8080)                     # error


# ── checking without a decorator ─────────────────────────────────────────────

from enforced import enforce_class, typecheck_function        # noqa: E402

class Later:
    def deposit(self, amount: float) -> float:
        return amount


typecheck_function(plain, ("a",), {"name": "b"}, coerce = True, check_return = True)
reveal_type(enforce_class(Later, check_return = True))      # revealed: def () -> static_typing_sample.Later
reveal_type(enforce_class(Later)().deposit)                 # revealed: def (amount: float) -> float
typecheck_function(plain, "a")              # error
typecheck_function(plain, ("a",), {}, True) # error
enforce_class(plain)                        # error
enforce_class(Later, (1.0,))                # error


# ── a check in Annotated, marked ─────────────────────────────────────────────

from typing import Annotated                                    # noqa: E402
from enforced import Check                                      # noqa: E402

Even = Annotated[int, Check(lambda n: n % 2 == 0)]


@typecheck
def halve(n: Even) -> int:
    return n // 2


reveal_type(halve)                          # revealed: def (n: int) -> int
reveal_type(Check(str.isupper))             # revealed: _checks.Check
halve(4)
Check(5)                                    # error
halve("4")                                  # error


# ── protect, Ok and Err ──────────────────────────────────────────────────────

from enforced import Err, Ok, protect                           # noqa: E402

async def fetch() -> int:
    return 1


async def use() -> None:
    result = await protect(fetch())
    reveal_type(result)                     # revealed: Ok[int] | enforced.utils.Err
    match result:
        case Ok(value):
            reveal_type(value)              # revealed: int
        case Err(error):
            reveal_type(error)              # revealed: BaseException
    await protect(5)                        # error
    Err("text")                             # error
