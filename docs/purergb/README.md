# pureRGB integration — documents

**Status 2026-09-19: implemented and gate-verified (G0–G5 signed; G6 = the owner's tag).**
pureRGB v2.7.6 (`7e7a4653`) is a second Gen 1 foundation: `game_id gen1_purergb`, titles PureRed /
PureBlue / PureGreen, running the same client, codec and server machinery as vanilla Red/Blue, with
its own companion overlay and its own randomizer fork. This page is the map of the documents — what
shipped, what it was planned from, and how to rebuild the ROMs from source.

## Start here

| Document | What it answers |
|---|---|
| `CHANGELOG.md` | **What shipped**, by area, with the commit for each change; the shared-code behaviour changes a vanilla player can notice; the defects the live gates found; the evidence; the known limits; operating notes (build, overlay, fork, generators, release gate). |
| `PLAN.md` | The fact-grounded plan. §13 is the phased execution with owner gates and **§13.1 the gate ledger** (signatures, trees, receipts); §12 the executive summary; §6 the milestones; §11.2 the verified-facts appendix every generator cites; the "M3 live findings" and "P6 full-run findings" paragraphs before §M4 record what the emulator taught us after the plan was written. |
| `../historical/release_notes.md` | The release-note section (pureRGB short form). |
| `../REFERENCE.md` | The user-facing Gen 1 · pureRGB bullet. |
| `../protocol.md` | The acknowledged `key_change` contract. |
| `../gen1_requirements.md` | The pureRGB requirement rows. |
| `../../data/games/gen1_purergb/README.md` | The data pack. |
| `../../patch/gen1/purergb/README.md` | The companion overlay (`patch/dist/SLink-Pure{Red,Blue,Green}.ups`). |
| `../../patch/upr/` + `../../tools/build_upr_fork.py` | The randomizer fork. |
| `../../data/purergb/` | Canonical `.sym`/`.map` for the three titles (clean and `*_slink` overlay), `build_provenance.json`, `overlay_provenance.json`, `upr_pure_entries.ini`. |

## Research-phase artefacts

Still the citation source for the pack, and superseded wherever the pack says so:

- `research/` — worker outputs the plan cites (paths in the plan like `workers/s1/...` map to
  `research/s1/...`): `s1/` site anchors verified in the built ROMs; `s2/`, `w2/` UPR ZX INI drafts
  (the generated `data/purergb/upr_pure_entries.ini` supersedes them); `s3/` overlay design (the built
  overlay applies the H2 corrections in PLAN §11.2); `w1/` encounter census + per-map area draft
  (superseded by `gen_gen1_area_map.py`, which applies the U10 collapse); `d1/` fork brief; `d2/` the
  first pure facts module (superseded by `lua/tests/gen1_pure_facts.lua`); `d3/` client brief + pack
  schemas; `p3/` the P3 literal censuses.
- `probes/` — the BizHawk probe scripts and their outputs (checkpoint shape, WRAM domain, GBC-fade
  stress, RC route runs, APEX write window, save/PYDEC parity) plus `rom_scan.py`, `bps_apply.py`,
  `export_audit.py`. `rc_*.lua` expect `SLINK_RC_ROOT` = a scratch copy of `lua/` + `data/` with
  `data/pret/pokered.sym` replaced by `data/purergb/pokered.sym`.

## Build recipe (M0 build-equivalence gate)

| Tool | Role |
|---|---|
| `../../data/purergb_sources.lock.json` | The source of truth for "does this build match the one we reviewed": the pureRGB commit, the RGBDS / w64devkit downloads by sha256, and the sha1 of each built ROM (`outputs.<pokered\|pokeblue\|pokegreen>.sha1`). |
| `../../tools/build_purergb_syms.py` | Drives the build and regenerates `../../data/purergb/*.sym\|*.map` from source. **Publishes nothing unless every sha1 matches the lock.** |
| `.github/workflows/purergb-syms.yml` | Reproduces the canonical build from a clean Ubuntu checkout (pinned RGBDS v1.0.3 + pinned pureRGB commit), checks the built ROMs' sha1 against the lock, and diffs the `.sym`/`.map` output against what's committed here — the CI-side half of the same gate. |
| `../../tools/apply_bps.py` | Applies a BPS v1 patch to a source ROM (the upstream release patch over a clean Red/Blue dump is the other way to obtain the pinned ROMs). See `tests/unit/test_apply_bps.py` for the format details it implements. |
| `../../tools/build_purergb_overlay.py` | Builds the companion overlay on top and emits the UPS files. |
| `../../tools/build_upr_fork.py --bootstrap` | Builds the randomizer fork jar. |

Two gotchas that cost real time:

- **PureGreen's `.bps` is built against a clean _Blue_ dump, not Red** — upstream ships Red-over-Red
  but Blue-**and-Green**-over-Blue (PLAN.md §11.2 "Release artefacts"). Applying it to a clean Red dump
  produces a CRC mismatch, not PureGreen.
- **`build_purergb_syms.py` normalises `.sym`/`.map` to LF before hashing/publishing** (rgbds on
  Windows writes CRLF; the repo pins `.sym`/`.map` as LF per `.gitattributes`), so comparing raw build
  output against the committed files without that normalisation reports spurious drift.

Live and duo gates that need the built ROMs read `SLINK_PURERGB_ROMS` (a directory holding
`pokered.gbc`/`pokeblue.gbc`/`pokegreen.gbc`; default `.cache/purergb`):

```bash
SLINK_PURERGB_ROMS=.cache/purergb python tools/verify_gen1_release.py --lane <name>
```