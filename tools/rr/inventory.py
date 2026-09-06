"""Required RR release cases. This is an inventory, never completed evidence."""
from copy import deepcopy

SCHEMA_VERSION = 1
MODES = ("default_mgm_off", "default_mgm_on")
GROUPS = ("foundation", "admission", "storage", "battle", "acquisition", "native",
          "ghost", "presentation", "distribution", "campaign", "soak")
BINDING_ROLES = ("source", "rom", "patch", "client", "data", "emulator", "fixture")
BASE_ROM_MD5 = "8529f3a45d32bce4da637976fcf269d4"

# Each tuple contains a stable suffix and independently reportable required oracles.
CASES = {
    "foundation": [
        ("partial_tcp_frames", "all_bytes_delivered_once", "one_semantic_action"),
        ("durable_reconnect", "same_action_identity", "receipt_survives_restart"),
        ("duplicate_delivery", "mutation_applied_once", "same_receipt_returned"),
        ("coordinator_restart", "pending_actions_recovered", "no_unverified_retry"),
        ("malformed_message", "rejected_without_mutation", "connection_state_consistent"),
        ("staged_state_commit", "old_state_until_commit", "committed_state_complete"),
    ],
    "admission": [
        ("current_companion_both_players", "both_loaded_roms_match", "both_descriptors_match"),
        ("missing_companion", "admission_refused", "no_game_mutation"),
        ("stale_patch", "admission_refused", "actionable_version_reason"),
        ("wrong_rom", "admission_refused", "no_game_mutation"),
        ("mismatched_player_builds", "admission_refused", "no_game_mutation"),
        ("unsupported_mode", "mode_detected_from_game", "admission_refused"),
        ("trainer_save_identity", "trainer_identity_used", "lead_ot_does_not_change_identity"),
        ("savestate_rollback", "generation_invalidated", "paused_until_reconciled"),
        ("mixed_mgm_pair", "admission_refused", "both_actual_modes_recorded"),
    ],
    "storage": [
        ("deposit", "source_identity_checked", "destination_faithful", "source_removed_once"),
        ("withdraw", "source_identity_checked", "stats_and_pp_correct", "source_removed_once"),
        ("memorialize", "correct_dead_identity", "destination_not_overwritten", "survivors_preserved"),
        ("occupied_destination", "mutation_refused", "both_mons_preserved"),
        ("full_party_or_boxes", "mutation_refused", "no_loss_or_duplicate"),
        ("all_25_boxes", "each_box_address_verified", "every_box_roundtrip_faithful"),
        ("reordered_party", "expected_key_relocated_or_rejected", "other_mons_unchanged"),
        ("last_usable_mon", "rule_applied_explicitly", "no_uncontrolled_whiteout"),
        ("move_item_status_roundtrip", "moves_pp_item_status_preserved", "mode_stats_correct"),
        ("borrowed_party_freeze", "real_party_not_replaced", "deferred_work_reconciled"),
        ("battle_context_refusal", "unsafe_write_deferred", "eventual_readback_matches"),
        ("ambiguous_completion", "no_blind_retry", "identity_readback_reconciled"),
    ],
    "battle": [
        ("player_faint", "settled_faint_detected_once", "correct_link_propagated"),
        ("foe_faint", "no_player_death_emitted", "player_party_unchanged"),
        ("simultaneous_faints", "each_identity_counted_once", "final_link_state_consistent"),
        ("battle_epoch", "stale_counters_not_replayed", "next_battle_detects_new_faint"),
        ("outcome_codes", "rr_outcome_decoded", "win_loss_escape_distinguished"),
        ("explosion_lua_path", "production_lua_path_used", "move_resolves_without_softlock"),
        ("explosion_special_states", "blocked_or_forced_behavior_verified", "no_controller_corruption"),
        ("whiteout", "all_deaths_settled", "return_scene_reconciled"),
        ("rival_team_replace", "expected_team_committed", "active_battlers_consistent"),
        ("rival_swap_restore", "borrowed_party_epoch_closed", "real_party_preserved"),
    ],
    "acquisition": [
        ("starter", "real_game_acquisition", "identity_and_area_linked_once"),
        ("wild_capture", "real_game_capture", "pair_consistent_both_players"),
        ("gift", "real_game_gift", "policy_applied_once"),
        ("egg_and_hatch", "identity_survives_hatch", "no_duplicate_acquisition"),
        ("fossil", "real_game_revival", "policy_applied_once"),
        ("static_encounter", "correct_encounter_area", "policy_applied_once"),
        ("dupes", "duplicate_policy_verified", "eligible_encounter_not_consumed"),
        ("dead_zone", "restriction_enforced", "unrelated_area_unchanged"),
        ("shiny_bonus", "shiny_rule_verified", "bonus_link_consistent"),
        ("capture_to_pc", "boxed_identity_observed", "link_not_lost"),
    ],
    "native": [
        ("mailbox_queued_receipts", "each_sequence_receipt_retained", "payload_not_overwritten"),
        ("async_owner", "one_owner_until_retirement", "queued_work_eventually_resolves"),
        ("buffer_lifetime", "last_reader_finishes_before_reuse", "text_and_blob_intact"),
        ("sequence_wrap_reset", "old_receipt_not_reused", "generation_change_detected"),
        ("arena_ownership", "all_arena_accesses_attributed", "no_legitimate_owner_collision"),
        ("native_trade", "native_scene_observed", "matching_halves_swapped", "readback_reconciled"),
        ("trade_evolution", "native_evolution_observed", "post_evolution_identity_reconciled"),
        ("trade_ui_cancel", "cancel_preserves_party", "field_and_mailbox_released"),
        ("pc_trade_npc", "safe_template_and_interaction", "resources_released"),
        ("pause_during_scene", "new_gameplay_blocked", "controlled_completion_only", "reconcile_before_resume"),
    ],
    "ghost": [
        ("initialized_gfx16", "stack_pattern_independent", "full_graphics_id_preserved"),
        ("avatar_spawn_commit", "complete_avatar_after_spawn", "palette_only_change_applied"),
        ("palette_reference_lifetime", "references_balanced", "unrelated_palettes_preserved"),
        ("sprite_tile_ownership", "geometry_matches_allocation", "no_foreign_resource_write"),
        ("resource_exhaustion", "no_partial_or_borrowed_resources", "retry_after_capacity_recovers"),
        ("running", "motion_matches_source", "no_sprite_corruption"),
        ("bike", "complete_mode_animation", "geometry_and_speed_correct"),
        ("surf", "bound_surf_effect_present", "bobbing_and_teardown_correct"),
        ("fishing", "complete_rod_animation", "return_to_walk_resources_correct"),
        ("scene_reconstruction", "no_nonfield_writes", "one_owner_after_return"),
        ("freshness_disconnect", "stale_visibility_and_collision_removed", "fresh_epoch_respawns"),
        ("interaction", "valid_native_script_only", "no_unintended_warp_or_battle"),
        ("elevation_depth", "correct_remote_elevation", "depth_and_collision_consistent"),
    ],
    "presentation": [
        ("native_messages", "text_complete_and_dismissible", "field_released"),
        ("battle_notifications", "text_persists_in_context", "no_window_or_palette_corruption"),
        ("sounds", "correct_cue_audible", "no_audio_stall_or_corruption"),
        ("calculator", "display_matches_independent_oracle", "toggle_and_notification_coexist"),
        ("info_panel", "live_pairs_and_status_correct", "pagination_and_close_work"),
        ("dashboard_and_pause", "actual_run_state_visible", "pause_reason_and_recovery_visible"),
    ],
    "distribution": [
        ("reproducible_build", "source_rebuild_matches_patch", "no_mutable_native_rom_sections"),
        ("clean_patch_application", "clean_base_hash_verified", "output_rom_matches_manifest"),
        ("wrong_patch_input", "wrong_input_rejected", "original_rom_unchanged"),
        ("package_contents", "all_runtime_files_present", "client_data_native_versions_consistent"),
        ("fresh_machine_launch", "clean_install_starts", "both_clients_admitted"),
        ("build_descriptor", "actual_loaded_descriptor_matches", "layout_and_capabilities_match"),
        ("evidence_manifest", "all_hashes_verified", "no_missing_skipped_or_retried_cases"),
    ],
    "campaign": [
        ("starter_to_brock", "real_progression_recorded", "links_and_party_consistent"),
        ("misty_to_surge", "real_progression_recorded", "links_and_party_consistent"),
        ("erika", "real_progression_recorded", "links_and_party_consistent"),
        ("koga", "real_progression_recorded", "links_and_party_consistent"),
        ("sabrina", "real_progression_recorded", "links_and_party_consistent"),
        ("blaine", "real_progression_recorded", "links_and_party_consistent"),
        ("giovanni", "real_progression_recorded", "links_and_party_consistent"),
        ("elite_four", "real_progression_recorded", "links_and_party_consistent"),
        ("champion_and_credits", "credits_reached_in_game", "final_party_and_links_reconciled"),
        ("supported_postgame", "named_checkpoint_manifest_completed", "postgame_state_reconciled"),
    ],
    "soak": [
        ("normal_speed_2h", "continuous_capture_accounted", "no_uncertain_operation", "resources_balanced"),
    ],
}

