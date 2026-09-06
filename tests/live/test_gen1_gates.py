"""The Gen 1 headless gates, as pytest.

    SLINK_LIVE=1 pytest tests/live/test_gen1_gates.py -q
    SLINK_LIVE=1 pytest tests/live -q -k memory

Gen 1 had unit tests and a Lua client but had never executed against a running cartridge.
That gap hid real bugs that no static check could reach — a deferred-command queue that
crashed on first use (valid Lua, so the syntax gate passed), a box level read from an
offset past the end of the box struct, PP reported without its PP-Up mask. These gates
close it.

DIFFERENT FROM tests/live/test_lua_gates.py (Gen 3), which loads a version-locked
`slink_*.State` and therefore needs tools/mkstates.py to rebuild states after every BizHawk
upgrade. Gen 1 boots from `tests/fixtures/gen1/*.SaveRAM` — battery saves are plain SRAM,
never version-locked — so nothing here goes stale. Booting to CONTINUE costs ~640 frames.

Each gate is skipped, never hung, when a prerequisite is missing: no EmuHawk, no cartridge
dump (they are gitignored), or no fixture.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as play  # noqa: E402
from run_gb_gate import run_gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 1 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

# gate script -> which fixture it needs. Both currently want an encounter-free save; a gate
# that needs a wild battle would ask for "battle" instead.
GATES = {
    "lua/tests/test_platform_storage_gate.lua": "town",
    "lua/tests/test_gen1_session_metadata_gate.lua": "town",
    # Execute canonical MoveMon/RemovePokemon on cloned emulator states and compare
    # all active records, names, lists and dex bytes across every count/source slot.
    "lua/tests/test_gen1_storage_differential.lua": "town",
    "lua/tests/test_gen1_storage_persistence.lua": "town",
    "lua/tests/test_gen1_stats_differential.lua": "town",
    "lua/tests/test_gen1_memory_gate.lua": "town",
    "lua/tests/test_gen1_writes_gate.lua": "town",
    # The withdraw half of party sync. test_gen1_writes_gate only deposits.
    "lua/tests/test_gen1_boxroundtrip_gate.lua": "town",
    # The stat formula behind the withdraw rebuild, checked against the GAME's own numbers:
    # every party mon carries both the inputs and the answer, so recomputing and comparing
    # is a real control rather than a self-consistency check.
    "lua/tests/test_gen1_stat_rebuild.lua": "town",
    # Evolution: a Gen 1 key is DVs:OTID:SPECIES, so evolving rewrites it. Drives a real
    # Moon Stone through the real bag menus — no battle, no encounter RNG, and
    # uncancellable (wForceEvolution). Needs the town save, not the battle one:
    # ItemUseEvoStone refuses outright while wIsInBattle is set.
    "lua/tests/test_gen1_evolution_gate.lua": "town",
}
ROMS = ("red", "blue", "yellow")


def test_gen1_luasocket_fragmentation_and_reconnect(emuhawk, monkeypatch):
    """Real DLL wire fidelity, bounded flooding, oversize resync and stream isolation."""
    import secrets
    import socket
    import threading
    import time

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(.2)
    stop = threading.Event()
    failures, seen = [], []
    token = secrets.token_hex(16)
    monkeypatch.setenv("SLINK_TRANSPORT_PORT", str(listener.getsockname()[1]))
    monkeypatch.setenv("SLINK_TRANSPORT_TOKEN", token)

    def accept():
        deadline = time.monotonic() + 60
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                conn, _ = listener.accept()
                conn.settimeout(20)
                return conn
            except TimeoutError:
                continue
        raise AssertionError("emulator did not connect to the local transport peer")

    def peer():
        try:
            with accept() as first:
                received = first.makefile("rb").readline(400000)
                assert received == token.encode() + b":" + "é12345678".encode() * 30000 + b"\n"
                seen.append("outbound")
                first.sendall(b"".join(f"n:{i}\n".encode() for i in range(1000)))
                long = b"R" + "éabc".encode() * 40000 + b"\n"
                # Force multiple partial receives, including one-byte boundaries.
                for start in range(0, len(long), 997):
                    part = long[start:start + 997]
                    first.sendall(part[:1])
                    first.sendall(part[1:])
                    time.sleep(.001)
                first.sendall(b"X" * (5 * 1024 * 1024) + b"\nsurvived\nready\nstale\n")
                assert first.recv(1) == b"", "first stream was not explicitly disconnected"
            with accept() as second:
                second.sendall(b"fresh:" + token.encode() + b"\n")
                assert second.makefile("rb").readline(100) == b"ack:" + token.encode() + b"\n"
                seen.append("reconnected")
        except Exception as exc:
            failures.append(repr(exc))

    thread = threading.Thread(target=peer, daemon=True)
    thread.start()
    try:
        passed, result_path, text = run_gate("lua/tests/test_gen1_transport_gate.lua",
                                            rom_key="red", target="town", timeout=180, quiet=True)
        thread.join(5)
        assert passed, f"real transport gate failed\n{result_path}\n{text[-5000:]}"
        assert not failures and seen == ["outbound", "reconnected"], (failures, seen)
        assert not thread.is_alive(), "local transport peer did not finish"
    finally:
        stop.set()
        listener.close()
        thread.join(1)


@pytest.mark.parametrize("rom", ROMS)
@pytest.mark.parametrize("state,target", [("overworld", "town"), ("battle", "battle")])
def test_gen1_write_checkpoint(rom, state, target, emuhawk):
    """Independent cartridge execution contexts exercise the real runtime predicate."""
    import hashlib
    from pathlib import Path

    passed, result_path, text = run_gate(f"lua/tests/test_gen1_write_safety_{state}.lua",
                                        rom_key=rom, target=target, timeout=300, quiet=True)
    assert passed, f"checkpoint gate {state}/{rom} failed\n{result_path}\n{text[-6000:]}"
    expected = hashlib.sha1(Path(REPO, play.ROMS[rom]).read_bytes()).hexdigest()
    assert f"rom_sha1={expected}" in text


def test_yellow_pc_policy(emuhawk):
    """Exercise the unmodified Yellow deposit permission branch, including starter identity."""
    passed, result_path, text = run_gate("lua/tests/test_gen1_yellow_pc_policy.lua",
                                        rom_key="yellow", target="town", timeout=300, quiet=True)
    assert passed, f"Yellow PC policy did not PASS\nresult: {result_path}\n{text[-3000:]}"


@pytest.mark.parametrize("rom", ROMS)
def test_gen1_party_codec_cartridge(rom, emuhawk):
    """Lua and Python consume a current-run cartridge-produced blob; PP uses the engine oracle."""
    import hashlib
    import json
    from pathlib import Path

    from server.gen1_party_codec import PartyCodec

    evidence = Path(REPO, f".cache/gen1-codec-{rom}.json")
    evidence.unlink(missing_ok=True)
    passed, result_path, text = run_gate("lua/tests/test_gen1_party_codec_gate.lua",
                                        rom_key=rom, target="town", timeout=300, quiet=True)
    assert passed, f"codec gate {rom} did not PASS\nresult: {result_path}\n{text[-3000:]}"
    result = json.loads(evidence.read_text())
    expected_hash = hashlib.sha1(Path(REPO, play.ROMS[rom]).read_bytes()).hexdigest()
    assert result["rom_sha1"].lower() == expected_hash
    assert result["variant"] == rom and result["pp_cases"] == 660
    decoded = PartyCodec(rom).validate_blob(result["blob"], expected_key=result["key"])
    assert decoded.experience == 1000


@pytest.mark.parametrize("rom", ROMS)
def test_gen1_prepared_command_receipts(rom, emuhawk):
    """Real RAM/file persistence and a separate Python validator verify current-run receipts."""
    import hashlib
    import json
    from pathlib import Path

    from server.gen1_command_receipts import verify_force_faint_receipt

    evidence = Path(REPO, f".cache/gen1-command-receipts-{rom}.json")
    evidence.unlink(missing_ok=True)
    passed, result_path, text = run_gate("lua/tests/test_gen1_command_receipts_gate.lua",
                                        rom_key=rom, target="town", timeout=300, quiet=True)
    assert passed, f"prepared command gate {rom} failed\n{result_path}\n{text[-5000:]}"
    result = json.loads(evidence.read_text(encoding="utf-8"))
    assert result["variant"] == rom
    assert result["rom_sha1"] == hashlib.sha1(Path(REPO, play.ROMS[rom]).read_bytes()).hexdigest()
    assert [case["boundary"] for case in result["cases"]] == ["before_effect", "after_effect"]
    for case in result["cases"]:
        assert case["physical_writes"] == 2 and case["unrelated_wram_changes"] == 0
        assert verify_force_faint_receipt(case["command"], case["receipt"], variant=rom,
                                         identity=case["identity"])["slot"] == 0


@pytest.mark.parametrize("rom", ROMS)
def test_gen1_original_trade_animation(rom, emuhawk):
    """Original source-derived scene order, rendering and return on each cartridge."""
    import hashlib
    import json
    from pathlib import Path

    evidence = Path(REPO, f".cache/gen1-native-trade-animation-{rom}.json")
    evidence.unlink(missing_ok=True)
    passed, result_path, text = run_gate("lua/tests/test_gen1_native_trade_animation.lua",
                                        rom_key=rom, target="town", timeout=300, quiet=True)
    assert passed, f"original trade animation {rom} failed\n{result_path}\n{text[-5000:]}"
    result = json.loads(evidence.read_text(encoding="utf-8"))
    assert result["variant"] == rom and result["native_entry"] == "InternalClockTradeAnim"
    assert result["rom_sha1"] == hashlib.sha1(Path(REPO, play.ROMS[rom]).read_bytes()).hexdigest()
    source = "pokeyellow" if rom == "yellow" else "pokered"
    script = Path(REPO, f".cache/pret/{source}/engine/movie/trade.asm").read_text(encoding="utf-8")
    sequence = script.split("\nInternalClockTradeFuncSequence:\n", 1)[1].split("\n\tdb -1", 1)[0]
    expected = [line.strip().split()[1] for line in sequence.splitlines() if line.strip().startswith("tradefunc ")]
    assert len(expected) == 16 and result["expected"] == expected
    assert [entry["name"] for entry in result["trace"]] == expected
    assert result["frames"] > 500 and result["font_bytes_verified"] > 0 and result["party_unchanged"] is True
    samples = result["samples"]
    assert [s["phase"] for s in samples] == ["Trade_ShowPlayerMon", "Trade_AnimLeftToRight", "Trade_ShowEnemyMon"]
    assert len({s["vram_hex"] for s in samples}) == 3
    for sample in samples:
        screenshot = Path(sample["screenshot"]).resolve()
        assert screenshot.is_relative_to(Path(REPO).resolve())
        assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

# The companion-patch spike, which only exists for Red and Blue — Yellow has no free WRAM
# for a mailbox (pret's map: WRAM0 TOTAL EMPTY $0000).
PATCH_ROMS = ("red_patched", "blue_patched")


@pytest.fixture(scope="session")
def emuhawk():
    if not os.path.exists(play.EMUHAWK):
        pytest.skip(f"EmuHawk not found at {play.EMUHAWK}")
    return play.EMUHAWK


@pytest.mark.parametrize("gate", sorted(GATES))
@pytest.mark.parametrize("rom", ROMS)
def test_gen1_gate(gate, rom, emuhawk):
    """Run one gate against one ROM.

    Parametrised over all three cartridges on purpose: Yellow shifts nearly every WRAM
    address by -1, so a Red-only run would not exercise the profile that is most likely to
    be wrong.
    """
    if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
        pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
    target = GATES[gate]
    fixture = os.path.join(play.FIXTURES, f"{rom}_{target}.SaveRAM")
    if not os.path.exists(fixture):
        pytest.skip(f"missing fixture — build with "
                    f"`python tools/gen1_playthrough.py --rom {rom} --target {target}`")

    passed, result_path, text = run_gate(gate, rom_key=rom, target=target,
                                         timeout=300, quiet=True)
    assert passed, (f"{os.path.basename(gate)} on {rom}/{target} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


@pytest.mark.parametrize("rom", PATCH_ROMS)
def test_gen1_companion_patch(rom, emuhawk):
    """The companion-patch spike: is the injected code reached, every frame, everywhere?

    Asserts the 'SLNK' beacon, a frame counter that advances in the overworld AND in battle
    AND with a menu open (VBlank is an interrupt, which is why that hook site was chosen),
    that the displaced TrackPlayTime still runs, and that the game still plays.
    """
    from run_gb_gate import PATCHED
    base_key, rom_rel, _ = PATCHED[rom]
    if not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python patch/gen1/tools/build.py`")
    if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_town.SaveRAM")):
        pytest.skip("missing fixture — `python tools/gen1_playthrough.py`")

    passed, result_path, text = run_gate("lua/tests/test_gen1_patch_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"companion patch gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


@pytest.mark.parametrize("rom", PATCH_ROMS)
def test_gen1_menu_row(rom, emuhawk):
    """The SLINK row the companion patch appends to the START menu.

    Separate from the companion-patch gate because it tests a different thing: that gate
    covers the VBlank hook and its mailbox, this one covers a structural edit to a menu the
    player uses constantly. The row is INERT in this increment -- selecting it falls through
    to CloseStartMenu exactly as EXIT does -- so what is under test is that it draws inside
    a resized box, that the cursor can reach it, and that no existing menu index moved.
    """
    from run_gb_gate import PATCHED
    base_key, rom_rel, _ = PATCHED[rom]
    if not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python patch/gen1/tools/build.py`")
    if not os.path.exists(os.path.join(play.FIXTURES, f"{base_key}_town.SaveRAM")):
        pytest.skip("missing fixture — `python tools/gen1_playthrough.py`")

    passed, result_path, text = run_gate("lua/tests/test_gen1_menu_row_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"START-menu row gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


# The Archipelago builds and their negative control. `red_cold`/`blue_cold` run the SAME
# gate on the VANILLA cartridge, where every AP assertion has to come out the other way —
# without that pair, a detection function stuck at "yes" would pass on its own.
AP_ROMS = ("red_ap", "blue_ap", "red_cold", "blue_cold")


@pytest.mark.parametrize("rom", AP_ROMS)
def test_gen1_archipelago(rom, emuhawk):
    """Does SLink read an Archipelago cartridge, and only when it is one?

    Needs no fixture: the fork's save block is 4 bytes longer than vanilla's
    (sMainDataCheckSum 0xB523 -> 0xB527), so no committed .SaveRAM is loadable by it and the
    gate asserts against the ROM and the intro instead. See the gate's own header.
    """
    from run_gb_gate import PATCHED
    _, rom_rel, _ = PATCHED[rom]
    if rom_rel is None:                       # the vanilla control: needs only the dump
        base = play.ROMS[rom.rsplit("_", 1)[0]]
        if not os.path.exists(os.path.join(REPO, base)):
            pytest.skip(f"{base} not present (ROMs are gitignored)")
    elif not os.path.exists(os.path.join(REPO, rom_rel)):
        pytest.skip(f"{rom_rel} not built — `python tools/gen1_ap_rom.py` "
                    f"(needs a Pokemon RB apworld and the vanilla dump)")

    passed, result_path, text = run_gate("lua/tests/test_gen1_ap_gate.lua",
                                         rom_key=rom, target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"Archipelago gate on {rom} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")


def test_gen1_panel_on_a_randomized_cartridge(emuhawk):
    """THE structural injector's only real question, answered on hardware.

    build.py is gated on the two pinned clean SHA-1s, which is right for a build tool and
    useless for a randomized ROM: every seed is a different file, so there is no hash to
    check and a UPS -- which embeds its source's CRC32 -- cannot apply at all. The injector
    therefore verifies STRUCTURE: every span holds the bytes the manifest expects, the hook
    site is untouched, bank $3F is empty, the header is protected.

    That reasoning is only as good as the cartridge it produces, and the failure it would
    hide is one no byte comparison can see: a ROM that patches "successfully" and then does
    not boot. So this randomizes Red for real, injects, and runs the whole panel gate --
    row, open, staging, page turn, close, walk away -- on the result.

    The artifact is rebuilt rather than committed, because a randomized ROM is a ROM.
    """
    import subprocess

    from run_gb_gate import PATCHED
    _base, rom_rel, _sav = PATCHED["red_rand_patched"]
    rom_path = os.path.join(REPO, rom_rel)

    if not os.path.exists(rom_path):
        proc = subprocess.run([sys.executable,
                               os.path.join(REPO, "tools", "make_randomized_patched.py")],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(rom_path):
            pytest.skip(f"could not build a randomized+patched ROM: "
                        f"{(proc.stderr or '').strip()[-200:]}")

    passed, result_path, text = run_gate("lua/tests/test_gen1_menu_row_gate.lua",
                                         rom_key="red_rand_patched", target="town",
                                         timeout=300, quiet=True)
    assert passed, (f"the panel gate failed on a randomized+injected cartridge\n"
                    f"result: {result_path}\n{text[-3000:]}")
