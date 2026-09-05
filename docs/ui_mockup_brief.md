# UI mockup brief

The brief both mockup tracks build against. Track A (Jinja + Alpine + htmx, no build) and
Track B (Vite + Svelte SPA) implement the *same* design from this document, so that
comparing them compares the frameworks and not two different designers' taste.

Read this before writing any markup.

---

## 1. Why

The browser UI is two disjoint apps on two ports, built two different ways:

| | Port | Built with | Size |
|---|---|---|---|
| Run Manager | 8090 | `server/templates/manager.html` + Alpine | 815 tmpl / 898 css |
| Run dashboard | 8081+ | Python string concatenation, `server/server.py:3279` `_build_status_html` | ~1465 py / 1796 css |

Seven more destinations hang off the same rail (`server/chrome.py:28` `_NAV_ITEMS`), four of
which are entire HTML documents living as Python module constants (`_STATUS_HTML`,
`_DEBUG_HTML`, `_TWITCH_PAGE_HTML`, `_OBS_PAGE_HTML`). The Manager already embeds the run
dashboard in an `<iframe>`, which is the two pages admitting they want to be one.

Every new feature — peer ghost, companion ROM patch, in-game START-menu panel, five
generations, the damage calculator — has landed as more of that. Gen 1 is the next
thoroughly-tested cartridge and it breaks the last shared assumption: with randomized ROM
pairs, the two players are not even playing the same content as each other.

## 2. Information architecture — 9 destinations become 3

| Destination | Absorbs | Notes |
|---|---|---|
| **Run** | Manager, Status (`/`), Memorial | Run list becomes the left rail. Memorial becomes a tab. |
| **Broadcast** | Stream gallery, Twitch, OBS | One page, three panels. All of it is "what the audience sees". |
| **Tools** | Patcher, Randomizer, launcher downloads | Run setup that is not live state. |
| *(external)* Calc | — | Vendored third-party app with its own chrome. New tab. Unchanged. |
| *(drawer)* Debug | `_DEBUG_HTML` + 12 `/api/debug/*` | Slide-over panel, not a rail item. |

One origin. The Manager becomes the only UI server; per-run servers keep serving OBS
overlays. The UI reaches a run's state through a per-run proxy, which already exists for
the pinned run at `server/manager.py:878-880` and needs only to take a run id.

## 3. Layouts

Three were sketched and built; one survived. Track A now ships **L1 with L2's board as
its Links tab**, and L3 is gone — the reasoning is in §9. The three are kept below as the
record of what was tried. Track B builds L1 only — it exists to answer "is an SPA better
here?", and layout exploration is framework-independent.

The chrome rule that came out of streamlining it: **nothing is labelled twice.** The
player chip under the run name is the header for that player's column, so the cards
beneath it carry none; a party table has no `<thead>`, because sprites and HP bars do not
need captions; and every card header that captioned something the chip already said —
"Player A · Alice", "Encounters here · Route 22 · from firered_rr", "Recent events" — is
gone. Card headers survive only on Setup, Broadcast and Tools, where a page holds several
distinct things that need telling apart.

### L1 "Workspace" — the recommended baseline

```
┌────────────┬──────────────────────────────────────────────┐
│ SOUL LINK  │  Kanto Duo          ● running    [Stop][Pin] │
│ ─────────  │  A Alice  Red   ●2  Cerulean   B Bob  Blue ●1│
│ ▸ RUNS     ├──────────────────────────────────────────────┤
│  ● Kanto   │  Live │ Links │ Boxes │ Memorial │ Setup     │
│  ○ RR Hard ├──────────────────────────────────────────────┤
│  ⊘ Red/Blue│                                              │
│            │            (the selected tab)                │
│ ▸ BROADCAST│                                              │
│ ▸ TOOLS    │                                              │
│ ─────────  │                                              │
│ [font][thm]│                                              │
└────────────┴──────────────────────────────────────────────┘
```

Rail: brand → run switcher (status dots, grouped by state) → the three destinations →
font and theme pickers. Main: a run header strip, then a tab row. Lowest risk; absorbs
every existing surface without inventing anything.

