"""The compiled tier: source generated for one signature shape, and the code objects of a wrapper."""
from ._container import datetime_class
from ._general_path import NO_ARGS, NO_KWARGS
from ._lifetime import CACHE_LOCK
from ._self_routing import return_router
from ._shared_names import FUNCTION_CODE_KEY
from ._type_conversion import FAILED
from typing import Any, Callable, TYPE_CHECKING
from types import CodeType, FunctionType
import inspect


if TYPE_CHECKING:
    from ._checker import PreparedChecker


#* What `_pv_MISSING` is in generated code: a parameter the call didn't pass.
MISSING = object()
SPACE = " "
#* The indentation of generated code, one name per nesting level (4 spaces each), so that the depth of a
#* line reads at a glance: `_INDENT_2` is two levels in, the body of an `if` inside the wrapper.
_INDENT_1 = SPACE * 4
_INDENT_2 = SPACE * 8
_INDENT_3 = SPACE * 12
_INDENT_4 = SPACE * 16


#* source -> (code object, source) (for a generator function: (source, its kind) -> ...). Like the other
#* two annotation caches, it lets its oldest entry go when it is full.
#* Reads take no lock; inserting and evicting do.
#* The source is kept with the code so that every wrapper of a shape holds that one string as its
#* `__enforced_source__` (about 6 KB for five parameters), not a copy of its own.
_CODE_CACHE: dict[Any, tuple[CodeType, str]] = {}
_CODE_CACHE_MAX = 2048


