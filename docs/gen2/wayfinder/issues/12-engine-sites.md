# Candidate Gen 2 execution-site table

Type: research
Status: resolved (2026-09-26; was open, blocked by 11)
Blocked by: 11 (closed)

## Question

Which pret routines become bus_exec sites for each lifecycle event (battle start wild/trainer, battle end + result, capture->party vs ->box, player faint at `UpdateFaintedPlayerMon`/`HandlePlayerMonFaint`, poison faint `DoPoisonStep`, whiteout at `Script_Whiteout` before `HealParty`, evolution species publish, NPC trade write, PC deposit/withdraw/release/ChangeBox, map load, bag ball received, save, CONTINUE, New Game, soft reset), with bank:address and expected bytes from the pinned build (ticket 11)? Input: Codex cx-8172d76c audit `docs/gen2/research/codex_engine_site_audit.md` (pending) and the Gen 1 site table shape `docs/gen1_engine_sites.md` section 3.

## Answer

Built (implementation ticket [`docs/gen2/issues/09-p2-engine-sites.md`](../../issues/09-p2-engine-sites.md)):
`tools/gen_gen2_engine_signals.py` generates `engine_site_specs.json` (bank:address + `expected_hex`) for
all three titles from the pinned build, published at `docs/gen2/gen2_engine_sites.md`. Byte-level ROM
verification is `tools/verify_gen2_rom_layout.py`; PHYSICAL confirmation on a running cartridge is the
`live_new_gates.inspect_run.json` receipt (see [ticket 20](../../issues/20-p3b-live-inspect.md)).
