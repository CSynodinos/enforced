"""InvalidDataError and Problem: what is wrong with a call, as data, and how both are pickled."""

from .._colours import colours_on, decide, decision, formatter, release, strip_colours
from ._text import break_trace_colouring, made_dataclass, render_error, short_repr
from ._lifetime import findable, frame_above
from ._shared_names import BOOTSTRAP_CODE_KEY
from typing import Any, Callable, Literal
from itertools import islice
import collections
import json
import math
import os
import pickle
import re
import sys
import threading
import warnings


#* Taken when the problems of an error are first made, never when it is raised. Two threads that
#* read ``e.problems`` at once shared the notes being sorted, and one of them got no problems at
#* all (1 error in 20 under a tight switch interval). Reentrant: no deadlock should making one ever read another error.
_MAKING = threading.RLock()


class InvalidDataError(TypeError):
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
            with _MAKING:
                problems = self._problems
                if problems is None:                    # not made by another thread meanwhile
                    pending = self._pending
                    problems = [] if pending is None else pending[0]._problems_of(pending[1], pending[2])
                    if self._field_of is not None:
                        as_field_problems(problems, self._field_of)
                    self._problems, self._pending = problems, None
        return problems

    @problems.setter
    def problems(self, problems: "list[Problem] | tuple[Problem, ...]") -> None:
        with _MAKING:                                   # not overwritten by a first read under way
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

    def errors(self, *, include_input: bool = True, include_context: bool = True) -> list[dict[str, Any]]:
        """
        The problems as a list of dictionaries, in pydantic's shape: ``type`` (the problem's
        ``kind``), ``loc`` (where: ``["prices", "apple", 1]``), ``msg`` (what is wrong, in plain
        text, without the value), ``input`` (the value, made JSON-safe) and ``ctx`` (what was
        expected, the reason of a refusal, the function or class). Every value in it can be
        written as JSON as it is: ``json.dumps(e.errors())`` never fails.

        ``include_input = False`` leaves the values out: the input is echoed otherwise, also to an
        API client that gets these as a response. A ``SecretStr`` is masked either way.
        ``include_context = False`` leaves ``ctx`` out. A missing argument is one entry per name.
        """
        problems = self.problems
        if not problems:                                # an error that is a sentence: a call that can't be bound ...
            entry: dict[str, Any] = {
                "type": "binding" if self._said is not None else "error",
                "loc": [],
                "msg": plain(self.message).strip(),
                }
            if include_context:
                entry["ctx"] = {"context": self.context}
            return [entry]
        entries: list[dict[str, Any]] = []
        for problem in problems:
            entries += details_of(problem, self.context, include_input, include_context)
        return entries

    def json(self, *, include_input: bool = True, include_context: bool = True, indent: int | None = None) -> str:
        """``errors()`` as a JSON string: the body of a 422 response, say. The options are those of ``errors``."""
        return json.dumps(
            self.errors(include_input = include_input, include_context = include_context),
            indent = indent,
            ensure_ascii = False,
            allow_nan = False,
            default = _last_resort
            )

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
        #* now, and the problems as data (see Problem.__reduce__). A subclass (``error = ...``)
        #* travels as itself where pickle can find it by name, else as this class.
        cls = type(self)
        if cls is InvalidDataError or not findable(cls):
            return (_restore_error, (self.message, self.context, self.problems))
        return (_restore_error, (self.message, self.context, self.problems, cls))

#* Tracebacks print "InvalidDataError: ..." instead of the full module path.
InvalidDataError.__module__ = "builtins"


#* What travels as ``warn``: ``False``, or the class ``on_error = "warn"`` issues (so ``warning`` needs no road of its own).
type WarnAs = type[InvalidDataWarning] | Literal[False]


class InvalidDataWarning(UserWarning):
    """
    What ``on_error = "warn"`` issues in place of a :class:`InvalidDataError`: the same message,
    as a warning, and the call goes ahead. ``error`` is the error that was not raised, with its
    ``problems`` as data. It is a category of its own, so the standard filters apply to it alone:
    ``warnings.simplefilter("error", InvalidDataWarning)`` raises it, ``"always"`` shows every one
    (by default Python shows a warning once for each line it comes from).
    """

    def __init__(self, message: str = "", error: "InvalidDataError | None" = None) -> None:
        super().__init__(message)
        self.error = error

    def __reduce__(self) -> Any:
        #* A subclass's ``__init__`` may take a library's own arguments, and is never run for what enforced issues.
        return (_restore_warning, (type(self) if findable(type(self)) else InvalidDataWarning, str(self), self.error))

    def shown(self) -> str:
        """
        The message as a terminal shows it. ``str`` stays plain, so that a filter's ``message`` regex
        matches on a terminal as it does elsewhere; the colours are here. A subclass may add its own.
        """
        return str(self) if self.error is None else str(self.error)