class _WrapperWriter:
    """
    Writes the lines of one wrapper. Holds what every part of it needs: the checker, the
    namespace the generated code reads its names from, how a call is made and its result checked,
    the jump to the fallback, and the parameters tested against the class of the call. Every line
    after the first two is written by its methods, in this order: `emit_self_class_setup`, then the two
    lanes, `emit_fast_args_only_lane` and `emit_general_binding_lane` for every call the first didn't take.
    `str()` of it is the source written so far.
    """
    __slots__ = (
        "lines",
        "checker", "namespace", "setattr_globals",
        "return_test", "return_failed", "await_prefix",
        "to_fallback", "by_instance", "self_tested"
        )

    def __init__(
        self,
        lines: list[str],
        checker: "PreparedChecker",
        namespace: dict[str, Any],
        setattr_globals: dict[str, Any] | None,
        return_test: str | None,
        return_failed: str,
        await_prefix: str,
        to_fallback: str,
        by_instance: bool,
        self_tested: list[str],
        ) -> None:
        """
        Args:
            lines (list[str]): The source written so far; the writer appends to it.
            checker (PreparedChecker): The checker of the function: its specs, converters and `inject`.
            namespace (dict[str, Any]): The wrapper's globals. Every value the code needs is put here
                under a `_pv_` name, never written into the source.
            setattr_globals (dict[str, Any] | None): The globals of a dataclass's generated `__setattr__`,
                where the checked arguments are put while `__init__` runs (see `wrap_callable`'s `mark`);
                None for anything else.
            return_test (str | None): The inline test of `_pv_result`, or None when the return value isn't checked.
            return_failed (str): What a call returns when `return_test` fails: `_pv_return_failed(...)`,
                or `_pv_return_router(...)` for a `-> Self` tested against the class of the call.
            await_prefix (str): `"await "` for a coroutine function, else `""`.
            to_fallback (str): The statement that hands the whole call to the general path.
            by_instance (bool): The `Self` tests are written against `_pv_call_class` (see `generate_wrapper`).
            self_tested (list[str]): The parameters (and `"return"`) whose annotation uses `Self`.
        """
        self.lines = lines
        self.checker = checker
        self.namespace = namespace
        self.setattr_globals = setattr_globals
        self.return_test = return_test
        self.return_failed = return_failed
        self.await_prefix = await_prefix
        self.to_fallback = to_fallback
        self.by_instance = by_instance
        self.self_tested = self_tested
        return

    def __str__(self) -> str:
        """The source: the lines written so far, one per line."""
        return "\n".join(self.lines)

    def _append(self, line: str) -> None:
        """Add one line of source."""
        self.lines.append(line)
        return

    def _emit_call(self, indent: str, call: str, args: str = "_pv_args", kwargs: str | None = "_pv_kwargs") -> None:
        """
        Write the call of the function and what is returned: the result as it is, the result once
        `return_test` passes it, or the call inside the dataclass handshake (`setattr_globals`).

        Args:
            indent (str): The indentation of the lines.
            call (str): The call expression, `_pv_function(...)`.
            args (str): Source for the positional arguments `call` passes, put into `setattr_globals`.
            kwargs (str | None): Source for the keyword arguments `call` passes, or None when it passes none.
        """
        if self.setattr_globals is not None:
            if kwargs is None:
                self._append(f"{indent}_pv_setattr_globals['_pv_init_args'] = {args}")
                self._append(f"{indent}try: return {call}")
                self._append(f"{indent}finally: _pv_setattr_globals['_pv_init_args'] = _pv_NO_ARGS")
            else:
                self._append(f"{indent}_pv_setattr_globals['_pv_init_kwargs'] = {kwargs}; _pv_setattr_globals['_pv_init_args'] = {args} or _pv_NO_ARGS")
                self._append(f"{indent}try: return {call}")
                self._append(f"{indent}finally: _pv_setattr_globals['_pv_init_args'] = _pv_NO_ARGS; _pv_setattr_globals['_pv_init_kwargs'] = _pv_NO_KWARGS")
            return
        if self.return_test is None:
            self._append(f"{indent}return {self.await_prefix}{call}")
            return
        self._append(f"{indent}_pv_result = {self.await_prefix}{call}")
        self._append(f"{indent}if {self.return_test}: return _pv_result")
        self._append(f"{indent}return {self.return_failed}")            # converts, or raises the detailed error
        return

    def _emit_check(self, indent: str, test: str | None) -> None:
        """Write `test`, with the whole call handed to the fallback when it fails (nothing when `test` is None)."""
        if test is not None:
            self._append(f"{indent}if not ({test}): {self.to_fallback}")
        return

    def _emit_value_check(
        self,
        indent: str,
        test: str | None,
        variable: str,
        name: str,
        suffix: str,
        on_converted: str,
        handed_on: tuple[str, str] = ("_pv_args", "_pv_kwargs"),
        ) -> None:
        """
        Write the test of one parameter's value. If it fails and the parameter has a converter, the
        value is converted inline and `on_converted` runs; otherwise the call goes to the fallback,
        which is told the parameter's name, so it doesn't run that test or conversion again.

        Args:
            indent (str): The indentation of the lines.
            test (str | None): The inline test of `variable`, or None when anything passes.
            variable (str): The local that holds the value (`_pv_arg_0`, `_pv_kwonly_0`).
            name (str): The parameter's name, the key of its converter.
            suffix (str): What the namespace names of this parameter end with (`0`, `k0`).
            on_converted (str): The statement that records a converted value.
            handed_on (tuple[str, str]): Source for the call as the general path is to receive it when
                `variable` fails, with what this wrapper has converted so far in place of the originals.
                Given the originals, the general path converted each of them a second time (a wrong call
                of a dataclass converted its other fields twice).
        """
        converter = self.checker.converters.get(name)
        if test is None:
            return
        handed_args = f"{handed_on[0]}, {handed_on[1]}"
        if converter is None:
            #* The general path is told which parameter failed its test and doesn't run it again:
            #* for `Annotated[int, check]` that is the user's check. Not for
            #* a parameter tested against the class of the call (`Self`): that test is this wrapper's own.
            if self.by_instance and name in self.self_tested:
                self._emit_check(indent, test)
            else:
                self.namespace[f"_pv_failed_param_{suffix}"] = name
                self._append(f"{indent}if not ({test}): return {self.await_prefix}_pv_fallback({handed_args}, _pv_failed_param_{suffix})")
            return
        #* The general path is told which parameter's conversion has just failed, and doesn't
        #* try it again: for a TypeModel that is the user's `clean`, run twice per wrong call.
        self.namespace[f"_pv_converter_{suffix}"], self.namespace[f"_pv_failed_param_{suffix}"] = converter, name
        self._append(f"{indent}if not ({test}):")
        self._append(f"{indent}{_INDENT_1}{variable} = _pv_converter_{suffix}({variable})")
        self._append(f"{indent}{_INDENT_1}if {variable} is _pv_FAILED: return {self.await_prefix}_pv_fallback({handed_args}, _pv_failed_param_{suffix})")
        self._append(f"{indent}{_INDENT_1}{on_converted}")
        return

    def emit_self_class_setup(self, by_class: bool) -> None:
        """
        The lines that get the class of the call into a method whose checked annotations use `Self`
        (see `_self_testing`); nothing for any other function.

        - `by_instance`: the class of the first argument is `_pv_call_class`, for the tests written
            against it. What stands in the place of `self` has to be an instance of the class at all:
            anything else is left to the general path.
        - `by_class`: this code is for `_pv_compiled_for`. A call made on another class goes to the
            wrapper for that class, straight from the family when it has been met before, else through
            the fallback, which makes one. The family knows a class by its id and holds its wrapper
            weakly (see `_route`).
        """
        checker, to_fallback = self.checker, self.to_fallback
        if self.by_instance:
            self.namespace["_pv_owner"] = checker.owner
            self._append(f"{_INDENT_1}if not _pv_n_args: {to_fallback}")
            self._append(f"{_INDENT_1}_pv_call_class = type(_pv_args[0])")
            self._append(f"{_INDENT_1}if _pv_call_class is not _pv_owner and not isinstance(_pv_args[0], _pv_owner): {to_fallback}")
        elif by_class:
            with CACHE_LOCK:
                if checker.family is None:
                    checker.family = {}
            self.namespace["_pv_compiled_for"], self.namespace["_pv_family"] = checker.me or checker.owner, checker.family
            called_on = "_pv_args[0]" if checker.class_first else "type(_pv_args[0])"
            self._append(f"{_INDENT_1}if _pv_n_args and {called_on} is not _pv_compiled_for:")
            self._append(f"{_INDENT_2}_pv_routed = _pv_family.get(id({called_on}))")
            self._append(f"{_INDENT_2}if _pv_routed is not None:")
            self._append(f"{_INDENT_3}_pv_routed = _pv_routed()")
            self._append(f"{_INDENT_3}if _pv_routed is not None: return {self.await_prefix}_pv_routed(*_pv_args, **_pv_kwargs)")
            self._append(f"{_INDENT_2}{to_fallback}")
        return

    def emit_fast_args_only_lane(
        self,
        positional: "list[inspect.Parameter]",
        positional_tests: list[str | None],
        var_pos: "inspect.Parameter | None",
        var_pos_test: str | None,
        var_pos_tuple_test: str | None,
        ) -> None:
        """
        The fast lane: every positional parameter passed positionally, no keywords at all. Each
        argument is tested (and converted) where it stands; a call it doesn't take falls through to
        the general lane, written after it. Converted keyword-only defaults the function can't hold
        (`PreparedChecker.inject`) are passed as `**_pv_kwonly_defaults`: this lane passes no keyword,
        so all of them, at once.

        Args:
            positional (list[inspect.Parameter]): The positional parameters, in order.
            positional_tests (list[str | None]): The test of each, or None where anything passes.
            var_pos (inspect.Parameter | None): The `*args` parameter, if any.
            var_pos_test (str | None): The test of each extra positional argument.
            var_pos_tuple_test (str | None): The test of the extra positional arguments as one tuple
                (`*args: *tuple[...]`).
        """
        injected = self.checker.inject or {}
        kwonly_default_args = ""
        kwonly_injected = {
            p.name: injected[p.name] for p in self.checker.sig.parameters.values()
            if p.kind is inspect.Parameter.KEYWORD_ONLY and p.name in injected
            }
        if kwonly_injected:
            self.namespace["_pv_kwonly_defaults"] = kwonly_injected
            kwonly_default_args = ", **_pv_kwonly_defaults"
        n_positional = len(positional)
        arity_test = f"_pv_n_args >= {n_positional}" if var_pos else f"_pv_n_args == {n_positional}"
        self._append(f"{_INDENT_1}if not _pv_kwargs and {arity_test}:")
        if n_positional:
            unpacked_names = ", ".join(f"_pv_arg_{i}" for i in range(n_positional))
            unpacked_from = "_pv_args" if not var_pos else f"_pv_args[:{n_positional}]"
            self._append(f"{_INDENT_2}{unpacked_names}, = {unpacked_from}")

        converting = [positional_tests[i] is not None and p.name in self.checker.converters for i, p in enumerate(positional)]
        if any(converting):
            self._append(f"{_INDENT_2}_pv_any_converted = False")
        for i, (p, test) in enumerate(zip(positional, positional_tests)):
            #* What was converted before this one: its local, the rest as given.
            converted_so_far = (f"({''.join(f'_pv_arg_{k}, ' for k in range(i))}*_pv_args[{i}:])", "_pv_kwargs") if any(converting[:i]) else ("_pv_args", "_pv_kwargs")
            self._emit_value_check(
                indent = _INDENT_2,
                test = test,
                variable = f"_pv_arg_{i}",
                name = p.name,
                suffix = str(i),
                on_converted = "_pv_any_converted = True",
                handed_on = converted_so_far,
                )

        if var_pos and var_pos_test:
            self._append(f"{_INDENT_2}for _pv_extra in _pv_args[{n_positional}:]:")
            self._emit_check(_INDENT_3, var_pos_test)
        self._emit_check(_INDENT_2, var_pos_tuple_test)

        if any(converting):
            extra_positional = f", *_pv_args[{n_positional}:]" if var_pos else ""
            self._append(f"{_INDENT_2}if _pv_any_converted:")
            passed = "".join(f"_pv_arg_{i}, " for i in range(n_positional)) + (f"*_pv_args[{n_positional}:]" if var_pos else "")
            self._emit_call(
                indent = _INDENT_3,
                call = f"_pv_function({', '.join(f'_pv_arg_{i}' for i in range(n_positional))}{extra_positional}{kwonly_default_args})",
                args = f"({passed})" if n_positional else "_pv_args",
                kwargs = None,
                )
        self._emit_call(
            indent = _INDENT_2,
            call = f"_pv_function(*_pv_args{kwonly_default_args})",
            args = "_pv_args" if n_positional else "(_pv_args or _pv_NO_ARGS)",
            kwargs = None,
            )

        return

    def emit_general_binding_lane(
        self,
        params: "list[inspect.Parameter]",
        positional: "list[inspect.Parameter]",
        positional_tests: list[str | None],
        kw_only: "list[inspect.Parameter]",
        kwonly_tests: list[str | None],
        var_pos: "inspect.Parameter | None",
        var_pos_test: str | None,
        var_kw: "inspect.Parameter | None",
        var_kw_test: str | None,
        var_pos_tuple_test: str | None,
        ) -> None:
        """
        The general lane: any mix of positional and keyword arguments, bound with straight-line code.
        A default the function can't hold (`PreparedChecker.inject`) is passed where the call leaves
        its parameter out.

        Args:
            params (list[inspect.Parameter]): Every parameter of the checker's signature.
            positional (list[inspect.Parameter]): The positional parameters, in order.
            positional_tests (list[str | None]): The test of each, or None where anything passes.
            kw_only (list[inspect.Parameter]): The keyword-only parameters, in order.
            kwonly_tests (list[str | None]): The test of each, or None where anything passes.
            var_pos (inspect.Parameter | None): The `*args` parameter, if any.
            var_pos_test (str | None): The test of each extra positional argument.
            var_kw (inspect.Parameter | None): The `**kwargs` parameter, if any.
            var_kw_test (str | None): The test of each extra keyword argument.
            var_pos_tuple_test (str | None): The test of the extra positional arguments as one tuple
                (`*args: *tuple[...]`).
        """

        Parameter = inspect.Parameter
        checker, namespace, to_fallback = self.checker, self.namespace, self.to_fallback
        injected = checker.inject or {}
        n_positional = len(positional)
        if not var_pos:
            self._append(f"{_INDENT_1}if _pv_n_args > {n_positional}: {to_fallback}")
        self._append(f"{_INDENT_1}_pv_kwargs_used = 0")
        may_convert = bool(injected) or any(p.name in checker.converters for p in positional + kw_only)
        if may_convert:
            self._append(f"{_INDENT_1}_pv_converted_args = _pv_converted_kwargs = None")         # converted copies of args / kwargs, made on demand
        store_converted_arg = lambda i, variable: f"_pv_converted_args = list(_pv_args) if _pv_converted_args is None else _pv_converted_args; _pv_converted_args[{i}] = {variable}"
        store_converted_kwarg = lambda key, variable: f"_pv_converted_kwargs = dict(_pv_kwargs) if _pv_converted_kwargs is None else _pv_converted_kwargs; _pv_converted_kwargs[{key}] = {variable}"

        #* The call as converted so far, for the general path (see `emit_value_check`).
        converted_so_far = (
            ("(_pv_args if _pv_converted_args is None else tuple(_pv_converted_args))", "(_pv_kwargs if _pv_converted_kwargs is None else _pv_converted_kwargs)")
            if may_convert else ("_pv_args", "_pv_kwargs")
            )
        for i, p in enumerate(positional):
            required = p.default is Parameter.empty
            self._append(f"{_INDENT_1}if _pv_n_args > {i}:")
            if p.kind is Parameter.POSITIONAL_OR_KEYWORD:
                namespace[f"_pv_param_name_{i}"] = p.name
                self._append(f"{_INDENT_2}if _pv_param_name_{i} in _pv_kwargs: {to_fallback}")   # duplicate binding
            self._append(f"{_INDENT_2}_pv_arg_{i} = _pv_args[{i}]")
            self._emit_value_check(
                indent = _INDENT_2,
                test = positional_tests[i],
                variable = f"_pv_arg_{i}",
                name = p.name,
                suffix = str(i),
                on_converted = store_converted_arg(i, f"_pv_arg_{i}"),
                handed_on = converted_so_far,
                )
            if p.kind is Parameter.POSITIONAL_ONLY:
                if required or p.name in injected:            # a default to pass by position: left to the fallback
                    self._append(f"{_INDENT_1}else: {to_fallback}")
                continue
            self._append(f"{_INDENT_1}else:")
            self._append(f"{_INDENT_2}_pv_arg_{i} = _pv_kwargs.get(_pv_param_name_{i}, _pv_MISSING)")
            self._append(f"{_INDENT_2}if _pv_arg_{i} is _pv_MISSING:")
            if p.name in injected:
                namespace[f"_pv_default_{i}"] = injected[p.name]
                self._append(f"{_INDENT_3}{store_converted_kwarg(f'_pv_param_name_{i}', f'_pv_default_{i}')}")
            else:
                self._append(f"{_INDENT_3}{to_fallback}" if required else f"{_INDENT_3}pass")
            self._append(f"{_INDENT_2}else:")
            self._append(f"{_INDENT_3}_pv_kwargs_used += 1")
            self._emit_value_check(
                indent = _INDENT_3,
                test = positional_tests[i],
                variable = f"_pv_arg_{i}",
                name = p.name,
                suffix = str(i),
                on_converted = store_converted_kwarg(f"_pv_param_name_{i}", f"_pv_arg_{i}"),
                handed_on = converted_so_far,
                )
        for j, p in enumerate(kw_only):
            variable = f"_pv_kwonly_{j}"
            namespace[f"_pv_kwonly_name_{j}"] = p.name
            self._append(f"{_INDENT_1}{variable} = _pv_kwargs.get(_pv_kwonly_name_{j}, _pv_MISSING)")
            self._append(f"{_INDENT_1}if {variable} is _pv_MISSING:")
            if p.name in injected:
                namespace[f"_pv_kwonly_default_{j}"] = injected[p.name]
                self._append(f"{_INDENT_2}{store_converted_kwarg(f'_pv_kwonly_name_{j}', f'_pv_kwonly_default_{j}')}")
            else:
                self._append(f"{_INDENT_2}{to_fallback}" if p.default is Parameter.empty else f"{_INDENT_2}pass")
            self._append(f"{_INDENT_1}else:")
            self._append(f"{_INDENT_2}_pv_kwargs_used += 1")
            self._emit_value_check(
                indent = _INDENT_2,
                test = kwonly_tests[j],
                variable = variable,
                name = p.name,
                suffix = f"k{j}",
                on_converted = store_converted_kwarg(f"_pv_kwonly_name_{j}", variable),
                handed_on = converted_so_far,
                )
        if var_pos and var_pos_test:
            self._append(f"{_INDENT_1}for _pv_extra in _pv_args[{n_positional}:]:")
            self._emit_check(_INDENT_2, var_pos_test)
        self._emit_check(_INDENT_1, var_pos_tuple_test)
        self._append(f"{_INDENT_1}if _pv_kwargs_used != len(_pv_kwargs):")
        if var_kw is None:
            self._append(f"{_INDENT_2}{to_fallback}")         # unknown keyword
        elif var_kw_test is not None:
            namespace["_pv_named_params"] = frozenset(p.name for p in params if p.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY))
            self._append(f"{_INDENT_2}for _pv_extra_name, _pv_extra in _pv_kwargs.items():")
            self._append(f"{_INDENT_3}if _pv_extra_name not in _pv_named_params:")
            self._emit_check(_INDENT_4, var_kw_test)
        else:
            self._append(f"{_INDENT_2}pass")
        if may_convert:
            self._append(f"{_INDENT_1}if _pv_converted_args is not None or _pv_converted_kwargs is not None:")
            self._emit_call(
                indent = _INDENT_2,
                call = "_pv_function(*(_pv_args if _pv_converted_args is None else _pv_converted_args), **(_pv_kwargs if _pv_converted_kwargs is None else _pv_converted_kwargs))",
                args = "(_pv_args if _pv_converted_args is None else _pv_converted_args)",
                kwargs = "(_pv_kwargs if _pv_converted_kwargs is None else _pv_converted_kwargs)",
                )
        self._emit_call(indent = _INDENT_1, call = "_pv_function(*_pv_args, **_pv_kwargs)")

        return


