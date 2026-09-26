"""Regressions for OMP review cx-2985fe38 (F1-F5).

F1: /api/reset (and rollback) must re-resolve the adapter from the FULL rom_type on the
next hello, not just game_id/is_rr -- a same-generation variant swap (Red -> reset ->
Yellow, or the reverse) used to keep the stale adapter, whose panel/trade capabilities
are bound to the wrong variant (`Gen1Adapter.supports_info_panel`/`native_trade_ui`,
server/adapters/gen1_rby.py).

F2: hello handling must be transactional. The candidate rom_type, panel/panel_abi/sfx
capabilities and adapter are staged, and committed only once contract admission
(`_decide_admission`) and save-identity acceptance (`state.handle_event`) both accept the
hello. A refusal at either stage must restore `connected_players` and `self.adapter`
exactly (docs/protocol.md §2.2 steps 1/1': "rejected ⇒ state untouched").

F3: `handle_debug_rollback` must clear `connected_players` and the derived
party/box/battle/display caches through the same helper `/api/reset` uses.

F5: `_bind_player_adapter` must pass the run's committed `artifact_kind`, and the ordering
on the first hello (which both binds a per-player adapter and commits the run's kind) must
not leave that adapter stuck at the constructor default.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock

from server.server import SLinkServer


def _hello(player: str, rom_type: str, *, ot_id: str = "30B8", **extra) -> dict:
    return {"event": "hello", "player": player, "rom_type": rom_type,
            "trainer_name": player.upper(), "ot_id": ot_id, "party": [], **extra}


# ── F1 ──────────────────────────────────────────────────────────────────────────────────

def test_reset_then_yellow_hello_gets_a_yellow_adapter_not_a_stale_red_one(tmp_path):
    s = SLinkServer(data_dir=str(tmp_path))
    s._dispatch("a", _hello("a", "Red"))
    assert s.state.rom_type == "Red"
    assert s.adapter.native_trade_ui() is True     # Red/Blue-only companion capability
    assert s.adapter.supports_info_panel() is True

    asyncio.run(s.handle_reset_api(None))
    assert not s.state.rom_type, "reset must clear the committed variant lock"

    s._dispatch("a", _hello("a", "Yellow"))
    assert s.state.rom_type == "Yellow"
    assert s.adapter.native_trade_ui() is False, "kept the stale Red adapter's trade capability"
    assert s.adapter.supports_info_panel() is False, "kept the stale Red adapter's panel capability"


def test_reset_then_red_hello_after_yellow_gets_a_red_adapter(tmp_path):
    s = SLinkServer(data_dir=str(tmp_path))
    s._dispatch("a", _hello("a", "Yellow"))
    assert s.adapter.native_trade_ui() is False

    asyncio.run(s.handle_reset_api(None))
    s._dispatch("a", _hello("a", "Red"))
    assert s.state.rom_type == "Red"
    assert s.adapter.native_trade_ui() is True, "kept the stale Yellow adapter's trade capability"
    assert s.adapter.supports_info_panel() is True


# ── F2 ──────────────────────────────────────────────────────────────────────────────────

def test_wrong_save_hello_preserves_the_prior_rom_type_panel_and_sfx(tmp_path):
    """Codex cx-2985fe38 F2 identity sequence: a wrong-OT hello that also claims NEW
    capabilities must not leave connected_players or the adapter describing the rejected
    cartridge."""
    s = SLinkServer(data_dir=str(tmp_path))
    s._dispatch("a", _hello("a", "Red", ot_id="30B8", panel=False, sfx=False))
    assert s.state.rom_type == "Red"
    before_conn = dict(s.connected_players["a"])
    before_adapter = s.adapter

    s._dispatch("a", _hello("a", "Blue", ot_id="WRONG", panel=True, sfx=True))
    assert s.state.identity_error.get("a"), "expected an identity (wrong save) rejection"
    assert s.connected_players["a"] == before_conn, \
        "rom_type/panel/sfx leaked from a rejected hello"
    assert s.adapter is before_adapter
    assert s.state.rom_type == "Red"


def test_a_hello_that_raises_mid_decision_rolls_back_the_staged_cartridge(tmp_path):
    """Review of 8418c931 (P3): an exception between staging and the accept/reject decision
    must not leave the candidate cartridge's adapter/capabilities applied."""
    import pytest
    s = SLinkServer(data_dir=str(tmp_path))
    before_conn = dict(s.connected_players.get("a", {}))
    before_adapter = s.adapter

    def boom(*_a, **_k):
        raise RuntimeError("boom")
    s.state.handle_event = boom
    with pytest.raises(RuntimeError):
        s._dispatch("a", _hello("a", "Yellow", panel=True, sfx=True))
    assert s.adapter is before_adapter and s.state.adapter is before_adapter
    assert dict(s.connected_players.get("a", {})) == before_conn


