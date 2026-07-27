"""Archipelago Red/Blue must resolve to an adapter, and vanilla must never look like AP.

Two independent defects made AP support non-functional, and the second hid behind the first.

1. Detection read CPU `0xFFDB` on the System Bus. On Game Boy that is HRAM — runtime
   scratch that is nonzero during ordinary play — so the "any nonzero byte means AP" test
   eventually fired on every VANILLA cart. The seed actually lives at ROM offset `0x5F22`
   (`Title_Seed`, per the AP world's rom.py), which is in bank 1 and therefore has to be
   read from the flat ROM domain: on the bus, `0x4000-0x7FFF` shows whichever bank happens
   to be mapped.

2. `rom_type_for_variant` returned the display string `"Red (AP)"`, which is not a key in
   `_ROM_TYPE_TO_GAME_ID`, so `game_id_for_rom_type` returned None and the hello never
   bound an adapter. rom_type is a key; the label is the server's own business.

The byte fixtures below are measured from the real ROMs and the real AP basepatch
(`basepatch_red.bsdiff4`, applied to the verified cartridge dump). The AP placeholder
decodes to "(NOT RANDOMIZED)" — the generator overwrites it with the actual seed name, so
detection must key on "this looks like text", never on any particular content.
"""
import os

import pytest

from server.adapters import game_id_for_rom_type, get_adapter, variant_label

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LUA_MODULE = os.path.join(REPO, "lua", "games", "gen1_rby.lua")

# --- measured fixtures -------------------------------------------------------------
# Vanilla Red AND Blue, ROM offset 0x5F22 (identical in both): executable code.
VANILLA_5F22 = bytes.fromhex("24cccb782018cb70202efe082850fe0d")
# Same offset after applying the shipped AP basepatch: "(NOT RANDOMIZED)".
AP_5F22 = bytes.fromhex("9a8d8e937f91808d838e8c889984839b")
# A generated multiworld overwrites it with the seed name, e.g. "AP12345 SEED".
AP_REAL_SEED = bytes([0x80, 0x8F, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0x7F,
                      0x92, 0x84, 0x84, 0x83, 0x50, 0x50, 0x50, 0x50])


def _detect(seed_bytes: bytes) -> bool:
    """Run the REAL `M.detect_archipelago` from lua/games/gen1_rby.lua against `seed_bytes`.

    Executing the shipped Lua rather than reimplementing it in Python is the point: a
    Python "mirror" of the rule is exactly the kind of thing that silently drifts from the
    code it claims to mirror. The stubbed `memory.read_u8` asserts the domain, so a
    regression back to the System Bus fails here too.
    """
    lupa = pytest.importorskip("lupa", reason="lupa needed to execute the Lua under test")
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute('_G.memory = { getmemorydomainlist = function() return {"ROM"} end }\n'
              '_G.console = { log = function() end }')
    with open(LUA_MODULE, encoding="utf-8") as f:
        game = L.eval("function(src) return load(src)() end")(f.read())
    L.globals().PAYLOAD = L.table_from(list(seed_bytes))
    L.execute("""
    _G.memory = {
      getmemorydomainlist = function() return {"System Bus", "ROM"} end,
      read_u8 = function(addr, dom)
        assert(dom == "ROM", "seed must be read from the flat ROM domain, got "..tostring(dom))
        return PAYLOAD[addr - 0x5F22 + 1] or 0
      end }
    """)
    return bool(game.detect_archipelago())


def test_vanilla_seed_slot_is_not_mistaken_for_ap():
    """The regression that shipped: vanilla self-identifying as Archipelago."""
    assert not _detect(VANILLA_5F22), (
        "vanilla ROM code at 0x5F22 scored as text — detection would misreport every "
        "vanilla cart as Archipelago"
    )


@pytest.mark.parametrize("seed,label", [(AP_5F22, "basepatch placeholder"),
                                        (AP_REAL_SEED, "generated seed name")])
def test_ap_seed_slot_is_detected(seed, label):
    assert _detect(seed), f"AP {label} at 0x5F22 was not recognised as text"


