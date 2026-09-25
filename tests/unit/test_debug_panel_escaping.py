"""The debug panel builds markup with innerHTML from /api/status and raw state, where
nicknames, trainer names, area ids and errors come from the game clients. Every such
value must go through the panel's esc() helper."""
from __future__ import annotations

import os
import re

import pytest

PANEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "server", "templates", "_debug_panel.html")

# Values that come from the server status or raw state (or locals built from them).
FIELDS = re.compile(
    r"\b(trainer_name|ot_id|nickname|species_name|species|area_id|area_display|pending_area|"
    r"error|cause|modified|label|identErr|disp|aid|aDisp|bDisp|aLbl|bLbl|lbl|statusLabel|"
    r"info\.d|keys\[k\]|pids|st|slot|key|k)(?!\w)")
# Lines that assemble markup for innerHTML.
ASSEMBLY = re.compile(r"\b(h|kh|ah)\s*\+?=|innerHTML\s*=|return\s*'<")
STRING = re.compile(r"'(?:\\.|[^'\\])*'")
SAFE_CALL = re.compile(r"\b(esc|Number)\(")   # escaped, or coerced to a number


def _script():
    with open(PANEL, encoding="utf-8") as f:
        src = f.read()
    return src[src.index("<script>"):]


def _strip_esc_calls(line):
    """Remove every esc(...) / Number(...) call, balanced parens included."""
    while match := SAFE_CALL.search(line):
        start = match.start()
        depth, i = 0, match.end() - 1
        while i < len(line):
            depth += {"(": 1, ")": -1}.get(line[i], 0)
            if depth == 0:
                break
            i += 1
        line = line[:start] + line[i + 1:]
    return line


def _unescaped_fields(script):
    bad = []
    for n, line in enumerate(script.splitlines(), 1):
        if not ASSEMBLY.search(line):
            continue
        code = STRING.sub("''", _strip_esc_calls(line))
        # Only operands of a string concatenation reach the markup.
        operands = (re.findall(r"(?:^|[^+=])\+\s*\(?\s*([\w.\[\]]+)", code)
                    + re.findall(r"([\w.\[\]]+)\s*\)?\s*\+(?![+=])", code))
        bad += [(n, op, line.strip()) for op in operands if FIELDS.search(op)]
    return bad


def test_esc_helper_exists_and_escapes_attribute_quotes():
    body = re.search(r"function esc\(s\) \{(.*?)\n\}", _script(), re.S)
    assert body, "the panel lost its esc() helper"
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in body.group(1)


def test_no_state_field_reaches_innerhtml_unescaped():
    assert _unescaped_fields(_script()) == []


@pytest.mark.parametrize("unsafe", [
    "h += '<td>' + (entry.area_id || '?') + '</td>';",
    "h += '&nbsp;&nbsp;A: ' + identErr.a + '<br>';",
    "document.getElementById('ml-warn').innerHTML = '\\u26a0 ' + j.error;",
    "h += '<button data-area-id=\"'+lnk.area_id+'\">x</button>';",
    "kh += '<option value=\"' + k + '\">' + keys[k] + '</option>';",
])
def test_the_scan_catches_an_unwrapped_sink(unsafe):
    """Known-positive control: the scan must flag the sinks it exists to catch."""
    assert _unescaped_fields("<script>\n" + unsafe)
