-- lua/gen4/companion.lua -- the Gen 4 (HG/SS) companion binder: the title-private beacon
-- block over the shared NDS mailbox reader (lua/nds/mailbox.lua).
--
-- PURE like the shared reader it builds: no emulator API, no globals, no writes, no clock
-- and no retained transaction state. `io` is injected and the caller closes it over the
-- window the ROM and the host actually share; this module names no address and no bus
-- domain, so it cannot silently pick the wrong window.
--
-- DOMAIN (the one fact a caller must get right, and the reason there is no domain argument
-- here). The arena is aliased: the same 4 KiB is reachable at 0x01FFEC00 on the ARM9 CPU
-- and at the ITCM mirror, which is how BizHawk's "Instruction TCM" domain presents it
-- (C2_BEACON_SPEC.md:411-415). The host must read the "Instruction TCM" domain and NEVER
-- the ARM9 bus mirror of the same bytes; probe row `a` exists only to keep the two windows
-- agreeing (lua/tests/probe_gen4_mailbox.lua:8,105). lua/gen4/client.lua:107 holds the
-- platform fact (Client.PLATFORM.bus_domain) and the caller passes that io in here.
--
-- WHAT THIS ADDS over the shared reader. The shared module decodes the six-scalar envelope
-- and hands out raw regions; the 64-byte title-private block at the ABI's
-- SLINK_RESERVED_OFFSET (beacon.h:75-76) is Gen 4's own (D-C2-1, beacon.h:61-73) and it
-- carries the liveness facts the shared reader has no opinion about: cookie, identity,
-- engine-clock delta, generation. This module decodes it and owns the liveness state
-- machine; it owns nothing else.
--
-- THE BLOCK IS UNTRUSTED UNTIL VALID (beacon.h:61-73). It is NOT covered by the
-- witness revision protocol, so its publish order and its coherent-snapshot rule are the
-- title's own: the ROM writes the payload first and magic LAST (beacon.c:195-210), so a
-- host sampling mid-visit can read bytes of two different visits under a header that already
-- validates (magic/version/size are constants). That is exactly why this module takes two
-- copies around a check and refuses when they differ: identical() is the defence, the
-- publish order is not.
--
local Companion = {}

-- LAYOUT. Every number below is an offset or a constant from patch/src/nds/gen4/beacon.h
-- (SLINK_GEN4_TITLE_* and SlinkGen4Title, beacon.h:75-103), never an address. title_offset
-- is DERIVED at run time from the shared reader's own reserved_offset, because beacon.h:75 defines SLINK_GEN4_TITLE_OFFSET as
-- SLINK_RESERVED_OFFSET: deriving it is what stops the two headers from drifting apart.
--
-- CONFIG (base and mailbox are required; the two thresholds are optional):
--   base          the arena base, which the CALLER derives. This module names no address.
--   mailbox       the shared reader's module table (lua/nds/mailbox.lua), injected so this
--                 file has no hidden dofile/require. lua/gen4/entry.lua loads its siblings
--                 by literal path (entry.lua:181) and passes them in the same way.
--   stable_polls  K: consecutive coherent polls agreeing on one (generation, cookie) before
--                 LIVE (C2_BEACON_SPEC.md:517-520). PER TITLE and adapter-owned: the
--                 default here is a fallback for a caller that says nothing and is never
--                 enforced over a value that was given.
--   stall_polls   N: consecutive polls without a delta advance that make the arena stale
--                 (C2_BEACON_SPEC.md:521-522). Also per title, never enforced over a
--                 value that was given.
--
-- CAPABILITIES NEVER GATE ANYTHING. capabilities is ROM-owned and informational
-- (C2_BEACON_SPEC.md:429-452): at C2 the advertised set is 0, so a host that required any
-- capability bit could never come live at all. This module reports caps_shared,
-- reserved_bits and the title-private bits 16..31 passed through untouched, and neither
-- poll() nor step() can read them into a decision -- step() is not even handed the
-- envelope.
--
-- The one 8-hex-digit literal in this file is the title magic, and it is a magic, not an
-- address (beacon.h:78). tests/unit/test_gen4_companion.py asserts it against the value
-- the real header compiles to, so it cannot rot into an address unnoticed.
--
-- headroom_first_field is the start of the declared reserved[36] tail, which "stays zero"
-- (beacon.h SlinkGen4Title.reserved, :95); it is REPORTED and never gated (see below).
local L = {
    title_size = 0x40,        -- SLINK_GEN4_TITLE_SIZE (beacon.h:76)
    title_magic = 0x34474C53, -- SLINK_GEN4_TITLE_MAGIC, "SLG4" little-endian (beacon.h:78)
    title_version = 1,        -- SLINK_GEN4_TITLE_VERSION (beacon.h:79)
    title_cookie_field = 0x08,
    title_identity_field = 0x0C,
    title_delta_field = 0x10,
    title_generation_field = 0x14,
    title_registrations_field = 0x18,
    headroom_first_field = 0x1C,
    abi = 3,                  -- SLINK_ABI_VERSION; the shared reader admits nothing else
}

