# Native partner consent and return over TCP

The native runtime now selects the actual RBY partner YES/NO executor. Consent
is a typed durable event checked by the production server policy. The runtime
persists the prompt intent before staging it and consumes current command-scoped
frame windows while the original prompt runs. It requires the observed native
service/prompt/choice sequence and unchanged party/save/UI state.

After the exact decision acknowledgement, the next preparation or abort command
owns the prompt's return. Its closure intent is persisted before the release
write. The return window is independently bound to the acknowledged prompt and
the same live context. Preparation captures its read-only checkpoint only after
the native prompt has returned. A failure in that read-only stage cannot repeat
the already completed closure.

Decline/B returns a native refusal and closes both participants without COMMIT,
animation, evolution or save calls. A YES response received after the persisted
offer deadline also closes through the abort path. The initiator has a read-only
abort receipt; the prompted player must provide verified native closure evidence.
The server cannot accept an idle/no-effect claim from the prompt owner.

The expiry test advances only the transaction clock and then answers the actual
prompt. It does not qualify automatic UI dismissal while a user remains idle.
Mid-prompt disconnect, queued-command retirement after interruption and controlled
recovery remain separate work. The native routine's result3 means unavailable,
not a timer expiry.

The shared journal, command executor, driver, operation windows, frame pacer and
host owner are reused. RBY layout/readback and prompt/abort rules remain in:

- `lua/gen1_partner_prompt_executor.lua`
- `lua/gen1_prepare_after_prompt.lua`
- `lua/gen1_trade_abort.lua`
- `server/gen1_prompt_execution.py`
- `server/gen1_trade_abort_receipts.py`

The native network tests now use NativeTradePolicy directly. Their linked-party
bootstrap and receptionist-origin event remain declared fixtures; partner consent
does not. Natural receptionist initiation still needs the ordinary observation and
execution lifecycle. Default launchers therefore remain held_service, and this
cut does not declare the full Gen1 RC ready.

Performance qualification keeps the existing native animation timing bounds.
The shared JSON parser scans ordinary ASCII spans while retaining its strict
escape/Unicode/resource checks; the shared execution window compares its fully
validated flat scope without per-frame JSON conversion. Native empty durable
sync polls use a one-second interval. Completion events, independent control
renewals, per-frame authorization and grant expiry retain their original rules.

Stable evidence: `.cache/prompt-runtime-final.xml`,8 passes in432.37s, no skips.
Canonical normal-case COMMIT playback took48.10-48.69s for2618 frames (43.83s of
cartridge time). Reproduced UPR Y/Y took51.37/51.60s for2788 frames (46.68s of
cartridge time). The delayed-renewal case remains a separate injected fault.
Both endpoints still require exactly one original animation, complete native/file
verification, empty durable queues and held return. Evidence paths and current
requirement-pin accounting are in `.cache/prompt-cut-evidence.json`.

The focused parser/window/canonical suite passed154 checks and252 project Lua
files parse under explicit Lua5.4. Collection inventory is4566 unit,147 integration,
219 live gates and45 duo cases. Collection is not execution evidence.

The next verified save boundary is recorded in [pre-trade save work](PRETRADE_SAVE_NEXT.md).

Final broad unit/integration regression: `.cache/prompt-runtime-full.xml`,4711
passes and the same two Windows symlink skips,199.83s. Exact workflow bug-class
Ruff rules pass. These results qualify this slice and do not waive the remaining
full RC gates.

The generation-neutral window/pacer/codec modules are isolated in local commit
3649e2d1b35ccef124acd33e1c75ff10b0cce310 with their tests and
[shared contract](../shared-native-frame-primitives.md). Exact-tree validation:
2991 passes,15 existing baseline environment/fixture skips,225 Lua5.4 parses.
The user subsequently approved publication. The frame correctioncfed9be is pushed
and green in GitHub34168470179. The later
[receptionist/full-save continuation](RECEPTIONIST_SAVE_RUNTIME.md) supersedes
this evidence cutoff with16 live passes and4770 broad passes; its shared helper
cut97046232 is green in GitHub34182490380.
