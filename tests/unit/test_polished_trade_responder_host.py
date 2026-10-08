"""H1: real Lua binder and built commit-disabled responder; native UI remains MODEL traps."""
from __future__ import annotations

import copy
import sys

import pytest

from tests.unit import test_polished_trade_responder as resp
from tests.unit.test_polished_trade_binder import PATH, PROFILE, Binder, payload

env = resp.env
TRADE = PROFILE["overlay"]["trade"]
CMD = TRADE["commands"]
LEASE = TRADE["lease"]["base"]
TOKEN = list(resp.TOKEN)


def prompt(b, slot=2, token=None, data=None):
    return b.call("arm", CMD["PROMPT"], slot, TOKEN if token is None else token,
                  payload() if data is None else data)


class HostRig(resp.Rig):
    def __init__(self, env, *, mutation=None, **kwargs):
        super().__init__(env, **kwargs)
        self.mutation = mutation

    def build_ram(self, machine):
        host = super().build_ram(machine)
        # Parent supplies the native party/staging fixture. Only this real binder publishes the request.
        machine.poke(self.lease, bytes([0] * 16))
        machine.poke(self.lease + 6, self.gen0)
        machine.poke(self.lease + 7, self.gen0)
        self.binder = Binder(self.env, machine=machine, clock=lambda: self.frame, mutation=self.mutation)
        self.prompt_gen = prompt(self.binder, slot=self.own)
        assert isinstance(self.prompt_gen, int), self.prompt_gen
        return host


def real_visit(env, *, yes=True, gen0=0x10, mutation=None):
    rig = HostRig(env, gen0=gen0, mutation=mutation)
    seen = []

    def host(h):
        b = rig.binder
        while not (done := b.call("poll_done")):
            yield
        seen.append(done.disposition)
        assert done.disposition == ("CONSENTED" if yes else "DECLINED")
        assert b.call("release", rig.prompt_gen) is True
        if not yes:
            return
        before = list(b.writes)
        rig.immediate = b.apply()
        if isinstance(rig.immediate, tuple):
            assert rig.immediate[1:] == ("PENDING", "RELEASE frame gap required")
            assert b.writes == before
            yield  # ROM observes RELEASE before the host publishes fresh APPLY.
            gen = b.apply()
        else:
            gen = rig.immediate  # mutant: the ROM must reject this unobserved RELEASE.
        assert gen == (rig.prompt_gen + 1) % 256
        while not (done := b.call("poll_done")):
            yield
        seen.append(done.disposition)
        assert done.result == 1 and done.disposition == "NOT_PERFORMED"
        assert b.call("release", gen) is True

    run = rig.run(host, yesno=yes)
    resp.common(rig, run, "ADADC" if yes else "ADC", results=[0, 1] if yes else [1])
    assert rig.binder.call("advertised") is False
    assert rig.binder.call("closed") is True
    assert rig.binder.call("disposition")[0] == ("NOT_PERFORMED" if yes else "DECLINED")
    assert rig.binder.call("reset") is True
    return rig, run, seen


@pytest.mark.parametrize("yes,gen0", [(True, 0x10), (True, 0xFE), (True, 0xFF), (False, 0x10)],
                         ids=["consent", "apply-wrap", "prompt-wrap", "decline"])
def test_real_responder_host_handshake(env, yes, gen0):
    rig, run, seen = real_visit(env, yes=yes, gen0=gen0)
    assert seen == (["CONSENTED", "NOT_PERFORMED"] if yes else ["DECLINED"])
    # Arm uses the unchanged shared helper: full frame (old gen/ACK) then generation LAST.
    pubs = [(a, v) for a, v in rig.binder.writes if LEASE <= a < LEASE + 16]
    assert [a - LEASE for a, _ in pubs[:17]] == [*range(16), 6]
    assert pubs[6][1] == pubs[7][1] == gen0 and pubs[16][1] == (gen0 + 1) % 256
    spans = TRADE["staging"]
    allowed = [(LEASE, 16), *[(s["addr"], s["size"]) for s in spans.values()]]
    assert all(any(lo <= a < lo + size for lo, size in allowed) for a, _ in rig.binder.writes)