### L2 "Split Board"

The page *is* the soul link. Two symmetric player columns with a centre spine carrying
link status, area and pairing; global run state in a thin top bar. This generalises the
dashboard's existing Split|Combined toggle (`dashboard.css:687`, `.lp-card`, the 5-column
mirror table) from one widget to the whole page. Best fit for the Gen 1 reality of two
different cartridges.

### L3 "Deck"

Icon-only rail. One scrolling canvas of collapsible cards (Situation · Party A · Party B ·
Battle · Encounters · Links · Events · Boxes) under a sticky situation bar, with a
right-hand dock for the event feed and quick actions. Maximum density for a second
monitor during play.

## 4. Capability-driven panels — the Gen 1 rule

**A panel a generation does not have must be absent, not empty.**

Today the difference is written into tooltip prose — "Gen 3 only", "has no effect on Gen
1". Prose does not scale past two generations and it cannot hide a column: the Ability
column still renders, blank, beside a cartridge that predates abilities.

`fixtures/capabilities.json` answers this per **rom_type**, not per generation, because
several capabilities come from the Radical Red companion patch rather than from the
hardware:

| rom_type | abilities | explode_mode | info_panel | badges | party blob |
|---|---|---|---|---|---|
| `red` | ✗ | **✓** | ✗ | 8 | 66 |
| `crystal` | ✗ | ✗ | ✗ | 16 | 70 |
| `firered` | ✓ | ✗ | ✗ | 8 | 100 |
| `firered_rr` | ✓ | ✓ | ✓ | 8 | 100 |
| `heartgold` | ✓ | ✗ | ✗ | 16 | — |
| `pokemon_black` | ✓ | ✗ | ✗ | 8 | — |

Note `firered` and `firered_rr` differ on two rows. Capability is a property of the
cartridge in front of the player.

Rules:

- **Abilities** — `capabilities[rom_type].abilities` false ⇒ no Ability column at all.
- **Held items** — *not* in capabilities, deliberately: no adapter answers it, and asking
  whether the adapter knows item names measures the bag (which Gen 1 has) rather than the
  held-item slot (which it lacks). Decide from the data — if no mon in the payload carries
  a non-zero `held_item_id`, the column has nothing to show.
- **Stat stages** — `stat_stage_labels` is the ordered label list; a blank label suppresses
  that badge. Gen 1 has a single Special where later generations have Sp.Atk and Sp.Def.
- **Box capacity** — `mons_per_box`, not a hardcoded 30. Gen 1 stores 20.
- **Run options** — Explode Mode and Rival Swap are *available on Gen 1 with no patch*;
  Overworld Presence, Native Messages, Native Sounds and Battle Calc are Gen 3 only. Show
  unavailable options as unavailable in place rather than as an enabled checkbox with a
  disappointing tooltip.
- **null means unknown.** Several predicates (`mons_per_box`, `stat_stage_labels`,
  `info_panel_width`) land with the Gen 1 branch and read `null` on this checkout. Render
  those as unknown; do not collapse them to false, which claims something different.

## 5. Per-player, not per-run

Randomized ROM pairs mean the two players hold cartridges with the same *settings* and
different *seeds*. The consequences the layout must carry:

- **Encounter tables are per player.** `players.{a,b}.encounter_table` — already in the
  payload, and `server/server.py:1801` `adapter_for(player_id)` is how the server resolves
  it. Never render one shared encounter table.
- **Cartridge identity is per player** — seed and ROM SHA1 belong beside that player, not
  in a run-level summary.
- **Native panel capability is per player**, because on Gen 1 it comes from the companion
  patch, which one player may have applied and the other not.
- The two players can be on **different versions** of the same generation (`red` / `blue`,
  `firered` / `leafgreen`), so the game label belongs on the player chip. (Not
  `leafgreen_rr` — Radical Red is a FireRed hack with no LeafGreen build; an RR run is
  `firered_rr` on both sides.)

