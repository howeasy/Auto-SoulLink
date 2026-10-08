"""C3 real Lua binder + shared permit/lease against the assembled proposer service.

Native UI/frame routines use the existing service rig traps; no emulator/live
qualification. Validation facts now come from the generated profile and the
built ROM table; C4 owns ROM reader admission. Explicit fact overrides remain.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys

import pytest
from lupa.lua55 import LuaRuntime

from tests.unit import test_polished_trade_responder as resp, test_polished_trade_service as svc

env = svc.env

ROOT = svc.REPO
PATH = ROOT / "lua/gen2/polished_trade.lua"
PROFILE = json.loads((ROOT / "data/games/polished_crystal/profile.json").read_bytes())["titles"][
    "polished"
]
LEASE_BASE = PROFILE["overlay"]["trade"]["lease"]["base"]
FIELDS = PROFILE["overlay"]["trade"]["lease"]["fields"]
CMD = PROFILE["overlay"]["trade"]["commands"]


def facts(env):
    rel = "patch/polished/src/trade_validate.asm"
    raw = (ROOT / rel).read_bytes()
    prov = json.loads((ROOT / "data/polished/overlay_provenance.json").read_bytes())
    assert hashlib.sha256(raw).hexdigest() == prov["overlay"]["sources_sha256"][rel]
    validation = copy.deepcopy(PROFILE['overlay']['trade']['validation'])
    locator = validation['items']
    assert (locator['bank'],locator['addr']) == env.sym['SlinkTradeAllowedItems']
    start = svc.pc._flat(locator['bank'],locator['addr'])
    assert start+locator['size'] == env.flat('SlinkTradeAllowedItemsEnd')
    validation['items'] = list(env.rom[start:start+locator['size']])
    return validation


def payload():
    s = svc.Stage()
    return {"blob": list(s.rec + s.ot + s.nick), "sender": list(s.sender)}


class Binder:
    def __init__(
        self,
        env,
        *,
        machine=None,
        clock=None,
        profile=None,
        dev=True,
        test_hooks=False,
        mutation=None,
        validation="built",
    ):
        self.frame, self.writes, self.fail_at = 0, [], None
        self.mem = bytearray(65536)
        self.machine, self.clock = machine, clock
        self.logs: list[str] = []
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.pyread, g.pywrite = self.read, self.write
        g.pylog = lambda message: self.logs.append(str(message))
        g.pyframe = lambda: self.clock() if self.clock else self.frame
        g.pymapped = lambda b, a, n: True
        source = PATH.read_text(encoding="utf-8")
        if mutation:
            before, after = mutation
            assert before in source
            source = source.replace(before, after)
        self.pt = self.lua.eval("function(s,p) return assert(load(s,'@'..p))() end")(
            source, str(PATH).replace("\\", "/")
        )
        io = self.lua.execute("""return {
            read_u8=function(a) return pyread(a) end,
            read_range=function(a,n) local b={} for i=1,n do b[i]=pyread(a+i-1) end return b end,
            write_u8=function(a,b,d) return pywrite(a,b) end,
            framecount=function() return pyframe() end,
            bank_valid=function(b,a,n) return pymapped(b,a,n) end}""")
        spec = self.lua.table_from(
            {
                "profile": copy.deepcopy(profile or PROFILE),
                "dev": dev,
                "test_hooks": test_hooks,
                "validation": None if validation == "built" else validation,
            },
            recursive=True,
        )
        spec.io = io
        spec.log = self.lua.eval("function(message) pylog(message) end")
        if validation == 'built':
            g.pyrom = lambda bank, addr, size: self.lua.table_from(list(
                env.rom[svc.pc._flat(bank,addr):svc.pc._flat(bank,addr)+size]))
            spec.read_rom = self.lua.eval('function(bank,addr,size) return pyrom(bank,addr,size) end')
        out = self.pt.compose(spec)
        self.api, self.error = out if isinstance(out, tuple) else (out, None)

    def read(self, a):
        return self.machine.peek(a)[0] if self.machine else self.mem[a]

    def put(self, a, value):
        if self.machine:
            self.machine.poke(a, value)
        else:
            self.mem[a] = value

    def write(self, a, value):
        self.writes.append((a, value))
        if len(self.writes) == self.fail_at:
            raise RuntimeError("injected write failure")
        self.put(a, value)

    def call(self, name, *args):
        assert self.api is not None, self.error
        return self.api[name](
            self.api,
            *(
                self.lua.table_from(a, recursive=True) if isinstance(a, (list, dict)) else a
                for a in args
            ),
        )

    def frame_image(self, command, gen=42, ack=41, slot=2):
        t = PROFILE["overlay"]["trade"]
        lease, f = t["lease"], t["lease"]["fields"]
        for i in range(lease["size"]):
            self.put(lease["base"] + i, 0)
        for i, v in enumerate(lease["magic"]):
            self.put(lease["base"] + i, v)
        for k, v in {
            "version": lease["version"],
            "command": t["commands"][command],
            "generation": gen,
            "ack": ack,
            "slot": slot,
        }.items():
            self.put(lease["base"] + f[k], v)
        for i, v in enumerate(svc.TOKEN):
            self.put(lease["base"] + f["token"] + i, v)

    def accepted(self, gen=43):
        self.frame_image("QUERY", gen=(gen - 1) % 256, ack=(gen - 2) % 256)
        assert self.call("answer_query", (gen - 1) % 256, 4, list(svc.TOKEN)) is True
        self.frame_image("OFFER", gen=gen, ack=(gen - 1) % 256)
        assert self.call("answer_offer", gen, True) is True

    def apply(self, data=None, slot=2, token=None):
        return self.call(
            "arm",
            PROFILE["overlay"]["trade"]["commands"]["APPLY"],
            slot,
            list(svc.TOKEN) if token is None else token,
            payload() if data is None else data,
        )


def test_default_off(env):
    b = Binder(env, dev=False)
    assert b.api is None and "development proposer trade disabled" in b.error
    assert b.writes == []


@pytest.mark.parametrize(
    "part",
    [
        "lease",
        "entries",
        "staging",
        "snapshot",
        "commands",
        "timeouts",
        "capabilities",
        "dispatcher_stack_pin_names",
    ],
    ids=["lease", "entries", "staging", "snapshot", "commands", "timeouts", "caps", "pins"],
)
def test_partial_family_refused(env, part):
    p = copy.deepcopy(PROFILE)
    del p["overlay"]["trade"][part]
    b = Binder(env, profile=p)
    assert b.api is None and b.error
    assert not b.writes


def test_query_ack_last_and_gap(env):
    b = Binder(env)
    b.accepted()
    assert b.call("advertised") is False
    lease = PROFILE["overlay"]["trade"]["lease"]
    assert [a - lease["base"] for a, _ in b.writes] == [10, 11, 12, 13, 14, 15, 7, 8, 7]
    before = list(b.writes)
    assert b.apply()[1:] == ("PENDING", "OFFER frame gap required")
    assert b.writes == before
    b.frame += 1
    assert b.apply() == 44
    expected = payload()
    t = PROFILE["overlay"]["trade"]
    for k, raw in [
        ("party", expected["blob"][:48]),
        ("ot", expected["blob"][48:59]),
        ("nickname", expected["blob"][59:]),
        ("sender", expected["sender"]),
    ]:
        s = t["staging"][k]
        assert list(b.mem[s["addr"] : s["addr"] + s["size"]]) == raw
    assert b.writes[-1] == (lease["base"] + lease["fields"]["generation"], 44)


@pytest.mark.parametrize("gen", [0, 254, 255], ids=["zero", "fe", "ff"])
def test_generation_wrap(env, gen):
    b = Binder(env)
    b.accepted(gen)
    b.frame += 1
    assert b.apply() == (gen + 1) % 256


@pytest.mark.parametrize("name", ["party", "ot", "nickname"], ids=["party", "ot", "nick"])
def test_snapshot_permit_refuses_before_first_byte(env, name):
    b = Binder(env, test_hooks=True)
    b.accepted()
    b.frame += 1
    before = list(b.writes)
    w = b.api.test_hooks
    addr = PROFILE["overlay"]["trade"]["snapshot"][name]["addr"]
    with pytest.raises(Exception, match="outside domain bounds"):
        w.write_bytes(w, addr, b.lua.table_from([17]))
    assert b.writes == before


def real_run(env, mutation=None, gen0=0x10):
    rig = svc.Rig(env, gen0=gen0)
    result = {}

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame, mutation=mutation)
        result["binder"] = b
        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        assert b.call("answer_offer", o.gen, True) is True
        immediate = b.apply()
        result["immediate"] = immediate
        if isinstance(immediate, tuple):
            assert immediate[1:] == ("PENDING", "OFFER frame gap required")
            yield  # Exactly the NEXT frame; ROM gets to consume the OFFER answer.
            gen = b.apply()
        else:
            gen = immediate
        result["gen"] = gen
        assert isinstance(gen, int)
        while not b.call("poll_done"):
            yield
        done = b.call("poll_done")
        result["done"] = done.disposition
        assert done.result == 1
        assert b.call("release", gen) is True

    run = rig.run(host)
    return rig, run, result


@pytest.mark.parametrize("gen0", [0x10, 0xFD], ids=["normal", "apply-wrap"])
def test_real_service_one_frame_gap(env, gen0):
    rig, run, result = real_run(env, gen0=gen0)
    svc.common(rig, run, "QOADC")
    assert result["done"] == "NOT_PERFORMED"
    assert svc.snapshot_matches(rig, run)
    assert result["gen"] == (gen0 + 3) % 256


def test_gap_mutant_real_service_closes_without_done(env):
    _, run, result = real_run(env, ("if frame() <= answered_at then", "if false then"))
    assert run.events == "QOC"
    assert "done" not in result
    with pytest.raises(AssertionError):
        assert run.events == "QOADC"


def test_snapshot_allowlist_mutant_caught(env):
    b = Binder(
        env,
        test_hooks=True,
        mutation=(
            "for _,s in ipairs(protected) do all[#all+1]=s end",
            "for _,s in ipairs(protected) do all[#all+1]=s; spans[#spans+1]=s end",
        ),
    )
    b.accepted()
    b.frame += 1
    before = list(b.writes)
    w = b.api.test_hooks
    addr = PROFILE["overlay"]["trade"]["snapshot"]["party"]["addr"]
    w.write_bytes(w, addr, b.lua.table_from([17]))
    with pytest.raises(AssertionError):
        assert b.writes == before


def test_staging_span_mutant_caught(env):
    b = Binder(
        env,
        mutation=(
            "addr=st.party.addr,bytes=slice(b,1,st.party.size)",
            "addr=snap.party.addr,bytes=slice(b,1,st.party.size)",
        ),
    )
    b.accepted()
    b.frame += 1
    before = list(b.writes)
    out = b.apply()
    assert out[0] is None and "outside domain bounds" in str(out)
    assert b.writes == before  # whole batch preflight, not one late refusal
    with pytest.raises(AssertionError):
        assert out == 44


@pytest.mark.parametrize(
    "case",
    [
        "species0",
        "speciesff",
        "ext0",
        "extmax",
        "level0",
        "level101",
        "nature25",
        "mail",
        "ot-long",
        "nick-low",
        "sender-low",
        "valid",
        "egg",
        "metadata",
    ],
    ids=[
        "species0",
        "speciesff",
        "ext0",
        "extmax",
        "level0",
        "level101",
        "nature25",
        "mail",
        "ot-long",
        "nick-low",
        "sender-low",
        "valid",
        "egg",
        "metadata",
    ],
)
def test_validator_parity_with_real_staged_routine(env, case):
    p = payload()
    edits = {
        "species0": (0, 0),
        "speciesff": (0, 255),
        "level0": (31, 0),
        "level101": (31, 101),
        "nature25": (20, 25),
        "mail": (1, 245),
        "nick-low": (59, 1),
        "egg": (21, 64),
    }
    if case in edits:
        i, v = edits[case]
        p["blob"][i] = v
    elif case == "ext0":
        p["blob"][0], p["blob"][21] = 0, 32
    elif case == "extmax":
        p["blob"][0], p["blob"][21] = 36, 32
    elif case == "ot-long":
        p["blob"][48:56] = [128] * 8
    elif case == "sender-low":
        p["sender"][0] = 1
    elif case == "metadata":
        p["blob"][56:59] = [0, 255, 1]
    b = Binder(env)
    b.accepted()
    b.frame += 1
    before = list(b.writes)
    accepted = isinstance(b.apply(p), int)
    m = svc.S.SM83(env.rom, env.sym["SlinkTradeValidateIncomingStaged"][0])
    for name, raw in [
        ("party", p["blob"][:48]),
        ("ot", p["blob"][48:59]),
        ("nickname", p["blob"][59:]),
        ("sender", p["sender"]),
    ]:
        m.poke(PROFILE["overlay"]["trade"]["staging"][name]["addr"], bytes(raw))
    m.call_routine(env.a("SlinkTradeValidateIncomingStaged"))
    assert accepted == (not m.cf)
    if not accepted:
        assert b.writes == before


def test_partial_staging_fault_before_publication_is_not_performed_and_closed(env):
    # Owner ruling 2026-10-07: a staging fault leaves the lease as the held OFFER (no APPLY byte, no
    # generation), so it is pre-APPLY: NOT_PERFORMED, the lease closed through the cancel path, logged once.
    b = Binder(env)
    b.accepted()
    b.frame += 1
    b.fail_at = len(b.writes) + 5
    result = b.apply()
    assert result[1] == "NOT_PERFORMED" and "APPLY not published" in result[2]
    assert "injected write failure" in result[2]
    assert b.read(LEASE_BASE + FIELDS["command"]) == CMD["OFFER"]
    assert b.read(LEASE_BASE + FIELDS["generation"]) == 43 == b.read(LEASE_BASE + FIELDS["ack"])
    assert [b.read(LEASE_BASE + FIELDS["token"] + i) for i in range(4)] == [0, 0, 0, 0]
    before = list(b.writes)
    b.fail_at = None
    assert b.apply()[1:] == ("NOT_PERFORMED", result[2]) and b.writes == before
    assert b.call("disposition") == ("NOT_PERFORMED", result[2])
    assert len(b.logs) == 1 and "APPLY not published" in b.logs[0]
    b.put(LEASE_BASE + FIELDS["command"], 0)
    assert b.call("reset") is True


@pytest.mark.parametrize(
    "missing",
    ["glyph_floor", "nature_count", "species_low_max", "items", "all"],
    ids=["glyph", "nature", "species", "items", "all"],
)
def test_missing_validation_facts_refused(env, missing):
    v = facts(env)
    if missing == "all":
        v = None
    else:
        del v[missing]
    b = Binder(env, validation=v)
    assert b.api is None and b.error and not b.writes


@pytest.mark.parametrize(
    "kind",
    ["glyph", "nature", "species", "table-short", "table-value"],
    ids=["glyph", "nature", "species", "table-short", "table-value"],
)
def test_malformed_validation_facts_refused(env, kind):
    v = facts(env)
    if kind == "glyph":
        v["glyph_floor"] = 0
    elif kind == "nature":
        v["nature_count"] = 100
    elif kind == "species":
        v["species_low_max"] = 256
    elif kind == "table-short":
        v["items"].pop()
    else:
        v["items"][1] = 2
    b = Binder(env, validation=v)
    assert b.api is None and b.error and not b.writes


@pytest.mark.parametrize(
    "field",
    ["command", "generation", "ack", "slot", "token", "version", "magic", "result"],
    ids=["cmd", "gen", "ack", "slot", "token", "version", "magic", "result"],
)
def test_changed_offer_lease_refuses_zero_write(env, field):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    lease = PROFILE["overlay"]["trade"]["lease"]
    addr = lease["base"] + lease["fields"][field]
    b.put(addr, (b.read(addr) + 1) % 256)
    before = list(b.writes)
    result = b.apply()
    assert result[0] is None and result[1] == "PENDING"
    assert b.writes == before


@pytest.mark.parametrize(
    "kind", ["slot", "token", "prompt", "repeat"], ids=["slot", "token", "prompt", "repeat"]
)
def test_invalid_apply_request_is_not_staged(env, kind):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    if kind == "repeat":
        assert b.apply() == 44
    before = list(b.writes)
    if kind == "slot":
        result = b.apply(slot=1)
    elif kind == "token":
        result = b.apply(token=[1, 2, 3, 4])
    elif kind == "prompt":
        result = b.call(
            "arm", PROFILE["overlay"]["trade"]["commands"]["PROMPT"], 2, list(svc.TOKEN), payload()
        )
    else:
        result = b.apply()
    assert result[0] is None and b.writes == before


@pytest.mark.parametrize(
    "result", [0, 1, 2, 3], ids=["zero", "not-performed", "uncertain", "three"]
)
def test_done_never_reports_completion(env, result):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    gen = b.apply()
    b.frame_image("DONE", gen=gen, ack=gen)
    lease = PROFILE["overlay"]["trade"]["lease"]
    b.put(lease["base"] + lease["fields"]["result"], result)
    done = b.call("poll_done")
    assert done.disposition == ("NOT_PERFORMED" if result == 1 else "UNCERTAIN")
    before = list(b.writes)
    if result == 1:
        assert b.call("release", gen) is True
    else:
        assert b.call("release", gen)[1] == "UNCERTAIN" and b.writes == before


def test_wrong_bank_preflight_stages_nothing(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    b.lua.globals().pymapped = lambda bank, a, n: bank == 0
    before = list(b.writes)
    assert b.apply()[1] == "PENDING"
    assert b.writes == before


def test_swallowed_staging_write_does_not_publish_apply(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    addr = PROFILE["overlay"]["trade"]["staging"]["party"]["addr"]

    def swallow(a, value):
        if a != addr:
            b.write(a, value)

    b.lua.globals().pywrite = swallow
    result = b.apply()
    # The staging readback failed before any lease byte of the APPLY: pre-APPLY, so NOT_PERFORMED and the
    # lease is closed through the cancel path (token zeroed; command and generation untouched).
    assert result[1] == "NOT_PERFORMED" and "readback mismatch" in result[2]
    lease = PROFILE["overlay"]["trade"]["lease"]
    assert (
        b.read(lease["base"] + lease["fields"]["command"])
        == PROFILE["overlay"]["trade"]["commands"]["OFFER"]
    )
    assert [b.read(LEASE_BASE + FIELDS["token"] + i) for i in range(4)] == [0, 0, 0, 0]
    assert b.call("disposition")[0] == "NOT_PERFORMED" and len(b.logs) == 1


def test_advisory_bypass_mutant_violates_rom_subset(env):
    b = Binder(env, mutation=("if low == 0 or low >", "if false and low == 0 or low >"))
    data = payload()
    data["blob"][0] = 0
    b.accepted()
    b.frame += 1
    screened = isinstance(b.apply(data), int)
    m = svc.S.SM83(env.rom, env.sym["SlinkTradeValidateIncomingStaged"][0])
    for name, raw in [
        ("party", data["blob"][:48]),
        ("ot", data["blob"][48:59]),
        ("nickname", data["blob"][59:]),
        ("sender", data["sender"]),
    ]:
        m.poke(PROFILE["overlay"]["trade"]["staging"][name]["addr"], bytes(raw))
    m.call_routine(env.a("SlinkTradeValidateIncomingStaged"))
    assert screened and m.cf
    with pytest.raises(AssertionError):
        assert not screened or not m.cf


def test_missing_whole_family(env):
    profile = copy.deepcopy(PROFILE)
    del profile["overlay"]["trade"]
    b = Binder(env, profile=profile)
    assert b.api is None and "overlay.trade required" in b.error


@pytest.mark.parametrize(
    "group,name",
    [
        *[("entries", n) for n in PROFILE["overlay"]["trade"]["entries"]],
        *[("staging", n) for n in PROFILE["overlay"]["trade"]["staging"]],
        *[("snapshot", n) for n in PROFILE["overlay"]["trade"]["snapshot"]],
    ],
    ids=str,
)
def test_missing_family_leaf(env, group, name):
    profile = copy.deepcopy(PROFILE)
    del profile["overlay"]["trade"][group][name]
    b = Binder(env, profile=profile)
    assert b.api is None and b.error and not b.writes


def test_reset_requires_closed_proved_not_performed(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    gen = b.apply()
    assert b.call("reset")[1] == "UNCERTAIN"
    b.frame_image("DONE", gen=gen, ack=gen)
    lease = PROFILE["overlay"]["trade"]["lease"]
    b.put(lease["base"] + lease["fields"]["result"], 1)
    assert b.call("poll_done").disposition == "NOT_PERFORMED"
    assert b.call("release", gen) is True
    assert b.call("reset")[1] == "PENDING"
    b.put(lease["base"] + lease["fields"]["command"], 0)
    assert b.call("reset") is True
    b.accepted()
    b.frame += 1
    assert b.apply() == 44


def test_all_future_capabilities_still_do_not_advertise(env):
    profile = copy.deepcopy(PROFILE)
    t = profile["overlay"]["trade"]
    t["production"] = True
    for cap, name, addr in [
        ("responder_service", "SlinkTradeResponderService", 0x5000),
        ("commit", "SlinkTradeCommit", 0x5100),
    ]:
        t["capabilities"][cap] = True
        for label, where in [(name, addr), (name + "End", addr + 16)]:
            t["entries"][label] = {"symbol": label, "bank": 126, "addr": where}
    b = Binder(env, profile=profile)
    assert b.call("advertised") is False
    b = Binder(env, profile=profile, dev=False)
    assert b.api is None and "disabled" in b.error


def diagnostic_write(b, addr, values):
    hooks = b.api.test_hooks
    assert hooks is not None, "explicit dev test hooks required"
    return hooks.write_bytes(hooks, addr, b.lua.table_from(values))


def test_test_hooks_are_explicit_and_refused_without_dev(env):
    b = Binder(env)
    assert b.api.test_hooks is None and b.api.writes is None
    disabled = Binder(env, dev=False, test_hooks=True)
    assert disabled.api is None and "disabled" in disabled.error
    assert not disabled.writes


def test_raw_writer_cannot_bypass_same_frame_offer_real_service(env):
    rig = svc.Rig(env)
    observed = {}

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame, test_hooks=True)
        observed["binder"] = b
        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        assert b.call("answer_offer", o.gen, True) is True
        before = list(b.writes)
        # Exercise the old exploit if a raw writer ever leaks again.
        legacy = b.api.writes
        if legacy is not None:
            legacy.arm()
            legacy.write_bytes(legacy, rig.lease + 5, b.lua.table_from([5, (o.gen + 1) % 256]))
        assert b.writes == before
        blocked = diagnostic_write(b, rig.lease + 5, [5, (o.gen + 1) % 256])
        assert blocked[1:] == ("PENDING", "OFFER frame gap required")
        assert b.writes == before
        yield
        gen = b.apply()
        assert isinstance(gen, int)
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "NOT_PERFORMED"
        assert b.call("release", gen) is True

    run = rig.run(host)
    svc.common(rig, run, "QOADC")
    assert svc.snapshot_matches(rig, run)
    assert observed["binder"].call("disposition")[0] == "NOT_PERFORMED"


def test_diagnostic_requires_accepted_offer_and_consumes_one_attempt(env):
    b = Binder(env, test_hooks=True)
    addr = PROFILE["overlay"]["trade"]["staging"]["party"]["addr"]
    assert diagnostic_write(b, addr, [17])[1] == "PENDING"
    assert not b.writes
    b.accepted()
    before = list(b.writes)
    assert diagnostic_write(b, addr, [17])[1:] == ("PENDING", "OFFER frame gap required")
    assert b.writes == before
    b.frame += 1
    assert diagnostic_write(b, addr, [17]) is True
    assert b.read(addr) == 17
    after = list(b.writes)
    assert diagnostic_write(b, addr, [18])[1] == "PENDING"
    assert b.apply()[1] == "PENDING"
    assert b.writes == after


@pytest.mark.parametrize("path", ["query", "offer", "apply", "release", "diagnostic"],
                         ids=["query", "offer", "apply", "release", "diag"])
def test_partial_diagnostic_exception_poisons_every_write_path_and_reset(env, path):
    b = Binder(env, test_hooks=True)
    b.accepted()
    b.frame += 1
    addr = PROFILE["overlay"]["trade"]["staging"]["party"]["addr"]
    b.fail_at = len(b.writes) + 2
    with pytest.raises(Exception, match="injected write failure"):
        diagnostic_write(b, addr, [17, 18])
    assert b.read(addr) == 17
    state, reason = b.call("disposition")
    assert state == "UNCERTAIN" and "injected write failure" in reason
    before = list(b.writes)
    b.fail_at = None
    actions = {
        "query": lambda: b.call("answer_query", 42, 4, list(svc.TOKEN)),
        "offer": lambda: b.call("answer_offer", 43, True),
        "apply": b.apply,
        "release": lambda: b.call("release", 44),
        "diagnostic": lambda: diagnostic_write(b, addr, [19]),
    }
    assert actions[path]()[1:] == ("UNCERTAIN", reason)
    assert b.writes == before
    assert b.call("poll_query") is None and b.call("poll_offer") is None
    lease = PROFILE["overlay"]["trade"]["lease"]
    b.put(lease["base"] + lease["fields"]["command"], 0)
    assert b.call("closed") is True
    assert b.call("reset")[1] == "UNCERTAIN"
    assert b.call("disposition") == ("UNCERTAIN", reason)
    assert b.writes == before


@pytest.mark.parametrize("publication,events", [
    ("query", "QC"), ("offer", "QOC"), ("apply", "QOC"), ("release", "QOADC"),
], ids=["query-ack", "offer-ack", "apply-gen", "release"])
def test_silently_dropped_lease_publication_obeys_apply_boundary_real_service(env, publication, events):
    rig = svc.Rig(env)
    observed = {}

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame)
        observed["binder"] = b

        def refuse_success(callback, offset, wanted):
            address = rig.lease + offset
            old = b.read(address)
            assert old != wanted

            def drop(a, value):
                if (a, value) != (address, wanted):
                    b.write(a, value)

            b.lua.globals().pywrite = drop
            result = callback()
            expected_disposition = "NOT_PERFORMED" if publication == "apply" else "UNCERTAIN"
            assert result[0] is None and result[1] == expected_disposition
            expected = f"lease readback mismatch at ${address:04X}: expected ${wanted:02X}, observed ${old:02X}"
            assert expected in result[2]
            assert b.call("disposition") == (expected_disposition, result[2])
            observed["reason"] = result[2]
            b.lua.globals().pywrite = b.write

        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        if publication == "query":
            refuse_success(lambda: b.call("answer_query", q.gen, 4, list(svc.TOKEN)), 7, q.gen)
            return
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        if publication == "offer":
            refuse_success(lambda: b.call("answer_offer", o.gen, True), 7, o.gen)
            return
        assert b.call("answer_offer", o.gen, True) is True
        yield
        if publication == "apply":
            refuse_success(b.apply, 6, (o.gen + 1) % 256)
            return
        gen = b.apply()
        assert isinstance(gen, int)
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "NOT_PERFORMED"
        refuse_success(lambda: b.call("release", gen), 5, 8)

    run = rig.run(host)
    svc.common(rig, run, events)
    if publication != "query":
        assert svc.snapshot_matches(rig, run)
    b, reason = observed["binder"], observed["reason"]
    assert b.call("closed") is True
    if publication == "apply":
        assert b.call("poll_done") is None
        assert b.call("disposition") == ("NOT_PERFORMED", reason) and len(b.logs) == 1
        assert b.call("reset") is True
        return
    assert b.call("poll_done").disposition == "UNCERTAIN"
    assert b.call("reset")[1:] == ("UNCERTAIN", reason)
    before = list(b.writes)
    assert b.apply()[1:] == ("UNCERTAIN", reason)
    assert b.writes == before


def test_query_ack_readback_also_verifies_previously_written_payload(env):
    b = Binder(env)
    b.frame_image("QUERY")
    lease = PROFILE["overlay"]["trade"]["lease"]
    base, fields = lease["base"], lease["fields"]

    def corrupt(a, value):
        b.write(a, value)
        if a == base + fields["ack"]:
            b.put(base + fields["available"], 0)

    b.lua.globals().pywrite = corrupt
    result = b.call("answer_query", 42, 4, list(svc.TOKEN))
    assert result[0] is None and result[1] == "UNCERTAIN"
    assert (f"at ${base + fields['available']:04X}: expected $01, observed $00") in result[2]
    assert b.call("disposition") == ("UNCERTAIN", result[2])


@pytest.mark.parametrize("unexpected", [0, 2, 3, 4], ids=["zero", "two", "three", "bad-byte"])
def test_unexpected_done_cannot_be_erased_by_result_one_real_service(env, unexpected):
    rig = svc.Rig(env)
    observed = {}
    commands = PROFILE["overlay"]["trade"]["commands"]

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame, test_hooks=True)
        observed["binder"] = b
        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        assert b.call("answer_offer", o.gen, True) is True
        yield
        gen = b.apply()
        assert isinstance(gen, int)
        while not h.header(commands["DONE"]):
            yield
        assert h.rd(6) == h.rd(7) == gen
        h.wr(8, unexpected)  # Fault injection on a real, matching native DONE.
        done = b.call("poll_done")
        assert done.result == unexpected and done.disposition == "UNCERTAIN"
        reason = done.reason
        observed["reason"] = reason
        before = list(b.writes)
        h.wr(8, 1)
        assert b.call("poll_done").disposition == "UNCERTAIN"
        assert b.call("disposition") == ("UNCERTAIN", reason)
        assert b.call("release", gen)[1:] == ("UNCERTAIN", reason)
        assert b.call("reset")[1:] == ("UNCERTAIN", reason)
        addr = PROFILE["overlay"]["trade"]["staging"]["party"]["addr"]
        assert diagnostic_write(b, addr, [17])[1:] == ("UNCERTAIN", reason)
        assert b.writes == before
        # No RELEASE: let the actual service's bounded hold close its lease.

    run = rig.run(host)
    svc.common(rig, run, "QOADC")
    assert svc.snapshot_matches(rig, run)
    b, reason = observed["binder"], observed["reason"]
    assert b.call("closed") is True
    assert b.call("poll_done").disposition == "UNCERTAIN"
    assert b.call("release", (rig.gen0 + 3) % 256)[1:] == ("UNCERTAIN", reason)
    assert b.call("reset")[1:] == ("UNCERTAIN", reason)
    assert b.call("disposition") == ("UNCERTAIN", reason)


def test_foreign_bad_done_result_does_not_poison_current_visit(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    gen = b.apply()
    lease = PROFILE["overlay"]["trade"]["lease"]
    b.frame_image("DONE", gen=(gen + 1) % 256, ack=(gen + 1) % 256)
    b.put(lease["base"] + lease["fields"]["result"], 4)
    assert b.call("poll_done") is None
    assert b.call("disposition")[0] == "PENDING"
    b.frame_image("DONE", gen=gen, ack=gen)
    b.put(lease["base"] + lease["fields"]["result"], 1)
    assert b.call("poll_done").disposition == "NOT_PERFORMED"
    assert b.call("release", gen) is True
    b.put(lease["base"] + lease["fields"]["command"], 0)
    assert b.call("reset") is True


def test_silently_partial_diagnostic_write_poisons_visit(env):
    b = Binder(env, test_hooks=True)
    b.accepted()
    b.frame += 1
    addr = PROFILE["overlay"]["trade"]["staging"]["party"]["addr"]

    def drop_second(address, value):
        if address != addr + 1:
            b.write(address, value)

    b.lua.globals().pywrite = drop_second
    with pytest.raises(Exception, match="readback mismatch"):
        diagnostic_write(b, addr, [17, 18])
    assert b.read(addr) == 17 and b.read(addr + 1) != 18
    disposition, reason = b.call("disposition")
    assert disposition == "UNCERTAIN"
    before = list(b.writes)
    b.lua.globals().pywrite = b.write
    assert b.apply()[1:] == ("UNCERTAIN", reason)
    lease = PROFILE["overlay"]["trade"]["lease"]
    b.put(lease["base"] + lease["fields"]["command"], 0)
    assert b.call("reset")[1:] == ("UNCERTAIN", reason)
    assert b.writes == before


def test_proposer_phase_is_explicit_and_still_cannot_become_a_responder(env):
    b = Binder(env)
    b.accepted()
    assert b.call("phase") == ("proposer", "offer")
    before = list(b.writes)
    out = b.call("arm", PROFILE["overlay"]["trade"]["commands"]["PROMPT"], 2, list(svc.TOKEN), payload())
    assert out[0] is None and out[1] == "PENDING" and b.writes == before
    b.frame += 1
    gen = b.apply()
    assert b.call("phase") == ("proposer", "apply")
    b.frame_image("DONE", gen=gen, ack=gen)
    b.put(PROFILE["overlay"]["trade"]["lease"]["base"] + 8, 0)
    assert b.call("poll_done").disposition == "UNCERTAIN"


# ── g2p-cancel: host cancel/close of a pre-APPLY visit ─────────────────────────────────────
# The ROM's own documented host-side closes (patch/polished/src/trade_service.asm:20-21): the four visit-token
# bytes zeroed (SlinkTradeCheckToken, trade_frame.asm:50,69-71, refused at trade_service.asm:81,114,140,166 and
# trade_responder.asm:70,106,150 -> SlinkTradeExit / SlinkTradeResponderExit, never a DONE) plus, for an
# unanswered OFFER, the reject (result 1, ACK last: trade_service.asm:145-147). Command and generation are never
# written by a cancel.


def lease_offsets(b, start):
    return [a - LEASE_BASE for a, _ in b.writes[start:] if LEASE_BASE <= a < LEASE_BASE + 16]


def apply_writes(env):
    """The addresses a successful arm(APPLY) writes, in order (staging, then the 16-byte frame, then gen)."""
    p = Binder(env)
    p.accepted()
    p.frame += 1
    n = len(p.writes)
    assert p.apply() == 44
    return [a for a, _ in p.writes[n:]]


def test_cancel_refusals_write_nothing(env):
    b = Binder(env)
    out = b.call("cancel", "x")
    assert isinstance(out, tuple) and out[1:] == ("PENDING", "no visit to cancel")
    b.accepted()
    before = list(b.writes)
    for bad in ("", 7, None):
        out = b.call("cancel", bad)
        assert isinstance(out, tuple) and out[1:] == ("PENDING", "cancel reason required")
    assert b.writes == before and not b.logs
    b.frame += 1
    assert b.apply() == 44
    before = list(b.writes)
    out = b.call("cancel", "server withdrew")
    # Once an APPLY is armed the visit is the ROM's: that path stays UNCERTAIN-capable and is not changed.
    assert isinstance(out, tuple) and out[1:] == ("PENDING", "APPLY already armed: cancel refused")
    assert b.writes == before and not b.logs
    assert b.call("phase") == ("proposer", "apply") and b.call("disposition")[0] == "PENDING"


def test_cancel_after_offer_reject_is_already_terminal(env):
    b = Binder(env)
    b.frame_image("QUERY", gen=42, ack=41)
    assert b.call("answer_query", 42, 4, list(svc.TOKEN)) is True
    b.frame_image("OFFER", gen=43, ack=42)
    assert b.call("answer_offer", 43, False) is True
    before = list(b.writes)
    out = b.call("cancel", "late")
    assert isinstance(out, tuple) and out[1:] == ("NOT_PERFORMED", "visit already terminal: offer rejected")
    assert b.writes == before and not b.logs


@pytest.mark.parametrize("when", ["query", "offer-pending", "accepted"], ids=["query", "offer", "accepted"])
def test_cancel_writes_only_the_sanctioned_bytes_and_logs_once(env, when):
    b = Binder(env)
    b.frame_image("QUERY", gen=42, ack=41)
    assert b.call("answer_query", 42, 4, list(svc.TOKEN)) is True
    if when != "query":
        b.frame_image("OFFER", gen=43, ack=42)
    if when == "accepted":
        assert b.call("answer_offer", 43, True) is True
    start = len(b.writes)
    assert b.call("cancel", "menu left") is True
    pending = when == "offer-pending"
    assert lease_offsets(b, start) == ([8, 12, 13, 14, 15, 7] if pending else [12, 13, 14, 15])
    assert [v for _, v in b.writes[start:]] == ([1, 0, 0, 0, 0, 43] if pending else [0, 0, 0, 0])
    # command and generation are never touched: no PROMPT/APPLY/RELEASE can be forged out of a cancel
    assert b.read(LEASE_BASE + FIELDS["command"]) == (CMD["QUERY"] if when == "query" else CMD["OFFER"])
    assert b.read(LEASE_BASE + FIELDS["generation"]) == (42 if when == "query" else 43)
    assert b.call("disposition") == ("NOT_PERFORMED", "cancelled before APPLY: menu left")
    assert b.call("phase") == ("proposer", "cancelled")
    assert len(b.logs) == 1 and "menu left" in b.logs[0] and "cancelled before APPLY" in b.logs[0]
    after = list(b.writes)
    assert b.call("cancel", "again") is True  # idempotent: no second write, no second log
    assert b.writes == after and len(b.logs) == 1
    b.frame += 1
    assert b.call("poll_query") is None and b.call("poll_offer") is None and b.call("poll_done") is None
    for out in (b.call("answer_query", 42, 4, list(svc.TOKEN)), b.call("answer_offer", 43, True),
                b.apply(), b.call("release", 44)):
        assert isinstance(out, tuple) and out[1:] == ("NOT_PERFORMED", "cancelled before APPLY: menu left")
    assert b.writes == after
    # a DONE the ROM may still publish is not claimed by a cancelled visit
    b.frame_image("DONE", gen=44, ack=44)
    b.put(LEASE_BASE + FIELDS["result"], 1)
    assert b.call("poll_done") is None and b.call("disposition")[0] == "NOT_PERFORMED"
    # reusable only after the ROM closes
    assert b.call("reset")[1] == "PENDING"
    b.put(LEASE_BASE + FIELDS["command"], 0)
    assert b.call("reset") is True and b.call("phase") == (None, None)
    b.accepted()
    b.frame += 1
    assert b.apply() == 44


def test_cancel_in_responder_phases_before_apply(env):
    for phase in ("prompt", "consented", "released"):
        b = Binder(env)
        gen = b.call("arm", CMD["PROMPT"], 2, list(svc.TOKEN), payload())
        assert isinstance(gen, int)
        if phase != "prompt":
            b.frame_image("DONE", gen=gen, ack=gen)
            b.put(LEASE_BASE + FIELDS["result"], 0)
            assert b.call("poll_done").disposition == "CONSENTED"
        if phase == "released":
            assert b.call("release", gen) is True
            b.frame += 1
        start = len(b.writes)
        assert b.call("cancel", "disconnected") is True
        assert lease_offsets(b, start) == [12, 13, 14, 15]
        assert b.call("phase") == ("responder", "cancelled")
        assert b.call("disposition") == ("NOT_PERFORMED", "cancelled before APPLY: disconnected")
        before = list(b.writes)
        out = b.apply()
        assert isinstance(out, tuple) and out[1] == "NOT_PERFORMED" and b.writes == before
        assert len(b.logs) == 1
    # a declined PROMPT is already terminal: release() is its path, cancel writes nothing
    b = Binder(env)
    gen = b.call("arm", CMD["PROMPT"], 2, list(svc.TOKEN), payload())
    b.frame_image("DONE", gen=gen, ack=gen)
    b.put(LEASE_BASE + FIELDS["result"], 1)
    assert b.call("poll_done").disposition == "DECLINED"
    before = list(b.writes)
    out = b.call("cancel", "x")
    assert isinstance(out, tuple) and out[1] == "DECLINED" and "already terminal" in out[2]
    assert b.writes == before and not b.logs


def test_cancel_poisoned_binder_stays_uncertain(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    # Fresh generation landed BEFORE the write sink threw: a commit can have started.
    def published_then_throw(address, value):
        b.write(address, value)
        if address == LEASE_BASE + FIELDS["generation"] and value == 44:
            raise RuntimeError("injected published generation failure")
    b.lua.globals().pywrite = published_then_throw
    out = b.apply()
    assert isinstance(out, tuple) and out[1] == "UNCERTAIN"
    assert b.read(LEASE_BASE + FIELDS["command"]) == CMD["APPLY"]
    before = list(b.writes)
    b.fail_at = None
    cancel = b.call("cancel", "x")
    assert isinstance(cancel, tuple) and cancel[1:] == ("UNCERTAIN", out[2])
    assert b.writes == before and not b.logs


def test_cancel_dropped_token_write_is_not_performed(env):
    b = Binder(env)
    b.accepted()
    at = LEASE_BASE + FIELDS["token"]
    b.lua.globals().pywrite = lambda a, v: None if a == at else b.write(a, v)
    out = b.call("cancel", "x")
    assert isinstance(out, tuple) and out[1] == "NOT_PERFORMED"
    assert f"lease readback mismatch at ${at:04X}: expected $00, observed ${svc.TOKEN[0]:02X}" in out[2]
    assert b.call("disposition") == ("NOT_PERFORMED", out[2]) and len(b.logs) == 1
    assert "watchdog" in b.logs[0] and b.call("phase") == ("proposer", "cancelled")
    assert b.call("reset")[1] == "PENDING"


def test_responder_apply_fault_before_publication_is_not_performed(env):
    b = Binder(env)
    gen = b.call("arm", CMD["PROMPT"], 2, list(svc.TOKEN), payload())
    b.frame_image("DONE", gen=gen, ack=gen)
    b.put(LEASE_BASE + FIELDS["result"], 0)
    assert b.call("poll_done").disposition == "CONSENTED"
    assert b.call("release", gen) is True
    b.frame += 1
    b.fail_at = len(b.writes) + 2
    out = b.apply()
    assert isinstance(out, tuple) and out[1] == "NOT_PERFORMED" and "APPLY not published" in out[2]
    assert b.read(LEASE_BASE + FIELDS["command"]) == CMD["RELEASE"]
    assert b.read(LEASE_BASE + FIELDS["generation"]) == gen == b.read(LEASE_BASE + FIELDS["ack"])
    assert [b.read(LEASE_BASE + FIELDS["token"] + i) for i in range(4)] == [0, 0, 0, 0]
    assert len(b.logs) == 1


# ---- the real proposer service --------------------------------------------------------------------------

class SeededRig(svc.Rig):
    """The proposer rig whose lease starts from a given 16-byte image (a previous visit's close)."""

    def __init__(self, env, seed=None, **kwargs):
        super().__init__(env, **kwargs)
        self.seed = seed

    def build_ram(self, m):
        super().build_ram(m)
        if self.seed is not None:
            m.poke(self.lease, bytes(self.seed))


def cancelled_run(env, when, *, binder=None, seed=None):
    """QUERY answered, then the host cancels at `when` ("armed" = full visit, cancel refused after arm)."""
    rig = SeededRig(env, seed=seed)
    result = {}

    def host(h):
        b = binder or Binder(env, machine=h.m, clock=lambda: rig.frame)
        if binder is not None:
            b.machine, b.clock = h.m, lambda: rig.frame
        result["binder"] = b
        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        if when == "query":
            assert b.call("cancel", "disconnected") is True  # the same frame as the answer
            result["cancel_frame"] = rig.frame
            return
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        if when == "offer-pending":
            start = len(b.writes)
            assert b.call("cancel", "server declined") is True
            assert lease_offsets(b, start) == [8, 12, 13, 14, 15, 7]
            result["cancel_frame"] = rig.frame
            return
        assert b.call("answer_offer", o.gen, True) is True
        yield
        if when == "accepted":
            assert b.call("cancel", "withdrawal queued") is True
            result["cancel_frame"] = rig.frame
            return
        gen = b.apply()
        assert isinstance(gen, int)
        result["gen"] = gen
        before = list(b.writes)
        out = b.call("cancel", "too late")
        assert isinstance(out, tuple) and out[1:] == ("PENDING", "APPLY already armed: cancel refused")
        assert b.writes == before
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "NOT_PERFORMED"
        assert b.call("release", gen) is True

    run = rig.run(host)
    return rig, run, result


@pytest.mark.parametrize("when", ["query", "offer-pending", "accepted"], ids=["query", "offer", "accepted"])
def test_real_proposer_service_closes_on_cancel_without_done(env, when):
    rig, run, result = cancelled_run(env, when)
    svc.common(rig, run, "QC" if when == "query" else "QOC", forbid_calls=("menu",) if when == "query" else ())
    assert run.frames == result["cancel_frame"]  # the ROM exits on the very frame it next inspects the lease
    b = result["binder"]
    assert b.call("closed") is True and b.call("disposition")[0] == "NOT_PERFORMED"
    assert len(b.logs) == 1
    if when != "query":
        assert svc.snapshot_matches(rig, run)
    assert tuple(run.m.peek(rig.lease + 12, 4)) == (0, 0, 0, 0)


def test_real_proposer_binder_is_reusable_after_a_cancelled_visit(env):
    rig, run, result = cancelled_run(env, "accepted")
    svc.common(rig, run, "QOC")
    b = result["binder"]
    assert b.call("closed") is True and b.call("reset") is True and b.call("phase") == (None, None)
    seed = list(run.m.peek(rig.lease, 16))
    rig2, run2, result2 = cancelled_run(env, "armed", binder=b, seed=seed)
    svc.common(rig2, run2, "QOADC")
    assert svc.snapshot_matches(rig2, run2)
    assert result2["gen"] == (seed[6] + 3) % 256 and len(b.logs) == 1
    assert b.call("closed") is True and b.call("disposition")[0] == "NOT_PERFORMED" and b.call("reset") is True


def test_real_armed_apply_cannot_be_cancelled(env):
    rig, run, result = cancelled_run(env, "armed")
    svc.common(rig, run, "QOADC")
    assert svc.snapshot_matches(rig, run)


def arm_fault_run(env, half):
    """Fresh generation is publication; command/payload bytes alone cannot permit native pickup."""
    rig = svc.Rig(env)
    result = {}
    addrs = apply_writes(env)
    cmd_at = addrs.index(LEASE_BASE + FIELDS["command"])

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame)
        result["binder"] = b
        while not b.call("poll_query"):
            yield
        q = b.call("poll_query")
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not b.call("poll_offer"):
            yield
        o = b.call("poll_offer")
        assert b.call("answer_offer", o.gen, True) is True
        result["offer_frame"] = rig.frame
        yield
        if half == "published":
            def generation_then_throw(address, value):
                b.write(address, value)
                if address == LEASE_BASE + FIELDS["generation"] and value == (o.gen + 1) % 256:
                    raise RuntimeError("injected fault AFTER fresh generation")
            b.lua.globals().pywrite = generation_then_throw
        else:
            b.fail_at = len(b.writes) + (2 if half == "before" else len(addrs) if half == "payload" else cmd_at + 2)
        if half == "unreadable":
            failed = [False]
            def write_then_unavailable(address, value):
                try:
                    b.write(address, value)
                except RuntimeError:
                    failed[0] = True
                    raise
            def unavailable(address):
                if failed[0] and address == LEASE_BASE + FIELDS["generation"]:
                    raise RuntimeError("injected unavailable generation readback")
                return b.read(address)
            b.lua.globals().pywrite, b.lua.globals().pyread = write_then_unavailable, unavailable
        out = b.apply()
        b.fail_at = None
        b.lua.globals().pywrite, b.lua.globals().pyread = b.write, b.read
        assert isinstance(out, tuple), out
        if half in ("before", "after", "payload"):
            assert out[1] == "NOT_PERFORMED", "unpublished APPLY became UNCERTAIN"
            assert "APPLY not published" in out[2] and "injected write failure" in out[2]
            assert h.rd(5) == (svc.OFFER if half == "before" else svc.APPLY)
            assert h.rd(6) == o.gen == h.rd(7)
            if half == "payload":
                assert h.rd(8) == 0xFF  # full unpublished frame; result is no longer the held OFFER's 0
            assert tuple(h.rd(12 + i) for i in range(4)) == (0, 0, 0, 0)
            assert b.call("disposition")[0] == "NOT_PERFORMED" and len(b.logs) == 1
            result["cancel_frame"] = rig.frame
            return
        assert out[1] == "UNCERTAIN", out
        assert h.rd(5) == svc.APPLY
        assert h.rd(6) == ((o.gen + 1) % 256 if half == "published" else o.gen)
        before = list(b.writes)
        assert b.call("cancel", "x")[1] == "UNCERTAIN" and b.call("reset")[1] == "UNCERTAIN"
        assert b.writes == before and not b.logs
        yield from h.frames(10 ** 9)

    run = rig.run(host)
    svc.common(rig, run, "QOADC" if half == "published" else "QOC")
    assert svc.snapshot_matches(rig, run)
    b = result["binder"]
    if half in ("before", "after", "payload"):
        assert run.frames == result["cancel_frame"]
        assert b.call("closed") is True and b.call("reset") is True
        b.clock, b.frame = None, run.frames + 1
        b.accepted()
        b.frame += 1
        assert b.apply() == 44
    else:
        if half == "unreadable":
            # No proof is available to the binder; real gen==ACK prevents pickup until native timeout.
            assert run.frames == result["offer_frame"] + 3600
        assert b.call("closed") is True and b.call("disposition")[0] == "UNCERTAIN"
        assert b.call("reset")[1] == "UNCERTAIN" and not b.logs


