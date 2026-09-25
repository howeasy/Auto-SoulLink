# Mobile layout and accessibility

Sources:

- `cx-303c3e92`: mobile layout and accessibility (SECOND_OPINION, read-only). Main source.
- `cx-c518530b`: theme contrast review (default, light, Funtastic Smoke).
- `cx-6214a81c`: board accessibility review (`_board.html`, `_macros.html`).
- `cx-f486dbca`: rail, theme picker and page shell review.

All at master a9bdce38.

## Summary

Below 900px use a top app bar with an off-canvas navigation disclosure, not a permanent icon rail
or bottom tabs; the current rail mixes run management, broadcast, tools, calc, debug, patcher and
spectator content. Stack each pair as A → bond/status → B below 600px. Use one dedicated polite
live region for pair formation and death, and give users a real pause control for live refresh.

The report's own strongest doubt: the phase-1 public IA does not exist in the repo yet. If it
settles on exactly three to five peer views, bottom tabs would give better one-tap reach.

The three narrow reviews add: edge tokens fail 3:1 in every audited theme, Smoke's brand colour is
used as text at about 1.6:1, pair status and HP rely on styling, and there is no skip link or
`aria-current` anywhere in the shell.

## Key findings

### 1. The phone layout is structurally broken (critical, high confidence)

- `.mk` is always rail plus main column: `server/static/board.css:65`.
- On phones `--scale-step` clamps to 22px and the rail is `8.2 × scale-step`:
  `server/static/slink.css:145-155`, `server/static/board.css:43-48`.
- So at 360px the rail is about 180px, leaving about **136px** after 44px of padding; at 400px,
  about 176px.
- Pairs stack below 760px, but only inside that cramped column: `server/static/board.css:397-400`.
- The 900px rule targets `.mgr-launcher` and `.mgr-rail`, not the real `.mk`/`.mk-rail`:
  `server/static/board.css:568-572`; the element is `.mk-rail` at `server/templates/_rail.html:9`.

### 2. Navigation: a disclosure drawer fits the current IA (high)

Destinations are many and mixed: New run `server/templates/_rail.html:18-23`; run list `:28-45`;
Broadcast, Twitch, OBS, Tools `:48-75`; Calc and Debug `:61-74`; standalone Overlays, Twitch, OBS,
Patcher `:76-100`.

