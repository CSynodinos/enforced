"""``protect``, the two results it returns (``Ok`` and ``Err``), and ``unwrap_protected``."""
from enforced import Err, Ok, InvalidDataError, protect, unwrap_protected
from typing import Any
import asyncio
import copy
import dataclasses
import inspect
import pickle
import re
import warnings
import pytest
import enforced


def _plain(e: BaseException) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e))


async def work(result: Any = "done", fail: BaseException | None = None) -> Any:
    await asyncio.sleep(0)
    if fail is not None:
        raise fail
    return result


# ── protect ──────────────────────────────────────────────────────────────────

def test_protect_returns_ok_with_the_result():
    assert asyncio.run(protect(work(5))) == Ok(5)
    assert asyncio.run(protect(work(None))) == Ok(None)                 # a result of None is a result
    made = [1, 2]
    assert asyncio.run(protect(work(made))).value is made               # the object itself, not a copy


def test_protect_returns_err_with_the_exception():
    error = ValueError("no")
    result = asyncio.run(protect(work(fail = error)))
    assert type(result) is Err and result.error is error
    assert result.error.__traceback__ is not None                       # where it was raised is kept


@pytest.mark.parametrize("error", [KeyError("k"), TypeError("t"), RuntimeError(), OSError(2, "gone"), ZeroDivisionError(),
                                   StopAsyncIteration(), InvalidDataError("checked")], ids = lambda e: type(e).__name__)
def test_protect_catches_every_kind_of_exception(error):
    assert asyncio.run(protect(work(fail = error))).error is error


@pytest.mark.parametrize("error", [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(3), GeneratorExit()],
                         ids = lambda e: type(e).__name__)
def test_protect_lets_through_what_is_no_error_of_the_work(error):
    #* Only Exception is caught. Cancellation above all: a task that swallowed it could not be cancelled.
    with pytest.raises(type(error)):
        asyncio.run(protect(work(fail = error)))


def test_a_protected_task_can_still_be_cancelled():
    async def main() -> str:
        task = asyncio.create_task(protect(asyncio.sleep(60)))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"
        return "swallowed"

    assert asyncio.run(main()) == "cancelled"


def test_protect_takes_anything_that_can_be_awaited():
    class Later:
        def __await__(self):
            yield from asyncio.sleep(0).__await__()
            return "later"

    async def main() -> list[Any]:
        future = asyncio.get_running_loop().create_future()
        future.set_result("future")
        failed = asyncio.get_running_loop().create_future()
        failed.set_exception(KeyError("k"))
        return [await protect(work("coroutine")), await protect(asyncio.create_task(work("task"))),
                await protect(future), await protect(Later()), await protect(asyncio.gather(work(1), work(2))),
                await protect(failed)]

    *fine, failed = asyncio.run(main())
    assert fine == [Ok("coroutine"), Ok("task"), Ok("future"), Ok("later"), Ok([1, 2])]
    assert type(failed) is Err and type(failed.error) is KeyError


@pytest.mark.parametrize("nothing", [5, None, "text", work, lambda: 1, [work()]], ids = ["int", "None", "str", "function", "lambda", "list"])
def test_what_cannot_be_awaited_is_refused_not_reported_as_a_failure(nothing):
    #* protect(work) without the call is a mistake in the program. It used to come back as
    #* Err(TypeError("'function' object can't be awaited")), as if the work had failed.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)                 # the coroutine inside the list is never awaited
        with pytest.raises(InvalidDataError) as e:
            asyncio.run(protect(nothing))
    assert "For parameter c of <Function protect>: expected type: 'collections.abc.Awaitable'" in _plain(e.value)


def test_protect_is_a_coroutine_function_and_keeps_what_it_is():
    assert inspect.iscoroutinefunction(protect) and protect.__name__ == "protect" and "Await ``coroutine``" in protect.__doc__
    assert list(inspect.signature(protect).parameters) == ["c"]
    pending = protect(work())
    assert inspect.iscoroutine(pending)
    assert asyncio.run(pending) == Ok("done")


def test_several_at_once():
    async def main() -> list[Any]:
        return await asyncio.gather(*(protect(work(n, ValueError(n) if n % 2 else None)) for n in range(6)))

    results = asyncio.run(main())
    assert [type(r) for r in results] == [Ok, Err] * 3 and [r.value for r in results[::2]] == [0, 2, 4]
    assert [r.error.args for r in results[1::2]] == [(1,), (3,), (5,)]


def test_match_statement():
    def read(result: Any) -> str:
        match result:
            case Ok(value):
                return f"ok {value}"
            case Err(error):
                return f"err {error}"
        return "neither"

    assert read(asyncio.run(protect(work(1)))) == "ok 1"
    assert read(asyncio.run(protect(work(fail = ValueError("bad"))))) == "err bad"
    assert Ok.__match_args__ == ("value",) and Err.__match_args__ == ("error",)


# ── Ok and Err ───────────────────────────────────────────────────────────────