#* Python writes "file:line: Category: message" itself, so only its formatter can colour the first three.
#* ``_formatwarnmsg_impl`` is private, but ``warnings.formatwarning`` isn't the place: replacing that one
#* costs every other warning its "Object allocated at" lines, and a program's own replacement should win.
_standard_format = getattr(warnings, "_formatwarnmsg_impl", None)


def _format_warning(msg: Any) -> str:
    """What the standard formatter writes, with the head of one of our warnings coloured. Others pass through."""
    text = _standard_format(msg)                                    # type: ignore[misc]  # set only where it exists
    message = msg.message
    if not isinstance(message, InvalidDataWarning) or not colours_on():
        return text
    plain = f"{msg.filename}:{msg.lineno}: {msg.category.__name__}: {message}\n"
    if not text.startswith(plain):
        return text
    try:
        shown = message.shown()
    except Exception:                                               # a subclass's own, without its __init__: never fail a warning
        shown = str(message)
    return (f"{formatter(msg.filename, 'cyan')}:{formatter(msg.lineno, 'bold_yellow')}: "
            f"{formatter(msg.category.__name__, 'bold_orange')}: {shown}\n{text[len(plain):]}")


if _standard_format is not None:
    setattr(warnings, "_formatwarnmsg_impl", _format_warning)


ON_ERROR = ("raise", "warn")


def warns(on_error: Any, warning: Any = InvalidDataWarning) -> WarnAs:
    """
    What ``on_error`` asks for: ``False``, or the class of the warning to issue. Anything but ``"raise"``
    and ``"warn"`` is refused, and a ``warning`` that isn't a subclass of ``InvalidDataWarning``, under either.
    """
    if warning is not InvalidDataWarning:
        check_warning_type(warning)
    if on_error == "raise":
        return False
    if on_error == "warn":
        return warning
    raise InvalidDataError(
        break_trace_colouring + f"on_error must be {formatter(repr('raise'), 'bold_yellow')} or "
        f"{formatter(repr('warn'), 'bold_yellow')}, got {formatter(short_repr(on_error, 60), 'bold_red')}"
        )


#* Frames that are not the caller's: the package's own files, and the code it generates.
_OUR_FILES = (os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + os.sep, "<enforced")


def check_warning_type(warning: Any) -> "type[InvalidDataWarning]":
    """``warning``, the class ``on_error = "warn"`` issues (the ``warning`` option of every API), checked where it is written."""
    if isinstance(warning, type) and issubclass(warning, InvalidDataWarning):
        return warning
    raise InvalidDataError(
        break_trace_colouring + f"warning must be {formatter('InvalidDataWarning', 'bold_yellow')} or a subclass of it, "
        f"got {formatter(short_repr(warning, 60), 'bold_red')}"
        )


def _restore_warning(cls: "type[InvalidDataWarning]", message: str, error: "InvalidDataError | None") -> "InvalidDataWarning":
    restored = cls.__new__(cls)
    InvalidDataWarning.__init__(restored, message, error)
    return restored


def warn_of(error: InvalidDataError, warning: "type[InvalidDataWarning]") -> None:
    """
    Issue ``error`` as a ``warning``, in the name of the line that made the call:
    the first frame outside this package (and outside the ``__init__`` that ``dataclasses``
    generates). Python shows a warning once per line it is attributed to, so one mistake in a
    loop is reported once, and two mistakes on different lines are both reported; attributed to
    a line in here, every warning of a program after the first would have been dropped.
    """
    frame: Any = frame_above()
    while frame is not None:
        code = frame.f_code
        name = code.co_filename
        if not (name.startswith(_OUR_FILES) or (name == "<string>" and code.co_qualname.startswith("__create_fn__"))):
            break
        frame = frame.f_back
    message = _restore_warning(warning, plain(str(error)), error)   # as for an error, a subclass's __init__ is never run
    if frame is None:
        warnings.warn_explicit(message, warning, "<unknown>", 1)
        return
    scope = frame.f_globals
    warnings.warn_explicit(message, warning, frame.f_code.co_filename, frame.f_lineno,
                           scope.get("__name__"), scope.setdefault("__warningregistry__", {}))


_new_error = TypeError.__new__


