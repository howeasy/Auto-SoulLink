# Shared NDS ARM/Thumb helpers (`tools/nds_isa.py`)

Pure-Python, dependency-free ARMv5TE (ARM946E-S) encode/decode helpers used to build and
validate ROM detours and bootstraps. The module targets ARMv5TE (the ARM9, ARM946E-S); the NDS
ARM7 is ARMv4T and lacks BLX, CLZ and the other ARMv5 additions, so none of this applies to it.
Gen 4 and Gen 5 NDS companions share them. Gen 3's
`tools/pin_gen3_site.py` is Thumb-only and is unchanged. Tests: `tests/unit/test_nds_isa.py`.

## Conventions

- **Code pointer**: bit 0 carries the ISA. Odd = Thumb, even = ARM (an ARM pointer must also have
  bit 1 clear). **Plain address**: bit 0 cleared. `thumb_detour` / `arm_detour` take a code pointer
  for `target`; the low-level encoders take plain addresses.
- Encoders take the site address (where byte 0 is written) and return little-endian bytes.
- Every refusal is a subclass of `NdsIsaError`: `IsaRangeError`, `IsaAlignmentError`,
  `IsaWrongFormError`, `IsaEncodingError`, `IsaDecodeError`, `ReplayRefusedError`. Nothing is
  clamped, truncated or silently rewritten.

## PC rules (ARM ARM)

| Form | PC value | Reach / alignment |
|---|---|---|
| Thumb `BL` pair | site + 4 | signed 23 bit, -0x400000..+0x3FFFFE, even target |
| Thumb `BLX` imm pair (to ARM) | Align(site + 4, 4) | -0x400000..+0x3FFFFC, target word aligned; site may be 2 mod 4 |
| Thumb `B` | site + 4 | -2048..+2046 |
| Thumb `B<cond>` | site + 4 | -256..+254, cond 0..13 (AL and 0xF refused) |
| Thumb `ldr rt,[pc,#imm]`, `add rd,pc,#imm` | Align(site + 4, 4) | +0..+1020, word aligned literal, rt/rd r0-r7 |
| ARM `B` / `BL` | site + 8 | -0x2000000..+0x1FFFFFC, word aligned |
| ARM `BLX` imm (H bit) | site + 8 | -0x2000000..+0x1FFFFFE, target Thumb (even) |
| ARM `ldr rd,[pc,#+-imm12]` | site + 8 | +-4095, word aligned literal |

## Supported forms

- Thumb: BL, BLX(imm), B, B<cond>, BX Rm, BLX Rm (Rm = PC refused), `ldr rN,[pc,#imm]`, ADR,
  PUSH {r0-r7[,lr]}, POP {r0-r7[,pc]}, MOV (high-register, no flags), NOP (`0x46C0`), and the 8-byte
  `ldr r3,[pc]; bx r3; .word target` veneer (`thumb_entry_veneer`, byte-identical to Gen 3
  `thumb_entry_jump` for a Thumb target; the site must be word aligned; r3 is clobbered, LR kept).
- ARM: B/BL with condition, BLX(imm), BX/BLX Rm, `ldr rd,[pc,#+-imm]`, STMFD sp! (r0-r14; PC in a push list is UNPREDICTABLE and refused), LDMFD sp! (r0-r15; a PC
  in the pop list makes it a branch and is allowed),
  NOP (`mov r0,r0`; ARMv5 has no NOP hint), and the 8-byte `ldr pc,[pc,#-4]; .word target` veneer
  (an LDR to PC interworks on bit 0 under ARMv5T, so a Thumb target keeps bit 0).
- `thumb_detour(site, target, kind, cond=None)` / `arm_detour(site, target, kind, cond)` return the
  exact replacement bytes. `kind` is `bl`, `blx`, `b`, `bcond` (Thumb) or `b`, `bl`, `blx`
  (ARM), or `veneer` (either ISA).

## Refused (named errors, tested)

Out-of-range displacement; odd or misaligned site/target; ISA-wrong forms (Thumb or ARM `BL`/`B`
to the other ISA must use BLX or a veneer; BLX(imm) always switches ISA, so a same-ISA target is
refused; ARM BLX(imm) is unconditional only); unaligned literal; literal behind a Thumb `ldr`/ADR;
registers or lists outside the form (`push {r8}`, `pop {lr}`, ARM `push {..,pc}`, empty list); `bx pc`.

