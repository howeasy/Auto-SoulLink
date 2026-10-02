# Gen 2 overlay admission: contract (2026-10-02)

Owner, 2026-10-02: "Do the full fix." Production admits the patched Gen 2 cartridges (overlay:
Crystal `b405446e`, Gold `69067c4b`, Silver `583d8df4`; `data/gen2/overlay_provenance.json`) with
PHYSICAL proof recorded on the overlay ROM itself. Clean cartridges stay admitted (patch-first,
`patch/README.md`). G4 is signed (`docs/gen2/PLAN.md:207`); the playtest is not a blocker. Design:
Codex ROMPatch cx-ddc39d87, adopted except where D6 says otherwise. Coordinator: Claude session
4c3e927b. Branch `claude/mandatory-rom-patch-3fcfda`.

Owner, 2026-10-02: Gen 2 NEEDS its companion. The Soul Link rules run without it, but trade (the only
Gen 2 trade path), the SLINK panel and native sounds do not. Once admitted, it is non-optional,
like Red/Blue: Crystal/Gold/Silver rejoin `server/manager.py` `COMPANION_TITLES`. Rule: a title whose
features need a patch gets it with no opt-out; a title that needs none is not given one.

## Why the clean facts do not carry over

The overlay is a source rebuild (`tools/build_gen2_companion.py`). Symbol MOVEMENT is confined to
bank 4 (`verify_symbol_scope`), but operands elsewhere may change (:535-548) and ROM0 `DelayFrame`
is rewritten (:176-187). RAM symbols do not move, so RAM coordinates, codecs, charmap, areas and
policy are shared. Executed bytes (engine sites, preludes, checkpoint anchors, header anchors,
ROM-valued profile coordinates) are per artifact.

## Decisions

**D1 Catalog rows (`data/games/gen2_<t>/admission.json`, schema_version 2).**
- clean: unchanged. `kind=clean, selection=SELECTED, status=BUILT`; runtime grant = `matrix.gate`
  G1 ADMITTED. Crystal 1.1 stays `BUILD_ONLY`.
- overlay before activation: `kind=overlay, selection=FUTURE, status=BUILT`; never runtime eligible.
- overlay activated: `selection=SELECTED, status=ADMITTED`, plus
  `runtime_gate={"id":"G4","state":"ADMITTED","grant_fingerprint":<existing grant>}` and
  `binding_sha256` (sha256 of the overlay binding sidecar, D2). `matrix.gate` stays the CLEAN G1 grant
  and never grants an overlay.
- `Entry.kind` returns `clean` or `overlay` in sha1 mode only; ghost/randomized/unknown stay refused.
- Generated only by `tools/gen_gen2_admission.py`; never hand-edited.

**D2 Overlay execution binding** (new, generated): `data/games/gen2_<t>/overlay/binding.json`, made by
`tools/gen2_artifacts.py` from the VERIFIED overlay ROM (published UPS applied to the pinned clean
build, sha1 checked against provenance) plus the overlay `.sym`/`.map` (sha256 checked). It holds
`{schema, title, kind:"overlay", rom_sha1, base_sha1, ups_sha256, sym_sha256, map_sha256,
sites, checkpoint, header_anchors, profile_rom}`. `sites` and `checkpoint` use the same schema as
the clean `engine_signals.json` title sites and `write_checkpoint.json` title rows, with overlay-resolved
offsets and expected_hex read from the verified overlay ROM. Every changed byte must be explained by
a symbol move or a pinned builder substitution; an unexplained opcode/control-flow change refuses
generation. Clean has no sidecar (its view is the existing packs). The clean packs keep their
`source.*` lineage untouched; `profile.rom_sha1` stays the clean base fact.

**D3 Runtime view API** (`lua/gen2/artifact.lua`, new): `Artifact.view(root, json, data, title, row)`
-> `{kind, rom_sha1, base_sha1, binding_sha256, sites, checkpoint, anchors, profile_rom}` or
`nil, why`. Clean returns the pack view. Overlay loads the sidecar, checks `binding_sha256` against
the row, and never falls back to clean.

**D4 Proof namespace.** `Entry.RECEIPT_FILES[pack] = {clean={...existing, unchanged},
overlay={engine_sites, write_window, qualifications}}` with overlay files under
`data/games/gen2_<t>/receipts/overlay/`. Silver overlay has ITS OWN write_window (O-23 stays clean-only).
Fixture IDs (`crystal_battle`, `gold_town`, ...) are unchanged. Fixture BYTES are reused (RAM layout
unchanged), but every overlay qualification is a fresh boot/re-save/reload receipt on the overlay ROM.
Synthetic (O-33) setups are reused only under their existing disclosures, and v2 U1 unions never mix
kinds or ROMs.

