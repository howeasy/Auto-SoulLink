# Staged party grants

`server/party_grant_rules.py:record_exempt_party_grant` records one validated,
clause-exempt grant already present in the player's party. Call it on a detached
`StagedSoulLinkState`, with the player, pairing area, `MonInfo`, and an optional
verified peer `MonInfo` for the same source group.

The generation binding must prove source, exemption, physical presence,
uniqueness and the peer's provenance before calling. This is an internal staged
operation, not a network event or a way for a client to claim an exemption.
Boxed grants, ordinary catches, shiny/bonus policy and physical reconciliation
need their own binding.

The first grant becomes a pending capture and marks the area as waiting for the
other player. A matching second grant forms one live rule link. Conflicting
pending/link state, a peer absent from the party, ended runs and unpublished
commands are refused before mutation. Matching raw keys across different
players are allowed; the generation's identity registry provides durable identity.

The helper queues no retrieval, boxing, sound, dialogue or other game commands.
It does not infer Pokéball credit, change party statistics or create logical
identity IDs. The caller stages those from verified observations and commits
rules, identities, source evidence and both outboxes in one journal transaction.
Generation-owned policy must still decide when ordinary gameplay may run.

Gen1 uses this operation after joining a verified starter call/return with a
later complete inventory. This preserves Yellow/Yellow's valid starter pair
when clauses are enabled, and avoids legacy retrieval commands for Pokémon
that are already in their parties. Other generations must qualify their own
source and exemption policy before selecting the helper.
