"""
What differs between Python 3.13 and the versions after it, in one place: the rest of the package
never asks ``sys.version_info``. Every branch reads the same way: 3.13 is the bridge, and whatever
comes after 3.13 follows 3.14's rules (the owner's decision, 2026-11-03).

Imports nothing from the package: any module may use it.
"""
from types import UnionType
from typing import Annotated, Any, Callable, Optional, Union
import dataclasses
import sys

__all__ = ["Format", "PUBLIC_MODULES", "UNION_TYPES", "annotated_of", "annotation_text", "get_annotations", "public_names",
           "standard_make_dataclass", "union_of"]

#* ``isinstance(x, UNION_TYPES)``: a union, however it was written. ``Union[int, str]`` is one object with
#* ``int | str`` from 3.14; on 3.13 another class, equal to it all the same.
UNION_TYPES: Any = (UnionType,) if sys.version_info >= (3, 14) else (UnionType, type(Optional[int]))


if sys.version_info >= (3, 14):
    from annotationlib import Format, get_annotations

    standard_make_dataclass = dataclasses.make_dataclass

    #* A class's module as messages show it.
    PUBLIC_MODULES: dict[str, str] = {}

    def annotation_text(annotation: Any) -> str:
        """``str(annotation)``, as messages show it."""
        return str(annotation)

    def public_names(text: str) -> str:
        """``text`` as messages show it: as it is."""
        return text

else:
    from enum import IntEnum
    from types import new_class, NoneType
    from typing import get_args, get_origin, Literal
    import inspect
    import keyword

    PUBLIC_MODULES = {"pathlib._local": "pathlib"}

    class Format(IntEnum):
        """``annotationlib.Format``, for the names the package uses."""
        VALUE = 1
        FORWARDREF = 3
        STRING = 4

    def get_annotations(obj: Any, *, format: Format = Format.VALUE) -> dict[str, Any]:
        """
        3.13 evaluated the annotations when it ran their ``def`` or class, so ``FORWARDREF`` is ``VALUE`` here,
        and ``STRING`` writes each one out. What was quoted stays a string under any format.
        """
        found = inspect.get_annotations(obj)
        if format is Format.STRING:
            return {name: value if isinstance(value, str) else inspect.formatannotation(value) for name, value in found.items()}
        return found

    def standard_make_dataclass(
        cls_name: str,
        fields: Any,
        *,
        bases: tuple[type, ...] = (),
        namespace: dict[str, Any] | None = None,
        module: str | None = None,
        decorator: Callable[..., Any] = dataclasses.dataclass,
        **options: Any,
        ) -> type:
        """``dataclasses.make_dataclass`` of 3.14: 3.13's calls its own ``dataclass``, and has no ``decorator``."""
        seen: set[str] = set()
        annotations: dict[str, Any] = {}
        defaults: dict[str, Any] = {}
        for item in fields:
            if isinstance(item, str):
                name, annotation = item, Any
            elif len(item) == 2:
                name, annotation = item
            elif len(item) == 3:
                name, annotation, defaults[item[0]] = item
            else:
                raise TypeError(f"Invalid field: {item!r}")
            if not isinstance(name, str) or not name.isidentifier():
                raise TypeError(f"Field names must be valid identifiers: {name!r}")
            if keyword.iskeyword(name):
                raise TypeError(f"Field names must not be keywords: {name!r}")
            if name in seen:
                raise TypeError(f"Field name duplicated: {name!r}")
            seen.add(name)
            annotations[name] = annotation

        def body(class_namespace: dict[str, Any]) -> None:
            class_namespace.update(namespace or {})
            class_namespace.update(defaults)
            class_namespace["__annotations__"] = annotations

        cls = new_class(cls_name, bases, {}, body)
        if module is not None:
            cls.__module__ = module
        return decorator(cls, **options)                    # type: ignore[no-any-return]

    def annotation_text(annotation: Any) -> str:
        """``str(annotation)`` as 3.14 prints it: 3.13 says ``Optional[X]``, ``Union[X, NoneType]``, ``pathlib._local.Path``."""
        text = str(annotation)
        return public_names(_written(annotation) if "Union[" in text or "Optional[" in text else text)

    def _written(annotation: Any) -> str:
        """Made from the objects, which still know the order of a union, where ``str`` has lost it (``None | X``)."""
        if isinstance(annotation, UNION_TYPES):
            return " | ".join("None" if member is NoneType else _written(member) for member in annotation.__args__)
        if annotation is ...:
            return "..."
        if isinstance(annotation, list):                # the parameters of a ``Callable``
            return f"[{', '.join(_written(part) for part in annotation)}]"
        args = get_args(annotation)
        if isinstance(annotation, type) and not args:
            return annotation.__qualname__ if annotation.__module__ == "builtins" else f"{annotation.__module__}.{annotation.__qualname__}"
        if not args or get_origin(annotation) is Literal:
            return repr(annotation)
        return f"{repr(annotation).partition('[')[0]}[{', '.join(_written(part) for part in args)}]"

    def public_names(text: str) -> str:
        """``text`` without the module 3.13 keeps the classes of ``pathlib`` in, which 3.14 doesn't show."""
        return text.replace("pathlib._local.", "pathlib.") if "pathlib._local." in text else text


#* ``typing`` keeps what ``Union[...]`` (on 3.13) and ``Annotated[...]`` (on every version) made in a cache,
#* the 128 most recent, and with it the classes they name. An annotation enforced writes for a class made
#* at run time must not keep that class alive, so these two step past the cache. Private names, read
#* with ``getattr``: where they are gone the annotation comes from the cache, and is just as good.
_UNION_UNCACHED: Any = getattr(Union, "_getitem", None) if sys.version_info < (3, 14) else None
_ANNOTATED_UNCACHED: Any = getattr(getattr(Annotated, "_getitem", None), "__wrapped__", None)


def union_of(members: tuple[Any, ...]) -> Any:
    """``Union[members]``, with nothing kept by ``typing``."""
    return Union[members] if _UNION_UNCACHED is None else _UNION_UNCACHED(Union, members)


def annotated_of(parts: tuple[Any, ...]) -> Any:
    """``Annotated[parts]``, with nothing kept by ``typing``."""
    return Annotated[parts] if _ANNOTATED_UNCACHED is None else _ANNOTATED_UNCACHED(Annotated, *parts)
