"""C2 profile metadata only: source/model evidence, never trade admission."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re

import pytest

from tools import gen_polished_profile as gp


@pytest.fixture
def inputs():
    return gp.parse_symbols(gp.SYM.read_text()), json.loads(gp.PROVENANCE.read_bytes())


def assert_schema(trade):
    assert trade["schema"] == "polished-trade-v1"
    assert trade["production"] is False
    assert trade["capabilities"] == {"proposer_service": True, "responder_service": False, "commit": False}
    lease = trade["lease"]
    assert (lease["base"], lease["offset"], lease["size"], lease["bank"]) == (0xC619, 14, 16, 0)
    assert lease["fields"] == {"magic": 0, "version": 4, "command": 5, "generation": 6, "ack": 7,
                               "result": 8, "slot": 9, "available": 10, "mask": 11, "token": 12}
    assert lease["magic"] == [0x53, 0x4C, 0x54, 0x31] and lease["version"] == 1
    assert trade["commands"] == {"QUERY": 1, "OFFER": 2, "PROMPT": 3, "APPLY": 5, "DONE": 7, "RELEASE": 8}
    assert trade["timeouts"] == {"QUERY": 600, "OFFER": 600, "APPLY": 3600, "RELEASE": 90}
    assert set(trade["entries"]) == set(gp.TRADE_ENTRIES)
    assert trade["dispatcher_stack_pin_names"] == ["NextOverworldFrame", "DelayFrame",
        "NextOverworldFrame.gfx_done", "HandleMap", "OverworldLoop.loop"]
    for group, expected in (("staging", {"party": (0xD28B, 48), "ot": (0xD3AB, 11),
                                       "nickname": (0xD3ED, 11), "sender": (0xD276, 11)}),
                            ("snapshot", {"party": (0xD2BB, 48), "ot": (0xD3B6, 11),
                                         "nickname": (0xD3F8, 11)})):
        assert set(trade[group]) == set(expected)
        assert {k: (v["addr"], v["size"]) for k, v in trade[group].items()} == expected
        assert all(v["bank"] == 1 for v in trade[group].values())


def assert_disjoint(trade):
    rows = [*trade["staging"].values(), *trade["snapshot"].values()]
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            assert a["bank"] != b["bank"] or a["addr"] + a["size"] <= b["addr"] or b["addr"] + b["size"] <= a["addr"]


def test_schema_and_generated_family(inputs):
    trade = gp.trade_block(*inputs)
    assert_schema(trade)
    assert_disjoint(trade)
    assert json.loads(gp.OUT.read_bytes())["titles"]["polished"]["overlay"]["trade"] == trade
    for row in trade["entries"].values():
        assert (row["bank"], row["addr"]) == inputs[0][row["symbol"]]


@pytest.mark.parametrize("name,cap", [("SlinkTradeResponderService", "responder_service"),
                                    ("SlinkTradeCommit", "commit")], ids=["responder", "commit"])
def test_future_component_pair_flips_only_its_presence(inputs, name, cap):
    symbols, prov = inputs
    assert name not in symbols and "SlinkTradePromptEntry" in symbols
    seed = symbols["SlinkTradeEntry"]
    symbols[name] = seed._replace(address=0x5000)
    with pytest.raises(ValueError, match="incomplete component"):
        gp.trade_block(symbols, prov)
    symbols[name + "End"] = seed._replace(address=0x5010)
    trade = gp.trade_block(symbols, prov)
    assert trade["capabilities"][cap] is True
    assert trade["production"] is False
    assert trade["entries"][name]["addr"] == 0x5000
    del symbols[name]
    with pytest.raises(ValueError, match="incomplete component"):
        gp.trade_block(symbols, prov)


def test_complete_symbols_do_not_grant_production(inputs):
    symbols, prov = inputs
    for n, name in enumerate(("SlinkTradeResponderService", "SlinkTradeCommit")):
        symbols[name] = symbols["SlinkTradeEntry"]._replace(address=0x5000 + n * 0x100)
        symbols[name + "End"] = symbols[name]._replace(address=symbols[name].address + 16)
    trade = gp.trade_block(symbols, prov)
    assert all(trade["capabilities"].values())
    assert trade["production"] is False


def test_prompt_stub_as_responder_mutant_is_caught(inputs):
    text = inspect.getsource(gp.trade_block)
    old = '"responder_service": component("SlinkTradeResponderService")'
    assert old in text
    namespace = dict(gp.__dict__)
    exec(text.replace(old, '"responder_service": "SlinkTradePromptEntry" in symbols'), namespace)
    with pytest.raises(AssertionError):
        assert_schema(namespace["trade_block"](*inputs))


@pytest.mark.parametrize("name", gp.TRADE_ENTRIES + gp.TRADE_STACK_PINS + (
    "wSlinkMailbox", "wSlinkMailboxEnd", "wOTPartyMon1", "wOTPartyMon1End",
    "wOTPartyMon2", "wOTPartyMon2End", "wOTPartyMonOTs", "wOTPartyMon2OT", "wOTPartyMon3OT",
    "wOTPartyMonNicknames", "wOTPartyMon2Nickname", "wOTPartyMon3Nickname", "wOTPlayerName", "wOTPlayerID"),
    ids=lambda name: name)
def test_required_symbol_missing_refuses(inputs, name):
    del inputs[0][name]
    with pytest.raises(ValueError, match="trade required symbol missing: " + re.escape(name)):
        gp.trade_block(*inputs)


@pytest.mark.parametrize("group,name", [("entries", "SlinkTradeEntry"), ("staging", "wOTPlayerName")],
                         ids=["entry", "sender"])
def test_relocated_sym_copy_is_followed(inputs, tmp_path, group, name):
    # Parse an actual mutated copy, not a hand-built symbols mapping.
    text = gp.SYM.read_text()
    bank, addr = inputs[0][name]
    replacement = addr + 1
    text, count = re.subn(rf"^{bank:02x}:{addr:04x} {name}$", f"{bank:02x}:{replacement:04x} {name}", text, flags=re.M)
    assert count == 1
    path = tmp_path / gp.SYM.name
    path.write_text(text)
    result = gp.trade_block(gp.parse_symbols(path.read_text()), inputs[1])
    row = result[group][name if group == "entries" else "sender"]
    assert row["addr"] == replacement
    if group == "staging":
        assert row["size"] == 10


def test_overlap_refused(inputs):
    symbols, prov = inputs
    symbols["wOTPlayerName"] = symbols["wOTPartyMon1"]
    symbols["wOTPlayerID"] = symbols["wOTPartyMon1End"]
    with pytest.raises(ValueError, match="overlap"):
        gp.trade_block(symbols, prov)


@pytest.mark.parametrize("rel", ["patch/gb/slink_abi.inc", "patch/polished/src/trade_frame.asm",
                                "patch/polished/src/trade_service.asm"], ids=["abi", "frame", "service"])
def test_source_provenance_required(inputs, rel):
    inputs[1]["overlay"]["sources_sha256"][rel] = "0" * 64
    with pytest.raises(ValueError, match="trade source provenance mismatch"):
        gp.trade_block(*inputs)


def test_deterministic(inputs):
    symbols, prov = inputs
    assert gp.render(gp.trade_block(symbols, prov)) == gp.render(gp.trade_block(dict(reversed(list(symbols.items()))), prov))


def test_constants_follow_receipted_source_copy(inputs, monkeypatch, tmp_path):
    symbols, prov = inputs
    for rel in ("patch/gb/slink_abi.inc", "patch/polished/src/trade_frame.asm", "patch/polished/src/trade_service.asm"):
        raw = (gp.ROOT / rel).read_bytes()
        if rel.endswith("trade_service.asm"):
            changed = raw.replace(b"SLINK_TRADE_QUERY_FRAMES EQU 600", b"SLINK_TRADE_QUERY_FRAMES EQU 601")
            assert changed != raw
            raw = changed
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        prov["overlay"]["sources_sha256"][rel] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(gp, "ROOT", tmp_path)
    assert gp.trade_block(symbols, prov)["timeouts"]["QUERY"] == 601


@pytest.mark.parametrize("kind", ["wrong-bank", "backward", "oversize-lease"],
                         ids=["wrong-bank", "backward", "oversize-lease"])
def test_bad_geometry_refuses(inputs, kind):
    symbols, prov = inputs
    if kind == "wrong-bank":
        symbols["SlinkTradeEntry"] = symbols["SlinkTradeEntry"]._replace(address=0xC000)
    elif kind == "backward":
        symbols["wOTPartyMon1End"] = symbols["wOTPartyMon1"]
    else:
        symbols["wSlinkMailboxEnd"] = symbols["wSlinkMailbox"]._replace(address=symbols["wSlinkMailbox"].address + 20)
    with pytest.raises(ValueError, match="trade"):
        gp.trade_block(symbols, prov)


def test_check_freshness_and_red_control(monkeypatch, tmp_path):
    # Exercise the real generator and --check path; keep its other pack inputs in place.
    expected = gp.build()
    assert gp.main(["--check"]) == 0
    out = tmp_path / "profile.json"
    out.write_bytes(gp.render(expected).encode())
    monkeypatch.setattr(gp, "OUT", out)
    monkeypatch.setattr(gp, "build", lambda: expected)
    assert gp.main(["--check"]) == 0
    data = copy.deepcopy(expected)
    del data["titles"]["polished"]["overlay"]["trade"]
    out.write_bytes(gp.render(data).encode())
    assert gp.main(["--check"]) == 1


def test_full_build_follows_sym_and_checks_digest(monkeypatch, tmp_path):
    original = gp.SYM.read_bytes()
    changed = original.replace(b"7e:4480 SlinkTradeEntry", b"7e:4481 SlinkTradeEntry")
    assert changed != original
    path, receipt = tmp_path / gp.SYM.name, tmp_path / "provenance.json"
    path.write_bytes(changed)
    prov = json.loads(gp.PROVENANCE.read_bytes())
    receipt.write_text(json.dumps(prov))
    monkeypatch.setattr(gp, "SYM", path)
    monkeypatch.setattr(gp, "PROVENANCE", receipt)
    with pytest.raises(ValueError, match="sha256 differs"):
        gp.build()
    prov["symbols"][path.name] = hashlib.sha256(changed).hexdigest()
    receipt.write_text(json.dumps(prov))
    assert gp.build()["titles"]["polished"]["overlay"]["trade"]["entries"]["SlinkTradeEntry"]["addr"] == 0x4481


@pytest.mark.parametrize("mutation", ["production", "lease", "commands", "timeouts", "staging", "snapshot", "stack"],
                         ids=["production", "lease", "commands", "timeouts", "staging", "snapshot", "stack"])
def test_schema_oracle_rejects_mutants(inputs, mutation):
    trade = gp.trade_block(*inputs)
    if mutation == "production":
        trade["production"] = True
    elif mutation == "lease":
        trade["lease"]["fields"]["ack"] = 6
    elif mutation == "commands":
        trade["commands"]["APPLY"] = 4
    elif mutation == "timeouts":
        trade["timeouts"]["QUERY"] = 599
    elif mutation in ("staging", "snapshot"):
        trade[mutation]["party"]["addr"] += 1
    else:
        trade["dispatcher_stack_pin_names"] = [0x5185]
    with pytest.raises(AssertionError):
        assert_schema(trade)


def test_disabled_overlap_guard_mutant_is_caught(inputs):
    text = inspect.getsource(gp.trade_block)
    old = 'require(left["bank"] != right["bank"] or'
    assert old in text
    namespace = dict(gp.__dict__)
    exec(text.replace(old, 'require(True or left["bank"] != right["bank"] or'), namespace)
    symbols, prov = inputs
    symbols["wOTPlayerName"] = symbols["wOTPartyMon1"]
    symbols["wOTPlayerID"] = symbols["wOTPartyMon1End"]
    with pytest.raises(AssertionError):
        assert_disjoint(namespace["trade_block"](symbols, prov))
