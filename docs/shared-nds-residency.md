# Shared NDS overlay residency (HGSS and Gen 5) and the PK4/PK5 cipher core

Status: NDS-3 deliverable (shared NDS companion stack), 2026-10-02, revised after review. Code:
`lua/nds/residency_contract.lua` (residency) and `lua/nds/pkm45_crypto.lua` with its Python oracle
`tools/nds_pkm45.py` (cipher); tests: `tests/unit/test_nds_residency_contract.py`,
`tests/unit/test_nds_pkm45.py`. Both Lua modules are pure and hold no per-game geometry or field maps: each
lane implements a strategy for its own table, and both lanes arm hooks through the same helper so the same
safety property holds in both.

## Why a contract

Both generations keep a table of loaded overlays and both let a hook site live in overlay code. The tables
differ, the pitfalls do not:

- the entry becomes **active before the load is known to have succeeded**; a failed load leaves the entry
  active (no rollback), so the flag can **lead** the real code (Gen 5: FILE, `rom_overlay_loader.md`);
- on unload `active` is cleared but the **id stays**, so an id match alone is meaningless;
- aliased overlays (Gen 5 B2W2 ov11 / ov12 at `0x02150400`, any pair sharing RAM) can put other bytes where a
  site was registered.

The Gen 4 `NDS.resident` (`lua/nds/hook_binding.lua`, Gen 4 branch) hard-asserts the HGSS geometry
(`regions == 3`, `per_region == 8`, `entry_size == 8`). That cannot serve Gen 5. The Gen 4 coordinator replaces
the assert by injecting a strategy that passes `assert_strategy`.

## The two reference geometries (what each lane implements)

| | HGSS / hg-engine (Gen 4 lane) | Gen 5 BW / B2W2 (Gen 5 lane) |
|---|---|---|
| Table | static `.bss` array (`sOverlayRegions`), 3 regions x 8 entries x 8 B | **heap block** `P` reached through a static pointer global |
| Header | none | `u8` counts at `P+0 / +1 / +2`; `u32` list pointers at `P+4 / +8 / +0xC`; entries start at `P+0x10` |
| Per-region counts | 8 / 8 / 8 | BW **16 / 4 / 4**; B2W2 **20 / 4 / 4** |
| Entry | `{u32 id; u32 active}` | `{u32 id; u32 active}`; region-0 entries are **inline** from `P+0x10`, regions 1 and 2 are found through their list pointers |
| Address | fixed (pack constant) | read the pointer global first; `0` means "manager not created yet" (no entries) |
| What can move | nothing | the block itself (pointer changes) as well as its contents |
| Residency | main region (region 0) | main region (list 0) |

A Gen 5 reader must read the counts, then **follow** `u32[P+4]` (not assume `P`), or it produces phantom
entries out of the header words; the test fake reads exactly this layout and asserts entry 0 is the first
real `{id, active}` pair. The header layout is the lane's FILE fact to confirm against RAM; the contract does
not depend on it.

Rules both share (FILE for Gen 5, `rom_overlay_loader.md`; Gen 4 per its own research): the first free slot is
taken, `active = 1; id = ID` is written, then the code is copied; unload clears `active` only.

The fakes in the test file are the executable form of this table. Entry field order inside the 8 bytes is the
lane's business (the fakes use `id` at +0, `active` at +4). **Caution:** the geometries in this table and in the fakes
(HGSS 3 x 8 x 8 B, the HGSS entry field order, the Gen 5 header and counts) are carried from research, not
measured on a ROM or emulator. They are an unmeasured fixture assumption: the fakes prove the contract, not the games.

## The strategy

A plain table of plain functions (no `self`):

```
entries(read)  -> array of { id = integer, active = boolean, region = integer }
                  every slot of every region, stale slots included (active = false)
resident(id)   -> boolean   true iff the MAIN region (region 0) shows `id` active. A HINT, see the stale-flag rule
epoch()        -> integer   changes whenever the table could have changed; equal epochs = nothing happened between
geometry()     -> optional, diagnostics only
```

- `read` is the caller's memory reader, forwarded to `entries`; the contract never calls it. `resident` and
  `epoch` use the strategy's own bound reader.
