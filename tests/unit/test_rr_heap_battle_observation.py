"""Modeled host callbacks plus the real read-only heap reader; no emulator runs."""
from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lua/tests/rr/heap_battle_observation.lua"
HEAP, ROOT_PTR, SIZE_PTR = 0x02000000, 0x03000A38, 0x03000A3C
POINTS = {"init": (0x08002B80, 0x08002B8E), "alloc": (0x08002B9C, 0x08002BA8),
          "alloc_zeroed": (0x08002BB0, 0x08002BBC), "free": (0x08002BC4, 0x08002BD0)}
ROM_BYTES = {
    0x08002B80: "00b5044a1060044a1160fff7ddfe01bc00470000380a00033c0a0003",
    0x08002B9C: "00b5011c02480068fff7dafe02bc0847380a0003",
    0x08002BB0: "00b5011c02480068fff796ff02bc0847380a0003",
    0x08002BC4: "00b5011c02480068fff71cff01bc0047380a0003",
    0x0800051A: "78f329fd", 0x081E3B14: "80b584b06f4638607960ba60",
}


class Model:
    def __init__(self, fault=None, *, options=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.ram, self.callbacks, self.registrations, self.cleanup = {}, {}, [], []
        self.frame, self.fault, self.inject, self.parent_called = 0, fault, False, False
        self.register_reads = 0
        self.assertions, self.checkpoints, self.regs = [], [], {"R0": 0, "R1": 0, "R14": 0, "R15": 0, "CPSR": 0x20}
        for address, data in ROM_BYTES.items():
            for i, value in enumerate(bytes.fromhex(data)):
                self.ram[address + i] = value
        globals_ = self.lua.globals()
        globals_._frame = lambda: self.frame
        globals_._register = self.register
        globals_._unregister = self.unregister
        globals_._registers = self.registers
        globals_._read8 = lambda a, domain: self.read(a, 1, domain)
        globals_._read16 = lambda a, domain: self.read(a, 2, domain)
        globals_._read32 = lambda a, domain: self.read(a, 4, domain)
        globals_._load = self.load
        globals_._parent = self.parent
        globals_._check = self.check
        globals_._checkpoint = self.checkpoint
        self.lua.execute('''
            emu={framecount=function() return _frame() end, getregisters=function() return _registers() end,
                 frameadvance=function() error("wrapper must not advance frames") end,
                 yield=function() error("wrapper must not yield") end}
            memory={read_u8=function(a,d) return _read8(a,d) end,
                    read_u16_le=function(a,d) return _read16(a,d) end,
                    read_u32_le=function(a,d) return _read32(a,d) end}
            event={on_bus_exec=function(cb,a,n,s) return _register(cb,a,n,s) end,
                   unregisterbyname=function(n) return _unregister(n) end}
            dofile=function(path) return _load(path) end
        ''')
        self.report = self.lua.table_from({"evidence": self.lua.table()})
        self.context = self.lua.table_from({
            "config": self.lua.table_from({
                "source_root": ROOT.as_posix(), "purpose": "validation",
                "identity": self.lua.table_from({"run_id": "heap_test", "player": "a",
                    "rom_sha256": "3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301"}),
                "descriptor": self.lua.table_from({"build_id": "a568a586fee86a54150bd09d148f78eb7e85f6b521b58a2d56a043a5dd8d101c"}),
                "probe_options": self.lua.table_from({"heap_observation": self.lua.table_from(options or {})}),
            }),
            "report": self.report,
            "check": self.lua.eval("function(n,a,e) return _check(n,a,e) end"),
            "checkpoint": self.lua.eval("function(name) return _checkpoint(name) end"),
        })

    def write(self, address, value, width=4):
        for i in range(width):
            self.ram[address + i] = value >> (i * 8) & 255

    def read(self, address, width, domain):
        assert domain == "System Bus"
        if self.inject and self.fault == "heap_read" and address == HEAP + 2:
            raise RuntimeError("modeled heap bus read failed")
        return sum(self.ram.get(address + i, 0) << (i * 8) for i in range(width))

    def header(self, address, used, size, previous, next_):
        self.write(address, used, 2)
        self.write(address + 2, 0xA3A3, 2)
        for offset, value in [(4, size), (8, previous), (12, next_)]:
            self.write(address + offset, value)

    def heap(self, allocated=0):
        self.write(ROOT_PTR, HEAP)
        self.write(SIZE_PTR, 128)
        if not allocated:
            self.header(HEAP, 0, 112, HEAP, HEAP)
        else:
            second = HEAP + 16 + allocated
            self.header(HEAP, 1, allocated, HEAP, second)
            self.header(second, 0, 128 - allocated - 32, HEAP, HEAP)

    def register(self, callback, address, name, scope):
        assert scope == "System Bus" and address not in self.callbacks
        self.registrations.append((name, address))
        self.callbacks[address] = (name, callback)
        index = len(self.registrations)
        if index == 4:
            if self.fault == "register_throw":
                raise RuntimeError("name installed before registration failed")
            if self.fault == "register_zero":
                return "00000000-0000-0000-0000-000000000000"
            if self.fault == "register_duplicate":
                return "00000000-0000-0000-0000-000000000001"
            if self.fault == "register_malformed":
                return "not-a-uuid"
            if self.fault == "install_frame":
                self.frame += 1
            if self.fault == "install_callback":
                callback()
        return f"00000000-0000-0000-0000-{index:012x}"

    def unregister(self, name):
        self.cleanup.append(name)
        if len(self.cleanup) == 3:
            if self.fault == "cleanup_throw":
                raise RuntimeError("modeled unregister failed")
            if self.fault == "cleanup_false":
                return False
        for address, (registered_name, _) in list(self.callbacks.items()):
            if registered_name == name:
                del self.callbacks[address]
                return True
        return False

    def registers(self):
        self.register_reads += 1
        if self.inject and self.fault == "register_read":
            raise RuntimeError("modeled register read failed")
        values = dict(self.regs)
        if self.inject and self.fault == "register_missing":
            values.pop("R14")
        return self.lua.table_from(values)

    def load(self, path):
        if path == (ROOT / "lua/rr/heap_snapshot.lua").as_posix():
            return self.lua.execute(Path(path).read_text(encoding="utf-8"))
        assert path == (ROOT / "lua/tests/rr/ghost_natural_battle_probe.lua").as_posix()
        return self.lua.eval("function(ctx) return _parent(ctx) end")

    def check(self, name, actual, expected):
        self.assertions.append(name)
        assert actual == expected, name

    def checkpoint(self, name):
        out = self.report.evidence.heap
        self.checkpoints.append({"name": name, "assert_hits": out.assert_hits,
                                 "parent_returned": out.parent_returned,
                                 "first_failure": out.failures[1].code,
                                 "address": out.fatal_context and out.fatal_context.address,
                                 "registers": out.fatal_context and out.fatal_context.registers})
        if self.fault == "checkpoint_throw":
            raise RuntimeError("modeled checkpoint failure")
        if self.fault == "checkpoint_reenter":
            self.fire(0x081E3B14)

    def fire(self, address, r0=0, r1=0, lr=0x08012345):
        self.regs.update(R0=r0, R1=r1, R14=lr, R15=address + 4, CPSR=0x20)
        self.callbacks[address][1]()

    def parent(self, ctx):
        self.parent_called = True
        ctx.report.evidence.runtime = self.lua.table_from({"parent_marker": "untouched", "release_ready": False})
        if self.fault != "no_frame":
            self.fire(0x0800051A)
        self.fire(POINTS["init"][0], HEAP, 128, 0x080003F9)
        if self.fault == "unfinished":
            return
        self.heap()
        self.frame += 1  # modeled guest operation may span frame boundaries
        self.fire(POINTS["init"][1], HEAP, 128, POINTS["init"][1] | 1)
        ctx.check("modeled_parent_init", True, True)
        if self.fault == "parent":
            raise RuntimeError("modeled parent failed")
        if self.fault in ("assert", "checkpoint_throw", "checkpoint_reenter"):
            self.fire(0x081E3B14)
            ctx.check("modeled_after_assert", True, True)
        if self.fault == "unmatched":
            self.fire(POINTS["free"][1])
            ctx.check("modeled_after_unmatched", True, True)
        self.inject = True
        self.fire(POINTS["alloc"][0], 32, 0, 0x08045679)
        ctx.check("modeled_parent_alloc_entry", True, True)
        self.heap(32)
        self.fire(POINTS["alloc"][1], HEAP + 16, 0, POINTS["alloc"][1] | 1)
        ctx.check("modeled_parent_alloc_post", True, True)
        self.fire(POINTS["free"][0], HEAP + 16)
        self.heap()
        self.fire(POINTS["free"][1], 0, 0, POINTS["free"][1] | 1)
        self.fire(POINTS["alloc_zeroed"][0], 16)
        self.heap(16)
        self.fire(POINTS["alloc_zeroed"][1], HEAP + 16, 0, POINTS["alloc_zeroed"][1] | 1)
        self.fire(POINTS["free"][0], HEAP + 16)
        self.heap()
        self.fire(POINTS["free"][1], 0, 0, POINTS["free"][1] | 1)
        self.frame += 1
        if self.fault != "no_frame":
            self.fire(0x0800051A)
        ctx.check("modeled_parent_complete", True, True)

    def run(self):
        self.lua.execute(SCRIPT.read_text(encoding="utf-8"))(self.context)


def test_wrapper_retains_real_reader_statistics_and_entry_callers_without_own_frame_work():
    h = Model()
    h.run()
    out = h.report.evidence.heap
    assert out.complete is True and out.release_ready is False and out.complete_peak_coverage is False
    assert h.report.evidence.runtime.parent_marker == "untouched"
    assert len(h.registrations) == len(h.cleanup) == 10 and not h.callbacks
    assert out.frame_control.hits == 2 and out.counts.init.entry == out.counts.init.post == 1
    assert out.counts.alloc.entry == out.counts.alloc.post == 1
    assert out.counts.free.entry == out.counts.free.post == 2
    assert out.before.available is False and out.before.reason == "uninitialized_or_invalid_extent"
    assert out.before.free_bytes is None and out.unavailable_snapshots == 2
    assert out.extents[1].min_free_bytes == out.extents[1].min_largest_free == 64
    assert out.extents[1].max_allocated_bytes == 32
    rows = [row for row in out.trace.values() if row.operation == "alloc"]
    assert rows[0].args.size == 32 and rows[1].result_pointer == HEAP + 16
    assert rows[0].call_id == rows[1].call_id and rows[1].caller == 0x08045679
    assert rows[1].registers["R14"] == POINTS["alloc"][1] | 1
    assert out.after.free_bytes == 112 and out.parent_returned is True
    assert {"heap_observation_frame_control", "heap_observation_no_agb_assert",
            "heap_observation_init_observed", "heap_observation_alloc_observed",
            "heap_observation_free_observed"} <= set(h.assertions)
    assert not h.checkpoints


@pytest.mark.parametrize("fault", ["register_zero", "register_duplicate", "register_malformed", "register_throw", "install_frame", "install_callback"])
def test_partial_registration_cleans_every_attempted_name_and_never_starts_parent(fault):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert len(h.registrations) == len(h.cleanup) == 4
    assert h.cleanup == [name for name, _ in h.registrations]
    assert not h.callbacks and not h.parent_called
    assert h.report.evidence.heap.complete is False


@pytest.mark.parametrize("fault", ["cleanup_false", "cleanup_throw"])
def test_cleanup_failure_still_attempts_all_names_and_refuses_complete(fault):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_callbacks_removed"):
        h.run()
    assert len(h.cleanup) == 10 and len(h.callbacks) == 1
    assert h.report.evidence.heap.complete is False


@pytest.mark.parametrize("fault,counter", [("heap_read", "heap_read_errors"), ("register_read", "register_read_errors"),
                                          ("register_missing", "register_read_errors"), ("assert", "assert_hits"),
                                          ("unmatched", "pair_errors")])
def test_callback_read_pair_and_guest_assertion_failures_abort_and_cleanup(fault, counter):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert h.report.evidence.heap[counter] > 0
    assert len(h.cleanup) == 10 and not h.callbacks
    assert h.report.evidence.runtime.parent_marker == "untouched"


@pytest.mark.parametrize("options,counter", [({"max_records": 3}, "trace_overflow"), ({"max_blocks": 1}, "scan_overflow")])
def test_trace_and_heap_scan_overflow_are_failures_not_zero_capacity(options, counter):
    h = Model(options=options)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert h.report.evidence.heap[counter] > 0
    assert len(h.report.evidence.heap.trace) <= options.get("max_records", 8192)
    assert len(h.cleanup) == 10 and not h.callbacks


@pytest.mark.parametrize("fault", ["parent", "no_frame", "unfinished"])
def test_parent_failure_or_missing_positive_coverage_never_skips_cleanup(fault):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert len(h.cleanup) == 10 and not h.callbacks
    assert h.report.evidence.runtime.parent_marker == "untouched"
    assert h.report.evidence.heap.complete is False


def test_rom_byte_mismatch_refuses_instrumentation():
    h = Model()
    h.ram[POINTS["alloc"][0]] ^= 1
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert not h.registrations and not h.parent_called


@pytest.mark.parametrize("options", [False, {"max_records": False}, {"max_blocks": 0}, {"max_depth": "16"}, {"unknown": 1}])
def test_malformed_explicit_options_cannot_silently_use_defaults(options):
    h = Model()
    h.context.config.probe_options.heap_observation = h.lua.table_from(options) if isinstance(options, dict) else options
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert not h.registrations and not h.parent_called


@pytest.mark.parametrize("fault,first_failure", [("assert", "agb_assert_observed"),
                                                ("register_read", "register_read_failed"),
                                                ("heap_read", "heap_read_failed")])
def test_fatal_callback_is_checkpointed_before_parent_can_return(fault, first_failure):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert len(h.checkpoints) == 1
    saved = h.checkpoints[0]
    assert saved["first_failure"] == first_failure and saved["parent_returned"] is False
    assert saved["name"] == "heap_observation_fatal_" + first_failure
    if fault == "assert":
        assert saved["assert_hits"] == 1 and saved["address"] == 0x081E3B14
        assert saved["registers"]["R14"] == 0x08012345


@pytest.mark.parametrize("fault", ["checkpoint_throw", "checkpoint_reenter"])
def test_checkpoint_failure_or_reentrant_callback_does_not_loop_or_prevent_cleanup(fault):
    h = Model(fault)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert len(h.checkpoints) == 1 and len(h.cleanup) == 10 and not h.callbacks
    assert h.report.evidence.heap.fatal_checkpoint.call_ok is (fault != "checkpoint_throw")


@pytest.mark.parametrize("options,code", [({"max_records": 3}, "heap_trace_overflow"),
                                         ({"max_blocks": 1}, "heap_scan_overflow")])
def test_overflow_checkpoint_precedes_parent_return(options, code):
    h = Model(options=options)
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert len(h.checkpoints) == 1 and h.checkpoints[0]["parent_returned"] is False
    assert h.checkpoints[0]["first_failure"] == code
    assert h.report.evidence.heap.fatal_context.caller == 0x08045679


def test_missing_checkpoint_api_prevents_hook_installation():
    h = Model()
    h.context.checkpoint = None
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert not h.registrations and not h.parent_called


def test_callable_userdata_bindings_execute_and_validate_all_actual_results():
    h = Model()
    # Python callables are Lua userdata in Lupa; do not hide them in Lua closures.
    h.lua.execute('event.on_bus_exec=_register; event.unregisterbyname=_unregister; emu.getregisters=_registers')
    h.run()
    out = h.report.evidence.heap
    assert {out.api_types[name] for name in ("on_bus_exec", "unregisterbyname", "getregisters")} == {"userdata"}
    assert all(out.api_present[name] for name in ("on_bus_exec", "unregisterbyname", "getregisters"))
    assert out.preflight_registers.R14 == 0 and h.register_reads > 1
    assert len(h.registrations) == len(h.cleanup) == 10 and not h.callbacks
    assert out.complete is True and out.counts.alloc.post == 1


@pytest.mark.parametrize("binding", ["on_bus_exec", "unregisterbyname", "getregisters"])
@pytest.mark.parametrize("value", [None, False, 1, "not callable"])
def test_absent_or_nonsensical_binding_types_fail_before_instrumentation(binding, value):
    h = Model()
    table = h.lua.globals().emu if binding == "getregisters" else h.lua.globals().event
    table[binding] = value
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert not h.registrations and not h.parent_called
    assert h.report.evidence.heap.api_present[binding] is (value is not None)
    assert h.report.evidence.heap.failures[1].code == "heap_callback_api_unavailable"


@pytest.mark.parametrize("binding", ["on_bus_exec", "unregisterbyname", "getregisters"])
def test_noncallable_userdata_is_not_capability_evidence(binding):
    h = Model()
    table = h.lua.globals().emu if binding == "getregisters" else h.lua.globals().event
    table[binding] = object()  # userdata without a usable call implementation
    expected = "heap_observation_callbacks_removed" if binding != "getregisters" else "heap_observation_complete"
    with pytest.raises(AssertionError, match=expected):
        h.run()
    out = h.report.evidence.heap
    assert out.api_types[binding] == "userdata" and out.complete is False
    if binding == "getregisters":
        assert not h.registrations and not h.parent_called and out.register_read_errors == 1
    elif binding == "on_bus_exec":
        assert not h.registrations and not h.parent_called
        assert len(out.registration_attempts) == len(out.cleanup_attempts) == 1
        assert out.registration_attempts[1].call_ok is False
    else:
        assert len(out.registration_attempts) == len(out.cleanup_attempts) == 10
        assert all(row.call_ok is False for row in out.cleanup_attempts.values())


def test_userdata_register_reader_invalid_shape_is_rejected_before_hooks():
    h = Model()
    h.lua.globals().emu.getregisters = lambda: h.lua.table_from({"R0": 0})
    with pytest.raises(AssertionError, match="heap_observation_complete"):
        h.run()
    assert not h.registrations and not h.parent_called
    assert h.report.evidence.heap.register_read_errors == 1
