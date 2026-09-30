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
The final pass also confirmed the actual `funtastic-grape` theme at 1024px and
presentation-only fixtures with running, unavailable-board and stopped rows at
1440px and 320px. A long unbroken run name and its primary CTA wrap without overflow.
Fixtures were rendered directly into a test page; no Manager registry or game state
was populated. Current statuses remain visible when counts exist or are unavailable.
All 33 README link/image references were checked for local-path existence; no missing
local targets. Both SVG export files are byte-identical. External URLs were not fetched.

PHYSICAL: Not run or claimed. These are presentation checks, not release qualification.

## Independent review and next action

Frozen author commit: `dee76923a8553a0468411674b72ecc4d9a5a9280`.
Two isolated non-authors reviewed the same nine-file diff against the source cut.
Both sent explicit read-only grant ACKs and reported a clean worktree and correct HEAD.

### Standards

`/root/landing_standards`: **APPROVE**, no actionable documented-standard breach or
Fowler-smell finding. Shared Jinja/CSS placement, conditional home stylesheet loading,
theme tokens, asset reuse, visible focus and reduced-motion rules follow the established
contracts. README family choices and ZIP/launcher setup match current source.
Reviewer performed source reads only and did not independently exercise the browser.

### Spec

`/root/landing_spec`: **APPROVE**, no concrete missing requirement, incorrect setup
instruction, unsupported hardware/qualification claim or extra feature implementation.
The reviewer checked restrained gameplay copy, literal black SVG outlines, current
Manager game choices and ZIP setup, retained documentation targets, and supplied
desktop/mobile screenshots. No tests or integration performed by reviewer.

Zero findings on each axis. Reviewer boundaries remain distinct from author checks.

Next action: present preview and revised README; obtain owner authority before applying
this reviewed cut to local master. GitHub publication remains unperformed.

Suggestions to present to owner: a short player setup guide, refreshed gameplay
screenshots, and a first-run readiness checklist on the run page.

## Interface polish coverage

Full scope: home composition, shared Poké Ball brand asset and its rail placement;
Jinja2 and established plain CSS. No gameplay or game-adapter scope.

| Category | Inspected evidence | Result |
|---|---|---|
| Typography | Heading/body font token, balanced headings, wrapping, long names | Clear |
| Surfaces | Structural dividers, run rows, focus rings, phone hit targets | Clear |
| Animations | Brief border/background hover transitions, shared button press, reduced motion | No entrance animation added; reduced-motion layout verified |
| Icons | Shared brand image, explicit black outlines, decorative empty alt | Clear |
| Performance | Home-only stylesheet, existing shell, explicit transition properties | Clear |

| Location | Before | After | Why |
|---|---|---|---|
| `manager.html`, `_home.html` | Single stacked introduction | Hero, core rules, actual runs, setup and utility links | Clear hierarchy and direct primary path |
| `home.css` | Pixel heading and brief home styles in board CSS | Scoped system-font content, responsive grids and readable spacing | Legible prose; preserves established styling system |
| `pokeball.svg`, `_rail.html`, docs logo | Repeated theme-colored SVG outlines | One shared UI asset with literal black outlines and a docs export | Consistent requested brand treatment |
| `_home.html`, `home.css` | Counts could replace visible process status | Status remains beside pair counts | Avoids confusing a running process with gameplay progress |
| `home.css` | Single-column desktop setup and fixed run-name truncation | Two-column setup; narrow-screen stack and long-name wrapping | Preserves content at narrow sizes |
| `home.css` | Inherited link underlines on primary controls | Explicit button link decoration | Clear button affordance |

Considered but rejected: an animated gameplay demo (owner requested restrained tone
and direct setup); new per-game palettes (existing theme tokens already cover the
page); global font changes (the requested landing content is the bounded scope).

Verdict: **APPROVE** within SOURCE/MODEL presentation scope. Not verified: full
screen-reader narration, all remaining palettes, physical gameplay or release readiness.


## Owner-approved integration, 2026-09-30

Owner: "Looks good. Commit to main". The repository's primary branch is `master`.
Authority now includes local master integration and the required owned task-worktree
retirement. It does not include GitHub push or a release claim.

Current integration base: `623e95252e63e2d0d34d4c9ae5420799587f9ab3`.
Since the original UI cut, main gained Emerald support and broader cartridge-form
support. Reconciled that main cut in the existing UI task worktree. README conflict
resolution preserves the approved player-focused rewrite, adds Emerald to the
available games, removes its old disabled label, and describes preparation/randomizer
options by game capability. No hardware verification wording is restored.
The Manager's current `form.randomizer_games` conditions and `gen1()` implementation
remain identical to main; the landing changes do not replace them.

Foreign root untracked files `lua/memory_gba.lua` and
`server/adapters/gen2_crystal.py` are excluded from staging and cleanup. Their SHA256
pins before integration are, respectively:
`8518B82CF0FD10141C8029D05781E2394E7D5DFE42A27883CCF8E6B7EBE85B55` and
`0590A8B52E2E5E0938CA2D7E0206BACE50B7AE826DE0995EBA2933A27AC65D06`.

Reconciled SOURCE/MODEL checks: the same eight focused Manager/board/theme modules
reported **95 passed, 1 skipped** in 7.32 seconds. The skip remains the absent
`patch/build/gen1_red.gb`, not a present-but-wrong input. Merge conflict markers are
removed and the scoped diff check is clean. Frozen reconciliation independent
review precedes final master delivery; no PHYSICAL run is added.
