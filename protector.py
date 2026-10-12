from pyvalidate import dataclass
from typing import Awaitable


@dataclass(frozen = True)
class Ok[T]:
    value: T


@dataclass(frozen = True)
class Err:
    error: Exception


async def protect[T](coroutine: Awaitable[T]) -> Ok[T] | Err:
    """
    Protects an awaitable coroutine by catching any exceptions.

    Args:
        coroutine (Awaitable[T]): The coroutine to protect.

    Returns:
        Ok[T]: If the coroutine completes successfully.
        Err: If the coroutine raises an exception.

    Example:
        >>> from pyvalidate import protect, Ok, Err
        ... result = await protect(some_coroutine())
        ... match result:
        ...     case Ok():
        ...         print("Success:", value)
        ...     case Err():
        ...         print("Error:", error)
    """
    try:
        return Ok(await coroutine)
    except Exception as e:
        return Err(e)
