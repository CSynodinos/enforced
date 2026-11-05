"""
The names a string annotation may use besides its module's: those local to where the definition
is written, kept at decoration or read when the enclosing function returns.
"""
from ._lifetime import CACHE_LOCK, can_go, frame_above
from typing import Any, Callable, ForwardRef, get_origin, Literal
from .._compat import Format, get_annotations
from dataclasses import InitVar
from functools import cached_property
from types import CodeType, FunctionType
import __future__
import ast
import builtins
import inspect
import re
import sys


def look_again(fn: Any, owner: type | None) -> bool:
    """
    An annotation of ``fn`` names something unknown. If ``fn`` (or its class) was defined inside a
    function, the name may be local to that function and have come into being after the decorator
    ran: a class written a few lines further down. While that function is still running, as it is
    in a test that defines its classes and then uses them, its frame is on the stack, and the
    names are looked up there once more. Nothing is kept alive for this: once the function has
    returned, such a name can't be found any more. Returns whether a new name was found.
    """
    new = False
    for target in (owner, fn):
        if target is None or "<locals>" not in getattr(target, "__qualname__", ""):
            continue
        known = set(vars(target).get(_SCOPE) or ())         # its own: a class would also show its base's
        remember_scope(target, frame_above(2), 64, False)
        new = new or bool(set(vars(target).get(_SCOPE) or ()) - known)
    return new


def unwrapped(fn: Any) -> Any:
    try:
        return inspect.unwrap(fn)
    except ValueError:                                  # a __wrapped__ chain that loops
        return fn


#* Where a function or class decorated inside another function keeps the local names its string
#* annotations use (see ``remember_scope``).
_SCOPE = "__enforced_scope__"
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def local_names(fn: Any, owner: type | None) -> dict[str, Any] | None:
    """
    What a string annotation of ``fn`` may name besides the globals of its module: the class it
    belongs to, the type parameters of that class (``class Box[T]``), and what was local to the
    function it was defined in. ``None`` when there is nothing.
    """
    names: dict[str, Any] = {}
    if owner is not None:
        for klass in reversed(owner.__mro__[:-1]):          # base classes first: the class itself wins
            names.update(vars(klass).get(_SCOPE) or ())
            for parameter in getattr(klass, "__type_params__", ()):
                names[parameter.__name__] = parameter
        names[owner.__name__] = owner
    own = getattr(fn, "__dict__", None)                 # where remember_scope left it: on the function itself
    if own and (scope := own.get(_SCOPE)):
        names.update(scope)
    return names or None


def remember_scope(target: Any, frame: Any, depth: int = 16, later: bool = True) -> None:
    """
    ``target`` (a function or a class) was decorated inside a function. A string annotation of it
    may name something local to that function, such as a class defined a few lines above, and by the
    first call that scope is gone. So the names its annotations use are looked up now, in the frames
    the definition is written in, and what is found is kept on ``target``.

    Only string annotations need this: under ``from __future__ import annotations`` every
    annotation is one. Without that import Python 3.14 keeps the enclosing scope itself, and 3.13 has
    evaluated every unquoted annotation already.

    For a class: its annotations, those of its methods and properties, and those of a base that can go
    as it can (written in a function, or made with ``type()``). A base its module holds means what the names mean there.

    A name that is nowhere yet may be defined further down in the same function. With ``later``,
    it is looked for once more when that function ends (see ``_when_it_ends``).
    """
    try:
        texts: list[str] = []
        if isinstance(target, type):
            fields = vars(target).get("__dataclass_fields__", ())
            for name, member in list(vars(target).items()):     # a list: reading annotations may move them in the class
                #* What ``dataclasses`` generated holds the fields of the bases too, whose names mean what they mean
                #* there. A field's default is a value, also a function written elsewhere: no member of this class.
                if name not in fields and not (fields and name == "__init__"):
                    for function in _functions_of(member):
                        texts += _annotation_texts(unwrapped(function))
            for klass in target.__mro__[:-1]:
                #* A base its module holds resolves there: the same name may mean something else
                #* here, and looking for it would only cost.
                if klass is target or can_go(klass):
                    texts += _annotation_texts(klass)
        else:
            texts = _annotation_texts(target)
        wanted = _names_in(texts)
        if not wanted:
            return
        qualname, module = target.__qualname__, target.__module__
        found: dict[str, Any] = {}
        parents: list[Any] = []
        scopes: list[Any] = []
        for _ in range(depth):
            if frame is None or frame.f_locals is frame.f_globals:      # module level: those names are globals
                break
            #* Only the scopes the definition is written in, not whatever happens to be calling.
            if frame.f_globals.get("__name__") == module and qualname.startswith(frame.f_code.co_qualname + "."):
                #* Of a function that calls itself, the innermost call is the one this was written in.
                if all(frame.f_code is not parent.f_code for parent in parents):
                    parents.append(frame)
                scopes.append(frame.f_locals)
            frame = frame.f_back
        _look_up(wanted, scopes, found)
        _keep_scope(target, found)
        if later and parents:
            known = parents[0].f_globals
            missing = [name for name in wanted if name not in found and name not in known
                       and not hasattr(builtins, name) and name != target.__name__]
            if missing:
                _when_it_ends(parents, target, missing)
    except Exception:                                   # never a reason for a definition to fail
        pass