# ── error = ...: the class a checker raises ──────────────────────────────────

def check_error_type(error: Any) -> "type[InvalidDataError]":
    """
    ``error``, the class a checker is to raise (the ``error`` option of every API), checked where it is
    written: a subclass of ``InvalidDataError`` (or that class itself, the default). Its instances must
    have the base's layout: an error made inside enforced (an annotation it can't read) is given the
    class afterwards (``retype``), which a subclass with ``__slots__`` of its own refuses.
    """
    if isinstance(error, type) and issubclass(error, InvalidDataError):
        if error is not InvalidDataError:
            probe: InvalidDataError = _new_error(InvalidDataError)
            try:
                probe.__class__ = error
            except TypeError:
                raise InvalidDataError(
                    break_trace_colouring + f"error = {formatter(error.__qualname__, 'bold_red')}: its instances are laid "
                    f"out unlike InvalidDataError's ({formatter('__slots__', 'bold_yellow')} of its own?): keep the "
                    f"attributes a subclass needs in its dictionary, or on the class"
                    ) from None
        return error
    raise InvalidDataError(
        break_trace_colouring + f"error must be a subclass of {formatter('InvalidDataError', 'bold_yellow')}, "
        f"got {formatter(short_repr(error, 60), 'bold_red')}"
        )


def retype(error: InvalidDataError, cls: "type[InvalidDataError]") -> InvalidDataError:
    """``error`` as an instance of ``cls`` (a checker's ``error``), where enforced made it as its own class."""
    if cls is not InvalidDataError and type(error) is InvalidDataError:
        error.__class__ = cls
    return error


def make_error(cls: "type[InvalidDataError]", message: str = "", *, problems: "list[Problem] | tuple[Problem, ...]" = (),
               context: str = "call", said: str | None = None) -> InvalidDataError:
    """
    ``cls(message, problems = ..., ...)`` with ``InvalidDataError``'s own ``__init__``: a subclass's
    ``__init__`` is never run by enforced (it may take other arguments, as a library's error does).
    """
    if cls is InvalidDataError:
        return InvalidDataError(message, problems = problems, context = context, said = said)
    error: InvalidDataError = _new_error(cls)
    InvalidDataError.__init__(error, message, problems = problems, context = context, said = said)
    return error


def pending_error(checker: Any, found: Any, missing: Any) -> InvalidDataError:
    """The error of a wrong call, made without its problems: see ``InvalidDataError.problems``."""
    error: InvalidDataError = _new_error(checker.error)            # the checker's class (``error = ...``)
    error._pending = (checker, found, missing)
    return error


def said_error(said: str, cls: "type[InvalidDataError]" = InvalidDataError) -> InvalidDataError:
    """``cls(said = said)``, without the cost of ``__init__``."""
    error: InvalidDataError = _new_error(cls)
    error._said = said
    return error


def field_error(checker: Any, entry: Any, value: Any, cls: type) -> InvalidDataError:
    """
    The error of a value assigned to a field of the dataclass ``cls`` that has the wrong type, or to an
    annotated attribute of an ``enforce`` class (``attribute assignment``).
    """
    error: InvalidDataError = _new_error(checker.error)
    error._pending = (checker, [(0, entry, value)], None)
    error._field_of = cls
    error.context = "field assignment" if made_dataclass(cls) else "attribute assignment"
    return error


#* Set by ``_dataclass._field_messages``: ``(problems, cls)``, words the problems of a failed assignment
#* for the dataclass (this module can't import that one).
as_field_problems: Any = None

#* Set by ``_messages`` (which comes later in the order of the modules): the entries of
#* ``InvalidDataError.errors()`` for one problem, ``(problem, context, include_input, include_context)``.
details_of: Any = None


# ── where a problem is, and its value as JSON ────────────────────────────────

class Where(str):
    """
    Where a problem is, as messages write it (``prices['apple'][1]``), with the steps that lead
    there in ``loc`` (``('prices', 'apple', 1)``), for ``InvalidDataError.errors()``. Only an item
    inside a value is one; a parameter's own name is a plain ``str``. Everything else reads it as
    the text it is.
    """
    loc: tuple[Any, ...]


def step(path: str, text: str, *parts: Any) -> Where:
    """
    ``path`` and then ``text`` (``"[1]"``, ``"['apple']"``, ``".x"``), one or more ``parts`` further
    down. Made only for an item that has failed: a valid value builds no path.
    """
    where = Where(path + text)
    where.loc = (path.loc if type(path) is Where else (path,)) + parts
    return where


