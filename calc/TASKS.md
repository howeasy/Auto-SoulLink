# Tasks

These are upstream `smogon/damage-calc` maintainer instructions (updating the `@smogon/sets`
package, publishing `@smogon/calc` to npm). Neither applies to this fork: SLink vendors its own
trainer sets instead of pulling `@smogon/sets` (see `calc/README.md`'s "Vendored Trainer Sets"
section), `calc/import/` is unused dead weight from upstream, and this fork is never published to
npm — it's a personal tool, not an `@smogon` org package.

This fork is maintained instead by:

- `npm run build` (or `node build`) in `calc/` after any TypeScript change under `calc/calc/src/`.
- `tools/gen_purergb_calc_patch.py --check` / `tools/gen_purergb_setdex.py --check` to regenerate
  pureRGB's calc data and trainer sets from the pinned ROM checkout; drop `--check` to write.
- `tools/gen_rr_priority_trainers.py` for Radical Red's priority trainer-set overrides.