def generate_wrapper(
    checker: "PreparedChecker",
    check_return: bool,
    is_async: bool,
    namespace: dict[str, Any],
    fallback: Callable[..., Any],
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    kind: int = 0,
    ) -> tuple[CodeType, str]:
    """
    Write the source of a wrapper specialised to the shape of `checker.sig`, and compile it (or take
    the code of the same source from `_CODE_CACHE`).

    The generated code only decides "definitely fine" and then calls the function: it binds
    arguments with straight-line code and inlines one test per parameter. Any doubt (wrong type,
    missing or duplicate argument, unknown keyword, a conversion that failed) jumps to the fallback,
    which converts what it can and raises the detailed error for the rest. CODEGEN.md describes
    the source it writes.

    Args:
        checker (PreparedChecker): The checker of the function, prepared (`checker.ready`).
        check_return (bool): Whether the return value is checked.
        is_async (bool): Whether the function is a coroutine function: the wrapper is then one too.
        namespace (dict[str, Any]): The wrapper's globals. The names the code reads are put here.
        fallback (Callable[..., Any]): The general path, `make_fallback(checker, check_return, is_async, mark)`:
            the one the wrapper's first calls took.
        mark (Callable[[], dict[str, Any] | None] | None): For a dataclass `__init__`: returns the globals of
            the generated `__setattr__`, where the checked arguments are put while `__init__` runs
            (see `wrap_callable`). None for anything else.
        kind (int): The `function_kind` of the function. The code carries a generator flag where that is
            harmless (`_FLAGGED`, see `_stub_codes`); any other kind is ignored here.

    Returns:
        tuple[CodeType, str]: The code object of `_pv_wrapper`, and its source (the cache's string,
        shared by every wrapper of the same shape).
    """
    Parameter = inspect.Parameter
    namespace.update({
        FUNCTION_CODE_KEY: checker.call,
        "_pv_fallback": fallback,
        "_pv_return_failed": checker.check_return,
        "_pv_MISSING": MISSING,
        "_pv_FAILED": FAILED,
        })
    await_prefix = "await " if is_async else ""
    to_fallback = f"return {await_prefix}_pv_fallback(_pv_args, _pv_kwargs)"
    _asy_prefix = 'async ' if is_async else ''
    lines = [
        f"{_asy_prefix}def _pv_wrapper(*_pv_args, **_pv_kwargs):",
        f"{_INDENT_1}_pv_n_args = len(_pv_args)",
        ]

    self_tested, by_instance, by_class = _self_testing(checker, check_return)
    return_test, return_failed = _return_check(
        checker = checker,
        check_return = check_return,
        by_instance = by_instance,
        self_tested = self_tested,
        namespace = namespace,
        mark = mark,
        )

    #* A dataclass __init__ whose __setattr__ skips re-checking what was checked here (see `mark`
    #* in wrap_callable). Two dict stores per call, and only for classes that asked for it.
    setattr_globals = mark() if mark is not None and not is_async and return_test is None else None
    if setattr_globals is not None:
        namespace.update({"_pv_setattr_globals": setattr_globals, "_pv_NO_ARGS": NO_ARGS, "_pv_NO_KWARGS": NO_KWARGS})

    #* Break down the signature into its structural parts for targeted test generation.
    params = list(checker.sig.parameters.values())
    positional = [p for p in params if p.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)]
    kw_only = [p for p in params if p.kind is Parameter.KEYWORD_ONLY]
    var_pos = next((p for p in params if p.kind is Parameter.VAR_POSITIONAL), None)
    var_kw = next((p for p in params if p.kind is Parameter.VAR_KEYWORD), None)

    #* `*args: *tuple[int, str]`: the extra positional arguments are tested as one tuple.
    var_pos_tuple_test = None
    if var_pos is not None and checker.var_pos_node is not None:
        namespace["_pv_check_var_args"] = checker.var_pos_node.check
        var_pos_tuple_test = f"_pv_check_var_args(_pv_args[{len(positional)}:])"

    def test_for(p: inspect.Parameter, variable: str, suffix: object) -> str | None:
        """The inline test of parameter `p`'s value in `variable`, or None when anything passes."""
        if by_instance and p.name in self_tested:
            return _self_test(checker, p.name, variable)
        spec = checker.specs.get(p.name)
        return None if spec is None else check_expr(spec, variable, namespace, str(suffix))

    positional_tests = [test_for(p, f"_pv_arg_{i}", i) for i, p in enumerate(positional)]
    var_pos_test = test_for(var_pos, "_pv_extra", "vp") if var_pos else None
    var_kw_test = test_for(var_kw, "_pv_extra", "vk") if var_kw else None
    kwonly_tests = [test_for(p, f"_pv_kwonly_{j}", f"k{j}") for j, p in enumerate(kw_only)]

    #* Inline test expressions for each parameter kind, parallel to their parameter lists. A `None`
    #* entry means no annotation or an annotation that always passes (e.g. `Any`), so no check is emitted.
    #* `_WrapperWriter` accumulates source lines and owns all the context needed to emit each structural
    #* section of the wrapper: the `Self` class setup, the fast positional lane (no kwargs, no binding), and the
    #* general binding lane (any mix of arguments, bound with straight-line code). It writes directly into `lines` and resolves
    #* runtime references through `namespace`.
    writer = _WrapperWriter(
        lines = lines,
        checker = checker,
        namespace = namespace,
        setattr_globals = setattr_globals,
        return_test = return_test,
        return_failed = return_failed,
        await_prefix = await_prefix,
        to_fallback = to_fallback,
        by_instance = by_instance,
        self_tested = self_tested,
        )
    writer.emit_self_class_setup(by_class)
    if not any(p.default is Parameter.empty for p in kw_only):    # a required keyword-only parameter: no fast lane
        writer.emit_fast_args_only_lane(
            positional = positional,
            positional_tests = positional_tests,
            var_pos = var_pos,
            var_pos_test = var_pos_test,
            var_pos_tuple_test = var_pos_tuple_test,
            )
    writer.emit_general_binding_lane(
        params = params,
        positional = positional,
        positional_tests = positional_tests,
        kw_only = kw_only,
        kwonly_tests = kwonly_tests,
        var_pos = var_pos,
        var_pos_test = var_pos_test,
        var_kw = var_kw,
        var_kw_test = var_kw_test,
        var_pos_tuple_test = var_pos_tuple_test,
        )

    return _generate_codetype_from_source(src = str(writer), kind = kind)