def _look_up(wanted: set[str], scopes: list[Any], found: dict[str, Any]) -> None:
    """Fill ``found`` from ``scopes``, innermost first. An alias found (``Al = Optional['Loc']``) wants what it quotes as well."""
    waiting = list(wanted)
    while waiting:
        name = waiting.pop()
        if name in found:
            continue
        for scope in scopes:
            if name in scope:
                found[name] = value = scope[name]
                try:
                    if not isinstance(value, type) and (texts := strings_in(value)):
                        waiting += _names_in(texts)
                except Exception:                       # any object may stand there, and refuse to be read
                    pass
                break


def _keep_scope(target: Any, found: dict[str, Any]) -> None:
    """Add ``found`` to the local names kept on ``target`` (from an earlier look: kept, what is found now comes on top)."""
    if found:
        known = vars(target).get(_SCOPE)
        setattr(target, _SCOPE, {**known, **found} if known else found)


def _functions_of(member: Any) -> list[Any]:
    """The functions a class checks through one of its members: a method, or the accessors of a property."""
    if isinstance(member, property):
        return [accessor for accessor in (member.fget, member.fset, member.fdel) if accessor is not None]
    if isinstance(member, cached_property):
        return [member.func]
    member = getattr(member, "__func__", member)
    return [member] if isinstance(member, FunctionType) else []


def _names_in(texts: list[str]) -> set[str]:
    """
    The names in annotations written out as text. A regular expression does for one without quotes, and
    is cheap: this runs for every local definition under the future import. One with quotes is read with
    ``ast``: a quoted text is another annotation (``Optional['Loc']``, ``list['Loc']``), except for the
    values of a ``Literal`` and the metadata of an ``Annotated``. Names stand there too (``Literal[Color.RED, 'x']``).
    """
    found: set[str] = set()
    for text in texts:
        if "'" in text or '"' in text:
            _names_of_text(text, found)
        else:
            found.update(_NAME.findall(text))
    return found


def _names_of_text(text: str, found: set[str]) -> None:
    try:
        #* As a tuple's item: ``*tuple[int, str]`` stands only there. So does ``typing.ForwardRef`` read one.
        #* On a line of its own, the bracket: the text may end in a comment.
        _collect_names(ast.parse(f"({text}\n,)", mode = "eval"), found, True)
    except (SyntaxError, ValueError):                   # text that is no annotation names nothing
        pass


