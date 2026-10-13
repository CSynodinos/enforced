"""The compiled tier: source generated for one signature shape, and the code objects of a wrapper."""
from ._general_path import make_fallback, NO_ARGS, NO_KWARGS
from ._lifetime import CACHE_LOCK
from ._self_routing import return_router
from ._type_conversion import FAILED
from typing import Any, Callable, TYPE_CHECKING
from types import CodeType, FunctionType
import inspect

if TYPE_CHECKING:
    from ._checker import PreparedChecker


MISSING = object()


#* source -> code object (for a generator function: (source, its kind) -> code object). Like the other
#* two annotation caches, it lets its oldest entry go when it is full (it used to stop taking new
#* ones). Reads take no lock; inserting and evicting do.
_CODE_CACHE: dict[Any, CodeType] = {}
_CODE_CACHE_MAX = 2048


def generate_wrapper(
    checker: "PreparedChecker",
    check_return: bool,
    is_async: bool,
    ns: dict[str, Any],
    mark: "Callable[[], dict[str, Any] | None] | None" = None,
    kind: int = 0,
    ) -> tuple[CodeType, str]:
    """
    Write and ``exec`` a wrapper specialised to ``checker.fn``'s signature.

    The generated code only decides "definitely fine" and then calls ``fn``: it binds
    arguments with straight-line code and inlines one ``isinstance``/``type`` test per
    parameter. Any doubt (wrong type, missing or duplicate argument, unknown keyword)
    jumps to the fallback, which converts what it can and raises the same detailed
    errors as before for the rest.

    ``kind`` is the flag of a generator function (see ``_stub_codes``); 0 for any other. The code
    carries it where that is harmless (``_FLAGGED``).
    """
    P = inspect.Parameter
    ns.update({
        "_pv_fn": checker.call,
        "_pv_fallback": make_fallback(checker, check_return, is_async, mark),
        "_pv_ret_fail": checker.check_return,
        "_pv_M": MISSING,
        "_pv_F": FAILED,
        })
    aw = "await " if is_async else ""
    fail = f"return {aw}_pv_fallback(_pv_a, _pv_k)"
    lines = [f"{'async ' if is_async else ''}def _pv_wrapper(*_pv_a, **_pv_k):"]

    #* A method whose checked annotations use ``Self`` (see ``_route``). Two ways to get the
    #* class of the call into a check that was compiled once:
    #*   - ``by_instance``: every such annotation is ``Self`` itself, tested by nothing but the
    #*     class. The test is then written against the class of the first argument, and one
    #*     wrapper serves every class: ``isinstance(other, type(self))``.
    #*   - otherwise (``Self | None``, ``list[Self]``, a class method ...): this code is for one
    #*     class, ``_pv_me``, and a call made on another goes to the wrapper for that class.
    me = checker.me or checker.owner
    uses = checker.self_uses or {}
    checks_return = check_return and checker.ret_spec is not None
    relative = [name for name in uses if name != "return" or checks_return]

    def plain_self(name: str) -> bool:
        spec = checker.ret_spec if name == "return" else checker.specs.get(name)
        converted = (name in checker.converters or (name == checker.var_pos and checker.var_pos_conv is not None)
                     or (name == checker.var_kw and checker.var_kw_conv is not None))
        return bool(uses[name]) and not converted and spec is not None and spec[0] in ("isinstance", "is") and spec[1] is me

    by_instance = bool(relative) and not checker.class_first and all(plain_self(name) for name in relative)
    by_class = bool(relative) and not by_instance

    def self_expr(name: str, var: str) -> str:
        """The test of ``var`` against the class of this call (``_pv_c0``), as the spec for ``me`` tests it."""
        strict = (checker.ret_spec if name == "return" else checker.specs[name])[0] == "is"     # type: ignore[index]
        return f"type({var}) is _pv_c0" if strict else f"isinstance({var}, _pv_c0)"

    ret_expr = None
    ret_fail = "_pv_ret_fail(_pv_r)"
    if checks_return:
        if by_instance and "return" in relative:
            ret_expr = self_expr("return", "_pv_r")
            #* What went wrong is said by the checker of the class the call was made on.
            ns["_pv_ret_route"] = return_router(checker, mark)
            ret_fail = "_pv_ret_route(_pv_r, _pv_a)"
        else:
            ret_expr = check_expr(checker.ret_spec, "_pv_r", ns, "ret")      # type: ignore[arg-type]

    #* A dataclass __init__ whose __setattr__ skips re-checking what was checked here (see ``mark``
    #* in wrap_callable). Two dict stores per call, and only for classes that asked for it.
    state = mark() if mark is not None and not is_async and ret_expr is None else None
    if state is not None:
        ns.update({"_pv_g": state, "_pv_N": NO_ARGS, "_pv_E": NO_KWARGS})

    def emit_call(ind: str, call: str, args: str = "_pv_a", kwargs: str | None = "_pv_k") -> None:
        """``args`` / ``kwargs``: source for the arguments ``call`` passes (``kwargs`` None: it passes none)."""
        if state is not None:
            if kwargs is None:
                lines.append(f"{ind}_pv_g['_pv_args'] = {args}")
                lines.append(f"{ind}try: return {call}")
                lines.append(f"{ind}finally: _pv_g['_pv_args'] = _pv_N")
            else:
                lines.append(f"{ind}_pv_g['_pv_kw'] = {kwargs}; _pv_g['_pv_args'] = {args} or _pv_N")
                lines.append(f"{ind}try: return {call}")
                lines.append(f"{ind}finally: _pv_g['_pv_args'] = _pv_N; _pv_g['_pv_kw'] = _pv_E")
            return
        if ret_expr is None:
            lines.append(f"{ind}return {aw}{call}")
            return
        lines.append(f"{ind}_pv_r = {aw}{call}")
        lines.append(f"{ind}if {ret_expr}: return _pv_r")
        lines.append(f"{ind}return {ret_fail}")            # converts, or raises the detailed error

    def emit_check(ind: str, expr: str | None) -> None:
        if expr is not None:
            lines.append(f"{ind}if not ({expr}): {fail}")

    def emit_value_check(ind: str, expr: str | None, var: str, name: str, tag: str, record: str) -> None:
        """Check ``var``; if it fails and a converter exists, convert inline and run ``record``."""
        converter = checker.converters.get(name)
        if expr is None or converter is None:
            emit_check(ind, expr)
            return
        #* The general path is told which parameter's conversion has just failed, and doesn't
        #* try it again: for a TypeModel that is the user's ``validate``, run twice per wrong call.
        ns[f"_pv_cv_{tag}"], ns[f"_pv_nm_{tag}"] = converter, name
        lines.append(f"{ind}if not ({expr}):")
        lines.append(f"{ind}    {var} = _pv_cv_{tag}({var})")
        lines.append(f"{ind}    if {var} is _pv_F: return {aw}_pv_fallback(_pv_a, _pv_k, _pv_nm_{tag})")
        lines.append(f"{ind}    {record}")

    params = list(checker.sig.parameters.values())
    positional = [p for p in params if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
    kw_only = [p for p in params if p.kind is P.KEYWORD_ONLY]
    var_pos = next((p for p in params if p.kind is P.VAR_POSITIONAL), None)
    var_kw = next((p for p in params if p.kind is P.VAR_KEYWORD), None)
    n_pos = len(positional)
    specs = checker.specs

    #* Converted defaults that could not be written into the function (see ``PreparedChecker.inject``):
    #* the wrapper passes them itself where the call leaves the parameter out.
    inject = checker.inject or {}
    also = ""
    if kw_inject := {p.name: inject[p.name] for p in kw_only if p.name in inject}:
        ns["_pv_dk"] = kw_inject
        also = ", **_pv_dk"                             # the fast lane passes no keyword: all of them, at once
    #* ``*args: *tuple[int, str]``: the extra positional arguments are tested as one tuple.
    tuple_check = None
    if var_pos is not None and checker.var_pos_node is not None:
        ns["_pv_vp"] = checker.var_pos_node.check
        tuple_check = f"_pv_vp(_pv_a[{n_pos}:])"

    def expr_for(p: inspect.Parameter, var: str, tag: object) -> str | None:
        spec = specs.get(p.name)
        if by_instance and p.name in relative:
            return self_expr(p.name, var)
        return None if spec is None else check_expr(spec, var, ns, str(tag))

    exprs = [expr_for(p, f"_v{i}", i) for i, p in enumerate(positional)]
    var_pos_expr = expr_for(var_pos, "_x", "vp") if var_pos else None
    var_kw_expr = expr_for(var_kw, "_x", "vk") if var_kw else None

    lines.append("    _pv_n = len(_pv_a)")

    if by_instance:
        #* The class of this call, for the tests written against it. What stands in the place of
        #* ``self`` has to be an instance of the class at all: anything else is left to the general path.
        ns["_pv_owner"] = checker.owner
        lines.append(f"    if not _pv_n: {fail}")
        lines.append("    _pv_c0 = type(_pv_a[0])")
        lines.append(f"    if _pv_c0 is not _pv_owner and not isinstance(_pv_a[0], _pv_owner): {fail}")
    elif by_class:
        #* Compiled for ``_pv_me``. A call made on another class goes to the wrapper for that class,
        #* straight from the family when it has been met before, else through the fallback, which
        #* makes one. The family knows a class by its id and holds its wrapper weakly (see ``_route``).
        with CACHE_LOCK:
            if checker.family is None:
                checker.family = {}
        ns["_pv_me"], ns["_pv_subs"] = me, checker.family
        called_on = "_pv_a[0]" if checker.class_first else "type(_pv_a[0])"
        lines.append(f"    if _pv_n and {called_on} is not _pv_me:")
        lines.append(f"        _pv_s = _pv_subs.get(id({called_on}))")
        lines.append("        if _pv_s is not None:")
        lines.append("            _pv_s = _pv_s()")
        lines.append(f"            if _pv_s is not None: return {aw}_pv_s(*_pv_a, **_pv_k)")
        lines.append(f"        {fail}")

    #* Fast lane: every positional parameter passed positionally, no keywords at all.
    if not any(p.default is P.empty for p in kw_only):
        cond = f"_pv_n >= {n_pos}" if var_pos else f"_pv_n == {n_pos}"
        lines.append(f"    if not _pv_k and {cond}:")
        if n_pos:
            targets = ", ".join(f"_v{i}" for i in range(n_pos))
            source = "_pv_a" if not var_pos else f"_pv_a[:{n_pos}]"
            lines.append(f"        {targets}, = {source}")
        fast_conv = any(exprs[i] is not None and p.name in checker.converters for i, p in enumerate(positional))
        if fast_conv:
            lines.append("        _pv_ch = False")
        for i, (p, e) in enumerate(zip(positional, exprs)):
            emit_value_check("        ", e, f"_v{i}", p.name, str(i), "_pv_ch = True")
        if var_pos and var_pos_expr:
            lines.append(f"        for _x in _pv_a[{n_pos}:]:")
            emit_check("            ", var_pos_expr)
        emit_check("        ", tuple_check)
        if fast_conv:
            rest = f", *_pv_a[{n_pos}:]" if var_pos else ""
            lines.append("        if _pv_ch:")
            given = "".join(f"_v{i}, " for i in range(n_pos)) + (f"*_pv_a[{n_pos}:]" if var_pos else "")
            emit_call("            ", f"_pv_fn({', '.join(f'_v{i}' for i in range(n_pos))}{rest}{also})",
                      f"({given})" if n_pos else "_pv_a", None)
        emit_call("        ", f"_pv_fn(*_pv_a{also})", "_pv_a" if n_pos else "(_pv_a or _pv_N)", None)

    #* General lane: any mix of positional and keyword arguments.
    if not var_pos:
        lines.append(f"    if _pv_n > {n_pos}: {fail}")
    lines.append("    _pv_c = 0")
    general_conv = bool(inject) or any(p.name in checker.converters for p in positional + kw_only)
    if general_conv:
        lines.append("    _pv_ca = _pv_ck = None")         # converted copies of args / kwargs, made on demand
    keep_pos = lambda i, var: f"_pv_ca = list(_pv_a) if _pv_ca is None else _pv_ca; _pv_ca[{i}] = {var}"
    keep_kw = lambda key, var: f"_pv_ck = dict(_pv_k) if _pv_ck is None else _pv_ck; _pv_ck[{key}] = {var}"
    for i, p in enumerate(positional):
        required = p.default is P.empty
        lines.append(f"    if _pv_n > {i}:")
        if p.kind is P.POSITIONAL_OR_KEYWORD:
            ns[f"_pv_name{i}"] = p.name
            lines.append(f"        if _pv_name{i} in _pv_k: {fail}")   # duplicate binding
        lines.append(f"        _v{i} = _pv_a[{i}]")
        emit_value_check("        ", exprs[i], f"_v{i}", p.name, str(i), keep_pos(i, f"_v{i}"))
        if p.kind is P.POSITIONAL_ONLY:
            if required or p.name in inject:            # a default to pass by position: left to the fallback
                lines.append(f"    else: {fail}")
            continue
        lines.append("    else:")
        lines.append(f"        _v{i} = _pv_k.get(_pv_name{i}, _pv_M)")
        lines.append(f"        if _v{i} is _pv_M:")
        if p.name in inject:
            ns[f"_pv_d{i}"] = inject[p.name]
            lines.append(f"            {keep_kw(f'_pv_name{i}', f'_pv_d{i}')}")
        else:
            lines.append(f"            {fail}" if required else "            pass")
        lines.append("        else:")
        lines.append("            _pv_c += 1")
        emit_value_check("            ", exprs[i], f"_v{i}", p.name, str(i), keep_kw(f"_pv_name{i}", f"_v{i}"))
    for j, p in enumerate(kw_only):
        var = f"_w{j}"
        ns[f"_pv_kname{j}"] = p.name
        lines.append(f"    {var} = _pv_k.get(_pv_kname{j}, _pv_M)")
        lines.append(f"    if {var} is _pv_M:")
        if p.name in inject:
            ns[f"_pv_dw{j}"] = inject[p.name]
            lines.append(f"        {keep_kw(f'_pv_kname{j}', f'_pv_dw{j}')}")
        else:
            lines.append(f"        {fail}" if p.default is P.empty else "        pass")
        lines.append("    else:")
        lines.append("        _pv_c += 1")
        emit_value_check("        ", expr_for(p, var, f"k{j}"), var, p.name, f"k{j}", keep_kw(f"_pv_kname{j}", var))
    if var_pos and var_pos_expr:
        lines.append(f"    for _x in _pv_a[{n_pos}:]:")
        emit_check("        ", var_pos_expr)
    emit_check("    ", tuple_check)
    lines.append("    if _pv_c != len(_pv_k):")
    if var_kw is None:
        lines.append(f"        {fail}")         # unknown keyword
    elif var_kw_expr is not None:
        ns["_pv_known"] = frozenset(p.name for p in params if p.kind in (P.POSITIONAL_OR_KEYWORD, P.KEYWORD_ONLY))
        lines.append("        for _kk, _x in _pv_k.items():")
        lines.append("            if _kk not in _pv_known:")
        emit_check("                ", var_kw_expr)
    else:
        lines.append("        pass")
    if general_conv:
        lines.append("    if _pv_ca is not None or _pv_ck is not None:")
        emit_call("        ", "_pv_fn(*(_pv_a if _pv_ca is None else _pv_ca), **(_pv_k if _pv_ck is None else _pv_ck))",
                  "(_pv_a if _pv_ca is None else _pv_ca)", "(_pv_k if _pv_ck is None else _pv_ck)")
    emit_call("    ", "_pv_fn(*_pv_a, **_pv_k)")

    source = "\n".join(lines)
    # Names live in ``ns``, so the source only encodes the signature's *shape*:
    # functions with the same shape share one compiled code object.
    key: Any = (source, kind) if kind & _FLAGGED else source
    code = _CODE_CACHE.get(key)
    if code is None:
        code = _stub_code(source)
        if key is not source:
            code = code.replace(co_flags = code.co_flags | kind)
        with CACHE_LOCK:
            while len(_CODE_CACHE) >= _CODE_CACHE_MAX:
                _CODE_CACHE.pop(next(iter(_CODE_CACHE)), None)      # the oldest entry
            _CODE_CACHE[key] = code
    return code, source


def check_expr(spec: tuple, var: str, ns: dict[str, Any], tag: str) -> str | None:
    """Inline Python expression testing ``var`` against a compiled spec (None = always passes)."""
    kind = spec[0]
    if kind == "any":
        return None
    name = f"_pv_t_{tag}"
    ns[name] = spec[1]
    if kind == "isinstance":
        return f"isinstance({var}, {name})"
    if kind == "nobool":
        return f"(isinstance({var}, {name}) and type({var}) is not bool)"
    if kind == "is":
        return f"type({var}) is {name}"
    if kind == "in":
        return f"type({var}) in {name}"
    return f"{name}({var})"                     # "pred": precompiled predicate


def _stub_code(source: str) -> CodeType:
    """Compile ``source`` (which defines ``_pv_wrapper``) and return that function's code object."""
    namespace: dict[str, Any] = {}
    exec(compile(source, "<enforced wrapper>", "exec"), namespace)
    return namespace["_pv_wrapper"].__code__


_GENERATOR_FLAGS = inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
_KIND_FLAGS = inspect.CO_COROUTINE | _GENERATOR_FLAGS


def function_kind(fn: Any) -> int:
    """
    What kind of function ``inspect`` takes ``fn`` for: ``CO_COROUTINE``, ``CO_GENERATOR``,
    ``CO_ASYNC_GENERATOR``, or 0 for an ordinary one.
    """
    #* A function: answered from the flags of its code, which is all inspect reads, unless
    #* inspect.markcoroutinefunction has said otherwise. (Three inspect calls cost more than the
    #* rest of a decoration put together.)
    if type(fn) is FunctionType and "_is_coroutine_marker" not in fn.__dict__:
        return fn.__code__.co_flags & _KIND_FLAGS
    if inspect.iscoroutinefunction(fn):
        return inspect.CO_COROUTINE
    if inspect.isgeneratorfunction(fn):                 # a functools.partial of one, ...
        return inspect.CO_GENERATOR
    return inspect.CO_ASYNC_GENERATOR if inspect.isasyncgenfunction(fn) else 0


_PROBE = "def _pv_wrapper(*_pv_a, **_pv_k):\n    return _pv_fn\n"


def _runs_at_once(kind: int, source: str = _PROBE) -> bool:
    """
    Whether an ordinary function still runs when it is called, once its code carries the flag of
    a generator function (``kind``). It does in every CPython since 3.11: what makes a generator
    is an instruction at the start of a generator function's code, and nothing reads the flag when
    code is run. That is no promise, so it is tried here, once, on the Python that is running: a
    function made of ``source`` with the flag added is called and has to return at once. Where it
    doesn't (it hands back a generator, or Python refuses such code), no wrapper is given the flag.
    """
    try:
        code = _stub_code(source)
        return FunctionType(code.replace(co_flags = code.co_flags | kind), {"_pv_fn": MISSING})() is MISSING
    except Exception:
        return False


#* The flags a wrapper may carry on this Python (see ``_stub_codes``): both, or none where they would be acted on.
_FLAGGED: int = sum(kind for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR) if _runs_at_once(kind))


