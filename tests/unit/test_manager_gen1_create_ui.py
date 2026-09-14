"""The Manager Create form's Gen 1 branch (structural checks; runtime dispatch is covered by the handler test).

`createRun()` used to POST `/api/runs/new` for every create, so no human could
start a selected Gen 1 runtime from the dashboard — only `POST /api/runs/gen1`
(server/manager.py handle_create_gen1) prepares one. The form now takes two
optional cartridge paths: both empty keeps the generic run, both filled creates
the Gen 1 run, and one filled is refused before any request.

Alpine runs client-side, so the Jinja-rendered HTML always contains every
branch. Without a JS engine what we CAN pin is the markup and the exact request
the function builds:

  * the three Gen 1 inputs exist with their ids and x-model bindings, and the
    error line is bound to `gen1Create.error`
  * `createRun()` emits `/api/runs/gen1` with `native: true`, `start: true` and
    the both-or-neither refusal text
  * its rule keys are exactly the six `create_runtime` accepts for Gen 1, with
    `native_sounds` forced off — the other newOpts keys would 400 the request
  * `/api/runs/new` survives as the generic fallback, and the error line sits
    outside the closed disclosure so a generic-run refusal is visible

Runtime dispatch (that this body really creates a run) is covered by
tests/unit/test_manager_prepared_gen1.py, which posts it to the handler.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

_GEN1_RULE_KEYS = {"species_lock", "gender_lock", "type_lock", "explode_mode", "rival_team_swap", "pc_trade_npc"}


@pytest.fixture(scope="module")
def html():
    with open(os.path.join(_REPO, "server", "templates", "manager.html"), encoding="utf-8") as f:
        return f.read()


def _script(html):
    """Every inline <script> body joined, with // and /* */ comments stripped.

    manager.html opens with a small bootstrap block (window.SLINK_RUNS), so the
    dashboard script is not the first <script> in the file.
    """
    blocks = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert blocks, "no inline <script> block in manager.html"
    body = re.sub(r"/\*[\s\S]*?\*/", "", "\n".join(blocks))
    return re.sub(r"//[^\n]*", "", body)


def _create_run_body(html):
    match = re.search(r"async createRun\(\)\s*\{([\s\S]*?)\n\s*\},", _script(html))
    assert match, "no createRun() function found in the inline script"
    return match.group(1)


def test_the_gen1_create_inputs_are_bound_to_their_state(html):
    for identifier, binding in (("gen1-create-rom-a", "gen1Create.rom_a"),
                                ("gen1-create-rom-b", "gen1Create.rom_b"),
                                ("gen1-create-fastest-text", "gen1Create.fastest_text")):
        match = re.search(r'<input[^>]*id="' + re.escape(identifier) + r'"[^>]*>', html)
        assert match, f"the Gen 1 create form has no input id={identifier}"
        assert f'x-model="{binding}"' in match.group(0), f"{identifier} is not bound to {binding}"
    assert re.search(r'<p class="mgr-rand-error" x-show="gen1Create\.error" x-text="gen1Create\.error"></p>', html), \
        "the Gen 1 create form has no error line bound to gen1Create.error"


def test_create_run_posts_the_gen1_handler_with_both_or_neither(html):
    body = _create_run_body(html)
    assert "'/api/runs/gen1'" in body or '"/api/runs/gen1"' in body, "createRun never targets the Gen 1 handler"
    assert re.search(r"native\s*:\s*true", body), "the Gen 1 body must select native (the prepared pair)"
    assert re.search(r"start\s*:\s*true", body), "the Gen 1 body must start the run"
    assert "Both cartridge paths are required" in body, "one filled path is not refused before the request"


def test_create_run_sends_only_the_gen1_rule_keys(html):
    body = _create_run_body(html)
    match = re.search(r"\[(\s*'[^\]]*?)\]\.forEach", body)
    assert match, "the rules dict is not built from an explicit key list"
    keys = set(re.findall(r"'([^']+)'", match.group(1)))
    assert keys == _GEN1_RULE_KEYS, f"Gen 1 rule keys differ from create_runtime's allowed set: {sorted(keys)}"
    assert re.search(r"rules\.native_sounds\s*=\s*false", body), "native_sounds must be forced off for Gen 1"
    for rejected in ("overworld_presence", "native_messages", "battle_calc"):
        assert rejected not in body, f"createRun must not send the server-rejected key {rejected}"


def test_the_generic_path_survives(html):
    body = _create_run_body(html)
    assert "'/api/runs/new'" in body or '"/api/runs/new"' in body, "the generic run fallback is gone"


def test_the_create_error_line_is_visible_outside_the_disclosure(html):
    """A "Enter a run name" refusal on the generic path must not hide inside a closed <details>."""
    match = re.search(r'<button class="mgr-create-btn"[\s\S]*?</button>([\s\S]{0,200})', html)
    assert match, "Create button markup not found"
    assert re.search(r'<p class="mgr-rand-error" x-show="gen1Create\.error" x-text="gen1Create\.error"></p>', match.group(1)), \
        "the create error line is not directly below the Create button"