def test_ok_holds_any_value():
    for value in (0, "", None, [], {"a": 1}, Ok(1), ValueError("a value like any other")):
        assert Ok(value).value is value
    assert Ok(value = 1) == Ok(1) and Ok[int](1) == Ok(1) and Ok[int]("not checked: T is a parameter").value
    with pytest.raises(TypeError, match = "missing 1 required positional argument"):
        Ok()                                                            # type: ignore[call-arg]


def test_err_holds_the_exception():
    for error in (ValueError("a"), KeyboardInterrupt(), asyncio.CancelledError(), InvalidDataError("t")):
        assert Err(error).error is error


def test_results_are_standard_dataclasses_and_check_nothing():
    #* A result is made on every call of protect, and holds what protect puts in: nothing to check.
    #* (They were checked dataclasses: 130 ns for Ok(1), and a __setattr__ of their own.)
    for cls in (Ok, Err):
        assert dataclasses.is_dataclass(cls) and "__enforced_dataclass__" not in vars(cls)
        assert cls.__dataclass_params__.frozen and not hasattr(cls.__init__, "__wrapped__")
    assert Err("a static type checker objects to this; nothing does at run time").error       # type: ignore[arg-type]


def test_results_are_frozen_dataclasses():
    ok, err = Ok(1), Err(ValueError("a"))
    assert dataclasses.is_dataclass(ok) and dataclasses.is_dataclass(err)
    for result, name in ((ok, "value"), (err, "error")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(result, name, 2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            delattr(result, name)
    assert repr(ok) == "Ok(value=1)" and repr(err) == "Err(error=ValueError('a'))"
    assert dataclasses.asdict(ok) == {"value": 1} and dataclasses.replace(ok, value = 2) == Ok(2)


def test_equality_and_hash():
    error = ValueError("a")
    assert Ok(1) == Ok(1) and Ok(1) != Ok(2) and Ok(1) != Err(error) and Ok(1) != 1
    assert Err(error) == Err(error) and Err(error) != Err(ValueError("a"))      # two exceptions are never equal
    assert hash(Ok(1)) == hash(Ok(1)) and {Ok(1), Ok(1), Err(error), Err(error)} == {Ok(1), Err(error)}
    with pytest.raises(TypeError, match = "unhashable"):
        hash(Ok([1]))


def test_results_copy_and_pickle():
    ok = Ok({"a": [1]})
    assert copy.copy(ok) == ok and copy.copy(ok).value is ok.value
    assert copy.deepcopy(ok) == ok and copy.deepcopy(ok).value is not ok.value
    assert pickle.loads(pickle.dumps(ok)) == ok
    back = pickle.loads(pickle.dumps(Err(KeyError("k"))))
    assert type(back) is Err and type(back.error) is KeyError and back.error.args == ("k",)


def test_the_package_offers_them():
    assert {"Ok", "Err", "protect", "unwrap_protected"} <= set(enforced.__all__)
    assert enforced.Ok is Ok and enforced.Err is Err and enforced.protect is protect
    assert enforced.unwrap_protected is unwrap_protected


# ── Err is generic in its exception (2026-11-16) ─────────────────────────────

def test_err_is_generic_in_its_exception_and_protect_says_which():
    import typing
    (parameter,) = Err.__type_params__
    assert parameter.__bound__ is BaseException
    assert Err[KeyError](KeyError("k")).error.args == ("k",)                 # subscripted, it is the same class
    returns = typing.get_type_hints(protect.__wrapped__)["return"]
    assert Err[Exception] in typing.get_args(returns)                       # what protect catches, and nothing more


# ── unwrap_protected ─────────────────────────────────────────────────────────

def test_unwrap_protected_gives_the_value_of_an_ok():
    made = [1, 2]
    assert unwrap_protected(Ok(made)) is made                               # the object itself
    for value in (0, "", None, False):                                     # a falsy value is a value
        assert unwrap_protected(Ok(value)) is value


def test_unwrap_protected_gives_the_exception_of_an_err_and_raises_nothing():
    error = ValueError("no")
    assert unwrap_protected(Err(error)) is error
    assert unwrap_protected(asyncio.run(protect(work(fail = error)))) is error
    assert unwrap_protected(asyncio.run(protect(work(5)))) == 5


def test_unwrap_protected_of_several_at_once():
    async def all_of() -> list[Any]:
        return [unwrap_protected(r) for r in await asyncio.gather(protect(work(1)), protect(work(fail = KeyError("k"))))]
    one, failed = asyncio.run(all_of())
    assert one == 1 and type(failed) is KeyError


@pytest.mark.parametrize("given", [5, None, "Ok", (1,), ValueError("not wrapped")], ids = repr)
def test_unwrap_protected_refuses_what_is_no_result(given):
    with pytest.raises(InvalidDataError) as caught:
        unwrap_protected(given)
    assert "For parameter result of <Function unwrap_protected>: expected type: 'Ok' | 'Err'" in _plain(caught.value)


def test_unwrap_protected_refuses_a_coroutine_that_was_not_awaited():
    #* The mistake the check is there for: matched against Ok and Err, it came back as None.
    inner = work()
    pending = protect(inner)
    try:
        with pytest.raises(InvalidDataError, match = "got type 'coroutine'"):
            unwrap_protected(pending)
    finally:
        pending.close()
        inner.close()                                                   # neither was started: no warning

