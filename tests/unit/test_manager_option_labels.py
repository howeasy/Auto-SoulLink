"""Setup labels explain per-game support without making live readiness claims."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from server.board import FAMILIES, OPTION_LABELS
from server.manager_board import shell_context
from tests.html_contract import Document, Element


def text(node):
    return "".join(text(item) if isinstance(item, Element) else item for item in node.content)


@pytest.fixture(scope="module")
def labels():
    env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[2] / "server/templates"), autoescape=select_autoescape())
    page = env.get_template("manager.html").render(**shell_context(), theme="default", families=FAMILIES, option_labels=OPTION_LABELS, runs=[])
    dom = Document(page)
    return {node.attrs["name"]: text(node.closest("label")) for node in dom.root.descendants("input") if node.attrs.get("type") == "checkbox"}


@pytest.mark.parametrize("feature", ["explode_mode", "rival_team_swap"])
def test_gen1_feature_labels_do_not_claim_a_companion_patch_is_required(labels, feature):
    assert "Gen 1 does not need a companion patch" in labels[feature]
    assert "where the connected game supports it" in labels[feature]


@pytest.mark.parametrize("feature", ["overworld_presence", "native_messages", "native_sounds", "pc_trade_npc"])
def test_feature_support_is_checked_against_the_connected_cartridge(labels, feature):
    assert "support" in labels[feature]
    assert "Gen 3 only" not in labels[feature]


def test_gender_clause_explains_missing_gen1_gender_data(labels):
    assert "Gen 1 has no gender data" in labels["gender_lock"]
