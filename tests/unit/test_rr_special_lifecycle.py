"""Actual pinned ROM census plus bounded parser refusal controls; no emulator."""
from pathlib import Path
import pytest
from tools.research import rr_special_lifecycle as rr
from tools.pin_gen3_site import ROM_SPECS


def test_unrecognized_rom_identity_fails_closed():
    with pytest.raises(ValueError, match="unrecognized RR identity"):
        rr.census(b"not an admitted cartridge")


@pytest.mark.parametrize("address,size", [(rr.ROM_BASE-1,1),(rr.ROM_BASE,4),(rr.ROM_BASE,-1)])
def test_reader_refuses_outside_bounds(address,size):
    with pytest.raises(ValueError, match="ROM bounds"):
        rr.take(b"abc",address,size)


def test_unknown_command_and_incomplete_command_fail_closed():
    with pytest.raises(ValueError, match="unrecognized script opcode"):
        rr.instructions(bytes([0xEE]),rr.ROM_BASE,rr.ROM_BASE+1)
    with pytest.raises(ValueError, match="ROM bounds"):
        rr.instructions(bytes([0x23]),rr.ROM_BASE,rr.ROM_BASE+1)


@pytest.mark.parametrize("path,sha1", [
    (ROM_SPECS["rr"][3],rr.CLEAN_SHA1),
    (ROM_SPECS["rr_companion"][3],rr.COMPANION_SHA1)])
def test_actual_nature_census_proves_script_and_mutation_pair(path,sha1):
    if not path.is_file(): pytest.skip(f"absent pinned ROM: {path}")
    result=rr.census(path.read_bytes())
    assert result["rom_sha1"] == sha1
    n=result["nature"]
    assert n["map"] == [5,4] and n["npc"]["local_id"] == 5
    assert n["npc"]["script"] == rr.SERVICE and n["npc"]["flag_id"] == 0
    assert n["anchor_occurrences"] == 1
    assert n["code_sha256"] == "d9a37097cd0f5b8871109981c41a1b53dbc0dd274daeb6144ddb330080a2c045"
    assert n["before_pid_store"] == 0x090B1874
    assert n["after_pid_store"] == 0x090B1878
    assert n["mon_register"] == "R4" and n["stride"] == 100
    assert n["slot_address"] == 0x020370C0 and n["party_base"] == 0x02024284
    assert len(n["wrappers"]) == 21
    assert len({w["nature"] for w in n["wrappers"]}) == 21
    assert "free of charge" in n["texts"][0]["text"]
    borrow = result["borrowed_party"]
    assert borrow["status"] == "SOURCE_PIN"
    assert borrow["begin"] == 0x09079300 and borrow["end"] == 0x0804C262
    assert borrow["script_flags_checked"] == [0x1047, 0x1096]
    assert borrow["npc"]["script"] == 0x09051ABF
    assert all(b["anchor_occurrences"] == 1 for b in borrow["bodies"].values())
    assert "UNRESOLVED" in borrow["postbattle_restore_caller"]


def test_borrowed_contract_wrong_script_target_and_truncation_fail_closed():
    path = ROM_SPECS["rr"][3]
    if not path.is_file(): pytest.skip(f"absent pinned ROM: {path}")
    rom = path.read_bytes()
    altered = bytearray(rom)
    altered[0x01051B88] ^= 2
    with pytest.raises(ValueError, match="script binding changed"):
        rr.borrowed_contract(bytes(altered))
    with pytest.raises(ValueError, match="ROM bounds"):
        rr.borrowed_contract(rom[:0x01079304])
    altered = bytearray(rom)
    altered[0x0015FD60 + 0x28*4] ^= 2
    with pytest.raises(ValueError, match="special target changed"):
        rr.borrowed_contract(bytes(altered))


def test_existing_battle_fixture_school_progress_flags_are_clear():
    path = Path(__file__).resolve().parents[1] / "fixtures/gen3/rr_battle2.sav"
    rom_path = ROM_SPECS["rr"][3]
    if not path.is_file() or not rom_path.is_file(): pytest.skip("existing RR battle fixture/ROM absent")
    result = rr.school_fixture_flags(rom_path.read_bytes(), path.read_bytes())
    assert result["sha256"] == "4145232bca94592323a46fcbe606e153abde52a89594fd86ae790c93abd276ac"
    assert result["flags"] == {"1047": 0, "1096": 0}
    assert "unauthenticated" in result["storage"]


def test_opponent_script_target_and_actual_party_callee_are_bound():
    for name in ("rr", "rr_companion"):
        path = ROM_SPECS[name][3]
        if not path.is_file(): pytest.skip(f"absent pinned ROM: {path}")
        rom = path.read_bytes()
        facts = rr.census(rom)["borrowed_party"]
        assert facts["opponent_entry"] == 0x090790C8 and facts["opponent_begin"] == 0x090790E4
        assert facts["opponent_script_call"] == 0x09051C11
        assert facts["opponent_var"] == 0x512B and facts["opponent_branch_values"] == [6, 7]
        assert facts["bodies"]["opponent_builder"]["size"] == 72
        assert facts["bodies"]["opponent_callee"]["size"] == 300
        assert facts["opponent_party_pointer_literal"] == 0x09079108
        altered = bytearray(rom)
        altered[0x01051C12] ^= 2
        with pytest.raises(ValueError, match="script binding changed"):
            rr.borrowed_contract(bytes(altered))


@pytest.mark.parametrize("value,expected_hit", [(0,False),(5,False),(6,True),(7,True),(8,False),(0xFFFF,False)])
def test_opponent_prewrite_point_is_reached_only_by_actual_six_seven_branches(value,expected_hit):
    """Follow the ROM's bounded Thumb control flow after the VAR512B read."""
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    path = ROM_SPECS["rr"][3]
    if not path.is_file(): pytest.skip(f"absent pinned ROM: {path}")
    rom = path.read_bytes()
    decoded = {i.address:i for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(
        rr.take(rom,0x090790D2,40),0x090790D2)}
    pc,eq,hit = 0x090790D2,False,False
    for _ in range(24):
        if pc == 0x090790E4:
            hit=True;break
        instruction=decoded[pc]
        if instruction.mnemonic=="pop": break
        if instruction.mnemonic=="cmp":
            assert instruction.op_str.startswith("r0, #")
            eq=value==int(instruction.op_str.split("#")[1],0)
        if instruction.mnemonic=="bne" and not eq or instruction.mnemonic=="b":
            pc=int(instruction.op_str.removeprefix("#"),0)
        else: pc+=instruction.size
    assert hit is expected_hit
