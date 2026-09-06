"""Behavioral regressions: every case describes the desired fixed behavior."""

from dataclasses import asdict, dataclass
from pathlib import Path

from tests.rr.runtime.rr_harness import HarnessError, RRHarness


@dataclass
class Result:
    name: str
    expected: dict
    observed: dict
    source_sha256: dict
    evidence_logs: list

    @property
    def passed(self):
        return self.expected == self.observed

    def document(self):
        return {**asdict(self), "passed": self.passed}


def result(h, name, expected, observed):
    return Result(
        name,
        expected,
        observed,
        h.manifest(),
        [
            line
            for line in h.logs()
            if any(
                s in line
                for s in [
                    "CONFIRMED",
                    "VERIFY",
                    "native deposit",
                    "battle] end",
                    "memorialize:",
                ]
            )
        ],
    )


def party_keys(h):
    return [
        h.M.monKey(h.M.PARTY_BASE + i * h.M.MON_SIZE) for i in range(h.u8(h.M.PARTY_COUNT_ADDR))
    ]


def require_opcode(h, expected):
    actual = h.pending_native()
    if actual["opcode"] != expected:
        raise HarnessError(
            f"Scenario prerequisite: expected native opcode {expected}, got {actual}"
        )
    return actual


def stale_slot_deposit(repo: Path):
    h = RRHarness(repo, party=(111, 333))
    h.step()
    h.command("box_mon", key=h.key(111))
    h.step()
    op = require_opcode(h, 24)
    box, pos = op["args"][1:]
    address = int(h.M.boxMonAddr(box, pos))
    guards = [
        h.canary(address - 1, 1),
        h.canary(address + 58, 1),
        h.canary(int(h.M.PARTY_BASE) - 1, 1),
        h.canary(int(h.M.PARTY_BASE) + 600, 1),
    ]
    # Engine/user reorder after request was staged, before the native refusal.
    h.set_mon(0, 333)
    h.set_mon(1, 111)
    h.engine_ack(ok=False, reason=4)
    h.step()
    h.check_canaries(*guards)
    return result(
        h,
        "stale_slot_deposit",
        {"party_keys": [h.key(333), h.key(111)], "destination_key": None},
        {"party_keys": party_keys(h), "destination_key": h.M.boxMonKey(box, pos)},
    )


def false_memorial_receipt(repo: Path):
    h = RRHarness(repo, party=(111, 333))
    h.step()
    h.set_mon(0, 111, 0)
    h.command("memorialize", key=h.key(111))
    h.step()
    op = require_opcode(h, 26)
    address = int(h.M.boxMonAddr(op["args"][1], op["args"][2]))
    guards = [h.canary(address - 1, 1), h.canary(address + 58, 1)]
    # ST_OK is only a transport/handler assertion: the fixture supplies inconsistent
    # readback deliberately. The actual client MUST reject this as proof of burial.
    h.engine_ack(ok=True)
    h.step()
    h.check_canaries(*guards)
    return result(
        h,
        "false_memorial_receipt",
        {"success_receipts": 0, "source_still_present": True, "destination_key": None},
        {
            "success_receipts": len(h.events("memorialize_done")),
            "source_still_present": h.key(111) in party_keys(h),
            "destination_key": h.M.boxMonKey(op["args"][1], op["args"][2]),
        },
    )


def borrowed_reload(repo: Path):
    h = RRHarness(repo, party=(111,), load=False)
    h.seed(int(h.M.REAL_PARTY_BACKUP_ADDR), h.bytes(int(h.M.PARTY_BASE), 100))
    h.set_mon(0, 999)
    h.set_battler(0, 999)
    h.set_battle(True, flags=12)  # Generic TRAINER|IS_MASTER preset, no borrowed flag.
    h.seed_u8(0x0203F840, 1)
    h.seed_u8(0x0203F841, 7)
    h.seed_u32(0x0203F844, 111)
    h.load_client()
    h.step(31)
    leaked = [
        e["event"]
        for e in h.events()
        if any(m.get("key") == h.key(999) for m in e.get("party", []))
    ]
    return result(
        h,
        "borrowed_reload",
        {"borrowed_party_published_by": []},
        {"borrowed_party_published_by": leaked},
    )


