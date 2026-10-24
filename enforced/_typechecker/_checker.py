"""PreparedChecker: everything known about one function's checks, and the one pass over a call."""
from ._annotations import find_owner, resolve_annotations, SELF_IN_PARAMETERS, SELF_IN_RETURN, tag_owner
from ._checks import REFUSED
from ._container import matches_type, TypeContainer, TypeUnion
from ._defaults import check_defaults, IN_PLACE, PASSED, copy_with_defaults
from ._errors import pending_error, Problem, retype, said_error, step, InvalidDataError, warn_of
from .._formatting_tool import coloured
from ._messages import invalid_head, invalid_tail, missing_msg, type_head, type_tail
from ._text import OWNER_ATTR
from ._problems import type_problem, typechecker_type_error_factory, value_problems
from ._scope import resolver
from ._signatures import own_signature, signature_of, typed_kwargs
from ._slow_path import full_check, typecheck_return_pipeline
from ._specs import (
    always_false, args_node, compile_converter, compile_spec, deep_converter, deep_node, predicate, SLOW,
    unpacked_tuple,
    )
from ._type_conversion import FAILED, is_model, REJECTED
from typing import Any, Callable, get_args, TYPE_CHECKING
from functools import partial
import inspect
import sys

if TYPE_CHECKING:
    from ._defaults import ExtraDefaults


