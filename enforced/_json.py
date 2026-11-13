"""
``to_json``: a value as JSON text, with the types enforced works with (dataclasses, ``TypeModel``s,
``SecretStr``, enums, dates ...), and without the trap of ``json.dumps``: a ``SecretStr`` is a ``str``,
so ``json.dumps`` writes its real text. Here it is written masked unless ``reveal_secrets``.

Not on any checking path: nothing here is imported by the checkers.
"""
from .data_types import SecretStr
from ._validator._transform import Transform
from collections.abc import Mapping
from datetime import date, time
from enum import Enum
from typing import Any
import dataclasses
import json


def to_json(obj: Any, *, indent: int | None = None, reveal_secrets: bool = False) -> str:
    """
    ``obj`` as JSON text.

    What each value becomes:

    - ``None``, ``bool``, ``int``, ``float``, ``str``: themselves; a subclass (``Port``, ``Email``, any
      ``TypeModel``) as its base value. ``NaN`` and the infinities are refused (they are no JSON).
    - ``SecretStr``: ``"**********"``, or its real text with ``reveal_secrets = True`` (to write a
      configuration file, say).
    - a ``Transform``: what it holds (``value``), written by these same rules.
    - a dataclass instance: an object of its fields, nested ones included.
    - a mapping: an object. Its keys must be text, numbers, booleans or ``None`` (JSON makes them text)
      or enum members of such values.
    - a list, tuple, set or frozenset: an array (a set in its own order).
    - an ``Enum`` member: its value. ``datetime``, ``date``, ``time``: ISO 8601 (``isoformat()``).
      ``Decimal``, ``Fraction``, ``UUID`` and paths: their text (``"1.10"``, ``"1/3"``).

    Anything else, ``bytes`` and ``timedelta`` among them, is a ``TypeError`` naming its type and where
    it is (``orders[2].total``), and a value that contains itself a ``ValueError``.

    Args:
        obj: The value.
        indent (int | None): As for ``json.dumps``: ``None`` (default) writes one line.
        reveal_secrets (bool): Write a ``SecretStr``'s real text. Off by default.

    Example:

        >>> @dataclass
        ... class Login:
        ...     user: Email
        ...     password: SecretStr
        ...     at: datetime
        >>> to_json(Login("ana@example.com", "s3cret", datetime(2026, 10, 22, 9, 30)))
        '{"user": "ana@example.com", "password": "**********", "at": "2026-10-22T09:30:00"}'
    """
    data = _plain(obj, reveal_secrets, "", set())
    try:
        return json.dumps(data, indent = indent, ensure_ascii = False, allow_nan = False)
    except ValueError as e:
        raise ValueError(f"to_json: {e} (NaN and the infinities are no JSON)") from None


#* (module, class) of the values written as their text. Compared by name, as ``_type_conversion`` does,
#* so that importing enforced never imports these modules (a test holds it).
_AS_TEXT = frozenset({("decimal", "Decimal"), ("fractions", "Fraction"), ("uuid", "UUID"), ("pathlib", "PurePath")})


def _written_as_text(cls: type) -> bool:
    return any((getattr(base, "__module__", "").split(".")[0], base.__qualname__) in _AS_TEXT for base in cls.__mro__)


def _where(path: str) -> str:
    return f" at {path}" if path else ""


def _plain(value: Any, reveal: bool, path: str, active: set[int]) -> Any:
    """``value`` as what ``json.dumps`` writes as it is. ``active``: the containers being walked (a cycle)."""
    mask = str
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, SecretStr):
        return str.__str__(value) if reveal else mask(value)
    if isinstance(value, Enum):
        return _plain(value.value, reveal, path, active)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return str.__str__(value)                                   # a subclass's own text, not its __str__
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, (date, time)):                              # datetime is a date
        return value.isoformat()
    if _written_as_text(type(value)):
        return str(value)

    if isinstance(value, Transform):
        return _plain(value.value, reveal, path, active)            # what it holds
    if id(value) in active:
        raise ValueError(f"to_json: the value contains itself{_where(path)}")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        active.add(id(value))
        try:
            return {f.name: _plain(getattr(value, f.name), reveal, _step(path, f.name), active)
                    for f in dataclasses.fields(value)}
        finally:
            active.discard(id(value))
    if isinstance(value, Mapping):
        active.add(id(value))
        try:
            return {_key(key, path): _plain(item, reveal, _step(path, key), active) for key, item in value.items()}
        finally:
            active.discard(id(value))
    if isinstance(value, (list, tuple, set, frozenset)):
        active.add(id(value))
        try:
            return [_plain(item, reveal, f"{path}[{i}]", active) for i, item in enumerate(value)]
        finally:
            active.discard(id(value))
    raise TypeError(f"to_json: a {type(value).__name__} can't be written as JSON{_where(path)}: {_shown(value)}")


def _key(key: Any, path: str) -> Any:
    """A key as JSON takes it: text (a ``SecretStr`` key stays masked: a key is no place for a secret)."""
    if isinstance(key, Enum):
        key = key.value
    if key is None or type(key) in (str, int, float, bool):
        return key
    if isinstance(key, SecretStr):
        return str(key)                                             # the mask
    if isinstance(key, str):
        return str.__str__(key)
    if isinstance(key, int):
        return int(key)
    if isinstance(key, float):
        return float(key)
    raise TypeError(f"to_json: a key must be text or a number, got a {type(key).__name__}{_where(path)}: {_shown(key)}")


def _step(path: str, key: Any) -> str:
    return f"{path}.{key}" if path else str(key)                    # str() of a SecretStr key is the mask


def _shown(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."