def faint_counter_credit(repo: Path):
    h = RRHarness(repo, party=(111, 333))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step(3)  # Zero remains pending until authoritative evidence arrives.
    h.set_faint_counter(1)
    h.set_mon(0, 111, 0)
    h.set_battler(1, 333, 50)
    h.step()
    h.set_battler(1, 333, 0)
    h.step()  # One-frame protection transient, not a death.
    h.set_battler(1, 333, 1)
    h.step()
    return result(
        h,
        "faint_counter_credit",
        {"fainted_keys": [h.key(111)], "whiteouts": 0},
        {
            "fainted_keys": [e["key"] for e in h.events("faint")],
            "whiteouts": len(h.events("whiteout")),
        },
    )


def battle_end_pending_death(repo: Path):
    h = RRHarness(repo)
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step()  # Timer still pending.
    h.set_faint_counter(1)
    h.set_mon(0, 111, 0)
    h.set_battle(False, outcome=2)
    h.step(2)
    return result(
        h,
        "battle_end_pending_death",
        {"fainted_keys": [h.key(111)], "whiteouts": 1},
        {
            "fainted_keys": [e["key"] for e in h.events("faint")],
            "whiteouts": len(h.events("whiteout")),
        },
    )


def delayed_whiteout(repo: Path):
    h = RRHarness(repo)
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step(3)
    h.set_faint_counter(1)
    h.step()
    h.set_mon(0, 111, 0)
    h.set_battle(False, outcome=2)
    h.step(2)
    return result(
        h,
        "delayed_whiteout",
        {"fainted_keys": [h.key(111)], "whiteouts": 1},
        {
            "fainted_keys": [e["key"] for e in h.events("faint")],
            "whiteouts": len(h.events("whiteout")),
        },
    )


def overlapping_battles(repo: Path):
    h = RRHarness(repo)
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battle(False, outcome=4)
    h.step(2)
    h.set_area(20)
    h.set_battle(True)
    h.step(96)
    return result(
        h,
        "overlapping_battles",
        {"no_catch_areas": ["route_1"], "second_battle_still_active": True},
        {
            "no_catch_areas": [e["area_id"] for e in h.events("no_catch")],
            "second_battle_still_active": bool(h.M.isInBattle()),
        },
    )


def storage_during_script(repo: Path):
    h = RRHarness(repo, party=(111, 333))
    h.step()
    h.seed_u8(0x03000F9C, 1)
    h.command("box_mon", key=h.key(111))
    h.step()
    return result(
        h,
        "storage_during_script",
        {"native_opcode": 0, "script_locked": True},
        {
            "native_opcode": h.pending_native()["opcode"],
            "script_locked": h.u8(0x03000F9C) == 1,
        },
    )


def boxed_memorialization(repo: Path):
    h = RRHarness(repo, party=(333, 555))
    raw = bytearray(h.bytes(int(h.M.PARTY_BASE), 100))
    raw[:4] = (111).to_bytes(4, "little")
    compressed = h.compressed_fixture(bytes(raw))
    source = int(h.M.boxMonAddr(0, 0))
    destination = int(h.M.boxMonAddr(24, 0))
    h.seed(source, compressed)
    guards = [
        h.canary(source - 1, 1),
        h.canary(source + 58, 1),
        h.canary(destination - 1, 1),
        h.canary(destination + 58, 1),
    ]
    before = h.bytes(int(h.M.PARTY_BASE), 600)
    h.step()
    h.command("memorialize", key=h.key(111))
    h.step()
    opcode = h.pending_native()["opcode"]
    if opcode == 28:
        h.engine_storage_effect()
        h.step()
    h.check_canaries(*guards)
    return result(
        h,
        "boxed_memorialization",
        {
            "opcode": 28,
            "source_key": None,
            "destination_key": h.key(111),
            "unchanged_party": True,
            "success_receipts": 1,
        },
        {
            "opcode": opcode,
            "source_key": h.M.boxMonKey(0, 0),
            "destination_key": h.M.boxMonKey(24, 0),
            "unchanged_party": h.bytes(int(h.M.PARTY_BASE), 600) == before,
            "success_receipts": len(h.events("memorialize_done")),
        },
    )


CASES = {
    f.__name__: f
    for f in [
        stale_slot_deposit,
        false_memorial_receipt,
        borrowed_reload,
        faint_counter_credit,
        battle_end_pending_death,
        delayed_whiteout,
        overlapping_battles,
        storage_during_script,
        boxed_memorialization,
    ]
}
