"""Exact RR action-selection dispatch evidence; no upstream enum guessing."""

import hashlib
import struct


def test_pinned_rr_selection_state_machine_and_turn_transition(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
    # HandleTurnActionSelectionState entry and comm[battler] dispatch (max6).
    assert rom[0x14040:0x14050].hex() == "f0b557464e464546e0b487b00f480021"
    assert rom[0x14070:0x1408C].hex() == "0649207840180078062801d900f0e7fd800005494018006887460000"
    assert struct.unpack_from("<I", rom, 0x1408C)[0] == 0x02023E82
    assert struct.unpack_from("<I", rom, 0x14098)[0] == 0x0801409C
    assert struct.unpack_from("<7I", rom, 0x1409C) == (
        0x080140B8, 0x080141DC, 0x08014764, 0x08014AA0,
        0x08014B44, 0x08014B88, 0x08014C20,
    )
    # State1 reads controller action into gChosenAction; state2 dispatches it.
    assert rom[0x1420A:0x1421C].hex() == "0d4aaa180d49680201314018007810701878"
    assert struct.unpack_from("<II", rom, 0x14240) == (0x02023D7C, 0x020233C4)
    assert rom[0x14790:0x1479A].hex() == "0849681800780b1c0928"
    assert struct.unpack_from("<I", rom, 0x147B4)[0] == 0x02023D7C
    # State4 increments ACTIONS_CONFIRMED_COUNT. Once every battler is confirmed,
    # the function assigns the turn-order main080150A9, not another selection.
    assert rom[0x14B6C:0x14B76].hex() == "05490879013008716be0"
    assert rom[0x14C68:0x14C78].hex() == "0a4800791278904202d10a490a480860"
    assert struct.unpack_from("<II", rom, 0x14C9C) == (0x03004F84, 0x080150A9)
    # RR's extended turn-start routine contains the same Thumb selection pointer.
    assert struct.unpack_from("<I", rom, 0x10706E0)[0] == 0x08014041
