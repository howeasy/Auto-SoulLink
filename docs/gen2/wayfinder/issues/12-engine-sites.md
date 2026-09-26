# Candidate Gen 2 execution-site table

Type: research
Status: open
Blocked by: 11

## Question

Which pret routines become bus_exec sites for each lifecycle event (battle start wild/trainer, battle end + result, capture->party vs ->box, player faint at `UpdateFaintedPlayerMon`/`HandlePlayerMonFaint`, poison faint `DoPoisonStep`, whiteout at `Script_Whiteout` before `HealParty`, evolution species publish, NPC trade write, PC deposit/withdraw/release/ChangeBox, map load, bag ball received, save, CONTINUE, New Game, soft reset), with bank:address and expected bytes from the pinned build (ticket 11)? Input: Codex cx-8172d76c audit `docs/gen2/research/codex_engine_site_audit.md` (pending) and the Gen 1 site table shape `docs/gen1_engine_sites.md` section 3.
