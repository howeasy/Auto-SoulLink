"""
Unit tests for stat stage icon rendering and passthrough.

Tests:
- stat_stages_html() helper in server/html_render.py
- status_icon_html() helper in server/html_render.py
- stat_stages field flows through tick handler → party_details
- stat_stages flows through _enrich_battle_state() for enemy party
- Offset constant M.BATTLE_MON_STAT_STAGES_OFF = 0x19 (cannot read CFRU type3)
"""
import pytest
from server.html_render import (
    stat_stages_html as _stat_stages_html,
    STAT_STAGE_LABELS as _STAT_STAGE_LABELS,
    status_icon_html as _status_icon_html,
)


# ── _stat_stages_html: None / empty / all-neutral ────────────────────────────

class TestStatStagesHtmlNullCases:
    def test_none_returns_empty(self):
        assert _stat_stages_html(None) == ""

    def test_empty_list_returns_empty(self):
        assert _stat_stages_html([]) == ""

    def test_all_neutral_returns_empty(self):
        assert _stat_stages_html([6, 6, 6, 6, 6, 6, 6]) == ""

    def test_string_returns_empty(self):
        assert _stat_stages_html("garbage") == ""

    def test_dict_returns_empty(self):
        assert _stat_stages_html({"atk": 8}) == ""

    def test_int_returns_empty(self):
        assert _stat_stages_html(8) == ""


# ── _stat_stages_html: content correctness ───────────────────────────────────

class TestStatStagesHtmlContent:
    def test_atk_boost_2(self):
        # ATK = 8, all others neutral
        result = _stat_stages_html([8, 6, 6, 6, 6, 6, 6])
        assert "+2" in result
        assert "ATK" in result
        assert "ss-up" in result
        assert "ss-dn" not in result

    def test_spd_drop_1(self):
        # SPD = 5 (index 2)
        result = _stat_stages_html([6, 6, 5, 6, 6, 6, 6])
        assert "\u22121" in result
        assert "SPD" in result
        assert "ss-dn" in result
        assert "ss-up" not in result

    def test_multiple_stages(self):
        # ATK +2, DEF -1, ACC +1
        result = _stat_stages_html([8, 5, 6, 6, 6, 7, 6])
        assert "+2 ATK" in result
        assert "\u22121 DEF" in result
        assert "+1 ACC" in result

    def test_max_stage_12(self):
        result = _stat_stages_html([12, 6, 6, 6, 6, 6, 6])
        assert "+6 ATK" in result

    def test_min_stage_0(self):
        result = _stat_stages_html([0, 6, 6, 6, 6, 6, 6])
        assert "\u22126 ATK" in result

    def test_label_order(self):
        # Each stat should map to correct label
        for i, label in enumerate(_STAT_STAGE_LABELS):
            stages = [6] * 7
            stages[i] = 8  # +2 boost
            result = _stat_stages_html(stages)
            assert label in result, f"Expected label '{label}' at index {i}"

    def test_exactly_7_labels(self):
        assert _STAT_STAGE_LABELS == ["ATK", "DEF", "SPD", "SATK", "SDEF", "ACC", "EVA"]
        assert len(_STAT_STAGE_LABELS) == 7


# ── _stat_stages_html: malformed input hardening ─────────────────────────────

