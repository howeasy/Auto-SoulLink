"""Explicit MODEL-only hook probes; no emulator or physical qualification."""

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
# BizHawk 2.11.1 Gambatte emu.getregister keys, bank names included: no HL/DE/BC/AF pairs
# (docs/purergb/PLAN.md A15).
BIZHAWK_REGISTERS = ("PC", "SP", "A", "B", "C", "D", "E", "F", "H", "L",
                     "ROM0 BANK", "ROMX BANK", "VRAM BANK", "SRAM BANK", "WRAM BANK")
PAIRS = {"AF": ("A", "F"), "BC": ("B", "C"), "DE": ("D", "E"), "HL": ("H", "L")}


class Registers(dict):
    """Single CPU registers as BizHawk has them. A test may set or read a pair for
    convenience; the emulator side (bizhawk_register) refuses a pair name loudly."""

    def __init__(self, sp):
        super().__init__({name: 0 for name in BIZHAWK_REGISTERS})
        self["SP"] = sp

    def __setitem__(self, name, value):
        if name in PAIRS:
            super().__setitem__(PAIRS[name][0], value >> 8 & 255)
            super().__setitem__(PAIRS[name][1], value & 255)
        else:
            super().__setitem__(name, value)

    def __getitem__(self, name):
        if name in PAIRS:
            return super().__getitem__(PAIRS[name][0]) * 256 + super().__getitem__(PAIRS[name][1])
        return super().__getitem__(name)


def bizhawk_register(registers, name):
    if name not in BIZHAWK_REGISTERS:
        raise KeyError(f"BizHawk 2.11.1 emu.getregister has no {name!r} (singles only)")
    return registers.get(name)


