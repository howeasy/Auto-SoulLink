"""Generate reviewed scripted-grant delivery sites from pinned source, symbols and ROM bytes.

Every non-starter script grant in the acquisition census reaches the player's party or
current box through one shared helper: `GivePokemon` (home) -> `_GivePokemon`, which calls
`AddPartyMon` (party has room), `SendNewMonToBox` (party full, box has room) or fails at
`.boxFull`. Each script's `call GivePokemon` and its return are pinned per source so a
read-only observer can witness party/box before and after; the call site itself, never
the map, names the source. The Game Corner additionally pins the coin subtraction that
follows a delivered prize. The starter is classified as excluded: it calls `AddPartyMon`
directly and is settled by the engine-signal starter pair.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
try:
    from gen_gen1_acquisition_sources import TITLES, address, flat, symbols
    from gen_gen1_encounters import parse_pokemon_constants
    from verify_canonical_sources import verify
finally:
    sys.path.pop(0)

OUTPUT = ROOT/'data/games/gen1_rby/grant_sites.json'
LUA = ROOT/'data/games/gen1_rby/gen1_grant_sites.lua'
# Fresh-delivery content a grant receipt is checked against: the base-stats record's
# catch rate (+8) and level-1 moves (+15..18), and the EvosMoves learnset WriteMonMoves
# walks. Kept apart from party_codec data so the codec schema does not churn.
FRESH_OUTPUT = ROOT/'data/games/gen1_rby/grant_fresh_content.json'
FRESH_LUA = ROOT/'data/games/gen1_rby/gen1_grant_fresh_content.lua'
BASE_STATS_RECORD = 28
NAMES = ['hLoadedROMBank', 'wPartyDataStart', 'wBoxDataStart', 'wPlayerName', 'wPlayerID', 'wCurMap', 'wIsInBattle',
         'wCurPartySpecies', 'wCurEnemyLevel', 'wMonDataLocation', 'wAddedToParty', 'wCurrentBoxNum',
         'wPlayerCoins', 'wWhichPrize', 'wWhichPrizeWindow', 'wPrize1', 'wPrize1Price']
# `lb bc, SPECIES, LEVEL` immediately before the call: species byte at call-1, level at call-2.
IMMEDIATE = {'eevee': ('EEVEE', 25), 'lapras': ('LAPRAS', 15), 'magikarp_salesman': ('MAGIKARP', 5),
             'yellow_bulbasaur': ('BULBASAUR', 10), 'yellow_charmander': ('CHARMANDER', 10), 'yellow_squirtle': ('SQUIRTLE', 10)}
DOJO = ['HITMONLEE', 'HITMONCHAN']
STARTER_EXCLUSION = ('calls AddPartyMon directly, never GivePokemon; settled by gen1_starter_settlement from the '
                     'engine-signal starter_begin/starter_end pair (see STARTER_SETTLEMENT.md), so it is not a grant site')
# Source lines whose exact semantics the decoder's predicates depend on.
GUARDS = {
    'home/give.asm': [
        "GivePokemon::\n; Give the player monster b at level c.\n\tld a, b\n\tld [wCurPartySpecies], a\n\tld a, c\n"
        "\tld [wCurEnemyLevel], a\n\txor a ; PLAYER_PARTY_DATA\n\tld [wMonDataLocation], a\n\tfarjp _GivePokemon\n"],
    'engine/events/give_pokemon.asm': [
        "_GivePokemon::\n; returns success in carry\n; and whether the mon was added to the party in [wAddedToParty]\n"
        "\tcall EnableAutoTextBoxDrawing\n\txor a\n\tld [wAddedToParty], a\n\tld a, [wPartyCount]\n\tcp PARTY_LENGTH\n"
        "\tjr c, .addToParty\n\tld a, [wBoxCount]\n\tcp MONS_PER_BOX\n\tjr nc, .boxFull\n; add to box\n\txor a\n"
        "\tld [wEnemyBattleStatus3], a\n\tld a, [wCurPartySpecies]\n\tld [wEnemyMonSpecies2], a\n\tcallfar LoadEnemyMonData\n"
        "\tcall SetPokedexOwnedFlag\n\tcallfar SendNewMonToBox\n",
        ".boxFull\n\tld hl, BoxIsFullText\n\tcall PrintText\n\tand a\n\tret\n.addToParty\n\tcall SetPokedexOwnedFlag\n",
        "\tcall AddPartyMon\n\tld a, 1\n\tld [wDoNotWaitForButtonPressAfterDisplayingText], a\n\tld [wAddedToParty], a\n\tscf\n\tret\n"],
    'engine/pokemon/add_mon.asm': [
        "\tld a, [wIsInBattle]\n\tand a ; is this a wild mon caught in battle?\n\tjr nz, .copyEnemyMonData\n\n; Not wild.\n"
        "\tcall Random ; generate random IVs\n\tld b, a\n\tcall Random\n",
        "\tld a, 1\n\tld c, a\n\txor a\n\tld b, a\n\tcall CalcStat      ; calc HP stat (set cur Hp to max HP)\n",
        "\txor a\n\tld [de], a         ; box level\n\tinc de\n\tld [de], a         ; status ailments\n\tinc de\n\tjr .copyMonTypesAndMoves\n",
        "\tld hl, wPlayerName\n\tld bc, NAME_LENGTH\n\tcall CopyData\n",
        "\tld a, [wPlayerID]  ; set trainer ID to player ID\n",
        ".writeEVsLoop              ; set all EVs to 0\n",
        "\tcall AddPartyMon_WriteMovePP\n\tinc de\n\tld a, [wCurEnemyLevel]\n\tld [de], a\n\tinc de\n\tld a, [wIsInBattle]\n\tdec a\n\tjr nz, .calcFreshStats\n",
        ".calcFreshStats\n\tpop hl\n\tld bc, MON_HP_EXP - 1\n\tadd hl, bc\n\tld b, $0\n\tcall CalcStats         ; calculate fresh set of stats\n",
        "AddPartyMon_WriteMovePP:\n\tld b, NUM_MOVES\n.pploop\n\tld a, [hli]     ; read move ID\n\tand a\n\tjr z, .empty\n",
        "\tld a, [wMoveData + MOVE_PP]\n.empty\n\tinc de\n\tld [de], a\n"],
    'engine/battle/core.asm': [
        "LoadEnemyMonData:\n\tld a, [wLinkState]\n\tcp LINK_STATE_BATTLING\n\tjp z, LoadEnemyMonFromParty\n"
        "\tld a, [wEnemyMonSpecies2]\n\tld [wEnemyMonSpecies], a\n\tld [wCurSpecies], a\n\tcall GetMonHeader\n",
        "; random DVs for wild mon\n\tcall BattleRandom\n\tld b, a\n\tcall BattleRandom\n.storeDVs\n\tld hl, wEnemyMonDVs\n"
        "\tld [hli], a\n\tld [hl], b\n\tld de, wEnemyMonLevel\n\tld a, [wCurEnemyLevel]\n\tld [de], a\n\tinc de\n"
        "\tld b, $0\n\tld hl, wEnemyMonHP\n\tpush hl\n\tcall CalcStats\n",
        "; if it's a wild mon and not transformed, init the current HP to max HP and the status to 0\n\tld a, [wEnemyMonMaxHP]\n"
        "\tld [hli], a\n\tld a, [wEnemyMonMaxHP+1]\n\tld [hli], a\n\txor a\n\tinc hl\n\tld [hl], a ; init status to 0\n",
        "\tpredef WriteMonMoves ; get moves based on current level\n.loadMovePPs\n\tld hl, wEnemyMonMoves\n\tld de, wEnemyMonPP - 1\n\tpredef LoadMovePPs\n"],
    'engine/items/item_effects.asm': [
        ".skipMonDataShift\n\tld a, [wEnemyMonLevel]\n\tld [wEnemyMonBoxLevel], a\n\tld hl, wEnemyMon\n\tld de, wBoxMon1\n"
        "\tld bc, wEnemyMonDVs - wEnemyMon\n\tcall CopyData\n\tld hl, wPlayerID\n",
        "\tld hl, wEnemyMonDVs\n\tld a, [hli]\n\tld [de], a\n\tinc de\n\tld a, [hli]\n\tld [de], a\n\tld hl, wEnemyMonPP\n\tld b, NUM_MOVES\n",
        "\tld hl, wPlayerName\n\tld de, wBoxMon1OT\n\tld bc, NAME_LENGTH\n\tcall CopyData\n"],
    'engine/events/prize_menu.asm': [
        "\tcall HandleMenuInput ; menu choice handler\n\tbit B_PAD_B, a\n\tjr nz, .noChoice\n\tld a, [wCurrentMenuItem]\n"
        "\tcp 3 ; \"NO,THANKS\" choice\n\tjr z, .noChoice\n\tcall HandlePrizeChoice\n",
        "\tcall YesNoChoice\n\tld a, [wCurrentMenuItem] ; yes/no answer (Y=0, N=1)\n\tand a\n\tjr nz, .printOhFineThen\n"
        "\tcall LoadCoinsToSubtract\n\tcall HasEnoughCoins\n\tjr c, .notEnoughCoins\n\tld a, [wWhichPrizeWindow]\n"
        "\tcp 2 ; is prize a TM?\n\tjr nz, .giveMon\n\tld a, [wNamedObjectIndex]\n\tld b, a\n\tld a, 1\n\tld c, a\n\tcall GiveItem\n"
        "\tjr nc, .bagFull\n\tjr .subtractCoins\n.giveMon\n\tld a, [wNamedObjectIndex]\n\tld [wCurPartySpecies], a\n\tpush af\n"
        "\tcall GetPrizeMonLevel\n\tld c, a\n\tpop af\n\tld b, a\n\tcall GivePokemon\n",
        "; If the mon couldn't be given to the player (because both the party and box\n; were full), return without subtracting coins.\n"
        "\tret nc\n\n.subtractCoins\n\tcall LoadCoinsToSubtract\n\tld hl, hCoins + 1\n\tld de, wPlayerCoins + 1\n"
        "\tld c, $02 ; how many bytes\n\tpredef SubBCDPredef\n\tjp PrintPrizePrice\n",
        "LoadCoinsToSubtract:\n\tld a, [wWhichPrize]\n\tadd a\n\tld d, 0\n\tld e, a\n\tld hl, wPrize1Price\n\tadd hl, de ; get selected prize's price\n",
        "GetPrizeMonLevel:\n\tld a, [wCurPartySpecies]\n\tld b, a\n\tld hl, PrizeMonLevelDictionary\n.loop\n\tld a, [hli]\n\tcp b\n"
        "\tjr z, .matchFound\n\tinc hl\n\tjr .loop\n.matchFound\n\tld a, [hl]\n\tld [wCurEnemyLevel], a\n\tret\n"],
    'engine/events/cinnabar_lab.asm': [
        "\tcp DOME_FOSSIL\n\tjr z, .choseDomeFossil\n\tcp HELIX_FOSSIL\n\tjr z, .choseHelixFossil\n\tld b, AERODACTYL\n"
        "\tjr .fossilSelected\n.choseHelixFossil\n\tld b, OMANYTE\n\tjr .fossilSelected\n.choseDomeFossil\n\tld b, KABUTO\n"
        ".fossilSelected\n\tld [wFossilItem], a\n\tld a, b\n\tld [wFossilMon], a\n"],
    'home/move_mon.asm': [
        "\tld a, d\n\tand a\n\tjr z, .statExpDone  ; consider stat exp?\n",
        "\tadd b      ; HP IV: LSB of the other 4 IVs\n",
        "\tld a, $64\n\tldh [hDivisor], a\n",
        "; non-HP: (((Base + IV) * 2 + ceil(Sqrt(stat exp)) / 4) * Level) / 100 + 5\n",
        "; HP: (((Base + IV) * 2 + ceil(Sqrt(stat exp)) / 4) * Level) / 100 + Level + 10\n"],
    'home/pokemon.asm': [".done\n\tld a, [wCurSpecies]\n\tld [wMonHIndex], a\n"],
    'home/money.asm': [
        "HasEnoughCoins::\n; Check if the player has at least as many\n; coins as the 2-byte BCD value at hCoins.\n"
        "\tld de, wPlayerCoins\n\tld hl, hCoins\n\tld c, 2\n\tjp StringCmp\n"],
    'engine/math/bcd.asm': [
        "SubBCD::\n\tand a\n\tld b, c\n.sub\n\tld a, [de]\n\tsbc [hl]\n\tdaa\n\tld [de], a\n\tdec de\n\tdec hl\n\tdec c\n\tjr nz, .sub\n"],
    'ram/wram.asm': ["; 0 = not added\n; 1 = added\nwAddedToParty::", "wPlayerCoins:: dw ; BCD\n"],
}


def lua(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, dict):
        return '{'+','.join('['+json.dumps(k)+']='+lua(v) for k, v in sorted(value.items()))+'}'
    if isinstance(value, list):
        return '{'+','.join(lua(v) for v in value)+'}'
    if isinstance(value, str):
        return json.dumps(value)
    if type(value) is int:
        return str(value)
    raise TypeError(value)


def site(rom, label, bank, cpu, length):
    value = address((bank, cpu))
    value.update(symbol=label, expected_hex=rom[value['rom_offset']:value['rom_offset']+length].hex().upper())
    return value


def word(syms, name, delta=0):
    return (syms[name][1]+delta).to_bytes(2, 'little')


def static_record(statics, species_offset, level_offset):
    """The one approved-UPR static record that may rewrite this species byte; its level byte is never a claim."""
    hits = [row for row in statics if species_offset in row['Species']]
    if len(hits) != 1 or hits[0]['ghost'] or hits[0]['Level'] != [level_offset]:
        raise ValueError(f'UPR static record differs at {species_offset:#x}: {hits}')
    return hits[0]


def fresh_content(rom, syms, variant, catch_overrides, texts):
    """Per internal species: header catch rate, header level-1 moves, ascending learnset."""
    sys.path.insert(0, str(ROOT))
    try:
        from server.adapters.gen1_rom_scan import scan_evos_moves, scan_pokedex_order
    finally:
        sys.path.pop(0)
    # The synthesis emulates this routine; pin the lines its semantics come from.
    evos = (ROOT/'.cache/pret'/('pokeyellow' if variant == 'yellow' else 'pokered')/'engine/pokemon/evos_moves.asm').read_text(encoding='utf-8')
    for guard in ("\tld a, [wCurEnemyLevel]\n\tcp b\n\tjp c, .done       ; mon level < move level (assumption: learnset is sorted by level)\n",
                  ".alreadyKnowsCheckLoop\n\tld a, [de]\n\tinc de\n\tcp [hl]\n\tjr z, .nextMove\n",
                  ".findEmptySlotLoop\n\tld a, [de]\n\tand a\n\tjr z, .writeMoveToSlot2\n",
                  "\tcall WriteMonMoves_ShiftMoveData ; shift all moves one up (deleting move 1)\n",
                  "WriteMonMoves_ShiftMoveData:\n\tld c, NUM_MOVES - 1\n.loop\n\tinc de\n\tld a, [de]\n\tld [hli], a\n\tdec c\n\tjr nz, .loop\n\tret\n"):
        assert guard in evos, (variant, guard)
    assert "\txor a\n\tld [wLearningMovesFromDayCare], a\n\tpredef WriteMonMoves\n" in texts['engine/pokemon/add_mon.asm']
    order = scan_pokedex_order(rom)
    learnsets = scan_evos_moves(rom)
    base = flat(syms['BaseStats'])
    mew = flat(syms['MewBaseStats']) if 'MewBaseStats' in syms else None
    species = {}
    for internal, dex in order.items():
        if not dex:
            continue
        offset = mew if (dex == 151 and mew is not None) else base+(dex-1)*BASE_STATS_RECORD
        record = rom[offset:offset+BASE_STATS_RECORD]
        assert len(record) == BASE_STATS_RECORD and record[0] == dex, (variant, internal, dex)
        moves = [list(pair) for pair in learnsets[internal]['moves']]
        levels = [level for level, _ in moves]
        assert all(1 <= level <= 100 for level in levels), (variant, internal, moves)
        assert all(1 <= move <= 165 for _, move in moves) and all(0 <= move <= 165 for move in record[15:19]), (variant, internal)
        assert record[15] != 0, (variant, internal, 'a species always has one level-1 move')
        # WriteMonMoves assumes ascending levels and stops at the first level above the
        # mon's. Some pinned learnsets are not sorted (Yellow internal 117: 46 before 45);
        # the engine then never teaches the later entry. Record the fact; emulate, do not repair.
        species[str(internal)] = {'dex': dex, 'catch_rate': record[8], 'base_moves': list(record[15:19]), 'learnset': moves,
                                  'sorted': levels == sorted(levels)}
    assert len(species) == 151
    return {'species': species, 'catch_rate_overrides': dict(catch_overrides),
            'synthesis': 'header level-1 moves, then WriteMonMoves: for each learnset (level, move) with level <= mon level, skip known, '
                         'fill the first empty slot, else drop slot 0 and append; PP = max PP, no PP Ups; catch = overrides or header'}


def build():
    checked = verify(rom_dir=ROOT)
    if checked['status'] != 'pass':
        raise ValueError('canonical grant sources did not verify')
    lock = json.loads((ROOT/'data/pret_sources.lock.json').read_text())
    census = json.loads((ROOT/'data/games/gen1_rby/acquisition_sources.json').read_text(encoding='utf-8'))
    layout = json.loads((ROOT/'data/games/gen1_rby/upr_layout.json').read_text(encoding='utf-8'))
    result = {'schema': 'rby-grant-sites-v1', 'titles': {}}
    fresh = {'schema': 'rby-grant-fresh-content-v1', 'titles': {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT/'.cache/pret'/source
        syms = symbols(repo/(target+'.sym'))
        rom = (ROOT/lock['clean_roms'][target]['filename']).read_bytes()
        statics = layout['profiles'][variant]['statics']
        pokemon = parse_pokemon_constants(str(repo/'constants/pokemon_constants.asm'))
        texts = {}
        for name, guards in GUARDS.items():
            texts[name] = (repo/name).read_text(encoding='utf-8')
            for guard in guards:
                assert guard in texts[name], (variant, name, guard)
        assert texts['engine/events/give_pokemon.asm'].count('call AddPartyMon') == 1
        # Shared helper bytes: GivePokemon (home) and _GivePokemon's three exits.
        give = flat(syms['GivePokemon'])
        far = syms['_GivePokemon']
        # 3x (ld a,r ; ld [nn],a) = 12 bytes, then farjp = ld b,n ; ld hl,nn ; jp nn = 8 bytes.
        assert rom[give:give+20] == (b'\x78\xea'+word(syms, 'wCurPartySpecies')+b'\x79\xea'+word(syms, 'wCurEnemyLevel')+b'\xaf\xea'
                                     + word(syms, 'wMonDataLocation')+bytes((0x06, far[0], 0x21))+word(syms, '_GivePokemon')+b'\xc3'+word(syms, 'Bankswitch'))
        entry = flat(far)
        assert rom[entry+3:entry+13] == b'\xaf\xea'+word(syms, 'wAddedToParty')+b'\xfa'+word(syms, 'wPartyDataStart')+b'\xfe\x06\x38'
        assert rom[entry+14:entry+20] == b'\xfa'+word(syms, 'wBoxDataStart')+b'\xfe\x14\x30'
        assert syms['SendNewMonToBox'][0] == 3 and rom[entry+21:entry+51].count(b'\x21'+word(syms, 'SendNewMonToBox')+b'\x06\x03\xcd'+word(syms, 'Bankswitch')) == 1
        add = flat(syms['_GivePokemon.addToParty'])
        tail = b'\xcd'+word(syms, 'AddPartyMon')+b'\x3e\x01\xea'+word(syms, 'wDoNotWaitForButtonPressAfterDisplayingText')+b'\xea'+word(syms, 'wAddedToParty')+b'\x37\xc9'
        # Yellow prints UnknownTerminator_f6794 between SetPokedexOwnedFlag and AddPartyMon
        # (ld hl,nn ; call PrintText = 6 bytes); Red/Blue call AddPartyMon directly.
        party_tail = rom[add:add+32].find(tail)
        assert party_tail == (9 if variant == 'yellow' else 3) and rom[add:add+3] == b'\xcd'+word(syms, 'SetPokedexOwnedFlag') and syms['AddPartyMon'][0] == 0
        if variant == 'yellow':
            assert rom[add+3] == 0x21 and rom[add+6:add+9] == b'\xcd'+word(syms, 'PrintText')
            assert '.addToParty\n\tcall SetPokedexOwnedFlag\n\tld hl, UnknownTerminator_f6794\n\tcall PrintText\n\tcall AddPartyMon\n' in texts['engine/events/give_pokemon.asm']
        full = flat(syms['_GivePokemon.boxFull'])
        assert rom[full:full+8] == b'\x21'+word(syms, 'BoxIsFullText')+b'\xcd'+word(syms, 'PrintText')+b'\xa7\xc9'
        catch_overrides = {}
        if variant == 'yellow':
            override = 'cp KADABRA\n\tjr nz, .notKadabra\n\tld a, TWISTEDSPOON_GSC\n'
            assert override in texts['engine/pokemon/add_mon.asm'] and override in texts['engine/items/item_effects.asm']
            values = re.findall(r'^DEF TWISTEDSPOON_GSC EQU \$([0-9a-fA-F]+)$', (repo/'constants/item_constants.asm').read_text(encoding='utf-8'), re.M)
            assert len(values) == 1
            catch_overrides[str(pokemon['KADABRA'])] = int(values[0], 16)
        assert syms['wPartyDataEnd'][1]-syms['wPartyDataStart'][1] == 404 and syms['wBoxDataEnd'][1]-syms['wBoxDataStart'][1] == 1122
        assert syms['wPartyCount'] == syms['wPartyDataStart'] and syms['wBoxCount'] == syms['wBoxDataStart']
        assert syms['wPrize2'][1] == syms['wPrize1'][1]+1 and syms['wPrize3'][1] == syms['wPrize1'][1]+2
        assert syms['wPrize2Price'][1] == syms['wPrize1Price'][1]+2 and syms['wPrize3Price'][1] == syms['wPrize1Price'][1]+4
        sites, excluded = {}, {}
        for row in census['titles'][variant]['sources']:
            if row['kind'] != 'scripted_grant':
                continue
            group, call = row['group'], row['call']
            off, bank, cpu = call['rom_offset'], call['bank'], call['address']
            if group == 'starter':
                assert row['target_symbol'] == 'AddPartyMon' and rom[off:off+3] == b'\xcd'+word(syms, 'AddPartyMon')
                excluded[row['source_id']] = {'reason': STARTER_EXCLUSION, 'call': call, 'scope_symbol': row['scope_symbol'], 'map_id': row['map_id']}
                continue
            assert row['target_symbol'] == 'GivePokemon' and rom[off:off+3] == b'\xcd'+word(syms, 'GivePokemon') and row['return_address'] == cpu+3
            text = (repo/row['source_file']).read_text(encoding='utf-8')
            entry = {'group': group, 'yellow_only': row['yellow_only'], 'map': row['map'], 'map_id': row['map_id'],
                     'source_file': row['source_file'], 'source_line': row['source_line'], 'scope_symbol': row['scope_symbol'],
                     'call': site(rom, row['scope_symbol'], bank, cpu, 3), 'return': site(rom, row['scope_symbol'], bank, cpu+3, 8)}
            if group in IMMEDIATE:
                name, level = IMMEDIATE[group]
                assert rom[off-3:off] == bytes((0x01, level, pokemon[name])) and f'\tlb bc, {name}, {level}\n\tcall GivePokemon\n' in text
                prelude, species_offsets, clean, level_offset, levels = off-3, [off-1], [pokemon[name]], off-2, [level]
                species_source = 'immediate: lb bc, SPECIES, LEVEL'
            elif group == 'dojo_choice':
                name = DOJO[int(row['source_id'].rsplit(':', 1)[1])]
                assert rom[off-6:off] == b'\xfa'+word(syms, 'wCurPartySpecies')+b'\x47\x0e\x1e' and row['scope_symbol'].endswith('.GetMon')
                get_mon = flat(syms[row['scope_symbol']])
                assert rom[get_mon:get_mon+5] == bytes((0x3e, pokemon[name], 0xcd))+word(syms, 'DisplayPokedex')
                assert f'.GetMon\n\tld a, {name}\n\tcall DisplayPokedex\n' in text
                assert text.count('\tld a, [wCurPartySpecies]\n\tld b, a\n\tld c, 30\n\tcall GivePokemon\n') == 2
                prelude, species_offsets, clean, level_offset, levels = off-6, [get_mon+1], [pokemon[name]], off-1, [30]
                species_source = 'immediate: ld a, SPECIES before DisplayPokedex, read back from wCurPartySpecies'
            elif group == 'fossil_revival':
                assert rom[off-6:off] == b'\xfa'+word(syms, 'wFossilMon')+b'\x47\x0e\x1e'
                assert '\tld a, [wFossilMon]\n\tld b, a\n\tld c, 30\n\tcall GivePokemon\n' in text
                helix, dome = flat(syms['GiveFossilToCinnabarLab.choseHelixFossil']), flat(syms['GiveFossilToCinnabarLab.choseDomeFossil'])
                assert dome == helix+4 and rom[helix-4] == rom[helix] == rom[dome] == 0x06 and rom[helix-2] == rom[helix+2] == 0x18
                clean = [pokemon['AERODACTYL'], pokemon['OMANYTE'], pokemon['KABUTO']]
                species_offsets = [helix-3, helix+1, dome+1]
                assert [rom[o] for o in species_offsets] == clean
                prelude, level_offset, levels = off-6, off-1, [30]
                species_source = 'wFossilMon, written from ld b, AERODACTYL/OMANYTE/KABUTO in GiveFossilToCinnabarLab'
            elif group == 'game_corner_purchase':
                assert cpu-13 == syms['HandlePrizeChoice.giveMon'][1]
                assert rom[off-13:off] == (b'\xfa'+word(syms, 'wNamedObjectIndex')+b'\xea'+word(syms, 'wCurPartySpecies')+b'\xf5\xcd'
                                           + word(syms, 'GetPrizeMonLevel')+b'\x4f\xf1\x47')
                species_offsets, clean = [], []
                for table in ('PrizeMenuMon1Entries', 'PrizeMenuMon2Entries'):
                    base = flat(syms[table])
                    assert rom[base+3] == 0x50
                    species_offsets += [base, base+1, base+2]
                    clean += list(rom[base:base+3])
                assert rom[flat(syms['PrizeMenuTMsEntries'])+3] == 0x50
                dictionary = flat(syms['PrizeMonLevelDictionary'])
                pairs = rom[dictionary:dictionary+12]
                assert list(pairs[0::2]) == clean, 'prize dictionary keys differ from the prize tables'
                levels = list(pairs[1::2])
                get_level = flat(syms['GetPrizeMonLevel'])
                assert rom[get_level:get_level+7] == b'\xfa'+word(syms, 'wCurPartySpecies')+b'\x47\x21'+word(syms, 'PrizeMonLevelDictionary')
                sub = syms['HandlePrizeChoice.subtractCoins']
                soff = flat(sub)
                # predef SubBCDPredef = ld a,ID ; call Predef (the ID byte at +12 is source-owned, not pinned here).
                assert rom[soff:soff+12] == (b'\xcd'+word(syms, 'LoadCoinsToSubtract')+b'\x21'+word(syms, 'hCoins', 1)+b'\x11'
                                             + word(syms, 'wPlayerCoins', 1)+b'\x0e\x02\x3e')
                assert rom[soff+13:soff+19] == b'\xcd'+word(syms, 'Predef')+b'\xc3'+word(syms, 'PrintPrizePrice')
                # LoadCoinsToSubtract indexes wPrize1Price by 2*wWhichPrize; HasEnoughCoins compares the 2 BCD bytes big-endian.
                costs = {name: rom[flat(syms[name]):flat(syms[name])+6].hex().upper() for name in ('PrizeMenuMon1Cost', 'PrizeMenuMon2Cost')}
                for hexes in costs.values():
                    assert all(int(ch, 16) <= 9 for ch in hexes)
                # +16 is the `jp PrintPrizePrice` executed only after SubBCD returned: coins are already paid there.
                entry['purchase'] = {'paid': site(rom, 'HandlePrizeChoice.subtractCoins+16', bank, sub[1]+16, 3), 'mon_windows': [0, 1],
                                     'tm_window': 2, 'clean_costs_bcd': costs,
                                     'note': 'a delivered prize is paid only after GivePokemon returned with carry set; '
                                             'cancel, NO THANKS, not enough coins, the TM window and .boxFull never reach the call'}
                prelude, level_offset = off-13, None
                species_source = 'prize table via wPrize1..3 -> wNamedObjectIndex -> wCurPartySpecies'
            else:
                raise ValueError(f'unclassified grant group: {variant}/{group}')
            # Approved UPR may rewrite exactly these species bytes; the paired level byte is never a UPR claim.
            if group == 'game_corner_purchase':
                level_offsets = [dictionary+1+2*index for index in range(6)]
                for index, species_offset in enumerate(species_offsets):
                    assert static_record(statics, species_offset, level_offsets[index])['Species'] == [species_offset, dictionary+2*index]
                level_source = 'PrizeMonLevelDictionary value for the first key equal to wCurPartySpecies'
            else:
                for species_offset in species_offsets:
                    static_record(statics, species_offset, level_offset)
                level_offsets = [level_offset]
                level_source = 'immediate operand'
            entry['prelude'] = {'rom_offset': prelude, 'expected_hex': rom[prelude:off].hex().upper()}
            entry['species'] = {'source': species_source, 'rom_offsets': species_offsets, 'clean': clean,
                                'policy': 'read from cartridge memory (wCurPartySpecies) and the delivered record; approved staticPokemonMod may rewrite these bytes'}
            entry['level'] = {'source': level_source, 'rom_offsets': level_offsets, 'values': levels,
                              'policy': 'pinned: gen1_upr_scan never claims these bytes, so RomChangeAudit.finish rejects any admitted ROM that changed them'}
            sites[row['source_id']] = entry
        expected = 10 if variant == 'yellow' else 7
        assert len(sites) == expected and set(excluded) == {'grant:starter:0'}, (variant, sorted(sites))
        assert all(row['yellow_only'] == (variant == 'yellow' and row['group'].startswith('yellow_')) for row in sites.values())
        result['titles'][variant] = {
            'source_commit': lock['sources'][source]['commit'],
            'symbols_sha256': hashlib.sha256((repo/(target+'.sym')).read_bytes()).hexdigest(),
            'clean_sha1': lock['clean_roms'][target]['sha1'],
            'addresses': {name: syms[name][1] for name in NAMES},
            'lengths': {'party': 404, 'box': 1122, 'name': 11, 'player_id': 2, 'coins': 2, 'prizes': 3, 'prices': 6},
            'give_pokemon': {'entry': address(syms['GivePokemon']) | {'symbol': 'GivePokemon'}, 'far_entry': address(far) | {'symbol': '_GivePokemon'},
                             'party_call': address(syms['_GivePokemon.addToParty']) | {'symbol': '_GivePokemon.addToParty', 'add_party_mon_offset': party_tail},
                             'box_full': address(syms['_GivePokemon.boxFull']) | {'symbol': '_GivePokemon.boxFull'}},
            'catch_rate_overrides': catch_overrides, 'out_of_battle_flag': 0,
            'sites': sites, 'excluded': excluded}
        fresh['titles'][variant] = {'source_commit': lock['sources'][source]['commit'], 'clean_sha1': lock['clean_roms'][target]['sha1'],
                                    **fresh_content(rom, syms, variant, catch_overrides, texts)}
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    fresh['sha256'] = hashlib.sha256(json.dumps(fresh, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result, fresh


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    value, fresh = build()
    outputs = {OUTPUT: json.dumps(value, indent=2, sort_keys=True)+'\n',
               LUA: '-- Generated by tools/gen_gen1_grant_sites.py from pinned source/ROMs.\nreturn '+lua(value)+'\n',
               FRESH_OUTPUT: json.dumps(fresh, indent=2, sort_keys=True)+'\n',
               FRESH_LUA: '-- Generated by tools/gen_gen1_grant_sites.py from pinned source/ROMs.\nreturn '+lua(fresh)+'\n'}
    if args.check:
        stale = [path.name for path, text in outputs.items() if not path.exists() or path.read_text(encoding='utf-8') != text]
        assert not stale, 'grant data is stale: '+', '.join(stale)
    else:
        for path, text in outputs.items():
            path.write_text(text, encoding='utf-8', newline='\n')
    print('OK: grant delivery sites', {name: len(row['sites']) for name, row in value['titles'].items()},
          'fresh content species', {name: len(row['species']) for name, row in fresh['titles'].items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
