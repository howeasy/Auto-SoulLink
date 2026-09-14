"""The Manager dashboard's Resume control (CARD UI-1).

`POST /api/runs/gen1` already supports `resume_from` (server/manager.py
handle_create_gen1, tests/integration/test_manager_gen1_resume.py) but the
dashboard has no way to trigger it. Alpine's x-if/x-show run client-side, so
the Jinja-rendered HTML always contains the markup for every branch — there
is no server-side render-diff to assert "only shown for a stopped run" the
way a Jinja {% if %} would give us. What we CAN pin, without a JS engine:

  * the x-if/x-show guard expressions gating the Resume control and the two
    lineage lines are exactly the conditions the feature needs (stopped +
    !resumed_by; current.resume; current.resumed_by)
  * the Start button's :disabled is wired to resumed_by
  * the launcher hint uses the exact flag tools/launch_bizhawk.py defines
  * the JS request-body builder emits exactly the keys handle_create_gen1
    requires

This is the "say so and test string presence" fallback the CARD calls for.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


@pytest.fixture(scope="module")
def html():
    with open(os.path.join(_REPO, "server", "templates", "manager.html"), encoding="utf-8") as f:
        return f.read()


def test_resume_control_is_gated_to_stopped_and_unresumed(html):
    """The Resume trigger must only ever be live for a stopped run with no successor."""
    m = re.search(r'x-if="current\s*&&\s*current\.status\s*===\s*\'stopped\'\s*&&\s*!current\.resumed_by"', html)
    assert m, "Resume control is not gated on (stopped && !resumed_by)"


def test_resumed_from_lineage_is_gated_on_resume_field(html):
    m = re.search(r'x-if="current(\?\.|\s*&&\s*current\.)resume"', html)
    assert m, "no lineage block gated on current.resume"
    tail = html[m.end():m.end() + 400]
    assert "resumed from" in tail and "current.resume.from_run" in tail


def test_resumed_by_lineage_is_gated_on_resumed_by_field(html):
    m = re.search(r'x-if="current(\?\.|\s*&&\s*current\.)resumed_by"', html)
    assert m, "no lineage block gated on current.resumed_by"
    tail = html[m.end():m.end() + 400]
    assert "resumed by" in tail and "current.resumed_by" in tail


def test_start_button_is_disabled_once_resumed(html):
    """The server refuses /start on a run with resumed_by (manager.py:727) — the
    button must not invite a click that only produces an alert()."""
    m = re.search(r'mgr-btn-start"[^>]*?/?>|mgr-btn-start"[\s\S]*?</button>', html)
    assert m, "Start button markup not found"
    start_block = m.group(0)
    assert ':disabled' in start_block and 'resumed_by' in start_block, (
        "Start button has no :disabled binding on resumed_by")


def test_launcher_hint_uses_the_exact_resume_save_flag(html):
    assert "--resume-save" in html, "launcher hint must name the actual CLI flag"


def test_resume_request_body_has_exactly_the_keys_handle_create_gen1_requires(html):
    """handle_create_gen1 requires name, rom_a, rom_b and accepts rules/start/native/resume_from
    (server/manager.py ~line 871). Pin the JS payload builder to those keys."""
    m = re.search(r'resumeRequestBody\s*\([^)]*\)\s*\{([\s\S]*?)\n\s*\},', html)
    assert m, "no resumeRequestBody(...) function found in the inline script"
    body = m.group(1)
    for key in ("name", "rom_a", "rom_b", "rules", "native", "start", "resume_from"):
        assert re.search(key + r'\s*:', body), f"resumeRequestBody is missing the '{key}' key"
    assert re.search(r'start\s*:\s*false', body), "a resume must not auto-start (matches the CARD's payload)"


def test_resume_rule_options_only_uses_server_allowed_keys(html):
    """server/gen1_run_config.py's create_runtime rejects any rule_options key outside this
    set (JournalError) -- sending the other registry settings (overworld_presence,
    native_messages, battle_calc) would 400 the resume."""
    m = re.search(r'resumeRuleOptions\s*\([^)]*\)\s*\{([\s\S]*?)\n\s*\},', html)
    assert m, "no resumeRuleOptions(...) helper found"
    # Strip // line comments before checking keys -- a key named only in a comment
    # (e.g. explaining what's excluded) must not satisfy either assertion below.
    body = re.sub(r'//[^\n]*', '', m.group(1))
    allowed = {"species_lock", "gender_lock", "type_lock", "explode_mode",
               "rival_team_swap", "native_sounds", "pc_trade_npc"}
    disallowed = {"overworld_presence", "native_messages", "battle_calc"}
    for key in allowed:
        assert key in body, f"resumeRuleOptions should carry forward {key}"
    for key in disallowed:
        assert key not in body, f"resumeRuleOptions must not send server-rejected key {key}"
