import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest


@pytest.fixture(autouse = True)
def plain_messages(monkeypatch):
    """
    Messages are compared as text in these tests, so they are rendered without colours, whatever
    the shell exports (``FORCE_COLOR=1`` used to fail the tests that match on a whole message).
    A test that is about colours switches them back on (see test_formatter.py).
    """
    monkeypatch.setenv("ENFORCED_COLOURS_OFF", "1")
