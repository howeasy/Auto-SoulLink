# Spectator run page and share previews

Source: OMP research report `cx-1e847dcd` (SECOND_OPINION, read-only, repo at master a9bdce38).

## Summary

Ship a separate, sanitized spectator contract and a phone-first page. Do not reuse the operator
board with controls hidden by CSS. Serve it from a public, GET-only origin or allowlist, then add
a versioned 1200×630 preview image and a durable death timeline.

The report's own strongest doubt: live history is a 200-entry ring buffer, so a spectator page
built on today's payload can look complete while silently losing the start of the run.

## Key findings

### 1. Spectator and operator are different products

Importance critical; confidence high.

The board is an operator console:

- Save failures and identity/admission warnings: `server/templates/_board.html:83-94`
- Trainer names, connection age, last event, ball count, battle moves/PP, encounter tables,
  trainer panels, calc-preview attributes: `server/templates/_board.html:105-168`
- Cartridge and launcher downloads: `server/templates/_board.html:179-194`
- Raw trainer names around pair sections: `server/templates/_board.html:200-207`
- Event log: `server/templates/_board.html:234-242`
- `board_context()` builds launcher and ROM URLs unconditionally: `server/board.py:209-252`
- Standalone header shows the TCP port plus Calc and Debug: `server/templates/dashboard.html:27-33`
- The rail shows New run, Broadcast, Tools, Calc, Debug, Overlays, Twitch, OBS, Patcher:
  `server/templates/_rail.html:15-120`

Remove for spectators: save-failure text (can disclose filesystem paths); identity and admission
warnings, including ROM fingerprints and SHA-1 prefixes (`server/server.py:524-559`); ports and
host details; launcher, ROM, debug, calc, broadcast and operator nav; raw `key`, OT ID,
pending-bonus and bonus-pair identifiers; full unlinked party and box, queued commands, exact
moves/PP, encounter tables, hidden calc attributes; connection freshness and stale warnings
unless deliberately public. The identity warning contains truncated expected and incoming OT IDs
(`server/state.py:995-1005`).

Keep: run title, game/region, public aliases; live/stopped/game-over; attempt number, badge
totals, current area; one compact "now" per player (area, wild or trainer battle, active mon);
pair cards (area, nickname/species, level, sprite, shiny, HP/status, alive/pending/boxed/fallen);
rule badges; latest death; memorial and timeline.

Raw identifiers are present even when not printed: `_half()` carries `key`
(`server/board.py:83-99`); party entries get the raw key (`server/server.py:2222-2240`); links,
killfeed and bonus queues expose more keys (`server/server.py:2336-2423`). The public DTO must
never be `/api/status`.

Hiding HTML is not enough: the same app registers status, reset, inject, attempts, launcher,
debug, calc and raw-state routes (`server/server.py:4733-4788`). CSRF middleware rejects
cross-origin browser writes but lets headerless native callers through
(`server/http_safety.py:40-70`); it is not spectator authorization.

Proposed GET/HEAD-only routes:

```text
/s/{public_slug}
/s/{public_slug}/fragment
/s/{public_slug}/preview/{revision}.png
/api/public/s/{public_slug}
```

A separate public hostname or reverse-proxy allowlist rejects every other path and every
mutation.

### 2. Phone layout: keep the bond, do not stack

Importance high; confidence high.

Desktop pairs are a three-track A/bond/B grid (`server/static/board.css:337-385`). At 760px it
collapses to one column, so A, bond and B stack (`server/static/board.css:397-401`), which the
report says destroys the comparison that makes the board useful.

Comparable live-follow pages:

- LiveSplit: current segment, total and delta in one scan.
  https://github.com/LiveSplit/LiveSplit
  https://raw.githubusercontent.com/LiveSplit/LiveSplit.github.io/master/images/livesplittimer.png
- Speedrun.com Live: compact sortable board without management controls.
  https://www.speedrun.com/live
- The Run: separates Live, Runs and Recap. https://therun.gg/live
- Soullocke: timeline/summary split, player columns, badges, teams, boxes, grave.
  https://github.com/jynnie/soullocke
  https://raw.githubusercontent.com/jynnie/soullocke/main/public/Preview.png
- MyPokePanion overlay: run identity, party, route, badges, deaths, latest event; token-protected
  and rotatable. https://mypokepanion.com/en/nuzlocke/
  https://mypokepanion.com/nuzlocke/stream-overlay.png

Soullocke is a warning: every link holder can edit, and mobile support is listed as future work.
https://soullocke.vercel.app/ https://soullocke.vercel.app/privacy

