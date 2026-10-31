from typing import Literal, Optional
from enforced import validate, dataclass, InvalidDataError
import pytest


def test_literal_in_union_accepts_the_other_members():
    """
    A Literal inside a union must not swallow the union's other members.
    Today the whole union is checked as "one of the literal values", so None, plain strs,
    ints and the like are rejected even though the annotation allows them.
    """
    #* The common case: an optional mode with a None default.
    @validate
    def open_file(mode: Optional[Literal["r", "w"]] = None) -> None: ...

    open_file()                                 # bug: InvalidDataError "in definition" (the None default)
    open_file(None)                             # bug: rejected
    open_file("r")

    #* Literal next to a plain type: any str must pass, not only the literal values.
    @validate
    def label(x: Literal[1] | str) -> None: ...

    label(1)
    label("hello")                              # bug: rejected

    #* Literal next to another class.
    @validate
    def level(x: Literal["auto"] | int) -> None: ...

    level("auto")
    level(5)                                    # bug: rejected

    #* The same inside collections (deep) and dataclass fields.
    @validate(deep = True)
    def modes(xs: list[Literal["r", "w"] | None]) -> None: ...

    modes(["r", None])                          # bug: None item rejected

    @dataclass
    class File:
        mode: Literal["r", "w"] | None = None   # bug: definition error on the default

    File()
    File("w")

    #* What must still be rejected: values outside every member.
    with pytest.raises(InvalidDataError):
        open_file("x")                          # not a literal value, not None
    with pytest.raises(InvalidDataError):
        label(2)                                # not 1, not a str
    with pytest.raises(InvalidDataError):
        level("manual")                         # not "auto", not an int
    with pytest.raises(InvalidDataError):
        modes(["x"])


def test_literal_union_details():
    #* Several Literals in one union are merged (the last one used to replace the others).
    @validate
    def pick(x: Literal["a"] | Literal["b"]) -> None: ...

    pick("a")
    pick("b")
    with pytest.raises(InvalidDataError):
        pick("c")

    #* The other members still convert; Literal values themselves are never produced by conversion.
    @validate
    def size(x: Literal["auto"] | float) -> float | str:
        return x

    assert size(2) == 2.0 and type(size(2)) is float
    assert size("auto") == "auto"

    #* Value and type must both match, as before: True is not Literal[1], but it isn't an int either.
    @validate
    def one(x: Literal[1] | str) -> None: ...

    with pytest.raises(InvalidDataError):
        one(True)

    #* Strict mode applies to the other members.
    class Name(str):
        pass

    @validate(allow_subclass = False)
    def strict(x: Literal["auto"] | str) -> None: ...

    strict("auto")
    strict("x")
    with pytest.raises(InvalidDataError):
        strict(Name("x"))

    #* Dataclass assignment, return values and nested Literal unions (deep).
    @dataclass
    class Job:
        mode: Literal["fast", "slow"] | None = None

    job = Job()
    job.mode = "slow"
    job.mode = None
    with pytest.raises(InvalidDataError):
        job.mode = "medium"

    @validate(check_return = True)
    def ret(x: object) -> Literal["ok"] | None:
        return x                                    # type: ignore[return-value]

    assert ret(None) is None and ret("ok") == "ok"
    with pytest.raises(InvalidDataError):
        ret("no")

    @validate(deep = True)
    def table(rows: dict[str, Literal["r", "w"] | int]) -> None: ...

    table({"a": "r", "b": 3})
    with pytest.raises(InvalidDataError) as exc:
        table({"a": "x"})
    assert [p.parameter for p in exc.value.problems] == ["rows['a']"]
