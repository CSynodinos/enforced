from ._typechecker import typecheck
from dataclasses import dataclass
from typing import Awaitable


#* Standard dataclasses, not checked ones: a result is made on every call of ``protect``, and there
#* is nothing in it to check. ``Ok`` holds whatever the awaitable returned, and ``Err`` what an
#* ``except`` clause caught, which is an exception by construction.
@dataclass(frozen = True)
class Ok[T]:
    """What ``protect`` returns for an awaitable that completed: its result, in ``value``."""
    value: T


@dataclass(frozen = True)
class Err:
    """What ``protect`` returns for an awaitable that raised: the exception, in ``error``."""
    error: BaseException


#* Checked: handing over something that can't be awaited (``protect(fetch)`` without the call) is a
#* mistake in the program. Awaited inside the ``try`` it came back as ``Err(TypeError(...))``, looking
#* like a failure of the work itself.
@typecheck
async def protect[T](c: Awaitable[T]) -> Ok[T] | Err:
    """
    Await ``coroutine`` and return what happened as a value, instead of letting an exception out.

    Args:
        c (Awaitable[T]): What to await: a coroutine, a task, a future.

    Returns:
        Ok[T] or Err: Its result, in ``.value``, if it completed or the exception, in ``.error``, if it raised one.

    Raises:
        TypeCheckerError: If ``coroutine`` can't be awaited at all.

    Only ``Exception`` is caught. What is no error of the work itself goes through as ever:
    cancellation (``asyncio.CancelledError``), ``KeyboardInterrupt``, ``SystemExit``.

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