def done_frame(b, gen, result=0):
    b.frame_image("DONE", gen=gen, ack=gen)
    b.put(LEASE + 8, result)


def consent_released(b):
    gen = prompt(b)
    assert isinstance(gen, int), gen
    done_frame(b, gen)
    assert b.call("poll_done").disposition == "CONSENTED"
    assert b.call("release", gen) is True
    b.frame += 1
    return gen


@pytest.mark.parametrize("result,expected", [(0, "CONSENTED"), (1, "DECLINED"), (2, "UNCERTAIN"),
                                            (3, "UNCERTAIN"), (4, "UNCERTAIN"), (255, "UNCERTAIN")],
                         ids=["consent", "decline", "two", "three", "four", "ff"])
def test_prompt_dispositions_and_poison_are_phase_bound(env, result, expected):
    b = Binder(env)
    gen = prompt(b)
    assert b.call("phase") == ("responder", "prompt")
    done_frame(b, gen, result)
    assert b.call("poll_done").disposition == expected
    assert b.call("disposition")[0] == expected
    before = list(b.writes)
    if expected == "UNCERTAIN":
        done_frame(b, gen, 1)
        assert b.call("poll_done").disposition == "UNCERTAIN"
        assert b.call("release", gen)[1] == "UNCERTAIN"
        b.put(LEASE + 5, 0)
        assert b.call("reset")[1] == "UNCERTAIN" and b.writes == before
    else:
        assert b.call("reset")[1] == "PENDING"
        assert b.call("release", gen) is True
        assert b.call("phase") == ("responder", "released")
        assert b.call("reset")[1] == "PENDING"


@pytest.mark.parametrize("field", ["magic", "version", "command", "generation", "ack", "slot", "token"],
                         ids=["magic", "version", "cmd", "gen", "ack", "slot", "token"])
def test_foreign_prompt_done_never_releases_or_changes_disposition(env, field):
    b = Binder(env)
    gen = prompt(b)
    done_frame(b, gen)
    at = LEASE + TRADE["lease"]["fields"][field]
    b.put(at, (b.read(at) + 1) % 256)
    before = list(b.writes)
    assert b.call("poll_done") is None and b.call("disposition")[0] == "PENDING"
    assert b.call("release", gen)[0] is None and b.writes == before
    done_frame(b, gen)
    assert b.call("poll_done").disposition == "CONSENTED"
    assert b.call("release", (gen + 1) % 256)[0] is None and b.writes == before
    assert b.call("release", gen) is True


@pytest.mark.parametrize("field", ["magic", "version", "command", "generation", "ack", "slot", "token", "result"],
                         ids=["magic", "version", "cmd", "gen", "ack", "slot", "token", "result"])
def test_apply_requires_unchanged_consent_release_lease(env, field):
    b = Binder(env)
    consent_released(b)
    at = LEASE + TRADE["lease"]["fields"][field]
    b.put(at, (b.read(at) + 1) % 256)
    before = list(b.writes)
    out = b.apply()
    assert isinstance(out, tuple) and out[1] == "PENDING" and b.writes == before


@pytest.mark.parametrize("kind", ["no-consent", "no-release", "declined", "wrong-token", "wrong-slot", "repeat"],
                         ids=["pending", "unreleased", "declined", "token", "slot", "repeat"])
def test_responder_apply_phase_refusals_never_stage(env, kind):
    b = Binder(env)
    gen = prompt(b)
    if kind != "no-consent":
        done_frame(b, gen, 1 if kind == "declined" else 0)
        b.call("poll_done")
        if kind != "no-release":
            assert b.call("release", gen) is True
    b.frame += 1
    if kind == "repeat":
        assert isinstance(b.apply(), int)
    before = list(b.writes)
    reply = b.apply(token=[1, 2, 3, 4]) if kind == "wrong-token" else b.apply(slot=1) if kind == "wrong-slot" else b.apply()
    assert isinstance(reply, tuple) and reply[1] == "PENDING" and b.writes == before


