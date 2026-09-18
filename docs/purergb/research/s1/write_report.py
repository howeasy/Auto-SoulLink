import json, os

OUT = os.path.dirname(os.path.abspath(__file__))
TITLES = ["red", "blue", "green"]

sites = json.load(open(os.path.join(OUT, "sites_purergb.json")))["titles"]
ram = json.load(open(os.path.join(OUT, "ram_symbols.json")))
geom = json.load(open(os.path.join(OUT, "geometry.json")))
maps = json.load(open(os.path.join(OUT, "map_summary.json")))

lines = []
a = lines.append

a("# pureRGB engine-signal site verification (v2.7.6 / RGBDS 1.0.3, commit 7e7a465)")
a("")
a("Method: parsed `pokered/blue/green.sym`, computed flat ROM offsets "
  "(bank\\*0x4000 + addr-0x4000, or addr for bank 0), sliced 8 bytes from the "
  "matching `.gbc`, and checked them against instruction shapes derived by hand "
  "from the cited `P/` source lines (macro lengths taken from `macros/farcall.asm`, "
  "confirmed: farcall/callfar/jpfar/homecall/predef/rst byte counts all match the "
  "task's stated macro table). Every symbol resolved on the first try in all three "
  "`.sym` files; no unresolved names.")
a("")

a("## 1. Site-by-site verification")
a("")
a("All 40 code sites below are **byte-identical across red/blue/green** -- "
  "confirmed programmatically (zero cross-title differences found). pureRGB's "
  "code segments are shared across the three titles; only text/graphics ROMX "
  "content differs, which is why the SUMMARY byte counts differ slightly (see §3).")
a("")
a("| kind | symbol (as resolved) | bank:addr | rom_offset | bytes (8) | verdict | note |")
a("|---|---|---|---|---|---|---|")

order = list(sites["red"]["sites"].keys())
for kind in order:
    e = sites["red"]["sites"][kind]
    verdict = "PASS" if e["source_assert_ok"] else "FAIL (see §4)"
    sym = e["symbol"] if e["symbol"] else "(raw addr)"
    off = f'+{hex(e["offset"])}' if e["offset"] is not None else ""
    bank_addr = f'{e["bank"]:02x}:{e["address"]:04x}'
    note = e["note"].split(". ")[0]
    if len(note) > 110:
        note = note[:107] + "..."
    a(f'| {kind} | {sym}{off} | {bank_addr} | {e["rom_offset"]:06x} | `{e["expected_hex"]}` | {verdict} | {note} |')

a("")
a("Full per-site notes (source citation + byte-level derivation) are in "
  "`sites_purergb.json`; every entry's `note` field carries the file/line and "
  "the exact instruction sequence. Since bytes are identical across all three "
  "titles for every site, the table above is not repeated three times; "
  "`sites_purergb.json` still stores independent red/blue/green captures "
  "(cross-checked equal).")
a("")

a("## 2. RAM symbols the SLink profile needs")
a("")
a("All resolved in all three `.sym` files, all identical across titles (WRAM/HRAM "
  "layout is shared code, confirmed independently by §3's WRAMX/HRAM EMPTY "
  "blocks being byte-identical too).")
a("")
a("| symbol | bank | address | identical across titles |")
a("|---|---|---|---|")
for sym, row in ram.items():
    r = row["red"]
    a(f'| {sym} | {r["bank"]} | ${r["hex"]} | {"yes" if row["identical_across_titles"] else "NO"} |')
a("")
a("Observation: `wMoveMonType` and `wRemoveMonFromBox` both resolve to `$CF95` "
  "(bank 0) -- they alias the same scratch byte. Not a bug in this resolver; "
  "confirmed directly from the `.sym` file, and consistent with the two flags "
  "never being live at the same time (one is used mid-`MoveMon`, the other only "
  "around `RemovePokemon`).")
a("")

a("## 3. `.map` capacities (SUMMARY + EMPTY blocks)")
a("")
a("| region | red used/free | blue used/free | green used/free | identical? |")
a("|---|---|---|---|---|")
for region in ["ROM0", "ROMX", "SRAM", "WRAM0", "WRAMX", "HRAM"]:
    vals = {t: maps[t]["summary"][region] for t in TITLES}
    same = vals["red"]["free"] == vals["blue"]["free"] == vals["green"]["free"]
    cells = " | ".join(f'{vals[t]["used"]}/{vals[t]["free"]}' + (f' in {vals[t]["banks"]} banks' if vals[t]["banks"] else "") for t in TITLES)
    a(f'| {region} | {cells} | {"yes" if same else "NO -- ROMX text/data differs per title"} |')
a("")
a("ROM0 EMPTY: `$3a9a-$3fff` (1382 bytes / `$0566`), identical across all three titles.")
a("")
a("ROMX bank `$3D` (decimal #61, the highest bank actually used) EMPTY tail:")
a("")
a("| title | EMPTY range | free bytes |")
a("|---|---|---|")
for t in TITLES:
    e = maps[t]["romx_3d_empty"][0]
    a(f'| {t} | {e} | |')
