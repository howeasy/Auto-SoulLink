"""Independent English R/B/Y byte oracle, derived from pret, not SLink decoders.

Source citations below are relative to pret/pokered at 405b6246372d7e5a2cb029cbb65219b13286b8c9.
Yellow was checked at 0a0851546ff65f65c4bb2af2b95e279e709a8653. Its record macros,
charmap, dex/growth tables and stat/experience routines agree with Red; only the
WRAM bases below differ. SRAM offsets address a flat four-bank battery image.

Decoding preserves raw record values, including unusual species/status/levels;
it does not certify a legal Pokemon. Collection decoders additionally validate
count, terminator and species-list agreement. Box records have no stored battle
stats: these are None, never invented. Names are English font tokens, not gender
inference. Unknown glyph bytes use reversible <$XX> tokens.
"""

from __future__ import annotations

from math import isqrt

# constants/pokemon_data_constants.asm:28-56; macros/ram.asm:7-36.
# Each tuple is (offset, byte width); words/experience are stored most-significant
# byte first: home/move_mon.asm:39-43; engine/pokemon/experience.asm:11-24.
_FIELDS = {
    "species": (0, 1),       # constants/pokemon_data_constants.asm:28
    "hp": (1, 2),            # constants/pokemon_data_constants.asm:29
    "box_level": (3, 1),     # constants/pokemon_data_constants.asm:30
    "status": (4, 1),        # constants/pokemon_data_constants.asm:31
    "catch_rate": (7, 1),    # constants/pokemon_data_constants.asm:32-36
    "ot_id": (12, 2),        # constants/pokemon_data_constants.asm:37-38
    "exp": (14, 3),          # constants/pokemon_data_constants.asm:39
}
_STAT_EXP = {"hp": 17, "atk": 19, "def": 21, "spd": 23, "spc": 25}
# constants/pokemon_data_constants.asm:40-44 (five consecutive big-endian words).
_STORED_STATS = {"max_hp": 34, "atk": 36, "def": 38, "spd": 40, "spc": 42}
# constants/pokemon_data_constants.asm:48-55 (level at 33, then five words).
PARTY_MON_SIZE, BOX_MON_SIZE = 44, 33  # constants/pokemon_data_constants.asm:47,56
PARTY_CAPACITY, BOX_CAPACITY, BOX_COUNT = 6, 20, 12
# constants/pokemon_data_constants.asm:58-61.
NAME_SIZE = 11  # constants/text_constants.asm:3
NAME_END = 0x50  # constants/charmap.asm:12
SPECIES_END = 0xFF  # engine/menus/save.asm:568-572
_TYPES = slice(5, 7)  # constants/pokemon_data_constants.asm:32-35
_MOVES = slice(8, 12)  # constants/pokemon_data_constants.asm:37
_DVS = slice(27, 29)  # constants/pokemon_data_constants.asm:45
_PP = slice(29, 33)  # constants/pokemon_data_constants.asm:46
_LEVEL = 33  # constants/pokemon_data_constants.asm:48
_PP_MASK, _PP_UP_SHIFT = 0x3F, 6  # constants/pokemon_data_constants.asm:100-102

# ram/wram.asm:1722-1744 and 2226-2248; Yellow ram/wram.asm:1903-1925,2491-2513.
# The species array has capacity + 1 bytes, following a one-byte count.
PARTY_LAYOUT = {"count": 0, "species": 1, "mons": 8, "ot_names": 272,
                "nicknames": 338, "size": 404}
BOX_LAYOUT = {"count": 0, "species": 1, "mons": 22, "ot_names": 682,
              "nicknames": 902, "size": 1122}
BOX_SIZE = BOX_LAYOUT["size"]

# Linked placement: layout.link:180-202, ram/wram.asm:1718-1744,2222-2248.
# pokered.sym:18984,18989,19145,19152,19159,19616;
# pokeyellow.sym:22212,22217,22373,22380,22387,22902.
WRAM_BASES = {
    "red": {"party": 0xD163, "box": 0xDA80},
    "blue": {"party": 0xD163, "box": 0xDA80},
    "yellow": {"party": 0xD162, "box": 0xDA7F},
}
# ram/sram.asm:12-24,37-49 and layout.link:197-202; linked symbols:
# pokered.sym:17398-17421, pokeyellow.sym:20339-20362. These are IDENTICAL in R/B/Y.
SRAM_LAYOUT = {
    "sPlayerName": 0x2598, "sMainData": 0x25A3, "sSpriteData": 0x2D2C,
    "sPartyData": 0x2F2C, "sCurBoxData": 0x30C0, "sTileAnimations": 0x3522,
    "sMainDataCheckSum": 0x3523,
    "box_banks": (0x4000, 0x6000), "all_boxes_checksums": (0x5A4C, 0x7A4C),
    "individual_checksums": (0x5A4D, 0x7A4D),
}
SRAM_SIZE = 0x8000  # layout.link:195-202: four SRAM banks, $a000-$bfff per bank
# sMainData + (wCurrentBoxNum - wMainDataStart): ram/sram.asm:18;
# ram/wram.asm:1749,1897-1899; pokered.sym:19158,19259; Yellow:22386,22543.
_CURRENT_BOX = 0x284C
_BOX_INITIALIZED = 0x80  # constants/ram_constants.asm:50-52

