"""Which client `lua/slink.lua` loads for a Gen 3 cartridge (P4 C4-4).

Mirrors `test_gen1_launcher_route.py`'s technique: execute the real launcher under lupa with
BizHawk's globals stubbed, and assert on the one observable that matters -- the path that gets
dofile'd. `lua/gen3/entry.lua` and `lua/json_codec.lua` are dofile'd for real (not stubbed), so
the admission the route depends on is the real `Entry.admit`/`Entry.header_code`, not a
restatement of it -- run against the real pinned hashes in `data/games/gen3_{frlg,rr}/
engine_signals.json`.

Route (owner rulings 2026-09-23, docs/gen3/PLAN.md §0; docs/gen3/research/
p4_gen1_contract_map.md §3.6; C5-6 / owner ruling 24): a cartridge admitted as pack `gen3_frlg`
or `gen3_rr` by HASH or ANCHORS goes to `lua/gen3/run.lua`. The old client is archived (tag
archive/gen3-old-client): header-only admissions, Emerald and any other GBA cartridge are
refused by name, never handed to `game_detect`.
"""
from __future__ import annotations

import json
import os

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the launcher")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LUA = os.path.join(_REPO, "lua").replace("\\", "/")
_NEW_GEN3_CLIENT = "lua/gen3/run.lua"
_NEW_GEN1_CLIENT = "lua/gen1/run.lua"
_OLD_GEN3_CLIENT = "lua/clients/gen3_frlge_client.lua"  # deleted; see archive/gen3-old-client:lua/clients/


