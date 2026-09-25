# Accounts, identity and partner invites

Source: OMP research report `cx-31d45b60` (SECOND_OPINION, read-only, repo at master a9bdce38).
Scope: UI and UX only, designed for phase 1 while keeping phase 2 possible.

## Summary

Phase 1 does not need accounts. Publish a sanitized, read-only spectator projection behind
separate capabilities: an unguessable viewer link for unlisted sharing, a distinct host-only
secret or session for management, and a single-use partner invite bound to Player B. Add a
claimable account layer in phase 2: Discord as the optional primary identity, Google or email
magic link as fallback. Twitch is a channel connection, not the account system. Passkeys come
later as an upgrade.

The report's own strongest doubt: if phase 1 runs live, centrally hosted, writable runs rather
than spectator snapshots, a host secret is a bearer credential with weak recovery, audit, abuse
handling and data-request support, and accounts may be needed sooner.

## Key findings

### 1. The current web surface cannot be made public by adding a login page

Importance critical; confidence high.

- Run IDs are timestamps, `run_YYYYMMDD_HHMMSS`: `server/manager.py:895-902`.
- Start, stop, archive, delete, cartridge, ROM and launcher handlers authorize by run ID alone:
  `server/manager.py:936-1001`, `1003-1025`.
- Those routes have no auth or session middleware: `server/manager.py:1698-1713`.
- The Manager binds `0.0.0.0` by default: `server/manager.py:1805-1810`.
- CSRF protection rejects cross-origin browser mutations but does not establish who owns a run:
  `server/http_safety.py:1-5`, `41-55`.
- The game identity lock is a save identity (trainer name and OT ID), not a web account:
  `server/state.py:202-206`, `995-1029`, `3275-3277`.

The status payload is too rich for spectators: trainer names (`server/server.py:2293-2307`), PC
boxes and party (`server/server.py:2301-2304`), raw mon keys and nicknames in links and killfeed
(`server/server.py:2339-2349`, `2388-2406`), identity errors and capability data
(`server/server.py:2305-2307`). `/api/status` is a normal GET route (`server/server.py:4734-4738`)
and the Manager proxies it (`server/manager.py:1640-1663`). Build a separate public projection.

### 2. Capabilities are the phase-1 primitive; accounts are a later ownership layer

Importance high; confidence high.

| Property | Share link + host secret | Real account |
|---|---|---|
| Time to publish/view | Best | Worse; provider consent and recovery |
| Spectator access | Excellent | No benefit |
| Host ownership | Recovery code/secret only | Durable identity |
| Partner joining | Invite link/session | Invite plus account |
| Revocation | Rotate/revoke capabilities | Revoke sessions/connections |
| Audit trail | Weak without extra work | Stronger |
| Moderation and abuse response | Weak | Better |
| Provider lock-in | None | Discord/Google/etc. dependency |
| Phase-2 migration | Easy to claim later | Native |