-- Model numbers, sized for the New Game burst the K rule exists to absorb
-- (C2_BEACON_SPEC.md:517-520). A caller-supplied threshold always wins; see new().
Companion.DEFAULTS = { stable_polls = 3, stall_polls = 2 }

local function uint(v, maximum)
    return type(v) == "number" and v % 1 == 0 and v >= 0 and v <= maximum
end
local function positive(v)
    return uint(v, 0xFFFF) and v >= 1
end
local function plain(t)
    return type(t) == "table" and getmetatable(t) == nil
end
local function copy(t)
    local out = {}
    for k, v in pairs(t) do out[k] = v end
    return out
end

-- Little-endian decode of an ALREADY TAKEN COPY. This deliberately repeats the shared
-- module's private word reader instead of re-reading through `io`: the copy is the thing
-- the coherence claim covers, so decoding must not go back to memory for a second look.
local function word(raw, offset, width)
    local value = 0
    for i = width, 1, -1 do value = value * 256 + raw[offset + i] end
    return value
end

-- Byte-for-byte over the whole block. A partial compare would accept a tear in the tail.
local function identical(a, b, n)
    if #a ~= n or #b ~= n then return false end
    for i = 1, n do
        if a[i] ~= b[i] then return false end
    end
    return true
end

local function headroom_clear(raw)
    -- raw is a 1-indexed copy: byte N of the block is raw[N + 1]
    for i = L.headroom_first_field + 1, L.title_size do
        if raw[i] ~= 0 then return false end
    end
    return true
end

-- The static half of the layout, before it is resolved against the shared reader.
function Companion.layout()
    return copy(L)
end

