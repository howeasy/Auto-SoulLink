"""Synthetic consumer-visible service traces; no emulator, server or SLink client.

Six positive cases, independently corrupted publications/ownership/restoration,
runner pure parts, and Lua 5.5 compilation without executing the driver.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trade_service_probe", ROOT / "tools/polished_live/trade_service_probe.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class Trace:
    """Fixture author, not an emulator: explicit ROM/host stores build the evidence chain."""

    def __init__(self, case):
        self.case = case
        self.events = []
        self.frame = 100
        self.lease = [0] * 16
        self.record = [1] + [0] * 47
        self.record[31] = 50
        self.ot = [0x80] + [0x53] * 7 + [1, 2, 3]
        self.nick = [0x90] + [0x53] * 10
        self.own0 = P._checksum(self.record + self.ot + self.nick)
        self.ot0 = P._checksum([0] * 70)
        self.ot1 = self.ot0
        self.tx = None

    def add(self, kind, **fields):
        e = {"kind": kind, "ord": len(self.events) + 1, "frame": self.frame, "pc": 0x4480,
             "sp": 0xC0CE, "bank": 0x7E, "vblank": 0, "link": 0, "running": 1, "stack": 0,
             "count": 5, "party_sum": "01234567", "ot_tail_sum": "89abcdef",
             "own0_sum": self.own0, "ot0_sum": self.ot0, "ot1_sum": self.ot1,
             "lease": self.lease.copy(), "sbank": 0x24, "spos": 0x762C, "x": 5, "y": 3}
        e.update(fields)
        self.events.append(e)
        return e

    def tick(self, n=1):
        self.frame += n

    def write(self, owner, offset, value):
        before = self.lease.copy()
        self.lease[offset] = value
        fields = {"offset": offset, "value": value, "before": before}
        if owner == "host":
            fields["tx"] = self.tx
        self.add(owner + "_write", **fields)

    def begin(self, tx):
        self.tick()
        self.tx = tx
        self.add("host_begin", tx=tx, pump="onframeend")

    def end(self):
        self.add("host_end", tx=self.tx)
        self.tx = None

    def publish_query(self):
        self.tick()
        for offset, value in enumerate(P.MAGIC):
            self.write("rom", offset, value)
        for offset, value in ((5, 1), (10, 0), (11, 0), (7, 0), (6, 1)):
            self.write("rom", offset, value)

    def query_reply(self):
        self.begin("query")
        values = [1, 0 if self.case == "no-eligible" else 1] + P.TOKEN
        for offset, value in enumerate(values, 10):
            self.write("host", offset, value)
        self.write("host", 7, self.lease[6])
        self.end()

    def publish_offer(self):
        self.tick()
        self.ot1 = self.own0
        for offset, value in ((9, 0), (8, 255), (5, 2), (7, 1), (6, 2)):
            self.write("rom", offset, value)

    def offer_reply(self):
        self.begin("offer")
        self.write("host", 8, 1 if self.case == "offer-reject" else 0)
        self.write("host", 7, self.lease[6])
        self.end()

    def apply(self):
        self.begin("apply")
        ot = [0x81] + [0x53] * 7 + self.ot[8:]
        sender = [0x81] + [0x53] * 10
        nick = [0x80] * 11 if self.case == "apply-invalid" else self.nick
        payload = self.record + ot + nick
        for symbol, data in (("wOTPartyMon1", self.record), ("wOTPartyMonOTs", ot),
                             ("wOTPartyMonNicknames", nick), ("wOTPlayerName", sender)):
            for i, v in enumerate(data):
                self.add("host_stage_write", tx="apply", symbol=symbol, offset=i, value=v, old=0)
        self.ot0 = P._checksum(payload)
        self.add("staged", tx="apply", staged_sum=self.ot0, invalid=self.case == "apply-invalid",
                 record=bytes(self.record).hex(), ot=bytes(ot).hex(), nick=bytes(nick).hex(),
                 sender=bytes(sender).hex(), source_record=bytes(self.record).hex(),
                 source_ot=bytes(self.ot).hex(), source_nick=bytes(self.nick).hex())
        for offset, value in enumerate(P.MAGIC + [5, 2, 2, 255, 0, 1, 0] + P.TOKEN):
            self.write("host", offset, value)
        self.write("host", 6, 3)
        self.end()
        self.tick()
        self.write("rom", 7, 3)  # pickup ACK precedes incoming validation, not DONE

    def done(self):
        self.tick()
        self.write("rom", 8, 1)
        for offset, value in enumerate(P.MAGIC):
            self.write("rom", offset, value)
        for offset, value in enumerate(P.TOKEN, 12):
            self.write("rom", offset, value)
        for offset, value in ((9, 0), (5, 7), (6, 3), (7, 3)):
            self.write("rom", offset, value)
        self.begin("release")
        self.write("host", 5, 8)
        self.end()

    def close(self):
        self.tick()
        self.add("close")
        for offset in (5, 10, 11):
            self.write("rom", offset, 0)
        self.add("service_return", sp=0xC0D0, ret_sp=0xC0CE)
        self.add("gsb", bank=0x25, sbank=0x2D, spos=0x7595)
        self.add("endtext", bank=0x25, sbank=0x2D, spos=0x7596)
        self.tick(40)
        self.add("final", running=0)
        self.add("move_start", running=0)
        self.tick(24)
        self.add("move_end", running=0, y=4)
        self.add("complete", running=0, y=4, case=self.case)


def good_trace(case):
    t = Trace(case)
    t.add("setup", case=case, synth=True, token=P.TOKEN)
    t.add("service_entry")
    t.publish_query()
    if case == "query-timeout":
        t.tick(600)
    else:
        t.query_reply()
    if case not in ("no-eligible", "query-timeout"):
        t.tick()
        t.add("party_menu")
        t.add("answer", which="party", btn="B" if case == "cancel-menu" else "A", slot=0)
        if case != "cancel-menu":
            t.add("answer", which="confirm", btn="A")
            t.publish_offer()
            t.offer_reply()
            if case.startswith("apply-"):
                t.apply()
                if case == "apply-done1":
                    t.done()
    t.close()
    return t.events


def mutate(trace, kind, **fields):
    out = copy.deepcopy(trace)
    next(e for e in out if e["kind"] == kind).update(fields)
    return out


def rekind(trace, old, new, **fields):
    """Turn the first `old` event into a `new`-kind event (mutate's own `kind` parameter selects, never sets)."""
    out = copy.deepcopy(trace)
    e = next(e for e in out if e["kind"] == old)
    e.update(fields)
    e["kind"] = new
    return out


def renumber(trace):
    for i, e in enumerate(trace, 1):
        e["ord"] = i
    return trace


def missing(trace, kind):
    return renumber([e for e in copy.deepcopy(trace) if e["kind"] != kind])


def open_lease(trace):
    out = copy.deepcopy(trace)
    next(e for e in out if e["kind"] == "final")["lease"][5] = 2
    return out


def done_zero(trace):
    out = copy.deepcopy(trace)
    event = copy.deepcopy(next(e for e in out if e["kind"] == "close"))
    event.update(kind="done_observed", result=0)
    event["lease"][5], event["lease"][8] = 7, 0
    i = next(i for i, e in enumerate(out) if e["kind"] == "close")
    out.insert(i, event)
    return renumber(out)


def generation_early(trace):
    out = copy.deepcopy(trace)
    indices = [i for i, e in enumerate(out) if e["kind"] == "rom_write" and e["lease"][5] == 1]
    i_gen = next(i for i in indices if out[i]["offset"] == 6)
    i_ack = next(i for i in indices if out[i]["offset"] == 7)
    # One defect: swap the final generation/ACK stores and recompute their actual images.
    old = out[i_ack]["before"].copy()
    gen, ack = out[i_gen], out[i_ack]
    gen["before"] = old.copy()
    old[6] = gen["value"]
    gen["lease"] = old.copy()
    ack["before"] = old.copy()
    old[7] = ack["value"]
    ack["lease"] = old.copy()
    out[i_ack], out[i_gen] = gen, ack
    return renumber(out)


@pytest.mark.parametrize("case", P.CASES)
def test_each_good_scenario_passes(case):
    ok, reasons = P.evaluate(case, good_trace(case))
    assert ok, reasons


DEFECTS = (
    ("unbalanced RET", lambda t: mutate(t, "service_return", ret_sp=0xC0CA), "return SP != entry SP"),
    ("party changed", lambda t: mutate(t, "final", party_sum="deadbeef"), "party/OT/nickname checksum changed"),
    ("lease open", open_lease, "lease not closed"),
    ("no endtext", lambda t: missing(t, "endtext"), "endtext: expected exactly once"),
    ("false success", done_zero, "DONE result 0"),
    ("generation early", generation_early, "ROM generation written before payload"),
    ("no movement", lambda t: mutate(t, "move_end", y=3), "player did not move"),
    ("VBlank leaked", lambda t: mutate(t, "final", vblank=1), "final vblank != 0"),
    ("link mode leaked", lambda t: mutate(t, "final", link=1), "final link != 0"),
    ("observation overflow", lambda t: rekind(t, "move_start", "gsb_overflow"), "gsb_overflow"),
    ("early exit", lambda t: missing(t, "complete"), "complete: expected exactly once"),
)


@pytest.mark.parametrize("case", P.CASES)
@pytest.mark.parametrize("_label,defect,reason", DEFECTS, ids=[d[0] for d in DEFECTS])
def test_each_single_defect_fails_for_its_own_reason(case, _label, defect, reason):
    ok, reasons = P.evaluate(case, defect(good_trace(case)))
    assert not ok
    assert any(reason in failure for failure in reasons), reasons


@pytest.mark.parametrize("case", [c for c in P.CASES if c != "query-timeout"])
def test_host_cannot_answer_rom_owned_frame(case):
    trace = good_trace(case)
    begin = next(e for e in trace if e["kind"] == "host_begin")
    begin["lease"][7] = begin["lease"][6]  # already ACKed: ROM owns next native action
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("host wrote while ROM-owned" in r for r in reasons)


def test_timeout_host_cannot_write_unsolicited():
    trace = good_trace("query-timeout")
    e = copy.deepcopy(trace[-1])
    e.update(kind="host_begin", tx="query")
    trace.append(e)
    ok, reasons = P.evaluate("query-timeout", renumber(trace))
    assert not ok
    assert any("host wrote while ROM-owned" in r for r in reasons)


@pytest.mark.parametrize("case", P.CASES)
def test_missing_symbol_fails_closed(case):
    trace = rekind(good_trace(case), "move_start", "missing_symbol", symbol="SlinkTradeEntry")
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("missing_symbol" in r for r in reasons)


def test_offer_reject_must_not_publish_done():
    trace = good_trace("offer-reject")
    e = copy.deepcopy(next(e for e in trace if e["kind"] == "close"))
    e.update(kind="rom_write", offset=7, value=2)
    e["lease"] = P.MAGIC + [7, 2, 2, 1, 0, 1, 1] + P.TOKEN
    e["before"] = e["lease"].copy()
    e["before"][7] = 1
    i = next(i for i, event in enumerate(trace) if event["kind"] == "close")
    trace.insert(i, e)
    ok, reasons = P.evaluate("offer-reject", renumber(trace))
    assert not ok
    assert any("ROM publication order" in r and "done" in r for r in reasons)


@pytest.mark.parametrize("case", ["no-eligible", "query-timeout"])
def test_ineligible_or_unanswered_query_must_not_open_menu(case):
    trace = good_trace(case)
    e = copy.deepcopy(next(e for e in trace if e["kind"] == "close"))
    e["kind"] = "party_menu"
    trace.insert(next(i for i, event in enumerate(trace) if event["kind"] == "close"), e)
    ok, reasons = P.evaluate(case, renumber(trace))
    assert not ok
    assert any("party menu: expected 0" in r for r in reasons)


def test_query_timeout_must_not_close_early():
    trace = good_trace("query-timeout")
    query_frame = next(e["frame"] for e in trace if e["kind"] == "rom_write" and e["offset"] == 6)
    for e in trace:
        if e["frame"] > query_frame:
            e["frame"] -= 100
    ok, reasons = P.evaluate("query-timeout", trace)
    assert not ok
    assert any("QUERY timeout did not wait 600" in r for r in reasons)


@pytest.mark.parametrize("case", ["apply-done1", "apply-invalid"])
def test_apply_staging_must_not_touch_snapshot_slot(case):
    trace = good_trace(case)
    e = next(e for e in trace if e["kind"] == "host_stage_write" and e["symbol"] == "wOTPartyMon1")
    e["offset"] = 48
    ok, reasons = P.evaluate(case, trace)
    assert not ok
    assert any("staging escaped OT slot 0" in r for r in reasons)


def test_apply_requires_validated_decline_result_not_uncertain():
    trace = good_trace("apply-done1")
    for e in trace:
        if e["lease"][5] == 7:
            e["lease"][8] = 2
    ok, reasons = P.evaluate("apply-done1", trace)
    assert not ok
    assert any("APPLY must publish matching DONE result 1" in r for r in reasons)


def test_apply_invalid_must_really_have_no_name_terminator():
    trace = good_trace("apply-invalid")
    staged = next(e for e in trace if e["kind"] == "staged")
    staged["nick"] = bytes([0x80] * 10 + [0x53]).hex()
    ok, reasons = P.evaluate("apply-invalid", trace)
    assert not ok
    assert any("incoming name still has a terminator" in r for r in reasons)


@pytest.mark.parametrize("trace", [None, [], [{}], ["not an event"]])
def test_malformed_trace_is_not_evidence(trace):
    assert not P.evaluate("offer-reject", trace)[0]


@pytest.mark.parametrize("argv", [[], ["--case", "unknown"], ["--case", "offer-reject", "--timeout", "0"],
                                  ["--case", "offer-reject", "--timeout", "-5"],
                                  ["--case", "offer-reject", "--timeout", "NaN"]])
def test_invalid_runner_arguments_fail(argv):
    with pytest.raises(SystemExit):
        P.parse_args(argv)


def provenance(tmp_path, base="1" * 40, output="2" * 40):
    path = tmp_path / "data/polished/overlay_provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_sha1": base, "output": {"sha1": output}}), encoding="utf-8")
    return path


