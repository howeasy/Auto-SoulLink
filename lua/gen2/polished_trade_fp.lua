-- lua/gen2/polished_trade_fp.lua — the Lua twin of
-- server/adapters/polished_trade_fingerprint.py.
--
-- WHAT THIS IS. The decision half of SlinkTradeDispatch, as a pure function over a snapshot.
-- No ROM byte is written, no overlay source is touched, and nothing here is armed: the overlay
-- is frozen until the title slice lands, and the capability bit is still not advertised
-- (patch/polished/src/slink.asm:73 `xor a ; core build: no capabilities`).
--
-- WHY THE CONSTANTS ARE INJECTED. Python resolves the nine expected bytes from
-- data/polished/polished_slink.sym at import, so a moved label fails there. Lua cannot read the
-- .sym, so the values arrive in a config table the composition supplies. This module REFUSES
-- without them — same shape as lua/gen2/polished_trade.lua, whose compose() returns nil, why when
-- the profile has no overlay trade block. A half-configured twin must never answer yes.
--
-- THE WINDOW. Samples are taken at SlinkDelayFrameBridge (ROM0 $0070) ENTRY; the dispatcher runs
-- three frames further in. bridge sp+0..31 becomes dispatch sp+12..43 and hROMBank lands at
-- sp+5. That shift is `local BRIDGE_DEPTH = 12`, mirroring the module's FRAME_DEPTH, and it is the
-- only place in this file that knows about it.
--
-- THE MEASUREMENT. tests/fixtures/polished/explore_B_stacks.json (sha256 pinned by
-- tests/unit/test_polished_trade_fp.py), overlay 34942315bb3e62189a56dabbcb9cef6dd3e9a9f5,
-- Pokemon Center 2F, 937 samples over 181 distinct stacks.
--
-- WHY THE ENGINE STATE IS THE GATE. Four measured samples carry a stack BYTE-IDENTICAL to the
-- accept case (talk x3, after_wait x1, all SP $C0DE, hROMBank $25) and must still be refused.
-- Nothing in the stack can separate them, so engineOk is the only discriminator there.
--
-- NOT CHECKED HERE, and both are omissions rather than grants:
--   * hVBlank. Polished's is a 0-7 mode selector, not vanilla's flag (docs/polished/TRADE.md
--     10.7; engine/link/link.asm:2276-2278), so the vanilla `cp VBLANK_NORMAL` port is `cp 0`.
--     It is not here because no Polished sample recorded hVBlank.
--   * the SVBK window vanilla checks at trade_dispatch.asm:30-33. No Polished evidence either way.
local FP = {}

local BRIDGE_DEPTH = 12

-- The nine dispatch-entry positions, bank first. sp+5 is hROMBank; the rest are bridge-entry
-- words shifted by BRIDGE_DEPTH. Order is load-bearing: sp+5 alone rejects the script bank ($24)
-- and the link wait ($0A), three of the five measured phases, before any deeper comparison.
FP.PINNED_POSITIONS = { 5, 12, 13, 14, 15, 24, 25, 26, 27 }

-- Positions deliberately NOT pinned: the game's own registers. Stage B and Stage 4 both record
-- sp+4 and sp+8..9 varying between runs; pinning them pins a register.
FP.NOISE_POSITIONS = { 4, 8, 9, 16, 17, 18, 19, 20, 21, 22, 23 }

-- WRAM refusals in patch/gen2/src/trade_dispatch.asm's order (:34-63): a value that must equal
-- `cfg.values[name]`, then the bit in `cfg.bits[name]` that must be clear.
FP.ENGINE_REFUSALS = { "wScriptMode", "wBattleMode", "wLinkMode", "wGameLogicPaused",
                       "hInMenu", "wMapStatus", "wMapEventStatus" }
FP.ENGINE_CLEAR_BITS = { "wPlayerStepFlags" }

local function unhex(s)
    if type(s) ~= "string" then return nil end
    if #(s) % 2 ~= 0 then return nil end
    return (s:gsub("%x%x", function(byte) return string.char(tonumber(byte, 16)) end))
end