-- --------------------------------------------------------------------- liveness (pure)
--
-- Companion.step(previous, sample, opts) is the whole machine and it is PURE: it never
-- mutates `previous` and holds no state of its own, so the caller owns the table, may keep
-- it, and may hand it to the next poll. `sample` is what poll() decoded; a sample of nil
-- is an INCOHERENT poll, which is itself a liveness event (see below).
--
-- Rules, in the order they are evaluated:
--   * first sample of a handshake -> WARMING. Nothing is bound yet, so there is nothing to
--     lose and this is the start of the K-poll warmup, NOT a lost generation.
--   * changed (generation, cookie) -> LOST, fresh handshake. That is the soft-reset /
--     New Game latch: the cookie is re-minted and the generation bumped in one block
--     (beacon.c:174-193, C2_BEACON_SPEC.md:326-336,367-377).
--   * unchanged (generation, cookie) and the engine-clock delta did not advance -> a stall
--     tick, and N of them -> LOST.
--   * LIVE only when K consecutive polls agreed on the pair AND the clock advanced on this
--     poll. "advanced at all within N polls", NEVER "advanced by exactly N" (C2_BEACON_SPEC.md:403-407): the service is
--     visited at most once per outer loop iteration and only inside the frame-sync guard
--     (C2_BEACON_SPEC.md:394-407).
function Companion.step(previous, sample, opts)
    local options = plain(opts) and opts or {}
    local stable_polls = positive(options.stable_polls) and options.stable_polls or Companion.DEFAULTS.stable_polls
    local stall_polls = positive(options.stall_polls) and options.stall_polls or Companion.DEFAULTS.stall_polls
    if not plain(previous) then previous = {} end

    -- Declared before restart() so the closure below closes over THESE locals; a forward
    -- declaration here would silently bind a global instead.
    local generation, cookie, delta

    local function restart(state_name, stable, stalled)
        return {
            state = state_name, stable = stable, stalled = stalled,
            stable_generation = generation, stable_cookie = cookie, stable_delta = delta,
        }
    end

    if not plain(sample) or not plain(sample.title) then
        -- An incoherent poll is a liveness event, not a shrug. The header is re-stamped on
        -- every service visit, so a refusal that left the previous LIVE standing would be a
        -- host that stays live over a header it has just failed to read -- the shape of
        -- falsifier 3b (C2_BEACON_SPEC.md:528). Everything observed is discarded and the
        -- handshake restarts from nothing.
        return { state = "LOST", stable = 0, stalled = 0, reason = "sample:absent" }
    end

    generation, cookie, delta = sample.generation, sample.title.cookie, sample.title.delta
    if not uint(generation, 0xFFFFFFFF) or not uint(cookie, 0xFFFFFFFF)
        or not uint(delta, 0xFFFFFFFF) then
        return { state = "LOST", stable = 0, stalled = 0, reason = "sample:fields" }
    end

    local last_generation, last_cookie = previous.stable_generation, previous.stable_cookie
    if not uint(last_generation, 0xFFFFFFFF) or not uint(last_cookie, 0xFFFFFFFF) then
        return restart("WARMING", 1, 0)
    end

    if generation ~= last_generation or cookie ~= last_cookie then
        -- LATCH. The ROM zeroes its own delta in the same block that bumps the generation
        -- (beacon.c:181), so that reset IS the latch and is deliberately NOT counted as a
        -- stall tick: this branch returns before the clock is examined at all.
        return restart("LOST", 0, 0)
    end

    -- DESIGN (open, owner/ABI call): a stall shorter than N is TOLERATED -- stable is kept and
    -- only `stalled` moves, so a skipped service visit (C2_BEACON_SPEC.md:403-407) does not
    -- flap LIVE. The spec says "K consecutive polls" without defining a sub-N stall.
    -- producer_phase is REPORTED, not gated: spec 6.2 item 5 (phase == 0) is the readiness of
    -- a publisher, which the C5 consumer reads from state.producer_phase.
    local stable = uint(previous.stable, 0xFFFF) and previous.stable or 0
    local stalled = uint(previous.stalled, 0xFFFF) and previous.stalled or 0
    if delta ~= previous.stable_delta then
        stable, stalled = math.min(stable + 1, 0xFFFF), 0  -- saturate: a wrap would drop LIVE
    else
        stalled = stalled + 1
    end
    if stalled >= stall_polls then
        -- The arena has not been re-stamped for N polls: drop the bound epoch, drop every
        -- outstanding request, re-handshake (C2_BEACON_SPEC.md:521-522).
        return restart("LOST", 0, 0)
    end
    return restart((stable >= stable_polls and stalled == 0) and "LIVE" or "WARMING", stable, stalled)
end

-- ------------------------------------------------------------------------ construction

