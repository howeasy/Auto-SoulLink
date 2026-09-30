# Gen1 Pure owner feedback fixes — 2026-09-29

Owner reports: post-trade player sprite corruption until area change; trade event log shows keys; full calculator still presents Radical Red; OBS sprites tiny; embedded battle calculator displays only Move 1.

Task checkout `C:/slink-wt/gen1-pure-feedback`, branch `codex/gen1-pure-feedback`, base `abc6bf28cf0e16d1c2c276f768e4d58f35dfec11`. Owner subsequently authorized local master integration and matching JAR installation; delivery is recorded below. No push, emulator run or release claim occurred. All author workers acknowledged exact disjoint files; coordinator alone records guide/register.

## Changes and reuse

- Native Pure trade saves/restores movement mode, then reuses native `InitMapSprites`, `LoadPlayerSpriteGraphics` and `UpdateSprites` after presentation restoration and before full save. Font-loaded bit temporarily forces upper walking-frame reload; the entire original font flag byte is restored. The source-bound graphics model shows why the first screen restore leaves font bytes in sprite VRAM. Actual native engine facts stay in the Pure assembly, while existing native engine routines supply restoration.
- Shared trade journal resolves the received mon from the post-swap link and uses per-player adapter names, before existing name-cache fallback. This includes trade evolution and escaped nicknames. Historical persisted event text is not rewritten.
- Shared calculator bridge refreshes its UI data tables on same-generation dex changes and updates the page title from the adapter profile. Pure adapter owns `name: pureRGB`; no game-id branch was added to the server.
- Pure sprite adapter owns its 96-pixel canvas / 56-pixel cell / 20-pixel padding facts. Shared CSS owns the contextual OBS frame size. At 1920×1080: party frame 40→58px, focus 40→80px; at 640×480 screenshots visibly improve. Existing dashboard/encounter frame footprints and board combatant sizing are preserved.
- Shared embedded preview retains every occupied move: damaging range, `Status`, legitimate `0–0%`, or `Unavailable` for lookup/calculation failures. Empty slots remain absent. Four damaging moves already rendered correctly; zero-result and error filtering caused the reported one-row shape.

## SOURCE and MODEL evidence

Production-source digest (six runtime files, sorted path + NUL + raw bytes + NUL): `9577ac128c6a5ecd359e7ccca1e89dfbb4b52a44e11506e31a24c26545309a63`.

Pinned Pure source `7e7a46535ca332ad24ecb02e326ea2f75e79ebb9`; RGBDS v1.0.3. Primary facts: `home/reload_sprites.asm:17-18` reloads sprites then font; `ram/vram.asm:14,21` aliases font and upper NPC sprite tiles; `home/text_script.asm:161-169` supplies the ordinary close-text sprite-reload tail bypassed by foreground trade.

| Replay | Red before fix | Green after fix |
| --- | --- | --- |
| Assembled native trade + pinned native graphics effects | 8 failed / 3 passed (walking/bike/surf/lava, unrelated font flags) | 11 new pass; 39 new + trade-save checks pass |
| Completed native trade → event journal → rendered log | Gen3 3 failed / 1 passed; Pure key-as-text failures; captured owner event has the same shape | 13 new pass, Gen3 first; 92 adjacent pass |
| Actual Chromium normal/hardcore HTML + source-winning bridge | RR title remains; pure→vanilla Gen1 retains Pure Voltorb types | Both page variants/profile transitions/live import/positive damage pass, 0 console errors/warnings |
| Real OBS templates → adapter HTML → Chromium geometry | 12 failed / 1 passed | 15 browser geometry checks pass; 142 scoped checks pass |
| Actual board attribute → actual preview JS → compiled engine | Four damaging controls pass; 6 status/immunity/error failures | 12 new pass; 53 preview/stats/bundle/dashboard checks pass |

Combined selected suite: 426 passed and one old exact calc-profile expectation failed because `name` is new. That expectation was updated; the complete profile + browser group then passed 19/19. Test-only import/lambda hygiene changes subsequently passed their native (39), preview (12), and profile/browser (19) groups. Thus all 427 selected cases have current passing evidence across those runs; no production source changed during test-only closure. All exercised groups have 0 skips. Scoped Ruff and diff whitespace checks pass after closure.

Canonical combined command (20 files):

```powershell
$env:SLINK_RGBDS_BIN='C:/slink-wt/gen1-pure-feedback/.cache/toolchains/rgbds103'
& 'E:/Google Drive/SLink/.venv/Scripts/python.exe' -m pytest tests/unit/test_trade_log_names_feedback.py tests/unit/test_calc_page_feedback.py tests/unit/test_obs_sprite_feedback.py tests/unit/test_calc_board_moves_feedback.py tests/unit/test_gen1_purergb_trade_restore_feedback.py tests/unit/test_gen1_trade_save.py tests/unit/test_calc_profile.py tests/unit/test_calc_preview.py tests/unit/test_calc_preview_stats.py tests/unit/test_calc_purergb.py tests/unit/test_calc_bundle.py tests/unit/test_calc_names_multigen.py tests/unit/test_gen1_purergb_adapter.py tests/unit/test_sprite_html_contract.py tests/unit/test_state_gen1_trade.py tests/unit/test_state_trade_hardening.py tests/unit/test_state_trade_uncertain.py tests/unit/test_state_trade_watchdog.py tests/unit/test_obs_lifecycle.py tests/unit/test_overlay_catalog.py -q -rs --tb=short
```