# Generated from the cited English charmap rows; alternate graphics modes are
# deliberately excluded (constants/charmap.asm:65-88,199-386).
_CHARMAP = {
    0x00: '<NULL>',  # constants/charmap.asm:5
    0x49: '<PAGE>',  # constants/charmap.asm:6
    0x4A: '<PKMN>',  # constants/charmap.asm:7
    0x4B: '<_CONT>',  # constants/charmap.asm:8
    0x4C: '<SCROLL>',  # constants/charmap.asm:9
    0x4E: '<NEXT>',  # constants/charmap.asm:10
    0x4F: '<LINE>',  # constants/charmap.asm:11
    0x51: '<PARA>',  # constants/charmap.asm:13
    0x52: '<PLAYER>',  # constants/charmap.asm:14
    0x53: '<RIVAL>',  # constants/charmap.asm:15
    0x54: '#',  # constants/charmap.asm:16
    0x55: '<CONT>',  # constants/charmap.asm:17
    0x56: '<……>',  # constants/charmap.asm:18
    0x57: '<DONE>',  # constants/charmap.asm:19
    0x58: '<PROMPT>',  # constants/charmap.asm:20
    0x59: '<TARGET>',  # constants/charmap.asm:21
    0x5A: '<USER>',  # constants/charmap.asm:22
    0x5B: '<PC>',  # constants/charmap.asm:23
    0x5C: '<TM>',  # constants/charmap.asm:24
    0x5D: '<TRAINER>',  # constants/charmap.asm:25
    0x5E: '<ROCKET>',  # constants/charmap.asm:26
    0x5F: '<DEXEND>',  # constants/charmap.asm:27
    0x60: '<BOLD_A>',  # constants/charmap.asm:31
    0x61: '<BOLD_B>',  # constants/charmap.asm:32
    0x62: '<BOLD_C>',  # constants/charmap.asm:33
    0x63: '<BOLD_D>',  # constants/charmap.asm:34
    0x64: '<BOLD_E>',  # constants/charmap.asm:35
    0x65: '<BOLD_F>',  # constants/charmap.asm:36
    0x66: '<BOLD_G>',  # constants/charmap.asm:37
    0x67: '<BOLD_H>',  # constants/charmap.asm:38
    0x68: '<BOLD_I>',  # constants/charmap.asm:39
    0x69: '<BOLD_V>',  # constants/charmap.asm:40
    0x6A: '<BOLD_S>',  # constants/charmap.asm:41
    0x6B: '<BOLD_L>',  # constants/charmap.asm:42
    0x6C: '<BOLD_M>',  # constants/charmap.asm:43
    0x6D: '<COLON>',  # constants/charmap.asm:44
    0x6E: 'ぃ',  # constants/charmap.asm:45
    0x6F: 'ぅ',  # constants/charmap.asm:46
    0x70: '‘',  # constants/charmap.asm:47
    0x71: '’',  # constants/charmap.asm:48
    0x72: '“',  # constants/charmap.asm:49
    0x73: '”',  # constants/charmap.asm:50
    0x74: '·',  # constants/charmap.asm:51
    0x75: '…',  # constants/charmap.asm:52
    0x76: 'ぁ',  # constants/charmap.asm:53
    0x77: 'ぇ',  # constants/charmap.asm:54
    0x78: 'ぉ',  # constants/charmap.asm:55
    0x79: '┌',  # constants/charmap.asm:57
    0x7A: '─',  # constants/charmap.asm:58
    0x7B: '┐',  # constants/charmap.asm:59
    0x7C: '│',  # constants/charmap.asm:60
    0x7D: '└',  # constants/charmap.asm:61
    0x7E: '┘',  # constants/charmap.asm:62
    0x7F: ' ',  # constants/charmap.asm:63
    0x80: 'A',  # constants/charmap.asm:92
    0x81: 'B',  # constants/charmap.asm:93
    0x82: 'C',  # constants/charmap.asm:94
    0x83: 'D',  # constants/charmap.asm:95
    0x84: 'E',  # constants/charmap.asm:96
    0x85: 'F',  # constants/charmap.asm:97
    0x86: 'G',  # constants/charmap.asm:98
    0x87: 'H',  # constants/charmap.asm:99
    0x88: 'I',  # constants/charmap.asm:100
    0x89: 'J',  # constants/charmap.asm:101
    0x8A: 'K',  # constants/charmap.asm:102
    0x8B: 'L',  # constants/charmap.asm:103
    0x8C: 'M',  # constants/charmap.asm:104
    0x8D: 'N',  # constants/charmap.asm:105
    0x8E: 'O',  # constants/charmap.asm:106
    0x8F: 'P',  # constants/charmap.asm:107
    0x90: 'Q',  # constants/charmap.asm:108
    0x91: 'R',  # constants/charmap.asm:109
    0x92: 'S',  # constants/charmap.asm:110
    0x93: 'T',  # constants/charmap.asm:111
    0x94: 'U',  # constants/charmap.asm:112
    0x95: 'V',  # constants/charmap.asm:113
    0x96: 'W',  # constants/charmap.asm:114
    0x97: 'X',  # constants/charmap.asm:115
    0x98: 'Y',  # constants/charmap.asm:116
    0x99: 'Z',  # constants/charmap.asm:117
    0x9A: '(',  # constants/charmap.asm:119
    0x9B: ')',  # constants/charmap.asm:120
    0x9C: ':',  # constants/charmap.asm:121
    0x9D: ';',  # constants/charmap.asm:122
    0x9E: '[',  # constants/charmap.asm:123
    0x9F: ']',  # constants/charmap.asm:124
    0xA0: 'a',  # constants/charmap.asm:126
    0xA1: 'b',  # constants/charmap.asm:127
    0xA2: 'c',  # constants/charmap.asm:128
    0xA3: 'd',  # constants/charmap.asm:129
    0xA4: 'e',  # constants/charmap.asm:130
    0xA5: 'f',  # constants/charmap.asm:131
    0xA6: 'g',  # constants/charmap.asm:132
    0xA7: 'h',  # constants/charmap.asm:133
    0xA8: 'i',  # constants/charmap.asm:134
    0xA9: 'j',  # constants/charmap.asm:135
    0xAA: 'k',  # constants/charmap.asm:136
    0xAB: 'l',  # constants/charmap.asm:137
    0xAC: 'm',  # constants/charmap.asm:138
    0xAD: 'n',  # constants/charmap.asm:139
    0xAE: 'o',  # constants/charmap.asm:140
    0xAF: 'p',  # constants/charmap.asm:141
    0xB0: 'q',  # constants/charmap.asm:142
    0xB1: 'r',  # constants/charmap.asm:143
    0xB2: 's',  # constants/charmap.asm:144
    0xB3: 't',  # constants/charmap.asm:145
    0xB4: 'u',  # constants/charmap.asm:146
    0xB5: 'v',  # constants/charmap.asm:147
    0xB6: 'w',  # constants/charmap.asm:148
    0xB7: 'x',  # constants/charmap.asm:149
    0xB8: 'y',  # constants/charmap.asm:150
    0xB9: 'z',  # constants/charmap.asm:151
    0xBA: 'é',  # constants/charmap.asm:153
    0xBB: "'d",  # constants/charmap.asm:154
    0xBC: "'l",  # constants/charmap.asm:155
    0xBD: "'s",  # constants/charmap.asm:156
    0xBE: "'t",  # constants/charmap.asm:157
    0xBF: "'v",  # constants/charmap.asm:158
    0xE0: "'",  # constants/charmap.asm:160
    0xE1: '<PK>',  # constants/charmap.asm:161
    0xE2: '<MN>',  # constants/charmap.asm:162
    0xE3: '-',  # constants/charmap.asm:163
    0xE4: "'r",  # constants/charmap.asm:165
    0xE5: "'m",  # constants/charmap.asm:166
    0xE6: '?',  # constants/charmap.asm:168
    0xE7: '!',  # constants/charmap.asm:169
    0xE8: '.',  # constants/charmap.asm:170
    0xE9: 'ァ',  # constants/charmap.asm:172
    0xEA: 'ゥ',  # constants/charmap.asm:173
    0xEB: 'ェ',  # constants/charmap.asm:174
    0xEC: '▷',  # constants/charmap.asm:176
    0xED: '▶',  # constants/charmap.asm:177
    0xEE: '▼',  # constants/charmap.asm:178
    0xEF: '♂',  # constants/charmap.asm:179
    0xF0: '¥',  # constants/charmap.asm:180
    0xF1: '×',  # constants/charmap.asm:181
    0xF2: '<DOT>',  # constants/charmap.asm:182
    0xF3: '/',  # constants/charmap.asm:183
    0xF4: ',',  # constants/charmap.asm:184
    0xF5: '♀',  # constants/charmap.asm:185
    0xF6: '0',  # constants/charmap.asm:187
    0xF7: '1',  # constants/charmap.asm:188
    0xF8: '2',  # constants/charmap.asm:189
    0xF9: '3',  # constants/charmap.asm:190
    0xFA: '4',  # constants/charmap.asm:191
    0xFB: '5',  # constants/charmap.asm:192
    0xFC: '6',  # constants/charmap.asm:193
    0xFD: '7',  # constants/charmap.asm:194
    0xFE: '8',  # constants/charmap.asm:195
    0xFF: '9',  # constants/charmap.asm:196
}
_ENCODE_CHARS = {text: byte for byte, text in _CHARMAP.items()}
_NAME_TOKENS = sorted(_ENCODE_CHARS, key=len, reverse=True)

