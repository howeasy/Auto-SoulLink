# D0 Red/Blue scripted idle entry — model handoff

The explicit `tests/live/test_gen1_selected_idle.py::idle_enrollment` entry now defaults `variants` to `("red", "blue")` and forwards that pair to the existing `SelectedRun`. A caller can still provide an explicit pair override. The shared selected-run lifecycle, script host, Lua normal-button wrapper, source pins, enrollment/save oracles, and cleanup were not edited. This is an RC scope correction; prior Yellow evidence remains preserved and does not qualify Red/Blue.

The complete modeled file passed 19 cases with zero failures, errors, skips or deselection; focused Ruff passed. Receipts are `.cache/d0-rb-model.xml` and `.cache/d0-rb-model.txt`. No physical invocation was made. Root's independent review and a separate sole Red/Blue live grant govern the next run.
