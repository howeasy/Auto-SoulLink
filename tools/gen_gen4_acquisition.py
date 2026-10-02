#!/usr/bin/env python3
"""gen_gen4_acquisition.py -- HGSS acquisition coverage map from pinned pret/pokeheartgold.

Writes data/games/gen4_hgss/acquisition.json. It JOINS four inventories so no producer can vanish
silently (docs/gen4/PLAN.md section 4.4, research/acquisition.md):

  script_sites   every line of files/fielddata/script/scr_seq/*.s that runs one of
                 GiveMon|GiveEgg|GiveTogepiEgg|GiveSpikyEarPichu|GiveLoanMon|CreateRoamer|WildBattle|
                 LoadNPCTrade|ChooseStarter (61 at the pin), resolved to species/level where the
                 script makes that possible, otherwise carried as version_branch / candidates /
                 unresolved with the reason
  c_producers    every call site in src/**/*.c of Party_AddMon, Party_SafeCopyMonToSlot_*, the PCStorage
                 place calls and GiveMon/GiveEgg, each classified (acquisition, not_acquisition,
                 external, infrastructure). A new, unclassified call site FAILS the generation
  npc_trade_records  the 13 records of NARC files/a/1/1/2 (NPCTrade, 0x54 bytes), each tied to its
                 LoadNPCTrade / GiveLoanMon sites: 10 exchanges, 2 loans, 1 dormant record
  runtime_branches  every GetGameVersion branch in a script that holds a site (HG/SS differ at runtime;
                 there is one shared scr_seq build)
  reachability   per script site (`script_sites[].reachability`): the story gates guarding it, derived from SOURCE with a
                 file:line cite each (script path flags/vars + the zone_event/header trigger that starts the entry), or
                 `partial`/`unresolved` with the reason (see the reachability section below)

D10/D14 zone mapping is data here: statics/gifts/eggs/starters/loans use the gift rules in the map's
area, roamers are extra catches, the Bug-Catching Contest and Safari are their own zones (the contest
catch is awarded at the result, not in the contest). Unsupported/unresolved producers are listed in
`unresolved`; hg-engine has its own authored inventory and is NOT covered here (UNVERIFIED).

hge mode (data/games/gen4_hge/acquisition.json): the hg-engine build runs the same script NARC members and
NPC trade records, so the script-side sections are the vanilla ones, PROVED by hashing the 47 member files
holding the sites (and the trade NARC) in both ROMs. The C side is NOT shared: hge replaces GiveMon, GiveEgg,
GiveTogepiEgg, _CreateTradeMon, the PC place functions, ... so the hge producer inventory is scanned from the
fork's src/ (see section "hge mode" below) and every vanilla producer is marked replaced / kept.

Usage:
  python tools/gen_gen4_acquisition.py [--pret PATH] [--check]
  python tools/gen_gen4_acquisition.py hge [--check] [--pret P] [--rom HGE_ROM] [--vanilla-rom ROM] [--src FORK] [--xmap MAP]
Exit: 0 ok, 1 drift / wrong pin / unclassified producer / differing script member, 2 an input is absent (named).
"""

from __future__ import annotations

import argparse
import bisect
import functools
import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen4_pins  # noqa: E402
import gen_gen4_area_map as base  # noqa: E402
import gen_gen4_names as names  # noqa: E402  (ROM/fork locators + Absent/Mismatch, shared with the names tool)

# NAME COLLISION: "GiveEgg" is both a script COMMAND (macro GiveEgg -> opcode 138 -> handler ScrCmd_GiveEgg) and a
# vanilla C FUNCTION (script_pokemon_util.c GiveEgg, the shared implementation the Manaphy mystery gift calls).
# COMMANDS / script_sites / `scripts` fields use the command; C_PRODUCERS and HGE_C_APIS keys use the C function.
COMMANDS = ("GiveMon", "GiveEgg", "GiveTogepiEgg", "GiveSpikyEarPichu", "GiveLoanMon", "CreateRoamer", "WildBattle", "LoadNPCTrade", "ChooseStarter")
SCAN_RE = re.compile(r"^\s*(" + "|".join(COMMANDS) + r")\b(.*)$")
KIND = {
    "ChooseStarter": "starter",
    "GiveMon": "gift",
    "GiveEgg": "egg",
    "GiveTogepiEgg": "egg",
    "GiveSpikyEarPichu": "special_gift",
    "GiveLoanMon": "loan",
    "CreateRoamer": "roamer",
    "WildBattle": "static",
    "LoadNPCTrade": "npc_exchange",
}
ZONE_POLICY = {
    "wild": {"zone": "area", "plan": "D10", "note": "ordinary wild encounter: first catch per area (encounters.json banks)"},
    "starter": {"zone": "gift", "plan": "D10", "note": "scripted gifts/eggs/statics follow the gift-namespace rules"},
    "gift": {"zone": "gift", "plan": "D10"},
    "egg": {"zone": "gift", "plan": "D10", "note": "O-15: a hatched egg is a gift catch"},
    "special_gift": {"zone": "gift", "plan": "D10"},
    "loan": {"zone": "gift", "plan": "D11", "note": "loan grant is an acquisition, never a fabricated old->new exchange"},
    "static": {"zone": "gift", "plan": "D10", "note": "WildBattle with fixed species/level; the catch follows the gift rules"},
    "roamer": {"zone": "roamer", "plan": "D10", "note": "roamers are extra catches: they do not consume or fill an area"},
    "npc_exchange": {"zone": "exchange", "plan": "D11", "note": "key_change{reason:npc_trade} only after an executed slot replacement with observed old/new PID:OTID"},
    "bug_contest": {"zone": "own", "area": "bug_catching_contest", "plan": "D10", "note": "the kept bug is the catch, awarded at the result"},
    "safari": {"zone": "own", "plan": "D10", "note": "one zone per Safari area, resolved at runtime"},
}
HV = {"heartgold": 7, "soulsilver": 8}  # include/config.h VERSION_HEARTGOLD/SOULSILVER, compared by GetGameVersion
SITE_COUNT = 61  # script sites for COMMANDS at the pin (docs/gen4/research/acquisition.md)
# Mon-making script commands deliberately outside COMMANDS. Key = command; a count change fails generation so
# new producers cannot appear unnoticed.
OUT_OF_SCOPE = {
    "GiveDaycareEgg": {"count": 1, "why": "daycare egg grant: the hatch is the O-15 gift catch (see C producer GiveEggToPlayer)"},
    "RetrieveDaycareMon": {"count": 1, "why": "daycare withdrawal: the mon already has a Soul Link key (see C producer open_question)"},
    "MysteryGift": {"count": 14, "why": "external distribution, not observable (src/scrcmd_mystery_gift.c)"},
    "NPCTradeExec": {"count": 11, "why": "executes the LoadNPCTrade record; counted 1:1 with LoadNPCTrade per file, the exchange itself is the LoadNPCTrade site"},
    "GetFossilPokemon": {"count": 2, "why": "fills the fossil species var that a GiveMon site consumes (resolved as `candidates` via sFossilPokemonMap)"},
}
INPUTS = [
    "include/constants/maps.h",
    "src/data/map_headers.h",
    "include/constants/map_sections.h",
    "include/constants/safari.h",
    "files/msgdata/msg/msg_0279.gmm",
    "include/constants/species.h",
    "include/constants/items.h",
    "include/constants/npc_trade.h",
    "include/config.h",
    "files/msgdata/msg/msg_0237.gmm",
    "files/msgdata/msg/msg_0222.gmm",
    "files/msgdata/msg/msg_0200.gmm",
    "files/a/1/1/2",
    "src/choose_starter.c",
    "src/field_roamer.c",
    "src/scrcmd_fossils.c",
    "src/field/scrcmd_pokemon_misc.c",
]

# C producer classification. Key = (file, enclosing function, API); value = expected call count + class.
# Anything the scan finds that is not here (or a count change) fails generation: a new producer must be
# classified on purpose. `scripts` names the script commands that reach the site.
C_APIS = (
    "Party_AddMon",
    "Party_SafeCopyMonToSlot_ResetAprijuiceModifiers",
    "PCStorage_PlaceMonInFirstEmptySlotInAnyBox",
    "PCStorage_PlaceMonInBoxFirstEmptySlot",
    "GiveMon",
    "GiveEgg",
)
def _p(**fields) -> dict:
    return fields


