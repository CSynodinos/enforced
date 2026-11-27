from ._validator._type_data_model import TypeModel
from ._validator._checks import Check
from typing import Annotated, Any
from datetime import datetime
from urllib.parse import urlsplit
import ipaddress
import math
import re


#* A number to calculate with: a float (an int is converted), and not nan or an infinity. A check of
#* isinstance(x, (int, float)) would be one no value could fail: it is a float by then.
Number = Annotated[float, Check(math.isfinite)]


# Common numeric type annotations for validation.
PositiveInt = Annotated[int, Check(lambda x: x > 0)]
NegativeInt = Annotated[int, Check(lambda x: x < 0)]
NonNegativeInt = Annotated[int, Check(lambda x: x >= 0)]
PositiveFloat = Annotated[float, Check(lambda x: x > 0)]
NegativeFloat = Annotated[float, Check(lambda x: x < 0)]
NonNegativeFloat = Annotated[float, Check(lambda x: x >= 0)]


# Common string type annotations for validation.
NumericalStr = Annotated[str, Check(lambda x: x.isdigit())]
AlphanumericStr = Annotated[str, Check(lambda x: x.isalnum())]
AlphabeticStr = Annotated[str, Check(lambda x: x.isalpha())]


def _has_text(text: str) -> bool:
    if not text.strip():
        raise ValueError("must not be empty or only whitespace")
    return True


def _has_time_zone(moment: datetime) -> bool:
    if moment.utcoffset() is None:                      # Python's own definition of an aware datetime
        raise ValueError("must have a time zone (tzinfo)")
    return True


def _is_probability(x: float) -> bool:
    if not 0 <= x <= 1:                                 # nan fails both comparisons
        raise ValueError("must be between 0 and 1")
    return True


def _is_percentage(x: float) -> bool:
    if not 0 <= x <= 100:
        raise ValueError("must be between 0 and 100")
    return True


#* Text with something in it: not "", not only spaces. The value is kept as it was given.
NonEmptyStr = Annotated[str, Check(_has_text)]
#* A datetime that knows its offset from UTC. A naive one compared with an aware one raises, and
#* subtracted from one gives a wrong answer: caught where it comes in.
AwareDatetime = Annotated[datetime, Check(_has_time_zone)]
#* A float from 0 to 1, and from 0 to 100 (an int is converted). nan is refused.
Probability = Annotated[float, Check(_is_probability)]
Percentage = Annotated[float, Check(_is_percentage)]


