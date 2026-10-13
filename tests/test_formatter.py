from enforced.formatting_tool import formatter
from typing import Any
import enforced.formatting_tool as formatting_utils
import subprocess
import sys
import pytest


@pytest.fixture(autouse = True)
def colours_wanted(monkeypatch):
    """
    These tests are about what a spec is turned into, so they need colours switched on:
    whatever the shell exports (``ENFORCED_COLOURS_OFF=1`` used to fail all of them), and although
    pytest's captured output is no terminal.
    """
    for name in ("ENFORCED_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED"):
        monkeypatch.delenv(name, raising = False)
    monkeypatch.setenv("FORCE_COLOR", "1")


#* The escape sequences, written out here a second time: what a terminal is to be sent.
CODES = {"bold": "\x1b[1m", "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m", "blue": "\x1b[34m",
         "magenta": "\x1b[35m", "cyan": "\x1b[36m", "orange": "\x1b[38;2;255;165;0m"}
COLOURS = ["red", "green", "yellow", "blue", "magenta", "cyan", "orange"]


def styled(text: str, color: Any = None, attrs: Any = ()) -> str:
    """``text`` as ``formatter`` has to return it: the attribute first, then the colour, and a reset behind."""
    return "".join(CODES[attr] for attr in attrs) + (CODES[color] if color else "") + text + "\x1b[0m"


class TestFormatter:
    """
    A spec names styles joined by ``_``. Only the styles the package's own messages use exist
    (the owner's decision, 2026-10-13, when termcolor went: no dependency, and nothing unused).
    """

    def test_returns_the_text_between_the_sequences(self):
        assert formatter("hello", "red") == "\x1b[31mhello\x1b[0m"
        assert formatter("hello", "bold_red") == "\x1b[1m\x1b[31mhello\x1b[0m"
        assert formatter("hello", "bold") == "\x1b[1mhello\x1b[0m"

    @pytest.mark.parametrize("color", COLOURS)
    def test_each_colour_alone_and_bold(self, color):
        assert formatter("text", color) == styled("text", color)
        assert formatter("text", f"bold_{color}") == styled("text", color, ["bold"])

    @pytest.mark.parametrize("color", COLOURS)
    def test_the_order_in_a_spec_does_not_matter(self, color):
        assert formatter("text", f"{color}_bold") == formatter("text", f"bold_{color}")

    def test_the_styles_are_the_ones_the_package_uses(self):
        #* Every spec written in the package is made of them, and none of them is unused.
        import pathlib
        import re
        used: set[str] = set()
        for path in pathlib.Path(formatting_utils.__file__).parent.rglob("*.py"):
            text = path.read_text()
            for call in re.findall(r"(?:formatter\([^\n]*?,\s*|escapes\()((?:f?['\"][a-z_]+['\"](?:,\s*)?)+)\)", text):
                for spec in re.findall(r"['\"]([a-z_]+)['\"]", call):
                    used.update(spec.split("_"))
        assert used == set(formatting_utils.STYLES) == set(CODES)
        assert formatting_utils.STYLES == CODES

    # --- text variants ---

    def test_empty_text(self):
        assert formatter("", "red") == styled("", "red")

    def test_multiword_text(self):
        assert formatter("hello world", "bold") == styled("hello world", attrs = ["bold"])

    def test_text_with_special_characters(self):
        assert formatter("hi\nthere", "red") == styled("hi\nthere", "red")

    @pytest.mark.parametrize("text", [5, 2.5, None, ("a", 1), ["x"], b"raw", ValueError("no")], ids = repr)
    def test_text_that_is_no_string(self, text):
        assert formatter(text, "bold_red") == styled(str(text), "red", attrs = ["bold"])

    @pytest.mark.parametrize("text", ["\x1b[31mred\x1b[0m", "%d %s", "{0}", "\x00enforced\x00", "a\x00b"])
    def test_text_is_never_read_as_anything_else(self, text):
        assert formatter(text, "bold_green") == styled(text, "green", attrs = ["bold"])

    # --- what there is no style for ---

    @pytest.mark.parametrize("spec", ["purple", "", "bold_purple", "on_red", "light_red", "underline", "red_on_blue", "teal", "grey"])
    def test_an_unknown_style_is_refused_by_name(self, spec):
        for _ in range(2):                                          # the refusal is not remembered as an answer
            with pytest.raises(ValueError, match = "unknown style"):
                formatter("text", spec)

    def test_with_colours_off_the_spec_is_not_read(self, monkeypatch):
        monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")
        assert formatter("text", "bold_red") == "text" and formatter(5, "purple") == "5"