def test_roles_cannot_interleave_and_reset_requires_closure(env):
    b = Binder(env)
    gen = prompt(b)
    before = list(b.writes)
    b.frame_image("QUERY")
    assert b.call("poll_query") is None
    answer = b.call("answer_query", 42, 4, TOKEN)
    assert isinstance(answer, tuple) and answer[1] == "PENDING"
    assert b.call("answer_offer", 42, True)[1] == "PENDING"
    assert b.call("poll_offer") is None and b.writes == before
    b.put(LEASE + 5, 0)
    repeated = prompt(b)
    assert isinstance(repeated, tuple) and repeated[1] == "PENDING" and b.writes == before
    assert b.call("reset") is True
    assert b.call("phase") == (None, None)
    b.accepted()
    assert b.call("phase") == ("proposer", "offer")
    before = list(b.writes)
    assert prompt(b)[1] == "PENDING" and b.writes == before
    assert isinstance(gen, int)


@pytest.mark.parametrize("result", [0, 1, 2, 3, 255], ids=["zero", "one", "two", "three", "ff"])
def test_responder_apply_cannot_be_reclassified_as_prompt_consent(env, result):
    b = Binder(env)
    consent_released(b)
    gen = b.apply()
    assert b.call("phase") == ("responder", "apply")
    done_frame(b, gen, result)
    assert b.call("poll_done").disposition == ("NOT_PERFORMED" if result == 1 else "UNCERTAIN")
    if result != 1:
        done_frame(b, gen, 1)
        assert b.call("poll_done").disposition == "UNCERTAIN"
        assert b.call("release", gen)[1] == "UNCERTAIN"


@pytest.mark.parametrize("case", ["b-consent", "b-apply", "timeout-consent", "timeout-apply", "b-after-arm"],
                         ids=["b-consent", "b-apply", "timeout-consent", "timeout-apply", "b-armed"])
def test_real_responder_closure_and_timeout_dispositions(env, case):
    rig = HostRig(env)

    def host(h):
        b = rig.binder
        while not b.call("poll_done"):
            yield
        assert b.call("poll_done").disposition == "CONSENTED"
        if case in ("b-apply", "timeout-apply", "b-after-arm"):
            assert b.call("release", rig.prompt_gen) is True
            yield
        if case == "b-after-arm":
            assert isinstance(b.apply(), int)
        if case.startswith("b-"):
            h.press_b()
        yield from h.frames(10 ** 9)

    run = rig.run(host)
    resp.common(rig, run, "ADC", results=[0])
    expected = "UNCERTAIN" if case == "b-after-arm" else "NOT_PERFORMED"
    assert rig.binder.call("disposition")[0] == expected
    if case.startswith("timeout"):
        assert run.frames == 3600
    else:
        assert run.frames <= 3
    if expected == "UNCERTAIN":
        reset = rig.binder.call("reset")
        assert isinstance(reset, tuple) and reset[1] == "UNCERTAIN"
    else:
        assert rig.binder.call("reset") is True


