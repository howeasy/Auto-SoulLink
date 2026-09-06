# UI mockup brief

The approved Track A composition is now ported to the production run board.
See [the migration plan](ui_migration_plan.md) and
[Phase 5 evidence](ui_migration/phase5_board.md). Mockup assets and Track B were
retired after their required fonts and fixtures were promoted. The sections below
record the reviewed design and framework comparison; historical demo URLs no
longer describe the production tree.

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

## 3. Layout — zones, and the pair is the unit

What a Soul Link is, per the rules the server enforces (`docs/REFERENCE.md` §"Soul Link
Rules Enforced") and the community ruleset: two players, two games; the first catch per
route on each side is **linked**; if either faints **both are dead** and go to the
memorial box; if either fails the route it is a **dead zone for both**; linked pairs live
**together** — both in the party or both boxed; one caught and the other not yet is
**waiting**, quarantined to the box. The unit is the pair. Three drafts treated it as a
footnote on each player's party, which is how the payload hands the data back and not how
anyone thinks about it.

The page is four zones, in the order a player cares during a run. Each is a real heading
with a rule across the line and a count; the gap between zones does the dividing. And
**every zone sits on the same three-track grid — Alice's column, the spine, Bob's
column** — so a player's side reads straight down the page and the bond between two mons
is drawn where it is: between them. An earlier draft put both halves inside one card and
flowed the cards in a grid; it was impossible to scan one player's side, which is the
first thing a partner does.

- **Now.** One card per player — the header for that player. Who, on what cartridge,
  where, badges, balls, and an *in battle · Embo* tag when they are fighting. The wild
  encounters for the area are a collapsed line, as the old encounter widget was: they are
  reference material, not status. Nothing transient lives here.

**Whose mon is whose.** The board cannot know which player is looking at it, so "you" and
"ours" mean nothing on it. The only thing that says whose mon a mon is, unambiguously, is
**which column it sits in** — and every later decision follows from that.

**Battle is drawn in the pair row.** When Bob's Embo is out, the Sparky↔Embo row *is* the
battle view: Bob's half shows Embo with the foe nested beneath it in a red strip — *vs
wild Caterpie · Lv 11*, HP bar — and Alice's half, across the spine, shows Sparky tagged
**at stake**. Position says whose mon it is, nesting says whose foe, and the spine says why
the other half is in danger. Two players in two fights show as two rows with foes. Battle
is a player state, never a pair state, so there is no pair-wide battle tint and no
battle zone: a draft put a red card in the fighting player's column with the foe, the
player's mon and the partner stacked under small labels, and it was not clear which of
the three was theirs. The only pair-wide tint is at-risk, because HP risk genuinely is.

- **The team** (`In party`). One row per linked pair, spanning both columns and
  card-styled: A's half, the spine, B's half, mirrored so the sprites sit at the outer
  edges and the text faces the bond; both HP bars, ability and item. The spine carries
  the route, the tie, and the state. The zone heading carries the two players' names at
  its ends. A pair is tinted and labelled **at risk** when its *weaker* half is under 35%
  — both halves die if either faints, so the pair's health is its minimum, not its
  average.
- **Pending link**, directly under the team: one half caught and quarantined, the other
  a dashed slot reading "waiting for Bob". Then **Boxed**: pairs on the shelf together, no
  HP. **Split** — one half in the party and one boxed — gets its own zone when it happens,
  because the sync rules will act on it. Both compact.
- **Fallen.** The graveyard, with presence rather than a dimmed table: dashed cards,
  greyed sprites, names struck, and the epitaph in the header — `fainted · wild Geodude`.
  Dead zones sit here too, both slots reading *missed*.
- **Log**, a sticky column beside the zones from 1400px, under them below that.

Scaling: the two player columns share the width, so each half gets more room on a wider
monitor rather than more columns appearing; the log takes a column of its own from
1400px. Sprites track `--scale-step` too (`--mk-spr`, 60–104px), sitting at or above
their native 56–64px on any real monitor and upscaling pixelated past that. Gen 1's
sprite arrives as a 40px crop wrapper around a 52px image with inline styles, so its
wrapper and image are scaled by the same factor in plain lengths — dividing a length by a
length in `calc()` is invalid CSS and was silently dropped in an earlier draft, which is
why Gen 1 stayed small. The proper fix is the server emitting a sprite that sizes
itself; that is a Phase 1 line in §9. The page scrolls like a page; only the run header is sticky. An earlier draft
locked the board into `100vh` and it read as cramped at every size.

**The manager is the rail and the run header.** New run is a guided form beside a
preview: name; the **game family**, as chips — Red · Blue · Yellow, FireRed · LeafGreen,
and so on — defaulting to *detect when players connect* (today's behaviour) but greying
what a chosen family's cartridges cannot honour, with the reason, before anyone connects.
The unit of compatibility is the family, not the cartridge: any two of Red, Blue and
Yellow can link, because they share an adapter and an area map; what separates families
is a different map (Radical Red from vanilla FireRed, Platinum from HGSS) or a reshuffled
world (the Archipelago builds). The exact cartridge each player is on is read from their
hello; the three option groups, each option carrying its one-line description
in the manager's own words — on the board those were fluff, on the form that sets them
they are the point; a randomized-ROM-pair toggle for Gen 1; and *what happens next* with
the port the run will get. Then start / stop / pin / archive / delete, a launchers
popover, ports. A run nobody has connected to says so instead of
borrowing another run's data. A stopped run shows only what was persisted — the links, no
HP, no battle, no Now cards — which is exactly what the Manager has for it today; its
pairs sit under **Linked** rather than claiming to know who is in a party.

**Per player, not per run.** Game label, area, badges, balls, battle and wild encounters
live on that player's Now card. A dropped client keeps its last state on screen with a
*disconnected* tag rather than vanishing — the server keeps that state across a
reconnect, and the UI should agree with it.

Track B built the earlier L1 Workspace draft only; it exists to answer "is an SPA better
here?", and that answer (§9) does not depend on which arrangement won.

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

The brief for the font sharpened after the plain faces were seen in place: **Pixelify's
character, more legible** — not a neutral sans. So the second round is pixel-flavoured
faces that keep more of the glyph. **Jersey 20 was chosen**, and the page's small-size
tiers were retuned to it: it is condensed with a tall x-height and reads a size smaller
than a plain sans at the same px, so the secondary tier (sub-lines, tags, bond state, HP
figures, the log) now sits at ≥12px off a 16px body where it had computed to 9–11px.
Jersey's narrowness is what pays for that.

| Option | Notes |
|---|---|
| **Jersey 20** *(chosen; mockup default)* | The same proportional pixel-sans idea as Pixelify at a finer grid; condensed, real x-height, names and figures hold at table size. |
| Jersey 15 | Jersey 20 one step coarser. Nearly interchangeable. |
| Jersey 10 | The coarse end of the family — nearest to Pixelify's look, and to its legibility problem. |
| DotGothic16 | The most legible pixel face here outright: round dots, generous width. Wide, and its Latin has a Japanese accent. |
| Tiny5 | A 5px grid rendered chunky; charming, heavy, reads more "toy" than "tool". |
| Handjet | Variable weight, pixel-shaped elements. Not judged: its capture came back identical to the previous one, so it was not seen rendered. |
| Doto | Dot-matrix, variable weight. LED-sign flavour; likely better on overlays than on tables. |
| VT323 | Terminal mono. Very legible, everything aligns, and everything looks like a terminal. |
| IBM Plex Sans | The plain-face recommendation from round one. Technical without being sterile, tabular figures. |
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

Track A is one page and one layout — the board (§3). The mockup controls, bottom-left,
switch cartridge, density, body font and theme; they are the only part of the page that
would not ship.

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

## 9. Implementation plan

The approved [UI migration plan](ui_migration_plan.md) supersedes the earlier
recommendations in this section. The reviewed design in section 3 remains the
board baseline, with the approved mild responsive/accessibility refinements.

The restricted runtime handoff is recorded in [ui-runtime-handoff.md](ui-runtime-handoff.md).
Regenerate rendering fixtures offline with `python tools/capture_ui_fixtures.py`;
live RBY mock injection remains blocked by the runtime operation restrictions.
These rendering scenarios do not claim cartridge admission or live readiness.