class World:
    def __init__(self, title="crystal"):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.title = title
        self.profile = self.read_pack("profile")
        self.pack = self.read_pack("engine_signals")
        self.sites = self.pack["titles"][title]["sites"]
        self.p = self.profile["titles"][title]
        self.memory, self.rom, self.callbacks, self.removed = {}, {}, {}, []
        self.reg = Registers(0xC020 if title == "crystal" else 0xDF20)
        self.bank, self.shadow, self.wram_bank, self.sram_bank = 0, 0, 1, 1
        self.generation, self.operation, self.frame, self.held = 1, "operation-1", 1, True
        self.fields = {name: row for site in self.sites.values() for name, row in site["point_symbols"].items()}
        self.stack = self.read_pack("write_checkpoint")["titles"][title]["primary"]["caller_stack"]
        for site in self.sites.values():
            for offset, value in enumerate(bytes.fromhex(site["expected_hex"])):
                self.rom[site["rom_offset"] + offset] = value
            script = site["guards"].get("script_context")
            if script:
                flat = script["bank"] * 0x4000 + script["addr"] - 0x4000
                for offset, value in enumerate(bytes.fromhex(script["expected_hex"])):
                    self.rom[flat + offset] = value
        self.party([self.mon()])
        self.box([])
        self.field("wCurPartyMon", 0)
        self.field("wCurBattleMon", 0)
        self.field("wCurPartySpecies", 25)
        self.field("wBattleType", 0)
        self.field("wCurBox", 0)
        self.field("wMapGroup", 24)
        self.field("wMapNumber", 3)
        self.module = self.lua.eval("dofile")((ROOT / "lua/gen2/signals.lua").as_posix())
        self.registry = self.lua.eval("dofile")((ROOT / "lua/hook_registry.lua").as_posix())
        self.gb = self.lua.eval("dofile")((ROOT / "lua/gb_hook_binding.lua").as_posix())
        reads_module = self.lua.eval("dofile")((ROOT / "lua/gen2/reads.lua").as_posix())
        self.io = self.lua.table(
            model_only=True, cart_ram_linear=True,
            read_u8=self.read, read_range=lambda a, n, d: self.lua.table_from([self.read(a + i, d) for i in range(n)]),
            register=lambda name: bizhawk_register(self.reg, name), framecount=lambda: self.frame,
            on_bus_exec=self.register, unregister=self.unregister, bank_valid=self.bank_valid,
            stack_valid=lambda sp, n: self.stack["minimum_sp"] <= sp and sp + n <= self.stack["exclusive_stack_end"],
            domain_size=lambda domain: 0x8000 if domain == "CartRAM" else 0x200000,
        )
        self.io = self.lua.eval("""function(py)
            local io={model_only=true,cart_ram_linear=true}
            for _,name in ipairs({'read_u8','read_range','register','framecount','on_bus_exec',
                                  'unregister','bank_valid','stack_valid','domain_size'}) do
                local fn=py[name]
                io[name]=function(...) return fn(...) end
            end
            return io
        end""")(self.io)
        self.reads = reads_module.new(self.lua.table_from(self.p, recursive=True), self.io)
        assert not isinstance(self.reads, tuple), self.reads
        self.authority = self.lua.table(
            kind="MODEL_PROBE", allow_model_registration=True,
            capture=lambda: self.lua.table(generation=self.generation, operation=self.operation),
            valid=lambda stamp: self.held and stamp.generation == self.generation and stamp.operation == self.operation,
        )

    def read_pack(self, name):
        return json.loads((ROOT / f"data/games/gen2_{self.title}/{name}.json").read_text())

    def options(self):
        return self.lua.table(
            title=self.title, profile=self.lua.table_from(self.profile, recursive=True),
            pack=self.lua.table_from(self.pack, recursive=True), io=self.io,
            Registry=self.registry, GB=self.gb, reads=self.reads, authority=self.authority,
            areas=self.lua.table_from(self.read_pack("area_map"), recursive=True),
            encounters=self.lua.table_from(self.read_pack("encounter_tables"), recursive=True),
            owner="gen2-model-test", max_pending=64,
        )

    def bind(self):
        result = self.module.new_model(self.options())
        if isinstance(result, tuple):
            assert result[0] is not None, result[1]
            return result[0]
        return result

    def register(self, callback, address, name, domain):
        self.callbacks[name] = (callback, address)
        return name

    def unregister(self, handle):
        self.removed.append(handle)
        self.callbacks.pop(handle)
        return True

    def bank_valid(self, bank, address, size):
        if address < 0x4000:
            return bank == 0 and address + size <= 0x4000
        if address < 0x8000:
            return bank == self.bank and address + size <= 0x8000
        if 0xC000 <= address < 0xD000:
            return bank == 0 and address + size <= 0xD000
        if 0xD000 <= address < 0xE000:
            return bank == self.wram_bank and address + size <= 0xE000
        if 0xA000 <= address < 0xC000:
            return bank == self.sram_bank and address + size <= 0xC000
        return bank == 0 and address >= 0xFF80 and address + size <= 0xFFFF

    def read(self, address, domain):
        if domain == "ROM":
            return self.rom.get(address, 0)
        if domain == "System Bus" and address < 0x8000:
            flat = address if address < 0x4000 else self.bank * 0x4000 + address - 0x4000
            return self.rom.get(flat, 0)
        if domain == "System Bus" and address == self.p["ram"]["hROMBank"]:
            return self.shadow
        return self.memory.get((domain, address), 0)

    def field(self, name, value, width=1):
        address = self.fields[name]["addr"] if name in self.fields else self.p["ram"][name]
        for offset in range(width):
            self.memory["System Bus", address + offset] = value >> (8 * offset) & 255

    @staticmethod
    def mon(species=25, ot=0x1234, dvs=0x2AAA, nickname=0x81, hp=30):
        return {"species": species, "ot": ot, "dvs": dvs, "nickname": nickname, "hp": hp}

    def collection(self, mons, capacity, stride):
        record_start = capacity + 2
        ot_start = record_start + capacity * stride
        nick_start = ot_start + capacity * 11
        raw = bytearray(nick_start + capacity * 11)
        raw[0] = len(mons)
        raw[len(mons) + 1] = 255
        for i, mon in enumerate(mons):
            raw[i + 1] = mon["species"]
            start = record_start + i * stride
            raw[start] = mon["species"]
            raw[start + 6:start + 8] = mon["ot"].to_bytes(2, "big")
            raw[start + 21:start + 23] = mon["dvs"].to_bytes(2, "big")
            raw[start + 31] = 20
            if stride == 48:
                raw[start + 34:start + 36] = mon["hp"].to_bytes(2, "big")
                raw[start + 36:start + 38] = (50).to_bytes(2, "big")
            raw[ot_start + i * 11:ot_start + i * 11 + 2] = bytes([0x80, 0x50])
            raw[nick_start + i * 11:nick_start + i * 11 + 2] = bytes([mon["nickname"], 0x50])
        return raw

    def party(self, mons):
        for offset, value in enumerate(self.collection(mons, 6, 48)):
            self.memory["System Bus", self.p["ram"]["wPartyCount"] + offset] = value

    def box(self, mons):
        for offset, value in enumerate(self.collection(mons, 20, 32)):
            self.memory["CartRAM", self.p["derived"]["active_box_flat"] + offset] = value

    def fire(self, site_id, *, wrong_pc=False, wrong_shadow=False, wrong_mapping=False):
        site = self.sites[site_id]
        self.reg["PC"] = site["addr"] + int(wrong_pc)
        self.bank, self.shadow = site["bank"], site["bank"] + int(wrong_shadow)
        if wrong_mapping:
            self.bank += 1
        callbacks = [callback for callback, address in self.callbacks.values() if address == site["addr"]]
        assert callbacks
        for callback in callbacks:
            callback()

    def set_guards(self, site_id):
        guards = self.sites[site_id]["guards"]
        for register, value in guards.get("registers", {}).items():
            self.reg[register] = value
        for field in guards.get("memory_equals", []):
            self.field(field["symbol"], field["value"], field["width"])
        for field in guards.get("stack_words_equals", []):
            address = self.reg["SP"] + field["sp_offset"]
            self.memory["System Bus", address] = field["value"] & 255
            self.memory["System Bus", address + 1] = field["value"] >> 8
        for flag, value in guards.get("flags", {}).items():
            mask = {"Z": 0x80, "C": 0x10}[flag]
            self.reg["F"] = self.reg["F"] & ~mask | (mask if value else 0)

    @staticmethod
    def events(binder):
        batches = binder.drain(binder)
        return [event for batch in batches.values() for event in batch.events.values()]


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_source_candidate_cannot_register_production_hooks(title):
    world = World(title)
    options = world.options()
    options.runtime_qualification = world.lua.table(qualified=True, allow_candidate=True)
    service, reason = world.module.new(options)
    assert service is None and "qualification" in reason.lower()
    assert world.callbacks == {}


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_model_party_capture_waits_for_final_name_and_consumes_once(title):
    world = World(title)
    binder = world.bind()
    world.fire("capture_party_finalized")
    assert world.events(binder) == []
    world.fire("capture_party")
    assert not any(event.kind == "capture" for event in world.events(binder))
    world.party([world.mon(nickname=0x82)])
    world.fire("capture_party_finalized")
    captures = [event for event in world.events(binder) if event.kind == "capture"]
    assert len(captures) == 1
    event = captures[0]
    assert event.mon.key == "2AAA:1234:19" and event.mon.nickname_raw_hex.startswith("8250")
    assert event.evidence_level == "MODEL" and event.runtime_authorized is False
    world.fire("capture_party_finalized")
    assert world.events(binder) == []