def test_detection_is_inert_without_a_rom_domain():
    """A core exposing no ROM domain must report "not AP" rather than guess."""
    lupa = pytest.importorskip("lupa")
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute('_G.memory = { getmemorydomainlist = function() return {"System Bus"} end }\n'
              '_G.console = { log = function() end }')
    with open(LUA_MODULE, encoding="utf-8") as f:
        game = L.eval("function(src) return load(src)() end")(f.read())
    assert game.detect_archipelago() is False


@pytest.mark.parametrize("rom_type", ["red_ap", "blue_ap"])
def test_ap_rom_types_resolve_to_the_gen1_adapter(rom_type):
    assert game_id_for_rom_type(rom_type) == "gen1_rby", (
        f"{rom_type!r} does not map to a game_id — the hello cannot bind an adapter"
    )


@pytest.mark.parametrize("rom_type,expected", [("red_ap", "Red (AP)"), ("blue_ap", "Blue (AP)")])
def test_ap_rom_types_have_display_labels(rom_type, expected):
    assert variant_label(rom_type) == expected


def test_display_label_is_not_used_as_a_rom_type():
    """"Red (AP)" is a label. If it ever comes back as a rom_type it resolves to nothing."""
    assert game_id_for_rom_type("Red (AP)") is None


@pytest.mark.parametrize("rom_type,expected_variant", [
    ("red_ap", "red"), ("blue_ap", "blue"),
])
def test_ap_inherits_its_base_games_encounter_tables(rom_type, expected_variant):
    """AP randomises placement, not the wild tables, so it uses the base game's."""
    adapter = get_adapter("gen1_rby", rom_type=rom_type)
    assert adapter._enc_variant == expected_variant


# --- WRAM relocation -----------------------------------------------------------------
# Archipelago is built from Alchav's fork, which adds ~121 lines of WRAM for item/event
# tracking. 861 of the 2171 symbols shared with vanilla move. The AP profile used to
# inherit every vanilla address, so an AP run read the wrong byte for its map, badges,
# trainer id, PC box and enemy party. Addresses verified against `alchav_pokered` by
# tools/verify_profile_addresses.py; the deltas are asserted here so a silent revert to
# "AP is just vanilla with a label" fails loudly.
RELOCATED = {
    "MAP_ID_ADDR": (0xD35E, 0xD436),
    "PLAYER_ID_ADDR": (0xD359, 0xD431),
    "BADGES_ADDR": (0xD356, 0xD42E),
    "ENEMY_BASE_ADDR": (0xD8A4, 0xD892),
    "ENEMY_COUNT_ADDR": (0xD89C, 0xD88A),
    "BOX_BASE_ADDR": (0xDA96, 0xDAA1),
    "BOX_COUNT_ADDR": (0xDA80, 0xDA8B),
}
# Deliberately NOT relocated — the party struct and battle state stay put.
INHERITED = ("PARTY_BASE_ADDR", "PARTY_COUNT_ADDR", "BATTLE_FLAG_ADDR",
             "TRAINER_CLASS_ADDR")


@pytest.fixture(scope="module")
def profiles():
    lupa = pytest.importorskip("lupa")
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute('_G.memory = { getmemorydomainlist = function() return {"ROM"} end }\n'
              '_G.console = { log = function() end }')
    with open(LUA_MODULE, encoding="utf-8") as f:
        return L.eval("function(s) return load(s)() end")(f.read()).PROFILES


@pytest.mark.parametrize("field,addrs", sorted(RELOCATED.items()))
def test_ap_profile_uses_relocated_addresses(profiles, field, addrs):
    vanilla, ap = addrs
    assert int(profiles.red[field]) == vanilla, f"vanilla red {field} moved unexpectedly"
    assert int(profiles.red_ap[field]) == ap, (
        f"red_ap {field} should be 0x{ap:04X} (Alchav fork), not 0x{int(profiles.red_ap[field]):04X}"
    )


@pytest.mark.parametrize("field", INHERITED)
def test_ap_profile_inherits_unmoved_addresses(profiles, field):
    assert int(profiles.red_ap[field]) == int(profiles.red[field]), (
        f"{field} did not move in the AP fork — it should still be inherited, not overridden"
    )


def test_blue_ap_matches_red_ap(profiles):
    """Blue's AP build shares Red's layout, as vanilla Blue shares vanilla Red's."""
    for field in RELOCATED:
        assert int(profiles.blue_ap[field]) == int(profiles.red_ap[field])
