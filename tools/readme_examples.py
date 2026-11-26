"""
The README's examples, run: what ``tests/test_readme.py`` checks, and what makes the coloured images.

A ```python block of the README is run on its own, statement by statement, with what its comments say:

    expression          # -> 12.0                 the value's repr must be exactly this
    statement           # InvalidDataError ...    it must raise that (or warn, for a ``...Warning``)
    statement           # InvalidDataError, shown below
                                                  ... and its message is the block's image

A block after ``<!-- render: NAME -->`` makes ``assets/readme/NAME-light.svg`` and ``NAME-dark.svg``:
the message of its statement marked ``shown below``, coloured as a terminal shows it. A block after
``<!-- not run -->`` is left alone.

    python tools/readme_examples.py            write the images again
    python tools/readme_examples.py --check    only say which images are out of date
"""
from __future__ import annotations

import ast
import contextlib
import io
import linecache
import pathlib
import re
import sys
import tokenize
import types
import warnings
from dataclasses import dataclass, field
from html import escape
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
IMAGES = ROOT / "assets" / "readme"


# ── the blocks of the README ─────────────────────────────────────────────────

@dataclass
class Block:
    source: str
    line: int                                   # where the code starts in the README
    render: str | None = None                   # the image's name, from <!-- render: NAME -->
    run: bool = True


def blocks(text: str) -> list[Block]:
    found: list[Block] = []
    lines = text.splitlines()
    i = 0
    pending: dict[str, Any] = {}
    while i < len(lines):
        line = lines[i].strip()
        if (marker := re.fullmatch(r"<!--\s*render:\s*([\w-]+)\s*-->", line)):
            pending["render"] = marker[1]
        elif re.fullmatch(r"<!--\s*not run\s*-->", line):
            pending["run"] = False
        elif line == "```python":
            start = i + 1
            j = start
            while lines[j].strip() != "```":
                j += 1
            found.append(Block("\n".join(lines[start:j]), start + 1, **pending))
            pending = {}
            i = j
        elif line and not line.startswith("<!--"):
            pending = {}                        # a marker belongs to the block right after it
        i += 1
    return found


# ── running one block ────────────────────────────────────────────────────────

@dataclass
class Outcome:
    failures: list[str] = field(default_factory = list)
    shown: Any = None                           # the error (or warning) marked "shown below"


def _comments(source: str) -> dict[int, str]:
    comments: dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.string[1:].strip()
    return comments


def _exception_class(name: str, namespace: dict[str, Any]) -> type[BaseException] | None:
    """The exception or warning a comment names: the block's own, enforced's, or a built-in one."""
    import builtins
    import enforced
    found = namespace.get(name) or getattr(enforced, name, None) or getattr(builtins, name, None)
    return found if isinstance(found, type) and issubclass(found, BaseException) else None