Mobile hierarchy: sticky run header; attempt, alive/fallen, badges, locations; latest meaningful
event or death one tap away; filter chips (Standing / Pending / Boxed / Fallen); pair list in
story order; timeline as a second view.

**Keep each pair as two narrow columns plus a 24-32px bond spine, even at 320px.** Shrink
sprites and type rather than stacking. (This conflicts with `mobile-a11y.md`; see the README.)

Semantic fix: `board.counts.alive` counts linked rows not in `fallen` and excludes
`pending_rows` (`server/board.py:163-181`). Label it **"bonds standing"**, or define and test a
real living-Pokémon count.

### 3. Link previews need a generated, versioned image

Importance high; confidence high for OG/Meta and the approach, medium for current X/Discord
details.

`server/templates/base.html:3-16` has no canonical, Open Graph or Twitter tags. Add `canonical`,
`og:type`, `og:title`, `og:description`, `og:url`, `og:image`, `og:image:secure_url`,
`og:image:type`, `og:image:width` (1200), `og:image:height` (630), `og:image:alt`, and
`twitter:card=summary_large_image` with title, description, image and image alt.

- Open Graph requires `og:title`, `og:type`, `og:image`, `og:url` and recommends image alt.
  https://ogp.me/
- Meta recommends 1200×630 (1.91:1, 8 MB max) and a new image URL when content changes, since
  images are cached by URL. https://developers.facebook.com/documentation/sharing/webmasters/images
- X's large-image card (`summary_large_image`, raster, near 2:1) is documented only in a preserved
  copy; verify with a real post.
  https://web.archive.org/web/20220123005523/https://developer.twitter.com/en/docs/twitter-for-websites/cards/overview/summary-card-with-large-image
- Discord has no separate link-unfurl meta set; it uses Open Graph. Its Bot API confirms embed
  images must be HTTP(S) but gives no link-preview pixel contract.
  https://docs.discord.com/developers/resources/message#embed-object-embed-image-structure

Generation: Pillow is the lightest option but not installed (`requirements.txt:1-6`); a
Chromium/Satori screenshot is heavier. Composition: 1200×630, title, game, LIVE/ENDED, attempt,
standing/fallen totals, four standing pairs plus the latest fallen pair if room, aliases only,
large sprites, little text, high contrast. Do not regenerate on HP ticks; hash only preview state
(pair formed/died, species/nickname, badges, attempt, phase). Serve
`/s/{slug}/preview/{sanitized-payload-hash}.png` with
`Cache-Control: public, max-age=31536000, immutable`, keep old revisions, generate off the event
loop and write atomically. Adapters mix local RR sprites and remote PokeAPI images
(`server/adapters/gen3_frlge.py:221-252,348-395`), so do not assume sprites are local.

### 4. The death log is reusable; recent events are not a durable story

Importance high; confidence high.

The killfeed has what a death timeline needs: `killed_at`, area, cause, killer, initiating
player, both nicknames, species, sprites, levels, pair status (`server/server.py:2387-2416`). The
memorial already formats battle cause, dead zone, whiteout and time
(`server/templates/_macros.html:163-198`; `server/templates/memorial.html:66-89`).

But the event log is a 200-entry ring (`_EVENTS_MAX = 200`, `server/server.py:79-80`; ring and
raw `key`, `server/server.py:1571-1600`) and carries diagnostics and identity text.
`attempts_count` is one manually set integer, not a history; zero means "not set"
(`server/state.py:200-201`; `server/server.py:3016-3029`). Manager registry creation time gives a
coarse start (`server/manager.py:906-913`); there is no end timestamp or attempt archive.

### 5. Privacy needs a display policy, not hidden CSS

Importance critical; confidence high.

Never public: mon keys or OT IDs (Gen 3 keys concatenate personality and OT ID); identity and
admission errors; ROM seeds, hashes, fingerprints or contracts; ports, hostnames, filesystem
errors, queue state; emulator or viewer IPs (peer IPs are logged on connect,
`server/server.py:1161-1162`); unlinked party and box state unless players opt in; raw event
objects.

Trainer names may be a streamer handle or a legal name. Default to an operator-set alias
("Run A / Run B" or an explicit handle); let players opt in to the in-game name. Treat nicknames
the same way. Build the DTO as an allowlist; no "strip known secret keys" pass, because a new
operator field would then leak silently.

## Wireframe (phone)

