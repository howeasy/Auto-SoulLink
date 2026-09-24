# `gen3_rr` pack

Generated. Do not hand-edit anything here — run `python tools/gen_gen3_profile.py`
(`--check` is the P2 exit condition "profile diff = 0 vs today's literals").

## `profile.json`

First cut (P2 card C2-2). One title, `radical_red`, parsed out of the literal table
`GEN3.profiles.radical_red` in `lua/games/gen3_frlge.lua` — the only source of today's
addresses. Sections and the verbatim-Thumb rule are the same as `gen3_frlg`
(see `data/games/gen3_frlg/README.md`).

Pins: RR 4.1 base `rom_sha1 964f951a0fdaf209e4ea1344883ef0d557bb3a80`,
`rom_md5 8529f3a45d32bce4da637976fcf269d4`.

Notable CFRU/DPE facts that ride in `derived`: `PARTY_IN_SB1: false` (SB1+0x38 is a shadow copy —
reads and writes must use the vanilla EWRAM party at `PARTY_BASE`), `CFRU_NO_ENCRYPT: true`,
`CFRU_COMPRESSED_BOX` with the 25-entry `CFRU_BOX_BASES` list (the Lua `base + 1740*n`
expressions, evaluated).

## `native` (kind `companion`)

Present only in this pack. It is the SLink companion patch's ABI, lifted from the two production
modules that carry it as literals today: `archive/gen3-old-client:lua/mailbox.lua` (mailbox base, blob/text/menu buffers,
battle-notification struct, event ring, the plain-EWRAM config bytes, the SOULLINK info struct,
ghost and swap structs, opcode ids) and `archive/gen3-old-client:lua/peer_ghost_npc.lua` (object-event base, the
`gMain.callback2`/`CB2_Overworld` field gate, sprite base, OBJ palette buffer, camera Y).
`native._src` maps every name to its `file:line`, so each address is traceable to the line it
came from and `tests/unit/test_gen3_profile.py` re-derives all of them independently.

Not yet lifted (relative expressions rather than literals, so a first cut cannot parse them from
an assignment): the mailbox field offsets `O_SIG…O_RESULT` (a single multi-assignment at
`archive/gen3-old-client:lua/mailbox.lua:17-18`) and the `MB.GH_*` / `MB.INFO_*` sub-field offsets written as `MB.GH + n`.
`lua/gen3/native.lua` needs them before P5; pinning them against `patch/src/ADDRESSES.md` is the
follow-up.

The `native` block describes the **companion** artifact kind only; a clean RR ROM has no mailbox
and `native.lua` must refuse rather than read these addresses.