The randomizer flow (jar, settings file, two clean ROMs → two seeded ROMs with recorded
SHA1s) is a **first-class step in run setup**, not a collapsed `<details>` at the bottom
of a detail pane. The seeds recorded there are the only record of what each player is
playing — UPR's CLI has no seed flag and writes it only to its log.

## 6. Theme contract

**Do not invent a palette.** `server/static/slink.css:58-168` is a real design system and
`server/static/themes/CONTRAST.md` holds a WCAG audit of every theme. Mockups link the
real stylesheets and swap `<link id="slink-theme">`, so all nine themes work in them.

Tokens, all consumed rather than redefined:

```
--c-alive --c-dead --c-pend --c-gold      semantic status
--c-txt --c-dim --c-bg --c-card           surfaces and text
--c-edge --c-sep --c-sticky               borders, separators, opaque sticky headers
--c-brand --c-link --c-info               accent, hyperlink, area/info cyan
--c-hp-high --c-hp-mid --c-hp-low         HP bar thresholds
--font-ui --font-pixel --font-heading     typography (--font-ui flips with body.font-classic)
--scale-step                              the clamp() every --space-* and --size-* derives from
--space-1..6  --size-rail --size-sprite-* spacing and named sizes
```

Two additions are in scope:

- `--density: comfortable | compact` — the merged UI packs more per screen than either page
  did alone.
- `calc/src/js/slink_bridge.js` carries a hardcoded `var C = {...}` hex palette and is the
  one surface that ignores the token system. Note it; do not fix it in a mockup.

### 6a. The body font is an open question

`--font-ui` currently resolves to **Pixelify Sans**, a pixel face. It is on-brand and it is
the single hardest thing to read in the UI — and merging the two pages makes that worse,
not better, because the run list, both parties, the links table and the event feed now
share one viewport. There is far more small text per screen than either page had alone.

Candidates are vendored (`tools/vendor_fonts.py`, never fetched at runtime) and switchable
live in the Track A mockup, so the choice gets made by looking:

| Option | Notes |
|---|---|
| **IBM Plex Sans** *(mockup default)* | Technical without being sterile, has a matching mono, tabular figures. |
| Inter | The neutral standard. Safest, least character. |
| Space Grotesk | Geometric with some quirk left in it. |
| IBM Plex Mono | Everything aligns; heavy over a whole page. |
| System UI | Zero bytes. Looks like the OS, not like the project. |
| Pixelify Sans | What ships today, kept for comparison. |

Whatever is chosen, `--font-pixel` (Press Start 2P) **stays** for the stream overlays,
where text is large, sparse and read from across a room. The argument is about the dense
UI, not about the brand — which lives in the sprites, the palette and the overlays.

The detail that decides it is figures. A party table is mostly numbers — `26/26`, `Lv 11`,
`2/8 badges` — and they only read as columns when the digits share a width. Pixelify has
no tabular set, so HP values jitter row to row. Every other candidate has one.

**Not changed in the mockups: `slink.css` itself.** `_funtastic-base.css` routes `html,
body` through `--font-ui`, so flipping the default restyles all ~25 OBS overlays too, and
those are laid out inside fixed-size browser sources where a wider glyph can overflow. The
switch is a one-line change gated on re-checking the overlays; that belongs to the
implementation plan, not here.

Constraints inherited from OBS browser sources (`server/templates/stream/_base.html`): no
CDN, no SSE, no fonts loaded at runtime. Anything added to `slink.css` ships to OBS too.

## 7. Fixtures

In `server/static/mockups/fixtures/`. **Generated, never hand-written** — a hand-written
fixture drifts into fiction and then the mockup is designing for a payload that does not
exist.

| File | Source | Contents |
|---|---|---|
| `gen3.json` | `GET /api/status` | Radical Red. 6-mon parties both sides, 3+2 boxed, 8 links, 2 deaths, B mid-battle, attempts 7, abilities and held items present |
| `gen1.json` | same, `--game gen1` | Red vs Blue. Same shape; genderless, no abilities, no held items, Gen 1 move names |
| `capabilities.json` | `tools/gen_ui_capabilities.py` | the table in §4 |
| `runs.json` | Manager `window.SLINK_RUNS` | 3 runs — running / stopped / archived — with `created_short`, `safe_name`, `game_label`, `last_event` |

