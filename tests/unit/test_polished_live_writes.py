"""Run the actual live write oracle against deliberately corrupted memory transitions."""
from pathlib import Path

import pytest
from lupa.lua55 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def run_driver(fault="none"):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().driver_root = ROOT.as_posix()
    lua.globals().fault = fault
    lua.execute(r'''
        local real_dofile = dofile
        os.getenv = function(name)
            if name == "SLINK_ROOT" then return driver_root end
            return nil
        end
        local frame, phase = 0, "before"
        local mem = { ["System Bus"] = {}, CartRAM = {}, WRAM = {} }
        local keys = {"one", "two", "three", "four", "five"}
        local sb, count_at, ots, nicks = 0xdcd6, 0xdcce, 0xddf6, 0xde38
        local function read(a, d)
            if d == "WRAM" and a >= 0x1000 and a < 0x2000 then
                return mem["System Bus"][a + 0xc000] or 0
            end
            return mem[d][a] or 0
        end
        memory = {read_u8 = read, write_u8 = function(a, v, d) mem[d][a] = v end}
        local function put(a, v, d) memory.write_u8(a, v, d or "System Bus") end
        mem["System Bus"][count_at] = 5
        for slot = 0, 5 do
            for off = 0, 47 do mem["System Bus"][sb + slot * 48 + off] = slot + 1 end
            mem["System Bus"][sb + slot * 48 + 32] = 0
            mem["System Bus"][sb + slot * 48 + 34] = 0
            mem["System Bus"][sb + slot * 48 + 35] = 100
            mem["System Bus"][sb + slot * 48 + 36] = 0
            mem["System Bus"][sb + slot * 48 + 37] = 100
            for off = 0, 10 do
                mem["System Bus"][ots + slot * 11 + off] = 20 + slot
                mem["System Bus"][nicks + slot * 11 + off] = 40 + slot
            end
        end
        local coords = {sNewBox1 = {1, 0xb0e4}, wPokeDB1UsedEntries = {2, 0xd8b7},
                        wPokeDB2UsedEntries = {2, 0xd8d1}}
        for i = 1, 20 do coords["sNewBox" .. i] = {1, 0xb0e4 + (i - 1) * 33} end
        coords.sBoxMons1A, coords.sBoxMons1B, coords.sBoxMons1C = {2, 0xa000}, {0, 0xa000}, {1, 0xb60c}
        coords.sBoxMons2A, coords.sBoxMons2B, coords.sBoxMons2C = {3, 0xa000}, {0, 0xabf1}, {1, 0xb858}
        local census = {}
        function census.read_storage_box(index)
            if phase == "withdrawn" and fault == "withdraw_census_refusal" then return nil, "unreadable" end
            local present = phase == "deposited" or (phase == "withdrawn" and fault == "withdraw_ghost")
            return {mons = (index == 0 and present) and {{key = "four", slot = 0, raw_hex = "00", bank = 1, entry = 1}} or {}}
        end
        local reads = {}
        function reads:read_party()
            if phase == "deposited" and fault == "read_party_refusal" then return nil, "corrupt party" end
            local mons = {}
            for i, key in ipairs(keys) do mons[i] = {key = key, species = i, level = 50} end
            return {mons = mons}
        end
        SLINK_GEN2_PARTS = {pack = "polished_crystal", artifact_kind = "overlay", runtime_rom_sha1 = "synthetic",
                           reads = reads, overworld = {writes = {}, boxes = {}, coords = coords, census = census}}
        SLINK_GEN2_CLIENT = {}
        function SLINK_GEN2_CLIENT:handle_command(cmd)
            if cmd.cmd == "force_faint" then
                for _, off in ipairs({32, 34, 35}) do put(sb + 2 * 48 + off, 0) end
                if fault == "faint_other_zero" then put(sb + 32, 0) end
            elseif cmd.cmd == "box_mon" then
                for i = 0, 48 do put(0x4000 + i, i % 7, "CartRAM") end
                put(0x30e4, 1, "CartRAM")
                put(0x30f8, 0, "CartRAM")
                put(0x28b7, 1, "WRAM")
                for _, spec in ipairs({{sb, 48}, {ots, 11}, {nicks, 11}}) do
                    for slot = 3, 4 do
                        for off = 0, spec[2] - 1 do
                            put(spec[1] + slot * spec[2] + off, read(spec[1] + (slot + 1) * spec[2] + off, "System Bus"))
                        end
                    end
                end
                put(count_at, 4)
                keys = {"one", "two", "three", "five"}
                phase = "deposited"
                if fault == "unrelated_nickname" then put(nicks, 99)
                elseif fault == "unrelated_ot" then put(ots + 2 * 11, 99)
                elseif fault == "unrelated_party" then put(sb, 99)
                elseif fault == "unrelated_cart" then put(0x4031, 99, "CartRAM")
                elseif fault == "unrelated_box" then put(0x3105, 99, "CartRAM")
                elseif fault == "unrelated_alloc" then put(0x28b8, 1, "WRAM") end
            elseif cmd.cmd == "party_mon" then
                keys = {"one", "two", "three", "five", "four"}
                for off = 0, 47 do put(sb + 4 * 48 + off, 4) end
                for _, off in ipairs({32, 34, 36}) do put(sb + 4 * 48 + off, 0) end
                for _, off in ipairs({35, 37}) do put(sb + 4 * 48 + off, 100) end
                for off = 0, 10 do put(ots + 4 * 11 + off, 23); put(nicks + 4 * 11 + off, 43) end
                put(count_at, 5)
                put(0x30e4, 0, "CartRAM")
                put(0x30f8, 0, "CartRAM")
                phase = "withdrawn"
            end
        end
        L = {ROOT = driver_root, SYM = {wPartyMons = {1, sb}, wPartyCount = {1, count_at},
                    wPartyMonOTs = {1, ots}, wPartyMonNicknames = {1, nicks},
                    wPartyMonNicknamesEnd = {1, 0xde7a}}, failures = 0, logs = {}, checks = {},
             json = real_dofile(driver_root .. "/lua/json_codec.lua")}
        function L.log(text) L.logs[#L.logs + 1] = text end
        function L.check(what, ok, detail)
            L.checks[#L.checks + 1] = {what = what, ok = ok == true, detail = detail}
            if not ok then L.failures = L.failures + 1 end
            return ok
        end
        function L.finish(tag) L.finished = tag; error("oracle-finished", 0) end
        function L.die(why) L.check(why, false); L.finish("aborted") end
        function L.woff(name) return L.SYM[name][2] - 0xc000 end
        function L.rw(name)
            if name == "wPartyCount" then return read(count_at, "System Bus") end
            if name == "wMapStatus" then return 2 end
            return 0
        end
        function L.bus(a) return read(a, "System Bus") end
        function L.unhex(s) return {0} end
        function L.hook() end
        function L.to_overworld() return true end
        function L.idle(n) frame = frame + n end
        emu = {framecount = function() return frame end}
        event = {onframeend = function() end}
        dofile = function(path)
            if path:match("pol_lib.lua$") then return L end
            if path:match("slink.lua$") then return end
            if path:match("polished_boxes.lua$") then return {verify = function() return true end} end
            return real_dofile(path)
        end
        local ok, why = pcall(real_dofile, driver_root .. "/tools/polished_live/writes.lua")
        assert(not ok and why == "oracle-finished", tostring(why))
    ''')
    return lua.globals().L


def test_valid_deposit_withdraw_memory_roundtrip_is_accepted():
    report = run_driver()
    failures = [r["what"] for r in report.checks.values() if not r["ok"]]
    assert report.failures == 0, failures
    assert report.finished == "pol-live-writes"


@pytest.mark.parametrize("fault", [
    "unrelated_nickname", "unrelated_ot", "unrelated_party", "unrelated_cart",
    "unrelated_box", "unrelated_alloc", "read_party_refusal", "withdraw_ghost",
    "withdraw_census_refusal", "faint_other_zero",
])
def test_live_oracle_rejects_collateral_writes_and_refused_readbacks(fault):
    report = run_driver(fault)
    assert report.failures > 0, f"corrupt transition {fault} was accepted"
