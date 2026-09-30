"""Tests for the Gen 2 adapter, Gen2GSCAdapter (Crystal, Gold and Silver).

REPLACE path of docs/gen2/PLAN.md §4 (P3b.6): this file used to test the legacy
Gen2CrystalAdapter, removed with the rest of the legacy Gen 2 runtime at P3b.8 (O-25 refused
Archipelago Crystal, its last route). Only the gen2_gsc classes remain.
"""

import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def gsc_adapter(request):
    from server.adapters.gen2_gsc import Gen2GSCAdapter

    return Gen2GSCAdapter(request.param)


def _gsc_blob():
    raw = bytearray(70)
    raw[0:8] = bytes([25, 143, 33, 45, 0, 0, 0x12, 0x34])
    raw[21:23] = bytes.fromhex("2aaa")
    raw[23:27] = bytes([35, 40, 0, 0])
    raw[31] = 20
    raw[34:38] = bytes.fromhex("00200030")
    raw[38:48] = bytes.fromhex("00200020002000200020")
    raw[48:] = bytes([0x80, 0x50] + [0] * 9 + [0x81, 0x50] + [0] * 9)
    return bytes(raw)


class TestGen2GSCAdapter:
    @pytest.mark.parametrize("kind,slot_count", [("grass", 7), ("water", 3)])
    def test_normal_and_swarm_tables_remain_alternatives(self, gsc_adapter, kind, slot_count):
        """Actual normal/swarm rows share one area but each distribution totals 100%."""
        path = (Path(__file__).resolve().parents[2] / "data/games"
                / f"gen2_{gsc_adapter.title}" / "encounter_tables.json")
        pack = json.loads(path.read_text("utf-8"))
        by_map_time = {}
        for row in pack["wild"][kind]:
            key = row["map_group"], row["map_number"], row["time"]
            by_map_time.setdefault(key, []).append(row)
        alternative_groups = 0
        for (group, number, daytime), alternatives in by_map_time.items():
            area = pack["map_areas"][str(group * 256 + number)]
            source_names = {row["table"] for row in alternatives}
            projected = {
                method: rows for method, rows in gsc_adapter.encounter_table(area).items()
                if rows and rows[0].get("source_table") in source_names
                and rows[0].get("map_group") == group and rows[0].get("map_number") == number
                and rows[0].get("time") == daytime
            }
            # This is the reported symptom: the old projection has 14 grass or
            # 6 water slots and sums to 200 after merging two alternatives.
            assert all(len(rows) == slot_count for rows in projected.values())
            assert all(sum(row["rate"] for row in rows) == 100 for rows in projected.values())
            assert len(projected) == len(alternatives)
            for source in alternatives:
                selected = [rows for rows in projected.values()
                            if {row["source_table"] for row in rows} == {source["table"]}]
                assert len(selected) == 1
                assert [row["species_id"] for row in selected[0]] == [row["species"] for row in source["slots"]]
                assert [row["min_level"] for row in selected[0]] == [row["level"] for row in source["slots"]]
                assert [row["slot"] for row in selected[0]] == list(range(slot_count))
            if len(alternatives) > 1:
                alternative_groups += 1
                assert any("Swarm" in method for method in projected)
                assert any("Normal" in method for method in projected)
            assert gsc_adapter.encounter_table(area + "_swarm") is None
        # Crystal deliberately has no water swarm table; still exercise every
        # actual normal-water distribution there, without reporting a skip.
        assert alternative_groups > 0 if kind == "grass" or gsc_adapter.title != "crystal" else alternative_groups == 0

    def test_selected_pack_and_capability_refusal(self, gsc_adapter):
        assert gsc_adapter.game_id == "gen2_gsc"
        assert gsc_adapter.title in {"crystal", "gold", "silver"}
        assert gsc_adapter.party_blob_size() == 70
        assert gsc_adapter.mons_per_box == 20
        assert gsc_adapter.memorial_box_index == 13
        assert not gsc_adapter.supports_abilities()
        assert not gsc_adapter.supports_info_panel()
        assert not gsc_adapter.native_trade_ui()
        assert gsc_adapter.supports_explode_mode()          # W-3, owner 2026-09-26 (Gen 1 parity)
        assert gsc_adapter.info_panel_width() == 0
        # W-4: class * 256 + instance for RIVAL1 (9) x 15 and RIVAL2 ($2A) x 6 (trainer_constants.asm)
        assert gsc_adapter.rival_trainer_ids() == ({9 * 256 + i for i in range(1, 16)}
                                                   | {0x2A * 256 + i for i in range(1, 7)})
        gsc_adapter.set_artifact_kind("clean")
        with pytest.raises(ValueError):
            gsc_adapter.set_artifact_kind("named")
        assert gsc_adapter.pairing_kind("named") == "named"

    def test_raw_ratio_sentinels_and_dv_boundaries(self, gsc_adapter):
        # Actual generated source bytes: 254 is female, 255 is genderless.
        for attack in range(16):
            for speed in range(16):
                dvs = f"{attack:X}A{speed:X}A"
                assert gsc_adapter.gender_from_key(f"{dvs}:1234:F1", 241) == "female"
                assert gsc_adapter.gender_from_key(f"{dvs}:1234:51", 81) == "genderless"
                assert gsc_adapter.gender_from_key(f"{dvs}:1234:80", 128) == "male"
                assert gsc_adapter.gender_from_key(f"{dvs}:1234:98", 152) == (
                    "female" if attack * 16 + speed <= 31 else "male"
                )
        assert gsc_adapter.gender_from_key("7AAA:1234:19", 25) == "female"
        assert gsc_adapter.gender_from_key("8AAA:1234:19", 25) == "male"
        assert gsc_adapter.gender_from_key("AAAA:1234:19", 152) == ""

    def test_dv_shiny_mask_and_strict_keys(self, gsc_adapter):
        for attack in range(16):
            assert gsc_adapter.is_shiny(f"{attack:X}AAA:1234:19") is bool(attack & 2)
        for key in ("AAAA:1234:FD", "AAAA:1234:00", "AAAA:1234:FC", "AAAA:1234:FF",
                    "AAAA:1234:1", "AAAA:1234:19\n", "AAAA:1234", None):
            assert not gsc_adapter.is_valid_mon_key(key)
            assert not gsc_adapter.is_shiny(key)
            assert gsc_adapter.parse_ot_id(key) == ""
        assert gsc_adapter.is_valid_mon_key("2aaa:abcd:fb")
        assert gsc_adapter.parse_ot_id("2aaa:abcd:fb") == "ABCD"
        assert not gsc_adapter.is_shiny("AA9A:1234:19")

    def test_species_evolution_move_and_held_item_facts(self, gsc_adapter):
        assert gsc_adapter.species_name(152) == "Chikorita"
        assert gsc_adapter.species_types(81) == (23, 9)
        assert gsc_adapter.species_types(197) == (27, 27)
        assert gsc_adapter.to_national_dex(253) == 0
        assert gsc_adapter.species_types(253) is None
        assert gsc_adapter.evo_family(25) == gsc_adapter.evo_family(172)
        assert gsc_adapter.evo_family(133) == gsc_adapter.evo_family(197)
        assert gsc_adapter.evo_family(106) == gsc_adapter.evo_family(237)
        assert gsc_adapter.move_data(44)["type_name"] == "Dark"
        assert gsc_adapter.move_data(44)["split"] == 1
        assert gsc_adapter.move_data(14)["split"] == 2
        assert gsc_adapter.move_data(252) is None
        assert gsc_adapter.is_valid_held_item(0)
        assert gsc_adapter.is_valid_held_item(143)
        for item in (6, 175, 158, 255, 256, -1, True):
            assert not gsc_adapter.is_valid_held_item(item)

    def test_gsc_context_gender_type_area_form_and_trainer_facts(self, gsc_adapter):
        """OMP census gap: these were exercised on the legacy Gen2CrystalAdapter but
        never on gen2_gsc, the adapter every Crystal/Gold/Silver run actually uses."""
        assert gsc_adapter.gender_symbol("male") == "♂"
        assert gsc_adapter.gender_symbol("female") == "♀"
        assert gsc_adapter.gender_symbol("genderless") == ""
        assert gsc_adapter.gender_symbol("unknown") == ""
        assert gsc_adapter.type_name(0) == "Normal"
        assert gsc_adapter.type_name(27) == "Dark"
        assert gsc_adapter.type_name(9) == "Steel"
        assert gsc_adapter.type_name(999) == "Type #999"
        assert gsc_adapter.area_display_name("route_29") == "Route 29"
        assert gsc_adapter.area_display_name("gift_daycare") == "Egg Hatch"
        assert gsc_adapter.area_display_name(None) == ""
        assert gsc_adapter.form_sprite_id(152) is None
        assert gsc_adapter.form_sprite_id(201) is None  # Unown forms are cosmetic
        # Randy, the Route 35 guard, is a named source NPC (gifts.json
        # named_trainer=true for his Spearow gift) -- but a gift-giver carries
        # no (class, instance) trainer id, so gsc still answers ("", "").
        assert gsc_adapter.trainer_info(0) == ("", "")
        assert gsc_adapter.trainer_info(999) == ("", "")     # Bugsy (3) has no instance 231
        # the packed id: class * 256 + instance (lua/gen2/client.lua trainer_id_of)
        assert gsc_adapter.trainer_info(1 * 256 + 1) == ("Falkner", "Leader")
        assert gsc_adapter.trainer_info(9 * 256 + 1) == ("", "Rival")   # the player names him: "?" in the pack
        assert gsc_adapter.trainer_info(1) == ("", "")         # class 0 is no trainer

    # data/items/mail_items.asm:1-12 (MailItems, identical in both pins; read by
    # ItemIsMail, C engine/pokemon/mail_2.asm:941-945, G :922-926). Ids from
    # constants/item_constants.asm. LITEBLUEMAIL/PORTRAITMAIL lack an _MAIL suffix.
    MAIL_ITEMS = (0x9E, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD)

    def test_every_source_mail_item_is_refused_as_held_item(self, gsc_adapter):
        """O-14: held items travel with a traded mon, mail does not."""
        pack = json.loads((Path(__file__).resolve().parents[2] / "data/games"
                           / f"gen2_{gsc_adapter.title}" / "items.json").read_text("utf-8"))
        assert pack["mail_ids"] == list(self.MAIL_ITEMS)
        for item in self.MAIL_ITEMS:
            assert not gsc_adapter.is_valid_held_item(item), hex(item)
            raw = bytearray(_gsc_blob())
            raw[1] = item
            assert not gsc_adapter.validate_party_blob(bytes(raw), species_marker=25), hex(item)
        # Non-mail control: BERRY (0xAD) and the 0x8F control still pass.
        assert gsc_adapter.is_valid_held_item(0xAD) and gsc_adapter.is_valid_held_item(0x8F)
        assert gsc_adapter.validate_party_blob(_gsc_blob(), species_marker=25)

    def test_mail_gate_reads_the_pack_flag_not_the_constant_name(self, tmp_path):
        from server.adapters.gen2_gsc import Gen2GSCAdapter

        source = Path(__file__).resolve().parents[2] / "data/games/gen2_crystal"
        shutil.copytree(source, tmp_path / "gen2_crystal")
        path = tmp_path / "gen2_crystal/items.json"
        data = json.loads(path.read_text("utf-8"))
        data["items"]["173"]["mail"] = True  # BERRY, flagged as mail.
        data["items"]["182"]["constant"] = "LITEBLUE_MAIL"  # suffix alone must not matter
        data["items"]["182"]["mail"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        adapter = Gen2GSCAdapter("crystal", data_root=tmp_path)
        assert not adapter.is_valid_held_item(173)
        assert adapter.is_valid_held_item(182)
        del data["items"]["173"]["mail"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError):
            Gen2GSCAdapter("crystal", data_root=tmp_path)

    def test_blob_preserves_identity_names_and_held_item(self, gsc_adapter):
        raw = _gsc_blob()
        assert gsc_adapter.validate_party_blob(raw, key="2AAA:1234:19", species_marker=25)
        assert gsc_adapter.validate_party_blob(raw.hex(), species_marker=25)
        assert not gsc_adapter.validate_party_blob(raw)  # EGG state is absent from the blob.
        mon = gsc_adapter.decode_party_blob(raw, species_marker=25)
        assert mon["held_item"] == 143
        assert mon["key"] == "2AAA:1234:19"
        assert mon["ot_raw_hex"] == raw[48:59].hex()
        assert mon["nickname_raw_hex"] == raw[59:70].hex()
        assert not gsc_adapter.validate_party_blob(raw, key="2AAA:1234:1A", species_marker=25)
        assert not gsc_adapter.validate_party_blob(raw[:-1], species_marker=25)
        assert not gsc_adapter.validate_party_blob(raw + b"\0", species_marker=25)
        for offset, value in ((0, 253), (1, 6), (1, 158), (2, 252), (31, 0)):
            bad = bytearray(raw)
            bad[offset] = value
            assert not gsc_adapter.validate_party_blob(bytes(bad), species_marker=25)
        egg = gsc_adapter.decode_party_blob(raw, species_marker=253)
        assert egg["is_egg"] and egg["species_id"] == 25

    def test_acquisition_namespaces_require_explicit_origin(self, gsc_adapter):
        assert gsc_adapter.gift_link_area("route_29", acquisition="egg_hatch", species_id=25) == "gift_daycare"
        assert gsc_adapter.gift_link_area("route_29", acquisition="roamer", species_id=243) == "legend_243"
        assert gsc_adapter.gift_link_area("national_park", acquisition="contest", species_id=123) == "national_park_contest"
        assert gsc_adapter.gift_link_area("legend_243") == "legend_243"
        assert gsc_adapter.gift_link_area("national_park_contest") == "national_park_contest"
        assert gsc_adapter.is_gift_area("legend_243")
        assert gsc_adapter.is_gift_area("gift_daycare")
        assert not gsc_adapter.is_gift_area("route_34")
        assert not gsc_adapter.is_gift_area("goldenrod_city")
        assert not gsc_adapter.is_gift_area("legend_25")
        assert not gsc_adapter.is_gift_area("legend_0243")
        assert not gsc_adapter.is_gift_area("gift_")
        assert gsc_adapter.is_gift_area("static_lake_of_rage_130")  # 09:06 Red Gyarados.
        # The retired group*256+number shape (2310 = 09:06) is not a member any more.
        assert not gsc_adapter.is_gift_area("static_2310_130")
        assert not gsc_adapter.is_gift_area("static_lake_of_rage_25")
        # Membership is per title (gen2-static-canon, O-16): Crystal's Celebi row is not a
        # Gold/Silver static even though the id shape is canonical everywhere.
        if gsc_adapter.title == "crystal":
            assert gsc_adapter.is_gift_area("static_ilex_forest_251")
        else:
            assert not gsc_adapter.is_gift_area("static_ilex_forest_251")
        assert gsc_adapter.is_daycare_area("gift_daycare")
        assert not gsc_adapter.is_egg_pickup_area("egg_route_30")
        with pytest.raises(ValueError):
            gsc_adapter.gift_link_area("route_30", acquisition="egg_pickup", species_id=175)
        with pytest.raises(ValueError):
            gsc_adapter.gift_link_area("route_29", acquisition="roamer", species_id=25)
        if gsc_adapter.title == "crystal":
            with pytest.raises(ValueError):
                gsc_adapter.gift_link_area("tin_tower", acquisition="roamer", species_id=245)
        else:
            assert gsc_adapter.gift_link_area("route_29", acquisition="roamer", species_id=245) == "legend_245"

    def test_crystal_tin_tower_suicune_static_resolves_as_a_legend(self, gsc_adapter):
        """O-21 (SOURCE; runtime capture OPEN, N12b): like the roaming Suicune, the Tin Tower static is legend_245
        and never locks tin_tower as a consumed ordinary-wild capture area."""
        path = (Path(__file__).resolve().parents[2] / "data/games"
                / f"gen2_{gsc_adapter.title}" / "static_encounters.json")
        statics = json.loads(path.read_text("utf-8"))["encounters"]
        suicune = [row for row in statics if row["species"] == 245]
        if gsc_adapter.title != "crystal":
            assert suicune == []  # Gold/Silver: Suicune roams, it has no static row.
            return
        row = next(iter(suicune))
        assert row["area_id"] == "legend_245"
        assert row["static_area_id"] == "legend_245"  # the pack's own published id (O-16/O-21)
        assert gsc_adapter.is_gift_area("legend_245")
        assert gsc_adapter.gift_link_area("legend_245") == "legend_245"
        assert gsc_adapter.area_display_name("legend_245") == "Suicune"

    def test_presentation_keeps_source_map_time_and_slot_rows(self, gsc_adapter):
        table = gsc_adapter.encounter_table("route_29")
        assert {"Morn", "Day", "Nite"} <= set(table)
        assert any(row["species_id"] == 161 for row in table["Morn"])
        assert any(row["species_id"] == 163 for row in table["Nite"])
        assert all("map_group" in row and "slot" in row for row in table["Morn"])
        assert gsc_adapter.encounter_table("unmapped_place") is None
        assert gsc_adapter.gym_badge_slugs("")[4][1] == "Mineral Badge"
        assert gsc_adapter.gym_badge_slugs("")[5][1] == "Storm Badge"
        assert gsc_adapter.status_token(0x08) == "PSN"
        assert gsc_adapter.ability_name(1) == ""
        assert gsc_adapter.sprite_html(253) == ""
        for payload in ({}, {"schema": "gen2-rom-tables-v1"}):
            with pytest.raises(ValueError):
                gsc_adapter.rom_content_fingerprint(payload)


    def test_fishing_rows_are_gated_on_reachable_water(self, gsc_adapter):
        """OMP N7 / review F3: rod rows exist only where the rod can face water."""
        pack = json.loads((Path(__file__).resolve().parents[2] / "data/games"
                           / f"gen2_{gsc_adapter.title}" / "area_map.json").read_text("utf-8"))
        tables = {area: gsc_adapter.encounter_table(area) or {}
                  for area in ("new_bark_town", "route_29", "route_16", "union_cave")}
        rods = {label: rows for table in tables.values()
                for label, rows in table.items() if "Rod" in label}
        assert rods, "expected rod rows where the rod can reach water"
        for rows in rods.values():
            for row in rows:
                source = pack[str(row["map_group"] * 256 + row["map_number"])]
                assert source["fishing_water"] is True
                assert source["fishing_group"] != 0
                assert row["map_association"] == "UNQUALIFIED"
        # The review's example is gone: no rod row comes from a dry indoor map.
        assert not [label for label in rods if "(ElmsLab)" in label]
        # New Bark Town's six maps each used to carry six rod labels; only the town has water.
        assert len([label for label in tables["new_bark_town"] if "Rod" in label]) == 6
        # A dry route and a walled-water route keep their other rows and gain no rod rows.
        for area in ("route_29", "route_16"):
            assert tables[area] and not [label for label in tables[area] if "Rod" in label]
        assert all("map_association" not in row for row in tables["route_29"]["Morn"])

    def test_disabled_tree_sets_present_no_headbutt(self, gsc_adapter):
        """G/S GetTreeMons refuses UNUSED/CITY (pokegold engine/events/treemons.asm:98-102)."""
        for area in ("new_bark_town", "violet_city", "ecruteak_city", "mahogany_town", "blackthorn_city"):
            table = gsc_adapter.encounter_table(area) or {}
            assert not [label for label in table if label.startswith("Headbutt")], (area, sorted(table))
        # Enabled sets are still presented on every title.
        assert {"Headbutt Common", "Headbutt Rare"} <= set(gsc_adapter.encounter_table("azalea_town"))


class TestGen2GSCPackRefusal:
    def test_title_selection_is_explicit(self):
        from server.adapters.gen2_gsc import Gen2GSCAdapter

        for title in ("crystal11", "ap", "unknown", None, "../crystal"):
            with pytest.raises(ValueError):
                Gen2GSCAdapter(title)

    @pytest.mark.parametrize("corruption", ["title", "missing_title", "source", "schema", "missing_species", "ratio"])
    def test_mismatched_or_malformed_pack_is_refused(self, tmp_path, corruption):
        from server.adapters.gen2_gsc import Gen2GSCAdapter

        source = Path(__file__).resolve().parents[2] / "data/games/gen2_crystal"
        target = tmp_path / "gen2_crystal"
        shutil.copytree(source, target)
        path = target / "species_index.json"
        data = json.loads(path.read_text("utf-8"))
        if corruption == "title":
            data["title"] = "gold"
        elif corruption == "missing_title":
            del data["title"]
        elif corruption == "source":
            data["source"]["rom_sha1"] = "0" * 40
        elif corruption == "schema":
            data["schema"] = "gen1-species-index-v1"
        elif corruption == "missing_species":
            del data["species"]["81"]
        else:
            data["species"]["81"]["gender_ratio"] = 256
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError):
            Gen2GSCAdapter("crystal", data_root=tmp_path)

def test_sprites_use_the_transparent_folder(gsc_adapter):
    # the bare gold/ and silver/ PNGs have an opaque white background
    assert gsc_adapter.sprite_src(25).endswith(f"/generation-ii/{gsc_adapter.title}/transparent/25.png")


def test_sprite_img_is_decorative(gsc_adapter):
    """The name sits beside every sprite, so the image is alt="" (as Gen 1's and Gen 3's are), not unlabelled."""
    assert ' alt="" ' in gsc_adapter.sprite_html(25)


def test_display_names_keep_acronyms_and_possessives(gsc_adapter):
    assert (gsc_adapter.item_name(82), gsc_adapter.item_name(26), gsc_adapter.item_name(191)) == ("King's Rock", "HP Up", "TM01")