- **Residency is region 0 only.** An active entry for the same id in region 1 or 2 does not make `resident`
  true and does not fail validation of a correct region-0 strategy; a strategy that counts other regions is
  rejected by `validate_strategy(s, read)` as disagreeing with its own entries.
- **`epoch()` cost and coverage (Gen 4 requirement).** It sits on the arming path, so it is at most a few
  reads: a heap/table pointer, a loader-call counter and a boot/save **generation counter**, never a hash of
  every slot. It must change on a loader call, on relocation of the table, and on soft reset and
  Continue / New Game **even when the heap hands back the same addresses with the same-looking words** (the
  words cannot tell; only the generation counter can). It may over-report change (that only costs a
  re-snapshot). The test fakes read 2 (HGSS) and 3 (Gen 5) words and prove all of this, including the
  same-addresses reset trap.
- `assert_strategy(s [, read])` raises on a malformed strategy. Without `read` it checks shape only; with
  `read` it exercises the strategy: every entry well-formed, `epoch()` an integer and stable with no table
  change, `resident(id)` a boolean that is true exactly for ids with an active region-0 entry, and false for an
  unknown id. `validate_strategy` is the non-raising twin (`true | false, reason`).
- `snapshot(s, read)` returns `{ epoch, entries }`, epoch taken **first**, so a change during the read can only
  make the view look stale. It forwards `read` into `assert_strategy`, so the behavioural validation also runs
  on the arming path, not only at construction.

## The stale-flag rule (mandatory)

> A residency flag alone never arms or fires a hook. The site's expected bytes are re-read at arm time and at
> every fire, and the epoch the decision was made on must still be current.

The binder supplies, per site, `site_confirmed(site)`: re-read the site's registration pin / fire word from
memory **now** and return exactly `true` if it matches. Anything else (false, nil, a truthy non-boolean, an
error) is a refusal. The strategy cannot supply this: it knows the table, not the code bytes. Re-reading the
4-byte fire word on every fire is fine.

**Physical counterexample (Gen 4 coordinator, 2026-10-02, HeartGold overlay 12, run `C:/slink/g4/g1-settle-HG-1144-serial`).**
The overlay table went active at frame 7325, but the async copy only landed 10-11 frames later (the site pins read ready
at +10/+11). A strategy that trusts the flag would have armed a hook on bytes that were not there yet. The pin check at
arm and fire is therefore load-bearing, not belt and braces. This is a Gen 4 HGSS measurement; Gen 5's loader marks an
entry active before the load is known to have succeeded (static, FILE) and has no physical measurement yet.

Helpers (all return `true` or `false, reason`; they never raise on bad input and never arm on bad input):

- `may_arm(strategy, site, site_confirmed, epoch)`
  - `site = { id = non-empty string, overlay_id = nil (static ARM9) | integer }`.
  - Overlay site: `epoch` is required and must equal `strategy.epoch()`; `strategy.resident(overlay_id)` must be
    true; then the pin is re-read. Static site: no residency or epoch, the pin is still re-read.
- `may_fire(strategy, site, site_confirmed)` at fire time: overlay must still be resident (quiet refusal, another
  overlay may share the RAM), then the pin is re-read. A `pin_mismatch` while resident is a **fault** to
  surface, never a silent drop (the Gen 4 binder latches it).

Refusal reasons: `bad_strategy`, `bad_site`, `no_pin_check`, `epoch_required`, `stale_epoch`, `not_resident`,
`pin_mismatch`, `pin_error`.

Worked failure the rule exists for: ov36 load starts, the entry is active, the SDK call fails (or has not
finished). `resident(36)` is true, the registration bytes are not the overlay's. `may_arm` returns
`false, "pin_mismatch"`; once the code is really copied it returns `true`. A rebuilt table after an
unload/reload shows the same `resident` answer but a different epoch: a decision taken on the old snapshot is
`stale_epoch` and must be re-taken.

### How the binder must use the checks (three rules)

