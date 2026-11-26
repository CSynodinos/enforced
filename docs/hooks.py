"""
MkDocs hooks (mkdocs.yml, ``hooks``): the home page is README.md, read as GitHub reads it.
"""
from pathlib import Path
from typing import Any

README = Path(__file__).resolve().parent.parent / "README.md"


def on_page_markdown(markdown: str, page: Any, **_: Any) -> str:
    if page.file.src_uri != "index.md":
        return markdown
    #* The README itself, read here rather than through an include: an include is expanded after
    #* this hook, too late for the change below. GitHub reads Markdown inside the README's centred
    #* header; Python-Markdown does only where the block says so (md_in_html), so the attribute is
    #* added here and the README stays as GitHub wants it.
    return README.read_text(encoding = "utf-8").replace('<div align="center">', '<div align="center" markdown>')