def _collect_names(node: ast.AST, found: set[str], quoted: bool) -> None:
    """``quoted``: whether a string at this place is an annotation in its turn."""
    if isinstance(node, ast.Name):
        found.add(node.id)
    elif isinstance(node, ast.Constant):
        if quoted and isinstance(node.value, str):
            _names_of_text(node.value, found)
    elif isinstance(node, ast.Subscript):
        base = node.value.attr if isinstance(node.value, ast.Attribute) else getattr(node.value, "id", None)
        _collect_names(node.value, found, quoted)
        if base == "Literal":
            _collect_names(node.slice, found, False)
        elif base == "Annotated" and isinstance(node.slice, ast.Tuple) and node.slice.elts:
            _collect_names(node.slice.elts[0], found, quoted)
            for metadata in node.slice.elts[1:]:
                _collect_names(metadata, found, False)
        else:
            _collect_names(node.slice, found, quoted)
    else:
        for child in ast.iter_child_nodes(node):
            _collect_names(child, found, quoted)


def strings_in(annotation: Any, depth: int = 0) -> list[str]:
    """What is still a string in an evaluated annotation: all of it (``"Loc"``), or a part (``Optional["Loc"]``)."""
    if isinstance(annotation, str):
        return [annotation]
    if isinstance(annotation, ForwardRef):
        return [annotation.__forward_arg__]
    if isinstance(annotation, InitVar):                 # keeps what it was given, and has no ``__args__``
        return strings_in(annotation.type, depth + 1)
    args = getattr(annotation, "__args__", None)
    if not args or depth > 8 or type(args) is not tuple or get_origin(annotation) is Literal:
        return []
    return [text for arg in args for text in strings_in(arg, depth + 1)]


def _annotation_texts(obj: Any) -> list[str]:
    """
    What is a string in the annotations of ``obj`` (a function or a class): all of them under ``from
    __future__ import annotations``, otherwise what was written in quotes. Nothing is evaluated: 3.13 has
    done that, and later versions are left to do it when the annotation is needed. Empty when no annotation
    is a string: then Python itself remembers the enclosing scope, and there is nothing to look up.
    """
    try:
        annotate = getattr(obj, "__annotate__", None)
        if annotate is None:
            #* On 3.13 always; else a class under the future import, or annotations assigned by hand: they are simply there.
            #* Once read they have moved: from 3.14 to the cache.
            own = vars(obj) if isinstance(obj, type) else None
            found = (own.get("__annotations__") or own.get("__annotations_cache__")) if own is not None else getattr(obj, "__annotations__", None)
            return [text for annotation in (found or {}).values() for text in strings_in(annotation)]
        code = getattr(obj, "__code__", None)
        if code is not None:
            if code.co_flags & _FUTURE_ANNOTATIONS:
                return [text for text in annotate(Format.VALUE).values() if isinstance(text, str)]
            #* Without the import, decorating a local function must stay as cheap as it was. A quoted
            #* annotation shows as a string among the constants of the annotate function, next to the
            #* parameter names: no other string there means nothing is quoted (the usual case).
            names: Any = code.co_varnames[:code.co_argcount + code.co_kwonlyargcount + bool(code.co_flags & 4) + bool(code.co_flags & 8)]
            if not any(text not in names and text != "return" for text in _string_constants(annotate)):
                return []
        elif isinstance(obj, type) and "__annotations_cache__" in vars(obj):
            #* The same test for a class whose annotations have been read already (dataclasses does).
            names = vars(obj)["__annotations_cache__"]
            if not any(text not in names for text in _string_constants(annotate)):
                return []
        return [text for text in get_annotations(obj, format = Format.STRING).values() if isinstance(text, str)]
    except Exception:
        return []


def _string_constants(annotate: Any) -> list[str]:
    """The string constants of a compiler-made annotate function (those folded into a tuple included)."""
    found: list[str] = []
    for constant in getattr(getattr(annotate, "__code__", None), "co_consts", ()):
        if isinstance(constant, str):
            found.append(constant)
        elif isinstance(constant, tuple):
            found += [item for item in constant if isinstance(item, str)]
    return found


_FUTURE_ANNOTATIONS = __future__.annotations.compiler_flag


