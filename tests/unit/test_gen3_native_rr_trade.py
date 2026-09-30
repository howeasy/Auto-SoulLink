"""RR-DURABLE MODEL controls: Radical Red's durable trade descriptor in lua/gen3/native.lua.

RR stays ABI1 (Codex Emerald ruling P3). Its durable trade is an isolated descriptor: the shared
producer's shadow SlinkMailboxV2 at profile native.TRADE_BASE (patch/src/rr_trade_relay.h), with
capabilities/session_epoch/producer_phase at +0x40/+0x44/+0x48 and the witness at +0x50. Commands
still travel through the ABI1 mailbox at native.BASE."""
import pytest
from lupa import lua54

from server.adapters.gen3_codec import encode_party_mon
from tests.unit import test_gen3_native as native_model
from tests.unit.gen3_trade_journal_model import JournalModel
from tests.unit.gen3_world import mon_record
from tests.unit.test_gen3_native import World


@pytest.fixture(autouse=True)
def bizhawk_lua_version(monkeypatch):
    monkeypatch.setattr(native_model, "lupa", lua54)


def to_python(value):
    if lua54.lua_type(value) == "table":
        return {k: to_python(v) for k, v in value.items()}
    return value


class RRTradeWorld(World):
    def __init__(self, *, capability=1, production=True, title="radical_red", epoch=0x12345678,
                 bind=True):
        super().__init__(pack="gen3_rr")
        self.battle = False
        self.recovery_clear = True
        self.tb = self.n["TRADE_BASE"]
        self.put(self.tb + 0x40, capability, 4)
        module = self.lua.execute((native_model.ROOT / "lua/gen3/native.lua").read_text(encoding="utf-8"))
        self.native = module.new(self.lua.table_from(self.profile, recursive=True), self.lua.table(
            io=self.native_io, writes=self.writes, reads=self.reads, title=title, player="a",
            production=production, artifact_kind="companion", initial_seq=10, timeout_frames=8,
            send=lambda event, fields: self.events.append((event, fields)), log=self.logs.append,
            in_battle=lambda: self.battle, trade_recovery_clear=lambda: self.recovery_clear,
            trade_safe=lambda: self.safe and not self.battle,
            panel_closed=lambda: (True, 1)))
        if bind:
            self.native.set_session_epoch(self.native, epoch)
            self.service()
        # CFRU plaintext records; species 1324 is past FR's 411 (RR's own species table)
        self.old = mon_record(1, 2, species=1324)
        self.incoming = mon_record(5, 6, species=277)
        self.old_key = "00000001:00000002"
        self.incoming_key = "00000005:00000006"
        self.seed_party(self.old, mon_record(3, 4, species=1))

    def seed_party(self, *rows):
        self.put(self.ram["PARTY_COUNT_ADDR"], len(rows))
        for slot, row in enumerate(rows):
            for i, byte in enumerate(encode_party_mon(row, rr=True)):
                self.put(self.ram["PARTY_BASE"] + slot * 100 + i, byte)

    def phase(self, value):
        self.put(self.tb + 0x48, value, 4)

    def witness(self, *, bits=31, result=1, phase=4, flags=3, saved=1):
        raw = bytearray(80)
        raw[0:4] = (0x12345678).to_bytes(4, "little")
        raw[4:8] = self.prepare_args[12:16]
        raw[8:24] = self.prepare_args[16:32]
        raw[24:26] = (2).to_bytes(2, "little")
        raw[26:28] = flags.to_bytes(2, "little")
        raw[28:32] = bits.to_bytes(4, "little")
        scene = getattr(self, "scene_seq", 999)
        for i, seq in enumerate((self.prepare_seq, scene, scene, scene, scene)):
            raw[32 + i * 2:34 + i * 2] = seq.to_bytes(2, "little")
        raw[42], raw[43] = result, saved
        raw[64:72] = self.prepare_args[4:12]
        raw[72:80] = bytes.fromhex("0500000006000000")
        for i, byte in enumerate(raw):
            self.put(self.tb + 0x50 + i, byte)
        self.phase(phase)