@pytest.mark.parametrize("boundary", ["failure", "cancel", "reset", "reload", "source_change"])
def test_failed_cancelled_or_reset_operation_cannot_reuse_capture_latch(boundary):
    world = World()
    binder = world.bind()
    world.fire("capture_party")
    binder.boundary(binder, boundary)
    world.fire("capture_party_finalized")
    assert world.events(binder) == []


def test_roamer_classifier_decorates_one_capture_and_does_not_double_consume():
    world = World()
    binder = world.bind()
    world.party([world.mon(species=243)])
    world.field("wCurPartySpecies", 243)
    world.field("wBattleType", 5)
    world.fire("capture_party")
    world.events(binder)
    world.fire("capture_party_finalized")
    events = world.events(binder)
    captures = [event for event in events if event.kind == "capture"]
    assert len(captures) == 1 and captures[0].area_id == "legend_243"
    assert captures[0].acquisition == "roamer"
    assert "roamer_party_finalized" in list(captures[0].classifications.values())


def test_hatch_slot_latch_allows_source_ot_finalization_but_not_another_mon():
    world = World()
    binder = world.bind()
    world.fire("hatch_species")
    world.events(binder)
    world.party([world.mon(ot=0x5678, nickname=0x83)])
    world.fire("hatch_finalized")
    event = world.events(binder)[0]
    assert event.kind == "capture" and event.area_id == "gift_daycare"
    assert event.mon.key == "2AAA:5678:19"


@pytest.mark.parametrize("fault", ["pc", "shadow", "mapped_bank", "wram", "generation", "identity", "hold"])
def test_wrong_execution_or_stale_identity_never_publishes_capture(fault):
    world = World()
    binder = world.bind()
    world.fire("capture_party")
    world.events(binder)
    if fault == "wram":
        world.wram_bank = 2
    elif fault == "generation":
        world.generation += 1
    elif fault == "identity":
        world.party([world.mon(dvs=0x3AAA)])
    elif fault == "hold":
        world.held = False
    world.fire("capture_party_finalized", wrong_pc=fault == "pc", wrong_shadow=fault == "shadow",
               wrong_mapping=fault == "mapped_bank")
    assert not any(event.kind == "capture" for event in world.events(binder))


