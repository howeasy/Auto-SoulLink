"""Producer-shaped receipts from the real test-only Lua carrier; no emulator."""

import hashlib
import json
from pathlib import Path

import pytest
from lupa import lua54

from tests.unit.test_gen3_trade_duo import model_bound_file, model_manifest
from tools import gen3_trade_duo as t5

ROOT = Path(__file__).resolve().parents[2]


class Carrier:
    def __init__(self, tmp_path, side="a", decline=False):
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.base, self.party_base, self.count_address = 0x0201B000, 0x02024284, 0x02024029
        self.bus, self.writes, self.lines, self.sent, self.forwarded, self.hooks = (
            {},
            [],
            [],
            [],
            [],
            {},
        )
        self.flash = (ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes()
        self.counter = t5.codec.parse_flash(self.flash)["counter"]
        party = t5.codec.party_from_save(self.flash)
        self.bus[self.count_address] = len(party)
        for i, byte in enumerate(b"".join(t5.codec.encode_party_mon(mon) for mon in party)):
            self.bus[self.party_base + i] = byte
        (tmp_path / "patch/build").mkdir(parents=True)
        self.battery = tmp_path / "probe.SaveRAM"
        manifest = model_manifest()
        manifest.update(
            native={"BASE": self.base},
            party_count=self.count_address,
            hooks={
                "TradeMons_body": 0x08050814,
                "TrySavingData": 0x080DA364,
                "DoInGameTradeScene": 0x08054440,
                "TradeEvolutionScene": 0x080CE540,
                "CB2_InitPartyMenu": 0x0811EBD0,
            },
        )
        for path in (*manifest["source_sha1"], *manifest["pack_files"].values()):
            destination = tmp_path / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(model_bound_file(path).encode())
        raw_manifest = json.dumps(manifest)
        d = self.lua.table(
            wt=tmp_path.as_posix(),
            game="gen3_fr_trade",
            title="firered",
            player=side,
            scenario="native_trade_decline_firered" if decline else "native_trade_firered",
            phase="initial",
            native_battery=self.battery.as_posix(),
            native_decline=decline,
            native_manifest_sha1=hashlib.sha1(raw_manifest.encode()).hexdigest(),
        )
        g = self.lua.globals()
        g.gameinfo = self.lua.table(getromhash=lambda: manifest["rom_sha1"])
        g.emu = self.lua.table(framecount=lambda: 1)
        g.os.getenv = lambda name: manifest["nonce"] if name == t5.ENV else None
        g.memory = self.lua.table(read_u8=self.read, read_u16_le=lambda at, *_: self.word(at, 2),
                                  read_u32_le=lambda at, *_: self.word(at, 4))

        def register(fn, at, name):
            self.hooks[name] = (at, fn)
            return name

        g.event = self.lua.table(on_bus_exec=register)
        self.json = self.lua.execute((ROOT / "lua/json_codec.lua").read_text())
        module = self.lua.execute((ROOT / "lua/tests/duo/gen3_trade_candidate.lua").read_text())
        self.carrier = module.new(
            d,
            self.json,
            self.lua.table_from(manifest, recursive=True),
            self.lines.append,
            raw_manifest,
        )

        def write(address, value, *_):
            self.writes.append((address, value))
            self.bus[address] = value

        def flush():
            self.battery.write_bytes(self.flash)

        self.io = self.lua.table(
            read_u16=lambda at: self.word(at, 2),
            write_u8=write,
            saveram=flush,
            trade_journal=self.lua.table(
                ready=lambda *_: True, hidden=lambda *_: False, has_entries=lambda *_: False
            ),
        )
        self.carrier.before_build(self.lua.table(io=self.io))
        self.session = self.lua.table(
            send=lambda event, fields: self.sent.append(
                (event, json.loads(self.json.encode(fields)))
            )
        )
        self.carrier.attach(
            self.session, self.lua.table(native=self.lua.table(trade_capable=lambda *_: True))
        )
        self.ctx = self.lua.table(
            G=self.lua.table(flash_domain=lambda: "SaveRAM", save_counter=lambda *_: self.counter),
            reader=self.lua.table(party_base=lambda: self.party_base),
        )
        self.carrier.start(self.ctx)

    def read(self, address, domain="System Bus"):
        return self.flash[address] if domain == "SaveRAM" else self.bus.get(address, 0)

    def word(self, address, count):
        return sum(self.read(address + i) << (8 * i) for i in range(count))

    def command(self, cmd, **fields):
        def forward(value):
            self.forwarded.append(json.loads(self.json.encode(value)))
            return True

        return self.carrier.command(self.lua.table_from({"cmd": cmd, **fields}, recursive=True), forward)


def test_observer_reads_hooks_and_publication_without_writing_native_evidence(tmp_path):
    w = Carrier(tmp_path)
    assert w.writes == []
    assert set(w.hooks) == {
        "T5-TradeMons_body",
        "T5-TrySavingData",
        "T5-DoInGameTradeScene",
        "T5-TradeEvolutionScene",
        "T5-CB2_InitPartyMenu",
    }
    w.io.write_u8(w.base + 6, 29)
    w.io.write_u8(w.base + 7, 0)
    w.hooks["T5-TradeMons_body"][1]()
    rows = t5.events("\n".join(w.lines), "a", "initial")
    request = next(r for r in rows if r["kind"] == "prepare")
    data = t5.evidence_file(tmp_path, request, "ab" * 16, "a", "initial")
    assert t5.decode_witness(data)["opcode"] == 29
    assert w.writes == [(w.base + 6, 29), (w.base + 7, 0)]
    assert any(r["kind"] == "commit" for r in rows)


def test_flush_receipt_contains_actual_flash_and_file_bytes_from_the_lua_producer(tmp_path):
    w = Carrier(tmp_path)
    w.io.saveram()
    rows = t5.events("\n".join(w.lines), "a", "initial")
    flash, flushed = [next(r for r in rows if r["kind"] == kind) for kind in ("flash", "flush")]
    assert rows.index(flash) < rows.index(flushed)
    for row in (flash, flushed):
        assert t5.evidence_file(tmp_path, row, "ab" * 16, "a", "initial") == w.flash
    assert w.writes == []


@pytest.mark.parametrize("side,decline", [("a", False), ("b", False), ("b", True)])
def test_candidate_forwards_every_prompt_and_never_synthesizes_protocol_answers(tmp_path, side, decline):
    w = Carrier(tmp_path, side, decline)
    commands = ["show_choices", "choose_mon", "show_menu", "msgbox", "link_panel",
                "apply_prepare", "apply_trade", "withdraw_trade", "trade_final"]
    for command in commands:
        assert w.command(command, token="t1")
    assert [row["cmd"] for row in w.forwarded] == commands
    assert w.sent == [] and w.writes == []
    assert w.carrier.start_selection is None



def test_capability_ready_waits_for_a_server_config_after_the_advertised_hello(tmp_path):
    w = Carrier(tmp_path)
    w.command("config", run_id="run")
    assert not w.carrier.ready
    w.carrier.tx(w.lua.table(event="hello", trade_prepare=True))
    w.command("config", run_id="run")
    assert w.carrier.ready


def test_candidate_redirects_only_store_path_and_preserves_real_store_factory(tmp_path):
    w = Carrier(tmp_path)
    calls = []
    sentinel = w.lua.table(real_store=True)
    module = w.lua.table(file_store=lambda deps: calls.append(deps.path) or sentinel)
    w.carrier.bind_journal(module)
    supplied = w.lua.table(
        path="unchanged-production-root/slink_gen3_trade", fs="real-host-adapter"
    )
    got = module.file_store(supplied)
    assert got.real_store
    assert calls == [tmp_path.as_posix() + "/patch/build/private/slink_gen3_trade_" + "ab" * 16]
    assert supplied.fs == "real-host-adapter"


@pytest.mark.parametrize("side,decline", [("a", False), ("b", False), ("b", True)])
def test_actual_lua_observer_feeds_the_independent_carrier_byte_oracle(tmp_path, side, decline):
    from tests.unit.test_gen3_native_carrier_duo import carrier_rows

    w = Carrier(tmp_path, side, decline)
    manifest = model_manifest()
    c = manifest["carrier"]

    def put(address, data):
        w.bus.update({address+i: byte for i, byte in enumerate(data)})

    for row in carrier_rows(manifest, side, decline):
        kind, raw = row["kind"], row.get("raw")
        if kind == "npc_edge":
            put(c["control"], raw[:16])
            put(c["objects"], raw[32:608])
            put(c["avatar"], raw[608:])
            w.carrier.observe_carrier()
            put(c["control"], raw[16:32])
            w.carrier.observe_carrier()
        elif raw is not None:
            put(w.base, raw[:160])
            put(c["state"], raw[160:540])
            put(c["callback"], raw[540:544])
            put(c["field_lock"], raw[544:545])
            put(c["script_status"], raw[545:546])
            put(c["party_cursor"], raw[546:547])
            if kind == "ui_post":
                w.io.write_u8(w.base+7, 0)
            elif kind == "chooser_entry":
                w.hooks["T5-CB2_InitPartyMenu"][1]()
                w.hooks["T5-CB2_InitPartyMenu"][1]()  # same command's multi-frame initialization
            else:
                w.carrier.observe_carrier()
        elif kind == "rx":
            message = row["message"]
            w.command(**message)
        elif kind == "tx":
            w.carrier.tx(w.lua.table_from(row["message"]))
        else:
            assert w.carrier.carrier_complete()
    rows = t5.events("\n".join(w.lines), side, "initial")
    assert t5.carrier_problems(rows, manifest, side,
        lambda row: t5.evidence_file(tmp_path, row, manifest["nonce"], side, "initial"), decline=decline) == []
    assert w.sent == [], "the observer never manufactures server protocol answers"