def _self_testing(checker: "PreparedChecker", check_return: bool) -> tuple[list[str], bool, bool]:
    """
    Which checked annotations of a method use `Self` (see `_route`), and how the class of the call gets
    into a check that was compiled once:

    - `by_instance`: every such annotation is `Self` itself, tested by nothing but the class. The test
        is then written against the class of the first argument, and one wrapper serves every class:
        `isinstance(other, type(self))`.
    - `by_class` (`Self | None`, `list[Self]`, a class method ...): this code is for one class,
        `_pv_compiled_for`, and a call made on another goes to the wrapper for that class.

    Returns:
        tuple[list[str], bool, bool]: The names that use `Self` and are checked (`"return"` among them under `check_return`), `by_instance`, `by_class`.
            Both are `False` where no name uses `Self`.
    """
    compiled_for = checker.me or checker.owner
    self_uses = checker.self_uses or {}
    checks_return = check_return and checker.ret_spec is not None
    self_tested = [name for name in self_uses if name != "return" or checks_return]

    def plain_self(name: str) -> bool:
        """Whether `name` (or `"return"`) is tested by the class alone: `Self` itself, no converter, a spec of `compiled_for`."""
        spec = checker.ret_spec if name == "return" else checker.specs.get(name)
        converted = (
            name in checker.converters \
                or (name == checker.var_pos and checker.var_pos_conv is not None) \
                or (name == checker.var_kw and checker.var_kw_conv is not None)
                )
        return bool(self_uses[name]) and not converted and spec is not None and spec[0] in ("isinstance", "is") and spec[1] is compiled_for

    by_instance = bool(self_tested) and not checker.class_first and all(plain_self(name) for name in self_tested)
    return self_tested, by_instance, bool(self_tested) and not by_instance