@pytest.mark.parametrize("fault", ["kind", "instruction", "bytes", "title", "authority", "prior", "script_bytes"])
def test_all_site_validation_precedes_model_registration(fault):
    world = World()
    if fault == "kind":
        world.sites["capture_party"]["kind"] = "SCRIPT_BYTECODE"
    elif fault == "instruction":
        world.sites["capture_party"]["instructions"] = ["special HealParty"]
    elif fault == "bytes":
        world.sites["capture_party"]["expected_hex"] = "00"
    elif fault == "title":
        world.pack["source"]["artifact"] = "pokegold"
    elif fault == "authority":
        world.authority.allow_model_registration = False
    elif fault == "prior":
        world.sites["capture_party_finalized"]["guards"] = {}
    else:
        world.sites["whiteout_before_heal"]["guards"]["script_context"]["expected_hex"] = "00"
    result = world.module.new_model(world.options())
    assert isinstance(result, tuple) and result[0] is None
    assert world.callbacks == {}


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_box_capture_and_contest_box_require_a_real_prior_insertion(title):
    world = World(title)
    binder = world.bind()
    world.box([world.mon()])
    world.fire("contest_box_finalized")
    assert world.events(binder) == []  # The capacity-refusal path reaches this same RET.
    world.fire("contest_box_inserted")
    world.box([world.mon(nickname=0x84)])
    world.fire("contest_box_finalized")
    event = world.events(binder)[0]
    assert event.kind == "capture" and event.destination == "box"
    assert event.area_id == "national_park_contest" and event.mon.nickname_raw_hex.startswith("8450")
    world.operation = "ordinary-box"
    world.fire("capture_box")
    world.events(binder)
    world.fire("capture_box_finalized")
    event = world.events(binder)[0]
    assert event.destination == "box" and event.area_id == "route_29"


@pytest.mark.parametrize("fault", [None, "special_index", "script_pos", "caller", "stack_bounds", "live_hp"])
def test_whiteout_is_cpu_dispatch_with_complete_preheal_guards(fault):
    world = World()
    binder = world.bind()
    world.party([world.mon(hp=0)])
    world.set_guards("whiteout_before_heal")
    if fault == "special_index":
        world.reg["DE"] += 1
    elif fault == "script_pos":
        world.field("wScriptPos", 0, 2)
    elif fault == "caller":
        world.memory["System Bus", world.reg["SP"]] ^= 1
    elif fault == "stack_bounds":
        world.reg["SP"] = world.stack["exclusive_stack_end"] - 1
    elif fault == "live_hp":
        world.party([world.mon(hp=1)])
    world.fire("whiteout_before_heal")
    events = world.events(binder)
    if fault is None:
        assert len(events) == 1 and events[0].kind == "whiteout"
        assert events[0].party.mons[1].hp == 0 and events[0].runtime_authorized is False
    else:
        assert events == []


def test_actual_bank_mapping_refuses_even_when_wrong_bank_bytes_match():
    world = World()
    binder = world.bind()
    world.fire("capture_party")
    site = world.sites["capture_party_finalized"]
    wrong_flat = (site["bank"] + 1) * 0x4000 + site["addr"] - 0x4000
    for offset, value in enumerate(bytes.fromhex(site["expected_hex"])):
        world.rom[wrong_flat + offset] = value
    world.fire("capture_party_finalized", wrong_mapping=True)
    assert world.events(binder) == []
    assert "actual mapped ROM bank" in binder.status(binder).failed


def test_changed_hatch_slot_permanently_retires_the_prior_attempt():
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon(species=172)])
    world.fire("hatch_species")
    world.field("wCurPartyMon", 1)
    world.fire("hatch_finalized")
    assert world.events(binder) == []
    world.field("wCurPartyMon", 0)
    world.fire("hatch_finalized")
    assert world.events(binder) == []


def test_unimplemented_gift_context_is_explicit_and_close_uses_shared_lifecycle():
    world = World()
    binder = world.bind()
    world.fire("gift_begin")
    assert world.events(binder) == []
    assert "OPEN" in binder.status(binder).refusals.gift_begin
    count = len(world.callbacks)
    assert binder.close(binder) is True
    assert len(world.removed) == count and not world.callbacks


def test_scripted_static_with_normal_battle_type_is_not_guessed_as_wild():
    world = World()
    binder = world.bind()
    world.field("wBattleScriptFlags", 128)
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    assert world.events(binder) == []
    status = binder.status(binder)
    assert status.failed is None and "scripted/static" in status.refusals.capture_party_finalized