C_PRODUCERS: dict[tuple[str, str, str], dict] = {
    ("src/battle/battle_command.c", "Task_GetPokemon", "Party_AddMon"): _p(n=1, cls="acquisition", kind="wild_capture", note="catch: ball hit adds the mon to the party; a Bug-Catching Contest catch branches earlier and is stored in the battle system instead (awarded at the result)"),
    ("src/battle/battle_command.c", "Task_GetPokemon", "PCStorage_PlaceMonInBoxFirstEmptySlot"): _p(n=1, cls="acquisition", kind="wild_capture", note="catch with a full party: transferred to the PC (the same capture)"),
    ("src/battle/battle_setup.c", "BattleSetup_New_Tutorial", "Party_AddMon"): _p(n=2, cls="not_acquisition", kind="tutorial_battle", note="synthetic Marill vs Rattata in a battle-setup party; the save party is untouched"),
    ("src/battle/battle_setup.c", "BattleSetup_AddMonToParty", "Party_AddMon"): _p(n=1, cls="not_acquisition", kind="battle_party_copy", note="copies a mon into the BattleSetup party, not the save"),
    ("src/choose_starter.c", "CreateStarter", "Party_AddMon"): _p(n=1, cls="acquisition", kind="starter", scripts=["ChooseStarter"], note="Elm's choice of Chikorita/Cyndaquil/Totodile, level 5"),
    ("src/field/encounter_check.c", "initRoamingWildmon", "Party_AddMon"): _p(n=1, cls="not_acquisition", kind="roamer_enemy_generation", note="builds the roamer as a BattleSetup enemy; catching goes through Task_GetPokemon"),
    ("src/field/encounter_check.c", "addGeneratedMonToBattleSetupParty", "Party_AddMon"): _p(n=1, cls="not_acquisition", kind="wild_enemy_generation", note="wild enemy into the BattleSetup party; catching goes through Task_GetPokemon"),
    ("src/field/scrcmd_pokemon_misc.c", "ScrCmd_GiveTogepiEgg", "Party_AddMon"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveTogepiEgg"], note="Mr. Pokemon's Togepi egg (species fixed in C)"),
    ("src/field/scrcmd_pokemon_misc.c", "ScrCmd_GiveSpikyEarPichu", "Party_AddMon"): _p(n=1, cls="acquisition", kind="special_gift", scripts=["GiveSpikyEarPichu"], note="Spiky-eared Pichu L30 form 1 (fixed in C)"),
    ("src/get_egg.c", "Save_Daycare_MoveMonToParty", "Party_AddMon"): _p(n=1, cls="not_acquisition", kind="daycare_withdraw", open_question="the mon already has a Soul Link key; while deposited it is in neither party nor box, so the storage watcher must treat the withdrawal as a known-key party gain", note="returns the deposited mon to the party"),
    ("src/get_egg.c", "GiveEggToPlayer", "Party_AddMon"): _p(n=1, cls="acquisition", kind="egg", note="daycare egg (O-15: the hatch is the gift catch); reached from a daycare script, not one of the 9 commands"),
    ("src/npc_trade.c", "NPCTrade_MakeAndGiveLoanMon", "Party_AddMon"): _p(n=1, cls="acquisition", kind="loan", scripts=["GiveLoanMon"], note="loan grant: adds a party mon, replaces no outgoing slot"),
    ("src/npc_trade.c", "NPCTrade_ReceiveMonToSlot", "Party_SafeCopyMonToSlot_ResetAprijuiceModifiers"): _p(n=1, cls="acquisition", kind="npc_exchange", scripts=["LoadNPCTrade"], note="the executed exchange replaces the chosen party slot"),
    ("src/overlay_bug_contest.c", "BugContest_RestoreParty_RetrieveCaughtPokemon", "Party_SafeCopyMonToSlot_ResetAprijuiceModifiers"): _p(n=1, cls="not_acquisition", kind="contest_party_restore", note="puts the (used) lead mon back into the restored party"),
    ("src/overlay_bug_contest.c", "BugContest_RestoreParty_RetrieveCaughtPokemon", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox"): _p(n=1, cls="acquisition", kind="contest_result", note="contest result with a full party: the kept bug goes to the PC"),
    ("src/overlay_bug_contest.c", "BugContest_RestoreParty_RetrieveCaughtPokemon", "Party_AddMon"): _p(n=1, cls="acquisition", kind="contest_result", note="contest result: the kept bug joins the party; this, not the in-contest catch, is the Soul Link catch"),
    ("src/pokemon_storage_system.c", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox", "PCStorage_PlaceMonInBoxFirstEmptySlot"): _p(n=1, cls="infrastructure", kind="storage_helper", note="internal call of the storage helper itself"),
    ("src/scrcmd_12.c", "ScrCmd_510", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox"): _p(n=1, cls="external", kind="pal_park_migration", note="Pal Park migration from Gen 3 cartridges; migrated mons only, out of scope"),
    ("src/scrcmd_mystery_gift.c", "MGGive_ManaphyEgg", "GiveEgg"): _p(n=1, cls="external", kind="mystery_gift", note="external distribution, not observable"),
    ("src/scrcmd_mystery_gift.c", "MGGive_Mon", "Party_AddMon"): _p(n=1, cls="external", kind="mystery_gift", note="external distribution, not observable"),
    ("src/scrcmd_party.c", "ScrCmd_GiveMon", "GiveMon"): _p(n=1, cls="script_dispatch", kind="gift", scripts=["GiveMon"], note="GiveMon command handler"),
    ("src/scrcmd_party.c", "ScrCmd_GiveEgg", "Party_AddMon"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveEgg"], note="GiveEgg command: adds a party egg when the party has room"),
    ("src/script_pokemon_util.c", "GiveMon", "Party_AddMon"): _p(n=1, cls="script_dispatch", kind="gift", scripts=["GiveMon"], note="shared GiveMon implementation"),
    ("src/script_pokemon_util.c", "GiveEgg", "Party_AddMon"): _p(n=1, cls="script_dispatch", kind="egg", scripts=["GiveEgg"], note="shared GiveEgg implementation (also the Manaphy mystery-gift egg)"),
    ("src/trainer_data.c", "CreateNPCTrainerParty", "Party_AddMon"): _p(n=4, cls="not_acquisition", kind="trainer_party", note="builds a trainer's enemy party"),
}


# --------------------------------------------------------------------------- script scan


def val(text: str, species: dict[str, int]) -> int | None:
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return species.get(text)


class Ctx:
    def __init__(self, clone: Path):
        self.clone = clone
        self.species = base.defines(clone, "include/constants/species.h", "SPECIES_")
        self.items = base.defines(clone, "include/constants/items.h", "ITEM_")
        self.species_names = {k: base.titled(v) for k, v in base.gmm(clone, 237).items()}
        self.item_names = base.gmm(clone, 222)
        self.model = base.build_model(clone)
        self.maps: base.Maps = self.model["maps"]
        self.version_consts = base.defines(clone, "include/config.h", "VERSION_")
        assert self.version_consts["VERSION_HEARTGOLD"] == HV["heartgold"] and self.version_consts["VERSION_SOULSILVER"] == HV["soulsilver"], "version constants drifted"
        self.fossils = dict(re.findall(r"\{\s*(ITEM_\w+),\s*(SPECIES_\w+)\s*\}", base.read(clone, "src/scrcmd_fossils.c")))
        assert len(self.fossils) == 7, "fossil table drifted"

    def sp(self, sid: int) -> dict:
        return {"id": sid, "name": self.species_names.get(sid, "")}

    def species_val(self, text: str) -> dict | None:
        v = val(text, self.species)
        return None if v is None else self.sp(v)


def entry_start(lines: list[str], idx: int) -> int:
    while idx > 0 and not re.match(r"^scr_seq_\w+:", lines[idx]):
        idx -= 1
    return idx


BLOCK_END = re.compile(r"^\s*(End|Return|GoTo|EndMovement|ScrDefEnd|InitScriptEntryEnd|\.balign)\b")


def entry_roots(lines: list[str], hit: int) -> list[str]:
    """Script entries (scr_seq_* labels) that can reach line `hit`: walk label references (Call/GoTo*) and
    fall-through backwards from the hit's label block. Shared subroutines (e.g. `Call _0801` from three
    starter-choice entries) have several roots; entry_start() alone would silently pick the textually nearest."""
    lab = [(i, m[1]) for i, ln in enumerate(lines) if (m := re.match(r"^(\w+):\s*$", ln))]
    starts, names = [i for i, _ in lab], [n for _, n in lab]
    refs: dict[str, list[int]] = {}
    for i, ln in enumerate(lines):
        if not re.match(r"^\w+:\s*$", ln):
            for w in set(re.findall(r"\w+", ln)):
                refs.setdefault(w, []).append(i)
    blk = lambda i: bisect.bisect_right(starts, i) - 1  # noqa: E731
    seen, todo = {blk(hit)}, [blk(hit)]
    while todo:
        k = todo.pop()
        if k < 0:
            continue
        preds = [blk(i) for i in refs.get(names[k], [])]
        if k > 0:
            last = next((lines[x] for x in range(starts[k] - 1, starts[k - 1], -1) if lines[x].strip()), "")
            if not BLOCK_END.match(last):
                preds.append(k - 1)  # falls into this label
        for q in preds:
            if q >= 0 and q not in seen:
                seen.add(q)
                todo.append(q)
    return sorted(names[k] for k in seen if k >= 0 and names[k].startswith("scr_seq_"))


def assignments(lines: list[str], lo: int, hi: int, var: str, ctx: Ctx) -> list[tuple[int, str, object]]:
    """Writes to `var` in lines[lo:hi]: (line, 'lit', value) for SetVar/SetOrCopyVar literals,
    (line, 'cmd', command) for commands that fill it at runtime (Get*, CopyVar, ...)."""
    out = []
    for i in range(lo, hi):
        m = re.match(rf"^\s*(?:SetVar|SetOrCopyVar)\s+{re.escape(var)},\s*(\S+)\s*$", lines[i])
        if m:
            v = val(m.group(1), ctx.species)
            out.append((i + 1, "lit", v) if v is not None else (i + 1, "cmd", f"SetOrCopyVar from {m.group(1)}"))
            continue
        m = re.match(rf"^\s*(Get\w+|CopyVar|AddVar|SubVar|ScrCmd_\d+)\s+{re.escape(var)}\s*(?:,|$)", lines[i])
        if m:
            out.append((i + 1, "cmd", m.group(1)))
    return out


def version_paths(lines: list[str], lo: int, hit: int, ctx: Ctx):
    """Parse `GetGameVersion; Compare R,N; GoToIfNe/Eq L; <A>; GoTo E; L: <B>` ahead of a hit.
    Returns (line_of_GetGameVersion, {version: [(line, var, value)]}) or ("unparsed", reason) / None."""
    g = next((i for i in range(hit - 1, lo - 1, -1) if "GetGameVersion" in lines[i]), None)
    if g is None:
        return None
    cmp_m = re.match(r"^\s*Compare\s+\S+,\s*(\d+)\s*$", lines[g + 1])
    jmp_m = re.match(r"^\s*(GoToIfNe|GoToIfEq)\s+(\w+)\s*$", lines[g + 2])
    if not cmp_m or not jmp_m or int(cmp_m.group(1)) not in HV.values():
        return "unparsed", f"GetGameVersion at line {g + 1} is not the Compare 7/8 + GoToIfNe/Eq pattern"
    n, op, target = int(cmp_m.group(1)), jmp_m.group(1), jmp_m.group(2)

    def collect(start: int, stop_at_label: bool) -> tuple[list, str | None]:
        rows, i = [], start
        while i < hit:
            line = lines[i]
            if stop_at_label and re.match(r"^\w+:", line):
                return rows, None
            m = re.match(r"^\s*GoTo\s+(\w+)\s*$", line)
            if m:
                return rows, m.group(1)
            m = re.match(r"^\s*SetVar\s+(\S+),\s*(\S+)\s*$", line)
            if m and (v := val(m.group(2), ctx.species)) is not None:
                rows.append((i + 1, m.group(1), v))
            i += 1
        return rows, None

    fall, _end = collect(g + 3, True)
    tgt_line = next((i for i in range(g + 3, hit) if lines[i].strip() == f"{target}:"), None)
    if tgt_line is None:
        return "unparsed", f"branch label {target} not found before the site"
    tgt, _ = collect(tgt_line + 1, True)
    eq_path, ne_path = (fall, tgt) if op == "GoToIfNe" else (tgt, fall)
    return g + 1, {v: (eq_path if num == n else ne_path) for v, num in HV.items()}


def resolve(arg: str, kind: str, lines: list[str], hit: int, ctx: Ctx):
    """Resolve one script argument. kind 'species' or 'int'. Returns a resolution dict."""

    def wrap(v):
        return ctx.sp(v) if kind == "species" else v

    v = val(arg, ctx.species)
    if v is not None:
        return {"resolution": "literal", "value": wrap(v)}
    var = arg.strip()
    if not re.match(r"^VAR_", var):
        return {"resolution": "unresolved", "reason": f"unrecognised argument {arg!r}"}
    lo = entry_start(lines, hit)
    roots = entry_roots(lines, hit)
    if roots and roots != [lines[lo].rstrip(":")]:
        return {"resolution": "unresolved", "var": var, "reason": "cross_entry", "detail": f"the site is shared code reached from {len(roots)} script entries; {var} is set by the caller, so it is not statically one value", "entries": roots}
    vp = version_paths(lines, lo, hit, ctx)
    if isinstance(vp, tuple) and vp[0] == "unparsed":
        return {"resolution": "unresolved", "reason": vp[1]}
    if vp is not None:
        g_line, paths = vp
        per = {}
        for ver, rows in paths.items():
            hit_rows = [r for r in rows if r[1] == var]
            if hit_rows:
                per[ver] = wrap(hit_rows[-1][2])
        if per:
            if len(per) == 2:
                return {"resolution": "version_branch", "by_version": per, "branch_line": g_line}
            # assigned on one side only; the other side keeps the pre-branch value
            pre = [a for a in assignments(lines, lo, g_line - 1, var, ctx) if a[1] == "lit"]
            if pre:
                for ver in HV:
                    per.setdefault(ver, wrap(pre[-1][2]))
                return {"resolution": "version_branch", "by_version": per, "branch_line": g_line}
    # Last writes to the variable before the site, WITHIN the site's own script entry (lo = its
    # scr_seq_* label). A literal 0 is a reset, not a value. If the last real write is a runtime
    # command the value is runtime; otherwise the trailing run of literal writes is the candidate set.
    # A write that exists only in an EARLIER entry is never promoted: that entry is a different
    # script, so the site is unresolved (`cross_entry`).
    def real(a: tuple) -> bool:
        return not (a[1] == "lit" and a[2] == 0)

    events = [a for a in assignments(lines, lo, hit, var, ctx) if real(a)]
    if not events:
        outside = [a[0] for a in assignments(lines, 0, lo, var, ctx) if real(a)]
        if outside:
            return {"resolution": "unresolved", "var": var, "reason": "cross_entry", "detail": f"{var} is written only outside this script entry (lines {outside}; the entry starts at line {lo + 1})", "outside_entry_lines": outside}
        return {"resolution": "unresolved", "var": var, "reason": f"no assignment of {var} before the site"}
    if events[-1][1] == "cmd":
        line, _k, cmd = events[-1]
        if cmd == "GetFossilPokemon" and kind == "species":
            cands = [ctx.sp(ctx.species[s]) for s in ctx.fossils.values()]
            return {"resolution": "candidates", "var": var, "candidates": cands, "from": f"GetFossilPokemon at line {line}: src/scrcmd_fossils.c sFossilPokemonMap (item -> species)", "runtime": "which fossil the player hands over"}
        return {"resolution": "unresolved", "var": var, "reason": f"{var} is assigned at runtime by {cmd} (line {line})"}
    run = []
    for a in reversed(events):
        if a[1] == "cmd":
            break
        run.append(a)
    vals = list(dict.fromkeys(a[2] for a in reversed(run)))
    lines_ = [a[0] for a in reversed(run)]
    if len(vals) == 1:
        return {"resolution": "literal", "value": wrap(vals[0]), "var": var, "set_at_lines": lines_}
    return {"resolution": "candidates", "var": var, "candidates": [wrap(x) for x in vals], "set_at_lines": lines_, "runtime": "which value the script reaches is decided by menu/flag flow"}


def split_args(raw: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def c_facts(ctx: Ctx) -> dict:
    """Species/level that the engine, not the script, supplies (read from the pinned C)."""
    c = ctx.clone
    starters = re.findall(r"SPECIES_\w+", re.search(r"const int species\[\] = \{(.*?)\}", base.read(c, "src/choose_starter.c"), re.S)[1])
    starter_level = int(re.search(r"CreateMon\(mon, species\[i\], (\d+)", base.read(c, "src/choose_starter.c"))[1])
    roam_src = base.read(c, "src/field_roamer.c")
    roamers = {
        idx: (sp_c, int(lv))
        for idx, sp_c, lv in re.findall(r"case (ROAMER_\w+):\s*species = (SPECIES_\w+);\s*level = (\d+);", roam_src)
    }
    roam_ids = base.defines(c, "include/constants/roamer.h", "ROAMER_")
    pm = base.read(c, "src/field/scrcmd_pokemon_misc.c")
    togepi = re.search(r"BOOL ScrCmd_GiveTogepiEgg.*?SetEggStats\(mon, (SPECIES_\w+)", pm, re.S)[1]
    pichu = re.search(r"BOOL ScrCmd_GiveSpikyEarPichu.*?CreateMon\(mon, (SPECIES_\w+), (\d+)", pm, re.S)
    pichu_item = re.search(r"BOOL ScrCmd_GiveSpikyEarPichu.*?heldItem = (ITEM_\w+)", pm, re.S)[1]
    return {
        "starters": [ctx.sp(ctx.species[s]) for s in starters],
        "starter_level": starter_level,
        "roamers": {roam_ids[k]: {"const": k, "species": ctx.sp(ctx.species[s]), "level": lv} for k, (s, lv) in roamers.items()},
        "togepi": ctx.sp(ctx.species[togepi]),
        "pichu": {"species": ctx.sp(ctx.species[pichu[1]]), "level": int(pichu[2]), "form": 1, "item": {"id": ctx.items[pichu_item], "name": ctx.item_names[ctx.items[pichu_item]]}},
    }


# --------------------------------------------------------------------------- NPC trade NARC

NPC_FIELDS = ("give_species", "hpIv", "atkIv", "defIv", "speedIv", "spAtkIv", "spDefIv", "ability", "otId", "cool", "beauty", "cute", "smart", "tough", "pid", "heldItem", "gender", "sheen", "language", "ask_species", "unk_50")


def parse_npc_narc(data: bytes) -> list[dict]:
    assert data[:4] == b"NARC", "files/a/1/1/2 is not a NARC"
    fat_size = struct.unpack_from("<I", data, 0x14)[0]
    assert data[0x10:0x14] == b"BTAF"
    count = struct.unpack_from("<H", data, 0x18)[0]
    fat = [struct.unpack_from("<II", data, 0x1C + 8 * i) for i in range(count)]
    fnt = 0x10 + fat_size
    assert data[fnt : fnt + 4] == b"BTNF"
    gmif = fnt + struct.unpack_from("<I", data, fnt + 4)[0]
    assert data[gmif : gmif + 4] == b"GMIF"
    rows = []
    for start, end in fat:
        blob = data[gmif + 8 + start : gmif + 8 + end]
        assert len(blob) == 0x54, "NPCTrade record is not 0x54 bytes"
        rows.append(dict(zip(NPC_FIELDS, struct.unpack("<21i", blob), strict=True)))
    return rows


def npc_records(ctx: Ctx, sites: list[dict]) -> list[dict]:
    rows = parse_npc_narc((ctx.clone / "files/a/1/1/2").read_bytes())
    enum = re.findall(r"^\s+(NPC_TRADE_\w+),", base.read(ctx.clone, "include/constants/npc_trade.h"), re.M)
    enum = [e for e in enum if e != "NPC_TRADE_MAX"]
    assert len(rows) == len(enum) == 13, "NPC trade record count drifted"
    ot_names = base.gmm(ctx.clone, 200)
    out = []
    for i, (rec, name) in enumerate(zip(rows, enum, strict=True)):
        loads = [s["id"] for s in sites if s["command"] == "LoadNPCTrade" and s["npc_record"] == i]
        loans = [s["id"] for s in sites if s["command"] == "GiveLoanMon" and s["npc_record"] == i]
        cls = "authored_exchange" if loads else "authored_loan_grant" if loans else "dormant_narc_record_in_pinned_authored_scan"
        assert not (loads and loans), f"record {i} is both loaded and loaned"
        out.append(
            {
                "index": i,
                "enum": name,
                "source_class": cls,
                "give": ctx.sp(rec["give_species"]),
                "ask": ctx.sp(rec["ask_species"]),
                "held_item": {"id": rec["heldItem"], "name": ctx.item_names.get(rec["heldItem"], "")},
                "ot_name": ot_names.get(13 + i),
                "record": rec,
                "load_sites": loads,
                "loan_sites": loans,
                "same_species": rec["give_species"] == rec["ask_species"],
                "version_split": False,
                "identity_rule": {
                    "authored_exchange": "key_change{reason:npc_trade} candidate only after an executed slot replacement with observed old/new PID:OTID (src/npc_trade.c NPCTrade_ReceiveMonToSlot)",
                    "authored_loan_grant": "acquisition (gift namespace); adds a party mon, no outgoing slot replacement, never key_change (src/npc_trade.c NPCTrade_MakeAndGiveLoanMon)",
                    "dormant_narc_record_in_pinned_authored_scan": "no authored execution in the pinned scripts; no key_change",
                }[cls],
            }
        )
    return out


# --------------------------------------------------------------------------- C scan


def scan_c(clone: Path) -> tuple[list[dict], list[str]]:
    pat = re.compile(r"(?<![\w])(" + "|".join(C_APIS) + r")\(")
    found: dict[tuple[str, str, str], list[int]] = {}
    for p in sorted((clone / "src").rglob("*.c")):
        rel = p.relative_to(clone).as_posix()
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = pat.search(line)
            if not m or line[:1] not in " \t":  # call sites are indented; definitions/prototypes are not
                continue
            func = None
            for j in range(i, -1, -1):
                if re.match(r"^[A-Za-z_][\w\s\*]*\b(\w+)\([^;]*$", lines[j]) and not lines[j].startswith(("static const", "return", "else", "if", "for", "while", "switch")):
                    func = re.match(r"^[A-Za-z_][\w\s\*]*?\b(\w+)\(", lines[j])[1]
                    break
            found.setdefault((rel, func, m.group(1)), []).append(i + 1)
    problems = []
    for key, lns in found.items():
        want = C_PRODUCERS.get(key)
        if want is None:
            problems.append(f"unclassified C producer {key} at lines {lns}: classify it in C_PRODUCERS")
        elif want["n"] != len(lns):
            problems.append(f"C producer {key} has {len(lns)} call sites, table says {want['n']}")
    problems += [f"classified C producer {k} no longer found in the source" for k in C_PRODUCERS if k not in found]
    out = [{"file": k[0], "function": k[1], "api": k[2], "lines": found[k], **{a: b for a, b in C_PRODUCERS[k].items() if a != "n"}} for k in sorted(found) if k in C_PRODUCERS]
    return out, problems


# --------------------------------------------------------------------------- build


def build(clone: Path) -> dict[str, str]:
    return {"acquisition.json": base.dumps(build_doc(clone), 3)}


def build_doc(clone: Path) -> dict:
    ctx = Ctx(clone)
    cf = c_facts(ctx)
    script_dir = clone / "files/fielddata/script/scr_seq"
    files = sorted(script_dir.glob("*.s"))
    sites: list[dict] = []
    branch_files: set[str] = set()  # script files holding a site AND a GetGameVersion branch
    map_sources: dict[str, MapSources] = {}
    std = StdScripts(clone)
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [(i, SCAN_RE.match(line)) for i, line in enumerate(lines)]
        hits = [(i, m) for i, m in hits if m]
        if not hits:
            continue
        if any("GetGameVersion" in ln for ln in lines):
            branch_files.add(path.name)
        m = re.match(r"scr_seq_(\d+)_(\w+?)(?:_hdr)?\.s$", path.name)
        token = m[2] if m else None
        assert token in ctx.maps.by_token, f"{path.name}: script token {token!r} names no map"
        mid = ctx.maps.by_token[token]
        row = ctx.maps.rows[mid]
        area = ctx.model["map_area"].get(mid)
        script = Script(f"{SCR_DIR}/{path.name}", lines)
        ms = map_sources.setdefault(token, MapSources(clone, token))
        for i, mm in hits:
            cmd, raw = mm.group(1), mm.group(2).strip()
            args = split_args(raw)
            kind = KIND[cmd]
            site = {
                "id": f"{path.stem}:{i + 1}",
                "file": path.name,
                "line": i + 1,
                "command": cmd,
                "raw_args": raw,
                "kind": kind,
                "zone": ZONE_POLICY[kind]["zone"],
                "map_id": mid,
                "map_const": row["const"],
                "map_token": token,
                "area": area,
            }
            if cmd == "GiveMon":
                site |= {
                    "species": resolve(args[0], "species", lines, i, ctx),
                    "level": resolve(args[1], "int", lines, i, ctx),
                    "held_item": resolve(args[2], "int", lines, i, ctx),
                    "form": resolve(args[3], "int", lines, i, ctx),
                    "ability": resolve(args[4], "int", lines, i, ctx),
                }
            elif cmd == "GiveEgg":
                site |= {"species": resolve(args[0], "species", lines, i, ctx), "level": {"resolution": "literal", "value": 1, "evidence": "src/field/scrcmd_pokemon_misc.c / scrcmd_party.c SetEggStats(level 1)"}}
            elif cmd == "WildBattle":
                site |= {"species": resolve(args[0], "species", lines, i, ctx), "level": resolve(args[1], "int", lines, i, ctx), "shiny": args[2] == "1" if len(args) > 2 else False}
            elif cmd == "CreateRoamer":
                idx = int(args[0])
                r = cf["roamers"][idx]
                site |= {"roamer_index": idx, "species": {"resolution": "c_source", "value": r["species"], "evidence": "src/field_roamer.c Save_CreateRoamerByID"}, "level": {"resolution": "c_source", "value": r["level"], "evidence": "src/field_roamer.c Save_CreateRoamerByID"}}
            elif cmd == "ChooseStarter":
                site |= {"species": {"resolution": "candidates", "candidates": cf["starters"], "evidence": "src/choose_starter.c CreateStarter species[]", "runtime": "the player's choice"}, "level": {"resolution": "c_source", "value": cf["starter_level"], "evidence": "src/choose_starter.c CreateMon(level)"}}
            elif cmd == "GiveTogepiEgg":
                site |= {"species": {"resolution": "c_source", "value": cf["togepi"], "evidence": "src/field/scrcmd_pokemon_misc.c ScrCmd_GiveTogepiEgg SetEggStats"}, "level": {"resolution": "literal", "value": 1}}
            elif cmd == "GiveSpikyEarPichu":
                p = cf["pichu"]
                site |= {"species": {"resolution": "c_source", "value": p["species"], "evidence": "src/field/scrcmd_pokemon_misc.c ScrCmd_GiveSpikyEarPichu"}, "level": {"resolution": "c_source", "value": p["level"]}, "form": {"resolution": "c_source", "value": p["form"]}, "held_item": {"resolution": "c_source", "value": p["item"]}}
            elif cmd == "GiveLoanMon":
                # GiveLoanMon tradeno, level, mapno: the third argument is a MAP number, not a species
                site |= {"npc_record": int(args[0]), "level": {"resolution": "literal", "value": int(args[1])}, "loan_map_arg": int(args[2]), "species": {"resolution": "npc_record", "record": int(args[0]), "evidence": "species comes from NARC a/1/1/2 record give_species"}}
            elif cmd == "LoadNPCTrade":
                site |= {"npc_record": int(args[0])}
            site["status"] = status_of(site)
            site["reachability"] = reachability(script, ms, i, mid, row["const"], std)
            assert_in_own_entry(site, lines, i)
            sites.append(site)
    assert len(sites) == SITE_COUNT, f"script site count {len(sites)} != pinned {SITE_COUNT}"
    if reach_problems := verify_reachability(clone, sites):
        raise base.PretMismatch("reachability: " + "; ".join(reach_problems))
    if gated := [f"{s['id']}: {c['std']} may write {c['token']} (tested at {c['gate_cite']})" for s in sites for c in s["reachability"]["callstd"]["conflicts"]]:
        raise base.PretMismatch("reachability: CallStd callee writes a tested flag/var; model the gate before regenerating: " + "; ".join(gated))
    out_of_scope = scan_out_of_scope(files)

    # resolve loan species from the NPC record and mark them resolved
    records = npc_records(ctx, sites)
    for s in sites:
        if s["command"] == "GiveLoanMon":
            s["species"] = {"resolution": "npc_record", "value": records[s["npc_record"]]["give"], "record": s["npc_record"]}
            s["status"] = status_of(s)

    # runtime HG/SS branches in every script that holds a site
    branches = []
    for name in sorted(branch_files):
        lines = (script_dir / name).read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if "GetGameVersion" in line:
                lo = entry_start(lines, i)
                nxt = next((j for j in range(i + 1, len(lines)) if re.match(r"^scr_seq_\w+:", lines[j])), len(lines))
                affected = [s["id"] for s in sites if s["file"] == name and lo < s["line"] <= nxt]
                branches.append({"file": name, "line": i + 1, "entry": lines[lo].rstrip(":") if lines[lo].startswith("scr_seq_") else None, "affects_sites": affected})

    c_producers, problems = scan_c(clone)
    if problems:
        raise base.PretMismatch("; ".join(problems))
    commands_with_c = {c for p in c_producers for c in p.get("scripts", [])}

    unresolved = []
    for s in sites:
        if s["status"] in ("unresolved", "candidates"):
            unresolved.append({"id": s["id"], "kind": s["kind"], "status": s["status"], "why": unresolved_reason(s)})
    for p in c_producers:
        if p.get("open_question"):
            unresolved.append({"id": f"{p['file']}:{p['lines'][0]}", "kind": p["kind"], "status": "open_policy", "why": p["open_question"]})
    unresolved.append({"id": "hg_engine", "kind": "inventory", "status": "unverified", "why": "hg-engine's authored acquisition/exchange inventory is not covered here; vanilla counts must not be reused for hge"})
    unresolved.append({"id": "mystery_gift", "kind": "external", "status": "unobservable", "why": "src/scrcmd_mystery_gift.c distributions are external"})
    unresolved.append({"id": "link_trade_gts_pal_park", "kind": "external", "status": "unobservable", "why": "link trade, GTS and Pal Park migration are outside the scripted/C inventory"})

    counts = Counter(s["command"] for s in sites)
    script_digest = hashlib.sha256("".join(f"{f.name}:{hashlib.sha256(f.read_bytes()).hexdigest()}" + chr(10) for f in files).encode()).hexdigest()
    doc = {
        "_note": "GENERATED by tools/gen_gen4_acquisition.py from pinned pret/pokeheartgold -- do not edit. Joins script sites, C producers, NPC trade records and runtime HG/SS branches; nothing unresolved is dropped (see `unresolved`).",
        "_schema": "gen4-hgss-acquisition-v1",
        "source": base.provenance(clone, "tools/gen_gen4_acquisition.py", INPUTS + sorted({f"files/fielddata/script/scr_seq/{s['file']}" for s in sites} | {p["file"] for p in c_producers} | {r for m in map_sources.values() for r in (m.event_rel, m.hdr_rel) if r}))
        | {"scan": {"script_dir": "files/fielddata/script/scr_seq", "script_files_scanned": len(files), "script_scan_digest": script_digest, "command_regex": SCAN_RE.pattern}},
        "inventory": {
            "script_site_count": len(sites),
            "script_command_counts": {c: counts[c] for c in COMMANDS},
            "script_file_count_with_sites": len({s["file"] for s in sites}),
            "c_producer_count": len(c_producers),
            "c_call_site_count": sum(len(p["lines"]) for p in c_producers),
            "npc_record_count": len(records),
            "npc_classification": dict(Counter(r["source_class"] for r in records)),
            "npc_load_site_count": counts["LoadNPCTrade"],
            "npc_distinct_exchange_ids": sorted({s["npc_record"] for s in sites if s["command"] == "LoadNPCTrade"}),
            "status_counts": dict(sorted(Counter(s["status"] for s in sites).items())),
            "reachability_status_counts": dict(sorted(Counter(s["reachability"]["status"] for s in sites).items())),
            "callstd_call_count": sum(len(s["reachability"]["callstd"]["calls"]) for s in sites),
            "callstd_conflict_count": sum(len(s["reachability"]["callstd"]["conflicts"]) for s in sites),
            "callstd_targets": sorted({c["std"] for s in sites for c in s["reachability"]["callstd"]["calls"]}),
            "reachability_by_command": {c: dict(sorted(Counter(s["reachability"]["status"] for s in sites if s["command"] == c).items())) for c in COMMANDS},
            "commands_without_a_c_producer": sorted(set(COMMANDS) - commands_with_c - {"CreateRoamer", "WildBattle"}),
            "scope": "bounded candidate inventory: script sites for the 9 commands plus the C call sites of the 6 producer APIs; hge has its own inventory (UNVERIFIED)",
        },
        "zone_policy": ZONE_POLICY,
        "reachability_scope": REACHABILITY_SCOPE,
        "out_of_scope_commands": out_of_scope,
        "special_modes": {
            "bug_contest": {
                "area": "bug_catching_contest",
                "map_id": next(m for m, r in ctx.maps.rows.items() if r["const"] == base.BUG_CONTEST_MAP),
                "evidence": "src/battle/battle_setup.c BattleSetup_New_BugContest; src/overlay_bug_contest.c BugContest_RestoreParty_RetrieveCaughtPokemon (catch is awarded at the result)",
            },
            "safari": {
                "areas": [a for a, v in ctx.model["areas"].items() if v.get("parent") == "safari_zone"],
                "resolution": base.SAFARI_RESOLUTION,
                "balls": "30 (src/scrcmd_c.c)",
            },
            "roamers": {str(i): {**r} for i, r in sorted(cf["roamers"].items())},
        },
        "script_sites": sites,
        "c_producers": c_producers,
        "npc_trade_records": records,
        "runtime_branches": branches,
        "unresolved": unresolved,
    }
    return doc


def assert_in_own_entry(site: dict, lines: list[str], hit: int) -> None:
    """Every resolution that cites `set_at_lines` must cite writes inside the site's own script entry
    (a write in another entry is a different script: resolve() reports that as cross_entry)."""
    lo = entry_start(lines, hit)
    for field, v in site.items():
        if isinstance(v, dict) and v.get("set_at_lines"):
            bad = [n for n in v["set_at_lines"] if not (lo < n <= hit)]  # 1-based line n is index n-1 >= lo
            assert not bad, f"{site['id']} {field}: set_at_lines {bad} lie outside the site's entry (starts at line {lo + 1})"


def scan_out_of_scope(files: list[Path]) -> dict:
    """Mon-making script commands that are NOT in COMMANDS, with counts + file:line pinned so growth fails
    loudly. Also pins LoadNPCTrade / NPCTradeExec 1:1 per file (the exchange record is loaded then executed)."""
    pat = re.compile(r"^\s*(" + "|".join([*OUT_OF_SCOPE, "LoadNPCTrade"]) + r")\b")
    found: dict[str, list[str]] = {c: [] for c in [*OUT_OF_SCOPE, "LoadNPCTrade"]}
    per_file = {"LoadNPCTrade": Counter(), "NPCTradeExec": Counter()}
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if m := pat.match(line):
                found[m[1]].append(f"{f.name}:{n}")
                if m[1] in per_file:
                    per_file[m[1]][f.name] += 1
    assert per_file["LoadNPCTrade"] == per_file["NPCTradeExec"], f"LoadNPCTrade / NPCTradeExec are not 1:1 per file: {dict(per_file['LoadNPCTrade'])} vs {dict(per_file['NPCTradeExec'])}"
    out = {}
    for cmd, spec in OUT_OF_SCOPE.items():
        assert len(found[cmd]) == spec["count"], f"out-of-scope command {cmd}: {len(found[cmd])} sites, pinned {spec['count']} ({found[cmd]})"
        out[cmd] = {"count": len(found[cmd]), "sites": found[cmd], "why": spec["why"]}
    return out


def status_of(site: dict) -> str:
    states = [v["resolution"] for k, v in site.items() if isinstance(v, dict) and "resolution" in v]
    for bad in ("unresolved", "candidates", "version_branch"):
        if bad in states:
            return bad
    return "resolved"


def unresolved_reason(site: dict) -> str:
    parts = []
    for k, v in site.items():
        if isinstance(v, dict) and v.get("resolution") in ("unresolved", "candidates"):
            parts.append(f"{k}: {v.get('reason') or v.get('runtime') or 'candidate set, the runtime choice is not statically known'}" + (f" ({v['detail']})" if v.get("detail") else ""))
    return "; ".join(parts)


# --------------------------------------------------------------------------- reachability
#
# CARD gen4-G2-acq-reachability (docs/gen4/PLAN.md:243 "NPC reachability"). For every script site, derive from the
# pinned SOURCE which story gates guard it:
#   script gates   conditional jumps on every path from a script ENTRY (scr_seq_<token>_NNN label) to the site:
#                  GoToIfSet/Unset FLAG and `Compare VAR,N` + GoToIfEq/Ne/Lt/Gt/Le/Ge, in the polarity that reaches the site
#   trigger gates  how the player starts that entry: the map's zone_event JSON (NPC hide flag `eventFlag`, coord event
#                  var==val, bg event) and the map's `_hdr` script (frame-table InitScriptGoToIfEqual / OnResume ...)
# Every gate carries `cite` = "<repo path>:<line>" of a line holding the named token. Nothing is guessed: what cannot be
# derived is listed in `unresolved` with a reason and the record is `partial` (or `unresolved` when no script entry
# reaches the site). NOT derived (REACHABILITY_SCOPE): how the player gets INTO the map (warp chains, HM/badge gates on
# routes) and the common scripts a site reaches through CallStd (scr_seq member 3).

SCR_DIR = "files/fielddata/script/scr_seq"
EVT_DIR = "files/fielddata/eventdata/zone_event"
EVENT_NARC = "a/0/3/2"
CMP_OP = {"Eq": "==", "Ne": "!=", "Lt": "<", "Gt": ">", "Le": "<=", "Ge": ">="}
NEG_OP = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
TRANSIENT_VARS = ("VAR_TEMP_", "VAR_SPECIAL_", "VAR_OBJ_")
JUMP_RE = re.compile(r"^\s*((?:GoTo|Call)(?:If\w+)?)\b\s*(.*?)\s*(?:@.*)?$")
CASE_RE = re.compile(r"^\s*Case\s+([^,\s]+),\s*(\w+)\s*(?:@.*)?$")
CALLSTD_RE = re.compile(r"^\s*CallStd\s+(\S+)\s*(?:@.*)?$")
READ_ONLY_RE = re.compile(r"^\s*(?:Compare|GoTo\w*|Call\w*|Switch|Case)\b")
TOKEN_RE = re.compile(r"\b((?:FLAG|VAR)_\w+)\b")
COMPARE_RE = re.compile(r"^\s*Compare\s+(\w+),\s*(\S+)\s*$")
REACHABILITY_SCOPE = "in-map script path + the event/header trigger that starts the entry, from pinned SOURCE; the gate flags/vars are NAMED and cited, not traced to the scripts that set them. NOT derived: how the player reaches the map (warp chains, HM/badge route gates) and common scripts reached through CallStd (scr_seq member 3)"


def _gate(kind: str, token: str, scope: str, cite: str, cls: str, **extra) -> dict:
    return {"kind": kind, "token": token, "scope": scope, "class": cls, **extra, "cite": cite}


def _var_class(token: str, via: dict | None) -> str:
    if via and via["cmd"] == "GetGameVersion":
        return "version"
    return "runtime" if token.startswith(TRANSIENT_VARS) else "story"


def gate_key(g: dict) -> tuple:
    return (g["kind"], g["token"], g.get("op") or g.get("state"), str(g.get("value")))


def _gate_order(g: dict) -> tuple:
    f, _, n = g["cite"].rpartition(":")
    return (g["scope"], f, int(n) if n.isdigit() else 0, gate_key(g))  # a cite-less gate must reach verify_reachability, not die here


class Script:
    """One scr_seq .s file as labelled blocks plus the jump graph between them."""

    def __init__(self, rel: str, lines: list[str]):
        self.rel, self.lines = rel, lines
        lab = [(i, m[1]) for i, ln in enumerate(lines) if (m := re.match(r"^(\w+):\s*$", ln))]
        self.starts, self.names = [i for i, _ in lab], [n for _, n in lab]
        self.index = {n: k for k, n in enumerate(self.names)}
        ends = [*self.starts[1:], len(lines)]
        # first unconditional terminator (End/Return/GoTo/...) of each block: lines after it are dead code
        self.term = [next((i for i in range(st + 1, en) if BLOCK_END.match(lines[i])), None) for st, en in zip(self.starts, ends, strict=True)]
        self.preds: dict[int, list[tuple[str, int, int]]] = {k: [] for k in range(len(lab))}
        for i, ln in enumerate(lines):
            tgt = (m := CASE_RE.match(ln)) and m[2] or (m := JUMP_RE.match(ln)) and split_args(m[2])[-1:] and split_args(m[2])[-1]
            if tgt in self.index and (k := self.blk(i)) >= 0 and self.live(k, i):
                self.preds[self.index[tgt]].append(("jump", k, i))
        for k in range(1, len(lab)):
            last = next((lines[x] for x in range(self.starts[k] - 1, self.starts[k - 1], -1) if lines[x].strip()), "")
            if not BLOCK_END.match(last):
                self.preds[k].append(("fall", k - 1, self.starts[k]))
        self.succ: dict[int, list[tuple[int, str, int]]] = {}  # built once: flow() and the CallStd closure both walk it
        for k, ps in self.preds.items():
            for kind, pk, at in ps:
                self.succ.setdefault(pk, []).append((k, kind, at))

    def live(self, k: int, i: int) -> bool:
        """Is line i of block k executable (no unconditional terminator earlier in the block)?"""
        return self.term[k] is None or i <= self.term[k]

    def blk(self, i: int) -> int:
        return bisect.bisect_right(self.starts, i) - 1

    def cite(self, i: int) -> str:
        return f"{self.rel}:{i + 1}"

    def writer(self, i: int, var: str) -> dict | None:
        """The nearest earlier line of the same block that mentions `var` (what fills the compared variable)."""
        for x in range(i - 1, self.starts[self.blk(i)], -1):
            t = self.lines[x].split("@", 1)[0].strip()
            if t and re.search(rf"\b{re.escape(var)}\b", t) and not re.match(r"(Compare|GoTo|Call)", t):
                return {"cmd": t.split()[0], "cite": self.cite(x)}
        return None

    def switch_var(self, i: int) -> tuple[str, int] | None:
        """(variable, line) of the Switch that feeds the Case on line i (nearest earlier Switch of the same block)."""
        for x in range(i - 1, self.starts[self.blk(i)], -1):
            if m := re.match(r"^\s*Switch\s+(\w+)\s*$", self.lines[x]):
                return m[1], x
        return None

    def jump_gate(self, i: int, taken: bool) -> tuple[dict | None, dict | None]:
        """(gate, unresolved) for the jump on line i, in the polarity that reaches the site."""
        if cm := CASE_RE.match(self.lines[i]):
            sw = self.switch_var(i)
            if not sw:
                return None, {"what": f"Case at line {i + 1}", "reason": "no Switch precedes this Case in its block", "cite": self.cite(i)}
            return _gate("var", sw[0], "script", self.cite(sw[1]), _var_class(sw[0], None), op="==" if taken else "!=", value=cm[1]), None
        m = JUMP_RE.match(self.lines[i])
        mn, args = m[1], split_args(m[2])
        if mn in ("GoTo", "Call"):
            return None, None
        suf = mn.split("If", 1)[1]
        if suf in ("Set", "Unset"):
            state = suf.lower() if taken else ("unset" if suf == "Set" else "set")
            return _gate("flag", args[0], "script", self.cite(i), "story", state=state), None
        p = next((x for x in range(i - 1, self.starts[self.blk(i)], -1) if self.lines[x].strip()), None)
        cm = COMPARE_RE.match(self.lines[p]) if p is not None else None
        if suf in CMP_OP and cm:
            via = self.writer(p, cm[1])
            op = CMP_OP[suf] if taken else NEG_OP[CMP_OP[suf]]
            ver = {"versions": [v for v, num in HV.items() if (str(num) == cm[2]) == (op == "==")]} if via and via["cmd"] == "GetGameVersion" and op in ("==", "!=") else {}
            return _gate("var", cm[1], "script", self.cite(p), _var_class(cm[1], via), op=op, value=cm[2], **({"via": via} if via else {}), **ver), None
        return None, {"what": f"condition of {mn} at line {i + 1}", "reason": f"{mn} is not a flag test or a Compare + GoToIfEq/Ne/Lt/Gt/Le/Ge pair, so it is not modelled as a gate", "cite": self.cite(i)}

    def prefix(self, k: int, upto: int) -> list[tuple[dict | None, dict | None]]:
        """Conditional jump lines of block k before `upto`: they were NOT taken on the way to the site."""
        return [self.jump_gate(i, False) for i in range(self.starts[k] + 1, upto) if self.live(k, i) and (CASE_RE.match(self.lines[i]) or ((m := JUMP_RE.match(self.lines[i])) and m[1].startswith("GoToIf")))]

    def flow(self, hit: int) -> dict:
        """Must/may gate sets from every scr_seq_ entry that reaches the site, by dataflow over the label graph (no path
        enumeration: shared subroutines and loops make paths explode). must = on EVERY path entry -> site, may = on SOME.
        Returns {"roots": {entry: (must, may)}, "unresolved": [...], "dead": [...], "reentered": {entry: [lines]}}."""
        hk = self.blk(hit)
        if not self.live(hk, hit):  # the site sits after an End/Return/GoTo of its own block: nothing executes it
            return {"roots": {}, "unresolved": [], "dead": [], "reentered": {}, "relevant": {}, "hk": hk}
        back, todo = {hk}, [hk]  # blocks that can reach the site, not walking past an entry label
        while todo:
            k = todo.pop()
            if self.names[k].startswith("scr_seq_"):
                continue
            for _kind, pk, _at in self.preds[k]:
                if pk not in back:
                    back.add(pk)
                    todo.append(pk)
        roots = sorted(k for k in back if self.names[k].startswith("scr_seq_"))
        dead = sorted(k for k in back if not self.preds[k] and k not in roots)
        out: dict = {"roots": {}, "unresolved": [], "dead": [{"label": self.names[k], "cite": self.cite(self.starts[k])} for k in dead], "reentered": {}, "relevant": {}, "hk": hk}
        un: dict[str, dict] = {}
        edge_cache: dict[tuple, list[dict]] = {}

        def edge(kind: str, pk: int, at: int) -> list[dict]:
            if (kind, pk, at) not in edge_cache:
                parts = self.prefix(pk, at) + [self.jump_gate(at, True) if kind != "fall" else (None, None)]
                for _g, u in parts:
                    if u:
                        un[u["cite"]] = u
                edge_cache[(kind, pk, at)] = [g for g, _u in parts if g]
            return edge_cache[(kind, pk, at)]

        for r in roots:
            if self.preds[r]:
                out["reentered"][self.names[r]] = sorted(at + 1 for _k, _pk, at in self.preds[r])
            fwd, todo = {r}, [r]
            while todo:
                for k, _kind, _at in self.succ.get(todo.pop(), []):
                    if k not in fwd and k in back and not self.names[k].startswith("scr_seq_"):
                        fwd.add(k)
                        todo.append(k)
            must: dict[int, dict | None] = dict.fromkeys(fwd)  # None = every gate (not yet constrained)
            may: dict[int, dict] = {k: {} for k in fwd}
            must[r] = {}
            changed = True
            while changed:
                changed = False
                for k in sorted(fwd - {r}):
                    for kind, pk, at in self.preds[k]:
                        if pk not in fwd:
                            continue
                        eg = {gate_key(g): g for g in edge(kind, pk, at)}
                        for key, g in may[pk].items():
                            if key not in may[k]:
                                may[k][key] = g
                                changed = True
                        for key, g in eg.items():
                            if key not in may[k]:
                                may[k][key] = g
                                changed = True
                        if must[pk] is None:
                            continue
                        inc = {**must[pk], **eg}
                        new = inc if must[k] is None else {key: g for key, g in must[k].items() if key in inc}
                        if must[k] is None or set(new) != set(must[k]):
                            must[k] = new
                            changed = True
            tail = [(g, u) for g, u in self.prefix(hk, hit)]
            for _g, u in tail:
                if u:
                    un[u["cite"]] = u
            tg = {gate_key(g): g for g, _u in tail if g}
            mh, yh = {**(must[hk] or {}), **tg}, {**may[hk], **tg}
            out["roots"][self.names[r]] = (mh, {k: g for k, g in yh.items() if k not in mh})
            out["relevant"][self.names[r]] = sorted(fwd)
        out["unresolved"] = [un[c] for c in sorted(un)]
        return out


class StdScripts:
    """CallStd targets. ScrCmd_CallStd (src/scrcmd_c.c) runs the callee in its own script context while the caller waits,
    so a callee that sets a flag/var the caller then tests is a gate. Resolved like the engine does: `std_*` id
    (include/constants/std_script.h) -> the first sScriptBankMapping row (src/fieldmap.c, descending) with id >= scriptIdLo
    -> scr_seq member + entry (id - scriptIdLo = the ScrDef index). `writes()` = every FLAG_/VAR_ token that a callee closure
    mentions outside a Compare/GoTo/Call/Switch/Case operand (its entry block, everything it can reach, and its own CallStd
    callees): a CONSERVATIVE set of possible writers (a read through a Buffer or message command counts too)."""

    def __init__(self, clone: Path):
        self.clone = clone
        self.consts = {n: int(v) for n, v in re.findall(r"^#define\s+(\w+)\s+(\d+)\b", base.read(clone, "include/constants/std_script.h"), re.M)}
        rows = re.findall(r"^\s*\{\s*(\w+),\s*NARC_scr_seq_scr_seq_(\d+)_bin,", base.read(clone, "src/fieldmap.c"), re.M)
        self.banks = [(int(lo) if lo.isdigit() else self.consts[lo], int(member)) for lo, member in rows]
        assert len(self.banks) == 30 and [b[0] for b in self.banks] == sorted((b[0] for b in self.banks), reverse=True), "sScriptBankMapping drifted (30 rows, descending)"
        self._scripts: dict[int, Script] = {}
        self._writes: dict[tuple[int, str], dict[str, str]] = {}

    def script(self, member: int) -> Script:
        if member not in self._scripts:
            (path,) = sorted((self.clone / SCR_DIR).glob(f"scr_seq_{member:04d}*.s"))
            self._scripts[member] = Script(f"{SCR_DIR}/{path.name}", path.read_text(encoding="utf-8", errors="replace").splitlines())
        return self._scripts[member]

    def resolve(self, arg: str) -> dict | None:
        sid = self.consts.get(arg)
        if sid is None:
            return None
        lo, member = next((b for b in self.banks if sid >= b[0]), (None, None))
        if lo is None:
            return None
        sc = self.script(member)
        defs = [m[1] for ln in sc.lines if (m := re.match(r"^\s*ScrDef\s+(\w+)", ln))]
        if sid - lo >= len(defs) or defs[sid - lo] not in sc.index:
            return None
        return {"std": arg, "id": sid, "member": member, "entry": defs[sid - lo], "callee_cite": sc.cite(sc.starts[sc.index[defs[sid - lo]]])}

    def writes(self, member: int, entry: str, _seen: frozenset = frozenset()) -> dict[str, str]:
        """token -> cite of its first mention in the callee closure."""
        if (member, entry) in self._writes:
            return self._writes[(member, entry)]
        sc, out = self.script(member), {}
        todo, seen = [sc.index[entry]], set()
        me = _seen | {(member, entry)}
        while todo:
            k = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            todo += [n for n, _kind, _at in sc.succ.get(k, [])]
            stop = len(sc.lines) if k + 1 >= len(sc.starts) else sc.starts[k + 1]
            for i in range(sc.starts[k] + 1, stop):
                t = sc.lines[i].split("@", 1)[0]
                if (m := CALLSTD_RE.match(t)) and (r := self.resolve(m[1])) and (r["member"], r["entry"]) not in me:
                    for tok, cite in self.writes(r["member"], r["entry"], me).items():
                        out.setdefault(tok, cite)
                if t.strip() and not READ_ONLY_RE.match(t):
                    for tok in TOKEN_RE.findall(t):
                        out.setdefault(tok, sc.cite(i))
        self._writes[(member, entry)] = out
        return out


def parse_events(text: str) -> dict[str, list[dict]]:
    """zone_event JSON (pret's 2-space pretty print) -> {section: [{field: (value, line)}]}, line numbers kept for cites."""
    out: dict[str, list[dict]] = {}
    sec, cur = None, None
    for n, ln in enumerate(text.splitlines(), 1):
        if m := re.match(r'^  "(\w+)": \[\s*$', ln):
            sec = m[1]
            out[sec] = []
        elif sec and re.match(r"^    \{\s*$", ln):
            cur = {}
            out[sec].append(cur)
        elif cur is not None and (m := re.match(r'^      "(\w+)": (.*?),?\s*$', ln)):
            cur[m[1]] = (m[2].strip('"'), n)
        elif re.match(r"^    \},?\s*$", ln):
            cur = None
    return out


class MapSources:
    """The event + header sources of one map token."""

    def __init__(self, clone: Path, token: str):
        self.token = token
        ev = sorted((clone / EVT_DIR).glob(f"[0-9][0-9][0-9]_{token}.json"))
        hdr = sorted((clone / SCR_DIR).glob(f"scr_seq_[0-9][0-9][0-9][0-9]_{token}_hdr.s"))
        self.event_rel = ev[0].relative_to(clone).as_posix() if len(ev) == 1 else None
        self.event_member = int(ev[0].name[:3]) if len(ev) == 1 else None
        self.hdr_rel = hdr[0].relative_to(clone).as_posix() if len(hdr) == 1 else None
        self.hdr_member = int(hdr[0].name[8:12]) if len(hdr) == 1 else None
        self.events = parse_events(ev[0].read_text(encoding="utf-8")) if ev else {}
        self.hdr_lines = hdr[0].read_text(encoding="utf-8", errors="replace").splitlines() if hdr else []
        if ev:  # the line-based parse must agree with the real JSON, or its cites are not trustworthy
            real = json.loads(ev[0].read_text(encoding="utf-8"))
            for sec, rows in self.events.items():
                assert len(rows) == len(real[sec]), f"{self.event_rel}: parsed {len(rows)} {sec}, json has {len(real[sec])}"

    def triggers(self, nnn: str) -> list[dict]:
        """Everything in the map's events / header that starts script entry scr_seq_<token>_<nnn>."""
        want = f"_EV_scr_seq_{self.token}_{nnn} + 1"
        out = []
        for sec, kind in (("objects", "npc"), ("bgs", "bg_event"), ("coords", "coord_event")):
            for row in self.events.get(sec, []):
                if row.get("scriptId", ("",))[0] != want:
                    continue
                gates = []
                if kind == "npc" and row["eventFlag"][0] not in ("0", "FLAG_NOTHING"):
                    gates.append(_gate("flag", row["eventFlag"][0], "npc_visibility", f"{self.event_rel}:{row['eventFlag'][1]}", "story", state="unset"))
                if kind == "coord_event":
                    gates.append(_gate("var", row["var"][0], "trigger", f"{self.event_rel}:{row['var'][1]}", _var_class(row["var"][0], None), op="==", value=row["val"][0]))
                out.append({"kind": kind, "cite": f"{self.event_rel}:{row['scriptId'][1]}", "gates": gates})
        for n, ln in enumerate(self.hdr_lines, 1):
            t = ln.split("@", 1)[0].strip()
            if re.search(rf"_EV_scr_seq_{self.token}_{nnn}\b", t):
                mn = t.split()[0]
                gates = []
                if mn == "InitScriptGoToIfEqual":
                    var, val_, _dest = split_args(t[len(mn) :])
                    gates.append(_gate("var", var, "trigger", f"{self.hdr_rel}:{n}", _var_class(var, None), op="==", value=val_))
                out.append({"kind": f"map_script:{mn}", "cite": f"{self.hdr_rel}:{n}", "gates": gates})
        return out


def callstd_check(script: Script, std, fl: dict, hit: int, entries: list[dict]) -> tuple[dict, list[dict]]:
    """Every CallStd on a path to the site (blocks that can reach it; lines before the site, or before the block's
    terminator): list it, resolve it, and flag any token its callee closure may write that a script gate of this record
    tests, unless the caller refills that variable itself after the call. Returns ({calls, conflicts}, unresolved)."""
    calls: dict[int, dict] = {}
    un: list[dict] = []
    for k in sorted({k for ks in fl["relevant"].values() for k in ks}):
        stop = hit if k == fl["hk"] else (script.starts[k + 1] if k + 1 < len(script.starts) else len(script.lines))
        for i in range(script.starts[k] + 1, stop):
            if script.live(k, i) and (m := CALLSTD_RE.match(script.lines[i])):
                res = std.resolve(m[1])
                if res is None:
                    un.append({"what": f"CallStd {m[1]}", "reason": "target is not a std_script.h id that maps to a scr_seq entry, so its callee cannot be checked for gates", "cite": script.cite(i)})
                else:
                    calls[i] = {**res, "cite": script.cite(i)}
    gates = {gate_key(g): g for e in entries for g in (*e["script_gates"], *e["path_dependent_gates"]) if g["scope"] == "script"}
    conflicts = []
    for i, c in sorted(calls.items()):
        for tok, wcite in sorted(std.writes(c["member"], c["entry"]).items()):
            for g in (g for g in gates.values() if g["token"] == tok):
                via = int(g["via"]["cite"].rpartition(":")[2]) - 1 if g.get("via") else None
                if via is not None and via > i and script.blk(via) == script.blk(i):
                    continue  # the caller refills the variable after the call, so the callee write cannot reach this test
                conflicts.append({"call": c["cite"], "std": c["std"], "token": tok, "write_cite": wcite, "gate_cite": g["cite"]})
    conflicts = list({(c["call"], c["token"], c["gate_cite"]): c for c in conflicts}.values())
    for c in conflicts:
        un.append({"what": f"CallStd {c['std']} may write {c['token']}", "reason": f"the callee writes {c['token']} (see write_cite) and the caller tests it at {c['gate_cite']}; a gate set inside a CallStd callee is not derived", "cite": c["call"]})
    return {"calls": [c for _i, c in sorted(calls.items())], "conflicts": sorted(conflicts, key=lambda c: (c["call"], c["token"]))}, un


def reachability(script: Script, ms: MapSources, hit: int, mid: int, const: str, std) -> dict:
    fl = script.flow(hit)
    un = list(fl["unresolved"])
    rec = {
        "map": {"id": mid, "const": const, "token": ms.token},
        "sources": {
            "script": script.rel,
            "events": {"file": ms.event_rel, "narc": EVENT_NARC, "member": ms.event_member} if ms.event_rel else None,
            "header": {"file": ms.hdr_rel, "narc": SCRIPT_NARC, "member": ms.hdr_member} if ms.hdr_rel else None,
        },
    }
    if fl["dead"]:
        rec["dead_blocks_ignored"] = fl["dead"]  # no jump references them: unreachable, so they carry no path (not a gap)
    if not fl["roots"]:
        un.append({"what": "entry", "reason": "no scr_seq_ entry label reaches the site by Call/GoTo/Case/fall-through", "cite": script.cite(hit)})
        return rec | {"entries": [], "gates": [], "callstd": {"calls": [], "conflicts": []}, "status": "unresolved", "unresolved": un}
    entries, combos = [], []
    for r, (must, may) in fl["roots"].items():
        m = re.fullmatch(rf"scr_seq_{re.escape(ms.token)}_(\d{{3}})", r)
        trig = ms.triggers(m[1]) if m else []
        at = script.cite(script.starts[script.index[r]])
        if not trig:
            why = "no object/bg/coord event in the map's zone_event JSON and no header script entry starts it (reached from another script file, or unused)"
            un.append({"what": f"trigger of {r}", "reason": why if m else "entry label is not scr_seq_<map token>_NNN, so it cannot be matched to this map's events", "cite": at})
        if r in fl["reentered"]:
            un.append({"what": f"entry {r} is also jumped to", "reason": f"lines {fl['reentered'][r]} jump to this entry label, so another entry reaches the site through it and that entry's trigger is not listed", "cite": at})
        entries.append({"entry": r, "script_gates": sorted(must.values(), key=_gate_order), "path_dependent_gates": sorted(may.values(), key=_gate_order), "triggers": trig})
        combos += [{**must, **{gate_key(g): g for g in t["gates"]}} for t in (trig or [{"gates": []}])]
    nec = set.intersection(*(set(c) for c in combos))
    gates = sorted((next(c[k] for c in combos if k in c) for k in nec), key=_gate_order)
    cs, cun = callstd_check(script, std, fl, hit, entries)
    un = list({(u["what"], u["cite"]): u for u in [*un, *cun]}.values())
    rec |= {"entries": entries, "gates": gates, "callstd": cs, "status": "partial" if un else "resolved", "unresolved": un}
    if not gates and not un:  # resolved with nothing to cite: say why, with the entry labels as evidence
        counts = [(e["entry"], len(e["script_gates"]) + max((len(t["gates"]) for t in e["triggers"]), default=0)) for e in entries]
        why = "entries_have_disjoint_gate_sets" if any(n for _e, n in counts) else "no_gate_on_any_route"
        rec["empty_gates"] = {"reason": why, "entries": [{"entry": e, "gate_count": n, "cite": script.cite(script.starts[script.index[e]])} for e, n in counts]}
    return rec


def iter_gates(rec: dict):
    """Every gate dict in a reachability record (top-level, per-entry script/path gates, trigger gates)."""
    yield from rec["gates"]
    for e in rec["entries"]:
        yield from e["script_gates"]
        yield from e["path_dependent_gates"]
        for t in e["triggers"]:
            yield from t["gates"]


def cite_problem(clone: Path, who: str, cite: str | None, token: str | None) -> list[str]:
    if not cite or not token or ":" not in cite:
        return [f"{who}: uncited"]
    rel, _, n = cite.rpartition(":")
    path = clone / rel
    if not path.is_file() or not n.isdigit():
        return [f"{who}: cite {cite} names no file"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not 1 <= int(n) <= len(lines) or token not in lines[int(n) - 1]:
        return [f"{who}: cite {cite} does not hold {token}"]
    return []


def verify_reachability(clone: Path, sites: list[dict]) -> list[str]:
    """Problems: a site without a record, a gate or trigger without a cite, or a cite whose file:line is absent or lacks the token."""
    problems = []
    for s in sites:
        rec = s.get("reachability")
        if not rec:
            problems.append(f"{s['id']}: no reachability record")
            continue
        if rec["status"] not in ("resolved", "partial", "unresolved") or (rec["status"] == "resolved") != (not rec["unresolved"]):
            problems.append(f"{s['id']}: reachability status {rec['status']!r} does not match its unresolved list")
        if rec["status"] == "resolved" and not rec["gates"]:
            ej = rec.get("empty_gates")
            if not ej or not ej.get("entries"):
                problems.append(f"{s['id']}: resolved with empty gates and no justification (`empty_gates`)")
            for e in (ej or {}).get("entries", []):
                problems += cite_problem(clone, f"{s['id']} empty gates {e.get('entry')}", e.get("cite"), e.get("entry"))
        if "callstd" not in rec:
            problems.append(f"{s['id']}: no callstd check recorded")
        for c in rec.get("callstd", {}).get("calls", []):
            problems += cite_problem(clone, f"{s['id']} CallStd {c['std']}", c.get("cite"), f"CallStd {c['std']}")
            problems += cite_problem(clone, f"{s['id']} callee {c['entry']}", c.get("callee_cite"), c["entry"])
        for g in iter_gates(rec):
            problems += cite_problem(clone, f"{s['id']} gate {g.get('token')}", g.get("cite"), g.get("token"))
        for t in (t for e in rec["entries"] for t in e["triggers"]):
            problems += cite_problem(clone, f"{s['id']} trigger {t['kind']}", t.get("cite"), "_EV_scr_seq_")
    return problems


# --------------------------------------------------------------------------- hge mode
#
# The hg-engine fork (pinned commit) builds the ROM data/games/gen4_hge describes. What carries over from the
# vanilla inventory and what does not (docs/gen4/research/hge_data_delta.md section 4):
#   script sites / npc records / runtime branches  carry over IF the script NARC members holding the sites and the
#                  trade NARC are byte-identical in the two ROMs -- compared here, a difference fails generation
#   C producers    do NOT carry over: hge replaces engine functions (hooks file) with its own C in src/. The hge
#                  inventory is scanned from the fork's src/ and classified like the vanilla one; each vanilla
#                  producer is then marked replaced / patched_inline / kept by resolving the hooks to vanilla
#                  functions (xMAP address ranges). Hooks are written in the fork's `hooks` file as
#                  `<arm9|overlay> <name> <addr> [reg]`; an address is absolute (02xxxxxx) or an offset form
#                  (08xxxxxx = 0x02000000 + offset for arm9, overlay RAM base + offset otherwise).

HGE_SCHEMA = "gen4-hge-acquisition-v1"
HGE_OUT = base.REPO / "data" / "games" / "gen4_hge"
SCRIPT_NARC, TRADE_NARC = "a/0/1/2", "a/1/1/2"
COMMON_SCRIPT_MEMBER = 3  # scr_seq_0003: the common scripts reached through CallStd (std_* ids 2000-2499 and others)
# "GiveEgg" below is the vanilla C function (shared implementation), NOT the script command of the same name:
# the command's handler ScrCmd_GiveEgg is the one the fork replaces (see HGE_PRODUCERS and script_dispatch).
HGE_C_APIS = (
    "PokeParty_Add",
    "Party_AddMon",
    "PokeParaSet",
    "CreateBoxMonData",
    "SetEggStats",
    "GiveMon",
    "GiveEgg",
    "Party_SafeCopyMonToSlot_ResetAprijuiceModifiers",
    "PCStorage_PlaceMonInFirstEmptySlotInAnyBox",
    "PCStorage_PlaceMonInBoxFirstEmptySlot",
    "PCStorage_PlaceMonInBoxByIndexPair",
)
DIRECT_WRITE = "party_slot_write_from_save_misc"  # pseudo-API: `*slot = saveMiscData->storedMons[..]` (DNA Splicers)
DIRECT_WRITE_RE = re.compile(r"\*\w+\s*=\s*saveMiscData->storedMons\[")

# Fork call sites. Key = (file, enclosing function, API); n = ACTIVE call sites (preprocessor-evaluated against
# include/config.h + include/debug.h), inactive = call sites compiled out. `hook` = the hooks-file name that
# routes vanilla code to the function (default = the function name; None = reached only from other fork C).
HGE_PRODUCERS: dict[tuple[str, str, str], dict] = {
    ("src/field/enemy_party.c", "AddWildPartyPokemon", "PokeParty_Add"): _p(n=1, cls="not_acquisition", kind="wild_enemy_generation", note="wild enemy into the BattleSetup party (replaces addGeneratedMonToBattleSetupParty); catching still goes through the kept Task_GetPokemon"),
    ("src/field/enemy_party.c", "MakeTrainerPokemonParty", "PokeParaSet"): _p(n=1, cls="not_acquisition", kind="trainer_party", note="builds a trainer's enemy party (replaces CreateNPCTrainerParty)"),
    ("src/field/enemy_party.c", "MakeTrainerPokemonParty", "PokeParty_Add"): _p(n=1, cls="not_acquisition", kind="trainer_party", note="one loop call (vanilla has 4 unrolled call sites)"),
    ("src/field/script_commands.c", "ScrCmd_GiveEgg", "PokeParty_Add"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveEgg"], note="GiveEgg command: species arg is species|form<<11, honours the hidden-ability script flag"),
    ("src/field/script_commands.c", "ScrCmd_GiveEgg", "SetEggStats"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveEgg"], note="egg creation (level 1)"),
    ("src/field/script_commands.c", "ScrCmd_GiveTogepiEgg", "PokeParty_Add"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveTogepiEgg"], note="Mr. Pokemon's Togepi egg; the fork then reads the freed buffer for SaveMisc_SetTogepiPersonalityGender (use after free)"),
    ("src/field/script_commands.c", "ScrCmd_GiveTogepiEgg", "SetEggStats"): _p(n=1, cls="acquisition", kind="egg", scripts=["GiveTogepiEgg"], note="Togepi egg creation (species fixed in C, level 1, Extrasensory added)"),
    ("src/field_roamer.c", "Save_CreateRoamerByID", "PokeParaSet"): _p(n=1, cls="not_acquisition", kind="roamer_generation", scripts=["CreateRoamer"], note="temp mon whose IVs/personality seed the roamer save record; the catch goes through the kept Task_GetPokemon"),
    ("src/individual/PartyMenu_HandleUseItemOnMon.c", "UseItemMonAttrChangeCheck", DIRECT_WRITE): _p(n=1, cls="not_acquisition", kind="dna_splicers_restore", hook="PartyMenu_HandleUseItemOnMon", open_question="DNA Splicers move the fused Reshiram/Zekrom out of the party into save misc storage (storedMons) and write it back; while stored it is in neither party nor box, so the storage watcher must treat the restore as a known-key party gain", note="direct struct write into the party slot, no PokeParty_Add; hge-only mechanic"),
    ("src/npc_trade.c", "_CreateTradeMon", "PokeParaSet"): _p(n=1, cls="acquisition", kind="npc_trade_mon", scripts=["LoadNPCTrade", "GiveLoanMon"], note="builds the received/loaned mon from the NPCTrade record; insertion stays in the kept vanilla NPCTrade_ReceiveMonToSlot / NPCTrade_MakeAndGiveLoanMon"),
    ("src/pokemon.c", "GiveMon", "PokeParaSet"): _p(n=1, cls="script_dispatch", kind="gift", scripts=["GiveMon"], note="shared GiveMon helper (replaced): adds forme/ability/ball/encounterType args"),
    ("src/pokemon.c", "GiveMon", "PokeParty_Add"): _p(n=1, cls="script_dispatch", kind="gift", scripts=["GiveMon"], note="shared GiveMon helper adds to the party and updates the Pokedex"),
    ("src/pokemon_storage_system.c", "PCStorage_InitializeBoxes", "CreateBoxMonData"): _p(n=0, inactive=1, cls="not_acquisition", kind="debug_pc_fill", note="compiled out: DEBUG_INIT_PC_BOXES_WITH_MONS is not defined"),
    ("src/pokemon_storage_system.c", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox", "PCStorage_PlaceMonInBoxFirstEmptySlot"): _p(n=1, cls="infrastructure", kind="storage_helper", note="internal call of the storage helper itself"),
    ("src/starters.c", "CreateStarter_CreateMon", "PokeParaSet"): _p(n=1, cls="acquisition", kind="starter", scripts=["ChooseStarter"], hook="CreateStarterMon_hook", note="wraps the CreateMon call inside the kept vanilla CreateStarter so starters can carry a form; Party_AddMon is the kept vanilla call"),
    ("src/test_battle.c", "TestBattle_OverridePokemon", "PokeParaSet"): _p(n=0, inactive=1, cls="not_acquisition", kind="debug_test_battle", hook=None, note="compiled out: DEBUG_BATTLE_SCENARIOS is not defined"),
    ("src/test_battle.c", "TestBattle_OverrideParties", "PokeParaSet"): _p(n=0, inactive=1, cls="not_acquisition", kind="debug_test_battle", hook=None, note="compiled out: DEBUG_BATTLE_SCENARIOS is not defined"),
    ("src/test_battle.c", "TestBattle_OverrideParties", "PokeParty_Add"): _p(n=0, inactive=1, cls="not_acquisition", kind="debug_test_battle", hook=None, note="compiled out: DEBUG_BATTLE_SCENARIOS is not defined"),
}
# Fork definitions of the insert/create primitives the producers go through. Key = (file, API).
HGE_DEFINITIONS: dict[tuple[str, str], dict] = {
    ("src/pokemon.c", "GiveMon"): _p(n=1, cls="script_dispatch", kind="gift", scripts=["GiveMon"], note="replaces the vanilla GiveMon helper; the script command ScrCmd_GiveMon is kept"),
    ("src/pokemon.c", "CreateBoxMonData"): _p(n=1, cls="infrastructure", kind="mon_creation_core", note="replaces vanilla CreateBoxMon (CreateMon calls it): EVERY mon built with CreateMon/PokeParaSet on hge goes through this function"),
    ("src/pokemon_storage_system.c", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox"): _p(n=1, cls="infrastructure", kind="storage_insert", note="30-box rewrite; callers: bug-contest result with a full party, Pal Park (vanilla code, kept)"),
    ("src/pokemon_storage_system.c", "PCStorage_PlaceMonInBoxFirstEmptySlot"): _p(n=1, cls="infrastructure", kind="storage_insert", note="30-box rewrite; the party-full catch store (Task_GetPokemon, kept)"),
    ("src/pokemon_storage_system.c", "PCStorage_PlaceMonInBoxByIndexPair"): _p(n=1, cls="infrastructure", kind="storage_move", note="PC deposit/withdraw/move of an existing mon; not an acquisition"),
}
# Hooked functions that touch mons but neither create nor insert one (recorded so they are not mistaken for producers).
HGE_REPLACED_OTHER = {
    "sub_0206D328": ("hatch_stats", "egg -> mon hatch rewrite (carries over the hidden ability); the hatch is the O-15 gift catch of the vanilla daycare egg"),
    "GetMonEvolution": ("evolution_dispatch", "evolution dispatch replaced (species change of an existing mon, same key)"),
    "SetFixedWildEncounter": ("wild_slot_choice", "hooks:469 patches vanilla chooseAbilityCoercedSlot (static/magnet-pull slot choice), not a mon producer"),
    "ScrCmd_CreateRoamer": ("roamer_script_command", "script command shim in src/script_new_cmds.c; calls the replaced Save_CreateRoamerByID"),
    "Save_CreateRoamerByID": ("roamer_save_record", "builds the roamer save record (see the PokeParaSet row)"),
    "ScrCmd_DaycareSanitizeMon": ("daycare_sanitize", "daycare sanitize script command"),
    "SetupAndStartTutorialBattle": ("tutorial_battle", "tutorial battle setup; synthetic parties, the save is untouched"),
}
HGE_NOTES = {
    ("src/battle/battle_command.c", "Task_GetPokemon"): "inline hooks are capture-experience and critical-capture, not the catch store; the Party_AddMon call is shared and the PC call lands in hge's replaced PCStorage_PlaceMonInBoxFirstEmptySlot. Byte-level equality of the call sites is not checked (SOURCE only)",
    ("src/npc_trade.c", "NPCTrade_ReceiveMonToSlot"): "the received mon is built by the replaced _CreateTradeMon in the trade-work setup (another function); this slot copy is kept",
    ("src/get_egg.c", "GiveEggToPlayer"): "daycare egg creation is kept; the later hatch goes through the replaced sub_0206D328 (see replaced_non_producers)",
    ("src/choose_starter.c", "CreateStarter"): "inline hooks wrap the species list, the CreateMon call (CreateStarter_CreateMon, forms) and the hidden ability; the Party_AddMon call is kept",
}
HGE_FACT_FILES = ["src/starters.c", "src/field_roamer.c", "src/field/script_commands.c", "rom.ld"]
ROAMER_RE = re.compile(r"case (ROAMER_\w+):\s*species = (SPECIES_\w+);\s*level = (\d+);")


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match[0])


def code_lines(path: Path) -> list[str]:
    """Source lines with /* */ and // comments blanked (line numbers preserved)."""
    text = re.sub(r"/\*.*?\*/", _blank, path.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    return [ln.split("//", 1)[0] for ln in text.splitlines()]


_PP = re.compile(r"\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)")


def active_map(lines: list[str], defined: set[str]) -> list[bool]:
    """Per line: is it compiled in? Handles #ifdef/#ifndef/#if defined(..) &&,||/#else/#endif against `defined`."""
    stack: list[tuple[bool, bool]] = []
    cur, out = True, []
    for line in lines:
        m = _PP.match(line)
        if m:
            d, rest = m[1], m[2].strip()
            if d in ("ifdef", "ifndef"):
                c = (rest.split()[0] in defined) == (d == "ifdef")
            elif d == "if":
                expr = re.sub(r"defined\s*\(?\s*(\w+)\s*\)?", lambda x: str(x[1] in defined), rest).replace("&&", " and ").replace("||", " or ")
                if not re.fullmatch(r"(True|False|and|or|\(|\)|\s)+", expr):
                    raise ValueError(f"unsupported preprocessor condition: #if {rest}")
                c = eval(expr)  # noqa: S307 -- charset-checked above
            elif d == "elif":
                raise ValueError("#elif is not supported")
            if d in ("ifdef", "ifndef", "if"):
                stack.append((cur, c))
                cur = cur and c
            elif d == "else":
                par, c = stack[-1]
                cur = par and not c
            else:  # endif
                cur = stack.pop()[0]
        out.append(cur)
    return out


def enclosing(lines: list[str], i: int) -> str | None:
    for j in range(i, -1, -1):
        ln = re.sub(r"__attribute__\(\((?:[^()]|\([^()]*\))*\)\)\s*", "", lines[j])
        if re.match(r"^[A-Za-z_][\w\s\*]*\b(\w+)\([^;]*$", ln) and not ln.startswith(("static const", "return", "else", "if", "for", "while", "switch")):
            return re.match(r"^[A-Za-z_][\w\s\*]*?\b(\w+)\(", ln)[1]
    return None


def fork_defines(src: Path) -> set[str]:
    out: set[str] = set()
    for rel in ("include/config.h", "include/debug.h"):
        out |= set(re.findall(r"^\s*#\s*define\s+(\w+)", (src / rel).read_text(encoding="utf-8"), re.M))
    return out


def scan_hge_c(src: Path, defined: set[str]) -> tuple[list[dict], list[dict], list[str]]:
    """Scan src/**/*.c of the fork. Returns (call producers, definitions, problems); anything not in
    HGE_PRODUCERS / HGE_DEFINITIONS (or a changed count) is a problem and fails generation."""
    pat = re.compile(r"(?<![\w])(" + "|".join(HGE_C_APIS) + r")\(")
    calls: dict[tuple[str, str, str], dict[str, list[int]]] = {}
    defs: dict[tuple[str, str], list[int]] = {}
    for p in sorted((src / "src").rglob("*.c")):
        rel = p.relative_to(src).as_posix()
        lines = code_lines(p)
        if not any(pat.search(ln) or DIRECT_WRITE_RE.search(ln) for ln in lines):
            continue  # only files holding a producer need their #if state evaluated
        try:
            act = active_map(lines, defined)
        except ValueError as exc:
            raise names.Mismatch(f"{rel}: {exc}") from exc
        for i, line in enumerate(lines):
            m = pat.search(line)
            api = m[1] if m else DIRECT_WRITE if DIRECT_WRITE_RE.search(line) else None
            if api is None:
                continue
            if line[:1] in " \t" or api == DIRECT_WRITE:
                slot = calls.setdefault((rel, enclosing(lines, i), api), {"lines": [], "inactive_lines": []})
                slot["lines" if act[i] else "inactive_lines"].append(i + 1)
            elif ";" not in line and re.match(r"^[A-Za-z_][\w\s\*]*\b" + api + r"\(", re.sub(r"__attribute__\(\((?:[^()]|\([^()]*\))*\)\)\s*", "", line)):
                if act[i]:
                    defs.setdefault((rel, api), []).append(i + 1)
    problems = []
    for key, got in calls.items():
        want = HGE_PRODUCERS.get(key)
        if want is None:
            problems.append(f"unclassified hge C producer {key} at lines {got['lines'] + got['inactive_lines']}: classify it in HGE_PRODUCERS")
        elif (want["n"], want.get("inactive", 0)) != (len(got["lines"]), len(got["inactive_lines"])):
            problems.append(f"hge C producer {key} has {len(got['lines'])} active / {len(got['inactive_lines'])} inactive call sites, table says {want['n']} / {want.get('inactive', 0)}")
    problems += [f"classified hge C producer {k} no longer found in the source" for k in HGE_PRODUCERS if k not in calls]
    for key, lns in defs.items():
        want = HGE_DEFINITIONS.get(key)
        if want is None:
            problems.append(f"unclassified hge C definition {key} at lines {lns}: classify it in HGE_DEFINITIONS")
        elif want["n"] != len(lns):
            problems.append(f"hge C definition {key} has {len(lns)} definitions, table says {want['n']}")
    problems += [f"classified hge C definition {k} no longer found in the source" for k in HGE_DEFINITIONS if k not in defs]
    out = [{"file": k[0], "function": k[1], "api": k[2], **got, **{a: b for a, b in HGE_PRODUCERS[k].items() if a not in ("n", "inactive")}} for k, got in sorted(calls.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2])) if k in HGE_PRODUCERS]
    odefs = [{"file": k[0], "api": k[1], "lines": defs[k], **{a: b for a, b in HGE_DEFINITIONS[k].items() if a != "n"}} for k in sorted(defs) if k in HGE_DEFINITIONS]
    return out, odefs, problems


# ---- vanilla address space: xMAP functions, main.lsf regions, hooks

XMAP_FN = re.compile(r"^\s+([0-9A-F]{8}) ([0-9A-F]{8}) \.text\s+(\w+)\s+\((\w+)\.o\)", re.M)


def locate_xmap(arg: str | None) -> Path:
    path = Path(arg or gen4_pins.default_locations().assets["heartgold_xmap"])
    if not path.is_file():
        raise names.Absent(f"heartgold_xmap not found at {path} (pass --xmap)")
    want = gen4_pins.MAP_SPECS["heartgold_xmap"][0]
    have = hashlib.sha256(path.read_bytes()).hexdigest()
    if have != want:
        raise names.Mismatch(f"{path} sha256 {have} != pinned {want} (heartgold_xmap)")
    return path


class Vanilla:
    """Vanilla HG functions (xMAP), their region (arm9 / overlay id from main.lsf) and the fork's active hooks."""

    def __init__(self, xmap: Path, lsf_text: str, bases: dict[int, int], hooks_text: str, defined: set[str]):
        self.funcs = [(int(a, 16), int(s, 16), n, o) for a, s, n, o in XMAP_FN.findall(xmap.read_text(encoding="utf-8", errors="replace")) if int(s, 16)]
        self.region: dict[str, str | int] = {}
        cur: str | int | None = None
        ov = -1
        for line in lsf_text.splitlines():
            s = line.strip()
            if s.startswith("Static "):
                cur = "arm9"
            elif s.startswith("Overlay "):
                ov += 1
                cur = ov
            m = re.match(r"Object\s+\S*?(\w+)\.o$", s)
            if m and cur is not None:
                self.region.setdefault(m[1], cur)
        by_region: dict[str | int, list[tuple[int, int, str, str]]] = {}
        for f in sorted(set(self.funcs)):
            if f[3] in self.region:
                by_region.setdefault(self.region[f[3]], []).append(f)
        for reg, fs in by_region.items():  # containing() takes the first hit: overlapping ranges would misclassify silently
            far = fs[0]  # the entry with the greatest end so far: every entry is compared against it, not just its neighbour
            for b in fs[1:]:
                a = far
                if a[0] + a[1] > b[0]:
                    raise names.Mismatch(f"xMAP functions overlap in region {reg}: {a[2]} ({a[3]}.o {a[0]:08X}+{a[1]:X}) and {b[2]} ({b[3]}.o {b[0]:08X}+{b[1]:X})")
                if b[0] + b[1] > far[0] + far[1]:
                    far = b
        lines = hooks_text.splitlines()
        self.hooks, self.skipped = [], 0
        for ln, act in zip(lines, active_map(lines, defined), strict=True):
            p = ln.split()
            if not act or ln.lstrip().startswith("#") or len(p) < 3 or not re.fullmatch(r"[0-9A-Fa-f]{8}", p[2]):
                continue
            region: str | int = "arm9" if p[0] == "arm9" else int(p[0])
            raw = int(p[2], 16)
            if raw >> 24 == 2:
                addr = raw
            elif raw >> 24 == 8:
                base_addr = 0x02000000 if region == "arm9" else bases.get(region)
                if base_addr is None:  # overlay id unknown to the ROM's overlay table: cannot resolve, count it
                    self.skipped += 1
                    continue
                addr = base_addr + (raw & 0xFFFFFF)
            else:
                self.skipped += 1
                continue
            self.hooks.append({"region": region, "name": p[1], "addr": addr})

    def find(self, name: str, obj: str | None = None) -> list[tuple[int, int, str, str]]:
        return [f for f in self.funcs if f[2] == name and (obj is None or f[3] == obj)]

    def containing(self, region, addr: int):
        return next((f for f in self.funcs if self.region.get(f[3]) == region and f[0] <= addr < f[0] + f[1]), None)

    def replaced_names(self) -> set[str]:
        """Vanilla functions whose entry bytes a hook overwrites (full replacement)."""
        out = set()
        for h in self.hooks:
            fn = self.containing(h["region"], h["addr"])
            if fn and fn[0] == h["addr"]:
                out.add(fn[2])
        return out

    def hooks_in(self, fn) -> list[dict]:
        return [h for h in self.hooks if h["region"] == self.region.get(fn[3]) and fn[0] <= h["addr"] < fn[0] + fn[1]]

    def status(self, fn) -> tuple[str, list[dict]]:
        hs = self.hooks_in(fn)
        return ("replaced" if any(h["addr"] == fn[0] for h in hs) else "patched_inline" if hs else "kept"), hs


# ---- the two ROMs

@functools.cache
def _rom(path: str):
    import ndspy.rom

    return ndspy.rom.NintendoDSRom.fromFile(path)


@functools.cache
def narc_member_hashes(rom: str, narc: str) -> tuple[str, ...]:
    """sha256 of every member of a NARC inside the ROM (ndspy)."""
    import ndspy.narc

    return tuple(hashlib.sha256(f).hexdigest() for f in ndspy.narc.NARC(_rom(rom).getFileByName(narc)).files)


@functools.cache
def overlay_bases(rom: str) -> dict[int, int]:
    return {i: o.ramAddress for i, o in _rom(rom).loadArm9Overlays().items()}


def script_member_proof(vanilla: str, hge: str, sites: list[dict]) -> tuple[dict, dict, list[str]]:
    """Hash every NARC member in both ROMs. The members holding the sites and every trade record must be equal."""
    problems = []
    v, h = narc_member_hashes(vanilla, SCRIPT_NARC), narc_member_hashes(hge, SCRIPT_NARC)
    if len(v) != len(h):
        problems.append(f"{SCRIPT_NARC} has {len(v)} members in the vanilla ROM and {len(h)} in the hge ROM")
    members = {int(re.match(r"scr_seq_(\d+)_", s["file"])[1]): s["file"] for s in sites}
    proof = {}
    for n in sorted(members):
        if n >= min(len(v), len(h)):
            problems.append(f"{SCRIPT_NARC} member {n} ({members[n]}) is missing")
            continue
        proof[str(n)] = {"file": members[n], "vanilla_sha256": v[n], "hge_sha256": h[n]}
        if v[n] != h[n]:
            problems.append(f"{SCRIPT_NARC} member {n} ({members[n]}) differs between the vanilla and hge ROMs: the acquisition sites in it are not shared")
    differing = [n for n in range(min(len(v), len(h))) if v[n] != h[n]]
    script = {"narc": SCRIPT_NARC, "member_count": len(h), "site_member_count": len(members), "site_members": proof, "members_differing_in_hge": differing, "differing_members_holding_sites": sorted(set(differing) & set(members))}
    tv, th = narc_member_hashes(vanilla, TRADE_NARC), narc_member_hashes(hge, TRADE_NARC)
    if tv != th:
        problems.append(f"{TRADE_NARC} (NPC trade records) differs between the vanilla and hge ROMs: {[i for i in range(min(len(tv), len(th))) if tv[i] != th[i]] or 'member count'}")
    trade = {"narc": TRADE_NARC, "member_count": len(th), "members": {str(i): {"vanilla_sha256": tv[i], "hge_sha256": th[i]} for i in range(min(len(tv), len(th)))}, "all_equal": tv == th}
    return script, trade, problems


def reachability_member_proof(vanilla: str, hge: str, sites: list[dict]) -> tuple[dict, list[str]]:
    """The ENTRY half of a shared site's reachability: the map's zone_event member (a/0/3/2) and its `_hdr` script member
    (a/0/1/2) that START the entries must be byte-identical in both ROMs (the site members themselves are proved by
    script_member_proof). A difference fails generation. The PATH half (CallStd callees, which live in other members,
    notably member 3 that DIFFERS in hge) is callstd_member_proof."""
    problems, out = [], {}
    for key, narc in (("events", EVENT_NARC), ("header", SCRIPT_NARC)):
        v, h = narc_member_hashes(vanilla, narc), narc_member_hashes(hge, narc)
        if len(v) != len(h):
            problems.append(f"{narc} has {len(v)} members in the vanilla ROM and {len(h)} in the hge ROM")
        members = {s["reachability"]["sources"][key]["member"]: s["reachability"]["sources"][key]["file"] for s in sites if s["reachability"]["sources"][key]}
        rows = {}
        for n, f in sorted(members.items()):
            if n >= min(len(v), len(h)):
                problems.append(f"{narc} member {n} ({f}) is missing")
                continue
            rows[str(n)] = {"file": f, "vanilla_sha256": v[n], "hge_sha256": h[n]}
            if v[n] != h[n]:
                problems.append(f"{narc} member {n} ({f}) differs between the vanilla and hge ROMs: the reachability derived from it is not shared")
        out[key] = {"narc": narc, "member_count": len(h), "members": rows, "members_differing_in_hge": [n for n in range(min(len(v), len(h))) if v[n] != h[n]]}
    return out, problems


def callstd_member_proof(vanilla: str, hge: str, sites: list[dict]) -> tuple[dict, list[str]]:
    """The PATH half of a shared site's reachability. A site whose path crosses a CallStd runs the callee from another
    script member. A callee member that is byte-identical in both ROMs is proved; member 3 (the common scripts) DIFFERS
    in hge, so a site crossing into it inherits the vanilla CallStd check UNPROVEN (`inherits_unproven_callstd_member_3`:
    the callee bytes of the targets used were not shown identical). Any OTHER differing callee member fails generation."""
    v, h = narc_member_hashes(vanilla, SCRIPT_NARC), narc_member_hashes(hge, SCRIPT_NARC)
    problems = [f"{SCRIPT_NARC} has {len(v)} members in the vanilla ROM and {len(h)} in the hge ROM"] if len(v) != len(h) else []
    used = sorted({c["member"] for s in sites for c in s["reachability"]["callstd"]["calls"]})
    members = {}
    for m in used:
        if m >= min(len(v), len(h)):
            problems.append(f"{SCRIPT_NARC} member {m} (CallStd callee bank) is missing")
            continue
        members[str(m)] = {"vanilla_sha256": v[m], "hge_sha256": h[m], "proven_identical": v[m] == h[m]}
        if v[m] != h[m] and m != COMMON_SCRIPT_MEMBER:
            problems.append(f"{SCRIPT_NARC} member {m} (CallStd callee bank) differs between the vanilla and hge ROMs: the CallStd check of the sites that reach it is not shared")
    per_site = {}
    for s in sites:
        ms = sorted({c["member"] for c in s["reachability"]["callstd"]["calls"]})
        unproven = any(not members.get(str(m), {}).get("proven_identical") for m in ms)
        per_site[s["id"]] = {"status": "inherits_unproven_callstd_member_3" if unproven else "proven_identical", "members": ms}
    return {
        "narc": SCRIPT_NARC,
        "member_3_differs": v[COMMON_SCRIPT_MEMBER] != h[COMMON_SCRIPT_MEMBER],
        "members": members,
        "sites": per_site,
        "note": "records stay the vanilla ones; `sites` says which of them cross a CallStd into a member that differs in hge",
    }, problems


# ---- fork facts that script resolution relies on

def fact_checks(pret: Path, src: Path) -> tuple[list[dict], list[str]]:
    """The species/level the C side supplies for starters, roamers and the Togepi egg must equal the vanilla ones
    (they resolve the c_source fields of the shared script sites)."""
    rows = []
    cs, st = base.read(pret, "src/choose_starter.c"), base.read(src, "src/starters.c")
    sc = base.read(src, "src/field/script_commands.c")
    pm = base.read(pret, "src/field/scrcmd_pokemon_misc.c")
    pairs = {
        "starter_species": (re.findall(r"SPECIES_\w+", re.search(r"const int species\[\] = \{(.*?)\}", cs, re.S)[1]), re.findall(r"SPECIES_\w+", re.search(r"sStarterChoices\[3\] = \{(.*?)\}", st, re.S)[1])),
        "starter_level": (int(re.search(r"CreateMon\(mon, species\[i\], (\d+)", cs)[1]), int(re.search(r"PokeParaSet\(mon, species, (\d+)", st)[1])),
        "roamers": (ROAMER_RE.findall(base.read(pret, "src/field_roamer.c")), ROAMER_RE.findall(base.read(src, "src/field_roamer.c"))),
        "togepi_egg_species": (re.search(r"BOOL ScrCmd_GiveTogepiEgg.*?SetEggStats\(mon, (SPECIES_\w+)", pm, re.S)[1], re.search(r"SetEggStats\(togepi, (SPECIES_\w+)", sc)[1]),
    }
    problems = []
    for fact, (v, h) in pairs.items():
        rows.append({"fact": fact, "vanilla": v, "hge": h, "equal": v == h})
        if v != h:
            problems.append(f"hge C fact {fact} differs from pret: vanilla {v} vs hge {h}; the c_source resolution of the shared script sites no longer holds")
    return rows, problems


def pret_callees(pret: Path, rel: str, name: str) -> set[str] | None:
    """Identifiers called inside the pret C definition of `name` (None when the function is not in that file)."""
    m = re.search(r"^[^\s#/][^\n;]*\b" + re.escape(name) + r"\([^;]*?\)\s*\{.*?^\}", base.read(pret, rel), re.M | re.S)
    return set(re.findall(r"\b(\w+)\(", m[0].split("{", 1)[1])) if m else None


def romld_addresses(src: Path) -> dict[str, int]:
    return {n: int(a, 16) for n, a in re.findall(r"^(\w+)\s*=\s*(0x[0-9A-Fa-f]{8})\s*\|\s*1;", (src / "rom.ld").read_text(encoding="utf-8"), re.M)}


# ---- script DISPATCH: the hashes prove the script bytecode, not the C handler each opcode runs

TABLE_RE = re.compile(r"gScriptCmdTable\[\] = \{(.*?)\};", re.S)
# Hooked ScrCmd_* handlers a site-bearing script may use that are not acquisition code (reason required). Empty on
# purpose: the 3 hooked handlers the sites reach (CreateRoamer, GiveEgg, GiveTogepiEgg) are all inventory rows.
HGE_DISPATCH_OK: dict[str, str] = {}


# script.inc macros that parse to NO opcode: the script-header / entry-table macros (data words, `.if` blocks, the
# hex terminator `.short 0xFD13`). They emit table data, never a command, so no handler runs for them. Pinned: a new
# empty-opcode macro is not in this set, so using it fails script_dispatch instead of silently skipping the check.
HEADER_MACROS = frozenset(
    ["ScrDef", "ScrDefEnd", "MapScript", "MapScript2", "ScriptEntry", "ScriptEntryEnd", "InitScriptEntry_Fixed", "InitScriptEntry_OnFrameTable", "InitScriptEntry_OnTransition", "InitScriptEntry_OnResume", "InitScriptEntry_OnLoad", "InitScriptEntryEnd", "InitScriptGoToIfEqual", "InitScriptEnd"]
)


def macro_opcodes(inc_text: str) -> dict[str, set[int]]:
    """asm/macros/script.inc: macro -> the script opcodes it can emit. A macro whose first emitting line is
    `.short N` IS opcode N; a composite macro (Compare, GoToIfEq, ItemVars ...) emits whatever the macros in its body emit."""
    bodies = {}
    for m in re.finditer(r"\.macro (\w+)[^\n]*\n(.*?)\.endm", inc_text, re.S):
        bodies[m[1]] = [ln.strip() for ln in m[2].splitlines() if ln.strip() and not re.match(r"\.(if|ifdef|ifndef|else|endif|error|set)\b", ln.strip())]
    memo: dict[str, set[int]] = {}

    def ops(name: str, stack: tuple[str, ...] = ()) -> set[int]:
        if name in memo:
            return memo[name]
        body = bodies[name]
        first = re.match(r"\.short\s+(\d+)\s*$", body[0]) if body else None
        out: set[int] = {int(first[1])} if first else set()
        if not first:
            for ln in body:
                w = ln.split()[0]
                if w in bodies and w != name and w not in stack:
                    out |= ops(w, (*stack, name))
        memo[name] = out
        return out

    return {n: ops(n) for n in bodies}


def check_dispatch(used: dict[str, set[str]], hooked: dict[str, list[str]], accounted: dict[str, str]) -> tuple[list[dict], list[str]]:
    """used = handler -> commands reaching it; hooked = handler -> hook names patching it. A used, hooked handler that
    nothing accounts for is a problem."""
    rows, problems = [], []
    for handler in sorted(set(used) & set(hooked)):
        why = accounted.get(handler)
        rows.append({"handler": handler, "hooks": hooked[handler], "commands": sorted(used[handler]), "accounted_by": why})
        if why is None:
            problems.append(f"script dispatch: {sorted(used[handler])} reach handler {handler}, which the fork hooks ({hooked[handler]}) and nothing in the inventory accounts for it; the shared script sites may behave differently on hge")
    return rows, problems


def script_dispatch(pret: Path, files: list[str], van: Vanilla, accounted: dict[str, str]) -> tuple[dict, list[str]]:
    """Decode every command used by the site-bearing script sources through script.inc (macro -> opcode) and the pret
    command table (opcode -> handler), and check no handler the fork hooks is reached unaccounted. SOURCE level: the
    member BYTES are proved identical by script_narc, the command names come from the same .s sources the sites do."""
    handlers = re.findall(r"^\s*(\w+),\s*$", TABLE_RE.search(base.read(pret, "src/data/fieldmap/script_cmd_table.h"))[1], re.M)
    ops = macro_opcodes(base.read(pret, "asm/macros/script.inc"))
    movement = set(re.findall(r"\.macro (\w+)", base.read(pret, "asm/macros/movement.inc")))
    used_cmds: dict[str, set[str]] = {}
    unknown: dict[str, list[str]] = {}
    for f in files:
        for ln in (pret / "files/fielddata/script/scr_seq" / f).read_text(encoding="utf-8", errors="replace").splitlines():
            t = ln.split("@", 1)[0].strip()
            if not t or t[0] in ".#;" or t.startswith("//") or t.split()[0].endswith(":"):
                continue
            w = t.split()[0]
            if w in ops:
                used_cmds.setdefault(w, set()).add(f)
            elif w not in movement:  # movement.inc macros are movement DATA read by a movement command, not script commands
                unknown.setdefault(w, []).append(f)
    problems = [f"script dispatch: mnemonic {w!r} in {fs[0]} is not a script.inc macro; cannot decode it" for w, fs in sorted(unknown.items())]
    used: dict[str, set[str]] = {}
    for cmd in used_cmds:
        if not ops[cmd] and cmd not in HEADER_MACROS:  # e.g. hex `.short 0xFD13` or .if-only bodies: the parser cannot see the opcode, so the check would be blind
            problems.append(f"script dispatch: command {cmd} (used in {sorted(used_cmds[cmd])[0]}) resolves to no opcode in script.inc; cannot check its handler")
        for op in ops[cmd]:
            if op >= len(handlers):
                problems.append(f"script dispatch: command {cmd} opcode {op} is outside the {len(handlers)}-entry command table")
            else:
                used.setdefault(handlers[op], set()).add(cmd)
    hooked: dict[str, list[str]] = {}
    for name in used:
        for fn in van.find(name):
            hooked.setdefault(name, []).extend(h["name"] for h in van.hooks_in(fn))
    hooked = {k: sorted(set(v)) for k, v in hooked.items() if v}
    rows, bad = check_dispatch(used, hooked, accounted)
    doc = {
        "method": "source level: every command mnemonic in the site-bearing scr_seq sources -> opcode (asm/macros/script.inc) -> handler (src/data/fieldmap/script_cmd_table.h gScriptCmdTable) -> hooks on that handler. The script bytes are proved by script_narc; member 3 (common scripts reached through CallStd) is the one NARC member that differs and is NOT covered here.",
        "command_table_size": len(handlers),
        "commands_used": len(used_cmds),
        "handlers_used": len(used),
        "hooked_handlers_used": rows,
    }
    return doc, problems + bad


# ---- build

def make_vanilla(pret: Path, xmap: Path, vanilla_rom: Path, src: Path) -> Vanilla:
    return Vanilla(xmap, base.read(pret, "main.lsf"), overlay_bases(str(vanilla_rom)), (src / "hooks").read_text(encoding="utf-8"), fork_defines(src))


def build_hge(pret: Path, hge_rom: Path, vanilla_rom: Path, src: Path, commit: str, xmap: Path, hge_sha1: str, vanilla_sha1: str) -> str:
    vdoc = build_doc(pret)
    sites = vdoc["script_sites"]
    defined = fork_defines(src)
    script, trade, problems = script_member_proof(str(vanilla_rom), str(hge_rom), sites)
    reach_proof, reach_problems = reachability_member_proof(str(vanilla_rom), str(hge_rom), sites)
    problems += reach_problems
    callstd_proof, callstd_problems = callstd_member_proof(str(vanilla_rom), str(hge_rom), sites)
    problems += callstd_problems
    reach_proof["callstd"] = callstd_proof
    calls, defs, scan_problems = scan_hge_c(src, defined)
    problems += scan_problems
    facts, fact_problems = fact_checks(pret, src)
    problems += fact_problems

    van = make_vanilla(pret, xmap, vanilla_rom, src)
    by_name: dict[str, list[dict]] = {}
    for h in van.hooks:
        by_name.setdefault(h["name"], []).append(h)

    def replaces(row_name: str, hook: str | None) -> dict | None:
        """Resolve a fork function to the vanilla function its hook patches."""
        if hook is None:
            return None
        hs = by_name.get(hook, [])
        if not hs:
            problems.append(f"fork function {row_name}: no active hook named {hook} in the hooks file (never reached from vanilla code?)")
            return None
        fn = van.containing(hs[0]["region"], hs[0]["addr"])
        if fn is None:
            problems.append(f"fork function {row_name}: hook {hook} at {hs[0]['addr']:08X} is inside no vanilla function in the xMAP")
            return None
        return {"hook": hook, "region": hs[0]["region"], "hook_addr": f"{hs[0]['addr']:08X}", "object": fn[3], "function": fn[2], "function_addr": f"{fn[0]:08X}", "how": "full_replacement" if hs[0]["addr"] == fn[0] else "inline_patch"}

    for row in calls:
        row["replaces"] = replaces(f"{row['file']}:{row['function']}", row.get("hook", row["function"]))
        row.pop("hook", None)
    for row in defs:
        row["replaces"] = replaces(f"{row['file']}:{row['api']}", row["api"])

    other = [{"hook": hook, "kind": kind, "why": why, "replaces": replaces(hook, hook)} for hook, (kind, why) in sorted(HGE_REPLACED_OTHER.items())]
    # replaced vanilla functions that matter to acquisition: those the fork rewrites as a producer/primitive/mon-touching helper
    replaced = {r["replaces"]["function"] for r in calls + defs + other if r["replaces"]} & van.replaced_names()

    accounted = {r["replaces"]["function"]: f"fork function {r.get('function') or r.get('api') or r['hook']} replaces it" for r in calls + defs + other if r["replaces"] and r["replaces"]["function"].startswith("ScrCmd_")} | HGE_DISPATCH_OK
    dispatch, dispatch_problems = script_dispatch(pret, sorted({s["file"] for s in sites}), van, accounted)
    problems += dispatch_problems

    # API names the fork calls -> the vanilla function behind them, and whether it is hooked
    ld = romld_addresses(src)
    api_res = {}
    for api in sorted(({r["api"] for r in calls} | {r["api"] for r in defs}) - {DIRECT_WRITE}):
        if api in ld:
            fn = next((f for f in van.funcs if f[0] == ld[api]), None)
            how = "rom.ld import"
        elif api in by_name:
            fn = van.containing(by_name[api][0]["region"], by_name[api][0]["addr"])
            how = "defined in the fork, hooked over the vanilla function"
        else:
            problems.append(f"API {api}: neither a rom.ld import nor a hook")
            continue
        if fn is None:
            problems.append(f"API {api}: no vanilla xMAP function at its address")
            continue
        status, hs = van.status(fn)
        pf = next(iter(sorted((pret / "src").rglob(fn[3] + ".c"))), None)
        callees = pret_callees(pret, pf.relative_to(pret).as_posix(), fn[2]) if pf else None
        api_res[api] = {
            "vanilla_function": fn[2],
            "object": fn[3],
            "addr": f"{fn[0]:08X}",
            "how": how,
            "vanilla_status": status,
            "hooks": [h["name"] for h in hs],
            "direct_callees_replaced": sorted((callees or set()) & replaced),
        }

    # every vanilla producer: replaced / patched_inline / kept (+ its callee)
    vrows = []
    for p in vdoc["c_producers"]:
        obj = Path(p["file"]).stem
        fns = van.find(p["function"], obj)
        callee = van.find(p["api"])
        if len(fns) != 1 or len(callee) != 1:
            problems.append(f"vanilla producer {p['file']}:{p['function']} / {p['api']} does not resolve to one xMAP function ({len(fns)} / {len(callee)})")
            continue
        status, hs = van.status(fns[0])
        cstatus = van.status(callee[0])[0]
        called = sorted((pret_callees(pret, p["file"], p["function"]) or set()) & replaced)
        summary = "replaced" if status == "replaced" else "kept_callee_replaced" if called else status
        vrows.append(
            {
                "file": p["file"],
                "function": p["function"],
                "api": p["api"],
                "cls": p["cls"],
                "kind": p["kind"],
                "region": van.region[obj],
                "function_status": status,
                "function_hooks": [h["name"] for h in hs],
                "api_status": cstatus,
                "function_callees_replaced": called,
                "hge_status": summary,
                "hge_counterparts": sorted({f"{r['file']}:{r['function']}" for r in calls if r["replaces"] and (r["replaces"]["object"], r["replaces"]["function"]) == (obj, p["function"])}),
                **({"scripts": p["scripts"]} if p.get("scripts") else {}),
                **({"open_question": p["open_question"]} if p.get("open_question") else {}),
            }
        )
        if (p["file"], p["function"]) in HGE_NOTES:
            vrows[-1]["note"] = HGE_NOTES[(p["file"], p["function"])]

    if problems:
        raise names.Mismatch("; ".join(problems))

    reach = {c for r in calls + defs + vrows for c in r.get("scripts", [])}
    counts = Counter(r["hge_status"] for r in vrows)
    unresolved = [u for u in vdoc["unresolved"] if u["id"] not in ("hg_engine",) and (u["status"] != "open_policy")]
    unresolved += [
        {"id": f"{r['file']}:{r['lines'][0]}", "kind": r["kind"], "status": "open_policy", "why": r["open_question"]}
        for r in calls
        if r.get("open_question")
    ]
    unresolved += [{"id": f"{r['file']}:{r['function']}", "kind": r["kind"], "status": "open_policy", "why": r["open_question"]} for r in vrows if r.get("open_question") and r["hge_status"] in ("kept", "kept_callee_replaced")]
    unresolved.append({"id": "hge_runtime_receipt", "kind": "runtime", "status": "open", "why": "GiveMon, ScrCmd_GiveEgg, ScrCmd_GiveTogepiEgg, _CreateTradeMon and the PC place functions are replaced C: an hge runtime acquisition receipt is still required (this inventory is SOURCE + ROM data only)"})
    inputs = {rel: hashlib.sha256((src / rel).read_bytes()).hexdigest() for rel in sorted({"hooks", "include/config.h", "include/debug.h", *HGE_FACT_FILES} | {r["file"] for r in calls + defs})}
    doc = {
        "_note": "GENERATED by tools/gen_gen4_acquisition.py hge from the pinned hg-engine fork, the pinned hge ROM and pret/pokeheartgold -- do not edit. Script sites, NPC trade records and runtime branches are the vanilla HGSS ones, valid because script_narc/trade_narc prove the members holding them are byte-identical in both ROMs (BYTECODE only) and script_dispatch checks, at source level, that no command they use reaches a handler the fork hooks without the inventory accounting for it; member 3 (common scripts via CallStd) differs and is not covered; the per-site `reachability` records are shared the same way: reachability_narc proves the zone_event and header members that START their entries are byte-identical (the entry question), and reachability_narc.callstd covers the PATH question: callee members outside member 3 are proved identical, while the sites whose path crosses a CallStd into member 3 (which differs) are listed as inheriting an unproven path; the C inventory is scanned from the fork (hge replaces engine code).",
        "_schema": HGE_SCHEMA,
        "rom_sha1": hge_sha1,
        "vanilla_rom_sha1": vanilla_sha1,
        "source": {
            "fork_commit": commit,
            "inputs": inputs,
            "pret": vdoc["source"],
            "xmap": {"name": "heartgold_xmap", "sha256": gen4_pins.MAP_SPECS["heartgold_xmap"][0]},
            "main_lsf_sha256": hashlib.sha256((pret / "main.lsf").read_bytes()).hexdigest(),
            "active_hooks": len(van.hooks),
            "hooks_with_unknown_address_form": van.skipped,
        },
        "script_narc": script,
        "trade_narc": trade,
        "reachability_narc": reach_proof,
        "script_dispatch": dispatch,
        "inventory": {
            "script_site_count": len(sites),
            "script_command_counts": vdoc["inventory"]["script_command_counts"],
            "script_file_count_with_sites": vdoc["inventory"]["script_file_count_with_sites"],
            "npc_record_count": len(vdoc["npc_trade_records"]),
            "npc_classification": vdoc["inventory"]["npc_classification"],
            "reachability_status_counts": vdoc["inventory"]["reachability_status_counts"],
            "reachability_by_command": vdoc["inventory"]["reachability_by_command"],
            "callstd_call_count": vdoc["inventory"]["callstd_call_count"],
            "callstd_conflict_count": vdoc["inventory"]["callstd_conflict_count"],
            "callstd_targets": vdoc["inventory"]["callstd_targets"],
            "callstd_sites_inheriting_unproven": sorted(i for i, v in callstd_proof["sites"].items() if v["status"] != "proven_identical"),
            "c_producer_count": len(calls),
            "c_call_site_count": sum(len(r["lines"]) for r in calls),
            "c_inactive_call_site_count": sum(len(r["inactive_lines"]) for r in calls),
            "c_definition_count": len(defs),
            "vanilla_producer_count": len(vrows),
            "vanilla_producer_status_counts": dict(sorted(counts.items())),
            "commands_without_a_c_producer": sorted(set(COMMANDS) - reach - {"CreateRoamer", "WildBattle"}),
            "scope": "script sites = the vanilla 61 (members proven identical); C side = call sites and definitions of the 11 producer APIs in the fork's src/ plus the status of every vanilla producer",
        },
        "zone_policy": vdoc["zone_policy"],
        "reachability_scope": vdoc["reachability_scope"],
        "special_modes": vdoc["special_modes"],
        "script_sites": sites,
        "npc_trade_records": vdoc["npc_trade_records"],
        "runtime_branches": vdoc["runtime_branches"],
        "c_fact_checks": facts,
        "api_resolution": api_res,
        "c_producers": calls,
        "c_definitions": defs,
        "replaced_non_producers": other,
        "vanilla_c_producers": vrows,
        "unresolved": unresolved,
    }
    return base.dumps(doc, 3)


def main_hge(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gen_gen4_acquisition.py hge", description="hge acquisition coverage map from the pinned hg-engine fork + ROMs")
    ap.add_argument("--check", action="store_true", help="regenerate in memory and diff vs the committed JSON")
    ap.add_argument("--pret", help=f"pokeheartgold clone (default ${base.ENV_CLONE} or the gen4_pins location)")
    ap.add_argument("--rom", help="hge ROM (default: the pinned cache build)")
    ap.add_argument("--vanilla-rom", help="vanilla HeartGold ROM (default: the gen4_pins location)")
    ap.add_argument("--src", help="hg-engine fork clone")
    ap.add_argument("--xmap", help="heartgoldus.xMAP")
    ap.add_argument("--out-dir", default=str(HGE_OUT))
    args = ap.parse_args(argv)
    try:
        pret = base.locate_clone(args.pret)
        base.verify_clone(pret)
        hge_rom, hge_sha1 = names.locate_rom("hge", args.rom)
        van_rom, van_sha1 = names.locate_rom("hgss", args.vanilla_rom)
        src, commit = names.locate_src("hge", args.src)
        xmap = locate_xmap(args.xmap)
        text = build_hge(pret, hge_rom, van_rom, src, commit, xmap, hge_sha1, van_sha1)
    except (base.PretAbsent, names.Absent) as exc:
        print(f"OPEN: {exc}", file=sys.stderr)
        return 2
    except (base.PretMismatch, names.Mismatch) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0 if base.finish(Path(args.out_dir) / "acquisition.json", text, args.check) else 1


def main() -> int:
    if sys.argv[1:2] == ["hge"]:
        return main_hge(sys.argv[2:])
    return base.cli(build, __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
