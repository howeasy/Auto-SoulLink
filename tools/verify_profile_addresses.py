"""Verify effective Gen 1 profiles against canonical source, symbols and ROM bytes.

Gen 1 loads all five runtime profiles, including aliases, inherited values,
decimal constants and nested leaves. Every field is a verified symbol,
structure, ROM-byte check, source-derived invariant, or intentionally nil.
Missing evidence and unknown fields fail. --gen1-only excludes the older Gen 2
hex-literal audit, whose offset-only SKIP rows remain outside this release gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

from verify_gen1_constants import GEN1_REPOS, SOURCE_ROOT, EvidenceError, profile_contracts

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE_GEN1 = REPO_ROOT / "lua" / "games" / "gen1_rby.lua"
PROFILE_GEN2 = REPO_ROOT / "lua" / "games" / "gen2_crystal.lua"
PRET_SYMS = REPO_ROOT / "data" / "pret_syms.json"

# (variant, lua_field_name) → (pret_repo, pret_symbol)
# Variant names: "red", "blue", "yellow", "crystal"
# pret_repos:    "pokered", "pokeyellow", "pokecrystal"
# Blue and Red share the same Lua block (M.PROFILES.blue = M.PROFILES.red), so
# blue verification reuses pokered symbols.
#
# Fields with NO expected pret symbol get an explicit None — they're either
# derived offsets (dv_offset_1, party_struct_size), runtime sentinels
# (is_egg_species), or placeholders we don't auto-verify.
PROFILE_TO_PRET: dict[tuple[str, str], tuple[str, str] | None] = {}


def _add(variant: str, repo: str, mapping: dict[str, str | None]) -> None:
    for field, sym in mapping.items():
        PROFILE_TO_PRET[(variant, field)] = (repo, sym) if sym else None


# ── Red / Blue (pokered) ─────────────────────────────────────────────────────
_RED_MAP: dict[str, str | None] = {
    "PARTY_COUNT_ADDR": "wPartyCount",
    "PARTY_SPECIES_ADDR": "wPartySpecies",
    "PARTY_BASE_ADDR": "wPartyMon1",
    "PARTY_OT_NAMES_ADDR": "wPartyMonOT",
    "PARTY_NICKS_ADDR": "wPartyMonNicks",
    "party_struct_size": None,  # constant, not an address
    "ENEMY_COUNT_ADDR": "wEnemyPartyCount",
    "ENEMY_BASE_ADDR": "wEnemyMons",
    "ENEMY_SPECIES_LIST_ADDR": "wEnemyPartySpecies",
    "BOX_COUNT_ADDR": "wBoxCount",
    "BOX_SPECIES_ADDR": "wBoxSpecies",
    "BOX_BASE_ADDR": "wBoxMon1",
    "BOX_OT_NAMES_ADDR": "wBoxMonOT",
    "BOX_NICKS_ADDR": "wBoxMonNicks",
    "box_struct_size": None,
    "box_max_mons": None,
    "BAG_COUNT_ADDR": "wNumBagItems",
    "BAG_ITEMS_ADDR": "wBagItems",
    "bag_max_items": None,
    "BATTLE_FLAG_ADDR": "wIsInBattle",
    # Rival Team Swap / Explode Mode (Gen 1 does both from RAM, no ROM patch).
    "CUR_OPPONENT_ADDR": "wCurOpponent",
    "ENEMY_OT_NAMES_ADDR": "wEnemyMonOT",
    "ENEMY_NICKS_ADDR": "wEnemyMonNicks",
    "PLAYER_SELECTED_MOVE_ADDR": "wPlayerSelectedMove",
    "PLAYER_MOVE_LIST_INDEX_ADDR": "wPlayerMoveListIndex",
    "PLAYER_MON_NUMBER_ADDR": "wPlayerMonNumber",
    "BATTLE_MON_MOVES_ADDR": "wBattleMonMoves",
    "BATTLE_MON_PP_ADDR": "wBattleMonPP",
    # What MainInBattleLoop actually reads for the faint check. force_faint writes
    # this as well as the party struct — see M.forceFaint in lua/memory_gb.lua.
    "BATTLE_MON_HP_ADDR": "wBattleMonHP",
    "JOY_IGNORE_ADDR": "wJoyIgnore",
    "FONT_LOADED_ADDR": "wFontLoaded",
    "CURRENT_BOX_NUM_ADDR": "wCurrentBoxNum",

    # The game's own wild-encounter preconditions (see M.isInGrass).
    "TILE_MAP_ADDR": "wTileMap",
    "GRASS_TILE_ADDR": "wGrassTile",
    "GRASS_RATE_ADDR": "wGrassRate",
    "STATUS_FLAGS_4_ADDR": "wStatusFlags4",
    "MOVEMENT_FLAGS_ADDR": "wMovementFlags",

    # ── Memorial-box SRAM guard (see M.protectSramBoxes) ──────────────────────
    # This one IS worth verifying: it is the same wCurrentBoxNum the client reads, and the
    # guard is wrong in a save-destroying way if it points anywhere else.
    "changed_boxes_addr": "wCurrentBoxNum",
    "changed_boxes_bit": None,          # BIT_HAS_CHANGED_BOXES = 7, a constant
    "checksum_offset": None,            # offset within an SRAM bank, not an address
    "box_len": None,                    # wBoxDataEnd - wBoxDataStart, a size
    "boxes_per_bank": None,             # NUM_BOXES / 2, a constant
    # $DEE2 is the free WRAM the companion patch claims — it has no pret symbol precisely
    # because pret's linker reports it as empty (WRAM0 TOTAL EMPTY $001E).
    "companion_patch_mailbox": None,
    # A flat ROM offset, not a WRAM symbol. Verified far more strongly at runtime: the
    # writes gate reads the actual instruction bytes there and asserts CB 7E CC.
    "change_box_bit_test_rom_addr": None,
    "ENEMY_MON_SPECIES_ADDR": "wEnemyMon",
    "ENEMY_MON_HP_ADDR": "wEnemyMonHP",
    "ENEMY_MON_LEVEL_ADDR": "wEnemyMonLevel",
    "ENEMY_MON_MAXHP_ADDR": "wEnemyMonMaxHP",
    "MAP_ID_ADDR": "wCurMap",
    "PLAYER_NAME_ADDR": "wPlayerName",
    "PLAYER_ID_ADDR": "wPlayerID",
    "dv_offset_1": None,
    "dv_offset_2": None,
    "otid_offset": None,
    "species_offset": None,
    "hp_offset": None,
    "maxhp_offset": None,
    "level_offset": None,
    # Derived offset, not an address. Gen 1's box struct keeps BoxLevel at +0x03
    # (pret wBoxMon1BoxLevel) while the party level lives at +0x21.
    "box_level_offset": None,
    # Derived offset: start of the computed stat block (wPartyMon1Attack, party+0x24).
    "stats_offset": None,
    "status_offset": None,
    "enemy_status_offset": None,
    "ball_item_ids": None,
    "BADGES_ADDR": "wObtainedBadges",
    "PLAYER_STAT_STAGES_ADDR": "wPlayerMonAttackMod",
    "ENEMY_STAT_STAGES_ADDR": "wEnemyMonAttackMod",
    "stat_stages_count": None,
    "stat_stages_layout": None,
    "moves_offset": None,
    "pp_offset": None,
    "pp_encoding": None,
    "ENEMY_BATTLE_MOVES_ADDR": "wEnemyMonMoves",
    "ENEMY_BATTLE_PP_ADDR": "wEnemyMonPP",
    "enemy_battle_pp_encoding": None,
    "TRAINER_CLASS_ADDR": "wTrainerClass",
    "TRAINER_ID_ADDR": "wTrainerNo",
    # SFX dispatch. This IS a pret WRAM symbol, so verify it rather than skipping.
    # It was skipped, and that is how Gen 2 shipped 0xC2BD (wCryTracks) under a comment
    # naming wMusicID. Gen 1's is nil (no RAM sound trigger exists there), and a nil profile
    # value is skipped anyway, so mapping it costs Gen 1 nothing.
    "SFX_DISPATCH_ADDR": "wMusicID",
    "capture":   None,
    "gift":      None,
    "faint":     None,
    "whiteout":  None,
    "no_catch":  None,
    "success":   None,
    "failure":   None,
    "boo":       None,
    "shiny":     None,
}
_add("red", "pokered", _RED_MAP)
_add("blue", "pokered", _RED_MAP)  # blue shares red profile in Lua

# ── Archipelago Red/Blue (Alchav's fork, NOT pret) ────────────────────────────
# The AP fork adds WRAM for item/event tracking, moving 861 of 2171 shared symbols —
# wCurMap +216, wEnemyMons -18, the box block +11. Same field names, different repo, so
# the AP profiles get verified against `alchav_pokered` instead of `pokered`. Without
# this the AP blocks would be unverified and free to rot back into inheriting vanilla.
# blue_ap inherits red_ap, exactly as vanilla blue inherits red, so only red_ap is listed.
_add("red_ap", "alchav_pokered", _RED_MAP)
# The fork predates pret's symbol rename, so a handful of fields answer to the OLD name.
# Without the override the lookup misses, the field is reported WARN instead of FAIL, and an
# address that is simply absent from the profile looks like a deliberate opt-out.
PROFILE_TO_PRET[("red_ap", "MOVEMENT_FLAGS_ADDR")] = ("alchav_pokered", "wd736")
_add("blue_ap", "alchav_pokered", _RED_MAP)
PROFILE_TO_PRET[("blue_ap", "MOVEMENT_FLAGS_ADDR")] = ("alchav_pokered", "wd736")

# ── Yellow (pokeyellow) ───────────────────────────────────────────────────────
# Same field-name shape as Red/Blue.
_add("yellow", "pokeyellow", _RED_MAP)

# ── Crystal (pokecrystal) ─────────────────────────────────────────────────────
_CRYSTAL_MAP: dict[str, str | None] = {
    "PARTY_COUNT_ADDR": "wPartyCount",
    "PARTY_SPECIES_ADDR": "wPartySpecies",
    "PARTY_BASE_ADDR": "wPartyMon1",
    "PARTY_OT_NAMES_ADDR": "wPartyMonOTs",
    "PARTY_NICKS_ADDR": "wPartyMonNicknames",
    "party_struct_size": None,
    "ENEMY_COUNT_ADDR": "wOTPartyCount",
    "ENEMY_BASE_ADDR": "wOTPartyMon1",
    "ENEMY_SPECIES_LIST_ADDR": "wOTPartySpecies",
    "BOX_COUNT_ADDR": None,  # SRAM in Gen 2 — not in WRAM .sym
    "BOX_SPECIES_ADDR": None,
    "BOX_BASE_ADDR": None,
    "BOX_OT_NAMES_ADDR": None,
    "BOX_NICKS_ADDR": None,
    "box_struct_size": None,
    "box_max_mons": None,
    "box_in_sram": None,
    "sram_bank": None,
    "BAG_COUNT_ADDR": "wNumBalls",
    "BAG_ITEMS_ADDR": "wBalls",
    "bag_max_items": None,
    "BATTLE_FLAG_ADDR": "wBattleMode",
    "ENEMY_MON_SPECIES_ADDR": "wEnemyMon",
    "ENEMY_MON_HP_ADDR": "wEnemyMonHP",
    "ENEMY_MON_LEVEL_ADDR": "wEnemyMonLevel",
    "ENEMY_MON_MAXHP_ADDR": "wEnemyMonMaxHP",
    "MAP_GROUP_ADDR": "wMapGroup",
    "MAP_NUMBER_ADDR": "wMapNumber",
    "PLAYER_ID_ADDR": "wPlayerID",
    "PLAYER_NAME_ADDR": "wPlayerName",
    "BADGES_ADDR": "wJohtoBadges",
    "KANTO_BADGES_ADDR": "wKantoBadges",
    "species_offset": None,
    "held_item_offset": None,
    "otid_offset": None,
    "dv_offset_1": None,
    "dv_offset_2": None,
    "level_offset": None,
    "hp_offset": None,
    "maxhp_offset": None,
    "status_offset": None,
    "enemy_status_offset": None,
    # Derived offsets into party_struct, not addresses. Gen 2 SPLIT Special, so spdef_offset
    # is a distinct field rather than Gen 1's alias of spAtk.
    "stats_offset": None,
    "spdef_offset": None,
    "CURRENT_BOX_NUM_ADDR": "wCurBox",
    # Gen 2 has no wJoyIgnore. The measured equivalent is wScriptRunning — see the
    # profile comment for the three candidates that looked right and were not.
    "JOY_IGNORE_ADDR": "wScriptRunning",
    "box_species_offset": None,
    "box_held_item_offset": None,
    "box_otid_offset": None,
    "box_dv_offset_1": None,
    "box_dv_offset_2": None,
    "box_level_offset": None,
    "ball_item_ids": None,
    "generation": None,
    "uses_map_group": None,
    "is_egg_species": None,
    "PLAYER_STAT_STAGES_ADDR": "wPlayerStatLevels",
    "ENEMY_STAT_STAGES_ADDR": "wEnemyStatLevels",
    "stat_stages_count": None,
    "stat_stages_layout": None,
    "moves_offset": None,
    "pp_offset": None,
    "pp_encoding": None,
    "ENEMY_BATTLE_MOVES_ADDR": "wEnemyMonMoves",
    "ENEMY_BATTLE_PP_ADDR": "wEnemyMonPP",
    "enemy_battle_pp_encoding": None,
    "TRAINER_CLASS_ADDR": "wOtherTrainerClass",
    "TRAINER_ID_ADDR": "wOtherTrainerID",
    # SFX dispatch — a real symbol, verified. See the Gen 1 table for why this is not skipped.
    "SFX_DISPATCH_ADDR": "wMusicID",
    "capture":   None,
    "gift":      None,
    "faint":     None,
    "whiteout":  None,
    "no_catch":  None,
    "success":   None,
    "failure":   None,
    "boo":       None,
    "shiny":     None,
}
_add("crystal", "pokecrystal", _CRYSTAL_MAP)

# ── Gold / Silver (pokegold; _GOLD and _SILVER share WRAM layout) ────────────
# Maps to the same pret symbols as crystal, but resolved against pokegold.sym
# (which has different absolute addresses because Crystal added Mobile / Phone /
# Time Capsule sections that shifted WRAMX bank 1 layout).
_GOLD_MAP = dict(_CRYSTAL_MAP)
# Active box lives in SRAM; the same sBox* symbol names work in pokegold too.
_GOLD_MAP.update({
    "BOX_COUNT_ADDR": "sBoxCount",
    "BOX_SPECIES_ADDR": "sBoxSpecies",
    "BOX_BASE_ADDR": "sBoxMons",
    "BOX_OT_NAMES_ADDR": "sBoxMonOTs",
    "BOX_NICKS_ADDR": "sBoxMonNicknames",
})
_add("gold", "pokegold", _GOLD_MAP)
_add("silver", "pokegold", _GOLD_MAP)

# Also enable SRAM checks for crystal now that build_pret_syms ships SRAM syms
_CRYSTAL_SRAM_OVERRIDES = {
    "BOX_COUNT_ADDR": "sBoxCount",
    "BOX_SPECIES_ADDR": "sBoxSpecies",
    "BOX_BASE_ADDR": "sBoxMons",
    "BOX_OT_NAMES_ADDR": "sBoxMonOTs",
    "BOX_NICKS_ADDR": "sBoxMonNicknames",
}
for field, sym in _CRYSTAL_SRAM_OVERRIDES.items():
    PROFILE_TO_PRET[("crystal", field)] = ("pokecrystal", sym)


# ── Lua profile parser ───────────────────────────────────────────────────────

_VARIANT_BLOCK_RE = re.compile(r'(\b\w+)\s*=\s*\{', re.MULTILINE)
_FIELD_RE = re.compile(r'^\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+)', re.MULTILINE)


def _extract_variant_addresses(lua_path: pathlib.Path) -> dict[str, dict[str, int]]:
    """Load complete effective Gen 1 profiles, or legacy Gen 2 hex literals.

    Gen 2 retains the previous parser; its booleans, strings and tables are ignored.

    Variant blocks are matched by walking the file: each top-level `<name> = {`
    inside `M.PROFILES = { ... }` starts a new variant; we track brace depth
    to know when the variant block closes.
    """
    if lua_path.name == "gen1_rby.lua":
        return load_gen1_profiles(lua_path)
    text = lua_path.read_text(encoding="utf-8")

    # Find the M.PROFILES = { ... } block
    start = text.find("M.PROFILES")
    if start < 0:
        return {}
    # Move to the opening brace
    brace_open = text.find("{", start)
    if brace_open < 0:
        return {}

    out: dict[str, dict[str, int]] = {}
    depth = 0
    i = brace_open
    current_variant: str | None = None
    current_fields: dict[str, int] = {}
    variant_block_start = -1

    # Walk character by character, tracking { } depth.
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
            if depth == 2 and current_variant is None:
                # Variant block opened — find which variant by scanning backwards
                # for `<name> = {` on the line above.
                preceding = text[max(0, i - 200):i]
                m = re.search(r'(\w+)\s*=\s*$', preceding)
                if m:
                    current_variant = m.group(1)
                    current_fields = {}
                    variant_block_start = i + 1
        elif c == "}":
            depth -= 1
            if depth == 1 and current_variant is not None:
                # Variant block closed — parse fields
                block_text = text[variant_block_start:i]
                for field_match in _FIELD_RE.finditer(block_text):
                    fname = field_match.group(1)
                    fval = int(field_match.group(2), 16)
                    current_fields[fname] = fval
                out[current_variant] = current_fields
                current_variant = None
            elif depth == 0:
                break
        i += 1
    return out


def load_gen1_profiles(lua_path: pathlib.Path = PROFILE_GEN1) -> dict[str, dict]:
    """Load effective profiles, including aliases, inherited values and nested leaves.

    A regex over hexadecimal literals misses decimal addresses, sizes, inline table
    members and metatable inheritance. Execute this side-effect-free game module in
    Lua, inspect the effective values and validate every leaf, regardless of syntax.
    Missing Lua support is a dependency failure, never a skipped validation.
    """
    from lupa import LuaRuntime, lua_type

    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute(lua_path.read_text(encoding="utf-8"))
    effective = lua.eval("""function(t)
        local out = {}
        local function copy(v, seen)
            if seen[v] then error('profile inheritance cycle') end
            seen[v] = true
            local mt = getmetatable(v)
            if mt and mt.__index then
                if type(mt.__index) ~= 'table' then error('uninspectable profile inheritance') end
                copy(mt.__index, seen)
            end
            for k, value in pairs(v) do out[k] = value end
            seen[v] = nil
        end
        copy(t, {})
        return out
    end""")

    def flatten(table, prefix=""):
        out = {}
        for key, value in effective(table).items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if lua_type(value) == "table":
                children = flatten(value, path)
                if not children:
                    out[path] = {}  # Empty, unsupported tables must not disappear.
                out.update(children)
            else:
                out[path] = value
        return out

    actual = set(module.PROFILES.keys())
    if actual != set(GEN1_REPOS):
        raise EvidenceError(f"Gen 1 variant inventory changed: {sorted(actual)}")
    return {variant: flatten(module.PROFILES[variant]) for variant in GEN1_REPOS}


def _rom_evidence(variant: str) -> tuple[bytes, dict[str, int]]:
    names = {
        "red": "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
        "blue": "Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
        "yellow": "Pokemon - Yellow Version (USA, Europe).gbc",
    }
    clean_hashes = {
        "red": "ea9bcae617fdf159b045185467ae58b2e4a48b9a",
        "blue": "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2",
        "yellow": "cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1",
    }
    repo = {"red": "pokered", "blue": "pokeblue", "yellow": "pokeyellow"}[variant]
    artifact = json.loads((REPO_ROOT / "data/pret_rom_syms.json").read_text(encoding="utf-8"))[repo]
    candidates = (REPO_ROOT / names[variant], REPO_ROOT / "patch/build" / f"gen1_{variant}.{'gbc' if variant == 'yellow' else 'gb'}")
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise EvidenceError(f"missing legally supplied clean {variant} ROM")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != clean_hashes[variant] or artifact["rom_sha1"] != clean_hashes[variant]:
        raise EvidenceError(f"{variant}: ROM/symbol identity does not match supported clean SHA-1")
    return rom, artifact["symbols"]


def _flat(encoded: int) -> int:
    bank, addr = encoded >> 16, encoded & 0xFFFF
    if bank == 0 and addr < 0x4000:
        return addr
    if bank > 0 and 0x4000 <= addr < 0x8000:
        return bank * 0x4000 + addr - 0x4000
    raise EvidenceError(f"invalid bank-qualified ROM symbol: {encoded:#x}")


def verify_checkpoint_references(repo: pathlib.Path) -> None:
    """Reject menu/data references to the two positive main-loop entry points."""
    pattern = r'\bOverworldLoop(?:LessDelay)?\b'
    reference = re.compile(pattern)
    permitted = re.compile(r'(?:OverworldLoop(?:LessDelay)?::|jp\s+(?:(?:z|nz|c|nc),\s*)?OverworldLoop(?:LessDelay)?)$')
    lines = []
    if binary := shutil.which("rg"):
        result = subprocess.run([binary, "--json", "--hidden", "--no-ignore", "--glob", "*.asm",
                                 "--glob", "!.git/**", pattern, str(repo)],
                                capture_output=True, text=True, encoding="utf-8", check=False)
        if result.returncode not in (0, 1):
            raise EvidenceError("checkpoint reference search failed: " + result.stderr.strip())
        for record in result.stdout.splitlines():
            data = json.loads(record)
            if data["type"] == "match":
                lines.append((pathlib.Path(data["data"]["path"]["text"]), data["data"]["lines"]["text"]))
    else:
        for path in repo.rglob("*.asm"):
            lines.extend((path, line) for line in path.read_text(encoding="utf-8").splitlines()
                         if reference.search(line))
    for path, line in lines:
        code = line.split(";", 1)[0].strip()
        if reference.search(code) and (path != repo / "home/overworld.asm" or not permitted.fullmatch(code)):
            raise EvidenceError(f"non-main-loop reference to the admitted checkpoint: {path.relative_to(repo)}: {code}")


def write_safe_contracts(variant: str, symbols: dict[str, int]) -> dict:
    """Prove the only two admitted caller PCs and the native interrupt stack shape."""
    repo = SOURCE_ROOT / GEN1_REPOS[variant]
    rom, rom_syms = _rom_evidence(variant)
    names = {"vblank_entry": "VBlank", "delay_frame": "DelayFrame",
             "overworld_loop": "OverworldLoop", "overworld_loop_less_delay": "OverworldLoopLessDelay"}
    addresses = {field: _flat(rom_syms[label]) for field, label in names.items()}
    if any(address >= 0x4000 for address in addresses.values()):
        raise EvidenceError("main-loop checkpoint must be entirely ROM0")
    header = (repo / "home/header.asm").read_text(encoding="utf-8")
    vector = re.search(r'SECTION "vblank", ROM0\[\$(\w+)\]\s+jp VBlank', header)
    stack = re.search(r'org\s+\$(\w+)\s+"Stack"', (repo / "layout.link").read_text(encoding="utf-8"), re.I)
    if not vector or not stack:
        raise EvidenceError("missing native VBlank vector or Stack allocation")
    irq = int(vector[1], 16)
    delay = addresses["delay_frame"]
    flag = symbols["hVBlankOccurred"]
    if not 0xFF80 <= flag < 0xFFFF:
        raise EvidenceError("VBlank flag is not HRAM")
    anchors = {
        irq: bytes((0xC3, addresses["vblank_entry"] & 255, addresses["vblank_entry"] >> 8)),
        delay: bytes((0x3E, 1, 0xE0, flag & 255, 0x76, 0xF0, flag & 255, 0xA7)),
        addresses["overworld_loop"]: bytes((0xCD, delay & 255, delay >> 8)) * 2,
    }
    if addresses["overworld_loop_less_delay"] != addresses["overworld_loop"] + 3:
        raise EvidenceError("overworld frame calls are not adjacent")
    if any(rom[address:address + len(expected)] != expected for address, expected in anchors.items()):
        raise EvidenceError("native interrupt, HALT/resume or main-loop CALL bytes differ")
    source = (repo / "home/overworld.asm").read_text(encoding="utf-8")
    if not re.search(r'OverworldLoop::\s+call DelayFrame\s+OverworldLoopLessDelay::\s+call DelayFrame', source):
        raise EvidenceError("missing source-level main-loop checkpoint")
    # These are main-loop entry points, never subroutines called by a menu.
    # A new reference in any other routine/data table invalidates that invariant.
    verify_checkpoint_references(repo)
    serial = (repo / "constants/serial_constants.asm").read_text(encoding="utf-8")
    constants = {}
    for field, name in {"link_none": "LINK_STATE_NONE", "disconnected_serial": "CONNECTION_NOT_ESTABLISHED"}.items():
        value = re.search(rf'DEF {name}\s+EQU \$([0-9a-f]+)', serial, re.I)
        if not value:
            raise EvidenceError(f"missing source serial constant {name}")
        constants[field] = (int(value[1], 16), "invariant", f"serial_constants.asm:{name}")
    values = {field: (address, "rom_bytes", f"{names[field]} + exact ROM0 instruction anchors")
              for field, address in addresses.items()}
    values.update({
        "version": ("gen1-main-loop-v1", "invariant", "versioned RBY CPU checkpoint contract"),
        "irq_vector": (irq, "rom_bytes", "home/header.asm VBlank vector + JP bytes"),
        "stack_min": (int(stack[1], 16), "invariant", "layout.link Stack origin"),
        "stack_end": (symbols["wStack"], "symbol", "ram/wram.asm:wStack, final allocated stack byte"),
        **constants,
    })
    for field, label in {"vblank_flag": "hVBlankOccurred", "link_state": "wLinkState",
                         "serial_status": "hSerialConnectionStatus", "entering_cable_club": "wEnteringCableClub"}.items():
        values[field] = (symbols[label], "symbol", label)
    values["printer_open"] = ((symbols["wPrinterConnectionOpen"], "symbol", "wPrinterConnectionOpen")
                              if variant == "yellow" else (None, "unsupported", "no printer on R/B"))
    return {f"write_safe.{field}": contract for field, contract in values.items()}


def verify_gen1(profiles: dict[str, dict], pret_syms: dict[str, dict[str, int]]) -> list[dict]:
    """Five accepted dispositions, with zero WARN/SKIP paths for Gen 1."""
    rows = []
    for variant, fields in profiles.items():
        repo = GEN1_REPOS[variant]
        symbols = pret_syms.get(repo, {})
        errors = None
        try:
            contracts = profile_contracts(SOURCE_ROOT / repo, symbols)
            if not variant.endswith("_ap"):
                contracts.update(write_safe_contracts(variant, symbols))
        except (OSError, KeyError, ValueError) as exc:
            contracts, errors = {}, str(exc)
        if errors is not None:
            rows.append({"variant": variant, "field": "source_contracts", "severity": "FAIL", "profile_addr": None, "pret_addr": None, "pret_symbol": None, "category": None, "note": errors})
        unsupported = {"SFX_DISPATCH_ADDR"}
        if variant.endswith("_ap"):
            unsupported |= {"STATUS_FLAGS_4_ADDR", "companion_patch_mailbox", "change_box_bit_test_rom_addr", "sfx_ids", "write_safe"}
        elif variant == "yellow":
            unsupported.add("companion_patch_mailbox")
        required = {key for key, symbol in _RED_MAP.items() if symbol is not None and key != "changed_boxes_addr"}
        required.add("sram_box_layout.changed_boxes_addr")
        required |= set(contracts)
        if not variant.endswith("_ap"):
            required |= {"change_box_bit_test_rom_addr"}
            if variant != "yellow":
                required.add("companion_patch_mailbox")
            required |= {f"sfx_ids.{event}" for event in ("capture", "gift", "faint", "whiteout", "no_catch", "success", "failure", "boo", "shiny")}
        all_fields = set(fields) | required | unsupported
        for field in sorted(all_fields):
            actual = fields.get(field)
            expected, category, evidence = None, None, ""
            try:
                if field in unsupported or field.split(".")[0] in unsupported:
                    category, evidence = "unsupported", "intentionally unsupported; must be nil"
                    if actual is not None:
                        raise EvidenceError("unsupported field must be nil, not inherited or false")
                elif field == "variant_label":
                    expected = {"red_ap": "Red (AP)", "blue_ap": "Blue (AP)"}[variant]
                    category, evidence = "invariant", "explicit variant identity label"
                elif field in contracts:
                    expected, category, evidence = contracts[field]
                elif field == "sram_box_layout.changed_boxes_addr":
                    expected, category, evidence = symbols["wCurrentBoxNum"], "symbol", f"{repo}:wCurrentBoxNum"
                elif PROFILE_TO_PRET.get((variant, field)) is not None:
                    _, symbol = PROFILE_TO_PRET[(variant, field)]
                    expected, category, evidence = symbols[symbol], "symbol", f"{repo}:{symbol}"
                elif field == "companion_patch_mailbox":
                    expected, category = symbols["wBoxDataEnd"], "invariant"
                    evidence = "pokered wBoxDataEnd..layout.link Stack origin ($DF00): 30 unallocated bytes"
                    layout = (SOURCE_ROOT / repo / "layout.link").read_text(encoding="utf-8")
                    if not re.search(r'"Current Box Data"\s+org\s+\$df00\s+"Stack"', layout, re.I) or expected + 30 != 0xDF00:
                        raise EvidenceError("30-byte companion mailbox is not proven outside canonical allocations")
                elif field == "change_box_bit_test_rom_addr":
                    rom, rom_syms = _rom_evidence(variant)
                    start = _flat(rom_syms["ChangeBox"])
                    # Match the source's bit 7,[hl]; call z,EmptyAllSRAMBoxes with
                    # the exact bank-qualified call target, within this routine.
                    target = rom_syms["EmptyAllSRAMBoxes"]
                    if target >> 16 != rom_syms["ChangeBox"] >> 16:
                        raise EvidenceError("ChangeBox call crosses a bank")
                    pattern = bytes((0xCB, 0x7E, 0xCC, target & 255, (target >> 8) & 255))
                    hits = [start + i for i in range(64) if rom[start + i:start + i + 5] == pattern]
                    if len(hits) != 1:
                        raise EvidenceError(f"ChangeBox expected-byte anchor is ambiguous/missing: {hits}")
                    expected, category, evidence = hits[0], "rom_bytes", "ChangeBox label + CB7ECC + EmptyAllSRAMBoxes call bytes"
                elif field.startswith("sfx_ids."):
                    _rom, rom_syms = _rom_evidence(variant)
                    event = field.split(".")[1]
                    labels = {"capture": "Get_Item2", "gift": "Get_Item2", "shiny": "Get_Item2", "success": "Heal_HP", "faint": "Tink", "whiteout": "Tink", "no_catch": "Tink", "failure": "Tink", "boo": "Tink"}
                    name = labels[event]
                    ids = []
                    for bank in (1, 2, 3):
                        header = rom_syms[f"SFX_Headers_{bank}"]
                        sound = rom_syms[f"SFX_{name}_{bank}"]
                        if header >> 16 != sound >> 16 or (sound - header) % 3:
                            raise EvidenceError("SFX header is not a bank-local three-byte entry")
                        ids.append((sound - header) // 3)
                    if len(set(ids)) != 1:
                        raise EvidenceError("sound id differs between engine audio banks")
                    expected, category, evidence = ids[0], "invariant", f"SFX_{name}_1/2/3 label deltas / 3"
                else:
                    raise EvidenceError(errors or "active field has no source-backed contract")
                if actual != expected:
                    raise EvidenceError(f"observed={actual!r}; expected={expected!r}")
                severity, note = "OK", evidence
            except (OSError, KeyError, ValueError) as exc:
                severity, note = "FAIL", str(exc)
            rows.append({"variant": variant, "field": field, "severity": severity,
                         "profile_addr": actual, "pret_addr": expected, "pret_symbol": evidence,
                         "category": category, "note": note})
    return rows


# ── Verification logic ──────────────────────────────────────────────────────

def verify(
    profile_addrs: dict[str, dict[str, int]],
    pret_syms: dict[str, dict[str, int]],
) -> list[dict]:
    """Return a list of result rows: {variant, field, severity, profile_addr,
    pret_addr, pret_symbol, note}. severity is "OK" / "FAIL" / "WARN" / "SKIP"."""
    results: list[dict] = []
    gen1 = {name: fields for name, fields in profile_addrs.items() if name in GEN1_REPOS}
    results.extend(verify_gen1(gen1, pret_syms))
    for variant, fields in profile_addrs.items():
        if variant in GEN1_REPOS:
            continue
        for field, profile_addr in fields.items():
            mapping = PROFILE_TO_PRET.get((variant, field))
            if mapping is None:
                # Either intentionally None (offset constant), or unmapped (we don't know which pret symbol)
                if (variant, field) in PROFILE_TO_PRET:
                    severity = "SKIP"
                    note = "no pret symbol (offset / constant)"
                else:
                    severity = "WARN"
                    note = "unmapped — add to PROFILE_TO_PRET to verify"
                results.append({
                    "variant": variant,
                    "field": field,
                    "severity": severity,
                    "profile_addr": profile_addr,
                    "pret_addr": None,
                    "pret_symbol": None,
                    "note": note,
                })
                continue

            repo, sym = mapping
            if repo not in pret_syms:
                results.append({
                    "variant": variant,
                    "field": field,
                    "severity": "WARN",
                    "profile_addr": profile_addr,
                    "pret_addr": None,
                    "pret_symbol": sym,
                    "note": f"pret repo {repo} missing from data/pret_syms.json",
                })
                continue

            pret_addr = pret_syms[repo].get(sym)
            if pret_addr is None:
                results.append({
                    "variant": variant,
                    "field": field,
                    "severity": "WARN",
                    "profile_addr": profile_addr,
                    "pret_addr": None,
                    "pret_symbol": sym,
                    "note": f"symbol {sym} not in {repo}.sym (renamed upstream?)",
                })
                continue

            severity = "OK" if profile_addr == pret_addr else "FAIL"
            results.append({
                "variant": variant,
                "field": field,
                "severity": severity,
                "profile_addr": profile_addr,
                "pret_addr": pret_addr,
                "pret_symbol": sym,
                "note": "" if severity == "OK"
                         else f"delta={profile_addr - pret_addr:+d} bytes",
            })
    return results


def _format_table(results: list[dict], *, verbose: bool) -> str:
    """Pretty-print results. By default hides OK / SKIP rows."""
    lines: list[str] = []
    for row in results:
        if not verbose and row["severity"] in ("OK", "SKIP"):
            continue
        sev = row["severity"]
        marker = {"OK": "[OK]  ", "FAIL": "[FAIL]", "WARN": "[WARN]", "SKIP": "[SKIP]"}[sev]
        prof = repr(row["profile_addr"])
        pret = repr(row["pret_addr"])
        sym = row["pret_symbol"] or ""
        note = row["note"]
        lines.append(
            f"{marker} {row['variant']:<8} {row['field']:<32} profile={prof}  pret={pret}  {sym:<25} {note}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true", help="show OK rows as well as FAIL/WARN")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of table")
    ap.add_argument("--gen1-only", action="store_true", help="strict effective Red/Blue/Yellow/AP profiles only")
    args = ap.parse_args()

    if not PRET_SYMS.exists():
        print(
            f"ERROR: {PRET_SYMS} missing.\n"
            f"Run: python tools/build_pret_syms.py",
            file=sys.stderr,
        )
        return 2

    pret_syms_data: dict[str, dict[str, int]] = json.loads(PRET_SYMS.read_text(encoding="utf-8"))

    try:
        profile_addrs = load_gen1_profiles()
        if not args.gen1_only:
            profile_addrs.update(_extract_variant_addresses(PROFILE_GEN2))
    except (ImportError, OSError, ValueError) as exc:
        print(f"ERROR: cannot load effective profiles: {exc}", file=sys.stderr)
        return 2

    results = verify(profile_addrs, pret_syms_data)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(_format_table(results, verbose=args.verbose))
        # Always print a summary footer
        counts = {"OK": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
        for r in results:
            counts[r["severity"]] += 1
        print(f"\nSummary: {counts['OK']} ok / {counts['FAIL']} fail / {counts['WARN']} warn / {counts['SKIP']} skip")

    failed = sum(1 for r in results if r["severity"] == "FAIL")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
