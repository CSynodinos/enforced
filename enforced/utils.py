from ._validator import validate
from dataclasses import dataclass
from typing import Awaitable


#* Standard dataclasses, not checked ones: a result is made on every call of `protect`, and there
#* is nothing in it to check. `Ok` holds whatever the awaitable returned, and `Err` what an
#* `except` clause caught, which is an exception by construction.
@dataclass(frozen = True)
class Ok[T]:
    """What `protect` returns for an awaitable that completed: its result, in `value`."""
    value: T


@dataclass(frozen = True)
class Err[T: BaseException]:
    """What `protect` returns for an awaitable that raised: the exception, in `error`."""
    error: T


#* Checked: handing over something that can't be awaited (`protect(fetch)` without the call) is a
#* mistake in the program. Awaited inside the `try` it came back as `Err(TypeError(...))`, looking
#* like a failure of the work itself.
@validate
async def protect[T](c: Awaitable[T]) -> Ok[T] | Err[Exception]:
    """
    Await `coroutine` and return what happened as a value, instead of letting an exception out.

    Args:
        c (Awaitable[T]): What to await: a coroutine, a task, a future.

    Returns:
        Ok[T] or Err[Exception]: Its result, in `.value`, if it completed or the exception, in `.error`, if it
        raised one. `Err[Exception]`, not `BaseException`: nothing else is caught, so a checker knows it too.

    Raises:
        InvalidDataError: If `coroutine` can't be awaited at all.

    Only `Exception` is caught. What is no error of the work itself goes through as ever:
    cancellation (`asyncio.CancelledError`), `KeyboardInterrupt`, `SystemExit`.

    Example:

        >>> from enforced import protect, Ok, Err
        ...
        ... match await protect(fetch(url)):
        ...    case Ok(value):
        ...        print("Success:", value)
        ...    case Err(error):
        ...        print("Error:", error)
    """
    try:
        return Ok(await c)
    except Exception as e:
        return Err(e)


#* Checked: a coroutine handed over unawaited (`unwrap_protected(protect(work()))`) matches neither
#* case, and without the check it came back as None, silently.
@validate
def unwrap_protected[T, E: BaseException](result: Ok[T] | Err[E]) -> T | E:
    """
    What a result of `protect` holds: the value of an `Ok`, or the exception of an `Err`.

    The exception is returned, not raised: a caller that wants to tell the two apart uses `match`
    on the result itself (or `isinstance(x, BaseException)` on what this returns).

    Use this utility for simple result extraction.

    Args:
        result (Ok[T] or Err[E]): What `protect` returned.

    Returns:
        T or E: `result.value` for an `Ok`, `result.error` for an `Err`.

    Raises:
        InvalidDataError: If `result` is neither an `Ok` nor an `Err`.

    Example:

        >>> from enforced import protect, unwrap_protected
        ...
        ... print(
        ...    unwrap_protected(
        ...        await protect(fetch(url))
        ...        )
        ...    )
        ...
        ... boilerplate for:
        ... match await protect(fetch(url)):
        ...    case Ok(value):
        ...        print(value.value)  # res of fetch(url)
        ...    case Err(error):
        ...        print(error.error)  # exception from fetch(url)
    """
    match result:
        case Ok(value):
            return value
        case Err(error):
            return error
