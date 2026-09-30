# T3 native v2 binding status

The v2 client path is inert in production. All four target headers under
`patch/src/trade_targets/` still have `SLINK_TARGET_READY=0`.
`tools/gen_gen3_profile.py:native_block(title)` emits no native block for a held target;
setting READY alone currently raises a missing-qualified-binding error. RR's default
native block remains its published v1 ABI.

The parser and `lua/gen3/native.lua` mailbox/epoch tests are SOURCE and MODEL evidence.
Their injected v2 profile and arena are not target admission. `trade_capable()` remains
false, and v2 panel/control binding remains unavailable.

Before any v2 client path can be enabled, the generator must emit a qualified READY=1
binding for the admitted artifact. Resolving `native.BASE` from that target's
`SLINK_TARGET_ARENA_BASE` is an **open prerequisite**: all shipped target BASE macros are
currently zero, and a diagnostic candidate must not be substituted. The binding also
needs the matching per-title entry/safety routing and capability qualification.
The qualified-target emitter must also include **every** `SLINK_OP_*` key from the
canonical ABI. That positive READY=1 emitter and its synthetic control remain an open
prerequisite; the current function deliberately refuses READY=1 rather than guessing a base.

R4 checks pin every mailbox field used by the client, compare profile opcodes with
the canonical `abi.h` enum, and compare Python layout facts with host-C
`sizeof`/`offsetof`. Native epoch zero permits only a fresh handshake; an unreadable
epoch or a different nonzero epoch refuses work. These checks do not qualify a native
save, trade, Match Call, or physical v2 target.

The R4 Emerald NPC-trade receipt exercises observation on the clean vanilla cartridge.
It is separate from the unqualified companion-v2 path described here.
