# Phase 2 verified cleanup

Removed the unused SSE heartbeat task/method (the real SSE handler owns its
keepalive), unused OBS trigger-name list/config-copy/convenience helpers, the
empty Nuzlocke badge fragment, and the no-op OBS path branch. Renderer access to
always-initialized state/adapter fields is direct. Runtime-owned coercion and
admission/dispatch code remains untouched.

The source sweep found five unreferenced SVG symbols in this integrated tree:
`i-bolt`, `i-box`, `i-coffin`, `i-reroll`, and `i-warn`. They were removed after
checking literal references and dynamic-reference sites. The handoff's original
six-symbol estimate was not treated as a deletion target.

Removed unused sidebar footer/pulse rules and their animation, chrome-card,
heading-glow, encounter sprite, retired manager iframe, unused whiteout-phase,
and unknown-killfeed styling. Shared logo and active phase/killfeed styles remain.

Validation: Gen3/state/render/route/SVG/OBS selection passed 757 tests. Hydrated
RR and R/B `_build_status_html` output exactly matched the Phase1 implementation.
The full local suite passed 3703 tests with the same three documented skips;
portable CI passed 3398 selected tests with the unchanged 308 named deferrals.
Required lint and whitespace checks passed. No test was removed or reclassified.
