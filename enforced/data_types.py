from ._typechecker._type_data_model import TypeModel
from ._typechecker._type_container import Check
from typing import Annotated
import math
import re


#* A number to calculate with: a float (an int is converted), and not nan or an infinity. The check
#* used to be isinstance(x, (int, float)), which no value could fail: it is a float by then.
Number = Annotated[float, Check(math.isfinite)]


# Common numeric type annotations for validation.
PositiveInt = Annotated[int, lambda x: x > 0]
NegativeInt = Annotated[int, lambda x: x < 0]
NonNegativeInt = Annotated[int, lambda x: x >= 0]
PositiveFloat = Annotated[float, lambda x: x > 0]
NegativeFloat = Annotated[float, lambda x: x < 0]
NonNegativeFloat = Annotated[float, lambda x: x >= 0]


# Common string type annotations for validation.
NumericalStr = Annotated[str, lambda x: x.isdigit()]
AlphanumericStr = Annotated[str, lambda x: x.isalnum()]
AlphabeticStr = Annotated[str, lambda x: x.isalpha()]


class Email(TypeModel[str], str):
    """
    An email address: validated and normalised when it's created, a plain str afterwards.
    """
    #* \Z, not $: "$" also matches just before a trailing newline, which let "a\n@b.com" through.
    #* (match() with \Z rather than fullmatch(): measured ~6% faster for the whole validation.)
    _LOCAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+\Z")
    _LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)\Z")

    @classmethod
    def validate(cls, raw: str) -> str:

        # Strip leading and trailing whitespace from the raw email address.
        address = raw.strip()
        if address.count("@") != 1:
            raise ValueError("must contain exactly one '@'")
        local, domain = address.split("@")

        # Validate the local part of the email address.
        if not local or len(local) > 64:
            raise ValueError("the part before '@' must be 1-64 characters")
        if not cls._LOCAL.match(local) or local.startswith(".") or local.endswith(".") or ".." in local:
            raise ValueError("the part before '@' contains invalid characters")

        # Validate the domain part of the email address.
        labels = domain.split(".")
        if len(labels) < 2 or not all(cls._LABEL.match(label) for label in labels):
            raise ValueError("the domain must look like example.com")
        if len(address) > 254:
            raise ValueError("must be at most 254 characters")

        return f"{local}@{domain.lower()}"      # domains are case-insensitive; the local part may not be

    @property
    def local(self) -> str:
        return str(self).partition("@")[0]

    @property
    def domain(self) -> str:
        return str(self).partition("@")[2]


class Port(TypeModel[int], int):
    """
    A network port number: validated to be within the range 1-65535.
    """

    @classmethod
    def validate(cls, raw: int) -> int:
        if not 0 < raw < 65536:
            raise ValueError("must be between 1 and 65535")
        return raw

