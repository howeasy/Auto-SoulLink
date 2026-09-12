# Native R/B panel ABI-3 protocol

The required mailbox layout now occupies the existing30-byte R/B reservation:
magic0–3, ABI4, capabilities5, heartbeat6–7, disabled SFX head/tail8–9,
FIFO10–13, overflow14, panel controls15–21 and8canary bytes22–29.
Yellow retains its trade-only artifact and no permanent panel mailbox.

Panel controls are state15, requested page16, page count17, generation18,
acknowledgement generation19, transfer bitmap20 and client lease21. States are
closed0, awaiting1, staged2 and displayed3. The ROM owns requests, display and
closure; the qualified client owns generation publication and lease refresh.

`lua/staged_panel.lua` is the reusable publisher. It knows no cartridge addresses
or glyph mapping. An endpoint supplies byte reads/writes, availability, page
height, lease bound and painting. Publication sets an odd generation, clears the
transfer bitmap, writes the count/page contents, then publishes the next even
generation and STAGED. Availability/page/generation drift or a paint exception
leaves publication incomplete. Only the current owned generation can refresh or
revoke its lease. `memory_gb.lua` supplies RBY's20×18 formatter and ABI addresses.

The existing VBlank hook performs beacon, heartbeat, lease and transfer accounting.
It never calls PlaySound. Because AutoBgMapTransfer runs before this hook, the
hook records which actual top/middle/bottom portion completed. Reveal requires
all three bits, an even generation different from the prior ACK, an unchanged
captured generation, live lease and intact canary. The palette stays blank during
staging; the native routine reveals then acknowledges that generation.

A advances and wraps. B or START closes. Held opening input cannot advance a
page. Missing/odd/stale/incomplete data closes within180frames; a disconnected
client's unrefreshed lease closes a visible panel. Generation changes or canary
failure close without publishing another page. The startup WRAM clear in pinned
pokered home/init.asm clears the mailbox on native reset; interception/rebind of
host reset, load-state and rewind remain separate unqualified runtime work.

The R/B live gate drives twelve scenarios per cartridge: missing data, wrap,
B, START, held A, odd generation, stale even generation, changed generation during
transfer, disabled BG transfer, lease expiry, visible generation change and canary
failure. It observes all three native BG portions before each reveal, checks actual
VRAM against the page, and verifies return to the native map with unchanged party
and SaveRAM. The test injects its negative-control faults deliberately.

Remaining panel qualification includes broader map/Safari and Pokédex states,
full reset/rebind behavior under the eventual host controller, capability downgrade,
and the final combined release run. A passing protocol slice does not authorize
ordinary or bounded native execution in the held-service launcher.

Panel ABI-3 continuation: implemented locked mailbox controls, odd/even staging, three actual BG portions before reveal/ACK, A wrap, B/START close,180-frame missing-data/lease closure, changed-generation refusal and persistent canary detection. R/B each passed12 native protocol scenarios; the full13 combined-artifact cases and7legacy menu/launcher cases passed. Broad unit/integration:4,288passed/2existing Windows symlink skips; subsequent focused manifest/publisher/panel/rebuild checks:102passed. Parsed241 project Lua files plus the old-reader fixture. Evidence:.cache/panel-full-first.xml,.cache/panel-final-companions.xml,.cache/panel-legacy-live.xml,.cache/panel-final-targets.xml. Shared staged_panel9f7f6c7 is published. Remaining: broader panel maps/Pokedex and controller/reset qualification, then host/native authority and production runtime integration.
