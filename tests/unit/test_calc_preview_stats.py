"""_calc_preview's real stat inputs (server/server.py _calc_preview).

Before this, the preview built the player with a hard-coded 'Hardy' nature and no IVs/EVs/DVs,
and the enemy with a fake max(maxHP, 1) that forced an unknown foe to 100% HP. Both are now
sourced from the same calc_stats /api/calc/mons already builds (base.GameRulesAdapter.calc_stats
contract) -- see handle_calc_mons's own adapter.calc_stats(detail) call for the enemy side this
mirrors.
"""
from __future__ import annotations

from server.adapters.gen1_rby import Gen1Adapter
from server.server import SLinkServer

_PLAYER_CALC_STATS = {
    "dvs": {"atk": 9, "def": 8, "spe": 7, "spc": 6},
    "stat_exp": {"hp": 65535, "atk": 10000, "def": 0, "spe": 5000, "spc": 2500},
    "stats": {"hp": 100, "atk": 50, "def": 45, "spa": 40, "spd": 40, "spe": 42},
}


def _server(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._player_adapters["b"] = Gen1Adapter(rom_type="red")
    srv.party_details["b"] = {
        "p1": {
            "level": 50, "hp": 100, "maxHP": 100, "nickname": "", "species_id": 1,
            "held_item_id": 0, "ability_id": 0, "moves": ["Tackle"], "pp": [4],
            "slot": 0, "active": True, "status_cond": 0, "stat_stages": None,
            "calc_stats": _PLAYER_CALC_STATS,
        },
    }
    return srv


def test_calc_preview_carries_player_calc_stats_and_no_nature(tmp_path):
    srv = _server(tmp_path)
    foe = {"species_id": 4, "level": 12, "hp": 30, "dvs_raw": 0x9C4A}  # no maxHP: unknown
    c = srv._calc_preview("b", [foe])

    assert c["player_calc_stats"] == _PLAYER_CALC_STATS
    assert c["player_nature"] is None  # Gen 1 has no PV-derived nature
    assert c["player_ability"] == ""  # Gen 1 has no abilities


def test_calc_preview_enemy_calc_stats_from_dvs_raw_and_hp_pct_none_when_maxhp_unknown(tmp_path):
    srv = _server(tmp_path)
    foe = {"species_id": 4, "level": 12, "hp": 30, "dvs_raw": 0x9C4A}
    c = srv._calc_preview("b", [foe])

    adapter = srv.adapter_for("b")
    assert c["enemy_calc_stats"] == adapter.calc_stats(foe) == {
        "dvs": {"atk": 9, "def": 12, "spe": 4, "spc": 10},
        "stat_exp": {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0},
    }
    assert c["enemy_hp_pct"] is None


def test_calc_preview_enemy_hp_pct_present_when_maxhp_known(tmp_path):
    srv = _server(tmp_path)
    foe = {"species_id": 4, "level": 12, "hp": 30, "maxHP": 40, "dvs_raw": 0}
    c = srv._calc_preview("b", [foe])

    assert c["enemy_hp_pct"] == 75
    assert c["enemy_calc_stats"] == {
        "dvs": {"atk": 0, "def": 0, "spe": 0, "spc": 0},
        "stat_exp": {"hp": 0, "atk": 0, "def": 0, "spe": 0, "spc": 0},
    }