@pytest.mark.parametrize("half", ["before", "after", "payload", "published", "unreadable"],
                         ids=["staging", "command", "payload", "fresh-generation", "unreadable"])
def test_real_arm_fault_halves(env, half):
    arm_fault_run(env, half)


# ---- the real responder service -------------------------------------------------------------------------

class ResponderHostRig(resp.Rig):
    def build_ram(self, m):
        host = super().build_ram(m)
        m.poke(self.lease, bytes([0] * 16))
        m.poke(self.lease + 6, self.gen0)
        m.poke(self.lease + 7, self.gen0)
        self.binder = Binder(self.env, machine=m, clock=lambda: self.frame)
        self.prompt_gen = self.binder.call("arm", CMD["PROMPT"], self.own, list(svc.TOKEN), payload())
        assert isinstance(self.prompt_gen, int), self.prompt_gen
        return host


@pytest.mark.parametrize("when", ["prompt-yes", "prompt-no", "consented", "released"],
                         ids=["prompt-yes", "prompt-no", "consented", "released"])
def test_real_responder_service_closes_on_cancel_before_apply(env, when):
    rig = ResponderHostRig(env)

    def host(h):
        b = rig.binder
        if when.startswith("prompt"):
            yield from h.frames(10 ** 9)  # the cancel fires inside the YesNoBox (on_native)
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "CONSENTED"
        if when == "released":
            assert b.call("release", rig.prompt_gen) is True
            yield
        assert b.call("cancel", "disconnected") is True
        rig.mark("cancel")
        yield from h.frames(10 ** 9)

    def on_native(h, what):
        if what == "yesno" and "cancel" not in rig.marks:
            assert rig.binder.call("cancel", "menu left") is True
            rig.mark("cancel")

    if when.startswith("prompt"):
        rig.on_native = on_native
    run = rig.run(host, yesno=(when != "prompt-no"))
    b = rig.binder
    if when == "prompt-yes":
        # YES after the cancel: CheckHeldFrame refuses the zero token (trade_responder.asm:106): no snapshot,
        # no consent DONE, the text box closed, exit before any wait frame.
        resp.common(rig, run, "AC", results=[], frames=0)
        assert run.snap_first is None
    elif when == "prompt-no":
        # NO after the cancel: the decline DONE is still published, then the 90-frame hold closes it.
        resp.common(rig, run, "ADC", results=[1], frames=90)
    else:
        resp.common(rig, run, "ADC", results=[0])
        assert run.frames == rig.marks["cancel"]
    assert b.call("closed") is True and b.call("poll_done") is None
    assert b.call("disposition") == ("NOT_PERFORMED", "cancelled before APPLY: " +
                                     ("menu left" if when.startswith("prompt") else "disconnected"))
    assert len(b.logs) == 1
    assert b.call("reset") is True and b.call("phase") == (None, None)
    # reusable on the ROM's closed lease: a fresh PROMPT arms
    again = b.call("arm", CMD["PROMPT"], rig.own, list(svc.TOKEN), payload())
    assert isinstance(again, int)


