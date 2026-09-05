"""Side-effect-free status payloads for the Manager's no-run response."""


def empty_status_payload() -> dict:
    """Return fresh containers matching the run server's empty status schema.

    There is no game selected, so the badge catalogue is empty. A contract test
    compares the remaining nested keys and JSON types with the run serializer.
    """
    return {
        "save_failed": "",
        "players": {
            pid: {
                "connected": False,
                "rom_type": "?",
                "last_event": "—",
                "last_seen": "—",
                "last_seen_age": None,
                "nuzlocke_active": False,
                "current_area": "",
                "current_area_id": "",
                "current_area_display": "",
                "ball_count": 0,
                "badges": 0,
                "kanto_badges": 0,
                "trainer_name": "",
                "pc_boxes": [],
                "party_keys": [],
                "party_details": {},
                "queued": 0,
                "battle_state": {
                    "in_battle": False,
                    "is_trainer_battle": False,
                    "enemy_party": [],
                    "trainer_id": 0,
                    "opponent_name": "",
                    "opponent_class": "",
                    "is_doubles": False,
                },
                "identity_error": "",
                "encounter_table": None,
            }
            for pid in ("a", "b")
        },
        "links": [],
        "area_states": {},
        "pending_captures": {},
        "rules": {
            "species_lock": False,
            "gender_lock": False,
            "type_lock": False,
            "explode_mode": False,
            "rival_team_swap": False,
            "overworld_presence": False,
            "native_messages": False,
            "native_sounds": False,
            "battle_calc": True,
            "pc_trade_npc": True,
        },
        "recent_events": [],
        "killfeed": [],
        "run_over": False,
        "attempts_count": 0,
        "bonus_keys": {"a": [], "b": []},
        "pending_bonus": {"a": [], "b": []},
        "badge_slugs": [],
    }
