"""
clitint is optional (``pip install "enforced[colour]"``): ``enforced._colours`` is the only module that
imports it. Without it enforced imports, every public name is there and every message is plain text.
The interpreter that runs these tests may have clitint or not, so the run without it is a fresh one
in which clitint can't be imported (``sys.modules["clitint"] = None``).
"""
import os
import pathlib
import subprocess
import sys

import pytest

import enforced
from enforced import _colours

ROOT = pathlib.Path(enforced.__file__).resolve().parent.parent

_WITHOUT_CLITINT = r'''
import sys, warnings
sys.modules["clitint"] = None                       # import clitint now raises ImportError
import enforced
from enforced import _colours, InvalidDataError, InvalidDataWarning, validate

assert _colours.HAS_CLITINT is False
assert all(hasattr(enforced, name) for name in enforced.__all__)
assert sys.modules["clitint"] is None and "clitint._tint" not in sys.modules

@validate
def f(x: int) -> int:
    return x

try:
    f("a")
except InvalidDataError as e:
    text = str(e)
assert "\x1b" not in text, repr(text)
assert "For parameter x of <Function f>: expected type: 'int', got type 'str' (Value: 'a')" in text, text

assert enforced.turn_colours_on() is None           # nothing to switch on: still plain
try:
    f("b")
except InvalidDataError as e:
    assert "\x1b" not in str(e)
assert enforced.turn_colours_off() is None

@validate(on_error = "warn")
def g(x: int) -> int:
    return x

with warnings.catch_warnings(record = True) as seen:
    warnings.simplefilter("always")
    g("c")
shown = warnings.formatwarning(seen[0].message, seen[0].category, "/a/b.py", 3, None)
assert issubclass(seen[0].category, InvalidDataWarning) and "\x1b" not in shown, repr(shown)
assert _colours.escapes("bold_red", "bold") == ("", "", "", "")
assert _colours.strip_colours("\x1b[1mx\x1b[0m") == "x" and _colours.formatter(5, "bold_red") == "5"
print("plain")
'''


def test_enforced_works_without_clitint_and_every_message_is_plain():
    env = {k: v for k, v in os.environ.items() if k not in ("CLITINT_COLOURS_OFF", "NO_COLOR", "ANSI_COLORS_DISABLED")}
    env.update(FORCE_COLOR = "1", PYTHONPATH = str(ROOT))   # colours forced: without clitint there are none all the same
    done = subprocess.run([sys.executable, "-c", _WITHOUT_CLITINT], env = env, capture_output = True, text = True)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "plain\n"


@pytest.mark.colours
def test_with_clitint_the_functions_are_clitints_own():
    import clitint
    assert _colours.HAS_CLITINT is True
    for name in ("colours_on", "decide", "decision", "escapes", "formatter", "release", "strip_colours",
                 "turn_colours_off", "turn_colours_on"):
        assert getattr(_colours, name) is getattr(clitint, name), name
    assert enforced.turn_colours_off is clitint.turn_colours_off and enforced.turn_colours_on is clitint.turn_colours_on


def test_only_the_colours_module_imports_clitint():
    import ast
    for path in (ROOT / "enforced").rglob("*.py"):
        if path.name == "_colours.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding = "utf-8"))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(name.split(".")[0] == "clitint" for name in names), f"{path.relative_to(ROOT)}:{node.lineno}"