def run_block(block: Block, colours: bool = False) -> Outcome:
    """Run ``block`` statement by statement, checking what its comments say."""
    try:
        import clitint._tint as tool                                # the switches are clitint's state
    except ImportError:                                             # no clitint: every message is plain already
        if colours:
            raise RuntimeError('the coloured images need clitint: pip install "enforced[colour]"') from None
        tool = None
    outcome = Outcome()
    tree = ast.parse(block.source)
    comments = _comments(block.source)
    #* A module of its own, in sys.modules while it runs: dataclasses and pickle look a class's module up.
    module = types.ModuleType(f"readme_block_{block.line}")
    sys.modules[module.__name__] = module
    namespace: dict[str, Any] = module.__dict__
    chosen = tool._CHOSEN if tool is not None else None
    if tool is not None:
        tool._CHOSEN = colours
    source_lines = block.source.splitlines(keepends = True)
    wheres: list[str] = []
    try:
        for node in tree.body:
            first_line = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
            said = next((comments[n] for n in range(first_line, (node.end_lineno or node.lineno) + 1) if n in comments), "")
            where = f"README line {block.line + node.lineno - 1}"
            #* A message shows a lambda check by its source (`n < 0`), read through linecache: as in a real file.
            linecache.cache[where] = (1, None, source_lines, where)  # type: ignore[assignment]
            wheres.append(where)
            #* dont_inherit: compile() would hand a block this file's `from __future__ import annotations`.
            code = ast.Module([node], [])
            first = said.split()[0].rstrip(",:.") if said else ""
            expected_class = _exception_class(first, namespace) if first else None
            if said.startswith("->") and isinstance(node, ast.Expr):
                try:
                    value = eval(compile(ast.Expression(node.value), where, "eval", dont_inherit = True), namespace)
                except BaseException as error:
                    outcome.failures.append(f"{where}: raised {type(error).__name__}: {error}")
                    continue
                wanted = said[2:].strip()
                if repr(value) != wanted:
                    outcome.failures.append(f"{where}: {repr(value)} where the README says {wanted}")
            elif expected_class is not None and issubclass(expected_class, Warning):
                with warnings.catch_warnings(record = True) as caught:
                    warnings.simplefilter("always")
                    exec(compile(code, where, "exec", dont_inherit = True), namespace)
                ours = [w for w in caught if issubclass(w.category, expected_class)]
                if not ours:
                    outcome.failures.append(f"{where}: no {first} where the README says one is issued")
                elif "shown below" in said and outcome.shown is None:
                    outcome.shown = ours[0].message
            elif expected_class is not None:
                try:
                    exec(compile(code, where, "exec", dont_inherit = True), namespace)
                except expected_class as error:
                    if "shown below" in said and outcome.shown is None:
                        outcome.shown = error
                        str(error)                  # made now, with the colours chosen above
                except BaseException as error:
                    outcome.failures.append(f"{where}: {type(error).__name__} where the README says {first}: {error}")
                else:
                    outcome.failures.append(f"{where}: nothing raised where the README says {first}")
            else:
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(code, where, "exec", dont_inherit = True), namespace)
                except BaseException as error:
                    outcome.failures.append(f"{where}: raised {type(error).__name__}: {error}")
    finally:
        if tool is not None:
            tool._CHOSEN = chosen
        sys.modules.pop(module.__name__, None)
        for where in wheres:
            linecache.cache.pop(where, None)
    if block.render and outcome.shown is None:
        outcome.failures.append(f"README line {block.line}: <!-- render: {block.render} --> but no statement is 'shown below'")
    return outcome


def message_of(shown: Any) -> str:
    """What a terminal shows: ``InvalidDataError: ...`` as the last line of a traceback, or the warning."""
    return f"{type(shown).__name__}: {shown.shown() if hasattr(shown, 'shown') else shown}"


# ── ANSI to SVG ──────────────────────────────────────────────────────────────

#* GitHub's own palettes, light and dark, for the eight styles enforced writes.
THEMES = {
    "light": {"background": "#f6f8fa", "border": "#d1d9e0", "text": "#1f2328", "dots": ("#ff5f57", "#febc2e", "#28c840"),
              "colours": {31: "#cf222e", 32: "#116329", 33: "#9a6700", 34: "#0550ae", 35: "#8250df", 36: "#1b7c83",
                          (255, 165, 0): "#bc4c00"}},
    "dark": {"background": "#0d1117", "border": "#3d444d", "text": "#e6edf3", "dots": ("#ff5f57", "#febc2e", "#28c840"),
             "colours": {31: "#ff7b72", 32: "#7ee787", 33: "#e3b341", 34: "#79c0ff", 35: "#d2a8ff", 36: "#76e3ea",
                         (255, 165, 0): "#ffa657"}},
    }
_SGR = re.compile(r"\x1b\[([0-9;]*)m")
FONT_SIZE, LINE_HEIGHT, CHAR_WIDTH, PAD_X, PAD_TOP, PAD_BOTTOM = 14, 21, 8.43, 20, 46, 18


