"""TypeCheckerError and Problem: what is wrong with a call, as data, and how both are pickled."""
from ..formatting_tool import formatter
from ._text import break_trace_colouring, render_error, short_repr
from typing import Any, Callable
import os
import pickle
import sys
import warnings


class TypeCheckerError(TypeError):
    """
    Exception raised for type checking errors.

    ``problems`` holds each issue as a :class:`Problem`. The (coloured) message is only
    built the first time the error is turned into text, so code that catches and
    handles the error never pays for formatting.
    """

    #* Defaults on the class: an error made on the path of a wrong call (``pending_error``,
    #* ``said_error``) sets one attribute and never runs ``__init__``, whose keyword arguments
    #* alone cost more than raising the error does (143 ns against 69).
    context: str = "call"
    _said: str | None = None
    _message: str | None = None
    _problems: "list[Problem] | None" = None
    #* What the problems are made from when they are read: ``(checker, found, missing)``, see
    #* ``PreparedChecker._problems_of``. ``_field_of``: the dataclass whose field was assigned
    #* (the problems are worded for it, see ``as_field_problems``).
    _pending: "tuple[Any, Any, Any] | None" = None
    _field_of: Any = None

    def __init__(
        self,
        message: str = "",
        *,
        problems: "list[Problem] | tuple[Problem, ...]" = (),
        context: str = "call",
        said: str | None = None
        ) -> None:
        #* No super().__init__(message): ``args`` is answered by the property below, from the
        #* message when it is read. A list of problems is taken as it is (it is made for this
        #* error); the error is on the path of every wrong call.
        self._problems = problems if type(problems) is list else list(problems)
        self.context = context
        #* ``said``: a message without problems, in plain words (a call that can't be bound). Like
        #* the others it is put together when it is read: what goes in front of it depends on
        #* whether messages are coloured, and finding that out costs more than raising the error.
        self._said = said
        self._message = message if (message or not (problems or said is not None)) else None

    @property
    def problems(self) -> "list[Problem]":
        """
        Each thing that is wrong, as a :class:`Problem`. For a wrong call they are made when this
        is first read: the error knows which arguments failed, and code that only catches it
        never pays for the objects.
        """
        problems = self._problems
        if problems is None:
            pending = self._pending
            problems = [] if pending is None else pending[0]._problems_of(pending[1], pending[2])
            if self._field_of is not None:
                as_field_problems(problems, self._field_of)
            self._problems, self._pending = problems, None
        return problems

    @problems.setter
    def problems(self, problems: "list[Problem] | tuple[Problem, ...]") -> None:
        self._problems, self._pending = (problems if type(problems) is list else list(problems)), None

    @property
    def message(self) -> str:
        if self._message is None:
            self._message = (
                break_trace_colouring + self._said if self._said is not None
                else render_error(self.problems, self.context)
                )
        return self._message

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r})"

    @property                                   # type: ignore[override]
    def args(self) -> tuple[str]:
        return (self.message,)

    @args.setter
    def args(self, value: tuple[Any, ...]) -> None:        # type: ignore[override]
        self._message = str(value[0]) if value else ""

    def __reduce__(self) -> tuple[Any, ...]:
        #* Rebuilt through a module-level function: pickle can't find the class itself,
        #* because __module__ is "builtins" (see below). The message travels as text, rendered
        #* now, and the problems as data (see Problem.__reduce__).
        return (_restore_error, (self.message, self.context, self.problems))

#* Tracebacks print "TypeCheckerError: ..." instead of the full module path.
TypeCheckerError.__module__ = "builtins"


class TypeCheckerWarning(UserWarning):
    """
    What ``on_error = "warn"`` issues in place of a :class:`TypeCheckerError`: the same message,
    as a warning, and the call goes ahead. ``error`` is the error that was not raised, with its
    ``problems`` as data. It is a category of its own, so the standard filters apply to it alone:
    ``warnings.simplefilter("error", TypeCheckerWarning)`` raises it, ``"always"`` shows every one
    (by default Python shows a warning once for each line it comes from).
    """

    def __init__(self, message: str = "", error: "TypeCheckerError | None" = None) -> None:
        super().__init__(message)
        self.error = error


ON_ERROR = ("raise", "warn")


def warns(on_error: Any) -> bool:
    """Whether ``on_error`` asks for a warning; anything but ``"raise"`` and ``"warn"`` is refused."""
    if on_error == "raise":
        return False
    if on_error == "warn":
        return True
    raise TypeCheckerError(
        break_trace_colouring + f"on_error must be {formatter(repr('raise'), 'bold_yellow')} or "
        f"{formatter(repr('warn'), 'bold_yellow')}, got {formatter(short_repr(on_error, 60), 'bold_red')}"
        )


