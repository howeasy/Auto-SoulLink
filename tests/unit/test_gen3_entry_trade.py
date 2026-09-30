"""Composition/admission MODEL controls; no companion artifact is qualified here."""
import copy
import json
import shutil

import pytest
from lupa import lua54

from tests.unit import test_gen3_entry as entry_model, test_gen3_native as native_model
from tests.unit.test_gen3_native_trade import TradeNativeWorld


@pytest.fixture
def entry_model_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_model, "lupa", lua54)
    monkeypatch.setattr(native_model, "lupa", lua54)
    root = native_model.ROOT
    shutil.copytree(root / "lua", tmp_path / "lua")
    # gen3_exp (X3): registered in Entry.PACKS, so admission opens its pack too
    for pack in ("gen3_frlg", "gen3_rr", "gen3_emerald", "gen3_frlge", "gen3_exp"):
        shutil.copytree(root / "data/games" / pack, tmp_path / "data/games" / pack)
    return tmp_path


def edit_json(path, modify):
    value = json.loads(path.read_text(encoding="utf-8"))
    modify(value)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.mark.parametrize("mode", ["hash", "anchors", "build"])
def test_nonproduction_identity_is_refused_even_if_pinned(entry_model_tree, mode):
    root = entry_model_tree
    edit_json(root / "data/games/gen3_frlg/engine_signals.json", lambda obj:
              obj["titles"]["firered"]["artifacts"]["clean"].update(production=False))
    w = entry_model.World(pack="gen3_frlg", title="firered", build=False)
    if mode == "build":
        with pytest.raises(lua54.LuaError, match="non-production"):
            entry_model._production(w, root=root.as_posix())
    else:
        args = w.lua.table(root=root.as_posix(), json=w.lua.execute((root / "lua/json_codec.lua").read_text()),
                           rom_hash=entry_model.artifact_of("gen3_frlg", "firered", "clean")["rom_sha1"]
                           if mode == "hash" else "ab"*20,
                           rom_read=w._rom_read, header_code="BPRE")
        admitted, why = w.Entry.admit_routed(args)
        assert admitted is None and "non-production" in why


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
@pytest.mark.parametrize("production", [True, None, False])
def test_only_explicit_production_fr_companion_constructs_the_trade_binding(entry_model_tree, production, monkeypatch, title):
    monkeypatch.delenv("SLINK_GEN3_BATTLE_NONCE", raising=False)
    root = entry_model_tree
    model = TradeNativeWorld()
    edit_json(root / "data/games/gen3_frlg/profile.json", lambda obj: obj.update(native=model.n))

    def companion(obj):
        rows = obj["titles"][title]["artifacts"]
        rows["companion"] = copy.deepcopy(rows["clean"])
        rows["companion"].update(rom_sha1="ab"*20, rom_md5="cd"*16)
        if production is not None:
            rows["companion"]["production"] = production
    edit_json(root / "data/games/gen3_frlg/engine_signals.json", companion)
    edit_json(root / "data/games/gen3_frlg/write_checkpoint.json", lambda obj: [
        anchor["expected_hex"].update(companion=anchor["expected_hex"]["clean"])
        for anchor in obj[title]["anchors"].values()])
    w = entry_model.World(pack="gen3_frlg", title=title, build=False)
    if production is not True:
        with pytest.raises(lua54.LuaError, match="production"):
            entry_model._production(w, root=root.as_posix(), kind="companion")
        return
    w.io.trade_journal = w.lua.table(ready=lambda *_: True, hidden=lambda *_: False,
                                    outstanding=lambda *_: w.lua.table(), has_entries=lambda *_: False)
    client, parts = entry_model._production(w, root=root.as_posix(), kind="companion", battle_nonce_seed="1234567800000001")
    assert parts.native is not None and parts.native_present
    assert parts.native.trade_capable(parts.native) is False
    w.poke(model.n["BASE"], model.n["SIG"].to_bytes(4, "little"))
    w.poke(model.n["BASE"] + 4, b"\x02\x00")
    w.poke(model.n["BASE"] + 0x40, b"\x01\x00\x00\x00")
    # Composition test: real writes/native modules over a MODEL-safe checkpoint.
    parts.safety.check = lambda *_: True
    parts.safety.snapshot = lambda *_: w.lua.table()
    parts.policy.check = lambda *_: True
    w.io.write_u8 = lambda a, v, *_: w.poke(a, bytes([v]))
    client.hello_sent = True
    serviced = parts.native.service(parts.native)
    assert w._read(model.n["BASE"] + 0x44, 4) == 0x12345678, (serviced, w.logs)
    assert parts.native.trade_capable(parts.native) is True
    assert client.hello_sent is False, "the bound capability must be advertised after the initial hello"


@pytest.mark.parametrize("production", [True, None])
def test_rr_production_companion_binds_its_durable_descriptor(entry_model_tree, production, monkeypatch):
    """RR-DURABLE: the admitted RR companion binds the trade epoch into its shadow block
    (native.TRADE_BASE + 0x44, never the ABI1 mailbox's +0x44 SwapState) when production is
    explicit; without it the companion still builds (ABI1) but never trades."""
    monkeypatch.delenv("SLINK_GEN3_BATTLE_NONCE", raising=False)
    root = entry_model_tree

    def mark(obj):
        rows = obj["titles"]["radical_red"]["artifacts"]["companion"]
        rows.pop("production", None)
        if production is not None:
            rows["production"] = production
    edit_json(root / "data/games/gen3_rr/engine_signals.json", mark)
    w = entry_model.World(pack="gen3_rr", title="radical_red", build=False)
    n = json.loads((root / "data/games/gen3_rr/profile.json").read_text(encoding="utf-8"))["native"]
    w.io.trade_journal = w.lua.table(ready=lambda *_: True, hidden=lambda *_: False,
                                    outstanding=lambda *_: w.lua.table(), has_entries=lambda *_: False)
    client, parts = entry_model._production(w, root=root.as_posix(), kind="companion",
                                            battle_nonce_seed="1234567800000001")
    w.poke(n["BASE"], n["SIG"].to_bytes(4, "little"))
    w.poke(n["BASE"] + 4, b"\x01\x00")
    w.poke(n["TRADE_BASE"] + 0x40, b"\x01\x00\x00\x00")
    parts.safety.check = lambda *_: True
    parts.safety.snapshot = lambda *_: w.lua.table()
    parts.policy.check = lambda *_: True
    w.io.write_u8 = lambda a, v, *_: w.poke(a, bytes([v]))
    parts.native.service(parts.native)
    bound = w._read(n["TRADE_BASE"] + 0x44, 4)
    assert w._read(n["BASE"] + 0x44, 4) == 0
    assert (bound, parts.native.trade_capable(parts.native)) == (
        (0x12345678, True) if production else (0, False))