To regenerate:

```bash
python -m server.server --port 54321 --http-port 8080 --data-dir <scratch> --reset &
python tools/inject_full_mocks.py                 # or: --game gen1
curl -s localhost:8080/api/status > server/static/mockups/fixtures/gen3.json
python tools/gen_ui_capabilities.py > server/static/mockups/fixtures/capabilities.json
```

The status payload is built by `server/server.py:3044` `_build_status_dict`. That function
is the contract; `tests/unit/test_mockup_fixtures.py` pins the fixtures to it.

**Gotcha worth knowing:** `rom_type` must be a string the client actually sends
(`red`, `firered_rr`, …), not an adapter `game_id`. An unrecognised value leaves the
server on whichever adapter it already had — silently — and the first attempt at a Gen 1
fixture came out with Gen 3 genders and abilities because of exactly that.

## 8. Output layout

```
server/static/mockups/
  index.html          side-by-side entry point, links both tracks
  fixtures/*.json     shared, above
  a/                  Track A — index.html + mockup.css + mockup.js + fonts.css
  b/                  Track B — built Vite output, committed
```

Track A is one page and, after streamlining, one layout. The earlier draft switched
between three without a reload; the board became the Links tab and the deck was dropped
(§9), so the switcher went with them.

Note the URLs need the explicit `index.html`. aiohttp's `add_static` is mounted without
`show_index` (`server/templating.py:142`), so `/static/mockups/` itself returns 403.

`/static/` is already mounted by both apps (`server/templating.py:142`), so this needs
**zero new routes**. View with `python -m server.manager` at
`http://localhost:8090/static/mockups/`.

Both tracks must:

1. Link the real `/static/slink.css` and a real `/static/themes/*.css`, with a working
   theme switcher.
2. Offer a **Gen 3 / Gen 1 toggle** that reloads from the other fixture, so capability
   differences are one click apart.
3. Work with no network access and no build tooling installed on the viewer's machine.

---

## 9. What comes next — recommendations for the implementation plan

Written after building both tracks and reading most of the UI code. Ordered by the
sequence I would actually do them in. Each phase ships on its own and is demoable in a
browser before the next starts.

### Decision: Track A, L1 shell, with L2's board as the Links tab. Drop L3.

- **Track A.** Both Track B agents recommended against their own track and the reasoning
  holds: the SPA retires nothing. The ~25 OBS overlays still need server-rendered
  fragments, so Jinja stays either way, and the payload contract ends up consumed in two
  languages. The hard part of this brief is the capability model, which is a
  data-modelling problem and comes out identical in both stacks.
- **L1 as the shell.** It absorbs every existing surface without inventing anything, and
  the tab row is where Memorial, Boxes and Setup go without a fight.
- **L2's split board becomes the Links tab.** Having built both, the board is a better
  links view than the links table — the spine makes the pairing legible in a way a row
  of two cells never does — and it is the direct descendant of the dashboard's existing
  Combined view, so the `lp-view` toggle (`dashboard.js:702`) and the 5-column mirror
  table can go.
- **Drop L3.** The Deck is a "second monitor during play" mode, and the project already
  has a better answer to that: the OBS overlays, which are pixel-tuned, per-widget, and
  sized for exactly that use. A third rendering of the same panels is not worth owning.

### Phase 1 — the data model (small, ships alone, fixes real bugs)

1. **Emit capabilities in `/api/status`.** `players.{pid}.capabilities`, resolved through
   `adapter_for(pid)` (`server.py:1801`, from the Gen 1 branch), carrying exactly what
   `tools/gen_ui_capabilities.py` probes. This is what lets the tooltip prose die: a
   template asks `caps.abilities`, not "is this RR". When the Gen 1 branch merges,
   `stat_stage_labels` / `mons_per_box` / `info_panel_width` stop being null and every
   consumer lights up without changing.
