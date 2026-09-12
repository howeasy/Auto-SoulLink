"""RBY launch policy on the reusable checked-launcher builder."""
from pathlib import Path

from server.gen1_runtime_state import state_type_for
from server.runtime_launcher import file_bundle, render_launcher

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "lua/slink.lua", "lua/gen1_client_entry.lua", "lua/gen1_runtime.lua", "lua/gen1_session.lua", "lua/gen1_runtime_profiles.lua",
    "lua/durable_runtime.lua", "lua/client_session.lua", "lua/client_journal.lua", "lua/control_service.lua",
    "lua/command_executor.lua", "lua/connector.lua", "lua/json_codec.lua", "lua/state_store.lua",
    "lua/platform_storage.lua", "lua/platform_identity.lua", "lua/platform_execution.lua", "lua/platform_clock.lua",
    "lua/memory_gb.lua", "lua/gen1_write_safety.lua", "lua/games/gen1_rby.lua", "lua/gen1_party_codec.lua",
    "lua/staged_panel.lua",
    "lua/wire_protocol.lua", "lua/socket.lua", "lua/x64/socket-windows-5-4.dll",
    "data/games/gen1_rby/gen1_admission_profiles.lua", "data/games/gen1_rby/gen1_party_codec_data.lua",
    "data/games/gen1_rby/gen1_companion_profiles.lua",
)
OBSERVATION_FILES=("lua/gen1_held_initial_save.lua","lua/gen1_held_save_image.lua","lua/gen1_held_retirement.lua","lua/gen1_held_storage.lua","lua/gen1_storage_checkpoint.lua","lua/hex_delta.lua","lua/gen1_held_memorial.lua","lua/platform_saveram.lua","lua/gen1_initial_observation.lua","lua/gen1_full_save.lua","lua/gen1_trade_preparation.lua",
    "lua/gen1_held_faint.lua","lua/held_write_permit.lua","lua/gen1_write_checkpoint.lua","lua/gen1_force_faint_executor.lua",
    "lua/gen1_command_receipts.lua","lua/journal_document.lua","lua/observation_stream.lua",
    "lua/gen1_engine_signals.lua","data/games/gen1_rby/gen1_engine_signal_data.lua",
    "data/games/gen1_rby/gen1_full_save_layout.lua",
    "lua/gen1_bootstrap_observer.lua","data/games/gen1_rby/gen1_bootstrap_sites.lua")


ORDINARY_FILES = ("lua/gen1_frame_client.lua", "lua/platform_bounded_execution.lua",
                  "lua/execution_window.lua", "lua/frame_pacer.lua",
                  "lua/gen1_identity_guard.lua", "data/games/gen1_rby/gen1_identity_sites.lua",
                  "lua/gen1_acquisition_observers.lua", "lua/gen1_capture_observer.lua", "lua/gen1_grant_observer.lua",
                  "lua/gen1_native_frame_client.lua",
                  "lua/gen1_static_observer.lua", "lua/gen1_npc_exchange_observer.lua", "lua/gen1_wild_encounter_observer.lua",
                  "lua/gen1_evolution_observer.lua", "data/games/gen1_rby/gen1_evolution_sites.lua",
                  "data/games/gen1_rby/gen1_static_sites.lua", "data/games/gen1_rby/gen1_npc_exchange_sites.lua",
                  "data/games/gen1_rby/gen1_wild_encounter_sites.lua",
                  "data/games/gen1_rby/gen1_capture_sites.lua", "data/games/gen1_rby/gen1_grant_sites.lua")

NATIVE_FILES = ("lua/command_service_router.lua", "lua/gen1_native_runtime.lua",
    "lua/gen1_native_trade_executor.lua", "lua/gen1_partner_prompt_executor.lua", "lua/gen1_prepared_save.lua",
    "lua/gen1_receptionist_client.lua", "lua/gen1_receptionist_executor.lua", "lua/gen1_saved_trade_executor.lua",
    "lua/gen1_trade_abort.lua", "lua/gen1_trade_events.lua", "lua/staged_command.lua")


def configuration(runtime, player, *, root=ROOT):
    return build_configuration(runtime.journal.run_id, runtime.contract, player, root=root,
        prepared_cartridges=getattr(runtime,"prepared_cartridges",None),initial_observations=runtime.initial_observations,
        ordinary_frames=getattr(runtime,"ordinary_frames",False),native_trade=getattr(runtime,"native_trade",False))


def build_configuration(run_id, contract, player, *, root=ROOT,prepared_cartridges=None,initial_observations=False,
                        ordinary_frames=False,native_trade=False):
    profiles = state_type_for(prepared_cartridges).validate_contract(contract)
    if player not in ("a", "b"):
        raise ValueError("RBY launch player required")
    if type(ordinary_frames) is not bool or ordinary_frames and not initial_observations:
        raise ValueError("ordinary frame launch requires initial observations")
    if type(native_trade) is not bool or native_trade and (not ordinary_frames or prepared_cartridges is None
            or not all(p['capabilities']['pc_trade'] for p in profiles.values())):
        raise ValueError('native launcher requires the reproduced native cartridge pair and bounded frames')
    result={"schema": "slink-gen1-launch-v1", "protocol": "slink-gen1-durable-v1",
        "mode": "held_service", "run_id": run_id, "player": player,
        "cartridge": profiles[player], "files": file_bundle(root, FILES+(OBSERVATION_FILES if initial_observations else ())
                                                          +(ORDINARY_FILES if ordinary_frames else ())
                                                          +(NATIVE_FILES if native_trade else ()))}
    if initial_observations:result['initial_observations']=True
    if ordinary_frames:result['ordinary_frames']=True
    if native_trade:result['native_manifest']=prepared_cartridges.manifest(player)
    return result


def launcher(runtime, player, host, port, *, name="SLink", root=ROOT, root_hint=None):
    return render_launcher(configuration(runtime, player, root=root), host=host, port=port, name=name, root_hint=root_hint)
