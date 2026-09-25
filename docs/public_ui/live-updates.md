# Live updates and notifications

Source: OMP research report `cx-40be13ca` (SECOND_OPINION, read-only, repo at master a9bdce38).

## Summary

Use SSE as a revision (invalidation) channel followed by a conditional HTMX fragment GET. Do not
use WebSockets for a read-only spectator feed. Put a sanitized, read-only public surface behind an
outbound-only managed tunnel; use managed live-video ingest if video is included. Start with
accessible in-page toasts, not Web Push.

The report's own strongest doubt: if the meaningful board revision changes about every two seconds,
correctly cached ETag polling may be simpler and cheaper than 1,000 long-lived streams. Measure the
real change rate before removing polling.

## Key findings

### 1. Today's SSE endpoint is a ping, not a resumable revision stream

Importance high; confidence high.

- The board polls every two seconds: `server/templates/_board.html:69`.
- A standalone run polls `/`, rebuilding the whole dashboard before HTMX picks `#content`:
  `server/server.py:2443-2463`.
- The Manager has a lighter fragment endpoint, but each request fetches fresh status from the
  child server: `server/manager.py:786-824`.
- SSE keeps one `asyncio.Queue(maxsize=1)` per browser and writes only `retry: 3000` plus empty
  `event: ping`: `server/server.py:1057-1074`, `server/server.py:1093-1157`.
- Every accepted TCP message calls `_notify_sse()`, whether or not public data changed:
  `server/server.py:1353-1354`.
- The docstring promises a `status` event that is never sent (`server/server.py:1096-1101` versus
  `server/server.py:1124-1153`); the debug page listens for it anyway
  (`server/templates/_debug_panel.html:304-324`).
- No `id:` is emitted, so browsers cannot send `Last-Event-ID`.
- The Manager proxy forwards `Content-Type` and `Accept` but not `Last-Event-ID`:
  `server/manager.py:1502-1529`.
- The calc bridge closes `EventSource` on the first error and builds a new one, losing native
  reconnect state: `calc/src/js/slink_bridge.js:2221-2238`.
- The root Manager `/api/events` is deliberately absent; per-run SSE goes through the proxy:
  `tests/unit/test_manager_pages.py:102-105`.

