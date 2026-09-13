# D1-RB private volume setup

2026-09-13 17:43 EDT. Sol `/root/rb_mute_sol`, conditional ACTIVE claim acknowledged at canonical `gen1/rc` HEAD `fb2a7d6cadc0ffd5b2d22bf7fca003c1af5d8faf`. Exclusive code path: `tests/live/gen1_selected_scenario.py`. R0 report and Sol2 parcel files were already dirty and remain outside this claim.

The owned copied base config now sets `SoundVolume=0` and `SoundVolumeRWFF=0` beside its existing frame-skip and auto-minimize overrides. The private emulator receipt requires both zero values. Source original config remains hash-audited before/after; sound enable, throttle, core config and performance settings are untouched. This is silent test input setup, not physical gameplay or FPS evidence.

Offline checks: focused selected R/B ball-gate and idle pair `45 passed in 1.25s`, exit 0, no skip/error/failure (`.cache/d1-rb-mute.models.txt`); Ruff changed file `All checks passed`, exit 0 (`.cache/d1-rb-mute.ruff.txt`). Code SHA256 `5661d4341a244f2db74568ffcdf56ba32b8d3c95735132f36afd925f14094ff`. No emulator, CUA, host user-config edit, product source edit, or commit. Physical volume receipt remains unrun; coordinator reviews tiny diff and owns fresh sole live grant.
