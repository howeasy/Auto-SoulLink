"""
tools/verify_profile_addresses.py — Phase 10 address-correctness verifier

Diffs Lua profile addresses (lua/games/gen1_rby.lua, lua/games/gen2_crystal.lua)
against pret-authoritative addresses (data/pret_syms.json, produced by
tools/build_pret_syms.py).

Output: structured per-(variant, field) diff with severity:
  [OK]    profile matches pret
  [FAIL]  profile differs from pret → correction needed
  [WARN]  pret symbol not mapped — manual inspection
  [SKIP]  field has no expected pret symbol (e.g. derived offsets like dv_offset_1)

Exit code 0 if all-OK or only WARN/SKIP. Non-zero if any FAIL.

Usage:
    python tools/verify_profile_addresses.py
    python tools/verify_profile_addresses.py --verbose   # show OK rows too
    python tools/verify_profile_addresses.py --json      # machine-readable output

The PROFILE_TO_PRET mapping below is the source of truth for which Lua profile
field corresponds to which pret symbol. Update this when adding new profile
addresses.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Optional

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
PROFILE_TO_PRET: dict[tuple[str, str], Optional[tuple[str, str]]] = {}


def _add(variant: str, repo: str, mapping: dict[str, Optional[str]]) -> None:
    for field, sym in mapping.items():
        PROFILE_TO_PRET[(variant, field)] = (repo, sym) if sym else None


# ── Red / Blue (pokered) ─────────────────────────────────────────────────────
_RED_MAP: dict[str, Optional[str]] = {
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
}
_add("red", "pokered", _RED_MAP)
_add("blue", "pokered", _RED_MAP)  # blue shares red profile in Lua

# ── Yellow (pokeyellow) ───────────────────────────────────────────────────────
# Same field-name shape as Red/Blue.
_add("yellow", "pokeyellow", _RED_MAP)

# ── Crystal (pokecrystal) ─────────────────────────────────────────────────────
_CRYSTAL_MAP: dict[str, Optional[str]] = {
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
    "ENEMY_SPECIES_LIST_ADDR": "wOTPartySpecies",
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
    """Return {variant_name: {field_name: int_addr}}. Only hex-valued fields
    (those that look like 0xABCD) are extracted. Other field types (booleans,
    strings, tables) are ignored.

    Variant blocks are matched by walking the file: each top-level `<name> = {`
    inside `M.PROFILES = { ... }` starts a new variant; we track brace depth
    to know when the variant block closes.
    """
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
    current_variant: Optional[str] = None
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


# ── Verification logic ──────────────────────────────────────────────────────

def verify(
    profile_addrs: dict[str, dict[str, int]],
    pret_syms: dict[str, dict[str, int]],
) -> list[dict]:
    """Return a list of result rows: {variant, field, severity, profile_addr,
    pret_addr, pret_symbol, note}. severity is "OK" / "FAIL" / "WARN" / "SKIP"."""
    results: list[dict] = []
    for variant, fields in profile_addrs.items():
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
        prof = f"0x{row['profile_addr']:04X}" if row["profile_addr"] is not None else "----"
        pret = f"0x{row['pret_addr']:04X}" if row["pret_addr"] is not None else "----"
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
    args = ap.parse_args()

    if not PRET_SYMS.exists():
        print(
            f"ERROR: {PRET_SYMS} missing.\n"
            f"Run: python tools/build_pret_syms.py",
            file=sys.stderr,
        )
        return 2

    pret_syms_data: dict[str, dict[str, int]] = json.loads(PRET_SYMS.read_text(encoding="utf-8"))

    profile_addrs = {
        **_extract_variant_addresses(PROFILE_GEN1),
        **_extract_variant_addresses(PROFILE_GEN2),
    }

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
