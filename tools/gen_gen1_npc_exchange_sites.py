"""Generate reviewed NPC in-game exchange sites from pinned source, symbols and ROM bytes.

Every used `npctrade` row in the acquisition census is reached from one map script that
stores its trade index (`ld [wWhichTrade], a`) and dispatches `predef DoInGameTradeDialogue`.
The store is the per-source call witness: its PC is unique per source even where two rows
share one dispatch (Cinnabar trade room), and register A carries the index. Delivery runs
through one shared engine sequence in `InGameTrade_DoTrade`: `call RemovePokemon` (party
still intact, wWhichPokemon = outgoing slot, wCurEnemyLevel = its level) and the `call
ClearScreen` reached only after AddPartyMon, InGameTrade_CopyDataToReceivedMon and the
trade-evolution hook have all returned. Both engine PCs, the table records, the `<TRAINER>`
OT string and the dispatch bytes are pinned against the clean ROMs. The table bytes are
canonical under admission: gen1_upr_scan claims no in-game-trade domain, so
RomChangeAudit.finish rejects any admitted ROM that changed them.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
try:
    from gen_gen1_acquisition_sources import TITLES, address, flat, symbols
    from gen_gen1_encounters import parse_pokemon_constants
    from gen_gen1_grant_sites import GUARDS as GRANT_GUARDS, lua, site, word
    from verify_canonical_sources import verify

    from server.gen1_grant_receipt import FRESH, fresh_moves
finally:
    sys.path.pop(0)
    sys.path.pop(0)

OUTPUT = ROOT / "data/games/gen1_rby/npc_exchange_sites.json"
LUA = ROOT / "data/games/gen1_rby/gen1_npc_exchange_sites.lua"
RECORD = 14  # db give, receive, dialog ; dname nick, NAME_LENGTH
NAMES = ["hLoadedROMBank", "wPartyDataStart", "wBoxDataStart", "wPlayerName", "wPlayerID", "wCurMap", "wIsInBattle",
         "wCurrentBoxNum", "wWhichTrade", "wWhichPokemon", "wCurPartySpecies", "wCurEnemyLevel", "wMonDataLocation",
         "wRemoveMonFromBox", "wInGameTradeGiveMonSpecies", "wInGameTradeReceiveMonSpecies", "wInGameTradeMonNick",
         "wTradedEnemyMonOTID"]
TX_START_ASM, TRAINER, TERMINATOR = 0x08, 0x5D, 0x50
TABLE_POLICY = ("pinned: gen1_upr_scan claims no in-game-trade domain (inGameTradesMod is never validated), "
                "so RomChangeAudit.finish rejects any admitted ROM that changed these bytes")
SELECTOR = re.compile(r"\t(?:ld a, (TRADE_FOR_\w+)|xor a ; (TRADE_FOR_\w+))\n\tld \[wWhichTrade\], a\n")
# Source lines whose exact semantics the decoder's predicates depend on.
GUARDS = {
    "engine/events/in_game_trades.asm": [
        "\tld a, [hli]\n\tld [wInGameTradeGiveMonSpecies], a\n\tld a, [hli]\n\tld [wInGameTradeReceiveMonSpecies], a\n"
        "\tld a, [hli]\n\tpush af\n\tld de, wInGameTradeMonNick\n\tld bc, NAME_LENGTH\n\tcall CopyData\n",
        "\tld a, [wInGameTradeGiveMonSpecies]\n\tld b, a\n\tld a, [wCurPartySpecies]\n\tcp b\n\tld a, TRADETEXT_WRONG_MON\n"
        "\tjr nz, .tradeFailed ; jump if the selected mon's species is not the required one\n\tld a, [wWhichPokemon]\n"
        "\tld hl, wPartyMon1Level\n\tld bc, PARTYMON_STRUCT_LENGTH\n\tcall AddNTimes\n\tld a, [hl]\n\tld [wCurEnemyLevel], a\n",
        "\tpop af\n\tld [wCurEnemyLevel], a\n\tpop af\n\tld [wWhichPokemon], a\n\tld a, [wInGameTradeReceiveMonSpecies]\n"
        "\tld [wCurPartySpecies], a\n\txor a\n\tld [wMonDataLocation], a ; not used\n\tld [wRemoveMonFromBox], a\n"
        "\tcall RemovePokemon\n\tld a, $80 ; prevent the player from naming the mon\n\tld [wMonDataLocation], a\n"
        "\tcall AddPartyMon\n\tcall InGameTrade_CopyDataToReceivedMon\n",
        "\tcall ClearScreen\n\tcall InGameTrade_RestoreScreen\n\tfarcall RedrawMapView\n\tand a\n\tld a, TRADETEXT_THANKS\n"
        "\tjr .tradeSucceeded\n.tradeFailed\n\tscf\n.tradeSucceeded\n\tld [wInGameTradeTextPointerTableIndex], a\n\tret\n",
        "\tld de, wTradedPlayerMonOTID\n\tld bc, $2\n\tcall InGameTrade_CopyData\n\tcall Random\n\tld hl, hRandomAdd\n"
        "\tld de, wTradedEnemyMonOTID\n\tjp CopyData\n",
        "InGameTrade_CopyData:\n\tpush hl\n\tpush bc\n\tcall CopyData\n\tpop bc\n\tpop hl\n\tret\n",
        "InGameTrade_CopyDataToReceivedMon:\n\tld hl, wPartyMonNicks\n\tld bc, NAME_LENGTH\n"
        "\tcall InGameTrade_GetReceivedMonPointer\n\tld hl, wInGameTradeMonNick\n\tld bc, NAME_LENGTH\n\tcall CopyData\n"
        "\tld hl, wPartyMonOT\n\tld bc, NAME_LENGTH\n\tcall InGameTrade_GetReceivedMonPointer\n\tld hl, InGameTrade_TrainerString\n"
        "\tld bc, NAME_LENGTH\n\tcall CopyData\n\tld hl, wPartyMon1OTID\n\tld bc, PARTYMON_STRUCT_LENGTH\n"
        "\tcall InGameTrade_GetReceivedMonPointer\n\tld hl, wTradedEnemyMonOTID\n\tld bc, 2\n\tjp CopyData\n",
        "InGameTrade_GetReceivedMonPointer:\n\tld a, [wPartyCount]\n\tdec a\n\tcall AddNTimes\n\tld e, l\n\tld d, h\n\tret\n",
        'InGameTrade_TrainerString:\n\tdname "<TRAINER>", NAME_LENGTH\n'],
    "data/events/trades.asm": [
        "MACRO npctrade\n; give mon, get mon, dialog id, nickname\n\tdb \\1, \\2, \\3\n\tdname \\4, NAME_LENGTH\nENDM\n",
        "\ttable_width 3 + NAME_LENGTH\n"],
    "engine/pokemon/remove_mon.asm": [
        "\tld a, [hl]\n\tdec a\n\tld [hli], a\n\n\tld a, [wWhichPokemon]\n\tld c, a\n\tld b, 0\n\tadd hl, bc\n\tld e, l\n\tld d, h\n"
        "\tinc de\n.shiftMonSpeciesLoop\n\tld a, [de]\n\tinc de\n\tld [hli], a\n\tinc a ; reached terminator?\n",
        ".copyUntilPartyMonOT\n\tld bc, PARTYMON_STRUCT_LENGTH\n\tadd hl, bc ; get address of next slot\n\tld bc, wPartyMonOT\n"
        ".shiftOTs\n\tcall CopyDataUntil ; shift all pokemon data up one slot\n",
        "\tjp CopyDataUntil ; shift all pokemon nicknames up one slot\n"],
    "engine/pokemon/add_mon.asm": [
        "\tld a, [de]\n\tinc a\n\tcp PARTY_LENGTH + 1\n\tret nc ; return if the party is already full\n\tld [de], a\n",
        "\tld a, [wCurPartySpecies]\n\tld [de], a ; write species of new mon in party list\n\tinc de\n\tld a, $ff ; terminator\n\tld [de], a\n",
        "\tld a, [wMonDataLocation]\n\tand a\n\tjr nz, .skipNaming\n"],
    "constants/charmap.asm": ['\tcharmap "@",         $50 ; string terminator\n', '\tcharmap "<TRAINER>", $5d ; "TRAINER"\n'],
    "macros/scripts/text.asm": ["MACRO text_asm\n\tdb TX_START_ASM\nENDM\n"],
}
RB_GUARDS = {
    "engine/events/in_game_trades.asm": ["\tcall InGameTrade_CopyDataToReceivedMon\n\tcallfar InGameTrade_CheckForTradeEvo\n\tcall ClearScreen\n"],
    "engine/events/evolve_trade.asm": [
        "\tld a, [wInGameTradeReceiveMonName]\n\tcp 'G' ; GRAVELER\n\tjr z, .nameMatched\n\t; \"SPECTRE\" (HAUNTER)\n\tcp 'S'\n"
        "\tret nz\n\tld a, [wInGameTradeReceiveMonName + 1]\n\tcp 'P'\n\tret nz\n"],
}
YELLOW_GUARDS = {
    "engine/events/in_game_trades.asm": [
        "\tcall InGameTrade_CopyDataToReceivedMon\n\tcall InGameTrade_CheckForTradeEvo\n\tcall ClearScreen\n",
        "InGameTrade_CheckForTradeEvo:\n\tld a, [wInGameTradeReceiveMonSpecies]\n\tcp KADABRA\n\tjr z, .tradeEvo\n\tcp GRAVELER\n"
        "\tjr z, .tradeEvo\n\tcp MACHOKE\n\tjr z, .tradeEvo\n\tcp HAUNTER\n\tjr z, .tradeEvo\n\tret\n\n.tradeEvo\n\tld a, [wPartyCount]\n"
        "\tdec a\n\tld [wWhichPokemon], a\n\tld a, $1\n\tld [wForceEvolution], a\n\tld a, LINK_STATE_TRADING\n\tld [wLinkState], a\n"
        "\tcallfar TryEvolvingMon\n"],
    "engine/movie/evolution.asm": [".pressedB\n\tld a, [wForceEvolution]\n\tand a\n\tjr nz, .notAllowedToCancel\n"],
    "engine/pokemon/evos_moves.asm": [
        ".checkTradeEvo\n\tld a, [wLinkState]\n\tcp LINK_STATE_TRADING\n\tjp nz, .nextEvoEntry1 ; if not trading, go to the next evolution entry\n"
        "\tld a, [hli] ; level requirement\n\tld b, a\n\tld a, [wLoadedMonLevel]\n\tcp b ; is the mon's level greater than the evolution requirement?\n"
        "\tjp c, Evolution_PartyMonLoop ; if so, go the next mon\n\tjr .doEvolution\n",
        "\tld hl, wLoadedMonHPExp - 1\n\tld de, wLoadedMonStats\n\tld b, $1\n\tcall CalcStats\n",
        "\tld hl, wLoadedMonHP + 1\n\tld a, [hl]\n\tadd c\n\tld [hld], a\n\tld a, [hl]\n\tadc b\n\tld [hl], a\n\tdec hl\n\tpop bc\n"
        "\tcall CopyData\n\tld a, [wCurSpecies]\n\tld [wPokedexNum], a\n\txor a\n\tld [wMonDataLocation], a\n\tcall LearnMoveFromLevelUp\n"
        "\tpop hl\n\tpredef SetPartyMonTypes\n",
        "\tld a, [wLoadedMonSpecies]\n\tld [hl], a\n",
        "\tld a, [wCurEnemyLevel]\n\tcp b ; is the move learnt at the mon's current level?\n\tld a, [hli] ; move ID\n\tjr nz, .learnSetLoop\n",
        ".checkCurrentMovesLoop ; check if the move to learn is already known\n\tld a, [hli]\n\tcp d\n\tjr z, .done ; if already known, jump\n"],
    "engine/pokemon/set_types.asm": [
        "\tld bc, MON_TYPE\n\tadd hl, bc\n\tld a, [wPokedexNum]\n\tld [wCurSpecies], a\n\tpush hl\n\tcall GetMonHeader\n\tpop hl\n"
        "\tld a, [wMonHType1]\n\tld [hli], a\n\tld a, [wMonHType2]\n\tld [hl], a\n\tret\n"],
}
TRADE_EVO = ("KADABRA", "GRAVELER", "MACHOKE", "HAUNTER")


def guard(repo, table, variant):
    for name, guards in table.items():
        text = (repo / name).read_text(encoding="utf-8")
        for value in guards:
            assert value in text, (variant, name, value)


def find_once(rom, start, end, needle):
    hits = [index for index in range(start, end - len(needle) + 1) if rom[index:index + len(needle)] == needle]
    assert len(hits) == 1, (hex(start), needle.hex())
    return hits[0]


def engine(rom, syms, variant, text):
    """The shared InGameTrade_DoTrade delivery sequence, pinned byte for byte."""
    bank, do_trade = syms["InGameTrade_DoTrade"]
    failed = syms["InGameTrade_DoTrade.tradeFailed"]
    assert failed[0] == bank and syms["InGameTrade_DoTrade.tradeSucceeded"] == (bank, failed[1] + 1)
    start, end = flat((bank, do_trade)), flat(failed)
    check = (b"\xfa" + word(syms, "wInGameTradeGiveMonSpecies") + b"\x47\xfa" + word(syms, "wCurPartySpecies") + b"\xb8\x3e\x02\x20")
    check_at = find_once(rom, start, end, check)
    assert check_at + len(check) + 1 + rom[check_at + len(check)] == end, "wrong-species jr does not reach .tradeFailed"
    level = (b"\xfa" + word(syms, "wWhichPokemon") + b"\x21" + word(syms, "wPartyMon1Level") + b"\x01\x2c\x00\xcd" + word(syms, "AddNTimes")
             + b"\x7e\xea" + word(syms, "wCurEnemyLevel"))
    assert rom[check_at + len(check) + 1:check_at + len(check) + 1 + len(level)] == level
    evo = syms["InGameTrade_CheckForTradeEvo"]
    hook = (b"\xcd" + word(syms, "InGameTrade_CheckForTradeEvo") if variant == "yellow"
            else b"\x21" + word(syms, "InGameTrade_CheckForTradeEvo") + bytes((0x06, evo[0], 0xcd)) + word(syms, "Bankswitch"))
    assert (evo[0] == bank) == (variant == "yellow")
    head = (b"\xf1\xea" + word(syms, "wCurEnemyLevel") + b"\xf1\xea" + word(syms, "wWhichPokemon") + b"\xfa"
            + word(syms, "wInGameTradeReceiveMonSpecies") + b"\xea" + word(syms, "wCurPartySpecies") + b"\xaf\xea"
            + word(syms, "wMonDataLocation") + b"\xea" + word(syms, "wRemoveMonFromBox"))
    remove = b"\xcd" + word(syms, "RemovePokemon")
    middle = b"\x3e\x80\xea" + word(syms, "wMonDataLocation") + b"\xcd" + word(syms, "AddPartyMon") + b"\xcd" + word(syms, "InGameTrade_CopyDataToReceivedMon") + hook
    tail = (b"\xcd" + word(syms, "ClearScreen") + b"\xcd" + word(syms, "InGameTrade_RestoreScreen") + bytes((0x06, syms["RedrawMapView"][0], 0x21))
            + word(syms, "RedrawMapView") + b"\xcd" + word(syms, "Bankswitch") + b"\xa7\x3e\x03\x18\x01")
    block = head + remove + middle + tail
    assert rom[end - len(block):end] == block, "delivery block differs"
    assert rom[end:end + 5] == b"\x37\xea" + word(syms, "wInGameTradeTextPointerTableIndex") + b"\xc9"
    remove_at = end - len(block) + len(head)
    return_at = remove_at + len(remove) + len(middle)
    cpu = lambda offset: do_trade + (offset - start)  # noqa: E731
    copy = flat(syms["InGameTrade_CopyDataToReceivedMon"])
    nick, ot = b"\x01\x0b\x00", b"\x01\x2c\x00"
    getter = b"\xcd" + word(syms, "InGameTrade_GetReceivedMonPointer")
    copied = (b"\x21" + word(syms, "wPartyMonNicks") + nick + getter + b"\x21" + word(syms, "wInGameTradeMonNick") + nick + b"\xcd" + word(syms, "CopyData")
              + b"\x21" + word(syms, "wPartyMonOT") + nick + getter + b"\x21" + word(syms, "InGameTrade_TrainerString") + nick + b"\xcd" + word(syms, "CopyData")
              + b"\x21" + word(syms, "wPartyMon1OTID") + ot + getter + b"\x21" + word(syms, "wTradedEnemyMonOTID") + b"\x01\x02\x00\xc3" + word(syms, "CopyData"))
    assert rom[copy:copy + len(copied)] == copied, "InGameTrade_CopyDataToReceivedMon differs"
    pointer = flat(syms["InGameTrade_GetReceivedMonPointer"])
    assert rom[pointer:pointer + 10] == b"\xfa" + word(syms, "wPartyCount") + b"\x3d\xcd" + word(syms, "AddNTimes") + b"\x5d\x54\xc9"
    ot_source = (b"\x11" + word(syms, "wTradedPlayerMonOTID") + b"\x01\x02\x00\xcd" + word(syms, "InGameTrade_CopyData") + b"\xcd" + word(syms, "Random")
                 + b"\x21" + word(syms, "hRandomAdd") + b"\x11" + word(syms, "wTradedEnemyMonOTID") + b"\xc3" + word(syms, "CopyData"))
    ot_at = find_once(rom, flat(syms["InGameTrade_PrepareTradeData"]), flat(syms["InGameTrade_CopyData"]), ot_source)
    trainer = flat(syms["InGameTrade_TrainerString"])
    assert rom[trainer:trainer + 11] == bytes((TRAINER,)) + bytes((TERMINATOR,)) * 10
    return {
        "do_trade": address(syms["InGameTrade_DoTrade"]) | {"symbol": "InGameTrade_DoTrade"},
        "species_level_check": {"rom_offset": check_at, "expected_hex": rom[check_at:check_at + len(check) + 1 + len(level)].hex().upper(),
                                "source": "engine/events/in_game_trades.asm: cp wInGameTradeGiveMonSpecies, else .tradeFailed; wCurEnemyLevel = outgoing party level"},
        "block": {"rom_offset": end - len(block), "expected_hex": block.hex().upper()},
        "remove": site(rom, "InGameTrade_DoTrade", bank, cpu(remove_at), 3) | {"source": "call RemovePokemon: party intact, wWhichPokemon = outgoing slot, wCurEnemyLevel = its level, wCurPartySpecies = receive species"},
        "return": site(rom, "InGameTrade_DoTrade", bank, cpu(return_at), 3) | {"source": "call ClearScreen: reached only after AddPartyMon, InGameTrade_CopyDataToReceivedMon and the trade-evolution hook returned"},
        "copy_received": {"rom_offset": copy, "expected_hex": copied.hex().upper(), "source": "nickname <- table, OT name <- InGameTrade_TrainerString, OT id <- wTradedEnemyMonOTID, all at slot wPartyCount-1"},
        "ot_id_source": {"rom_offset": ot_at, "expected_hex": ot_source.hex().upper(), "source": "InGameTrade_PrepareTradeData: two Random bytes (hRandomAdd, hRandomSub) -> wTradedEnemyMonOTID"},
        "trainer_string": {"rom_offset": trainer, "expected_hex": rom[trainer:trainer + 11].hex().upper(), "symbol": "InGameTrade_TrainerString"},
    }


def selector(repo, rom, syms, row, trade_names, predef_id):
    """The map script's `ld [wWhichTrade], a` store (call witness) and its dispatch bytes."""
    text = (repo / row["source_file"]).read_text(encoding="utf-8")
    matches = [m for m in SELECTOR.finditer(text) if trade_names.index(m[1] or m[2]) == row["trade_index"]]
    assert len(matches) == 1, (row["source_id"], len(matches))
    match = matches[0]
    labels = list(re.finditer(r"^(\w+):(?::)?[ \t]*\n", text[:match.start()], re.M))
    label = labels[-1][1]
    assert text[labels[-1].end():match.start()] == "\ttext_asm\n", (row["source_id"], label)
    bank, cpu = syms[label]
    offset = flat((bank, cpu))
    assert rom[offset] == TX_START_ASM
    load = b"\xaf" if match[2] else bytes((0x3e, row["trade_index"]))
    if match[2]:
        assert row["trade_index"] == 0
    assert rom[offset + 1:offset + 1 + len(load)] == load
    store = offset + 1 + len(load)
    assert rom[store:store + 3] == b"\xea" + word(syms, "wWhichTrade")
    dispatch = store + 3
    if rom[dispatch] == 0x18:  # jr to a shared dispatch tail
        dispatch = dispatch + 2 + rom[dispatch + 1]
    predef = bytes((0x3e, predef_id, 0xcd)) + word(syms, "Predef")
    assert rom[dispatch:dispatch + 5] == predef, (row["source_id"], rom[dispatch:dispatch + 5].hex())
    line = text[:match.end()].count("\n")  # the store line
    return label, line, {
        "call": site(rom, label, bank, cpu + 1 + len(load), 3) | {"register": "a", "source": "ld [wWhichTrade], a: A = trade index; unique per source"},
        "selector": {"rom_offset": offset, "expected_hex": rom[offset:store + 3].hex().upper()},
        "dispatch": {"rom_offset": dispatch, "address": cpu + (dispatch - offset), "expected_hex": predef.hex().upper(), "symbol": "predef DoInGameTradeDialogue"},
    }