-- new(io, config) -> binder | nil, reason. No write path, no clock, no domain.
function Companion.new(io, config)
    if not plain(config) then return nil, "config" end
    local mailbox = config.mailbox
    if not plain(mailbox) or type(mailbox.new) ~= "function" or type(mailbox.layout) ~= "function" then
        return nil, "config:mailbox"
    end
    local shared = mailbox.layout()
    if not plain(shared) or not uint(shared.reserved_offset, 0xFFFF)
        or not uint(shared.caps_shared, 0xFFFFFFFF) or not uint(shared.caps_reserved, 0xFFFFFFFF) then
        return nil, "config:mailbox"
    end
    -- A threshold that is present but not a positive count is a caller bug, not something
    -- to paper over with the default; a threshold that is absent takes the default.
    local stable_polls, stall_polls = Companion.DEFAULTS.stable_polls, Companion.DEFAULTS.stall_polls
    if config.stable_polls ~= nil then
        if not positive(config.stable_polls) then return nil, "config:polls" end
        stable_polls = config.stable_polls
    end
    if config.stall_polls ~= nil then
        if not positive(config.stall_polls) then return nil, "config:polls" end
        stall_polls = config.stall_polls
    end
    local reader, why = mailbox.new(io, { base = config.base, abi = L.abi })
    if not reader then return nil, why end

    -- beacon.h:75: SLINK_GEN4_TITLE_OFFSET IS SLINK_RESERVED_OFFSET. Derived, not copied.
    local title_offset = shared.reserved_offset
    local shared_mask, reserved_mask = shared.caps_shared, shared.caps_reserved
    local title_mask = (~(shared_mask | reserved_mask)) & 0xFFFFFFFF
    local opts = { stable_polls = stable_polls, stall_polls = stall_polls }

    local function decode(raw)
        local magic = word(raw, 0, 4)
        if magic ~= L.title_magic then return nil, "title:magic" end
        local version = word(raw, 0x04, 2)
        if version ~= L.title_version then return nil, "title:version" end
        local size = word(raw, 0x06, 2)
        -- The declared size is the ROM's own; a smaller block would leave fields this
        -- reader would then invent, and a larger one claims bytes that were never copied.
        if size ~= L.title_size then return nil, "title:size" end
        return {
            magic = magic, version = version, size = size,
            cookie = word(raw, L.title_cookie_field, 4),
            identity = word(raw, L.title_identity_field, 4),
            delta = word(raw, L.title_delta_field, 4),
            generation = word(raw, L.title_generation_field, 4),
            registrations = word(raw, L.title_registrations_field, 4),
            -- Reported, never gated: beacon.h:95 says the tail stays zero, but nothing in
            -- the liveness rule reads it and a host write there is transient by design.
            headroom_zero = headroom_clear(raw),
        }, nil
    end

    local binder = {}

    function binder:layout()
        local out = copy(L)
        for k, v in pairs({ title_offset = title_offset,
                            caps_shared_mask = shared_mask, caps_reserved_mask = reserved_mask,
                            caps_title_mask = title_mask, stable_polls = stable_polls,
                            stall_polls = stall_polls }) do
            out[k] = v
        end
        return out
    end

    -- ONE poll: the envelope snapshot, then the title block copied twice AROUND a check,
    -- then the decode and the cross-checks. The copies are taken either side of a fresh
    -- envelope sample so that the sample they are compared against sits BETWEEN them: a
    -- latch that lands during either window then shows up as a generation mirror mismatch
    -- or as two differing copies, never as a silently coherent read.
    function binder:poll(previous)
        local function refuse(reason)
            local lost = Companion.step(previous, nil, opts)
            lost.reason = reason
            return lost, reason
        end

        local snap, snap_why = reader:snapshot()
        -- snap is consumed for its COHERENCE claim only (mailbox.lua:167-174) and its
        -- payload bytes are never decoded here: they are the shared transaction envelope,
        -- which is the mailbox WRITER's business, not this binder's.
        if not snap then return refuse(snap_why) end
        local first, first_why = reader:region(title_offset, L.title_size)
        if not first then return refuse(first_why) end
        local mid, mid_why = reader:header()
        if not mid then return refuse(mid_why) end
        local second, second_why = reader:region(title_offset, L.title_size)
        if not second then return refuse(second_why) end
        if not identical(first, second, L.title_size) then
            return refuse("title:coherence")
        end

        local title, decode_why = decode(first)
        if not title then return refuse(decode_why) end
        -- The title's generation is a MIRROR of the mailbox's reserved word (beacon.h:93).
        -- Equal is the cross-check that binds the two headers into one coherent read; a
        -- mismatch means this poll straddled a latch.
        if title.generation ~= mid.reserved then
            return refuse("title:coherence")
        end

        -- Reported whole: bits 0..6 shared, 7..15 reserved, 16..31 title-private (beacon.h:111-125).
        local caps = { word = mid.capabilities, shared = mid.caps_shared,
                       reserved = mid.reserved_bits, title_private = mid.capabilities & title_mask }
        local state = Companion.step(previous, {
            title = title, generation = mid.reserved,
            session_epoch = mid.session_epoch, producer_phase = mid.phase,
            capabilities = caps.word, caps_shared = caps.shared,
            reserved_bits = caps.reserved, caps = caps,
        }, opts)
        -- One table in, one table out: the caller passes this straight back as `previous`.
        state.title = title
        state.caps = caps
        state.capabilities = caps.word
        state.caps_shared = caps.shared
        state.reserved_bits = caps.reserved
        state.generation = mid.reserved
        state.session_epoch = mid.session_epoch
        state.producer_phase = mid.phase
        return state, nil
    end

    return binder, nil
end

return Companion