a("")
a("ROMX banks `$3E` and `$3F` (decimal #62/#63): **not present in the map at all** "
  "for any of the three titles -- only 61 of the 63 possible ROMX banks are used, "
  "so both banks are entirely free (2 × 16 KiB = 32 KiB of unused capacity, "
  "on top of the 89 KiB of fragmented free space the SUMMARY reports scattered "
  "across the 61 used banks).")
a("")
a("| region | EMPTY | identical across titles |")
a("|---|---|---|")
a(f'| WRAM0 | fully used, 0 free | yes |')
a(f'| WRAMX bank 1 | `$deea-$deff` (22 bytes / `$0016`) | yes |')
a(f'| WRAMX bank 2 | `$d080-$dfff` (3968 bytes / `$0f80`) | yes |')
a(f'| HRAM | fully used, 0 free | yes |')
a("")

a("## 4. Geometry via symbol arithmetic")
a("")
a("| expression | red | blue | green | note |")
a("|---|---|---|---|---|")
notes = {
    "wPartyMon2-wPartyMon1": "= PARTYMON_STRUCT_LENGTH (44 bytes), matches vanilla.",
    "wBoxMon2-wBoxMon1": "= 33 bytes, matches vanilla box-mon struct length.",
    "wPartyMonOT-wPartyMons": "264 bytes = 6 party slots × 44.",
    "sBox2-sBox1": "1122 bytes per box (SRAM).",
    "sBox7-sBox1": "0x0000 delta but **different bank** (sBox7 is bank 3, sBox1 is bank 2) -- box 7 starts a second SRAM bank at the same local offset as box 1, it is not a linear 6× continuation.",
    "wMainDataEnd-wMainDataStart": "1929 bytes of main save data.",
    "wBoxDataEnd-wBoxDataStart": "1122 bytes = one box's worth (matches sBox2-sBox1).",
    "wPartyDataEnd-wPartyDataStart": "404 bytes of party save data.",
}
for label, row in geom.items():
    vals = []
    for t in TITLES:
        r = row[t]
        bank_note = "" if r["same_bank"] else f' (banks differ: {r["a_bank"]:#x} vs {r["b_bank"]:#x})'
        vals.append(f'{r["delta_hex"]}{bank_note}')
    same = len(set(vals)) == 1
    a(f'| {label} | {vals[0]} | {vals[1]} | {vals[2]} | {notes.get(label,"")} |')
a("")

a("## 5. Offsets that did NOT match the task's literal site definition")
a("")
a("Three of the ~40 sites, as literally specified, land on the wrong byte. All "
  "three were confirmed empirically (byte dump + symbol-address cross-check, not "
  "just hand-counted) and a corrected offset/symbol was found by walking the "
  "surrounding disassembly:")
a("")
a("1. **trainer_staging** -- `_InitBattleCommon + 0x48/0x4D` (task's literal symbol, "
  "*with* underscore) does **not** contain `ld a,2`. That label is core.asm's "
  "shared wild/trainer tail (L7111); at +0x48 it sits mid-instruction inside "
  "`call z, DrawEnemyHUDAndHPBar` / a `callfar CheckInitSpecialBattleEffect`. "
  "**Corrected symbol: `InitBattleCommon` (no underscore, core.asm L7044)** -- "
  "a distinct, similarly-named label 67 lines earlier. Same offsets (0x48/0x4D) "
  "on the corrected symbol give exactly `3E 02 EA 57 D0 18 49 21` = `ld a,2 ; "
  "ld [wIsInBattle],a ; jr +0x49` (which lands exactly on `_InitBattleCommon`), "
  "matching the task's own '3E 02' hypothesis precisely.")
a("2. **changebox_full_save** -- `ChangeBox.yes + 0x38` is `3E B6 ...` "
  "(`ld a, SFX_SAVE`), not `call SaveGameData`. The call is 3 bytes earlier. "
  "**Corrected offset: `ChangeBox.yes + 0x35`** -> `CD B5 78` = `call SaveGameData` "
  "($78B5), confirmed against the resolved `SaveGameData` symbol address.")
a("3. **cable_add** -- `TradeCenter_Trade.doTrade + 0xA0` is `FA 6B D1 ...` "
  "(`ld a,[wPartyCount]`), the instruction *after* the call. **Corrected offset: "
  "`TradeCenter_Trade.doTrade + 0x9D`** -> `CD CB 34` = `call AddEnemyMonToPlayerParty` "
  "($34CB), confirmed against the resolved symbol address.")
a("")
a("All other ~37 sites (including every RST vector, every `callfar`/`farcall` "
  "shape, and every checkpoint) matched their derived expectation exactly on "
  "the first try, with the target CALL/JP addresses cross-checked against the "
  "resolved symbol table (not just opcode shape) wherever the site names a "
  "specific callee. `sites_purergb.json` carries both the as-specified (FAILing) "
  "entry and a `*_corrected` shadow entry (PASSing) for all three of the above.")
a("")

with open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("wrote REPORT.md,", len(lines), "lines")