# ---- red controls ----------------------------------------------------------------------------------------

CANCEL_MUTANTS = [
    ("cancel-after-arm",
     "if attempted then return nil,'PENDING','APPLY already armed: cancel refused' end",
     "if false then end", test_cancel_refusals_write_nothing),
    ("cancel-after-arm-real",
     "if attempted then return nil,'PENDING','APPLY already armed: cancel refused' end",
     "if false then end", test_real_armed_apply_cannot_be_cancelled),
    ("cancel-readback",
     "verify_lease(expected) -- all written fields, not just the publication byte",
     "-- readback skipped", test_cancel_dropped_token_write_is_not_performed),
    ("cancel-order",
     "writes:write_bytes(l.base+l.fields.token,{0,0,0,0}) -- cancel: token drift",
     "if pending then writes:write_bytes(l.base+l.fields.ack,{pending.gen}) end "
     "writes:write_bytes(l.base+l.fields.token,{0,0,0,0})",
     lambda e: test_cancel_writes_only_the_sanctioned_bytes_and_logs_once(e, "offer-pending")),
    ("arm-fault-mapped-to-uncertain",
     "and apply_unpublished(slot) then", "and false then", lambda e: arm_fault_run(e, "before")),
]


@pytest.mark.parametrize("name,before,after,check", CANCEL_MUTANTS, ids=[m[0] for m in CANCEL_MUTANTS])
def test_each_cancel_mutant_is_caught(env, monkeypatch, name, before, after, check):
    source = PATH.read_text(encoding="utf-8")
    assert source.count(before) == 1
    check(env)
    original = Binder

    def mutated(*args, **kwargs):
        kwargs["mutation"] = (before, after)
        return original(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "Binder", mutated)
    with pytest.raises(AssertionError):
        check(env)