def test_plan_reads_current_provenance_not_a_pinned_digest(tmp_path):
    path = provenance(tmp_path)
    args = P.parse_args(["--case", "apply-done1", "--timeout", "12", "--dry-run"])
    first = P.plan(args, repo=tmp_path, work=tmp_path / "lanes")
    assert first["base_sha1"] == "1" * 40
    assert first["expected_overlay_sha1"] == "2" * 40
    path.write_text(json.dumps({"base_sha1": "a" * 40, "output": {"sha1": "b" * 40}}), encoding="utf-8")
    second = P.plan(args, repo=tmp_path, work=tmp_path / "lanes")
    assert second["expected_overlay_sha1"] == "b" * 40
    assert second["lane"] == str(tmp_path / "lanes/apply-done1")
    assert second["timeout"] == 12
    assert "no cable partner, server, SLink client" in second["disclosure"]
    assert second["cleanup"] == "harness.launch finally kills only its own EmuHawk PID"


@pytest.mark.parametrize("base,output", [(None, "2" * 40), ("1" * 40, "bad"), ("z" * 40, "2" * 40)])
def test_malformed_provenance_fails(base, output, tmp_path):
    with pytest.raises(ValueError, match="provenance"):
        P.read_provenance(provenance(tmp_path, base, output))


