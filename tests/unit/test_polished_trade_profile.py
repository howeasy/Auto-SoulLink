"""C2 profile metadata only: source/model evidence, never trade admission."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re

import pytest

from tests.unit import test_polished_trade_binder as bt, test_polished_trade_service as svc
from tools import gen_polished_profile as gp

binder_env = svc.shipped_env


@pytest.fixture
def inputs():
    return gp.parse_symbols(gp.SYM.read_text()), json.loads(gp.PROVENANCE.read_bytes())


def assert_schema(trade):
    assert trade["schema"] == "polished-trade-v1"
    assert trade["production"] is True
    # Production requires the provenance-verified enable define and every component.
    assert trade["capabilities"] == {"proposer_service": True, "responder_service": True, "commit": True}
    lease = trade["lease"]
    assert (lease["base"], lease["offset"], lease["size"], lease["bank"]) == (0xC619, 14, 16, 0)
    assert lease["fields"] == {"magic": 0, "version": 4, "command": 5, "generation": 6, "ack": 7,
                               "result": 8, "slot": 9, "available": 10, "mask": 11, "token": 12}
    assert lease["magic"] == [0x53, 0x4C, 0x54, 0x31] and lease["version"] == 1
    assert trade["commands"] == {"QUERY": 1, "OFFER": 2, "PROMPT": 3, "APPLY": 5, "DONE": 7, "RELEASE": 8}
    assert trade["timeouts"] == {"QUERY": 600, "OFFER": 600, "APPLY": 3600, "RELEASE": 90}
    assert trade['validation'] == {
        'glyph_floor': 0x5F, 'nature_count': 25, 'species_low_max': 0xFE,
        'items': {'symbol':'SlinkTradeAllowedItems','bank':0x7E,'addr':0x428F,'size':256},
    }
    assert set(trade["entries"]) == set(gp.TRADE_ENTRIES) | {"SlinkTradeResponderService", "SlinkTradeResponderServiceEnd", "SlinkTradeCommit", "SlinkTradeCommitEnd"}
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


def test_schema_and_generated_family(inputs, binder_env):
    trade = gp.trade_block(*inputs)
    assert_schema(trade)
    assert_disjoint(trade)
    assert json.loads(gp.OUT.read_bytes())["titles"]["polished"]["overlay"]["trade"] == trade
    assert binder_env.rom[binder_env.flat("SlinkTradeCommitEnabled")] == 1
    for row in trade["entries"].values():
        assert (row["bank"], row["addr"]) == inputs[0][row["symbol"]]


def test_the_responder_pair_is_present_and_a_half_pair_is_refused(inputs, binder_env):
    symbols, prov = inputs
    for name in ("SlinkTradeResponderService", "SlinkTradeResponderServiceEnd"):
        assert name in symbols
    trade = gp.trade_block(symbols, prov)
    assert trade["capabilities"]["responder_service"] is True and trade["production"] is True
    assert trade["capabilities"]["commit"] is True
    assert binder_env.rom[binder_env.flat("SlinkTradeCommitEnabled")] == 1
    assert trade["entries"]["SlinkTradeResponderService"]["addr"] == 0x5000
    del symbols["SlinkTradeResponderServiceEnd"]
    with pytest.raises(ValueError, match="incomplete component"):
        gp.trade_block(symbols, prov)


def test_responder_capability_follows_the_symbol_pair_not_a_constant(inputs):
    symbols, prov = inputs
    for name in ("SlinkTradeResponderService", "SlinkTradeResponderServiceEnd"):
        del symbols[name]
    assert gp.trade_block(symbols, prov)["capabilities"]["responder_service"] is False
    text = inspect.getsource(gp.trade_block)
    old = '"responder_service": component("SlinkTradeResponderService")'
    assert old in text
    namespace = dict(gp.__dict__)
    exec(text.replace(old, '"responder_service": True'), namespace)        # a hard-coded capability is the mutant
    with pytest.raises(AssertionError):
        assert namespace["trade_block"](symbols, prov)["capabilities"]["responder_service"] is False


@pytest.mark.parametrize("name,cap", [("SlinkTradeCommit", "commit")], ids=["commit"])
def test_component_pair_flips_only_its_presence(inputs, name, cap):
    symbols, prov = inputs
    assert name in symbols and "SlinkTradePromptEntry" in symbols
    del symbols[name + "End"]
    with pytest.raises(ValueError, match="incomplete component"):
        gp.trade_block(symbols, prov)
    symbols[name + "End"] = symbols[name]._replace(address=symbols[name].address + 16)
    trade = gp.trade_block(symbols, prov)
    assert trade["capabilities"][cap] is True
    assert trade["production"] is True
    assert trade["entries"][name]["addr"] == 0x5300
    del symbols[name]
    with pytest.raises(ValueError, match="incomplete component"):
        gp.trade_block(symbols, prov)


def test_test_build_complete_symbols_do_not_grant_production(inputs):
    symbols, prov = inputs
    for n, name in enumerate(("SlinkTradeResponderService", "SlinkTradeCommit")):
        symbols[name] = symbols["SlinkTradeEntry"]._replace(address=0x5000 + n * 0x100)
        symbols[name + "End"] = symbols[name]._replace(address=symbols[name].address + 16)
    prov["test_only"] = {"SLINK_TRADE_COMMIT_ENABLE": 1}
    trade = gp.trade_block(symbols, prov)
    assert all(trade["capabilities"].values())
    assert trade["production"] is False


def test_prompt_entry_alone_is_not_the_commit_capability(inputs):
    """A PromptEntry alone must never stand in for the commit's paired markers."""
    symbols, _ = inputs
    del symbols["SlinkTradeCommit"]
    del symbols["SlinkTradeCommitEnd"]
    text = inspect.getsource(gp.trade_block)
    old = '"commit": component("SlinkTradeCommit")'
    assert old in text
    namespace = dict(gp.__dict__)
    exec(text.replace(old, '"commit": "SlinkTradePromptEntry" in symbols'), namespace)
    with pytest.raises(AssertionError):
        assert namespace["trade_block"](*inputs)["capabilities"]["commit"] is False


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
                                "patch/polished/src/trade_service.asm", "patch/polished/src/trade_validate.asm"],
                         ids=["abi", "frame", "service", "validator"])