@pytest.mark.parametrize("fault", ["token", "generation", "apply-zero"], ids=["token", "gen", "apply-zero"])
def test_real_responder_rejects_foreign_binding_and_apply_success_claim(env, fault):
    rig = HostRig(env)

    def host(h):
        b = rig.binder
        while not h.header(CMD["DONE"]):
            yield
        if fault != "apply-zero":
            offset = 12 if fault == "token" else 6
            original = h.rd(offset)
            h.wr(offset, original ^ 1)
            before = list(b.writes)
            assert b.call("poll_done") is None
            assert b.call("release", rig.prompt_gen)[0] is None and b.writes == before
            h.wr(offset, original)
        assert b.call("poll_done").disposition == "CONSENTED"
        assert b.call("release", rig.prompt_gen) is True
        yield
        before = list(b.writes)
        assert b.apply(token=[1, 2, 3, 4])[1] == "PENDING" and b.writes == before
        gen = b.apply()
        assert isinstance(gen, int)
        while not h.header(CMD["DONE"]):
            yield
        if fault == "apply-zero":
            h.wr(8, 0)  # An otherwise bound but unsupported trade-completion claim.
            assert b.call("poll_done").disposition == "UNCERTAIN"
            before = list(b.writes)
            h.wr(8, 1)
            assert b.call("poll_done").disposition == "UNCERTAIN"
            assert b.call("release", gen)[1] == "UNCERTAIN" and b.writes == before
            return
        assert b.call("poll_done").disposition == "NOT_PERFORMED"
        assert b.call("release", gen) is True

    run = rig.run(host)
    resp.common(rig, run, "ADADC", results=[0, 1])
    assert rig.binder.call("disposition")[0] == ("UNCERTAIN" if fault == "apply-zero" else "NOT_PERFORMED")


@pytest.mark.parametrize("command", ["QUERY", "OFFER", "PROMPT", "APPLY", "DONE", "RELEASE"],
                         ids=["query", "offer", "prompt", "apply", "done", "release"])
def test_prompt_does_not_overwrite_a_busy_mailbox(env, command):
    b = Binder(env)
    b.frame_image(command)
    out = prompt(b)
    assert isinstance(out, tuple) and out[1] == "PENDING" and not b.writes


def test_prompt_requires_responder_component_and_explicit_dev(env):
    profile = copy.deepcopy(PROFILE)
    profile["overlay"]["trade"]["capabilities"]["responder_service"] = False
    for name in ("SlinkTradeResponderService", "SlinkTradeResponderServiceEnd"):
        del profile["overlay"]["trade"]["entries"][name]
    b = Binder(env, profile=profile)
    out = prompt(b)
    assert isinstance(out, tuple) and out[1] == "PENDING" and not b.writes
    disabled = Binder(env, dev=False)
    assert disabled.api is None and not disabled.writes


def test_diagnostic_writer_does_not_expand_into_responder_role(env):
    b = Binder(env, test_hooks=True)
    consent_released(b)
    before = list(b.writes)
    out = b.api.test_hooks.write_bytes(b.api.test_hooks, LEASE + 5, b.lua.table_from([CMD["APPLY"]]))
    assert isinstance(out, tuple) and out[1] == "PENDING" and b.writes == before


@pytest.mark.parametrize("failure", ["throw", "drop-gen", "drop-release"], ids=["throw", "gen", "release"])
def test_responder_publication_failure_stays_poisoned(env, failure):
    b = Binder(env)
    if failure == "throw":
        b.fail_at = 5
        out = prompt(b)
    else:
        if failure == "drop-release":
            gen = prompt(b)
            done_frame(b, gen)
        at = LEASE + (6 if failure == "drop-gen" else 5)
        wanted = 1 if failure == "drop-gen" else CMD["RELEASE"]
        b.lua.globals().pywrite = lambda a, v: None if (a, v) == (at, wanted) else b.write(a, v)
        out = prompt(b) if failure == "drop-gen" else b.call("release", gen)
    assert out[1] == "UNCERTAIN"
    before = list(b.writes)
    b.fail_at = None
    b.lua.globals().pywrite = b.write
    b.put(LEASE + 5, 0)
    assert prompt(b)[1] == "UNCERTAIN" and b.call("reset")[1] == "UNCERTAIN"
    assert b.writes == before


@pytest.mark.parametrize("decision", [0, 1], ids=["consent-to-decline", "decline-to-consent"])
def test_prompt_decision_cannot_reverse(env, decision):
    b = Binder(env)
    gen = prompt(b)
    done_frame(b, gen, decision)
    assert b.call("poll_done").disposition in ("CONSENTED", "DECLINED")
    b.put(LEASE + 8, 1 - decision)
    assert b.call("poll_done").disposition == "UNCERTAIN"
    assert b.call("release", gen)[1] == "UNCERTAIN"