def test_dry_run_has_no_staging_or_emulator_side_effects(tmp_path, monkeypatch, capsys):
    provenance(tmp_path)
    original = P.plan
    monkeypatch.setattr(P, "plan", lambda args: original(args, repo=tmp_path, work=tmp_path / "lanes"))
    assert P.main(["--case", "query-timeout", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["service_budget_frames"] == 700
    assert printed["expected_overlay_sha1"] == "2" * 40
    assert not (tmp_path / "lanes").exists()


def test_symbols_keep_missing_optional_service_hooks_absent(tmp_path):
    path = tmp_path / "probe.sym"
    path.write_text("7e:4480 SlinkTradeEntry\n01:d28b wOTPartyMon1\n; ignored\n", encoding="utf-8")
    assert P.read_symbols(path) == {"SlinkTradeEntry": [0x7E, 0x4480], "wOTPartyMon1": [1, 0xD28B]}


def test_lua55_loads_driver_without_running_it():
    from lupa.lua55 import LuaRuntime

    lua = LuaRuntime(unpack_returned_tuples=True)
    compile_only = lua.eval("function(source) local f, why = load(source, '@trade_service_probe.lua'); return f ~= nil, why end")
    ok, why = compile_only((ROOT / "tools/polished_live/trade_service_probe.lua").read_text(encoding="utf-8"))
    assert ok, why
