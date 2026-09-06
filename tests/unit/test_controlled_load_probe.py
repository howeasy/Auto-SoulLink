"""Actual probe/actuator/mailbox Lua with modeled host and native boundaries.

No routine/source rewriting and no emulator claim: the fake engine supplies only
the harmless PING dispatch/receipt and state restoration boundaries under test.
"""

import struct
from pathlib import Path

import pytest

from tests.rr.runtime.rr_harness import RRHarness
from tests.unit.test_controlled_load import busy_header
from tests.unit.test_platform_execution import HOST
from tools.rr.controlled_load import BATTERY_SHA256, ROM_SHA1, ROM_SHA256, SCHEMA

ROOT = Path(__file__).parents[2]
PROBE = ROOT / "lua/tests/rr/controlled_load_probe.lua"
BASE = 0x0203F800
DESCRIPTOR = 0x0837BF04
BUILD = "a568a586fee86a54150bd09d148f78eb7e85f6b521b58a2d56a043a5dd8d101c"
LAYOUT = "878066ab0db1dbff0bee8cd0935f5eabe2b0dc1b6259ff6d5af6c054843bdd56"


def table(lua, value):
    if isinstance(value, dict):
        return lua.table_from({k: table(lua, v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return lua.table_from([table(lua, v) for v in value])
    return value


class Probe:
    def __init__(self, mode="valid", fault=None):
        self.h = RRHarness(ROOT, load=False)
        self.lua = self.h.lua
        game_memory = self.lua.globals().memory
        self.lua.execute(HOST)
        self.lua.globals().memory = game_memory
        self.lua.execute("main.MaxFutureFrames=0;main.MovieSession={NewMovieQueued=false};T.seconds=0")
        profile = self.lua.execute(
            (ROOT / "lua/platform_execution.lua").read_text()
        ).supported_profile()
        self.lua.globals().setup(profile)
        self.state = self.lua.globals().T
        self.state.frame = 1
        self.lua.execute("""
            local import=luanet.import_type
            luanet.import_type=function(name)
                if name=='System.Diagnostics.Stopwatch' then return {StartNew=function()
                    return {Elapsed=setmetatable({}, {__index=function(_,key)
                        assert(key=='TotalSeconds');return T.seconds end})}
                end} end
                if name=='System.IO.File' then return {
                    Exists=function(path) return T.hashes[path]~=nil end,
                    ReadAllBytes=function(path) return assert(T.hashes[path],'unknown artifact path') end}
                end
                return import(name)
            end
        """)
        descriptor = bytearray(156)
        struct.pack_into("<IHHIIIHH", descriptor, 0, 0x32444C53, 1, 2, 156, 31, BASE, 64, 0xA2)
        descriptor[24:88] = BUILD.encode()
        descriptor[89:153] = LAYOUT.encode()
        self.h.seed(DESCRIPTOR, descriptor)
        self.h.seed(0x08378F70, bytes.fromhex("f0b5b84bb84c89b0"))
        self.mode, self.fault = mode, fault
        self.callbacks, self.assertions, self.checkpoints = {}, [], []
        self.native_calls, self.loads, self.saves, self.writes_after_load = 0, 0, 0, None
        self.saved_marker = busy_header()
        self.saved_frame = 1660
        self.producer_state = None
        experiment = {
            "schema": SCHEMA,
            "rom_sha1": ROM_SHA1,
            "rom_sha256": ROM_SHA256,
            "battery_sha256": BATTERY_SHA256,
            "saved_frame": self.saved_frame,
            "mailbox_hex": self.saved_marker.hex(),
            "general_interlock_proved": False,
            "release_ready": False,
            "valid": {"file_name": "busy_ping.State", "sha256": "d" * 64},
            "late_failure": {"file_name": "busy_late_failure.State", "sha256": "e" * 64},
        }
        source_root = ROOT.as_posix()
        self.state.hashes[source_root + "/probe_artifacts/busy_ping.State"] = "d" * 64
        self.state.hashes[source_root + "/probe_artifacts/busy_late_failure.State"] = "e" * 64
        if fault == "artifact_hash":
            self.state.hashes[source_root + "/probe_artifacts/busy_ping.State"] = "f" * 64
        self.config = table(
            self.lua,
            {
                "purpose": "validation",
                "fixture_kind": "battery",
                "frames": 1659,
                "identity": {
                    "rom_sha1": ROM_SHA1.upper(),
                    "rom_sha256": ROM_SHA256,
                    "fixture_sha256": BATTERY_SHA256,
                },
                "source_root": source_root,
                "result_path": "private/results/result.json",
                "fixture_meta": {
                    "boot_inputs": [{"frames": 600}, {"frames": 600}, {"frames": 456}],
                    "ram_assertions": [{"address": BASE, "width": 4, "expected": 0x4B4E4C53}],
                },
                "descriptor": {
                    "address": DESCRIPTOR,
                    "size": 156,
                    "hex": descriptor.hex(),
                    "build_id": BUILD,
                },
                "probe_options": {
                    "mode": mode,
                    "hold_ms": 250,
                    "owner_id": "a" * 32,
                    "expected_host": profile,
                    "experiment": experiment,
                },
            },
        )
        self.lua.globals().joypad = table(self.lua, {"set": lambda _buttons: None})
        self.lua.globals().emu.frameadvance = self.advance
        self.lua.globals().emu.yield_ = self.yield_held  # Avoid Python's reserved keyword.
        self.lua.globals().emu["yield"] = self.yield_held
        self.lua.globals().event = table(
            self.lua,
            {
                "on_bus_exec": self.register_exec,
                "onloadstate": self.register_load,
                "unregisterbyname": self.unregister,
            },
        )
        self.lua.globals().savestate = table(self.lua, {"save": self.save, "load": self.load})
        self.report = table(self.lua, {"evidence": {}})
        self.ctx = table(
            self.lua,
            {
                "config": self.config,
                "report": self.report,
                "check": self.check,
                "checkpoint": self.checkpoint,
                "host": {"available": True, "matches_requested_core": True},
                "main_form": self.lua.globals().main,
            },
        )

    def check(self, name, actual, expected):
        assert name not in [row[0] for row in self.assertions], f"duplicate assertion: {name}"
        self.assertions.append((name, actual, expected))
        if actual != expected:
            raise AssertionError(f"{name}: {actual!r} != {expected!r}")

    def checkpoint(self, name):
        self.checkpoints.append(name)

    def register_exec(self, callback, address, name, scope):
        assert self.state.blocked and scope == "System Bus"
        return self.register(callback, address, name)

    def register_load(self, callback, name):
        assert self.state.blocked
        return self.register(callback, None, name)

    def register(self, callback, address, name):
        self.callbacks[name] = (callback, address)
        if self.fault == "zero_registration":
            return "00000000-0000-0000-0000-000000000000"
        if self.fault == "duplicate_registration":
            return "00000000-0000-0000-0000-000000000001"
        return f"00000000-0000-0000-0000-{len(self.callbacks):012x}"

    def unregister(self, name):
        assert self.state.blocked
        if self.fault == "cleanup":
            return False
        return self.callbacks.pop(name, None) is not None

    def execute_callbacks(self):
        for callback, address in tuple(self.callbacks.values()):
            if address and not (self.fault == "missing_native_control" and address == 0x08378F70):
                callback(address, 0, 0)

    def advance(self):
        assert not self.state.blocked and self.loads == 0, (
            "forward execution after load or while held"
        )
        self.state.frame += 1
        self.lua.globals()._RR_FRAME = self.state.frame
        self.execute_callbacks()
        if self.h.u16(BASE + 6):
            assert self.h.u16(BASE + 6) == 1 and self.h.u16(BASE + 10) == 1, (
                "only BUSY PING allowed"
            )
            self.native_calls += 1
            if self.fault != "missing_receipt":
                self.h.seed_u32(BASE + 48, DESCRIPTOR)
                self.h.engine_ack(ok=True)

    def yield_held(self):
        assert self.state.blocked, "observer yielded without hold"
        self.state.seconds += 0.025
        self.state.yields += 1
        if self.loads and self.fault == "dispatch_during_quarantine":
            self.execute_callbacks()

    def save(self, path, suppress):
        assert self.state.blocked and suppress and self.native_calls == 1
        assert self.h.u16(BASE + 6) == 1 and self.h.u16(BASE + 10) == 1
        self.saves += 1
        self.producer_state = (self.state.frame, self.h.bytes(BASE, 64))
        self.state.hashes[path] = "c" * 64
        return True

    def load(self, path, suppress):
        assert self.state.blocked and suppress and self.native_calls == 1
        assert self.h.u16(BASE + 6) == 0 and self.h.u16(BASE + 10) == 0
        assert "controlled_before_load" in self.checkpoints
        self.loads += 1
        if self.fault != "no_restore":
            self.state.frame = self.saved_frame
            self.lua.globals()._RR_FRAME = self.saved_frame
            self.h.seed(BASE, self.saved_marker)
        if self.fault == "changed_marker":
            self.h.seed_u8(BASE + 48, 1)
        if self.fault == "dispatch_during_load":
            self.execute_callbacks()
        if self.mode == "valid":
            for callback, address in tuple(self.callbacks.values()):
                if address is None:
                    callback(path)
        self.writes_after_load = len(list(self.lua.globals()._RR_WRITES.values()))
        return self.mode == "valid"

    def run(self):
        return self.lua.execute(PROBE.read_text())(self.ctx)

    @property
    def output(self):
        return self.report.evidence.runtime

    def assert_held_no_writes(self):
        assert self.state.blocked and self.state.pause_writes == 0
        assert (
            self.output.final_owner.lease_owned and self.output.final_owner.physical_stop_verified
        )
        if self.loads:
            assert len(list(self.lua.globals()._RR_WRITES.values())) == self.writes_after_load
        assert all(
            BASE <= row.address < BASE + 64 for row in self.lua.globals()._RR_WRITES.values()
        )


def test_producer_posts_only_ping_and_saves_verified_busy_under_hold():
    case = Probe("produce")
    case.run()
    assert case.saves == 1 and case.loads == 0 and case.native_calls == 1
    assert case.producer_state[0] == 1660
    assert case.output.produced.mailbox_hex == case.producer_state[1].hex()
    assert not case.output.final_owner.failed and not case.callbacks
    assert case.output.forward_frames == 1659
    case.assert_held_no_writes()


@pytest.mark.parametrize("mode", ["valid", "late_failure"])
def test_restored_frame_invalidates_original_owner_and_retains_busy_without_dispatch(mode):
    case = Probe(mode)
    case.run()
    assert case.loads == 1 and case.native_calls == 1 and case.saves == 0
    assert case.output.after_load.old_owner_verified is False
    assert case.output.final_owner.failed and not case.callbacks
    assert case.state.frame == 1660 and case.h.bytes(BASE, 64) == case.saved_marker
    assert case.output.held_period.yields >= 10
    assert case.output.general_interlock_proved is False
    case.assert_held_no_writes()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_native_control",
        "missing_receipt",
        "artifact_hash",
        "zero_registration",
        "duplicate_registration",
        "no_restore",
        "changed_marker",
        "dispatch_during_load",
        "dispatch_during_quarantine",
        "cleanup",
    ],
)
def test_faults_fail_visibly_and_never_clear_or_reinterpret_uncertain_state(fault):
    case = Probe(fault=fault)
    with pytest.raises(AssertionError):
        case.run()
    assert len(list(case.output.failures.values())) > 0
    case.assert_held_no_writes()
    if fault in {
        "missing_native_control",
        "missing_receipt",
        "artifact_hash",
        "zero_registration",
        "duplicate_registration",
    }:
        assert case.loads == 0


@pytest.mark.parametrize("field,value", [("mode", "unheld_negative"), ("hold_ms", 0)])
def test_unknown_or_unbounded_probe_is_rejected_before_boot(field, value):
    case = Probe()
    case.config.probe_options[field] = value
    with pytest.raises(AssertionError):
        case.run()
    assert case.state.frame == 1 and not case.callbacks and case.state.flag_writes == 0


@pytest.mark.parametrize("field", ["paused", "blocked"])
def test_preexisting_pause_or_hold_refuses_before_any_boot_advance(field):
    case = Probe()
    case.state[field] = True
    with pytest.raises(AssertionError, match="initial_unpaused_unheld"):
        case.run()
    assert case.state.frame == 1 and case.state.flag_writes == 0 and case.state[field]
