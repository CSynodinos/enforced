"""The general path of a wrapper: check, convert, call, check the result."""
from ._self_routing import elsewhere
from ._shared_names import INIT_ARGS_CODE_KEY, INIT_KWARGS_CODE_KEY
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ._checker import PreparedChecker


def make_fallback(
    checker: "PreparedChecker",
    check_return: bool,
    is_async: bool,
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    ) -> Callable[..., Any]:
    """
    The general path: full checks (with detailed errors), conversion, call, optional return check.

    What is called is ``checker.call``, read at each call: the first one may replace the function
    by a copy that has its converted defaults (see ``_prepare``).

    Where an annotation that is checked uses ``Self`` (``checker.self_in``: not 0, or not known
    yet), a call made on another class than this checker's goes to the wrapper for that class
    first (see ``elsewhere``).

    ``failed``, from a compiled wrapper: the parameter whose conversion it tried without success.
    """
    if mark is not None and not is_async:
        def marking_fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
            if checker.self_in != 0 and (other := elsewhere(checker, args, check_return, mark)) is not None:
                return other(*args, **kwargs)
            args, kwargs = checker.check_inputs(args, kwargs, failed)
            state = mark()
            if state is None:
                result = checker.call(*args, **kwargs)
            else:
                state[INIT_KWARGS_CODE_KEY], state[INIT_ARGS_CODE_KEY] = kwargs, args or NO_ARGS      # as checked (and converted)
                try:
                    result = checker.call(*args, **kwargs)
                finally:
                    state[INIT_ARGS_CODE_KEY], state[INIT_KWARGS_CODE_KEY] = NO_ARGS, NO_KWARGS
            return checker.check_return(result) if check_return else result
        return marking_fallback

    if is_async:
        async def async_fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
            if checker.self_in != 0 and (other := elsewhere(checker, args, check_return, mark)) is not None:
                return await other(*args, **kwargs)
            args, kwargs = checker.check_inputs(args, kwargs, failed)
            if checker.inject is not None:
                args, kwargs = checker.with_defaults(args, kwargs)
            result = await checker.call(*args, **kwargs)
            return checker.check_return(result) if check_return else result
        return async_fallback

    def fallback(args: tuple[Any, ...], kwargs: dict[str, Any], failed: str | None = None) -> Any:
        if checker.self_in != 0 and (other := elsewhere(checker, args, check_return, mark)) is not None:
            return other(*args, **kwargs)
        args, kwargs = checker.check_inputs(args, kwargs, failed)
        if checker.inject is not None:
            args, kwargs = checker.with_defaults(args, kwargs)
        result = checker.call(*args, **kwargs)
        return checker.check_return(result) if check_return else result
    return fallback


#* What a ``mark`` namespace holds while no call is running: a first argument that is no instance.
NO_ARGS: tuple[Any, ...] = (None,)
NO_KWARGS: dict[str, Any] = {}