# Generated from data/pokemon/dex_order.asm:3-192 and the DEX_* definitions in
# constants/pokedex_constants.asm:6-157. Zero entries represent MissingNo holes.
_DEX_ORDER = (
    112,  # data/pokemon/dex_order.asm:3; constants/pokedex_constants.asm:118
    115,  # data/pokemon/dex_order.asm:4; constants/pokedex_constants.asm:121
    32,  # data/pokemon/dex_order.asm:5; constants/pokedex_constants.asm:38
    35,  # data/pokemon/dex_order.asm:6; constants/pokedex_constants.asm:41
    21,  # data/pokemon/dex_order.asm:7; constants/pokedex_constants.asm:27
    100,  # data/pokemon/dex_order.asm:8; constants/pokedex_constants.asm:106
    34,  # data/pokemon/dex_order.asm:9; constants/pokedex_constants.asm:40
    80,  # data/pokemon/dex_order.asm:10; constants/pokedex_constants.asm:86
    2,  # data/pokemon/dex_order.asm:11; constants/pokedex_constants.asm:8
    103,  # data/pokemon/dex_order.asm:12; constants/pokedex_constants.asm:109
    108,  # data/pokemon/dex_order.asm:13; constants/pokedex_constants.asm:114
    102,  # data/pokemon/dex_order.asm:14; constants/pokedex_constants.asm:108
    88,  # data/pokemon/dex_order.asm:15; constants/pokedex_constants.asm:94
    94,  # data/pokemon/dex_order.asm:16; constants/pokedex_constants.asm:100
    29,  # data/pokemon/dex_order.asm:17; constants/pokedex_constants.asm:35
    31,  # data/pokemon/dex_order.asm:18; constants/pokedex_constants.asm:37
    104,  # data/pokemon/dex_order.asm:19; constants/pokedex_constants.asm:110
    111,  # data/pokemon/dex_order.asm:20; constants/pokedex_constants.asm:117
    131,  # data/pokemon/dex_order.asm:21; constants/pokedex_constants.asm:137
    59,  # data/pokemon/dex_order.asm:22; constants/pokedex_constants.asm:65
    151,  # data/pokemon/dex_order.asm:23; constants/pokedex_constants.asm:157
    130,  # data/pokemon/dex_order.asm:24; constants/pokedex_constants.asm:136
    90,  # data/pokemon/dex_order.asm:25; constants/pokedex_constants.asm:96
    72,  # data/pokemon/dex_order.asm:26; constants/pokedex_constants.asm:78
    92,  # data/pokemon/dex_order.asm:27; constants/pokedex_constants.asm:98
    123,  # data/pokemon/dex_order.asm:28; constants/pokedex_constants.asm:129
    120,  # data/pokemon/dex_order.asm:29; constants/pokedex_constants.asm:126
    9,  # data/pokemon/dex_order.asm:30; constants/pokedex_constants.asm:15
    127,  # data/pokemon/dex_order.asm:31; constants/pokedex_constants.asm:133
    114,  # data/pokemon/dex_order.asm:32; constants/pokedex_constants.asm:120
    0,  # data/pokemon/dex_order.asm:33
    0,  # data/pokemon/dex_order.asm:34
    58,  # data/pokemon/dex_order.asm:35; constants/pokedex_constants.asm:64
    95,  # data/pokemon/dex_order.asm:36; constants/pokedex_constants.asm:101
    22,  # data/pokemon/dex_order.asm:37; constants/pokedex_constants.asm:28
    16,  # data/pokemon/dex_order.asm:38; constants/pokedex_constants.asm:22
    79,  # data/pokemon/dex_order.asm:39; constants/pokedex_constants.asm:85
    64,  # data/pokemon/dex_order.asm:40; constants/pokedex_constants.asm:70
    75,  # data/pokemon/dex_order.asm:41; constants/pokedex_constants.asm:81
    113,  # data/pokemon/dex_order.asm:42; constants/pokedex_constants.asm:119
    67,  # data/pokemon/dex_order.asm:43; constants/pokedex_constants.asm:73
    122,  # data/pokemon/dex_order.asm:44; constants/pokedex_constants.asm:128
    106,  # data/pokemon/dex_order.asm:45; constants/pokedex_constants.asm:112
    107,  # data/pokemon/dex_order.asm:46; constants/pokedex_constants.asm:113
    24,  # data/pokemon/dex_order.asm:47; constants/pokedex_constants.asm:30
    47,  # data/pokemon/dex_order.asm:48; constants/pokedex_constants.asm:53
    54,  # data/pokemon/dex_order.asm:49; constants/pokedex_constants.asm:60
    96,  # data/pokemon/dex_order.asm:50; constants/pokedex_constants.asm:102
    76,  # data/pokemon/dex_order.asm:51; constants/pokedex_constants.asm:82
    0,  # data/pokemon/dex_order.asm:52
    126,  # data/pokemon/dex_order.asm:53; constants/pokedex_constants.asm:132
    0,  # data/pokemon/dex_order.asm:54
    125,  # data/pokemon/dex_order.asm:55; constants/pokedex_constants.asm:131
    82,  # data/pokemon/dex_order.asm:56; constants/pokedex_constants.asm:88
    109,  # data/pokemon/dex_order.asm:57; constants/pokedex_constants.asm:115
    0,  # data/pokemon/dex_order.asm:58
    56,  # data/pokemon/dex_order.asm:59; constants/pokedex_constants.asm:62
    86,  # data/pokemon/dex_order.asm:60; constants/pokedex_constants.asm:92
    50,  # data/pokemon/dex_order.asm:61; constants/pokedex_constants.asm:56
    128,  # data/pokemon/dex_order.asm:62; constants/pokedex_constants.asm:134
    0,  # data/pokemon/dex_order.asm:63
    0,  # data/pokemon/dex_order.asm:64
    0,  # data/pokemon/dex_order.asm:65
    83,  # data/pokemon/dex_order.asm:66; constants/pokedex_constants.asm:89
    48,  # data/pokemon/dex_order.asm:67; constants/pokedex_constants.asm:54
    149,  # data/pokemon/dex_order.asm:68; constants/pokedex_constants.asm:155
    0,  # data/pokemon/dex_order.asm:69
    0,  # data/pokemon/dex_order.asm:70
    0,  # data/pokemon/dex_order.asm:71
    84,  # data/pokemon/dex_order.asm:72; constants/pokedex_constants.asm:90
    60,  # data/pokemon/dex_order.asm:73; constants/pokedex_constants.asm:66
    124,  # data/pokemon/dex_order.asm:74; constants/pokedex_constants.asm:130
    146,  # data/pokemon/dex_order.asm:75; constants/pokedex_constants.asm:152
    144,  # data/pokemon/dex_order.asm:76; constants/pokedex_constants.asm:150
    145,  # data/pokemon/dex_order.asm:77; constants/pokedex_constants.asm:151
    132,  # data/pokemon/dex_order.asm:78; constants/pokedex_constants.asm:138
    52,  # data/pokemon/dex_order.asm:79; constants/pokedex_constants.asm:58
    98,  # data/pokemon/dex_order.asm:80; constants/pokedex_constants.asm:104
    0,  # data/pokemon/dex_order.asm:81
    0,  # data/pokemon/dex_order.asm:82
    0,  # data/pokemon/dex_order.asm:83
    37,  # data/pokemon/dex_order.asm:84; constants/pokedex_constants.asm:43
    38,  # data/pokemon/dex_order.asm:85; constants/pokedex_constants.asm:44
    25,  # data/pokemon/dex_order.asm:86; constants/pokedex_constants.asm:31
    26,  # data/pokemon/dex_order.asm:87; constants/pokedex_constants.asm:32
    0,  # data/pokemon/dex_order.asm:88
    0,  # data/pokemon/dex_order.asm:89
    147,  # data/pokemon/dex_order.asm:90; constants/pokedex_constants.asm:153
    148,  # data/pokemon/dex_order.asm:91; constants/pokedex_constants.asm:154
    140,  # data/pokemon/dex_order.asm:92; constants/pokedex_constants.asm:146
    141,  # data/pokemon/dex_order.asm:93; constants/pokedex_constants.asm:147
    116,  # data/pokemon/dex_order.asm:94; constants/pokedex_constants.asm:122
    117,  # data/pokemon/dex_order.asm:95; constants/pokedex_constants.asm:123
    0,  # data/pokemon/dex_order.asm:96
    0,  # data/pokemon/dex_order.asm:97
    27,  # data/pokemon/dex_order.asm:98; constants/pokedex_constants.asm:33
    28,  # data/pokemon/dex_order.asm:99; constants/pokedex_constants.asm:34
    138,  # data/pokemon/dex_order.asm:100; constants/pokedex_constants.asm:144
    139,  # data/pokemon/dex_order.asm:101; constants/pokedex_constants.asm:145
    39,  # data/pokemon/dex_order.asm:102; constants/pokedex_constants.asm:45
    40,  # data/pokemon/dex_order.asm:103; constants/pokedex_constants.asm:46
    133,  # data/pokemon/dex_order.asm:104; constants/pokedex_constants.asm:139
    136,  # data/pokemon/dex_order.asm:105; constants/pokedex_constants.asm:142
    135,  # data/pokemon/dex_order.asm:106; constants/pokedex_constants.asm:141
    134,  # data/pokemon/dex_order.asm:107; constants/pokedex_constants.asm:140
    66,  # data/pokemon/dex_order.asm:108; constants/pokedex_constants.asm:72
    41,  # data/pokemon/dex_order.asm:109; constants/pokedex_constants.asm:47
    23,  # data/pokemon/dex_order.asm:110; constants/pokedex_constants.asm:29
    46,  # data/pokemon/dex_order.asm:111; constants/pokedex_constants.asm:52
    61,  # data/pokemon/dex_order.asm:112; constants/pokedex_constants.asm:67
    62,  # data/pokemon/dex_order.asm:113; constants/pokedex_constants.asm:68
    13,  # data/pokemon/dex_order.asm:114; constants/pokedex_constants.asm:19
    14,  # data/pokemon/dex_order.asm:115; constants/pokedex_constants.asm:20
    15,  # data/pokemon/dex_order.asm:116; constants/pokedex_constants.asm:21
    0,  # data/pokemon/dex_order.asm:117
    85,  # data/pokemon/dex_order.asm:118; constants/pokedex_constants.asm:91
    57,  # data/pokemon/dex_order.asm:119; constants/pokedex_constants.asm:63
    51,  # data/pokemon/dex_order.asm:120; constants/pokedex_constants.asm:57
    49,  # data/pokemon/dex_order.asm:121; constants/pokedex_constants.asm:55
    87,  # data/pokemon/dex_order.asm:122; constants/pokedex_constants.asm:93
    0,  # data/pokemon/dex_order.asm:123
    0,  # data/pokemon/dex_order.asm:124
    10,  # data/pokemon/dex_order.asm:125; constants/pokedex_constants.asm:16
    11,  # data/pokemon/dex_order.asm:126; constants/pokedex_constants.asm:17
    12,  # data/pokemon/dex_order.asm:127; constants/pokedex_constants.asm:18
    68,  # data/pokemon/dex_order.asm:128; constants/pokedex_constants.asm:74
    0,  # data/pokemon/dex_order.asm:129
    55,  # data/pokemon/dex_order.asm:130; constants/pokedex_constants.asm:61
    97,  # data/pokemon/dex_order.asm:131; constants/pokedex_constants.asm:103
    42,  # data/pokemon/dex_order.asm:132; constants/pokedex_constants.asm:48
    150,  # data/pokemon/dex_order.asm:133; constants/pokedex_constants.asm:156
    143,  # data/pokemon/dex_order.asm:134; constants/pokedex_constants.asm:149
    129,  # data/pokemon/dex_order.asm:135; constants/pokedex_constants.asm:135
    0,  # data/pokemon/dex_order.asm:136
    0,  # data/pokemon/dex_order.asm:137
    89,  # data/pokemon/dex_order.asm:138; constants/pokedex_constants.asm:95
    0,  # data/pokemon/dex_order.asm:139
    99,  # data/pokemon/dex_order.asm:140; constants/pokedex_constants.asm:105
    91,  # data/pokemon/dex_order.asm:141; constants/pokedex_constants.asm:97
    0,  # data/pokemon/dex_order.asm:142
    101,  # data/pokemon/dex_order.asm:143; constants/pokedex_constants.asm:107
    36,  # data/pokemon/dex_order.asm:144; constants/pokedex_constants.asm:42
    110,  # data/pokemon/dex_order.asm:145; constants/pokedex_constants.asm:116
    53,  # data/pokemon/dex_order.asm:146; constants/pokedex_constants.asm:59
    105,  # data/pokemon/dex_order.asm:147; constants/pokedex_constants.asm:111
    0,  # data/pokemon/dex_order.asm:148
    93,  # data/pokemon/dex_order.asm:149; constants/pokedex_constants.asm:99
    63,  # data/pokemon/dex_order.asm:150; constants/pokedex_constants.asm:69
    65,  # data/pokemon/dex_order.asm:151; constants/pokedex_constants.asm:71
    17,  # data/pokemon/dex_order.asm:152; constants/pokedex_constants.asm:23
    18,  # data/pokemon/dex_order.asm:153; constants/pokedex_constants.asm:24
    121,  # data/pokemon/dex_order.asm:154; constants/pokedex_constants.asm:127
    1,  # data/pokemon/dex_order.asm:155; constants/pokedex_constants.asm:7
    3,  # data/pokemon/dex_order.asm:156; constants/pokedex_constants.asm:9
    73,  # data/pokemon/dex_order.asm:157; constants/pokedex_constants.asm:79
    0,  # data/pokemon/dex_order.asm:158
    118,  # data/pokemon/dex_order.asm:159; constants/pokedex_constants.asm:124
    119,  # data/pokemon/dex_order.asm:160; constants/pokedex_constants.asm:125
    0,  # data/pokemon/dex_order.asm:161
    0,  # data/pokemon/dex_order.asm:162
    0,  # data/pokemon/dex_order.asm:163
    0,  # data/pokemon/dex_order.asm:164
    77,  # data/pokemon/dex_order.asm:165; constants/pokedex_constants.asm:83
    78,  # data/pokemon/dex_order.asm:166; constants/pokedex_constants.asm:84
    19,  # data/pokemon/dex_order.asm:167; constants/pokedex_constants.asm:25
    20,  # data/pokemon/dex_order.asm:168; constants/pokedex_constants.asm:26
    33,  # data/pokemon/dex_order.asm:169; constants/pokedex_constants.asm:39
    30,  # data/pokemon/dex_order.asm:170; constants/pokedex_constants.asm:36
    74,  # data/pokemon/dex_order.asm:171; constants/pokedex_constants.asm:80
    137,  # data/pokemon/dex_order.asm:172; constants/pokedex_constants.asm:143
    142,  # data/pokemon/dex_order.asm:173; constants/pokedex_constants.asm:148
    0,  # data/pokemon/dex_order.asm:174
    81,  # data/pokemon/dex_order.asm:175; constants/pokedex_constants.asm:87
    0,  # data/pokemon/dex_order.asm:176
    0,  # data/pokemon/dex_order.asm:177
    4,  # data/pokemon/dex_order.asm:178; constants/pokedex_constants.asm:10
    7,  # data/pokemon/dex_order.asm:179; constants/pokedex_constants.asm:13
    5,  # data/pokemon/dex_order.asm:180; constants/pokedex_constants.asm:11
    8,  # data/pokemon/dex_order.asm:181; constants/pokedex_constants.asm:14
    6,  # data/pokemon/dex_order.asm:182; constants/pokedex_constants.asm:12
    0,  # data/pokemon/dex_order.asm:183
    0,  # data/pokemon/dex_order.asm:184
    0,  # data/pokemon/dex_order.asm:185
    0,  # data/pokemon/dex_order.asm:186
    43,  # data/pokemon/dex_order.asm:187; constants/pokedex_constants.asm:49
    44,  # data/pokemon/dex_order.asm:188; constants/pokedex_constants.asm:50
    45,  # data/pokemon/dex_order.asm:189; constants/pokedex_constants.asm:51
    69,  # data/pokemon/dex_order.asm:190; constants/pokedex_constants.asm:75
    70,  # data/pokemon/dex_order.asm:191; constants/pokedex_constants.asm:76
    71,  # data/pokemon/dex_order.asm:192; constants/pokedex_constants.asm:77
)
_NATDEX_TO_INTERNAL = {dex: idx for idx, dex in enumerate(_DEX_ORDER, 1) if dex}


