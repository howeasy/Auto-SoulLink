"""RR ABI1 stays outside the unqualified durable-trade contract."""
from pathlib import Path

from lupa import LuaRuntime

from server.adapters import get_adapter
from server.manager import OPTION_SUPPORT
from server.state import SoulLinkState
from tests.unit.gen3_world import World
from tests.unit.test_gen3_client import KB, A, B, party

ROOT = Path(__file__).resolve().parents[2]


def test_real_rr_bootstrap_does_not_construct_a_trade_journal():
    lua = LuaRuntime()
    entry = lua.execute((ROOT / "lua/gen3/entry.lua").read_text())
    g = lua.globals()
    g.Entry, g.ROOT = entry, ROOT.as_posix()
    g.admitted = lua.table(kind="companion", pack="gen3_rr", title="radical_red", rom_hash="ab" * 20)
    g.player = "a"
    g.console = lua.table(log=lambda *_: None)
    g.io_ = lua.table()
    # Execute the actual production construction block. Opening its store or
    # constructing the journal is a failure; no CLR/filesystem adapter is needed.
    source = (ROOT / "lua/gen3/run.lua").read_text()
    start = source.index("-- <<< durable trade storage <<<") + len("-- <<< durable trade storage <<<")
    end = source.index("\nlocal ok_build", start)
    lua.execute(source[start:end])
    assert g.io_.trade_journal is None


def test_rr_server_and_manager_report_trade_unavailable(tmp_path):
    adapter = get_adapter("gen3_frlge", is_rr=True, rom_type="firered_rr")
    assert not adapter.supports_trade_recovery()
    state = SoulLinkState(data_dir=str(tmp_path), adapter=adapter)
    commands = state.handle_event("a", {"event": "trade_request"})
    assert state.pending_trade is None
    assert any(c["cmd"] == "msgbox" and "unavailable" in c["text"].lower() for c in commands)
    support = OPTION_SUPPORT["pc_trade_npc"]["gen3_frlge_rr"]
    assert support["ok"] is False and "unavailable" in support["why"].lower()


def test_rr_no_journal_has_no_withholding_and_rejects_trade_without_writes():
    w = World("gen3_rr", "radical_red", "companion")
    w.set_party(party(A, B))
    w.step_to(60)
    assert w.events("hello")[0]["trade_prepare"] is False
    assert not w.events("hello")[0].get("party_hidden")
    w.command(cmd="config")
    w.step()
    before = len(w.writes)
    w.command(cmd="apply_trade", token="unavailable", slot=1, old_key=KB, blob_hex=w.encode(party(B)[0]).hex())
    w.step(3)
    assert len(w.writes) == before
    assert w.events("trade_done")[-1]["new_key"] == KB  # unchanged refusal, no raw-swap success
    assert w.events("menu_result")[-1]["withdraw"] is True
    assert not any(m.get("party_hidden") for m in w.events("tick"))