def _self_test(checker: "PreparedChecker", name: str, variable: str) -> str:
    """The test of `variable` against the class of this call (`_pv_call_class`), as the spec of `name` tests its own class."""
    strict = (checker.ret_spec if name == "return" else checker.specs[name])[0] == "is"     # type: ignore[index]
    return f"type({variable}) is _pv_call_class" if strict else f"isinstance({variable}, _pv_call_class)"


def _return_check(
    checker: "PreparedChecker",
    check_return: bool,
    by_instance: bool,
    self_tested: list[str],
    namespace: dict[str, Any],
    mark: "Callable[[], dict[str, Any] | None] | None",
    ) -> tuple[str | None, str]:
    """
    The inline test of the return value, and what a call returns when it fails.

    Args:
        checker (PreparedChecker): The checker of the function.
        check_return (bool): Whether the return value is checked.
        by_instance (bool): The `Self` tests are written against `_pv_call_class` (see `_self_testing`).
        self_tested (list[str]): The names whose annotation uses `Self`.
        namespace (dict[str, Any]): The wrapper's globals.
        mark (Callable[[], dict[str, Any] | None] | None): As for `generate_wrapper`, for `return_router`.

    Returns:
        tuple[str | None, str]: The test of `_pv_result` (None when the return value isn't checked),
        and the expression returned when it fails: `_pv_return_failed(...)`, which converts or raises,
        or for a `-> Self` tested against the class of the call `_pv_return_router(...)`, where the
        checker of that class says what went wrong.
    """
    if not (check_return and checker.ret_spec is not None):
        return None, "_pv_return_failed(_pv_result)"
    if by_instance and "return" in self_tested:
        namespace["_pv_return_router"] = return_router(checker, mark)
        return _self_test(checker, "return", "_pv_result"), "_pv_return_router(_pv_result, _pv_args)"
    return check_expr(checker.ret_spec, "_pv_result", namespace, "ret"), "_pv_return_failed(_pv_result)"