def _sha1(pack: str, title: str, kind: str) -> str:
    """A real pinned hash from the pack's own admission table (never invented)."""
    path = os.path.join(_REPO, "data", "games", pack, "engine_signals.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["titles"][title]["artifacts"][kind]["rom_sha1"]


_FR_CLEAN_SHA1 = _sha1("gen3_frlg", "firered", "clean")
_LG_CLEAN_SHA1 = _sha1("gen3_frlg", "leafgreen", "clean")
_RR_CLEAN_SHA1 = _sha1("gen3_rr", "radical_red", "clean")
_RR_COMPANION_SHA1 = _sha1("gen3_rr", "radical_red", "companion")


def _rom_gba(header_code: str = "\0\0\0\0", size: int = 0x200) -> bytes:
    """A cartridge image whose header game code ($AC, 4 bytes) holds `header_code`."""
    image = bytearray(size)
    image[0xAC:0xAC + 4] = header_code.encode("ascii")
    return bytes(image)


_GETSYSTEMID_THROWS = "__throws__"  # sentinel: emu.getsystemid() errors (distinct from nil)


def _run_launcher(system_id: str | None, rom: bytes, rom_hash: str = "0" * 40,
                  detected_game_id: str = "gen2_crystal", bizhawk: str = "2.11.1",
                  gb_title: str = "POKEMON RED") -> list[str]:
    """dofile `lua/slink.lua` with stub BizHawk globals; return the paths it dofile'd.

    `system_id` is the system id `emu.getsystemid()` returns; `None` makes it return Lua
    nil (a system BizHawk failed to identify, distinct from an error); the
    `_GETSYSTEMID_THROWS` sentinel makes it raise instead.

    `lua/gen1/entry.lua`, `lua/gen3/entry.lua` and `lua/json_codec.lua` are executed for
    real (the admission logic under test); every other dofile target is recorded and
    skipped, so no client ever actually starts.
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    loaded: list[str] = []

    def norm(path: str) -> str:
        rel = os.path.relpath(os.path.normpath(path), _REPO)
        return rel.replace("\\", "/")

    real_dofile = g.dofile
    _REAL_TARGETS = ("gen1/entry.lua", "gen3/entry.lua", "json_codec.lua")

    def fake_dofile(path):
        rel = norm(path)
        loaded.append(rel)
        if rel.endswith(_REAL_TARGETS):
            return real_dofile(path)
        return None

    def getsystemid():
        if system_id == _GETSYSTEMID_THROWS:
            raise RuntimeError("no core loaded")
        return system_id

    # $0134 (GB header title) and $A0/$AC (GBA header title/code) never overlap within this
    # small buffer's low offsets, so one fake ROM buffer serves both detectors: the GB path
    # only ever runs when system_id is GB/GBC/SGB, the GBA path only when it is GBA.
    gb_image = bytearray(max(len(rom), 0x144))
    gb_image[:len(rom)] = rom
    gb_image[0x134:0x134 + len(gb_title)] = gb_title.encode("ascii")
    full_rom = bytes(gb_image)

    g.dofile = fake_dofile
    g.emu = lua.table_from({"getsystemid": getsystemid})
    g.client = lua.table_from({"getversion": lambda: bizhawk})
    g.gameinfo = lua.table_from({"getromhash": lambda: rom_hash})
    g.memory = lua.table_from({
        "read_u8": lambda addr, domain: full_rom[addr] if 0 <= addr < len(full_rom) else 0,
    })
    g.console = lua.table_from({"log": lambda *a: None})
    # Only the console-tee's own log file is stubbed away (it would otherwise truncate
    # slink_lua.log in the repo root); Entry.admit legitimately reads real pack JSON through
    # io.open, so every other path must still go to the real filesystem.
    real_io_open = g.io.open

    def fake_io_open(path, *a):
        if str(path).endswith("slink_lua.log"):
            return None
        return real_io_open(path, *a)

    g.io.open = fake_io_open
    g.require = lambda name: lua.table_from({
        "detect": lambda: lua.table_from({
            "module": lua.table_from({"display_name": detected_game_id}),
            "variant": "x", "profile": lua.table_from({}), "game_id": detected_game_id,
        }),
    }) if name == "game_detect" else None

    real_dofile(f"{_LUA}/slink.lua")
    return loaded


def test_a_clean_firered_sha1_reaches_the_new_gen3_client():
    loaded = _run_launcher("GBA", _rom_gba(), rom_hash=_FR_CLEAN_SHA1)
    assert _NEW_GEN3_CLIENT in loaded, loaded
    assert _OLD_GEN3_CLIENT not in loaded, loaded


def test_a_clean_leafgreen_sha1_reaches_the_new_gen3_client():
    loaded = _run_launcher("GBA", _rom_gba(), rom_hash=_LG_CLEAN_SHA1)
    assert _NEW_GEN3_CLIENT in loaded, loaded
    assert _OLD_GEN3_CLIENT not in loaded, loaded


@pytest.mark.parametrize("rr_sha1", [_RR_COMPANION_SHA1, _RR_CLEAN_SHA1])
def test_a_radical_red_sha1_reaches_the_new_gen3_client(rr_sha1):
    """gen3_rr joined the routed set at G5 (C5-6)."""
    loaded = _run_launcher("GBA", _rom_gba(), rom_hash=rr_sha1)
    assert _NEW_GEN3_CLIENT in loaded, loaded
    assert _OLD_GEN3_CLIENT not in loaded, loaded


def test_an_unknown_bpre_hash_admitted_by_header_is_refused_by_name():
    """A header-named admission (admitted_by == 'header') is refused, not routed: RR and the
    Archipelago builds carry FireRed's header code too."""
    with pytest.raises(lupa.LuaError, match="Unsupported Gen 3 cartridge.*not a pinned cartridge"):
        _run_launcher("GBA", _rom_gba(header_code="BPRE"), rom_hash="f" * 40)


def test_emerald_is_refused_by_name():
    with pytest.raises(lupa.LuaError, match="Unsupported Gen 3 cartridge: Pokemon Emerald"):
        _run_launcher("GBA", _rom_gba(header_code="BPEE"), rom_hash="f" * 40)


def test_an_unknown_gba_cartridge_is_refused_and_never_reaches_game_detect():
    with pytest.raises(lupa.LuaError, match="Unsupported Gen 3 cartridge.*header AXVE"):
        _run_launcher("GBA", _rom_gba(header_code="AXVE"), rom_hash="f" * 40,
                      detected_game_id="gen3_frlge")


def test_a_gb_cartridge_still_takes_the_unchanged_gen1_route():
    loaded = _run_launcher("GB", _rom_gba(), rom_hash="f" * 40)
    assert _NEW_GEN1_CLIENT in loaded, loaded
    assert _NEW_GEN3_CLIENT not in loaded, loaded


def test_an_old_bizhawk_on_a_firered_cartridge_is_refused():
    with pytest.raises(lupa.LuaError, match="too old"):
        _run_launcher("GBA", _rom_gba(), rom_hash=_FR_CLEAN_SHA1, bizhawk="2.9.1")


def test_only_one_client_is_ever_loaded_for_a_routed_cartridge():
    loaded = _run_launcher("GBA", _rom_gba(), rom_hash=_FR_CLEAN_SHA1)
    clients = [p for p in loaded if "client" in p or p == _NEW_GEN3_CLIENT]
    assert clients == [_NEW_GEN3_CLIENT], f"expected exactly one client, got {clients}"


# ── fail-closed system identification (G5-ADMIT-HARDEN) ────────────────────────────────
#
# emu.getsystemid() erroring, or returning anything that is neither "GBA" nor one of the
# other systems game_detect is legitimately asked to route (GB/GBC/SGB for Gen 1, NDS for
# Gen 4/5), must refuse by name -- never silently fall through to game_detect, which has no
# row for an unidentified system and could otherwise misroute.

def test_a_getsystemid_error_is_refused_and_never_reaches_game_detect():
    with pytest.raises(lupa.LuaError, match="could not determine the loaded system"):
        _run_launcher(_GETSYSTEMID_THROWS, _rom_gba(), rom_hash=_FR_CLEAN_SHA1)


def test_a_nil_systemid_is_refused_and_never_reaches_game_detect():
    with pytest.raises(lupa.LuaError, match="could not determine the loaded system"):
        _run_launcher(None, _rom_gba(), rom_hash=_FR_CLEAN_SHA1)


def test_a_gbc_cartridge_still_falls_through_to_game_detect():
    """gb_title is deliberately not a Gen 1 title, so the Gen 1 route's own detector declines
    and this ROM keeps falling through to game_detect, same as before this card."""
    loaded = _run_launcher("GBC", _rom_gba(), rom_hash="f" * 40,
                           detected_game_id="gen2_crystal", gb_title="POKEMON CRYSTAL")
    assert _NEW_GEN1_CLIENT not in loaded
    assert _NEW_GEN3_CLIENT not in loaded
    assert "lua/clients/gen2_crystal_client.lua" in loaded


def test_an_nds_cartridge_still_falls_through_to_game_detect():
    loaded = _run_launcher("NDS", _rom_gba(), rom_hash="f" * 40,
                           detected_game_id="gen4_hgsspt", gb_title="POKEMON CRYSTAL")
    assert _NEW_GEN1_CLIENT not in loaded
    assert _NEW_GEN3_CLIENT not in loaded
    assert "lua/clients/gen4_hgsspt_client.lua" in loaded


def test_an_unrecognized_systemid_is_refused_and_never_reaches_game_detect():
    with pytest.raises(lupa.LuaError, match="could not determine the loaded system"):
        _run_launcher("SNES", _rom_gba(), rom_hash="f" * 40)
