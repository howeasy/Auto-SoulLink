--[[
  lua/tests/duo/gen2_trade.lua -- card P4.3e, driver side: the native Gen 2 SLINK TRADE duo harness (TEST ONLY).

  Contract: Codex's P4.3e FOR DRIVER v1 + refinements (scenario keys gen2_trade_new / _decline_new / _timeout /
  _reset_wait / _reset_commit / _refuse_item); the consumer is tools/gen2_trade_oracles.py.

  1. HARNESS_ONLY_OVERLAY composition override. Production refuses an overlay ROM (lua/gen2/entry.lua admits
     only the clean catalog kind, asserts the clean profile sha1 twice, passes artifact_kind=nil). This file
     text-patches lua/gen2/entry.lua IN MEMORY (T.PATCHES, each fragment exactly once in the source) and serves
     that chunk to the unmodified lua/gen2/run.lua through a dofile interception scoped to the run.lua load.
     Only the published overlay sha1s (T.load_pins: data/gen2/overlay_provenance.json outputs, read at load
     and bound by its sha256 in the manifest; never hardcoded, the overlays get republished) are admitted, each only for
     its own title and only when the profile's overlay block names it. The patched graph reports qualification
     "HARNESS_ONLY_OVERLAY" (never "PHYSICAL_RECEIPTED": the U1/U2 receipts it re-validates are the CLEAN ones).
     Disclosure: TRADE_OVERRIDE <manifest json> (entry/run source sha256, the patches, the pins) and
     TRADE_ADMISSION {admission_scope, override_manifest_sha256 = sha256(that exact json text), ...}.
     Production JSON and source are unchanged.

  2. The native trade, normal buttons only. Both players: the `link` catch (Route 29, linked, native save),
     walk to the Cherrygrove #MON CENTER 2F (the U1f legs + SLINK_GEN2_TRADE_FACTS, tools/gen2_trade_facts.py),
     answering any phone call (the overlays' "first link" SLINK call: text + one waitbutton) and RUNning from
     any wild battle; stand below the trade receptionist facing Up; native save = TRADE_BASELINE; TRADE_READY;
     wait for TRADE_GO in the go-file. A (proposer) talks: intro text, yes/no "trade?" YES, the native party
     menu (PartyMenuSelect) onto the linked slot, "SLINK TRADE?" YES. B (responder) idles until its cartridge
     picks up the PROMPT (SlinkTradeDispatch) and answers "SLINK TRADE?" per case. B is never pressed during a
     wait (SlinkTradeWaitFrame exits on B) except A's disclosed decline/refuse cancel.

  MARKERS (JSON after the tag; frames are emu.framecount(); sites are overlay .sym {symbol, bank, address}):
    TRADE_OVERRIDE {...manifest}  TRADE_ADMISSION {admission_scope, overlay_sha1, base_sha1, title,
        override_manifest_sha256, trade_manifest_sha256, run_id}                      after CLIENT
    TRADE_BASELINE / TRADE_NATIVE_SAVE / TRADE_FINAL   immutable images: {frame, snapshot_path, snapshot_sha256,
        cartram_sha256, snapshot_bytes=32790, cartram_bytes=32768, kind}; BASELINE adds party[{species_marker,
        blob_hex(70)}] + dex {primary,backup}{caught_hex,seen_hex} read from the SAVED image, slot/count/key;
        NATIVE_SAVE (frame == TRADE_DONE.frame) adds capture_frame, flush_frame, save_entry_frame, flushed_matches;
        every image carries client_saves: TRADE_FINAL is a FLUSH (never an ordinary save), so on a traded side its
        client_saves equals the NATIVE_SAVE count (main ruling: no save between the native trade save and the final)
    TRADE_FORCED_SAVE   proposer only, exactly one (coordinator ruling after 9805ac1c): the image right after the
        receptionist's forced native save succeeded (TryQuickSave -> SlinkTradeEntry, which is reached only on a
        successful save). CartRAM captured at the SlinkTradeEntry exec, flushed at the frame boundary; same image
        fields + capture_frame, flush_frame, flushed_matches, client_saves (> the baseline's), save_completed_frame.
        The oracle compares the negative cases' A final against THIS image, byte-exact.
    TRADE_READY {frame, snapshot_sha256 (the baseline image), slot, key}
    TRADE_GO {frame, run_id}   (the runner writes "TRADE_GO" into the go-file after freezing both baselines and
        the server links; run_id is the admission manifest's)
    TRADE_ENTRY {frame, role, site}      the proposer's SlinkTradeEntry / the responder's fresh PROMPT pickup
    TRADE_OFFER {frame, site, pc, rom_bank, role, slot, count, token[4], generation, lease_hex, species_marker,
        blob_hex, incoming_species_marker?, incoming_blob_hex?}   proposer at SlinkTradeWaitAck (lease cmd OFFER),
        responder at SlinkTradePromptEntry (cmd PROMPT, gen ~= ack)
    TRADE_WAIT_APPLY {frame}   TRADE_APPLY_PICKUP {frame, site, pc, rom_bank, role, slot, lease_hex, own_blob_hex,
        incoming_blob_hex, incoming_species_marker}   TRADE_COMMIT_ENTRY {frame, site, slot(A), role(B), lease_hex}
    TRADE_PRE_REMOVE {frame, site, slot, cur_party_mon, live={domain,bank,spans[3]}, frozen={...}}
    TRADE_NATIVE_CALL {frame, symbol, bank, address}   (ordered; every hit after the baseline)
    TRADE_DONE {frame, lease_hex, result}   TRADE_EXIT {frame, lease_hex}   TRADE_RESET_ENTRY {frame}
    TRADE_RELOAD {frame, snapshot_sha256, cartram_sha256, party_keys[], dex {primary, backup}}   traded sides only,
        after TRADE_FINAL: a soft reset (RELOAD_CHORD) boots the flushed TRADE_FINAL image (CartRAM digest checked
        == TRADE_FINAL.cartram_sha256 first), CONTINUE (RELOADED, BOOTED's shape), read back WITHOUT saving. The
        game loads one copy into WRAM: dex.primary and dex.backup are both that WRAM readback (the oracle compares
        them to each decoded copy of TRADE_FINAL)
    TRADE_SAVE_RETURNED {frame, site, registers}   SlinkTradeCommit.cleanup with B=0: SaveAfterLinkTrade returned
    TRADE_RECOVERED {frame, text}   reset_commit A: the server settled the DONE-less side (watchdog + party
        evidence) and sent "Traded ..."; A's NATIVE_SAVE is then captured at SAVE_RETURNED, not at a DONE
    TRADE_ANSWER {frame, answer, after}  TRADE_CANCEL {frame, button}
    TRADE_CONTROL {kind, before={frame, site, registers, lease_hex, slot?}, after={frame, site, registers, lease_hex}}
        (refinement 2: the negative case's trigger, proven on the side that triggers it)
          decline     responder: SlinkTradePublishDone A=1 on the PROMPT lease -> SlinkTradeExit, lease DONE/RELEASE
                      with result 1
          timeout     proposer: the first SlinkTradeWaitApply.wait (BC=T.APPLY_WAIT) -> SlinkTradeExit with BC=0,
                      >= T.APPLY_WAIT frames later, before any APPLY
          reset_wait  proposer: Reset while pre-APPLY -> StartTitleScreen with the 16-byte lease zeroed
          reset_commit proposer: adds commit = its TRADE_COMMIT_ENTRY; Reset after SlinkTradeCommit (after the
                      native save returned, before DONE) -> StartTitleScreen with the lease zeroed
          d3          proposer: SlinkTradeItemAllowed with A = the baseline slot held item -> SlinkTradeExit
                      (the cartridge refuses its own selected mon at the query stage: no offer; the peer
                      never has a visit, visit_state "none")
    CHORD {frame, frames}  RESET_SEEN {frame, delta}  REBOOTED {...BOOTED}   PHONE {frame, text}
    TRADE_STACK {domain, stack_bank, stack_start, stack_end, armed_count, hook_failures, phases[4]}
    TRADE_HOOK_ERROR {text}   (any hook fault; the verdict refuses it)
    HARNESS_WRITE {frame, domain="WRAM", bank, address, symbol, wram_offset, bytes_before, bytes_after, purpose, ...}
        O-31 (owner, "Test-only setup"), the ONLY writes, each disclosed and listed in the receipt's
        harness_write_scopes; production is unchanged:
          d3_mail_item          refuse_item A: after the link, before TRADE_BASELINE, the offered linked mon's held
                                item byte (wPartyMon1 + slot*48 + MON_ITEM) := FLOWER_MAIL. SlinkTradeItemAllowed is a
                                pure item-id table lookup (patch/gen2/src/trade_items.asm, $9E -> 0), so no mail
                                record is needed; the native CheckOwnSlot refuses it
          trade_evolve_species  trade_evolve A: at StartBattle of the first Route 29 wild battle (after
                                ChooseWildEncounter stored it, before StartBattle reads it), wTempWildMonSpecies :=
                                HAUNTER; the catch, capture site, link and key are then all native
    RECEIPT {schema "gen2-duo-trade-v1", case, variant, outcome, ...}   PASS only
--]]
local T = {}
T.SCOPE = "HARNESS_ONLY_OVERLAY"
T.SCHEMA = "gen2-duo-trade-v1"
T.OVERRIDE_SCHEMA = "gen2-duo-overlay-override-v1"
-- The published overlays (d09e76c1; data/gen2/overlay_provenance.json outputs.*.sha1, profile overlay blocks).
T.OVERLAY_SHA1 = {}   -- filled by T.load_pins from the published provenance
T.PROVENANCE = "data/gen2/overlay_provenance.json"
-- Mail ids, identical in the three pinned packs (data/games/gen2_*/items.json mail_ids; the unit tests pin it):
-- an offered mon holding one can only come from the disclosed D3 plant.
T.MAIL = {[0x9E]=true}
for id = 0xB5, 0xBD do T.MAIL[id] = true end
T.CART, T.SAVERAM = 0x8000, 0x8000 + 22
T.LEASE_OFF = 14                              -- slink_abi.inc SLINK_OFS_TRADE_LEASE
T.CMD = {query=1, offer=2, prompt=3, apply=5, done=7, release=8}
T.CHORD = {A=true, B=true, Select=true, Start=true}
T.CHORD_FRAMES = 4                            -- scenario_gen2_soft_reset.lua S.CHORD_FRAMES
T.PHASES = {"wait", "trade_animation", "evolution_animation", "native_save"}
T.MARGIN = 32
T.HOLD = 12
-- ponytail: live bounds, not measured; raise if a lane needs longer.
T.WALK = {max_frames=40000, max_phase_frames=20000}
T.VISIT_FRAMES = 30000
T.TALK_RETRY = 180
T.APPLY_WAIT = 3600                           -- SLINK_TRADE_APPLY_FRAMES (trade_service.asm, 67143736; a unit test pins it)
T.CHORD_AFTER = 120                           -- frames into the held wait / the animation before the chord
T.RESET_FRAMES = 120
T.PARTNER_FRAMES = 54000
T.GO_FRAMES = 54000
T.SETTLE_FRAMES = 120
T.RECOVERY_FRAMES = 432000                    -- the lane's watchdog bound (2400 s), Codex 1ac09296
T.DECLINED = "Your partner declined the trade."   -- server/state.py _handle_menu_result
T.REGIONS = {
    crystal = {{"PlayerData", "wPlayerData", "wPlayerDataEnd"}, {"CurMapData", "wCurMapData", "wCurMapDataEnd"},
               {"PokemonData", "wPokemonData", "wPokemonDataEnd"}},
    gold = {{"PlayerData1", "wPlayerData1", "wPlayerData1End"}, {"PlayerData2", "wPlayerData2", "wPlayerData2End"},
            {"PlayerData3", "wPlayerData3", "wPlayerData3End"}, {"CurMapData", "wCurMapData", "wCurMapDataEnd"},
            {"PokemonData", "wPokemonData", "wPokemonDataEnd"}},
}
T.REGIONS.silver = T.REGIONS.gold

local fmt = string.format
local function integer(v, lo, hi) return type(v) == "number" and v % 1 == 0 and v >= lo and v <= hi end
local function hex(bytes, first, last)
    local out = {}
    for i = first or 1, last or #bytes do out[#out + 1] = fmt("%02x", bytes[i]) end
    return table.concat(out)
end
T.hex = hex

-- ── 1. the composition override (pure parts first) ──────────────────────────────────────────────
T.PATCHES = {
    {id="catalog", from='for _, row in ipairs(assert(data.admission.artifacts, "artifact catalog required")) do',
     to='for _, row in ipairs(SLINK_HARNESS.catalog(title, profile, data.admission.artifacts)) do'},
    {id="kind", from='if mode == "sha1" and candidate.row.kind == "clean" then return "clean" end',
     to='if mode == "sha1" and SLINK_HARNESS.overlay(candidate.title, candidate.row) then return "overlay" end'},
    {id="compose_hash", from='assert(Admission.sha1(read_rom, size) == profile.rom_sha1, "candidate ROM hash mismatch")',
     to='assert(Admission.sha1(read_rom, size) == SLINK_HARNESS.rom_sha1(title, profile), "candidate ROM hash mismatch")'},
    {id="final_hash", from='and Admission.sha1(read_rom, size) == profile.rom_sha1',
     to='and Admission.sha1(read_rom, size) == SLINK_HARNESS.rom_sha1(title, profile)'},
    {id="artifact_kind", from='artifact_kind=(not production) and deps.artifact_kind or nil,',
     to='artifact_kind=(not production) and deps.artifact_kind or "overlay",'},
    {id="client_rom_sha1", from='rom_sha1=profile.rom_sha1, log=deps.log,',
     to='rom_sha1=SLINK_HARNESS.rom_sha1(title, profile), log=deps.log,'},
    {id="qualification", from='qualification=production and "PHYSICAL_RECEIPTED" or "SOURCE_MODEL_CANDIDATE"',
     to='qualification=production and "HARNESS_ONLY_OVERLAY" or "SOURCE_MODEL_CANDIDATE"'},
}
T.PREFIX = "local SLINK_HARNESS = ...; "     -- same line as the source's first line: line numbers unchanged

-- Pure: source text -> patched text, or nil + why. Every fragment must occur exactly once.
function T.patch_entry(text)
    local out = text
    for _, p in ipairs(T.PATCHES) do
        local first = text:find(p.from, 1, true)
        if not first or text:find(p.from, first + 1, true) then
            return nil, "entry.lua fragment " .. p.id .. (first and " occurs twice" or " not found")
        end
        local at = out:find(p.from, 1, true)
        out = out:sub(1, at - 1) .. p.to .. out:sub(at + #p.from)
    end
    return T.PREFIX .. out
end

-- The published overlay pins: {title -> sha1} from outputs[*].slink_title/sha1; returns the file's sha256.
function T.load_pins(root, json, sha256_text)
    local raw = T.read(root .. "/" .. T.PROVENANCE)
    local doc = assert(json.decode(raw, {items=1000000}), "overlay provenance unreadable")
    assert(doc.schema == "gen2-overlay-provenance-v1", "unexpected overlay provenance schema")
    local pins = {}
    for _, out in pairs(doc.outputs) do
        if type(out) == "table" and type(out.slink_title) == "string" and type(out.sha1) == "string" then
            assert(pins[out.slink_title] == nil, "two published overlays for " .. out.slink_title)
            pins[out.slink_title] = out.sha1:lower()
        end
    end
    T.OVERLAY_SHA1 = pins
    T.provenance_sha256 = sha256_text and sha256_text(raw) or nil
    return pins
end

-- The harness seam the patched chunk receives as `...`. Exact-hash: only T.OVERLAY_SHA1[title], only when the
-- profile's overlay block names that sha1 over the profile's own clean base.
function T.harness()
    local H = {}
    local function pinned(title, profile)
        local sha = T.OVERLAY_SHA1[title]
        local ov = type(profile) == "table" and profile.overlay or nil
        return sha ~= nil and type(ov) == "table" and ov.rom_sha1 == sha and ov.base_sha1 == profile.rom_sha1 and sha or nil
    end
    -- The catalog's own BUILT overlay row (selection FUTURE in production) over this profile's clean base; the
    -- harness grants only its selection. Nothing else of the catalog reaches the admission engine.
    function H.catalog(title, profile, rows)
        local sha = pinned(title, profile)
        if not sha then return {} end
        for _, row in ipairs(rows or {}) do
            if row.kind == "overlay" and row.sha1 == sha and row.base_sha1 == profile.rom_sha1 and row.status == "BUILT" then
                local copy = {}
                for k, v in pairs(row) do copy[k] = v end
                copy.selection, copy.harness, copy.production_selection = "SELECTED", T.SCOPE, row.selection
                return {copy}
            end
        end
        return {}
    end
    function H.overlay(title, row)
        return type(row) == "table" and row.kind == "overlay" and row.harness == T.SCOPE and row.sha1 == T.OVERLAY_SHA1[title]
    end
    function H.rom_sha1(title, profile)
        return assert(pinned(title, profile), "HARNESS_ONLY_OVERLAY: no pinned overlay for " .. tostring(title))
    end
    return H
end

-- Pure: the disclosed manifest (json.encode sorts keys, so its text is canonical).
function T.manifest(sha256_text, entry_text, run_text, title, running_sha1)
    local patches = {}
    for i, p in ipairs(T.PATCHES) do patches[i] = {id=p.id, from=p.from, to=p.to} end
    return {schema=T.OVERRIDE_SCHEMA, admission_scope=T.SCOPE, prefix=T.PREFIX, patches=patches,
            entry={path="lua/gen2/entry.lua", sha256=sha256_text(entry_text)},
            run={path="lua/gen2/run.lua", sha256=sha256_text(run_text)},
            overlay_sha1=T.OVERLAY_SHA1, provenance={path=T.PROVENANCE, sha256=T.provenance_sha256},
            title=title, running_sha1=running_sha1,
            dofile_scope="lua/gen2/run.lua load only"}
end

local function read(path)
    local f = assert(io.open(path, "rb"), "cannot open " .. path)
    local text = f:read("a")
    f:close()
    return text
end
T.read = read

-- The scripted-gate view over the overlay (lua/tests/gen2_panel_gate.lua's binding): the running ROM must be the
-- pinned overlay of SLINK_GEN2_TITLE; the clean facts then bind to its base (the overlay moves no RAM symbol and
-- none of the UI/observer sites: each site's bytes are still re-validated at registration).
function T.context_api(api, getenv)
    local title = getenv("SLINK_GEN2_TITLE")
    local root = assert(getenv("SLINK_ROOT"), "SLINK_ROOT missing")
    T.load_pins(root, dofile(root .. "/lua/json_codec.lua"))
    local want = T.OVERLAY_SHA1[title or ""]
    assert(want, "no pinned overlay for SLINK_GEN2_TITLE " .. tostring(title))
    local running = tostring(api.romhash()):lower()
    assert(running == want, fmt("running ROM %s is not the pinned %s overlay %s", running, tostring(title), want))
    local env_ov = getenv("SLINK_GEN2_OVERLAY_SHA1")
    assert(env_ov == nil or env_ov:lower() == want, "SLINK_GEN2_OVERLAY_SHA1 differs from the pin")
    local base = assert(getenv("SLINK_GEN2_ROM_SHA1"), "SLINK_GEN2_ROM_SHA1 missing"):lower()
    T.running = {title=title, overlay_sha1=want, base_sha1=base}
    return setmetatable({romhash=function() return base end}, {__index=api})
end

-- The unmodified run.lua, served the patched entry.lua. Returns client, parts (run.lua's globals).
function T.start_production(root, SG, json)
    local sha = function(text) return SG.sha256(function(i) return text:byte(i + 1) end, #text) end
    T.load_pins(root, json, sha)
    local entry_path, run_path = root .. "/lua/gen2/entry.lua", root .. "/lua/gen2/run.lua"
    local entry_text, run_text = read(entry_path), read(run_path)
    local patched = assert(T.patch_entry(entry_text))
    local chunk = assert(load(patched, "@" .. entry_path, "t", _G))
    local Entry = chunk(T.harness())
    assert(type(Entry) == "table" and type(Entry.build) == "function", "patched entry.lua returned no Entry")
    local running = T.running or {}
    local manifest = T.manifest(sha, entry_text, run_text, running.title, running.overlay_sha1)
    T.manifest_text = assert(json.encode(manifest))
    T.manifest_sha256 = sha(T.manifest_text)
    local real = dofile
    dofile = function(path, ...)
        if type(path) == "string" and path:gsub("\\", "/"):sub(-#"lua/gen2/entry.lua") == "lua/gen2/entry.lua" then
            return Entry
        end
        return real(path, ...)
    end
    local ok, err = pcall(real, run_path)
    dofile = real
    if not ok then error(err, 0) end
    return SLINK_GEN2_CLIENT, SLINK_GEN2_PARTS
end

-- ── 2. facts, saved-image reads (pure) ──────────────────────────────────────────────────────────
-- Pure: flat CartRAM offset of `sym` (n bytes) inside the saved copy ("primary" | "backup").
function T.saved_offset(profile, title, copy, sym, n)
    local ram, banks = profile.ram, profile.sram_bank
    local addr = assert(ram[sym], "profile lacks " .. sym)
    for _, r in ipairs(T.REGIONS[title]) do
        local base, stop = ram[r[2]], ram[r[3]]
        if base and stop and addr >= base and addr + n <= stop then
            local s = (copy == "primary" and "s" or "sBackup") .. r[1]
            return banks[s] * 0x2000 + ram[s] - 0xA000 + addr - base
        end
    end
    error("saved symbol outside all save regions: " .. sym)
end
-- Pure: the saved party [{species_marker, blob_hex}] and dex {primary, backup} from a SaveRAM string.
function T.saved_party(saved, profile, title, copy)
    local function at(sym, off, n)
        local o = T.saved_offset(profile, title, copy or "primary", sym, off + n) + off
        local out = {}
        for i = 1, n do out[i] = saved:byte(o + i) end
        return out
    end
    local c = profile.constants
    local L, N, M = c.PARTYMON_STRUCT_LENGTH, c.NAME_LENGTH, c.MON_NAME_LENGTH
    local count = at("wPartyCount", 0, 1)[1]
    assert(count <= c.PARTY_LENGTH, "saved party count out of range")
    local species, party = at("wPartySpecies", 0, count), {}
    for i = 0, count - 1 do
        party[#party + 1] = {species_marker=species[i + 1],
            blob_hex=hex(at("wPartyMon1", i * L, L)) .. hex(at("wPartyMonOTs", i * N, N)) .. hex(at("wPartyMonNicknames", i * M, M))}
    end
    return party
end
function T.saved_dex(saved, profile, title)
    local out = {}
    for _, copy in ipairs({"primary", "backup"}) do
        local row = {}
        for kind, sym in pairs({caught_hex="wPokedexCaught", seen_hex="wPokedexSeen"}) do
            local o, bytes = T.saved_offset(profile, title, copy, sym, 32), {}
            for i = 1, 32 do bytes[i] = saved:byte(o + i) end
            row[kind] = hex(bytes)
        end
        out[copy] = row
    end
    return out
end

-- Before SG.hooks(ctx): the trade facts, the party-menu origin and the two yes/no anchors.
function T.prepare(ctx, SG, getenv)
    local tf = assert(ctx.json.decode(assert(getenv("SLINK_GEN2_TRADE_FACTS"), "SLINK_GEN2_TRADE_FACTS missing"),
                                      {items=1000000}))
    assert(tf.schema == "gen2-trade-facts-v1" and tf.title == ctx.env.title, "trade facts belong to another title")
    assert(T.running and tf.overlay_sha1 == T.running.overlay_sha1 and tf.base_sha1 == ctx.env.rom_sha1,
           "trade facts belong to another overlay")
    ctx.trade_facts = tf
    ctx.facts.ui_origins.trade_party = assert(ctx.u1.faint_ui and ctx.u1.faint_ui.battle_party,
                                              "SLINK_GEN2_U1_FACTS lacks faint_ui.battle_party (PartyMenuSelect)")
    for prompt, anchors in pairs(tf.prompts) do ctx.prompts[prompt] = anchors end
end

-- ── 3. pure drivers ─────────────────────────────────────────────────────────────────────────────
local TEXT = {text=true, prompt_button=true, wait_button=true}
local function on(point, map) return point.map_group == map.map_group and point.map_number == map.map_number end

local function presser(self)
    local held, left, release = nil, 0, false
    local p = {}
    function p.press(button)
        release, held, left = true, button, T.HOLD - 1
        return {[button]=true}, self.phase
    end
    function p.busy()
        if left > 0 then left = left - 1; return {[held]=true}, self.phase end
        if release then release = false; return {}, self.phase end
    end
    function p.choose(ui, wanted)
        if type(ui.items) ~= "table" or not integer(ui.cursor, 1, #ui.items) or ui.columns ~= 1 then
            return nil, "source menu geometry unavailable"
        end
        local target
        for i, label in ipairs(ui.items) do
            if type(label) == "string" and label:upper() == wanted then target = i end
        end
        if not target then return nil, "required native menu item missing: " .. wanted end
        if target == ui.cursor then return p.press("A") end
        return p.press(target > ui.cursor and "Down" or "Up")
    end
    return p
end

-- Pure point -> buttons, phase: walk the legs to the receptionist stand, facing Up ("at-desk" terminal).
-- Phone calls and every other text wait take A; a wild battle is RUN from (battle_menu RUN, move_menu B).
function T.travel_driver(PI, maps, legs, stand)
    local self = {terminal="at-desk", phase="to-desk"}
    local p, waited = presser(self), 0
    local function walk(map, point, goals)
        local button, why = PI.step_toward(map, point, goals)
        if not button then button = PI.step_toward(map, {x=point.x, y=point.y, can_step=point.can_step}, goals) end
        if not button then
            local open = {x=point.x, y=point.y, can_step={Up=true, Down=true, Left=true, Right=true}}
            if PI.step_toward(map, open, goals) and waited < PI.WAIT_FRAMES then
                waited = waited + 1
                return {}, self.phase
            end
            return nil, why
        end
        waited = 0
        if button == "arrived" then return nil, "arrived" end
        return {[button]=true}, self.phase
    end
    function self.step(point)
        if type(point) ~= "table" then return nil, "observation missing" end
        local busy, phase = p.busy()
        if busy then return busy, phase end
        if self.phase == self.terminal then return {}, self.phase end
        local ui = point.ui
        if integer(point.battle_mode, 1, 255) then
            if ui == nil or point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "battle_menu" then
                if point.battle_mode ~= 1 then return nil, "trainer battle on the way to the Center" end
                if type(ui.items) ~= "table" then return {}, self.phase end
                for i, label in ipairs(ui.items) do
                    if label:upper() == "RUN" then
                        if i == ui.cursor then return p.press("A") end
                        local tx, cx = (i - 1) % 2, (ui.cursor - 1) % 2
                        if tx ~= cx then return p.press(tx > cx and "Right" or "Left") end
                        return p.press(i > ui.cursor and "Down" or "Up")
                    end
                end
                return nil, "battle menu without RUN"
            end
            if ui.kind == "move_menu" then return p.press("B") end
            if TEXT[ui.kind] then return p.press("A") end
            return nil, "UI is not valid in a battle on the way: " .. tostring(ui.kind)
        end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if TEXT[ui.kind] then return p.press("A") end   -- the SLINK phone call, NPC text
            return nil, "UI is not valid while walking to the Center: " .. tostring(ui.kind) .. "/" .. tostring(ui.prompt)
        end
        if point.overworld_ready ~= true then return {}, self.phase end
        for name, leg in pairs(legs) do
            local map = maps[name]
            if map and on(point, map) then
                if leg.kind == "edge" then
                    local buttons, why = walk(map, point, leg.exits)
                    if why == "arrived" then return {[leg.side]=true}, self.phase end
                    return buttons, why
                end
                if leg.kind == "warp" then
                    local buttons, why = walk(map, point, {leg.tile})
                    if why == "arrived" then
                        if leg.carpet then return p.press(leg.carpet) end
                        return {}, self.phase   -- a stair/door warp fires on arrival
                    end
                    return buttons, why
                end
                if leg.kind == "stand" then
                    local buttons, why = walk(map, point, {stand})
                    if why ~= "arrived" then return buttons, why end
                    if point.facing ~= "Up" then return p.press("Up") end
                    self.phase = self.terminal
                    return {}, self.phase
                end
            end
        end
        return nil, fmt("map %s:%s is not on the Center plan", tostring(point.map_group), tostring(point.map_number))
    end
    return self
end

-- Pure point -> buttons, phase: one trade visit. point.trade = {entered, exited, waiting, committing}; point.x/y,
-- facing, party_cursor (trade_party), ui. opts: role "proposer"|"responder", slot, stand,
-- answer(point) -> "YES"|"NO"|nil (responder; nil holds the yes/no open), cancel(point) -> bool (proposer: one B
-- press inside the held wait), chord(point) -> bool (one soft-reset chord; terminal right after it),
-- on_answer(answer), on_cancel(), on_chord().
function T.visit_driver(opts)
    local self = {terminal="visited", phase=opts.role == "proposer" and "talk" or "idle"}
    local p = presser(self)
    local talked_at, cancelled, chord_left, chorded, answered = nil, false, 0, false, nil
    function self.step(point, frame)
        if type(point) ~= "table" then return nil, "observation missing" end
        if chord_left > 0 then
            chord_left = chord_left - 1
            if chord_left == 0 then self.phase = self.terminal end
            return T.CHORD, "chord"
        end
        if self.phase == self.terminal then return {}, self.phase end
        local tr = point.trade or {}
        -- the chord overrides a held press: its window (after the save returned, before DONE) is a few frames
        if opts.chord and not chorded and opts.chord(point) then
            chorded, chord_left = true, T.CHORD_FRAMES - 1
            if opts.on_chord then opts.on_chord() end
            return T.CHORD, "chord"
        end
        local busy, phase = p.busy()
        if busy then return busy, phase end
        if tr.exited and point.overworld_ready == true then
            self.phase = self.terminal
            return {}, self.phase
        end
        if opts.cancel and not cancelled and tr.waiting and opts.cancel(point) then
            cancelled = true
            if opts.on_cancel then opts.on_cancel() end
            return p.press("B")
        end
        local ui = point.ui
        if integer(point.battle_mode, 1, 255) then return nil, "a battle started during the trade visit" end
        if ui ~= nil then
            if point.input_ready ~= true then return {}, self.phase end
            if ui.kind == "trade_party" then
                if opts.role ~= "proposer" then return nil, "party menu on the responder" end
                if not integer(point.party_cursor, 0, 5) then return {}, self.phase end
                if point.party_cursor == opts.slot then return p.press("A") end
                return p.press(point.party_cursor < opts.slot and "Down" or "Up")
            end
            if ui.kind == "yes_no" then
                -- 9805ac1c: both roles make the native forced pre-trade save (must_save / trade_save, then the
                -- native overwrite yes/no of an existing file); the responder decides at trade_offer
                local role, prompt = opts.role, ui.prompt
                if role == "proposer" and (prompt == "trade_intro" or prompt == "must_save" or prompt == "slink_trade") then
                    return p.choose(ui, "YES")
                end
                if prompt == "save_overwrite" and (role == "proposer" or answered == "YES") then return p.choose(ui, "YES") end
                if role == "responder" and prompt == "trade_save" and answered == "YES" then return p.choose(ui, "YES") end
                if role == "responder" and prompt == "trade_offer" and answered == nil then
                    local answer = opts.answer(point)
                    if answer == nil then return {}, "hold" end
                    answered = answer
                    if opts.on_answer then opts.on_answer(answer) end
                    return p.choose(ui, answer)
                end
                return nil, "unmapped yes/no during the trade visit: " .. tostring(prompt) .. " (" .. tostring(role) .. ")"
            end
            if TEXT[ui.kind] then return p.press("A") end
            return nil, "UI is not valid during the trade visit: " .. tostring(ui.kind)
        end
        if opts.role == "proposer" and not tr.entered and point.overworld_ready == true then
            if talked_at and frame - talked_at < T.TALK_RETRY then return {}, self.phase end
            if point.x ~= opts.stand.x or point.y ~= opts.stand.y then return nil, "the proposer left the desk" end
            if point.facing ~= "Up" then return p.press("Up") end
            talked_at = frame
            return p.press("A")
        end
        return {}, self.phase
    end
    return self
end

-- ── 4. the per-instance attachment (emulator side) ──────────────────────────────────────────────
-- e = {h, ctx, SG, F, api, D, host, gen2, parts, log, jlog, json}. Adds h.trade.
function T.attach(e)
    local h, ctx, SG, F, D, json, jlog = e.h, e.ctx, e.SG, e.F, e.D, e.json, e.jlog
    local api = ctx.api
    local tf = ctx.trade_facts
    local frame = e.api.framecount
    local LEASE = tf.ram.wSlinkMailbox.addr + T.LEASE_OFF
    local hrom = ctx.profile.hram.hROMBank
    local bottom, top, stack_bank = tf.ram.wStackBottom.addr, tf.ram.wStackTop.addr, tf.ram.wStackBottom.bank
    local c = ctx.profile.constants
    local L, N, M = c.PARTYMON_STRUCT_LENGTH, c.NAME_LENGTH, c.MON_NAME_LENGTH
    local function bus(addr, n) return api.read_range(addr, n, "System Bus") end
    local function u8(addr) return api.read_u8(addr, "System Bus") end
    local function rom_bank() return u8(hrom) end
    local function lease() return bus(LEASE, 16) end
    local function site(name) local s = tf.code[name] return {symbol=name, bank=s.bank, address=s.addr} end
    local function sha(text) return SG.sha256(function(i) return text:byte(i + 1) end, #text) end

    -- the runner's frozen admission manifest (tools/gen2_trade_lane.py): run_id and this side's overlay pin
    -- (SLINK_DUO.trade_manifest/_sha256, else the same pair from the environment)
    local mpath = assert(D.trade_manifest or os.getenv("SLINK_GEN2_TRADE_MANIFEST"), "trade manifest path missing")
    local mtext = read(mpath)
    local msha = sha(mtext)
    assert(msha == tostring(D.trade_manifest_sha256 or os.getenv("SLINK_GEN2_TRADE_MANIFEST_SHA256")):lower(),
           "trade manifest sha256 differs")
    assert(D.trade_case == nil or D.trade_case == D.scenario or D.trade_case == "gen2_trade_" .. tostring(e.case),
           "SLINK_DUO.trade_case differs from the scenario")
    local manifest = assert(json.decode(mtext))
    local mine = manifest.players and manifest.players[D.player]
    assert(manifest.evidence_class == T.SCOPE and mine and mine.rom_sha1 == T.running.overlay_sha1
           and mine.title == ctx.env.title and mine.artifact_kind == "overlay", "trade manifest does not admit this side")
    e.log("TRADE_OVERRIDE " .. T.manifest_text)
    jlog("TRADE_ADMISSION", {admission_scope=T.SCOPE, overlay_sha1=T.running.overlay_sha1, base_sha1=T.running.base_sha1,
        title=ctx.env.title, override_manifest_sha256=T.manifest_sha256, trade_manifest_sha256=msha,
        run_id=manifest.run_id, qualification=tostring(e.parts.qualification)})

    local st = {armed=false, errors={}, exec={}, writes={}, hit={}, disarm={}, rearm=false, unarm=false,
                armed_count=0, hook_failures=0, current=nil, phase={}, calls={}, logs={}}
    for _, name in ipairs(T.PHASES) do st.phase[name] = {phase=name, visited=false, samples={}} end
    h.trade = {state=st, facts=tf, manifest=manifest, manifest_sha256=msha, title=ctx.env.title, variant=D.variant}
    local function fault(text)
        st.errors[#st.errors + 1] = text
        jlog("TRADE_HOOK_ERROR", {text=text})
    end

    -- client log lines (run.lua passes log = console.log at call time): refusals and phone deliveries
    local _console = console.log
    console.log = function(line)
        local s = tostring(line)
        if s:find("[SLink-gen2]", 1, true) and st.armed then
            st.logs[#st.logs + 1] = {frame=frame(), text=s}
            if s:find("phone: call", 1, true) then jlog("PHONE", {frame=frame(), text=s}) end
        end
        return _console(line)
    end
    -- every trade command the client receives (after duo main's RX logging)
    st.rx = {}
    local _handle = e.gen2.handle_command
    e.gen2.handle_command = function(self, cmd)
        if type(cmd) == "table" then st.rx[#st.rx + 1] = {frame=frame(), cmd=cmd.cmd, token=cmd.token, text=cmd.text} end
        return _handle(self, cmd)
    end
    function h.trade.rx_text(text)
        for _, r in ipairs(st.rx) do if r.cmd == "msgbox" and r.text == text then return true end end
        return false
    end

    -- phases (stack coverage)
    local function phase_start(name, at)
        local ph = st.phase[name]
        if ph.visited then return end
        ph.visited, ph.start, ph.hit = true, {frame=frame(), site=site(at)}, {}
        st.current = ph
    end
    local function phase_end(name, at)
        local ph = st.phase[name]
        if not ph.visited or ph["end"] then return end
        ph["end"] = {frame=frame(), site=site(at)}
        if st.current == ph then st.current = nil end
    end
    local function open_phases_end(at)
        for _, name in ipairs(T.PHASES) do phase_end(name, at) end
    end

    local function party_blob(slot)
        return hex(bus(tf.ram.wPartyMon1.addr + slot * L, L)) .. hex(bus(tf.ram.wPartyMonOTs.addr + slot * N, N))
               .. hex(bus(tf.ram.wPartyMonNicknames.addr + slot * M, M))
    end
    local function ot_blob(slot)
        return hex(bus(tf.ram.wOTPartyMon1.addr + slot * L, L)) .. hex(bus(tf.ram.wOTPartyMonOTs.addr + slot * N, N))
               .. hex(bus(tf.ram.wOTPartyMonNicknames.addr + slot * M, M))
    end
    local function spans(names, slot)
        local out = {}
        for i, name in ipairs(names) do
            local size = i == 1 and L or (i == 2 and N or M)
            local addr = tf.ram[name].addr + slot * size
            out[i] = {symbol=name, address=addr, hex=hex(bus(addr, size))}
        end
        local svbk = u8(0xFF70) % 8
        return {domain="System Bus", bank=svbk == 0 and 1 or svbk, spans=json.array(out)}
    end
    local function token(l) return json.array({l[13], l[14], l[15], l[16]}) end
    local function cpu(row, name)
        row.frame, row.site, row.pc, row.rom_bank = frame(), site(name), api.register("PC"), rom_bank()
        return row
    end
    local function registers()
        local out = {}
        for _, r in ipairs({"A", "F", "B", "C", "D", "E", "H", "L", "SP", "PC"}) do
            local ok, value = pcall(api.register, r)
            out[r] = ok and value or json.null
        end
        return out
    end
    local function control_point(name, slot)
        return {frame=frame(), site=site(name), registers=registers(), lease_hex=hex(lease()), slot=slot}
    end
    local function control(kind, before, after, commit)
        if st.control_logged or st.control_kind ~= kind or not before then return end
        st.control_logged = true
        jlog("TRADE_CONTROL", {kind=kind, before=before, after=after, commit=commit})
    end
    local function call(name)
        local row = {frame=frame(), symbol=name, bank=tf.code[name].bank, address=tf.code[name].addr}
        st.calls[#st.calls + 1] = row
        jlog("TRADE_NATIVE_CALL", row)
    end

    -- O-31: the only harness writes. WRAM domain at the symbol's named bank; read back; disclosed.
    st.harness_writes = {}
    local function harness_write(symbol, addr, bank, bytes, purpose, extra)
        local off = SG.wram_offset(bank, addr, #bytes)
        local before = api.read_range(off, #bytes, "WRAM")
        for i, b in ipairs(bytes) do api.write_u8(off + i - 1, b, "WRAM") end
        local after = api.read_range(off, #bytes, "WRAM")
        local row = {frame=frame(), domain="WRAM", bank=bank, address=addr, symbol=symbol, wram_offset=off,
                     bytes_before=hex(before), bytes_after=hex(after), purpose=purpose}
        for k, val in pairs(extra or {}) do row[k] = val end
        st.harness_writes[#st.harness_writes + 1] = {purpose=purpose, domain="WRAM", symbol=symbol, address=addr, bank=bank}
        jlog("HARNESS_WRITE", row)
        assert(hex(after) == hex(bytes), purpose .. ": the harness write did not read back")
        return row
    end
    local plant = tf.plants
    function h.trade.plant_mail(slot)
        local r = tf.ram.wPartyMon1
        return harness_write("wPartyMon1Item", r.addr + slot * L + c.MON_ITEM, r.bank, {plant.mail_item.id}, "d3_mail_item",
                             {slot=slot, item=plant.mail_item.name})
    end
    function h.trade.arm_species_plant() st.plant_species = {map=ctx.facts.maps.Route29} end
    local PRE = {}
    function PRE.StartBattle()
        local want = st.plant_species
        if not want or want.done then return end
        local r = tf.ram
        if u8(r.wOtherTrainerClass.addr) ~= 0 or u8(r.wBattleMode.addr) ~= 1 or u8(r.wBattleType.addr) ~= 0
           or u8(r.wMapGroup.addr) ~= want.map.map_group or u8(r.wMapNumber.addr) ~= want.map.map_number then return end
        want.done = true
        harness_write("wTempWildMonSpecies", r.wTempWildMonSpecies.addr, r.wTempWildMonSpecies.bank,
                      {plant.evolve_species.id}, "trade_evolve_species", {species=plant.evolve_species.name,
                      evolves_to=plant.evolves_to.name, site=site("StartBattle")})
    end

    local H = {}
    function H.SlinkTradeEntry(name)
        if not st.forced then st.forced = {frame=frame(), cart=api.read_range(0, T.CART, "CartRAM")} end
        st.role, st.entry_frame = 0, frame()
        jlog("TRADE_ENTRY", {frame=frame(), role=0, site=site(name)})
        phase_start("wait", name)
    end
    function H.SlinkTradePromptEntry(name)
        local l = lease()
        if l[6] ~= T.CMD.prompt or l[7] == l[8] or st.offer then return end
        st.role, st.entry_frame = 1, frame()
        jlog("TRADE_ENTRY", {frame=frame(), role=1, site=site(name)})
        phase_start("wait", name)
        local slot = l[10]
        st.offer = cpu({role=1, slot=slot, count=u8(tf.ram.wPartyCount.addr), token=token(l), generation=l[7],
            lease_hex=hex(l), species_marker=u8(tf.ram.wPartySpecies.addr + slot), blob_hex=party_blob(slot),
            incoming_species_marker=u8(tf.ram.wOTPartySpecies.addr), incoming_blob_hex=ot_blob(0)}, name)
        jlog("TRADE_OFFER", st.offer)
    end
    function H.SlinkTradeWaitAck(name)
        local l = lease()
        if l[6] ~= T.CMD.offer or st.offer then return end
        local slot = l[10]
        st.offer = cpu({role=0, slot=slot, count=u8(tf.ram.wPartyCount.addr), token=token(l), generation=l[7],
            lease_hex=hex(l), species_marker=u8(tf.ram.wPartySpecies.addr + slot), blob_hex=party_blob(slot)}, name)
        jlog("TRADE_OFFER", st.offer)
    end
    function H.SlinkTradeWaitApply()
        if st.wait_apply_frame then return end
        st.wait_apply_frame = frame()
        jlog("TRADE_WAIT_APPLY", {frame=frame()})
    end
    function H.SlinkTradeApplyPickup(name)
        local l = lease()
        local slot = l[10]
        st.pickup = cpu({role=st.role, slot=slot, lease_hex=hex(l), own_blob_hex=party_blob(slot),
            incoming_species_marker=u8(tf.ram.wOTPartySpecies.addr), incoming_blob_hex=ot_blob(0)}, name)
        jlog("TRADE_APPLY_PICKUP", st.pickup)
    end
    function H.SlinkTradeCommit(name)
        st.committing = true
        phase_end("wait", name)
        st.commit_entry = {frame=frame(), site=site(name), slot=api.register("A"), role=api.register("B"),
                           lease_hex=hex(lease())}
        jlog("TRADE_COMMIT_ENTRY", st.commit_entry)
    end
    function H.RemoveMonFromPartyOrBox(name)
        call(name)
        if st.committing and not st.pre_remove then
            local slot = st.offer and st.offer.slot or u8(tf.ram.wCurPartyMon.addr)
            st.pre_remove = {frame=frame(), site=site(name), slot=slot, cur_party_mon=u8(tf.ram.wCurPartyMon.addr),
                live=spans({"wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames"}, slot),
                frozen=spans({"wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames"}, 1)}
            jlog("TRADE_PRE_REMOVE", st.pre_remove)
        end
    end
    function H.TradeAnimation(name) call(name); if st.committing then phase_start("trade_animation", name) end end
    H.TradeAnimationPlayer2 = H.TradeAnimation
    function H.AddTempmonToParty(name) call(name); phase_end("trade_animation", name) end
    function H.EvolvePokemon(name) call(name) end
    function H.EvolutionAnimation(name) if st.committing then phase_start("evolution_animation", name) end end
    function H.SaveAfterLinkTrade(name)
        call(name)
        st.save_entry_frame = frame()
        phase_end("evolution_animation", name)
        if st.committing then phase_start("native_save", name) end
    end
    function H.SlinkTradeWaitRelease(name)
        local l = lease()
        if l[6] ~= T.CMD.done then return end
        st.done = {frame=frame(), lease_hex=hex(l), result=l[9]}
        jlog("TRADE_DONE", st.done)
        if l[9] == 0 and st.committing and not st.native then
            st.native = {frame=frame(), cart=api.read_range(0, T.CART, "CartRAM")}   -- the DONE-instant CartRAM
        end
    end
    function H.SlinkTradeExit(name)
        st.exit_frame = frame()
        jlog("TRADE_EXIT", {frame=frame(), lease_hex=hex(lease())})
        phase_end("wait", name)
        local after = control_point(name)
        control("decline", st.decline_before, after)
        control("timeout", st.wait_before, after)
        control("d3", st.item_before, after)
    end
    function H.Reset(name)
        jlog("TRADE_RESET_ENTRY", {frame=frame()})
        open_phases_end(name)
        local l = lease()
        if l[6] ~= T.CMD.apply and l[6] ~= T.CMD.done and not st.committing then st.reset_before = control_point(name) end
        if st.committing and not st.done then st.reset_commit_before = control_point(name) end
    end
    H["SlinkTradeCommit.cleanup"] = function(name)
        if not st.committing or api.register("B") ~= 0 or st.save_returned then return end
        st.save_returned = frame()
        jlog("TRADE_SAVE_RETURNED", {frame=frame(), site=site(name), registers=registers()})
        if st.capture_at_save and not st.native then
            st.native = {frame=frame(), cart=api.read_range(0, T.CART, "CartRAM"), at="save_returned"}
        end
    end
    function H.StartTitleScreen(name)
        control("reset_wait", st.reset_before, control_point(name))
        control("reset_commit", st.reset_commit_before, control_point(name), st.commit_entry)
    end
    function H.SlinkTradePublishDone(name)
        local l = lease()
        if st.committing and api.register("A") == 0 then phase_end("native_save", name) end
        if api.register("A") == 1 and l[6] == T.CMD.prompt and not st.decline_before then
            st.decline_before = control_point(name, l[10])
        end
    end
    H["SlinkTradeWaitApply.wait"] = function(name)
        if st.wait_before == nil then st.wait_before = control_point(name, lease()[10]) end
    end
    function H.SlinkTradeItemAllowed(name)
        if st.item_before == nil then st.item_before = control_point(name, u8(tf.ram.wCurPartyMon.addr)) end
    end

    local write = api.on_bus_write or function(fn, addr, name, domain) return event.onmemorywrite(fn, addr, name, domain) end
    for name, fn in pairs(PRE) do H[name] = fn end
    for name, fn in pairs(H) do
        local s = tf.code[name]
        assert(api.read_u8(s.flat, "ROM") == tonumber(s.hex, 16), name .. ": the running overlay's byte differs from the facts")
        local handle = api.on_bus_exec(function()
            if not (st.armed or PRE[name]) or (s.addr >= 0x4000 and rom_bank() ~= s.bank) then return end
            local ok, err = pcall(fn, name)
            if not ok then fault(name .. ": " .. tostring(err)) end
        end, s.addr, "SLink-duo-trade-" .. name, "System Bus")
        assert(handle ~= nil and handle ~= "", name .. ": exec hook registration failed")
        st.exec[#st.exec + 1] = handle
    end

    -- The P4.1g bus-write SP witness, CONTINUOUS: one hook per stack byte, all registered once at the baseline
    -- (before the first monitored phase), never disarmed or re-armed until TRADE_STACK. Each push (a write at
    -- SP-2..SP+1) is classified into the open phase; the first push per address per phase is the sample.
    local function unarm_all()
        for a, handle in pairs(st.writes) do pcall(api.unregister, handle); st.writes[a] = nil end
    end
    local function arm_all()
        assert(next(st.writes) == nil and not st.coverage_started, "the stack witness is armed once")
        st.registration, st.global, st.global_hit, st.low, st.pushes = {}, {}, {}, nil, 0
        local n = 0
        for a = bottom, top do
            local ok, handle = pcall(write, function()
                local sp = api.register("SP")
                if a < sp - 2 or a > sp + 1 then return end
                st.pushes = (st.pushes or 0) + 1
                local low = st.low
                local ph = st.current
                if low and math.min(a, sp) >= math.min(low.stack_addr, low.sp) and (not ph or ph.hit[a])
                   and st.global_hit[a] then return end
                local row = {frame=frame(), stack_addr=a, sp=sp, pc=api.register("PC"), rom_bank=rom_bank()}
                if not low or math.min(a, sp) < math.min(low.stack_addr, low.sp) then st.low = row end
                if not st.global_hit[a] then st.global_hit[a] = true; st.global[#st.global + 1] = row end
                if ph and not ph.hit[a] then ph.hit[a] = true; ph.samples[#ph.samples + 1] = row end
            end, a, "SLink-duo-trade-sp-" .. a, "System Bus")
            if ok and handle ~= nil and handle ~= "" then
                st.writes[a], n = handle, n + 1
                st.registration[#st.registration + 1] = {action="arm", address=a, frame=frame(), hook_id=tostring(handle)}
            else st.hook_failures = st.hook_failures + 1 end
        end
        st.armed_count = n
        st.coverage_started = {frame=frame(), site="harness:trade_go"}
    end
    local function native_image()
        local cap = st.native
        st.native_done = true
        local digest = SG.cart_digest(api)
        local saved = SG.flush(ctx, digest)
        local same = #saved == T.SAVERAM
        for i = 1, T.CART do if saved:byte(i) ~= cap.cart[i] then same = false break end end
        local chars = {}
        for i = 1, T.CART do chars[i] = string.char(cap.cart[i]) end
        local image = table.concat(chars) .. saved:sub(T.CART + 1)
        h.trade.image("TRADE_NATIVE_SAVE", "trade_native", image, {frame=cap.frame, capture_frame=cap.frame,
            flush_frame=frame(), save_entry_frame=st.save_entry_frame, flushed_matches=same, kind="native_trade_save",
            client_saves=h.rec.client_saves})
    end
    local function forced_image()
        local cap = st.forced
        st.forced_done = true
        local saved = SG.flush(ctx, SG.cart_digest(api))
        local same = #saved == T.SAVERAM
        for i = 1, T.CART do if saved:byte(i) ~= cap.cart[i] then same = false break end end
        local chars = {}
        for i = 1, T.CART do chars[i] = string.char(cap.cart[i]) end
        h.trade.image("TRADE_FORCED_SAVE", "trade_forced_save", table.concat(chars) .. saved:sub(T.CART + 1),
            {frame=cap.frame, capture_frame=cap.frame, flush_frame=frame(), flushed_matches=same, kind="forced_native_save",
             client_saves=h.rec.client_saves, save_completed_frame=h.rec.save_completed_frame or json.null})
    end
    local real_advance = api.advance
    api.advance = function()
        real_advance()
        if st.forced and not st.forced_done then
            local ok, err = pcall(forced_image)
            if not ok then fault("forced save image: " .. tostring(err)) end
        end
        if st.native and not st.native_done then
            local ok, err = pcall(native_image)
            if not ok then fault("native image: " .. tostring(err)) end
        end
    end

    -- ── the scenario-facing helpers ──
    -- An immutable image: <SLINK_DUO.trade_evidence_dir>/<player>_<suffix>.SaveRAM (the runner keeps that
    -- directory, even on success), else next to the result file. Never overwritten.
    function h.trade.image(tag, suffix, saved, extra)
        local path
        if D.trade_evidence_dir then
            path = D.trade_evidence_dir:gsub("\\", "/"):gsub("/$", "") .. "/" .. D.player .. "_" .. suffix .. ".SaveRAM"
        else
            local result = D.result:gsub("\\", "/")
            path = result:gsub("_result%.txt$", "") .. "_" .. suffix .. ".SaveRAM"
            assert(path ~= result .. "_" .. suffix .. ".SaveRAM", "result path does not end in _result.txt")
        end
        local existing = io.open(path, "rb")
        if existing then existing:close(); error("snapshot already exists: " .. path, 0) end
        local f = assert(io.open(path, "wb"), "cannot write " .. path)
        f:write(saved)
        f:close()
        local row = {frame=frame(), snapshot_path=path, snapshot_sha256=sha(saved),
                     cartram_sha256=SG.sha256(function(i) return saved:byte(i + 1) end, T.CART),
                     snapshot_bytes=#saved, cartram_bytes=T.CART}
        for k, v in pairs(extra or {}) do row[k] = v end
        jlog(tag, row)
        return row
    end
    function h.trade.cart_digest() return SG.cart_digest(api) end
    function h.trade.party_keys()
        local wire = e.wire or dofile(h.root .. "/lua/gen2/wire.lua")
        local party, out = ctx.reads.read_party(), {}
        for _, m in ipairs(party and party.mons or {}) do out[#out + 1] = wire.mon_key(m) end
        return out
    end
    function h.trade.wram_dex()
        return {caught_hex=hex(ctx.sym("wPokedexCaught", 0, 32)), seen_hex=hex(ctx.sym("wPokedexSeen", 0, 32))}
    end
    function h.trade.flush()
        local digest = SG.cart_digest(api)
        return SG.flush(ctx, digest)
    end
    function h.trade.observe()
        local base = SG.qualify_observer(ctx)
        local FI = e.FI or dofile(h.root .. "/lua/tests/duo/gen2_faint_inputs.lua")
        return function()
            local point = base()
            if point.ui and point.ui.kind == "trade_party" then point.party_cursor = FI.party_cursor(SG.screen(ctx)) end
            point.trade = {entered=st.entry_frame ~= nil, exited=st.exit_frame ~= nil, committing=st.committing == true,
                           waiting=st.wait_apply_frame ~= nil and st.exit_frame == nil and not st.committing,
                           wait_apply_frame=st.wait_apply_frame}
            return point
        end
    end
    function h.trade.play(name, driver, max_frames)
        local left = math.max(1, (D.timeout_frames or 150000) - frame())
        local spec = {name=name, terminal=driver.terminal, terminal_idle=true, max_frames=math.min(max_frames, left),
                      max_phase_frames=math.min(max_frames, left), settle_frames=F.BUDGET.settle_frames}
        local observe = h.trade.observe()
        local wrapped = {terminal=driver.terminal}
        function wrapped.step(point) return driver.step(point, frame()) end
        setmetatable(wrapped, {__index=function(_, k) return driver[k] end})
        return F.play(e.host, spec, wrapped, observe, {log=e.log, frame=frame,
            screen=function() return SG.screen(ctx) end, where=function() return "-" end,
            trace=os.getenv("SLINK_GEN2_TRACE") == "1"})
    end
    function h.trade.walk()
        local PI = dofile(h.root .. "/lua/tests/gen2_poison_inputs.lua")
        local pc = assert(ctx.u1.pc, "SLINK_GEN2_U1_FACTS lacks pc (the U1f Center legs)")
        local maps, legs = {}, {}
        for k, v in pairs(pc.maps) do maps[k] = v end
        for k, v in pairs(tf.maps) do maps[k] = v end
        for k, v in pairs(pc.to_pc) do legs[k] = v end
        for k, v in pairs(tf.legs) do legs[k] = v end
        return h.trade.play("duo-gen2-trade-walk", T.travel_driver(PI, maps, legs, tf.stand), T.WALK.max_frames)
    end
    -- The baseline: the native save just made, frozen with its saved party/dex; arms the trade hooks.
    function h.trade.baseline(key)
        local saved = h.trade.flush()
        local slot = h.slot_of(key)
        assert(slot ~= nil, "the linked key left the party")
        local party = T.saved_party(saved, ctx.profile, ctx.env.title)
        local row = h.trade.image("TRADE_BASELINE", "trade_baseline", saved, {kind="native_save", slot=slot,
            count=#party, key=key, party=json.array(party), dex=T.saved_dex(saved, ctx.profile, ctx.env.title),
            client_saves=h.rec.client_saves})
        st.armed, st.baseline = true, row
        return row
    end
    -- The continuous stack witness, armed once at TRADE_GO: before any receptionist input or monitored phase.
    function h.trade.arm_stack()
        local ok, err = pcall(arm_all)
        if not ok then fault("stack witness: " .. tostring(err)) end
    end
    function h.trade.stack()
        local phases = {}
        for i, name in ipairs(T.PHASES) do
            local ph = st.phase[name]
            phases[i] = {phase=name, visited=ph.visited, start=ph.start or json.null, ["end"]=ph["end"] or json.null,
                         samples=json.array(ph.samples)}
        end
        local ended = {frame=frame(), site="harness:before_report"}
        unarm_all()
        local first
        for _, name in ipairs(T.PHASES) do
            local ph = st.phase[name]
            if ph.start and (first == nil or ph.start.frame < first) then first = ph.start.frame end
        end
        local last_arm = st.registration and #st.registration > 0 and st.registration[#st.registration].frame or nil
        local row = {domain="System Bus", stack_bank=stack_bank, stack_start=bottom, stack_end=top,
                     armed_count=st.armed_count, hook_failures=st.hook_failures, phases=json.array(phases),
                     registration_events=json.array(st.registration or {}), continuous=true,
                     global_low_water=st.low or json.null, global_observations=st.pushes or 0,
                     global_minima=json.array(st.global or {}),   -- sparse: the first push per address, no completeness claim
                     coverage_started=st.coverage_started or json.null, coverage_ended=ended,
                     registration_complete_before_first_phase=last_arm ~= nil and (first == nil or last_arm <= first)}
        jlog("TRADE_STACK", row)
        return row
    end
    function h.trade.release()
        unarm_all()
        for _, handle in ipairs(st.exec) do pcall(api.unregister, handle) end
        st.exec = {}
        console.log = _console
    end
    return h.trade
end

-- ── 5. the verdict (pure) ───────────────────────────────────────────────────────────────────────
T.JSON_TAGS = {}
for _, tag in ipairs({"DUO_GEN2", "CLIENT", "BOOTED", "HELLO", "ENGINE_CAPTURE", "TRADE_ADMISSION", "TRADE_BASELINE",
                      "TRADE_READY", "TRADE_GO", "TRADE_ENTRY", "TRADE_OFFER", "TRADE_WAIT_APPLY", "TRADE_APPLY_PICKUP",
                      "TRADE_COMMIT_ENTRY", "TRADE_PRE_REMOVE", "TRADE_NATIVE_CALL", "TRADE_DONE", "TRADE_NATIVE_SAVE",
                      "TRADE_EXIT", "TRADE_RESET_ENTRY", "TRADE_ANSWER", "TRADE_CANCEL", "TRADE_CONTROL", "CHORD",
                      "TRADE_SAVE_RETURNED", "TRADE_RECOVERED", "TRADE_RELOAD", "RELOAD_CHORD", "RELOADED", "HARNESS_WRITE",
                      "TRADE_FORCED_SAVE",
                      "SAVE_WITNESS",
                      "RESET_SEEN", "REBOOTED", "TRADE_FINAL", "TRADE_STACK", "TRADE_HOOK_ERROR"}) do
    T.JSON_TAGS[tag] = true
end
-- case -> player -> {role, outcome, extra}: who does what (the scenario plans below are built from this).
-- visit (receipt visit_state): accepted (a host-accepted offer/prompt visit) | query (D3: refused at the query
-- stage) | none (the D3 peer: no visit at all). Every side keeps its declared role (0 proposer, 1 responder).
T.CASES = {
    new          = {a={role="proposer", outcome="committed", visit="accepted"},
                    b={role="responder", outcome="committed", visit="accepted", answer="YES"}},
    decline_new  = {a={role="proposer", outcome="unchanged", visit="accepted", cancel=true},
                    b={role="responder", outcome="unchanged", visit="accepted", answer="NO", control="decline"}},
    timeout      = {a={role="proposer", outcome="unchanged", visit="accepted", control="timeout"},
                    b={role="responder", outcome="unchanged", visit="accepted", answer="NO", after="TRADE_EXIT"}},
    evolve       = {a={role="proposer", outcome="committed", visit="accepted", plant="species"},
                    b={role="responder", outcome="committed", visit="accepted", answer="YES", evolves=true}},
    reset_wait   = {a={role="proposer", outcome="unchanged", visit="accepted", chord="wait", control="reset_wait"},
                    b={role="responder", outcome="unchanged", visit="accepted", answer="NO", after="REBOOTED"}},
    reset_commit = {a={role="proposer", outcome="committed", visit="accepted", chord="commit", recovered=true,
                       control="reset_commit"},
                    b={role="responder", outcome="committed", visit="accepted", answer="YES"}},
    refuse_item  = {a={role="proposer", outcome="unchanged", visit="query", control="d3", plant="mail"},
                    b={role="responder", outcome="unchanged", visit="none", after="TRADE_EXIT"}},
}
local ANIM = {[0]="TradeAnimation", [1]="TradeAnimationPlayer2"}

local function hex64(v) return type(v) == "string" and #v == 64 and v:match("^%x+$") ~= nil end
local function hexbytes(v, n) return type(v) == "string" and #v == 2 * n and v:match("^%x+$") ~= nil end
local function lease_bytes(v)
    if not hexbytes(v, 16) then return nil end
    local out = {}
    for i = 1, 32, 2 do out[#out + 1] = tonumber(v:sub(i, i + 1), 16) end
    return out
end

-- Pure: marker lines -> problems (empty = PASS), receipt facts. case = "new"..; player "a"|"b".
function T.verdict(lines, json, case, player)
    local plan = T.CASES[case] and T.CASES[case][player]
    local problems, seen, order = {}, {}, {}
    local function need(ok, what) if not ok then problems[#problems + 1] = what end return ok end
    if not need(plan ~= nil, "unknown trade case/player " .. tostring(case) .. "/" .. tostring(player)) then return problems end
    for index, line in ipairs(lines) do
        local tag, body = tostring(line):match("^([%u%d_]+) (.*)$")
        if tostring(line):sub(1, 7) == "RESULT:" then need(false, "a RESULT line precedes the verdict") end
        if tag and T.JSON_TAGS[tag] then
            local value = json.decode(body)
            if need(type(value) == "table", "malformed " .. tag .. " marker") then
                seen[tag] = seen[tag] or {}
                table.insert(seen[tag], {at=index, value=value})
                order[#order + 1] = {tag=tag, at=index, value=value}
            end
        elseif tag == "CAUGHT" then seen.CAUGHT = (seen.CAUGHT or 0) + 1 end
    end
    local function all(tag) return seen[tag] or {} end
    local function one(tag)
        local rows = all(tag)
        need(#rows == 1, (#rows == 0 and "missing " or (#rows .. " ")) .. tag .. (#rows == 0 and " marker" or " markers (expected one)"))
        return rows[1]
    end
    local function none(tag) need(#all(tag) == 0, "unexpected " .. tag .. " marker") end
    local function v(row) return row and row.value or {} end
    local function before(a, b, what) if a and b then need(a.at < b.at, what) end end
    local function image(row, label)
        local r = v(row)
        need(r.snapshot_bytes == T.SAVERAM and r.cartram_bytes == T.CART and hex64(r.snapshot_sha256)
             and hex64(r.cartram_sha256) and type(r.snapshot_path) == "string" and r.snapshot_path ~= ""
             and integer(r.frame, 0, 2^53), label .. " image incomplete")
    end

    none("TRADE_HOOK_ERROR")
    local head, client, adm = one("DUO_GEN2"), one("CLIENT"), one("TRADE_ADMISSION")
    one("BOOTED"); one("HELLO")
    need(v(client).qualification == T.SCOPE and v(client).production_admitted == true,
         "client is not the disclosed HARNESS_ONLY_OVERLAY composition")
    local a = v(adm)
    need(a.admission_scope == T.SCOPE and hex64(a.override_manifest_sha256) and hex64(a.trade_manifest_sha256)
         and type(a.run_id) == "string" and a.run_id ~= "" and hexbytes(a.overlay_sha1, 20),
         "trade admission disclosure incomplete or not the pinned overlay")
    need((seen.CAUGHT or 0) == 1 and #all("ENGINE_CAPTURE") >= 1, "the linked catch was not reported")

    local base, ready, go, final = one("TRADE_BASELINE"), one("TRADE_READY"), one("TRADE_GO"), one("TRADE_FINAL")
    -- O-31: exactly the planned disclosed write, nothing else; an undisclosed plant is refused below
    local writes = all("HARNESS_WRITE")
    local capture = all("ENGINE_CAPTURE")[1]
    local mail_item, planted
    if not plan.plant then
        need(#writes == 0, "a harness write in a case that plans none")
    else
        planted = one("HARNESS_WRITE")
        local w = v(planted)
        local purpose = plan.plant == "mail" and "d3_mail_item" or "trade_evolve_species"
        need(w.purpose == purpose and w.domain == "WRAM" and hexbytes(w.bytes_before, 1) and hexbytes(w.bytes_after, 1)
             and integer(w.address, 0xC000, 0xDFFF), "harness write is not the planned disclosed " .. purpose)
        if plan.plant == "mail" then
            mail_item = hexbytes(w.bytes_after, 1) and tonumber(w.bytes_after, 16) or nil
            need(capture and planted and planted.at > capture.at, "the mail item was planted before the link catch")
            before(planted, base, "TRADE_BASELINE before the disclosed mail plant")
        else
            before(planted, capture, "the species plant came after the catch")
            need(capture and w.bytes_after == fmt("%02x", v(capture).species_id or -1),
                 "the caught species is not the disclosed planted species")
        end
    end
    image(base, "baseline"); image(final, "final")
    local b = v(base)
    need(type(b.party) == "table" and #b.party == b.count and integer(b.slot, 0, 5) and b.slot < (b.count or 0)
         and type(b.dex) == "table" and type(b.dex.primary) == "table" and type(b.dex.backup) == "table",
         "baseline party/dex incomplete")
    for i, mon in ipairs(b.party or {}) do
        need(integer(mon.species_marker, 1, 255) and hexbytes(mon.blob_hex, 70), "baseline party record malformed")
        if i == (b.slot or -1) + 1 and hexbytes(mon.blob_hex, 70) then
            local item = tonumber(mon.blob_hex:sub(3, 4), 16)
            need(plan.plant == "mail" and item == mail_item or plan.plant ~= "mail" and not T.MAIL[item],
                 "the offered mon's held item is not the disclosed plant (undisclosed write?)")
        end
    end
    before(base, ready, "TRADE_READY before TRADE_BASELINE")
    before(ready, go, "TRADE_GO before TRADE_READY")
    before(go, final, "TRADE_FINAL before TRADE_GO")
    need(v(ready).snapshot_sha256 == b.snapshot_sha256, "TRADE_READY does not name the baseline image")
    need(v(go).run_id == a.run_id, "TRADE_GO does not carry the admission run_id")
    if base and final then
        need(v(final).frame > b.frame and v(final).snapshot_path ~= b.snapshot_path, "final image is not a newer snapshot")
    end
    -- nothing of the visit may precede the go
    for _, row in ipairs(order) do
        if row.tag:sub(1, 6) == "TRADE_" and row.tag ~= "TRADE_ADMISSION" and row.tag ~= "TRADE_BASELINE"
           and row.tag ~= "TRADE_READY" and row.tag ~= "TRADE_GO" and row.tag ~= "TRADE_HOOK_ERROR" and go then
            need(row.at > go.at, row.tag .. " before TRADE_GO")
        end
    end

    -- the proposer's forced native save (9805ac1c): one immutable image, after GO, before the visit's entry
    if plan.role == "proposer" then
        local fs = one("TRADE_FORCED_SAVE")
        image(fs, "forced save")
        local f = v(fs)
        need(f.flushed_matches == true and integer(f.client_saves, (b.client_saves or 0) + 1, 2^53)
             and integer(f.save_completed_frame, v(go).frame or 0, f.frame or -1),
             "forced save image is not the successful pre-lease native save")
        need(f.frame == v(all("TRADE_ENTRY")[1]).frame, "forced save image is not captured at SlinkTradeEntry")
        need(f.snapshot_path ~= b.snapshot_path and f.snapshot_path ~= v(final).snapshot_path, "forced save image reused")
    else
        none("TRADE_FORCED_SAVE")
    end
    local offered = plan.visit ~= "none" and plan.visit ~= "query"
    local offer = offered and one("TRADE_OFFER") or nil
    local o = v(offer)
    local role = plan.role == "proposer" and 0 or 1
    if not offered then
        none("TRADE_OFFER")
        if plan.visit == "none" then none("TRADE_ENTRY"); none("TRADE_EXIT"); none("TRADE_WAIT_APPLY")
        else need(v(one("TRADE_ENTRY")).role == 0, "the query visit is not the proposer's") end
    else
        local entry = one("TRADE_ENTRY")
        need(v(entry).role == role and o.role == role, "trade role differs from the case plan")
        before(entry, offer, "TRADE_OFFER before TRADE_ENTRY")
        local l = lease_bytes(o.lease_hex)
        need(l ~= nil and l[6] == (role == 0 and T.CMD.offer or T.CMD.prompt) and l[7] == o.generation and l[10] == o.slot
             and type(o.token) == "table" and #o.token == 4 and l[13] == o.token[1] and l[16] == o.token[4]
             and (o.token[1] + o.token[2] + o.token[3] + o.token[4]) > 0, "offer lease/token/generation inconsistent")
        need(o.slot == b.slot and o.count == b.count, "offered slot/count differ from the baseline")
        local mon = (b.party or {})[(o.slot or -1) + 1] or {}
        need(o.species_marker == mon.species_marker and o.blob_hex == mon.blob_hex, "offered record differs from the baseline save")
        if role == 1 then need(hexbytes(o.incoming_blob_hex, 70), "responder offer lacks the staged incoming record") end
    end

    local commit = plan.outcome ~= "unchanged"
    local calls = all("TRADE_NATIVE_CALL")
    if plan.outcome == "committed" then
        local pickup, entry, pre = one("TRADE_APPLY_PICKUP"), one("TRADE_COMMIT_ENTRY"), one("TRADE_PRE_REMOVE")
        local recovered = plan.recovered == true
        local done = not recovered and one("TRADE_DONE") or nil
        local native, returned = one("TRADE_NATIVE_SAVE"), one("TRADE_SAVE_RETURNED")
        if recovered then
            none("TRADE_DONE"); none("TRADE_EXIT")
            local rec = one("TRADE_RECOVERED")
            before(one("REBOOTED"), rec, "TRADE_RECOVERED before REBOOTED")
            before(rec, final, "TRADE_FINAL before TRADE_RECOVERED")
            need(v(final).kind == "flush", "the recovered side saved again after the reset")
            before(returned, one("CHORD"), "the chord preceded the returned native save")
        else
            one("TRADE_EXIT")
            need(v(final).kind == "flush", "the traded side's final image is not a flush of the native trade save")
        end
        local want = {"RemoveMonFromPartyOrBox", ANIM[role], "AddTempmonToParty", "EvolvePokemon", "SaveAfterLinkTrade"}
        need(#calls == #want, fmt("%d native calls (expected %d)", #calls, #want))
        for i, name in ipairs(want) do
            need(calls[i] and calls[i].value.symbol == name, "native call " .. i .. " is not " .. name)
            if i > 1 and calls[i] and calls[i - 1] then need(calls[i].value.frame >= calls[i - 1].value.frame, "native call frames reversed") end
        end
        before(offer, pickup, "TRADE_APPLY_PICKUP before TRADE_OFFER")
        before(pickup, entry, "TRADE_COMMIT_ENTRY before TRADE_APPLY_PICKUP")
        before(entry, pre, "TRADE_PRE_REMOVE before TRADE_COMMIT_ENTRY")
        before(done or returned, native, "TRADE_NATIVE_SAVE before its capture point")
        before(native, final, "TRADE_FINAL before TRADE_NATIVE_SAVE")
        need(v(final).client_saves == v(native).client_saves and #all("SAVE_WITNESS") == 0,
             "an ordinary save ran between the native trade save and TRADE_FINAL")
        local chord, reloaded, reload = one("RELOAD_CHORD"), one("RELOADED"), one("TRADE_RELOAD")
        before(final, chord, "RELOAD_CHORD before TRADE_FINAL")
        before(chord, reloaded, "RELOADED before RELOAD_CHORD")
        before(reloaded, reload, "TRADE_RELOAD before RELOADED")
        local r = v(reload)
        need(r.snapshot_sha256 == v(final).snapshot_sha256 and r.cartram_sha256 == v(final).cartram_sha256
             and type(r.party_keys) == "table" and #r.party_keys > 0 and type(r.dex) == "table"
             and type(r.dex.primary) == "table" and type(r.dex.backup) == "table",
             "TRADE_RELOAD does not read back the TRADE_FINAL image")
        local g = (o.generation or 0) + 1
        local lp, ld = lease_bytes(v(pickup).lease_hex), lease_bytes(v(done).lease_hex)
        if recovered then ld = {0, 0, 0, 0, 0, T.CMD.done, g % 256, g % 256, 0, o.slot} end   -- no DONE by design
        need(lp and lp[6] == T.CMD.apply and lp[7] == g % 256 and lp[8] == (g - 1) % 256 and lp[10] == o.slot
             and lp[13] == o.token[1] and lp[16] == o.token[4], "APPLY pickup lease inconsistent with the accepted offer")
        need(ld and ld[6] == T.CMD.done and ld[7] == g % 256 and ld[8] == g % 256 and ld[9] == 0 and ld[10] == o.slot
             and (recovered or v(done).result == 0), "DONE is not a successful native commit of this visit")
        need(hexbytes(v(pickup).incoming_blob_hex, 70) and integer(v(pickup).incoming_species_marker, 1, 255),
             "APPLY pickup lacks the staged incoming record")
        -- the server re-key: this side's trade_done names the received (evolved when planned) species
        local sent
        for _, line in ipairs(lines) do
            local body = tostring(line):match("^TX (.*)$")
            local okd, msg = pcall(json.decode, body or "")
            if okd and type(msg) == "table" and msg.event == "trade_done" then sent = msg end
        end
        need(sent ~= nil and type(sent.new_key) == "string" and integer(sent.new_species, 1, 251),
             "no trade_done with the received key on the wire")
        if plan.evolves and sent then
            need(sent.new_species ~= v(pickup).incoming_species_marker
                 and sent.new_key:sub(-2):lower() == fmt("%02x", sent.new_species),
                 "the received trade evolver did not evolve natively (trade_done keeps the old species)")
        elseif sent then
            need(sent.new_species == v(pickup).incoming_species_marker, "a received mon changed species without a trade evolution")
        end
        local ce = v(entry)
        need(ce.slot == o.slot and ce.role == role, "SlinkTradeCommit registers disagree with the offer")
        local p = v(pre)
        need(p.frame == (calls[1] and calls[1].value.frame) and p.slot == o.slot, "pre-remove is not at the Remove entry")
        for _, part in ipairs({"live", "frozen"}) do
            local rec, joined = p[part], {}
            need(type(rec) == "table" and rec.domain == "System Bus" and rec.bank == 1 and type(rec.spans) == "table"
                 and #rec.spans == 3, part .. " pre-remove spans incomplete")
            for _, s in ipairs(rec and rec.spans or {}) do joined[#joined + 1] = s.hex end
            need(table.concat(joined) == o.blob_hex, part .. " pre-remove record differs from the accepted offer")
        end
        local n = v(native)
        image(native, "native trade save")
        need(n.frame == (recovered and v(returned) or v(done)).frame and (n.flushed_matches == true or recovered)
             and n.save_entry_frame == (calls[5] and calls[5].value.frame) and (v(returned).frame or -1) >= (n.save_entry_frame or 0),
             "native trade image is not the DONE-instant (or, reset after the save, the save-returned) CartRAM")
    else
        none("TRADE_NATIVE_SAVE")
        if plan.outcome == "unchanged" then
            none("TRADE_APPLY_PICKUP"); none("TRADE_COMMIT_ENTRY"); none("TRADE_PRE_REMOVE"); none("TRADE_RELOAD")
            need(#calls == 0, "negative case entered a native trade call")
            need(v(final).kind == "flush", "negative case made a native save after the baseline")
        else
            need(false, "unknown outcome " .. tostring(plan.outcome))
        end
    end
    if plan.chord then
        local chord, reset, rebooted = one("CHORD"), one("RESET_SEEN"), one("REBOOTED")
        one("TRADE_RESET_ENTRY")
        before(chord, reset, "RESET_SEEN before CHORD")
        before(reset, rebooted, "REBOOTED before RESET_SEEN")
        before(rebooted, final, "TRADE_FINAL before REBOOTED")
        if plan.chord == "wait" then before(one("TRADE_WAIT_APPLY"), chord, "the chord preceded the held wait") end
        none("TRADE_DONE")
        if plan.chord == "commit" then before(chord, rebooted, "REBOOTED before CHORD") end
    elseif plan.visit ~= "none" then
        one("TRADE_EXIT")
    end
    -- refinement 2: the negative case's trigger, on the side that triggers it
    if plan.control then
        local ctl = v(one("TRADE_CONTROL"))
        local bf, af = ctl.before or {}, ctl.after or {}
        local lb, la = lease_bytes(bf.lease_hex), lease_bytes(af.lease_hex)
        local rb, ra = bf.registers or {}, af.registers or {}
        local function at(row, symbol) return type(row.site) == "table" and row.site.symbol == symbol end
        need(ctl.kind == plan.control and lb ~= nil and la ~= nil and integer(bf.frame, 0, 2^53)
             and integer(af.frame, bf.frame or 0, 2^53), "TRADE_CONTROL incomplete for " .. plan.control)
        if lb and la and ctl.kind == "decline" then
            need(at(bf, "SlinkTradePublishDone") and rb.A == 1 and lb[6] == T.CMD.prompt and at(af, "SlinkTradeExit")
                 and (la[6] == T.CMD.done or la[6] == T.CMD.release) and la[9] == 1, "decline control is not PublishDone(1) -> Exit")
        elseif lb and la and ctl.kind == "timeout" then
            local bc = function(r) return type(r.B) == "number" and type(r.C) == "number" and r.B * 256 + r.C or nil end
            need(at(bf, "SlinkTradeWaitApply.wait") and bc(rb) == T.APPLY_WAIT and at(af, "SlinkTradeExit") and bc(ra) == 0
                 and af.frame - bf.frame >= T.APPLY_WAIT and lb[6] ~= T.CMD.apply and la[6] ~= T.CMD.apply,
                 "timeout control is not WaitApply(BC=APPLY_FRAMES) -> Exit(BC=0) before APPLY")
        elseif lb and la and ctl.kind == "reset_wait" then
            local zero = true
            for i = 1, 16 do if la[i] ~= 0 then zero = false end end
            need(at(bf, "Reset") and lb[6] ~= T.CMD.apply and lb[6] ~= T.CMD.done and at(af, "StartTitleScreen") and zero,
                 "reset control is not Reset pre-APPLY -> StartTitleScreen with a zeroed lease")
        elseif lb and la and ctl.kind == "reset_commit" then
            local zero, cm = true, ctl.commit or {}
            for i = 1, 16 do if la[i] ~= 0 then zero = false end end
            local entry = v(all("TRADE_COMMIT_ENTRY")[1])
            need(at(bf, "Reset") and at(af, "StartTitleScreen") and zero and at(cm, "SlinkTradeCommit")
                 and cm.frame == entry.frame and cm.lease_hex == entry.lease_hex and integer(cm.frame, 0, (bf.frame or 0) - 1),
                 "reset_commit control is not SlinkTradeCommit -> Reset -> StartTitleScreen with a zeroed lease")
        elseif lb and la and ctl.kind == "d3" then
            local mon = (b.party or {})[(b.slot or -1) + 1] or {}
            local item = type(mon.blob_hex) == "string" and tonumber(mon.blob_hex:sub(3, 4), 16) or nil
            need(at(bf, "SlinkTradeItemAllowed") and rb.A == item and bf.slot == b.slot and at(af, "SlinkTradeExit"),
                 "D3 control is not ItemAllowed(baseline item) -> Exit on the selected slot")
        end
    else
        none("TRADE_CONTROL")
    end
    if plan.cancel then
        local cancel = one("TRADE_CANCEL")
        need(v(cancel).button == "B", "cancel is not the native B")
        before(one("TRADE_WAIT_APPLY"), cancel, "cancel before the held wait")
    else
        none("TRADE_CANCEL")
    end
    if plan.answer then
        local ans = one("TRADE_ANSWER")
        need(v(ans).answer == plan.answer, "responder answered " .. tostring(v(ans).answer) .. ", plan " .. plan.answer)
        if plan.after then need(v(ans).after == plan.after, "responder answered before the partner's " .. plan.after) end
    end

    -- the stack witness shape and bounds (the oracle re-derives the bounds from the overlay .sym)
    local stack = v(one("TRADE_STACK"))
    need(stack.domain == "System Bus" and integer(stack.stack_start, 0xC000, 0xDFFF) and integer(stack.stack_end, 0xC000, 0xDFFF)
         and stack.armed_count == (stack.stack_end or 0) - (stack.stack_start or 0) + 1 and stack.hook_failures == 0,
         "stack witness coverage incomplete")
    local events, addrs = stack.registration_events or {}, {}
    local cs, ce = stack.coverage_started or {}, stack.coverage_ended or {}
    need(stack.continuous == true and stack.registration_complete_before_first_phase == true
         and #events == stack.armed_count and integer(cs.frame, 0, 2^53) and integer(ce.frame, cs.frame or 0, 2^53),
         "stack witness is not one continuous registration")
    for _, ev in ipairs(events) do
        need(ev.action == "arm" and not addrs[ev.address] and integer(ev.address, stack.stack_start or 0, stack.stack_end or -1)
             and integer(ev.frame, 0, cs.frame or -1) and type(ev.hook_id) == "string" and ev.hook_id ~= "",
             "stack registration event malformed or repeated")
        addrs[ev.address or -1] = true
    end
    local low = stack.global_low_water
    local low_margin = type(low) == "table" and integer(low.stack_addr, stack.stack_start or 0, stack.stack_end or -1)
        and integer(low.sp, stack.stack_start or 0, (stack.stack_end or 0) + 1)
        and math.min(low.stack_addr, low.sp) - stack.stack_start or nil
    need(low_margin ~= nil and low_margin >= T.MARGIN and integer(stack.global_observations, 1, 2^53),
         "no global stack low-water mark with a 32-byte margin")
    local phases = stack.phases or {}
    need(#phases == 4, "stack phases missing")
    for i, name in ipairs(T.PHASES) do
        local ph = phases[i] or {}
        need(ph.phase == name, "stack phase " .. i .. " is not " .. name)
        local required = name == "wait" and plan.visit ~= "none"
            or (plan.outcome == "committed" and (name ~= "evolution_animation" or plan.evolves == true))
        local allowed = required or (commit and name ~= "wait" and name ~= "evolution_animation")
        need(not required or ph.visited == true, "required stack phase " .. name .. " unvisited")
        need(allowed or ph.visited ~= true, "stack phase " .. name .. " visited in a case that forbids it")
        local samples = ph.samples or {}
        need((#samples > 0) == (ph.visited == true), "stack phase " .. name .. " visitation/sample mismatch")
        if ph.visited then
            local s, en = ph.start or {}, ph["end"] or {}
            need(type(s.site) == "table" and type(en.site) == "table" and integer(s.frame, cs.frame or 0, 2^53)
                 and integer(en.frame, s.frame or 0, ce.frame or -1), "stack phase " .. name .. " lacks coverage endpoints")
            if name == "native_save" then
                need(en.site.symbol == (plan.recovered and "Reset" or "SlinkTradePublishDone"),
                     "native_save does not end at the successful DONE (or the planned reset)")
            end
            for _, sm in ipairs(samples) do
                need(integer(sm.frame, s.frame or 0, en.frame or -1) and integer(sm.sp, stack.stack_start or 0, (stack.stack_end or 0) + 1)
                     and integer(sm.stack_addr, stack.stack_start or 0, stack.stack_end or -1)
                     and sm.stack_addr >= sm.sp - 2 and sm.stack_addr <= sm.sp + 1
                     and math.min(sm.stack_addr, sm.sp) - stack.stack_start >= T.MARGIN
                     and (low_margin == nil or math.min(sm.stack_addr, sm.sp) - stack.stack_start >= low_margin),
                     "stack sample outside bounds/margin (or below the global low water) in " .. name)
            end
        end
    end
    if #problems > 0 then return problems, nil end
    local hv = v(head)
    local facts = {role=role, offer=o, baseline=b, final=v(final), admission=a, head=hv}
    if plan.visit == "query" then
        local l = lease_bytes(v(all("TRADE_CONTROL")[1]).before and v(all("TRADE_CONTROL")[1]).before.lease_hex)
        if l then facts.query_token, facts.query_generation = json.array({l[13], l[14], l[15], l[16]}), l[7] end
    end
    return problems, facts
end

-- ── 6. the scenario (scenario_gen2_trade_<case>.lua returns T.scenario(case)) ─────────────────────
function T.scenario(case)
    local S = {TRADE=true, CASE=case, RECEIPT_SCHEMA=T.SCHEMA, T=T}
    S.HELLO_FRAMES, S.GO_FRAMES = 3600, T.GO_FRAMES
    function S.verdict(lines, json, player) return T.verdict(lines, json, case, player) end
    function S.run(h)
        local plan = T.CASES[case][h.player]
        local tr = h.trade
        h.jitter()
        local arrived, why = h.arrive()
        if not arrived then return false, "no CONTINUE arrival: " .. tostring(why) end
        h.party()
        if not h.wait(function() return h.sent.hello ~= nil end, S.HELLO_FRAMES) then return false, "the client never sent hello" end
        if not h.wait(h.go, S.GO_FRAMES) then return false, "no go-file" end
        if plan.plant == "species" then tr.arm_species_plant() end   -- O-31: the next Route 29 wild battle
        -- the linked pair: the `link` route (catch, linked, native save)
        local played, outcome = h.play({settled=h.link_settled})
        if not played then return false, "link route failed: " .. tostring(outcome) end
        local key = h.rec.caught
        if not key then return false, "no reported catch" end
        h.party()
        local walked, walk_why = tr.walk()
        if not walked then return false, "walk to the trade desk: " .. tostring(walk_why) end
        if plan.plant == "mail" then   -- O-31: after the link, before the baseline save
            local slot = h.slot_of(key)
            if slot == nil then return false, "the linked key left the party" end
            tr.plant_mail(slot)
        end
        local saved, save_why = h.save()
        if not saved then return false, "baseline save: " .. tostring(save_why) end
        local base = tr.baseline(key)
        h.jlog("TRADE_READY", {frame=h.frame(), snapshot_sha256=base.snapshot_sha256, slot=base.slot, key=key})
        if not h.wait(function() return h.file_has(h.go_file, "TRADE_GO") end, T.GO_FRAMES) then
            return false, "the runner never wrote TRADE_GO"
        end
        h.jlog("TRADE_GO", {frame=h.frame(), run_id=tr.manifest.run_id})
        tr.arm_stack()
        local st = tr.state
        local ok, visit_why = S.visit(h, plan, base)
        if not ok then return false, visit_why end
        -- the images after the visit
        if plan.outcome == "committed" and not plan.recovered then
            if not h.wait(function() return st.native_done == true end, T.SETTLE_FRAMES) then
                return false, "no native trade image at DONE"
            end
        end
        h.frames(T.SETTLE_FRAMES)
        local final = tr.image("TRADE_FINAL", "trade_final", tr.flush(), {kind="flush", client_saves=h.rec.client_saves})
        tr.stack()
        h.frames(T.SETTLE_FRAMES)
        tr.release()
        if plan.outcome == "committed" then
            local ok, why = S.reload(h, final)
            if not ok then return false, why end
        end
        local problems, facts = S.verdict(h.lines, h.json, h.player)
        if #problems > 0 then return false, table.concat(problems, "; ") end
        local o, hd = facts.offer, facts.head
        h.jlog("RECEIPT", {schema=T.SCHEMA, case="gen2_trade_" .. case, variant=h.trade.variant or h.json.null,
            outcome=plan.outcome, player=h.player, title=hd.title, rom_sha1=facts.admission.overlay_sha1,
            base_sha1=facts.admission.base_sha1, admission_scope=T.SCOPE,
            override_manifest_sha256=facts.admission.override_manifest_sha256,
            trade_manifest_sha256=facts.admission.trade_manifest_sha256, run_id=facts.admission.run_id,
            attempt=hd.attempt, fixture_sha256=hd.fixture_sha256, visit_state=plan.visit,
            role=facts.role,
            token=o.token or facts.query_token or h.json.null, generation=o.generation or facts.query_generation or h.json.null,
            key=key,
            baseline_sha256=facts.baseline.snapshot_sha256, final_sha256=facts.final.snapshot_sha256,
            input_mode="normal_buttons", harness_write_scopes=h.json.array(h.trade.state.harness_writes),
            harness_exception=#h.trade.state.harness_writes > 0 and "O-31" or h.json.null})
        return true, fmt("%s %s: %s", case, h.player, plan.outcome)
    end
    -- The persistence leg (traded sides): boot the flushed TRADE_FINAL image and read it back, never saving.
    function S.reload(h, final)
        local digest = h.trade.cart_digest()
        if digest ~= final.cartram_sha256 then return false, "CartRAM moved after TRADE_FINAL (a save after the trade?)" end
        local chord = h.frame()
        h.hold(T.CHORD, T.CHORD_FRAMES)
        h.jlog("RELOAD_CHORD", {frame=chord, frames=T.CHORD_FRAMES})
        if not h.wait(function()
            local id = h.identity()
            return id ~= nil and id.ot_id == 0 and id.party_count == 0
        end, T.RESET_FRAMES) then return false, "the reload chord did not clear WRAM" end
        local arrived, why = h.arrive("RELOADED")
        if not arrived then return false, "no CONTINUE on the reload: " .. tostring(why) end
        local keys = h.trade.party_keys()
        if #keys == 0 then return false, "the reloaded party is unreadable" end
        local dex = h.trade.wram_dex()
        h.jlog("TRADE_RELOAD", {frame=h.frame(), snapshot_sha256=final.snapshot_sha256, cartram_sha256=digest,
                                party_keys=h.json.array(keys), dex={primary=dex, backup=dex}})
        return true
    end
    -- One visit by plan; markers come from the hooks, the answers/cancel/chord from here.
    function S.visit(h, plan, base)
        local tr, st = h.trade, h.trade.state
        st.control_kind = plan.control
        if plan.visit == "none" then   -- the D3 peer: never offered anything, never has a visit
            if not h.wait(function() return h.partner_has(plan.after) end, T.PARTNER_FRAMES) then
                return false, "the proposer never left the trade service"
            end
            return true
        end

        local opts = {role=plan.role, slot=base.slot, stand=tr.facts.stand}
        if plan.answer then
            opts.answer = function()
                if plan.after and not h.partner_has(plan.after) then return nil end
                return plan.answer
            end
            opts.on_answer = function(answer)
                if not st.answered then
                    st.answered = true
                    h.jlog("TRADE_ANSWER", {frame=h.frame(), answer=answer, after=plan.after or h.json.null})
                end
            end
        end
        if plan.cancel then
            opts.cancel = function() return tr.rx_text(T.DECLINED) end
            opts.on_cancel = function() h.jlog("TRADE_CANCEL", {frame=h.frame(), button="B"}) end
        end
        if plan.chord == "wait" then
            opts.chord = function(point)
                return point.trade.waiting and h.frame() - point.trade.wait_apply_frame >= T.CHORD_AFTER
                       and h.partner_has("TRADE_OFFER")
            end
        elseif plan.chord == "commit" then   -- main ruling: after SaveAfterLinkTrade returned, before DONE
            st.capture_at_save = true
            opts.chord = function() return st.save_returned ~= nil and st.done == nil end
        end
        if plan.chord then opts.on_chord = function() st.chord_frame = h.frame(); h.jlog("CHORD", {frame=h.frame(), frames=T.CHORD_FRAMES}) end end
        local ok, why = tr.play("duo-gen2-trade-visit", T.visit_driver(opts), T.VISIT_FRAMES)
        if not ok then return false, "trade visit: " .. tostring(why) end
        if plan.chord then
            if not h.wait(function()
                local id = h.identity()
                return id ~= nil and id.ot_id == 0 and id.party_count == 0
            end, T.RESET_FRAMES) then return false, "the soft reset chord did not clear WRAM" end
            h.jlog("RESET_SEEN", {frame=h.frame(), delta=h.frame() - st.chord_frame})
            local rebooted, rwhy = h.arrive("REBOOTED")
            if not rebooted then return false, "no CONTINUE after the reset: " .. tostring(rwhy) end
            if plan.recovered then   -- keep ticking until the server settles the DONE-less side on party evidence
                local text
                if not h.wait(function()
                    for _, r in ipairs(st.rx) do
                        if r.cmd == "msgbox" and type(r.text) == "string" and r.text:sub(1, 7) == "Traded " then text = r.text return true end
                    end
                    return false
                end, T.RECOVERY_FRAMES) then return false, "the server never settled the reset side (watchdog + party evidence)" end
                h.jlog("TRADE_RECOVERED", {frame=h.frame(), text=text})
            end
        end
        return true
    end
    return S
end

return T