# Twenty different transitions/fault boundaries, not twenty aliases of one retry.
TIMING_SCENARIOS = (
    ("ghost", "existing_ghost_to_wild_battle"),
    ("ghost", "existing_ghost_to_trainer_battle"),
    ("ghost", "battle_return_resource_reuse"),
    ("ghost", "door_warp_during_sample"),
    ("ghost", "bike_mount_dismount"),
    ("ghost", "surf_mount_dismount"),
    ("ghost", "fishing_return"),
    ("ghost", "avatar_commit_during_respawn"),
    ("native", "party_picker_return"),
    ("native", "bag_menu_return"),
    ("native", "trade_scene_takeover"),
    ("native", "trade_evolution_completion"),
    ("native", "notification_payload_contention"),
    ("native", "queued_receipt_retirement"),
    ("storage", "source_reorder_before_commit"),
    ("storage", "destination_changes_before_commit"),
    ("battle", "faint_at_outcome_boundary"),
    ("battle", "borrowed_party_restore_boundary"),
    ("foundation", "disconnect_after_apply_before_receipt"),
    ("admission", "reset_during_pending_operation"),
)
SOAK_MIN_COUNTS = {
    "map_transitions": 100, "battles_completed": 30, "storage_roundtrips": 25,
    "native_trades_completed": 5, "ghost_mode_transitions": 30,
    "reconnect_recoveries": 10, "native_ui_cycles": 50,
}


