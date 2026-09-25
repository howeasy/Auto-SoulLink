# Phase 1 decisions

The owner decided the open questions in [README.md](README.md) on 2026-09-25. These answers
replace the "Decisions needed" and "Cross-topic conflicts" lists there.

| # | Question | Decision |
|---|---|---|
| 1 | Route naming | `/runs/{slug}` (with `/runs/{slug}/timeline`, `/memorial`); public API under `/api/public/runs/{slug}` |
| 2 | Phone pair layout | Side by side down to 320px, with a slim spectator card (sprite, name, level, HP; no ability, item or moves) |
| 3 | Where public pages are served from | The host's own read-only spectator app, behind an outbound tunnel (Cloudflare Tunnel or similar). The page is offline when the host is |
| 4 | Default visibility | Private until the host publishes with a preview. Published runs are unlisted or listed |
| 4b | Landing page run list | Lists only runs published as "listed"; with none, it shows the how-it-works demo |
| 4c | Search engines | Every run page is `noindex` |
| 5 | Player names | In-game trainer names and nicknames, shown as-is (no alias layer) |
| 6 | Radical Red sprites | Use the bundled sprites publicly, with credit to the source repo |
| 7 | Pokémon IP | No special handling |
| 8 | Rail mark | Keep the Poké Ball |
| 9 | Sprite hosting | Self-hosted (already the case for RR; the other gens' hot-links are still open) |
| 10 | Typography | Keep the current fonts |
| 11 | Public themes | All picker themes (so each needs a full contrast pass); `transparent` stays OBS-only |
| 12 | Games | Gen 1, 2 and 3 can publish, each with a maturity label. Gen 4/5 stay hidden |
| 13 | Accounts | None in phase 1 |
| 14 | Video | Link out to the host's Twitch/YouTube only; no ingest or relay |
| 15 | Notifications | In-page toasts only. Screen readers hear new links, pair deaths and run over, with a Pause control |
| 16 | Onboarding order | Player ZIP route, correct host address and clear connection states first |
| 17 | Attempts | Manual: the host sets the number, public pages show it |

## Consequences

- Prerequisite 4 in the README (public alias) is dropped. Trainer names are an explicit owner
  choice; the publish preview must still show exactly what will be public.
- Prerequisites 1-3 stand: a sanitized, allowlisted public projection (never `/api/status`), a
  GET-only spectator app that is the only thing the tunnel reaches, and one ID per logical event.
- Every picker theme stays public, so the four themes still under 3:1 on control borders (Grape,
  Fire, Ice, Watermelon) are in scope.
- Live transport was not asked: default to the existing HTMX polling of a cheap fragment with an
  ETag, and move to SSE revisions only if measured load needs it.
