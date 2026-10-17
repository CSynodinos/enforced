"""The ready-made types in enforced.data_types, on their own and through the checker."""
from typing import Any, get_args
import pickle
import re

import pytest

from enforced import typecheck, dataclass, InvalidDataError, TypeModel
from enforced.data_types import Email, Port, PositiveInt, NegativeInt, NonNegativeInt, Number


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _message(fn, *args, **kwargs) -> str:
    with pytest.raises(InvalidDataError) as info:
        fn(*args, **kwargs)
    return _plain(str(info.value))


# ── Email ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "ana@example.com",
    "first.last@example.co.uk",
    "a+tag@sub.example.org",
    "x@a-b.io",
    "o'brien@example.ie",
    "!#$%&'*+/=?^_`{|}~-@example.com",
    "a" * 64 + "@example.com",
])
def test_email_accepts_valid_addresses(raw):
    assert Email(raw) == raw


@pytest.mark.parametrize("raw, reason", [
    ("", "exactly one '@'"),
    ("plainaddress", "exactly one '@'"),
    ("a@b@example.com", "exactly one '@'"),
    ("@example.com", "1-64 characters"),
    ("a" * 65 + "@example.com", "1-64 characters"),
    ("a b@example.com", "invalid characters"),
    ("a(b)@example.com", "invalid characters"),
    (".ana@example.com", "invalid characters"),
    ("ana.@example.com", "invalid characters"),
    ("an..a@example.com", "invalid characters"),
    ("ana@", "domain must look like"),
    ("ana@example", "domain must look like"),
    ("ana@example.", "domain must look like"),
    ("ana@.example.com", "domain must look like"),
    ("ana@exa..mple.com", "domain must look like"),
    ("ana@-example.com", "domain must look like"),
    ("ana@example-.com", "domain must look like"),
    ("ana@exam_ple.com", "domain must look like"),
    ("ana@" + "a" * 64 + ".com", "domain must look like"),
])
def test_email_rejects_invalid_addresses(raw, reason):
    with pytest.raises(ValueError, match=re.escape(reason)):
        Email(raw)


@pytest.mark.parametrize("raw", ["a\n@example.com", "ana@example\n.com", "ana@example.com\n.org"])
def test_email_rejects_embedded_newlines(raw):
    """A line break inside an address is never valid (in a "validated" address it is a way to inject mail headers)."""
    with pytest.raises(ValueError):
        Email(raw)


def test_email_total_length_limit():
    local = "a" * 64
    domain = ".".join(["b" * 60] * 4)                # 243 characters
    assert len(f"{local}@{domain}") > 254
    with pytest.raises(ValueError, match="at most 254"):
        Email(f"{local}@{domain}")
    ok = f"{local}@{'b' * 60}.{'c' * 60}.{'d' * 60}"
    assert len(ok) <= 254 and Email(ok) == ok


def test_email_strips_whitespace_and_lowercases_only_the_domain():
    e = Email("  Ana.Smith@Example.COM\n")
    assert e == "Ana.Smith@example.com"
    assert e.local == "Ana.Smith"
    assert e.domain == "example.com"


def test_email_parts_are_plain_str():
    e = Email("ana@example.com")
    assert type(e.local) is str and type(e.domain) is str


def test_email_is_a_str():
    e = Email("ana@example.com")
    assert isinstance(e, str)
    assert e.endswith(".com") and e.split("@") == ["ana", "example.com"]


def test_email_rejects_non_str():
    for bad in (None, 5, b"ana@example.com"):
        with pytest.raises(TypeError):
            Email(bad)


def test_email_pickles():
    e = Email("ana@example.com")
    assert pickle.loads(pickle.dumps(e)) == e


# ── Port ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [1, 22, 80, 443, 8080, 65535])
def test_port_accepts_the_valid_range(raw):
    p = Port(raw)
    assert p == raw and isinstance(p, int) and type(p) is Port


@pytest.mark.parametrize("raw", [0, -1, 65536, 10**9])
def test_port_rejects_out_of_range(raw):
    with pytest.raises(ValueError, match="between 1 and 65535"):
        Port(raw)


@pytest.mark.parametrize("raw", [True, 80.0, "80", None])
def test_port_rejects_non_int(raw):
    with pytest.raises(TypeError):
        Port(raw)


# ── Annotated number types: the checks themselves ────────────────────────────