class PreparedChecker:
    """
    Per-function checker compiled on first call and reused afterwards.

    Holds the resolved annotations, validated defaults, the bound-parameter layout
    and one precompiled predicate per parameter. The fast path only ever answers
    "definitely fine"; anything else (errors, odd call shapes) is handed to the full
    path (``full_check``), so messages are identical to the uncompiled behaviour.
    """
    #* Slots: attribute reads stay fast however many there are (instances with more than ~30
    #* plain attributes lose CPython's inline-attribute fast path, slowing every self.x).
    __slots__ = (
        "fn", "convert", "coerce", "deep", "rewrite_defaults", "_given_record", "allow_subclass", "owner",
        "skip_first", "ready", "defaults_ok", "record", "nodes", "pos_names", "n_pos", "kw_names", "required",
        "var_pos", "var_kw", "checks", "var_pos_check", "var_kw_check", "ret_check", "specs", "ret_spec",
        "converters", "check_order", "var_pos_conv", "var_kw_conv", "can_convert", "ret_conv", "extra_defaults",
        "resolve", "var_pos_node", "var_pos_annotation", "sig", "call", "inject", "me", "self_in", "self_uses", "class_first",
        "family", "plan", "kw_plan", "required_at", "bound_at", "ret_entry", "warn", "error", "heads", "leave",
        )
    var_pos_node: Any
    var_pos_annotation: Any
    sig: inspect.Signature
    plan: Any                   # set by ``_plan``, with ``kw_plan`` and ``required_at``; None: the one pass is not used
    kw_plan: Any
    required_at: Any
    bound_at: int
    ret_entry: Any

    def __init__(
        self,
        fn: Callable[..., Any],
        allow_subclass: bool,
        owner: type | None,
        skip_first: bool,
        record: dict[str, Any] | None = None,
        convert: bool = True,
        coerce: bool = False,
        rewrite_defaults: "bool | str" = False,
        deep: bool = False,
        extra_defaults: "ExtraDefaults | None" = None,
        resolve: "Callable[[str], Any] | None" = None,
        me: type | None = None,
        family: "dict[int, Any] | None" = None,
        warn: bool = False,
        error: "type[InvalidDataError]" = InvalidDataError,
        leave: "frozenset[str]" = frozenset(),
        ) -> None:
        #* ``leave``: parameters not to check at all (a version of ``enforced.dispatch``: its anchor was
        #* tested by the choice of the version). Read once, by ``_make_ready``.
        self.leave = leave
        #* ``on_error = "warn"``: a value that fails is reported as a warning, and the call goes
        #* ahead with it. A call that can't be made (a missing argument, one that doesn't bind)
        #* and a mistake in the definition (a default, an annotation) are raised all the same.
        self.warn = warn
        #* ``error = ...``: the class of every error this checker raises (checked by the API that was
        #* given it: ``check_error_type``). Read where an error is made, never on a valid call.
        self.error = error
        self.heads: dict[tuple[Any, ...], str] | None = None      # see ``_head``

        self.fn = fn
        self.convert = convert
        self.coerce = coerce
        self.deep = deep
        #* What happens to a default that is converted (``x: float = 0``). False: nothing (a field
        #* checker, a record that is only tested). True: the wrapper is to call something that
        #* receives ``0.0``, without touching ``fn`` (see ``call`` and ``inject``). ``IN_PLACE``: it is
        #* written into ``fn`` itself. ``PASSED``: it is handed back with the checked arguments
        #* (typecheck_record, which never calls ``fn`` and never changes it).
        self.rewrite_defaults = rewrite_defaults
        #* What the wrapper calls: ``fn``, or once a default was converted a copy of ``fn`` that has it.
        self.call: Any = fn
        #* Converted defaults that no copy can hold, because the defaults aren't ``fn``'s own (a
        #* decorator made with ``functools.wraps``, a ``functools.partial``, an object with
        #* ``__call__``): name -> value, passed explicitly where a call leaves the parameter out.
        self.inject: dict[str, Any] | None = None
        self.extra_defaults = extra_defaults    # defaults that aren't parameters of fn (see check_defaults)
        self._given_record = record     # explicit annotations (typecheck_record); None = resolve from fn
        self.allow_subclass = allow_subclass
        self.owner = owner
        self.skip_first = skip_first
        #* For a method: the class ``Self`` stands for in this checker (None: the owner), and where
        #* its annotations use ``Self`` (None until they are resolved by ``_prepare``, then
        #* ``SELF_IN_PARAMETERS`` and ``SELF_IN_RETURN``; 0 for anything that isn't a method).
        #* ``family``: the wrappers of the same method for the other classes it was called on, None
        #* until there is one (see ``_route``). ``self_uses`` and ``class_first`` are set by ``_prepare``.
        self.me = me
        self.family = family
        self.self_in: int | None = None
        self.ready = False
        self.plan = None                # until ``_prepare`` has laid one out (``_plan``)
        self.ret_entry = None
        self.defaults_ok = False
        #* Reads a name left as a string inside an annotation. With an explicit record it is only set
        #* by a caller whose record comes from source code (a dataclass's fields): the strings of a
        #* typecheck_record record are data, and are never evaluated.
        self.resolve = resolve
        #* ``var_pos_node`` / ``var_pos_annotation`` are set by ``_prepare``, like the other results:
        #* for ``*args: *tuple[int, str]`` the node that checks the extra positional arguments as one
        #* tuple, and that tuple annotation (for messages); None for every other function.
        return

    def _prepare(self, args: tuple[Any, ...] = ()) -> None:
        """
        Read the annotations, check the defaults, lay the checks out (``_make_ready``). An error made
        on the way (an annotation that can't be read, a wrong default) is made by code that doesn't know
        the checker, as ``InvalidDataError``: it is given the checker's class here.
        """
        try:
            self._make_ready(args)
        except InvalidDataError as e:
            retype(e, self.error)
            raise

    def _make_ready(self, args: tuple[Any, ...] = ()) -> None:
        P = inspect.Parameter
        fn = self.fn
        sig = signature_of(fn)
        self_uses: dict[str, bool] | None = None
        class_first = False
        if self._given_record is not None:
            record, resolve = self._given_record, self.resolve
        else:
            #* A method decorated on its own doesn't know its class until it is called.
            if self.owner is None and (found := find_owner(fn, args)) is not None:
                self.owner, through_self = found
                self.skip_first = self.skip_first or through_self
                tag_owner(fn, self.owner)
            #* A method (it takes ``self`` or ``cls``): ``Self`` is the class of this call, exactly.
            uses: dict[str, bool] = {}                  # name -> whether its annotation is ``Self`` and nothing else
            method = self.owner is not None and self.skip_first
            record = resolve_annotations(fn, self.owner, not self.allow_subclass,
                                          (self.me or self.owner) if method else None, uses)
            if method and uses:
                self_uses = uses
                first = args[0] if args else None
                class_first = (isinstance(first, type) and not isinstance(first, self.owner)       # type: ignore[arg-type]
                               and self.owner in first.__mro__)
            if self.leave:
                record = {name: annotation for name, annotation in record.items() if name not in self.leave}
            record, sig = typed_kwargs(record, sig)
            resolve = self.resolve = resolver(fn, self.owner)
        #* Where ``Self`` stands (name -> whether it is the whole annotation; None: nowhere, or this is
        #* no method), and whether the first argument is the class itself, as for a class method.
        self.self_uses, self.class_first = self_uses, class_first
        self.self_in = 0 if self_uses is None else (
            (SELF_IN_PARAMETERS if any(name != "return" for name in self_uses) else 0)
            | (SELF_IN_RETURN if "return" in self_uses else 0))
        self.sig = sig
        if not self.defaults_ok:
            converted = check_defaults(fn, record, self.allow_subclass, self.convert, self.coerce,
                                        self.rewrite_defaults is IN_PLACE, self.deep, self.extra_defaults, resolve, sig)
            own = own_signature(fn)
            if converted and self.rewrite_defaults is True and own:
                self.call = copy_with_defaults(fn, converted, sig)
            elif converted and (self.rewrite_defaults in (True, PASSED) or (self.rewrite_defaults is IN_PLACE and not own)):
                #* Nowhere to write them: they are passed with each call that leaves the parameter out.
                self.inject = {name: value for name, (_, value) in converted.items()}
            self.defaults_ok = True

        pos_names: list[str] = []
        kw_names: set[str] = set()
        required: list[str] = []
        var_pos = var_kw = None
        for name, p in sig.parameters.items():
            if p.kind is P.VAR_POSITIONAL:
                var_pos = name
                continue
            if p.kind is P.VAR_KEYWORD:
                var_kw = name
                continue
            if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD):
                pos_names.append(name)
            if p.kind is not P.POSITIONAL_ONLY:
                kw_names.add(name)
            if p.default is P.empty:
                required.append(name)

        #* Whether a method that uses ``Self`` is called on instances or on the class shows in the
        #* first argument: without one (a call that can't be made anyway) it is found out next time.
        cacheable = not (self.self_in and not args)
        checks: dict[str, Callable[[Any], bool]] = {}
        specs: dict[str, tuple] = {}
        converters: dict[str, Callable[[Any], Any]] = {}
        var_pos_check = var_kw_check = None
        flags = (self.allow_subclass, self.convert, self.coerce)
        ret_flags = self._return_flags()
        #* ``*args: *tuple[...]`` describes the extra positional arguments as a whole.
        var_pos_node = var_pos_annotation = None
        if var_pos is not None and (unpacked := unpacked_tuple(record.get(var_pos))) is not None:
            items = get_args(unpacked)
            if len(items) == 2 and items[1] is Ellipsis:
                record = {**record, var_pos: items[0]}      # *tuple[int, ...] says what *args: int says
            else:
                record = {**record, var_pos: Any}           # no test per argument: the tuple is checked below
                node = args_node(unpacked, *flags, self.deep, resolve)
                if node is SLOW:
                    cacheable = False
                elif node is not None:
                    var_pos_node, var_pos_annotation = node, unpacked
        #* Deep checks, per parameter (and "return"): only annotations with items to check.
        nodes: dict[str, Any] = {}
        if self.deep:
            for name, annotation in record.items():
                if name == "return":
                    node = deep_node(type(None) if annotation is None else annotation, *ret_flags, resolve)
                else:
                    node = deep_node(annotation, *flags, resolve)
                if node is not None:
                    nodes[name] = node
        for name, annotation in record.items():
            if name == "return":
                continue
            spec = compile_spec(annotation, self.allow_subclass, name, self.deep, self.convert, self.coerce, resolve)
            if spec is SLOW:
                cacheable = False       # e.g. forward ref not defined yet: retry on the next call
                spec = ("pred", always_false)
            specs[name] = spec          # type: ignore[assignment]
            compiled = predicate(spec) # type: ignore[arg-type]
            if name == var_pos:
                var_pos_check = compiled
            elif name == var_kw:
                var_kw_check = compiled
            elif compiled is not None:
                checks[name] = compiled   # type: ignore[assignment]
            if name in nodes and nodes[name] is not SLOW and (self.convert or self.coerce):
                #* The node that reports the errors converts too: where it stopped is kept on it
                #* (``_deep._stopped``), and an annotation that names a local class isn't cached, so a
                #* second compile would make a second node.
                converter = deep_converter(nodes[name])
            else:
                converter = compile_converter(annotation, self.allow_subclass, name, self.convert, self.coerce, self.deep,
                                               resolve)
            if converter is not None:
                converters[name] = converter

        ret_check: Callable[[Any], bool] | None = None
        ret_spec: tuple | None = None
        ret_conv: Callable[[Any], Any] | None = None
        if "return" in record:
            rt = record["return"]
            rt = type(None) if rt is None else rt
            _, ret_convert, ret_coerce = ret_flags
            spec = compile_spec(rt, self.allow_subclass, "return", self.deep, ret_convert, ret_coerce, resolve)
            if spec is SLOW:
                cacheable = False
                spec = ("pred", always_false)
            ret_spec = spec             # type: ignore[assignment]
            ret_check = predicate(spec)  # type: ignore[arg-type]
            ret_conv = compile_converter(rt, self.allow_subclass, "return", ret_convert, ret_coerce, self.deep, resolve)

        self.record = record
        self.nodes = nodes
        self.pos_names = tuple(pos_names)
        self.n_pos = len(pos_names)
        self.kw_names = frozenset(kw_names)
        self.required = tuple(required)
        self.var_pos = var_pos
        self.var_kw = var_kw
        self.checks = checks
        self.var_pos_check = var_pos_check
        self.var_kw_check = var_kw_check
        self.ret_check = ret_check
        self.specs = specs
        self.ret_spec = ret_spec
        self.converters = converters
        self.check_order = tuple(name for name in record if name != "return")
        self.var_pos_conv = converters.pop(var_pos, None) if var_pos else None
        self.var_kw_conv = converters.pop(var_kw, None) if var_kw else None
        self.var_pos_node, self.var_pos_annotation = var_pos_node, var_pos_annotation
        self.can_convert = (bool(converters) or self.var_pos_conv is not None or self.var_kw_conv is not None
                            or (var_pos_node is not None and var_pos_node.can_convert))
        self.ret_conv = ret_conv
        self.plan = self.kw_plan = self.required_at = self.ret_entry = None
        if cacheable:                           # a checker that isn't ready prepares again at the next call
            self._plan(record, checks, converters, sig, var_pos_node is not None)
            if ret_check is not None and nodes.get("return") is None:
                #* Like a plan entry, for the return value (``check_return``).
                rt = type(None) if record["return"] is None else record["return"]
                self.ret_entry = (ret_check, ret_conv, "return", 0, *_only_type("return", rt, ret_flags[1]), rt)
        self.ready = cacheable

    def _plan(self, record: dict[str, Any], checks: dict[str, Any], converters: dict[str, Any],
              sig: inspect.Signature, tuple_args: bool) -> None:
        """
        Lay the checks out for the one pass that the general path makes over a call (``check_inputs``):
        ``plan`` has one entry per positional parameter, in order (``None``: nothing to check),
        ``kw_plan`` the same by name, ``required_at`` each required parameter with its position
        (-1: keyword-only). An entry is ``(check, converter, name, order, expected, quick, annotation)``;
        ``expected`` is the runtime type where a failure can only be a wrong type, and ``NO_TYPE``
        where it may also be a rejected value (an ``Annotated`` check, a TypeModel), which the
        slower way of making a problem finds out.

        A parameter whose items are checked (``deep``) has ``DEEP`` for ``expected`` and its node for
        ``quick``: what is wrong inside it is found by the node, at once (``_deep_entry_problems``),
        one problem per bad item. (It took the three passes until 2026-10-15, and a wrong call of a
        deep dataclass cost three times what it does now.)

        ``plan`` is ``None`` for a function that the pass doesn't take: ``*args`` / ``**kwargs``, and
        ``*args: *tuple[...]``. Those keep the three passes (``_fast_ok``, ``_convert``, ``_type_problems``).
        """
        if self.var_pos is not None or self.var_kw is not None or tuple_args:
            return
        tolerant = self.convert or self.coerce
        nodes = self.nodes
        entries: dict[str, tuple[Any, ...]] = {}
        for order, name in enumerate(self.check_order):
            check = checks.get(name)
            if check is None:
                continue
            node = nodes.get(name)
            if node is not None:
                entries[name] = (check, converters.get(name), name, order, DEEP, node, record[name])
            else:
                entries[name] = (check, converters.get(name), name, order, *_only_type(name, record[name], tolerant), record[name])
        self.kw_plan = {name: entries.get(name) for name in self.kw_names}
        position = {name: i for i, name in enumerate(self.pos_names)}
        self.required_at = tuple([(name, position.get(name, -1)) for name in self.required])
        #* With this many positional arguments, no required parameter is left to ask after.
        at = [position.get(name, -1) for name in self.required]
        self.bound_at = sys.maxsize if -1 in at else max(at, default = -1) + 1
        #* Last: ``check_inputs`` goes by ``plan`` alone, and another thread may be in it now.
        self.plan = tuple([entries.get(name) for name in self.pos_names])
        return

    def _problems_of(self, found: "list[tuple[int, Any, Any]] | None", missing: "list[str] | None") -> list[Problem]:
        """
        The problems of a call that ``check_inputs`` refused, made when the error is asked for
        them (``InvalidDataError.problems``): the missing arguments first, then each argument
        that failed, in the order of the parameters however they were passed. ``found`` holds
        ``(order, plan entry, value)``, or ``(order, None, problem)`` for one that was made at once.
        """
        problems: list[Problem] = []
        if missing is not None:
            names, record, fn = tuple(missing), self.record, self.fn
            problems.append(Problem("missing", names, tuple([record.get(m) for m in missing]), None, fn,
                                    partial(missing_msg, fn, names, record, False)))
        if found is not None:
            if len(found) > 1:
                found.sort(key = _first)
            for _, entry, value in found:
                problems.append(value if entry is None else self._problem(entry, value))
        return problems

    def _problem(self, entry: tuple[Any, ...], value: Any, fresh: bool = False) -> Problem:
        """
        The problem for an argument that failed its test and couldn't be converted. Where only the
        type can be wrong it is put together from what the plan holds, and the text is left for
        later (``_render_type``, which keeps the part of the message that is the same for every value).
        Next to a missing argument the reason is looked for as anywhere else (until 2026-10-18 it
        wasn't, after the full path, and a rejected ``Port`` read as a wrong type).

        A value that may have been rejected (``NO_TYPE``) is first asked the short way (see
        ``_only_type``); what that finds is what ``_invalid_reason`` would find first.

        ``fresh``: the pass has just tested and tried to convert this very value, so a refusal by
        its check would be the last one noted (``REFUSED``). Where the short way then finds none,
        for one ``Annotated`` member of a type the value doesn't have and no TypeModel in it, the
        long way would find none either: nothing converts the value (or its conversion would have
        been refused, and noted: then the long way decides), so it is a wrong type. After a hand-over from the compiled wrapper
        (the wrapper tried this value, the pass skips it) only while no argument has failed in the
        pass yet: a check that passes notes nothing, so the last refusal noted is still the wrapper's.
        """
        expected, name, annotation = entry[4], entry[2], entry[6]
        if expected is NO_TYPE:
            quick, failure = entry[5], None
            if type(quick) is TypeContainer:
                failure = quick.constraint_failure(value, self.allow_subclass, True)
            elif quick is not None:
                rejected = REJECTED
                if rejected[0] is value and rejected[1] is quick:
                    failure = (quick, rejected[2])
                    rejected[0] = rejected[1] = rejected[2] = None
            if failure is not None:
                return Problem("invalid", name, failure[0], value, self.fn, (_render_invalid, self), failure[1], annotation)
            if fresh and type(quick) is TypeContainer and _only_a_type(quick, value, self.allow_subclass):
                return Problem("type", name, quick._expected_type, value, self.fn, (_render_type, self), None, annotation)
            container = TypeContainer(self.fn, name, value, annotation)
            return type_problem(container, "type", None, self.allow_subclass, self.convert, self.coerce,
                                quick if type(quick) is TypeContainer else None)
        fn = self.fn
        return Problem("return" if name == "return" else "type", name, expected, value, fn, (_render_type, self), None,
                       annotation)

    def _deep_entry_problems(self, entry: tuple[Any, ...], value: Any) -> "list[Problem]":
        """
        What is wrong inside a ``deep`` argument that failed its test and couldn't be converted:
        what ``_deep_problems`` said of it. Made at once, not when read: the items are the
        caller's, and may change. Next to a missing argument as anywhere else.
        """
        return value_problems(self.fn, entry[2], value, entry[6], entry[5], "type", self.allow_subclass, self.convert,
                              self.coerce)

    def _return_flags(self) -> tuple[bool, bool, bool]:
        """
        ``(allow_subclass, convert, coerce)`` for the return value. It gets the lossless conversions
        (``1`` -> ``1.0``, which ``coerce`` includes) but is never coerced: parsing is for what comes
        in from outside, and a function that returns ``"42"`` for an ``int`` has a bug to report.
        """
        return self.allow_subclass, self.convert or self.coerce, False

    def _fast_ok(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        n_pos = self.n_pos
        extra_args: tuple[Any, ...] = ()
        if len(args) > n_pos:
            if self.var_pos is None:
                return False
            extra_args = args[n_pos:]
        arguments = dict(zip(self.pos_names, args))
        extra_kwargs: dict[str, Any] | None = None
        if kwargs:
            kw_names = self.kw_names
            for k, v in kwargs.items():
                if k in arguments:
                    return False
                if k in kw_names:
                    arguments[k] = v
                elif self.var_kw is not None and k not in self.pos_names:
                    if extra_kwargs is None:
                        extra_kwargs = {}
                    extra_kwargs[k] = v
                else:
                    return False
        for r in self.required:
            if r not in arguments:
                return False
        checks = self.checks
        for k, v in arguments.items():
            chk = checks.get(k)
            if chk is not None and not chk(v):
                return False
        if extra_args and self.var_pos_check is not None:
            if not all(self.var_pos_check(item) for item in extra_args):
                return False
        if self.var_pos_node is not None and not self.var_pos_node.check(extra_args):      # also when there are none
            return False
        if extra_kwargs and self.var_kw_check is not None:
            if not all(self.var_kw_check(item) for item in extra_kwargs.values()):
                return False
        return True

    def _convert(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any], bool]:
        """Replace every failing argument that has a valid conversion. Binding errors are left for the checks."""
        new_args: list[Any] | None = None
        new_kwargs: dict[str, Any] | None = None
        checks, converters = self.checks, self.converters
        for i, value in enumerate(args):
            if i < self.n_pos:
                name = self.pos_names[i]
                check, converter = checks.get(name), converters.get(name)
            else:
                check, converter = self.var_pos_check, self.var_pos_conv
            if converter is not None and check is not None and not check(value):
                if (out := converter(value)) is not FAILED:
                    new_args = new_args or list(args)
                    new_args[i] = out
        for key, value in kwargs.items():
            if key in self.kw_names:
                check, converter = checks.get(key), converters.get(key)
            elif self.var_kw is not None:
                check, converter = self.var_kw_check, self.var_kw_conv
            else:
                continue
            if converter is not None and check is not None and not check(value):
                if (out := converter(value)) is not FAILED:
                    new_kwargs = new_kwargs or dict(kwargs)
                    new_kwargs[key] = out
        node = self.var_pos_node
        if node is not None and node.can_convert and not node.check(rest := args[self.n_pos:]):
            try:
                fixed: Any = node.convert(rest)
            except Exception:
                fixed = FAILED
            if fixed is not FAILED and node.check(fixed):
                new_args = (new_args or list(args))[:self.n_pos] + list(fixed)
        changed = new_args is not None or new_kwargs is not None
        return (tuple(new_args) if new_args is not None else args,
                new_kwargs if new_kwargs is not None else kwargs, changed)

    #* Core checks
    def check_inputs(self, args: tuple[Any, ...], kwargs: dict[str, Any],
                     failed: str | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        Validate a call; returns ``(args, kwargs)`` with converted values swapped in. Raises on failure.

        Where there is a ``plan`` this is one pass: bind the call, test each argument, convert the
        ones that fail and can be, and note the rest. It is where a wrong call spends its time,
        and with tiered compilation where the first calls of every function do, so it is written
        out here in one piece (as a method of its own it cost a wrong call 50 ns more). What is
        noted is not made into problems: the error makes them when it is asked (``_problems_of``),
        except where finding out what is wrong means running the user's code (an ``Annotated``
        check, a TypeModel), which is done now, on the value as it is.

        ``failed`` names a parameter whose test the caller has just run on this call's value, and
        its converter if it has one, to no avail: neither is run again.

        The pass leaves (``break``) a call that doesn't bind for another reason than a missing
        argument, and a missing argument next to a positional one that doesn't fit: there the
        full path looks for a better placement.
        """
        plan = self.plan
        if plan is None and not self.ready:
            self._prepare(args)
            plan = self.plan
        while plan is not None:                         # one round: ``break`` hands the call to the slower way
            n = len(args)
            if n > self.n_pos:
                break
            #* Binding first: nothing is converted for a call that turns out not to bind.
            kw_plan = self.kw_plan
            if kwargs:
                given = self.pos_names[:n]
                unbound = False
                for key in kwargs:
                    if key not in kw_plan or key in given:
                        unbound = True
                        break
                if unbound:
                    break
            missing: list[str] | None = None
            if n < self.bound_at:                       # else every required parameter was given by position
                for name, at in self.required_at:
                    if (at < 0 or at >= n) and name not in kwargs:
                        if missing is None:
                            missing = []
                        missing.append(name)

            found: list[tuple[int, Any, Any]] | None = None
            new_args: list[Any] | None = None
            #* The entry of ``failed``: the compiled wrapper has just run its test, and its
            #* converter, on this call's value. (A positional-only parameter has no entry by name
            #* and is simply tested again.)
            skip = None if failed is None else kw_plan.get(failed)
            misplaced = False
            i = 0
            for value in args:
                entry = plan[i]
                i += 1
                if entry is None:
                    continue
                if entry is not skip and entry[0](value):
                    continue
                if missing is not None:                 # a missing argument and one that doesn't fit: the full path
                    misplaced = True
                    break
                converter = entry[1]
                if converter is not None and entry is not skip and (out := converter(value)) is not FAILED:
                    if new_args is None:
                        new_args = list(args)
                    new_args[i - 1] = out
                    continue
                if found is None:
                    found = []
                if entry[4] is NO_TYPE:
                    found.append((entry[3], None, self._problem(entry, value, entry is not skip or not found)))
                elif entry[4] is DEEP:
                    found += [(entry[3], None, problem) for problem in self._deep_entry_problems(entry, value)]
                else:
                    found.append((entry[3], entry, value))
            if misplaced:
                break
            new_kwargs: dict[str, Any] | None = None
            if kwargs:
                for key, value in kwargs.items():
                    entry = kw_plan[key]
                    if entry is None:
                        continue
                    if entry is not skip and entry[0](value):
                        continue
                    converter = entry[1]
                    if converter is not None and entry is not skip and (out := converter(value)) is not FAILED:
                        if new_kwargs is None:
                            new_kwargs = dict(kwargs)
                        new_kwargs[key] = out
                        continue
                    if found is None:
                        found = []
                    if entry[4] is NO_TYPE:
                        found.append((entry[3], None, self._problem(entry, value, entry is not skip or not found)))
                    elif entry[4] is DEEP:
                        found += [(entry[3], None, problem) for problem in self._deep_entry_problems(entry, value)]
                    else:
                        found.append((entry[3], entry, value))

            if found is not None or missing is not None:
                #* Made by a function, never held in a local here: the error's traceback holds this
                #* frame, and a frame that holds the error makes a cycle of the two, which only
                #* the collector frees (a wrong call cost 350 ns more that way).
                if missing is not None or not self.warn:
                    raise pending_error(self, found, missing)
                warn_of(pending_error(self, found, None))       # and on with the call: what could be converted is
            if new_args is not None:
                args = tuple(new_args)
            if new_kwargs is not None:
                kwargs = new_kwargs
            return args, kwargs

        if self.ready:
            if plan is not None and (said := self._binding_error(args, kwargs)) is not None:
                raise said_error(said, self.error)
            #* Without converters, _type_problems below answers "fine" just as well (it returns []),
            #* so the error path doesn't run every check (and deep scan) one extra time.
            if self.can_convert:
                if self._fast_ok(args, kwargs):
                    return args, kwargs
                args, kwargs, changed = self._convert(args, kwargs)
                if changed and self._fast_ok(args, kwargs):
                    return args, kwargs
            #* Common failure: the call binds fine and only types are wrong. Report it straight
            #* from the prepared layout. Errors are reported on the (partly) converted call.
            problems = self._type_problems(args, kwargs)
            if problems:
                if not self.warn:
                    raise typechecker_type_error_factory(problems, "call", self.error)
                warn_of(typechecker_type_error_factory(problems, "call", self.error))
            if problems is not None:
                return args, kwargs
        #* An argument too many, a name given twice, a keyword nobody takes: said at once, in the
        #* words Signature.bind uses, without running it (it takes 2 µs to arrive at the same sentence).
        if self.ready and (said := self._binding_error(args, kwargs)) is not None:
            raise said_error(said, self.error)
        #* Missing arguments, and whatever else doesn't bind: the full path (with realignment hints).
        try:
            full_check(self.fn, self.record, self.allow_subclass, args, kwargs, self.skip_first,
                        nodes = self.nodes, sig = self.sig, convert = self.convert, coerce = self.coerce)
        except InvalidDataError as e:
            retype(e, self.error)                       # made there as InvalidDataError: the checker's class
            raise
        return args, kwargs

    def _binding_error(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
        """
        What ``Signature.bind`` says of a call that can't be bound for one of the three usual
        reasons, found in the order it finds them: too many positional arguments, a parameter given
        by position and by name, a keyword that no parameter takes. ``None`` for a call that binds,
        and for a positional-only parameter passed by keyword, which the full path words.
        """
        names, parameters = self.pos_names, self.sig.parameters
        positional_only = inspect.Parameter.POSITIONAL_ONLY
        for i in range(len(args)):
            if i >= self.n_pos:
                if self.var_pos is None:
                    return "too many positional arguments"
                break
            if names[i] in kwargs:
                if parameters[names[i]].kind is positional_only:
                    return None
                return f"multiple values for argument {names[i]!r}"
        unknown = None
        for key in kwargs:
            if key in self.kw_names:
                continue
            if key in names:                            # a positional-only parameter, by keyword
                return None
            if unknown is None and self.var_kw is None:
                unknown = key
        return None if unknown is None else f"got an unexpected keyword argument {unknown!r}"

    def with_defaults(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """
        A checked call with the converted defaults of ``inject`` filled in for the parameters it
        leaves out: by keyword where the parameter takes one, else by position (which then needs
        the default of every positional-only parameter before it as well).
        """
        inject, given = self.inject, len(args)
        out: dict[str, Any] | None = None
        by_position: list[str] = []
        for name in inject:                                 # type: ignore[union-attr]
            if name in kwargs:
                continue
            if name in self.kw_names:
                if name not in self.pos_names[:given]:
                    out = out or dict(kwargs)
                    out[name] = inject[name]                # type: ignore[index]
            elif name in self.pos_names[given:]:
                by_position.append(name)
        if by_position:
            last = max(self.pos_names.index(name) for name in by_position)
            parameters = self.sig.parameters
            args += tuple(inject.get(name, parameters[name].default) for name in self.pos_names[given:last + 1])  # type: ignore[union-attr]
        return args, kwargs if out is None else out

    def _type_problems(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> "list[Problem] | None":
        """
        Wrong-type problems for a call that binds cleanly, in the same order and wording as
        the full path. Returns ``None`` when binding isn't clean (let the full path explain).
        Only failing arguments get a ``TypeContainer``.
        """
        n_pos = self.n_pos
        if len(args) > n_pos and self.var_pos is None:
            return None
        arguments = dict(zip(self.pos_names, args))
        extra_kwargs: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key in arguments:
                return None
            if key in self.kw_names:
                arguments[key] = value
            elif self.var_kw is not None and key not in self.pos_names:
                extra_kwargs[key] = value
            else:
                return None
        for name in self.required:
            if name not in arguments:
                return None

        if self.nodes:
            return self._deep_problems(args, arguments, extra_kwargs)
        fn, record, checks = self.fn, self.record, self.checks
        flags = (self.allow_subclass, self.convert, self.coerce)
        problems: list[Problem] = []
        for name in self.check_order:
            if name == self.var_pos:
                check = self.var_pos_check
                if self.var_pos_node is not None:
                    problems += self._unpacked_args_problems(args)
                elif check is not None:
                    problems += [type_problem(TypeContainer(fn, step(name, f"[{i}]", i), item, record[name]), "type", None, *flags)
                                 for i, item in enumerate(args[n_pos:]) if not check(item)]
            elif name == self.var_kw:
                check = self.var_kw_check
                if check is not None:
                    problems += [type_problem(TypeContainer(fn, step(name, f"[{k}]", k), v, record[name]), "type", None, *flags)
                                 for k, v in extra_kwargs.items() if not check(v)]
            elif name in arguments:
                check = checks.get(name)
                if check is not None and not check(arguments[name]):
                    problems.append(type_problem(TypeContainer(fn, name, arguments[name], record[name]), "type", None, *flags))
        return problems

    def _deep_problems(
        self, args: tuple[Any, ...], arguments: dict[str, Any], extra_kwargs: dict[str, Any],
        ) -> "list[Problem]":
        """``_type_problems`` when some parameters have deep checks: one problem per bad item."""
        fn, record, checks, nodes = self.fn, self.record, self.checks, self.nodes
        flags = (self.allow_subclass, self.convert, self.coerce)
        problems: list[Problem] = []
        for name in self.check_order:
            node = nodes.get(name)
            if name == self.var_pos:
                check = self.var_pos_check
                if self.var_pos_node is not None:
                    problems += self._unpacked_args_problems(args)
                elif check is not None:
                    for i, item in enumerate(args[self.n_pos:]):
                        if not check(item):
                            problems += value_problems(fn, step(name, f"[{i}]", i), item, record[name], node, "type", *flags)
            elif name == self.var_kw:
                check = self.var_kw_check
                if check is not None:
                    for k, v in extra_kwargs.items():
                        if not check(v):
                            problems += value_problems(fn, step(name, f"[{k}]", k), v, record[name], node, "type", *flags)
            elif name in arguments:
                check = checks.get(name)
                if check is not None and not check(arguments[name]):
                    problems += value_problems(fn, name, arguments[name], record[name], node, "type", *flags)
        return problems

    def _unpacked_args_problems(self, args: tuple[Any, ...]) -> "list[Problem]":
        """``*args: *tuple[int, str]``: what is wrong with the extra positional arguments, taken as that tuple."""
        rest, node, name = args[self.n_pos:], self.var_pos_node, str(self.var_pos)
        if node.check(rest):
            return []
        return value_problems(self.fn, name, rest, self.var_pos_annotation, node, "type",
                               self.allow_subclass, self.convert, self.coerce)

    def check_return(self, result: Any) -> Any:
        """Validate a return value; returns it (converted if needed). Raises on failure."""
        if not self.ready:
            self._prepare()
        if self.ready:
            chk = self.ret_check
            if "return" not in self.record or chk is None or chk(result):
                return result
            if self.ret_conv is not None and (out := self.ret_conv(result)) is not FAILED:
                return out
            entry = self.ret_entry
            if entry is not None and entry[4] is not NO_TYPE:  # only the type can be wrong: said when the error is read
                if not self.warn:
                    raise pending_error(self, [(0, entry, result)], None)
                warn_of(pending_error(self, [(0, entry, result)], None))
                return result
        allow_subclass, convert, coerce = self._return_flags()
        try:
            typecheck_return_pipeline(self.fn, self.record, allow_subclass, result, self.nodes.get("return"), convert, coerce)
        except InvalidDataError as refused:
            retype(refused, self.error)                 # made there as InvalidDataError: the checker's class
            if not self.warn or not refused.problems:   # with warn: an annotation that can't be read is raised all the same
                raise
            warn_of(refused)
        return result


#* The heads of a checker's messages (``type_head``, ``invalid_head``), at most this many: a head is
#* the same for every wrong value of a parameter, and putting it together was most of rendering one.
_HEADS_MAX = 64


def _head(checker: PreparedChecker, key: tuple[Any, ...], make: Callable[[], str]) -> str:
    """The head under ``key`` (which includes whether colours are on, and the function's owner), made once."""
    heads = checker.heads
    if heads is None:
        heads = checker.heads = {}
    head = heads.get(key)
    if head is None:
        head = make()
        if len(heads) < _HEADS_MAX:
            heads[key] = head
    return head


def _only_a_type(quick: TypeContainer, value: Any, allow_subclass: bool) -> bool:
    """Whether ``value`` can only be of the wrong type for ``quick``'s one ``Annotated`` member (see ``_problem``)."""
    constraints = quick._constraints
    if constraints is None or len(constraints) != 1 or quick._plain_types is not None or quick._literal_values is not None \
            or quick._type_arg is not None:
        return False
    target, checks = constraints[0]
    #* The last refusal noted is by one of these checks: a converted value of this argument was
    #* refused ("-5" coerced to -5 for ``x > 0``), and the long way says so ("invalid").
    if REFUSED[1] in checks:
        return False
    members = tuple(target) if isinstance(target, TypeUnion) else (target,)
    return not any(is_model(m) for m in members) and not matches_type(value, target, allow_subclass)


def _render_type(problem: Problem, checker: PreparedChecker) -> str:
    """The text of a wrong-type problem that ``_problem`` made from a plan entry (``Problem.__str__`` calls it)."""
    fn, name = checker.fn, problem.parameter
    key = ("type", name, coloured(), getattr(fn, OWNER_ATTR, None))
    head = _head(checker, key, lambda: type_head(TypeContainer(fn, name, problem.value, problem.annotation)))
    return head + type_tail(problem.value)


def _render_invalid(problem: Problem, checker: PreparedChecker) -> str:
    """The text of a rejected value that ``_problem`` made from a plan entry."""
    key = ("invalid", problem.parameter, id(problem.expected), coloured(), getattr(checker.fn, OWNER_ATTR, None))
    return _head(checker, key, lambda: invalid_head(problem)) + invalid_tail(problem)


#* In a plan entry: a failure of this parameter may be a rejected value, not only a wrong type.
NO_TYPE: Any = object()
#* In a plan entry: the items of this parameter are checked (``deep``); its node says what is wrong.
DEEP: Any = object()


def _only_type(name: str, annotation: Any, tolerant: bool) -> tuple[Any, Any]:
    """
    The last two parts of a plan entry, ``(expected, quick)``: what a value that fails
    ``annotation`` can have wrong.

    ``expected`` is the runtime type where it can only be the type, and ``NO_TYPE`` where it may
    also be a rejected value: an ``Annotated`` check, or with ``tolerant`` (values are converted) a
    TypeModel. Why a value was rejected is found by ``_invalid_reason``, the long way. ``quick``
    is a shorter one for the usual shapes (``PreparedChecker._problem``): a container of the
    annotation, to ask its checks, or where the annotation has one TypeModel class (``Url``, also
    ``Url | None``), that class: the converter has just run its ``validate`` and left the reason in
    ``REJECTED``, and ``_invalid_reason`` would ask that one model and no other.
    """
    try:
        container = TypeContainer(None, name, None, annotation)
        targets = container._expected_type
        models = [t for t in (targets if isinstance(targets, TypeUnion) else (targets,)) if is_model(t)]
        if container._constraints is not None:
            return NO_TYPE, container
        if not (tolerant and models):
            return targets, None
        if len(models) == 1:
            return NO_TYPE, models[0]
    except Exception:
        pass
    return NO_TYPE, None


def _first(pair: tuple[Any, ...]) -> int:
    return pair[0]
