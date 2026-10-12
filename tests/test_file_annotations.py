"""File annotations: ``typing.IO``, ``TextIO``, ``BinaryIO``, ``IO[str]`` and ``IO[bytes]``."""
from pyvalidate import typecheck, dataclass, TypeCheckerError, typecheck_from_dict
from typing import IO, Any, AnyStr, BinaryIO, Optional, TextIO
from unittest import mock
import gzip
import io
import re
import sys
import tempfile
import pytest


TEXT = [TextIO, IO[str]]
BINARY = [BinaryIO, IO[bytes]]
EITHER = [IO, IO[Any], IO[AnyStr]]


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _identity(annotation: Any, **flags: Any):
    """A checked identity function for ``annotation``."""
    def f(x): return x
    f.__annotations__ = {"x": annotation}
    return typecheck(f, **flags)


def _name(annotation: Any) -> str:
    return str(annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")


@pytest.fixture
def text_file(tmp_path):
    with open(tmp_path / "notes.txt", "w+") as fh:
        yield fh


@pytest.fixture
def binary_file(tmp_path):
    with open(tmp_path / "data.bin", "wb+") as fh:
        yield fh


# ── real files ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("annotation", TEXT + EITHER, ids = _name)
def test_text_files_are_accepted(annotation, text_file):
    f = _identity(annotation)
    assert f(text_file) is text_file                    # what open() returns
    assert f(sys.stdout) is sys.stdout
    assert f(sys.stderr) is sys.stderr
    buffer = io.StringIO()
    assert f(buffer) is buffer


@pytest.mark.parametrize("annotation", BINARY + EITHER, ids = _name)
def test_binary_files_are_accepted(annotation, binary_file, tmp_path):
    f = _identity(annotation)
    assert f(binary_file) is binary_file                # io.BufferedRandom
    buffer = io.BytesIO()
    assert f(buffer) is buffer
    with open(tmp_path / "data.bin", "rb") as reader:   # io.BufferedReader
        assert f(reader) is reader
    with open(tmp_path / "data.bin", "rb", buffering = 0) as raw:   # io.FileIO
        assert f(raw) is raw
    assert f(text_file_buffer := io.TextIOWrapper(io.BytesIO()).buffer) is text_file_buffer


@pytest.mark.parametrize("annotation", TEXT, ids = _name)
def test_text_annotation_rejects_a_binary_file(annotation, binary_file):
    f = _identity(annotation)
    for value in (binary_file, io.BytesIO(), io.TextIOWrapper(io.BytesIO()).buffer):
        with pytest.raises(TypeCheckerError):
            f(value)


@pytest.mark.parametrize("annotation", BINARY, ids = _name)
def test_binary_annotation_rejects_a_text_file(annotation, text_file):
    f = _identity(annotation)
    for value in (text_file, io.StringIO(), sys.stdout):
        with pytest.raises(TypeCheckerError):
            f(value)


class WriteOnly:
    """Something print() can write to, but not a file."""
    def write(self, text: str) -> int: return len(text)
    def flush(self) -> None: ...


@pytest.mark.parametrize("annotation", TEXT + BINARY + EITHER, ids = _name)
@pytest.mark.parametrize("value", ["notes.txt", b"data", 5, None, io.StringIO, io.BytesIO, WriteOnly(), ["line"], object()],
                         ids = lambda v: getattr(v, "__name__", type(v).__name__))
def test_not_a_file_is_rejected(annotation, value):
    #* The usual mistake is the path instead of the open file; the class instead of an instance is another.
    with pytest.raises(TypeCheckerError):
        _identity(annotation)(value)


def test_compressed_files(tmp_path):
    path = tmp_path / "notes.gz"
    with gzip.open(path, "wb") as fh:                   # gzip.GzipFile, an io.BufferedIOBase
        assert _identity(BinaryIO)(fh) is fh
        assert _identity(IO[bytes])(fh) is fh
        with pytest.raises(TypeCheckerError):
            _identity(TextIO)(fh)
    with gzip.open(path, "rt") as fh:                   # a text layer over it
        assert _identity(TextIO)(fh) is fh
        with pytest.raises(TypeCheckerError):
            _identity(BinaryIO)(fh)


# ── classes written by the user ──────────────────────────────────────────────

class Upper(io.TextIOBase):
    def write(self, text: str) -> int: return len(text)


class Zeros(io.RawIOBase):
    def readinto(self, buffer: Any) -> int: return 0


class TypedText(TextIO):                                # inherits the typing class, as type checkers ask
    pass


class TypedBinary(BinaryIO):
    pass


class TypedFile(IO[str]):                               # the argument is read from the bases as they were written
    pass


class TypedBytesFile(IO[bytes]):
    pass


class TypedAnyFile(IO):                                 # doesn't say which kind it is
    pass


class TypedTextChild(TypedFile):                        # the kind is inherited
    pass


def test_subclass_of_an_io_class():
    assert isinstance(_identity(TextIO)(Upper()), Upper)
    assert isinstance(_identity(IO)(Upper()), Upper)
    assert isinstance(_identity(BinaryIO)(Zeros()), Zeros)
    with pytest.raises(TypeCheckerError):
        _identity(BinaryIO)(Upper())
    with pytest.raises(TypeCheckerError):
        _identity(TextIO)(Zeros())


def test_subclass_of_a_typing_class():
    assert isinstance(_identity(TextIO)(TypedText()), TypedText)
    assert isinstance(_identity(IO[str])(TypedText()), TypedText)
    assert isinstance(_identity(BinaryIO)(TypedBinary()), TypedBinary)
    assert isinstance(_identity(IO)(TypedBinary()), TypedBinary)
    with pytest.raises(TypeCheckerError):
        _identity(TextIO)(TypedBinary())
    with pytest.raises(TypeCheckerError):
        _identity(BinaryIO)(TypedText())


def test_subclass_of_io_with_an_argument_is_of_that_kind():
    #* Review finding 21: a subclass of typing.IO[str] used to pass as a binary file too.
    for annotation in TEXT + EITHER:
        assert isinstance(_identity(annotation)(TypedFile()), TypedFile)
        assert isinstance(_identity(annotation)(TypedTextChild()), TypedTextChild)
    for annotation in BINARY + EITHER:
        assert isinstance(_identity(annotation)(TypedBytesFile()), TypedBytesFile)
    for annotation in BINARY:
        for value in (TypedFile(), TypedTextChild()):
            with pytest.raises(TypeCheckerError):
                _identity(annotation)(value)
    for annotation in TEXT:
        with pytest.raises(TypeCheckerError):
            _identity(annotation)(TypedBytesFile())
    #* One that doesn't say (bare IO) is still accepted for both.
    for annotation in TEXT + BINARY + EITHER:
        assert isinstance(_identity(annotation)(TypedAnyFile()), TypedAnyFile)


def test_a_subclass_used_as_the_annotation_is_an_ordinary_class():
    f = _identity(TypedText)
    assert isinstance(f(TypedText()), TypedText)
    with pytest.raises(TypeCheckerError):
        f(io.StringIO())


# ── file-like objects: not io classes, but with every method of a file ───────

class Proxy:
    """Hands everything on to the file it wraps (what colour and progress-bar libraries put in sys.stdout)."""
    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)

    def __enter__(self) -> "Proxy": return self
    def __exit__(self, *exc: Any) -> None: ...