# ---- binder2: pre-publication close faults remain NOT_PERFORMED -------------------------------------------

def close_fault_run(env, fault, *, mutation=None):
    """Real accepted-OFFER ROM visit; fault only the binder's I/O or optional diagnostic sink."""
    rig = svc.Rig(env)
    seen = {"log_attempts": 0, "log_phases": []}

    def host(h):
        b = Binder(env, machine=h.m, clock=lambda: rig.frame, mutation=mutation)
        seen["binder"] = b
        while not (q := b.call("poll_query")):
            yield
        assert b.call("answer_query", q.gen, 4, list(svc.TOKEN)) is True
        while not (o := b.call("poll_offer")):
            yield
        assert b.call("answer_offer", o.gen, True) is True
        seen["offer_frame"] = rig.frame
        yield
        if fault.startswith("token"):
            if fault == "token":
                b.fail_at = len(b.writes) + 2  # first token byte lands; second throws before its store
            else:
                def lose_all_tokens(address, value):
                    if not LEASE_BASE + FIELDS["token"] <= address < LEASE_BASE + FIELDS["token"] + 4:
                        b.write(address, value)
                b.lua.globals().pywrite = lose_all_tokens
        else:
            def throwing_log(_message):
                seen["log_attempts"] += 1
                seen["log_phases"].append(b.call("phase"))
                raise RuntimeError("injected optional log failure")
            b.lua.globals().pylog = throwing_log
        out = b.call("cancel", "disconnected")
        if fault.startswith("token"):
            assert isinstance(out, tuple) and out[1] == "NOT_PERFORMED", "pre-APPLY close fault became UNCERTAIN"
            assert ("injected write failure" if fault == "token" else "lease readback mismatch") in out[2]
            assert "watchdog" in out[2]
            assert b.call("disposition") == ("NOT_PERFORMED", out[2])
            assert tuple(h.rd(12 + i) for i in range(4)) == ((0, *svc.TOKEN[1:]) if fault == "token" else svc.TOKEN)
            assert len(b.logs) == 1 and "watchdog" in b.logs[0]
        else:
            assert out is True
            assert seen["log_attempts"] == 1
            assert seen["log_phases"] == [("proposer", "cancelled")], "optional logger observed nonterminal phase"
        assert b.call("phase") == ("proposer", "cancelled")
        assert b.call("reset")[1:] == ("PENDING", "lease must close before reset")
        seen["cancel_frame"] = rig.frame
        before = list(b.writes)
        b.fail_at = None
        b.lua.globals().pywrite = b.write
        assert b.call("cancel", "retry") is True
        assert b.writes == before
        assert (len(b.logs) == 1) if fault.startswith("token") else (seen["log_attempts"] == 1)
        assert b.apply()[1] == "NOT_PERFORMED" and b.writes == before

    run = rig.run(host)
    svc.common(rig, run, "QOC")  # no APPLY pickup or DONE publication
    assert svc.snapshot_matches(rig, run)
    assert run.frames == (seen["offer_frame"] + 3600 if fault == "token-all" else seen["cancel_frame"])
    b = seen["binder"]
    assert b.call("closed") is True and b.call("poll_done") is None
    assert b.call("disposition")[0] == "NOT_PERFORMED"
    assert b.call("reset") is True
    return seen


