from ._typechecker._type_data_model import TypeModel
from ._typechecker._checks import Check
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


class Email(TypeModel[str]):
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


class Port(TypeModel[int]):
    """
    A network port number to connect to: an int from 1 to 65535, and an int afterwards.

    Port 0 is refused. It is no port to connect to; it only means "any free port" when handed to
    ``bind``, and a function that takes that as well should say so (``Port | Literal[0]``).
    ``True`` and ``False`` are refused too: a bool is not a number here, as everywhere in enforced.

    The three properties say which of the IANA ranges the port is in; exactly one of them is true.

    Example:

        >>> port = Port(443)
        ... port.is_system    # True: 1-1023
        ... port + 1          # 444, a plain int
    """

    @classmethod
    def validate(cls, raw: int) -> int:
        if not 0 < raw < 65536:
            raise ValueError("must be between 1 and 65535")
        return raw

    @property
    def is_system(self) -> bool:
        """1-1023: the well-known ports (22, 80, 443). Binding one needs elevated privileges on most systems."""
        return self < 1024

    @property
    def is_registered(self) -> bool:
        """1024-49151: the ports assigned to applications (3306, 5432, 8080)."""
        return 1024 <= self < 49152

    @property
    def is_ephemeral(self) -> bool:
        """49152-65535: the dynamic ports, which a system hands out for outgoing connections."""
        return self >= 49152