def _checks(alias):
    return get_args(alias)[1:]


@pytest.mark.parametrize("alias, good, bad", [
    (PositiveInt, [1, 2, 10**20], [0, -1]),
    (NegativeInt, [-1, -10**20], [0, 1]),
    (NonNegativeInt, [0, 1, 10**20], [-1]),
])
def test_number_alias_checks(alias, good, bad):
    assert get_args(alias)[0] is int
    for v in good:
        assert all(check(v) for check in _checks(alias))
    for v in bad:
        assert not all(check(v) for check in _checks(alias))


def test_number_alias_is_float_based():
    assert get_args(Number)[0] is float


# ── Annotated number types through the checker ───────────────────────────────

@typecheck
def numbers(p: PositiveInt, n: NegativeInt, z: NonNegativeInt, x: Number):
    return p, n, z, x


def test_number_types_accept_valid_values():
    assert numbers(1, -1, 0, 1.5) == (1, -1, 0, 1.5)


def test_number_type_converts_int_to_float():
    out = numbers(1, -1, 0, 2)
    assert out[3] == 2.0 and type(out[3]) is float


@pytest.mark.parametrize("args, name, check", [
    ((0, -1, 0, 1.0), "p", "x > 0"),
    ((-5, -1, 0, 1.0), "p", "x > 0"),
    ((1, 0, 0, 1.0), "n", "x < 0"),
    ((1, -1, -1, 1.0), "z", "x >= 0"),
])
def test_number_types_reject_values_failing_their_check(args, name, check):
    msg = _message(numbers, *args)
    assert f"For parameter {name} of <Function numbers>: invalid 'int': failed check {check}" in msg


def test_number_types_report_every_failure():
    msg = _message(numbers, 0, 0, -1, 1.0)
    assert msg.startswith("3 problems found in call:")


@pytest.mark.parametrize("args", [
    (True, -1, 0, 1.0),          # bool is not an int
    (1.0, -1, 0, 1.0),           # float is not an int
    ("1", -1, 0, 1.0),           # no coercion by default
    (1, -1, 0, "1.5"),
    (1, -1, 0, True),
])
def test_number_types_still_check_the_type(args):
    msg = _message(numbers, *args)
    assert "expected type: " in msg and "invalid" not in msg


def test_number_types_coerce_then_check():
    @typecheck(coerce=True)
    def f(p: PositiveInt, x: Number):
        return p, x

    assert f("5", "2.5") == (5, 2.5)
    assert "failed check x > 0" in _message(f, "-5", 1.0)


def test_port_ranges():
    #* The three IANA ranges: every port is in exactly one of them.
    for number, expected in ((1, "system"), (22, "system"), (1023, "system"), (1024, "registered"), (8080, "registered"),
                             (49151, "registered"), (49152, "ephemeral"), (65535, "ephemeral")):
        port = Port(number)
        ranges = {"system": port.is_system, "registered": port.is_registered, "ephemeral": port.is_ephemeral}
        assert [name for name, inside in ranges.items() if inside] == [expected], number
        assert all(type(inside) is bool for inside in ranges.values())
    assert Port(443) + 1 == 444 and type(Port(443) + 1) is int      # arithmetic gives a plain int, as before


@pytest.mark.parametrize("flag", [True, False])
def test_port_says_why_a_bool_is_not_a_port(flag):
    with pytest.raises(TypeError, match = rf"Port expects an int, got the bool {flag}: True and False are not taken for 1 and 0 "
                                          rf"\(write Port\({int(flag)}\) if the number is meant\)"):
        Port(flag)

    @typecheck
    def listen(port: Port) -> Port:
        return port

    assert "expected type: 'enforced.data_types.Port', got type 'bool'" in _message(listen, flag)   # through the checker: the usual type error


def test_port_zero_is_refused_and_can_be_allowed_by_name():
    from typing import Literal

    @typecheck
    def bind(port: Port | Literal[0]) -> Any:
        return port

    with pytest.raises(ValueError, match = "must be between 1 and 65535"):
        Port(0)
    assert bind(0) == 0 and type(bind(8080)) is Port and "Port" in (Port.__doc__ or "") and "Port 0 is refused" in Port.__doc__


# ── Email and Port through the checker ───────────────────────────────────────

@typecheck
def connect(host: Email, port: Port):
    return host, port