Archipelago is the closest comparable: create a room, copy its URL, send it to friends
([Archipelago setup guide](https://archipelago.gg/tutorial/Archipelago/setup_en)); anonymous
session UUID without login ([`WebHostLib/session.py`](https://raw.githubusercontent.com/ArchipelagoMW/Archipelago/main/WebHostLib/session.py));
rooms with UUID IDs and an owner UUID ([`WebHostLib/models.py`](https://raw.githubusercontent.com/ArchipelagoMW/Archipelago/main/WebHostLib/models.py));
separate public room route and owner-only console route ([`WebHostLib/misc.py`](https://raw.githubusercontent.com/ArchipelagoMW/Archipelago/main/WebHostLib/misc.py)).
Its weakness: clearing cookies loses console access.

Four distinct capabilities:

1. **Viewer**: read-only run access.
2. **Host**: visibility, rules, invites, deletion.
3. **Partner invite**: request or claim one specific slot.
4. **Launcher/connection lease**: lets one game client use a slot.

The host capability is never the viewer URL. Store only a hash of high-entropy tokens; rotate and
revoke independently; exchange a bootstrap secret for an `HttpOnly` session; keep the host secret
out of query strings, share payloads, QR codes and page metadata. A recovery code is the
accountless "forgot password", not authorization.

Pastebin's API gives vocabulary, not security: `0=public`, `1=unlisted`, `2=private`
([Pastebin API documentation](https://pastebin.com/doc_api)). "Unlisted" means not discoverable,
not private; a forwarded link still grants access.

### 3. Sign-in ranking for phase 2

Confidence high on provider behaviour, medium on audience ranking (no user research).

1. **Discord OAuth, optional primary.** Login scope `identify` only; `email` only for recovery;
   `guilds` only when choosing a server; `bot` only in a separate install flow; `guilds.join`
   only to add a user to a guild the bot is already in. Use `state`.
   [Discord OAuth2](https://docs.discord.com/developers/topics/oauth2),
   [Discord Activity guide](https://docs.discord.com/developers/activities/building-an-activity).
   Discord-first is an inference from the audience.
2. **Google OIDC, broad fallback.** `openid`; `profile` only for name/avatar; `email` only for
   recovery. `state`, `nonce`, exact redirect, ID-token validation.
   [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).
   Hosted button returns a signed ID token:
   https://developers.google.com/identity/gsi/web/guides/display-button (the report's link text
   here was garbled; the URL is as given). Verification may apply:
   [Google OAuth verification](https://support.google.com/cloud/answer/13463073),
   [Google scope guidance](https://developers.google.com/identity/protocols/oauth2/scopes).
3. **Email magic link or OTP, recovery and non-OAuth fallback.** Short expiry, single use, limited
   attempts, rate limits, enumeration-resistant responses.
   [Auth0 passwordless email](https://auth0.com/docs/authenticate/passwordless/authentication-methods/email-otp),
   [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).
4. **Passkeys, phase-2 upgrade.** After an account exists, or as step-up for destructive actions;
   never the only recovery path. [W3C WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/),
   [FIDO Passkeys](https://fidoalliance.org/passkeys/).
5. **Twitch, connection only.** OIDC supports `openid`
   ([Twitch OIDC](https://dev.twitch.tv/docs/authentication/getting-tokens-oidc/));
   `user:read:email` is not needed to identify a user
   ([Twitch scopes](https://dev.twitch.tv/docs/authentication/scopes/)). SLink's Twitch bot already
   asks for chat/bot permissions separately (`README.md:193-223`). Use "Connect Twitch" later.

OAuth baseline for every provider: server-side Authorization Code flow, exact redirect URI,
`state` and OIDC `nonce`, PKCE ([RFC 9700](https://www.rfc-editor.org/rfc/rfc9700)), identity keyed
by `(issuer, subject)`, tokens server-side and out of exports, explicit account linking only.

### 4. Partner invite and slot pairing

Confidence high on the technical boundaries, medium on the exact approval UX.

**Host:** `Run settings → Invite partner`; pick `Player B` explicitly; generate a single-use,
expiring invite; show copyable URL, QR of the same URL, native Share where supported, expiry, and
"Anyone with this link can request this slot." Never show the host secret here.

**Invite landing page** (before acceptance, nothing else from the run):

> Someone invited you to join a Pokémon Soul Link run as **Player B**.
> Requesting pairing does not give you host controls. The host will see your requested display
> name and the run will show your game activity according to the run's visibility settings.

**Partner confirms:** clicks `Request to pair as Player B`; picks a display label (no OT ID in the
browser); sees a short confirmation code; confirms role, visibility and that they can leave. State
becomes `pending`, not `paired`.

**Host approves:** sees the request and code (`K4P-72Q`), then Approve or Reject.

```text
vacant → invite issued → requested → paired
                         ↘ expired
                         ↘ rejected
```

A forwarded invite cannot silently take the slot; link previews and crawler GETs must not consume
it. An explicit `One-click join` host option can accept the next requester; default to approval for
private runs.

QR is a desktop-to-phone convenience, not a second factor; encode the invite URL, never the host
secret; show URL text as a fallback; put expiry and revoke beside it; keep invite URLs out of OG
previews, analytics, error trackers and third-party sprite requests.

Web Share is progressive enhancement: `navigator.share()` needs a user gesture and secure context;
check `navigator.canShare()`; support is limited, so always offer `Copy link`
([MDN Web Share API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Share_API)). Do not rely on
Web Share Target, which is experimental and needs an installed PWA
([MDN Web Share Target](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest/Reference/share_target),
[W3C draft](https://w3c.github.io/web-share-target/)).

Slot binding: `(run_id, slot=B, partner_session/lease, invite_id, expiry, revoked_at)`. The TCP
handler trusts the client-declared `player` field and applies save identity checks later
(`server/server.py:1202-1205`, `1233-1326`). A hosted phase-2 flow needs a slot-specific lease or
signed launcher config; trainer name and OT ID stay game admission checks.

### 5. Roles and visibility

Importance critical; confidence high. Roles are independent of Player A/B; a host can be A, B or
neither.

| Capability | Host | Partner | Spectator |
|---|---:|---:|---:|
| View board | Yes | Yes | Only if visibility grants it |
| View raw/debug/OT-ID data | Yes, with warning | Own data only | No |
| Download launcher | Yes | Own slot only | No |
| Invite/revoke partner | Yes | No | No |
| Change rules/visibility | Yes | No | No |
| Export run | Yes | Own data/run subset | No |
| Delete run | Yes | Leave/revoke own pairing | No |
| Manage OBS/Twitch/debug | Yes | No | No |

- **Private:** host, accepted partner, invited spectators only. No listing, search, sitemap or
  preview metadata; `no-store`; no third-party assets that receive the URL.
- **Unlisted:** anyone with the viewer capability; `noindex`; not listed; rotatable.
- **Public:** stable readable URL, optionally listed, explicit publish confirmation.

Default: **private or unlisted until the host explicitly publishes.** Default-hidden or never
public: OT ID, raw mon keys, party/box, sensitive live location, identity errors, logs, launcher
data, and all host, invite and OAuth secrets.

### 6. Privacy and data screens

Importance critical; confidence high for product controls; legal applicability depends on
jurisdiction.

Persisted data exceeds what spectators need: mon keys, nicknames, species, levels, stats, pending
captures (`server/state.py:139-159`); trainer names, OT IDs, pending memorials, bonus keys, run
metadata (`server/state.py:163-206`, `3228-3290`); memorial records, event logs, generated
cartridges, randomizer seeds, server logs.

Minimum screens:

- **Run access** (host): visibility selector, exact public preview, viewer link (copy, Share, QR,
  rotate), partner invite list, host key (reveal once, rotate, revoke sessions), recovery code.
- **Privacy choices** (partner): display label or alias, hide trainer name and nicknames, leave
  pairing, export own data.
- **Your data**: `public-snapshot.json` versus a role-scoped private export; never export secrets,
  tokens or launcher credentials; redact the other participant's data.
  [ICO Right of Access guidance](https://ico.org.uk/media2/5txar1ff/right-of-access.pdf).
- **Delete**: separate Unpublish, Leave run, Delete run and Delete account. The local delete handler
  removes the run directory (`server/manager.py:982-1001`); a public service also needs an
  inventory of backups, logs, CDN copies and processors.
  [ICO Right to Erasure](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/).

The report includes a short layered privacy-notice draft (independent fan project; what is
processed; private by default; unlisted means link holders; aliases; provider ID only on sign-in;
retention and processor placeholders; rights contact). Checklists:
[ICO Right to be Informed](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-be-informed/),
[ICO Data Protection by Design](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/accountability-and-governance/guide-to-accountability-and-governance/data-protection-by-design-and-by-default/).
The report states this is a product baseline, not a legal conclusion.

## Recommendations

**P0, before any public spectator page**

1. A separate spectator projection, enforced server-side; not the Manager.
2. Explicit, separate viewer, host, invite and game-connection capabilities; hashed at rest;
   rotatable; never in URLs, QR codes, share payloads, analytics or logs. Keep a nullable
   `owner_subject` so phase-2 accounts can claim anonymous runs.
3. Private or unlisted by default; explicit publish confirmation with a "what spectators see"
   preview; aliases by default; `noindex` and no metadata for private and unlisted pages.
4. Host access and recovery screens: session, one-time recovery code, session list, link rotation,
   invite list, export and delete with clear consequences.
5. Partner pairing: single-use expiring invite, disclosure screen, confirmation code, host approval
   by default, atomic slot binding, separate launcher lease, leave and revoke.
6. Privacy notice at collection and publish time; public and private exports; unpublish, leave,
   delete-run, delete-account; a retention schedule covering backups, logs, ROM copies and caches.

**P1**

7. Share UX: `canShare()` detection, `share()` only on click, copy fallback, QR of the same URL.
8. Public runs may have previews; unlisted and private must not leak title, description or tokened
   URLs. Set a `Referrer-Policy` suited to capability URLs.
9. Partner privacy: alias mode, leave, own-data export, a clear "who sees what".

**P2, hosted accounts**

10. Discord OAuth first, optional, `identify` only.
11. Google OIDC or email magic link as fallback.
12. Passkeys after account bootstrap, with multiple credentials and recovery.
13. Twitch as a separate connection.
14. Claim flow: sign in, enter the recovery code, become `owner_subject`; existing links, partner
    sessions and history stay valid.

## Where the report expects disagreement

- "Add Discord accounts before launch": no, for a spectator-first phase 1.
- "An unguessable link is private": no; it is a capability URL.
- "Twitch OAuth as the account system": no; keep broadcaster scopes separate from ownership.
- "Expose the status API and hide controls": strongly no.
- "The invite auto-consumes the slot": only in an explicit one-click mode.

## Unverified and open

- Audience: no data shows Discord is the majority provider.
- Deployment shape: static snapshots, a proxy of live run servers, or writable hosted runs. The last
  strengthens the case for accounts.
- Legal: no jurisdiction, operator identity, hosting location or child-user assessment supplied.
- Provider app verification, domain ownership, quotas and policy for the real deployment.
- Web Share and QR behaviour on target devices; copy-link is the guaranteed path.
- Whether a given OT ID, nickname or memorial entry is personal data depends on context; treat
  linkable identifiers as personal.
- Static inspection only; no server started.
- Editor's note, not from the report: the invite, slot-lease and host-secret flows assume a hosted
  service. While players self-host the game side, the phase-1 subset is the viewer capability,
  publish/unpublish and the privacy screens; the rest waits for phase 2.

## Validation

6/6 accepted. A Sonnet validator confirmed timestamp run IDs, no auth middleware, the `0.0.0.0`
bind, CSRF not being authorization, the client-declared TCP player, and Archipelago's cookie-owner
room model, plus Discord's `identify` scope, RFC 9700 and Pastebin's visibility levels. It noted
one garbled markdown link, not a fabrication.
