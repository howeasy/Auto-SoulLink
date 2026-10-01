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

D10/D14 zone mapping is data here: statics/gifts/eggs/starters/loans use the gift rules in the map's
area, roamers are extra catches, the Bug-Catching Contest and Safari are their own zones (the contest
catch is awarded at the result, not in the contest). Unsupported/unresolved producers are listed in
`unresolved`; hg-engine has its own authored inventory and is NOT covered here (UNVERIFIED).

Usage:
  python tools/gen_gen4_acquisition.py [--pret PATH] [--check]
Exit: 0 ok, 1 drift / wrong pret commit / unclassified producer, 2 pret clone absent.
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_gen4_area_map as base  # noqa: E402

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
    # Last writes to the variable before the site, file-wide (shared code is reached from several
    # entries). A literal 0 is a reset, not a value. If the last real write is a runtime command the
    # value is runtime; otherwise the trailing run of literal writes is the candidate set.
    events = [a for a in assignments(lines, 0, hit, var, ctx) if not (a[1] == "lit" and a[2] == 0)]
    if not events:
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
    ctx = Ctx(clone)
    cf = c_facts(ctx)
    script_dir = clone / "files/fielddata/script/scr_seq"
    files = sorted(script_dir.glob("*.s"))
    sites: list[dict] = []
    branch_files: dict[str, list[int]] = {}
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [(i, SCAN_RE.match(line)) for i, line in enumerate(lines)]
        hits = [(i, m) for i, m in hits if m]
        if not hits:
            continue
        m = re.match(r"scr_seq_(\d+)_(\w+?)(?:_hdr)?\.s$", path.name)
        token = m[2] if m else None
        assert token in ctx.maps.by_token, f"{path.name}: script token {token!r} names no map"
        mid = ctx.maps.by_token[token]
        row = ctx.maps.rows[mid]
        area = ctx.model["map_area"].get(mid)
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
            sites.append(site)
            if re.search(r"GetGameVersion", "\n".join(lines)):
                branch_files.setdefault(path.name, [])
    assert len(sites) == sum(Counter(s["command"] for s in sites).values())

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
        "source": base.provenance(clone, "tools/gen_gen4_acquisition.py", INPUTS + sorted({f"files/fielddata/script/scr_seq/{s['file']}" for s in sites} | {p["file"] for p in c_producers}))
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
            "commands_without_a_c_producer": sorted(set(COMMANDS) - commands_with_c - {"CreateRoamer", "WildBattle"}),
            "scope": "bounded candidate inventory: script sites for the 9 commands plus the C call sites of the 6 producer APIs; hge has its own inventory (UNVERIFIED)",
        },
        "zone_policy": ZONE_POLICY,
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
    return {"acquisition.json": base.dumps(doc, 3)}


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
            parts.append(f"{k}: {v.get('reason') or v.get('runtime') or 'candidate set, the runtime choice is not statically known'}")
    return "; ".join(parts)


def main() -> int:
    return base.cli(build, __doc__.splitlines()[0])


if __name__ == "__main__":
    sys.exit(main())