def test_raw_values_are_built_into_models():
    host, port = connect(" Ana@Example.COM ", 8080)
    assert type(host) is Email and host == "Ana@example.com"
    assert type(port) is Port and port == 8080


def test_existing_instances_pass_unchanged():
    e, p = Email("ana@example.com"), Port(22)
    host, port = connect(e, p)
    assert host is e and port is p


def test_invalid_raw_values_report_the_reason():
    msg = _message(connect, "nope", 0)
    assert "For parameter host of <Function connect>: invalid 'Email': must contain exactly one '@' (Value: 'nope')" in msg
    assert "For parameter port of <Function connect>: invalid 'Port': must be between 1 and 65535 (Value: 0)" in msg


def test_wrong_types_are_type_errors_not_invalid():
    msg = _message(connect, 5, "80")
    assert "invalid" not in msg
    assert "got type 'int'" in msg and "got type 'str'" in msg


def test_bool_is_not_a_port():
    msg = _message(connect, "ana@example.com", True)
    assert "got type 'bool'" in msg


def test_port_from_str_needs_coerce():
    @typecheck(coerce=True)
    def listen(port: Port):
        return port

    assert listen("8080") == 8080 and type(listen("8080")) is Port
    assert "invalid 'Port': must be between 1 and 65535 (Value: '99999')" in _message(listen, "99999")
    assert "got type 'str'" in _message(connect, "a@b.com", "8080")


def test_dataclass_with_data_types():
    @dataclass
    class Server:
        admin: Email
        port: Port = 8080
        workers: PositiveInt = 4

    s = Server("Admin@Example.com")
    assert type(s.admin) is Email and s.admin.domain == "example.com"
    assert type(s.port) is Port and s.workers == 4

    s.port = 443
    assert type(s.port) is Port
    with pytest.raises(InvalidDataError) as info:
        s.workers = 0
    assert "Field Server.workers of <Dataclass Server>: invalid 'int': failed check x > 0 (Value: 0)" in _plain(str(info.value))

    with pytest.raises(InvalidDataError) as info:
        Server("admin@example.com", port = 70000)
    assert "invalid 'Port': must be between 1 and 65535" in _plain(str(info.value))


# ── review finding 18 and the Number alias ───────────────────────────────────

def test_shipped_models_carry_no_dict():
    import pickle
    import sys

    port, email = Port(80), Email("A@B.co")
    for value in (port, email):
        assert not hasattr(value, "__dict__")
        assert pickle.loads(pickle.dumps(value)) == value
    assert sys.getsizeof(port) < 60                                 # 60 with a __dict__, 44 without
    assert (email.local, email.domain, email + "!") == ("A", "b.co", "A@b.co!")
    assert port + 1 == 81 and isinstance(port, int) and isinstance(email, str)
    with pytest.raises(AttributeError):
        port.note = "x"                                             # type: ignore[attr-defined]


def test_user_model_carries_no_dict_without_being_told():
    #* Review finding 18: a model class needed __slots__ = () written out, or every instance had a __dict__.
    import copy
    import functools
    import sys
    from decimal import Decimal
    from fractions import Fraction

    class Usual(TypeModel[int]):
        pass

    class Short(TypeModel[str]):                                    # the short form
        pass

    class Half(TypeModel[Fraction]):                      # a base type with a metaclass of its own
        pass

    class Price(TypeModel[Decimal]):
        pass

    class Child(Usual):
        pass

    for value in (Usual(1), Short("a"), Half(Fraction(1, 2)), Price(Decimal(1)), Child(1)):
        assert not hasattr(value, "__dict__") and copy.copy(value) == value
        with pytest.raises(AttributeError):
            value.note = "x"                                        # type: ignore[attr-defined]
    assert sys.getsizeof(Usual(1)) == sys.getsizeof(Port(80)) < 60
    assert Half(Fraction(1, 2)) + 1 == Fraction(3, 2) and isinstance(Half(Fraction(1, 2)), Fraction)

    class Keeps(TypeModel[str]):                               # one that wants its dictionary back says so
        __slots__ = ("__dict__",)

        @functools.cached_property
        def shout(self) -> str:
            return self.upper()

    assert Keeps("a").shout == "A" and hasattr(Keeps("a"), "__dict__")


