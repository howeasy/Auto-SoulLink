"""Frame-model regressions for the Gen 3 active-faint L-hammer input boundary.

(Reviewed and finished by W2, G5-RR-BATTERY, from an OMP draft: L is KEYINPUT 0x200, not R's
0x100; the pulse is driven by the game's own read of L, so the model's per-frame read yields the
alternation asserted below.)

The fake engine below runs the real ``scenario_gen3_linked_faint_active.lua`` module. It samples
``gMain.heldKeysRaw`` before each observer callback, so a joypad change made at the end of one
frame is visible to the next frame. That makes the pre-commit guard, the one-frame L pulse, and
the KO release observable as engine state rather than as source-text shape.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


_LH_MODEL = r"""
function LH(case, fault)
    fault = fault or ""
    local FROM, TO, SLOTADDR = 0x0802E33D, 0x0802E3B5, 0x03004FE0
    local PARTY_HP, BATTLE_HP = 0x02024284 + 0x56, 0x02023BE4 + 0x28
    local logs, lines, watchers, sites, press_events = {}, {}, {}, {}, {}
    local frame, rx, entry, commit_at, ko_at = 100, 0, nil, nil, nil
    local joy_l, presses, balls = false, 0, 5
    local party = {
        { slot = 0, key = "K0", hp = 20, max_hp = 20, level = 9 },
        { slot = 1, key = "K1", hp = 17, max_hp = 17, level = 4 },
    }
    local e = {
        in_battle = false, ctrl0 = 0x08030001, exec = 1, keys = 0,
        battler0_slot = 0, battle_hp = 20, pp = { 35, 30, 0, 0 },
        status3 = 0, counter = 0, last_move = 0, outcome = 0,
    }

    local ctx = {
        D = { active_faint_case = case, timeout_secs = 60 }, player = "b", cp = {},
        rr = case == "lhammer",
        handoff = { slot_addr = SLOTADDR, from = FROM, to = { TO } },
    }
    ctx.log = function(s) logs[#logs + 1] = tostring(s) end

    local function tick()
        frame = frame + 1
        e.keys = joy_l and 0x200 or 0       -- heldKeysRaw (L = 0x200) sampled at the frame boundary
        if rx == 1 and not commit_at and e.in_battle then
            commit_at = frame
            if fault == "commit_keys" then e.keys = 0x100 end
            for i = 1, 5 do
                local last = i == 5
                lines[#lines + 1] = {
                    reason = "battle_commit", address = last and SLOTADDR or 0x02023DFC + i,
                    len = last and 4 or 1, frame = frame,
                }
            end
            e.ctrl0, e.status3 = FROM, 0x20
            entry = { key = "K0", perish = true, handoff = true, why = "active faint committed" }
            logs[#logs + 1] = "[client] [SLink-gen3] force_faint: Perish commit battler=0 handoff=1 K0"
        elseif commit_at and frame == commit_at + 1 then
            e.ctrl0, e.exec = TO, 0
        elseif commit_at and frame == commit_at + 5 then
            e.battle_hp, e.status3, ko_at = 0, 0, frame
        elseif ko_at and #sites == 0 then
            party[1].hp = 0
            sites[#sites + 1] = {
                frame = frame, active = 0, battler0_slot = 0, battle_hp = 0,
                party_hp = 0, counter = e.counter + 1,
            }
            logs[#logs + 1] = string.format("FORCED_HP0 K0 frame=%d in_battle=1 battler=1", frame)
            entry = nil
        end
        for i = #watchers, 1, -1 do
            if watchers[i]() then table.remove(watchers, i) end
        end
    end

    ctx.frames = function(n) for _ = 1, n do tick() end end
    ctx.watch = function(fn) watchers[#watchers + 1] = fn end
    ctx.wait_until = function(pred)
        for _ = 1, 100 do
            if pred() then return true end
            tick()
        end
        return false
    end
    ctx.mash_until = function(pred)
        for _ = 1, 100 do
            if pred() then return true end
            ctx.press({ A = true })
            tick()
        end
        return false
    end
    ctx.wait_go = function() return true end
    ctx.linked = function() return "K0" end
    ctx.party = function() return party end
    ctx.find = function(key) for _, mon in ipairs(party) do if mon.key == key then return mon end end end
    ctx.hunt = function() e.in_battle, e.ctrl0 = true, 0x08030001; return true end
    ctx.SP = {
        verify_fight_cursor = function() return e.in_battle and (ko_at and "party" or "fight") or nil end,
    }
    ctx.battler_slot = function() return e.battler0_slot end
    ctx.in_battle = function() return e.in_battle end
    ctx.write_lines = function() return lines end
    ctx.attempted = function() return #lines end
    ctx.inputs = function() return presses end
    ctx.press = function(buttons)
        local down = buttons.L == true
        if down then presses = presses + 1 end
        press_events[#press_events + 1] = { frame = frame, l = down }
        joy_l = down
    end
    ctx.faint_sites = function() return sites end
    ctx.hp_addrs = function() return { [PARTY_HP] = true, [BATTLE_HP] = true } end
    ctx.engine_sample = function()
        local sample = {}
        for key, value in pairs(e) do sample[key] = value end
        sample.pp = { e.pp[1], e.pp[2], e.pp[3], e.pp[4] }
        sample.frame, sample.party_hp = frame, party[1].hp
        return sample
    end
    ctx.battle_hold = function(key) if entry and entry.key == key then return entry end end
    ctx.received = function(cmd)
        if cmd == "force_faint" then return rx end
        return cmd == "memorialize" and 1 or 0
    end
    ctx.wait_received = function()
        rx = 1
        logs[#logs + 1] = "RX force_faint key=K0"
        if fault == "pre_press" then ctx.press({ L = true }) end
        return true
    end
    ctx.balls = function() return balls end
    ctx.peek_u8 = function() return 4 end
    ctx.try = function(fn, ...) return pcall(fn, ...) end
    ctx.send_out = function(slot)
        e.battler0_slot = slot
        tick()
        logs[#logs + 1] = "SENT_OUT slot=1 battler_slot=1"
        return true
    end
    ctx.run_away = function()
        e.outcome = 4
        tick()
        e.in_battle = false
        tick()
        return true
    end
    ctx.play = {
        fight_through = function() e.in_battle = false; tick(); return true end,
        wait_scene_settled = function() ctx.frames(1); return true end,
    }
    local sent = {}
    ctx.sent = function(event) return sent[event] or 0 end
    ctx.wait_sent = function(event, key)
        sent[event] = 1
        logs[#logs + 1] = "TX " .. event .. " " .. key .. " {}"
        return true
    end
    ctx.queued = function() return nil end
    ctx.save = function()
        logs[#logs + 1] = "SAVE_WITNESS_DUMP path=p bytes=131072 saves=1 frame=1 counter=5"
        return true
    end

    local fn = dofile(SCENARIO_DIR .. "/scenario_gen3_linked_faint_active.lua")
    local ok, passed, message = pcall(fn, ctx)
    return ok, passed, tostring(ok and message or passed),
           table.concat(logs, "\n") .. "\n", press_events
end
"""


@pytest.fixture(scope="module")
def runner():
    from lupa import LuaRuntime

    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.globals().SCENARIO_DIR = str(REPO / "lua" / "tests" / "duo").replace("\\", "/")
    runtime.execute(_LH_MODEL)
    return runtime.globals().LH


def _run(runner, case, fault=""):
    ok, passed, message, log, press_events = runner(case, fault)
    events = [{"frame": press_events[i]["frame"], "l": press_events[i]["l"]}
              for i in range(1, len(press_events) + 1)]
    return bool(ok), passed is True, str(message), str(log), events


def test_lhammer_rejects_a_press_before_the_commit(runner):
    ok, passed, message, log, _ = _run(runner, "lhammer", "pre_press")

    assert ok and not passed
    assert message == "input before the commit"
    assert "ACTIVE_COMMIT K0" not in log


def test_lhammer_is_a_one_frame_pulse_and_is_released_at_the_ko(runner):
    ok, passed, message, log, events = _run(runner, "lhammer")

    assert ok and passed, message
    commit = int(re.search(r"^ACTIVE_COMMIT K0 frame=(\d+) ", log, re.M).group(1))
    ko = int(re.search(r"^ACTIVE_KO K0 frame=(\d+) ", log, re.M).group(1))
    assert [event["frame"] for event in events] == list(range(commit, ko + 1))
    assert all(events[i]["l"] is (i % 2 == 0) for i in range(len(events)))
    assert events[-1]["l"] is False
    assert re.search(r"^ACTIVE_COMMIT K0 .* case=lhammer$", log, re.M)
    assert re.search(r"^ACTIVE_KO K0 .* case=lhammer$", log, re.M)


def test_ordinary_case_rejects_a_key_seen_only_on_the_commit_frame(runner):
    ok, passed, message, log, _ = _run(runner, "wild", "commit_keys")

    assert ok and not passed
    # the pre-commit guard runs on the commit frame itself, before the commit is accepted
    assert message == "input before the commit"
    assert "ACTIVE_COMMIT K0" not in log


def test_ordinary_case_with_no_input_passes_and_case_tags_the_receipt(runner):
    ok, passed, message, log, events = _run(runner, "wild")

    assert ok and passed, message
    assert events == []
    assert re.search(r"^ACTIVE_COMMIT K0 .* why=\"active faint committed\" case=wild$", log, re.M)
    assert re.search(r"^ACTIVE_KO K0 .* attempted=5 case=wild$", log, re.M)
