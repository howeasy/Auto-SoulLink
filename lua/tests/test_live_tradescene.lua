-- test_live_tradescene.lua — SPIKE + validation for OP_TRADE_SCENE (the NATIVE trade animation).
-- Confirms the FireRed in-game trade scene (special DoInGameTradeScene, idx 265) can be driven against
-- a mon WE stage in gEnemyParty[0] (skipping the ROM-table CreateInGameTradePokemon): it trades
-- gPlayerParty[slot] <-> gEnemyParty[0] and returns to the overworld. We stage a REAL mon (a copy of the
-- player's own party slot 1, so gEnemyParty[0] is a valid/decryptable mon) and trade it into slot 0,
-- then assert slot 0 now holds the staged mon (compare the PLAINTEXT personality+OTID @ 0x00/0x04 — the
-- received mon's identity; trade-evolution would change the encrypted species but NOT these, so this
-- holds either way). Trade-evolution species change is validated in the two-instance manual run.
-- Needs the overworld savestate (has a party). Load with the PATCHED ROM:
--   EmuHawk.exe --lua=<this> patch/build/slink_RR.gba
local WT = SLINK_ROOT or os.getenv("SLINK_ROOT") or debug.getinfo(1, "S").source:match([=[^@(.*)[/\]lua[/\]tests[/\]]=])
assert(WT, "repo root unknown — launch via: python tools/run_gate.py <this script>")
local OUT = WT .. "/patch/build/tradescene_result.txt"
local MB  = dofile(WT .. "/lua/mailbox.lua")
local MON = 100
local gPlayerParty = 0x02024284
local function read_blob(addr) local t = {}; for j = 1, MON do t[j] = memory.read_u8(addr + (j - 1)) end; return t end
local function id4(addr, off) return string.format("%08X", memory.read_u32_le(addr + off)) end

local lines, fails = {}, 0
local function log(s) lines[#lines + 1] = s; console.log(s) end
local function check(n, c, e) if not c then fails = fails + 1 end
    log(string.format("  [%s] %s%s", c and "PASS" or "FAIL", n, e and "  " .. e or "")) end
local function finish() log(fails == 0 and "RESULT: PASS" or ("RESULT: FAIL (" .. fails .. ")"))
    local f = io.open(OUT, "w"); if f then f:write(table.concat(lines, "\n") .. "\n"); f:close() end
    client.exit() end
local function poll_ok(seq, n) for _ = 1, (n or 60) do emu.frameadvance(); local s = MB.poll(seq); if s then return s end end end

pcall(function() client.speedmode(400) end)
pcall(savestate.load, "E:/Howard/Bizhawk/GBA/State/slink_overworld.State")
emu.frameadvance(); pcall(memory.usememorydomain, "System Bus")
if not MB.present() then log("FAIL: beacon absent (unpatched ROM?)"); finish(); return end
log("beacon up")

-- The "partner" mon = a fresh, valid engine mon built into gEnemyParty[0] via OP_CREATE_MON (the
-- savestate's spare party slots are empty, so we can't copy one). Record its plaintext identity
-- (personality @0x00, OTID @0x04) after creation.
local gEnemyParty = 0x0202402C
local cseq = MB.send(MB.OP_CREATE_MON, MB.create_mon_args(0, 1, 5, 1, 0))  -- enemy slot0, Bulbasaur L5
check("created partner mon in gEnemyParty[0]", cseq ~= nil and poll_ok(cseq) == MB.ST_OK)
local want_pid, want_otid = id4(gEnemyParty + 0, 0x00), id4(gEnemyParty + 0, 0x04)
local before_pid = id4(gPlayerParty + 0, 0x00)
log("partner mon (gEnemyParty[0]): pid=" .. want_pid .. " otid=" .. want_otid ..
    " | player slot0 pid before=" .. before_pid)
check("partner mon is valid (non-zero identity)", want_pid ~= "00000000")

-- Run the native trade scene on slot 0. The scene plays many frames + may prompt; press A throughout.
local tseq = MB.trade_scene(0)
check("MB.trade_scene returned a seq", tseq ~= nil, "seq=" .. tostring(tseq))
if not tseq then finish(); return end
local st = nil
for i = 1, 6000 do
    if i % 2 == 0 then joypad.set({ A = true }) else joypad.set({}) end
    emu.frameadvance()
    st = MB.poll(tseq); if st then break end
end
check("trade scene ran and returned to the overworld (acked)", st ~= nil, "status=" .. tostring(st))
check("ack is ST_OK", st == MB.ST_OK)

-- Slot 0 now holds the received mon (the staged partner): plaintext identity matches + changed.
local got_pid, got_otid = id4(gPlayerParty + 0, 0x00), id4(gPlayerParty + 0, 0x04)
check("gPlayerParty[0] is now the traded-in partner mon", got_pid == want_pid and got_otid == want_otid,
      string.format("got pid=%s otid=%s want pid=%s otid=%s", got_pid, got_otid, want_pid, want_otid))
check("slot 0 actually changed (a real trade, not a no-op)", got_pid ~= before_pid,
      "before=" .. before_pid .. " after=" .. got_pid)
check("beacon still present (no crash)", MB.present())
finish()
