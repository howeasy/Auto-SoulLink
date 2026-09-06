"""Compare real hydrated rendering against the reviewed pre-extraction output."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.dashboard_scenarios import CLOCK, SCENARIOS, dashboard_scenario
from tests.html_contract import Document

GOLDENS = Path(__file__).resolve().parents[1] / "fixtures/ui/legacy_dashboard"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_dashboard_content_matches_legacy_markup(tmp_path, scenario):
    with patch("server.server.time.time", return_value=CLOCK):
        srv = dashboard_scenario(scenario, tmp_path / scenario)
        expected = Document((GOLDENS / f"{scenario}.html").read_text(encoding="utf-8")).by_id("content")
        actual = Document(srv._build_status_html()).by_id("content")
    wanted = expected.normalized()
    # The old pending-status helper escaped an already escaped trainer name.
    # Jinja now escapes the original text once. Preserve the archived bytes and
    # admit only this exact, reviewed text correction in the warnings scenario.
    def corrected(value):
        if isinstance(value, list):
            return [corrected(item) for item in value]
        if isinstance(value, dict) and value.get("id", "").startswith("calc-preview-"):
            # RR-U02 deliberately replaces raw IDs with adapter-resolved names.
            # All other attributes remain part of the equivalence comparison.
            return {key: item for key, item in value.items() if key != "data-player-moves"}
        if scenario == "warnings" and value == '&lt;Alice &amp; &quot;friend&quot;&gt;:':
            return '<Alice & "friend">:'
        return value
    assert corrected(actual.normalized()) == corrected(wanted)


def test_dashboard_context_is_detached_and_renders_without_runtime_access(tmp_path):
    import json

    from server.dashboard import render_dashboard

    srv = dashboard_scenario("gen3", tmp_path / "isolated")
    context = srv._build_dashboard_context()
    original = json.dumps(context)
    before = render_dashboard(context)
    srv.party_details.clear()
    srv.pc_boxes.clear()
    srv.state.links.clear()
    assert json.dumps(context) == original
    assert render_dashboard(context) == before