#* Under this name a running function carries, among its own local names, what is to be looked up
#* in it when it ends: [(target, names)]. In the frame, and never the frame somewhere else: a frame
#* keeps its caller's frames, and with them every local of the whole stack, alive for as long as
#* it is held (review finding 31). What the frame carries goes when the frame goes.
_PENDING = "__enforced_pending__"
#* code -> how many of its frames carry something; the code is watched while there is one.
_WATCHED: dict[CodeType, int] = {}
_WATCHER: list[Any] = []                                # [tool id], or [None] where none could be had


def _watcher() -> int | None:
    """
    The ``sys.monitoring`` tool id under which enforced hears of a function returning, taken on
    first use: one of the two that no kind of tool is assigned (debuggers, coverage, profilers and
    the optimiser have theirs). ``None`` when both are taken: then a later name is found as before,
    only while its function runs.
    """
    if not _WATCHER:
        chosen = None
        try:
            monitoring = sys.monitoring
            for tool in (4, 3):
                if monitoring.get_tool(tool) is None:
                    monitoring.use_tool_id(tool, "enforced")
                    monitoring.register_callback(tool, monitoring.events.PY_RETURN, _it_returned)
                    chosen = tool
                    break
        except Exception:
            chosen = None
        _WATCHER.append(chosen)
    return _WATCHER[0]


def _when_it_ends(frames: list[Any], target: Any, names: list[str]) -> None:
    """
    ``target`` was decorated inside the functions that ``frames`` are running, and its annotations
    use ``names`` that exist nowhere yet: a class written a few lines further down. They can't be
    waited for by keeping the frame (see ``_PENDING``). So Python is asked to say when each of these
    functions returns: at that moment its local names are final, and the ones wanted are read from
    it (``_it_returned``) and kept on ``target``.

    Only the code of these functions is watched, and only while one of their frames is waited
    for. (A frame that is left by an exception is never heard of: its function stays watched,
    which costs a call at each of its returns and nothing else.)
    """
    tool = _watcher()
    if tool is None:
        return
    for frame in frames:
        code = frame.f_code
        if not code.co_flags & inspect.CO_OPTIMIZED:    # a class body: its names are the class's attributes
            continue
        local = frame.f_locals
        pending = local.get(_PENDING)
        if pending is None:
            local[_PENDING] = pending = []
            with CACHE_LOCK:
                _WATCHED[code] = _WATCHED.get(code, 0) + 1
                if _WATCHED[code] == 1:
                    sys.monitoring.set_local_events(tool, code, sys.monitoring.events.PY_RETURN)
        pending.append((target, names))


def _it_returned(code: CodeType, *_: Any) -> None:
    """Called by Python when a watched function returns: the frame that returns is the caller's."""
    try:
        returning = frame_above()
        if returning is None:                           # a Python without frames: nothing to read
            return
        local = returning.f_locals
        pending = local.get(_PENDING)
        if pending is None:                             # another call of the same function: nothing waits for it
            return
        with CACHE_LOCK:
            left = _WATCHED.get(code, 1) - 1
            if left > 0:
                _WATCHED[code] = left
            else:
                _WATCHED.pop(code, None)
                sys.monitoring.set_local_events(_WATCHER[0], code, 0)
        for target, names in pending:
            known = vars(target).get(_SCOPE) or ()      # a name an inner function has supplied stays
            _keep_scope(target, {name: local[name] for name in names if name in local and name not in known})
    except Exception:                                   # never a reason for the function that returned to fail
        pass


def resolver(fn: Any, owner: type | None) -> Callable[[str], Any]:
    """
    ``text -> object`` for a name that is still a string inside an annotation, as in the old way
    to write a recursive alias: ``Json = Union[int, List["Json"]]``. It is evaluated where the
    annotation was written: in the module of ``fn``, with its local names. Only ever given text
    from source code, never a string of a validate_record record.
    """
    namespaces: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    def resolve(text: str) -> Any:
        if not namespaces:                              # on first use: most annotations have no such name
            target = unwrapped(fn)
            globalns = getattr(target, "__globals__", None)
            if globalns is None:
                module = sys.modules.get(getattr(target, "__module__", None) or "")
                globalns = vars(module) if module is not None else {}
            namespaces.append((globalns, local_names(fn, owner)))
        return eval(text, *namespaces[0])
    return resolve
