# pureRGB integration — research phase artefacts (2026-09-17)

- `PLAN.md` — the fact-grounded integration plan (also at `~/.claude/plans/moonlit-napping-nautilus.md`). §12 is the executive summary, §6 the milestones, §11 the research ledger + verified-facts appendix, §11.3 the closure.
- `research/` — worker outputs the plan cites (paths in the plan like `workers/s1/...` map to `research/s1/...`):
  - `s1/` site anchors verified in the built ROMs (`sites_purergb.json`, `REPORT.md`)
  - `s2/`, `w2/` UPR ZX 4.6.1 INI entries for PureRed/PureBlue/PureGreen (`upr_pure_entries_v2.ini` is the resolved one)
  - `s3/` companion source-overlay design (apply the H2 corrections recorded in PLAN.md §11.2)
  - `w1/` encounter census + per-map area map draft (`encounter_census.json`, `area_map_purergb.json`)
  - `d1/` UPR fork implementation brief; `d2/` pure harness facts module (`gen1_pure_facts.lua`); `d3/` client brief + data-pack schemas
- `probes/` — the BizHawk probe scripts and their outputs (checkpoint shape, WRAM domain, GBC-fade stress, RC route runs, APEX write window, save/PYDEC parity) plus `rom_scan.py`, `bps_apply.py`, `export_audit.py`. `rc_*.lua` expect `SLINK_RC_ROOT` = a scratch copy of `lua/` + `data/` with `data/pret/pokered.sym` replaced by `data/purergb/pokered.sym`.
- `../../data/purergb/` — canonical `.sym`/`.map` for the three titles + `build_provenance.json`.

Nothing here is wired into the runtime; implementation starts only after the Gen 1 R/B RC ships (owner order). Built ROMs are not committed.
