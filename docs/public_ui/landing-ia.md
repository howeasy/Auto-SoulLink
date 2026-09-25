# Landing page and information architecture

Source: OMP research report `cx-141d8654` (SECOND_OPINION, read-only, repo at master a9bdce38).

## Summary

Build a separate public spectator front end: a landing page plus stable run permalinks. Keep
today's Manager as a local control plane and never expose it publicly. The landing page leads
with one claim ("Two Pokémon Nuzlockes. One shared fate.") and one user-controlled demo
(catch, link, faint propagating), then offers **Watch live runs** and **Set up SLink**.

The report's own strongest doubt: no one-way publish, redaction or archival contract exists
yet, and today's HTTP surface is local and full of mutations. Without that bridge the IA has
nothing safe to show.

## Key findings

### 1. Comparable sites keep browsing public and put accounts at the contribution boundary

Importance high; confidence high for the pattern.

- Archipelago explains itself in one paragraph, then routes to games, setup guides, start
  playing and FAQ. Its guide separates a shareable room page from the creator's owner console,
  with owner access tied to the creating browser's cookie.
  [Archipelago homepage](https://archipelago.gg/),
  [official setup guide](https://archipelago.gg/tutorial/Archipelago/setup_en).
  (The validator marked the nav wording as only partly matching.)
- Nuzlocke Tracker leads with New Game, Load Game, Guides and "Free, no login, runs in your
  browser". [Nuzlocke Tracker](https://nuzlocketracker.org/)
- MyPokePanion's landing page demonstrates the real route timeline, Soul Link pairing, team
  sync and overlay. [MyPokePanion Nuzlocke](https://mypokepanion.com/en/nuzlocke/)
- Soullocke explains Soul Link at once and uses account-free shareable run URLs, but anyone
  with the link can edit. Do not copy that.
  [Soullocke](https://soullocke.vercel.app/),
  [Soullocke getting started](https://soullocke.vercel.app/guides/getting-started)
- nuzlockes.gg shows recent runs and leaderboards publicly with "Submit a run" as the
  contribution call to action. [nuzlockes.gg](https://nuzlockes.gg/),
  [game/category page](https://nuzlockes.gg/games/pokemon-emerald),
  [About](https://nuzlockes.gg/about). (The validator marked the About-page account funnel as
  only partly matching.)
- Speedrun.com and Twitch put games, leaderboards and streams in front of signed-out visitors.
  [Speedrun.com](https://www.speedrun.com/),
  [Speedrun live streams](https://www.speedrun.com/streams),
  [public user page showing sign-in links](https://www.speedrun.com/users/MgR),
  [Twitch directory](https://www.twitch.tv/directory)
- Desktop tools are more direct still: one sentence then Download.
  [LockeBox](https://heavyc.dev/lockebox/), [LiveSplit](https://livesplit.org/),
  [UPR FVX](https://upr-fvx.github.io/universal-pokemon-randomizer-fvx/)

### 2. Shallow public IA, separate operator control plane

Importance critical; confidence high on the separation, medium on exact path names.

Proposed public sitemap:

```text
/
├── /how-it-works
├── /runs
│   └── /runs/{immutable-run-slug}
│       ├── /pairs
│       ├── /timeline
│       └── /memorial
├── /games
│   └── /games/{game-slug}
├── /download
├── /setup
│   └── /setup/{game-slug}
├── /about
├── /privacy
└── /status
```

- Primary nav: `Live runs`, `How it works`, `Games`, `Set up`. Primary call to action:
  `Watch a live run`.
- Run identity: immutable, human-readable slugs such as `/runs/kanto-duo-radical-red`. Never
  expose or depend on the Manager's internal run ID.
- Read-only public API: `/api/public/runs` and `/api/public/runs/{slug}` only.
- Operator console stays on `http://127.0.0.1:8090/`. If one codebase serves both, use a
  separate `/console` namespace bound to loopback or an admin credential, and never share route
  tables between the public and operator origins.
- Phase 1 has no public registration, comments, editing or run administration.

Evidence: the Manager is a run-creation and process-control surface (new, start, stop,
archive, delete, ROM upload, Debug, broadcast proxying) at `server/manager.py:1701-1760`. The
run server mixes public status with reset, injection, queue, rollback, Twitch and OBS mutations
at `server/server.py:4733-4788`.

### 3. The public projection must be an allowlist, not today's status object

Importance critical; confidence high.

A purpose-built `PublicRun` DTO. Include: title, slug, lifecycle state, game family and
variant, timestamps, public display names, pair area/species/nickname/level/HP/party-or-box
state/death state and cause, human-readable events, rule chips, optional Twitch/VOD/Discord
links. Omit: stable mon keys, party-key dictionaries, full box inventory, queued command counts,
save-failure text, identity errors, cartridge admission details, ROM hashes, ports, stale
diagnostics, debug fields, bonus queues, raw event vocabulary, anything operator or credential.

Evidence: the status payload carries `save_failed`, `queued`, `identity_error`, admission data,
full party and box, connection diagnostics, stable pair keys, pending-bonus internals and raw
recent events (`server/server.py:2280-2415`; the validator found the `save_failed` range only
partly exact). The overlay catalog exposes implementation event names such as `force_faint`,
`key_change` and `no_catch` (`server/overlay_catalog.py:35-44`).

### 4. The hero: one sentence and one visual sequence

Confidence high for structure, medium for comprehension until tested with visitors.

> **Two Pokémon Nuzlockes. One shared fate.**
> SLink pairs the first Pokémon each player catches in the same area. If one falls, its
> partner falls too.

Buttons: **Watch live runs** (primary), **Set up SLink** (secondary), **See how it works**
(text link). When no run is live, the primary becomes **Browse recent runs**.

Demo, five to eight seconds, user-triggered and replayable:

1. Route 1: A catches Pidgey; B catches Rattata.
2. A chain draws between them; the label changes to **LINKED**.
3. A's HP reaches zero, the link pulses, B's HP reaches zero; the label becomes **SHARED FATE**.

Show a useful static first frame. No autoplay. Pause and Replay controls. Under
`prefers-reduced-motion`, replace the motion with three static states.

Below the demo: live or recent run cards; a three-step explanation (catches link, boxes stay
synced, faints propagate); supported games with maturity labels; requirements and setup; an
optional memorial teaser; open-source, privacy and status links.

Evidence: [Homepage Design: 5 Fundamental Principles](https://www.nngroup.com/articles/homepage-design-principles/),
[How Users Read on the Web](https://www.nngroup.com/articles/how-users-read-on-the-web/),
[Photos as Web Content](https://www.nngroup.com/articles/photos-as-web-content/),
[Animation for Attention and Comprehension](https://www.nngroup.com/articles/animation-usability/),
[Pause, Stop, Hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html),
[Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html).

### 5. The run page is a narrative scoreboard, not a shrunk Manager

Confidence high.

Four views: **Overview** (lifecycle, game pair, trainers, badges, alive and fallen counts, last
update, current location or battle, latest pairs and events), **Pairs** (active, separated,
boxed, waiting, fallen), **Timeline**, **Memorial**. Header state is `Live`, `Paused`,
`Completed` or `Abandoned`, and "completed" is never inferred from a stopped process. Show
`Live` only while fresh observations arrive; otherwise `Last updated N minutes ago` or
`Final snapshot`.

Evidence: the board already models the pair as the unit, A-side / bond / B-side
(`server/board.py:1-9`, `server/board.py:65-153`). The `Now` cards hold good spectator material
(`server/templates/_board.html:108-177`), and the event log is reusable
(`server/templates/_board.html:234-242`). The same fragment carries operator diagnostics, setup
steps and server-health warnings (`server/templates/_board.html:78-104`,
`server/templates/_board.html:194-230`).

### 6. Reuse the visual language and view models; replace the shell and controls

Confidence high.

| Current asset | Public use |
|---|---|
| Pair-centred A / bond / B geometry | Core run-page component |
| `Now` cards | "Live now" overview |
| Linked-pair chain visual | Landing demo and run-page pairs |
| Rules badges | "Run rules" chips |
| Event log | Timeline |
| Memorial wall | Run-specific `/memorial` |
| Theme tokens, sprites, HTMX/idiomorph refresh | Visual and runtime base |

Renames: `Board` to `Run overview`; `In party` to `In teams`; `Pending link` to
`Waiting to link`; `Split` to `Separated`; `Boxed` to `In boxes`; `Fallen` to `Memorial` or
`Fallen pairs`; `Broadcast` to `Stream setup` (console only); `Tools` to `Run preparation`;
`Patcher` to `Optional companion` (setup docs).

Hide from the public site: New Run and all run actions; ports, manager status, pin, archive,
delete; save, stale, identity, cartridge-admission and wrong-save diagnostics; launcher
instructions (move to `/setup`); Debug, raw JSON, manual links, injection, reset, backups,
rollback; randomizer, Calc, Patcher, Twitch credentials, OBS host/password/triggers; overlay
configuration. Keep moves, battle detail, held items, encounter tables and Upcoming Trainers
behind an expandable **Run details** section.

Evidence: pair vocabulary `server/board.py:20-29`, `server/board.py:160-192`; chain visual
`server/templates/stream/_links_root.html:1-52`; memorial tombstones nearly public-ready but the
rail and "Back to the board" shell are not (`server/templates/memorial.html:65-100`); Manager
header exposes ports, start/stop, pin, launchers, archive, delete
(`server/templates/manager.html:124-160`); the rail mixes New run, Broadcast, Twitch, OBS, Tools,
Calc, Debug, Overlays, Patcher (`server/templates/_rail.html:19-104`); Debug is manual linking,
injection, state toggles and rollback (`server/templates/_debug_panel.html:1-6`); OBS host, port
and password fields (`server/templates/_obs_panel.html:39-77`); Twitch app credentials and bot
setup (`server/templates/_twitch_panel.html:44-80`); `base.html` loads Alpine globally and
injects the theme switcher (`server/templates/base.html:1-39`), so a simpler landing shell is
preferable.

### 7. Supported Games must show maturity

Importance high; confidence high.

Each game page: generation and cartridge combinations; stable, partially verified or
experimental; what is proven; known limits; companion-patch needs; setup link; last
verification date once maintained. Best-supported first. Only Gen 3 FireRed/LeafGreen and
Radical Red are marked stable; Gen 1 and Crystal are partial; Emerald, Gen 4 and Gen 5 carry
explicit limits, and Gen 4/5 have never run against a real game (`README.md:5-17`). Compare
[Archipelago games](https://archipelago.gg/games).

## Where the report expects disagreement

- Do not put the current Manager board at the public `/`.
- Do not copy Soullocke's edit-by-link model; phase 1 is public-read, operator-write.
- Do not ship one undifferentiated Supported Games grid.
- Make `Watch a run` the dominant action; equal weight for `Start a run` reads as another
  self-hosted tracker.

## Recommendations

**P0**

1. Define the public data boundary first: a `PublicRun` DTO and a one-way publish mechanism. The
   local console gets a revocable **Publish run** action; the public host serves only sanitized
   `GET` resources. Never proxy or reuse `/api/status`, Manager routes or Debug routes.
2. Keep the operator plane local on `127.0.0.1:8090`. If code is shared during development,
   enforce a `/console` namespace with loopback or admin protection and a public-route allowlist.
3. Build the landing page on the one claim and the non-autoplaying Pidgey/Rattata demo with a
   static fallback.
4. Ship one canonical run page first: `/runs/{slug}`, then only `/timeline` and `/memorial`; keep
   pair filtering in-page. Live and completed runs use the same public schema.

**P1**

5. Build a separate `public_run.html` that reuses `board.py` and the visual macros, not the
   Manager shell.
6. Publish evidence-based game pages ordered by maturity, each labelled `Stable`,
   `Partially verified` or `Experimental`.
7. Accessibility and trust: descriptive titles, headings, readable body type, contrast, reduced
   motion, pause/replay, explicit last-updated times
   ([WCAG 2.4.2](https://www.w3.org/WAI/WCAG22/Understanding/page-titled.html),
   [WCAG 2.4.6](https://www.w3.org/WAI/WCAG22/Understanding/headings-and-labels.html)).
8. Validate one complete spectator journey: a stranger lands, explains Soul Link, opens a run,
   understands its state and finds setup without an account or operator terms. Verify that no
   public request reaches a mutation route.

**P2 / not in phase 1**

Public accounts, run editing, comments, full-text search, leaderboards, hosted orchestration,
chat, a public Manager.

## Unverified and open

- Public ingestion model: snapshot export versus one-way live relay, reconnects, replay,
  archival, and whether a public run survives its operator going offline. A one-run end-to-end
  spike would settle it.
- Publisher identity and moderation: who may publish, owner-chosen titles, review, or
  unguessable publish tokens.
- Privacy defaults for trainer names, nicknames, movesets, held items and exact timing. A
  revocable publish token with a visibility preview would settle the default.
- Ten-second comprehension: untested. Suggested prompts: "What is this?", "What happens to a
  partner?", "What can I do here?"
- No first-party desktop Soul Link tracker comparable was established.
- The original UPR homepage did not resolve; the maintained UPR FVX site was used instead.
- Twitch embeds, VOD archiving, chat and co-streaming: undecided; keep as optional run metadata.
- Validator partial matches (open): Archipelago nav wording, the nuzlockes.gg About-page account
  funnel, and the `save_failed` line range in `server/server.py:2280-2415`.
- Route naming conflicts with `spectator-share.md` (`/runs/{slug}` here, `/s/{slug}` there). See
  the README.

## Validation

11 accepted, 3 open (partly confirmed). A Sonnet validator checked 14 claims: 11 confirmed,
including every repo file:line claim (two had trivial line shifts); 3 partly. No invented URLs.
