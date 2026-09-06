"""Actual Lua post-native rival refresh over controlled RR battle/party RAM."""
import pytest

from tests.rr.runtime.rr_harness import RRHarness


@pytest.mark.parametrize("doubles", [False, True])
def test_rival_refresh_resets_all_seven_stages_without_writing_type3(rr_repo, doubles):
    h = RRHarness(rr_repo, party=(111, 444), load=False)
    size = int(h.M.BATTLE_MON_SIZE)
    party = int(h.M.PARTY_BASE + h.M.MON_SIZE)
    raw = bytes(h.u8(party + i) for i in range(100))
    for slot in range(2):
        h.seed(int(h.M.ENEMY_BASE + slot * h.M.MON_SIZE), raw)
    h.set_battle(True)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4 if doubles else 2)
    enemy_battlers = (1, 3) if doubles else (1,)
    for battler in enemy_battlers:
        h.seed_u16(h.M.BATTLER_PARTY_INDEXES_ADDR + battler * 2, battler // 2)
        base = int(h.M.BATTLE_MONS_ADDR + battler * size)
        # Distinct neighboring type byte and nonneutral EVA expose the old
        # one-byte-left reset, unlike a zero-filled or already-neutral record.
        h.seed_u8(base + 0x18, 17)
        h.seed(base + 0x19, bytes([0, 1, 2, 3, 4, 5, 12]))
    player_before = bytes(h.u8(int(h.M.BATTLE_MONS_ADDR) + i) for i in range(size))
    result = h.M.refreshEnemyPartyNative(2 if doubles else 1)
    assert result[1] == 25  # public post-native entry actually decoded the party
    for battler in enemy_battlers:
        base = int(h.M.BATTLE_MONS_ADDR + battler * size)
        assert [h.u8(base + 0x19 + i) for i in range(7)] == [6] * 7
        assert h.u8(base + 0x18) == 17
    assert bytes(h.u8(int(h.M.BATTLE_MONS_ADDR) + i) for i in range(size)) == player_before