def _stub_codes(call: str, flagged: int | None = None) -> dict[int, CodeType]:
    """
    The code of a wrapper that does nothing but ``call``, for each kind of function: an ordinary one
    (0), a coroutine function, a generator function and an async generator function.

    A wrapper of a generator function is an ordinary function: it checks the arguments when it is
    called and hands back the generator that ``fn`` returns. But ``inspect.isgeneratorfunction``
    reads one thing only, a flag on the code object, and frameworks branch on it (a pytest ``yield``
    fixture, a dependency with teardown): told "not a generator function", they use the generator
    object itself as the value. So the wrapper's code carries the flag of the function it wraps.
    Python itself doesn't read the flag when it runs code (a real generator function starts with an
    instruction that makes the generator), so the wrapper still runs at once, at the call.
    A wrapper keeps the kind it was made with: assigning a function code of another kind is deprecated.

    ``flagged`` (``_FLAGGED`` unless given) holds the flags that were found to be harmless on this
    Python (``_runs_at_once``). A kind that is not among them gets the plain code: its wrapper
    checks and calls as ever, and is an ordinary function to ``inspect``.
    """
    if flagged is None:
        flagged = _FLAGGED
    plain = _stub_code(f"def _pv_wrapper(*_pv_a, **_pv_k):\n    return {call}\n")
    codes = {0: plain, inspect.CO_COROUTINE: _stub_code(f"async def _pv_wrapper(*_pv_a, **_pv_k):\n    return await {call}\n")}
    for kind in (inspect.CO_GENERATOR, inspect.CO_ASYNC_GENERATOR):
        codes[kind] = plain.replace(co_flags = plain.co_flags | kind) if kind & flagged else plain
    return codes


#* Shared code objects for every stub; each stub gets its own globals dict. ``BOOT_CODES``: until the
#* first call has compiled the wrapper. ``PLAIN_CODES``: for a function that is not to be checked.
BOOT_CODES = _stub_codes("_pv_bootstrap(_pv_a, _pv_k)")
PLAIN_CODES = _stub_codes("_pv_fn(*_pv_a, **_pv_k)")
