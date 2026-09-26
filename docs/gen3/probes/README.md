# Gen 3 probe and gate receipts

Raw output of live runs, kept as evidence. Each file is named for its row and the cut (8-hex sha) or date it ran at, and describes that tree only.

- **Current evidence:**
  - Frozen cut `a2985d5a`: `fc_SUMMARY_a2985d5a*.txt` (FR/LG 43/43, RR 19/19).
  - Post-merge passes on master: `fc_SUMMARY_a9ad03d3*.txt` (FR/LG shards, RR), then the zip rows re-run at `a20cd945` (`fc_SUMMARY_a20cd945*.txt`).
  - How to read them: `docs/gen3/G4_final_cut_runbook.md`, `docs/gen3/G4_request_draft.md` and `docs/gen3/G5_request_draft.md`.
- **Older cuts** (`157e1ef7`, `2b926be1`, `382703b3`, `58a8951f`, `6e85ddfc`, `870e5e5d`, `c0f6101b`, `d0a4bba5`, dated `2026-09-2x` files) were superseded and are kept only as history.
- **Counts before `56449231`:** `tools/release_lanes.py` under-reported the pass count of any run that contained failures. A lane total quoted from a failing run before that commit is a floor, not the real number.
- **Old client:** receipts from before `addc9225` that exercise `lua/clients/gen3_frlge_client.lua` never count as evidence for the new client (`docs/gen3_requirements.md`).