def test_model_in_a_union_is_checked_as_before():
    @typecheck
    def f(a: Email | None = None, b: int | Port | str = 0, c: Port | None | float = None):
        return a, b, c

    email, port = Email("a@b.co"), Port(80)
    for _ in range(3):
        assert f() == (None, 0, None) and f(email, port, port) == (email, port, port)
        assert f(None, "x", 1.5) == (None, "x", 1.5) and type(f("c@d.co")[0]) is Email
        assert type(f(None, 1, 80)[2]) is Port and type(f(None, 1, 70000)[2]) is float
        for bad in (lambda: f(5), lambda: f(None, 1.5), lambda: f(None, True), lambda: f(None, 0, "x")):
            with pytest.raises(InvalidDataError):
                bad()


def test_number_rejects_what_is_no_finite_number():
    #* Its check was isinstance(x, (int, float)), which no value could fail: it is a float by then.
    @typecheck
    def f(x: Number):
        return x

    assert f(1.5) == 1.5 and type(f(2)) is float and f(-0.0) == 0
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(InvalidDataError) as e:
            f(value)
        assert e.value.problems[0].kind == "invalid" and "isfinite" in str(e.value)
    for value in ("1", True, None, 1j):
        with pytest.raises(InvalidDataError):
            f(value)


# ── Url ──────────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone          # noqa: E402
from enforced.data_types import (                            # noqa: E402
    AwareDatetime, NonEmptyStr, Percentage, PhoneNumber, Probability, SecretStr, Slug, Url,
    )


@pytest.mark.parametrize("raw, stored, host, port", [
    (" HTTPS://Shop.Example:8443/Items?Page=2#Top ", "https://shop.example:8443/Items?Page=2#Top", "shop.example", 8443),
    ("http://example.com", "http://example.com", "example.com", 80),
    ("https://example.com/", "https://example.com/", "example.com", 443),
    ("http://localhost:8000/health", "http://localhost:8000/health", "localhost", 8000),
    ("http://db_1:5432", "http://db_1:5432", "db_1", 5432),             # every kind of host: a single name too
    ("http://10.0.0.1/x", "http://10.0.0.1/x", "10.0.0.1", 80),
    ("http://[::1]:8000/", "http://[::1]:8000/", "::1", 8000),
    ("http://[2001:DB8::1]", "http://[2001:db8::1]", "2001:db8::1", 80),
    ("https://example.com.", "https://example.com.", "example.com.", 443),
    ("https://bücher.example/ü", "https://bücher.example/ü", "bücher.example", 443),
    ("https://example.com?q=1", "https://example.com?q=1", "example.com", 443),
])
def test_url_accepts_and_normalises(raw, stored, host, port):
    url = Url(raw)
    assert url == stored and type(url) is Url and url.host == host and url.port == port
    assert url.scheme == stored.partition(":")[0]


def test_url_parts():
    url = Url("https://a.example:444/p/q?x=1&y=2#frag")
    assert (url.path, url.query, url.fragment) == ("/p/q", "x=1&y=2", "frag")
    assert (Url("http://a.example").path, Url("http://a.example").query, Url("http://a.example").fragment) == ("", "", "")
    assert str(url).startswith("https://") and pickle.loads(pickle.dumps(url)) == url


@pytest.mark.parametrize("raw, reason", [
    ("ftp://files.example", "http or https"),
    ("javascript:alert(1)", "http or https"),
    ("mailto:a@b.co", "http or https"),
    ("example.com", "http or https"),
    ("http:example.com", "must have a host"),
    ("https://", "must have a host"),
    ("https:///path", "must have a host"),
    ("https://good.example@evil.example", "user name or password"),       # goes to evil.example
    ("https://user:pass@host.example", "user name or password"),
    ("http://a b.example", "spaces or control characters"),
    ("http://a.example/\npath", "spaces or control characters"),
    ("http://a.example/\tx", "spaces or control characters"),
    ("http://a.example:0", "port"),
    ("http://a.example:65536", "port"),
    ("http://a.example:", "port"),
    ("http://a.example:8o", "port"),
    ("http://-a.example", "invalid characters"),
    ("http://a-.example", "invalid characters"),
    ("http://a..example", "invalid characters"),
    ("http://a\\b.example", "invalid characters"),
    ("http://" + "a" * 64 + ".example", "invalid characters"),
    ("http://999.1.1.1", "IPv4"),
    ("http://[::zz]", "IPv6"),
    ("http://[::1", "IPv6"),
    ("http://[::1]x", "port"),
])
def test_url_refuses(raw, reason):
    with pytest.raises(ValueError, match = re.escape(reason)):
        Url(raw)