def location(parameter: Any) -> list[Any]:
    """The ``loc`` of a problem: its steps, each one JSON-safe (a key that isn't is shown by its ``repr``)."""
    parts = parameter.loc if type(parameter) is Where else (parameter,)
    return [part if part is None or type(part) in (str, int, bool) or (type(part) is float and math.isfinite(part))
            else short_repr(part, 40) for part in parts]


plain = strip_colours                                   # ``text`` without its colours (the formatting tool's)


#* How much of a value ``input`` shows: an error about one item of a list of three million costs
#* no more to describe than one about a short list.
_INPUT_TEXT = 200
_INPUT_ITEMS = 50
_INPUT_DEPTH = 4
_SEQUENCES = (list, tuple, set, frozenset, collections.deque)


def jsonable(value: Any, depth: int = 0) -> Any:
    """
    ``value`` as JSON can hold it: ``None``, a bool, an int, a finite float and a short text as
    they are; a container as a list or a dict of what it holds, the first ``_INPUT_ITEMS`` items
    and ``"..."`` for the rest; ``nan`` and the infinities, and anything else, as text. A ``str``
    subclass goes through ``str()``: a ``SecretStr`` gives its mask.
    """
    kind = type(value)
    try:
        if value is None or kind is bool:
            return value
        if kind is str:
            return value if len(value) <= _INPUT_TEXT else value[:_INPUT_TEXT] + "..."
        if kind is int:
            #* JSON has no limit, but Python won't write an int of more than 4,300 digits as text.
            return value if value.bit_length() <= 1024 else f"<int of {value.bit_length()} bits>"
        if kind is float:
            return value if math.isfinite(value) else repr(value)
        if isinstance(value, str):
            return jsonable(str.__str__(str(value)), depth)
        if isinstance(value, int):
            return jsonable(int(value), depth)
        if isinstance(value, float):
            return jsonable(float(value), depth)
        if isinstance(value, (*_SEQUENCES, dict)):
            if depth >= _INPUT_DEPTH:
                return short_repr(value, 80)
            if isinstance(value, dict):
                pairs = list(islice(value.items(), _INPUT_ITEMS + 1))
                shown = {_key_text(k): jsonable(v, depth + 1) for k, v in pairs[:_INPUT_ITEMS]}
                if len(pairs) > _INPUT_ITEMS:
                    shown["..."] = "..."
                return shown
            items = list(islice(value, _INPUT_ITEMS + 1))
            listed = [jsonable(x, depth + 1) for x in items[:_INPUT_ITEMS]]
            return listed + ["..."] if len(items) > _INPUT_ITEMS else listed
        return short_repr(value, 80)
    except Exception:                                   # a value whose str, iteration or repr fails
        return f"<{kind.__name__}>"


def _key_text(key: Any) -> str:
    """A mapping key as a JSON object key: always text."""
    if type(key) is str:
        return key
    if key is None or type(key) in (int, float, bool):
        return repr(key)
    return short_repr(key, 40)


def _last_resort(value: Any) -> str:
    """What ``json.dumps`` writes for something that ``jsonable`` let through by mistake."""
    return short_repr(value, 80)


def _restore_error(message: str, context: str = "call", problems: "list[Problem] | tuple[Problem, ...]" = (),
                   cls: "type[InvalidDataError]" = InvalidDataError) -> InvalidDataError:
    """Unpickle an InvalidDataError (or a subclass): its message as it was rendered, its context and its problems."""
    return make_error(cls, message, problems = problems, context = context)


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
    if getattr(found, "__enforced_dispatch__", None) is not None:
        return found.__wrapped__                        # a dispatcher (enforced.dispatch): its base function
    inner = found
    for _ in range(16):
        if BOOTSTRAP_CODE_KEY in getattr(inner, "__globals__", ()):    # a wrapper made by wrap_callable
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
            check or TypeModel ``clean``, keys that collide after conversion, a container
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
            the reason for ``"invalid"``, ``"instances only"`` for a wrong type where a ``Transform``
            is expected and no raw value is taken (``convert = False``, a dispatcher's anchor).

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
            if decision() is not None:                  # part of a whole message: render_error has decided
                text = self._text = str(render[0](self, *render[1:]) if type(render) is tuple else render())
                return text
            #* Read on its own (an app that turns each problem into a line of its 422 body): coloured
            #* or not is asked once here, where each coloured word of the message asked it again.
            decide()
            try:
                text = self._text = str(render[0](self, *render[1:]) if type(render) is tuple else render())
            finally:
                release()
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
