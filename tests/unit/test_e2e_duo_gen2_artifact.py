"""Executed artifact selection for all Gen 2 duo cells, without an emulator."""

from types import SimpleNamespace

import pytest

from tools import e2e_duo as duo


def test_every_gen2_scenario_can_explicitly_select_overlay():
    args = SimpleNamespace(gen2_artifact="overlay")
    assert duo.gen2_selected_artifact(args, "gen2_pc_ops") == "overlay"
    assert duo.gen2_selected_artifact(args, "link") == "overlay"


def test_native_trade_never_falls_back_to_clean():
    with pytest.raises(ValueError, match="trade requires overlay"):
        duo.gen2_selected_artifact(SimpleNamespace(gen2_artifact="clean"), "gen2_trade_new")


def test_legacy_default_is_clean_for_gameplay_and_overlay_for_native_trade(monkeypatch):
    monkeypatch.delenv("SLINK_GEN2_ARTIFACT", raising=False)
    assert duo.gen2_selected_artifact(SimpleNamespace(), "link") == "clean"
    assert duo.gen2_selected_artifact(SimpleNamespace(), "gen2_trade_new") == "overlay"
