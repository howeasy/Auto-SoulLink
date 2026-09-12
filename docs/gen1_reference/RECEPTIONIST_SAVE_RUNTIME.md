# Receptionist and full-save runtime wiring

The selected native runtime can adopt the cartridge's actual unanswered
receptionist query. It checks the loaded companion, bank-qualified caller,
interrupt/stack checkpoint and exact query generation. A typed event creates one
durable native UI command and recovery obligation. The server calculates the
eligible linked-party mask from owned rule/identity snapshots.

Only that command's finite execution window permits the native menu to proceed.
The existing receptionist client handles query publication and the durable offer.
The server binds an offer to the current menu's token, generation, mask and party.
The original routine prefix and unchanged party/save/map checkpoint are required
for the return receipt; its ACK retires the UI obligation before queued trade
preparation can run. Cancel and CABLE CLUB keep their original cartridge paths.

Preparation now composes three durable stages: return from the partner prompt
where required, save the complete game state and verify its actual file, then
capture the final read-only preparation checkpoint. The complete save uses the
pinned `SaveGameData` copy geometry: trainer name, main world state, sprites,
current box, party, tile animation flag and checksum. It sets save status to2,
preserves every other SRAM byte and advances no emulator frames. Its source,
expected image, exact owned window and file readback are checked independently
before paired COMMIT. Both original trade animations and final save/file/return
verification remain mandatory.

The save kernel has24 complete32KiB comparisons against actual original
SaveGameData across R/B/Y (8 varied snapshots each). The reference routine runs
in an isolated cloned core with IRQs disabled so both transforms consume the
same held snapshot; this test-only CPU invocation is absent from production.
Evidence: `.cache/full-save-oracle.xml`,3 passes/16.94s. Python prediction and
the actual Lua writes both match every original output byte and save-status byte.

The shared staged-command adapter and remote save-image verifier contain no RBY
addresses. The generated layout and cartridge/source interpretation remain in
Gen1 modules. Transport queue draining runs between semantic ticks, respecting
the same I/O bounds and deadlines. A500ms control interval leaves a semantic tick
for offer/receipt delivery; grant expiry remains1000ms and native pacing limits
are unchanged.

Qualification boundary: the live test's fixture supplies an isolated linked run
and uses physical Up/A to open the real receptionist before the held service
starts. Query, mask, selection, offer, acknowledgements, prompt, saves, animations
and return then use the production TCP components. This is a query handoff, not
ordinary gameplay/bootstrap or default-launcher activation. Generated launchers
remain held_service. Controlled recovery after interrupted native UI/save work,
the remaining rule/storage/campaign matrices, packaging and the human release
gate remain separate RC obligations.

Final evidence: `.cache/receptionist-save-live.xml`,16 passes in663.97s with no
skips or deselection. This includes13 TCP cases and3 original-save routine cases,
with actual receptionist flow for canonical R/B,B/Y,Y/Y and reproduced-UPR Y/Y.
The TCP cases retain the unchanged native animation timing assertions.

Broad regression: `.cache/receptionist-save-full.xml`,4770 passes and the same
two Windows symlink skips,202.57s. Exact workflow bug-class Ruff rules pass and
257 project Lua files parse under explicit Lua5.4. Current collection inventory:
4625 unit,147 integration,227 live and45 duo nodes.333 acceptance requirements
have28 current source-pin registrations,104 stale and201 missing; these counts
are integrity accounting, not a full release verdict.

Shared helpers are isolated at97046232f4b17e883a7dfe9f19c5e3bb2f52bfb3 on
codex/shared-staged-command-v1, parentcfed9be. Five files only, including their
contract/tests. The exact candidate passes3019 tests with15 existing baseline
environment/fixture skips and11 subtests;226 Lua5.4 parses and required Ruff pass.
The exact published commit is green in GitHub run34182490380. Shared frame-window
budget/clock correctioncfed9be is also green in run34168470179; consumers were
notified of the corrected version.