def test_source_provenance_required(inputs, rel):
    inputs[1]["overlay"]["sources_sha256"][rel] = "0" * 64
    with pytest.raises(ValueError, match="trade source provenance mismatch"):
        gp.trade_block(*inputs)


def test_deterministic(inputs):
    symbols, prov = inputs
    assert gp.render(gp.trade_block(symbols, prov)) == gp.render(gp.trade_block(dict(reversed(list(symbols.items()))), prov))


def test_constants_follow_receipted_source_copy(inputs, monkeypatch, tmp_path):
    symbols, prov = inputs
    for rel in ("patch/gb/slink_abi.inc", "patch/polished/src/trade_frame.asm", "patch/polished/src/trade_service.asm",
                "patch/polished/src/trade_validate.asm"):
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
        trade["production"] = False
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


@pytest.mark.parametrize('name', ['SlinkTradeAllowedItems','SlinkTradeAllowedItemsEnd'], ids=['table','table-end'])
def test_validation_table_label_required(inputs, name):
    del inputs[0][name]
    with pytest.raises(ValueError, match='trade required symbol missing: '+name):
        gp.trade_block(*inputs)


def test_validation_locator_follows_sym_copy(inputs, tmp_path):
    raw = gp.SYM.read_text()
    for name in ['SlinkTradeAllowedItems','SlinkTradeAllowedItemsEnd']:
        bank, addr = inputs[0][name]
        raw,count = re.subn(rf'^{bank:02x}:{addr:04x} {name}$',f'{bank:02x}:{addr+1:04x} {name}',raw,flags=re.M)
        assert count == 1
    copied = tmp_path / gp.SYM.name
    copied.write_text(raw)
    table = gp.trade_block(gp.parse_symbols(copied.read_text()),inputs[1])['validation']['items']
    assert table['addr'] == inputs[0]['SlinkTradeAllowedItems'].address+1
    assert table['size'] == 256


