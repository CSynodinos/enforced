"""
What a static type checker makes of code that uses enforced. Not run: tests/test_static_typing.py
hands this file to mypy and compares what it reports with the comments here.

    # revealed: TEXT     the type mypy shows for the ``reveal_type`` on that line contains TEXT
    # error              mypy reports an error on that line (and on no line without this comment)
"""
import dataclasses
from dataclasses import KW_ONLY, InitVar, field
from typing import reveal_type
from enforced import dataclass, enforce, validate


# ── validate ────────────────────────────────────────────────────────────────

@validate
def plain(name: str) -> str:
    return name


@validate(check_return = True)
def with_options(name: str, times: int = 1) -> str:
    return name * times


@validate()
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

    @validate(coerce = True)
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


@validate
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


# ── Transform ────────────────────────────────────────────────────────────────

import io                                         # noqa: E402
from enforced import Transform                    # noqa: E402


class BufferFile(Transform[str, io.BytesIO]):       # the real generic class for a checker: it holds a BytesIO
    @classmethod
    def transform(cls, raw: str) -> io.BytesIO:
        return io.BytesIO(raw.encode())


@validate
def load(file: BufferFile) -> bytes:
    return file.value.read()


reveal_type(BufferFile("abc"))              # revealed: static_typing_sample.BufferFile
reveal_type(BufferFile("abc").value)        # revealed: _io.BytesIO
load(BufferFile("abc"))
load("abc")                                 # error
BufferFile(5)                               # error


# ── checking without a decorator ─────────────────────────────────────────────

from enforced import enforce_class, validate_function         # noqa: E402

class Later:
    def deposit(self, amount: float) -> float:
        return amount


validate_function(plain, ("a",), {"name": "b"}, coerce = True, check_return = True)
reveal_type(enforce_class(Later, check_return = True))      # revealed: def () -> static_typing_sample.Later
reveal_type(enforce_class(Later)().deposit)                 # revealed: def (amount: float) -> float
validate_function(plain, "a")               # error
validate_function(plain, ("a",), {}, True) # error
enforce_class(plain)                        # error
enforce_class(Later, (1.0,))                # error


# ── a check in Annotated, marked ─────────────────────────────────────────────

from typing import Annotated                                    # noqa: E402
from enforced import Check                                      # noqa: E402

Even = Annotated[int, Check(lambda n: n % 2 == 0)]


@validate
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


# ── the Enforced base class ──────────────────────────────────────────────────

from enforced import Enforced                                   # noqa: E402


class Ledger(Enforced, check_return = True, coerce = True):
    def __init__(self, owner: str) -> None:
        self.owner = owner

    def post(self, amount: float) -> float:
        return amount


class Branch(Ledger, deep = True):
    def code(self) -> str:
        return self.owner


reveal_type(Ledger("a").post)               # revealed: def (amount: float) -> float
reveal_type(Branch("a").code)               # revealed: def () -> str
reveal_type(Branch)                         # revealed: def (owner: str) -> static_typing_sample.Branch
Ledger(5)                                   # error
Branch("a").post("x")                       # error


class Misnamed(Enforced, on_error = "log"):  # error
    pass


# ── error = ...: a library's own error class ─────────────────────────────────

from enforced import InvalidDataError, enforce                  # noqa: E402


class SampleError(InvalidDataError):
    pass


@validate(error = SampleError)
def priced(amount: float) -> float:
    return amount


@dataclass(error = SampleError)
class Item:
    n: int


@enforce(error = SampleError)
class Counter:
    def add(self, n: int) -> int:
        return n


class Kept(Enforced, error = SampleError):
    pass


reveal_type(priced)                         # revealed: def (amount: float) -> float
reveal_type(Item(n = 1))                    # revealed: static_typing_sample.Item
reveal_type(Counter().add)                  # revealed: def (n: int) -> int


@validate(error = ValueError)               # error
def not_ours(x: int) -> int:
    return x


class NotOurs(Enforced, error = ValueError):  # error
    pass


from enforced import dispatch                                   # noqa: E402


@dispatch
def described(node: object, width: int = 0) -> str:
    return ""


@described.register
def described_int(node: int, width: int = 0) -> str:
    return "int"


reveal_type(described(5))                   # revealed: str
reveal_type(described_int)                  # revealed: def (node: int, width: int =) -> str
described(5, "wide")                        # error
described.register(list[int])(described_int)


@dispatch(error = ValueError)               # error
def described_wrongly(node: object) -> str:
    return ""


@enforce(check_assignment = False)
class Unwatched:
    x: int


class KeptLoose(Enforced, check_assignment = False):
    y: int


reveal_type(Unwatched())                    # revealed: static_typing_sample.Unwatched


@enforce(check_assignment = "no")           # error
class WrongOption:
    pass


from enforced import dispatchmethod                             # noqa: E402


class Shapes:
    @dispatchmethod
    def area(self, shape: object, scale: float = 1.0) -> float:
        return 0.0

    @area.register
    def area_of_int(self, shape: int, scale: float = 1.0) -> float:
        return shape * scale

    @dispatchmethod
    @classmethod
    def named(cls, shape: object) -> str:
        return cls.__name__

    @dispatchmethod(check_return = True)
    def checked(self, shape: object) -> bytes:
        return b""


reveal_type(Shapes().area(3))               # revealed: float
reveal_type(Shapes.area(Shapes(), 3))       # revealed: float
reveal_type(Shapes().named(3))              # revealed: str
reveal_type(Shapes.named(3))                # revealed: str
reveal_type(Shapes().checked(3))            # revealed: bytes
reveal_type(Shapes().area_of_int)           # revealed: def (shape: int, scale: float =) -> float
Shapes().area(3, "wide")                    # error


@enforce(False)                             # error
class PositionalOption:
    pass
