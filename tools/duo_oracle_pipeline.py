"""Duo evidence orchestration; cartridge facts belong to injected validators."""
import inspect
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceContract:
    witness_validator: str | None = None
    require_oracle: bool = False


def _callback(owner, name, stage):
    callback = getattr(owner, name, None) if isinstance(name, str) and name else None
    if not callable(callback):
        raise RuntimeError(f"{stage} is missing or not callable: {name!r}")
    return callback


def _arguments(callback, kwargs, stage):
    try:
        inspect.signature(callback).bind({}, **kwargs)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {stage} arguments: {exc}") from exc


def validate_pipeline(owner, contract, scenario):
    """Resolve every stage before any launch or evidence callback can run."""
    if not isinstance(contract, EvidenceContract):
        raise RuntimeError("missing or invalid family evidence contract")
    if type(contract.require_oracle) is not bool:
        raise RuntimeError("invalid family evidence contract: require_oracle must be bool")
    if not isinstance(scenario, Mapping):
        raise RuntimeError("invalid scenario evidence declaration")
    witness = None
    if contract.require_oracle or contract.witness_validator is not None:
        if not contract.require_oracle:
            raise RuntimeError("evidence contract witness requires a post-result oracle")
        witness = _callback(owner, contract.witness_validator, "witness validator")
    name = scenario.get("oracle")
    oracle = None
    if contract.require_oracle and not name:
        raise RuntimeError(f"{owner.scenario} declares no post-result oracle in SCENARIOS")
    if contract.require_oracle or name:
        oracle = _callback(owner, name, "post-result oracle")
    kwargs = scenario.get("oracle_kwargs", {})
    if not isinstance(kwargs, dict) or any(not isinstance(key, str) for key in kwargs):
        raise RuntimeError("invalid post-result oracle kwargs")
    if witness is not None:
        _arguments(witness, {}, "witness validator")
    if oracle is not None:
        _arguments(oracle, kwargs, "post-result oracle")
    return witness, oracle, dict(kwargs)


def run_pipeline(owner, contract, scenario, results):
    """Transport the original receipts, witness first; None preserves legacy success."""
    witness, oracle, kwargs = validate_pipeline(owner, contract, scenario)
    if witness is not None and witness(results) is False:
        raise RuntimeError("witness validator rejected evidence")
    if oracle is not None and oracle(results, **kwargs) is False:
        raise RuntimeError("post-result oracle rejected evidence")