class RRProtocolWorld(RRTradeWorld):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.trace = []
        self.flush_fails = False
        self.journal = JournalModel(ot="00000002")(self.lua)
        module = self.lua.execute((native_model.ROOT / "lua/gen3/trade.lua").read_text())

        def decode(hex_string):
            return self.reads.decode_party_mon(self.lua.table(*bytes.fromhex(hex_string)))

        self.trade = module.new(self.lua.table(
            native=self.native, journal=self.journal, frame=lambda: self.frame, epoch=lambda: 1,
            eligible=lambda: True, ready_to_send=lambda: True, clear=lambda: True,
            capacity=6, mon_size=100, prepare_frames=600, apply_frames=1800,
            decode_blob=decode, key=self.reads.key, party=self.reads.read_party,
            saveram=self.flush,
            send=lambda name, fields, *_: self.trace.append((name, to_python(fields))),
            log=lambda text: self.trace.append(("log", text))))

    def flush(self):
        self.trace.append(("saveram", None))
        if self.flush_fails:
            raise OSError("MODEL flush failed")


def test_rr_descriptor_reads_the_shadow_block_and_stays_abi1():
    w = RRTradeWorld()
    mb = w.native.mailbox(w.native)
    assert mb.abi == 1 and mb.capabilities == 1 and mb.session_epoch == 0x12345678
    assert w.read(w.tb + 0x44, 4) == 0x12345678           # the epoch went to the shadow block
    assert w.read(w.n["BASE"] + 0x44, 4) == 0              # never over SwapState
    assert w.native.trade_capable(w.native) is True
    # ruling P3: reasons 11/12 keep their legacy (unnamed) RR meanings; 14 is named
    for reason, name in ((11, None), (12, None), (14, "withdraw_too_late")):
        w.put(w.n["BASE"] + 14, reason, 2)
        assert w.native.mailbox(w.native).reason_name == name


@pytest.mark.parametrize("capability,production,title,capable", [
    (1, True, "radical_red", True), (0, True, "radical_red", False),     # old UPS: zero tail
    (1, None, "radical_red", False), (1, True, "firered", False), (3, True, "radical_red", False),
])
def test_rr_capability_requires_the_tail_bit_and_production_identity(capability, production, title, capable):
    w = RRTradeWorld(capability=capability, production=production, title=title)
    assert w.native.trade_capable(w.native) is capable


def test_rr_v1_ops_never_wait_for_the_epoch_and_16_18_are_not_trade_paths():
    w = RRTradeWorld(bind=False)
    assert w.native.play_sound(w.native, 25) is not None      # no client_too_old on ABI1
    w.service()
    assert w.read(w.n["BASE"] + 6, 2) == w.n["OP_PLAY_SE"]


def test_rr_eligibility_uses_rr_facts():
    w = RRTradeWorld()
    mon = to_python(w.reads.read_party()[1])
    assert mon["species"] == 1324 and "checksum_ok" not in mon
    assert w.native.trade_eligible(w.native, w.reads.read_party()[1]) is True
    held = mon_record(1, 2, species=1324)
    held["held_item"] = 121                                    # ItemIsMail range (=FR bytes in RR)
    w.seed_party(held)
    assert w.native.trade_eligible(w.native, w.reads.read_party()[1]) is False


@pytest.mark.parametrize("flush_fails", [False, True])
def test_rr_journal_native_scene_saveram_and_trade_done_end_to_end_model(flush_fails):
    w = RRProtocolWorld()
    w.flush_fails = flush_fails
    base = w.n["BASE"]
    w.trade.prepare(w.trade, w.lua.table(token="server-token", old_key=w.old_key))
    w.service()
    assert w.read(base + 6, 2) == 29                         # PREPARE through the ABI1 mailbox
    w.prepare_seq, w.prepare_args = w.read(base + 8, 2), w.raw(base + 16, 32)
    w.witness(bits=1, result=0, phase=2)
    w.ack()
    w.service()
    assert ("apply_ready", {"token": "server-token", "ok": True}) in w.trace
    w.trade.apply(w.trade, w.lua.table(token="server-token", old_key=w.old_key,
                                      blob_hex=encode_party_mon(w.incoming, rr=True).hex()))
    w.trade.tick(w.trade)
    w.service()
    w.service()
    assert w.read(base + 6, 2) == 21                         # SCENE; never 16 or 18
    assert not any(a == base + 6 and v in (16, 18) for a, v in w.output)
    w.scene_seq = w.read(base + 8, 2)
    w.seed_party(w.incoming, mon_record(3, 4, species=1))
    w.witness()
    w.ack()
    w.service()
    w.trade.tick(w.trade)
    done = [v for name, v in w.trace if name == "trade_done"]
    if flush_fails:
        assert done == [{"token": "server-token", "uncertain": True, "after_reset": True}]
    else:
        assert done == [{"token": "server-token", "slot": 0, "new_key": w.incoming_key, "new_species": 277}]
        names = [name for name, _ in w.trace]
        assert names.index("saveram") < names.index("trade_done")