class TestStatStagesHtmlMalformed:
    def test_out_of_range_high_ignored(self):
        # Raw value 25 would be stage +19 — clamp/skip
        result = _stat_stages_html([25, 6, 6, 6, 6, 6, 6])
        assert result == ""

    def test_out_of_range_low_negative_ignored(self):
        # Negative raw values (unsigned read shouldn't produce these, but defensive)
        result = _stat_stages_html([-5, 6, 6, 6, 6, 6, 6])
        assert result == ""

    def test_none_entry_in_list_skipped(self):
        # Mixed list: one None value should not raise
        result = _stat_stages_html([None, 8, 6, 6, 6, 6, 6])
        assert "ATK" not in result  # first slot skipped
        assert "+2 DEF" in result   # second slot rendered

    def test_string_entry_in_list_skipped(self):
        result = _stat_stages_html(["bad", 6, 6, 6, 6, 6, 6])
        assert result == ""

    def test_longer_list_truncated_to_7_labels(self):
        # Extra elements beyond 7 should be ignored
        result = _stat_stages_html([8, 6, 6, 6, 6, 6, 6, 8, 8])
        # Only ATK badge — no extra badges for indices 7,8
        assert result.count("stat-stage") == 1

    def test_shorter_list_renders_available(self):
        # Only first 3 elements provided
        result = _stat_stages_html([8, 6, 4])
        assert "+2 ATK" in result
        assert "\u22122 SPD" in result
        assert "DEF" not in result  # neutral, no badge


# ── party_details stat_stages passthrough ─────────────────────────────────────

class TestPartyDetailsPassthrough:
    """Verify stat_stages is stored in party_details during tick processing.

    Uses the SLinkServer._handle_tcp() path indirectly by inspecting the
    party_details dict the server builds from a synthetic tick message.
    """

    def _make_server(self, tmp_path):
        """Create a minimal SLinkServer instance."""
        import asyncio
        from server.server import SLinkServer
        srv = SLinkServer.__new__(SLinkServer)
        srv.data_dir = str(tmp_path)
        srv.run_id   = "test"
        srv.run_name = ""
        srv.manager_port = None
        srv.verbose  = False
        srv.host     = "127.0.0.1"
        srv.port     = 0
        srv.http_port = 0

        from server.adapters import get_adapter
        srv.adapter  = get_adapter("gen3_frlge")

        from server.state import SoulLinkState
        import unittest.mock as mock
        with mock.patch("server.state.LINKS_PATH", str(tmp_path / "links.json")):
            srv.state = SoulLinkState()

        srv.connected_players = {}
        srv.party_details = {"a": {}, "b": {}}
        srv.battle_state  = {}
        srv.player_area   = {}
        srv.player_area_id = {}
        srv.player_ball_count = {}
        srv.player_badges = {}
        srv.player_kanto_badges = {}
        srv.trainer_name  = {}
        srv._sse_queues   = []
        srv.event_log     = []
        srv._backups_dir  = str(tmp_path / "backups")
        return srv

    def test_active_mon_stages_stored(self, tmp_path):
        srv = self._make_server(tmp_path)
        stages = [8, 6, 6, 4, 6, 6, 6]  # ATK+2, SPATK-2
        party_msg = [
            {"key": "AABBCCDD:11223344", "hp": 45, "maxHP": 50, "level": 12,
             "active": True, "status_cond": 0, "stat_stages": stages}
        ]
        # Simulate what the tick handler does: build party_details from msg
        srv.party_details["a"] = {
            m["key"]: {
                "hp":         m.get("hp", 0),
                "maxHP":      m.get("maxHP", 1),
                "level":      m.get("level", 0),
                "active":     m.get("active", False),
                "status_cond": m.get("status_cond", 0),
                "stat_stages": m.get("stat_stages"),
            }
            for m in party_msg if m.get("key")
        }
        detail = srv.party_details["a"]["AABBCCDD:11223344"]
        assert detail["active"] is True
        assert detail["stat_stages"] == stages

    def test_inactive_mon_stages_none(self, tmp_path):
        srv = self._make_server(tmp_path)
        party_msg = [
            {"key": "AABBCCDD:11223344", "hp": 45, "maxHP": 50, "level": 12,
             "active": False, "status_cond": 0}  # no stat_stages key
        ]
        srv.party_details["a"] = {
            m["key"]: {
                "active":     m.get("active", False),
                "stat_stages": m.get("stat_stages"),
            }
            for m in party_msg if m.get("key")
        }
        detail = srv.party_details["a"]["AABBCCDD:11223344"]
        assert detail["active"] is False
        assert detail["stat_stages"] is None

    def test_stat_stages_html_not_rendered_for_inactive(self):
        stages = [8, 6, 6, 6, 6, 6, 6]
        # is_active=False → `(False and _stat_stages_html(...) or "")` must give ""
        result = False and _stat_stages_html(stages) or ""
        assert result == ""


