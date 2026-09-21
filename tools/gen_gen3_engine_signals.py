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
              "at lua/clients/gen3_frlge_client.lua:3005-3379 is behavior to preserve, not pret proof.",
              reason="RR-specific mutation and restore pairing not pinned"),
    candidate("nature_change", "RR nature-changer special", "src/pokemon.c#L3686-L3706",
              "RR-specific PID identity update; existing client.lua:3399-3557 is only a local behavior "
              "reference. The linked vanilla source is a contrast, NOT evidence for the special.",
              reason="no pinned RR special entry/store/caller context"),
]



# C2-3b: offsets are relative to independently resolved FR/LG function symbols.
# Literal anchors were separately read and disassembled in BOTH admitted ROMs.
BINDINGS = {
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
    if kind == "nature_change":
        hits = find_offsets(rom, (0x02024284).to_bytes(4, "little"))
        return {"status": "UNVERIFIED", "reason":
                f"party-base 02024284 has {len(hits)} literal matches; no unique nature-special PID "
                "write/dispatch identified. CFRU scripting/util/item/party_menu/build_pokemon name search "
                "did not provide an RR special address; a generic PID store is not sufficient attribution."}
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
                    source_url=CFRU + contract["source_path"], replaces=contract["replaces"],
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
              "RR borrowed_party and nature_change remain UNVERIFIED. Poison's replacement is disabled; "
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
