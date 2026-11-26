"""
The README's examples run, and say what they do: every ```python block is run, each ``# -> value`` is
compared with the value, each ``# InvalidDataError`` (or another error or warning) must happen, and the
coloured images in ``assets/readme`` are what the examples print today (``tools/readme_examples.py``).
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("readme_examples", ROOT / "tools" / "readme_examples.py")
examples = importlib.util.module_from_spec(_spec)               # type: ignore[arg-type]
sys.modules["readme_examples"] = examples                       # its dataclasses look their module up
_spec.loader.exec_module(examples)                              # type: ignore[union-attr]

BLOCKS = [block for block in examples.blocks(examples.README.read_text(encoding = "utf-8")) if block.run]


def test_the_readme_has_examples():
    assert len(BLOCKS) >= 15


@pytest.mark.parametrize("block", BLOCKS, ids = [f"line {block.line}" for block in BLOCKS])
def test_an_example_does_what_its_comments_say(block):
    outcome = examples.run_block(block)
    assert not outcome.failures, "\n".join(outcome.failures)


@pytest.mark.colours
def test_the_images_are_what_the_examples_print():
    made = examples.images()
    assert made, "no <!-- render: ... --> block"
    stale = [str(path.relative_to(ROOT)) for path, content in made.items()
             if not path.exists() or path.read_text(encoding = "utf-8") != content]
    assert not stale, f"run python tools/readme_examples.py: {stale}"
    text = examples.README.read_text(encoding = "utf-8")
    for path in made:
        assert f"assets/readme/{path.name}" in text, f"{path.name} is made but the README never shows it"