def test_real_cancel_token_fault_is_not_performed_logged_once_and_closes(env):
    close_fault_run(env, "token")


def test_real_cancel_all_token_stores_lost_waits_for_watchdog_without_retry(env):
    close_fault_run(env, "token-all")


def test_real_cancel_throwing_logger_is_contained_and_phase_is_consistent(env):
    close_fault_run(env, "log")


@pytest.mark.parametrize("where", ["command", "payload", "close-fault"],
                         ids=["command", "payload", "failed-close"])
def test_real_responder_unpublished_apply_remains_not_performed(env, where):
    rig = ResponderHostRig(env)
    observed = {}
    addrs = apply_writes(env)
    fail_index = addrs.index(LEASE_BASE + FIELDS["command"]) + 2 if where == "command" else len(addrs)

    def host(h):
        b = rig.binder
        observed["binder"] = b
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "CONSENTED"
        assert b.call("release", rig.prompt_gen) is True
        yield
        b.fail_at = len(b.writes) + fail_index
        original = b.write
        def closing_fault(address, value):
            if where == "close-fault" and address == LEASE_BASE + FIELDS["token"] + 1 and value == 0:
                raise RuntimeError("injected second close-token failure")
            original(address, value)
        b.lua.globals().pywrite = closing_fault
        out = b.apply()
        assert out[1] == "NOT_PERFORMED" and "APPLY not published" in out[2]
        assert h.rd(5) == CMD["APPLY"] and h.rd(6) == rig.prompt_gen == h.rd(7)
        assert b.call("disposition") == ("NOT_PERFORMED", out[2])
        assert b.call("phase") == ("responder", "cancelled") and len(b.logs) == 1
        if where == "close-fault":
            assert "second close-token failure" in out[2] and "watchdog" in out[2]
        assert b.call("reset")[1] == "PENDING"
        b.fail_at = None
        b.lua.globals().pywrite = b.write

    run = rig.run(host)
    resp.common(rig, run, "ADC", results=[0])  # consent only; no APPLY pickup/final DONE
    b = observed["binder"]
    assert b.call("closed") is True and b.call("poll_done") is None
    assert b.call("reset") is True


