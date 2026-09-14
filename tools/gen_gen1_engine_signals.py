"""Generate reviewed engine signal sites from pinned source, symbols and ROM bytes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
try:
    from gen_gen1_acquisition_sources import TITLES, address, symbols
    from verify_canonical_sources import verify
finally:
    sys.path.pop(0)

OUTPUT = ROOT/'data/games/gen1_rby/engine_signals.json'
LUA = ROOT/'data/games/gen1_rby/gen1_engine_signal_data.lua'


def build():
    checked = verify(rom_dir=ROOT)
    if checked['status'] != 'pass':
        raise ValueError('canonical signal sources did not verify')
    lock = json.loads((ROOT/'data/pret_sources.lock.json').read_text())
    census = json.loads((ROOT/'data/games/gen1_rby/acquisition_sources.json').read_text())
    result = {'schema': 'rby-engine-signal-sites-v1', 'titles': {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT/'.cache/pret'/source
        syms = symbols(repo/(target+'.sym'))
        rom = (ROOT/lock['clean_roms'][target]['filename']).read_bytes()
        def site(name, offset=0, length=8, syms=syms, rom=rom):
            bank, cpu = syms[name]
            value = address((bank, cpu+offset))
            value.update(symbol=name, expected_hex=rom[value['rom_offset']:value['rom_offset']+length].hex().upper())
            return value
        poison = (repo/'engine/events/poison.asm').read_text()
        assert '; the mon fainted from the damage\n\tpush hl' in poison
        point = site('ApplyOutOfBattlePoisonDamage.noBorrow')
        raw = bytes.fromhex(point['expected_hex'])
        assert raw[:3] == bytes.fromhex('2AB620') and raw[4:8] == bytes.fromhex('E5232377')
        battle = (repo/'engine/battle/core.asm').read_text()
        assert 'RemoveFaintedPlayerMon:\n\tld a, [wPlayerMonNumber]' in battle
        assert '\tcall RemoveFaintedPlayerMon\n.playermonnotfaint' in battle
        starter = next(row for row in census['titles'][variant]['sources'] if row['group'] == 'starter')
        assert starter['target_symbol'] == 'AddPartyMon'
        call = starter['call']
        offset = call['rom_offset']
        assert rom[offset:offset+3].hex() == starter['expected_call_hex']
        sites = {'battle_faint': site('RemoveFaintedPlayerMon'),
                 'poison_faint': site('ApplyOutOfBattlePoisonDamage.noBorrow', 4),
                 'starter_begin': {**call, 'symbol': starter['scope_symbol'],
                                   'expected_hex': rom[offset:offset+3].hex().upper()},
                 'starter_end': {**address((call['bank'], starter['return_address'])),
                                 'symbol': starter['scope_symbol'], 'expected_hex': rom[offset+3:offset+11].hex().upper()}}
        items = (repo/'engine/items/inventory.asm').read_text()
        assert '.done\n\tpop hl\n\tpop de\n\tpop bc\n\tpop bc\n\tld a, b\n\tld [wItemQuantity], a' in items
        done = site('AddItemToInventory_.done', length=9)
        quantity = syms['wItemQuantity'][1]
        assert bytes.fromhex(done['expected_hex']) == bytes((0xE1,0xD1,0xC1,0xC1,0x78,0xEA,quantity&255,quantity>>8,0xC9))
        sites['bag_received'] = {**done, 'capture_offset': 8}
        # START-menu save completion: SaveMenu.save is `call SaveGameData` then `hlcoord`/`ld hl`; the
        # capture point is the instruction after the call, reached only once SaveGameData has returned.
        # (SaveGameData's own RET is shared with the Cable Club partial save, ChangeBox and the Hall of Fame.)
        save = (repo/'engine/menus/save.asm').read_text()
        assert '.save\n\tcall SaveGameData\n' in save and 'SaveGameData::\n\tld a, $2\n\tld [wSaveFileStatus], a\n' in save
        menu = site('SaveMenu.save', length=6)
        callee = syms['SaveGameData'][1]
        assert bytes.fromhex(menu['expected_hex'])[:4] == bytes((0xCD, callee&255, callee>>8, 0x21))
        sites['save_witness'] = {**menu, 'capture_offset': 3}
        names = ['hLoadedROMBank', 'wPartyDataStart', 'wPlayerName', 'wPlayerID', 'wCurMap', 'wIsInBattle',
                 'wPlayerMonNumber', 'wBattleMonHP', 'wBattleMonSpecies', 'wWhichPokemon',
                 'wMonDataLocation', 'wCurPartySpecies', 'wCurEnemyLevel', 'wNumBagItems', 'wCurItem', 'wItemQuantity',
                 'wCurOpponent']  # trainer class + 200 while wIsInBattle == 2: the free loop's trainer_battle_start probe
        assert syms['wPartyDataEnd'][1]-syms['wPartyDataStart'][1] == 404
        result['titles'][variant] = {'source_commit': lock['sources'][source]['commit'],
            'symbols_sha256': hashlib.sha256((repo/(target+'.sym')).read_bytes()).hexdigest(),
            'clean_sha1': lock['clean_roms'][target]['sha1'], 'starter_map': starter['map_id'],
            'addresses': {name: syms[name][1] for name in names}, 'sites': sites}
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def lua(value):
    if isinstance(value, dict):
        return '{'+','.join('['+json.dumps(k)+']='+lua(v) for k,v in sorted(value.items()))+'}'
    if isinstance(value, str):
        return json.dumps(value)
    if type(value) is int:
        return str(value)
    raise TypeError(value)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args=parser.parse_args()
    value=build()
    encoded=json.dumps(value, indent=2, sort_keys=True)+'\n'
    text='-- Generated by tools/gen_gen1_engine_signals.py from pinned source/ROMs.\nreturn '+lua(value)+'\n'
    if args.check:
        assert OUTPUT.read_text()==encoded and LUA.read_text()==text, 'engine signal data is stale'
    else:
        OUTPUT.write_text(encoded, encoding='utf-8', newline='\n')
        LUA.write_text(text, encoding='utf-8', newline='\n')