## Rebuilt cartridge artifacts

All three overlay UPS files, symbols/maps, profile, signal/admission pins and UPR INI entries regenerated. Checkpoint regeneration is byte-identical to the existing file. Independent rebuild `tools/build_purergb_overlay.py --check` reproduces every published artifact byte-for-byte. Toolchain directories use read-only no-space junctions because w64devkit shell cannot parse the original `E:/Google Drive` path. Initial failed build produced no publication; final build/check succeeded.

Artifact/INI/JAR-pinning suite: 64 passed, 0 skipped. An earlier attempt overlapped the cache rebuild (one transient missing-ROM prerequisite skip) and used the old explicit CRC pin (one failure); that attempt is not evidence. The final suite ran after the rebuild with the new CRC pin and passed fully.

| Title | Overlay SHA-1 | Header CRC |
| --- | --- | --- |
| pokered | `43642f1248197ecbc8247ad6038b56c72264cbbc` | `ABD1` |
| pokeblue | `237cf7cf80376b6ab0e18969266a38fe4e0e5f6d` | `E593` |
| pokegreen | `df71763fd52eff57bc2c4492add85d4bd0d82070` | `E3B1` |

UPR patch `0011-slink-pure-overlay-trade-sprite-restore.patch` updates exactly the new overlay entry CRCs. New fork JAR is a resource-only update of the existing allowed fork: all ZIP entries except `com/dabomstew/pkrandom/config/gen1_offsets.ini` are byte-identical; no Java class changes. New SHA-256 `db24703b4da3cea08386c6368ec1acbf37c8fc5e34935348881348581056d0f6`. Java 8 CLI, all options off, produces byte-identical output for all three clean and all three overlay cartridges (6/6). The new resource JAR lives in the ignored task cache and its digest is pinned in `data/upr_jars.json`; the main checkout cache has not been replaced.

## Independent review and delivery

Independent isolated reviewer approved source/model candidate `9ece893c4b2bcd04d975533fa7362e0037b68bfa` with no material blocker. Review receipt: `docs/gen1_pure_feedback_review_2026-09-29.md`. Reviewer independently ran 116 checks (52 feedback + 64 artifact/INI/JAR), all passed with 0 skips, and read-only verified actual JAR resource/pin and provenance. Author workers did not review their own changes. Runtime-source digest remained unchanged after review.

PHYSICAL remains unverified for these changes: no emulator or actual OBS run was used. Existing owner run is PureRed `rand_overlay`; changing server/CSS/bridge alone cannot repair graphics code already inside that randomized cartridge. Fresh provisioned cartridges use the rebuilt overlay. An existing-run ROM upgrade must preserve the randomization and saves and regenerate matching admission/contract hashes; do not silently replace or restart the owner's played run.

Next action: reload SLink processes and web/OBS views as appropriate; provision updated Pure cartridges or prepare a compatible upgrade of the existing randomized run, then perform a normal-input post-trade movement retest. No release readiness inference. The same font restore ordering exists in pokered; vanilla follow-up is prospective and outside this owner Pure feedback scope.

## Owner-authorized local delivery

2026-09-29T23:56:19Z: owner selected Merge fixes and install JAR. Local master fast-forwarded to reviewed documentation cut `883660a7` (runtime candidate `9ece893c`). Installed `.cache/slink-upr/PokeRandoZX.jar` has SHA-256 `db24703b4da3cea08386c6368ec1acbf37c8fc5e34935348881348581056d0f6`, is allowlisted, and is recognized as a fork by the destination pipeline. Original JAR preserved as `.cache/slink-upr/PokeRandoZX-pre0011-2026-09-29.jar` (SHA-256 `28292b595a411e78beef851e0cd5017a5d4ff592eca9a1db3f8939b0f7ab6e56`). Destination overlay ROMs/symbols/maps/native source were refreshed and all three overlay SHA-1s verified through the destination foundation resolver. Screenshots and CLI smoke evidence preserved under the main checkout cache.

The owned task Git worktree registration and `codex/gen1-pure-feedback` branch are removed. Filesystem residue remains at `C:/slink-wt/gen1-pure-feedback`: Git removal returned Windows permission denied; explicitly verified native recursive cleanup was rejected by automatic approval review as blocked by policy. The duplicate `.cache/slink-upr/PokeRandoZX-pure-feedback-install.tmp` also remains after native single-file cleanup was rejected by the same policy. No alternative deletion mechanism was attempted. The remaining folder is not a registered or active worktree.

No played ROM, save, live process or OBS session was changed. Existing processes need normal restart/refresh to load applicable server/UI changes. The existing played randomized cartridge needs a compatible code/contract upgrade for the native sprite fix; this remains a separate delivery action. No physical or release claim.