def test_contract_rejected_hello_leaves_connected_players_and_adapter_untouched(tmp_path):
    """Codex cx-2985fe38 F2 contract sequence: a fresh contracted run refuses a hello with
    no rom_content, and must leave connected_players/self.adapter/state.rom_type exactly as
    they were -- not switched to the refused cartridge's game first."""
    contract = {"upr_version": "1", "settings_sha256": "0" * 64, "categories": ["wild"],
                "players": {"a": {"fingerprint": "f" * 64, "rom_sha1": "a" * 40}}}
    with open(os.path.join(str(tmp_path), "rom_contract.json"), "w") as f:
        json.dump(contract, f)
    s = SLinkServer(data_dir=str(tmp_path))
    before_conn = dict(s.connected_players.get("a", {}))
    before_adapter = s.adapter
    before_rom_type = s.state.rom_type

    cmds = s._dispatch("a", _hello("a", "Red"))
    assert cmds == [{"cmd": "noop", "refused": "admission"}]
    assert s.admission["a"]["state"] == "rejected"
    assert s.connected_players.get("a", {}) == before_conn
    assert s.adapter is before_adapter, "the run's adapter was switched by a refused hello"
    assert s.state.rom_type == before_rom_type


def test_an_accepted_hello_after_a_rejection_still_commits_normally(tmp_path):
    """Control: the staging/rollback machinery must not swallow a GOOD hello."""
    contract = {"upr_version": "1", "settings_sha256": "0" * 64, "categories": ["wild"],
                "players": {"a": {"fingerprint": "f" * 64, "rom_sha1": "a" * 40}}}
    with open(os.path.join(str(tmp_path), "rom_contract.json"), "w") as f:
        json.dump(contract, f)
    s = SLinkServer(data_dir=str(tmp_path))
    s._dispatch("a", _hello("a", "Red"))
    assert s.admission["a"]["state"] == "rejected"

    s._rom_contract = None  # simplest way to make the next hello admissible
    s._dispatch("a", _hello("a", "Red", panel=True, sfx=True))
    assert s.state.rom_type == "Red"
    assert s.connected_players["a"]["panel"] is True
    assert s.connected_players["a"]["sfx"] is True


# ── F3 ──────────────────────────────────────────────────────────────────────────────────

def test_rollback_clears_connection_and_display_caches_like_reset(tmp_path):
    s = SLinkServer(data_dir=str(tmp_path))
    s._dispatch("a", _hello("a", "Red", panel=True, sfx=True,
                            party=[{"key": "DEAD:BEEF:01", "species_id": 1, "level": 5,
                                    "hp": 10, "maxHP": 10}]))
    s.pc_boxes["a"] = [{"key": "DEAD:BEEF:02", "species_id": 4, "level": 5}]
    s.battle_state["a"]["in_battle"] = True
    s.battle_state["a"]["enemy_party"] = [{"species_id": 7, "level": 5}]
    s.player_area["a"] = "Route 1"
    assert s.connected_players["a"].get("panel") is True
    assert s.party_details["a"]

    s.state._save()
    backup = Path(s.state._links_path).parent / "backups" / "links.backup.1.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    copyfile(s.state._links_path, backup)
    response = asyncio.run(s.handle_debug_rollback(
        AsyncMock(json=AsyncMock(return_value={"slot": 1}))))
    assert response.status == 200

    assert s.connected_players == {}, "rollback left a stale connection record"
    assert s.party_details == {"a": {}, "b": {}}
    assert s.pc_boxes == {"a": [], "b": []}
    assert s.battle_state["a"]["in_battle"] is False
    assert s.battle_state["a"]["enemy_party"] == []
    assert s.player_area == {"a": "", "b": ""}


# ── F5 ──────────────────────────────────────────────────────────────────────────────────

def test_bind_player_adapter_gets_the_committed_artifact_kind_on_the_very_first_hello(tmp_path):
    """Codex cx-2985fe38 F5: the FIRST hello of the run both commits `state.artifact_kind`
    and binds the partner's per-player adapter (`_bind_player_adapter`). If the bind runs
    before the commit, the partner's adapter is stuck at the constructor default ("clean")
    forever, even though the run is committed to "overlay"."""
    s = SLinkServer(data_dir=str(tmp_path))
    # Gold hellos FIRST: this is the hello that both establishes the run's own adapter AND
    # commits state.artifact_kind.
    s._dispatch("a", _hello("a", "Gold", artifact_kind="overlay"))
    assert s.state.artifact_kind == "overlay"
    # Crystal hellos second and does NOT match the run's own key, so it gets its own
    # per-player-bound adapter -- built (F5) AFTER the kind above was already committed.
    s._dispatch("b", _hello("b", "Crystal", ot_id="7B0B", artifact_kind="overlay"))

    partner = s.adapter_for("b")
    assert partner is not s.state.adapter, "expected Crystal to be a distinct per-player adapter"
    assert partner.supports_info_panel() is True, \
        "the partner's adapter was bound at the default kind, not the committed overlay kind"
    assert partner.native_trade_ui() is True