2. **Put the mon key inside the party entry.** `party_details` is keyed by key and does
   not repeat it in the value. It cost the mockup its entire "linked to" column and it
   will cost the Jinja templates the same. One line in `_enrich_party`.
3. **Make an unrecognised `rom_type` loud.** Today it leaves the server on whichever
   adapter it already had — silently. That gave the first Gen 1 fixture Gen 3 genders and
   abilities, and the comment at `adapters/__init__.py:53` records the same thing
   happening to Gen 2 before. Reject the hello with an `identity_error` the UI already
   knows how to show, and log at WARNING. This is a correctness bug in shipped code, twice.
4. **Reconcile `leafgreen_rr`.** `server.py:3397` labels it; nothing routes it; Radical Red
   has no LeafGreen build. Delete the label.

### Phase 2 — rendering (same pixels, new source)

5. **Delete `_build_status_html`** (`server.py:3279`, ~1465 lines) and render the dashboard
   body from Jinja partials fed by `_build_status_dict`. The pattern is already proven
   twenty times over in `templates/stream/`; `_macros.html` already has `hp_bar`,
   `status_pill`, `stat_stages_row`, `mon_card`. Column presence comes from
   `player.capabilities`, not from `if rr`. Ship this with the OLD chrome so the diff is
   provably "same output, different generator" — the `_smoke.html` fixture is the check.
6. **One chroma-keyer.** `dashboard.js:35` and `overlay-helpers.js:31` are the same
   function. Keep the vendored one; delete the copy.

### Phase 3 — the shell (the visible change)

7. **Manager absorbs Status and Memorial.** One origin. Generalise
   `handle_proxy_status` / `handle_proxy_events` (`manager.py:878`) to take a run id
   instead of reading the pin. Delete the iframe preview and `_augment_for_template`'s
   habit of scraping `links.json` / `events.json` off disk — it proxies the live run's
   `/api/status` instead.
8. **`chrome.py` `_NAV_ITEMS` 9 → 3** (+ Calc external, + Debug drawer). Delete
   `_STATUS_HTML`, `_DEBUG_HTML`, `_TWITCH_PAGE_HTML`, `_OBS_PAGE_HTML` — four whole HTML
   documents living as Python constants — and fold Twitch + OBS + Stream into one
   Broadcast template, Patcher + Randomizer into Setup / Tools.
9. **One poll.** Today there are six: htmx every 2s on the dashboard and every overlay,
   `refreshRuns` every 10s and `_fetchLiveStatus` every 2.5s on the manager, `loadStatus`
   every 5s on both Twitch and OBS, and an SSE fallback every 10s. The merged page polls
   once. Do NOT reach for SSE to do it: `_STATUS_HTML` documents why (Chrome's 6-per-origin
   connection cap, one held open per tab), and a single origin makes that worse, not
   better. Keep htmx polling; just have one poller.
10. **Delete `manager.css` (898) and `sidebar.css` (328).** One sidebar, one stylesheet
    on top of `slink.css`. The calc keeps its own Bootstrap chrome behind its own page.
11. **`python -m server.server` keeps working.** The single-server path is the README's
    "simplest" option. It renders the same shell with one run in the rail — same
    templates, no second code path.

### Phase 4 — polish

12. **Flip `--font-ui` to IBM Plex Sans**, after checking every overlay in
    `overlay_catalog.py` at its recommended size. `_funtastic-base.css` routes
    `html, body` through the token, so it is one line — gated on that check.
13. **`slink_bridge.js`** (`calc/src/js/`, 2276 lines) reads its `var C = {...}` palette
    from the tokens instead of hardcoding hex. Last, because it is the least visible.
14. **`--density`** as a real user setting beside font and theme.

### Things I would NOT do

- Add `show_index` to the `/static/` mount to fix the mockup 403s. It exposes directory
  listings for the whole static tree to fix a URL. Link `index.html`.
- Move overlays to the new templates. They are pixel-tuned OBS sources with their own
  base template and their own constraints; leave them on the pattern they already use.
- Keep the Split | Combined toggle. L2's board is the combined view; the split view is
  the Live tab. Two tabs, no toggle.
