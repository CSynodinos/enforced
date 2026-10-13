from enforced.formatting_tool import formatter
from termcolor import colored
from typing import Any
import enforced.formatting_tool as formatting_utils
import pytest


@pytest.fixture(autouse = True)
def colours_wanted(monkeypatch):
    """
    These tests are about how a spec is handed to termcolor, so they need colours switched on:
    whatever the shell exports (``ENFORCED_COLOURS_OFF=1`` used to fail all of them), and although
    pytest's captured output is no terminal.
    """
    for name in ("ENFORCED_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED"):
        monkeypatch.delenv(name, raising = False)
    monkeypatch.setenv("FORCE_COLOR", "1")


def styled(text: str, color: Any = None, on_color: Any = None, attrs: Any = ()) -> str:
    """What termcolor itself makes of ``text`` with these arguments: what ``formatter`` has to return."""
    return colored(text, color, on_color, attrs = list(attrs), force_color = True)


class TestFormatter:
    """
    Each test names a spec and the termcolor arguments it stands for, and compares what
    ``formatter`` returns with what termcolor returns for them. (These tests used to assert on the
    call itself, through a mock: ``formatter`` now asks termcolor once per spec, not once per text.)
    """

    # --- return value ---

    def test_returns_what_termcolor_returns(self):
        assert formatter("hello", "red") == styled("hello", "red") == "\x1b[31mhello\x1b[0m"

    # --- colors ---

    def test_single_color(self):
        assert formatter("text", "red") == styled("text", "red")

    @pytest.mark.parametrize("color", ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"])
    def test_all_colors(self, color):
        assert formatter("text", color) == styled("text", color)

    def test_light_color(self):
        assert formatter("text", "light_red") == styled("text", "light_red")

    def test_custom_colors(self):
        assert formatter("text", "orange") == styled("text", (255, 165, 0))
        assert formatter("text", "bold_teal") == styled("text", (0, 128, 128), attrs = ["bold"])

    # --- attributes ---

    @pytest.mark.parametrize("attr", ["bold", "dark", "underline", "blink", "reverse", "concealed"])
    def test_all_attrs(self, attr):
        assert formatter("text", attr) == styled("text", attrs = [attr])

    def test_multiple_attrs(self):
        assert formatter("text", "bold_underline") == styled("text", attrs = ["bold", "underline"])

    def test_all_six_attributes_combined(self):
        assert formatter("text", "bold_dark_underline_blink_reverse_concealed") == styled(
            "text", attrs = ["bold", "dark", "underline", "blink", "reverse", "concealed"])

    # --- background colors ---

    def test_background_color(self):
        assert formatter("text", "on_red") == styled("text", None, "on_red")

    @pytest.mark.parametrize("color", ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"])
    def test_all_background_colors(self, color):
        assert formatter("text", f"on_{color}") == styled("text", None, f"on_{color}")

    def test_light_background_color(self):
        assert formatter("text", "on_light_red") == styled("text", None, "on_light_red")

    # --- combinations ---

    def test_color_and_background(self):
        assert formatter("text", "red_on_blue") == styled("text", "red", "on_blue")

    def test_color_and_attr(self):
        assert formatter("text", "red_bold") == styled("text", "red", attrs = ["bold"])

    def test_attribute_before_color(self):
        assert formatter("text", "bold_red") == styled("text", "red", attrs = ["bold"])

    def test_color_background_and_attr(self):
        assert formatter("text", "red_on_blue_bold") == styled("text", "red", "on_blue", ["bold"])

    def test_color_background_multiple_attrs(self):
        assert formatter("text", "green_on_yellow_bold_underline") == styled("text", "green", "on_yellow", ["bold", "underline"])

    def test_light_color_and_light_background(self):
        assert formatter("text", "light_red_on_light_blue") == styled("text", "light_red", "on_light_blue")

    def test_light_color_and_attr(self):
        assert formatter("text", "light_blue_bold") == styled("text", "light_blue", attrs = ["bold"])

    def test_color_light_background_and_attr(self):
        assert formatter("text", "red_on_light_green_bold") == styled("text", "red", "on_light_green", ["bold"])

    def test_light_color_light_background_attr(self):
        assert formatter("text", "light_cyan_on_light_magenta_underline") == styled(
            "text", "light_cyan", "on_light_magenta", ["underline"])

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
        #* Not as a format string, and not as the marker the escape sequences are worked out with.
        assert formatter(text, "bold_green") == styled(text, "green", attrs = ["bold"])

    # --- unknown/unrecognized spec ---

    def test_unknown_token_is_taken_for_a_color(self):
        #* ... and termcolor knows no such colour. Its answer comes through, every time.
        for _ in range(2):
            with pytest.raises(KeyError, match = "purple"):
                formatter("text", "purple")

    def test_empty_spec(self):
        with pytest.raises(KeyError):
            formatter("text", "")


# ═════════════════════════════════════════════════════════════════════════════
#  WHAT A COLOURED MESSAGE COSTS
# ═════════════════════════════════════════════════════════════════════════════

def test_termcolor_is_asked_once_per_spec_not_once_per_text(monkeypatch):
    #* Review finding 17: one termcolor call per coloured word was most of what printing a message cost.
    asked = []
    monkeypatch.setattr(formatting_utils, "colored", lambda *args, **kwargs: asked.append(args) or colored(*args, **kwargs))
    formatting_utils._escapes.cache_clear()
    try:
        texts = [formatter(word, "bold_yellow") for word in ("int", "str", "float")] + [formatter("x", "bold_red")]
        assert texts == [styled("int", "yellow", attrs = ["bold"]), styled("str", "yellow", attrs = ["bold"]),
                         styled("float", "yellow", attrs = ["bold"]), styled("x", "red", attrs = ["bold"])]
        assert len(asked) == 2 and "int" not in str(asked)          # once for each spec, and never with the text
    finally:
        formatting_utils._escapes.cache_clear()                                # nothing made through the patch stays behind


def test_a_whole_message_is_what_termcolor_would_have_made_of_it(monkeypatch):
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
    assert (formatter("x", "bold") != "x") is coloured     # termcolor is told, it doesn't look for itself


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
