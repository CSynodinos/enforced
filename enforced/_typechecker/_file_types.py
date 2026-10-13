"""
``typing.IO``, ``TextIO`` and ``BinaryIO`` as runtime checks.

No real file inherits from these three classes (``isinstance(sys.stdout, TextIO)`` is ``False``),
so the checker tests each of them through a stand-in class of this module, whose ``isinstance``
knows what a file is:

    built-in files      what ``open()`` returns, ``io.StringIO``, ``io.BytesIO``, ``sys.stdout``
    io classes          anything derived from ``io.TextIOBase``, ``io.RawIOBase`` or
                        ``io.BufferedIOBase``: gzip, sockets, zip members, your own
    typing classes      a class that inherits ``typing.TextIO``, ``BinaryIO`` or ``IO``
    file-like objects   an object of none of these that has every method a file is used through,
                        such as the wrapper ``tempfile.NamedTemporaryFile`` returns, or the
                        ``unittest.mock.Mock()`` that stands for a file in a test

Text and binary are told apart: ``TextIO`` (and ``IO[str]``) rejects ``io.BytesIO()``, ``BinaryIO``
(and ``IO[bytes]``) rejects ``sys.stdout``. A file-like object counts as text when it has an
``encoding``. Bare ``IO``, ``IO[Any]`` and ``IO[AnyStr]`` accept both kinds. Whatever the class,
a value without a ``read`` attribute is not a file.

``type[TextIO]`` asks the same of a class, as far as a class shows it (``FileType.__subclasscheck__``).
"""
from typing import IO, Any, BinaryIO, TextIO, get_args, get_origin
import io


#* The built-in classes are plain C types: the usual file is recognised without asking an ABC
#* (about 10 ns against 110 ns for isinstance(f, io.TextIOBase)).
_TEXT_BUILT_IN: tuple[type, ...] = (io.TextIOWrapper, io.StringIO)
_BINARY_BUILT_IN: tuple[type, ...] = (
    io.BufferedReader, io.BufferedWriter, io.BytesIO, io.BufferedRandom, io.FileIO, io.BufferedRWPair,
    )
_TEXT: tuple[type, ...] = _TEXT_BUILT_IN + (io.TextIOBase, TextIO)
_BINARY: tuple[type, ...] = _BINARY_BUILT_IN + (io.RawIOBase, io.BufferedIOBase, BinaryIO)

#* The methods a file is used through: those typing.IO declares, but for ``__enter__`` and
#* ``__exit__``. Whether an object can stand after ``with`` says nothing about whether it can be read
#* and written, and asking for it turned away the usual stand-in for a file in a test: a
#* ``unittest.mock.Mock()`` answers every name except the special ones (review finding 21).
#* The attributes ``mode`` and ``name`` aren't asked for either: io.StringIO has neither.
_METHODS = (
    "read", "write", "readline", "readlines", "writelines", "flush", "close", "seek", "tell", "truncate",
    "fileno", "isatty", "readable", "writable", "seekable",
    )


