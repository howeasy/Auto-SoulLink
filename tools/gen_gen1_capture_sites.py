"""Generate reviewed successful-capture delivery sites from pinned source, symbols and ROM bytes.

A thrown ball reaches exactly one of two delivery calls inside ItemUseBall only after
the capture succeeded: `call AddPartyMon` (party has room) or `call SendNewMonToBox`
(party full, current box has room). Trainer, ghost, old-man/Pikachu tutorial and
failed/missed throws never execute either call. The call and its return are pinned
here so a read-only observer can witness the party/box before and after delivery.
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
    from gen_gen1_acquisition_sources import TITLES, address, flat, instruction_site, source_scopes, symbols
    from gen_gen1_engine_signals import lua
    from verify_canonical_sources import verify
    from gen_gen1_encounters import parse_pokemon_constants
finally:
    sys.path.pop(0)

OUTPUT = ROOT/'data/games/gen1_rby/capture_sites.json'
LUA = ROOT/'data/games/gen1_rby/gen1_capture_sites.lua'
NAMES = ['hLoadedROMBank', 'wPartyDataStart', 'wBoxDataStart', 'wEnemyMon', 'wPlayerName', 'wPlayerID', 'wCurMap',
         'wIsInBattle', 'wBattleType', 'wCurPartySpecies', 'wCapturedMonSpecies', 'wCurEnemyLevel',
         'wMonDataLocation', 'wCurrentBoxNum']
# Struct offsets the decoder relies on, asserted against every title's symbols.
ENEMY = {'wEnemyMonSpecies': 0, 'wEnemyMonHP': 1, 'wEnemyMonBoxLevel': 3, 'wEnemyMonStatus': 4, 'wEnemyMonType1': 5,
         'wEnemyMonCatchRate': 7, 'wEnemyMonMoves': 8, 'wEnemyMonDVs': 12, 'wEnemyMonLevel': 14, 'wEnemyMonMaxHP': 15,
         'wEnemyMonPP': 25, 'wEnemyMonSpecies2': -13}
PARTY = {'wPartyCount': 0, 'wPartySpecies': 1, 'wPartyMons': 8, 'wPartyMonOT': 272, 'wPartyMonNicks': 338, 'wPartyDataEnd': 404}
BOX = {'wBoxCount': 0, 'wBoxSpecies': 1, 'wBoxMons': 22, 'wBoxMon1': 22, 'wBoxMon1CatchRate': 29, 'wBoxMonOT': 682,
       'wBoxMon1OT': 682, 'wBoxMonNicks': 902, 'wBoxMon1Nick': 902, 'wBoxDataEnd': 1122}
# Source lines whose exact semantics the decoder's predicates depend on.
ITEM_GUARDS = [
    "; Balls can't be used out of battle.\n\tld a, [wIsInBattle]\n\tand a\n\tjp z, ItemUseNotTime\n\n"
    "; Balls can't catch trainers' Pokémon.\n\tdec a\n\tjp nz, ThrowBallAtTrainerMon\n",
    "\tld a, [wBoxCount] ; is box full?\n\tcp MONS_PER_BOX\n\tjp z, BoxFullCannotThrowBall\n\n.canUseBall\n\txor a\n\tld [wCapturedMonSpecies], a\n",
    "\tcallfar IsGhostBattle\n\tld b, $10 ; can't be caught value\n\tjp z, .setAnimData\n",
    "\tld a, [wEnemyMonSpecies2]\n\tcp RESTLESS_SOUL\n\tld b, $10 ; can't be caught value\n\tjp z, .setAnimData\n",
    "\tld a, [wEnemyMonSpecies]\n\tld [wCapturedMonSpecies], a\n\tld [wCurPartySpecies], a\n\tld [wPokedexNum], a\n\tld a, [wBattleType]\n",
    "\tld a, [wPartyCount]\n\tcp PARTY_LENGTH ; is party full?\n\tjr z, .sendToBox\n\txor a ; PLAYER_PARTY_DATA\n\tld [wMonDataLocation], a\n",
    "\tcall AddPartyMon\n\tjr .done\n\n.sendToBox\n\tcall ClearSprites\n\tcall SendNewMonToBox\n\tld hl, ItemUseBallText07\n",
    ".skipMonDataShift\n\tld a, [wEnemyMonLevel]\n\tld [wEnemyMonBoxLevel], a\n\tld hl, wEnemyMon\n\tld de, wBoxMon1\n"
    "\tld bc, wEnemyMonDVs - wEnemyMon\n\tcall CopyData\n\tld hl, wPlayerID\n",
    "\tld hl, wEnemyMonDVs\n\tld a, [hli]\n\tld [de], a\n\tinc de\n\tld a, [hli]\n\tld [de], a\n\tld hl, wEnemyMonPP\n\tld b, NUM_MOVES\n",
    "\tld hl, wPlayerName\n\tld de, wBoxMon1OT\n\tld bc, NAME_LENGTH\n\tcall CopyData\n",
]
ADD_MON_GUARDS = [
    "\tcp PARTY_LENGTH + 1\n\tret nc ; return if the party is already full\n",
    "\tld hl, wPlayerName\n\tld bc, NAME_LENGTH\n\tcall CopyData\n",
    "\tld a, [wIsInBattle]\n\tand a ; is this a wild mon caught in battle?\n\tjr nz, .copyEnemyMonData\n",
    ".copyEnemyMonData\n\tld bc, MON_DVS\n\tadd hl, bc\n\tld a, [wEnemyMonDVs] ; copy IVs from cur enemy mon\n",
    "\tld a, [wEnemyMonHP]    ; copy HP from cur enemy mon\n",
    "\txor a\n\tld [de], a                ; box level\n\tinc de\n\tld a, [wEnemyMonStatus]   ; copy status ailments from cur enemy mon\n",
    "\tld a, [wPlayerID]  ; set trainer ID to player ID\n",
    ".writeEVsLoop              ; set all EVs to 0\n",
    "\tld a, [wIsInBattle]\n\tdec a\n\tjr nz, .calcFreshStats\n\tld hl, wEnemyMonMaxHP\n\tld bc, NUM_STATS * 2\n\tcall CopyData          ; copy stats of cur enemy mon\n",
]
OLD_MAN = {'pokered': "\tld a, [wBattleType]\n\tdec a ; is this the old man battle?\n\tjr z, .oldManCaughtMon",
           'pokeyellow': "\tcp BATTLE_TYPE_OLD_MAN ; is this the old man battle?\n\tjp z, .oldManCaughtMon ; if so, don't give the player the caught Pokémon\n"
                         "\tcp BATTLE_TYPE_PIKACHU\n\tjr z, .oldManCaughtMon"}
EXCLUDED = {'pokered': ['BATTLE_TYPE_OLD_MAN'], 'pokeyellow': ['BATTLE_TYPE_OLD_MAN', 'BATTLE_TYPE_PIKACHU']}


def battle_types(repo):
    text = (repo/'constants/battle_constants.asm').read_text(encoding='utf-8')
    block = text.split('; battle type constants (wBattleType values)\n\tconst_def\n', 1)[1].split('\n\n', 1)[0]
    return {name: index for index, name in enumerate(re.findall(r'^\tconst (BATTLE_TYPE_\w+)', block, re.M))}


def assigned_battle_types(repo):
    found = set()
    for file in [*(repo/'scripts').glob('*.asm'), *(repo/'engine').rglob('*.asm')]:
        found.update(re.findall(r'^\tld a, (BATTLE_TYPE_\w+)$', file.read_text(encoding='utf-8'), re.M))
    return found


def call_site(lines, scopes, syms, rom, target):
    def enclosing(n):
        return [name for k, name in scopes if k < n][-1]
    hits = [n for n, line in enumerate(lines) if line.strip() == 'call '+target and enclosing(n).startswith('ItemUseBall')]
    if len(hits) != 1:
        raise ValueError(f'expected one ItemUseBall call to {target}: {hits}')
    operand = syms[target][1]
    return instruction_site(lines, scopes, syms, rom, hits[0], bytes((0xCD, operand & 255, operand >> 8)))


def site(rom, label, bank, cpu, length):
    value = address((bank, cpu))
    value.update(symbol=label, expected_hex=rom[value['rom_offset']:value['rom_offset']+length].hex().upper())
    return value


def operand(syms, target):
    return syms[target][1].to_bytes(2, 'little')


def build():
    checked = verify(rom_dir=ROOT)
    if checked['status'] != 'pass':
        raise ValueError('canonical capture sources did not verify')
    lock = json.loads((ROOT/'data/pret_sources.lock.json').read_text())
    result = {'schema': 'rby-capture-sites-v1', 'titles': {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT/'.cache/pret'/source
        syms = symbols(repo/(target+'.sym'))
        rom = (ROOT/lock['clean_roms'][target]['filename']).read_bytes()
        items = (repo/'engine/items/item_effects.asm').read_text(encoding='utf-8')
        add_mon = (repo/'engine/pokemon/add_mon.asm').read_text(encoding='utf-8')
        battle = (repo/'engine/battle/core.asm').read_text(encoding='utf-8')
        wram = (repo/'ram/wram.asm').read_text(encoding='utf-8')
        for guard in ITEM_GUARDS:
            assert guard in items, (variant, guard)
        for guard in ADD_MON_GUARDS:
            assert guard in add_mon, (variant, guard)
        assert 'ld hl, wMonHMoves' in add_mon and 'predef WriteMonMoves' in add_mon
        assert 'ld hl, wMonHMoves' in battle and 'predef WriteMonMoves ; get moves based on current level' in battle
        catch_overrides={}
        if variant=='yellow':
            assert 'cp KADABRA\n\tjr nz, .notKadabra\n\tld a, TWISTEDSPOON_GSC\n\tld [wBoxMon1CatchRate], a' in items
            species=parse_pokemon_constants(str(repo/'constants/pokemon_constants.asm'))['KADABRA']
            definitions=(repo/'constants/item_constants.asm').read_text(encoding='utf-8')
            values=re.findall(r'^DEF TWISTEDSPOON_GSC EQU \$([0-9a-fA-F]+)$',definitions,re.M)
            assert len(values)==1
            catch_overrides[str(species)]=int(values[0],16)
        assert OLD_MAN[source] in items and items.count('.oldManCaughtMon') == 1+len(EXCLUDED[source])
        assert '; wild battle, this is 1\n; trainer battle, this is 2\nwIsInBattle:: db\n' in wram
        for table, base in ((ENEMY, 'wEnemyMon'), (PARTY, 'wPartyDataStart'), (BOX, 'wBoxDataStart')):
            assert {name: syms[name][1]-syms[base][1] for name in table} == table, (variant, base)
        assert syms['wCurItem'] == syms['wCurPartySpecies']  # the ball id is overwritten by the caught species
        types = battle_types(repo)
        assigned = assigned_battle_types(repo)
        assert set(EXCLUDED[source]) <= assigned and 'BATTLE_TYPE_SAFARI' in assigned and 'BATTLE_TYPE_NORMAL' not in assigned
        delivering = {name: value for name, value in types.items()
                      if name not in EXCLUDED[source] and (name == 'BATTLE_TYPE_NORMAL' or name in assigned)}
        assert delivering == {'BATTLE_TYPE_NORMAL': 0, 'BATTLE_TYPE_SAFARI': 2}
        lines = items.splitlines()
        scopes = source_scopes(lines, syms)
        label, (bank, cpu) = call_site(lines, scopes, syms, rom, 'AddPartyMon')
        assert label == 'ItemUseBall.skipShowingPokedexData' and syms['AddPartyMon'][0] == 0
        party_begin, party_end = site(rom, label, bank, cpu, 3), site(rom, label, bank, cpu+3, 8)
        tail = bytes.fromhex(party_end['expected_hex'])
        assert tail[0] == 0x18 and cpu+5 == syms['ItemUseBall.sendToBox'][1]  # jr .done, then .sendToBox
        assert tail[2:8] == b'\xcd'+operand(syms, 'ClearSprites')+b'\xcd'+operand(syms, 'SendNewMonToBox')
        label, (bank, cpu) = call_site(lines, scopes, syms, rom, 'SendNewMonToBox')
        assert label == 'ItemUseBall.sendToBox' and cpu == syms['ItemUseBall.sendToBox'][1]+3
        assert rom[flat((bank, cpu-3)):flat((bank, cpu))] == b'\xcd'+operand(syms, 'ClearSprites')
        box_begin, box_end = site(rom, label, bank, cpu, 3), site(rom, label, bank, cpu+3, 8)
        tail = bytes.fromhex(box_end['expected_hex'])
        assert tail[0] == 0x21 and tail[1:3] == operand(syms, 'ItemUseBallText07') and tail[3] == 0xFA and tail[6] == 0xCB
        assert flat(syms['ItemUseBall']) <= party_begin['rom_offset'] < box_end['rom_offset'] < flat(syms['ItemUseBallText00'])
        result['titles'][variant] = {
            'source_commit': lock['sources'][source]['commit'],
            'symbols_sha256': hashlib.sha256((repo/(target+'.sym')).read_bytes()).hexdigest(),
            'clean_sha1': lock['clean_roms'][target]['sha1'],
            'addresses': {name: syms[name][1] for name in NAMES},
            'lengths': {'party': 404, 'box': 1122, 'enemy': 29, 'name': 11, 'player_id': 2},
            'battle_types': types, 'delivering_battle_types': delivering,
            'boxed_catch_rate_overrides':catch_overrides,
            'excluded_battle_types': {name: types[name] for name in EXCLUDED[source]}, 'wild_battle_flag': 1,
            'sites': {'party_begin': party_begin, 'party_end': party_end, 'box_begin': box_begin, 'box_end': box_end}}
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    value = build()
    encoded = json.dumps(value, indent=2, sort_keys=True)+'\n'
    text = '-- Generated by tools/gen_gen1_capture_sites.py from pinned source/ROMs.\nreturn '+lua(value)+'\n'
    if args.check:
        assert OUTPUT.read_text(encoding='utf-8') == encoded and LUA.read_text(encoding='utf-8') == text, 'capture site data is stale'
    else:
        OUTPUT.write_text(encoded, encoding='utf-8', newline='\n')
        LUA.write_text(text, encoding='utf-8', newline='\n')
    print('OK: capture delivery sites', {name: row['sites']['party_begin']['address'] for name, row in value['titles'].items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