def _generate_codetype_from_source(src: str, kind: int) -> tuple[CodeType, str]:
    """
    The code object of `src`, from `_CODE_CACHE` or compiled (and kept there), with the source as the
    cache holds it. Names live in the namespace, so the source only encodes the signature's *shape*:
    functions with the same shape share one code object, and one source string. A generator
    function's wrapper carries the flag of its `kind` where that is harmless (`_FLAGGED`), and is kept
    under `(src, kind)`.

    Returns:
        tuple[CodeType, str]: The code object, and the source: equal to `src`, and the same object for
        every wrapper of this shape while the entry is in the cache.
    """
    key: Any = (src, kind) if kind & _FLAGGED else src
    cached = _CODE_CACHE.get(key)
    if cached is None:
        code = _stub_code(src)
        if key is not src:
            code = code.replace(co_flags = code.co_flags | kind)
        cached = (code, src)
        with CACHE_LOCK:
            while len(_CODE_CACHE) >= _CODE_CACHE_MAX:
                _CODE_CACHE.pop(next(iter(_CODE_CACHE)), None)      # the oldest entry
            _CODE_CACHE[key] = cached
    return cached


def check_expr(spec: tuple, variable: str, namespace: dict[str, Any], suffix: str) -> str | None:
    """
    The inline expression that tests `variable` against a compiled spec. The spec's object goes into
    `namespace`: `_pv_type_<suffix>` for a class (or a tuple or set of them), `_pv_predicate_<suffix>`
    for a function. Also used by the dataclass `__init__` and `__setattr__` generators.

    Args:
        spec (tuple): The spec: `("any",)`, `("isinstance", T)`, `("nobool", T)`, `("nodatetime", T)`,
            `("is", T)`, `("in", set)` or `("pred", callable)`.
        variable (str): The name of the value in the generated code.
        namespace (dict[str, Any]): The globals of the generated code.
        suffix (str): What the namespace names end with, so that each value has its own.

    Returns:
        str | None: The expression, or None for `("any",)`: anything passes.

    Raises:
        ValueError: If the spec's kind is none of these.
    """
    kind = spec[0]
    if kind == "any":
        return None
    if kind == "pred":
        namespace[f"_pv_predicate_{suffix}"] = spec[1]
        return f"_pv_predicate_{suffix}({variable})"        # precompiled
    name = f"_pv_type_{suffix}"
    namespace[name] = spec[1]
    match kind:
        case "isinstance":
            return f"isinstance({variable}, {name})"
        case "nobool":
            return f"(isinstance({variable}, {name}) and type({variable}) is not bool)"
        case "nodatetime":
            namespace[f"_pv_datetime_{suffix}"] = datetime_class()
            return f"(isinstance({variable}, {name}) and not isinstance({variable}, _pv_datetime_{suffix}))"
        case "is":
            return f"type({variable}) is {name}"
        case "in":
            return f"type({variable}) in {name}"
        case _:
            raise ValueError(f"Unknown kind: {kind}")