def test_the_package_imports_nothing_but_the_standard_library():
    #* termcolor was the one dependency. A fresh interpreter, so that what pytest imported doesn't count.
    code = ("import sys; before = set(sys.modules); import enforced, enforced.data_types, enforced.formatting_tool\n"
            "new = {name.split('.')[0] for name in set(sys.modules) - before}\n"
            "print(sorted(new - set(sys.stdlib_module_names) - {'enforced'}))")
    done = subprocess.run([sys.executable, "-c", code], capture_output = True, text = True)
    assert done.stdout.strip() == "[]", done.stdout + done.stderr


def test_the_sequences_are_the_ones_termcolor_wrote():
    #* Where termcolor happens to be installed: messages are, to the byte, what they were with it.
    termcolor = pytest.importorskip("termcolor")
    for color in COLOURS:
        name: Any = (255, 165, 0) if color == "orange" else color
        assert formatter("x", color) == termcolor.colored("x", name, force_color = True)
        assert formatter("x", f"bold_{color}") == termcolor.colored("x", name, attrs = ["bold"], force_color = True)
    assert formatter("x", "bold") == termcolor.colored("x", attrs = ["bold"], force_color = True)


# ═════════════════════════════════════════════════════════════════════════════
#  WHAT A COLOURED MESSAGE COSTS
# ═════════════════════════════════════════════════════════════════════════════

def test_a_spec_is_worked_out_once_not_once_per_text(monkeypatch):
    #* Review finding 17: working the sequences out for each coloured word was most of what printing a message cost.
    asked = []
    real = formatting_utils._escapes
    monkeypatch.setattr(formatting_utils, "_escapes", lambda spec: asked.append(spec) or real(spec))
    monkeypatch.setattr(formatting_utils, "_ESCAPES", {})
    texts = [formatter(word, "bold_yellow") for word in ("int", "str", "float")] + [formatter("x", "bold_red")]
    assert texts == [styled("int", "yellow", attrs = ["bold"]), styled("str", "yellow", attrs = ["bold"]),
                     styled("float", "yellow", attrs = ["bold"]), styled("x", "red", attrs = ["bold"])]
    assert asked == ["bold_yellow", "bold_red"]


def test_a_whole_message_coloured(monkeypatch):
    from enforced import TypeCheckerError, typecheck

    @typecheck
    def f(x: int, mode: str = "r") -> None: ...

    with pytest.raises(TypeCheckerError) as exc:
        f("a")
    reset = styled("", attrs = ["bold"])
    assert str(exc.value) == (
        reset + styled("1", "red", attrs = ["bold"]) + " problem found in call:\n    -> "
        + "For parameter " + styled("x", "green", attrs = ["bold"]) + " of <"
        + styled(styled("Function", "magenta", attrs = ["bold"]), attrs = ["bold"]) + " " + styled("f", "blue", attrs = ["bold"])
        + ">: expected type: " + styled("'int'", "yellow", attrs = ["bold"]) + ", got type "
        + styled("'str'", "red", attrs = ["bold"]) + " (Value: " + styled("'a'", "red", attrs = ["bold"]) + ")"
        )


def test_a_message_built_once_colours_change_is_built_anew(monkeypatch):
    #* The escape sequences are remembered per spec; whether they are used is asked for every message.
    assert formatter("x", "bold") == styled("x", attrs = ["bold"])
    monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")
    assert formatter("x", "bold") == "x"
    monkeypatch.delenv("ENFORCED_COLOURS_OFF")
    assert formatter("x", "bold") == styled("x", attrs = ["bold"])


# ═════════════════════════════════════════════════════════════════════════════
#  WHEN MESSAGES ARE COLOURED
# ═════════════════════════════════════════════════════════════════════════════

class _Stream:
    def __init__(self, terminal: bool) -> None:
        self.terminal = terminal

    def isatty(self) -> bool:
        return self.terminal

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


def _streams(monkeypatch, out: bool, err: bool) -> None:
    import sys
    monkeypatch.delenv("FORCE_COLOR", raising = False)
    monkeypatch.delenv("TERM", raising = False)
    monkeypatch.setattr(sys, "stdout", _Stream(out))
    monkeypatch.setattr(sys, "stderr", _Stream(err))


@pytest.mark.parametrize("out, err, coloured", [
    (True, True, True),             # a terminal: someone is reading
    (True, False, False),           # 2> errors.log: the traceback goes into a file
    (False, True, False),           # | less, > out.txt
    (False, False, False),          # a CI job, a service
    ])