[Material 3 navigation bar](https://m3.material.io/components/navigation-bar/guidelines) is for
switching views on small devices; [Apple HIG: Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars)
limits tabs to top-level sections, few in number, labelled, without overflow.

Proposal: a separate public/spectator rendering mode that omits admin links from the HTML (never
decide what is public with viewport CSS). Under 900px: a 56px sticky top bar with run identity and
a labelled **Menu** button; the rail as an off-canvas disclosure with `aria-expanded`,
`aria-controls`, Escape to close, focus return, `inert` background and a scrim; `aria-current="page"`;
a first-focus "Skip to live board" link. An icon rail would take 14-18% of a 360px screen.
[WAI-ARIA APG](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/).

### 3. Pair layouts at 360-400px (high)

- **A. Full-width vertical pair (recommended).** Keeps source order and the pair as the unit, no
  hidden partner, names get room, bond stays between the halves. Costs: taller page, repeated A/B
  labels, and the nickname ellipsis rule (`server/static/board.css:357`) must go. Stack below
  **600px**, unmirror B, add visible **Player A / Player B** labels, because column position
  stops carrying ownership once stacked.
- **B. Bond header plus two narrow columns.** Fastest comparison, but each half is about 160-170px
  at 400px before padding; only works as a simplified summary, not the same component shrunk.
- **C. Swipe or A/B selector (not recommended).** Hides the partner, gesture-dependent, easy to
  miss live changes, conflicts with reflow expectations.

[WCAG 1.4.10 Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html): content must work at
320 CSS px without two-dimensional scrolling. (This conflicts with `spectator-share.md`; see the
README.)

### 4. Do not make the morph target live (critical)

`#content` polls and morphs every two seconds with no live-region semantics
(`server/templates/_board.html:69`; also confirmed by `cx-6214a81c`). Making it `aria-live` would
read HP changes, timestamps and structural diffs aloud. Use one stable region outside `#content`,
present in the initial HTML: `role="status" aria-live="polite" aria-atomic="true"`.

Announce pair-level changes only: new link ("New link at Route 1: Red's Pikachu and Blue's
Eevee."), pair death, optionally run over. Never HP, unlinked captures, each partner force-faint,
memorialization after an announced death, or every poll. `polite`, never `assertive`.
[WCAG 4.1.3 Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html),
[WAI-ARIA technique ARIA22](https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA22.html),
[MDN: Live regions](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions/).

Events lack a unique ID (`server/server.py:1590-1600`). Duplicates to coalesce: a link is logged
once per player (`server/server.py:1988-1991`); a death can produce faint, partner force-faint and
memorialize records (`server/server.py:1790-1792`, `2013-2015`, `2044-2046`).

`cx-6214a81c` proposes a wider announcement set (disconnects, area changes, dead zones, run over).
That is a scope choice for the owner; both reports agree on one region outside `#content` and no
HP announcements.

### 5. Live refresh needs a user control (high)

[WCAG 2.2.2 Pause, Stop, Hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)
covers auto-updating content shown alongside other content. The "essential" exception is
arguable; a visible **Pause live updates / Resume** control is cheap. On resume, jump to current
state. Keep it outside the morph target and announce pause/resume in the same region.

### 6. Focus preservation is promising but unproven (high)

For: idiomorph's vendored default `restoreFocus:true` (`server/static/vendor/idiomorph-ext.min.js:1`);
the hook preserves `open` state and sprite attributes (`server/static/dashboard.js:292-357`); the
rail is outside the polled fragment. Against: refresh blocking uses `mousedown`/`mouseup`, not
keyboard focus (`server/static/dashboard.js:95-125`), so a keyboard user on a `<summary>` can be
hit by a poll. Contract: stable IDs on every repeatable control; record `activeElement.id`; hold
the swap while focus is in a board control; restore with `preventScroll:true` if the control
still exists, else focus the pair's heading, not `body`.
[2.4.1](https://www.w3.org/WAI/WCAG22/Understanding/bypass-blocks.html),
[2.4.3](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html),
[2.4.7](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html),
[2.4.11](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html).

### 7. Reduced motion is partly done (medium)

The board already drops transitions, HP animation and press scaling under `prefers-reduced-motion`
(the report cites `server/static/board.css:591-597`; the validator found the lines are 594-597).
Extend to every non-essential transition, smooth scrolling and the drawer.
[MDN: prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion),
[WCAG 2.3.3](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html) (AAA).

### 8. Meaning carried by colour or shape (high)

- HP bars have no progressbar role or name (`server/templates/_board.html:22-23`). `hp_bar()`
  has no role, label or value at all (`server/templates/_macros.html:19-30`, per `cx-6214a81c`).
- Connected state is a green left border; only disconnected gets text
  (`server/templates/_board.html:112`, `server/static/board.css:219-220`).
- Bond status is glyph plus colour; "Linked" has no text, others do
  (`server/templates/_board.html:216-224`, `server/board.py:53-54`). `link_row()` reduces alive,
  dead and memorial to the classes `la`/`ld` (`server/templates/_macros.html:139-155`, per
  `cx-6214a81c`).
- The battle sword relies on `title` and the shiny glyph has no text
  (`server/templates/_board.html:49`, per `cx-6214a81c`).
- Fallen state is already redundant: grayscale, dashed border, strike-through
  (`server/static/board.css:348-350`).

Fix: progressbar semantics (or `<progress>`) with `aria-valuetext`, not live; "HP unavailable" when
`max <= 0`; visible Connected/Disconnected text; a visible status pill on every bond (Linked,
Pending, Boxed, Split, Fallen, Dead zone) with the glyph `aria-hidden`; text for "Out in battle"
and "Shiny".
[WCAG 1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html),
[1.3.1](https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships.html).

### 9. Contrast across themes (high)

From `cx-303c3e92`: `themes/CONTRAST.md:27-41` says Smoke's `--c-brand` is never text, yet the
board uses it for rail brand text (`server/static/board.css:82`), active rail/tab state
(`:105,157`), Player A/B labels (`:209`), the focus outline (`:587-588`), and links/event-player
text (`:410,483`). Documented ratio 1.57:1. Add `--c-focus` (3:1 against card and page in every
public theme) and `--c-on-brand`.
[1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).

From `cx-c518530b` (computed with alpha compositing):

- **`--c-edge` fails 3:1 in all audited themes.** Default 1.2:1 on bg / 1.3:1 on card
  (`slink.css:85`); Light 1.3:1 (`slink.css:344`); Smoke 1.9:1 / 1.7:1
  (`funtastic-smoke.css:12`). It borders buttons and inputs (`server/static/board.css:161`,
  `:422`; `server/static/slink.css:505-507`). Fixes: Default `rgba(255,255,255,.38)`, Light
  `rgba(0,0,0,.48)`, Smoke `#808080`.
- **Smoke brand as text:** `#333333` (`funtastic-smoke.css:25`) is 1.6:1 on bg, 1.4:1 on card,
  used as text at `board.css:82`, `:106`, `:157`, `:483` and `slink.css:289`, `:303`. Fix:
  `--c-brand: #c0c0c0` (Smoke's `--c-gold`), about 10.9:1.
- **Alpha backgrounds make contrast backdrop-dependent:** `--c-bg` is translucent in default and
  light (`slink.css:83`, `:342`) and applied to `html` and `body` (`slink.css:218-219`). Over a
  white canvas, default dead text drops to about 4.1:1 (inference). Fix: opaque `#070910` and
  `#eef2fc`.
- **`CONTRAST.md` is stale:** no edge column, values that do not match compositing, and an
  incomplete regeneration script (`CONTRAST.md:49-68`). Replace it with an executable test.
- Default and Light pass all body, dim, brand and status text checks on both surfaces.

### 10. Pixel type needs a floor (medium)

Sizes are 12, 13, 14, 16, 18, 20.8px (`server/static/board.css:22`); Jersey 20 with Pixelify and
monospace fallbacks (`board.css:30`); HP values at 13px (`board.css:325-330`). WCAG sets no minimum
size but requires 200% resize and text-spacing tolerance
([1.4.4](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html),
[1.4.12](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html)). Product floor: 16px for
body, controls, names, HP and log; 14px metadata; pixel faces for headings, short labels and
figures only; wrap nicknames. [Apple HIG Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility).

### 11. Target sizes (medium)

Controls get `min-height:40px` (`server/static/board.css:574-588`): passes
[WCAG 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) (24×24) but not
Apple's 44×44pt default. Use 44×44px minimum, 48px preferred, for menu, rail links, theme controls,
every `<summary>` and future tabs.

### 12. Shell findings (`cx-f486dbca`)

- **No skip link** (`server/templates/base.html:18-40`). 2.4.1, Level A. Add one targeting a
  single `<main id="main-content" tabindex="-1">`.
- **Rail only partly in `<nav>`:** only the run list is (`server/templates/_rail.html:35-43`); New
  run, Manager, run and standalone links sit outside (`:19-21`, `:49-64`, `:67-74`, `:77-91`).
- **Active state is visual only:** `.active` without `aria-current` in `_rail.html`,
  `dashboard.html:30-33`, `panel_page.html:29-30`, `stream_index.html:379-380`.
- **Theme picker keyboard contract incomplete:** Alpine `radiogroup`/`radio` with no roving
  tabindex, arrow, Home/End or Escape handling, click-only selection
  (`server/templates/_theme_switcher.html:36-44`); the vanilla fallback lacks `role="radio"` and
  `aria-checked` (`server/static/dashboard.js:239-240`, `:241-244`, `:224-226`); neither returns focus to the
  summary (`_theme_switcher.html:170-174`; `dashboard.js:263-267`). Prefer native radios and one
  implementation.
- **Nested `<main>`** in `server/templates/stream_index.html:374` and `:418`.
- **Error pages** lack `lang` (`server/manager.py:297-300`) or both `lang` and `<title>`
  (`server/manager.py:1618-1624`).

### 13. Headings (`cx-6214a81c`, low to moderate)

Now cards (`_board.html:107-115`), setup (`:172-194`) and encounter articles (`:208-223`) have no
headings. Add `<h3>` per player card and area, `<h2>Getting started</h2>`.

## Recommendations

**P0**

1. Fix the phone shell at 900px: public-mode app bar and Menu disclosure; the closed rail is
   `inert`, not only translated; `scroll-padding-top` and `env(safe-area-inset-top)` for the
   sticky bar.
2. Phone pair layout below 600px (A → bond → B, labels, unmirrored B, wrapped nicknames), or the
   side-by-side alternative, once the owner decides.
3. A stable pair-level announcer outside the morph target, fed by canonical event IDs with link and
   death duplicates coalesced.
4. Pause/Resume live updates.

**P1**

5. Focus and drawer semantics: stable IDs, `focusin` poll pause, restore after morph, Escape and
   scrim close, skip link, `aria-current`, one labelled `<nav>`.
6. Remove colour- and glyph-only status: bond pills, Connected text, HP progressbar semantics,
   text for battle and shiny.
7. Theme tokens: opaque `--c-bg`, raised `--c-edge`, Smoke `--c-brand`, new `--c-focus` and
   `--c-on-brand`; an executable contrast test replacing `CONTRAST.md`.
8. Typography and targets: 16px essential text, 14px metadata, 44px controls, 48px nav.
9. Theme picker: native radios, one implementation, Escape and focus return.
10. Single `<main>` per page; `lang` and `<title>` on error pages; headings for cards and areas.

**P2: audit checklist**

- Widths 320, 360, 390, 400, 599/600, 899/900 and desktop; no page-level horizontal scroll.
- 200% text, 400% zoom, [WCAG text-spacing metrics](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html).
- Keyboard only: Menu, links, disclosures, Pause/Resume, theme controls; focus visible and not
  hidden.
- VoiceOver/Safari and NVDA/Chrome: unchanged polls are silent; one link and one death each
  announced once.
- Focus a summary, let several polls pass, confirm focus survives.
- Greyscale and colour-vision simulation.
- Every public theme: text 4.5:1, graphics and focus 3:1.
- Every nav and disclosure target at least 44×44px.
- Reduced motion removes transitions but keeps state feedback.
- axe plus manual keyboard and screen-reader review.

## Where the reports expect disagreement

- Bottom tabs now: no; they should follow a deliberate public IA, not compress the Manager rail.
- A permanent icon rail: no; it costs phone width and makes run names ambiguous.
- `aria-live` on `#content`: strongly no (both `cx-303c3e92` and `cx-6214a81c`).
- Live updates declared "essential" with no pause: push back.
- `CONTRAST.md` as proof: no.

## Unverified and open

- Public IA: no spectator routes or nav set exist yet; this decides whether a menu is needed at all.
- No browser rendering; the ~136px figure is arithmetic from CSS; wrapping and overflow untested.
- Idiomorph focus with keyboard, VoiceOver, NVDA, TalkBack and mobile browsers not exercised.
- Computed contrast for the other five Funtastic themes and `color-mix()` surfaces not calculated.
- Pixel-font legibility at 200-400% not user-tested.
- Event deduplication needs backend work (no event ID).
- Safe areas: no evidence the sticky bar or drawer handle `env(safe-area-inset-*)`.
- Sprite alt text (open item from `cx-6214a81c`): Gen 1 and Gen 2 `sprite_html` emit no `alt` at
  all (0 `alt=` in `gen1_rby.py` and `gen2_crystal.py`); Gen 3 emits `alt=""`. Rendered-DOM check
  pending.
- Theme picker focus location after closing `<details>`, and native Escape behaviour, vary by
  browser.
- Theme count: this file follows the reports' "all public themes" wording; `brand-identity.md`
  recommends exposing only Auto, Light and Dark publicly. See the README.
- Truncation: the validator worked from a stored reply cut after finding 11. This file uses the
  full retained reply (`magi mail --task cx-303c3e92`), so the disagreements, unknowns and
  recommendations above were not independently checked.

## Validation

`cx-303c3e92`: 15 accepted, 1 open. A Sonnet validator confirmed 15 claims, including the ~136px
arithmetic at 360px, the 900px rule targeting the retired `.mgr-rail`, the mouse-only pause, the
Smoke brand contradiction and the WCAG/HIG facts. One was partly right: the reduced-motion lines
are 594-597. The stored reply is truncated after finding 11.

Supporting reviews, findings accepted: `cx-c518530b` 4/0/0 (contrast); `cx-6214a81c` 5/0/1 (board;
sprite alt open); `cx-f486dbca` 6/0/0 (shell).
