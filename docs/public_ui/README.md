# Public UI research: phase 1 spectator site

Research notes for a public version of SLink. Nothing here is built yet; this directory records
seven research reports and the decisions they leave open.

## What phase 1 is

Phase 1 is a **spectator site**: a public landing page and public, read-only run pages. Players
still self-host the game side: BizHawk, the Lua client, the SLink server and the Manager all stay
on the players' own machines. Spectators need no account and can change nothing. A full hosted
service (phase 2) is out of scope, except where a phase-1 choice would constrain it.

## Sources and method

Each topic file condenses one OMP research report run against master a9bdce38. A Sonnet validator
checked each report's claims at source; the counts are in each file's "Validation" line. The full
replies were read with `magi mail --task <id>`, because the `magi exchange <id>` record truncates
long replies. Where a validator worked from a truncated copy, the topic file says which parts were
not checked. File:line citations and URLs are kept as the reports gave them; line numbers refer to
master a9bdce38.

Nothing here is legal advice. Where a report cites a legal or IP source, these docs state what the
source says.

## Topics

**[Landing page and information architecture](landing-ia.md)** (`cx-141d8654`). Comparable hobby
sites keep browsing public and put accounts at the point of contribution. Proposes a shallow public
sitemap (`/`, `/how-it-works`, `/runs/{slug}`, `/games`, `/setup`, …) kept apart from the local
operator console on `127.0.0.1:8090`, a hero line ("Two Pokémon Nuzlockes. One shared fate.") with
a non-autoplaying catch → link → shared-fate demo, and a run page built as a narrative scoreboard
that reuses the board's pair geometry, not the Manager shell. Game pages must show maturity
(stable, partly verified, experimental).

**[Setup and onboarding](onboarding.md)** (`cx-119fd772`). The biggest newcomer blocker is
packaging: the Manager serves only a `.lua` stub, while a tested player ZIP builder exists with no
route. Other blockers: wrong host IP baked in from the Host header, the BizHawk version mismatch
(docs say 2.9+, Gen 1 refuses below 2.11), experimental games offered beside proven ones, and a
waiting screen that cannot tell failure modes apart. A browser-only ROM hash check works only in a
secure context and has known-good hashes for Gen 1 only. Includes a step-by-step wizard with copy
for each state.

**[Spectator run page and share previews](spectator-share.md)** (`cx-1e847dcd`). Spectator and
operator are different products; hiding operator HTML is not enough because raw keys, OT IDs and
mutation routes sit behind it. Proposes a GET-only `/s/{slug}` surface, a phone layout that keeps
each pair side by side, Open Graph and Twitter tags with a generated 1200×630 image at a versioned
URL, and an append-only public timeline, since today's event log is a 200-entry ring and
`attempts_count` is one integer.

