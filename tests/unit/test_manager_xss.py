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
import re
from html.parser import HTMLParser

import pytest

from server import manager
from server.manager import _json_for_script

pytest_plugins = ["tests.unit.manager_harness"]

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


# -- The run name inside the Archive/Delete @click handlers ---------------------------------
# `{{ run.name | e }}` inside a JS string is HTML-decoded before Alpine evaluates it, so a
# quote in the name closed the string. The name now arrives as a JSON literal.

class _Clicks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.clicks = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "@click" and value and value.startswith("act('") and "run '" in value:
                self.clicks.append(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["x');alert(1);//", 'a" onmouseover="alert(1)', "back\\slash </b>"])
async def test_run_name_is_a_json_literal_in_the_action_buttons(manager_client, name):
    manager._save_registry([{"run_id": "r1", "name": name, "created_at": "2026-09-24T12:00:00",
                             "tcp_port": 54321, "http_port": 8081, "status": "stopped",
                             "pid": None, "game": "gen1"}])
    resp = await manager_client.get("/runs/r1")
    assert resp.status == 200
    assert resp.headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    parser = _Clicks()
    parser.feed(await resp.text())
    assert len(parser.clicks) == 2, parser.clicks          # Archive + Delete, attribute intact
    for click in parser.clicks:
        literal = re.fullmatch(r"act\('(archive|delete)', '\w+ run ' \+ (\".*\") \+ '[^']*'\)", click)
        assert literal, click
        assert json.loads(literal.group(2)) == name


@pytest.mark.asyncio
async def test_new_run_name_is_capped(manager_client):
    resp = await manager_client.post("/api/runs/new", json={"name": "n" * 81})
    assert resp.status == 400
    assert "too long" in (await resp.json())["error"]
