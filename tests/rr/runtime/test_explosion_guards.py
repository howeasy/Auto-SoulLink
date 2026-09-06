"""Explosion target ownership using the unchanged production client and memory helpers."""

import pytest

from .rr_harness import RRHarness


def battle(repo):
    h = RRHarness(repo, party=(111, 333, 555))
    h.step()
    h.set_battle(True)
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, 0x08014041)
    h.seed_u32(h.M.BATTLE_STRUCT_PTR_ADDR, 0x02018000)
    h.step()
    return h


def end_battle(h):
    h.set_battle(False)
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, h.M.RETURN_FROM_BATTLE_ADDR)


def moves(h, battler=0):
    base = h.M.BATTLE_MONS_ADDR + battler * h.M.BATTLE_MON_SIZE
    return h.bytes(base + h.M.BATTLE_MON_MOVES_OFF, 8)


def test_incoming_slot_index_does_not_authorize_exploding_outgoing_identity(rr_repo):
    h = battle(rr_repo)
    # Authentic switch boundary: index now names incoming333; BattlePokemon is
    # still outgoing111. Read-only projections already handle this boundary.
    h.seed_u16(h.M.BATTLER_PARTY_INDEXES_ADDR, 1)
    before = moves(h)
    h.command("force_explode", key=h.key(333))
    h.step()
    assert moves(h) == before
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    # The obligation is retained and executes only once the same slot AND raw
    # battler identity agree. No private state access is used to assert this.
    h.set_battler(1, 333)
    h.step()
    assert moves(h) == (153).to_bytes(2, "little") * 4