## Interworking table

| caller \ callee | Thumb | ARM |
|---|---|---|
| Thumb | `BL` | `BLX` (imm) |
| ARM | `BLX` (imm) | `BL` |

`classify_code_address(ptr)` returns `(isa, plain)` (strict about ARM word alignment),
`code_pointer(isa, addr)`, `needs_interwork(caller, callee)`, `call_form(caller, callee)`.

## Call-site scan (`find_bl_sites`)

Returns decoded BL/BLX(imm) candidates at every halfword (Thumb) or word (ARM). It is a pattern
match, not control flow: literal pools, tables and the other ISA's code can look like calls, and a
Thumb scan can desynchronise mid-instruction. A BL whose first half is the buffer's last halfword is
not reported. Results are candidates to confirm against a symbol or second source.

## Replay planning (`plan_replay`)

Given the bytes displaced by a detour, `plan_replay(displaced, old_addr, new_addr, isa, pic_offsets)`
returns a plan with one step per instruction. Actions: `verbatim` (recognised position-independent
family), `reencoded` (PC-relative B/BL/BLX/B<cond>/literal load/ADR re-encoded to keep its original
**absolute** target from the new address), `asserted_pi` (listed in `pic_offsets`: the caller's
explicit claim, copied verbatim), `refused`. A PC-relative instruction whose original target lies
inside the displaced span is re-pointed to the same offset in the moved copy (a literal or loop
head that travels with the code); if that relocated target does not fit the encoding the step is
refused. A `pic_offsets` entry that is not the start of a decoded instruction (mid-instruction or
past the span) makes `plan_replay` raise `ReplayRefusedError` instead of being ignored; so does an
entry naming a PC-relative instruction (B/BL/BLX, B<cond>, literal load, ADR), which is always
re-encoded and can never be asserted position independent. `plan.ok` / `plan.refusals`; `plan.replay_bytes()` raises
`ReplayRefusedError` unless every step is safe. Refused: a re-encode that does not fit (the Gen 3
Emerald CallCallbacks case, where a Thumb literal load cannot reach backwards), instructions that
read PC through a register (Thumb `add rd,pc`, ARM `add rd,pc,#n`, `ldr` pc-relative with writeback),
unclassified instructions, and a span that ends inside a Thumb BL pair. Position independence is
decided by an opcode-family table, deliberately narrow: anything not in it is refused, not assumed
safe. A replayed call sets LR for the new address; the caller's continuation must account for that.

## Evidence in the tests

Hand-computed ARM ARM vectors with boundary cases (`VECTORS`, `REFUSALS`); 2000-iteration
random round trips for every form; 17 source-mutation controls (PC bias, range, alignment mask,
bit 0, H bit, literal base, decoder bias, PC-register-read checks) each of which must fail a vector, plus a clean control;
real-ROM tests on the decompressed ARM9 of Black and Black 2 (prologues `0xB538` decode as
`push {r3-r5,lr}`; every decoded scan BL re-encodes to the ROM's own bytes; one caller is
hand-decoded with independent arithmetic). The pinned caller counts per function are regression
pins from this module's own scan, not independent evidence.

## NOT verified

- No instruction is executed; nothing models the pipeline, caches, TCM, write buffers or
  instruction-cache coherency after patching (a patched ROM region still needs cache maintenance
  or a non-cached path where it runs from RAM).
- No ARMv5TE extensions beyond the forms above (no CLZ, saturating/DSP multiplies, LDRD/STRD, PLD,
  coprocessor, Thumb-2). They decode as `unknown` and are refused for replay.
- The `pi` family table is coarse (by opcode family and register fields). It does not prove an
  instruction is safe to move in context (flags, condition state, `sp`/`lr` assumptions).
- The Thumb BLX(1) second-halfword bit-0 rule (bit 0 must be 0) is enforced conservatively (bit 0 set is
  refused); this follows the ARM ARM text but was not exercised against hardware.
- White and White 2 were not measured; the pinned function addresses are Black/Black 2 only.
