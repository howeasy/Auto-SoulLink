# Shared hook lifecycle and Game Boy binding

`lua/hook_registry.lua` owns hook registration, handles, bounded queues and cleanup.
`lua/gb_hook_binding.lua` supplies explicit Game Boy ROM0/ROMX addressing, register
and domain binding. Neither module owns game event classification or qualification.
This extraction has SOURCE/MODEL controls; Gen 1 and Gen 2 physical hook lanes remain open.

## Registry contract

Load one registry module instance for every group of binders sharing a hook backend.
Loading another independent copy creates another ownership scope, so composition must
reuse the instance rather than relying on separate `dofile` calls to share owners.

`Registry.new(options)` returns a service, or `nil, error, failed_service`. Options:

- `owner`: explicit namespace consisting of letters, digits, underscore, dot or hyphen.
- `max_pending`: explicit positive finite integer queue capacity.
- `sites`: nonempty dense array of descriptors with unique string `id` values.
- `validate(site)`: returns a prepared descriptor preserving the id, or raises.
- `register(prepared, callback, owned_name)`: returns the backend handle.
- `unregister(handle)`: returns anything except `false` on success; may raise on failure.
- `valid_handle(handle)`: total, side-effect-free predicate that returns `true` for a handle.
- `capture(prepared, ...)`: returns an event table, or `nil` to drop an irrelevant hit.
- `on_event(event)`: optional synchronous handler, called after a snapshot is queued.
- `name_for_site(prepared)`: optional naming policy; otherwise `owner .. ':' .. id`.

The registry reserves the namespace, validates **all** descriptors and hook names,
then registers. Descriptors are copied before external validation, registration and
capture. Names and accepted handles must be unique within the shared instance.
The backend registration operation must either return its handle or fail without
creating an unreported registration: no registry can clean a handle never returned.
Registration-time callbacks are ignored until the entire set is installed.

If the backend returns a handle this registry instance already owns, the registration
is refused and that backend registration is left unowned: it is neither unregistered
nor tracked, because unregistering the handle would remove the other owner's hook.
The refusing service fails closed, so the callback bound to it stays inert. Such a
duplicate is a backend fault; the error names the site.

On registration failure, cleanup attempts every accepted owned handle in reverse
order. No foreign handle is unregistered. Cleanup failure keeps the namespace and
names reserved, leaves callbacks inert, and is reported on `failed_service:status()`.
The caller may retry `failed_service:close()` once the backend can unregister.

Methods:

- `service:peek()` returns a detached copy of the queued snapshots in arrival order,
  for observers such as test tees. Mutating it never changes the queue.
- `service:drain()` returns queued snapshots in arrival order and starts an empty queue.
  Draining never resets an error latch.
- `service:status()` returns `failed`, `handler_error`, `pending`, `closed`,
  `registered` and `cleanup_errors`. Registered is the total successfully owned count.
- `service:close()` disables callbacks, attempts all remaining unregister operations,
  and returns whether cleanup completed. It is safe to retry and does not discard
  already queued evidence. Ownership is released only after all handles are removed.

A capture exception, invalid event or overflow latches `failed`, which stops subsequent
callbacks. A synchronous handler exception is contained: the event is already queued,
`handler_error` records the latest handler failure, and later callbacks keep capturing
and queuing. `handler_error` is a status field, never a kill switch. The queued event
snapshot is separate from the handler's mutable argument. Cleanup or callback errors
never imply rollback of external effects already performed by a backend or handler.

## GB binding contract

`GB.new(io, config)` requires IO callbacks `read_u8`, `read_range`, `register`,
`framecount`, `on_bus_exec` and `unregister`. Every config value is explicit:
`bus_domain`, `rom_domain`, `bank_domain`, `bank_address`, `pc_register`, `sp_register`.

`binding:validate(site)` accepts `id`, `bank`, `address`, `capture_offset`,
`rom_offset`, `expected_hex` plus opaque binder metadata. It verifies GB bank/window
consistency, the flat ROM offset, the entire ROM anchor and that the hook PC falls
inside that anchor. This binding observes a single bank-shadow byte and refuses
bank selectors above 255. The returned descriptor includes `pc` and parsed `expected` bytes.

`binding:context(prepared, accept)` drops a different switchable-bank shadow value.
At a matching bank it then runs the optional binder predicate `accept()`; a false
result drops the hit before any PC or byte check, so a filtered hit cannot latch a
failure. A throwing `accept` is also a dropped hit: that one callback yields no event,
`binding:status()` records `accept_errors` (a count) and `accept_error` (the latest
message, prefixed with the site id), and later hits keep running. It is never a latch,
the same rule as a handler error. For an accepted hit it requires exact PC, rechecks the anchor through the bus domain, and
returns `{pc, bank, sp, frame}`. Missing bank/SP/frame or incorrect PC/bytes raises.
These are explicit shadow/byte checks, not a claim that the emulator's actual mapping,
callback timing or source-only engine site has been physically qualified. A binder
requiring stronger mapping/stack proofs must supply and check that separate authority.

`binding:register`, `:unregister` and `:valid_handle` adapt the IO. GB registration
accepts positive integer handles or nonempty strings and refuses zero GUID variants.

## Gen 1 binding

`Signals.bind({registry=Registry, gb_binding=GB, owner='SLink-gen1'})` returns a
factory with the existing `new(profile, sites, io, on_fire)` interface. Its event
filters and snapshots remain in `lua/gen1/signals.lua`; each kind's filter is passed as
`accept`, restoring master's order (bank, filter, then PC and bytes); it explicitly supplies
`System Bus`, `ROM`, `PC`, `SP` and `profile.ram.hLoadedROMBank` to the GB binding.
The existing `SLink-gen1-<kind>` hook names remain unchanged through its naming policy.
`lua/gen1/client.lua` logs each in-hook handler fault (`signal handler <kind>: ...`) and
re-raises it, so the fault is visible on the console and in `status().handler_error`.
The Gen 1 duo save-witness tee counts new queue entries through `peek()`.

Entry owns loading and injecting both dependencies and the release manifest owns
shipping them. Constructor failure preserves `factory.failed_service` for explicit
cleanup retry. The historical signal receipt tests remain MODEL expectations from
older physical runs; passing them does not qualify this rebind physically.