def test_duplicate_insertion_and_duplicate_key_are_fail_closed():
    world = World()
    binder = world.bind()
    world.fire("capture_party")
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    assert world.events(binder) == []
    assert binder.status(binder).failed is None
    assert "duplicate acquisition start" in binder.status(binder).refusals.capture_party
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon()])
    world.fire("capture_party")
    assert world.events(binder) == []
    assert "ambiguous receiver identity" in binder.status(binder).refusals.capture_party


@pytest.mark.parametrize("site", ["soft_reset", "new_game", "continue_confirmed", "battle_end"])
def test_native_lifecycle_sites_discard_pending_acquisition(site):
    world = World()
    binder = world.bind()
    world.fire("capture_party")
    world.fire(site)
    world.events(binder)
    world.fire("capture_party_finalized")
    assert world.events(binder) == []
    assert binder.status(binder).pending_acquisitions == 0


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("action", ["deposit", "withdraw", "release_party", "release_box", "npc_trade"])
def test_pc_and_npc_completion_correlate_full_identity_through_compaction(title, action):
    world = World(title)
    binder = world.bind()
    outgoing = world.mon(species=25)
    survivor = world.mon(species=172, dvs=0x3AAA)
    boxed = world.mon(species=133, dvs=0x4AAA)
    received = world.mon(species=66, ot=0x5678, dvs=0xABCD, nickname=0x84)
    if action in {"deposit", "release_party", "npc_trade"}:
        world.party([outgoing, survivor])
        world.box([boxed])
        world.field("wCurPartyMon", 0)
    else:
        world.party([survivor])
        world.box([boxed, outgoing])
        world.field("wCurPartyMon", 1)
    start = "npc_trade_begin" if action == "npc_trade" else "pc_" + action + "_begin"
    final = "npc_trade_finalized" if action == "npc_trade" else "pc_" + action + "_complete"
    world.fire(start)
    assert world.events(binder) == []
    if action == "deposit":
        world.party([survivor])
        world.box([boxed, outgoing])
    elif action == "withdraw":
        world.party([survivor, outgoing])
        world.box([boxed])
    elif action == "release_party":
        world.party([survivor])
    elif action == "release_box":
        world.box([boxed])
    else:
        world.party([survivor, received])
        # Native trade restores the outgoing index. Receiver is last, not index0.
        world.field("wCurPartyMon", 0)
    world.fire(final)
    event = world.events(binder)[0]
    assert event.old_key == "2AAA:1234:19"
    assert event.kind == {"deposit": "party_to_box", "withdraw": "box_to_party",
                          "release_party": "pc_release", "release_box": "pc_release",
                          "npc_trade": "key_change"}[action]
    assert event.mon.key == ("ABCD:5678:42" if action == "npc_trade" else "2AAA:1234:19")
    assert event.runtime_authorized is False
    world.fire(final)
    assert world.events(binder) == []


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_change_box_matches_requested_destination_without_claiming_durability(title):
    world = World(title)
    binder = world.bind()
    world.reg["DE"] = 2
    world.fire("change_box_begin")
    world.field("wCurBox", 2)
    world.box([world.mon(species=133)])
    world.fire("change_box_loaded")
    event = world.events(binder)[0]
    assert (event.kind, event.old_box, event.new_box) == ("box_change", 0, 2)
    assert event.persistence == "OPEN" and event.runtime_authorized is False


def test_pc_failure_or_ambiguous_identity_cannot_publish_completion():
    world = World()
    binder = world.bind()
    world.fire("pc_deposit_begin")
    world.fire("pc_deposit_complete")  # No successful copy or compaction happened.
    assert world.events(binder) == []
    assert "topology" in binder.status(binder).refusals.pc_deposit_complete
    world = World()
    binder = world.bind()
    world.box([world.mon()])  # Same FULL key exists in both collections.
    world.fire("pc_deposit_begin")
    assert world.events(binder) == []
    assert "ambiguous across party/active box" in binder.status(binder).refusals.pc_deposit_begin


# ── boundaries deliver what was finalized before them (item 1) ──────────────────────────
@pytest.mark.parametrize("boundary", ["battle_end", "soft_reset", "new_game", "continue_confirmed",
                                      "failure", "reset", "reload"])