class Broken:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError("no attribute access today")


def test_named_temporary_file():
    #* tempfile.NamedTemporaryFile returns a wrapper object, not an io class.
    with tempfile.NamedTemporaryFile("w+") as text, tempfile.NamedTemporaryFile() as binary:
        assert not isinstance(text, io.IOBase)
        for annotation in TEXT + EITHER:
            assert _identity(annotation)(text) is text
        for annotation in BINARY + EITHER:
            assert _identity(annotation)(binary) is binary
        for annotation in TEXT:
            with pytest.raises(TypeCheckerError):
                _identity(annotation)(binary)
        for annotation in BINARY:
            with pytest.raises(TypeCheckerError):
                _identity(annotation)(text)


def test_spooled_temporary_file():
    with tempfile.SpooledTemporaryFile(mode = "w+") as text, tempfile.SpooledTemporaryFile() as binary:
        assert _identity(TextIO)(text) is text
        assert _identity(BinaryIO)(binary) is binary
        assert _identity(IO)(text) is text
        with pytest.raises(TypeCheckerError):
            _identity(TextIO)(binary)
        with pytest.raises(TypeCheckerError):
            _identity(BinaryIO)(text)


def test_proxy_around_a_file():
    text, binary = Proxy(io.StringIO()), Proxy(io.BytesIO())
    assert _identity(TextIO)(text) is text
    assert _identity(IO[str])(text) is text
    assert _identity(BinaryIO)(binary) is binary
    assert _identity(IO)(binary) is binary
    with pytest.raises(TypeCheckerError):
        _identity(TextIO)(binary)                       # no encoding: not a text file


def test_mock_objects():
    stand_in = mock.MagicMock()
    for annotation in TEXT + BINARY + EITHER:
        assert _identity(annotation)(stand_in) is stand_in
    binary = mock.Mock(spec = io.BytesIO)
    assert _identity(BinaryIO)(binary) is binary
    with pytest.raises(TypeCheckerError):
        _identity(TextIO)(binary)


def test_an_object_that_fails_on_attribute_access_is_rejected_cleanly():
    for annotation in TEXT + BINARY + EITHER:
        with pytest.raises(TypeCheckerError):
            _identity(annotation)(Broken())


