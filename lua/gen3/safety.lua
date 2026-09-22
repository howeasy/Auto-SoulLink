-- Read-only checkpoint. Pack semantics: docs/gen3_write_checkpoint.md §4;
-- ROM offsets (not anchor.address) select bytes, including frame_control's slice.
local S = {}
local anchors = {"cb1_overworld", "cb2_overworld", "frame_control", "run_tasks", "try_saving_data"}
local predicates = {"callback1", "callback2", "field_controls_locked", "in_battle",
    "link_callback", "link_transferring", "palette_fade_active", "save_dialog_cb",
    "link_players_received", "script_context_status", "soft_reset_disabled"}
local function uint(v, limit)
    assert(type(v) == "number" and v % 1 == 0 and v >= 0 and v <= limit, "unreadable integer")
    return v
end
function S.new(pack, deps, kind)
    local self = {}
    local function read(addr, width, domain)
        uint(addr, 4294967295)
        local names = {[1] = "read_u8", [2] = "read_u16_le", [4] = "read_u32_le"}
        local fn = assert(deps.io[assert(names[width], "invalid width")])
        return uint(fn(addr, domain or "System Bus"), 256 ^ width - 1)
    end
    local function pointers()
        local p, out = assert(pack.pointers), {}
        assert(p.gSaveBlock1Ptr and p.gSaveBlock2Ptr, "missing save pointers")
        assert(p.gPokemonStoragePtr or p.pokemon_storage_base, "missing storage location")
        for name, spec in pairs(p) do
            local value = name == "pokemon_storage_base" and uint(spec.address, 4294967295)
                or read(spec.address, 4)
            assert(value > 0 and value % 4 == 0, "invalid pointer: " .. name)
            out[name] = value
        end
        return out
    end
    -- Snapshot is opaque to writers. Failure returns nil, reason; never a partial snapshot.
    function self:snapshot()
        local ok, result = pcall(pointers)
        if ok then return result end
        return nil, tostring(result)
    end
    function self:check(snapshot)
        local ok, result = pcall(function()
            assert(pack.version == "gen3-overworld-v1", "unsupported checkpoint")
            assert(type(kind) == "string", "artifact kind required")
            for _, name in ipairs(anchors) do assert(pack.anchors[name], "missing anchor: " .. name) end
            for _, a in pairs(pack.anchors) do
                local hex = assert(a.expected_hex[kind], "unverified artifact anchor")
                assert(#hex > 0 and #hex == a.length * 2 and not hex:find("[^%x]"), "invalid anchor bytes")
                for i = 1, a.length do
                    assert(read(a.rom_offset + i - 1, 1, "ROM") == tonumber(hex:sub(i * 2 - 1, i * 2), 16),
                        "ROM anchor differs")
                end
            end
            for _, name in ipairs(predicates) do assert(pack.predicates[name], "missing predicate: " .. name) end
            for name, p in pairs(pack.predicates) do
                local value = read(p.address + p.offset, p.width)
                if p.mask then value = value & uint(p.mask, 256 ^ p.width - 1) end
                assert(value == p.expect, "forbidden state: " .. name)
            end
            -- One parked range per title, from the pack. A frame end taken inside an IRQ handler
            -- fails the mode test on purpose; the next parked frame admits (checkpoint doc §4.3).
            local cpu, regs = assert(pack.cpu), deps.regs()
            local pc, cpsr = uint(regs.R15, 4294967295), uint(regs.CPSR, 4294967295)
            assert(cpsr % 32 == cpu.mode and math.floor(cpsr / 32) % 2 == cpu.thumb
                and pc >= cpu.pc_min and pc <= cpu.pc_max, "CPU outside parked checkpoint")
            local t, allowed = assert(pack.tasks), {}
            for _, address in pairs(t.allowed_overworld_tasks) do allowed[uint(address, 4294967295)] = true end
            assert(next(allowed), "empty task allow-list")
            assert(uint(t.count, 256) > 0 and uint(t.struct_size, 65535) > 0, "invalid task layout")
            for i = 0, t.count - 1 do
                local base = t.address + i * t.struct_size
                if read(base + t.is_active_offset, 1) ~= 0 then
                    local fn = read(base + t.func_offset, 4)
                    assert(fn % 2 == 1 and allowed[fn - 1], "unknown active task")
                end
            end
            assert(deps.native_idle() == true, "native transaction in flight or unreadable")
            local current = pointers()
            if snapshot then
                for name, value in pairs(current) do assert(snapshot[name] == value, "pointer moved: " .. name) end
                for name in pairs(snapshot) do assert(current[name] ~= nil, "pointer layout changed") end
            end
            return true
        end)
        if not ok then return false, tostring(result) end
        return result, "verified overworld checkpoint"
    end
    return self
end
return S