class Email(TypeModel[str]):
    """
    An email address: validated and normalised when it's created, a plain str afterwards.

    Properties:

        * local: The local part of the email address (before the '@').
        * domain: The domain part of the email address (after the '@').
    """
    #* \Z, not $: "$" also matches just before a trailing newline, which let "a\n@b.com" through.
    #* (match() with \Z rather than fullmatch(): measured ~6% faster for the whole validation.)
    _LOCAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+\Z")
    _LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)\Z")

    @classmethod
    def clean(cls, raw: str) -> str:

        address = raw.strip()
        if address.count("@") != 1:
            raise ValueError("must contain exactly one '@'")
        local, domain = address.split("@")

        if not local or len(local) > 64:
            raise ValueError("the part before '@' must be 1-64 characters")
        if not cls._LOCAL.match(local) or local.startswith(".") or local.endswith(".") or ".." in local:
            raise ValueError("the part before '@' contains invalid characters")

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

    Properties:

        * is_system: True if the port is in the well-known range (1-1023).
        * is_registered: True if the port is in the registered range (1024-49151).
        * is_ephemeral: True if the port is in the dynamic/ephemeral range (49152-65535).

    Example:

        >>> port = Port(443)
        ... port.is_system    # True: 1-1023
        ... port + 1          # 444, a plain int
    """

    @classmethod
    def clean(cls, raw: int) -> int:
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


class Url(TypeModel[str]):
    """
    An ``http`` or ``https`` URL with a host: validated and normalised when it's created, a plain
    str afterwards. Other schemes are refused: a model of your own can take them.

    The host may be a name (``example.com``, ``localhost``, ``db_1``), an IPv4 address or an IPv6
    one in brackets (``http://[::1]:8000``). A user name or password before the host is refused
    (``https://good.example@evil.example`` goes to ``evil.example``). Spaces and control characters
    are refused anywhere. The scheme and the host are lower-cased; the rest is kept exactly as given.

    Properties:

        * host: The host part of the URL (lower-cased).
        * port: The port number (default 80 for http, 443 for https if not specified).
        * scheme: The URL scheme (http or https).
        * path: The path part of the URL (including the leading '/').
        * query: The query part of the URL (after the '?' if present).
        * fragment: The fragment part of the URL (after the '#' if present).

    Example:

        >>> url = Url(" HTTPS://Shop.Example:8443/items?page=2 ")
        ... url             # Url('https://shop.example:8443/items?page=2')
        ... url.host        # 'shop.example'
        ... url.port        # 8443 (443 when none is written)
    """
    _LABEL = re.compile(r"(?!-)[\w-]{1,63}(?<!-)\Z")
    _PORT = re.compile(r"[0-9]{1,5}\Z")

    @classmethod
    def clean(cls, raw: str) -> str:
        text = raw.strip()
        #* Before urlsplit, which drops tabs and line breaks without a word.
        if any(c <= " " or c == "\x7f" for c in text):
            raise ValueError("must not contain spaces or control characters")
        scheme, colon, rest = text.partition(":")
        scheme = scheme.lower()
        if not colon or scheme not in ("http", "https"):
            raise ValueError("must be an http or https URL")
        if not rest.startswith("//"):
            raise ValueError("must have a host (http://host/...)")
        rest = rest[2:]
        end = min((rest.find(c) for c in "/?#" if c in rest), default = len(rest))
        authority, rest = rest[:end], rest[end:]
        if "@" in authority:
            raise ValueError("must not contain a user name or password")
        if "\\" in authority:
            raise ValueError("the host contains invalid characters")
        if authority.startswith("["):
            closing = authority.find("]")
            host, port = authority[:closing + 1], authority[closing + 1:]
            try:
                if closing < 0:
                    raise ValueError
                ipaddress.IPv6Address(host[1:-1])
            except ValueError:
                raise ValueError("the host is no valid IPv6 address") from None
        else:
            host, _, port = authority.partition(":")
            port = ":" + port if _ else ""
            cls._check_name(host)
        if port:
            if not port.startswith(":") or not cls._PORT.match(port[1:]) or not 0 < int(port[1:]) < 65536:
                raise ValueError("the port must be a number from 1 to 65535")
        return f"{scheme}://{host.lower()}{port}{rest}"

    @classmethod
    def _check_name(cls, host: str) -> None:
        if not host:
            raise ValueError("must have a host (http://host/...)")
        labels = host[:-1].split(".") if host.endswith(".") else host.split(".")   # a trailing dot: a full name
        if len(host) > 253 or not all(cls._LABEL.match(label) for label in labels):
            raise ValueError("the host contains invalid characters")
        if len(labels) == 4 and all(label.isdigit() for label in labels):
            try:
                ipaddress.IPv4Address(host)
            except ValueError:
                raise ValueError("the host is no valid IPv4 address") from None

    @property
    def scheme(self) -> str:
        """``"http"`` or ``"https"``."""
        return self.partition(":")[0]

    @property
    def host(self) -> str:
        """The host, lower-cased; an IPv6 address without its brackets."""
        return urlsplit(self).hostname or ""

    @property
    def port(self) -> int:
        """The port written in the URL, else the scheme's own: 80 for http, 443 for https."""
        return urlsplit(self).port or (443 if self.scheme == "https" else 80)

    @property
    def path(self) -> str:
        """``"/items"``, or ``""`` when nothing follows the host."""
        return urlsplit(self).path

    @property
    def query(self) -> str:
        """What follows ``?``, without it: ``"page=2"``."""
        return urlsplit(self).query

    @property
    def fragment(self) -> str:
        """What follows ``#``, without it."""
        return urlsplit(self).fragment


class Slug(TypeModel[str]):
    """
    A short name for a URL or an ID: lower-case letters and digits in groups joined by single
    hyphens (``my-post-2``). Surrounding whitespace is stripped and letters are lower-cased, so
    ``" My-Post "`` becomes ``"my-post"``; anything else is refused.
    """
    _SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")

    @classmethod
    def clean(cls, raw: str) -> str:
        slug = raw.strip().lower()
        if not cls._SLUG.match(slug):
            raise ValueError("must be lower-case letters and digits joined by single hyphens (my-post-2)")
        return slug


class PhoneNumber(TypeModel[str]):
    """
    A phone number in the international E.164 form: ``+``, a country code and the number, 8 to 15
    digits in all. Spaces, dashes, dots and brackets are taken out, so ``"+44 (20) 7946-0958"``
    becomes ``"+442079460958"``. A number without its ``+`` and country code is refused: no rule can
    tell which country it belongs to. (Whether the number exists needs a library such as
    ``phonenumbers``.)
    """
    _E164 = re.compile(r"\+[1-9][0-9]{7,14}\Z")
    _SEPARATORS = str.maketrans("", "", " -.()")

    @classmethod
    def clean(cls, raw: str) -> str:
        number = raw.strip().translate(cls._SEPARATORS)
        if not cls._E164.match(number):
            raise ValueError("must be + and a country code, then the number: 8 to 15 digits in all")
        return number


class SecretStr(TypeModel[str]):
    """
    A string that isn't shown: a password, a token, an API key. Its ``repr``, ``str()`` and
    ``format()`` give ``'**********'``, so it stays out of enforced's error messages, the ``repr``
    of a dataclass that holds it, ``print`` and logging. ``get_secret_value()`` gives the text.

    It is still a str: whatever reads its characters (``==``, ``len``, ``.encode()``, a database
    driver, ``json.dumps``) reads the real text. Only the three ways of turning it into text for
    people are masked.

    Example:

        >>> token = SecretStr("hunter2")
        ... token                       # SecretStr('**********')
        ... f"token: {token}"           # 'token: **********'
        ... token.get_secret_value()    # 'hunter2'
    """
    _MASK = "**********"
    def get_secret_value(self) -> str:
        """The text itself, as a plain str."""
        return str.__str__(self)
    def __repr__(self) -> str:
        return f"SecretStr('{self._MASK}')"
    def __str__(self) -> str:
        return self._MASK
    def __format__(self, spec: str) -> str:
        return format(self._MASK, spec)
    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (str.__str__(self),))      # str(self) is the mask: pickle the text
