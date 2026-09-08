# Ordered durable command stages

`lua/staged_command.lua` composes existing command adapters under one durable
outer command. The caller supplies a checked state store, ordered named child
adapters, a current physical-context callback, and final physical readback policy.
It supplies no ROM layout, frame authority, save path or physical effect itself.

The outer intent binds command ID/sequence, body digest, physical context and
stage names. Each child intent is persisted before its effect. A verified child
receipt is persisted before selecting the next child. Armed native work remains
pending; partial states/errors remain recoverable obligations. A completed child
is never applied again when later work or receipt publication fails.

`verify_completed(results, body, identity)` must prove current final physical
state before a completed sequence can produce its outer receipt. Optional
`receipt(results, body, identity)` converts those results to a generation's typed
wire receipt. The standard prepare/classify/apply/receipt methods are dot calls.
`current(command_id)` returns a detached current child intent. `stage(command_id)`
returns only its name/schema for inexpensive scope lookup. `completed(id, name)`
proves a child receipt was durably stored; it grants no authority.

Gen1 uses prompt-return, full-save, and read-only preparation stages. Other
generations can compose their own adapters without inheriting RBY memory or UI
rules. A replaced physical context cannot continue an old sequence by changing a
success flag; generation recovery remains a separate verified procedure.

`server/save_file_receipt.py` independently verifies a supplied complete image
against the existing typed SaveRAM file receipt, expected host and bounded frame
interval. Remote paths remain opaque and are never opened by the server. Gen1
uses it for both full pre-trade saves and the final original-trade save.