def assert_decline_is_not_apply_permission(env):
    b = Binder(env)
    gen = prompt(b)
    done_frame(b, gen, 1)
    assert b.call("poll_done").disposition == "DECLINED"
    assert b.call("release", gen) is True
    b.frame += 1
    b.put(LEASE + 8, 0)  # A later lease cannot turn the already observed decline into consent.
    before = list(b.writes)
    out = b.apply()
    assert isinstance(out, tuple) and out[1] == "PENDING" and b.writes == before


def test_decline_cannot_be_laundered_by_changing_the_released_frame(env):
    assert_decline_is_not_apply_permission(env)


MUTANTS = [
    ("consent", "if role == 'responder' and (phase == 'prompt' or phase == 'consented' or phase == 'declined') then",
     "if false then", lambda e: real_visit(e)),
    ("apply-phase", "if role == 'responder' and (phase == 'prompt' or phase == 'consented' or phase == 'declined') then",
     "if role == 'responder' then", lambda e: test_responder_apply_cannot_be_reclassified_as_prompt_consent(e, 0)),
    ("release-gap", "if frame() <= released_at then", "if false then", lambda e: real_visit(e)),
    ("decline", "or prompt_result ~= 0 then", "then", assert_decline_is_not_apply_permission),
    ("active-role", "if role ~= nil then", "if false then", test_roles_cannot_interleave_and_reset_requires_closure),
    ("query-role", "if role == 'responder' then return nil,'PENDING','responder visit active' end",
     "if false then return nil,'PENDING','responder visit active' end", test_roles_cannot_interleave_and_reset_requires_closure),
    ("busy", "if not self:closed() then return nil,'PENDING','lease must close before PROMPT' end",
     "if false then return nil,'PENDING','lease must close before PROMPT' end", lambda e: test_prompt_does_not_overwrite_a_busy_mailbox(e, "QUERY")),
    ("component", "if not t.capabilities.responder_service then", "if false then", test_prompt_requires_responder_component_and_explicit_dev),
    ("release-gen", "bytes[l.fields.generation+1] ~= prompt_visit.gen", "false",
     lambda e: test_apply_requires_unchanged_consent_release_lease(e, "generation")),
    ("release-ack", "bytes[l.fields.ack+1] ~= prompt_visit.gen", "false",
     lambda e: test_apply_requires_unchanged_consent_release_lease(e, "ack")),
    ("release-cmd", "bytes[l.fields.command+1] ~= t.commands.RELEASE", "false",
     lambda e: test_apply_requires_unchanged_consent_release_lease(e, "command")),
    ("apply-zero", "elseif result ~= 1 then", "elseif false then",
     lambda e: test_responder_apply_cannot_be_reclassified_as_prompt_consent(e, 0)),
    ("bad-prompt", "(result ~= 0 and result ~= 1)", "false",
     lambda e: test_prompt_dispositions_and_poison_are_phase_bound(e, 2, "UNCERTAIN")),
    ("reverse", "(prompt_result ~= nil and result ~= prompt_result)", "false",
     lambda e: test_prompt_decision_cannot_reverse(e, 0)),
    ("reset", "if attempted and disposition ~= 'NOT_PERFORMED' then", "if false then",
     lambda e: test_real_responder_closure_and_timeout_dispositions(e, "b-after-arm")),
]


@pytest.mark.parametrize("name,before,after,check", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_each_phase_guard_mutant_is_caught(env, monkeypatch, name, before, after, check):
    source = PATH.read_text(encoding="utf-8")
    assert source.count(before) == (2 if name == "query-role" else 1)
    check(env)
    original = Binder

    def mutated(*args, **kwargs):
        kwargs["mutation"] = (before, after)
        return original(*args, **kwargs)

    monkeypatch.setattr(sys.modules[__name__], "Binder", mutated)
    with pytest.raises(AssertionError):
        check(env)