class FileType(type):
    """Metaclass of the stand-ins: ``isinstance(value, stand_in)`` is the file test described above."""
    built_in: tuple[type, ...]          # what open() returns for this kind of file
    accepted: tuple[type, ...]          # every class of this kind of file
    rejected: tuple[type, ...]          # the classes of the other kind (bytes for TextIO)
    text: bool | None                   # what a file-like object must be: text, binary, or either (None)

    def __instancecheck__(cls, value: Any) -> bool:
        if isinstance(value, cls.built_in):
            return True
        #* The usual value that isn't a file (None for ``TextIO | None``, a path, a number) has no
        #* ``read``: answered here, before any ABC is asked.
        try:
            if not hasattr(value, "read"):
                return False
        except Exception:                       # a __getattr__ that fails in its own way
            return False
        if isinstance(value, cls.accepted):
            return True
        if isinstance(value, cls.rejected):
            return False
        if isinstance(value, IO):               # a class derived from typing.IO[...]
            kind = _declared_kind(type(value))
            return cls.text is None or kind is None or kind is cls.text
        return _file_like(value, cls.text)

    def __subclasscheck__(cls, sub: Any) -> bool:
        """
        For ``type[TextIO]``: a class whose instances pass the test above, as far as a class can
        say. The ``io`` classes and those derived from the typing classes say which kind of file
        they are. Of any other class only its own attributes can be seen:

        - It defines every method of a file: a file class. A text file's when ``encoding`` is a
          text on the class itself. Where the class doesn't say (no ``encoding``, one that is
          ``None``, or a property, whose value only an instance has), it is taken for either kind.
        - It answers names through ``__getattr__``, as a wrapper does that passes everything on to
          the file inside (the one ``tempfile.NamedTemporaryFile`` returns): what its instances
          have can't be read off the class at all. It is taken for a file class of either kind,
          as long as nothing it does define speaks against it.
        """
        if not isinstance(sub, type):
            return False
        if issubclass(sub, cls.accepted):
            return True
        if issubclass(sub, cls.rejected):
            return False
        if issubclass(sub, IO):                 # a class derived from typing.IO[...]
            kind = _declared_kind(sub)
            return cls.text is None or kind is None or kind is cls.text
        try:
            passes_on = getattr(sub, "__getattr__", None) is not None
            if not passes_on:
                for name in _METHODS:
                    if not hasattr(sub, name):
                        return False
            #* Only a text says "text file" from the class: a property has its value on the instance.
            return cls.text is not False or not isinstance(getattr(sub, "encoding", None), str)
        except Exception:                       # a metaclass that fails in its own way
            return False


def _declared_kind(tp: type) -> bool | None:
    """
    What a class derived from ``typing.IO[...]`` says it holds: True for ``IO[str]``, False for
    ``IO[bytes]``, None when it doesn't say (``IO``, ``IO[Any]``). The argument isn't part of the
    class itself, but the bases are kept as they were written.
    """
    for klass in tp.__mro__:
        for base in vars(klass).get("__orig_bases__", ()):
            if get_origin(base) is IO:
                argument = (get_args(base) or (None,))[0]
                if argument is str:
                    return True
                if argument is bytes:
                    return False
    return None


def _file_like(value: Any, text: bool | None) -> bool:
    """Whether an object of no known file class has a file's methods, and is of the kind asked for."""
    if isinstance(value, type):                 # io.StringIO without the call: the class has the methods too
        return False
    try:
        for name in _METHODS:
            if not hasattr(value, name):
                return False
        if text is None:
            return True
        if text:
            return hasattr(value, "encoding")
        return not isinstance(getattr(value, "encoding", None), str)
    except Exception:                           # a property or __getattr__ that fails in its own way
        return False


def _stand_in(name: str, text: bool | None) -> type:
    cls = FileType(name, (), {"__slots__": ()})
    #* Shown in messages, where the stand-in reads like what it stands for: expected type: 'typing.TextIO'.
    cls.__module__ = "typing"
    cls.text = text
    if text is None:
        cls.built_in, cls.accepted, cls.rejected = _TEXT_BUILT_IN + _BINARY_BUILT_IN, _TEXT + _BINARY + (io.IOBase, IO), ()
    elif text:
        cls.built_in, cls.accepted, cls.rejected = _TEXT_BUILT_IN, _TEXT, _BINARY
    else:
        cls.built_in, cls.accepted, cls.rejected = _BINARY_BUILT_IN, _BINARY, _TEXT
    return cls


_ANY_FILE = _stand_in("IO", None)
_TEXT_IO = _stand_in("TextIO", True)
_BINARY_IO = _stand_in("BinaryIO", False)
_IO_STR = _stand_in("IO[str]", True)
_IO_BYTES = _stand_in("IO[bytes]", False)


def file_stand_in(annotation: Any, origin: Any = None, args: tuple[Any, ...] = ()) -> type | None:
    """
    The class to test with ``isinstance`` for ``IO``, ``TextIO``, ``BinaryIO`` or ``IO[...]``
    (given with its ``origin`` and ``args``); ``None`` for any other annotation.
    """
    if annotation is TextIO:
        return _TEXT_IO
    if annotation is BinaryIO:
        return _BINARY_IO
    if annotation is IO:
        return _ANY_FILE
    if origin is IO:
        arg = args[0] if args else None
        return _IO_STR if arg is str else _IO_BYTES if arg is bytes else _ANY_FILE
    return None