**D5 Validators take the artifact.** `signals.qualified_sites/new/bind_*` and
`gen2_write_safety.qualified/new/bind_*` take the selected view (D3) and validate every run against
its `rom_sha1`/kind/binding. The checkpoint `admitted(title, sha)` closure uses the EXECUTED sha1.
`compose()` takes identity from the admission decision (kind + actual rehashed sha1); production
ignores `deps.artifact_kind` and passes `artifact_kind=decision.kind`, `rom_sha1=decision.rom_sha1`
to the client. Both compose hash checks and `source_anchors` use the view.

**D6 Activation before freeze (digest unchanged).** The CODE_DIGEST stays all-file (no scope
change). Order: (1) code; (2) round-1 overlay qualification + U1 + U2 captures (pre-freeze, tooling
only, production admission not needed); (3) ship digest-free copies under `receipts/overlay/` and
activate the rows: `--promote-overlays` splits its pre-check into ACTIVATION preconditions (G4 signed,
published pins, binding sidecar, overlay proofs valid under the production validators), not the full
release-evidence; (4) one commit, then freeze; (5) full sweep, clean and overlay, at the frozen digest;
(6) pin, `gen_gen2_admission --check`, `verify_gen2_release.py --release-evidence`.

**D7 Evidence obligations (overlay, in addition to the full clean re-sweep).** Matrix cell identity
gains `artifact_kind`. Per title: overlay qualification of every RECEIPT_FILES fixture, U1 union, U2
(all modes), inspect_run, panel/sfx/w6/phone/sp_lowwater under the honest artifact context. Duo: the
full `DUO_PAIRS_SCENARIOS` on overlay C-C and G-S, overlay C-G link, and every `TRADE_END_STATUS`
case on C-C/G-S/C-G, through the unmodified production entry. The `T.PATCHES` harness
(`lua/tests/duo/gen2_trade.lua`) is deleted. Historical `HARNESS_ONLY_OVERLAY` receipts stay
labelled as such.

**D8 Server.** No change: `gen2_gsc` already pairs overlay with overlay only and refuses mixed kinds.
Model tests prove it.

## Streams (exclusive files; workers do not commit, the coordinator reviews and commits)

| Stream | Owner | Files |
|---|---|---|
| R: execution binding | Codex ROMPatch | `tools/gen2_artifacts.py` (new), `tools/gen2_source_data.py`, `lua/gen2/artifact.lua` (new), `data/games/gen2_{crystal,gold,silver}/overlay/binding.json` (generated), `tests/unit/test_gen2_artifacts.py` (new) |
| A: runtime + catalog | Sonnet A | `lua/gen2/entry.lua`, `lua/gen2/signals.lua`, `lua/gen2_write_safety.lua`, `lua/gen2/run.lua`, `lua/gen2/client.lua`, `tools/gen_gen2_admission.py`, `data/games/gen2_*/admission.json` (regenerated), `tests/unit/test_gen2_entry.py`, `tests/unit/test_gen2_admission.py`, `tests/unit/test_gen2_overlay_admission.py` (new) |
| B: capture tooling | Sonnet B | `tools/run_gb_gate.py`, `tools/gen2_fixtures.py`, `lua/tests/test_gen2_scripted_gate.lua`, `lua/tests/gen2_{inspect_gate,frame_align,u1g_inputs,write_windows,qualify,scripted_play,panel_gate,sfx_gate,phone_gate,w6_gate,sp_lowwater_gate}.lua`, `tests/live/test_gen2_*.py`, `tests/unit/test_gen2_physical_receipts.py` |
| C: duo + verifier (after R) | Codex ROMPatch | `tools/e2e_duo.py` (Gen 2 parts), `tools/gen2_duo_oracles.py`, `tools/gen2_trade_oracles.py`, `tools/gen2_trade_lane.py`, `lua/tests/duo/{gen2_trade,duo_gen2_main}.lua`, `tools/verify_gen2_release.py`, `tests/gen2_{live_gate,release}_requirements.json`, `tools/gen2_final_sweep.py`, `tools/make_release.py` |
| Coordinator | Claude | this doc, `server/manager.py` `COMPANION_TITLES` (Gen 2 re-added last), emulator lane, integration |

Interface order: R commits the `lua/gen2/artifact.lua` API skeleton (D3) first; A codes against it.
Every stream starts from red tests (the falsifiers in cx-ddc39d87 RECOMMENDATION 2-6).
