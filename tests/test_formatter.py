from unittest.mock import patch
from pyvalidate.utils import formatter
import pytest


@pytest.fixture(autouse = True)
def colours_wanted(monkeypatch):
    """
    These tests are about how a spec is handed to termcolor, so they need colours switched on:
    whatever the shell exports (``PYVALIDATE_COLOURS_OFF=1`` used to fail all of them), and although
    pytest's captured output is no terminal.
    """
    for name in ("PYVALIDATE_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED"):
        monkeypatch.delenv(name, raising = False)
    monkeypatch.setenv("FORCE_COLOR", "1")


@patch("pyvalidate.utils.colored")
class TestFormatter:

    # --- return value ---

    def test_returns_colored_result(self, mock_colored):
        mock_colored.return_value = "styled"
        assert formatter("hello", "red") == "styled"

    # --- colors ---

    def test_single_color(self, mock_colored):
        formatter("text", "red")
        mock_colored.assert_called_once_with("text", "red", None, attrs=[], force_color=True)

    @pytest.mark.parametrize("color", ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"])
    def test_all_colors(self, mock_colored, color):
        formatter("text", color)
        mock_colored.assert_called_once_with("text", color, None, attrs=[], force_color=True)

    def test_light_color(self, mock_colored):
        formatter("text", "light_red")
        mock_colored.assert_called_once_with("text", "light_red", None, attrs=[], force_color=True)

    # --- attributes ---

    @pytest.mark.parametrize("attr", ["bold", "dark", "underline", "blink", "reverse", "concealed"])
    def test_all_attrs(self, mock_colored, attr):
        formatter("text", attr)
        mock_colored.assert_called_once_with("text", None, None, attrs=[attr], force_color=True)

    def test_multiple_attrs(self, mock_colored):
        formatter("text", "bold_underline")
        mock_colored.assert_called_once_with("text", None, None, attrs=["bold", "underline"], force_color=True)

    def test_all_six_attributes_combined(self, mock_colored):
        formatter("text", "bold_dark_underline_blink_reverse_concealed")
        mock_colored.assert_called_once_with(
            "text", None, None, attrs=["bold", "dark", "underline", "blink", "reverse", "concealed"], force_color=True
        )

    # --- background colors ---

    def test_background_color(self, mock_colored):
        formatter("text", "on_red")
        mock_colored.assert_called_once_with("text", None, "on_red", attrs=[], force_color=True)

    @pytest.mark.parametrize("color", ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"])
    def test_all_background_colors(self, mock_colored, color):
        formatter("text", f"on_{color}")
        mock_colored.assert_called_once_with("text", None, f"on_{color}", attrs=[], force_color=True)

    def test_light_background_color(self, mock_colored):
        formatter("text", "on_light_red")
        mock_colored.assert_called_once_with("text", None, "on_light_red", attrs=[], force_color=True)

    # --- combinations ---

    def test_color_and_background(self, mock_colored):
        formatter("text", "red_on_blue")
        mock_colored.assert_called_once_with("text", "red", "on_blue", attrs=[], force_color=True)

    def test_color_and_attr(self, mock_colored):
        formatter("text", "red_bold")
        mock_colored.assert_called_once_with("text", "red", None, attrs=["bold"], force_color=True)

    def test_attribute_before_color(self, mock_colored):
        formatter("text", "bold_red")
        mock_colored.assert_called_once_with("text", "red", None, attrs=["bold"], force_color=True)

    def test_color_background_and_attr(self, mock_colored):
        formatter("text", "red_on_blue_bold")
        mock_colored.assert_called_once_with("text", "red", "on_blue", attrs=["bold"], force_color=True)

    def test_color_background_multiple_attrs(self, mock_colored):
        formatter("text", "green_on_yellow_bold_underline")
        mock_colored.assert_called_once_with("text", "green", "on_yellow", attrs=["bold", "underline"], force_color=True)

    def test_light_color_and_light_background(self, mock_colored):
        formatter("text", "light_red_on_light_blue")
        mock_colored.assert_called_once_with("text", "light_red", "on_light_blue", attrs=[], force_color=True)

    def test_light_color_and_attr(self, mock_colored):
        formatter("text", "light_blue_bold")
        mock_colored.assert_called_once_with("text", "light_blue", None, attrs=["bold"], force_color=True)

    def test_color_light_background_and_attr(self, mock_colored):
        formatter("text", "red_on_light_green_bold")
        mock_colored.assert_called_once_with("text", "red", "on_light_green", attrs=["bold"], force_color=True)

    def test_light_color_light_background_attr(self, mock_colored):
        formatter("text", "light_cyan_on_light_magenta_underline")
        mock_colored.assert_called_once_with("text", "light_cyan", "on_light_magenta", attrs=["underline"], force_color=True)

    # --- text variants ---

    def test_empty_text(self, mock_colored):
        formatter("", "red")
        mock_colored.assert_called_once_with("", "red", None, attrs=[], force_color=True)

    def test_multiword_text(self, mock_colored):
        formatter("hello world", "bold")
        mock_colored.assert_called_once_with("hello world", None, None, attrs=["bold"], force_color=True)

    def test_text_with_special_characters(self, mock_colored):
        formatter("hi\nthere", "red")
        mock_colored.assert_called_once_with("hi\nthere", "red", None, attrs=[], force_color=True)

    # --- unknown/unrecognized spec ---

    def test_unknown_token_treated_as_color(self, mock_colored):
        formatter("text", "purple")
        mock_colored.assert_called_once_with("text", "purple", None, attrs=[], force_color=True)

    def test_empty_spec(self, mock_colored):
        formatter("text", "")
        mock_colored.assert_called_once_with("text", "", None, attrs=[], force_color=True)


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
    from pyvalidate.utils import colours_on
    _streams(monkeypatch, out, err)
    assert colours_on() is coloured
    assert (formatter("x", "bold") != "x") is coloured     # termcolor is told, it doesn't look for itself


def test_the_environment_decides_before_the_streams(monkeypatch):
    from pyvalidate.utils import colours_on
    _streams(monkeypatch, True, True)
    for name, value in (("PYVALIDATE_COLOURS_OFF", "1"), ("NO_COLOR", "1"), ("ANSI_COLORS_DISABLED", "1"), ("TERM", "dumb")):
        monkeypatch.setenv(name, value)
        assert colours_on() is False, name
        monkeypatch.delenv(name)
    _streams(monkeypatch, False, False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert colours_on() is True
    monkeypatch.setenv("PYVALIDATE_COLOURS_OFF", "1")           # off wins over forced
    assert colours_on() is False


def test_a_stream_without_isatty_is_no_terminal(monkeypatch):
    import sys
    from pyvalidate.utils import colours_on
    monkeypatch.delenv("FORCE_COLOR", raising = False)
    monkeypatch.setattr(sys, "stdout", None)                    # pythonw, a detached process
    monkeypatch.setattr(sys, "stderr", object())
    assert colours_on() is False and formatter("x", "red") == "x"


def test_switching_colours_off_later_leaves_no_escape_sequence(monkeypatch):
    #* Review finding 17: the reset sequence in front of every message was worked out once, at
    #* import, so a message built after colours were switched off still began with it.
    from pyvalidate import TypeCheckerError, typecheck

    @typecheck
    def f(x: int) -> None: ...

    with pytest.raises(TypeCheckerError) as coloured:
        f("a")
    assert "\x1b[" in str(coloured.value)                       # forced on by the fixture
    monkeypatch.setenv("PYVALIDATE_COLOURS_OFF", "1")
    with pytest.raises(TypeCheckerError) as plain:
        f("a")
    assert "\x1b" not in str(plain.value)
    assert str(plain.value).startswith("1 problem found in call")
    with pytest.raises(TypeCheckerError) as definition:         # a message that is built when it is raised
        typecheck(int)
    assert "\x1b" not in str(definition.value)


def test_a_message_asks_once_whether_it_is_coloured(monkeypatch):
    import pyvalidate.utils as utils
    from pyvalidate import TypeCheckerError, typecheck
    asked = []
    real = utils.colours_on
    monkeypatch.setattr(utils, "colours_on", lambda: asked.append(1) or real())

    @typecheck
    def f(x: int, y: str, z: float) -> None: ...

    with pytest.raises(TypeCheckerError) as exc:
        f("a", 1, "b")
    assert asked == []                                          # nothing is formatted until the error is read
    text = str(exc.value)
    assert text.count("For parameter") == 3 and len(asked) == 1