#* Frames that are not the caller's: the package's own files, and the code it generates.
_OUR_FILES = (os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + os.sep, "<enforced")


def warn_of(error: TypeCheckerError) -> None:
    """
    Issue ``error`` as a :class:`TypeCheckerWarning`, in the name of the line that made the call:
    the first frame outside this package (and outside the ``__init__`` that ``dataclasses``
    generates). Python shows a warning once per line it is attributed to, so one mistake in a
    loop is reported once, and two mistakes on different lines are both reported; attributed to
    a line in here, every warning of a program after the first would have been dropped.
    """
    frame: Any = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        name = code.co_filename
        if not (name.startswith(_OUR_FILES) or (name == "<string>" and code.co_qualname.startswith("__create_fn__"))):
            break
        frame = frame.f_back
    message = TypeCheckerWarning(str(error), error)
    if frame is None:
        warnings.warn_explicit(message, TypeCheckerWarning, "<unknown>", 1)
        return
    scope = frame.f_globals
    warnings.warn_explicit(message, TypeCheckerWarning, frame.f_code.co_filename, frame.f_lineno,
                           scope.get("__name__"), scope.setdefault("__warningregistry__", {}))


_new_error = TypeError.__new__


def pending_error(checker: Any, found: Any, missing: Any) -> TypeCheckerError:
    """The error of a wrong call, made without its problems: see ``TypeCheckerError.problems``."""
    error: TypeCheckerError = _new_error(TypeCheckerError)
    error._pending = (checker, found, missing)
    return error


def said_error(said: str) -> TypeCheckerError:
    """``TypeCheckerError(said = said)``, without the cost of ``__init__``."""
    error: TypeCheckerError = _new_error(TypeCheckerError)
    error._said = said
    return error


def field_error(checker: Any, entry: Any, value: Any, cls: type) -> TypeCheckerError:
    """The error of a value assigned to a field of the dataclass ``cls`` that has the wrong type."""
    error: TypeCheckerError = _new_error(TypeCheckerError)
    error._pending = (checker, [(0, entry, value)], None)
    error._field_of = cls
    error.context = "field assignment"
    return error


#* Set by ``_dataclass._field_messages``: ``(problems, cls)``, words the problems of a failed assignment
#* for the dataclass (this module can't import that one).
as_field_problems: Any = None


def _restore_error(message: str, context: str = "call", problems: "list[Problem] | tuple[Problem, ...]" = ()) -> TypeCheckerError:
    """Unpickle a TypeCheckerError: its message as it was rendered, its context and its problems."""
    return TypeCheckerError(message, problems = problems, context = context)


class Unpickled:
    """
    Stands in an unpickled ``Problem`` for a part that could not travel: a value of a local class,
    a lock, a function that pickle can't find by name. It shows the ``repr`` of what it replaces.
    """
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Unpickled) and other.text == self.text

    def __hash__(self) -> int:
        return hash(self.text)

    def __reduce__(self) -> tuple[Any, ...]:
        return (Unpickled, (self.text,))


def _picklable(part: Any) -> Any:
    """``part`` if pickle takes it, else a stand-in that shows its repr."""
    if part is None or type(part) in (str, int, float, bool):
        return part
    try:
        pickle.dumps(part)
        return part
    except Exception:
        return Unpickled(short_repr(part, 80))


def _origin_reference(origin: Any) -> Any:
    """
    How the function or class a problem belongs to is pickled. A decorated function can't go by
    name the usual way: its name leads to the wrapper, and what the problem holds is the function
    inside. So it goes as ``(module, qualname)`` when following that name, and then the wrappers,
    leads back to it; a class goes as it is; anything else as a stand-in.

    The accessor of a property goes as ``(module, qualname, which)``: the name leads to the
    property, whose getter and setter share it, and ``which`` says which of them it is.
    """
    module, qualname = getattr(origin, "__module__", None), getattr(origin, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str) and not isinstance(origin, type):
        for which in (None, *_ACCESSORS):
            try:
                if _find_origin(module, qualname, which) is origin:
                    return (module, qualname) if which is None else (module, qualname, which)
            except Exception:
                pass
    return _picklable(origin)


#* Where a property (fget, fset, fdel) and a functools.cached_property (func) keep their functions.
_ACCESSORS = ("fget", "fset", "fdel", "func")


