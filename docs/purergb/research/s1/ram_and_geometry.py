import json, os
from symtool import Title, TITLES

OUT = os.path.dirname(os.path.abspath(__file__))
titles = {t: Title(t) for t in TITLES}

RAM_SYMS = """wPartyCount wPartySpecies wPartyMons wPartyMonOT wPartyMonNicks
wBoxCount wBoxSpecies wBoxMons wBoxMonOT wBoxMonNicks
wCurrentBoxNum wIsInBattle wBattleType wCurOpponent wEnemyMonSpecies2
wCurEnemyLevel wCurMap wPlayerID wPlayerName wNumBagItems wBagItems
wPocketAbraNick wPlayerMoney wMonDataLocation wWhichPokemon wMoveMonType
wRemoveMonFromBox wCurPartySpecies wLinkState wDayCareMon wDayCareInUse
wUsedItemOnWhichPokemon wSaveFileStatus wOptions wOptions2
wPkmnTypeRemapFlags wSafariType wGameInternalVersion hLoadedROMBank hGBC
sPlayerName sMainData sPartyData sCurBoxData sMainDataCheckSum sBox1
sBox7 sBank2AllBoxesChecksum sBank3AllBoxesChecksum""".split()

ram_table = {}
for sym in RAM_SYMS:
    row = {}
    vals = []
    for t in TITLES:
        v = titles[t].sym.get(sym)
        row[t] = None if v is None else {"bank": v[0], "address": v[1], "hex": f"{v[1]:04X}"}
        vals.append(v)
    row["identical_across_titles"] = (vals[0] == vals[1] == vals[2]) and vals[0] is not None
    row["all_resolved"] = all(v is not None for v in vals)
    ram_table[sym] = row

with open(os.path.join(OUT, "ram_symbols.json"), "w") as f:
    json.dump(ram_table, f, indent=2)

# ---------------------------------------------------------------------------
# Geometry via symbol arithmetic (address deltas), computed per title.
# ---------------------------------------------------------------------------
GEOM_PAIRS = [
    ("wPartyMon2-wPartyMon1", "wPartyMon2", "wPartyMon1"),
    ("wBoxMon2-wBoxMon1", "wBoxMon2", "wBoxMon1"),
    ("wPartyMonOT-wPartyMons", "wPartyMonOT", "wPartyMons"),
    ("sBox2-sBox1", "sBox2", "sBox1"),
    ("sBox7-sBox1", "sBox7", "sBox1"),
    ("wMainDataEnd-wMainDataStart", "wMainDataEnd", "wMainDataStart"),
    ("wBoxDataEnd-wBoxDataStart", "wBoxDataEnd", "wBoxDataStart"),
    ("wPartyDataEnd-wPartyDataStart", "wPartyDataEnd", "wPartyDataStart"),
]

geometry = {}
for label, a, b in GEOM_PAIRS:
    row = {}
    for t in TITLES:
        va = titles[t].sym.get(a)
        vb = titles[t].sym.get(b)
        if va is None or vb is None:
            row[t] = {"a": va, "b": vb, "delta": None, "note": "unresolved symbol"}
            continue
        delta = va[1] - vb[1]
        same_bank = va[0] == vb[0]
        row[t] = {
            "a_bank": va[0], "a_addr": f"{va[1]:04X}",
            "b_bank": vb[0], "b_addr": f"{vb[1]:04X}",
            "same_bank": same_bank,
            "delta_dec": delta, "delta_hex": f"{delta:#06x}" if delta >= 0 else f"-{-delta:#06x}",
        }
    geometry[label] = row

with open(os.path.join(OUT, "geometry.json"), "w") as f:
    json.dump(geometry, f, indent=2)

print("wrote ram_symbols.json, geometry.json")