```text
┌──────────────────────────────────┐
│ Run Name                    ● LIVE│
│ Radical Red · Attempt #3         │
│ 12 bonds standing · 2 fallen     │
│ A ◇◆◆◇ 3/8       B ◇◆◇◇◇ 2/8   │
│ A: Route 9 · in battle          │
│ B: Ecruteak City                 │
├──────────────────────────────────┤
│ LATEST · 2m ago                  │
│ ⚔ Route 9                        │
│ Pikachu ×  Cyndaquil fell        │
│ Wild Rattata Lv18                │
├──────────────────────────────────┤
│ [Standing] [Pending] [Fallen]    │
│ ROUTE 1 · STANDING               │
│ [Pikachu Lv12]  ∞  [Cyndaquil12] │
│ ROUTE 22 · FALLEN                │
│ [Charmander] × [Torkoal]         │
└──────────────────────────────────┘
```

## Recommendations

**P0: establish the public boundary**

1. Add `/s/{public_slug}` and a dedicated `build_public_status()` allowlist.
2. Never expose the existing `/api/status` payload publicly.
3. Put spectator routes on a separate public origin or a GET/HEAD-only reverse-proxy allowlist.
4. Block `/debug`, `/api/debug`, `/api/reset`, `/api/inject*`, `/api/attempts`, `/launcher`, calc,
   OBS, Twitch, patcher, raw-state and internal Manager routes.
5. Default trainers to public aliases; never emit mon keys, OT IDs, hashes, IPs, ports or save
   errors.

**P1: phone-first view**

6. A/bond/B side by side at 320-430px; latest death as a distinct high-contrast card; memorial
   and timeline as tabs over one data source; no rail, calculator, encounter tables or move panels.
7. Keep 2-second HTMX polling only if the sanitized fragment is cheap; add an opaque revision or
   ETag.

**P1: share metadata and images**

8. Canonical, OG and Twitter tags; Pillow-generated 1200×630 PNGs, asynchronous, hashed on headline
   state, immutable URLs, old images kept.
9. A trusted `PUBLIC_BASE_URL`; never derive social URLs from an untrusted Host header.
10. Default run pages to `noindex,nofollow` in phase 1.
11. Test with Meta Sharing Debugger, a real X post and a real Discord paste.

**P2: the run story**

12. A sanitized append-only `public_timeline` per run: start/resume, link formed, badge gained,
    whiteout, death, memorialized, attempt changed, game over. Opaque event IDs; no mon keys, OT
    IDs, hashes or infrastructure text.
13. One death record rendered three ways: newest-first live timeline, chronological post-run story,
    memorial gallery.
14. Summary fields: result, start and end, attempt, badges, pairs formed, bonds standing, deaths,
    dead zones, clause badges. Define attempt semantics explicitly.
15. A short "About Soul Link" below the live content.

**Acceptance gates**

- OT IDs, mon keys, ROM hashes, ports and filesystem paths are absent from HTML, JSON, DOM, image
  metadata and logs served publicly.
- Every non-GET public request is rejected before reaching SLink.
- Useful at 320px without vertical A/bond/B stacking.
- Stopped and restarted runs still render persisted pairs, memorial and attempts.
- Meta, X and Discord previews resolve from a production HTTPS URL and survive a state update.

## Where the report expects disagreement

- Reject "reuse the board and hide operator sections with CSS".
- `attempts_count` is not attempt history.
- Do not expose trainer names automatically.
- Keep a compact battle context ("now" card); removing it makes the page feel disconnected.

## Unverified and open

- X card dimensions and caching: the official page is gone; the old validator redirects to login.
  Verify 1200×630 with a real post.
- Discord unfurl sizing and cache: no official pixel contract; paste a production URL to check.
- No maintained Pokémon-specific Twitch Extension was found; absence is unverified.
- Indexing: "shareable" does not require indexing; `noindex,nofollow` is safer unless creators opt
  in.
- Existing runs cannot recover events older than the 200-entry ring.
- Public aliases and consent UI do not exist yet; the operator workflow needs a product choice.
- Route naming conflicts with `landing-ia.md` (`/s/{slug}` here, `/runs/{slug}` there), and the
  phone layout conflicts with `mobile-a11y.md`. See the README.

## Validation

14/14 accepted. A Sonnet validator confirmed every checked claim: the board banners, the
unconditional launcher URLs in `board_context`, admission and identity text leaking fingerprints
and OT prefixes, the 200-entry event ring, `attempts_count` as a single int, the ogp.me required
tags, Meta's 1200×630 size, X `summary_large_image`, and Discord embeds. It flagged the route
naming conflict with `cx-141d8654`.
