"""Select native execution only from an already owned, admitted cartridge contract."""
from server.gen1_cartridge_profiles import companion_profiles
from server.adapters.gen1_rom_scan import RomScanError
from server.gen1_native_execution import NativeExecutionPolicy
from server.gen1_trade_result import TradeResultRules
from server.protocol import canonical_json
from server.protocol_journal import JournalError
from server.durable_runtime import TIMEOUT
from server.trade_driver import TradeDriver


def install_native_execution(runtime, *, roms=None):
    """Install the native frame verifier; never enable ordinary or recovery play.

    Canonical callers supply both exact local ROM byte snapshots. Reproduced UPR
    runs use their existing immutable registry; replacement bytes are not accepted.
    Trade policy/controller and current physical admission remain separate gates.
    """
    from server.gen1_held_faint import verify as held_verifier
    fallback = runtime.verify_operation_execution
    if runtime.trade is None or (fallback is not None and fallback is not held_verifier) or runtime._failed:
        raise JournalError("owned native coordinator and unselected execution binding required")
    stage=runtime.state()
    if canonical_json(stage.component["contract"])!=canonical_json(runtime.contract):
        raise JournalError("native runtime contract changed")
    cartridges=runtime.prepared_cartridges
    if cartridges is not None:
        if roms is not None:raise JournalError("reproduced native cartridges cannot be replaced")
        cartridges.validate_contract(runtime.contract)
        manifests={p:cartridges.manifest(p) for p in ("a","b")}
        images={p:cartridges.rom(p) for p in ("a","b")}
    else:
        if not isinstance(roms,dict) or set(roms)!={"a","b"} or any(type(raw) is not bytes for raw in roms.values()):
            raise JournalError("both immutable admitted native ROM images required")
        profiles=companion_profiles()
        manifests={p:profiles[expected["variant"]]["manifest"] for p,expected in runtime.contract["players"].items()}
        images=dict(roms)
    rules={}
    for p,expected in runtime.contract["players"].items():
        if (expected["capabilities"]["pc_trade"] is not True
                or manifests[p]["final_sha1"]!=expected["final_rom_sha1"]):
            raise JournalError("admitted native trade companion required")
        try:
            rules[p]=TradeResultRules.from_rom(expected["variant"],images[p],expected_sha1=expected["final_rom_sha1"])
        except (RomScanError,ValueError) as error:
            raise JournalError(f"player {p}: native ROM differs from the admitted contract: {error}") from error
    verifier=NativeExecutionPolicy(rules=rules,manifests=manifests,fallback=fallback)
    verifier.bind(runtime)
    runtime.verify_operation_execution=verifier
    return verifier


def install_native_driver(runtime, *, authority):
    if (runtime.trade is None or runtime.trade_driver is not None
            or not isinstance(runtime.verify_operation_execution,NativeExecutionPolicy)
            or runtime.verify_operation_execution.runtime is not runtime):
        raise JournalError("owned native execution binding and unselected driver required")
    def current():
        identifier=runtime.state().document()["active_trade"]
        return runtime.trade.status(identifier) if identifier else None
    def advance(action,identifier,operation):
        now=runtime._now()
        if (runtime._failed or set(runtime.gate.sessions)!={"a","b"}
                or set(runtime._control_seen)!={"a","b"}
                or any(now-seen>=TIMEOUT for seen in runtime._control_seen.values())):
            return None
        return runtime.trade_control(action,identifier,operation,authority=authority)
    runtime.trade_driver=TradeDriver(current,advance)
    return runtime.trade_driver