# ── with the other features ──────────────────────────────────────────────────

def test_optional_and_union():
    f = _identity(TextIO | None)
    assert f(None) is None
    assert f(sys.stdout) is sys.stdout
    with pytest.raises(TypeCheckerError):
        f("out.txt")
    g = _identity(Optional[IO[bytes]])
    assert g(None) is None
    with pytest.raises(TypeCheckerError):
        g(io.StringIO())
    h = _identity(TextIO | BinaryIO | str)
    assert h("out.txt") == "out.txt"
    assert isinstance(h(io.BytesIO()), io.BytesIO)
    with pytest.raises(TypeCheckerError):
        h(5)


def test_default_and_return_value():
    @typecheck(check_return = True)
    def opened(out: TextIO = sys.stdout) -> TextIO:
        return out

    assert opened() is sys.stdout

    @typecheck(check_return = True)
    def wrong() -> BinaryIO:
        return io.StringIO()                            # type: ignore[return-value]

    with pytest.raises(TypeCheckerError):
        wrong()

    @typecheck
    def bad_default(out: TextIO = "out.txt"): ...       # type: ignore[assignment]

    with pytest.raises(TypeCheckerError, match = "definition"):
        bad_default()


def test_strict_mode_accepts_files():
    #* No file is an instance of exactly typing.TextIO, so strict mode can't ask for the exact type.
    f = _identity(TextIO, allow_subclass = False)
    assert f(sys.stdout) is sys.stdout
    assert isinstance(f(io.StringIO()), io.StringIO)
    with pytest.raises(TypeCheckerError):
        f(io.BytesIO())
    g = _identity(BinaryIO | int, allow_subclass = False)
    assert isinstance(g(io.BytesIO()), io.BytesIO)
    assert g(5) == 5
    with pytest.raises(TypeCheckerError):
        g(True)                                         # int stays exact next to it


def test_coercion_never_makes_a_file():
    f = _identity(TextIO, coerce = True)
    with pytest.raises(TypeCheckerError):
        f("out.txt")


def test_deep_items():
    f = _identity(list[TextIO], deep = True)
    files = [io.StringIO(), sys.stdout]
    assert f(files) is files
    with pytest.raises(TypeCheckerError) as exc:
        f([io.StringIO(), io.BytesIO()])
    assert [p.parameter for p in exc.value.problems] == ["x[1]"]
    g = _identity(dict[str, IO[bytes]], deep = True)
    assert g({"a": io.BytesIO()})
    with pytest.raises(TypeCheckerError):
        g({"a": io.StringIO()})


def test_type_of_file_class():
    f = _identity(type[TextIO])
    assert f(io.StringIO) is io.StringIO
    assert f(io.TextIOWrapper) is io.TextIOWrapper
    assert f(Upper) is Upper
    for value in (io.BytesIO, str, io.StringIO()):
        with pytest.raises(TypeCheckerError):
            f(value)


def test_dataclass_field():
    @dataclass
    class Report:
        out: TextIO = sys.stdout
        raw: BinaryIO | None = None

    report = Report()
    report.out = io.StringIO()
    report.raw = io.BytesIO()
    with pytest.raises(TypeCheckerError):
        report.out = io.BytesIO()                       # type: ignore[assignment]
    with pytest.raises(TypeCheckerError):
        Report(raw = "data.bin")                        # type: ignore[arg-type]


def test_typecheck_from_dict():
    spec = {"object_name": "export", "record": {"out": TextIO, "raw": IO[bytes]}}
    out, raw = io.StringIO(), io.BytesIO()
    assert typecheck_from_dict({**spec, "args": (out, raw)}) == ((out, raw), {})
    with pytest.raises(TypeCheckerError):
        typecheck_from_dict({**spec, "args": (raw, out)})


# ── messages ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("annotation, shown", [
    (TextIO, "'typing.TextIO'"), (BinaryIO, "'typing.BinaryIO'"), (IO, "'typing.IO'"),
    (IO[str], "'typing.IO[str]'"), (IO[bytes], "'typing.IO[bytes]'"), (TextIO | None, "'TextIO' | 'NoneType'"),
    ], ids = _name)
def test_message_names_the_annotation(annotation, shown):
    with pytest.raises(TypeCheckerError) as exc:
        _identity(annotation)(5)
    assert f"expected type: {shown}, got type 'int' (Value: 5)" in _plain(str(exc.value))


def test_message_for_the_wrong_kind_of_file():
    with pytest.raises(TypeCheckerError) as exc:
        _identity(TextIO)(io.BytesIO())
    text = _plain(str(exc.value))
    assert "For parameter x of <Function f>: expected type: 'typing.TextIO', got type '_io.BytesIO'" in text
    assert exc.value.problems[0].kind == "type"
