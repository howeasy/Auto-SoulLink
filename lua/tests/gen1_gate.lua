-- lua/tests/gen1_gate.lua — headless gate harness for the NEW Gen 1 client modules.
--
-- Like gatelib.lua but built on lua/gen1/entry.lua (profile.json, reads, signals, writes,
-- write_safety) instead of the pre-rewrite memory_gb/gen1_rby modules, which are not evidence.
-- Boot proof is the CPU checkpoint gen1_write_safety verifies (main thread parked in OverworldLoop),
-- because party count / flags / map id all read plausibly on the title and loading screens
-- and gatelib's walking proof triggers encounters on a grass fixture.
--
--   local G = dofile(SLINK_ROOT .. "/lua/tests/gen1_gate.lua")
--   local t = G.start("test_gen1_inspect_gate")   -- result: patch/build/<name>_result.txt
--   t.check(what, ok, detail); t.finish()
local Lib = {}

function Lib.start(gate_name, opts)
    opts = opts or {}
    local ROOT = SLINK_ROOT or os.getenv("SLINK_ROOT")
    assert(ROOT, "SLINK_ROOT unset — launch via tools/run_gb_gate.py")
    package.path = ROOT .. "/lua/?.lua;" .. package.path
    local Entry = dofile(ROOT .. "/lua/gen1/entry.lua")
    local OUT = ROOT .. "/patch/build/" .. gate_name .. "_result.txt"
    local fmt = string.format
    local t = { ROOT = ROOT, Entry = Entry, frame = 0, failures = 0, lines = {} }

    function t.log(s)
        console.log(s)
        t.lines[#t.lines + 1] = s
        local f = io.open(OUT, "w")
        if f then f:write(table.concat(t.lines, "\n") .. "\n"); f:close() end
    end
    function t.check(what, ok, detail)
        if not ok then t.failures = t.failures + 1 end
        t.log(fmt("  [%s] %s%s", ok and "ok" or "FAIL", what, detail and ("  — " .. tostring(detail)) or ""))
        return ok
    end
    function t.finish(extra)
        t.log(fmt("RESULT: %s %s (%d checks failed)", t.failures == 0 and "PASS" or "FAIL", extra or gate_name, t.failures))
        client.exit()
        error("slink-gate-finished", 0)
    end
    function t.step(buttons)
        if buttons then joypad.set(buttons) end
        emu.frameadvance()
        t.frame = t.frame + 1
    end
    function t.hold(btn, frames, stop)
        for _ = 1, frames do
            if stop and stop() then return true end
            t.step({ [btn] = true })
        end
        t.step(nil)
        return stop and stop() or false
    end
    function t.idle(frames) for _ = 1, frames do t.step(nil) end end

    -- Foundation first, by sha1, exactly as lua/gen1/run.lua does it (P3b-e). The built pureRGB
    -- cartridges keep the vanilla header, so the header names the family but cannot name the
    -- foundation -- and PureGreen has no family at all -- so admission, not detect_title, is what
    -- decides which pack and which title the gate runs against.
    local json_codec = dofile(ROOT .. "/lua/json_codec.lua")
    local function rom_u8(a) return memory.read_u8(a, "ROM") end
    local env_title = os.getenv("SLINK_GATE_TITLE")
    local title, pack, kind
    if env_title and env_title ~= "" then
        -- The launcher named the cartridge: only for a build whose sha1 cannot be admitted (the
        -- vanilla companion-patch artifacts, which are vanilla-layout). run_gb_gate.gate_env
        -- sets this, and never for a pureRGB build.
        title, kind = env_title, "named"
        pack = env_title:sub(1, 4) == "pure" and "gen1_purergb" or "gen1_rby"
    else
        local admitted, why = Entry.admit({
            root = ROOT, json = json_codec,
            rom_sha1 = gameinfo.getromhash and gameinfo.getromhash() or "",
            indatabase = gameinfo.indatabase and gameinfo.indatabase() or false,
            read_rom_u8 = rom_u8, rom_size = memory.getmemorydomainsize("ROM"),
            header = Entry.header_title(rom_u8),
        })
        if not admitted then
            t.log(fmt("RESULT: FAIL not an admitted Gen 1 cartridge: %s", tostring(why)))
            client.exit()
            error("slink-gate-finished", 0)
        end
        title, pack, kind = admitted.title, admitted.pack, admitted.kind
    end
    t.title, t.pack, t.kind = title, pack, kind
    -- The lane's driver-facts table (P3b-e) and the pack's own write checkpoint: a pure gate has to
    -- read data/games/gen1_purergb/write_checkpoint.json, keyed by the pure title.
    t.facts = dofile(ROOT .. "/lua/tests/"
                     .. (pack == "gen1_purergb" and "gen1_pure_facts.lua" or "gen1_rb_facts.lua"))
    -- The admitted KIND picks the checkpoint file, same rule as Entry.build's pack_file(): clean
    -- reads "checkpoint", any other kind reads "checkpoint_<kind>" (overlay -> checkpoint_overlay).
    -- Hard-coding "checkpoint" here booted an overlay-admitted cartridge against the CLEAN
    -- checkpoint's WRAM-bank/PC facts, which is a different build (PLAN M3 A4).
    local checkpoint_key = kind == "clean" and "checkpoint" or ("checkpoint_" .. kind)
    t.checkpoint_path = ROOT .. "/" .. assert(Entry.PACK_FILES[pack][checkpoint_key],
        pack .. " ships no " .. checkpoint_key .. " for admitted kind " .. tostring(kind))
    -- Emulator speed multiplier: a BizHawk-level fact, SAME in both tables (F.CLIENT.speedmode).
    client.speedmode(t.facts.CLIENT.speedmode)
    t.deps = Entry.bizhawk_deps()
    local sent, replies = {}, {}
    t.sent, t.replies = sent, replies
    -- a loopback "server": the gate inspects what the client would send and feeds replies
    t.net = {
        init = function() end, connected = function() return t.online == true end, pump = function() end,
        send = function(line) sent[#sent + 1] = line end,
        receive = function() return table.remove(replies, 1) end,
    }
    -- The overlay is stubbed out (a gate has no one to show it to), but `sanitize` is the REAL
    -- one: entry.lua folds every panel row through deps.hud.sanitize before it becomes tiles,
    -- and its fallback when the field is missing is the identity. A gate carrying the identity
    -- would paint bytes the cartridge has no glyph for and still call itself green.
    t.hud = { show = function() end, prompt = function() end, set_game_over = function() end,
              set_rebuilding = function() end, clear_rebuilding = function() end,
              sanitize = dofile(ROOT .. "/lua/hud.lua").sanitize }
    t.client, t.parts = Entry.build({ root = ROOT, io = t.deps, net = t.net, hud = t.hud,
                                      pack = pack, title = title, kind = kind,
                                      player = "a", rom_sha1 = gameinfo.getromhash():lower(),
                                      log = function(s) console.log(s) end })
    local ram = t.parts.profile.ram
    t.ram = ram
    t.log(fmt("[%s] title=%s rom=%s", gate_name, title, gameinfo.getromhash():lower():sub(1, 8)))
    if opts.no_boot then return t end

    -- Boot proof. gatelib walked two round trips because party count / flags / map id all read
    -- plausibly on the title and CONTINUE screens. Walking triggers encounters on a grass
    -- fixture (blue/battle: stuck in a wild battle at frame 1555), so the proof here is the
    -- checkpoint gen1_write_safety verifies from the CPU itself: the main thread parked in
    -- OverworldLoop's DelayFrame, PC at the IRQ vector, no battle/script/text/serial owner.
    -- That is unreachable from any menu or loading screen, and it moves the player nowhere.
    local safety = dofile(ROOT .. "/lua/gen1_write_safety.lua")
    local ws = t.parts.json.decode(assert(io.open(t.checkpoint_path, "rb")):read("*a"))[title]
    t.overworld_ok = function() return safety.check(ws, t.deps) == true end
    local booted, settled = false, 0
    for f = 1, 6000 do
        local count = memory.read_u8(ram.wPartyCount, "System Bus")
        local ok = count >= 1 and count <= 6 and t.overworld_ok()
        settled = ok and settled + 1 or 0
        if settled >= 30 then booted = true break end
        -- A on the lane's tap cadence (F.TUNING.input_cadence) walks the title and CONTINUE
        -- prompts; never Down.
        t.step((not ok and f % t.facts.TUNING.input_cadence < 2) and { A = true } or nil)
    end
    if not booted then
        client.screenshot(ROOT .. "/patch/build/" .. gate_name .. "_bootfail.png")
        t.check("booted into the overworld from the battery save", false, fmt("stuck at frame %d", t.frame))
        t.finish("boot failed")
    end
    t.log(fmt("[%s] booted at frame %d (party=%d, map=%d)", gate_name, t.frame,
              memory.read_u8(ram.wPartyCount, "System Bus"), memory.read_u8(ram.wCurMap, "System Bus")))
    return t
end

return Lib
