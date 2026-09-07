# Shared staged native page publisher

`staged_panel.new(options)` takes read/write/available/paint callbacks, positive
integer page_rows and a1–255lease_frames bound. It never advances frames, touches
fixed addresses, chooses a glyph encoding, connects a socket or grants authority.

`stage(rows)` requires an available awaiting endpoint. It validates the requested
page and count, publishes odd generation before painting, and sets the next even
generation before STAGED only if availability, state, page and generation remain
unchanged. A paint exception retains odd/incomplete publication. The binding's
native timeout/closure policy owns recovery. More than255pages is refused.

`maintain(connected)` refreshes or clears the lease only for the same generation
this object successfully published and an available, nonclosed endpoint. A new
publisher, changed generation or closed/unavailable endpoint cannot extend it.
The caller must derive connected/available from its current physical/session
authority; these arguments are not themselves proof of that authority.

The RBY binding is the first real caller. Its native code implements transfer
completion, acknowledgement, input and timeout semantics; other generations must
qualify their own endpoint before reusing this publisher. Eight portable tests
cover order, wrap, interrupted publication, ownership and closed/refused endpoints.