--- bridge-entry sp+0..31 -> dispatch-entry sp+12..43, with hROMBank at sp+5.
-- The only place the frame depth lives, in this file and in its Python twin.
function FP.dispatchView(bridgeBytes, rombank)
    local raw = unhex(bridgeBytes)
    if not raw or #raw ~= 32 then return nil, "bridge sample is not 32 bytes" end
    local view = {}
    for index = 0, 31 do
        view[index + BRIDGE_DEPTH] = string.byte(raw, index + 1)
    end
    view[5] = tonumber(tostring(rombank), 16)
    return view
end

--- Validate the injected config; nil, why on anything short. Fail-closed, never a default.
function FP.checkConfig(cfg)
    if type(cfg) ~= "table" then return nil, "no config table" end
    for _, position in ipairs(FP.PINNED_POSITIONS) do
        local want = cfg.expected and cfg.expected[position]
        if type(want) ~= "number" or want < 0 or want > 255 then
            return nil, "config.expected[" .. position .. "] is missing or not a byte"
        end
    end
    for _, name in ipairs(FP.ENGINE_REFUSALS) do
        if type(cfg.values and cfg.values[name]) ~= "number" then
            return nil, "config.values." .. name .. " is missing"
        end
    end
    for _, name in ipairs(FP.ENGINE_CLEAR_BITS) do
        if type(cfg.bits and cfg.bits[name]) ~= "number" then
            return nil, "config.bits." .. name .. " is missing"
        end
    end
    return cfg
end

--- The nine pinned bytes, bank first.
function FP.stackOk(view, cfg)
    if type(view) ~= "table" then return false, "no dispatch view", nil end
    for _, position in ipairs(FP.PINNED_POSITIONS) do
        local got = view[position]
        if type(got) ~= "number" then
            return false, "dispatch sp+" .. position .. " is not in the sample", position
        end
        local want = cfg.expected[position]
        if got ~= want then
            return false, string.format("dispatch sp+%d is $%02x, expected $%02x",
                                        position, got, want), position
        end
    end
    return true, "stack fingerprint matches the idle overworld", nil
end

--- Every WRAM refusal the vanilla dispatcher makes, less the two with no Polished evidence.
function FP.engineOk(engine, cfg)
    if type(engine) ~= "table" then return false, "no engine block in the snapshot", nil end
    for _, name in ipairs(FP.ENGINE_REFUSALS) do
        local got = engine[name]
        if type(got) ~= "number" then
            return false, name .. " is not in the snapshot: refusing", name
        end
        local want = cfg.values[name]
        if got ~= want then
            return false, string.format("%s is $%02x, expected $%02x for a safe frame",
                                        name, got, want), name
        end
    end
    for _, name in ipairs(FP.ENGINE_CLEAR_BITS) do
        local got = engine[name]
        if type(got) ~= "number" then
            return false, name .. " is not in the snapshot: refusing", name
        end
        local bit = cfg.bits[name]
        if math.floor(got / (2 ^ bit)) % 2 == 1 then
            return false, string.format("%s bit %d (PLAYERSTEP_CONTINUE_F) is set: this frame adds "
                                        .. "no step vector, so opening a prompt would reanchor "
                                        .. "the background", name, bit), name
        end
    end
    return true, "engine state is a safe idle overworld frame", nil
end

--- The whole gate. Both halves run before the answer is yes.
-- Returns accepted, reason, stage, position.
function FP.accepts(snapshot, cfg)
    local conf, why = FP.checkConfig(cfg)
    if not conf then return false, why, "config", nil end
    local view = type(snapshot) == "table" and snapshot.stack_view or nil
    local ok, reason, position = FP.stackOk(view, conf)
    if not ok then return false, reason, "stack", position end
    ok, reason, position = FP.engineOk(type(snapshot) == "table" and snapshot.engine or nil, conf)
    if not ok then return false, reason, "engine", position end
    return true, reason, nil, nil
end

--- A raw lane record plus an engine block -> a snapshot.
function FP.snapshotFromProbe(sample, engine)
    if type(sample) ~= "table" then return nil, "no sample" end
    local view, why = FP.dispatchView(sample.bytes, sample.rombank)
    if not view then return nil, why end
    local copy = {}
    for key, value in pairs(engine or {}) do copy[key] = value end
    return { stack_view = view, engine = copy, phase = sample.phase }
end

return FP