def test_colours_need_both_streams_to_be_terminals(monkeypatch, out, err, coloured):
    from enforced.formatting_tool import colours_on
    _streams(monkeypatch, out, err)
    assert colours_on() is coloured
    assert (formatter("x", "bold") != "x") is coloured


def test_the_environment_decides_before_the_streams(monkeypatch):
    from enforced.formatting_tool import colours_on
    _streams(monkeypatch, True, True)
    for name, value in (("ENFORCED_COLOURS_OFF", "1"), ("NO_COLOR", "1"), ("ANSI_COLORS_DISABLED", "1"), ("TERM", "dumb")):
        monkeypatch.setenv(name, value)
        assert colours_on() is False, name
        monkeypatch.delenv(name)
    _streams(monkeypatch, False, False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colours_on() is True
    monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")           # off wins over forced
    assert colours_on() is False


def test_a_stream_without_isatty_is_no_terminal(monkeypatch):
    import sys
    from enforced.formatting_tool import colours_on
    monkeypatch.delenv("FORCE_COLOR", raising = False)
    monkeypatch.setattr(sys, "stdout", None)                    # pythonw, a detached process
    monkeypatch.setattr(sys, "stderr", object())
    assert colours_on() is False and formatter("x", "red") == "x"


def test_switching_colours_off_later_leaves_no_escape_sequence(monkeypatch):
    #* Review finding 17: the reset sequence in front of every message was worked out once, at
    #* import, so a message built after colours were switched off still began with it.
    from enforced import TypeCheckerError, typecheck

    @typecheck
    def f(x: int) -> None: ...

    with pytest.raises(TypeCheckerError) as coloured:
        f("a")
    assert "\x1b[" in str(coloured.value)                       # forced on by the fixture
    monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")
    with pytest.raises(TypeCheckerError) as plain:
        f("a")
    assert "\x1b" not in str(plain.value)
    assert str(plain.value).startswith("1 problem found in call")
    with pytest.raises(TypeCheckerError) as definition:         # a message that is built when it is raised
        typecheck(int)
    assert "\x1b" not in str(definition.value)


def test_a_message_asks_once_whether_it_is_coloured(monkeypatch):
    import enforced.formatting_tool as fmrt
    from enforced.formatting_tool import colours_on
    from enforced import TypeCheckerError, typecheck
    asked = []
    real = colours_on
    monkeypatch.setattr(fmrt, "colours_on", lambda: asked.append(1) or real())

    @typecheck
    def f(x: int, y: str, z: float) -> None: ...

    with pytest.raises(TypeCheckerError) as exc:
        f("a", 1, "b")
    assert asked == []                                          # nothing is formatted until the error is read
    text = str(exc.value)
    assert text.count("For parameter") == 3 and len(asked) == 1


def test_the_environment_is_read_as_it_is_now(monkeypatch):
    #* colours_on reads the dictionary below os.environ (five lookups through os.environ took 1 µs).
    #* That is the same data, whichever way it is changed, and another mapping put in the place
    #* of os.environ is read as well.
    import os
    import enforced.formatting_tool as tool
    from enforced import EnvVar
    for name in (EnvVar.COLOURS_OFF, EnvVar.NO_COLOR, EnvVar.ANSI_COLORS_DISABLED, EnvVar.FORCE_COLOR, EnvVar.TERM):
        monkeypatch.delenv(name, raising = False)
    monkeypatch.setattr(tool, "_both_terminals", lambda: True)
    assert tool._FAST and tool.colours_on()
    steps = [(EnvVar.TERM, "dumb", False), (EnvVar.FORCE_COLOR, "1", True), (EnvVar.ANSI_COLORS_DISABLED, "", False)]
    for name, value, expected in steps:
        os.environ[name] = value                                    # the ordinary way to set one
        assert tool.colours_on() is expected
    for name, _, _ in steps:
        del os.environ[name]
    assert tool.colours_on()
    os.environ.update({EnvVar.COLOURS_OFF: "1"})
    assert not tool.colours_on()
    os.environ.pop(EnvVar.COLOURS_OFF)
    monkeypatch.setattr(os, "environ", {"NO_COLOR": "1"})           # a plain dictionary in its place
    assert not tool.colours_on()
    monkeypatch.setattr(os, "environ", {"TERM": "xterm"})
    assert tool.colours_on()
    monkeypatch.setattr(tool, "_FAST", False)                       # a Python without that dictionary: the same answers
    assert tool.colours_on()
    monkeypatch.setattr(os, "environ", {"TERM": "dumb"})
    assert not tool.colours_on()