def build():
    checked = verify(rom_dir=ROOT)
    if checked["status"] != "pass":
        raise ValueError("canonical exchange sources did not verify")
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    census = json.loads((ROOT / "data/games/gen1_rby/acquisition_sources.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data/games/gen1_rby/upr_layout.json").read_text(encoding="utf-8"))
    codec_data = json.loads((ROOT / "data/games/gen1_rby/party_codec.json").read_text(encoding="utf-8"))
    result = {"schema": "rby-npc-exchange-sites-v1", "titles": {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT / ".cache/pret" / source
        syms = symbols(repo / (target + ".sym"))
        rom = (ROOT / lock["clean_roms"][target]["filename"]).read_bytes()
        pokemon = parse_pokemon_constants(str(repo / "constants/pokemon_constants.asm"))
        species = codec_data["titles"][variant]["species"]
        content = FRESH["titles"][variant]
        guard(repo, GUARDS, variant)
        guard(repo, YELLOW_GUARDS if variant == "yellow" else RB_GUARDS, variant)
        # The received record is AddPartyMon's fresh construction: those lines are pinned by the grant generator.
        guard(repo, {name: GRANT_GUARDS[name] for name in ("engine/pokemon/add_mon.asm", "home/move_mon.asm")}, variant)
        trades_text = (repo / "engine/events/in_game_trades.asm").read_text(encoding="utf-8")
        trade_names = re.findall(r"^\s*const\s+(TRADE_FOR_\w+)", (repo / "constants/script_constants.asm").read_text(encoding="utf-8"), re.M)
        rows = re.findall(r'^\s*npctrade\s+(\w+),\s*(\w+),\s*(\w+),\s*"([^"\n]+)"', (repo / "data/events/trades.asm").read_text(encoding="utf-8"), re.M)
        assert len(rows) == len(trade_names) == 10
        table = flat(syms["TradeMons"])
        assert layout["profiles"][variant]["settings"]["TradeTableOffset"] == table, "UPR layout table root differs from TradeMons"
        predefs = re.findall(r"^\tadd_predef (\w+)", (repo / "data/predef_pointers.asm").read_text(encoding="utf-8"), re.M)
        predef_id = predefs.index("DoInGameTradeDialogue")
        names = flat(syms["MonsterNames"])
        shared = engine(rom, syms, variant, trades_text)
        sites = {}
        for row in census["titles"][variant]["sources"]:
            if row["kind"] != "npc_exchange":
                continue
            index = row["trade_index"]
            give, receive, _dialog, nick = rows[index]
            record = rom[table + RECORD * index:table + RECORD * (index + 1)]
            assert row["record_rom_offset"] == table + RECORD * index and row["trade_constant"] == trade_names[index]
            assert record[0] == pokemon[give] == row["wanted_species_index"] and record[1] == pokemon[receive] == row["received_species_index"]
            assert record[0] != record[1] and record[2] <= 2 and TERMINATOR in record[3:] and record[3] != TERMINATOR
            nickname = record[3:RECORD]
            assert str(record[0]) in species and str(record[1]) in species
            receive_name = rom[names + 10 * (record[1] - 1):names + 10 * record[1]]
            delivered, evolution = record[1], None
            if variant == "yellow":
                if receive in TRADE_EVO:
                    targets = species[str(record[1])]["evolution_targets"]
                    assert len(targets) == 1, (variant, receive, targets)
                    delivered = targets[0]
                    assert species[str(delivered)]["growth_rate"] == species[str(record[1])]["growth_rate"], "codec would refuse the evolved exp"
                    # RenameEvolvedMon keeps a nickname that differs from the pre-evolution species name.
                    assert nickname[:10] != receive_name
                    # LearnMoveFromLevelUp teaches the evolved learnset's exact-level move unless known; WriteMonMoves
                    # for the received species already taught it at every level, so the move set is unchanged.
                    for level in range(1, 101):
                        known = fresh_moves(content, record[1], level)
                        assert all(move in known for learned, move in content["species"][str(delivered)]["learnset"] if learned == level), (receive, level)
                    evolution = {"from": record[1], "to": delivered, "forced": True,
                                 "source": "InGameTrade_CheckForTradeEvo -> TryEvolvingMon with wForceEvolution=1 (B cannot cancel) and LINK_STATE_TRADING",
                                 "record": "species/stats/HP/types follow the evolved species; catch rate byte, experience and moves stay the received species'"}
            else:
                # evolve_trade.asm evolves only a received mon whose NAME starts with 'G' or "SP"; none of the used rows does.
                assert receive_name[0] != 0x86 and receive_name[:2] != b"\x92\x8f", (variant, receive)
            label, line, witnesses = selector(repo, rom, syms, row, trade_names, predef_id)
            sites[row["source_id"]] = {
                "exchange_id": "exchange:" + row["source_id"].removeprefix("npc:"),
                "trade_index": index, "trade_constant": trade_names[index], "map": row["map"], "map_id": row["map_id"],
                "source_file": row["source_file"], "source_line": line, "scope_symbol": label,
                "give_species": record[0], "receive_species": record[1], "delivered_species": delivered,
                "nickname_hex": nickname.hex().upper(), "record_rom_offset": table + RECORD * index, "record_hex": record.hex().upper(),
                **witnesses, **({"trade_evolution": evolution} if evolution else {}),
            }
        assert len(sites) == (7 if variant == "yellow" else 9), (variant, sorted(sites))
        assert {row["index"] for row in census["titles"][variant]["unused_trade_rows"]} == set(range(10)) - {s["trade_index"] for s in sites.values()}
        result["titles"][variant] = {
            "source_commit": lock["sources"][source]["commit"],
            "symbols_sha256": hashlib.sha256((repo / (target + ".sym")).read_bytes()).hexdigest(),
            "clean_sha1": lock["clean_roms"][target]["sha1"],
            "addresses": {name: syms[name][1] for name in NAMES},
            "lengths": {"party": 404, "box": 1122, "name": 11, "player_id": 2, "ot_id": 2, "record": RECORD},
            "out_of_battle_flag": 0,
            "table": {"rom_offset": table, "symbol": "TradeMons", "record_length": RECORD, "policy": TABLE_POLICY},
            "predef_id": predef_id,
            "engine": shared,
            "sites": sites,
            "unused": census["titles"][variant]["unused_trade_rows"],
        }
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    value = build()
    outputs = {OUTPUT: json.dumps(value, indent=2, sort_keys=True) + "\n",
               LUA: "-- Generated by tools/gen_gen1_npc_exchange_sites.py from pinned source/ROMs.\nreturn " + lua(value) + "\n"}
    if args.check:
        stale = [path.name for path, text in outputs.items() if not path.exists() or path.read_text(encoding="utf-8") != text]
        assert not stale, "npc exchange data is stale: " + ", ".join(stale)
    else:
        for path, text in outputs.items():
            path.write_text(text, encoding="utf-8", newline="\n")
    print("OK: npc exchange sites", {name: len(row["sites"]) for name, row in value["titles"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