@pytest.mark.parametrize('bad', ['short','long','bank'], ids=['short','long','bank'])
def test_validation_table_geometry_refused(inputs, bad):
    sym = inputs[0]
    end = sym['SlinkTradeAllowedItemsEnd']
    sym['SlinkTradeAllowedItemsEnd'] = (end._replace(bank=end.bank+1) if bad == 'bank'
                                      else end._replace(address=end.address+(-1 if bad == 'short' else 1)))
    with pytest.raises(ValueError, match='trade item table must span'):
        gp.trade_block(*inputs)


def source_copy(inputs, monkeypatch, tmp_path, old, new):
    for rel in ('patch/gb/slink_abi.inc','patch/polished/src/trade_frame.asm',
                'patch/polished/src/trade_service.asm','patch/polished/src/trade_validate.asm'):
        raw = (gp.ROOT / rel).read_bytes()
        if rel.endswith('trade_validate.asm'):
            assert old in raw
            raw = raw.replace(old,new)
        path = tmp_path / rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
        inputs[1]['overlay']['sources_sha256'][rel] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(gp,'ROOT',tmp_path)


@pytest.mark.parametrize('key,old,new,value', [
    ('glyph_floor',b'SLINK_TRADE_NAME_FLOOR EQU $5f',b'SLINK_TRADE_NAME_FLOOR EQU $60',0x60),
    ('nature_count',b'NUM_NATURES == 25',b'NUM_NATURES == 24',24),
    ('species_low_max',b'ld d, $fe',b'ld d, $fd',0xFD),
], ids=['glyph','nature','species'])
def test_validation_follows_receipted_source(inputs, monkeypatch, tmp_path, key, old, new, value):
    source_copy(inputs,monkeypatch,tmp_path,old,new)
    assert gp.trade_block(*inputs)['validation'][key] == value


@pytest.mark.parametrize('old,new', [
    (b'DEF SLINK_TRADE_NAME_FLOOR EQU $5f',b'; missing glyph floor'),
    (b'NUM_NATURES == 25',b'OTHER_CONSTANT == 25'),
    (b'ld d, $fe',b'nop'),
], ids=['glyph','nature','species'])
def test_missing_validator_source_fact_refuses(inputs, monkeypatch, tmp_path, old, new):
    source_copy(inputs,monkeypatch,tmp_path,old,new)
    with pytest.raises(ValueError, match='trade (constant|validator facts)'):
        gp.trade_block(*inputs)


@pytest.mark.parametrize('key', ['glyph_floor','nature_count','species_low_max','items'], ids=['glyph','nature','species','table'])
def test_validation_schema_mutants_are_caught(inputs, key):
    trade = gp.trade_block(*inputs)
    if key == 'items':
        trade['validation'][key]['addr'] += 1
    else:
        trade['validation'][key] += 1
    with pytest.raises(AssertionError):
        assert_schema(trade)


# Invoke the existing C3 corpus unchanged, once per loader. No assertion is removed
# or replaced in the binder tests: all native subset/parity assertions run both ways.
CORPUS = next(mark.args[1] for mark in bt.test_validator_parity_with_real_staged_routine.pytestmark
              if mark.name == 'parametrize' and mark.args[0] == 'case')


@pytest.mark.parametrize('case',CORPUS,ids=list(CORPUS))
@pytest.mark.parametrize('loader',['profile','injected'],ids=['profile','injected'])
def test_existing_rom_corpus_both_fact_paths(binder_env, monkeypatch, case, loader):
    original = bt.Binder
    if loader == 'injected':
        def injected(env, **kwargs):
            return original(env,validation=bt.facts(env),**kwargs)
        monkeypatch.setattr(bt,'Binder',injected)
    bt.test_validator_parity_with_real_staged_routine(binder_env,case)


