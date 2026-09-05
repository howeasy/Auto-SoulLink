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

Track A builds all three. Track B builds **L1 only** — it exists to answer "is an SPA
better here?", and layout exploration is framework-independent.

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
  `firered_rr` / `leafgreen_rr`), so the game label belongs on the player chip.

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
  a/                  Track A — index.html, l1.html, l2.html, l3.html
  b/                  Track B — built Vite output, committed
```

`/static/` is already mounted by both apps (`server/templating.py:142`), so this needs
**zero new routes**. View with `python -m server.manager` at
`http://localhost:8090/static/mockups/`.

Both tracks must:

1. Link the real `/static/slink.css` and a real `/static/themes/*.css`, with a working
   theme switcher.
2. Offer a **Gen 3 / Gen 1 toggle** that reloads from the other fixture, so capability
   differences are one click apart.
3. Work with no network access and no build tooling installed on the viewer's machine.