**[Mobile layout and accessibility](mobile-a11y.md)** (`cx-303c3e92`, plus contrast `cx-c518530b`,
board `cx-6214a81c` and shell `cx-f486dbca`). At 360px the rail leaves about 136px for content, and
the 900px rule targets a retired class. Proposes an app bar and off-canvas menu below 900px,
stacking pairs below 600px, one polite live region outside the morph target that announces only
links and deaths, a Pause control, and fixes for colour-only status, contrast (edge tokens fail 3:1
everywhere; Smoke's brand text is 1.6:1), the missing skip link and `aria-current`, and the theme
picker's keyboard handling.

**[Accounts and partner invites](accounts-invites.md)** (`cx-31d45b60`). Phase 1 needs no accounts.
Use separate capabilities (viewer link, host secret, single-use partner invite, connection lease),
private or unlisted by default, and an explicit publish step with a preview. Phase 2 adds optional
Discord sign-in (`identify` only) with Google or email fallback; Twitch is a channel connection;
passkeys later. Includes an invite flow with host approval, a role and visibility matrix, and the
privacy screens.

**[Brand and visual identity](brand-identity.md)** (`cx-ed94d6ce`). Keep pixel type for display
only and use Atkinson Hyperlegible for body text. Replace the Poké Ball rail mark with an original
twin-link mark. Expose Auto, Light and Dark publicly. Ship a standard favicon and manifest set. Stop
hot-linking sprites from `master`. Records two IP facts that bear on current choices (below).

**[Live updates and notifications](live-updates.md)** (`cx-40be13ca`). Today's SSE is a bare ping
fired on every TCP message. Proposes SSE as a revision signal plus a conditional HTMX fragment GET,
not WebSockets; a spectator-only origin behind an outbound managed tunnel; managed ingest for any
video; a freshness-based live indicator; and in-page toasts before browser notifications or Web
Push, which need canonical event IDs first.

## Prerequisites shared by every topic

Every report assumes these four items. None exists today.

1. **A separate, sanitized public projection. Never `/api/status`.** An allowlisted DTO built for
   spectators. The current status payload carries raw mon keys, OT IDs, party and box snapshots,
   identity and admission errors, ports and save-failure text (`server/server.py:2280-2415`,
   `2336-2423`), and the same app serves reset, inject, debug and launcher routes
   (`server/server.py:4733-4788`). No "strip known secrets" pass: a new operator field would leak
   silently. (landing-ia, spectator-share, accounts-invites, live-updates)
2. **A spectator-only origin or allowlist.** Public traffic reaches only GET/HEAD spectator routes,
   on a separate app or hostname or behind an edge allowlist that denies everything else. The
   Manager and run server bind `0.0.0.0` with no auth, and CSRF middleware is not authorization
   (`server/http_safety.py:40-70`). (all topics)
3. **Canonical event IDs.** Events have no unique ID (`server/server.py:1590-1600`); a link is
   logged once per player and a death up to three times. Timelines, screen-reader announcements,
   toasts, notifications and SSE resume all need one opaque ID per logical event. (spectator-share,
   mobile-a11y, live-updates)
4. **A public alias instead of trainer names.** Trainer names may be a streamer handle or a legal
   name, and the identity lock pairs them with OT IDs. Default to an operator-set alias; showing
   the in-game name or nicknames is opt-in. (spectator-share, accounts-invites, landing-ia)

## Decisions needed from the owner

1. **Route naming.** `/runs/{slug}` or `/s/{slug}` for public run pages. See conflict (a).
2. **Phone pair layout.** Side by side with a bond spine, or stacked A → bond → B below 600px. See
   conflict (b).
3. **Where public pages are served from.** A one-way publish to a separate public host, or the
   host's own spectator-only app behind a managed tunnel. See conflict (c). This also decides
   whether a run page survives its host going offline.
4. **Default visibility and discovery.** Whether runs are private or unlisted until published, and
   whether the landing page lists live runs. See conflict (d). Also: `noindex` by default?
5. **Aliases.** Confirm alias-by-default, with trainer names and nicknames opt-in.
6. **IP fact 1: the Radical Red sprites have no licence.** The bundled `server/static/sprites/rr/`
   (1,322 PNGs) is extracted from `JwowSquared/Radical-Red-Pokedex`, a repository that declares no
   licence (GitHub API: `license: null`). No permission is on record. Decide whether RR runs can be
   shown publicly with these sprites, with a neutral placeholder, or not until permission is
   obtained. See [brand-identity.md](brand-identity.md).
7. **IP fact 2: The Pokémon Company asks people not to use its IP.** Its US support page says it
   cannot review requests to use Pokémon characters, names or designs, and asks people not to use
   them or associate them with a project in any way. This bears on the whole public site: the mark,
   the sprites, preview images and the use of "Pokémon" in copy. Decide whether to get legal advice
   before launch. See [brand-identity.md](brand-identity.md).
8. **Replace the Poké Ball rail mark** with an original mark before launch.
9. **Sprite hosting.** Self-host from a pinned build-time import with credits, in place of runtime
   hot-links to `master`.
10. **Typography.** Pixel faces for display only, with Atkinson Hyperlegible for body and UI text.
11. **Public themes.** Auto, Light and Dark only, or more. See conflict (e).
12. **Which games appear publicly, and how they are labelled.** Maturity labels on game pages;
    whether experimental generations are hidden in the default run form.
13. **Accounts.** Confirm no accounts in phase 1. The host-secret, invite and slot-lease flows then
    wait for phase 2.
14. **Video.** Whether phase 1 carries video at all. This decides whether managed video ingest and
    its cost apply.
15. **Notifications and announcements.** In-page toasts only in phase 1? Which events a screen
    reader hears. See conflict (f).
16. **Onboarding order.** Player ZIP route and connection states first, or the browser ROM checker
    first. The onboarding report argues for the ZIP and connection states.
17. **Attempt semantics.** What an "attempt" is, since `attempts_count` is one manually set integer.

## Cross-topic conflicts

Each conflict is laid out with both sides. None is decided here.

### (a) Route naming: `/runs/{slug}` or `/s/{slug}`

- **`/runs/{slug}` (`landing-ia.md`, `cx-141d8654`).** Part of a readable sitemap: `/runs` lists
  runs and `/runs/{slug}` has `/pairs`, `/timeline` and `/memorial` under it. Immutable,
  human-readable slugs such as `/runs/kanto-duo-radical-red`. Public API at `/api/public/runs/{slug}`.
  The report was only medium-confident on exact path names.
- **`/s/{slug}` (`spectator-share.md`, `cx-1e847dcd`).** A short share URL with `/s/{slug}/fragment`,
  `/s/{slug}/preview/{revision}.png` and `/api/public/s/{slug}`. A short, separate prefix is easy to
  allowlist at the edge as a GET-only spectator surface, and a short link suits sharing.
- The validator flagged the conflict. Both reports agree on an opaque or immutable public slug that
  never exposes the Manager's run ID, and on a separate `/api/public/…` namespace.

### (b) Phone pair layout: side by side or stacked

- **Side by side, 24-32px bond spine, down to 320px (`spectator-share.md`, `cx-1e847dcd`).** The pair
  is the unit, and the board is useful because A and B can be compared at a glance. Stacking A, bond
  and B "destroys the comparison". Comparable live-follow pages (LiveSplit, Speedrun.com Live,
  MyPokePanion's overlay) compress to a scannable summary. Shrink sprites and type instead of
  stacking, and move detail (moves, encounter tables, calc) off the spectator page so the halves
  fit.
- **Stack A → bond → B below 600px (`mobile-a11y.md`, `cx-303c3e92`).** At 400px each half is about
  160-170px before padding, leaving little room for sprite, nickname, species, ability, item and HP.
  Stacking keeps source order, no partner is hidden, names can wrap instead of being cut off, and it
  fits WCAG 1.4.10 Reflow. It needs visible Player A/B labels and an unmirrored B. The same report
  rates "bond header plus two narrow columns" workable only as a deliberately simplified summary,
  not the full component shrunk.
- Two things narrow the gap. The spectator-share layout assumes a reduced spectator card (no
  ability or item), while the mobile-a11y costs are measured against today's full card. Both reject
  a swipe or carousel that hides the partner.

### (c) Where public pages are served from

- **One-way publish to a separate public host (`landing-ia.md`).** The local console gets a
  revocable "Publish run" action; the public host serves only sanitized GET resources and never
  proxies local routes. Completed runs and live runs share one schema, and a run page can outlive
  the host's session.
- **Host's own spectator-only app behind an outbound managed tunnel (`live-updates.md`).** Keep the
  game and control plane on the LAN and expose a sanitized spectator app through Cloudflare Tunnel or
  similar. This is the least new infrastructure for live data. A custom relay comes only if measured
  load requires it.
- `accounts-invites.md` lists the deployment shape as unknown and notes that it changes how soon
  accounts are needed.

### (d) Run discovery and default visibility

- **Public discovery (`landing-ia.md`).** The primary call to action is "Watch live runs", with live
  or recent run cards on the landing page and a `/runs` index.
- **Private or unlisted until explicitly published (`accounts-invites.md`); `noindex` by default
  (`spectator-share.md`).** Unlisted runs are never listed. Public runs may be listed only after an
  explicit publish with a preview.
- These fit together only if the landing page lists runs whose hosts chose "public, listed". The
  landing page's fallback ("Browse recent runs") then depends on how many hosts opt in.

### (e) How many themes are public

- **Auto, Light and Dark only (`brand-identity.md`).** Keep the other palettes for the Manager and
  OBS, and never expose `transparent`.
- **"All eight public themes" (`mobile-a11y.md`).** Its contrast and audit steps assume the eight
  picker themes stay public. If only three are public, the audit narrows to those three, but the
  Smoke and edge-token fixes still matter for the Manager.

### (f) What a screen reader announces

- **Links and pair deaths only, optionally run over (`cx-303c3e92`).** Keep announcements rare.
- **Also disconnects, area changes and dead zones (`cx-6214a81c`).** This covers more state changes.
- Both agree on one polite region outside `#content`, no HP announcements, and never `aria-live` on
  the morph target.

### (g) Smaller tensions

- **Preview images.** `spectator-share.md` composes per-run cards from sprites. `brand-identity.md`
  keeps third-party sprite art out of the site's social card and flags sprite rights. Per-run cards
  depend on decision 6 and 7.
- **Transport.** `spectator-share.md` keeps 2-second HTMX polling if the fragment is cheap, with an
  ETag. `live-updates.md` prefers SSE revisions plus conditional GETs, with 5-10 second conditional
  polling as the fallback. Both call for an opaque revision.

## Files

- [README.md](README.md): this index
- [landing-ia.md](landing-ia.md)
- [onboarding.md](onboarding.md)
- [spectator-share.md](spectator-share.md)
- [mobile-a11y.md](mobile-a11y.md)
- [accounts-invites.md](accounts-invites.md)
- [brand-identity.md](brand-identity.md)
- [live-updates.md](live-updates.md)
