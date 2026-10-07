"""C3 real Lua binder + shared permit/lease against the assembled proposer service.

Native UI/frame routines use the existing service rig traps; no emulator/live
qualification. Validation facts now come from the generated profile and the
built ROM table; C4 owns ROM reader admission. Explicit fact overrides remain.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from lupa.lua55 import LuaRuntime

from tests.unit import test_polished_trade_service as svc

env = svc.env

ROOT = svc.REPO
PATH = ROOT / "lua/gen2/polished_trade.lua"
PROFILE = json.loads((ROOT / "data/games/polished_crystal/profile.json").read_bytes())["titles"][
    "polished"
]


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
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        g = self.lua.globals()
        g.pyread, g.pywrite = self.read, self.write
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


def test_partial_write_latches_uncertain(env):
    b = Binder(env)
    b.accepted()
    b.frame += 1
    b.fail_at = len(b.writes) + 5
    result = b.apply()
    assert result[1] == "UNCERTAIN"
    before = list(b.writes)
    b.fail_at = None
    assert b.apply()[1] == "UNCERTAIN" and b.writes == before
    assert b.call("disposition")[0] == "UNCERTAIN"


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
    assert result[1] == "UNCERTAIN" and "readback mismatch" in result[2]
    lease = PROFILE["overlay"]["trade"]["lease"]
    assert (
        b.read(lease["base"] + lease["fields"]["command"])
        == PROFILE["overlay"]["trade"]["commands"]["OFFER"]
    )


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
    ids=[
        "dispatch",
        "entry",
        "prompt",
        "service",
        "service-end",
        "timeout",
        "wait",
        "stage-nick",
        "stage-ot",
        "stage-party",
        "stage-sender",
        "snap-nick",
        "snap-ot",
        "snap-party",
    ],
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
def test_silently_dropped_lease_publication_is_uncertain_real_service(env, publication, events):
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
            assert result[0] is None and result[1] == "UNCERTAIN"
            expected = f"lease readback mismatch at ${address:04X}: expected ${wanted:02X}, observed ${old:02X}"
            assert expected in result[2]
            assert b.call("disposition") == ("UNCERTAIN", result[2])
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
