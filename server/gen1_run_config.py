"""Explicit prepared-run selection for the Gen1 held-service launcher/runtime."""
from __future__ import annotations

from pathlib import Path

from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_held_faint import verify as verify_held_faint
from server.gen1_runtime import Gen1Runtime
from server.gen1_runtime_state import state_type_for
from server.journal_reader import read_journal
from server.json_files import atomic_write_json
from server.protocol import canonical_json, decode_frame, digest
from server.protocol_journal import JournalError

FILENAME = "gen1_runtime.json"
SCHEMA = "slink-gen1-prepared-run-v1"


def read_configuration(directory):
    return read_bound_configuration(directory)[0]


def read_bound_configuration(directory):
    directory = Path(directory).resolve()
    path = directory/FILENAME
    if not path.exists():
        return None,None
    value = decode_frame(path.read_bytes())
    fields={"schema", "mode", "run_id", "journal", "contract"}
    if (set(value)-fields-{'prepared_artifacts','initial_observations','native_trade','free_service'} or not fields<=set(value) or value["schema"] != SCHEMA
            or ('initial_observations' in value and value['initial_observations'] is not True)
            or ('native_trade' in value and (value['native_trade'] is not True or value.get('initial_observations') is not True or 'prepared_artifacts' not in value))
            or ('free_service' in value and (value['free_service'] is not True or value.get('initial_observations') is not True))
            or value["mode"] != "held_service" or not isinstance(value["journal"], str)
            or Path(value["journal"]).name != value["journal"] or ":" in value["journal"] or "\\" in value["journal"]):
        raise JournalError("unsupported prepared Gen1 run configuration")
    journal = (directory/value["journal"]).resolve()
    if journal.parent != directory:
        raise JournalError("Gen1 journal must belong to this run directory")
    cartridges=None
    if "prepared_artifacts"in value:
        from server.gen1_prepared_cartridges import PreparedCartridges
        relative=value["prepared_artifacts"]
        if not isinstance(relative,str)or Path(relative).is_absolute():raise JournalError("relative prepared artifact directory required")
        artifacts=(directory/relative).resolve()
        if not artifacts.is_relative_to(directory):raise JournalError("prepared artifacts leave this run")
        cartridges=PreparedCartridges(artifacts)
    stored = read_journal(journal, run_id=value["run_id"], contract_hash=digest(value["contract"]))
    stage = state_type_for(cartridges).restore(stored.snapshot.state, data_dir=str(directory))
    if canonical_json(stage.component["contract"]) != canonical_json(value["contract"]):
        raise JournalError("prepared Gen1 contract differs from the committed runtime")
    return value,cartridges


def configure_runtime(runtime):
    """Publish only from an already opened, explicitly bootstrapped runtime."""
    directory = Path(runtime.data_dir).resolve()
    journal = runtime.journal.path.resolve()
    if journal.parent != directory:
        raise JournalError("runtime journal is outside its run directory")
    stage = runtime.state()
    value = {"schema": SCHEMA, "mode": "held_service", "run_id": runtime.journal.run_id,
        "journal": journal.name, "contract": stage.component["contract"]}
    if runtime.initial_observations:value['initial_observations']=True
    if runtime.native_trade:value['native_trade']=True
    if runtime.free_service:value['free_service']=True
    cartridges=getattr(runtime,"prepared_cartridges",None)
    if cartridges is not None:
        if not cartridges.directory.is_relative_to(directory):raise JournalError("prepared artifacts must belong to this run")
        value["prepared_artifacts"]=cartridges.directory.relative_to(directory).as_posix()
    path = directory/FILENAME
    if path.exists():
        if canonical_json(read_configuration(directory)) != canonical_json(value):
            raise JournalError("prepared run configuration is immutable")
        return value
    atomic_write_json(path, value)
    return value