@pytest.mark.parametrize('bad', ['missing','symbol','bank','addr','size','reader-short','reader-value'],
                         ids=['missing','symbol','bank','addr','size','reader-short','reader-value'])
def test_profile_fact_loading_fails_closed(binder_env, bad):
    profile = copy.deepcopy(bt.PROFILE)
    if bad == 'missing':
        del profile['overlay']['trade']['validation']
    elif bad.startswith('reader-'):
        pass
    else:
        table = profile['overlay']['trade']['validation']['items']
        table[bad] = {'symbol':'wrong','bank':0,'addr':0x7FFF,'size':255}[bad]
    mutation = None
    if bad == 'reader-short':
        mutation = ('v.items = clone(spec.read_rom(locator.bank,locator.addr,locator.size))', 'v.items = {}')
    elif bad == 'reader-value':
        mutation = ('v.items = clone(spec.read_rom(locator.bank,locator.addr,locator.size))',
                    'v.items = clone(spec.read_rom(locator.bank,locator.addr,locator.size)); v.items[1] = 2')
    b = bt.Binder(binder_env,profile=profile,mutation=mutation)
    assert b.api is None and b.error and not b.writes


def test_profile_loader_requires_reader_but_explicit_override_does_not(binder_env):
    b = bt.Binder(binder_env,validation=None)
    assert b.api is None and 'ROM reader required' in b.error
    b = bt.Binder(binder_env,validation=bt.facts(binder_env))
    assert b.api is not None and b.call('advertised') is False


def test_both_fact_paths_emit_identical_staging_and_publications(binder_env):
    loaded = bt.Binder(binder_env)
    injected = bt.Binder(binder_env,validation=bt.facts(binder_env))
    for binder in (loaded,injected):
        binder.accepted()
        binder.frame += 1
        assert binder.apply() == 44
    assert loaded.writes == injected.writes
    assert loaded.mem == injected.mem


def test_source_hash_bypass_mutant_is_caught(inputs):
    text = inspect.getsource(gp.trade_block)
    old = 'require(provenance["overlay"]["sources_sha256"].get(rel)'
    assert old in text
    namespace = dict(gp.__dict__)
    exec(text.replace(old,'require(True or provenance["overlay"]["sources_sha256"].get(rel)'),namespace)
    inputs[1]['overlay']['sources_sha256']['patch/polished/src/trade_validate.asm'] = '0'*64
    with pytest.raises(ValueError, match='provenance mismatch'):
        gp.trade_block(*inputs)
    # Mutant emits a family despite the invalid receipt, violating refusal.
    result = namespace['trade_block'](*inputs)
    with pytest.raises(AssertionError):
        assert result is None


@pytest.mark.parametrize("enabled", [0, 1], ids=["disabled-source", "enabled-source"])
def test_production_follows_verified_source_gate(inputs, monkeypatch, tmp_path, enabled):
    symbols, prov = inputs
    for rel in ("patch/gb/slink_abi.inc", "patch/polished/src/trade_frame.asm", "patch/polished/src/trade_service.asm", "patch/polished/src/trade_validate.asm"):
        raw = (gp.ROOT / rel).read_bytes()
        if rel.endswith("trade_service.asm"):
            raw = raw.replace(b"SLINK_TRADE_COMMIT_ENABLE EQU 1", f"SLINK_TRADE_COMMIT_ENABLE EQU {enabled}".encode())
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        prov["overlay"]["sources_sha256"][rel] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(gp, "ROOT", tmp_path)
    block = gp.trade_block(symbols, prov)
    assert block["production"] is bool(enabled)
    assert (block["commit_gate"]["bank"], block["commit_gate"]["addr"]) == symbols["SlinkTradeCommitEnabled"]