def _stub_code(source: str) -> CodeType:
    """Compile `source` (which defines `_pv_wrapper`) and return that function's code object."""
    namespace: dict[str, Any] = {}
    exec(compile(source, "<enforced wrapper>", "exec"), namespace)
    return namespace["_pv_wrapper"].__code__


_GENERATOR_FLAGS = inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
_KIND_FLAGS = inspect.CO_COROUTINE | _GENERATOR_FLAGS


def function_kind(fn: Any) -> int:
    """
    What kind of function `inspect` takes `fn` for: `CO_COROUTINE`, `CO_GENERATOR`,
    `CO_ASYNC_GENERATOR`, or 0 for an ordinary one.
    """
    #* A function: answered from the flags of its code, which is all inspect reads, unless
    #* inspect.markcoroutinefunction has said otherwise. (Three inspect calls cost more than the
    #* rest of a decoration put together.)
    if type(fn) is FunctionType and "_is_coroutine_marker" not in fn.__dict__:
        return fn.__code__.co_flags & _KIND_FLAGS
    elif inspect.iscoroutinefunction(fn):
        return inspect.CO_COROUTINE
    elif inspect.isgeneratorfunction(fn):                 # a functools.partial of one, ...
        return inspect.CO_GENERATOR
    else:
        return inspect.CO_ASYNC_GENERATOR if inspect.isasyncgenfunction(fn) else 0


