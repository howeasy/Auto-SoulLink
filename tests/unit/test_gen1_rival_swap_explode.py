"""Rival Team Swap and Explode Mode on Gen 1 are opted into by the ADAPTER, not by a patch.

Gen 3 needed the native companion patch for the rival swap because `gEnemyParty` is
encrypted and checksummed. Gen 1 has no encryption, no checksums and no ASLR: the enemy
party is a plaintext block at a fixed address, so the swap is a byte copy and Explosion is
a move-id write. Both features are therefore enabled by two adapter overrides and some Lua,
with no patched ROM anywhere in the picture. The two overrides are what this file pins: get
`rival_trainer_ids()` wrong and the server sends `replace_rival_team` for the wrong battle,
or for none.

P8-2b: the Lua half moved to lua/gen1/writes.lua and is proved against the Python codec by
tests/unit/test_gen1_writes.py (`test_enemy_party_is_validated_completely_before_any_byte_lands`
for the count/species-list/terminator/stride/OT/nickname layout and the all-or-nothing
validation, `test_explode_fills_all_four_slots_in_both_structs` for Explode Mode, and
`test_active_battler_faint_needs_the_loop_head_and_hits_both_structs` for the battle-loop-head
requirement that replaced the old "not in battle" refusal).
"""
from server.adapters import get_adapter


def test_adapter_opts_into_both_features():
    a = get_adapter("gen1_rby", rom_type="Red")
    assert a.supports_explode_mode() is True
    # RIVAL1/2/3 = $19/$2A/$2B + OPP_ID_OFFSET(200).
    assert a.rival_trainer_ids() == {225, 242, 243}


def test_non_rival_trainers_do_not_trigger_a_swap():
    a = get_adapter("gen1_rby", rom_type="Red")
    for tid in (201, 234, 247):     # Youngster, Brock, Lance
        assert tid not in a.rival_trainer_ids()