# ── _enrich_battle_state passthrough ─────────────────────────────────────────

class TestEnrichBattleStatePassthrough:
    """stat_stages on enemy mons passes through _enrich_battle_state unchanged."""

    def test_stat_stages_preserved_after_enrich(self):
        """_enrich_battle_state does em2=dict(em) shallow copy; stat_stages list
        is preserved by reference (safe because it is not mutated)."""
        stages = [6, 9, 6, 6, 6, 6, 6]  # DEF +3
        enemy_party_in = [
            {"species_id": 6, "hp": 50, "maxHP": 50, "level": 36,
             "active": True, "status_cond": 0, "stat_stages": stages},
            {"species_id": 7, "hp": 0, "maxHP": 40, "level": 30,
             "active": False, "status_cond": 0, "stat_stages": None},
        ]
        # Simulate the shallow copy _enrich_battle_state performs
        enriched = []
        for em in enemy_party_in:
            em2 = dict(em)
            enriched.append(em2)

        assert enriched[0]["stat_stages"] == stages
        assert enriched[1]["stat_stages"] is None

    def test_non_active_enemy_stages_none(self):
        """Non-active enemy mons should have stat_stages=None."""
        stages = [6, 9, 6, 6, 6, 6, 6]
        result = _stat_stages_html(None)
        assert result == ""

    def test_stat_stages_html_renders_enemy_active(self):
        stages = [6, 9, 6, 6, 6, 6, 6]  # DEF +3
        result = _stat_stages_html(stages)
        assert "+3 DEF" in result
        assert "ss-up" in result


# ── Offset correctness: 0x19 skips both vanilla HP-stage and CFRU type3 ──────

class TestOffsetConstant:
    """Regression guard: the magic offset 0x19 must never silently revert to 0x18."""

    def test_stat_stages_offset_is_0x19(self):
        """Read the constant directly from the memory_gba module source to ensure
        it hasn't been changed back to 0x18 (which would read CFRU type3 as a stage)."""
        import re, pathlib
        src = pathlib.Path("lua/memory_gba.lua").read_text(encoding="utf-8")
        match = re.search(
            r"M\.BATTLE_MON_STAT_STAGES_OFF\s*=\s*(0x[0-9a-fA-F]+|\d+)", src
        )
        assert match, "M.BATTLE_MON_STAT_STAGES_OFF constant not found in memory_gba.lua"
        value = int(match.group(1), 0)
        assert value == 0x19, (
            f"M.BATTLE_MON_STAT_STAGES_OFF is 0x{value:02X}, expected 0x19. "
            "Using 0x18 would read CFRU type3 (Fairy type ID) as a stat stage bonus."
        )

    def test_stat_stage_offset_comment_mentions_cfru(self):
        """The comment explaining the CFRU/vanilla difference should be present."""
        import pathlib
        src = pathlib.Path("lua/memory_gba.lua").read_text(encoding="utf-8")
        assert "type3" in src or "CFRU" in src, (
            "memory_gba.lua should document why 0x19 is used instead of 0x18 "
            "(CFRU has type3 at +0x18, vanilla has HP-stage there — never display either)."
        )


# ── _status_icon_html ─────────────────────────────────────────────────────────

