"""Which client `lua/slink.lua` loads for a Gen 2 cartridge (card gen2-U5, Crystal cutover;
docs/gen2/reviews/OMP_U5_CUTOVER_FACTS_2026-09-23.md).

Mirrors tests/unit/test_gen1_launcher_route.py's approach for the same reason: the launcher
is the only thing a player ever runs, and no other test executes its dispatch. This drives
the real `lua/slink.lua` under lupa with BizHawk's globals stubbed and asserts on the one
observable that matters: the path that gets dofile'd. `dofile` is intercepted rather than
mocked away for `gen1/entry.lua` and `gen2/entry.lua`, so the header/title detection the
route depends on is the real `Entry.detect_title`, not a restatement of it. `gen2/run.lua`
itself is recorded, never executed -- it dofiles BizHawk-only modules (connector, hud) and
opens a socket, which belongs in a live gate, not here.
"""
from __future__ import annotations

import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the launchers")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LUA = os.path.join(_REPO, "lua").replace("\\", "/")
_NEW_CLIENT = "lua/gen2/run.lua"
_OLD_CLIENT = "lua/clients/gen2_crystal_client.lua"
_TITLE_OFFSET = 0x134


def _rom(title: str) -> bytes:
    """A cartridge image whose $0134 title field holds `title`, zero-padded."""
    image = bytearray(_TITLE_OFFSET + 16)
    image[_TITLE_OFFSET:_TITLE_OFFSET + len(title)] = title.encode("ascii")
    return bytes(image)


def _run_launcher(system_id: str | None, rom: bytes, detected_game_id: str = "gen3_frlge") -> list[str]:
    """dofile `lua/slink.lua` with stub BizHawk globals; return the paths it dofile'd.

    Only `gen1/entry.lua` and `gen2/entry.lua` are executed for real -- both are pure
    cartridge-header detectors with no side effects -- every other dofile target
    (including `gen2/run.lua`) is recorded and skipped, so no client ever starts.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    loaded: list[str] = []

    def norm(path: str) -> str:
        rel = os.path.relpath(os.path.normpath(path), _REPO)
        return rel.replace("\\", "/")

    real_dofile = g.dofile

    def fake_dofile(path):
        rel = norm(path)
        loaded.append(rel)
        if rel.endswith("gen1/entry.lua") or rel.endswith("gen2/entry.lua"):
            return real_dofile(path)
        return None

    def getsystemid():
        if system_id is None:
            raise RuntimeError("no core loaded")
        return system_id

    g.dofile = fake_dofile
    g.emu = lua.table_from({"getsystemid": getsystemid})
    g.client = lua.table_from({"getversion": lambda: "2.11.1"})
    g.memory = lua.table_from({
        "read_u8": lambda addr, domain: rom[addr] if 0 <= addr < len(rom) else 0,
    })
    g.console = lua.table_from({"log": lambda *a: None})
    g.io.open = lambda *a: None  # the console-tee log; nil handle is "no log available"
    g.require = lambda name: lua.table_from({
        "detect": lambda: lua.table_from({
            "module": lua.table_from({"display_name": detected_game_id}),
            "variant": "x", "profile": lua.table_from({}), "game_id": detected_game_id,
        }),
    }) if name == "game_detect" else None

    real_dofile(f"{_LUA}/slink.lua")
    return loaded


def _asserts_exactly_one_client(loaded: list[str]) -> None:
    """The Gen 1 probe (gen1/entry.lua) always runs first and legitimately finds no match
    for a Crystal header; the Gen 2 route must still be the only CLIENT ever dofile'd."""
    clients = [p for p in loaded if p.endswith("run.lua") or "client" in p]
    assert clients == [_NEW_CLIENT], f"expected exactly one client, got {clients}: {loaded}"


def test_a_crystal_cartridge_reaches_the_new_client():
    loaded = _run_launcher("GBC", _rom("PM_CRYSTAL"))
    assert _NEW_CLIENT in loaded, loaded
    _asserts_exactly_one_client(loaded)


def test_super_game_boy_mode_crystal_reaches_the_new_client():
    loaded = _run_launcher("SGB", _rom("PM_CRYSTAL"))
    assert _NEW_CLIENT in loaded, loaded
    _asserts_exactly_one_client(loaded)


@pytest.mark.parametrize("header", ["POKEMON_GLD", "POKEMON_SLV"])
def test_gold_and_silver_headers_also_reach_the_new_client(header):
    """O-23 widened admission to all three titles: the launcher routes by TITLE (any
    Entry.detect_title match), not by a per-title admission check -- Entry.build (run.lua)
    is what admits or refuses a given Gold/Silver revision."""
    loaded = _run_launcher("GBC", _rom(header))
    assert _NEW_CLIENT in loaded, loaded
    _asserts_exactly_one_client(loaded)


def test_crystal_ap_keeps_the_legacy_route():
    """The Archipelago fork's header is "AP_CRYSTAL", not "PM_CRYSTAL" -- Entry.detect_title
    (gen2) does not recognise it at all (O-8: AP is not admitted in the RC), so it never
    reaches the new client and falls through to game_detect exactly as before."""
    loaded = _run_launcher("GBC", _rom("AP_CRYSTAL"), detected_game_id="gen2_crystal")
    assert _NEW_CLIENT not in loaded, loaded
    assert _OLD_CLIENT in loaded, loaded


def test_a_non_gameboy_core_is_untouched_by_the_gen2_route():
    """A GBA core never reaches Entry.detect_title (gen2) at all -- not even a header that
    happens to spell PM_CRYSTAL routes a non-Game-Boy core into the Gen 2 client."""
    loaded = _run_launcher("GBA", _rom("PM_CRYSTAL"), detected_game_id="gen3_frlge")
    assert _NEW_CLIENT not in loaded, loaded
    assert "lua/gen2/entry.lua" not in loaded, loaded
    assert "lua/clients/gen3_frlge_client.lua" in loaded, loaded


def test_a_failing_system_probe_does_not_route_to_gen2():
    loaded = _run_launcher(None, _rom("PM_CRYSTAL"))
    assert _NEW_CLIENT not in loaded, loaded


# ── run.lua's own admission: an unpinned Crystal sha1 is refused with no fallback ────────
#
# run.lua builds production through Entry.build only (U3, lua/gen2/run.lua), which calls
# Entry.admit first. This drives that real function directly -- not through slink.lua/run.lua,
# which would need a live socket and BizHawk memory domains -- to pin the fail-closed
# contract the launcher route above depends on: a cartridge whose sha1 the admission catalog
# does not know is refused outright, with no vanilla-header fallback (unlike Gen 1's named-
# family fallback, deliberately absent here per the plan, GEN2_BINDING_PLAN.md:372 P6.2).
def test_an_unpinned_crystal_sha1_is_refused_with_no_fallback():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    Entry = lua.eval(f'dofile("{_LUA}/gen2/entry.lua")')
    rom = _rom("PM_CRYSTAL")  # correct header, but not any real ROM's bytes/sha1

    def read_rom_u8(offset):
        return rom[offset] if 0 <= offset < len(rom) else 0

    deps = lua.table_from({"root": _REPO, "rom_size": len(rom), "read_rom_u8": read_rom_u8})
    result, reason = Entry.build(deps)
    assert result is None, "an unadmitted sha1 must never fall back to a client build"
    assert "unknown artifact SHA-1" in reason, reason