def build_inventory():
    cases = []
    for mode in MODES:
        for group, rows in CASES.items():
            for suffix, *assertions in rows:
                case = {"case_id": f"rr41.{mode}.{group}.{suffix}", "mode": mode,
                        "group": group, "assertions": list(assertions), "requirements": {}}
                if group == "soak":
                    case["requirements"] = {"normal_speed_wall_seconds": 7200,
                                            "scenario_counts": deepcopy(SOAK_MIN_COUNTS)}
                if suffix == "supported_postgame":
                    case["requirements"]["candidate_postgame_checkpoints"] = True
                cases.append(case)
        for group, scenario in TIMING_SCENARIOS:
            cases.append({"case_id": f"rr41.{mode}.{group}.timing_{scenario}",
                          "mode": mode, "group": group,
                          "assertions": ["correct_boundary_behavior", "no_foreign_or_duplicate_mutation",
                                         "final_state_and_resources_reconciled"],
                          "requirements": {"meaningful_repetitions": 20, "timing_scenario": scenario}})
    return {"schema_version": SCHEMA_VERSION, "inventory_id": "rr41-stability-v1",
            "modes": list(MODES), "groups": list(GROUPS),
            "candidate": {"candidate_id": None, "source_commit": None,
                          "game": "rr4.1", "base_rom_md5": BASE_ROM_MD5,
                          "native_abi": 2, "native_build_id": None,
                          "layout_sha256": None, "capabilities_sha256": None,
                          "bindings": {role: None for role in BINDING_ROLES if role != "fixture"},
                          "fixtures": dict.fromkeys(MODES),
                          "postgame_checkpoints": []},
            "cases": cases}