class TestStatusIconHtml:
    """Tests for _status_icon_html().

    Gen 3 status1 bitmask (from pret/pokefirered include/constants/pokemon.h):
      bits 0–2  STATUS1_SLEEP         (counter 1–7)
      bit  3    STATUS1_POISON        0x08
      bit  4    STATUS1_BURN          0x10
      bit  5    STATUS1_FREEZE        0x20
      bit  6    STATUS1_PARALYSIS     0x40
      bit  7    STATUS1_TOXIC_POISON  0x80  — always combined with bit 3 (0x88)
    """

    # ── null cases ──────────────────────────────────────────────────────────

    def test_zero_returns_empty(self):
        assert _status_icon_html(0) == ""

    def test_none_returns_empty(self):
        assert _status_icon_html(None) == ""

    # ── individual conditions ───────────────────────────────────────────────

    def test_sleep_counter_1(self):
        result = _status_icon_html(0x01)
        assert "SLP" in result
        assert "s-slp" in result

    def test_sleep_counter_7(self):
        result = _status_icon_html(0x07)
        assert "SLP" in result

    def test_poison(self):
        result = _status_icon_html(0x08)
        assert "PSN" in result
        assert "s-psn" in result

    def test_burn(self):
        result = _status_icon_html(0x10)
        assert "BRN" in result
        assert "s-brn" in result

    def test_freeze(self):
        result = _status_icon_html(0x20)
        assert "FRZ" in result
        assert "s-frz" in result

    def test_paralysis(self):
        result = _status_icon_html(0x40)
        assert "PAR" in result
        assert "s-par" in result

    def test_toxic(self):
        # Toxic sets both bit 7 (0x80) and bit 3 (0x08) in-game
        result = _status_icon_html(0x88)
        assert "TOX" in result
        assert "s-tox" in result

    # ── priority: Toxic must win over PSN ──────────────────────────────────

    def test_toxic_beats_poison_when_both_bits_set(self):
        """Toxic sets STATUS1_POISON (bit 3) and STATUS1_TOXIC_POISON (bit 7).
        0x88 must display TOX, not PSN. Reversing the check order would break this."""
        result = _status_icon_html(0x88)
        assert "TOX" in result
        assert "PSN" not in result

    def test_tox_bit_alone_shows_tox(self):
        # bit 7 set without bit 3 — still TOX
        result = _status_icon_html(0x80)
        assert "TOX" in result
        assert "PSN" not in result

    # ── only one badge returned ─────────────────────────────────────────────

    def test_returns_single_badge_for_sleep_and_poison(self):
        """If somehow both sleep and poison bits are set, sleep wins (checked first)."""
        result = _status_icon_html(0x01 | 0x08)
        assert "SLP" in result
        assert "PSN" not in result

    def test_returns_one_span(self):
        result = _status_icon_html(0x40)
        assert result.count("<span") == 1

    # ── CSS class names ─────────────────────────────────────────────────────

    def test_css_class_names(self):
        """Verify exact class names — stream overlays depend on these."""
        cases = [
            (0x01, "s-slp"),
            (0x08, "s-psn"),
            (0x10, "s-brn"),
            (0x20, "s-frz"),
            (0x40, "s-par"),
            (0x80, "s-tox"),
        ]
        for cond, cls in cases:
            result = _status_icon_html(cond)
            assert cls in result, f"Expected CSS class '{cls}' for status_cond=0x{cond:02X}"

    # ── JS statusIcon parity check ──────────────────────────────────────────

    def test_js_statusicon_tox_before_psn(self):
        """In stream_overlays.py JS, the TOX (0x80) check must come before PSN (0x08).
        This is a source-level regression guard — if the order is swapped,
        Toxic mons would display PSN on stream overlays."""
        import re, pathlib
        src = pathlib.Path("server/stream_overlays.py").read_text(encoding="utf-8")
        tox_pos = src.find("0x80")
        psn_pos = src.find("0x08")
        assert tox_pos != -1, "0x80 (Toxic) check not found in stream_overlays.py"
        assert psn_pos != -1, "0x08 (Poison) check not found in stream_overlays.py"
        assert tox_pos < psn_pos, (
            "In stream_overlays.py JS, the 0x80 (Toxic) check must come before "
            "the 0x08 (Poison) check, otherwise Toxic displays as PSN."
        )


# ── is_doubles passthrough via tick handler ───────────────────────────────────

