# Shared runtime validation and publication

Committed responses are written to the transport before presentation callbacks.
Publication reads one detached projection and derives both the rule view and
status from it. The optional generation `_presentation_state()` hook is used
only by presentation; admission and execution continue to use `state()`.
Presentation errors cannot roll back or duplicate a committed event.

Component record reads still query their current history bounds, capability
marker and snapshot row. The journal reuses successful canonical/hash validation
only when the freshly read `(revision, body, digest)` tuple is identical. Changing
even the snapshot body at the same revision invalidates that reuse. Record
bodies and their digests are checked on every read; decoded snapshot state and
execution authority are not cached.

`VerifiedContentCache` separately supports bounded reuse of deterministic JSON
validators. A caller supplies fresh external dependencies as part of its key;
failed validations are never cached and results are freshly decoded. See
`shared-verified-content-cache.md` for its contract. Neither helper changes
watchdogs, protocol deadlines, journal durability or command ordering.

`lua/command_service_router.lua` composes generation-selected command services.
Exactly one service may claim a body. The pending request retains its response
route, and revocation reaches every service even if one revocation fails. The
outer runtime still owns all host, frame and write permission checks.

Tests cover response-before-presentation ordering and callback failure, changed
snapshot/record bytes after a cached validation, detached outputs, invalidation
and bounded cache eviction, and command routing/revocation. These shared tests
do not qualify a generation's physical execution or release candidate.
