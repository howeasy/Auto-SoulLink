"""The manager's inline run JSON must be inert as markup.

`manager.html` does `window.SLINK_FORM = {{ form_json | safe }}` inside a <script>
element. `json.dumps` escapes quotes and backslashes but NOT `<`, so a run whose name
contained `</script>` closed the element and everything after it was parsed as markup --
stored XSS, reachable through the API that creates runs, not just by typing it into the
local UI.

The repo had no XSS coverage of any kind before this file.
"""
from __future__ import annotations

import json

import pytest

from server.manager import _json_for_script

PAYLOADS = [
    "</script><img src=x onerror=alert(1)>",
    "</SCRIPT ><svg onload=alert(1)>",
    "<!--<script>",
    "\u2028\u2029 line separators",
    "already \u003c escaped",
    "quotes \" and ' and backslash \\",
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_no_payload_can_close_the_script_element(payload):
    out = _json_for_script({"name": payload, "run_id": "r1"})
    assert "<" not in out and ">" not in out, f"raw angle bracket survived: {out}"


@pytest.mark.parametrize("payload", PAYLOADS)
def test_the_value_survives_the_round_trip_unchanged(payload):
    """The load-bearing control. Escaping that corrupts the data would 'pass' the
    test above while breaking every run name in the UI."""
    out = _json_for_script({"name": payload})
    assert json.loads(out)["name"] == payload


def test_ampersand_is_escaped_too():
    """Not strictly needed to close a script element, but it is what turns an
    escaped payload back into markup if the string is ever re-parsed as HTML."""
    assert "&" not in _json_for_script({"n": "a&b"})


def test_ordinary_names_are_still_readable_json():
    out = _json_for_script({"name": "Red vs Blue", "run_id": "abc"})
    assert json.loads(out) == {"name": "Red vs Blue", "run_id": "abc"}


def test_the_template_still_marks_it_safe():
    """This escaping is only load-bearing because the template bypasses autoescaping.
    If someone removes `| safe`, the double-escaping would show as literal \u003c on
    screen -- a visible bug, not a silent one -- so this pins the coupling."""
    import os
    repo = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    with open(os.path.join(repo, "server", "templates", "manager.html"), encoding="utf-8") as f:
        src = f.read()
    assert "form_json | safe" in src, (
        "manager.html no longer injects form_json with | safe — _json_for_script's "
        "escaping may now be double-applied")
