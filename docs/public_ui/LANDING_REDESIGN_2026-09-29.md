# Landing page and README redesign

## Owner request and boundary

2026-09-29, Codex chat 01a0ef91-b9ba-7c40-a8fc-983d34f3d651:

> Redesign the landing page in the UI. Make the pokeball outlines black.
> Update the Github readme. Its close but still too technical in some spots and not focused on the game.
> Give other suggesstions.

Owner correction:

> Its also not on real cartridges. It doesn't have to be so whimsical.

Implement a restrained local Manager landing page and a plain, player-focused README.
Use BizHawk emulation wording. No public spectator site, hosting, gameplay changes,
new game support, emulator run, master merge or push is part of this grant.

Source cut: `883660a7cc6cefc0a9716fe09d4c2f5f9259395f`.
Task worktree: `C:/slink-wt/ui-landing`, branch `codex/ui-landing`.
Integration target: `master`, owner authority pending.
Exact grants and ACK are in the sole hook guide checkpoint under `ui-landing-readme`.

## Implementation and reuse decision

- Move the home composition into `_home.html` and its styles into `home.css`.
  Manager conditionally loads that stylesheet only for the home page. The board shell,
  run projection, route ordering, action URLs, theme tokens and buttons are reused.
- Replace three duplicated inline Poké Balls with `server/static/pokeball.svg`.
  Every outline, center ring and divider uses explicit black; the halves stay red/white.
  The shared rail uses the same asset on Manager and standalone pages. The README
  uses this asset too; its previous docs image path retains an identical export.
- Use the existing system body-font token for the landing content. Leave the board
  and navigation's existing font settings in place. Stack rules and setup on phones,
  retain keyboard focus styles and honor reduced-motion settings.
- Keep actual run data authoritative: live selection and pair counts still come from
  `_home_runs`; the template doesn't infer progress from process status. Status is
  displayed alongside pair counts, including running runs whose board is unavailable.
- Rewrite the README around playing, linking, teams, faints, battle planning,
  the memorial and streaming. Replace the stale launcher-only setup with the current
  player ZIP workflow. Remove hardware/test-count marketing and unsupported release
  claims; the games table describes current `server/manager.py:GAMES` choices.
- Game facts and runtime behavior remain in their existing modules. No adapter changes
  or new abstraction is needed for shared presentation.

## Verification

SOURCE: Reviewed Manager `GAMES`, `UNADMITTED_GAMES`, `_home_runs`, launcher/setup
links and the existing shared theme/shell contracts. README game availability is tied
to this checkout; it isn't a status claim about other generation worktrees.

MODEL:

```text
python -m pytest tests/unit/test_manager_pages.py tests/unit/test_manager_a11y.py -q -rs
31 passed, 1 skipped (patch/build/gen1_red.gb absent; pre-existing input-dependent test)

python -m pytest tests/unit/test_dashboard_contract.py tests/unit/test_board_css_coverage.py tests/unit/test_board_mobile.py tests/unit/test_manager_xss.py tests/unit/test_theme_tokens.py tests/unit/test_theme_contrast.py -q
64 passed
```

The existing home tests cover empty-state setup, running-first ordering, stored runs,
archive exclusion, counts and the active-run CTA. No new implementation-mirroring tests.

Scripted Chromium rendered the isolated Manager on loopback port 18095, using an
empty private data directory outside gameplay state. Visual checks: desktop 1440px,
phone 390px, narrow phone 320px with reduced motion, and light theme 1440px. No
horizontal overflow, missing images, failed HTTP resources or page errors. The three
brand images load; the New run link opens the actual form, setup anchor works,
and the keyboard skip link focuses `main-content`. Screenshots visually inspected.
Additional theme and populated-run presentation checks are recorded after final review.

PHYSICAL: Not run or claimed. These are presentation checks, not release qualification.

## Independent review and next action

Required on the frozen author commit by isolated non-authors, covering Standards and
the owner's Spec separately. Review results and final frozen cut will be appended
here before delivery. No master merge or push without owner authority.

Suggestions to present to owner: a short player setup guide, refreshed gameplay
screenshots, and a first-run readiness checklist on the run page.
