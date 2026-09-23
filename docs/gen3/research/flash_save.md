# Gen 3 flash-save SOURCE research — gen3-P0-C0-3

Research date: 2026-09-21. SLink source cut inspected: **5e9d7bad8cbb170843c29553ca7228899d301f22**. This note supplies SOURCE inputs to [PLAN §5.5/P2](../PLAN.md). It does not qualify a ROM, fixture, installed emulator or execution hook. No build, generator or emulator was run. **[DERIVED]** identifies arithmetic/inference; **[RECOMMENDATION]** identifies codec/test policy, rather than a game guarantee.

Research pins (upstream master revisions resolved during this card, NOT substitutes for the coordinator's admitted-ROM/build pins):

- FR: pret/pokefirered **c75f352304d529f6ba92d4f74b9cf8b5c3810788** ([commit](https://github.com/pret/pokefirered/commit/c75f352304d529f6ba92d4f74b9cf8b5c3810788)).
- CF: Skeli789/Complete-Fire-Red-Upgrade **b637a27898b14e25dd24d0f69a3e302f0069deb8** ([commit](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/commit/b637a27898b14e25dd24d0f69a3e302f0069deb8)).
- BH: BizHawk 2.11.1 **bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5**, with MG gitlink **94b1578f8545d8ad17bb4036dba908612d5731e2** ([gitlink](https://github.com/TASEmulators/BizHawk/tree/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/submodules/mgba)).

Every upstream reference below is immutable. Current FR source has REVISION >= 0xA branches; the original flash-writing branch is the relevant research input for proposed US 1.0 support. Binary/build equivalence is still UNVERIFIED. [FR save.c:214–231][fw]

## 1. FRLG flash layout

### Geometry and footer

FR defines 32 sectors of 0x1000 bytes: **[DERIVED] 0x20000 / 128 KiB**. Physical sectors 0–13 and 14–27 hold two rotating game slots; 28–29 hold Hall of Fame; 30–31 are Trainer Tower special sectors. A slot has 14 logical section IDs, which must not be confused with physical-sector position. [FR save.h:6–30][fh]

| Sector-relative bytes | Format |
|---|---|
| 0000–0F7F | Maximum normal data area: 3968 bytes |
| 0F80–0FF3 | 116 unused bytes in vanilla footer |
| 0FF4–0FF5 | u16 logical section ID |
| 0FF6–0FF7 | u16 checksum |
| 0FF8–0FFB | u32 signature, 0x08012025 |
| 0FFC–0FFF | u32 counter |

Offsets are **[DERIVED]** from SaveSector's data[3968], unused[128-12], u16/u16/u32/u32 members. The source calls the requested “security” field **signature**; it is not SaveBlock2's encryption key. The GBA fields are decoded little-endian; the bound emulator domain declares little-endian in §2. [FR save.h:63–74][fh]

Normal section checksum: sum size/4 u32 words into a wrapping u32 accumulator, then return u16((sum >> 16) + sum). The length is the section's actual chunk size, NOT always 0xF80 or the entire sector. The writer clears the whole sector buffer, copies the chunk, and assigns this checksum. [FR save.c:167–194][fw], [614–627][fs]

### Chunk table

The chunk macro uses offset = chunkNum * 0xF80 and length = min(sizeof(struct)-offset,0xF80). ID 0 is SaveBlock2; IDs 1–4 are SaveBlock1; IDs 5–13 are PokemonStorage. UpdateSaveAddresses resolves their current RAM pointers. [FR save.c:43–78][fc], [630–647][fs]

| Logical ID | Object | Inclusive object-relative range | Length |
|---|---|---|---|
| 0 | SaveBlock2 | 0000–0F23 | 0F24 |
| 1 | SaveBlock1 | 0000–0F7F | 0F80 |
| 2 | SaveBlock1 | 0F80–1EFF | 0F80 |
| 3 | SaveBlock1 | 1F00–2E7F | 0F80 |
| 4 | SaveBlock1 | 2E80–3D67 | 0EE8 |
| 5 | PokemonStorage | 0000–0F7F | 0F80 |
| 6 | PokemonStorage | 0F80–1EFF | 0F80 |
| 7 | PokemonStorage | 1F00–2E7F | 0F80 |
| 8 | PokemonStorage | 2E80–3DFF | 0F80 |
| 9 | PokemonStorage | 3E00–4D7F | 0F80 |
| 10 | PokemonStorage | 4D80–5CFF | 0F80 |
| 11 | PokemonStorage | 5D00–6C7F | 0F80 |
| 12 | PokemonStorage | 6C80–7BFF | 0F80 |
| 13 | PokemonStorage | 7C00–83CF | 07D0 |

All ranges are **[DERIVED]** from the macro and source sizes: SaveBlock2=F24, SaveBlock1=3D68, storage ending at 83C2 + 14 = 83D0. P2 must assert compiler/map sizes against the admitted build. [FR global.h:327–359][sb2], [759–822][sb1], [storage header:7–11,44–50][storage]

The storage header's boxes comment says +0001, but the C array has alignment requirements: 420 records ×80 bytes followed by boxNames at +8344 implies **[DERIVED] boxes start +4**. Do not use the +0001 comment as a decoder constant without ABI/build validation. [storage]

### Rotation, slot selection and status

A full-slot write backs up rotation/counter, increments rotation modulo 14, and increments the u32 counter BEFORE writing. Logical ID n is placed at physical sector ((rotation+n) % 14) + 14*(counter % 2). If the damaged-sector mask is nonzero, status becomes ERROR and the in-memory rotation/counter are restored. That does not undo already-written flash. A single-sector call does not take the increment branch. [FR save.c:133–194][fw]

GetSaveValidStatus scans both slots. Each matching signature/checksum sets that section ID's bit and overwrites the slot's candidate counter with the current sector counter. All 14 ID bits means OK; any matching signature but incomplete coverage means ERROR; no matching signature means EMPTY. It does not explicitly require all accepted sectors to share the same counter. [FR save.c:466–532][fl]

When both slots are OK, select the larger u32 candidate counter, except the explicit FFFFFFFF/0 pair selects 0 as newer; a numeric tie chooses slot 1's counter. With only one OK slot, use its counter, returning ERROR if the other slot is ERROR and OK otherwise. Both EMPTY resets counter/rotation and returns EMPTY; remaining cases return INVALID. The copy routine chooses the physical half by counter parity, copies each chunk by its recorded ID, and learns rotation from the position of ID 0. [FR save.c:423–581][fl]

Status constants: EMPTY=0, OK=1, INVALID=2, NO_FLASH=4, ERROR=FF. With missing flash, LoadGameSave assigns gSaveFileStatus=NO_FLASH but returns ERROR; these are distinct outputs. [FR save.h:34–43][fh], [save.c:803–830][ft]

**[RECOMMENDATION]** Separate faithful loader classification from stricter witness qualification. Bounds-check IDs before indexing; reject duplicate/missing IDs and mixed counters; require the newly intended completed generation. These extra checks are SLink policy, not all guarantees of the original loader. A recovered old slot can be playable without proving that the requested new save succeeded. Cover wrap, tie/parity, one-valid/one-damaged, invalid ID, duplicate ID and mixed-generation controls. [fl]; PLAN:128–129.

### Partial and special writes

- SAVE_NORMAL serializes state and writes the full slot. SAVE_LINK writes only IDs 0–4; SAVE_EREADER only ID 0. SAVE_OVERWRITE_DIFFERENT_FILE erases 28–31 then full-saves. HOF writes its two extra sectors, then falls through to normal save. [FR save.c:650–698][fs]
- Incremental link-full-save advances the counter during initialization; intermediate calls write sections, replace the last section and later publish the omitted signature byte. Its booleans are task-progress results, not synonymous with SAVE_STATUS_OK. Source includes both full-link and partial SaveBlock2/SaveBlock1 pipelines. [FR save.c:234–419][fi], [723–800][fx], [882–963][ft]
- Hall of Fame uses HandleWriteSectorNBytes, storing its checksum in the id member; TryLoadSaveSector checks it there. Trainer Tower special functions accept physical sectors 30/31 with SPECIAL_SECTOR_SENTINEL=0xB39D at the beginning, rather than using ordinary ID/counter interpretation. Do not feed all four extra sectors into the normal 14-section validator. [FR save.c:197–211][fhof], [584–605][fhofr], [833–879][ft], [save.h:17][fh]

## 2. BizHawk mGBA battery file and runtime domain

**Correction to local tools/mkstates.py:102–107:** the 16-byte suffix is OPTIONAL RTC state, not an unconditional Pokémon-save footer. The source RTC buffer holds seven time bytes, a control byte and u64 lastLatch; the writer encodes lastLatch little-endian. It returns without writing when HW_RTC is absent, there is no VFile, or the mapping is read-only. [MG savedata.h:91–95][mh], [savedata.c:599–622][mr]

| Optional suffix offset | Meaning |
|---|---|
| 0–6 | RTC time[7] |
| 7 | control |
| 8–15 | lastLatch, little-endian u64 |

BizHawk CloneSaveRam and StoreSaveRam apply TruncateRTCIfUsingDeterministicTime: only !DeterministicEmulation && RTCUseRealTime preserves the native length; otherwise len is rounded down with len & ~0xff. Native retrieval refreshes RTC and reads the backing file. For the expected 128-KiB cartridge body, 0x20000 and 0x20010 are therefore distinct supported source cases; actual save type/settings remain a probe obligation. [BH ISaveRam.cs:11–38,67–69][bs], [MG bizinterface.c:636–650][md]

The memory domain is **SRAM**, **0x20000 bytes**, little-endian. BH deliberately exposes the maximum GBA savedata buffer because mGBA may not know the cartridge type at startup; the domain binds to the native buffer and the bridge returns ctx->sram. It is not named SaveRAM or Flash. [BH IMemoryDomains.cs:23–37,70][bd], [MG bizinterface.c:624–628][md]

**[RECOMMENDATION]** Compare the first 0x20000 bytes as flash; recognize/preserve the optional 16-byte RTC suffix separately. Never unconditionally subtract 16 bytes, never include RTC in section checksums, and reject unsupported lengths rather than guessing. The fixed domain size alone does not prove the ROM's selected save type. [bd], [bs], [mr]

**Runtime UNVERIFIED:** installed core hashes, actual domains, ROM save-type/RTC overrides, emitted file length and save-site-to-flush byte equality. Future authorized probe: record binary/settings/ROM pins; enumerate domains and SRAM size; dump SRAM[0..1FFFF] at the successful save boundary; flush and exit; compare the flash body exactly and record any RTC suffix independently. This note supplies SOURCE evidence only. [bd], [bs]; PLAN:129.

## 3. CFRU / Radical Red divergence

### Upstream CFRU facts, not an RR binary qualification

CF changes chunk capacity to **FF0**, not vanilla F80. Its nearby “3968 bytes / 128 byte footer” comment is stale against the define. SaveSection still puts its id/checksum/signature/counter in the final 12 bytes (data[FF4], then u16/u16/u32/u32); FF0–FF3 sit between the used chunk extent and ID. [CF save.c:17–48][cl], [include/save.h:29–36][ch]

CF chunk mapping:

| Logical IDs | Object offsets | Lengths |
|---|---|---|
| 0 | SaveBlock2 +0 | F24 |
| 1–3 | SaveBlock1 +0, +FF0, +1FE0 | FF0 each |
| 4 | SaveBlock1 +2FD0 | D98 |
| 5–12 | Storage +i*FF0, i=0..7 | FF0 each |
| 13 | Storage +7F80 | 450 |

These are the literal CF table. **[DERIVED]** Object extents remain F24/3D68/83D0, but split boundaries differ from vanilla. [CF save.c:27–48][cl]

CF also serializes a RAM “parasite” block at 0203B174, length EC4, into spare space in IDs 0,4,13. The pieces are CC,258,BA0 bytes at sector data F24,D98,450 respectively, each ending at FEF. HandleWriteSector computes the regular checksum over chunkSize BEFORE SaveParasite appends those bytes. **[DERIVED] The ordinary section checksum excludes these parasite bytes.** [CF save.c:23–55][cl], [119–176][cp], [361–394][cw]

Physical sectors **30/31 are repurposed**: CF writes FF0 bytes each from RAM after the EC4 parasite block. These buffers are zeroed before copying and sent to TryWriteSector without normal section metadata construction; the corresponding helper loads the data directly without normal signature/checksum checks. The full save writes these sectors after the 14 rotating chunks; single-chunk writes do not. **[DERIVED]** The extensions are not a second alternating copy selected by the normal slot counter, so recovering an older slot alone cannot prove a matching extension generation. [CF save.c:80–115][ce], [399–433][cw]

CF allows custom signatures and uses s32 candidate counters in its selector, whereas FR uses u32; both have an explicit -1/0 wrap case. **[RECOMMENDATION]** Do not assume one generic numeric comparator around 7FFFFFFF/80000000 until RR's binary establishes the actual rule. [CF save.c:68–77][cl], [238–356][cs], [FR save.c:466–581][fl]

### Compressed boxes and the local RR assumptions

CF's packed CompressedPokemon is **58 bytes / 3A**, containing personality, OTID, nickname, language, sanity, OT name, markings and packed growth/move/EV/misc data; moves are four 10-bit fields. It is not an encrypted vanilla 80-byte BoxPokemon. [CF storage header:16–57][cm]

CF's table places 25 boxes in noncontiguous RAM: boxes 1–19 at 02029318 with 30*58 strides; 20–22 at 0203CB44; 23–24 at 02027434; 25 at 02024638. [CF storage.c:44–86][cb] The current SLink RR profile mirrors those bases and sets CFRU_NO_ENCRYPT; its reconstruction leaves the checksum zero. That proves the local binding's assumptions, not RR's complete disk layout. [SLink lua/games/gen3_frlge.lua:260–303,342](../../../lua/games/gen3_frlge.lua#L260), [lua/memory_gba.lua:570–588,1075–1083](../../../lua/memory_gba.lua#L1075).

### RR binary revalidation and codec support (C5, 2026-09-23)

The chunk table, parasite mapping and 25-box disk map are now **SOURCE/binary pinned**, as previously recorded in [rr_save_layout.md](rr_save_layout.md). C5 independently re-read `patch/build/slink_RR.gba` and the clean RR image; `verify_rr_save_layout_rom` in `server/adapters/gen3_codec.py` checks the tables and instruction anchors on both. The companion witness SHA1 is `b7d1e0756fcc66575878affc8f7b95c45386bb1c`; clean RR is `964f951a0fdaf209e4ea1344883ef0d557bb3a80`. File offsets below are not GBA bus addresses.

| Witness | ROM file offset / evidence |
|---|---|
| 14 `{u16 object offset,u16 size}` entries | `0x1148BF0`; exactly `RR_CHUNK_TABLE`, sizes F24 / FF0,FF0,FF0,D98 / eight FF0,450 |
| 25 live box pointers | `0x1148930`; first 19 in storage, next 3 in extension, next 2 in SB1, final in SB2 |
| Object bases | setter pools `0x4C094`, `0x4C098`, `0x4C0A0` -> `02024588`, `0202552C`, `02029314` |
| Checksum precedes parasite insertion | checksum halfword store `0x10B8D28`, then ID comparisons `0x10B8D30..38` and copy at `0x10B8D54` |
| Parasite destinations/lengths | pools `0x10B8DEC`, `0x10B8DF0`, `0x10B8E04` -> `0203B174`, `0203B240`, `0203B498`; lengths CC, 96<<2=258, BA<<4=BA0 from `0x10B8D3E`, `0x10B8D42..46`, `0x10B8DB6..BA` |
| Shared extension | pools `0x10B8DFC`, `0x10B8E00` -> `0203C038`, `0203D028`; FF0-byte copies and physical-sector immediates 1E/1F at `0x10B8D78..AE` |

`party_from_save(image, rr=True)` and `boxes_from_save(image, rr=True)` now dispatch to the RR layout. The legacy `rr_*` entry points remain available. They are loader-style readers; a save witness must separately require `qualify_flash(cfru=True)` and its counter/attempt/live-save receipt. Sectors 30/31 have no checksum or generation counter, so a complete rotating slot cannot authenticate their age.

`rr_patch_saved_ranges(image, {ram_address: bytes})` is a structural rewrite primitive. It validates the selected rotating slot, maps bytes across section boundaries and the FF0 extension boundary, applies only requested byte edits, and recomputes only changed ordinary section checksums. It never calls the zero-filling `write_sector` on existing data. Parasite regions are excluded from writable mappings; opaque parasite bytes in both slots, inactive-slot bytes, section tails, HOF sectors and optional RTC are preserved. Empty/no-op edits are byte-identical. `rr_rewrite_identity` builds a restricted header-only edit on this primitive (§5.7).

MODEL tests cover `rr_town.sav`, inverse byte edits, owned/foreign identity selection, occupied synthetic records in all four regions including box20 slot21 across physical sectors30/31 and box23 across ordinary chunks, and direct equality with the Lua RAM-record decoder on the fixture party bytes. The committed fixture's actual boxed records are empty: synthetic occupied records are not a physical all-box save/reload receipt. High-bit save-counter rewrites explicitly refuse pending RR selector qualification; parasite semantics and extension generation coupling remain RR-OPEN.

## 4. Save-completion witness candidates

For vanilla, the clearest high-level candidate is the **successful return of u8 TrySavingData(u8 saveType), returning SAVE_STATUS_OK (1)**, qualified by saveType=SAVE_NORMAL for the first implementation. It checks flash presence, calls HandleSavingData and checks gDamagedSaveSectors. **HandleSavingData returns 0 regardless of success; its return value is not the witness.** Other save types require distinct caller/side-effect qualification. [FR save.c:650–720][fs]

A lower-level candidate is WriteSaveSectorOrSlot(FULL_SAVE_SLOT,...) returning OK. Capture the full-slot argument/caller; a successful single-sector return is insufficient. gSaveCounter advances at save.c:149 before the writes and is restored on failure at :160. A counter increment alone cannot certify completion. [FR save.c:133–164][fw]

Incremental link saves require a separate boundary after final signature publication/damage checks; their initialization already advances the counter, and task booleans represent progress. [FR save.c:723–761][fx], [882–963][ft]

For upstream CF, SaveWriteToFlash(FFFF,...) returning OK covers its normal 14 sections plus sectors 30/31, with damaged-sector checks after those writes. Its HandleSavingData still returns 0. HOF writes occur AFTER SaveWriteToFlash, so that return is not the final all-flash HOF boundary. **RR locations, hooks and exact status propagation are UNVERIFIED.** [CF save.c:399–486][cw]

**[RECOMMENDATION]** Receipt fields: entry/caller/save type, successful return/status, pre/post counter under the admitted wrap rule, ROM/core pins, attempt and frame. Pin the exact return instruction/callback semantics and prove failure/partial/reset negatives before any PHYSICAL claim. Dump the frozen flash buffer then separately compare the flushed body. [fw], [fs]; PLAN:108–110,129.

**[RECOMMENDATION]** Predefine “untouched” fields/ranges. Full saves rotate sectors and clear buffers; serialization/play time and relocated-save encryption can legitimately change bytes. Compare unchanged logical records after reconstruction where appropriate, and physical bytes only outside declared physical writes; never derive an allowed mask from the observed differences. Save-block relocation may generate a new encryptionKey and re-encrypt unrelated money/items/stats. [FR save.c:167–194][fw], [load_save.c:125–128,274–298][rekey].

## 5. Distinct-OT _b fixture derivation

1. **Identity manifest.** SaveBlock2 has playerName +0, playerTrainerId[4] +A, and independent encryptionKey +F20. Select new identity and explicitly enumerate owned records to transform, preserving intended traded-mon provenance. **[RECOMMENDATION]** Never global-replace four-byte patterns. [FR global.h:327–359][sb2]

2. **Party and PC.** Saved party count is SB1+34, party records begin +38; SavePlayerParty copies the live party into that block. Each Pokemon contains BoxPokemon plus party-only fields; BoxPokemon contains PID, OTID, OT name and secure data. PC holds BoxPokemon records. Change only manifest-selected OTID/OT name; preserve unrelated stats, moves, nickname, status and held item. [FR global.h:759–773][sb1], [load_save.c:160–177][serial], [pokemon.h:105–143][mon], [storage]

3. **Other embedded identities.** SB1 has mail +2CD0, daycare +2F80 and Route5 DaycareMon +3C98. DaycareMon embeds BoxPokemon and daycare mail. Mail has sender name/trainerId; daycare mail also has OT_name. SaveBlock2 has Battle Tower records with trainer IDs/checksums; link-battle record structures also carry IDs. These may be foreign/history data, not the current player: preserve them unless explicitly selected. **[RECOMMENDATION]** Restrict simple fixtures to empty daycare/mail and documented history, or derive and verify each additional record checksum. This is not a claim all dormant structures are active gameplay. [FR global.h:240–325,524–554,798–822][ident]

4. **Vanilla encryption.** Decrypt secure data using the OLD PID XOR OTID, verify its u16 sum of decrypted substructures, retain PID/permutation, change OTID/name and re-encrypt with the NEW PID XOR OTID. Recompute/verify mon checksum, then separately update all affected flash section checksums. **[DERIVED]** If only header OTID/name changed and plaintext is unchanged, the mon checksum stays equal; changing OTID without re-encryption corrupts interpretation. [FR pokemon.c:2069–2091][mcheck], [2797–2900][crypt], [save.c:614–627][fs]

5. **Separate bag/save encryption.** An OT-only transformation need not change SaveBlock2.encryptionKey. If that key changes, source rekeys bag contents, game statistics, Berry Powder, trainer-tower times, money and coins; mon re-encryption does not perform those operations. [sb2], [FR load_save.c:274–298][rekey]

6. **Behavioral identity.** Shininess depends on PID and OTID halves. **[DERIVED]** A new OT may change shiny classification even when payload bytes are preserved; choose and record a policy. Keeping the XOR of old OTID halves in the new OTID preserves that contribution for unchanged PID, but needs independent fixture assertions. Do not silently rewrite PID, which also selects substructure interpretation. [FR pokemon.h:282][shiny], [crypt]

7. **RR needs its own derivation.** Its binding uses fixed-order unencrypted party data; compressed records include OTID directly and have no vanilla secure-data checksum layout. Use the admitted RR codec, not the vanilla XOR recipe. Recompute applicable flash checksums, separately protect parasite/extension data, and establish the full RR daycare/history ownership inventory before claiming completeness. [SLink memory_gba.lua:570–572,764–775,1075–1083](../../../lua/memory_gba.lua#L570), [cm], [cw], [ce]

   **C5 primitive:** `rr_rewrite_identity(image, trainer_id, trainer_name, owned_ot_id=None) -> (bytes, manifest)` changes selected-slot trainer OT/name plus occupied party and compressed-box records whose OT matches the source trainer (or explicit owner selector). Only header OTID +4 and OT name +14 change; raw compressed data, PID, mon checksums and foreign records remain byte-identical. The caller chooses the new identity/shiny policy; the helper does not invent one. The inactive rotating slot deliberately retains the original identity, while sectors30/31 are shared; this policy is reported in the manifest. Daycare/mail/history and parasite identities are preserved without claiming a complete ownership inventory. A caller requiring both rotating slots to become B must not treat this selected-slot primitive as that stronger policy. The fixture worker owns CLI integration and cold boot qualification.

8. **Backup slot and RTC.** Preserve/hash the original; record selected slot/counter/rotation and transformed record keys. **[RECOMMENDATION]** Explicitly decide whether the backup slot retains A identity or is transformed too: recovery into an old A identity can invalidate a B/wrong-save fixture. Preserve special sectors and optional RTC unless intentionally changed. Every derived output requires cold boot→CONTINUE→re-save→reload plus independent decoding; encode/decode round trips alone are not usability proof. [fl], [bs]; PLAN:130.

## 6. Outside-lease findings and P2 verification targets

No file outside this note was changed.

- tools/mkstates.py:102–107 describes a universal 16-byte suffix; source makes RTC serialization/retention conditional. Route the helper's documentation/normalization assumptions to its owner. [bs], [mr]
- docs/gen3/PLAN.md:128–129 must not be implemented as one vanilla chunk/special-sector schema for RR. CFRU changes both split boundaries and the treatment/protection of extra bytes; actual RR binary qualification remains required. [cl], [ce], [cw]
- **[RECOMMENDATION] test_gen3_flash_layout.py:** per-ID checksum length; rotation/counter parity, wrap and tie; both slot recovery statuses; malformed/duplicate/missing IDs; mixed counters; missing final signature; partial vs full saves; HOF/special sector formats; CF parasite coverage and nonredundant extension generations; 0x20000 versus 0x20010 and rejected other lengths. These are targeted falsifiers of the sourced assumptions, not tests of a generated round-trip alone. [fh], [fi], [fl], [ce], [cw], [bs]
- **[RECOMMENDATION] witness controls:** successful full save versus failed/no-flash/partial/counter-only observations; exact frozen SRAM-to-file-body comparison with RTC separated; correct save generation/ROM/attempt binding. [fs], [fx], [bd], [bs]

## 7. NOT VERIFIED / UNVERIFIED

- FR research revision→admitted FR/LG US 1.0 binary equivalence, compiled sizes and exact execution sites; pinned build/ROM checks and live callback receipts still required. [fc], [fw]; PLAN:108–110.
- Installed BH/MG hashes, SRAM domain/content binding, save-type/RTC overrides, file length and witness/flush equality; the §2 probe is not run. [bd], [bs], [md]
- RR table/parasite/extension mappings and ordinary checksum coverage are binary-pinned (§3). RR signed counter selection at high-bit boundaries, full/partial completion semantics, and extension generation coupling remain unqualified; rewrite explicitly refuses high-bit counters. [cs], [ce], [cw]
- All 25 RR box locations have SOURCE and synthetic MODEL coverage, but occupied-record save/reload across every region still needs PHYSICAL receipts. No claim that the single-copy extension matches a recovered older rotating slot is possible from the image alone. [cb], [ce]
- Complete _b identity/history transformation, intended shiny/ownership behavior and bootability; no fixture was created. [ident], [shiny]; PLAN:130.
- No live save witness, interrupted-save recovery, flash failure, RTC change or cross-version test was executed. This is SOURCE research only; MODEL and PHYSICAL gates remain outstanding. PLAN:127–139.

[fh]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/save.h#L6-L74
[fc]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L43-L78
[fw]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L133-L231
[fi]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L234-L419
[fl]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L423-L581
[fs]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L614-L720
[fx]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L723-L800
[ft]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L803-L963
[fhof]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L197-L211
[fhofr]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/save.c#L584-L605
[sb2]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/global.h#L327-L359
[sb1]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/global.h#L759-L822
[storage]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/pokemon_storage_system.h#L7-L50
[ident]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/global.h#L240-L822
[mon]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/pokemon.h#L105-L143
[mcheck]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/pokemon.c#L2069-L2091
[crypt]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/pokemon.c#L2797-L2900
[shiny]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/include/pokemon.h#L282-L282
[serial]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/load_save.c#L160-L206
[rekey]: https://github.com/pret/pokefirered/blob/c75f352304d529f6ba92d4f74b9cf8b5c3810788/src/load_save.c#L125-L298
[ch]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/save.h#L5-L60
[cl]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L17-L77
[ce]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L80-L115
[cp]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L119-L208
[cs]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L238-L356
[cw]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/save.c#L361-L486
[cm]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/new/pokemon_storage_system.h#L16-L57
[cb]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/src/pokemon_storage_system.c#L44-L86
[cn]: https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/b637a27898b14e25dd24d0f69a3e302f0069deb8/include/new/save.h#L6-L20
[bd]: https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAHawk.IMemoryDomains.cs#L23-L70
[bs]: https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAHawk.ISaveRam.cs#L11-L69
[md]: https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/platform/bizhawk/bizinterface.c#L624-L650
[mh]: https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/include/mgba/internal/gba/savedata.h#L91-L95
[mr]: https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/gba/savedata.c#L599-L659