def test_a_boundary_delivers_a_capture_finalized_before_it(boundary):
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon(species=19, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")  # same frame: nothing drained yet
    if boundary in world.sites:
        world.fire(boundary)
    else:
        binder.boundary(binder, boundary)
    events = world.events(binder)
    assert [event.kind for event in events if event.kind == "capture"] == ["capture"]
    assert events[0].kind == "capture"  # delivered in engine order, before the boundary's own event
    assert binder.status(binder).failed is None


def test_only_a_stale_observation_is_dropped_and_the_drop_is_recorded():
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon(species=19, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.fire("battle_faint")  # settles against a later read: meaningless in a new epoch
    world.generation += 1
    binder.boundary(binder, "reset")
    events = world.events(binder)
    assert [event.kind for event in events] == ["capture"]
    drop = binder.status(binder).drops.battle_faint
    assert drop.count == 1 and "stale" in drop.reason


# ── a refusal is a value, not a kill switch (item 2) ────────────────────────────────────
def test_one_scripted_static_refusal_does_not_silence_later_signals():
    world = World()
    binder = world.bind()
    world.field("wBattleScriptFlags", 128)
    world.party([world.mon(), world.mon(species=243, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    assert world.events(binder) == []
    world.field("wBattleScriptFlags", 0)
    world.party([world.mon(), world.mon(species=243, dvs=0x7AAA), world.mon(species=19, dvs=0x8AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    (event,) = world.events(binder)
    assert event.kind == "capture" and event.mon.key == "8AAA:1234:13"
    status = binder.status(binder)
    assert status.failed is None and "scripted/static" in status.refusals.capture_party_finalized


def test_a_refused_final_retires_its_latch():
    world = World()
    binder = world.bind()
    world.field("wBattleScriptFlags", 128)
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    world.field("wBattleScriptFlags", 0)
    world.fire("capture_party_finalized")  # the refused attempt cannot finalize later
    assert world.events(binder) == [] and binder.status(binder).pending_acquisitions == 0


# ── faint observations carry a same-frame identity (item 3) ─────────────────────────────
def test_battle_and_poison_faints_carry_the_fainting_record_identity():
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon(species=172, dvs=0x3AAA)])
    world.field("wCurBattleMon", 1)
    world.fire("battle_faint")
    (event,) = world.events(binder)
    assert (event.kind, event.cause, event.slot, event.mon.key) == ("faint", "battle", 1, "3AAA:1234:AC")
    world.party([world.mon(hp=0), world.mon(species=172, dvs=0x3AAA)])
    world.field("wCurPartyMon", 0)
    world.fire("poison_faint")
    (event,) = world.events(binder)
    assert (event.kind, event.cause, event.slot, event.mon.key) == ("faint", "poison", 0, "2AAA:1234:19")


def test_a_faint_on_an_unreadable_slot_is_refused_not_fatal():
    world = World()
    binder = world.bind()
    world.field("wCurBattleMon", 3)  # one-mon party
    world.fire("battle_faint")
    assert world.events(binder) == []
    status = binder.status(binder)
    assert status.failed is None and "slot" in status.refusals.battle_faint


# ── evolution publishes a key_change at the species-list store (item 4) ─────────────────
def evolve(world, slot, new_species, *, link_mode=0, a=None, hl_delta=0):
    world.field("wCurPartyMon", slot)
    world.field("wLinkMode", link_mode)
    world.reg["A"] = new_species if a is None else a
    world.reg["HL"] = world.p["ram"]["wPartySpecies"] + slot + hl_delta
    world.fire("evolution_species_published")


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_evolution_emits_key_change_from_the_source_pre_evolution(title):
    world = World(title)
    binder = world.bind()
    world.party([world.mon(species=133, dvs=0x3AAA), world.mon(species=26)])  # Pikachu -> Raichu
    world.field("wEvolutionOldSpecies", 40)  # ForgetMove's wListMovesLineSpacing alias store
    evolve(world, 1, 26)
    (event,) = world.events(binder)
    assert (event.kind, event.reason, event.slot) == ("key_change", "evolution", 1)
    assert (event.old_key, event.new_key, event.mon.key) == ("2AAA:1234:19", "2AAA:1234:1A", "2AAA:1234:1A")
    assert event.runtime_authorized is False


def test_cancelled_evolution_emits_nothing_and_the_next_slot_is_its_own():
    world = World()
    binder = world.bind()
    # Slot 0 was B-cancelled: CancelEvolution jumps back to the master loop without reaching
    # the species-list store, so its record is unchanged and nothing fires for it.
    world.party([world.mon(species=25), world.mon(species=2, dvs=0x3AAA)])
    assert world.events(binder) == []
    evolve(world, 1, 2)  # slot 1 (Bulbasaur -> Ivysaur) evolves in the same pass
    (event,) = world.events(binder)
    assert (event.slot, event.old_key, event.new_key) == (1, "3AAA:1234:01", "3AAA:1234:02")


@pytest.mark.parametrize("fault", ["a_register", "hl_register", "no_pre_evolution", "link_trade", "duplicate"])
def test_unqualified_evolution_context_is_refused_and_signals_keep_flowing(fault):
    world = World()
    binder = world.bind()
    party = [world.mon(species=26)]
    if fault == "duplicate":
        party.append(world.mon(species=25))  # the old key would name two records
    species = 1 if fault == "no_pre_evolution" else 26
    if fault == "no_pre_evolution":
        party = [world.mon(species=1)]
    world.party(party)
    evolve(world, 0, species, link_mode=2 if fault == "link_trade" else 0,
           a=27 if fault == "a_register" else None, hl_delta=int(fault == "hl_register"))
    assert not any(event.kind == "key_change" for event in world.events(binder))
    status = binder.status(binder)
    assert status.failed is None and status.refusals.evolution_species_published
    world.party([world.mon(species=26)])
    evolve(world, 0, 26)
    assert [event.kind for event in world.events(binder)] == ["key_change"]


# ── N3-1: register pairs are composed from BizHawk's single registers ──────────────────
def test_the_register_fake_is_bizhawk_faithful():
    registers = Registers(0xC020)
    registers["HL"] = 0xDCDF
    assert (registers["H"], registers["L"], bizhawk_register(registers, "L")) == (0xDC, 0xDF, 0xDF)
    assert bizhawk_register(registers, "WRAM BANK") == 0 and bizhawk_register(registers, "SP") == 0xC020
    for pair in PAIRS:
        with pytest.raises(KeyError, match="singles only"):
            bizhawk_register(registers, pair)


def test_an_unavailable_single_register_is_a_refusal_not_a_stop():
    world = World()
    binder = world.bind()
    world.party([world.mon(hp=0)])
    world.set_guards("whiteout_before_heal")
    del world.reg["E"]  # the emulator answers nil for it
    world.fire("whiteout_before_heal")
    assert world.events(binder) == []
    status = binder.status(binder)
    assert status.failed is None and "CPU register E unavailable" in status.refusals.whiteout_before_heal
    world.set_guards("whiteout_before_heal")
    world.fire("whiteout_before_heal")
    assert [event.kind for event in world.events(binder)] == ["whiteout"]


def test_a_16_bit_register_guard_is_compared_not_refused():
    """R3 I-1: PC/SP are 16-bit singles; a guard on SP compares instead of refusing as out of range."""
    world = World()
    world.sites["whiteout_before_heal"]["guards"]["registers"]["SP"] = world.reg["SP"]
    binder = world.bind()
    world.party([world.mon(hp=0)])
    world.set_guards("whiteout_before_heal")
    world.fire("whiteout_before_heal")
    assert [event.kind for event in world.events(binder)] == ["whiteout"]
    assert binder.status(binder).failed is None


# ── N3-2: a native failure branch between start and completion strands no event ────────
def test_a_deposit_into_a_full_box_does_not_swallow_the_next_deposit():
    world = World()
    binder = world.bind()
    a, b = world.mon(species=25), world.mon(species=172, dvs=0x3AAA)
    world.party([a, b])
    world.field("wCurPartyMon", 0)
    world.fire("pc_deposit_begin")  # SendGetMonIntoFromBox carry -> .BoxFull: no completion
    assert world.events(binder) == []
    world.fire("pc_deposit_begin")  # the next attempt (after a box change)
    world.party([b])
    world.box([a])
    world.fire("pc_deposit_complete")
    (event,) = world.events(binder)
    assert (event.kind, event.mon.key) == ("party_to_box", "2AAA:1234:19")
    status = binder.status(binder)
    assert status.failed is None and status.refusals.pc_deposit_begin is None
    assert status.drops.pc_deposit_begin.count == 1 and "superseded" in status.drops.pc_deposit_begin.reason
    assert status.pending_acquisitions == 0


def test_a_withdraw_into_a_full_party_does_not_swallow_the_next_withdraw():
    world = World()
    binder = world.bind()
    lead, boxed = world.mon(species=25), world.mon(species=172, dvs=0x3AAA)
    world.party([lead])
    world.box([boxed])
    world.field("wCurPartyMon", 0)
    world.fire("pc_withdraw_begin")  # carry -> .PartyFull
    world.fire("pc_withdraw_begin")
    world.party([lead, boxed])
    world.box([])
    world.fire("pc_withdraw_complete")
    assert [(event.kind, event.mon.key) for event in world.events(binder)] == [("box_to_party", "3AAA:1234:AC")]
    assert binder.status(binder).drops.pc_withdraw_begin.count == 1


def test_a_declined_box_change_does_not_swallow_the_next_box_change():
    world = World()
    binder = world.bind()
    world.reg["DE"] = 3
    world.fire("change_box_begin")  # YesNoBox "No" -> .refused
    world.reg["DE"] = 2
    world.fire("change_box_begin")
    world.field("wCurBox", 2)
    world.box([world.mon(species=133)])
    world.fire("change_box_loaded")
    (event,) = world.events(binder)
    assert (event.kind, event.old_box, event.new_box) == ("box_change", 0, 2)
    assert binder.status(binder).drops.change_box_begin.count == 1


# ── N3-3: an acquisition the binder refused after the engine inserted a mon is counted ──
def test_refused_acquisitions_count_refusals_after_insertion_not_failed_throws():
    world = World()
    binder = world.bind()
    count = lambda: binder.status(binder).refused_acquisitions  # noqa: E731
    world.fire("capture_party_finalized")  # a missed throw reaches the same RET with no insertion
    assert world.events(binder) == [] and count() == 0
    world.party([world.mon(), world.mon(species=19, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")
    assert [event.kind for event in world.events(binder)] == ["capture"] and count() == 0
    world.party([world.mon(), world.mon()])  # the caught record equals the lead: ambiguous
    world.fire("capture_party")
    assert world.events(binder) == [] and count() == 1
    world.party([world.mon(), world.mon(species=19, dvs=0x8AAA)])
    world.fire("capture_party")  # inserted, then the battle ends before the final name
    world.fire("battle_end")
    assert [event.kind for event in world.events(binder)] == ["observation"] and count() == 2


# ── R4 S2: an abandoned timeline is not a natural boundary ─────────────────────────────────────
def test_an_abandoned_timeline_discards_finalized_batches_and_retires_latches():
    world = World()
    binder = world.bind()
    world.party([world.mon(), world.mon(species=19, dvs=0x7AAA)])
    world.fire("capture_party")
    world.fire("capture_party_finalized")  # finalized but not drained
    world.party([world.mon(), world.mon(species=19, dvs=0x7AAA), world.mon(species=16, dvs=0x5AAA)])
    world.fire("capture_party")  # a second insertion: an open acquisition latch
    assert binder.status(binder).pending_acquisitions == 1
    binder.abandon(binder, "savestate load")
    assert world.events(binder) == []
    status = binder.status(binder)
    assert status.pending_acquisitions == 0 and status.failed is None
    assert status.drops.abandoned_timeline.count == 1 and "savestate load" in status.drops.abandoned_timeline.reason
    world.fire("capture_party_finalized")  # the resumed timeline has no insertion behind this final
    assert [event.kind for event in world.events(binder)] == []


# Every ROMX bank's code runs at $4000-$7FFF, so most hits are some OTHER bank at a site's PC.
# N13b: that reject path reads nothing held and builds nothing; the held operation is stamped
# only once the bank matches (the next accepted hit or drain() stamps first, so a deferred
# operation change is cleared before any latch is read).
def test_wrong_bank_hits_stamp_nothing_and_allocate_nothing():
    world = World()
    stamps = {"n": 0}
    capture = world.authority.capture

    def counted():
        stamps["n"] += 1
        return capture()

    world.authority.capture = counted
    binder = world.bind()
    site = world.sites["capture_party"]
    assert site["addr"] >= 0x4000
    world.bank, world.shadow, world.reg["PC"] = site["bank"], site["bank"] + 1, site["addr"]
    fns = world.lua.table(*[cb for cb, address in world.callbacks.values() if address == site["addr"]])
    k, probe = 500, world.lua.eval("""function(fns, k)
        for _, fn in ipairs(fns) do fn() end  -- warm-up
        collectgarbage("collect"); collectgarbage("stop")
        local before = collectgarbage("count")
        for _ = 1, k do for _, fn in ipairs(fns) do fn() end end
        local grown = collectgarbage("count") - before
        collectgarbage("restart")
        return grown
    end""")
    grown = probe(fns, 4 * k) - probe(fns, k)  # per-hit growth only; lupa's fixed overhead cancels
    assert stamps["n"] == 0, f"{stamps['n']} held stamps on wrong-bank hits"
    assert grown < 1.0, f"{grown:.1f} KB allocated by {3 * k} extra wrong-bank hits"
    assert binder.status(binder).failed is None and world.events(binder) == []
    # the bank-matched path is unchanged: stamped, latched, finalized once
    world.fire("capture_party")
    assert stamps["n"] >= 2  # the drain above, then this hit
    world.events(binder)
    world.party([world.mon(nickname=0x82)])
    world.fire("capture_party_finalized")
    assert [event.kind for event in world.events(binder)] == ["capture"]