Consequence: wiring the board to today's SSE could turn every game-client message into a fragment
GET per spectator. A revision or dirty-state gate is required.
[WHATWG SSE §9.2](https://html.spec.whatwg.org/multipage/server-sent-events.html).

### 2. SSE invalidation beats WebSockets; conditional polling is the fallback

Importance high; confidence high.

| Option | Direction | Connections at N viewers | Advantages | Disadvantages |
|---|---:|---:|---|---|
| Blind 2 s poll | Pull | Short requests | Simple, CDN-friendly | Returns unchanged state; requests scale linearly |
| ETag/304 poll | Pull | Short requests | Small response when unchanged | Still pays request and revalidation cost |
| SSE revision + fragment GET | Push signal, pull body | N long-lived streams | Low idle volume, native reconnect and cursor | Proxy buffering and timeouts |
| WebSocket | Bidirectional | N long-lived sockets | Chat, client commands | None needed; more protocol and proxy handling |

htmx describes SSE as a lighter, one-way WebSocket alternative that passes proxies more easily, with
exponential reconnect ([htmx SSE extension](https://htmx.org/extensions/sse/)); WebSockets suit
two-way messaging ([htmx WebSocket extension](https://htmx.org/extensions/ws/)).

Client shape: one native `EventSource` per page plus `htmx.ajax()` for the fragment. If declarative
htmx is preferred, vendor `htmx-ext-sse` 2.2.4+ (needed with idiomorph); it is not vendored today
(`server/static/vendor/VERSIONS.md:10-14`).

SSE `id:` and fragment `ETag` are different mechanisms that can share one opaque value such as
`run-instance:revision`. The board is a snapshot, so replaying missed events is unnecessary: on
(re)connect advertise the current revision and fetch only when the client is behind. Durable
notifications need their own event IDs and log.
[MDN EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource),
[RFC 9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#name-conditional-requests).

The six-connection figure is a browser HTTP/1.1 pool behaviour, not a protocol rule
([MDN: Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events),
[RFC 9112 §9.4](https://www.rfc-editor.org/rfc/rfc9112.html#name-concurrency)). WebSockets do not
avoid it. Terminate HTTP/2 at the edge and keep one SSE stream per page. Comments claiming "Chrome
caps" or that the dashboard holds SSE are stale: `server/templates/dashboard.html:5-8`,
`server/templates/stream/_base.html:11-17`.

Proxy and CDN requirements: `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`,
`X-Accel-Buffering: no`; a named heartbeat event every 15 seconds (a comment keeps proxies alive but
is invisible to `EventSource`); no buffering compression
([nginx proxy buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering));
read timeouts above the heartbeat (Cloudflare documents 125 s origin read and 900 s idle:
[Cloudflare connection limits](https://developers.cloudflare.com/fundamentals/reference/connection-limits/));
same origin for page and fragment; no CDN caching of SSE, but cache versioned assets and
microcache the fragment ([Cloudflare default cache behavior](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)).
The development no-cache policy (`server/templating.py:139-167`) should give way to versioned URLs
with `Cache-Control: public, max-age=31536000, immutable` in a public release.

### 3. Scale needs revision filtering and edge collapsing

Importance high; confidence medium pending a load test.

| Viewers | Current 2 s polls | Conditional polls | SSE streams |
|---:|---:|---:|---:|
| 10 | 5 GET/s | 5 GET/s | 10 |
| 100 | 50 GET/s | 50 GET/s | 100 |
| 1,000 | 500 GET/s | 500 GET/s | 1,000 |

Conditional polling removes bodies, not requests. With `r` meaningful changes per second, SSE costs
about `r × viewers` fragment GETs unless the edge collapses them. At an illustrative, unmeasured
50 KiB fragment, blind polling is about 0.9 GB/hour at 10 viewers, 9 GB/hour at 100 and 90 GB/hour
at 1,000. Because `_notify_sse()` fires on every inbound message, including companion traffic,
naive wiring could be worse than today's poll: publish only when the public projection changes,
coalesce on a trailing edge, cap the rate.

### 4. Put an edge in front; do not build a custom relay yet

Importance high; confidence high.

- **Game and control plane:** BizHawk TCP `54321`, Manager admin, debug, injection, reset, archive
  and ROM tools stay on LAN or VPN.
- **Public spectator plane:** sanitized board HTML, status, event feed and a named public SSE
  endpoint only.
- **Video plane:** one encoded stream to managed ingest, if video is carried.

The run and Manager default to `0.0.0.0` (`server/server.py:4884-4887`, `server/manager.py:1807-1810`).
Proxying the whole Manager would expose reset, injection, debug and run start/stop/delete
(`server/server.py:4737-4783`, `server/manager.py:1709-1716`). So: a separate spectator-only aiohttp
app, or an edge allowlist that denies everything else. CSRF middleware is not authentication.

- Phase 1: Cloudflare Tunnel or an equivalent outbound-only managed tunnel; it hides the origin from
  DNS and allows closing inbound ports
  ([Cloudflare Tunnel architecture](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)).
  It hides the site origin, not the home IP if another public service reveals it.
- Later, only if measured load demands it: a small relay with one authenticated upstream
  subscription that sanitizes and renders once and fans out.
- Direct port forwarding is the worst option.

Video, illustrative 6 Mbps feed watched for one hour:

| Viewers | Direct home egress | Cloudflare Stream delivery |
|---:|---:|---:|
| 10 | 60 Mbps aggregate | ~$0.60 |
| 100 | 600 Mbps aggregate | ~$6 |
| 1,000 | 6 Gbps aggregate | ~$60 |

[Cloudflare Stream](https://developers.cloudflare.com/stream/) at $1 per 1,000 viewer-minutes
([pricing](https://developers.cloudflare.com/stream/pricing/)). Two feeds double both columns;
recording storage is extra. For video, managed ingest is not optional.

### 5. The live indicator describes data freshness, not socket state

Importance medium; confidence high.

| State | Entry condition | Visible text |
|---|---|---|
| Connecting | No initial snapshot yet | `Connecting…` |
| Live | Stream open, recent heartbeat, rendered revision is current | `Live · updated 3s ago` |
| Reconnecting | `readyState === CONNECTING` after being live | `Reconnecting… · showing revision 42 from 2:14 PM` |
| Stale/delayed | No heartbeat or successful check for about three heartbeats, or a revision unapplied too long | `Updates delayed · last checked 1m ago` |
| Ended | Run explicitly ended | `Run ended · final board` |

- An open stream with a failed fragment request is not live; a `304` counts as a successful check.
- Show last successful check separately from last content change ("no changes for 12 minutes").
- Keep the last good board visible while reconnecting.
- Text and shape as well as colour; a pulsing green dot alone fails.
- State label in an initial `role="status" aria-live="polite" aria-atomic="true"` region; announce
  transitions only; the relative age sits outside it, with `<time datetime>`
  ([W3C SC 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)).
- Respect `prefers-reduced-motion` for pulses and spinners.

Per-player age and 10-second staleness exist (`server/server.py:248-249`, `server/server.py:2283-2291`),
but no top-level snapshot time or revision; add both.

### 6. Notifications: in-page first, then opt-in system notifications, then Web Push for followers

Importance medium; confidence high.

Fix the event model first. Events have second-resolution timestamps and no ID
(`server/server.py:1592-1599`). A new pair is logged twice (`server/server.py:1988-1991`); a faint and
the partner's forced death are separate (`server/server.py:1790-1792`, `server/server.py:2013-2015`);
badge masks are overwritten on tick with no badge-earned event (`server/server.py:1850-1856`).
Canonical envelope:

```json
{
  "event_id": "opaque-unique-id",
  "run_id": "run-id",
  "revision": 123,
  "kind": "pair_death | link_formed | badge_earned | run_ended",
  "occurred_at": "2026-09-24T14:32:10.123Z",
  "payload": {}
}
```

One pair death produces one notification.

Channel ranking:

1. **In-page toast plus persistent event log (default).** No permission or service worker; polite
   announcements; dismiss control; pause dismissal on hover or focus; keep the event in the log
   ([WAI-ARIA Alert Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/alert/)).
2. **Browser Notifications (opt-in).** HTTPS and permission from a user gesture
   ([MDN `requestPermission()`](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static));
   use a service worker's `showNotification()` rather than `new Notification()` on mobile
   ([MDN Notification constructor](https://developer.mozilla.org/en-US/docs/Web/API/Notification/Notification)).
   For a backgrounded open page.
3. **Web Push (followers only).** For closed pages; needs a service worker, stored subscription,
   VAPID, encrypted payload, one push request per subscriber; subscription endpoints are secrets
   ([MDN Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API),
   [RFC 8292](https://datatracker.ietf.org/rfc/rfc8292), [RFC 8030](https://datatracker.ietf.org/rfc/rfc8030)).
   iOS and iPadOS support Home Screen web apps from 16.4, not ordinary Safari tabs
   ([Apple web-push documentation](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers),
   [WebKit iOS announcement](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)).

Do not over-notify: in-page shows all four kinds; push defaults to pair death and run end, with
link and badge optional; aggregate bursts ("3 Soul Links died"); dedupe by `event_id`; never replay
on reconnect; one tag per run; a visible "Following this run" control and settings; never prompt on
page load
([NN/g: Five Mistakes in Push Notifications](https://www.nngroup.com/articles/push-notification/),
[NN/g notification guidance](https://www.nngroup.com/articles/smart-home-notifications/)). At 10
push-worthy events an hour, 10/100/1,000 followers means 100/1,000/10,000 push POSTs.

## Recommendations

**P0**

1. A spectator-only public origin. Manager, TCP, debug, mutation and ROM endpoints stay private.
   Bind locally and publish through an outbound-only managed tunnel. Video, if any, goes to managed
   ingest.
2. Make `/api/events` a real revision stream: opaque `run_instance:revision` in SSE `id:` and data;
   advertise it on connect; honour `Last-Event-ID`; a named 15-second heartbeat; publish only after
   a public-projection change, coalesced.
3. Dedicated board-fragment endpoints with ETags, reusing the Manager fragment shape
   (`server/manager.py:798-804`) and adding a run-server route instead of polling `/`. Check
   `If-None-Match` before building status. `Cache-Control: no-cache`.

**P1**

4. One native `EventSource` plus `htmx.ajax()`; do not close on transient errors; skip GETs when
   current; conditional polling as fallback; catch up on `visibilitychange` and `online`.
5. Change the server at the right points: `_notify_sse()` (`server/server.py:1057-1074`), the
   unconditional publish (`server/server.py:1353-1354`), `handle_sse()` (`server/server.py:1093-1157`),
   `Last-Event-ID` forwarding (`server/manager.py:1502-1529`), the polling attributes
   (`server/templates/_board.html:69`).
6. The accessible live/stale indicator and a top-level `generated_at`.
7. Canonical public moment events; toasts and log first.

**P2**

8. Opt-in browser notifications, then Web Push only for "Follow this run".
9. Load-test the real public path at 10, 100 and 1,000 clients, including reconnects, dropped
   Wi-Fi, server restart, stale detection and `Last-Event-ID`; set admission and load-shedding
   policy first.

## Where the report expects disagreement

- "WebSockets because SSE has a connection limit": rejected.
- "Keep 2 s polling": fine at low activity or as fallback; use 5-10 s conditional polling when SSE
  is unavailable.
- "A custom relay now": too early for board data.
- "A reverse proxy is enough because the board is public": the Manager is not public-only.
- "Web Push now": premature.
- "Six connections is an HTTP/1.1 rule": incorrect.

## Unverified and open

- **Validator open item:** the channel ranking was truncated in the copy the validator read. The
  ranking above comes from the full retained reply (`magi mail --task cx-40be13ca`) and was not
  independently checked.
- Compressed size and render time of `_board.html` early, mid and late in a run.
- The real spectator-visible revision rate, especially during battle HP updates and companion ghost
  traffic.
- aiohttp memory, CPU, handles and reconnect behaviour at 10/100/1,000 SSE clients on a Windows host.
- Whether the chosen tunnel or CDN buffers, compresses or times out SSE.
- Edge connection limits and costs; video feeds, bitrate, retention and audience geography.
- Push-service quotas and pricing.
- The final public privacy policy (names, identities, exact times, history).
- No load test was run.
- The managed-tunnel model here assumes the public page is served from the host's own machine.
  `landing-ia.md` proposes a one-way publish to a separate public host. See the README.

## Validation

15 accepted, 1 open. A Sonnet validator confirmed 9 repo claims (SSE is ping-only with no `id:`; the
docstring promises a status event never sent; the proxy drops `Last-Event-ID`; the bridge closes
`EventSource` on error; events have no id; a link is logged twice) and 6 external claims (WHATWG
`Last-Event-ID`, htmx-ext-sse 2.2.4 with idiomorph, RFC 9112 §9.4, Cloudflare's 125 s timeout,
Stream at $1 per 1,000 minutes, iOS 16.4 home-screen-only push). Open: the channel ranking was
truncated in the reply.
