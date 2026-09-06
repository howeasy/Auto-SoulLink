# RR 4.1 reference evidence

`tools.rr.reference` reads the exact pinned base RR ROM and extracts deterministic
baseline evidence. It imports no runtime modules and never launches an emulator or
patches/copies a ROM. Generated files here are **not runtime tables** and do not
approve any release or companion build. Runtime gender/type/family tables remain
unchanged until their policy and compatibility work is reviewed.

From the intended repository/worktree root, pass both inputs explicitly:

```powershell
python -m tools.rr.reference --rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba' --repo . --output-dir docs/rr_reference/generated
python -m pytest tests/unit/test_rr_reference.py -q
python -m pytest tests/rr/reference -q --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
python -m ruff check .
```

The pure API is `build_artifacts(rom_bytes, load_sources(repo_path))`. Source hashes
and output hashes are recorded without timestamps or absolute paths. Comparators
parse literal baseline dictionaries through `ast`, never execute workspace code,
and have controlled fixtures independent of whether runtime defects are repaired.
Missing/wrong required ROM evidence fails; it does not skip.

Six generated JSON files cover species, evolution components, compressed box
pointers, mode flags, baseline comparisons, and the manifest. Instruction anchors
check the actual RR gender getter, shiny classifier and active palette detours,
expanded flags, and mode-setting scripts. Shiny classification stays XOR below 8;
raw Fairy byte 23 is explicitly translated to existing server type 18.

The verified ROM tables contain **1376 records, IDs 0-1375**, including None/Egg
sentinels and zero placeholder records. Independent name-table and BaseStats-table
boundaries agree; see [species extent evidence](SPECIES_EXTENT.md). Record 1376
belongs to following assets and is never interpreted as a species.

The input canonical-name catalog currently ends at 1355. The remaining 20 records
retain their exact ROM display labels and explicit missing-catalog classifications.
Truncated names and shared form labels are not expanded by guesswork. No form aliases,
biological base forms, or playability are inferred from names. These catalog gaps
still require resolution before a complete runtime-data release.

Evolution output preserves method ID, parameter, auxiliary field, slot and address.
Methods 1-252 define undirected permanent-evolution components; 253+ remain separate.
Unknown target edges are retained and components are marked incomplete. Component
IDs are minimum member IDs, not biological claims. The final clause policy must
supply reviewed regional/cosmetic/temporary-form aliases separately.

These outputs prove neither current save mode nor save compatibility, dynamic RAM
ownership, actual companion execution, or campaign readiness. Both players still
require the exact approved companion and paired reconciliation before gameplay.