def _uint(value: int, bits: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 1 << bits:
        raise ValueError(f"{label} must be an unsigned {bits}-bit integer")
    return value


def _dv_parts(raw: int) -> dict:
    # home/move_mon.asm:109-153: A/D/S/S nibbles, HP from their low bits.
    parts = {stat: (raw >> shift) & 0xF
             for stat, shift in zip(("atk", "def", "spd", "spc"), (12, 8, 4, 0), strict=True)}
    parts["hp"] = sum((parts[stat] & 1) << shift
                      for stat, shift in zip(("atk", "def", "spd", "spc"), (3, 2, 1, 0), strict=True))
    return {"raw": raw, **parts}


def decode_party_mon(b: bytes, *, box: bool = False) -> dict:
    """Decode exactly 44/33 bytes; dvs={raw,atk,def,spd,spc,hp}.

    ``box_level`` preserves byte 3. ``level`` is byte 33 for party records,
    otherwise byte 3. ``box`` records the format for encode_party_mon().
    ``pp`` is remaining PP; ``pp_ups`` is the four two-bit usage counts.
    """
    size = BOX_MON_SIZE if box else PARTY_MON_SIZE
    if len(b) != size:
        raise ValueError(f"expected exactly {size} mon bytes, got {len(b)}")
    result = {name: int.from_bytes(b[offset:offset + width], "big")
              for name, (offset, width) in _FIELDS.items()}
    result.update({
        "box": box, "level": result["box_level"] if box else b[_LEVEL],
        "types": list(b[_TYPES]), "moves": list(b[_MOVES]),
        "stat_exp": {name: int.from_bytes(b[offset:offset + 2], "big")
                     for name, offset in _STAT_EXP.items()},
        "dvs": _dv_parts(int.from_bytes(b[_DVS], "big")),
        "pp": [value & _PP_MASK for value in b[_PP]],
        "pp_ups": [value >> _PP_UP_SHIFT for value in b[_PP]],
    })
    result.update({name: None if box else int.from_bytes(b[offset:offset + 2], "big")
                   for name, offset in _STORED_STATS.items()})
    return result


def encode_party_mon(d: dict) -> bytes:
    """Inverse of decode_party_mon; reject out-of-range or contradictory fields.

    Derived DV nibbles must agree with dvs.raw; update them together when editing.
    A box's level must agree with box_level and its absent stats must remain None.
    Collection metadata (names/species_list_entry) is ignored.
    """
    box = d["box"]
    if not isinstance(box, bool):
        raise ValueError("box must be bool")
    b = bytearray(BOX_MON_SIZE if box else PARTY_MON_SIZE)

    def put(offset: int, width: int, value: int, label: str) -> None:
        b[offset:offset + width] = _uint(value, width * 8, label).to_bytes(width, "big")

    for name, (offset, width) in _FIELDS.items():
        put(offset, width, d[name], name)
    for name, span in (("types", _TYPES), ("moves", _MOVES)):
        values = d[name]
        if len(values) != span.stop - span.start:
            raise ValueError(f"wrong number of {name}")
        b[span] = bytes(_uint(v, 8, name) for v in values)
    for name, offset in _STAT_EXP.items():
        put(offset, 2, d["stat_exp"][name], f"stat_exp.{name}")
    raw = _uint(d["dvs"]["raw"], 16, "dvs.raw")
    if d["dvs"] != _dv_parts(raw):
        raise ValueError("DV nibbles disagree with dvs.raw")
    put(_DVS.start, 2, raw, "dvs.raw")
    if len(d["pp"]) != 4 or len(d["pp_ups"]) != 4:
        raise ValueError("pp and pp_ups must each contain four entries")
    b[_PP] = bytes(_uint(pp, 6, "pp") | (_uint(ups, 2, "pp_ups") << _PP_UP_SHIFT)
                   for pp, ups in zip(d["pp"], d["pp_ups"], strict=True))
    if box:
        if d["level"] != d["box_level"] or any(d[name] is not None for name in _STORED_STATS):
            raise ValueError("box level disagrees or box contains party-only stats")
    else:
        put(_LEVEL, 1, d["level"], "level")
        for name, offset in _STORED_STATS.items():
            put(offset, 2, d[name], name)
    return bytes(b)


def decode_name(b: bytes) -> str:
    """Decode up to 11 bytes, stopping at @; retain spaces and <PK>/<MN> tokens.

    No font-mode/gender inference. Bytes without an English glyph are <$XX>.
    Padding after the terminator is not part of the returned display name.
    """
    if len(b) > NAME_SIZE:
        raise ValueError("name field exceeds 11 bytes")
    return "".join(_CHARMAP.get(value, f"<${value:02X}>")
                   for value in b.split(bytes([NAME_END]), 1)[0])


def encode_name(name: str) -> bytes:
    """Encode English glyph tokens to 11 bytes, padding with @ (maximum 10 glyphs).

    An explicit @ terminates the input. Multi-letter tokens count as one byte.
    Unknown characters raise ValueError; no lossy substitutions or truncation.
    """
    name = name.split("@", 1)[0]
    out = bytearray()
    while name:
        if name.startswith("<$") and len(name) >= 5 and name[4] == ">":
            try:
                value = int(name[2:4], 16)
            except ValueError:
                raise ValueError(f"invalid byte escape: {name[:5]}") from None
            if value == NAME_END:
                raise ValueError("use @ for the name terminator")
            token = name[:5]
        else:
            token = next((t for t in _NAME_TOKENS if name.startswith(t)), None)
            if token is None:
                raise ValueError(f"unsupported name character: {name[0]!r}")
            value = _ENCODE_CHARS[token]
        out.append(value)
        name = name[len(token):]
    if len(out) >= NAME_SIZE:
        raise ValueError("name exceeds ten glyphs plus terminator")
    return bytes(out) + bytes([NAME_END]) * (NAME_SIZE - len(out))


def _decode_collection(b: bytes, *, box: bool) -> list[dict]:
    layout = BOX_LAYOUT if box else PARTY_LAYOUT
    capacity, stride = (BOX_CAPACITY, BOX_MON_SIZE) if box else (PARTY_CAPACITY, PARTY_MON_SIZE)
    if len(b) != layout["size"]:
        raise ValueError(f"expected exactly {layout['size']} collection bytes, got {len(b)}")
    count = b[layout["count"]]
    if count > capacity:
        raise ValueError(f"count {count} exceeds capacity {capacity}")
    if b[layout["species"] + count] != SPECIES_END:
        raise ValueError("missing species-list terminator at count + 1")
    result = []
    for slot in range(count):
        offset = layout["mons"] + slot * stride
        mon = decode_party_mon(b[offset:offset + stride], box=box)
        listed = b[layout["species"] + slot]
        if listed == SPECIES_END or listed != mon["species"]:
            raise ValueError(f"species-list mismatch in slot {slot + 1}")
        if listed == 0:
            # species 0 is not a Pokemon (constants/pokemon_constants.asm starts at 1); a zero
            # inside the count is a torn or uninitialised list, refused like the Lua reader does
            raise ValueError(f"species 0 inside the count in slot {slot + 1}")
        mon["species_list_entry"] = listed
        for key, block in (("ot_name", "ot_names"), ("nickname", "nicknames")):
            start = layout[block] + slot * NAME_SIZE
            mon[key + "_bytes"] = bytes(b[start:start + NAME_SIZE])
            mon[key] = decode_name(mon[key + "_bytes"])
        result.append(mon)
    return result


def decode_party(wram_slice: bytes) -> list[dict]:
    """404 bytes from wPartyCount: count@0, species@1, structs@8, OT@272, nicks@338.

    R/B: D163,D164,D16B,D273,D2B5, end D2F7 (exclusive).
    Yellow: D162,D163,D16A,D272,D2B4, end D2F6 (exclusive).
    Sources/linked symbol lines are cited at PARTY_LAYOUT and WRAM_BASES.
    """
    return _decode_collection(wram_slice, box=False)


def decode_box(sram_box_bytes: bytes) -> list[dict]:
    """1122 bytes: count@0, species@1, structs@22, OT@682, nicks@902; R/B/Y identical."""
    return _decode_collection(sram_box_bytes, box=True)


def key(mon: dict) -> str:
    """Gen 1 SLink identity: DDDD:OOOO:SS (raw DVs:OT ID:internal species).

    Matches docs/protocol.md:143-150 (published during CODEC-1) and the
    task's explicit format. Other-gen context: gen3_frlge_client.lua:1086
    uses PID:OTID; that two-component representation is not Gen 1's contract.
    """
    return (f"{_uint(mon['dvs']['raw'], 16, 'dvs.raw'):04X}:"
            f"{_uint(mon['ot_id'], 16, 'ot_id'):04X}:"
            f"{_uint(mon['species'], 8, 'species'):02X}")


def sav_checksum(b: bytes) -> int:
    """Complement of byte sum, modulo 256; empty input gives 0xFF.

    Called CalcCheckSum (not SAVCheckSum) in these pinned pret revisions.
    """
    # engine/menus/save.asm:297-310; pokeyellow/engine/menus/save.asm:281-294.
    return ~sum(b) & 0xFF


def verify_bank1(sram: bytes) -> bool:
    """Check sPlayerName through sTileAnimations inclusive in a 32 KiB image.

    Checksum validity alone does not establish semantic validity of the save.
    A truncated/oversized image returns False rather than checking partial data.
    """
    if len(sram) != SRAM_SIZE:
        return False
    # engine/menus/save.asm:281-284; ram/sram.asm:16-24.
    start, end = SRAM_LAYOUT["sPlayerName"], SRAM_LAYOUT["sMainDataCheckSum"]
    return sav_checksum(sram[start:end]) == sram[end]


def verify_boxes(sram: bytes) -> dict:
    """Report all 12 raw individual checksums and both whole-bank checksums.

    ``boxes`` maps 1..12 to count, populated, initialized, stored, calculated,
    valid and offset. ``banks`` maps 2/3 to stored/calculated/valid.
    Raw ``valid`` is always the actual checksum comparison, even for unused
    banks. ``initialized`` comes from the saved has-changed-boxes bit; False
    does NOT turn a checksum mismatch into a success. ``populated`` is None
    before initialization, otherwise count > 0 (including malformed counts).
    The active box in sCurBoxData is covered by verify_bank1, not these banks.
    """
    if len(sram) != SRAM_SIZE:
        raise ValueError(f"expected exactly {SRAM_SIZE} SRAM bytes")
    # engine/menus/save.asm:365-367,529-565: first box change initializes banks.
    initialized = bool(sram[_CURRENT_BOX] & _BOX_INITIALIZED)
    boxes, banks = {}, {}
    for bank_index, start in enumerate(SRAM_LAYOUT["box_banks"]):
        bank = bank_index + 2  # layout.link:199-202
        end = SRAM_LAYOUT["all_boxes_checksums"][bank_index]
        calculated = sav_checksum(sram[start:end])
        stored = sram[end]
        banks[bank] = {"stored": stored, "calculated": calculated, "valid": stored == calculated}
        # ram/sram.asm:39-49; engine/menus/save.asm:312-327,427-431.
        for slot in range(BOX_COUNT // 2):
            offset = start + slot * BOX_SIZE
            calculated = sav_checksum(sram[offset:offset + BOX_SIZE])
            stored = sram[SRAM_LAYOUT["individual_checksums"][bank_index] + slot]
            count = sram[offset]
            boxes[bank_index * (BOX_COUNT // 2) + slot + 1] = {
                "offset": offset, "count": count, "initialized": initialized,
                "populated": bool(count) if initialized else None,
                "stored": stored, "calculated": calculated, "valid": stored == calculated,
            }
    return {"initialized": initialized, "boxes": boxes, "banks": banks}


def calc_stat(base: int, dv: int, stat_exp: int, level: int, *, hp: bool = False) -> int:
    """Pret CalcStat with stat experience enabled, including ceil-sqrt and 999 cap.

    Accepts the engine's full byte-sized level range, including levels over 100.
    """
    _uint(base, 8, "base")
    _uint(dv, 4, "dv")
    _uint(stat_exp, 16, "stat_exp")
    _uint(level, 8, "level")
    # home/move_mon.asm:73-92: first b whose square >= stat_exp, capped at 255.
    root = min(255, isqrt(stat_exp) + (isqrt(stat_exp) ** 2 < stat_exp))
    # home/move_mon.asm:154-212: integer division after level multiplication.
    value = ((base + dv) * 2 + root // 4) * level // 100
    value += level + 10 if hp else 5
    return min(999, value)  # home/move_mon.asm:214-226; constants/battle_constants.asm:69


# data/growth_rates.asm:15-20; indexes constants/pokemon_data_constants.asm:85-94.
GROWTH_RATES = ((1, 1, 0, 0, 0), (3, 4, 10, 0, 30), (3, 4, 20, 0, 70),
                (6, 5, -15, 100, 140), (4, 5, 0, 0, 0), (5, 4, 0, 0, 0))


def exp_for_level(growth_rate: int, level: int) -> int:
    """Pret's 24-bit CalcExperience, including the medium-slow level-1 underflow."""
    _uint(growth_rate, 8, "growth_rate")
    if growth_rate >= len(GROWTH_RATES):
        raise ValueError("growth_rate must be a pret table index 0..5")
    _uint(level, 8, "level")
    a, b, c, d, e = GROWTH_RATES[growth_rate]
    # engine/pokemon/experience.asm:39-58 truncates cubic division BEFORE adding
    # other terms; :59-136 performs the remaining arithmetic in three bytes.
    return (a * level**3 // b + c * level**2 + d * level - e) & 0xFFFFFF


def level_from_exp(growth_rate: int, exp: int) -> int:
    """First failing threshold minus one, as in pret; no invented level-100 clamp.

    CalcLevelFromExperience starts checking at 2, so level-1 underflow is not
    consulted. Inputs that would wrap the engine's level counter raise ValueError
    instead of reproducing its nonterminating loop (corrupt/glitch experience).
    """
    _uint(exp, 24, "exp")
    # engine/pokemon/experience.asm:6-27: 8-bit d starts at 1, increment then compare.
    for level in range(2, 256):
        if exp_for_level(growth_rate, level) > exp:
            return level - 1
    raise ValueError("experience would wrap CalcLevelFromExperience's byte counter")


def internal_to_natdex(idx: int) -> int:
    """Map an internal index 1..190; return zero for a pret MissingNo hole.

    Zero/out-of-range indices raise ValueError (zero is not a table entry).
    """
    if not isinstance(idx, int) or isinstance(idx, bool) or not 1 <= idx <= len(_DEX_ORDER):
        raise ValueError("internal index must be in 1..190")
    return _DEX_ORDER[idx - 1]


def natdex_to_internal(dex: int) -> int:
    """Inverse for dex 1..151; MissingNo has no unique inverse."""
    if not isinstance(dex, int) or isinstance(dex, bool) or dex not in _NATDEX_TO_INTERNAL:
        raise ValueError("national dex must be in 1..151")
    return _NATDEX_TO_INTERNAL[dex]


def recompute_stats(mon: dict, base_stats: dict) -> dict:
    """Rebuild stored stat names from a gen1_rom_scan.scan_base_stats() entry.

    Call scan_base_stats(rom)[internal_to_natdex(mon['species'])] once outside
    this pure oracle. The scanner currently exposes hp/attack/defense/speed/
    special but not growth_rate; supply a verified growth-rate index separately
    to level_from_exp. No ROM tables or scanner implementation are duplicated.
    """
    names = {"hp": ("hp", "max_hp"), "atk": ("attack", "atk"),
             "def": ("defense", "def"), "spd": ("speed", "spd"), "spc": ("special", "spc")}
    return {stored: calc_stat(base_stats[base], mon["dvs"][stat], mon["stat_exp"][stat],
                              mon["level"], hp=stat == "hp")
            for stat, (base, stored) in names.items()}