def test_armed_explosion_does_not_faint_replacement_in_stale_party_slot(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.set_mon(0, 333)
    h.set_mon(1, 111)
    h.set_battler(1, 111)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50


def test_duplicate_explode_command_does_not_reset_committed_pp(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u8(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_PP_OFF, 4)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 4)
    h.command("force_explode", key=h.key(111))
    h.step()
    assert h.u8(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_PP_OFF) == 4
    assert h.u8(h.M.BATTLE_COMM_ADDR) == 4


def test_borrowed_party_ownership_blocks_command_even_if_key_matches(rr_repo):
    h = battle(rr_repo)
    h.seed_u8(h.MB.SW, 1)
    h.seed_u8(h.MB.SW + 1, 1)
    h.seed_u32(h.MB.SW + 4, 111)
    before = moves(h)
    h.command("force_explode", key=h.key(111))
    h.step()
    assert moves(h) == before


def test_doubles_battler_move_does_not_reinforce_original_battler(rr_repo):
    h = battle(rr_repo)
    h.set_battler(1, 333, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.set_battler(1, 333, battler=0)
    h.set_battler(0, 111, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    h.seed_u8(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_PP_OFF, 5)
    h.seed_u16(h.M.CHOSEN_MOVE_ADDR, 33)
    h.step()
    assert h.u16(h.M.CHOSEN_MOVE_ADDR) == 33
    assert h.u8(h.M.BATTLE_COMM_ADDR) == 0


@pytest.mark.parametrize("battler,slot,pid", [(0, 0, 111), (2, 1, 333)])
def test_owned_battler_preserves_the_existing_menu_skip_write_contract(rr_repo, battler, slot, pid):
    h = battle(rr_repo)
    if battler == 2:
        h.set_battler(slot, pid, battler=2)
        h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    party_before = h.bytes(h.M.PARTY_BASE, 300)
    foe_before = h.bytes(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_SIZE, h.M.BATTLE_MON_SIZE)
    h.command("force_explode", key=h.key(pid))
    h.step()
    base = h.M.BATTLE_MONS_ADDR + battler * h.M.BATTLE_MON_SIZE
    assert moves(h, battler) == (153).to_bytes(2, "little") * 4
    assert h.bytes(base + h.M.BATTLE_MON_PP_OFF, 4) == bytes([5] * 4)
    assert h.u8(h.M.CHOSEN_ACTION_ADDR + battler) == 0
    assert h.u16(h.M.CHOSEN_MOVE_ADDR + battler * 2) == 153
    assert h.u8(h.M.BATTLE_COMM_ADDR + battler) == 3
    assert h.u8(0x02018000 + h.M.BATTLE_STRUCT_CHOSEN_MOVE_POS_OFF + battler) == 0
    assert h.u8(0x02018000 + h.M.BATTLE_STRUCT_MOVE_TARGET_OFF + battler) == 1
    assert h.bytes(h.M.PARTY_BASE, 300) == party_before
    assert h.bytes(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_SIZE, h.M.BATTLE_MON_SIZE) == foe_before


def test_switch_settlement_resolves_key_and_keeps_new_battler_hp_and_lock(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.set_battler(1, 333)
    h.seed_u16(h.M.LOCKED_MOVES_ADDR, 999)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0
    assert h.u16(h.M.PARTY_BASE + h.M.MON_SIZE + h.M.OFF_HP) == 50
    assert h.u16(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_HP_OFF) == 50
    assert h.u16(h.M.LOCKED_MOVES_ADDR) == 999


def test_borrowed_transition_and_battle_cleanup_retain_real_obligation(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u8(h.MB.SW, 1)
    h.seed_u8(h.MB.SW + 1, 1)
    h.seed_u32(h.MB.SW + 4, 111)
    h.seed_u16(h.M.CHOSEN_MOVE_ADDR, 33)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    h.step()
    assert h.u16(h.M.CHOSEN_MOVE_ADDR) == 33
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    end_battle(h)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.seed_u8(h.MB.SW, 0)
    h.seed_u8(h.MB.SW + 1, 2)
    h.step(2)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0


def test_postbattle_writer_blocks_then_settles_retained_identity(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    task = h.M.TASKS_BASE_ADDR
    h.seed_u32(task, h.M.POST_BATTLE_WRITER_TASKS[1])
    h.seed_u8(task + 4, 1)
    end_battle(h)
    h.step(4)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.seed_u8(task + 4, 0)  # DestroyTask leaves the function pointer in place.
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0


@pytest.mark.parametrize("fault", ["duplicate_key", "counted_vacancy", "invalid_bs", "absent_key"])
def test_unavailable_identity_or_allocation_never_authorizes_writes(rr_repo, fault):
    h = battle(rr_repo)
    if fault == "duplicate_key":
        h.set_mon(1, 111)
    elif fault == "counted_vacancy":
        h.seed(h.M.PARTY_BASE + h.M.MON_SIZE, bytes(100))
    elif fault == "invalid_bs":
        h.seed_u32(h.M.BATTLE_STRUCT_PTR_ADDR, 0x08000100)
    key = h.key(999 if fault == "absent_key" else 111)
    party_before, moves_before = h.bytes(h.M.PARTY_BASE, 300), moves(h)
    h.command("force_explode", key=key)
    h.step()
    assert moves(h) == moves_before
    assert h.bytes(h.M.PARTY_BASE, 300) == party_before


def test_old_context_never_reinforces_new_allocation_and_waits_for_field(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u32(h.M.BATTLE_STRUCT_PTR_ADDR, 0x02019000)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    h.seed_u16(h.M.CHOSEN_MOVE_ADDR, 33)
    h.seed(0x02019000, bytes([0xA5] * 256))
    h.step()
    assert h.u16(h.M.CHOSEN_MOVE_ADDR) == 33
    assert h.bytes(0x02019000, 256) == bytes([0xA5] * 256)
    end_battle(h)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0


def test_local_duplicate_does_not_extend_existing_fallback_deadline(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.step(599)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    h.command("force_explode", key=h.key(111))
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0


def test_observed_host_rewind_retains_uncertainty_without_mutation(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.lua.globals()._RR_FRAME = 0
    end_battle(h)
    h.step(3)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    assert any("continuity needs reconciliation" in str(row) for row in h.lua.globals()._RR_LOGS.values())


def test_unsettled_previous_battle_cannot_reinforce_chained_battle(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u8(0x03000F9C, 1)
    end_battle(h)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.set_battle(True)
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, 0x08014041)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    h.seed_u16(h.M.CHOSEN_MOVE_ADDR, 33)
    h.step()
    assert h.u16(h.M.CHOSEN_MOVE_ADDR) == 33
    assert h.u8(h.M.BATTLE_COMM_ADDR) == 0
    end_battle(h)
    h.seed_u8(0x03000F9C, 0)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0


def test_absent_target_is_retained_without_fainting_then_resolved_by_key(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.set_mon(0, 777)
    end_battle(h)
    h.step(2)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.set_mon(2, 111)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    assert h.u16(h.M.PARTY_BASE + 2 * h.M.MON_SIZE + h.M.OFF_HP) == 0


def test_changed_save_cannot_inherit_pending_key_even_when_party_key_matches(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u8(h.SB2 + 1, 0xBC)
    end_battle(h)
    h.step(2)
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50


@pytest.mark.parametrize("state", [3, 4, 5, 6])
def test_first_request_waits_while_action_controller_has_already_progressed(rr_repo, state):
    h = battle(rr_repo)
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, 0x08014041)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, state)
    before = moves(h)
    h.command("force_explode", key=h.key(111))
    h.step()
    assert h.u8(h.M.BATTLE_COMM_ADDR) == state
    assert moves(h) == before
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)  # The next verified selection phase.
    h.step()
    assert moves(h) == (153).to_bytes(2, "little") * 4


def test_first_request_does_not_treat_nonselection_battle_main_as_readiness(rr_repo):
    h = battle(rr_repo)
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, h.M.RETURN_FROM_BATTLE_ADDR)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)
    before = moves(h)
    h.command("force_explode", key=h.key(111))
    h.step()
    assert moves(h) == before
    assert h.u8(h.M.BATTLE_COMM_ADDR) == 0


@pytest.mark.parametrize("state,action,ready", [(0, 3, True), (1, 3, True), (2, 0, True), (2, 1, False), (2, 2, False)])
def test_selection_case_gate_distinguishes_move_from_item_or_switch(rr_repo, state, action, ready):
    h = battle(rr_repo)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, state)
    h.seed_u8(h.M.CHOSEN_ACTION_ADDR, action)
    before = moves(h)
    h.command("force_explode", key=h.key(111))
    h.step()
    expected = (153).to_bytes(2, "little") * 4 if ready else before
    assert moves(h) == expected


def test_reinforcement_and_elapsed_fallback_wait_for_verified_selection(rr_repo):
    h = battle(rr_repo)
    h.command("force_explode", key=h.key(111))
    h.step()
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, 0x080150A9)
    h.seed_u8(h.M.BATTLE_COMM_ADDR, 0)  # Stale low state during turn execution.
    h.seed_u16(h.M.CHOSEN_MOVE_ADDR, 33)
    h.step(600)
    assert h.u16(h.M.CHOSEN_MOVE_ADDR) == 33
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 50
    h.seed_u32(h.M.BATTLE_MAIN_FUNC_ADDR, 0x08014041)
    h.step()
    assert h.u16(h.M.PARTY_BASE + h.M.OFF_HP) == 0