def test_url_through_the_checker():
    @typecheck
    def fetch(url: Url) -> Url:
        return url
    assert fetch("HTTPS://Example.com/a") == "https://example.com/a" and type(fetch("http://x.example")) is Url
    assert "invalid 'Url': must be an http or https URL (Value: 'ftp://x')" in _message(fetch, "ftp://x")


# ── Slug, PhoneNumber ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, stored", [("my-post-2", "my-post-2"), (" My-Post ", "my-post"), ("a", "a"), ("2024", "2024")])
def test_slug_accepts(raw, stored):
    assert Slug(raw) == stored


@pytest.mark.parametrize("raw", ["", "my--post", "-a", "a-", "a_b", "a b", "ça", "a.b"])
def test_slug_refuses(raw):
    with pytest.raises(ValueError, match = "single hyphens"):
        Slug(raw)


@pytest.mark.parametrize("raw, stored", [
    ("+442079460958", "+442079460958"),
    ("+44 (20) 7946-0958", "+442079460958"),
    (" +1.202.555.0143 ", "+12025550143"),
    ("+12345678", "+12345678"),                         # 8 digits: the shortest
    ("+123456789012345", "+123456789012345"),           # 15: the longest E.164 allows
])
def test_phone_number_accepts(raw, stored):
    assert PhoneNumber(raw) == stored


@pytest.mark.parametrize("raw", ["020 7946 0958", "442079460958", "+0442079460958", "+1234567", "+1234567890123456", "+44 20 79x6", "++44207946"])
def test_phone_number_refuses(raw):
    with pytest.raises(ValueError, match = "country code"):
        PhoneNumber(raw)


# ── SecretStr ────────────────────────────────────────────────────────────────

def test_secret_str_is_masked_wherever_it_is_shown():
    token = SecretStr("hunter2")
    assert repr(token) == "SecretStr('**********')" and str(token) == "**********"
    assert f"{token}" == "**********" and f"[{token:>12}]" == "[  **********]" and "%s" % token == "**********"
    assert token.get_secret_value() == "hunter2" and type(token.get_secret_value()) is str


def test_secret_str_is_still_the_text():
    token = SecretStr("hunter2")
    assert token == "hunter2" and len(token) == 7 and token.encode() == b"hunter2" and token.upper() == "HUNTER2"
    assert pickle.loads(pickle.dumps(token)).get_secret_value() == "hunter2"   # str(self) is the mask: not pickled
    assert SecretStr(token) is token


def test_secret_str_stays_out_of_messages_and_reprs():
    @dataclass
    class Login:
        user: str
        password: SecretStr

    assert repr(Login("ana", "pw")).endswith("Login(user='ana', password=SecretStr('**********'))")

    @typecheck
    def count(n: int) -> int:
        return n
    message = _message(count, SecretStr("leaked?"))
    assert "leaked" not in message and "SecretStr('**********')" in message


# ── NonEmptyStr, AwareDatetime, Probability, Percentage ──────────────────────

def test_the_annotated_types():
    @typecheck
    def f(name: NonEmptyStr = "x", when: AwareDatetime = datetime(2026, 1, 1, tzinfo = timezone.utc),
          p: Probability = 0.5, pc: Percentage = 50.0) -> tuple:
        return name, when, p, pc
    assert f(" a ") == (" a ", datetime(2026, 1, 1, tzinfo = timezone.utc), 0.5, 50.0)    # kept as given
    assert f(p = 1, pc = 0) == ("x", datetime(2026, 1, 1, tzinfo = timezone.utc), 1.0, 0.0)
    assert type(f(p = 0)[2]) is float
    assert f(when = datetime(2026, 1, 1, tzinfo = timezone(timedelta(hours = 2))))[1].utcoffset() == timedelta(hours = 2)
    assert "must not be empty or only whitespace" in _message(f, " \t")
    assert "must not be empty" in _message(f, "")
    assert "must have a time zone" in _message(f, when = datetime(2026, 1, 1))
    for p in (-0.1, 1.01, float("nan")):
        assert "must be between 0 and 1" in _message(f, p = p)
    for pc in (-1, 100.5, float("inf")):
        assert "must be between 0 and 100" in _message(f, pc = pc)
