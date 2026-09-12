"""Generate reviewed static-battle origin sites from pinned source, symbols and ROM bytes.

A static encounter starts its battle by writing the opponent into wCurOpponent and the
level into wCurEnemyLevel, then returning to the overworld loop, which sees a non-zero
wCurOpponent and jumps to InitBattle -> InitOpponent -> InitWildBattle (home/overworld.asm
`.newBattle`, engine/battle/core.asm or init_battle.asm). Two writers exist:

- script statics (Route 12/16 Snorlax): the map script writes both bytes itself; the
  10-byte write block is pinned per site and the witness PC is the instruction after it.
- object statics (Mewtwo, the three birds, Power Plant Voltorbs/Electrodes): the object
  record's species/level bytes are loaded into wMapSpriteExtraData at map load, copied
  to wEngagedTrainerClass/Set by EngageMapTrainer using wSpriteIndex, and written by the
  shared home routine InitBattleEnemyParameters (`.noTrainer` for class < OPP_ID_OFFSET).
  The witness PC is that routine's `ret`; wSpriteIndex (== the object's text id, asserted
  against every record) names the object.

Every static then shares one `began` witness: InitWildBattle just after wIsInBattle := 1,
where wEnemyMonSpecies2 == wCurOpponent. Fishing (RodResponse) also writes wCurOpponent,
so `began` alone never names a static; the arm witness does. Ghost Marowak and the
unidentified GHOST are classified as excluded: ItemUseBall refuses both, and every
Pokemon Tower map is refused outright.

Every battle, however it ends, leaves through one routine: InitBattleCommon runs
`call StartBattle` then `callfar EndOfBattle` unconditionally (the only call of
EndOfBattle in the ROM, asserted), and StartBattle returns for every exit -- enemy KO
(HandleEnemyMonFainted `ret z` for wild), player loss/blackout (HandlePlayerBlackOut
`scf ; ret`), RUN (TryRunningFromBattle `.canEscape`, `ret c` in MainInBattleLoop),
capture (`.returnAfterCapturingMon` `scf ; ret`), wild flight/Poke Doll (wEscapedFromBattle
`ret nz`). At EndOfBattle's entry wBattleResult ($00 win, $01 lose, $02 draw: caught or
ran) is final and wIsInBattle/wCurOpponent/wCurEnemyLevel are still intact; `.resetVariables`
clears them. That entry is the single `battle_end` witness. A ball that breaks free returns
through `.returnAfterUsingItem_NoCapture` with carry clear: the battle continues and no
battle_end is witnessed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
try:
    from gen_gen1_acquisition_sources import TITLES, address, flat, symbols
    from gen_gen1_capture_sites import battle_types
    from gen_gen1_grant_sites import lua, site, static_record, word
    from verify_canonical_sources import verify
finally:
    sys.path.pop(0)

OUTPUT = ROOT/'data/games/gen1_rby/static_sites.json'
LUA = ROOT/'data/games/gen1_rby/gen1_static_sites.lua'
NAMES = ['hLoadedROMBank', 'wCurMap', 'wCurOpponent', 'wCurEnemyLevel', 'wEnemyMonSpecies2', 'wIsInBattle', 'wBattleType',
         'wSpriteIndex', 'wEngagedTrainerClass', 'wEngagedTrainerSet', 'wPlayerName', 'wPlayerID', 'wBattleResult', 'wLinkState']
INIT_BATTLE = {'pokered': 'engine/battle/core.asm', 'pokeyellow': 'engine/battle/init_battle.asm'}
OPP_ID_OFFSET, RESTLESS_SOUL, TRAINER, MAX_OBJECT_EVENTS = 200, 0x91, 0x40, 16
LINK_STATE_BATTLING, CHAN5 = 4, 4
BATTLE_RESULTS = {'win': 0, 'lose': 1, 'draw': 2}  # $02 is also written by a capture and by a successful RUN
EXCLUDED_REASONS = {
    'script-battle:ghost-marowak': 'Ghost Marowak: ItemUseBall sets the can\'t-be-caught value when wCurMap == POKEMON_TOWER_6F and '
                                   'wEnemyMonSpecies2 == RESTLESS_SOUL; the decoder refuses every Pokemon Tower map before any static id',
    'script-battle:unidentified-tower-ghost': 'unidentified GHOST: IsGhostBattle (wild battle on POKEMON_TOWER_1F..7F without SILPH_SCOPE) '
                                              'makes ItemUseBall set the can\'t-be-caught value; the decoder refuses every Pokemon Tower map',
    'script-battle:old-man-tutorial': 'BATTLE_TYPE_OLD_MAN: ItemUseBall jumps to .oldManCaughtMon and never delivers; the decoder requires '
                                      'BATTLE_TYPE_NORMAL at the began witness',
    'script-battle:oak-pikachu': 'BATTLE_TYPE_PIKACHU: ItemUseBall treats it as the old man battle and never delivers; the decoder requires '
                                 'BATTLE_TYPE_NORMAL at the began witness',
}
# Source lines whose exact semantics the decoder's predicates depend on (both sources unless keyed).
GUARDS = {
    'home/trainers.asm': [
        "InitBattleEnemyParameters::\n\tld a, [wEngagedTrainerClass]\n\tld [wCurOpponent], a\n\tld [wEnemyMonOrTrainerClass], a\n"
        "\tcp OPP_ID_OFFSET\n\tld a, [wEngagedTrainerSet]\n\tjr c, .noTrainer\n\tld [wTrainerNo], a\n\tret\n.noTrainer\n"
        "\tld [wCurEnemyLevel], a\n\tret\n",
        "EngageMapTrainer::\n\tld hl, wMapSpriteExtraData\n\tld d, $0\n\tld a, [wSpriteIndex]\n\tdec a\n\tadd a\n\tld e, a\n"
        "\tadd hl, de     ; seek to engaged trainer data\n\tld a, [hli]    ; load trainer class\n\tld [wEngagedTrainerClass], a\n"
        "\tld a, [hl]     ; load trainer mon set\n\tld [wEngagedTrainerSet], a\n",
        "StartTrainerBattle::\n\txor a\n\tld [wJoyIgnore], a\n\tcall InitBattleEnemyParameters\n",
        "; if the player talked to the trainer of his own volition\n\tcall EngageMapTrainer\n"],
    'home/overworld.asm': [
        "\tld a, [wCurOpponent]\n\tand a\n\tjp nz, .newBattle\n",
        ".newBattle\n\tcall NewBattle\n",
        "\tld a, [wStatusFlags4]\n\tbit BIT_NO_BATTLES, a\n\tjr nz, .noBattle\n\tfarjp InitBattle\n",
        ".trainerSprite\n\tld a, [hli]\n\tldh [hLoadSpriteTemp1], a ; save trainer class\n\tld a, [hli]\n"
        "\tldh [hLoadSpriteTemp2], a ; save trainer number (within class)\n\tpush hl\n\tld hl, wMapSpriteExtraData\n"],
    'home/text_script.asm': ["\tldh a, [hTextID]\n\tld [wSpriteIndex], a\n", "\tASSERT hSpriteIndex == hTextID"],
    'engine/battle/core.asm': [
        # Every exit of the battle loop returns to InitBattleCommon; none clears wIsInBattle itself.
        "\tcall DisplayBattleMenu ; show battle menu\n\tret c ; return if player ran from battle\n\tld a, [wEscapedFromBattle]\n\tand a\n"
        "\tret nz ; return if pokedoll was used to escape from battle\n",
        "\tld a, [wIsInBattle]\n\tdec a\n\tret z ; return if it's a wild battle\n",  # HandleEnemyMonFainted: wild KO
        "\tcall SaveScreenTilesToBuffer1\n\txor a\n\tld [wBattleResult], a\n\tld b, EXP_ALL\n",  # FaintEnemyPokemon: win
        "\tcall SlideDownFaintedMonPic\n\tld a, $1\n\tld [wBattleResult], a\n",  # RemoveFaintedPlayerMon: lose
        "\tcall PrintText\n\tld a, [wStatusFlags6]\n\tres BIT_ALWAYS_ON_BIKE, a\n\tld [wStatusFlags6], a\n\tcall ClearScreen\n\tscf\n\tret\n",
        ".playSound\n\tld [wBattleResult], a\n\tld a, SFX_RUN\n\tcall PlaySoundWaitForCurrent\n\tld hl, GotAwayText\n",  # RUN: $02
        ".returnAfterUsingItem_NoCapture\n\n\tcall GBPalNormal\n\tand a ; reset carry\n\tret\n\n.returnAfterCapturingMon\n\tcall GBPalNormal\n"
        "\txor a\n\tld [wCapturedMonSpecies], a\n\tld a, $2\n\tld [wBattleResult], a\n\tscf ; set carry\n\tret\n",
        "IsGhostBattle:\n\tld a, [wIsInBattle]\n\tdec a\n\tret nz\n\tld a, [wCurMap]\n\tcp POKEMON_TOWER_1F\n\tjr c, .next\n"
        "\tcp POKEMON_TOWER_7F + 1\n\tjr nc, .next\n\tld b, SILPH_SCOPE\n\tcall IsItemInBag\n\tret z\n.next\n\tld a, 1\n\tand a\n\tret\n"],
    'engine/battle/init_battle_variables.asm': [
        "\tld a, [wCurMap]\n\tcp SAFARI_ZONE_EAST\n\tjr c, .notSafariBattle\n\tcp SAFARI_ZONE_CENTER_REST_HOUSE\n\tjr nc, .notSafariBattle\n"
        "\tld a, BATTLE_TYPE_SAFARI\n\tld [wBattleType], a\n.notSafariBattle\n"],
    'engine/battle/end_of_battle.asm': [
        "EndOfBattle:\n\tld a, [wLinkState]\n\tcp LINK_STATE_BATTLING\n\tjr nz, .notLinkBattle\n",
        ".notLinkBattle\n\tld a, [wBattleResult]\n\tand a\n\tjr nz, .resetVariables\n",
        ".resetVariables\n\txor a\n\tld [wLowHealthAlarm], a ;disable low health alarm\n\tld [wChannelSoundIDs + CHAN5], a\n"
        "\tld [wIsInBattle], a\n\tld [wBattleType], a\n\tld [wMoveMissed], a\n\tld [wCurOpponent], a\n"],
    'engine/battle/wild_encounters.asm': [
        "\tld a, [hli]\n\tld [wCurEnemyLevel], a\n\tld a, [hl]\n\tld [wCurPartySpecies], a\n\tld [wEnemyMonSpecies2], a\n"],
    'engine/items/item_effects.asm': [
        "\tcallfar IsGhostBattle\n\tld b, $10 ; can't be caught value\n\tjp z, .setAnimData\n",
        "\tld a, [wCurMap]\n\tcp POKEMON_TOWER_6F\n\tjr nz, .loop\n\tld a, [wEnemyMonSpecies2]\n\tcp RESTLESS_SOUL\n"
        "\tld b, $10 ; can't be caught value\n\tjp z, .setAnimData\n",
        "\tld a, b ; level\n\tld [wCurEnemyLevel], a\n\tld a, c ; species\n\tld [wCurOpponent], a\n"],
    'ram/wram.asm': [
        "; in a wild battle, this is the species of pokemon\n; in a trainer battle, this is the trainer class + OPP_ID_OFFSET\nwCurOpponent:: db\n",
        "wMapSpriteExtraData:: ds MAX_OBJECT_EVENTS * 2 ; trainer class/item ID, trainer set ID\n",
        "; $00 - win\n; $01 - lose\n; $02 - draw\nwBattleResult:: db\n"],
    'constants/serial_constants.asm': ["DEF LINK_STATE_BATTLING      EQU $04 ; in a link battle\n"],
    'constants/audio_constants.asm': ["\tconst CHAN5 ; 4\n"],
    'macros/scripts/maps.asm': ["\tIF _NARG > 7\n\t\tdb TRAINER | \\6\n\t\tdb \\7\n\t\tdb \\8\n", "MACRO object_const_def\n\tconst_def 1\nENDM\n"],
    'constants/map_object_constants.asm': ["\tconst BIT_TRAINER ; 6\n", "DEF TRAINER EQU 1 << BIT_TRAINER\n"],
    'constants/trainer_constants.asm': ["DEF OPP_ID_OFFSET EQU 200\n"],
    'constants/pokemon_constants.asm': ["DEF RESTLESS_SOUL EQU MAROWAK\n"],
}
INIT_GUARDS = [
    "InitBattle::\n\tld a, [wCurOpponent]\n\tand a\n\tjr z, DetermineWildOpponent\n\nInitOpponent:\n\tld a, [wCurOpponent]\n"
    "\tld [wCurPartySpecies], a\n\tld [wEnemyMonSpecies2], a\n\tjr InitBattleCommon\n",
    "\tld a, [wEnemyMonSpecies2]\n\tsub OPP_ID_OFFSET\n\tjp c, InitWildBattle\n",
    "InitWildBattle:\n\tld a, $1\n\tld [wIsInBattle], a\n",
    "\tld a, [wCurOpponent]\n\tcp RESTLESS_SOUL\n\tjr z, .isGhost\n",
    "\tcallfar EndOfBattle\n\tpop af\n\tld [wLetterPrintingDelayFlags], a\n",
]
SNORLAX = "\tld a, SNORLAX\n\tld [wCurOpponent], a\n\tld a, 30\n\tld [wCurEnemyLevel], a\n\tld a, TOGGLE_ROUTE_{}_SNORLAX\n\tld [wToggleableObjectIndex], a\n"
MAROWAK = "\tld a, RESTLESS_SOUL\n\tld [wCurOpponent], a\n\tld a, 30\n\tld [wCurEnemyLevel], a\n"
OLD_MAN = "\tld a, BATTLE_TYPE_OLD_MAN\n\tld [wBattleType], a\n\tld a, 5\n\tld [wCurEnemyLevel], a\n\tld a, {}\n\tld [wCurOpponent], a\n"
PIKACHU = "\tld a, BATTLE_TYPE_PIKACHU\n\tld [wBattleType], a\n\tld a, STARTER_PIKACHU\n\tld [wCurOpponent], a\n\tld a, 5\n\tld [wCurEnemyLevel], a\n"
SPECIES_POLICY = 'read from cartridge memory (wCurOpponent) at both witnesses; approved staticPokemonMod may rewrite these bytes'
LEVEL_POLICY = 'pinned: gen1_upr_scan never claims these bytes, so RomChangeAudit.finish rejects any admitted ROM that changed them'


def anchor(rom, offset, length):
    return {'rom_offset': offset, 'expected_hex': rom[offset:offset+length].hex().upper()}


def find_once(rom, start, end, pattern):
    hits = [offset for offset in range(start, end-len(pattern)+1) if rom[offset:offset+len(pattern)] == pattern]
    assert len(hits) == 1, (pattern.hex(), hits)
    return hits[0]


def build():
    checked = verify(rom_dir=ROOT)
    if checked['status'] != 'pass':
        raise ValueError('canonical static sources did not verify')
    lock = json.loads((ROOT/'data/pret_sources.lock.json').read_text())
    census = json.loads((ROOT/'data/games/gen1_rby/acquisition_sources.json').read_text(encoding='utf-8'))
    layout = json.loads((ROOT/'data/games/gen1_rby/upr_layout.json').read_text(encoding='utf-8'))
    result = {'schema': 'rby-static-sites-v1', 'titles': {}}
    for variant, (source, target) in TITLES.items():
        repo = ROOT/'.cache/pret'/source
        syms = symbols(repo/(target+'.sym'))
        rom = (ROOT/lock['clean_roms'][target]['filename']).read_bytes()
        statics = layout['profiles'][variant]['statics']
        ghost = [row for row in statics if row['ghost']]
        assert len(ghost) == 1
        texts = {name: (repo/name).read_text(encoding='utf-8') for name in [*GUARDS, INIT_BATTLE[source]]}
        for name, guards in GUARDS.items():
            for guard in guards:
                assert guard in texts[name], (variant, name, guard)
        for guard in INIT_GUARDS:
            assert guard in texts[INIT_BATTLE[source]], (variant, guard)
        assert 'wCurOpponent' not in texts['engine/battle/wild_encounters.asm']  # random encounters never write it
        types = battle_types(repo)
        assert types['BATTLE_TYPE_NORMAL'] == 0 and types['BATTLE_TYPE_OLD_MAN'] == 1 and types['BATTLE_TYPE_SAFARI'] == 2
        assert syms['hSpriteIndex'] == syms['hTextID']
        # Shared writer for object statics: InitBattleEnemyParameters, .noTrainer at +20, its ret at +23.
        params = flat(syms['InitBattleEnemyParameters'])
        routine = (b'\xfa'+word(syms, 'wEngagedTrainerClass')+b'\xea'+word(syms, 'wCurOpponent')+b'\xea'+word(syms, 'wEnemyMonOrTrainerClass')
                   + bytes((0xfe, OPP_ID_OFFSET))+b'\xfa'+word(syms, 'wEngagedTrainerSet')+b'\x38\x04\xea'+word(syms, 'wTrainerNo')+b'\xc9\xea'
                   + word(syms, 'wCurEnemyLevel')+b'\xc9')
        assert rom[params:params+24] == routine and syms['InitBattleEnemyParameters.noTrainer'][1] == syms['InitBattleEnemyParameters'][1]+20
        assert syms['InitBattleEnemyParameters'][0] == 0
        object_arm = site(rom, 'InitBattleEnemyParameters.noTrainer+3', 0, syms['InitBattleEnemyParameters.noTrainer'][1]+3, 1)
        object_arm['routine'] = anchor(rom, params, 24)
        # Shared began witness: InitWildBattle after `ld a, 1 ; ld [wIsInBattle], a`, at the LoadEnemyMonData call.
        wild = syms['InitWildBattle']
        woff = flat(wild)
        assert rom[woff:woff+5] == b'\x3e\x01\xea'+word(syms, 'wIsInBattle')
        load = syms['LoadEnemyMonData']
        if wild[0] == load[0]:
            call = b'\xcd'+word(syms, 'LoadEnemyMonData')
        else:  # Yellow: callfar = ld hl, nn ; ld b, BANK ; call Bankswitch
            call = b'\x21'+word(syms, 'LoadEnemyMonData')+bytes((0x06, load[0], 0xcd))+word(syms, 'Bankswitch')
        assert rom[woff+5:woff+5+len(call)] == call
        began = site(rom, 'InitWildBattle+5', wild[0], wild[1]+5, len(call))
        began['prelude'] = anchor(rom, woff, 5)
        # Shared battle_end witness: EndOfBattle's entry, `ld a, [wLinkState] ; cp LINK_STATE_BATTLING`, reached
        # once per battle from the ROM's only `callfar EndOfBattle`, right after `call(far) StartBattle` returns.
        end = syms['EndOfBattle']
        eoff = flat(end)
        assert rom[eoff:eoff+5] == b'\xfa'+word(syms, 'wLinkState')+bytes((0xfe, LINK_STATE_BATTLING))
        battle_end = site(rom, 'EndOfBattle', end[0], end[1], 5)
        reset = syms['EndOfBattle.resetVariables']
        assert reset[0] == end[0]
        clears = (b'\xaf\xea'+word(syms, 'wLowHealthAlarm')+b'\xea'+word(syms, 'wChannelSoundIDs', CHAN5)+b'\xea'+word(syms, 'wIsInBattle')
                  + b'\xea'+word(syms, 'wBattleType')+b'\xea'+word(syms, 'wMoveMissed')+b'\xea'+word(syms, 'wCurOpponent'))
        assert rom[flat(reset):flat(reset)+len(clears)] == clears
        battle_end['reset'] = anchor(rom, flat(reset), len(clears))
        callfar = b'\x21'+word(syms, 'EndOfBattle')+bytes((0x06, end[0], 0xcd))+word(syms, 'Bankswitch')
        assert rom.count(callfar) == 1
        start = syms['StartBattle']
        if start[0] == syms['InitBattle'][0]:
            starter = b'\xcd'+word(syms, 'StartBattle')
        else:  # Yellow moved InitBattle out of the core bank: callfar StartBattle
            starter = b'\x21'+word(syms, 'StartBattle')+bytes((0x06, start[0], 0xcd))+word(syms, 'Bankswitch')
        coff = rom.find(callfar)
        assert rom[coff-len(starter):coff] == starter and flat(syms['InitBattle']) < coff < flat(syms['InitBattle'])+0x200
        battle_end['call'] = anchor(rom, coff-len(starter), len(starter)+len(callfar))
        # The engine's own ghost test after the transition; UPR rewrites this operand with the script's.
        compare = find_once(rom, woff, woff+48, b'\xfa'+word(syms, 'wCurOpponent')+bytes((0xfe, RESTLESS_SOUL)))+4
        entry = flat(syms['InitBattle'])
        assert rom[entry:entry+5] == b'\xfa'+word(syms, 'wCurOpponent')+b'\xa7\x28'
        # IsGhostBattle: the tower range and the Silph Scope test give the excluded map ids.
        ghost_test = flat(syms['IsGhostBattle'])
        expect = b'\xfa'+word(syms, 'wIsInBattle')+b'\x3d\xc0\xfa'+word(syms, 'wCurMap')+b'\xfe'
        # fa w 3d c0 fa w | fe 8E 38 rr | fe 95 30 rr | 06 48 (SILPH_SCOPE) cd IsItemInBag c8 3e 01 a7 c9
        assert rom[ghost_test:ghost_test+9] == expect and rom[ghost_test+12] == 0xfe and rom[ghost_test+16:ghost_test+18] == b'\x06\x48'
        assert rom[ghost_test+18:ghost_test+21] == b'\xcd'+word(syms, 'IsItemInBag') and rom[ghost_test+21:ghost_test+26] == b'\xc8\x3e\x01\xa7\xc9'
        tower = list(range(rom[ghost_test+9], rom[ghost_test+13]))
        sites, excluded = {}, {}
        for row in census['titles'][variant]['sources']:
            if row['kind'] == 'uncatchable_script_battle':
                reason = EXCLUDED_REASONS[row['source_id']]
                text = (repo/row['source_file']).read_text(encoding='utf-8') if 'source_file' in row else None
                if row['source_id'] == 'script-battle:ghost-marowak':
                    off = row['entry']['rom_offset']
                    assert MAROWAK in text and rom[off:off+10] == bytes((0x3e, RESTLESS_SOUL, 0xea))+word(syms, 'wCurOpponent')+b'\x3e\x1e\xea'+word(syms, 'wCurEnemyLevel')
                    assert row['map_id'] in tower and row['species_index'] == RESTLESS_SOUL
                    # UPR's ghost record rewrites the script operand and both engine compares together.
                    assert {off+1, compare} <= set(ghost[0]['Species']) and ghost[0]['Level'] == [off+6]
                    ball = flat(syms['ItemUseBall'])
                    ball_compare = find_once(rom, ball, ball+0x100, b'\xfa'+word(syms, 'wEnemyMonSpecies2')+bytes((0xfe, RESTLESS_SOUL)))+4
                    assert ball_compare in ghost[0]['Species']
                elif row['source_id'] == 'script-battle:unidentified-tower-ghost':
                    assert row['map_ids'] == tower and row['entry'] == address(syms['IsGhostBattle'])
                else:
                    off = row['entry']['rom_offset']
                    assert rom[off:off+5] == bytes((0x3e, row['species_index'], 0xea))+word(syms, 'wCurOpponent')
                    if row['source_id'] == 'script-battle:oak-pikachu':
                        assert PIKACHU in text and variant == 'yellow'
                    else:
                        assert OLD_MAN.format('RATTATA' if variant == 'yellow' else 'WEEDLE') in text
                excluded[row['source_id']] = {'reason': reason, **{k: v for k, v in row.items() if k not in ('kind', 'source_id')}}
                continue
            if row['kind'] != 'catchable_static':
                continue
            entry = {'map': row['map'], 'map_id': row['map_id'], 'source_file': row['source_file']}
            assert row['map_id'] not in tower
            if 'entry' in row:  # a map script writes both operands itself
                off, bank, cpu = row['entry']['rom_offset'], row['entry']['bank'], row['entry']['address']
                text = (repo/row['source_file']).read_text(encoding='utf-8')
                assert SNORLAX.format(row['map'].rsplit('_', 1)[1]) in text and row['species_index'] == 0x84
                assert rom[off:off+10] == bytes((0x3e, row['species_index'], 0xea))+word(syms, 'wCurOpponent')+b'\x3e\x1e\xea'+word(syms, 'wCurEnemyLevel')
                assert rom[off+10] == 0x3e and rom[off+12:off+15] == b'\xea'+word(syms, 'wToggleableObjectIndex')
                static_record(statics, off+1, off+6)
                entry.update(kind='script', source_line=row['source_line'], scope_symbol=row['scope_symbol'],
                             arm=site(rom, row['scope_symbol']+'+10', bank, cpu+10, 5), writes=anchor(rom, off, 10),
                             species={'source': 'immediate: ld a, SPECIES ; ld [wCurOpponent], a', 'rom_offsets': [off+1],
                                      'clean': [row['species_index']], 'policy': SPECIES_POLICY},
                             level={'source': 'immediate: ld a, LEVEL ; ld [wCurEnemyLevel], a', 'rom_offsets': [off+6], 'values': [30],
                                    'policy': LEVEL_POLICY})
            else:  # an object record: db TRAINER | text_id, species, level
                sp, lv = row['species_rom_offset'], row['level_rom_offset']
                assert lv == sp+1 and rom[sp-1] == TRAINER | row['object_index'] and rom[sp] == row['species_index'] and rom[lv] == row['level']
                assert 1 <= row['object_index'] < MAX_OBJECT_EVENTS and row['species_index'] < OPP_ID_OFFSET
                static_record(statics, sp, lv)
                entry.update(kind='object', object_index=row['object_index'], object_symbol=row['object_symbol'],
                             arm=dict(object_arm), writes=anchor(rom, sp-1, 3),
                             species={'source': 'object record byte via wMapSpriteExtraData -> wEngagedTrainerClass -> wCurOpponent',
                                      'rom_offsets': [sp], 'clean': [row['species_index']], 'policy': SPECIES_POLICY},
                             level={'source': 'object record byte via wMapSpriteExtraData -> wEngagedTrainerSet -> wCurEnemyLevel',
                                    'rom_offsets': [lv], 'values': [row['level']], 'policy': LEVEL_POLICY})
            sites[row['source_id']] = entry
        assert len(sites) == 14 and sum(row['kind'] == 'script' for row in sites.values()) == 2, (variant, sorted(sites))
        expected_excluded = {'script-battle:ghost-marowak', 'script-battle:unidentified-tower-ghost', 'script-battle:old-man-tutorial'}
        if variant == 'yellow':
            expected_excluded.add('script-battle:oak-pikachu')
        assert set(excluded) == expected_excluded, (variant, sorted(excluded))
        objects = {(row['map_id'], row['object_index']) for row in sites.values() if row['kind'] == 'object'}
        assert len(objects) == 12  # (map, sprite index) names an object static uniquely
        result['titles'][variant] = {
            'source_commit': lock['sources'][source]['commit'],
            'symbols_sha256': hashlib.sha256((repo/(target+'.sym')).read_bytes()).hexdigest(),
            'clean_sha1': lock['clean_roms'][target]['sha1'],
            'addresses': {name: syms[name][1] for name in NAMES},
            'lengths': {'name': 11, 'player_id': 2},
            'constants': {'opp_id_offset': OPP_ID_OFFSET, 'restless_soul': RESTLESS_SOUL, 'max_object_events': MAX_OBJECT_EVENTS,
                          'link_state_battling': LINK_STATE_BATTLING},
            'battle_types': types, 'origin_battle_type': types['BATTLE_TYPE_NORMAL'], 'out_of_battle_flag': 0, 'wild_battle_flag': 1,
            'trainer_battle_flag': 2, 'battle_results': BATTLE_RESULTS,
            'tower_map_ids': tower,
            'init_battle': address(syms['InitBattle']) | {'symbol': 'InitBattle'},
            'began': began, 'object_arm': object_arm, 'battle_end': battle_end,
            'sites': sites, 'excluded': excluded}
    ids = [set(row['sites']) for row in result['titles'].values()]
    assert all(row == ids[0] for row in ids)  # the census ids are already title-neutral
    result['sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    value = build()
    outputs = {OUTPUT: json.dumps(value, indent=2, sort_keys=True)+'\n',
               LUA: '-- Generated by tools/gen_gen1_static_sites.py from pinned source/ROMs.\nreturn '+lua(value)+'\n'}
    if args.check:
        stale = [path.name for path, text in outputs.items() if not path.exists() or path.read_text(encoding='utf-8') != text]
        assert not stale, 'static site data is stale: '+', '.join(stale)
    else:
        for path, text in outputs.items():
            path.write_text(text, encoding='utf-8', newline='\n')
    print('OK: static origin sites', {name: len(row['sites']) for name, row in value['titles'].items()},
          'excluded', {name: len(row['excluded']) for name, row in value['titles'].items()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
