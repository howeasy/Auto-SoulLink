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
        g.memory = self.lua.table(read_u8=self.read, read_u16_le=lambda at, *_: self.word(at, 2))

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

        return self.carrier.command(self.lua.table(cmd=cmd, **fields), forward)


def test_observer_reads_hooks_and_publication_without_writing_native_evidence(tmp_path):
    w = Carrier(tmp_path)
    assert w.writes == []
    assert set(w.hooks) == {
        "T5-TradeMons_body",
        "T5-TrySavingData",
        "T5-DoInGameTradeScene",
        "T5-TradeEvolutionScene",
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


@pytest.mark.parametrize(
    "side,decline,commands,expected",
    [
        (
            "a",
            False,
            ["show_choices", "choose_mon"],
            [
                ("trade_request", {}),
                ("menu_result", {"token": "t1", "choice": 0}),
                ("mon_chosen", {"token": "t1", "slot": 1}),
            ],
        ),
        ("b", False, ["show_menu"], [("menu_result", {"token": "t1", "choice": 1})]),
        ("b", True, ["show_menu"], [("menu_result", {"token": "t1", "choice": 0})]),
    ],
)
def test_selection_bridge_preserves_server_protocol_and_never_supplies_native_results(
    tmp_path, side, decline, commands, expected
):
    w = Carrier(tmp_path, side, decline)
    w.carrier.start_selection()
    for command in commands:
        assert w.command(command, token="t1")
    assert w.sent == expected
    assert w.forwarded == [] and w.writes == []
    for command in ("apply_prepare", "apply_trade", "withdraw_trade", "trade_final"):
        assert w.command(command, token="t1")
    assert [row["cmd"] for row in w.forwarded] == [
        "apply_prepare",
        "apply_trade",
        "withdraw_trade",
        "trade_final",
    ]
    assert w.sent == expected and w.writes == []


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