def _segments(line: str) -> list[tuple[str, Any, bool]]:
    """``(text, colour key or None, bold)`` for one line of ANSI text."""
    out: list[tuple[str, Any, bool]] = []
    colour: Any = None
    bold = False
    pos = 0
    for match in _SGR.finditer(line):
        if match.start() > pos:
            out.append((line[pos:match.start()], colour, bold))
        codes = [int(c) for c in match[1].split(";") if c] or [0]
        k = 0
        while k < len(codes):
            code = codes[k]
            if code == 0:
                colour, bold = None, False
            elif code == 1:
                bold = True
            elif code == 22:
                bold = False
            elif code == 39:
                colour = None
            elif 30 <= code <= 37:
                colour = code
            elif code == 38 and codes[k + 1:k + 2] == [2]:
                colour = tuple(codes[k + 2:k + 5])
                k += 4
            k += 1
        pos = match.end()
    if pos < len(line):
        out.append((line[pos:], colour, bold))
    return out


def svg(text: str, theme: str) -> str:
    """``text`` (with ANSI colours) as an SVG of a terminal window."""
    palette = THEMES[theme]
    lines = text.splitlines()
    width = round(PAD_X * 2 + max(len(_SGR.sub("", line)) for line in lines) * CHAR_WIDTH)
    height = PAD_TOP + LINE_HEIGHT * len(lines) + PAD_BOTTOM
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           f'role="img" aria-label="{escape(_SGR.sub("", text))}">',
           f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" fill="{palette["background"]}" '
           f'stroke="{palette["border"]}"/>']
    for k, dot in enumerate(palette["dots"]):
        out.append(f'<circle cx="{20 + k * 18}" cy="18" r="5.5" fill="{dot}"/>')
    out.append(f'<g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, \'Liberation Mono\', monospace" '
               f'font-size="{FONT_SIZE}" fill="{palette["text"]}" xml:space="preserve" style="white-space: pre">')
    for n, line in enumerate(lines):
        y = PAD_TOP + LINE_HEIGHT * n + FONT_SIZE
        #* Leading spaces as a position: not every renderer keeps them (``xml:space`` is old, ``white-space`` new).
        indent = len(_SGR.sub("", line)) - len(_SGR.sub("", line).lstrip(" "))
        line = re.sub(r"^((?:\x1b\[[0-9;]*m)*) {%d}" % indent, r"\1", line) if indent else line
        spans = []
        for piece, colour, bold in _segments(line):
            attributes = ""
            if colour is not None:
                attributes += f' fill="{palette["colours"].get(colour, palette["text"])}"'
            if bold:
                attributes += ' font-weight="bold"'
            spans.append(f"<tspan{attributes}>{escape(piece)}</tspan>" if attributes else escape(piece))
        out.append(f'<text x="{round(PAD_X + indent * CHAR_WIDTH, 1)}" y="{y}">{"".join(spans)}</text>')
    out.append("</g></svg>")
    return "\n".join(out) + "\n"


# ── the images ───────────────────────────────────────────────────────────────

def images(readme: pathlib.Path = README) -> dict[pathlib.Path, str]:
    """Every image the README asks for: path -> SVG text."""
    made: dict[pathlib.Path, str] = {}
    for block in blocks(readme.read_text(encoding = "utf-8")):
        if not block.render or not block.run:
            continue
        outcome = run_block(block, colours = True)
        if outcome.failures:
            raise RuntimeError("\n".join(outcome.failures))
        text = message_of(outcome.shown)
        for theme in THEMES:
            made[IMAGES / f"{block.render}-{theme}.svg"] = svg(text, theme)
    return made


def main() -> None:
    check = "--check" in sys.argv
    stale = []
    for path, content in images().items():
        if not path.exists() or path.read_text(encoding = "utf-8") != content:
            stale.append(path)
            if not check:
                path.parent.mkdir(parents = True, exist_ok = True)
                path.write_text(content, encoding = "utf-8")
    for path in stale:
        print(("out of date: " if check else "written: ") + str(path.relative_to(ROOT)))
    if check and stale:
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