def open_runtime(directory):
    value,cartridges = read_bound_configuration(directory)
    if value is None:
        return None
    def no_new_observations(*args):
        raise JournalError("gameplay observation binding is not qualified in held-service mode")
    return Gen1Runtime(Path(directory)/value["journal"], contract=value["contract"], data_dir=directory,
        run_id=value["run_id"], validate_event=no_new_observations,
        prepared_cartridges=cartridges,
        initial_observations=value.get('initial_observations',False),
        native_trade=value.get('native_trade',False),
        free_service=value.get('free_service',False),
        verify_operation_execution=verify_held_faint if value.get('initial_observations',False) else None,
        validate_receipt=Gen1ReceiptPolicy({p: c["variant"] for p,c in value["contract"]["players"].items()}),
        verify_reconciliation=lambda *args: None)


def create_runtime(directory,contract,*,run_id=None,prepared_cartridges=None,rule_options=None,native_trade=False,free_service=False):
    """Create an empty owned run; initial game evidence arrives separately over TCP.

    free_service=True launches the free-running observation client (P10). free_service=False keeps
    the held-service launch (enrollment and writes under the hold, no gameplay) that the bootstrap
    launcher rows still use. The frame-credit mode that used to sit between them is retired.
    """
    import secrets

    from server.adapters import get_adapter
    from server.gen1_staged_state import StagedGen1State
    from server.identity_registry import IdentityRegistry
    from server.state import SoulLinkState
    if type(native_trade) is not bool or native_trade and prepared_cartridges is None:
        raise JournalError('native trade selection requires reproduced prepared cartridges')
    if type(free_service) is not bool:
        raise JournalError('explicit free-run observation selection required')
    allowed={'species_lock','gender_lock','type_lock','explode_mode','rival_team_swap','native_sounds','pc_trade_npc'}
    if (rule_options is not None
            and (not isinstance(rule_options,dict) or set(rule_options)-allowed
                 or any(type(value) is not bool for value in rule_options.values()))):
        raise JournalError('explicit supported Gen1 rule options required')
    if rule_options and rule_options.get('native_sounds') is True:
        raise JournalError('Gen 1 native sounds are unavailable')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    if any((directory/name).exists() for name in (FILENAME,'runtime.sqlite3','links.json','memorial.json')):
        raise JournalError('fresh runtime creation cannot replace an existing or legacy run')
    profiles=state_type_for(prepared_cartridges).validate_contract(contract)
    run_id=run_id or secrets.token_hex(16)
    rules=SoulLinkState(data_dir=str(directory),adapter=get_adapter('gen1_rby',rom_type=profiles['a']['variant'],
        peer_rom_type=profiles['b']['variant']))   # the pair decides the starter clause policy
    rules.rom_type=profiles['a']['variant']
    rules.battle_calc=False;rules.native_messages=False;rules.overworld_presence=False
    if rule_options is not None:
        for key,value in rule_options.items():setattr(rules,key,value)
    initial=state_type_for(prepared_cartridges).initial(
        StagedGen1State.from_live(rules,{'retired_pairs':[]}).document(),IdentityRegistry(run_id).document(),contract,data_dir=directory)
    def unavailable(*args):raise JournalError('ordinary gameplay policy is not selected for initial enrollment')
    journal=directory/'runtime.sqlite3'
    try:
        with journal.open('xb'):pass
    except FileExistsError as error:raise JournalError('fresh runtime journal was already created') from error
    runtime=Gen1Runtime(journal,contract=contract,data_dir=directory,run_id=run_id,
        initial_state=initial,initial_observations=True,prepared_cartridges=prepared_cartridges,
        native_trade=native_trade,
        free_service=free_service,
        verify_operation_execution=verify_held_faint,
        validate_event=unavailable,validate_receipt=Gen1ReceiptPolicy({p:c['variant'] for p,c in profiles.items()}),
        verify_reconciliation=lambda *args:None)
    try:configure_runtime(runtime)
    except Exception:runtime.close();raise
    return runtime
