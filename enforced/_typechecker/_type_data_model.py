"""TypeModel[T]: a single validated value that *is* a T (an ``Email`` is a ``str``)."""
from typing import Any, ClassVar, Generic, Self, TypeVar
from abc import ABCMeta
from decimal import Decimal
from fractions import Fraction
from ._type_conversion import FAILED        # the same sentinel the converters use

#* Base types a model can extend: immutable and subclassable (so the value can *be* a T).
_ALLOWED_BASES = (str, int, float, complex, bytes, Decimal, Fraction)


def _base_slots(base: type) -> frozenset[str]:
    return frozenset(n for k in base.__mro__ for n in getattr(k, "__slots__", ()) if isinstance(n, str))


T = TypeVar("T")


class ModelMeta(type):
    """
    Metaclass of every TypeModel class. It does one thing: a model class that says nothing about
    ``__slots__`` gets ``__slots__ = ()``, so its instances carry no ``__dict__`` and are as small
    as a subclass of the base type can be (a ``Port`` is 44 bytes, 60 with a dictionary that
    nothing could use: instances are immutable). A class that wants one back, for a
    ``functools.cached_property`` say, writes ``__slots__ = ("__dict__",)``.

    Slots are fixed when the class statement runs, and only a metaclass can step in there. The
    price is that ``isinstance(x, Model)`` takes a slower route in Python when ``x`` is no instance
    of exactly ``Model``. The checker keeps that off the valid-call path: in a union it tests the
    ordinary classes first (see ``_type_spec``), so ``None`` for ``Email | None`` never gets there.
    """

    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any) -> Any:
        namespace.setdefault("__slots__", ())
        return super().__new__(mcls, name, bases, namespace, **kwargs)


class _AbstractModelMeta(ModelMeta, ABCMeta):
    """For a base type that has a metaclass of its own (``Fraction`` is registered as a number through ABCMeta)."""


class TypeModel(Generic[T], metaclass = ModelMeta):
    """
    Subclass ``TypeModel[T]`` and define ``validate``:

        class Email(TypeModel[str]):
            @classmethod
            def validate(cls, raw: str) -> str: ...   # return the normalised value, or raise ValueError(reason)

    ``Email("a@b.com")`` validates, then builds an ``Email``, which is a real ``str``.

    For a static type checker, name the base type a second time: ``class Email(TypeModel[str], str)``.
    At runtime the two spellings are the same class (``TypeModel[str]`` already inherits from ``str``).
    A checker can't know that: it sees a generic class, which is what ``Generic[T]`` is here for
    (without it mypy refuses ``TypeModel[str]`` altogether), and learns from the second base that an
    ``Email`` is a ``str``.

    Instances carry no ``__dict__``: a model class gets ``__slots__ = ()`` unless it declares
    slots itself (see ``ModelMeta``).
    """
    __slots__ = ()

    __base_type__: ClassVar[type]                      # T, set by TypeModel[T]
    auto_construct: ClassVar[bool] = True              # enforced builds it from a raw T under convert=True
    _BASES: ClassVar[dict[type, type]] = {}

    # ── TypeModel[T] -> a real base class that subclasses T ────────────────────
    def __class_getitem__(cls, base: type) -> type:
        if cls is not TypeModel:
            raise TypeError(f"{cls.__name__} is already parameterised")
        if not isinstance(base, type) or not issubclass(base, _ALLOWED_BASES) or base is bool:
            raise TypeError(f"TypeModel[{getattr(base, '__name__', base)}]: the base type must be one of "
                            + ", ".join(t.__name__ for t in _ALLOWED_BASES))
        made = cls._BASES.get(base)
        if made is None:
            meta = ModelMeta if type(base) is type else _AbstractModelMeta
            made = cls._BASES[base] = meta(f"TypeModel[{base.__name__}]", (TypeModel, base),
                                           {"__slots__": (), "__base_type__": base, "__module__": __name__})
        return made

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "__base_type__"):
            raise TypeError(f"{cls.__name__} must subclass TypeModel[T], e.g. TypeModel[str]")
        if "__new__" in vars(cls) or "__init__" in vars(cls):
            raise TypeError(f"{cls.__name__}: put the checks in the validate classmethod, not __new__/__init__")

    # ── construction = validation ─────────────────────────────────────────────
    def __new__(cls, raw: Any) -> Self:
        base = cls.__base_type__
        if type(raw) is not base:                       # a plain T (the common case) skips these tests
            if isinstance(raw, cls):
                return raw                              # already validated; values are immutable
            if not isinstance(raw, base) or (base is int and isinstance(raw, bool)):
                raise TypeError(f"{cls.__name__} expects a {base.__name__}, got {type(raw).__name__}")
            raw = base(raw)                             # a plain T, so validate never sees a subclass
        value = cls.validate(raw)
        if type(value) is not base and not isinstance(value, base):
            raise TypeError(f"{cls.__name__}.validate must return a {base.__name__}")
        return base.__new__(cls, value)                 # type: ignore[arg-type, return-value]

    @classmethod
    def validate(cls, raw: Any) -> Any:
        """Override: return the (normalised) value, or raise ValueError with a reason."""
        return raw

    # ── the hook enforced calls: value -> model instance | FAILED (+ the reason) ───
    @classmethod
    def __enforced_convert__(cls, value: Any) -> "tuple[Any, str | None]":
        if isinstance(value, cls):
            return value, None
        if not isinstance(value, cls.__base_type__) or isinstance(value, bool):
            return FAILED, None                         # wrong type entirely: the usual type error
        try:
            return cls(value), None
        except ValueError as e:
            return FAILED, str(e)                       # the reason shown in the error message

    # ── plain-value behaviour ─────────────────────────────────────────────────
    def __setattr__(self, name: str, value: Any) -> None:
        #* Only the base type's own slots may be filled, once, while it builds itself (Fraction does this).
        if name in _base_slots(type(self).__base_type__) and not hasattr(self, name):
            return object.__setattr__(self, name, value)
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.__base_type__.__repr__(self)})"   # type: ignore[call-arg]

    #* A copy of an immutable value is the value. (Fraction has a __copy__ of its own that calls
    #* the class with two arguments, which a model's constructor doesn't take.)
    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, memo: Any) -> Self:
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.__base_type__(self),))  # pickle/copy re-validate through the constructor