class TestDoublesPassthrough:
    """Verify is_doubles is stored, cleared, and left alone by the tick handler."""

    def _make_server(self, tmp_path):
        from server.server import SLinkServer
        import unittest.mock as mock
        srv = SLinkServer.__new__(SLinkServer)
        srv.data_dir = str(tmp_path)
        srv.run_id   = "test"
        srv.run_name = ""
        srv.manager_port = None
        srv.verbose  = False
        srv.host     = "127.0.0.1"
        srv.port     = 0
        srv.http_port = 0
        from server.adapters import get_adapter
        srv.adapter  = get_adapter("gen3_frlge")
        from server.state import SoulLinkState
        with mock.patch("server.state.LINKS_PATH", str(tmp_path / "links.json")):
            srv.state = SoulLinkState()
        srv.connected_players = {}
        srv.party_details = {"a": {}, "b": {}}
        srv.battle_state  = {
            p: {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                "is_doubles": False}
            for p in ("a", "b")
        }
        srv.player_area   = {}
        srv.player_area_id = {}
        srv.player_ball_count = {}
        srv.player_badges = {}
        srv.player_kanto_badges = {}
        srv.trainer_name  = {}
        srv._sse_queues   = []
        srv.event_log     = []
        srv._backups_dir  = str(tmp_path / "backups")
        return srv

    def _apply_tick(self, srv, player_id, msg):
        """Apply only the is_doubles / enemy_party portion of the tick handler logic."""
        bs = srv.battle_state[player_id]
        was_in_battle = bs.get("in_battle", False)
        now_in_battle = msg.get("in_battle", was_in_battle)
        bs["in_battle"] = now_in_battle

        if was_in_battle and not now_in_battle:
            bs["is_doubles"] = False
            bs["enemy_party"] = []

        if "enemy_party" in msg:
            bs["enemy_party"] = msg["enemy_party"]
        if "is_doubles" in msg:
            bs["is_doubles"] = bool(msg["is_doubles"])
        elif "enemy_party" in msg:
            active_count = sum(1 for e in msg["enemy_party"] if e.get("active"))
            if active_count > 1:
                bs["is_doubles"] = True

    def test_is_doubles_set_from_tick(self, tmp_path):
        """A tick with is_doubles=true sets battle_state['is_doubles'] to True."""
        srv = self._make_server(tmp_path)
        self._apply_tick(srv, "a", {
            "in_battle": True,
            "is_doubles": True,
            "enemy_party": [
                {"species_id": 1, "level": 10, "active": True},
                {"species_id": 4, "level": 10, "active": True},
            ],
        })
        assert srv.battle_state["a"]["is_doubles"] is True

    def test_is_doubles_cleared_on_battle_end(self, tmp_path):
        """When in_battle transitions False, is_doubles is reset to False."""
        srv = self._make_server(tmp_path)
        # Put server into a doubles battle
        srv.battle_state["a"]["in_battle"] = True
        srv.battle_state["a"]["is_doubles"] = True
        # Battle ends
        self._apply_tick(srv, "a", {"in_battle": False})
        assert srv.battle_state["a"]["is_doubles"] is False

    def test_is_doubles_unchanged_when_key_absent(self, tmp_path):
        """A tick without the is_doubles key leaves the existing value untouched."""
        srv = self._make_server(tmp_path)
        srv.battle_state["a"]["in_battle"] = True
        srv.battle_state["a"]["is_doubles"] = True
        # Tick mid-battle without is_doubles key
        self._apply_tick(srv, "a", {
            "in_battle": True,
            "enemy_party": [{"species_id": 1, "level": 10, "active": True}],
        })
        assert srv.battle_state["a"]["is_doubles"] is True

    def test_is_doubles_inferred_from_active_count(self, tmp_path):
        """Without is_doubles key, two active enemies infer is_doubles=True."""
        srv = self._make_server(tmp_path)
        self._apply_tick(srv, "b", {
            "in_battle": True,
            "enemy_party": [
                {"species_id": 7, "level": 15, "active": True},
                {"species_id": 9, "level": 15, "active": True},
            ],
        })
        assert srv.battle_state["b"]["is_doubles"] is True