1. **A refusal is a visible fault, never "no site", and arming is retried.** A `may_arm` refusal (for example
   `not_resident` because the overlay has not loaded yet, or `pin_mismatch` on a flag that leads its load) must
   be latched or counted in the phase layer so the owner can see it; it must not be handled like a site that
   does not exist. Because the Gen 4 hook registry is constructor-only per phase, the binder re-attempts arming
   on the next phase / poll, with a fresh `snapshot`, until the pin matches or the phase ends.
2. **`accept` is not part of the contract.** The caller's own `accept` filter (a binder-side drop that never
   latches) is evaluated **before** `may_fire`. The contract predicate is only residency plus the pin / fire-word
   check, so a benign `accept` rejection can never be turned into a latched `pin_mismatch`.
3. **The checks are pure and own no state.** `may_arm`, `may_fire`, `snapshot` and the validators hold no state,
   write nothing to the strategy, the site or any shared table, and consume nothing. The Gen 4 D7 single-shot
   lease (`battle_write` renewed, `pre_pump` clears, the callback consumes) remains the **only** state; a check
   may be repeated any number of times with the same answer for the same memory (a test asserts this, including
   that the module, strategy, site, RAM and `_G` are untouched).

## Wiring (done by the owning lanes, not here)

- Gen 4 lane: build the HGSS strategy from the pack `overlay_table` (address, regions, per_region, entry_size,
  `id_off`, `active_off`), keep its pin check as `site_confirmed`, replace the geometry assert in
  `NDS.resident` with the injected strategy. **The binder calls `assert_strategy(s, read)` once at
  construction**, then routes `register()` through `may_arm` (with a `snapshot` taken per arming attempt, which
  re-runs the behavioural check) and the fire path through `may_fire`.
- Gen 5 lane: build the heap-block strategy (pointer global, counts, list pointers, `{id, active}` entries), call
  `assert_strategy(s, read)` at construction, same hook.

## Companion: the PK4/PK5 cipher core and the flags word

`lua/nds/pkm45_crypto.lua` is the shared 0x88-byte stored-record cipher (party length is a parameter: Gen 4
`0xEC`, Gen 5 `0xDC`). Its input contract is a string or a dense 1-based byte array; the identity accessors read
PID/TID/SID/OTID from the plain, unshuffled record and nothing game-specific (`0x41/0x42/0x85` stay in the
game packs).

The flags word at `+0x04` has two independent meanings the module keeps apart:

- **bit 2 (bad egg)** is a legitimate stored state: reported as `info.bad_egg`, preserved by encrypt, never an
  error, never repaired.
- **bits 0-1 are the game's own "decrypted" marker.** FILE (`docs/gen5/research/rom_code_anchors.md:66` and
  `:214`): `Decrypt` sets bits 0-1 and XORs body and tail **without reordering the blocks** (they stay
  shuffled); `Encrypt` tests bit 0, clears bits 0-1, recomputes the checksum and re-XORs. **Whether LIVE RAM
  party records are at rest plaintext or ciphertext is OPEN (needs RAM)**, so a reader must key on the flag.
  Default: a record carrying the marker is refused (`locked`). `opts.allow_decrypted = true` (the second /
  third argument of `decrypt_*`) opts in: body and tail are taken as already XOR-plain, only un-shuffled,
  `info.decrypted = true`, and the stored checksum is **reported** as `info.checksum_ok`, not enforced (the game
  only recomputes it in `Encrypt`). `encrypt_*` always clears bits 0-1.

## Not verified here

- No emulator run: both residency strategies are tested against fakes over a flat byte map, not against a
  running Black/White or HGSS. The real field order inside the 8-byte entry (HGSS), the pointer-global
  addresses, the Gen 5 heap-block header (u8 counts / u32 list pointers / entries at `P+0x10`, taken from the
  review of the loader, not measured here) and the true behaviour of a failed load on hardware are carried from
  the research docs, not re-measured.
- `epoch()` quality is each lane's; the contract checks only that it is an integer and stable on an unchanged
  table, and the fakes demonstrate the cost and boot-generation requirements; the real counters (loader-call,
  boot/save generation) still have to be located per game.
- The decrypted-at-rest RAM representation (above) and any real Gen 5 PK5 record vector: the Black battery save
  is a never-saved new game, so Gen 5 cipher coverage rests on the Gen 4 vectors plus the cartridge table and
  the LCRNG literal.
