"""Rebuild SOURCE-only Gen 3 site packs and their PINNED/UNVERIFIED inventory.

No network or emulator. Only unique, aligned anchors with a reviewed capture
contract and matching enclosing context are emitted. PINNED is not live proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.pin_gen3_site import (  # noqa: E402
    ROM_SPECS,
    find_offsets,
    load_rom,
    make_site,
    pattern_bytes,
)

PRET = "https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/"
CFRU = "https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/"
DOC = ROOT / "docs/gen3_engine_sites.md"


def candidate(kind, symbol, source, inventory, *, offset=None, pattern=None, capture=0,
              point=(), context=None, reason=None, patterns=None):
    return {"kind": kind, "symbol": symbol, "source": source, "inventory": inventory,
            "offset": offset, "pattern": pattern, "capture": capture, "point": list(point),
            "context": context, "reason": reason, "patterns": patterns}


# Checked-in evidence, not slices freshly trusted from whatever ROM is supplied.
# Capture offsets below were checked by Thumb disassembly of the pinned FR bytes.
# Static symbol/caller gaps remain explicit; no speculative gameplay site is emitted.
CANDIDATES = [
    candidate("frame_control", "CallCallbacks (control only)", "src/main.c#L241-L251",
              "Caller UpdateLinkAndCallCallbacks/main loop (main.c:196-223). Runs callback1/2 after "
              "save/help gating; void, repeated frame control, not a game event. Capture at 0800051A "
              "before the FR help-screen call; RR replaces that span. RR-companion is the patch BL. "
              "Source address: patch/tools/build.py:63 and parked callback receipt, not the idle census.",
              offset=0x51A, point=("R15", "CPSR"),
              patterns={"fr": "3BF1A9F9000600280AD1064C20680028",
                        "lg": "3BF195F9000600280AD1064C20680028",
                        "rr": "C046C046C046C046C046064C20680028",
                        "rr_companion": "78F329FDC046C046C046064C20680028"}),
    candidate("battle_begin", "CB2_InitBattle", "src/battle_main.c#L612-L646",
              "Callback selected by battle-start flow; resets/moves save blocks and allocates battle "
              "resources, then initializes normal/multi battle; void. Capture ENTRY before relocation, "
              "not an initialized party snapshot. One callback invocation; event dedupe/battle-type "
              "qualification remains the consumer's duty. Address corroboration: BR "
              "docs/rr_reference/GAME_HEAP_RESERVATION.md:48-49; first BL targets 0804C0A4.",
              offset=0xFD9C, pattern="10B53CF081F91EF04BF924F007F8", point=("R15", "CPSR")),
    candidate("battle_end", "ReturnFromBattleToOverworld", "src/battle_main.c#L3915-L3940",
              "Battle main callback: sets result, clears inBattle, restores callback1, handles roamer/"
              "Pokerus and installs saved callback2; void. Capture BEFORE final SetMainCallback2 "
              "on completion branch, after inBattle clear; link-wait branch bypasses it. This is "
              "not an exp/evolution-settled checkpoint. Entry address comes from RETURN_FROM_BATTLE_ADDR.",
              offset=0x15BCC, pattern="08488068EAF7B8FC70BC01BC", capture=4,
              point=("R0", "R15", "CPSR"),
              context=(-0x74, "70B5204E306802252840002806D11E4C")),
    candidate("faint", "Cmd_tryfaintmon", "src/battle_script_commands.c#L2831-L2905",
              "Battle script table index 0x19 (same source:339); filters absent/zero HP/side, changes "
              "script/hit markers, counts faint and adjusts friendship; void. Entry also handles "
              "non-faint control branch; capture must follow player-counter mutation with battler "
              "identity, not assume one invocation equals one faint.",
              reason="static routine absent from inspected BPRE.ld; mutation instruction not pinned"),
    candidate("capture_wild", "Cmd_givecaughtmon -> GiveMonToPlayer",
              "src/battle_script_commands.c#L9617-L9645",
              "Battle script table index 0xF0 (source:554); calls GiveMonToPlayer and builds PC message/"
              "caught-species/nickname; void. Need post-call result and battle acquisition context. "
              "One script acquisition can traverse mon_given too; reducer must not duplicate it.",
              reason="static caller and post-BL address not pinned; generic mon_given cannot classify wild capture"),
    candidate("mon_given", "GiveMonToPlayer common return", "src/pokemon.c#L3686-L3740",
              "Known caller Cmd_givecaughtmon; script gift chain ScrCmd_givemon -> ScriptGiveMon "
              "(scrcmd.c:1734-1755), full call census OPEN. Sets OT name/gender/id then copies into "
              "party or SendMonToPC. R0 result distinguishes party/PC/failure; common pop at +0x76 "
              "from inferred function entry 08040B14. Capture R0/R6 BEFORE pop. Caller context is "
              "required before classifying gift versus catch; zero failure is NOT inferred.",
              offset=0x40B80, pattern="301C00F005F80006000E70BC02BC0847", capture=10,
              point=("R0", "R6", "R13"), context=(-0x6C, "70B5061C094C22680721FFF72DFC2268")),
    candidate("pc_move", "Task_MoveMon / Task_WithdrawMon / Task_DepositMenu / Task_ReleaseMon",
              "src/pokemon_storage_system_tasks.c#L1076-L1310",
              "Storage menu tasks repeatedly drive animation and moves. Deposit/withdraw/release and "
              "multi-move (pokemon_storage_system_misc.c:234) must be separate mutation/return sites; "
              "SendMonToPC is an acquisition helper, NOT all user PC operations. Cardinality: tasks "
              "repeat; emit only completed record transitions.",
              reason="no source-built static symbols/copy-return anchors; multiple operations require separate sites"),
    candidate("whiteout", "CB2_WhiteOut completion branch", "src/overworld.c#L1545-L1566",
              "Whiteout callback repeats until ++state >=120; calls DoWhiteOut, reloads map and "
              "restores field callbacks; void. Capture BEFORE final SetMainCallback2 exclusively "
              "on completion branch (early returns bypass). Party may already be healed; not "
              "a faint-time HP witness. BPRE.ld:1073 supplies entry 080566A4.",
              offset=0x566F2, pattern="00F087F90748FFF772FF0648A9F721FF", capture=12,
              point=("R0", "R15"), context=(-0x4E, "00B581B017498720C000091808780130")),
    candidate("map_load", "CB2_LoadMap2 normal completion branch", "src/overworld.c#L1568-L1591",
              "CB2_LoadMap only schedules callbacks; its return is NOT completed load. Normal "
              "CB2_LoadMap2 calls DoMapLoadLoop, then restores field callbacks; Quest Log branch "
              "does something else. Capture BEFORE final SetMainCallback2 on normal branch. "
              "Other map/load/return paths remain uncovered. BPRE.ld:1074 gives dispatcher "
              "0805671C; its savedCallback literal at 08056748 is 0805674D.",
              offset=0x5676C, pattern="00F04AF90348FFF735FF0348A9F7E4FE", capture=12,
              point=("R0", "R15"), context=(-0x20, "00B5064800F084FB")),
    candidate("evolve_species_store", "Task_EvolutionScene / Task_TradeEvolutionScene",
              "src/evolution_scene.c#L634-L790",
              "Tasks created by scene setup (source:293,509), species writes at :779 and :1213; "
              "CB2_EvolutionSceneUpdate only drives work. Capture AFTER each SetMonData species "
              "publish; ordinary/trade evolution and Shedinja (:559) need distinct coverage.",
              offset=0xCE710,
              reason="profile CB2 is a driver, not species-store site; task offsets/extra paths not pinned"),
    candidate("trade_done", "DoInGameTradeScene and native/link completion branches",
              "src/trade_scene.c#L2774-L2789",
              "DoInGameTradeScene starts a task/fade and returns BEFORE trade; Task_InGameTrade "
              "switches to animation callback. Field returns at source:1800 and :2300 are candidates. "
              "Need actual record swap + evolution completion and NPC/link/SLink context; repeated "
              "animation frames must not produce repeated trade_done.",
              reason="completion branches and record ownership not pinned; initializer is not completion"),
    candidate("save", "TrySavingData successful-return preparation", "src/save.c#L650-L720",
              "Save-menu callers supply saveType. Serializes then writes; returns OK=1 or ERROR=255. "
              "Capture at common pop BEFORE R5 restored: require R0==1 AND R5==SAVE_NORMAL(0). "
              "One observation per invocation, not every call is full save. BPRE.ld:1708 gives "
              "entry 080DA364; LG byte search moves it to 080DA338. RR wrapper byte pin does NOT "
              "qualify its relocated writer/extension sectors or flash-witness completeness.",
              offset=0xDA39C, pattern="02480480012030BC02BC084720540003", capture=6,
              point=("R0", "R5", "R13"), context=(-0x38, "30B50006050E09480468012C09D1281C")),
    candidate("poison_faint", "DoPoisonFieldEffect / FaintFromFieldPoison",
              "src/field_poison.c#L32-L118",
              "Field poison step mutates HP across party and returns FLDPSN_*; later task "
              "Task_TryFieldPoisonWhiteOut clears status/adjusts friendship and displays per-mon "
              "messages. Need zero-HP edge identity before cure/whiteout; UpdatePoisonStepCounter "
              "(BPRE.ld:1168) is not the per-mon HP write.",
              reason="static HP-store/caller site and one-per-mon filter not pinned"),
    candidate("borrowed_party", "RR backup/restore hooks", "src/battle_main.c#L612-L646",
              "RR-specific source/binary census required: existing client freeze/restore handling "
              "at lua/clients/gen3_frlge_client.lua:3005-3379 is behavior to preserve, not pret proof.",
              reason="RR-specific mutation and restore pairing not pinned"),
    candidate("nature_change", "RR nature-changer special", "src/pokemon.c#L3686-L3706",
              "RR-specific PID identity update; existing client.lua:3399-3557 is only a local behavior "
              "reference. The linked vanilla source is a contrast, NOT evidence for the special.",
              reason="no pinned RR special entry/store/caller context"),
]


def output_path(pack: str) -> Path:
    return ROOT / "data/games" / pack / "engine_signals.json"


def resolve(c: dict, name: str, rom: bytes) -> dict:
    pattern = (c["patterns"] or {}).get(name, c["pattern"])
    diagnostic = {}
    if c["offset"] is not None:
        diagnostic = {"reference_offset": c["offset"],
                      "reference_bytes": rom[c["offset"]:c["offset"] + 16].hex().upper()}
    if c["reason"] or not pattern:
        return {"status": "UNVERIFIED", "reason": c["reason"] or "no reviewed anchor", **diagnostic}
    data = pattern_bytes(pattern)
    offsets = find_offsets(rom, data)
    if len(offsets) != 1:
        return {"status": "UNVERIFIED", "reason": f"exact pattern has {len(offsets)} matches",
                "matches": offsets, **diagnostic}
    offset = offsets[0]
    if c["context"]:
        delta, expected = c["context"]
        actual = rom[offset + delta:offset + delta + len(expected) // 2]
        if actual.hex().upper() != expected:
            return {"status": "UNVERIFIED", "reason": "enclosing entry context differs (possible detour/dead tail)",
                    "matches": offsets, **diagnostic}
    try:
        site = make_site(rom, offset, data, capture_offset=c["capture"], symbol=c["symbol"], point=c["point"])
    except ValueError as exc:
        return {"status": "UNVERIFIED", "reason": str(exc), "matches": offsets, **diagnostic}
    site.update(source=PRET + c["source"], capture_contract=c["inventory"])
    if c["context"]:
        delta, expected = c["context"]
        site["context"] = {"rom_offset": offset + delta, "expected_hex": expected}
    return {"status": "PINNED", "site": site, "matches": offsets}


def build(roms: dict[str, bytes]) -> tuple[dict, dict]:
    packs = {p: {"schema": "gen3-engine-signals-v1", "pack": p,
                 "evidence": "SOURCE_BYTE_PIN", "live_verified": False, "titles": {}}
             for p in ("gen3_frlg", "gen3_rr")}
    inventory = {}
    for name, (pack, title, kind, _, sha1) in ROM_SPECS.items():
        rom = roms[name]
        if hashlib.sha1(rom).hexdigest() != sha1:
            raise ValueError(f"{name}: ROM identity changed")
        inventory[name] = {c["kind"]: resolve(c, name, rom) for c in CANDIDATES}
        artifact = {"rom_sha1": sha1, "rom_md5": hashlib.md5(rom).hexdigest(),
                    "sites": {k: r["site"] for k, r in inventory[name].items() if r["status"] == "PINNED"}}
        packs[pack]["titles"].setdefault(title, {"artifacts": {}})["artifacts"][kind] = artifact
    for pack in packs.values():
        pack["sha256"] = hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return packs, inventory


def document(inventory: dict) -> str:
    lines = [
        "# Gen 3 engine-site inventory (SOURCE only)", "",
        "Generated by tools/gen_gen3_engine_signals.py; edit its checked-in candidate table.",
        "PINNED means a unique exact byte anchor, aligned reviewed instruction boundary and any "
        "required enclosing-entry anchor. It is NOT PHYSICAL hook delivery, exhaustive caller coverage, "
        "a release verdict, or permission to mutate RAM. All gameplay classification must obey each "
        "capture contract. UNVERIFIED rows are absent from both JSON packs.", "",
        "Schema: titles[title].artifacts[clean|companion].sites[kind]. Each record has address, "
        "capture_offset, expected_hex, rom_offset, point and mode=thumb. address=08000000+rom_offset; "
        "hook address=address+capture_offset. No bank translation. Compare callback address, not raw R15 "
        "(docs/gen3/research/pins.md:181-198). Companion is an artifact of radical_red, not another title.",
        "", "## Sources and limitations", "",
        f"- [Pinned pret source]({PRET}) and [CFRU BPRE.ld]({CFRU}BPRE.ld). BPRE names are "
        "lookup seeds, not RR equivalence proof. Static symbols not present in that map stay unresolved.",
        "- Control address: patch/tools/build.py:63; parked "
        "codex/rr-foundation:docs/rr_reference/BIZHAWK_MGBA_CALLBACKS.md:150-170 "
        "(callback 0800051A, raw R15 0800051C). Artifact-specific control bytes are intentional.",
        "- Read-only Capstone 5.0.7 Thumb disassembly established FR capture boundaries and call targets; "
        "no disassembly/runtime dependency in regeneration. Transported matches are [INFERENCE] of "
        "the same local sequence, not proof of caller reachability. Runtime fields must come from each pack profile.",
        "- docs/gen3/probes/census_rr_overworld_2026-09-21.txt:7-17 observes R15=000001C4, "
        "CPSR mode/T=31/0 and tasks 0806E811,0806E83D,08079E0D during 1800 idle frames. "
        "This is BIOS idle census, not evidence for any gameplay site in this inventory.",
        "- mon_given is deliberately NOT pinned on RR: its vanilla return bytes survive, but "
        "entry 08040B14 is detoured (0049084791D70709...). A unique dead tail is not a hook.",
        "- map_load covers only the normal CB2_LoadMap2 branch; Quest Log and other loaders remain OPEN. "
        "whiteout is a completion marker after healing, not an HP-at-faint capture. save requires R0=1/R5=0; "
        "RR flash extensions and final save witness ownership remain UNVERIFIED "
        "(docs/gen3/research/flash_save.md:93-137).",
        "", "## ROM identities", "",
        "| Artifact | SHA-1 (required) |", "|---|---|",
    ]
    lines += [f"| {name} | {spec[4]} |" for name, spec in ROM_SPECS.items()]
    lines += ["", "## PINNED / UNVERIFIED matrix", "",
              "| Kind | FR | LG | RR clean | RR companion |", "|---|---|---|---|---|"]
    for c in CANDIDATES:
        lines.append("| " + c["kind"] + " | " + " | ".join(inventory[n][c["kind"]]["status"] for n in ROM_SPECS) + " |")
    lines += ["", "## Caller / mutation / result / cardinality / capture inventory", ""]
    for c in CANDIDATES:
        lines += [f"### {c['kind']} — {c['symbol']}", "",
                  f"[pret {c['source']}]({PRET}{c['source']}). {c['inventory']}", "",
                  "| ROM | Status | Anchor address / capture offset / flat | Expected bytes | Reason |",
                  "|---|---|---|---|---|"]
        for name in ROM_SPECS:
            r = inventory[name][c["kind"]]
            if r["status"] == "PINNED":
                s = r["site"]
                lines.append(f"| {name} | PINNED | {s['address']:08X} / +{s['capture_offset']:X} / {s['rom_offset']:X} "
                             f"| {s['expected_hex']} | SOURCE only; capture contract above |")
            else:
                where = ", ".join(f"{x:X}" for x in r.get("matches", [])) or "not resolved"
                diagnostic = r.get("reference_bytes", "not established")
                lines.append(f"| {name} | UNVERIFIED | {where}; no capture offset authorized "
                             f"| {diagnostic} | {r['reason']}; bytes, if shown, are diagnostic only |")
        lines.append("")
    lines += ["## Reproduce and falsify", "",
              "- python tools/gen_gen3_engine_signals.py --check (offline; all four pinned ROMs required).",
              "- python tools/pin_gen3_site.py HEX --rom fr --capture-offset 0 prints all matches and "
              "only a candidate record. It never writes/adopts a pin.",
              "- pytest tests/unit/test_gen3_engine_sites.py -q checks every emitted pin, exclusion, "
              "wrong ROM, ambiguous/odd matches and the retained RR-tail trap.",
              "", "## NOT VERIFIED", "",
              "Missing static/caller/mutation sites remain UNVERIFIED. No emulator was run on this card. "
              "PINNED rows still need per-artifact natural-play positive/negative receipts, snapshot validity, "
              "semantic reduction, duplicate suppression and full caller coverage before P3 can close a row. "
              "Do not infer that byte-match tests qualify faint/capture/PC/trade/evolution/poison, all map paths, "
              "RR borrowed-party/nature changes, or flash persistence. Profile/save/checkpoint files are outside this lease.",
              ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        packs, inventory = build({name: load_rom(name) for name in ROM_SPECS})
        outputs = {output_path(p): json.dumps(v, indent=2, sort_keys=True) + "\n" for p, v in packs.items()}
        outputs[DOC] = document(inventory)
        stale = []
        for path, text in outputs.items():
            if args.check:
                if not path.is_file() or path.read_text(encoding="utf-8") != text:
                    stale.append(str(path.relative_to(ROOT)))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
        for name, rows in inventory.items():
            count = sum(r["status"] == "PINNED" for r in rows.values())
            print(f"{name}: {count} PINNED, {len(rows) - count} UNVERIFIED")
        if stale:
            print("STALE: " + ", ".join(stale))
            return 1
        print("CHECK PASSED (SOURCE only)" if args.check else "WROTE two packs + inventory (SOURCE only)")
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