def _find_origin(module: str, qualname: str, which: str | None = None) -> Any:
    """
    The function that ``module.qualname`` names, or the one an enforced wrapper found there checks.
    With ``which``, the name is a property's and the function is that accessor of it.
    """
    found: Any = sys.modules.get(module) or __import__(module, fromlist = ["*"])
    for part in qualname.split("."):
        found = getattr(found, part)
    if which is not None:
        if which not in _ACCESSORS:                     # the reference comes out of a pickle: only these are read
            raise ValueError(which)
        found = getattr(found, which)
    found = getattr(found, "__func__", found)           # a method, a class method
    inner = found
    for _ in range(16):
        if "_pv_bootstrap" in getattr(inner, "__globals__", ()):    # a wrapper made by wrap_callable
            return inner.__wrapped__
        inner = getattr(inner, "__wrapped__", None)
        if inner is None:
            break
    return found


def _unpickle_and_restore_problem(
    kind: str,
    parameter: Any,
    expected: Any,
    value: Any,
    origin: Any,
    detail: Any,
    annotation: Any,
    text: str
    ) -> "Problem":
    """Unpickle a Problem object: its data, and its message as text."""
    if type(origin) is tuple:
        try:
            origin = _find_origin(*origin)
        except Exception:
            origin = Unpickled(".".join(origin))
    problem = Problem(kind, parameter, expected, value, origin, str, detail, annotation)
    problem._text = text
    return problem


type ErrorMessage = str

class Problem:
    """
    One thing wrong with a call or a definition, kept as data.

    Attributes:
        kind: ``"type"`` (an argument), ``"default"``, ``"return"`` or ``"missing"``; with deep
            checks also ``"length"`` (a fixed tuple of the wrong length), ``"missing_key"``
            (a required TypedDict key) and ``"cycle"`` (data that contains itself). ``"invalid"``
            is a value of the right type that is rejected all the same: a failed ``Annotated``
            check or TypeModel ``validate``, keys that collide after conversion, a container
            whose type can't hold its converted items.
        parameter: The parameter name (``"args[2]"`` / ``"kwargs[b]"`` for varargs items);
            for ``"missing"``, a tuple of all missing names. With deep checks, the path to
            the bad item: ``"scores[3]"``, ``"prices['apple']"``, ``"point.x"``, ``"return[0]"``.
        expected: The expected type (for ``"missing"``, a tuple of annotations).
        annotation: The annotation as it was written, where the problem is about one value:
            ``Literal['r', 'w']`` where ``expected`` is the type of those values (``str``).
        value: The offending value (``None`` for ``"missing"`` and ``"missing_key"``).
        origin: The function or class being checked.
        detail: Extra data: the expected length for ``"length"``, the key for ``"missing_key"``,
            the reason for ``"invalid"``.

    ``str(problem)`` gives the coloured one-line message.
    """
    __slots__ = ("kind", "parameter", "expected", "value", "origin", "detail", "annotation", "_render", "_text")

    def __init__(
        self,
        kind: str,
        parameter: Any,
        expected: Any,
        value: Any,
        origin: Any,
        render: "Callable[[], str] | tuple[Any, ...]",
        detail: Any = None,
        annotation: Any = None
        ) -> None:
        self.kind = kind
        self.parameter = parameter
        self.expected = expected
        self.annotation = annotation
        self.value = value
        self.origin = origin
        self.detail = detail
        self._render = render
        self._text: str | None = None
        return

    def __str__(self) -> str:
        text = self._text
        if text is None:
            #* ``(function, *arguments)``: a renderer that needs the problem itself is called with
            #* it in front. Held as a ``partial`` over the problem it made a cycle of the two, and
            #* every such error was left to the collector.
            render: Any = self._render
            text = self._text = str(render[0](self, *render[1:]) if type(render) is tuple else render())
        return text

    def __repr__(self) -> str:
        return f"Problem(kind={self.kind!r}, parameter={self.parameter!r}, expected={self.expected!r}, value={short_repr(self.value)})"

    def __reduce__(self) -> tuple[Any, ...]:
        #* A problem travels as data, with its message as text: what renders the message holds the
        #* function, the value and the annotation, and any of them may refuse to be pickled. A part
        #* that refuses is replaced by a stand-in (``Unpickled``), so the error still arrives.
        return (
            _unpickle_and_restore_problem, (
                self.kind,
                _picklable(self.parameter),
                _picklable(self.expected),
                _picklable(self.value),
                _origin_reference(self.origin),
                _picklable(self.detail),
                _picklable(self.annotation),
                str(self),
                )
            )
