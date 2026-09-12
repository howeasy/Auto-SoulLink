"""Pin original trainer-name borrow/copy intervals from source and assembled ROMs."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gen_gen1_acquisition_sources import TITLES, flat, symbols  # noqa: E402
from gen_gen1_capture_sites import site  # noqa: E402
from gen_gen1_engine_signals import lua  # noqa: E402
from verify_canonical_sources import verify  # noqa: E402

OUTPUT = ROOT / 'data/games/gen1_rby/identity_sites.json'
LUA = OUTPUT.with_name('gen1_identity_sites.lua')


def build():
    assert verify(rom_dir=ROOT)['status'] == 'pass'
    lock = json.loads((ROOT / 'data/pret_sources.lock.json').read_text())
    result = {'schema': 'rby-identity-sites-v1', 'titles': {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT / '.cache/pret' / source
        syms = symbols(repo / (target + '.sym'))
        rom = (ROOT / lock['clean_roms'][target]['filename']).read_bytes()
        battle = (repo / 'engine/battle/core.asm').read_text(encoding='utf-8')
        items = (repo / 'engine/items/item_effects.asm').read_text(encoding='utf-8')
        trade = (repo / 'engine/movie/trade.asm').read_text(encoding='utf-8')
        def word(name, table=syms):
            return table[name][1].to_bytes(2, 'little')
        backup = b'\x21' + word('wPlayerName') + b'\x11' + word('wLinkEnemyTrainerName') + b'\x01\x0b\x00\xcd' + word('CopyData')
        assert '\tld hl, wPlayerName\n\tld de, wLinkEnemyTrainerName\n\tld bc, NAME_LENGTH\n\tcall CopyData\n' in battle
        bank, start = syms['DisplayBattleMenu']
        stop = syms['DisplayBattleMenu.handleBattleMenuInput'][1]
        offset = rom.index(backup, flat((bank, start)), flat((bank, stop)))
        assert rom.count(backup, flat((bank, start)), flat((bank, stop))) == 1
        address = start + offset - flat((bank, start))
        copy_name = b'\x11' + word('wPlayerName') + b'\x01\x0b\x00\xcd' + word('CopyData')
        name_offset = rom.index(copy_name, offset + len(backup), flat((bank, stop)))
        assert '\tld hl, wGrassRate\n\tld de, wPlayerName\n\tld bc, NAME_LENGTH\n\tcall CopyData' in items
        restore = b'\x21' + word('wGrassRate') + b'\x11' + word('wPlayerName') + b'\x01\x0b\x00\xcd' + word('CopyData')
        ibank, ibegin = syms['ItemUseBall']
        restore_offset = rom.index(restore, flat((ibank, ibegin)), flat((ibank, ibegin)) + 1500)
        restore_address = ibegin + restore_offset - flat((ibank, ibegin))
        sites = {}
        for name, sbank, cpu, length in (
            ('backup_begin', bank, address + 9, 3), ('backup_done', bank, address + 12, 3),
            ('borrow_begin', bank, start + name_offset - flat((bank, start)) + 6, 3),
            ('borrow_done', bank, start + name_offset - flat((bank, start)) + 9, 3),
            ('restore_begin', ibank, restore_address + 9, 3), ('restore_done', ibank, restore_address + 12, 3),
        ):
            sites[name] = site(rom, name, sbank, cpu, length)
        names = {}
        for kind, label, battle_type, map_id in (
            ('old_man', 'DisplayBattleMenu.oldManName', 1, 1),
            *((('oak', 'DisplayBattleMenu.profOakName', 4, 0),) if variant == 'yellow' else ()),
        ):
            address = syms[label][1]
            names[str(battle_type)] = {'kind': kind, 'address': address, 'map': map_id,
                                      'hex': rom[flat(syms[label]):flat(syms[label]) + 11].hex().upper()}
        if variant == 'yellow':
            pallet = (repo / 'scripts/PalletTown.asm').read_text(encoding='utf-8')
            assert '\tld a, BATTLE_TYPE_PIKACHU\n\tld [wBattleType], a\n' in pallet
            assert '\tld a, SCRIPT_PALLETTOWN_AFTER_PIKACHU_BATTLE\n\tld [wPalletTownCurScript], a\n' in pallet
            assert 'SCRIPT_PALLETTOWN_AFTER_PIKACHU_BATTLE' in pallet.split('PalletTownDefaultScript:')[0]
            names['4']['pallet_script'] = 5
        swap = b'\x21' + word('wPlayerName') + b'\x11' + word('wBuffer') + b'\x01\x0b\x00\xcd' + word('CopyData')
        swap += b'\x21' + word('wLinkEnemyTrainerName') + b'\x11' + word('wPlayerName') + b'\x01\x0b\x00\xcd' + word('CopyData')
        swap += b'\x21' + word('wBuffer') + b'\x11' + word('wLinkEnemyTrainerName') + b'\x01\x0b\x00\xc3' + word('CopyData')
        tbank, ts = syms['Trade_SwapNames']
        assert rom[flat((tbank, ts)):flat((tbank, ts)) + 36] == swap
        assert 'tradefunc Trade_SwapNames' not in trade.split('InternalClockTradeFuncSequence:')[1].split('ExternalClockTradeFuncSequence:')[0]
        sites['swap_begin'] = site(rom, 'Trade_SwapNames', tbank, ts, 36)
        sites['swap_copy_begin'] = site(rom, 'Trade_SwapNames+21', tbank, ts + 21, 3)
        sites['swap_copy_done'] = site(rom, 'Trade_SwapNames+24', tbank, ts + 24, 3)
        sites['swap_cleanup'] = site(rom, 'Trade_Cleanup', *syms['Trade_Cleanup'], 4)
        cb, ca = syms['CopyData']
        assert cb == 0
        expected_copy = bytes.fromhex('2A12130B79B020F8C9')
        if variant == 'yellow':
            expected_copy = bytes.fromhex('78A7280C79A7280104CD') + (ca + 16).to_bytes(2, 'little') + bytes.fromhex('0520FAC92A12130D20FAC9')
        assert rom[ca:ca + len(expected_copy)] == expected_copy
        result['titles'][variant] = {
            'source_commit': lock['sources'][source]['commit'], 'sites': sites, 'names': names,
            'copy': site(rom, 'CopyData', 0, ca, len(expected_copy)),
            'ram': {name: syms[name][1] for name in ('hLoadedROMBank', 'wPlayerName', 'wPlayerID', 'wLinkEnemyTrainerName',
                                                    'wBuffer', 'wBattleType', 'wCurMap', 'wIsInBattle', 'wPartyCount', 'wPalletTownCurScript')},
        }
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    value = build()
    text = json.dumps(value, indent=2, sort_keys=True) + '\n'
    script = '-- Generated by tools/gen_gen1_identity_sites.py.\nreturn ' + lua(value) + '\n'
    if args.check:
        assert OUTPUT.read_text(encoding='utf-8') == text and LUA.read_text(encoding='utf-8') == script
    else:
        OUTPUT.write_text(text, encoding='utf-8', newline='\n')
        LUA.write_text(script, encoding='utf-8', newline='\n')
    print('OK: RBY source-qualified trainer-name borrow intervals')


if __name__ == '__main__':
    main()
