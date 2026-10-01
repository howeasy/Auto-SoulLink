"""Rebuild SOURCE-only Gen 3 site packs and their PINNED/UNVERIFIED inventory.

No network or emulator. Only unique, aligned anchors with a reviewed capture
contract and matching enclosing context are emitted. PINNED is not live proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.pin_gen3_site import (  # noqa: E402
    EMERALD_SPECS,
    ROM_BASE,
    ROM_SPECS,
    decode_thumb_detour,
    find_offsets,
    load_rom,
    make_site,
    parse_symbols,
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
              "at archive/gen3-old-client:lua/clients/gen3_frlge_client.lua:3005-3379 is behavior to preserve, not pret proof.",
              reason="RR-specific mutation and restore pairing not pinned"),
    candidate("nature_change", "RR nature-changer special", "src/pokemon.c#L3686-L3706",
              "RR-specific PID identity update; existing client.lua:3399-3557 is only a local behavior "
              "reference. The linked vanilla source is a contrast, NOT evidence for the special.",
              reason="no pinned RR special entry/store/caller context"),
]

# RR-only additions do not change either vanilla pack's emitted sites.
CANDIDATES.append(candidate(
    "nature_change_begin", "RR Nature Changer PID preimage", "include/constants/pokemon.h#L5",
    "RR map 5,4 local NPC5 at (8,2), script0904C154 option0 -> Nature Changer script0904C3D6. "
    "Twenty-one callnative wrappers call090B17CC. Paired preimage at090B1874 immediately before "
    "SetMonData(MON_DATA_PERSONALITY=0); R4=gPlayerParty+100*VAR8004. Read old raw PID/OT from "
    "the same valid aligned party record; preserve scalar preimage, slot, mon pointer and reset epoch. "
    "No wire event at begin. Pair only same record/slot/epoch with nature_change; clear on reset "
    "or mismatch and emit nothing if missing/invalid/unchanged. ROM binary, not upstream routine, "
    "is authoritative; SOURCE only.", reason="RR-only Nature Changer; not applicable to vanilla FR/LG"))
_nature = next(c for c in CANDIDATES if c["kind"] == "nature_change")
_nature["source"] = "include/constants/pokemon.h#L5"
_nature["inventory"] = (
    "RR Nature Changer paired postimage at090B1878 after SetMonData(PERSONALITY=0), before "
    "CalculateMonStats. R4 is the same aligned party record as nature_change_begin at090B1874. "
    "Require validated old/new scalar PID+OT, same slot/pointer/reset epoch, decoded valid species/flags "
    "and non-Bad-Egg/non-egg record; RR checksum is explicitly unused, never require checksum_ok=true/zero. "
    "unchanged OT and changed PID; emit one key_change reason=nature_change after successful pairing. "
    "Never reconstruct old PID from final RAM or correlate by species/similarity. Begin has no event; "
    "drop mismatched/absent/unchanged pairs and clear on reset. Capture is synchronous engine delivery; "
    "do not let a queued signal reread only the final record. SOURCE only, natural-play proof unrun.")
for _kind, _symbol, _contract in (
    ("borrowed_party_begin", "RR School rental team builder",
     "RR School map5,2 NPC1(6,2) script09051ABF, builder callnative09051B87/09051BF2 ->09079300. "
     "Capture builder ENTRY before six CreateMon calls overwrite gPlayerParty, including ViewYourTeam "
     "before battle_begin. Preserve validated own raw records/keys/count and reset epoch, force borrowed "
     "state until matching restore; no gameplay event/capture/faint from the borrowed records. "
     "Nested/replayed begin must not replace the original own-party baseline."),
    ("borrowed_party_opponent_begin", "RR School opponent team builder",
     "School ViewOppTeam option1: script09051C06 sets VAR512B=7, callnative09051C11->090790C8. "
     "Capture shared callsite090790E4 BEFORE BL09078F9C, reached only by VAR512B6/7 paths; "
     "unsupported values return090790E8 without a begin hit. Same own-records/keys/count "
     "and reset-epoch preimage contract as borrowed_party_begin; never replace active own baseline. "
     "Function reads VAR512B and only values6/7 invoke09078F9C with party pointer02024284; that "
     "callee computes100*i and calls CreateMon09078C48. Other values return without overwriting. "
     "Begin hit alone is not proof of party divergence or PHYSICAL qualification. Restore only on "
     "borrowed_party_end with exact own keys/count; clear on reset. SOURCE ROM, not guessed backup RAM."),
    ("borrowed_party_end", "LoadPlayerParty restored-party completion",
     "RR special28 -> LoadPlayerParty0804C230; capture0804C262 BX R0 after count restoration and "
     "six 100-byte copies from *gSaveBlock1Ptr+0x38. Generic restore call: end ONLY an active borrowed "
     "epoch whose restored own keys/count match the saved preimage; unrelated loads never end/emit. "
     "Clear on reset and reject invalid/mismatched restore. School cancel special28 proven; school "
     "postbattle restore caller UNRESOLVED. Both own/opponent begins share the first active own baseline; "
     "later begin hits cannot replace it. Borrowed own-party writes remain held until verified restore.")):
    CANDIDATES.append(candidate(_kind, _symbol, "src/pokemon.c", _contract,
                                reason="RR-only school borrow lifecycle; not applicable to vanilla pack"))



# C2-3b: offsets are relative to independently resolved FR/LG function symbols.
# Literal anchors were separately read and disassembled in BOTH admitted ROMs.
BINDINGS = {
    "hatch": {
        "function": "AddHatchedMonToParty", "anchor_offset": 0x9E, "capture": 12,
        "anchors": {"fr": "281CFDF76AFA281CF7F739FB05B030BC", "lg": "281CFDF76AFA281CF7F739FB05B030BC"},
        "entries": {"fr": "30B585B00006000E03AC462121706421", "lg": "30B585B00006000E03AC462121706421"},
    },
    "frame_control": {
        "function": "CallCallbacks",
        "anchor_offset": 10,
        "capture": 0,
        "anchors": {
            "fr": "3BF1A9F9000600280AD1064C20680028",
            "lg": "3BF195F9000600280AD1064C20680028"
        },
        "entries": {
            "fr": "10B5F4F001FE00280FD13BF1A9F90006",
            "lg": "10B5F4F0EDFD00280FD13BF195F90006"
        }
    },
    "battle_begin": {
        "function": "CB2_InitBattle",
        "anchor_offset": 0,
        "capture": 0,
        "anchors": {
            "fr": "10B53CF081F91EF04BF924F007F8",
            "lg": "10B53CF081F91EF04BF924F007F8"
        },
        "entries": {
            "fr": "10B53CF081F91EF04BF924F007F825F0",
            "lg": "10B53CF081F91EF04BF924F007F825F0"
        }
    },
    "battle_end": {
        "function": "ReturnFromBattleToOverworld",
        "anchor_offset": 116,
        "capture": 4,
        "anchors": {
            "fr": "08488068EAF7B8FC70BC01BC",
            "lg": "08488068EAF7B8FC70BC01BC"
        },
        "entries": {
            "fr": "70B5204E306802252840002806D11E4C",
            "lg": "70B5204E306802252840002806D11E4C"
        }
    },
    "mon_given": {
        "function": "GiveMonToPlayer",
        "anchor_offset": 108,
        "capture": 10,
        "anchors": {
            "fr": "301C00F005F80006000E70BC02BC0847",
            "lg": "301C00F005F80006000E70BC02BC0847"
        },
        "entries": {
            "fr": "70B5061C094C22680721FFF72DFC2268",
            "lg": "70B5061C094C22680721FFF72DFC2268"
        }
    },
    "whiteout": {
        "function": "CB2_WhiteOut",
        "anchor_offset": 78,
        "capture": 12,
        "anchors": {
            "fr": "00F087F90748FFF772FF0648A9F721FF",
            "lg": "00F087F90748FFF772FF0648A9F721FF"
        },
        "entries": {
            "fr": "00B581B017498720C000091808780130",
            "lg": "00B581B017498720C000091808780130"
        }
    },
    "map_load": {
        "function": "CB2_LoadMap2",
        "anchor_offset": 32,
        "capture": 12,
        "anchors": {
            "fr": "00F04AF90348FFF735FF0348A9F7E4FE",
            "lg": "00F04AF90348FFF735FF0348A9F7E4FE"
        },
        "entries": {
            "fr": "00B5064800F084FBBCF0F8FF0006000E",
            "lg": "00B5064800F084FBBCF0E4FF0006000E"
        }
    },
    "save": {
        "function": "TrySavingData",
        "anchor_offset": 56,
        "capture": 6,
        "anchors": {
            "fr": "02480480012030BC02BC084720540003",
            "lg": "02480480012030BC02BC084720540003"
        },
        "entries": {
            "fr": "30B50006050E09480468012C09D1281C",
            "lg": "30B50006050E09480468012C09D1281C"
        }
    },
    "faint": {
        "function": "Cmd_tryfaintmon",
        "anchor_offset": 280,
        "capture": 4,
        "anchors": {
            "fr": "0130087038780CF02DFF2DE0C43B0202",
            "lg": "0130087038780CF02DFF2DE0C43B0202"
        },
        "entries": {
            "fr": "F0B54F464646C0B481B0184802689178",
            "lg": "F0B54F464646C0B481B0184802689178"
        }
    },
    "capture_wild": {
        "function": "Cmd_givecaughtmon",
        "anchor_offset": 36,
        "capture": 4,
        "anchors": {
            "fr": "13F076F9000600285DD09EF0C1FF0006",
            "lg": "13F076F9000600285DD09EF0ABFF0006"
        },
        "entries": {
            "fr": "F0B54F464646C0B419488146194D2878",
            "lg": "F0B54F464646C0B419488146194D2878"
        }
    },
    "pc_move": {
        "function": "SendMonToPC",
        "anchor_offset": 156,
        "capture": 4,
        "anchors": {
            "fr": "BFD1022008BC9846F0BC02BC0847",
            "lg": "BFD1022008BC9846F0BC02BC0847"
        },
        "entries": {
            "fr": "F0B5474680B480461A482DF0E5FC0006",
            "lg": "F0B5474680B480461A482DF0E5FC0006"
        }
    },
    "pc_deposit": {
        "function": "TryStorePartyMonInBox",
        "anchor_offset": 120,
        "capture": 8,
        "anchors": {
            "fr": "012175F715F9012070BC02BC08470000",
            "lg": "012175F72BF9012070BC02BC08470000"
        },
        "entries": {
            "fr": "70B50006060E301CF9F70CF80004040C",
            "lg": "70B50006060E301CF9F70CF80004040C"
        }
    },
    "pc_withdraw": {
        "function": "SetPlacedMonData",
        "anchor_offset": 30,
        "capture": 6,
        "anchors": {
            "fr": "642252F140FF12E0",
            "lg": "642252F144FF12E0"
        },
        "entries": {
            "fr": "F0B50006060E09060F0E0E2E12D10649",
            "lg": "F0B50006060E09060F0E0E2E12D10649"
        }
    },
    "pc_box_place": {
        "function": "SetPlacedMonData",
        "anchor_offset": 68,
        "capture": 8,
        "anchors": {
            "fr": "301C391CF8F7CAFDF0BC01BC0047",
            "lg": "301C391CF8F7CAFDF0BC01BC0047"
        },
        "entries": {
            "fr": "F0B50006060E09060F0E0E2E12D10649",
            "lg": "F0B50006060E09060F0E0E2E12D10649"
        }
    },
    "pc_release_begin": {
        "function": "ReleaseMon",
        "anchor_offset": 0,
        "capture": 0,
        "anchors": {
            "fr": "00B5FDF757FF03490878002804D00020",
            "lg": "00B5FDF757FF03490878002804D00020"
        },
        "entries": {
            "fr": "00B5FDF757FF03490878002804D00020",
            "lg": "00B5FDF757FF03490878002804D00020"
        }
    },
    "pc_release": {
        "function": "ReleaseMon",
        "anchor_offset": 56,
        "capture": 6,
        "anchors": {
            "fr": "101CFFF7EDFE00F0DBFB01BC0047",
            "lg": "101CFFF7EDFE00F0DBFB01BC0047"
        },
        "entries": {
            "fr": "00B5FDF757FF03490878002804D00020",
            "lg": "00B5FDF757FF03490878002804D00020"
        }
    },
    "evolve_species_store": {
        "function": "Task_EvolutionScene",
        "anchor_offset": 1162,
        "capture": 8,
        "anchors": {
            "fr": "48460B2171F707FB48466FF784FB6189",
            "lg": "48460B2171F71DFB48466FF79AFB6189"
        },
        "entries": {
            "fr": "F0B557464E464546E0B486B00006070E",
            "lg": "F0B557464E464546E0B486B00006070E"
        }
    },
    "trade_evolve_species_store": {
        "function": "Task_TradeEvolutionScene",
        "anchor_offset": 920,
        "capture": 8,
        "anchors": {
            "fr": "40460B2170F750FD40466EF7CDFD6189",
            "lg": "40460B2170F766FD40466EF7E3FD6189"
        },
        "entries": {
            "fr": "F0B5474680B488B00006060E1C4DB000",
            "lg": "F0B5474680B488B00006060E1C4DB000"
        }
    },
    "trade_done": {
        "function": "TradeMons",
        "anchor_offset": 186,
        "capture": 4,
        "anchors": {
            "fr": "FFF79BFF01B018BC9846A146F0BC01BC",
            "lg": "FFF79BFF01B018BC9846A146F0BC01BC"
        },
        "entries": {
            "fr": "F0B54F464646C0B481B00C1C0006000E",
            "lg": "F0B54F464646C0B481B00C1C0006000E"
        }
    },
    "poison_hp_before": {
        "function": "DoPoisonFieldEffect",
        "anchor_offset": 48,
        "capture": 4,
        "anchors": {
            "fr": "9FF7CEFA0090002803D00138",
            "lg": "9FF7E4FA0090002803D00138"
        },
        "entries": {
            "fr": "F0B581B0194C002700260525201C0521",
            "lg": "F0B581B0194C002700260525201C0521"
        }
    },
    "poison_faint": {
        "function": "DoPoisonFieldEffect",
        "anchor_offset": 70,
        "capture": 8,
        "anchors": {
            "fr": "39216A469FF78BFE01376434013D002D",
            "lg": "39216A469FF7A1FE01376434013D002D"
        },
        "entries": {
            "fr": "F0B581B0194C002700260525201C0521",
            "lg": "F0B581B0194C002700260525201C0521"
        }
    },
    "trade_begin": {
        "function": "TradeMons",
        "anchor_offset": 0,
        "capture": 0,
        "anchors": {
            "fr": "F0B54F464646C0B481B00C1C0006000E",
            "lg": "F0B54F464646C0B481B00C1C0006000E"
        },
        "entries": {
            "fr": "F0B54F464646C0B481B00C1C0006000E",
            "lg": "F0B54F464646C0B481B00C1C0006000E"
        }
    }
}

BOUND_CONTRACTS = {
    "hatch": ("src/daycare.c#L1639-L1678",
        "AddHatchedMonToParty +0xAA, after MonRestorePP and CalculateMonStats, before stack unwind. "
        "R5 is the completed party mon. Snapshot only that aligned party record; require non-egg, "
        "non-Bad-Egg and valid checksum. O-15: one gift_daycare acquisition at hatch; GiveEgg is not acquisition. "
        "Normal caller CB2_EggHatch_0; ScriptHatchMon also calls this completed mutation routine.", ["R5"]),
    "faint": ("src/battle_script_commands.c#L2831-L2905",
        "Battle opcode 0x19. At function +0x11C after the PLAYER counter increment/store "
        "(+0x11A); saturated counter skips the store but reaches this same point. Player-side, "
        "present-battler and HP-zero branches precede it. R7/R8 point at gActiveBattler. "
        "Snapshot battler/party identity now; consumer dedupes the faint transition; not every entry is a faint.",
        ["R7", "R8", "R13"]),
    "capture_wild": ("src/battle_script_commands.c#L9617-L9645",
        "Battle opcode 0xF0; +0x28 is immediately AFTER BL GiveMonToPlayer (+0x24). "
        "R0 holds party/PC/failure result before shift. Destination has been assigned on success; "
        "read party/box identity using profile facts. Do not count failure as acquisition or emit twice "
        "with mon_given. This is acquired-mon placement, not a ball animation witness.",
        ["R0", "R5", "R8", "R9"]),
    "pc_move": ("src/pokemon.c#L3708-L3740",
        "SendMonToPC called by GiveMonToPlayer; +0xA0 common return before register restoration. "
        "R0=MON_GIVEN_TO_PC(1) or MON_CANT_GIVE(2); R5/R6 destination box/slot only valid "
        "on success; R8 source mon. This is acquisition-to-storage, not every PC menu operation.",
        ["R0", "R5", "R6", "R8"]),
    "pc_deposit": ("src/pokemon_storage_system_data.c#L658-L682",
        "TryStorePartyMonInBox called by Task_DepositMenu (tasks.c:1214); +0x80 common "
        "return with R0 bool, R6 box and R4 slot-in-high-byte on success. Requires R0==1. "
        "Moving-mon and party-selected branches converge; task compacts later (tasks.c:1232), "
        "so snapshot the actual transfer and do not assume final party slot numbering yet.",
        ["R0", "R4", "R6"]),
    "pc_withdraw": ("src/pokemon_storage_system_data.c#L625-L655",
        "SetPlacedMonData party branch: +0x24 after memcpy(gPlayerParty[position],movingMon,100), "
        "BEFORE branch to epilogue. R6=14, R7=party destination. Called by placement/shift paths; "
        "origin may be party rather than box. Correlate moving-mon origin/caller before emitting box_to_party. "
        "One record placement, not a whole animation or batch completion.",
        ["R6", "R7"]),
    "pc_box_place": ("src/pokemon_storage_system_data.c#L625-L655",
        "SetPlacedMonData common epilogue +0x4C AFTER SetBoxMonAt call on box path. "
        "Party path also joins here; REQUIRE R6<14, valid R7<30. R6/R7 name destination; "
        "moving-mon origin identifies deposit versus box rearrange/shift. Do not duplicate pc_deposit.",
        ["R6", "R7"]),
    "pc_release_begin": ("src/pokemon_storage_system_data.c#L716-L733",
        "ReleaseMon entry, called after permission/confirmation in Task_ReleaseMon (tasks.c:1302). "
        "Capture pre-removal identity and moving/party/box context via profile facts BEFORE purge. "
        "Pairs with pc_release; moving-mon release may only clear the carried flag.",
        ["R13", "R14"]),
    "pc_release": ("src/pokemon_storage_system_data.c#L716-L733",
        "ReleaseMon +0x3E: after PurgeMonOrBoxMon (or moving flag clear), before display refresh. "
        "One confirmed release; resolve key from pc_release_begin snapshot, never from zeroed bytes. "
        "This must not be classified as party_to_box; party compaction may follow.",
        ["R13"]),
    "evolve_species_store": ("src/evolution_scene.c#L764-L785",
        "Task_EvolutionScene EVOSTATE_SET_MON_EVOLVED; +0x492 immediately after "
        "SetMonData(MON_DATA_SPECIES), whose BL is +0x48E. R9=mon, R4=task. "
        "Stats/re-nickname/dex updates FOLLOW, so retain species publication then settle; "
        "do not call this final evolution completion. Cancellation bypasses this state.",
        ["R9", "R4"]),
    "trade_evolve_species_store": ("src/evolution_scene.c#L1206-L1219",
        "Task_TradeEvolutionScene T_EVOSTATE_SET_MON_EVOLVED; +0x3A0 after "
        "SetMonData species BL +0x39C. R8=mon, R4=task. Stats/name/dex follow. "
        "Correlate trade lease to suppress ordinary key_change during SLink apply.",
        ["R8", "R4"]),
    "trade_begin": ("src/trade_scene.c#L1054-L1084",
        "TradeMons entry captures player slot R0 and partner slot R1 plus pre-swap identities. "
        "Same primitive called by NPC cable/wireless animations (:1776,:2276) and link "
        "CB2_UpdateLinkTrade (:2533). Preserve caller/trade context; distinguish NPC and SLink.",
        ["R0", "R1", "R14"]),
    "trade_done": ("src/trade_scene.c#L1054-L1084",
        "TradeMons +0xBE before stack restoration: BOTH party/enemy copies, friendship/mail/dex "
        "updates have finished. R7=received player mon, R9=player slot. NPC cable/wireless "
        "callers (:1776,:2276) and link caller (:2533) share this primitive, not distinct copies. "
        "This is RECORD-SWAP completion, NOT native scene/evolution completion; do not emit wire "
        "trade_done until that separate lifecycle is complete. Use trade_begin for old key.",
        ["R7", "R9", "R5"]),
    "poison_hp_before": ("src/field_poison.c#L92-L118",
        "DoPoisonFieldEffect +0x34 after GetMonData(HP), before stack store/decrement. "
        "R0=old HP, R4=mon pointer. Pair by pointer and ordered invocation/iteration with "
        "poison_faint, not merely frame; up to six iterations may occur in one frame.",
        ["R0", "R4", "R5"]),
    "poison_faint": ("src/field_poison.c#L92-L118",
        "DoPoisonFieldEffect +0x4E immediately after SetMonData(HP) BL +0x4A. "
        "R4=current mon, [R13]=new HP. REQUIRE new HP==0 AND paired old HP>0; source "
        "also writes zero for already-fainted mons. Capture before later poison task clears "
        "status/whiteout heals (field_poison.c:32-81). One edge per actual newly fainted mon.",
        ["R4", "R13", "R5"]),
}
for _kind, (_source, _contract, _point) in BOUND_CONTRACTS.items():
    _old = next((c for c in CANDIDATES if c["kind"] == _kind), None)
    if _old is None:
        _old = candidate(_kind, BINDINGS[_kind]["function"], _source, _contract)
        CANDIDATES.append(_old)
    _old.update(symbol=BINDINGS[_kind]["function"], source=_source,
                inventory=_contract, point=_point, reason=None)
for _c in CANDIDATES:
    if _c["kind"] in BINDINGS:
        _b = BINDINGS[_c["kind"]]
        _c["binding"] = _b
        _c["capture"] = _b["capture"]
        _c["pattern"] = _b["anchors"]["fr"]
        if _c["kind"] != "frame_control":
            _c["context"] = (-_b["anchor_offset"], _b["entries"]["fr"])

SYMBOL_FILES = {"fr": "pokefirered.sym", "lg": "pokeleafgreen.sym"}
SYMBOL_HASHES = {
    "fr": "6f9d2929b78d0b723180653082c9a115b4b876657af8ab1c0493b4d14151f7b0",
    "lg": "6a48f1b3f3cabea043074d5d94f16cdf8b727cb529f8eced142beaa410a9ebae",
}


@lru_cache(maxsize=2)
def symbol_table(name: str) -> dict:
    path = ROOT / "data/gen3/pret" / SYMBOL_FILES[name]
    raw = path.read_bytes()
    provenance = json.loads((path.parent / "provenance.json").read_text())
    if (hashlib.sha256(raw).hexdigest() != SYMBOL_HASHES[name]
            or provenance["files"][path.name] != SYMBOL_HASHES[name]
            or provenance["source"]["commit"] != PRET.split("/")[-2]
            or provenance["roms"][path.name.replace(".sym", ".gba")] != ROM_SPECS[name][4]):
        raise ValueError(f"{name}: symbol/build provenance mismatch")
    return parse_symbols(raw.decode("utf-8"))


def output_path(pack: str) -> Path:
    return ROOT / "data/games" / pack / "engine_signals.json"



# RR-only binary bindings. All constants were independently checked in both ROMs.
# Unlike vanilla reference_size, these are explicit ESTIMATES with boundary bytes.
RR_BODIES = {
    # Both RR artifacts independently inspected: native hatch body stays in place.
    "hatch": {name: {
        "origin": None, "target": 0x08046D60, "anchor_offset": 0x9E, "capture": 12,
        "pattern": "281CFDF76AFA281CF7F739FB05B030BC", "entry": "30B585B00006000E03AC462121706421",
        "extent": 0xC0, "boundary": "00B503480078FFF7",
    } for name in ("rr", "rr_companion")},
    "faint": {
        "rr": {
            "origin": None,
            "target": 0x0909E968,
            "anchor_offset": 0x56A,
            "capture": 0,
            "pattern": "BCE638E00302C5510708E95107084A3D",
            "entry": "F0B5BA4B8BB002AF7B611B685878D4F7",
            "extent": 0x56A + 16,
            "boundary": "0202C94E0408C43F"
        },
        "rr_companion": {
            "origin": None,
            "target": 0x0909E968,
            "anchor_offset": 0x56A,
            "capture": 0,
            "pattern": "BCE638E00302C5510708E95107084A3D",
            "entry": "F0B5BA4B8BB002AF7B611B685878D4F7",
            "extent": 0x56A + 16,
            "boundary": "0202C94E0408C43F"
        }
    },
    "capture_wild": {
        "rr": {
            "origin": None,
            "target": 0x0907DD44,
            "anchor_offset": 0x3C,
            "capture": 8,
            "pattern": "5A532000FFF704FD374E002822D0374B",
            "entry": "F8B5FFF73FFF040010F0ACF9002816D0",
            "extent": 0x3C + 16,
            "boundary": "00F082FB364D374B"
        },
        "rr_companion": {
            "origin": None,
            "target": 0x0907DD44,
            "anchor_offset": 0x3C,
            "capture": 8,
            "pattern": "5A532000FFF704FD374E002822D0374B",
            "entry": "F8B5FFF73FFF040010F0ACF9002816D0",
            "extent": 0x3C + 16,
            "boundary": "00F082FB364D374B"
        }
    },
    "mon_given": {
        "rr": {
            "origin": 134482708,
            "target": 151508880,
            "anchor_offset": 104,
            "capture": 8,
            "pattern": "00200E4B01351D7070BD0135062DE3D1",
            "entry": "70B504001CF0FAFA20002BF0A1FE2000",
            "extent": 168,
            "boundary": "012313B51D220093",
            "trampoline": "0049084791D70709"
        },
        "rr_companion": {
            "origin": 134482708,
            "target": 151508880,
            "anchor_offset": 104,
            "capture": 8,
            "pattern": "00200E4B01351D7070BD0135062DE3D1",
            "entry": "70B504001CF0FAFA20002BF0A1FE2000",
            "extent": 168,
            "boundary": "012313B51D220093",
            "trampoline": "0049084791D70709"
        }
    },
    "pc_move": {
        "rr": {
            "origin": 134482832,
            "target": 151744056,
            "anchor_offset": 98,
            "capture": 6,
            "pattern": "00F0EDF90120F8BD01351E2DD7D10134",
            "entry": "F8B5204B0700204800F01AFA0006000E",
            "extent": 172,
            "boundary": "70B506000C001500",
            "trampoline": "00490847396E0B09"
        },
        "rr_companion": {
            "origin": 134482832,
            "target": 151744056,
            "anchor_offset": 98,
            "capture": 6,
            "pattern": "00F0EDF90120F8BD01351E2DD7D10134",
            "entry": "F8B5204B0700204800F01AFA0006000E",
            "extent": 172,
            "boundary": "70B506000C001500",
            "trampoline": "00490847396E0B09"
        }
    },
    "pc_withdraw": {
        "rr": {
            "origin": None,
            "target": 134819796,
            "anchor_offset": 30,
            "capture": 6,
            "pattern": "642252F140FF12E0",
            "entry": "F0B50006060E09060F0E192E12D10649",
            "extent": 92,
            "boundary": "00B50006000E0906"
        },
        "rr_companion": {
            "origin": None,
            "target": 134819796,
            "anchor_offset": 30,
            "capture": 6,
            "pattern": "642252F140FF12E0",
            "entry": "F0B50006060E09060F0E192E12D10649",
            "extent": 92,
            "boundary": "00B50006000E0906"
        }
    },
    "pc_box_place": {
        "rr": {
            "origin": None,
            "target": 134819796,
            "anchor_offset": 68,
            "capture": 8,
            "pattern": "301C391CF8F7CAFDF0BC01BC0047",
            "entry": "F0B50006060E09060F0E192E12D10649",
            "extent": 92,
            "boundary": "00B50006000E0906"
        },
        "rr_companion": {
            "origin": None,
            "target": 134819796,
            "anchor_offset": 68,
            "capture": 8,
            "pattern": "301C391CF8F7CAFDF0BC01BC0047",
            "entry": "F0B50006060E09060F0E192E12D10649",
            "extent": 92,
            "boundary": "00B50006000E0906"
        }
    }
}
RR_CONTRACTS = {
    "hatch": {"replaces": "AddHatchedMonToParty (RR in-place)",
        "source_path": "src/daycare.c#L1639-L1678", "source_root": PRET, "point": ["R5"],
        "contract": "RR ROM 08046D60 body; capture 08046E0A after its CalculateMonStats call. "
                    "R5 is the completed hatchling. RR CB2_EggHatch_0 calls this body at 080471D4; "
                    "the body, entry, tail and caller were read independently in both RR artifacts. "
                    "Require an aligned party record, non-egg/non-Bad-Egg; publish once in gift_daycare.",
        "extent": "RR body ends at 08046E20: return at +0xB0, three data words +0xB4..BF; next ScriptHatchMon entry pinned."},
    "faint": {
        "replaces": "Cmd_tryfaintmon (opcode 0x19 dead; capture moved to opcode 0x1B cleanup)",
        "source_path": "src/general_bs_commands.c#L1392-L1433",
        "point": ["R2", "R3", "R7"],
        "contract": "RR selects a replacement battle-script command table at 0903EF20 (five pool "
                    "words replaced): opcode 0x19 dispatches to atk19_tryfaintmon 0909E5BC, but the "
                    "physical census shows no fire there. The live once-per-faint witness is CFRU "
                    "atk1B_cleareffectsonfaint completion, at its state-reset/script-cursor-advance "
                    "epilogue (entry 0909E968, capture 0909EED2): fires once per faint (census v3b, "
                    "10/10 faints). Fainted battler = gActiveBattler (0x02023BC4, pokefirered.sym:77) "
                    "at this hit (validated by census v3b: 1 on the nine wild faints, 0 on the player "
                    "faint). Player side = gBattlerPositions[gActiveBattler] (0x02023BD6, "
                    "pokefirered.sym:81) & 1 == 0 (B_SIDE_PLAYER); party slot = "
                    "gBattlerPartyIndexes[gActiveBattler] (0x02023BCE, pokefirered.sym:80), then the "
                    "mon key PID:OTID from that party record — do NOT use gActiveBattler parity "
                    "directly as the side test. gBattleResults.playerFaintCounter 0x03004F90 also went "
                    "0->1 on the player-faint hit as a cross-check. docs/gen3/research/rr_faint_repin.md "
                    "R5 and docs/gen3/probes/census_rr_faint_v3b_catch_2026-09-21.txt pin this; the old "
                    "vanilla Cmd_tryfaintmon capture 080213C8 is DEAD on RR (opcode table replaced, "
                    "docs/gen3/research/rr_opcode_table_audit.md R4).",
        "extent": "Capture pattern ends at entry+0x56A+16=0x57A; boundary bytes checked immediately "
                  "after the capture slice, not a proved whole-function size."},
    "capture_wild": {
        "replaces": "Cmd_givecaughtmon (opcode 0xF0 dead; capture moved into the RR replacement body)",
        "source_path": "src/catching.c#L614-L656",
        "point": ["R0", "R4"],
        "contract": "RR selects a replacement battle-script command table at 0903EF20; opcode 0xF0 "
                    "dispatches to the RR atkF0_givecaughtmon replacement (entry 0907DD44), not the "
                    "dead vanilla Cmd_givecaughtmon (capture 0802D824+4 = 0802D828 DEAD on RR, "
                    "docs/gen3/research/rr_opcode_table_audit.md R4). Capture at 0907DD88, immediately "
                    "after the BL to the already-pinned RR GiveMonToPlayer body 0907D790 (BL at "
                    "0907DD84): R0 = placement result (0 party / 1 box / failure codes), R4 = caught "
                    "mon pointer (docs/gen3/research/rr_opcode_table_audit.md R4 decode). Pinned by "
                    "bytes here; live delivery has NOT yet been observed with the observer running, "
                    "though the RR catch input sequence (Right, A, Right, Right, A, "
                    "A at the action menu, ball pocket fixture 0x0203C354) is now pinned "
                    "(docs/gen3/probes/census_rr_faint_v3b_catch_2026-09-21.txt) so a driver can "
                    "exercise it. Do not count failure as acquisition or double-emit with mon_given: "
                    "the reducer must filter on R0's result before treating any hit as a catch, since "
                    "failures and duplicate GiveMonToPlayer/mon_given helper observations are not "
                    "themselves acquisitions.",
        "extent": "Capture pattern ends at entry+0x3C+16=0x4C; boundary bytes checked immediately "
                  "after the capture slice, not a proved whole-function size."},
    "mon_given": {
        "replaces": "GiveMonToPlayer", "source_path": "src/catching.c#L600-L620",
        "point": ["R0", "R4", "R5"],
        "contract": "RR replacement common POP at 0907D800, before restoring registers. "
                    "R0=party(0)/PC(1)/failure(2); R4=source mon. Party path has copied 100 bytes "
                    "and stored gPlayerPartyCount; PC path returns here after SendMonToPC. "
                    "R5 is a party count only on the party-success path. RR inline free-slot/forced-PC "
                    "logic differs from current upstream helper: binary is authoritative. Correlate "
                    "capture/gift caller before event emission; no event on failure.",
        "extent": "Estimate end 0907D838: code finishes with branch at +86 back to POP +70, "
                  "literal pool +88..A7, next routine begins MOVS then PUSH at +A8/+AA."},
    "pc_move": {
        "replaces": "SendMonToPC", "source_path": "src/pokemon_storage_system.c#L403-L435",
        "point": ["R0", "R4", "R5", "R7"],
        "contract": "RR compressed-PC acquisition common POP at 090B6EA0. R0=PC(1)/failure(2); "
                    "R4=box and R5=slot only on success, R7=source mon. Compression call "
                    "090B6E72 -> 090B6B78 completes before box/slot vars and return status. "
                    "This is acquisition-to-storage, not a general user deposit event.",
        "extent": "Estimate end 090B6EE4: final branch +82 returns to POP +68; "
                  "literal pool +84..AB; following PUSH starts at +AC."},
    "pc_withdraw": {
        "replaces": "SetPlacedMonData", "source_path": "src/pokemon_storage_system.c#L220-L233",
        "point": ["R6", "R7"],
        "contract": "RR IN-PLACE modification, not an entry trampoline. Compare at 08092FDE "
                    "uses party sentinel 25 (CMP R6,#19 hex), not vanilla 14. Capture at "
                    "08092FF8 after the 100-byte party memcpy. R6=25, R7=destination slot. "
                    "Moving-mon origin/caller distinguishes withdrawal from party rearrangement. "
                    "Vanilla control flow: pret pokemon_storage_system_data.c:625-633.",
        "extent": "Estimate inherited layout to 08093030 (+5C): code ends BX at +50, "
                  "padding/literals +52..5B; next PurgeMonOrBoxMon prologue at +5C."},
    "pc_box_place": {
        "replaces": "SetPlacedMonData", "source_path": "src/pokemon_storage_system.c#L220-L233",
        "point": ["R6", "R7"],
        "contract": "RR IN-PLACE wrapper; capture 08093020 after BL 0808BBB4. Require R6<25 "
                    "and R7<30 because party branch also reaches this POP. R6/R7 are destination "
                    "box/slot. Callee SetBoxMonAt detours to 090B6CA4, compresses at 090B6CC2 "
                    "then writes 58 bytes at 090B6CD6. Deduplicate against higher-level deposit. "
                    "Vanilla wrapper source: pret pokemon_storage_system_data.c:625-633.",
        "extent": "Estimate inherited layout to 08093030 (+5C): code ends BX at +50, "
                  "padding/literals +52..5B; next PurgeMonOrBoxMon prologue at +5C."},
}


def rr_resolution(c: dict, name: str, rom: bytes) -> dict | None:
    kind = c["kind"]
    if kind in ("borrowed_party_begin", "borrowed_party_opponent_begin", "borrowed_party_end"):
        from tools.research.rr_special_lifecycle import census
        try:
            facts = census(rom)["borrowed_party"]
            body = facts["bodies"]["builder" if kind == "borrowed_party_begin" else
                                    "opponent_builder" if kind == "borrowed_party_opponent_begin" else "restore"]
            flat = body["address"] - ROM_BASE
            code_size = 100 if kind == "borrowed_party_begin" else 52 if kind == "borrowed_party_opponent_begin" else 64
            data = rom[flat:flat + code_size]
            capture = 0x32 if kind == "borrowed_party_end" else 0x1C if kind == "borrowed_party_opponent_begin" else 0
            site = make_site(rom, flat, data, capture_offset=capture,
                             symbol=c["symbol"], point=["R15", "CPSR"])
            site.update(source="rr_school_script_binary",
                        capture_contract=c["inventory"],
                        context={"rom_offset": flat, "expected_hex": body["expected_hex"]},
                        function={"address": body["address"], "size": code_size,
                                  "capture_offset": capture, "anchor_offset": 0,
                                  "symbol": c["symbol"], "context_size": body["size"],
                                  "size_evidence": ("52-byte executable span includes NOP090790FA; "
                                                    "72-byte context adds20-byte pool090790FC..0907910F"
                                                    if kind == "borrowed_party_opponent_begin" else
                                                    "reviewed ROM code/return boundary")},
                        caller={"map": [5, 2], "npc_local_id": 1, "script": 0x09051ABF},
                        pair_contract={"begin": kind if kind != "borrowed_party_end" else
                                       ["borrowed_party_begin", "borrowed_party_opponent_begin"],
                                       "accepted_begins": ["borrowed_party_begin", "borrowed_party_opponent_begin"],
                                       "baseline_precedence": "first active own baseline preserved; later begin hits never replace it",
                                       "end": "borrowed_party_end",
                                       "party_base": facts["party_base"], "stride": 100,
                                       "baseline": "own raw records/keys/count before builder",
                                       "restore": "active epoch only; exact own keys/count match",
                                       "reset": "clear unmatched borrow on reset"})
            return {"status": "PINNED", "site": site, "matches": [flat]}
        except ValueError as exc:
            return {"status": "UNVERIFIED", "reason": str(exc)}
    if kind in ("poison_faint", "poison_hp_before"):
        try:
            detour = decode_thumb_detour(rom, 0x080A0618)
            at = detour["target"] - 0x08000000
            body = rom[at:at + 4].hex().upper()
            reason = (f"DoPoisonFieldEffect detour -> {detour['target']:08X}, bytes {body}; "
                      "MOVS R0,0 / BX LR: this admitted path has NO HP mutation or before/after pair"
                      if detour["target"] == 0x090B20D4 and body == "00207047"
                      else "poison disabled-body evidence differs; do not reuse vanilla tail")
            return {"status": "UNVERIFIED", "reason": reason, "detour": detour,
                    "reference_bytes": body}
        except ValueError as exc:
            return {"status": "UNVERIFIED", "reason": str(exc)}
    if kind == "borrowed_party":
        hits = find_offsets(rom, (0x02025564).to_bytes(4, "little"))
        aligned = [0x08000000 + i for i in hits if i % 4 == 0]
        return {"status": "UNVERIFIED", "reason":
                f"backup literal 02025564: {len(hits)} matches, aligned={','.join(hex(x) for x in aligned) or 'none'}; "
                "clean ROM has no aligned direct literal. Companion-only literal is patch data; "
                "MoveSaveBlocks_ResetHeap copies are relocation, not proof of a borrowed-party swap/restore. "
                "Indirect/synthesized addressing remains possible; no unique begin/restore pair established."}
    if kind in ("nature_change_begin", "nature_change"):
        from tools.research.rr_special_lifecycle import census, MUTATOR, MUTATOR_END
        try:
            facts = census(rom)["nature"]
            if (facts["anchor_occurrences"] != 1 or facts["code_sha256"] !=
                    "d9a37097cd0f5b8871109981c41a1b53dbc0dd274daeb6144ddb330080a2c045"):
                raise ValueError("Nature Changer body is missing, changed or ambiguous")
            flat = MUTATOR - ROM_BASE
            data = rom[flat:flat + MUTATOR_END - MUTATOR]
            capture = (facts["before_pid_store"] if kind == "nature_change_begin"
                       else facts["after_pid_store"]) - MUTATOR
            site = make_site(rom, flat, data, capture_offset=capture,
                             symbol=c["symbol"], point=["R4", "R15", "CPSR"])
            site.update(source="rr_script_special_binary",
                        source_url=PRET + "include/constants/pokemon.h#L5",
                        capture_contract=c["inventory"],
                        context={"rom_offset": flat, "expected_hex": data.hex().upper()},
                        function={"address": MUTATOR, "size": len(data),
                                  "capture_offset": capture, "anchor_offset": 0,
                                  "symbol": "RR_NatureChanger_PIDMutation",
                                  "size_evidence": "ROM code through branch090B1898; literals begin090B189C"},
                        caller={"map": facts["map"], "npc_local_id": 5,
                                "script": facts["npc"]["script"], "option": 0},
                        pair_contract={"begin": "nature_change_begin", "end": "nature_change",
                                       "mon_register": "R4", "slot_address": facts["slot_address"],
                                       "party_base": facts["party_base"], "stride": 100,
                                       "old_fields": ["PID", "OT"], "new_fields": ["PID", "OT"],
                                       "reset": "same epoch required; clear unmatched preimage on reset"})
            return {"status": "PINNED", "site": site, "matches": [flat]}
        except ValueError as exc:
            return {"status": "UNVERIFIED", "reason": str(exc)}
    if kind not in RR_BODIES:
        return None
    b, contract = RR_BODIES[kind][name], RR_CONTRACTS[kind]
    target = b["target"]
    detour = None
    try:
        if b["origin"] is not None:
            detour = decode_thumb_detour(rom, b["origin"])
            if detour["target"] != target:
                raise ValueError("decoded detour target differs from reviewed body")
            off = b["origin"] - 0x08000000
            if rom[off:off + 8].hex().upper() != b["trampoline"]:
                raise ValueError("trampoline/literal bytes differ")
        flat = target - 0x08000000
        if rom[flat:flat + 16].hex().upper() != b["entry"]:
            raise ValueError("replacement/in-place entry anchor differs")
        end = flat + b["extent"]
        if rom[end:end + 8].hex().upper() != b["boundary"]:
            raise ValueError("estimated body boundary anchor differs")
        data = pattern_bytes(b["pattern"])
        at = flat + b["anchor_offset"]
        if find_offsets(rom, data) != [at]:
            raise ValueError("replacement capture pattern is missing, ambiguous or at another offset")
        if b["anchor_offset"] + max(len(data), b["capture"] + 2) > b["extent"]:
            raise ValueError("capture exceeds estimated replacement extent")
        site = make_site(rom, at, data, capture_offset=b["capture"],
                         symbol=contract["replaces"], point=contract["point"])
        site.update(source="cfru_detour" if detour else "cfru_inplace",
                    source_url=contract.get("source_root", CFRU) + contract["source_path"], replaces=contract["replaces"],
                    capture_contract=contract["contract"],
                    context={"rom_offset": flat, "expected_hex": b["entry"]},
                    rr_body={"address": target, "extent_estimate": b["extent"],
                             "extent_evidence": contract["extent"],
                             "entry_hex": b["entry"], "boundary_hex": b["boundary"]})
        if detour:
            site["detour"] = detour
        if kind == "pc_box_place":
            callee = decode_thumb_detour(rom, 0x0808BBB4)
            entry = "70B5050090B00C001600182813D81D29"
            if (callee["target"] != 0x090B6CA4
                    or rom[0x10B6CA4:0x10B6CA4 + 16].hex().upper() != entry):
                raise ValueError("compressed SetBoxMonAt callee binding differs")
            site["callee_detour"] = dict(callee, entry_hex=entry)
        return {"status": "PINNED", "site": site, "matches": [at]}
    except ValueError as exc:
        return {"status": "UNVERIFIED", "reason": str(exc)}



def resolve(c: dict, name: str, rom: bytes) -> dict:
    if name in ("rr", "rr_companion"):
        specific = rr_resolution(c, name, rom)
        if specific is not None:
            return specific
    pattern = (c["patterns"] or {}).get(name, c["pattern"])
    binding = c.get("binding")
    if binding and name in SYMBOL_FILES:
        pattern = binding["anchors"][name]
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
    fn = None
    context = c["context"]
    if binding:
        vanilla = name in SYMBOL_FILES
        reference = name if vanilla else "fr"
        fn = symbol_table(reference)[binding["function"]]
        delta = -binding["anchor_offset"]
        if vanilla:
            if offset != fn["address"] - 0x08000000 + binding["anchor_offset"]:
                return {"status": "UNVERIFIED", "reason": "unique anchor is outside symbol location"}
            context = (delta, binding["entries"][name])
        if binding["anchor_offset"] + max(c["capture"] + 2, len(data)) > fn["size"]:
            return {"status": "UNVERIFIED", "reason": "capture or anchor exceeds symbol size"}
    if context:
        delta, expected = context
        actual = rom[offset + delta:offset + delta + len(expected) // 2]
        if actual.hex().upper() != expected:
            return {"status": "UNVERIFIED", "reason": "enclosing entry context differs (possible detour/dead tail)",
                    "matches": offsets, **diagnostic}
    try:
        site = make_site(rom, offset, data, capture_offset=c["capture"], symbol=c["symbol"], point=c["point"])
    except ValueError as exc:
        return {"status": "UNVERIFIED", "reason": str(exc), "matches": offsets, **diagnostic}
    site.update(source=PRET + c["source"], capture_contract=c["inventory"])
    if context:
        delta, expected = context
        site["context"] = {"rom_offset": offset + delta, "expected_hex": expected}
    if fn:
        info = {"symbol": binding["function"], "address": site["address"] - binding["anchor_offset"],
                "capture_offset": binding["anchor_offset"] + c["capture"],
                "anchor_offset": binding["anchor_offset"],
                "symbol_source": f"data/gen3/pret/{SYMBOL_FILES[reference]}:{fn['line']}",
                "symbols_sha256": SYMBOL_HASHES[reference]}
        if name in SYMBOL_FILES:
            info["size"] = fn["size"]
            info["size_evidence"] = "verified_vanilla_symbol"
        else:
            info["reference_size"] = fn["size"]
            info["size_evidence"] = "vanilla_reference_only"
        site["function"] = info
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
        if name == "rr_companion":
            # RR-DURABLE: the shipped durable-trade UPS (patch/dist/SLink-RR.ups); its native
            # trade descriptor binds only for explicit production metadata (lua/gen3/entry.lua).
            artifact = {"production": True, **artifact}
        packs[pack]["titles"].setdefault(title, {"artifacts": {}})["artifacts"][kind] = artifact
    for pack in packs.values():
        if pack["pack"] == "gen3_frlg":
            from tools.gen3_companions import published, artifact as companion_artifact
            for title, name in (("firered","fr"),("leafgreen","lg")):
                result=published(title,roms[name],ROOT)
                if result:
                    rom,row=result
                    artifacts=pack["titles"][title]["artifacts"]
                    artifacts["companion"]=companion_artifact(artifacts["clean"],rom,row)
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
        f"- [Pinned pret source]({PRET}). Vanilla function addresses/sizes come independently from "
        "data/gen3/pret/pokefirered.sym and pokeleafgreen.sym, including LOCAL symbols. "
        "Their fixed SHA-256s and source/ROM identities are checked against provenance.json. "
        f"[CFRU BPRE.ld]({CFRU}BPRE.ld) is only a cross-check, never the vanilla address authority.",
        "- Control address: patch/tools/build.py:63; parked "
        "codex/rr-foundation:docs/rr_reference/BIZHAWK_MGBA_CALLBACKS.md:150-170 "
        "(callback 0800051A, raw R15 0800051C). Artifact-specific control bytes are intentional.",
        "- Read-only Capstone 5.0.7 Thumb disassembly established FR capture boundaries and call targets; "
        "no disassembly/runtime dependency in regeneration. FR and LG capture windows were independently "
        "read and checked. RR transported matches are [INFERENCE] of the same local sequence, not proof "
        "of script-table dispatch/caller reachability or unchanged interior code. Runtime fields must come from each pack profile.",
        "- docs/gen3/probes/census_rr_overworld_2026-09-21.txt:7-17 observes R15=000001C4, "
        "CPSR mode/T=31/0 and tasks 0806E811,0806E83D,08079E0D during 1800 idle frames. "
        "This is BIOS idle census, not evidence for any gameplay site in this inventory.",
        "- RR GiveMonToPlayer/SendMonToPC now follow their decoded LDR/BX literals to "
        "0907D790/090B6E38; their retained vanilla tails are NOT used. RR SetPlacedMonData "
        "is modified IN PLACE (party sentinel 25, not 14), not entry-detoured. Its box-write "
        "callee SetBoxMonAt detours 0808BBB4 -> 090B6CA4 and writes compressed records.",
        "- RR DoPoisonFieldEffect detours 080A0618 -> 090B20D4, which is 00207047 "
        "(MOVS R0,0; BX LR): no HP mutation exists on this admitted path. Both poison rows "
        "stay un-emitted; their UNVERIFIED matrix label must not be read as an undiscovered "
        f"vanilla-style store. Source map: [CFRU overworld.c:1934-2001]({CFRU}src/overworld.c#L1934-L2001) "
        "has NO_POISON_IN_OW/POISON_1_HP_SURVIVAL branches; binary, not macro inference, settles this path.",
        "- RR backup literal search: clean has only unaligned 095DE3E1; companion additionally "
        "has patch literal 08379708. Party-base literal search has 906/910 matches respectively. "
        "These are search receipts, not writer attribution. The memcpy sites at 0804C10C/0804C212 "
        "sit in relocation/serialization code; they do not establish a unique borrowed-party begin/restore pair. "
        f"[CFRU build_pokemon.c:745-755]({CFRU}src/build_pokemon.c#L745-L755) names "
        "BackupPartyToTempTeam but supplies no verified RR binding for the requested special.",
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
        if c.get("binding"):
            b = c["binding"]
            lines += ["Function bounds and independently pinned entry anchors (vanilla):", "",
                      "| ROM | Symbol source | Function address / size | Function-relative capture | Entry bytes |",
                      "|---|---|---|---|---|"]
            for name in ("fr", "lg"):
                fn = symbol_table(name)[b["function"]]
                lines.append(f"| {name} | data/gen3/pret/{SYMBOL_FILES[name]}:{fn['line']} "
                             f"{b['function']} | {fn['address']:08X} / {fn['size']:X} "
                             f"| +{b['anchor_offset'] + c['capture']:X} | {b['entries'][name]} |")
            lines += ["", "Unless an RR-specific binding is described below, RR entry checks use the FR "
                      "entry bytes at the uniquely matched anchor minus the reviewed function-relative anchor "
                      "offset; a mismatch is refused, never repinned. JSON reference_size is a vanilla bound, "
                      "not a proved RR extent. frame_control retains its measured/patched artifact binding.", ""]
        if c["kind"] in RR_BODIES:
            contract = RR_CONTRACTS[c["kind"]]
            lines += ["RR-specific capture contract:", "",
                      f"[CFRU source map]({CFRU}{contract['source_path']}). {contract['contract']}",
                      "Binary body, not upstream C, is authoritative. " + contract["extent"], "",
                      "| Artifact | Entry/trampoline | Body entry bytes | Estimated extent | Boundary bytes |",
                      "|---|---|---|---|---|"]
            for name in ("rr", "rr_companion"):
                b = RR_BODIES[c["kind"]][name]
                entry = f"{b['origin']:08X} -> {b['target']:08X}" if b["origin"] else f"{b['target']:08X} in-place"
                lines.append(f"| {name} | {entry} | {b['entry']} | {b['extent']:X} (estimate) | {b['boundary']} |")
            lines.append("")
    lines += ["## Reproduce and falsify", "",
              "- python tools/gen_gen3_engine_signals.py --check (offline; all four pinned ROMs required).",
              "- python tools/pin_gen3_site.py HEX --rom fr --capture-offset 0 prints all matches and "
              "only a candidate record. It never writes/adopts a pin.",
              "- pytest tests/unit/test_gen3_engine_sites.py -q checks every emitted pin, exclusion, "
              "wrong ROM, ambiguous/odd matches and the retained RR-tail trap.",
              "", "## NOT VERIFIED", "",
              "The legacy generic borrowed_party candidate remains UNVERIFIED; RR School borrowed_party_begin/end "
              "are SOURCE pinned with exact builder/restore bodies and an active-borrow restore contract. "
              "School postbattle restore caller attribution remains UNRESOLVED. Nature Changer paired PID sites are SOURCE pinned "
              "by the exact NPC script and unique ROM body, not PHYSICAL qualified. Poison's replacement is disabled; "
              "its old tails remain excluded. Replacement extents are explicit estimates, not symbol sizes. "
              "Additional paths (multi-move, Shedinja creation, final trade scene/evolution completion) need "
              "separate evidence; the mutation sites here are not a claim of complete gameplay coverage. "
              "No emulator was run on this card. "
              "PINNED rows still need per-artifact natural-play positive/negative receipts, snapshot validity, "
              "semantic reduction, duplicate suppression and full caller coverage before P3 can close a row. "
              "Do not infer that byte-match tests physically qualify faint/capture/PC/trade/evolution/poison, all map paths, "
              "RR borrowed-party/nature changes, or flash persistence. Profile/save/checkpoint files are outside this lease.",
              ""]
    return "\n".join(lines)


# ── E1-PACK: vanilla Emerald (BPEE rev 0), a separate pack + inventory ─────────────────────
# Kept apart from ROM_SPECS/CANDIDATES so the FR/LG/RR outputs above stay byte-identical. Every
# capture offset below was RE-DERIVED on the Emerald bytes (Capstone 5.0.7 Thumb disassembly of
# each function out of pokeemerald.sym, read against the pinned pret source), never carried over
# from FR: faint/pc_move/mon_given/battle_end/save/poison/trade/PC-release keep the FR
# function-relative offset because the disassembled instruction streams match; capture_wild
# (+0x2A vs +0x28), whiteout (+0x54 vs +0x5A), map_load (+0x14 vs +0x2C), pc_deposit (+0x7E vs
# +0x80), both evolution stores (+0x462/+0x370 vs +0x492/+0x3A0) and frame_control (entry, no
# help-screen gate) moved.
EMERALD_PRET = "https://github.com/pret/pokeemerald/blob/c65e93f20a5275ab03b07d6f6411096a82a60ffd/"
EMERALD_SYMBOLS = "data/gen3/pret/pokeemerald.sym"
EMERALD_PROVENANCE = "data/gen3/pret/pokeemerald_provenance.json"
EMERALD_DOC = ROOT / "docs/gen3_emerald/engine_sites.md"
# kind -> (function, anchor_offset, capture, anchor hex @function+anchor_offset,
#          entry hex @function+0, pret source, point, capture contract)
EMERALD_BINDINGS = {
    "hatch": ("AddHatchedMonToParty", 0x9E, 12, "281CFDF7E4F9281CF7F7D5FB05B030BC",
        "30B585B00006000E03AC462121706421", "src/egg_hatch.c#L358-L397", ["R5"],
        "AddHatchedMonToParty +0xAA after MonRestorePP and CalculateMonStats; R5 = completed hatchling. "
        "Snapshot that aligned party record, require non-egg/non-Bad-Egg and valid checksum; "
        "O-15 publishes one gift_daycare capture at hatch, never at GiveEgg."),
    "frame_control": ("CallCallbacks", 0x0, 0, "10B5074C2068002801D0E6F2D3FD6068",
        "10B5074C2068002801D0E6F2D3FD6068", "src/main.c#L188-L195", ["R15", "CPSR"],
        "Emerald CallCallbacks has no save-failed/help-screen gate (FR 0800051A sits after one); "
        "it only runs gMain.callback1 then callback2. Capture the ENTRY: once per main-loop frame, "
        "before either callback. Frame control, not a game event. E2 CLIENT PRECONDITION: pret "
        "src/main.c#L171-L174 (UpdateLinkAndCallCallbacks) calls CallCallbacks only when "
        "!HandleLinkConnection(); during an active link exchange this site does not fire every "
        "frame. A client must not assume FR's help/save-failed gate, and must not assume this "
        "capture has FR's fixed one-hit-per-frame cadence."),
    "battle_begin": ("CB2_InitBattle", 0x0, 0, "00B540F063FA20F0DFFB26F0D5FC",
        "00B540F063FA20F0DFFB26F0D5FC28F0", "src/battle_main.c#L588-L617", ["R15", "CPSR"],
        "Entry, before MoveSaveBlocks_ResetHeap relocates the save blocks (first BL, 08076C2C). "
        "Emerald splits multi/recorded setup into CB2_InitBattleInternal and "
        "CB2_HandleStartMultiPartnerBattle, all reached from this one callback invocation; "
        "battle-type qualification and dedupe stay the consumer's duty."),
    "battle_end": ("ReturnFromBattleToOverworld", 0x74, 4, "08488068C2F7AAFA70BC01BC",
        "70B5204E306802252840002806D11E4C", "src/battle_main.c#L5217-L5249", ["R0", "R15", "CPSR"],
        "+0x78 is BL SetMainCallback2(gMain.savedCallback) on the completion branch, after "
        "inBattle is cleared (+0x44) and callback1 restored; the link-wait early return (+0x2C) "
        "bypasses it. R0 = the saved callback. Not an exp/evolution-settled checkpoint."),
    "faint": ("Cmd_tryfaintmon", 0x118, 4, "0130087038780DF03BFA26E064400202",
        "F0B54F464646C0B481B0184802689178", "src/battle_script_commands.c#L2965-L3050",
        ["R7", "R8", "R13"],
        "Battle opcode 0x19. +0x11C follows the PLAYER faint-counter increment/store (+0x118..+0x11A, "
        "battle_script_commands.c:3010-3011); a saturated counter skips the store but reaches the "
        "same point. R7/R8 point at gActiveBattler (02024064). Snapshot battler/party identity "
        "now; consumer dedupes; not every entry is a faint."),
    "capture_wild": ("Cmd_givecaughtmon", 0x26, 4, "14F0A1FE000600285CD0E4F0A0FD0006",
        "F0B557464E464546E0B419488146194D", "src/battle_script_commands.c#L10055-L10083",
        ["R0", "R5", "R8", "R9"],
        "Battle opcode 0xF0; +0x2A is immediately AFTER BL GiveMonToPlayer (+0x26; FR +0x24/+0x28, "
        "the Emerald prologue also saves R10). R0 = party/PC/failure result before the shift; "
        "R5 = &gBattlerAttacker, R8 = gEnemyParty, R9 = gBattlerPartyIndexes. Do not count "
        "failure as acquisition or emit twice with mon_given."),
    "mon_given": ("GiveMonToPlayer", 0x6C, 10, "301C00F005F80006000E70BC02BC0847",
        "70B5061C094C22680721FFF745FC2268", "src/pokemon.c#L4425-L4445", ["R0", "R6", "R13"],
        "Common POP at +0x76, after the party copy (R0=MON_GIVEN_TO_PARTY 0) or the CopyMonToPC "
        "return (R0=1 PC / 2 can't give). R6 = source mon. Callers: Cmd_givecaughtmon and "
        "ScriptGiveMon; caller context is required before classifying gift versus catch."),
    "pc_move": ("CopyMonToPC", 0x9C, 4, "BFD1022008BC9846F0BC02BC0847",
        "F0B5474680B480461A4832F0FBF80006", "src/pokemon.c#L4447-L4479", ["R0", "R5", "R6", "R8"],
        "CopyMonToPC (the FR SendMonToPC, renamed and static) called by GiveMonToPlayer; +0xA0 is "
        "the common return before register restoration. R0=MON_GIVEN_TO_PC(1) or MON_CANT_GIVE(2); "
        "R5/R6 destination box/slot only on success; R8 source mon. Acquisition-to-storage, not "
        "every PC menu operation."),
    "whiteout": ("CB2_WhiteOut", 0x48, 12, "00F0EEF90748FFF76FFF07487AF7C8FA",
        "00B581B016498720C000091808780130", "src/overworld.c#L1550-L1570", ["R0", "R15"],
        "+0x54 is BL SetMainCallback2(CB2_Overworld) on the ++gMain.state >= 120 completion branch "
        "(FR +0x5A). The party is already healed by DoWhiteOut "
        "(+0x26); a completion marker, not an HP-at-faint witness."),
    "map_load": ("CB2_LoadMap2", 0x08, 12, "00F0BCF90448FFF73DFF04487AF796FA",
        "00B5064800F0D6FB00F0BCF90448FFF7", "src/overworld.c#L1582-L1588", ["R0", "R15"],
        "+0x14 is BL SetMainCallback2(CB2_Overworld) after DoMapLoadLoop (+0x04) finished the load. "
        "Emerald has no Quest Log branch, so this is the only path through CB2_LoadMap2 (FR +0x2C "
        "on its normal branch). CB2_LoadMap only schedules; other loaders stay uncovered."),
    "evolve_species_store": ("Task_EvolutionScene", 0x45A, 8, "48460B212CF76DF948462AF79AF96189",
        "F0B54F464646C0B486B00006070E184A", "src/evolution_scene.c#L757-L771", ["R9", "R4"],
        "EVOSTATE_SET_MON_EVOLVED: +0x462 immediately after SetMonData(mon, MON_DATA_SPECIES) whose "
        "BL is +0x45E (evolution_scene.c:764). R9 = mon, R4 = task. Stats/re-nickname/dex follow; "
        "cancellation bypasses this state."),
    "trade_evolve_species_store": ("Task_TradeEvolutionScene", 0x368, 8,
        "48460B212BF7C2FB484629F7EFFB6189", "F0B54F464646C0B486B00006070E0C4B",
        "src/evolution_scene.c#L1176-L1190", ["R9", "R4"],
        "T_EVOSTATE_SET_MON_EVOLVED: +0x370 after the SetMonData species BL at +0x36C "
        "(evolution_scene.c:1183). R9 = mon (FR used R8), R4 = task. Correlate the trade lease to "
        "suppress an ordinary key_change during SLink apply."),
    "trade_begin": ("TradeMons", 0x0, 0, "F0B54F464646C0B481B00C1C0006000E",
        "F0B54F464646C0B481B00C1C0006000E", "src/trade.c#L3102-L3130", ["R0", "R1", "R14"],
        "TradeMons entry: R0 player slot, R1 partner slot, pre-swap identities. Callers: the "
        "in-game cable/wireless animations (trade.c:3874, :4371) and the link path (:4633)."),
    "trade_done": ("TradeMons", 0xBA, 4, "FFF79BFF01B018BC9846A146F0BC01BC",
        "F0B54F464646C0B481B00C1C0006000E", "src/trade.c#L3102-L3130", ["R7", "R9", "R5"],
        "TradeMons +0xBE before stack restoration: both party/enemy copies and mail/dex updates are "
        "done. RECORD-SWAP completion, NOT scene/evolution completion; use trade_begin for the "
        "old key."),
    "save": ("TrySavingData", 0x38, 6, "02480480012030BC02BC084794620003",
        "30B50006050E09480468012C09D1281C", "src/save.c#L765-L785", ["R0", "R5", "R13"],
        "Common POP at +0x3E before R5 is restored: require R0==1 (SAVE_STATUS_OK) AND "
        "R5==SAVE_NORMAL(0). One observation per invocation; not every call is a full save."),
    "poison_hp_before": ("DoPoisonFieldEffect", 0x30, 4, "70F7D0FE0090002803D00138",
        "F0B581B0194C002700260525201C0521", "src/field_poison.c#L120-L154", ["R0", "R4", "R5"],
        "+0x34 after GetMonData(MON_DATA_HP) (field_poison.c:133), before the stack store/"
        "decrement. R0 = old HP, R4 = mon. Pair with poison_faint by pointer and iteration."),
    "poison_faint": ("DoPoisonFieldEffect", 0x46, 8, "39216A4671F78DFA01376434013D002D",
        "F0B581B0194C002700260525201C0521", "src/field_poison.c#L120-L154", ["R4", "R13", "R5"],
        "+0x4E immediately after SetMonData(MON_DATA_HP) (field_poison.c:137). R4 = mon, [R13] = "
        "new HP. REQUIRE new HP==0 AND paired old HP>0; one edge per newly fainted mon."),
    "pc_deposit": ("TryStorePartyMonInBox", 0x76, 8, "012139F7C8FF012070BC02BC0847",
        "70B50006060E301CF8F716FF0004040C", "src/pokemon_storage_system.c#L6400-L6424",
        ["R0", "R4", "R6"],
        "Called by the deposit menu (pokemon_storage_system.c:2872). +0x7E is the common POP (FR "
        "+0x80: the Emerald sStorage load is one instruction shorter) with R0 bool, R6 box and R4 "
        "slot<<24 on success. Requires R0==1."),
    "pc_withdraw": ("SetPlacedMonData", 0x1E, 6, "64221BF292F912E0",
        "F0B50006060E09060F0E0E2E12D10649", "src/pokemon_storage_system.c#L6365-L6376", ["R6", "R7"],
        "Party branch: +0x24 after memcpy(gPlayerParty[position], movingMon, 100), before the branch "
        "to the epilogue. R6=14, R7=party destination. Correlate moving-mon origin before emitting "
        "box_to_party."),
    "pc_box_place": ("SetPlacedMonData", 0x44, 8, "301C391C03F020FFF0BC01BC0047",
        "F0B50006060E09060F0E0E2E12D10649", "src/pokemon_storage_system.c#L6365-L6376", ["R6", "R7"],
        "Common epilogue +0x4C after the SetBoxMonAt call on the box path. The party path joins "
        "here too: REQUIRE R6<14 and R7<30. Do not duplicate pc_deposit."),
    "pc_release_begin": ("ReleaseMon", 0x0, 0, "00B5FDF7A1FE03490878002804D00020",
        "00B5FDF7A1FE03490878002804D00020", "src/pokemon_storage_system.c#L6460-L6479",
        ["R13", "R14"],
        "ReleaseMon entry, called after confirmation (pokemon_storage_system.c:2958). Capture the "
        "pre-removal identity before the purge; pairs with pc_release."),
    "pc_release": ("ReleaseMon", 0x38, 6, "101CFFF7E9FE00F013FC01BC0047",
        "00B5FDF7A1FE03490878002804D00020", "src/pokemon_storage_system.c#L6460-L6479", ["R13"],
        "+0x3E after PurgeMonOrBoxMon (BL +0x3A), before the display refresh. One confirmed "
        "release; resolve the key from the pc_release_begin snapshot."),
}


@lru_cache(maxsize=1)
def emerald_symbols() -> tuple[dict, str]:
    raw = (ROOT / EMERALD_SYMBOLS).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    provenance = json.loads((ROOT / EMERALD_PROVENANCE).read_text(encoding="utf-8"))
    if (digest != provenance["sha256"]
            or provenance["rom"]["sha1"] != EMERALD_SPECS["e"][4]
            or provenance["origin"]["source_commit"] != EMERALD_PRET.split("/")[-2]):
        raise ValueError("emerald: symbol/build provenance mismatch")
    return parse_symbols(raw.decode("utf-8")), digest


def emerald_resolve(kind: str, rom: bytes) -> dict:
    """One Emerald site: unique anchor, inside its .sym function, entry bytes checked."""
    function, anchor_offset, capture, anchor, entry, source, point, contract = EMERALD_BINDINGS[kind]
    symbols, digest = emerald_symbols()
    fn = symbols.get(function)
    if fn is None:
        return {"status": "UNVERIFIED", "reason": f"{function} is absent or ambiguous in the .sym"}
    data = pattern_bytes(anchor)
    offsets = find_offsets(rom, data)
    base = fn["address"] - ROM_BASE
    if offsets != [base + anchor_offset]:
        return {"status": "UNVERIFIED", "matches": offsets,
                "reason": f"exact pattern has {len(offsets)} matches or sits outside {function}"}
    if anchor_offset + max(capture + 2, len(data)) > fn["size"]:
        return {"status": "UNVERIFIED", "reason": "capture or anchor exceeds symbol size"}
    if rom[base:base + len(entry) // 2].hex().upper() != entry:
        return {"status": "UNVERIFIED", "reason": "enclosing entry context differs"}
    try:
        site = make_site(rom, offsets[0], data, capture_offset=capture, symbol=function, point=point)
    except ValueError as exc:
        return {"status": "UNVERIFIED", "reason": str(exc), "matches": offsets}
    site.update(source=EMERALD_PRET + source, capture_contract=contract,
                context={"rom_offset": base, "expected_hex": entry},
                function={"symbol": function, "address": fn["address"],
                          "anchor_offset": anchor_offset, "capture_offset": anchor_offset + capture,
                          "size": fn["size"], "size_evidence": "verified_vanilla_symbol",
                          "symbol_source": f"{EMERALD_SYMBOLS}:{fn['line']}",
                          "symbols_sha256": digest})
    return {"status": "PINNED", "site": site, "matches": offsets}


def build_emerald(rom: bytes) -> tuple[dict, dict]:
    sha1 = EMERALD_SPECS["e"][4]
    if hashlib.sha1(rom).hexdigest() != sha1:
        raise ValueError("e: ROM identity changed")
    inventory = {kind: emerald_resolve(kind, rom) for kind in EMERALD_BINDINGS}
    artifact = {"rom_sha1": sha1, "rom_md5": hashlib.md5(rom).hexdigest(),
                "sites": {k: r["site"] for k, r in inventory.items() if r["status"] == "PINNED"}}
    pack = {"schema": "gen3-engine-signals-v1", "pack": "gen3_emerald",
            "evidence": "SOURCE_BYTE_PIN", "live_verified": False,
            "titles": {"emerald": {"artifacts": {"clean": artifact}}}}
    from tools.gen3_companions import published, artifact as companion_artifact
    result=published("emerald",rom,ROOT)
    if result:
        patched,row=result
        pack["titles"]["emerald"]["artifacts"]["companion"]=companion_artifact(artifact,patched,row)
    pack["sha256"] = hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return pack, inventory


def document_emerald(inventory: dict) -> str:
    fr = {kind: b["anchor_offset"] + b["capture"] for kind, b in BINDINGS.items()}
    lines = [
        "# Emerald engine-site inventory (SOURCE only)", "",
        "Generated by tools/gen_gen3_engine_signals.py (EMERALD_BINDINGS); edit that table, never "
        "this file. Same schema and meaning as docs/gen3_engine_sites.md: PINNED is a unique exact "
        "byte anchor at its pokeemerald.sym function offset with the function entry bytes checked. "
        "It is NOT physical hook delivery, caller coverage or a release verdict. live_verified "
        "stays false until E2.", "",
        "Schema: data/games/gen3_emerald/engine_signals.json titles.emerald.artifacts.clean.sites[kind] "
        "= {address, capture_offset, expected_hex, rom_offset, point, mode=thumb, context, function}. "
        "address=08000000+rom_offset; hook address=address+capture_offset.", "",
        "## Sources", "",
        f"- [pret/pokeemerald @ c65e93f2]({EMERALD_PRET}); function addresses/sizes from "
        f"{EMERALD_SYMBOLS} (pret symbols branch dba968c6), sha256 checked against "
        f"{EMERALD_PROVENANCE}.",
        "- Capture offsets were re-derived per kind by read-only Capstone 5.0.7 Thumb disassembly of "
        "the Emerald function, read against the pret source; no FR offset is assumed to transfer. "
        "The FR column below is for comparison only.",
        "- OPEN kinds: none. Every FR site kind has an Emerald counterpart that pins cleanly; an "
        "UNVERIFIED row below would mean a resolver refusal and the kind is absent from the JSON.",
        "", "## ROM identity", "",
        "| Artifact | SHA-1 (required) |", "|---|---|",
        f"| e (Pokemon - Emerald Version (USA, Europe), BPEE rev 0) | {EMERALD_SPECS['e'][4]} |",
        "", "## PINNED / UNVERIFIED matrix", "",
        "| Kind | Emerald | Function | FR capture | Emerald capture |", "|---|---|---|---|---|",
    ]
    for kind, b in EMERALD_BINDINGS.items():
        r = inventory[kind]
        lines.append(f"| {kind} | {r['status']} | {b[0]} | +{fr[kind]:X} | +{b[1] + b[2]:X} |")
    lines += ["", "## Capture inventory", ""]
    for kind, (function, _, _, _, entry, source, point, contract) in EMERALD_BINDINGS.items():
        r = inventory[kind]
        lines += [f"### {kind} — {function}", "",
                  f"[pret {source}]({EMERALD_PRET}{source}). {contract} Point: {', '.join(point)}.", "",
                  "| Status | Function address / size | Anchor address / capture offset / flat "
                  "| Expected bytes | Entry bytes |", "|---|---|---|---|---|"]
        if r["status"] == "PINNED":
            s, fn = r["site"], r["site"]["function"]
            lines.append(f"| PINNED | {fn['address']:08X} / {fn['size']:X} ({fn['symbol_source']}) "
                         f"| {s['address']:08X} / +{s['capture_offset']:X} / {s['rom_offset']:X} "
                         f"| {s['expected_hex']} | {entry} |")
        else:
            lines.append(f"| UNVERIFIED | — | — | — | {r['reason']} |")
        lines.append("")
    lines += ["## Reproduce and falsify", "",
              "- python tools/gen_gen3_engine_signals.py --check (offline; needs the pinned ROMs).",
              "- python tools/pin_gen3_site.py HEX --rom e --symbol-file data/gen3/pret/pokeemerald.sym "
              "--symbol NAME prints every match and a candidate record only.",
              "- pytest tests/unit/test_gen3_emerald_pack.py -q: every expected_hex at its rom_offset, "
              "uniqueness, function bounds, entry context, a corrupted-entry refusal, plus the profile "
              "HEADER / literal-pool controls.", "",
              "## NOT VERIFIED", "",
              "No emulator was run. Natural-play positive/negative receipts, caller coverage "
              "(ScriptGiveMon gifts, Battle Frontier/contest/secret-base paths, multi-move, Shedinja, "
              "trade scene completion) and flash persistence remain open for E2.", ""]
    return "\n".join(lines)


# X1 offsets below are from the reference build's Thumb disassembly, not vanilla.
# SOURCE contracts were read at e8bd1cd7; pack remains unadmitted/live_verified=false.
EXPANSION_BINDINGS = {
    "frame_control": ("AgbMainLoop", 0x20, "src/main.c:134-172", ["R15", "CPSR"],
        "Start of the main-loop iteration at input polling, before callbacks; back edges from both VBlank wait paths return here. Not the inlined CallCallbacks function or FR's help gate."),
    "battle_begin": ("CB2_InitBattle", 0, "src/battle_main.c:472-504", ["R15", "CPSR"],
        "Entry before battle initialization/save relocation. Dedupe and battle-type filtering required."),
    "battle_end": ("ReturnFromBattleToOverworld", 0x38, "src/battle_main.c:5422-5457", ["R0", "R15", "CPSR"],
        "BL SetMainCallback2 after inBattle clear/callback1 restore on completion path. R0 saved callback; link-wait return bypasses this point. Not evolution-settled."),
    "faint": ("Cmd_tryfaintmon", 0x8A, "src/battle_script_commands.c:1906; src/battle_util.c:11125-11153", ["R4", "R15", "CPSR"],
        "After SetValuesOnFaint returns; R4 is battler, player/opponent counters updated. REQUIRE player-side ownership and identity dedupe; not every opcode invocation is a faint."),
    "capture_wild": ("GiveCapturedMonToPlayer", 0x62, "src/battle_script_commands.c:8371; src/pokemon.c:2941-2961", ["R0", "R6", "R13", "R15", "CPSR"],
        "Common return: R0 party/PC/failure, R6 source mon. REQUIRE saved caller LR at R13+16 equal 0x080AA0DA or 0x080AA36A (the two compiler-emitted Cmd_givecaughtmon call returns), success, and dedupe against mon_given. ScriptGiveMon also calls this routine."),
    "mon_given": ("GiveCapturedMonToPlayer", 0x62, "src/pokemon.c:2941-2961; src/script_pokemon_util.c:76", ["R0", "R6", "R13", "R15", "CPSR"],
        "Common return after party copy or CopyMonToPC. R0 outcome, R6 source mon. Captures and scripted gifts share this renamed routine; classify by caller and dedupe capture_wild."),
    "pc_move": ("CopyMonToPC", 0x72, "src/pokemon.c:2963", ["R0", "R5", "R7", "R8", "R15", "CPSR"],
        "Common epilogue: R0 allocation result, R8 source mon, R7 box/R5 slot only on success. Acquisition-to-storage, not every PC menu operation."),
    "whiteout": ("CB2_WhiteOut", 0x80, "src/overworld.c:1956-1981", ["R0", "R15", "CPSR"],
        "BL SetMainCallback2(CB2_Overworld) after whiteout healing/load completion; early state<120 return bypasses it. Not an HP-at-faint witness."),
    "map_load": ("CB2_LoadMap2", 0x22, "src/overworld.c:1992-1998", ["R0", "R15", "CPSR"],
        "BL SetMainCallback2(CB2_Overworld) after DoMapLoadLoop and callback1 restoration. Other map loaders remain outside this signal's coverage."),
    "evolve_species_store": ("Task_EvolutionScene", 0x2D6, "src/evolution_scene.c:786-792", ["R4", "R15", "CPSR"],
        "After SetMonData(MON_DATA_SPECIES=18), before evolution-tracker reset and stat/dex updates. R4 mon; cancellation bypasses this state."),
    "trade_evolve_species_store": ("Task_TradeEvolutionScene", 0x252, "src/evolution_scene.c:1214-1220", ["R7", "R15", "CPSR"],
        "After SetMonData(MON_DATA_SPECIES=18), before tracker/stat/dex updates. R7 mon; correlate native trade lease."),
    "trade_begin": ("TradeMons", 0, "src/trade.c:3083", ["R0", "R1", "R15", "CPSR"],
        "Entry: R0 player slot, R1 partner slot, pre-swap identities."),
    "trade_done": ("TradeMons", 0xE2, "src/trade.c:3083-3205", ["R15", "CPSR"],
        "Common epilogue after record/mail/dex branches; record-swap completion, not scene/evolution completion."),
    "save": ("TrySavingData", 0x16, "src/save.c:773-792", ["R0", "R4", "R15", "CPSR"],
        "Common epilogue before R4 restore. REQUIRE R0==SAVE_STATUS_OK(1) and R4==SAVE_NORMAL(0); every failure also reaches here."),
    "poison_hp_before": ("DoPoisonFieldEffect", 0x3C, "src/field_poison.c:125-149", ["R0", "R4", "R15", "CPSR"],
        "After GetMonData(MON_DATA_HP=10). R0 old HP, R4 mon. Pair by mon/iteration with post-store point."),
    "poison_faint": ("DoPoisonFieldEffect", 0x54, "src/field_poison.c:135-149", ["R4", "R13", "R15", "CPSR"],
        "Both SetMonData branches join before advancing R4. New HP=[R13]. REQUIRE paired old HP>0 and new HP==0. Reference build has Gen4+ poison minimum1, so this is not a demonstrated faint path."),
    "pc_withdraw": ("SetPlacedMonData", 0x9A, "src/pokemon_storage_system.c:6450-6463", ["R4", "R5", "R6", "R15", "CPSR"],
        "Party branch after SetMonFormPSS: R5==14, R6 slot, R4 party mon. Correlate moving-mon origin; placement can also be a party rearrangement."),
    "pc_box_place": ("SetPlacedMonData", 0x5A, "src/pokemon_storage_system.c:6464-6468", ["R5", "R6", "R15", "CPSR"],
        "Box branch after SetMonFormPSS: R5==5*box ID, R6 slot. Require box<14/slot<30 and correlate origin; do not duplicate deposit."),
    "pc_deposit": ("Task_DepositMenu", 0x16E, "src/pokemon_storage_system.c:2843-2880,6492-6517", ["R4", "R5", "R7", "R15", "CPSR"],
        "State 1, chosen box<14 and free slot<30: inlined TryStorePartyMonInBox joins here after SetPlacedMonData and party-icon destruction or moving-flag clear. R7 chosen box, R4 first free slot, R5=&sStorage; successful deposit only. Distinguish moved-mon origin using sIsMonBeingMoved before the call, and do not duplicate pc_box_place."),
    "pc_release_begin": ("Task_ReleaseMon", 0xFA, "src/pokemon_storage_system.c:2908-2958,6552-6582", ["R5", "R15", "CPSR"],
        "State 3 after DestroyReleaseMonIcon and the moved-mon bypass: R5=&sStorage; snapshot sCursorArea/sCursorPosition and pre-removal mon identity now. Party area selects boxId=TOTAL_BOXES_COUNT; box area selects StorageGetCurrentBox. Pair with pc_release; no snapshot is emitted for moved-mon flag clear."),
    "pc_release": ("Task_ReleaseMon", 0x17C, "src/pokemon_storage_system.c:2954-2958,6552-6582", ["R5", "R15", "CPSR"],
        "State 3 common continuation after inlined party ZeroMonData or box ZeroBoxMonAt and optional AddBagItem; R5=&sStorage. Emit only with a matching pc_release_begin snapshot, because the moved-mon flag-clear path also joins here. Resolve identity from that snapshot, never from cleared storage."),
}
EXPANSION_OPEN = {}

# Per-build PC cursor/state facts, bound to the .sym by expansion_symbol (which refuses a
# name that is not unique) and cross-checked against the ROM. `from_sStorage` is the byte offset
# from &sStorage; the address itself is never written as a literal here, it comes from the .sym.
#
# Additive registry metadata: the consumers (upr_pipeline.py:348-362, e2e_duo.py:3106) read only
# address/expected_hex/rom_offset/capture_offset/point/mode/function/symbol, so these keys are
# carried and ignored. No runtime consumer is added by this change and none is implied.
EXPANSION_CURSOR_SYMBOLS = {
    "sStorage": 0,
    "sCursorArea": 4,
    "sIsMonBeingMoved": 5,
    "sCursorPosition": 24,
}

# Snapshot provenance, per site. `contract` is the one-shot pairing obligation; it is a contract
# only, there is no consumer here and none should be added without a run card.
EXPANSION_SNAPSHOT_PROVENANCE = {
    "pc_release_begin": {
        "emits": "pc_release_begin",
        "one_shot": True,
        "cleared_by": ["pc_release", "release_cancel", "task_change", "storage_reset"],
        "reads": ["sCursorArea", "sCursorPosition", "sIsMonBeingMoved"],
        "contract": ("Consumed once by the next pc_release from the SAME Task_ReleaseMon invocation. "
                     "A moved-mon flag clear emits no begin and must not reuse an older latch."),
    },
    "pc_release": {
        "emits": "pc_release",
        "one_shot": False,
        "consumes": "pc_release_begin",
        "cleared_by": ["pc_release", "release_cancel", "task_change", "storage_reset"],
        "contract": ("Emit only when a matching pc_release_begin latch exists; resolve identity from "
                     "the snapshot, never from cleared storage."),
    },
    "pc_deposit": {
        "emits": "pc_deposit",
        "one_shot": False,
        "cleared_by": ["task_change", "storage_reset"],
        "reads": ["sIsMonBeingMoved"],
        "contract": ("Read sIsMonBeingMoved BEFORE the storage call to tell a moved-mon release-clear "
                     "apart from an acquisition deposit. R4 slot and R7 box are compiled def-use; "
                     "runtime liveness is not demonstrated by this pin."),
    },
}


def expansion_cursor_symbols(context):
    """Bind the PC cursor/state globals to the .sym, and prove the ROM agrees.

    The base is taken from sStorage EXPLICITLY, not from whichever name the table yields first:
    a table reorder or a rename of the first key must not silently redefine every other offset.
    """
    from tools.gen_gen3_profile import expansion_symbol
    out = {}
    base = expansion_symbol(context, "sStorage")["address"]
    for name, offset in EXPANSION_CURSOR_SYMBOLS.items():
        hit = expansion_symbol(context, name)
        want = base + offset
        if hit["address"] != want:
            raise ValueError(f"{name} is 0x{hit['address']:08X}, expected &sStorage+{offset} = 0x{want:08X}")
        out[name] = {"address": hit["address"], "size": hit["size"], "from_sStorage": offset,
                     "symbol_source": f"build:pokemon.sym:{hit['line']}",
                     "symbols_sha256": context["source"]["symbols_sha256"],
                     "size_evidence": "verified_build_symbol"}
    return out


def expansion_pool_register(context, symbol, offset=8, register=5):
    """Prove `ldr r<register>,[pc,#imm]` at `symbol+offset` resolves to &sStorage.

    Static register reasoning over verified ROM bytes. It does NOT demonstrate that the value is
    live at the capture point; that is a PHYSICAL question this card leaves open.
    """
    from tools.gen_gen3_profile import expansion_symbol
    from tools.pin_gen3_site import ROM_BASE
    fn = expansion_symbol(context, symbol)
    base = fn["address"] - ROM_BASE
    ins = int.from_bytes(context["rom"][base + offset:base + offset + 2], "little")
    if ins & 0xF800 != 0x4800 or (ins >> 8) & 7 != register:
        raise ValueError(f"{symbol}+{offset:#x} is not ldr r{register},[pc,#imm] (0x{ins:04X})")
    pool = ((offset + 4) & ~3) + (ins & 0xFF) * 4
    word = int.from_bytes(context["rom"][base + pool:base + pool + 4], "little")
    storage = expansion_symbol(context, "sStorage")["address"]
    if word != storage:
        raise ValueError(f"{symbol}+{offset:#x} pool resolves 0x{word:08X}, not &sStorage 0x{storage:08X}")
    return {"symbol": symbol, "function_offset": offset, "register": f"R{register}",
            "pool_function_offset": pool, "pool_value": word,
            "evidence": "COMPILED_DEF_USE", "runtime_liveness": "OPEN_PHYSICAL"}


def build_expansion(context):
    import copy

    from tools.gen_gen3_profile import EXPANSION_TITLE
    from tools.pin_gen3_site import pin_expansion_site

    sites, inventory = {}, {}
    for kind, (symbol, capture, source, point, contract) in EXPANSION_BINDINGS.items():
        site = pin_expansion_site(context, symbol, capture, point)
        site.update(source=f"expansion@{context['source']['source_commit']}:{source}", capture_contract=contract)
        sites[kind] = site
        inventory[kind] = {"status": "PINNED_SOURCE_ONLY", "source": source, "capture_contract": contract}
    inventory.update({k: {"status": "OPEN", "reason": v} for k, v in EXPANSION_OPEN.items()})
    cursors = expansion_cursor_symbols(context)
    for kind, provenance in EXPANSION_SNAPSHOT_PROVENANCE.items():
        if kind not in sites:
            raise ValueError(f"snapshot provenance names unknown site: {kind}")
        for name in provenance.get("reads", ()):
            if name not in cursors:
                raise ValueError(f"{kind} provenance names unbound cursor symbol: {name}")
        if "consumes" in provenance and provenance["consumes"] not in sites:
            raise ValueError(f"{kind} provenance consumes unknown site: {provenance['consumes']}")
        if provenance.get("emits") != kind:
            raise ValueError(f"{kind} provenance declares emits={provenance.get('emits')!r}")
        # A returned pack is caller-owned. Handing out the module constant by reference would let
        # one build's mutation leak into the next build, so each pack gets its own copy.
        sites[kind]["snapshot"] = copy.deepcopy(provenance)
    for kind in sites:
        sites[kind].setdefault("snapshot", None)
    register_proof = {symbol: expansion_pool_register(context, symbol)
                      for symbol in ("Task_DepositMenu", "Task_ReleaseMon")}
    result = {"schema": "gen3-engine-signals-v1", "pack": "gen3_exp", "build": context["build"],
              "evidence": "SOURCE_BYTE_PIN", "live_verified": False, "source": context["source"],
              "inventory": inventory, "titles": {EXPANSION_TITLE: {"artifacts": {"clean": {
                  "rom_sha1": context["source"]["rom_sha1"], "rom_md5": hashlib.md5(context["rom"]).hexdigest(),
                  "cursor_symbols": cursors, "register_pool_proof": register_proof, "sites": sites}}}}}
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--expansion", choices=["28877d73"])
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    if args.expansion:
        from tools.gen_gen3_profile import expansion_inputs, expansion_write

        context = expansion_inputs(args.expansion, args.artifacts)
        expansion_write(context, "engine_signals.json", build_expansion(context), args.check)
        return 0
    try:
        packs, inventory = build({name: load_rom(name) for name in ROM_SPECS})
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")

    outputs = {output_path(p): json.dumps(v, indent=2, sort_keys=True) + "\n" for p, v in packs.items()}
    outputs[DOC] = document(inventory)

    # Emerald is a separate, copyrighted ROM the FR/LG/RR verdict must not depend on: guard it in
    # its own step so a machine without it still gets a full --check of the three packs above.
    # Absence is not a defect (exit 0, printed and excluded from `outputs`/`stale`); a present but
    # wrong-identity ROM, or a pinned pack that no longer regenerates byte-identical, is a real
    # defect and is treated exactly like an FR/LG/RR mismatch (exit 1).
    emerald_failed = False
    try:
        e_rom = load_rom("e")
    except OSError:
        print("Emerald ROM absent: gen3_emerald not checked")
    except ValueError as exc:
        print(f"Emerald ROM error: {exc}")
        emerald_failed = True
    else:
        try:
            e_pack, e_inventory = build_emerald(e_rom)
        except ValueError as exc:
            print(f"Emerald ROM error: {exc}")
            emerald_failed = True
        else:
            outputs[output_path("gen3_emerald")] = json.dumps(e_pack, indent=2, sort_keys=True) + "\n"
            outputs[EMERALD_DOC] = document_emerald(e_inventory)
            inventory = dict(inventory, e=e_inventory)

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
    if stale or emerald_failed:
        if stale:
            print("STALE: " + ", ".join(stale))
        return 1
    print("CHECK PASSED (SOURCE only)" if args.check
          else "WROTE outputs (SOURCE only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