BINDER2_MUTANTS = [
    ("close-fault-is-poison", "            local detail=why\n            if not yes then",
     "            if not yes then return yes,a,b end\n            local detail=why\n            if not yes then",
     lambda e: close_fault_run(e, "token"), "pre-APPLY close fault became UNCERTAIN"),
    ("command-is-publication", "            return bytes[f.version+1] == l.version\n",
     "            return bytes[f.version+1] == l.version and bytes[f.command+1] ~= t.commands.APPLY\n",
     lambda e: arm_fault_run(e, "after"), "unpublished APPLY became UNCERTAIN"),
    ("phase-after-log",
     "            phase='cancelled' -- terminal state is consistent even inside a throwing optional log sink\n"
     "            pcall(log,string.format('[SLink-polished] trade visit cancelled before APPLY (%s/%s): %s',\n"
     "                                    tostring(role),tostring(previous_phase),detail))\n",
     "            pcall(log,string.format('[SLink-polished] trade visit cancelled before APPLY (%s/%s): %s',\n"
     "                                    tostring(role),tostring(previous_phase),detail))\n"
     "            phase='cancelled' -- mutant: logger observed the old phase\n",
     lambda e: close_fault_run(e, "log"), "optional logger observed nonterminal phase"),
]


@pytest.mark.parametrize("name,before,after,check,message", BINDER2_MUTANTS, ids=[m[0] for m in BINDER2_MUTANTS])
def test_binder2_each_undo_mutant_fails_the_real_service_oracle(env, monkeypatch, name, before, after, check, message):
    assert PATH.read_text(encoding="utf-8").count(before) == 1
    check(env)
    original = Binder
    def mutated(*args, **kwargs):
        kwargs["mutation"] = (before, after)
        return original(*args, **kwargs)
    monkeypatch.setattr(sys.modules[__name__], "Binder", mutated)
    with pytest.raises(AssertionError, match=message):
        check(env)