_PROBE = f"def _pv_wrapper(*_pv_args, **_pv_kwargs):\n{_INDENT_1}return _pv_function\n"


def _runs_at_once(kind: int, source: str = _PROBE) -> bool:
    """
    Whether an ordinary function still runs when it is called, once its code carries the flag of
    a generator function (`kind`). It does in every CPython since 3.11: what makes a generator
    is an instruction at the start of a generator function's code, and nothing reads the flag when
    code is run. That is no promise, so it is tried here, once, on the Python that is running: a
    function made of `source` with the flag added is called and has to return at once. Where it
    doesn't (it hands back a generator, or Python refuses such code), no wrapper is given the flag.
    """
    try:
        code = _stub_code(source)
        return FunctionType(code.replace(co_flags = code.co_flags | kind), {FUNCTION_CODE_KEY: MISSING})() is MISSING
    except Exception:
        return False


#* The flags a wrapper may carry on this Python (see `_stub_codes`): both, or none where they would be acted on.
_FLAGGED: int = sum(kind for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR) if _runs_at_once(kind))


def _stub_codes(call: str, flagged: int | None = None) -> dict[int, CodeType]:
    """
    The code of a wrapper that does nothing but `call`, for each kind of function: an ordinary one
    (0), a coroutine function, a generator function and an async generator function.

    A wrapper of a generator function is an ordinary function: it checks the arguments when it is
    called and hands back the generator that `fn` returns. But `inspect.isgeneratorfunction`
    reads one thing only, a flag on the code object, and frameworks branch on it (a pytest `yield`
    fixture, a dependency with teardown): told "not a generator function", they use the generator
    object itself as the value. So the wrapper's code carries the flag of the function it wraps.
    Python itself doesn't read the flag when it runs code (a real generator function starts with an
    instruction that makes the generator), so the wrapper still runs at once, at the call.
    A wrapper keeps the kind it was made with: assigning a function code of another kind is deprecated.

    `flagged` (`_FLAGGED` unless given) holds the flags that were found to be harmless on this
    Python (`_runs_at_once`). A kind that is not among them gets the plain code: its wrapper
    checks and calls as ever, and is an ordinary function to `inspect`.
    """
    if flagged is None:
        flagged = _FLAGGED
    plain = _stub_code(f"def _pv_wrapper(*_pv_args, **_pv_kwargs):\n{_INDENT_1}return {call}\n")
    codes = {0: plain, inspect.CO_COROUTINE: _stub_code(f"async def _pv_wrapper(*_pv_args, **_pv_kwargs):\n{_INDENT_1}return await {call}\n")}
    for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR):
        codes[kind] = plain.replace(co_flags = plain.co_flags | kind) if kind & flagged else plain
    return codes


#* Shared code objects for every stub; each stub gets its own globals dict. `BOOT_CODES`: until the
#* first call has compiled the wrapper. `PLAIN_CODES`: for a function that is not to be checked.
BOOT_CODES = _stub_codes("_pv_bootstrap(_pv_args, _pv_kwargs)")
PLAIN_CODES = _stub_codes("_pv_function(*_pv_args, **_pv_kwargs)")
