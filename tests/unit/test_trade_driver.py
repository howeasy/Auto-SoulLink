"""Automatic transitions through the real SQLite coordinator; physical policy is modeled."""

from types import SimpleNamespace

import pytest

from server.identity_registry import IdentityRegistry, IdentityWitness, MigrationWitness
from server.protocol_journal import JournalError
from server.trade_coordinator import PreparedTrade, TradeCoordinator, TradeVerification
from server.trade_driver import TradeDriver
from tests.unit.test_trade_runtime_composition import source  # noqa: F401


@pytest.fixture
def run(source):  # noqa: F811
    journal, policy = source
    policy.control = policy.owner
    policy.fail_finalize = False
    policy.decision = lambda trade, p, command, receipt: (True, receipt)
    policy.prepare = lambda trade, p: {"schema": "test-prepare-v1"}
    policy.ready = lambda trade, p, command, receipt: PreparedTrade(
        trade["proposal_digest"],
        trade["proposal"]["participants"][p]["context"]["context_generation"],
        trade["proposal"]["participants"][p]["evidence_digest"],
        receipt,
    )
    policy.commit = lambda *args: {"schema": "test-commit-v1"}
    policy.applied = lambda trade, p, command, receipt: receipt

    def verified(trade, p, command, receipt):
        own = trade["proposal"]["participants"][p]
        peer = trade["proposal"]["participants"]["b" if p == "a" else "a"]
        witness = MigrationWitness(
            peer["member_id"],
            IdentityRegistry._read_context(peer["context"]),
            peer["key"],
            peer["evidence_digest"],
            IdentityWitness(
                IdentityRegistry._read_context(own["context"]),
                "same-key",
                ("c" if p == "a" else "d") * 64,
                1,
            ),
        )
        return TradeVerification(witness, {"schema": "test-native-v1"}, {"schema": "test-file-v1"})

    policy.verified = verified

    def finalize(rules, *args):
        if policy.fail_finalize:
            raise JournalError("injected finalization failure")
        return rules

    policy.finalize = finalize
    value = SimpleNamespace(journal=journal, policy=policy)
    sequence = 100

    def op():
        nonlocal sequence
        sequence += 1
        return f"{sequence:032x}"

    service = TradeCoordinator(journal, policy, clock=lambda: 1000, new_id=op)
    value.service = service

    def command(p, kind):
        return next(row for row in journal.pending(p) if row["cmd"] == kind)

    def event(p, kind, issued, receipt):
        return service.handle(
            p,
            op(),
            {
                "event": kind,
                "transaction_id": value.tx,
                "command_id": issued["command_id"],
                "command_sequence": issued["command_sequence"],
                "receipt": receipt,
            },
            owner=policy.owner,
        )

    def offer():
        value.tx = service.handle(
            "a", op(), {"event": "trade_offer", "payload": {}}, owner=policy.owner
        )["transaction_id"]

    value.offer = offer
    value.accept = lambda: event(
        "b", "trade_decision", command("b", "native_trade_prompt"), {"schema": "test-decision-v1"}
    )
    value.ready = lambda p: event(
        p, "trade_ready", command(p, "native_trade_prepare"), {"schema": "test-ready-v1"}
    )
    value.control = lambda action, details=None: service.control(
        action, value.tx, op(), authority=policy.owner, details=details
    )

    def committed():
        offer()
        value.accept()
        value.control("prepare")
        value.ready("a")
        value.ready("b")
        value.control("commit")

    value.committed = committed

    def apply(p):
        issued = command(p, "native_trade_commit")
        event(p, "trade_applied", issued, {"schema": "test-applied-v1"})
        return issued, None

    value.apply = apply
    value.verify = lambda p, issued, after: event(
        p, "trade_verified", issued, {"schema": "test-verified-v1"}
    )
    yield value


def driver_for(value):
    return TradeDriver(
        lambda: value.service.status(value.tx) if hasattr(value, "tx") else None,
        lambda action, tx, operation: value.service.control(
            action, tx, operation, authority=value.policy.control
        ),
    )


def test_driver_advances_only_after_both_required_verified_inputs(run):  # noqa: F811
    driver = driver_for(run)
    assert driver.step() is None
    run.offer()
    assert driver.step() is None
    run.accept()
    assert driver.step()["action"] == "prepare"
    assert driver.step() is None
    run.ready("a")
    assert driver.step() is None
    run.ready("b")
    assert driver.step()["action"] == "commit"
    before = run.journal.snapshot()
    assert driver.step() is None
    assert run.journal.snapshot() == before
    command, after = run.apply("a")
    run.verify("a", command, after)
    assert driver.step() is None
    command, after = run.apply("b")
    run.verify("b", command, after)
    assert driver.step()["action"] == "finalize"
    assert driver.step() is None


def test_interrupted_verified_trade_never_automatically_resumes(run):  # noqa: F811
    run.committed()
    for p in ("a", "b"):
        command, after = run.apply(p)
        run.verify(p, command, after)
    run.control("interrupt", details={"reason": "owned context lost"})
    before = run.journal.snapshot()
    assert driver_for(run).step() is None
    assert run.journal.snapshot() == before


def test_failed_finalization_stays_retryable_without_publishing_a_partial_link(run):  # noqa: F811
    run.committed()
    for p in ("a", "b"):
        command, after = run.apply(p)
        run.verify(p, command, after)
    driver = driver_for(run)
    run.policy.fail_finalize = True
    before = run.journal.snapshot()
    with pytest.raises(JournalError):
        driver.step()
    assert run.journal.snapshot() == before
    run.policy.fail_finalize = False
    assert driver.step()["action"] == "finalize"


@pytest.mark.parametrize(
    "state",
    [
        {"phase": "accepted", "recovery_required": False},
        {"phase": "made_up", "transaction_id": "a" * 32, "recovery_required": False},
        {"phase": "accepted", "transaction_id": "a" * 32, "recovery_required": 0},
    ],
)
def test_invalid_status_cannot_drive_a_transition(state):
    calls = []
    driver = TradeDriver(lambda: state, lambda *args: calls.append(args))
    with pytest.raises(JournalError):
        driver.step()
    assert not calls


@pytest.mark.parametrize("value", [False, 0, "", [], {}, "not callable", object()])
def test_invalid_identifier_factory_refuses_before_reading_or_advancing(value):
    calls = []
    with pytest.raises(JournalError, match="factory must be callable"):
        TradeDriver(lambda: calls.append("read"), lambda *args: calls.append("advance"), new_id=value)
    assert calls == []


def test_falsey_callable_identifier_factory_is_retained():
    class Factory:
        def __bool__(self):
            return False

        def __call__(self):
            return "b" * 32

    factory = Factory()
    driver = TradeDriver(
        lambda: {"phase": "accepted", "transaction_id": "a" * 32, "recovery_required": False},
        lambda action, transaction, operation: operation,
        new_id=factory,
    )
    assert driver.new_id is factory
    assert driver.step() == {"action": "prepare", "result": "b" * 32}
